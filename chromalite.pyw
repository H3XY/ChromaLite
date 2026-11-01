"""
ChromaLite — a lightweight lighting controller for Razer Chroma devices.

Talks directly to the Razer Chroma SDK REST server (localhost:54235) that
ships with Synapse, so you don't need the Synapse UI at all. Also plays
Synapse 3 Chroma Studio effect files (.ChromaEffects), remapped onto
whatever devices you have. Standard library only. Run with:
    pyw chromalite.pyw          (add --minimized to start minimized)
"""
import colorsys
import ctypes
import http.client
import json
import math
import os
import random
import shutil
import sys
import threading
import time
import tkinter as tk
from tkinter import colorchooser, filedialog, ttk
from urllib.parse import urlparse

import chroma_effects as ce

APP_NAME = "ChromaLite"
SDK_HOST, SDK_PORT = "localhost", 54235
FPS = 30
SMOOTHING_S = 0.06  # time constant of the per-LED ease between frames
APPDATA = os.environ.get("APPDATA", os.path.expanduser("~"))
CONFIG_DIR = os.path.join(APPDATA, "ChromaLite")
LEGACY_CONFIG_DIR = os.path.join(APPDATA, "RazerLighting")  # pre-rename location
CONFIG_PATH = os.path.join(CONFIG_DIR, "settings.json")
EFFECTS_DIR = os.path.join(CONFIG_DIR, "effects")
EFFECT_EXT = ".ChromaEffects"
STARTUP_VBS = os.path.join(APPDATA, r"Microsoft\Windows\Start Menu\Programs\Startup\ChromaLite.vbs")
FROZEN = getattr(sys, "frozen", False)  # running as the PyInstaller .exe
BASE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
ICON_PATH = os.path.join(BASE_DIR, "assets", "chromalite.ico")

FILE_PREFIX = "File: "
EFFECTS = ["Static", "Breathing", "Duo Pulse", "Spectrum Cycle", "Rainbow Wave", "Gradient Wave", "Starlight", "Off"]

PRESETS = ["#FF0000", "#FF6A00", "#FFD000", "#00FF40", "#00FFD5", "#0088FF", "#3A00FF", "#B000FF", "#FF00A0", "#FFFFFF"]

DEFAULTS = {
    "effect": "Rainbow Wave",
    "color1": "#00FF40",
    "color2": "#3A00FF",
    "brightness": 100,
    "speed": 5,
    "devices": {"keyboard": True, "mouse": True, "mousepad": True},
}


# ---------------------------------------------------------------- helpers
def hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def rgb_to_hex(c):
    return "#%02X%02X%02X" % tuple(max(0, min(255, int(v))) for v in c)


def mix(a, b, k):
    return tuple(a[i] + (b[i] - a[i]) * k for i in range(3))


def hue(h):
    return tuple(v * 255 for v in colorsys.hsv_to_rgb(h % 1.0, 1.0, 1.0))


def effect_files():
    try:
        names = [f[:-len(EFFECT_EXT)] for f in os.listdir(EFFECTS_DIR) if f.lower().endswith(EFFECT_EXT.lower())]
    except OSError:
        return []
    return sorted(names, key=str.lower)


def effect_path(name):
    return os.path.join(EFFECTS_DIR, name + EFFECT_EXT)


def load_settings():
    s = json.loads(json.dumps(DEFAULTS))
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            saved = json.load(f)
        s.update({k: v for k, v in saved.items() if k in s and k != "devices"})
        s["devices"].update(saved.get("devices", {}))
    except (OSError, ValueError):
        pass
    eff = s["effect"]
    if eff not in EFFECTS and not (eff.startswith(FILE_PREFIX) and os.path.exists(effect_path(eff[len(FILE_PREFIX):]))):
        s["effect"] = DEFAULTS["effect"]
    return s


def save_settings(s):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(s, f, indent=2)
    except OSError:
        pass


# ---------------------------------------------------------------- Chroma SDK
class ChromaSession:
    """One registered app session with the Chroma SDK REST server."""

    def __init__(self):
        self.base = None  # (host, port, path)
        self.conn = None
        self.last_call = 0.0

    def _request(self, host, port, method, path, body=None):
        if self.conn is None or (self.conn.host, self.conn.port) != (host, port):
            self.close_conn()
            self.conn = http.client.HTTPConnection(host, port, timeout=3)
        data = json.dumps(body) if body is not None else None
        try:
            self.conn.request(method, path, body=data, headers={"Content-Type": "application/json"})
            resp = self.conn.getresponse()
            raw = resp.read()
        except Exception:
            self.close_conn()
            raise
        self.last_call = time.time()
        return json.loads(raw) if raw else {}

    def close_conn(self):
        if self.conn is not None:
            try:
                self.conn.close()
            except Exception:
                pass
            self.conn = None

    def connect(self, devices):
        res = self._request(SDK_HOST, SDK_PORT, "POST", "/razer/chromasdk", {
            "title": APP_NAME,
            "description": "Lightweight lighting controller",
            "author": {"name": "local", "contact": "local"},
            "device_supported": list(devices),
            "category": "application",
        })
        u = urlparse(res["uri"])
        self.base = (u.hostname, u.port, u.path.rstrip("/"))
        time.sleep(1.0)  # the SDK needs a moment before it accepts effects

    def put(self, device, payload):
        host, port, path = self.base
        return self._request(host, port, "PUT", f"{path}/{device}", payload)

    def heartbeat(self):
        host, port, path = self.base
        self._request(host, port, "PUT", f"{path}/heartbeat")

    def disconnect(self):
        if self.base:
            host, port, path = self.base
            try:
                self._request(host, port, "DELETE", path)
            except Exception:
                pass
        self.base = None
        self.close_conn()


# ---------------------------------------------------------------- renderer
class Engine(threading.Thread):
    def __init__(self, settings):
        super().__init__(daemon=True)
        self.settings = settings
        self.lock = threading.Lock()
        self.stop_evt = threading.Event()
        self.dirty = threading.Event()
        self.status = "Connecting…"
        self.devices = ce.make_devices()
        self.preview = [(0, 0, 0)] * 22
        self.stars = {k: [[0.0, (0, 0, 0)] for _ in d.leds] for k, d in self.devices.items()}
        self.file_renderer, self.file_error, self.file_time = None, "", 0.0
        self.keys, self.audio = None, None
        self.smoothed = {}

    def smooth(self, kind, colors, dt):
        """Ease each LED toward its new color so single-frame jumps can't flash.
        Also gives a quick crossfade when switching effects."""
        prev = self.smoothed.get(kind)
        if prev is None or len(prev) != len(colors):
            self.smoothed[kind] = [tuple(c) for c in colors]
            return colors
        k = 1 - math.exp(-dt / SMOOTHING_S)
        out = [(p[0] + (c[0] - p[0]) * k, p[1] + (c[1] - p[1]) * k, p[2] + (c[2] - p[2]) * k)
               for p, c in zip(prev, colors)]
        self.smoothed[kind] = out
        return out

    def update(self, **changes):
        with self.lock:
            self.settings.update(changes)
        self.dirty.set()

    def snapshot(self):
        with self.lock:
            return json.loads(json.dumps(self.settings))

    # built-in effects -------------------------------------------------
    def builtin_colors(self, kind, s, t, dt):
        eff, speed = s["effect"], s["speed"]
        c1, c2 = hex_to_rgb(s["color1"]), hex_to_rgb(s["color2"])
        leds = self.devices[kind].leds
        n = len(leds)
        pos = [l.v if kind == "mouse" else l.u for l in leds]  # mouse LEDs run top to bottom
        if eff == "Breathing":
            k = (1 - math.cos(2 * math.pi * t * 0.07 * speed)) / 2
            return [mix((0, 0, 0), c1, k)] * n
        if eff == "Duo Pulse":
            k = (1 - math.cos(2 * math.pi * t * 0.07 * speed)) / 2
            return [mix(c1, c2, k)] * n
        if eff == "Spectrum Cycle":
            return [hue(t * 0.03 * speed)] * n
        if eff == "Rainbow Wave":
            return [hue(p * 0.8 - t * 0.06 * speed) for p in pos]
        if eff == "Gradient Wave":
            return [mix(c1, c2, (math.sin(2 * math.pi * (p - t * 0.06 * speed)) + 1) / 2) for p in pos]
        if eff == "Starlight":
            chance = 0.004 * speed * (dt * FPS)
            base = mix((0, 0, 0), c2, 0.15)
            out = []
            for st in self.stars[kind]:
                if st[0] <= 0 and random.random() < chance:
                    st[0], st[1] = 1.0, (c1 if random.random() < 0.5 else c2)
                st[0] = max(0.0, st[0] - dt * (0.25 + 0.08 * speed))
                out.append(mix(base, st[1], math.sin(math.pi * st[0])))  # fade in, then out
            return out
        return [c1] * n  # Static

    # file effects -----------------------------------------------------
    def file_frame(self, name, s, dt):
        r = self.file_renderer
        if r is None or r.name != name:
            try:
                r = self.file_renderer = ce.load(effect_path(name), self.devices)
                self.file_error, self.file_time = "", 0.0
                if r.unsupported:
                    self.file_error = "Skipped unsupported layers: " + ", ".join(r.unsupported)
            except Exception as e:
                self.file_renderer, self.file_error = None, f"Couldn't load {name}: {e}"
                return None
        if r.needs_keys and self.keys is None:
            self.keys = ce.KeyWatcher()
        if r.needs_audio and self.audio is None:
            self.audio = ce.AudioMeter()
        k = s["speed"] / 5
        self.file_time += dt * k
        presses = self.keys.poll() if r.needs_keys else ()
        level = self.audio.level() if r.needs_audio else 0.0
        return r.render(self.file_time, dt * k, presses, level)

    def run(self):
        sess = ChromaSession()
        t0 = last = time.time()
        last_static_push = 0.0
        while not self.stop_evt.is_set():
            if sess.base is None:
                try:
                    sess.connect(self.devices)
                    self.status = "Connected to Chroma SDK"
                    last_static_push = 0.0
                except Exception:
                    self.status = "Chroma SDK not reachable — retrying…"
                    sess.base = None
                    self.stop_evt.wait(3)
                    continue
            now = time.time()
            dt, last = min(0.25, now - last), now
            s = self.snapshot()
            bright = s["brightness"] / 100.0
            eff = s["effect"]
            is_file = eff.startswith(FILE_PREFIX)
            animated = eff not in ("Static", "Off")
            try:
                force = self.dirty.is_set() or now - last_static_push > 5
                if animated or force:
                    self.dirty.clear()
                    last_static_push = now
                    frame = self.file_frame(eff[len(FILE_PREFIX):], s, dt) if is_file else None
                    if is_file:
                        self.status = self.file_error or f"Playing {eff[len(FILE_PREFIX):]}"
                    elif self.status.startswith(("Playing", "Couldn't", "Skipped")):
                        self.status = "Connected to Chroma SDK"
                    for kind, dev in self.devices.items():
                        if not s["devices"].get(kind, True) or eff == "Off" or (is_file and frame is None):
                            sess.put(kind, {"effect": "CHROMA_NONE"})
                            if kind == "keyboard":
                                self.preview = [(0, 0, 0)] * 22
                            continue
                        if eff == "Static":
                            sess.put(kind, {"effect": "CHROMA_STATIC", "param": {"color": ce.to_bgr(hex_to_rgb(s["color1"]), bright)}})
                            colors = [hex_to_rgb(s["color1"])] * len(dev.leds)
                            self.smoothed[kind] = colors
                        else:
                            colors = frame[kind] if is_file else self.builtin_colors(kind, s, now - t0, dt)
                            colors = self.smooth(kind, colors, dt)
                            sess.put(kind, dev.payload(colors, bright))
                        if kind == "keyboard":
                            self.preview = [tuple(v * bright for v in colors[2 * 22 + c]) for c in range(22)]
                if now - sess.last_call > 4:
                    sess.heartbeat()
            except Exception:
                self.status = "Lost connection — reconnecting…"
                sess.base = None
                sess.close_conn()
                continue
            wait = (1.0 / FPS) if animated else 0.5
            self.dirty.wait(max(0.0, wait - (time.time() - now)))
        sess.disconnect()


# ---------------------------------------------------------------- UI
BG, PANEL, FG, MUTED, ACCENT = "#121214", "#1C1C20", "#ECECEC", "#8A8A93", "#44D62C"


class App:
    def __init__(self, root, engine):
        self.root, self.engine = root, engine
        s = engine.snapshot()
        root.title(APP_NAME)
        try:
            root.iconbitmap(default=ICON_PATH)
        except tk.TclError:
            pass
        root.configure(bg=BG)
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("TCombobox", fieldbackground=PANEL, background=PANEL, foreground=FG, arrowcolor=FG)
        style.map("TCombobox", fieldbackground=[("readonly", PANEL)], foreground=[("readonly", FG)])
        style.configure("Horizontal.TScale", background=BG, troughcolor=PANEL)
        root.option_add("*TCombobox*Listbox.background", PANEL)
        root.option_add("*TCombobox*Listbox.foreground", FG)
        root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)

        pad = {"padx": 16}
        tk.Label(root, text="CHROMALITE", bg=BG, fg=ACCENT, font=("Segoe UI Semibold", 13)).pack(anchor="w", pady=(14, 2), **pad)
        self.status_lbl = tk.Label(root, text="", bg=BG, fg=MUTED, font=("Segoe UI", 9), wraplength=360, justify="left")
        self.status_lbl.pack(anchor="w", **pad)

        self.preview = tk.Canvas(root, width=360, height=26, bg=BG, highlightthickness=0)
        self.preview.pack(pady=(10, 4), **pad)

        # Effect
        self.section("Effect")
        erow = tk.Frame(root, bg=BG)
        erow.pack(anchor="w", **pad)
        self.effect = tk.StringVar(value=s["effect"])
        self.effect_cb = ttk.Combobox(erow, textvariable=self.effect, state="readonly", width=30, font=("Segoe UI", 10), height=20)
        self.effect_cb.pack(side="left")
        self.effect_cb.bind("<<ComboboxSelected>>", lambda e: self.choose_effect())
        self.button(erow, "Import…", self.import_files).pack(side="left", padx=(8, 0))
        self.button(erow, "Folder", self.open_folder).pack(side="left", padx=(4, 0))
        tk.Label(root, text="Import Synapse Chroma Studio exports (.ChromaEffects) — they're remapped to your devices",
                 bg=BG, fg=MUTED, font=("Segoe UI", 8), wraplength=360, justify="left").pack(anchor="w", **pad)
        self.refresh_effects()

        # Colors
        self.section("Colors")
        self.color_area = tk.Frame(root, bg=BG)
        self.color_area.pack(anchor="w", fill="x")
        row = tk.Frame(self.color_area, bg=BG)
        row.pack(anchor="w", **pad)
        self.c1_btn = self.color_button(row, "color1", s["color1"], "Color 1")
        self.c2_btn = self.color_button(row, "color2", s["color2"], "Color 2")
        presets = tk.Frame(self.color_area, bg=BG)
        presets.pack(anchor="w", pady=(8, 0), **pad)
        tk.Label(presets, text="Quick:", bg=BG, fg=MUTED, font=("Segoe UI", 9)).pack(side="left", padx=(0, 6))
        for p in PRESETS:
            sw = tk.Label(presets, bg=p, width=2, height=1, cursor="hand2", relief="flat")
            sw.pack(side="left", padx=2)
            sw.bind("<Button-1>", lambda e, c=p: self.set_color("color1", c))
            sw.bind("<Button-3>", lambda e, c=p: self.set_color("color2", c))
        self.color_hint = tk.Label(self.color_area, text="", bg=BG, fg=MUTED, font=("Segoe UI", 8))
        self.color_hint.pack(anchor="w", **pad)
        self.update_color_hint()

        # Sliders
        self.section("Brightness")
        self.bright = self.slider(0, 100, s["brightness"], "brightness")
        self.section("Speed")
        self.speed = self.slider(1, 10, s["speed"], "speed")

        # Devices
        self.section("Devices")
        drow = tk.Frame(root, bg=BG)
        drow.pack(anchor="w", **pad)
        self.dev_vars = {}
        for kind, dev in engine.devices.items():
            v = tk.BooleanVar(value=s["devices"].get(kind, True))
            self.dev_vars[kind] = v
            tk.Checkbutton(drow, text=dev.label, variable=v, command=self.devices_changed, bg=BG, fg=FG,
                           selectcolor=PANEL, activebackground=BG, activeforeground=FG,
                           font=("Segoe UI", 10)).pack(side="left", padx=(0, 10))

        # Startup
        self.startup = tk.BooleanVar(value=os.path.exists(STARTUP_VBS))
        tk.Checkbutton(root, text="Start with Windows (minimized)", variable=self.startup, command=self.toggle_startup,
                       bg=BG, fg=MUTED, selectcolor=PANEL, activebackground=BG, activeforeground=FG,
                       font=("Segoe UI", 9)).pack(anchor="w", pady=(14, 2), **pad)
        tk.Label(root, text="Closing this window hands lighting back to Synapse. Minimize to keep it running.",
                 bg=BG, fg=MUTED, font=("Segoe UI", 8), wraplength=360, justify="left").pack(anchor="w", pady=(0, 14), **pad)

        self.tick()

    # widgets
    def section(self, text):
        tk.Label(self.root, text=text.upper(), bg=BG, fg=MUTED, font=("Segoe UI Semibold", 8)).pack(anchor="w", padx=16, pady=(12, 4))

    def button(self, parent, text, cmd):
        return tk.Button(parent, text=text, command=cmd, bg=PANEL, fg=FG, activebackground="#2A2A30", activeforeground=FG,
                         relief="flat", bd=0, padx=10, pady=3, font=("Segoe UI", 9), cursor="hand2")

    def color_button(self, parent, key, value, label):
        f = tk.Frame(parent, bg=BG)
        f.pack(side="left", padx=(0, 14))
        b = tk.Label(f, bg=value, width=6, height=2, cursor="hand2", relief="flat", bd=0)
        b.pack(side="left")
        lbl = tk.Label(f, text=f"{label}\n{value}", bg=BG, fg=FG, font=("Segoe UI", 9), justify="left")
        lbl.pack(side="left", padx=6)
        b.bind("<Button-1>", lambda e: self.pick(key))
        b.text_lbl, b.caption = lbl, label
        return b

    def slider(self, lo, hi, val, key):
        f = tk.Frame(self.root, bg=BG)
        f.pack(anchor="w", padx=16, fill="x")
        var = tk.IntVar(value=val)
        out = tk.Label(f, text=str(val), bg=BG, fg=FG, width=4, font=("Segoe UI", 10))

        def changed(v):
            iv = int(float(v))
            var.set(iv)
            out.config(text=str(iv))
            self.push(**{key: iv})

        ttk.Scale(f, from_=lo, to=hi, value=val, command=changed, length=300).pack(side="left")
        out.pack(side="left", padx=6)
        return var

    # actions
    def push(self, **changes):
        self.engine.update(**changes)
        save_settings(self.engine.snapshot())

    def refresh_effects(self):
        self.effect_cb.config(values=EFFECTS + [FILE_PREFIX + n for n in effect_files()])

    def choose_effect(self):
        self.push(effect=self.effect.get())
        self.update_color_hint()

    def update_color_hint(self):
        if self.effect.get().startswith(FILE_PREFIX):
            self.color_hint.config(text="Effect files use their own colors — brightness and speed still apply")
        else:
            self.color_hint.config(text="Left-click sets Color 1, right-click sets Color 2")

    def import_files(self):
        start = next((d for d in (os.path.expanduser(r"~\Downloads"), os.path.expanduser(r"~\Desktop"))
                      if os.path.isdir(d)), os.path.expanduser("~"))
        paths = filedialog.askopenfilenames(parent=self.root, title="Import Chroma Studio effects", initialdir=start,
                                            filetypes=[("Chroma Studio effects", "*" + EFFECT_EXT), ("All files", "*.*")])
        if not paths:
            return
        os.makedirs(EFFECTS_DIR, exist_ok=True)
        ok, bad = [], []
        for p in paths:
            try:
                ce.ChromaEffect(p)  # validate before copying
                name = os.path.basename(p)
                if not name.lower().endswith(EFFECT_EXT.lower()):
                    name += EFFECT_EXT
                shutil.copyfile(p, os.path.join(EFFECTS_DIR, name))
                ok.append(name[:-len(EFFECT_EXT)])
            except Exception:
                bad.append(os.path.basename(p))
        self.refresh_effects()
        if ok:
            self.effect.set(FILE_PREFIX + ok[0])
            self.choose_effect()
        msg = f"Imported {len(ok)} effect(s)."
        if bad:
            msg += " Not valid Chroma Studio files: " + ", ".join(bad)
        self.status_lbl.config(text=msg)
        self.hold_status_until = time.time() + 4

    def open_folder(self):
        os.makedirs(EFFECTS_DIR, exist_ok=True)
        os.startfile(EFFECTS_DIR)
        self.root.after(1500, self.refresh_effects)

    def pick(self, key):
        cur = self.engine.snapshot()[key]
        res = colorchooser.askcolor(color=cur, title="Choose color", parent=self.root)
        if res and res[1]:
            self.set_color(key, res[1].upper())

    def set_color(self, key, value):
        btn = self.c1_btn if key == "color1" else self.c2_btn
        btn.config(bg=value)
        btn.text_lbl.config(text=f"{btn.caption}\n{value}")
        self.push(**{key: value})

    def devices_changed(self):
        self.push(devices={d: v.get() for d, v in self.dev_vars.items()})

    def toggle_startup(self):
        try:
            if self.startup.get():
                if FROZEN:
                    args = f'""{sys.executable}""'
                else:
                    exe = sys.executable
                    if exe.lower().endswith("python.exe"):
                        exe = exe[:-10] + "pythonw.exe"
                    args = f'""{exe}"" ""{os.path.abspath(__file__)}""'
                with open(STARTUP_VBS, "w", encoding="utf-8") as f:
                    f.write(f'CreateObject("WScript.Shell").Run "{args} --minimized", 0, False\n')
            elif os.path.exists(STARTUP_VBS):
                os.remove(STARTUP_VBS)
        except OSError as e:
            self.status_lbl.config(text=f"Couldn't update startup: {e}")

    hold_status_until = 0.0

    def tick(self):
        if time.time() > self.hold_status_until:
            self.status_lbl.config(text=self.engine.status)
        c = self.preview
        c.delete("all")
        cells = self.engine.preview
        w = 360 / len(cells)
        for i, col in enumerate(cells):
            c.create_rectangle(i * w + 1, 2, (i + 1) * w - 1, 24, fill=rgb_to_hex(col), outline="")
        self.root.after(60, self.tick)

    def on_close(self):
        save_settings(self.engine.snapshot())
        self.engine.stop_evt.set()
        self.engine.dirty.set()
        self.engine.join(timeout=3)
        self.root.destroy()


def migrate_legacy_config():
    """Carry settings and imported effects over from the pre-rename folder."""
    if os.path.isdir(CONFIG_DIR) or not os.path.isdir(LEGACY_CONFIG_DIR):
        return
    try:
        shutil.copytree(LEGACY_CONFIG_DIR, CONFIG_DIR)
    except OSError:
        pass


def already_running():
    """Two instances would fight over the lights, so only allow one."""
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW(None, False, "Local\\ChromaLite.SingleInstance")
    return kernel32.GetLastError() == 183  # ERROR_ALREADY_EXISTS


def main():
    if already_running():
        ctypes.windll.user32.MessageBoxW(None, "ChromaLite is already running.", APP_NAME, 0x40)
        return
    migrate_legacy_config()
    engine = Engine(load_settings())
    engine.start()
    root = tk.Tk()
    App(root, engine)
    if "--minimized" in sys.argv:
        root.iconify()
    root.mainloop()


if __name__ == "__main__":
    main()
