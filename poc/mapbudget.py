import re, sys, collections

# Parse rgbds .map file, aggregate SECTION bytes by category.
mapfile = r"C:\Users\Anthony\pokered-nano\pokered-master\pokered.map"
txt = open(mapfile, encoding="utf-8", errors="replace").read()

# SECTION: $XXXX-$YYYY ($ZZZZ bytes) ["name"]   or  ($0000 bytes)
sec_re = re.compile(r'SECTION: \$[0-9a-fA-F]+(?:-\$[0-9a-fA-F]+)? \(\$([0-9a-fA-F]+) (?:bytes|byte)\) \["([^"]*)"\]')

# Track current memory region; only count ROM0/ROMX (real ROM bytes).
region_re = re.compile(r'^(ROM0|ROMX|SRAM|WRAM0|WRAM|HRAM|VRAM|OAM) bank #?\d*', re.M)
secs = []  # (name, bytes)
cur_region = None
for line in txt.splitlines():
    rm = region_re.match(line.strip())
    if rm:
        cur_region = rm.group(1)
        continue
    m = sec_re.search(line)
    if m and cur_region in ("ROM0", "ROMX"):
        secs.append((m.group(2), int(m.group(1), 16)))

def cat(name):
    n = name.lower()
    if name.startswith("Pics"): return "ART: Pokemon sprites (.pic)"
    if name.startswith("Tilesets"): return "ART: tilesets+blocksets (2bpp)"
    if name.startswith("NPC Sprites") or name.startswith("Sprites"): return "ART: overworld NPC sprites"
    if "trainer" in n and ("pic" in n): return "ART: Trainer sprites (.pic)"
    if name.startswith("Music") or name.startswith("SFX") or "sound effect" in n or "audio engine" in n or "music header" in n or "sfx header" in n or "low health alarm" in n or "noise instruments" in n:
        return "Audio (music+sfx+engine+headers)"
    if name.startswith("Text") or "pokedex text" in n or "pokédex text" in n or "move names" in n:
        return "Text (dialogue/dex/names)"
    if name.startswith("Maps") or name.startswith("Map "): return "Maps (map data sections)"
    if "font" in n: return "Font graphics"
    if name in ("Home","High Home","NULL","Header") or name.startswith("rst") or name in ("vblank","lcd","timer","serial","joypad"):
        return "Home/ROM0 core"
    return "Code+data (engine/scripts/tables/etc)"

agg = collections.Counter()
cnt = collections.Counter()
for name, b in secs:
    c = cat(name)
    agg[c] += b
    cnt[c] += 1

total = sum(agg.values())
print(f"parsed {len(secs)} sections, total {total} bytes ({total/1024:.1f} KB)\n")
print(f"{'category':42} {'KB':>8} {'%':>6} {'#sec':>5}")
print("-"*65)
for c, b in agg.most_common():
    print(f"{c:42} {b/1024:8.1f} {100*b/total:6.1f} {cnt[c]:5d}")
print("-"*65)
print(f"{'TOTAL USED':42} {total/1024:8.1f}")

# Show the big "Code+data" sections individually to understand the elephant
print("\n=== top 30 sections in 'Code+data' bucket ===")
big = [(n,b) for (n,b) in secs if cat(n)=="Code+data (engine/scripts/tables/etc)"]
for n,b in sorted(big, key=lambda x:-x[1])[:30]:
    print(f"  {b/1024:7.1f} KB  {n}")
