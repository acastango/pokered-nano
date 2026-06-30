#!/usr/bin/env python3
"""
pokered-nano — ASCII map grid (debug view), modeled on pokered-c's
Debug_PrintGrid (src/game/debug_overlay.c). One char per movement cell
(16x16px = the unit collision/warps/NPCs live on), classified by what's there:

    @ player   1-9/A-Z NPC (unique per NPC)   D warp/door   S sign
    g grass (wild encounters)   # solid/impassable   . walkable

    C:\\msys64\\mingw64\\bin\\python.exe ascii_map.py [MAP_CONST]   (default PALLET_TOWN)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mapdata import MapData

GRASS_TILE = 0x52       # Overworld wGrassTile
# NPC glyphs: digits then uppercase, skipping ones used by terrain (D, S, G)
NPC_GLYPHS = "123456789ABCEFHIJKLMNOPQRTUVWXYZ"


def classify(m, cx, cy, player_cell, npc_chars):
    if player_cell == (cx, cy):
        return "@"
    if (cx, cy) in npc_chars:
        return npc_chars[(cx, cy)]
    if (cx, cy) in m.warp_at:
        return "D"
    if (cx, cy) in getattr(m, "sign_at", {}):
        return "S"
    if not m.walkable(cx, cy):
        return "#"
    if m.collision_tile(cx, cy) == GRASS_TILE:
        return "g"
    return "."


def plain_grid(m, player_cell=None, npcs=None):
    """Just the WxH cell grid (no header/border/legend) for training corpora.
    Allocentric: the map frame is static and only '@' moves -> easy to learn
    and fully predictable (the natural closed-loop world-model format)."""
    npcs = m.npcs if npcs is None else npcs
    npc_chars = {(n["cx"], n["cy"]): NPC_GLYPHS[i % len(NPC_GLYPHS)]
                 for i, n in enumerate(k for k in npcs if not k.get("hidden"))}
    return "\n".join("".join(classify(m, cx, cy, player_cell, npc_chars)
                             for cx in range(m.GW)) for cy in range(m.GH))


def viewport(m, cx, cy, npcs=None, radius=4, oob=" "):
    """Egocentric fixed (2R+1)x(2R+1) window centered on (cx,cy): '@' at the
    center, off-map cells -> oob char. Player-centered & translation-invariant,
    so the movement/collision rules are local and easy for a small model."""
    npcs = m.npcs if npcs is None else npcs
    npc_chars = {(n["cx"], n["cy"]): NPC_GLYPHS[i % len(NPC_GLYPHS)]
                 for i, n in enumerate(k for k in npcs if not k.get("hidden"))}
    rows = []
    for dy in range(-radius, radius + 1):
        row = []
        for dx in range(-radius, radius + 1):
            x, y = cx + dx, cy + dy
            if dx == 0 and dy == 0:
                row.append("@")
            elif not (0 <= x < m.GW and 0 <= y < m.GH):
                row.append(oob)
            else:
                row.append(classify(m, x, y, None, npc_chars))
        rows.append("".join(row))
    return "\n".join(rows)


def grid_str(m, player_cell=None, npcs=None, legend=True):
    """Render map m as an ASCII grid (one char per cell)."""
    npcs = m.npcs if npcs is None else npcs
    npc_chars, gi = {}, 0
    for n in npcs:
        if n.get("hidden"):
            continue
        npc_chars[(n["cx"], n["cy"])] = NPC_GLYPHS[gi % len(NPC_GLYPHS)]
        gi += 1

    notes = ["@=player   1-9/A-Z=NPC",
             "D=warp/door   S=sign",
             "g=grass   #=solid   .=walkable"]
    bar = "+" + "-" * m.GW + "+"
    out = ["MAP: %s  (%dx%d cells)" % (m.const, m.GW, m.GH), bar]
    for cy in range(m.GH):
        row = "".join(classify(m, cx, cy, player_cell, npc_chars)
                      for cx in range(m.GW))
        note = notes[cy] if legend and cy < len(notes) else ""
        out.append("|%s| %s" % (row, note))
    out.append(bar)
    return "\n".join(out)


if __name__ == "__main__":
    mc = sys.argv[1] if len(sys.argv) > 1 else "PALLET_TOWN"
    print(grid_str(MapData(mc)))
