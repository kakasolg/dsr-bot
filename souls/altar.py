"""Taurus bridge → Hellkite bridge → Sunlight Altar (MoKa demo 2026-10-12, docs/stages/burg-to-altar.md §2-b).

  python run.py altar --radar            after `python savepoint.py restore backup-20261012-152651-altar-bridge-entry-no-drake`

Order (route data: data/routes/altar-demo-20261012.json, F9 markers ①–④):
  ① bridge entry → sprint without stopping down the stairs to ② (the fly-by breath sweeps the bridge)
  → up the stairs to ③ (cover behind the parapet) and wait for the Hellkite to land on the bridge
  → sprint past it to ④ (terrace) → wait there until it flies back to its perch
  → Claymore (pickup flag 51010210; skipped when already on) → Sunlight Altar bonfire.
"""
from __future__ import annotations

import json
import math
import time

from . import moves as M

DRAKE = 343000
ROUTE = "altar-demo-20261012.json"
CLAYMORE_FLAG = 51010210
BRIDGE_FOES = {255040}                # the two hollows on the bridge — MoKa ran past them 0.85 m away

# ── 임시값 (시연 한 번에서 잰 값) ──────────────────────────────
#  · 착지: 다리 위 (8.9, 9.5, −48.0) — y 12 밑, z −38 ~ −58이면 '앉음'
#  · ③ 대기: 시연 18 s 뒤 착지. [MoKa] "몇십초 기다리면 내려옴", 안 내려올 수도 있음(조건 모름)
#    → 기다림 한도를 넘으면 지금은 그냥 감. MoKa 방법(사다리 → 성벽 마을 화톳불 휴식 → 다시 ③)은 다음 단계
#  · ④ 대기: 시연 도착 4.6 s 뒤 날아오름, 8.7 s 뒤 횃대 (20.6, 18.9, −29.0) — 횃대 = y 15 위
LAND_Y = 12.0
LAND_Z = (-58.0, -38.0)
PERCH_Y = 15.0
COVER_WAIT_S = 60.0
TERRACE_WAIT_S = 25.0
PICK_TRIES = 3


def load_route(data_dir) -> dict:
    return json.loads((data_dir / "routes" / ROUTE).read_text(encoding="utf-8"))


def drake(s):
    return None if s is None else next((c for c in s.chars if c.npc_param == DRAKE), None)


def landed(s) -> bool:
    d = drake(s)
    return d is not None and d.y < LAND_Y and LAND_Z[0] <= d.z <= LAND_Z[1]


def away(s) -> bool:
    """Not on the bridge any more: out of reading range or up on its perch."""
    d = drake(s)
    return d is None or d.y > PERCH_Y


class Altar:
    def __init__(self, field, nm, data_dir, log=print, events=lambda *a, **k: None):
        self.f, self.mv, self.nm = field, field.mv, nm
        self.tm, self.pad = field.mv.tm, field.mv.pad
        self.log, self.events = log, events
        self.R = load_route(data_dir)

    def _where(self, s) -> str:
        d = drake(s)
        return "헬카이트 안 보임" if d is None else f"헬카이트 ({d.x:.1f}, {d.y:.1f}, {d.z:.1f}) 애니 {d.anim}"

    def _leg(self, pts, tag: str, mode: str, ignore: set = frozenset()) -> str:
        self.f.ignore_npcs = {DRAKE} | set(ignore)
        # 질주 중엔 걷기 자동 에스트 끔 — 첫 시험(153318)에서 다리 위 브레스 −183 뒤 멈춰 마심(6 s, 두 번 끊김), 브레스 줄 한가운데
        self.f.walk_heal = mode != "sprint"
        try:
            r = self.f.walk([tuple(q) for q in pts], self.nm, tag, mode=mode)
        finally:
            self.f.walk_heal = True
        self.log(f"   {tag}: {r}")
        self.events("altar", what="leg", leg=tag, result=r)
        return r

    def run(self) -> str:
        """→ 'arrived' | 'died' | '<step> <result>'"""
        if not self.f.alive():
            return "died"
        m = self.R["markers"]
        try:
            s = self.mv.snap(80.0)
            self.log(f"   시작: {self._where(s)}")
            p = s.player
            if math.dist((p.x, p.y, p.z), tuple(m["1_bridge_entry"])) > 4.0:
                r = self.f.walk_to(tuple(m["1_bridge_entry"]), self.nm, "① 다리 입구로")
                if r not in ("arrived", "done"):
                    return "died" if r == "dead" else f"① {r}"
            # ① → ②: 멈추지 않고 계단 아래까지 ([MoKa] "처음 마커 찍은 곳에서 두번째 마커 까지 빨리 달리기로 계단으로 내려가야해")
            r = self._leg(self.R["sprint_1_to_2"], "① → ② 계단 아래 (질주)", "sprint", BRIDGE_FOES)
            if r == "dead" or not self.f.alive():
                return "died"
            r = self.f.walk_to(tuple(m["3_stairs_cover"]), self.nm, "② → ③ 엄폐 자리")
            self.log(f"   ② → ③: {r}")
            if r == "dead" or not self.f.alive():
                return "died"
            r = self._wait_landing()
            if r == "died":
                return r
            r = self._leg(self.R["sprint_3_to_4"], "③ → ④ 테라스 (질주)", "sprint")
            if r == "dead" or not self.f.alive():
                return "died"
            self._wait_away()
            r = self._claymore()
            if r == "died":
                return r
            r = self.f.walk_to(tuple(self.R["altar_bonfire"]), self.nm, "제단 화톳불로")
            self.log(f"   제단 화톳불로: {r}")
            if r == "dead" or not self.f.alive():
                return "died"
            return "arrived" if r in ("arrived", "done") else f"화톳불 {r}"
        finally:
            self.f.ignore_npcs = set()
            self.pad.sprint(False)
            self.pad.neutral()

    def _wait_landing(self) -> str:
        """At ③: wait for it to land on the bridge. Not within COVER_WAIT_S → go anyway (for now)."""
        t0 = time.time()
        seen = False
        while time.time() - t0 < COVER_WAIT_S:
            if not self.f.alive():
                return "died"
            s = self.mv.snap(80.0)
            seen = seen or drake(s) is not None
            if landed(s):
                self.log(f"   ③ 헬카이트 착지 {time.time() - t0:.1f} s: {self._where(s)}")
                self.events("altar", what="landed", wait=round(time.time() - t0, 1))
                return "landed"
            time.sleep(0.1)
        self.log(f"   ③ {COVER_WAIT_S:.0f} s 안에 착지 안 함 ({'보였음' if seen else '한 번도 안 보임'}) — 그냥 감")
        self.events("altar", what="no_landing", seen=seen)
        return "timeout"

    def _wait_away(self) -> None:
        """At ④: wait until it is off the bridge (perch / out of range) — [MoKa] "테라스쪽으로 뛰어가서 기다리면 다른 곳으로 날아감"."""
        t0 = time.time()
        while time.time() - t0 < TERRACE_WAIT_S:
            s = self.mv.snap(80.0)
            if away(s):
                self.log(f"   ④ 헬카이트 떠남 {time.time() - t0:.1f} s: {self._where(s)}")
                return
            time.sleep(0.2)
        self.log(f"   ④ {TERRACE_WAIT_S:.0f} s 기다려도 다리 위 — {self._where(self.mv.snap(80.0))}, 그냥 감")

    def _claymore(self) -> str:
        c = self.R["claymore"]
        if self.tm.event_flag(c["flag"]):
            self.log("   클레이모어: 이미 주움 (플래그 켜짐) — 건너뜀")
            return "had"
        r = self.f.walk_to(tuple(c["pos"]), self.nm, "클레이모어")
        if r == "dead" or not self.f.alive():
            return "died"
        for k in range(PICK_TRIES):
            self.mv.press(M.B.XUSB_GAMEPAD_A)
            time.sleep(1.5)
            if self.tm.event_flag(c["flag"]):
                self.log(f"   클레이모어: 주움 ({k + 1}번째 A)")
                self.events("altar", what="claymore", got=True)
                self.mv.press(M.B.XUSB_GAMEPAD_A)           # close the item pop-up
                return "got"
        self.log("   클레이모어: 못 주움")
        self.events("altar", what="claymore", got=False)
        return "miss"
