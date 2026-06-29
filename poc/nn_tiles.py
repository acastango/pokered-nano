#!/usr/bin/env python3
"""
pokered-nano wildcard experiment: learned-latent tile codec.

Auto-decoder (DeepSDF-style): no encoder. Jointly optimize
  - one latent vector z (L floats) per UNIQUE tile, and
  - a single shared decoder MLP  z -> 64 pixels, each a 4-way (0..3) class.

After training:
  - argmax reconstruction -> per-tile exactness + per-pixel accuracy
  - residual stream of sparse pixel corrections makes it lossless
  - measured compressed size = lzma(weights) + lzma(latents) + lzma(residuals)
    compared against the lzma floor on the same raw 2bpp tile art.

Stdlib + numpy only. Reuses the POC's PNG decoder / tile slicer.
"""

import os, sys, lzma, struct, argparse, time
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from roundtrip import decode_png_2bpp_gray, extract_tiles

TILESET_DIR = "pokered-master/gfx/tilesets"


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #
def load_unique_tiles():
    """Return (uniq_tiles[N,64] uint8, instance_count N) deduped across all 19."""
    pngs = sorted(f for f in os.listdir(TILESET_DIR) if f.endswith(".png"))
    order = {}          # tile-tuple -> unique index, preserves first-seen order
    uniq = []
    n_inst = 0
    for f in pngs:
        w, h, px = decode_png_2bpp_gray(os.path.join(TILESET_DIR, f))
        tiles, _, _ = extract_tiles(w, h, px)
        for t in tiles:
            n_inst += 1
            if t not in order:
                order[t] = len(uniq)
                uniq.append(t)
    X = np.array(uniq, dtype=np.uint8)          # (N,64) values 0..3
    return X, n_inst


def lzma_len(b):
    return len(lzma.compress(b, preset=9 | lzma.PRESET_EXTREME))


def raw_floor(X):
    """Pack unique tiles back to 2bpp bytes (16 B/tile) and lzma them."""
    N = X.shape[0]
    packed = bytearray()
    for t in X:
        for r in range(8):
            for cb in range(2):              # 4 pixels per byte, 2 bytes per row
                byte = 0
                for c in range(4):
                    byte = (byte << 2) | int(t[r * 8 + cb * 4 + c])
                packed.append(byte)
    raw = bytes(packed)
    return N * 16, lzma_len(raw)


# --------------------------------------------------------------------------- #
# Model: z(L) -> tanh(z@W1+b1) -> logits(z@W2+b2) reshaped (.,64,4)
# --------------------------------------------------------------------------- #
def init_params(N, L, H, seed=0):
    rng = np.random.default_rng(seed)
    p = {
        "Z":  rng.normal(0, 0.1, (N, L)),
        "W1": rng.normal(0, 1/np.sqrt(L), (L, H)),
        "b1": np.zeros(H),
        "W2": rng.normal(0, 1/np.sqrt(H), (H, 256)),
        "b2": np.zeros(256),
    }
    return p


def forward(p):
    z = p["Z"]
    a = np.tanh(z @ p["W1"] + p["b1"])            # (N,H)
    logits = a @ p["W2"] + p["b2"]                # (N,256)
    return a, logits


def softmax_ce(logits, Y):
    """logits (N,256) -> per-pixel softmax CE vs Y (N,64) int. Returns loss, dlogits."""
    N = logits.shape[0]
    lo = logits.reshape(N, 64, 4)
    lo = lo - lo.max(axis=2, keepdims=True)
    e = np.exp(lo)
    sm = e / e.sum(axis=2, keepdims=True)         # (N,64,4)
    # gather true-class prob
    idx0 = np.arange(N)[:, None]
    idx1 = np.arange(64)[None, :]
    p_true = sm[idx0, idx1, Y]                     # (N,64)
    loss = -np.log(p_true + 1e-12).mean()
    d = sm.copy()
    d[idx0, idx1, Y] -= 1.0
    d /= (N * 64)
    return loss, d.reshape(N, 256)


def accuracy(logits, Y):
    pred = logits.reshape(-1, 64, 4).argmax(axis=2)
    px = (pred == Y).mean()
    perfect = (pred == Y).all(axis=1).mean()
    return px, perfect, pred


def train(p, Y, iters, lr, wd, log_every=200):
    keys = ["Z", "W1", "b1", "W2", "b2"]
    m = {k: np.zeros_like(p[k]) for k in keys}
    v = {k: np.zeros_like(p[k]) for k in keys}
    b1d, b2d, eps = 0.9, 0.999, 1e-8
    N = Y.shape[0]
    t0 = time.time()
    for it in range(1, iters + 1):
        a, logits = forward(p)
        loss, dlogits = softmax_ce(logits, Y)
        # backprop
        g = {}
        g["W2"] = a.T @ dlogits + wd * p["W2"]
        g["b2"] = dlogits.sum(0)
        da = dlogits @ p["W2"].T
        dz_pre = da * (1 - a * a)                  # tanh'
        g["W1"] = p["Z"].T @ dz_pre + wd * p["W1"]
        g["b1"] = dz_pre.sum(0)
        g["Z"] = dz_pre @ p["W1"].T + wd * p["Z"]
        # adam
        for k in keys:
            m[k] = b1d * m[k] + (1 - b1d) * g[k]
            v[k] = b2d * v[k] + (1 - b2d) * (g[k] * g[k])
            mh = m[k] / (1 - b1d ** it)
            vh = v[k] / (1 - b2d ** it)
            p[k] -= lr * mh / (np.sqrt(vh) + eps)
        if it % log_every == 0 or it == 1:
            px, perfect, _ = accuracy(logits, Y)
            print(f"  it {it:5d}  loss {loss:.4f}  pixel-acc {px*100:5.2f}%  "
                  f"perfect-tiles {perfect*100:5.2f}%  ({time.time()-t0:4.1f}s)")
    return p


# --------------------------------------------------------------------------- #
# Quantize + size accounting
# --------------------------------------------------------------------------- #
def quant_int8(arr):
    """Per-tensor symmetric int8. Returns (int8 bytes, scale float32 bytes)."""
    amax = np.abs(arr).max()
    scale = (amax / 127.0) if amax > 0 else 1.0
    q = np.clip(np.round(arr / scale), -127, 127).astype(np.int8)
    return q.tobytes(), struct.pack("<f", scale), q, scale


def dequant_int8(q, scale, shape):
    return (q.astype(np.float64) * scale).reshape(shape)


def build_residuals(pred, Y):
    """Sparse corrections for every mismatched pixel.
    Stream: for each tile with errors -> varint(tile_idx_delta), count, then
    (pixel_idx byte, true_val byte) pairs. We just dump three flat arrays and
    let lzma handle it; report the lzma size."""
    mism = np.argwhere(pred != Y)                 # (M,2): tile, pixel
    if mism.size == 0:
        return b"", 0
    tiles = mism[:, 0].astype(np.uint16)
    pix = mism[:, 1].astype(np.uint8)
    vals = Y[mism[:, 0], mism[:, 1]].astype(np.uint8)
    blob = tiles.tobytes() + pix.tobytes() + vals.tobytes()
    return blob, mism.shape[0]


def run(L, H, iters, lr, wd, seed):
    X, n_inst = load_unique_tiles()
    Y = X.astype(np.int64)
    N = X.shape[0]
    raw_bytes, floor = raw_floor(X)
    print(f"unique tiles N={N}  (instances={n_inst})")
    print(f"raw dedup art   {raw_bytes:7d} B  ({raw_bytes/1024:.1f} KB)")
    print(f"lzma floor art  {floor:7d} B  ({floor/1024:.1f} KB)   <-- target to beat")
    print(f"\nconfig  L={L}  H={H}  iters={iters}  lr={lr}  wd={wd}")

    p = init_params(N, L, H, seed)
    p = train(p, Y, iters, lr, wd)

    _, logits = forward(p)
    px, perfect, pred = accuracy(logits, Y)
    print(f"\nfinal  pixel-acc {px*100:.3f}%  perfect-tiles {perfect*100:.2f}%")

    # ---- size accounting (float weights/latents quantized to int8 + lzma) ----
    wbytes = b""
    sbytes = b""
    for k in ["W1", "b1", "W2", "b2"]:
        qb, sc, _, _ = quant_int8(p[k])
        wbytes += qb
        sbytes += sc
    zqb, zsc, _, _ = quant_int8(p["Z"])

    # recompute prediction from the QUANTIZED params -> honest lossy recon
    def dq(k):
        _, _, q, sc = quant_int8(p[k])
        return q.astype(np.float64) * sc
    pq = {k: dq(k) for k in ["Z", "W1", "b1", "W2", "b2"]}
    _, logits_q = forward(pq)
    pxq, perfq, predq = accuracy(logits_q, Y)
    print(f"int8   pixel-acc {pxq*100:.3f}%  perfect-tiles {perfq*100:.2f}%")

    w_lz = lzma_len(wbytes + sbytes)
    z_lz = lzma_len(zqb + zsc)
    res_blob, nres = build_residuals(predq, Y)
    r_lz = lzma_len(res_blob) if res_blob else 0
    total = w_lz + z_lz + r_lz

    print(f"\n--- compressed size (lossless via residuals) ---")
    print(f"weights (int8+lzma)   {w_lz:7d} B")
    print(f"latents (int8+lzma)   {z_lz:7d} B   ({z_lz/N:.2f} B/tile, L={L})")
    print(f"residuals lzma        {r_lz:7d} B   ({nres} pixel corrections, "
          f"{100*nres/(N*64):.2f}% of pixels)")
    print(f"TOTAL                 {total:7d} B  ({total/1024:.2f} KB)")
    print(f"vs lzma floor         {floor:7d} B  -> ratio {total/floor:.2f}x "
          f"({'BEATS floor' if total < floor else 'loses to floor'})")
    print(f"vs raw dedup art      {raw_bytes:7d} B  -> ratio {total/raw_bytes:.2f}x")
    return dict(L=L, H=H, total=total, floor=floor, raw=raw_bytes,
                perfect=perfq, px=pxq, w=w_lz, z=z_lz, r=r_lz, nres=nres)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--L", type=int, default=8)
    ap.add_argument("--H", type=int, default=32)
    ap.add_argument("--iters", type=int, default=3000)
    ap.add_argument("--lr", type=float, default=0.01)
    ap.add_argument("--wd", type=float, default=1e-5)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    run(a.L, a.H, a.iters, a.lr, a.wd, a.seed)
