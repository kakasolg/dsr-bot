"""
적이 없을 때 경로를 끝까지 걸어 올라갈 수 있나 — 사용자: "화염병 몹 위쪽 놈을 잡으러 계단을 못 올라가. 내가 다 죽일 테니
제일 위까지 갈 수 있는지부터 확인". 경로점마다 결과(arrived/timeout/stuck/unreachable)·걸린 시간·위치를 적는다.

  python climb_test.py navmesh      내비메시 경로 (봇이 지금 쓰는 것) — 지금 자리 → BOUND_A
  python climb_test.py route        사람이 녹화한 경로(firelink-merchant-run.json 구간 A) — 가장 가까운 점부터 끝까지
  [--merchant]                      경계 넘어 상인까지 (구간 B)
  [--mode walk|sprint]              기본 walk
결과: data/climb.jsonl (경로점 한 줄씩)
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import control
import env
import merchantrun as mr
import nav
import navmesh

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "climb.jsonl"


def walk(tm, pad, pts, nm, mode: str, tag: str) -> bool:
    t0 = time.time()
    fails = 0
    for i, q in enumerate(pts):
        s = tm.snapshot(within=5.0)
        if not s:
            print(f"   {tag} {i}: 스냅샷 없음 (로딩?)", flush=True)
            time.sleep(2.0)
            continue
        p0 = (s.player.x, s.player.y, s.player.z)
        t1 = time.time()
        r = nav.goto(tm, pad, tuple(q), tolerance=1.0, timeout=12, log=lambda *a: None, terrain=nm,
                     mode_fn=lambda _s: mode)
        s2 = tm.snapshot(within=5.0)
        p1 = (s2.player.x, s2.player.y, s2.player.z) if s2 else None
        left = None if p1 is None else round(math.dist(p1, q), 2)
        row = {"t": round(time.time() - t0, 1), "tag": tag, "i": i, "goal": [round(v, 2) for v in q], "result": r,
               "secs": round(time.time() - t1, 1), "from": [round(v, 2) for v in p0], "at": None if p1 is None else [round(v, 2) for v in p1],
               "left": left, "hp": s2.player.hp if s2 else None, "anim": s2.player.anim if s2 else None}
        with OUT.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        flag = "" if r == "arrived" else "  <<<"
        print(f"   {tag} {i:3d}/{len(pts)}: {r:<11} {row['secs']:5.1f}s  목표 {row['goal']}  도착 {row['at']}  남은 {left} m{flag}", flush=True)
        if r == "dead":
            return False
        if r != "arrived":
            fails += 1
            if fails >= 3:
                print(f"   {tag}: 연속 {fails}번 못 감 — 여기서 멈춤", flush=True)
                return False
        else:
            fails = 0
    pad.neutral()
    print(f"   {tag}: 끝까지 {time.time() - t0:.0f} s", flush=True)
    return True


def main() -> None:
    args = sys.argv[1:]
    how = args[0] if args else "navmesh"
    mode = args[args.index("--mode") + 1] if "--mode" in args else "walk"
    tm = env.make_telemetry({})
    pad = control.Pad()
    control.focus_game()
    na = navmesh.Navmesh(mr.MAP_A)
    s = tm.snapshot(within=5.0)
    here = (s.player.x, s.player.y, s.player.z)
    goal = mr.BOUND_A
    if "--top" in args:                    # 사용자가 서 있던 자리 (5번 바로 위 윗길) — "지금 있는 위치까지 올라와야 해"
        goal = tuple(json.loads((ROOT / "data" / "climb-goal.json").read_text(encoding="utf-8"))["top"])
    if how == "route":
        pts = [tuple(q) for q in mr.ROUTE["segments"][0]["points"]]
        k = min(range(len(pts)), key=lambda j: math.dist(pts[j], here))
        pts = pts[k:]
    elif how == "user":
        # 사람이 올라간 길 (녹화에서 1.5 m 간격) — 경사로 밑(-24.5,-47.0,29.1)부터. 거기까진 내비메시로
        up = [tuple(q) for q in json.loads((ROOT / "data" / "routes" / "user-climb.json").read_text(encoding="utf-8"))["points"]]
        k0 = min(range(len(up)), key=lambda j: math.dist(up[j], (-24.5, -47.0, 29.1)))
        up = up[k0:] + [goal]
        pts = (na.find_path(here, up[0]) or [up[0]])[1:] + up[1:]
    else:
        pts = (na.find_path(here, goal) or [goal])[1:]
    print(f"── {how} ({mode}): {len(pts)} 점, 지금 {tuple(round(v, 1) for v in here)} → {tuple(round(v, 1) for v in goal)}", flush=True)
    ok = walk(tm, pad, pts, na, mode, how)
    if ok and "--merchant" in args:
        nb = navmesh.Navmesh(mr.MAP_B)
        time.sleep(1.0)
        s = tm.snapshot(within=5.0)
        here = (s.player.x, s.player.y, s.player.z) if s else mr.BOUND_B
        if how == "route":
            ptsb = [tuple(q) for q in mr.ROUTE["segments"][1]["points"]]
        else:
            ptsb = (nb.find_path(here, mr.MERCHANT) or [mr.MERCHANT])[1:]
        print(f"── 구간 B ({how}): {len(ptsb)} 점 → 상인 {mr.MERCHANT}", flush=True)
        walk(tm, pad, ptsb, nb, mode, how + "-B")
    pad.neutral()


if __name__ == "__main__":
    main()
