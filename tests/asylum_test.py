"""souls/asylum 오프라인 테스트 — 구간 자르기, 방향 계산, 단계 실행 순서·멈춤, 사다리 오르기 판정. 게임 없음.

  python tests/asylum_test.py
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import math
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from field_fakes import World, make_field
from souls import asylum as A

STEPS = [
    {"type": "walk", "pts": [[0, 0, 0]]},
    {"type": "menu", "keys": ["START", "START"], "label": "감방"},          # intro skip — must be dropped
    {"type": "press", "pos": [1, 0, 0], "hd": 0.0, "n": 2, "label": "감방: 열쇠"},
    {"type": "menu", "keys": ["START", "RIGHT"], "label": "감방"},          # after a press — kept
    {"type": "walk", "pts": [[1, 0, 0], [5, 0, 0]]},
    {"type": "press", "pos": [5, 0, 0], "hd": 1.0, "n": 1, "label": "첫 화톳불 (1812960) 불 붙이기"},
    {"type": "walk", "pts": [[5, 0, 0], [9, 0, 0]]},
    {"type": "press", "pos": [9, 0, 0], "hd": 1.0, "n": 1, "label": "큰 방 문"},
]


def test_segment() -> None:
    s1 = A.segment(STEPS, 1)
    assert [x["type"] for x in s1] == ["walk", "press", "menu", "walk", "press"], s1
    assert s1[-1]["label"].startswith("첫 화톳불")
    try:
        A.segment(STEPS, 2)
        raise AssertionError("segment 2 has no end label yet")
    except (KeyError, ValueError):
        pass
    real = A.segment(A.load(), 1)
    assert real[-1]["label"].startswith("첫 화톳불") and not any(x["type"] == "menu" for x in real), real
    assert any(x["type"] == "climb" for x in real), "segment 1 climbs the ladder"
    print(f"ok  segment 1 = cell → ladder → first bonfire ({len(real)} steps), intro menu dropped")


def test_heading() -> None:
    assert abs(A.heading_off(0.1, -0.1) + math.degrees(0.2)) < 1e-6
    assert abs(abs(A.heading_off(3.1, -3.1)) - math.degrees(2 * math.pi - 6.2)) < 1e-6   # wraps around ±π
    dx, dz = A.heading_vec(0.0)                                          # world yaw = heading + π → facing −z
    assert abs(dx) < 1e-9 and abs(dz + 1.0) < 1e-9, (dx, dz)
    print("ok  heading_off wraps, heading_vec(0) faces −z (world yaw = heading + π)")


def test_run_order_and_stop() -> None:
    f = make_field(World(player=(0.0, -49.4, 0.0)))
    f.alive = lambda: True
    a = A.Asylum(f, nm=None, log=f.log)
    done = []
    for kind in ("walk", "press", "menu", "climb", "fight", "mark", "jump"):
        setattr(a, "_" + kind, (lambda k: lambda st, tag: done.append(k) or ("fail" if st.get("x") else "ok"))(kind))
    r = a.run([{"type": "walk"}, {"type": "press"}, {"type": "climb", "x": 1, "label": "사다리"}, {"type": "walk"}])
    assert done == ["walk", "press", "climb"] and r.startswith("fail at 3 climb 사다리"), (done, r)
    print(f"ok  steps run in order, stops at the first failure → '{r}'")


class ClimbMv:
    """Snapshots whose y rises while the stick is pushed up."""
    def __init__(self, world, rate):
        self.w, self.rate = world, rate
        self.pushing = False
        self.pad = self
        self.tm = None
        self.presses = 0

    def move(self, x, y):
        self.pushing = y > 0.5

    def neutral(self):
        self.pushing = False

    def snap(self, within=3.0):
        if self.pushing:
            self.w.player.y += self.rate
        return self.w.snapshot(within)

    def press(self, button, hold=0.1, gap=0.1):
        self.presses += 1


def test_climb() -> None:
    A.CLIMB_S = 4.0
    import time as _t
    sleep = A.time.sleep
    A.time.sleep = lambda s: None                                        # no real waiting; loop is bounded by CLIMB_S on wall time
    try:
        for rate, want in ((0.05, "ok"), (0.0, "fail")):
            w = World(player=(0.0, 190.5, 0.0))
            f = make_field(w)
            a = A.Asylum(f, nm=None, log=f.log)
            a.mv = ClimbMv(w, rate)
            a.pad = a.mv
            t0 = _t.time()
            r = a._climb({"from": [0, 190.5, 0], "to": [0, 195.6, 0]}, "t")
            assert r == want, (rate, r, f.logs[-2:])
            if want == "fail":
                assert a.mv.presses == 1, a.mv.presses                   # one A retry when it doesn't start climbing
    finally:
        A.time.sleep = sleep
    print("ok  ladder: climbs to the top → ok; y never rises → one A retry, then fail")


if __name__ == "__main__":
    test_segment()
    test_heading()
    test_run_order_and_stop()
    test_climb()
    print("전부 통과")
