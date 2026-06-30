#!/usr/bin/env python3
"""
pokered-nano — CLOSED-LOOP rollout: let the learned model BE the engine.

The model predicts the next state, then THAT prediction is fed back as its own
next input (no oracle in the loop). The real engine (pokeworld) runs the same
actions in parallel only to score drift: do the model's self-generated states
stay equal to the true game over a whole trajectory?

    <conda-python> poc\\rollout.py [MAP_CONST] [steps]
"""

import os
import sys
import random
import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from train_torch import GPT, ACT, END, PAD, DEV
from pokeworld import World, DELTA

HERE = os.path.dirname(os.path.abspath(__file__))


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
def predict(model, state, action, stoi, itos, T):
    """Greedy next-state from (state, action) — the model alone."""
    end_id, pad_id = stoi[END], stoi[PAD]
    pre = [stoi[c] for c in state + "\n" + ACT[action] + "\n"]
    buf = torch.full((1, T), pad_id, dtype=torch.long, device=DEV)
    buf[0, :len(pre)] = torch.tensor(pre, device=DEV)
    cur, out = len(pre), []
    while cur < T:
        nxt = int(model(buf)[0, cur - 1].argmax())
        if nxt == end_id:
            break
        out.append(nxt)
        buf[0, cur] = nxt
        cur += 1
    return "".join(itos[i] for i in out)


def main():
    map_const = next((a for a in sys.argv[1:] if not a.isdigit()), "OAKS_LAB")
    steps = int(next((a for a in sys.argv[1:] if a.isdigit()), 100))
    model, stoi, itos, T = load_model()
    rng = random.Random(7)

    w = World(map_const)                 # oracle (ground truth)
    w.spawn_main()                       # start in the largest walkable region
    sim = w.render_plain()               # the model's state (starts true)
    print("CLOSED-LOOP: model runs on its OWN output; engine tracks for scoring")
    print("map:", map_const, " steps:", steps)
    oks, first_div, first_div_frames = [], None, None
    for t in range(1, steps + 1):
        a = rng.choice(list(DELTA))
        before = sim
        sim = predict(model, sim, a, stoi, itos, T)   # <-- model feeds itself
        w.step(a)
        if w.m.const != map_const:
            print("(engine left the map at step %d; stopping)" % t)
            break
        truth = w.render_plain()
        ok = sim == truth
        oks.append(ok)
        if not ok and first_div is None:
            first_div, first_div_frames = t, (before, a, sim, truth)
    # metrics
    longest = cur = 0
    for ok in oks:
        cur = cur + 1 if ok else 0
        longest = max(longest, cur)
    timeline = "".join("." if ok else "X" for ok in oks)
    print("\ntimeline (.=match X=drift):\n" + timeline)
    print("\ntotal agreement: %d/%d (%.0f%%)  longest faithful run: %d  "
          "first drift: %s" % (sum(oks), len(oks), 100 * sum(oks) / max(len(oks), 1),
                               longest, first_div or "none"))
    if first_div_frames:
        b, a, s, tr = first_div_frames
        print("\nfirst drift (step %d, action %s) — model vs truth:" % (first_div, a))
        for ml, tl in zip(s.split("\n"), tr.split("\n")):
            print("   %-12s %s %-12s" % (ml, "*" if ml != tl else " ", tl))


if __name__ == "__main__":
    main()
