import os

# Overworld layout round-trip POC.
#
# Thesis (DESIGN, overworld DSL): the TILE is the primitive (art + collision
# attach to tile-ids in a shared, amortized tileset table), but the least-data
# STORAGE unit for a map is the BLOCK grid (.blk) over a shared blockset. The
# DSL is authoring-only and COMPILES DOWN to the block grid.
#
# This proves the round-trip is lossless and confirms the size story:
#   real .blk  (block grid)   --expand-->  tile grid (the tile-primitive form)
#   tile grid  --auto-intern-->  block grid   ==?==  original .blk  (byte-exact)
#
# A Gen I block = 4x4 tiles = 16 bytes, row-major. A .blk byte = one block id.

ROOT = r"C:\Users\Anthony\pokered-nano\pokered-master"
BLK  = os.path.join(ROOT, "maps", "PalletTown.blk")
BST  = os.path.join(ROOT, "gfx", "blocksets", "overworld.bst")
W, H = 10, 9          # PalletTown size in blocks (map_constants.asm)

blk = open(BLK, "rb").read()          # 90 bytes: block ids, row-major WxH
bst = open(BST, "rb").read()          # 2048 bytes: 128 blocks x 16 tile-ids
assert len(blk) == W * H, (len(blk), W * H)
nblocks = len(bst) // 16
blocks = [bst[i*16:(i+1)*16] for i in range(nblocks)]   # each = 16 tile-ids (4x4)

# --- expand .blk -> full tile grid (the tile-primitive "authored" form) ---
# tile grid is (H*4) rows x (W*4) cols of tile-ids.
TW, TH = W * 4, H * 4
tile_grid = [[0] * TW for _ in range(TH)]
for by in range(H):
    for bx in range(W):
        b = blocks[blk[by * W + bx]]
        for r in range(4):
            for c in range(4):
                tile_grid[by * 4 + r][bx * 4 + c] = b[r * 4 + c]

# --- auto-intern: build reverse map (4x4 tile pattern -> block id) over the
#     WHOLE blockset, as a real compiler would (it doesn't know which are used).
#     first id wins on duplicate patterns. ---
pattern_to_id = {}
dupe_ids = {}
for bid, b in enumerate(blocks):
    key = bytes(b)
    if key in pattern_to_id:
        dupe_ids[bid] = pattern_to_id[key]   # bid renders identical to an earlier id
    else:
        pattern_to_id[key] = bid

# --- recompile: walk tile grid in 4x4 windows -> block id ---
recompiled = bytearray(W * H)
unknown = 0
for by in range(H):
    for bx in range(W):
        pat = bytes(
            tile_grid[by * 4 + r][bx * 4 + c]
            for r in range(4) for c in range(4)
        )
        bid = pattern_to_id.get(pat)
        if bid is None:
            unknown += 1
            bid = 0
        recompiled[by * W + bx] = bid

# --- diff against original .blk, byte for byte ---
exact = sum(1 for a, b in zip(blk, recompiled) if a == b)
# a mismatch is "render-equivalent" if it differs only because the original used
# a duplicate-pattern block id (same 16 tiles, different id).
render_equiv = True
mismatches = []
for i, (a, b) in enumerate(zip(blk, recompiled)):
    if a != b:
        same_pattern = blocks[a] == blocks[b]
        mismatches.append((i, a, b, same_pattern))
        if not same_pattern:
            render_equiv = False

print("=== Overworld layout round-trip: PalletTown ===")
print(f"map: {W}x{H} blocks   tileset: overworld   blockset: {nblocks} blocks")
print(f"duplicate-pattern block ids in blockset: {len(dupe_ids)}")
print(f"unknown 4x4 windows (no matching block): {unknown}")
print()
print(f"block-id exact match: {exact}/{len(blk)} bytes "
      f"({'PASS' if exact == len(blk) else 'see mismatches'})")
if mismatches:
    print(f"mismatches: {len(mismatches)} "
          f"(all render-equivalent: {render_equiv})")
    for i, a, b, sp in mismatches[:10]:
        print(f"  cell {i:3d} (row {i//W},col {i%W}): orig {a:3d} -> recompiled {b:3d}"
              f"  {'[same 16 tiles]' if sp else '[DIFFERENT TILES]'}")
print()

# --- data story: which unit is least-data ---
print("=== size story (why block grid is the storage unit) ===")
print(f"  tile grid  : {TW}x{TH} = {TW*TH:5d} B  (tile-primitive form)")
print(f"  block grid : {W}x{H} = {len(blk):5d} B  (.blk, {TW*TH/len(blk):.0f}x smaller)")
print(f"  blockset   : {len(bst):5d} B  (shared/amortized across all overworld maps)")
print()
used = set(blk)
print(f"  PalletTown uses {len(used)} distinct blocks of {nblocks} "
      f"({100*len(used)/nblocks:.0f}% of blockset)")
