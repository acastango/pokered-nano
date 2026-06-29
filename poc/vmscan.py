import re, collections, glob, os

# Evidence for the script/event VM opcode set: count recurring idioms across
# all per-map scripts. We tally (a) macro-style ops (CheckEvent, SetEvent, ...),
# (b) `call`/`predef`/`jp` targets, (c) `ld [mem], a` style engine-RAM pokes,
# (d) text-stream commands. Frequency drives which idioms deserve an opcode.
root = r"C:\Users\Anthony\pokered-nano\pokered-master\scripts"
files = glob.glob(os.path.join(root, "*.asm"))

macro_ops = collections.Counter()   # leading-token idioms (CheckEvent etc.)
call_tgts = collections.Counter()   # call/jp/predef targets
ld_writes = collections.Counter()   # ld [wXxx], a  -> which RAM var
text_cmds = collections.Counter()   # text_* / sound_* stream commands
totals = collections.Counter()

# known high-level script/event macro names (from macros/scripts/*.asm + usage)
known_macros = {
    "CheckEvent","CheckEventReuseA","CheckEventReuseHL","CheckEventHL",
    "CheckAndSetEvent","CheckAndResetEvent","SetEvent","SetEvents",
    "SetEventReuseHL","ResetEvent","ResetEvents","ResetEventReuseHL",
    "CheckBothEventsSet","CheckEitherEventSet","SetEventRange","ResetEventRange",
}
call_kw = {"call","jp","jr","predef","predef_jump","farcall","callfar","callab","callba"}

for f in files:
    for raw in open(f, encoding="utf-8", errors="replace"):
        line = raw.strip()
        if not line or line.startswith(";"):
            continue
        line = line.split(";",1)[0].strip()
        tok = line.split()
        if not tok:
            continue
        head = tok[0]
        totals["lines"] += 1
        # text-stream commands
        if head.startswith(("text_","sound_","script_")) or head in ("text","line","para","cont","done","prompt","next","page","dex"):
            text_cmds[head]+=1; continue
        # high-level event macros
        if head in known_macros:
            macro_ops[head]+=1; continue
        # call-like
        if head in call_kw:
            # target = last token (handles `jr z, .label`, `call PrintText`, `predef HideObject`)
            tgt = tok[-1]
            call_tgts[tgt]+=1
            macro_ops[head]+=1
            continue
        # engine-RAM write: ld [wXxx], a   /  ld [hXxx], a
        m = re.match(r"ld\s+\[(\w+)\]\s*,\s*a", line)
        if m:
            ld_writes[m.group(1)]+=1
            macro_ops["ld[mem],a"]+=1
            continue
        # generic opcode head (ld, cp, and, xor, ret, ...)
        macro_ops[head]+=1

def show(title, ctr, n=30):
    print(f"\n=== {title} (top {n}, of {sum(ctr.values())} total) ===")
    for k,v in ctr.most_common(n):
        print(f"  {v:5d}  {k}")

print(f"scanned {len(files)} script files, {totals['lines']} non-comment lines")
show("instruction/idiom heads", macro_ops)
show("call/jp/predef targets (the 'primitives' the scripts invoke)", call_tgts, 40)
show("engine-RAM vars written via `ld [x], a`", ld_writes, 30)
show("text-stream commands", text_cmds, 30)
