"""P-121: Reflex.dodge with attack — backstep + R1 as one move; no roll at a close foe (fake mv, fake floor; no game).
  python tests/reflex_dodge_attack_test.py

[MoKa] 2026-11-03: "봇은 구르기 하고 기다렸다 약공 … 백 스텝 하고 기다렸다 공격, 사이가 떠 버려. 그런데 발차기 약공은 한 동작 처럼 해"
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import math
import sys
from types import SimpleNamespace as NS

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from souls import reflex as R
from souls import style as St
from telemetry import Chr, Snapshot


def check(name: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        raise SystemExit(1)


class FakeMv:
    def __init__(self):
        self.calls: list = []
        self.pad = NS(guard=lambda on: None, move=lambda x, y: None)

    def backstep_attack(self, s, c, nm=None):
        self.calls.append("backstep_attack")
        return NS(presses=2)

    def backstep(self):
        self.calls.append("backstep")

    def combo(self, name, s, c, nm=None, need_back=0.0, need_front=3.0):
        self.calls.append(name)
        return NS(presses=2)

    def guard(self, on):
        self.calls.append(f"guard {on}")

    def face(self, s, c, deg=25.0):
        self.calls.append("face")
        return True


def scene():
    # player at the origin facing +z (heading −π → the back is −z), foe 1.2 m in front
    p = Chr(ptr=1, npc_param=0, team=1, hp=500, max_hp=600, x=0.0, y=0.0, z=0.0, sp=100, max_sp=100, heading=-math.pi)
    c = Chr(ptr=7, npc_param=255002, team=6, hp=85, max_hp=85, x=0.0, y=0.0, z=1.2, anim=3009, dist=1.2)
    return Snapshot(t=0.0, player=p, chars=[c]), c


def run(back: bool, front: bool, attack: bool, bs_ok: bool = True) -> tuple[str, list]:
    saved = R.nav.can_move
    R.nav.can_move = lambda nm, p, dx, dz, d: back if dz < 0 else front    # −z = behind, +z = toward the foe
    try:
        mv = FakeMv()
        rf = R.Reflex(mv, nm=object(), bs_ok=lambda c: bs_ok)
        s, c = scene()
        return rf.dodge(s, c, attack=attack), mv.calls
    finally:
        R.nav.can_move = saved


def main() -> None:
    check("guard style now allows the backstep attack", St.GUARD.bs_attack is True)
    kind, calls = run(back=True, front=True, attack=True)
    check(f"floor behind and ahead → backstep + R1 one move ({kind}, {calls})", kind == "bsattack" and calls == ["backstep_attack"])
    kind, calls = run(back=False, front=True, attack=True)
    check(f"no floor behind → no roll at a close foe, face it ({kind}, {calls})", kind == "hold" and "roll_r1" not in calls)
    kind, calls = run(back=True, front=True, attack=True, bs_ok=False)
    check(f"shield foe → plain backstep ({kind}, {calls})", kind == "backstep" and calls == ["backstep"])
    kind, calls = run(back=False, front=True, attack=True, bs_ok=False)
    check(f"shield foe, no floor behind → no roll, face it ({kind}, {calls})", kind == "hold" and "roll_r1" not in calls)
    kind, calls = run(back=True, front=True, attack=False)
    check(f"attack off (defend in place) → plain backstep ({kind}, {calls})", kind == "backstep" and calls == ["backstep"])


if __name__ == "__main__":
    main()
