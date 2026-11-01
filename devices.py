"""
The device model every lighting backend produces: a device is a list of LEDs
with positions, plus a way to send colors to it. Effects only ever see this,
so they work the same on any brand.

Positions:
  gx, gy  position on a shared "desk" layout, in key widths, so animations
          can flow from one device to the next;
  u, v    position within the device itself (0..1, left->right, top->bottom);
  key     SDK keyboard (row, col) when the LED sits under a known key, which
          lets effect files and key-press effects target specific keys.
"""


class Led:
    __slots__ = ("gx", "gy", "u", "v", "key")

    def __init__(self, gx, gy, u, v, key=None):
        self.gx, self.gy, self.u, self.v, self.key = gx, gy, u, v, key


# Where each kind of device sits on the shared desk layout: (x, y, width, height)
DESK = {
    "keyboard": (0.0, 0.0, 22.0, 6.0),
    "mousepad": (23.5, -0.5, 11.0, 8.0),
    "mouse": (27.0, 0.5, 4.0, 6.0),
    "other": (36.0, 0.0, 6.0, 6.0),
}


def grid(rows, cols, x0, y0, w, h, keys=False):
    out = []
    for r in range(rows):
        for c in range(cols):
            u, v = (c + 0.5) / cols, (r + 0.5) / rows
            out.append(Led(x0 + u * w, y0 + v * h, u, v, (r, c) if keys else None))
    return out


def perimeter(n, x0, y0, w, h):
    """LEDs running down the right edge, along the bottom, then up the left."""
    total, out = 2 * h + w, []
    for i in range(n):
        d = (i + 0.5) * total / n
        if d < h:
            x, y = x0 + w, y0 + d
        elif d < h + w:
            x, y = x0 + w - (d - h), y0 + h
        else:
            x, y = x0, y0 + h - (d - h - w)
        out.append(Led(x, y, (x - x0) / w, (y - y0) / h))
    return out


class Device:
    """Base class. Backends subclass it and implement send()."""

    def __init__(self, id, kind, name, brand, source, leds):
        self.id, self.kind, self.name, self.brand, self.source = id, kind, name, brand, source
        self.leds = leds
        self.label = name  # kept for older code paths
        self.vendor_id = None

    @property
    def available(self):
        """False while something else (e.g. Windows) holds control of the lights."""
        return True

    def send(self, colors, bright):
        raise NotImplementedError

    def send_static(self, color, bright):
        self.send([color] * len(self.leds), bright)

    def send_off(self):
        self.send([(0, 0, 0)] * len(self.leds), 1.0)

    def preview_layout(self):
        """How the app draws this device: a silhouette box and which LEDs to show
        as what. Returns {"frame": (x, y, w, h), "shape": str, "dots": [(i, style), ...]}."""
        x, y, w, h = DESK.get(self.kind, DESK["other"])
        return {"frame": (x, y, w, h), "shape": self.kind, "dots": [(i, "dot") for i in range(len(self.leds))]}
