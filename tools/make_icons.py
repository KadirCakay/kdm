"""Eklenti simgelerini üretir (bağımlılıksız)."""
import struct, zlib
from pathlib import Path

def png(size):
    S = 4  # süper örnekleme (kenar yumuşatma)
    n = size * S
    def inside(x, y):
        # yuvarlatılmış kare
        r = n * 0.22
        cx = min(max(x, r), n - r); cy = min(max(y, r), n - r)
        return (x - cx) ** 2 + (y - cy) ** 2 <= r * r
    def arrow(x, y):
        u, v = x / n, y / n
        if 0.42 <= u <= 0.58 and 0.18 <= v <= 0.52: return True          # gövde
        if 0.52 <= v <= 0.72 and abs(u - 0.5) <= (0.72 - v) * 1.1: return True  # uç
        if 0.78 <= v <= 0.86 and 0.24 <= u <= 0.76: return True          # taban çizgisi
        return False
    rows = []
    for py in range(size):
        row = bytearray([0])
        for px in range(size):
            bg = fg = 0
            for sy in range(S):
                for sx in range(S):
                    x, y = px * S + sx + .5, py * S + sy + .5
                    if inside(x, y):
                        bg += 1
                        if arrow(x, y): fg += 1
            a = bg / (S * S); f = fg / max(bg, 1)
            r = int(37 + (255 - 37) * f); g = int(99 + (255 - 99) * f); b = int(235 + (255 - 235) * f)
            row += bytes([r, g, b, int(a * 255)])
        rows.append(bytes(row))
    def chunk(t, d): return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b""))

out = Path(__file__).resolve().parent.parent / "extension" / "icons"
out.mkdir(parents=True, exist_ok=True)
for s in (16, 32, 48, 128):
    (out / f"{s}.png").write_bytes(png(s))
print("ok")
