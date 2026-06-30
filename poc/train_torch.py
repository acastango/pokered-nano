#!/usr/bin/env python3
"""
pokered-nano — PyTorch/CUDA trainer for the world model (the fast path).

Same task as train.py (predict next ASCII state from state+action) but on the
GPU, so we can use a real model + many steps + more maps. Reuses the stdlib
oracle (pokeworld) for both the corpus and in-loop scoring.

SETUP (needs a standard CPython + CUDA torch, NOT the MSYS python):
    # install Python 3.11 from python.org, then:
    py -3.11 -m pip install --upgrade pip
    py -3.11 -m pip install numpy
    py -3.11 -m pip install torch --index-url https://download.pytorch.org/whl/cu121

RUN:
    py -3.11 poc\\gen_data.py 1500 poc\\transitions_allo.jsonl 0   # (re)build corpus
    py -3.11 poc\\train_torch.py poc\\transitions_allo.jsonl 4000
"""

import os
import sys
import json
import random
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pokeworld import World, DELTA

HERE = os.path.dirname(os.path.abspath(__file__))
ACT = {"up": "^", "down": "v", "left": "<", "right": ">"}
END, PAD = "$", "\x00"
DEV = "cuda" if torch.cuda.is_available() else "cpu"


# --------------------------------------------------------------------------- data
def build(corpus, W=8.0, cap=320):
    rows = [json.loads(l) for l in open(corpus, encoding="utf-8")]
    rows = [r for r in rows                         # drop oversized grids (VRAM)
            if max(len(r["state"]), len(r["next"])) <= cap]
    maps = sorted({r["map"] for r in rows})        # eval on the same maps
    seqs = [r["state"] + "\n" + ACT[r["action"]] + "\n" + r["next"] + END
            for r in rows]
    starts = [len(r["state"]) + 3 for r in rows]
    chars = sorted(set("".join(seqs)) | {PAD})
    stoi = {c: i for i, c in enumerate(chars)}
    Tmax = max(len(s) for s in seqs)
    N = len(seqs)
    ids = np.full((N, Tmax), stoi[PAD], np.int64)
    Ls = np.empty(N, np.int64)
    for i, s in enumerate(seqs):
        ids[i, :len(s)] = [stoi[c] for c in s]
        Ls[i] = len(s)
    inp, tgt = ids[:, :-1], ids[:, 1:]
    at = stoi["@"]
    w = np.zeros_like(tgt, np.float32)
    for i in range(N):
        sg = starts[i] - 3
        for p in range(Tmax - 1):
            tp = p + 1
            if starts[i] <= tp < Ls[i]:
                j = tp - starts[i]
                c = ids[i, tp]
                w[i, p] = W if (c == at or (j < sg and ids[i, j] != c)) else 1.0
    return (torch.tensor(inp), torch.tensor(tgt), torch.tensor(w),
            chars, stoi, Tmax - 1, maps)


# --------------------------------------------------------------------------- model
class Block(nn.Module):
    def __init__(self, d, h):
        super().__init__()
        self.ln1, self.ln2 = nn.LayerNorm(d), nn.LayerNorm(d)
        self.attn = nn.MultiheadAttention(d, h, batch_first=True)
        self.mlp = nn.Sequential(nn.Linear(d, 4 * d), nn.GELU(), nn.Linear(4 * d, d))

    def forward(self, x, mask):
        h = self.ln1(x)
        a, _ = self.attn(h, h, h, attn_mask=mask, need_weights=False)
        x = x + a
        return x + self.mlp(self.ln2(x))


class GPT(nn.Module):
    def __init__(self, V, T, d=256, h=8, L=6):
        super().__init__()
        self.T = T
        self.tok = nn.Embedding(V, d)
        self.pos = nn.Embedding(T, d)
        self.blocks = nn.ModuleList(Block(d, h) for _ in range(L))
        self.lnf = nn.LayerNorm(d)
        self.head = nn.Linear(d, V)
        self.register_buffer("mask", torch.triu(torch.full((T, T), float("-inf")), 1))

    def forward(self, ids):
        T = ids.shape[1]
        x = self.tok(ids) + self.pos(torch.arange(T, device=ids.device))
        for b in self.blocks:
            x = b(x, self.mask[:T, :T])
        return self.head(self.lnf(x))


# --------------------------------------------------------------------------- eval
@torch.no_grad()
def oracle_set(maps, k, R, rng):
    states, acts, truths = [], [], []
    for mc in maps:
        w = World(mc)
        for _ in range(k):
            s = w.render_plain()
            a = rng.choice(list(DELTA))
            w.step(a)
            if w.m.const != mc:
                w = World(mc)
                continue
            states.append(s); acts.append(a); truths.append(w.render_plain())
    return states, acts, truths


@torch.no_grad()
def evaluate(model, states, acts, truths, stoi, T):
    itos = {i: c for c, i in stoi.items()}
    end_id, pad_id = stoi[END], stoi[PAD]
    B = len(states)
    buf = torch.full((B, T), pad_id, dtype=torch.long, device=DEV)
    cur = torch.empty(B, dtype=torch.long)
    for i in range(B):
        pre = [stoi[c] for c in states[i] + "\n" + ACT[acts[i]] + "\n"]
        buf[i, :len(pre)] = torch.tensor(pre, device=DEV)
        cur[i] = len(pre)
    done = [False] * B
    outs = [[] for _ in range(B)]
    for _ in range(T):
        if all(done):
            break
        logits = model(buf)
        nxt = logits[torch.arange(B), cur - 1].argmax(-1)
        for i in range(B):
            if done[i] or cur[i] >= T:
                done[i] = True
                continue
            c = int(nxt[i])
            if c == end_id:
                done[i] = True
                continue
            buf[i, cur[i]] = c
            outs[i].append(c)
            cur[i] += 1

    def at_rc(s):
        for r, ln in enumerate(s.split("\n")):
            c = ln.find("@")
            if c >= 0:
                return (r, c)

    ex = mv_ok = mv = bl_ok = bl = 0
    for i in range(B):
        pred = "".join(itos[x] for x in outs[i])
        ex += pred == truths[i]
        moved = states[i] != truths[i]
        ok = at_rc(pred) == at_rc(truths[i])
        if moved:
            mv += 1; mv_ok += ok
        else:
            bl += 1; bl_ok += ok
    return (100 * ex / B, 100 * mv_ok / max(mv, 1), 100 * bl_ok / max(bl, 1))


# --------------------------------------------------------------------------- train
def main():
    corpus = next((a for a in sys.argv[1:] if not a.startswith("-")),
                  os.path.join(HERE, "transitions_allo.jsonl"))
    steps = int(next((a for a in sys.argv[2:] if a.isdigit()), 4000))
    inp, tgt, w, chars, stoi, T, maps = build(corpus)
    V, N = len(chars), inp.shape[0]
    print(f"device={DEV} corpus={N} vocab={V} T={T} maps={maps}", flush=True)
    inp, tgt, w = inp.to(DEV), tgt.to(DEV), w.to(DEV)

    model = GPT(V, T).to(DEV)
    print("params: %.2fM" % (sum(p.numel() for p in model.parameters()) / 1e6))
    opt = torch.optim.AdamW(model.parameters(), lr=3e-4, weight_decay=0.01)
    # held-out eval: sample up to ~24 maps so the generation batch fits in VRAM
    es_maps = maps if len(maps) <= 24 else random.Random(7).sample(maps, 24)
    es = oracle_set(es_maps, 6, 0, random.Random(999))
    B = 128
    for step in range(1, steps + 1):
        bi = torch.randint(0, N, (B,), device=DEV)
        logits = model(inp[bi])
        loss = (F.cross_entropy(logits.reshape(-1, V), tgt[bi].reshape(-1),
                                reduction="none") * w[bi].reshape(-1)).sum() \
            / w[bi].sum()
        opt.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()
        if step % 200 == 0 or step == 1:
            ex, mvok, blok = evaluate(model, *es, stoi, T)
            print("step %5d  loss %.4f | exact %.0f%%  moved-@ %.0f%%  "
                  "blocked-@ %.0f%%" % (step, loss.item(), ex, mvok, blok),
                  flush=True)
    torch.save({"model": model.state_dict(), "chars": chars, "T": T},
               os.path.join(HERE, "model_torch.pt"))
    print("saved model_torch.pt")


if __name__ == "__main__":
    main()
