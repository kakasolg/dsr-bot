"""나이프 없는 캐릭터 오프라인 테스트 — 끌어오기가 'no_knife'면 그 정리 동안 다시 던지러 가지 않고 걸어가 붙는다,
--no-lure 는 clear-ramp 뿐 아니라 burg-bonfire 등 경사로를 지나는 미션 모두에 적용된다.

  python tests/field_no_knife_test.py
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from field_fakes import World, make_field
from souls import field as F
from souls import missions as MS

SPAWN2 = (-23.4, -49.67, 16.15)
SPOT = (-30.35, -49.43, 27.91)
LA = {"spot": SPOT, "min": 13.0, "max": 15.0, "hold": True}
T2 = {"npc": 255010, "pos": list(SPAWN2), "label": 2, "lure": True, "lure_at": LA}
T1 = {"npc": 254000, "pos": [-29.79, -49.62, 24.88], "label": 1, "lure": True}

F.HOLD_WAIT = 0.01


def test_hold_target_no_knife_fights() -> None:
    w = World(player=SPOT)
    w.add(2, 0x1018, 255010, SPAWN2, hp=85, max_hp=85)
    f = make_field(w)
    f.lure_result = "no_knife"
    r = f.clear([dict(T2)], nm=None, lure=True)
    assert len(f.lures) == 1, f.lures                                   # 예전: 3번 + 미룬 뒤 3번
    assert [x["ptr"] for x in f.fights] == [2], f.fights               # 미루지 않고 싸움
    assert not any("맨 뒤로" in l for l in f.logs), f.logs
    assert r == "cleared", r
    print(f"ok  hold target, no_knife → 1 lure try, then fought → '{r}'")


def test_later_targets_not_lured() -> None:
    w = World(player=SPOT)
    w.add(1, 0x1015, 254000, T1["pos"])
    w.add(2, 0x1018, 255010, SPAWN2, hp=85, max_hp=85)
    f = make_field(w)
    f.lure_result = "no_knife"
    r = f.clear([dict(T1), dict(T2)], nm=None, lure=True)
    assert len(f.lures) == 1, f.lures
    assert [x["ptr"] for x in f.fights] == [1, 2], f.fights
    print(f"ok  first no_knife turns lures off for the rest → fights #1, #2 → '{r}'")


def test_no_lure_reaches_burg_bonfire() -> None:
    seen = []
    ms = MS.Missions.__new__(MS.Missions)
    ms.lure = False
    ms.nms = {MS.MAP_A: None}
    ms.log = lambda *a: None
    ms.f = type("F", (), {"clear": lambda self, t, nm, arena=None, lure=True: seen.append(lure) or "cleared"})()
    ms.clear_ramp()
    ms.clear_ramp(lure=True)
    assert seen == [False, True], seen
    print("ok  Missions(lure=False) → clear_ramp() without lures; explicit lure=True still wins")


if __name__ == "__main__":
    test_hold_target_no_knife_fights()
    test_later_targets_not_lured()
    test_no_lure_reaches_burg_bonfire()
    print("전부 통과")
