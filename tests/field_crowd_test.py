"""둘러싸임 오프라인 테스트 — 퀵 종료 대신 후퇴 ([MoKa] 2026-09-28: "둘러싸였을 때는 퀵 종료하면 안 되고 후퇴해야 해", 무조건 후퇴).

  duel: crowd_ok 이면 움직이는 적 둘 이상이 4 m 안에 있을 때 HP와 상관없이 'crowd' 로 끝남 (서 있는 옆 적은 안 셈)
  Field.fall_back: 지나온 길(home 쪽)로 가드 든 채 걷다가 따라온 적이 하나 이하가 되면 멈춤, 길이 없으면 잠깐 제자리 싸움
  Escape: 둘러싸여도 퀵 종료하지 않음

  python tests/field_crowd_test.py
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import inspect
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from duel_shadow_test import DuelMv
from field_fakes import World, make_field
from souls import duel as D
from souls import field as F
from souls import watch
from souls import weapons

AXE = weapons.BATTLE_AXE


def run(second_anim, crowd_ok=True, ticks=6):
    w = World(player=(0.0, -49.4, 0.0), sp=90, hp=682)
    w.add(2, 0x1018, 254000, (1.2, -49.4, 0.0), anim=3000)
    w.add(3, 0x1019, 254001, (0.0, -49.4, 2.0), anim=second_anim)
    mv = DuelMv(w, 2)
    n = {"k": 0}

    def cancel():
        n["k"] += 1
        return n["k"] > ticks
    return D.duel(mv, AXE, 2, None, log=lambda *a: None, cancel=cancel, reflex=None, gen=0,
                  events=lambda *a, **k: None, crowd_ok=crowd_ok)


def test_duel_crowd() -> None:
    assert run(3003).result == "crowd"                                   # 둘 다 움직임, HP 100 %
    assert run(-1).result != "crowd"                                     # 옆 적은 서 있음(자는 중)
    assert run(3003, crowd_ok=False).result != "crowd"                   # 기본값은 예전 그대로 (duel_golden)
    print("ok  duel ends 'crowd' at full HP with 2 moving foes within 4 m; standing neighbour or crowd_ok=False → no")


class Nm:
    def __init__(self, path):
        self.path = path

    def find_path(self, a, b):
        return self.path


def field_with(world):
    f = make_field(world)
    f.home = (-20.0, -49.4, 0.0)
    f._crowd_off_until = 0.0
    return f


def test_fall_back_stops_when_split() -> None:
    w = World(player=(0.0, -49.4, 0.0), hp=682)
    w.add(2, 0x1018, 254000, (1.2, -49.4, 0.0), anim=3000)
    w.add(3, 0x1019, 254001, (0.0, -49.4, 2.0), anim=3003)
    f = field_with(w)
    seen = {}

    def walk_path(path, nm, mode="walk", stop=None, **kw):
        seen["mode"] = mode
        t0 = time.time()
        while time.time() - t0 < 3.0:
            w.move(3, (0.0, -49.4, 20.0))                                   # 한 놈은 포기하고 멀어짐
            if stop(w.snapshot()):
                return "stopped"
            time.sleep(0.05)
        return "arrived"
    f.mv.walk_path = walk_path
    r = f.fall_back(Nm([(0.0, -49.4, 0.0), (-10.0, -49.4, 0.0), (-20.0, -49.4, 0.0)]))
    assert r == "stopped" and seen["mode"] == "guard", (r, seen)
    assert any("물러남" in l and "따라온 적 1" in l for l in f.logs), f.logs
    print("ok  fall_back walks home with guard up, stops when only one follows")


def test_fall_back_no_path() -> None:
    w = World(player=(0.0, -49.4, 0.0), hp=682)
    f = field_with(w)
    assert f.fall_back(Nm(None)) == "no_path"
    assert f._crowd_off_until > time.time() + F.FALL_BACK_OFF_S - 1.0
    print("ok  no path back → fight in place for FALL_BACK_OFF_S (no endless crowd → fall_back loop)")


def test_crowd_cap() -> None:
    """P-26: 'crowd' → fall_back → 'crowd' 16 times, none counted as a try by the callers. CROWD_MAX in CROWD_WINDOW_S ends it."""
    f = field_with(World(player=(0.0, -49.4, 0.0), hp=682))
    f.events = lambda *a, **k: None
    seen = []
    for k in range(F.CROWD_MAX - 1):
        assert f._crowd_capped() is False, k
        seen.append(f._crowd_off_until)
    assert all(t == 0.0 for t in seen), "no cap before CROWD_MAX"
    assert f._crowd_capped() is True
    assert f._crowd_off_until > time.time() + F.CROWD_OFF_S - 1.0 and f._crowd_hits == []
    assert any("P-26" in l for l in f.logs), f.logs
    # old ones age out: CROWD_MAX - 1 hits, then a long pause → the next one is counted alone
    f._crowd_off_until = 0.0
    f._crowd_hits = [time.time() - F.CROWD_WINDOW_S - 1.0] * (F.CROWD_MAX - 1)
    assert f._crowd_capped() is False and len(f._crowd_hits) == 1
    print("ok  crowd fall-back capped: CROWD_MAX within CROWD_WINDOW_S → fight in place for CROWD_OFF_S; old hits age out")


def test_fight_loop_bounded() -> None:
    """The real Field.fight with CROWD_FALL_BACK on and a duel that keeps ending 'crowd' (P-26): fall_back runs CROWD_MAX - 1 times,
    then the duel is asked with crowd_ok False."""
    from types import SimpleNamespace
    f = field_with(World(player=(0.0, -49.4, 0.0), hp=682))
    f.events = lambda *a, **k: None
    f.w, f.esc = None, SimpleNamespace(gen=0, escaping=False)
    f.reflex = SimpleNamespace(nm=None)
    f.style = SimpleNamespace(grip=None)
    f.mv = SimpleNamespace(estus_id=lambda: None, tm=SimpleNamespace(grip=lambda: None), cam_target=None)
    f.heal = lambda *a, **k: None
    asked, falls = [], []
    f.fall_back = lambda nm: falls.append(1) or "stopped"
    duel, cw = D.duel, F.CROWD_FALL_BACK
    D.duel = lambda *a, **k: (asked.append(k["crowd_ok"]), D.DuelResult("crowd" if k["crowd_ok"] else "timeout"))[1]
    F.CROWD_FALL_BACK = True
    try:
        for _ in range(8):
            F.Field.fight(f, 2, None, "t")
    finally:
        D.duel, F.CROWD_FALL_BACK = duel, cw
    assert len(falls) == F.CROWD_MAX - 1, falls
    assert asked[:F.CROWD_MAX] == [True] * F.CROWD_MAX and not any(asked[F.CROWD_MAX:]), asked
    print(f"ok  Field.fight: crowd → fall_back {len(falls)}× then capped, later duels run with crowd_ok=False ({asked})")


def test_no_crowd_quit_out() -> None:
    src = inspect.getsource(watch.Escape)
    assert '"crowd"' not in src.split("def _back_to_mesh", 1)[0], "crowd quit-out still in the Escape watch loop"
    print("ok  Escape no longer quits out for being surrounded")


if __name__ == "__main__":
    test_duel_crowd()
    test_fall_back_stops_when_split()
    test_fall_back_no_path()
    test_crowd_cap()
    test_fight_loop_bounded()
    test_no_crowd_quit_out()
    print("전부 통과")
