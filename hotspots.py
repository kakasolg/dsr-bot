"""Where does the bot trip over the same spot, run after run? — from run logs, no game needed.

  python hotspots.py                               data/samples/*.txt and data/runs/*.log
  python hotspots.py data/runs/2026*_burg-bonfire.log ...
  python hotspots.py --min-runs 2 --radius 3
  python hotspots.py --all                         the old full list (every place in ≥ --min-runs runs)

By default only the newest run (--last 1) is compared with the ones before it: NEW places (first time), AGAIN places
(this run and earlier ones too), and places that went wrong in ≥ 2 earlier runs but not this time (GONE) —
so a fix's effect shows up without scrolling through every old run.

Reads the text logs run.py writes (data/runs/<stamp>_<mission>.log) and pulls every walking problem with a position:
  point-fail  "<tag>: i/n번 점 (x, y, z) 못 감 (reason, k번째) — 나 (x, y, z), d m"
  smash       "<tag>: 길 막은 oXXXX (name) 부숨 시도 — (x,y,z)"
then groups them by place (within --radius m) and lists the places that went wrong in --min-runs runs or more.
A walk that got stuck and recovered on its own still leaves these lines, so this finds the mistakes that never show up
as damage or death (ROADMAP 1-e). Numbers are what the log says.
"""
from __future__ import annotations

import argparse
import glob
import math
import os
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
_T = re.compile(r"^\[ *([\d.]+)\]\s*(.*)$")
_FAIL = re.compile(r"(?P<tag>.+?): (?P<i>\d+)/(?P<n>\d+)번 점 \((?P<q>[^)]*)\) 못 감 \((?P<why>\w+), (?P<k>\d+)번째\) — "
                   r"나 \((?P<me>[^)]*)\), (?P<d>[\d.]+) m")
_SMASH = re.compile(r"(?P<tag>.+?): 길 막은 (?P<model>\w+) \((?P<name>\w+)\) 부숨 시도 — \((?P<q>[^)]*)\)")


def _vec(s: str) -> tuple[float, float, float]:
    x, y, z = (float(v) for v in s.split(","))
    return x, y, z


def parse(path: str) -> list[dict]:
    """Walking problems in one log."""
    out = []
    for line in open(path, encoding="utf-8", errors="replace"):
        m = _T.match(line.rstrip())
        if not m:
            continue
        t, body = float(m[1]), m[2].strip()
        f = _FAIL.search(body)
        s = _SMASH.search(body) if not f else None
        if f:
            me = _vec(f["me"])
            q = _vec(f["q"])
            out.append({"run": path, "t": t, "kind": "point-fail", "tag": f["tag"].strip(), "why": f["why"], "pos": q,
                        "me": me, "dy": round(q[1] - me[1], 2), "point": f"{f['i']}/{f['n']}"})
        elif s:
            out.append({"run": path, "t": t, "kind": "smash", "tag": s["tag"].strip(), "why": s["name"], "pos": _vec(s["q"])})
    return out


def group(events: list[dict], radius: float = 3.0) -> list[dict]:
    """Places: events within radius (horizontal) of the first event of a group."""
    places: list[dict] = []
    for e in events:
        for p in places:
            if math.hypot(p["pos"][0] - e["pos"][0], p["pos"][2] - e["pos"][2]) <= radius and abs(p["pos"][1] - e["pos"][1]) < 2.0:
                p["events"].append(e)
                break
        else:
            places.append({"pos": e["pos"], "events": [e]})
    for p in places:
        p["runs"] = sorted({e["run"] for e in p["events"]})
    return sorted(places, key=lambda p: (-len(p["runs"]), -len(p["events"])))


def report(places: list[dict], n_runs: int, min_runs: int = 2) -> str:
    lines = [f"{n_runs} runs, {sum(len(p['events']) for p in places)} walking problems, "
             f"{sum(1 for p in places if len(p['runs']) >= min_runs)} places in ≥{min_runs} runs"]
    for p in places:
        if len(p["runs"]) < min_runs:
            continue
        x, y, z = p["pos"]
        kinds = {}
        for e in p["events"]:
            kinds[f"{e['kind']}:{e['why']}"] = kinds.get(f"{e['kind']}:{e['why']}", 0) + 1
        lines.append(f"\n● ({x:.1f}, {y:.1f}, {z:.1f})  {len(p['runs'])}/{n_runs} runs  "
                     + ", ".join(f"{k}×{v}" for k, v in kinds.items()))
        for e in p["events"]:
            extra = f"  me ({e['me'][0]:.1f}, {e['me'][1]:.1f}, {e['me'][2]:.1f}) height {e['dy']:+.1f} m" if "me" in e else ""
            lines.append(f"    {Path(e['run']).name}  {e['t']:6.1f} s  {e['tag']}  {e.get('point', '')}{extra}")
    return "\n".join(lines)


def dedupe(runs: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """Drop logs that are copies of another one (a run's log copied into data/samples/ was counted twice, ROADMAP P-12):
    same problems at the same times and places = same run. Logs with no problems are kept (they still count as runs)."""
    seen: dict[tuple, str] = {}
    out = {}
    for path, evs in runs.items():
        key = tuple((e["t"], e["kind"], e["pos"]) for e in evs)
        if evs and key in seen:
            continue
        seen.setdefault(key, path)
        out[path] = evs
    return out


def compare(runs: dict[str, list[dict]], last: int = 1, radius: float = 3.0) -> str:
    """The newest `last` runs (in the given order) vs the rest: NEW / AGAIN / GONE places."""
    names = list(runs)
    now, before = names[-last:], names[:-last]
    ps = group([e for evs in runs.values() for e in evs], radius)
    new, again, gone = [], [], []
    for p in ps:
        n_now = [r for r in p["runs"] if r in now]
        n_before = [r for r in p["runs"] if r in before]
        if n_now and not n_before:
            new.append(p)
        elif n_now:
            again.append(p)
        elif len(n_before) >= 2:
            gone.append(p)
    lines = [f"this time: {', '.join(Path(r).name for r in now)}  vs {len(before)} earlier runs"]

    def row(p, label):
        x, y, z = p["pos"]
        mine = [e for e in p["events"] if e["run"] in now]
        items = sorted({f"{e['kind']}:{e['why']} {re.sub(r'( 돌아서)+', ' 돌아서', e['tag'])}" for e in mine or p["events"]})
        what = ", ".join(items[:4]) + (f" (+{len(items) - 4} more)" if len(items) > 4 else "")
        b = len([r for r in p["runs"] if r in before])
        return f"  {label:5} ({x:.1f}, {y:.1f}, {z:.1f})  earlier {b}/{len(before)} runs  {what}"
    lines += [row(p, "NEW") for p in new] + [row(p, "AGAIN") for p in again] + [row(p, "GONE") for p in gone[:10]]
    if not new and not again:
        lines.append("  no walking problems this time")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("logs", nargs="*")
    ap.add_argument("--min-runs", type=int, default=2)
    ap.add_argument("--radius", type=float, default=3.0)
    ap.add_argument("--last", type=int, default=1, help="how many newest runs count as 'this time'")
    ap.add_argument("--all", action="store_true", help="old full report")
    a = ap.parse_args()
    logs = a.logs or sorted(glob.glob(str(ROOT / "data" / "samples" / "*.txt")) + glob.glob(str(ROOT / "data" / "runs" / "*.log")),
                            key=os.path.getmtime)   # newest run last — by name, data/samples/ sorted after data/runs/ and a copy became "this time"
    runs = dedupe({p: parse(p) for p in logs})
    if not a.all:
        print(compare(runs, a.last, a.radius))
        return
    events = [e for evs in runs.values() for e in evs]
    print(report(group(events, a.radius), len(runs), a.min_runs))


if __name__ == "__main__":
    main()
