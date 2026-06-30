#!/usr/bin/env python3
"""
pokered-nano — headless, deterministic, cell-level world engine.

This is the GROUND-TRUTH oracle for training a model to "be" Pokemon Red: it
applies the real overworld rules (collision, NPC obstacles, map connections,
warps/doors) one tile-step at a time and renders the state as the ASCII grid.
No pixels, no animation, no real-time loop. Reuses the verified mapdata logic.

    w = World("PALLET_TOWN")
    w.step("up")            # actions: up/down/left/right
    print(w.render())       # ASCII grid (the state representation)

Feed (render(), action, render()) triples to gen_data.py to build the corpus.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mapdata import MapData
from ascii_map import grid_str, viewport, plain_grid

DELTA = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}


class World:
    def __init__(self, map_const, cx=None, cy=None, facing="down"):
        self.last_map = self.last_pos = None
        self.facing = facing
        self._load(map_const, cx, cy)

    def _load(self, map_const, cx=None, cy=None):
        self.m = MapData(map_const)
        self.npc_cells = {(n["cx"], n["cy"]) for n in self.m.npcs
                          if not n.get("hidden")}
        if cx is None:
            cx, cy = self._default_start()
        self.cx, self.cy = cx, cy

    def _default_start(self):
        for cy in range(self.m.GH):
            for cx in range(self.m.GW):
                if self.walkable(cx, cy) and (cx, cy) not in self.m.warp_at:
                    return cx, cy
        return self.m.GW // 2, self.m.GH // 2

    def walkable(self, cx, cy):
        if (cx, cy) in self.npc_cells:
            return False
        return self.m.walkable(cx, cy)

    def _warp(self, warp):
        wx, wy, dest, wid = warp
        if self.m.outside:                 # remember where we left the overworld
            self.last_map, self.last_pos = self.m.const, (wx, wy)
        if dest == "LAST_MAP":
            if self.last_map is None:
                return
            self._load(self.last_map, *self.last_pos)
        else:
            nm = MapData(dest)
            tx, ty, _, _ = nm.warps[wid - 1]    # dest id is 1-based
            self._load(dest, tx, ty)

    def step(self, action):
        """Apply one tile-step. Returns True if the player's cell changed."""
        if action not in DELTA:
            return False
        self.facing = action
        dx, dy = DELTA[action]
        nx, ny = self.cx + dx, self.cy + dy
        if not (0 <= nx < self.m.GW and 0 <= ny < self.m.GH):
            nb = self.m._neighbor_cell(nx, ny)    # seamless map connection
            if nb is not None:
                self._load(nb[0], nb[1], nb[2])
                return True
            return False
        if not self.walkable(nx, ny):
            return False                          # bumped a wall/NPC
        self.cx, self.cy = nx, ny
        if (self.cx, self.cy) in self.m.warp_at:  # stepped onto a door/warp
            self._warp(self.m.warp_at[(self.cx, self.cy)])
        return True

    def render(self):
        return grid_str(self.m, (self.cx, self.cy), self.m.npcs, legend=False)

    def render_view(self, radius=4):
        return viewport(self.m, self.cx, self.cy, self.m.npcs, radius)

    def render_plain(self):
        return plain_grid(self.m, (self.cx, self.cy), self.m.npcs)


if __name__ == "__main__":
    w = World("PALLET_TOWN")
    print(w.render())
    for a in ["up", "up", "left", "down"]:
        moved = w.step(a)
        print("\n>>> %s (%s)\n" % (a, "moved" if moved else "blocked"))
        print(w.render())
