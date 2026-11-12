"""Exploration walk between two spots, character invincible and unseen (MoKa M1111-14: "캐릭터를 무적으로 하고 안드레아가 있는
화톳불까지 진행해봐. 다른 몹한테도 보이지 않게").

  python explore_walk.py [--from altar-bonfire] [--to andre-bonfire] [--map m10_01_00_00]

OFFLINE ONLY — writes game memory: ChrDbg PLAYER_NO_DEAD, PLAYER_HIDE, PLAYER_SILENCE on for the walk, and the player's HP back
to max whenever it dropped (NO_DEAD alone still takes damage). NO_DEAD does not stop
a fall death (P-152). Path = NavMesh find_path from where the character stands to the target spot's stand; it walks it with
Moves.walk_path (nav.follow) and stops at the first failure — it does not improvise a way round (doors, gates, lifts).
Every 0.25 s position → data/runs/<time>_explore.jsonl, so a walk that arrived can become a route recording.
Flags: off again when it arrived within ARRIVE_M of the target; left ON when it stopped elsewhere (the character stands among
foes — turning them off there gets it killed, memory never-hard-stop-mid-zone), and the end line says so.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import threading
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
FLAGS = ("DBG_PLAYER_NO_DEAD", "DBG_PLAYER_HIDE", "DBG_PLAYER_SILENCE")
ARRIVE_M = 3.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="src", default="altar-bonfire", help="only for the log — the walk starts where the character is")
    ap.add_argument("--to", default="andre-bonfire")
    ap.add_argument("--map", default="m10_01_00_00")
    ap.add_argument("--mode", default="walk", choices=("walk", "sprint"))
    a = ap.parse_args()
    import control
    import env
    import navmesh
    from botlock import BotLock
    from souls import missions, moves
    from dsr_telemetry import OFF_HP
    goal = tuple(missions.SPOTS[a.to]["stand"])
    lock = BotLock()
    if not lock.acquire():
        raise SystemExit("봇이 돌고 있음 (data/bot.lock)")
    out = ROOT / "data" / "runs" / f"{time.strftime('%Y%m%d_%H%M%S')}_explore.jsonl"
    tm = pad = None
    stop_rec = threading.Event()
    res, arrived = None, False
    try:
        control.focus_game()
        time.sleep(0.8)
        tm = env.make_telemetry({})
        pad = control.Pad()
        time.sleep(2.0)
        mv = moves.Moves(tm, pad)
        nm = navmesh.Navmesh(a.map)
        s = tm.snapshot(within=30.0)
        start = (s.player.x, s.player.y, s.player.z)
        path = nm.find_path(start, goal)
        length = sum(math.dist(p, q) for p, q in zip(path, path[1:]))
        print(f"탐색: {a.src} {tuple(round(v, 1) for v in start)} → {a.to} {goal} · NavMesh 경로 {len(path)}점 {length:.0f} m")
        if not path:
            raise SystemExit("NavMesh 경로 없음")
        for f in FLAGS:
            tm.set_dbg(getattr(tm, f), True)
        print("플래그 켬:", {f: tm.get_dbg(getattr(tm, f)) for f in FLAGS})

        def rec():
            with out.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"k": "hdr", "from": a.src, "to": a.to, "map": a.map, "goal": goal, "path": path}) + "\n")
                t0 = time.time()
                while not stop_rec.is_set():
                    sn = tm.snapshot(within=30.0)
                    # NO_DEAD는 피해를 막지 않음 (11-11: 기사와 싸우다 849 → 36) — 줄면 바로 최대로 다시 씀 (M1111-14 '무적')
                    if sn is not None and 0 < sn.player.hp < sn.player.max_hp:
                        tm.pm.write_int(tm.player_ptr() + OFF_HP, sn.player.max_hp)
                    if sn is not None:
                        fh.write(json.dumps({"t": round(time.time() - t0, 2), "pos": [round(sn.player.x, 2), round(sn.player.y, 2),
                                             round(sn.player.z, 2)], "hp": sn.player.hp, "anim": sn.player.anim,
                                             "near": sorted((c.npc_param, round(c.dist, 1)) for c in sn.chars if c.dist < 12)[:6]}) + "\n")
                    time.sleep(0.25)
        th = threading.Thread(target=rec, daemon=True)
        th.start()
        t0 = time.time()
        res = mv.walk_path(path, nm, mode=a.mode, tol=1.0, timeout_per=12.0)
        s = tm.snapshot(within=30.0)
        here = (s.player.x, s.player.y, s.player.z) if s else None
        d = math.dist(here, goal) if here else None
        arrived = d is not None and d <= ARRIVE_M
        # 경로상 어디까지 갔나: 가장 가까운 경로점
        k = min(range(len(path)), key=lambda i: math.dist(path[i], here)) if here else None
        print(f"결과: {res} · {time.time() - t0:.0f} s · 지금 {tuple(round(v, 1) for v in here) if here else None} · 목표까지 {d:.1f} m · "
              f"경로점 {k}/{len(path) - 1} · HP {s.player.hp if s else None}")
    finally:
        stop_rec.set()
        if pad is not None:
            pad.neutral()
        if tm is not None:
            if arrived:
                for f in FLAGS:
                    tm.set_dbg(getattr(tm, f), False)
                print("도착 — 플래그 끔:", {f: tm.get_dbg(getattr(tm, f)) for f in FLAGS})
            else:
                print("도착 못 함 — 플래그(무적·투명·무음)는 켠 채 둠:", {f: tm.get_dbg(getattr(tm, f)) for f in FLAGS})
        if pad is not None:
            pad.close()
        lock.release()
        print(f"→ {out}")


if __name__ == "__main__":
    main()
