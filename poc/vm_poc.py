import re, collections

# VM POC: measure one real script (BluesHouse) — assembled Z80 script-code bytes
# (from pokered.map symbol-delta sizing) vs a hand-encoded bytecode of the SAME
# logic. We compare SCRIPT CODE only; the text strings themselves (_Foo in the
# text bank) are CONTENT, unchanged by the VM, and excluded from both sides.
mp = open(r"C:\Users\Anthony\pokered-nano\pokered-master\pokered.map",
          encoding="utf-8", errors="replace").read()

region_re = re.compile(r'^(ROM0|ROMX|SRAM|WRAM0|WRAM|HRAM|VRAM|OAM) bank')
sec_re = re.compile(r'SECTION: \$([0-9a-fA-F]+)(?:-\$([0-9a-fA-F]+))? \(\$([0-9a-fA-F]+) (?:bytes|byte)\) \["([^"]*)"\]')
sym_re = re.compile(r'^\s*\$([0-9a-fA-F]+) = (\S+)')

items = []
cur_region = None; cur_sec = None
for line in mp.splitlines():
    rm = region_re.match(line.strip())
    if rm: cur_region = rm.group(1); cur_sec=None; continue
    sm = sec_re.search(line)
    if sm:
        start=int(sm.group(1),16); nbytes=int(sm.group(3),16)
        cur_sec=(start,start+nbytes,sm.group(4),cur_region); continue
    ym = sym_re.match(line)
    if ym and cur_sec and cur_sec[3] in ("ROM0","ROMX"):
        items.append((int(ym.group(1),16), ym.group(2), cur_sec))

# size each symbol = gap to next symbol in same section (else to section end)
bysec=collections.defaultdict(list)
for a,n,s in items: bysec[s].append((a,n))
size={}
for s,syms in bysec.items():
    syms.sort(); end=s[1]
    for i,(a,n) in enumerate(syms):
        nxt = syms[i+1][0] if i+1<len(syms) else end
        size[n]=max(0,nxt-a)

# BluesHouse script-code symbols (the executable script logic + the dispatch/
# pointer tables + the text-command wrappers). NOT the _Foo text strings.
code_syms = [
    "BluesHouse_Script",
    "BluesHouseDefaultScript","BluesHouseNoopScript",
    "BluesHouseDaisySittingText",          # the text_asm logic block
    # text-command wrappers (each text_far=4B + text_end=1B; GotMapText also +1 sound)
    "BluesHouseDaisyRivalAtLabText","BluesHouseDaisyOfferMapText","GotMapText",
    "BluesHouseDaisyBagFullText","BluesHouseDaisyUseMapText",
    "BluesHouseDaisyWalkingText","BluesHouseTownMapText",
]
# pointer tables don't get their own delta symbol if unlabeled internally; include
# the table label sizes we can see:
table_syms = ["BluesHouse_ScriptPointers","BluesHouse_TextPointers"]

print("=== assembled Z80 'now' (pokered.map symbol-delta) ===")
now=0
for n in code_syms+table_syms:
    b=size.get(n)
    if b is None:
        print(f"  (missing) {n}")
    else:
        print(f"  {b:4d} B  {n}"); now+=b
print(f"  ----\n  NOW total: {now} B  (script code, excl. text strings)\n")

# ---- hand-encoded bytecode of the SAME logic ----
# opcode byte costs from the proposed ISA. We list each op with its byte size and
# a comment tracing it to the original source line(s).
prog = [
 # --- dispatcher: BluesHouse_Script -> run current script state ---
 ("ENABLE_TEXTBOX",        1, "call EnableAutoTextBoxDrawing (header flag)"),
 ("DISPATCH wCurScript",   1, "ld hl,ScriptPointers/ld a,[cur]/jp CallFunctionInTable -> implicit"),
 # --- BluesHouseDefaultScript ---
 ("SETEVENT ENTERED",      3, "SetEvent EVENT_ENTERED_BLUES_HOUSE"),
 ("SETSCRIPT NOOP",        2, "ld a,NOOP/ld [wCurScript],a"),
 ("END",                   1, "ret"),
 # --- BluesHouseNoopScript ---
 ("END",                   1, "ret  (noop state)"),
 # --- BluesHouseDaisySittingText (the text_asm decision tree) ---
 ("IFEVENT GOT_TOWN_MAP -> got",   4, "CheckEvent GOT_TOWN_MAP / jr nz .got_town_map"),
 ("IFEVENT GOT_POKEDEX  -> give",  4, "CheckEvent GOT_POKEDEX / jr nz .give_town_map"),
 ("PRINT RivalAtLab",              3, "ld hl,...RivalAtLab / call PrintText"),
 ("JUMP done",                     2, "jr .done"),
 # .give_town_map
 ("PRINT OfferMap",                3, "ld hl,...OfferMap / call PrintText"),
 ("GIVE TOWN_MAP,1 -> bagfull",    4, "lb bc,TOWN_MAP,1 / call GiveItem / jr nc .bag_full"),
 ("HIDE DAISY_OBJ",                2, "ld a,TOGGLE.../ld [wToggleableObjectIndex],a / predef HideObject"),
 ("PRINT GotMap",                  3, "ld hl,GotMapText / call PrintText"),
 ("SETEVENT GOT_TOWN_MAP",         3, "SetEvent EVENT_GOT_TOWN_MAP"),
 ("JUMP done",                     2, "jr .done"),
 # .got_town_map
 ("PRINT UseMap",                  3, "ld hl,...UseMap / call PrintText"),
 ("JUMP done",                     2, "jr .done"),
 # .bag_full
 ("PRINT BagFull",                 3, "ld hl,...BagFull / call PrintText"),
 # .done
 ("END",                           1, "jp TextScriptEnd"),
 # --- text-command wrappers that remain (PRINT refs above already point at the
 #     text strings; the standalone text entries below are plain text displays
 #     reachable via TextPointers, encoded as PRINT+END pairs) ---
 ("PRINT DaisyWalking; END",       4, "BluesHouseDaisyWalkingText: text_far+text_end"),
 ("PRINT TownMap; END",            4, "BluesHouseTownMapText: text_far+text_end"),
 # GotMap/RivalAtLab/OfferMap/BagFull/UseMap are referenced by PRINT inside the
 # logic above, so they don't need separate wrapper bytes (the VM PRINT op takes
 # the text ref directly) — this is itself a saving vs the Z80 wrapper-per-string.
 # GotMap needs its sound; fold into PRINT flag or a SFX op:
 ("SFX get_key_item",              2, "GotMapText had sound_get_key_item"),
]
bc = sum(b for _,b,_ in prog)
print("=== hand-encoded bytecode (same logic) ===")
for op,b,why in prog:
    print(f"  {b:2d} B  {op:32} ; {why}")
print(f"  ----\n  BYTECODE total: {bc} B")
print(f"\n  ratio: {now/bc:.2f}x   (now {now} B -> bytecode {bc} B, "
      f"{100*(now-bc)/now:.0f}% smaller)")

# ---- DENOMINATOR: how big is the script-code layer game-wide? ----
# Sum symbol-delta sizes for script-code-ish symbols across the whole ROM:
#  - script logic / dispatch:    *Script, *_Script
#  - text-command wrappers:      *Text  (NOT _Text prose, which is the text bank)
#  - dispatch/pointer tables:    *ScriptPointers, *TextPointers
# This is the mass the script VM would replace (excludes the actual prose).
script_total=0; wrapper_total=0; logic_total=0; tbl_total=0
nsym=0
for n,b in size.items():
    if n.startswith("_"):           # _Foo = prose in the text bank: skip
        continue
    low=n
    if n.endswith("ScriptPointers") or n.endswith("TextPointers"):
        tbl_total+=b; script_total+=b; nsym+=1
    elif "Script" in n:
        logic_total+=b; script_total+=b; nsym+=1
    elif n.endswith("Text"):
        wrapper_total+=b; script_total+=b; nsym+=1

print("\n=== DENOMINATOR: script-code layer, game-wide (pokered.map) ===")
print(f"  script logic/dispatch (*Script)    : {logic_total/1024:6.1f} KB")
print(f"  text-command wrappers (*Text)      : {wrapper_total/1024:6.1f} KB")
print(f"  dispatch/pointer tables            : {tbl_total/1024:6.1f} KB")
print(f"  ---- script-code layer TOTAL       : {script_total/1024:6.1f} KB "
      f"({nsym} symbols)")
print(f"\n  At the measured 1.60x: {script_total/1024:.1f} KB -> "
      f"{script_total/1024/1.6:.1f} KB  (saves ~{script_total*(1-1/1.6)/1024:.1f} KB)")
print(f"  vs total ROM 561.9 KB: this layer is "
      f"{100*script_total/1024/561.9:.1f}% of the ROM")
