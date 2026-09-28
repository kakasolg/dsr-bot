"""track.py + track_report.py offline test — planned path vs actual track, stalls without a foe near. No game.

  python tests/track_report_test.py
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import os
import sys
import tempfile
import types

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import track
import track_report as R
from field_fakes import World

PATH = [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (10.0, 0.0, 10.0)]     # an L: 10 m east, then 10 m north


def write_run(fn: str, stall_at_corner: float, foe_wait: bool = False) -> None:
    """Walk the L at 2 m/s, stand still at the corner for stall_at_corner s; with foe_wait also wait 3 s mid-leg beside a foe."""
    w = World(player=(0.0, 0.0, 0.0))
    foe = w.add(5, 0x105, 254000, (50.0, 0.0, 50.0))
    mv = types.SimpleNamespace(show_path=("#4 이동", PATH), cam_target=None)
    t = track.Track(fn, rate_hz=1e9).follow(mv)
    clock = [0.0]
    orig, track.time.time = track.time.time, (lambda: clock[0])   # the fake world drives the clock
    t.t0 = 0.0

    def at(x, z, dt=0.5):
        w.player.x, w.player.z = x, z
        clock[0] += dt
        t.snapshot(w.snapshot())

    for k in range(11):
        at(k * 1.0, 0.0)
        if k == 5 and foe_wait:
            foe.x, foe.z = 5.0, 2.0
            for _ in range(6):
                at(5.0, 0.0)
            foe.x, foe.z = 50.0, 50.0
    for _ in range(int(stall_at_corner / 0.5)):
        at(10.0 + 0.05, 0.0)                              # rubbing the corner
    for k in range(1, 11):
        at(10.0, k * 1.0)
    mv.show_path = None
    at(10.0, 10.0)
    t.f.close()
    track.time.time = orig


def test_report() -> None:
    d = tempfile.mkdtemp()
    runs = [os.path.join(d, f"r{i}.track.jsonl") for i in range(3)]
    write_run(runs[0], 3.0, foe_wait=True)
    write_run(runs[1], 0.0)
    write_run(runs[2], 2.0)
    text, st = R.report_run(runs[0])
    ws = [R.summarize(w) for w in R.walks(R.frames(runs[0]))]
    assert len(ws) == 1 and ws[0]["reached"] and ws[0]["tag"] == "#4 이동", ws
    assert ws[0]["plan"] == 20.0 and ws[0]["off_max"] < 0.1
    assert len(st) == 1 and abs(st[0]["p"][0] - 10.0) < 0.2 and st[0]["s"] >= 2.5, st   # the corner, not the foe wait
    assert ws[0]["fight_s"] >= 2.5
    assert R.report_run(runs[1])[1] == []
    all_st = [s for r in runs for s in R.report_run(r)[1]]
    out = R.places(all_st, runs)
    assert "2/3 runs" in out and "[3 · 2]" in out, out
    print(text)
    print(out)
    print("ok  track: corner stall found in 2 of 3 runs, the wait beside a foe not counted")


if __name__ == "__main__":
    test_report()
