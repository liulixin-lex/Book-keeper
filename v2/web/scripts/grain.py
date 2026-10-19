# Regenerate: python3 scripts/grain.py public/grain.png
# Procedural matte grain: 160×160 RGBA tile of fine black/white speckles at very low alpha (seeded, tileable by construction).
# The CSS draws it at 80px, so on a 2x screen each speckle is one device pixel: a tooth, not visible dots.
import random, struct, zlib, sys
W = H = 160
rnd = random.Random(20261019)
rows = []
for y in range(H):
    row = bytearray([0])  # filter type 0
    for x in range(W):
        v = 255 if rnd.random() < 0.5 else 0
        a = int(rnd.random() ** 2 * 12)  # at most ~4.5% alpha, mostly far less: felt, not seen, behind small text
        row += bytes([v, v, v, a])
    rows.append(bytes(row))
raw = b"".join(rows)
def chunk(t, d):
    return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", W, H, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
open(sys.argv[1], "wb").write(png)
print(len(png), "bytes")
