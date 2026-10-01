"""셋 이상 붙으면 벽으로 물러나 하나씩 — 오프라인 테스트 (P-29, [MoKa] 2026-09-30: "벽으로 물러나서 하나씩").

  duel: wall_ok 이고 움직이는 적이 셋 이상(목표 포함) 4 m 안인데 벽(Navmesh.wall_dist) 옆이 아니면 'crowd' + wall_back 으로 끝남.
        벽 옆이면 그대로 싸움. 셋 이상 붙어 있으면 뒤잡기로 돌지 않음 (T.room 끔)
  Field.back_to_wall: 적 반대쪽·낭떠러지(drop) 먼 벽 자리로 가드 든 채 걸어감. 모서리 먼저. 자리 없으면 그 자리에서 싸움
  Navmesh.edge_kinds: 열린 경계를 seam(같은 높이 바닥) · drop(1.5 m 넘게 아래 바닥) · wall(바닥 없음)로 나눔

  python tests/field_wall_back_test.py
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import math
import sys
import time

import numpy as np

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from duel_shadow_test import DuelMv
from field_fakes import World, make_field
import navmesh
from souls import duel as D
from souls import field as F
from souls import weapons

AXE = weapons.BATTLE_AXE


class Nm:
    """Flat floor; a wall along x = WALL_X (and nothing else). Spots are given."""
    def __init__(self, wall_x=None, spots=(), drop_at=None):
        self.wall_x, self.spots, self.drop_at = wall_x, list(spots), drop_at

    def wall_dist(self, x, y, z, dy=2.0):
        return float("inf") if self.wall_x is None else abs(x - self.wall_x)

    def drop_dist(self, x, y, z, dy=2.0):
        return float("inf") if self.drop_at is None else math.hypot(x - self.drop_at[0], z - self.drop_at[2])

    def wall_spots(self, x, y, z, r=10.0, dy=1.0):
        return [(q, n) for q, n in self.spots if math.hypot(q[0] - x, q[2] - z) <= r]

    def find_path(self, a, b):
        return [tuple(a), tuple(b)]

    def __getattr__(self, name):                 # anything else the duel asks the NavMesh: "don't know"
        return lambda *a, **k: None


def three(w, anims=(3000, 3003, 3004)):
    w.add(2, 0x1018, 254010, (1.0, -49.4, 0.0), anim=anims[0])
    w.add(3, 0x1019, 254010, (0.0, -49.4, 1.2), anim=anims[1])
    w.add(4, 0x101A, 254010, (-0.8, -49.4, 0.8), anim=anims[2])


def duel(w, nm, wall_ok=True, ticks=4):
    mv = DuelMv(w, 2)
    mv.tm.grip = lambda: 1
    n = {"k": 0}

    def cancel():
        n["k"] += 1
        return n["k"] > ticks
    return D.duel(mv, AXE, 2, nm, log=lambda *a: None, cancel=cancel, reflex=None, gen=0, events=lambda *a, **k: None,
                  wall_ok=wall_ok)


def test_duel_wall_back() -> None:
    w = World(player=(0.0, -49.4, 0.0), sp=90, hp=682)
    three(w)
    r = duel(w, Nm(wall_x=None))
    assert r.result == "crowd" and r.wall_back, (r.result, r.wall_back)
    r = duel(w, Nm(wall_x=0.5))                                          # back already 0.5 m from a wall: stay
    assert not r.wall_back and r.result != "crowd", (r.result, r.wall_back)
    r = duel(w, Nm(wall_x=None), wall_ok=False)
    assert not r.wall_back and r.result != "crowd", r.result
    w2 = World(player=(0.0, -49.4, 0.0), sp=90, hp=682)
    three(w2, anims=(3000, 3003, -1))                                    # third one standing still doesn't count
    r = duel(w2, Nm(wall_x=None))
    assert not r.wall_back, r.result
    print("ok  duel: 3 moving foes away from a wall → crowd + wall_back; at a wall / wall_ok off / 2 moving → keep fighting")


def test_no_backstab_in_crowd() -> None:
    old = D.CIRCLE_MAX_SWEEPS
    D.CIRCLE_MAX_SWEEPS = 3
    tried = []
    rb, bs = D._room_behind, D._backstab
    D._room_behind = lambda *a, **k: True
    D._backstab = lambda *a, **k: (tried.append(1), "not_behind")[1]
    try:
        w = World(player=(0.0, -49.4, 0.0), sp=90, hp=682)
        three(w)
        duel(w, Nm(wall_x=0.5), ticks=6)                                 # at a wall: fights on, three on us
        assert not tried, "backstab tried with three on us"
        w2 = World(player=(0.0, -49.4, 0.0), sp=90, hp=682)
        w2.add(2, 0x1018, 254010, (1.0, -49.4, 0.0), anim=3000)
        w2.add(3, 0x1019, 254011, (0.0, -49.4, 1.2), anim=3003)              # 2:1 (MoKa 2026-10-01: past the secret passage)
        duel(w2, Nm(wall_x=0.5), ticks=6)
        assert not tried, "backstab tried at 2:1"
        w1 = World(player=(0.0, -49.4, 0.0), sp=90, hp=682)
        w1.add(2, 0x1018, 254010, (1.0, -49.4, 0.0), anim=3000)
        duel(w1, Nm(wall_x=0.5), ticks=6)
        assert tried, "one foe: backstab should still be tried"
    finally:
        D.CIRCLE_MAX_SWEEPS, D._room_behind, D._backstab = old, rb, bs
    print("ok  two or three on us → no backstab circling; one foe → backstab as before")


def test_back_to_wall_picks_spot() -> None:
    w = World(player=(0.0, -49.4, 0.0), hp=682)
    three(w)                                                             # foes around +x/+z
    f = make_field(w)
    f.events = lambda *a, **k: None
    walked = {}

    def walk_path(path, nm, mode="walk", stop=None, **kw):
        walked["to"], walked["mode"] = path[-1], mode
        w.player.x, w.player.z = path[-1][0], path[-1][2]
        return "stopped" if stop(w.snapshot()) else "arrived"
    f.mv.walk_path = walk_path
    toward = ((3.0, -49.4, 2.0), 1)                                      # toward the foes — never
    corner = ((-5.0, -49.4, -4.0), 2)
    plain = ((-3.0, -49.4, -1.0), 1)
    cliffy = ((-2.0, -49.4, -2.0), 2)                                    # a corner, but a drop 1 m away
    nm = Nm(wall_x=-5.0, spots=[toward, plain, corner, cliffy], drop_at=(-2.0, -49.4, -3.0))
    r = f.back_to_wall(nm)
    assert r == "stopped" and walked["mode"] == "guard", (r, walked)
    assert walked["to"] == corner[0], walked
    assert f._wall_off_until > time.time() + F.WALL_OFF_S - 1.0
    assert any("벽으로" in l for l in f.logs), f.logs
    f2 = make_field(World(player=(0.0, -49.4, 0.0), hp=682))
    f2.events = lambda *a, **k: None
    three(f2.mv.w)
    assert f2.back_to_wall(Nm(spots=[toward])) == "no_spot"
    print("ok  back_to_wall: away from the foes, no drop close, corner first, guard up; nothing fit → fight in place")


def test_edge_kinds() -> None:
    """Two floor squares joined at x = 2 (a seam), a lower floor beyond x = 4 on one side (drop), nothing elsewhere (wall)."""
    nm = navmesh.Navmesh.__new__(navmesh.Navmesh)
    v = np.array([[0, 0, 0], [2, 0, 0], [2, 0, 2], [0, 0, 2],          # A 0-3
                  [2, 0, 0], [4, 0, 0], [4, 0, 2], [2, 0, 2],          # B 4-7 (same height, its own piece → seam at x=2)
                  [4.5, -5, -1], [9, -5, -1], [9, -5, 3], [4.5, -5, 3]], dtype=float)   # C 8-11, 5 m below, beyond x=4
    t = np.array([[0, 1, 2], [0, 2, 3], [4, 5, 6], [4, 6, 7], [8, 9, 10], [8, 10, 11]])
    adj = np.array([[-1, -1, 1], [0, -1, -1], [-1, -1, 3], [2, -1, -1], [-1, -1, 5], [4, -1, -1]])
    nm.v, nm.t, nm.adj, nm.flags = v, t, adj, np.zeros(len(t), dtype=int)
    nm.centroid = (v[t[:, 0]] + v[t[:, 1]] + v[t[:, 2]]) / 3.0
    nm.a, nm.b, nm.c = v[t[:, 0]], v[t[:, 1]], v[t[:, 2]]
    k = nm.edge_kinds()
    assert len(k["seam"][0]) >= 1 and len(k["drop"][0]) >= 1 and len(k["wall"][0]) >= 1, {a: len(b[0]) for a, b in k.items()}
    assert nm.drop_dist(3.8, 0, 1.0) < 0.5                               # next to x=4, the lower floor is beyond
    assert nm.wall_dist(0.1, 0, 1.0) < 0.5                               # x=0 side: nothing beyond
    assert nm.wall_dist(2.0, 0, 1.0) > 0.5                               # the seam at x=2 is not a wall
    print(f"ok  edge_kinds: seam / drop / wall ({ {a: len(b[0]) for a, b in k.items()} })")


if __name__ == "__main__":
    test_duel_wall_back()
    test_no_backstab_in_crowd()
    test_back_to_wall_picks_spot()
    test_edge_kinds()
    print("전부 통과")
