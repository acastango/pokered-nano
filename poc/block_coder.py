#!/usr/bin/env python3
"""Test the adaptive 2D backoff coder on blocksets (each block = 4x4 tile-index
grid). Does 2D modeling beat lzma (5948 B) like it did on map grids?"""
import os, math
from collections import Counter, defaultdict
__file__ = "./block_coder.py"
exec(open("corpus.py").read().split("def main")[0])  # loaders + TILESET_STEM + ROOT


def adaptive_bits(maps_2d, A, alpha, beta):
    c0 = Counter(); N0 = 0
    c1 = defaultdict(Counter); N1 = defaultdict(int)
    c2 = defaultdict(Counter); N2 = defaultdict(int)
    bits = 0.0; base = 1.0 / A
    for grid in maps_2d:
        H = len(grid); W = len(grid[0]) if H else 0
        for y in range(H):
            for x in range(W):
                s = grid[y][x]
                Ln = grid[y][x-1] if x else -1
                Un = grid[y-1][x] if y else -1
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


stems = sorted(set(TILESET_STEM.values()))
tot = 0.0
for s in stems:
    bst = open(f"{ROOT}/gfx/blocksets/{s}.bst", "rb").read()
    nb = len(bst) // 16
    grids = [[list(bst[b*16+r*4 : b*16+r*4+4]) for r in range(4)] for b in range(nb)]
    tot += adaptive_bits(grids, 257, 2, 4)
B = tot / 8.0
print(f"blocksets adaptive 2D coder: {B:.0f} B = {B/1024:.2f} KB  (lzma was 5948 B / 5.8 KB)")
