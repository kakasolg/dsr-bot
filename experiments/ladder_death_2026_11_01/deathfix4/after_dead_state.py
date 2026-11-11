"""Scratch (not a repo test): pad / fake-device state right after Missions._before returns 'dead', then after the pad calls
run.py's finally makes (replayed in order from reading run.py — not run.py itself), then after an extra release_due (assumed).
Real control.Pad on tests/pad_fakes; fake clock. Run: python <this> <repo>"""
import math
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace as NS

REPO = Path(sys.argv[1]).resolve()
sys.path[:0] = [str(REPO), str(REPO / "tests")]
os.environ.setdefault("BOT_GAME", "dsr")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
import control  # noqa: E402
import pad_fakes  # noqa: E402
from souls import missions as MS  # noqa: E402

A, LB, BB = "XUSB_GAMEPAD_A", "XUSB_GAMEPAD_LEFT_SHOULDER", "XUSB_GAMEPAD_B"
FOOT, FACE, TOP = (49.16, 15.97, -117.1), (50.5, 15.97, -117.1), 24.8
STEP = {"ladder": {"bottom": list(FOOT), "face": list(FACE), "top_y": TOP}}
clock = {"t": 1000.0}
time.time = lambda: clock["t"]
time.sleep = lambda s: clock.__setitem__("t", clock["t"] + s)


def short(st):
    b = sorted(x.replace("XUSB_GAMEPAD_", "") for x in st["buttons"])
    return f"btn={b or '-'} L=({st['lx']:.2f},{st['ly']:.2f}) R=({st['rx']:.2f},{st['ry']:.2f})"


def internal(pad):
    return (f"due={sorted(getattr(b, 'name', b).replace('XUSB_GAMEPAD_', '') + f'@{t - 1000:.2f}' for b, t in pad._due.items())} "
            f"b_since={None if pad._b_since is None else round(pad._b_since - 1000, 2)} force_guard={pad.force_guard} "
            f"kept={pad._kept} guard_want={pad._guard_want} frozen_by={'other' if pad._frozen_by not in (None, threading.get_ident()) else pad._frozen_by}")


def run(name, mode, gap=1.0):
    vg = pad_fakes.install(Path(tempfile.mkdtemp(prefix="afterdead_")))
    pad = control.Pad()
    rec = vg.devices[-1]
    calls = []                                       # (t, thread, method, sent?) in order
    for meth in ("neutral", "move", "tap", "release_due", "sprint", "keep_guard", "unkeep", "freeze", "unfreeze"):
        orig = getattr(pad, meth)
        def wrap(*a, _o=orig, _m=meth, **k):
            n0 = len(rec.sent)
            r = _o(*a, **k)
            calls.append((round(clock["t"] - 1000, 2), threading.current_thread().name, _m, len(rec.sent) > n0))
            return r
        setattr(pad, meth, wrap)
    w = {"hp": 377, "y": FOOT[1], "anim": -1, "climbs": 0, "mark": None, "mark_call": None}
    holder = {"th": None, "go": threading.Event(), "ready": threading.Event()}

    def die(dev):
        w["reads"] = w.get("reads", 0) + 1
        if mode == "freeze":
            return w["reads"] >= 30                   # nothing mounts while frozen (A dropped) — HP 0 on read 30
        if w["climbs"] < 3:
            return False
        if mode == "sprint":                          # B pressed 0.0 s before the HP-0 read, its release asked for at once
            t = threading.Thread(target=lambda: (pad.sprint(True), pad.sprint(False)), name="sprinter")
            t.start(); t.join()
        if mode == "keep":                            # guardkeep's call (souls/guardkeep.step): LB until now + 1.5
            t = threading.Thread(target=lambda: pad.keep_guard(time.time() + 1.5), name="guardkeep")
            t.start(); t.join()
        return True

    def snap(r=5.0):
        dev = rec.dev
        st = dev.state()
        if w["hp"] > 0 and die(dev):
            w["hp"], w["anim"] = 0, 6053
        if w["hp"] > 0:
            if A in st["buttons"] and not 7000 <= w["anim"] < 7100:
                w["anim"] = 7010
            if st["ly"] > 0.9 and 7000 <= w["anim"] < 7100:
                w["y"] += 0.5
                w["climbs"] += 1
        if w["hp"] <= 0 and w["mark"] is None:
            w["mark"], w["mark_call"] = len(rec.sent), len(calls)
        return NS(player=NS(x=FOOT[0], y=w["y"], z=FOOT[2], anim=w["anim"], heading=-math.pi / 2, hp=w["hp"]), cam_yaw=0.0)

    m = MS.Missions.__new__(MS.Missions)
    m.log = lambda *a: None
    m.mv = NS(snap=snap, stick_to=lambda s, x, z, sc=1.0: (sc, 0.0), pad=pad)
    m.f = NS(walk_to=lambda *a, **k: "arrived", walk=lambda *a, **k: "arrived",
             alive=lambda: snap().player.hp > 0, _settle=lambda *a, **k: 0.0)
    if mode == "freeze":                              # souls/watch.py quit-out: freeze … finally neutral → unfreeze
        def quitout():
            pad.freeze()
            holder["ready"].set()
            holder["go"].wait(5)
            pad.neutral()
            pad.unfreeze()
        holder["th"] = threading.Thread(target=quitout, name="quitout")
        holder["th"].start()
        holder["ready"].wait(5)
    if mode == "force":
        pad.force_guard = True                        # the setter (inf) — used by tests only; bot code sets it False only
    r = m._before(STEP, None, "t")
    n_ret = len(rec.sent)
    print(f"\n### {name}: _before → {r!r}")
    print("  calls after the first HP-0 read (t, thread, method, report sent?):")
    for c in calls[w["mark_call"]:]:
        print("   ", c)
    print(f"  reports after the HP-0 read: {[short(x) + ' th=' + x['th'] for x in rec.sent[w['mark']:n_ret]] or '(none)'}")
    print(f"  A  device now : {short(rec.dev.state())}")
    print(f"     last report: {short(rec.sent[n_ret - 1])} (th={rec.sent[n_ret - 1]['th']})")
    print(f"     pad        : {internal(pad)}")

    # pure time passing, nobody calls the pad
    time.sleep(gap)
    if mode == "keep":
        time.sleep(2.0)                               # past the keep_guard window (1.5 s), still no pad call
    print(f"  +{gap + (2.0 if mode == 'keep' else 0.0):.1f} s, no pad call: device {short(rec.dev.state())} · {internal(pad)} · reports +{len(rec.sent) - n_ret}")

    if mode == "freeze":                              # the quit-out holder finishes its own cleanup (watch.py finally)
        holder["go"].set(); holder["th"].join(5)
        print(f"  holder's finally neutral → unfreeze: device {short(rec.dev.state())} · {internal(pad)}")

    # B: run.py taurus path after 'died' — finally: pad.neutral(); waits (esc, alive, wait_respawn: snaps + sleeps, no pad
    # call); gk.stop() = force_guard False + unkeep(); …; pad.neutral(); lock release. Replayed here in that order.
    n_b = len(rec.sent)
    pad.neutral()
    first = (short(rec.dev.state()), internal(pad))
    time.sleep(5.0)                                   # stands for esc wait / alive / wait_respawn (no pad calls)
    pad.force_guard = False
    pad.unkeep()
    pad.neutral()
    print(f"  B  run.py finally 1st neutral: device {first[0]} · {first[1]}")
    print(f"     … +5 s, gk.stop, 2nd neutral: device {short(rec.dev.state())} · {internal(pad)} · reports +{len(rec.sent) - n_b}")

    # C (assumed follow-up, not on run.py's path): an explicit release_due
    n_c = len(rec.sent)
    pad.release_due()
    print(f"  C  + release_due (assumed): device {short(rec.dev.state())} · {internal(pad)} · reports +{len(rec.sent) - n_c}")
    pad.close()


if __name__ == "__main__":
    run("1 normal (death while climbing)", "normal")
    run("2a force_guard setter (tests only)", "force")
    run("2b keep_guard window from a guardkeep thread", "keep")
    run("3 sprint B pressed + release scheduled at the HP-0 read", "sprint")
    run("3b same, run.py's first neutral 0.1 s after the return", "sprint", gap=0.1)
    run("4 another thread holds the freeze (quit-out)", "freeze")
