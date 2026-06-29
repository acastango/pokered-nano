#!/usr/bin/env python3
"""
INTERPRETER-IDEA PROBE. Test whether the block abstraction is overhead.

Today we store: grids (which block per cell, ~7.8KB) + blocksets (what tiles in
each block, ~5.9KB) = 13.7KB. A block is just a frequent 4x4 tile pattern.

So: EXPAND every map to its full TILE FIELD (each block -> its 4x4 tiles) and let
compression / 2D-modeling rediscover the blocks as repeated patterns. If the tile
field compresses below 13.7KB, the block abstraction was pure overhead and the
"store the field, interpret it" approach wins (and merges grids+blocksets).

Also run the adaptive 2D context coder on the tile field (captures left+up 2D
structure lzma's 1D byte stream misses). Art (11.4KB) is unaffected either way.

Stdlib only. Reuses corpus.py loaders.
"""
import os, math, lzma
from collections import Counter, defaultdict
__file__ = "./tilefield.py"
exec(open("corpus.py").read().split("def main")[0])  # loaders + TILESET_STEM + ROOT

KB = 1024.0
L = lambda b: len(lzma.compress(bytes(b), preset=9 | lzma.PRESET_EXTREME))


def adaptive_bits(maps_2d, A, alpha=2, beta=4):
    c0 = Counter(); N0 = 0
    c1 = defaultdict(Counter); N1 = defaultdict(int)
    c2 = defaultdict(Counter); N2 = defaultdict(int)
    bits = 0.0; base = 1.0 / A
    for grid in maps_2d:
        H = len(grid); W = len(grid[0]) if H else 0
        for y in range(H):
            row = grid[y]; prow = grid[y-1] if y else None
            for x in range(W):
                s = row[x]
                Ln = row[x-1] if x else -1
                Un = prow[x] if prow is not None else -1
                p0 = (c0[s] + base) / (N0 + 1.0)
                pL = (c1[Ln][s] + alpha * p0) / (N1[Ln] + alpha)
                pU = (c1[Un][s] + alpha * p0) / (N1[Un] + alpha)
                p1 = 0.5 * (pL + pU)
                k2 = (Ln, Un)
                p2 = (c2[k2][s] + beta * p1) / (N2[k2] + beta)
                bits += -math.log2(p2)
                c0[s] += 1; N0 += 1
                c1[Ln][s] += 1; N1[Ln] += 1
                c1[Un][s] += 1; N1[Un] += 1
                c2[k2][s] += 1; N2[k2] += 1
    return bits


def main():
    dims = parse_map_dims(); headers = parse_map_headers()

    fields_by_stem = defaultdict(list)   # tileset -> list of 2D tile grids
    all_field_bytes = bytearray()        # row-major concat, all maps
    cells = 0
    for blk, mconst, tconst in headers:
        stem = TILESET_STEM.get(tconst); wh = dims.get(mconst)
        path = f"{ROOT}/maps/{blk}.blk"
        if stem is None or wh is None or not os.path.exists(path):
            continue
        data = open(path, "rb").read(); W, H = wh
        if len(data) != W * H:
            continue
        _, blocks = load_tileset(stem)
        TW, TH = W * 4, H * 4
        field = [[0]*TW for _ in range(TH)]
        for by in range(H):
            for bx in range(W):
                B = data[by*W + bx]
                blk16 = blocks[B] if B < len(blocks) else (0,)*16
                for r in range(4):
                    for c in range(4):
                        field[by*4+r][bx*4+c] = blk16[r*4+c]
        fields_by_stem[stem].append(field)
        for row in field:
            all_field_bytes += bytes(row)
        cells += TW * TH

    print(f"tile field: {sum(len(v) for v in fields_by_stem.values())} maps, "
          f"{cells} tile cells (raw 1B/cell = {cells/KB:.1f} KB)\n")

    print("=== INTERPRETER PROBE: store the tile field, drop the block abstraction ===")
    lz = L(all_field_bytes)
    print(f"  lzma(tile field, row-major)      : {lz:6d} B = {lz/KB:.2f} KB")

    tot = 0.0
    for stem, fs in fields_by_stem.items():
        A = 1 + max(s for f in fs for row in f for s in row)
        tot += adaptive_bits(fs, A)
    ab = tot / 8.0
    print(f"  adaptive 2D coder (tile field)   : {ab:6.0f} B = {ab/KB:.2f} KB")
    print()
    print("  baseline to beat: grids 7.8 + blocksets 5.9 = 13.7 KB")
    best = min(lz, ab)
    print(f"  --> interpreter best {best/KB:.2f} KB vs 13.7 KB : "
          f"{'WINS' if best < 13.7*KB else 'LOSES'} "
          f"({(13.7*KB-best)/KB:+.2f} KB)")
    print(f"\n  full-corpus total if it wins: art 11.4 + {best/KB:.2f} "
          f"= {11.4 + best/KB:.2f} KB  (vs 25.1 KB current, 20 KB target)")


if __name__ == "__main__":
    main()
