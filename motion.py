"""Movement model — how the character moves for a stick input (ROADMAP 6-a layer 2). No game.

  python motion.py fit                         fit on data/samples/observe_*.jsonl (human demos), leave-one-file-out check
  python motion.py fit data/radar/x.jsonl --slot 1    the bot's own pad in a radar recording (the bot is slot 1)

The walk harness's layer 2 runs nav.goto against this instead of the game. Model (measured on the human demos first:
the character moves in the stick's world direction — median 0.7° off — and faces the same way, heading + π):
  target direction  cam_yaw + atan2(lx, ly)                              (control.world_to_stick inverted)
  target speed      stick < dead → 0 · < walk_hi → v_walk · else v_jog · B held → v_run
  facing            turns toward the target direction at ≤ turn rad/s
  speed             first-order toward the target speed (tau_up / tau_down), moving along the facing
Walls and floors aren't here — the NavMesh comes with layer 2's world (data from [win]).
Only frames with no lock-on, plain anim (-1) and no gap are used: locked-on movement strafes, attacks/rolls move by
animation.
"""
from __future__ import annotations

import argparse
import glob
import math
import sys
from dataclasses import asdict, dataclass, replace
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
PAD_MAX = 32767.0
BTN_B = 0x2000           # XInput B — held = run (DSR)
DT = 1.0 / 60.0          # integration step
SEG_GAP_S = 0.25         # frames farther apart than this split a segment
SEG_JUMP_MPS = 12.0      # faster than this between frames = a teleport (quit-out, warp) — split


@dataclass
class Params:
    dead: float = 0.4        # stick below this doesn't move (nav.CREEP_STICK note: guard up, < 0.4 = stop)
    walk_hi: float = 0.7     # 0.4 ~ 0.7 = walk (same note)
    v_walk: float = 1.64     # m/s (same note, measured)
    v_jog: float = 3.27      # m/s full stick — fitted below
    v_run: float = 3.98      # m/s B held
    turn: float = 10.0       # rad/s max facing turn rate
    tau_up: float = 0.15     # s speed-up time constant
    tau_down: float = 0.10   # s slow-down time constant


@dataclass
class State:
    x: float
    z: float
    face: float              # facing = movement direction, world angle atan2(dx, dz) (= game heading + π)
    v: float


def wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def target(p: Params, lx: float, ly: float, cam_yaw: float, btn: int) -> tuple[float | None, float]:
    """→ (world direction or None, target speed) for a stick in [-1, 1]."""
    mag = min(1.0, math.hypot(lx, ly))
    if mag < p.dead:
        return None, 0.0
    d = cam_yaw + math.atan2(lx, ly)
    if btn & BTN_B and mag >= p.walk_hi:
        return d, p.v_run
    return d, (p.v_walk if mag < p.walk_hi else p.v_jog)


def step(p: Params, s: State, lx: float, ly: float, cam_yaw: float, btn: int, dt: float = DT) -> State:
    d, vt = target(p, lx, ly, cam_yaw, btn)
    face = s.face
    if d is not None:
        e = wrap(d - face)
        face = wrap(face + max(-p.turn * dt, min(p.turn * dt, e)))
    tau = p.tau_up if vt > s.v else p.tau_down
    v = vt + (s.v - vt) * math.exp(-dt / max(tau, 1e-3))
    return State(s.x + math.sin(face) * v * dt, s.z + math.cos(face) * v * dt, face, v)


# ── data: segments of free movement from radar / observe recordings ────────────────────────────────────────────

def segments(msgs: list[dict], slot: int | None = None) -> list[dict]:
    """[{frames: [(t, x, z, face, cam_yaw)], pad: [(t, lx, ly, btn)]}] — runs of snapshots with no lock-on, plain anim
    and no gap/teleport, with the pad states (slot = XInput slot, None = any) that were live during them."""
    pads = [(m["rt"], (m.get("lx") or 0) / PAD_MAX, (m.get("ly") or 0) / PAD_MAX, m.get("btn") or 0)
            for m in msgs if m.get("type") == "pad" and (slot is None or m.get("i") == slot)]
    snaps = [m for m in msgs if m.get("type") == "snap" and m.get("player") and m.get("cam_yaw") is not None]
    out, cur = [], []
    for m in snaps:
        pl = m["player"]
        if not (pl.get("anim") in (-1, None) and "target" not in m and pl.get("heading") is not None):
            if cur:
                out.append(cur)
            cur = []
            continue
        if cur:
            t0, x0, z0 = cur[-1][0], cur[-1][1], cur[-1][2]
            dt = m["rt"] - t0
            if dt <= 0 or dt > SEG_GAP_S or math.hypot(pl["x"] - x0, pl["z"] - z0) / dt > SEG_JUMP_MPS:
                out.append(cur)                        # gap / teleport: this frame starts a new segment
                cur = []
        cur.append((m["rt"], pl["x"], pl["z"], wrap(pl["heading"] + math.pi), m["cam_yaw"]))
    if cur:
        out.append(cur)
    res = []
    for fr in out:
        if len(fr) < 3:
            continue
        t0, t1 = fr[0][0], fr[-1][0]
        before = [p for p in pads if p[0] <= t0]
        pad = ([before[-1]] if before else []) + [p for p in pads if t0 < p[0] <= t1]
        if pad:
            res.append({"frames": fr, "pad": pad})
    return res


def load(files: list[str], slot: int | None = None) -> dict[str, list[dict]]:
    import radar_record
    return {Path(f).name: segments(radar_record.load(f), slot) for f in files}


def _pad_at(pad: list, t: float, j: int) -> tuple[int, tuple]:
    while j + 1 < len(pad) and pad[j + 1][0] <= t:
        j += 1
    return j, pad[j]


def rollout(p: Params, seg: dict, i: int, horizon: float) -> tuple[float, float] | None:
    """Start at frame i (position, facing, speed from the frame before), play the recorded pad for `horizon` s
    → predicted (x, z) at the frame nearest t_i + horizon, or None if the segment ends first."""
    fr, pad = seg["frames"], seg["pad"]
    if i < 1:
        return None
    t_end = fr[i][0] + horizon
    k = next((k for k in range(i + 1, len(fr)) if fr[k][0] >= t_end - 0.05), None)
    if k is None or pad[0][0] > fr[i][0]:
        return None
    a, b = fr[i - 1], fr[i]
    v0 = math.hypot(b[1] - a[1], b[2] - a[2]) / max(1e-3, b[0] - a[0])
    s = State(b[1], b[2], b[3], v0)
    t, j, f = b[0], 0, i
    while t < fr[k][0] - 1e-9:
        j, (_, lx, ly, btn) = _pad_at(pad, t, j)
        while f + 1 <= k and fr[f + 1][0] <= t:
            f += 1
        dt = min(DT, fr[k][0] - t)
        s = step(p, s, lx, ly, fr[f][4], btn, dt)
        t += dt
    return s.x, s.z


def errors(p: Params | None, segs: list[dict], horizon: float, every: int = 2) -> list[float]:
    """Position error (m) at `horizon` s, from every `every`-th frame. p=None → baseline 'keeps its velocity';
    p='stay' → baseline 'stands still'."""
    out = []
    for seg in segs:
        fr = seg["frames"]
        for i in range(1, len(fr), every):
            k = next((k for k in range(i + 1, len(fr)) if fr[k][0] >= fr[i][0] + horizon - 0.05), None)
            if k is None:
                continue
            if p is None:
                a, b = fr[i - 1], fr[i]
                h = fr[k][0] - b[0]
                dt = max(1e-3, b[0] - a[0])
                q = (b[1] + (b[1] - a[1]) / dt * h, b[2] + (b[2] - a[2]) / dt * h)
            elif p == "stay":
                q = (fr[i][1], fr[i][2])
            else:
                q = rollout(p, seg, i, horizon)
                if q is None:
                    continue
            out.append(math.hypot(q[0] - fr[k][1], q[1] - fr[k][2]))
    return out


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else math.inf


FIT_KEYS = {"v_jog": (2.5, 4.0), "v_run": (3.0, 5.5), "turn": (2.0, 30.0), "tau_up": (0.02, 0.8), "tau_down": (0.02, 0.8)}
# turn: 10 Hz frames can't resolve turns faster than ~10 rad/s — the human demos fit to the upper bound (turning looks
# instant at 10 Hz). The bot's 10 Hz radar recording + its stick will say more; nav.FACE_STICK's 84° in 0.6 s (0.45 stick)
# is the only slow-turn measurement so far.


def fit(segs: list[dict], p0: Params | None = None, horizon: float = 0.5, rounds: int = 3) -> Params:
    """Coordinate search over FIT_KEYS minimising the mean position error at `horizon`. dead / walk band stay at the
    measured values — the demos hold few half-stick samples."""
    p = p0 or Params()
    best = _mean(errors(p, segs, horizon))
    for _ in range(rounds):
        for key, (lo, hi) in FIT_KEYS.items():
            for frac in (0.5, 0.25, 0.1):
                cur = getattr(p, key)
                span = (hi - lo) * frac
                for v in (cur - span, cur + span):
                    v = min(hi, max(lo, v))
                    q = replace(p, **{key: v})
                    e = _mean(errors(q, segs, horizon))
                    if e < best - 1e-6:
                        p, best = q, e
    return p


def _q(xs: list[float], f: float) -> float:
    xs = sorted(xs)
    return xs[int(f * (len(xs) - 1))] if xs else math.nan


def cross_check(data: dict[str, list[dict]], horizons=(0.5, 1.0)) -> list[dict]:
    """Leave one file out: fit on the rest, error on it. → rows per (file, horizon) for model / keep velocity / stand."""
    rows = []
    names = [n for n, s in data.items() if s]
    for n in names:
        train = [s for m in names if m != n for s in data[m]]
        p = fit(train) if train else Params()
        for h in horizons:
            rows.append({"file": n, "h": h, "model": errors(p, data[n], h), "keep_v": errors(None, data[n], h),
                         "stay": errors("stay", data[n], h), "params": p})
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=["fit"])
    ap.add_argument("files", nargs="*")
    ap.add_argument("--slot", type=int, default=None, help="XInput slot of the pad to use (bot = 1 in radar recordings)")
    a = ap.parse_args()
    files = a.files or sorted(glob.glob(str(ROOT / "data" / "samples" / "observe_*.jsonl")))
    data = load(files, a.slot)
    n_seg = sum(len(s) for s in data.values())
    n_fr = sum(len(x["frames"]) for s in data.values() for x in s)
    print(f"{len(files)} files, {n_seg} free-movement segments, {n_fr} frames ({n_fr / 10:.0f} s at 10 Hz)")
    allsegs = [s for v in data.values() for s in v]
    p = fit(allsegs)
    print("fitted on all:", {k: round(v, 3) for k, v in asdict(p).items()})
    print(f"\nleave one file out — position error (m) p50 / p90:")
    print(f"  {'held-out file':<44} {'h':>4} | {'model':>11} | {'keep velocity':>13} | {'stand still':>11}")
    for r in cross_check(data):
        f = lambda xs: f"{_q(xs, .5):5.2f}/{_q(xs, .9):5.2f}"
        print(f"  {r['file'][:44]:<44} {r['h']:4.1f} | {f(r['model']):>11} | {f(r['keep_v']):>13} | {f(r['stay']):>11}"
              f"  (n {len(r['model'])})")


if __name__ == "__main__":
    main()
