"""
Synapse 3 Chroma Studio effect files (.ChromaEffects): loader, retargeter and
renderer.

A .ChromaEffects file is a zip holding one XML document: a stack of effect
layers (bottom first), each split into regions that list the exact LEDs they
cover on the author's devices. Those are rarely the devices you own, so every
region is remapped onto *your* hardware:

  * keyboard keys are matched by identity (Razer's LedId = IBM key number),
    so a WASD highlight lands on WASD whatever keyboard it was made on;
  * every other LED takes the region of the nearest source LED by relative
    position on a device of the same type;
  * a device type the effect never targeted borrows the layout of the
    effect's keyboard (or its biggest device), so everything lights up.
"""
import ctypes
import math
import os
import random
import time
import zipfile
import xml.etree.ElementTree as ET


# =============================================================== key tables
# Razer LedId (IBM PC key number) -> Chroma SDK keyboard (row, col)
LEDID_TO_KEY = {110: (0, 1), 124: (0, 15), 125: (0, 16), 126: (0, 17),
                15: (1, 14), 75: (1, 15), 80: (1, 16), 85: (1, 17), 90: (1, 18), 95: (1, 19), 100: (1, 20), 105: (1, 21),
                16: (2, 1), 76: (2, 15), 81: (2, 16), 86: (2, 17), 91: (2, 18), 96: (2, 19), 101: (2, 20), 106: (2, 21),
                30: (3, 1), 92: (3, 18), 97: (3, 19), 102: (3, 20),
                44: (4, 1), 45: (4, 2), 57: (4, 14), 83: (4, 16), 93: (4, 18), 98: (4, 19), 103: (4, 20), 108: (4, 21),
                58: (5, 1), 127: (5, 2), 60: (5, 3), 61: (5, 7), 62: (5, 11), 201: (5, 12), 129: (5, 13), 64: (5, 14),
                79: (5, 15), 84: (5, 16), 89: (5, 17), 99: (5, 19), 104: (5, 20)}
LEDID_TO_KEY.update({112 + i: (0, 3 + i) for i in range(12)})            # F1-F12
LEDID_TO_KEY.update({n: (1, n) for n in range(1, 14)})                   # ` 1-0 - =
LEDID_TO_KEY.update({n: (2, n - 15) for n in range(17, 30)})             # Q-P [ ] \
LEDID_TO_KEY.update({n: (3, n - 29) for n in range(31, 44)})             # A-L ; ' # Enter
LEDID_TO_KEY.update({n: (4, n - 43) for n in range(46, 56)})             # Z-M , . /
LEDID_TO_KEY.update({160 + i: (1 + i, 0) for i in range(5)})             # macro keys
KEY_TO_LEDID = {v: k for k, v in LEDID_TO_KEY.items()}

# Windows virtual-key code -> SDK (row, col), for reactive / ripple effects
VK_TO_KEY = {0x1B: (0, 1), 0x2C: (0, 15), 0x91: (0, 16), 0x13: (0, 17),
             0xC0: (1, 1), 0xBD: (1, 12), 0xBB: (1, 13), 0x08: (1, 14), 0x2D: (1, 15), 0x24: (1, 16), 0x21: (1, 17),
             0x90: (1, 18), 0x6F: (1, 19), 0x6A: (1, 20), 0x6D: (1, 21),
             0x09: (2, 1), 0xDB: (2, 12), 0xDD: (2, 13), 0xDC: (2, 14), 0x2E: (2, 15), 0x23: (2, 16), 0x22: (2, 17),
             0x67: (2, 18), 0x68: (2, 19), 0x69: (2, 20), 0x6B: (2, 21),
             0x14: (3, 1), 0xBA: (3, 11), 0xDE: (3, 12), 0x0D: (3, 14), 0x64: (3, 18), 0x65: (3, 19), 0x66: (3, 20),
             0xA0: (4, 1), 0xBC: (4, 10), 0xBE: (4, 11), 0xBF: (4, 12), 0xA1: (4, 14), 0x26: (4, 16),
             0x61: (4, 18), 0x62: (4, 19), 0x63: (4, 20),
             0xA2: (5, 1), 0x5B: (5, 2), 0xA4: (5, 3), 0x20: (5, 7), 0xA5: (5, 11), 0x5D: (5, 13), 0xA3: (5, 14),
             0x25: (5, 15), 0x28: (5, 16), 0x27: (5, 17), 0x60: (5, 19), 0x6E: (5, 20)}
VK_TO_KEY.update({0x70 + i: (0, 3 + i) for i in range(12)})
VK_TO_KEY.update({0x31 + i: (1, 2 + i) for i in range(9)})
VK_TO_KEY[0x30] = (1, 11)
VK_TO_KEY.update({ord(ch): (2, 2 + i) for i, ch in enumerate("QWERTYUIOP")})
VK_TO_KEY.update({ord(ch): (3, 2 + i) for i, ch in enumerate("ASDFGHJKL")})
VK_TO_KEY.update({ord(ch): (4, 3 + i) for i, ch in enumerate("ZXCVBNM")})


class KeyWatcher:
    """Polls key state each frame; returns keys newly pressed since last poll."""

    def __init__(self):
        self._get = ctypes.windll.user32.GetAsyncKeyState
        self._down = set()

    def poll(self):
        presses = []
        for vk, key in VK_TO_KEY.items():
            s = self._get(vk)
            held, tapped = bool(s & 0x8000), bool(s & 1)
            if (held and vk not in self._down) or (tapped and not held):
                presses.append(key)
            if held:
                self._down.add(vk)
            else:
                self._down.discard(vk)
        return presses


# =============================================================== audio level
class _GUID(ctypes.Structure):
    _fields_ = [("d1", ctypes.c_ulong), ("d2", ctypes.c_ushort), ("d3", ctypes.c_ushort), ("d4", ctypes.c_ubyte * 8)]


def _guid(s):
    g = _GUID()
    ctypes.windll.ole32.CLSIDFromString(ctypes.c_wchar_p(s), ctypes.byref(g))
    return g


def _vcall(obj, index, argtypes, *args):
    vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)(vtbl[index])(obj, *args)


class AudioMeter:
    """Peak level (0..1) of the default playback device via Windows Core Audio."""

    def __init__(self):
        self._meter, self._retry_at, self._opened_at = None, 0.0, 0.0

    def _release(self):
        if self._meter:
            try:
                _vcall(self._meter, 2, ())
            except OSError:
                pass
        self._meter = None

    def _open(self):
        ole32 = ctypes.windll.ole32
        ole32.CoInitializeEx(None, 0)
        enum, dev, meter = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
        hr = ole32.CoCreateInstance(ctypes.byref(_guid("{BCDE0395-E52F-467C-8E3D-C4579291692E}")), None, 23,
                                    ctypes.byref(_guid("{A95664D2-9614-4F35-A746-DE8DB63617E6}")), ctypes.byref(enum))
        if hr:
            raise OSError(hr)
        hr = _vcall(enum, 4, (ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)), 0, 1, ctypes.byref(dev))
        _vcall(enum, 2, ())
        if hr:
            raise OSError(hr)
        hr = _vcall(dev, 3, (ctypes.POINTER(_GUID), ctypes.c_ulong, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)),
                    ctypes.byref(_guid("{C02216F6-8C67-4B5B-9D00-D008E73E0064}")), 23, None, ctypes.byref(meter))
        _vcall(dev, 2, ())
        if hr:
            raise OSError(hr)
        self._meter, self._opened_at = meter, time.time()

    def level(self):
        now = time.time()
        if self._meter and now - self._opened_at > 30:
            self._release()  # periodically re-pick the default output device
        if not self._meter:
            if now < self._retry_at:
                return 0.0
            try:
                self._open()
            except OSError:
                self._retry_at = now + 5
                return 0.0
        peak = ctypes.c_float()
        if _vcall(self._meter, 3, (ctypes.POINTER(ctypes.c_float),), ctypes.byref(peak)):
            self._release()
            return 0.0
        return peak.value


# =============================================================== file parsing
TYPE_KIND = {"1": "mouse", "2": "keyboard", "3": "headset", "4": "keypad", "5": "mousepad",
             "7": "chromalink", "8": "case", "9": "accessory", "15": "monitor"}
MIN_GRID = {"keyboard": (6, 22), "mouse": (9, 5), "mousepad": (9, 7)}
SUPPORTED = {"static", "wave", "spectrum", "starlight", "fire", "colorwheel", "reactive", "ripple", "audiometer"}


def _num(el, tag, default=0.0):
    try:
        return float(el.findtext(tag))
    except (TypeError, ValueError):
        return default


def _color(el):
    if (el.findtext("IsBlank") or "").lower() == "true":
        return (0, 0, 0, 0.0)
    a = el.findtext("Alpha")
    alpha = 1.0 if a is None else int(a) / 255
    return (int(el.findtext("Red") or 0), int(el.findtext("Green") or 0), int(el.findtext("Blue") or 0), alpha)


class Region:
    def __init__(self, el):
        self.params = {c.tag: (c.text or "").strip() for c in el if len(c) == 0}
        self.colors = [_color(c) for c in el.find("Colors") or []]
        self.stops = [float(s.text) for s in el.find("Stops") or []]
        center = el.find("Center")
        self.center = (_num(center, "px", 50), _num(center, "py", 50)) if center is not None and len(center) else (50, 50)
        self.cells = {}  # source device key -> set of (row, col, ledid)
        for item in el.iterfind("Cells/Item"):
            d = item.find("Key/Device")
            if d is None or d.findtext("Type") is None:
                continue
            key = ((d.findtext("Name") or "").upper(), d.findtext("Type"))
            s = self.cells.setdefault(key, set())
            for dc in item.iter("DeviceCell"):
                s.add((int(dc.findtext("Row") or 0), int(dc.findtext("Col") or 0), int(dc.findtext("LedId") or -1)))

    def p(self, name, default=0.0):
        try:
            return float(self.params.get(name, default))
        except ValueError:
            return default


class Layer:
    def __init__(self, el):
        self.effect = (el.findtext("Effect") or "none").lower()
        self.visible = (el.findtext("Visible") or "true").lower() != "false"
        self.alpha = _num(el, "Alpha", 100) / 100
        self.regions = [Region(r) for r in el.iterfind("Regions/EffectRegion")]


class ChromaEffect:
    def __init__(self, path):
        self.name = os.path.basename(path).rsplit(".", 1)[0]
        with zipfile.ZipFile(path) as z:
            info = next((i for i in z.infolist() if i.filename.lower().endswith(".xml")), None)
            if info is None or info.file_size > 64 * 1024 * 1024:
                raise ValueError("not a Chroma Studio effect file")
            root = ET.fromstring(z.read(info))
        if root.tag != "LightingEffects":
            raise ValueError("not a Chroma Studio effect file")
        self.layers = [Layer(l) for l in root.iterfind("EffectLayers/EffectLayer")]
        self.sources = {}  # device key -> all cells the effect references on it
        for layer in self.layers:
            for reg in layer.regions:
                for key, cells in reg.cells.items():
                    self.sources.setdefault(key, set()).update(cells)
        self.unsupported = sorted({l.effect for l in self.layers if l.effect not in SUPPORTED | {"none"}})


# =============================================================== retargeting
def _source_for(effect, kind):
    def kind_of(k):
        return TYPE_KIND.get(k[1], "other")
    same = [k for k in effect.sources if kind_of(k) == kind]
    pool = same or [k for k in effect.sources if kind_of(k) == "keyboard"] or list(effect.sources)
    return max(pool, key=lambda k: len(effect.sources[k])) if pool else None


def _assign(effect, dev):
    """For each target LED, the source cell whose regions it should follow."""
    src = _source_for(effect, dev.kind)
    if src is None:
        return None, [None] * len(dev.leds)
    cells = list(effect.sources[src])
    skind = TYPE_KIND.get(src[1], "other")
    mr, mc = MIN_GRID.get(skind, (1, 1))
    rows = max(mr, max(c[0] for c in cells) + 1)
    cols = max(mc, max(c[1] for c in cells) + 1)
    pts = [((c[1] + 0.5) / cols, (c[0] + 0.5) / rows, c) for c in cells]
    by_ledid = {c[2]: c for c in cells if c[2] in LEDID_TO_KEY} if skind == "keyboard" else {}
    out = []
    for led in dev.leds:
        hit = by_ledid.get(KEY_TO_LEDID.get(led.key)) if led.key else None
        if hit is None:
            hit = min(pts, key=lambda p: (p[0] - led.u) ** 2 + (p[1] - led.v) ** 2)[2]
        out.append(hit)
    return src, out


# =============================================================== rendering
def _lerp4(a, b, k):
    if a[3] == 0:
        a = (b[0], b[1], b[2], 0.0)
    if b[3] == 0:
        b = (a[0], a[1], a[2], 0.0)
    return tuple(a[i] + (b[i] - a[i]) * k for i in range(4))


def _lut(colors, stops, n=256):
    if not colors:
        return [(255, 255, 255, 1.0)] * n
    if len(stops) != len(colors):
        stops = [i * 100 / max(1, len(colors) - 1) for i in range(len(colors))]
    pairs = sorted(zip(stops, colors), key=lambda p: p[0])
    out = []
    for i in range(n):
        p = i * 100 / (n - 1)
        if p <= pairs[0][0]:
            out.append(pairs[0][1])
            continue
        if p >= pairs[-1][0]:
            out.append(pairs[-1][1])
            continue
        for (s0, c0), (s1, c1) in zip(pairs, pairs[1:]):
            if s0 <= p <= s1:
                out.append(_lerp4(c0, c1, (p - s0) / (s1 - s0) if s1 > s0 else 0))
                break
    return out


def _blur_lut(lut, radius):
    """Circular box blur, so hard color stops become short fades instead of
    instant snaps as they sweep past a key (and the wrap-around seam softens)."""
    r = int(radius)
    if r < 1:
        return lut
    n, span = len(lut), 2 * r + 1
    out = []
    for i in range(n):
        acc = [0.0, 0.0, 0.0, 0.0]
        for j in range(i - r, i + r + 1):
            c = lut[j % n]
            for ch in range(4):
                acc[ch] += c[ch]
        out.append(tuple(a / span for a in acc))
    return out


DURATION = {"short": 0.5, "medium": 1.0, "long": 2.0}
WAVE_UNITS_PER_SPEED = 0.3    # key widths per second, per unit of Chroma Studio "Speed"
RIPPLE_UNITS_PER_SPEED = 0.8  # ripples are one-shot rings, so they travel faster
EDGE_SOFTNESS_KEYS = 1.6      # hard gradient edges fade over about 1.6 key widths


class RegionRT:
    def __init__(self, layer, reg, members, devices):
        self.effect, self.alpha, self.reg, self.members = layer.effect, layer.alpha, reg, members
        self.lut = _lut(reg.colors, reg.stops)
        self.solid = [c for c in reg.colors if c[3] > 0] or [(255, 255, 255, 1.0)]
        pts = [(devices[k].leds[i].gx, devices[k].leds[i].gy) for k, idx in members.items() for i in idx]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        self.x0, self.x1, self.y0, self.y1 = min(xs), max(xs), min(ys), max(ys)
        self.extent = math.hypot(self.x1 - self.x0, self.y1 - self.y0) + 2
        self.speed = reg.p("Speed", 5)
        self.dur = DURATION.get(reg.params.get("Duration", "medium").lower(), 1.0)
        self.data = {}
        e = self.effect
        for kind, idx in members.items():
            leds = [devices[kind].leds[i] for i in idx]
            if e == "wave":
                a = math.radians(reg.p("Angle", 90))
                dx, dy = math.sin(a), -math.cos(a)
                proj = [l.gx * dx + l.gy * dy for l in leds]
                if reg.params.get("Split", "").lower() == "true":
                    c = ((self.x0 + self.x1) * dx + (self.y0 + self.y1) * dy) / 2
                    proj = [abs(p - c) for p in proj]
                self.data[kind] = proj
            elif e == "colorwheel":
                cx = self.x0 + (self.x1 - self.x0) * reg.center[0] / 100
                cy = self.y0 + (self.y1 - self.y0) * reg.center[1] / 100
                self.data[kind] = [(math.atan2(l.gy - cy, l.gx - cx) / (2 * math.pi)) % 1 for l in leds]
            elif e == "audiometer":
                w = max(1e-6, self.x1 - self.x0)
                self.data[kind] = [(l.gx - self.x0) / w for l in leds]
            elif e == "starlight":
                self.data[kind] = [[0.0, self.solid[0]] for _ in leds]
            elif e == "fire":
                self.data[kind] = [[random.uniform(-1, 1), l.v] for l in leds]
            elif e in ("reactive", "ripple"):
                self.data[kind] = [l.key for l in leds]
        # every keyboard key this region covers, on any device
        self.keyset = {k for keys in self.data.values() for k in keys if k} if e in ("reactive", "ripple") else set()
        self.pressed = {}   # reactive: key -> time
        self.ripples = []   # ripple: (x, y, t0)
        self.level = self.peak_hold = 0.0
        self.wavelen = max(0.5, reg.p("Width", 100) / 100 * 22)
        self.pause = reg.p("Pause", 0)
        if e == "wave":
            self.lut = _blur_lut(self.lut, len(self.lut) * EDGE_SOFTNESS_KEYS / self.wavelen / 2)
        elif e == "colorwheel":
            self.lut = _blur_lut(self.lut, 6)

    def draw(self, out, t, dt, presses, audio):
        e, la = self.effect, self.alpha
        if e == "static":
            c = self.reg.colors[0] if self.reg.colors else (0, 0, 0, 0)
            for kind, idx in self.members.items():
                px = out[kind]
                for i in idx:
                    _blend(px[i], c, la)
        elif e == "wave":
            vel = max(0.01, self.speed * WAVE_UNITS_PER_SPEED)
            if self.pause > 0:
                travel = self.wavelen / vel
                n, rem = divmod(t, travel + self.pause)
                tt = n * travel + min(rem, travel)
            else:
                tt = t
            shift, inv, lut = tt * vel, 1 / self.wavelen, self.lut
            for kind, idx in self.members.items():
                px = out[kind]
                for i, p in zip(idx, self.data[kind]):
                    _blend(px[i], lut[int(((p - shift) * inv) % 1.0 * 255)], la)
        elif e == "spectrum":
            c = self.lut[int((t / (8 * self.dur)) % 1.0 * 255)]
            for kind, idx in self.members.items():
                px = out[kind]
                for i in idx:
                    _blend(px[i], c, la)
        elif e == "colorwheel":
            rot, lut = t * self.speed / 150, self.lut
            for kind, idx in self.members.items():
                px = out[kind]
                for i, a in zip(idx, self.data[kind]):
                    _blend(px[i], lut[int(((a + rot) % 1.0) * 255)], la)
        elif e == "starlight":
            rate = self.reg.p("Density", 5) * 0.05 * dt
            life = self.dur * 1.2
            for kind, idx in self.members.items():
                px = out[kind]
                for i, st in zip(idx, self.data[kind]):
                    if st[0] <= 0:
                        if random.random() < rate:
                            st[0], st[1] = life, random.choice(self.solid)
                        continue
                    st[0] -= dt
                    k = math.sin(math.pi * max(0.0, st[0]) / life)
                    c = st[1]
                    _blend(px[i], (c[0], c[1], c[2], c[3] * k), la)
        elif e == "fire":
            base = self.reg.colors[0] if self.reg.colors else (255, 40, 0, 1.0)
            tip = self.reg.colors[1] if len(self.reg.colors) > 1 else (255, 200, 0, 1.0)
            jitter = dt * 4 * max(0.2, self.speed / 5)
            for kind, idx in self.members.items():
                px = out[kind]
                for i, st in zip(idx, self.data[kind]):
                    st[0] = max(-1.0, min(1.0, st[0] + random.uniform(-jitter, jitter)))
                    heat = max(0.0, min(1.0, st[1] * 1.4 - 0.45 + st[0] * 0.35))
                    c = _lerp4(tip, base, heat)
                    _blend(px[i], (c[0], c[1], c[2], c[3] * min(1.0, heat * 1.6)), la)
        elif e == "audiometer":
            boost = self.reg.p("BoostLevel", 1) or 1
            if self.reg.params.get("AutoBoost", "").lower() == "true":
                self.peak_hold = max(audio, self.peak_hold * (0.5 ** dt))
                target = audio / max(0.08, self.peak_hold)
            else:
                target = audio * 1.6
            target = min(1.0, target * boost)
            decay = max(0.05, self.reg.p("DecayMs", 400) / 1000)
            self.level = target if target > self.level else max(target, self.level - dt / decay)
            lut = self.lut
            for kind, idx in self.members.items():
                px = out[kind]
                for i, f in zip(idx, self.data[kind]):
                    if f <= self.level:
                        _blend(px[i], lut[int(min(1.0, f) * 255)], la)
        elif e == "reactive":
            for key in presses:
                if key in self.keyset:
                    self.pressed[key] = t
            self.pressed = {k: t0 for k, t0 in self.pressed.items() if t - t0 < self.dur}
            if not self.pressed:
                return
            c0 = self.reg.colors[0] if self.reg.colors else (255, 255, 255, 1.0)
            c1 = self.reg.colors[1] if len(self.reg.colors) > 1 else (0, 0, 0, 0.0)
            for kind, idx in self.members.items():
                px = out[kind]
                for i, key in zip(idx, self.data[kind]):
                    t0 = self.pressed.get(key) if key else None
                    if t0 is None:
                        continue
                    k = 1 - (t - t0) / self.dur
                    c = _lerp4(c1, c0, k)
                    _blend(px[i], (c[0], c[1], c[2], c[3] * k), la)
        elif e == "ripple":
            any_key = self.reg.params.get("Start", "").lower() == "onkeypress"
            for key in presses:
                if any_key or key in self.keyset:
                    self.ripples.append((key[1] + 0.5, key[0] + 0.5, t))
            if not self.ripples:
                return
            vel = max(0.5, self.speed * RIPPLE_UNITS_PER_SPEED)
            ring = max(1.0, self.reg.p("Width", 100) / 100 * 2)
            self.ripples = [r for r in self.ripples if (t - r[2]) * vel - ring < self.extent]
            lut = self.lut
            for kind, idx in self.members.items():
                px, leds = out[kind], self.devices_leds[kind]
                for i in idx:
                    l = leds[i]
                    for rx, ry, t0 in self.ripples:
                        radius = (t - t0) * vel
                        d = radius - math.hypot(l.gx - rx, l.gy - ry)
                        if 0 <= d <= ring:
                            c = lut[int(d / ring * 255)]
                            fade = max(0.0, 1 - radius / self.extent)
                            _blend(px[i], (c[0], c[1], c[2], c[3] * fade), la)


def _blend(px, c, layer_alpha):
    a = c[3] * layer_alpha
    if a >= 0.999:
        px[0], px[1], px[2] = c[0], c[1], c[2]
    elif a > 0.001:
        k = 1 - a
        px[0] = px[0] * k + c[0] * a
        px[1] = px[1] * k + c[1] * a
        px[2] = px[2] * k + c[2] * a


class Renderer:
    """A loaded effect compiled against your devices."""

    def __init__(self, effect, devices):
        self.name, self.devices = effect.name, devices
        self.unsupported = effect.unsupported
        assignments = {kind: _assign(effect, dev) for kind, dev in devices.items()}
        self.regions = []
        for layer in effect.layers:
            if not layer.visible or layer.effect not in SUPPORTED:
                continue
            for reg in layer.regions:
                members = {}
                for kind, (src, cell_of) in assignments.items():
                    cells = reg.cells.get(src) if src else None
                    if cells:
                        idx = [i for i, c in enumerate(cell_of) if c in cells]
                        if idx:
                            members[kind] = idx
                if members:
                    rt = RegionRT(layer, reg, members, devices)
                    rt.devices_leds = {k: d.leds for k, d in devices.items()}
                    self.regions.append(rt)
        self.needs_keys = any(r.effect in ("reactive", "ripple") for r in self.regions)
        self.needs_audio = any(r.effect == "audiometer" for r in self.regions)

    def render(self, t, dt, presses=(), audio=0.0):
        out = {k: [[0.0, 0.0, 0.0] for _ in d.leds] for k, d in self.devices.items()}
        for rt in self.regions:
            rt.draw(out, t, dt, presses, audio)
        return out


def load(path, devices):
    return Renderer(ChromaEffect(path), devices)
