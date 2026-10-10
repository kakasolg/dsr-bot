"""Exact-input scenes (scenes.py) and their replay (scene_replay.py) — docs/design-scene-expectations.md 3.3. No game.

  python tests/scene_replay_test.py

Checks:
  · round trip: fights run with the tap on (MoKa's expectation scenes + golden situations without a fake NavMesh), every
    kept decision replayed from its record → the same rule, 100 %
  · the tap doesn't change a single decision (golden traces with and without it are equal) and never raises — not even
    when its sink raises
  · which decisions are kept: attacks etc. always; a pose rule (block, wait …) only while the target staggers or winds up,
    once per change
  · a real run's scene whose body was 42.5° off replays to the same rule (the fake face() answers like Moves.face)
  · timestamps / sets / int-keyed dicts survive restore() with a new clock
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import collections
import itertools
import json
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import duel_expect_test as E
import duel_golden_test as G
import scene_replay as R
import scene_world as W
import scenes
from souls import duel as D


def check(name: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        raise SystemExit(1)


def golden_sample(step: int = 9) -> list[dict]:
    """golden situations whose floor checks aren't faked: no stand-in NavMesh (the terrain / axe sets hand duel one with no
    map id, which a replay can't load — real runs record the map and replay loads data/samples/navmesh_<map>.npz) and
    room behind the foe (golden patches duel._room_behind to say 'no room'; with no NavMesh the real check says yes)."""
    return [sc for sc in G.situations() if sc["room"]][::step]


def main() -> None:
    got: list = []
    D.SCENE_TAP = scenes.Tap(sink=got.append)
    try:
        for r in E.load():
            W.decide(r["situation"])
        n_expect = len(got)
        for sc in golden_sample():
            G.run(sc)
    finally:
        D.SCENE_TAP = None
    json.loads(json.dumps(got))                                    # records are plain JSON
    same = collections.Counter(R.replay(r) == r["rule"] for r in got)
    bad = [(r["rule"], R.replay(r)) for r in got if R.replay(r) != r["rule"]][:5]
    check(f"round trip: {len(got)} kept decisions ({n_expect} from the expectation scenes) replay to the same rule — {bad}",
          len(got) > 300 and same[False] == 0)
    rules = collections.Counter(r["rule"] for r in got)
    check(f"kept: attacks and pose rules in a stagger both appear ({dict(rules.most_common(6))})",
          all(rules[k] > 0 for k in ("stagger_punish", "finish_first", "attack")) and any(k in D.FOLD_RULES for k in rules))

    sample = golden_sample(37)
    plain = [G.run(sc) for sc in sample]
    D.SCENE_TAP = scenes.Tap(sink=lambda rec: None)
    try:
        tapped = [G.run(sc) for sc in sample]
    finally:
        D.SCENE_TAP = None
    check(f"the tap changes no decision ({len(sample)} golden situations, traces equal)", plain == tapped)

    def boom(rec):
        raise RuntimeError("sink down")
    tap = scenes.Tap(sink=boom)
    D.SCENE_TAP = tap
    try:
        traces = [G.run(sc) for sc in sample[:40]]
    finally:
        D.SCENE_TAP = None
    check("a failing sink: no raise, decisions unchanged, errors counted",
          traces == plain[:40] and tap.errors > 0 and "errors" in tap.summary())

    # which decisions are kept
    from types import SimpleNamespace as NS
    kept = []
    tap = scenes.Tap(sink=kept.append)
    F = NS(foe=NS(windup=(3004,)))
    T = lambda a: NS(a=a, c=NS(ptr=2))
    for rule, a in (("block", 3003), ("block", 3500), ("block", 3500), ("wait_far", 3500), ("block", 3004), ("attack", -1)):
        tap.pre = {"x": 1}
        tap.decided(F, T(a), rule, D.CONT)
    check("pose rule kept only in a stagger / windup and once per change; attacks always",
          [k["rule"] for k in kept] == ["block", "wait_far", "block", "attack"])

    # 2026-10-09 burg-upper run: body 42.5° off an HP 11 foe — the game's face(deg=30) said no, so finish_first passed and
    # after_swing (deg 45) acted; a replay whose face() always says yes picked finish_first
    rec = json.loads((_pl.Path(__file__).resolve().parent / "expect" / "scene_after_swing_42deg.json").read_text(encoding="utf-8"))
    check(f"real scene, body 42.5° off: replay face() answers like Moves.face → {R.replay(rec)}", R.replay(rec) == "after_swing")

    now = 2_000_000_000.0
    v = scenes._plain({"t": now - 1.5, "s": {3, 4}, "d": {7: (1.0, now - 0.2)}, "x": [now + 2]}, now)
    back = scenes.restore(v, 100.0)
    check("restore: times shift to the new clock, sets and int keys come back",
          abs(back["t"] - 98.5) < 1e-9 and back["s"] == {3, 4} and abs(back["d"][7][1] - 99.8) < 1e-6 and abs(back["x"][0] - 102.0) < 1e-9)
    print("scene_replay_test: 전부 통과")


if __name__ == "__main__":
    main()
