#!/usr/bin/env python3
"""
pokered-nano — first renderer. Pallet Town to pixels.

Pipeline (all proven pieces, just composed):
  overworld.png  --decode 2bpp-->  96 tiles of 8x8 color-ids (roundtrip.py)
  PalletTown.blk --expand via blockset--> tile grid (overworld_roundtrip.py)
  tile grid + tile art  --compose-->  full-map pixel buffer (color-ids 0..3)
  pixel buffer  --threshold-->  1-bit "inked" framebuffer

Rendering contract (DESIGN s10): engine output = a 1-bit framebuffer; the
display is a swappable adapter. Here two adapters: a 4-shade grayscale PNG
(reference, to confirm shade direction) and the 1-bit inked PNG (the target
look: dark ink on warm grey-tan paper, palette applied at render = 0 bytes).

Stdlib only.
"""

import os
import zlib
import struct

# reuse the proven 2bpp PNG decoder
import sys
sys.path.insert(0, os.path.dirname(__file__))
from roundtrip import decode_png_2bpp_gray, extract_tiles

ROOT = r"C:\Users\Anthony\pokered-nano\pokered-master"
PNG  = os.path.join(ROOT, "gfx", "tilesets", "overworld.png")
BLK  = os.path.join(ROOT, "maps", "PalletTown.blk")
BST  = os.path.join(ROOT, "gfx", "blocksets", "overworld.bst")
OUT  = os.path.dirname(__file__)
W, H = 10, 9                      # PalletTown size in blocks

# Empirically (see first render): in these overworld PNGs the open ground sits
# at the HIGH id end, so to match the game's light-ground look we map id 0 =
# darkest .. id 3 = lightest.
GRAY = {0: 0, 1: 85, 2: 170, 3: 255}
# "inked" 1-bit: ink = the two darker ids (0,1); paper = the two lighter (2,3).
PAPER = (183, 174, 158)          # warm grey-tan (DESIGN option BL)
INK   = (54, 50, 46)


def write_png_rgb(path, w, h, rgb_rows, scale=1):
    """rgb_rows[y] = flat list of length w*3. Nearest-neighbor scale up."""
    raw = bytearray()
    for y in range(h):
        row = rgb_rows[y]
        # scale horizontally
        sline = bytearray()
        for x in range(w):
            px = row[x*3:x*3+3]
            sline += px * scale
        for _ in range(scale):       # scale vertically
            raw.append(0)            # filter type 0 (None)
            raw += sline
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff))
    ihdr = struct.pack(">IIBBBBB", w*scale, h*scale, 8, 2, 0, 0, 0)
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", ihdr)
           + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
           + chunk(b"IEND", b""))
    open(path, "wb").write(png)


def main():
    # --- tile art ---
    w, h, pixels = decode_png_2bpp_gray(PNG)
    tiles, tw, th = extract_tiles(w, h, pixels)   # tiles[i] = 64 color-ids
    print(f"tileset {os.path.basename(PNG)}: {w}x{h} -> {len(tiles)} tiles")

    # --- expand .blk -> tile grid ---
    blk = open(BLK, "rb").read()
    bst = open(BST, "rb").read()
    blocks = [bst[i*16:(i+1)*16] for i in range(len(bst)//16)]
    TW, TH = W*4, H*4                              # tile grid dims (40x36)
    tile_grid = [[0]*TW for _ in range(TH)]
    for by in range(H):
        for bx in range(W):
            b = blocks[blk[by*W+bx]]
            for r in range(4):
                for c in range(4):
                    tile_grid[by*4+r][bx*4+c] = b[r*4+c]

    maxid = max(max(row) for row in tile_grid)
    print(f"map tile grid: {TW}x{TH}; tile-id range used: 0..{maxid} "
          f"(tiles available: {len(tiles)})")
    if maxid >= len(tiles):
        print("  !! tile grid references tiles beyond the sheet — will clamp")

    # --- compose full pixel buffer (color-ids 0..3) ---
    PW, PH = TW*8, TH*8                            # 320x288
    buf = [[0]*PW for _ in range(PH)]
    for gy in range(TH):
        for gx in range(TW):
            tid = tile_grid[gy][gx]
            tile = tiles[tid] if tid < len(tiles) else tiles[0]
            for py in range(8):
                base = py*8
                ry = gy*8+py
                for px in range(8):
                    buf[ry][gx*8+px] = tile[base+px]

    # --- adapter 1: 4-shade grayscale reference ---
    gray_rows = []
    for y in range(PH):
        row = bytearray()
        for x in range(PW):
            v = GRAY[buf[y][x]]
            row += bytes((v, v, v))
        gray_rows.append(row)
    p1 = os.path.join(OUT, "pallet_4shade.png")
    write_png_rgb(p1, PW, PH, gray_rows, scale=3)

    # --- adapter 2: 1-bit inked (target look) ---
    ink_rows = []
    for y in range(PH):
        row = bytearray()
        for x in range(PW):
            row += bytes(INK if buf[y][x] <= 1 else PAPER)
        ink_rows.append(row)
    p2 = os.path.join(OUT, "pallet_inked.png")
    write_png_rgb(p2, PW, PH, ink_rows, scale=3)

    print(f"wrote {p1}  ({PW*3}x{PH*3})")
    print(f"wrote {p2}  ({PW*3}x{PH*3})")


if __name__ == "__main__":
    main()
