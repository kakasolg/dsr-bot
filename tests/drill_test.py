"""P-121 drill (run.py --drill): only the chosen attack — set up distance / floor first, never swap to another attack (no game).
  python tests/drill_test.py

[MoKa] 2026-11-03: "이 초반 공격은 내가 원하는 특정 공격을 유도 할 수 있어야해. 가장 쉬운 장소에 약한 상대 들이 잖아."
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import sys
import time
from types import SimpleNamespace as NS

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from souls import combo_table as CTB
from souls import duel as D

HOLLOW = NS(kind="other", ranged=False)


def check(name: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        raise SystemExit(1)


class Mv:
    def __init__(self):
        self.calls = []

    def step(self, s, x, z, secs, guard=True):
        self.calls.append(("step", round(x, 1), round(z, 1)))

    def backstep(self):
        self.calls.append(("backstep",))

    def guard(self, on):
        pass

    def roll_toward(self, s, x, z, hold=False):
        self.calls.append(("roll", round(x, 1), round(z, 1)))


def fight():
    return NS(mv=Mv(), nm=None, log=lambda *_: None, events=lambda *_a, **_k: None, foe=HOLLOW, hp_start=600)


def run(drill, h, anim=-1, back=True, front=True, phase="hit", F=None, hp=600, others=()):
    D.DRILL = drill
    F = F or fight()
    p = NS(x=0.0, y=0.0, z=0.0, heading=0.0, hp=hp, max_hp=698)
    c = NS(ptr=7, npc_param=254000, x=0.0, y=0.0, z=h, anim=anim, hp=80)
    s = NS(player=p, hostile=lambda r: [c] + list(others))
    k = CTB.key(h, HOLLOW, anim, back, front)
    try:
        return D._drill_setup(F, s, c, k, h, back, front, phase), F
    finally:
        D.DRILL = None


def main() -> None:
    r, F = run("backstep_r1", 0.9)
    check("백스텝 드릴 0.9 m, 바닥 있음 → 지금 침", r is None and F.mv.calls == [])
    r, F = run("backstep_r1", 1.6)
    check(f"백스텝 드릴 1.6 m → 더 다가가지 않음, 지금 침 (182931: 1.15 m까지 다가가 서서 휘두르는 놈에 5번 누름) ({F.mv.calls})",
          r is None and F.mv.calls == [])
    r, F = run("backstep_r1", 3.0)
    check(f"백스텝 드릴 3.0 m → 다가가지 않고 기다림 (오면 2.3 m에서 B) ({F.mv.calls})", r is not None and r.kind == "wait"
          and not [x for x in F.mv.calls if x[0] == "step"])
    F = fight(); g, locks = [], []
    F.mv.guard = lambda on: g.append(on); F.mv.lock_state = lambda p: "none"
    F.mv.lock_target = lambda p, tries=3: locks.append(tries) or True
    r, F = run("backstep_r1", 3.0, F=F)
    check(f"기다리는 동안 방패 내림 · 락온 미리 1번 ({g}, {locks})", g and g[-1] is False and locks == [1])
    r, F = run("backstep_r1", 6.0)
    check(f"백스텝 드릴 6.0 m → 5 m 안까지 다가감 ({F.mv.calls})", r is not None and F.mv.calls and F.mv.calls[0][0] == "step")
    # 그립 (P-121 · P-123): 망자 1:1 → 양손, 다른 놈 근처 → 그대로 한손
    for name, others, g0, want in (("망자 1:1, 한손 → 양손으로", (), 1, 1), ("망자인데 4 m에 다른 놈 → 한손 그대로", (
            NS(ptr=8, npc_param=255010, x=4.0, y=0.0, z=0.0, anim=-1, hp=80),), 1, 0), ("이미 양손 → 안 건드림", (), 3, 0)):
        F = fight(); toggles = []
        F.mv.tm = NS(grip=lambda g0=g0: g0); F.mv.pad = NS(two_hand_right=lambda: toggles.append(1))
        F.events = lambda *_a, **_k: None
        run("backstep_r1", 3.0, F=F, others=others)
        check(f"백스텝 드릴 기다리며 그립: {name} ({len(toggles)})", len(toggles) == want)
    F = fight(); F._drill_idle_t = {("bs", 7): time.time() - 4.0}
    r, F = run("backstep_r1", 4.2, F=F)
    check(f"4.2 m에서 4 s 안 옴 → 한 걸음 ({F.mv.calls})", F.mv.calls and F.mv.calls[0][0] == "step")
    F = fight(); F._drill_idle_t = {("bs", 7): time.time() - 4.0}
    r, F = run("backstep_r1", 3.2, F=F)
    check(f"3.2 m (< 3.5)에선 안 와도 더 안 다가감 ({F.mv.calls})", not [x for x in F.mv.calls if x[0] == "step"])
    r, F = run("backstep_r1", 0.9, anim=3000)
    check("휘두르는 중 → 기다림, 움직임 없음", r is not None and r.kind == "wait" and F.mv.calls == [])
    # [MoKa] 11-03 "거리가 없으면 어떻게 구르기를 해?" — 붙은 뒤 벌리지 않음 (140350 · 140920 낙사), 이 놈은 표대로
    r, F = run("roll_r1", 1.0)
    check(f"구르기 드릴 1.0 m 붙음 → 벌리지 않고 표대로 ({F.mv.calls})", r is None and F.mv.calls == []
          and F._drill_n[7] > D.DRILL_SETUPS)
    r, F = run("roll_r1", 1.0, phase="entry")
    check("진입 단계에서 이미 붙음 → 진입 안 함", r is not None and r.kind == "entry" and F.mv.calls == [])
    r, F = run("jump_r2", 4.0)
    check("점프 드릴 4.0 m → 지금", r is None)
    r, F = run("jump_r2", 5.5)
    check(f"점프 드릴 5.5 m → 다가가지 않고 기다림 (방패 내림) ({F.mv.calls})", r is not None and r.kind == "wait"
          and not [x for x in F.mv.calls if x[0] == "step"])
    r, F = run("jump_r2", 8.0)
    check(f"점프 드릴 8.0 m → 7 m 안까지 다가감 ({F.mv.calls})", F.mv.calls and F.mv.calls[0][0] == "step")
    two = [NS(ptr=8, npc_param=254002, x=1.0, y=0.0, z=1.0, anim=3000, hp=80)]
    r, F = run("backstep_r1", 1.6, anim=3003, others=two)
    check("두 놈 붙음 → 드릴 그만 (표대로)", r is None and F._drill_n[7] > D.DRILL_SETUPS and F.mv.calls == [])
    r, F = run("backstep_r1", 1.6, hp=350)
    check("이 싸움에서 250 맞음 → 드릴 그만", r is None and F._drill_n[7] > D.DRILL_SETUPS)
    r, F = run("backstep_r1", 1.0, phase="entry")
    check("백스텝 드릴은 진입 안 함", r is not None and r.kind == "entry")
    F = fight()
    for _ in range(D.DRILL_SETUPS):
        run("backstep_r1", 6.0, F=F)
    r, F = run("backstep_r1", 6.0, F=F)
    check("8번 다가감 뒤 → 포기 (기본 싸움)", r is None)
    F = fight()
    for _ in range(D.DRILL_SETUPS + 3):
        run("roll_r1", 6.0, front=False, F=F)
    check(f"앞막힘은 1 s에 한 번만 셈 ({F._drill_n})", F._drill_n.get(7) == 1)
    # 135152 · 140006 · 140350: 기다림(rule_wait_far)이 진입보다 먼저 걸려 진입 0번 → 기다리는 중에도 진입을 먼저 시도
    seen, saved = [], D._entry_try
    D._entry_try = lambda F, T: seen.append(T.h) or "entry"
    try:
        F = NS(weapon=NS(reach=1.6), wait_far=True, foe=HOLLOW, wait_hp0=None, style=NS(shield=True), mv=Mv())
        T = NS(s=None, c=None, p=NS(hp=600), h=3.0, now=0.0, backstab_chance=False)
        r = D.rule_wait_far(F, T)
    finally:
        D._entry_try = saved
    check(f"기다리는 중 3.0 m → 진입 시도 ({seen})", r == "entry" and seen == [3.0])

    # [MoKa] 11-03 "실패 하더라도 거리를 미리 계산 하고 해야지" — 2 m/s로 오는 놈, 구르기 누름→닿음 0.9 s: 4.0 m → 닿을 때 2.2 m
    D.DRILL = "roll_r1"
    try:
        F = fight(); F._hv = {7: (0.0, 4.0, 2.0)}
        he = D._entry_h(F, NS(ptr=7), 4.0)
    finally:
        D.DRILL = None
    check(f"다가오는 놈 → 닿을 때 거리로 계산 ({he:.2f} m)", abs(he - (4.0 - 2.0 * D.ENTRY_LEAD["roll_r1"])) < 1e-6)
    F = fight()
    check("멀어지는 놈은 당겨 계산하지 않음", D._entry_h(F, NS(ptr=7), 3.0) == 3.0)

    # [MoKa] 11-03 "콤보는 적을 락업 하는 게 필수야" — 락온 없으면 콤보 누르지 않고 기다림
    saved = D.COMBO_ONLY
    D.COMBO_ONLY = True
    try:
        mv = Mv(); mv.lock_state = lambda ptr: "none"
        F = NS(mv=mv, nm=None, log=lambda *_: None, events=lambda *_a, **_k: None, foe=HOLLOW, hp_start=600,
               weapon=NS(reach=1.6, combo=2))
        p = NS(x=0.0, y=0.0, z=0.0, heading=0.0, hp=600, max_hp=698, anim=-1)
        c = NS(ptr=7, npc_param=254000, x=0.0, y=0.0, z=0.9, anim=-1, hp=80)
        r = D._combo_strike(F, NS(player=p, hostile=lambda r: [c]), c)
    finally:
        D.COMBO_ONLY = saved
    check(f"락온 안 걸림 → 콤보 안 누름 ({r.kind}: {r.skipped})", r.kind == "wait" and "락온" in r.skipped and mv.calls == [])


if __name__ == "__main__":
    main()
