"""Zone 8 hold (souls/missions._wait_at_safe still_out): a crossbowman that stands and shoots ends the wait after HOLD_STILL_S,
one that walks in is waited for, a patroller's `wait` (still_out False) keeps the full time. Fakes only — no game, no pad.
MoKa 11-08 "사다리 타고 올라가면, 다음 판단 느려지는 것도 여전하네" (20261108_192447: 8-2 stood 7.2 m out 20 s).
python tests/zone8_hold_test.py"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import time
from types import SimpleNamespace as NS

if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8")

from souls import missions as MS

SAFE = (61.95, 23.7, -116.93)


def make(path):
    """path(t) → target x; the target walks along x only (z = safe z)."""
    m = MS.Missions.__new__(MS.Missions)
    m.log = lambda *a, **k: None
    m._encounters = lambda s, ptr: []
    t0 = time.time()
    foe = NS(ptr=7, x=0.0, y=23.7, z=SAFE[2], hp=85)

    def snap(r):
        foe.x = path(time.time() - t0)
        return NS()
    m.mv = NS(snap=snap, find=lambda s, ptr: foe, pad=NS(guard=lambda on: None))
    return m


def timed(m, secs, **k):
    t = time.time()
    r = m._wait_at_safe(7, SAFE, secs, **k)
    return r, time.time() - t


def main() -> None:
    old = MS.HOLD_STILL_S
    MS.HOLD_STILL_S = 0.6                                  # keep the test short; the rule is the same
    try:
        stand = lambda t: SAFE[0] - 10.0                   # 10 m out, never closer (192447 8-2 shooting from 7.2 m)
        r, dt = timed(make(stand), 5.0, still_out=True)
        assert r is False and dt < 1.5, (r, dt)
        print(f"ok  standing shooter: wait ends after {dt:.1f} s (HOLD_STILL_S {MS.HOLD_STILL_S}), not the full 5 s")

        come = lambda t: SAFE[0] - max(0.0, 12.0 - 3.0 * t)   # walks in at 3 m/s → inside UPPER_COME_R
        r, dt = timed(make(come), 5.0, still_out=True)
        assert r is True, (r, dt)
        print(f"ok  walking in: it came ({dt:.1f} s)")

        r, dt = timed(make(stand), 1.5)
        assert r is False and dt >= 1.4, (r, dt)
        print(f"ok  patroller wait (still_out False): full {dt:.1f} s")
    finally:
        MS.HOLD_STILL_S = old


if __name__ == "__main__":
    main()
