import re, collections

# Logic census: attribute ROM bytes to subsystems via symbol-delta sizing.
# rgbds .map lists, per bank/section, symbols as "$ADDR = Name". Size of a symbol
# ~= (next symbol addr) - (this addr) within the same section; last symbol runs to
# section end. ROM bytes only (ROM0/ROMX). Bucketed by keyword on symbol name.
mp = open(r"C:\Users\Anthony\pokered-nano\pokered-master\pokered.map",
          encoding="utf-8", errors="replace").read()

region_re = re.compile(r'^(ROM0|ROMX|SRAM|WRAM0|WRAM|HRAM|VRAM|OAM) bank', )
sec_re = re.compile(r'SECTION: \$([0-9a-fA-F]+)(?:-\$([0-9a-fA-F]+))? \(\$([0-9a-fA-F]+) (?:bytes|byte)\) \["([^"]*)"\]')
sym_re = re.compile(r'^\s*\$([0-9a-fA-F]+) = (\S+)')

# Build flat list of (addr, name, section, region) plus section end bounds.
items = []          # (addr, name, secname)
sec_bounds = []     # (start, end, secname, region)
cur_region = None
cur_sec = None
for line in mp.splitlines():
    rm = region_re.match(line.strip())
    if rm:
        cur_region = rm.group(1); cur_sec = None; continue
    sm = sec_re.search(line)
    if sm:
        start = int(sm.group(1),16)
        nbytes = int(sm.group(3),16)
        name = sm.group(4)
        end = start + nbytes
        cur_sec = (start, end, name, cur_region)
        if cur_region in ("ROM0","ROMX") and nbytes>0:
            sec_bounds.append(cur_sec)
        continue
    ym = sym_re.match(line)
    if ym and cur_sec and cur_sec[3] in ("ROM0","ROMX"):
        items.append((int(ym.group(1),16), ym.group(2), cur_sec))

# Size each symbol = gap to next symbol in same section, else to section end.
# Group symbols by section, sort, diff.
bysec = collections.defaultdict(list)
for addr,name,sec in items:
    bysec[sec].append((addr,name))

sized = []  # (size, name, secname)
covered = collections.Counter()  # bytes attributed per section
for sec, syms in bysec.items():
    start,end,secname,region = sec
    syms.sort()
    for i,(addr,name) in enumerate(syms):
        nxt = syms[i+1][0] if i+1 < len(syms) else end
        sz = max(0, nxt-addr)
        sized.append((sz,name,secname))
        covered[sec]+=sz

def bucket(name, sec):
    n = name.lower(); s = sec.lower()
    # data-ish sections first
    if sec.startswith("Pics") or "pic" in n: return "gfx: pokemon/trainer pics"
    if sec.startswith("Tilesets") or sec.startswith("NPC Sprites") or "tileset" in n or "blockset" in n: return "gfx: tilesets/sprites"
    if sec.startswith("Text") or "_text" in n or sec.startswith("Pok") and "text" in s: return "text"
    if sec.startswith("Music") or sec.startswith("SFX") or "audio" in n or "music" in n or "sfx" in n or "sound" in n: return "audio"
    if sec.startswith("Maps") or "_blocks" in n or "_object" in n or "mapheader" in n or "_h:" in n: return "maps: data(grids/headers/objects)"
    # behavioral / code buckets by symbol keyword
    if any(k in n for k in ("battle","move","ai_","trainerai","damage","crit","typeeffect","statuseffect")): return "code: battle"
    if any(k in n for k in ("overworld","map","warp","connection","sprite","movement","collision","tile","door","ledge","grass","walk")): return "code: overworld/map engine"
    if any(k in n for k in ("menu","textbox","start_menu","party","cursor","print","drawhp","hpbar","scroll","window")): return "code: menus/UI"
    if any(k in n for k in ("pokedex","dex")): return "code: pokedex"
    if any(k in n for k in ("item","bag","mart","money","tms","tm_","hm_")): return "code: items/shop"
    if any(k in n for k in ("pokemon","mon","evol","learn","exp","stat","party","status_screen","cry","name")): return "code: pokemon mgmt/stats"
    if any(k in n for k in ("save","sram","box","bank","backup")): return "code: save/box/SRAM"
    if any(k in n for k in ("link","cable","trade","serial")): return "code: link/trade"
    if any(k in n for k in ("audio","song","note","channel","music","sound")): return "audio engine"
    if any(k in n for k in ("script","engine","oak","intro","title","credits","slot","fish","badge")): return "code: scripts/cutscene/misc"
    return "code: misc/uncategorized"

agg = collections.Counter()
for sz,name,sec in sized:
    agg[bucket(name,sec)] += sz

# account uncovered bytes (sections with no symbols, e.g. pure INCBIN data)
uncovered = collections.Counter()
for sec in sec_bounds:
    start,end,secname,region = sec
    gap = (end-start) - covered.get(sec,0)
    if gap>0:
        uncovered[bucket("", secname)] += gap
for k,v in uncovered.items():
    agg[k]+=v

total = sum(agg.values())
print(f"census total: {total/1024:.1f} KB across {len(sized)} symbols + INCBIN remainder\n")
print(f"{'bucket':42}{'KB':>8}{'%':>7}")
print("-"*58)
for k,v in agg.most_common():
    print(f"{k:42}{v/1024:8.1f}{100*v/total:7.1f}")

print("\n=== top 30 individual symbols by size ===")
for sz,name,sec in sorted(sized, reverse=True)[:30]:
    print(f"  {sz/1024:6.2f}KB  {name:38} [{sec}]")

# Drill into the misc/uncategorized code bucket: what's actually in there?
print("\n=== top 50 symbols in code: misc/uncategorized ===")
misc = [(sz,name,sec) for sz,name,sec in sized if bucket(name,sec)=="code: misc/uncategorized"]
for sz,name,sec in sorted(misc, reverse=True)[:50]:
    print(f"  {sz/1024:6.2f}KB  {name:38} [{sec}]")
print(f"  ...{len(misc)} symbols total in misc, "
      f"{sum(s for s,_,_ in misc)/1024:.1f}KB")
