# pokered-nano — Design Spec

> Working reference for the project. Read this first.
> Authoritative ROM numbers come from a **byte-exact build** of `pokered-master/`
> (sha1 `ea9bcae…` verified) parsed with [`poc/mapbudget.py`](poc/mapbudget.py).
> Ground truth for all Gen I behavior/formats is the `pokered-master/` disassembly
> — never guess, read the source.

---

## 1. Goal

Re-derive Pokémon Red **from first principles** into a micro/nano-sized version:
the smallest artifact that **looks exactly like** Red and **plays like** Red.
Not a byte-exact port — a re-derivation that keeps what a player perceives and
discards the machinery they don't.

**Fidelity contract (the organizing principle of this whole project):**

| Class | What it covers | Bar | Lossy budget? |
|-------|----------------|-----|---------------|
| **VISUAL** | all art, sprites, **map layout** | a deliberate, *consistent* **1bpp inked re-style** (see §3) — shapes/silhouettes faithful, shading dropped | **Stylistic only.** Locked to the chosen style; no per-asset approximation. |
| **CONTENT** | text, audio | lossless (it's information, not pixels, but no perceptual license to drop it) | No — but highly compressible |
| **BEHAVIORAL** | mechanics, formulas, event logic, the numbers driving them | "a casual player can't tell" | **Yes** — this is the 90–95% lever |

**ART DIRECTION (decided):** the game is re-styled to **1-bit-per-pixel "inked"**
(ink vs paper, threshold of the original 4 shades), rendered **dark-grey on cream**
— a Game & Watch / pencil-on-paper identity. This is a *style*, not a degradation:
applied uniformly to every asset (sprites, trainers, tilesets, UI) so it reads as
intentional. The palette is a render-time choice (**0 bytes**), tunable freely.
Procedural-redraw and lossy/autotiled *map layouts* remain **vetoed** — layout is
still faithful; only the per-pixel shading is dropped by the style.

---

## 2. The real ROM budget (the map)

The "1 MB cartridge" is mostly air. Of 1024 KB, only **561.9 KB is used
content**; **462 KB (45%) is empty bank padding.** The honest target is ~562 KB.

| Category | KB | % of used | Fidelity class | Status |
|----------|----:|----:|----------------|--------|
| **CODE** (engine/home/data tables) | 143 | 26% | behavioral | open — biggest lever |
| **TEXT** (dialogue/dex/names) | 124 | 22% | content | **open — biggest lossless win** |
| **ART — overworld** (tilesets+blocksets) | 48 | 8.5% | visual | 1bpp → ~22 KB (§3) |
| **ART — mon/trainer/npc/font sprites** | 114 | 20% | visual | 1bpp → ~52 KB (§3) |
| **MAPS** (`.blk` grids + scripts + objects) | 86 | 15% | mixed (see §6) | grids ~solved; scripts open |
| **AUDIO** (music+sfx+engine) | 47 | 8% | content | open (modest) |

`.blk` grids = 23.9 KB across 228 maps. The other ~62 KB of the "Maps" bucket is
per-map **scripts** (behavioral code), **headers**, and **objects** (NPC/warp/sign).

### What this kills
The original plan chased map+tile **art** under a (now-disproven) ~270 KB
baseline and a 20 KB / quadtree target. Reality: overworld art+grids is ~72 KB,
already squeezed to ~25 KB by the custom coders, and is **only ~13% of the ROM.**
That battle is essentially won; further work there is rounding error. The bytes
live elsewhere.

### Target & feasibility verdict
Goal: behavioral fidelity at **1/3–1/4 of the real 562 KB** (≈ 140–187 KB).
Aggressive per-class floors *with the 1bpp art decision (§3)*:

| Class | now | floor | lever |
|-------|----:|------:|-------|
| Visual (1bpp inked) | 186 | **~74** | bit-depth halving + lzma (§3) |
| Text (lossless) | 124 | **~32** | shared-dict PPM (§4) |
| Audio | 47 | **~25** | pattern factoring (§4) |
| Behavioral — script VM | 42 | **~20** | bytecode (§5a, *measured 1.6×*) |
| Behavioral — engine | ~80 | **~30–50** | host re-derivation (§5a, *unsized*) |
| Behavioral — drop tail | ~10 | **0** | delete (SGB/link/save) |
| **TOTAL** | **562** | **~181–201** | |

So **~1/3 (≈181 KB) is the honest reachable floor** with the levers we've now
*measured*. The earlier "~156–171" leaned on an optimistic VM that the POC
disproved (the VM is a ~20 KB script lever, not a code-wide one). The gap from
~1/3 to a true 1/4 (140 KB) lives **entirely in the engine re-derivation** — the
only lever still unsized, because its byte cost can't be counted until the host
runtime is chosen (§9). **That host decision is now the critical-path unknown.**

---

## 3. VISUAL class — 1bpp inked re-style

The locked floor of *2bpp pixel-exact* art (~128 KB, near its entropy floor —
sprites are genuine information, see §5 measurement) was the wall blocking the
size target. **Decision: re-style the whole game to 1bpp inked** (§1), which
roughly halves the visual class while giving it a coherent identity.

**Why 1bpp is the lever (measured, `poc/` experiments):**
- 2bpp mon sprites: 127 KB raw → 74 KB (Gen-I) → 72 KB (best modern lzma).
  Cross-sprite dictionary buys only ~2.5% — *irreducible at 2bpp.*
- 1bpp **threshold ("inked")**: → **~36 KB** lzma, and stays recognizable.
- 1bpp ink-silhouette: ~32 KB but looks bad (interiors collapse to blobs).
- 1bpp dither ("pencil"): prettiest sketch look but ~45–50 KB — **noise doesn't
  compress; avoid.** Use the clean threshold.

**Chosen encoding:** 1bpp threshold of the original 4 shades (ink = the two
darker shades). Rendered dark-grey-on-cream at draw time (palette = 0 bytes).
Known weakness: sprites with large solid-dark regions (Rhydon, Gengar) go
blobby; hand-touch the few worst offenders.

**Revised visual floor (whole class, all 1bpp):**
- mon sprites 72 → **~36**
- trainer/npc/font 30 → **~16**
- overworld: tilesets 12 (art halves) + blocksets ~6 + grids ~9 → **~22**
  (grids/blockset *indices* don't shrink with bit-depth; only tile art does)
- **visual class ≈ 128 KB → ~74 KB.**

Compression method per stream is settled: **plain entropy coding (lzma-class) on
the 1bpp bitmaps**, plus cross-map grid sharing. **Abandon global
content-addressed pools and the quadtree** — both lost to lzma on real data.
Treat the codec as solved; remaining work is the 1bpp conversion pipeline +
the few manual sprite fixes.

---

## 4. CONTENT class — lossless, the quick win

**TEXT — 124 KB → ~35 KB. Highest ROI in the project. Do this first.**
Gen I stores text nearly raw (a handful of substring macros). Measured on the
corpus: order-0 entropy floor 89 KB, bz2 43.6 KB, lzma 48 KB. A tuned
**PPM / word-dictionary** coder tailored to the corpus (huge phrase redundancy:
`POKéMON`, mon names, `There's a …`, dex boilerplate) reaches ~35 KB. **Zero
fidelity cost, no taste calls** — pure information coding. ~85 KB saved, more
than the entire art effort, for a contained, decisive experiment.

**AUDIO — 47 KB, modest.** Music/SFX are already compact channel-command
streams (MIDI-like). Lossless recompression yields little. Iconic themes are
perceptually load-bearing — treat as VISUAL-adjacent and keep. Lossy
simplification is possible but low-yield; defer.

---

## 5. BEHAVIORAL class — the 90–95% fidelity lever (~205 KB)

The real elephant: CODE (143 KB) + per-map scripts/headers/objects (~62 KB).
Hand-written Z80 expressing behavior a compact modern engine states in far fewer
bytes — **and the casual-play bar licenses dropping the long tail.** This is an
**engine-design** problem: re-derive the *minimal* mechanics that reproduce the
felt experience. Two modes:

1. **Equivalent logic refactor** (zero risk) — same behavior, compact expression.
2. **Player-equivalent simplification** of invisible subsystems (needs play-feel taste).

### Drop entirely (invisible long tail)
Link cable / trade-evolution plumbing, glitch behaviors, debug menus, hardware
workarounds, copy-protection, SRAM/save-corruption handling, unused code.

### Simplify (invisible mechanics — high value)
- **DV (IV) + stat-exp (EV) removal** — biggest single win: invisible system
  costing per-mon save bytes *and* gnarly formula code; replace with base+level.
- **Crit formula** — Gen-I speed-based → flat probability.
- **Damage / stat formulas** — streamline.
- **Trainer AI** — unify; drop per-class scoring tables.
- **RNG** — standard PRNG.
- **Behavioral-number quantization** — catch rate, base-exp, encounter rates.

### Keep near-exact (invisible but load-bearing for FEEL)
Type-effectiveness chart, status effects, and the **relative power ordering** of
Pokémon (quantize stats but preserve ranking). Caveat: speedrun/competitive
players *do* perceive DVs/crits — our bar is explicitly casual.

> Gen I already algorithmized its truly generative data (stats from base values,
> exp from growth-group polynomials, type chart as sparse exceptions). Keep those.

### LOGIC CENSUS (done — [`poc/census.py`](poc/census.py), symbol-delta sizing)
The ~144 KB code mass, by subsystem (ROM0/ROMX, symbol-delta sized):

| Subsystem | KB | Lever |
|-----------|---:|-------|
| misc / long tail | 41.7 | drop the invisible tail |
| pokemon mgmt/stats | 22.7 | quantize stats, drop DV/EV (`BaseStats` 4.1 KB) |
| battle | 22.1 | flat crit, unify AI |
| overworld/map engine | 20.9 | equivalent refactor |
| menus/UI | 16.3 | equivalent refactor |
| items/shop | 6.2 | refactor |
| scripts/cutscene | 6.1 | VM bytecode |
| pokedex | 4.2 | refactor |
| link/trade | 2.8 | **drop** |
| save/box/SRAM | 1.1 | **drop/simplify** |

**Key structural finding:** the code is *not* a few fat functions — it's
**~2300+ tiny routines** (every top code symbol ≤0.2 KB; the 41.7 KB misc bucket
alone is 2289 symbols averaging ~18 bytes). Reducing it is *not* one lever — it's
**three distinct mechanisms** that must be costed separately (see §5a).

### 5a. The behavioral mass needs THREE different levers (do not conflate)
Measured ([`poc/vmscan.py`](poc/vmscan.py), [`poc/vm_poc.py`](poc/vm_poc.py)):

1. **Script/event VM — bytecode.** Gen I *already* interprets text via a command
   stream (`home/text.asm` `TextCommandJumpTable`); scripts, by contrast, are
   *assemble-time macros* that expand to inline Z80 (every `CheckEvent` = 6 bytes
   of bit-twiddling ×330). Extending the text VM to cover events/scripts/cutscenes
   is the real "VM" work. **Measured scope: the script-code layer is 42.5 KB**
   (logic 15.9 + text-command wrappers 23.3 + dispatch tables 3.4) = 7.6% of ROM.
   Hand-encoding a real script (BluesHouse) into a ~30-opcode ISA gave **1.60×**
   (93 B → 58 B). So the basic VM saves **~16 KB**. *Bonus:* 23.3 KB of that layer
   is pure `text_far`+`text_end` indirection (5 B/string ×~1900); a 1-bit
   "plain-text" tag on the text-pointer table entry drops the wrapper to ~0 B,
   taking the layer toward ~18–20 KB (**~22 KB saved**).
2. **Engine re-derivation — compact host code, NOT bytecode.** The ~80 KB of
   battle/overworld/menu/mgmt engine shrinks by re-expressing it in a compact host
   (no banking/trampolines, no manual register allocation, host stdlib) + dropping
   invisible mechanics (DV/EV). **This is the real ~60–80 KB question** and the VM
   does *not* touch it. Gated on the host-language decision (§9).
3. **Drop the tail.** SGB 4 + link 2.8 + save 1.1 KB + glitch/debug ≈ ~10 KB.

The ~30-opcode ISA (script layer): `PRINT ref`, `END`, `IFEVENT/SET/CLR id`,
`SETSCRIPT n`, `SHOW/HIDE id`, `MOVE id,path`, `SETTILE coord,block`,
`IFAT coord`, `GIVE item,qty`, `TRAINER id`, `SFX/CRY/MUSIC id`, `YESNO`,
`DELAY`, `CALLNATIVE id` (the escape hatch for the ~12% `text_asm` procedural
tail). Avg ~2.5 B/op vs ~6–9 B of Z80 macro-expansion.

**Drop-now (surfaced in misc):** SGB/Super Game Boy border gfx+palettes ~4 KB
(`BorderPalettes`, `SGBBorderGraphics`, `SuperPalettes`, `CheckSGB`) — invisible
on plain GB, doubly so under the 1bpp re-style; link/trade 2.8 KB; save plumbing
1.1 KB; hidden-event flavor. **Simplify:** battle move-animation engine (bank1E
`FrameBlock`/`Subanimation`/`SpecialEffect`). **Keep but table-pack:** per-trainer
party data (`*Data` + `TrainerDataPointers`).

Caveat: keyword bucketing leaks some data (gfx/palettes/pointer tables) into code
buckets; `.map` symbol names can't cleanly split code-vs-data without disassembly.

---

## 6. The "Maps" bucket, decomposed (86 KB)

It's three different fidelity classes wearing one section name:
- `.blk` **grids** (23.9 KB) → VISUAL, locked, ~solved.
- per-map **headers + objects** (NPC/warp/sign/connections) → structured data;
  RLE/table-pack, mostly lossless.
- per-map **scripts** → BEHAVIORAL code; folds into the §5 logic census.

Don't optimize it as one thing.

---

## 7. Priority sequence

1. ~~Logic census~~ — **done** (§5). Behavioral mass mapped; VM POC measured.
2. **Host/runtime decision** (§9) — now the critical path: it unblocks the only
   unsized big lever (engine re-derivation) and defines the VM's `CALLNATIVE`
   surface. A design call, not more measurement.
3. **Text codec** — biggest *undone* lossless win (~85 KB), independent, no taste.
4. **Script VM assembler** — build once the host is chosen (ISA in §5a).
5. **Sprite recodec** — open ~114 KB visual front (modest, lossless-locked).
6. **Audio** — last, low yield.

Overworld art/grids: **done**, do not reopen without a cheap win.

---

## 8. Build & verification (reproducible ground truth)

```
toolchain : rgbds 1.0.1  (C:\Users\Anthony\rgbds-dl, win64) + mingw gcc (for tools/)
build     : mingw32-make pokered.gbc RGBDS=/c/Users/Anthony/rgbds-dl/
verify    : sha1sum pokered.gbc  ==  ea9bcae617fdf159b045185467ae58b2e4a48b9a
budget    : python poc/mapbudget.py   (parses pokered.map -> per-category bytes)
```

Any nano build's fidelity is judged against this byte-exact reference: VISUAL =
pixel diff must be zero; BEHAVIORAL = casual play-feel parity.

---

## 9. Open items

- ~~Host/runtime decision~~ — **settled** (§10): DSL is source of truth; C core
  ships standalone, Python is dev-mode interpreter of the same DSL.
- **DSL contract** *(critical path)* — the C-core primitive set + how engine
  mechanics (battle/overworld/menu) lower into the DSL. The script ISA (§5a) is the
  seed slice; generalize from there. Defines the `CALLNATIVE` signal surface.
- **Text coder design** — PPM order, dictionary construction, control-code handling.
- **Sprite codec** — is there a lossless scheme that beats Gen-I RLE by >20%?
- **Save-data shrink** — DV/EV removal changes the per-mon save struct; quantify.
- **Map headers/objects** — packing scheme for the ~62 KB non-grid map data.

---

## 10. Target architecture (the nano build)

The nano build is **not a Game Boy ROM**. The keystone decision: **a DSL is the
single source of truth** for behavior; the runtime executes it and surfaces the
complete game. Behavior is *authored once* in the DSL, never re-derived per target.

```
                  ┌───────────────────────────────────┐
                  │   DSL  — single source of truth    │
                  │   (behavior + content, declarative)│
                  └──────┬──────────────────────┬──────┘
        lower (dev)  ◄───┘                      └───►  lower (ship)
   ┌───────────────────────────┐       ┌───────────────────────────┐
   │  PYTHON interpreter        │       │  C CORE  (ships standalone)│
   │  (dev mode / reference)    │       │  minimal primitives +      │
   │  fast iteration, concepts  │       │  dispatch loop ONLY        │
   │  that resist lowering live │       │  — behavior lives in DSL,  │
   │  here while being derived  │       │    NOT hand-written in C   │
   └───────────────────────────┘       └───────────────────────────┘
                  both consume ▼ the same content blobs ▼
   ┌──────────────┬────────────────┬───────────────┬──────────────┐
   │ SCRIPT/logic │  TEXT blob      │  ART blobs    │  DATA tables │
   │ (DSL bytecode│ (PPM/dict, §4)  │ (1bpp+lzma §3)│ (stats/maps) │
   │  ~20 KB §5a) │  ~32 KB         │  ~74 KB       │  packed      │
   └──────────────┴────────────────┴───────────────┴──────────────┘
                  render ▼ (swappable adapter)
   ┌──────────────────────────────────────────────────────────────┐
   │  160×144 1bpp FRAMEBUFFER  → terminal (ref) / PNG / SDL / web  │
   └──────────────────────────────────────────────────────────────┘
```

### Host decision (settled)
**The DSL is canonical; two interpreters consume it.** Chosen model: *#2 (lower
away) with #1 (polyglot) as dev mode.*
- **Ship target = C core, standalone.** Minimal primitive set + a dispatch loop —
  *nothing more*. The bulk of "engine" is **not hand-written in C**; it lives in
  the DSL the C core interprets. (Per the rule: don't hand-build a big C engine —
  that's the brittle part. Keep C tiny; push behavior into the DSL.)
- **Dev mode = Python interpreter of the same DSL.** Fast iteration; concepts that
  resist lowering are expressed in Python *while being derived*, then lowered into
  the DSL — never stranded as a permanent Python dependency.
- **Derive once.** Both targets fall out of one DSL, eliminating the port/drift
  risk of re-deriving the engine twice.
- **Not Z80.** Re-compiling to Z80 re-inflates everything; the nano build is not
  a ROM.

### Rendering contract (settled)
The engine's *only* visual output is a **160×144 1-bit framebuffer** (exactly the
GB screen). Display is a **swappable adapter**, never known to the engine:
- **Reference adapter = terminal**, pixel-by-pixel, zoomed out (1 bit → 1 cell,
  ink/paper = two ANSI colors; the dark-grey-on-cream palette is applied here, 0
  bytes). The framebuffer is the universal interface — the *same* bits go to PNG /
  SDL / web canvas unchanged.
- Aspect caveat (terminal cells ~2:1 tall) is an adapter concern (square font or
  half-block), not an engine concern.

**Layering principles (each earned from the analysis above):**
- **Content is data, not code.** Scripts, text, maps, stats are *interpreted
  blobs*. Gen I already does this for text (`TextCommandJumpTable`); we push
  *everything author-facing* into the DSL/blobs so the C core stays tiny and each
  blob compresses independently.
- **The DSL is the only "logic."** The C core holds *only* irreducible primitives
  + dispatch; mechanics are DSL. This is what keeps the ship target small.
- **Render is decoupled from storage and from the engine.** Stored 1bpp; palette
  at draw time; framebuffer → swappable adapter.
- **One escape hatch, not many.** Genuinely procedural bits (the ~12% `text_asm`
  tail) route through a single `CALLNATIVE` opcode into a *named C-core primitive*
  — this is exactly the DSL↔C "signal layer," kept narrow on purpose.
- **Cut by class, never as one mass.** Each blob uses the codec matching its
  information type (entropy-code art, PPM text, byte-code logic, quantize data).

**Byte-counting frame:** the *artifact we minimize* = DSL behavior + content blobs.
The runtime (C core, or Python in dev) is fixed overhead — "hardware-equivalent,"
not counted — just as we never counted the Game Boy itself.

**What's settled vs open:**
- Settled: DSL-as-source-of-truth; C-core-ships / Python-dev; the framebuffer
  rendering contract; the four blob types; 1bpp art; the script ISA (§5a, the first
  DSL slice); per-class codecs (§3–4).
- Open: the **DSL contract itself** — the C-core primitive set + how engine
  mechanics (battle/overworld/menu) lower into DSL (the script ISA is the seed,
  generalize from there); text codec internals (§4); save-struct shrink (DV/EV).
```

## 11. Overworld DSL — the first concrete slice (settled + proven)

The overworld is the first subsystem authored in the DSL. The world decomposes
as **`@position kind → payload`** (payload recursively another blob: warp→map,
sign→text, npc→script). Terrain is the largest part and pinned the primitive.

**Primitive = the tile; storage = the block grid; DSL compiles down to it.**
Reasoning (least-data, matches the engine's own grain):
- A **tile** (8×8) is the primitive — *art and collision attach to tile-ids* in a
  shared, amortized tileset table. This matches Gen I: collision/grass/water/
  ledge/warp behavior all dispatch off the **tile-id**, not the block. (Block
  carries no properties; it is pure visual layout.)
- A **block** (4×4 tiles = 16 B) is *not* an authored object — it is **derived
  compression**: a repeated 4×4 tile pattern interned once. The blockset stops
  being hand-authored content and becomes auto-interned dedup over the tile grid.
- The **map** is canonically a tile grid but **stored as a block grid** (`.blk`,
  1 byte/block) because that is dramatically least-data. There is no "house
  object" abstraction — buildings are just their constituent tiles laid cell by
  cell; reuse is the block layer underneath, automatic and invisible.
- The **DSL is authoring-only**: author for legibility, *compile to the block
  grid*. Source representation and shipped bytes are independent.

**Round-trip proven** — [`poc/overworld_roundtrip.py`](poc/overworld_roundtrip.py)
on real PalletTown: `.blk` (block grid) → expand to tile grid → auto-intern 4×4
windows back to block ids → **byte-exact match, 90/90 bytes**; 0 duplicate-pattern
blocks, 0 unknown windows. Confirms the tile↔block layer is lossless and that
block-grid is the storage unit:
```
  tile grid  : 40×36 = 1440 B   (tile-primitive form)
  block grid : 10×9  =   90 B   (.blk, 16× smaller)        ← storage unit
  blockset   :         2048 B   (shared across all overworld maps)
  PalletTown uses 28 of 128 blocks (22%)
```

**Schema (shape, to refine as entities land):**
```
tileset overworld {
  tile '.' { art <8B 1bpp>  walk }
  tile 'T' { art <8B 1bpp>  solid }
  tile '"' { art <8B 1bpp>  walk encounter }
  tile 'D' { art <8B 1bpp>  warp }
}
map PalletTown : overworld 10x9 {
  grid """ <tile glyphs; compiles to block grid via auto-intern> """
  link  north Route1 ; link south Route21
  warp  @x,y -> RedsHouse1F
  sign  @x,y -> <text>
  npc   @x,y SPRITE_OAK stay -> <script>
  wild  ...
}
```

**Open (overworld):** entity coordinate origin (clean map coords vs raw +4
border-offset); whether to ship pokered's real blockset or our auto-interned one
(round-trip shows they coincide); generalizing the auto-interner across all
tilesets/maps and measuring game-wide grid+blockset bytes vs the 86 KB maps
bucket (§6).
