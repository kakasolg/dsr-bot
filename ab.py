"""Compare bot runs by their settings first, then their results (docs/design-run-settings.md 3.5).

  python ab.py RUN_A RUN_B [RUN_C …]          run ids (<stamp>_<cmd>), logs, or .settings.json files
  python ab.py RUN_A RUN_B --want args.basic  the one difference you meant — anything else that differs is a warning

Shows what differs between the runs (code commit / uncommitted changes / arguments / constants / data / start HP, Estus)
and each run's end (result, seconds). A/B results only mean something when the runs differ in what you meant to change.
"""
from __future__ import annotations

import argparse
import sys

import runinfo

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SKIP = {"argv", "note", "started", "run", "settings_sha1", "schema", "end", "args.note"}


def flat(d, pre: str = "") -> dict:
    out = {}
    for k, v in (d or {}).items():
        key = f"{pre}{k}"
        if isinstance(v, dict):
            out.update(flat(v, key + "."))
        else:
            out[key] = v
    return out


def differences(recs: list[dict]) -> dict:
    """{key: [value per run]} for every setting that isn't the same in all runs (game state: HP and Estus only)."""
    fl = []
    for d in recs:
        f = flat({k: v for k, v in d.items() if k not in ("game", "end")})
        g = d.get("game") or {}
        f["game.hp"], f["game.estus"] = g.get("hp"), g.get("estus")
        fl.append(f)
    keys = sorted(set().union(*fl))
    return {k: [f.get(k) for f in fl] for k in keys
            if k not in SKIP and not k.startswith("code.diff") and len({repr(f.get(k)) for f in fl}) > 1}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--want", action="append", default=[], help="a setting you meant to differ (e.g. args.basic); repeatable")
    a = ap.parse_args()
    recs, names = [], []
    for ref in a.runs:
        f = runinfo.find(ref)
        d = runinfo.read(f) if f else None
        if d is None:
            print(f"{ref}: no settings file (a run from before runinfo?) — can't compare")
            return
        recs.append(d)
        names.append(d.get("run", ref))
    for n, d in zip(names, recs):
        e = d.get("end") or {}
        print(f"{n}: {runinfo.short(d)}")
        print(f"    end: {e.get('result', '(no end — still running or crashed)')} · {e.get('secs', '?')} s")
    diff = differences(recs)
    if not diff:
        print("settings: the same in every run")
        return
    print("settings that differ:")
    for k, vs in diff.items():
        mark = "  " if k in a.want else "⚠ "
        print(f"  {mark}{k}: " + " | ".join(repr(v) for v in vs))
    extra = [k for k in diff if k not in a.want]
    if a.want and extra:
        print(f"⚠ {len(extra)} more difference(s) than --want — the results may not be from the change you meant")


if __name__ == "__main__":
    main()
