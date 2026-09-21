"""
기억하는 지도 — 다크소울은 지도를 안 주니 봇이 걸어 본 자리를 스스로 기억한다.

  python mapmem.py record <이름>     사람/봇이 걷는 동안 5 Hz 로 좌표를 0.5 m 격자에 찍는다 (Ctrl+C 로 끝, 매 20 점마다 저장)
  python mapmem.py stats <이름>      칸 수·범위

저장: data/maps/<이름>.json  {"cell": 0.5, "cells": {"x,z": {"y": 높이, "n": 방문 수, "wall": ["N","E",..]}}}
  · 칸 = 갈 수 있는 자리. 높이(y)는 평균 — 이웃 칸과 1.5 m 넘게 차이 나면 연결 안 함 (층·절벽)
  · wall = 그 방향으로 밀었는데 안 움직인 기록 (봇의 막힘 감지가 채운다)
길찾기(A*)는 nav 쪽에서 이 격자를 읽어 쓴다 (다음 단계).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
MAPS = ROOT / "data" / "maps"
CELL = 0.5


class MapMemory:
    def __init__(self, name: str):
        self.path = MAPS / f"{name}.json"
        self.cells: dict[str, dict] = {}
        if self.path.exists():
            self.cells = json.loads(self.path.read_text(encoding="utf-8")).get("cells", {})

    @staticmethod
    def key(x: float, z: float) -> str:
        return f"{int(x // CELL)},{int(z // CELL)}"

    def visit(self, x: float, y: float, z: float) -> bool:
        """칸을 방문 처리. 새 칸이면 True."""
        k = self.key(x, z)
        c = self.cells.get(k)
        if c is None:
            self.cells[k] = {"y": round(y, 2), "n": 1}
            return True
        c["y"] = round((c["y"] * c["n"] + y) / (c["n"] + 1), 2)
        c["n"] += 1
        return False

    def wall(self, x: float, z: float, direction: str) -> None:
        k = self.key(x, z)
        c = self.cells.setdefault(k, {"y": 0.0, "n": 0})
        c.setdefault("wall", [])
        if direction not in c["wall"]:
            c["wall"].append(direction)

    def save(self) -> None:
        MAPS.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"cell": CELL, "cells": self.cells}, ensure_ascii=False), encoding="utf-8")

    def stats(self) -> str:
        if not self.cells:
            return "빈 지도"
        xs = [int(k.split(",")[0]) for k in self.cells]
        zs = [int(k.split(",")[1]) for k in self.cells]
        ys = [c["y"] for c in self.cells.values()]
        return (f"칸 {len(self.cells)} (≈{len(self.cells) * CELL * CELL:.0f} m²)  x {min(xs) * CELL:.0f}..{max(xs) * CELL:.0f}  "
                f"z {min(zs) * CELL:.0f}..{max(zs) * CELL:.0f}  y {min(ys):.0f}..{max(ys):.0f}  벽 기록 {sum(1 for c in self.cells.values() if c.get('wall'))}")


def record(name: str) -> None:
    import env
    tm = env.make_telemetry({})
    mm = MapMemory(name)
    print(f"탐색 기록 시작: {name} — {mm.stats()}. 걸으세요. Ctrl+C 로 끝", flush=True)
    new = 0
    try:
        while True:
            s = tm.snapshot(within=1.0)
            if s and s.player.gx is not None and s.player.hp > 0:
                if mm.visit(s.player.gx, s.player.gy, s.player.gz):
                    new += 1
                    if new % 20 == 0:
                        mm.save()
                        print(f"  +{new} 칸  ({s.player.gx:.1f}, {s.player.gy:.1f}, {s.player.gz:.1f})  {mm.stats()}", flush=True)
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    mm.save()
    print(f"저장: {mm.path}  {mm.stats()}")


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "record":
        record(sys.argv[2])
    elif len(sys.argv) >= 3 and sys.argv[1] == "stats":
        print(MapMemory(sys.argv[2]).stats())
    else:
        print(__doc__)
