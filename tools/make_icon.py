"""Generates assets/chromalite.ico (a rainbow ring) using only the standard library."""
import colorsys
import math
import os
import struct
import zlib

SIZES = (16, 24, 32, 48, 64, 128, 256)
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "chromalite.ico")


def pixel(x, y, n):
    """RGBA for one pixel, 4x supersampled for smooth edges."""
    acc = [0.0, 0.0, 0.0, 0.0]
    for sy in range(4):
        for sx in range(4):
            px = (x + (sx + 0.5) / 4) / n * 2 - 1
            py = (y + (sy + 0.5) / 4) / n * 2 - 1
            r = math.hypot(px, py)
            if r > 0.98:
                continue
            if 0.56 <= r <= 0.86:  # the rainbow ring
                h = (math.atan2(py, px) / (2 * math.pi) + 0.25) % 1.0
                c = colorsys.hsv_to_rgb(h, 0.85, 1.0)
            elif r < 0.22:  # center dot
                c = (0x44 / 255, 0xD6 / 255, 0x2C / 255)
            else:  # dark disc
                c = (0x12 / 255, 0x12 / 255, 0x14 / 255)
            acc[0] += c[0]
            acc[1] += c[1]
            acc[2] += c[2]
            acc[3] += 1
    a = acc[3]
    if a == 0:
        return (0, 0, 0, 0)
    return (int(acc[0] / a * 255), int(acc[1] / a * 255), int(acc[2] / a * 255), int(a / 16 * 255))


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
