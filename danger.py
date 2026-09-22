"""맞은 자리를 기억한다 — 다크소울은 어디서 당하는지가 정해져 있다.

사용자 원칙: "맞은 지역 20 m 지점부터는 아주 천천히 이동해야 한다."
한 번 피해를 입은 좌표를 구역별로 저장해 두고, 다음에 그 근처에 들어가면 이동을 creep(반속 + 가드)으로 낮춘다.
고정된 z 값 같은 기준이 아니라 **실제로 맞은 기록**이라, 새 구역에서도 저절로 쌓인다.

  python danger.py list <맵ID>          기록된 위험 지점
  python danger.py add <맵ID> <x y z>   손으로 추가
  python danger.py clear <맵ID>

저장: data/danger/<맵ID>.json  [{"pos": [x,y,z], "hits": n, "dmg": 최대피해}]
가까운(MERGE_M 안) 기록은 하나로 합친다 — 같은 자리에서 여러 번 맞아도 점이 늘어나지 않게.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
DIR = ROOT / "data" / "danger"
SLOW_RADIUS = 20.0    # 이 안에 들어오면 아주 천천히 (사용자 원칙)
MERGE_M = 6.0         # 이만큼 가까운 기록은 같은 지점으로 본다


class Danger:
    def __init__(self, map_id: str):
        self.map_id = map_id
        self.path = DIR / f"{map_id}.json"
        self.points: list[dict] = []
        if self.path.exists():
            self.points = json.loads(self.path.read_text(encoding="utf-8"))

    def add(self, x: float, y: float, z: float, dmg: int = 0) -> bool:
        """새 지점이면 True. 가까운 기록이 있으면 거기에 합친다."""
        for p in self.points:
            if math.dist(p["pos"], (x, y, z)) < MERGE_M:
                p["hits"] += 1
                p["dmg"] = max(p.get("dmg", 0), dmg)
                self.save()
                return False
        self.points.append({"pos": [round(x, 1), round(y, 1), round(z, 1)], "hits": 1, "dmg": dmg})
        self.save()
        return True

    def near(self, x: float, y: float, z: float, radius: float = SLOW_RADIUS) -> dict | None:
        """그 자리가 위험 지점 반경 안인가 — 가장 가까운 기록을 돌려준다."""
        best = None
        for p in self.points:
            d = math.dist(p["pos"], (x, y, z))
            if d < radius and (best is None or d < best[0]):
                best = (d, p)
        return best[1] if best else None

    def save(self) -> None:
        DIR.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.points, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "list" and len(sys.argv) >= 3:
        d = Danger(sys.argv[2])
        print(f"{d.map_id}: 위험 지점 {len(d.points)}개 (반경 {SLOW_RADIUS} m 안이면 아주 천천히)")
        for p in sorted(d.points, key=lambda q: -q["hits"]):
            print(f"   ({p['pos'][0]:7.1f},{p['pos'][1]:7.1f},{p['pos'][2]:7.1f})  맞은 횟수 {p['hits']}  최대 피해 {p.get('dmg', 0)}")
    elif cmd == "add" and len(sys.argv) >= 6:
        d = Danger(sys.argv[2])
        print("추가" if d.add(*(float(v) for v in sys.argv[3:6])) else "기존 지점에 합침")
    elif cmd == "clear" and len(sys.argv) >= 3:
        d = Danger(sys.argv[2]); d.points = []; d.save(); print("비움")
    else:
        print(__doc__)
