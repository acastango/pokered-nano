#!/usr/bin/env python3
"""
pokered-nano — the ACTUAL battle HUD / HP-bar tile graphics (no approximation).

Gen I loads these into VRAM at fixed tile ids (engine/battle/core.asm
Load{Hud,HpBarAndStatus}TilePatterns):
  gfx/font/font_battle_extra.2bpp  -> tile $62  (HP-bar fill tiles, status)
  gfx/battle/battle_hud_1.1bpp     -> tile $6d  (endcaps, "HP:", triangle)
  gfx/battle/battle_hud_2/3.1bpp   -> tile $73  (frame: tick/corner/line)

HP bar (home/pokemon.asm DrawHPBar): $71 "HP:" + $62 left + 6 fill tiles
($63+px, 0..8 px each) + $6d endcap. Frame (PlaceHUDTiles): $73 tick, corner
($74 enemy/$77 player), 8x $76 line, triangle ($78 enemy/$6f player).
Stdlib only.
"""

import os

GFX = r"C:\Users\Anthony\pokered-nano\pokered-master\gfx"


def _load_2bpp(path):
    """Raw GB 2bpp (planar, 16 bytes/tile) -> list of 8x8 id grids (0..3)."""
    d = open(path, "rb").read()
    tiles = []
    for t in range(len(d) // 16):
        tile = []
        for r in range(8):
            lo, hi = d[t*16 + r*2], d[t*16 + r*2 + 1]
            tile.append([((hi >> (7-c)) & 1) * 2 + ((lo >> (7-c)) & 1)
                         for c in range(8)])
        tiles.append(tile)
    return tiles


def _load_1bpp(path):
    """Raw GB 1bpp (8 bytes/tile) -> list of 8x8 0/1 grids (bit set = ink)."""
    d = open(path, "rb").read()
    return [[[(d[t*8 + r] >> (7-c)) & 1 for c in range(8)] for r in range(8)]
            for t in range(len(d) // 8)]


def _ink2(tile):
    # font_battle_extra stores glyphs LIGHT-on-dark (opposite of the overworld):
    # the "HP:" text, bar frame and FILL are the high ids (2,3), the background
    # is the low ids. So ink = id>=2 (id<=2 made the empty bar/background dark).
    return [[1 if v >= 2 else 0 for v in row] for row in tile]


def _build():
    T = {}
    for i, t in enumerate(_load_2bpp(os.path.join(GFX, "font",
                                                  "font_battle_extra.2bpp"))):
        T[0x62 + i] = _ink2(t)
    # battle_hud_1 overwrites $6d.. (load order matches the asm)
    for i, t in enumerate(_load_1bpp(os.path.join(GFX, "battle",
                                                  "battle_hud_1.1bpp"))):
        T[0x6d + i] = t
    rest = (_load_1bpp(os.path.join(GFX, "battle", "battle_hud_2.1bpp")) +
            _load_1bpp(os.path.join(GFX, "battle", "battle_hud_3.1bpp")))
    for i, t in enumerate(rest):
        T[0x73 + i] = t
    return T


TILES = _build()


def place(fb, tile_id, tx, ty):
    """Blit an 8x8 tile (opaque) at tile coords (tx,ty)."""
    tile = TILES.get(tile_id)
    if tile is None:
        return
    oy, ox = ty * 8, tx * 8
    for y in range(8):
        fb[oy + y][ox:ox + 8] = tile[y]


def hp_pixels(cur, mx):
    """Gen I bar fill in pixels (0..48); keep a 1px sliver while any HP remains."""
    if mx <= 0:
        return 0
    p = (cur * 48) // mx
    return max(1, p) if cur > 0 else 0


def draw_hpbar(fb, tx, ty, cur, mx):
    """DrawHPBar: $71 'HP:' + $62 left + 6 fill ($63+px) + $6d endcap."""
    place(fb, 0x71, tx, ty)
    place(fb, 0x62, tx + 1, ty)
    e = hp_pixels(cur, mx)
    for i in range(6):
        seg = max(0, min(8, e))
        e -= 8
        place(fb, 0x63 + seg, tx + 2 + i, ty)
    place(fb, 0x6d, tx + 8, ty)


def draw_hud_frame(fb, tx, ty, enemy):
    """PlaceHUDTiles: $73 tick at (tx,ty); next row corner + 8x $76 line +
    triangle, running right (enemy) or left (player)."""
    de = 1 if enemy else -1
    corner = 0x74 if enemy else 0x77
    tri = 0x78 if enemy else 0x6f
    place(fb, 0x73, tx, ty)
    cx, cy = tx, ty + 1
    place(fb, corner, cx, cy)
    for _ in range(8):
        cx += de
        place(fb, 0x76, cx, cy)
    cx += de
    place(fb, tri, cx, cy)
