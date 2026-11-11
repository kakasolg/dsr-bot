"""Andre's bonfire (1012964) → first group → walkway pair, MoKa's demo 2026-10-19 (docs/stages/new-route-20261019.md §5).

  python run.py parish-group1 --radar       first group only (A–C)
  python run.py parish-route --radar        first group, then the walkway: 256000 (D) and 255040 (E) to the route end

Order: (if far) walk the recorded route back to the bonfire → rest (every foe revives) → recorded route points 0–20
(stairs, then west to MoKa's F9 marker) → fight the three c2550 soldiers in MoKa's kill order → stop where we stand.
Existing layers only: Field.walk / walk_to / fight / recover, duel RULES, guardkeep, reflex. No parry, no B-22 predictor.
foes.py is left as it is (255041 / 255042 fall back to UNKNOWN) — this run is the baseline for that choice.
"""
from __future__ import annotations

import json
import math
import time

ROUTE = "new-route-20261019.json"
MARKER_I = 20                                    # route point nearest MoKa's F9 marker (36.9, 26.6, 107.4)
# 첫 무리 — MSB m10_01_00_00 배치 = 시범 기록의 첫 위치. 순서 = MoKa가 잡은 순서 (65.9 · 88.4 · 104.1 s)
TARGETS = [
    {"npc": 255042, "pos": (30.3, 26.6, 113.4), "msb": "c2550_0045"},
    {"npc": 255041, "pos": (30.5, 26.6, 103.3), "msb": "c2550_0046"},
    {"npc": 255041, "pos": (26.2, 26.6, 100.0), "msb": "c2550_0047"},
]
# 통로 둘 — 시범 D·E (138.7 · 152.6 s). 256000 = c2560: 3006은 r 0.4 타격 ImpactLevel 5 (가드 브레이크 모양, 미확인)
WALKWAY = [
    {"npc": 256000, "pos": (37.7, 29.8, 60.8), "msb": "c2560_0003"},
    {"npc": 255040, "pos": (38.2, 29.8, 44.0), "msb": "c2550_0031"},
]
WALKWAY_FROM_I = 28                              # route point (28.5, 26.6, 101.5): after the demo's group wander, up the slope
GROUP_R = 15.0                                   # 무리 정리 판정: 스폰 중심에서 이 안에 산 255041·255042가 없으면 cleared
GROUP_LIMIT_S = 180.0                            # 첫 무리를 이 안에 못 끝내면 멈추고 MoKa에게 넘긴다 (시범 42 s)
NEAR_BONFIRE = 5.0


def load_route(data_dir) -> list[tuple]:
    return [tuple(q) for q in json.loads((data_dir / "routes" / ROUTE).read_text(encoding="utf-8"))["points"]]


def legs(pts: list[tuple]) -> tuple[list, list]:
    """→ (bonfire → marker, route end → bonfire). The way back skips the demo's fight wander (points 22–26)."""
    out = pts[:MARKER_I + 1]
    back = list(reversed(pts[28:])) + [pts[27], pts[21]] + list(reversed(pts[:MARKER_I + 1]))
    return out, back


def left_alive(s, targets=TARGETS) -> list:
    """Group foes still alive near the spawns — a foe can die inside another target's fight (run 205059: 255041 cut in, was killed,
    then the next target's spot was empty), so per-target results alone undercount."""
    if s is None:
        return []
    npcs = {e["npc"] for e in targets}
    return [c for c in s.chars if c.npc_param in npcs and c.hp > 0
            and min(math.dist((c.x, c.y, c.z), e["pos"]) for e in targets) < GROUP_R]


def nearest_i(pts: list[tuple], p) -> int:
    return min(range(len(pts)), key=lambda i: math.dist(pts[i], p))


class Group1:
    def __init__(self, fld, nm, data_dir, bonfire: dict, log=print, events=None):
        self.f, self.nm, self.log = fld, nm, log
        self.ev = events or (lambda *a, **k: None)
        self.bonfire = bonfire
        self.pts = load_route(data_dir)
        self.out, self.back = legs(self.pts)

    def _here(self):
        s = self.f.mv.snap(5.0)
        return None if s is None else (s.player.x, s.player.y, s.player.z)

    def to_bonfire(self) -> str:
        p = self._here()
        if p is None or math.dist(p, tuple(self.bonfire["stand"])) <= NEAR_BONFIRE:
            return "here"
        i = nearest_i(self.back, p)
        if math.dist(self.back[i], p) > 6.0:
            return self.f.walk_to(tuple(self.bonfire["stand"]), self.nm, "화톳불로")
        return self.f.walk(self.back[i:], self.nm, "화톳불로(녹화 경로)")

    def run(self, walkway: bool = False) -> str:
        if not self.f.alive() and not self.f.wait_respawn():
            return "not_alive"
        r = self.to_bonfire()
        self.log(f"── 화톳불로: {r}")
        if r == "dead":
            return "died"
        if not self.f.rest_at(self.nm, self.bonfire):
            return "휴식 실패"
        self.log("── 안드레이 화톳불 휴식: 됨")
        r = self.f.walk(self.out, self.nm, "첫 무리 앞(마커)")
        self.log(f"── 마커까지: {r}")
        if r == "dead":
            return "died"
        if r != "arrived":
            return f"walk {r}"                           # 계단 등에서 막힘 — MoKa에게 넘김
        r = self.group()
        if not walkway or r != "cleared":
            return r
        w = self.f.walk(self.pts[WALKWAY_FROM_I:], self.nm, "통로로")
        self.log(f"── 통로 끝까지: {w}")
        if w == "dead":
            return "died"
        r2 = self.clear(WALKWAY, "통로 둘", "시범: 2/2, D 282 · E 1 받음, 에스트 1")
        return f"group cleared / walkway {r2}"

    def group(self) -> str:
        return self.clear(TARGETS, "첫 무리", "시범: 3/3, 42 s, 받은 피해 609, 에스트 1")

    def clear(self, targets: list[dict], name: str, demo: str) -> str:
        s0 = self.f.mv.snap(5.0)
        hp0, est0, t0 = s0.player.hp if s0 else None, self.f.estus_left(), time.time()
        kills, results, taken = 0, [], 0
        for i, e in enumerate(targets, 1):
            tag = f"#{i} {e['npc']}"
            if time.time() - t0 > GROUP_LIMIT_S:
                self.log(f"   ⚠ {GROUP_LIMIT_S:.0f} s 넘음 — 멈춤 (MoKa 인계)")
                results.append("timeout")
                break
            if not self.f.alive():
                results.append("died")
                break
            c = self.f.find_at(e["npc"], e["pos"], 8.0)
            if c is None:
                r = self.f.walk_to(e["pos"], self.nm, f"{tag} 이동")
                if r == "dead":
                    results.append("died")
                    break
                c = self.f.find_at(e["npc"], e["pos"], 15.0)
            if c is None:
                self.log(f"   {tag}: 안 보임 — 앞 싸움 중 이미 잡았을 수 있음")
                results.append("not_seen")
                continue
            res = self.f.fight(c.ptr, self.nm, tag)
            results.append(res.result)
            taken += getattr(res, "taken", 0) or 0
            if res.result == "killed":
                kills += 1
            elif res.result == "me_dead":
                break
            elif not self.f.recover(f"{tag} {res.result}", self.nm) and self.f.estus_left() <= 0:
                results.append("no_estus")
                break
        s1 = self.f.mv.snap(40.0)
        left = left_alive(s1, targets)
        summ = {"left_alive": len(left), "kills": kills, "results": results, "secs": round(time.time() - t0, 1), "taken_in_fights": taken,
                "hp": [hp0, s1.player.hp if s1 else None], "estus": [est0, self.f.estus_left()]}
        self.log(f"── {name}: 남은 적 {len(left)} · 싸움 결과 {results}, {summ['secs']} s, 싸움 중 받은 피해 {taken}, HP {summ['hp']}, 에스트 {summ['estus']} "
                 f"({demo})")
        self.ev("parish_clear", name=name, **summ)
        if "died" in results or "me_dead" in results:
            return "died"
        if s1 is None:
            return "partial (no snapshot) " + ",".join(results)
        return "cleared" if not left else "partial " + ",".join(results)
