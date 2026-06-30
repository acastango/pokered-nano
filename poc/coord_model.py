#!/usr/bin/env python3
"""
pokered-nano — COORDINATE / delta world model (layer 1: the player).

Instead of redrawing the whole grid (80 chances to drift every step), the model
reads the STATIC map + the player's coordinate + an action, and predicts only the
NEW coordinate. The renderer draws the frame. Two wins:
  * static map can never corrupt (the model never draws it)
  * position is explicit ("read 6,5 -> write 7,5"), not counted in a token-sea

A cheap VERIFIER ("the detect-if-off") checks the predicted coord is legal given
the grid (adjacent-or-stay, target walkable) — your continuous-correction loop.

    <conda-python> poc\\coord_model.py gen   [steps] [out]
    <conda-python> poc\\coord_model.py train [corpus] [steps]
    <conda-python> poc\\coord_model.py bench [n_maps] [steps]
    <conda-python> poc\\coord_model.py watch  MAP [steps] [--still]
"""
import os
import sys
import json
import time
import random
import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from train_torch import GPT, ACT, END, PAD, DEV
from dagger import batch_next
from pokeworld import World, DELTA
from ascii_map import plain_grid, NPC_GLYPHS
from gen_data import small_maps

HERE = os.path.dirname(os.path.abspath(__file__))
ACTIONS = list(DELTA)
WALK = set(".gD")                                   # floor / grass / door
PRETTY = {"#": "█", ".": "·", "@": "@", "D": "▙"}


def state_str(grid, x, y):
    return grid + "\n@%d,%d" % (x, y)


def parse_coord(s):
    try:
        a, b = s.strip().split(",")
        return int(a), int(b)
    except Exception:
        return None


def move_from_grid(x, y, a, lines):
    """The verifier's rule: where the player legally ends up, read off the grid."""
    dx, dy = DELTA[a]
    nx, ny = x + dx, y + dy
    if 0 <= ny < len(lines) and 0 <= nx < len(lines[ny]) and lines[ny][nx] in WALK:
        return nx, ny
    return x, y


def npc_text_pages(base, text_const):
    """Resolve an NPC's dialogue (via text_engine) to a list of 2-row pages of
    plain displayable text. None/[] if the NPC has no static text (scripted)."""
    import text_engine
    try:
        screens = text_engine.resolve_text(base, text_const)
    except Exception:
        return None
    if not screens:
        return None
    lines = [text_engine.expand_tokens(b) for b, _ in screens]
    lines = [l for l in lines if l.strip()]
    if not lines:
        return None
    return [lines[i:i + 2] for i in range(0, len(lines), 2)]


def window_at(full, ci, cj, CW, CH, b=1):
    """A screen (CWxCH) plus a b-cell border ring into neighbors, so the model
    can see one tile past every edge and predict crossings. Off-map -> '#'.
    Core cells are window indices [b, b+CW) x [b, b+CH); a coord landing in the
    ring (outside the core) means the player crossed into the next screen."""
    GH = len(full)
    win = []
    for wy in range(CH + 2 * b):
        fy = cj * CH - b + wy
        row = []
        for wx in range(CW + 2 * b):
            fx = ci * CW - b + wx
            if 0 <= fy < GH and 0 <= fx < len(full[fy]):
                row.append(full[fy][fx])
            else:
                row.append("#")
        win.append("".join(row))
    return win


# --------------------------------------------------------------------------- data
def _emit_enum(f, mc, grid, reach):
    """Real enumerated transitions from the oracle (exact)."""
    n = 0
    for (x, y) in sorted(reach):
        for a in ACTIONS:
            o = World(mc); o.cx, o.cy = x, y
            o.step(a)
            if o.m.const != mc:
                continue
            f.write(json.dumps({"map": mc, "action": a,
                                "state": state_str(grid, x, y),
                                "next": "%d,%d" % (o.cx, o.cy)}) + "\n")
            n += 1
    return n


def cmd_gen(argv):
    enum = "enum" in argv or "--enum" in argv
    aug = "aug" in argv or "--aug" in argv
    chunks = "chunks" in argv or "--chunks" in argv
    windows = "windows" in argv or "--windows" in argv
    world = "world" in argv or "--world" in argv
    argv = [a for a in argv if a not in ("enum", "--enum", "aug", "--aug",
                                         "chunks", "--chunks", "windows", "--windows",
                                         "world", "--world")]
    steps = int(next((a for a in argv if a.isdigit()), 200))
    out = next((a for a in argv if not a.isdigit()),
               os.path.join(HERE, "transitions_coord.jsonl"))
    maps = small_maps()
    n = 0
    if world:
        # Phase B: like windows, but the STATE carries a map-id and the OUTPUT is
        # either a move (wx,wy) or a transition "M<dest>:dx,dy" (warp/stairs/edge
        # connection). Moves labeled by the fast rule; transitions by the oracle,
        # oversampled (they're rare) so the net memorizes the warp graph.
        from mapdata import _MAP_INDEX
        MAP_IDX = {c: i for i, c in enumerate(_MAP_INDEX)}
        CW, CH, b, OVER = 10, 9, 1, 20
        print("maps: %d  mode=world  (map-id + warp graph)" % len(_MAP_INDEX), flush=True)
        nt = 0
        with open(out, "w", encoding="utf-8") as f:
            for mc in _MAP_INDEX:
                try:
                    w = World(mc)
                    midx = MAP_IDX[mc]
                    full = plain_grid(w.m, None, w.m.npcs).split("\n")
                    GH, GW = len(full), len(full[0])
                    warp_at = w.m.warp_at
                    o = World(mc)                       # reused oracle for transitions
                    for cj in range(-(-GH // CH)):
                        for ci in range(-(-GW // CW)):
                            win = window_at(full, ci, cj, CW, CH, b)
                            cs = "\n".join(win)
                            for wy in range(b, b + CH):
                                for wx in range(b, b + CW):
                                    if win[wy][wx] not in ".g":
                                        continue
                                    ax, ay = ci * CW - b + wx, cj * CH - b + wy
                                    state = "M%d\n%s\n@%d,%d" % (midx, cs, wx, wy)
                                    for a in ACTIONS:
                                        dx, dy = DELTA[a]
                                        tx, ty = ax + dx, ay + dy
                                        transition = ((tx, ty) in warp_at
                                                      or not (0 <= tx < GW and 0 <= ty < GH))
                                        if not transition:           # plain move
                                            nx, ny = move_from_grid(wx, wy, a, win)
                                            outp = "%d,%d" % (nx, ny)
                                            reps = 1
                                        else:                        # warp / connection
                                            if o.m.const != mc:
                                                o = World(mc)
                                            o.cx, o.cy = ax, ay
                                            try:
                                                o.step(a)
                                            except Exception:
                                                o = World(mc); continue
                                            if o.m.const != mc and o.m.const in MAP_IDX:
                                                outp = "M%d:%d,%d" % (MAP_IDX[o.m.const],
                                                                      o.cx, o.cy)
                                                reps = OVER; nt += 1
                                            else:
                                                outp = "%d,%d" % (wx, wy)  # blocked edge
                                                reps = 1
                                        for _ in range(reps):
                                            f.write(json.dumps({"map": mc, "action": a,
                                                    "state": state, "next": outp}) + "\n")
                                            n += 1
                except Exception as e:
                    print("skip %s: %s" % (mc, e))
        print("wrote %d transitions (%d are warp/connection x%d) -> %s"
              % (n, nt, OVER, out))
        return
    if windows:
        # like chunks, but each screen carries a 1-cell BORDER ring so the model
        # learns to CROSS screen edges itself (Phase A). Label = verified rule on
        # the bordered window; a coord landing in the ring = a crossing.
        from mapdata import _MAP_INDEX
        CW, CH, b = 10, 9, 1
        print("maps: %d  mode=windows(%dx%d +%d border)"
              % (len(_MAP_INDEX), CW, CH, b), flush=True)
        with open(out, "w", encoding="utf-8") as f:
            for mc in _MAP_INDEX:
                try:
                    w = World(mc)
                    full = plain_grid(w.m, None, w.m.npcs).split("\n")
                    GH, GW = len(full), len(full[0])
                    for cj in range(-(-GH // CH)):
                        for ci in range(-(-GW // CW)):
                            win = window_at(full, ci, cj, CW, CH, b)
                            cs = "\n".join(win)
                            for wy in range(b, b + CH):
                                for wx in range(b, b + CW):
                                    if win[wy][wx] not in ".g":
                                        continue
                                    for a in ACTIONS:
                                        nx, ny = move_from_grid(wx, wy, a, win)
                                        f.write(json.dumps({"map": mc, "action": a,
                                                "state": state_str(cs, wx, wy),
                                                "next": "%d,%d" % (nx, ny)}) + "\n")
                                        n += 1
                except Exception as e:
                    print("skip %s: %s" % (mc, e))
        print("wrote %d windowed transitions -> %s" % (n, out))
        return
    if chunks:
        # EVERY map (big included) sliced into GB-screen chunks, exactly as play
        # sees them; label each chunk-local move with the verified rule. Teaches
        # the model to walk the whole overworld (indoor + outdoor), no edge bias.
        from mapdata import _MAP_INDEX
        CW, CH = 10, 9
        print("maps: %d  mode=chunks(%dx%d)" % (len(_MAP_INDEX), CW, CH), flush=True)
        with open(out, "w", encoding="utf-8") as f:
            for mc in _MAP_INDEX:
                try:
                    w = World(mc)
                    full = plain_grid(w.m, None, w.m.npcs).split("\n")
                    GH, GW = len(full), len(full[0])
                    for cj in range(-(-GH // CH)):
                        for ci in range(-(-GW // CW)):
                            chunk = [row[ci * CW: ci * CW + CW]
                                     for row in full[cj * CH: cj * CH + CH]]
                            cs = "\n".join(chunk)
                            for ly, row in enumerate(chunk):
                                for lx, ch in enumerate(row):
                                    if ch not in ".g":
                                        continue
                                    for a in ACTIONS:
                                        nx, ny = move_from_grid(lx, ly, a, chunk)
                                        f.write(json.dumps({"map": mc, "action": a,
                                                "state": state_str(cs, lx, ly),
                                                "next": "%d,%d" % (nx, ny)}) + "\n")
                                        n += 1
                except Exception as e:
                    print("skip %s: %s" % (mc, e))
        print("wrote %d chunked transitions -> %s" % (n, out))
        return
    if aug:
        # real enumerated + AUGMENTED variants: sprinkle extra NPC glyphs on
        # random floor tiles and label with the verified rule (move_from_grid).
        # Floods the corpus with "move into a solid glyph -> blocked" so dense-
        # NPC maps stop fooling the model.
        V = max(1, int(next((a for a in argv if a.isdigit()), 2)))
        rng = random.Random(7)
        print("maps: %d  mode=augment  variants=%d" % (len(maps), V), flush=True)
        with open(out, "w", encoding="utf-8") as f:
            for mc in maps:
                try:
                    w = World(mc); reach = w.spawn_main()
                    grid = plain_grid(w.m, None, w.m.npcs)
                    n += _emit_enum(f, mc, grid, reach)
                    base = [list(l) for l in grid.split("\n")]
                    for _ in range(V):
                        lines = [row[:] for row in base]
                        floors = [(x, y) for y, r in enumerate(lines)
                                  for x, c in enumerate(r) if c == "."]
                        if len(floors) < 4:
                            continue
                        rng.shuffle(floors)
                        k = rng.randint(3, max(4, len(floors) // 3))
                        for (x, y) in floors[:k]:
                            lines[y][x] = rng.choice(NPC_GLYPHS)
                        al = ["".join(r) for r in lines]
                        ag = "\n".join(al)
                        for y, r in enumerate(al):
                            for x, c in enumerate(r):
                                if c not in ".g":
                                    continue
                                for a in ACTIONS:
                                    nx, ny = move_from_grid(x, y, a, al)
                                    f.write(json.dumps({"map": mc, "action": a,
                                            "state": state_str(ag, x, y),
                                            "next": "%d,%d" % (nx, ny)}) + "\n")
                                    n += 1
                except Exception as e:
                    print("skip %s: %s" % (mc, e))
        print("wrote %d transitions (real + augmented) -> %s" % (n, out))
        return
    if enum:
        # EXHAUSTIVE: every reachable tile x every action. Perfectly uniform
        # coverage (random walks over-sample the center, starve the corners).
        print("maps: %d  mode=enumerate" % len(maps), flush=True)
        with open(out, "w", encoding="utf-8") as f:
            for mc in maps:
                try:
                    w = World(mc)
                    reach = w.spawn_main()
                    grid = plain_grid(w.m, None, w.m.npcs)
                    for (x, y) in sorted(reach):
                        for a in ACTIONS:
                            o = World(mc); o.cx, o.cy = x, y
                            o.step(a)
                            if o.m.const != mc:              # warped out -> skip
                                continue
                            f.write(json.dumps({"map": mc, "action": a,
                                                "state": state_str(grid, x, y),
                                                "next": "%d,%d" % (o.cx, o.cy)}) + "\n")
                            n += 1
                except Exception as e:
                    print("skip %s: %s" % (mc, e))
        print("wrote %d enumerated transitions -> %s" % (n, out))
        return
    rng = random.Random(1234)
    print("maps: %d  steps/map=%d  mode=randomwalk" % (len(maps), steps), flush=True)
    with open(out, "w", encoding="utf-8") as f:
        for mc in maps:
            try:
                w = World(mc)
                w.spawn_main()
                grid = plain_grid(w.m, None, w.m.npcs)      # static map, no @
                for _ in range(steps):
                    px, py = w.cx, w.cy
                    a = rng.choice(ACTIONS)
                    w.step(a)
                    if w.m.const != mc:                      # warped out -> reset
                        w = World(mc); w.spawn_main()
                        grid = plain_grid(w.m, None, w.m.npcs)
                        continue
                    f.write(json.dumps({"map": mc, "action": a,
                                        "state": state_str(grid, px, py),
                                        "next": "%d,%d" % (w.cx, w.cy)}) + "\n")
                    n += 1
            except Exception as e:
                print("skip %s: %s" % (mc, e))
    print("wrote %d coord transitions -> %s" % (n, out))


def build(corpus, cap=400):
    rows = [json.loads(l) for l in open(corpus, encoding="utf-8")]
    rows = [r for r in rows if len(r["state"]) + len(r["next"]) <= cap]
    maps = sorted({r["map"] for r in rows})
    seqs = [r["state"] + "\n" + ACT[r["action"]] + "\n" + r["next"] + END for r in rows]
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
    w = np.zeros_like(tgt, np.float32)
    for i in range(N):
        for p in range(Tmax - 1):
            if starts[i] <= p + 1 < Ls[i]:                  # loss on the next-coord
                w[i, p] = 1.0
    return (torch.tensor(inp), torch.tensor(tgt), torch.tensor(w),
            chars, stoi, Tmax - 1, maps)


# --------------------------------------------------------------------------- eval
def oracle_coord_set(maps, k, rng):
    """Eval set: sample tiles UNIFORMLY from the reachable area (not a random
    walk, which clusters) so per-step accuracy reflects the whole map."""
    items = []
    for mc in maps:
        w = World(mc)
        reach = list(w.spawn_main())
        if not reach:
            continue
        grid = plain_grid(w.m, None, w.m.npcs)
        for _ in range(k):
            x, y = rng.choice(reach)
            a = rng.choice(ACTIONS)
            o = World(mc); o.cx, o.cy = x, y
            o.step(a)
            if o.m.const != mc:
                continue
            items.append((grid, x, y, a, o.cx, o.cy))
    return items


def chunk_eval_set(maps, k, rng):
    """Held-out eval matching how play sees the world: random bordered screen
    windows (with map-id) of each map, random core tile, MOVE labeled by the
    verified rule. Returns (state, action, expected) triples."""
    from mapdata import _MAP_INDEX
    MAP_IDX = {c: i for i, c in enumerate(_MAP_INDEX)}
    CW, CH, b = 10, 9, 1
    items = []
    for mc in maps:
        try:
            midx = MAP_IDX.get(mc, 0)
            w = World(mc)
            full = plain_grid(w.m, None, w.m.npcs).split("\n")
            GH, GW = len(full), len(full[0])
            for _ in range(k):
                ci = rng.randrange(-(-GW // CW))
                cj = rng.randrange(-(-GH // CH))
                win = window_at(full, ci, cj, CW, CH, b)
                cells = [(wx, wy) for wy in range(b, b + CH)
                         for wx in range(b, b + CW) if win[wy][wx] in ".g"]
                if not cells:
                    continue
                wx, wy = rng.choice(cells)
                a = rng.choice(ACTIONS)
                nx, ny = move_from_grid(wx, wy, a, win)
                state = "M%d\n%s\n@%d,%d" % (midx, "\n".join(win), wx, wy)
                items.append((state, a, "%d,%d" % (nx, ny)))
        except Exception:
            pass
    return items


def evaluate(model, items, stoi, itos, T):
    states = [it[0] for it in items]
    acts = [it[1] for it in items]
    preds = batch_next(model, states, acts, stoi, itos, T)
    ok = sum(1 for pr, it in zip(preds, items) if pr == it[2])
    return 100 * ok / max(len(items), 1)


# --------------------------------------------------------------------------- train
def cmd_train(argv):
    resume = "--resume" in argv
    argv = [a for a in argv if not a.startswith("--")]
    corpus = next((a for a in argv if not a.isdigit()),
                  os.path.join(HERE, "transitions_coord.jsonl"))
    steps = int(next((a for a in argv if a.isdigit()), 4000))
    inp, tgt, w, chars, stoi, T, maps = build(corpus)
    V, N = len(chars), inp.shape[0]
    itos = {i: c for c, i in stoi.items()}
    print("device=%s corpus=%d vocab=%d T=%d maps=%d%s" % (DEV, N, V, T, len(maps),
          "  (resume)" if resume else ""), flush=True)
    inp, tgt, w = inp.to(DEV), tgt.to(DEV), w.to(DEV)
    model = GPT(V, T).to(DEV)
    path = os.path.join(HERE, "model_coord.pt")
    if resume and os.path.exists(path):
        ck = torch.load(path, map_location=DEV, weights_only=False)
        if ck["chars"] == chars:
            model.load_state_dict(ck["model"])
            print("resumed from model_coord.pt", flush=True)
    print("params: %.2fM" % (sum(p.numel() for p in model.parameters()) / 1e6))
    opt = torch.optim.AdamW(model.parameters(), lr=3e-4, weight_decay=0.01)
    es_maps = maps if len(maps) <= 24 else random.Random(7).sample(maps, 24)
    es = chunk_eval_set(es_maps, 6, random.Random(999))
    B = 128
    import torch.nn.functional as F
    for step in range(1, steps + 1):
        bi = torch.randint(0, N, (B,), device=DEV)
        logits = model(inp[bi])
        loss = (F.cross_entropy(logits.reshape(-1, V), tgt[bi].reshape(-1),
                                reduction="none") * w[bi].reshape(-1)).sum() / w[bi].sum()
        opt.zero_grad(); loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()
        if step % 200 == 0 or step == 1:
            acc = evaluate(model, es, stoi, itos, T)
            print("step %5d  loss %.4f  | next-coord exact %.1f%%"
                  % (step, loss.item(), acc), flush=True)
        if step % 2000 == 0:                           # checkpoint (survives timeout)
            torch.save({"model": model.state_dict(), "chars": chars, "T": T}, path)
    torch.save({"model": model.state_dict(), "chars": chars, "T": T}, path)
    print("saved model_coord.pt")


def load_model():
    ck = torch.load(os.path.join(HERE, "model_coord.pt"), map_location=DEV,
                    weights_only=False)
    chars, T = ck["chars"], ck["T"]
    stoi = {c: i for i, c in enumerate(chars)}
    model = GPT(len(chars), T).to(DEV)
    model.load_state_dict(ck["model"]); model.eval()
    return model, stoi, {i: c for c, i in stoi.items()}, T


# --------------------------------------------------------------------------- bench
def longest_run(oks):
    best = cur = 0
    for ok in oks:
        cur = cur + 1 if ok else 0
        best = max(best, cur)
    return best


def cmd_bench(argv):
    verified = "--verified" in argv
    argv = [a for a in argv if not a.startswith("--")]
    n = int(next((a for a in argv if a.isdigit()), 25))
    K = int([a for a in argv if a.isdigit()][1]) if len([a for a in argv if a.isdigit()]) > 1 else 200
    print("mode: %s" % ("model + VERIFIER in loop" if verified else "raw model"))
    model, stoi, itos, T = load_model()
    maps = small_maps()
    sample = random.Random(1).sample(maps, min(n, len(maps)))
    runs, agrees, covs, fixes, rows = [], [], [], [], []
    for mc in sample:
        w = World(mc); reach = w.spawn_main()
        if len(reach) < 2:
            continue
        grid = plain_grid(w.m, None, w.m.npcs)
        lines = grid.split("\n")
        rng = random.Random(7)
        coord = (w.cx, w.cy)
        oracle = World(mc); oracle.cx, oracle.cy = coord
        oks, visited, fix = [], {coord}, 0
        for _ in range(K):
            a = rng.choice(ACTIONS)
            pred = batch_next(model, [state_str(grid, *coord)], [a], stoi, itos, T)[0]
            mco = parse_coord(pred)
            legal = move_from_grid(coord[0], coord[1], a, lines)
            if mco != legal:
                fix += 1
            if verified:
                coord = legal                              # verifier corrects slips
            else:
                coord = mco if mco is not None else coord  # RAW: feed model's coord
            oracle.step(a)
            if oracle.m.const != mc:
                break
            true = (oracle.cx, oracle.cy)
            visited.add(true)
            oks.append(coord == true)
        if not oks:
            continue
        lr, ag = longest_run(oks), 100 * sum(oks) / len(oks)
        cov = 100 * len(visited) / len(reach)
        fr = 100 * fix / len(oks)
        runs.append(lr); agrees.append(ag); covs.append(cov); fixes.append(fr)
        rows.append((mc, lr, ag, cov, fr, len(oks)))
    rows.sort(key=lambda r: -r[1])
    print("map                              longest agree% cover% vfix%  steps")
    for mc, lr, ag, cov, fr, ln in rows:
        print("  %-30s %5d   %4.0f  %4.0f  %4.0f   %4d" % (mc, lr, ag, cov, fr, ln))
    print("\n%d maps | avg longest %.1f | avg agree %.0f%% | avg cover %.0f%% "
          "| avg verifier-fix %.0f%% | median longest %d"
          % (len(runs), sum(runs) / len(runs), sum(agrees) / len(agrees),
             sum(covs) / len(covs), sum(fixes) / len(fixes), sorted(runs)[len(runs) // 2]))


# --------------------------------------------------------------------------- watch
def vt_on():
    if os.name == "nt":
        import ctypes
        k = ctypes.windll.kernel32
        k.SetConsoleMode(k.GetStdHandle(-11), 7)


def cmd_watch(argv):
    still = "--still" in argv
    verified = "--verified" in argv
    argv = [a for a in argv if not a.startswith("--")]
    mc = next((a for a in argv if not a.isdigit()), "CERULEAN_POKECENTER")
    steps = int(next((a for a in argv if a.isdigit()), 60))
    model, stoi, itos, T = load_model()
    vt_on()
    w = World(mc); w.spawn_main()
    grid = plain_grid(w.m, None, w.m.npcs)
    lines = grid.split("\n")
    oracle = World(mc); oracle.cx, oracle.cy = w.cx, w.cy
    coord = (w.cx, w.cy)
    rng = random.Random(7)
    arrow = {"up": "↑", "down": "↓", "left": "←", "right": "→"}
    for t in range(1, steps + 1):
        a = rng.choice(ACTIONS)
        pred = batch_next(model, [state_str(grid, *coord)], [a], stoi, itos, T)[0]
        c = parse_coord(pred)
        legal = move_from_grid(coord[0], coord[1], a, lines)
        corrected = verified and c != legal
        coord = legal if verified else (c if c is not None else coord)
        oracle.step(a)
        ok = (oracle.m.const == mc and coord == (oracle.cx, oracle.cy))
        frame = plain_grid(w.m, coord, w.m.npcs)
        body = "\n".join("    " + "".join(PRETTY.get(ch, ch) for ch in ln)
                         for ln in frame.split("\n"))
        tag = "corrected" if corrected else ("OK" if ok else "drift")
        head = "  %s  step %3d  %s  [%s]" % (mc, t, arrow[a], tag)
        if still:
            print(head + "\n" + body + "\n")
        else:
            print("\033[2J\033[H  🧠 neural net is running the game\n\n" + head
                  + "\n\n" + body)
            sys.stdout.flush(); time.sleep(0.18)


def cmd_play(argv):
    """Walk the WHOLE overworld inside the model. Big maps are sliced into
    GB-screen chunks that connect Zelda-style: the model drives movement on the
    current screen; the engine handles screen-crossings, map connections, and
    warps (doors/stairs). Reuses the trained model on any map, no retrain."""
    import msvcrt
    raw = "--raw" in argv
    gfx = "--gfx" in argv                               # real 1bpp tile graphics
    braille = "--braille" in argv
    argv = [a for a in argv if not a.startswith("--")]
    mc = next((a for a in argv if not a.isdigit()), "PALLET_TOWN")
    CW, CH = 10, 9                                      # screen size (cells)
    model, stoi, itos, T = load_model()
    from mapdata import _MAP_INDEX
    IDX_LIST = list(_MAP_INDEX)                          # idx -> map const
    MAP_IDX = {c: i for i, c in enumerate(IDX_LIST)}     # map const -> idx
    vt_on()
    facing = "down"
    if gfx:                                             # reuse the engine renderer
        from mapdata import load_sprite
        from play import compose, CENTER, clamp
        from play_pallet import to_block, to_braille, VW_PX, VH_PX
        spr = load_sprite("red")
    w = World(mc); w.spawn_main()
    full = plain_grid(w.m, None, w.m.npcs).split("\n")
    keys = {b"w": "up", b"s": "down", b"a": "left", b"d": "right"}
    arrows = {b"H": "up", b"P": "down", b"K": "left", b"M": "right"}
    note = ""
    dlg, dpg = None, 0                                  # active dialogue pages, page idx
    while True:
        GH, GW = len(full), len(full[0])
        ax, ay = w.cx, w.cy
        ci, cj = ax // CW, ay // CH
        if gfx:                                     # real 16x16 tile art, 1bpp
            px, py = w.m.player_px(ax, ay)
            cam_x = clamp(px - CENTER, 0, w.m.PTWpx - VW_PX)
            cam_y = clamp(py - CENTER, 0, w.m.PTHpx - VH_PX)
            sprites = [(spr[facing][0], px - cam_x, py - cam_y)]
            fb = compose(w.m.world_fb, cam_x, cam_y, sprites, invert=True)
            body = (to_braille if braille else to_block)(fb)
        else:                                       # camera-follow ASCII viewport
            VW, VH = 13, 11
            view = []
            for vy in range(VH):
                row = []
                for vx in range(VW):
                    wx, wy = ax - VW // 2 + vx, ay - VH // 2 + vy
                    if vx == VW // 2 and vy == VH // 2:
                        row.append("@")             # player stays centered
                    elif 0 <= wy < GH and 0 <= wx < len(full[wy]):
                        row.append(full[wy][wx])
                    else:
                        row.append(" ")             # off-map -> blank
                view.append("".join(row))
            body = "\n".join("    " + "".join(PRETTY.get(c, c) for c in r) for r in view)
        print("\033[2J\033[H")
        print("  🧠 the neural net is driving   %s  (%d,%d)  %s"
              % (mc, ax, ay, "[raw]" if raw else "[+verifier]"))
        print("  WASD/arrows move,  Z talk,  Q quit       %s\n" % note)
        print(body)
        if dlg is not None:
            top, bot = (dlg[dpg] + ["", ""])[:2]
            more = "▼ Z" if dpg < len(dlg) - 1 else "(end)"
            print("\n   ╔" + "═" * 20 + "╗")
            print("   ║ %-18s ║" % top)
            print("   ║ %-18s ║  %s" % (bot, more))
            print("   ╚" + "═" * 20 + "╝")
        sys.stdout.flush()
        k = msvcrt.getch()
        if k in (b"q", b"\x1b"):
            break
        if k in (b"z", b" ", b"\r", b"\n"):            # A / talk / confirm
            if dlg is not None:
                dpg += 1
                if dpg >= len(dlg):
                    dlg, dpg = None, 0
            else:
                fdx, fdy = DELTA[facing]
                fcell = (ax + fdx, ay + fdy)
                npc = next((n for n in w.m.npcs if not n.get("hidden") and
                            (n.get("cx", n["x"]), n.get("cy", n["y"])) == fcell), None)
                if npc is not None:
                    pages = npc_text_pages(w.m.base, npc.get("text"))
                    dlg, dpg = (pages if pages else [["...", ""]]), 0
            continue
        if dlg is not None:                            # dialogue eats movement keys
            continue
        if k in (b"\xe0", b"\x00"):
            action = arrows.get(msvcrt.getch())
        else:
            action = keys.get(k.lower())
        if not action:
            continue
        facing = action
        note = ""
        b = 1                                          # bordered window + map-id
        win = window_at(full, ci, cj, CW, CH, b)
        wx, wy = ax - ci * CW + b, ay - cj * CH + b
        state = "M%d\n%s\n@%d,%d" % (MAP_IDX[mc], "\n".join(win), wx, wy)
        pred = batch_next(model, [state], [action], stoi, itos, T)[0]
        if pred.startswith("M") and ":" in pred:       # model predicts a transition
            try:
                didx, dc = pred[1:].split(":")
                dx, dy = dc.split(",")
                mc = IDX_LIST[int(didx)]
                w = World(mc); w.cx, w.cy = int(dx), int(dy)
                full = plain_grid(w.m, None, w.m.npcs).split("\n")
                note = "→ %s" % mc
            except Exception:
                note = "(bad warp: %s)" % pred
        else:                                          # plain move within the map
            c = parse_coord(pred)
            legal = move_from_grid(wx, wy, action, win)
            nl = c if (raw and c is not None) else legal
            if c != legal:
                note = ("model -> %s" % pred) if raw else "(verifier corrected)"
            w.cx, w.cy = ci * CW - b + nl[0], cj * CH - b + nl[1]
    print("\033[2J\033[H  bye.")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "bench"
    rest = sys.argv[2:]
    {"gen": cmd_gen, "train": cmd_train, "bench": cmd_bench,
     "watch": cmd_watch, "play": cmd_play}[cmd](rest)
