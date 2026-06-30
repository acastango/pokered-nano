#!/usr/bin/env python3
"""
pokered-nano — move data + the Gen I type chart, parsed from the disassembly.

  * moves:   data/moves/moves.asm   (effect, power, type, accuracy, PP)
  * types:   data/types/type_matchups.asm  (attacker x defender -> multiplier)

The type chart is a sparse list of exceptions; any pair not listed is neutral
(x1). This is exactly the form DESIGN flags as already-algorithmized data to
keep near-exact. Stdlib only.
"""

import os
import re

ROOT = r"C:\Users\Anthony\pokered-nano\pokered-master"

# effectiveness constant -> multiplier (Gen I stores these *10; we use floats)
_EFF = {"SUPER_EFFECTIVE": 2.0, "NOT_VERY_EFFECTIVE": 0.5, "NO_EFFECT": 0.0}


def _clean_type(t):
    return t.replace("_TYPE", "")


def load_moves():
    """move constant (e.g. 'TACKLE') -> {effect,power,type,accuracy,pp,name}."""
    txt = open(os.path.join(ROOT, "data", "moves", "moves.asm"),
               encoding="utf-8", errors="replace").read()
    out = {}
    for name, eff, power, typ, acc, pp in re.findall(
            r"move\s+(\w+),\s*(\w+),\s*(\d+),\s*(\w+),\s*(\d+),\s*(\d+)", txt):
        out[name] = {"effect": eff, "power": int(power),
                     "type": _clean_type(typ), "accuracy": int(acc),
                     "pp": int(pp), "name": name.replace("_", " ")}
    return out


def load_type_chart():
    """(attacker_type, defender_type) -> multiplier, for the listed exceptions."""
    txt = open(os.path.join(ROOT, "data", "types", "type_matchups.asm"),
               encoding="utf-8", errors="replace").read()
    chart = {}
    for atk, dfn, eff in re.findall(
            r"db\s+(\w+),\s*(\w+),\s*(SUPER_EFFECTIVE|NOT_VERY_EFFECTIVE|NO_EFFECT)",
            txt):
        chart[(_clean_type(atk), _clean_type(dfn))] = _EFF[eff]
    return chart


MOVES = load_moves()
TYPE_CHART = load_type_chart()

# In Gen I, physical vs special is decided by the move's TYPE, not the move.
# Special types are those >= FIRE in type_constants.asm.
SPECIAL_TYPES = {"FIRE", "WATER", "GRASS", "ELECTRIC", "PSYCHIC", "ICE", "DRAGON"}

# moves with a 1/8 crit ratio instead of base (data/battle/critical_hit_moves.asm)
HIGH_CRIT_MOVES = {"KARATE_CHOP", "RAZOR_LEAF", "CRABHAMMER", "SLASH"}

# stat-stage multipliers, index = stage + 6 (data/battle/stat_modifiers.asm)
STAT_STAGE = [25/100, 28/100, 33/100, 40/100, 50/100, 66/100, 1.0,
              15/10, 2.0, 25/10, 3.0, 35/10, 4.0]


def is_special(move_type):
    return move_type in SPECIAL_TYPES


def stage_mult(stage):
    """stage in [-6, +6] -> stat multiplier."""
    return STAT_STAGE[max(-6, min(6, stage)) + 6]


def effectiveness(atk_type, defender_types):
    """Combined type multiplier of an attacking type vs a (1- or 2-type)
    defender: the product over each defending type (neutral if unlisted)."""
    mult = 1.0
    for d in defender_types:
        mult *= TYPE_CHART.get((atk_type, d), 1.0)
    return mult
