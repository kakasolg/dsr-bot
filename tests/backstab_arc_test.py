"""P-121 / [MoKa] 11-03 "옆에 경사로가 막고 있어서 돌수도 없는데 그쪽으로 무리하게 돌다 실패": duel._arc_open sees which way round
the foe has floor all the way to its back (fake floor, no game).  python tests/backstab_arc_test.py
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import math
import sys
from types import SimpleNamespace as NS

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from souls import duel as D


def check(name: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        raise SystemExit(1)


class Floor:
    def __init__(self, ok):
        self.ok = ok

    def floor_at(self, x, z, y):
        return (0.0, 0) if self.ok(x, z) else None


def main() -> None:
    c = NS(x=0.0, y=0.0, z=0.0, heading=0.0)              # its back is +z
    p = NS(x=0.0, y=0.0, z=-1.2, gx=0.0, gy=0.0, gz=-1.2)  # we stand in front of it
    check("floor everywhere → both ways open", D._arc_open(Floor(lambda x, z: True), p, c) == (True, True))
    plus, minus = D._arc_open(Floor(lambda x, z: x > -0.05), p, c)
    check(f"slope on the −x side → only the +x way ({plus}, {minus})", (plus, minus) == (False, True))
    check("no floor round it → neither", D._arc_open(Floor(lambda x, z: abs(z) > 5), p, c) == (False, False))
    check("no NavMesh → not checked", D._arc_open(None, p, c) == (True, True))


if __name__ == "__main__":
    main()
