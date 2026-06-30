#!/usr/bin/env python3
"""
pokered-nano — trainer party data (data/trainers/parties.asm).

Each trainer CLASS has a list of parties (one per trainer instance of that
class). A party line is either:
    db level, SPECIES, SPECIES, ..., 0          ; all mons at one level
    db $FF, level, SPECIES, level, SPECIES, 0   ; per-mon levels
e.g. TRAINERS['Rival1'][0] = [(5, 'SQUIRTLE')]  (the lab rival, if you took
Bulbasaur -> [1] Squirtle ... matched by starter choice). Stdlib only.
"""

import os
import re

ROOT = r"C:\Users\Anthony\pokered-nano\pokered-master"


def load_trainers():
    txt = open(os.path.join(ROOT, "data", "trainers", "parties.asm"),
               encoding="utf-8", errors="replace").read()
    out = {}
    for label, body in re.findall(r"^(\w+)Data:\n(.*?)(?=^\w+Data:|\Z)",
                                  txt, re.S | re.M):
        parties = []
        for line in body.splitlines():
            line = line.split(";")[0].strip()
            if not line.startswith("db"):
                continue
            args = [a.strip() for a in line[2:].split(",") if a.strip()]
            if args and args[-1] == "0":
                args = args[:-1]
            if not args:
                continue
            party = []
            if args[0] == "$FF":               # per-mon levels
                rest = args[1:]
                for i in range(0, len(rest)-1, 2):
                    party.append((int(rest[i]), rest[i+1]))
            else:                              # uniform level
                lvl = int(args[0])
                party = [(lvl, sp) for sp in args[1:]]
            parties.append(party)
        out[label] = parties
    return out


TRAINERS = load_trainers()
