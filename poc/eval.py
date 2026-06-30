#!/usr/bin/env python3
"""
pokered-nano — score the learned model against the ground-truth oracle.

Generates fresh transitions from pokeworld (held-out seed), feeds the model
(state + action), greedily generates the predicted next state, and compares it
to what the real engine produces. Reports exact-match and per-cell accuracy,
split by moved vs blocked (the collision rule).

    python eval.py [n_per_map] [view_radius]
"""

import os
import sys
import json
import random
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from train import GPT, ACT, END, PAD
from pokeworld import World, DELTA

HERE = os.path.dirname(os.path.abspath(__file__))
MAPS = ["REDS_HOUSE_1F", "BLUES_HOUSE"]


def load_model():
    cfg = json.load(open(os.path.join(HERE, "model.json")))
    w = np.load(os.path.join(HERE, "model.npz"))
    chars = cfg["chars"]
    stoi = {c: i for i, c in enumerate(chars)}
    m = GPT(len(chars), cfg["T"], cfg["d"], cfg["heads"], cfg["layers"])
    for k in m.params():
        m.params()[k].data[:] = w[k]
    return m, chars, stoi, cfg["T"]


def generate_batch(m, prefixes, T, end_id, pad_id):
    """Greedy-decode many transitions at once: one forward per char position
    over the whole batch (instead of one per transition). No KV cache -- each
    step recomputes, but batched it's fast enough."""
    B = len(prefixes)
    buf = np.full((B, T), pad_id, dtype=np.int64)
    cur = np.empty(B, np.int64)
    for i, p in enumerate(prefixes):
        buf[i, :len(p)] = p
        cur[i] = len(p)
    done = np.zeros(B, bool)
    outs = [[] for _ in range(B)]
    for _ in range(T):
        if done.all():
            break
        logits = m.forward(buf).data
        nxt = logits[np.arange(B), cur - 1].argmax(-1)
        for i in range(B):
            if done[i] or cur[i] >= T:
                done[i] = True
                continue
            if nxt[i] == end_id:
                done[i] = True
                continue
            buf[i, cur[i]] = nxt[i]
            outs[i].append(int(nxt[i]))
            cur[i] += 1
    return outs


def main():
    k = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    R = int(sys.argv[2]) if len(sys.argv) > 2 else 0   # 0 = allocentric full grid
    render = (lambda w: w.render_view(R)) if R else (lambda w: w.render_plain())
    m, chars, stoi, T = load_model()
    itos = {i: c for c, i in stoi.items()}
    end_id, pad_id = stoi[END], stoi[PAD]
    rng = random.Random(999)

    # collect held-out transitions from the oracle
    states, acts, truths, prefixes = [], [], [], []
    for mc in MAPS:
        try:
            w = World(mc)
        except Exception:
            continue
        for _ in range(k):
            state = render(w)
            a = rng.choice(list(DELTA))
            w.step(a)
            if w.m.const != mc:            # warp -> reset, skip (within-map eval)
                w = World(mc)
                continue
            truth = render(w)
            pre = [stoi.get(c) for c in state + "\n" + ACT[a] + "\n"]
            if any(c is None for c in pre):
                continue
            states.append(state); acts.append(a); truths.append(truth)
            prefixes.append(pre)

    def at_rc(s):                                  # (row,col) of '@', or None
        for r, line in enumerate(s.split("\n")):
            c = line.find("@")
            if c >= 0:
                return (r, c)
        return None

    gen = generate_batch(m, prefixes, T, end_id, pad_id)
    exact = n = cells_ok = cells_tot = 0
    cat = {"moved": [0, 0], "blocked": [0, 0]}     # [exact, total]
    atc = {"moved": [0, 0], "blocked": [0, 0]}     # [@-placed-right, total]
    sample = None
    for state, a, truth, g in zip(states, acts, truths, gen):
        pred = "".join(itos[i] for i in g)
        n += 1
        ok = pred == truth
        exact += ok
        key = "blocked" if state == truth else "moved"
        cat[key][0] += ok
        cat[key][1] += 1
        atc[key][0] += (at_rc(pred) == at_rc(truth))   # did @ land in the right cell
        atc[key][1] += 1
        for i in range(max(len(pred), len(truth))):
            cells_tot += 1
            cells_ok += (i < len(pred) and i < len(truth) and pred[i] == truth[i])
        if sample is None or (not ok and sample[3] == sample[2]):
            sample = (state, a, truth, pred)

    print("evaluated %d transitions vs the oracle:" % n)
    print("  exact-match (whole grid): %.1f%%" % (100 * exact / max(n, 1)))
    print("  per-cell accuracy:        %.1f%%" % (100 * cells_ok / max(cells_tot, 1)))
    print("  @-placement (THE RULE):")
    for kk, (e, t) in atc.items():
        if t:
            print("     %-8s %.1f%%  (%d)" % (kk, 100 * e / t, t))
    for kk, (e, t) in cat.items():
        if t:
            print("  %-8s exact: %.1f%%  (%d)" % (kk, 100 * e / t, t))
    if sample:
        s, a, tr, pr = sample
        print("\n--- example  (ACTION %s) ---" % a)
        sl, trl, prl = s.split("\n"), tr.split("\n"), pr.split("\n")
        print("   %-11s %-11s %-11s" % ("state", "truth", "model"))
        for i in range(max(len(sl), len(trl), len(prl))):
            print("   %-11s %-11s %-11s" % (sl[i] if i < len(sl) else "",
                  trl[i] if i < len(trl) else "", prl[i] if i < len(prl) else ""))


if __name__ == "__main__":
    main()
