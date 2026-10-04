"""Layer 4 — field playbook. Multiple foes, terrain, paths. Goal is **reach the destination alive**; foes already killed are not thrown away.
Hands one foe at a time to layer 3 (duel) and decides the next step from the result:
  · killed → estus if HP below 70 % (only when safe)
  · my HP low / stalemate / lost / blocked → quit-out to shake foes off (dead foes stay dead), estus → same foe again (up to three times)
  · no estus → stop (the layer above decides whether to rest)
  · a chaser catches up while walking the path → that one first (don't walk with back turned — user: "there's an enemy, why aren't you reacting")
Resting (bonfire) **revives every foe**, so this layer avoids it. Bloodstain pickup (A) is also skipped within 6 m of a bonfire (it would sit down).
"""
from __future__ import annotations

import json
import math
import time
import types
from pathlib import Path

import control
import nav

from . import duel as D
from . import foes as foes_
from . import moves as M
from . import props as props_
from .reflex import Reflex
from . import style as style_
from .watch import Blood

FOLLOW_R = 4.5           # while walking the path, fight any awake foe that closes within this (horizontal)
FOLLOW_DY = 2.5          # foe following on stairs — up to this height difference
SAFE_R = 6.0             # estus: no awake foe within this, and
SAFE_ATTACK_R = 8.0      #          nobody swinging within this
RESYNC_BACK, RESYNC_AHEAD = 3, 15   # range for re-picking the waypoint after a fight while walking (field.walk)
# ── 아는 안개벽 (P-41) ─────────────────────────────────────────────
#  · 성벽 마을 마을 구역(#1~#3) 끝 → `#4 이동`: "Traverse the white light". 10-03a 봇이 21 s 비비다 timeout 1번 → fog_through는
#    2번 놓쳐야 켜져서 안 켜짐, [MoKa]가 A. 첫 방문 캐릭터에만 걸림 (그전 실행들은 이미 지난 캐릭터)
#  · 길이 이 벽을 가로지르면 걷기 전에 벽 앞에 서서 A — 안내창 판정 없이 (흰 빛 뒤라 어두운 상자 판정이 안 됨, 10-03b 4번 실패).
#    벽이 없어졌으면 A가 아무 일도 안 하고 2 m 안 움직임 → 그냥 걸음
FOG_WALLS = [(-50.0, -22.3, -32.0)]
FOG_PASS_R = 1.5         # the line to the next point passes this close (horizontal) to a wall's center → it crosses the wall
FOG_DY = 2.5
FOG_FRONT_M = 0.6        # stand this far before the wall, on the line to the point, then fog_through (1.2 too far — 10-03b)


def fog_ahead(p, q):
    """The FOG_WALLS entry the straight line p → q crosses (center strictly between them, within FOG_PASS_R), else None."""
    dx, dz = q[0] - p[0], q[2] - p[2]
    l2 = dx * dx + dz * dz
    if l2 < 1e-6:
        return None
    for c in FOG_WALLS:
        if abs(c[1] - p[1]) > FOG_DY:
            continue
        t = ((c[0] - p[0]) * dx + (c[2] - p[2]) * dz) / l2
        if 0.0 < t < 1.0 and math.hypot(c[0] - (p[0] + t * dx), c[2] - (p[2] + t * dz)) <= FOG_PASS_R:
            return c
    return None


RESYNC_DY = 1.0                     # nearest waypoint this far above/below → different level: re-plan from here (hotspot #4, 2026-09-28)
ALMOST_M, ALMOST_DY = 1.7, 0.8       # a point missed ('stuck'/'timeout') from this close = almost there: go on to the next point
                                     # (MoKa 2026-09-30, ROADMAP 6-a: 40 % of the logged misses were ≤ 1.7 m / |dy| ≤ 0.8 — the
                                     # arrival radius, not a blockage — and the detour after them failed again 43 % of the time).
                                     # Not for the last point: that is where the walk has to end up (throw spot, arena).
                                     # Doesn't reset the fail count (fog walls, see _walk_missed).


def resync(path: list, here, nm, lo: int = 0, hi: int | None = None) -> tuple[list, int, float]:
    """Where to carry on walking from `here` after a fight / quit-out. → (path, i, dy).
    Nearest waypoint in path[lo:hi]; if it's on a different level (|dy| > RESYNC_DY — fought the crossbowman on the ledge, the nearest
    point is 1.5 m below: unreachable, 6~8 s stuck in 5 of 6 runs) re-plan from here to the end on the navmesh (i = 0, dy returned ≠ 0).
    If there's no navmesh / no path, keep the old path and the nearest point."""
    hi = len(path) if hi is None else hi
    i = min(range(lo, hi), key=lambda j: math.dist(path[j], here))
    dy = here[1] - path[i][1]
    if abs(dy) <= RESYNC_DY or nm is None:
        return path, i, 0.0
    try:
        newp = nm.find_path(tuple(here), tuple(path[-1]))
    except Exception:
        newp = None
    if not newp:
        return path, i, 0.0
    newp = [tuple(q) for q in nav.trim_path(list(newp[1:]) or list(newp), path[-1])]
    return newp, 0, dy


class WalkPlan:
    """Where the walk is on its path: points, current index, arrival tolerance per point. No game — Field._walk drives it.
    Without tol (navmesh path) only steep segments (stairs, ramps) are stepped precisely at 0.4 m (nav.path_tolerances) — stepping everything at 1 m
    couldn't get from the ramp ledge up to the stair top: 'passage blocked' (2026-09-24). Human-recorded paths get tol (0.8) from the caller
    — narrowing recorded points to 0.4 m got stuck unable to get within 0.6~0.7 m at stair ends (hunt.walk_fight). Corners tighten either way."""

    def __init__(self, path: list, tag: str, tol: float | None = None):
        self.tag, self.tol, self.i = tag, tol, 0
        self.set_path([tuple(q) for q in path])

    def set_path(self, path: list) -> None:
        self.path = path
        self.tols = nav.path_tolerances(path, 1.0) if self.tol is None else nav.path_tolerances(path, self.tol, steep=False)

    @property
    def done(self) -> bool:
        return self.i >= len(self.path)

    def point(self):
        return self.path[self.i]

    def tolerance(self, tight: dict | None = None) -> float:
        """Inside tight = {"center", "r"} (narrow bridge without railings) step precisely at 0.45 m."""
        q = self.path[self.i]
        if tight and math.dist((q[0], q[2]), (tight["center"][0], tight["center"][2])) < tight["r"]:
            return 0.45
        return self.tols[self.i]

    def nearest(self, here) -> None:
        self.i = min(range(len(self.path)), key=lambda j: math.dist(self.path[j], here))

    def resync(self, here, nm, window: bool) -> float:
        """Carry on from `here`: nearest point (within RESYNC_BACK·RESYNC_AHEAD of i if window), re-planned on another level.
        → dy of the re-plan, 0.0 if the old path was kept."""
        lo, hi = (max(0, self.i - RESYNC_BACK), min(len(self.path), self.i + RESYNC_AHEAD)) if window else (0, len(self.path))
        newp, j, dy = resync(self.path, here, nm, lo, hi)
        if newp is not self.path:
            self.set_path(newp)
        self.i = j
        return dy
RETREAT_GUARD_R = 4.0    # retreat: shield up while an awake foe is within this (horizontal)
SMASH_TRIES = 2          # swings (x2 attacks) per blocking prop per walk — a prop that won't break isn't hit forever
SMASH_WALK_S = 2.0       # s to step up to it
SMASH_R = 1.3            # m — light attack reach from the prop's origin
SMASH_FACE_S = 1.2       # s to turn toward it
SMASH_SWING_S = 0.7      # s per light attack
REPAIR_FRAC = 0.4        # repair powder when weapon durability is below this fraction of max (field.repair)
RANGED_R = 25.0          #          and no awake, moving 'thrower' (foes.ranged) within this
BONFIRE_NO_A = 6.0
# 에스트는 아끼지 말고 자주 ([MoKa] 2026-09-28: "열심히 에스트 마시면서 플레이하는 것이 최선" — 규칙을 더할수록 문제가 생김).
# Bandit Bot e 실행: 최저 HP 10 %까지 떨어지고도 에스트 5개가 남음 → 0.5 / 0.6 에서 올림
FIGHT_HEAL = 0.6         # while fighting: drink at an opening (duel.opening) if HP is below this
WALK_HEAL = 0.7          # while walking: if below this and safe, drink (heal(0.7): up to 70 % or 3 sips) — the trigger equals the target, so each drink only lifts HP back to the line


# 둘러싸임 후퇴(duel 'crowd' → fall_back)는 지금 꺼 둠 — 1~2 s 물러나고 다시 둘러싸이기를 반복해 두 번 사망 (P-26). [MoKa] 2026-09-28:
# 일단 끄고 테스트, 달려서 떼어놓는 방식으로 따로 고칠 것. 꺼져 있어도 둘러싸임 퀵 종료는 없음 — HP 45 % 후퇴(recover)만
CROWD_FALL_BACK = False
FALL_BACK_R = 6.0        # fall_back stops once at most one moving foe is within this
FALL_BACK_MAX_S = 15.0   # …or after this long
FALL_BACK_OFF_S = 10.0   # no path back → fight in place this long before trying to fall back again
CROWD_MAX = 3            # 'crowd' fall-backs within CROWD_WINDOW_S before we stop falling back — the callers don't count a 'crowd' as a try, so without
CROWD_WINDOW_S = 90.0    # this cap 'crowd → fall_back → crowd' repeats forever (P-26: 16 times, 0 damage dealt, dead)
IGNORE_CLOSE_R = 2.5     # a foe the walk gave up on ('stuck'/'lost') still counts as a chaser when it is this close and swinging or
                         # staggered — 10-01c: an ignored 254010 hit us 4 times from 0.8 m over 10 s (staggered 3 times) with no counter,
                         # we walked on being hit and fell 5 m into the gap by town#3 ([MoKa]: "판단이 느려서 적에게 밀려서 틈에 빠졌음")
CHASER_ROLL_R = 1.8      # a foe this close when we start backing off → roll away from it first (floor 2.5 m that way), else stay and fight
CHASER_STOP_R = 1.3      # while backing off, a foe swinging this close → stop walking, turn back to the fight
RETREAT_CLEAR_R = 10.0   # a retreat goes on until no awake foe is within this (same level) — stopping at safe() (6 m) left the chaser 6–7 m
                         # behind and the Estus check then said 'foes nearby' (20 times in 09-30a…10-01b)
RETREAT_HP = 0.5         # leave a fight below this share of max HP (was 0.25 — MoKa 2026-10-01: retreat more; low_hp fights took 335 each)
WALL_BACK = True         # three or more on us away from a wall → back to a wall and take them one at a time (P-29, duel.WALL_BACK_N)
WALL_BACK_R = 10.0       # look for a wall spot this far (horizontal) from us
WALL_SPOT_DROP = 2.5     # …with no drop edge (Navmesh.drop_dist) closer than this — backing into a fight next to a drop is P-14/P-16
WALL_OFF_S = 20.0        # after backing to a wall (or finding none), fight where we stand this long before trying again
CROWD_OFF_S = 60.0       # …then fight in place this long (the old 45 % HP retreat still applies) before trying again


def awake(c) -> bool:
    return c.hp > 0 and not (9000 <= (c.anim or 0) < 9100)


SEEK_R = 100.0           # radius to look for that foe (same as duel.SEEK_R)
COMING_LIMIT = 12.0      # an interloper not killed within this gets disengaged — no dragging into a bad trade (17~22 s, 400+ damage)
                         # (user 2026-09-25: "if you can't kill the interfering mob in one go, better to run")
LURE_R = 10.0            # knife throw distance — with lock-on, 11.9 and 11.4 m missed, 10.8 m hit (2026-09-24, thrown items fly ~10 m)
LURE_TRIES = 3
LURE_DY = 1.5            # max height diff between throw spot and target / current spot — so we don't jump down to a foe below a cliff (2026-09-24 run 8)
LURE_ABORT_R = 10.0              # abort throwing if another awake, moving foe is within this
PICK_TRIES = 3           # A presses to pick up a bloodstain
CAREFUL_LEG = 4.0        # careful_walk_to: walk this far, then stop and look
CAREFUL_LOOK_S = 1.5     # …stand this long (guard up) watching who comes
CAREFUL_COME_R = 12.0    # an awake, moving foe this close (same level) → wait for it here and fight it alone
CAREFUL_MAX_S = 240.0
LURE_MIN, LURE_MAX = 6.0, 13.0   # throw conditions on flat ground — closer than this and just walking wakes it; farther and lock-on fails
KNIFE_LOW = 5            # warn below this — going to buy from the merchant is a later task (user 2026-09-24)
HOLD_TRIES = 3           # hold-the-spot targets (lure_at.hold): lure attempts; wait HOLD_WAIT in place between them
HOLD_WAIT = 8.0
MISSING_S = 5.0          # if a bound target stays missing from snapshots this long → 'unknown' (not treated as death)
MOVED_R, MOVED_DY = 3.0, 3.0   # alive and this far off its spawn → 'moved'
BIND_EVERY = 1.0         # interval for re-finding unbound targets at their spawn
HOLD_SPOT_TOL = 0.5      # tolerance for standing at the throw spot / arena wait spot (previously 1.5 m)
HOLD_ZONE_R = 2.5        # safe zone around the throw spot (spot is 1.1 m from RAMP_ARENA; nearest drop on that flat ground is 4.0 m)
HOLD_CALM_R = 5.0        # no foe within this → 'calm' — lower the shield
HOLD_GUARD_R = 3.0       # within this → 'contact'
HOLD_GUARD_SP = 0.25     # fraction of max stamina — below this, defend in place instead of shielding
DEFEND_SLICE = 1.0
APPROACH_DV = 0.3        # closing this much in 0.5 s → 'approaching'
LURE_UNBLOCK_S = 0.5     # lure block releases only after within 5 m stays quiet this long **continuously** (so a foe grazing the edge doesn't flip it)
MOVED_WAIT_DY = 1.2      # more than this height diff from the arena (flat ground) → 'different height' — don't go find it, wait on the flat ground (Patch E-1)
MOVED_WAIT_S = 20.0
HOLD_KEEP_R = 12.0       # E-1b: don't go find a moved target within this of the spawn of a remaining hold-the-spot target (shield soldier) (user kills #1·#3 at 12.3~17.7 m)      # wait time per round. If it doesn't come down after two waits → 'left #i~' (not approached)
RETURN_LEG_M = 2.0       # length of the first leg of the path back to the spot — don't walk it if it heads toward an awake foe
# 'least-bad spots' the user marked with F9 (data/safe-zones.json, observe 161923) — not a safety guarantee, just a retreat destination.
# user: "it's not a fully safe zone", "you'll still need to guard even where I said" → walk there with guard up, and keep blocking there too
ZONES = [tuple(z["pos"]) for z in json.loads((Path(__file__).resolve().parent.parent / "data" / "safe-zones.json")
                                              .read_text(encoding="utf-8"))["zones"]]
ZONE_REACH = 15.0        # before fighting a chaser, if a marked spot is within this (horizontal, same floor 1.5 m), retreat there and receive it
UNSAFE_PAUSE = 5.0       # incoming foe not engaged due to E-2 — wait/defend ticks on flat ground this long, then re-check (user: "even 2 seconds is short, wait 5 seconds")
CLOSE_MELEE_R = 3.0      # end a contact fight if another foe is within this (wider than duel.SWITCH_R 2.5 — cut before switching targets)


class LureBlock:
    """Lure block + release hysteresis — after set(), releases only once no foe within HOLD_CALM_R has held **continuously** for more than LURE_UNBLOCK_S."""

    def __init__(self):
        self.on, self.calm_since = False, None

    def set(self) -> None:
        self.on, self.calm_since = True, None

    def update(self, near: bool, now: float) -> bool:
        """→ still blocked?"""
        if not self.on:
            return False
        if near:
            self.calm_since = None
        elif self.calm_since is None:
            self.calm_since = now
        elif now - self.calm_since >= LURE_UNBLOCK_S:
            self.on, self.calm_since = False, None
        return self.on


class Field:
    def __init__(self, mv: M.Moves, weapon, escape, bonfires: list, log=print, events=None, style="guard"):
        self.mv, self.w, self.esc, self.log = mv, weapon, escape, log
        self._detour = False                               # keeps walk's "detour" from recursing
        self._crowd_hits: list[float] = []                 # times of recent 'crowd' fall-backs (CROWD_MAX per CROWD_WINDOW_S)
        self._wall_off_until = 0.0
        self._crowd_off_until = 0.0                        # fall_back 이 길이 없어 못 물러났으면 잠깐 둘러싸여도 싸운다 (같은 자리에서 무한 반복 방지)
        self.style = style_.of(style)                      # souls/style.py — every layer only reads this object
        self.bonfires = [tuple(b) for b in bonfires]      # bloodstain pickup (A) forbidden zones
        self.home = self.bonfires[0] if self.bonfires else None   # last bonfire rested at (retreat target, Darksign arrival check)
        self.events = events or (lambda *a, **k: None)
        # reflex — first on every tick, fighting or walking (navmesh for the footing check is set when used). Unblockable attacks come from foe data (layer 3)
        self.reflex = Reflex(mv, unblockable=lambda c: (c.anim or -1) in foes_.of(c.npc_param).unblockable,
                             bs_ok=lambda c: foes_.of(c.npc_param).kind != "shield")
        self.reflex.evade = self.style.evade
        self.reflex.bs_attack = self.style.bs_attack
        self.reflex.reflex_on = self.style.reflex_on
        mv.guard_ok = self.style.shield
        self.reflex.events = self.events

    # ── State─────────────────────────────────────────────────
    def snap_settled(self, within: float = 5.0):
        """During quit-out (loading), wait until it ends, then snapshot — anywhere that reads position uses this. Reading None during loading
        collided with a fall-death quit-out right after the Burg cleanup and stopped the run with AttributeError (2026-09-25 195213)."""
        t0 = time.time()
        while time.time() - t0 < 45.0:
            if not self.esc.escaping:
                s = self.mv.snap(within)
                if s is not None:
                    return s
            time.sleep(0.2)
        return None

    def estus_left(self) -> int:
        """Estus count — reads as 0 during quit-out (loading). Trusting that ended a run that never drank as "no_estus"
        (2026-09-25 202220: right after a ramp-surrounded quit-out). Waits until it ends, then reads"""
        self.snap_settled(5.0)
        return self.mv.estus_left()

    def alive(self) -> bool:
        # during quit-out (loading) the character isn't visible — reading that as death ended a run at HP 343 as "died" (2026-09-25 190651:
        # the menu-less quit-out enters loading in just 0.6 s, exposing this gap). Wait until it ends, then look
        t0 = time.time()
        while self.esc.escaping and time.time() - t0 < 40.0:
            time.sleep(0.2)
        s = self.mv.snap(5.0)
        if s is None:                                       # loading just ended or not yet — a bit longer
            time.sleep(1.5)
            s = self.mv.snap(5.0)
        return bool(s and s.player.hp and s.player.hp > 0)

    def wait_respawn(self, timeout: float = 45.0) -> bool:
        """If dead, wait until standing up at the bonfire (no snapshot during loading)."""
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                s = self.mv.snap(5.0)
            except Exception:
                s = None
            if s and s.player.hp and s.player.hp > 0 and s.player.hp >= s.player.max_hp * 0.99:
                self.forget_foes()
                time.sleep(1.0)
                return True
            time.sleep(0.5)
        return False

    def forget_foes(self) -> None:
        """After a rest or a respawn every foe is back — drop what we remembered about them by pointer (careful_walk_to's failed
        pulls): a revived foe can get the same pointer and would then never be pulled again."""
        self.__dict__.pop("_careful_lured", None)

    def safe(self, s) -> bool:
        """OK to drink estus? — no foe nearby, nobody swinging, and **no thrower (firebomb) awake within RANGED_R**.
        Checking only 8 m, a firebomb hollow on the ledge above hit us mid-drink, interrupting it, and we died (2026-09-24)."""
        for c in s.hostile(RANGED_R):
            if not awake(c):
                continue
            if c.dist < SAFE_R or ((c.anim or -1) in M.ATTACK and c.dist < SAFE_ATTACK_R):
                return False
            if foes_.of(c.npc_param).ranged and (c.anim not in (None, -1)):
                return False
        return True

    # ── Healing─────────────────────────────────────────────────
    def heal(self, frac: float = 0.7, sips: int = 3) -> None:
        self.repair()
        for _ in range(sips):
            s = self.mv.snap(15.0)
            if not s or s.player.hp >= s.player.max_hp * frac:
                return
            if self.estus_left() <= 0:
                self.log("      에스트 없음")
                return
            if not self.safe(s):
                self.log("      에스트: 근처에 적 — 안 마심")
                return
            r = self.mv.drink(self.safe)
            self.log(f"      에스트: {r}")
            self.events("estus", **r)
            if not r["ok"]:
                return

    def repair(self, frac: float = REPAIR_FRAC) -> None:
        """Repair powder if weapon durability is below frac of max — only when safe between fights (same place as heal).
        The Claymore broke within one set (user 2026-09-25: "some weapons are unusually weak")."""
        mx = self.w.max_dur
        d = self.mv.tm.weapon_durability() if mx else None
        if d is None or d >= mx * frac:
            return
        s = self.mv.snap(15.0)
        if not s or not self.safe(s):
            return
        r = self.mv.repair(self.safe)
        self.log(f"      수리: 내구도 {d}/{mx} → {r}")
        self.events("repair", **r)

    def care(self) -> "Care":
        return Care(self)

    def wait_escape(self, timeout: float = 40.0) -> None:
        """Wait until the quit-out ends — without waiting, the five remaining foes were all passed as 'cancel' within 0.5 s of those 10 s."""
        t0 = time.time()
        while self.esc.escaping and time.time() - t0 < timeout:
            time.sleep(0.2)

    def shake_off(self, why: str) -> dict:
        """Quit-out sends foes back to spawn (aggro reset, dead foes stay dead)."""
        return self.esc.fire(why, "shake")

    def retreat(self, nm, home) -> str:
        """Retreat along the path toward the bonfire — stop once safe (foes go back once out of their aggro range)."""
        s = self.mv.snap(5.0)
        if s is None or home is None:
            return "no_home"
        path = nm.find_path((s.player.x, s.player.y, s.player.z), tuple(home)) if nm is not None else None
        if not path:
            return "no_path"                               # (spinning in place → recover returns False → next fight is to-the-end)
        t0 = time.time()
        last = [None]

        def mode(sn):
            m = self._retreat_mode(sn)
            if m != last[0]:                               # log each switch — whether the guard was up can be read off the log (1-c)
                c = min(sn.hostile(RETREAT_GUARD_R + 1.0), key=lambda x: M.horiz(sn.player, x), default=None)
                self.log(f"      후퇴 모드: {m}" + (f" (가장 가까운 {c.npc_param} {M.horiz(sn.player, c):.1f} m)" if c else ""))
                last[0] = m
            return m

        def clear(sn) -> bool:
            p = sn.player
            return self.safe(sn) and not any(awake(c) and M.horiz(p, c) < RETREAT_CLEAR_R and abs(c.y - p.y) < FOLLOW_DY
                                             for c in sn.hostile(RETREAT_CLEAR_R + 1.0))

        def chased(sn) -> bool:                            # being hit from behind while walking off — stop and face it
            p = sn.player
            return time.time() - t0 > 1.0 and any(awake(c) and (c.anim or -1) in M.ATTACK and M.horiz(p, c) < CHASER_STOP_R
                                                  for c in sn.hostile(CHASER_STOP_R + 1.0))
        return self.mv.walk_path(nav.trim_path(path[1:], tuple(home)), nm, mode,   # walk, not run: running safety is only a NavMesh estimate (evidence-grade gate, 2026-09-26)
                                 stop=lambda sn: (time.time() - t0 > 3.0 and clear(sn)) or chased(sn))

    def fall_back(self, nm) -> str:
        """Surrounded (duel 'crowd') — walk back toward home (the way we came: Firelink / the Burg entrance) with the guard up
        until at most one foe is still with us, then stop so the caller fights that one. Foes chase at different speeds and give up at
        different distances, so backing off splits them. No quit-out (it restarts on the spot, next to the same foes)."""
        t0 = time.time()

        def split(sn) -> bool:
            p = sn.player
            n = sum(1 for c in sn.hostile(FALL_BACK_R + 1.0)
                    if awake(c) and c.anim not in (-1, None) and M.horiz(p, c) < FALL_BACK_R and abs(c.y - p.y) < FOLLOW_DY)
            return time.time() - t0 > 1.0 and n <= 1 or time.time() - t0 > FALL_BACK_MAX_S

        s = self.mv.snap(5.0)
        path = nm.find_path((s.player.x, s.player.y, s.player.z), tuple(self.home)) if (s and nm is not None and self.home) else None
        if not path:
            self._crowd_off_until = time.time() + FALL_BACK_OFF_S
            self.log(f"   둘러싸임 — 물러날 길 없음 ({'home 없음' if not self.home else 'no_path'}), {FALL_BACK_OFF_S:.0f} s 동안은 그 자리에서 싸움")
            self.events("fall_back", result="no_path")
            return "no_path"
        r = self.mv.walk_path(nav.trim_path(path[1:], tuple(self.home)), nm, "guard", stop=split)
        s = self.mv.snap(FALL_BACK_R + 1.0)
        n = 0 if s is None else sum(1 for c in s.hostile(FALL_BACK_R) if awake(c) and c.anim not in (-1, None))
        self.log(f"   둘러싸임 — 가드 든 채 지나온 길로 물러남 {time.time() - t0:.1f} s: {r}, 따라온 적 {n}")
        self.events("fall_back", result=r, secs=round(time.time() - t0, 1), near=n)
        return r

    def back_to_wall(self, nm) -> str:
        """Three or more on us (duel wall_back) — walk with the guard up to the nearest wall spot that isn't toward them and has no drop
        close, so they can only come from the front, one or two at a time. Corners first. Then the caller fights the nearest.
        No spot / no path → fight where we stand (WALL_OFF_S)."""
        t0 = time.time()
        self._wall_off_until = t0 + WALL_OFF_S
        s = self.mv.snap(WALL_BACK_R + 2.0)
        if s is None or nm is None or not hasattr(nm, "wall_spots"):
            return "no_nav"
        p = s.player
        foes = [c for c in s.hostile(8.0) if awake(c) and abs(c.y - p.y) < FOLLOW_DY]
        fx = sum(c.x for c in foes) / len(foes) if foes else p.x
        fz = sum(c.z for c in foes) / len(foes) if foes else p.z
        ux, uz = fx - p.x, fz - p.z                        # toward the foes
        L = math.hypot(ux, uz)
        cands = []
        for q, n in nm.wall_spots(p.x, p.y, p.z, r=WALL_BACK_R):
            d = math.hypot(q[0] - p.x, q[2] - p.z)
            back = -((q[0] - p.x) * ux + (q[2] - p.z) * uz) / L if L > 0.3 else 0.0   # how far it lies away from them (≥ 0 = not their side)
            if back < 0 or nm.drop_dist(*q) < WALL_SPOT_DROP:
                continue                                   # on their side (the path would cross them), or a drop close by
            cands.append((d - 1.5 * (n >= 2) - 0.3 * back, q, d))
        for _, q, d in sorted(cands)[:5]:
            path = nm.find_path((p.x, p.y, p.z), q)
            if not path or sum(math.dist(a, b) for a, b in zip(path, path[1:])) > d * 1.6 + 2.0:
                continue
            r = self.mv.walk_path(path[1:], nm, "guard", stop=lambda sn, q=q: M.horiz(sn.player, types.SimpleNamespace(x=q[0], z=q[2])) < 0.6)
            sn = self.mv.snap(5.0)
            wd = nm.wall_dist(sn.player.x, sn.player.y, sn.player.z) if sn else None
            self.log(f"   셋 이상 붙음 — 벽으로 ({q[0]:.1f},{q[1]:.1f},{q[2]:.1f}) {time.time() - t0:.1f} s: {r}, "
                     f"벽까지 {wd if wd is None else round(wd, 1)} m, 그 자리에서 하나씩")
            self.events("wall_back", result=r, spot=q, secs=round(time.time() - t0, 1), foes=len(foes))
            return r
        self.log(f"   셋 이상 붙음 — 갈 벽 자리 없음 (후보 {len(cands)}), {WALL_OFF_S:.0f} s 동안 그 자리에서 싸움")
        self.events("wall_back", result="no_spot", foes=len(foes))
        return "no_spot"

    def _crowd_capped(self) -> bool:
        """Count this 'crowd' end; the CROWD_MAX-th within CROWD_WINDOW_S switches fall-back off for CROWD_OFF_S. → True when it did."""
        now = time.time()
        hits = getattr(self, "_crowd_hits", [])
        hits = [t for t in hits if now - t < CROWD_WINDOW_S] + [now]
        if len(hits) >= CROWD_MAX:
            self._crowd_hits = []
            self._crowd_off_until = now + CROWD_OFF_S
            self.log(f"   둘러싸임 후퇴 {len(hits)}번 연속 ({CROWD_WINDOW_S:.0f} s 안) — 이번엔 물러나지 않고 {CROWD_OFF_S:.0f} s 동안 그 자리에서 싸움 (P-26 반복 방지)")
            self.events("fall_back", result="capped", n=len(hits))
            return True
        self._crowd_hits = hits
        return False

    @staticmethod
    def _retreat_mode(sn) -> str:
        """Shield up while an awake foe is still close — like _retreat_to_zone. Walking off with the guard down after a timed-out
        duel took -109 from the shield soldier 1.85 m away (2026-09-27 burg-bonfire, ROADMAP P-7(c))."""
        p = sn.player
        near = any(awake(c) and M.horiz(p, c) < RETREAT_GUARD_R and abs(c.y - p.y) < FOLLOW_DY for c in sn.hostile(RETREAT_GUARD_R + 1.0))
        return "guard" if near else "walk"

    def recover(self, why: str, nm=None) -> bool:
        """When a fight goes wrong. → is it worth continuing
          · if safe, estus up to 90 %
          · foe close and HP low: retreat toward the bonfire, drink once safe
          · no quit-out to shake off — it restarted in the same place and re-engaged immediately (repeated 5 times, HP 659 → 24, user:
            "this spot is bad for force-quitting")"""
        s = self.mv.snap(15.0)
        if s is None:
            return False
        # 'losing' (duel: took 35 % of max HP, dealt under half the foe's) counts as low whatever the HP — it ends at ~65 % from a full
        # start, and with only the 60 % line we stood there, didn't drink (foe near) and opened a new fight at once (0 'losing' acted, 10-01)
        low = s.player.hp < s.player.max_hp * 0.6 or why.endswith("losing")
        # ── 붙어 있는 적에게서 걸어서 물러나지 않는다 ([MoKa] 2026-10-01 진행) ──────────────
        #  구역 1 `--basic`: low_hp로 가드 든 채 물러나는 동안 화염병 망자가 0.95 m로 따라붙어 4번 더 침(3009 가드 깨기 포함), HP 388 → 0.
        #  붙은 적이 있으면 그 반대로 한 번 구르고 나서 물러남. 뒤가 낭떠러지면 구르지 않고 그 자리에서 싸움(→ False)
        p = s.player
        stuck_on = [c for c in s.hostile(CHASER_ROLL_R + 1.0) if awake(c) and M.horiz(p, c) < CHASER_ROLL_R and abs(c.y - p.y) < FOLLOW_DY]
        if not self.safe(s) and low and stuck_on and not why.endswith("crowd"):
            c = min(stuck_on, key=lambda x: M.horiz(p, x))
            d = M.horiz(p, c) or 1.0
            dx, dz = (p.x - c.x) / d, (p.z - c.z) / d
            if nm is not None and not nav.ground_ahead(nm, p, dx, dz, reach=2.5):
                self.log(f"   {why}: {c.npc_param} {d:.1f} m 붙어 있고 뒤에 바닥 없음 — 구르지 않고 그 자리에서 싸움")
                return False
            self.log(f"   {why}: {c.npc_param} {d:.1f} m 붙어 있음 — 반대로 구른 뒤 물러남")
            self.mv.roll_toward(s, p.x + dx * 3.0, p.z + dz * 3.0)
            s = self.mv.snap(15.0) or s
        if not self.safe(s) and low and not why.endswith("crowd"):   # crowd: fall_back already split them — fight the one that followed
            # no Darksign — like resting it revives every killed foe (user 2026-09-24) and also loses souls and humanity.
            # worse than dying (after death the bloodstain can recover them). Used while engaged, we sometimes died to hits during its 2~3 s
            r = self.retreat(nm, self.home)
            self.log(f"   {why}: 적이 가깝고 HP {s.player.hp} — 화톳불 쪽으로 물러남: {r}")
        self.heal(0.9, sips=4)
        s = self.mv.snap(5.0)
        return bool(s and s.player.hp >= s.player.max_hp * 0.6)

    # ── Fighting─────────────────────────────────────────────────
    def _near_zone(self, s, nm):
        """Nearest marked spot within ZONE_REACH of here, same floor, on this navmesh (None if already within 2.5 m)."""
        if s is None or nm is None:
            return None
        p = s.player
        best = None
        for z in ZONES:
            d = math.hypot(z[0] - p.x, z[2] - p.z)
            if d <= HOLD_ZONE_R:
                return None
            if d <= ZONE_REACH and abs(z[1] - p.y) < 1.5 and nm.on_mesh(*z) and (best is None or d < best[0]):
                best = (d, z)
        return best and best[1]

    def _retreat_to_zone(self, zone, nm) -> str:
        """Walk to the marked spot with guard up. No path → don't go (no straight-line walking)."""
        s = self.mv.snap(5.0)
        if s is None:
            return "no_snapshot"
        path = nm.find_path((s.player.x, s.player.y, s.player.z), tuple(zone))
        if not path:
            return "no_path"
        return self.mv.walk_path(nav.trim_path(path[1:], tuple(zone), within=0.8), nm, "guard", timeout_per=4.0)

    def fight(self, ptr, nm, tag: str, arena=None, desperate: bool = False, limit: float = 45.0, wait_far: bool = False,
              leash=None, may_approach=None) -> D.DuelResult:
        """If leash() is true, end the fight on that tick (cancel) — keeps a contact fight during hold-the-spot inside the safe zone (Patch C)."""
        g0 = self.esc.gen
        e = self.mv.estus_id()
        if e is not None and self.mv.tm.selected_item() != e:
            self.mv.select_item(e)                         # pre-select — so there are no 1~3 s of cycling slots when an opening comes
        self.reflex.nm = nm
        want = getattr(self, "grip_want", None) or self.style.grip   # grip_want: a caller's override (souls/asylum: two hands for the demon)
        if self.mv.tm.grip() not in (None, want):
            # on the first run (right after resting) one toggle + 0.5 s sometimes didn't switch it (2026-09-25, rush style 1st target
            # fought still at grip 1) — retry until the switch is actually confirmed
            for _ in range(3):
                self.mv.pad.two_hand_right()               # hold Y + RB toggle
                time.sleep(0.5)
                g = self.mv.tm.grip()
                if g == want:
                    break
            self.log(f"   잡기: grip {self.mv.tm.grip()} (원함 {want})")
        self.mv.cam_target = ptr                           # camera.CamFollow turns the camera toward this foe
        try:
            r = D.duel(self.mv, self.w, ptr, nm, log=self.log,
                       cancel=lambda: self.esc.escaping or self.esc.gen != g0 or (leash is not None and leash()),
                       care=Care(self), reflex=self.reflex, arena=arena, low_hp=0.0 if desperate else RETREAT_HP, style=self.style,
                       limit=limit, wait_far=wait_far, gen=self.esc.gen, events=self.events, may_approach=may_approach,
                       crowd_ok=CROWD_FALL_BACK and time.time() >= self._crowd_off_until,
                       wall_ok=WALL_BACK and time.time() >= getattr(self, "_wall_off_until", 0.0),
                       advisor=getattr(self, "advisor", None),   # run.py --laya-shadow: record-only (LAYA.md)
                       tap=getattr(self, "tap", None))           # run.py --attack-audit: observation only (attack_audit.py)
        finally:
            self.mv.cam_target = None
        self.log(f"   {tag}{' (끝까지)' if desperate else ''}: {r.line()}")
        self.events("duel", tag=tag, npc=r.npc, result=r.result, secs=round(r.secs, 1), dealt=r.dealt, taken=r.taken)
        if r.result == "crowd" and r.wall_back:
            self.back_to_wall(nm)
        elif r.result == "crowd" and self._crowd_capped():
            pass                                           # too many in a row — fight in place (crowd_ok stays off for CROWD_OFF_S)
        elif r.result == "crowd":
            self.fall_back(nm)
        if r.result == "killed":
            self.heal(0.7)
        return r

    def _asleep(self, ptr, hold: float = 0.4) -> bool:
        """Stood (anim -1) without moving for hold? No comparison with map spawn coords — a foe standing 6 m from its spawn
        was misjudged as 'already awake' (2026-09-24 #3)."""
        s0 = self.mv.snap(SEEK_R)
        c0 = self.mv.find(s0, ptr)
        if c0 is None or c0.anim not in (-1, None):
            return False
        time.sleep(hold)
        c1 = self.mv.find(self.mv.snap(SEEK_R), ptr)
        return c1 is not None and c1.anim in (-1, None) and math.dist((c0.x, c0.y, c0.z), (c1.x, c1.y, c1.z)) < 0.3

    def lure(self, ptr, spawn, nm, tag: str, arena=None, lure_at: dict | None = None) -> str:
        """Wake just one foe (user 2026-09-24: "best is to pull them one at a time and hit", "you have throwing knives, one at a time from afar").
        If arena is within LURE_R+3 of the foe, throw from there; otherwise approach along the path only up to LURE_R and throw a knife.
        lure_at = {"spot", "min", "max"} → throw only from that spot at that range, never closer (ramp #2 shield soldier —
        user 2026-09-26: "only from a far enough distance, like the distance I threw from … out of firebomb reach").
        → 'lured' (it moved) | 'awake' (already awake, not thrown) | 'no_reaction' | 'no_knife' | 'no_path' | 'dead'
          | 'too_far' / 'too_close' / 'no_lock' (outside lure_at conditions — not thrown)"""
        lo, hi = (lure_at.get("min", LURE_MIN), lure_at.get("max", LURE_MAX)) if lure_at else (LURE_MIN, LURE_MAX)
        self.mv.cam_target = ptr                           # keep showing that foe while walking to the throw spot
        try:
            return self._lure(ptr, nm, tag, arena, lure_at, lo, hi)
        finally:
            self.mv.cam_target = None

    def _lure(self, ptr, nm, tag: str, arena, lure_at, lo: float, hi: float) -> str:
        s = self.mv.snap(SEEK_R)
        c = self.mv.find(s, ptr)
        if c is None or c.hp <= 0:
            return "dead"                                  # 152540: tried to throw a knife at the corpse of #4, already killed as an 'incoming foe'
        want = int((lure_at or {}).get("knives") or 0)   # hits wanted — throw even if awake (while it throws firebombs)
        if not want and not self._asleep(ptr):
            return "awake"
        knives = self.mv.tm.goods_count(M.ITEM_KNIFE) or 0
        if not knives:
            return "no_knife"
        quick = getattr(self.mv.tm, "quick_items", None)
        if callable(quick) and quick() and M.ITEM_KNIFE not in quick():
            return "no_knife"                              # 가지고는 있어도 퀵 슬롯에 없으면 못 고른다 (2026-09-28)
        if knives <= KNIFE_LOW:
            self.log(f"   ⚠ 투척 나이프 {knives} 개 — 상인에게 사야 한다")
        here = (s.player.x, s.player.y, s.player.z)
        goal = (c.x, c.y, c.z)
        d_arena = math.dist(tuple(arena), goal) if arena is not None else None
        if lure_at and lure_at.get("spot"):
            spot = tuple(lure_at["spot"])
        elif d_arena is not None and LURE_MIN <= d_arena <= LURE_MAX:
            spot = tuple(arena)
        else:
            # flat ground too close (#1: 5 m — walking there just wakes it) or too far → first point on the path within LURE_R
            path = nm.find_path(here, goal)
            if not path:
                return "no_path"
            spot = next((tuple(q) for q in path if math.dist(tuple(q), goal) <= LURE_R and abs(q[1] - goal[1]) <= LURE_DY), None)
            if spot is None:
                return "no_spot"                              # foes below/above a cliff have no throw spot — take the usual path (run 8: jumped down to #2 below the cliff)
        if math.dist(here, spot) > (HOLD_SPOT_TOL if lure_at else 1.5):
            r = self.walk_to(spot, nm, f"{tag} 던질 자리로", tol=HOLD_SPOT_TOL if lure_at else None) \
                if math.dist(here, spot) > 1.5 else "arrived"
            if r == "dead":
                return "dead"
            if r != "arrived":
                self.log(f"   {tag}: 던질 자리까지 {r} — 지금 자리에서 던진다")
            if lure_at:
                self._settle(spot)                         # preset throw spot: get within 0.5 m (so it doesn't clash with the 13 m minimum distance)
        c = self.mv.find(self.mv.snap(SEEK_R), ptr)
        if c is None or c.hp <= 0:
            # 155129: #4, which followed while walking to the throw spot, was killed inside walk, but here only None was seen, so lock-on on the corpse was tried for 10 s
            return "dead"
        if c.dist > hi:
            # out of lock-on range — threw 3 knives into the air at #6 (22 m, ledge above) (2026-09-24)
            self.log(f"   {tag}: 던질 자리에서 {c.dist:.1f} m — 너무 멀어 안 던진다")
            return "too_far"
        if lure_at and c.dist < lo:
            self.log(f"   {tag}: 던질 자리에서 {c.dist:.1f} m — {lo:.0f} m 안이라 안 던진다 (화염병 거리)")
            return "too_close"
        locked_once, hits = False, 0
        for n in range(1, (want + 2 if want else LURE_TRIES) + 1):
            s = self.mv.snap(SEEK_R)
            cn = self.mv.find(s, ptr)
            if cn is None or cn.hp <= 0:
                return "dead"
            # stop if another awake foe approaches while throwing — the throw loop has no defense, 742 → 154 (2026-09-24 #1)
            near = [x for x in s.hostile(LURE_ABORT_R) if x.ptr != ptr and awake(x) and x.anim not in (-1, None)]
            if near:
                self.log(f"   {tag}: 다른 놈 {len(near)} 접근 ({near[0].dist:.1f} m) — 끌어오기 중단, 그놈부터")
                return "interrupted"
            if not want and not self._asleep(ptr):
                return "lured" if n > 1 else "awake"
            if n > 1 and not locked_once and lure_at:
                self.log(f"   {tag}: 락온 안 걸림 — 이 놈은 {lo:.0f} m 안으로 다가가지 않는다")
                return "no_lock"
            if n > 1 and not locked_once:
                # no lock-on = occluded or far (user: "a wall is blocking, you threw and missed") — don't throw into the air, go 4 m closer along the path
                c = self.mv.find(self.mv.snap(SEEK_R), ptr)
                if c is None:
                    return "dead"
                path = nm.find_path((s.player.x, s.player.y, s.player.z), (c.x, c.y, c.z)) if (s := self.mv.snap(5.0)) else None
                want = max(LURE_MIN, c.dist - 4.0)
                nxt = next((tuple(q) for q in (path or []) if math.dist(tuple(q), (c.x, c.y, c.z)) <= want and abs(q[1] - c.y) <= LURE_DY
                            and abs(q[1] - s.player.y) <= LURE_DY), None)
                if nxt is None:
                    return "no_spot"
                self.log(f"   {tag}: 락온 안 걸림 — {want:.0f} m 까지 다가감")
                if self.walk_to(nxt, nm, f"{tag} 더 가까이") == "dead":
                    return "dead"
                if not self._asleep(ptr):
                    return "lured"
            r = self.mv.throw_knife(ptr, require_lock=True)
            if want and r.get("why") and not (self.mv.tm.goods_count(M.ITEM_KNIFE) or 0) and self._emergency():
                r = self.mv.throw_firebomb(ptr)            # firebomb only when out of knives and about to die
                self.log(f"   {tag}: 나이프 없음 + 위기 — 화염병 → 피해 {r.get('hit')}")
            locked_once = locked_once or bool(r.get("locked"))
            s2 = self.mv.snap(25.0)
            others = [x for x in (s2.hostile(25.0) if s2 else []) if x.ptr != ptr and awake(x) and x.anim not in (-1, None)]
            self.log(f"   {tag}: 나이프 {n} ({r.get('dist')} m, 락온 {r.get('locked')}, 조준 {r.get('aim_off')}°) → "
                     f"피해 {r.get('hit')}, {'움직임' if r.get('woke') else '반응 없음'}{' | ' + r['why'] if r.get('why') else ''}"
                     f"{' | 다른 놈 깸 ' + str(len(others)) if others else ''}")
            self.events("lure", tag=tag, n=n, **{k: r.get(k) for k in ("dist", "locked", "aim_off", "hit", "woke", "knives")})
            if want:
                hits += 1 if (r.get("hit") or 0) > 0 else 0
                cn = self.mv.find(self.mv.snap(SEEK_R), ptr)
                if cn is None or cn.hp <= 0:
                    return "dead"
                if hits >= want:
                    return "lured"
                if r.get("ok"):
                    time.sleep(0.3)
                continue
            if r.get("woke"):
                return "lured"
            if not r.get("ok"):
                time.sleep(0.5)
        return "lured" if hits else "no_reaction"

    def _emergency(self) -> bool:
        """About to die — HP under 35 % and no estus (condition for firebombs, user: 'bombs are better than dying')."""
        s = self.mv.snap(5.0)
        return s is not None and s.player.hp < 0.35 * (s.player.max_hp or 1) and self.estus_left() <= 0

    # ── Hold the spot (Patch C, 2026-09-26) ─────────────────────
    # previously the shield was up the whole wait (B-1) so stamina never refilled (R3 34/106). Now each tick only judges and returns state; no fighting
    # here. Shield only when an approaching foe is actually closing. A foe in contact: if stamina is short, defend in place only (_defend_in_place);
    # if enough and it is inside the safe zone, a fight bound to its identity (_zone_leash) — ends if it leaves the zone or a second foe closes in.

    def _in_zone(self, spot, x: float, y: float, z: float, nm) -> bool:
        if math.hypot(x - spot[0], z - spot[2]) > HOLD_ZONE_R or abs(y - spot[1]) >= 1.2:
            return False
        return nm is None or nm.on_mesh(x, y, z)

    def _closing(self, c, h: float) -> bool:
        """Did that foe close by more than APPROACH_DV over the last 0.5 s (from horizontal distance history — anim IDs not used)."""
        hist = self.__dict__.setdefault("_hold_hist", {}).setdefault(c.ptr, [])
        now = time.time()
        hist.append((now, h))
        while hist and now - hist[0][0] > 1.0:
            hist.pop(0)
        old = [hh for t, hh in hist if now - t >= 0.5]
        return bool(old) and old[-1] - h >= APPROACH_DV

    def _return_leg_toward_foe(self, spot, s, nm, ignore=()):
        """If the first leg of the return path (RETURN_LEG_M) points at an awake foe (cos > 0.5) and not toward the spot (cos < 0.5), that foe; else None."""
        if nm is None:
            return None
        p = s.player
        path = nm.find_path((p.x, p.y, p.z), tuple(spot))
        if not path:
            return None
        q = next((tuple(x) for x in path[1:] if math.hypot(x[0] - p.x, x[2] - p.z) >= RETURN_LEG_M), tuple(path[-1]))
        lx, lz = q[0] - p.x, q[2] - p.z
        L = math.hypot(lx, lz)
        if L < 0.3:
            return None
        sx, sz = spot[0] - p.x, spot[2] - p.z
        if (lx * sx + lz * sz) / (L * (math.hypot(sx, sz) or 1e-9)) >= 0.5:
            return None
        for c in s.hostile(SEEK_R):
            if c.ptr in ignore or not awake(c) or c.hp <= 0:
                continue
            cx, cz = c.x - p.x, c.z - p.z
            if (lx * cx + lz * cz) / (L * (math.hypot(cx, cz) or 1e-9)) > 0.5:
                return c
        return None

    def _hold_at(self, spot, nm, tag: str, s=None, ignore=()) -> tuple[str, object]:
        """Judge one tick → (state, foe). States: returning | coming | low_stamina_threat | contact_in_zone | contact_out_of_zone |
        approach | calm. No fighting or approaching — the caller (clear) decides from the state."""
        self.mv.show_spot = (tag, tuple(spot), time.time())     # viewers only (radar)
        s = s or self.mv.snap(SEEK_R)
        if s is None:
            time.sleep(0.05)
            return "calm", None
        p = s.player
        d_spot = math.dist((p.x, p.y, p.z), spot)
        if d_spot > HOLD_SPOT_TOL:
            if d_spot > 1.5:
                foe_c = self._return_leg_toward_foe(spot, s, nm, ignore)
                if foe_c is not None:
                    # 160200: from the throw spot (17 m from the arena) the first leg back to the arena bent east (toward #6), approaching the descending #6
                    # at 0.96 m/s (chase watchdog stopped). If the first leg heads at an awake foe and not toward the arena, don't walk — defend in place
                    self.mv.guard(True)
                    self.mv.face(s, foe_c, deg=20.0)
                    time.sleep(0.1)
                    return "returning", None
                self.walk_to(spot, nm, f"{tag} 제자리로", tol=HOLD_SPOT_TOL)
            self._settle(spot)
            return "returning", None
        coming = [c for c in s.hostile(FOLLOW_R + 2.0) if awake(c) and c.ptr not in ignore and c.anim not in (None, -1)
                  and M.horiz(p, c) < FOLLOW_R + 2.0 and abs(c.y - p.y) < FOLLOW_DY]
        if coming:
            return "coming", min(coming, key=lambda x: M.horiz(p, x))   # the existing 'incoming foe' branch handles it — nothing done here
        near = [c for c in s.hostile(HOLD_CALM_R + 3.0) if abs(c.y - p.y) < 1.2 and M.horiz(p, c) <= HOLD_CALM_R]
        self.mv.pad.move(0.0, 0.0)
        if not near:
            self.mv.guard(False)                           # when calm, lower the shield to refill stamina
            time.sleep(0.05)
            return "calm", None
        t = min(near, key=lambda x: M.horiz(p, x))
        h = M.horiz(p, t)
        sp_ok = (p.sp or 0) >= HOLD_GUARD_SP * (p.max_sp or 1)
        closing = self._closing(t, h)
        if h <= HOLD_GUARD_R:
            if not sp_ok:
                self.mv.guard(False)
                return "low_stamina_threat", t
            if self._in_zone(spot, t.x, t.y, t.z, nm):
                return "contact_in_zone", t
            self.mv.guard(closing)
            time.sleep(0.05)
            return "contact_out_of_zone", t
        self.mv.guard(sp_ok and closing)
        time.sleep(0.05)
        return "approach", t

    # Patch E-1/E-1b: conditions to wait instead of going after a moved arena target. E-1b (user 2026-09-26 "attacked the second enemy in a
    # dangerous area"): even at the same height, wait if outside the arena zone or near the shield soldier spawn — chased #3 to 8.8 m from the shield soldier and got spotted (133016)
    def _wait_reasons(self, c, arena, pending) -> list:
        out = []
        if abs(c.y - arena[1]) > MOVED_WAIT_DY:
            out.append(f"평지와 높이차 {c.y - arena[1]:+.1f} m")
        d = math.hypot(c.x - arena[0], c.z - arena[2])
        if d > HOLD_ZONE_R:
            out.append(f"평지 구역 밖 {d:.1f} m")
        for pe in pending:
            if (pe.get("lure_at") or {}).get("hold"):
                ds = math.hypot(c.x - pe["pos"][0], c.z - pe["pos"][2])
                if ds < HOLD_KEEP_R:
                    out.append(f"제자리 고수 대상 #{pe.get('label')} 스폰에서 {ds:.1f} m")
        return out

    def _approach_guard(self, arena, pending, binds: dict):
        """'may I approach' (cc, snapshot) → bool that E-2·E-3 pass to duel.
        · listed target still at spawn → yes (ledge-above #4~#6 are climbed up to and killed as before)
        · listed target that moved → no if an E-1b wait condition holds (different height / outside arena zone / within 12 m of shield soldier spawn) — regardless of player position
        · unlisted foe → blocked by the same conditions only when the player is near the arena (6 m, same height) (ledge fights unchanged)"""
        if arena is None:
            return None

        def spawn_of(ptr):
            for pe in pending:
                b = binds.get(id(pe)) or {}
                if b.get("ptr") == ptr and b.get("gen") == self.esc.gen:
                    return pe["pos"]
            return None

        def may(cc, sn) -> bool:
            p = sn.player if sn is not None else None
            # removed the ranged exception (engage if same height 1.2 m and outside shield soldier 12 m) (evidence-grade gate, 2026-09-26) — both values are code_constant_only, not grounds for approaching
            sp = spawn_of(cc.ptr)
            if sp is not None:
                moved = math.hypot(cc.x - sp[0], cc.z - sp[2]) > MOVED_R or abs(cc.y - sp[1]) > MOVED_DY
                return not (moved and self._wait_moved(cc, arena, pending))
            near_arena = p is not None and math.hypot(p.x - arena[0], p.z - arena[2]) <= 6.0 and abs(p.y - arena[1]) < 1.2
            return not (near_arena and self._wait_moved(cc, arena, pending))
        return may

    def _wait_moved(self, c, arena, pending) -> bool:
        return bool(self._wait_reasons(c, arena, pending))

    def _wait_why(self, c, arena, pending) -> str:
        return ", ".join(self._wait_reasons(c, arena, pending))

    def _arena_wait(self, arena, nm, ignore, secs: float) -> str | None:
        """Only wait/defend ticks on the arena (flat ground) for secs — no approaching. → 'died' | None"""
        lb, t0 = LureBlock(), time.time()
        while time.time() - t0 < secs:
            if not self.alive():
                return "died"
            s = self.mv.snap(SEEK_R)
            if s is None:
                time.sleep(0.1)
                continue
            if self._hold_tick("평지", tuple(arena), s, nm, arena, ignore, lb, {}) == "died":
                return "died"
            time.sleep(0.05)
        return None

    def _hold_tick(self, i, spot, s, nm, arena, ignore, lb, hold_until: dict):
        """One tick at the spot — by _hold_at state: defend in place / leashed contact fight. Shared by hold-the-spot (#2) and arena wait (E-1).
        → 'died' | None"""
        st, thr = self._hold_at(spot, nm, f"#{i}", s, ignore)
        if st == "low_stamina_threat":
            # end this wait (block new lures), defend in place only — neither approach nor keep blocking
            if not lb.on:
                self.log(f"   #{i}: 스태미나 {s.player.sp}/{s.player.max_sp} 인데 {thr.npc_param} {M.horiz(s.player, thr):.1f} m"
                         " — 제자리 방어")
            hold_until[i] = time.time()
            lb.set()
            self._defend_in_place(thr.ptr, nm)
        elif st == "contact_in_zone":
            lb.set()
            r = self.fight(thr.ptr, nm, f"hold 접촉 {thr.npc_param}", arena=arena, limit=COMING_LIMIT,
                           wait_far=True, leash=self._zone_leash(thr, spot, nm))
            if r.result == "me_dead":
                return "died"
        return None

    def _defend_in_place(self, threat_ptr, nm) -> str:
        """Low stamina with a foe in contact — only defend in place for DEFEND_SLICE. Stick neutral (no approach), shield only when the reflex sees an attack
        actually start (not held up), reflex counter (backstep attack) off. Below 25 % HP, the existing recover() (retreat and drink).
        → 'defended' | 'recovered' | 'cancel'"""
        saved = self.reflex.bs_attack
        self.reflex.bs_attack = False
        t0 = time.time()
        try:
            self.mv.pad.move(0.0, 0.0)
            self.mv.guard(False)
            while time.time() - t0 < DEFEND_SLICE:
                if self.esc.escaping:
                    return "cancel"
                s = self.mv.snap(10.0)
                if s is None:
                    time.sleep(0.05)
                    continue
                p = s.player
                if p.max_hp and p.hp < 0.25 * p.max_hp:
                    self.recover("제자리 방어 중 HP 낮음", nm)
                    return "recovered"
                self.reflex.update(s)
                self.reflex.tick(s)
                time.sleep(0.03)
            return "defended"
        finally:
            self.reflex.bs_attack = saved
            self.mv.pad.move(0.0, 0.0)

    def _zone_leash(self, threat, spot, nm):
        """Contact-fight leash — only for the identity first bound (ptr, handle, generation). True if the identity changes, that foe or I leave the safe zone, or another foe
        closes within CLOSE_MELEE_R → fight ends that tick. Does not switch targets to another foe."""
        ptr, handle, gen = threat.ptr, self.mv.tm.handle(threat.ptr), self.esc.gen

        def leash() -> bool:
            if self.esc.gen != gen:
                return True
            s = self.mv.snap(10.0)
            if s is None:
                return False
            c = self.mv.find(s, ptr)
            if c is None or c.hp <= 0 or self.mv.tm.handle(ptr) != handle:
                return True
            p = s.player
            if not self._in_zone(spot, c.x, c.y, c.z, nm) or not self._in_zone(spot, p.x, p.y, p.z, nm):
                return True
            return any(x.ptr != ptr and M.horiz(p, x) < CLOSE_MELEE_R and abs(x.y - p.y) < 1.2
                       for x in s.hostile(CLOSE_MELEE_R + 1.0))
        return leash

    def find_at(self, npc: int, pos, r: float = 3.0, dy_max: float = 3.0):
        """That type near spawn pos. Even when searching wide (30 m), only **within dy_max height diff** — from below the ramp it took #6 on the ledge above as #1,
        walked toward a 15 m cliff and got stuck three times for 17 s each (2026-09-24 night run 3, 5 min wasted)."""
        s = self.mv.snap(200.0)
        if s is None:
            return None
        cands = [c for c in s.chars if c.npc_param == npc and c.hp > 0 and math.dist((c.x, c.y, c.z), tuple(pos)) < r
                 and abs(c.y - pos[1]) <= dy_max]
        return min(cands, key=lambda c: math.dist((c.x, c.y, c.z), tuple(pos)), default=None)

    # ── Target liveness (Patch A, 2026-09-26) ─────────────────────────
    # find_at only looks near spawn within 3 m height diff, so #3 (raw HP 75), which came down from the ledge to the arena, was dropped as "not within 30 m of spawn — already dead"
    # (R1·R2·R3 observe 101202·101538·101913). A target is found at spawn only once, then tracked by **runtime identity**
    # (ptr + handle + esc.gen). Death = raw HP 0 in **two consecutive distinct snapshots** within the same generation. The raw death flag is
    # unknown (OBSERVE.md). An unreadable tick (read_chr failed → dropped from the list) is 'missing', not death.
    # quit-out / reload (esc.gen change) is a new-life boundary — drop the old identity and re-bind from spawn (R1: #2 at 0 stood up again at 85).

    def _bind(self, b: dict, e: dict, s) -> None:
        """Find an unbound target at its spawn and bind it (find_at — first resolution only)."""
        c = self.find_at(e["npc"], e["pos"], 3.0) or self.find_at(e["npc"], e["pos"], 12.0) or self.find_at(e["npc"], e["pos"], 30.0)
        if c is None:
            return
        b.update(ptr=c.ptr, handle=self.mv.tm.handle(c.ptr), gen=self.esc.gen, zero_n=0, zero_t=None,
                 last_hp=c.hp, missing_since=None)

    def _liveness(self, b: dict, e: dict, s) -> tuple[str, object]:
        """→ (state, chr). state: 'dead' | 'moved' | 'alive' | 'missing' | 'unknown' | 'unbound'."""
        if b.get("ptr") is None:
            return "unbound", None
        if b["gen"] != self.esc.gen:                       # new-life boundary — drop the old identity
            b.clear()
            return "unknown", None
        c = self.mv.find(s, b["ptr"])
        if c is not None and self.mv.tm.handle(b["ptr"]) != b["handle"]:
            c = None                                       # a different foe at the same ptr — not that one
        now = time.time()
        if c is None:
            if b.get("missing_since") is None:
                b["missing_since"] = now
            if now - b["missing_since"] >= MISSING_S:
                b.clear()
                return "unknown", None
            return "missing", None
        b["missing_since"] = None
        if c.hp <= 0:
            if b.get("zero_t") != s.t:
                b["zero_n"] = b.get("zero_n", 0) + 1
                b["zero_t"] = s.t
            if b["zero_n"] >= 2:
                return "dead", c
            return "alive", c                              # a single 0 is not conclusive yet — check the next snapshot
        b["zero_n"], b["zero_t"], b["last_hp"] = 0, None, c.hp
        far = math.dist((c.x, c.z), (e["pos"][0], e["pos"][2])) > MOVED_R or abs(c.y - e["pos"][1]) > MOVED_DY
        return ("moved" if far else "alive"), c

    def clear(self, targets: list[dict], nm, tries: int = 3, arena=None, lure: bool = False) -> str:
        """Engagement queue (2026-09-25 layer design step 2): **if awake foes are coming, handle them nearest first**; only when none, lure or go to
        the next foe on the spawn list. Most actual kills were 'foes that chased us on the way', yet the old code treated that as an exception inside walk.
        targets = [{"npc":…, "pos":[x,y,z], "label":n, "lure":bool}, …] is the 'who to wake next' intent.
        → 'cleared' | 'left #2 #4' (not killed after three tries; '#3?' = liveness unconfirmed, not treated as dead) | 'died' | 'no_estus'
          | 'partial deferred_unreachable #2' (hold-the-spot target never lured — not a success, not approached)"""
        pending = list(targets)
        lure_n: dict = {}                                  # hold-the-spot targets: lure attempts / wait end / deferred once?
        hold_until: dict = {}
        deferred: dict = {}
        unreachable: list[str] = []                        # hold-the-spot targets never lured in the end (Patch B)
        blocks: dict = {}                                  # LureBlock per hold-the-spot target (Patch C)
        wait_since: dict = {}                              # when we started waiting on flat ground for a moved target at a different height (Patch E-1)
        moved_n: dict = {}                                 # number of times that wait ended
        binds: dict = {}                                   # id(target) → runtime identity (Patch A)
        unres: dict = {}                                   # count of not found at spawn / identity lost
        last_bind = 0.0
        left: list[str] = []
        tried: dict = {}                                   # spawn label / ptr → attempt count
        ignore: set = set()                                # incoming foes not killed in three tries (left to the quit-out watchdog)
        desperate = False
        while pending:
            if not self.alive():
                return "died"
            self.wait_escape()
            s = self.mv.snap(SEEK_R)
            if s is None:
                time.sleep(0.1)
                continue
            coming = [c for c in s.hostile(FOLLOW_R + 2.0) if awake(c) and c.ptr not in ignore and c.anim not in (None, -1)
                      and M.horiz(s.player, c) < FOLLOW_R + 2.0 and abs(c.y - s.player.y) < FOLLOW_DY]
            if coming:
                c = min(coming, key=lambda x: M.horiz(s.player, x))
                tried[c.ptr] = tried.get(c.ptr, 0) + 1
                # walking to a foe still far lets other awake foes join meanwhile, so one that would come alone becomes several at once
                # (user 2026-09-25: "it would come if you waited, why did you rush up and miss the chance") — wait if out of reach
                r = self.fight(c.ptr, nm, f"오는 놈 {c.npc_param}" + (f" ({tried[c.ptr]}번째)" if tried[c.ptr] > 1 else ""),
                               arena=arena, desperate=desperate, limit=COMING_LIMIT, wait_far=True,
                               may_approach=self._approach_guard(arena, pending, binds))
                if r.result == "me_dead":
                    return "died"
                if r.result == "unsafe_approach":
                    # E-2 loop fix (2026-09-26 134451): opening a new fight right away against a ranged foe (no wait_far) meant opening and closing
                    # 20+ fights per second, standing with no defense. Run wait/defend ticks on the arena for UNSAFE_PAUSE, then re-check
                    if self._arena_wait(arena, nm, ignore, UNSAFE_PAUSE) == "died":
                        return "died"
                    continue
                if r.result == "crowd":
                    tried[c.ptr] -= 1                      # fell back to split them — not a failed try against this one
                if r.result != "killed":
                    ok = self.recover(f"오는 놈 {r.result}", nm)
                    if not ok and self.estus_left() <= 0:
                        return "no_estus"
                    desperate = not ok
                    if r.result == "timeout" or tried[c.ptr] >= tries:
                        # timeout = engaged briefly but couldn't kill — don't drag into a bad trade, disengage right away
                        # (user 2026-09-25: "if you can't kill the interfering mob in one go, better to run"). stuck/lost differ —
                        # those just failed to reach it, so retry up to tries times ("Rush mode should attack the enemy to the end").
                        ignore.add(c.ptr)
                else:
                    desperate = False
                continue
            if time.time() - last_bind >= BIND_EVERY:        # unbound targets from spawn (usually all bound on the first pass)
                last_bind = time.time()
                for pe in pending:
                    pb = binds.setdefault(id(pe), {})
                    if pb.get("ptr") is None:
                        self._bind(pb, pe, s)
            e = pending[0]
            i = e.get("label", 0)
            b = binds.setdefault(id(e), {})
            st, c = self._liveness(b, e, s)
            if st == "dead":
                self.log(f"   #{i} {e['npc']}: 죽음 (raw HP 0 ×2, 핸들 {b.get('handle')}, 세대 {b.get('gen')})")
                pending.pop(0)
                continue
            if st == "missing":                            # briefly not visible — not treated as death
                if len(pending) > 1:
                    pending.append(pending.pop(0))
                else:
                    time.sleep(0.2)
                continue
            if st in ("unbound", "unknown"):
                if st == "unbound":
                    self._bind(b, e, s)
                    if b.get("ptr") is not None:
                        continue
                unres[i] = unres.get(i, 0) + 1
                self.log(f"   #{i} {e['npc']}: {'스폰에서 못 찾음' if st == 'unbound' else '신원 끊김(세대 변화·오래 안 보임)'}"
                         f" — 죽음으로 보지 않는다 ({unres[i]}번째)")
                if unres[i] >= 2:
                    left.append(f"#{i}?")
                    pending.pop(0)
                elif len(pending) > 1:
                    pending.append(pending.pop(0))
                continue
            k = tried.get(i, 0)
            la = e.get("lure_at") or {}
            if arena is not None and not la.get("hold") and st == "moved" and self._wait_moved(c, arena, pending):
                # Patch E-1 (user 2026-09-26): if an arena target (#1·#3 etc.) moved to a different height, don't go find it; wait on the arena
                # — same as shield soldier hold-the-spot; if it comes down, the 'incoming foe' branch takes it. After Patch A the bot walked up to the descending #3's **old
                # spot** (on the ramp) and left the arena (observe 131752·132053, 5.95~6.0 m from the arena).
                w0 = wait_since.get(i)
                if w0 is None:
                    w0 = wait_since[i] = time.time()
                    self.log(f"   #{i} {e['npc']}: 움직임 — {self._wait_why(c, arena, pending)} — 찾아가지 않고 평지에서 기다림")
                if time.time() - w0 < MOVED_WAIT_S:
                    if self._hold_tick(i, tuple(arena), s, nm, arena, ignore, blocks.setdefault(("wait", i), LureBlock()), {}) == "died":
                        return "died"
                    continue
                wait_since.pop(i, None)
                moved_n[i] = moved_n.get(i, 0) + 1
                if moved_n[i] < 2:
                    self.log(f"   #{i}: {MOVED_WAIT_S:.0f} s 기다려도 안 내려옴 — " + ("맨 뒤로 미룬다" if len(pending) > 1 else "한 번 더 기다림"))
                    if len(pending) > 1:
                        pending.append(pending.pop(0))
                    continue
                self.log(f"   #{i} {e['npc']}: 끝내 안 내려옴 — 찾아가지 않는다 (핸들 {b.get('handle')}, 위치 "
                         f"({c.x:.1f},{c.y:.1f},{c.z:.1f}))")
                left.append(f"#{i}~")
                pending.pop(0)
                continue
            wait_since.pop(i, None)
            if lure and la.get("hold"):
                # hold the spot (user 2026-09-26: "hold the position where you killed the first enemy — the 2nd enemy gets pulled there. Doing it near there,
                # the shield soldier doesn't notice"). When luring failed the bot walked to the shield soldier and was spotted every time at (-28,-49.3,23.8) — 8.8~9.1 m from the shield soldier
                # (observe 090241·092141·092612·094231). The user never entered within 12 m of the shield soldier and threw from 13.7 m
                spot = tuple(la["spot"])
                lb = blocks.setdefault(i, LureBlock())
                near5 = any(abs(x.y - s.player.y) < 1.2 and M.horiz(s.player, x) <= HOLD_CALM_R
                            for x in s.hostile(HOLD_CALM_R + 3.0))
                if time.time() < hold_until.get(i, 0.0) or lb.update(near5, time.time()):
                    if self._hold_tick(i, spot, s, nm, arena, ignore, lb, hold_until) == "died":
                        return "died"
                    continue
                if lure_n.get(i, 0) < HOLD_TRIES:
                    lr = self.lure(c.ptr, e["pos"], nm, f"#{i}", arena=arena, lure_at=la)
                    lure_n[i] = lure_n.get(i, 0) + 1
                    self.log(f"   #{i} 끌어오기 {lure_n[i]}/{HOLD_TRIES}: {lr}")
                    if lr == "no_knife":
                        lure = self._no_knife()
                        continue
                    if lr == "dead":
                        pending.pop(0)
                    elif lr != "lured":
                        hold_until[i] = time.time() + HOLD_WAIT   # wait in place — incoming foes are taken by the 'incoming foe' branch above
                        self.log(f"   #{i}: 다가가지 않고 던질 자리에서 {HOLD_WAIT:.0f} s 기다림")
                    continue
                # Patch B: never go after it even after deferring — previously on its second turn fight() walked up to within 0.85 m
                # (R3 observe 101913). Defer, try throwing from the spot one more round, and if still no luck, end safely
                if not deferred.get(i):
                    deferred[i] = True
                    lure_n[i] = 0
                    if len(pending) > 1:
                        self.log(f"   #{i}: 끌어오기 {HOLD_TRIES}번 안 됨 — 맨 뒤로 미룬다")
                        pending.append(pending.pop(0))
                    else:
                        self.log(f"   #{i}: 끌어오기 {HOLD_TRIES}번 안 됨, 남은 게 이놈뿐 — 제자리에서 한 바퀴 더")
                    continue
                self._deferred_unreachable(e, i, b, c, s)
                unreachable.append(f"#{i}")
                pending.pop(0)
                continue
            if lure and k == 0 and e.get("lure", True) and not la.get("hold"):
                lr = self.lure(c.ptr, e["pos"], nm, f"#{i}", arena=arena, lure_at=e.get("lure_at"))
                self.log(f"   #{i} 끌어오기: {lr}")
                if lr == "no_knife":
                    lure = self._no_knife()
                    continue
                tried[i] = 1
                if lr == "dead":
                    pending.pop(0)
                continue                                   # if it wakes and comes, the 'incoming foe' branch above takes it; if not, go find it next round
            tried[i] = k + 1
            r = self.fight(c.ptr, nm, f"#{i} {e['npc']}" + (f" ({tried[i]}번째)" if tried[i] > 1 else ""), arena=arena, desperate=desperate,
                           may_approach=self._approach_guard(arena, pending, binds))
            if r.result in ("unsafe_approach", "crowd"):
                tried[i] = k                               # E-2: don't count as an attempt — E-1 arena wait next round (crowd: fell back, go again)
                continue
            if r.result == "killed":
                pending.pop(0)
                desperate = False
                continue
            if r.result == "me_dead":
                return "died"
            self.wait_escape()
            if not self.alive():
                return "died"
            ok = self.recover(f"#{i} {r.result}", nm)
            if not ok and self.estus_left() <= 0:
                return "no_estus"
            desperate = not ok                             # couldn't retreat or drink — go to the end next time
            if tried[i] >= tries + 1:
                left.append(f"#{i}")
                pending.pop(0)
        if unreachable:                                    # not a success — the caller goes no further along the path
            return "partial deferred_unreachable " + " ".join(unreachable) + ("" if not left else " left " + " ".join(left))
        return "cleared" if not left else "left " + " ".join(left)

    def _deferred_unreachable(self, e: dict, i, b: dict, c, s) -> None:
        """Patch B ending contract: neutral input, shield down, no auto-tracking toward that foe, log last identity/HP/position."""
        self.mv.pad.neutral()
        self.mv.guard(False)
        p = s.player if s is not None else None
        pos = None if c is None else [round(c.x, 2), round(c.y, 2), round(c.z, 2)]
        dist = None if (c is None or p is None) else round(math.dist((p.x, p.y, p.z), (c.x, c.y, c.z)), 2)
        hp = None if c is None else c.hp
        self.log(f"   #{i} {e['npc']}: 끝내 못 끌어옴 — deferred_unreachable (핸들 {b.get('handle')}, 세대 {b.get('gen')}, "
                 f"raw HP {hp}, 위치 {pos}, 거리 {dist} m). 찾아가지 않는다")
        self.events("deferred_unreachable", label=i, npc=e["npc"], handle=b.get("handle"), gen=b.get("gen"),
                    hp=hp, pos=pos, dist=dist, lure_tries=2 * HOLD_TRIES)

    def _no_knife(self) -> bool:
        # 나이프가 없거나 퀵 슬롯에 없으면 다음 번에도 없다 — 예전엔 '이번엔 안 됨'으로 세서 8 s 기다리기를 3번 반복하고
        # 방패병을 맨 뒤로 미뤘다 (2026-09-28 Bandit Bot, 나이프 0개: 25 s 버리고 셋이 한꺼번에 붙어 사망)
        self.log("   나이프 없음 — 이번 정리는 끌어오기 없이 걸어가 붙는다")
        return False

    def _clear_old(self, targets: list[dict], nm, tries: int = 3, arena=None, lure: bool = False) -> str:
        """(old) One at a time in spawn-map order. targets = [{"npc":…, "pos":[x,y,z]}, …].
        → 'cleared' | 'left #2 #4' (not killed after three tries) | 'died' | 'no_estus'
        Missing foes are skipped (already dead — quit-out doesn't revive them)."""
        left = []
        for n, e in enumerate(targets, 1):
            i = e.get("label", n)                          # map label (records keep the map label even if the order changes)
            killed, desperate = False, False
            for k in range(tries):
                if not self.alive():
                    return "died"
                # some foes moved away from spawn chasing us — checking only 12 m skipped a living #4 as 'already dead' and we got hit in the back
                c = (self.find_at(e["npc"], e["pos"], 3.0) or self.find_at(e["npc"], e["pos"], 12.0)
                     or self.find_at(e["npc"], e["pos"], 30.0))
                if c is None:
                    self.log(f"   #{i} {e['npc']}: 스폰 30 m 안에 없음 — 이미 죽음")
                    killed = True
                    break
                self.wait_escape()
                if lure and k == 0 and e.get("lure", True):
                    lr = self.lure(c.ptr, e["pos"], nm, f"#{i}", arena=arena)
                    self.log(f"   #{i} 끌어오기: {lr}")
                    if lr == "dead":
                        killed = True
                        break
                    if lr == "interrupted":
                        s_ = self.mv.snap(SEEK_R)
                        near = [x for x in s_.hostile(LURE_ABORT_R) if x.ptr != c.ptr and awake(x) and x.anim not in (-1, None)] if s_ else []
                        if near:
                            r0 = self.fight(near[0].ptr, nm, f"#{i} 끼어든 {near[0].npc_param}", arena=arena)
                            if r0.result == "me_dead":
                                return "died"
                            c = self.find_at(e["npc"], e["pos"], 30.0) or c
                r = self.fight(c.ptr, nm, f"#{i} {e['npc']}" + (f" ({k + 1}번째)" if k else ""), arena=arena, desperate=desperate)
                if r.result == "killed":
                    killed = True
                    break
                if r.result == "me_dead":
                    return "died"
                self.wait_escape()
                if not self.alive():
                    return "died"
                ok = self.recover(f"#{i} {r.result}", nm)
                if not ok and self.estus_left() <= 0:
                    return "no_estus"
                # couldn't retreat or drink — next time don't pull out even at low HP, go to the end (repeating 'low → can't retreat → can't drink' every 0.1 s,
                # we stood without raising the shield and died, 2026-09-24)
                desperate = not ok
            if not killed:
                left.append(f"#{i}")
        return "cleared" if not left else "left " + " ".join(left)

    # ── Path───────────────────────────────────────────────────
    def walk(self, path: list, nm, tag: str, tol: float | None = None, tight: dict | None = None, mode: str = "walk",
             done=None) -> str:
        prev, self.mv.show_path = self.mv.show_path, (tag, [tuple(q) for q in path])   # viewers only (radar)
        try:
            return self._walk(path, nm, tag, tol, tight, mode, done)
        finally:
            self.mv.show_path = prev                       # a detour (walk_to inside walk) hands the outer path back

    # ── walking, in four pieces (ROADMAP 0-c): WalkPlan = where we are on the path (pure) · _follow = stick toward one point
    # (nav.goto — swap this to change how the bot steers) · _walk_chaser = a foe interrupts · _walk_missed = a point wasn't reached

    def _follow(self, q, tolerance: float, terrain, mover, on_stuck, mode_fn) -> str:
        """Follower: walk to one point. → 'arrived' | 'retreat' | 'dead' | 'timeout' | 'stuck' | 'unreachable' …"""
        return nav.goto(self.mv.tm, self.mv.pad, q, tolerance=tolerance if terrain is not None else max(tolerance, 0.8), timeout=15,
                        log=lambda *a: None, terrain=terrain, mover=mover, on_stuck=on_stuck, mode_fn=mode_fn)

    def _chaser(self, sn, ignore: set):
        """The awake foe closing in that the walk should stop for, or None.
        Shield soldiers are deferred — with several, easy ones first (user 2026-09-25: "deal with the other enemies first, I said",
        "you go to the two shield soldiers too fast" — met the two shield soldiers on the Undead Burg terrace back to back with no time to heal,
        took 220+ damage each and got surrounded). Only when there is no easy one (shield soldiers only) take that one first."""
        on_us = lambda c: M.horiz(sn.player, c) < IGNORE_CLOSE_R and ((c.anim or -1) in M.ATTACK or (c.anim or -1) in M.STAGGER)
        cands = [c for c in sn.hostile(FOLLOW_R + 1.0) if awake(c) and (c.ptr not in ignore or on_us(c))
                 and c.npc_param not in getattr(self, "ignore_npcs", ())   # e.g. the Asylum Demon while fleeing (souls/asylum)
                 and M.horiz(sn.player, c) < FOLLOW_R and abs(c.y - sn.player.y) < FOLLOW_DY
                 and (c.anim not in (None, -1) or c.dist < 2.0)]
        if not cands:
            return None
        easy = [c for c in cands if foes_.of(c.npc_param).kind != "shield"]
        return min(easy or cands, key=lambda c: c.dist if c.dist is not None else 999.0)

    def _resync_plan(self, plan: "WalkPlan", nm, window: bool) -> None:
        """Pick up the path again from where we stand (after a fight / quit-out); re-plan if that point is on another level."""
        s2 = self.mv.snap(5.0)
        if not s2:
            return
        dy = plan.resync((s2.player.x, s2.player.y, s2.player.z), nm, window)
        if dy:
            self.log(f"   {plan.tag}: 경로 재탐색 — 이어갈 점이 다른 층 (Δy {dy:+.1f} m), {len(plan.path)}점")
            self.mv.show_path = (plan.tag, list(plan.path))

    def _walk_chaser(self, plan: "WalkPlan", st, nm, mover) -> str | None:
        """goto said 'retreat': block, fight the chaser if there is one, carry on from where the fight left us. → 'dead' | 'no_estus' | None"""
        tag = plan.tag
        mover.stop()
        self.reflex.hold()                     # when an attack comes while walking, first block facing it
        s2 = self.mv.snap(40.0)
        c = self._chaser(s2, st.ignore) if s2 else None
        if c is not None and st.fights >= 15:
            st.ignore.add(c.ptr)               # fought too much on one path — leave this one to the quit-out watchdog
        elif c is not None:
            st.fights += 1
            mover.stop()
            # same principle as incoming foes (wait_far) — walking up here too lets others join meanwhile (user: "climbing up again")
            zone = self._near_zone(s2, nm)
            if zone is not None:
                zr = self._retreat_to_zone(zone, nm)
                self.log(f"   {tag}: 따라온 {c.npc_param} — 찍어 둔 자리 ({zone[0]:.1f},{zone[1]:.1f},{zone[2]:.1f})로 가드 든 채 물러남: {zr}")
                if zr == "dead":
                    return "dead"
            res = self.fight(c.ptr, nm, f"{tag}: 따라온 {c.npc_param}", arena=zone, desperate=st.desperate, wait_far=True)
            if res.result == "me_dead":
                return "dead"
            st.desperate = False
            if res.result != "killed":
                ok = self.recover(f"{tag} {res.result}", nm)
                if not ok and self.estus_left() <= 0:
                    return "no_estus"
                st.desperate = not ok
                if res.result in ("stuck", "lost"):
                    st.ignore.add(c.ptr)       # unreachable foe — ignore on this path (if it chases, the quit-out shakes it off)
            # pushed back while fighting or moved by chasing — insisting on the pre-fight target point (i) left it behind a wall/ledge
            # and got stuck (2026-09-25 return passage, two runs in a row "chaser killed → stuck 30~50 s later"). Like after a quit-out / fog wall,
            # restart from the nearest point — but only within RESYNC_BACK·RESYNC_AHEAD around i so we don't go far back.
            self._resync_plan(plan, nm, window=True)
        return None

    def _walk_missed(self, plan: "WalkPlan", st, q, r: str, nm, mover, done) -> str:
        """goto didn't reach q. → 'retry' (same point again) | 'next' | 'stuck'"""
        tag, path, i = plan.tag, plan.path, plan.i
        st.fails += 1
        s3 = self.mv.snap(5.0)
        if s3:                                  # where it gets stuck (2026-09-25 return passage stuck recurred even after fixes)
            pp = (s3.player.x, s3.player.y, s3.player.z)
            self.log(f"      {tag}: {i}/{len(path)}번 점 {tuple(round(v, 1) for v in q)} 못 감 ({r}, {st.fails}번째) — "
                     f"나 {tuple(round(v, 1) for v in pp)}, {math.dist(pp, q):.1f} m")
            self.events("walk_fail", tag=tag, i=i, n=len(path), q=[round(v, 2) for v in q],
                        pos=[round(v, 2) for v in pp], r=r, fails=st.fails)
            # a breakable prop on the way (the NavMesh doesn't know crates) — break it and try the same point again, before
            # detouring: the detour's navmesh path runs through the same crate (2026-09-27 burg-bonfire #6, ROADMAP P-6)
            if self._smash_blocking(nm, pp, q, st.smashed, tag, mover, why=f"점 못 감 ({r})"):
                st.fails = 0
                return "retry"
            d, dy = math.dist(pp, q), pp[1] - q[1]
            if r in ("stuck", "timeout") and i + 1 < len(path) and d <= ALMOST_M and abs(dy) <= ALMOST_DY:
                self.log(f"      {tag}: {i}번 점 거의 도착 ({d:.1f} m, Δy {dy:+.1f}) — 다음 점으로")
                self.events("walk_almost", tag=tag, i=i, n=len(path), d=round(d, 2), dy=round(dy, 2), r=r)
                # fails is NOT reset: in front of a fog wall the first point is almost there but the rest lie beyond it —
                # the next real miss makes fails 2 and fog_through runs at once (resetting it here cost one more point,
                # asylum 수용소4 (−7.8, 208.4, −8.2)). This return skips the 3-in-a-row 'stuck', so almost-there misses
                # never end the walk; any arrival resets fails as before.
                return "next"
            # if the straight line fails, detour once via navmesh pathfinding — pushed while fighting onto the upper passage beside the stairs (1.1~1.5 m higher),
            # heading straight for the stair point hit the railing, failing three points in a row (2026-09-25 191817 return passage points 28~30)
            # the detouring walk_to also uses walk internally — detouring again there recurses endlessly ("detour detour …",
            # 15 min timeout in front of ramp #2, 2026-09-25 194804). One level only
            if st.fails == 1 and not self._detour and nm.find_path(pp, q):
                self._detour = True
                try:
                    r2 = self.walk_to(q, nm, f"{tag} 돌아서", done=done)
                finally:
                    self._detour = False
                if r2 == "arrived":
                    st.fails = 0
                    return "next"
        if st.fails >= 2 and self.fog_through(q):
            st.fails = 0                        # passed the fog wall — restart from the nearest point
            s2 = self.mv.snap(5.0)
            if s2:
                plan.nearest((s2.player.x, s2.player.y, s2.player.z))
            return "retry"
        if st.fails >= 3:
            return "stuck"
        return "next"

    def _walk(self, path: list, nm, tag: str, tol: float | None = None, tight: dict | None = None, mode: str = "walk",
              done=None) -> str:
        """Walk the path, killing first any foe that chases and closes in. → 'arrived' | 'dead' | 'stuck' | 'no_estus'
        Per-point floor check only when both the target and current spot are on this navmesh (edges / bridges have navmesh gaps).
        Inside tight = {"center": [x,y,z], "r": m} (narrow bridge without railings), step precisely at 0.45 m."""
        plan = WalkPlan(path, tag, tol)
        st = types.SimpleNamespace(fails=0, fights=0, ignore=set(), desperate=False,
                                   smashed={},         # smashed: prop name → swings this walk (props_.blocking)
                                   fogged=set())       # FOG_WALLS already tried this walk (fog_ahead)
        self.reflex.nm = nm
        mover = nav.Mover(self.mv.pad)
        no_obs = control.NoObs(self.mv.pad, on_full=mover.stop)   # no snapshot: stick off now, everything off after a while (P0-C)
        try:
            while not plan.done:
                if self.esc.escaping:
                    time.sleep(0.2)
                    continue
                q = plan.point()
                t = plan.tolerance(tight)
                s = self.mv.snap(40.0)
                if s is None:
                    no_obs.missing()
                    time.sleep(0.1)
                    continue
                no_obs.seen()
                if done is not None and done(s):
                    mover.stop()
                    return "arrived"                       # caller-defined 'no need to go further'
                if s.player.hp < s.player.max_hp * WALK_HEAL and self.safe(s) and self.estus_left() > 0:
                    mover.stop()                           # damage taken while walking (firebombs etc.) — don't defer until the next fight
                    self.heal(0.7)
                fog = fog_ahead((s.player.x, s.player.y, s.player.z), q)
                if fog is not None and fog not in st.fogged:
                    st.fogged.add(fog)
                    mover.stop()
                    self._fog_cross(fog, (s.player.x, s.player.y, s.player.z), q, nm, tag)
                    continue
                f_q = nm.floor_at(q[0], q[2], q[1]) if len(q) > 2 else None
                f_p = nm.floor_at(s.player.x, s.player.z, s.player.y)
                terr = nm if (f_q is not None and abs(f_q[0] - q[1]) < 2.0 and f_p is not None and abs(f_p[0] - s.player.y) < 2.0) else None
                g0 = self.esc.gen

                def on_stuck(p, target, q=q):
                    # stuck on the way (nav.goto STUCK_WINDOW, 2 s) — a crate in front? break it now, not after the 15 s timeout
                    return self._smash_blocking(nm, (p.x, p.y, p.z), q, st.smashed, tag, mover,
                                                why=f"막힘 감지 ({nav.STUCK_WINDOW:.0f} s 동안 {nav.STUCK_MIN_PROGRESS} m 미만)")

                r = self._follow(q, t, terr, mover, on_stuck,
                                 mode_fn=lambda sn: "retreat" if (self.reflex.threat_now(sn) or self._chaser(sn, st.ignore)
                                                                  or self.esc.escaping or self.esc.gen != g0) else mode)
                if r == "dead":
                    return "dead"
                if self.esc.gen != g0:                     # left and returned via quit-out — restart from the nearest point
                    self._resync_plan(plan, nm, window=False)
                    continue
                if r == "retreat":
                    out = self._walk_chaser(plan, st, nm, mover)
                    if out:
                        return out
                    continue
                if r != "arrived":
                    step = self._walk_missed(plan, st, q, r, nm, mover, done)
                    if step == "stuck":
                        return "stuck"
                    if step == "retry":
                        continue
                else:
                    st.fails = 0
                plan.i += 1
            return "arrived"
        finally:
            mover.stop()

    def _smash_blocking(self, nm, me, goal, smashed: dict, tag: str, mover=None, why: str = "") -> bool:
        """A breakable prop between me and goal not yet swung at SMASH_TRIES times this walk → break it, True. Else False.
        why = what noticed the block (logged, so the time from stuck to swing can be read off the log)."""
        prop = next((o for o in props_.blocking(getattr(nm, "map_id", None), me, goal)
                     if smashed.get(o["name"], 0) < SMASH_TRIES), None)
        if prop is None:
            return False
        smashed[prop["name"]] = smashed.get(prop["name"], 0) + 1
        self.log(f"      {tag}: {why or '막힘'} — 앞길에 {prop['model']} ({prop['name']}, {math.dist(me, prop['pos']):.1f} m)")
        if mover is not None:
            mover.stop()                                   # release run (B) before stepping up and swinging
        self._smash(prop, tag)
        self.mv.show_smash = (prop["name"], tuple(prop["pos"]), time.time())    # viewers only (radar)
        return True

    def _smash(self, prop: dict, tag: str) -> None:
        """Step up to a breakable prop (to SMASH_R, or until it stops getting closer), turn to it and swing twice (light
        attack). No lock-on — props can't be locked."""
        q = prop["pos"]
        spot = types.SimpleNamespace(ptr=None, x=q[0], y=q[1], z=q[2])
        t, best = time.time(), None
        while time.time() - t < SMASH_WALK_S:
            s = self.mv.snap(5.0)
            if s is None:
                break
            h = math.hypot(q[0] - s.player.x, q[2] - s.player.z)
            if h <= SMASH_R or (best is not None and h > best - 0.02 and time.time() - t > 0.4):
                break                                      # close enough, or pressed against it
            best = h if best is None else min(best, h)
            self.mv.pad.move(*self.mv.stick_to(s, q[0], q[2], 0.5))
            time.sleep(0.1)
        self.mv.pad.move(0.0, 0.0)
        t = time.time()
        while time.time() - t < SMASH_FACE_S:
            s = self.mv.snap(5.0)
            if s is None or self.mv.face(s, spot, deg=15.0):
                break
            time.sleep(0.05)
        self.mv.pad.move(0.0, 0.0)
        for _ in range(2):
            self.mv.pad.attack()
            time.sleep(SMASH_SWING_S)
        self.log(f"      {tag}: 길 막은 {prop['model']} ({prop['name']}) 부숨 시도 — ({q[0]:.1f},{q[1]:.1f},{q[2]:.1f})")
        self.events("smash", tag=tag, prop=prop["name"], model=prop["model"], pos=q)

    def fog_through(self, toward, known: bool = False) -> bool:
        """If stuck before a fog wall: turn toward the next waypoint, and press A when the prompt appears (user: "press A at the fog wall", "align direction").
        We stood beside the fog pushing into the wall → 'blocked' (2026-09-24). The prompt only appears when facing the fog.
        known: a FOG_WALLS wall — press A without the prompt check: under the Burg wall's white light the dark-box check never
        fired (10-03b, 4 tries, no A), P-41. → passed through? (moved more than 2 m)"""
        import legacy.ladder_test as L                    # prompt detection (dark ratio at bottom center of screen, ~900 when shown)
        s = self.mv.snap(5.0)
        if s is None or s.cam_yaw is None:
            return False
        p0 = (s.player.x, s.player.y, s.player.z)
        for scale in (0.5, 0.7):
            self.mv.pad.move(*self.mv.stick_to(s, toward[0], toward[2], scale))
            time.sleep(0.3)
            self.mv.pad.move(0.0, 0.0)
            time.sleep(0.4)
            if known or L.prompt_px() >= 850:
                self.mv.press(M.B.XUSB_GAMEPAD_A, 0.3)
                time.sleep(4.5)
                s2 = self.mv.snap(5.0)
                moved = math.dist(p0, (s2.player.x, s2.player.y, s2.player.z)) if s2 else 0.0
                self.log(f"   안개벽: A → {moved:.1f} m 이동")
                if moved > 2.0 or not known:
                    return moved > 2.0
            s = self.mv.snap(5.0) or s                     # known wall, A didn't take: push a bit harder and press again
        return False

    def _fog_cross(self, fog, p, q, nm, tag: str) -> bool:
        """Known fog wall between us and q: stand FOG_FRONT_M before it on the line to q, then fog_through (turn, A on the prompt).
        No wall there any more (no prompt) → fog_through just gives up and the walk carries on as before. → passed?"""
        dx, dz = q[0] - p[0], q[2] - p[2]
        n = math.hypot(dx, dz) or 1.0
        front = (fog[0] - dx / n * FOG_FRONT_M, fog[1], fog[2] - dz / n * FOG_FRONT_M)
        if math.hypot(front[0] - p[0], front[2] - p[2]) > 0.8:
            self.walk([front], nm, f"{tag} 안개벽 앞")
        ok = self.fog_through(q, known=True)
        self.log(f"   {tag}: 안개벽 ({fog[0]:.1f}, {fog[1]:.1f}, {fog[2]:.1f}) {'통과' if ok else '못 지나감 — 그대로 걸음'}")
        self.events("fog_cross", tag=tag, fog=list(fog), ok=ok)
        return ok

    def walk_to(self, goal, nm, tag: str, mode: str = "walk", tol: float | None = None, done=None) -> str:
        s = self.mv.snap(5.0)
        if s is None:
            return "no_snapshot"
        path = nm.find_path((s.player.x, s.player.y, s.player.z), tuple(goal))
        if not path:
            return "no_path"                               # no path → don't walk straight (cliff)
        return self.walk(nav.trim_path(path[1:], tuple(goal)), nm, tag, mode=mode, tol=tol, done=done)

    def careful_walk_to(self, goal, nm, tag: str, done=None) -> str:
        """── 천천히, 기다리며, 하나씩 ([MoKa] 2026-10-01) ──────────────────────────────
         성벽 마을 `#4 이동`에서 두 번 죽음(09-30b 셋, 10-01a 셋) — "너무 성급하게 진행해서 다수에게 둘러싸임. 그쪽으로 가게 되면 천천히 가고,
         대기하면서 한 명씩 끌어당겨야 함". 그래서: CAREFUL_LEG만 걷고 멈춰 CAREFUL_LOOK_S 가드 든 채 지켜봄 →
          · 깨어 움직이는 적이 CAREFUL_COME_R 안이면 그 자리에서 기다려(wait_far) 그놈만 싸움
          · 아니면 던질 거리(LURE_MAX) 안·같은 층·길 있는 적 하나를 나이프로 깨워 기다려 싸움 (한 놈에 2번까지)
          · 아무도 없으면 다음 CAREFUL_LEG
        → 'arrived' | 'done' | 'dead' | 'no_path' | 'timeout'"""
        t0 = time.time()
        lured = self.__dict__.setdefault("_careful_lured", {})   # kept across walks — 10-01b retried the ledge crossbowman on every walk
        while time.time() - t0 < CAREFUL_MAX_S:
            if not self.alive():
                return "dead"
            self.wait_escape()
            s = self.mv.snap(SEEK_R)
            if s is None:
                time.sleep(0.1)
                continue
            p = s.player
            if done is not None and done(s):
                return "done"
            if math.hypot(p.x - goal[0], p.z - goal[2]) < 1.5 and abs(p.y - goal[1]) < FOLLOW_DY:
                return "arrived"
            same = lambda c: abs(c.y - p.y) < FOLLOW_DY
            coming = [c for c in s.hostile(CAREFUL_COME_R) if awake(c) and same(c) and c.anim not in (None, -1)]
            if coming:
                c = min(coming, key=lambda x: M.horiz(p, x))
                r = self.fight(c.ptr, nm, f"{tag}: 오는 놈 {c.npc_param}", wait_far=True, limit=COMING_LIMIT)
                if r.result == "me_dead":
                    return "dead"
                if r.result != "killed" and not self.recover(f"{tag} {r.result}", nm) and self.estus_left() <= 0:
                    return "dead"
                continue
            idle = [c for c in s.hostile(LURE_MAX) if c.hp > 0 and same(c) and lured.get(c.ptr, 0) < 2
                    and nm.find_path((p.x, p.y, p.z), (c.x, c.y, c.z))]
            if idle:
                c = min(idle, key=lambda x: M.horiz(p, x))
                lured[c.ptr] = lured.get(c.ptr, 0) + 1
                here = (p.x, p.y, p.z)
                lr = self.lure(c.ptr, (c.x, c.y, c.z), nm, f"{tag}: {c.npc_param}", arena=here)
                self.log(f"   {tag}: {c.npc_param} 끌어오기 {lured[c.ptr]}번째 — {lr}")
                if lr == "dead":
                    continue
                if lr in ("lured", "awake"):
                    r = self.fight(c.ptr, nm, f"{tag}: 끌어온 {c.npc_param}", wait_far=True, limit=COMING_LIMIT)
                    if r.result == "me_dead":
                        return "dead"
                    if r.result != "killed":
                        self.recover(f"{tag} {r.result}", nm)
                    continue
                if lr in ("no_knife", "no_spot", "no_path"):   # no_lock / too_far / too_close: may work from the next stop
                    lured[c.ptr] = 2                       # can't pull it from here (ledge, no throw spot) — walk on, it comes when it sees us
            path = nm.find_path((p.x, p.y, p.z), tuple(goal))
            if not path:
                return "no_path"
            leg, acc = [], 0.0
            for a, b in zip(path, path[1:]):
                leg.append(b)
                acc += math.dist(a, b)
                if acc >= CAREFUL_LEG:
                    break
            r = self.walk(leg, nm, tag, mode="walk")
            if r == "dead":
                return "dead"
            self.mv.pad.move(0.0, 0.0)
            getattr(self.mv.pad, "guard", lambda on: None)(True)
            time.sleep(CAREFUL_LOOK_S)
            getattr(self.mv.pad, "guard", lambda on: None)(False)
        return "timeout"

    def _settle(self, spot, tol: float = None, tries: int = 10) -> float:
        """Last few steps — short stick taps to get within tol of spot (horizontal). Throw-spot tolerance 1.5 m clashed with the 13 m lure minimum,
        giving 12.8~13.0 m → 'too_close' (R3 101913, 134451 three times) — user-approved 2026-09-26 'to 0.5 m'. → remaining distance"""
        tol = HOLD_SPOT_TOL if tol is None else tol
        d = None
        for _ in range(tries):
            s = self.mv.snap(5.0)
            if s is None or s.cam_yaw is None:
                break
            d = math.hypot(s.player.x - spot[0], s.player.z - spot[2])
            if d <= tol:
                break
            self.mv.pad.move(*self.mv.stick_to(s, spot[0], spot[2], 0.45))
            time.sleep(0.12)
            self.mv.pad.move(0.0, 0.0)
            time.sleep(0.12)
        return d if d is not None else 0.0

    # ── Bloodstain────────────────────────────────────────────────
    def pick_blood(self, nm, near: float = 20.0, bonfire_ok: bool = False) -> str | None:
        """bonfire_ok: we'll sit at this bonfire anyway, so A accidentally sitting is fine (bloodstain next to the Undead Burg bonfire)."""
        b = Blood.read()
        if not b:
            return None
        pos = tuple(b["pos"])
        if not bonfire_ok and any(math.dist(pos, bf) < BONFIRE_NO_A for bf in self.bonfires):
            self.log(f"   핏자국 {pos} 이 화톳불 옆 — A 를 누르면 앉아 버려(적 전부 부활) 안 줍는다. 기록은 남긴다")
            return "near_bonfire"
        s = self.mv.snap(5.0)
        if s is None or math.dist((s.player.x, s.player.y, s.player.z), pos) > near:
            return None
        r = self.walk_to(pos, nm, "핏자국")
        if r != "arrived":
            return r
        souls0 = self.mv.tm.souls() or 0
        got = False
        for k in range(PICK_TRIES):                        # 09-30·10-01: the first A on arrival missed both times, a later one took it
            if k:
                time.sleep(1.0)
            self.mv.press(M.B.XUSB_GAMEPAD_A)
            time.sleep(1.5)
            got = (self.mv.tm.souls() or 0) > souls0
            if got:
                break
        self.log(f"   핏자국: {'회수' if got else '못 주움'} (소울 {souls0} → {self.mv.tm.souls()})")
        return "got" if got else "miss"

    # ── Rest─────────────────────────────────────────────────
    def rest_at(self, nm, bonfire: dict) -> bool:
        """Walk to the bonfire fighting along the way and rest. **Every foe revives** — only when starting a fresh run."""
        if not self.alive() and not self.wait_respawn():
            return False
        s = self.mv.snap(5.0)
        stand = tuple(bonfire["stand"])
        if s and math.dist((s.player.x, s.player.y, s.player.z), stand) > 5.0:
            r = self.walk_to(stand, nm, "화톳불로")
            self.log(f"   화톳불로: {r}")
            if r == "dead":
                self.wait_respawn()
        ok = self.mv.rest(nm, bonfire)
        self.forget_foes()
        return ok


class Care:
    """In-fight healing (duel's care). Whether to drink is decided here (layer 4), whether it's an opening by duel.opening (layer 3).
    Reading estus count every tick is heavy (32 KB) — recount only when drinking."""

    def __init__(self, f: Field):
        self.f = f
        self.left = f.estus_left()

    def wants(self, s) -> bool:
        return self.left > 0 and s.player.hp < s.player.max_hp * FIGHT_HEAL

    def take(self, recheck) -> dict:
        r = self.f.mv.drink(recheck)
        self.left = r.get("left", self.f.estus_left())
        self.f.events("estus", fight=True, **r)
        return r
