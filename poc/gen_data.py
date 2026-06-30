#!/usr/bin/env python3
"""
pokered-nano — training-corpus generator. Rolls out the headless oracle engine
(pokeworld.World) and emits (state, action, next_state) ASCII transitions for
training a model to predict the game's dynamics.

    python gen_data.py [steps_per_map] [out.jsonl]

Output: JSONL, one transition per line: {"map","action","state","next"}.
The model's job: given state + action, produce next.  It learns the rules
(collision, doors/warps, connections, NPC obstacles) from these examples.
"""

import os
import sys
import json
import random

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pokeworld import World, DELTA
from mapdata import MapData, _MAP_INDEX

ACTIONS = list(DELTA)          # up / down / left / right


def small_maps(max_cells=120):
    """All maps small enough for short fixed-frame grids. Training across MANY
    diverse small layouts forces the model to learn the RULE, not memorize one
    map -> real generalization."""
    out = []
    for mc in _MAP_INDEX:
        try:
            m = MapData(mc)
            if 0 < m.GW * m.GH <= max_cells:
                out.append(mc)
        except Exception:
            pass
    return out


def rollout(map_const, steps, rng, view=0):
    w = World(map_const)

    def render():                           # read the CURRENT w (it gets reset)
        return w.render_view(view) if view else w.render_plain()
    out = []
    for _ in range(steps):
        state = render()
        action = rng.choice(ACTIONS)
        w.step(action)
        if w.m.const != map_const:          # stepped through a warp/connection ->
            w = World(map_const)            # reset; keep the corpus within-map
            continue
        out.append({"map": map_const, "action": action,
                    "state": state, "next": render()})
    return out


def main():
    steps = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    out_path = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
        os.path.dirname(__file__), "transitions.jsonl")
    view = int(sys.argv[3]) if len(sys.argv) > 3 else 0   # 0=full map, R>0=viewport
    rng = random.Random(1234)
    maps = small_maps()
    print("maps: %d  (steps/map=%d, view=%d)" % (len(maps), steps, view), flush=True)
    n = 0
    with open(out_path, "w", encoding="utf-8") as f:
        for mc in maps:
            try:
                rolls = rollout(mc, steps, rng, view)
            except Exception as e:
                print("skip %s: %s" % (mc, e))
                continue
            for t in rolls:
                f.write(json.dumps(t) + "\n")
                n += 1
    print("wrote %d transitions -> %s" % (n, out_path))


if __name__ == "__main__":
    main()
