"""Turn a human Asylum run (observe_record.py recording) into a step list the bot can follow — no game needed.

  python asylum_steps.py data/observe/20260928_221908.jsonl            → data/routes/asylum-fresh.json
  python asylum_steps.py <recording> --out other.json --until 327

A fresh character's first pass through the Northern Undead Asylum has one-time events (cell key, fleeing the demon, picking up
the class gear and equipping it from the menu, Oscar, the plunge onto the demon, the big door, the crow) — the ramp's "rest and
retry" doesn't apply, so the human run is the template. Steps, in order:

  walk      {"pts": [[x,y,z], …], "run"}          NavMesh walking between the other steps (points every ~2 m, on the mesh);
                                                 run = B held most of the way (fleeing the demon)
  press     {"pos", "n", "label"}                 A pressed n times standing here (door, pickup, bonfire, lever, talk)
  menu      {"pos", "keys": ["START", …]}          menu inputs (equipping the picked-up gear) — replayed as-is
  climb     {"from", "to"}                        off-mesh vertical move (ladder) — A at the bottom, then up
  fight     {"pos", "npc", "secs"}                an enemy fought here (its HP dropped) — the bot uses its own duel
  jump      {"from", "to"}                        position jump > 15 m without walking (crow / warp) — ends the recording's useful part

Labels are guesses from where they happen; MoKa checks them (ROADMAP 수용소). Raw values only, no game memory writes.
"""
from __future__ import annotations

import argparse
import bisect
import json
import math
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
MAP = "m18_01_00_00"
BTN = {0x1000: "A", 0x2000: "B", 0x4000: "X", 0x8000: "Y", 0x0010: "START", 0x0020: "BACK",
       0x0001: "UP", 0x0002: "DOWN", 0x0004: "LEFT", 0x0008: "RIGHT"}
STEP_M = 2.0             # walk point spacing
PRESS_JOIN_S = 1.5       # A presses closer than this (and < PRESS_JOIN_M apart) are one press step with n
PRESS_JOIN_M = 0.6
MENU_KEYS = {"START", "UP", "DOWN", "LEFT", "RIGHT"}
JUMP_M = 15.0
CLIMB_DY = 2.0           # off-mesh stretch that rises/falls this much = ladder (or a drop)

# 녹화 위치로 붙인 이름. 2026-09-28 Bandit Bot 녹화 기준 — 추정, [MoKa] 확인한 것만 (확인) 표시
LABELS = [
    ((-14.2, 184.9, -44.6), 2.5, "감방: 열쇠 줍기·문 열기"),
    ((-1.0, 189.6, 22.3), 1.5, "사다리 (감방 복도 → 뜰)"),
    ((3.3, 195.9, 8.2), 1.5, "첫 화톳불 (1812960) 불 붙이기"),
    ((3.0, 198.1, -3.4), 1.5, "큰 방 문 (데몬 처음 나옴 → 도망)"),
    ((32.7, 193.2, -26.0), 1.5, "도망친 방 화톳불 (1812961)"),
    ((37.2, 192.5, -12.0), 1.5, "시작 장비 줍기 1: 방패 + 메뉴 장착 (확인, 항상 같음)"),
    ((38.9, 195.4, 15.7), 1.5, "시작 장비 줍기 2: 배틀 액스 + 메뉴 장착 (확인, 항상 같음)"),
    ((-9.2, 205.0, 6.2), 1.5, "굴러오는 바위 — 떨어져 피함 (확인)"),
    ((-5.5, 201.6, 20.6), 1.5, "오스카 대화 (에스트·열쇠)"),
    ((-7.8, 208.4, -8.1), 1.5, "위층 문"),
    ((3.3, 210.1, -34.7), 1.5, "데몬 위 발판 (떨어지며 치기)"),
    ((2.3, 197.7, -18.9), 1.5, "데몬 처치 뒤 열쇠 줍기"),
    ((3.2, 198.1, -32.7), 1.5, "데몬 열쇠로 잠긴 문 열기 → 까마귀 쪽 (확인)"),
]


def label_at(pos) -> str:
    best = None
    for p, r, name in LABELS:
        d = math.dist(p, pos)
        if d <= r and (best is None or d < best[0]):
            best = (d, name)
    return best[1] if best else ""


def load(path: Path):
    ws, pads = [], []
    for ln in path.open(encoding="utf-8"):
        try:
            d = json.loads(ln)
        except ValueError:
            continue
        if d.get("k") == "w" and d.get("p"):
            ws.append(d)
        elif d.get("k") == "pad":
            pads.append(d)
    ws.sort(key=lambda d: d["ms"])
    pads.sort(key=lambda d: d["ms"])
    return ws, pads


def presses(pads) -> list[tuple[float, str]]:
    out, prev = [], 0
    for d in pads:
        new = d["btn"] & ~prev
        out += [(d["ms"], n) for m, n in BTN.items() if new & m]
        prev = d["btn"]
    return out


def build(ws, pads, on_mesh, until_s: float | None = None) -> list[dict]:
    if until_s is not None:
        ws = [d for d in ws if d["ms"] <= until_s * 1000]
        pads = [d for d in pads if d["ms"] <= until_s * 1000]
    wt = [d["ms"] for d in ws]
    pt = [d["ms"] for d in pads]

    def b_held(ms) -> bool:
        i = bisect.bisect_right(pt, ms) - 1
        return i >= 0 and bool(pads[i]["btn"] & 0x2000)

    def pos_at(ms):
        i = min(bisect.bisect_left(wt, ms), len(ws) - 1)
        return [round(v, 2) for v in ws[i]["p"]["pos"]]

    # events on the timeline: presses/menu (from the pad), jumps, fights (enemy HP drops)
    ev: list[tuple[float, dict]] = []
    menu: dict | None = None
    for ms, n in presses(pads):
        if n == "START" or (menu is not None and n in MENU_KEYS | {"A", "B"} and ms - menu["_t"] < 3000):
            if menu is None:
                menu = {"type": "menu", "pos": pos_at(ms), "keys": [], "_t": ms, "t": round(ms / 1000, 1)}
                ev.append((ms, menu))
            menu["keys"].append(n)
            menu["_t"] = ms
            continue
        menu = None
        if n != "A":
            continue
        p = pos_at(ms)
        last = ev[-1][1] if ev else None
        if last and last["type"] == "press" and ms - last["_t"] < PRESS_JOIN_S * 1000 and math.dist(last["pos"], p) < PRESS_JOIN_M:
            last["n"] += 1
            last["_t"] = ms
            continue
        ev.append((ms, {"type": "press", "pos": p, "n": 1, "_t": ms, "t": round(ms / 1000, 1)}))
    hp: dict = {}
    for d in ws:
        for e in d.get("e", []):
            if e.get("vt") != "enemy" or not e.get("npc"):
                continue
            k = e["id"]
            h0 = hp.get(k)
            if h0 is not None and e["hp_raw"] < h0:
                last = next((x for _, x in reversed(ev) if x["type"] == "fight" and x["_id"] == k), None)
                if last and d["ms"] - last["_t"] < 10000:
                    last["_t"] = d["ms"]
                    last["secs"] = round((d["ms"] - last["_t0"]) / 1000, 1)
                    last["killed"] = e["hp_raw"] <= 0
                else:
                    ev.append((d["ms"], {"type": "fight", "pos": pos_at(d["ms"]), "npc": e["npc"], "_id": k, "_t": d["ms"],
                                         "_t0": d["ms"], "secs": 0.0, "killed": e["hp_raw"] <= 0, "t": round(d["ms"] / 1000, 1)}))
            hp[k] = e["hp_raw"]
    for a, b in zip(ws, ws[1:]):
        if math.dist(a["p"]["pos"], b["p"]["pos"]) > JUMP_M:
            ev.append((b["ms"], {"type": "jump", "from": pos_at(a["ms"]), "to": pos_at(b["ms"]), "t": round(b["ms"] / 1000, 1)}))
            break
    ev.sort(key=lambda x: x[0])
    stop_ms = next((ms for ms, x in ev if x["type"] == "jump"), ws[-1]["ms"] + 1)

    # walk points between events; off-mesh stretches that rise/fall become climbs
    steps: list[dict] = []
    cur: list = []
    run = [0, 0]                                           # samples with B held / all, for the current walk
    off: list = []
    ei = 0

    def flush():
        nonlocal cur, run
        if cur:
            steps.append({"type": "walk", "pts": cur, "run": run[0] > run[1] / 2})
        cur, run = [], [0, 0]
    for d in ws:
        if d["ms"] >= stop_ms:
            break
        while ei < len(ev) and ev[ei][0] <= d["ms"]:
            flush()
            steps.append(ev[ei][1])
            ei += 1
        p = [round(v, 2) for v in d["p"]["pos"]]
        if not on_mesh(*p):
            off.append(p)
            continue
        if off:
            if abs(off[-1][1] - off[0][1]) >= CLIMB_DY:
                flush()
                steps.append({"type": "climb", "from": off[0], "to": off[-1], "t": round(d["ms"] / 1000, 1)})
            off = []
        run[0] += b_held(d["ms"])
        run[1] += 1
        if not cur or math.dist(cur[-1], p) >= STEP_M:
            cur.append(p)
    flush()
    steps += [x for ms, x in ev[ei:] if ms >= stop_ms][:1]
    for s in steps:
        for k in [k for k in s if k.startswith("_")]:
            del s[k]
        if s["type"] in ("press", "menu", "climb", "fight"):
            s["label"] = label_at(s.get("pos") or s.get("from"))
    return steps


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("recording")
    ap.add_argument("--out", default=str(ROOT / "data" / "routes" / "asylum-fresh.json"))
    ap.add_argument("--until", type=float, default=None, help="seconds — ignore the recording after this")
    a = ap.parse_args()
    import navmesh
    nm = navmesh.Navmesh(MAP)
    ws, pads = load(Path(a.recording))
    steps = build(ws, pads, nm.on_mesh, a.until)
    out = {"name": "asylum-fresh", "map": MAP, "source": Path(a.recording).name,
           "note": "asylum_steps.py — 사람 첫 통과 녹화에서 뽑음. label 은 추정 ([MoKa] 확인 전)", "steps": steps}
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    kinds: dict = {}
    for s in steps:
        kinds[s["type"]] = kinds.get(s["type"], 0) + 1
    print(f"{a.out}: {len(steps)} steps {kinds}")
    for s in steps:
        if s["type"] == "walk":
            print(f"  {'run ' if s['run'] else 'walk'}   {len(s['pts'])} pts  {s['pts'][0]} → {s['pts'][-1]}")
        elif s["type"] == "press":
            print(f"  press  {s['t']:6.1f}s ×{s['n']:<2} {s['pos']}  {s['label']}")
        elif s["type"] == "menu":
            print(f"  menu   {s['t']:6.1f}s {' '.join(s['keys'])}  {s['label']}")
        elif s["type"] == "climb":
            print(f"  climb  {s['t']:6.1f}s {s['from']} → {s['to']}  {s['label']}")
        elif s["type"] == "fight":
            print(f"  fight  {s['t']:6.1f}s npc {s['npc']} {s['secs']} s {'killed' if s['killed'] else ''}  {s['label']}")
        else:
            print(f"  {s['type']:6s} {s.get('t')}s {s.get('from')} → {s.get('to')}")


if __name__ == "__main__":
    main()
