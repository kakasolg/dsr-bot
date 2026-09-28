"""Layer 3 — one opponent. Picks layer-1 actions from weapon usage (layer 2) and the enemy type (foes).
Returns only the result. Whether to drink Estus, quit out, or who to hit next is decided by layer 4 (field).

Order within one tick:
  1) it is swinging and within 4 m → raise shield and face it (don't trade hits)
  2) if it is knocked down, raise shield and wait
  3) out of reach (weapon reach, horizontal) or height differs by more than 1 m → follow a path to close in (climbs high ledges too)
  4) low stamina → shield
  5) face it: if a shield user is standing and looking at me, kick; otherwise per weapon (broadsword: 2 light attacks)
  0) (first) if layer 4 wants to drink: drink if there's an opening, if close, backstep to open distance
End conditions: kill · my death · my HP low · lost · no damage dealt for 15 s (stalemate) · timeout · cancel (escaping)
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

import nav

from . import foes as foes_
from . import moves as M

STALEMATE_S = 15.0       # no damage dealt this long within reach = stalemate — previously gave up on 'not dead after 6 hits' (kicks and blocked light attacks counted too)
NEAR = 4.0               # shield if it swings within this
KICK_COOLDOWN = 2.5
SEP_R = 4.0              # if the target and another awake foe are both within this, split them (_separate)
SEP_RUN = 5.0            # run this far — hollows (slow) and the shield soldier lunge (3–4.5 m/s) arrive staggered in time
SEP_COOLDOWN = 5.0       # so we don't just keep running
SEP_MAX = 3              # at most this many per fight
OPEN_R = 3.0             # Estus 'opening' mid-fight: it is knocked down, or not swinging and at least this far away
OTHERS_R, OTHERS_ATTACK_R = 5.0, 8.0   # and no other awake foe within 5 m, and none swinging within 8 m
CARE_RETRY = 3.0
FINISH_KEEP_HP = 40     # if its HP is below this, don't retreat even when my HP is low (down to 12 %) (after dark sign the shield soldier went 10 → 85)
FINISH_HP, FINISH_SP = 25, 15   # if its HP is within one light attack (measured 34–41), hit with as little as 15 stamina
HEAVY_SP = 100           # heavy attack in a stagger opening only at this stamina or more (one heavy while guarding costs 90)
INTERRUPT_STARTUP_MAX = 0.45   # weapons with startup longer than this (claymore 0.68 s) can't interrupt a foe that started swinging — only hit idle foes first.
                               # the battle axe had almost no delay and interrupted, but using the same rule with the claymore, the top damage source was hollow (254010) (2026-09-25)
INTERRUPT_S = 0.35       # if its attack started within this, hit first instead of blocking (the light attack lands sooner)
SWITCH_MARGIN, SWITCH_HOLD = 0.8, 3.0
SWITCH_R = 2.5           # if an awake foe closer than the target is within this (horizontal, same height), take it first
RANGED_SWITCH_R = 25.0   # if a thrower/shooter (foes.ranged) is swinging (throwing), take it first within this regardless of distance (user: "the one shooting arrows from above first")
RANGED_REACHABLE_DY = 3.0   # height difference above this = spot unreachable on foot, excluded from ranged switching (successful switches were all ≤ +3.0;
                            # at 4.0 it switched to a crossbowman on a +3.6 ledge, stuck 8 s and got hit by a nearby hollow, 2026-09-25 164722)
MELEE_BUSY_R = 2.0       # no ranged switch if a sword foe is within this (same height) — it went for a 15.8 m crossbowman with a hollow 0.9 m ahead
WAIT_APPROACH_S = 3.0    # wait_far: if it doesn't come WAIT_CLOSE_M closer in this time it won't come — stop waiting and close in
WAIT_CLOSE_M = 0.5
WAIT_HURT_HP = 120.0    # if this much HP is lost while waiting via wait_far — being hit by something other than the tracked (non-swinging) target, stop waiting
LEDGE_DY = 3.0           # don't lure it if it is this much above or below arena (it won't follow)
SWING_S = 1.6            # past this since the attack anim started, not considered swinging
PULL_R = 8.0             # lure: start backing off if it is within this (even if not moving)
SEEK_R = 100.0           # search for it within this radius — at 40 m it missed #1 at 42 m from the bonfire and everything was 'lost'
CIRCLE_MAX_SWEEPS = 2    # give up if not behind after this many (path blocked etc.) — normal attacks instead (prevents infinite loop)
# backstab — from 3 human demos (backstab_report.py, observe_backstab_*.jsonl, 2026-09-28): lock-on stays ON while circling (aim ≤ 6°),
# circling at body contact 0.85–0.96 m with the stick full (≥ 1.0, 2.5–3.9 m/s), behind within 0.6–1.1 s; R1 at 130–180° behind with the
# foe idle (anim −1) → the game snaps us behind (0.59 m) and the kill lands 0.8–0.9 s later. R1 while it's staggered/attacking = a normal hit.
# (the old _circle_sweep did a 3.5 s wide arc without lock-on — too slow, it turned to face us)
BACKSTAB_DEG = 130       # behind at least this much (deg from its front) → R1 (human R1s at 130–180°)
BACKSTAB_R = 0.9         # circle at this distance (human 0.85–0.96 m)
BACKSTAB_MAX_R = 1.7     # R1 only within this — 1.3 → 1.7 (27l: stood 139° behind an idle hollow at 1.6 m for 1.3 s without pressing R1)
BACKSTAB_REACH = 3.5     # start only within this (walk the rest while circling) — 2.5 → 3.5 (27j: idle hollows stood at 2.4–3 m, the bot waited, walked in head-on and woke them)
BACKSTAB_S = 2.5         # give up circling after this (human 0.6–1.1 s from contact; + walking in from BACKSTAB_REACH)
BACKSTAB_WATCH_S = 1.0   # after R1, watch this long for the kill (human 0.8–0.9 s)
BACKSTAB_TICK = 0.05
BACKSTAB_RELEASE_S = 0.1  # all input released this long before R1 (see stab())
SNEAK_R = 6.0            # a still hollow showing its back (≥ SNEAK_DEG) within this: walk straight in to its back, no circling
SNEAK_DEG = 110          # (radar 27k: circling never got past 6° — the hollow turns with us — but twice one stood 6 m off facing away 160–175°)
BACKSTAB_STILL_S = 0.3   # foe must have stood (moved < BACKSTAB_STILL_M) this long — a hollow walking in is also anim −1 and swings on arrival
BACKSTAB_STILL_M = 0.3   # distance to us dropped less than this (walking in ≈ 0.45 m per 0.3 s; 27h: 8/8 tries on walking-in hollows ended 'moved')


def backstab_stick(c, p) -> tuple[float, float, float]:
    """Stick (x, y) while locked on (x = strafe right +, y = forward) that circles p toward c's back. → (x, y, behind_deg).
    Player on the foe's right (rel_angle + ) → strafe left; distance corrected toward BACKSTAB_R."""
    ang = M.rel_angle(c, p)
    h = M.horiz(p, c)
    behind = abs(math.degrees(ang))
    if behind >= BACKSTAB_DEG:                             # already at its back — walk straight in (strafing would carry us off it)
        return 0.0, max(0.0, min(0.8, (h - BACKSTAB_R) * 1.5)), behind
    fwd = max(-0.5, min(0.8, (h - BACKSTAB_R) * 1.5))
    return (-1.0 if ang >= 0 else 1.0), fwd, behind


def _backstab(mv, s, c, cancel) -> str:
    """Lock on, strafe round at body contact, R1 once behind. → 'stabbed' | 'hit' (R1 landed but no kill) | 'moved' (it stopped
    being idle) | 'not_behind' (time out) | 'no_lock' | 'lost'. Always leaves the stick centered and lock-on off."""
    ptr, hp0 = c.ptr, c.hp

    def wait(t: float) -> None:                            # sleep but let Pad release the tapped buttons (R3/R1 are only scheduled to lift —
        t1 = time.time() + t                               # 27j: R3 left held after a no_lock try broke every later lock-on, 10 knife lures 'no_lock')
        while time.time() < t1:
            getattr(mv.pad, "release_due", lambda: None)()
            time.sleep(0.01)
    busy0, mv.cam_busy = getattr(mv, "cam_busy", False), True   # lock-on drives the camera — CamFollow hands off
    def stab() -> str:
        # let go of everything first — guard (LB) up or the stick held turns R1 into a normal attack. Human demos press R1 alone
        # (buttons 0x200, no LB); the bot held LB through the whole duel (0x100 → 0x180 at R1). user 2026-09-28: "behind it, all input
        # released for an instant — that is when the backstab registers"
        getattr(mv.pad, "guard", lambda on: None)(False)
        mv.pad.move(0.0, 0.0)
        wait(BACKSTAB_RELEASE_S)
        mv.pad.attack()
        c2 = None
        for _ in range(max(1, int(BACKSTAB_WATCH_S / max(BACKSTAB_TICK, 1e-3)))):
            wait(BACKSTAB_TICK)
            s2 = mv.snap(8.0)
            c2 = mv.find(s2, ptr) if s2 else None
            if c2 is None or c2.hp <= 0:
                return "stabbed"
        return "hit" if c2.hp < hp0 else "not_behind"

    def at_back(s_, c_) -> bool:
        return abs(math.degrees(M.rel_angle(c_, s_.player))) >= BACKSTAB_DEG and M.horiz(s_.player, c_) <= BACKSTAB_MAX_R

    try:
        if at_back(s, c):                                  # already at its back (e.g. it staggered while we stood) — R1 now; locking on
            return stab()                                  # first cost 0.25 s and then 'no_lock' threw the chance away (27m: 145° at 1.4 m)
        if mv.lock_state(ptr) != "target":
            mv.unlock()
            mv.pad.lock_on()
            wait(0.25)
            if mv.lock_state(ptr) != "target":
                s = mv.snap(8.0) or s
                c = mv.find(s, ptr) or c
                return stab() if at_back(s, c) else "no_lock"
        budget = max(BACKSTAB_S, M.horiz(s.player, c) / 1.5 + 1.0)   # walking in from SNEAK_R takes longer than a circle at contact
        for _ in range(max(1, int(budget / max(BACKSTAB_TICK, 1e-3)))):
            if cancel():
                return "lost"
            s = mv.snap(8.0)
            c = mv.find(s, ptr) if s else None
            if c is None:
                return "lost"
            if (c.anim if c.anim is not None else -1) != -1:
                return "moved"
            x, y, behind = backstab_stick(c, s.player)
            if behind >= BACKSTAB_DEG and M.horiz(s.player, c) <= BACKSTAB_MAX_R:
                return stab()
            mv.pad.move(x, y)
            wait(BACKSTAB_TICK)
        return "not_behind"
    finally:
        mv.pad.move(0.0, 0.0)
        wait(0.1)
        mv.unlock()
        wait(0.1)
        mv.cam_busy = busy0


def _pair_close(s, p, ptr, h: float) -> list:
    """Awake, moving foes other than the target within SEP_R (same height) — only when the target is also within SEP_R. Excludes idle (-1) and downed ones."""
    if h >= SEP_R:
        return []
    near = [x for x in s.hostile(SEP_R + 1.0) if x.hp > 0 and M.horiz(p, x) < SEP_R and abs(x.y - p.y) < 1.2
            and not (9000 <= (x.anim or 0) < 9100) and (x.anim or -1) not in M.DOWNED]
    # don't run if anyone is swinging (lunging) — the lunge (3005, 3–4.5 m/s) is faster than running, we got hit in the back:
    # turned and ran from a lunging shield soldier at 2.7 m, took −281 at +178° (observe 094231). Split only between attacks
    if any((x.anim or -1) in M.ATTACK for x in near):
        return []
    return [x for x in near if x.ptr != ptr]


def _separate(mv, s, ptr, others: list, nm, arena, cancel) -> str:
    """Split two foes coming in together (user 2026-09-26 (a)) — run SEP_RUN m away from their midpoint so they come one at a time.
    A hollow swung beside a shield soldier for −161, meanwhile light attacks cost stamina −5 → guard broken by shield soldier 3210 for −103 (observe 092612).
    Destination: only on the navmesh and reachable in an unbroken straight line (clear_line). arena if it's that way. Otherwise don't run.
    → 'arrived' | 'stopped' | 'no_spot' | …(walk_path values)"""
    p = s.player
    c = mv.find(s, ptr)
    group = [x for x in [c, *others] if x is not None]
    cx, cz = sum(x.x for x in group) / len(group), sum(x.z for x in group) / len(group)
    ax, az = p.x - cx, p.z - cz
    n = math.hypot(ax, az)
    if n < 0.3:                                            # caught between the two — go away from the target
        ax, az = p.x - c.x, p.z - c.z
        n = math.hypot(ax, az) or 1.0
    ax, az = ax / n, az / n
    cands = []
    if arena is not None:
        dx, dz = arena[0] - p.x, arena[2] - p.z
        da = math.hypot(dx, dz)
        if 2.0 < da < SEP_RUN + 4.0 and (dx * ax + dz * az) / da > 0.3:
            cands.append(tuple(arena))
    base = math.atan2(ax, az)
    for off in (0, 30, -30, 60, -60):
        t = base + math.radians(off)
        q = (p.x + math.sin(t) * SEP_RUN, p.y, p.z + math.cos(t) * SEP_RUN)
        w = nm.nearest_walkable(*q, r=1.5, dy=1.2) if nm is not None else None
        if w is not None:
            cands.append(w)
    here = (p.x, p.y, p.z)
    goal = next((g for g in cands if nm is not None and nm.clear_line(here, g)), None)
    if goal is None:
        return "no_spot"
    r = mv.walk_path([goal], nm, "walk", stop=lambda sn: cancel(), timeout_per=2.5)   # run → walk (evidence-grade gate, 2026-09-26)
    mv.guard(True)
    s2 = mv.snap(10.0)
    c2 = mv.find(s2, ptr) if s2 else None
    if c2 is not None:
        mv.face(s2, c2, deg=20.0)
    return r


GOAL_STALE_M = 3.0       # Patch E-2: while closing in, if it moves this far from where the path was planned, stop and re-decide
SHADOW_WINDOW = 1.5      # log the outcome (my HP·its HP change) this long after a shadow kick candidate


def _early_kick_candidate(foe, a: int, age, h: float, dy: float, sp: float, weapon, others_attacking: bool) -> bool:
    """Is this an early kick candidate — looks only at raw anim (foe.windup just started / STAGGER), distance, height, stamina, side attackers. No side effects
    (the mv.face() inside the old condition moved the body — that is now called separately only for 'act')."""
    if not foe.kick_when_idle or h > weapon.reach + 0.3 or abs(dy) > 1.0 or sp < weapon.sp_min or others_attacking:
        return False
    return (a in foe.windup and age is not None and age < foe.windup_act_s) or (foe.kick_on_stagger and a in M.STAGGER)


class ShadowKick:
    """Patch D — the early kick on raw anims 3004·3500 is unverified in meaning, so don't do it; only log candidate events.
    One event = one (handle, generation, anim, start time). After SHADOW_WINDOW, log an outcome event once more."""

    def __init__(self, log=print, events=None, gen=None):
        self.log, self.events, self.gen = log, events or (lambda *a, **k: None), gen
        self.seen: set = set()
        self.pending: list = []
        self._last: dict = {}                              # ptr → (anim, start time)

    def note_anim(self, ptr, anim: int, now: float) -> None:
        prev = self._last.get(ptr)
        if prev is None or prev[0] != anim:
            self._last[ptr] = (anim, now)

    def onset(self, ptr, anim: int, age, now: float) -> float:
        """When this anim **started being continuously seen** on this foe — now − age jitters per tick (±0.05 s), turning one 3004 into
        two events (observe 133016). age is kept only for logging."""
        last = self._last.get(ptr)
        return last[1] if last and last[0] == anim else now

    def observe(self, now, ptr, handle, npc, anim, age, h, dy, sp, max_sp, others_n, player_hp, target_hp) -> str | None:
        on = self.onset(ptr, anim, age, now)
        key = f"{handle}|g{self.gen}|{anim}|{on:.3f}"
        if key in self.seen:
            return None
        self.seen.add(key)
        ev = dict(key=key, handle=handle, gen=self.gen, ptr=ptr, npc=npc, anim=anim,
                  age=None if age is None else round(age, 2), h=round(h, 2), dy=round(dy, 2), sp=sp, max_sp=max_sp,
                  hostiles_4_5m=others_n, t=round(now, 2))
        self.log(f"      그림자 발차기 후보 (안 함) key={key} 애니 {anim} age {ev['age']} 거리 {ev['h']} m SP {sp}/{max_sp} 옆 {others_n}")
        self.events("shadow_kick", **ev)
        self.pending.append(dict(key=key, t=now, ptr=ptr, php=player_hp, thp=target_hp))
        return key

    def _emit(self, pe, now, s, cancelled: bool, truncated: bool) -> None:
        p = s.player if s is not None else None
        c = next((x for x in s.chars if x.ptr == pe["ptr"]), None) if s is not None else None
        out = dict(key=pe["key"], window_s=round(now - pe["t"], 2), truncated=truncated,
                   player_hp_delta=None if p is None or pe["php"] is None else p.hp - pe["php"],
                   target_hp_delta=None if c is None or pe["thp"] is None else c.hp - pe["thp"],
                   escape_or_cancel=cancelled, death=bool(p is not None and p.hp is not None and p.hp <= 0))
        self.log(f"      그림자 발차기 결과 key={out['key']} 내 HP {out['player_hp_delta']} 그놈 HP {out['target_hp_delta']}"
                 f"{' (잘림)' if truncated else ''}")
        self.events("shadow_kick_outcome", **out)

    def tick(self, now: float, s) -> None:
        for pe in [x for x in self.pending if now - x["t"] >= SHADOW_WINDOW]:
            self.pending.remove(pe)
            self._emit(pe, now, s, False, False)

    def flush(self, now: float, s, cancelled: bool) -> None:
        for pe in list(self.pending):
            self.pending.remove(pe)
            self._emit(pe, now, s, cancelled, True)


OTHER_SWING_R = 2.5      # another foe swinging within this (horizontal) → don't start our own attack, block
CROWD_R = 4.0            # awake foes within this count as "surrounded" for the retreat line
CROWD_LOW_HP = 0.45      # retreat line with ≥2 awake foes that close: two shield soldiers took 262 → 22 → dead in one exchange (P-8)


def _other_swinging(s, ptr) -> bool:
    """A foe other than ptr is mid-attack within OTHER_SWING_R."""
    p = s.player
    return any(x.ptr != ptr and (x.anim or -1) in M.ATTACK and M.horiz(p, x) < OTHER_SWING_R for x in s.hostile(OTHER_SWING_R + 2.0))


def _low_hp_line(s, low_hp: float) -> float:
    """HP fraction below which the duel ends with low_hp. Raised to CROWD_LOW_HP when ≥2 living, not-downed foes (target
    included) are within CROWD_R at our level. low_hp 0 (desperate, fight to the end) stays 0."""
    if low_hp <= 0:
        return low_hp
    p = s.player
    # standing foes count too: a shield soldier stands (anim -1) behind its raised shield
    n = sum(1 for x in s.hostile(CROWD_R + 1.0) if x.hp > 0 and M.horiz(p, x) < CROWD_R and abs(x.y - p.y) < 2.0
            and not (9000 <= (x.anim or 0) < 9100))
    return max(low_hp, CROWD_LOW_HP) if n >= 2 else low_hp


def _others_quiet(s, ptr) -> bool:
    for x in s.hostile(OTHERS_ATTACK_R):
        if x.ptr == ptr or 9000 <= (x.anim or 0) < 9100:
            continue
        if x.dist < OTHERS_R or (x.anim or -1) in M.ATTACK:
            return False
    return True


def opening(s, ptr) -> bool:
    """Is now an opening to drink — it is knocked down (not getting up), or not swinging and more than OPEN_R away, and the others are quiet."""
    c = next((x for x in s.chars if x.ptr == ptr), None)
    if c is None:
        return _others_quiet(s, ptr)
    a = c.anim if c.anim is not None else -1
    down = a in M.DOWNED and a != M.GETTING_UP
    return (down or (a not in M.ATTACK and M.horiz(s.player, c) >= OPEN_R)) and _others_quiet(s, ptr)


def _interloper(x, p, ptr, h: float) -> bool:
    """Is x an awake foe clearly closer than the target (at horizontal distance h), at our height — take it first?
    Standing foes (anim -1 / None) are asleep or idle and don't count: switching to one asleep on a ledge 1.2 m below
    left the edge guard blocking every step for 18 s, then 'stuck' (2026-09-27 burg-bonfire, ROADMAP P-6).
    If it wakes and closes in, it qualifies on a later tick."""
    return (x.ptr != ptr and x.hp > 0 and x.anim not in (-1, None) and not (9000 <= x.anim < 9100)
            and M.horiz(p, x) < min(SWITCH_R, h - SWITCH_MARGIN) and abs(x.y - p.y) < 1.2)


@dataclass
class DuelResult:
    result: str                      # killed | me_dead | low_hp | lost | stalemate | stuck | timeout | cancel
    npc: int | None = None
    vs: int | None = None            # npc actually fought last, when it switched away from the target (interloper / ranged first)
    secs: float = 0.0
    dealt: int = 0
    taken: int = 0
    hits: list = field(default_factory=list)

    def line(self) -> str:
        kinds = [h["kind"] + ("" if h["dmg"] else "×") for h in self.hits]
        vs = f" (실제 상대 {self.vs})" if self.vs is not None and self.vs != self.npc else ""
        return f"{self.result}{vs} — {self.secs:.0f} s, 준 피해 {self.dealt}, 받은 피해 {self.taken}, 공격 {' '.join(kinds) or '없음'}"


def _approach(mv: M.Moves, weapon, s, c, nm, foe, cancel, log=lambda *a: None, may_approach=None) -> str:
    """Follow a path to close in on it. Stops that tick once close / it starts swinging / cancelled.
    The path is planned to **its position at departure** — if it moves, re-plan after arriving (its position is logged every 1 s)."""
    p, ptr = s.player, c.ptr
    goal = (c.x, c.y, c.z)
    seen_t = [time.time()]
    path = nm.find_path((p.x, p.y, p.z), goal) if nm is not None else None
    if not path or len(path) < 2:
        if s.cam_yaw is None:
            return "no_cam"
        mv.pad.move(*mv.stick_to(s, c.x, c.z, 0.8))        # no path — just one step
        time.sleep(0.15)
        mv.pad.move(0.0, 0.0)
        return "step"
    path = nav.trim_path(path[1:], goal, within=weapon.reach)

    def stop(sn) -> bool:
        if cancel():
            return True
        cc = mv.find(sn, ptr)
        if time.time() - seen_t[0] >= 1.0:
            seen_t[0] = time.time()
            where = "30 m 밖(안 보임)" if cc is None else f"그놈 ({cc.x:.1f}, {cc.y:.1f}, {cc.z:.1f}) 애니 {cc.anim}, 거리 {M.horiz(sn.player, cc):.1f}"
            log(f"        붙는 중: 나 ({sn.player.x:.1f}, {sn.player.y:.1f}, {sn.player.z:.1f}) → 목표 {tuple(round(v, 1) for v in goal)} | {where}")
        if cc is None:
            return False          # goto's snapshot only holds 30 m — a far foe being invisible doesn't mean it's gone
        if cc.hp <= 0:
            return True
        # Patch E-2 (2026-09-26): if it moved more than GOAL_STALE_M from where the path was planned, stop and let duel re-decide from its current spot.
        # Previously it walked all the way to the departure spot, passing #3 coming down and climbing to its old spot up the ramp (observe 131752·132053·133827).
        if math.dist((cc.x, cc.y, cc.z), goal) > GOAL_STALE_M:
            return True
        if may_approach is not None and not may_approach(cc, sn):
            return True           # heading somewhere we must not approach — duel ends with 'unsafe_approach'
        d = M.horiz(sn.player, cc)
        if any(x.ptr != ptr and x.hp > 0 and not (9000 <= (x.anim or 0) < 9100) and M.horiz(sn.player, x) < SWITCH_R
               and abs(x.y - sn.player.y) < 1.2 for x in sn.hostile(SWITCH_R + 2.0)):
            return True           # another foe closed in while walking — stop and take it first (duel switches target)
        # with a large height difference (foe that won't come down, ledge we can't climb), stopping on just 'swinging + close' freezes us there — stop early
        # only within the height limit, otherwise follow the path to the end (the detour if any) (user 2026-09-25: "if you're going to stop mid-fight, go around",
        # "why are you staying in the danger zone" — measured: at 1.7–1.9 m height difference, 45 s+ of endless "붙기:stopped", 0 attacks)
        # shooters (foe.ranged) don't get "stop and block while swinging" — crossbowman 255002's 3000/3001 is always an aim/fire stance, so
        # it stopped every time 2–3 m away and never got into reach (1.8 m): 34 s, 0 attacks, 653 damage (2026-09-25 164722, user "you can't handle archers at all")
        return (d <= weapon.reach and abs(cc.y - sn.player.y) <= 1.0) or (
            not foe.ranged and (cc.anim or -1) in M.ATTACK and d < NEAR and abs(cc.y - sn.player.y) <= 1.2)

    def mode(sn) -> str:
        cc = mv.find(sn, ptr)                               # None beyond 30 m — then just walk
        if cc is not None and M.horiz(sn.player, cc) < NEAR:
            return "guard"                                  # when close, walk with shield raised
        # removed running at ranged foes (evidence-grade gate, 2026-09-26) — projectile arc unknown, running safety is only a NavMesh estimate
        # don't run if another foe is within 8 m — while running we can't block and get hit defenseless until it enters 2.5 m (SWITCH_R)
        # (user 2026-09-25: "trying to get the shooter, but you react slowly and get surrounded by other mobs") → walk with shield up
        return "guard" if foe.ranged else "walk"
    return mv.walk_path(path, nm, mode, stop, timeout_per=6.0)


PUNISH_AFTER = 1.1       # backstep style: the blade has passed only this long after the attack starts (8 of 11 entries within 1.0 s got hit, 1.0–1.3 s were 3/3 unhurt)
PUNISH_MIN_R = 1.8       # closer than this, leave it to reflex instead of punishing the whiff (5 of 7 entries at ≤1.6 m got hit by the next swing)
PUNISH_R = 1.6           # within reach + this, walk in and hit (with 0.9 it couldn't get in from 2.5 m for 6 s)


def duel(mv: M.Moves, weapon, ptr, nm, log=print, limit: float = 45.0, low_hp: float = 0.25,
         cancel=lambda: False, care=None, reflex=None, arena=None, style=None, wait_far: bool = False,
         gen=None, events=None, may_approach=None) -> DuelResult:
    """care: healing handler from layer 4 — care.wants(s) (wants to drink?), care.take(recheck) (drinks; recheck(s) rechecks the opening).
    Whether there's an opening is judged here (layer 3): opening(). If close, backstep to open distance and recheck next tick.
    reflex: reflex (souls/reflex.py) — first thing every tick. If it moved, this tick rests (it also blocks attacks from non-targets head-on).
    arena: a flat spot nearby — if footing is toward a cliff (nav.footing), back off there to receive it when it isn't swinging.
      User principle: "not being in a dangerous position in the first place comes first" — quit-out can't save a fall (the menu won't open while falling, 2026-09-24).
    wait_far: if out of reach, don't approach; block in place and wait — turn this on for foes that are walking in.
      User 2026-09-25: "it would come if you waited, why did you rush up and miss the chance" — walking toward a still-distant foe made others
      come along too, so what would have come alone had to be fought as a group at once (ramp, 0 damage/8 s, 493 taken, force-quit for being surrounded).
      Distinguish "when to wait and when to act" — let distant foes come, react only after they enter reach."""
    from . import style as style_
    style = style_.of(style or "guard")
    t0 = time.time()
    s0 = mv.snap()
    hp_start = s0.player.hp if s0 else 0
    res = DuelResult("timeout")
    last_dmg_t, kick_t = t0, 0.0
    sep_t, sep_n = 0.0, 0
    best_h, best_t = None, t0
    wait_t0, wait_hmin = 0.0, 0.0
    wait_hp0 = None                                         # HP when wait_far waiting began (to see if we're hit from elsewhere)
    last_seen, foe = None, None
    care_t, backstep_t, move_t = 0.0, 0.0, 0.0
    pulled = arena is None
    orig_ptr, switch_t = None, 0.0
    circle_n = 0                                            # attempts to circle behind (foe.circle_behind) — prevents infinite loop
    still = [None, 0.0, 0.0, 0.0]                          # [ptr, x, z, since] — where the foe last moved, for BACKSTAB_STILL_S
    acts: dict = {}                                        # what was done in 1 s (for logging)
    note_t = [t0]

    def note(act: str, s_, c_) -> None:
        """Count what was done per tick, one line per 1 s — so we can see where it gets stuck (2026-09-24: didn't know why it couldn't hit for 18 s at 4 m)."""
        acts[act] = acts.get(act, 0) + 1
        if time.time() - note_t[0] < 1.0:
            return
        note_t[0] = time.time()
        p_ = s_.player
        a_ = c_.anim if c_.anim is not None else -1
        line = (f"      [{time.time() - t0:4.1f}s] 거리 {M.horiz(p_, c_):.1f} 높이 {c_.y - p_.y:+.1f} 그놈 애니 {a_} HP {c_.hp} | "
                f"나 HP {p_.hp} SP {p_.sp} 애니 {p_.anim} 각 {math.degrees(M.rel_angle(p_, c_)) if p_.heading is not None else 0:+.0f}° | "
                + " ".join(f"{k}×{v}" for k, v in acts.items()))
        log(line)
        acts.clear()

    hp_min = [hp_start]

    shadow = ShadowKick(log=log, events=events, gen=gen)   # gen·events: supplied by Field.fight (for shadow kick events)

    def done(result: str) -> DuelResult:
        getattr(mv.pad, "guard", lambda on: None)(False)
        mv.pad.move(0.0, 0.0)
        s_ = mv.snap(5.0)
        shadow.flush(time.time(), s_, cancelled=(result == "cancel"))
        if s_ and s_.player.hp is not None:
            hp_min[0] = min(hp_min[0], s_.player.hp)
        res.result, res.secs = result, time.time() - t0
        if orig_ptr is not None and last_seen is not None:
            res.vs = last_seen.npc_param
        res.taken = max(0, hp_start - hp_min[0])          # based on lowest HP (so Estus drunk midway doesn't hide it)
        return res

    while True:
        if cancel():
            return done("cancel")
        now = time.time()
        if now - t0 > limit:
            return done("timeout")
        s = mv.snap(SEEK_R)
        if s is None:
            time.sleep(0.05)
            continue
        p = s.player
        if p.hp is not None:
            hp_min[0] = min(hp_min[0], p.hp)
        if p.hp is not None and p.hp <= 0:
            return done("me_dead")
        c = mv.find(s, ptr)
        if c is None:
            # dropped from the list — could be a corpse removed, or the pointer changed after a quit-out. If the same type is alive nearby, it's that one
            if last_seen is not None:
                again = [x for x in s.chars if x.npc_param == last_seen.npc_param and x.hp > 0
                         and math.dist((x.x, x.y, x.z), (last_seen.x, last_seen.y, last_seen.z)) < 3.0]
                if again:
                    ptr = again[0].ptr
                    continue
            if orig_ptr is not None and orig_ptr != ptr:   # the interloper vanished (died and removed) — back to the original target
                ptr, orig_ptr, last_seen = orig_ptr, None, None
                continue
            if last_seen is not None and res.hits and res.hits[-1]["dead"]:
                return done("killed")
            return done("lost")
        if c.hp <= 0:
            if orig_ptr is not None and orig_ptr != ptr:
                log(f"      끼어든 {c.npc_param} 처치 — 원래 목표로")
                ptr, orig_ptr = orig_ptr, None
                last_seen = None
                continue
            return done("killed")
        last_seen = c
        if res.npc is None:
            res.npc = c.npc_param
        # the foe data must follow whoever ptr is now. It used to be set once, so after "interloper killed — back to the
        # original target" a shield soldier kept the hollow's data and got hollow moves (먼저 치기 into the shield: dealt 4,
        # took 240, then died — 2026-09-27 burg-bonfire 27c, ROADMAP P-8)
        foe = foes_.of(c.npc_param)
        if p.hp < p.max_hp * _low_hp_line(s, low_hp) and not (c.hp <= FINISH_KEEP_HP and p.hp >= p.max_hp * 0.12):
            return done("low_hp")                          # don't retreat from an almost-dead foe — if we leave and return, a survivor's HP refills
        if now - last_dmg_t > STALEMATE_S:
            return done("stalemate")
        h, dy, a = M.horiz(p, c), c.y - p.y, (c.anim if c.anim is not None else -1)
        ranged_cut = [x for x in s.hostile(RANGED_SWITCH_R) if x.ptr != ptr and x.hp > 0
                      and foes_.of(x.npc_param).ranged and (x.anim or -1) in M.ATTACK
                      and abs(x.y - p.y) < RANGED_REACHABLE_DY]
        # shooters above (or far away), unlike close interlopers (cut, below), have no distance limit — we were getting hit while fighting only the
        # foe in front defensively (user 2026-09-25: "the arrow guy is attacking so it's set to defense-heavy — deal with him first").
        # But height difference is limited — switching to 254012 (terrace archer, height difference +6–8.5 m) made _approach() endlessly try to close
        # a distance unreachable on foot, taking only arrows for 30 s, HP 695→137 (2026-09-25, burg-loop 091110).
        # measured: successful ranged switches were all at height difference ≤ +3.0 m — above that, treat as unreachable and ignore.
        # if a sword foe is right in front (MELEE_BUSY_R), take it first — turning your back to go for a distant shooter gets you hit by both
        busy = any(x.hp > 0 and not foes_.of(x.npc_param).ranged and M.horiz(p, x) < MELEE_BUSY_R and abs(x.y - p.y) < 1.2
                   and not (9000 <= (x.anim or 0) < 9100) for x in s.hostile(MELEE_BUSY_R + 1.0))
        if ranged_cut and not busy and now - switch_t > SWITCH_HOLD:
            x = min(ranged_cut, key=lambda y: M.horiz(p, y))
            if orig_ptr is None:
                orig_ptr = ptr
            log(f"      원거리부터: {x.npc_param} ({M.horiz(p, x):.1f} m, 높이차 {x.y - p.y:+.1f}) — 원래 목표 {h:.1f} m")
            ptr, c, switch_t = x.ptr, x, now
            last_seen, foe = x, foes_.of(x.npc_param)
            h, dy, a = M.horiz(p, c), c.y - p.y, (c.anim if c.anim is not None else -1)
        cut = [x for x in s.hostile(SWITCH_R + 2.0) if _interloper(x, p, ptr, h)]
        # between two at similar distances it switched targets every 1–2 s, turning and getting hit in the back (±140–166°, 442 in 25 s) —
        # switch only when clearly closer (SWITCH_MARGIN), and keep it for SWITCH_HOLD after switching
        if cut and now - switch_t > SWITCH_HOLD:
            # interloper first (old hunt.py rule, user: "can't you attack the nearby enemy?") — watching only the map target, took 387 in 13 s from one hitting from the side and died.
            # after killing it, return to the original target
            x = min(cut, key=lambda y: M.horiz(p, y))
            if orig_ptr is None:
                orig_ptr = ptr
            log(f"      목표 바꿈: {x.npc_param} ({M.horiz(p, x):.1f} m, 애니 {x.anim}) — 원래 목표 {h:.1f} m")
            ptr, c, switch_t = x.ptr, x, now
            last_seen, foe = x, foes_.of(x.npc_param)
            h, dy, a = M.horiz(p, c), c.y - p.y, (c.anim if c.anim is not None else -1)

        if not (h > weapon.reach and wait_far):                 # if not waiting, also clear the waiting HP baseline
            wait_hp0 = None

        pair = _pair_close(s, p, ptr, h)
        if (pair and nm is not None and sep_n < SEP_MAX and now - sep_t > SEP_COOLDOWN and a not in M.STAGGER
                and a not in M.DOWNED and c.hp > FINISH_HP):
            # two closed in together — split them and take one at a time (user 2026-09-26 (a)). Don't run during stagger/downed (openings) or from a one-hit kill
            sep_t, sep_n = now, sep_n + 1
            r = _separate(mv, s, ptr, pair, nm, arena, cancel)
            log(f"      떼어놓기 {sep_n}: {c.npc_param}({h:.1f} m) + " + ", ".join(f"{x.npc_param}({M.horiz(p, x):.1f} m, {x.anim})" for x in pair)
                + f" → {r}")
            note(f"떼어놓기:{r}", s, c)
            if r != "no_spot":
                continue

        if (c.hp <= FINISH_HP and a not in M.ATTACK and h <= weapon.reach and abs(dy) <= 1.0
                and not (foe is not None and foe.kick_when_idle and a == -1)
                and (p.sp or 0) >= FINISH_SP and mv.face(s, c, deg=30.0)):
            # dies in one hit and isn't swinging now — hit before reflex (in front of an HP 18 foe, reflex just held the shield every tick and died)
            hit = mv.light(s, c, n=1)
            d = hit.as_dict()
            res.hits.append({k: d[k] for k in ("kind", "presses", "dmg", "dead", "taken", "others")})
            if hit.dmg > 0:
                last_dmg_t = time.time()
                res.dealt += hit.dmg
            note("마무리", s, c)
            if hit.dead and orig_ptr is None:
                return done("killed")
            continue
        if reflex is not None:
            reflex.prefer = ptr
            reflex.update(s)
        age = reflex.attack_age(ptr) if reflex is not None else None
        shadow.note_anim(ptr, a, now)
        shadow.tick(now, s)
        near45 = [x for x in s.hostile(4.5) if x.ptr != ptr]
        ek = getattr(foe, "early_kick", "off")
        cand = ek != "off" and _early_kick_candidate(
            foe, a, age, h, dy, p.sp or 0, weapon,
            any((x.anim or -1) in M.ATTACK and M.horiz(p, x) < 2.5 for x in near45))
        if cand and ek == "shadow":
            # Patch D: don't kick on raw anim alone — only log and fall through to the branches below (as if B8 never existed)
            shadow.observe(now, ptr, mv.tm.handle(ptr), c.npc_param, a, age, h, dy, p.sp, p.max_sp, len(near45), p.hp, c.hp)
        if cand and ek == "act" and mv.face(s, c, deg=30.0):
            # (experiment only, no Foe data enables it) kick one beat earlier (user 2026-09-26) — at the start of a slow-landing attack (3004),
            # or just as post-attack stagger (3500) begins. Checked before reflex and lure
            kick_t = now
            why = f"{a} {age:.2f}s" if a in foe.windup else f"휘청 {a}"
            hit = mv.kick_combo(s, c, n=foe.punish_hits or weapon.combo)
            d = hit.as_dict()
            res.hits.append({k: d[k] for k in ("kind", "presses", "dmg", "dead", "taken", "others")})
            if hit.dmg > 0:
                last_dmg_t = time.time()
                res.dealt += hit.dmg
            note("빠른발차기", s, c)
            log(f"      빠른 발차기({why}) → {hit.kind}×{hit.presses} 피해 {hit.dmg}, 내 피해 {hit.taken}, 그놈 애니 {hit.e_anims[:4]}")
            if hit.dead and orig_ptr is None:
                return done("killed")
            continue
        if a in foe.windup and age is not None and age >= foe.windup_act_s and h < NEAR:
            # too late — it lands soon (2.0–2.1 s after start). Treating it as 'standing' via SWING_S and kicking gets hit at that moment (−220·−323) → block
            mv.guard(True)
            mv.face(s, c)
            note("늦은windup막기", s, c)
            time.sleep(0.02)
            continue
        if a in M.ATTACK and age is not None and age > SWING_S:
            # if the 3000 series lasts beyond SWING_S it isn't swinging (it lingers 1.5–5.3 s after the attack ends — log analysis).
            # the spear shield soldier (255002) stays in 3001 holding up its shield, so for 15 s we only blocked at 1.4 m and never kicked
            a = -1
        if (foe.kind != "shield" and h <= weapon.reach
                and not (foe.circle_behind and res.dealt > 0 and a == -1 and circle_n < CIRCLE_MAX_SWEEPS) and abs(dy) <= 1.0 and (p.sp or 0) >= weapon.sp_min
                and (a == -1 or (a in M.ATTACK and age is not None and age < INTERRUPT_S
                                 and (weapon.startup or 0.0) <= INTERRUPT_STARTUP_MAX))
                and not _other_swinging(s, ptr)
                and mv.face(s, c, deg=30.0)):
            # hit first (user: "if you'd swung even once, that enemy would have backed off") — a hollow flinches (2000·2002) from one light attack and backs off.
            # when it has just started attacking (within INTERRUPT_S) or is standing still. Shield soldiers excluded (blocked by shield); if another foe swings beside us, block first
            hit = mv.light(s, c, n=weapon.combo, sp_second=weapon.sp_min)
            d = hit.as_dict()
            res.hits.append({k: d[k] for k in ("kind", "presses", "dmg", "dead", "taken", "others")})
            if hit.dmg > 0:
                last_dmg_t = time.time()
                res.dealt += hit.dmg
            note("먼저치기", s, c)
            log(f"      먼저 치기 → {hit.kind}×{hit.presses} 피해 {hit.dmg}, 옆 {hit.others}, 내 피해 {hit.taken}")
            if hit.dead and orig_ptr is None:
                return done("killed")
            continue
        if reflex is not None and reflex.tick(s):          # reflex: if anyone within 2.5 m starts swinging, block head-on
            bh = getattr(reflex, "last_hit", None)
            if bh is not None:                             # backstep attack (one move) result — record it
                reflex.last_hit = None
                d = bh.as_dict()
                res.hits.append({k: d[k] for k in ("kind", "presses", "dmg", "dead", "taken", "others")})
                if bh.dmg > 0:
                    last_dmg_t = time.time()
                    res.dealt += bh.dmg
                log(f"      백스텝 공격 → 피해 {bh.dmg}, 내 피해 {bh.taken} ({h:.1f} m) 내 애니 {bh.my_anims[:6]} 그놈 {bh.e_anims[:5]}")
                note("백스텝공격", s, c)
                if bh.dead and orig_ptr is None:
                    return done("killed")
                continue
            note("반사", s, c)
            time.sleep(0.02)
            continue
        ledge = arena is not None and abs(c.y - arena[1]) > LEDGE_DY
        # a foe standing on a ledge (ramp #5 y -39 vs flat ground -49) won't come down — luring to flat ground or backing off just went up and down repeatedly (three 'stuck')
        if (not pulled and not ledge and nm is not None and a not in M.ATTACK and (a != -1 or h < PULL_R)
                and math.dist((p.x, p.y, p.z), tuple(arena)) > 3.0):
            # 0--) lure (user: "drag it to the terrain you want") — once it notices (moves or is close), back off to arena.
            # ramp spot #2 is where firebombs from the ledge above land; engaging there took 275 in 1 s (2026-09-24)
            pulled = True
            path = nm.find_path((p.x, p.y, p.z), tuple(arena))
            if path:
                r = mv.walk_path(nav.trim_path(path[1:], tuple(arena), within=0.8), nm, "walk",
                                 stop=lambda sn: cancel() or any((x.anim or -1) in M.ATTACK and M.horiz(sn.player, x) < NEAR
                                                                 for x in sn.hostile(NEAR + 1.0)))
                note(f"끌어오기:{r}", s, c)
                continue
        if (nm is not None and a not in M.ATTACK and now - move_t > 3.0 and p.gx is not None
                and nav.footing(nm, p)[0] < nav.FOOTING_MIN):
            # 0-) next to a cliff — go to a flat spot (it follows). Without arena, one step toward the widest ground
            move_t = now
            if arena is not None and not ledge and math.dist((p.x, p.y, p.z), tuple(arena)) > 1.5:
                path = nm.find_path((p.x, p.y, p.z), tuple(arena))
                if path:
                    r = mv.walk_path(nav.trim_path(path[1:], tuple(arena), within=0.8), nm, "walk",
                                     stop=lambda sn: cancel() or any((x.anim or -1) in M.ATTACK and M.horiz(sn.player, x) < NEAR
                                                                     for x in sn.hostile(NEAR + 1.0)))
                    note(f"자리옮김:{r}", s, c)
                    continue
            # NavMesh only blocks — it doesn't choose a step toward 'the wider ground' (evidence-grade gate, 2026-09-26). At an edge, raise shield and face it
            mv.guard(True)
            mv.face(s, c, deg=20.0)
            note("가장자리방어", s, c)
            continue
        if care is not None and now - care_t > CARE_RETRY and care.wants(s):   # 0) Estus mid-fight (user: drink if safe)
            if opening(s, ptr):
                care_t = now
                r = care.take(lambda sn: opening(sn, ptr))
                log(f"      싸우는 중 에스트: {r}")
                note("에스트", s, c)
                continue
            if (a not in M.ATTACK and h < OPEN_R and now - backstep_t > 2.0 and p.heading is not None and _others_quiet(s, ptr)
                    and nav.ground_ahead(nm, p, math.sin(p.heading), math.cos(p.heading), reach=2.2)):
                backstep_t = now                           # close — if there's ground behind, backstep to open distance
                mv.backstep()
                note("백스텝", s, c)
                continue

        if (a in M.STAGGER or a == M.GUARD_BROKEN) and h <= weapon.reach + 0.3 and abs(dy) <= 1.0 and (p.sp or 0) >= weapon.sp_min \
                and not _other_swinging(s, ptr):
            # not while another foe is swinging next to us — punishing the staggered shield soldier took -115 from a hollow's 3003
            # 1.2 m away (dealt 4, 2026-09-27 27c P-8); the reflex blocks that swing instead and the stagger is taken next time
            # 1-) stagger = opening. If facing is right, hit at once (right after bouncing off the guard — old note "3500 stagger — if close, hit immediately")
            if mv.face(s, c, deg=30.0):
                # heavy attack in a shield soldier's stagger opening (user 2026-09-25: "guard·heavy·guard is better against strong-guard enemies") — heavy while guarding
                # costs 90 stamina, so only when full (HEAVY_SP). kind is logged to compare damage with light attacks
                if weapon.heavy_punish and foe.kind == "shield" and (p.sp or 0) >= HEAVY_SP:
                    hit = mv.heavy(s, c)
                else:
                    hit = mv.light(s, c, n=foe.punish_hits or weapon.combo, sp_second=weapon.sp_min)
                d = hit.as_dict()
                res.hits.append({k: d[k] for k in ("kind", "presses", "dmg", "dead", "taken", "others")})
                if hit.dmg > 0:
                    last_dmg_t = time.time()
                    res.dealt += hit.dmg
                note("휘청반격", s, c)
                log(f"      휘청 → {hit.kind}×{hit.presses} 피해 {hit.dmg}, 옆 {hit.others}, 내 피해 {hit.taken}")
                if hit.dead and orig_ptr is None:
                    return done("killed")
            else:
                note("휘청돌기", s, c)
            continue
        if style.evade and a in M.ATTACK and h < NEAR:
            # 1b) backstep style (user 2026-09-24: "experts use backsteps well, backstep + light attack, stronger two-handed, and no guard stamina used")
            #     reflex dodged the swing start with a backstep (when there's ground behind). Once the blade has passed (PUNISH_AFTER), step in and light attack.
            if (age is not None and age >= style.punish_after and style.punish_min_r <= h <= weapon.reach + PUNISH_R and abs(dy) <= 1.0
                    and (p.sp or 0) >= weapon.sp_min and mv.face(s, c, deg=30.0)):
                if h > weapon.reach and s.cam_yaw is not None:
                    mv.pad.move(*mv.stick_to(s, c.x, c.z, 0.8))
                    time.sleep(min(0.45, 0.12 + (h - weapon.reach) * 0.22))   # 2.5 m/s walk — for the remaining distance
                    mv.pad.move(0.0, 0.0)
                hit = mv.light(s, c, n=weapon.combo, sp_second=weapon.sp_min)
                d = hit.as_dict()
                res.hits.append({k: d[k] for k in ("kind", "presses", "dmg", "dead", "taken", "others")})
                if hit.dmg > 0:
                    last_dmg_t = time.time()
                    res.dealt += hit.dmg
                note("뒤치기", s, c)
                log(f"      헛친 뒤 → {hit.kind}×{hit.presses} 피해 {hit.dmg}, 내 피해 {hit.taken} ({h:.1f} m, {age:.2f} s)")
                if hit.dead and orig_ptr is None:
                    return done("killed")
                continue
            mv.guard(False)
            mv.face(s, c, deg=25.0)                        # keep it in front and wait for the blade to pass (no shield)
            note("피함대기", s, c)
            time.sleep(0.02)
            continue
        if style.shield and a in M.ATTACK and h < NEAR:     # 1) swinging → block (only styles with a shield —
            # rush (no shield, no evade) just stood here taking hits, the enemy combo never broke: 8 s+ 0 attacks, 676 taken, 2026-09-25)
            mv.guard(True)
            if h > weapon.reach + 0.3 and abs(dy) <= 1.0 and s.cam_yaw is not None and (
                    nm is None or nav.ground_ahead(nm, p, c.x - p.x, c.z - p.z, reach=0.8)):
                # just blocking in place out of reach never reaches a foe swinging from afar (3008 repeated) — approach with shield raised
                mv.pad.move(*mv.stick_to(s, c.x, c.z, 0.6))
                note("막으며다가감", s, c)
            else:
                mv.face(s, c)
                note("막기", s, c)
            time.sleep(0.02)
            continue
        if a in M.DOWNED and a != M.GETTING_UP:            # 2) knocked down
            mv.guard(True)
            mv.face(s, c)
            note("누움대기", s, c)
            time.sleep(0.03)
            continue
        # an idle hollow within backstab range is a backstab chance, not a reason to wait (user 2026-09-28: "never even tries" —
        # 27g: idle foe at 1.7–2.2 m, the bot just blocked and waited, so the backstab check below was never reached)
        # "still" = not closing in: the distance hasn't dropped by BACKSTAB_STILL_M since the anchor. Position-based, the anchor reset
        # every tick (27o: never past 0.2 s) though recordings show idle hollows not moving — the positions the duel reads jitter
        if still[0] != c.ptr or a != -1 or still[1] - h > BACKSTAB_STILL_M:
            still[:] = [c.ptr, h, 0.0, now]
        foe_still = now - still[3] >= BACKSTAB_STILL_S
        back_to_me = c.heading is not None and abs(math.degrees(M.rel_angle(c, p))) >= SNEAK_DEG
        bs_near = h <= BACKSTAB_REACH or (back_to_me and h <= SNEAK_R)
        foe_still = True                                      # user 2026-09-28: hollows never stand still for a backstab — not a condition
        backstab_chance = (foe is not None and foe.circle_behind and a == -1 and foe_still and circle_n < CIRCLE_MAX_SWEEPS
                           and bs_near and abs(dy) <= 1.0)
        if backstab_chance and not (not _other_swinging(s, ptr) and (nm is None or nav.ground_ahead(nm, p, c.x - p.x, c.z - p.z, reach=1.0))):
            note("뒤잡기안함:" + ("옆공격" if _other_swinging(s, ptr) else "바닥"), s, c)   # passes the chance test but not the trigger below
        if not backstab_chance and foe is not None and foe.circle_behind and a == -1 and h <= BACKSTAB_REACH + 0.5:
            why = (f"안멈춤({now - still[3]:.1f}s)" if not foe_still else "횟수" if circle_n >= CIRCLE_MAX_SWEEPS else "멀다" if h > BACKSTAB_REACH
                   else "높이" if abs(dy) > 1.0 else "?")
            note(f"뒤잡기안함:{why}", s, c)                   # why an idle hollow close by was not backstabbed (27i: 1 try in a whole run)
        if h > weapon.reach and wait_far and not (foe and foe.ranged) and not backstab_chance:   # 3-wait) shooters keep shooting if we wait — don't wait. Still far — don't approach, block in place and wait
            if wait_hp0 is None:
                wait_hp0 = p.hp
                wait_t0, wait_hmin = now, h
            if h < wait_hmin - WAIT_CLOSE_M:
                wait_t0, wait_hmin = now, h                  # approaching — keep waiting
            elif now - wait_t0 > WAIT_APPROACH_S and may_approach is not None and not may_approach(c, s):
                # Patch E-3 (2026-09-26): if approaching would leave the safe zone or get near the shield soldier spawn, don't switch 'not coming→close in';
                # keep waiting — going for #3 standing 6.4 m out at the edge of the flat ground, got spotted 6.6 m from the shield soldier spawn and surrounded (133827)
                wait_t0 = now
                note("안옴→기다림유지", s, c)
            elif now - wait_t0 > WAIT_APPROACH_S:
                # waiting for a foe that won't approach never ends: shield soldier 255002 held guard (3000/3001) at 4.6 m while the bot just blocked,
                # 15 s stalemate → repeated stalemate with the same foe (user 2026-09-25: "the enemy is right in front and you just guard and wait")
                wait_far = False
                note("안옴→붙기", s, c)
                continue
            elif p.hp is not None and wait_hp0 - p.hp > WAIT_HURT_HP:
                # the tracked foe isn't swinging (a not in M.ATTACK, not approaching) but HP keeps dropping — means we're being hit by another.
                # don't sit still thinking "waiting is safe" (user 2026-09-25: "the enemies lull you and raise the danger,
                # this game is never easy" — measured: waiting 11 s in front of a non-swinging target 4.3 m away, dropped 490→242).
                return done("low_hp")
            if style.shield:
                mv.guard(True)
            mv.face(s, c)
            note("기다림", s, c)
            time.sleep(0.03)
            continue
        if h > weapon.reach and not backstab_chance:        # 3) close in — if horizontally within reach, height difference alone doesn't enter here (a backstab chance circles in itself)
            # (user 2026-09-25: "if you're going to stop midway, at least swing light attacks while stopped" — even when height difference prevents closing,
            # drop to below (attack attempt) and at least swing a light attack. Previously even with h<=reach, dy>1.0 kept trying to close in here,
            # 8 s+ of 0 attacks while getting beaten.)
            last_dmg_t = now                               # stalemate counts only within reach (walking 42 m counted as 'stalemate')
            # treating "within 3 m horizontally = not stuck" meant for a foe that won't come down (large height difference only) h stayed <3,
            # best_t refreshed every tick and stuck never triggered (measured 2026-09-25: 45 s+ of repeated "붙기:stopped" at 1.7–1.9 m height difference,
            # 0 attacks — user: "if you're going to stop mid-fight, go around", "why are you staying in the danger zone"). Count progress only when height difference narrows too.
            if h < 3.0 and abs(dy) <= 1.2:
                best_h, best_t = h, now                    # truly within reach (height too) — not stuck
            elif best_h is None or h < best_h - 0.5:
                best_h, best_t = h, now
            elif now - best_t > 8.0:
                return done("stuck")
            if may_approach is not None and not may_approach(c, s):
                log(f"      다가가지 않음 — {c.npc_param} ({c.x:.1f}, {c.y:.1f}, {c.z:.1f}) 는 안전 구역 밖 (Patch E-2)")
                return done("unsafe_approach")
            r = _approach(mv, weapon, s, c, nm, foe, cancel, log, may_approach=may_approach)
            last_dmg_t = time.time()                       # time spent closing in isn't stalemate (one walk took 17 s)
            note(f"붙기:{r}", s, c)
            if r == "dead":
                return done("me_dead")
            continue
        if (c.hp <= FINISH_HP and (p.sp or 0) >= FINISH_SP and not (foe.kick_when_idle and a == -1)
                and mv.face(s, c, deg=30.0)):   # a shield soldier standing with shield up blocks even the finisher (22 → 21 → 20, 114 counter) — kick instead
            # 3+) dies in one hit — hit even if a bit short on stamina (guard broke while a shield soldier held out 4 s at HP 10)
            hit = mv.light(s, c, n=1)
            d = hit.as_dict()
            res.hits.append({k: d[k] for k in ("kind", "presses", "dmg", "dead", "taken", "others")})
            if hit.dmg > 0:
                last_dmg_t = time.time()
                res.dealt += hit.dmg
            note("마무리", s, c)
            if hit.dead and orig_ptr is None:
                return done("killed")
            continue
        if (p.sp or 0) < weapon.sp_min:                    # 4) stamina — lower shield (recovery −80 %, wiki) and stand keeping it in front
            # backing off pushed the stick the other way without lock-on, **turning and walking away**, getting hit in the back (body-foe ±180°, user: "can't align direction")
            mv.guard(False)
            mv.face(s, c)
            note("SP회복", s, c)
            time.sleep(0.05)
            continue
        if not mv.face(s, c):                              # 5) face it
            note("돌기", s, c)
            time.sleep(0.02)
            continue
        s = mv.snap(SEEK_R)
        c = mv.find(s, ptr) if s else None
        if c is None:
            continue
        a = c.anim if c.anim is not None else -1
        if a in M.ATTACK and reflex is not None and (reflex.attack_age(ptr) or 0.0) > SWING_S:
            a = -1                                         # 3000 series lingering in guard stance — treat as standing (kick)
        behind_deg = abs(math.degrees(M.rel_angle(c, s.player))) if c.heading is not None else 0.0
        looks_at_me = behind_deg < 60
        if (foe.circle_behind and a == -1 and foe_still and circle_n < CIRCLE_MAX_SWEEPS and bs_near and abs(dy) <= 1.0
                and not _other_swinging(s, ptr)
                and (nm is None or nav.ground_ahead(nm, p, c.x - p.x, c.z - p.z, reach=1.0))):
            # idle → circle behind with lock-on and backstab (human demos, see BACKSTAB_*). Past CIRCLE_MAX_SWEEPS tries, normal attacks
            circle_n += 1
            r = _backstab(mv, s, c, cancel)
            note(f"뒤잡기:{r}", s, c)
            log(f"      뒤잡기 → {r}")
            if r == "stabbed" and orig_ptr is None:
                return done("killed")
            continue
        circle_n = 0
        if foe.kick_when_idle and a == -1 and looks_at_me and now - kick_t > KICK_COOLDOWN:
            kick_t = now
            hit = mv.kick_combo(s, c, n=weapon.combo)       # kick → light attack right away (if the gap is large the shield soldier guards again, user)
        elif weapon.use_heavy:
            hit = mv.heavy(s, c)
        else:
            hit = mv.light(s, c, n=weapon.combo, sp_second=weapon.sp_min)
        d = hit.as_dict()
        res.hits.append({k: d[k] for k in ("kind", "presses", "dmg", "dead", "taken", "others")})
        if hit.dmg > 0:
            last_dmg_t = time.time()
            res.dealt += hit.dmg
        note(hit.kind, s, c)
        log(f"      {hit.kind}×{hit.presses} → 피해 {hit.dmg}, 내 피해 {hit.taken}, 그놈 애니 {hit.e_anims[:4]}")
        if hit.dead and orig_ptr is None:
            return done("killed")
