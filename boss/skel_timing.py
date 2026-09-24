"""묘지 해골 공격 타이밍 실측 — 죽지 않음 플래그 켜고 입구에 가만히 서서 (해골 애니 시작 → 내 HP 깎인 시각) 기록.
  python boss/skel_timing.py [초]"""
import sys, time, json, math, pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import control, env, nav, navmesh, farm, merchantrun as mr
tm = env.make_telemetry({}); pad = control.Pad(); pad.reconnect(); control.focus_game()
n = navmesh.Navmesh(mr.MAP_A)
SECS = float(sys.argv[1]) if len(sys.argv) > 1 else 60
SPOT = (-42.4, -59.6, 119.1)
FLAGS = (tm.DBG_PLAYER_NO_DEAD,)
rows, hits = [], []
try:
    for o in FLAGS: tm.set_dbg(o, True)
    print("플래그", [tm.get_dbg(o) for o in FLAGS])
    s = tm.snapshot(within=5); here = (s.player.x, s.player.y, s.player.z)
    p = n.find_path(here, SPOT) or [SPOT]
    print("가기", nav.follow(tm, pad, [tuple(q) for q in p[1:]] + [SPOT], terrain=None, mode_fn=lambda _s: "sprint", default_tol=1.0, log=lambda *a: None))
    pad.neutral()
    start = {}; last = {}; myhp = None; t0 = time.time()
    while time.time() - t0 < SECS:
        s = tm.snapshot(within=25)
        if s is None: time.sleep(0.02); continue
        now = time.time() - t0
        for c in s.hostile(25.0):
            a = c.anim if c.anim is not None else -1
            if last.get(c.ptr) != a:
                last[c.ptr] = a; start[c.ptr] = (a, now)
                rows.append((round(now, 2), c.npc_param, a, round(c.dist, 1)))
        if myhp is not None and s.player.hp < myhp:
            near = sorted(s.hostile(6.0), key=lambda c: c.dist)
            who = [(c.npc_param, start.get(c.ptr, (None, 0))[0], round(now - start.get(c.ptr, (0, now))[1], 2), round(c.dist, 1)) for c in near[:3]]
            hits.append({"t": round(now, 2), "dmg": myhp - s.player.hp, "near": who})
            print("맞음", round(now, 2), myhp - s.player.hp, who, flush=True)
        myhp = s.player.hp
        if myhp < 300:
            tm.set_hp(s.player.max_hp); myhp = s.player.max_hp
        time.sleep(0.02)
finally:
    pad.neutral()
    json.dump({"anims": rows, "hits": hits}, open(ROOT / f"data/trace/skel_timing_{time.strftime('%H%M%S')}.json", "w", encoding="utf-8"))
    s = tm.snapshot(within=5); bf = tuple(mr.BONFIRE["stand"])
    p = n.find_path((s.player.x, s.player.y, s.player.z), bf) or [bf]
    print("복귀", nav.follow(tm, pad, [tuple(q) for q in p[1:]] + [bf], terrain=None, mode_fn=lambda _s: "sprint", default_tol=1.5, log=lambda *a: None))
    farm.rest(tm, pad, n, mr.BONFIRE)
    for o in FLAGS: tm.set_dbg(o, False)
    print("플래그 끔", [tm.get_dbg(o) for o in FLAGS])
