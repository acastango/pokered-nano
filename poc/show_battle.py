#!/usr/bin/env python3
"""
Standalone battle-screen viewer — Charmander (you) vs Squirtle (foe).

    C:\\msys64\\mingw64\\bin\\python.exe show_battle.py            (auto-fit)
    C:\\msys64\\mingw64\\bin\\python.exe show_battle.py block      (force a mode)
    ...also: braille | color | ascii

The GB screen is 160x144 px. "block" needs a terminal >=160 columns wide;
"braille"/"color" pack 2 px per column so they fit an 80-column terminal. The
viewer auto-picks whichever fits your window. Press Enter to exit.
"""

import os
import sys
import shutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import battle_screen as bs
import pokemon as pk
from text_engine import load_glyphs
from play_pallet import to_block, to_braille, to_braille_color, to_ascii

if os.name == "nt":                          # same setup play.py uses
    import ctypes
    k = ctypes.windll.kernel32
    k.SetConsoleMode(k.GetStdHandle(-11), 7)  # processed out + wrap + VT (ANSI)
    k.SetConsoleOutputCP(65001)
    k.SetConsoleCP(65001)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

RENDER = {"block": to_block, "braille": to_braille,
          "color": to_braille_color, "ascii": to_ascii}
WIDTH = {"block": 160, "braille": 80, "color": 80, "ascii": 80}


def main():
    glyphs = load_glyphs()
    fb = bs.blank_fb()
    bs.draw_battle_screen(fb, glyphs, pk.Pokemon("charmander", 5),
                          pk.Pokemon("squirtle", 5),
                          message="Wild SQUIRTLE\nappeared!", arrow=True)

    cols, _ = shutil.get_terminal_size((80, 24))
    mode = sys.argv[1] if len(sys.argv) > 1 else "block"   # block is the default
    if mode not in RENDER:
        mode = "block"
    lines = RENDER[mode](fb).split("\n")

    out = ["\x1b[?7l\x1b[2J\x1b[H"]            # no-wrap, clear, home
    for i, ln in enumerate(lines):
        out.append(f"\x1b[{i+1};1H{ln}\x1b[0m")
    note = f"  mode={mode} ({WIDTH[mode]} cols)  terminal={cols} cols  [Enter] exit "
    if WIDTH[mode] > cols:
        note += " <-- WIDEN TERMINAL or try: show_battle.py braille "
    out.append(f"\x1b[{len(lines)+1};1H{note}")
    sys.stdout.write("".join(out))
    sys.stdout.flush()
    try:
        input()
    finally:
        sys.stdout.write("\x1b[?7h\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
