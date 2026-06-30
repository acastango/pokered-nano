#!/usr/bin/env python3
"""
pokered-nano — a tiny reverse-mode autograd over NumPy (no deps but numpy).

Just enough to build a char-level decoder-only transformer from first
principles: every op records a local backward, Tensor.backward() walks the
graph in reverse. float64 throughout (small model; lets us gradient-check).
"""

import numpy as np

DT = np.float32        # backprop verified in float64 (gradcheck); float32 ~2x faster


def _unbroadcast(g, shape):
    """Sum a gradient back to `shape` (reverse of NumPy broadcasting)."""
    while g.ndim > len(shape):
        g = g.sum(axis=0)
    for i, s in enumerate(shape):
        if s == 1 and g.shape[i] != 1:
            g = g.sum(axis=i, keepdims=True)
    return g


class Tensor:
    def __init__(self, data, parents=()):
        self.data = np.asarray(data, dtype=DT)
        self.grad = np.zeros_like(self.data)
        self._parents = parents
        self._backward = lambda: None

    # --- elementwise ---
    def __add__(self, other):
        other = other if isinstance(other, Tensor) else Tensor(other)
        out = Tensor(self.data + other.data, (self, other))

        def bw():
            self.grad += _unbroadcast(out.grad, self.data.shape)
            other.grad += _unbroadcast(out.grad, other.data.shape)
        out._backward = bw
        return out

    def __mul__(self, other):
        other = other if isinstance(other, Tensor) else Tensor(other)
        out = Tensor(self.data * other.data, (self, other))

        def bw():
            self.grad += _unbroadcast(out.grad * other.data, self.data.shape)
            other.grad += _unbroadcast(out.grad * self.data, other.data.shape)
        out._backward = bw
        return out

    def __matmul__(self, other):
        out = Tensor(self.data @ other.data, (self, other))

        def bw():
            a, b = self.data, other.data
            self.grad += _unbroadcast(out.grad @ np.swapaxes(b, -1, -2), a.shape)
            other.grad += _unbroadcast(np.swapaxes(a, -1, -2) @ out.grad, b.shape)
        out._backward = bw
        return out

    def relu(self):
        out = Tensor(np.maximum(self.data, 0), (self,))

        def bw():
            self.grad += out.grad * (self.data > 0)
        out._backward = bw
        return out

    # --- shape ---
    def reshape(self, *shape):
        out = Tensor(self.data.reshape(*shape), (self,))

        def bw():
            self.grad += out.grad.reshape(self.data.shape)
        out._backward = bw
        return out

    def transpose(self, *axes):
        out = Tensor(np.transpose(self.data, axes), (self,))
        inv = np.argsort(axes)

        def bw():
            self.grad += np.transpose(out.grad, inv)
        out._backward = bw
        return out

    def backward(self):
        topo, seen = [], set()

        def build(t):
            if id(t) not in seen:
                seen.add(id(t))
                for p in t._parents:
                    build(p)
                topo.append(t)
        build(self)
        self.grad = np.ones_like(self.data)
        for t in reversed(topo):
            t._backward()


# --- fused ops (cleaner forward, hand-written backward) --------------------

def add_mask(scores, mask):
    """scores (..,T,T) + constant causal mask (T,T) of 0/-inf (no grad)."""
    out = Tensor(scores.data + mask, (scores,))

    def bw():
        scores.grad += out.grad
    out._backward = bw
    return out


def softmax(x):
    """softmax over the last axis."""
    e = np.exp(x.data - x.data.max(axis=-1, keepdims=True))
    s = e / e.sum(axis=-1, keepdims=True)
    out = Tensor(s, (x,))

    def bw():
        g = out.grad
        x.grad += s * (g - (g * s).sum(axis=-1, keepdims=True))
    out._backward = bw
    return out


def layernorm(x, gamma, beta, eps=1e-5):
    """LayerNorm over the last axis."""
    mu = x.data.mean(axis=-1, keepdims=True)
    var = x.data.var(axis=-1, keepdims=True)
    inv = 1.0 / np.sqrt(var + eps)
    xhat = (x.data - mu) * inv
    out = Tensor(xhat * gamma.data + beta.data, (x, gamma, beta))
    D = x.data.shape[-1]

    def bw():
        g = out.grad
        gamma.grad += _unbroadcast(g * xhat, gamma.data.shape)
        beta.grad += _unbroadcast(g, beta.data.shape)
        dxhat = g * gamma.data
        x.grad += inv * (dxhat - dxhat.mean(-1, keepdims=True)
                         - xhat * (dxhat * xhat).mean(-1, keepdims=True))
    out._backward = bw
    return out


def embedding(idx, table):
    """Gather rows table[idx]; idx is a plain int array (no grad)."""
    out = Tensor(table.data[idx], (table,))

    def bw():
        np.add.at(table.grad, idx, out.grad)
    out._backward = bw
    return out


def cross_entropy(logits, targets, mask):
    """Mean masked CE. logits (N,V), targets (N,) int, mask (N,) 0/1 -> scalar."""
    z = logits.data - logits.data.max(axis=-1, keepdims=True)
    e = np.exp(z)
    p = e / e.sum(axis=-1, keepdims=True)
    n = max(mask.sum(), 1.0)
    logp = np.log(p[np.arange(len(targets)), targets] + 1e-12)
    loss = -(logp * mask).sum() / n
    out = Tensor(loss, (logits,))

    def bw():
        d = p.copy()
        d[np.arange(len(targets)), targets] -= 1.0
        d *= (mask / n)[:, None]
        logits.grad += d * out.grad
    out._backward = bw
    return out
