"""
Иконка приложения 256×256: кольцо реактора с треугольником, циан на тёмном.
Чистый Python (zlib), без Pillow. electron-builder сам сделает из PNG .ico.
Запуск: python scripts/make_icon.py
"""
import math
import struct
import zlib
from pathlib import Path

N = 256
C = (90, 217, 255)
BG = (4, 8, 13)


def px(x, y):
    cx = cy = (N - 1) / 2
    dx, dy = x - cx, y - cy
    r = math.hypot(dx, dy)
    a = 0.0
    col = BG
    if r <= 126:
        a = 1.0
    # кольцо
    ring = max(0.0, 1 - abs(r - 104) / 7)
    # внутреннее кольцо пунктиром
    ang = math.atan2(dy, dx)
    dash = 1.0 if (math.sin(ang * 12) > -0.3) else 0.0
    ring2 = max(0.0, 1 - abs(r - 80) / 2.5) * dash * 0.7
    # ядро
    core = max(0.0, 1 - r / 46) ** 1.4
    # треугольник
    tri = 0.0
    for i in range(3):
        a1 = -math.pi / 2 + i * 2 * math.pi / 3
        a2 = -math.pi / 2 + (i + 1) * 2 * math.pi / 3
        x1, y1 = math.cos(a1) * 56, math.sin(a1) * 56
        x2, y2 = math.cos(a2) * 56, math.sin(a2) * 56
        vx, vy = x2 - x1, y2 - y1
        t = max(0, min(1, ((dx - x1) * vx + (dy - y1) * vy) / (vx * vx + vy * vy)))
        d = math.hypot(dx - (x1 + t * vx), dy - (y1 + t * vy))
        tri = max(tri, max(0.0, 1 - d / 2.4))
    glow = max(ring, ring2, tri * 0.9)
    r_ = BG[0] + (C[0] - BG[0]) * glow + (255 - BG[0]) * core
    g_ = BG[1] + (C[1] - BG[1]) * glow + (255 - BG[1]) * core
    b_ = BG[2] + (C[2] - BG[2]) * glow + (255 - BG[2]) * core
    col = tuple(min(255, int(v)) for v in (r_, g_, b_))
    edge = max(0.0, min(1.0, 127 - r))      # сглаживание края
    return (*col, int(255 * a * edge) if r > 125 else int(255 * a))


def png(path: Path):
    raw = b"".join(b"\x00" + b"".join(struct.pack("BBBB", *px(x, y)) for x in range(N)) for y in range(N))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", N, N, 8, 6, 0, 0, 0)) + \
        chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    path.write_bytes(data)


if __name__ == "__main__":
    out = Path(__file__).resolve().parent.parent / "shell" / "icon.png"
    png(out)
    print("иконка:", out)
