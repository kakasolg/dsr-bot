"""P-81: Escape stops nudging back from a ledge after NUDGE_FUTILE nudges in a row that left us where the last one started
(clay18-1 zone 6: 23 nudges 1 s apart while standing 1 m down on solid floor off the NavMesh; pull-off2 ramp ledge: 22 at 3.5 m
down). Moving away or standing on floor again re-arms it. No game, no pad.  python tests/ledge_futile_test.py"""
from __future__ import annotations
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import types

from souls.watch import Escape
from telemetry import Chr, Snapshot


def check(name: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        raise SystemExit(1)


def make(floor_y=None):
    """Escape with a fake NavMesh: floor at floor_y everywhere (None = no floor) and a nudge that only counts."""
    logs, events = [], []
    nm = types.SimpleNamespace()
    esc = Escape(None, [nm], log=logs.append, events=lambda kind, **kw: events.append(kind))
    esc.floor_drop = lambda p: None if esc._floor_y is None else p.y - esc._floor_y
    esc._floor_y = floor_y
    esc.sent = []
    esc._nudge = lambda st: (esc.sent.append(st), True)[1]
    return esc, logs, events


def tick(esc, t, x, y, z):
    p = Chr(1, 0, 1, 500, 500, x, y, z)
    esc._ledge(Snapshot(t=t, player=p, chars=[], cam_yaw=0.0), p, t)


def stand(esc, t0, secs, x, y, z, hz=10):
    """Stand still at (x, y, z) for secs, ticking like _run does: _ledge only after NUDGE_COOLDOWN since the last nudge (fake clock)."""
    last = -9.0
    for k in range(int(secs * hz)):
        t = t0 + k / hz
        if t - last > esc.NUDGE_COOLDOWN:
            n = len(esc.sent)
            tick(esc, t, x, y, z)
            if len(esc.sent) > n:
                last = t
    return t0 + secs


def main() -> None:
    # standing still 1 m below the safe spot, no floor in the NavMesh — clay18-1 zone 6
    esc, logs, events = make(floor_y=0.0)
    tick(esc, 0.0, 0.0, 0.0, 0.0)                       # on floor → safe spot
    esc._floor_y = None
    stand(esc, 0.1, 20.0, 0.4, -1.0, 0.0)
    check(f"20 s standing still off the mesh: {len(esc.sent)} nudges (was ~20)", len(esc.sent) == esc.NUDGE_FUTILE)
    check("one line + one event when it gives up", sum("그만" in l for l in logs) == 1 and events.count("ledge_futile") == 1)

    # moving on (a real slide that keeps going) re-arms it
    n0 = len(esc.sent)
    stand(esc, 21.0, 1.5, 0.4, -1.6, 1.0)
    check("a new spot further down → nudges again", len(esc.sent) > n0)

    # standing on floor again resets it
    esc._floor_y = -1.6
    tick(esc, 30.0, 0.4, -1.6, 1.0)
    check("floor underfoot again → count reset", esc._futile == 0 and esc._nudge_at is None)

    # a real slide: every nudge starts lower than the last → never futile
    esc, logs, events = make(floor_y=0.0)
    tick(esc, 0.0, 0.0, 0.0, 0.0)
    esc._floor_y = None
    last = -9.0
    for k in range(60):                                 # 6 s at 10 Hz, y −0.7 → −2.8 (0.35 m/s), creeping 0.03 m/s sideways
        t = 0.1 + k / 10
        if t - last > esc.NUDGE_COOLDOWN:
            n = len(esc.sent)
            tick(esc, t, 0.3 + 0.003 * k, -0.7 - 0.035 * k, 0.0)
            last = t if len(esc.sent) > n else last
    check(f"sliding 0.35 m/s (2026-09-25 152400 shape): nudged all along, never gave up ({len(esc.sent)})",
          len(esc.sent) >= 8 and "ledge_futile" not in events)
    print("ledge_futile_test: all ok")


if __name__ == "__main__":
    main()
