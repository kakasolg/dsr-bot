"""휘두름 끝날 무렵 스틱 놓기 오프라인 테스트 — souls/moves.quiet_aim ([MoKa] 2026-10-06 제안 A).

  막는 중 적 공격이 STICK_QUIET_AGE 넘게 이어졌고 이미 30° 안을 보고 있으면 face()가 스틱을 건드리지 않게 —
  다음 R1이 스틱 놓고 기다리는 0.16 s(Pad.STICK_RELEASE_S) 없이 나간다

  python tests/stick_quiet_test.py
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import math
import sys
from types import SimpleNamespace as NS

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from souls import moves as M

fails = 0


def check(name, cond):
    global fails
    print(("  ok   " if cond else "  FAIL ") + name)
    fails += 0 if cond else 1


def aimed_at(deg):
    """A player at the origin and a foe 1.5 m away, the body turned `deg` off the foe (heading found by search, any convention)."""
    c = NS(x=0.0, y=0.0, z=1.5)
    best = None
    for k in range(3600):
        h = -math.pi + k * (2 * math.pi / 3600)
        p = NS(x=0.0, y=0.0, z=0.0, heading=h)
        off = abs(math.degrees(M.rel_angle(p, c)))
        if best is None or abs(off - deg) < abs(best[1] - deg):
            best = (p, off)
    return best[0], c


p, c = aimed_at(10)
check("swing 1.2 s old, 10° off → leave the stick alone", M.quiet_aim(p, c, 1.2))
check("swing 0.5 s old → still turn to it (the hit may be coming)", not M.quiet_aim(p, c, 0.5))
check("not attacking (age None) → normal facing", not M.quiet_aim(p, c, None))
p, c = aimed_at(45)
check("45° off → turn even late in the swing (R1 would miss)", not M.quiet_aim(p, c, 1.2))
p.heading = None
check("heading unknown → normal facing", not M.quiet_aim(p, c, 1.2))

print(f"\n{'all ok' if not fails else f'{fails} FAILED'}")
sys.exit(1 if fails else 0)
