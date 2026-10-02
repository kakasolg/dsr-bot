"""P0-C: no snapshot → nothing held. control.NoObs in duel._sense and Field._walk; feed.Feed never hands out a stale frame.
Real control.Pad on a fake vgamepad (pad_fakes), fake worlds, no game.  python tests/no_obs_test.py

Checks:
  · NoObs: stick to 0 on the first missing tick, buttons kept; everything released after NO_OBS_NEUTRAL_S, once per gap
  · duel._sense: same, while the snapshot stays None
  · Field._walk: same (full release through mover.stop)
  · Feed: when the feed thread stalls without dying, snapshot() gives None after the wait — not the old frame
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import sys
import tempfile
import threading
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import control
import feed
import pad_fakes
from field_fakes import World, make_field
from telemetry import Chr, Snapshot

LB = "XUSB_GAMEPAD_LEFT_SHOULDER"


def check(name: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        raise SystemExit(1)


def held(pad) -> None:
    pad.move(0.6, 0.8)
    pad.guard(True)


def stick_zero_lb_kept(st: dict) -> bool:
    return st["lx"] == 0 and st["ly"] == 0 and LB in st["buttons"]


def test_noobs(vg) -> None:
    pad = control.Pad()
    rec = vg.devices[-1]
    held(pad)
    full: list = []
    no = control.NoObs(pad, on_full=lambda: (full.append(1), pad.neutral()))
    no.missing()
    check("NoObs: 첫 틱 — 스틱 0, 가드(LB)는 그대로", stick_zero_lb_kept(rec.last()))
    time.sleep(control.NO_OBS_NEUTRAL_S + 0.05)
    no.missing()
    check("NoObs: 문턱 뒤 — 전부 놓음", rec.is_neutral() and full == [1])
    no.missing()
    check("NoObs: 한 공백에 전부 놓기는 한 번", full == [1])
    no.seen()
    held(pad)
    no.missing()
    check("NoObs: seen() 뒤 새 공백은 다시 스틱부터", stick_zero_lb_kept(rec.last()) and full == [1])
    pad.close()


class NoneThenWorld:
    """snap(): None for the first `n` calls, then the world. Captures the pad report at chosen calls."""

    def __init__(self, world, rec, n: int, capture: dict):
        self.world, self.rec, self.n, self.capture, self.calls = world, rec, n, capture, 0

    def __call__(self, within: float = 40.0):
        self.calls += 1
        if self.calls in self.capture:
            self.capture[self.calls] = dict(self.rec.last())
        return None if self.calls <= self.n else self.world.snapshot(within)


def test_duel(vg) -> None:
    from souls import duel as D
    from souls import style as style_
    world = World()
    f = make_field(world)
    pad = control.Pad()
    rec = vg.devices[-1]
    f.mv.pad = pad
    F = D.Fight(f.mv, None, 3, None, print, 45.0, 0.25, lambda: False, None, None, None, style_.of("guard"),
                False, 0, None, None)
    held(pad)
    cap = {2: None}
    f.mv.snap = NoneThenWorld(world, rec, 99, cap)
    r = D._sense(F)
    check("duel._sense: None → CONT", r is D.CONT)
    check("duel._sense: 첫 틱 — 스틱 0, 가드 그대로", stick_zero_lb_kept(rec.last()))
    t0 = time.time()
    while time.time() - t0 < control.NO_OBS_NEUTRAL_S + 0.1:
        D._sense(F)
    check("duel._sense: 계속 없으면 전부 놓음", rec.is_neutral())
    pad.close()


def test_walk(vg) -> None:
    world = World()
    f = make_field(world)
    pad = control.Pad()
    rec = vg.devices[-1]
    f.mv.pad = pad
    held(pad)
    cap = {2: None, 6: None}
    f.mv.snap = NoneThenWorld(world, rec, 5, cap)      # 5 × None (0.1 s apart) = 0.5 s > NO_OBS_NEUTRAL_S, then the world
    r = f._walk([(0.0, -49.4, 5.0)], None, "test", done=lambda s: True)
    check("Field._walk: 끝까지 감 (done)", r == "arrived")
    check("Field._walk: 두 번째 None 틱 — 스틱 0, 가드 그대로", stick_zero_lb_kept(cap[2]))
    check("Field._walk: 관측이 돌아오기 전에 이미 전부 놓음", cap[6] and not cap[6]["buttons"] and cap[6]["lx"] == 0)
    pad.close()


class StallTm:
    """First snapshot fine, then the read hangs (thread alive, no new frames) until release."""

    def __init__(self):
        self.n = 0
        self.gate = threading.Event()

    def snapshot(self, within: float = 60.0):
        self.n += 1
        if self.n > 1:
            self.gate.wait()
        return Snapshot(t=time.time(), player=Chr(1, 0, 0, 659, 659, 0, 0, 0), chars=[], cam_yaw=0.0)


def test_feed_stale() -> None:
    tm = StallTm()
    fd = feed.Feed(tm).start()
    s1 = fd.snapshot(within=5.0)
    check("Feed: 첫 프레임은 받음", s1 is not None)
    time.sleep(feed.MAX_AGE + 0.02)
    s2 = fd.snapshot(within=5.0)                        # thread is stuck in the read: no new frame within WAIT
    check("Feed: 멈춘 피드의 낡은 프레임을 새것처럼 안 줌 (None)", s2 is None and fd.served["stale"] == 1)
    check("Feed: 피드 스레드는 살아 있음 (직접 읽기로 안 빠짐)", fd.alive())
    tm.gate.set()
    fd.stop()


def main() -> None:
    vg = pad_fakes.install(Path(tempfile.mkdtemp(prefix="noobs_")))
    test_noobs(vg)
    test_duel(vg)
    test_walk(vg)
    test_feed_stale()
    print("no_obs_test: 전부 통과")


if __name__ == "__main__":
    main()
