#!/usr/bin/env python3
"""
Turn the optimistic 2D order-2 entropy floor (2.8 KB) into a REAL achievable
number, by measuring an *adaptive* 2D context model. Code length of an ideal
arithmetic coder == sum of -log2(p) under the sequentially-updated model, so
this pays the model-learning ("table") cost implicitly and honestly.

Model: 2D PPM-style hierarchical backoff per block cell.
  order2 = (left, up)  ->  order1 = blend(left, up)  ->  order0  ->  uniform
Counts are updated after every symbol (adaptive). Grouped per tileset so
contexts share across maps of the same tileset but never collide across
tilesets. Border neighbours use sentinel -1.

Stdlib only. Reuses corpus.py loaders.
"""
import os, math
from collections import Counter, defaultdict

__file__ = "./grid_coder.py"
exec(open("corpus.py").read().split("def main")[0])   # loaders + TILESET_STEM + ROOT

KB = 1024.0


def adaptive_bits(maps_2d, A, alpha, beta):
    """Total bits to code all cells with adaptive 2D backoff model.
    A = alphabet size (block count). alpha/beta = backoff concentrations."""
    c0 = Counter(); N0 = 0
    c1 = defaultdict(Counter); N1 = defaultdict(int)   # keyed by single neighbour value
    c2 = defaultdict(Counter); N2 = defaultdict(int)   # keyed by (left, up)
    bits = 0.0
    base = 1.0 / A
    for grid in maps_2d:
        H = len(grid); W = len(grid[0]) if H else 0
        for y in range(H):
            for x in range(W):
                s = grid[y][x]
                L = grid[y][x-1] if x else -1
                U = grid[y-1][x] if y else -1
                # order-0
                p0 = (c0[s] + base) / (N0 + 1.0)
                # order-1: blend left-context and up-context predictions
                pL = (c1[L][s] + alpha * p0) / (N1[L] + alpha)
                pU = (c1[U][s] + alpha * p0) / (N1[U] + alpha)
                p1 = 0.5 * (pL + pU)
                # order-2: (left, up)
                k2 = (L, U)
                p2 = (c2[k2][s] + beta * p1) / (N2[k2] + beta)
                bits += -math.log2(p2)
                # update
                c0[s] += 1; N0 += 1
                c1[L][s] += 1; N1[L] += 1
                c1[U][s] += 1; N1[U] += 1
                c2[k2][s] += 1; N2[k2] += 1
    return bits


def main():
    dims = parse_map_dims(); headers = parse_map_headers()

    # group maps' 2D grids by tileset stem; track per-tileset alphabet (block count)
    by_stem = defaultdict(list)
    blockcount = {}
    for blk, mconst, tconst in headers:
        stem = TILESET_STEM.get(tconst); wh = dims.get(mconst)
        path = f"{ROOT}/maps/{blk}.blk"
        if stem is None or wh is None or not os.path.exists(path):
            continue
        data = open(path, "rb").read(); W, H = wh
        if len(data) != W * H:
            continue
        if stem not in blockcount:
            bst = open(f"{ROOT}/gfx/blocksets/{stem}.bst", "rb").read()
            blockcount[stem] = max(1, len(bst) // 16)
        by_stem[stem].append([list(data[r*W:(r+1)*W]) for r in range(H)])

    total_cells = sum(len(g)*len(g[0]) for ms in by_stem.values() for g in ms)
    print(f"grids: {sum(len(v) for v in by_stem.values())} maps, "
          f"{len(by_stem)} tilesets, {total_cells} cells\n")

    print("=== adaptive 2D backoff coder (real, model cost included) ===")
    for alpha, beta in ((1,1),(2,4),(4,8),(8,16)):
        tot = 0.0
        for stem, ms in by_stem.items():
            A = max(blockcount[stem], 1 + max(s for g in ms for row in g for s in row))
            tot += adaptive_bits(ms, A, alpha, beta)
        B = tot / 8.0
        print(f"  alpha={alpha:<2} beta={beta:<2} : {B:8.0f} B = {B/KB:5.2f} KB")

    print("\n  reference: lzma(grids concat)=9276 B (9.1 KB), "
          "order-2 optimistic floor=2872 B (2.8 KB)")


if __name__ == "__main__":
    main()
