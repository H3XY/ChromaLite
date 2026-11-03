"""
Button customization: give mouse side buttons and keyboard macro keys new jobs.

Triggers
  * Mouse side buttons (Back / Forward, i.e. XBUTTON1 / XBUTTON2). Watched with
    a low-level mouse hook, installed only while one of them is customized.
  * F13-F24. No keyboard has these keys, so they're ideal targets for Razer
    macro keys (set each macro key to one of them in Synapse). They're caught
    with RegisterHotKey, a standard per-key Windows hotkey, so Prismatic never
    sees anything else you type.

Actions: default (leave alone), disabled, a key or shortcut, a media key,
launch an app/file/URL, type text, or a sequence of those with delays.
"""
import ctypes
import os
import queue
import threading
import time
from ctypes import wintypes as w

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# ------------------------------------------------------------------ triggers
TRIGGERS = [("mouse_x1", "Mouse: Back button"), ("mouse_x2", "Mouse: Forward button")] + \
           [(f"f{n}", f"F{n}") for n in range(13, 25)]
TRIGGER_IDS = {t for t, _ in TRIGGERS}
FKEY_VK = {f"f{n}": 0x7C + (n - 13) for n in range(13, 25)}  # VK_F13 = 0x7C ... VK_F24 = 0x87

MEDIA = {"play_pause": 0xB3, "next": 0xB0, "previous": 0xB1, "stop": 0xB2,
         "volume_up": 0xAF, "volume_down": 0xAE, "mute": 0xAD}
EXTENDED_VKS = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x5B, 0x5C, 0x5D, 0x6F, 0x90,
                0xA3, 0xA5} | set(MEDIA.values())
MODIFIER_VKS = {0x10, 0x11, 0x12, 0x5B, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5}

# ------------------------------------------------------------------ Win32
LRESULT = ctypes.c_ssize_t
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, w.WPARAM, w.LPARAM)
WH_MOUSE_LL, WM_XBUTTONDOWN, WM_XBUTTONUP, WM_HOTKEY = 14, 0x020B, 0x020C, 0x0312
WM_RECONFIGURE, WM_QUIT = 0x8000 + 10, 0x0012
LLMHF_INJECTED = 0x1
MOD_NOREPEAT = 0x4000
INPUT_KEYBOARD, KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 1, 0x1, 0x2, 0x4


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("pt", w.POINT), ("mouseData", w.DWORD), ("flags", w.DWORD), ("time", w.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", w.WORD), ("wScan", w.WORD), ("dwFlags", w.DWORD), ("time", w.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", w.LONG), ("dy", w.LONG), ("mouseData", w.DWORD), ("dwFlags", w.DWORD),
                ("time", w.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", w.DWORD), ("u", _INPUTUNION)]


user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, w.HINSTANCE, w.DWORD]
user32.SetWindowsHookExW.restype = w.HHOOK
user32.CallNextHookEx.argtypes = [w.HHOOK, ctypes.c_int, w.WPARAM, w.LPARAM]
user32.CallNextHookEx.restype = LRESULT
user32.UnhookWindowsHookEx.argtypes = [w.HHOOK]
user32.RegisterHotKey.argtypes = [w.HWND, ctypes.c_int, w.UINT, w.UINT]
user32.UnregisterHotKey.argtypes = [w.HWND, ctypes.c_int]
user32.PostThreadMessageW.argtypes = [w.DWORD, w.UINT, w.WPARAM, w.LPARAM]
user32.GetMessageW.argtypes = [ctypes.POINTER(w.MSG), w.HWND, w.UINT, w.UINT]
user32.SendInput.argtypes = [w.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
kernel32.GetModuleHandleW.restype = w.HMODULE


# ------------------------------------------------------------------ performing actions
def _key(vk, up=False):
    flags = (KEYEVENTF_EXTENDEDKEY if vk in EXTENDED_VKS else 0) | (KEYEVENTF_KEYUP if up else 0)
    i = INPUT(type=INPUT_KEYBOARD)
    i.u.ki = KEYBDINPUT(wVk=vk, wScan=0, dwFlags=flags, time=0, dwExtraInfo=0)
    return i


def _send(inputs):
    if inputs:
        arr = (INPUT * len(inputs))(*inputs)
        user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))


def press_shortcut(vks):
    """Press keys in order (modifiers first), then release in reverse."""
    vks = [int(v) for v in vks if 0 < int(v) < 256][:6]
    if vks:
        _send([_key(v) for v in vks] + [_key(v, up=True) for v in reversed(vks)])


def type_text(text):
    """Type text as Unicode input, so any character works regardless of keyboard layout."""
    inputs = []
    data = str(text)[:2000].encode("utf-16-le")
    for k in range(0, len(data), 2):  # UTF-16 code units (emoji are two)
        unit = int.from_bytes(data[k:k + 2], "little")
        for up in (False, True):
            i = INPUT(type=INPUT_KEYBOARD)
            i.u.ki = KEYBDINPUT(wVk=0, wScan=unit, dwFlags=KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if up else 0),
                                time=0, dwExtraInfo=0)
            inputs.append(i)
    _send(inputs)


def run_step(step):
    kind = step.get("type")
    if kind == "keys":
        press_shortcut(step.get("keys") or [])
    elif kind == "media" and step.get("media") in MEDIA:
        press_shortcut([MEDIA[step["media"]]])
    elif kind == "text":
        type_text(step.get("text") or "")
    elif kind == "launch" and (step.get("target") or "").strip():
        os.startfile(step["target"].strip())
    elif kind == "delay":
        time.sleep(max(0, min(10000, int(step.get("ms") or 0))) / 1000)


def run_action(action):
    kind = (action or {}).get("type", "default")
    if kind == "sequence":
        for step in (action.get("steps") or [])[:50]:
            run_step(step)
    else:
        run_step(action)


def clean_action(a, allow_sequence=True):
    """Validate an action coming from the interface; anything unexpected becomes 'default'."""
    a = a if isinstance(a, dict) else {}
    t = a.get("type")
    if t in ("default", "disabled"):
        return {"type": t}
    if t == "keys":
        keys = [int(k) for k in a.get("keys") or [] if isinstance(k, (int, float)) and 0 < int(k) < 256][:6]
        if keys:
            return {"type": "keys", "keys": keys, "label": str(a.get("label") or "")[:80]}
    if t == "media" and a.get("media") in MEDIA:
        return {"type": "media", "media": a["media"]}
    if t == "launch" and str(a.get("target") or "").strip():
        return {"type": "launch", "target": str(a["target"]).strip()[:1000]}
    if t == "text" and str(a.get("text") or ""):
        return {"type": "text", "text": str(a["text"])[:2000]}
    if t == "delay":
        try:
            return {"type": "delay", "ms": max(0, min(10000, int(a.get("ms") or 0)))}
        except (TypeError, ValueError):
            return {"type": "delay", "ms": 100}
    if t == "sequence" and allow_sequence:
        steps = [clean_action(s, allow_sequence=False) for s in (a.get("steps") or [])[:50]]
        steps = [s for s in steps if s["type"] not in ("default", "disabled")]
        if steps:
            return {"type": "sequence", "steps": steps}
    return {"type": "default"}


# ------------------------------------------------------------------ manager
class ButtonManager:
    def __init__(self, get_config):
        """get_config() -> {trigger id: action dict}; read on every reconfigure."""
        self.get_config = get_config
        self.last_pressed = None  # (trigger id, time) - shown in the app so you can identify keys
        self.status = "Starting…"
        self._tid = None
        self._hook = None
        self._hook_proc = HOOKPROC(self._mouse_proc)  # keep a reference
        self._mouse_actions = {}
        self._actions = queue.Queue()
        self._ready = threading.Event()

    def start(self):
        threading.Thread(target=self._run, daemon=True, name="buttons").start()
        threading.Thread(target=self._worker, daemon=True, name="button-actions").start()
        self._ready.wait(3)

    def reconfigure(self):
        if self._tid:
            user32.PostThreadMessageW(self._tid, WM_RECONFIGURE, 0, 0)

    def stop(self):
        if self._tid:
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
        self._actions.put(None)

    def test(self, action):
        self._actions.put(action)

    # internals -------------------------------------------------------
    def _worker(self):
        while True:
            action = self._actions.get()
            if action is None:
                return
            try:
                run_action(action)
            except Exception:
                pass

    def _apply(self):
        cfg = self.get_config() or {}
        self._mouse_actions = {}
        for btn, trig in ((1, "mouse_x1"), (2, "mouse_x2")):
            a = cfg.get(trig)
            if a and a.get("type", "default") != "default":
                self._mouse_actions[btn] = a
        want_hook = bool(self._mouse_actions)
        if want_hook and not self._hook:
            self._hook = user32.SetWindowsHookExW(WH_MOUSE_LL, self._hook_proc, kernel32.GetModuleHandleW(None), 0)
        elif not want_hook and self._hook:
            user32.UnhookWindowsHookEx(self._hook)
            self._hook = None
        n = sum(1 for t, a in cfg.items() if a and a.get("type", "default") != "default")
        self.status = f"{n} button{'s' if n != 1 else ''} customized" if n else "No buttons customized"

    def _mouse_proc(self, code, wparam, lparam):
        if code == 0 and wparam in (WM_XBUTTONDOWN, WM_XBUTTONUP):
            info = MSLLHOOKSTRUCT.from_address(lparam)
            if not info.flags & LLMHF_INJECTED:  # never react to input we (or others) synthesized
                btn = (info.mouseData >> 16) & 0xFFFF
                if wparam == WM_XBUTTONDOWN:
                    self.last_pressed = (f"mouse_x{btn}", time.time())
                action = self._mouse_actions.get(btn)
                if action:
                    if wparam == WM_XBUTTONDOWN and action.get("type") != "disabled":
                        self._actions.put(action)
                    return 1  # swallow both down and up so the original Back/Forward doesn't happen
        return user32.CallNextHookEx(None, code, wparam, lparam)

    def _run(self):
        self._tid = kernel32.GetCurrentThreadId()
        # F13-F24 are always registered (nothing else uses them), so the app can show which one a key sends.
        for i, (trig, vk) in enumerate(FKEY_VK.items(), start=1):
            user32.RegisterHotKey(None, i, MOD_NOREPEAT, vk)
        ids = {i: trig for i, trig in enumerate(FKEY_VK, start=1)}
        self._apply()
        self._ready.set()
        msg = w.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                trig = ids.get(msg.wParam)
                if trig:
                    self.last_pressed = (trig, time.time())
                    action = (self.get_config() or {}).get(trig)
                    if action and action.get("type", "default") not in ("default", "disabled"):
                        self._actions.put(action)
            elif msg.message == WM_RECONFIGURE:
                self._apply()
        for i in ids:
            user32.UnregisterHotKey(None, i)
        if self._hook:
            user32.UnhookWindowsHookEx(self._hook)
