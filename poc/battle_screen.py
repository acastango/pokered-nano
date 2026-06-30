#!/usr/bin/env python3
"""
pokered-nano — the battle screen (engine/battle/core.asm layout).

Faithful Gen I placement (8px tiles, 20x18 screen):
  enemy HUD  top-left  (0,0)   name (1,0)         enemy front sprite (12,0)
  player HUD bottom-rt (9,7)   name (10,7) hp(10,9)  player back sprite (1,5)
  battle text/menu box  bottom 6 rows

Mon sprites are imported from gfx/pokemon/*.png at 1bpp (ink = color id <= 1,
same 2-tone rule as the overworld). Back sprites are 32x32, pixel-doubled to
64x64 like the GB does. Stdlib only.
"""

import os
from roundtrip import decode_png_2bpp_gray
from text_engine import (str_to_codes, draw_textbox, _blit,
                         TL, HZ, TR, VT, BL, BR, SP)
import battle_hud as bh
import moves as mv

# the 2x2 battle menu (data/text_boxes.asm BattleMenuText): box (8,12)-(19,17),
# FIGHT/PKMN top row, ITEM/RUN bottom. Items 0=FIGHT 1=ITEM 2=PKMN 3=RUN.
MENU_CURSORS = [(9, 14), (9, 16), (15, 14), (15, 16)]
CURSOR = 0xED          # '▶'

GFX = r"C:\Users\Anthony\pokered-nano\pokered-master\gfx\pokemon"
RED_BACK = r"C:\Users\Anthony\pokered-nano\pokered-master\gfx\player\redb.png"


def _ink(px, w, h, solid):
    """Threshold a region to 1bpp. solid=True (silhouette) inks the light-gray
    body too (id<=2) for the solid shapes the slide-in shows."""
    thr = 2 if solid else 1
    return [[1 if px[y][x] <= thr else 0 for x in range(w)] for y in range(h)]


def mon_front(species_key, solid=False):
    """Front sprite at native size (n*8 px), 1bpp."""
    w, h, px = decode_png_2bpp_gray(os.path.join(GFX, "front", species_key + ".png"))
    return _ink(px, w, h, solid)


def back_56(path, solid=False):
    """A 32x32 back pic -> ScaleSpriteByTwo (crop right/bottom 4px, 2x) -> 56x56."""
    w, h, px = decode_png_2bpp_gray(path)
    return scale2x(_ink(px, 28, 28, solid))


def mon_back_56(species_key, solid=False):
    return back_56(os.path.join(GFX, "back", species_key + "b.png"), solid)


def scale2x(spr):
    out = []
    for row in spr:
        dbl = [v for v in row for _ in (0, 0)]
        out.append(dbl)
        out.append(dbl[:])
    return out


def scale_to(spr, n):
    """Nearest-neighbour downscale a sprite to n x n (the send-out 'grow' steps:
    AnimateSendingOutMon draws the mon at 3x3=24px, 5x5=40px, then full 56px)."""
    H, W = len(spr), len(spr[0])
    return [[spr[(y * H) // n][(x * W) // n] for x in range(n)] for y in range(n)]


def blit(fb, spr, ox, oy, transparent=True):
    """Draw a 1bpp sprite at pixel (ox,oy); ink pixels only (transparent bg)."""
    H, W = len(fb), len(fb[0])
    for y, row in enumerate(spr):
        fy = oy + y
        if not (0 <= fy < H):
            continue
        frow = fb[fy]
        for x, v in enumerate(row):
            fx = ox + x
            if 0 <= fx < W and (v or not transparent):
                frow[fx] = v


def draw_str(fb, glyphs, s, tx, ty):
    """Blit a string of font glyphs at tile (tx,ty) as ink-on-paper."""
    for i, code in enumerate(str_to_codes(s)):
        g = glyphs.get(code)
        if g:
            blit(fb, g, (tx + i) * 8, ty * 8, transparent=False)


def draw_level(fb, glyphs, level, tx, ty):
    """Level the way the GB does in battle: the dedicated ':L' tile ($6e, from
    battle_hud_1 — distinct from the regular font) then the number."""
    bh.place(fb, 0x6e, tx, ty)
    draw_str(fb, glyphs, str(level), tx + 1, ty)


def hp_bar(fb, ox, oy, cur, mx):
    """A 48px (6-tile) HP bar: outline + proportional fill (like the GB bar).
    Gen I fills in 1/48 steps and keeps a sliver while any HP remains."""
    W = 48
    fill = 0 if mx <= 0 else min(W, (48 * cur) // mx)
    if cur > 0:
        fill = max(1, fill)
    for x in range(W + 2):            # top/bottom border
        fb[oy][ox + x] = 1
        fb[oy + 5][ox + x] = 1
    for y in range(6):
        fb[oy + y][ox] = 1
        fb[oy + y][ox + W + 1] = 1
    for y in range(2, 4):             # the bar fill row
        for x in range(W):
            fb[oy + y][ox + 1 + x] = 1 if x < fill else 0


def underline(fb, tx, ty, length, tick_right):
    """The HUD's lower frame: a horizontal line with an upward tick at one end
    (PlaceHUDTiles' $76 line + $73/corner)."""
    y, x0 = ty * 8, tx * 8
    for x in range(length * 8):
        fb[y][x0 + x] = 1
    tickx = x0 + length * 8 - 1 if tick_right else x0
    for yy in range(max(0, y - 5), y):
        fb[yy][tickx] = 1


def draw_box(fb, glyphs, x1, y1, x2, y2):
    """A bordered text box (same style as draw_textbox) over a tile rect."""
    blank = glyphs[SP]
    for ty in range(y1, y2 + 1):
        for tx in range(x1, x2 + 1):
            border = ty in (y1, y2) or tx in (x1, x2)
            if ty == y1:
                code = TL if tx == x1 else TR if tx == x2 else HZ
            elif ty == y2:
                code = BL if tx == x1 else BR if tx == x2 else HZ
            else:
                code = VT if tx in (x1, x2) else SP
            _blit(fb, glyphs.get(code, blank), tx, ty, border)


def draw_battle_menu(fb, glyphs, cursor):
    """The FIGHT/PKMN/ITEM/RUN box at (8,12)-(19,17) with the cursor."""
    draw_box(fb, glyphs, 8, 12, 19, 17)
    draw_str(fb, glyphs, "FIGHT", 10, 14)
    blit(fb, glyphs[0xE1], 16 * 8, 14 * 8, transparent=False)   # <PK>
    blit(fb, glyphs[0xE2], 17 * 8, 14 * 8, transparent=False)   # <MN>
    draw_str(fb, glyphs, "ITEM", 10, 16)
    draw_str(fb, glyphs, "RUN", 16, 16)
    cx, cy = MENU_CURSORS[cursor]
    blit(fb, glyphs[CURSOR], cx * 8, cy * 8, transparent=False)


def draw_move_menu(fb, glyphs, mon, cursor):
    """FIGHT submenu (MoveSelectionMenu + PrintMenuItem): move-info box
    (0,8)-(10,12) with TYPE/<type> and <PP>/<maxPP>, and the move list box
    (4,12)-(19,17). They meet at row 12 with a connecting notch."""
    cm = mv.MOVES[mon.moves[cursor]]
    draw_box(fb, glyphs, 0, 8, 10, 12)          # TextBoxBorder (0,8) b=3 c=9
    draw_str(fb, glyphs, "TYPE/", 1, 9)
    draw_str(fb, glyphs, cm["type"], 2, 10)
    draw_str(fb, glyphs, "%2d/%2d" % (cm["pp"], cm["pp"]), 5, 11)
    draw_box(fb, glyphs, 4, 12, 19, 17)         # TextBoxBorder (4,12) b=4 c=14
    _blit(fb, glyphs[HZ], 4, 12, True)          # connect the two boxes (asm
    _blit(fb, glyphs[BR], 10, 12, True)         # overwrites (4,12)=─ (10,12)=┘)
    for i, m in enumerate(mon.moves):
        draw_str(fb, glyphs, mv.MOVES[m]["name"], 6, 13 + i)
    blit(fb, glyphs[CURSOR], 5 * 8, (13 + cursor) * 8, transparent=False)


def blank_fb():
    return [[0] * 160 for _ in range(144)]


ENEMY_BOX = (12, 0)                # enemy front 7x7 box origin (tiles)
PLAYER_BOX = (1, 5)                # player back 7x7 box origin (tiles)


def enemy_spot(spr):
    """Pixel position of the enemy front sprite (AlignSpriteDataCentered)."""
    w, h = len(spr[0]) // 8, len(spr) // 8
    return ENEMY_BOX[0] * 8 + ((8 - w) // 2) * 8, ENEMY_BOX[1] * 8 + (7 - h) * 8


def draw_battle_screen(fb, glyphs, player, enemy, message=None, arrow=False,
                       player_back=None, show_player_hud=True):
    """Compose the battle scene into fb (160x144). player_back overrides the
    player's bottom-left sprite (e.g. Red's trainer back before the mon is sent
    out); show_player_hud=False hides the player HUD until then."""
    es = mon_front(enemy.species)
    blit(fb, es, *enemy_spot(es))
    ps = player_back if player_back is not None else mon_back_56(player.species)
    blit(fb, ps, PLAYER_BOX[0] * 8, PLAYER_BOX[1] * 8)        # 56x56 in the 7x7 box

    # enemy HUD (top-left): name (1,0), :Llevel (4,1), real HP bar (2,2) + frame
    draw_str(fb, glyphs, enemy.nickname, 1, 0)
    draw_level(fb, glyphs, enemy.level, 4, 1)
    bh.draw_hpbar(fb, 2, 2, enemy.cur_hp, enemy.max_hp)
    bh.draw_hud_frame(fb, 1, 2, enemy=True)

    if show_player_hud:
        draw_str(fb, glyphs, player.nickname, 10, 7)
        draw_level(fb, glyphs, player.level, 14, 8)
        bh.draw_hpbar(fb, 10, 9, player.cur_hp, player.max_hp)
        draw_str(fb, glyphs, "%3d/%3d" % (player.cur_hp, player.max_hp), 11, 10)
        bh.draw_hud_frame(fb, 18, 10, enemy=False)

    if message is not None:
        top, _, bot = message.partition("\n")
        draw_textbox(fb, glyphs, top, bot, arrow=arrow)
    return fb
