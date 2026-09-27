"""Patch E-1 오프라인 테스트 — 평지에서 잡을 목표가 움직여 다른 높이에 있으면 찾아가지 않고 평지에서 기다린다.

  python field_moved_wait_test.py
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from field_fakes import World, make_field
from souls import field as F

ARENA = (-30.0, -49.25, 29.0)
SPAWN3 = (-20.57, -40.35, 18.93)
T3 = {"npc": 254000, "pos": list(SPAWN3), "label": 3, "lure": True}
RAMP_MID = (-24.8, -44.2, 24.0)          # 경사로 중간 — 평지보다 5 m 위 (run 131752·132053 에서 #3 이 있던 곳)

F.MOVED_WAIT_S = 0.3


def world_with_hook(steps):
    """steps: [(스냅샷 번호, 함수(world))] — 번호는 **#3 을 묶은 뒤**부터 센다 (0 = 묶자마자). 실제로도 #1 을 잡을 때쯤
    #3 은 이미 내려오는 중이다 (131752·132053)."""
    w = World(player=ARENA)
    w.add(3, 0x1013, 254000, SPAWN3)
    snap0, n = w.snapshot, {"k": None}

    def snapshot(within=60.0):
        if n["k"] is not None:
            n["k"] += 1
            for k, fn in steps:
                if n["k"] == k:
                    fn(w)
        return snap0(within)
    w.snapshot = snapshot
    w.bound = lambda: (n.__setitem__("k", 0), [fn(w) for k, fn in steps if k == 0])
    return w


def make(w):
    f = make_field(w)
    orig = f._bind

    def bind(b, e, s):
        orig(b, e, s)
        if b.get("ptr") is not None and not getattr(f, "_bound_once", False):
            f._bound_once = True
            w.bound()
    f._bind = bind
    return f


def test_wait_then_coming() -> None:
    """#3 이 경사로 중간(다른 높이)에 서 있으면 lure·fight 없이 평지에서 기다리고, 내려와 휘두르면 '오는 놈' 으로 잡는다."""
    def down(w):
        w.move(3, (ARENA[0] + 2.0, ARENA[1], ARENA[2]))
        w.chars[3].anim = 3000
    w = world_with_hook([(0, lambda w: w.move(3, RAMP_MID)), (40, down)])
    f = make(w)
    old = F.MOVED_WAIT_S
    F.MOVED_WAIT_S = 30.0
    try:
        r = f.clear([dict(T3)], nm=None, arena=ARENA, lure=True)
    finally:
        F.MOVED_WAIT_S = old
    assert r == "cleared", r
    assert f.lures == [], f.lures                                       # 끌어오기로 걸어가지 않음
    # 내려온 뒤 '오는 놈' 으로 먼저 잡는다. 그 뒤 fight() 가 한 번 더 불릴 수 있는데, 그건 raw HP 0 이 한 프레임만 보인 목표에
    # 대한 Patch A 의 알려진 경계(duel 이 바로 'killed', 움직임 없음)라 E-1 과 무관 — 그 호출이 HP 0 목표에게만인지 확인한다
    assert f.fights and f.fights[0]["tag"] == "오는 놈 254000", f.fights
    assert all(w.chars[x["ptr"]].hp == 0 for x in f.fights[1:]), f.fights
    assert any("찾아가지 않고 평지에서 기다림" in l for l in f.logs), f.logs
    assert all(c[1] == 0 and c[2] == 0 for c in f.mv.pad.calls if c[0] == "move")
    print("ok  #3 moved up the ramp (dy +5) → waits at the arena (no lure, no fight); comes down swinging → fought as 오는 놈")


def test_never_comes_down() -> None:
    """두 번 기다려도 안 내려오면 찾아가지 않고 'left #3~'."""
    w = world_with_hook([(0, lambda w: w.move(3, RAMP_MID))])
    f = make(w)
    r = f.clear([dict(T3)], nm=None, arena=ARENA, lure=True)
    assert r == "left #3~", r
    assert f.lures == [] and f.fights == [] and not any(g[1] != "#3 제자리로" for g in f.walks), (f.lures, f.fights, f.walks)
    print(f"ok  #3 stays on the ramp → waits twice, never pursued → '{r}'")


def test_waits_at_arena_not_elsewhere() -> None:
    """평지에서 떨어져 있으면 평지로 돌아간다 (걸어가는 곳은 평지뿐)."""
    w = world_with_hook([(0, lambda w: w.move(3, RAMP_MID))])
    w.player.x, w.player.z = ARENA[0] + 3.0, ARENA[2]
    f = make(w)
    f.clear([dict(T3)], nm=None, arena=ARENA, lure=True)
    assert f.walks and all(g[0] == ARENA for g in f.walks), f.walks
    print("ok  player 3 m off the arena → walk_to(arena) only")


def test_same_floor_inside_zone_unchanged() -> None:
    """평지 구역(2.5 m) 안, 같은 높이로 들어온 목표는 예전 그대로 (끌어오기 → 싸움)."""
    w = world_with_hook([(0, lambda w: w.move(3, (ARENA[0] + 2.0, ARENA[1] + 0.3, ARENA[2] - 1.0)))])
    f = make(w)
    f.lure_result = "no_reaction"
    r = f.clear([dict(T3)], nm=None, arena=ARENA, lure=True)
    assert r == "cleared" and len(f.lures) == 1 and [x["ptr"] for x in f.fights] == [3], (r, f.lures, f.fights)
    print("ok  moved into the arena zone (same floor, 2.2 m) → existing lure → fight path (unchanged)")


def test_same_floor_outside_zone_waits() -> None:
    """E-1b: 같은 높이라도 평지 구역 밖이면 찾아가지 않고 기다린다 — 133016 의 #3 (평지 가장자리, 약 5 m)."""
    w = world_with_hook([(0, lambda w: w.move(3, (-25.8, -48.7, 24.0)))])
    f = make(w)
    r = f.clear([dict(T3)], nm=None, arena=ARENA, lure=True)
    assert r == "left #3~" and f.lures == [] and f.fights == [], (r, f.lures, f.fights)
    assert any("평지 구역 밖" in l for l in f.logs), f.logs
    print("ok  E-1b: same floor but 6.5 m off the arena (133016's #3 spot) → wait, never pursued → 'left #3~'")


def test_near_hold_spawn_waits() -> None:
    """E-1b: 아직 남은 방패병(제자리 고수 대상) 스폰에서 12 m 안이면 기다린다."""
    T2 = {"npc": 255010, "pos": [-23.4, -49.67, 16.15], "label": 2, "lure": True,
          "lure_at": {"spot": (-30.35, -49.43, 27.91), "min": 13.0, "max": 15.0, "hold": True}}
    w = world_with_hook([(0, lambda w: w.move(3, (-24.5, -49.5, 22.0)))])
    w.add(2, 0x1018, 255010, T2["pos"], hp=85, max_hp=85)
    f = make(w)
    reasons = f._wait_reasons(w.chars[3], ARENA, [dict(T3), T2])
    assert any("스폰에서" in r for r in reasons), reasons
    print(f"ok  E-1b: moved target 6 m from the shield's spawn → wait ({', '.join(reasons)})")


def test_at_spawn_ledge_unchanged() -> None:
    """스폰 그대로인 위 턱 목표(#4~#6 처럼)는 예전 그대로 (E-1 은 '움직인' 목표만)."""
    w = World(player=ARENA)
    w.add(3, 0x1013, 254000, SPAWN3)
    f = make_field(w)
    f.lure_result = "no_reaction"
    f.clear([dict(T3)], nm=None, arena=ARENA, lure=True)
    assert len(f.lures) == 1 and [x["ptr"] for x in f.fights] == [3], (f.lures, f.fights)
    print("ok  target still at its ledge spawn → existing lure → fight path (unchanged)")


if __name__ == "__main__":
    test_wait_then_coming()
    test_never_comes_down()
    test_waits_at_arena_not_elsewhere()
    test_same_floor_inside_zone_unchanged()
    test_same_floor_outside_zone_waits()
    test_near_hold_spawn_waits()
    test_at_spawn_ledge_unchanged()
    print("전부 통과")
