"""불의 제전 화톳불 → 묘지 해골 구역 시체(宝死体07, 아이템 로트 1020150 = 츠바이헨더 350000) 줍고 → 달려서 화톳불."""
import sys, time, math, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import control, env, nav, navmesh, farm, merchantrun as mr, ladder_test as L

ITEM = (-23.7, -70.3, 167.5)
tm = env.make_telemetry({}); pad = control.Pad(); pad.reconnect(); control.focus_game()
n = navmesh.Navmesh(mr.MAP_A)
def here():
    s = tm.snapshot(within=5.0); return (s.player.x, s.player.y, s.player.z)
def run(goal, tol=0.8, timeout=60):
    p = n.find_path(here(), goal) or [goal]
    r = nav.follow(tm, pad, [tuple(q) for q in p[1:]] + [goal], terrain=None,
                   mode_fn=lambda s: "sprint" if s.player.sp > 25 else "walk", default_tol=tol, log=lambda *a: None)
    pad.neutral(); print("→", [round(v, 1) for v in goal], r, [round(v, 1) for v in here()], "HP", tm.snapshot(within=3).player.hp, flush=True)
    return r
try:
    run(ITEM, 0.6)
    nav.goto(tm, pad, ITEM, tolerance=0.4, timeout=4, log=lambda *a: None, mode_fn=lambda _s: "walk"); pad.neutral()
    print("안내", L.prompt_px(), L.shot("zwei_item.jpg"))
    for _ in range(3):
        L.press_a(pad); time.sleep(0.8)
    print("주운 뒤", L.shot("zwei_after.jpg"))
    run(tuple(mr.BONFIRE["stand"]), 1.5)
    print("휴식", farm.rest(tm, pad, n, mr.BONFIRE))
finally:
    pad.neutral()
