"""motion.py offline test — stick → movement model: target direction/speed, integration, segments from recordings,
rollout, and that fitting recovers known parameters from synthetic data. No game.

  python tests/motion_test.py
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import math
import random
import sys
from dataclasses import replace
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import control
import motion as M

fails = 0


def check(name, cond):
    global fails
    print(("  ok   " if cond else "  FAIL ") + name)
    fails += 0 if cond else 1


P = M.Params()

print("target direction / speed")
for cam in (0.0, 1.0, -2.5):
    for want in (0.3, 2.0, -1.2):
        sx, sy = control.world_to_stick(math.sin(want), math.cos(want), cam, 0.0, False)
        d, v = M.target(P, sx, sy, cam, 0)
        ok = d is not None and abs(M.wrap(d - want)) < 1e-9 and v == P.v_jog
        if not ok:
            break
check("inverse of control.world_to_stick: full stick toward a world direction → that direction, v_jog", ok)
check("stick below dead → no direction, 0 m/s", M.target(P, 0.3, 0.0, 0.0, 0) == (None, 0.0))
check("half stick → walk", M.target(P, 0.0, 0.55, 0.0, 0)[1] == P.v_walk)
check("full stick + B → run", M.target(P, 0.0, 1.0, 0.0, M.BTN_B)[1] == P.v_run)
check("B with half stick → still walk (can't run slowly)", M.target(P, 0.0, 0.55, 0.0, M.BTN_B)[1] == P.v_walk)

print("step")
P = replace(M.Params(), tau_up=0.15)                   # the step checks below assume a quick speed-up
s = M.State(0.0, 0.0, 0.0, 0.0)
for _ in range(120):                                   # 2 s full stick straight ahead (+z, cam 0)
    s = M.step(P, s, 0.0, 1.0, 0.0, 0)
check("2 s full stick from rest → ~v_jog, moved ~2·v_jog minus the ramp", abs(s.v - P.v_jog) < 0.01
      and 2 * P.v_jog - 1.0 < s.z < 2 * P.v_jog and abs(s.x) < 1e-9)
s2 = s
for _ in range(6):                                     # 0.1 s full stick to +x: turns ≤ turn·0.1 rad
    s2 = M.step(P, s2, 1.0, 0.0, 0.0, 0)
check("turning is rate-limited (≤ turn · dt per step)", abs(s2.face - min(math.pi / 2, P.turn * 0.1)) < 1e-6)
s3 = s
for _ in range(60):
    s3 = M.step(P, s3, 0.0, 0.0, 0.0, 0)
check("stick released → slows to ~0 within 1 s", s3.v < 0.01)

print("segments from recordings")


def snap(t, x, z, hd, anim=-1, lock=False, cam=0.0):
    m = {"rt": t, "type": "snap", "player": {"x": x, "y": 0.0, "z": z, "heading": hd, "anim": anim}, "cam_yaw": cam}
    if lock:
        m["target"] = 123
    return m


msgs = [{"rt": 0.0, "type": "pad", "i": 0, "lx": 0, "ly": 32767, "btn": 0}]
msgs += [snap(0.1 * k, 0.0, 0.3 * k, math.pi) for k in range(10)]            # 1 s free
msgs += [snap(1.0, 0.0, 3.0, math.pi, anim=303000)]                          # attack splits
msgs += [snap(1.1 + 0.1 * k, 0.0, 3.3 + 0.3 * k, math.pi) for k in range(5)]
msgs += [snap(1.6, 0.0, 4.8, math.pi, lock=True)]                            # lock-on splits
msgs += [snap(1.7 + 0.1 * k, 0.0, 5.1 + 0.3 * k, math.pi) for k in range(3)]
msgs += [snap(2.0 + 0.1 * k, 50.0, 5.1 + 0.3 * k, math.pi) for k in range(3)]  # teleport splits
seg = M.segments(msgs)
check("anim / lock-on / teleport split the run: 4 segments of 10, 5, 3, 3", [len(x["frames"]) for x in seg] == [10, 5, 3, 3])
check("facing = heading + π (heading π → facing 0 = +z)", abs(seg[0]["frames"][0][3]) < 1e-9)
check("pad state before the segment is carried in", seg[1]["pad"][0][0] == 0.0)
check("slot filter: pad from slot 1 only → no pad, no segments", M.segments(msgs, slot=1) == [])

print("rollout and fit on synthetic data")
TRUE = replace(P, v_jog=3.3, v_run=4.4, turn=6.0, tau_up=0.3, tau_down=0.12)
rng = random.Random(4)


def synth(p, secs=40.0, seed=0) -> dict:
    """The model itself playing random sticks (held 0.3~1.2 s), sampled at 10 Hz like a recording."""
    r = random.Random(seed)
    s, t, frames, pad, nxt = M.State(0.0, 0.0, 0.0, 0.0), 0.0, [], [], 0.0
    lx = ly = 0.0
    btn = 0
    k = 0
    while t < secs:
        if t >= nxt:
            a, mag = r.uniform(-math.pi, math.pi), r.choice((0.0, 1.0, 1.0, 0.55))
            lx, ly, btn = math.sin(a) * mag, math.cos(a) * mag, r.choice((0, 0, M.BTN_B))
            pad.append((t, lx, ly, btn))
            nxt = t + r.uniform(0.3, 1.2)
        if abs(t - k * 0.1) < 1e-6 or t > k * 0.1:
            frames.append((round(k * 0.1, 6), s.x, s.z, s.face, 0.0))
            k += 1
        s = M.step(p, s, lx, ly, 0.0, btn, M.DT)
        t = round(t + M.DT, 9)
    return {"frames": frames, "pad": pad}


segs = [synth(TRUE, seed=i) for i in range(3)]
e_true = M.errors(TRUE, segs, 1.0)
check("rollout with the true params ≈ exact (p90 < 0.25 m at 1 s — start speed comes from 10 Hz frames)",
      M._q(e_true, 0.9) < 0.25)
e_def = M.errors(P, segs, 1.0)
fit = M.fit(segs, p0=replace(M.Params(), tau_up=0.15), horizon=1.0, rounds=2)
e_fit = M.errors(fit, segs, 1.0)
check("fit brings the 1 s error down from the defaults", M._mean(e_fit) < M._mean(e_def) * 0.7)
check("fit recovers v_jog / v_run within 0.25 m/s", abs(fit.v_jog - TRUE.v_jog) < 0.25 and abs(fit.v_run - TRUE.v_run) < 0.25)
check("model beats 'keep velocity' at 1 s on synthetic data", M._mean(e_fit) < M._mean(M.errors(None, segs, 1.0)))

print("committed human demos (data/samples/observe_*.jsonl)")
files = sorted(str(p) for p in (Path(__file__).resolve().parent.parent / "data" / "samples").glob("observe_*.jsonl"))
data = M.load(files)
segs = [s for v in data.values() for s in v]
check("demos give free-movement segments", len(segs) >= 5 and sum(len(s["frames"]) for s in segs) > 500)
e_m, e_v = M.errors(P, segs, 1.0), M.errors(None, segs, 1.0)
check("default params already beat 'keep velocity' at 1 s on the demos (median)", M._q(e_m, 0.5) < M._q(e_v, 0.5))

print("bot walk cuts from [win] (data/samples/radar_walk_*.jsonl)")
cuts = M.load_walk_cuts(str(Path(__file__).resolve().parent.parent / "data" / "samples" / "radar_walk_storeroom.jsonl"))
check("6 walks, each read with its own bot_slot, all give segments", len(cuts) == 6 and all(w["segs"] for w in cuts)
      and {w["slot"] for w in cuts} <= {0, 1})
bot = M.load([str(Path(__file__).resolve().parent.parent / "data" / "samples" / "radar_walk_storeroom.jsonl")])
segs_b = next(iter(bot.values()))
check("load() spots a walk-cut file and uses the cuts", len(segs_b) == sum(len(w["segs"]) for w in cuts))
check("on the bot's walks the default model beats 'keep velocity' at 1 s (median)",
      M._q(M.errors(P, segs_b, 1.0), 0.5) < M._q(M.errors(None, segs_b, 1.0), 0.5))

print("world: floor, walls, drops, off-mesh fill")


class FakeMesh:
    """Corridor floor y 0 for x 0~10, z 0~2; a floor 5 m lower beside it (z < 0); nothing for z > 2 (a wall) or x > 10
    (no NavMesh — like the secret passage)."""
    map_id = "fake"

    def floor_tri_at(self, x, z, y):
        if 0 <= x <= 10 and 0 <= z <= 2:
            return (0.0, 0, 1)
        if 0 <= x <= 10 and -6 <= z < 0:
            return (-5.0, 0, 2)
        return None

    def on_mesh(self, x, y, z):
        return self.floor_tri_at(x, z, y) is not None


W = M.World(FakeMesh())
s0 = M.State(5.0, 1.0, 0.0, 3.0, 0.0)
moved = W.move(s0, M.State(5.3, 1.0, 0.0, 3.0, 0.0))
check("along the corridor: goes, height stays", (moved.x, moved.z, moved.y) == (5.3, 1.0, 0.0))
nearwall = M.State(5.0, 1.95, 0.0, 3.0, 0.0)
slid = W.move(nearwall, M.State(5.2, 2.15, 0.0, 3.0, 0.0))                 # diagonal into the z = 2 wall
check("diagonal into a wall: slides along it (x grows, stays inside)", slid.x > 5.0 and slid.z <= 2.0)
stuck = W.move(nearwall, M.State(5.0, 2.25, 0.0, 3.0, 0.0))                # straight into it
check("straight into a wall: stays put, counted as blocked", (stuck.x, stuck.z) == (5.0, 1.95) and W.blocked == 1)
fell = W.move(M.State(5.0, 0.05, 0.0, 3.0, 0.0), M.State(5.0, -0.25, 0.0, 3.0, 0.0))
check("off the low edge: falls to the floor 5 m below, counted", fell.y == -5.0 and W.falls == 1)
Wf = M.World(FakeMesh(), fill=[(10.0 + 0.25 * k, 0.1, 1.0, "other walk") for k in range(9)])
s1 = M.State(9.9, 1.0, 0.0, 3.0, 0.0)
check("off the mesh where another walk went (fill): goes, at the recorded height",
      Wf.move(s1, M.State(10.2, 1.0, 0.0, 3.0, 0.0)).x == 10.2 and Wf.move(s1, M.State(10.2, 1.0, 0.0, 3.0, 0.0)).y == 0.1)
check("… but not on the walk's own recorded positions (no peeking)",
      Wf.move(s1, M.State(10.2, 1.0, 0.0, 3.0, 0.0), "other walk").x == 9.9)
seg = {"frames": [(0.1 * k, 5.0, 1.0 + 0.0 * k, math.pi / 2, 0.0, 0.0) for k in range(12)],
       "pad": [(0.0, 0.0, 1.0, 0)]}                                          # stick toward +z from x 5: into the wall
free = M.rollout(P, seg, 1, 1.0, None)
walled = M.rollout(P, seg, 1, 1.0, M.World(FakeMesh()))
check("rollout with a world stops at the wall (z ≤ 2); without one it walks through", walled[1] <= 2.0 < free[1])

print(f"\n{'all ok' if not fails else f'{fails} FAILED'}")
sys.exit(1 if fails else 0)
