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

import nav

from . import moves as M

THREAT_R = 2.5           # horizontal
EVADE_DELAY = 0.0        # dodge this long after attack start — dodging instantly lets the enemy track and follow in (10 runs: half of 51 backsteps got hit)
EVADE_R = 1.8            # backstep style: dodge only swings within this — dodging at 2.5~3 m too kept pushing us back, couldn't close in for 6 s (2026-09-24)
MIXED_R = 4.0            # even in backstep style, use the shield if another enemy is awake within this (250 taken from two without shield)
GUARD_SP = 25            # blocking below this breaks the guard (blocked at SP 12~22, guard broke, pushed off, fatal fall, 2026-09-24) — back off instead
THREAT_S = 1.3           # a threat only for this long after an attack anim starts
HIT_R = 3.0


class Reflex:
    def __init__(self, mv: M.Moves, nm=None, unblockable=lambda c: False, bs_ok=lambda c: True):
        self.mv, self.nm, self.unblockable, self.bs_ok = mv, nm, unblockable, bs_ok
        # bs_ok(c): may we backstep-attack this enemy — shield soldiers block the lunging axe, then their combo dealt 351 (2026-09-24 diagnosis)
        self.evade = False       # True = don't block; dodge **every** attack with backstep/roll (backstep style — two-handed, no shield)
        self.bs_attack = False   # append a backstep attack (B → R1) when dodging (Style.bs_attack)
        self.reflex_on = True    # False = tick() only records (update), never moves — rush style: no block, no dodge, keep attacking
        self.events = None       # if layer 4 sets it, an 'evade' event per dodge (kind, distance, hit within the next 1.3 s) — counted by style_report.py
        self._pending: dict | None = None
        self.last_hit = None     # last backstep-attack result (duel takes it for logging)
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
                if c.hp > 0 and M.horiz(s.player, c) < THREAT_R and now - self._start.get(c.ptr, 0.0) < THREAT_S
                and (c.anim if c.anim is not None else -1) in M.ATTACK]

    def threat_now(self, s) -> bool:
        self.update(s)
        return bool(self.threats(s)) or (time.time() - self._hit_t < 0.4 and self._nearest(s, HIT_R) is not None)

    def _nearest(self, s, r: float):
        near = [c for c in s.hostile(r + 2.0) if c.hp > 0 and not (9000 <= (c.anim or 0) < 9100) and M.horiz(s.player, c) < r]
        return min(near, key=lambda c: M.horiz(s.player, c), default=None)

    def tick(self, s) -> bool:
        """→ whether the reflex moved this tick (shield, turning)."""
        self.update(s)
        if not self.reflex_on:
            return False         # rush: record only (attack_age etc.), no block or dodge — the attack loop isn't interrupted
        th = self.threats(s)
        now = time.time()
        lock_ptr, lock_until = self._lock
        c = next((x for x in th if x.ptr == lock_ptr), None) if now < lock_until else None
        if c is None and th:
            c = next((x for x in th if x.ptr == self.prefer), None) or min(th, key=lambda x: M.horiz(s.player, x))
            self._lock = (c.ptr, self._start.get(c.ptr, now) + THREAT_S)
        if c is None and time.time() - self._hit_t < 0.4:
            c = self._nearest(s, HIT_R)                    # 2) hit from an unknown source — nearest enemy
        if c is None:
            return False
        p = s.player
        start = self._start.get(c.ptr)
        evade_now = self.evade and M.horiz(p, c) <= EVADE_R          # dodge even with two — never use the shield (user)
        if evade_now and start is not None and now - start < EVADE_DELAY and self._dodged.get(c.ptr) != start:
            self.step_away(s, c)                           # too early — just face it and wait (dodge after the blade is committed so it can't track)
            self.acted += 1
            return True
        if c.anim is not None and start is not None and (evade_now or self.unblockable(c)):
            if self._dodged.get(c.ptr) != start:
                self._dodged[c.ptr] = start
                kind = self.dodge(s, c, attack=evade_now and self.bs_attack)
                self._pending = {"t": now, "kind": kind, "dist": round(M.horiz(p, c), 2), "eanim": c.anim, "npc": c.npc_param,
                                 "hp0": p.hp or 0, "min_hp": p.hp or 0}
            else:
                self.step_away(s, c)                       # once dodged, keep distance without shield for the rest of that attack
            self.acted += 1
            return True
        if (p.sp or 0) < GUARD_SP or self.evade:
            self.step_away(s, c)                       # backstep style: if we can't dodge (too far), just face it, no shield
            self.acted += 1
            return True
        self.mv.pad.guard(True)
        safe_turn = self.nm is None or nav.ground_ahead(self.nm, p, c.x - p.x, c.z - p.z, reach=0.8)
        if safe_turn:
            self.mv.face(s, c, deg=25.0)
        else:
            self.mv.pad.move(0.0, 0.0)
        self.acted += 1
        return True

    def _others_near(self, s, c) -> bool:
        return any(x.ptr != c.ptr and x.hp > 0 and x.anim not in (-1, None) and M.horiz(s.player, x) < MIXED_R for x in s.hostile(MIXED_R + 1))

    def dodge(self, s, c, attack: bool = False) -> str:
        """Unblockable attack — backstep if there is ground behind, else roll to a side with ground. If neither, guard (no choice)."""
        p = s.player
        if p.heading is not None and self.nm is not None:
            back = (math.sin(p.heading), math.cos(p.heading))          # heading direction = behind the body (same convention as hunt.backstep_attack)
            if nav.ground_ahead(self.nm, p, back[0], back[1], reach=2.6):
                if attack and self.bs_ok(c) and nav.ground_ahead(self.nm, p, -back[0], -back[1], reach=2.2):   # first hit lands near the start spot; 3.0 almost always fails on the ramp
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
