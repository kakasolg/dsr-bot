"""Movement model — how the character moves for a stick input (ROADMAP 6-a layer 2). No game.

  python motion.py fit                         fit on data/samples/observe_*.jsonl (human demos), leave-one-file-out check
  python motion.py fit data/samples/radar_walk_*.jsonl   the bot's own walks ([win] cuts: each walk carries its bot_slot)
  python motion.py walls                       the bot's walks with / without the world (NavMesh floor, walls, drops)
  python motion.py fit data/radar/x.jsonl --slot 1    a whole radar recording (bot pad slot 1 if a human pad was plugged in)

The walk harness's layer 2 runs nav.goto against this instead of the game. Model (measured on the human demos first:
the character moves in the stick's world direction — median 0.7° off — and faces the same way, heading + π):
  target direction  cam_yaw + atan2(lx, ly)                              (control.world_to_stick inverted)
  target speed      stick < dead → 0 · < walk_hi → v_walk · else v_jog · B held → v_run
  facing            turns toward the target direction at ≤ turn rad/s
  speed             first-order toward the target speed (tau_up / tau_down), moving along the facing
Walls and floors: World (NavMesh from [win]'s .npz export + recorded positions where the NavMesh has none).
Only frames with no lock-on, plain anim (-1) and no gap are used: locked-on movement strafes, attacks/rolls move by
animation.
"""
from __future__ import annotations

import argparse
import glob
import json
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
    v_jog: float = 3.42      # m/s full stick — fitted on the bot's walks with walls (2026-10-01; demos alone: 3.27~3.42)
    v_run: float = 3.98      # m/s B held — from the demos (the bot's B frames are stuck-escape pushes, not runs)
    turn: float = 10.0       # rad/s max facing turn rate
    tau_up: float = 0.215    # s speed-up — refit with the world (fill 0.35 m), 2026-10-01; the demos gave 0.23. (0.8 earlier
                             # was the fit making up for a passage the 1 m fill had widened)
    tau_down: float = 0.10   # s slow-down time constant


@dataclass
class State:
    x: float
    z: float
    face: float              # facing = movement direction, world angle atan2(dx, dz) (= game heading + π)
    v: float
    y: float = 0.0           # height — only the world (World.move) changes it


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
    return State(s.x + math.sin(face) * v * dt, s.z + math.cos(face) * v * dt, face, v, s.y)


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
        cur.append((m["rt"], pl["x"], pl["z"], wrap(pl["heading"] + math.pi), m["cam_yaw"], pl.get("y", 0.0)))
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


def load_walk_cuts(path: str) -> list[dict]:
    """[win]'s bot walk cuts (data/samples/radar_walk_*.jsonl, experiments/radar_walk_export.py): each walk is a
    {"type": "walk", src, tag, t0, t1, bot_slot} line followed by its snap / pad / say lines. Times are per source
    recording, and the bot's pad slot differs by recording (1 with a human pad plugged in, else 0) — so every walk is
    cut apart and read with its own bot_slot. → [{tag, src, slot, segs}]"""
    walks, cur = [], None
    for line in open(path, encoding="utf-8"):
        try:
            m = json.loads(line)
        except ValueError:
            continue
        if m.get("type") == "walk":
            cur = {"tag": m.get("tag"), "src": m.get("src"), "slot": m.get("bot_slot"), "msgs": []}
            walks.append(cur)
        elif cur is not None:
            cur["msgs"].append(m)
    out = []
    for k, w in enumerate(walks):
        wid = f"{Path(path).name}#{k}"
        segs = segments(sorted(w["msgs"], key=lambda m: m.get("rt", 0.0)), w["slot"])
        for sg in segs:
            sg["walk"] = wid                             # World leaves this walk's own positions out of its off-mesh fill
        out.append({"tag": w["tag"], "src": w["src"], "slot": w["slot"], "id": wid, "segs": segs})
    return out


def load(files: list[str], slot: int | None = None) -> dict[str, list[dict]]:
    """{file name: segments}. Walk-cut files (radar_walk_*) use each walk's bot_slot; others go through
    radar_record.load (radar recordings and observe_record.py demos) with `slot`."""
    import radar_record
    out = {}
    for f in files:
        with open(f, encoding="utf-8") as fh:
            first = fh.readline()
        if '"type": "walk"' in first or '"type":"walk"' in first:
            out[Path(f).name] = [s for w in load_walk_cuts(f) for s in w["segs"]]
        else:
            out[Path(f).name] = segments(radar_record.load(f), slot)
    return out


def _pad_at(pad: list, t: float, j: int) -> tuple[int, tuple]:
    while j + 1 < len(pad) and pad[j + 1][0] <= t:
        j += 1
    return j, pad[j]


def rollout(p: Params, seg: dict, i: int, horizon: float, world: "World | None" = None) -> tuple[float, float] | None:
    """Start at frame i (position, facing, speed from the frame before), play the recorded pad for `horizon` s
    → predicted (x, z) at the frame nearest t_i + horizon, or None if the segment ends first.
    With a world, every step goes through World.move (floor, walls, drops)."""
    fr, pad = seg["frames"], seg["pad"]
    if i < 1:
        return None
    t_end = fr[i][0] + horizon
    k = next((k for k in range(i + 1, len(fr)) if fr[k][0] >= t_end - 0.05), None)
    if k is None or pad[0][0] > fr[i][0]:
        return None
    a, b = fr[i - 1], fr[i]
    v0 = math.hypot(b[1] - a[1], b[2] - a[2]) / max(1e-3, b[0] - a[0])
    s = State(b[1], b[2], b[3], v0, b[5] if len(b) > 5 else 0.0)
    t, j, f = b[0], 0, i
    while t < fr[k][0] - 1e-9:
        j, (_, lx, ly, btn) = _pad_at(pad, t, j)
        while f + 1 <= k and fr[f + 1][0] <= t:
            f += 1
        dt = min(DT, fr[k][0] - t)
        s2 = step(p, s, lx, ly, fr[f][4], btn, dt)
        s = world.move(s, s2, seg.get("walk")) if world is not None else s2
        t += dt
    return s.x, s.z


def errors(p: Params | None, segs: list[dict], horizon: float, every: int = 2, world=None) -> list[float]:
    """Position error (m) at `horizon` s, from every `every`-th frame. p=None → baseline 'keeps its velocity';
    p='stay' → baseline 'stands still'. world: None = each segment's own seg["world"] (attach_worlds), False = none."""
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
                q = rollout(p, seg, i, horizon, seg.get("world") if world is None else (world or None))
                if q is None:
                    continue
            out.append(math.hypot(q[0] - fr[k][1], q[1] - fr[k][2]))
    return out


# ── the world: floor, walls, drops (NavMesh + recorded positions where the NavMesh has none) ──────────────────────

STEP_DY = 0.6            # floor within this up/down of the current height = walk on (stairs, slopes)
FALL_DY = 1.5            # only floor more than this below = walked off an edge: fall (edge_kinds 'drop')
CELL_M = 0.5             # off-mesh fill: recorded positions binned on this grid (lookup only) …
FILL_R = 0.35            # … walkable within this of a recorded position (was the whole 3×3 cell block, up to ~1 m:
                         #     it widened the secret passage — 2026-10-01) …
FILL_DY = 1.0            # … at that height ± this
FALL_GUARD_R = 2.0       # no fall where another walk went at this height within this — the bot never fell there in any
                         # record; the NavMesh only has the floor far below (passage entrance over the bridge arch, 16 m)
SLIDE_DEGS = (20, 40, 60, 80)   # blocked: try the move turned ± this much (and shortened by cos) — slide along a wall
                                # when only one side is open; both open at the same angle = pushing square into it: stay


class World:
    """Where the character can stand. move(old, new, walk_id) → the state actually reached:
      floor at the same level (± STEP_DY)  → go, height follows the floor
      a recorded position within FILL_R (off-mesh fill, other walks only) → go — the secret passage has no NavMesh (1-f)
      only floor far below (> FALL_DY), no walk within FALL_GUARD_R at this height → go and fall (falls += 1)
      nothing                              → a wall: slide (SLIDE_DEG), else stay put (pushing against it)"""

    def __init__(self, nm, fill: list[tuple] | None = None, fill_r: float = FILL_R, fall_guard_r: float = FALL_GUARD_R):
        self.nm = nm
        self.fill_r, self.fall_guard_r = fill_r, fall_guard_r
        self.falls = 0
        self.blocked = 0
        self.fill: dict[tuple[int, int], list[tuple[float, float, float, str]]] = {}
        for x, y, z, wid in fill or []:
            self.fill.setdefault((int(math.floor(x / CELL_M)), int(math.floor(z / CELL_M))), []).append((x, y, z, wid))

    def _near(self, x: float, z: float, y: float, wid, r: float) -> float | None:
        """Height of the nearest recorded position (another walk's) within r horizontally and FILL_DY in height."""
        cx, cz = int(math.floor(x / CELL_M)), int(math.floor(z / CELL_M))
        n = int(math.ceil(r / CELL_M))
        best, best_d = None, r
        for dx in range(-n, n + 1):
            for dz in range(-n, n + 1):
                for px, yy, pz, w in self.fill.get((cx + dx, cz + dz), ()):
                    if w == wid or abs(yy - y) > FILL_DY:
                        continue
                    d = math.hypot(px - x, pz - z)
                    if d <= best_d:
                        best, best_d = yy, d
        return best

    def _filled(self, x: float, z: float, y: float, wid) -> float | None:
        return self._near(x, z, y, wid, self.fill_r)

    def _floor(self, x: float, z: float, y: float, wid) -> tuple[str, float] | None:
        hit = self.nm.floor_tri_at(x, z, y)
        if hit is not None and abs(hit[0] - y) <= STEP_DY:
            return "floor", hit[0]
        f = self._filled(x, z, y, wid)
        if f is not None:
            return "fill", f
        if hit is not None and hit[0] < y - FALL_DY and self._near(x, z, y, wid, self.fall_guard_r) is None:
            return "fall", hit[0]
        return None

    def move(self, old: State, new: State, wid=None) -> State:
        dx, dz = new.x - old.x, new.z - old.z
        if dx * dx + dz * dz < 1e-12:
            return new
        here = self._floor(new.x, new.z, old.y, wid)
        if here is None:
            for deg in SLIDE_DEGS:
                c = math.cos(math.radians(deg))
                opts = []
                for a in (math.radians(deg), -math.radians(deg)):
                    sx = (dx * math.cos(a) + dz * math.sin(a)) * c
                    sz = (-dx * math.sin(a) + dz * math.cos(a)) * c
                    h = self._floor(old.x + sx, old.z + sz, old.y, wid)
                    if h is not None and h[0] != "fall":
                        opts.append((sx, sz, h))
                if len(opts) == 1:                       # the wall lies on one side: slide that way
                    sx, sz, here = opts[0]
                    new = replace(new, x=old.x + sx, z=old.z + sz)
                    break
                if len(opts) == 2:                       # both sides open at the same angle = pushing square into it
                    break
        if here is None:
            self.blocked += 1
            return replace(new, x=old.x, z=old.z, y=old.y)
        if here[0] == "fall":
            self.falls += 1
        return replace(new, y=here[1])


def world_for(nms: dict, segs: list[dict], fill_segs: list[dict] | None = None) -> "World":
    """The map whose NavMesh holds most of these segments' frames, with an off-mesh fill from fill_segs' positions."""
    pts = [(fr[1], fr[5], fr[2]) for sg in segs for fr in sg["frames"] if len(fr) > 5]
    nm = max(nms.values(), key=lambda m: sum(m.on_mesh(x, y, z) for x, y, z in pts[::5]))
    fill = [(fr[1], fr[5], fr[2], sg.get("walk")) for sg in (fill_segs or []) for fr in sg["frames"] if len(fr) > 5]
    return World(nm, fill)


def attach_worlds(data: dict[str, list[dict]], nms: dict) -> None:
    """Give every segment seg["world"]: its map's NavMesh, filled off-mesh from all files' positions (minus its own
    walk — World leaves those out by walk id)."""
    allsegs = [s for v in data.values() for s in v]
    for segs in data.values():
        if segs:
            w = world_for(nms, segs, allsegs)
            for sg in segs:
                sg["world"] = w


def load_navmeshes(folder: Path = ROOT / "data" / "samples") -> dict:
    import navmesh
    return {p.stem.replace("navmesh_", ""): navmesh.Navmesh.from_npz(p) for p in sorted(folder.glob("navmesh_*.npz"))}


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else math.inf


FIT_KEYS = {"v_jog": (2.5, 4.0), "v_run": (3.0, 5.5), "turn": (2.0, 30.0), "tau_up": (0.02, 0.8), "tau_down": (0.02, 0.8)}
# turn: 10 Hz frames can't resolve turns faster than ~10 rad/s — the human demos fit to the upper bound (turning looks
# instant at 10 Hz). The bot's 10 Hz radar recording + its stick will say more; nav.FACE_STICK's 84° in 0.6 s (0.45 stick)
# is the only slow-turn measurement so far.


def fit(segs: list[dict], p0: Params | None = None, horizon: float = 0.5, rounds: int = 3,
        keys: tuple[str, ...] | None = None, every: int = 2) -> Params:
    """Coordinate search over FIT_KEYS (or `keys`) minimising the mean position error at `horizon`. dead / walk band
    stay at the measured values — the demos hold few half-stick samples."""
    p = p0 or Params()
    best = _mean(errors(p, segs, horizon, every))
    for _ in range(rounds):
        for key, (lo, hi) in FIT_KEYS.items():
            if keys is not None and key not in keys:
                continue
            for frac in (0.5, 0.25, 0.1):
                cur = getattr(p, key)
                span = (hi - lo) * frac
                for v in (cur - span, cur + span):
                    v = min(hi, max(lo, v))
                    q = replace(p, **{key: v})
                    e = _mean(errors(q, segs, horizon, every))
                    if e < best - 1e-6:
                        p, best = q, e
    return p


def _q(xs: list[float], f: float) -> float:
    xs = sorted(xs)
    return xs[int(f * (len(xs) - 1))] if xs else math.nan


def cross_check(data: dict[str, list[dict]], horizons=(0.5, 1.0), keys: tuple[str, ...] | None = None) -> list[dict]:
    """Leave one file out: fit on the rest, error on it. → rows per (file, horizon) for model / keep velocity / stand."""
    rows = []
    names = [n for n, s in data.items() if s]
    for n in names:
        train = [s for m in names if m != n for s in data[m]]
        p = fit(train, keys=keys) if train else Params()
        for h in horizons:
            rows.append({"file": n, "h": h, "model": errors(p, data[n], h), "keep_v": errors(None, data[n], h),
                         "stay": errors("stay", data[n], h), "params": p})
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=["fit", "walls"])
    ap.add_argument("files", nargs="*")
    ap.add_argument("--slot", type=int, default=None, help="XInput slot of the pad to use (bot = 1 in radar recordings)")
    a = ap.parse_args()
    files = a.files or sorted(glob.glob(str(ROOT / "data" / "samples" / "observe_*.jsonl")))
    if a.cmd == "walls":
        files = a.files or sorted(glob.glob(str(ROOT / "data" / "samples" / "radar_walk_*.jsonl")))
        data = load(files, a.slot)
        attach_worlds(data, load_navmeshes())
        p = Params()
        print(f"1 s position error (m) p50 / p90 with the default params {[round(v, 2) for v in asdict(p).values()]}")
        print(f"  {'file':<32} {'map':<13} | {'walls':>11} | {'no walls':>11} | {'keep velocity':>13} | falls  blocked steps")
        for n, segs in data.items():
            if not segs:
                continue
            w = segs[0]["world"]
            w.falls = w.blocked = 0
            e_w = errors(p, segs, 1.0)
            fl, bl = w.falls, w.blocked
            f = lambda xs: f"{_q(xs, .5):5.2f}/{_q(xs, .9):5.2f}"
            print(f"  {n[:32]:<32} {w.nm.map_id:<13} | {f(e_w):>11} | {f(errors(p, segs, 1.0, world=False)):>11} | "
                  f"{f(errors(None, segs, 1.0)):>13} | {fl:5d}  {bl}")
        return
    data = load(files, a.slot)
    n_seg = sum(len(s) for s in data.values())
    n_fr = sum(len(x["frames"]) for s in data.values() for x in s)
    print(f"{len(files)} files, {n_seg} free-movement segments, {n_fr} frames ({n_fr / 10:.0f} s at 10 Hz)")
    allsegs = [s for v in data.values() for s in v]
    keys = None
    if any(n.startswith("radar_walk_") for n in data):
        # the bot holds B mostly right after a stuck escape ('re-approach running', nav.goto boost_until) — still
        # pressed against the wall, so B frames move 0.7 m/s (median): v_run can't be fitted without walls. Keep it.
        keys = tuple(k for k in FIT_KEYS if k != "v_run")
        print(f"bot walks: v_run kept at {Params().v_run} (B frames are stuck-escape re-approaches against walls)")
    p = fit(allsegs, keys=keys)
    print("fitted on all:", {k: round(v, 3) for k, v in asdict(p).items()})
    print(f"\nleave one file out — position error (m) p50 / p90:")
    print(f"  {'held-out file':<44} {'h':>4} | {'model':>11} | {'keep velocity':>13} | {'stand still':>11}")
    for r in cross_check(data, keys=keys):
        f = lambda xs: f"{_q(xs, .5):5.2f}/{_q(xs, .9):5.2f}"
        print(f"  {r['file'][:44]:<44} {r['h']:4.1f} | {f(r['model']):>11} | {f(r['keep_v']):>13} | {f(r['stay']):>11}"
              f"  (n {len(r['model'])})")


if __name__ == "__main__":
    main()
