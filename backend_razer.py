"""
Razer devices through the Razer Chroma SDK REST server that ships with Synapse
(http://localhost:54235). Works in the background, so lighting keeps running
while ChromaLite sits in the tray.

The SDK addresses devices by type (keyboard / mouse / mousepad), not by model,
so device names come from Windows' list of connected USB devices.
"""
import asyncio
import http.client
import json
import threading
import time
from urllib.parse import urlparse

import devices as dv
from chroma_effects import KEY_TO_LEDID

SDK_HOST, SDK_PORT = "localhost", 54235
RAZER_VID = 0x1532

KIND_WORDS = {
    "mousepad": ("firefly", "goliathus", "strider", "mouse mat", "mousepad", "mouse pad"),
    "keyboard": ("blackwidow", "huntsman", "ornata", "cynosa", "deathstalker", "turret", "keyboard"),
    "mouse": ("deathadder", "basilisk", "viper", "naga", "mamba", "orochi", "cobra", "lancehead",
              "atheris", "abyssus", "diamondback", "mouse"),
}
GENERIC_NAMES = {"keyboard": "Razer Keyboard", "mouse": "Razer Mouse", "mousepad": "Razer Mousepad"}


def to_bgr(c, bright):
    r, g, b = (max(0, min(255, int(v * bright))) for v in c)
    return (b << 16) | (g << 8) | r


def classify(name):
    low = name.lower()
    for kind, words in KIND_WORDS.items():  # mousepad first: "mouse" is a substring of it
        if any(w in low for w in words):
            return kind
    return None


def connected_razer_names():
    """Friendly names of connected Razer USB devices, via Windows device enumeration."""
    from winrt.windows.devices.enumeration import DeviceInformation, DeviceInformationKind
    import winrt.windows.foundation.collections  # noqa: F401  (result list type; bundled by the .exe build)

    async def find():
        infos = await DeviceInformation.find_all_async_with_kind_aqs_filter_and_additional_properties(
            'System.Devices.DeviceInstanceId:~<"USB\\VID_1532"', [], DeviceInformationKind.DEVICE)
        return sorted({i.name for i in infos if i.name and i.name.lower().startswith("razer")})

    return asyncio.run(find())


# ------------------------------------------------------------------ SDK session
class ChromaSession:
    """One registered app session with the Chroma SDK REST server."""

    def __init__(self):
        self.base = None  # (host, port, path)
        self.conn = None
        self.last_call = 0.0
        self.version = ""

    def _request(self, host, port, method, path, body=None):
        if self.conn is None or (self.conn.host, self.conn.port) != (host, port):
            self.close_conn()
            self.conn = http.client.HTTPConnection(host, port, timeout=3)
        data = json.dumps(body) if body is not None else None
        try:
            self.conn.request(method, path, body=data, headers={"Content-Type": "application/json"})
            raw = self.conn.getresponse().read()
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

    def connect(self, app_name):
        info = self._request(SDK_HOST, SDK_PORT, "GET", "/razer/chromasdk")
        self.version = info.get("version", "")
        res = self._request(SDK_HOST, SDK_PORT, "POST", "/razer/chromasdk", {
            "title": app_name,
            "description": "Lightweight lighting controller",
            "author": {"name": "ChromaLite", "contact": "https://github.com/H3XY/ChromaLite"},
            "device_supported": ["keyboard", "mouse", "mousepad"],
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


# ------------------------------------------------------------------ devices
KB_KEYS = 6 * 22
REAL_KEYS = set(KEY_TO_LEDID)  # SDK grid cells that are actual keys on a full-size board


class RazerDevice(dv.Device):
    def __init__(self, backend, kind, name):
        x, y, w, h = dv.DESK[kind]
        if kind == "keyboard":
            leds = dv.grid(6, 22, x, y, w, h, keys=True) + dv.grid(8, 24, x - 0.5, y - 0.5, w + 1, h + 1)
        elif kind == "mouse":
            leds = dv.grid(9, 7, x, y, w, h)
        else:
            leds = dv.perimeter(20, x, y, w, h)
        super().__init__(f"razer:{kind}", kind, name, "Razer", "Razer Chroma", leds)
        self.backend = backend
        self.vendor_id = RAZER_VID

    @property
    def available(self):
        return self.backend.connected

    def _payload(self, b):
        if self.kind == "keyboard":
            keys, glow = b[:KB_KEYS], b[KB_KEYS:]
            return {"effect": "CHROMA_CUSTOM2", "param": {
                "color": [glow[r * 24:(r + 1) * 24] for r in range(8)],
                "key": [[k | 0x01000000 for k in keys[r * 22:(r + 1) * 22]] for r in range(6)],
            }}
        if self.kind == "mouse":
            return {"effect": "CHROMA_CUSTOM2", "param": [b[r * 7:(r + 1) * 7] for r in range(9)]}
        return {"effect": "CHROMA_CUSTOM2", "param": b}

    def send(self, colors, bright):
        self.backend.put(self.kind, self._payload([to_bgr(c, bright) for c in colors]))

    def send_static(self, color, bright):
        self.backend.put(self.kind, {"effect": "CHROMA_STATIC", "param": {"color": to_bgr(color, bright)}})

    def send_off(self):
        self.backend.put(self.kind, {"effect": "CHROMA_NONE"})

    def preview_layout(self):
        x, y, w, h = dv.DESK[self.kind]
        if self.kind == "keyboard":
            dots = [(r * 22 + c, "key") for r in range(6) for c in range(22) if (r, c) in REAL_KEYS]
            dots += [(KB_KEYS + r * 24 + c, "glow") for r in range(8) for c in range(24)
                     if r in (0, 7) or c in (0, 23)]
        elif self.kind == "mouse":
            dots = [(2 * 7 + 3, "wheel"), (7 * 7 + 3, "logo")]  # scroll wheel and logo
        else:
            dots = [(i, "seg") for i in range(len(self.leds))]
        return {"frame": (x, y, w, h), "shape": self.kind, "dots": dots}


# ------------------------------------------------------------------ backend
class RazerBackend:
    name = "Razer Chroma"

    def __init__(self, app_name):
        self.app_name = app_name
        self.session = ChromaSession()
        self.lock = threading.Lock()
        self.connected = False
        self.status = "Connecting…"
        self._devices = []
        self._stop = threading.Event()
        self._names_at = 0.0

    def start(self):
        threading.Thread(target=self._run, daemon=True, name="razer").start()

    def stop(self):
        self._stop.set()
        with self.lock:
            self.session.disconnect()
        self.connected = False

    def devices(self):
        return list(self._devices) if self.connected else []

    def put(self, sdk_kind, payload):
        if not self.connected:
            return
        try:
            with self.lock:
                self.session.put(sdk_kind, payload)
        except Exception:
            self._lost()

    def _lost(self):
        self.connected = False
        self.status = "Lost connection to Razer Synapse — reconnecting…"
        with self.lock:
            self.session.base = None
            self.session.close_conn()

    def _refresh_names(self):
        try:
            names = connected_razer_names()
        except Exception:
            names = None
        found = {}
        for n in names or []:
            kind = classify(n)
            if kind:
                found.setdefault(kind, []).append(n)
        if not found:  # couldn't tell what's connected: offer all three, the SDK ignores missing ones
            found = {k: [v] for k, v in GENERIC_NAMES.items()}
        current = {d.kind: d for d in self._devices}
        devs = []
        for kind in ("keyboard", "mouse", "mousepad"):
            if kind in found:
                name = " + ".join(found[kind])
                d = current.get(kind)
                if d is None or d.name != name:
                    d = RazerDevice(self, kind, name)
                devs.append(d)
        self._devices = devs
        self._names_at = time.time()

    def _run(self):
        while not self._stop.is_set():
            if not self.connected:
                try:
                    with self.lock:
                        self.session.connect(self.app_name)
                    self._refresh_names()
                    self.connected = True
                    self.status = f"Connected · Chroma SDK {self.session.version}".rstrip(" ")
                except Exception:
                    self.connected = False
                    self.status = "Razer Synapse not found — install Synapse to control Razer devices in the background"
                    self._stop.wait(3)
                    continue
            if time.time() - self._names_at > 10:
                self._refresh_names()  # notice devices being plugged in or out
            if time.time() - self.session.last_call > 4:
                try:
                    with self.lock:
                        self.session.heartbeat()
                except Exception:
                    self._lost()
            self._stop.wait(1)
