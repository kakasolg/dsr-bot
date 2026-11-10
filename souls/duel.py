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

import control
import ctl
import ctlspan as CS
import nav

from . import combo_table as CTB
from . import counter_trace as CT
from . import foes as foes_
from . import moves as M
from . import reflex as R
from . import swing_windows as SW

STALEMATE_S = 15.0       # no damage dealt this long within reach = stalemate — previously gave up on 'not dead after 6 hits' (kicks and blocked light attacks counted too)
NEAR = 4.0               # shield if it swings within this
KICK_COOLDOWN = 2.5
SEP_R = 4.0              # if the target and another awake foe are both within this, split them (_separate)
SEP_RUN = 5.0            # run this far — hollows (slow) and the shield soldier lunge (3–4.5 m/s) arrive staggered in time
SEP_COOLDOWN = 5.0       # so we don't just keep running
SEP_MAX = 3              # at most this many per fight
SEP_ESCAPE = True        # no straight-line spot → back off along the NavMesh toward where the foes are not (souls/escape.pick) —
                         # 74 of 112 splits in data/samples ended 'no_spot' and stood there (10-11 video review, 10-03e stairs 255000 ×2)
SEP_ESCAPE_M = 7.0       # … walking at most this much of its path
OPEN_R = 3.0             # Estus 'opening' mid-fight: it is knocked down, or not swinging and at least this far away
OTHERS_R, OTHERS_ATTACK_R = 5.0, 8.0   # and no other awake foe within 5 m, and none swinging within 8 m
CARE_RETRY = 3.0
FINISH_KEEP_HP = 40     # if its HP is below this, don't retreat even when my HP is low (down to 12 %) (after dark sign the shield soldier went 10 → 85)
FINISH_HP, FINISH_SP = 25, 15   # if its HP is within one light attack (measured 34–41), hit with as little as 15 stamina
THIRD_REACH_SLACK = 0.0  # _third only within reach — at +0.3 it swung at 1.8 m into a foe staggered back and missed (10-03f)
SINGLE_HIT_R = 6.0       # hit first: another foe (awake or lying still) this close → one light, then the shield (P-39 (A))
HEAVY_SP = 100           # heavy attack in a stagger opening only at this stamina or more (one heavy while guarding costs 90)
WALL_R = 1.2             # a NavMesh border (wall or drop) this close to us or the foe → heavy_vertical weapons slam instead of the light
LOSING_TAKEN = 0.35       # taken this share of max HP in this fight …
LOSING_DEALT = 0.5        # … while dealing less than this share of the foe's max HP → end 'losing' (Field backs off, heals, comes back)
NO_BACKSTAB_N = 2        # this many on us (target + moving others within CROWD_R) → no backstab circling, light + shield (2:1, MoKa 2026-10-01)
WALL_BACK_N = 3          # this many on us (target + moving others within CROWD_R) → back to a wall, one at a time (P-29)
WALL_AT = 1.2            # already this close to a wall (Navmesh.wall_dist) → stay and fight
WALL_HEAVY_SP = 60       # …when stamina is at least this (Battle Axe heavy −50, −20 more if it hits the ground)
INTERRUPT_STARTUP_MAX = 0.45   # weapons with startup longer than this (claymore 0.68 s) can't interrupt a foe that started swinging — only hit idle foes first.
                               # the battle axe had almost no delay and interrupted, but using the same rule with the claymore, the top damage source was hollow (254010) (2026-09-25)
INTERRUPT_S = 0.35       # if its attack started within this, hit first instead of blocking (the light attack lands sooner)
SWITCH_MARGIN, SWITCH_HOLD = 0.8, 3.0
SWITCH_R = 2.5           # if an awake foe closer than the target is within this (horizontal, same height), take it first
RANGED_SWITCH_R = 25.0   # if a thrower/shooter (foes.Foe.thrower) is swinging (throwing), take it first within this regardless of distance (user: "the one shooting arrows from above first")
RANGED_REACHABLE_DY = 3.0   # height difference above this = spot unreachable on foot, excluded from ranged switching (successful switches were all ≤ +3.0;
                            # at 4.0 it switched to a crossbowman on a +3.6 ledge, stuck 8 s and got hit by a nearby hollow, 2026-09-25 164722)
MELEE_BUSY_R = 2.0       # no ranged switch if any awake foe is within this (same height) — it went for a 15.8 m crossbowman with a hollow 0.9 m ahead;
                         # P-56: 'sword foe' read foes.ranged, so the axe hollow 0.9 m ahead didn't count and the bot turned to 254002
# ranged-first switch safety (P-121, _switch_threat) — 셋 다 측정 전 가설 (try 27 한 장면에서 잡은 값, 게임 측정 없음)
SAFE_SWITCH_NEAR_R = 2.5     # 가설: 이 안(같은 높이)에 깨어 있는 놈이 있으면 원거리로 안 바꿈
SAFE_SWITCH_CLEAR_R = 4.0    # 가설: 이 안에서 SAFE_SWITCH_RECENT_S 안에 휘두른 놈도 위협 — 이 밖으로 나가면 해소
SAFE_SWITCH_RECENT_S = 3.0   # 가설
WAIT_APPROACH_S = 3.0    # wait_far: if it doesn't come WAIT_CLOSE_M closer in this time it won't come — stop waiting and close in
WAIT_CLOSE_M = 0.5
WAIT_HURT_HP = 120.0    # if this much HP is lost while waiting via wait_far — being hit by something other than the tracked (non-swinging) target, stop waiting
LEDGE_DY = 3.0           # don't lure it if it is this much above or below arena (it won't follow)
TARGET_DROP_DY = 2.5     # a target more than this below us (or falling) ends the duel 'lost' — = field.FOLLOW_DY (P-69)
SWING_S = 1.6            # past this since the attack anim started, not considered swinging — except a windup that hasn't landed (swing_over)
LAND_PAD = 0.2           # a windup (foes.Foe.windup_land_s) counts as landed this long after its measured landing time
AFTER_SWING_S = 0.6      # rule_after_swing: right after its swing ends, this long to strike ([MoKa] '끝나면 무조건 공격')
AFTER_SWING_DEG = 45.0   # …strike at once if aimed within this (turn first only beyond it)
AFTER_SWING_STEP = 1.2   # …and step in if it's at most this much beyond our reach
PULL_R = 8.0             # lure: start backing off if it is within this (even if not moving)
SEEK_R = 100.0           # search for it within this radius — at 40 m it missed #1 at 42 m from the bonfire and everything was 'lost'
CIRCLE_MAX_SWEEPS = 2    # tries per foe before normal attacks (99 during the 2026-09-28 "backstab no matter what" runs)
BACK_CHECK_M = (0.5, 1.0, 1.5, 2.0)   # floor checked this far behind the foe (_room_behind)
FOOT_R = 1.0            # after a backstab: floor this far round us, or step back to where we started it
BACKSTAB = True          # False (run.py --basic): no backstab tries at all — shield + light only ([MoKa] 2026-10-01: "뒤잡기를 임시로 하지 말고,
                         # 방패, 약공 플레이로 새로 시작해봐" — the backstab rules took over guarding: no guard while closing in on an idle foe,
                         # no block when it swung within 2 m; with the Battle Axe 8/8 swing-backstabs were normal hits)
HEAVY = True             # False (run.py --basic): no wall heavy / two-hand switch either
LOCK_KEEP = True         # False: no lock-on keeping in 1:1 fights (the old way — lock only for backstab / throws)
LOCK_KEEP_R = 8.0        # keep lock-on on the target within this (horizontal) …
LOCK_KEEP_DY = 2.0       # … and this height difference
LOCK_KEEP_CAM_DEG = 15.0 # R3 when the camera is within this of the target — wider than a throw's M.LOCK_CAM_DEG (6°): in 1:1 there is
                         # no neighbour for R3 to grab, and CamFollow keeps the fight camera within ~10° (9 of 10 ticks); at 6° the
                         # keeper never pressed again after a backstab try (074829 zone 1-3: camera 13°, the hit went out unlocked)
LOCK_RETRY_S = 1.0       # after an R3, wait this long before the next — the game needs ~0.3 s, and an R3 that finds nothing
                         # resets the camera behind the body, so pressing every tick would spin the camera
BACKSTAB_ONLY = False    # True: against hollows only the backstab (no hit-first, no stagger punish). Off: backstab when the checks allow it, else the usual rules (user 2026-09-28)
# backstab — from 3 human demos (backstab_report.py, observe_backstab_*.jsonl, 2026-09-28): lock-on stays ON while circling (aim ≤ 6°),
# circling at body contact 0.85–0.96 m with the stick full (≥ 1.0, 2.5–3.9 m/s), behind within 0.6–1.1 s; R1 at 130–180° behind with the
# foe idle (anim −1) → the game snaps us behind (0.59 m) and the kill lands 0.8–0.9 s later. R1 while it's staggered/attacking = a normal hit.
# (the old _circle_sweep did a 3.5 s wide arc without lock-on — too slow, it turned to face us)
BACKSTAB_DEG = 140       # behind at least this much (deg from its front) → R1 — drill: kills at 151°·153° (1.12 m), 133° at 1.50 m was a normal hit
BACKSTAB_R = 0.9         # circle at this distance (human 0.85–0.96 m)
BACKSTAB_MAX_R = 1.3     # R1 only within this — drill: 1.12 m killed, 1.50 m was a normal hit (human 0.85 m)
BACKSTAB_REACH = 3.5     # start only within this (walk the rest while circling) — 2.5 → 3.5 (27j: idle hollows stood at 2.4–3 m, the bot waited, walked in head-on and woke them)
BACKSTAB_S = 2.5         # give up circling after this (human 0.6–1.1 s from contact; + walking in from BACKSTAB_REACH)
BACKSTAB_WATCH_S = 1.0   # after R1, watch this long for the kill (human 0.8–0.9 s)
BACKSTAB_TICK = 0.05
BACKSTAB_RELEASE_S = 0.1  # all input released this long before R1 (see stab())
SNEAK_R = 6.0            # a still hollow showing its back (≥ SNEAK_DEG) within this: walk straight in to its back, no circling
SNEAK_DEG = 110          # (radar 27k: circling never got past 6° — the hollow turns with us — but twice one stood 6 m off facing away 160–175°)
BACKSTAB_STILL_S = 0.3   # foe must have stood (moved < BACKSTAB_STILL_M) this long — a hollow walking in is also anim −1 and swings on arrival
BACKSTAB_STILL_M = 0.3   # distance to us dropped less than this (walking in ≈ 0.45 m per 0.3 s; 27h: 8/8 tries on walking-in hollows ended 'moved')


def backstab_stick(c, p, side: float | None = None) -> tuple[float, float, float]:
    """Stick (x, y) while locked on (x = strafe right +, y = forward) that circles p toward c's back. → (x, y, behind_deg).
    Player on the foe's right (rel_angle + ) → strafe left; distance corrected toward BACKSTAB_R."""
    ang = M.rel_angle(c, p)
    h = M.horiz(p, c)
    behind = abs(math.degrees(ang))
    if behind >= BACKSTAB_DEG:                             # already at its back — walk straight in (strafing would carry us off it)
        return 0.0, max(0.0, min(0.8, (h - BACKSTAB_R) * 1.5)), behind
    fwd = max(-0.5, min(0.8, (h - BACKSTAB_R) * 1.5))
    # side: keep the strafe direction chosen at the start — right in front (≈0°) the sign flipped every tick (drill 4: 2.5 s lost)
    return (side if side is not None else (-1.0 if ang >= 0 else 1.0)), fwd, behind


def _backstab(mv, s, c, cancel, nm=None, log=None) -> str:
    """Lock on, strafe round at body contact, R1 once behind. → 'stabbed' | 'hit' (R1 landed but no kill) | 'moved' (it stopped
    being idle) | 'not_behind' (time out) | 'no_lock' | 'lost'. Always leaves the stick centered; lock-on off unless it was
    already on the target when we came in (_keep_lock's — releasing it cost the next hit its lock, 074829 zone 1-3)."""
    ptr, hp0 = c.ptr, c.hp
    held = getattr(mv, "lock_state", lambda p: "none")(ptr) == "target"

    def wait(t: float) -> None:                            # sleep but let Pad release the tapped buttons (R3/R1 are only scheduled to lift —
        t1 = time.time() + t                               # 27j: R3 left held after a no_lock try broke every later lock-on, 10 knife lures 'no_lock')
        while time.time() < t1:
            getattr(mv.pad, "release_due", lambda: None)()
            time.sleep(0.01)
    busy0 = vars(mv).get("cam_busy", False)           # vars(): test fakes raise on unknown attributes
    mv.cam_busy = True                                     # lock-on drives the camera — CamFollow hands off
    def stab(s0=None, c0=None) -> str:
        # let go of everything first — guard (LB) up or the stick held turns R1 into a normal attack. Human demos press R1 alone
        # (buttons 0x200, no LB); the bot held LB through the whole duel (0x100 → 0x180 at R1). user 2026-09-28: "behind it, all input
        # released for an instant — that is when the backstab registers"
        getattr(mv.pad, "guard", lambda on: None)(False)
        mv.pad.move(0.0, 0.0)
        t0 = time.time()
        wait(BACKSTAB_RELEASE_S)
        mv.pad.attack()
        if log is not None and s0 is not None and c0 is not None:
            # where it was when we decided vs right after R1 went in — MoKa 2026-10-01: with the Battle Axe the backstab misses
            # its timing (a delay), not the weapon. This shows how far the foe turned / we drifted during the release + R1.
            s1 = mv.snap(8.0)
            c1 = mv.find(s1, ptr) if s1 else None
            if c1 is not None:
                log(f"      뒤잡기 R1: 판정 {abs(math.degrees(M.rel_angle(c0, s0.player))):.0f}°·{M.horiz(s0.player, c0):.2f} m "
                    f"→ 누른 직후 {abs(math.degrees(M.rel_angle(c1, s1.player))):.0f}°·{M.horiz(s1.player, c1):.2f} m "
                    f"({time.time() - t0:.2f} s, 적 애니 {c0.anim}→{c1.anim})")
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
            return stab(s, c)                              # first cost 0.25 s and then 'no_lock' threw the chance away (27m: 145° at 1.4 m)
        if mv.lock_state(ptr) != "target":
            if mv.lock_state(ptr) == "other":
                mv.unlock()
            if not mv.lock_target(ptr, tries=2, aim=False):   # camera onto it first — a bare R3 grabs whatever is at camera center
                s = mv.snap(8.0) or s
                c = mv.find(s, ptr) or c
                return stab(s, c) if at_back(s, c) else "no_lock"
        side = None
        plus_ok, minus_ok = _arc_open(nm, s.player, c)
        if not (plus_ok or minus_ok):
            return "no_room"                               # 어느 쪽으로도 그놈 등까지 바닥이 없음 — 돌기 시작하지 않음
        want = None if plus_ok and minus_ok else (1.0 if plus_ok else -1.0)   # world-angle way that is open (None = either)
        last = (s.player.x, s.player.z)
        flipped = False
        budget = max(BACKSTAB_S, M.horiz(s.player, c) / 1.5 + 1.0)   # walking in from SNEAK_R takes longer than a circle at contact
        for _ in range(max(1, int(budget / max(BACKSTAB_TICK, 1e-3)))):
            if cancel():
                return "lost"
            s = mv.snap(8.0)
            c = mv.find(s, ptr) if s else None
            if c is None:
                return "lost"
            if (c.anim if c.anim is not None else -1) in M.DOWNED:
                return "moved"                             # knocked down — nothing to get behind. A swing is NOT a reason to stop: it can't
                                                           # turn while it swings, that is when we get round (drill: 4 kills, all mid-swing)
            if not _circle_floor(nm, s.player, c, sides=False):
                return "edge"                              # no floor straight out from it — stop before stepping off (27u: fell 6 m into a gap)
            p_ = s.player
            if want is not None and side is not None and math.hypot(p_.x - last[0], p_.z - last[1]) > 0.05:
                # which world way the strafe really carries us round it: sign of the change in our angle round the foe
                a_now = math.atan2(p_.x - c.x, p_.z - c.z)
                a_was = math.atan2(last[0] - c.x, last[1] - c.z)
                turn = (a_now - a_was + math.pi) % (2 * math.pi) - math.pi
                if abs(turn) > 0.02 and (turn > 0) != (want > 0):
                    if flipped:
                        return "edge"
                    side, flipped = -side, True            # going round the blocked way — turn the strafe the other way once
            last = (p_.x, p_.z)
            x, y, behind = backstab_stick(c, s.player, side)
            if side is None and x != 0.0:
                side = x
            if behind >= BACKSTAB_DEG and M.horiz(s.player, c) <= BACKSTAB_MAX_R:
                return stab(s, c)
            mv.pad.move(x, y)
            wait(BACKSTAB_TICK)
        return "not_behind"
    finally:
        mv.pad.move(0.0, 0.0)
        wait(0.1)
        if not held:
            mv.unlock()
            wait(0.1)
        mv.cam_busy = busy0



def _room_behind(nm, p, c, r: float = 1.0) -> bool:
    """Floor behind the foe and at least one side (r m out, NavMesh, same level)? A hollow with its back to a wall or a drop can't be
    got behind — circling there walks into the wall or off the edge (user 2026-09-28: "except foes against a wall or a cliff").
    True when there's no NavMesh / no global coords to check with."""
    if nm is None or c.heading is None or getattr(p, "gx", None) is None:
        return True
    ox, oy, oz = p.gx - p.x, p.gy - p.y, p.gz - p.z         # foes only have tile-local coords — same tile offset as the player
    fwd = c.heading + math.pi                              # world yaw = heading + π (moves.rel_angle)

    def floor(turn: float, dist: float = r) -> bool:
        a = fwd + turn
        hit = nm.floor_at(c.x + ox + math.sin(a) * dist, c.z + oz + math.cos(a) * dist, c.y + oy)
        return hit is not None and abs(hit[0] - (c.y + oy)) <= 1.0

    # the backstab pulls us in right behind it (≈0.6 m) and we circle out to ~1.3 m — floor all along 0.5–2 m behind, not just at 1 m
    # (27t: backstabbed a hollow near the ramp edge, then fell 25 m on the first step)
    behind_ok = all(floor(math.pi, d) for d in BACK_CHECK_M)
    return behind_ok and (floor(math.pi / 2) or floor(-math.pi / 2))




def _arc_open(nm, p, c, step_deg: float = 20.0) -> tuple[bool, bool]:
    """Floor along the circle round the foe from where we stand to its back, each way (+ / − in world angle), at our distance
    (0.9–1.6 m), same level. → (plus_ok, minus_ok). Both True without NavMesh / global coords / the foe's heading.

    ── 돌 공간이 없으면 뒤잡기 안 함 ([MoKa] 2026-11-03 clear-ramp 123006) ──────────────────────────
     · "옆에 경사로가 막고 있어서 돌수도 없는데 그쪽으로 무리하게 돌다 실패 했잖아" · "지금은 돌수 있는 공간 있어서 뒤잡 성공"
     · 예전엔 돌면서 매 틱 _circle_floor(양쪽 접선 + 바깥 모두 바닥)로만 봐서, 한쪽이 막힌 자리에선 돌기 시작한 뒤 'edge'로 멈춤
       (이 런 뒤잡기 7번 중 edge 4번). 이제 시작 전에 길 전체를 보고 열린 쪽으로만 돈다
    """
    if nm is None or c.heading is None or getattr(p, "gx", None) is None:
        return True, True
    ox, oz = p.gx - p.x, p.gz - p.z
    r = max(0.9, min(1.6, M.horiz(p, c)))
    a0 = math.atan2(p.x - c.x, p.z - c.z)                  # where we stand round it
    ab = c.heading                                         # its back (world yaw of its facing = heading + π)
    d = (ab - a0 + math.pi) % (2 * math.pi) - math.pi     # shortest signed turn to its back
    out = []
    for sign in (1.0, -1.0):
        span = d if (d >= 0) == (sign > 0) else d + sign * 2 * math.pi
        n = max(1, int(abs(math.degrees(span)) / step_deg))
        ok = True
        for k in range(1, n + 1):
            a = a0 + span * k / n
            hit = nm.floor_at(c.x + ox + math.sin(a) * r, c.z + oz + math.cos(a) * r, p.gy)
            if hit is None or abs(hit[0] - p.gy) > 1.0:
                ok = False
                break
        out.append(ok)
    return out[0], out[1]


def _circle_floor(nm, p, c, step: float = 0.8, sides: bool = True) -> bool:
    """Floor (same level) round us where circling the foe can take us: both ways along the circle and straight out from it, step m
    (sides=False: straight out only — _backstab checks the way round with _arc_open). True without NavMesh / global coords."""
    if nm is None or getattr(p, "gx", None) is None:
        return True
    vx, vz = p.x - c.x, p.z - c.z
    n = math.hypot(vx, vz) or 1.0
    vx, vz = vx / n, vz / n
    for dx, dz in (((vz, -vx), (-vz, vx), (vx, vz)) if sides else ((vx, vz),)):   # tangent both ways, outward
        hit = nm.floor_at(p.gx + dx * step, p.gz + dz * step, p.gy)
        if hit is None or abs(hit[0] - p.gy) > 1.0:
            return False
    return True


def _footing_ok(nm, p, r: float = FOOT_R) -> bool:
    """Floor under us and FOOT_R m round us at our level (NavMesh). True without NavMesh / global coords."""
    if nm is None or getattr(p, "gx", None) is None:
        return True
    for k in range(8):
        a = k * math.pi / 4
        for d in (0.0, r) if k == 0 else (r,):
            hit = nm.floor_at(p.gx + math.sin(a) * d, p.gz + math.cos(a) * d, p.gy)
            if hit is None or abs(hit[0] - p.gy) > 1.0:
                return False
    return True


def _back_to_safe(mv, nm, start, log, arena=None, secs: float = 2.5) -> None:
    """The backstab pulled us somewhere with no floor close by — walk back toward where it started (that was on floor) before
    anything else moves the stick (27t: the next lure step walked off the ramp edge, 25 m fall)."""
    s = mv.snap(8.0)
    if s is None or _footing_ok(nm, s.player):
        return
    p = s.player
    # the fight spot (arena — the flat ground where we drink estus) when it's close and on our level (user 2026-09-28), else where the backstab started
    if arena is not None and math.hypot(arena[0] - p.x, arena[2] - p.z) < 10.0 and abs(arena[1] - p.y) < 1.5:
        start, where = tuple(arena), "싸움 자리"
    else:
        where = "시작 자리"
    log(f"      뒤잡기 뒤 발밑 가장자리 — {where} ({start[0]:.1f},{start[2]:.1f})로 물러남")
    # shield up while walking back — this walk is a blind spell (no duel tick, no reflex): 09-30 runs lost −341 HP per run in
    # these (blind_report.py), [MoKa] 2026-10-01: "가드는 하는 것이 좋음". Left up: the next duel tick sets the guard it wants.
    getattr(mv, "guard", lambda on: None)(True)
    t0 = time.time()
    while time.time() - t0 < secs:
        s = mv.snap(8.0)
        if s is None:
            break
        if math.hypot(s.player.x - start[0], s.player.z - start[2]) < 0.4 or _footing_ok(nm, s.player):
            break
        mv.pad.move(*mv.stick_to(s, start[0], start[2], 0.5))    # walk, not run
        getattr(mv.pad, "release_due", lambda: None)()
        time.sleep(0.03)
    mv.pad.move(0.0, 0.0)


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


def _separate(mv, s, ptr, others: list, nm, arena, cancel, trail=None) -> str:
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
    if goal is not None:
        way, how = [goal], ""
    else:
        way = _escape_way(s, nm, here, trail)
        if not way:
            return "no_spot"
        how = "escape_"
    r = mv.walk_path(way, nm, "walk", stop=lambda sn: cancel(), timeout_per=2.5)   # run → walk (evidence-grade gate, 2026-09-26)
    mv.guard(True)
    s2 = mv.snap(10.0)
    c2 = mv.find(s2, ptr) if s2 else None
    if c2 is not None:
        mv.face(s2, c2, deg=20.0)
    return how + r


def _escape_way(s, nm, here, trail) -> list:
    """No straight-line split spot (narrow stairs, ramps): the first SEP_ESCAPE_M of escape.pick's path — toward where the foes
    are not, usually the way we came. [] when off, no real NavMesh (golden's stand-in has no graph) or nothing better."""
    if not SEP_ESCAPE or nm is None or not hasattr(nm, "graph"):
        return []
    from . import escape as E
    try:
        foes = [(x.x, x.y, x.z, x.anim not in (None, -1) and not (9000 <= x.anim < 9100))
                for x in s.hostile(E.SCAN_R + 2.0) if x.hp > 0]
        ch = E.pick(nm, here, foes, list(trail or []))
    except Exception:
        return []
    if ch.point is None:
        return []
    way, acc, last = [], 0.0, here
    for q in [*ch.path, ch.point]:
        d = math.hypot(q[0] - last[0], q[2] - last[2])
        if d < 0.8 and not way:
            continue                                       # the centroid we stand on
        if acc + d > SEP_ESCAPE_M:
            break
        acc += d
        way.append(tuple(q))
        last = q
    return way


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


def free_or_blocking(anim) -> bool:
    """
    ── 내 동작: 빈손(-1) 또는 방패로 막는 중 ──────────────────────────────
     · 방패에 맞은 동작은 무기 종류가 앞자리에 붙는다: 배틀 액스 140 · 클레이모어 20140 (공격도 303000 / 253000)
     · 예전엔 100–199만 봐서 클레이모어로 막는 중을 '내 공격·구르기 중'으로 읽고 rule_after_swing·rule_face_first를 건너뜀
       (10-12 클레이모어 3런: 막은 뒤 반격 3/10, 배틀 액스 65/151)
    """
    return anim in (None, -1) or (0 <= anim < 100000 and 100 <= anim % 10000 < 200)


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


def _crowd(s, ptr) -> int:
    """Foes around us that count as "surrounded": the target, plus others that are moving/swinging (anim ≠ -1), within CROWD_R at our level.
    Others standing still (anim -1) don't count — asleep hollows next to the fight would end every duel."""
    p = s.player
    return sum(1 for x in s.hostile(CROWD_R + 1.0)
               if x.hp > 0 and M.horiz(p, x) < CROWD_R and abs(x.y - p.y) < 2.0 and not (9000 <= (x.anim or 0) < 9100)
               and (x.ptr == ptr or x.anim not in (-1, None)))


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


def _foe_brief(p, x) -> dict:
    """One foe as the target-switch record sees it: who, how far, which side, what it is doing, how hurt."""
    ang = None
    if p.heading is not None:
        ang = round(math.degrees(M.rel_angle(p, x)))
    return {"ptr": x.ptr, "npc": x.npc_param, "h": round(M.horiz(p, x), 2), "dy": round(x.y - p.y, 2), "deg": ang,
            "anim": x.anim, "hp": x.hp, "max_hp": x.max_hp}


def _arb_start(F, p, c, ranged_cut, busy, x, threat, now) -> dict:
    """── 목표 바꿈 판단 기록 (MoKa 2026-11-09, docs/decision_model_pplx_2026-11-09.md) ──────────
     목표 바꿈은 RULES 전에 일어나고 지금 목표가 얼마나 다쳤는지 안 봄 (M1108-10 '다친 적 유지'와 부딪힘).
     원래 목표 → 원거리 후보(+근접 위협 거부) → 끼어든 놈 후보 → 최종 목표를 한 기록으로 남김. 영상 판정과 맞출 원자료.
     기록만 — 이 dict는 다시 읽히지 않음."""
    return {"t": now, "from": _foe_brief(p, c), "busy": bool(busy),
            "ranged": [_foe_brief(p, y) for y in ranged_cut],
            "ranged_pick": None if x is None else x.ptr,
            "ranged_veto": None if threat is None else _foe_brief(p, threat),
            "ranged_hold_left": round(max(0.0, SWITCH_HOLD - (now - F.switch_t)), 2),
            "orig_ptr": F.orig_ptr}


def _switch_threat(s, p, x, swung: dict, now: float):
    """
    ── 원거리 전환 안전성 (P-121, [MoKa] 2026-11-03) ──────────────────────────────
     try 27 530.7 s: 근접 석궁병이 딱 2.0 m(MELEE_BUSY_R은 '< 2.0')라 busy가 아님 → 8.1 m 쪽으로 돌아섬 → −97·−81, 사선 안 에스트 끊김, 사망.
     [MoKa]: "구르기 2번 이후 거리가 너무 멀어 지면, 당연히 석궁병 들이 압도적으로 유리하지."
     · 원거리 우선 고르기는 그대로, 고른 결과에 이 검사만 덧붙임: 같은 높이에서 SAFE_SWITCH_NEAR_R 안의 깨어 있는 놈, 또는
       SAFE_SWITCH_CLEAR_R 안에서 SAFE_SWITCH_RECENT_S 안에 휘두른 놈(지금 목표 포함, 고른 원거리 놈 제외)이 있으면 바꾸지 않음.
     · 그놈이 죽거나 CLEAR_R 밖으로 나가거나 CLEAR_R 안에서 RECENT_S 동안 조용하면 다음 틱에 다시 바꿀 수 있음.
     · 세 숫자 모두 측정 전 가설.
    → the foe that makes the switch unsafe, or None"""
    near = []
    for y in s.hostile(SAFE_SWITCH_CLEAR_R + 1.0):
        if y.ptr == x.ptr or y.hp <= 0 or abs(y.y - p.y) >= 1.2 or (y.anim or 0) in M.DOWNED or 9000 <= (y.anim or 0) < 9100:
            continue
        h = M.horiz(p, y)
        if h < SAFE_SWITCH_NEAR_R or (h < SAFE_SWITCH_CLEAR_R and now - swung.get(y.ptr, -1e9) < SAFE_SWITCH_RECENT_S):
            near.append(y)
    return min(near, key=lambda y: M.horiz(p, y)) if near else None


@dataclass
class DuelResult:
    result: str                      # killed | me_dead | low_hp | losing | crowd | lost | stalemate | stuck | timeout | cancel | shot
    npc: int | None = None
    vs: int | None = None            # npc actually fought last, when it switched away from the target (interloper / ranged first)
    secs: float = 0.0
    dealt: int = 0
    taken: int = 0
    hits: list = field(default_factory=list)
    rules: dict = field(default_factory=dict)   # rule name → ticks it acted (RULES) — which rules drove this fight
    shot_from: tuple | None = None   # result 'shot': (x, y, z, npc) of the thrower that hit us
    wall_back: bool = False          # 'crowd' because WALL_BACK_N were on us away from a wall — Field backs to a wall (not the way home)

    def line(self) -> str:
        kinds = [h["kind"] + ("" if h["dmg"] else "×") for h in self.hits]
        vs = f" (실제 상대 {self.vs})" if self.vs is not None and self.vs != self.npc else ""
        return f"{self.result}{vs} — {self.secs:.0f} s, 준 피해 {self.dealt}, 받은 피해 {self.taken}, 공격 {' '.join(kinds) or '없음'}"


def _approach(mv: M.Moves, weapon, s, c, nm, foe, cancel, log=lambda *a: None, may_approach=None, rush: bool = False) -> str:
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
        if rush and cc is not None and not any(
                x.ptr != ptr and _awake_anim(x.anim) and M.horiz(sn.player, x) < RUSH_OTHER_R and abs(x.y - sn.player.y) < 1.2
                for x in sn.hostile(RUSH_OTHER_R + 1.0)):
            return "sprint"                                 # M1006-17: 붙을 수 있는 화염병 할로우 — 던지는 줄에 오래 서 있지 않게 질주
        return "guard" if foe.ranged else "walk"
    return mv.walk_path(path, nm, mode, stop, timeout_per=6.0)


PUNISH_AFTER = 1.1       # backstep style: the blade has passed only this long after the attack starts (8 of 11 entries within 1.0 s got hit, 1.0–1.3 s were 3/3 unhurt)
PUNISH_MIN_R = 1.8       # closer than this, leave it to reflex instead of punishing the whiff (5 of 7 entries at ≤1.6 m got hit by the next swing)
PUNISH_R = 1.6           # within reach + this, walk in and hit (with 0.9 it couldn't get in from 2.5 m for 6 s)


CONT = "continue"      # a rule acted this tick — start the next tick


class Fight:
    """What one duel remembers across ticks (the old duel() locals). Rules read and change it."""

    def __init__(self, mv, weapon, ptr, nm, log, limit, low_hp, cancel, care, reflex, arena, style, wait_far, gen, events,
                 may_approach, crowd_ok: bool = False, wall_ok: bool = False, trail=None):
        self.mv, self.weapon, self.ptr, self.nm, self.log, self.limit, self.low_hp = mv, weapon, ptr, nm, log, limit, low_hp
        self.cancel, self.care, self.reflex, self.arena, self.style = cancel, care, reflex, arena, style
        self.wait_far, self.may_approach = wait_far, may_approach
        self.crowd_ok = crowd_ok                           # True: 둘 이상에게 둘러싸이면 HP와 상관없이 싸움을 끝낸다 ('crowd') — Field 가 물러남
        # rule_shot: HP last tick, times hit from afar, ptr → last time seen swinging — Moves.swung, kept by every snapshot read
        # (also inside attack moves and by the camera), so a swing during a multi-second kick combo is not missed (P-66 b)
        self.shot_hp, self.shots = None, []
        self.swung = mv.__dict__.setdefault("swung", {}) if hasattr(mv, "__dict__") else {}
        self.trail = trail or []                           # where we walked (Field.trail) — escape.pick's 'way we came' for a split with no spot
        self.wall_ok = wall_ok                             # True: WALL_BACK_N 이상이 붙었는데 벽 옆이 아니면 끝낸다 ('crowd', wall_back) — Field 가 벽으로
        self.t0 = time.time()
        s0 = mv.snap()
        self.hp_start = s0.player.hp if s0 else 0
        self.hp_min = self.hp_start
        self.res = DuelResult("timeout")
        self.last_dmg_t, self.kick_t = self.t0, 0.0
        self.plan_for = None          # COMBO_ONLY: ptr of the foe the engagement plan was logged for
        self.sep_t, self.sep_n = 0.0, 0
        self.best_h, self.best_t = None, self.t0
        self.wait_t0, self.wait_hmin = 0.0, 0.0
        self.wait_hp0 = None                               # HP when wait_far waiting began (to see if we're hit from elsewhere)
        self.last_seen, self.foe = None, None
        self.care_t, self.backstep_t, self.move_t = 0.0, 0.0, 0.0
        self.pulled = arena is None
        self.orig_ptr, self.switch_t = None, 0.0
        self.circle_n = 0                                  # attempts to circle behind (foe.circle_behind) — prevents infinite loop
        self.edge_until = 0.0                              # after an 'edge' stop: no backstab for a while (it'd circle into the same gap)
        self.still = [None, 0.0, 0.0, 0.0]                 # [ptr, x, z, since] — where the foe last moved, for BACKSTAB_STILL_S
        self.calm: dict[int, tuple[float, float, float]] = {}   # ptr → (x, z, first seen) while it hasn't moved or animated (_asleep)
        self.woke: set[int] = set()
        self.acts: dict = {}                               # what was done in 1 s (for logging)
        self.note_t = self.t0
        self.shadow = ShadowKick(log=log, events=events, gen=gen)   # gen·events: supplied by Field.fight (for shadow kick events)
        self.events = events or (lambda *_a, **_k: None)   # also the combo-only test's "combo" events (combo_table)
        self.no_obs = control.NoObs(mv.pad)                # no snapshot: stick off now, everything off after a while (P0-C)
        self.lock_t, self.lock_n = 0.0, 0                  # last R3 from _keep_lock, presses made (lock on + release)

    def note(self, act: str, s_, c_) -> None:
        """Count what was done per tick, one line per 1 s — so we can see where it gets stuck (2026-09-24: didn't know why it couldn't hit for 18 s at 4 m)."""
        self.acts[act] = self.acts.get(act, 0) + 1
        if time.time() - self.note_t < 1.0:
            return
        self.note_t = time.time()
        p_ = s_.player
        a_ = c_.anim if c_.anim is not None else -1
        line = (f"      [{time.time() - self.t0:4.1f}s] 거리 {M.horiz(p_, c_):.1f} 높이 {c_.y - p_.y:+.1f} 그놈 애니 {a_} HP {c_.hp} | "
                f"나 HP {p_.hp} SP {p_.sp} 애니 {p_.anim} 각 {math.degrees(M.rel_angle(p_, c_)) if p_.heading is not None else 0:+.0f}° | "
                + " ".join(f"{k}×{v}" for k, v in self.acts.items()))
        self.log(line)
        self.acts.clear()

    def record(self, hit) -> None:
        if self.reflex is not None and R.wall_bounced(hit):
            s_ = self.mv.snap(5.0)
            if s_ is not None and self.reflex.note_bounce(s_.player, hit):
                self.log(f"      무기가 벽에 튕김 (내 애니 {[a for _, a in hit.my_anims][:5]}) — 이 자리에서 다시 안 휘두름 (P-139)")
        d = hit.as_dict()
        self.res.hits.append({k: d[k] for k in ("kind", "presses", "dmg", "dead", "taken", "others")})
        if hit.dmg > 0:
            self.last_dmg_t = time.time()
            self.res.dealt += hit.dmg

    def done(self, result: str) -> DuelResult:
        mv, res = self.mv, self.res
        getattr(mv.pad, "guard", lambda on: None)(False)
        mv.pad.move(0.0, 0.0)
        if self.lock_n:
            _lock_release(mv, self.ptr)                    # we locked on in this fight — the walk after it must not stay locked
        s_ = mv.snap(5.0)
        self.shadow.flush(time.time(), s_, cancelled=(result == "cancel"))
        if s_ and s_.player.hp is not None:
            self.hp_min = min(self.hp_min, s_.player.hp)
        res.result, res.secs = result, time.time() - self.t0
        if self.orig_ptr is not None and self.last_seen is not None:
            res.vs = self.last_seen.npc_param
        res.taken = max(0, self.hp_start - self.hp_min)    # based on lowest HP (so Estus drunk midway doesn't hide it)
        return res

    def killed_if(self, dead: bool):
        """A hit killed the target (not an interloper) → the duel's result, else CONT."""
        return self.done("killed") if dead and self.orig_ptr is None else CONT


class Tick:
    """What this tick sees: s, p (player), c (target), h (horizontal distance), dy, a (its anim), now — plus what rules work out."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


def _sense(F: Fight):
    """Read the game, follow the target (re-found after a quit-out, interlopers / shooters first), end conditions.
    → DuelResult (over) | CONT (nothing to act on this tick) | Tick"""
    mv, res = F.mv, F.res
    s = mv.snap(SEEK_R)
    # 죽음이 먼저 (P-68): cancel(안전 자리 8 m 밖)을 먼저 봐서 HP 0인 채 'cancel' → 부른 쪽이 죽은 캐릭터로 물러남·약공·구르기를 이어 감
    if s is not None and s.player.hp is not None and s.player.hp <= 0:
        F.hp_min = 0
        return F.done("me_dead")
    if F.cancel():
        return F.done("cancel")
    now = time.time()
    if now - F.t0 > F.limit:
        return F.done("timeout")
    if s is None:
        F.no_obs.missing()                                 # nothing seen → nothing held (P0-C)
        time.sleep(0.05)
        return CONT
    F.no_obs.seen()
    p = s.player
    if p.hp is not None:
        F.hp_min = min(F.hp_min, p.hp)
    if p.hp is not None and p.hp <= 0:
        return F.done("me_dead")
    c = mv.find(s, F.ptr)
    if c is None:
        # dropped from the list — could be a corpse removed, or the pointer changed after a quit-out. If the same type is alive nearby, it's that one
        ls = F.last_seen
        if ls is not None:
            again = [x for x in s.chars if x.npc_param == ls.npc_param and x.hp > 0
                     and math.dist((x.x, x.y, x.z), (ls.x, ls.y, ls.z)) < 3.0]
            if again:
                F.ptr = again[0].ptr
                return CONT
        if F.orig_ptr is not None and F.orig_ptr != F.ptr:   # the interloper vanished (died and removed) — back to the original target
            F.ptr, F.orig_ptr, F.last_seen = F.orig_ptr, None, None
            return CONT
        if F.last_seen is not None and res.hits and res.hits[-1]["dead"]:
            return F.done("killed")
        return F.done("lost")
    if c.hp <= 0:
        if F.orig_ptr is not None and F.orig_ptr != F.ptr:
            F.log(f"      끼어든 {c.npc_param} 처치 — 원래 목표로")
            F.ptr, F.orig_ptr = F.orig_ptr, None
            F.last_seen = None
            return CONT
        return F.done("killed")
    F.last_seen = c
    if res.npc is None:
        res.npc = c.npc_param
    # the foe data must follow whoever ptr is now. It used to be set once, so after "interloper killed — back to the
    # original target" a shield soldier kept the hollow's data and got hollow moves (먼저 치기 into the shield: dealt 4,
    # took 240, then died — 2026-09-27 burg-bonfire 27c, ROADMAP P-8)
    F.foe = foes_.of(c.npc_param)
    if p.hp < p.max_hp * _low_hp_line(s, F.low_hp) and not (c.hp <= FINISH_KEEP_HP and p.hp >= p.max_hp * 0.12):
        return F.done("low_hp")                            # don't retreat from an almost-dead foe — if we leave and return, a survivor's HP refills
    # ── 지는 싸움은 일찍 나온다 ([MoKa] 2026-10-01: "전술적인 문제와 후퇴를 더 많이 할 필요") ──
    #  09-30a~10-01b: 큰 피격의 절반(4779/9824)이 옆에 아무도 없는 1:1에서 망자 연타(3003·3000)를 계속 받은 것, low_hp로 끝난 7번이 2347을 받음
    #  (25 %까지 버티다 나옴). 이 싸움에서 최대 HP의 LOSING_TAKEN을 받았는데 그놈 HP의 LOSING_DEALT도 못 깎았으면 → 물러나 마시고 다시
    if (F.low_hp > 0 and p.max_hp and (F.hp_start or 0) - min(F.hp_min or p.hp, p.hp) >= p.max_hp * LOSING_TAKEN
            and F.res.dealt < (c.max_hp or c.hp or 1) * LOSING_DEALT and c.hp > FINISH_KEEP_HP):
        return F.done("losing")
    # 둘러싸이면 HP와 상관없이 물러난다 ([MoKa] 2026-09-28: "둘러싸였을 때는 퀵 종료하면 안 되고 후퇴해야 해"). 레벨 낮은 Bandit Bot 은
    # 둘이 같이 치면 0.16 s 에 −237 — HP를 보고 정하면 이미 늦다. 퀵 종료는 그 자리에서 다시 시작해 HP 65 % 로 이어 싸우다 사망
    if F.crowd_ok and _crowd(s, F.ptr) >= 2:
        return F.done("crowd")
    # ── 셋 이상이면 벽으로 (P-29, [MoKa] 2026-09-30: "벽으로 물러나서 하나씩") ──
    #  09-30b: 망자 254010 셋이 0.85 m로 붙어 싸움 4번에 준 피해 0, 뒤잡기 시도 → edge 반복, 사망. 등을 벽에 대면 뒤로 못 돌아 들어온다
    if F.wall_ok and _crowd(s, F.ptr) >= WALL_BACK_N and not _at_wall(F.nm, p):
        F.res.wall_back = True
        return F.done("crowd")
    if now - F.last_dmg_t > STALEMATE_S:
        return F.done("stalemate")
    h, dy, a = M.horiz(p, c), c.y - p.y, (c.anim if c.anim is not None else -1)
    # ── a target that falls off / is now on a lower level is not one to move toward (P-69) ──
    #  10-11 174753 zone 1: 254010 fell off the ledge mid-fight (anim 1500, −1.1 → −4.6 m); rule_face_first turned us to it — face()
    #  turns by pushing the stick, so it walked us over the same ledge (4 m, quit-out; with no fall quit-out now, possibly a death).
    #  Same reach as Field's chasers (FOLLOW_DY): 'lost' → Field leaves it out for the rest of this walk.
    #  ── 처음부터 아래층에 서 있던 적은 '떨어짐'이 아님 (10-13 Claymore 구역 1–8) ──
    #   구역 5의 창 방패병 255001 둘은 안전 자리보다 3 m 아래에 서 있음 → 싸움 첫 틱에 'lost' 8번(17 s씩, 140 s), 둘 다 못 잡고 구역 6에서
    #   같이 와서 사망. 떨어짐 = 그 적 자신의 높이가 싸움에서 처음 본 뒤 TARGET_DROP_DY 넘게 내려감 (내가 계단을 오르내린 건 안 셈)
    y0 = F.__dict__.setdefault("_foe_y0", {}).setdefault(c.ptr, c.y)
    if a in M.FALLING or (dy < -TARGET_DROP_DY and c.y < y0 - TARGET_DROP_DY):
        F.log(f"      {c.npc_param}가 아래로 떨어짐 (높이 {dy:+.1f} m, 애니 {a}) — 따라가지 않음")
        F.note("목표 떨어짐", s, c)
        return F.done("lost")
    ranged_cut = [x for x in s.hostile(RANGED_SWITCH_R) if x.ptr != F.ptr and x.hp > 0
                  and foes_.of(x.npc_param).thrower and (x.anim or -1) in M.ATTACK
                  and abs(x.y - p.y) < RANGED_REACHABLE_DY]
    # shooters above (or far away), unlike close interlopers (cut, below), have no distance limit — we were getting hit while fighting only the
    # foe in front defensively (user 2026-09-25: "the arrow guy is attacking so it's set to defense-heavy — deal with him first").
    # But height difference is limited — switching to 254012 (terrace archer, height difference +6–8.5 m) made _approach() endlessly try to close
    # a distance unreachable on foot, taking only arrows for 30 s, HP 695→137 (2026-09-25, burg-loop 091110).
    # measured: successful ranged switches were all at height difference ≤ +3.0 m — above that, treat as unreachable and ignore.
    # if a foe is right in front (MELEE_BUSY_R), take it first — turning your back to go for a distant shooter gets you hit by both.
    # P-56 (ramp ledge 2:1, 10-10..10-11): both checks read foes.ranged, which the axe hollow 254001 carries for lure / waiting
    # (MoKa-approved, LAYA.md 13) — so a swinging axe hollow was 'a shooter' and didn't make us busy; the bot flipped between it and
    # 254002 (42 'ranged first' switches in the seg 1-2 runs, 27 to the axe hollow, 9 away from a target < 2 m), turning 90–160°
    # with both on it. Now: only real throwers (Foe.thrower) pull us away, and any awake foe within MELEE_BUSY_R — a thrower in
    # melee too — keeps us on what is in front (the interloper rule below still takes a clearly closer one)
    busy = any(x.hp > 0 and M.horiz(p, x) < MELEE_BUSY_R and abs(x.y - p.y) < 1.2
               and not (9000 <= (x.anim or 0) < 9100) for x in s.hostile(MELEE_BUSY_R + 1.0))
    swung = F.__dict__.setdefault("_swing_t", {})
    for x in s.hostile(SAFE_SWITCH_CLEAR_R + 1.0):
        if x.hp > 0 and (x.anim or -1) in M.ATTACK:
            swung[x.ptr] = now
    x = min(ranged_cut, key=lambda y: M.horiz(p, y)) if ranged_cut and not busy and now - F.switch_t > SWITCH_HOLD else None
    threat = _switch_threat(s, p, x, swung, now) if x is not None else None
    arb = _arb_start(F, p, c, ranged_cut, busy, x, threat, now) if SCENE_TAP is not None and ranged_cut else None
    if threat is not None:
        if F.__dict__.get("_switch_held") != threat.ptr:
            F._switch_held = threat.ptr
            F.log(f"      원거리 전환 보류: {x.npc_param} {M.horiz(p, x):.1f} m — 근접 {threat.npc_param} {M.horiz(p, threat):.1f} m"
                  f" (애니 {threat.anim})")
        x = None
    if x is not None:
        if F.__dict__.pop("_switch_held", None) is not None:
            F.log("      근접 위협 해소 — 원거리 전환 재개")
        if F.orig_ptr is None:
            F.orig_ptr = F.ptr
        F.log(f"      원거리부터: {x.npc_param} ({M.horiz(p, x):.1f} m, 높이차 {x.y - p.y:+.1f}) — 원래 목표 {h:.1f} m")
        F.ptr, c, F.switch_t = x.ptr, x, now
        F.last_seen, F.foe = x, foes_.of(x.npc_param)
        h, dy, a = M.horiz(p, c), c.y - p.y, (c.anim if c.anim is not None else -1)
    cut = [x for x in s.hostile(SWITCH_R + 2.0) if _interloper(x, p, F.ptr, h)]
    if SCENE_TAP is not None and (arb is not None or cut):
        arb = arb or _arb_start(F, p, c, [], busy, None, None, now)
        arb["mid"] = _foe_brief(p, c)                     # target after the ranged step, before the interloper step
        arb["cut"] = [_foe_brief(p, y) for y in cut]
        arb["cut_hold_left"] = round(max(0.0, SWITCH_HOLD - (now - F.switch_t)), 2)
    # between two at similar distances it switched targets every 1–2 s, turning and getting hit in the back (±140–166°, 442 in 25 s) —
    # switch only when clearly closer (SWITCH_MARGIN), and keep it for SWITCH_HOLD after switching
    if cut and now - F.switch_t > SWITCH_HOLD:
        # interloper first (old hunt.py rule, user: "can't you attack the nearby enemy?") — watching only the map target, took 387 in 13 s from one hitting from the side and died.
        # after killing it, return to the original target
        x = min(cut, key=lambda y: M.horiz(p, y))
        if F.orig_ptr is None:
            F.orig_ptr = F.ptr
        F.log(f"      목표 바꿈: {x.npc_param} ({M.horiz(p, x):.1f} m, 애니 {x.anim}) — 원래 목표 {h:.1f} m")
        F.ptr, c, F.switch_t = x.ptr, x, now
        F.last_seen, F.foe = x, foes_.of(x.npc_param)
        h, dy, a = M.horiz(p, c), c.y - p.y, (c.anim if c.anim is not None else -1)
    if arb is not None:
        arb["to"] = _foe_brief(p, c)
        arb["switched"] = arb["to"]["ptr"] != arb["from"]["ptr"]
        SCENE_TAP.switch(F, arb)                           # record only (scenes.py) — nothing here is read back
    if not (h > F.weapon.reach and F.wait_far):            # if not waiting, also clear the waiting HP baseline
        F.wait_hp0 = None
    _track_calm(F, c, a, now)
    F.mv.cam_target = F.ptr                                # the camera follows whoever we fight now — after an interloper /
    #                                                        'ranged first' switch it kept turning to the first target (P-65)
    return Tick(s=s, p=p, c=c, h=h, dy=dy, a=a, now=now)


def _track_calm(F, c, a, now) -> None:
    """Every tick, on the raw anim (before prep_linger rewrites it): a foe that animates or moves is awake for the rest of the fight."""
    if c.ptr in F.woke:
        return
    at = F.calm.setdefault(c.ptr, (c.x, c.z, now))
    if a != -1 or math.hypot(c.x - at[0], c.z - at[1]) > SLEEP_MOVE_M or c.hp < (c.max_hp or c.hp):
        F.woke.add(c.ptr)


def _asleep(F, c, now) -> bool:
    """Lying still the whole fight so far (≥ SLEEP_SEEN_S), never hit — the Asylum's dormant hollows wake only at ~1 m."""
    at = getattr(F, "calm", {}).get(c.ptr)
    return at is not None and c.ptr not in F.woke and now - at[2] >= SLEEP_SEEN_S


# ── rules, in priority order (RULES below). Each gets (Fight, Tick) and returns None (not mine — next rule), CONT (acted),
# or a DuelResult (duel over). "prep" steps only work something out for the rules after them. The order is the old duel()'s
# if-chain order exactly (tests/duel_golden_test.py) — to change a priority, move the rule in RULES and re-record on purpose.

SHOT_HP = 40             # rule_shot: one hit this big …
SHOT_NEAR_R = 6.0        # … with no foe this close swinging (or done swinging under SHOT_NEAR_S ago) — 6 m, not 4: a hollow's lunge
                         # lands from 4.3–5.7 m (P-59) …
SHOT_NEAR_S = 1.5        # (in a duel's first SHOT_NEAR_S nobody's earlier swings are known → any awake foe within SHOT_NEAR_R counts)
SHOT_FAR_R = 5.0         # … but a thrower (foes.Foe.thrower) at least this far — a melee foe that swung far off is not one (P-59)
SHOT_SCAN_R = 25.0
SHOT_HOLD_R = 2.5        # an awake melee foe this close (not staggered / down): stay and fight it (P-45: turning away 2 m from a foe
                         # got us hit three times) — unless it is the second shot within SHOT_AGAIN_S
SHOT_AGAIN_S = 10.0
SHOT_REACH = 11.0        # a thrower reaches this far (thrown items fly ~10 m, field.LURE_R) — Field backs off beyond it


def _awake_anim(a) -> bool:
    """Up and able to hit: an anim, not idle/asleep (9000s), not staggered or down."""
    return a not in (None, -1) and not (9000 <= a < 9100) and a not in M.STAGGER and a not in M.DOWNED


# ── 화염병 할로우는 곧장 붙는다 (M1006-17, [MoKa] 10-06 · 11-09 M1109-02 "둘 다 살림") ──────────────────────────────
#  10-06: "화염병 할로우(지붕 원거리)는 발사체를 읽지 않고 빨리 붙어서 친다 — 단, 붙으러 가는 길이 낙사 위험 구간이면 무시하고
#  사정권 밖에서 싸운다 (턱 위 254012)". 11-09 MoKa: rule_shot(사선 밖으로)과 둘 다 살림 — 붙을 수 있는 화염병 할로우가 목표일 때만
#  곧장 붙고(멀면 질주, 그 놈에게 맞아도 물러나지 않음), 다른 투척 적 · 붙을 수 없는 경우는 rule_shot 그대로.
#  "붙을 수 있음" = 아래 전부 (값은 측정 전 — 오프라인 테스트만):
#  "턱 위 254012"는 번호가 아니라 자리: Burg의 화염병 할로우 다섯은 모두 254012이고, MoKa가 무시하라고 한 건 턱 위 셋 (0.2,−4,−90.2) ·
#  (3.5,−1.9,−86.2) · (5.1,−1.8,−84.1), 높이 +6 m, 사다리 · 망루 쪽 낙사 구간으로만 감 (plan.md 1-m 10-06) → 높이 차 · 경로로 거름.
RUSH_DY = 1.2              # 그 놈과 높이 차가 이 안 (턱 위 · 아래층은 못 붙음)
RUSH_PATH_MAX = 20.0       # NavMesh 경로 길이가 이 안 …
RUSH_DETOUR = 1.6          # … 그리고 직선 거리의 이 배 안 (먼 우회 = 다른 길로 돌아감)
RUSH_DROP_R = 1.0          # 경로 위 점 중 하나라도 낙차 가장자리(NavMesh 'drop')가 이 안이면 낙사 위험 구간
RUSH_OTHER_R = 8.0         # 다른 깨어 있는 적이 이 안이면 질주 안 함 (뛰는 동안 못 막음 — _approach mode의 9-25 규칙 그대로)
RUSH_RECHECK_S = 1.0
RUSH_NM = None             # tests only (tests/scene_world.py "rush_nav"): NavMesh stand-in for rush_check when duel has none


def _path_len(path) -> float:
    return sum(math.dist(a, b) for a, b in zip(path, path[1:]))


def rush_check(nm, p, c) -> tuple[bool, str]:
    """Can we close in on firebomb hollow c straight away (M1006-17)? → (ok, why). Pure — no pad, no snapshot reads."""
    if foes_.of(c.npc_param) is not foes_.FIREBOMB_HOLLOW:
        return False, "화염병 할로우 아님"
    if abs(c.y - p.y) > RUSH_DY:
        return False, f"높이 차 {c.y - p.y:+.1f} m (턱 위 · 아래층)"
    if nm is None:
        return False, "NavMesh 없음"
    path = nm.find_path((p.x, p.y, p.z), (c.x, c.y, c.z))
    if not path or len(path) < 2:
        return False, "경로 없음"
    n, h = _path_len(path), M.horiz(p, c)
    if n > RUSH_PATH_MAX or n > max(h, 1.0) * RUSH_DETOUR:
        return False, f"경로 {n:.1f} m (직선 {h:.1f} m)"
    if hasattr(nm, "drop_dist"):
        for q in path[1:]:
            d = nm.drop_dist(*q)
            if d < RUSH_DROP_R:
                return False, f"경로에 낙차 가장자리 {d:.1f} m ({q[0]:.1f}, {q[1]:.1f}, {q[2]:.1f})"
    return True, f"경로 {n:.1f} m"


def _rush(F, s, c) -> bool:
    """rush_check for the current target, cached per foe for RUSH_RECHECK_S; logs when the answer changes."""
    now = time.time()
    memo = F.__dict__.setdefault("_rush", {})
    got = memo.get(c.ptr)
    if got is None or now - got[0] >= RUSH_RECHECK_S:
        ok, why = rush_check(F.nm if F.nm is not None else RUSH_NM, s.player, c)
        if got is None or got[1] != ok:
            F.log(f"      화염병 할로우 {c.npc_param} {'곧장 붙음' if ok else '곧장 안 붙음'} — {why} (M1006-17)")
        memo[c.ptr] = got = (now, ok)
    return got[1]


def swing_over(foe, a, age) -> bool:
    """The foe's attack anim is over — it lingers in the 3000s 1.5–5.3 s after the hit, so past SWING_S it counts as standing.
    A windup (foe.windup) is not over before it lands (foe.windup_land_s + LAND_PAD): P-66 — the shield soldier's 3004 lands at
    2.0–2.1 s, rule_after_swing (6th) took it as ended at 1.6 s and kicked into it (−228) while rule_late_windup_block (9th),
    which knows it lands later, never got its turn. One measure for rule_after_swing, prep_linger and prep_face."""
    if a is None or a not in M.ATTACK or age is None:
        return False
    if a in getattr(foe, "unblockable", ()):
        # ── 막을 수 없는 공격은 나이로 안 끝낸다 ([MoKa] 10-12 "가드와 공격이 미묘하게 안 맞아") ──
        #  10-12 guardkeep1 85 s: 망자 3009가 4.4 s 이어졌는데 1.6 s 넘었다고 '끝' → rule_after_swing 약공 → −208 (준 피해 0).
        #  애니가 바뀌어야 끝 (rule_after_swing의 3000번대 벗어남 경로는 그대로)
        return False
    limit = SWING_S
    land = getattr(foe, "windup_land_s", None)            # (getattr: test fakes carry only the Foe fields they need)
    if land and a in getattr(foe, "windup", ()):
        limit = max(SWING_S, land + LAND_PAD)
    return age > limit


def _keep_lock(F, T) -> None:
    """
    ── 1:1 싸움은 락온한 채로 ([MoKa] 2026-10-12) ──────────────────────
     · "강공 할때는 락온이 필수야. 않그러면 동작이 느려서 상대가 먼저 피하는데, 강공하면 모션이 상대를 따라 가기 때문에
       그래도 맞힐 확률이 올라가." → 강공 직전에만 락온 (0.5–1.5 s 늦음) 대신 "2번으로 해": 확실한 1:1이면 싸움 내내 락온
     · 1:1 = ALONE_R 안에 깨어 있는 다른 적 없음 (양손 전환과 같은 기준). 둘째가 붙으면 풀고 (락온은 한 놈만 보게 함), 끝나면 푼다 (done)
     · R3는 카메라 중앙에 가까운 놈을 잡는다 → 몸·카메라가 목표를 볼 때만 누름 (CamFollow가 싸움 중 카메라를 목표에 맞춰 둠).
       못 잡은 R3는 카메라를 몸 뒤로 돌리므로 LOCK_RETRY_S에 한 번만. 시야가 막히면 안 걸림 (docs/throwables.md: 건물 사이 0/7)
     · 매 틱 눌렀던 버튼을 뗌 (release_due): 싸움 루프는 스스로 떼지 않아 R3가 눌린 채 남으면 다음 R3가 안 먹음 (unlock 버그, 10-12)
    """
    mv = F.mv
    getattr(mv.pad, "release_due", lambda: None)()
    state, press = getattr(mv, "lock_state", None), getattr(mv.pad, "lock_on", None)
    if not LOCK_KEEP or state is None or press is None or T.now - F.lock_t < LOCK_RETRY_S:
        return
    st = state(F.ptr)
    # 콤보 시험은 여럿 있어도 지금 그놈에 락온 ([MoKa] 11-03 "콤보는 적을 락업 하는 게 필수야")
    want = T.h <= LOCK_KEEP_R and abs(T.dy) <= LOCK_KEEP_DY and (COMBO_ONLY or not _others_near(T.s, F.ptr, ALONE_R))
    if st == "other" or (st == "target" and not want):
        press()                                            # R3 is a toggle: off now, on the right one next time if still wanted
        F.lock_t, F.lock_n = T.now, F.lock_n + 1
        F.note("락온풀기", T.s, T.c)
        return
    if st != "none" or not want:
        return
    body = abs(math.degrees(M.rel_angle(T.p, T.c))) if T.p.heading is not None else 0.0
    cam_err = getattr(mv, "cam_err", None)
    cam = cam_err(T.s, T.c.x, T.c.z) if cam_err is not None else 0.0
    if body > M.LOCK_BODY_DEG or (cam is not None and abs(cam) > LOCK_KEEP_CAM_DEG):
        return
    press()
    F.lock_t, F.lock_n = T.now, F.lock_n + 1
    F.note("락온", T.s, T.c)


def _lock_release(mv, ptr) -> None:
    state = getattr(mv, "lock_state", None)
    if state is not None and state(ptr) != "none" and hasattr(mv, "unlock"):
        mv.unlock()


def _locked(F) -> bool:
    """Locked on the target — every heavy needs it ([MoKa] 2026-10-12, _keep_lock). Moves without a lock reading → True."""
    state = getattr(F.mv, "lock_state", None)
    return True if state is None else state(F.ptr) == "target"


def rule_shot(F, T):
    """Hit from afar while waiting or fighting — leave its line of fire (10-11 video review: 10-03e 52–58 s, −113 ×2 at the ramp
    flat while the shield soldier next to us was staggered — the ledge firebomb hollow). First in RULES so it sees every tick;
    it only ends the duel ('shot', Field.fight backs off out of the thrower's reach), never moves the stick itself."""
    s, p, now = T.s, T.p, T.now
    for x in s.hostile(SHOT_SCAN_R):
        if x.anim is not None and x.anim in M.ATTACK:
            F.swung[x.ptr] = now
    hp0, F.shot_hp = F.shot_hp, p.hp
    if hp0 is None or p.hp is None or hp0 - p.hp < SHOT_HP:
        return None
    fresh = now - F.t0 < SHOT_NEAR_S    # the swing that hit may have started before this duel (P-59, 061145 35.3 s)
    if any(M.horiz(p, x) < SHOT_NEAR_R and (now - F.swung.get(x.ptr, -1e9) < SHOT_NEAR_S or fresh and _awake_anim(x.anim))
           for x in s.hostile(SHOT_NEAR_R + 1.0)):
        return None                                        # a melee hit
    thr = [x for x in s.hostile(SHOT_SCAN_R) if M.horiz(p, x) >= SHOT_FAR_R and foes_.of(x.npc_param).thrower]
    if not thr:
        return None                                        # a melee lunge, a fall, fire on the floor, someone we can't see — not a thrower
    t = min(thr, key=lambda x: M.horiz(p, x))
    if t.ptr == T.c.ptr and _rush(F, s, T.c):
        F.log(f"      원거리 피격 −{hp0 - p.hp}: {t.npc_param} {M.horiz(p, t):.1f} m — 붙을 수 있는 화염병 할로우, 사선 밖으로 안 감 (M1006-17)")
        F.note("원거리피격:붙기", s, T.c)
        return None
    F.shots.append(now)
    again = sum(1 for t0 in F.shots if now - t0 < SHOT_AGAIN_S) >= 2
    hold = [x for x in s.hostile(SHOT_HOLD_R + 1.0) if M.horiz(p, x) < SHOT_HOLD_R and _awake_anim(x.anim) and abs(x.y - p.y) < 1.2]
    F.log(f"      원거리 피격 −{hp0 - p.hp}: {t.npc_param} {M.horiz(p, t):.1f} m (높이 {t.y - p.y:+.1f}, 애니 {t.anim})"
          + (f" — {hold[0].npc_param} {M.horiz(p, hold[0]):.1f} m가 붙어 있어 버팀" if hold and not again else " — 사선 밖으로"))
    if hold and not again:
        F.note("원거리피격:버팀", s, T.c)
        return None
    F.note("원거리피격", s, T.c)
    F.res.shot_from = (t.x, t.y, t.z, t.npc_param)
    return F.done("shot")


def rule_separate(F, T):
    """Two closed in together — split them and take one at a time (user 2026-09-26 (a)). Don't run during stagger/downed (openings) or from a one-hit kill."""
    pair = _pair_close(T.s, T.p, F.ptr, T.h)
    if (pair and F.nm is not None and F.sep_n < SEP_MAX and T.now - F.sep_t > SEP_COOLDOWN and T.a not in M.STAGGER
            and T.a not in M.DOWNED and T.c.hp > FINISH_HP):
        F.sep_t, F.sep_n = T.now, F.sep_n + 1
        r = _separate(F.mv, T.s, F.ptr, pair, F.nm, F.arena, F.cancel, F.trail)
        F.log(f"      떼어놓기 {F.sep_n}: {T.c.npc_param}({T.h:.1f} m) + " + ", ".join(f"{x.npc_param}({M.horiz(T.p, x):.1f} m, {x.anim})" for x in pair)
              + f" → {r}")
        F.note(f"떼어놓기:{r}", T.s, T.c)
        if r != "no_spot":
            return CONT
    return None


BOUNCE_CENTER_MIN = 0.2  # rule_wall_bounce: step to the passage middle only if it is at least this far
BOUNCE_TAP_SCALE = 0.45  # stick taps for that step (0.25 is inside the deadzone — 202047, Field._settle)


def rule_wall_bounce(F, T):
    """
    ── 벽에 튕긴 자리에서 같은 공격 반복 안 함 (P-139, [MoKa] 2026-11-08) ──────────────────────────────
     "무기가 벽에 부딪혀서 공격 실패함" · "가운데가 차라리 낫지" · "감지가 되면 다른데로 가야지" ·
     "한번은 이해가 되는데 무기가 벽에 부딪히면 다음 작업이 되야 하는데 않하고 반복하니 죽지"
     · 221120 구역 4: 송진 문 앞 같은 자리에서 약공 10번 — 맞힘 1, 벽에 튕김(303150) 3, 나가기 전 끊김 5 → 사망
     · 튕긴 자리 (Reflex.bounces, BOUNCE_SPOT_R 안)에 서 있으면 휘두르지 않고: ① 통로 가운데로 (좌우 바닥이 같아지게, 한 번)
       ② 그래도 그 자리면 뒤로 백스텝 (적을 넓은 데로 끌어냄) ③ 둘 다 못 하면 이 규칙은 비킴 (다른 규칙대로)
     · 그놈이 지금 휘두르는 중이면 비킴 — 방패가 먼저 (반사). 방패반격도 튕긴 자리에선 안 침 (Reflex.guard_counter)
     · 가운데가 벽에 안 걸린다는 건 MoKa 말 + 063807 시범(가운데 0.5/0.5 m에서 나이프 맞음)뿐 — 근접 휘두르기로 잰 건 아님
    """
    rf = F.reflex
    spot = rf.at_bounce(T.p) if rf is not None else None
    if spot is None or (T.a in M.ATTACK and T.h < NEAR):
        return None
    s, c, p = T.s, T.c, T.p
    if spot[3] == 0:
        spot[3] = 1
        room = nav.side_room(F.nm, p, c.x - p.x, c.z - p.z) if F.nm is not None and p.gx is not None else None
        if room is not None:
            right, left = room
            shift = (left - right) / 2.0                       # + = to my left
            if abs(shift) >= BOUNCE_CENTER_MIN:
                n = math.hypot(c.x - p.x, c.z - p.z) or 1.0
                lx, lz = -(c.z - p.z) / n, (c.x - p.x) / n     # left of facing the foe (nav.side_room: right = (fz, −fx))
                gx, gz = p.x + lx * shift, p.z + lz * shift
                if F.style.shield:
                    F.mv.guard(True)
                for _ in range(4):
                    sn = F.mv.snap(5.0)
                    if sn is None or sn.cam_yaw is None or math.hypot(sn.player.x - gx, sn.player.z - gz) < 0.15:
                        break
                    if any((x.anim or -1) in M.ATTACK and M.horiz(sn.player, x) < NEAR for x in sn.hostile(NEAR + 1.0)):
                        break
                    F.mv.pad.move(*F.mv.stick_to(sn, gx, gz, BOUNCE_TAP_SCALE))
                    time.sleep(0.12)
                    F.mv.pad.move(0.0, 0.0)
                    time.sleep(0.08)
                F.log(f"      벽 튕긴 자리 — 통로 가운데로 {shift:+.2f} m (오른쪽 {right} · 왼쪽 {left} m)")
                F.note("벽튕김가운데", s, c)
                return CONT
    if spot[3] <= 1 and p.heading is not None and nav.can_move(F.nm, p, math.sin(p.heading), math.cos(p.heading), 2.2):
        spot[3] = 2
        F.backstep_t = T.now
        F.mv.backstep()
        F.log("      벽 튕긴 자리 — 뒤로 백스텝 (넓은 데로 끌어냄)")
        F.note("벽튕김백스텝", s, c)
        return CONT
    if spot[3] < 3:
        spot[3] = 3
        F.log("      벽 튕긴 자리 — 옮길 데 없음, 다른 규칙대로")
    return None


def rule_finish_first(F, T):
    """Dies in one hit and isn't swinging now — hit before reflex (in front of an HP 18 foe, reflex just held the shield every tick and died)."""
    foe, a = F.foe, T.a
    if (T.c.hp <= FINISH_HP and a not in M.ATTACK and T.h <= F.weapon.reach and abs(T.dy) <= 1.0
            and not (foe is not None and foe.kick_when_idle and a == -1)
            and (T.p.sp or 0) >= FINISH_SP and F.mv.face(T.s, T.c, deg=30.0)):
        hit = _strike(F, T.s, T.c, n=1)
        F.record(hit)
        F.note("마무리", T.s, T.c)
        return F.killed_if(hit.dead)
    return None


FACE_FIRST_DEG = 35.0    # body this far off the target → this tick only turns toward it
FACE_FIRST_R = 10.0      # … when the target is within this
FACE_GUARD_R = 4.0       # … with the shield up if it is awake this close


def rule_face_first(F, T):
    """── 타겟이 정해지면 방향 정렬이 최우선 ([MoKa] 2026-10-01) ──────────────────
     · 몸이 타겟에서 FACE_FIRST_DEG 넘게 벗어나 있으면 이 틱은 돌기만 한다 (가까운 깨어 있는 적이면 방패 든 채로)
     · 10-01 구역 1: 다가오는 망자를 옆에 두고 다른 걸 하다 정면이 아닌 채로 맞음. 몸 방향은 가드 들 때만 맞추고 있었음
     · 내가 공격 동작 중이면 건너뜀 (그때 스틱은 안 먹음)
     · prep_reflex 뒤 (10-01 [cloud] 검토): 맨 앞이면 도는 틱마다 반사에 스냅이 안 들어감. 목표는 4 m 밖인데 옆 4.5 m 안 다른 적이
       휘두르면 그때도 방패 듦 (T.near45 — prep_reflex가 채움)"""
    s, c, p = T.s, T.c, T.p
    if c is None or p.heading is None or s.cam_yaw is None or T.h > FACE_FIRST_R:
        return None
    if not free_or_blocking(p.anim):   # own swing / roll etc. — guard-block (140 · 20140) can still turn
        return None
    if abs(math.degrees(M.rel_angle(p, c))) <= FACE_FIRST_DEG:
        return None
    other_swing = any((x.anim or -1) in M.ATTACK for x in getattr(T, "near45", ()))
    if F.style.shield and ((T.h < FACE_GUARD_R and not (9000 <= (c.anim or 0) < 9100)) or other_swing):
        F.mv.guard(True)
    F.mv.face(s, c, deg=FACE_FIRST_DEG / 2)
    F.note("방향", s, c)
    time.sleep(0.02)
    return CONT


def prep_reflex(F, T):
    """Feed the reflex and the shadow-kick logger; how long the target has been swinging (age)."""
    if F.reflex is not None:
        F.reflex.prefer = F.ptr
        F.reflex.update(T.s)
    T.age = F.reflex.attack_age(F.ptr) if F.reflex is not None else None
    F.shadow.note_anim(F.ptr, T.a, T.now)
    F.shadow.tick(T.now, T.s)
    T.near45 = [x for x in T.s.hostile(4.5) if x.ptr != F.ptr]
    if T.a in M.STAGGER:                                  # how long the target has been staggered (rule_stagger_punish, P-80)
        if F.__dict__.get("_stag_ptr") != F.ptr:
            F._stag_ptr, F._stag_t = F.ptr, T.now
        T.stag_age = T.now - F._stag_t
    else:
        F._stag_ptr, T.stag_age = None, None
    return None


COMBO_ONLY = False       # run.py --combo-only: every attack is roll_r1 / backstep_r1 / jump_r2 (_combo_strike; P-121 test)
JUMP_R = 3.5             # COMBO_ONLY: farther than this → jump attack (3.25 m forward, 11-03 room); BS_R..JUMP_R → roll attack (moves 2.9 m+)
JUMP_IN = 4.5            # COMBO_ONLY: a ranged foe (crossbowman) within this → roll attack (else jump attack) instead of walking in — start from range ([MoKa] 11-03 "미리 거리가 있을때 하면서 들어가야지"; roll+R1 moved 2.9–5.5 m in the room)
REPLAN = None             # COMBO_ONLY: Field sets it — rule_approach calls it (at most every 0.5 s) so the plan follows the group
_replan_t = 0.0
DRILL = None              # run.py --drill <attack>: only this attack, set up its conditions first (P-121, see _drill_setup)
DRILL_CROWD_R = 3.0       # drill: two or more awake foes this close → stop drilling this fight
DRILL_HURT = 0.3          # drill: lost this share of max HP in this fight → stop drilling it
DRILL_SETUPS = 8          # set-up moves per foe before giving up on the drilled attack for it
DRILL_BS_FAR = 5.0        # backstep drill: walk in only to within this, then wait for the foe to come
DRILL_BS_HOLD = 3.5       # … a step toward it after DRILL_BS_IDLE s of it not coming, never closer than this
DRILL_BS_IDLE = 3.0
# 진입 거리는 누른 순간이 아니라 공격이 닿을 때 기준 — 다가오는 놈은 그동안 더 옴 ([MoKa] 11-03 "실패 하더라도 거리를 미리 계산 하고 해야지").
# 누름→닿음 시간은 아직 안 잰 첫 값 (combo 이벤트의 h_now · v · h · h1로 맞춰 감)
ENTRY_LEAD = {"roll_r1": 0.9, "jump_r2": 0.8}
LOCK_WAIT_S = 4.0        # 콤보 전 락온을 이만큼 기다리고도 못 잡으면 락온 없이 침 (기록에 남김)
PLANNED: dict = {}


def _tech(c) -> str | None:
    """This foe's technique: the drill's, else the group plan's (--combo-only). Timing rules (jump · swing backstep) key off it,
    so a route run with --combo-only uses them per foe, not only in a one-attack drill ([MoKa] 11-04 "공격 기술을 적절한 타이밍에
    못 사용 한다는 것을 개선 해야해")."""
    return DRILL or (PLANNED.get(c.ptr) if COMBO_ONLY else None)
BS_WAIT = 0.0             # COMBO_ONLY: planned backstep combo but foe at 1.15–2.2 m → wait this long for it to come in        # COMBO_ONLY: foe ptr → planned attack, set by Field._group_plan (souls/group_plan.py) before the fight
BS_R = 2.2               # COMBO_ONLY: within this = 붙어 있음 (1.6 reach → 2.2 after "가까운데 구르기") → backstep attack first ([MoKa] 11-03 "적이 붙어 있으면 백스텝 콤보 사용해야지")
FOOTING = False          # run.py --footing: rule_footing on, rule_edge off (design-floor-check §3-A; [MoKa] 2026-10-11 answers to §7)
FOOT_STEP_M = 1.0        # one guarded step toward better footing (design §3-B 'step') …
FOOT_STEP_S = 0.4        # … this long on the stick (guarded walk ~2.5 m/s)
FOOT_STALL_M = 0.3       # stepped the same way for FOOT_STALL_S and moved less than this → rubbing a wall, rest FOOT_REST_S
FOOT_STALL_S = 1.0
FOOT_REST_S = 2.0
FOOT_CHECK_S = 0.1       # while the footing is fine, look again after this (danger: every tick)
_FLOORS: dict = {}       # id(NavMesh) → ground.Ground (NavMesh + walked cells) — rule_footing's floor, built once per map


def _floor(F):
    """rule_footing's floor: NavMesh + walked cells ([MoKa] 10-11 ③ — the ramp ledge is off the NavMesh but real floor), whether
    or not the rest of the fight reads the plain NavMesh (field.GROUND_IN_FIGHTS)."""
    nm = F.nm
    if nm is None or hasattr(nm, "walked"):
        return nm
    g = _FLOORS.get(id(nm))
    if g is None or g.nm is not nm:
        import ground
        g = _FLOORS[id(nm)] = ground.for_map(nm)
    return g


class _P:
    __slots__ = ("gx", "gy", "gz")

    def __init__(self, gx, gy, gz):
        self.gx, self.gy, self.gz = gx, gy, gz


def _foot_dir(g, p, foes):
    """Where to step: of 12 directions with floor FOOT_STEP_M out, the one whose landing has the best footing (on the floor map,
    nav.footing), not into a foe's body. foes: [(gx, gy, gz)]. → (dx, dz) unit or None."""
    best = None
    for k in range(12):
        a = k * math.pi / 6
        dx, dz = math.sin(a), math.cos(a)
        if not nav.can_move(g, p, dx, dz, FOOT_STEP_M):
            continue
        q = _P(p.gx + dx * FOOT_STEP_M, p.gy, p.gz + dz * FOOT_STEP_M)
        body = min((math.hypot(q.gx - x, q.gz - z) for x, _y, z in foes), default=9.0)
        if body < 0.8:
            continue
        st = nav.footing_state(g, q, foes)
        score = st["foot"] + (0.0 if st["on"] else -1.0) - 0.3 * len(st["push"]) + 0.05 * min(body, 3.0)
        if best is None or score > best[0]:
            best = (score, dx, dz)
    return None if best is None else (best[1], best[2])


def rule_footing(F, T):
    """
    ── 턱 끝에선 치기보다 자리 먼저 (P-58 · P-49, docs/design-floor-check.md §3-A, [MoKa] 2026-10-11) ──────────
     발밑이 위험하면(바닥 지도 = NavMesh + 걸어 본 자리에서 발밑에 바닥이 없음, 또는 발 디딜 곳이 좁은데(footing < 0.6) 3 m 안
     적에게 밀리면 1.5 m 뒤에 바닥이 없음) 더 넓은 바닥 쪽으로 방패 든 채 한 걸음. MoKa 답:
      ① 적이 휘두르는 중엔 막을 수 없는 공격(foes.unblockable — 도끼 망자 3009, P-58이 이것에 밀려 떨어짐)일 때만 움직임,
        막을 수 있는 휘두름은 지금처럼 막고 끝나면 옮김 · ② rule_after_swing 앞 · ③ NavMesh + 걸어 본 자리 · ④ 구르기 없이 걸음만
     같은 쪽으로 1 s 걸었는데 0.3 m도 못 가면(벽) 2 s 쉼. 기록(experiments/footing_probe.py): 싸움 중 낙하 7번 모두 2~2.5 s 전부터 위험.
    """
    if not FOOTING:
        return None
    p, now = T.p, T.now
    g = _floor(F)
    if g is None or p.gx is None or p.gy is None or now < max(F.__dict__.get("_foot_rest", 0.0), F.__dict__.get("_foot_next", 0.0)):
        return None
    ox, oz = p.gx - p.x, p.gz - p.z                        # local → the floor map's world coords (same offset as the player's)
    near = [x for x in T.s.hostile(nav.PUSH_FOE_R + 1.0) if x.hp > 0 and M.horiz(p, x) < nav.PUSH_FOE_R and abs(x.y - p.y) < 1.2
            and not (x.anim is not None and 9000 <= x.anim < 9100)]
    foes = [(x.x + ox, x.y, x.z + oz) for x in near]
    st = nav.footing_state(g, p, foes)
    if not st["danger"]:
        F._foot, F._foot_next = None, now + FOOT_CHECK_S   # ~2 ms on narrow ground (ramp) — not every tick while safe
        return None
    swinging = [x for x in near if (x.anim or -1) in M.ATTACK]
    if swinging and not any(x.anim in foes_.of(x.npc_param).unblockable for x in swinging):
        return None                                        # ① a blockable swing: block it (reflex / rule_block), step when it ends
    d = _foot_dir(g, p, foes)
    if d is None:
        return None                                        # nowhere better within a step — fight on as before
    dx, dz = d
    run = F.__dict__.get("_foot")
    if run is None or dx * run[0] + dz * run[1] < 0.7:     # a new direction (> ~45° off) — restart the stall watch
        run = F._foot = (dx, dz, now, p.x, p.z)
    elif now - run[2] > FOOT_STALL_S and math.hypot(p.x - run[3], p.z - run[4]) < FOOT_STALL_M:
        F._foot, F._foot_rest = None, now + FOOT_REST_S
        F.note("발밑:막힘", T.s, T.c)
        return None
    if now - F.__dict__.get("_foot_log", 0.0) > 2.0:
        F._foot_log = now
        why = "발밑 바닥 없음" if not st["on"] else f"발 디딜 곳 {st['foot']:.0%}, 밀리면 떨어짐 ({len(st['push'])}명)"
        F.log(f"      발밑 위험 — {why} → {math.degrees(math.atan2(dx, dz)):+.0f}° 쪽으로 방패 든 채 한 걸음"
              + (f" (막을 수 없는 공격 {swinging[0].anim})" if swinging else ""))
    F.mv.guard(True)
    F.mv.pad.move(*F.mv.stick_to(T.s, p.x + dx * FOOT_STEP_M, p.z + dz * FOOT_STEP_M, 0.8))
    time.sleep(FOOT_STEP_S)
    F.mv.pad.move(0.0, 0.0)
    F.note("발밑", T.s, T.c)
    return CONT


# ── 휘두름 백스텝: MoKa 시범 기준 (155254 직접 플레이, 성공 3번 — 패드 120 Hz · 애니 30 Hz, 클립 확인 전) ──
#  · B는 판정을 기다리지 않고 그놈이 ~2.2–2.3 m에 왔을 때 (다가오는 중이거나 휘두름 시작 +0.23 s 안), R1은 백스텝 중 B+0.53–0.73 s에
#    미리 넣음 → 304500이 690 끝(+0.79 s)에 나와 이어진 3001 · 3008 중에도 맞힘 (받은 0, 3번 모두 처치)
#  · 그 전 봇 방식 (142619 · 143026): 판정 0.30 → 0.15 s 전 B (= 시작 +0.7 s 안팎) · 이어지는 휘두름엔 백스텝만 · R1은 판정 끝 뒤
#    → 누름 6, 피함+맞힘 2, 맞교환 1, 못 피함 3. 시범에서도 시작 +0.5 s 넘어 누른 것(183 · 198 · 206 s)은 맞음
SWING_BS_R = 2.3         # B를 누르는 순간 이 거리 (MoKa 시범 2.2–2.3 m) — 다가오는 놈은 장전해서 그 시각에 (SWING_BS_ARM)
SWING_BS_ARM = 0.25      # 다가오는 놈이 이 안에 2.3 m에 닿으면 장전하고 그 시각에 B (_armed_wait) — 183549: 0.12는 3 m/s 놈의 창(0.36 m)을 틱이 건너뜀 → 1.7 m에서 누름
SWING_BS_POLL = 0.01     # 장전 중 보는 간격
SWING_BS_LAT = 0.15      # B 입력 → 690 보임 (155254)
# 160317: 0.9 m에서 누른 것은 3003에 그대로 맞음 (−160), 1.4 m 이상은 피함 4/4 → 이보다 가까우면 백스텝으로 못 벗어남 (막기에 맡김)
SWING_BS_MIN = 1.2
# P-130 ([MoKa] 11-04 "Yes, guard"): 휘두르기 시작한 놈에 1.8 m 넘어서 B → 11-04 로그 집계 피함+맞힘 3 · 못 피함 9 (−1210);
#  1.8 m 안은 10 · 6 (−815) → 휘두름 갈래는 이 거리 넘으면 B 안 누르고 가드 (다가올 때 장전 갈래는 그대로)
SWING_BS_SWING_MAX = 1.8
SWING_BS_V = 0.5         # 이보다 빨리 다가오는 놈만 (서 있는 놈엔 안 함 — 표대로)
SWING_BS_EARLY = 0.35    # 휘두름 시작 뒤 이만큼까지만 누름 (시범: +0.23 s 성공, +0.5 s 넘으면 맞음)
SWING_BS_R1 = 0.6        # B 뒤 이만큼에 R1 (시범 0.53–0.73 s)
SWING_BS_COOL = 1.5      # 한 놈에 이만큼 안에 다시 안 함
SWING_BS_SP = 50         # 이보다 기력이 적으면 안 함 (142619: 기력 27–45에서 누름)
# 뛰어들며 찌르는 공격 (duel_sim.LUNGES 3005–3007, 2 m 파고듦) — 백스텝으로는 거리가 안 벌어짐: 막기에 맡김
# (143026 68.8 s: 255010 3005 1.3 m, 판정 0.14 s 전 B → 맞힘 53 · 맞음 −305; 155254 330.9 s 시범도 3005에 −159)
SWING_BS_SKIP = {3005, 3006, 3007}
SWING_BS_NPC = (2540,)   # 휘두름 시작 뒤 B는 망자 254000대만 (시범 값) — 173404: 255010 3000 +0.09 s 2.3 m 그대로 맞음 (−385); 다가올 때는 됨 (160734 1.9·1.6 m)


def _armed_wait(F, s, c, arm: float, near: float | None = None, cancel_r: float | None = None):
    """Wait up to arm s for the foe to reach `near` (SWING_BS_R), polling every SWING_BS_POLL s; farther than cancel_r → cancel.
    → (s, c, 'time' | 'swing' | 'near' | 'cancel')."""
    near = SWING_BS_R if near is None else near
    cancel_r = near + 0.6 if cancel_r is None else cancel_r
    snap, find = getattr(F.mv, "snap", None), getattr(F.mv, "find", None)
    t_end = time.time() + arm
    for _ in range(int(arm / SWING_BS_POLL) + 2):
        left = t_end - time.time()
        if left <= 0:
            return s, c, "time"
        time.sleep(min(SWING_BS_POLL, left))
        if snap is None or find is None:
            continue
        s2 = snap(cancel_r + 1.0)                          # 190741: snap 5.3 m가 6.6 m 놈을 못 봐 장전 취소
        c2 = find(s2, c.ptr) if s2 is not None else None
        if c2 is None or c2.hp <= 0:
            return s, c, "cancel"
        s, h2 = s2, M.horiz(s2.player, c2)
        c = c2
        if (c2.anim if c2.anim is not None else -1) in M.ATTACK:
            return s, c, "swing"
        if h2 <= near:
            return s, c, "near"
        if h2 > cancel_r:
            return s, c, "cancel"
    return s, c, "time"


JUMP_LO, JUMP_HI = 2.6, 4.8   # 누를 때 서 있는 그놈 거리 — 점프 3.25 m (11-03 방) · 3.52 m (191414) 이동 + 무기 ~1.3 m; 밑이면 넘어 감
                              # (191414 #3: 5.7 m에서 눌러 그놈 옆 0.35 m 지나 내려앉음, [MoKa] "넘어갔어")
                              # 224536 #4: LO 3.4면 0번 — 망자는 2.5–3.2 m에 서고 헛친 뒤 3.2 m → 2.6으로 내려 잼 (몸에 막혀 멈추는지)
JUMP_FRONT = 4.3          # 앞에 이만큼 바닥 (140920 점프 드릴 #1 낙사)
JUMP_SP = 65              # 224853: 303600 점프 한 번에 기력 48 → −17 (≈65, 배틀 액스)
JUMP_DODGE_MIN = 1.6      # 백스텝만은 이보다 멀 때 — 225538: 3000 시작 1.4 m에서 B → 1.05 m에서 −83 (못 벗어남); 1.7 · 2.3 m는 피함
JUMP_DODGE_SP = JUMP_SP + 20
JUMP_SAVE_CROWD_R = 6.0   # 드릴 밖 계획 점프: 다른 놈이 이 안에 있으면 rule_jump_save (방패 내림) 안 함   # 백스텝만은 이만큼 있을 때 — 백스텝 ≈20 (98 → 78) 쓰고도 헛친 틈에 점프할 기력이 남게
JUMP_COOL = 2.0
JUMP_WAIT_FAR = 7.0       # 점프 드릴: 이보다 멀면 다가감, JUMP_HI..이 사이에선 기다림 (_drill_setup DRILL_WAIT)
JUMP_HOLD = 4.1           # 점프 드릴: 안 오면 이 거리까지 다가가서 섬 (창 JUMP_LO..JUMP_HI 가운데)


def rule_jump_drill(F, T):
    """
    ── 점프 공격 드릴 (P-121, [MoKa] 2026-11-03 "점프 공격으로 넘어가자") ──────────────────────────────
     MoKa가 준 정리: 패링 불가 · 강인도 감쇄·가드 브레이크 (방패 든 놈) · 중거리에서 순간 전진 (헛친 뒤 후딜레이에 파고듦) ·
     단타 배율 최고 · 헛치면 후딜레이가 길어 뒤잡기 당함 → "확실한 딜 타이밍에 단타로 치고 빠지는 용도".
     · 쓰는 때: 서 있는 놈 (다가오는 속도 < SWING_BS_V)이 JUMP_LO..JUMP_HI · 그놈 휘두름이 판정 끝을 지난 후딜레이(헛침) 때.
       휘두르는 중(판정 전·중)엔 안 함.
     · 다가오는 놈엔 안 함: 191414 #3에서 1.4 m/s로 재고 장전해 눌렀는데 점프 동안 그놈이 3.6 m/s로 달려 들어와 거리가
       5.5 → 1.0 m, 옆으로 넘어감 ([MoKa] "넘어갔어"). 망자는 다가오다 가속하니 속도로 착지 거리를 못 맞춤.
     · 락온 · 기력 JUMP_SP · 앞 바닥 JUMP_FRONT m · 높이 차 1 m 안. 매번 "jump_drill" 이벤트 (h · v · 내 애니·그놈 애니 시간 · 피해).
    """
    if _tech(T.c) != "jump_r2":
        return None
    s, c, h = T.s, T.c, T.h
    if h > JUMP_WAIT_FAR or abs(getattr(T, "dy", 0.0) or 0.0) > 1.0:
        return None
    v = _closing(F, c, h)
    swinging = T.a in M.ATTACK and T.age is not None
    w = SW.window(c.npc_param, T.a) if swinging else None
    whiff = swinging and w is not None and T.age > w[1] + 0.1
    if swinging and not whiff:
        return None
    vv = max(0.0, v)
    if not whiff and vv >= SWING_BS_V:
        return None
    if not JUMP_LO <= h <= JUMP_HI:
        return None
    last = F.__dict__.setdefault("_jump_t", {})
    if T.now - last.get(c.ptr, -99.0) < JUMP_COOL:
        return None
    lock = getattr(F.mv, "lock_state", lambda _p: "?")(c.ptr)
    sp = getattr(T.s.player, "sp", None) if T.s is not None else None
    what = f"헛침 {T.a} +{T.age:.2f} s" if whiff else f"서 있음 {v:.1f} m/s"
    if lock in ("none", "other") or (sp is not None and sp < JUMP_SP):
        last[c.ptr] = T.now
        why = f"락온 {lock}" if lock in ("none", "other") else f"기력 {sp} < {JUMP_SP}"
        F.log(f"      점프 공격 안 함: {c.npc_param} {what} {h:.1f} m — {why}")
        F.events("jump_drill", npc=c.npc_param, anim=T.a, v=round(v, 2), h=round(h, 2), what="skip", why=why)
        return None
    # 225538 ①: LB (방패) 든 채 앞+R2 → 선 채 R2 303300 (26)이 나감 (ctl pad btn 256); 나머지 둘은 btn 0 → 303600 점프.
    # 내 애니가 -1 (서 있음·걷기)일 때만 — 막기 경직 140 · 백스텝 후딜 690 중엔 앞+R2가 선 채 R2 303300으로 나감
    # (232507 #7: 690 중 누름 → 303300). 다음 틱에 다시 봄 (쿨다운 안 씀).
    if getattr(s.player, "anim", -1) not in (-1, None):
        return None
    F.mv.guard(False)
    held = getattr(getattr(F.mv, "pad", None), "guard_held", lambda: False)
    if held():
        time.sleep(0.04)
        if held():
            F.events("jump_drill", npc=c.npc_param, h=round(h, 2), what="skip", why="방패 안 내려감")
            return None
    last[c.ptr] = T.now
    t0 = time.time()
    hit = F.mv.combo("jump_r2", s, c, nm=F.nm, need_front=JUMP_FRONT)
    dmg, taken = getattr(hit, "dmg", 0), getattr(hit, "taken", 0)
    verdict = ("못 함 — " + (hit.skipped or "") if not hit.presses else
               "맞힘" if dmg > 0 and taken == 0 else "맞힘, 맞음" if dmg > 0 else "헛침" if taken == 0 else "헛치고 맞음")
    F.log(f"      점프 공격 [{c.npc_param} {what}] {h:.1f} m 락온 {lock}: {verdict} (준 {dmg}, 받은 {taken})"
          + (f" | 내 애니 {[a for _t, a in hit.my_anims][:6]} 그놈 {[a for _t, a in hit.e_anims][:6]}" if hit.presses else ""))
    F.events("jump_drill", npc=c.npc_param, anim=T.a, age=round(T.age, 3) if swinging else None, v=round(v, 2), h=round(h, 2),
             lock=lock, what="press" if hit.presses else "skipped", verdict=verdict,
             skipped=hit.skipped, dmg=dmg, taken=taken, dead=getattr(hit, "dead", False), t_press=round(t0, 3),
             my_anims=[[round(t_, 2), a] for t_, a in hit.my_anims][:10], e_anims=[[round(t_, 2), a] for t_, a in hit.e_anims][:10])
    if not hit.presses:
        return None
    F.record(hit)
    F.note("점프공격", s, c)
    return F.killed_if(hit.dead)


def rule_jump_dodge(F, T):
    """
    ── 점프 드릴: 붙어서 휘두르면 백스텝만 (P-121 190741, [MoKa] 11-03 "점프 드릴이라고 하면서 뒤잡만 하고 있네") ──────────
     190741: 놈이 0.7–2.2 m에 붙으면 드릴 포기 → 표대로 → 뒤잡기. 붙은 놈의 휘두름 시작에 B만 (R1 없음) → 헛친 후딜레이에
     거리가 2.4–4.3 m 생기면 rule_jump_drill이 점프 (헛침 갈래). 조건은 휘두름 백스텝과 같음 (망자 · SWING_BS_MIN..R · 시작
     SWING_BS_EARLY s 안 · 뒤 바닥 2.6 m).
    """
    if _tech(T.c) != "jump_r2":
        return None
    s, c, h = T.s, T.c, T.h
    swinging = T.a in M.ATTACK and T.age is not None
    if (not swinging or T.a in SWING_BS_SKIP or T.age > SWING_BS_EARLY or not max(SWING_BS_MIN, JUMP_DODGE_MIN) <= h <= SWING_BS_R
            or int(getattr(c, "npc_param", 0) or 0) // 100 not in SWING_BS_NPC):
        return None
    last = F.__dict__.setdefault("_jdodge_t", {})
    if T.now - last.get(c.ptr, -99.0) < SWING_BS_COOL:
        return None
    p = s.player
    if (getattr(p, "sp", None) or 99) < JUMP_DODGE_SP:
        return None                                        # 224853: 기력 43에 백스텝 → 헛친 틈 2.6 m에 기력 21이라 점프 못 함
    last[c.ptr] = T.now
    if F.nm is not None and p.heading is not None and not nav.can_move(F.nm, p, math.sin(p.heading), math.cos(p.heading), 2.6):
        F.events("jump_drill", npc=c.npc_param, anim=T.a, h=round(h, 2), what="dodge_no_floor")
        return None
    F.mv.backstep()
    F.log(f"      점프 드릴: {c.npc_param} {T.a} +{T.age:.2f} s {h:.1f} m — 백스텝만 (헛친 뒤 점프)")
    F.events("jump_drill", npc=c.npc_param, anim=T.a, age=round(T.age, 3), h=round(h, 2), what="dodge")
    F.note("점프드릴백스텝", s, c)
    return CONT


def rule_jump_save(F, T):
    """
    ── 점프 드릴: 기력 모으기 ([MoKa] 11-03 "기력 아껴 봐", 방패로 막으면 기력이 많이 들어 다음 공격이 어려움) ──────────
     224853 #5: 백스텝 ≈20 · 막기 (내 애니 140) 한 번 ≈20 · 점프 ≈65. 백스텝·막기·표대로 공격이 이어져 기력 3–43에 머물고, 헛친 틈
     (2.6 m)에 점프할 기력이 없었음. 기력 < JUMP_DODGE_SP이고 그놈이 안 휘두를 때는 방패 내리고 (회복 −80 % 없앰) 마주 보고만
     섬 — 다른 공격 안 함. 휘두르면 아래 막기·반사 규칙이 그대로 막음.
    """
    if _tech(T.c) != "jump_r2":
        return None
    if not DRILL and sum(1 for x in T.s.hostile(JUMP_SAVE_CROWD_R) if x.hp > 0 and x.ptr != T.c.ptr
                         and abs(x.y - T.s.player.y) < 1.2) > 0:
        return None                                        # 계획 점프 (드릴 밖): 다른 놈이 가까이 있으면 방패 내리지 않음
    sp = getattr(T.s.player, "sp", None)
    if sp is None or sp >= JUMP_DODGE_SP or (T.a in M.ATTACK and T.age is not None):
        return None
    F.mv.guard(False)
    F.mv.face(T.s, T.c)
    F.note("점프기력모음", T.s, T.c)
    time.sleep(0.05)
    return CONT


def rule_swing_backstep(F, T):
    """
    ── 다가오는 놈에 백스텝 콤보 (P-121, [MoKa] 2026-11-03) ──────────────────────────────
     "적이 무기를 휘두를때 백스텝으로 피하면 적이 휘청 거리는데, 바로 공격이 들어가는게 핵심인데 이것을 감지 하고 반응이
      굉장히 빨라야 하는데" → MoKa 시범 (155254)대로:
     · 그놈이 다가와 닿을 때 SWING_BS_R m 안이거나, 그 거리에서 휘두르기 시작한 지 SWING_BS_EARLY s 안이면 바로 B,
       R1은 B+SWING_BS_R1 s (백스텝 중 미리 입력). 이어지는 휘두름이어도 공격 키는 누름 (시범 267.9 s: 3001 중에 맞힘).
     · 락온이 그놈에 없으면 안 함 ([MoKa] 11-03 "콤보는 적을 락업 하는 게 필수야"). 뛰어드는 찌르기(SKIP)엔 안 함.
     · 매번 "swing_bs" 이벤트에 h · v · 그놈 애니 · age · 결과를 남겨 시범 값과 맞춰 봄.
    """
    s, c, h = T.s, T.c, T.h
    if not (COMBO_ONLY and DRILL in (None, "backstep_r1")) or h > SWING_BS_R + 1.5:
        return None
    if not DRILL and PLANNED.get(c.ptr) not in (None, "backstep_r1"):
        return None
    v = _closing(F, c, h)
    swinging = T.a in M.ATTACK and T.age is not None
    if T.a in SWING_BS_SKIP or swinging and int(getattr(c, "npc_param", 0) or 0) // 100 not in SWING_BS_NPC:
        return None
    # ── 미리 준비하고 그중 하나를 작동 ([MoKa] 2026-11-03 "반응 속도가 빠른 사람은 즉각적으로 하지만, 아닌 사람은 몇가지 경우를
    #  준비하고, 미리 작업을 준비하고, 그 중 하나를 작동 시키는 방법을 사용해") ──────────────────────────────
    #  MoKa의 2.3 m는 B를 **누른 순간** 거리. 틱(0.05–0.1 s)마다 보면 6 m/s 놈은 한 틱에 0.6 m 와서 늘 늦거나 이름 →
    #  다가오는 놈이 SWING_BS_ARM s 안에 2.3 m에 닿으면 지금 장전 (락온·기력·쿨다운은 아래에서 먼저 확인), 그 시각까지 10 ms로 보며
    #  기다렸다 B. 그 사이 휘두르기 시작 → 바로 B, 멈추거나 멀어짐 → 취소.
    arm = 0.0
    if swinging:
        if h > SWING_BS_R or T.age > SWING_BS_EARLY:
            return None
        if h >= SWING_BS_SWING_MAX:
            F.mv.guard(True)
            if F.__dict__.get("_sbs_guard") != (c.ptr, T.a):
                F._sbs_guard = (c.ptr, T.a)
                F.log(f"      백스텝 콤보 안 함: {c.npc_param} {T.a} +{T.age:.2f} s {h:.1f} m — {SWING_BS_SWING_MAX} m 넘음, 가드 (P-130)")
                F.events("swing_bs", npc=c.npc_param, anim=T.a, age=round(T.age, 3), v=round(v, 2), what="far_guard", h=round(h, 2))
            return None
    elif v >= SWING_BS_V:
        arm = max(0.0, (h - SWING_BS_R) / v)
        if arm > SWING_BS_ARM:
            return None
    else:
        return None
    he = h - max(0.0, v) * arm
    if h < SWING_BS_MIN:
        return None
    last = F.__dict__.setdefault("_sbs_t", {})
    if T.now - last.get(c.ptr, -99.0) < SWING_BS_COOL:
        return None
    lock = getattr(F.mv, "lock_state", lambda _p: "?")(c.ptr)
    sp = getattr(T.s.player, "sp", None) if T.s is not None else None
    what = f"{T.a} +{T.age:.2f} s" if swinging else f"다가옴 {v:.1f} m/s"
    if lock in ("none", "other") or (sp is not None and sp < SWING_BS_SP):
        last[c.ptr] = T.now
        why = f"락온 {lock}" if lock in ("none", "other") else f"기력 {sp} < {SWING_BS_SP}"
        F.log(f"      백스텝 콤보 안 함: {c.npc_param} {what} {h:.1f} m — {why}")
        F.events("swing_bs", npc=c.npc_param, anim=T.a, age=round(T.age, 3) if swinging else None, v=round(v, 2), lock=lock,
                 what="no_lock" if lock in ("none", "other") else "low_sp", h=round(h, 2))
        return None
    last[c.ptr] = T.now
    w = SW.window(c.npc_param, T.a) if swinging else None
    if arm > 0:
        s, c, how = _armed_wait(F, s, c, arm)
        if how == "cancel":
            F.log(f"      백스텝 콤보 장전 취소: {c.npc_param} {what} {h:.1f} m — 멈춤/멀어짐")
            F.events("swing_bs", npc=c.npc_param, anim=T.a, v=round(v, 2), lock=lock, what="armed_cancel", h=round(h, 2), arm=round(arm, 3))
            return None
        what += f" · 장전 {arm:.2f} s → {how}"
    hit = F.mv.backstep_attack(s, c, F.nm, r1_at=time.time() + SWING_BS_R1)
    dmg, taken = getattr(hit, "dmg", 0), getattr(hit, "taken", 0)
    verdict = ("못 함 — " + (hit.skipped or "") if not hit.presses else
               "피함+맞힘" if dmg > 0 and taken == 0 else "맞힘, 맞음" if dmg > 0 else
               "피함, 못 맞힘" if taken == 0 else "못 피함")
    F.log(f"      백스텝 콤보 [{c.npc_param} {what}" + (f" 판정 {w[0]:.2f}–{w[1]:.2f} s" if w else "")
          + f"] {h:.1f} m (닿을 때 {he:.1f}) 락온 {lock}: {verdict} (준 {dmg}, 받은 {taken})"
          + (f" — {hit.skipped}" if hit.presses and hit.skipped else "")
          + (f" | 내 애니 {[a for _t, a in hit.my_anims][:6]} 그놈 {[a for _t, a in hit.e_anims][:6]}" if hit.presses else ""))
    F.events("swing_bs", npc=c.npc_param, anim=T.a, age=round(T.age, 3) if swinging else None, win=w, v=round(v, 2),
             lock=lock, h=round(h, 2), what="press" if hit.presses else "skipped", verdict=verdict, skipped=hit.skipped,
             dmg=dmg, taken=taken, dead=getattr(hit, "dead", False),
             my_anims=[[round(t_, 2), a] for t_, a in hit.my_anims][:10], e_anims=[[round(t_, 2), a] for t_, a in hit.e_anims][:10])
    if not hit.presses:
        return None
    F.record(hit)
    F.note("휘두름백스텝", s, c)
    return F.killed_if(hit.dead)


def rule_after_swing(F, T):
    """
    ── 휘두름이 끝나면 무조건 친다 ([MoKa] 2026-10-06) ──────────────────────────────
     "상대가 휘두르는 애니 끝나면 무조건 공격해야해. 가끔 보면 타이밍 안 맞는다고 다음 기다리는데, 적들이 몰려오는데
      다음 텀 기다리면 다대일 되서 좋을게 없어."
     · 끝 = 공격 애니(3000번대)에서 벗어난 틱, 또는 swing_over(SWING_S 넘게 이어진 공격, 떨어지기 전 windup은 아님 — P-66;
       prep_linger와 같은 기준). 그 뒤 AFTER_SWING_S 안
     · 전엔 rule_face_first(30° 넘으면 먼저 돌기)·rule_hit_first(방패병 제외, 닿는 거리 안만)·rule_wait_far(멀면 기다림)
       때문에 한 텀 쉬는 일이 있었다 → 여기선 AFTER_SWING_DEG 안이면 바로, 닿는 거리 + AFTER_SWING_STEP 안이면 한 걸음 들어가 친다
     · 방패병(kick_when_idle)은 발차기 → 약공(rule_attack과 같은 콤보), 옆에 다른 적이 있으면 한 번만 치고 방패(rule_hit_first와 같음)
    """
    a_raw, now = T.a, T.now
    tr = ctl.on()                                         # counter trace (record only, souls/counter_trace.py) — never steers
    prev = F.__dict__.get("_aprev")
    prev_from = F.__dict__.get("_aprev_from", "unknown")  # 관측용 메타데이터: 그 값이 어느 목표의 애니였나 (정책은 안 읽음)
    F._aprev, F._aprev_from = a_raw, F.ptr
    started = getattr(F.reflex, "_start", {}).get(F.ptr) if F.reflex is not None else None   # identifies this one attack
    over = swing_over(F.foe, a_raw, T.age)               # (same call, same place as before — kept for the trace)
    if over and F.__dict__.get("_swing_aged") != started:
        F._swing_aged, F._swing_aged_from = started, F.ptr
        F._swing_end_t, F._swing_end_from = now, F.ptr
        if tr:
            CT.window(F, T, "a", prev, prev_from, started)
    elif prev in M.ATTACK and a_raw not in M.ATTACK:
        F._swing_end_t, F._swing_end_from = now, F.ptr
        if tr:
            CT.window(F, T, "b", prev, prev_from, started)
    end_t = F.__dict__.get("_swing_end_t")
    if end_t is None:
        return None
    if now - end_t > AFTER_SWING_S:
        if tr:
            CT.expired(F, T, end_t)
        return None
    w, c, p = F.weapon, T.c, T.p
    # the old single `if (… or …)`, unrolled in the same order with the same short-circuit; `conds` keeps what was evaluated
    NE = "not_evaluated"
    conds = {"over_first": over, "target_alive": NE, "still_swinging": NE, "dy": NE, "h": NE, "reach_limit": round(w.reach + AFTER_SWING_STEP, 3),
             "sp": NE, "sp_min": w.sp_min, "other_swinging": NE, "my_anim": NE, "my_free": NE} if tr else None
    why = None
    if c is None or c.hp <= 0:
        why = "no_target"
    else:
        if tr:
            conds["target_alive"] = True
        if a_raw in M.ATTACK and not swing_over(F.foe, a_raw, T.age):
            why = "still_swinging"
        else:
            if tr:
                conds["still_swinging"] = False
                conds["dy"] = round(T.dy, 3)
            if abs(T.dy) > 1.0:
                why = "dy"
            else:
                if tr:
                    conds["h"] = round(T.h, 3)
                if T.h > w.reach + AFTER_SWING_STEP:
                    why = "too_far"
                else:
                    if tr:
                        conds["sp"] = p.sp
                    if (p.sp or 0) < w.sp_min:
                        why = "sp"
                    else:
                        osw = _other_swinging(T.s, F.ptr)
                        if tr:
                            conds["other_swinging"] = osw
                        if osw:
                            why = "other_swinging"
                        else:
                            if tr:
                                conds["my_anim"] = p.anim
                            free = free_or_blocking(p.anim)
                            if tr:
                                conds["my_free"] = free
                            if not free:
                                why = "my_anim"
    if why is not None:
        if tr:
            if why == "still_swinging":
                conds["still_swinging"] = True
            CT.blocked(F, T, why, conds)
        return None
    if not F.mv.face(T.s, c, deg=AFTER_SWING_DEG):
        if tr:
            conds["faced"] = False
            CT.turn_only(F, T, conds)
        time.sleep(0.02)
        return CONT                                    # way off — this tick turns, the next one (still in the window) strikes
    stepped = bool(T.h > w.reach and T.s.cam_yaw is not None)
    if stepped:
        F.mv.pad.move(*F.mv.stick_to(T.s, c.x, c.z, 0.8))
        time.sleep(min(0.35, 0.1 + (T.h - w.reach) * 0.2))
    F._swing_end_t = None
    s = F.mv.snap(10.0) or T.s
    c = F.mv.find(s, F.ptr) or c
    single = _others_near(s, F.ptr, SINGLE_HIT_R)
    n = 1 if single or getattr(F.foe, "backstep_only", False) else w.combo   # 백스텝 상대는 한 대씩 (MoKa M1109-76)
    kick = F.foe.kick_when_idle
    dec = None
    if tr:
        conds.update(faced=True, stepped=stepped, single=single)
        dec = CT.intent(F, T, s, c, "kick_combo" if kick else "strike(light, or wall heavy via _slam)", n, conds)
    try:
        if kick and not (DRILL and DRILL != "kick_combo"):   # 드릴 중엔 방패병도 그 공격으로 (133704: 255010에 kick+light — 드릴 밖)
            hit = F.mv.kick_combo(s, c, n=n)
        else:
            hit = _strike(F, s, c, n=n, sp_second=w.sp_min)
    except BaseException as ex:
        if tr:
            CT.outcome(F, dec, error=f"{type(ex).__name__}: {ex}")
        raise
    if tr:
        CT.outcome(F, dec, hit)
    if single:
        F.mv.guard(True)
    F.record(hit)
    F.note("휘두름 끝 반격", s, c)
    if hit.presses or hit.kind != "wait":                # 콤보 시험의 기다림 (P-128 가드)은 _combo_strike가 한 번만 적음
        F.log(f"      휘두름 끝 → {hit.kind}×{hit.presses} 피해 {hit.dmg}, 옆 {hit.others}, 내 피해 {hit.taken}")
    return F.killed_if(hit.dead)


def rule_guard_counter(F, T):
    """방패에 맞으면 바로 약공 (P-136) — 판단은 Reflex.guard_counter (걷기·제자리 방어 등 reflex.tick이 도는 곳 모두 같은 것).
    여기선 판단 루프 맨 앞 (prep_reflex 바로 다음)에서 불러 기록·로그만 붙인다. 같은 막기에 두 번 치지 않음 (reflex._gc_done)."""
    rf = F.reflex
    if rf is None:
        return None
    hit = rf.guard_counter(T.s, prefer=F.ptr)
    a, c, _, why = rf.gc_last or (None, None, None, None)
    if hit is None:
        if why is not None and rf.gc_last is not F.__dict__.get("_gc_logged"):
            F._gc_logged = rf.gc_last
            F.log(f"      방패에 맞음 ({a}) — 반격 안 함: {why}")
        return None
    F._gc_logged = rf.gc_last
    F.record(hit)
    F.note("방패반격", T.s, c)
    F.log(f"      방패에 맞음 ({a}) → light×{hit.presses} {c.npc_param} {M.horiz(T.p, c):.1f} m 피해 {hit.dmg}, 내 피해 {hit.taken} "
          f"내 애니 {hit.my_anims[:4]}")
    return F.killed_if(hit.dead) if c.ptr == F.ptr else CONT


def rule_early_kick(F, T):
    """Shield soldier early kick: 'shadow' only logs the candidate; 'act' (experiment only, no Foe data enables it) kicks one beat earlier
    (user 2026-09-26) — at the start of a slow-landing attack (3004), or just as post-attack stagger (3500) begins. Checked before reflex and lure."""
    foe, a, age, p = F.foe, T.a, T.age, T.p
    ek = getattr(foe, "early_kick", "off")
    cand = ek != "off" and _early_kick_candidate(
        foe, a, age, T.h, T.dy, p.sp or 0, F.weapon,
        any((x.anim or -1) in M.ATTACK and M.horiz(p, x) < 2.5 for x in T.near45))
    if cand and ek == "shadow":
        # Patch D: don't kick on raw anim alone — only log and fall through to the branches below (as if B8 never existed)
        F.shadow.observe(T.now, F.ptr, F.mv.tm.handle(F.ptr), T.c.npc_param, a, age, T.h, T.dy, p.sp, p.max_sp, len(T.near45), p.hp, T.c.hp)
    if cand and ek == "act" and not (DRILL and DRILL != "kick_combo") and F.mv.face(T.s, T.c, deg=30.0):
        F.kick_t = T.now
        why = f"{a} {age:.2f}s" if a in foe.windup else f"휘청 {a}"
        hit = F.mv.kick_combo(T.s, T.c, n=foe.punish_hits or F.weapon.combo)
        F.record(hit)
        F.note("빠른발차기", T.s, T.c)
        F.log(f"      빠른 발차기({why}) → {hit.kind}×{hit.presses} 피해 {hit.dmg}, 내 피해 {hit.taken}, 그놈 애니 {hit.e_anims[:4]}")
        return F.killed_if(hit.dead)
    return None


def rule_late_windup_block(F, T):
    """Too late — it lands soon (2.0–2.1 s after start). Treating it as 'standing' via SWING_S and kicking gets hit at that moment (−220·−323) → block."""
    if T.a in F.foe.windup and T.age is not None and T.age >= F.foe.windup_act_s and T.h < NEAR:
        F.mv.guard(True)
        F.mv.face(T.s, T.c)
        F.note("늦은windup막기", T.s, T.c)
        time.sleep(0.02)
        return CONT
    return None


def prep_linger(F, T):
    """If the 3000 series lasts beyond SWING_S it isn't swinging (it lingers 1.5–5.3 s after the attack ends — log analysis).
    The spear shield soldier (255002) stays in 3001 holding up its shield, so for 15 s we only blocked at 1.4 m and never kicked.
    Also: room for a backstab (wall / drop at its back → no backstab, normal rules)."""
    if swing_over(F.foe, T.a, T.age):
        T.a = -1
    foe = F.foe
    T.room = BACKSTAB and foe is not None and foe.circle_behind and T.now >= F.edge_until and _room_behind(F.nm, T.p, T.c)
    if T.room and _crowd(T.s, F.ptr) >= NO_BACKSTAB_N:
        # 둘 이상 붙었으면 뒤잡기로 돌지 않고 약공·방패 ([MoKa] 2026-10-01: 비밀 통로 지나 만나는 둘은 구조적으로 동시에 2:1 —
        # 약공·방패 플레이가 맞음). 도는 동안 다른 놈에게 맞음 (P-29: 셋에게 뒤잡기 4번 모두 실패, 사망)
        T.room = False
    # 벽·좁은 통로가 우선 — 배틀 액스(heavy_vertical)면 뒤잡기로 돌지 않고 강공 ([MoKa] 2026-09-28: "벽, 좁은 통로가 우선 순위를 높여줘",
    # 배틀 액스만 가능한 플레이, 다른 무기는 약공이 나음)
    walled = _walled(F.nm, T.p, T.c) if F.weapon.heavy_vertical and (_two_handed(F) or _shield_foe(F)) else None
    if walled is not None:
        T.room = False                                     # at a wall: no circling for a backstab (as before)
    T.wall = walled if walled is not None and _heavy_ok(F, T.s) else None   # …the heavy itself only one-on-one (_heavy_ok)
    return None


def rule_hit_first(F, T):
    """Hit first (user: "if you'd swung even once, that enemy would have backed off") — a hollow flinches (2000·2002) from one light attack and backs off.
    When it has just started attacking (within INTERRUPT_S) or is standing still. Shield soldiers excluded (blocked by shield); if another foe swings beside us, block first."""
    foe, a, age, w = F.foe, T.a, T.age, F.weapon
    if (foe.kind != "shield" and T.h <= w.reach and not (BACKSTAB_ONLY and T.room)
            and not (foe.circle_behind and F.res.dealt > 0 and a == -1 and F.circle_n < CIRCLE_MAX_SWEEPS) and abs(T.dy) <= 1.0 and (T.p.sp or 0) >= w.sp_min
            and (a == -1 or (a in M.ATTACK and age is not None and age < INTERRUPT_S
                             and (w.startup or 0.0) <= INTERRUPT_STARTUP_MAX))
            and not _other_swinging(T.s, F.ptr)
            and F.mv.face(T.s, T.c, deg=30.0)):
        single = _others_near(T.s, F.ptr, SINGLE_HIT_R)
        if _sleeper_heavy(F, T):
            F.log(f"      잠든 적 (HP {T.c.hp}) — 강공 한 방")
            hit = F.mv.heavy(T.s, T.c)
        elif single:
            # ── 옆에 다른 적이 있으면 한 번만 치고 방패 ([MoKa] 2026-10-03, P-39 (A)) ──────────
            #  · 수용소 위층 망자 둘: 2연타(약 2 s) 도중 4 m 옆 둘째가 붙어 −154 (10-03a), −116 (10-03f)
            #  · 한 번 치고 곧바로 방패 — 이어지는 건 휘청 반격·막기 규칙이 맡는다
            hit = _strike(F, T.s, T.c, n=1, swinging=a != -1)
            F.mv.guard(True)
        else:
            hit = _strike(F, T.s, T.c, n=w.combo, sp_second=w.sp_min, swinging=a != -1)
        F.record(hit)
        F.note("먼저치기", T.s, T.c)
        if hit.presses or hit.kind != "wait":                # 콤보 시험의 기다림 (P-128 가드)은 _combo_strike가 한 번만 적음
            F.log(f"      먼저 치기 → {hit.kind}×{hit.presses} 피해 {hit.dmg}, 옆 {hit.others}, 내 피해 {hit.taken}")
        if not hit.dead and not single:
            hit = _third(F, hit)
        return F.killed_if(hit.dead)
    return None


def _third(F, hit):
    """
    ── 2연타가 한 번 몫을 남기면 곧바로 3타째 ([MoKa] 2026-10-03, P-39 (1)) ──────────
     · 수용소 위층 망자(HP 69): 배틀 액스 약공 2연타가 매번 64 → HP 5. 그 틈에 반격(3000)이 시작돼
       rule_finish_first(휘두르지 않을 때만)가 못 끝내고, 옆 망자까지 와서 −154·−106 (10-03a), −212·−53 (10-03e)
     · 그래서 2연타 직후 HP ≤ FINISH_HP이고 닿는 거리면 그놈 동작과 상관없이 한 번 더 — 맞은 휘청(2006) 중이라 먼저 들어간다
    → the last hit (the third if it was swung, else the one given)."""
    s2 = F.mv.snap(10.0)
    c2 = F.mv.find(s2, F.ptr) if s2 is not None else None
    if (c2 is None or c2.hp <= 0 or c2.hp > FINISH_HP or M.horiz(s2.player, c2) > F.weapon.reach + THIRD_REACH_SLACK
            or (s2.player.sp or 0) <= 0):
        return hit
    hp0 = c2.hp
    hit3 = F.mv.light(s2, c2, n=1)
    F.record(hit3)
    F.note("3타째", s2, c2)
    F.log(f"      3타째 (HP {hp0}) → 피해 {hit3.dmg}, 내 피해 {hit3.taken}{' — 처치' if hit3.dead else ''}")
    return hit3


def _sleeper_heavy(F, T) -> bool:
    """
    ── 잠든 적 첫 타는 강공 ([MoKa] 2026-10-03, P-39) ──────────────────
     · 수용소 위층 문 뒤 망자 둘(250022, HP 69): 1 m 안까지 자다가 깸. 첫 놈을 치면 4 m 옆 둘째가 ~1 s 만에 붙는다
     · 09-29a: 한손 벽 강공 한 방(69)에 첫 놈 죽음 → 둘째와 1:1, 받은 피해 0
     · 10-03a: 약공 2연타 64 → HP 5 남음 → 둘이 같이 침, −154·−106, 최저 HP 25 %
     · 그래서 자는 적이 강공 한 방에 죽을 HP면 한손이어도 강공. 준비 0.86 s 동안 그놈은 자고 있다.
       관측된 배틀 액스 강공 피해는 대부분 69·75·85 (망자 HP 그대로) — 0·26·32도 있음 (빗나감·방패)
    """
    w = F.weapon
    return (HEAVY and w.heavy_vertical and T.a == -1 and T.c.hp <= SLEEPER_HEAVY_HP
            and (T.p.sp or 0) >= SLEEPER_HEAVY_SP and _asleep(F, T.c, T.now) and _locked(F))


def _do_backstab(F, T, s, c, label: str):
    F.circle_n += 1
    start = (s.player.x, s.player.y, s.player.z)
    r = _backstab(F.mv, s, c, F.cancel, F.nm, F.log)
    _back_to_safe(F.mv, F.nm, start, F.log, F.arena)
    if r in ("edge", "no_room"):
        F.edge_until = time.time() + 5.0
    F.note(f"뒤잡기:{r}", s, c)
    F.log(f"      {label} → {r}")
    return F.done("killed") if r == "stabbed" and F.orig_ptr is None else CONT


def rule_backstab_swing(F, T):
    """A hollow (circle_behind) swinging at us up close, nobody else swinging = the backstab moment (drill: 4 kills, all mid-swing).
    The reflex below blocked every such swing first, so the backstab check further down was never reached (27q: 3 hollows)."""
    if (T.room and T.a in M.ATTACK and F.circle_n < CIRCLE_MAX_SWEEPS
            and T.h <= BACKSTAB_REACH and abs(T.dy) <= 1.0 and not _other_swinging(T.s, F.ptr)):
        return _do_backstab(F, T, T.s, T.c, "뒤잡기(휘두를 때)")
    return None


def rule_reflex(F, T):
    """Reflex: if anyone within 2.5 m starts swinging, block head-on (or the backstep style's backstep attack)."""
    reflex = F.reflex
    if reflex is not None and reflex.tick(T.s):
        bh = getattr(reflex, "last_hit", None)
        if bh is not None:                                 # backstep attack (one move) result — record it
            reflex.last_hit = None
            F.record(bh)
            F.log(f"      백스텝 공격 → 피해 {bh.dmg}, 내 피해 {bh.taken} ({T.h:.1f} m) 내 애니 {bh.my_anims[:6]} 그놈 {bh.e_anims[:5]}")
            F.note("백스텝공격", T.s, T.c)
            return F.killed_if(bh.dead)
        F.note("반사", T.s, T.c)
        time.sleep(0.02)
        return CONT
    return None


def _walk_to_arena(F, T, label: str):
    p = T.p
    path = F.nm.find_path((p.x, p.y, p.z), tuple(F.arena))
    if not path:
        return None
    cancel = F.cancel
    r = F.mv.walk_path(nav.trim_path(path[1:], tuple(F.arena), within=0.8), F.nm, "walk",
                       stop=lambda sn: cancel() or any((x.anim or -1) in M.ATTACK and M.horiz(sn.player, x) < NEAR
                                                       for x in sn.hostile(NEAR + 1.0)))
    F.note(f"{label}:{r}", T.s, T.c)
    return CONT


def rule_lure(F, T):
    """Lure (user: "drag it to the terrain you want") — once it notices (moves or is close), back off to arena.
    Ramp spot #2 is where firebombs from the ledge above land; engaging there took 275 in 1 s (2026-09-24).
    A foe standing on a ledge (ramp #5 y -39 vs flat ground -49) won't come down — luring to flat ground or backing off just went up and down repeatedly (three 'stuck')."""
    T.ledge = F.arena is not None and abs(T.c.y - F.arena[1]) > LEDGE_DY
    p, a = T.p, T.a
    if (not F.pulled and not T.ledge and F.nm is not None and a not in M.ATTACK and (a != -1 or T.h < PULL_R)
            and math.dist((p.x, p.y, p.z), tuple(F.arena)) > 3.0):
        F.pulled = True
        return _walk_to_arena(F, T, "끌어오기")
    return None


def rule_edge(F, T):
    """Next to a cliff — go to a flat spot (it follows). Without arena, raise shield and face it:
    the NavMesh only blocks — it doesn't choose a step toward 'the wider ground' (evidence-grade gate, 2026-09-26)."""
    p, nm = T.p, F.nm
    if (not FOOTING and nm is not None and T.a not in M.ATTACK and T.now - F.move_t > 3.0 and p.gx is not None
            and nav.footing(nm, p)[0] < nav.FOOTING_MIN):
        F.move_t = T.now
        if F.arena is not None and not T.ledge and math.dist((p.x, p.y, p.z), tuple(F.arena)) > 1.5:
            if _walk_to_arena(F, T, "자리옮김"):
                return CONT
        F.mv.guard(True)
        F.mv.face(T.s, T.c, deg=20.0)
        F.note("가장자리방어", T.s, T.c)
        return CONT
    return None


def rule_estus(F, T):
    """Estus mid-fight (user: drink if safe). If close, backstep to open distance (when there's ground behind) and recheck next tick."""
    care, p, ptr = F.care, T.p, F.ptr
    if care is not None and T.now - F.care_t > CARE_RETRY and care.wants(T.s):
        if opening(T.s, ptr):
            F.care_t = T.now
            r = care.take(lambda sn: opening(sn, ptr))
            F.log(f"      싸우는 중 에스트: {r}")
            F.note("에스트", T.s, T.c)
            return CONT
        if (T.a not in M.ATTACK and T.h < OPEN_R and T.now - F.backstep_t > 2.0 and p.heading is not None and _others_quiet(T.s, ptr)
                and nav.can_move(F.nm, p, math.sin(p.heading), math.cos(p.heading), 2.2)):
            F.backstep_t = T.now
            F.mv.backstep()
            F.note("백스텝", T.s, T.c)
            return CONT
    return None


STAGGER_PAD = 0.1        # rule_stagger_punish: the blade must land this long before the foe's stagger (foes.Foe.stagger_s) ends


def _stagger_late(foe, w, stag_age) -> bool:
    """
    ── 휘청 끝물엔 안 침 (P-80, [MoKa] 2026-10-12 "가드와 공격이 미묘하게 안 맞아") ──────────────────
     · tradefix1 92 s: 255001 휘청 0.89 s째에야 SP 60이 차서 약공 → 칼날(클레이모어 startup 0.68 s) 전에 휘청이 끝나 3000이 먼저 −126 → 사망
     · 경과 + startup + STAGGER_PAD > foe.stagger_s 면 늦음 → 방패 들고 정면 유지 (다음 빈틈은 rule_after_swing 등이 잡음)
     · 9600(발차기 뒤 가드 깨짐)은 길이를 안 재서 그대로 침
    """
    if stag_age is None or w.startup is None:
        return False
    return stag_age + w.startup + STAGGER_PAD > getattr(foe, "stagger_s", 1.5)


def rule_stagger_punish(F, T):
    """Stagger = opening. If facing is right, hit at once. Not while another foe is swinging next to us — punishing the staggered shield soldier
    took -115 from a hollow's 3003 1.2 m away (dealt 4, 2026-09-27 27c P-8); the reflex blocks that swing instead and the stagger is taken next time.
    Heavy in a shield soldier's stagger opening (user 2026-09-25: "guard·heavy·guard") costs 90 stamina, so only when full (HEAVY_SP)."""
    a, w, p, foe = T.a, F.weapon, T.p, F.foe
    if _stagger_late(foe, w, getattr(T, "stag_age", None)) and T.h <= w.reach + 0.3 and abs(T.dy) <= 1.0:
        if F.style.shield:
            F.mv.guard(True)
        F.mv.face(T.s, T.c, deg=30.0)
        F.note("휘청늦음", T.s, T.c)
        time.sleep(0.02)
        return CONT
    if (a in M.STAGGER or a == M.GUARD_BROKEN) and not (BACKSTAB_ONLY and T.room) and T.h <= w.reach + 0.3 and abs(T.dy) <= 1.0 \
            and (p.sp or 0) >= w.sp_min and not _other_swinging(T.s, F.ptr):
        if F.mv.face(T.s, T.c, deg=30.0):
            if w.heavy_punish and foe.kind == "shield" and (p.sp or 0) >= HEAVY_SP and _locked(F) and not COMBO_ONLY:
                hit = F.mv.heavy(T.s, T.c)
            else:
                hit = _strike(F, T.s, T.c, n=foe.punish_hits or w.combo, sp_second=w.sp_min)
            F.record(hit)
            F.note("휘청반격", T.s, T.c)
            F.log(f"      휘청 → {hit.kind}×{hit.presses} 피해 {hit.dmg}, 옆 {hit.others}, 내 피해 {hit.taken}")
            if hit.dead and F.orig_ptr is None:
                return F.done("killed")
        else:
            F.note("휘청돌기", T.s, T.c)
        return CONT
    return None


def rule_evade(F, T):
    """Backstep style (user 2026-09-24: "experts use backsteps well, backstep + light attack"): reflex dodged the swing start with a backstep.
    Once the blade has passed (punish_after), step in and light attack; until then keep it in front, no shield."""
    style, a, age, w, p, h, s, c = F.style, T.a, T.age, F.weapon, T.p, T.h, T.s, T.c
    if style.evade and a in M.ATTACK and h < NEAR:
        if (age is not None and age >= style.punish_after and style.punish_min_r <= h <= w.reach + PUNISH_R and abs(T.dy) <= 1.0
                and (p.sp or 0) >= w.sp_min and F.mv.face(s, c, deg=30.0)):
            if h > w.reach and s.cam_yaw is not None:
                F.mv.pad.move(*F.mv.stick_to(s, c.x, c.z, 0.8))
                time.sleep(min(0.45, 0.12 + (h - w.reach) * 0.22))   # 2.5 m/s walk — for the remaining distance
                F.mv.pad.move(0.0, 0.0)
            hit = _strike(F, s, c, n=w.combo, sp_second=w.sp_min)
            F.record(hit)
            F.note("뒤치기", s, c)
            F.log(f"      헛친 뒤 → {hit.kind}×{hit.presses} 피해 {hit.dmg}, 내 피해 {hit.taken} ({h:.1f} m, {age:.2f} s)")
            return F.killed_if(hit.dead)
        F.mv.guard(False)
        F.mv.face(s, c, deg=25.0)
        F.note("피함대기", s, c)
        time.sleep(0.02)
        return CONT
    return None


def rule_block(F, T):
    """Swinging → block (only styles with a shield — rush just stood there taking hits: 8 s+ 0 attacks, 676 taken, 2026-09-25).
    Out of reach, approach with the shield up (blocking in place never reaches a foe swinging from afar, 3008 repeated).
    Not when a hollow swinging up close is a backstab moment (drill)."""
    s, c, p, h, a, w, nm = T.s, T.c, T.p, T.h, T.a, F.weapon, F.nm
    bs_swing = (T.room and a in M.ATTACK and F.circle_n < CIRCLE_MAX_SWEEPS
                and h <= BACKSTAB_REACH and abs(T.dy) <= 1.0)
    if F.style.shield and a in M.ATTACK and h < NEAR and not bs_swing:
        F.mv.guard(True)
        if h > w.reach + 0.3 and abs(T.dy) <= 1.0 and s.cam_yaw is not None and (
                nm is None or nav.can_move(nm, p, c.x - p.x, c.z - p.z, 0.8)):
            F.mv.pad.move(*F.mv.stick_to(s, c.x, c.z, 0.6))
            F.note("막으며다가감", s, c)
        elif M.quiet_aim(p, c, T.age):
            # ── 휘두름 끝날 무렵엔 스틱을 미리 놓는다 ([MoKa] 2026-10-06, 제안 A) ──────────
            #  · R1 앞엔 스틱을 놓고 STICK_RELEASE_S(0.16 s) 기다린다(앞 + R1 = 발차기). 막는 동안 face()가 20°만 벗어나도
            #    스틱을 건드려서, 틈이 나면 매번 그 0.16 s를 다 기다렸다 — 적 공격 애니 끝 → 우리 공격 애니 시작 0.33~0.34 s
            #    (10-03·10-06 블랙박스). [MoKa]: "반응은 빠르면 빠를수록 피격을 안 당하고, 공격 성공율은 더 올라가"
            #  · 공격 규칙의 겨누기 허용(30°) 안이면 더 돌지 않고 놓아 둔다 → 틈이 나면 R1이 곧바로 나감
            F.mv.pad.move(0.0, 0.0)
            F.note("막기", s, c)
        else:
            F.mv.face(s, c)
            F.note("막기", s, c)
        time.sleep(0.02)
        return CONT
    return None


def rule_downed(F, T):
    """Knocked down — shield up, face it, wait."""
    if T.a in M.DOWNED and T.a != M.GETTING_UP:
        F.mv.guard(True)
        F.mv.face(T.s, T.c)
        F.note("누움대기", T.s, T.c)
        time.sleep(0.03)
        return CONT
    return None


def prep_backstab_chance(F, T):
    """An idle hollow within backstab range is a backstab chance, not a reason to wait (user 2026-09-28: "never even tries" — 27g).
    "still" = not closing in (position-based anchors jittered, 27o) — user 2026-09-28: hollows never stand still, so not a condition any more.
    Logs why a close hollow was not taken."""
    s, c, p, h, a, now, still = T.s, T.c, T.p, T.h, T.a, T.now, F.still
    if still[0] != c.ptr or a != -1 or still[1] - h > BACKSTAB_STILL_M:
        still[:] = [c.ptr, h, 0.0, now]
    T.foe_still = now - still[3] >= BACKSTAB_STILL_S
    back_to_me = c.heading is not None and abs(math.degrees(M.rel_angle(c, p))) >= SNEAK_DEG
    T.bs_near = h <= BACKSTAB_REACH or (back_to_me and h <= SNEAK_R)
    T.foe_still = True
    T.backstab_chance = (T.room and (a == -1 or a in M.ATTACK or a in M.STAGGER) and T.foe_still and F.circle_n < CIRCLE_MAX_SWEEPS
                         and T.bs_near and abs(T.dy) <= 1.0)
    if T.backstab_chance and not (not _other_swinging(s, F.ptr) and (F.nm is None or nav.can_move(F.nm, p, c.x - p.x, c.z - p.z, 1.0))):
        F.note("뒤잡기안함:" + ("옆공격" if _other_swinging(s, F.ptr) else "바닥"), s, c)
    if not T.backstab_chance and F.foe is not None and F.foe.circle_behind and a == -1 and h <= BACKSTAB_REACH + 0.5:
        why = (f"안멈춤({now - still[3]:.1f}s)" if not T.foe_still else "횟수" if F.circle_n >= CIRCLE_MAX_SWEEPS else "멀다" if h > BACKSTAB_REACH
               else "높이" if abs(T.dy) > 1.0 else "?")
        F.note(f"뒤잡기안함:{why}", s, c)
    return None


def rule_wait_far(F, T):
    """Still far — don't approach, block in place and wait (wait_far). Shooters keep shooting if we wait — don't wait for them.
    Ends when it won't come (WAIT_APPROACH_S → close in, unless may_approach says the approach would leave the safe zone — Patch E-3),
    or when HP keeps dropping while the target isn't swinging (hit from elsewhere: 490→242 waiting 11 s, user 2026-09-25)."""
    s, c, p, h, now, foe = T.s, T.c, T.p, T.h, T.now, F.foe
    if h > F.weapon.reach and F.wait_far and not (foe and foe.ranged) and not T.backstab_chance:
        if F.wait_hp0 is None:
            F.wait_hp0 = p.hp
            F.wait_t0, F.wait_hmin = now, h
        if h < F.wait_hmin - WAIT_CLOSE_M:
            F.wait_t0, F.wait_hmin = now, h                  # approaching — keep waiting
        elif now - F.wait_t0 > WAIT_APPROACH_S and F.may_approach is not None and not F.may_approach(c, s):
            F.wait_t0 = now
            F.note("안옴→기다림유지", s, c)
        elif now - F.wait_t0 > WAIT_APPROACH_S:
            F.wait_far = False
            F.note("안옴→붙기", s, c)
            return CONT
        elif p.hp is not None and F.wait_hp0 - p.hp > WAIT_HURT_HP:
            return F.done("low_hp")
        # 135152 · 140006 · 140350: 다가오는 놈을 여기서 막고 기다리다 2.2–3.5 m를 그냥 흘려보냄 → 진입 0번, 구르기 콤보 못 만듦
        # ([MoKa] 11-03 "구르기 콤보 할 상황을 전혀 못 만드네") — 콤보 시험에선 기다리는 중에도 진입 거리면 침
        r = _entry_try(F, T)
        if r is not None:
            return r
        if F.style.shield:
            F.mv.guard(True)
        F.mv.face(s, c)
        F.note("기다림", s, c)
        time.sleep(0.03)
        return CONT
    return None


CLOSE_WIN = 0.35   # closing speed = slope of distance over the last this many s (needs CLOSE_MIN_N samples over ≥ CLOSE_MIN_S)
CLOSE_MIN_N, CLOSE_MIN_S = 3, 0.12


def _closing(F, c, h: float) -> float:
    """How fast this foe comes at us (m/s, + = closer). Called every fight tick (run loop) as well as by the rules.

    ── 다가오는 속도 (P-121, [MoKa] 2026-11-03 "다가 오는 속도가 있는데, 봇이 이것을 계산 못하는 것으로 보여") ──────────
     · 예전: 규칙 안에서만, 3.8 m 안에 들어온 뒤에야 재기 시작 + 두 점 지수평활 → 기록 v 대부분 0–1.3 m/s
       (160317–173956 swing_bs 이벤트), MoKa 시범 155254는 255010 ~6 m/s · 254002 ~2.8 m/s.
     · 지금: 매 틱 거리 표본을 쌓고 최근 CLOSE_WIN s 직선 기울기. 표본이 모자라면 예전 두 점 식 (_hv)."""
    now = time.time()
    hs = F.__dict__.setdefault("_hs", {}).setdefault(c.ptr, [])
    if not hs or now - hs[-1][0] >= 0.02:
        hs.append((now, h))
    while hs and now - hs[0][0] > 2 * CLOSE_WIN:
        hs.pop(0)
    hist = F.__dict__.setdefault("_hv", {})
    t0, h0, v0 = hist.get(c.ptr, (None, None, 0.0))
    pts = [(t_, h_) for t_, h_ in hs if now - t_ <= CLOSE_WIN]
    if len(pts) >= CLOSE_MIN_N and pts[-1][0] - pts[0][0] >= CLOSE_MIN_S:
        mt = sum(t_ for t_, _ in pts) / len(pts)
        mh = sum(h_ for _, h_ in pts) / len(pts)
        den = sum((t_ - mt) ** 2 for t_, _ in pts)
        v = -sum((t_ - mt) * (h_ - mh) for t_, h_ in pts) / den if den > 0 else v0
    elif t0 is not None and 0.05 <= now - t0 <= 1.0:
        v = 0.5 * v0 + 0.5 * (h0 - h) / (now - t0)
    else:
        v = v0 if t0 is not None and now - t0 <= 1.0 else 0.0
    if t0 is None or now - t0 >= 0.05:
        hist[c.ptr] = (now, h, v)
    return v


def _entry_h(F, c, h: float) -> float:
    """Distance when the entry attack lands: now minus what the foe walks in meanwhile (never less than 0)."""
    lead = ENTRY_LEAD.get(DRILL or PLANNED.get(c.ptr) or "", 0.9)
    return max(0.0, h - max(0.0, F.__dict__.get("_hv", {}).get(c.ptr, (0, 0, 0.0))[2]) * lead)


def _entry_try(F, T):
    """COMBO_ONLY: strike the entry combo now if the foe will be inside the entry window when it lands (None = not now)."""
    s, c, h = T.s, T.c, T.h
    if COMBO_ONLY:
        _closing(F, c, h)
    if _tech(c) == "backstab":
        return None                                        # 계획 뒤잡: 진입 콤보로 뛰어들지 않고 오게 둠 (뒤잡 규칙이 돌아 들어감)
    if (COMBO_ONLY and BS_R < _entry_h(F, c, h) <= CTB.ENTRY_MAX and abs(T.dy) <= 1.0 and (T.p.sp or 0) >= F.weapon.sp_min
            and F.mv.face(s, c, deg=30.0)):
        # 걸어 붙은 다음에 고르지 말고 거리 있을 때 진입 콤보로 들어감 (P-121, [MoKa] 11-03 "미리 거리가 있을때 하면서 들어가야지")
        hit = _combo_strike(F, s, c, phase="entry")
        if hit.presses:
            F.record(hit)
            F.note(hit.kind, s, c)
            return F.killed_if(hit.dead)
    return None


def rule_approach(F, T):
    """Close in (a backstab chance circles in itself). Stuck when neither distance nor height difference improves for 8 s
    (45 s of "붙기:stopped" at 1.7–1.9 m height difference, 2026-09-25). Refuses an approach that leaves the safe zone (Patch E-2)."""
    s, c, h, now = T.s, T.c, T.h, T.now
    if h > F.weapon.reach and not T.backstab_chance:
        F.last_dmg_t = now                                 # stalemate counts only within reach (walking 42 m counted as 'stalemate')
        if h < 3.0 and abs(T.dy) <= 1.2:
            F.best_h, F.best_t = h, now                    # truly within reach (height too) — not stuck
        elif F.best_h is None or h < F.best_h - 0.5:
            F.best_h, F.best_t = h, now
        elif now - F.best_t > 8.0:
            return F.done("stuck")
        if F.may_approach is not None and not F.may_approach(c, s):
            F.log(f"      다가가지 않음 — {c.npc_param} ({c.x:.1f}, {c.y:.1f}, {c.z:.1f}) 는 안전 구역 밖 (Patch E-2)")
            return F.done("unsafe_approach")
        global _replan_t
        if COMBO_ONLY and REPLAN is not None and now - _replan_t > 0.5:
            _replan_t = now
            try:
                REPLAN()
            except Exception as e:                         # 계획은 기록용 — 싸움을 멈추지 않음
                F.log(f"      계획 다시 못 함: {e!r}")
        if COMBO_ONLY and F.plan_for != c.ptr:
            F.plan_for = c.ptr                             # 한 놈에 한 번: 붙기 전에 계획부터 ([MoKa] 11-03 "플랜 없이 마구잡이")
            F.log("      " + CTB.engage_line(h, F.foe, c.anim))
        r = _entry_try(F, T)
        if r is not None:
            return r
        r = _approach(F.mv, F.weapon, s, c, F.nm, F.foe, F.cancel, F.log, may_approach=F.may_approach,
                      rush=F.foe is foes_.FIREBOMB_HOLLOW and _rush(F, s, c))
        F.last_dmg_t = time.time()                         # time spent closing in isn't stalemate (one walk took 17 s)
        F.note(f"붙기:{r}", s, c)
        if r == "dead":
            return F.done("me_dead")
        return CONT
    return None


def rule_finish(F, T):
    """Dies in one hit — hit even if a bit short on stamina (guard broke while a shield soldier held out 4 s at HP 10).
    A shield soldier standing with shield up blocks even the finisher (22 → 21 → 20, 114 counter) — kick instead."""
    if (T.c.hp <= FINISH_HP and (T.p.sp or 0) >= FINISH_SP and not (F.foe.kick_when_idle and T.a == -1)
            and F.mv.face(T.s, T.c, deg=30.0)):
        hit = _strike(F, T.s, T.c, n=1)
        F.record(hit)
        F.note("마무리", T.s, T.c)
        return F.killed_if(hit.dead)
    return None


def rule_stamina(F, T):
    """Low stamina — lower shield (recovery −80 %, wiki) and stand keeping it in front (backing off without lock-on turned our back to it)."""
    if (T.p.sp or 0) < F.weapon.sp_min:
        F.mv.guard(False)
        F.mv.face(T.s, T.c)
        F.note("SP회복", T.s, T.c)
        time.sleep(0.05)
        return CONT
    return None


def prep_face(F, T):
    """Face it (CONT while turning), then read it again for the attack rules below. (p, h, dy stay from the start of the tick.)"""
    if not F.mv.face(T.s, T.c):
        F.note("돌기", T.s, T.c)
        time.sleep(0.02)
        return CONT
    s = F.mv.snap(SEEK_R)
    c = F.mv.find(s, F.ptr) if s else None
    if c is None:
        return CONT
    a = c.anim if c.anim is not None else -1
    if a in M.ATTACK and F.reflex is not None and swing_over(F.foe, a, F.reflex.attack_age(F.ptr) or 0.0):
        a = -1                                             # 3000 series lingering in guard stance — treat as standing (kick)
    T.s, T.c, T.a = s, c, a
    T.behind_deg = abs(math.degrees(M.rel_angle(c, s.player))) if c.heading is not None else 0.0
    return None


def rule_backstab(F, T):
    """Circle behind with lock-on and backstab (human demos, see BACKSTAB_*). Past CIRCLE_MAX_SWEEPS tries, normal attacks."""
    s, c, p, a = T.s, T.c, T.p, T.a
    if (T.room and (a == -1 or a in M.ATTACK or a in M.STAGGER) and T.foe_still and F.circle_n < CIRCLE_MAX_SWEEPS and T.bs_near
            and abs(T.dy) <= 1.0 and not _other_swinging(s, F.ptr)
            and (F.nm is None or nav.can_move(F.nm, p, c.x - p.x, c.z - p.z, 1.0))):
        return _do_backstab(F, T, s, c, "뒤잡기")
    F.circle_n = 0
    return None


def _at_wall(nm, p) -> bool:
    """Our back is within WALL_AT of a wall (Navmesh.wall_dist). No NavMesh / can't tell → True (don't leave the fight for it)."""
    wd = getattr(nm, "wall_dist", None)
    if wd is None:
        return True
    try:
        return wd(p.x, p.y, p.z) < WALL_AT
    except Exception:
        return True


def _walled(nm, p, c) -> float | None:
    """Distance from us or the foe (whichever is closer) to a wall, if within WALL_R — else None.
    Navmesh.wall_dist (real walls only); border_dist counted seams between NavMesh pieces too — MoKa's wall spot read 'wall 0.08 m'
    at a seam with the real wall 1.76 m off (2026-09-30, [MoKa]: use wall_dist). A NavMesh without wall_dist → border_dist."""
    for name in ("wall_dist", "border_dist"):
        fn = getattr(nm, name, None)
        if fn is None:
            continue
        try:
            a, b = fn(p.x, p.y, p.z), fn(c.x, c.y, c.z)
        except Exception:
            return None
        if a is None or b is None:
            continue
        d = min(a, b)
        return d if d < WALL_R else None
    return None


def _two_handed(F) -> bool:
    """Right weapon held in two hands (grip 3). Unreadable → False."""
    try:
        return F.mv.tm.grip() == 3
    except Exception:
        return False


def _shield_foe(F) -> bool:
    return F.foe is not None and F.foe.kind == "shield"


def _others_near(s, ptr, r: float) -> bool:
    """Another awake foe (not the target, not asleep or downed — standing still counts) within r m at our level."""
    p = s.player
    return any(x.ptr != ptr and x.hp > 0 and M.horiz(p, x) < r and abs(x.y - p.y) < 2.0
               and not (9000 <= (x.anim or 0) < 9100) and (x.anim if x.anim is not None else -1) not in M.DOWNED
               for x in s.hostile(r + 1.0))


def _heavy_ok(F, s) -> bool:
    """Wall heavy allowed: already two-handed with nobody else within HEAVY_CLEAR_R, or a shield soldier one-on-one (we'd switch
    to two hands for it — only with nobody else within ALONE_R). [MoKa] 2026-10-01: "3.5 m 안에 적이 있으면 양잡은 좋지 않음.
    1:1 확실한 상황에서 양잡" — 09-30c 343 s: two hands + heavy + light next to a second shield soldier (3.2 m, idle) took 3.2 s
    as one block, dealt 12, took 362."""
    if _others_near(s, F.ptr, HEAVY_CLEAR_R):
        return False
    return _two_handed(F) or (_shield_foe(F) and not _others_near(s, F.ptr, ALONE_R))


def _slam(F, s, c, swinging: bool = False) -> float | None:
    """Wall distance if the vertical heavy is the move now (heavy_vertical weapon, wall within WALL_R, SP ≥ WALL_HEAVY_SP), else None.

    ── 벽 강공 조건 ([MoKa] 2026-09-30) ──────────────────────────────
     · 강공은 양손으로 — 준비가 0.86 s라 맞을 위험을 지는 만큼 보상이 커야 한다
     · 방패병: 한손이면 먼저 양손으로 바꾸고 강공 → 약공 (_shield_combo). 양손 강공이 가드를 깨고 약공이 이어 들어감 ([MoKa] 경험).
       09-30 벽 자리 시험의 피해 15·준비 중 −145는 한손 강공이 방패에 막힌 것 (wall-heavy-2026-09-30a, guard 스타일 = 한손)
     · 다른 적: 이미 양손일 때만 강공, 한손이면 약공
     · 양손 전환은 확실한 1:1에서만(ALONE_R 6 m 안 다른 적 없음), 3.5 m 안 다른 적이 있으면 벽 강공 안 함 ([MoKa] 2026-10-01, _heavy_ok)
     · 적이 휘두르는 중에 끊어 치기로는 안 씀 (강공은 느림)"""
    w = F.weapon
    if (not HEAVY or not w.heavy_vertical or swinging or (s.player.sp or 0) < WALL_HEAVY_SP or not _heavy_ok(F, s)
            or not _locked(F)):
        return None
    return _walled(F.nm, s.player, c)


HEAVY_CLEAR_R = 3.5      # no wall heavy with another awake foe this close ([MoKa] 2026-10-01)
SLEEPER_HEAVY_HP = 75    # opening heavy on a sleeping foe only if one heavy kills it (Battle Axe heavy: 69/75/85 seen, _sleeper_heavy)
SLEEPER_HEAVY_SP = 60    # heavy costs 50 (+20 on a ground hit)
SLEEP_SEEN_S = 1.0       # watched lying still this long in this fight before it counts as asleep
SLEEP_MOVE_M = 0.3       # moved more than this from where it lay → awake
ALONE_R = 6.0            # switch to two hands only one-on-one: nobody else awake within this (FOE_R of the walk checks)
GRIP_WAIT_S = 0.6        # two_hand_right: the grip changes ~0.4 s after the toggle (control.Pad.two_hand_right)


def _shield_combo(F, s, c) -> "M.Hit":
    """Shield soldier by a wall: two hands (toggle if one-handed), heavy, then one light right away — one Hit for the pair.
    Stays two-handed for the rest of this fight; Field.fight sets the style's grip again at the next fight."""
    mv = F.mv
    if not _two_handed(F):
        try:
            g = mv.tm.grip()
        except Exception:
            g = None
        if g != 1:                                     # unreadable: a blind toggle could turn two hands into one
            return mv.light(s, c, n=1)
        mv.pad.two_hand_right()
        for _ in range(int(GRIP_WAIT_S / 0.05)):
            if _two_handed(F):
                break
            time.sleep(0.05)
        if not _two_handed(F):
            F.log("      양손 전환 안 됨 — 약공")
            return mv.light(s, c, n=1)
        F.log("      방패병: 양손으로")
    hit = mv.heavy(s, c)
    if hit.dead:
        return hit
    s2 = mv.snap(10.0)
    c2 = mv.find(s2, c.ptr) if s2 is not None else None
    if c2 is None or c2.hp <= 0 or M.horiz(s2.player, c2) > F.weapon.reach + 0.3:
        return hit
    li = mv.light(s2, c2, n=1)
    return M.Hit("heavy+light", presses=hit.presses + li.presses, dmg=hit.dmg + li.dmg, dead=li.dead, taken=hit.taken + li.taken,
                 e_anims=hit.e_anims + li.e_anims, my_anims=hit.my_anims + li.my_anims, others=hit.others + li.others)


def _combo_strike(F, s, c, phase: str = "hit") -> "M.Hit":
    """
    ── 콤보만 쓰는 시험 (P-121, [MoKa] 2026-11-03 "구르기 콤보, 백스텝 콤보, 점프 공격 만 이용해봐") ──────────
     · 무엇을 쓸지는 souls/combo_table.py 표 (거리·적 종류·적 상태 → 순서, 칸마다 출처) — "이 거리, 이 지형에서는 이 공격"
     · 표의 것을 다 못 하면 공격 없음 — 단 붙었는데 바닥 때문에 막힌 때만 기본 약공 ([MoKa] 11-03 "기본 약공",
       combo_table.fallback). 한 번 할 때마다 "combo" 이벤트: 칸 키, 고른 것, 못 쓴 이유,
       내 애니·그놈 애니, 피해, 판정과 이유 (combo_table.judge — "수행후 실패 이유, 성공 이유") → combo_report.py
     · 거리 기준은 방 안 실측(점프 3.25 m · 구르기 2.9–5.5 m · 백스텝 약공 1.5–1.8 m)에서 잡은 첫 값
    """
    p = s.player
    if phase == "hit" and M.my_attack(p.anim):
        # 내 공격 동작이 아직 끝나지 않음 — 지금 누르면 콤보가 안 되고 보통 약공으로 이어짐 (132637 160.5 s: 303150 중 백스텝 콤보 →
        # [303150, 2035, 303000], 그 사이 −155). 동작이 끝날 때까지 다음 콤보를 누르지 않음
        return M.Hit("wait", skipped="내 공격 동작 중")
    h, anim0 = M.horiz(p, c), c.anim
    h_now, v = h, F.__dict__.get("_hv", {}).get(c.ptr, (0, 0, 0.0))[2]
    if phase == "entry":
        h = _entry_h(F, c, h)                              # 표·드릴 거리는 닿을 때 거리로 (ENTRY_LEAD)
    lock = getattr(F.mv, "lock_state", lambda _p: "?")(c.ptr)
    front = h_now + 0.6          # 앞 바닥은 그놈 몸 조금 너머까지만 — 난간 끝 석궁병에 3 m 검사가 매번 막음 (11-03 121319 164 s, 공격 0)
    back_ok = front_ok = None
    if F.nm is not None and p.heading is not None:
        back_ok = nav.can_move(F.nm, p, math.sin(p.heading), math.cos(p.heading), 2.6)
        front_ok = nav.can_move(F.nm, p, c.x - p.x, c.z - p.z, min(3.0, front))
    k = CTB.key(h, F.foe, anim0, back_ok, front_ok)
    if DRILL:
        setup = _drill_setup(F, s, c, k, h, back_ok, front_ok, phase)
        if setup is not None:
            return setup
    moves, src = CTB.entry_plan(k) if phase == "entry" else CTB.plan(k)
    if DRILL and F.__dict__.get("_drill_n", {}).get(c.ptr, 0) <= DRILL_SETUPS:
        moves, src = [DRILL], f"드릴 {DRILL} (MoKa 11-03 \"내가 원하는 특정 공격을 유도 할 수 있어야\")"
    planned = PLANNED.get(c.ptr)
    # 132052: 1.5 s 기다려도 3/3 안 들어옴 (그놈이 1.5 m에 서서 침) → BS_WAIT 0 (끔), 코드는 남김
    if BS_WAIT > 0 and phase == "hit" and planned == "backstep_r1" and k["dist"] == "reach" and k["state"] != "swing":
        # 계획이 백스텝 콤보인데 1.15–2.2 m — 바로 약공으로 바꾸지 말고 그놈이 들어올 때까지 가드 든 채 BS_WAIT s
        # (131637: 계획 백스텝 → 1.16·1.51 m에서 약공 = 계획 안 지킴 2번)
        w = getattr(F, "bs_wait", None)
        if w is None or w[0] != c.ptr:
            F.bs_wait = w = (c.ptr, time.time())
            F.log(f"      계획 백스텝 콤보 — {h:.1f} m, {BS_WAIT:.1f} s 동안 {CTB.BS_MAX} m 안으로 오길 기다림")
        if time.time() - w[1] < BS_WAIT:
            F.mv.guard(True)
            return M.Hit("wait", skipped="계획: 백스텝 거리 기다림")
    # 계획한 공격을 표보다 먼저 — 단 이 단계에 맞는 것만 (진입: 구르기·점프 / 붙음: 백스텝·발차기), 휘두르는 놈엔 표대로
    fits = planned in (("roll_r1", "jump_r2") if phase == "entry" else ("backstep_r1", "kick_combo", "light"))
    # P-132: 붙어서 튕긴 놈 (방패병 말고)엔 계획이 백스텝 콤보여도 표대로 바로 약공 (MoKa 11-04 "바로 약공")
    bounced = phase == "hit" and k["state"] == "open" and k["kind"] != "shield" and moves[:1] == ["light"]
    if fits and not DRILL and k["state"] != "swing" and not (planned == "backstep_r1" and k["dist"] == "reach") and not bounced:
        moves, src = [planned] + [m for m in moves if m != planned], "계획 → " + src
    if phase == "entry" and not moves:
        return M.Hit("entry", skipped="진입 없음 — " + src)
    if phase == "hit" and not moves and k["state"] == "swing":
        # P-128: 표가 "휘두르는 놈엔 안 침"인데 그냥 서 있었음 — 040915 구역 2: 254011 3006 1.3 m 앞에서 "쓸 수 있는 콤보 없음" 54번, 가드 없이 섬
        #  → 가드 들고 기다림 (휘두름 끝 반격은 다음 규칙이 함). 같은 놈·같은 애니엔 한 번만 적음
        F.mv.guard(True)
        if getattr(F, "swing_guard", None) != (c.ptr, anim0):
            F.swing_guard = (c.ptr, anim0)
            F.log(f"      휘두르는 중 ({anim0}, {h_now:.1f} m) — 콤보 안 함, 가드 들고 기다림 ({src})")
        return M.Hit("wait", skipped="휘두름 — 가드")
    why, hit, used = [], None, None
    # ── 콤보는 락온한 채로 ([MoKa] 11-03 "콤보는 적을 락업 하는 게 필수야") ──────────────────
    #  락온이 그놈에 안 걸렸으면 콤보를 누르지 않고 기다림 (_keep_lock이 R3를 누름). LOCK_WAIT_S 넘게 못 잡으면 락온 없이 치고 기록
    if COMBO_ONLY and lock in ("none", "other") and any(m != "light" for m in moves):
        lw = F.__dict__.setdefault("_lock_wait", {})
        t0 = lw.setdefault(c.ptr, time.time())
        if time.time() - t0 < LOCK_WAIT_S:
            F.mv.guard(True)
            return M.Hit("wait" if phase == "hit" else "entry", skipped=f"락온 먼저 ({lock})")
        if lw.get(("logged", c.ptr)) is None:
            lw[("logged", c.ptr)] = True
            F.log(f"      락온 {LOCK_WAIT_S:.0f} s 못 잡음 ({lock}) — 락온 없이 콤보")
    for name in moves:
        if name == "kick_combo":
            hit = F.mv.kick_combo(s, c, n=F.weapon.combo)
        elif name == "light":
            hit = F.mv.light(s, c, n=1)
        elif name == "backstep_r1":
            hit = F.mv.backstep_attack(s, c, F.nm, front=min(2.2, front))
        else:
            hit = F.mv.combo(name, s, c, nm=F.nm, need_front=min(3.0, front))
        if hit.presses:
            used = name
            break
        why.append(f"{name}: {hit.skipped}")
    drilling = DRILL and F.__dict__.get("_drill_n", {}).get(c.ptr, 0) <= DRILL_SETUPS
    if used is None and phase == "hit" and not drilling and CTB.fallback(k, why):
        hit = F.mv.light(s, c, n=1)
        if hit.presses:
            used = "light"
            moves, src = moves + ["light"], src + " → " + CTB.NO_FLOOR_FALLBACK[1]
    if phase == "entry" and used is None:
        if getattr(F, "entry_why", None) == (c.ptr, tuple(why)):
            return hit                                     # 같은 놈·같은 이유로 진입 못 함 — 매 틱 다시 적지 않음
        F.entry_why = (c.ptr, tuple(why))
    s1 = F.mv.snap(2.0) if used else None
    c1 = next((x for x in s1.chars if x.ptr == c.ptr), None) if s1 is not None else None
    h1 = M.horiz(s1.player, c1) if c1 is not None else None
    verdict, reason = CTB.judge(used, hit, why, h_now, h1, anim0, F.weapon.reach)
    no_combo = CTB.why_not_combo(used, why, k, h) if used == "light" else None
    if no_combo and BS_WAIT > 0 and planned == "backstep_r1" and k["dist"] == "reach":
        no_combo = f"계획 백스텝 콤보였지만 {BS_WAIT:.1f} s 기다려도 {CTB.BS_MAX} m 안으로 안 옴 ({h:.1f} m)"
    if no_combo:
        reason += f" | 콤보 안 한 이유: {no_combo}"      # [MoKa] 11-03 "일반 공격을 한 경우 콤보를 못한 이유도 평가에 넣어줘"
    flag = lambda v: "O" if v else "X" if v is False else "?"
    cell = f"{k['dist']}/{k['kind']}/{k['state']} 뒤{flag(back_ok)} 앞{flag(front_ok)}"
    F.log(f"      {'진입' if phase == 'entry' else '콤보'} [{cell}] {h_now:.1f} m"
          + (f" (다가옴 {v:.1f} m/s → 닿을 때 {h:.1f} m)" if phase == "entry" else "") + f" 락온 {lock} → {used or '없음'}"
          + (f" (계획 {planned}{'' if used == planned else ' — 안 지킴'})" if planned else "") + f": {verdict} — {reason}"
          + (f" | 내 애니 {[a for _t, a in hit.my_anims][:6]}" if used else ""))
    F.events("combo", **k, phase=phase, h=round(h, 2), h_now=round(h_now, 2), v=round(v, 2), lock=lock, h1=None if h1 is None else round(h1, 2), foe_anim=anim0, npc=c.npc_param,
             plan=moves, src=src, planned=planned, followed=None if planned is None else used == planned, used=used, skipped=why, no_combo=no_combo, verdict=verdict, reason=reason,
             dmg=getattr(hit, "dmg", 0), taken=getattr(hit, "taken", 0), dead=getattr(hit, "dead", False),
             my_anims=[a for _t, a in hit.my_anims] if used else [], e_anims=[a for _t, a in hit.e_anims][:8] if used else [])
    return hit if hit is not None else M.Hit("combo", skipped="표에 없음")


# 드릴 공격마다 맞는 거리 (방 실측 + 오늘 경사로 판정: 백스텝 콤보 헛침 1.2 m+, 구르기 2.9–5.5 m 이동, 점프 3.25 m 이동)
DRILL_BAND = {"backstep_r1": (0.0, SWING_BS_R), "kick_combo": (0.0, 1.6), "light": (0.0, 1.8),
              "roll_r1": (CTB.NEAR_R, CTB.MID_R), "jump_r2": (CTB.MID_R, CTB.ENTRY_MAX)}


DRILL_BS_TWO_HAND = True   # backstep drill: two hands for a hollow one-on-one (_drill_grip)
DRILL_GRIP_COOL = 1.5      # s between grip toggles


def _drill_grip(F, s, c) -> None:
    """
    ── 백스텝 드릴의 그립: 망자 1:1이면 양손, 아니면 한손·방패 (P-121 · P-123) ──────────────────────────────
     · MoKa 시범 155254의 공격 애니는 전부 304xxx (양손) — 304500이 2.0–2.9 m에서 이어진 3001 중에 맞힘. 봇 한손 303500은
       183917에서 1.8·2.0 m 휘두름 시작에 피하고 못 맞힘 2/2.
     · 182029: 경사로 전체를 양손으로 돌려 255010(방패병)에게 사망 → 망자(SWING_BS_NPC)이고 ALONE_R 안에 다른 놈이 없을 때만.
     · 바꾸는 건 거리를 두고 기다리는 동안만 (토글 ~0.4 s, control.Pad.two_hand_right). 읽을 수 없으면 안 건드림.
    """
    if not DRILL_BS_TWO_HAND:
        return
    try:
        g = F.mv.tm.grip()
    except Exception:
        return
    if g not in (1, 3) or time.time() - F.__dict__.get("_grip_t", 0.0) < DRILL_GRIP_COOL:
        return
    want3 = int(getattr(c, "npc_param", 0) or 0) // 100 in SWING_BS_NPC and not _others_near(s, c.ptr, ALONE_R)
    if (g == 3) == want3:
        return
    F._grip_t = time.time()
    F.mv.pad.two_hand_right()
    F.log(f"      드릴 그립: {'양손 (망자 1:1)' if want3 else '한손·방패 (' + ('망자 아님' if int(getattr(c, 'npc_param', 0) or 0) // 100 not in SWING_BS_NPC else '다른 놈 근처') + ')'}")
    F.events("drill_grip", npc=c.npc_param, two=want3)


def _drill_setup(F, s, c, k, h, back_ok, front_ok, phase):
    """
    ── 드릴: 원하는 공격을 유도 (P-121, [MoKa] 2026-11-03) ──────────────────────────────
     "이 초반 공격은 내가 원하는 특정 공격을 유도 할 수 있어야해. 가장 쉬운 장소에 약한 상대 들이 잖아. 이게 않되면 뭔가 문제가 있는거야."
     · 다른 공격으로 바꾸지 않는다. 조건이 안 맞으면 조건부터 만든다: 휘두르는 중 → 기다림 · 뒤 바닥 없음 → 바닥 있는 자리로 ·
       멀다 → 다가감 · 이미 붙음(구르기·점프) → 벌리지 않고 이 놈은 표대로 (거리 있을 때 침). 한 놈에 DRILL_SETUPS번까지, 그 뒤엔 "유도 실패"와 이유.
     · 한 번 할 때마다 "drill_setup" 이벤트 (무엇을, 왜) → 공격까지 몇 단계, 어디서 막히는지가 남음.
    → None = 지금 친다, or a Hit("setup"/"wait") = 이번 틱은 준비만
    """
    lo, hi = DRILL_BAND.get(DRILL, (0.0, 9.0))
    n = F.__dict__.setdefault("_drill_n", {})
    if phase == "entry" and DRILL not in ("roll_r1", "jump_r2"):
        return M.Hit("entry", skipped="드릴: 진입 공격 아님 — 걸어서")
    if n.get(c.ptr, 0) >= DRILL_SETUPS:
        if n.get(c.ptr) == DRILL_SETUPS:
            n[c.ptr] += 1
            F.log(f"      드릴 {DRILL} 유도 실패 — {DRILL_SETUPS}번 준비해도 조건 안 됨 ({h:.1f} m) → 이 놈은 기본 싸움")
            F.events("drill_setup", attack=DRILL, npc=c.npc_param, what="give_up", h=round(h, 2))
        return None if phase == "hit" else M.Hit("entry", skipped="드릴 포기")
    p = s.player
    crowd = sum(1 for x in s.hostile(DRILL_CROWD_R + 1.0) if x.hp > 0 and (x.anim or -1) not in (-1,)
                and M.horiz(p, x) < DRILL_CROWD_R and abs(x.y - p.y) < 1.2)
    lost = (F.hp_start or 0) - (p.hp or 0)
    if crowd >= 2 or lost > DRILL_HURT * (p.max_hp or 1):
        # 드릴은 준비·기다림이 길다 — 여럿 붙었거나 많이 맞으면 이 싸움은 드릴 끝, 표대로 (140006 roll_r1 드릴: 3놈 사이에서
        # wait×만 하다 −1474, 사망)
        for x in s.hostile(DRILL_CROWD_R + 3.0):
            n[x.ptr] = DRILL_SETUPS + 1
        n[c.ptr] = DRILL_SETUPS + 1
        F.log(f"      드릴 {DRILL} 그만 — " + (f"{crowd}놈 붙음" if crowd >= 2 else f"이 싸움에서 {lost} 맞음") + " → 표대로 싸움")
        if DRILL == "backstep_r1" and _two_handed(F) and DRILL_BS_TWO_HAND:
            F._grip_t = time.time()
            F.mv.pad.two_hand_right()                      # 표대로 싸움은 한손·방패로 (P-123)
            F.log("      드릴 그립: 한손·방패로 되돌림")
        F.events("drill_setup", attack=DRILL, npc=c.npc_param, what="abort", crowd=crowd, lost=lost, h=round(h, 2))
        return None if phase == "hit" else M.Hit("entry", skipped="드릴 그만")
    if k["state"] == "swing":
        return M.Hit("wait", skipped="드릴: 휘두르는 중 — 기다림")
    what = why = None
    wait_near, hold, far = DRILL_WAIT.get(DRILL, (None, None, None))
    if wait_near is not None and (DRILL != "backstep_r1" or back_ok is not False) and h > wait_near:
        # ── 백스텝 드릴은 다가가지 않고 기다림 (P-121 182931: 1.15 m까지 다가가서 누른 5번 모두 서서 휘두른 놈 1.3–2.2 m, 다가오는
        #  놈엔 0번) — MoKa 시범처럼 거리를 두고 준비, 놈이 SWING_BS_R에 들어오면 rule_swing_backstep이 장전해서 B.
        #  DRILL_BS_FAR보다 멀면 그 안까지만 다가감, 기다려도 안 오면 (DRILL_BS_IDLE s) 한 걸음씩 ──────────────────────
        idle = F.__dict__.setdefault("_drill_idle_t", {})
        t0 = idle.setdefault(("bs", c.ptr), time.time())
        if h > far or (h > hold and time.time() - t0 > DRILL_BS_IDLE and front_ok is not False):
            idle[("bs", c.ptr)] = time.time()
            F.mv.step(s, c.x, c.z, min(0.6, (h - hold) / 2.5 + 0.1))
            what, why = "다가감", f"{h:.1f} m — {hold} m까지 (안 옴)" if h <= far else f"{h:.1f} m > {far} m"
        else:
            if DRILL == "backstep_r1":
                _drill_grip(F, s, c)
            # 기다리는 동안 방패를 내림 — 들고 있으면 기력이 늦게 차 백스텝+R1 기력(50)이 모자람 (#7 기력 < 50 ×7, 184413 기력 22)
            #  ([MoKa] 11-03 "방패 가드의 단점이 막으면 스테미나를 많이 사용해서 다음 공격이 어려워 지는데"), 락온은 지금 미리
            #  (184413 락온 none ×6 — 모두 2 m 안에서 휘두를 때 처음 봄)
            F.mv.guard(False)
            lock = getattr(F.mv, "lock_state", lambda _p: "target")(c.ptr)
            if lock != "target" and time.time() - F.__dict__.get("_drill_lock_t", 0.0) > 1.0:
                F._drill_lock_t = time.time()
                ok = getattr(F.mv, "lock_target", lambda *_a, **_k: False)(c.ptr, tries=1)
                F.events("drill_setup", attack=DRILL, npc=c.npc_param, what="lock", before=lock, ok=ok, h=round(h, 2))
            return M.Hit("wait", skipped=f"드릴: {h:.1f} m에서 기다림 (방패 내림) — 오면 {wait_near} m에서")
    elif DRILL == "backstep_r1" and back_ok is False:
        from . import group_plan as GP
        plan = GP.make(p, [c], F.nm, foe_of=foes_.of, rings=GP.SPOT_R + (5.0, 6.0))
        if plan.spot and plan.moved > 0.3 and "뒤 바닥 없음" not in plan.spot_why:
            F.mv.step(s, plan.spot[0], plan.spot[2], min(2.0, plan.moved / 2.5 + 0.2))
            what, why = "자리", f"뒤 바닥 없음 → ({plan.spot[0]:.1f}, {plan.spot[2]:.1f}) {plan.moved:.1f} m"
        else:
            # 6 m 안에 그런 자리가 없음 — 틱마다 다시 세지 말고 바로 포기 (133704 200.5 s: "자리없음" 8번을 0.8 s에 다 씀)
            n[c.ptr] = DRILL_SETUPS
            F.log(f"      드릴 {DRILL} 준비: 6 m 안에 뒤 바닥 2.6 m 있는 자리 없음 ({h:.1f} m)")
            F.events("drill_setup", attack=DRILL, npc=c.npc_param, what="자리없음", h=round(h, 2))
            return M.Hit("wait", skipped="드릴: 자리 없음")
    elif h > hi:
        if front_ok is False:
            what, why = "앞막힘", f"{h:.1f} m, 그쪽 바닥 없음"
        else:
            F.mv.step(s, c.x, c.z, min(0.6, (h - (lo + hi) / 2) / 2.5 + 0.1))
            what, why = "다가감", f"{h:.1f} m > {hi} m"
    elif h < lo:
        # 이미 붙음 — 여기서 벌려 만들지 않음. 백스텝(~1.5 m)은 쫓아오는 놈에게 안 벌어지고 (135152: 벌림 31번, 구르기 3번),
        # 뒤로 구르기는 경사로 밖으로 떨어짐 (140350 −587 낙사), 벽·턱에 몰려 죽음 (140920 −403 낙사)
        # ([MoKa] 11-03 "거리가 없으면 어떻게 구르기를 해?" · "미리 거리가 있을때 해야 하는 거지") → 이 놈은 표대로, 다음 놈을 거리에서
        n[c.ptr] = DRILL_SETUPS + 1
        F.log(f"      드릴 {DRILL}: 이미 {h:.1f} m 붙음 (< {lo} m) — 진입 거리 놓침 → 이 놈은 표대로")
        F.events("drill_setup", attack=DRILL, npc=c.npc_param, what="glued", h=round(h, 2), phase=phase)
        return None if phase == "hit" else M.Hit("entry", skipped="드릴: 이미 붙음")
    if what is None:
        return None
    if what == "앞막힘":
        # 움직이지 않은 준비 — 그놈이 움직이길 기다리는 것. 틱마다 세지 않고 1 s에 한 번만 (134253: "앞막힘" 16번에 2놈 포기)
        last = F.__dict__.setdefault("_drill_idle_t", {})
        if time.time() - last.get(c.ptr, 0.0) < 1.0:
            F.mv.guard(True)
            return M.Hit("wait", skipped=f"드릴 준비: {what}")
        last[c.ptr] = time.time()
        F.mv.guard(True)
    n[c.ptr] = n.get(c.ptr, 0) + 1
    F.log(f"      드릴 {DRILL} 준비 {n[c.ptr]}: {what} — {why}")
    F.events("drill_setup", attack=DRILL, npc=c.npc_param, what=what, why=why, h=round(h, 2), state=k["state"],
             back=back_ok, front=front_ok, n=n[c.ptr])
    return M.Hit("wait", skipped=f"드릴 준비: {what}")


def _strike(F, s, c, n: int, sp_second=None, swinging: bool = False) -> "M.Hit":
    """Our attack: the light (n swings), or the vertical heavy when _slam says so — a horizontal swing catches on the wall."""
    if COMBO_ONLY:
        return _combo_strike(F, s, c)
    wall = _slam(F, s, c, swinging)
    if wall is not None:
        # 좁은 통로·벽에 붙은 적: 가로 휘두르기는 벽에 걸린다 — 배틀 액스 강공은 수직이라 안 걸림 ([MoKa] 2026-09-28)
        F.log(f"      벽 {wall:.1f} m — 강공(수직)")
        return _shield_combo(F, s, c) if _shield_foe(F) else F.mv.heavy(s, c)
    return F.mv.light(s, c, n=n, sp_second=sp_second)


def rule_attack(F, T):
    """Default: kick an idle shield soldier looking at us (kick → light right away), else heavy or light per weapon."""
    s, c, a, w = T.s, T.c, T.a, F.weapon
    if COMBO_ONLY:
        hit = _combo_strike(F, s, c)
        if hit.kind == "wait":                             # 계획한 백스텝 거리 기다리는 중 — 매 틱 적지 않음
            F.note("계획대기", s, c)
            return F.killed_if(False)
    elif getattr(T, "wall", None) is not None and _slam(F, s, c) is not None:
        hit = _strike(F, s, c, n=w.combo, sp_second=w.sp_min)          # before the shield soldier kick too (two hands break the guard)
    elif F.foe.kick_when_idle and a == -1 and T.behind_deg < 60 and T.now - F.kick_t > KICK_COOLDOWN:
        F.kick_t = T.now
        hit = F.mv.kick_combo(s, c, n=w.combo)
    elif w.use_heavy and _locked(F):
        hit = F.mv.heavy(s, c)
    else:
        hit = _strike(F, s, c, n=w.combo, sp_second=w.sp_min)
    F.record(hit)
    F.note(hit.kind, s, c)
    F.log(f"      {hit.kind}×{hit.presses} → 피해 {hit.dmg}, 내 피해 {hit.taken}, 그놈 애니 {hit.e_anims[:4]}")
    return F.killed_if(hit.dead)


def _no_drill(rule):
    """Drills never swap to another attack ([MoKa] 11-03 "점프 드릴이라고 하면서 뒤잡만 하고 있네") — backstab rules off while DRILL,
    and with --combo-only for a foe whose plan is another technique ([MoKa] 11-04: 뒤잡은 근처에 하나 · 지형 안 막힐 때만)."""
    def wrapped(F, T):
        if DRILL is not None or _tech(T.c) not in (None, "backstab"):
            if rule is prep_backstab_chance:
                r = rule(F, T)
                T.backstab_chance = False
                return r
            return None
        return rule(F, T)
    wrapped.__name__ = rule.__name__
    wrapped.__doc__ = rule.__doc__
    return wrapped


# drill → (wait beyond this, step in only to this when it doesn't come, walk in beyond this) — _drill_setup
DRILL_WAIT = {"backstep_r1": (SWING_BS_R, DRILL_BS_HOLD, DRILL_BS_FAR), "jump_r2": (JUMP_HI, JUMP_HOLD, JUMP_WAIT_FAR)}

RULES = [rule_shot, rule_separate, rule_wall_bounce, rule_finish_first, prep_reflex, rule_guard_counter, rule_footing, rule_swing_backstep, rule_jump_drill, rule_jump_dodge,
         rule_jump_save, rule_after_swing, rule_face_first, rule_early_kick, rule_late_windup_block, prep_linger, rule_hit_first,
         _no_drill(rule_backstab_swing), rule_reflex, rule_lure, rule_edge, rule_estus, rule_stagger_punish, rule_evade, rule_block,
         rule_downed, _no_drill(prep_backstab_chance), rule_wait_far, rule_approach, rule_finish, rule_stamina, prep_face,
         _no_drill(rule_backstab), rule_attack]


_RULE_NAMES = [r.__name__.removeprefix("rule_").removeprefix("prep_") for r in RULES]   # counter trace: rule order


# ── P1-C: which rule acted (only with run.py --ctl) ──────────────────────────
# Rules that only hold a stance tick after tick are run-length folded (same rule and target → one record with n). Every
# other rule — attacks, backstab, estus, kicks, and any rule not listed here — is always written on its own.
SCENE_TAP = None   # run.py --ctl-scenes: scenes.Tap — copies each decision's input for scene_replay.py (record only, never read back)
FOLD_RULES = {"block", "wait_far", "approach", "face", "linger", "reflex", "stamina", "separate", "edge", "footing", "lure", "downed",
              "face_first", "backstab_chance", "late_windup_block"}


class _RuleRec:
    """Records only: the duel loop never reads anything from here, and nothing here raises.
    snap_age_ms = now − snap.t taken when add() runs, i.e. **after the rule returned** — it includes the rule's own action
    time (a light attack: ~1 s), so it is not the snapshot's age when the rule decided. The record's pc is that moment too;
    a folded run's record goes out when the next different rule returns. For when a rule was entered and first acted, see
    span.rule (ctlspan.py, run.py --ctl-spans)."""

    def __init__(self):
        self.run: dict | None = None     # pending folded run

    def add(self, F, T, name: str, out) -> None:
        try:
            c = getattr(T, "c", None)
            s = getattr(T, "s", None)
            ptr = getattr(c, "ptr", None) if c is not None else F.ptr
            st = getattr(s, "t", None)
            rec = {"rule": name, "ptr": ptr, "out": "result" if isinstance(out, DuelResult) else str(out),
                   "snap_t": st, "fseq": getattr(s, "fseq", None),
                   "snap_age_ms": None if st is None else round((time.time() - st) * 1000, 1)}
            if name in FOLD_RULES and self.run is not None and (self.run["rule"], self.run["ptr"]) == (name, ptr):
                self.run["n"] += 1
                return
            self.flush()
            if name in FOLD_RULES:
                self.run = {**rec, "n": 1}
            else:
                ctl.emit("dec.rule", **rec, n=1)
        except Exception:
            pass

    def flush(self) -> None:
        if self.run is not None:
            ctl.emit("dec.rule", **self.run)
            self.run = None



def duel(mv: M.Moves, weapon, ptr, nm, log=print, limit: float = 45.0, low_hp: float = 0.25,
         cancel=lambda: False, care=None, reflex=None, arena=None, style=None, wait_far: bool = False,
         gen=None, events=None, may_approach=None, crowd_ok: bool = False, wall_ok: bool = False,
         advisor=None, tap=None, trail=None) -> DuelResult:
    """care: healing handler from layer 4 — care.wants(s) (wants to drink?), care.take(recheck) (drinks; recheck(s) rechecks the opening).
    Whether there's an opening is judged here (layer 3): opening(). If close, backstep to open distance and recheck next tick.
    reflex: reflex (souls/reflex.py) — first thing every tick. If it moved, this tick rests (it also blocks attacks from non-targets head-on).
    arena: a flat spot nearby — if footing is toward a cliff (nav.footing), back off there to receive it when it isn't swinging.
      User principle: "not being in a dangerous position in the first place comes first" — quit-out can't save a fall (the menu won't open while falling, 2026-09-24).
    wait_far: if out of reach, don't approach; block in place and wait — turn this on for foes that are walking in.
      User 2026-09-25: "it would come if you waited, why did you rush up and miss the chance" — walking toward a still-distant foe made others
      come along too, so what would have come alone had to be fought as a group at once (ramp, 0 damage/8 s, 493 taken, force-quit for being surrounded).
      Distinguish "when to wait and when to act" — let distant foes come, react only after they enter reach.
    advisor: laya_shadow.Advisor (run.py --laya-shadow) — told which rule acted, after it acted. Record only: nothing it
      returns is read here, and it swallows its own errors (LAYA.md).
    tap: attack_audit.DecisionTap (run.py --attack-audit, off by default) — copies what features() reads before each rule
      call, records the attack rule invocations after they return. Observation only: nothing it returns steers the fight
      (its payload goes only to the advisor), and it swallows its own errors."""
    from . import style as style_
    F = Fight(mv, weapon, ptr, nm, log, limit, low_hp, cancel, care, reflex, arena, style_.of(style or "guard"), wait_far, gen, events,
              may_approach, crowd_ok, wall_ok, trail)
    rr = _RuleRec() if ctl.on() else None              # P1-C: record only
    if rr is not None:
        CT.fight_start(F)                                  # counter trace (record only)
    sp = CS.Fight(ptr) if CS.on() else None             # run.py --ctl-spans: span records (ctlspan.py, record only)
    if sp is None:
        return _duel_loop(F, rr, advisor, tap, None)
    res = None
    try:
        res = _duel_loop(F, rr, advisor, tap, sp)
        return res
    finally:
        sp.end(res)


def _duel_loop(F, rr, advisor, tap, sp) -> DuelResult:
    """duel()'s while loop. sp: ctlspan.Fight or None — its calls only write records."""
    while True:
        if sp is not None:
            sp.cycle_start()
        T = _sense(F)
        if isinstance(T, DuelResult):
            if sp is not None:
                sp.cycle_end("sense_result")
            if rr is not None:
                rr.flush()
                CT.fight_end(F, T)
            if advisor is not None:
                advisor.end(F, T)
            if tap is not None:
                tap.end(F, T)
            return T
        if T is CONT:
            if sp is not None:
                sp.cycle_end("sense_cont")
            continue
        if sp is not None:
            sp.sensed(T, SEEK_R)
        if tap is not None:
            tap.sensed(F, T)
        if SCENE_TAP is not None:
            SCENE_TAP.tick(F, T)                           # copies the input before the rules change F (scenes.py, record only)
        _keep_lock(F, T)
        if getattr(T, "c", None) is not None and getattr(T, "h", None) is not None:
            _closing(F, T.c, T.h)                          # every tick, every distance — the rules read it later (P-121)
        if rr is not None:
            CT.tick(F, T)
        picked = None
        for i_rule, rule in enumerate(RULES):
            tok = tap.freeze(F, T) if tap is not None else None
            if sp is not None:
                sp.rule_enter()
            out = rule(F, T)
            if out is None:
                if sp is not None:
                    sp.rule_none(rule.__name__.removeprefix("rule_").removeprefix("prep_"))
                continue
            name = picked = rule.__name__.removeprefix("rule_").removeprefix("prep_")
            if sp is not None:
                sp.rule_return(name, out)
            F.res.rules[name] = F.res.rules.get(name, 0) + 1
            if rr is not None:
                rr.add(F, T, name, out)
            if SCENE_TAP is not None:
                SCENE_TAP.decided(F, T, name, out, i_rule)
            pay = tap.decided(F, T, tok, name, out) if tap is not None else None
            if advisor is not None:
                if pay is None:
                    advisor.observe(F, T, name, out)
                else:
                    advisor.observe(F, T, name, out, payload=pay)
            if isinstance(out, DuelResult):
                if rr is not None:
                    rr.flush()
                    CT.after_rules(F, T, picked, _RULE_NAMES)
                    CT.fight_end(F, out)
                if tap is not None:
                    tap.end(F, out)
                if sp is not None:
                    sp.cycle_end("rule_result", picked, T)
                return out
            break
        if rr is not None:
            CT.after_rules(F, T, picked, _RULE_NAMES)      # a window open but an earlier rule acted → after_swing not evaluated
        if sp is not None:
            sp.cycle_end("rule_cont" if picked is not None else "no_rule", picked, T)
