"""Stage report — for each zone of an area: the terrain, the foes and what happened in our runs (offline, read-only).

[MoKa] 2026-10-12: analyse each stage — how it plays against the player, its terrain, how the foes are placed — and build
data on how to answer it. This is the automatic half: everything that can be measured. The other half (what the stage tests,
what to do — a hypothesis until runs confirm it) is written by hand in docs/stages/<area>.md, above the block this fills.

  python stage_report.py                    burg-upper → data/stages/burg-upper.json + the auto block of docs/stages/burg-upper.md
  python stage_report.py --print            also print the per-zone summary

Per zone:
  terrain   safe spot: nearest drop edge / wall (NavMesh edge_kinds), drop edges within DROP_NEAR_R; per foe: path length from
            the safe spot, how many metres of that path run within EDGE_EXPOSED_M of a drop edge, the height difference
  foes      who (souls/foes.py), sight / hearing / help group / patrol (game files' ThinkParam), how close it notices us
            (data/notice.json, measured), which foes sit close enough to wake together; foes near the safe spot we don't kill
  runs      data/samples logs: runs that reached the zone, cleared / died, death causes (black box: hit by whom, or a fall),
            falls, big hits by attacker, time in the zone; problems (docs/roadmap/problems.md headings naming the zone)
"""
from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
SAMPLES = ROOT / "data" / "samples"
AREAS = {
    "burg-upper": {"zones": ROOT / "data" / "burg-upper-map.json", "map": "m10_01_00_00", "runs": "*burg-upper*.txt",
                   "title": "성벽 마을 위쪽 — 화톳불 → 타우로스 (구역 1–8)"},
}
DROP_NEAR_R = 6.0       # drop edges this close to the safe spot are counted
EDGE_EXPOSED_M = 1.5    # a path point this close to a drop edge counts as "along an edge"
OTHERS_R = 20.0         # foes near the safe spot that we don't kill (left alone / ignored)
SPAWN_MATCH_R = 3.0     # a kill's spawn ↔ the game file's enemy
TOGETHER_PAD = 1.0      # two foes "wake together" when closer than the larger notice distance + this
BEGIN, END = "<!-- stage_report:begin -->", "<!-- stage_report:end -->"
T = re.compile(r"^\[\s*([\d.]+)\]")


# ── terrain ──────────────────────────────────────────────────────
def _drops_near(nm, p, r: float, dy: float = 2.5) -> list[float]:
    p0, p1, _ = nm.edge_kinds()["drop"]
    out = []
    for a, b in zip(p0, p1):
        m = (a + b) / 2.0
        if abs(m[1] - p[1]) <= dy:
            d = math.hypot(m[0] - p[0], m[2] - p[2])
            if d <= r:
                out.append(round(d, 1))
    return sorted(out)


def _path_info(nm, a, b) -> dict:
    path = nm.find_path(tuple(a), tuple(b))
    if not path:
        return {"path_m": None, "edge_m": None}
    L = sum(math.dist(path[i - 1], path[i]) for i in range(1, len(path)))
    pts = []                                               # every ~0.5 m along the path
    for i in range(1, len(path)):
        n = max(1, int(math.dist(path[i - 1], path[i]) / 0.5))
        pts += [tuple(path[i - 1][k] + (path[i][k] - path[i - 1][k]) * j / n for k in range(3)) for j in range(n)]
    pts.append(tuple(path[-1]))
    dd = [nm.drop_dist(*q) for q in pts]
    near = sum(1 for d in dd if d < EDGE_EXPOSED_M) * L / max(1, len(pts))
    return {"path_m": round(L, 1), "edge_m": round(near, 1)}     # how much of the walk runs within EDGE_EXPOSED_M of a drop


def terrain(nm, z: dict) -> dict:
    s = z["safe"]
    out = {"safe": s, "safe_drop_m": _r(nm.drop_dist(*s)), "safe_wall_m": _r(nm.wall_dist(*s)),
           "drops_near_safe": len(_drops_near(nm, s, DROP_NEAR_R)), "to_foes": []}
    for k in z["kills"]:
        info = _path_info(nm, s, k[1])
        out["to_foes"].append({"npc": k[0], "dist_m": round(math.dist(s, k[1]), 1), "dy_m": round(k[1][1] - s[1], 1), **info})
    return out


def _r(v):
    return None if v is None or math.isinf(v) else round(v, 1)


# ── foes ─────────────────────────────────────────────────────────
def _game_enemy(enemies: list, npc: int, pos) -> dict | None:
    c = [e for e in enemies if e.get("npc_param_id") == npc and math.dist(e["pos"], pos) <= SPAWN_MATCH_R]
    return min(c, key=lambda e: math.dist(e["pos"], pos)) if c else None


def foes(z: dict, enemies: list, notice: dict, ignored: list, all_kills: dict | None = None) -> dict:
    from souls import foes as foes_
    rows = []
    for k in z["kills"]:
        npc, pos = k[0], k[1]
        f = foes_.of(npc)
        g = _game_enemy(enemies, npc, pos)
        th = (g or {}).get("think") or {}
        nt = ((notice.get(str(npc)) or {}).get("all") or {}).get("d")
        rows.append({"npc": npc, "name": f.name, "kind": f.kind, "ranged": bool(f.thrower), "shield": bool(f.kick_when_idle),
                     "pos": pos, "how": (k[2] if len(k) > 2 else None), "notice_m": nt,
                     "sight_m": th.get("SightDistance"), "hearing_m": th.get("HearingDistance"),
                     "help_group": th.get("HelpGroupID") or None, "patrol": bool((g or {}).get("patrol"))})
    together = []
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            a, b = rows[i], rows[j]
            d = math.dist(a["pos"], b["pos"])
            lim = max(a["notice_m"] or 0, b["notice_m"] or 0) + TOGETHER_PAD
            same_group = a["help_group"] and a["help_group"] == b["help_group"]
            if d <= lim or same_group:
                together.append({"a": i + 1, "b": j + 1, "d_m": round(d, 1), "help_group": bool(same_group)})
    kill_pos = [k[1] for k in z["kills"]]
    others = []
    for e in enemies:
        npc = e.get("npc_param_id") or 0
        if e.get("kind") == "human" or not 250000 <= npc < 260000:   # Undead Burg foes are 25xxxx; others are NPCs / props
            continue
        d = math.dist(e["pos"], z["safe"])
        if d <= OTHERS_R and not any(math.dist(e["pos"], p) <= SPAWN_MATCH_R for p in kill_pos):
            zone = next((n for n, ks in (all_kills or {}).items() for k in ks if k[0] == npc and math.dist(e["pos"], k[1]) <= SPAWN_MATCH_R), None)
            others.append({"npc": npc, "d_m": round(d, 1), "dy_m": round(e["pos"][1] - z["safe"][1], 1),
                           "ignored": any(math.dist(e["pos"], ig[1]) <= SPAWN_MATCH_R for ig in ignored), "killed_in": zone})
    return {"kills": rows, "together": together, "others": sorted(others, key=lambda o: o["d_m"])}


# ── runs ─────────────────────────────────────────────────────────
ZONE_END = re.compile(r"══ 구역 (\d+) \([^)]*\) 끝: (.*)$")
ZONE_HINT = re.compile(r"구역(\d+)-\d")
BB = re.compile(r"▣ 블랙박스 #\d+: [\d.]+ s 동안 -(\d+) → HP (\d+)/\d+, (.*)$")
BLAME = re.compile(r"추정 (\d+) 애니")


def _zone_of_runs(lines: list[str]) -> list[tuple[float | None, int | None, str]]:
    """(t, zone, line) — the zone a line belongs to: the one whose end line comes next, else a 구역n- hint, else the last end + 1."""
    ends = [(i, int(m.group(1))) for i, l in enumerate(lines) for m in [ZONE_END.search(l)] if m]
    first = next((int(m.group(1)) for l in lines for m in [ZONE_HINT.search(l) or ZONE_END.search(l)] if m), None)
    out, k = [], 0
    for i, l in enumerate(lines):
        while k < len(ends) and ends[k][0] < i:
            k += 1
        z = ends[k][1] if k < len(ends) else ((ends[-1][1] + 1) if ends else first)
        m = T.match(l)
        out.append((float(m.group(1)) if m else None, z, l))
    return out


FALL_M = 3.0            # a death whose last FALL_LOOK s dropped this much before HP hit 0 = a fall (docs/analysis-death-2026-10-12.md)
FALL_LOOK = 3.0


def _track_for(f: Path) -> Path | None:
    for stem in (f.stem, f.stem.replace("-radar-", "-")):
        p = f.with_name(stem + ".track.jsonl")
        if p.exists():
            return p
    return None


def _fall_death(track: Path | None, t_end: float | None) -> bool | None:
    """From the run's own track: did my height drop ≥ FALL_M in the FALL_LOOK s before HP first hit 0 (near t_end)? None = no track."""
    if track is None or t_end is None:
        return None
    snaps = []
    for line in track.open(encoding="utf-8"):
        d = json.loads(line)
        if d.get("type") == "snap" and d.get("player") and t_end - 30 <= d["rt"] <= t_end + 10:
            snaps.append((d["rt"], d["player"].get("hp"), d["player"].get("y")))
    for i in range(1, len(snaps)):
        t, hp, y = snaps[i]
        if hp == 0 and (snaps[i - 1][1] or 0) > 0:
            top = max(q[2] for q in snaps[:i] if t - FALL_LOOK <= q[0])
            return top - y >= FALL_M
    return None


def runs(pattern: str, zones: list[int]) -> dict:
    per = {n: {"runs": 0, "tries": 0, "cleared": 0, "results": Counter(), "deaths": [], "falls": 0, "hits": 0, "hit_lost": 0,
               "blamed": Counter(), "secs": [], "files": []} for n in zones}
    files = sorted(SAMPLES.glob(pattern))
    for f in files:
        lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        rows = _zone_of_runs(lines)
        track = _track_for(f)
        seen, t_prev, last_bb = set(), 0.0, {}
        for t, z, l in rows:
            if z not in per:
                continue
            P = per[z]
            m = ZONE_END.search(l)
            h = ZONE_HINT.search(l)
            if z not in seen and (m or (h and int(h.group(1)) == z)):  # only a zone the run really played (not 'after the last end')
                seen.add(z)
                P["runs"] += 1
                P["files"].append(f.stem)
            if m:
                res = m.group(2).strip()
                P["tries"] += 1
                P["results"][res.split(" ")[0]] += 1
                if res.startswith("cleared"):
                    P["cleared"] += 1
                if t is not None:
                    P["secs"].append(round(t - t_prev, 1))
                    t_prev = t
            if ("⚠ 낙하:" in l or "⚠ 퀵 종료: 낙사" in l or "(퀵 종료 꺼짐) 낙사" in l) and "계획된" not in l:
                P["falls"] += 1
            b = BB.search(l)
            if b:
                lost, hp, rest = int(b.group(1)), int(b.group(2)), b.group(3)
                P["hits"] += 1
                P["hit_lost"] += lost
                w = BLAME.search(rest)
                if w and "낙하 -" not in rest.split("(추정")[0]:
                    P["blamed"][int(w.group(1))] += 1
                last_bb[z] = (lost, hp, rest)
            if "✝ 죽음" in l or ("끝: died" in l and m):
                if "✝ 죽음" in l:
                    continue                               # the zone-end 'died' line counts it once
                lost, hp, rest = last_bb.get(z, (None, None, ""))
                tf = _fall_death(track, t)
                fall = tf if tf is not None else ("낙하 -" in rest or "공격 애니 중인 적 없음" in rest)
                w = BLAME.search(rest)
                P["deaths"].append({"run": f.stem, "cause": "fall" if fall else "hit",
                                    "by": None if fall or not w else int(w.group(1))})
    out = {}
    for n, P in per.items():
        out[n] = {"runs": P["runs"], "tries": P["tries"], "cleared": P["cleared"], "results": dict(P["results"]), "deaths": P["deaths"],
                  "falls": P["falls"], "big_hits": P["hits"], "big_hit_lost": P["hit_lost"],
                  "blamed": dict(P["blamed"].most_common(4)),
                  "secs_median": round(statistics.median(P["secs"])) if P["secs"] else None, "files": P["files"]}
    return {"files": len(files), "zones": out}


def problems(zones: list[int]) -> dict:
    text = (ROOT / "docs" / "roadmap" / "problems.md").read_text(encoding="utf-8")
    heads = re.findall(r"^### (P-\d+) (.*)$", text, re.M)
    return {n: [p for p, h in heads if re.search(rf"(구역 ?{n}|zone ?{n})(?![0-9~–\-])", h)] for n in zones}


# ── build ────────────────────────────────────────────────────────
def build(area: str = "burg-upper") -> dict:
    import motion
    A = AREAS[area]
    zmap = json.loads(A["zones"].read_text(encoding="utf-8"))
    game = json.loads((ROOT / "data" / "gamefiles" / f"{A['map']}.json").read_text(encoding="utf-8"))
    notice = json.loads((ROOT / "data" / "notice.json").read_text(encoding="utf-8"))["table"]
    nm = motion.load_navmeshes()[A["map"]]
    zones = [z["n"] for z in zmap["zones"]]
    ev, pr = runs(A["runs"], zones), problems(zones)
    out = {"area": area, "title": A["title"], "map": A["map"], "made_by": "stage_report.py", "runs_read": ev["files"], "zones": []}
    for z in zmap["zones"]:
        n = z["n"]
        out["zones"].append({"n": n, "notes": {k: z[k] for k in ("note", "no_safe", "before") if k in z},
                             "terrain": terrain(nm, z),
                             "foes": foes(z, game["enemies"], notice, zmap.get("ignore", []), {q["n"]: q["kills"] for q in zmap["zones"]}),
                             "runs": ev["zones"][n], "problems": pr[n]})
    return out


def markdown(rep: dict) -> str:
    L = [BEGIN, "", f"_자동 생성: `python stage_report.py` — 실행 기록 {rep['runs_read']}개 (data/samples), NavMesh {rep['map']}, "
         "게임 파일 ThinkParam, data/notice.json. 손으로 고치지 말 것 — 다시 만들면 덮어씀._", "",
         "| 구역 | 판 | 시도 | 통과 | 사망 (낙하) | 낙하 감지 | 큰 피격 / −HP | 많이 때린 적 | 중앙 시간 | 안전 자리 낙차 | 문제 |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for z in rep["zones"]:
        r, t = z["runs"], z["terrain"]
        nd = len(r["deaths"])
        nf = sum(1 for d in r["deaths"] if d["cause"] == "fall")
        who = ", ".join(f"{k}×{v}" for k, v in r["blamed"].items()) or "-"
        L.append(f"| {z['n']} | {r['runs']} | {r['tries']} | {r['cleared']} | {nd} ({nf}) | {r['falls']} | {r['big_hits']} / {r['big_hit_lost']} | {who} | "
                 f"{r['secs_median'] if r['secs_median'] is not None else '-'} s | {t['safe_drop_m'] if t['safe_drop_m'] is not None else '-'} m | "
                 f"{', '.join(z['problems']) or '-'} |")
    for z in rep["zones"]:
        t, F = z["terrain"], z["foes"]
        L += ["", f"### 구역 {z['n']} — 자동", "",
              f"- 안전 자리 {t['safe']}: 낙차 가장자리 {t['safe_drop_m']} m, 벽 {t['safe_wall_m']} m, {DROP_NEAR_R:.0f} m 안 낙차 가장자리 {t['drops_near_safe']}개"]
        if F["kills"]:
            L += ["", "| # | 적 | 종류 | 방패 / 원거리 | 알아챔 m | 시야 / 청각 m | 순찰 | 안전 자리에서 m (높이) | 길 m | 그중 낙차 1.5 m 안 | 방법 |",
                  "|---|---|---|---|---|---|---|---|---|---|---|"]
            for i, (k, p) in enumerate(zip(F["kills"], t["to_foes"]), 1):
                how = json.dumps(k["how"], ensure_ascii=False) if k["how"] else "-"
                L.append(f"| {i} | {k['npc']} {k['name']} | {k['kind']} | {'방패' if k['shield'] else '-'} / {'원거리' if k['ranged'] else '-'} | "
                         f"{k['notice_m'] if k['notice_m'] is not None else '-'} | {k['sight_m']} / {k['hearing_m']} | {'예' if k['patrol'] else '-'} | "
                         f"{p['dist_m']} ({p['dy_m']:+}) | {p['path_m'] if p['path_m'] is not None else '길 없음'} | "
                         f"{p['edge_m'] if p['edge_m'] is not None else '-'} m | {how} |")
        if F["together"]:
            L.append("- 같이 깰 수 있는 짝: " + ", ".join(f"#{g['a']}–#{g['b']} {g['d_m']} m" + (" (도움 그룹)" if g["help_group"] else "")
                                                     for g in F["together"]))
        if F["others"]:
            L.append(f"- 안전 자리 {OTHERS_R:.0f} m 안의 다른 적 (이 구역에서 안 잡음): " + ", ".join(
                f"{o['npc']} {o['d_m']} m ({o['dy_m']:+})" + (" 무시" if o["ignored"] else f" 구역 {o['killed_in']}에서 잡음" if o["killed_in"] else "")
                for o in F["others"][:6]))
        d = z["runs"]["deaths"]
        if d:
            L.append("- 사망: " + ", ".join(f"{x['run'][:15]} {('낙하' if x['cause'] == 'fall' else str(x['by']))}" for x in d))
    L += ["", END]
    return "\n".join(L)


def write(rep: dict) -> tuple[Path, Path]:
    out = ROOT / "data" / "stages" / f"{rep['area']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    doc = ROOT / "docs" / "stages" / f"{rep['area']}.md"
    doc.parent.mkdir(parents=True, exist_ok=True)
    block = markdown(rep)
    if doc.exists():
        text = doc.read_text(encoding="utf-8")
        if BEGIN in text and END in text:
            text = text[:text.index(BEGIN)] + block + text[text.index(END) + len(END):]
        else:
            text = text.rstrip("\n") + "\n\n" + block + "\n"
    else:
        text = f"# {rep['title']}\n\n{block}\n"
    doc.write_text(text, encoding="utf-8")
    return out, doc


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("area", nargs="?", default="burg-upper", choices=sorted(AREAS))
    ap.add_argument("--print", action="store_true")
    a = ap.parse_args()
    rep = build(a.area)
    out, doc = write(rep)
    print(f"{out.relative_to(ROOT)} · {doc.relative_to(ROOT)} — {len(rep['zones'])} zones, {rep['runs_read']} runs read")
    if a.print:
        for z in rep["zones"]:
            r = z["runs"]
            print(f"zone {z['n']}: runs {r['runs']} tries {r['tries']} cleared {r['cleared']} deaths {len(r['deaths'])} falls {r['falls']} "
                  f"big hits {r['big_hits']} (−{r['big_hit_lost']}) by {r['blamed']} · safe drop {z['terrain']['safe_drop_m']} m · {z['problems']}")


if __name__ == "__main__":
    main()
