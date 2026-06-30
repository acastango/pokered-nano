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
import random

sys.path.insert(0, os.path.dirname(__file__))
from mapdata import MapData, load_sprite
from play_pallet import (to_braille, to_braille_color, to_block, to_ascii,
                         VW_PX, VH_PX)
from walk_pallet import DELTA, DOWN, UP, LEFT, RIGHT
from text_engine import (load_glyphs, resolve_text, resolve_far, draw_textbox,
                         str_to_codes, LINE_GAP)
import scriptvm as svm
import battle_intro as bx
import battle_screen as bs
import pokemon as pk
from wild import WILD, SLOT_WEIGHTS
from ascii_map import grid_str

GRID_DUMP = os.path.join(os.path.dirname(__file__), "map_grid.txt")

GRASS_TILE = 0x52              # Overworld tileset grass tile (wGrassTile)

FPS = 30
SPEED = 4                      # px/frame; 16/4 = 4 frames/tile (~Gen I pace)
FADE_FRAMES = 8                # warp transition: frames to dissolve out / in
CENTER = 64                    # player's top-left sits at screen px (64,64)
# All full-resolution renderers. "color" = colored braille (full GB screen in
# 80x36 chars, fits a normal terminal). "block" is 160x72 (twice as tall).
CELL = {"color": (2, 4), "braille": (2, 4), "ascii": (2, 4), "block": (1, 2)}
START_MAP = "PALLET_TOWN"
OPPOSITE = {UP: DOWN, DOWN: UP, LEFT: RIGHT, RIGHT: LEFT}
NPC_SPEED = 2                  # px/frame for NPC steps (gentler than player)
NPC_RANGE = 2                  # max cells an NPC wanders from its spawn


def make_battle(kind, enemy, mine, base):
    """Battle-intro state, with the sprites the slide-in needs pre-rendered:
    enemy front + Red's trainer back as solid silhouettes, plus Red's normal
    back for the post-slide screen (the mon isn't sent out until the pokeball)."""
    es = bs.mon_front(enemy.species, solid=True)
    return {"kind": kind, "phase": "flash", "f": 0, "enemy": enemy,
            "player_mon": mine, "base": base,
            "enemy_sil": es, "enemy_spot": bs.enemy_spot(es),
            "red_sil": bs.back_56(bs.RED_BACK, solid=True),
            "red_norm": bs.back_56(bs.RED_BACK),
            "mon_back": bs.mon_back_56(mine.species),
            "menu": 0, "menumsg": None, "fleeing": False, "nav": {},
            "sub": None, "movecur": 0}


def roll_encounter(map_base, rng):
    """Gen I wild check: on a grass step, ~rate/256 chance; pick a slot by the
    cumulative weights and build the wild Pokemon. Returns a Pokemon or None."""
    data = WILD.get(map_base)
    grass = data["grass"] if data else None
    if not grass or grass["rate"] == 0 or not grass["slots"]:
        return None
    if rng.randint(0, 255) >= grass["rate"]:
        return None
    r, cum, slot = rng.randint(0, 255), 0, grass["slots"][-1]
    for i, w in enumerate(SLOT_WEIGHTS):
        cum += w
        if r < cum:
            slot = grass["slots"][min(i, len(grass["slots"]) - 1)]
            break
    level, sp_const = slot
    sp = pk.BY_DEX.get(sp_const)
    return pk.Pokemon(sp["key"], level) if sp else None


def pick_dir(rng):
    """Choose a wander direction from an NPC's movement-range byte."""
    if rng == "UP_DOWN":
        return random.choice((UP, DOWN))
    if rng == "LEFT_RIGHT":
        return random.choice((LEFT, RIGHT))
    if rng in (DOWN, UP, LEFT, RIGHT):     # a fixed paced direction
        return rng
    return random.choice((UP, DOWN, LEFT, RIGHT))   # ANY_DIR / NONE


def npc_busy(n):
    sm = n.get("script_move")
    return (sm is not None and sm["remaining"] > 0) or n["phase"] == "walk"


def update_scripted_npcs(m):
    """Drive NPCs under a script-commanded walk (MOVENPC) — ignores collision
    and the random wander, used during cutscenes."""
    for n in m.npcs:
        sm = n.get("script_move")
        if sm is None:
            continue
        if n["phase"] == "walk":
            n["px"] += n["vx"]
            n["py"] += n["vy"]
            if (n["px"]-m.pad_px) % 16 == 0 and (n["py"]-m.pad_px) % 16 == 0:
                n["phase"] = "idle"
            continue
        if sm["remaining"] <= 0:
            n["script_move"] = None
            continue
        dx, dy = DELTA[sm["dir"]]
        n["facing"] = sm["dir"]
        n["cx"] += dx
        n["cy"] += dy
        n["vx"], n["vy"] = dx*NPC_SPEED, dy*NPC_SPEED
        n["phase"] = "walk"
        n["walkphase"] ^= 1
        sm["remaining"] -= 1


def apply_hidden(m):
    """Hide NPCs the original reveals via a script (per the MAP_HIDDEN registry),
    until a SHOW opcode reveals them."""
    spawns = svm.MAP_HIDDEN.get(m.const, ())
    for n in m.npcs:
        if n["spawn"] in spawns:
            n["hidden"] = True


def update_npcs(m, player_cell):
    """Advance NPC wandering one frame. STAY = fixed (NONE = look around);
    WALK = random step within NPC_RANGE of spawn, respecting collision."""
    for n in m.npcs:
        if n.get("hidden") or n.get("script_move"):
            continue
        if n["move"] != "WALK":                       # STAY
            if n["range"] == "NONE":                  # idly glance around
                n["timer"] -= 1
                if n["timer"] <= 0:
                    n["facing"] = random.choice((UP, DOWN, LEFT, RIGHT))
                    n["timer"] = random.randint(45, 120)
            continue
        if n["phase"] == "walk":                      # mid-step: glide
            n["px"] += n["vx"]
            n["py"] += n["vy"]
            if (n["px"]-m.pad_px) % 16 == 0 and (n["py"]-m.pad_px) % 16 == 0:
                n["phase"] = "idle"
                n["timer"] = random.randint(20, 120)
            continue
        n["timer"] -= 1                               # idle: count down, then try
        if n["timer"] > 0:
            continue
        d = pick_dir(n["range"])
        n["facing"] = d
        dx, dy = DELTA[d]
        tx, ty = n["cx"] + dx, n["cy"] + dy
        sx, sy = n["spawn"]
        if (abs(tx-sx) <= NPC_RANGE and abs(ty-sy) <= NPC_RANGE
                and 0 <= tx < m.GW and 0 <= ty < m.GH
                and m.walkable(tx, ty) and (tx, ty) != player_cell):
            n["cx"], n["cy"] = tx, ty
            n["vx"], n["vy"] = dx*NPC_SPEED, dy*NPC_SPEED
            n["phase"] = "walk"
            n["walkphase"] ^= 1
        else:
            n["timer"] = random.randint(15, 45)       # blocked: try again soon

VK = {"up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
      "W": 0x57, "A": 0x41, "S": 0x53, "D": 0x44,
      "Q": 0x51, "M": 0x4D, "I": 0x49, "R": 0x52, "B": 0x42, "X": 0x58,
      "G": 0x47,                                  # dump ASCII map grid
      "Z": 0x5A, "ENTER": 0x0D, "SPACE": 0x20}    # Z=A button, X=B button (back)


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
    MODES = ["block", "color", "braille", "ascii", "grid"]   # grid = live ASCII map
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
    apply_hidden(m)
    cx, cy = pick_start(m)
    px, py = m.player_px(cx, cy)
    facing, phase, moving, invert = DOWN, 0, False, True
    events = set()                    # event flags the scripts read/set
    script = None                     # active map-script VM (svm bytecode)
    locked = False                    # player input frozen during a cutscene
    ply_walk = None                   # (dir, cells) scripted player walk
    vx = vy = 0
    warp_armed = True
    last_map = last_pos = None        # LAST_MAP return target (set only when
    player = sprite("red")            # leaving an outside map, like Gen I)
    dialog = None                     # rolling 2-line window (dialog_open) when open
    transition = None                 # {"phase":"out"/"in","f":int,"warp":..} mid-warp
    battle = None                     # {"kind","phase","f","enemy","base"} battle intro
    party = pk.Party()                # the player's team (empty until a starter)
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
        apply_hidden(m)
        px, py = m.player_px(tx, ty)
        # facing is PRESERVED across the warp (walk up into a door -> face up
        # inside; the step-out-from-door sets DOWN for overworld exits).
        moving, warp_armed = False, False

    def scene_fb():
        cw, ch = CELL[mode]
        cam_x = clamp(px - CENTER, 0, m.PTWpx - VW_PX)
        cam_y = clamp(py - CENTER, 0, m.PTHpx - VH_PX)
        cam_x -= cam_x % cw
        cam_y -= cam_y % ch
        sprites = []
        for n in m.npcs:                         # NPCs (live position + walk anim)
            if n.get("hidden"):
                continue
            sx, sy = n["px"] - cam_x, n["py"] - cam_y
            if -16 < sx < VW_PX and -16 < sy < VH_PX:
                sx -= sx % cw
                sy -= sy % ch
                idx = n["walkphase"] if n["phase"] == "walk" else 0
                sprites.append((sprite(n["sprite"])[n["facing"]][idx], sx, sy))
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
        return fb

    def render_fb(fb, status=True):
        # Native, pixel-exact — the FULL GB screen, never cropped or scaled.
        # (battle/dialog use this even in "grid" mode -> fall back to block)
        lines = RENDER.get(mode, to_block)(fb).split("\n")
        _, trows = shutil.get_terminal_size((80, 80))
        out = ["\x1b[H"]
        for i, ln in enumerate(lines):
            out.append(f"\x1b[{i+1};1H{ln}\x1b[0m\x1b[K")
        if status and trows > len(lines):      # status only if there's a spare row
            out.append(f"\x1b[{len(lines)+1};1H WASD=walk Z=talk M=look[{mode}] "
                       f"I=invert[{'on' if invert else 'off'}] Q=quit "
                       f"\x1b[0m\x1b[K")
        sys.stdout.write("".join(out))
        sys.stdout.flush()

    def render_grid():
        # live ASCII map: one char per cell, '@' is you, updates as you walk
        pcell = ((px - m.pad_px) // 16, (py - m.pad_px) // 16)
        lines = grid_str(m, player_cell=pcell, npcs=m.npcs).split("\n")
        out = ["\x1b[H"]
        for i, ln in enumerate(lines):
            out.append(f"\x1b[{i+1};1H{ln}\x1b[0m\x1b[K")
        out.append(f"\x1b[{len(lines)+1};1H WASD=walk M=look[grid] Q=quit "
                   f"\x1b[0m\x1b[K")
        sys.stdout.write("".join(out))
        sys.stdout.flush()

    def draw():
        if mode == "grid":
            render_grid()
        else:
            render_fb(scene_fb())

    def step_script():
        """Interpret the active map-script bytecode until it blocks or ends."""
        nonlocal dialog, locked, facing, transition, px, py, ply_walk
        vm = script
        if vm.block is not None:
            if not vm.block():
                return
            vm.block = None
        code = vm.code
        while True:
            op = code[vm.pc]
            vm.pc += 1
            if op == svm.OP_END:
                vm.done = True
                return
            elif op == svm.OP_IFSET:
                flag = code[vm.pc]
                addr = code[vm.pc+1] | (code[vm.pc+2] << 8)
                vm.pc += 3
                if vm.prog.flags[flag] in events:
                    vm.pc = addr
            elif op == svm.OP_IFYGT:
                y = code[vm.pc]
                addr = code[vm.pc+1] | (code[vm.pc+2] << 8)
                vm.pc += 3
                if (py - m.pad_px) // 16 > y:
                    vm.pc = addr
            elif op == svm.OP_LOCK:
                locked = True
            elif op == svm.OP_RELEASE:
                locked = False
            elif op == svm.OP_FACEP:
                facing = svm.DIR_NAME[code[vm.pc]]
                vm.pc += 1
            elif op == svm.OP_TEXT:
                lines = resolve_far(m.base, vm.prog.texts[code[vm.pc]])
                vm.pc += 1
                if lines:
                    dialog = dialog_open(lines)
                    vm.block = lambda: dialog is None
                    return
            elif op == svm.OP_SHOW:
                m.npcs[code[vm.pc]]["hidden"] = False
                vm.pc += 1
            elif op == svm.OP_HIDE:
                n = m.npcs[code[vm.pc]]
                vm.pc += 1
                n["hidden"] = True
                n["cx"], n["cy"] = n["spawn"]
                n["px"], n["py"] = m.player_px(*n["spawn"])
                n["phase"], n["script_move"] = "idle", None
            elif op == svm.OP_FACENPC:
                m.npcs[code[vm.pc]]["facing"] = svm.DIR_NAME[code[vm.pc+1]]
                vm.pc += 2
            elif op == svm.OP_MOVENPC:
                i, d, cnt = code[vm.pc], code[vm.pc+1], code[vm.pc+2]
                vm.pc += 3
                m.npcs[i]["script_move"] = {"dir": svm.DIR_NAME[d],
                                            "remaining": cnt}
                vm.block = (lambda i=i: not npc_busy(m.npcs[i]))
                return
            elif op == svm.OP_SETFLAG:
                events.add(vm.prog.flags[code[vm.pc]])
                vm.pc += 1
            elif op == svm.OP_SFX:
                vm.pc += 1                        # no audio yet
            elif op == svm.OP_WAIT:
                vm.wait = code[vm.pc]
                vm.pc += 1

                def _wait():
                    vm.wait -= 1
                    return vm.wait <= 0
                vm.block = _wait
                return
            elif op == svm.OP_JUMP:
                vm.pc = code[vm.pc] | (code[vm.pc+1] << 8)
            elif op == svm.OP_SETPLY:
                px, py = m.player_px(code[vm.pc], code[vm.pc+1])
                vm.pc += 2
            elif op == svm.OP_MOVEPLY:
                ply_walk = (svm.DIR_NAME[code[vm.pc]], code[vm.pc+1])
                vm.pc += 2
                vm.block = lambda: ply_walk is None
                return
            elif op == svm.OP_STEPBOTH:
                i, od, pd = code[vm.pc], code[vm.pc+1], code[vm.pc+2]
                vm.pc += 3
                m.npcs[i]["script_move"] = {"dir": svm.DIR_NAME[od],
                                            "remaining": 1}
                ply_walk = (svm.DIR_NAME[pd], 1)
                vm.block = (lambda i=i: ply_walk is None
                            and not npc_busy(m.npcs[i]))
                return
            elif op == svm.OP_WARP:
                wcell = ((px - m.pad_px) // 16, (py - m.pad_px) // 16)
                if wcell in m.warp_at:
                    transition = {"phase": "out", "f": 0,
                                  "warp": m.warp_at[wcell]}
                    vm.block = lambda: transition is None
                    return

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
    prev_m = prev_q = prev_i = prev_t = prev_r = prev_b = prev_g = False
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
            now_r = held(VK["R"])     # reset event flags (re-watch cutscenes)
            if now_r and not prev_r:
                events.clear()
                apply_hidden(m)
                script, locked = None, False
            prev_r = now_r
            now_g = held(VK["G"])     # dump the current map as an ASCII grid
            if now_g and not prev_g:
                pcell = ((px - m.pad_px) // 16, (py - m.pad_px) // 16)
                with open(GRID_DUMP, "w", encoding="utf-8") as fh:
                    fh.write(grid_str(m, player_cell=pcell, npcs=m.npcs))
            prev_g = now_g
            now_b = held(VK["B"])     # debug: force a test battle (vs SQUIRTLE)
            if now_b and not prev_b and battle is None and transition is None:
                mine = party.mons[0] if party.mons else pk.Pokemon("charmander", 5)
                battle = make_battle("wild", pk.Pokemon("squirtle", 5),
                                     mine, scene_fb())
            prev_b = now_b

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

            # battle start: flash -> geometric wipe -> hold black -> placeholder.
            # (The battle screen itself is the next system; for now press Z to
            # leave once the intro lands.)
            if battle is not None:
                battle["f"] += 1
                ph = battle["phase"]
                if ph == "flash" and battle["f"] >= bx.FLASH_FRAMES:
                    battle["phase"], battle["f"] = "wipe", 0
                elif ph == "wipe" and battle["f"] >= bx.WIPE_FRAMES:
                    battle["phase"], battle["f"] = "hold", 0
                elif ph == "hold" and battle["f"] >= bx.HOLD_FRAMES:
                    battle["phase"], battle["f"] = "slide", 0
                elif ph == "slide" and battle["f"] >= bx.SLIDE_FRAMES:
                    battle["phase"], battle["f"] = "msg", 0
                elif ph == "throw" and battle["f"] >= bx.THROW_FRAMES:
                    battle["phase"], battle["f"] = "scale", 0
                elif ph == "scale" and battle["f"] >= bx.SCALE_FRAMES:
                    battle["phase"], battle["f"] = "ready", 0
                ph = battle["phase"]
                if ph in ("flash", "wipe"):
                    fb = bx.transition_frame(battle["base"], battle["kind"],
                                             ph, battle["f"])
                elif ph == "slide":
                    # the black hold has ended: the field is now white and the
                    # two pics slide on as solid black SILHOUETTES (enemy from
                    # the left, Red's trainer back from the right), then resolve.
                    t = battle["f"] / bx.SLIDE_FRAMES
                    fb = bs.blank_fb()
                    es, rb = battle["enemy_sil"], battle["red_sil"]
                    ex, ey = battle["enemy_spot"]
                    exc = round(-len(es[0]) + t * (ex + len(es[0])))
                    rxc = round(VW_PX + t * (8 - VW_PX))
                    bs.blit(fb, es, exc, ey)
                    bs.blit(fb, rb, rxc, 40)
                elif ph == "msg":                  # resolved: enemy + Red back
                    e = battle["enemy"]
                    fb = bs.blank_fb()
                    bs.draw_battle_screen(
                        fb, glyphs, battle["player_mon"], e,
                        message="Wild %s\nappeared!" % e.nickname,
                        arrow=(frame // 16) % 2 == 0,
                        player_back=battle["red_norm"], show_player_hud=False)
                elif ph == "throw":                # Red's back slides off left
                    e, mine = battle["enemy"], battle["player_mon"]
                    t = battle["f"] / bx.THROW_FRAMES
                    fb = bs.blank_fb()
                    bs.draw_battle_screen(fb, glyphs, mine, e,
                                          message="Go! %s!" % mine.nickname,
                                          player_back=[], show_player_hud=False)
                    bs.blit(fb, battle["red_norm"], round(8 - t * (8 + 56)), 40)
                elif ph == "scale":                # mon emerges: small -> full
                    e, mine = battle["enemy"], battle["player_mon"]
                    fb = bs.blank_fb()
                    bs.draw_battle_screen(fb, glyphs, mine, e,
                                          message="Go! %s!" % mine.nickname,
                                          player_back=[], show_player_hud=False)
                    n = round(bx.SCALE_START + (56 - bx.SCALE_START)
                              * battle["f"] / bx.SCALE_FRAMES)
                    n = max(8, min(56, n))
                    sm = bs.scale_to(battle["mon_back"], n)
                    bs.blit(fb, sm, 36 - n // 2, 96 - n)   # grow from bottom-center
                elif ph == "ready":                # full screen + FIGHT menu
                    e, mine = battle["enemy"], battle["player_mon"]
                    fb = bs.blank_fb()
                    bs.draw_battle_screen(fb, glyphs, mine, e)
                    if battle["menumsg"] is not None:
                        top, _, bot = battle["menumsg"].partition("\n")
                        draw_textbox(fb, glyphs, top, bot,
                                     arrow=(frame // 16) % 2 == 0)
                    elif battle["sub"] == "moves":
                        bs.draw_move_menu(fb, glyphs, mine, battle["movecur"])
                    else:                          # keep the message box, add menu
                        draw_textbox(fb, glyphs, "", "")
                        bs.draw_battle_menu(fb, glyphs, battle["menu"])
                else:                              # hold: black screen
                    fb = [[1] * VW_PX for _ in range(VH_PX)]
                render_fb(fb, status=False)
                if ph == "msg" and talk_edge:      # Z -> send out our mon
                    battle["phase"], battle["f"] = "throw", 0
                elif ph == "ready":
                    nav = battle["nav"]

                    def medge(name, *vks):
                        now = any(held(VK[k]) for k in vks)
                        edge = now and not nav.get(name, False)
                        nav[name] = now
                        return edge
                    up = medge("u", "up", "W")
                    dn = medge("d", "down", "S")
                    lf = medge("l", "left", "A")
                    rt = medge("r", "right", "D")
                    back = medge("x", "X")
                    mine = battle["player_mon"]
                    if battle["menumsg"] is not None:
                        if talk_edge:              # dismiss the message
                            if battle["fleeing"]:
                                battle = None
                            else:
                                battle["menumsg"] = None
                    elif battle["sub"] == "moves":  # FIGHT move submenu
                        n = len(mine.moves)
                        if up:
                            battle["movecur"] = (battle["movecur"] - 1) % n
                        if dn:
                            battle["movecur"] = (battle["movecur"] + 1) % n
                        if back:
                            battle["sub"] = None
                        elif talk_edge:            # pick a move (no engine yet)
                            mvname = mine.moves[battle["movecur"]].replace("_", " ")
                            battle["menumsg"] = "%s used\n%s!" % (mine.nickname, mvname)
                            battle["sub"] = None
                    else:                          # navigate the 2x2 menu
                        cur = battle["menu"]
                        if up and cur in (1, 3):
                            cur -= 1
                        if dn and cur in (0, 2):
                            cur += 1
                        if lf and cur in (2, 3):
                            cur -= 2
                        if rt and cur in (0, 1):
                            cur += 2
                        battle["menu"] = cur
                        if talk_edge:              # select
                            if cur == 0:           # FIGHT -> move submenu
                                battle["sub"], battle["movecur"] = "moves", 0
                            elif cur == 1:         # ITEM
                                battle["menumsg"] = "You have no\nITEMs!"
                            elif cur == 2:         # PKMN
                                battle["menumsg"] = "No other\n#MON!"
                            else:                  # RUN
                                battle["menumsg"] = "Got away\nsafely!"
                                battle["fleeing"] = True
                dt = time.perf_counter() - t0
                if dt < frame_dt:
                    time.sleep(frame_dt - dt)
                continue

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

            # advance an ACTIVE map-script cutscene (the trigger that creates it
            # runs after a step settles, in the not-moving block below).
            if script is not None:
                # drive scripted player movement (cutscene); paced to NPC_SPEED
                # so the player and Oak step in sync (STEPBOTH)
                if moving:
                    px += vx
                    py += vy
                    if (px-m.pad_px) % 16 == 0 and (py-m.pad_px) % 16 == 0:
                        moving = False
                if not moving and ply_walk is not None:
                    if ply_walk[1] > 0:
                        dd = ply_walk[0]
                        dx, dy = DELTA[dd]
                        facing = dd
                        moving = True
                        vx, vy = dx*NPC_SPEED, dy*NPC_SPEED
                        phase ^= 1
                        ply_walk = (dd, ply_walk[1]-1)
                    else:
                        ply_walk = None
                update_scripted_npcs(m)
                step_script()
                if script.done:
                    script = None
                if script is not None or locked:
                    draw()
                    dt = time.perf_counter() - t0
                    if dt < frame_dt:
                        time.sleep(frame_dt - dt)
                    continue            # cutscene in progress -> freeze free roam

            # NPC wandering: refresh occupancy, advance, refresh again so the
            # player's collision sees NPCs' new cells
            pcell = ((px - m.pad_px) // 16, (py - m.pad_px) // 16)
            m.npc_at = {(n["cx"], n["cy"]): n for n in m.npcs
                        if not n.get("hidden")}
            update_npcs(m, pcell)
            m.npc_at = {(n["cx"], n["cy"]): n for n in m.npcs
                        if not n.get("hidden")}

            if moving:
                px += vx
                py += vy
                if (px - m.pad_px) % 16 == 0 and (py - m.pad_px) % 16 == 0:
                    moving = False
                    # wild encounter: a step landed on a grass tile
                    gx, gy = (px - m.pad_px) // 16, (py - m.pad_px) // 16
                    if (battle is None and transition is None
                            and m.collision_tile(gx, gy) == GRASS_TILE):
                        enemy = roll_encounter(m.base, random)
                        if enemy is not None:
                            # stand-in player mon until the starter/party system
                            # is wired in (Oak's Lab script).
                            mine = (party.mons[0] if party.mons
                                    else pk.Pokemon("charmander", 5))
                            battle = make_battle("wild", enemy, mine, scene_fb())

            if not moving:
                cx = (px - m.pad_px) // 16
                cy = (py - m.pad_px) // 16
                # map-script trigger: settled on a new cell -> run this map's
                # registered script (bytecode VM), if any. It checks conditions
                # and, if it fires, LOCKs before movement input runs below.
                prog = svm.MAP_SCRIPTS.get(m.const)
                if prog is not None and script is None and not locked:
                    script = svm.ScriptVM(prog)
                    step_script()
                    if script.done:
                        script = None
                # seamless map-connection crossing (no fade): stepped off the
                # edge into a connected map -> switch and remap coords
                if not (0 <= cx < m.GW and 0 <= cy < m.GH):
                    nb = m._neighbor_cell(cx, cy)
                    if nb is not None:
                        m = MapData(nb[0])
                        apply_hidden(m)
                        cx, cy = nb[1], nb[2]
                        px, py = m.player_px(cx, cy)
                        warp_armed = True
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
                            if npc is not None:     # NPC stops & faces the player
                                npc["phase"] = "idle"
                                npc["px"], npc["py"] = m.player_px(npc["cx"],
                                                                   npc["cy"])
                                npc["timer"] = random.randint(30, 120)
                                npc["_save_face"] = npc["facing"]
                                npc["facing"] = OPPOSITE[facing]
                                dialog["npc"] = npc

            if dialog is None and transition is None and not moving and not locked:
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
