"""레벨용 소울 모으기 — 화톳불 쉼 → 수로 계단 사냥터까지 적 하나씩(ah.go) → 돌아와 쉼. 목표 소울 넘으면 멈춘다.
  python boss/soulfarm.py 2400 [최대 판수]"""
import sys, time, json, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent)); sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import ah, navmesh, farm, merchantrun as mr
from ah import tm, pad
ah.nm = navmesh.Navmesh(mr.MAP_A)
GOAL = int(sys.argv[1]) if len(sys.argv) > 1 else 2400
N = int(sys.argv[2]) if len(sys.argv) > 2 else 30
SPOT = (-30.1, -49.6, 25.5)   # spots.json burg-approach 앞 — "앞에 5마리 정도, 쉬운 편"(사용자)
BF = tuple(mr.BONFIRE["stand"])
deaths = 0
try:
    for k in range(N):
        farm.rest(tm, pad, ah.nm, mr.BONFIRE); time.sleep(1.0)
        s0 = tm.souls()
        r = ah.go(SPOT, tol=1.5, log=lambda *a: None)
        r2 = ah.go(BF, tol=2.0, log=lambda *a: None) if r != "dead" else "dead"
        if "dead" in (r, r2):
            deaths += 1; time.sleep(8)
        print(f"{k+1}판 {r}/{r2} 소울 {s0} → {tm.souls()} 사망 {deaths}", flush=True)
        if (tm.souls() or 0) >= GOAL:
            break
finally:
    ah.safe_end(); pad.neutral()
    farm.rest(tm, pad, ah.nm, mr.BONFIRE)
    print("끝 소울", tm.souls(), flush=True)
