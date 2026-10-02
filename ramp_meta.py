"""Derived metadata for the ramp shadow ticks and the boundary labels (LAYA.md 16) — sidecar files only; the ticks,
labels and recorded actions are not touched.

  python ramp_meta.py        → data/laya/ramp_tick_meta.jsonl, data/labels/boundary_scene_meta.jsonl

Groups (provisional data filter for this ramp recording — NOT a bot runtime rule or a navigation policy):
  navigation_not_judged  target farther than NAV_D_M or height difference over NAV_DY_M: walking to where the enemy is
                         (bonfire start, enemy on a ledge) — [MoKa] 2026-10-01: navigation, not a tactic choice
  pre_engagement         the target is asleep / not aware (no sign it is coming or fighting) — kept apart from combat
  combat                 everything else; same-plane waiting with the fight on → decision_kind combat_wait
Zone: the radar snapshot nearest to the tick's time → places.zone (rough anchor circles) and the ramp fight area
(missions.RAMP_ARENA). Estimates, never verified facts.
"""
from __future__ import annotations

import glob
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RADAR = ROOT / "data" / "radar" / "20261001_172152.jsonl"
NAV_D_M, NAV_DY_M = 10.0, 2.0
MATCH_OK_MS, MATCH_MAX_MS = 150, 1000
ARENA_R = 6.0                       # around missions.RAMP_ARENA — the zone 'ramp flat' uses the same 6 m circle
HEAD = re.compile(r'^\{"rt": ([0-9.]+), "type": "(\w+)"')
FILTER = {"name": "ramp-2026-10-01 provisional", "nav_distance_m": NAV_D_M, "nav_height_m": NAV_DY_M,
          "basis": "observed gap in these 203 ticks: excluded ≥ 8.7 m / ≥ 6.2 m, kept ≤ 6.4 m / ≤ 1.4 m",
          "not_for": "bot runtime rules or navigation policy"}


def load_ticks() -> list:
    out = []
    for fn in sorted(glob.glob(str(ROOT / "data" / "samples" / "clear-ramp-shadow-2026-10-01-a*.laya.jsonl"))):
        run = Path(fn).name.split("-")[-1].split(".")[0]
        for line in open(fn, encoding="utf-8"):
            r = json.loads(line)
            if r.get("type") == "answer":
                out.append(dict(r, run=run))
    return out


def load_snaps() -> list:
    out = []
    with RADAR.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            m = HEAD.match(line)
            if m and m.group(2) == "snap":
                s = json.loads(line)
                if (s.get("t") or 0) > 1e9 and (s.get("player") or {}).get("x") is not None:
                    out.append(s)
    return out


def nearest(snaps: list, t: float):
    lo, hi = 0, len(snaps) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if snaps[mid]["t"] < t:
            lo = mid + 1
        else:
            hi = mid
    i = min((j for j in (lo - 1, lo) if 0 <= j < len(snaps)), key=lambda j: abs(snaps[j]["t"] - t))
    return snaps[i]


def target_track(snaps: list, ptr, t0: float, t1: float) -> list:
    out = []
    for s in snaps:
        if t0 <= s["t"] <= t1:
            c = next((x for x in s.get("chars") or [] if x.get("ptr") == ptr), None)
            if c is not None:
                p = s["player"]
                out.append((s["t"], math.hypot(c["x"] - p["x"], c["z"] - p["z"]), c.get("anim")))
    return out


def engagement(snaps: list, tick: dict, snap) -> tuple[str, str]:
    """Is the fight on? Evidence from the recording around the tick (±2 s): target asleep (9000s) → not aware; distance
    to it shrinking ≥ 0.5 m → engaged (coming at us); swinging/staggered → engaged; else unknown."""
    f = tick["feat"]
    if f.get("target_state") == "asleep":
        return "not_aware", "target anim 9000s (asleep)"
    if f.get("target_state") in ("swinging", "staggered", "guard_broken", "downed", "getting_up"):
        return "engaged", f"target {f['target_state']}"
    ptr = (snap or {}).get("target")
    tr = target_track(snaps, ptr, tick["t_state"] - 2.0, tick["t_state"] + 2.0) if ptr else []
    if len(tr) >= 2 and tr[0][1] - tr[-1][1] >= 0.5:
        return "engaged", f"target closing {tr[0][1]:.1f} → {tr[-1][1]:.1f} m over {tr[-1][0] - tr[0][0]:.1f} s (radar)"
    if len(tr) >= 2:
        return "unknown", f"target distance {tr[0][1]:.1f} → {tr[-1][1]:.1f} m over {tr[-1][0] - tr[0][0]:.1f} s — not closing"
    return "unknown", "target not found in the radar around the tick"


def main() -> None:
    import places
    from souls import missions
    ticks, snaps = load_ticks(), load_snaps()
    rows = []
    for t in ticks:
        f = t["feat"]
        d, dy = f.get("distance_m"), f.get("height_diff_m")
        s = nearest(snaps, t["t_state"])
        delta = abs(s["t"] - t["t_state"]) * 1000
        p = s["player"]
        zone = places.zone(p["x"], p["y"], p["z"], en=True) if delta <= MATCH_MAX_MS else None
        arena_d = math.dist((p["x"], p["y"], p["z"]), missions.RAMP_ARENA) if delta <= MATCH_MAX_MS else None
        meta = {"run": t["run"], "seq": t["seq"], "fight": t["fight"], "npc": t.get("npc"), "rule": t["rule"], "policy": t["policy"],
                "filter": FILTER["name"],
                "zone": zone or "unknown", "zone_source": "radar snapshot nearest in time → places.zone (anchor circles)",
                "radar_timestamp": round(s["t"], 3), "match_delta_ms": round(delta, 1),
                "in_ramp_fight_area": (arena_d <= ARENA_R) if arena_d is not None else "unknown",
                "zone_confidence": ("unknown" if delta > MATCH_MAX_MS or zone is None else "high" if delta <= MATCH_OK_MS else "low"),
                "evidence_grade": "estimated"}
        if d is None or dy is None or d > NAV_D_M or abs(dy) > NAV_DY_M:
            meta["group"] = "navigation_not_judged"
            meta["group_reason"] = f"target {d} m away, height {dy:+} m — walking to where the enemy is (provisional {NAV_D_M} m / {NAV_DY_M} m)"
        else:
            eng, why = engagement(snaps, t, s)
            meta["engagement_state"], meta["engagement_evidence"] = eng, why
            if eng == "not_aware":
                meta["group"], meta["group_reason"] = "pre_engagement", why
            else:
                meta["group"] = "combat"
            if t["policy"] == "hold_position" and t["rule"] == "wait_far":
                meta.update(decision_kind="combat_wait" if eng == "engaged" else "wait_engagement_unclear",
                            same_plane=abs(dy) <= NAV_DY_M, distance_band="5-10 m" if d >= 5 else "2-5 m" if d >= 2 else "<2 m",
                            wait_reason="let_it_come (wait_far on): stand with the shield up and let it walk in")
            else:
                meta["decision_kind"] = "combat_action"
        rows.append(meta)
    out = ROOT / "data" / "laya" / "ramp_tick_meta.jsonl"
    out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    # boundary scenes: group (from their tick) + label quality, labels untouched
    nav = {(r["run"], r["seq"]): r for r in rows}
    scenes = [json.loads(l) for l in (ROOT / "data" / "labels" / "boundary_scenes.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    meta = []
    for sc in scenes:
        tm = nav[(sc["tick"]["run"], sc["tick"]["seq"])]
        meta.append({"scene_id": sc["scene_id"], "run": tm["run"], "seq": tm["seq"], "group": tm["group"],
                     "decision_kind": tm.get("decision_kind"), "label_quality": "low_resolution_pilot",
                     "label_quality_note": "game 1922×1112 → screenshots saved 960×555 → shown ~430 px wide in the label panel"})
    (ROOT / "data" / "labels" / "boundary_scene_meta.jsonl").write_text("\n".join(json.dumps(m, ensure_ascii=False) for m in meta) + "\n", encoding="utf-8")
    (ROOT / "data" / "laya" / "ramp_filter.json").write_text(json.dumps(FILTER, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(rows)} ticks → {out}; {len(meta)} boundary scenes → data/labels/boundary_scene_meta.jsonl")


if __name__ == "__main__":
    main()
