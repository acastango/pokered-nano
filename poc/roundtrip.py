#!/usr/bin/env python3
"""
pokered-nano Phase 0 — round-trip proof of concept.

No renderer, no map loading, no compression. Prove the quadtree data
structure is lossless: decompose every 8x8 tile into quadrants -> 2x2 nodes,
classify each node, pool with dedup, recompose, and verify pixel-perfect.

Ground truth: pokered-master/gfx/tilesets/overworld.png (128x48, 2bpp gray).
Stdlib only (zlib) — no Pillow/numpy.
"""

import sys
import zlib
import struct
from collections import Counter

# ---------------------------------------------------------------------------
# Minimal PNG decoder: grayscale (color type 0), bit depth 2, non-interlaced.
# Returns (width, height, pixels) where pixels[y][x] is a color id 0..3.
# ---------------------------------------------------------------------------

def decode_png_2bpp_gray(path):
    data = open(path, "rb").read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")

    width = height = bit_depth = color_type = interlace = None
    idat = bytearray()
    i = 8
    while i < len(data):
        (length,) = struct.unpack(">I", data[i:i + 4])
        ctype = data[i + 4:i + 8]
        body = data[i + 8:i + 8 + length]
        if ctype == b"IHDR":
            width, height, bit_depth, color_type, _comp, _filt, interlace = \
                struct.unpack(">IIBBBBB", body)
        elif ctype == b"IDAT":
            idat += body
        elif ctype == b"IEND":
            break
        i += 12 + length  # length + type(4) + data + crc(4)

    if color_type != 0 or bit_depth != 2 or interlace != 0:
        raise ValueError(
            "decoder only handles 2bpp grayscale non-interlaced "
            f"(got ct={color_type} bd={bit_depth} il={interlace})")

    raw = zlib.decompress(bytes(idat))
    stride = (width * bit_depth + 7) // 8  # bytes per scanline (no filter byte)
    bpp = 1  # filtering unit for sub-byte depths is 1 byte

    # Unfilter scanlines in place.
    out = bytearray()
    prev = bytearray(stride)
    pos = 0
    for _ in range(height):
        ftype = raw[pos]; pos += 1
        line = bytearray(raw[pos:pos + stride]); pos += stride
        if ftype == 0:        # None
            pass
        elif ftype == 1:      # Sub
            for x in range(bpp, stride):
                line[x] = (line[x] + line[x - bpp]) & 0xFF
        elif ftype == 2:      # Up
            for x in range(stride):
                line[x] = (line[x] + prev[x]) & 0xFF
        elif ftype == 3:      # Average
            for x in range(stride):
                a = line[x - bpp] if x >= bpp else 0
                line[x] = (line[x] + ((a + prev[x]) >> 1)) & 0xFF
        elif ftype == 4:      # Paeth
            for x in range(stride):
                a = line[x - bpp] if x >= bpp else 0
                b = prev[x]
                c = prev[x - bpp] if x >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[x] = (line[x] + pr) & 0xFF
        else:
            raise ValueError(f"bad filter type {ftype}")
        out += line
        prev = line

    # Unpack 2-bit samples (MSB-first) into per-pixel color ids 0..3.
    pixels = [[0] * width for _ in range(height)]
    for y in range(height):
        row = out[y * stride:(y + 1) * stride]
        for x in range(width):
            byte = row[x >> 2]
            shift = 6 - 2 * (x & 3)
            pixels[y][x] = (byte >> shift) & 0x3
    return width, height, pixels


# ---------------------------------------------------------------------------
# Tile extraction: slice the sheet into 8x8 tiles, row-major.
# Each tile is a flat tuple of 64 color ids (row-major).
# ---------------------------------------------------------------------------

def extract_tiles(width, height, pixels):
    tw, th = width // 8, height // 8
    tiles = []
    for ty in range(th):
        for tx in range(tw):
            tile = []
            for py in range(8):
                for px in range(8):
                    tile.append(pixels[ty * 8 + py][tx * 8 + px])
            tiles.append(tuple(tile))
    return tiles, tw, th


# ---------------------------------------------------------------------------
# Quadtree decomposition.
#   tile(8x8) -> 4 quadrants(4x4): TL, TR, BL, BR
#   quadrant(4x4) -> 4 nodes(2x2): TL, TR, BL, BR
#   node = (p0,p1,p2,p3) = TL,TR,BL,BR pixels
# ---------------------------------------------------------------------------

def tile_to_quadrants(tile):
    """Return 4 quadrants, each a 4x4 flat tuple (row-major), order TL,TR,BL,BR."""
    def quad(qx, qy):
        out = []
        for ry in range(4):
            for rx in range(4):
                out.append(tile[(qy * 4 + ry) * 8 + (qx * 4 + rx)])
        return tuple(out)
    return [quad(0, 0), quad(1, 0), quad(0, 1), quad(1, 1)]


def quadrant_to_nodes(q):
    """Return 4 nodes, each (p0,p1,p2,p3)=TL,TR,BL,BR, order TL,TR,BL,BR."""
    def node(nx, ny):
        return (q[(ny * 2 + 0) * 4 + (nx * 2 + 0)],
                q[(ny * 2 + 0) * 4 + (nx * 2 + 1)],
                q[(ny * 2 + 1) * 4 + (nx * 2 + 0)],
                q[(ny * 2 + 1) * 4 + (nx * 2 + 1)])
    return [node(0, 0), node(1, 0), node(0, 1), node(1, 1)]


# ---------------------------------------------------------------------------
# Node classification. Lossless by construction (RAW is the always-correct
# fallback); UNIFORM / GRADIENT are recognized special cases that cost fewer
# bits. classify() returns a hashable descriptor; render_node() inverts it.
#
# Node layout: p0=TL p1=TR p2=BL p3=BR.
#   UNIFORM  : 1 color                       -> ("U", c)            ~3 bits
#   GRADIENT : exactly 2 colors in a clean   -> ("G", a, b, dir)    ~6 bits
#              directional split. dir:
#                0 H    columns differ   (a b / a b)  p0==p2, p1==p3
#                1 V    rows differ      (a a / b b)  p0==p1, p2==p3
#                2 D    diagonal/checker (a b / b a)  p0==p3, p1==p2
#   RAW      : anything else                 -> ("R", p0,p1,p2,p3)  8 bits
#
# Note (gradient-classifier open item): in a 2x2 2bpp block the "/" and "\"
# diagonals collapse to a single structural checker pattern, distinguished
# only by which color sits at TL (captured by a vs b). So three structural
# directions cover every clean 2-color split; the 1-vs-3 "corner" patterns
# are not clean directional gradients and fall through to RAW.
# ---------------------------------------------------------------------------

DIR_H, DIR_V, DIR_D = 0, 1, 2


def classify(node):
    p0, p1, p2, p3 = node
    colors = set(node)
    if len(colors) == 1:
        return ("U", p0)
    if len(colors) == 2:
        if p0 == p2 and p1 == p3:           # H: left col / right col
            return ("G", p0, p1, DIR_H)
        if p0 == p1 and p2 == p3:           # V: top row / bottom row
            return ("G", p0, p2, DIR_V)
        if p0 == p3 and p1 == p2:           # D: diagonal checker
            return ("G", p0, p1, DIR_D)
    return ("R", p0, p1, p2, p3)


def render_node(desc):
    """Invert classify(): descriptor -> (p0,p1,p2,p3)."""
    kind = desc[0]
    if kind == "U":
        c = desc[1]
        return (c, c, c, c)
    if kind == "G":
        _, a, b, d = desc
        if d == DIR_H:
            return (a, b, a, b)
        if d == DIR_V:
            return (a, a, b, b)
        if d == DIR_D:
            return (a, b, b, a)
        raise ValueError("bad gradient dir")
    if kind == "R":
        return tuple(desc[1:5])
    raise ValueError("bad node kind")


NODE_BITS = {"U": 3, "G": 6, "R": 8}  # DESIGN nominal storage cost per node


# ---------------------------------------------------------------------------
# Pools with content-addressed dedup. Nodes are stored INLINE inside quadrant
# descriptors (sharing doesn't pay at node level), so there is no node *index*
# pool — but we still tally unique node descriptors for stats. Quadrants and
# tiles are pooled and referenced by index.
# ---------------------------------------------------------------------------

class Pool:
    def __init__(self):
        self.items = []
        self.index = {}

    def intern(self, key):
        idx = self.index.get(key)
        if idx is None:
            idx = len(self.items)
            self.index[key] = idx
            self.items.append(key)
        return idx

    def __len__(self):
        return len(self.items)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else \
        "pokered-master/gfx/tilesets/overworld.png"

    w, h, pixels = decode_png_2bpp_gray(path)
    tiles, tw, th = extract_tiles(w, h, pixels)
    print(f"tileset: {path}")
    print(f"  image {w}x{h}  ->  {tw}x{th} = {len(tiles)} tiles of 8x8")

    node_pool = Pool()       # unique node descriptors (for stats only)
    quad_pool = Pool()       # unique quadrants: tuple of 4 node descriptors
    tile_pool = Pool()       # unique tiles: tuple of 4 quadrant indices

    node_kind_counts = Counter()   # over ALL node instances (16 per tile)
    tile_indices = []              # per source tile -> tile-pool index

    for tile in tiles:
        quad_idxs = []
        for q in tile_to_quadrants(tile):
            node_descs = []
            for node in quadrant_to_nodes(q):
                d = classify(node)
                node_kind_counts[d[0]] += 1
                node_pool.intern(d)
                node_descs.append(d)
            quad_idxs.append(quad_pool.intern(tuple(node_descs)))
        tile_indices.append(tile_pool.intern(tuple(quad_idxs)))

    # ----- VERIFY: recompose every source tile and compare pixel-for-pixel.
    def recompose(tile_idx):
        quad_idxs = tile_pool.items[tile_idx]
        out = [0] * 64
        for qi, quad_index in enumerate(quad_idxs):
            qx, qy = qi % 2, qi // 2
            node_descs = quad_pool.items[quad_index]
            for ni, desc in enumerate(node_descs):
                nx, ny = ni % 2, ni // 2
                p = render_node(desc)
                base_x = qx * 4 + nx * 2
                base_y = qy * 4 + ny * 2
                out[(base_y + 0) * 8 + (base_x + 0)] = p[0]
                out[(base_y + 0) * 8 + (base_x + 1)] = p[1]
                out[(base_y + 1) * 8 + (base_x + 0)] = p[2]
                out[(base_y + 1) * 8 + (base_x + 1)] = p[3]
        return tuple(out)

    mismatches = 0
    for src, tile in enumerate(tiles):
        if recompose(tile_indices[src]) != tile:
            mismatches += 1
    ok = mismatches == 0

    # ----- STATS
    total_nodes = sum(node_kind_counts.values())
    u, g, r = node_kind_counts["U"], node_kind_counts["G"], node_kind_counts["R"]

    # Storage model:
    #   quadrant pool: each unique quadrant stores its 4 nodes inline.
    #   tile pool:     each unique tile stores 4 quadrant indices (1 byte each).
    quad_bits = sum(sum(NODE_BITS[d[0]] for d in q) for q in quad_pool.items)
    tile_bits = len(tile_pool) * 4 * 8
    pool_bits = quad_bits + tile_bits
    # map-level: 1 index byte per source tile to name which pooled tile it is.
    map_bits = len(tiles) * 8

    orig_bits = len(tiles) * 16 * 8  # 16 bytes/tile original

    print()
    print(f"  ROUND TRIP: {'PASS (100% lossless)' if ok else f'FAIL ({mismatches} mismatched tiles)'}")
    print()
    print("  pools (deduped):")
    print(f"    unique nodes      {len(node_pool):5d}")
    print(f"    unique quadrants  {len(quad_pool):5d}")
    print(f"    unique tiles      {len(tile_pool):5d}  (of {len(tiles)} source tiles)")
    print()
    print(f"  node classification ({total_nodes} node instances, 16/tile):")
    print(f"    UNIFORM   {u:5d}  {100*u/total_nodes:5.1f}%")
    print(f"    GRADIENT  {g:5d}  {100*g/total_nodes:5.1f}%")
    print(f"    RAW       {r:5d}  {100*r/total_nodes:5.1f}%")
    print(f"    uniform+gradient = {100*(u+g)/total_nodes:.1f}%  "
          f"(DESIGN pass bar: >~80%)")
    print()
    print("  storage (this tileset's art only):")
    print(f"    quadrant pool (inline nodes)  {quad_bits/8:8.1f} B")
    print(f"    tile pool (4 idx/tile)        {tile_bits/8:8.1f} B")
    print(f"    pools total                   {pool_bits/8:8.1f} B")
    print(f"    + map tile refs (1B/tile)     {map_bits/8:8.1f} B")
    print(f"    avg bytes / source tile       {(pool_bits+map_bits)/8/len(tiles):6.2f}  vs 16.0 original")
    print(f"    compression vs raw art        {orig_bits/(pool_bits+map_bits):6.2f}x")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
