#!/usr/bin/env python3
"""
Art is the biggest chunk (lzma 11.7 KB). lzma sees a 1D byte stream; the pixel
art has 2D structure. Test whether PNG-style 2D prediction filters (sub/up/paeth)
applied in the IMAGE domain, then lzma, beats lzma on the packed 2bpp blob.
Also report the on-disk .png sizes (2D filter + DEFLATE) as a real-world ref.

Stdlib only. Reuses corpus.py / roundtrip.py loaders.
"""
import os, lzma, zlib
from collections import defaultdict

__file__ = "./art_coder.py"
import roundtrip as rt
exec(open("corpus.py").read().split("def main")[0])

KB = 1024.0
L = lambda b: len(lzma.compress(bytes(b), preset=9 | lzma.PRESET_EXTREME))


def paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p-a), abs(p-b), abs(p-c)
    if pa <= pb and pa <= pc: return a
    return b if pb <= pc else c


def filter_image(px, W, H, mode):
    """Per-pixel 2D filter on a W*H byte grid (values 0-3). mode: sub/up/paeth."""
    out = bytearray(len(px))
    for y in range(H):
        for x in range(W):
            i = y*W + x
            a = px[i-1] if x else 0          # left
            b = px[i-W] if y else 0          # up
            c = px[i-W-1] if (x and y) else 0  # up-left
            if mode == "sub":   pred = a
            elif mode == "up":  pred = b
            else:               pred = paeth(a, b, c)
            out[i] = (px[i] - pred) & 0xFF
    return out


def pack2bpp(tiles):
    out = bytearray()
    for t in tiles:
        for i in range(0, 64, 4):
            out.append((t[i]<<6)|(t[i+1]<<4)|(t[i+2]<<2)|t[i+3])
    return out


def main():
    stems = sorted(set(TILESET_STEM.values()))

    packed = bytearray()       # the raw 2bpp blob (current scheme)
    png_disk = 0               # on-disk png bytes
    raw_px_all = bytearray()   # 1 byte/pixel, all tilesets concatenated (image order)
    filt = {m: bytearray() for m in ("sub","up","paeth")}

    for s in stems:
        p = f"{ROOT}/gfx/tilesets/{s}.png"
        png_disk += os.path.getsize(p)
        w, h, px2d = rt.decode_png_2bpp_gray(p)
        tiles, _, _ = rt.extract_tiles(w, h, px2d)
        packed += pack2bpp(tiles)
        px = bytearray()
        for row in px2d:
            px += bytes(row)
        raw_px_all += px
        for m in filt:
            filt[m] += filter_image(px, w, h, m)

    print("=== ART compression ===")
    print(f"  packed 2bpp raw            : {len(packed):6d} B")
    print(f"  on-disk .png (2Dfilt+DEFL) : {png_disk:6d} B = {png_disk/KB:.1f} KB")
    print(f"  lzma(packed 2bpp)          : {L(packed):6d} B = {L(packed)/KB:.1f} KB  <- current best")
    print(f"  lzma(raw 1B/px, unfiltered): {L(raw_px_all):6d} B")
    for m in ("sub","up","paeth"):
        # repack filtered residues to 2bpp-ish? keep 1B/px for entropy coder to model
        print(f"  lzma(2Dfilter={m:<5} 1B/px): {L(filt[m]):6d} B = {L(filt[m])/KB:.1f} KB")

    # filtered THEN packed 2 bits (residues are small near 0 but wrap; try packing)
    print("\n  (1B/px keeps residue distribution legible for the entropy coder;")
    print("   packing to 2bpp would re-shatter the 2D-filter gains.)")


if __name__ == "__main__":
    main()
