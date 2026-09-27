"""Patch A 오프라인 테스트 — 목표 생존 판정은 런타임 신원 + raw HP (스폰 거리로 죽음을 추정하지 않는다).

  python field_liveness_test.py
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from field_fakes import World, make_field
from souls import field as F

SPAWN3 = (-20.57, -40.35, 18.93)      # 경사로 #3 스폰 (위 턱)
T3 = {"npc": 254000, "pos": list(SPAWN3), "label": 3, "lure": False}


def bound(world):
    f = make_field(world)
    b = {}
    f._bind(b, T3, world.snapshot(200))
    assert b.get("ptr") == 3 and b["handle"] == 0x1003 and b["gen"] == 0, b
    return f, b


def test_moved_live_enemy_not_dead() -> None:
    w = World(player=(-30.0, -49.3, 29.0))
    w.add(3, 0x1003, 254000, SPAWN3)
    f, b = bound(w)
    w.move(3, (-27.0, -49.2, 26.0))                 # 위 턱에서 평지로 내려옴: 스폰에서 수평 10 m·아래 9 m
    st, c = f._liveness(b, T3, w.snapshot(200))
    assert st == "moved" and c.ptr == 3, st
    # clear 수준: 옛 find_at 이면 "스폰 30 m 안에 없음 — 이미 죽음" 으로 빠졌다. 이제는 싸움으로 간다
    w2 = World(player=(-30.0, -49.3, 29.0))
    w2.add(3, 0x1003, 254000, SPAWN3)
    f2 = make_field(w2)
    f2._bind_once = True
    t = dict(T3)
    orig = f2._liveness

    def liveness(bb, e, s):                          # 묶인 뒤 내려오게
        if bb.get("ptr") is not None:
            w2.move(3, (-27.0, -49.2, 26.0))
        return orig(bb, e, s)
    f2._liveness = liveness
    r = f2.clear([t], nm=None, lure=False)
    assert r == "cleared", r
    assert [x["ptr"] for x in f2.fights] == [3], f2.fights
    assert not any("이미 죽음" in l for l in f2.logs), f2.logs
    print("ok  moved live enemy (raw HP 75, 10 m/9 m from spawn) → 'moved', fought, not popped as dead")


def test_single_zero_glitch() -> None:
    w = World()
    w.add(3, 0x1003, 254000, SPAWN3)
    f, b = bound(w)
    w.chars[3].hp = 0
    assert f._liveness(b, T3, w.snapshot(200))[0] != "dead"
    w.chars[3].hp = 75
    st, _ = f._liveness(b, T3, w.snapshot(200))
    assert st == "alive" and b["zero_n"] == 0, (st, b)
    print("ok  one HP-0 frame then 75 → not dead (zero count reset)")


def test_two_consecutive_zero_dead() -> None:
    w = World()
    w.add(3, 0x1003, 254000, SPAWN3)
    f, b = bound(w)
    w.chars[3].hp = 0
    s = w.snapshot(200)
    assert f._liveness(b, T3, s)[0] == "alive"
    assert f._liveness(b, T3, s)[0] == "alive"       # 같은 스냅샷을 두 번 봐도 한 번으로 센다
    assert f._liveness(b, T3, w.snapshot(200))[0] == "dead"
    print("ok  raw HP 0 in two distinct consecutive snapshots → dead (same snapshot counted once)")


def test_missing_then_unknown() -> None:
    w = World()
    w.add(3, 0x1003, 254000, SPAWN3)
    f, b = bound(w)
    w.hidden.add(3)
    old = F.MISSING_S
    F.MISSING_S = 0.3
    try:
        assert f._liveness(b, T3, w.snapshot(200))[0] == "missing"
        time.sleep(0.15)
        assert f._liveness(b, T3, w.snapshot(200))[0] == "missing"
        time.sleep(0.2)
        st, _ = f._liveness(b, T3, w.snapshot(200))
        assert st == "unknown" and not b, (st, b)
    finally:
        F.MISSING_S = old
    print("ok  absent from snapshot → 'missing', after MISSING_S → 'unknown' (unbound), never dead")


def test_generation_change_new_life() -> None:
    w = World()
    w.add(3, 0x1003, 254000, SPAWN3, hp=0)          # 0세대에서 죽었다 (시체)
    f = make_field(w)
    b = {"ptr": 3, "handle": 0x1003, "gen": 0, "zero_n": 1, "zero_t": -1}
    f.esc.gen = 1                                    # 퀵 종료·다시 불러오기
    st, _ = f._liveness(b, T3, w.snapshot(200))
    assert st == "unknown" and not b, (st, b)
    del w.chars[3]
    w.add(7, 0x1007, 254000, SPAWN3, hp=75)          # 새 세대: 스폰에 가득 찬 새 생명
    f._bind(b, T3, w.snapshot(200))
    assert b["ptr"] == 7 and b["handle"] == 0x1007 and b["gen"] == 1, b
    assert f._liveness(b, T3, w.snapshot(200))[0] == "alive"
    print("ok  esc.gen change → 'unknown', old identity dropped; new full-HP life bound separately (gen 1)")


def test_dead_in_place() -> None:
    w = World()
    w.add(3, 0x1003, 254000, SPAWN3)
    f, b = bound(w)
    w.chars[3].hp = 0
    f._liveness(b, T3, w.snapshot(200))
    assert f._liveness(b, T3, w.snapshot(200))[0] == "dead"
    print("ok  regression: killed at spawn → dead")


def test_handle_mismatch_not_same() -> None:
    w = World()
    w.add(3, 0x1003, 254000, SPAWN3)
    f, b = bound(w)
    w.handles[3] = 0x9999                            # 같은 ptr 에 다른 놈
    assert f._liveness(b, T3, w.snapshot(200))[0] == "missing"
    print("ok  same ptr but different handle → treated as missing, not the target")


if __name__ == "__main__":
    test_moved_live_enemy_not_dead()
    test_single_zero_glitch()
    test_two_consecutive_zero_dead()
    test_missing_then_unknown()
    test_generation_change_new_life()
    test_dead_in_place()
    test_handle_mismatch_not_same()
    print("전부 통과")
