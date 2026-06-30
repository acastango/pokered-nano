#!/usr/bin/env python3
"""
pokered-nano — DAgger / scheduled sampling to make the world model survive long
closed-loop rollouts.

The model only trained on the ORACLE's (true) states, so once a rollout drifts
off-trajectory it's in unseen territory and compounds errors. Here we roll the
CURRENT model out closed-loop, and for every state it actually visits (drift
included) we ask the real engine for the CORRECT next state, given the @ the
model drew. Those (visited-state, action) -> (correct-next) pairs teach the
model to recover. Append them to the corpus and retrain.

    <conda-python> poc\\dagger.py [base_corpus] [out_corpus] [rollouts] [steps]
"""

import os
import sys
import json
import random
import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from train_torch import GPT, ACT, END, PAD, DEV
from pokeworld import World, DELTA
from gen_data import small_maps

HERE = os.path.dirname(os.path.abspath(__file__))
ACTS = list(DELTA)


def load_model():
    ckpt = torch.load(os.path.join(HERE, "model_torch.pt"),
                      map_location=DEV, weights_only=False)
    chars, T = ckpt["chars"], ckpt["T"]
    stoi = {c: i for i, c in enumerate(chars)}
    model = GPT(len(chars), T).to(DEV)
    model.load_state_dict(ckpt["model"])
    model.eval()
    return model, stoi, {i: c for c, i in stoi.items()}, T


@torch.no_grad()
def batch_next(model, states, actions, stoi, itos, T):
    """Greedy next-state for a batch of (state, action), in parallel."""
    end_id, pad_id = stoi[END], stoi[PAD]
    B = len(states)
    buf = torch.full((B, T), pad_id, dtype=torch.long, device=DEV)
    cur = []
    for i, (s, a) in enumerate(zip(states, actions)):
        pre = [stoi.get(c, pad_id) for c in s + "\n" + ACT[a] + "\n"]
        pre = pre[:T]
        buf[i, :len(pre)] = torch.tensor(pre, device=DEV)
        cur.append(len(pre))
    cur = torch.tensor(cur)
    done = [False] * B
    out = [[] for _ in range(B)]
    for _ in range(T):
        if all(done):
            break
        nx = model(buf)[torch.arange(B), cur - 1].argmax(-1)
        for i in range(B):
            if done[i] or cur[i] >= T:
                done[i] = True
                continue
            c = int(nx[i])
            if c == end_id:
                done[i] = True
                continue
            buf[i, cur[i]] = c
            out[i].append(c)
            cur[i] += 1
    return ["".join(itos[x] for x in o) for o in out]


def at_rc(grid):
    for r, line in enumerate(grid.split("\n")):
        c = line.find("@")
        if c >= 0:
            return r, c
    return None


def fresh(mc, rng):
    """A valid start state: the map with @ on a random walkable cell."""
    w = World(mc)
    cells = [(x, y) for y in range(w.m.GH) for x in range(w.m.GW)
             if w.walkable(x, y) and (x, y) not in w.m.warp_at]
    if not cells:
        return None
    w.cx, w.cy = rng.choice(cells)
    return w


def main():
    base = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "transitions_multi.jsonl")
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "transitions_dagger.jsonl")
    B = int(sys.argv[3]) if len(sys.argv) > 3 else 96      # parallel rollouts
    K = int(sys.argv[4]) if len(sys.argv) > 4 else 40      # steps per rollout
    rng = random.Random(2024)
    model, stoi, itos, T = load_model()
    maps = small_maps()

    # init B rollouts on random maps / random valid start cells
    worlds = []
    while len(worlds) < B:
        w = fresh(rng.choice(maps), rng)
        if w is not None:
            worlds.append(w)
    states = [w.render_plain() for w in worlds]
    mapc = [w.m.const for w in worlds]

    records, kept, skipped = [], 0, 0
    for step in range(K):
        actions = [rng.choice(ACTS) for _ in range(B)]
        preds = batch_next(model, states, actions, stoi, itos, T)
        for i in range(B):
            rc = at_rc(states[i])
            w = World(mapc[i])
            labeled = False
            if (rc is not None and 0 <= rc[1] < w.m.GW and 0 <= rc[0] < w.m.GH
                    and w.walkable(rc[1], rc[0])):
                w.cx, w.cy = rc[1], rc[0]
                try:
                    w.step(actions[i])
                    if w.m.const == mapc[i]:      # stayed in-map -> label it
                        records.append({"map": mapc[i], "action": actions[i],
                                        "state": states[i], "next": w.render_plain()})
                        kept += 1
                        states[i] = preds[i]      # closed loop: feed model's output
                        labeled = True
                except Exception:                 # warp into a broken map etc.
                    pass
            if not labeled:                       # invalid/warp/error -> re-anchor
                skipped += 1
                nw = fresh(rng.choice(maps), rng)
                worlds[i], mapc[i], states[i] = nw, nw.m.const, nw.render_plain()
        if (step + 1) % 10 == 0:
            print("step %d  dagger records: %d (skipped %d)"
                  % (step + 1, kept, skipped), flush=True)

    # write base + dagger
    n = 0
    with open(out, "w", encoding="utf-8") as f:
        for path in (base,):
            for l in open(path, encoding="utf-8"):
                f.write(l)
                n += 1
        for r in records:
            f.write(json.dumps(r) + "\n")
            n += 1
    print("wrote %d transitions (%d base + %d dagger) -> %s"
          % (n, n - kept, kept, out))


if __name__ == "__main__":
    main()
