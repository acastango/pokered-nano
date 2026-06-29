#!/usr/bin/env python3
"""
pokered-nano cross-corpus harness.

Tests the decisive question the single-tileset POC could not: once the SAME
tiles/blocks repeat across all of Kanto's maps, does bundle-level dedup
explode? Measures pattern reuse at every bundle size (node / quadrant / tile
/ block) over the whole corpus, and computes an end-to-end byte budget.

Reuses the decoder + classifier from roundtrip.py. Stdlib only.
"""

import os
import re
import math
import glob
from collections import Counter, defaultdict

import roundtrip as rt

ROOT = os.path.join(os.path.dirname(__file__), "..", "pokered-master")

# tileset constant -> gfx/blockset file stem (from gfx/tilesets.asm; several
# constants share one file).
TILESET_STEM = {
    "OVERWORLD": "overworld", "REDS_HOUSE_1": "reds_house", "MART": "pokecenter",
    "FOREST": "forest", "REDS_HOUSE_2": "reds_house", "DOJO": "gym",
    "POKECENTER": "pokecenter", "GYM": "gym", "HOUSE": "house",
    "FOREST_GATE": "gate", "MUSEUM": "gate", "UNDERGROUND": "underground",
    "GATE": "gate", "SHIP": "ship", "SHIP_PORT": "ship_port",
    "CEMETERY": "cemetery", "INTERIOR": "interior", "CAVERN": "cavern",
    "LOBBY": "lobby", "MANSION": "mansion", "LAB": "lab", "CLUB": "club",
    "FACILITY": "facility", "PLATEAU": "plateau",
}


# ---------------------------------------------------------------------------
# Parse the disassembly metadata.
# ---------------------------------------------------------------------------

def parse_map_dims():
    """MAP_CONSTANT -> (width, height) in blocks."""
    txt = open(f"{ROOT}/constants/map_constants.asm").read()
    dims = {}
    for m in re.finditer(r"map_const\s+(\w+)\s*,\s*(\d+)\s*,\s*(\d+)", txt):
        dims[m.group(1)] = (int(m.group(2)), int(m.group(3)))
    return dims


def parse_map_headers():
    """Each header -> (blk_name, map_constant, tileset_constant)."""
    out = []
    for path in glob.glob(f"{ROOT}/data/maps/headers/*.asm"):
        txt = open(path).read()
        m = re.search(r"map_header\s+(\w+)\s*,\s*(\w+)\s*,\s*(\w+)", txt)
        if m:
            out.append((m.group(1), m.group(2), m.group(3)))
    return out


# ---------------------------------------------------------------------------
# Load art for one tileset stem: list of 8x8 tiles as 64-pixel tuples, and
# the blockset (list of blocks, each a tuple of 16 tile indices, 4x4 layout).
# ---------------------------------------------------------------------------

_tileset_cache = {}

def load_tileset(stem):
    if stem in _tileset_cache:
        return _tileset_cache[stem]
    w, h, px = rt.decode_png_2bpp_gray(f"{ROOT}/gfx/tilesets/{stem}.png")
    tiles, tw, th = rt.extract_tiles(w, h, px)   # row-major, 16 wide
    bst = open(f"{ROOT}/gfx/blocksets/{stem}.bst", "rb").read()
    blocks = [tuple(bst[b * 16:b * 16 + 16]) for b in range(len(bst) // 16)]
    _tileset_cache[stem] = (tiles, blocks)
    return tiles, blocks


# content keys -------------------------------------------------------------

def tile_nodes(tile):
    """16 node descriptors (classified) for an 8x8 tile."""
    nodes = []
    for q in rt.tile_to_quadrants(tile):
        for n in rt.quadrant_to_nodes(q):
            nodes.append(rt.classify(n))
    return nodes


def main():
    dims = parse_map_dims()
    headers = parse_map_headers()
    print(f"corpus: {len(headers)} maps, {len(set(TILESET_STEM.values()))} unique tilesets\n")

    # ----- which tilesets are actually USED by maps, and total block placements
    stem_used = set()
    map_block_positions = 0     # total block cells across all maps
    map_tile_positions = 0      # total 8x8 tile cells across all maps
    used_maps = 0
    missing = []
    for blk, mconst, tconst in headers:
        stem = TILESET_STEM.get(tconst)
        wh = dims.get(mconst)
        path = f"{ROOT}/maps/{blk}.blk"
        if stem is None or wh is None or not os.path.exists(path):
            missing.append(blk); continue
        stem_used.add(stem)
        w, h = wh
        map_block_positions += w * h
        map_tile_positions += w * h * 16    # 16 tiles per block
        used_maps += 1

    # ===================================================================
    # MEASUREMENT 1 — cumulative ART dedup as tilesets are added.
    # Does node/quadrant/tile reuse grow across tilesets (sublinear pools)?
    # ===================================================================
    node_pool, quad_pool, tile_pool = set(), set(), set()
    block_pool = set()
    print("=== M1: cumulative unique pattern counts as tilesets accrete ===")
    print(f"{'after +tileset':<16}{'tiles':>8}{'uniqTile':>9}{'uniqQuad':>9}{'uniqNode':>9}{'uniqBlk':>8}")
    seen_tiles_total = 0
    for i, stem in enumerate(sorted(stem_used)):
        tiles, blocks = load_tileset(stem)
        for t in tiles:
            seen_tiles_total += 1
            tile_pool.add(t)
            ns = tile_nodes(t)
            for k in range(4):
                quad_pool.add(tuple(ns[k * 4:k * 4 + 4]))
            for d in ns:
                node_pool.add(d)
        for b in blocks:
            # block content = the actual pixels of its 16 tiles. Indices beyond
            # this tileset's gfx are shared font/text tiles (indoor maps share
            # VRAM with the font); key them globally by index as ('EXT', idx).
            content = []
            for idx in b:
                if idx < len(tiles):
                    content.append(tiles[idx])
                else:
                    ext = ("EXT", idx)
                    tile_pool.add(ext)
                    content.append(ext)
            block_pool.add(tuple(content))
        print(f"{stem:<16}{seen_tiles_total:>8}{len(tile_pool):>9}"
              f"{len(quad_pool):>9}{len(node_pool):>9}{len(block_pool):>8}")

    print()
    print(f"  total tiles across tilesets : {seen_tiles_total}")
    print(f"  unique tiles                : {len(tile_pool)}  "
          f"({100*len(tile_pool)/seen_tiles_total:.0f}% unique)")
    print(f"  unique quadrants            : {len(quad_pool)}")
    print(f"  unique nodes                : {len(node_pool)}")
    print(f"  unique blocks (by pixels)   : {len(block_pool)}")

    # ===================================================================
    # MEASUREMENT 2 — end-to-end byte budget for the WHOLE world.
    # Represent every map's full pixel content losslessly; compare schemes.
    # ===================================================================
    NB = rt.NODE_BITS
    uniq_tiles = list(tile_pool)
    tile_idx_bits = max(1, math.ceil(math.log2(len(uniq_tiles))))
    blk_idx_bits = max(1, math.ceil(math.log2(len(block_pool))))
    quad_idx_bits = max(1, math.ceil(math.log2(len(quad_pool))))

    # art pool storage (store each unique unit's pixels compactly). EXT font
    # tiles can't be decomposed here; count them as raw 16 B each.
    real_tiles = [t for t in uniq_tiles if not (isinstance(t, tuple) and t and t[0] == "EXT")]
    ext_count = len(uniq_tiles) - len(real_tiles)
    tile_pool_bytes = (sum(sum(NB[d[0]] for d in tile_nodes(t)) for t in real_tiles)
                       + ext_count * 16 * 8) / 8
    # a block stored as 16 tile-indices
    block_as_tilerefs_bytes = len(block_pool) * 16 * tile_idx_bits / 8

    print("\n=== M2: end-to-end byte budget (whole world, lossless) ===")
    print(f"  world size: {used_maps} maps, {map_block_positions} block-cells, "
          f"{map_tile_positions} tile-cells")
    print(f"  index widths: tile={tile_idx_bits}b quad={quad_idx_bits}b "
          f"block={blk_idx_bits}b")
    print()

    # Scheme TILE: map grids store a tile index per tile-cell + global tile pool
    sTILE = tile_pool_bytes + map_tile_positions * tile_idx_bits / 8
    # Scheme BLOCK (the game's structure): map grids store a block index per
    # block-cell + global block pool (blocks->tile refs) + global tile pool
    sBLOCK = (tile_pool_bytes + block_as_tilerefs_bytes
              + map_block_positions * blk_idx_bits / 8)

    # Original-ish baseline: per-tileset tile sheets (16B/tile) + blocksets
    # (16B/block) + map grids (1 byte/block-cell)
    orig_art = seen_tiles_total * 16
    orig_blocks = sum(len(load_tileset(s)[1]) for s in stem_used) * 16
    orig_maps = map_block_positions * 1
    orig_total = orig_art + orig_blocks + orig_maps

    print(f"  [TILE  bundle] tile pool {tile_pool_bytes:8.0f}B + grids "
          f"{map_tile_positions*tile_idx_bits/8:8.0f}B = {sTILE:8.0f}B")
    print(f"  [BLOCK bundle] tile pool {tile_pool_bytes:8.0f}B + block pool "
          f"{block_as_tilerefs_bytes:7.0f}B + grids "
          f"{map_block_positions*blk_idx_bits/8:7.0f}B = {sBLOCK:8.0f}B")
    print()
    print(f"  original-ish baseline (sheets+blocksets+grids): {orig_total:8.0f}B")
    print(f"    = art {orig_art} + blocksets {orig_blocks} + grids {orig_maps}")
    print()
    print(f"  BLOCK scheme vs baseline: {orig_total/sBLOCK:.2f}x   "
          f"({sBLOCK/1024:.1f} KB vs target 20 KB)")
    if missing:
        print(f"\n  (skipped {len(missing)} maps w/o dims/blk/tileset)")


if __name__ == "__main__":
    main()
