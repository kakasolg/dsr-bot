"""Zone 8 / Taurus ladder (`Missions._before`): from the first snapshot read with HP 0, no new ladder input. No game.

The real control.Pad runs on the fake vgamepad (pad_fakes), so what is checked is what the device was sent; time is faked.
20261101_002546: HP 0 at 82.53, then A at 82.66 · 84.02 · 85.38 on the corpse. Scan of the phases after the per-try check
(scratch, 11-01): death while turning → turn sticks + A; while climbing → stick up for the rest of LADDER_CLIMB_S (15 s);
after an A that didn't mount → the retry's settle taps.
Contract checked here: after the first HP-0 read the routine sends no A and no stick off centre and returns 'dead'. What
its neutral() leaves belongs to other owners (control.Pad): LB under force_guard (guardkeep), a sprint B younger than
SPRINT_MIN_HOLD_S (P-70, let go by a later release_due); while another thread holds the freeze its writes are dropped.
No snapshot is not death: it goes to Field.alive as at the routine's entry. Not checked: the time from the real death to
the read that shows it (one read late at best), and the entry settle before the first try (Field._settle, shared).
"""
import math
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("BOT_GAME", "dsr")

import control  # noqa: E402
import pad_fakes  # noqa: E402
from souls import missions as MS  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

A, LB, BB = "XUSB_GAMEPAD_A", "XUSB_GAMEPAD_LEFT_SHOULDER", "XUSB_GAMEPAD_B"
FOOT, FACE, TOP = (49.16, 15.97, -117.1), (50.5, 15.97, -117.1), 24.8
STEP = {"ladder": {"bottom": list(FOOT), "face": list(FACE), "top_y": TOP}}
FAILED: list[str] = []


def check(name: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        FAILED.append(name)


def scene(die=None, grab=True, heading_off=0.0, none_at=(), alive_on_none=True, before=None, other_freeze=False):
    """Run _before's ladder path once on a fake world driven by what the device holds.
    die(w, dev, pad) → True on the read where HP becomes 0. grab=False: A never mounts. none_at: read numbers that return
    no snapshot (Field.alive's own read included). other_freeze: another thread holds the pad freeze throughout.
    → (result, world, device record)"""
    clock = {"t": 1000.0}
    real = (time.time, time.sleep)
    time.time, time.sleep = (lambda: clock["t"]), (lambda s: clock.__setitem__("t", clock["t"] + s))
    vg = pad_fakes.install(Path(tempfile.mkdtemp(prefix="ladderdeath_")))
    pad = control.Pad()
    rec = vg.devices[-1]
    w = {"hp": 377, "y": FOOT[1], "anim": -1, "head": -math.pi / 2 + math.radians(heading_off), "reads": 0, "turns": 0,
         "climbs": 0, "a_reads": 0, "mark": None, "settles": [], "alive_calls": 0}

    def snap(r=5.0):
        dev = rec.dev
        w["reads"] += 1
        held = dev.state()
        if A in held["buttons"]:
            w["a_reads"] += 1
        if w["hp"] > 0 and die is not None and die(w, dev, pad):
            w["hp"], w["anim"] = 0, 6053
        if w["hp"] > 0:
            if A in held["buttons"] and grab and not 7000 <= w["anim"] < 7100:
                w["anim"] = 7010                                    # A taken: on the ladder
            if held["ly"] > 0.9 and 7000 <= w["anim"] < 7100:
                w["y"] += 0.5
                w["climbs"] += 1
            elif abs(held["lx"]) > 0.1:                             # turn 30° per read toward the ladder
                off = w["head"] + math.pi / 2
                w["head"] = -math.pi / 2 + math.copysign(max(abs(off) - math.radians(30), 0.0), off)
                w["turns"] += 1
        if w["hp"] <= 0 and w["mark"] is None:
            w["mark"] = len(rec.sent)                               # reports from here on came after the first HP-0 read
        if w["reads"] in none_at:
            return None
        return NS(player=NS(x=FOOT[0], y=w["y"], z=FOOT[2], anim=w["anim"], heading=w["head"], hp=w["hp"]), cam_yaw=0.0)

    def alive():                                                    # Field.alive's rule: a read, none = not alive
        w["alive_calls"] += 1
        s = snap()
        return alive_on_none if s is None else s.player.hp > 0

    m = MS.Missions.__new__(MS.Missions)
    m.log = lambda *a: None
    m.mv = NS(snap=snap, stick_to=lambda s, x, z, sc=1.0: (sc, 0.0), pad=pad)
    m.f = NS(walk_to=lambda *a, **k: "arrived", walk=lambda *a, **k: "arrived", alive=alive,
             _settle=lambda *a, **k: w["settles"].append(len(rec.sent)) or 0.0)
    hold, done, holder = threading.Event(), threading.Event(), None
    try:
        if other_freeze:
            def quitout():
                pad.freeze()
                hold.set()
                done.wait(5)
                pad.unfreeze()
            holder = threading.Thread(target=quitout, name="quitout")
            holder.start()
            hold.wait(5)
            w["freeze_at"] = len(rec.sent)
        if before is not None:
            before(pad)
        r = m._before(STEP, None, "t")
    finally:
        w["end"] = len(rec.sent)                                    # before the holder's unfreeze and pad.close()
        done.set()
        if holder is not None:
            holder.join(5)
        time.time, time.sleep = real
        w["due"] = {getattr(b, "name", b) for b in pad._due}
        pad.close()
    return r, w, rec


def after_mark(w, rec):
    return rec.sent[w["mark"]:] if w["mark"] is not None else []


def own_inputs(reports):
    """Reports that carry this routine's inputs: A, or the left stick off centre."""
    return [x for x in reports if A in x["buttons"] or abs(x["lx"]) > 1e-6 or abs(x["ly"]) > 1e-6]


def settles_after(w):
    return [i for i in w["settles"] if w["mark"] is not None and i >= w["mark"]]


def last(w, rec):
    """The device's last report from the routine (pad.close() sends one more after it)."""
    return rec.sent[w["end"] - 1]


def nothing_held(rep):
    return not rep["buttons"] and all(abs(rep[k]) < 1e-9 for k in ("lx", "ly", "rx", "ry", "lt", "rt"))


def died_clean(r, w, rec):
    return r == "dead" and w["mark"] is not None and not own_inputs(after_mark(w, rec)) and not settles_after(w)


# ── alive throughout: the normal path ───────────────────────────────────────
r, w, rec = scene(heading_off=90)
check("alive: turns, A, mounts, climbs → 'ok'",
      r == "ok" and w["y"] >= TOP - 0.3 and w["turns"] > 0 and any(A in x["buttons"] for x in rec.sent))
check("alive: snapshot reads not above the code before this change (31 here, alive() reads included)",
      w["reads"] <= 31)
print(f"     (normal path: {w['reads']} snapshot reads, {w['alive_calls']} alive() calls)")

# ── HP 0 while turning (179° off; HP 0 on the 2nd turn read) ─────────────────
r, w, rec = scene(heading_off=179, die=lambda w, d, p: w["turns"] >= 2)
check("HP 0 while turning → 'dead', no A and no stick after the first HP-0 read, no settle", died_clean(r, w, rec))
check("HP 0 while turning → device left with nothing held", nothing_held(last(w, rec)))

# ── HP 0 on the ladder ─────────────────────────────────────────────────────
r, w, rec = scene(die=lambda w, d, p: w["climbs"] >= 3)
check("HP 0 while climbing → 'dead', no stick-up after the first HP-0 read, no retry settle", died_clean(r, w, rec))
check("HP 0 while climbing → device left with nothing held", nothing_held(last(w, rec)))

# ── A not taken, HP 0 while waiting for the mount → no retry settle ──────────
r, w, rec = scene(grab=False, die=lambda w, d, p: w["a_reads"] >= 1 and A not in d.state()["buttons"])
check("A not taken, HP 0 before the retry → 'dead', no retry settle and no second A", died_clean(r, w, rec))

# ── HP 0 in the snapshot right before A (no turn needed) ─────────────────────
r, w, rec = scene(die=lambda w, d, p: w["reads"] >= 4)
check("HP 0 in the read before A → 'dead', A never pressed", r == "dead" and not any(A in x["buttons"] for x in rec.sent))

# ── no snapshot (read failure): Field.alive decides, as at the entry ─────────
r, w, rec = scene(none_at=(3, 4), alive_on_none=False)
check("no snapshot before A and alive() can't read either → 'dead' (existing policy), A never pressed",
      r == "dead" and w["hp"] > 0 and not any(A in x["buttons"] for x in rec.sent))
r, w, rec = scene(none_at=(3,), alive_on_none=True)
check("no snapshot before A, alive() reads HP > 0 → carries on, climbs ('ok')", r == "ok" and w["y"] >= TOP - 0.3)

# ── other owners' inputs: force_guard LB, a fresh sprint B, a quit-out freeze ─
def guard_on(pad):
    pad.force_guard = True                                          # guardkeep owns LB (souls/guardkeep)
r, w, rec = scene(die=lambda w, d, p: w["climbs"] >= 3, before=guard_on)
check("force_guard: HP 0 on the ladder → no A / stick after the HP-0 read; LB stays (guardkeep's)",
      died_clean(r, w, rec) and LB in last(w, rec)["buttons"] and not own_inputs([last(w, rec)]))

def sprint_at_death(w, d, p):
    if w["climbs"] >= 3:
        p.sprint(True)                                              # someone else's sprint, pressed just now
        return True
    return False
r, w, rec = scene(die=sprint_at_death)
check("sprint B 0 s old at the HP-0 read → no A / stick after it; B stays (P-70), its release left scheduled",
      died_clean(r, w, rec) and BB in last(w, rec)["buttons"] and BB in w["due"] and not own_inputs([last(w, rec)]))

r, w, rec = scene(die=lambda w, d, p: w["reads"] >= 30, other_freeze=True)
check("another thread holds the freeze → 'dead', nothing from this routine reached the device",
      r == "dead" and not [x for x in rec.sent[w["freeze_at"]:w["end"]] if x["th"] != "quitout"])

if __name__ == "__main__":
    if FAILED:
        print(f"{len(FAILED)} failed")
        sys.exit(1)
    print("all ok")
