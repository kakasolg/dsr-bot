"""Patch E-2·E-3 오프라인 테스트 — 붙으러 가는 중 예전 자리로 가지 않기(E-2), '안옴→붙기' 로 안전 구역 밖에 붙으러 가지 않기(E-3).

  python field_approach_guard_test.py
"""
from __future__ import annotations

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from field_fakes import World, make_field
from souls import duel as D
from souls import foes
from souls import moves as M
from souls import weapons

ARENA = (-30.0, -49.25, 29.0)
SPAWN3 = (-20.57, -40.35, 18.93)
SPAWN2 = (-23.4, -49.67, 16.15)
T3 = {"npc": 254000, "pos": list(SPAWN3), "label": 3, "lure": True}
T2 = {"npc": 255010, "pos": list(SPAWN2), "label": 2, "lure": True,
      "lure_at": {"spot": (-30.35, -49.43, 27.91), "min": 13.0, "max": 15.0, "hold": True}}
AXE = weapons.BATTLE_AXE


def guard_for(w, bound: bool):
    f = make_field(w)
    pending = [dict(T3), T2]
    binds = {}
    if bound:
        binds[id(pending[0])] = {"ptr": 3, "handle": 0x1013, "gen": 0}
    return f, f._approach_guard(ARENA, pending, binds)


def test_guard_predicate() -> None:
    w = World(player=ARENA)
    w.add(3, 0x1013, 254000, SPAWN3)
    f, may = guard_for(w, bound=True)
    s = w.snapshot()
    assert may(w.chars[3], s) is True                           # 스폰 그대로(위 턱) → 된다 (예전처럼)
    w.move(3, (-25.9, -48.7, 24.5))                              # 133827: 평지 가장자리, 방패병 스폰 8 m
    assert may(w.chars[3], w.snapshot()) is False               # 움직인 목록 목표 + 구역 밖·방패병 근처 → 안 된다
    w.move(3, (ARENA[0] + 1.5, ARENA[1], ARENA[2]))
    assert may(w.chars[3], w.snapshot()) is True                # 평지 구역 안으로 들어옴 → 된다
    # 목록에 없는 놈 — 플레이어가 평지 근처면 막고, 위 턱에 있으면 예전 그대로
    w2 = World(player=ARENA)
    w2.add(9, 0x1099, 254000, (-25.9, -48.7, 24.5))
    _, may2 = guard_for(w2, bound=False)
    assert may2(w2.chars[9], w2.snapshot()) is False
    w3 = World(player=(-18.0, -39.4, 16.0))
    w3.add(9, 0x1099, 254000, (-20.0, -39.4, 14.0))
    _, may3 = guard_for(w3, bound=False)
    assert may3(w3.chars[9], w3.snapshot()) is True
    print("ok  guard: at-spawn target → allowed; moved listed target off-zone/near shield → blocked; "
          "unlisted: blocked near the arena, unchanged on the ledge")


class DuelMv:
    def __init__(self, w, approach_ok=False):
        from field_fakes import FakeMv
        self._fm = FakeMv(w)
        self.w, self.tm, self.pad = w, self._fm.tm, self._fm.pad
        self.approaches = 0
        self.approach_ok = approach_ok

    def snap(self, within=40.0):
        return self.w.snapshot(within)

    find = staticmethod(lambda s, ptr: next((x for x in s.chars if x.ptr == ptr), None) if s else None)

    def guard(self, on):
        pass

    def face(self, s, c, deg=20.0):
        return True

    def stick_to(self, s, x, z, scale=1.0):
        self.approaches += 1                                    # _approach 가 경로 없이 한 걸음 내딛을 때 부른다
        if not self.approach_ok:
            raise AssertionError("다가가면 안 되는데 _approach 가 걸음을 냈다")
        return (0.0, scale)

    def light(self, s, c, n=2, sp_second=None):
        return M.Hit("light", presses=n)


def run_duel(may, wait_far, limit):
    w = World(player=ARENA, sp=100)
    w.add(3, 0x1013, 254000, (-25.9, -48.7, 24.5), anim=-1)      # 평지 가장자리에 가만히 선 #3 (6 m)
    mv = DuelMv(w, approach_ok=may is None)
    logs = []
    old = foes.of
    foes.of = lambda npc: foes.HOLLOW
    try:
        r = D.duel(mv, AXE, 3, None, log=logs.append, limit=limit, reflex=None, wait_far=wait_far,
                   may_approach=may)
    finally:
        foes.of = old
    return r, mv, logs


def test_e3_no_switch_when_unsafe() -> None:
    r, mv, logs = run_duel(lambda c, s: False, wait_far=True, limit=4.5)   # WAIT_APPROACH_S(3 s) 를 넘긴다
    assert mv.approaches == 0 and r.result == "timeout", (mv.approaches, r.result)
    r2, mv2, _ = run_duel(None, wait_far=True, limit=4.5)                  # 막지 않으면 예전처럼 붙으러 간다
    assert mv2.approaches > 0, mv2.approaches
    print(f"ok  E-3: idle #3 6 m away, unsafe → kept waiting past WAIT_APPROACH_S, no approach ({r.result}); "
          f"without guard → approached ({mv2.approaches} steps, unchanged)")


def test_e2_duel_refuses_unsafe_approach() -> None:
    r, mv, logs = run_duel(lambda c, s: False, wait_far=False, limit=5.0)
    assert r.result == "unsafe_approach" and mv.approaches == 0, (r.result, mv.approaches)
    assert any("다가가지 않음" in l for l in logs), logs
    print("ok  E-2: queue-style duel toward an unsafe target → 'unsafe_approach', no step taken")


def test_e2_approach_stops_on_stale_goal() -> None:
    w = World(player=ARENA)
    w.add(3, 0x1013, 254000, SPAWN3)                            # 경로를 짤 때 위 턱 스폰
    calls = {"n": 0}

    class NM:
        def find_path(self, a, b):
            return [a, (-26.0, -46.0, 25.0), b]

    class Mv(DuelMv):
        def walk_path(self, path, nm, mode="walk", stop=None, **kw):
            for k in range(20):                                 # 걷는 동안 #3 이 내려온다
                calls["n"] += 1
                w.move(3, (SPAWN3[0] - 0.4 * k, SPAWN3[1] - 0.5 * k, SPAWN3[2] + 0.3 * k))
                if stop(w.snapshot()):
                    return "stopped"
            return "arrived"
    mv = Mv(w)
    old = foes.of
    foes.of = lambda npc: foes.HOLLOW
    try:
        r = D._approach(mv, AXE, w.snapshot(), w.chars[3], NM(), foes.HOLLOW, lambda: False)
    finally:
        foes.of = old
    moved = ((w.chars[3].x - SPAWN3[0]) ** 2 + (w.chars[3].y - SPAWN3[1]) ** 2 + (w.chars[3].z - SPAWN3[2]) ** 2) ** 0.5
    assert r == "stopped" and 3.0 < moved < 4.5, (r, moved, calls)
    print(f"ok  E-2: target moved {moved:.1f} m from the planned goal → approach stopped (re-plan), not walked to the stale spot")


def test_clear_unsafe_no_retreat() -> None:
    w = World(player=ARENA)
    w.add(3, 0x1013, 254000, SPAWN3)
    f = make_field(w)
    seq = iter(["unsafe_approach", "killed"])

    def fight(ptr, nm, tag, arena=None, desperate=False, limit=45.0, wait_far=False, leash=None, may_approach=None):
        f.fights.append(dict(ptr=ptr, tag=tag, may=may_approach))
        r = next(seq)
        if r == "killed":
            w.chars[ptr].hp = 0
        return D.DuelResult(r)
    f.fight = fight
    f.lure_result = "no_reaction"
    r = f.clear([dict(T3)], nm=None, arena=ARENA, lure=True)
    assert r == "cleared" and f.recovers == [], (r, f.recovers)
    # 끌어오기가 첫 시도라 첫 싸움부터 '(2번째)' — unsafe_approach 는 시도로 안 세니 두 번째 싸움도 같은 번호여야 한다
    assert f.fights[0]["may"] is not None and f.fights[1]["tag"] == f.fights[0]["tag"], f.fights
    print("ok  clear: queue fight → 'unsafe_approach' → no retreat/recover, not counted as a try; guard passed to fight()")


if __name__ == "__main__":
    test_guard_predicate()
    test_e3_no_switch_when_unsafe()
    test_e2_duel_refuses_unsafe_approach()
    test_e2_approach_stops_on_stale_goal()
    test_clear_unsafe_no_retreat()
    print("전부 통과")
