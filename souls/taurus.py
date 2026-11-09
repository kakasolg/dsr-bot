"""Taurus Demon (225000) from the save point in front of its fog wall (MoKa 2026-10-06 plan, 2026-10-11 "여기서만 집중적으로").

  python run.py taurus --radar          after `python savepoint.py restore backup-20261011-235526-zone8-top-taurus-start`

Order (MoKa's 3rd recording 20261006_173431, 417.9–486.5 s, and the plan in problems.md P-47):
  fog wall → two hands + Gold Pine Resin → bridge F9#7 (the boss jumps down at the far end) → run back east to the ladder,
  climb → plunge when it stands within PLUNGE_R below (recording: 3.8 m, −411).
Then the plunge loop ([MoKa] 2026-10-12, a YouTube guide: "낙하 공격 루프만 유지하는 것이 안정적" — no stand-up fight on the
narrow wall, knock-back off the sides): one light while it reels → back to the ladder (roll toward it when it starts a
swing close by) → climb → Estus only up there, only when low → plunge again as soon as it stands below. 2–3 rounds.
Every one of its attacks is written as a `taurus` what=attack event (AttackLog) — where we stood and whether it hit —
for `taurus_report.py` ([MoKa] "이런 경우는 피해진다 / 반드시 피격 당한다는 데이타를 쌓아야 해").
"""
from __future__ import annotations

import math
import threading
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
#  · 붙기: 녹화에서 약공한 자리 0.3~1.9 m(보스 중심, 대부분 1.3 m 안). 10-12 시도 5~8: HIT_R 2.2였을 때 휘두름 19번 중
#    피해 0이 12번 — 거의 다 2.05~2.16 m에서 보스 공격(3002~3005) 중에 침. 1.4 m / 0.8 m로 좁혀 본 시도 9~11은 0/3
#    (2.2 m일 때 5~8은 2/4) → 거리만으로는 안 갈림, 2.2 / 1.2로 되돌림. 다음은 보스 공격 중 어디 서 있나(MoKa에게 물음)
#  · 11-03 MoKa (try 21 클립을 보고): "나는 보스 발 사이에서 공격하는데, 봇은 보스의 앞쪽에서 공격하는 것이 차이"
#    try 21: 붙어서 34 s, 약공 8번, 맞은 곳 1.2~2.0 m 정면 ±15° → 사망. 지난 런 약공 75번 거리 중앙값 2.09 m (최소 0.92).
#    보스 공격 기록 h_min 0.04 m도 있으니 발 사이(중심 ~0.7 m 안)까지 들어갈 수 있음 → 거기 들어가서만 친다.
#    시도 9~11의 0.8 m(0/3)는 낙하 여러 번·사다리 왕복 때라 지금 계획(낙하 1번 + 다리 위 싸움)과 다름
#  · 11-03 try 22 (HIT_R 0.7): 0.5~0.7 m까지 들어갔지만 보스 기준 앞 0.5~0.7 · 옆 0.0 (중앙선) → 3006 · 3000 연속 −244 → 12 s 만에 사망.
#    MoKa 직접 (taurus_watch 20261103_064407, 양손 도끼·송진 없음, 처치·받은 피해 191): "나는 보스 가랑이 사이에서 공격 한거야"
#    붙어서 친 자리 앞 0.2~1.0 · 옆 0.5~0.8 m (중앙선에서 비켜난 다리 안쪽). 기록 한 번뿐 — SPOT_* 값은 이 한 번에서 잼
#  · 스태미나: 양손 약공 한 번 ~38 — 40 밑이면 안 치고 붙은 채 회복 (0 밑으로 간 뒤 −237 두 번)
#  · 에스트: HP 40 % 밑, 보스가 공격 애니가 아닐 때 (녹화: 가까이서도 마심)
APPEAR_S = 20.0
PLUNGE_R = 5.0
PLUNGE_WAIT_S = 30.0
# [MoKa] 11-09 "앞발에 붙어서 적의 무기 공격 범위에 들어 간거야" · "살짝 더 안쪽으로 들어가서 두 다리 사이에 있어야 하는데, 좌측 발이
#  앞쪽으로 뻗고 있었는데 거기에 있었는데" — 072235 track: 근접 시간 대부분 중심 앞 1~2 m · 옆 ~0 (앞발 = 무기 범위). 0.4/0.6 → 더 안쪽.
#  0.0/0.25 = 같은 런 53.8 s에 실제로 서 본 자리 (앞 +0.01 · 옆 +0.24) — 몸 충돌로 못 들어가는 자리는 아님
SPOT_FWD = 0.0                      # where we swing from, in its own frame: this far in front of its center …
SPOT_SIDE = 0.25                    # … and this far to one side (between its legs, off the club's center line)
SPOT_R = 0.45                       # swing only within this of that spot; else walk to it
HIT_SP = 40
# ── 양손 가드 들고 가랑이로 들어감 (P-141, [MoKa] 2026-11-08) ──────────────────────────────
#  "타우로스 공략할때 가까이 갈때도 양잡 상태로 가드 해도, 배틀액스로도 방패보다는 데미지가 더 들어오지만 가드 하면서 들어가서 공격하면,
#  한방에 죽지는 않을 거야. 문제는 가드를 하면 스테미나가 차지 않는게 문제" · "양잡 가드 하면서 다리 밑으로 들어가봐 … 다음 공격이 될지는 나도 모르겠네"
#  · 칠 때와 에스트 때만 가드를 내림. 자리에서 기력을 기다릴 때도 가드 (기력이 차는지가 이번 시험 질문 — 'hit' 이벤트에 sp)
#  · 예전 (10-12 시험 4): 약공 뒤마다 LB가 눌린 채라 무기로 막아 기력 98 → 9, 약공 4번 중 1번만 맞음 → 가드 끔. GUARD_CLOSE False면 그대로
GUARD_CLOSE = True
# ── 보스 공격 애니 (P-142 2차, 11-09 065619) ──────────────────────────────────────────────
#  M.ATTACK(3000–3499)만 보고 마시다 4100 · 4101 · 4106에 −244 · −277 · −244 → 사망. TAE c2250(data/gamefiles/tae.json)에
#  4000–4006 · 4100–4106도 3000–3006과 같은 시각의 공격 판정이 있음 (파일), 예전 런에서도 4100번대 피격 5번 (런타임).
BOSS_ATTACK = frozenset(range(3000, 3500)) | frozenset(range(4000, 4007)) | frozenset(range(4100, 4107))
HIT_SP2 = 80                        # two in a row only from here (two cost ~76)
ESTUS_HP = 0.40
SPOT_ATTACK_S = 0.5                 # [MoKa] 11-09 "다리에 붙으면 0.5초 내에 공격 들어가봐": on the spot this long → swing even below HIT_SP (stamina > 0)
SIP_SPOT_R = 0.8                    # P-142 (MoKa 11-09 "에스트를 마셔도 다리 사이에서"): sip only this close to crotch_spot — unmeasured
SIP_SPOT_WAIT = 4.0                 # … unless a sip window has been open this long without reaching it (never drinking = death) — unmeasured
# ── 두 대 맞으면 죽음 → 한 대 맞으면 마심 ([MoKa] 11-02 "연속 2대 맞으면 죽잖아" · "에스트 마시면서") ──
#  11-02 051424: 착지 562 → 3006 −242 = 320(46 %, ESTUS_HP 위라 안 마심) → 3005 −242 = 78 → 마시다 끊겨 사망, 보스 HP ~161 남음
TAURUS_HIT = 245                    # one hit seen 233–242 (10-12 3003 −233, 11-02 3006 / 3005 −242)
PRE_HEAL = 0.80                     # before calling it: drink up to this (save point start is 680/742 = 0.92)
FIGHT_LIMIT = 150.0
CYCLES = 5                          # plunge rounds before falling back to the close fight (only when PLUNGES > 1)
PLUNGES = 1                         # plunges in all; after the last one, the close fight on the bridge (MoKa 11-02)
PUNISH_R = 2.6                      # after landing: one light if it's this close
BACK_S = 10.0                       # longest run back to the ladder
DODGE_R = 4.5                       # on the way back: roll toward the ladder when it starts a swing this close
HIT_AT = {3000: 1.45, 3002: 1.41, 3003: 1.99, 3004: 1.85, 3005: 1.51, 3006: 1.55}   # anim time (s) of its first hit, see ROLL_LEAD
ROLL_LEAD = 0.33                    # B this long before the hit: roll i-frames ~0.1–0.37 s after B (boss/boss.py)
DODGE_FAR = {3004: 12.0}            # the leap lands from far: hit at 8.99–10.7 m (002546, 235045, 230111)
TOP_HEAL = 0.50                     # Estus on the top only (YouTube guide), and only below this
RESIN_S = 55.0                      # Gold Pine Resin lasts ~60 s — rub again on the top after this
HIT_AFTER_S = 0.6                   # AttackLog: an HP drop this long after its anim ends still counts for that attack


def my_kind(anim) -> str:
    a = anim if anim is not None else -1
    if a == -1:
        return "서 있음/걷기"
    if M.my_attack(a):
        return "공격 중"
    if 700 <= a < 800:
        return "구르기/백스텝"
    if 7000 <= a < 7100:
        return "사다리"
    if 7580 <= a < 7590:
        return "에스트"
    if a in (1500, 1550) or 101500 <= a < 101800:
        return "낙하"
    if 2000 <= a < 2100 or 100000 <= a < 101500:
        return "경직/막기"
    return f"기타({a})"


WAY_NEXT_M = 0.7                    # steer at the first NavMesh path point at least this far ahead
WAY_EVERY_S = 1.0                   # path worked out again this often on the way back


def ladder_way(nm, p, goal):
    """The point to steer at on the way back to the ladder foot: the next NavMesh path point, or goal itself (no mesh / no path).

    ── 직선이 막히는 자리 (10-31 230917 · 20261101_000849) ─────────────────────────
     3012에 구른 뒤 안개벽 쪽 경사로 (49.5~50.6, 16.8~17.2, −118.3~−118.6)에 섬 → 사다리 아래 (49.16, 15.97, −117.1)까지
     직선 스틱이 8 s 막혀 제자리에서 3005·3002에 맞음. NavMesh로는 경사로를 내려가 서쪽 (45.96, −118.38)을 돌아가는 길만 이어짐."""
    if nm is None:
        return goal
    try:
        path = nm.find_path((p.x, p.y, p.z), tuple(goal))
    except Exception:
        path = None
    if not path:
        return goal
    for q in path:
        if math.hypot(q[0] - p.x, q[2] - p.z) >= WAY_NEXT_M:
            return tuple(q)
    return goal


def ang_off(b, p) -> float:
    """Where p stands off b's facing, degrees: 0 right in front, ±180 behind, + its right (raw heading: yaw = heading + π)."""
    fwd = (b.heading or 0.0) + math.pi
    a = math.atan2(p.x - b.x, p.z - b.z) - fwd
    return math.degrees((a + math.pi) % (2 * math.pi) - math.pi)


def crotch_spot(b, p) -> tuple[float, float]:
    """World (x, z) SPOT_FWD in front of b and SPOT_SIDE to the side p is already on (its right when dead center)."""
    fwd = (b.heading or 0.0) + math.pi
    side = 1.0 if ang_off(b, p) >= 0 else -1.0
    rgt = fwd + math.pi / 2
    return (b.x + SPOT_FWD * math.sin(fwd) + side * SPOT_SIDE * math.sin(rgt),
            b.z + SPOT_FWD * math.cos(fwd) + side * SPOT_SIDE * math.cos(rgt))


class AttackLog(threading.Thread):
    """Read-only, its own thread (~30 Hz): each of its attacks (anim 3000–3099, start → anim change) → one event with where we
    stood at its start and the HP we lost while it ran or within HIT_AFTER_S after. Never touches the pad."""

    def __init__(self, tm, events, log):
        super().__init__(name="taurus-attacks", daemon=True)
        self.tm, self.events, self.log = tm, events, log
        self.stop_ev = threading.Event()
        self.n = 0

    def run(self) -> None:
        cur, pending, prev_hp = None, [], None
        while not self.stop_ev.is_set():
            try:
                s = self.tm.snapshot(within=40.0)
            except Exception:
                s = None
            now = time.time()
            if s is None or s.player is None:
                time.sleep(0.03)
                continue
            p = s.player
            b = Taurus.boss(s)
            hp = p.hp
            if prev_hp is not None and hp is not None and hp < prev_hp:
                target = cur or next((x for x in reversed(pending) if now - x["t_end"] <= HIT_AFTER_S), None)
                if target is not None:
                    target["dmg"] += prev_hp - hp
            prev_hp = hp
            for x in [x for x in pending if now - x["t_end"] > HIT_AFTER_S]:
                pending.remove(x)
                self._emit(x)
            a = b.anim if b is not None and b.anim is not None else -1
            if cur is not None and a != cur["anim"]:
                cur["t_end"] = now
                pending.append(cur)
                cur = None
            if cur is None and b is not None and 3000 <= a < 3100:
                h = M.horiz(p, b)
                cur = {"anim": a, "h": round(h, 2), "h_min": round(h, 2), "ang": round(ang_off(b, p)), "dy": round(p.y - b.y, 1),
                       "me_anim": p.anim, "me": my_kind(p.anim), "my_hp": hp, "dmg": 0, "t0": now, "t_end": now}
            elif cur is not None and b is not None:
                cur["h_min"] = round(min(cur["h_min"], M.horiz(p, b)), 2)
            time.sleep(0.03)
        for x in pending + ([cur] if cur else []):
            self._emit(x)

    def _emit(self, x) -> None:
        self.n += 1
        self.events("taurus", what="attack", anim=x["anim"], h=x["h"], h_min=x["h_min"], ang=x["ang"], dy=x["dy"],
                    me=x["me"], me_anim=x["me_anim"], my_hp=x["my_hp"], dmg=x["dmg"], dur=round(x["t_end"] - x["t0"], 2))
        if x["dmg"]:
            self.log(f"      보스 {x['anim']} 맞음 −{x['dmg']}: {x['h']} m, 정면에서 {x['ang']:+d}°, 나 {x['me']}")


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
        # 진입 검사 — 석궁병 둘 처치 확인 · 송진 보유+퀵슬롯 (이 경로는 송진 필수) · 에스트 ≥ 1 ([MoKa] 10-06 "에스트는 1개만",
        # 10-31 "전제 미충족 또는 확인 불가이면 중단·보고"). 미충족이면 이동·공격·아이템 사용 전에 멈춤
        import boss_ready
        v = boss_ready.taurus(self.tm)
        self.log(f"   타우로스 진입 검사: {v.line()}")
        self.events("taurus", what="ready", ok=v.ok, stop=v.stop, facts=v.facts)
        if not v.ok:
            return "멈춤: " + " · ".join(v.stop)
        self.f.ignore_npcs = {TAURUS}                      # walks don't stop to duel it — we run to the ladder
        esc = self.f.esc
        saved = (esc.quit_ok, getattr(esc, "nudge_ok", True))
        try:
            r = self.ms._before({"fog": {"front": list(FOG["front"]), "beyond": list(FOG["beyond"])}}, self.nm, "타우로스")
            if r != "ok":
                return "died" if r == "dead" else f"안개벽 {r}"
            # two hands and the resin here, before calling it — try 3 (2026-10-12): at the ladder top the two-hand toggle's RB
            # went out as a light attack (304000), its step carried us off the narrow top and we fell among its feet
            # full run (MoKa 10-12 "화톳불 부터 보스 공략까지"): zones 1–8 can leave us low — drink up here while it still
            # sleeps on its perch, keeping one for the fight ([MoKa] 10-06 "에스트는 1개만 있으면")
            spare = self.mv.estus_left() - 1
            if spare > 0:
                self.f.heal(PRE_HEAL, sips=min(2, spare))
            self._two_hand()
            self._resin()
            r = self._call()
            if r != "ok":
                return r
            self.alog = AttackLog(self.tm, self.events, self.log)
            self.alog.start()
            self.g0 = getattr(esc, "gen", 0)
            r = self.ms._before({"ladder": {k: (list(v) if isinstance(v, tuple) else v) for k, v in LADDER.items()}},
                                self.nm, "타우로스")
            if r == "dead":
                return "died"
            if r != "ok":
                self.log(f"   타우로스: 사다리 {r} — 그 자리에서 싸움")
                esc.nudge_ok = False
                return self._fight()
            esc.quit_ok, esc.nudge_ok = False, False      # top of the ladder and the drop: no fall quit-out / ledge pull-back
            esc.planned = "타우로스 낙하 공격"               # …and not a fall (fall_seen)
            r = self._plunge()
            esc.quit_ok, esc.planned = saved[0], None      # the ledge pull-back stays off: try 4 it fired twice on landing
            if r == "died":
                return r
            return self._loop(r, saved[0])
        finally:
            if getattr(self, "alog", None) is not None:
                self.alog.stop_ev.set()
                self.alog.join(2.0)
                self.log(f"   타우로스 공격 기록: {self.alog.n}번")
            esc.quit_ok, esc.nudge_ok = saved
            esc.planned = None
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

    def _resin(self, wait: float = 1.0) -> None:
        """Select the resin, X, wait for the rub (~2 s); again once if the count didn't drop. Try 4 (2026-10-12): pressed right
        after the two-hand switch, the X was eaten (3 → 3)."""
        time.sleep(wait)
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

    def _over(self, s):
        """Boss gone from the snapshot: 'killed' if no quit-out since it woke, else 'gone' (see _fight_loop). None = still there."""
        if s is None or self.boss(s) is not None:
            return None
        dead = getattr(self.f.esc, "gen", 0) == getattr(self, "g0", 0) or any(c.npc_param == TAURUS and c.hp <= 0 for c in s.chars)
        return "killed" if dead else "gone"

    def _end(self, end: str, where: str, s) -> str:
        self.log(f"   타우로스 {'처치' if end == 'killed' else '안 보임 (퀵 종료?)'} — {where}, 내 HP {s.player.hp}")
        self.events("taurus", what=end, where=where, hp=s.player.hp)
        return end

    def _loop(self, first: str, quit_ok: bool) -> str:
        """Plunge rounds: (one light while it reels) → back to the ladder → climb → (Estus / resin on top) → plunge."""
        esc = self.f.esc
        guard_ok, self.mv.guard_ok = getattr(self.mv, "guard_ok", True), False    # two hands: LB is a weapon block
        self.pad.guard(False)
        r = first
        try:
            for cycle in range(1, CYCLES + 1):
                s = self.mv.snap(40.0)
                if (end := self._over(s)):
                    return self._end(end, f"낙하 {cycle - 1}번 뒤", s)
                if r == "ok":
                    self._punish()
                if not self.f.alive():
                    return "died"
                if cycle >= PLUNGES:
                    # ── 낙하는 한 번, 그다음은 다리에서 붙어 싸움 ([MoKa] 11-02) ────────────────────────────────
                    #  "나는 낙하 공격 한 번 하고 황금 송진 유효할때 계속 때려. 에스트 마시면서. 4-5번만 때리면 죽어 타우로스.
                    #   내가 보기엔 계단 올라가는 것도 위험해 보여. 올라가다 맞으면 연속 2대 맞으면 죽잖아. 나는 그런 선택 않해야."
                    #  → 사다리로 돌아가 다시 오르지 않음. 11-02 025549는 낙하 3번으로 잡았지만 오르는 길에 −242, 꼭대기 에스트 2번 끊김
                    #  송진은 싸움 중에 다시 바르지 않음 — [MoKa] "송진 다시 바르면 절대 않되. 그러다가 죽어" · "처음 바른 송진 유효할때 해결해야해"
                    self.log(f"   타우로스: 낙하 {cycle}번 뒤 붙어서 싸움 (송진 {self._resin_age()})")
                    return self._fight()
                r = self._back_up(cycle)
                if r in ("died", "killed", "gone"):
                    return r
                if r != "ok":
                    self.log(f"   타우로스: 사다리로 못 감 ({r}) — 붙어서 싸움")
                    return self._fight()
                self._on_top()
                esc.quit_ok, esc.nudge_ok = False, False
                esc.planned = "타우로스 낙하 공격"
                r = self._plunge()
                esc.quit_ok, esc.planned = quit_ok, None
                if r == "died":
                    return r
            return self._fight()
        finally:
            self.mv.guard_ok = guard_ok

    def _punish(self) -> None:
        """Just landed and it reels: one light if it is close (YouTube guide [02:02])."""
        s = self.mv.snap(40.0)
        b = self.boss(s)
        if s is None or b is None or M.horiz(s.player, b) > PUNISH_R or (s.player.sp or 0) < HIT_SP:
            return
        if self.mv.face(s, b, deg=35.0):
            hit = self.mv.light(s, b, n=1, sp_second=999)
            self.log(f"   타우로스 착지 뒤 약공: 피해 {hit.dmg}, 내 피해 {hit.taken}")
            self.events("taurus", what="hit", dmg=hit.dmg, taken=hit.taken, h=round(M.horiz(s.player, b), 2), anim=b.anim,
                        sp=s.player.sp)

    def _back_up(self, cycle: int) -> str:
        """Run to the ladder foot (roll toward it when it starts a swing within DODGE_R), then climb."""
        bottom = LADDER["bottom"]
        t0, prev_a, rolled = time.time(), None, 0.0
        way, way_t = bottom, 0.0
        dodged, seen_t, last_at = True, 0.0, None
        while time.time() - t0 < BACK_S:
            if not self.f.alive():
                return "died"
            s = self.mv.snap(40.0)
            if s is None:
                time.sleep(0.05)
                continue
            if (end := self._over(s)):
                return self._end(end, f"{cycle}회 뒤 사다리로 가는 중", s)
            p, b = s.player, self.boss(s)
            d = math.hypot(p.x - bottom[0], p.z - bottom[2])
            if d <= 0.6:
                break
            if time.time() - way_t > WAY_EVERY_S or math.hypot(p.x - way[0], p.z - way[2]) < 0.5:
                way, way_t = ladder_way(self.nm, p, bottom), time.time()
            a = b.anim if b.anim is not None else -1
            started = 3000 <= a < 3100 and a != prev_a
            prev_a = a
            # ── 시작이 아니라 닿기 직전에 구른다 (20261101_002546) ─────────────────────────────────
            #  시작 보자마자 구르면 1.4~2.0 s 앞서 굴러 구르기가 끝난 뒤 맞음 (001740 끝 0.14 s 뒤, 000027·001326 구르는 중).
            #  또 구르기 쿨다운 중 시작한 3005는 '시작'을 놓쳐 안 구르고 달리다 −233 (74.58 시작 → 76.10 맞음).
            #  블랙박스 60 Hz에서 애니 시작 → 피해가 애니마다 일정 (3002 1.41~1.49, 3005 1.51~1.64 …) → HIT_AT.
            #  게임의 애니 시간(anim_time)으로 HIT_AT − ROLL_LEAD에 구르고, 그때까지는 사다리 쪽으로 계속 달린다.
            #  HIT_AT에 없는 애니(3012 등)는 전처럼 시작에 바로.
            at = self.tm.anim_time(b.ptr) if 3000 <= a < 3100 and hasattr(self.tm, "anim_time") else None
            if started or (at is not None and last_at is not None and at < last_at - 0.2):   # new swing (or same id again)
                dodged, seen_t = False, time.time()
            last_at = at
            hit_at = HIT_AT.get(a)
            if hit_at is not None:
                age = at if at is not None else time.time() - seen_t
                due = not dodged and hit_at - ROLL_LEAD <= age < hit_at + 0.1 and M.horiz(p, b) < DODGE_FAR.get(a, DODGE_R)
            else:
                due = started and M.horiz(p, b) < DODGE_R and time.time() - rolled > 1.2
            if due and s.cam_yaw is not None:
                dodged = True
                when = "시작" if hit_at is None else f"{age:.2f} s (닿기 {hit_at:.2f} s)"
                self.log(f"   타우로스 {a} {when} {M.horiz(p, b):.1f} m (정면에서 {ang_off(b, p):+.0f}°) — 사다리 쪽으로 구르기")
                self.events("taurus", what="dodge", anim=a, h=round(M.horiz(p, b), 2), ang=round(ang_off(b, p)),
                            at=None if at is None else round(at, 3))
                self.mv.roll_toward(s, way[0], way[2], hold=True)   # stick held 1.2 s: 710 ends ~1.0 s (let go: 2.0 s, 10-31)
                rolled = time.time()
                continue
            if s.cam_yaw is not None:
                self.pad.sprint(d > 2.5)
                self.pad.move(*self.mv.stick_to(s, way[0], way[2], 1.0 if d > 1.5 else 0.5))
            self.pad.release_due()
            time.sleep(0.03)
        self.pad.sprint(False)
        self.pad.neutral()
        r = self.ms._before({"ladder": {"bottom": list(bottom), "face": list(LADDER["face"]), "top_y": LADDER["top_y"]}},
                            self.nm, f"타우로스 {cycle}회 뒤")
        return "died" if r == "dead" else ("ok" if r == "ok" else f"사다리 {r}")

    def _on_top(self) -> None:
        """On the top while it isn't below yet: Estus if low (YouTube guide [02:23]); the resin again once it has worn off."""
        s = self.mv.snap(40.0)
        if s is None:
            return
        b = self.boss(s)
        clear = b is None or M.horiz(s.player, b) > PLUNGE_R + 1.0
        # 11-02 002807: 꼭대기에서 HP 225/698(32 %)인데 보스가 사다리 밑 4.3 m라 안 마시고 낙하 → 보스 HP 9 남기고 착지 뒤 3001 −225에 사망.
        #  보스는 탑 위에 손이 안 닿음 — 낮으면 낙하 기회를 하나 놓치더라도 먼저 마신다
        if s.player.hp < s.player.max_hp * TOP_HEAL and self.mv.estus_left() > 0:
            r = self.mv.drink(lambda sn: True)
            self.log(f"   타우로스: 꼭대기에서 에스트 {r}")
            self.events("estus", **r)
            s = self.mv.snap(40.0)
            b = self.boss(s)
            clear = s is not None and (b is None or M.horiz(s.player, b) > PLUNGE_R + 1.0)
        rt = getattr(self, "resin_t", None)
        if clear and (rt is None or time.time() - rt > RESIN_S) and (self.tm.goods_count(RESIN) or 0) > 0:
            self._resin(wait=0.0)

    def _resin_age(self) -> str:
        rt = getattr(self, "resin_t", None)
        return "안 바름" if rt is None else f"{time.time() - rt:.0f} s 전"

    def _fight(self) -> str:
        """Between its legs ([MoKa] "바짝 붙어서 공격", 11-03 "보스 가랑이 사이에서 공격"): within SPOT_R of crotch_spot() and
        stamina ≥ HIT_SP → three lights (MoKa 11-09); else walk to the spot (floor-checked) and let stamina come back. HP < ESTUS_HP and it isn't swinging → Estus."""
        t0, hits = time.time(), 0
        # no guard: two-handed, LB is a weapon block — try 4 (2026-10-12) light() held it after each swing, the axe soaked
        # its hits (stamina 98 → 9), stamina came back slowly with LB down, and only 1 of 4 lights landed
        guard_ok, self.mv.guard_ok = getattr(self.mv, "guard_ok", True), False
        self.pad.guard(False)
        self.log(f"   타우로스 근접: {'양손 가드 들고 들어감 (P-141)' if GUARD_CLOSE else '가드 없이'}")
        try:
            return self._fight_loop(t0, hits)
        finally:
            self.mv.guard_ok = guard_ok
            self.pad.guard(False)

    def _fight_loop(self, t0: float, hits: int) -> str:
        g0 = getattr(self.f.esc, "gen", 0)
        low_said = False
        win_t = None                                   # first tick of the current sip window off the spot
        spot_t = None                                  # first tick on the spot since the last swing
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
                # gone after a quit-out = reloaded outside the fog, not dead (try 11, 2026-10-12: a fall quit-out at HP 33 put us
                # in front of the fog wall, the boss at HP 150 dropped out and this said "killed"). A real kill also just drops
                # out (tries 5·8: last seen HP 25 / 107, our hits summed to exactly its HP) — so judge by the quit-out, not HP 0
                dead = getattr(self.f.esc, "gen", 0) == g0 or any(c.npc_param == TAURUS and c.hp <= 0 for c in s.chars)
                what = "killed" if dead else "gone"
                self.log(f"   타우로스 {'처치' if dead else '안 보임 (퀵 종료?)'} — {time.time() - t0:.0f} s, 약공 {hits}번, "
                         f"내 HP {s.player.hp}, 위치 ({s.player.x:.1f},{s.player.y:.1f},{s.player.z:.1f})")
                self.events("taurus", what=what, secs=round(time.time() - t0, 1), hits=hits, hp=s.player.hp)
                return what
            p = s.player
            h = M.horiz(p, b)
            a = b.anim if b.anim is not None else -1
            # ── 붙어 싸울 때 에스트는 기력이 바닥날 때만, 다리 사이에서 (P-142 · P-144, MoKa 11-09) ─────────────────
            #  "에스트를 왜 마셔, 다리 사이에서 몇대 때리면 죽는데, 에스트 마시면서 시간 낭비" · "스테미나가 다 떨어져가서 할게 없으면
            #  에스트 마셔도 되겠지만, 다른 케이스는 스테미나가 더 중요한 상황" · "에스트를 마셔도 다리 사이에서 마셔야지".
            #  → HP가 마실 선 아래여도 기력이 HIT_SP 이상이면 아래에서 약공×3 (마시지 않음, 11-09 '3대 연속'). 기력이 모자라 어차피 가랑이 자리에서
            #  기다리는 틱에만, 보스가 BOSS_ATTACK 밖이고 자리 SIP_SPOT_R 안이면 마심. P-142 1차의 '약공 안 함 + 4 m 물러남'은 없앰
            #  (MoKa: "다리사이로 붙으라니깐 왜 멀리 떨어져"). 그 틈이 SIP_SPOT_WAIT 넘게 열렸는데 자리에 못 가면 그 자리에서 마심 (측정 전)
            low = p.hp < max(p.max_hp * ESTUS_HP, 2 * TAURUS_HIT) and self.mv.estus_left() > 0
            sx0, sz0 = crotch_spot(b, p)
            on_spot = math.hypot(sx0 - p.x, sz0 - p.z) <= SIP_SPOT_R
            window = low and (p.sp or 0) < HIT_SP and a not in BOSS_ATTACK
            win_t = (win_t or time.time()) if window and not on_spot else None
            late = win_t is not None and time.time() - win_t > SIP_SPOT_WAIT
            if window and (on_spot or late):
                if late:
                    self.log(f"   타우로스: 다리 사이 못 가고 {SIP_SPOT_WAIT:g} s — 그 자리에서 마심 ({h:.1f} m)")
                win_t = None
                self.pad.neutral()
                self.pad.guard(False)
                ok = lambda sn: (self.boss(sn) is None or (self.boss(sn).anim or -1) not in BOSS_ATTACK)
                r = self.mv.drink(ok)
                self.log(f"   타우로스 싸움 중 에스트 (기력 {p.sp}, 다리 사이 {math.hypot(sx0 - p.x, sz0 - p.z):.1f} m): {r}")
                self.events("estus", **r)
                # [MoKa] 11-09 "에스트를 두번 마셔봐" — 072235: 한 번 마셔 29 → 85 (마시는 중 −244), 또 맞아 사망. 한 모금 끝나면 바로 한 번 더
                #  (에스트 남았고 보스가 BOSS_ATTACK 밖일 때 — drink의 ok 검사)
                if r.get("ok") and self.mv.estus_left() > 0 and self.f.alive():
                    r2 = self.mv.drink(ok)
                    self.log(f"   타우로스 싸움 중 에스트 두 번째: {r2}")
                    self.events("estus", second=True, **r2)
                continue
            if low and not low_said:
                low_said = True
                self.log(f"   타우로스: HP {p.hp} — 마실 선 아래, 기력 {p.sp}: 기력 있으면 다리 사이에서 계속 치고, 모자랄 때 마심 (P-144)")
                self.events("taurus", what="low_hp", hp=p.hp, sp=p.sp, anim=a, h=round(h, 2))
            low_said = low_said and low
            sx, sz = crotch_spot(b, p)
            off = math.hypot(sx - p.x, sz - p.z)
            # [MoKa] 11-03 "2대 때리고 다시 가랑이에 붙어봐. 거리 조절도 되지만, 스테미나도 채워야해" — always two, then stay on the
            # spot (it re-follows the spot as the boss turns) until stamina is back to HIT_SP (11-09: was HIT_SP2 80 for two)
            # [MoKa] 11-09 "다리에 붙었으면 바로 공격하고 3대를 연속으로 때려봐" — 071032: 기력 80을 가드 든 채 기다리느라 6 s (초당 ~9),
            # 그동안 아무것도 안 함. 이제 자리에 붙으면 기력 HIT_SP(40)부터 바로 약공×3 (세 번째는 기력이 음수로 가도 나감, 측정 전)
            spot_t = (spot_t or time.time()) if off <= SPOT_R else None
            waited = time.time() - spot_t if spot_t is not None else 0.0
            if off <= SPOT_R and ((p.sp or 0) >= HIT_SP or (waited >= SPOT_ATTACK_S and (p.sp or 0) > 0)):
                if self.mv.face(s, b, deg=30.0):
                    self.log(f"   타우로스: 다리 사이 도착 → 약공까지 {waited:.2f} s (기력 {p.sp})")
                    spot_t = None
                    n = 3
                    self.pad.guard(False)
                    hit = self.mv.light(s, b, n=n, sp_second=0)
                    hits += n
                    self.events("taurus", what="hit", dmg=hit.dmg, taken=hit.taken, h=round(h, 2), anim=a, sp=p.sp,
                                guard=GUARD_CLOSE)
                    self.log(f"   타우로스 약공×{n}: 피해 {hit.dmg}, 내 피해 {hit.taken}, 기력 {p.sp} (거리 {h:.1f} m)")
                continue
            if GUARD_CLOSE:
                self.pad.guard(True)
            if off > SPOT_R and s.cam_yaw is not None:
                way = nav.safe_heading(self.nm, p, sx - p.x, sz - p.z, reach=min(1.2, max(0.3, off)))
                if way is None:
                    self.pad.move(0.0, 0.0)
                else:
                    # [MoKa] 11-03 "때릴때 마다 뒤로 밀려" — each swing pushes us off the spot: full stick back in unless right at it
                    self.pad.move(*self.mv.stick_to(s, p.x + way[0], p.z + way[1], 1.0 if h > 4.0 or off > 0.8 else 0.6))
            else:
                self.pad.move(0.0, 0.0)
            time.sleep(0.05)
        self.log(f"   타우로스 싸움: {FIGHT_LIMIT:.0f} s 넘음, 약공 {hits}번")
        return "timeout"
