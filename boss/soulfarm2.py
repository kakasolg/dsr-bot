"""레벨용 소울 — 상인 가는 길(계단 위 → 다리 → 통로 → 성벽 마을 앞부분)의 망자를 근접으로 하나씩(ah.go). 폭탄·나이프 없음.
  python boss/soulfarm2.py 목표소울 [판수]"""
import sys, time, json, math, pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "boss"))
import ah, navmesh, farm, merchantrun as mr
from ah import tm, pad
NA, NB = navmesh.Navmesh(mr.MAP_A), navmesh.Navmesh(mr.MAP_B)
R = json.loads((ROOT / "data/routes/passage-merchant.json").read_text(encoding="utf-8"))
TOP = tuple(json.loads((ROOT / "data/climb-goal.json").read_text(encoding="utf-8"))["top"])
OUT = [("A", TOP)] + [("A", tuple(q)) for q in R["top_bridge"][::2] + R["a"][::3]] + [("B", tuple(q)) for q in R["b"][:23:3]]
GOAL = int(sys.argv[1]) if len(sys.argv) > 1 else 2400
N = int(sys.argv[2]) if len(sys.argv) > 2 else 20
deaths = 0

def walk(legs):
    for m, q in legs:
        ah.nm = NA if m == "A" else NB
        r = ah.go(q, tol=1.2, log=lambda *a: None)
        if r == "dead":
            return "dead"
    return "ok"

try:
    for k in range(N):
        ah.nm = NA; farm.rest(tm, pad, NA, mr.BONFIRE); time.sleep(1.0); ah.TRAIL.clear()
        s0 = tm.souls(); t0 = time.time()
        r = walk(OUT)
        r2 = walk(list(reversed(OUT[:-1])) + [("A", tuple(mr.BONFIRE["stand"]))]) if r != "dead" else "dead"
        if "dead" in (r, r2):
            deaths += 1; time.sleep(10)
        print(f"{k+1}판 {r}/{r2} 소울 {s0} → {tm.souls()} 사망 {deaths} {time.time()-t0:.0f}s", flush=True)
        if (tm.souls() or 0) >= GOAL:
            break
finally:
    ah.safe_end(); pad.neutral()
    ah.nm = NA; farm.rest(tm, pad, NA, mr.BONFIRE)
    print("끝 소울", tm.souls(), flush=True)
