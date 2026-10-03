"""3타째 오프라인 테스트 (P-39 (1), [MoKa] 2026-10-03) — 먼저 치기 2연타가 그놈을 약공 한 번 몫(FINISH_HP 이하)으로 남기면
그놈 동작과 상관없이 곧바로 한 번 더. 수용소 위층 망자: 2연타 64 → HP 5, 그 틈에 반격과 옆 망자.

  python tests/duel_third_test.py
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from duel_wall_heavy_test import Mv, Nm
from field_fakes import World
from souls import duel as D
from souls import moves as M
from souls import weapons


class HpMv(Mv):
    """Each light takes `per` HP per press (the first call is the 2-hit combo); the foe swings back after the combo."""
    def __init__(self, world, target_ptr, per, swing_back=3000):
        super().__init__(world, target_ptr)
        self.per, self.swing_back, self.calls = per, swing_back, []

    def light(self, s, c, n=2, sp_second=None):
        self.calls.append(n)
        ch = self.w.chars[c.ptr]
        dmg = min(ch.hp, self.per * n)
        ch.hp -= dmg
        ch.anim = self.swing_back if ch.hp > 0 else -1
        return M.Hit("light", presses=n, dmg=dmg, dead=ch.hp <= 0)


def run(hp=69, per=32, ticks=1, sp=98):
    w = World(player=(0.0, -49.4, 0.0), sp=sp, max_sp=98, hp=616)
    w.add(2, 0x1018, 250022, (0.0, -49.4, 1.2), anim=-1, hp=hp, max_hp=69)
    mv = HpMv(w, 2, per)
    mv.tm.grip = lambda: 1
    n = {"k": 0}

    def cancel():
        n["k"] += 1
        return n["k"] > ticks
    logs = []
    r = D.duel(mv, weapons.BATTLE_AXE, 2, Nm(3.0), log=logs.append, cancel=cancel, reflex=None, gen=0, events=lambda *a, **k: None)
    return mv, logs, r


def test_third_finishes() -> None:
    mv, logs, r = run(hp=69, per=32)                 # 2 × 32 = 64 → HP 5 → third
    assert mv.calls == [2, 1], mv.calls
    assert r.result == "killed" and any("3타째 (HP 5)" in l for l in logs), (r.result, logs[-3:])
    print("ok  light×2 leaves HP 5 (foe swinging back) → third light at once, killed")


def test_no_third_when_tough() -> None:
    mv, logs, r = run(hp=69, per=20, ticks=1)         # 2 × 20 = 40 → HP 29 > FINISH_HP
    assert mv.calls == [2], mv.calls
    print(f"ok  light×2 leaves HP 29 (> {D.FINISH_HP}) → no third")


def test_no_third_when_dead() -> None:
    mv, logs, r = run(hp=60, per=32)                  # 64 ≥ 60 → dead after two
    assert mv.calls == [2] and r.result == "killed", (mv.calls, r.result)
    print("ok  combo kills → no third")


if __name__ == "__main__":
    test_third_finishes()
    test_no_third_when_tough()
    test_no_third_when_dead()
    print("전부 통과")
