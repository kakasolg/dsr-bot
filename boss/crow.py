"""수용소 데몬 처치 후 → 보스방 남쪽 문 → 경사로 → 절벽 끝 까마귀 둥지 (MSB 'カラスの巣' 1812001)."""
import sys, time, math, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import vgamepad, control, env, nav, navmesh
import ladder_test as L

tm = env.make_telemetry({}); pad = control.Pad(); pad.reconnect(); control.focus_game()
n = navmesh.Navmesh("m18_01_00_00")
def here():
    s = tm.snapshot(within=5.0); return (s.player.x, s.player.y, s.player.z)
def walk(goal, tol=0.7):
    p = n.find_path(here(), goal) or [goal]
    r = nav.follow(tm, pad, [tuple(q) for q in p[1:]] + [goal], terrain=None, mode_fn=lambda _s: "walk", default_tol=tol, log=lambda *a: None)
    pad.neutral(); print("→", goal, r, tuple(round(v, 1) for v in here()), flush=True); return r
try:
    walk((3.4, 198.2, -31.0), 0.5)
    L.face(tm, pad, (0.0, -1.0)); print("문 안내", L.prompt_px(), L.shot("crow_door.jpg"))
    L.press_a(pad); time.sleep(4.0)
    walk((3.4, 198.2, -36.0))
    walk((3.3, 209.8, -83.5))
    print("스크린샷", L.shot("crow_landing.jpg"))
    walk((3.5, 210.0, -95.0), 0.5)
    print("둥지 앞", tuple(round(v, 1) for v in here()), L.shot("crow_cliff.jpg"))
    t0 = time.time()
    while time.time() - t0 < 25:
        s = tm.snapshot(within=5.0)
        if s and abs(s.player.y - 210) > 15:
            print("이동됨", round(s.player.x, 1), round(s.player.y, 1), round(s.player.z, 1)); break
        time.sleep(1)
    print("끝", tuple(round(v, 1) for v in here()), L.shot("crow_end.jpg"))
finally:
    pad.neutral()
