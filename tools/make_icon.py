"""Generates assets/prismatic.ico (a prism with a spectrum edge and a blue core) using only the
standard library. Drawn in the same 48x48 coordinates as the logo SVG in ui/app.js."""
import colorsys
import math
import os
import struct
import zlib

SIZES = (16, 24, 32, 48, 64, 128, 256)
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "prismatic.ico")

TRI = ((24.0, 8.5), (38.5, 34.5), (9.5, 34.5))  # the prism
CX, CY = 24.0, 25.8                              # its centroid
CORE = tuple((CX + (x - CX) * 0.42, CY + (y - CY) * 0.42) for x, y in TRI)
BG, GLASS = (0x0B, 0x0E, 0x14), (0x12, 0x1A, 0x28)


def seg_dist(p, a, b):
    ax, ay = p[0] - a[0], p[1] - a[1]
    bx, by = b[0] - a[0], b[1] - a[1]
    t = max(0.0, min(1.0, (ax * bx + ay * by) / (bx * bx + by * by)))
    return math.hypot(ax - bx * t, ay - by * t)


def inside(p, tri):
    (x1, y1), (x2, y2), (x3, y3) = tri
    d1 = (p[0] - x2) * (y1 - y2) - (x1 - x2) * (p[1] - y2)
    d2 = (p[0] - x3) * (y2 - y3) - (x2 - x3) * (p[1] - y3)
    d3 = (p[0] - x1) * (y3 - y1) - (x3 - x1) * (p[1] - y1)
    return not ((d1 < 0 or d2 < 0 or d3 < 0) and (d1 > 0 or d2 > 0 or d3 > 0))


def sample(x, y):
    """RGB at a point in 48x48 logo space, or None outside the round badge."""
    if math.hypot(x - 24, y - 24) > 23.5:
        return None
    edge = min(seg_dist((x, y), TRI[i], TRI[(i + 1) % 3]) for i in range(3))
    if edge < 2.4:  # spectrum edge: hue runs around the prism
        h = (math.atan2(y - CY, x - CX) / (2 * math.pi) + 0.25) % 1.0
        return tuple(v * 255 for v in colorsys.hsv_to_rgb(h, 0.8, 1.0))
    if inside((x, y), CORE):  # glowing core, light to deep blue
        k = min(1.0, max(0.0, (y - CORE[0][1]) / (CORE[1][1] - CORE[0][1])))
        return (92 - 45 * k, 176 - 36 * k, 255)
    if inside((x, y), TRI):
        return GLASS
    return BG


def pixel(px, py, n):
    acc, hits = [0.0, 0.0, 0.0], 0
    for sy in range(4):
        for sx in range(4):
            c = sample((px + (sx + 0.5) / 4) / n * 48, (py + (sy + 0.5) / 4) / n * 48)
            if c is not None:
                acc[0] += c[0]
                acc[1] += c[1]
                acc[2] += c[2]
                hits += 1
    if not hits:
        return (0, 0, 0, 0)
    return (int(acc[0] / hits), int(acc[1] / hits), int(acc[2] / hits), int(hits / 16 * 255))


def png(n):
    rows = b"".join(b"\x00" + b"".join(bytes(pixel(x, y, n)) for x in range(n)) for y in range(n))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", n, n, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b""))


def main():
    images = [png(n) for n in SIZES]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries = b""
    for n, data in zip(SIZES, images):
        entries += struct.pack("<BBBBHHII", n % 256, n % 256, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "wb") as f:
        f.write(header + entries + b"".join(images))
    print("wrote", os.path.normpath(OUT))


if __name__ == "__main__":
    main()
