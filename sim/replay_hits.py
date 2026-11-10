"""Recorded big hits vs the foes' attack capsules in the replay room (MoKa M1109-59, hitbox step 1).

  python sim/replay_hits.py [<run>]          → table: per recorded hit, the attacker's capsule closest approach to the bot

For each big hit (data/runs/<run>.hits.jsonl, via the replay file) the room is asked (headless dump) for the attacker's
active AtkParam_Npc capsules every 1/60 s from 1.5 s before the recorded HP drop to 0.2 s after. Each capsule is
compared with the bot's body axis — a vertical segment BODY_LO..BODY_HI above the recorded feet position [guess: the
bot's own body capsules are not read yet] — and the table gives the gap = distance between the capsule's segment and
the axis − capsule radius. A gap ≤ body radius (≈ 0.3–0.4 m, also not read) means the capsule reaches the body.

What it does not show: whether the engine tests the capsule only at each update or swept between updates, the bot's
real pose (it is a stand-in in the room), i-frames / guard, or which part of the body was touched.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sim import godot_link as GL  # noqa: E402

BODY_LO, BODY_HI = 0.3, 1.5     # [guess] bot body axis above the feet, metres
STEP = 1.0 / 60.0
BEFORE, AFTER = 1.5, 0.2


def seg_dist(p0, p1, q0, q1) -> float:
    """Closest distance between segments p0p1 and q0q1."""
    p0, p1, q0, q1 = map(np.asarray, (p0, p1, q0, q1))
    d1, d2, r = p1 - p0, q1 - q0, p0 - q0
    a, e, f = d1 @ d1, d2 @ d2, d2 @ r
    if a < 1e-12 and e < 1e-12:
        return float(np.linalg.norm(r))
    if a < 1e-12:
        s, t = 0.0, np.clip(f / e, 0, 1)
    else:
        c = d1 @ r
        if e < 1e-12:
            t, s = 0.0, np.clip(-c / a, 0, 1)
        else:
            b = d1 @ d2
            den = a * e - b * b
            s = np.clip((b * f - c * e) / den, 0, 1) if den > 1e-12 else 0.0
            t = (b * s + f) / e
            if t < 0:
                t, s = 0.0, np.clip(-c / a, 0, 1)
            elif t > 1:
                t, s = 1.0, np.clip((b - c) / a, 0, 1)
    return float(np.linalg.norm((p0 + d1 * s) - (q0 + d2 * t)))


def dump(times: list) -> list:
    r = subprocess.run([str(GL.GODOT), "--headless", "--path", str(ROOT / "sim" / "godot"), "res://replay.tscn", "--",
                        "--dump=" + ",".join(f"{x:.4f}" for x in times)], capture_output=True, text=True,
                       encoding="utf-8", timeout=900)
    line = next((x for x in r.stdout.splitlines() if x.startswith("REPLAY_DUMP ")), None)
    if line is None:
        raise SystemExit("replay dump failed:\n" + r.stdout[-2000:] + r.stderr[-2000:])
    return json.loads(line[len("REPLAY_DUMP "):])


def check(run: str) -> list:
    rp = json.loads((ROOT / "data" / "replays" / f"{run}.json").read_text(encoding="utf-8"))
    hits = rp["hits"]
    times = sorted({round(h["t"] + k * STEP, 4) for h in hits
                    for k in range(int(-BEFORE / STEP), int(AFTER / STEP) + 1)})
    got = {round(g["t"], 4): g for g in dump(times)}
    rows = []
    for h in hits:
        key = str(h["id"])
        best = None
        other = None            # closest capsule of any other foe (the hit log's attacker is the logger's guess)
        active = []
        for k in range(int(-BEFORE / STEP), int(AFTER / STEP) + 1):
            tt = round(h["t"] + k * STEP, 4)
            g = got.get(tt)
            if g is None or "p" not in g["chars"]:
                continue
            px, py, pz = g["chars"]["p"][:3]
            axis = ([px, py + BODY_LO, pz], [px, py + BODY_HI, pz])
            for who, caps in g.get("caps", {}).items():
                for c0, c1, rad, _typ, atk in caps:
                    gap = seg_dist(c0, c1, *axis) - rad
                    if who == key:
                        if not active or active[-1] != tt:
                            active.append(tt)
                        if best is None or gap < best[0]:
                            best = (gap, tt, atk)
                    elif other is None or gap < other[0]:
                        other = (gap, tt, atk, who)
        rows.append({"t": h["t"], "attacker": key, "npc": h["npc"], "anim": h["anim"], "hp": [h["hp0"], h["lo"]],
                     "recorded_dist": h.get("d"),
                     "window": [active[0], active[-1]] if active else None,
                     "closest_gap": round(best[0], 3) if best else None,
                     "at": best[1] if best else None, "atk": best[2] if best else None,
                     "other": {"foe": other[3], "gap": round(other[0], 3), "at": other[1], "atk": other[2]} if other else None})
    return rows


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    run = sys.argv[1] if len(sys.argv) > 1 else "20261109_021816_burg-bonfire"
    rows = check(run)
    print(f"{run}: bot body axis {BODY_LO}–{BODY_HI} m above the feet [guess]; gap = capsule surface to that axis")
    print(f"{'hit t':>7} {'foe':>4} {'npc':>7} {'anim':>5} {'HP':>11} {'d rec':>6}  {'capsule live (room)':>19}  {'closest gap':>11} {'at':>7}   other foe's closest capsule")
    for r in rows:
        w = f"{r['window'][0]:.2f}–{r['window'][1]:.2f}" if r["window"] else "none"
        g = f"{r['closest_gap']:+.2f} m" if r["closest_gap"] is not None else "—"
        at = f"{r['at']:.2f}" if r["at"] is not None else "—"
        print(f"{r['t']:7.2f} {'#' + r['attacker']:>4} {r['npc']:>7} {r['anim']:>5} {r['hp'][0]:>5}→{r['hp'][1]:<5} "
              f"{r['recorded_dist'] or 0:6.2f}  {w:>19}  {g:>11} {at:>7}   "
              + (f"#{r['other']['foe']} {r['other']['gap']:+.2f} m at {r['other']['at']:.2f}" if r["other"] else "none"))
    out = ROOT / "data" / "replays" / f"{run}.hits_check.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
