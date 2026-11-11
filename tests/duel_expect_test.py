"""Are the fight rules *right*? — scenes MoKa judged, against today's duel() (docs/design-scene-expectations.md). No game.

  python tests/duel_expect_test.py            every scene in tests/expect/duel.jsonl
  python tests/duel_expect_test.py -v         also the scenes that behave as expected

duel_golden_test asks "did anything change?" (its reference is the rules' own output); this asks "does it match what MoKa
said?". One line of tests/expect/duel.jsonl = situation (tests/scene_world.py) + expect + source + status:
  pass               must meet the expectation now
  known_fail:<P-n>   an open decision (e.g. P-33) — must NOT meet it yet; when it starts to, this test fails so the line's
                     status is updated rather than the fix going unnoticed
  review             MoKa's label disagrees with the bot and no problem covers it yet — like known_fail, listed for MoKa
  needs_snapshot     the rebuild can't be trusted for this scene — listed, not run
New MoKa instruction → add 2–5 scenes here in the same commit as the rule change (source.kind "moka", quote it).
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import collections
import json
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import scene_world as W

FILE = _pl.Path(__file__).with_name("expect") / "duel.jsonl"


def load(path=FILE) -> list[dict]:
    rows = [json.loads(x) for x in open(path, encoding="utf-8") if x.strip()]
    ids = [r["id"] for r in rows]
    dup = [i for i, n in collections.Counter(ids).items() if n > 1]
    if dup:
        raise SystemExit(f"duplicate scene ids: {dup}")
    return rows


def main() -> None:
    verbose = "-v" in sys.argv
    rows = load()
    tally, bad = collections.Counter(), []
    for r in rows:
        status, kind = r.get("status", "pass"), r["source"]["kind"]
        if status == "needs_snapshot":
            tally[kind, "needs_snapshot"] += 1
            continue
        ok, why, d = W.judge(r["situation"], r["expect"])
        expected_fail = status.startswith("known_fail") or status == "review"
        if ok and not expected_fail:
            tally[kind, "pass"] += 1
            if verbose:
                print(f"  ok    {r['id']}: {d['tactic']} ({', '.join(d['rules'][:3])})")
        elif not ok and expected_fail:
            tally[kind, status] += 1
            if verbose or status == "review":
                print(f"  {status:<16} {r['id']}: {why} — {r.get('why', '')[:70]}")
        elif ok and expected_fail:
            bad.append(f"NOW PASSES {r['id']} ({status}) — the decision seems made: set status to pass (or check the change)")
        else:
            src = r["source"]
            bad.append(f"FAIL {r['id']}: {why} · rules {d['rules'][:4]} · {src['kind']} {src['ref']} {src.get('date', '')} "
                       f"«{src.get('quote', '')[:50]}» {r.get('why', '')[:60]}")
    kinds = sorted({k for k, _ in tally})
    print(f"{len(rows)} scenes from {FILE.name}: " + " · ".join(
        f"{k} " + ", ".join(f"{s} {n}" for (k2, s), n in sorted(tally.items()) if k2 == k) for k in kinds))
    for line in bad:
        print(line)
    if bad:
        sys.exit(1)
    print("ok  every scene behaves as its status says")


if __name__ == "__main__":
    main()
