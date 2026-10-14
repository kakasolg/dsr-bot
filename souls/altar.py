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
import os
import time

from . import moves as M

DRAKE = 343000
ROUTE = "altar-demo-20261012.json"
CLAYMORE_FLAG = 51010210
BRIDGE_FOES = {255040}                # the two hollows on the bridge — MoKa ran past them 0.85 m away
BRIDGE_ALL = {255040, 255041, 255042}   # bridge / under-bridge hollows — dashes past ③ don't stop for them (MoKa demo 2: passed at 6–7 m)

# ── 임시값 (시연 한 번에서 잰 값) ──────────────────────────────
#  · 착지: 다리 위 (8.9, 9.5, −48.0) — y 12 밑, z −38 ~ −58이면 '앉음'
#  · ③ 대기: 시연 18 s 뒤 착지. [MoKa] "몇십초 기다리면 내려옴", 안 내려올 수도 있음(조건 모름)
#    → 기다림 한도를 넘으면 지금은 그냥 감. MoKa 방법(사다리 → 성벽 마을 화톳불 휴식 → 다시 ③)은 다음 단계
#  · ④ 대기: 시연 도착 4.6 s 뒤 날아오름, 8.7 s 뒤 횃대 (20.6, 18.9, −29.0) — 횃대 = y 15 위
LAND_Y = 12.0
LAND_Z = (-58.0, -38.0)
PERCH_Y = 15.0
COVER_WAIT_S = 35.0     # landed after 19–21.5 s in 5 bot runs, MoKa waited ~17 s; not by then → run straight to the bonfire
COVER_FOE_R = 8.0        # at ③: an awake foe this close (same level) is fought before waiting on (10-13: bridge hollow lunged twice)
DRAKE_AWAY_WAIT_S = 30.0  # no landing: before leaving ③ for the shortcut, wait this long at most for the Hellkite to be away
REST_RETRIES = 2         # no landing at ③: shortcut → rest at the Burg bonfire → back to ③, at most this many times, then run straight
LADDER_A_R = 0.45         # ladder up: press A while walking in, this close to the bottom (demo 3: A at ~0.35 m)
LOW_WAIT_S = 15.0        # at ② (lower ledge): drink and wait until no awake foe is within LOW_CLEAR_R, at most this long
LOW_CLEAR_R = 10.0
COVER_HOME_R = 1.0       # at ③ with no foe close: further than this from the cover → walk back in
COVER_LEASH_R = 3.0      # at ③: a fight that takes us further than this from the cover is cut and taken back (breath line ~7 m off)
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
        # after burg-altar's zones 1–7, Field still holds zone 7's safe spot as tether / extra zone — not ours any more
        self.f.tether, self.f.extra_zones = None, ()
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
            self._settle_low()
            if not self.f.alive():
                return "died"
            if os.environ.get("ALTAR_TEST_REST") == "1" and not getattr(self, "_tested_rest", False):
                # practice the shortcut the way MoKa demo 3 did it: from ② straight to the ladder (never back up through the breath line)
                self._tested_rest = True
                rr = self._rest_and_return(from_cover=False)
                self.log(f"   (시험) ②에서 숏컷 쉬고 돌아오기: {rr}")
                if rr == "died":
                    return "died"
                if rr != "ok":
                    return f"숏컷 {rr}"
            r = self.f.walk_to(tuple(m["3_stairs_cover"]), self.nm, "② → ③ 엄폐 자리")
            self.log(f"   ② → ③: {r}")
            if r == "dead" or not self.f.alive():
                return "died"
            r = self._wait_landing()
            if r == "died":
                return r
            for k in range(REST_RETRIES):
                if r != "timeout":
                    break
                # ── 안 내려오면 밑의 길 → 숏컷(사다리) → 성안 화톳불에서 쉬고 → 다시 ③ ([MoKa] 2026-10-13 시연 3) ──
                #  "카라미트가 다리에 있는 병사들을 태워 버려야 하는데, 않나타나면 오히려 꼬여" · "밑에 있는 길로 가서 숏컷으로 해서 성안 화톳불 가서 쉬어야 해"
                #  시연 3 (data/observe/20261013_172318.jsonl): ② 아래층 → 서쪽 (−1.8, 4.5, −56.7) → 사다리 위 → 내려감 → 화톳불 쉼 →
                #  사다리 올라옴 (7010–7013) → 아래층 → 계단 → ③ → 21.8 s 뒤 착지
                self.log(f"   ③ 헬카이트 안 내려옴 — 숏컷으로 성안 화톳불 가서 쉬고 다시 ③ ({k + 1}/{REST_RETRIES})")
                rr = self._rest_and_return()
                self.log(f"   숏컷 쉬고 돌아오기: {rr}")
                if rr == "died":
                    return "died"
                if rr != "ok":
                    return f"숏컷 {rr}"            # stuck below / at the ladder — no straight run from there (10-13: no_path from the bonfire level)
                r = self._wait_landing()
                if r == "died":
                    return r
            if r == "timeout":
                self.log("   ③ 헬카이트 계속 안 내려옴 — 화톳불로 바로 달림")
                r = self._leg(self.R["sprint_3_to_4"], "③ → ④ (안 내려옴, 질주)", "sprint", BRIDGE_ALL)
                if r == "dead" or not self.f.alive():
                    return "died"
                return self._to_bonfire(BRIDGE_ALL)
            r = self._leg(self.R["sprint_3_to_4"], "③ → ④ 테라스 (질주)", "sprint", BRIDGE_ALL)
            if r == "dead" or not self.f.alive():
                return "died"
            self._wait_away()
            r = self._claymore()
            if r == "died":
                return r
            return self._to_bonfire()
        finally:
            self.f.ignore_npcs = set()
            self.pad.sprint(False)
            self.pad.neutral()

    def _rest_and_return(self, from_cover: bool = True) -> str:
        """③ (or ②) → ② lower ledge → ladder top → down → rest at the Undead Burg bonfire → up the ladder → ③.
        From ③ only once the Hellkite is away (perch / off the bridge): 10-13 practice 2 left ③ while it still flew over and the
        stair top (breath line) cost −975 → dead. → 'ok' | 'died' | '<step> <result>'"""
        from .missions import SPOTS
        m, lad = self.R["markers"], self.R["ladder_shortcut"]
        self.f.ignore_npcs = {DRAKE} | BRIDGE_ALL
        try:
            if from_cover:
                t0 = time.time()
                while time.time() - t0 < DRAKE_AWAY_WAIT_S and not away(self.mv.snap(80.0)):
                    if not self.f.alive():
                        return "died"
                    self.mv.guard(True)
                    time.sleep(0.2)
                self.mv.guard(False)
                self.log(f"   ③ 떠나기 전 헬카이트 {'떠남' if away(self.mv.snap(80.0)) else '아직 다리 위/근처'} ({time.time() - t0:.1f} s)")
            legs = ((m["2_stairs_bottom"], "③ → ② 아래층"), (lad["top"], "사다리 위로")) if from_cover else ((lad["top"], "② → 사다리 위로"),)
            for goal, tag in legs:
                r = self.f.walk_to(tuple(goal), self.nm, tag)
                if r == "dead" or not self.f.alive():
                    return "died"
                if r not in ("arrived", "done"):
                    return f"{tag} {r}"
            r = self._ladder_down(tuple(lad["top"]), tuple(lad["face"]), float(lad["bottom"][1]))
            if r != "ok":
                return f"사다리 내려가기 {r}"
            ok = self.f.rest_at(self.nm, SPOTS["burg-bonfire"])
            self.log(f"   성안 화톳불 휴식: {'됨' if ok else '안 됨'}")
            if not self.f.alive():
                return "died"
            r = self._ladder_up(tuple(lad["bottom"]), tuple(lad["top"]), tuple(lad["up_from"]), tuple(lad["up_face"]))
            if r != "ok":
                return f"사다리 올라가기 {r}"
            r = self.f.walk_to(tuple(m["3_stairs_cover"]), self.nm, "사다리 위 → ③")
            if r == "dead" or not self.f.alive():
                return "died"
            return "ok" if r in ("arrived", "done") else f"③ {r}"
        finally:
            self.f.ignore_npcs = {DRAKE}
            self.pad.neutral()

    def _ladder_up(self, bottom, top, up_from=None, up_face=None) -> str:
        """Demo 3 202.9 s: walking west into the ladder bottom (−2.9, −10.0, −62.6) → 7010 → 7011/7012 climbing → 7013 at the top →
        steps off by itself at (−3.4, −0.3, −63.5). On the ladder the body faces the top's x/z (heading 0.51). Stick up only on a ladder anim."""
        esc = self.f.esc
        saved = (getattr(esc, "nudge_ok", True), getattr(esc, "planned", None))
        try:
            esc.nudge_ok, esc.planned = False, "사다리 올라가기"
            # MoKa's spot and facing (route data up_from / up_face — demo 3: A at 0.3 m from the bottom facing heading 1.0);
            # 10-13 first try stood 0.6 m off facing the top's x/z (heading ~0.47) — A ×3, no ladder anim
            if up_from is None:
                dx, dz = bottom[0] - top[0], bottom[2] - top[2]
                n = math.hypot(dx, dz) or 1.0
                up_from = (bottom[0] + dx / n * 0.6, bottom[1], bottom[2] + dz / n * 0.6)
            # walk in and press A on the move, like MoKa (A at ~0.35 m from the bottom while still walking) — standing still
            # 0.4–2.3 m off with heading 1.33 got no ladder 3/3 (practice 3: _settle stopped short, the turn pulse didn't turn)
            back = (up_from[0] - (bottom[0] - up_from[0]) * 4.0, up_from[1], up_from[2] - (bottom[2] - up_from[2]) * 4.0)
            for attempt in range(LADDER_TRIES):
                self.f._settle(back, tol=0.5)                         # ~1.5 m back on MoKa's line
                t1 = time.time()
                pressed = False
                while time.time() - t1 < 4.0 and not self._on_ladder():
                    s = self.mv.snap(5.0)
                    if s is None or s.cam_yaw is None:
                        time.sleep(0.03)
                        continue
                    d = math.hypot(bottom[0] - s.player.x, bottom[2] - s.player.z)
                    self.pad.move(*self.mv.stick_to(s, bottom[0], bottom[2], 0.5))
                    if d < LADDER_A_R and not pressed:
                        self.pad.interact()
                        pressed = True
                    elif pressed and d < 0.15:
                        break
                    time.sleep(0.03)
                self.pad.move(0.0, 0.0)
                t1 = time.time()
                while time.time() - t1 < 1.0 and not self._on_ladder():
                    time.sleep(0.05)
                if not self._on_ladder():
                    s = self.mv.snap(5.0)
                    self.log(f"   사다리 (올라가기): A 뒤 안 탐 ({attempt + 1}/{LADDER_TRIES}, 애니 {None if s is None else s.player.anim})")
                    continue
                t0 = time.time()
                while time.time() - t0 < LADDER_DOWN_S:
                    self.pad.move(0.0, 1.0)                 # stick up = climb up
                    time.sleep(0.1)
                    s = self.mv.snap(5.0)
                    if s is not None and s.player.y >= top[1] - 0.4 and not self._on_ladder():
                        break
                self.pad.neutral()
                time.sleep(0.6)
                s = self.mv.snap(5.0)
                if s is not None and s.player.y >= top[1] - 0.6:
                    self.log(f"   사다리 올라감 (y {s.player.y:.1f})")
                    self.events("altar", what="ladder_up", ok=True, tries=attempt + 1)
                    return "ok"
                self.log(f"   사다리 안 올라감 ({attempt + 1}/{LADDER_TRIES}, y {None if s is None else round(s.player.y, 1)})")
                if s is not None and s.player.y > bottom[1] + 1.0:
                    return "stuck"
            self.events("altar", what="ladder_up", ok=False)
            return "fail"
        finally:
            esc.nudge_ok, esc.planned = saved
            self.pad.neutral()

    def _to_bonfire(self, ignore: set = frozenset()) -> str:
        self.f.ignore_npcs = {DRAKE} | set(ignore)
        r = self.f.walk_to(tuple(self.R["altar_bonfire"]), self.nm, "제단 화톳불로", mode="sprint" if ignore else "walk")
        self.log(f"   제단 화톳불로: {r}")
        if r == "dead" or not self.f.alive():
            return "died"
        return "arrived" if r in ("arrived", "done") else f"화톳불 {r}"

    def _settle_low(self) -> None:
        """
        ── ② 아래층에서 마시고, 쫓아오던 망자가 떨어질 때까지 ([MoKa] 시연 2, 2026-10-13) ──────────────────
         · 시연: 첫 브레스(−183) 뒤 굴러 ② 아래층(y 4.5)으로 → 에스트 403 → 742 → ~10 s 뒤 ③로. 다리 망자 255040 · 255041은 ③에 안 옴
         · 봇(5번 중 3번 사망): ②에 닿자마자 ③로 올라가 마심 → 다리 망자가 ③까지 따라와 돌진 (P-85)
         · 여기서 HP 90 %까지 마시고(3 m 안 적 없을 때), 10 m 안 깨어 있는 적이 없어질 때까지 최대 LOW_WAIT_S 가드 든 채 기다림.
           붙는 적은 여기서 싸움 (아래층은 브레스 줄 밖)
        """
        t0 = time.time()
        while time.time() - t0 < LOW_WAIT_S and self.f.alive():
            s = self.mv.snap(30.0)
            if s is None:
                break
            p = s.player
            awake = [c for c in s.hostile(LOW_CLEAR_R + 2.0) if c.npc_param != DRAKE and c.hp > 0 and c.anim not in (None, -1)
                     and not (9000 <= (c.anim or 0) < 9100) and M.horiz(p, c) < LOW_CLEAR_R]
            close = [c for c in awake if M.horiz(p, c) < 3.0 and abs(c.y - p.y) < 2.5]
            if close:
                d = self.f.fight(close[0].ptr, self.nm, f"② 아래층 {close[0].npc_param}", wait_far=True)
                self.log(f"   ② 아래층 {close[0].npc_param}: {d.result}")
                continue
            if p.hp < p.max_hp * 0.9 and self.f.estus_left() > 0 and self.f.safe(s):
                self.f.heal(0.9, sips=3)
                continue
            if not awake and p.hp >= p.max_hp * 0.9:
                break
            self.mv.guard(True)
            time.sleep(0.2)
        self.mv.guard(False)
        s = self.mv.snap(5.0)
        self.log(f"   ② 아래층 {time.time() - t0:.1f} s — HP {s.player.hp if s else '?'}")

    def _wait_landing(self) -> str:
        """At ③: wait for it to land on the bridge. Not within COVER_WAIT_S → 'timeout'.
        ALTAR_TEST_REST=1 (env): the first wait gives up after 1 s — to try the shortcut-rest fallback without a real no-landing."""
        t0 = time.time()
        seen = False
        limit = COVER_WAIT_S
        while time.time() - t0 < limit:
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
            self._back_to_cover()                  # drifted out (a fight, a push) — the breath line starts a few metres away
            if landed(s):
                self.log(f"   ③ 헬카이트 착지 {time.time() - t0:.1f} s: {self._where(s)}")
                self.events("altar", what="landed", wait=round(time.time() - t0, 1))
                return "landed"
            time.sleep(0.1)
        self.log(f"   ③ {limit:.0f} s 안에 착지 안 함 ({'보였음' if seen else '한 번도 안 보임'}) — 그냥 감")
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
        """
        ── ③는 엄폐 자리 — 싸워도 거기서 ([MoKa] 2026-10-13 "안전 자리 있어야 하는데 굳이 나와서 화염을 맞고 있네") ──────────
         · 4번째: ③ 싸움이 망자를 쫓아 (2.0, −65.7) 쪽으로 붙으러 나가 공격자 없는 −170(브레스). 5번째: 엄폐 밖 핏자국 줍기 → 브레스 −742
         · 싸움은 ③에서 COVER_LEASH_R 넘게 벗어나면 그 틱에 끊고(leash) 가드 든 채 ③로 돌아와 다시 받음(wait_far — 멀면 안 나감)
         · HP 낮음: Field.recover는 쓰지 않음 — escape.pick이 '온 길'(엄폐 밖, 브레스 줄)로 물러남. 3 m 안에 적이 없으면 ③에서 마시고,
           있으면 ③에서 계속 싸움(desperate). P-47(마시지 않고 0 s 싸움 반복)도 이렇게 피함
        """
        cover = tuple(self.R["markers"]["3_stairs_cover"])
        tag = f"③ 기다리다 {c.npc_param}"

        def off_cover() -> bool:
            s = self.mv.snap(5.0)
            return s is not None and math.hypot(s.player.x - cover[0], s.player.z - cover[2]) > COVER_LEASH_R

        desperate = False
        self.f.tether, self.f.extra_zones = cover, (cover,)   # Field.fight's tether / retreat home = the cover, not a zone spot
        for _ in range(6):
            if not self.f.alive():
                return "died"
            d = self.f.fight(c.ptr, self.nm, tag, desperate=desperate, wait_far=True, leash=off_cover)
            self.log(f"   {tag}: {d.result}")
            if d.result == "me_dead" or not self.f.alive():
                return "died"
            t = self.mv.find(self.mv.snap(80.0), c.ptr)
            if d.result == "killed" or t is None or t.hp <= 0:
                # back into cover after a kill too — 10-13 chain 183926: killed it 3.7 m out, stood there 12 s in the breath line
                # (−170 every ~3 s, the Hellkite out of reading range) → dead
                self._back_to_cover(cover)
                return "killed"
            if off_cover():
                r = self.f.walk_to(cover, self.nm, "③ 엄폐로 돌아옴", tol=0.6)
                self.log(f"   {tag}: ③ 밖으로 밀림 — 엄폐로: {r}")
            s = self.mv.snap(10.0)
            if s is not None and s.player.hp < s.player.max_hp * 0.6:
                near = [x for x in s.hostile(4.0) if x.hp > 0 and M.horiz(s.player, x) < 3.0]
                if not near and self.f.estus_left() > 0:
                    self.f.heal(0.9, sips=3)
                    desperate = False
                else:
                    desperate = True
        return "left"

    def _back_to_cover(self, cover=None) -> None:
        cover = cover or tuple(self.R["markers"]["3_stairs_cover"])
        s = self.mv.snap(5.0)
        if s is not None and math.hypot(s.player.x - cover[0], s.player.z - cover[2]) > COVER_HOME_R:
            r = self.f.walk_to(cover, self.nm, "③ 엄폐로", tol=0.6)
            self.log(f"   ③ 엄폐로 돌아옴: {r}")

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
