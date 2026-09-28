"""_lure: 던질 자리로 걷는 중 그놈이 죽으면(따라와 walk 안에서 잡힘) 시체에 던지지 않고 'dead' (observe 155129 #4).

  python field_lure_dead_test.py
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from field_fakes import World, make_field
from souls import field as F

SPOT = (-23.6, -42.4, 21.5)


def test_target_dies_during_walk() -> None:
    w = World(player=(-30.0, -49.25, 29.0))
    w.add(4, 0x1016, 254001, (-13.15, -39.07, 11.73))
    f = make_field(w)
    del f.lure                                             # 진짜 lure/_lure 를 쓴다
    f._asleep = lambda ptr, hold=0.4: True
    f._settle = lambda spot, tol=None, tries=10: 0.0
    f.mv.tm.goods_count = lambda item: 20
    f.mv.cam_target = None
    throws = []
    f.mv.throw_knife = lambda ptr, **kw: throws.append(ptr) or {"ok": True, "locked": False}

    def walk_to(goal, nm, tag, mode="walk", tol=None):
        w.chars[4].hp = 0                                  # 걷는 동안 따라와서 잡혔다
        w.player.x, w.player.y, w.player.z = goal
        return "arrived"
    f.walk_to = walk_to
    r = F.Field.lure(f, 4, [-13.15, -39.07, 11.73], None, "#4", arena=(-30.0, -49.25, 29.0),
                     lure_at={"spot": SPOT, "min": 0.0, "max": 14.5, "knives": 1})
    assert r == "dead" and not throws, (r, throws)
    print("ok  lure: target killed while walking to the throw spot → 'dead', no throw at the corpse")


if __name__ == "__main__":
    test_target_dies_during_walk()
    print("전부 통과")
