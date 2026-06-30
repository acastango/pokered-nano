#!/usr/bin/env python3
"""
pokered-nano — tiny script bytecode VM (seed of DESIGN s5a).

Gen I map scripts are a per-map state machine run every overworld step
(scripts/<Map>.asm). This re-expresses one such script as a compact bytecode
the engine interprets, instead of inline Z80. The interpreter lives in play.py
(it needs engine state); this module is the ISA: opcodes, a label-resolving
assembler, and the Pallet Town "Hey! Wait!" program.

Blocking ops (TEXT, MOVENPC, WAIT) suspend the VM; the engine resumes it when
the wait clears (dialog closed, NPC arrived, timer elapsed).
"""

# --- opcodes ---------------------------------------------------------------
OP_END     = 0x00
OP_IFSET   = 0x01   # flag(1), addr(2)  : if event flag set -> jump
OP_IFYGT   = 0x02   # y(1), addr(2)     : if player YCoord > y -> jump
OP_LOCK    = 0x03
OP_RELEASE = 0x04
OP_FACEP   = 0x05   # dir(1)            : set player facing
OP_TEXT    = 0x06   # textid(1)         : show dialogue (blocks)
OP_SHOW    = 0x07   # npc(1)            : make NPC visible
OP_HIDE    = 0x08   # npc(1)            : hide NPC
OP_FACENPC = 0x09   # npc(1), dir(1)
OP_MOVENPC = 0x0A   # npc(1), dir(1), count(1)  : scripted walk (blocks)
OP_SETFLAG = 0x0B   # flag(1)
OP_SFX     = 0x0C   # id(1)             : sound (stubbed — no audio yet)
OP_WAIT    = 0x0D   # frames(1)         : pause (blocks)
OP_JUMP    = 0x0E   # addr(2)
OP_MOVEPLY = 0x0F   # dir(1), count(1)  : scripted player walk (blocks)
OP_STEPBOTH = 0x10  # npc(1), oakdir(1), plydir(1) : both step 1 cell (blocks)
OP_SETPLY  = 0x11   # x(1), y(1)        : place the player at a cell
OP_WARP    = 0x12   # ()                : warp via the warp under the player

# arg layout per opcode ("addr" = 2 bytes, everything else = 1)
ARGS = {
    OP_END: (), OP_LOCK: (), OP_RELEASE: (), OP_WARP: (),
    OP_IFSET: ("b", "addr"), OP_IFYGT: ("b", "addr"), OP_JUMP: ("addr",),
    OP_FACEP: ("b",), OP_TEXT: ("b",), OP_SHOW: ("b",), OP_HIDE: ("b",),
    OP_FACENPC: ("b", "b"), OP_MOVENPC: ("b", "b", "b"),
    OP_SETFLAG: ("b",), OP_SFX: ("b",), OP_WAIT: ("b",),
    OP_MOVEPLY: ("b", "b"), OP_STEPBOTH: ("b", "b", "b"), OP_SETPLY: ("b", "b"),
}

# direction bytes
D_DOWN, D_UP, D_LEFT, D_RIGHT = 0, 1, 2, 3
DIR_NAME = ["down", "up", "left", "right"]


class ScriptProgram:
    """A compiled map script: bytecode + its symbol tables (text far-labels and
    event-flag names referenced by id in the bytecode)."""
    def __init__(self, code, texts=(), flags=()):
        self.code = code
        self.texts = list(texts)
        self.flags = list(flags)


class ScriptVM:
    """Execution state for a ScriptProgram. The interpreter (in play.py)
    advances `pc`; `block` is a no-arg predicate that, while it returns False,
    keeps the VM suspended (waiting on a dialog/NPC/timer)."""
    def __init__(self, prog):
        self.prog = prog
        self.code = prog.code
        self.pc = 0
        self.done = False
        self.block = None
        self.wait = 0


def assemble(program):
    """program: list of (OP, *args) and ("label", name). Jump args may be a
    label name (str) resolved to its byte offset. Returns bytes."""
    # pass 1: byte offset of each label
    labels, off = {}, 0
    for item in program:
        if item[0] == "label":
            labels[item[1]] = off
            continue
        op = item[0]
        off += 1 + sum(2 if s == "addr" else 1 for s in ARGS[op])
    # pass 2: emit
    out = bytearray()
    for item in program:
        if item[0] == "label":
            continue
        op = item[0]
        out.append(op)
        for spec, val in zip(ARGS[op], item[1:]):
            if spec == "addr":
                a = labels[val] if isinstance(val, str) else val
                out += bytes((a & 0xFF, (a >> 8) & 0xFF))
            else:
                out.append(val & 0xFF)
    return bytes(out)


# --- symbol tables for the Pallet "Hey! Wait!" program ---------------------
# text ids -> the far-text labels in text/PalletTown.asm
PALLET_TEXTS = ["_PalletTownOakHeyWaitDontGoOutText",
                "_PalletTownOakItsUnsafeText"]
# event flag ids
PALLET_FLAGS = ["FOLLOWED_OAK"]
# npc indices (into the map's object list); Oak is object 0 in PalletTown
OAK = 0

# The follow-to-lab path (data/.../auto_movement.asm RLEList_ProfOakWalkToLab):
# Oak leads; the player follows one cell behind (player dir = Oak's prev dir).
_OAK_PATH = ([D_DOWN]*5 + [D_LEFT] + [D_DOWN]*5 + [D_RIGHT]*3 + [D_UP])
_PLY_PATH = [D_DOWN] + _OAK_PATH[:-1]

# PalletTownDefaultScript + the full OakHeyWait -> FollowOakToLab chain:
PALLET_OAK_SCRIPT = assemble([
    (OP_IFSET, 0, "end"),         # FOLLOWED_OAK already set -> nothing
    (OP_IFYGT, 1, "end"),         # not at the north exit (YCoord > 1) -> nothing
    (OP_LOCK,),                   # freeze the player
    (OP_SETPLY, 10, 1),           # align to the left tile of the northern path
    (OP_FACEP, D_DOWN),
    (OP_SFX, 0),                  # "OAK appears" music (no audio yet)
    (OP_TEXT, 0),                 # "OAK: Hey! Wait! Don't go out!"
    (OP_SHOW, OAK),               # Oak appears at his spot...
    (OP_MOVENPC, OAK, D_RIGHT, 2),   # ...and walks over and up to the player
    (OP_MOVENPC, OAK, D_UP, 3),
    (OP_FACENPC, OAK, D_UP),
    (OP_FACEP, D_DOWN),
    (OP_TEXT, 1),                 # "It's unsafe! ... Here, come with me!"
    # follow Oak down to the lab (Oak + player step together)
    *[(OP_STEPBOTH, OAK, od, pd) for od, pd in zip(_OAK_PATH, _PLY_PATH)],
    (OP_HIDE, OAK),               # Oak enters the lab
    (OP_MOVEPLY, D_UP, 1),        # player steps onto the lab door
    (OP_SETFLAG, 0),              # FOLLOWED_OAK = done
    (OP_RELEASE,),
    (OP_WARP,),                   # ...and into Oak's lab
    ("label", "end"),
    (OP_END,),
])


# --- per-map registries (the generalized "script tables") ------------------
# MAP_SCRIPTS: map_const -> ScriptProgram run as that map's step-script. Only
# maps with an authored cutscene need one; dialogue for ALL maps is data-driven
# from <Map>_TextPointers (see text_engine.resolve_text), not registered here.
# Re-authoring more maps' Z80 cutscenes as bytecode extends this table.
MAP_SCRIPTS = {
    "PALLET_TOWN": ScriptProgram(PALLET_OAK_SCRIPT, PALLET_TEXTS, PALLET_FLAGS),
}

# NPCs the original reveals via a script (object index by spawn cell), hidden
# until SHOWn.
MAP_HIDDEN = {
    "PALLET_TOWN": [(8, 5)],      # Oak
}
