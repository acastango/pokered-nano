# pokered-nano

**Re-deriving Pokémon Red from first principles into a micro/nano-sized, full-fidelity version.**

The goal is not a byte-exact port. It's the *smallest artifact that still **looks
exactly like** Red and **plays like** Red* — keep everything a player perceives,
discard the machinery they don't. Along the way the project is a measurement-driven
study of where the bytes of a 1989-era game actually live, and how small "the same
game" can honestly get.

> The authoritative design doc is **[`DESIGN.md`](DESIGN.md)** — read it first for
> the full reasoning, measurements, and decisions. This README is the overview.

---

## What works today

A **playable terminal engine** rendered as a 1-bit framebuffer — the real Game Boy
screen (160×144), drawn pixel-by-pixel into your terminal.

Here is Pallet Town, captured straight from the engine's `block` display adapter
(player + NPCs composited). This is the *full* 160×144 GB screen: half-block
glyphs (`▀ ▄ █`) pack a vertical 1×2 pixel pair into each character cell, so 80×72
cells render every pixel. You can make out the buildings and doors, the round
tree-border, fences and signs (it's wide — scroll right to see the rest):

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

## The thesis (and what the measurements actually showed)

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
(movement, collision, warps, multi-map loading), NPCs, the text system.

**Open (in rough priority):**
1. **Code → DSL/bytecode** — the deciding lever; defines the C-core primitive set
   and how battle/overworld/menu mechanics lower into the DSL.
2. **Text codec** — ~124 KB → ~32 KB via a tuned PPM/word-dictionary coder
   (biggest lossless win, zero fidelity cost).
3. Save-struct shrink (remove invisible DV/EV systems), menus, battle system,
   NPC wandering, warp/door transition polish.

---

*This is a research / re-derivation project built on the open-source pret/pokered
disassembly. Pokémon and Pokémon Red are trademarks of Nintendo / Game Freak /
The Pokémon Company; no copyrighted ROM data is included in this repository.*
