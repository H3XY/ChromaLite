"""
Settings, built-in effects and the render loop.

The engine collects devices from every backend (Razer Chroma SDK, Windows
Dynamic Lighting), works out each device's effect (its own, or the shared
"All devices" one), renders a frame and sends it.
"""
import colorsys
import json
import math
import os
import random
import threading
import time

import buttons
import chroma_effects as ce
from backend_razer import RAZER_VID

FPS = 30
SMOOTHING_S = 0.06  # time constant of the per-LED ease between frames

APPDATA = os.environ.get("APPDATA", os.path.expanduser("~"))
CONFIG_DIR = os.path.join(APPDATA, "Prismatic")
# Earlier names' settings folders, newest first: ChromaLite (1.x-2.0 previews), RazerLighting (first version)
LEGACY_CONFIG_DIRS = [os.path.join(APPDATA, "ChromaLite"), os.path.join(APPDATA, "RazerLighting")]
CONFIG_PATH = os.path.join(CONFIG_DIR, "settings.json")
EFFECTS_DIR = os.path.join(CONFIG_DIR, "effects")
EFFECT_EXT = ".ChromaEffects"

FILE_PREFIX = "File: "
EFFECTS = ["Static", "Breathing", "Duo Pulse", "Spectrum Cycle", "Rainbow Wave", "Gradient Wave", "Starlight", "Off"]
PROFILE_KEYS = ("effect", "color1", "color2", "brightness", "speed")

DEFAULTS = {
    "effect": "Rainbow Wave",
    "color1": "#00FF40",
    "color2": "#3A00FF",
    "brightness": 100,
    "speed": 5,
    "device_enabled": {},  # device id -> bool (missing = on)
    "overrides": {},       # device id -> its own profile (PROFILE_KEYS); absent = follows the shared one
    "keypress_effects": True,
    "close_to_tray": True,
    "tray_hint_shown": False,
    "dynamic_lighting": True,
    "usb_control": True,  # control Razer devices directly when Synapse isn't available
    "buttons": {},  # trigger id (mouse_x1/x2, f13-f24) -> action (see buttons.py)
}


# ---------------------------------------------------------------- helpers
def hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


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
    return os.path.join(EFFECTS_DIR, os.path.basename(name) + EFFECT_EXT)


def valid_effect(eff):
    return eff in EFFECTS or (eff.startswith(FILE_PREFIX) and os.path.exists(effect_path(eff[len(FILE_PREFIX):])))


def load_settings():
    s = json.loads(json.dumps(DEFAULTS))
    saved = {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            saved = json.load(f)
    except (OSError, ValueError):
        pass
    s.update({k: v for k, v in saved.items() if k in s})
    # Settings from 1.x keyed devices by type ("keyboard"); now they're keyed by device id.
    for kind, on in (saved.get("devices") or {}).items():
        s["device_enabled"].setdefault(f"razer:{kind}", bool(on))
    if not valid_effect(s["effect"]):
        s["effect"] = DEFAULTS["effect"]
    overrides = {}
    for dev_id, p in (s.get("overrides") or {}).items():
        if isinstance(p, dict):
            dev_id = dev_id if ":" in dev_id else f"razer:{dev_id}"
            p = {k: p.get(k, s[k]) for k in PROFILE_KEYS}
            if not valid_effect(p["effect"]):
                p["effect"] = s["effect"]
            overrides[dev_id] = p
    s["overrides"] = overrides
    s["buttons"] = {t: buttons.clean_action(act) for t, act in (s.get("buttons") or {}).items()
                    if t in buttons.TRIGGER_IDS}
    return s


def save_settings(s):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        tmp = CONFIG_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({k: v for k, v in s.items() if k in DEFAULTS}, f, indent=2)
        os.replace(tmp, CONFIG_PATH)
    except OSError:
        pass


# ---------------------------------------------------------------- engine
class Engine(threading.Thread):
    def __init__(self, settings, razer, dynlight, razer_usb):
        super().__init__(daemon=True, name="engine")
        self.settings = settings
        self.razer, self.dynlight, self.razer_usb = razer, dynlight, razer_usb
        self.lock = threading.Lock()
        self.stop_evt = threading.Event()
        self.dirty = threading.Event()
        self.device_map = {}   # id -> Device currently connected
        self.colors = {}       # id -> last colors sent (after brightness), for the app's preview
        self.stars = {}
        self.renderers = {}    # (file name, speed) -> [Renderer or None, effect time]
        self.file_errors = {}  # file name -> message
        self.keys, self.audio = None, None
        self.smoothed = {}
        dynlight.enabled = settings["dynamic_lighting"]
        razer_usb.enabled = settings["usb_control"]

    # settings ----------------------------------------------------------
    def update(self, **changes):
        with self.lock:
            self.settings.update(changes)
        if "dynamic_lighting" in changes:
            self.dynlight.enabled = bool(changes["dynamic_lighting"])
        if "usb_control" in changes:
            self.razer_usb.enabled = bool(changes["usb_control"])
        self.dirty.set()

    def update_profile(self, target, changes):
        """Change the shared profile ("all") or one device's own profile."""
        changes = {k: v for k, v in changes.items() if k in PROFILE_KEYS}
        with self.lock:
            if target == "all":
                self.settings.update(changes)
            elif target in self.settings["overrides"]:
                self.settings["overrides"][target].update(changes)
        self.dirty.set()

    def set_override(self, dev_id, enabled):
        """Give a device its own profile (starting as a copy of the shared one), or drop it."""
        with self.lock:
            if enabled:
                self.settings["overrides"].setdefault(dev_id, {k: self.settings[k] for k in PROFILE_KEYS})
            else:
                self.settings["overrides"].pop(dev_id, None)
        self.dirty.set()

    def set_enabled(self, dev_id, on):
        with self.lock:
            self.settings["device_enabled"][dev_id] = bool(on)
        self.dirty.set()

    def snapshot(self):
        with self.lock:
            return json.loads(json.dumps(self.settings))

    @staticmethod
    def profile(s, dev_id):
        return dict(s["overrides"].get(dev_id) or {k: s[k] for k in PROFILE_KEYS})

    def current_devices(self):
        """Every device gets exactly one controller: Razer devices go through Synapse when it's
        there, otherwise directly over USB; Dynamic Lighting covers whatever's left."""
        usb = self.razer_usb
        # Synapse's SDK only reaches devices while the Synapse app runs; without it, prefer direct USB.
        sdk_usable = self.razer.connected and (usb.synapse_app or not usb.enabled or not usb.supports_present())
        if sdk_usable:
            self.razer_usb.wanted = False
            devs = self.razer.devices()
            skip_vendors, skip_products = {RAZER_VID}, set()
        else:
            self.razer_usb.wanted = True
            devs = self.razer_usb.devices()
            skip_vendors, skip_products = set(), {(d.vendor_id, d.product_id) for d in devs}
        devs += self.dynlight.devices(exclude_vendors=skip_vendors, exclude_products=skip_products)
        return {d.id: d for d in devs}

    # smoothing -----------------------------------------------------------
    def smooth(self, dev_id, colors, dt):
        """Ease each LED toward its new color so single-frame jumps can't flash.
        Also gives a quick crossfade when switching effects."""
        prev = self.smoothed.get(dev_id)
        if prev is None or len(prev) != len(colors):
            self.smoothed[dev_id] = [tuple(c) for c in colors]
            return colors
        k = 1 - math.exp(-dt / SMOOTHING_S)
        out = [(p[0] + (c[0] - p[0]) * k, p[1] + (c[1] - p[1]) * k, p[2] + (c[2] - p[2]) * k)
               for p, c in zip(prev, colors)]
        self.smoothed[dev_id] = out
        return out

    # built-in effects ----------------------------------------------------
    def builtin_colors(self, dev, p, t, dt):
        eff, speed = p["effect"], p["speed"]
        c1, c2 = hex_to_rgb(p["color1"]), hex_to_rgb(p["color2"])
        leds = dev.leds
        n = len(leds)
        pos = [l.v if dev.kind == "mouse" else l.u for l in leds]  # mouse LEDs run top to bottom
        if eff == "Breathing":
            k = (1 - math.cos(2 * math.pi * t * 0.07 * speed)) / 2
            return [mix((0, 0, 0), c1, k)] * n
        if eff == "Duo Pulse":
            k = (1 - math.cos(2 * math.pi * t * 0.07 * speed)) / 2
            return [mix(c1, c2, k)] * n
        if eff == "Spectrum Cycle":
            return [hue(t * 0.03 * speed)] * n
        if eff == "Rainbow Wave":
            return [hue(q * 0.8 - t * 0.06 * speed) for q in pos]
        if eff == "Gradient Wave":
            return [mix(c1, c2, (math.sin(2 * math.pi * (q - t * 0.06 * speed)) + 1) / 2) for q in pos]
        if eff == "Starlight":
            stars = self.stars.get(dev.id)
            if stars is None or len(stars) != n:
                stars = self.stars[dev.id] = [[0.0, (0, 0, 0)] for _ in range(n)]
            chance = 0.004 * speed * (dt * FPS)
            base = mix((0, 0, 0), c2, 0.15)
            out = []
            for st in stars:
                if st[0] <= 0 and random.random() < chance:
                    st[0], st[1] = 1.0, (c1 if random.random() < 0.5 else c2)
                st[0] = max(0.0, st[0] - dt * (0.25 + 0.08 * speed))
                out.append(mix(base, st[1], math.sin(math.pi * st[0])))  # fade in, then out
            return out
        return [c1] * n  # Static

    # effect files --------------------------------------------------------
    def file_frames(self, s, wanted, dt):
        """Render each effect file in use exactly once per frame.
        wanted: set of (file name, speed). Returns {(name, speed): frame or None}."""
        for key in list(self.renderers):
            if key not in wanted:
                del self.renderers[key]
        for key in wanted:
            if key not in self.renderers:
                name = key[0]
                try:
                    r = ce.load(effect_path(name), self.device_map)
                    self.file_errors.pop(name, None)
                    if r.unsupported:
                        self.file_errors[name] = f"{name}: skipped unsupported layers ({', '.join(r.unsupported)})"
                except Exception as e:
                    r = None
                    self.file_errors[name] = f"Couldn't load {name}: {e}"
                self.renderers[key] = [r, 0.0]
        live = [e[0] for e in self.renderers.values() if e[0]]
        presses, level = (), 0.0
        if s["keypress_effects"] and any(r.needs_keys for r in live):
            if self.keys is None:
                self.keys = ce.KeyWatcher()
            presses = self.keys.poll()
        if any(r.needs_audio for r in live):
            if self.audio is None:
                self.audio = ce.AudioMeter()
            level = self.audio.level()
        frames = {}
        for (name, speed), entry in self.renderers.items():
            r = entry[0]
            if r is None:
                frames[(name, speed)] = None
                continue
            k = speed / 5
            entry[1] += dt * k
            frames[(name, speed)] = r.render(entry[1], dt * k, presses, level)
        return frames

    # loop ----------------------------------------------------------------
    def run(self):
        t0 = last = time.time()
        last_static_push = 0.0
        while not self.stop_evt.is_set():
            now = time.time()
            dt, last = min(0.25, now - last), now
            devs = self.current_devices()
            # same ids can come from a different controller (e.g. Synapse -> direct USB), so compare objects
            if {i: id(d) for i, d in devs.items()} != {i: id(d) for i, d in self.device_map.items()}:
                self.device_map = devs
                self.renderers.clear()  # effect files are compiled against the device set
                for gone in set(self.colors) - set(devs):
                    self.colors.pop(gone, None)
                    self.smoothed.pop(gone, None)
                self.dirty.set()
            s = self.snapshot()
            profiles = {i: self.profile(s, i) for i in devs}
            on = {i: s["device_enabled"].get(i, True) and profiles[i]["effect"] != "Off" for i in devs}
            animated = any(on[i] and profiles[i]["effect"] != "Static" for i in devs)
            force = self.dirty.is_set() or now - last_static_push > 5
            if animated or force:
                self.dirty.clear()
                if force:
                    last_static_push = now
                wanted = {(p["effect"][len(FILE_PREFIX):], p["speed"]) for i, p in profiles.items()
                          if on[i] and p["effect"].startswith(FILE_PREFIX)}
                frames = self.file_frames(s, wanted, dt) if wanted or self.renderers else {}
                for dev_id, dev in devs.items():
                    try:
                        self._draw(dev, profiles[dev_id], on[dev_id], frames, force, now - t0, dt)
                    except Exception:
                        pass  # one device misbehaving shouldn't stop the others
            wait = (1.0 / FPS) if animated else 0.5
            self.dirty.wait(max(0.0, wait - (time.time() - now)))

    def _draw(self, dev, p, on, frames, force, t, dt):
        eff, bright = p["effect"], p["brightness"] / 100.0
        is_file = eff.startswith(FILE_PREFIX)
        frame = frames.get((eff[len(FILE_PREFIX):], p["speed"])) if is_file else None
        if not on or (is_file and frame is None):
            if force:
                dev.send_off()
                self.colors[dev.id] = [(0, 0, 0)] * len(dev.leds)
            return
        if eff == "Static":
            if not force:  # another device is animating; this one needs no new frame
                return
            color = hex_to_rgb(p["color1"])
            dev.send_static(color, bright)
            colors = [color] * len(dev.leds)
            self.smoothed[dev.id] = colors
        else:
            colors = frame[dev.id] if is_file else self.builtin_colors(dev, p, t, dt)
            colors = self.smooth(dev.id, colors, dt)
            dev.send(colors, bright)
        self.colors[dev.id] = [(c[0] * bright, c[1] * bright, c[2] * bright) for c in colors]
