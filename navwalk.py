"""내비메시 경로를 실제로 걸어 본다 — 게임 파일에서 뽑은 길이 진짜 걸어지는 길인지 검증한다.

  python navwalk.py where                     지금 어느 구역·어디에 서 있나 (내비메시 높이와 대조)
  python navwalk.py to <x> <y> <z> [--run]    현재 위치에서 그 지점까지 A* 경로를 뽑아 걸어간다
  python navwalk.py tour <반경> [개수]         주변에서 목표를 골라 왕복 — 안전한 구역에서 경로 추종만 검증

경로는 navmesh.py 가 준다 (조각 안은 NVM 인접, 조각 사이는 MCG 게이트, 마지막에 직선으로 폄).
이동은 기존 nav.goto 를 그대로 쓴다 — 전투/가드 없이 순수 이동만 본다.

검증에서 보는 것: 경로점마다 도착했는가(arrived), 막혔는가(timeout/stuck), 내비메시 높이와 실제 높이가
얼마나 벌어지는가. 벌어지는 지점이 곧 "내비메시는 길이라는데 실제로는 못 가는 곳"이다.
"""
from __future__ import annotations

import math
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import control
import danger
import env
import nav
import navmesh

AREAS = ["m10_02_00_00", "m10_01_00_00", "m10_00_00_00", "m11_00_00_00", "m12_00_00_00", "m12_01_00_00",
         "m13_00_00_00", "m13_01_00_00", "m13_02_00_00", "m14_00_00_00", "m14_01_00_00", "m15_00_00_00",
         "m15_01_00_00", "m16_00_00_00", "m17_00_00_00", "m18_00_00_00", "m18_01_00_00"]


def locate(tm, p) -> tuple[str, "navmesh.Navmesh", float] | None:
    """캐릭터가 선 자리를 덮는 내비메시 구역을 찾는다 (구역마다 좌표계가 따로라 이렇게 알아낸다)."""
    for mid in AREAS:
        try:
            nm = navmesh.Navmesh(mid)
        except SystemExit:
            continue
        hit = nm.floor_at(p.x, p.z, p.y)
        if hit is not None and abs(hit[0] - p.y) < 2.0:
            return mid, nm, hit[0]
    return None


def walk(path, tm, pad, tolerance: float = 1.5, timeout: float = 45.0, log=print, guard=None,
         dng=None) -> dict:
    """경로점을 차례로 간다.

    guard 를 주면 전투(막고→한 대)를 같이 돌린다. dng(위험 지점 기억)를 주면 사용자 원칙 두 개를 지킨다:
      · 전에 맞은 자리 20 m 안에 들어오면 **아주 천천히**(creep = 반속 + 가드)
      · 맞은 자리는 그때그때 위험 지점으로 기록한다 (다음 판부터 저절로 느려진다)
    """
    res = {"points": len(path), "arrived": 0, "fails": [], "dy": [], "hits": 0, "slow": 0}
    state = {"hp": None, "slow": False}

    def mode_for(s):
        p = s.player
        spot = dng.near(p.x, p.y, p.z) if dng else None
        if spot is not None:
            if not state["slow"]:
                state["slow"] = True
                res["slow"] += 1
                log(f"    ! 전에 맞은 자리 근처 ({spot['hits']}회) - 아주 천천히")
            return "probe"   # 앞으로/뒤로 반복하며 조금씩만 전진 (사용자 원칙)
        state["slow"] = False
        return guard.mode if guard is not None else "walk"

    def on_tick(s, dist):
        p = s.player
        if state["hp"] is not None and p.hp < state["hp"] and dng is not None:
            dmg = state["hp"] - p.hp
            new = dng.add(p.x, p.y, p.z, dmg)
            res["hits"] += 1
            log(f"    피격 {dmg} (hp {p.hp}) - 위험 지점 {'기록' if new else '갱신'}")
        state["hp"] = p.hp
        if guard is None:
            return
        a = guard.tick(s)
        if a:
            log(f"    guard: {a}  hp {p.hp} 적 {len(s.hostile(20.0))}")

    for i, q in enumerate(path[1:], 1):
        s = tm.snapshot(within=1.0)
        if not s or s.player.hp <= 0:
            res["fails"].append((i, "dead")); break
        d = math.hypot(q[0] - s.player.x, q[2] - s.player.z)
        if guard is not None or dng is not None:
            r = nav.goto(tm, pad, (q[0], q[1], q[2]), tolerance=tolerance, timeout=timeout, log=log,
                         on_tick=on_tick, mode_fn=mode_for,
                         engage_fn=(lambda _s: guard.engage_pos()) if guard else None)
        else:
            r = nav.goto(tm, pad, (q[0], q[1], q[2]), tolerance=tolerance, timeout=timeout, log=log,
                         mode_fn=lambda _s: "sprint" if d > nav.SPRINT_BEYOND else "walk")
        s2 = tm.snapshot(within=1.0)
        if s2 and s2.player.gx is not None:
            res["dy"].append(round(s2.player.y - q[1], 2))
        if r == "arrived":
            res["arrived"] += 1
            log(f"  [{i}/{len(path)-1}] 도착 ({q[0]:.1f},{q[1]:.1f},{q[2]:.1f})  실제 y {s2.player.y:.1f}")
        else:
            res["fails"].append((i, r))
            log(f"  [{i}/{len(path)-1}] {r} — 목표 ({q[0]:.1f},{q[1]:.1f},{q[2]:.1f})")
            if r == "dead":
                break
    pad.neutral()
    return res


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    tm = env.make_telemetry({})
    s = tm.snapshot(within=30.0)
    if not s or s.player.gx is None:
        print("캐릭터 위치를 못 읽음"); return
    p = s.player
    found = locate(tm, p)
    if not found:
        print(f"현재 좌표 ({p.x:.1f},{p.y:.1f},{p.z:.1f}) 를 덮는 내비메시 구역을 못 찾음"); return
    mid, nm, floor_y = found
    print(f"구역 {mid}  위치 ({p.x:.1f},{p.y:.1f},{p.z:.1f})  내비메시 바닥 {floor_y:.2f} (차이 {floor_y-p.y:+.2f} m)  "
          f"hp {p.hp}/{p.max_hp}  적 {len(s.hostile(30.0))}")
    if cmd == "where":
        return

    if cmd == "to" and len(sys.argv) >= 5:
        goal = tuple(float(v) for v in sys.argv[2:5])
    elif cmd == "tour":
        radius = float(sys.argv[2]) if len(sys.argv) >= 3 else 20.0
        import numpy as np
        ok = nm.walkable()
        d = np.linalg.norm(nm.centroid - np.array([p.x, p.y, p.z]), axis=1)
        cand = np.where(ok & (d > radius * 0.6) & (d < radius) & (np.abs(nm.centroid[:, 1] - p.y) < 3.0))[0]
        if not len(cand):
            print(f"반경 {radius}m 안에 같은 층 목표가 없음"); return
        goal = tuple(float(c) for c in nm.centroid[cand[len(cand) // 2]])
        print(f"목표 자동 선택: ({goal[0]:.1f},{goal[1]:.1f},{goal[2]:.1f})")
    else:
        print(__doc__); return

    path = nm.find_path((p.x, p.y, p.z), goal)
    if not path:
        print("경로 없음"); return
    total = sum(math.dist(path[i], path[i + 1]) for i in range(len(path) - 1))
    print(f"경로점 {len(path)}개  총 {total:.1f} m")
    if "--run" not in sys.argv and cmd != "tour":
        for q in path:
            print("   %7.1f %7.1f %7.1f" % q)
        print("(실제로 걸으려면 --run)")
        return

    control.focus_game()
    pad = control.Pad()
    dng = danger.Danger(mid)
    print(f"위험 지점 {len(dng.points)}개 기억 중 - 반경 {danger.SLOW_RADIUS} m 안에서는 아주 천천히")
    guard = None
    if "--fight" in sys.argv:
        import json, patrol, playbook
        pbf = playbook.ROOT / "data" / "playbook-dsr" / "current.json"   # DSR 은 별도 플레이북 (learn.py 와 같은 경로)
        pb = playbook.Playbook.from_json(pbf.read_text(encoding="utf-8")) if pbf.exists() else playbook.Playbook()
        guard = patrol.Guard(pad, pb, log=print)
        print(f"전투 켬 — 사거리 {pb.attack_range} 쿨 {pb.attack_cooldown} 락온 {pb.lock_range} 다수기준 {pb.crowd_threshold}")
    t0 = time.time()
    try:
        res = walk(path, tm, pad, guard=guard, dng=dng)
    finally:
        pad.neutral()
    print(f"\n결과: 경로점 {res['points']-1}개 중 도착 {res['arrived']}, 실패 {len(res['fails'])} {res['fails']}  피격 {res['hits']} 감속 {res['slow']}  "
          f"({time.time()-t0:.0f}s)")
    if res["dy"]:
        print(f"내비메시 높이와 실제 높이 차: {res['dy']}")


if __name__ == "__main__":
    main()
