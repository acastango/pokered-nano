#!/usr/bin/env python3
"""
pokered-nano — text system, faithful to Gen I.

Real font glyphs blitted into the same 1-bit framebuffer as the world, inside a
Game Boy text box drawn with the real box-border tiles.

  * glyphs:  gfx/font/font.1bpp  (128 1bpp tiles -> char codes $80-$ff)
             gfx/font/font_extra.png (32 2bpp tiles -> codes $60-$7f: box + space)
  * charmap: constants/charmap.asm  (char -> code)
  * text:    scripts/<Map>.asm <Map>_TextPointers (TEXT_* -> label -> text_far
             _Xxx) then text/<Map>.asm (_Xxx:: text/line/cont/para/done)

Box layout (home/text.asm coords): rows 12-17 x cols 0-19; border ┌─┐│└┘;
two text lines at rows 14 and 16, cols 1-18 (18 chars/line). Stdlib only.
"""

import os
import re

import sys
sys.path.insert(0, os.path.dirname(__file__))
from roundtrip import decode_png_2bpp_gray

ROOT = r"C:\Users\Anthony\pokered-nano\pokered-master"

# box-border char codes
TL, HZ, TR, VT, BL, BR, SP = 0x79, 0x7a, 0x7b, 0x7c, 0x7d, 0x7e, 0x7f


# --------------------------------------------------------------------------
# glyphs
# --------------------------------------------------------------------------

def load_glyphs():
    """code -> 8x8 list of {0,1} (1 = ink)."""
    g = {}
    data = open(os.path.join(ROOT, "gfx", "font", "font.1bpp"), "rb").read()
    for i in range(128):                       # 1bpp: codes $80-$ff
        t = data[i*8:(i+1)*8]
        g[0x80 + i] = [[(t[y] >> (7-x)) & 1 for x in range(8)] for y in range(8)]
    w, h, px = decode_png_2bpp_gray(
        os.path.join(ROOT, "gfx", "font", "font_extra.png"))
    for i in range(32):                        # 2bpp: codes $60-$7f
        tx, ty = (i % 16)*8, (i // 16)*8
        g[0x60 + i] = [[1 if px[ty+y][tx+x] >= 2 else 0 for x in range(8)]
                       for y in range(8)]
    g[SP] = [[0]*8 for _ in range(8)]          # force space blank (its tile in
    return g                                    # font_extra is a solid block)


# --------------------------------------------------------------------------
# charmap (the English subset we need) + token expansion
# --------------------------------------------------------------------------

def _build_charmap():
    cm = {}
    for i, c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
        cm[c] = 0x80 + i
    for i, c in enumerate("abcdefghijklmnopqrstuvwxyz"):
        cm[c] = 0xa0 + i
    for i, c in enumerate("0123456789"):
        cm[c] = 0xf6 + i
    cm.update({" ": 0x7f, "(": 0x9a, ")": 0x9b, ":": 0x9c, ";": 0x9d,
               "[": 0x9e, "]": 0x9f, "é": 0xba, "'": 0xe0, "-": 0xe3,
               "?": 0xe6, "!": 0xe7, ".": 0xe8, "/": 0xf3, ",": 0xf4,
               "♂": 0xef, "♀": 0xf5})
    return cm


_CHARMAP = _build_charmap()


def expand_tokens(s, player="RED", rival="BLUE"):
    s = s.replace("@", "")                # string terminator, not a glyph
    s = s.replace("#", "POKé")            # $54 ligature -> POKé
    s = s.replace("<PLAYER>", player).replace("<RIVAL>", rival)
    s = s.replace("<PK>", "PK").replace("<MN>", "MN")
    s = re.sub(r"<[^>]+>", "", s)          # drop any other control tokens
    return s


def str_to_codes(s):
    return [_CHARMAP.get(c, SP) for c in expand_tokens(s)]


# --------------------------------------------------------------------------
# text resolution: TEXT_* const -> list of (line1, line2) screens
# --------------------------------------------------------------------------

def _read(*p):
    return open(os.path.join(ROOT, *p), encoding="utf-8", errors="replace").read()


def resolve_text(map_base, text_const):
    """Return a list of screens, each a list of up to 2 text lines (strings),
    Returns a flat list of (text, kind) where kind drives the box behavior:
      'start' first line of the message      (fills the top row)
      'line'  second row, shown with the top (no button press)
      'scroll'cont/next -> scroll the window up one line (press, then roll)
      'para'  new paragraph -> clear the box and start fresh (press, then clear)
    or None if the text is procedural (text_asm) and not statically renderable."""
    scr = _read("scripts", map_base + ".asm")
    ptrs = dict((const, label) for label, const in
                re.findall(r"dw_const\s+(\w+),\s*(\w+)", scr))
    label = ptrs.get(text_const)
    if not label:
        return None
    # the label's body up to the next top-level label; take its first text_far
    # (handles plain `text_far _Xxx` AND text_asm wrappers that text_far inside)
    body = re.search(r"^" + label + r":\s*\n(.*?)(?=^\w+:)", scr, re.S | re.M)
    chunk = body.group(1) if body else scr[scr.find(label + ":"):][:1500]
    far = re.search(r"text_far\s+(\w+)", chunk)
    if not far:
        return None                        # fully procedural text -> no static text
    return _parse_text_lines(map_base, far.group(1))


def resolve_far(map_base, far_label):
    """Resolve a text/<Map>.asm far-text label directly to screens (used by the
    script VM, since some NPC texts are procedural text_asm whose body just
    text_fars these)."""
    return _parse_text_lines(map_base, far_label)


_KIND = {"text": "start", "line": "line", "cont": "scroll",
         "next": "scroll", "para": "para"}


def _parse_text_lines(map_base, far_label):
    txt = _read("text", map_base + ".asm")
    m = re.search(far_label + r"::\s*\n(.*?)(?:\n\s*(?:text_end|done)\b)",
                  txt, re.S)
    if not m:
        return None
    out = [(body, _KIND[kind]) for kind, body in
           re.findall(r'\b(text|line|cont|para|next)\b\s+"([^"]*)"', m.group(1))]
    return out or [("", "start")]


# --------------------------------------------------------------------------
# rendering a text box into a framebuffer
# --------------------------------------------------------------------------

BOX_TOP, BOX_BOT = 12, 17          # tile rows
LINE1, LINE2 = 14, 16              # text rows
COLS = 20
INT_Y0, INT_Y1 = (BOX_TOP+1)*8, BOX_BOT*8   # interior pixel y-range [104,136)
LINE_GAP = (LINE2 - LINE1) * 8     # 16px: one line scroll distance


def _blit(fb, glyph, tx, ty, invert=False):
    ox, oy = tx*8, ty*8
    for y in range(8):
        ry = oy + y
        if 0 <= ry < len(fb):
            row = fb[ry]
            grow = glyph[y]
            for x in range(8):
                rx = ox + x
                if 0 <= rx < len(fb[0]):
                    row[rx] = (1 - grow[x]) if invert else grow[x]


def _draw_text_row(fb, glyphs, codes, py):
    """Blit a row of glyph codes at pixel-y py (cols start at 1), dark-on-light,
    clipped to the box interior so sliding text never paints over the border."""
    blank = glyphs[SP]
    for i, code in enumerate(codes[:18]):
        g = glyphs.get(code, blank)
        ox = (1 + i) * 8
        for y in range(8):
            ry = py + y
            if INT_Y0 <= ry < INT_Y1 and 0 <= ry < len(fb):
                row, grow = fb[ry], g[y]
                for x in range(8):
                    rx = ox + x
                    if 0 <= rx < len(fb[0]):
                        row[rx] = grow[x]


def draw_textbox(fb, glyphs, top="", bot="", rt=None, rb=None,
                 scroll_off=0, arrow=False, invert=True):
    """Dark box, light inverted border, dark text on the light interior.
    rt/rb = chars revealed on each line (typewriter); scroll_off = pixels the
    text is slid up (scroll animation)."""
    blank = glyphs[SP]
    for ty in range(BOX_TOP, BOX_BOT + 1):
        for tx in range(COLS):
            border = ty in (BOX_TOP, BOX_BOT) or tx in (0, COLS-1)
            if ty == BOX_TOP:
                code = TL if tx == 0 else TR if tx == COLS-1 else HZ
            elif ty == BOX_BOT:
                code = BL if tx == 0 else BR if tx == COLS-1 else HZ
            else:
                code = VT if tx in (0, COLS-1) else SP
            _blit(fb, glyphs.get(code, blank), tx, ty, invert and border)
    tc, bc = str_to_codes(top), str_to_codes(bot)
    rt = len(tc) if rt is None else rt
    rb = len(bc) if rb is None else rb
    _draw_text_row(fb, glyphs, tc[:rt], LINE1*8 - scroll_off)
    _draw_text_row(fb, glyphs, bc[:rb], LINE2*8 - scroll_off)
    if arrow:
        _blit(fb, glyphs.get(0xee, blank), 18, LINE2, False)
