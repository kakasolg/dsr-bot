"""Taurus Demon (225000) from the save point in front of its fog wall (MoKa 2026-10-06 plan, 2026-10-11 "여기서만 집중적으로").

  python run.py taurus --radar          after `python savepoint.py restore backup-20261011-235526-zone8-top-taurus-start`

Order (MoKa's 3rd recording 20261006_173431, 417.9–486.5 s, and the plan in problems.md P-47):
  fog wall → bridge F9#7 (the boss jumps down at the far end) → run back east to the ladder, climb → two hands + Gold Pine
  Resin at the top → plunge when it stands within PLUNGE_R below (recording: 3.8 m, −411) → stay right up against it and
  light-attack while stamina allows (recording: 0.3–1.9 m from its center, in front, −91 each; the two −237 hits came when
  stamina had gone below 0) → Estus when low and it isn't swinging.
"""
from __future__ import annotations

import math
import time

import control
import nav

from . import moves as M

TAURUS = 225000
RESIN = 311                         # Gold Pine Resin (goods id; MoKa put it in a quick slot 2026-10-11)
TWO_HAND = 3
FOG = {"front": (52.07, 17.21, -118.55), "beyond": (49.62, 16.79, -118.74)}   # data/burg-upper-map.json zone 8
TRIGGER = (22.9, 15.9, -120.9)      # bridge spot that calls the boss (MoKa F9#7)
BRIDGE_Y = 22.0                     # it waits on the tower top (−6.7, 27.0, −110.4, anim 9001) until called; the bridge is y ~15.8
LADDER = {"bottom": (49.16, 15.97, -117.1), "face": (50.5, 15.97, -117.1), "top_y": 24.5,
          "approach": [(46.0, 15.83, -118.31), (47.31, 15.91, -117.51), (48.94, 15.96, -117.2), (49.16, 15.97, -117.1)]}

# ── 임시값 (녹화 한 번에서 잰 값 — 시도마다 다시 볼 것) ──────────────────────────────
#  · 낙하: 꼭대기에서 보스가 수평 3.8 m일 때 뛰어 −411. 5.0 m 안이면 감
#  · 붙기: 약공한 자리 0.3~1.9 m(보스 중심) — HIT_R 2.2 안이면 침, 밖이면 1.2 m까지 다가감
#  · 스태미나: 양손 약공 한 번 ~38 — 40 밑이면 안 치고 붙은 채 회복 (0 밑으로 간 뒤 −237 두 번)
#  · 에스트: HP 40 % 밑, 보스가 공격 애니가 아닐 때 (녹화: 가까이서도 마심)
APPEAR_S = 20.0
PLUNGE_R = 5.0
PLUNGE_WAIT_S = 30.0
HIT_R = 2.2
STICK_R = 1.2
HIT_SP = 40
HIT_SP2 = 80                        # two in a row only from here (two cost ~76)
ESTUS_HP = 0.40
FIGHT_LIMIT = 150.0


class Taurus:
    def __init__(self, field, nm, missions, log=print, events=lambda *a, **k: None):
        self.f, self.mv, self.nm, self.ms = field, field.mv, nm, missions
        self.tm, self.pad = field.mv.tm, field.mv.pad
        self.log, self.events = log, events

    @staticmethod
    def boss(s):
        return None if s is None else next((c for c in s.chars if c.npc_param == TAURUS and c.hp > 0), None)

    @classmethod
    def awake(cls, s) -> bool:
        """It has jumped down from its perch or started moving. On the perch it reads y 27.0, anim 9001 (a dormant pose) —
        tries 1–2 (2026-10-12) took 'present' / 'y below 27.3' for called and ran straight to the ladder; it never came."""
        b = cls.boss(s)
        a = b.anim if b is not None and b.anim is not None else -1
        return b is not None and (b.y < BRIDGE_Y or (a != -1 and not 9000 <= a < 9100))

    def run(self) -> str:
        """→ 'killed' | 'died' | 'no_estus' | '<step> fail' …"""
        if not self.f.alive():
            return "died"
        if self.mv.estus_left() < 1:                       # [MoKa] 10-06: "에스트는 1개만 있으면 될 것 같아"
            return "no_estus"
        if (self.tm.goods_count(RESIN) or 0) < 1:
            self.log("   타우로스: 황금 송진 없음 — 송진 없이 감")
        self.f.ignore_npcs = {TAURUS}                      # walks don't stop to duel it — we run to the ladder
        esc = self.f.esc
        saved = (esc.quit_ok, getattr(esc, "nudge_ok", True))
        try:
            r = self.ms._before({"fog": {"front": list(FOG["front"]), "beyond": list(FOG["beyond"])}}, self.nm, "타우로스")
            if r != "ok":
                return "died" if r == "dead" else f"안개벽 {r}"
            # two hands and the resin here, before calling it — try 3 (2026-10-12): at the ladder top the two-hand toggle's RB
            # went out as a light attack (304000), its step carried us off the narrow top and we fell among its feet
            self._two_hand()
            self._resin()
            r = self._call()
            if r != "ok":
                return r
            r = self.ms._before({"ladder": {k: (list(v) if isinstance(v, tuple) else v) for k, v in LADDER.items()}},
                                self.nm, "타우로스")
            if r == "dead":
                return "died"
            if r != "ok":
                self.log(f"   타우로스: 사다리 {r} — 그 자리에서 싸움")
                esc.nudge_ok = False
                return self._fight()
            esc.quit_ok, esc.nudge_ok = False, False      # top of the ladder and the drop: no fall quit-out / ledge pull-back
            r = self._plunge()
            esc.quit_ok = saved[0]                         # the ledge pull-back stays off: try 4 it fired twice on landing
            if r == "died":
                return r
            return self._fight()                           # plunge done, missed or knocked off the top — it's on us either way
        finally:
            esc.quit_ok, esc.nudge_ok = saved
            self.f.ignore_npcs = set()
            self.f.grip_want = None
            self.pad.sprint(False)
            self.pad.neutral()

    def _call(self) -> str:
        """Walk onto the bridge until the boss shows up (it jumps down at the far end), then run back to the ladder."""
        s = self.mv.snap(80.0)
        if not self.awake(s):
            r = self.f.walk_to(TRIGGER, self.nm, "타우로스 다리", done=lambda sn: self.awake(self.mv.snap(80.0)))
            if r == "dead" or not self.f.alive():
                return "died"
            t0 = time.time()
            while not self.awake(self.mv.snap(80.0)) and time.time() - t0 < APPEAR_S:
                time.sleep(0.2)
        s = self.mv.snap(80.0)
        b = self.boss(s)
        if not self.awake(s):
            self.log(f"   타우로스: {APPEAR_S:.0f} s 안에 안 나옴")
            return "안 나옴"
        self.log(f"   타우로스 나옴: HP {b.hp}, {M.horiz(s.player, b):.1f} m — 사다리로")
        self.events("taurus", what="appear", hp=b.hp, d=round(M.horiz(s.player, b), 1))
        r = self.f.walk_to(LADDER["approach"][0], self.nm, "타우로스 사다리로", mode="sprint")
        if r == "dead" or not self.f.alive():
            return "died"
        return "ok"

    def _two_hand(self) -> None:
        self.f.grip_want = TWO_HAND
        for _ in range(3):
            if self.tm.grip() == TWO_HAND:
                break
            self.pad.two_hand_right()
            time.sleep(0.5)
        self.log(f"   타우로스: 양손 grip {self.tm.grip()}")

    def _resin(self) -> None:
        """Select the resin, X, wait for the rub (~2 s); again once if the count didn't drop. Try 4 (2026-10-12): pressed right
        after the two-hand switch, the X was eaten (3 → 3)."""
        time.sleep(1.0)
        self.resin_t = None
        for k in range(2):
            n0 = self.tm.goods_count(RESIN) or 0
            if n0 < 1:
                return
            if not self.mv.select_item(RESIN):
                self.log("   타우로스: 송진 칸을 못 고름")
                return
            self.pad.neutral()
            self.pad.use_item()
            t0 = time.time()
            while time.time() - t0 < 2.6:                  # rubbing the resin on takes ~2 s
                self.pad.release_due()
                time.sleep(0.02)
            n1 = self.tm.goods_count(RESIN) or 0
            self.log(f"   타우로스: 황금 송진 {'바름' if n1 < n0 else '안 발라짐'} ({n0} → {n1})")
            if n1 < n0:
                self.resin_t = time.time()
                break
        self.events("taurus", what="resin", ok=self.resin_t is not None)
        e = self.mv.estus_id()
        if e is not None:
            self.mv.select_item(e)                         # back to Estus for the fight

    def _plunge(self) -> str:
        """Wait at the top until it stands within PLUNGE_R below, then run off toward it and R1 while falling (souls/asylum._plunge)."""
        t0 = time.time()
        while time.time() - t0 < PLUNGE_WAIT_S:
            s = self.mv.snap(40.0)
            b = self.boss(s)
            if s is not None and b is not None and M.horiz(s.player, b) <= PLUNGE_R and s.player.y - b.y > 5.0:
                break
            if not self.f.alive():
                return "died"
            if s is not None and s.player.y < LADDER["top_y"] - 1.5:
                self.log(f"   타우로스: 꼭대기에서 떨어짐 (y {s.player.y:.1f}) — 바로 싸움")
                return "off_top"
            time.sleep(0.05)
        else:
            self.log(f"   타우로스: {PLUNGE_WAIT_S:.0f} s 동안 사다리 밑으로 안 옴")
            return "낙하 안 함"
        s = self.mv.snap(40.0)
        b = self.boss(s)
        y0, hp0 = s.player.y, b.hp
        rt = getattr(self, "resin_t", None)
        self.log(f"   타우로스 낙하: {M.horiz(s.player, b):.1f} m, 높이 {s.player.y - b.y:.1f} m, 그놈 애니 {b.anim}"
                 f"{'' if rt is None else f', 송진 {time.time() - rt:.0f} s 전'}")
        pressed_t, last_rb, t1 = None, 0.0, time.time()
        try:
            self.pad.sprint(True)
            while time.time() - t1 < 6.0:
                s = self.mv.snap(40.0)
                if s is None:
                    time.sleep(0.03)
                    continue
                b = self.boss(s) or b
                if s.cam_yaw is not None:
                    self.pad.move(*self.mv.stick_to(s, b.x, b.z, 1.0))
                falling = s.player.anim in (1500, 1550) or s.player.y < y0 - 1.0
                if falling and s.player.y > y0 - 8.0 and time.time() - last_rb > 0.15:
                    self.pad.sprint(False)
                    self.mv.press(control.B.XUSB_GAMEPAD_RIGHT_SHOULDER, hold=0.06, gap=0.0)
                    last_rb = time.time()
                    pressed_t = pressed_t or time.time()
                    continue
                if pressed_t and time.time() - pressed_t > 1.5 and s.player.y < y0 - 6.0:
                    break
                time.sleep(0.02)
        finally:
            self.pad.sprint(False)
            self.pad.neutral()
        time.sleep(0.3)
        s = self.mv.snap(40.0)
        b2 = self.boss(s)
        landed = s is not None and s.player.y < y0 - 6.0
        self.log(f"   타우로스 낙하 공격: HP {hp0} → {b2.hp if b2 else 0}, 내 HP {None if s is None else s.player.hp}"
                 f"{'' if landed else ' — 안 떨어짐'}")
        self.events("taurus", what="plunge", boss_hp=[hp0, b2.hp if b2 else 0], landed=landed)
        return "ok" if landed else "낙하 실패"

    def _fight(self) -> str:
        """Stay right up against it ([MoKa] "바짝 붙어서 공격"): within HIT_R and stamina ≥ HIT_SP → one light; else step in to
        STICK_R (floor-checked) and let stamina come back. HP < ESTUS_HP and it isn't swinging → Estus."""
        t0, hits = time.time(), 0
        # no guard: two-handed, LB is a weapon block — try 4 (2026-10-12) light() held it after each swing, the axe soaked
        # its hits (stamina 98 → 9), stamina came back slowly with LB down, and only 1 of 4 lights landed
        guard_ok, self.mv.guard_ok = getattr(self.mv, "guard_ok", True), False
        self.pad.guard(False)
        try:
            return self._fight_loop(t0, hits)
        finally:
            self.mv.guard_ok = guard_ok

    def _fight_loop(self, t0: float, hits: int) -> str:
        while time.time() - t0 < FIGHT_LIMIT:
            if not self.f.alive():
                self.log(f"   타우로스 싸움: 사망 — {time.time() - t0:.0f} s, 약공 {hits}번")
                return "died"
            s = self.mv.snap(40.0)
            if s is None:
                time.sleep(0.05)
                continue
            b = self.boss(s)
            if b is None:
                self.log(f"   타우로스 처치 — {time.time() - t0:.0f} s, 약공 {hits}번, 내 HP {s.player.hp}")
                self.events("taurus", what="killed", secs=round(time.time() - t0, 1), hits=hits, hp=s.player.hp)
                return "killed"
            p = s.player
            h = M.horiz(p, b)
            a = b.anim if b.anim is not None else -1
            if p.hp < p.max_hp * ESTUS_HP and a not in M.ATTACK and self.mv.estus_left() > 0:
                self.pad.neutral()
                r = self.mv.drink(lambda sn: (self.boss(sn) is None or (self.boss(sn).anim or -1) not in M.ATTACK))
                self.log(f"   타우로스 싸움 중 에스트: {r}")
                self.events("estus", **r)
                continue
            if h <= HIT_R and (p.sp or 0) >= HIT_SP:
                if self.mv.face(s, b, deg=30.0):
                    n = 2 if (p.sp or 0) >= HIT_SP2 else 1     # recording: MoKa chained them while stamina lasted
                    hit = self.mv.light(s, b, n=n, sp_second=HIT_SP)
                    hits += n
                    self.events("taurus", what="hit", dmg=hit.dmg, taken=hit.taken, h=round(h, 2), anim=a, sp=p.sp)
                continue
            if h > STICK_R and s.cam_yaw is not None:
                way = nav.safe_heading(self.nm, p, b.x - p.x, b.z - p.z, reach=min(1.2, max(0.4, h - 0.3)))
                if way is None:
                    self.pad.move(0.0, 0.0)
                else:
                    self.pad.move(*self.mv.stick_to(s, p.x + way[0], p.z + way[1], 1.0 if h > 4.0 else 0.6))
            else:
                self.pad.move(0.0, 0.0)
            time.sleep(0.05)
        self.log(f"   타우로스 싸움: {FIGHT_LIMIT:.0f} s 넘음, 약공 {hits}번")
        return "timeout"
