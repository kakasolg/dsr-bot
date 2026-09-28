"""How does a human land a backstab? — from observe_record.py recordings (player, foes, lock-on, pad), no game needed.

  python backstab_report.py data/samples/observe_backstab_*.jsonl

A backstab = a foe's HP drops to 0 while the player is within 0.8 m of it, right after an R1 press (the game snaps the
player behind the foe: distance → ~0.6 m, behind angle → 180°). For each one it prints the approach (from 2.5 s before):
distance, behind angle (0° = in front of the foe, 180° = straight behind), how far the player's facing is off the foe
("aim"), stick size, lock-on, foe animation — and every R1 press near that foe with what it turned into.
Also lists R1 presses from behind (≥ 120°) that gave only a normal hit, with the foe's animation at the press.
"""
from __future__ import annotations

import glob
import json
import math
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

R1 = 0x200
KILL_R = 0.8
WINDOW_S = 2.5


def _ang(a: float) -> float:
    return abs(math.degrees((a + math.pi) % (2 * math.pi) - math.pi))


def rows_of(path: str) -> tuple[list[dict], list[dict]]:
    w, pads = [], []
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("k") == "w":
                w.append(r)
            elif r.get("k") == "pad":
                pads.append(r)
    return sorted(w, key=lambda r: r["ms"]), sorted(pads, key=lambda r: r["ms"])


def geometry(r: dict, e: dict) -> dict:
    """Player vs foe e in world row r. Facing = heading + π (dsr_telemetry convention)."""
    p = r["p"]
    px, pz, ex, ez = p["pos"][0], p["pos"][2], e["pos"][0], e["pos"][2]
    return {"d": math.hypot(px - ex, pz - ez),
            "behind": _ang(math.atan2(px - ex, pz - ez) - (e["hd"] + math.pi)),
            "aim": _ang(math.atan2(ex - px, ez - pz) - (p["hd"] + math.pi)),
            "lock": (r.get("lock") or {}).get("h") not in (-1, None),
            "foe_anim": e.get("anim"), "my_anim": p.get("anim")}


def pad_at(pads: list[dict], ms: float) -> dict:
    out = {}
    for q in pads:
        if q["ms"] > ms:
            break
        out = q
    return out


def backstabs(w: list[dict]) -> list[tuple[float, str]]:
    last, out = {}, []
    for r in w:
        for e in r.get("e") or []:
            if last.get(e["id"], 0) > 0 and e.get("hp_raw") == 0 and e.get("d", 9) < KILL_R:
                out.append((r["ms"], e["id"]))
            last[e["id"]] = e.get("hp_raw") or 0
    return out


def r1_presses(pads: list[dict]) -> list[float]:
    out, prev = [], 0
    for q in pads:
        b = q.get("btn") or 0
        if b & R1 and not prev & R1:
            out.append(q["ms"])
        prev = b
    return out


def report(path: str) -> str:
    w, pads = rows_of(path)
    lines = [f"== {path}"]
    for t_ms, eid in backstabs(w):
        seq = []
        for r in w:
            if t_ms - WINDOW_S * 1000 <= r["ms"] <= t_ms:
                e = next((e for e in r.get("e") or [] if e["id"] == eid), None)
                if e:
                    g = geometry(r, e)
                    q = pad_at(pads, r["ms"])
                    g["stick"] = math.hypot(q.get("lx", 0), q.get("ly", 0)) / 32768
                    g["t"] = (r["ms"] - t_ms) / 1000
                    seq.append(g)
        presses = [ms for ms in r1_presses(pads) if t_ms - WINDOW_S * 1000 <= ms <= t_ms]
        lines.append(f"backstab at {t_ms / 1000:.1f} s ({eid})")
        for ms in presses:
            g = min(seq, key=lambda g: abs(g["t"] - (ms - t_ms) / 1000)) if seq else None
            if g:
                lines.append(f"  R1 {(ms - t_ms) / 1000:+.1f} s: behind {g['behind']:.0f}°, {g['d']:.2f} m, aim {g['aim']:.0f}°, "
                             f"lock {'on' if g['lock'] else 'off'}, foe anim {g['foe_anim']}, my anim {g['my_anim']}")
        close = [g for g in seq if g["d"] < 1.0 and g["t"] < ((presses[-1] - t_ms) / 1000 if presses else 0)]
        if close:
            lines.append(f"  circling ≤1 m: {len(close) / 10:.1f} s, distance {min(g['d'] for g in close):.2f}–{max(g['d'] for g in close):.2f} m, "
                         f"behind {close[0]['behind']:.0f}° → {close[-1]['behind']:.0f}°, stick {min(g['stick'] for g in close):.2f}–"
                         f"{max(g['stick'] for g in close):.2f}, lock-on {sum(g['lock'] for g in close)}/{len(close)}, "
                         f"aim ≤ {max(g['aim'] for g in close):.0f}°")
    # R1 from behind that did not backstab
    kill_ms = [t for t, _ in backstabs(w)]
    for ms in r1_presses(pads):
        if any(0 <= k - ms <= 1500 for k in kill_ms):
            continue
        r = min(w, key=lambda r: abs(r["ms"] - ms))
        near = [e for e in r.get("e") or [] if e.get("d", 9) < 1.2 and (e.get("hp_raw") or 0) > 0]
        for e in near:
            g = geometry(r, e)
            if g["behind"] >= 120:
                lines.append(f"  no backstab: R1 at {ms / 1000:.1f} s from behind {g['behind']:.0f}°, {g['d']:.2f} m, "
                             f"foe anim {g['foe_anim']} (lock {'on' if g['lock'] else 'off'})")
    return "\n".join(lines)


def main() -> None:
    paths = sys.argv[1:] or sorted(glob.glob("data/samples/observe_backstab_*.jsonl"))
    print("\n\n".join(report(p) for p in paths))


if __name__ == "__main__":
    main()
