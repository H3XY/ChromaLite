"""
Devices from any brand that support Windows 11 Dynamic Lighting (the HID
LampArray standard): Logitech, Corsair, SteelSeries, HyperX, ASUS, Razer, ...

Windows reports every lamp's physical position and, on keyboards, which key
it sits under, so effects map onto these devices properly.

Limitation: Windows only gives lighting control to the app in the foreground
(or to packaged apps chosen under Settings > Personalization > Dynamic
Lighting > Background light control). So these devices follow Prismatic
while its window is in front, and Windows takes them back otherwise.
"""
import array
import asyncio
import hashlib
import threading

import devices as dv
from chroma_effects import VK_TO_KEY

KINDS = {1: "keyboard", 2: "mouse"}  # LampArrayKind; everything else is drawn as a generic device
PURPOSE_CONTROL = 1                  # LampPurposes.Control: a key or button


class LampDevice(dv.Device):
    def __init__(self, lamp_array, device_id, name, slot):
        from winrt.windows.ui import Color
        from winrt.system import Array
        self._Color, self._Array = Color, Array
        self.la = lamp_array
        kind = KINDS.get(int(lamp_array.lamp_array_kind), "other")
        x, y, w, h = dv.DESK[kind]
        x += slot * (w + 1)  # several devices of one kind sit side by side
        bb = lamp_array.bounding_box
        bw, bh = max(bb.x, 1e-6), max(bb.y, 1e-6)
        keys = {}
        if kind == "keyboard":
            from winrt.windows.system import VirtualKey
            for vk, key in VK_TO_KEY.items():
                try:
                    for i in lamp_array.get_indices_for_key(VirtualKey(vk)):
                        keys.setdefault(int(i), key)
                except Exception:
                    pass
        leds, self._purposes = [], []
        for i in range(lamp_array.lamp_count):
            info = lamp_array.get_lamp_info(i)
            u = min(1.0, max(0.0, info.position.x / bw))
            v = min(1.0, max(0.0, info.position.y / bh))
            leds.append(dv.Led(x + u * w, y + v * h, u, v, keys.get(i)))
            self._purposes.append(int(info.purposes))
        vid = int(lamp_array.hardware_vendor_id)
        uid = hashlib.sha1(device_id.encode("utf-8")).hexdigest()[:8]
        super().__init__(f"dl:{vid:04x}:{int(lamp_array.hardware_product_id):04x}:{uid}", kind, name,
                         BRANDS.get(vid, "Dynamic Lighting"), "Windows Dynamic Lighting", leds)
        self.vendor_id, self.product_id = vid, int(lamp_array.hardware_product_id)
        self.frame = (x, y, w, h)
        self._indices = array.array("i", range(len(leds)))

    @property
    def available(self):
        try:
            return bool(self.la.is_available)
        except Exception:
            return False

    def send(self, colors, bright):
        if not self.available:
            return
        C = self._Color
        arr = self._Array(C, [C(a=255, r=max(0, min(255, int(c[0] * bright))), g=max(0, min(255, int(c[1] * bright))),
                                b=max(0, min(255, int(c[2] * bright)))) for c in colors])
        self.la.set_colors_for_indices(arr, self._indices)

    def send_static(self, color, bright):
        if self.available:
            r, g, b = (max(0, min(255, int(v * bright))) for v in color)
            self.la.set_color(self._Color(a=255, r=r, g=g, b=b))

    def send_off(self):
        if self.available:
            self.la.set_color(self._Color(a=255, r=0, g=0, b=0))

    def preview_layout(self):
        if self.kind == "keyboard":
            dots = [(i, "key" if p & PURPOSE_CONTROL else "glow") for i, p in enumerate(self._purposes)]
        else:
            dots = [(i, "dot") for i in range(len(self.leds))]
        return {"frame": self.frame, "shape": self.kind, "dots": dots}


BRANDS = {0x1532: "Razer", 0x046D: "Logitech", 0x1B1C: "Corsair", 0x1038: "SteelSeries", 0x0951: "HyperX",
          0x03F0: "HyperX", 0x0B05: "ASUS", 0x1E7D: "ROCCAT", 0x2516: "Cooler Master", 0x258A: "Glorious",
          0x31E3: "Wooting", 0x045E: "Microsoft", 0x0C45: "Keychron", 0x3434: "Keychron"}


class DynamicLightingBackend:
    name = "Windows Dynamic Lighting"

    def __init__(self):
        self.enabled = True
        self.status = "Starting…"
        self._devices = []
        self._stop = threading.Event()

    def start(self):
        threading.Thread(target=self._run, daemon=True, name="dynlight").start()

    def stop(self):
        self._stop.set()

    def devices(self, exclude_vendors=(), exclude_products=()):
        if not self.enabled:
            return []
        return [d for d in self._devices if d.vendor_id not in exclude_vendors
                and (d.vendor_id, d.product_id) not in exclude_products]

    async def _scan(self, known):
        from winrt.windows.devices.lights import LampArray
        from winrt.windows.devices.enumeration import DeviceInformation
        infos = await DeviceInformation.find_all_async_aqs_filter(LampArray.get_device_selector())
        found, slots = {}, {}
        for info in infos:
            dev = known.get(info.id)
            if dev is None:
                la = await LampArray.from_id_async(info.id)
                if la is None or not la.is_connected or la.lamp_count == 0:
                    continue
                kind = KINDS.get(int(la.lamp_array_kind), "other")
                slot = slots.get(kind, 0)
                dev = LampDevice(la, info.id, info.name or "Lighting device", slot)
            slots[dev.kind] = slots.get(dev.kind, 0) + 1
            found[info.id] = dev
        return found

    def _run(self):
        known = {}
        try:
            import winrt.windows.devices.lights  # noqa: F401  (fail early if bindings are missing)
            # Loaded by name at runtime for result lists and lamp positions; imported here so the
            # .exe build bundles them.
            import winrt.windows.foundation.collections  # noqa: F401
            import winrt.windows.foundation.numerics  # noqa: F401
        except Exception:
            self.status = "Not available on this system"
            return
        while not self._stop.is_set():
            try:
                known = asyncio.run(self._scan(known))
                self._devices = list(known.values())
                n = len(self._devices)
                self.status = f"{n} device{'s' if n != 1 else ''} found" if n else "No compatible devices found"
            except Exception as e:
                self.status = f"Couldn't read devices ({type(e).__name__})"
            self._stop.wait(5)
