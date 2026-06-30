#!/usr/bin/env python3
"""Diagnostic: can the model memorize a tiny set? Trains on N transitions and
checks BOTH teacher-forced and free-running @-placement on those same ones.
If it can't overfit, the architecture/representation is too weak (not a scale
issue)."""
import os, sys, json, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import train as tr
from nn import Tensor

rows = [json.loads(l) for l in open(os.path.join(tr.HERE, "transitions_allo.jsonl"),
                                    encoding="utf-8")]
# 16 transitions that actually MOVE (the hard case)
rows = [r for r in rows if r["state"] != r["next"]][:16]
tmp = os.path.join(tr.HERE, "_overfit.jsonl")
open(tmp, "w").write("".join(json.dumps(r) + "\n" for r in rows))

inp, tgt, mask, chars, stoi, T = tr.load(tmp)
itos = {i: c for c, i in stoi.items()}
N, V = inp.shape[0], len(chars)
m = tr.GPT(V, T, d=64, heads=4, layers=2, rng=np.random.default_rng(0))
opt = tr.Adam(m.params(), lr=1.5e-3)
for s in range(1, 401):
    opt.zero()
    L = m.loss(inp, tgt, mask)
    L.backward(); tr.clip_grads(m.params(), 1.0); opt.step()
    if s % 80 == 0:
        print("step %d loss %.4f" % (s, L.data), flush=True)


def at_rc(s):
    for r, ln in enumerate(s.split("\n")):
        c = ln.find("@")
        if c >= 0:
            return (r, c)


# teacher-forced @ accuracy (argmax at each true position)
logits = m.forward(inp).data
tf_ok = 0
for i, r in enumerate(rows):
    pred_ids = logits[i].argmax(-1)
    # reconstruct predicted next chars at the masked positions
    seq = list(inp[i])
    nx = "".join(itos[int(pred_ids[p])] for p in range(T)
                 if mask[i, p] > 0)
    tf_ok += at_rc(nx) == at_rc(r["next"])
# free-running @ accuracy
end_id, pad_id = stoi[tr.END], stoi[tr.PAD]
fr_ok = 0
for i, r in enumerate(rows):
    prefix = [stoi[c] for c in r["state"] + "\n" + tr.ACT[r["action"]] + "\n"]
    buf = [pad_id] * T
    buf[:len(prefix)] = prefix
    cur = len(prefix); out = []
    while cur < T:
        lg = m.forward(np.array([buf], np.int64)).data
        nxt = int(lg[0, cur - 1].argmax())
        if nxt == end_id:
            break
        out.append(nxt); buf[cur] = nxt; cur += 1
    gen = "".join(itos[x] for x in out)
    fr_ok += at_rc(gen) == at_rc(r["next"])
print("OVERFIT 16 moved transitions:")
print("  teacher-forced @ correct: %d/16" % tf_ok)
print("  free-running   @ correct: %d/16" % fr_ok)
