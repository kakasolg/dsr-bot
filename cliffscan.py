"""경로 옆이 낭떠러지인지 벽인지 찍어 본다 — 낙사 방지.

  python cliffscan.py <spot 이름> [옆으로 몇 m]

내비메시만으로는 벽과 낭떠러지를 구분할 수 없다 (둘 다 "면이 없음"). 하지만 워프 탐침은 **실제 충돌**을
쓰므로 구분할 수 있다: 그 자리에 놓았을 때 바닥에 내려서면 길, 계속 떨어지면 낭떠러지, 아예 안 움직이면 벽.

경로의 각 점에서 좌우로 offset m 떨어진 자리를 찍어, 낭떠러지로 판정된 곳을 data/cliffs/<맵>.json 에 쌓는다.
navmesh.keep_inside() 가 이 점들에서 경로를 밀어낸다.

**무적으로 돌린다** (HP 고정). 워프는 속도를 리셋하지 않으므로 허공을 찍은 뒤에는 반드시 착지시켜 복구한다
— 안 하면 다음 탐침에서 바닥을 뚫고 월드 밖으로 떨어진다 (mapmem 에서 실측).
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import env
import navmesh

ROOT = Path(__file__).resolve().parent
DIR = ROOT / "data" / "cliffs"
SETTLE_LAG, STABLE_N, STABLE_EPS, MIN_FALL = 0.30, 3, 0.04, 0.15
DROP = 2.0          # 이만큼 위에서 떨어뜨린다
WAIT = 1.6
CLIFF_DROP = 3.0    # 경로 높이보다 이만큼 아래로 떨어지면 낭떠러지


def load(map_id: str) -> list[list[float]]:
    f = DIR / f"{map_id}.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else []


def scan(spot_name: str, offset: float = 1.6) -> None:
    import farm
    spot = farm.SPOTS[spot_name]
    tm = env.make_telemetry({})
    if not hasattr(tm, "set_hp"):
        print("이 게임은 탐침을 지원하지 않음"); return
    nm = navmesh.Navmesh(spot["map"])
    s = tm.snapshot(within=1.0)
    if not s or s.player.gx is None:
        print("캐릭터 위치를 못 읽음"); return
    if getattr(tm, "sitting", lambda: False)():
        print("앉아 있는 상태 — 먼저 일어나세요"); return
    mhp = s.player.max_hp
    start = (s.player.x, s.player.y, s.player.z)
    path = nm.find_path(start, farm.goal_xyz(nm, spot))
    if not path:
        print("경로 없음"); return

    def pos():
        pp = tm.player_ptr()
        mapd = tm.q(pp + 0x68) if pp else None
        posd = tm.q(mapd + 0x28) if mapd else None
        return (tm.f32(posd + 0x10), tm.f32(posd + 0x14), tm.f32(posd + 0x18)) if posd else (None, None, None)

    def probe(x, z, top):
        """→ (착지 높이, 종류). 종류: floor / air(계속 떨어짐) / solid(안 떨어짐 = 벽)"""
        tm.set_hp(mhp)
        tm.pos_warp(x, top, z, 0.0)
        t0, hist, last = time.time(), [], top
        while time.time() - t0 < WAIT:
            time.sleep(0.04)
            tm.set_hp(mhp)
            _, y, _ = pos()
            if y is None or time.time() - t0 < SETTLE_LAG:
                continue
            last = y
            hist.append(y)
            del hist[:-STABLE_N]
            if len(hist) == STABLE_N and max(hist) - min(hist) < STABLE_EPS and y < top - MIN_FALL:
                return y, "floor"
        return None, ("solid" if top - last < 0.5 else "air")

    def settle(x, y, z):
        for _ in range(6):
            tm.set_hp(mhp)
            tm.pos_warp(x, y + 0.5, z, 0.0)
            time.sleep(0.04)
        time.sleep(0.9)

    cliffs = load(spot["map"])
    print(f"경로 {len(path)}점 — 각 점 좌우 {offset} m 를 찍는다 (무적). 기존 기록 {len(cliffs)}개", flush=True)
    found = 0
    try:
        for i in range(1, len(path)):
            a, b = path[i - 1], path[i]
            hx, hz = b[0] - a[0], b[2] - a[2]
            n = math.hypot(hx, hz)
            if n < 0.3:
                continue
            px, pz = -hz / n, hx / n          # 진행 방향의 수직
            for sgn in (+1, -1):
                qx, qz = b[0] + px * offset * sgn, b[2] + pz * offset * sgn
                y, kind = probe(qx, qz, b[1] + DROP)
                if kind == "air" or (kind == "floor" and b[1] - y > CLIFF_DROP):
                    cliffs.append([round(qx, 2), round(b[1], 2), round(qz, 2)])
                    found += 1
                    print(f"  wp{i}: {'좌' if sgn > 0 else '우'}측 낭떠러지 ({qx:.1f},{qz:.1f})"
                          f"{'' if kind == 'air' else f' {b[1]-y:.1f} m 아래'}", flush=True)
                settle(*b)                     # 반드시 착지 — 낙하 속도가 남으면 다음 탐침에서 바닥을 뚫는다
    except KeyboardInterrupt:
        print("  (중단)")
    DIR.mkdir(parents=True, exist_ok=True)
    (DIR / f"{spot['map']}.json").write_text(json.dumps(cliffs, ensure_ascii=False), encoding="utf-8")
    settle(*start)
    print(f"저장: {DIR / (spot['map'] + '.json')}  이번에 {found}개 추가, 총 {len(cliffs)}개")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
    else:
        scan(sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 1.6)
