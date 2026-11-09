"""Reflex — above layer 1 (moves), below layer 3 (duel). Called **first on every tick**, fighting or walking (like breathing).
On a tick where the reflex moved (True), the caller skips its own action for that tick. Knows neither weapon nor goal.

Evidence (2026-09-24 log analysis, ramp 23 runs, 5,987 damage):
  · Blocking with shield **facing** the attacker: 34 (115 without shield) — but hits taken to the **side/back** while shield up: 16 hits, 1,560 (avg 74, same as no shield)
  · Took more from **other enemies** than from the current opponent (12 hits 1,082 vs 5 hits 588). 75 % happened with an enemy within 2.5 m
  · The old reflex.py raised the shield at ~0 s after attack start but did not face the attacker; 81 % of hits came after the shield was up
  · 3000-series anims linger 1.5~5.3 s after the attack ends — treating that as a threat means never attacking (once in 87 s)
  · Holding the shield cuts stamina regen by 80 % (wiki) — raise it only on threats, not always

Therefore:
  1) A threat only for THREAT_S **right after an attack anim starts**. Put the nearest threat within 2.5 m **in front of the body** and guard
  2) No threat but HP just dropped (unseen attack) → guard toward the nearest enemy within 3 m
  4) Below GUARD_SP stamina, don't block (a guard break pushes you off an edge) — stand facing that enemy (don't turn your back and retreat)
  3) Unblockable attacks (guard break 3009 etc. — layer 4 tells which via unblockable(c)) get
     a backstep instead of the shield; if behind is a cliff, roll sideways (blocked, guard broke, pushed off, fatal fall, 2026-09-24)
  Don't turn toward a direction with no ground underfoot (2 ramp falls recorded).
  (Two or more within 2.5 m is resolved by watch.Escape via quit-out)
"""
from __future__ import annotations

import math
import time

import ctl

import nav

from . import moves as M

THREAT_R = 2.5           # horizontal
EVADE_DELAY = 0.0        # dodge this long after attack start — dodging instantly lets the enemy track and follow in (10 runs: half of 51 backsteps got hit)
EVADE_R = 1.8            # backstep style: dodge only swings within this — dodging at 2.5~3 m too kept pushing us back, couldn't close in for 6 s (2026-09-24)
MIXED_R = 4.0            # even in backstep style, use the shield if another enemy is awake within this (250 taken from two without shield)
GUARD_SP = 25            # blocking below this breaks the guard (blocked at SP 12~22, guard broke, pushed off, fatal fall, 2026-09-24) — back off instead
THREAT_S = 1.3           # a threat only for this long after an attack anim starts
HIT_R = 3.0
GUARD_HIT_ANIM = 140     # my anim % 10000 when something hits my raised shield (Battle Axe 140 · Claymore 20140)
GUARD_COUNTER_STEP = 0.3 # guard_counter: the hitter within weapon reach + this (farther = an arrow or bolt on the shield)
WALL_BOUNCE_ANIM = 150   # my attack anim % 1000 after the swing struck a wall (Battle Axe 303000 → 303150) — wall_bounced()
BOUNCE_SPOT_R = 0.6      # a swing from within this of a bounce spot would bounce again — duel.rule_wall_bounce moves first
BOUNCE_KEEP_S = 120.0    # a bounce spot is remembered this long (one zone's fights)


def wall_bounced(hit) -> bool:
    """
    ── 무기가 벽에 튕김 (P-139, [MoKa] 2026-11-08 "무기가 벽에 부딪혀서 공격 실패함" · "감지가 되면 다른데로 가야지") ─────────
     · 내 공격 애니 뒤에 …150 (배틀 액스 303000 → 303150)이 나오면 벽에 걸린 휘두르기로 봄
     · 근거 (기록 대조만, 게임에서 따로 재 본 것 아님): 221120 구역 4 피해 0·안 맞음 휘두르기 2번 모두 303150 — MoKa가 같은 장면을
       "무기가 벽에" 라고 봄. 11-03~08 런 전체 303150 36번 중 피해 0이 20번. 피해가 난 16번은 먼저 맞히고 벽에 걸린 것으로 추정 (가설)
     · 클레이모어 등 다른 무기의 튕김 애니는 아직 못 봄 — 같은 규칙(…150)이 맞는지 모름
    """
    for x in getattr(hit, "my_anims", None) or ():
        a = x[1] if isinstance(x, (tuple, list)) else x
        if a is not None and a >= 100000 and a % 1000 == WALL_BOUNCE_ANIM:
            return True
    return False


class Reflex:
    def __init__(self, mv: M.Moves, nm=None, unblockable=lambda c: False, bs_ok=lambda c: True,
                 threat_s=lambda c: THREAT_S, lock_s=lambda c: THREAT_S):
        self.mv, self.nm, self.unblockable, self.bs_ok = mv, nm, unblockable, bs_ok
        # threat_s(c) / lock_s(c): how long after c's attack starts it is a threat / stays locked. Both THREAT_S unless given
        # (P-89 offline comparison only — tests/p89_reflex_window_test.py; nothing in the bot passes them)
        self.threat_s, self.lock_s = threat_s, lock_s
        # bs_ok(c): may we backstep-attack this enemy — shield soldiers block the lunging axe, then their combo dealt 351 (2026-09-24 diagnosis)
        self.evade = False       # True = don't block; dodge **every** attack with backstep/roll (backstep style — two-handed, no shield)
        self.bs_attack = False   # append a backstep attack (B → R1) when dodging (Style.bs_attack)
        self.reflex_on = True    # False = tick() only records (update), never moves — rush style: no block, no dodge, keep attacking
        self.events = None       # if layer 4 sets it, an 'evade' event per dodge (kind, distance, hit within the next 1.3 s) — counted by style_report.py
        self._pending: dict | None = None
        self.last_hit = None     # last backstep-attack result (duel takes it for logging)
        self.guard_counter_on = True   # 방패에 맞으면 약공 (P-136) — every caller of tick() and duel's rule_guard_counter
        self._gc_done = False          # this block (my anim …140) already decided
        self.bounces: list = []         # [x, z, t, tries] where my swing struck a wall (P-139) — note_bounce / at_bounce
        self.gc_last = None            # (my anim, foe or None, Hit or None, why or None) — the last decision, for the caller's log
        self._dodged: dict = {}        # ptr → start time of the dodged attack (dodge once per attack)
        self.prefer = None             # current opponent (duel sets it every tick) — preferred when there are several threats
        self._lock = (None, 0.0)       # (ptr, until) — keep the enemy we started guarding against in front for the whole attack
        # switching to the nearest enemy every tick flip-flopped between two in front and behind, taking side/back hits (body-to-enemy -117~-141°, 188 → 0, 2026-09-24)
        self._anim: dict = {}          # ptr → last anim
        self._start: dict = {}         # ptr → time the attack anim started
        self._hp = None
        self._hit_t = 0.0
        self.acted = 0

    def update(self, s) -> None:
        now = time.time()
        for c in s.hostile(8.0):
            a = c.anim if c.anim is not None else -1
            if a in M.ATTACK and self._anim.get(c.ptr) != a:
                self._start[c.ptr] = now
            self._anim[c.ptr] = a
        hp = s.player.hp
        if self._hp is not None and hp is not None and hp < self._hp:
            self._hit_t = now
        self._hp = hp
        if self._pending is not None:
            pe = self._pending
            if hp is not None:
                pe["min_hp"] = min(pe["min_hp"], hp)
            if now - pe["t"] >= THREAT_S:
                self._pending = None
                if self.events:
                    self.events("evade", kind=pe["kind"], dist=pe["dist"], eanim=pe["eanim"], npc=pe["npc"], taken=pe["hp0"] - pe["min_hp"])

    def attack_age(self, ptr) -> float | None:
        """Seconds since this enemy's current attack started (None if not attacking)."""
        a = self._anim.get(ptr)
        return time.time() - self._start[ptr] if a in M.ATTACK and ptr in self._start else None

    def threats(self, s) -> list:
        now = time.time()
        return [c for c in s.hostile(THREAT_R + 2.0)
                if c.hp > 0 and M.horiz(s.player, c) < THREAT_R and now - self._start.get(c.ptr, 0.0) < self.threat_s(c)
                and (c.anim if c.anim is not None else -1) in M.ATTACK]

    def threat_now(self, s) -> bool:
        self.update(s)
        return bool(self.threats(s)) or (time.time() - self._hit_t < 0.4 and self._nearest(s, HIT_R) is not None)

    def _nearest(self, s, r: float):
        near = [c for c in s.hostile(r + 2.0) if c.hp > 0 and not (9000 <= (c.anim or 0) < 9100) and M.horiz(s.player, c) < r]
        return min(near, key=lambda c: M.horiz(s.player, c), default=None)

    def note_bounce(self, p, hit) -> bool:
        """Remember p as a wall-bounce spot if hit's swing struck a wall (wall_bounced). → bounced?"""
        if p is None or p.x is None or not wall_bounced(hit):
            return False
        old = self.at_bounce(p)
        if old is not None:
            old[2] = time.time()
        else:
            self.bounces.append([p.x, p.z, time.time(), 0])
        if self.events:
            self.events("wall_bounce", pos=[round(p.x, 2), round(p.z, 2)], dmg=getattr(hit, "dmg", 0))
        return True

    def at_bounce(self, p):
        """The remembered bounce spot within BOUNCE_SPOT_R of p (newest first), or None."""
        now = time.time()
        self.bounces = [b for b in self.bounces if now - b[2] < BOUNCE_KEEP_S]
        if p is None or p.x is None:
            return None
        return next((b for b in reversed(self.bounces) if math.hypot(p.x - b[0], p.z - b[1]) < BOUNCE_SPOT_R), None)

    def guard_counter(self, s, prefer=None):
        """
        ── 방패에 맞으면 바로 약공 — 모든 싸움의 기본 (P-136, [MoKa] 2026-11-08) ──────────────────────────────
         "방패에 뭔가 부딪히면, 자동으로 약공이 나가야 하는데 3번 부딪히고 공격 한거 보면 이것도 시퀀스가 아니네" ·
         "방패, 약공이 우선이야. 이건 기본이고" · "방패, 약공은 모든 공격에세 기본으로 하게 수정해."
         · 내 애니가 막기 피격 (…140)이 된 틱에 R1 하나 — 경직 중에 누르면 경직이 풀리는 대로 약공이 나감
           (202047 hits #3 · #5: 20140 → 253000 0.3 s). 한 번 막을 때마다 한 번 (애니가 140을 벗어나면 다시 셈)
         · 맞힌 놈 = 무기 닿는 거리 + GUARD_COUNTER_STEP 안, 높이 차 1 m 안에서 휘두르는 중 (3000번대) 또는 내 방패에 튕긴
           휘청 (3500번대 — 205219 구역 1: 그 틱에 이미 3500이라 3000번대만 세던 첫 판은 3번 다 안 침). prefer (싸우는 놈) 먼저
         · 안 침 (몸이 못 하는 것만): 그런 놈 없음 (멀리서 쏜 화살·볼트도 방패에 140 — foes.py), 기력 sp_min 미만.
           옆 놈이 같이 휘둘러도 침 (첫 판은 rule_after_swing처럼 안 쳤음 — [MoKa] "모든 공격에서 기본")
         → Hit (쳤음) | None. self.gc_last에 (내 애니, 그놈, Hit, 안 친 이유)
        """
        p = s.player
        a = p.anim if p.anim is not None else -1
        if not (0 <= a < 100000 and a % 10000 == GUARD_HIT_ANIM):
            self._gc_done = False
            return None
        if self._gc_done or not self.guard_counter_on:
            return None
        self._gc_done = True                                   # this block is decided — counter or not, once
        w = getattr(self.mv, "weapon", None)
        reach = (getattr(w, "reach", None) or 1.6) + GUARD_COUNTER_STEP
        sp_min = getattr(w, "sp_min", None) or 30
        near = [x for x in s.hostile(reach + 2.0) if x.hp > 0 and ((x.anim or -1) in M.ATTACK or (x.anim or -1) in M.STAGGER)
                and M.horiz(p, x) <= reach and abs(x.y - p.y) <= 1.0]
        c = next((x for x in near if x.ptr == prefer), None) or min(near, key=lambda x: M.horiz(p, x), default=None)
        why = ("닿는 거리에 휘두르는 놈 없음" if c is None else f"기력 {p.sp}" if (p.sp or 0) < sp_min
               else "벽에 튕긴 자리 (P-139)" if self.at_bounce(p) is not None else None)
        if why is not None:
            self.gc_last = (a, c, None, why)
            return None
        h = self.mv.light(s, c, n=1)
        self.note_bounce(p, h)
        self.gc_last = (a, c, h, None)
        if self.events:
            self.events("guard_counter", anim=a, npc=c.npc_param, dist=round(M.horiz(p, c), 2), dmg=h.dmg, taken=h.taken)
        return h

    def tick(self, s) -> bool:
        """→ whether the reflex moved this tick (shield, turning)."""
        self.update(s)
        if not self.reflex_on:
            return self._act(None)  # rush: record only (attack_age etc.), no block or dodge — the attack loop isn't interrupted
        if not self.evade and self.guard_counter(s, prefer=self.prefer) is not None:
            self.acted += 1
            return self._act("guard_counter", self.gc_last[1], s, self._start.get(self.gc_last[1].ptr))
        th = self.threats(s)
        now = time.time()
        lock_ptr, lock_until = self._lock
        c = next((x for x in th if x.ptr == lock_ptr), None) if now < lock_until else None
        if c is None and th:
            c = next((x for x in th if x.ptr == self.prefer), None) or min(th, key=lambda x: M.horiz(s.player, x))
            self._lock = (c.ptr, self._start.get(c.ptr, now) + self.lock_s(c))
        if c is None and time.time() - self._hit_t < 0.4:
            c = self._nearest(s, HIT_R)                    # 2) hit from an unknown source — nearest enemy
        if c is None:
            return self._act(None)
        p = s.player
        start = self._start.get(c.ptr)
        evade_now = self.evade and M.horiz(p, c) <= EVADE_R          # dodge even with two — never use the shield (user)
        if evade_now and start is not None and now - start < EVADE_DELAY and self._dodged.get(c.ptr) != start:
            self.step_away(s, c)                           # too early — just face it and wait (dodge after the blade is committed so it can't track)
            self.acted += 1
            return self._act("wait", c, s, start)
        if c.anim is not None and start is not None and (evade_now or self.unblockable(c)):
            if self._dodged.get(c.ptr) != start:
                self._dodged[c.ptr] = start
                kind = self.dodge(s, c, attack=self.bs_attack)   # every style that allows it, not only evade_now (P-121)
                self._pending = {"t": now, "kind": kind, "dist": round(M.horiz(p, c), 2), "eanim": c.anim, "npc": c.npc_param,
                                 "hp0": p.hp or 0, "min_hp": p.hp or 0}
                act = f"dodge:{kind}"
            else:
                self.step_away(s, c)                       # once dodged, keep distance without shield for the rest of that attack
                act = "step_away"
            self.acted += 1
            return self._act(act, c, s, start)
        if (p.sp or 0) < GUARD_SP or self.evade:
            self.step_away(s, c)                       # backstep style: if we can't dodge (too far), just face it, no shield
            self.acted += 1
            return self._act("face", c, s, start)
        self.mv.pad.guard(True)
        safe_turn = self.nm is None or nav.can_move(self.nm, p, c.x - p.x, c.z - p.z, 0.8)
        if safe_turn and not M.quiet_aim(p, c, self.attack_age(c.ptr)):   # swing about to end, aimed → stick stays off (proposal A)
            self.mv.face(s, c, deg=25.0)
        else:
            self.mv.pad.move(0.0, 0.0)
        self.acted += 1
        return self._act("guard", c, s, start)

    _ctl_last: tuple | None = None   # P1-C: last (act, ptr) recorded

    def _act(self, act: str | None, c=None, s=None, start=None) -> bool:
        """tick's return value: True when it acted (act given), False when not. P1-C: with run.py --ctl, a 'dec.reflex' record
        when (act, target) changes — a new burst after a quiet tick counts as a change. Record only; never raises."""
        if not ctl.on():
            return act is not None
        key = None if act is None else (act, getattr(c, "ptr", None))
        if key != self._ctl_last:
            self._ctl_last = key
            if act is not None:
                try:
                    ctl.emit("dec.reflex", act=act, ptr=c.ptr, eanim=c.anim, npc=getattr(c, "npc_param", None),
                             age=None if start is None else round(time.time() - start, 3),
                             snap_t=getattr(s, "t", None), fseq=getattr(s, "fseq", None))
                except Exception:
                    pass
        return act is not None

    def _others_near(self, s, c) -> bool:
        return any(x.ptr != c.ptr and x.hp > 0 and x.anim not in (-1, None) and M.horiz(s.player, x) < MIXED_R for x in s.hostile(MIXED_R + 1))

    def dodge(self, s, c, attack: bool = False) -> str:
        """Unblockable attack — backstep if there is ground behind (with attack: backstep + R1 as one move); otherwise face it.
        No ground info at all → guard.

        ── 회피 뒤 약공은 한 동작 (P-121, [MoKa] 2026-11-03) ──────────────────────────────
         · "봇은 구르기 하고 기다렸다 약공 … 백 스텝 하고 기다렸다 공격, 사이가 떠 버려. 그런데 발차기 약공은 한 동작 처럼 해"
         · 원인: 발차기만 kick_combo 안에서 R1까지 누름. 백스텝은 backstep()만 하고 판단 루프로 돌아가 휘두름 끝·몸 돌리기·
           걸어가기를 거쳐 약공 (try 27: 백스텝 뒤 다음 공격 3.5 s). 백스텝 약공은 evade 스타일에서만 켜져 있었고,
           roll_r1은 정의만 있고 부르는 곳이 없었음
         · 그래서 guard 스타일도 bs_attack. 옆 구르기는 계속 안 함 (2026-09-24 16 m 낙사)
         · 뒤에 바닥이 없을 때 그놈 쪽 구르기 약공도 넣었다가 뺌 — 반사는 늘 붙어서(EVADE_R 안) 휘두를 때라,
           [MoKa] 11-03 "구르기 공격을 왜 이렇게 가까운데 사용해." 구르기는 거리가 있을 때만 (duel COMBO_ONLY BS_R)
        """
        p = s.player
        if p.heading is not None and self.nm is not None:
            back = (math.sin(p.heading), math.cos(p.heading))          # heading direction = behind the body (same convention as hunt.backstep_attack)
            if nav.can_move(self.nm, p, back[0], back[1], 2.6):
                if attack and self.bs_ok(c) and nav.can_move(self.nm, p, -back[0], -back[1], 2.2):   # first hit lands near the start spot; 3.0 almost always fails on the ramp
                    h = self.mv.backstep_attack(s, c, self.nm)     # backstep + R1 as one move (user)
                    if h.presses:
                        self.last_hit = h
                        return "bsattack"
                self.mv.backstep()
                return "backstep"
            if self.evade:
                # backstep style: no roll if there's no ground behind — passed the 2.5 m side check yet rolled into a 16 m fatal fall (2026-09-24, 4 runs).
                # taking one hit is cheaper than a fatal fall. Just face it.
                self.step_away(s, c)
                return "hold"
            # side roll removed (evidence-grade gate, 2026-09-26) — NavMesh picked the direction (passed the 2.5 m side check yet 16 m fatal fall, 2026-09-24).
            # backstep is a user tip (human_verified); NavMesh only blocks it when there's no ground behind
            self.step_away(s, c)
            return "hold"
        self.mv.guard(True)                                # no ground behind or to the sides — just face it unless guard_ok
        return "guard"

    def step_away(self, s, c) -> None:
        """Stand facing the enemy without shield. We used to push the stick away, but without lock-on that **turned and walked off**, taking hits in the back
        (body-to-enemy ±180°, 2026-09-24 terrace — user: "it can't line up its facing and attacks in the wrong direction")."""
        self.mv.pad.guard(False)
        self.mv.face(s, c, deg=25.0)

    def hold(self, max_s: float = 2.0) -> None:
        """Run only the reflex until the threat passes (when stopped while walking)."""
        t0 = time.time()
        while time.time() - t0 < max_s:
            s = self.mv.snap(15.0)
            if s is None or not self.tick(s):
                break
            time.sleep(0.02)
        self.mv.pad.move(0.0, 0.0)
