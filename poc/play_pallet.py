#!/usr/bin/env python3
"""
pokered-nano — viewport/camera + terminal display adapter.

Engine shape (DESIGN s10):
  full map  --camera window-->  one GB screen (20x18 tiles = 160x144 px)
            --threshold-->  1-bit framebuffer
            --adapter-->  display (terminal here; PNG for verification)

The framebuffer is the engine's ONLY visual output. The terminal adapter
never reaches back into map/tile data — it only consumes 1-bit pixels.

Adapters:
  braille  : 2x4 px per cell -> 80x36, fits a normal terminal, correct aspect.
  block    : half-block (U+2580) + 24-bit color, warm ink/paper palette.
  png      : viewport to a scaled PNG (for visual verification).

Usage:  python play_pallet.py [--cam TX TY] [--mode braille|block|png]
Stdlib only.

NOTE (overworld.png shade direction, verified): id 0 = darkest .. id 3 =
lightest. Inked threshold: ids {0,1} -> ink, {2,3} -> paper.
"""

import os
import sys
import zlib
import struct

# Windows consoles default to cp1252; braille/half-block need UTF-8.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(__file__))
from roundtrip import decode_png_2bpp_gray, extract_tiles
from render_pallet import write_png_rgb, INK, PAPER, GRAY

ROOT = r"C:\Users\Anthony\pokered-nano\pokered-master"
PNG  = os.path.join(ROOT, "gfx", "tilesets", "overworld.png")
BLK  = os.path.join(ROOT, "maps", "PalletTown.blk")
BST  = os.path.join(ROOT, "gfx", "blocksets", "overworld.bst")
OUT  = os.path.dirname(__file__)
W, H = 10, 9                       # PalletTown size in blocks

VW_TILES, VH_TILES = 20, 18        # one GB screen, in 8x8 tiles
VW_PX, VH_PX = VW_TILES * 8, VH_TILES * 8   # 160 x 144


def load_map():
    """Return (tiles, tile_grid, TW, TH) — tile_grid[y][x] is a tile-id."""
    w, h, pixels = decode_png_2bpp_gray(PNG)
    tiles, _, _ = extract_tiles(w, h, pixels)
    blk = open(BLK, "rb").read()
    bst = open(BST, "rb").read()
    blocks = [bst[i*16:(i+1)*16] for i in range(len(bst)//16)]
    TW, TH = W*4, H*4
    grid = [[0]*TW for _ in range(TH)]
    for by in range(H):
        for bx in range(W):
            b = blocks[blk[by*W+bx]]
            for r in range(4):
                for c in range(4):
                    grid[by*4+r][bx*4+c] = b[r*4+c]
    return tiles, grid, TW, TH


def compose_viewport(tiles, grid, TW, TH, cam_tx, cam_ty):
    """Window the map at tile (cam_tx,cam_ty) into a 1-bit framebuffer.
    Returns fb[y][x] in {0,1}, 1 = ink. Camera is clamped to map bounds."""
    cam_tx = max(0, min(cam_tx, TW - VW_TILES))
    cam_ty = max(0, min(cam_ty, TH - VH_TILES))
    fb = [[0]*VW_PX for _ in range(VH_PX)]
    for vy in range(VH_TILES):
        for vx in range(VW_TILES):
            tile = tiles[grid[cam_ty+vy][cam_tx+vx]]
            for py in range(8):
                base = py*8
                ry = vy*8+py
                for px in range(8):
                    # inked threshold: color-id <= 1 is ink
                    fb[ry][vx*8+px] = 1 if tile[base+px] <= 1 else 0
    return fb, cam_tx, cam_ty


# --- display adapters: consume fb only ------------------------------------

# braille dot bit for (dx in 0..1, dy in 0..3)
_BRAILLE = {(0,0):0x01,(0,1):0x02,(0,2):0x04,(0,3):0x40,
            (1,0):0x08,(1,1):0x10,(1,2):0x20,(1,3):0x80}

def to_braille(fb):
    h, w = len(fb), len(fb[0])
    lines = []
    for cy in range(0, h, 4):
        line = []
        for cx in range(0, w, 2):
            bits = 0
            for dy in range(4):
                for dx in range(2):
                    if fb[cy+dy][cx+dx]:
                        bits |= _BRAILLE[(dx, dy)]
            line.append(chr(0x2800 + bits))
        lines.append("".join(line))
    return "\n".join(lines)


def to_braille_color(fb):
    """Braille (full 160x144 res in 80x36 cells) WITH the warm ink/paper
    palette: dots render in ink, gaps in paper. Color is a constant ink-on-paper
    (one escape per line), so it's cheap and tear-free -- the colored look at
    the full-screen-fitting braille resolution."""
    fr, fg, fbl = INK
    br, bg, bbl = PAPER
    sgr = f"\x1b[38;2;{fr};{fg};{fbl}m\x1b[48;2;{br};{bg};{bbl}m"
    h, w = len(fb), len(fb[0])
    lines = []
    for cy in range(0, h, 4):
        line = [sgr]
        for cx in range(0, w, 2):
            bits = 0
            for dy in range(4):
                for dx in range(2):
                    if fb[cy+dy][cx+dx]:
                        bits |= _BRAILLE[(dx, dy)]
            line.append(chr(0x2800 + bits))
        lines.append("".join(line))
    return "\n".join(lines)


# ASCII fallback: 1 char per 2x4 px cell (same footprint as braille -> 80x36),
# but using only plain keyboard characters, so it renders in ANY font/terminal.
# Density ramp indexed by how many of the 8 sub-pixels are ink (0..8).
_ASCII_RAMP = " .:-=+*#@"

def to_ascii(fb):
    h, w = len(fb), len(fb[0])
    lines = []
    for cy in range(0, h, 4):
        row = []
        for cx in range(0, w, 2):
            n = (fb[cy][cx] + fb[cy][cx+1] + fb[cy+1][cx] + fb[cy+1][cx+1]
                 + fb[cy+2][cx] + fb[cy+2][cx+1] + fb[cy+3][cx] + fb[cy+3][cx+1])
            row.append(_ASCII_RAMP[n])
        lines.append("".join(row))
    return "\n".join(lines)


# Half-block glyphs encoding a vertical 1x2 ink/paper pair. These four are
# CP437-universal (present in essentially every monospace font), unlike the
# quadrant blocks. Index bits: top=1, bottom=2.
_HALF = [" ", "▀", "▄", "█"]

def to_block(fb):
    """Color via half blocks with CONSTANT color. The vertical pixel pair is
    encoded in the GLYPH (space/▀/▄/█), so ink-on-paper is fixed for the whole
    frame -> one color escape per line, not thousands. Tear-free AND uses only
    universal glyphs (no quadrant-font dependency). 160x72 cells, full res."""
    fr, fg, fbl = INK
    br, bg, bbl = PAPER
    sgr = f"\x1b[38;2;{fr};{fg};{fbl}m\x1b[48;2;{br};{bg};{bbl}m"
    h, w = len(fb), len(fb[0])
    lines = []
    for cy in range(0, h, 2):
        r0, r1 = fb[cy], fb[cy+1]
        row = [sgr]
        for cx in range(w):
            row.append(_HALF[r0[cx] | (r1[cx] << 1)])
        lines.append("".join(row))
    return "\n".join(lines)


def to_png(fb, path, scale=4):
    rows = []
    for y in range(len(fb)):
        row = bytearray()
        for x in range(len(fb[0])):
            row += bytes(INK if fb[y][x] else PAPER)
        rows.append(row)
    write_png_rgb(path, len(fb[0]), len(fb), rows, scale=scale)


def main():
    args = sys.argv[1:]
    mode = "braille"
    cam = None
    i = 0
    while i < len(args):
        if args[i] == "--mode":
            mode = args[i+1]; i += 2
        elif args[i] == "--cam":
            cam = (int(args[i+1]), int(args[i+2])); i += 3
        else:
            i += 1

    tiles, grid, TW, TH = load_map()
    if cam is None:
        cam = ((TW - VW_TILES)//2, (TH - VH_TILES)//2)   # center the town
    fb, cx, cy = compose_viewport(tiles, grid, TW, TH, cam[0], cam[1])

    sys.stderr.write(
        f"map {TW}x{TH} tiles | viewport {VW_TILES}x{VH_TILES} "
        f"({VW_PX}x{VH_PX}px) | camera tile ({cx},{cy}) | mode {mode}\n")

    if mode == "braille":
        print(to_braille(fb))
    elif mode == "block":
        print(to_block(fb))
    elif mode == "png":
        p = os.path.join(OUT, "pallet_viewport.png")
        to_png(fb, p)
        sys.stderr.write(f"wrote {p}\n")
    else:
        sys.stderr.write(f"unknown mode {mode}\n")


if __name__ == "__main__":
    main()
