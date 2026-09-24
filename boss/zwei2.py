"""츠바이헨더 2차 — 입구에서 해골을 하나씩 끌어내 방패 들고 잡으며 들어간다(ah.go: 가까운 적 먼저, 둘러싸이면 물러남)."""
import sys, time, math, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent)); sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import ah, navmesh, farm, merchantrun as mr
from ah import tm, pad, L, nav
ah.nm = navmesh.Navmesh(mr.MAP_A)
ITEM = (-23.7, -70.3, 167.5)
LEGS = [(-41.4, -56.2, 71.4), (-44.0, -56.5, 113.7), (-41.4, -63.0, 125.9), (-31.8, -63.4, 141.5), (-25.0, -65.0, 155.4), (-24.5, -66.9, 158.5), ITEM]
try:
    for g in LEGS:
        r = ah.go(g, tol=0.9)
        s = ah.snap(8)
        print("→", g, r, "HP", s.player.hp if s else None, "소울", tm.souls(), flush=True)
        if r == "dead":
            break
    else:
        nav.goto(tm, pad, ITEM, tolerance=0.4, timeout=4, log=lambda *a: None, mode_fn=lambda _s: "guard"); pad.neutral()
        print("안내", L.prompt_px(), L.shot("zwei2_item.jpg"))
        for _ in range(3):
            L.press_a(pad); time.sleep(0.8)
        print("주움", L.shot("zwei2_after.jpg"), flush=True)
        for g in reversed(LEGS[:-1]):
            if ah.go(g, tol=1.2) == "dead":
                print("돌아오다 죽음"); break
        else:
            print("휴식", farm.rest(tm, pad, ah.nm, mr.BONFIRE))
finally:
    ah.safe_end(); pad.neutral()
