#!/usr/bin/env python3
"""
pokered-nano — Pokemon species data + owned-Pokemon instances.

Species data is parsed straight from the disassembly (data/pokemon/base_stats/*),
so the 151 species' base stats, types, initial moves and growth rates are
ground-truth. An owned Pokemon is an instance of a species at a level, with
stats computed by the real Gen I formula (home/move_mon.asm CalcStat):

    stat = ((Base + IV)*2 + floor(ceil(sqrt(statexp))/4)) * Level / 100 + off
           off = Level + 10 for HP, else 5 ; capped at 999

Per DESIGN (DV/EV removal -> deterministic base+level), IV and statexp default
to 0, but the formula is faithful and the inputs are tunable. Stdlib only.
"""

import os
import re
import math

ROOT = r"C:\Users\Anthony\pokered-nano\pokered-master"
MAX_STAT = 999
STAT_NAMES = ("hp", "atk", "def", "spd", "spc")

# filenames whose display name isn't just an uppercase
_NAME_FIX = {
    "nidoran_m": "NIDORAN♂", "nidoran_f": "NIDORAN♀",
    "mr_mime": "MR.MIME", "farfetch_d": "FARFETCH'D",
    "nidoranm": "NIDORAN♂", "nidoranf": "NIDORAN♀",
    "farfetchd": "FARFETCH'D",
}


def _disp_name(key):
    return _NAME_FIX.get(key, key.upper())


def _parse_species_file(path):
    txt = open(path, encoding="utf-8", errors="replace").read()
    dex = re.search(r"db (DEX_\w+)", txt).group(1)[len("DEX_"):]
    base = re.search(r"db\s+(\d+),\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+)", txt)
    hp, atk, df, spd, spc = (int(g) for g in base.groups())
    t = re.search(r"db (\w+), (\w+) ; type", txt)
    catch = int(re.search(r"db (\d+) ; catch rate", txt).group(1))
    bexp = int(re.search(r"db (\d+) ; base exp", txt).group(1))
    mv = re.search(r"db (\w+), (\w+), (\w+), (\w+) ; level 1 learnset", txt)
    growth = re.search(r"db (GROWTH_\w+)", txt).group(1)[len("GROWTH_"):]
    moves = [m for m in mv.groups() if m != "NO_MOVE"]
    # PSYCHIC's type constant is PSYCHIC_TYPE (move name clash); clean for display
    t1, t2 = t.group(1).replace("_TYPE", ""), t.group(2).replace("_TYPE", "")
    types = [t1] if t1 == t2 else [t1, t2]
    return {"dex": dex, "base": {"hp": hp, "atk": atk, "def": df,
                                 "spd": spd, "spc": spc},
            "types": types, "catch_rate": catch, "base_exp": bexp,
            "moves": moves, "growth": growth}


def load_species():
    """key (filename, e.g. 'bulbasaur') -> species dict. Adds 'name' and 'key'."""
    d = {}
    bdir = os.path.join(ROOT, "data", "pokemon", "base_stats")
    for fn in os.listdir(bdir):
        if not fn.endswith(".asm"):
            continue
        key = fn[:-4]
        s = _parse_species_file(os.path.join(bdir, fn))
        s["key"] = key
        s["name"] = _disp_name(key)
        d[key] = s
    return d


# filenames without underscores whose EvosMoves label is mixed-case
_LABEL_FIX = {"mrmime": "MrMime", "nidoranf": "NidoranF", "nidoranm": "NidoranM"}


def _camel(key):
    if key in _LABEL_FIX:
        return _LABEL_FIX[key]
    return "".join(p.capitalize() for p in key.split("_"))


def load_evos_moves():
    """label -> {evolutions: [(method, *args)], learnset: [(level, move)]}.
    Parsed from data/pokemon/evos_moves.asm <Species>EvosMoves blocks."""
    txt = open(os.path.join(ROOT, "data", "pokemon", "evos_moves.asm"),
               encoding="utf-8", errors="replace").read()
    out = {}
    for label, body in re.findall(r"^(\w+)EvosMoves:\n(.*?)(?=^\w+EvosMoves:|\Z)",
                                  txt, re.S | re.M):
        evos, learn = [], []
        # the block is: evolutions... db 0 ; learnset... db 0
        section = 0
        for line in body.splitlines():
            line = line.split(";")[0].strip()
            if not line.startswith("db"):
                continue
            args = [a.strip() for a in line[2:].split(",")]
            if args == ["0"]:
                section += 1
                continue
            if section == 0:                      # evolutions
                evos.append(tuple(args))
            elif section == 1:                    # learnset: level, move
                learn.append((int(args[0]), args[1]))
        out[label] = {"evolutions": evos, "learnset": learn}
    return out


SPECIES = load_species()
_EVOS = load_evos_moves()
for _k, _s in SPECIES.items():                    # attach learnset/evolutions
    em = _EVOS.get(_camel(_k), {"evolutions": [], "learnset": []})
    _s["learnset"] = em["learnset"]
    _s["evolutions"] = em["evolutions"]
BY_DEX = {s["dex"]: s for s in SPECIES.values()}   # dex const name -> species


# --- experience / growth curves (Gen I, 4 groups) --------------------------

def exp_for_level(growth, n):
    """Total experience needed to BE level n, by growth-rate group."""
    if n <= 1:
        return 0
    if growth == "MEDIUM_FAST":
        e = n**3
    elif growth == "MEDIUM_SLOW":
        e = (6*n**3)//5 - 15*n**2 + 100*n - 140
    elif growth == "FAST":
        e = (4*n**3)//5
    elif growth == "SLOW":
        e = (5*n**3)//4
    else:
        e = n**3
    return max(0, e)


def exp_gain(base_exp, enemy_level, trainer=False, participants=1):
    """Experience a winner gains for a fainted mon (Gen I)."""
    g = (base_exp * enemy_level) // 7 // max(1, participants)
    if trainer:
        g = g * 3 // 2
    return g


def moves_at_level(species_key, level):
    """The (up to 4) moves a freshly-created mon of this species knows at a
    level: its initial moves plus learnset entries learned by then, last 4."""
    s = SPECIES[species_key]
    known = list(s["moves"])
    for lvl, mv in s["learnset"]:
        if lvl <= level:
            known.append(mv)
    # keep order, drop dups keeping the latest 4
    seen = []
    for mv in known:
        if mv in seen:
            seen.remove(mv)
        seen.append(mv)
    return seen[-4:]


def _ceil_sqrt(n):
    if n <= 0:
        return 0
    r = math.isqrt(n)
    return r if r*r == n else r + 1


def calc_stat(base, level, is_hp, iv=0, statexp=0):
    core = ((base + iv) * 2 + _ceil_sqrt(statexp) // 4) * level // 100
    return min(MAX_STAT, core + (level + 10 if is_hp else 5))


class Pokemon:
    """An owned Pokemon: a species instance at a level with computed stats."""
    def __init__(self, species_key, level, nickname=None, iv=0,
                 ot="RED", ot_id=0):
        s = SPECIES[species_key]
        self.species = species_key
        self.dex = s["dex"]
        self.name = s["name"]
        self.nickname = nickname or s["name"]
        self.level = level
        self.types = list(s["types"])
        self.moves = moves_at_level(species_key, level)   # level-appropriate set
        self.ot, self.ot_id = ot, ot_id
        self.iv = iv
        self.stats = {st: calc_stat(s["base"][st], level, st == "hp", iv)
                      for st in STAT_NAMES}
        self.max_hp = self.stats["hp"]
        self.cur_hp = self.max_hp
        self.status = None                      # None / 'PSN' / 'PAR' / ...

    def __repr__(self):
        return (f"<{self.nickname} L{self.level} {'/'.join(self.types)} "
                f"HP {self.cur_hp}/{self.max_hp} "
                f"Atk{self.stats['atk']} Def{self.stats['def']} "
                f"Spd{self.stats['spd']} Spc{self.stats['spc']} "
                f"moves={self.moves}>")


class Party:
    """The player's party: up to 6 owned Pokemon (Gen I PARTY_LENGTH)."""
    MAX = 6

    def __init__(self):
        self.mons = []

    def add(self, mon):
        if len(self.mons) >= self.MAX:
            return False                         # full -> would go to a Box
        self.mons.append(mon)
        return True

    def __len__(self):
        return len(self.mons)
