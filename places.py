"""Names for places and foes on the radar / overlay — so MoKa and the bot's notes can say "town #4 street" or "ramp#2 shield"
instead of coordinates ([MoKa] 2026-10-01: "구역과 이름을 특정하기 힘들어서").

  zone(x, y, z, en)         → zone name or None (first ZONES entry with an anchor within its radius and DY in height)
  Labels().of(char, en)     → a foe's label, fixed per foe (ptr) the first time it is seen:
                               "ramp#2 shield" / "town#4 hollow" (bot mission spawns, data/enemy-map.json · burg-town-map.json)
                               or "hollow-12" (any other foe: its MSB placement number, data/gamefiles/*.json)

Pure apart from reading data/ once. Zones are drawn from known points (spots, spawns, the recorded route) — rough circles,
not walls; first match wins, so the small specific ones come first.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
DY = 4.0                 # same level
SPAWN_R = 6.0            # a foe first seen this close to a mission spawn of its kind is that spawn's foe
MSB_R = 12.0             # …else the nearest game-file placement of its kind within this


def _load(name: str):
    try:
        return json.loads((DATA / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _zones() -> list[tuple[str, str, list, float]]:
    """[(korean, english, anchors [(x, y, z)], radius)] — order matters (first match)."""
    ramp = [tuple(e["pos"]) for e in (_load("enemy-map.json") or {}).get("enemies", [])]
    town = [tuple(e["pos"]) for e in (_load("burg-town-map.json") or {}).get("enemies", [])]
    R = _load("routes/passage-merchant.json") or {}
    top = tuple((_load("climb-goal.json") or {}).get("top") or (-24.7, -33.7, 9.3))
    z = [
        ("불의 제전 화톳불", "Firelink bonfire", [(-54.06, -59.95, 58.07)], 12.0),
        ("경사로 아래 평지", "ramp flat", [(-30.0, -49.25, 29.0)], 6.0),
        ("경사로 꼭대기", "ramp top", [top], 5.0),
        ("경사로", "ramp", ramp[1:], 6.0),
        ("제전 북쪽 길", "Firelink north path", [(-33.34, -51.4, 34.32), ramp[0]] if ramp else [(-33.34, -51.4, 34.32)], 9.0),
        ("비밀 통로", "secret passage", [tuple(q) for q in R.get("a", [])], 3.5),
        ("창고 방", "storeroom", [tuple(q) for q in R.get("c", [])], 3.5),
        ("상인", "merchant", [(-39.17, -19.8, -67.81)], 5.0),
        ("마을 화톳불", "Burg bonfire", [(1.7, -10.02, -61.2)], 8.0),
        ("석궁병 자리 (#5)", "crossbow spot (#5)", town[4:5], 5.0),
        ("마을 첫 마당 (#1~#3)", "town yard (#1-#3)", town[:3], 8.0),
        ("마을 #4 길 (셋 몰림)", "town #4 street (packs)", [(-28.1, -13.4, -58.8), (-34.7, -15.3, -45.3), (-20.0, -13.4, -62.5)], 7.0),
        ("마을 길", "town path", [tuple(q) for q in R.get("b", [])], 4.0),
    ]
    return LANDMARKS + [x for x in z if x[2]] + UPPER


# ── 상층 (마을 화톳불 다음, [MoKa] 2026-10-31 "zone을 더 세분화 … 그래야 내가 설명하기가 좋은데") ──────────────
# 작은 지점이 먼저 맞도록 맨 앞에 둔다. 좌표 출처: docs/boss-taurus.md · burg-upper-map.json 구역 8 · treasures.json 宝箱01 ·
# 10-31 스크린샷 "A: Open"(송진 문) · missions.to_altar_bridge 경로.
LANDMARKS = [
    ("송진 문", "resin door", [(19.9, -5.72, -103.7)], 2.5),
    ("송진 상자", "resin chest", [(31.34, -7.45, -111.07)], 2.5),
    ("탑 사다리 아래", "tower ladder bottom", [(49.16, 15.97, -117.1)], 1.8),
    ("탑 안개벽", "tower fog wall", [(52.07, 17.21, -118.55), (49.62, 16.79, -118.74)], 2.0),
    ("탑 사다리 위", "tower ladder top", [(49.96, 24.81, -116.86)], 2.0),
    ("탑 위 석궁병", "tower crossbows", [(52.9, 23.8, -119.8), (52.6, 23.8, -121.4)], 3.5),
    ("타우로스 부르는 자리", "Taurus call spot", [(22.9, 15.9, -120.9)], 3.0),
    ("타우로스 다리", "Taurus bridge", [(40.0, 16.0, -118.5), (31.0, 15.9, -119.8), (14.2, 15.8, -118.3),
                                         (5.0, 16.3, -115.5), (-3.3, 16.8, -112.5)], 5.0),
    ("헬카이트 다리 입구", "Hellkite bridge entrance", [(-21.3, 9.47, -101.77)], 5.0),
]


def _upper() -> list:
    """상층 n = burg-upper-map.json 구역 n의 안전 자리 + 그 구역 적 자리 (봇 로그 burg-upper:n 과 같은 번호)."""
    out = []
    for zn in (_load("burg-upper-map.json") or {}).get("zones", []):
        pts = [tuple(zn["safe"])] + [tuple(k[1]) for k in zn.get("kills", [])]
        out.append((f"상층 {zn['n']}", f"upper {zn['n']}", pts, 6.0))
    return out


UPPER = _upper()
ZONES = _zones()
NEAR_M = 20.0            # where(): outside every circle → nearest name on the same level within this


def upper_zone(x: float, y: float, z: float) -> int | None:
    """burg-upper zone number whose anchors are nearest on the same level (for a stain's zone) — None off the upper map."""
    best = min(((math.hypot(x - a[0], z - a[2]), int(ko.split()[1])) for ko, _, anchors, _ in UPPER for a in anchors
                if abs(y - a[1]) <= DY), default=(None, None))
    return best[1] if best[0] is not None and best[0] <= NEAR_M else None


def where(x: float, y: float, z: float) -> str | None:
    """Overlay line, Korean: "상층 4 · 송진 문", "마을 화톳불", or "상층 4 근처 6 m" outside every circle."""
    name = zone(x, y, z, en=False)
    area = next((ko for ko, _, anchors, r in UPPER
                 if any(math.hypot(x - a[0], z - a[2]) <= r and abs(y - a[1]) <= DY for a in anchors)), None)
    if name is None:
        d, near = min(((math.hypot(x - a[0], z - a[2]), ko) for ko, _, anchors, _ in ZONES for a in anchors
                       if abs(y - a[1]) <= DY), default=(None, None))
        return f"{near} 근처 {d:.0f} m" if d is not None and d <= NEAR_M else None
    return f"{area} · {name}" if area and area != name else name


def zone(x: float, y: float, z: float, en: bool = True) -> str | None:
    for ko, eng, anchors, r in ZONES:
        if any(math.hypot(x - a[0], z - a[2]) <= r and abs(y - a[1]) <= DY for a in anchors):
            return eng if en else ko
    return None


KIND = {"hollow": ("망자", "hollow"), "shield": ("방패병", "shield"), "skeleton": ("해골", "skeleton"), "boss": ("보스", "boss")}


def _kind(npc: int | None, en: bool) -> str:
    try:
        from souls import foes
        f = foes.of(npc)
    except Exception:
        f = None
    if npc == 255002:
        return "crossbow" if en else "석궁병"
    if f is not None and f.ranged:
        return "thrower" if en else "투척병"
    ko, eng = KIND.get(getattr(f, "kind", None), ("적", "foe"))
    return eng if en else ko


class Labels:
    """Foe labels, fixed per ptr (a foe keeps its name while it wanders off its spawn)."""

    def __init__(self, spawns: dict | None = None, msb: list | None = None):
        if spawns is None:
            spawns = {("경사로", "ramp"): (_load("enemy-map.json") or {}).get("enemies", []),
                      ("마을", "town"): (_load("burg-town-map.json") or {}).get("enemies", [])}
            # 상층 n#i = burg-upper-map.json 구역 n의 kills i번째 ([MoKa] 10-31 "상대하게 하는 적의 이름도 특정")
            for zn in (_load("burg-upper-map.json") or {}).get("zones", []):
                spawns[(f"상층{zn['n']}", f"upper{zn['n']}")] = [{"npc": k[0], "pos": k[1]} for k in zn.get("kills", [])]
        self.spawns = spawns
        if msb is None:
            msb = []
            for p in sorted((DATA / "gamefiles").glob("*.json")):
                for e in (_load(f"gamefiles/{p.name}") or {}).get("enemies", []):
                    if e.get("kind") == "enemy":
                        msb.append((e["npc_param_id"], tuple(e["pos"]), e["name"]))
        self.msb = msb
        self.by_ptr: dict = {}

    def _fresh(self, c: dict) -> tuple:
        npc, x, y, z = c.get("npc"), c.get("x"), c.get("y"), c.get("z")
        taken = {v[1][1:] for p, v in self.by_ptr.items() if p != c.get("ptr") and v[1][0] == "spawn"}
        cand = []                                            # nearest free spawn (상층 구역은 같은 종류가 몇 m 간격으로 붙어 있음)
        for (ko, eng), es in self.spawns.items():
            for i, e in enumerate(es, 1):
                q = e["pos"]
                d = math.hypot(x - q[0], z - q[2])
                if (e.get("npc") == npc and d <= SPAWN_R and abs(y - q[1]) <= DY
                        and (ko, eng, i) not in taken):      # one foe per mission spawn — a second one near it gets its MSB number
                    cand.append((d, ("spawn", ko, eng, i)))
        if cand:
            return min(cand, key=lambda t: t[0])[1]
        best = min(((math.hypot(x - q[0], z - q[2]), name) for n, q, name in self.msb if n == npc and abs(y - q[1]) <= DY),
                   default=(None, None))
        if best[0] is not None and best[0] <= MSB_R:
            return ("msb", int(best[1].split("_")[-1]))
        return ("none",)

    def of(self, c: dict, en: bool = True) -> str:
        ptr, npc = c.get("ptr"), c.get("npc")
        got = self.by_ptr.get(ptr)
        if got is None or got[0] != npc:
            got = (npc, self._fresh(c))
            self.by_ptr[ptr] = got
        k, where = _kind(npc, en), got[1]
        if where[0] == "spawn":
            return f"{where[2] if en else where[1]}#{where[3]} {k}"
        if where[0] == "msb":
            return f"{k}-{where[1]}"
        return f"{k}?"
