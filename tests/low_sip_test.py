"""HP below 30 % → drink now, in place (MoKa 11-12, M1112-02). No game.

  python tests/low_sip_test.py

Checks: Field.recover drinks first (before any roll / light / walking back) when HP < duel.LOW_SIP_HP and Estus is left,
with no safety check; above the line or with no Estus it doesn't. duel.rule_low_sip is first in RULES (the fight scenes
are in tests/expect/duel.jsonl, ids low-sip-*).
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

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


def fake(hp: int, estus: int):
    calls = []
    snaps = [NS(player=NS(hp=hp, max_hp=793)), NS(player=NS(hp=0, max_hp=793))]   # after the sip: hp 0 → recover stops there
    me = NS(estus_left=lambda: estus, log=lambda *a: None, events=lambda *a, **k: None,
            safe=lambda s: calls.append("safe") or False)
    me.mv = NS(snap=lambda r=15.0: snaps.pop(0) if snaps else NS(player=NS(hp=0, max_hp=793)),
               drink=lambda safe: calls.append(("drink", safe(None))) or {"ok": True})
    return me, calls


def main() -> None:
    check("rule_low_sip is first in RULES", D.RULES[0] is D.rule_low_sip and D.LOW_SIP_HP == 0.30)
    me, calls = fake(hp=180, estus=2)                     # 23 %
    r = F.Field.recover(me, "low_hp")
    check(f"recover at 23 % HP with Estus: drinks first, no safety check ({calls})",
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

    if FAILS:
        print(f"low_sip_test: {len(FAILS)} 실패")
        sys.exit(1)
    print("low_sip_test: 전부 통과")


if __name__ == "__main__":
    main()
