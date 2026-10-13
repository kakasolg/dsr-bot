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
COVER_FOE_R = 8.0        # at ③: an awake foe this close (same level) is fought before waiting on (10-13: bridge hollow lunged twice)
COVER_PICK_R = 15.0      # at ③: pick up a bloodstain this close (10-13 death at ③: 5432 souls)
TERRACE_WAIT_S = 25.0
PICK_TRIES = 3
LADDER_TRIES = 3
LADDER_DOWN_S = 12.0


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
            # ── ③에서 기다리는 동안 따라온 적은 싸움 (10-13 burg-altar 2번째 사망) ──────────────────────
            #  다리 망자 255040이 ③까지 따라와 3.7 · 5.1 m에서 돌진(3005) 두 번 −335 · −407 → 사망, 봇은 착지만 기다림
            c = self._foe_here(s)
            if c is not None:
                r = self._fight_here(c)
                if r == "died":
                    return "died"
                continue
            if landed(s):
                self.log(f"   ③ 헬카이트 착지 {time.time() - t0:.1f} s: {self._where(s)}")
                self.events("altar", what="landed", wait=round(time.time() - t0, 1))
                return "landed"
            time.sleep(0.1)
        self.log(f"   ③ {COVER_WAIT_S:.0f} s 안에 착지 안 함 ({'보였음' if seen else '한 번도 안 보임'}) — 그냥 감")
        self.events("altar", what="no_landing", seen=seen)
        return "timeout"

    def _foe_here(self, s):
        """An awake foe (not the Hellkite) within COVER_FOE_R on our level, nearest first, or None."""
        if s is None:
            return None
        p = s.player
        cs = [c for c in s.hostile(COVER_FOE_R + 2.0) if c.npc_param != DRAKE and c.hp > 0 and c.anim not in (None, -1)
              and not (9000 <= (c.anim or 0) < 9100) and abs(c.y - p.y) < 2.5 and M.horiz(p, c) < COVER_FOE_R]
        return min(cs, key=lambda c: M.horiz(p, c), default=None)

    def _fight_here(self, c) -> str:
        """Fight a foe that reached ③ the way zone fights do: a low_hp / losing end → Field.recover (back off, drink), then again;
        recover failing → the next fight is desperate (P-47: fighting again at once with no drink = 0 s fights until dead —
        10-13 burg-altar round 4 died that way here, 'low_hp — 0 s' × 30)."""
        tag = f"③ 기다리다 {c.npc_param}"
        desperate = False
        for _ in range(4):
            if not self.f.alive():
                return "died"
            d = self.f.fight(c.ptr, self.nm, tag, desperate=desperate)
            self.log(f"   {tag}: {d.result}")
            if d.result == "me_dead" or not self.f.alive():
                return "died"
            t = self.mv.find(self.mv.snap(80.0), c.ptr)
            if d.result == "killed" or t is None or t.hp <= 0:
                return "killed"
            ok = self.f.recover(f"{tag} {d.result}", self.nm)
            desperate = not ok
        return "left"

    def _pick_here(self) -> None:
        """A bloodstain close by — NOT called any more: ── ③ 밖은 헬카이트 브레스 줄 (10-13 burg-altar 5번째) ──
        ③에서 핏자국 (0.2, 9.47, −63.71)으로 걸어 나가다 브레스 −224 → −742 한 방, 사망 (전 핏자국 소울 8362 · 인간성 2 잃음).
        엄폐 밖으로 나가는 줍기는 헬카이트가 횃대에 있을 때만 — 그 조건을 정하기 전엔 안 씀."""
        r = self.f.pick_blood(self.nm, near=COVER_PICK_R)
        if r is not None:
            self.log(f"   핏자국 (③ 근처): {r}")

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

    def back_to_burg(self) -> str:
        """Altar → over the bridge → under it → down the kicked ladder → Undead Burg bonfire ([MoKa] 착지 안 하면 "숏컷으로 성안
        화톳불로 가서 쉬고 다시 올라오면 됨"). → 'arrived' | 'died' | '<step> <result>'"""
        if not self.f.alive():
            return "died"
        m, lad = self.R["markers"], self.R["ladder_shortcut"]
        try:
            s = self.mv.snap(80.0)
            self.log(f"   시작: {self._where(s)}")
            self.f.ignore_npcs = {DRAKE}
            self.f.walk_heal = False                       # 다리 위에서 멈춰 마시지 않음
            r = self.f.walk_to(tuple(m["2_stairs_bottom"]), self.nm, "다리 건너 계단 아래로", mode="sprint")
            self.f.walk_heal = True
            self.log(f"   계단 아래로: {r}")
            if r == "dead" or not self.f.alive():
                return "died"
            r = self.f.walk_to(tuple(lad["top"]), self.nm, "사다리 위로")
            self.log(f"   사다리 위로: {r}")
            if r == "dead" or not self.f.alive():
                return "died"
            r = self._ladder_down(tuple(lad["top"]), tuple(lad["face"]), float(lad["bottom"][1]))
            if r != "ok":
                return f"사다리 {r}"
            r = self.f.walk_to(tuple(self.R["burg_bonfire"]), self.nm, "성벽 마을 화톳불로")
            self.log(f"   성벽 마을 화톳불로: {r}")
            if r == "dead" or not self.f.alive():
                return "died"
            return "arrived" if r in ("arrived", "done") else f"화톳불 {r}"
        finally:
            self.f.ignore_npcs = set()
            self.f.walk_heal = True
            self.pad.sprint(False)
            self.pad.neutral()

    def _ladder_down(self, top, face, bottom_y: float) -> str:
        """Demo 285.9 s: at the top facing the ladder (heading −2.63), A → 7020 gets on → 7005 / 7001 slide → 7002 at the bottom in 2 s.
        Stick down only once a ladder anim (7000–7099) shows — 첫 시험(153818)은 A가 안 먹힌 채 스틱 아래(= 뒤로 걷기)로
        사다리 구멍에 떨어짐 (10.1 m, −143), 턱 되돌림도 입구를 턱으로 읽고 끌어당김 → 사다리 동안 둘 다 끔."""
        esc = self.f.esc
        saved = (getattr(esc, "nudge_ok", True), getattr(esc, "planned", None))
        try:
            esc.nudge_ok, esc.planned = False, "사다리 내려가기"
            return self._ladder_down_(top, face, bottom_y)
        finally:
            esc.nudge_ok, esc.planned = saved
            self.pad.neutral()

    def _on_ladder(self) -> bool:
        s = self.mv.snap(5.0)
        return s is not None and s.player.anim is not None and 7000 <= s.player.anim < 7100

    def _ladder_down_(self, top, face, bottom_y: float) -> str:
        self.f._settle(top, tol=0.4)
        for attempt in range(LADDER_TRIES):
            s = self.mv.snap(5.0)
            if s is not None and s.cam_yaw is not None:
                self.pad.move(*self.mv.stick_to(s, face[0], face[2], 0.35))
                time.sleep(0.25)
                self.pad.move(0.0, 0.0)
                time.sleep(0.2)
            self.pad.interact()
            t1 = time.time()
            while time.time() - t1 < 1.5 and not self._on_ladder():
                time.sleep(0.05)
            if not self._on_ladder():
                s = self.mv.snap(5.0)
                self.log(f"   사다리: A 뒤 안 탐 ({attempt + 1}/{LADDER_TRIES}, 애니 {None if s is None else s.player.anim})")
                self.f._settle(top, tol=0.4)
                continue
            t0 = time.time()
            while time.time() - t0 < LADDER_DOWN_S:
                self.pad.move(0.0, -1.0)                    # stick down = climb down
                time.sleep(0.1)
                s = self.mv.snap(5.0)
                if s is not None and s.player.y <= bottom_y + 0.5:
                    break
            self.pad.neutral()
            time.sleep(0.8)
            s = self.mv.snap(5.0)
            if s is not None and s.player.y <= bottom_y + 0.6:
                self.log(f"   사다리 내려감 (y {s.player.y:.1f})")
                self.events("altar", what="ladder_down", ok=True, tries=attempt + 1)
                return "ok"
            self.log(f"   사다리 안 내려감 ({attempt + 1}/{LADDER_TRIES}, y {None if s is None else round(s.player.y, 1)})")
            if s is not None and s.player.y < top[1] - 1.0:
                return "stuck"                              # on the ladder but not down — don't walk off it
            self.f._settle(top, tol=0.4)
        self.events("altar", what="ladder_down", ok=False)
        return "fail"

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
