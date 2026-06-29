#!/usr/bin/env python3
"""
pokered-nano — general map loader (any Gen I map), for warps + entities.

Parses the disassembly directly (ground truth) into a MapData object holding
everything the engine needs to render and walk a map and to warp between maps:
  * dimensions          constants/map_constants.asm  (map_const)
  * tileset assets      data/maps/headers + gfx/tilesets.asm + tileset_headers
  * blockset + .blk     gfx/blocksets + maps/<Name>.blk
  * collision           data/tilesets/collision_tile_ids.asm (<Tileset>_Coll)
  * warps/signs/npcs    data/maps/objects/<Name>.asm

Coordinate facts (from macros/scripts/maps.asm):
  * warp_event/bg_event coords are raw map cells (16x16 movement grid).
  * object_event coords are raw too (the +4 in the macro is storage only).
  * warp_event dest id is 1-based -> destination index = id - 1.

Stdlib only.
"""

import os
import re

import sys
sys.path.insert(0, os.path.dirname(__file__))
from roundtrip import decode_png_2bpp_gray, extract_tiles
from walk_pallet import build_inked_tiles, DOWN, UP, LEFT, RIGHT

ROOT = r"C:\Users\Anthony\pokered-nano\pokered-master"


def _read(*parts):
    return open(os.path.join(ROOT, *parts), encoding="utf-8", errors="replace").read()


# --------------------------------------------------------------------------
# one-time parsed tables (cached at module level)
# --------------------------------------------------------------------------

def _build_map_index():
    """MAP_CONST -> (file_basename, TILESET_CONST)."""
    idx = {}
    hdir = os.path.join(ROOT, "data", "maps", "headers")
    for fn in os.listdir(hdir):
        if not fn.endswith(".asm"):
            continue
        m = re.search(r"map_header\s+(\w+),\s*(\w+),\s*(\w+)",
                      open(os.path.join(hdir, fn), encoding="utf-8",
                           errors="replace").read())
        if m:
            idx[m.group(2)] = (m.group(1), m.group(3))
    return idx


def _parse_dims():
    dims = {}
    for m in re.finditer(r"map_const\s+(\w+),\s*(\d+),\s*(\d+)",
                         _read("constants", "map_constants.asm")):
        dims[m.group(1)] = (int(m.group(2)), int(m.group(3)))
    return dims


def _parse_tileset_files():
    """label ('Overworld','RedsHouse1',...) -> ('gfx_basename','block_basename').
    Labels may stack and fall through to the next INCBIN (shared art)."""
    gfx, block = {}, {}
    pend_g, pend_b = [], []
    for line in _read("gfx", "tilesets.asm").splitlines():
        line = line.strip()
        mg = re.match(r"(\w+)_GFX::(?:\s*INCBIN\s+\"([^\"]+)\")?", line)
        mb = re.match(r"(\w+)_Block::(?:\s*INCBIN\s+\"([^\"]+)\")?", line)
        if mg:
            pend_g.append(mg.group(1))
            if mg.group(2):
                base = os.path.splitext(os.path.basename(mg.group(2)))[0]
                for lb in pend_g:
                    gfx[lb] = base
                pend_g = []
        elif mb:
            pend_b.append(mb.group(1))
            if mb.group(2):
                base = os.path.splitext(os.path.basename(mb.group(2)))[0]
                for lb in pend_b:
                    block[lb] = base
                pend_b = []
    return gfx, block


def _norm_tileset(const):
    """TILESET const -> table label. REDS_HOUSE_1 -> RedsHouse1, DOJO -> Dojo."""
    return "".join(p.capitalize() for p in const.split("_"))


def _parse_coll(label):
    """passable tile-id set for <label>_Coll (handles shared labels)."""
    txt = _read("data", "tilesets", "collision_tile_ids.asm")
    i = txt.find(label + "_Coll::")
    if i < 0:
        return set()
    m = re.search(r"coll_tiles ([^\n]+)", txt[i:])
    return set(int(h, 16) for h in re.findall(r"\$([0-9a-fA-F]+)", m.group(1)))


def _parse_door_tiles():
    """TILESET const -> set of door tile-ids (PlayerStepOutFromDoor)."""
    txt = _read("data", "tilesets", "door_tile_ids.asm")
    label_consts = {}
    for const, label in re.findall(r"dbw\s+(\w+),\s*\.(\w+)", txt):
        label_consts.setdefault(label, []).append(const)
    out = {}
    for label, body in re.findall(r"\.(\w+):\s*\n\s*door_tiles ([^\n]+)", txt):
        ids = set(int(h, 16) for h in re.findall(r"\$([0-9a-fA-F]+)", body))
        for c in label_consts.get(label, []):
            out[c] = ids
    return out


_MAP_INDEX = _build_map_index()
_DIMS = _parse_dims()
_GFX, _BLOCK = _parse_tileset_files()
_DOOR_TILES = _parse_door_tiles()

_DIRS = {"UP": UP, "DOWN": DOWN, "LEFT": LEFT, "RIGHT": RIGHT}


def _parse_objects(base):
    txt = _read("data", "maps", "objects", base + ".asm")
    mb = re.search(r"db \$([0-9a-fA-F]+)\s*;\s*border block", txt)
    border = int(mb.group(1), 16) if mb else 0
    warps = [(int(x), int(y), dest, int(wid))
             for x, y, dest, wid in re.findall(
                 r"warp_event\s+(\d+),\s*(\d+),\s*(\w+),\s*(\w+)", txt)]
    signs = [(int(x), int(y), tid)
             for x, y, tid in re.findall(
                 r"bg_event\s+(\d+),\s*(\d+),\s*(\w+)", txt)]
    npcs = []
    for x, y, spr, mv, dr, tid in re.findall(
            r"object_event\s+(\d+),\s*(\d+),\s*(\w+),\s*(\w+),\s*(\w+),\s*(\w+)",
            txt):
        npcs.append({"x": int(x), "y": int(y),
                     "sprite": spr[len("SPRITE_"):].lower(),
                     "facing": _DIRS.get(dr, DOWN), "text": tid})
    return border, warps, signs, npcs


# --------------------------------------------------------------------------
# sprite loading (player + NPCs), 16x16 frames stacked vertically
# --------------------------------------------------------------------------

def load_sprite(name):
    """gfx/sprites/<name>.png -> {facing: [stand, walk]} of 16x16 color-id
    grids. 3-frame sprites (no walk) reuse stand for walk. right = mirror left."""
    path = os.path.join(ROOT, "gfx", "sprites", name + ".png")
    w, h, px = decode_png_2bpp_gray(path)
    n = h // 16

    def fr(i):
        return [[px[i * 16 + y][x] for x in range(16)] for y in range(16)]

    def mir(f):
        return [list(reversed(r)) for r in f]

    # object sprites (poke_ball, pokedex, fossil, ...) are a single 16x16 frame;
    # NPCs are 3 (no walk) or 6 frames. Fall back gracefully.
    down = fr(0)
    up = fr(1) if n >= 2 else down
    left = fr(2) if n >= 3 else down
    if n >= 6:
        dw, uw, lw = fr(3), fr(4), fr(5)
    else:
        dw, uw, lw = down, up, left
    return {DOWN: [down, dw], UP: [up, uw],
            LEFT: [left, lw], RIGHT: [mir(left), mir(lw)]}


# --------------------------------------------------------------------------
# MapData
# --------------------------------------------------------------------------

PAD_TILES = 12   # border-block ring (block-aligned, multiple of 4) around a map


class MapData:
    def __init__(self, map_const):
        self.const = map_const
        self.base, tileset_const = _MAP_INDEX[map_const]
        self.tileset_const = tileset_const
        # Gen I CheckIfInOutsideMap: outside = OVERWORLD or PLATEAU tileset.
        # Only outside maps set the LAST_MAP return target.
        self.outside = tileset_const in ("OVERWORLD", "PLATEAU")
        self.door_tiles = _DOOR_TILES.get(tileset_const, set())
        label = _norm_tileset(tileset_const)

        w, h, px = decode_png_2bpp_gray(
            os.path.join(ROOT, "gfx", "tilesets", _GFX[label] + ".png"))
        self.tiles, _, _ = extract_tiles(w, h, px)
        self.inked = build_inked_tiles(self.tiles)
        self.passable = _parse_coll(label)

        bst = open(os.path.join(ROOT, "gfx", "blocksets",
                                _BLOCK[label] + ".bst"), "rb").read()
        self.blocks = [bst[i*16:(i+1)*16] for i in range(len(bst)//16)]

        self.W, self.H = _DIMS[map_const]
        self.GW, self.GH = self.W * 2, self.H * 2
        blk = open(os.path.join(ROOT, "maps", self.base + ".blk"), "rb").read()
        self.TW, self.TH = self.W * 4, self.H * 4
        grid = [[0]*self.TW for _ in range(self.TH)]
        for by in range(self.H):
            for bx in range(self.W):
                b = self.blocks[blk[by*self.W + bx]]
                for r in range(4):
                    for c in range(4):
                        grid[by*4+r][bx*4+c] = b[r*4+c]
        self.grid = grid

        self.border, self.warps, self.signs, self.npcs = _parse_objects(self.base)
        self.warp_at = {(x, y): (x, y, dest, wid)
                        for (x, y, dest, wid) in self.warps}
        self.npc_at = {(n["x"], n["y"]): n for n in self.npcs}
        self.sign_at = {(x, y): const for (x, y, const) in self.signs}

        self.pad_px = PAD_TILES * 8
        self.world_fb = self._build_padded_fb()
        self.PTWpx = (self.TW + 2*PAD_TILES) * 8
        self.PTHpx = (self.TH + 2*PAD_TILES) * 8

    def _build_padded_fb(self):
        PAD = PAD_TILES
        PTW, PTH = self.TW + 2*PAD, self.TH + 2*PAD
        fb = [[0]*(PTW*8) for _ in range(PTH*8)]
        bblock = self.blocks[self.border]
        for pty in range(PTH):
            for ptx in range(PTW):
                mtx, mty = ptx - PAD, pty - PAD
                if 0 <= mtx < self.TW and 0 <= mty < self.TH:
                    tile = self.inked[self.grid[mty][mtx]]
                else:
                    tile = self.inked[bblock[(pty % 4)*4 + (ptx % 4)]]
                oy, ox = pty*8, ptx*8
                for py in range(8):
                    row = fb[oy+py]
                    base = py*8
                    for pxx in range(8):
                        row[ox+pxx] = tile[base+pxx]
        return fb

    def collision_tile(self, cx, cy):
        return self.grid[2*cy + 1][2*cx]

    def walkable(self, cx, cy):
        if not (0 <= cx < self.GW and 0 <= cy < self.GH):
            return False
        if (cx, cy) in self.npc_at:
            return False
        return self.collision_tile(cx, cy) in self.passable

    def player_px(self, cx, cy):
        """map cell -> pixel position in the padded world_fb (sprite top-left)."""
        return cx*16 + self.pad_px, cy*16 + self.pad_px
