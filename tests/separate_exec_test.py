"""Split (duel._separate) as a motion executor, and the rule-hold record (P-164; docs/tick-vs-fsm-review-2026-11-12.md §4-①②).
No game.

  python tests/separate_exec_test.py

Checks with a fake world: the walk stops at SEP_DEADLINE ('deadline') · stops once SEP_HP_ABORT of max HP is lost during it ('hp') ·
an 'arrived' walk with two foes still within PIN_R is reported 'pinned' (P-164's false success) · a clean walk stays 'arrived' ·
rule_separate stops further splits after 'pinned' · _record_hold writes a 'rule_hold' event (rule, seconds, HP and foes on us
before / after).
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import inspect
import sys
from types import SimpleNamespace as NS

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from souls import duel as D

FAILS = []


def check(what: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + what)
    if not ok:
        FAILS.append(what)


def foe(ptr, x, z, hp=75, anim=-1):
    return NS(ptr=ptr, npc_param=250050, x=x, y=0.0, z=z, hp=hp, anim=anim, team=6)


def snap(hp, foes):
    return NS(t=0.0, player=NS(x=0.0, y=0.0, z=0.0, hp=hp, max_hp=849, heading=0.0), chars=foes,
              hostile=lambda r, fs=foes: [f for f in fs if (f.x ** 2 + f.z ** 2) ** 0.5 <= r])


class Clock:
    def __init__(self):
        self.t = 1000.0

    def time(self):
        return self.t


def run(walk_snaps, end_snap, walk_result="arrived", dt=0.5):
    """_separate with a fake mv: walk_path feeds walk_snaps to stop() (clock + dt each), returns 'stopped' if stop fired."""
    clock = Clock()
    calls = []

    def walk_path(way, nm, mode, stop=None, timeout_per=10.0):
        for sn in walk_snaps:
            clock.t += dt
            if stop(sn):
                return "stopped"
        return walk_result
    mv = NS(walk_path=walk_path, guard=lambda on: calls.append(("guard", on)), snap=lambda r=10.0: end_snap,
            face=lambda s, c, deg=20.0: True, find=lambda s, ptr: next((c for c in s.chars if c.ptr == ptr), None))
    nm = NS(nearest_walkable=lambda x, y, z, r=1.5, dy=1.2: (x, y, z), clear_line=lambda a, b: True)
    a, b = foe(2, 0.0, 1.0), foe(3, 0.6, 1.0)
    s0 = snap(800, [a, b])
    real_time = D.time.time
    D.time.time = clock.time
    try:
        return D._separate(mv, s0, 2, [b], nm, None, lambda: False)
    finally:
        D.time.time = real_time


def main() -> None:
    far = [foe(2, 0.0, 6.0), foe(3, 0.6, 6.5)]
    many = [snap(800, far)] * 20                                # 20 × 0.5 s = 10 s of walking, never hit
    check(f"deadline: a walk longer than SEP_DEADLINE {D.SEP_DEADLINE} s stops → 'deadline'",
          run(many, snap(800, far)) == "deadline")
    hit = [snap(800, far), snap(760, far), snap(640, far), snap(640, far)]   # −160 = 19 % of 849 ≥ SEP_HP_ABORT
    check(f"hit while walking: ≥ {D.SEP_HP_ABORT:.0%} of max HP lost → 'hp'", run(hit, snap(640, far)) == "hp")
    on_us = [foe(2, 0.0, 0.8), foe(3, 0.5, 0.9)]
    check("P-164: walk 'arrived' but both foes still within PIN_R → 'pinned' (no false success)",
          run([snap(800, on_us)], snap(800, on_us)) == "pinned")
    check("a clean split stays 'arrived'", run([snap(800, far)], snap(800, far)) == "arrived")
    one_on = [foe(2, 0.0, 0.8), foe(3, 0.6, 5.0)]
    check("one foe close, the other split off → 'arrived' (pinned needs SEP_PINNED_N)",
          run([snap(800, one_on)], snap(800, one_on)) == "arrived")

    src = inspect.getsource(D.rule_separate)
    check("rule_separate: after 'pinned' no more splits this fight (sep_n = SEP_MAX) and a 'separate' event",
          'if r.endswith("pinned"):' in src and "F.sep_n = SEP_MAX" in src and 'ev("separate"' in src)

    ev, logs = [], []
    F = NS(mv=NS(snap=lambda r=10.0: snap(400, on_us)), events=lambda name, **k: ev.append((name, k)), log=logs.append)
    T = NS(p=NS(hp=583), s=snap(583, on_us), c=NS(npc_param=250050))
    D._record_hold(F, T, "separate", 4.3)
    check(f"_record_hold: 'rule_hold' event with rule, seconds, HP and foes on us before / after ({ev})",
          ev and ev[0][0] == "rule_hold" and ev[0][1]["rule"] == "separate" and ev[0][1]["secs"] == 4.3
          and ev[0][1]["hp0"] == 583 and ev[0][1]["hp1"] == 400 and ev[0][1]["on0"] == 2 and ev[0][1]["on1"] == 2 and logs)
    check("the duel loop times every rule call and records holds ≥ HOLD_LOG_S",
          "_record_hold(F, T, name, time.time() - t_rule)" in inspect.getsource(D._duel_loop) and D.HOLD_LOG_S == 1.0)

    if FAILS:
        print(f"separate_exec_test: {len(FAILS)} 실패")
        sys.exit(1)
    print("separate_exec_test: 전부 통과")


if __name__ == "__main__":
    main()
