"""P-31: a one-hit target with backstab room used to get swung at from 2.2–4.0 m — the backstab chance skipped
rule_approach and rule_finish (ahead of rule_backstab) had no reach check. A one-hit target is no backstab chance now:
out of reach the bot closes in (or waits, with wait_far); in reach it still finishes. --basic (BACKSTAB off) never had it.

  python tests/finish_reach_test.py
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import duel_golden_test as G

BASE = dict(foe="hollow", anim=-1, sp=90, low=True, back=False, room=True, other=False, reflex=False, style="guard")


def first(sc) -> str:
    return next(x[0] for x in G.run(sc) if x[0] not in ("log", "face", "move", "pad_guard"))


def main() -> None:
    for weapon in ("sword", "axe"):
        for h in (2.2, 4.0):
            sc = dict(BASE, h=h, wait=False, **({"weapon": "axe", "wall": None, "grip": 1, "edge": False, "arena": None, "care": False, "ground": True} if weapon == "axe" else {}))
            assert first(sc) == "approach", (weapon, h, first(sc))
    # with wait_far: wait for it (shield up), don't swing at the air
    assert first(dict(BASE, h=2.2, wait=True)) == "guard"
    # in reach: still the finishing blow; full HP at 2.2 m: still a backstab chance
    assert first(dict(BASE, h=1.0, wait=False)) == "light"
    assert first(dict(BASE, h=2.2, wait=False, low=False)) == "backstab"
    print("ok  one-hit target out of reach: approach (or wait), not a swing at the air; in reach: finish; full HP: backstab")


if __name__ == "__main__":
    main()
