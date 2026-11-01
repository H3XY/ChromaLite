"""
Razer devices controlled directly over USB (HID feature reports), so lighting
works without Razer Synapse installed or running.

Used only when Synapse isn't available: Synapse keeps writing its own
lighting, and two programs writing to one device makes it flicker. So this
backend steps aside whenever Synapse is running.

Protocol: 90-byte reports (status, transaction id, remaining packets,
protocol type, data size, command class, command id, 80 argument bytes, CRC
= XOR of bytes 2..87, reserved), sent as HID feature report 0. Lighting uses
the "extended matrix" commands: class 0x0F cmd 0x03 writes one row of RGB
values, class 0x0F cmd 0x02 effect 0x08 shows that custom frame.
Protocol facts are from the OpenRazer project's documentation of the
hardware; per-model layouts were confirmed on real devices.
"""
import ctypes
import threading
import time
from ctypes import wintypes as w

import devices as dv
from chroma_effects import LEDID_TO_KEY

RAZER_VID = 0x1532

# Synapse processes that write lighting themselves (Synapse 4, 3 and 2).
SYNAPSE_PROCESSES = {"razerappengine.exe", "razer synapse 3.exe", "razer synapse service.exe",
                     "razer synapse.exe", "rzsynapse.exe"}

# BlackWidow V4 Pro key matrix: per row, "col:LedId" for cells under a key (LedId = IBM key
# number, see chroma_effects.LEDID_TO_KEY; 160-164 = macro keys). Confirmed on a real V4 Pro:
# Esc 0,1 / F1 0,4 / macro keys in col 1 / ` 1,2 / Tab 2,2 / Q 2,3 / Caps 3,2 / A-S-D 3,3-5 /
# Left Shift 4,2 / Ctrl-Win 5,2-3 / arrow keys 4,17 and 5,16-18. The rest follows Razer's layout.
BLACKWIDOW_MATRIX = {
    0: "1:110 4:112 5:113 6:114 7:115 8:116 9:117 10:118 11:119 12:120 13:121 14:122 15:123 16:124 17:125 18:126",
    1: "1:160 2:1 3:2 4:3 5:4 6:5 7:6 8:7 9:8 10:9 11:10 12:11 13:12 14:13 15:15 16:75 17:80 18:85 19:90 20:95 21:100 22:105",
    2: "1:161 2:16 3:17 4:18 5:19 6:20 7:21 8:22 9:23 10:24 11:25 12:26 13:27 14:28 15:29 16:76 17:81 18:86 19:91 20:96 21:101 22:106",
    3: "1:162 2:30 3:31 4:32 5:33 6:34 7:35 8:36 9:37 10:38 11:39 12:40 13:41 14:43 19:92 20:97 21:102",
    4: "1:163 2:44 3:46 4:47 5:48 6:49 7:50 8:51 9:52 10:53 11:54 12:55 14:57 17:83 19:93 20:98 21:103",
    5: "1:164 2:58 3:127 4:60 8:61 13:62 14:201 15:64 16:79 17:84 18:89 20:99 21:104 22:108",
}


class Model:
    def __init__(self, name, kind, interface, txn, rows, cols):
        self.name, self.kind, self.interface, self.txn, self.rows, self.cols = name, kind, interface, txn, rows, cols


# Supported models. Interface and transaction id confirmed by each device answering a firmware query.
MODELS = {
    0x028D: Model("Razer BlackWidow V4 Pro", "keyboard", 3, 0x1F, 8, 23),  # rows 6-7: top/bottom underglow
    0x0084: Model("Razer DeathAdder V2", "mouse", 0, 0x1F, 1, 2),          # col 0 scroll wheel, col 1 logo
    0x0C04: Model("Razer Firefly V2", "mousepad", 0, 0x3F, 1, 19),         # loop from top-middle, going left
}


# ------------------------------------------------------------------ Windows HID plumbing
class _GUID(ctypes.Structure):
    _fields_ = [("d1", ctypes.c_ulong), ("d2", ctypes.c_ushort), ("d3", ctypes.c_ushort), ("d4", ctypes.c_ubyte * 8)]


class _IFACE(ctypes.Structure):
    _fields_ = [("cbSize", w.DWORD), ("guid", _GUID), ("flags", w.DWORD), ("reserved", ctypes.c_void_p)]


class _ATTRS(ctypes.Structure):
    _fields_ = [("Size", w.ULONG), ("VendorID", w.USHORT), ("ProductID", w.USHORT), ("Version", w.USHORT)]


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", w.DWORD), ("cntUsage", w.DWORD), ("th32ProcessID", w.DWORD), ("th32DefaultHeapID", ctypes.c_void_p),
                ("th32ModuleID", w.DWORD), ("cntThreads", w.DWORD), ("th32ParentProcessID", w.DWORD),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", w.DWORD), ("szExeFile", w.WCHAR * 260)]


_setupapi, _hid, _k32 = ctypes.windll.setupapi, ctypes.windll.hid, ctypes.windll.kernel32
_setupapi.SetupDiGetClassDevsW.restype = ctypes.c_void_p
_setupapi.SetupDiGetClassDevsW.argtypes = [ctypes.POINTER(_GUID), w.LPCWSTR, w.HWND, w.DWORD]
_setupapi.SetupDiEnumDeviceInterfaces.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(_GUID), w.DWORD, ctypes.POINTER(_IFACE)]
_setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_IFACE), ctypes.c_void_p, w.DWORD,
                                                      ctypes.POINTER(w.DWORD), ctypes.c_void_p]
_setupapi.SetupDiDestroyDeviceInfoList.argtypes = [ctypes.c_void_p]
_k32.CreateFileW.restype = w.HANDLE
_k32.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p, w.DWORD, w.DWORD, w.HANDLE]
_k32.CloseHandle.argtypes = [w.HANDLE]
_k32.CreateToolhelp32Snapshot.restype = w.HANDLE
_k32.Process32FirstW.argtypes = [w.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
_k32.Process32NextW.argtypes = [w.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
_hid.HidD_SetFeature.argtypes = [w.HANDLE, ctypes.c_void_p, w.ULONG]
_hid.HidD_GetAttributes.argtypes = [w.HANDLE, ctypes.POINTER(_ATTRS)]
_INVALID = w.HANDLE(-1).value


def _hid_paths():
    g = _GUID()
    _hid.HidD_GetHidGuid(ctypes.byref(g))
    info = _setupapi.SetupDiGetClassDevsW(ctypes.byref(g), None, None, 0x12)  # DIGCF_PRESENT | DIGCF_DEVICEINTERFACE
    out, i = [], 0
    try:
        while True:
            d = _IFACE()
            d.cbSize = ctypes.sizeof(d)
            if not _setupapi.SetupDiEnumDeviceInterfaces(info, None, ctypes.byref(g), i, ctypes.byref(d)):
                break
            need = w.DWORD()
            _setupapi.SetupDiGetDeviceInterfaceDetailW(info, ctypes.byref(d), None, 0, ctypes.byref(need), None)
            buf = ctypes.create_string_buffer(need.value)
            ctypes.cast(buf, ctypes.POINTER(w.DWORD))[0] = 8  # cbSize of SP_DEVICE_INTERFACE_DETAIL_DATA_W (x64)
            if _setupapi.SetupDiGetDeviceInterfaceDetailW(info, ctypes.byref(d), buf, need, None, None):
                out.append(ctypes.wstring_at(ctypes.addressof(buf) + 4))
            i += 1
    finally:
        _setupapi.SetupDiDestroyDeviceInfoList(info)
    return out


def synapse_running():
    snap = _k32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    if snap == _INVALID:
        return False
    try:
        e = _PROCESSENTRY32W()
        e.dwSize = ctypes.sizeof(e)
        ok = _k32.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            if e.szExeFile.lower() in SYNAPSE_PROCESSES:
                return True
            ok = _k32.Process32NextW(snap, ctypes.byref(e))
    finally:
        _k32.CloseHandle(snap)
    return False


def _report(txn, cls, cmd, args):
    r = bytearray(91)  # report id 0 + 90-byte Razer report
    r[2], r[6], r[7], r[8] = txn, len(args), cls, cmd
    r[9:9 + len(args)] = bytes(args)
    crc = 0
    for b in r[3:89]:  # bytes 2..87 of the Razer report
        crc ^= b
    r[89] = crc
    return r


# ------------------------------------------------------------------ devices
def _keyboard_leds(model):
    """Native 8x23 matrix: rows 0-5 keys (placed where the key sits), rows 6-7 the underglow edges."""
    x, y, w_, h = dv.DESK["keyboard"]
    native = {}
    for r, spec in BLACKWIDOW_MATRIX.items():
        for item in spec.split():
            c, led_id = item.split(":")
            native[(r, int(c))] = LEDID_TO_KEY[int(led_id)]
    leds, styles = [], []
    for r in range(model.rows):
        for c in range(model.cols):
            key = native.get((r, c))
            if key:  # put the LED where that key sits, so effects and key presses line up
                leds.append(dv.Led(x + key[1] + 0.5, y + key[0] + 0.5, (key[1] + 0.5) / 22, (key[0] + 0.5) / 6, key))
                styles.append("key")
            elif r >= 6:  # underglow: row 6 along the top edge, row 7 along the bottom
                u = (c + 0.5) / model.cols
                gy = y - 0.5 if r == 6 else y + h + 0.5
                leds.append(dv.Led(x + u * w_, gy, u, 0.0 if r == 6 else 1.0))
                styles.append("glow")
            else:  # a matrix cell with no key on this layout
                u, v = (c + 0.5) / model.cols, (r + 0.5) / 6
                leds.append(dv.Led(x + u * w_, y + v * h, u, v))
                styles.append(None)
    return leds, styles


def _mousepad_leds(model):
    """LEDs loop the whole edge, starting at the top middle and heading left."""
    x, y, w_, h = dv.DESK["mousepad"]
    per = 2 * (w_ + h)
    leds = []
    for i in range(model.cols):
        d = (i + 0.5) / model.cols * per
        if d < w_ / 2:
            px, py = x + w_ / 2 - d, y
        elif d < w_ / 2 + h:
            px, py = x, y + (d - w_ / 2)
        elif d < w_ / 2 + h + w_:
            px, py = x + (d - w_ / 2 - h), y + h
        elif d < w_ / 2 + 2 * h + w_:
            px, py = x + w_, y + h - (d - w_ / 2 - h - w_)
        else:
            px, py = x + w_ - (d - w_ / 2 - 2 * h - w_), y
        leds.append(dv.Led(px, py, (px - x) / w_, (py - y) / h))
    return leds, ["seg"] * len(leds)


def _mouse_leds(model):
    x, y, w_, h = dv.DESK["mouse"]
    cx = x + w_ / 2
    # same spots as the Chroma SDK mouse grid uses for the scroll wheel and logo
    leds = [dv.Led(cx, y + h * 2.5 / 9, 0.5, 2.5 / 9), dv.Led(cx, y + h * 7.5 / 9, 0.5, 7.5 / 9)]
    return leds, ["wheel", "logo"]


class RazerUsbDevice(dv.Device):
    def __init__(self, backend, pid, model, handle):
        build = {"keyboard": _keyboard_leds, "mouse": _mouse_leds, "mousepad": _mousepad_leds}[model.kind]
        leds, self._styles = build(model)
        # Same id as the Synapse version of this device, so per-device settings follow it.
        super().__init__(f"razer:{model.kind}", model.kind, model.name, "Razer", "Direct USB", leds)
        self.backend, self.model, self.handle = backend, model, handle
        self.vendor_id, self.product_id = RAZER_VID, pid
        self._last_rows = {}
        self._last_show = 0.0

    @property
    def available(self):
        return self.backend.active

    def _write(self, report):
        buf = (ctypes.c_ubyte * 91).from_buffer(report)
        if not _hid.HidD_SetFeature(self.handle, buf, 91):
            raise OSError("device didn't accept the report")

    def send(self, colors, bright):
        if not self.backend.active:
            return
        m = self.model
        now = time.time()
        if now - self._last_show > 2:
            self._last_rows.clear()  # resend everything now and then, in case something else changed the lights
        changed = False
        for r in range(m.rows):
            row = bytearray()
            for c in range(m.cols):
                cr, cg, cb = colors[r * m.cols + c]
                row += bytes((max(0, min(255, int(cr * bright))), max(0, min(255, int(cg * bright))),
                              max(0, min(255, int(cb * bright)))))
            if self._last_rows.get(r) != row:  # only rows that changed
                self._write(_report(m.txn, 0x0F, 0x03, bytes((0, 0, r, 0, m.cols - 1)) + row))
                self._last_rows[r] = row
                changed = True
        if changed or now - self._last_show > 2:  # show the frame (and re-assert it now and then)
            self._write(_report(m.txn, 0x0F, 0x02, bytes((0x00, 0x00, 0x08))))
            self._last_show = now

    def send_static(self, color, bright):
        self.send([color] * len(self.leds), bright)

    def send_off(self):
        self.send([(0, 0, 0)] * len(self.leds), 1.0)

    def preview_layout(self):
        dots = [(i, s) for i, s in enumerate(self._styles) if s]
        return {"frame": dv.DESK[self.kind], "shape": self.kind, "dots": dots}

    def close(self):
        if self.handle:
            _k32.CloseHandle(self.handle)
            self.handle = None


class RazerUsbBackend:
    name = "Razer direct USB"

    def __init__(self):
        self.enabled = True
        self.wanted = False   # set by the engine: True when Synapse's Chroma SDK isn't usable
        self.active = False   # actually driving devices
        # Synapse's app does the actual drawing for its Chroma SDK service: with the app closed,
        # the service still accepts commands but nothing reaches the devices.
        self.synapse_app = synapse_running()
        self.status = "Starting…"
        self._devices = {}    # pid -> RazerUsbDevice
        self._stop = threading.Event()

    def start(self):
        threading.Thread(target=self._run, daemon=True, name="razer-usb").start()

    def stop(self):
        self._stop.set()
        for d in self._devices.values():
            d.close()

    def devices(self):
        return list(self._devices.values()) if self.active else []

    def supports_present(self):
        """True if a Razer device this backend can drive is plugged in."""
        return bool(self._devices)

    def _scan(self):
        present = {}
        for path in _hid_paths():
            low = path.lower()
            if f"vid_{RAZER_VID:04x}" not in low or "&col" in low:
                continue
            for pid, model in MODELS.items():
                if f"pid_{pid:04x}" in low and f"mi_{model.interface:02x}" in low:
                    present[pid] = path
        for pid in list(self._devices):  # unplugged
            if pid not in present:
                self._devices.pop(pid).close()
        for pid, path in present.items():
            if pid not in self._devices:
                h = _k32.CreateFileW(path, 0, 3, None, 3, 0, None)  # no access rights needed for feature reports
                if h != _INVALID:
                    self._devices[pid] = RazerUsbDevice(self, pid, MODELS[pid], h)

    def _run(self):
        while not self._stop.is_set():
            try:
                self.synapse_app = synapse_running()
                self._scan()
                n = len(self._devices)
                if not self.enabled:
                    self.active, self.status = False, "Turned off"
                elif not self.wanted:
                    self.active = False
                    self.status = "Standing by — Razer Synapse is handling Razer devices"
                elif self.synapse_app:
                    self.active = False
                    self.status = "Razer Synapse is running but not accepting apps — close Synapse to control Razer devices directly"
                elif n:
                    if not self.active:
                        for d in self._devices.values():
                            d._last_show = 0.0  # taking over: send full frames straight away
                    self.active = True
                    self.status = f"Controlling {n} device{'s' if n != 1 else ''} directly"
                else:
                    self.active, self.status = False, "No supported Razer devices found"
            except Exception as e:
                self.active, self.status = False, f"Couldn't read devices ({type(e).__name__})"
            self._stop.wait(3)
