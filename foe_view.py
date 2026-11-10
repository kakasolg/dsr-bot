"""The ramp fight from the six foes' side (MoKa M1109-62: "몹들이 봇을 어떻게 막는지").

  python foe_view.py [<run>]          (newest clear-ramp run by default)
  python foe_view.py --radar data/radar/<session>.jsonl <wall t from> [<wall t to>]     a person's play (MoKa)
  python foe_view.py --room data/runs/<time>_room.jsonl       a bot run in the Godot ramp room (sim/godot ramp.tscn)

Reads the replay file (sim/replay_extract.py: radar recording + run events, ~9 snapshots/s) and, for each of the six
ramp foes (matched to data/enemy-map.json spawns, the Firelink MSB placements c2540_0003 … c2540_0007), tells:
  woke      first time it moved off its spawn (> MOVE_M) and the bot's distance then — the game files give each one a
            battle start distance (#1 #2 #6 "専守" 9 m, #3 #4 #5 20 m); the radar can't see the AI's own decision,
            so "moved" stands in for "noticed" [guess]
  reached   first time within NEAR_M of the bot
  attacks   attack animations (3000–3999) it started, with the bot's distance at the start
  hits      big hits on the bot blamed on it (the run's hit log — the blame is the logger's guess)
and for the group: how many were within NEAR_M of the bot at once (longest stretch, worst count), whether the bot ever
stood in region 1022710 ("敵が行けない場所", both readings of its 58° turn), and attacks that began while the bot was
busy (healing, rolling, getting up — the bot's own animation ids, ranges below are [guess]).

Recorded only — nothing here says why a foe did what it did; the AI's state is not read.
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SPAWNS = json.loads((ROOT / "data" / "enemy-map.json").read_text(encoding="utf-8"))["enemies"]
# game files (m10_02 MSB · NpcThinkParam names) — see docs/moka_ledger.jsonl M1109-60
ROLE = ["검·지키기 9 m", "롱소드 중전사·지키기 9 m", "검 20 m", "도끼 20 m", "검·화염병 20 m (시야 40)", "검·지키기 9 m"]
REGION = ((-27.1, -50.5, 6.14), 6.5, 33.0, 9.0, 58.0)       # 1022710 centre, width, depth, height, turn (deg)
FIREBOMB_POINT = (-23.36, -50.05, 15.76)                     # 1022711
MOVE_M, NEAR_M, SPAWN_MATCH_M = 1.0, 4.0, 3.0
BIG_HIT = 40            # HP drop counted as a hit in a person's play (no hit log there) [guess]
BUSY = {"회복": range(7580, 7600), "구르기·백스텝": range(700, 800), "피격·일어나기": range(2000, 2300)}   # [guess] bot anim ids (anim % 10000)


def _in_region(p, sign) -> bool:
    (cx, cy, cz), w, d, h, rot = REGION
    a = math.radians(rot) * sign
    dx, dz = p[0] - cx, p[2] - cz
    lx = dx * math.cos(a) - dz * math.sin(a)
    lz = dx * math.sin(a) + dz * math.cos(a)
    return abs(lx) <= w / 2 and abs(lz) <= d / 2 and cy - 0.5 <= p[1] <= cy + h


def _busy(anim: int):
    a = anim % 10000 if anim and anim > 0 else -1
    return next((k for k, r in BUSY.items() if a in r), None)


def load(run: str) -> dict:
    f = ROOT / "data" / "replays" / f"{run}.json"
    if not f.exists():
        subprocess.run([sys.executable, str(ROOT / "sim" / "replay_extract.py"), run], check=True)
    return json.loads(f.read_text(encoding="utf-8"))


def load_radar(path: Path, t_from: float, t_to: float = 1e12) -> dict:
    """A person's play (no run files): radar_server snapshots between two wall times → the replay shape view() reads
    (frames t / p / c, chars by pointer, hits = player HP drops ≥ BIG_HIT with the nearest live foe as [guess] blame)."""
    import os
    frames, chars, hits = [], {}, []
    size = os.path.getsize(path)
    with open(path, "rb") as h:
        lo, hi = 0, size                       # binary search the byte offset of t_from (the file is in time order)
        while hi - lo > 1 << 20:
            mid = (lo + hi) // 2
            h.seek(mid)
            h.readline()
            t = json.loads(h.readline() or b"{}").get("t", 1e18)
            lo, hi = (mid, hi) if t < t_from else (lo, mid)
        h.seek(lo)
        h.readline()
        for line in h:
            d = json.loads(line)
            if d.get("type") != "snap" or d["t"] < t_from:
                continue
            if d["t"] > t_to:
                break
            pl = d["player"]
            c = {}
            for x in d["chars"]:
                k = str(x["ptr"])
                chars.setdefault(k, {"npc": x["npc"], "team": x["team"], "max_hp": x["max_hp"]})
                c[k] = [x["x"], x["y"], x["z"], x["heading"], x["anim"], x["hp"]]
            frames.append({"t": d["t"] - t_from, "p": [pl["x"], pl["y"], pl["z"], pl["heading"], pl["anim"], pl["hp"]],
                           "c": c})
    for a, b in zip(frames, frames[1:]):
        if a["p"][5] - b["p"][5] >= BIG_HIT:
            near = min(((math.dist(v[:3], b["p"][:3]), k, v[4]) for k, v in b["c"].items() if v[5] > 0), default=None)
            hits.append({"t": b["t"], "hp0": a["p"][5], "lo": b["p"][5], "id": near[1] if near else None,
                         "anim": near[2] if near else None, "d": round(near[0], 2) if near else None})
    return {"frames": frames, "chars": chars, "hits": hits}


def load_room(path: Path) -> dict:
    """The Godot ramp room's own record (sim/godot_link.RoomTelemetry, 10 per s) → the replay shape view() reads.
    Hits = player HP drops ≥ BIG_HIT, blamed on the nearest live foe [guess], as for a person's play."""
    frames, chars, hits = [], {}, []
    t0 = None
    for line in open(path, encoding="utf-8"):
        d = json.loads(line)
        if "foes" not in d:
            continue
        t0 = d["t"] if t0 is None else t0
        c = {}
        for f in d["foes"]:
            k = str(f["ptr"])
            chars.setdefault(k, {"npc": f["npc"], "team": 6, "max_hp": f["max_hp"]})
            c[k] = [f["x"], f["y"], f["z"], f["heading"], f["anim"], f["hp"]]
        frames.append({"t": d["t"] - t0, "p": [d["x"], d["y"], d["z"], d["heading"], d["anim"], d["hp"]], "c": c})
    for a, b in zip(frames, frames[1:]):
        if a["p"][5] - b["p"][5] >= BIG_HIT:
            near = min(((math.dist(v[:3], b["p"][:3]), k, v[4]) for k, v in b["c"].items() if v[5] > 0), default=None)
            hits.append({"t": b["t"], "hp0": a["p"][5], "lo": b["p"][5], "id": near[1] if near else None,
                         "anim": near[2] if near else None, "d": round(near[0], 2) if near else None})
    return {"frames": frames, "chars": chars, "hits": hits}


def view(rp: dict) -> dict:
    frames = rp["frames"]
    # which recorded character is which ramp foe: the first snapshot it appears in, nearest spawn of the same npc
    first, alive_first = {}, {}           # first snapshot; first snapshot alive (a rest revives the dead at their spawn)
    for f in frames:
        for k, c in f["c"].items():
            first.setdefault(k, c)
            if c[5] > 0:
                alive_first.setdefault(k, (f["t"], c))
    who = {}
    for i, s in enumerate(SPAWNS):
        best = min(((math.dist(c[:3], s["pos"]), k) for k, (_, c) in alive_first.items()
                    if rp["chars"][k]["npc"] == s["npc"] and k not in who.values()), default=None)
        if best and best[0] < SPAWN_MATCH_M:
            who[i] = best[1]
    out = {"foes": [], "matched": len(who)}
    hits = rp.get("hits", [])
    for i, s in enumerate(SPAWNS):
        k = who.get(i)
        row = {"n": i + 1, "role": ROLE[i], "npc": s["npc"], "id": k}
        if k is not None and k not in alive_first:
            row["already_dead"] = True
        if k is None or row.get("already_dead"):
            out["foes"].append(row)
            continue
        woke = reached = None
        attacks, last_anim = [], None
        to_point = None
        t_alive = alive_first[k][0]
        for f in frames:
            c = f["c"].get(k)
            if c is None or f["t"] < t_alive:
                continue
            d = math.dist(c[:3], f["p"][:3])
            if woke is None and math.dist(c[:3], s["pos"]) > MOVE_M:
                woke = (f["t"], d)
            if reached is None and d < NEAR_M and c[5] > 0:
                reached = (f["t"], d)
            if 3000 <= c[4] < 4000 and c[4] != last_anim:
                attacks.append({"t": f["t"], "anim": c[4], "d": round(d, 2), "bot_busy": _busy(int(f["p"][4]))})
            if i == 4 and to_point is None and math.dist(c[:3], FIREBOMB_POINT) < 1.5:
                to_point = f["t"]
            last_anim = c[4]
        dead = next((f["t"] for f in frames if f["t"] > t_alive and k in f["c"] and f["c"][k][5] <= 0), None)
        row.update({"woke": woke, "reached": reached, "attacks": attacks, "dead": dead,
                    "hits": [(h["t"], h["hp0"] - h["lo"]) for h in hits if str(h.get("id")) == k]})
        if i == 4:
            row["firebomb_point"] = to_point
        out["foes"].append(row)
    # crowding: foes of the six within NEAR_M of the bot
    worst, run_start, longest = 0, None, (0.0, None, 0)
    for f in frames:
        n = sum(1 for k in who.values() if k in f["c"] and f["c"][k][5] > 0
                and math.dist(f["c"][k][:3], f["p"][:3]) < NEAR_M)
        worst = max(worst, n)
        if n >= 2 and run_start is None:
            run_start, peak = f["t"], n
        elif n >= 2:
            peak = max(peak, n)
        elif run_start is not None:
            if f["t"] - run_start > longest[0]:
                longest = (f["t"] - run_start, run_start, peak)
            run_start = None
    out["crowd"] = {"most_at_once": worst, "longest_2plus_s": round(longest[0], 1), "from": longest[1], "peak": longest[2]}
    out["bot_in_region"] = {s: [f["t"] for f in frames if _in_region(f["p"][:3], s)][:1] for s in (1, -1)}
    return out


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = sys.argv[1:]
    if args and args[0] == "--room":
        run = Path(args[1]).stem
        v = view(load_room(Path(args[1])))
    elif args and args[0] == "--radar":                  # --radar <file> <wall t from> [<wall t to>]: a person's play
        run = f"{Path(args[1]).stem}_{int(float(args[2]))}"
        v = view(load_radar(Path(args[1]), float(args[2]), float(args[3]) if len(args) > 3 else 1e12))
    else:
        run = args[0] if args else sorted(p.stem for p in (ROOT / "data" / "runs").glob("*_clear-ramp.log"))[-1]
        v = view(load(run))
    print(f"{run}: 경사로 6명 중 {v['matched']}명 녹화에서 찾음 (스폰 {SPAWN_MATCH_M} m 안)")
    for r in v["foes"]:
        if r["id"] is None or r.get("already_dead"):
            print(f"  #{r['n']} {r['role']}: " + ("녹화 시작부터 죽어 있음" if r.get("already_dead") else "녹화에 없음"))
            continue
        w = f"{r['woke'][0]:.1f} s (봇 {r['woke'][1]:.1f} m)" if r["woke"] else "안 움직임"
        re_ = f"{r['reached'][0]:.1f} s" if r["reached"] else "—"
        print(f"  #{r['n']} {r['role']} [id {r['id']}]: 움직임 {w} · {NEAR_M:.0f} m 안 도착 {re_} · "
              f"공격 {len(r['attacks'])}번 · 큰 피격 {len(r['hits'])}번 (−{sum(x[1] for x in r['hits'])}) · "
              f"죽음 {('%.1f s' % r['dead']) if r['dead'] else '—'}"
              + (f" · 화염병 지점 도착 {r['firebomb_point']:.1f} s" if r.get('firebomb_point') else ""))
        for a in r["attacks"]:
            print(f"      {a['t']:7.1f} s  anim {a['anim']}  거리 {a['d']:.2f} m" + (f"  봇 {a['bot_busy']} 중" if a["bot_busy"] else ""))
    c = v["crowd"]
    print(f"  겹침: 최대 {c['most_at_once']}명 동시 {NEAR_M:.0f} m 안 · 2명 이상 가장 긴 구간 {c['longest_2plus_s']} s"
          + (f" ({c['from']:.1f} s부터, 최대 {c['peak']}명)" if c["from"] else ""))
    print(f"  봇이 영역 1022710 안: +58° 해석 {v['bot_in_region'][1] or '없음'} · −58° 해석 {v['bot_in_region'][-1] or '없음'}")
    out = ROOT / "data" / "replays" / f"{run}.foe_view.json"
    out.write_text(json.dumps(v, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
