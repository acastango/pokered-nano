#!/usr/bin/env python3
"""
pokered-nano — battle-start transition (engine/battle/battle_transitions.asm).

Gen I flashes the screen (cycling the BG palette to black) then wipes to a black
screen with a shape depending on the encounter:
  wild    -> Circle / DoubleCircle   trainer -> Spiral
  dungeon -> Stripes / Shrink / Split
We can't pulse a 4-shade palette in a 1-bit terminal, so the flash is rendered
as full-screen INVERSION (the closest analog), and the wipes fill the frame to
ink in the same shapes, over the same ~1.4s timeframe. Stdlib only.
"""

import math

# timing (frames @30fps)
FLASH_FRAMES = 20      # ~0.7s: smooth brightness pulses (dark<->light)
WIPE_FRAMES = 24       # ~0.8s: the geometric wipe to black
HOLD_FRAMES = 45       # ~1.5s: stay black before the silhouettes slide in
SLIDE_FRAMES = 30      # ~1.0s: silhouettes slide onto the field
FLASH_CYCLES = 2       # full dark->light sweeps during the flash
THROW_FRAMES = 12      # Red's trainer back slides off to the left
SCALE_FRAMES = 8       # quick continuous grow (one size per frame, ~0.27s)
SCALE_START = 16       # starting px size; grows to the full 56

_BAYER = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]


def invert(fb):
    return [[1 - v for v in row] for row in fb]


def apply_brightness(fb, level):
    """Dithered brightness wash. level in [-16, 16]: >0 dissolves toward paper
    (brighten), <0 toward ink (darken); 0 = unchanged. Ordered dither gives the
    in-between shades the GB's palette pulse had, so it reads as a smooth flash
    rather than a hard invert."""
    a = min(16, abs(level))
    if a == 0:
        return [row[:] for row in fb]
    target = 0 if level > 0 else 1          # paper (light) vs ink (dark)
    src = 1 - target
    out = [row[:] for row in fb]
    for y, row in enumerate(out):
        by = _BAYER[y & 3]
        for x in range(len(row)):
            if row[x] == src and by[x & 3] < a:
                row[x] = target
    return out


def flash_frame(fb, f):
    """One smooth brightness sweep per cycle: normal -> dark -> normal -> light
    -> normal (the FlashScreen palette ramp), repeated FLASH_CYCLES times."""
    t = (f % (FLASH_FRAMES / FLASH_CYCLES)) / (FLASH_FRAMES / FLASH_CYCLES)
    level = round(-16 * math.sin(2 * math.pi * t))   # dip dark, then peak light
    return apply_brightness(fb, level)


def circle_wipe(fb, t):
    """Iris-close to ink: black creeps from the corners inward (wild battles)."""
    H, W = len(fb), len(fb[0])
    cx, cy = (W - 1) / 2, (H - 1) / 2
    thr = math.hypot(cx, cy) * (1 - t)
    out = [row[:] for row in fb]
    for y in range(H):
        dy2 = (y - cy) ** 2
        row = out[y]
        for x in range(W):
            if (x - cx) ** 2 + dy2 >= thr * thr:
                row[x] = 1
    return out


def _spiral_cells(cols, rows):
    """Inward spiral order of (col,row) tile coords."""
    order = []
    top, bot, left, right = 0, rows - 1, 0, cols - 1
    while top <= bot and left <= right:
        for x in range(left, right + 1):
            order.append((x, top))
        for y in range(top + 1, bot + 1):
            order.append((right, y))
        if top < bot:
            for x in range(right - 1, left - 1, -1):
                order.append((x, bot))
        if left < right:
            for y in range(bot - 1, top, -1):
                order.append((left, y))
        top += 1
        bot -= 1
        left += 1
        right -= 1
    return order


_SPIRAL = None


def spiral_wipe(fb, t, cell=8):
    """Fill 8x8 tiles to ink in inward-spiral order (trainer battles)."""
    global _SPIRAL
    H, W = len(fb), len(fb[0])
    cols, rows = W // cell, H // cell
    if _SPIRAL is None or len(_SPIRAL) != cols * rows:
        _SPIRAL = _spiral_cells(cols, rows)
    out = [row[:] for row in fb]
    for i in range(int(t * len(_SPIRAL))):
        tx, ty = _SPIRAL[i]
        for yy in range(ty*cell, ty*cell + cell):
            r = out[yy]
            for xx in range(tx*cell, tx*cell + cell):
                r[xx] = 1
    return out


def transition_frame(fb, kind, phase, f):
    """Return the effected framebuffer for the given phase/frame.
    kind: 'wild' (circle) or 'trainer' (spiral)."""
    if phase == "flash":
        return flash_frame(fb, f)
    if phase == "wipe":
        t = min(1.0, f / WIPE_FRAMES)
        return spiral_wipe(fb, t) if kind == "trainer" else circle_wipe(fb, t)
    return [[1] * len(fb[0]) for _ in range(len(fb))]   # hold: all ink
