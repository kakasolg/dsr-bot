"""HP below 30 % → drink now, in place (MoKa 11-12, M1112-02). No game.

  python tests/low_sip_test.py

Checks: Field.recover drinks first (before any roll / light / walking back) when HP < duel.LOW_SIP_HP and Estus is left,
with no safety check; above the line or with no Estus it doesn't. duel.rule_low_sip is first in RULES (the fight scenes
are in tests/expect/duel.jsonl, ids low-sip-*).
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
from souls import field as F

FAILS = []


def check(what: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + what)
    if not ok:
        FAILS.append(what)


def foe(d):
    return NS(x=0.0, y=0.0, z=d, hp=75, anim=-1, npc_param=250050, ptr=7)


def snap_at(hp, foes):
    return NS(player=NS(hp=hp, max_hp=793, x=0.0, y=0.0, z=0.0), hostile=lambda r, fs=foes: [f for f in fs if f.z <= r])


def fake(hp: int, estus: int, foe_d: float = 20.0):
    calls = []
    snaps = [snap_at(hp, [foe(foe_d)]), snap_at(0, [])]        # after the sip: hp 0 → recover stops there
    me = NS(estus_left=lambda: estus, log=lambda *a: None, events=lambda *a, **k: None,
            safe=lambda s: calls.append("safe") or False)
    me.mv = NS(snap=lambda r=15.0: snaps.pop(0) if snaps else snap_at(0, []),
               drink=lambda safe: calls.append(("drink", safe(None))) or {"ok": True})
    return me, calls


def main() -> None:
    check("rule_low_sip is first in RULES", D.RULES[0] is D.rule_low_sip and D.LOW_SIP_HP == 0.30)
    me, calls = fake(hp=180, estus=2)                     # 23 %, nearest foe 20 m → room 5 s
    r = F.Field.recover(me, "low_hp")
    check(f"recover at 23 % HP with Estus and room (foe 20 m): drinks first, no safety check ({calls})",
          calls[:1] == [("drink", True)] and "safe" not in calls and r is False)
    for hp, est, what in ((280, 2, "35 % HP"), (180, 0, "no Estus")):
        me, calls = fake(hp=hp, estus=est)
        try:
            F.Field.recover(me, "low_hp")
        except Exception:
            pass                                          # the fake has nothing for the rest of recover — only the first call matters
        check(f"recover with {what}: no in-place sip first ({calls[:1]})", not calls or calls[0] != ("drink", True))
    # M1112-03 "50% 물러남 없애줘": no HP retreat line; the 'losing' retreat keeps its own switch
    import inspect
    fsrc = inspect.getsource(F.Field._fight_once)
    check("Field: RETREAT_HP 0 (no HP retreat line), losing on unless the fight is to the end",
          F.RETREAT_HP == 0.0 and "losing=not desperate" in fsrc)
    check("duel: 'losing' reads its own switch (falls back to low_hp > 0 when not given, e.g. scene_replay)",
          "losing" in inspect.signature(D.duel).parameters
          and 'F.losing if getattr(F, "losing", None) is not None else F.low_hp > 0' in inspect.getsource(D._sense))
    check("the low_hp line with low_hp 0 stays 0 even with two foes close (CROWD_LOW_HP stays off)",
          D._low_hp_line(NS(player=NS(x=0, y=0, z=0), hostile=lambda r: []), 0.0) == 0.0)

    # M1112-04/05/17: room to drink = (distance − FOE_REACH) / FOE_CHASE_V ≥ SIP_MARGIN_S
    check("sip_margin: foe 15 m → 3.6 s, foe 1 m → 0, asleep / other level / none → inf",
          abs(D.sip_margin(snap_at(800, [foe(15.0)])) - 13.0 / 3.6) < 1e-6 and D.sip_margin(snap_at(800, [foe(1.0)])) == 0.0
          and D.sip_margin(snap_at(800, [NS(x=0, y=0, z=1.0, hp=75, anim=9001)])) == float("inf")
          and D.sip_margin(snap_at(800, [NS(x=0, y=5.0, z=1.0, hp=75, anim=-1)])) == float("inf")
          and D.sip_margin(snap_at(800, [])) == float("inf") and D.SIP_MARGIN_S == 3.0)
    # recover with a foe on us → sip_run: sprint toward home, stop at room, drink
    run = {}
    me, calls = fake(hp=180, estus=2, foe_d=1.0)
    me.tether, me.home = None, (0.0, 0.0, -30.0)
    seq = [snap_at(180, [foe(d)]) for d in (2.0, 6.0, 12.0, 15.0)]
    after = [snap_at(180, [foe(15.0)]), snap_at(180, [foe(15.0)]), snap_at(0, [])]
    snaps = [snap_at(180, [foe(1.0)])] + after

    def walk_path(path, nm, mode, stop=None, **k):
        run["mode"] = mode
        for sn in seq:
            if stop(sn):
                run["stopped_at"] = sn.hostile(99)[0].z
                return "stopped"
        return "arrived"
    me.mv = NS(snap=lambda r=15.0: snaps.pop(0) if snaps else snap_at(0, []), walk_path=walk_path,
               drink=lambda safe: calls.append(("drink", safe(None))) or {"ok": True})
    nm = NS(find_path=lambda a, b: [a, b])
    F.nav.trim_path, trim0 = (lambda path, goal: path), F.nav.trim_path
    try:
        F.Field.recover(me, "low_hp", nm)
    finally:
        F.nav.trim_path = trim0
    check(f"recover, HP 23 %, foe 1 m: sprints toward home, stops once room ≥ 3 s (foe 15 m), then drinks ({run}, {calls[:1]})",
          run.get("mode") == "sprint" and run.get("stopped_at") == 15.0 and calls[:1] == [("drink", True)])
    rsrc = inspect.getsource(F.Field.retreat)
    check("retreat (P-173): sprints when HP < 30 %, stops to drink once room ≥ SIP_MARGIN_S",
          'return "sprint"' in rsrc and "D.sip_margin(sn) >= D.SIP_MARGIN_S" in rsrc and 'low_sip.get("hit")' in rsrc)

    if FAILS:
        print(f"low_sip_test: {len(FAILS)} 실패")
        sys.exit(1)
    print("low_sip_test: 전부 통과")


if __name__ == "__main__":
    main()
