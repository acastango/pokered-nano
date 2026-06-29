#!/usr/bin/env python3
"""
pokered-nano — player + movement + collision + camera-follow.

Builds on play_pallet.py (viewport/camera) and the disassembly's real rules:

  * Movement grid = 16x16 px cells = 2x2 of our 8x8 art tiles. Player coords
    (cx,cy) are on this grid (this is Gen I's wXCoord/wYCoord).
  * Collision (home/overworld.asm CheckTilePassable + player_state.asm
    _GetTileAndCoordsInFrontOfPlayer): the player's standing/collision tile is
    the BOTTOM-LEFT 8x8 art tile of its cell -> art_grid[2*cy+1][2*cx].
    A cell is walkable iff that tile-id is in the tileset's passable list
    (data/tilesets/collision_tile_ids.asm : Overworld_Coll).
  * Player sprite red.png: 6 frames of 16x16 (down,up,left,down-walk,up-walk,
    left-walk; right = left mirrored). id 3 = transparent, ids {1,2} = ink,
    id 0 = paper.

No live input in this harness, so a scripted path drives it; each step is
rendered and tiled into one contact-sheet PNG (+ final frame as braille).
Stdlib only.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))
from roundtrip import decode_png_2bpp_gray, extract_tiles
from render_pallet import write_png_rgb, INK, PAPER
from play_pallet import (load_map, VW_TILES, VH_TILES, VW_PX, VH_PX,
                         to_braille)

ROOT = r"C:\Users\Anthony\pokered-nano\pokered-master"
RED  = os.path.join(ROOT, "gfx", "sprites", "red.png")
COLL = os.path.join(ROOT, "data", "tilesets", "collision_tile_ids.asm")
OUT  = os.path.dirname(__file__)

# screen tile where the player's top-left sits when centered (lda_coord 8,9 ->
# standing tile is bottom-left of the 2x2, so top-left is screen tile (8,8)).
CENTER_TX, CENTER_TY = 8, 8

DOWN, UP, LEFT, RIGHT = "down", "up", "left", "right"


def parse_overworld_passable():
    """Read Overworld_Coll passable tile-ids from the disassembly."""
    txt = open(COLL).read()
    m = re.search(r"Overworld_Coll::\s*\n\s*coll_tiles ([^\n]+)", txt)
    ids = [int(t.strip().lstrip("$"), 16) for t in m.group(1).split(",")]
    return set(ids)


def load_player_frames():
    """Return dict facing -> [stand_frame, walk_frame], each a 16x16 grid of
    color-ids. right is left mirrored."""
    w, h, px = decode_png_2bpp_gray(RED)
    def frame(i):
        return [[px[i*16+y][x] for x in range(16)] for y in range(16)]
    def mirror(f):
        return [list(reversed(row)) for row in f]
    down, up, left = frame(0), frame(1), frame(2)
    downw, upw, leftw = frame(3), frame(4), frame(5)
    return {
        DOWN:  [down, downw],
        UP:    [up, upw],
        LEFT:  [left, leftw],
        RIGHT: [mirror(left), mirror(leftw)],
    }


def build_inked_tiles(tiles):
    """Map each 8x8 tile's color-ids to 1-bit ink/paper, preserving texture:
      * a tile using exactly TWO tones keeps both -> its darker tone = ink,
        lighter = paper (so naturally-2-tone grass/ground keeps its dither
        instead of collapsing flat under the global threshold);
      * otherwise the global inked rule (color-id <= 1 = ink).
    Returns a list of 8x8 flat lists of {0,1}, indexed by tile-id."""
    out = []
    for t in tiles:
        ids = sorted(set(t))
        if len(ids) == 2:
            inkset = {ids[0]}                       # darker of the two tones
        else:
            inkset = {c for c in ids if c <= 1}     # global threshold
        out.append([1 if c in inkset else 0 for c in t])
    return out


class World:
    def __init__(self):
        self.tiles, self.grid, self.TW, self.TH = load_map()
        self.passable = parse_overworld_passable()
        self.GW, self.GH = self.TW // 2, self.TH // 2   # movement-grid size
        self.inked_tiles = build_inked_tiles(self.tiles)

    def collision_tile(self, cx, cy):
        return self.grid[2*cy + 1][2*cx]                # bottom-left 8x8

    def walkable(self, cx, cy):
        if not (0 <= cx < self.GW and 0 <= cy < self.GH):
            return False
        return self.collision_tile(cx, cy) in self.passable


DELTA = {DOWN: (0, 1), UP: (0, -1), LEFT: (-1, 0), RIGHT: (1, 0)}


def compose_frame(world, frames, cx, cy, facing, walk_phase):
    """Window the map around the player and overlay the sprite. Returns a
    1-bit framebuffer (160x144)."""
    cam_tx = max(0, min(2*cx - CENTER_TX, world.TW - VW_TILES))
    cam_ty = max(0, min(2*cy - CENTER_TY, world.TH - VH_TILES))

    fb = [[0]*VW_PX for _ in range(VH_PX)]
    for vy in range(VH_TILES):
        for vx in range(VW_TILES):
            tile = world.inked_tiles[world.grid[cam_ty+vy][cam_tx+vx]]
            for py in range(8):
                ry = vy*8+py
                base = py*8
                for px in range(8):
                    fb[ry][vx*8+px] = tile[base+px]

    # overlay player sprite (16x16) at its world position within the viewport
    spr = frames[facing][walk_phase]
    sx = (2*cx - cam_tx) * 8
    sy = (2*cy - cam_ty) * 8
    for y in range(16):
        ry = sy + y
        if not (0 <= ry < VH_PX):
            continue
        for x in range(16):
            rx = sx + x
            if not (0 <= rx < VW_PX):
                continue
            cid = spr[y][x]
            if cid == 3:                 # transparent
                continue
            fb[ry][rx] = 1 if cid in (1, 2) else 0   # ink {1,2}, paper {0}
    return fb


def fb_to_rgb_rows(fb):
    rows = []
    for y in range(len(fb)):
        r = bytearray()
        for x in range(len(fb[0])):
            r += bytes(INK if fb[y][x] else PAPER)
        rows.append(r)
    return rows


def contact_sheet(frames_rgb, w, h, cols, scale, pad=6):
    """Tile a list of rgb-row-images into one grid PNG."""
    n = len(frames_rgb)
    rows_n = (n + cols - 1) // cols
    PW = cols*w + (cols+1)*pad
    PH = rows_n*h + (rows_n+1)*pad
    bg = (235, 230, 222)
    canvas = [bytearray(bg * PW) for _ in range(PH)]
    for idx, img in enumerate(frames_rgb):
        gx, gy = idx % cols, idx // cols
        ox = pad + gx*(w+pad)
        oy = pad + gy*(h+pad)
        for y in range(h):
            canvas[oy+y][ox*3:(ox+w)*3] = img[y]
    return PW, PH, canvas, scale


def main():
    world = World()
    frames = load_player_frames()
    print(f"world grid {world.GW}x{world.GH} cells | "
          f"passable ids: {sorted(world.passable)}")

    # find a sensible start: a walkable cell near the town centre-bottom.
    start = None
    for cy in range(world.GH-1, -1, -1):
        for cx in range(world.GW):
            if world.walkable(cx, cy):
                start = (cx, cy); break
        if start: break
    cx, cy = start
    print(f"start cell {start}  collision-tile ${world.collision_tile(cx,cy):02x}")

    # scripted path: a walk that exercises movement, a blocked bump, turns.
    path = ([UP]*5 + [RIGHT]*6 + [UP]*3 + [LEFT]*4 + [DOWN]*3)

    shots = []
    facing = UP
    phase = 0
    # initial frame
    shots.append(fb_to_rgb_rows(compose_frame(world, frames, cx, cy, facing, 0)))
    for mv in path:
        facing = mv
        dx, dy = DELTA[mv]
        tx, ty = cx+dx, cy+dy
        if world.walkable(tx, ty):
            cx, cy = tx, ty
            phase ^= 1                    # toggle walk animation
        # if blocked, we still turn to face that way (and stay put)
        shots.append(fb_to_rgb_rows(
            compose_frame(world, frames, cx, cy, facing, phase)))

    print(f"rendered {len(shots)} frames; final cell ({cx},{cy})")

    # contact sheet
    PW, PH, canvas, scale = contact_sheet(shots, VW_PX, VH_PX, cols=6, scale=2)
    p = os.path.join(OUT, "walk_pallet_sheet.png")
    write_png_rgb(p, PW, PH, canvas, scale=scale)
    print(f"wrote {p}  ({PW*scale}x{PH*scale})")

    # final frame as braille (engine output, terminal adapter)
    final_fb = compose_frame(world, frames, cx, cy, facing, phase)
    print("\nfinal frame (braille):")
    print(to_braille(final_fb))


if __name__ == "__main__":
    main()
