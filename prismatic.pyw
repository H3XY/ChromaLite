"""
Prismatic — a lightweight lighting app for gaming keyboards, mice and mousepads.

Razer devices are controlled through the Razer Chroma SDK that ships with
Synapse; devices from other brands through Windows Dynamic Lighting. Also
plays Synapse 3 Chroma Studio effect files (.ChromaEffects) on any of them.

The window is an HTML interface (ui/) shown with pywebview (WebView2); this
file wires it to the engine and keeps the app alive in the system tray.

Run from source:  pyw prismatic.pyw   (add --minimized to start in the tray)
"""
import ctypes
import os
import shutil
import sys
import threading
import time
import webbrowser
import winreg

import webview

import buttons
import chroma_effects as ce
import engine as en
import tray
from backend_dynlight import DynamicLightingBackend
from backend_razer import RazerBackend
from backend_razer_usb import RazerUsbBackend

APP_NAME = "Prismatic"
APP_VERSION = "2.3.0"
REPO_URL = "https://github.com/H3XY/Prismatic"
LINKS = {"repo": REPO_URL, "issues": REPO_URL + "/issues", "releases": REPO_URL + "/releases"}

FROZEN = getattr(sys, "frozen", False)  # running as the PyInstaller .exe
BASE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
ICON_PATH = os.path.join(BASE_DIR, "assets", "prismatic.ico")
UI_INDEX = os.path.join(BASE_DIR, "ui", "index.html")
# "Start with Windows" uses the standard per-user Run registry entry.
RUN_KEY, RUN_VALUE = r"Software\Microsoft\Windows\CurrentVersion\Run", "Prismatic"
# Older versions used startup-folder scripts instead; they're replaced on first run.
STARTUP_DIR = os.path.join(en.APPDATA, r"Microsoft\Windows\Start Menu\Programs\Startup")
LEGACY_STARTUP_SCRIPTS = [os.path.join(STARTUP_DIR, n) for n in ("Prismatic.vbs", "ChromaLite.vbs")]

WINDOW_BG = "#07090D"

# What the interface needs to know about each built-in effect
BUILTIN_META = {
    "Static": {"colors": 1, "speed": False, "desc": "One solid color"},
    "Breathing": {"colors": 1, "speed": True, "desc": "Fades in and out"},
    "Duo Pulse": {"colors": 2, "speed": True, "desc": "Pulses between two colors"},
    "Spectrum Cycle": {"colors": 0, "speed": True, "desc": "Cycles through every color"},
    "Rainbow Wave": {"colors": 0, "speed": True, "desc": "A rainbow sweeping across"},
    "Gradient Wave": {"colors": 2, "speed": True, "desc": "Two colors sweeping across"},
    "Starlight": {"colors": 2, "speed": True, "desc": "Twinkling stars"},
    "Off": {"colors": 0, "speed": False, "desc": "Lights off"},
}


# ---------------------------------------------------------------- helpers
def rgb_hex(c):
    return "%02x%02x%02x" % (max(0, min(255, int(c[0]))), max(0, min(255, int(c[1]))), max(0, min(255, int(c[2]))))


_THUMB_DEVICES = None


def effect_palette(fx, n=7):
    """A few representative colors for an effect file's thumbnail: one rendered
    frame sampled across a virtual keyboard, or its declared colors if that's dark."""
    global _THUMB_DEVICES
    if _THUMB_DEVICES is None:
        from backend_razer import RazerDevice
        _THUMB_DEVICES = {"thumb": RazerDevice(None, "keyboard", "")}
    leds = _THUMB_DEVICES["thumb"].leds
    renderer = ce.Renderer(fx, _THUMB_DEVICES)
    frame = None
    for i in range(12):  # let starlight and similar effects get going
        frame = renderer.render(1.0 + i * 0.1, 0.1)["thumb"]
    row = sorted((i for i, l in enumerate(leds) if l.key and l.key[0] in (2, 3)), key=lambda i: (leds[i].u, leds[i].v))
    picks = [frame[row[int(k * (len(row) - 1) / (n - 1))]] for k in range(n)] if row else []
    lit = [c for c in picks if max(c) > 40]
    if len(lit) < 3:
        lit = [c[:3] for layer in fx.layers for reg in layer.regions for c in reg.colors if c[3] > 0 and max(c[:3]) > 40][:n]
    return ["#" + rgb_hex(c) for c in lit]


def startup_command():
    if FROZEN:
        return f'"{sys.executable}" --minimized'
    exe = sys.executable
    if exe.lower().endswith("python.exe"):
        exe = exe[:-10] + "pythonw.exe"
    return f'"{exe}" "{os.path.abspath(__file__)}" --minimized'


def _startup_value():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            return winreg.QueryValueEx(k, RUN_VALUE)[0]
    except OSError:
        return None


def startup_enabled():
    return _startup_value() is not None


def set_startup(enabled):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if enabled:
            winreg.SetValueEx(k, RUN_VALUE, 0, winreg.REG_SZ, startup_command())
        else:
            try:
                winreg.DeleteValue(k, RUN_VALUE)
            except FileNotFoundError:
                pass


def style_title_bar(window):
    """Dark Windows 11 title bar in the app's own background color."""
    try:
        hwnd = int(window.native.Handle.ToInt64())
        dwm = ctypes.windll.dwmapi
        for attr, value in ((20, 1),            # DWMWA_USE_IMMERSIVE_DARK_MODE
                            (35, 0x000D0907),   # DWMWA_CAPTION_COLOR  (0x00BBGGRR of WINDOW_BG)
                            (34, 0x000D0907),   # DWMWA_BORDER_COLOR
                            (36, 0x00F0EAE6)):  # DWMWA_TEXT_COLOR
            v = ctypes.c_int(value)
            dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v))
    except Exception:
        pass


# ---------------------------------------------------------------- JS bridge
class Api:
    """Methods the interface calls as pywebview.api.<name>(...). Attributes
    starting with "_" are not exposed to the page."""

    def __init__(self, app):
        self._app = app
        self._layout_sig = None
        self._layout = {}
        self._library_cache = {}

    # state ---------------------------------------------------------------
    def get_state(self):
        eng = self._app.engine
        s = eng.snapshot()
        devs = list(eng.device_map.values())
        in_use = {p["effect"][len(en.FILE_PREFIX):] for p in [en.Engine.profile(s, d.id) for d in devs] + [s]
                  if p["effect"].startswith(en.FILE_PREFIX)}
        return {
            "version": APP_VERSION,
            "devices": [{
                "id": d.id, "name": d.name, "kind": d.kind, "brand": d.brand, "source": d.source,
                "enabled": s["device_enabled"].get(d.id, True), "own": d.id in s["overrides"],
                "available": d.available, "leds": len(d.leds),
            } for d in devs],
            "profiles": dict({"all": {k: s[k] for k in en.PROFILE_KEYS}},
                             **{d.id: en.Engine.profile(s, d.id) for d in devs}),
            "builtin": [dict(name=n, **m) for n, m in BUILTIN_META.items()],
            "library": en.effect_files(),
            "file_prefix": en.FILE_PREFIX,
            "settings": {
                "keypress_effects": s["keypress_effects"],
                "close_to_tray": s["close_to_tray"],
                "dynamic_lighting": s["dynamic_lighting"],
                "usb_control": s["usb_control"],
                "start_with_windows": startup_enabled(),
            },
            "sources": [
                self._razer_source(),
                {"name": "Razer direct USB", "ok": self._app.razer_usb.active,
                 "standby": self._app.razer.connected and s["usb_control"],
                 "status": self._app.razer_usb.status if s["usb_control"] else "Turned off"},
                self._dynlight_source(s, devs),
            ],
            "errors": [eng.file_errors[n] for n in sorted(in_use) if n in eng.file_errors],
            "effects_dir": en.EFFECTS_DIR,
        }

    def _razer_source(self):
        razer, usb = self._app.razer, self._app.razer_usb
        src = {"name": "Razer Chroma", "ok": razer.connected, "status": razer.status, "standby": usb.active}
        if razer.connected and not usb.synapse_app:
            src["ok"] = False
            src["status"] = ("Not in use — Razer Synapse isn't running, so its Chroma SDK can't reach devices"
                             + (" (direct USB is handling them)" if usb.active else ""))
        return src

    def _dynlight_source(self, s, devs):
        name = "Windows Dynamic Lighting"
        if not s["dynamic_lighting"]:
            return {"name": name, "ok": False, "status": "Turned off"}
        found = self._app.dynlight._devices
        used = [d for d in devs if d.source == name]
        if found and not used:  # only Razer devices, which go through Synapse instead
            return {"name": name, "ok": True,
                    "status": f"{len(found)} device{'s' if len(found) != 1 else ''} found, all handled by a Razer source instead"}
        if used:
            return {"name": name, "ok": True, "status": f"Controlling {len(used)} device{'s' if len(used) != 1 else ''}"}
        return {"name": name, "ok": False, "status": self._app.dynlight.status}

    def get_layout(self):
        devs = self._app.engine.device_map
        sig = tuple(sorted(devs))
        if sig != self._layout_sig:
            layout = {}
            for d in devs.values():
                lay = d.preview_layout()
                layout[d.id] = {
                    "name": d.name, "kind": d.kind, "shape": lay["shape"], "frame": list(lay["frame"]),
                    "dots": [[i, style, round(d.leds[i].gx, 3), round(d.leds[i].gy, 3)] for i, style in lay["dots"]],
                }
            self._layout, self._layout_sig = layout, sig
        return self._layout

    def get_frame(self):
        """Current colors of every drawn LED: {device id: "rrggbb" * number of dots}."""
        layout = self.get_layout()
        colors = self._app.engine.colors
        out = {}
        for dev_id, lay in layout.items():
            cs = colors.get(dev_id)
            if cs:
                out[dev_id] = "".join(rgb_hex(cs[i[0]]) if i[0] < len(cs) else "000000" for i in lay["dots"])
        return out

    def get_library(self):
        items = []
        for name in en.effect_files():
            path = en.effect_path(name)
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            meta = self._library_cache.get(name)
            if not meta or meta["mtime"] != mtime:
                try:
                    fx = ce.ChromaEffect(path)
                    kinds = []
                    for layer in fx.layers:
                        if layer.visible and layer.effect in ce.SUPPORTED and layer.effect not in kinds:
                            kinds.append(layer.effect)
                    meta = {"mtime": mtime, "layers": kinds, "ok": True, "palette": effect_palette(fx),
                            "keys": any(k in ("reactive", "ripple") for k in kinds), "audio": "audiometer" in kinds}
                except Exception:
                    meta = {"mtime": mtime, "layers": [], "ok": False, "keys": False, "audio": False, "palette": []}
                self._library_cache[name] = meta
            items.append({"name": name, **{k: v for k, v in meta.items() if k != "mtime"}})
        return items

    # changes ---------------------------------------------------------------
    def _saved(self):
        en.save_settings(self._app.engine.snapshot())
        return self.get_state()

    def set_profile(self, target, changes):
        if "effect" in changes and not en.valid_effect(changes["effect"]):
            return self.get_state()
        self._app.engine.update_profile(target, changes)
        return self._saved()

    def set_own(self, dev_id, own):
        self._app.engine.set_override(dev_id, bool(own))
        return self._saved()

    def set_enabled(self, dev_id, on):
        self._app.engine.set_enabled(dev_id, bool(on))
        return self._saved()

    def set_setting(self, key, value):
        if key == "start_with_windows":
            try:
                set_startup(bool(value))
            except OSError:
                pass
            return self.get_state()
        if key in ("keypress_effects", "close_to_tray", "dynamic_lighting", "usb_control"):
            self._app.engine.update(**{key: bool(value)})
        return self._saved()

    def import_effects(self):
        paths = self._app.window.create_file_dialog(
            webview.FileDialog.OPEN, allow_multiple=True,
            file_types=("Chroma Studio effects (*.ChromaEffects)", "All files (*.*)"))
        imported, failed = [], []
        if paths:
            os.makedirs(en.EFFECTS_DIR, exist_ok=True)
            for p in paths:
                try:
                    ce.ChromaEffect(p)  # validate before copying
                    name = os.path.basename(p)
                    if not name.lower().endswith(en.EFFECT_EXT.lower()):
                        name += en.EFFECT_EXT
                    shutil.copyfile(p, os.path.join(en.EFFECTS_DIR, name))
                    imported.append(name[:-len(en.EFFECT_EXT)])
                except Exception:
                    failed.append(os.path.basename(p))
        return {"imported": imported, "failed": failed, "state": self.get_state()}

    def delete_effect(self, name):
        path = en.effect_path(name)  # effect_path() strips any directory parts
        eff = en.FILE_PREFIX + os.path.basename(name)
        eng = self._app.engine
        s = eng.snapshot()
        if s["effect"] == eff:
            eng.update_profile("all", {"effect": en.DEFAULTS["effect"]})
        for dev_id, p in s["overrides"].items():
            if p["effect"] == eff:
                eng.update_profile(dev_id, {"effect": en.DEFAULTS["effect"]})
        try:
            os.remove(path)
        except OSError:
            pass
        return self._saved()

    def open_effects_folder(self):
        os.makedirs(en.EFFECTS_DIR, exist_ok=True)
        os.startfile(en.EFFECTS_DIR)

    def open_link(self, which):
        if which in LINKS:
            webbrowser.open(LINKS[which])

    def hide_tray_hint(self):
        self._app.engine.update(tray_hint_shown=True)
        en.save_settings(self._app.engine.snapshot())

    # buttons ---------------------------------------------------------------
    def get_buttons(self):
        mgr = self._app.buttons
        last = mgr.last_pressed
        return {
            "triggers": [{"id": t, "name": n} for t, n in buttons.TRIGGERS],
            "config": self._app.engine.snapshot()["buttons"],
            "media": list(buttons.MEDIA),
            "last_pressed": {"id": last[0], "ago": round(time.time() - last[1], 2)} if last else None,
            "status": mgr.status,
        }

    def set_button(self, trigger, action):
        if trigger in buttons.TRIGGER_IDS:
            eng = self._app.engine
            cfg = dict(eng.snapshot()["buttons"])
            clean = buttons.clean_action(action)
            if clean["type"] == "default":
                cfg.pop(trigger, None)
            else:
                cfg[trigger] = clean
            eng.update(buttons=cfg)
            en.save_settings(eng.snapshot())
            self._app.buttons.reconfigure()
        return self.get_buttons()

    def test_button_action(self, action):
        clean = buttons.clean_action(action)
        if clean["type"] not in ("default", "disabled"):
            # give the window a moment to lose focus-sensitive state before input is sent
            threading.Timer(0.6, self._app.buttons.test, args=(clean,)).start()
        return clean["type"]

    def browse_for_app(self):
        paths = self._app.window.create_file_dialog(
            webview.FileDialog.OPEN, allow_multiple=False,
            file_types=("Programs (*.exe;*.lnk;*.bat;*.cmd)", "All files (*.*)"))
        return paths[0] if paths else None


# ---------------------------------------------------------------- app
class App:
    def __init__(self, minimized):
        self.razer = RazerBackend(APP_NAME)
        self.dynlight = DynamicLightingBackend()
        self.razer_usb = RazerUsbBackend()
        self.engine = en.Engine(en.load_settings(), self.razer, self.dynlight, self.razer_usb)
        self.buttons = buttons.ButtonManager(lambda: self.engine.snapshot()["buttons"])
        self.api = Api(self)
        self.quitting = False
        self.window = webview.create_window(
            APP_NAME, url=UI_INDEX, js_api=self.api, width=1200, height=780, min_size=(1000, 660),
            background_color=WINDOW_BG, hidden=minimized, text_select=False)
        self.window.events.closing += self.on_closing
        self.window.events.shown += lambda: style_title_bar(self.window)
        self.tray = tray.Tray(ICON_PATH, APP_NAME, self.show, self.quit)

    def run(self):
        self.razer.start()
        self.dynlight.start()
        self.razer_usb.start()
        self.engine.start()
        self.buttons.start()
        self.tray_ok = self.tray.start()
        webview.start(gui="edgechromium", private_mode=False,
                      storage_path=os.path.join(en.CONFIG_DIR, "webview"))
        # window closed for good
        self.tray.stop()
        self.engine.stop_evt.set()
        self.engine.dirty.set()
        self.engine.join(timeout=3)
        self.razer.stop()
        self.dynlight.stop()
        self.razer_usb.stop()
        self.buttons.stop()

    def show(self):
        self.window.show()
        self.window.restore()
        style_title_bar(self.window)

    def quit(self):
        self.quitting = True
        self.window.destroy()

    def on_closing(self):
        if self.quitting or not self.tray_ok or not self.engine.snapshot()["close_to_tray"]:
            self.quitting = True
            return True
        # Keep running in the tray; tell the page so it can explain once.
        threading.Thread(target=self._hide_soon, daemon=True).start()
        return False

    def _hide_soon(self):
        time.sleep(0.05)
        self.window.hide()
        if not self.engine.snapshot()["tray_hint_shown"]:
            self.tray.notify("Prismatic is still running", "Your lighting stays on. Right-click the tray icon to exit.")
            self.engine.update(tray_hint_shown=True)
            en.save_settings(self.engine.snapshot())


# ---------------------------------------------------------------- startup
def migrate_legacy_config():
    """Carry settings and imported effects over from the app's earlier names,
    and move a "start with Windows" entry made under an earlier name."""
    if not os.path.isdir(en.CONFIG_DIR):
        for old in en.LEGACY_CONFIG_DIRS:
            if os.path.isdir(old):
                try:
                    shutil.copytree(old, en.CONFIG_DIR, ignore=shutil.ignore_patterns("webview"))
                except OSError:
                    pass
                break
    try:
        legacy = [p for p in LEGACY_STARTUP_SCRIPTS if os.path.exists(p)]
        for p in legacy:
            os.remove(p)
        current = _startup_value()
        if legacy or (current is not None and current != startup_command()):
            set_startup(True)  # (re)point "start with Windows" at this copy of the app
    except OSError:
        pass


def already_running():
    """Two instances would fight over the lights, so only allow one."""
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW(None, False, "Local\\Prismatic.SingleInstance")
    return kernel32.GetLastError() == 183  # ERROR_ALREADY_EXISTS


def main():
    if already_running():
        # Launching again (e.g. from the Start menu) brings the running copy back.
        if not tray.show_existing_instance():
            ctypes.windll.user32.MessageBoxW(None, "Prismatic is already running.", APP_NAME, 0x40)
        return
    migrate_legacy_config()
    App(minimized="--minimized" in sys.argv).run()


if __name__ == "__main__":
    main()
