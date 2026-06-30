#!/usr/bin/env python3
"""
pokered-nano — train a tiny char-level transformer to BE the engine.

Reads a transitions corpus (gen_data.py), formats each as

    <state grid>\n<action ^v<>>\n<next grid>$

and trains a decoder-only transformer (built on nn.py autograd) to predict the
<next grid> from the (state, action) prefix. Loss is masked to the next-grid
chars only. The model literally becomes the transition function.

    python train.py [corpus.jsonl] [steps]      (default transitions_view.jsonl)
    python train.py --gradcheck                 (verify backprop numerically)

Saves model.npz + model.json (vocab/config) for eval.py / sampling.
"""

import os
import sys
import json
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nn
from nn import Tensor

HERE = os.path.dirname(os.path.abspath(__file__))
ACT = {"up": "^", "down": "v", "left": "<", "right": ">"}
END = "$"
PAD = "\x00"


# --------------------------------------------------------------------------- model
class GPT:
    def __init__(self, V, T, d=64, heads=4, layers=2, rng=None):
        rng = rng or np.random.default_rng(0)
        self.V, self.T, self.d, self.h, self.L = V, T, d, heads, layers
        self.dh = d // heads
        self.p = {}

        def par(name, shape, scale):
            self.p[name] = Tensor(rng.standard_normal(shape) * scale)

        par("tok", (V, d), 0.02)
        par("pos", (T, d), 0.02)
        for i in range(layers):
            par(f"ln1g{i}", (d,), 0.0); self.p[f"ln1g{i}"].data[:] = 1.0
            par(f"ln1b{i}", (d,), 0.0)
            for w in "qkv":
                par(f"W{w}{i}", (d, d), 0.02)
                par(f"b{w}{i}", (d,), 0.0)
            par(f"Wo{i}", (d, d), 0.02); par(f"bo{i}", (d,), 0.0)
            par(f"ln2g{i}", (d,), 0.0); self.p[f"ln2g{i}"].data[:] = 1.0
            par(f"ln2b{i}", (d,), 0.0)
            par(f"W1{i}", (d, 4 * d), 0.02); par(f"b1{i}", (4 * d,), 0.0)
            par(f"W2{i}", (4 * d, d), 0.02); par(f"b2{i}", (d,), 0.0)
        par("lnfg", (d,), 0.0); self.p["lnfg"].data[:] = 1.0
        par("lnfb", (d,), 0.0)
        par("head", (d, V), 0.02); par("bhead", (V,), 0.0)
        cm = np.triu(np.full((T, T), -1e9), 1)        # causal mask (0 / -inf)
        self.mask = cm

    def params(self):
        return self.p

    def forward(self, ids):                            # ids: (B,T) int
        B, T = ids.shape
        p = self.p
        x = nn.embedding(ids, p["tok"]) + p["pos"]     # (B,T,d)
        for i in range(self.L):
            h = nn.layernorm(x, p[f"ln1g{i}"], p[f"ln1b{i}"])

            def proj(w):
                y = h @ p[f"W{w}{i}"] + p[f"b{w}{i}"]
                return y.reshape(B, T, self.h, self.dh).transpose(0, 2, 1, 3)
            q, k, v = proj("q"), proj("k"), proj("v")
            scores = (q @ k.transpose(0, 1, 3, 2)) * (1.0 / np.sqrt(self.dh))
            attn = nn.softmax(nn.add_mask(scores, self.mask))
            ctx = (attn @ v).transpose(0, 2, 1, 3).reshape(B, T, self.d)
            x = x + (ctx @ p[f"Wo{i}"] + p[f"bo{i}"])
            h2 = nn.layernorm(x, p[f"ln2g{i}"], p[f"ln2b{i}"])
            m = (h2 @ p[f"W1{i}"] + p[f"b1{i}"]).relu() @ p[f"W2{i}"] + p[f"b2{i}"]
            x = x + m
        x = nn.layernorm(x, p["lnfg"], p["lnfb"])
        return x @ p["head"] + p["bhead"]              # (B,T,V)

    def loss(self, ids, tgt, mask):
        B, T = ids.shape
        logits = self.forward(ids)
        return nn.cross_entropy(logits.reshape(B * T, self.V),
                                tgt.reshape(-1), mask.reshape(-1).astype(float))


# --------------------------------------------------------------------------- data
def load(corpus):
    rows = [json.loads(l) for l in open(corpus, encoding="utf-8")]
    seqs = [r["state"] + "\n" + ACT[r["action"]] + "\n" + r["next"] + END
            for r in rows]
    starts = [len(r["state"]) + 3 for r in rows]       # where <next> begins
    chars = sorted(set("".join(seqs)) | {PAD})
    stoi = {c: i for i, c in enumerate(chars)}
    Tmax = max(len(s) for s in seqs)
    N = len(seqs)
    ids = np.full((N, Tmax), stoi[PAD], np.int64)
    Ls = np.zeros(N, np.int64)
    for i, s in enumerate(seqs):
        ids[i, :len(s)] = [stoi[c] for c in s]
        Ls[i] = len(s)
    inp, tgt = ids[:, :-1], ids[:, 1:]
    # weighted loss: the next-grid is ~all copy except the 1-2 cells the action
    # changes (the @ source/dest). Those (and the @) are the actual rule, but
    # they're a tiny fraction of chars -> upweight them so the model learns the
    # dynamics instead of just copying. (W=1 -> plain next-token loss.)
    W = 8.0
    at = stoi["@"]
    mask = np.zeros_like(tgt, np.float64)
    for i in range(N):
        sg = starts[i] - 3                       # length of the state grid
        for p in range(Tmax - 1):
            tpos = p + 1
            if not (starts[i] <= tpos < Ls[i]):
                continue
            j = tpos - starts[i]                 # index within the next grid
            c = ids[i, tpos]
            mask[i, p] = W if (c == at or (j < sg and ids[i, j] != c)) else 1.0
    return inp, tgt, mask, chars, stoi, Tmax - 1


# --------------------------------------------------------------------------- adam
class Adam:
    def __init__(self, params, lr=3e-3, b1=0.9, b2=0.999, eps=1e-8):
        self.params, self.lr, self.b1, self.b2, self.eps = params, lr, b1, b2, eps
        self.m = {k: np.zeros_like(p.data) for k, p in params.items()}
        self.v = {k: np.zeros_like(p.data) for k, p in params.items()}
        self.t = 0

    def step(self):
        self.t += 1
        for k, p in self.params.items():
            g = p.grad
            self.m[k] = self.b1 * self.m[k] + (1 - self.b1) * g
            self.v[k] = self.b2 * self.v[k] + (1 - self.b2) * g * g
            mh = self.m[k] / (1 - self.b1 ** self.t)
            vh = self.v[k] / (1 - self.b2 ** self.t)
            p.data -= self.lr * mh / (np.sqrt(vh) + self.eps)

    def zero(self):
        for p in self.params.values():
            p.grad[:] = 0


def clip_grads(params, maxnorm=1.0):
    """Global-norm gradient clipping (the runs were diverging without it)."""
    total = np.sqrt(sum(float((p.grad ** 2).sum()) for p in params.values()))
    if total > maxnorm:
        s = maxnorm / (total + 1e-12)
        for p in params.values():
            p.grad *= s
    return total


# --------------------------------------------------------------------------- gradcheck
def gradcheck():
    rng = np.random.default_rng(1)
    V, T, B = 7, 9, 2
    g = GPT(V, T, d=16, heads=2, layers=2, rng=rng)
    ids = rng.integers(0, V, (B, T))
    tgt = rng.integers(0, V, (B, T))
    mask = (rng.random((B, T)) > 0.4).astype(float)
    L = g.loss(ids, tgt, mask)
    for p in g.params().values():
        p.grad[:] = 0
    L.backward()
    worst = 0.0
    for name in ["tok", "Wq0", "ln1g0", "W11", "head", "pos"]:
        P = g.params()[name]
        idx = tuple(rng.integers(0, s) for s in P.data.shape)
        ana = P.grad[idx]
        eps = 1e-5
        P.data[idx] += eps
        lp = g.loss(ids, tgt, mask).data
        P.data[idx] -= 2 * eps
        lm = g.loss(ids, tgt, mask).data
        P.data[idx] += eps
        num = (lp - lm) / (2 * eps)
        err = abs(ana - num) / (abs(ana) + abs(num) + 1e-12)
        worst = max(worst, err)
        print(f"  {name:7s} analytic={ana:+.6f} numeric={num:+.6f} relerr={err:.2e}")
    tol = 1e-2 if nn.DT == np.float32 else 1e-4    # float32 finite-diff is noisy
    print("gradcheck %s (worst relerr %.2e)" % ("OK" if worst < tol else "FAIL", worst))


# --------------------------------------------------------------------------- train
def save(model, chars, T):
    np.savez(os.path.join(HERE, "model.npz"),
             **{k: p.data for k, p in model.params().items()})
    json.dump({"chars": chars, "T": T, "d": model.d, "heads": model.h,
               "layers": model.L, "act": ACT},
              open(os.path.join(HERE, "model.json"), "w"))


def main():
    if "--gradcheck" in sys.argv:
        gradcheck()
        return
    corpus = next((a for a in sys.argv[1:] if not a.startswith("-")),
                  os.path.join(HERE, "transitions_view.jsonl"))
    steps = int(next((a for a in sys.argv[2:] if a.isdigit()), 400))

    inp, tgt, mask, chars, stoi, T = load(corpus)
    N, V = inp.shape[0], len(chars)
    print("corpus %s: %d transitions, vocab=%d, T=%d" % (corpus, N, V, T))
    rng = np.random.default_rng(0)
    model = GPT(V, T, d=64, heads=4, layers=2, rng=rng)
    if "--resume" in sys.argv and os.path.exists(os.path.join(HERE, "model.npz")):
        w = np.load(os.path.join(HERE, "model.npz"))
        for kk in model.params():
            model.params()[kk].data[:] = w[kk]
        print("resumed from model.npz", flush=True)
    opt = Adam(model.params(), lr=1.5e-3)
    B = 16
    for step in range(1, steps + 1):
        bi = rng.integers(0, N, B)
        opt.zero()
        L = model.loss(inp[bi], tgt[bi], mask[bi])
        L.backward()
        clip_grads(model.params(), 1.0)
        opt.step()
        if step % 20 == 0 or step == 1:
            # token accuracy on the masked (next-grid) positions of this batch
            pred = model.forward(inp[bi]).data.argmax(-1)
            mb = mask[bi].astype(bool)
            acc = (pred[mb] == tgt[bi][mb]).mean()
            print("step %4d  loss %.4f  next-token acc %.3f"
                  % (step, L.data, acc), flush=True)
        if step % 100 == 0:                # checkpoint (survives timeouts)
            save(model, chars, T)
    save(model, chars, T)
    print("saved model.npz + model.json")


if __name__ == "__main__":
    main()
