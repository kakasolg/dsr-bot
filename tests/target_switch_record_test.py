"""Target-switch records (duel._sense → scenes.Tap.switch, MoKa 2026-11-09 decision-model plan): every proposed switch is written
with the original target, the candidates and the final target; the scene of the same tick carries it and is always kept, with the
rules evaluated before the winner. Record only — decisions are the same with or without it. Golden situations, no game.
python tests/target_switch_record_test.py"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8")

import json

import duel_golden_test as G
import scenes
from souls import duel as D


def check(msg: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        raise SystemExit(1)


def main() -> None:
    sample = list(G.situations())[::40]
    plain = [G.run(sc) for sc in sample]
    sw, kept = [], []
    D.SCENE_TAP = scenes.Tap(sink=kept.append, switch_sink=sw.append)
    try:
        tapped = [G.run(sc) for sc in sample]
    finally:
        D.SCENE_TAP = None
    check(f"switch records change no decision ({len(sample)} golden situations, traces equal)", plain == tapped)
    json.loads(json.dumps(sw))
    check(f"switch records written ({len(sw)}), plain JSON", len(sw) > 50)
    for r in sw:
        assert {"from", "to", "switched", "cut", "ranged", "tick"} <= set(r), r
        assert r["switched"] == (r["from"]["ptr"] != r["to"]["ptr"]), r
        for f in [r["from"], r["to"], *r["cut"]]:
            assert {"ptr", "npc", "h", "deg", "anim", "hp", "max_hp"} <= set(f), f
    check("each record: from / candidates / to, foe = who · distance · side angle · anim · HP of max", True)
    hurt = [r for r in sw if r["switched"] and r["from"]["hp"] < r["from"]["max_hp"]]
    check(f"switches away from a damaged target are visible as such ({len(hurt)}) — the M1108-10 conflict", len(hurt) > 0)

    by_tick = {r["tick"]: r for r in sw}
    with_sw = [k for k in kept if k.get("switch")]
    check(f"the scene of a switch tick is kept and carries the same record ({len(with_sw)} of {len(sw)})",
          len(with_sw) == len(sw) and all(by_tick[k["tick"]["id"]] == k["switch"] for k in with_sw))
    names = D._RULE_NAMES
    ok = all(k["declined"] == names[:names.index(k["rule"])] for k in kept if "declined" in k and k["rule"] in names)
    check("'declined' = exactly the rules before the winner (later ones were not evaluated)", ok and any("declined" in k for k in kept))

    D.SCENE_TAP = scenes.Tap(sink=lambda rec: None)              # default switch_sink with a custom sink → dropped, no error
    try:
        G.run(sample[0])
        errs = D.SCENE_TAP.errors
    finally:
        D.SCENE_TAP = None
    check("a custom scene sink without a switch sink: switch records dropped, no errors", errs == 0)
    print("target_switch_record_test: 전부 통과")


if __name__ == "__main__":
    main()
