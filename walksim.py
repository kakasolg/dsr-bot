"""Walk harness layer 2 (closed loop) — the bot's own nav.goto steering a simulated character. No game. (ROADMAP 6-a)

  python walksim.py entrance            passage entrance: the route before / after the point-70 fix (1-f), N runs each
  python walksim.py entrance -n 40

nav.goto runs unchanged: it reads snapshots from SimTm and pushes SimPad; its clock (nav.time) is the simulation's, so
time.sleep advances the simulated character instead of waiting. The character is motion.Params / motion.step (stick →
movement, fitted on the bot's walks) inside a motion.World (NavMesh floor and walls + recorded positions where the
NavMesh has none). Each run starts with a small random offset / facing / camera yaw (seeded) so one route gives a spread.
Measured per run: arrived or not, time, stalls (≥ STALL_S below STALL_V — track_report's definition) and where.
"""
from __future__ import annotations

import argparse
import glob
import math
import random
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import motion
import nav
import telemetry
import walkgeom as G

ROOT = Path(__file__).resolve().parent
STALL_V, STALL_S = 0.3, 1.0          # same as track_report
REC_HZ = 10.0


class Sim:
    """The simulated character + clock. sleep(dt) integrates the motion model with the pad as it is."""

    def __init__(self, world: motion.World, params: motion.Params, pos: tuple, face: float, cam_yaw: float):
        self.world, self.p = world, params
        self.s = motion.State(pos[0], pos[2], face, 0.0, pos[1])
        self.cam_yaw = cam_yaw
        self.t = 0.0
        self.lx = self.ly = 0.0
        self.btn = 0
        self.track: list[tuple] = [(0.0, pos[0], pos[1], pos[2])]
        self._next_rec = 1.0 / REC_HZ

    def sleep(self, dt: float) -> None:
        end = self.t + max(0.0, dt)
        while self.t < end - 1e-9:
            h = min(motion.DT, end - self.t)
            s2 = motion.step(self.p, self.s, self.lx, self.ly, self.cam_yaw, self.btn, h)
            self.s = self.world.move(self.s, s2, None)
            self.t += h
            if self.t >= self._next_rec - 1e-9:
                self.track.append((self.t, self.s.x, self.s.y, self.s.z))
                self._next_rec += 1.0 / REC_HZ

    def snapshot(self) -> telemetry.Snapshot:
        s = self.s
        pl = telemetry.Chr(ptr=1, npc_param=0, team=1, hp=500, max_hp=500, x=s.x, y=s.y, z=s.z, sp=100, max_sp=100,
                           anim=-1, gx=s.x, gy=s.y, gz=s.z, heading=motion.wrap(s.face - math.pi))
        return telemetry.Snapshot(t=self.t, player=pl, chars=[], cam_yaw=self.cam_yaw)


class SimTm:
    def __init__(self, sim: Sim):
        self.sim = sim

    def snapshot(self, within: float = 30.0):
        return self.sim.snapshot()


class SimPad:
    """The bits of control.Pad that nav.goto / nav.Mover use."""
    B, LB = motion.BTN_B, 0x0100

    def __init__(self, sim: Sim):
        self.sim = sim

    def move(self, x: float, y: float) -> None:
        self.sim.lx, self.sim.ly = max(-1.0, min(1.0, x)), max(-1.0, min(1.0, y))

    def neutral(self) -> None:
        self.sim.lx = self.sim.ly = 0.0
        self.sim.btn = 0

    def sprint(self, on: bool) -> None:
        self.sim.btn = (self.sim.btn | self.B) if on else (self.sim.btn & ~self.B)

    def guard(self, on: bool) -> None:
        self.sim.btn = (self.sim.btn | self.LB) if on else (self.sim.btn & ~self.LB)

    def jump(self) -> None:
        pass

    def release_due(self) -> None:
        pass


@dataclass
class Run:
    result: str
    secs: float
    track: list
    stalls: list = field(default_factory=list)     # [(t, s, (x, y, z))]
    falls: int = 0
    blocked: int = 0
    points: list = field(default_factory=list)     # per path point: goto result


def stalls(track: list) -> list:
    out, start = [], None
    for a, b in zip(track, track[1:]):
        dt = b[0] - a[0]
        slow = dt > 0 and math.hypot(b[1] - a[1], b[3] - a[3]) / dt < STALL_V
        if slow and start is None:
            start = a
        if (not slow or b is track[-1]) and start is not None:
            end = b if slow else a
            if end[0] - start[0] >= STALL_S:
                out.append((round(start[0], 1), round(end[0] - start[0], 1), (start[1], start[2], start[3])))
            start = None
    return out


def walk(nm, world: motion.World, path: list, start: tuple, face: float, cam_yaw: float, tol: float = 0.8,
         params: motion.Params | None = None, timeout: float = 15.0, walk_mode: str = "walk") -> Run:
    """Walk `path` the way Field._walk drives nav.goto (WalkPlan tolerances for a recorded route: tol, no stair rule,
    corners tightened; terrain only when the point and we are on this NavMesh), with nav.goto's own stuck escapes."""
    sim = Sim(world, params or motion.Params(), start, face, cam_yaw)
    tm, pad = SimTm(sim), SimPad(sim)
    fake_time = types.SimpleNamespace(time=lambda: sim.t, sleep=sim.sleep)
    saved = nav.time
    nav.time = fake_time
    world.falls = world.blocked = 0
    tols = nav.path_tolerances(path, tol, steep=False)
    mover = nav.Mover(pad)
    res, fails, per = "arrived", 0, []
    try:
        for q, t in zip(path, tols):
            s = sim.snapshot().player
            f_q = nm.floor_at(q[0], q[2], q[1])
            f_p = nm.floor_at(s.x, s.z, s.y)
            terr = nm if (f_q is not None and abs(f_q[0] - q[1]) < 2.0 and f_p is not None and abs(f_p[0] - s.y) < 2.0) else None
            r = nav.goto(tm, pad, tuple(q), tolerance=t if terr is not None else max(t, 0.8), timeout=timeout,
                         log=lambda *a: None, terrain=terr, mover=mover, mode_fn=lambda _s: walk_mode)
            per.append(r)
            if r != "arrived":
                fails += 1
                if fails >= 3:
                    res = r
                    break
            else:
                fails = 0
        else:
            res = "arrived" if math.dist((sim.s.x, sim.s.z), (path[-1][0], path[-1][2])) < 1.5 else "missed_end"
    finally:
        mover.stop()
        nav.time = saved
    return Run(res, round(sim.t, 2), sim.track, stalls(sim.track), world.falls, world.blocked, per)


# ── the passage entrance (ROADMAP 1-f, 70th point) ─────────────────────────────────────────────────────────────

ENTRANCE = (-25.1, -33.7, 8.8)       # where every pre-fix run stalled 1.8–4.4 s (radar 2026-09-27, 15/15)


def entrance_paths(nm) -> dict:
    """Top of the Firelink stairs → 3 points into the passage: the route before the fix (point 70 dropped by _no_void,
    69 → a0 diagonal) and after it (_with_entry_corner: 70 + the human's way in)."""
    from souls import missions as MS
    MS._VOID_NM = nm
    top, route, _ = MS._route()
    after = MS._with_entry_corner(route)
    cut = lambda pts: pts[:next(i for i, q in enumerate(pts) if math.dist(q, MS.PASSAGE_A0) < 0.3) + 4]
    return {"before": [tuple(q) for q in cut(route)], "after": [tuple(q) for q in cut(after)]}


def firelink_world(nms: dict | None = None) -> tuple:
    nms = nms or motion.load_navmeshes()
    nm = nms["m10_02_00_00"]
    files = sorted(glob.glob(str(ROOT / "data" / "samples" / "radar_walk_*.jsonl")))
    data = motion.load(files)
    # every recorded bot position is walkable (id "rec": the simulated walk itself has id None, so none are left out)
    fill = [(fr[1], fr[5], fr[2], "rec") for segs in data.values() for sg in segs for fr in sg["frames"] if len(fr) > 5]
    return nm, motion.World(nm, fill)


def entrance_trial(n: int = 20, seed: int = 0) -> dict:
    """n runs of each route from the top of the stairs (start ± 0.3 m, facing ± 30°, camera yaw anywhere)."""
    nm, world = firelink_world()
    paths = entrance_paths(nm)
    rng = random.Random(seed)
    out = {k: [] for k in paths}
    for _ in range(n):
        dx, dz = rng.uniform(-0.3, 0.3), rng.uniform(-0.3, 0.3)
        cam = rng.uniform(-math.pi, math.pi)
        jitter = math.radians(rng.uniform(-30, 30))
        for k, path in paths.items():
            a, b = path[0], path[1]
            face = math.atan2(b[0] - a[0], b[2] - a[2]) + jitter
            start = (a[0] + dx, a[1], a[2] + dz)
            out[k].append(walk(nm, world, path[1:], start, face, cam))
    return {"paths": paths, "runs": out}


def at_entrance(run: Run, r: float = 2.5) -> list:
    return [st for st in run.stalls if math.hypot(st[2][0] - ENTRANCE[0], st[2][2] - ENTRANCE[2]) <= r]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("what", choices=["entrance"])
    ap.add_argument("-n", type=int, default=20)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    res = entrance_trial(a.n, a.seed)
    print(f"passage entrance, {a.n} runs per route (game, radar 2026-09-27/28: before 15/15 runs stalled 1.8–4.4 s at "
          f"{ENTRANCE}, after 0)")
    for k, runs in res["runs"].items():
        ent = [at_entrance(r) for r in runs]
        secs = sorted(r.secs for r in runs)
        stall_s = [sum(s[1] for s in e) for e in ent]
        print(f"  {k:6} {len(res['paths'][k]):2d} pts | arrived {sum(r.result == 'arrived' for r in runs)}/{len(runs)} | "
              f"time p50 {secs[len(secs) // 2]:.1f} s max {secs[-1]:.1f} s | entrance stall in {sum(1 for e in ent if e)}/{len(runs)} "
              f"runs, {min(stall_s):.1f}–{max(stall_s):.1f} s | blocked steps p50 {sorted(r.blocked for r in runs)[len(runs) // 2]} "
              f"| falls {sum(r.falls for r in runs)} | misses {sum(sum(x != 'arrived' for x in r.points) for r in runs)}")


if __name__ == "__main__":
    main()
