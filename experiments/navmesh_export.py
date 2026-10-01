"""NavMesh를 게임 폴더 없이 쓰도록 내보내기 — 걷기 하네스 2층용 ([cloud]는 게임 파일이 없음, ROADMAP 6-a).

  python experiments/navmesh_export.py [mapID ...]     (기본: Burg m10_01_00_00 · Firelink m10_02_00_00 · Asylum m18_01_00_00)

→ data/samples/navmesh_<mapID>.npz:
  v (N,3) 꼭짓점 — MSB 배치(이동·Y 회전) 적용된 게임 좌표 · t (M,3) 삼각형 꼭짓점 번호 · flags (M,) · piece (M,) 조각(NVM) 번호
  adj (M,3) 조각 안 이웃 삼각형(-1 = 없음) · gate_tri / gate_id — MCG 게이트(조각 사이 문): gate_id가 같은 삼각형끼리 서로 이어짐
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import sys
from pathlib import Path

import numpy as np

import navmesh

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

OUT = Path(__file__).resolve().parent.parent / "data" / "samples"
MAPS = ["m10_01_00_00", "m10_02_00_00", "m18_01_00_00"]


def export(map_id: str) -> Path:
    nm = navmesh.Navmesh(map_id)
    gates = nm.gates()
    gate_tri = np.array([i for g in gates for i in g], dtype=np.int32)
    gate_id = np.array([k for k, g in enumerate(gates) for _ in g], dtype=np.int32)
    out = OUT / f"navmesh_{map_id}.npz"
    np.savez_compressed(out, map_id=map_id, v=nm.v, t=nm.t.astype(np.int32), flags=nm.flags.astype(np.int32),
                        piece=nm.piece.astype(np.int32), adj=nm.adj.astype(np.int32), gate_tri=gate_tri, gate_id=gate_id)
    print(f"{map_id}: 꼭짓점 {len(nm.v)}, 삼각형 {len(nm.t)}, 조각 {nm.piece.max() + 1}, 게이트 {len(gates)} → {out.name} "
          f"({out.stat().st_size / 1024:.0f} KB)")
    return out


if __name__ == "__main__":
    for m in sys.argv[1:] or MAPS:
        export(m)
