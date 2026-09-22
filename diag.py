"""왜 빗나가는지 구분한다 — 반응 속도 / 상태 인식 / 사거리·정렬 중 무엇인가.

  python diag.py <x> <y> <z> [초]

"스윙 13회 중 명중 5회"까지는 알아도 나머지 8회가 왜 빗나갔는지는 안 보인다. 스윙마다 아래를 남겨
세 가지를 구분한다:

  · 스윙 직후 **내 애니**가 공격(3xxxxx)으로 바뀌었나 → 안 바뀌었으면 **입력이 씹힌 것**(상태 문제)
  · 공격은 나갔는데 적 HP 가 안 줄었나        → **사거리·정렬 문제**
  · 그때 **적의 애니**가 무엇이었나            → 적이 피하는 중/때리는 중이었나
  · 틱 한 바퀴에 걸린 시간                     → **반응 속도 문제**

봇이 직접 싸우면서 잰다 (사람이 조작하는 dmglog 와 달리).
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import control
import env
import nav
import navmesh
import navwalk
import patrol
import playbook as pbm

ATTACK_ANIM = range(300000, 310000)   # 내 공격 애니 (실측: 303000/303001/303040/303150)


def main() -> None:
    tgt = tuple(float(v) for v in sys.argv[1:4])
    secs = float(sys.argv[4]) if len(sys.argv) > 4 else 180
    tm = env.make_telemetry({})
    pbm.set_dir(pbm.DIR.parent / "playbook-dsr")
    pb = pbm.load_current()
    control.focus_game()
    pad = control.Pad()
    guard = patrol.Guard(pad, pb, log=lambda *a: None)
    s0 = tm.snapshot(within=1.0)
    nm = navmesh.Navmesh(navwalk.locate(tm, s0.player)[0])

    swings: list[dict] = []
    ticks: list[float] = []
    st = {"pend": None, "last": time.time()}

    def on_tick(s, _d=None):
        now = time.time()
        ticks.append((now - st["last"]) * 1000)
        st["last"] = now
        p = s.player
        pend = st["pend"]
        if pend is not None:
            cur = next((c for c in s.chars if c.ptr == pend["ptr"]), None)
            if (p.anim or 0) in ATTACK_ANIM and not pend["came_out"]:
                pend["came_out"] = True
                pend["out_ms"] = round((now - pend["t"]) * 1000)
            if cur is not None and cur.hp < pend["hp0"]:
                pend["hit"] = True
                pend["dmg"] = pend["hp0"] - cur.hp
            if now - pend["t"] > 1.4:
                swings.append(pend)
                st["pend"] = None
        a = guard.tick(s)
        if a in ("attack", "counter", "combo") and guard.engage is not None and st["pend"] is None:
            e = guard.engage
            st["pend"] = {"t": now, "kind": a, "dist": round(e.dist, 2), "ptr": e.ptr, "hp0": e.hp,
                          "my_anim": p.anim, "enemy_anim": e.anim, "locked": guard.locked,
                          "sp": p.sp, "came_out": False, "out_ms": None, "hit": False, "dmg": 0}

    t0 = time.time()
    path = nm.find_path((s0.player.x, s0.player.y, s0.player.z), tgt)
    print(f"경로 {len(path)}점 — 진단 시작 (사거리 {pb.attack_range})", flush=True)
    for q in path[1:]:
        if time.time() - t0 > secs:
            break
        r = nav.goto(tm, pad, q, tolerance=1.5, timeout=40, log=lambda *a: None, on_tick=on_tick,
                     mode_fn=lambda _s: guard.mode, engage_fn=lambda _s: guard.engage_pos())
        if r == "dead":
            print("사망"); break
    # 목표 도착 후에도 주변 적이 있으면 계속 싸운다
    while time.time() - t0 < secs:
        s = tm.snapshot(within=25.0)
        if not s or s.player.hp <= 0:
            break
        live = [c for c in s.hostile(20.0) if c.hp > 0 and abs(c.y - s.player.y) < 3.0]
        if not live:
            break
        nav.goto(tm, pad, (live[0].x, live[0].y, live[0].z), tolerance=max(0.5, pb.attack_range - 0.3),
                 timeout=12, log=lambda *a: None, on_tick=on_tick,
                 mode_fn=lambda _s: guard.mode, engage_fn=lambda _s: guard.engage_pos())
    pad.guard(False)
    pad.neutral()
    if st["pend"]:
        swings.append(st["pend"])

    Path("data").mkdir(exist_ok=True)
    Path("data/diag.json").write_text(json.dumps({"swings": swings, "tick_ms": ticks}, ensure_ascii=False), encoding="utf-8")
    if not swings:
        print("스윙 없음"); return
    out = [s for s in swings if s["came_out"]]
    hit = [s for s in swings if s["hit"]]
    miss_out = [s for s in out if not s["hit"]]
    eaten = [s for s in swings if not s["came_out"]]
    print(f"\n스윙 {len(swings)}회")
    print(f"  ① 입력이 씹힘 (공격 애니가 안 나옴)   {len(eaten):3}회  {len(eaten)/len(swings)*100:4.0f}%")
    print(f"  ② 공격은 나갔으나 피해 0              {len(miss_out):3}회  {len(miss_out)/len(swings)*100:4.0f}%")
    print(f"  ③ 명중                                {len(hit):3}회  {len(hit)/len(swings)*100:4.0f}%")
    if out:
        oms = [s["out_ms"] for s in out if s["out_ms"] is not None]
        if oms:
            print(f"\n공격이 나오기까지: 중앙 {statistics.median(oms):.0f} ms  (최소 {min(oms)} 최대 {max(oms)})")
    if hit:
        print(f"명중 거리: {min(s['dist'] for s in hit):.2f}~{max(s['dist'] for s in hit):.2f} m")
    if miss_out:
        print(f"빗나간 거리: {min(s['dist'] for s in miss_out):.2f}~{max(s['dist'] for s in miss_out):.2f} m")
        ea = [s["enemy_anim"] for s in miss_out]
        print(f"  빗나갈 때 적 애니: {sorted(set(a for a in ea if a is not None))[:8]}")
    if eaten:
        print(f"씹힐 때 내 애니: {sorted(set(s['my_anim'] for s in eaten if s['my_anim'] is not None))[:8]}")
    if ticks:
        print(f"\n틱 간격: 중앙 {statistics.median(ticks):.0f} ms  90% {sorted(ticks)[int(len(ticks)*0.9)]:.0f} ms  최대 {max(ticks):.0f} ms")
        print(f"  → 초당 {1000/statistics.median(ticks):.1f} 회 판단")


if __name__ == "__main__":
    main()
