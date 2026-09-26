"""제자리로 돌아가는 경로 첫 구간이 깨어 있는 놈 쪽이면 걷지 않고 제자리 방어 (observe 160200 #6).

  python field_return_leg_test.py
"""
from __future__ import annotations

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from field_fakes import World, make_field

ARENA = (-30.0, -49.25, 29.0)
HERE = (-20.7, -40.5, 19.1)                    # #6 던질 자리
FOE6 = (-23.1, -34.1, 10.2)                     # 내려오는 #6


class NM:
    def __init__(self, first):
        self.first = first

    def find_path(self, a, b):
        return [a, self.first, b]


def run(first):
    w = World(player=HERE)
    w.add(6, 0x1017, 254000, FOE6, anim=3005)
    f = make_field(w)
    st, _ = f._hold_at(ARENA, NM(first), "평지", w.snapshot())
    return st, f


def test_leg_toward_foe_defends() -> None:
    st, f = run((-19.6, -39.9, 17.0))           # 첫 구간이 동쪽(#6 쪽)
    assert st == "returning" and not f.walks and f.mv.guards[-1] is True, (st, f.walks, f.mv.guards)
    st2, f2 = run((-22.5, -42.5, 21.5))          # 첫 구간이 평지 쪽
    assert f2.walks, (st2, f2.walks)
    print("ok  return leg: first leg toward the awake #6, not toward the arena → guard in place, no walk; "
          "leg toward the arena → walks as before")


if __name__ == "__main__":
    test_leg_toward_foe_defends()
    print("전부 통과")
