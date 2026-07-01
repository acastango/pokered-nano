#!/usr/bin/env python3
"""
The meta one: train a tiny GPT to PREDICT the game's text, and read off its
bits/char -- which IS the compressed size (entropy-code each char against the
model's next-char distribution). Same paradigm as the world model: a net that
predicts the game compresses the game.

    <conda-python> poc/text_lm.py
"""
import os, sys, glob, re, math
import torch
import torch.nn.functional as F

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from train_torch import GPT, DEV

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pokered-master")
pat = re.compile(r'\b(?:text|line|cont|para|next|page|prompt)\s+"([^"]*)"')
strings = []
for f in sorted(glob.glob(ROOT + "/text/**/*.asm", recursive=True)):
    strings += pat.findall(open(f, encoding="utf-8", errors="replace").read())
corpus = "\n".join(strings)
chars = sorted(set(corpus))
stoi = {c: i for i, c in enumerate(chars)}
V = len(chars)
data = [stoi[c] for c in corpus]
N = len(data)
split = int(0.9 * N)
train, held = data[:split], data[split:]
T = 128
raw_kb = len(corpus.encode("utf-8", "replace")) / 1024.0
lzma_bpc = 35.4 * 1024 * 8 / N
print("corpus %d chars (%.1f KB), vocab %d | lzma = %.2f bits/char" % (N, raw_kb, V, lzma_bpc))


def get_batch(seq, B):
    ix = torch.randint(0, len(seq) - T - 1, (B,))
    x = torch.stack([torch.tensor(seq[i:i + T]) for i in ix]).to(DEV)
    y = torch.stack([torch.tensor(seq[i + 1:i + T + 1]) for i in ix]).to(DEV)
    return x, y


@torch.no_grad()
def bits_per_char(seq):
    model.eval()
    tot, cnt = 0.0, 0
    for i in range(0, len(seq) - T - 1, T):
        x = torch.tensor([seq[i:i + T]]).to(DEV)
        y = torch.tensor([seq[i + 1:i + T + 1]]).to(DEV)
        loss = F.cross_entropy(model(x).reshape(-1, V), y.reshape(-1))
        tot += loss.item(); cnt += 1
    model.train()
    return (tot / cnt) / math.log(2)


model = GPT(V, T, d=192, h=6, L=4).to(DEV)
params = sum(p.numel() for p in model.parameters())
print("model: %.2fM params (~%.0f KB fp16)\n" % (params / 1e6, params * 2 / 1024))
opt = torch.optim.AdamW(model.parameters(), lr=3e-4, weight_decay=0.01)
for step in range(1, 4001):
    x, y = get_batch(train, 48)
    loss = F.cross_entropy(model(x).reshape(-1, V), y.reshape(-1))
    opt.zero_grad(); loss.backward()
    torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
    opt.step()
    if step % 500 == 0:
        tr, hd = bits_per_char(train), bits_per_char(held)
        print("step %4d  train %.2f bpc (%.1f KB)  held-out %.2f bpc (%.1f KB)"
              % (step, tr, tr * N / 8 / 1024, hd, hd * N / 8 / 1024))

tr, hd = bits_per_char(train), bits_per_char(held)
print("\n=== final ===")
print("lzma            : 3.04 bits/char -> 35.4 KB")
print("model TRAIN     : %.2f bits/char -> %.1f KB  (what it compresses seen text to)" % (tr, tr * N / 8 / 1024))
print("model HELD-OUT  : %.2f bits/char -> %.1f KB  (generalization to unseen text)" % (hd, hd * N / 8 / 1024))
print("model cost      : ~%.0f KB params (the honest caveat at this corpus size)" % (params * 2 / 1024))
