#!/usr/bin/env python3
"""
pokered-nano — wild encounter data (data/wild/maps/<Map>.asm).

Per map: a grass table and a water table, each an encounter RATE (0 = none)
and 10 (level, species) slots. Which slot is chosen follows fixed cumulative
weights (data/wild/probabilities.asm). Stdlib only.
"""

import os
import re

ROOT = r"C:\Users\Anthony\pokered-nano\pokered-master"

# slot weights out of 256 (WildMonEncounterSlotChances)
SLOT_WEIGHTS = [51, 51, 39, 25, 25, 25, 13, 13, 11, 3]


def _parse_table(body):
    rate = re.search(r"def_(?:grass|water)_wildmons\s+(\d+)", body)
    slots = [(int(l), s) for l, s in
             re.findall(r"db\s+(\d+),\s*(\w+)", body)]
    return {"rate": int(rate.group(1)) if rate else 0, "slots": slots}


def load_wild():
    """map basename (e.g. 'Route1') -> {'grass': {...}, 'water': {...}}."""
    out = {}
    wdir = os.path.join(ROOT, "data", "wild", "maps")
    for fn in os.listdir(wdir):
        if not fn.endswith(".asm"):
            continue
        txt = open(os.path.join(wdir, fn), encoding="utf-8",
                   errors="replace").read()
        g = re.search(r"def_grass_wildmons.*?end_grass_wildmons", txt, re.S)
        w = re.search(r"def_water_wildmons.*?end_water_wildmons", txt, re.S)
        out[fn[:-4]] = {"grass": _parse_table(g.group(0)) if g else {"rate": 0, "slots": []},
                        "water": _parse_table(w.group(0)) if w else {"rate": 0, "slots": []}}
    return out


WILD = load_wild()
