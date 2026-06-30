#!/usr/bin/env python3
"""Robust closed-loop benchmark: average the faithful horizon over many maps
instead of trusting one noisy rollout.

    <conda-python> poc\\bench.py [n_maps] [steps]
"""
import os
import sys
import random
import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rollout import load_model, predict
from pokeworld import World, DELTA
from gen_data import small_maps


def longest_run(oks):
    best = cur = 0
    for ok in oks:
        cur = cur + 1 if ok else 0
        best = max(best, cur)
    return best


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 25
    K = int(sys.argv[2]) if len(sys.argv) > 2 else 60
    model, stoi, itos, T = load_model()
    maps = small_maps()
    sample = random.Random(1).sample(maps, min(n, len(maps)))
    runs, agrees, covs, rows = [], [], [], []
    for mc in sample:
        w = World(mc)
        reach = w.spawn_main()                 # largest walkable region, central
        if len(reach) < 2:
            continue
        sim = w.render_plain()
        rng = random.Random(7)
        oks, visited = [], {(w.cx, w.cy)}
        for _ in range(K):
            a = rng.choice(list(DELTA))
            sim = predict(model, sim, a, stoi, itos, T)
            w.step(a)
            if w.m.const != mc:
                break
            visited.add((w.cx, w.cy))          # oracle's true path
            oks.append(sim == w.render_plain())
        if not oks:
            continue
        lr = longest_run(oks)
        ag = 100 * sum(oks) / len(oks)
        cov = 100 * len(visited) / len(reach)
        runs.append(lr); agrees.append(ag); covs.append(cov)
        rows.append((mc, lr, ag, cov, len(reach), len(oks)))
    rows.sort(key=lambda r: -r[1])
    print("map                              longest  agree%  cover%  cells  steps")
    for mc, lr, ag, cov, nc, ln in rows:
        print("  %-30s %5d    %4.0f    %4.0f   %4d   %4d" % (mc, lr, ag, cov, nc, ln))
    print("\n%d maps  |  avg longest faithful run: %.1f  |  avg agreement: %.0f%%  "
          "|  avg coverage: %.0f%%  |  median longest: %d"
          % (len(runs), sum(runs) / len(runs), sum(agrees) / len(agrees),
             sum(covs) / len(covs), sorted(runs)[len(runs) // 2]))


if __name__ == "__main__":
    main()
