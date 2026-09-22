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

RETREAT_M = 18.0    # 후퇴 거리 — 지나온 경로를 따라 이만큼 뒤로 (사용자 원칙: 맞으면 충분히 후퇴)

AREAS = ["m10_02_00_00", "m10_01_00_00", "m10_00_00_00", "m11_00_00_00", "m12_00_00_00", "m12_01_00_00",
         "m13_00_00_00", "m13_01_00_00", "m13_02_00_00", "m14_00_00_00", "m14_01_00_00", "m15_00_00_00",
         "m15_01_00_00", "m16_00_00_00", "m17_00_00_00", "m18_00_00_00", "m18_01_00_00"]


def locate(tm, p) -> tuple[str, "navmesh.Navmesh", float] | None:
    """캐릭터가 선 자리를 덮는 내비메시 구역을 찾는다 (구역마다 좌표계가 따로라 이렇게 알아낸다).

    바로 위/아래에 면이 없는 자리도 있다 — 내비메시는 적 AI 기준이라 빈 곳이 생긴다. 그럴 땐 가까운
    면(6 m 안)으로 구역을 판정한다. 실측: 묘지에서 퇴화 삼각형만 3 m 위에 있는 자리에 서서 길찾기가 막혔다."""
    import numpy as np
    best = None
    for mid in AREAS:
        try:
            nm = navmesh.Navmesh(mid)
        except SystemExit:
            continue
        hit = nm.floor_at(p.x, p.z, p.y)
        if hit is not None and abs(hit[0] - p.y) < 2.0:
            return mid, nm, hit[0]
        ok = nm.walkable()
        d = np.linalg.norm(nm.centroid - np.array([p.x, p.y, p.z]), axis=1)
        d = np.where(ok, d, np.inf)
        i = int(d.argmin())
        if np.isfinite(d[i]) and d[i] < 6.0 and (best is None or d[i] < best[0]):
            best = (float(d[i]), mid, nm, float(nm.centroid[i][1]))
    if best:
        return best[1], best[2], best[3]
    return None


def walk(path, tm, pad, tolerance: float = 1.5, timeout: float = 45.0, log=print, guard=None,
         dng=None) -> dict:
    """경로점을 차례로 간다.

    guard 를 주면 전투(막고→한 대)를 같이 돌린다. dng(위험 지점 기억)를 주면 사용자 원칙 두 개를 지킨다:
      · 전에 맞은 자리 20 m 안에 들어오면 **아주 천천히**(creep = 반속 + 가드)
      · 맞은 자리는 그때그때 위험 지점으로 기록한다 (다음 판부터 저절로 느려진다)
    """
    res = {"points": len(path), "arrived": 0, "fails": [], "dy": [], "hits": 0, "slow": 0,
           "swing": [], "land": []}
    state = {"hp": None, "slow": False, "swing_at": 0.0, "swing_d": None, "tgt_hp": None, "tgt_ptr": None}

    def mode_for(s):
        p = s.player
        # 교전 중이면 전투 이동이 우선이다. 위험 지점 감속(probe)은 경로점을 향해 앞뒤로 움직이는 것이라,
        # 이게 전투를 덮으면 봇이 적에게 다가가질 못한다 — 실측: 4.3 m 앞 적을 못 잡고 "닿지 않는 적"으로 포기했다.
        if guard is not None and guard.engage is not None:
            return guard.mode
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
        # 유효 사거리 실측: 휘두른 순간의 거리를 적어 두고, 0.8 s 안에 그 적 HP 가 줄면 "닿은 거리"로 센다.
        # (무기를 바꾸면 사거리가 달라지니 추측 대신 잰다 — 할버드는 도끼보다 훨씬 길다)
        cur = guard.engage
        if cur is not None and state["tgt_ptr"] == cur.ptr and state["tgt_hp"] is not None                 and cur.hp < state["tgt_hp"] and state["swing_d"] is not None                 and time.time() - state["swing_at"] < 0.8:
            res["land"].append(round(state["swing_d"], 2))
            state["swing_d"] = None
        if cur is not None:
            state["tgt_ptr"], state["tgt_hp"] = cur.ptr, cur.hp
        a = guard.tick(s)
        if a:
            log(f"    guard: {a}  hp {p.hp} 적 {len(s.hostile(20.0))}")
        if a in ("attack", "counter", "combo") and guard.engage is not None:
            state["swing_at"], state["swing_d"] = time.time(), guard.engage.dist
            res["swing"].append(round(guard.engage.dist, 2))

    def pull_back(i, log=log) -> bool:
        """HP 가 낮아 Guard 가 후퇴를 원한다 — 지나온 길을 따라 RETREAT_M 뒤까지 달려가 숨을 돌린다.

        이게 없으면 Guard 가 retreat 를 걸어도 nav.goto 가 "retreat" 를 돌려줄 뿐이고, 여기서 그걸
        실패로 적고 **다음 경로점으로 전진해 버린다** — HP 가 줄어도 계속 앞으로 가다 죽는다 (사용자 지적).
        """
        cur = tm.snapshot(within=1.0)
        if not cur or cur.player.hp <= 0:
            return False
        back = None
        for k in range(i - 1, -1, -1):
            if math.dist((path[k][0], path[k][1], path[k][2]),
                         (cur.player.x, cur.player.y, cur.player.z)) >= RETREAT_M:
                back = path[k]
                break
        if back is None:
            back = path[0]
        log(f"    ← 후퇴 (hp {cur.player.hp}) → ({back[0]:.1f},{back[2]:.1f})")
        if guard is not None:
            guard.engage, guard.locked = None, False
        pad.guard(False)
        nav.goto(tm, pad, back, tolerance=2.5, timeout=40, log=lambda *a: None,
                 mode_fn=lambda _s: "sprint")
        pad.neutral()
        # 숨 돌리기: 적이 8 m 밖이고 HP 가 회복될 때까지 (성배병은 Guard 가 마신다)
        t_wait = time.time()
        while time.time() - t_wait < 20:
            sn = tm.snapshot(within=20.0)
            if not sn or sn.player.hp <= 0:
                return False
            if guard is not None:
                guard.tick(sn)
            near = [c for c in sn.hostile(20.0) if c.hp > 0 and abs(c.y - sn.player.y) < 3.0 and c.dist < 8.0]
            if not near and sn.player.hp > sn.player.max_hp * 0.6:
                break
            time.sleep(0.2)
        pad.neutral()
        sn = tm.snapshot(within=1.0)
        log(f"    → 재개 (hp {sn.player.hp if sn else '?'})")
        return bool(sn) and sn.player.hp > 0

    for i, q in enumerate(path[1:], 1):
        s = tm.snapshot(within=1.0)
        if not s or s.player.hp <= 0:
            res["fails"].append((i, "dead")); break
        tries = 0
        d = math.hypot(q[0] - s.player.x, q[2] - s.player.z)
        if guard is not None or dng is not None:
            r = nav.goto(tm, pad, (q[0], q[1], q[2]), tolerance=tolerance, timeout=timeout, log=log,
                         on_tick=on_tick, mode_fn=mode_for,
                         engage_fn=(lambda _s: guard.engage_pos()) if guard else None)
        else:
            r = nav.goto(tm, pad, (q[0], q[1], q[2]), tolerance=tolerance, timeout=timeout, log=log,
                         mode_fn=lambda _s: "sprint" if d > nav.SPRINT_BEYOND else "walk")
        while r == "retreat" and tries < 3:
            tries += 1
            res["retreats"] = res.get("retreats", 0) + 1
            if not pull_back(i):
                r = "dead"
                break
            r = nav.goto(tm, pad, (q[0], q[1], q[2]), tolerance=tolerance, timeout=timeout, log=log,
                         on_tick=on_tick, mode_fn=mode_for,
                         engage_fn=(lambda _s: guard.engage_pos()) if guard else None)
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
    print(f"\n결과: 경로점 {res['points']-1}개 중 도착 {res['arrived']}, 실패 {len(res['fails'])} {res['fails']}  피격 {res['hits']} 감속 {res['slow']} 후퇴 {res.get('retreats', 0)}  "
          f"({time.time()-t0:.0f}s)")
    if res["swing"]:
        sw, la = sorted(res["swing"]), sorted(res["land"])
        print(f"휘두른 거리 {len(sw)}회: {sw[0]:.2f}~{sw[-1]:.2f} m (중앙 {sw[len(sw)//2]:.2f})")
        if la:
            print(f"  → 피해가 들어간 거리 {len(la)}회: {la[0]:.2f}~{la[-1]:.2f} m (중앙 {la[len(la)//2]:.2f})  "
                  f"**유효 사거리 ≈ {la[-1]:.2f} m**")
        else:
            print("  → 피해가 들어간 기록 없음")
    if res["dy"]:
        print(f"내비메시 높이와 실제 높이 차: {res['dy']}")


if __name__ == "__main__":
    main()
