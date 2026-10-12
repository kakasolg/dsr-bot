"""Taurus Demon attacks: for each of its attack anims, where we stood when it started and whether it hit
([MoKa] 2026-10-12: "보스 애니를 보고 이런 경우는 피해진다는 데이타 및 이런 경우는 반드시 피격 당한다는 데이타를 쌓아야 해").

  python taurus_report.py                 every source below
  python taurus_report.py --json out.json also write the instances

Sources (all read-only):
  data/observe/*.jsonl                    MoKa's recordings with the boss in them (10 Hz)
  data/runs|samples/*_taurus.track.jsonl  bot tries (2 Hz — an attack shows up in 1–4 frames)
  data/runs|samples/*_taurus.jsonl        `taurus` events what=attack written by souls/taurus.py (every fight tick, exact)

One instance = the boss enters an attack anim (3000–3099) until the anim changes. At its start: h (horizontal distance to its
center), ang (where we stand off its facing: 0 = right in front, ±180 = behind, + = its right), dy, our anim. Hit = our HP
dropped while it ran or within HIT_AFTER_S after (its blows land late in the anim).
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import math
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
TAURUS = 225000
HIT_AFTER_S = 0.6
NEAR_M = 8.0
H_BINS = ((0.0, 1.5), (1.5, 3.0), (3.0, 5.0), (5.0, NEAR_M))
ANG_BINS = (("앞", 0, 60), ("옆", 60, 120), ("뒤", 120, 181))


def ang_off(boss, me) -> float:
    """Where `me` stands off the boss's facing, degrees (0 front, ±180 behind). Raw heading: world yaw = heading + π."""
    fwd = boss["hd"] + math.pi
    a = math.atan2(me["x"] - boss["x"], me["z"] - boss["z"]) - fwd
    return math.degrees((a + math.pi) % (2 * math.pi) - math.pi)


def my_kind(anim) -> str:
    a = anim if anim is not None else -1
    if a == -1:
        return "서 있음/걷기"
    if 300000 <= a < 310000:
        return "공격 중"
    if 700 <= a < 800:
        return "구르기/백스텝"
    if 7580 <= a < 7590:
        return "에스트"
    if 2000 <= a < 2100 or 100000 <= a < 102000:
        return "경직/막기"
    return f"기타({a})"


def frames_observe(path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            if '"k":"w"' not in line and '"k": "w"' not in line:
                continue
            r = json.loads(line)
            if r.get("k") != "w":
                continue
            b = next((e for e in r.get("e", []) if e.get("npc") == TAURUS), None)
            if b is None:
                continue
            p = r["p"]
            yield (r["ms"] / 1000.0,
                   {"x": p["pos"][0], "y": p["pos"][1], "z": p["pos"][2], "anim": p.get("anim"), "hp": p.get("hp_raw")},
                   {"x": b["pos"][0], "y": b["pos"][1], "z": b["pos"][2], "hd": b.get("hd") or 0.0, "anim": b.get("anim"),
                    "hp": b.get("hp_raw")})


def frames_track(path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("type") != "snap":
                continue
            b = next((c for c in r.get("chars", []) if c.get("npc") == TAURUS), None)
            if b is None:
                continue
            p = r["player"]
            yield (r["rt"], {"x": p["x"], "y": p["y"], "z": p["z"], "anim": p.get("anim"), "hp": p.get("hp")},
                   {"x": b["x"], "y": b["y"], "z": b["z"], "hd": b.get("heading") or 0.0, "anim": b.get("anim"), "hp": b.get("hp")})


def instances(frames, src: str) -> list[dict]:
    out, cur, prev_hp, pending = [], None, None, []
    for t, me, boss in frames:
        a = boss["anim"] if boss["anim"] is not None else -1
        hp = me["hp"]
        drop = (prev_hp - hp) if (prev_hp is not None and hp is not None and hp < prev_hp) else 0
        prev_hp = hp
        if drop:
            target = cur or next((x for x in reversed(pending) if t - x["t_end"] <= HIT_AFTER_S), None)
            if target is not None:
                target["dmg"] += drop
        pending = [x for x in pending if t - x["t_end"] <= HIT_AFTER_S]
        if cur is not None and a != cur["anim"]:
            cur["t_end"] = t
            pending.append(cur)
            cur = None
        if cur is None and 3000 <= a < 3100:
            h = math.hypot(me["x"] - boss["x"], me["z"] - boss["z"])
            dy = me["y"] - boss["y"]
            if h <= NEAR_M and abs(dy) < 2.0 and (hp or 0) > 0:
                cur = {"src": src, "t": round(t, 2), "anim": a, "h": round(h, 2), "ang": round(ang_off(boss, me)),
                       "dy": round(dy, 1), "me": my_kind(me["anim"]), "dmg": 0, "t_end": t}
                out.append(cur)
        elif cur is not None:
            cur["h_min"] = round(min(cur.get("h_min", cur["h"]), math.hypot(me["x"] - boss["x"], me["z"] - boss["z"])), 2)
    return out


def events_attacks(path) -> list[dict]:
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if '"what": "attack"' not in line:
                continue
            e = json.loads(line)
            out.append({"src": Path(path).name, "t": e["t"], "anim": e["anim"], "h": e["h"], "ang": e["ang"], "dy": e.get("dy", 0.0),
                        "me": e.get("me", "?"), "dmg": e.get("dmg", 0), "h_min": e.get("h_min")})
    return out


def collect() -> list[dict]:
    rows = []
    for p in sorted(glob.glob(str(ROOT / "data" / "observe" / "*.jsonl"))):
        with open(p, encoding="utf-8") as f:
            if not any(str(TAURUS) in line for _, line in zip(range(200000), f)):
                continue
        rows += instances(frames_observe(p), "MoKa " + Path(p).stem)
    exact = set()
    for p in sorted(glob.glob(str(ROOT / "data" / "runs" / "*_taurus.jsonl"))):
        ev = events_attacks(p)
        if ev:
            rows += ev
            exact.add(Path(p).name[:15])
    seen = set()
    for d in ("runs", "samples"):
        for p in sorted(glob.glob(str(ROOT / "data" / d / "*_taurus*.track.jsonl"))):
            key = Path(p).name[:15]
            if key in seen or key in exact:
                continue
            seen.add(key)
            rows += instances(frames_track(p), "bot " + key)
    return rows


def table(rows) -> None:
    by = collections.defaultdict(list)
    for r in rows:
        by[r["anim"]].append(r)
    print(f"보스 공격 {len(rows)}번 (MoKa {sum(r['src'].startswith('MoKa') for r in rows)} · 봇 {sum(not r['src'].startswith('MoKa') for r in rows)})")
    print("애니  번  맞음  평균피해 | 거리×방향별 맞음/번 (앞 |각|<60 · 옆 60~120 · 뒤 >120)")
    for a in sorted(by):
        rs = by[a]
        hit = [r for r in rs if r["dmg"] > 0]
        cells = []
        for lo, hi in H_BINS:
            for name, alo, ahi in ANG_BINS:
                c = [r for r in rs if lo <= r["h"] < hi and alo <= abs(r["ang"]) < ahi]
                if c:
                    cells.append(f"{lo:.1f}-{hi:.1f}m {name} {sum(r['dmg'] > 0 for r in c)}/{len(c)}")
        avg = sum(r["dmg"] for r in hit) / len(hit) if hit else 0
        print(f"{a:5}  {len(rs):2}  {len(hit):2}   {avg:5.0f}   | " + " · ".join(cells))
    print("\n내 동작별 (공격 시작 순간): 맞음/번")
    mk = collections.defaultdict(list)
    for r in rows:
        mk[r["me"]].append(r)
    for k, rs in sorted(mk.items(), key=lambda x: -len(x[1])):
        print(f"  {k:12} {sum(r['dmg'] > 0 for r in rs)}/{len(rs)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    rows = collect()
    table(rows)
    if a.json:
        Path(a.json).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n→ {a.json} ({len(rows)}개)")


if __name__ == "__main__":
    main()
