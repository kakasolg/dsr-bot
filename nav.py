"""
Navigation primitive — walk to a target point in global coordinates.

  goto(tm, pad, (x, z)) : keeps steering the stick relative to camera yaw until it reaches the target.
                          If it gains < 0.3 m in 2 s it is "stuck" → tries to escape with a jump + sidestep.
  Measured (2026-09-21): stick forward = cam_yaw direction, right = +90°. Walk ~2.5 m/s, B-hold run ~3.7 m/s.

── Known limitations ──────────────────────────────
 · No obstacle avoidance (straight-line steering). Dense waypoints stand in for it.
 · Height (y) is ignored. Drop-risk sections are bypassed via waypoints.
"""
from __future__ import annotations

import math
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import control
import env
import telemetry

YAW_OFFSET = 0.0
FLIP_X = False
SPRINT_BEYOND = 8.0     # run when farther than this
STUCK_WINDOW = 2.0      # seconds
STUCK_MIN_PROGRESS = 0.3  # m
PROBE_FWD, PROBE_BACK, PROBE_HOLD = 0.8, 0.35, 0.45   # one probe cycle: forward/back/hold (s). Net gain ~0.7 m
CREEP_STICK = 0.45        # measured (guard up): stick <0.4 = stop, 0.4~0.7 = walk 1.64 m/s, 1.0 = jog 3.24 m/s. Walk is the slowest speed
ENGAGE_STICK = 0.5        # engagement approach also walks
ARRIVE_DY = 2.0         # arrival check also looks at height — with horizontal distance only, a path point 10 m above counts as "arrived", so
                        # on a spiral ramp it skipped the whole path and stood below the target getting hit (measured)
UNREACHABLE_DY = 1.5      # m — within 5 m in 2D but height difference larger than this = cliff/floor-level difference


JUMP_PERIOD = 1.2       # guardjump mode: jump at this period
JUMP_GUARD_OFF = 0.35   # time LB is released just before/after a jump


class Mover:
    """Movement-mode state machine. Give the desired mode via set(mode) each tick and it keeps the needed button state.
      walk       press nothing (stamina recovery)
      sprint     hold B
      guardjump  hold LB + every JUMP_PERIOD (release LB → A jump → LB) — fast, protected by jump i-frames + guard (Elden Ring)
      guard      hold LB only (DSR — no jump. DS1 jump is run+B, so it only causes accidents)
    """

    def __init__(self, pad: control.Pad):
        self.pad = pad
        self.mode = "walk"
        self.next_jump = 0.0
        self.guard_on = False
        self.jump_at = None

    def set(self, mode: str) -> None:
        now = time.time()
        if mode != self.mode:
            self.pad.sprint(mode == "sprint")
            if mode not in ("guardjump", "guard") and self.guard_on:
                self.pad.guard(False)
                self.guard_on = False
            if mode == "guardjump":
                self.next_jump = now + JUMP_PERIOD * 0.5
            self.mode = mode
        if mode == "guard":
            if not self.guard_on:
                self.pad.guard(True)
                self.guard_on = True
        elif mode == "guardjump":
            if self.jump_at is not None:
                if now - self.jump_at > JUMP_GUARD_OFF and not self.guard_on:
                    self.pad.guard(True)
                    self.guard_on = True
                    self.jump_at = None
            elif now >= self.next_jump:
                if self.guard_on:
                    self.pad.guard(False)
                    self.guard_on = False
                self.pad.jump()
                self.jump_at = now
                self.next_jump = now + JUMP_PERIOD
            elif not self.guard_on:
                self.pad.guard(True)
                self.guard_on = True

    def stop(self) -> None:
        self.pad.neutral()
        self.mode, self.guard_on, self.jump_at = "walk", False, None


BACK_PROBE = 1.4          # look this far ahead when backing up (m)
BACK_MAX_DROP = 1.2       # don't go if the floor there is more than this lower than the current one


FACE_STICK = 0.45         # measured (guard up): below 0.4 doesn't even turn (deadzone); 0.45 turns 84° in 0.6 s and walks 0.75 m
FACE_TOL = math.radians(20)
FOOTING_R = 1.6           # radius for measuring footing safety (m)
FOOTING_MIN = 0.6         # worse than this: don't fight at that spot


def footing(terrain, p, r: float = FOOTING_R):
    """**Footing safety** at the current spot — fraction of 12 surrounding directions that have floor, and the safest direction.

    User principle: "First, you shouldn't be in a dangerous position in the first place." Rather than detecting after falling while backing up,
    it's better not to start a fight next to a cliff. Fights last several seconds, during which you get pushed and turned."""
    if terrain is None:
        return 1.0, None
    ok, best, best_n = 0, None, -1
    for k in range(12):
        a = k * math.pi / 6
        qx, qz = p.gx + math.sin(a) * r, p.gz + math.cos(a) * r
        hit = terrain.floor_at(qx, qz, p.gy)
        good = hit is not None and hit[0] > p.gy - BACK_MAX_DROP
        if good:
            ok += 1
            # a direction is better if there is still floor one more step out
            q2 = terrain.floor_at(p.gx + math.sin(a) * r * 2, p.gz + math.cos(a) * r * 2, p.gy)
            n = 2 if (q2 is not None and q2[0] > p.gy - BACK_MAX_DROP) else 1
            if n > best_n:
                best_n, best = n, (math.sin(a), math.cos(a))
    return ok / 12.0, best


def ground_ahead(terrain, p, dx: float, dz: float, reach: float = 1.2) -> bool:
    """Is there floor to step on reach m ahead in that direction (NavMesh, no big drop). True if terrain is None.

    Combat movement (approaching, turning, circling) pushes the stick toward the enemy rather than a path point, so it can leave the NavMesh.
    Measured (merchant run #1): fighting on a ramp, got pushed to the edge and fell 22 m to death — footing was only checked when standing still (hold)."""
    if terrain is None:
        return True
    n = math.hypot(dx, dz)
    if n < 1e-6:
        return True
    for step in (reach * 0.5, reach):
        qx, qz = p.gx + dx / n * step, p.gz + dz / n * step
        hit = terrain.floor_at(qx, qz, p.gy)
        if hit is None or hit[0] < p.gy - BACK_MAX_DROP:
            return False
    return True


def safe_heading(terrain, p, dx: float, dz: float, reach: float = 1.2):
    """If (dx, dz) has floor, use it; otherwise try turning ±30°/±60°. If none, None (stop).
    Also used when heading straight for a path point — after being pushed off the path in a fight, the straight line to the path point may cross a cliff
    (measured: in the merchant run, fell 22 m twice at the same spot (-21.9, 12.6))."""
    if ground_ahead(terrain, p, dx, dz, reach):
        return dx, dz
    base = math.atan2(dx, dz)
    for deg in (30, -30, 60, -60):
        a = base + math.radians(deg)
        if ground_ahead(terrain, p, math.sin(a), math.cos(a), reach):
            return math.sin(a), math.cos(a)
    return None


def safe_back(terrain, p, dx: float, dz: float):
    """Pick a direction to back away that fits the terrain — None (stay put) if there is none.

    Retreat in backoff/probe just pushes away from the enemy, so it goes even with a cliff behind (user: fell to death while backing up).
    Check the floor BACK_PROBE ahead on the NavMesh; if blocked, rotate the direction in 30° steps to find a passable side."""
    if terrain is None:
        return dx, dz
    n = math.hypot(dx, dz)
    if n < 1e-6:
        return None
    base = math.atan2(dx, dz)
    for deg in (0, 30, -30, 60, -60, 90, -90, 120, -120):
        a = base + math.radians(deg)
        qx, qz = p.gx + math.sin(a) * BACK_PROBE, p.gz + math.cos(a) * BACK_PROBE
        hit = terrain.floor_at(qx, qz, p.gy)
        if hit is not None and hit[0] > p.gy - BACK_MAX_DROP:
            return math.sin(a), math.cos(a)
    return None


STEEP = 0.45        # uphill/downhill slope (height/horizontal) — on sections steeper than this, step on the entrance precisely
TIGHT_TOL = 0.4


def trim_path(path: list, goal, within: float = 2.5) -> list:
    """Cut at the first point within `within` m of the goal and end with the goal. NavMesh paths often overshoot the goal and come back at the end;
    on the stairs above #5 (floor is only the single stairs axis), heading to that overshoot point (16° off the axis) snagged on the side and fell."""
    out = []
    for q in path:
        out.append(q)
        if math.dist(q, goal) < within:
            break
    if not out or math.dist(out[-1], goal) > 0.05:
        out.append(tuple(goal))
    return out


def path_tolerances(path: list, default: float = 1.0) -> list[float]:
    """Arrival check per waypoint. If the next segment is steep (stairs/ramp), step on that point precisely with TIGHT_TOL — calling 'arrived' at 1 m
    and cutting diagonally overshot the stairs entrance, went to the lower level beside it and got blocked by the side (2/2); with 0.4 m: entrance 0.31 m, top 0.45 m.
    The last point also uses TIGHT_TOL."""
    tols = []
    for i, q in enumerate(path):
        if i + 1 >= len(path):
            tols.append(TIGHT_TOL)
            continue
        r = path[i + 1]
        h = math.dist((q[0], q[2]), (r[0], r[2]))
        steep = len(q) > 2 and h > 0.3 and abs(r[1] - q[1]) / h > STEEP
        tols.append(TIGHT_TOL if steep else default)
    return tols


def follow(tm, pad, path: list, terrain=None, mode_fn=None, on_tick=None, default_tol: float = 1.0,
           timeout_per: float = 12.0, stop_fn=None, log=lambda *a: None) -> str:
    """Follow a path (the caller does the trim). Each point is judged with path_tolerances. If stop_fn(snapshot) is true, 'stopped'.
    → 'arrived' | goto's failure value | 'stopped'. After 3 consecutive failures, that failure value."""
    tols = path_tolerances(path, default_tol)
    fails = 0
    # Keep one movement state (run B hold) for the whole path. Previously a new Mover per point pressed and released B —
    # with short gaps between points, a 'short B' = roll/backstep (jump if running) and it fell off ramps (2026-09-24 review)
    mover = Mover(pad)
    try:
        for q, tol in zip(path, tols):
            r = goto(tm, pad, tuple(q), tolerance=tol, timeout=timeout_per, log=log, terrain=terrain,
                     on_tick=on_tick, mode_fn=mode_fn, mover=mover)
            if r in ("dead", "retreat"):
                return r
            if stop_fn is not None:
                s = tm.snapshot(within=40.0)
                if s is not None and stop_fn(s):
                    return "stopped"
            if r != "arrived":
                fails += 1
                if fails >= 3:
                    return r
            else:
                fails = 0
        return "arrived"
    finally:
        mover.stop()


def goto(tm: telemetry.Telemetry, pad: control.Pad, target: tuple[float, float], tolerance: float = 1.5,
         timeout: float = 60.0, on_tick=None, log=print, sprint_always: bool = False, mode_fn=None,
         mover: "Mover | None" = None, engage_fn=None, abort_on_stuck: bool = False,
         terrain=None) -> str:
    """Returns: 'arrived' | 'timeout' | 'dead' | 'lost' | 'unreachable'.
    target is (x, z) or (x, y, z). With y given, 'unreachable' when close in 2D but the height difference exceeds UNREACHABLE_DY — pushing toward a point above from below a cliff
    (when going backwards through a drop section of an indoor path). mode_fn(snapshot) -> 'walk'|'sprint'|'guardjump'|'guard' is the movement mode each tick."""
    if len(target) == 3:
        tx, ty, tz = target
    else:
        (tx, tz), ty = target, None
    t_start = time.time()
    last_progress_t, last_progress_d = t_start, None
    escapes = 0
    boost_until = 0.0
    no_cam_since = None
    own_mover = mover is None             # a passed-in mover is stopped by the caller (keeps running for the whole path)
    mover = mover or Mover(pad)
    probe_t0 = time.time()
    probe_off = [False]      # if probe makes no progress, use normal walking for the rest of this goto
    try:
        while True:
            now = time.time()
            if now - t_start > timeout:
                return "timeout"
            s = tm.snapshot(within=30.0)
            if s is None or s.player.gx is None or s.cam_yaw is None:
                pad.neutral()
                time.sleep(0.1)
                if now - t_start > 15 and s is None:
                    return "lost"
                if s is not None and s.cam_yaw is None:   # if camadr dies, steering is impossible — don't stand waiting for the timeout
                    no_cam_since = no_cam_since or now
                    if now - no_cam_since > 5:
                        log("  카메라 yaw 없음 5 s — lost")
                        return "lost"
                continue
            no_cam_since = None
            p = s.player
            if p.hp <= 0:
                pad.neutral()
                return "dead"
            dx, dz = tx - p.gx, tz - p.gz
            dist = math.hypot(dx, dz)
            if on_tick:
                on_tick(s, dist)
            if dist <= tolerance and (ty is None or abs(p.gy - ty) <= ARRIVE_DY):
                pad.neutral()
                return "arrived"

            # stuck detection
            if last_progress_d is None or last_progress_d - dist >= STUCK_MIN_PROGRESS:
                last_progress_d, last_progress_t = dist, now
            elif now - last_progress_t > STUCK_WINDOW:
                if abort_on_stuck:          # stuck while retreating: don't sidestep (guard down) and get hit — turn around and block immediately
                    pad.neutral()
                    return "stuck"
                escapes += 1
                # stuck with the target far above/below = cliff/floor difference, not stairs — stairs are climbed without getting stuck, so judge only after being stuck
                if escapes >= 2 and ty is not None and p.gy is not None and abs(ty - p.gy) > UNREACHABLE_DY:
                    pad.neutral()
                    log(f"  막힘 + 높이 차 {ty - p.gy:+.1f} m — 못 가는 점")
                    return "unreachable"
                log(f"  stuck at {dist:.1f} m — escape #{escapes}")
                mover.set("walk")
                # layer-0 recovery: if standing off the NavMesh (pocket), return to a mesh point at the same height before back/side escapes
                if terrain is not None and hasattr(terrain, "on_mesh") and not terrain.on_mesh(p.gx, p.gy, p.gz):
                    nw = terrain.nearest_walkable(p.gx, p.gy, p.gz)
                    if nw is not None and math.hypot(nw[0] - p.gx, nw[2] - p.gz) > 0.4:
                        log(f"  메시 밖 — {nw[0]:.1f},{nw[2]:.1f} 로 복귀")
                        rx, ry = control.world_to_stick(nw[0] - p.gx, nw[2] - p.gz, s.cam_yaw, YAW_OFFSET, FLIP_X)
                        t_r = time.time()
                        while time.time() - t_r < 1.5:
                            pad.move(rx * 0.9, ry * 0.9)
                            s2 = tm.snapshot(within=5.0)
                            if s2 and s2.player.gx is not None and math.hypot(nw[0] - s2.player.gx, nw[2] - s2.player.gz) < 0.5:
                                break
                            time.sleep(0.05)
                        pad.move(0.0, 0.0)
                        last_progress_d, last_progress_t = None, time.time()
                        continue
                if env.GAME != "dsr":   # in DS1, A is interact, not jump (stops if an NPC dialog opens)
                    pad.jump()
                # check footing before escaping back/sideways too — sidestepping without a floor check fell to death on the narrow stairs above #5 (climb_test, 2026-09-23).
                # only to a side with floor; if neither side has floor, don't move and return 'stuck'
                yaw = math.atan2(dx, dz)
                first = 1.0 if escapes % 2 else -1.0
                side_dir = None
                for sd in (first, -first):
                    wx, wz = math.sin(yaw + sd * 1.2), math.cos(yaw + sd * 1.2)
                    if ground_ahead(terrain, p, wx, wz, reach=1.6):
                        side_dir = (wx, wz)
                        break
                if side_dir is None:
                    pad.neutral()
                    log("  막힘 — 양옆이 낭떠러지라 빠져나가지 않음")
                    return "stuck"
                # user 2026-09-24: "must back off enough, then go forward" — a 0.5 s (1.2 m) back-off got stuck at the same spot every time at the ledge under the ramp (-24.5,-48.3,26.0).
                # if there is floor behind, back off farther the more it gets stuck (0.9→1.3→1.7 s), turn slightly sideways, then re-approach running
                back_s = min(1.7, 0.9 + 0.4 * (escapes - 1))
                if ground_ahead(terrain, p, -dx, -dz, reach=3.0):
                    bx, by = control.world_to_stick(-dx, -dz, s.cam_yaw, YAW_OFFSET, FLIP_X)
                    pad.move(bx * 0.9, by * 0.9)
                    time.sleep(back_s)
                elif ground_ahead(terrain, p, -dx, -dz, reach=1.2):
                    bx, by = control.world_to_stick(-dx, -dz, s.cam_yaw, YAW_OFFSET, FLIP_X)
                    pad.move(bx * 0.8, by * 0.8)
                    time.sleep(0.5)
                ox, oy = control.world_to_stick(side_dir[0], side_dir[1], s.cam_yaw, YAW_OFFSET, FLIP_X)
                pad.move(ox * 0.9, oy * 0.9)          # turn toward the side with floor and re-approach
                time.sleep(0.4)
                boost_until = time.time() + 1.5       # re-approach running (a ledge can't be climbed walking but can be running)
                last_progress_d, last_progress_t = dist, time.time()
                if escapes >= 6:
                    pad.neutral()
                    return "timeout"
                continue

            mode = mode_fn(s) if mode_fn else ("sprint" if (sprint_always or dist > SPRINT_BEYOND) else "walk")
            if now < boost_until and mode in ("walk", "sprint"):
                mode = "sprint"                        # run to re-approach right after a stuck escape
            if mode == "retreat":
                pad.neutral()               # Guard wants retreat/flee — the path loop goes back
                return "retreat"
            if mode == "hold":
                # check footing before standing to fight — if next to a cliff, move first, then fight (user principle)
                fs, safe_dir = footing(terrain, p)
                if fs < FOOTING_MIN and safe_dir is not None:
                    sx, sy = control.world_to_stick(safe_dir[0], safe_dir[1], s.cam_yaw, YAW_OFFSET, FLIP_X)
                    pad.move(sx * CREEP_STICK, sy * CREEP_STICK)
                else:
                    pad.move(0.0, 0.0)      # enemy is close — guard in place instead of advancing (also resets stuck detection)
                mover.set("guard")
                last_progress_d, last_progress_t = dist, now
            elif mode == "circle":
                a = now * 2.5             # circle around near the spot (lure) — rotate the stick direction
                if ground_ahead(terrain, p, math.sin(a + s.cam_yaw), math.cos(a + s.cam_yaw)):
                    pad.move(math.sin(a) * 0.6, math.cos(a) * 0.6)
                else:
                    pad.move(0.0, 0.0)
                mover.set("guard")
                last_progress_d, last_progress_t = dist, now
            elif mode == "backoff" and engage_fn and engage_fn(s):
                # when stamina runs out the guard breaks — back away from the enemy to recover.
                # DS1 barely recovers stamina with the shield up, so lower the guard once far enough.
                ex, ez = engage_fn(s)
                dx2, dz2 = p.gx - ex, p.gz - ez
                far = math.hypot(dx2, dz2)
                safe = safe_back(terrain, p, dx2, dz2)
                if safe is None:
                    pad.move(0.0, 0.0)          # cliff behind — don't back off, hold ground
                else:
                    sx, sy = control.world_to_stick(safe[0], safe[1], s.cam_yaw, YAW_OFFSET, FLIP_X)
                    pad.move(sx * CREEP_STICK, sy * CREEP_STICK)
                mover.set("guard" if far < 4.0 else "walk")
                last_progress_d, last_progress_t = dist, now
            elif mode == "probe" and not probe_off[0]:
                # user principle: near dangerous spots, advance only ~1 m net by going forward and back.
                # walking straight in wakes sleeping enemies all at once and leaves no distance to flee. Guard stays up throughout.
                ph = (now - probe_t0) % (PROBE_FWD + PROBE_BACK + PROBE_HOLD)
                sx, sy = control.world_to_stick(dx, dz, s.cam_yaw, YAW_OFFSET, FLIP_X)
                if ph < PROBE_FWD:
                    pad.move(sx * CREEP_STICK, sy * CREEP_STICK)
                elif ph < PROBE_FWD + PROBE_BACK:
                    back = safe_back(terrain, p, -dx, -dz)
                    if back is None:
                        pad.move(0.0, 0.0)      # cliff behind — stop instead of backing off
                    else:
                        bx, by = control.world_to_stick(back[0], back[1], s.cam_yaw, YAW_OFFSET, FLIP_X)
                        pad.move(bx * CREEP_STICK, by * CREEP_STICK)
                else:
                    pad.move(0.0, 0.0)
                mover.set("guard")
                # deliberately slow, so **relax** stuck detection but don't turn it off.
                # with it off, it shuttled 0.4 m forever in front of an unclimbable ledge (user: "spinning around in the same place").
                if dist < last_progress_d - 0.3:
                    last_progress_d, last_progress_t = dist, now
                elif now - last_progress_t > STUCK_WINDOW * 3:
                    log(f"  probe 로 전진 못 함 ({dist:.1f} m) — 보통 걷기로 전환")
                    probe_off[0] = True
                    last_progress_d, last_progress_t = dist, now
            elif mode == "creep":
                h = safe_heading(terrain, p, dx, dz)
                if h is None:
                    pad.move(0.0, 0.0)
                else:
                    sx, sy = control.world_to_stick(h[0], h[1], s.cam_yaw, YAW_OFFSET, FLIP_X)
                    pad.move(sx * CREEP_STICK, sy * CREEP_STICK)   # slow when multiple enemies are visible — so as not to aggro them all at once (user principle)
                mover.set("guard")
            elif mode == "face" and engage_fn and engage_fn(s):
                ex, ez = engage_fn(s)       # face that enemy in place (without lock-on)
                off = 0.0
                if p.heading is not None:
                    off = (math.atan2(ex - p.gx, ez - p.gz) - (p.heading + math.pi) + math.pi) % (2 * math.pi) - math.pi
                reach = min(1.2, max(0.4, math.hypot(ex - p.gx, ez - p.gz) - 0.3))   # there is floor up to where the enemy stands
                if abs(off) > FACE_TOL and ground_ahead(terrain, p, ex - p.gx, ez - p.gz, reach):
                    sx, sy = control.world_to_stick(ex - p.gx, ez - p.gz, s.cam_yaw, YAW_OFFSET, FLIP_X)
                    pad.move(sx * FACE_STICK, sy * FACE_STICK)
                else:
                    pad.move(0.0, 0.0)
                mover.set("guard")
                last_progress_d, last_progress_t = dist, now
            elif mode == "engage" and engage_fn and engage_fn(s):
                ex, ez = engage_fn(s)       # approach the enemy (guard up, walking — don't rush in, make it come)
                # check distance only up to the enemy — fixed at 1.2 m it looked **past** an enemy 0.9 m ahead (off the ramp), got blocked,
                # couldn't turn around either, and repeated "turning around" over a thousand times (merchant run, measured)
                reach = min(1.2, max(0.4, math.hypot(ex - p.gx, ez - p.gz) - 0.3))
                if ground_ahead(terrain, p, ex - p.gx, ez - p.gz, reach):
                    sx, sy = control.world_to_stick(ex - p.gx, ez - p.gz, s.cam_yaw, YAW_OFFSET, FLIP_X)
                    pad.move(sx * ENGAGE_STICK, sy * ENGAGE_STICK)
                else:
                    pad.move(0.0, 0.0)      # that way is a cliff — let the enemy come
                mover.set("guard")
                last_progress_d, last_progress_t = dist, now
            else:
                h = safe_heading(terrain, p, dx, dz)
                if h is None:
                    pad.move(0.0, 0.0)          # no floor in any direction — stand and leave it to stuck handling
                else:
                    sx, sy = control.world_to_stick(h[0], h[1], s.cam_yaw, YAW_OFFSET, FLIP_X)
                    pad.move(sx, sy)
                mover.set(mode)
            pad.release_due()        # release scheduled buttons (tap doesn't sleep, so handle it here)
            time.sleep(0.02)         # snapshot dropped to 4 ms, so the tick can run tighter
    finally:
        if own_mover:
            mover.stop()
        else:
            pad.move(0.0, 0.0)


if __name__ == "__main__":
    # test: go to a point 8 m ahead in the camera direction, then return to the start
    tm = telemetry.Telemetry()
    pad = control.Pad()
    s = tm.snapshot()
    p = s.player
    start = (p.gx, p.gz)
    ahead = (p.gx + 8 * math.sin(s.cam_yaw), p.gz + 8 * math.cos(s.cam_yaw))
    print(f"start={start[0]:.1f},{start[1]:.1f} → ahead={ahead[0]:.1f},{ahead[1]:.1f}")
    r = goto(tm, pad, ahead, on_tick=lambda s, d: None)
    print("leg 1:", r, "pos=", round(tm.snapshot().player.gx, 1), round(tm.snapshot().player.gz, 1))
    time.sleep(0.5)
    r = goto(tm, pad, start)
    print("leg 2:", r, "pos=", round(tm.snapshot().player.gx, 1), round(tm.snapshot().player.gz, 1))
