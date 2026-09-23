"""
상인 달리기 경로의 적 지도 — 화톳불에서 쉰 직후(적이 스폰 자리)에 경로 주변 적을 경로 순서대로 적는다.

  python enemy_map.py            → data/enemy-map.json 과 표

사용자: "이 게임이 유저에게 유리한 점은 몹의 위치가 고정이고 패턴도 일정하다 — 제대로 접근하면 해결 가능하다."
그래서 매번 즉석에서 판단하지 않고, 적마다(스폰 위치로 구분) 알아채는 거리·잡는 법을 정해 두고 그대로 한다. 이 파일은 그 목록의 뼈대.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import env
import merchantrun as mr
import navmesh

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "enemy-map.json"
CORRIDOR = 15.0     # 경로에서 이만큼 안의 적만


def path_pos(path: list, q) -> tuple[float, float]:
    """점 q 를 경로에 내렸을 때 (경로를 따라간 거리, 경로와의 수평 거리)."""
    best, acc = (1e9, 0.0), 0.0
    for a, b in zip(path, path[1:]):
        a2, b2, q2 = np.array([a[0], a[2]]), np.array([b[0], b[2]]), np.array([q[0], q[2]])
        seg = b2 - a2
        L = float(np.linalg.norm(seg))
        t = 0.0 if L < 1e-6 else max(0.0, min(1.0, float((q2 - a2) @ seg) / (L * L)))
        d = float(np.linalg.norm(q2 - (a2 + t * seg)))
        if d < best[0]:
            best = (d, acc + t * L)
        acc += L
    return best[1], best[0]


def main() -> None:
    tm = env.make_telemetry({})
    na, nb = navmesh.Navmesh(mr.MAP_A), navmesh.Navmesh(mr.MAP_B)
    pa = na.find_path(tuple(mr.BONFIRE["stand"]), mr.BOUND_A)
    pb = nb.find_path(mr.BOUND_B, mr.MERCHANT)
    len_a = sum(math.dist(pa[k], pa[k + 1]) for k in range(len(pa) - 1))
    rows = []
    for ptr in tm.chr_ptrs():
        c = tm.read_chr(ptr)
        if not c or c.team != 6 or c.hp <= 0:
            continue
        for leg, path, base in (("A", pa, 0.0), ("B", pb, len_a)):
            s_along, off = path_pos(path, (c.x, c.y, c.z))
            if off <= CORRIDOR:
                # 경로 쪽을 보고 서 있나: 적 정면(heading+π)과 '가장 가까운 경로점 쪽' 사이 각도
                near_pt = min(path, key=lambda q: math.dist(q, (c.x, c.y, c.z)))
                fwd = (c.heading or 0.0) + math.pi
                to_path = math.atan2(near_pt[0] - c.x, near_pt[2] - c.z)
                face_path = abs(math.degrees((to_path - fwd + math.pi) % (2 * math.pi) - math.pi))
                rows.append({"leg": leg, "along_m": round(base + s_along, 1), "off_m": round(off, 1), "npc": c.npc_param,
                             "hp": c.max_hp, "pos": [round(c.x, 2), round(c.y, 2), round(c.z, 2)],
                             "heading": None if c.heading is None else round(c.heading, 3), "face_path_deg": round(face_path),
                             "dy_path": round(c.y - near_pt[1], 1), "anim": c.anim})
                break
    rows.sort(key=lambda r: r["along_m"])
    OUT.write_text(json.dumps({"route_len_a": round(len_a, 1), "enemies": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"경로 A(불의 제전→경계) {len_a:.0f} m, B(경계→상인) — 경로 {CORRIDOR:.0f} m 안의 적 {len(rows)}")
    print(f"{'#':>2} {'구간':<3} {'경로 m':>7} {'옆 m':>5} {'높이차':>6} {'npc':>7} {'HP':>5} {'경로 쪽 보나':>10} {'애니':>6}  위치")
    for i, r in enumerate(rows, 1):
        print(f"{i:>2} {r['leg']:<3} {r['along_m']:>7.1f} {r['off_m']:>5.1f} {r['dy_path']:>6.1f} {r['npc']:>7} {r['hp']:>5} "
              f"{r['face_path_deg']:>8}° {str(r['anim']):>6}  {tuple(r['pos'])}")


if __name__ == "__main__":
    main()
