"""나이프 오른팔 공간 시험 (P-135, [MoKa] 11-08 "계단에 올라가서 투척나이프 던지기 전에 멈추고 너가 직접 해봐 … 계속 조정해봐").

  python experiments/knife_arm_probe.py --npc 254011 --left 0.0      # 지금 자리에서 그대로 한 번
  python experiments/knife_arm_probe.py --npc 254011 --left 0.2      # 목표 쪽을 보고 왼쪽으로 0.2 m 옮긴 뒤 한 번
  python experiments/knife_arm_probe.py --npc 254011 --left 0.2 --dry  # 옮기기만

던질 때 내 애니를 30 ms마다 적어 벽에 튕김을 본다 (7540 던지기가 끝까지 가는지, 다른 애니로 끊기는지).
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]
import argparse, math, sys, threading, time
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
import control, env, nav, navmesh
from souls import missions, moves as M


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--npc", type=int, default=254011)
    ap.add_argument("--left", type=float, default=0.0, help="목표를 보고 왼쪽으로 이만큼 (음수 = 오른쪽)")
    ap.add_argument("--fwd", type=float, default=0.0, help="목표 쪽으로 이만큼 (계단 위로)")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    tm = env.make_telemetry({})
    control.focus_game(); time.sleep(1.5)
    pad = control.Pad(); time.sleep(2.0)
    nm = navmesh.Navmesh(missions.MAP_B)
    mv = M.Moves(tm, pad)
    s = mv.snap(40.0)
    cands = [c for c in s.chars if c.npc_param == a.npc and c.hp > 0]
    c = min(cands, key=lambda c: c.dist)
    p = s.player

    def room(p, c):
        return nav.side_room(nm, p, c.x - p.x, c.z - p.z)
    print(f"나 ({p.x:.2f},{p.y:.2f},{p.z:.2f}) 목표 {c.npc_param} {c.dist:.1f} m 높이 {c.y-p.y:+.1f} · 옆 바닥 (오른쪽, 왼쪽) {room(p, c)}")
    if abs(a.left) > 0.02 or abs(a.fwd) > 0.02:
        n = math.hypot(c.x - p.x, c.z - p.z)
        fx, fz = (c.x - p.x) / n, (c.z - p.z) / n
        goal = (p.x - fz * a.left + fx * a.fwd, p.z + fx * a.left + fz * a.fwd)
        for _ in range(12):
            s = mv.snap(40.0); q = s.player
            d = math.hypot(goal[0] - q.x, goal[1] - q.z)
            if d < 0.06:
                break
            pad.move(*mv.stick_to(s, goal[0], goal[1], 0.45))
            time.sleep(0.08 if d < 0.25 else 0.15)
            pad.move(0.0, 0.0); time.sleep(0.25)
        pad.move(0.0, 0.0); time.sleep(0.3)
        s = mv.snap(40.0); q = s.player; c = mv.find(s, c.ptr) or c
        print(f"옮김 {math.hypot(q.x-p.x, q.z-p.z):.2f} m → ({q.x:.2f},{q.z:.2f}) · 옆 바닥 {room(q, c)} · 남은 {math.hypot(goal[0]-q.x, goal[1]-q.z):.2f} m")
    if a.dry:
        pad.neutral(); return
    anims, stop = [], threading.Event()

    def rec():
        t0 = time.time()
        while not stop.is_set():
            sn = tm.snapshot(2.0)
            if sn is not None:
                a_ = sn.player.anim
                if not anims or anims[-1][1] != a_:
                    anims.append((round(time.time() - t0, 2), a_))
            time.sleep(0.03)
    th = threading.Thread(target=rec, daemon=True); th.start()
    r = mv.throw_knife(c.ptr, require_lock=True)
    time.sleep(0.6); stop.set(); th.join()
    print("던짐:", r)
    print("내 애니:", anims)
    pad.neutral()


if __name__ == "__main__":
    main()
