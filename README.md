# pokered-nano

**Can a small neural network *learn to be* Pokémon Red — and can you walk around inside it?**

It can. A **~5M-parameter character transformer**, trained only on a faithful
engine's ASCII traces, **walks the entire Kanto overworld at ~98% unaided** —
collision, doors, stairs, map connections — and you can drive it yourself with
WASD. No game rules were ever given to it; it induced them by watching the game
get played.

The project has two layers, and the second is the one worth your attention:

1. **A faithful engine** — the *smallest artifact that still looks and plays like
   Red* (Python stdlib only, rendered 1-bit into a terminal). It began as a study
   in how small "the same game" can honestly get; it turned out to be the perfect
   **teacher**.
2. **A learned simulator** — a tiny net that learns the game's *rules* from the
   engine's screens alone, then *runs* them. The engine is the oracle; the model
   is the student that becomes the engine.

> Original design/measurement doc: **[`DESIGN.md`](DESIGN.md)**.

---

## Walk the learned world

Every frame is the **neural net's own prediction**: you press a key, it predicts
the next screen. Big maps are sliced into Game-Boy-sized screen chunks that connect
Zelda-style, so a single model walks all 220 maps:

```
<conda-python> poc/coord_model.py play PALLET_TOWN      # WASD / arrows; Q to quit
```

The net handles movement; a cheap **verifier** (the collision rule read off the
grid, 99.96% faithful to the engine) catches its rare slips. Add `--raw` to drive
the *unaided* net (~98% correct). `█`=wall · `·`=floor · `@`=you · digits=NPCs.
How it learned this is in **[Teaching a net to be the engine](#teaching-a-model-to-be-the-engine-a-learned-world-model)**.

---

## The foundation: a faithful engine (the model's oracle)

The learned simulator is only as good as its teacher, and the teacher is a
**playable terminal engine** rendered as a 1-bit framebuffer — the real Game Boy
screen (160×144), drawn pixel-by-pixel into your terminal. It's faithful enough to
be ground truth: every `(screen, button) → next screen` it produces is an exact
training example.

Here is Pallet Town, straight from the engine's `block` display adapter (the *full*
160×144 GB screen — half-block glyphs `▀ ▄ █` pack a 1×2 pixel pair per cell; it's
wide, scroll right to see the rest):

```text
█ █▄▄▄▄▄▄▄▄▄▄█ █▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▀         █       ▄▄▄▀▀▀▀▀▀▄                     ▄ ▄     ▄ ▄     ██████████████▄     █  ▀       █ █▄▄▄▄▄▄▄▄▄▄█ █▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄
█ ████████████ ██     ▄██     ▄█          █        █▄▀▀▄▀▀▀▄█                    ▀ ▀ █ █ ▀ ▀ █ █ ▄██▄▄▄▄▄▄▄██▄██     █          █ ████████████ ██     ▄██     ▄█
█ ███      ███ ██   ▄▀▄██   ▄▀▄█          █      ▄▀█        █▀▄                   ▄ ▄     ▄ ▄   █ ▄       ▄▄  ██     █          █ ███      ███ ██   ▄▀▄██   ▄▀▄█
█ ███      ███ ██▄▄█▄████▄▄█▄███          █      █    █  █    █                   ▀ ▀     ▀ ▀   █ ▀▀ ▀ ▀▀ ▀▀ ▀██     █          █ ███      ███ ██▄▄█▄████▄▄█▄███
█ ██████████▀█ █                          █      ▄█▀▄      ▄▀█▄  ▄ ▄             ▄ ▄     ▄ ▄    █ ██ ▄ ▄▄ █ █ ██     █          █ ██████████▀█ █
█ ██        ██ █                          █     █  █ ▀████▀ █  █ ▀ ▀ █ █         ▀ ▀ █ █ ▀ ▀ █ █▀▄▄▄▄▄▄▄▄▄▄▄▄▄██     █          █ ██        ██ █
█ ██▄▄▄▄▄▄▄▄██ ██████████████████████████ █      ▀█▀  █▄▄█  ▀█▀   ▄ ▄             ▄ ▄     ▄ ▄             ▄██ ██     █ ██████████ ██▄▄▄▄▄▄▄▄██ █████████████████
█▄▀▀▀▀▀▀▀▀▀▀▀▀▄█▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀        ▄████▀▀████▄    ▀ ▀             ▀ ▀     ▀ ▀             ▀▀████      ▀▀▀▀▀▀▀▀▀▀█▄▀▀▀▀▀▀▀▀▀▀▀▀▄█▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀




                 ▄ ▄                             ▄ ▄                             ▄ ▄                             ▄ ▄                             ▄ ▄
                 ▀ ▀ █ █                         ▀ ▀ █ █                         ▀ ▀ █ █                         ▀ ▀ █ █                         ▀ ▀ █ █
                  ▄ ▄                             ▄ ▄                             ▄ ▄                             ▄ ▄                             ▄ ▄
                  ▀ ▀                             ▀ ▀                             ▀ ▀                             ▀ ▀                             ▀ ▀




 ▄ ▄                             ▄ ▄                             ▄ ▄                             ▄ ▄                             ▄ ▄
 ▀ ▀ █ █                         ▀ ▀ █ █                         ▀ ▀ █ █                         ▀ ▀ █ █                         ▀ ▀ █ █
  ▄ ▄                             ▄ ▄                             ▄ ▄                             ▄ ▄                             ▄ ▄
  ▀ ▀                             ▀ ▀                             ▀ ▀                             ▀ ▀                             ▀ ▀
 ▄ ▄     ▄ ▄     ▄ ▄     ▄ ▄     ▄ ▄     ▄ ▄                                                 ▄▄█▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀
 ▀ ▀ █ █ ▀ ▀ █ █ ▀ ▀ █ █ ▀ ▀ █ █ ▀ ▀ █ █ ▀ ▀ █ █                                         ▄▄██ ██
  ▄ ▄     ▄ ▄     ▄ ▄     ▄ ▄     ▄ ▄     ▄ ▄                                        ▄▄▀██ ██ ██▀▀▀█▀▀▀▀▀▀▀█▀▀▀▀▀▀▀█▀▀▀▀▀▀▀█▀▀▀▀▀▀▀█▀▀▀▀▀▀▀█▀▀▀▀▀▀▀█▀▀▀▀▀▀▀█▀▀▀▀
  ▀ ▀     ▀ ▀     ▀ ▀     ▀ ▀     ▀ ▀     ▀ ▀                                    ▄▄█▀██ ██ ██ ██ ▄▀      ▄▀      ▄▀      ▄▀      ▄▀      ▄▀      ▄▀      ▄▀
 ▄ ▄     ▄ ▄     ▄ ▄     ▄ ▄     ▄ ▄     ▄ ▄     ▄ ▄                            █ ██ ██ ██ ██ ██       ▄       ▄       ▄       ▄       ▄       ▄       ▄       ▄
 ▀ ▀ █ █ ▀ ▀ █ █ ▀ ▀ █ █ ▀ ▀ █ █ ▀ ▀ █ █ ▀ ▀ █ █ ▀ ▀ █ █                        █ ██ ██ ██ ██ ██     ▄▀      ▄▀      ▄▀      ▄▀      ▄▀      ▄▀      ▄▀      ▄▀
  ▄ ▄     ▄ ▄     ▄ ▄     ▄ ▄     ▄ ▄     ▄ ▄     ▄ ▄                           █ ██ ██ ██ ██ ██   ▄       ▄       ▄       ▄       ▄       ▄       ▄       ▄
  ▀ ▀     ▀ ▀     ▀ ▀     ▀ ▀     ▀ ▀     ▀ ▀     ▀ ▀                           █ ██ ██ ██ ██ ██ ▄▀      ▄▀      ▄▀      ▄▀      ▄▀      ▄▀      ▄▀      ▄▀
                                 ██████████████▄                    ▄▀▀▀▀▀▀▄    █ ██ ██ ██ ██ ██       ▄       ▄       ▄       ▄       ▄       ▄       ▄       ▄
 ▄████▄  ▄████▄  ▄████▄  ▄████▄  ▄██▄▄▄▄▄▄▄██▄██                   █        █   █ ██ ██ ██ ██ ██     ▄▀      ▄▀      ▄▀      ▄▀      ▄▀      ▄▀      ▄▀      ▄▀
 █▀████  █▀████  █▀████  █▀████ █ ▄       ▄▄  ██                  ██▀▄▄▄▄▄▄▀██  █ ██ ██ ██ ██ ██   ▄       ▄       ▄       ▄       ▄       ▄       ▄       ▄
 █  ███  █  ███  █  ███  █  ███ █ ▀▀ ▀ ▀▀ ▀▀ ▀██                 █ ▀  ▄  ▄  ▀ █ █ ██ ██ ██ ██ ██ ▄▀      ▄▀      ▄▀      ▄▀      ▄▀      ▄▀      ▄▀      ▄▀
 █  ███  █  ███  █  ███  █  ███ █ ██ ▄ ▄▄ █ █ ██                 ▄██▄ ▀  ▀ ▄██  █ ██ ██ ██ ██ ██▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀
 █  ▀ █  █  ▀ █  █  ▀ █  █  ▀ █ ▀▄▄▄▄▄▄▄▄▄▄▄▄▄██                 █  ████████  █ █ ██ ██ ██ ██ ██
 █▄ ▄██  █▄ ▄██  █▄ ▄██  █▄ ▄██           ▄██ ██                  ██▀▄▄▀▀▄▄▀█▀  █ ██ ██ ██ ██ ██▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄
  ▀▀▀▀    ▀▀▀▀    ▀▀▀▀    ▀▀▀▀            ▀▀████                  ▀▀▄▄▄▀▀▄▄▄▀   █ ██ ██ ██ █████████████████████████████████████████████████████████████████████
▀▄▀ ▀▄▀█▀▄▀ ▀▄▀█▀▄▀ ▀▄▀█▀▄▀ ▀▄▀█▀▄▀ ▀▄▀█▀▄▀ ▀▄▀█                                █ ██ ██▄█████▀▀ ▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄      ▄       ▄ ▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄
▀▄ ▄██▀▄▀▄ ▄██▀▄▀▄ ▄██▀▄▀▄ ▄██▀▄▀▄ ▄██▀▄▀▄ ▄██▀▄                                █ ██▄████▀▀     █     ▄██     ▄██     ▄█      ▀       ▀ █     ▄██     ▄██     ▄█
▀▄▀█▀ █▄▀▄▀█▀ █▄▀▄▀█▀ █▄▀▄▀█▀ █▄▀▄▀█▀ █▄▀▄▀█▀ █▄                                █████▀▀         █   ▄▀▄██   ▄▀▄██   ▄▀▄█  █       █     █   ▄▀▄██   ▄▀▄██   ▄▀▄█
 ▄█▄▄█▀▄ ▄█▄▄█▀▄ ▄█▄▄█▀▄ ▄█▄▄█▀▄ ▄█▄▄█▀▄ ▄█▄▄█▀▄                                 ▀▀▀█           █▄▄█▄████▄▄█▄████▄▄█▄███      ▄       ▄ █▄▄█▄████▄▄█▄████▄▄█▄███
▀▄▀ ▀▄▀█  ▄▀▀▄  ▀▄▀ ▀▄▀█  ▄▀▀▄  ▀▄▀ ▀▄▀█  ▄▀▀▄   ▄ ▄                                 █  ▀       ▀       ▀             ▄       ▄       ▄       ▄       ▄       ▄
▀▄ ▄██▀▄ █ ▀▀ █ ▀▄ ▄██▀▄ █ ▀▀ █ ▀▄ ▄██▀▄ █ ▀▀ █  ▀ ▀ █ █                             █                                ▀       ▀       ▀       ▀       ▀       ▀
▀▄▀█▀ █▄▄▄▀▄▄▀▄▄▀▄▀█▀ █▄▄▄▀▄▄▀▄▄▀▄▀█▀ █▄▄▄▀▄▄▀▄▄  ▄ ▄                                █                            █       █       █       █       █       █
 ▄█▄▄█▀▄ ▀▀██▀▀  ▄█▄▄█▀▄ ▀▀██▀▀  ▄█▄▄█▀▄ ▀▀██▀▀   ▀ ▀                                █                                ▄       ▄       ▄       ▄       ▄       ▄
  ▄▀▀▄  ▀▄▀ ▀▄▀█  ▄▀▀▄  ▀▄▀ ▀▄▀█  ▄▀▀▄  ▀▄▀ ▀▄▀█                                     █  ▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄█ █▄▄▄▄▄▄▄▄▄▄█ █▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄
 █ ▀▀ █ ▀▄ ▄██▀▄ █ ▀▀ █ ▀▄ ▄██▀▄ █ ▀▀ █ ▀▄ ▄██▀▄                                     █  █     ▄██     ▄██     ▄██ ████████████ ██     ▄██     ▄██     ▄██     ▄█
▄▄▀▄▄▀▄▄▀▄▀█▀ █▄▄▄▀▄▄▀▄▄▀▄▀█▀ █▄▄▄▀▄▄▀▄▄▀▄▀█▀ █▄                                     █  █   ▄▀▄██   ▄▀▄██   ▄▀▄██ ███      ███ ██   ▄▀▄██   ▄▀▄██   ▄▀▄██   ▄▀▄█
 ▀▀██▀▀  ▄█▄▄█▀▄ ▀▀██▀▀  ▄█▄▄█▀▄ ▀▀██▀▀  ▄█▄▄█▀▄                                     █  █▄▄█▄████▄▄█▄████▄▄█▄████ ███      ███ ██▄▄█▄████▄▄█▄████▄▄█▄████▄▄█▄███
▀▄▀ ▀▄▀█▀▄▀ ▀▄▀█▀▄▀ ▀▄▀█▀▄▀ ▀▄▀█▀▄▀ ▀▄▀█▀▄▀ ▀▄▀█                 ▄ ▄                 █                          █ ██████████▀█ █
▀▄ ▄██▀▄▀▄ ▄██▀▄▀▄ ▄██▀▄▀▄ ▄██▀▄▀▄ ▄██▀▄▀▄ ▄██▀▄                 ▀ ▀ █ █             █                          █ ██        ██ █
▀▄▀█▀ █▄▀▄▀█▀ █▄▀▄▀█▀ █▄▀▄▀█▀ █▄▀▄▀█▀ █▄▀▄▀█▀ █▄                  ▄ ▄                █ ██████████████████████████ ██▄▄▄▄▄▄▄▄██ █████████████████████████████████
 ▄█▄▄█▀▄ ▄█▄▄█▀▄ ▄█▄▄█▀▄ ▄█▄▄█▀▄ ▄█▄▄█▀▄ ▄█▄▄█▀▄                  ▀ ▀                 ▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀█▄▀▀▀▀▀▀▀▀▀▀▀▀▄█▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀
                                                                                 ▄ ▄     ▄ ▄     ▄ ▄     ▄ ▄     ▄ ▄     ▄ ▄     ▄ ▄     ▄ ▄     ▄ ▄     ▄ ▄
                                                                                 ▀ ▀ █ █ ▀ ▀ █ █ ▀ ▀ █ █ ▀ ▀ █ █ ▀ ▀ █ █ ▀ ▀ █ █ ▀ ▀ █ █ ▀ ▀ █ █ ▀ ▀ █ █ ▀ ▀ █ █
                                                                                  ▄ ▄     ▄ ▄     ▄ ▄     ▄ ▄     ▄ ▄     ▄ ▄     ▄ ▄     ▄ ▄     ▄ ▄     ▄ ▄
                                                                                  ▀ ▀     ▀ ▀     ▀ ▀     ▀ ▀     ▀ ▀     ▀ ▀     ▀ ▀     ▀ ▀     ▀ ▀     ▀ ▀
                 ▄ ▄                             ▄ ▄                             ▄ ▄     ▄ ▄     ▄ ▄     ▄ ▄     ▄ ▄     ▄ ▄     ▄ ▄     ▄ ▄     ▄ ▄     ▄ ▄
                 ▀ ▀ █ █                         ▀ ▀ █ █                         ▀ ▀ █ █ ▀ ▀ █ █ ▀ ▀ █ █ ▀ ▀ █ █ ▀ ▀ █ █ ▀ ▀ █ █ ▀ ▀ █ █ ▀ ▀ █ █ ▀ ▀ █ █ ▀ ▀ █ █
                  ▄ ▄                             ▄ ▄                             ▄ ▄     ▄ ▄     ▄ ▄     ▄ ▄     ▄ ▄     ▄ ▄     ▄ ▄     ▄ ▄     ▄ ▄     ▄ ▄
                  ▀ ▀                             ▀ ▀                             ▀ ▀     ▀ ▀     ▀ ▀     ▀ ▀     ▀ ▀     ▀ ▀     ▀ ▀     ▀ ▀     ▀ ▀     ▀ ▀
                                                                                                                                 ██████████████▄
                                                                                 ▄████▄  ▄████▄  ▄████▄  ▄████▄  ▄████▄  ▄████▄  ▄██▄▄▄▄▄▄▄██▄██ ▄████▄  ▄████▄
                                                                                 █▀████  █▀████  █▀████  █▀████  █▀████  █▀████ █ ▄       ▄▄  ██ █▀████  █▀████
                                                                                 █  ███  █  ███  █  ███  █  ███  █  ███  █  ███ █ ▀▀ ▀ ▀▀ ▀▀ ▀██ █  ███  █  ███
 ▄ ▄                             ▄ ▄                             ▄ ▄             █  ███  █  ███  █  ███  █  ███  █  ███  █  ███ █ ██ ▄ ▄▄ █ █ ██ █  ███  █  ███
 ▀ ▀ █ █                         ▀ ▀ █ █                         ▀ ▀ █ █         █  ▀ █  █  ▀ █  █  ▀ █  █  ▀ █  █  ▀ █  █  ▀ █ ▀▄▄▄▄▄▄▄▄▄▄▄▄▄██ █  ▀ █  █  ▀ █
  ▄ ▄                             ▄ ▄                             ▄ ▄            █▄ ▄██  █▄ ▄██  █▄ ▄██  █▄ ▄██  █▄ ▄██  █▄ ▄██           ▄██ ██ █▄ ▄██  █▄ ▄██
  ▀ ▀                             ▀ ▀                             ▀ ▀             ▀▀▀▀    ▀▀▀▀    ▀▀▀▀    ▀▀▀▀    ▀▀▀▀    ▀▀▀▀            ▀▀████  ▀▀▀▀    ▀▀▀▀
```

The `color` and `braille` adapters draw the *same* bits with a warm ink-on-cream
palette; `ascii` is a plain-keyboard fallback (`" .:-=+*#@"` density ramp) for
terminals/fonts that can't show the block glyphs.

- Smooth 30 fps game loop, held-key input, gliding movement, pixel-precise
  camera-follow — at the original ~7.5 tiles/s pace.
- Real Gen I **collision**, **warps** (doors between maps, indoor/outdoor return
  logic), and **NPCs** that block movement and turn to face you when talked to.
- A faithful Gen I **text system**: real font glyphs, the GB text box, typewriter
  animation, multi-page scrolling, signs and NPC dialogue.
- The **"inked" art direction**: every asset thresholded to 1-bit (ink vs paper),
  rendered dark-grey on cream — a Game & Watch / pencil-on-paper identity. World
  art is dark-on-light; characters are inverted (light-on-dark) so they pop.
- **Swappable display adapters** off the *same* framebuffer (proving render is
  decoupled from the engine): half-block color, colored braille, plain ASCII.

Everything is **Python stdlib only** — no Pillow, no numpy. PNGs are decoded by a
hand-rolled zlib-based reader.

### Run it

The interactive engine uses the Windows `GetAsyncKeyState` API for held-key input,
so live play is currently **Windows-only**:

```powershell
C:\msys64\mingw64\bin\python.exe poc\play.py
```

| Key | Action |
|-----|--------|
| `W A S D` / arrows | walk (hold) |
| `Z` / `Enter` / `Space` | talk / confirm |
| `M` | cycle display look (block → color → braille → ascii) |
| `I` | toggle character inversion |
| `Q` | quit |

> **Display fit:** render is always native resolution (never cropped/scaled). To
> see the whole screen, maximize the terminal and shrink the font — `block` mode
> needs ≥160 cols × 72 rows. Windows Terminal renders the half-block/braille
> glyphs best.

The non-interactive PoCs (round-trip, corpus analysis, renderers that emit PNGs)
run on any platform with Python 3.8+.

---

## Teaching a model to *be* the engine (a learned world model)

A different question from the rest of the project: instead of *shrinking* the
engine, can a small neural net **learn to be** it — predict the game's next frame
from the current one and a button press, having only ever *played*?

The trick is the representation. Render each map as an **ASCII grid, one character
per 8×8 tile** (`#` wall, `.` floor, `@` player, `D` door, digits = NPCs). That
turns one step of the game into a tiny language task: read the grid + an action
(`^ v < >`), emit the next grid. The faithful engine above becomes a perfect
**oracle** — it generates unlimited ground-truth `(state, action) → next` traces
and grades the model's predictions exactly.

The whole stack is from scratch — stdlib, plus one optional GPU dependency:

```
pokeworld.py    headless cell-level oracle (step + ASCII render), no render deps
gen_data.py     rolls the oracle over 103 small maps → (state, action, next) corpus
nn.py           a hand-written reverse-mode autograd engine over NumPy (gradient-checked)
train.py        char transformer built on nn.py — the from-scratch CPU proof
train_torch.py  the same model in PyTorch/CUDA — the fast path (trained on an RTX 3070)
eval.py         grades generated next-states against the oracle
rollout.py      closed-loop: feed the model its own output and let it run the game
dagger.py       scheduled sampling — train on the states the model itself visits
```

### What it showed

- **It learns the rule, not the map.** Trained on **103 diverse interiors**, a
  ~4.8 M-param transformer predicts the exact next grid **~99%** of the time on
  *held-out* transitions — collision, walls, NPC blocking, the player move, all
  inferred from examples.
- **Diversity *is* the teacher.** On only 2 maps it scored 82% — it had
  *memorized* two layouts. At 103 maps there was no room to memorize, so it was
  forced to generalize: held-out accuracy went **82% → ~99%**. More maps made it
  *more* accurate, not less.
- **The bottleneck was optimization, not capacity.** The from-scratch trainer
  plateaued until an overfit probe showed the loss was actually *diverging*;
  gradient clipping + a lower LR fixed it (a 16-example overfit then hit 16/16).
- **Per-step accuracy ≠ playability.** Run closed-loop — the model feeding on its
  own predictions — it stays a *coherent* simulator (every frame a valid state:
  intact walls, NPCs, exactly one player) but drifts off the true trajectory
  after ~7 steps, because it never trained on its own slightly-wrong states.
  **DAgger** (label the states it actually visits with the oracle's correct next,
  then retrain) lifts the faithful horizon ~6× in a single pass — the model
  visibly *recovers* back onto the real trajectory mid-rollout:

```text
closed-loop rollout, Oak's Lab (100 steps) — the engine tracks the model to score drift
timeline  (. = matches engine,  X = drift):
..XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX..........................................XXXXXXXX
                                                   └─ longest faithful run: 42 steps ─┘
```

The model is **not** part of the shipped artifact — it's a study of whether the
game's dynamics are *learnable* from the grid alone. They are. Pushing closed-loop
fidelity to hundreds of steps (more DAgger, a KV-cached rollout) and widening the
corpus to dialogue and battles is ongoing.

> **GPU path:** training needs a standard CPython + `torch` (CUDA). The MSYS
> Python that runs the interactive engine can't load torch — use a separate env
> (Miniconda / python.org). The oracle, corpus generator and CPU trainer are pure
> stdlib + NumPy and run anywhere.

### Update — a *walkable* world (the coordinate model)

The grid-redraw model above drifts: it repaints the whole screen every step (80
chances to err) and has to *count* the player's position in a field of identical
tiles. Two changes fixed both and made the world playable (`poc/coord_model.py`):

- **Predict the move, not the screen.** The model reads the static map + the
  player's `@x,y` + an action and emits only the **new coordinate**; a renderer
  draws the frame. The map can't corrupt, and position is explicit. A cheap
  **verifier** — the collision rule read straight off the grid (99.96% vs the
  engine) — catches the rare slip: a detect-and-correct loop.
- **Train on every tile, uniformly.** Random walks over-sample the center and
  starve the corners, so instead we **enumerate every reachable tile × action**.
  Big maps are sliced into **GB-screen chunks that connect Zelda-style**, so a
  single ~5M-param model walks the *whole* overworld — ~98% correct unaided
  across all 220 maps, with the engine handling doors, stairs and map
  connections.

Walk around inside it (WASD / arrows; movement is the net, transitions are the engine):
```
<conda-python> poc/coord_model.py play PALLET_TOWN
```

---

## Origins: the compression study (background)

*Where this began, before the world model: a measurement-driven study of how small
"the same game" can honestly get. It's what produced the faithful engine — which
then became the oracle above. Kept here because the findings are the reason the
project exists.*

### The thesis (and what the measurements actually showed)

Categories of a game's data split by **compressibility**, which turns out to run
*opposite* to raw size:

- **Visual data** (sprites, tilesets, map grids) is near its **entropy floor** —
  genuine information, barely compressible. This is the *binding constraint*.
- **Code, scripts, text, data tables** are **redundant** — boilerplate, templates,
  rule-derivable — and are where the real shrinking happens.

### Fidelity contract

| Class | Covers | Bar | Lossy budget? |
|-------|--------|-----|---------------|
| **VISUAL** | all art, sprites, **map layout** | a consistent 1bpp *inked* re-style — silhouettes faithful, shading dropped | Stylistic only — no per-asset approximation |
| **CONTENT** | text, audio | lossless (information, not pixels) | No, but highly compressible |
| **BEHAVIORAL** | mechanics, formulas, event logic, the numbers behind them | "a casual player can't tell" | **Yes** — this is the 90–95% lever |

### Key findings (all measured on the real disassembly, lossless unless noted)

- **The honest ROM budget is ~562 KB**, not 1 MB — 45% of the cartridge is empty
  bank padding. By compressibility class: visual ~185 KB (incompressible, *locked*),
  text 124 KB (very compressible — the biggest untapped lossless win), code+scripts
  ~205 KB (the behavioral lever), audio ~47 KB.
- **The quadtree-compression plan was disproven.** Dedup only pays when a reference
  is cheaper than the payload it replaces; a 2×2 pixel node (3–8 bits) can never be
  beaten by a ≥8-bit reference to it. *Sharing must happen at the bundle level.*
  The original ROM **already** shares tile art across maps, so the inflated ~270 KB
  baseline (and the 20 KB target derived from it) were wrong.
- **The block abstraction is load-bearing.** Expanding maps to raw tile fields and
  letting a compressor re-discover blocks *loses badly*. pokered's `.blk`-grid +
  blockset + renderer already *is* an efficient interpreter; referencing beats
  expand-and-recompress.
- **~25 KB is the robust lossless floor for all of Kanto's visuals** (three
  independent attacks converge: quadtree, custom 2D coders, tile-field). The 1bpp
  inked re-style roughly halves it again (mon sprites 72→36 KB, tileset art
  11.4→6 KB).
- **Feasibility verdict:** ~1/4 of the ROM (140 KB) is **impossible** while visuals
  stay pixel-exact — locked visuals + lossless text alone are ~160 KB. **~1/3
  (~190 KB) is the real floor**, and reaching it needs a ~6× collapse of the code
  mass. The binding constraint is the visual-lossless lock, not the code.

---

## Target architecture (see `DESIGN.md` §10–11)

- A **DSL is the single source of truth** for behavior + content (declarative);
  the runtime executes it and surfaces the whole game. Behavior is authored *once*.
- **Ship target = a tiny C core** (primitives + dispatch loop only); the bulk of
  the "engine" lives in the DSL the core interprets. **Dev mode = a Python
  interpreter of the same DSL.** Derive once → both targets fall out.
- **Rendering contract:** the engine's only output is a 160×144 1-bit framebuffer;
  the display is a swappable adapter the engine never knows about (terminal, PNG,
  SDL, web — all consume the same bits).
- **Overworld model:** the *tile* is the primitive (art + collision attach to
  tile-ids); the block grid is derived compression, not an authored object.
- The bytes we count are the **DSL + content blobs**; the runtime is fixed
  "hardware-equivalent" overhead (you never counted the Game Boy itself).

---

## Project layout

```
DESIGN.md          The authoritative spec — read this first.
poc/               Proof-of-concept engine + research scripts (Python, stdlib only).
  play.py            ← the playable terminal engine (Windows)
  play_pallet.py     viewport / camera / display adapters
  walk_pallet.py     movement / collision / camera-follow
  mapdata.py         general Gen I map loader (dims, tileset, warps, signs, NPCs)
  text_engine.py     font glyphs, text resolution, GB text box + animation
  render_pallet.py   first end-to-end map renderer (emits PNGs)
  roundtrip.py       quadtree round-trip POC (lossless tile codec)
  corpus.py          cross-corpus compression study (all 222 maps + 19 tilesets)
  experiments.py /   method bake-offs (lzma/bz2/zlib family proxies)
  *_coder.py         custom 2D coders for grids / art / blocksets
  census.py          logic census — sizing code by subsystem from pokered.map
  vm_poc.py          script-bytecode VM proof-of-concept
  scriptvm.py        overworld script/event VM (Oak follow, per-map script tables)
  pokemon.py moves.py trainers.py wild.py   Gen I data tables (species, moves +
                     type chart, trainer rosters, wild encounters)
  battle_intro.py battle_screen.py battle_hud.py   battle-start animation +
                     asm-faithful battle screen (1bpp sprites, HUD, menus)
  ascii_map.py       1-char-per-tile ASCII grid (debug view + world-model encoding)
  pokeworld.py gen_data.py nn.py train.py train_torch.py eval.py rollout.py dagger.py
                     learned world model — see "Teaching a model to be the engine"
  *.png              demo renders & contact sheets
```

### Ground-truth dependency

All PoCs read the **[pret/pokered](https://github.com/pret/pokered)**
disassembly as ground truth (formats, collision tables, scripts, art). It is **not**
vendored here. Clone it into `pokered-master/` at the repo root:

```bash
git clone https://github.com/pret/pokered.git pokered-master
```

A byte-exact build (sha1 `ea9bcae…`, via RGBDS 1.0.1) is what produces the
authoritative `pokered.map` figures used throughout `DESIGN.md`. Ground-truth rule
for the whole project: **never guess Gen I behavior — read the source.**

---

## Status & roadmap

**Done:** visual workstream (renderer + inked art direction), overworld engine
(movement, collision, warps, multi-map loading), NPCs, the text system, a script
VM, the full Pokémon / move / type / trainer / wild-encounter **data tables**,
asm-faithful **battle-start transitions + battle screen** (1bpp front/back
sprites, HP/status HUD, FIGHT·PKMN·ITEM·RUN and move menus), an **ASCII debug
grid** (1 char/tile, live), and a **learned world model** (see above).

**Open — the world model (active focus):**
1. **Push accuracy to 98–99%** — more `--resume` passes on the chunked corpus, for
   near-flawless *unaided* walking.
2. **Teach the model warps & connections** — fold the engine-handled transitions
   into the corpus with a map-id token, so the net predicts screen/map swaps
   itself (movement is learned; this makes it self-sufficient across maps).
3. **NPC dynamics (layer 2)** — shared movement physics + a per-entity wander
   policy; the oracle gains NPC movement first.
4. **Battles** — a full-battle-state *text* representation distilled from the
   engine; expose the RNG for a deterministic first pass, then learn the
   distribution.

**Open — engine / compression (origins):**
- **Code → DSL/bytecode** (the C-core primitive set); **text codec** (~124 KB →
  ~32 KB, the biggest lossless win); the battle **engine** (turn order, damage,
  effects, faint/exp/PP); save-struct shrink; menus.

---

*This is a research / re-derivation project built on the open-source pret/pokered
disassembly. Pokémon and Pokémon Red are trademarks of Nintendo / Game Freak /
The Pokémon Company; no copyrighted ROM data is included in this repository.*
