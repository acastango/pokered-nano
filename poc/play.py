#!/usr/bin/env python3
"""
pokered-nano — PLAYABLE Kanto (Pallet Town + interiors), with warps & NPCs.

    C:\\msys64\\mingw64\\bin\\python.exe poc\\play.py

Controls:  W/A/S/D or arrows = walk (hold)   M = change look   I = invert
           Q = quit

Real game loop (30fps, held-key input, smooth gliding, camera-follow). Loads
ANY map via mapdata.MapData; stepping onto a door/warp tile loads the
destination map (interiors fill the screen with the border block). NPCs are
drawn (inverted, like the player) and block movement. Stdlib only.
"""

import os
import sys
import time
import ctypes
import shutil

sys.path.insert(0, os.path.dirname(__file__))
from mapdata import MapData, load_sprite
from play_pallet import (to_braille, to_braille_color, to_block, to_ascii,
                         VW_PX, VH_PX)
from walk_pallet import DELTA, DOWN, UP, LEFT, RIGHT
from text_engine import (load_glyphs, resolve_text, draw_textbox,
                         str_to_codes, LINE_GAP)

FPS = 30
SPEED = 4                      # px/frame; 16/4 = 4 frames/tile (~Gen I pace)
FADE_FRAMES = 8                # warp transition: frames to dissolve out / in
CENTER = 64                    # player's top-left sits at screen px (64,64)
# All full-resolution renderers. "color" = colored braille (full GB screen in
# 80x36 chars, fits a normal terminal). "block" is 160x72 (twice as tall).
CELL = {"color": (2, 4), "braille": (2, 4), "ascii": (2, 4), "block": (1, 2)}
START_MAP = "PALLET_TOWN"
OPPOSITE = {UP: DOWN, DOWN: UP, LEFT: RIGHT, RIGHT: LEFT}

VK = {"up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
      "W": 0x57, "A": 0x41, "S": 0x53, "D": 0x44,
      "Q": 0x51, "M": 0x4D, "I": 0x49,
      "Z": 0x5A, "ENTER": 0x0D, "SPACE": 0x20}    # talk / confirm ("A button")


def talk_held():
    return held(VK["Z"]) or held(VK["ENTER"]) or held(VK["SPACE"])

_user32 = ctypes.windll.user32 if hasattr(ctypes, "windll") else None
if _user32:
    _user32.GetAsyncKeyState.restype = ctypes.c_short


def held(vk):
    return bool(_user32.GetAsyncKeyState(vk) & 0x8000) if _user32 else False


def setup_console():
    orig_in = None
    try:
        k = ctypes.windll.kernel32
        k.SetConsoleMode(k.GetStdHandle(-11), 7)
        k.SetConsoleOutputCP(65001)
        k.SetConsoleCP(65001)
        hin = k.GetStdHandle(-10)
        m = ctypes.c_uint()
        k.GetConsoleMode(hin, ctypes.byref(m))
        orig_in = m.value
        k.SetConsoleMode(hin, (orig_in & ~0x0006) | 0x0001)
    except Exception:
        pass
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    return orig_in


def restore_console(orig_in):
    try:
        k = ctypes.windll.kernel32
        if orig_in is not None:
            k.SetConsoleMode(k.GetStdHandle(-10), orig_in)
    except Exception:
        pass


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


# 4x4 ordered-dither matrix for the warp fade (dissolve to/from paper)
_BAYER = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]


def apply_fade(fb, level):
    """Dissolve toward paper: level 0 = full image, 16 = all paper. An ink pixel
    survives only if its dither cell is below the rising threshold."""
    if level <= 0:
        return
    thr = 16 - level
    for y, row in enumerate(fb):
        by = _BAYER[y & 3]
        for x in range(len(row)):
            if row[x] and by[x & 3] >= thr:
                row[x] = 0


# --- dialogue box state machine: typewriter + rolling/scrolling 2-line window -
# Phases: "type" reveal chars; "wait" full, blink ▼, await press; "scroll"
# animate the slide-up before typing the next line.
TYPE_SLOW, TYPE_FAST = 1, 4           # chars/frame (fast while talk held)
SCROLL_STEP = 4                       # px/frame of the 16px line slide


def _full(s):
    return len(str_to_codes(s))


def dialog_open(lines):
    d = {"lines": lines, "i": 1, "top": lines[0][0], "bot": "",
         "rt": 0, "rb": 0, "phase": "type", "off": 0, "pending": ""}
    if len(lines) > 1 and lines[1][1] == "line":   # second row shown with top
        d["bot"] = lines[1][0]
        d["i"] = 2
    return d


def _dialog_next(d):
    """Consume the next line at a wait point. Returns False to close."""
    L = d["lines"]
    if d["i"] >= len(L):
        return False
    text, kind = L[d["i"]]
    d["i"] += 1
    if kind == "scroll":
        d["pending"], d["off"], d["phase"] = text, 0, "scroll"
    elif kind == "para":                  # clear, start a fresh page
        d["top"], d["rt"], d["bot"], d["rb"] = text, 0, "", 0
        if d["i"] < len(L) and L[d["i"]][1] == "line":
            d["bot"] = L[d["i"]][0]
            d["i"] += 1
        d["phase"] = "type"
    else:
        d["bot"], d["rb"], d["phase"] = text, 0, "type"
    return True


def dialog_tick(d, edge, hold):
    """Advance one frame. Returns False when the box should close."""
    if d["phase"] == "type":
        ft, fb = _full(d["top"]), _full(d["bot"])
        if edge:                          # press skips to the end of the line(s)
            d["rt"], d["rb"] = ft, fb
        else:
            sp = TYPE_FAST if hold else TYPE_SLOW
            if d["rt"] < ft:
                d["rt"] = min(ft, d["rt"] + sp)
            elif d["rb"] < fb:
                d["rb"] = min(fb, d["rb"] + sp)
        if d["rt"] >= ft and d["rb"] >= fb:
            d["phase"] = "wait"
    elif d["phase"] == "wait":
        if edge:
            return _dialog_next(d)
    elif d["phase"] == "scroll":
        d["off"] += SCROLL_STEP
        if d["off"] >= LINE_GAP:          # slide done: roll window, type new line
            d["top"], d["rt"] = d["bot"], _full(d["bot"])
            d["bot"], d["rb"], d["off"], d["phase"] = d["pending"], 0, 0, "type"
    return True




def pick_start(m):
    ccx, ccy = m.GW // 2, m.GH // 2
    best, bestd = (ccx, ccy), 1e9
    for cy in range(m.GH):
        for cx in range(m.GW):
            if m.walkable(cx, cy):
                d = (cx-ccx)**2 + (cy-ccy)**2
                if d < bestd:
                    best, bestd = (cx, cy), d
    return best


def compose(world_fb, cam_x, cam_y, sprites, invert):
    """Window the padded world at (cam_x,cam_y); overlay character sprites
    given as (frame16x16, screen_x, screen_y). Returns a 160x144 framebuffer."""
    win = [row[cam_x:cam_x + VW_PX] for row in world_fb[cam_y:cam_y + VH_PX]]
    ink_ids = (0,) if invert else (1, 2)
    for frame, sx, sy in sprites:
        for y in range(16):
            ry = sy + y
            if 0 <= ry < VH_PX:
                line = win[ry]
                srow = frame[y]
                for x in range(16):
                    rx = sx + x
                    if 0 <= rx < VW_PX:
                        cid = srow[x]
                        if cid != 3:
                            line[rx] = 1 if cid in ink_ids else 0
    return win


def main():
    argv = sys.argv[1:]
    MODES = ["block", "color", "braille", "ascii"]
    RENDER = {"color": to_braille_color, "braille": to_braille,
              "block": to_block, "ascii": to_ascii}
    mode = next((m for m in MODES if m in argv), "block")
    selftest = "--selftest" in argv

    orig_in = setup_console()

    sprite_cache = {}

    def sprite(name):
        if name not in sprite_cache:
            sprite_cache[name] = load_sprite(name)
        return sprite_cache[name]

    glyphs = load_glyphs()
    m = MapData(START_MAP)
    cx, cy = pick_start(m)
    px, py = m.player_px(cx, cy)
    facing, phase, moving, invert = DOWN, 0, False, True
    vx = vy = 0
    warp_armed = True
    last_map = last_pos = None        # LAST_MAP return target (set only when
    player = sprite("red")            # leaving an outside map, like Gen I)
    dialog = None                     # rolling 2-line window (dialog_open) when open
    transition = None                 # {"phase":"out"/"in","f":int,"warp":..} mid-warp
    frame = 0                         # global frame counter (▼ arrow blink)

    def do_warp(warp):
        nonlocal m, px, py, moving, warp_armed, last_map, last_pos
        wx, wy, dest, wid = warp
        if m.outside:                        # remember where we left the overworld
            last_map, last_pos = m.const, (wx, wy)
        if dest == "LAST_MAP":
            if last_map is None:
                return
            m = MapData(last_map)
            tx, ty = last_pos
        else:
            m = MapData(dest)
            tx, ty, _, _ = m.warps[wid - 1]      # dest id is 1-based
        px, py = m.player_px(tx, ty)
        # facing is PRESERVED across the warp (walk up into a door -> face up
        # inside; the step-out-from-door sets DOWN for overworld exits).
        moving, warp_armed = False, False

    def draw():
        cw, ch = CELL[mode]
        cam_x = clamp(px - CENTER, 0, m.PTWpx - VW_PX)
        cam_y = clamp(py - CENTER, 0, m.PTHpx - VH_PX)
        cam_x -= cam_x % cw
        cam_y -= cam_y % ch
        sprites = []
        for n in m.npcs:                         # NPCs (static, standing frame)
            nx, ny = m.player_px(n["x"], n["y"])
            sx, sy = nx - cam_x, ny - cam_y
            if -16 < sx < VW_PX and -16 < sy < VH_PX:
                sx -= sx % cw
                sy -= sy % ch
                sprites.append((sprite(n["sprite"])[n["facing"]][0], sx, sy))
        psx, psy = px - cam_x, py - cam_y         # player on top
        psx -= psx % cw
        psy -= psy % ch
        sprites.append((player[facing][phase if moving else 0], psx, psy))

        fb = compose(m.world_fb, cam_x, cam_y, sprites, invert)
        if dialog is not None:
            # ▼ arrow blinks only while waiting for a press (not mid-type/scroll)
            arrow = dialog["phase"] == "wait" and (frame // 16) % 2 == 0
            draw_textbox(fb, glyphs, dialog["top"], dialog["bot"],
                         rt=dialog["rt"], rb=dialog["rb"],
                         scroll_off=dialog["off"], arrow=arrow)
        if transition is not None:        # warp fade: dissolve out then in
            f = transition["f"]
            level = (f if transition["phase"] == "out" else FADE_FRAMES - f)
            apply_fade(fb, round(16 * level / FADE_FRAMES))
        # Native, pixel-exact — the FULL GB screen, never cropped or scaled.
        lines = RENDER[mode](fb).split("\n")
        _, trows = shutil.get_terminal_size((80, 80))
        out = ["\x1b[H"]
        for i, ln in enumerate(lines):
            out.append(f"\x1b[{i+1};1H{ln}\x1b[0m\x1b[K")
        if trows > len(lines):                 # status only if there's a spare row
            out.append(f"\x1b[{len(lines)+1};1H WASD=walk Z=talk M=look[{mode}] "
                       f"I=invert[{'on' if invert else 'off'}] Q=quit "
                       f"\x1b[0m\x1b[K")
        sys.stdout.write("".join(out))
        sys.stdout.flush()

    if selftest:
        draw()
        # exercise a warp into Red's house to prove multi-map loading
        do_warp((5, 5, "REDS_HOUSE_1F", 1))
        print(f"\n[selftest ok] start=({cx},{cy}) on {START_MAP}; "
              f"warped into {m.const} ({m.W}x{m.H}), npcs={len(m.npcs)}")
        restore_console(orig_in)
        return

    try:
        ctypes.windll.winmm.timeBeginPeriod(1)
    except Exception:
        pass
    sys.stdout.write("\x1b[2J\x1b[?25l\x1b[?7l")
    prev_m = prev_q = prev_i = prev_t = False
    frame_dt = 1.0 / FPS
    try:
        draw()
        while True:
            t0 = time.perf_counter()
            frame += 1
            now_q = held(VK["Q"])
            if now_q and not prev_q:
                break
            prev_q = now_q
            now_m = held(VK["M"])
            if now_m and not prev_m:
                mode = MODES[(MODES.index(mode) + 1) % len(MODES)]
                sys.stdout.write("\x1b[2J")
            prev_m = now_m
            now_i = held(VK["I"])
            if now_i and not prev_i:
                invert = not invert
            prev_i = now_i

            now_t = talk_held()
            talk_edge = now_t and not prev_t
            prev_t = now_t

            # warp transition: dissolve out -> swap map -> dissolve in
            if transition is not None:
                transition["f"] += 1
                if transition["f"] >= FADE_FRAMES:
                    if transition["phase"] == "out":
                        do_warp(transition["warp"])
                        transition = {"phase": "in", "f": 0, "warp": None}
                    else:
                        transition = None
                        # PlayerStepOutFromDoor: if we arrived on a door tile,
                        # auto-walk one step down off it (moves off the warp).
                        cx = (px - m.pad_px) // 16
                        cy = (py - m.pad_px) // 16
                        if (m.collision_tile(cx, cy) in m.door_tiles
                                and m.walkable(cx, cy + 1)):
                            facing = DOWN
                            vx, vy = 0, SPEED
                            moving = True
                            phase ^= 1
                draw()
                dt = time.perf_counter() - t0
                if dt < frame_dt:
                    time.sleep(frame_dt - dt)
                continue            # frozen during the transition

            # tick an open dialog every frame (typewriter, scroll slide, waits)
            if dialog is not None:
                if not dialog_tick(dialog, talk_edge, talk_held()):
                    npc = dialog.get("npc")     # restore NPC's original facing
                    if npc is not None:
                        npc["facing"] = npc.pop("_save_face", npc["facing"])
                    dialog = None
                draw()
                dt = time.perf_counter() - t0
                if dt < frame_dt:
                    time.sleep(frame_dt - dt)
                continue            # no movement/warp while a box is open

            if moving:
                px += vx
                py += vy
                if (px - m.pad_px) % 16 == 0 and (py - m.pad_px) % 16 == 0:
                    moving = False

            if not moving:
                cx = (px - m.pad_px) // 16
                cy = (py - m.pad_px) // 16
                if (cx, cy) not in m.warp_at:
                    warp_armed = True
                elif warp_armed:                 # start the fade; warp at out-end
                    transition = {"phase": "out", "f": 0,
                                  "warp": m.warp_at[(cx, cy)]}

                # talk: open dialog if facing a sign or NPC with renderable text
                if transition is None and talk_edge:
                    dx, dy = DELTA[facing]
                    fc = (cx + dx, cy + dy)
                    npc = m.npc_at.get(fc)
                    const = m.sign_at.get(fc) or (npc["text"] if npc else None)
                    if const:
                        lines = resolve_text(m.base, const)
                        if lines:
                            dialog = dialog_open(lines)
                            if npc is not None:     # NPC turns to face the player
                                npc["_save_face"] = npc["facing"]
                                npc["facing"] = OPPOSITE[facing]
                                dialog["npc"] = npc

            if dialog is None and transition is None and not moving:
                d = None
                if held(VK["up"]) or held(VK["W"]):
                    d = UP
                elif held(VK["down"]) or held(VK["S"]):
                    d = DOWN
                elif held(VK["left"]) or held(VK["A"]):
                    d = LEFT
                elif held(VK["right"]) or held(VK["D"]):
                    d = RIGHT
                if d:
                    facing = d
                    dx, dy = DELTA[d]
                    if m.walkable(cx + dx, cy + dy):
                        moving = True
                        vx, vy = dx * SPEED, dy * SPEED
                        phase ^= 1
                    elif ((cx, cy) in m.warp_at and
                          not (0 <= cx+dx < m.GW and 0 <= cy+dy < m.GH)):
                        # standing on a warp, pressing toward the map edge:
                        # leave through it (CheckWarpsCollision / ExtraWarpCheck)
                        transition = {"phase": "out", "f": 0,
                                      "warp": m.warp_at[(cx, cy)]}

            draw()
            dt = time.perf_counter() - t0
            if dt < frame_dt:
                time.sleep(frame_dt - dt)
    finally:
        sys.stdout.write("\x1b[?7h\x1b[?25h\x1b[2J\x1b[H")
        sys.stdout.flush()
        restore_console(orig_in)
        try:
            ctypes.windll.winmm.timeEndPeriod(1)
        except Exception:
            pass
    print("bye!")


if __name__ == "__main__":
    main()
