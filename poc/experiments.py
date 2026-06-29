#!/usr/bin/env python3
"""
pokered-nano method bake-off. After abandoning the global quadtree, find which
information-theoretic approach actually compresses Kanto, whether they combine,
and what procedure falls out.

Strategy: use stdlib compressors as proxies for method *families* —
  zlib (DEFLATE)  ~ LZ77 dictionary + Huffman      (surface repeats + entropy)
  bz2  (BWT)      ~ context sorting + entropy        (local-context redundancy)
  lzma (LZMA)     ~ LZ + range coder + context       (strongest general ceiling)
Plus direct 2D conditional entropy on the block grids (= autotiling / local-rule
feasibility probe) and a per-map-vs-concatenated test (= cross-map redundancy).

Stdlib only. Reuses corpus.py loaders.
"""
import os, math, zlib, bz2, lzma
from collections import Counter, defaultdict

__file__ = "./experiments.py"
import roundtrip as rt
exec(open("corpus.py").read().split("def main")[0])   # loaders + TILESET_STEM + ROOT

KB = 1024.0

def comp(data):
    """Return dict of compressed sizes (bytes) by method family."""
    return {
        "raw":  len(data),
        "zlib": len(zlib.compress(data, 9)),
        "bz2":  len(bz2.compress(data, 9)),
        "lzma": len(lzma.compress(data, preset=9 | lzma.PRESET_EXTREME)),
    }

def show(label, d):
    print(f"  {label:<22} raw {d['raw']:6d} | zlib {d['zlib']:6d} | "
          f"bz2 {d['bz2']:6d} | lzma {d['lzma']:6d}  "
          f"(lzma {d['raw']/max(1,d['lzma']):.2f}x)")

def cond_entropy(maps_2d, order):
    """Empirical conditional entropy (bits) of block given context.
    order 0: none; 1: left; 2: left+up. Optimistic floor (ignores model cost)."""
    ctx = defaultdict(Counter)
    for grid in maps_2d:
        H = len(grid); W = len(grid[0]) if H else 0
        for y in range(H):
            for x in range(W):
                s = grid[y][x]
                if order == 0: c = ()
                elif order == 1: c = (grid[y][x-1] if x else -1,)
                else: c = (grid[y][x-1] if x else -1, grid[y-1][x] if y else -1)
                ctx[c][s] += 1
    bits = 0.0
    for c, cnt in ctx.items():
        n = sum(cnt.values())
        for s, k in cnt.items():
            bits += k * math.log2(n / k)
    return bits / 8.0


def main():
    dims = parse_map_dims(); headers = parse_map_headers()
    stems = sorted(set(TILESET_STEM.values()))

    # ---- build the three raw data streams ----
    art = bytearray()
    for s in stems:
        art += open(f"{ROOT}/gfx/tilesets/{s}.png", "rb").read()  # already DEFLATE'd png
    # better: raw 2bpp art = repack tiles. Use the .png decoded -> 2bpp bytes.
    art2bpp = bytearray()
    for s in stems:
        w,h,px = rt.decode_png_2bpp_gray(f"{ROOT}/gfx/tilesets/{s}.png")
        tiles,_,_ = rt.extract_tiles(w,h,px)
        for t in tiles:
            for i in range(0,64,4):
                art2bpp.append((t[i]<<6)|(t[i+1]<<4)|(t[i+2]<<2)|t[i+3])

    blocks = bytearray()
    for s in stems:
        blocks += open(f"{ROOT}/gfx/blocksets/{s}.bst","rb").read()

    grids = bytearray(); maps_2d = []; per_map_streams = []
    for blk,mconst,tconst in headers:
        stem = TILESET_STEM.get(tconst); wh = dims.get(mconst)
        path = f"{ROOT}/maps/{blk}.blk"
        if stem is None or wh is None or not os.path.exists(path): continue
        data = open(path,"rb").read(); W,H = wh
        if len(data) != W*H: continue
        grids += data; per_map_streams.append(data)
        maps_2d.append([list(data[r*W:(r+1)*W]) for r in range(H)])

    print("=== STREAM SIZES (raw) ===")
    print(f"  art(2bpp) {len(art2bpp)}  blocksets {len(blocks)}  grids {len(grids)}  "
          f"total {len(art2bpp)+len(blocks)+len(grids)} B = "
          f"{(len(art2bpp)+len(blocks)+len(grids))/KB:.1f} KB\n")

    print("=== EXP 1: general compressors per stream (method-family proxies) ===")
    da = comp(bytes(art2bpp)); db = comp(bytes(blocks)); dg = comp(bytes(grids))
    show("tile art (2bpp)", da)
    show("blocksets", db)
    show("map grids", dg)
    best = da["lzma"] + db["lzma"] + dg["lzma"]
    print(f"  --> lzma each stream, summed: {best} B = {best/KB:.1f} KB\n")

    print("=== EXP 2: cross-map redundancy (grids) ===")
    sep = sum(len(lzma.compress(m, preset=9)) for m in per_map_streams)
    tog = len(lzma.compress(bytes(grids), preset=9))
    print(f"  lzma each map separately, summed : {sep} B = {sep/KB:.1f} KB")
    print(f"  lzma all maps concatenated       : {tog} B = {tog/KB:.1f} KB")
    print(f"  cross-map redundancy captured    : {sep-tog} B "
          f"({100*(sep-tog)/sep:.0f}% smaller when shared)\n")

    print("=== EXP 3: 2D context entropy of grids (= autotile/local-rule probe) ===")
    for o,name in ((0,"order-0 (independent)"),(1,"order-1 (left)"),(2,"order-2 (left+up)")):
        print(f"  {name:<22}: {cond_entropy(maps_2d,o):.0f} B = {cond_entropy(maps_2d,o)/KB:.1f} KB")
    print("  (optimistic floor; ignores model-table cost)\n")

    print("=== EXP 4: does decomposition + lzma beat lzma alone on art? ===")
    # decomposed art bytes (node bit-stream) vs raw 2bpp, both then lzma
    print(f"  raw 2bpp -> lzma            : {da['lzma']} B")
    print(f"  (decomposition codec earlier gave ~15396 B uncompressed; "
          f"lzma on 2bpp already {da['lzma']} B)\n")

    print("=== EXP 5: combined end-to-end ceiling ===")
    everything = bytes(art2bpp) + bytes(blocks) + bytes(grids)
    allc = len(lzma.compress(everything, preset=9|lzma.PRESET_EXTREME))
    print(f"  lzma(art+blocks+grids together): {allc} B = {allc/KB:.1f} KB")
    print(f"  vs original ~74 KB  -> {73815/allc:.2f}x   vs target 20 KB")

if __name__ == "__main__":
    main()
