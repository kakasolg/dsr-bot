"""Planned path vs where the bot actually went — from track files or radar recordings, no game needed (ROADMAP 1-e / 0-b).

  python track_report.py                          newest data/runs/*.track.jsonl
  python track_report.py data/runs/*.track.jsonl  several runs: stall places compared run by run
  python track_report.py data/radar/2026*.jsonl   radar recordings work too (same format)

For every walk (one planned path, "path_tag" + "path") it prints: time, planned length vs walked distance, how far off
the planned line the bot got (max/mean, horizontal), whether it reached the end, and the stalls — ≥ STALL_S seconds
moving slower than STALL_V with no live foe within FOE_R (so waiting for / fighting a foe doesn't count).
Then the stall places over all files: a place that stalls in several runs is a mistake the bot repeats even when it
gets through in the end. The numbers are only what the records hold (2 Hz track, 10 Hz radar).
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
STALL_V = 0.3        # m/s
STALL_S = 1.0        # s
FOE_R = 6.0          # m
HOSTILE = (6, 7, 24, 25, 27, 33)
PLACE_R = 3.0


def frames(path: str) -> list[dict]:
    """[{t, p, tag, path, foe}] — path carried forward when a line leaves it out (track files write it only on change)."""
    out, cur_tag, cur_path = [], None, None
    for line in open(path, encoding="utf-8", errors="replace"):
        try:
            m = json.loads(line)
        except ValueError:
            continue
        if m.get("type") != "snap" or not m.get("player"):
            continue
        if "path" in m:
            cur_path = [tuple(q) for q in m["path"]] if m["path"] else None
            cur_tag = m.get("path_tag") if cur_path else None
        elif "path_tag" not in m and "rt" in m and "chars" in m and cur_path is not None and _is_radar(m):
            cur_path, cur_tag = None, None             # radar recording: no path in the message = not walking
        pl = m["player"]
        p = (pl["x"], pl["y"], pl["z"])
        foe = any(c.get("team") in HOSTILE and (c.get("hp") or 0) > 0 and math.hypot(c["x"] - p[0], c["z"] - p[2]) < FOE_R
                  and abs(c["y"] - p[1]) < 3.0 for c in m.get("chars") or [] if c.get("ptr") != pl.get("ptr"))
        out.append({"t": float(m["rt"]), "p": p, "tag": cur_tag, "path": cur_path, "foe": foe})
    return out


def _is_radar(m: dict) -> bool:
    return "cam_yaw" in m                                # radar sends the whole snapshot; track files don't


def seg_dist(p, a, b) -> float:
    """Horizontal distance from p to segment a-b."""
    ax, az, bx, bz = a[0], a[2], b[0], b[2]
    dx, dz = bx - ax, bz - az
    L = dx * dx + dz * dz
    u = 0.0 if L == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[2] - az) * dz) / L))
    return math.hypot(p[0] - ax - u * dx, p[2] - az - u * dz)


def off_path(p, path) -> float:
    if len(path) == 1:
        return math.hypot(p[0] - path[0][0], p[2] - path[0][2])
    return min(seg_dist(p, path[k], path[k + 1]) for k in range(len(path) - 1))


def walks(fr: list[dict]) -> list[dict]:
    """Split frames into walks (same planned path)."""
    out, cur = [], None
    for f in fr:
        if f["path"] is None:
            cur = None
            continue
        if cur is None or f["path"] is not cur["path"] and f["path"] != cur["path"]:
            cur = {"tag": f["tag"], "path": f["path"], "fr": []}
            out.append(cur)
        cur["fr"].append(f)
    return [w for w in out if len(w["fr"]) >= 2]


def stalls(fr: list[dict]) -> list[dict]:
    """Stretches ≥ STALL_S slower than STALL_V with no foe near."""
    out, start = [], None
    for a, b in zip(fr, fr[1:]):
        dt = b["t"] - a["t"]
        v = math.hypot(b["p"][0] - a["p"][0], b["p"][2] - a["p"][2]) / dt if dt > 0 else 0.0
        slow = dt > 0 and v < STALL_V and not a["foe"] and not b["foe"]
        if slow and start is None:
            start = a
        if (not slow or b is fr[-1]) and start is not None:
            end = b if slow else a
            if end["t"] - start["t"] >= STALL_S:
                out.append({"t": start["t"], "s": round(end["t"] - start["t"], 1), "p": start["p"]})
            start = None
    return out


def summarize(w: dict) -> dict:
    fr, path = w["fr"], w["path"]
    plan = sum(math.hypot(path[k + 1][0] - path[k][0], path[k + 1][2] - path[k][2]) for k in range(len(path) - 1))
    walked = sum(math.hypot(b["p"][0] - a["p"][0], b["p"][2] - a["p"][2]) for a, b in zip(fr, fr[1:]))
    offs = [off_path(f["p"], path) for f in fr if not f["foe"]] or [0.0]
    end = fr[-1]["p"]
    return {"tag": w["tag"], "t0": fr[0]["t"], "dur": round(fr[-1]["t"] - fr[0]["t"], 1), "plan": round(plan, 1),
            "walked": round(walked, 1), "off_max": round(max(offs), 2), "off_mean": round(sum(offs) / len(offs), 2),
            "reached": math.hypot(end[0] - path[-1][0], end[2] - path[-1][2]) < 1.5 and abs(end[1] - path[-1][1]) < 2.0,
            "fight_s": round(sum(b["t"] - a["t"] for a, b in zip(fr, fr[1:]) if a["foe"]), 1),
            "stalls": stalls(fr)}


def report_run(path: str) -> tuple[str, list[dict]]:
    ws = [summarize(w) for w in walks(frames(path))]
    lines = [f"== {Path(path).name}: {len(ws)} walks, stalls {sum(len(w['stalls']) for w in ws)} "
             f"({sum(s['s'] for w in ws for s in w['stalls']):.1f} s)"]
    for w in ws:
        flag = "" if w["reached"] else "  NOT REACHED"
        lines.append(f"  {w['t0']:7.1f} s  {w['tag']}: {w['dur']} s (fight {w['fight_s']} s), plan {w['plan']} m / walked "
                     f"{w['walked']} m, off path max {w['off_max']} m mean {w['off_mean']} m{flag}")
        for s in w["stalls"]:
            lines.append(f"      stall {s['s']} s at ({s['p'][0]:.1f}, {s['p'][1]:.1f}, {s['p'][2]:.1f})  {s['t']:.1f} s")
    stall_list = [{"run": path, "tag": w["tag"], **s} for w in ws for s in w["stalls"]]
    return "\n".join(lines), stall_list


def places(stall_list: list[dict], runs: list[str]) -> str:
    groups: list[dict] = []
    for s in stall_list:
        for g in groups:
            if math.hypot(g["p"][0] - s["p"][0], g["p"][2] - s["p"][2]) <= PLACE_R and abs(g["p"][1] - s["p"][1]) < 2.0:
                g["items"].append(s)
                break
        else:
            groups.append({"p": s["p"], "items": [s]})
    groups.sort(key=lambda g: (-len({s["run"] for s in g["items"]}), -sum(s["s"] for s in g["items"])))
    lines = [f"\n== stall places over {len(runs)} runs (seconds per run, oldest → newest)"]
    for g in groups:
        per = [sum(s["s"] for s in g["items"] if s["run"] == r) for r in runs]
        n = sum(1 for v in per if v > 0)
        if len(runs) > 1 and n < 2:
            continue
        tags = sorted({s["tag"] for s in g["items"] if s["tag"]})
        lines.append(f"  ({g['p'][0]:.1f}, {g['p'][1]:.1f}, {g['p'][2]:.1f})  {n}/{len(runs)} runs  "
                     f"[{' '.join(f'{v:.0f}' if v else '·' for v in per)}]  {', '.join(tags)}")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("files", nargs="*")
    ap.add_argument("--quiet", action="store_true", help="only the stall places, not every walk")
    a = ap.parse_args()
    files = a.files or sorted(glob.glob(str(ROOT / "data" / "runs" / "*.track.jsonl")))[-1:]
    if not files:
        print("no track files — run the bot once (run.py writes data/runs/<stamp>_<name>.track.jsonl)")
        return
    all_stalls = []
    for f in files:
        text, st = report_run(f)
        all_stalls += st
        if not a.quiet:
            print(text)
    print(places(all_stalls, files))


if __name__ == "__main__":
    main()
