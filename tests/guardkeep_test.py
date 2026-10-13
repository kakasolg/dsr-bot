"""souls/guardkeep.py + control.Pad.keep_guard — while a foe within 2.5 m swings, LB stays held whatever the callers do.
Real control.Pad on a fake vgamepad.  python tests/guardkeep_test.py

  · a hollow 1.0 m off starts 3000 → LB pressed; guard(False) / neutral() meanwhile don't release it
  · after THREAT_S the keeper lets go (it pressed LB itself, nobody asked for it since); a caller's own guard(True) is kept
  · not raised: foe 3.0 m off · unblockable 3009 · SP below GUARD_SP · my own swing (253000) · no shield
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import sys
import tempfile
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import control
import pad_fakes
from control import B
from souls import guardkeep
from souls.reflex import THREAT_S
from telemetry import Chr, Snapshot

LB = 0x100


def snap(foe_anim=-1, d=1.0, sp=98, my_anim=-1, npc=254010):
    p = Chr(ptr=1, npc_param=0, team=1, hp=700, max_hp=700, x=0.0, y=0.0, z=0.0, sp=sp, anim=my_anim)
    c = Chr(ptr=2, npc_param=npc, team=6, hp=75, max_hp=75, x=d, y=0.0, z=0.0, anim=foe_anim, dist=d)
    return Snapshot(t=time.time(), player=p, chars=[c])


def held(pad) -> bool:
    return bool(pad.pad.report.wButtons & LB)


def fresh(tmp, shield=True):
    pad = control.Pad()
    gk = guardkeep.GuardKeep(pad, shield=lambda: shield, log=lambda *a: None)
    return pad, gk


def test_keeps_guard_through_callers():
    with tempfile.TemporaryDirectory() as tmp:
        pad_fakes.install(Path(tmp))
        pad, gk = fresh(tmp)
        try:
            now = time.time()
            gk.step(snap(-1), now)
            assert not held(pad)
            assert gk.step(snap(3000), now + 0.05) and held(pad)
            pad.guard(False)                       # goto / hold done / look_pulse
            assert held(pad)
            pad.neutral("test")
            assert held(pad)
            gk.step(snap(3000), now + 0.05 + THREAT_S + 0.1)   # swing's threat window over (still 3000 = lingering anim)
            time.sleep(0.01)
            pad._force_until = 0.0                 # the keep time is wall-clock; end it here
            gk.step(snap(3000), now + 0.05 + THREAT_S + 0.2)
            assert not held(pad), "keeper pressed it, nobody asked since → let go"
            assert gk.pressed == 1
        finally:
            pad.close()


def test_callers_own_guard_is_kept():
    with tempfile.TemporaryDirectory() as tmp:
        pad_fakes.install(Path(tmp))
        pad, gk = fresh(tmp)
        try:
            now = time.time()
            gk.step(snap(-1), now)
            gk.step(snap(3000), now + 0.05)
            pad.guard(True)                        # a caller wants the shield too
            pad._force_until = 0.0
            gk.step(snap(-1), now + 2.0)
            assert held(pad), "caller's guard(True) since → keeper leaves LB alone"
        finally:
            pad.close()


def test_not_raised():
    cases = [dict(d=3.0), dict(npc=254010, foe=3009), dict(sp=10), dict(my_anim=253000)]
    with tempfile.TemporaryDirectory() as tmp:
        pad_fakes.install(Path(tmp))
        for k in cases:
            pad, gk = fresh(tmp)
            try:
                now = time.time()
                foe = k.pop("foe", 3000)
                gk.step(snap(-1, **k), now)
                assert not gk.step(snap(foe, **k), now + 0.05), k
                assert not held(pad), k
            finally:
                pad.close()
        pad, gk = fresh(tmp, shield=False)
        try:
            now = time.time()
            gk.step(snap(-1), now)
            assert not gk.step(snap(3000), now + 0.05) and not held(pad)
        finally:
            pad.close()


if __name__ == "__main__":
    test_keeps_guard_through_callers()
    test_callers_own_guard_is_kept()
    test_not_raised()
    print("ok")
