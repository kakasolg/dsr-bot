"""Walk replay harness, layer 1 (open loop) — recorded walks, perturbed hundreds of times, fed to the stop checks. No game.

  python walk_replay.py                                  data/samples/*.track.jsonl, 200 variants
  python walk_replay.py data/runs/x.track.jsonl -n 500   other files / more variants
  python walk_replay.py --window 1.5 2 3                 compare settings (one row each)
  python walk_replay.py --walks                          per-walk progress / lateral error / corners (no perturbation)
  python walk_replay.py --gate 0.8 0.9 0.95 -n 20        the 0.95 switching rule (walkgeom.Gate, release 1.0 m) on the
                                                         recorded walks; --release -1 0.5 1.0 compares release values
  python walk_replay.py --lookahead 0.5 1.5 1.5/0.5      look-ahead at sharp corners: fixed vs shrunk (walkgeom.lookahead_dist)
  python walk_replay.py --hits                           stop on hit / stun: hits while walking and which rule sees them
  python walk_replay.py --recovery                       recovery after a stall: back-off vs success, anchor, retry limit

What it can and can't tell (ROADMAP 6-a): the recording is what the *old* controller did, so this layer evaluates the
**checks** (progress, lateral error, no-progress stop, bad observation, stun) — not a new way of steering. A new
controller needs layer 2 (motion model + NavMesh, closed loop).

Per variant the recording gets noise, dropped frames, time jitter, speed scaling, a constant offset and injected
position jumps (seeded, reproducible). Scored against the unperturbed recording:
  stall recall     no-progress stop fired during a real stall (track_report: ≥ STALL_S slow, no foe near, and not
                   during the bot's own action) at least `window` long — shorter ones can't be caught by a window check
  false stops/min  no-progress stop outside any stall, per minute of walking with no foe near
  jump recall      injected position jumps flagged as bad observation;  false bad-obs/min  flagged elsewhere
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import random
import re
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import track_report as TR
import walkgeom as G

ROOT = Path(__file__).resolve().parent


def stunned(anim) -> bool:
    """My own hit-stun (same ranges as patrol.player_locked, measured: 2000~2052 hit, 160 guard break). Roll anim ids
    aren't measured yet — add them here when they are."""
    a = anim if anim is not None else -1
    return 2000 <= a < 2100 or a == 160


def busy(anim) -> bool:
    """Doing something other than walking (attack, estus, item, stun) — progress isn't expected, so the no-progress
    check pauses. -1 is plain walking/standing."""
    return anim not in (None, -1)


@dataclass
class Params:
    window: float = 2.0       # s — no-progress: along-path gain over this window …
    min_gain: float = 0.3     # m — … below this = stop (nav.STUCK_WINDOW / STUCK_MIN_PROGRESS measure distance-to-point)
    lat_max: float = 1.5      # m — lateral error above this = 'off line' event
    v_max: float = 8.0        # m/s horizontal between frames above this = bad observation (run ≈ 3.7 m/s)
    gap_s: float = 1.5        # s without a frame = bad observation (track files are 2 Hz)


@dataclass
class Checks:
    """Stop / warning checks fed one frame at a time. update(frame) → list of events [{t, kind, p, ...}]."""
    path: list
    prm: Params = field(default_factory=Params)

    def __post_init__(self):
        self.lens = G.seg_lengths(self.path)
        self.k, self.along = 0, None
        self.prev = None
        self.hist: list[tuple[float, float]] = []     # (t, along) while progress is expected
        self.off = False
        self.stun = False
        self.cand = None                                 # last flagged frame

    def update(self, f: dict) -> list[dict]:
        ev = []
        t, p = f["t"], f["p"]
        if self.prev is not None:
            dt = t - self.prev["t"]
            if dt > self.prm.gap_s:
                ev.append({"t": t, "kind": "bad_obs", "why": "gap", "p": p})
                self.hist = []
            elif dt > 0 and math.hypot(p[0] - self.prev["p"][0], p[2] - self.prev["p"][2]) / dt > self.prm.v_max:
                c = self.cand
                moved = c is not None and t > c["t"] and \
                    math.hypot(p[0] - c["p"][0], p[2] - c["p"][2]) / (t - c["t"]) <= self.prm.v_max
                if not moved:                            # odd frame: flag it, keep the last good one as reference
                    ev.append({"t": t, "kind": "bad_obs", "why": "jump", "p": p})
                    self.cand = f
                    self.hist = []
                    return ev                            # … and don't let it move the segment index
                # two frames agreeing on the new place = we really are somewhere else (quit-out, warp): accept
        self.cand = None
        self.prev = f
        pr = G.locate(self.path, p, self.k, lens=self.lens, along_hint=self.along)
        self.k, self.along = pr.seg, pr.along
        st = stunned(f.get("anim"))
        if st and not self.stun:
            ev.append({"t": t, "kind": "stun", "p": p, "anim": f.get("anim")})
        self.stun = st
        if f.get("foe") or busy(f.get("anim")):
            self.hist = []                               # fighting / acting: not a walking stall
            self.off = False
            return ev
        off = abs(pr.lat) > self.prm.lat_max
        if off and not self.off:
            ev.append({"t": t, "kind": "off_line", "p": p, "lat": round(pr.lat, 2), "seg": pr.seg})
        self.off = off
        self.hist.append((t, pr.along))
        while len(self.hist) > 1 and t - self.hist[1][0] >= self.prm.window:
            self.hist.pop(0)
        t0, a0 = self.hist[0]
        if t - t0 >= self.prm.window and pr.along - a0 < self.prm.min_gain and pr.frac < 0.999:
            ev.append({"t": t, "kind": "no_progress", "p": p, "gain": round(pr.along - a0, 2), "seg": pr.seg})
            self.hist = [(t, pr.along)]                  # fire once per window
        return ev


def run_checks(w: dict, prm: Params) -> list[dict]:
    c = Checks(w["path"], prm)
    return [e for f in w["fr"] for e in c.update(f)]


# ── perturbations (seeded) ──────────────────────────────────────────────────────────────────────────────────────

@dataclass
class Variant:
    noise: float = 0.0        # m, gaussian on x/z
    drop: float = 0.0         # fraction of frames removed (never the first/last)
    t_jitter: float = 0.0     # s, gaussian on time (order kept)
    speed: float = 1.0        # time scale: 0.8 = same track 25 % faster
    offset: float = 0.0       # m, constant x/z shift in a random direction (a path drawn slightly off)
    jumps: int = 0            # injected single-frame position jumps
    jump_m: float = 6.0


def random_variant(rng: random.Random) -> Variant:
    return Variant(noise=rng.uniform(0.0, 0.2), drop=rng.choice((0.0, 0.0, 0.1, 0.25)), t_jitter=rng.uniform(0.0, 0.05),
                   speed=rng.uniform(0.8, 1.25), offset=rng.choice((0.0, 0.0, rng.uniform(0.2, 0.8))),
                   jumps=rng.choice((0, 0, 1, 2)), jump_m=rng.uniform(4.0, 10.0))


def perturb(fr: list[dict], v: Variant, rng: random.Random) -> tuple[list[dict], list[float]]:
    """→ (new frames, times of injected jumps)."""
    a = rng.uniform(0, 2 * math.pi)
    ox, oz = math.sin(a) * v.offset, math.cos(a) * v.offset
    t0 = fr[0]["t"]
    out = []
    for i, f in enumerate(fr):
        if 0 < i < len(fr) - 1 and rng.random() < v.drop:
            continue
        x, y, z = f["p"]
        t = t0 + (f["t"] - t0) * v.speed + rng.gauss(0.0, v.t_jitter)
        out.append({**f, "t": t, "p": (x + ox + rng.gauss(0.0, v.noise), y, z + oz + rng.gauss(0.0, v.noise))})
    for k in range(1, len(out)):                       # keep time order after jitter
        if out[k]["t"] <= out[k - 1]["t"]:
            out[k]["t"] = out[k - 1]["t"] + 1e-3
    jumps = []
    free = list(range(1, len(out) - 1))
    for _ in range(min(v.jumps, len(free))):
        k = free.pop(rng.randrange(len(free)))
        b = rng.uniform(0, 2 * math.pi)
        x, y, z = out[k]["p"]
        out[k] = {**out[k], "p": (x + math.sin(b) * v.jump_m, y, z + math.cos(b) * v.jump_m)}
        jumps.append(out[k]["t"])
    return out, jumps


# ── scoring ─────────────────────────────────────────────────────────────────────────────────────────────────────

def load_walks(files: list[str]) -> list[dict]:
    out = []
    for fn in files:
        for w in TR.walks(TR.frames(fn)):
            w["file"] = Path(fn).name
            out.append(w)
    return out


def truth(w: dict) -> list[dict]:
    """The real walking stalls of the unperturbed walk: track_report's stalls, minus those where the bot was doing
    something itself (smashing a crate, estus — busy()): the checks pause there on purpose."""
    return [s for s in TR.stalls(w["fr"])
            if not any(busy(f.get("anim")) for f in w["fr"] if s["t"] <= f["t"] <= s["t"] + s["s"])]


def free_minutes(fr: list[dict]) -> float:
    return sum(b["t"] - a["t"] for a, b in zip(fr, fr[1:]) if not a["foe"] and not busy(a.get("anim"))) / 60.0


def score_variant(w: dict, stalls: list[dict], prm: Params, v: Variant, rng: random.Random) -> dict:
    fr, jumps = perturb(w["fr"], v, rng)
    ev = run_checks({**w, "fr": fr}, prm)
    t0 = w["fr"][0]["t"]
    scale = lambda t: t0 + (t - t0) * v.speed            # stall times in the perturbed clock
    iv = [(scale(s["t"]), scale(s["t"] + s["s"])) for s in stalls]
    np_ev = [e for e in ev if e["kind"] == "no_progress"]
    catchable = [(a, b) for a, b in iv if b - a >= prm.window]
    slack = 1.0                                          # a window check fires up to one frame after the stall ends
    hit = sum(1 for a, b in catchable if any(a <= e["t"] <= b + slack for e in np_ev))
    false = sum(1 for e in np_ev if not any(a - slack <= e["t"] <= b + prm.window + slack for a, b in iv))
    bad = [e for e in ev if e["kind"] == "bad_obs" and e.get("why") == "jump"]
    caught = sum(1 for j in jumps if any(abs(e["t"] - j) < 1e-6 for e in bad))
    bad_false = sum(1 for e in bad if not any(abs(e["t"] - j) < 1e-6 for j in jumps))
    return {"stalls": len(catchable), "hit": hit, "false": false, "jumps": len(jumps), "caught": caught,
            "bad_false": bad_false, "minutes": free_minutes(fr), "off_line": sum(1 for e in ev if e["kind"] == "off_line")}


def evaluate(walks: list[dict], prm: Params, n: int = 200, seed: int = 0) -> dict:
    """n seeded variants of every walk → totals and rates."""
    rng = random.Random(seed)
    tot = {"stalls": 0, "hit": 0, "false": 0, "jumps": 0, "caught": 0, "bad_false": 0, "minutes": 0.0, "off_line": 0}
    ref = [(w, truth(w)) for w in walks]
    for _ in range(n):
        v = random_variant(rng)
        for w, st in ref:
            r = score_variant(w, st, prm, v, rng)
            for k in tot:
                tot[k] += r[k]
    m = max(tot["minutes"], 1e-9)
    return {**tot, "recall": tot["hit"] / tot["stalls"] if tot["stalls"] else None, "false_per_min": tot["false"] / m,
            "jump_recall": tot["caught"] / tot["jumps"] if tot["jumps"] else None, "bad_false_per_min": tot["bad_false"] / m,
            "off_line_per_min": tot["off_line"] / m}


# ── the 0.95 switching rule (walkgeom.Gate) on recorded walks ─────────────────────────────────────────────────

GATE_HELD_M = 2.0        # Gate's target this far behind where the bot really is (along the path) = 'held'


def gate_replay(w: dict, switch_s: float = G.SWITCH_S, fr: list[dict] | None = None,
                release_lat: float | None = G.RELEASE_LAT) -> dict:
    """Run Gate beside the recorded (old, radius-switching) walk. Open loop: the bot didn't steer by Gate, so this says
    where the old walk **did not reach s ≥ switch_s** before moving on — the places Gate would have held the target
    back and a Gate controller would have had to walk further (or would stall, if it can't get there).
      points     path points Gate has to switch at (1 … n−2) that the walk went past
      short      … of those, passed with max s < switch_s on the segment before (Gate holds there)
      short_sharp  … at a sharp corner (turn > walkgeom.SHARP_DEG)
      reach      max s reached on the segment before each passed point (list)
      held_s     seconds with Gate's target ≥ GATE_HELD_M behind the measured position
      lag_max    m, largest such gap
      stuck      the walk got onto the last segment but Gate never did
      held_at    [(point i, x, y, z)] where Gate is held (first frame of each held stretch)"""
    path = w["path"]
    fr = w["fr"] if fr is None else fr
    free = [f for f in fr if not f["foe"] and not busy(f.get("anim"))]
    out = {"points": 0, "short": 0, "short_sharp": 0, "sharp": 0, "reach": [], "held_s": 0.0, "lag_max": 0.0,
           "stuck": False, "held_at": []}
    if len(path) < 3 or len(free) < 2:
        return out
    lens = G.seg_lengths(path)
    gate = G.Gate(path, switch_s, k=None, release_lat=release_lat)
    k, along = 0, None
    reach: dict[int, float] = {}                         # segment → max s while measured on it or the next
    passed: set[int] = set()                             # point indices the measured position went past
    held_since = None
    prev_t = None
    for f in free:
        m = G.locate(path, f["p"], k, lens=lens, along_hint=along)
        if along is not None and m.seg > k:
            passed.update(range(k + 1, m.seg + 1))
        k, along = m.seg, m.along
        for j in (m.seg - 1, m.seg):
            if 0 <= j < len(lens):
                reach[j] = max(reach.get(j, -9.0), G.project(path, f["p"], j, lens).s)
        g = gate.update(f["p"])
        lag = m.along - g.along
        held = lag >= GATE_HELD_M
        if held and prev_t is not None:
            out["held_s"] += f["t"] - prev_t
        if held and held_since is None:
            q = path[gate.k + 1]
            out["held_at"].append((gate.k + 1, round(q[0], 1), round(q[1], 1) if len(q) > 2 else None,
                                   round(q[-1], 1)))
        held_since = f["t"] if held else None
        out["lag_max"] = max(out["lag_max"], lag)
        prev_t = f["t"]
    for i in sorted(passed):
        if not 1 <= i <= len(path) - 2:
            continue
        r = reach.get(i - 1, -9.0)
        sharp = G.turn_deg(path, i) > G.SHARP_DEG
        out["points"] += 1
        out["sharp"] += sharp
        out["reach"].append(round(r, 3))
        if r < switch_s:
            out["short"] += 1
            out["short_sharp"] += sharp
    out["stuck"] = k == len(path) - 2 and gate.k < len(path) - 2
    out["lag_max"] = round(out["lag_max"], 2)
    return out


def gate_eval(walks: list[dict], switch_s: float, n: int = 0, seed: int = 0,
              release_lat: float | None = G.RELEASE_LAT) -> dict:
    """gate_replay over all walks, unperturbed plus n seeded variants (noise, drops, …; jumps off — they aren't the
    question here). → totals."""
    rng = random.Random(seed)
    tot = {"walks": 0, "points": 0, "short": 0, "sharp": 0, "short_sharp": 0, "held_s": 0.0, "stuck": 0,
           "minutes": 0.0, "lags": []}
    for it in range(n + 1):
        v = Variant() if it == 0 else replace(random_variant(rng), jumps=0)
        for w in walks:
            fr = w["fr"] if it == 0 else perturb(w["fr"], v, rng)[0]
            r = gate_replay(w, switch_s, fr, release_lat)
            if not r["points"]:
                continue
            tot["walks"] += 1
            for key in ("points", "short", "sharp", "short_sharp", "held_s"):
                tot[key] += r[key]
            tot["stuck"] += r["stuck"]
            tot["minutes"] += free_minutes(fr)
            tot["lags"].append(r["lag_max"])
    lags = sorted(tot.pop("lags")) or [0.0]
    return {**tot, "lag_p50": lags[len(lags) // 2], "lag_p90": lags[int(0.9 * (len(lags) - 1))]}


def gate_places(walks: list[dict], switch_s: float, release_lat: float | None = G.RELEASE_LAT) -> list[tuple]:
    """Where Gate is held, over all unperturbed walks: [(count, tag, point i, x, y, z)] most first."""
    seen: dict = {}
    for w in walks:
        for i, x, y, z in gate_replay(w, switch_s, release_lat=release_lat)["held_at"]:
            key = (w["tag"], x, y, z)
            seen[key] = seen.get(key, (0, w["tag"], i, x, y, z))
            seen[key] = (seen[key][0] + 1,) + seen[key][1:]
    return sorted(seen.values(), key=lambda r: -r[0])


# ── look-ahead (walkgeom.lookahead_dist) on recorded walks ─────────────────────────────────────────────────────

LA_NEAR_M = 3.0          # frames this close (horizontal) to a sharp corner point are 'at a corner'
LA_CUT_M = 0.25          # chord this far inside the path (beyond the bot's own offset) = a cut — about half the body
                         # (a 1.5 m aim at a 90° corner cuts ≤ ~0.5 m by geometry, so 0.5 m would count nothing)


def parse_la(spec: str) -> tuple[float, float]:
    """'1.5' = fixed 1.5 m, '1.5/0.5' = 1.5 m shrunk to 0.5 m at sharp corners (walkgeom.lookahead_dist)."""
    a, _, b = spec.partition("/")
    return float(a), float(b or a)


def _near_path(path: list, lens: list[float], p, lo: float, hi: float) -> float:
    """Horizontal distance from p to the part of the path between along lo and hi."""
    acc, best = 0.0, math.inf
    for k, L in enumerate(lens):
        if acc + L >= lo and acc <= hi:
            best = min(best, TR.seg_dist(p, path[k], path[k + 1]))
        acc += L
    return best


def lookahead_replay(w: dict, base: float, short: float, fr: list[dict] | None = None) -> dict:
    """Aim at the path point `lookahead_dist` ahead of where the bot really was, frame by frame. Open loop — the bot
    didn't steer by it; this is the geometry of the aim from the recorded positions, at sharp corners only.
      frames   free frames within LA_NEAR_M of a sharp corner
      cut      m, how far the straight line bot → aim point runs inside the path, beyond the bot's own offset
               (the chord cutting the corner = what walks into the inside wall, P-17 / 1-f), one value per frame
      turn     deg/m, change of aim bearing per metre walked between consecutive corner frames (how hard the
               stick has to swing), one value per step
      passes   [(turn deg of the corner, worst cut while near it)] — one per corner passed"""
    path = w["path"]
    fr = w["fr"] if fr is None else fr
    out = {"frames": 0, "cut": [], "turn": [], "passes": []}
    if len(path) < 3:
        return out
    lens = G.seg_lengths(path)
    corners = [(G._xz(path[i]), G.turn_deg(path, i)) for i in range(1, len(path) - 1)]
    corners = [(c, d) for c, d in corners if d > G.SHARP_DEG]
    if not corners:
        return out
    k, along, prev = 0, None, None
    worst: dict[int, float] = {}                        # corner index → worst cut near it
    for f in fr:
        if f["foe"] or busy(f.get("anim")):
            prev = None
            continue
        pr = G.locate(path, f["p"], k, lens=lens, along_hint=along)
        k, along = pr.seg, pr.along
        px, pz = f["p"][0], f["p"][2]
        ci, dc = min(((j, math.hypot(px - c[0], pz - c[1])) for j, (c, _) in enumerate(corners)), key=lambda t: t[1])
        if dc > LA_NEAR_M:
            prev = None
            continue
        L = G.lookahead_dist(path, pr, base, short, lens=lens)
        aim = G.point_at(path, pr.along + L, lens)
        ax, az = G._xz(aim)
        own = _near_path(path, lens, f["p"], pr.along - 2.0, pr.along + L + 2.0)
        n = max(2, int(math.hypot(ax - px, az - pz) / 0.1))
        dev = max(_near_path(path, lens, (px + (ax - px) * t / n, 0.0, pz + (az - pz) * t / n),
                             pr.along - 2.0, pr.along + L + 2.0) for t in range(n + 1))
        out["frames"] += 1
        cut = max(0.0, dev - own)
        out["cut"].append(cut)
        worst[ci] = max(worst.get(ci, 0.0), cut)
        bearing = math.atan2(ax - px, az - pz)
        if prev is not None:
            moved = math.hypot(px - prev[0], pz - prev[1])
            if moved > 0.2:
                d = (bearing - prev[2] + math.pi) % (2 * math.pi) - math.pi
                out["turn"].append(abs(math.degrees(d)) / moved)
        prev = (px, pz, bearing)
    out["passes"] = [(corners[j][1], c) for j, c in sorted(worst.items())]
    return out


def lookahead_eval(walks: list[dict], base: float, short: float, n: int = 0, seed: int = 0) -> dict:
    """lookahead_replay over all walks, unperturbed plus n seeded variants (jumps off). → quantiles."""
    rng = random.Random(seed)
    cut, turn, frames, passes = [], [], 0, []
    for it in range(n + 1):
        v = Variant() if it == 0 else replace(random_variant(rng), jumps=0)
        for w in walks:
            fr = w["fr"] if it == 0 else perturb(w["fr"], v, rng)[0]
            r = lookahead_replay(w, base, short, fr)
            frames += r["frames"]
            cut += r["cut"]
            turn += r["turn"]
            passes += r["passes"]
    q = lambda xs, a: sorted(xs)[int(a * (len(xs) - 1))] if xs else 0.0
    return {"frames": frames, "cut_frac": sum(c > LA_CUT_M for c in cut) / max(1, len(cut)),
            "cut_p50": q(cut, 0.5), "cut_p90": q(cut, 0.9), "turn_p50": q(turn, 0.5), "turn_p90": q(turn, 0.9),
            "passes": len(passes), "pass_cut": sum(c > LA_CUT_M for _, c in passes) / max(1, len(passes)),
            "sharp90": sum(d >= 90 for d, _ in passes),
            "pass_cut90": sum(c > LA_CUT_M for d, c in passes if d >= 90) / max(1, sum(d >= 90 for d, _ in passes))}


# ── stop on hit / stun (the 'hit, stagger, roll' stop condition) ──────────────────────────────────────────────

HIT_MIN = 10             # HP lost between two frames to count as a hit (patrol.CHIP_DMG: blocked chip is ≤ 10)
HIT_R = 3.0              # souls/reflex.HIT_R: today the walk stops on an HP drop only with an awake foe this close
HIT_REPEAT_S = 3.0       # another hit within this after the first = the walk kept taking damage
HIT_WALKING_S = 1.0      # 'hit while walking': the second before, plain anim (-1) and moving
HIT_WALK_V = 0.5         # m/s


def hit_events(w: dict) -> list[dict]:
    """Hits taken while walking, from a recorded walk. → [{t, p, dmg, foe_d, stun_seen, repeat}]
      stun_seen  my stun anim (stunned()) in a frame from 0.5 s before to 1.0 s after — what an anim-only stop sees
                 (2 Hz track: a 0.4~0.9 s stun is easily missed between frames; the bot reads at ~200 Hz)
      repeat     another hit within HIT_REPEAT_S"""
    fr = w["fr"]
    out = []
    for i in range(1, len(fr)):
        a, b = fr[i - 1], fr[i]
        if a.get("hp") is None or b.get("hp") is None or a["hp"] - b["hp"] < HIT_MIN:
            continue
        before = [f for f in fr[:i] if b["t"] - HIT_WALKING_S - 1e-9 <= f["t"] <= a["t"]]
        if not before or any(busy(f.get("anim")) for f in before):
            continue                                     # already fighting / acting: not a walking hit
        d = math.hypot(before[-1]["p"][0] - before[0]["p"][0], before[-1]["p"][2] - before[0]["p"][2])
        dt = before[-1]["t"] - before[0]["t"]
        if len(before) >= 2 and (dt <= 0 or d / dt < HIT_WALK_V):
            continue                                     # standing (holding a spot, waiting): not walking
        ds = [x for x in (a.get("foe_d"), b.get("foe_d")) if x is not None]
        win = [f for f in fr if b["t"] - 0.5 <= f["t"] <= b["t"] + 1.0]
        later = [f for j, f in enumerate(fr[i + 1:], i + 1)
                 if f["t"] - b["t"] <= HIT_REPEAT_S and fr[j - 1].get("hp") is not None and f.get("hp") is not None
                 and fr[j - 1]["hp"] - f["hp"] >= HIT_MIN]
        out.append({"t": b["t"], "p": b["p"], "dmg": a["hp"] - b["hp"], "foe_d": min(ds) if ds else None,
                    "stun_seen": any(stunned(f.get("anim")) for f in win), "repeat": bool(later)})
    return out


def hit_eval(walks: list[dict]) -> dict:
    """Walking hits over all walks, split by the nearest awake foe at the hit, with what each stop rule would catch:
      anim   stunned() seen (the stop condition as written: hit-stun / stagger)
      hp     any HP drop ≥ HIT_MIN (the direct signal — catches every hit by definition)
      now    HP drop + awake foe ≤ HIT_R (today's reflex.threat_now → the walk stops and fights)"""
    ev = [dict(e, tag=w["tag"]) for w in walks for e in hit_events(w)]
    bands = [("≤3 m", lambda d: d is not None and d <= HIT_R), ("3–6 m", lambda d: d is not None and HIT_R < d <= 6.0),
             ("6–12 m", lambda d: d is not None and d > 6.0), ("none ≤12 m", lambda d: d is None)]
    rows = []
    for name, ok in bands:
        es = [e for e in ev if ok(e["foe_d"])]
        rows.append({"band": name, "hits": len(es), "dmg": sum(e["dmg"] for e in es),
                     "anim": sum(e["stun_seen"] for e in es), "now": sum(e["foe_d"] is not None and e["foe_d"] <= HIT_R for e in es),
                     "repeat": sum(e["repeat"] for e in es)})
    return {"events": ev, "rows": rows, "hits": len(ev), "anim": sum(e["stun_seen"] for e in ev),
            "now": sum(e["foe_d"] is not None and e["foe_d"] <= HIT_R for e in ev), "repeat": sum(e["repeat"] for e in ev)}


# ── recovery after a stall (neutral → short back-off or back to the last safe anchor → retry limit → safe stop) ──

REC_PLACE_R = 3.0        # stalls this close (horizontal) = retries at the same place
REC_BACK_S = 3.0         # how long after a stall ends to look for the back-off
REC_OK_M = 1.0           # got through = along the stalled walk's path this far past the stall (any later walk counts —
REC_GIVE_S = 60.0        #   a detour "… 돌아서" is part of the recovery) within this
REC_START_M = 0.5        # stall within this of the path start = a slow start, not a blockage
REC_END_M = 1.5          # … within this of the path end = arriving
ANCHOR_V = 1.0           # m/s — 'moving normally' …
ANCHOR_S = 1.0           # … for this long = a safe anchor (the last one before the stall)


def load_runs(files: list[str]) -> list[dict]:
    """[{file, fr, walks, says}] — whole-run frames too, since recovery can run through later walks (detours);
    says = the bot's log lines the track file carries [(t, line)]."""
    out = []
    for fn in files:
        fr = TR.frames(fn)
        ws = TR.walks(fr)
        for w in ws:
            w["file"] = Path(fn).name
        says = []
        for line in open(fn, encoding="utf-8", errors="replace"):
            if '"say"' not in line:
                continue
            try:
                m = json.loads(line)
            except ValueError:
                continue
            if m.get("type") == "say":
                says.append((float(m["rt"]), m.get("line", "")))
        out.append({"file": Path(fn).name, "fr": fr, "walks": ws, "says": says})
    return out


START_CAUSES = ("quit-out load", "fight (foe ≤ 12 m, waiting)", "right after a fight", "fog wall ahead",
                "almost there at point 0", "bonfire (A)", "door / pick-up (A)", "unknown")
START_A_S = 8.0          # a big door takes ~6 s to push open (asylum 수용소2: 0.25 m/s creep for 6 s after A, anim -1)


def start_cause(run: dict, e: dict, stall_s: float) -> str:
    """Why the bot stood at a walk's start, from the log lines around it and the foes in the frames.
    First match wins, in START_CAUSES order."""
    t0, t1 = e["t"], e["t"] + stall_s
    near = lambda a, b: [x for t, x in run.get("says", []) if t0 - a <= t <= t1 + b]
    if any("퀵 종료" in x for x in near(10.0, 0.0)):
        return START_CAUSES[0]                           # loading after a quit-out: the position is frozen
    fr = [f for f in run["fr"] if t0 <= f["t"] <= t1]
    if any(f.get("foe_d") is not None for f in fr) or any("기다림" in x for x in near(0.5, 0.5)):
        return START_CAUSES[1]                           # a duel waiting on a foe beyond FOE_R (6 m) — not walking
    if any("killed —" in x or ": stuck —" in x for x in near(2.0, 0.0)):
        return START_CAUSES[2]
    if any("안개벽" in x for x in near(0.0, 8.0)):
        return START_CAUSES[3]                           # the walk's points lie beyond a fog wall (fog_through after 2 misses)
    if any("0/" in x and "못 감" in x and e["tag"] in x for x in near(0.0, 3.0)):
        return START_CAUSES[4]                           # stuck ≤ 1.7 m from point 0 (field.ALMOST_M handles it now)
    a = [x for x in near(START_A_S, 0.0) if " A ×" in x]
    if a:
        return START_CAUSES[5] if "화톳불" in a[-1] else START_CAUSES[6]
    return START_CAUSES[7]


def _along_on(path: list, lens: list[float], frames: list[dict]) -> list[tuple[float, float, dict]]:
    """[(t, along on `path`, frame)] for free frames (no foe, plain anim), tracked with locate."""
    out, k, a = [], 0, None
    for f in frames:
        if f["foe"] or busy(f.get("anim")):
            continue
        pr = G.locate(path, f["p"], k, lens=lens, along_hint=a)
        k, a = pr.seg, pr.along
        out.append((f["t"], pr.along, f))
    return out


def recovery_events(run: dict) -> list[dict]:
    """Walking stalls (truth()) of one run and what came after — open loop, the old nav.goto escape / detours did it.
    → [{t, p, tag, kind, along, back, away, anchor, ok, ok_s}]
      kind    'start' (≤ REC_START_M into the path: standing before setting off), 'end' (≤ REC_END_M from the end),
              'mid' (a real blockage)
      back    m back along the stalled path within REC_BACK_S after the stall;  away = m from the stall spot
      anchor  m along the path back to the last stretch moving ≥ ANCHOR_V for ANCHOR_S (None if none in the walk)
      ok      got REC_OK_M past the stall along that path within REC_GIVE_S (through any later walk);  ok_s = when"""
    out = []
    for w in run["walks"]:
        path = w["path"]
        if len(path) < 2:
            continue
        lens = G.seg_lengths(path)
        total = sum(lens)
        mine = _along_on(path, lens, w["fr"])
        for st in truth(w):
            t0, t1 = st["t"], st["t"] + st["s"]
            here = [a for t, a, _ in mine if t0 <= t <= t1]
            if not here:
                continue
            a0 = max(here)
            kind = "start" if a0 <= REC_START_M else "end" if total - a0 <= REC_END_M else "mid"
            later = _along_on(path, lens, [f for f in run["fr"] if t1 < f["t"] <= t1 + REC_GIVE_S])
            back = max(0.0, a0 - min((a for t, a, _ in later if t <= t1 + REC_BACK_S), default=a0))
            away = max((math.hypot(f["p"][0] - st["p"][0], f["p"][2] - st["p"][2])
                        for t, _, f in later if t <= t1 + REC_BACK_S), default=0.0)
            ok_t = next((t for t, a, _ in later if a >= a0 + REC_OK_M), None)
            anchor = None
            prev = [(t, a, f) for t, a, f in mine if t < t0]
            for j in range(len(prev) - 1, 0, -1):
                span = [f for t, _, f in prev[:j + 1] if prev[j][0] - ANCHOR_S - 1e-9 <= t]
                if len(span) >= 2 and span[-1]["t"] > span[0]["t"]:
                    v = math.hypot(span[-1]["p"][0] - span[0]["p"][0], span[-1]["p"][2] - span[0]["p"][2]) / \
                        (span[-1]["t"] - span[0]["t"])
                    if v >= ANCHOR_V:
                        anchor = max(0.0, a0 - prev[j][1])
                        break
            out.append({"t": t0, "p": st["p"], "tag": w["tag"], "kind": kind, "along": a0, "back": back, "away": away,
                        "anchor": anchor, "ok": ok_t is not None, "ok_s": None if ok_t is None else ok_t - t0,
                        "s": st["s"]})
            if kind == "start":
                out[-1]["cause"] = start_cause(run, out[-1], st["s"])
    return out


REC_NEAR_M = 1.7         # a point missed from this close (and |dy| ≤ REC_NEAR_DY) = 'almost there'
REC_NEAR_DY = 0.8
_FAIL_ME = re.compile(r"— 나 \(([^)]*)\), ([\d.]+) m")


def recovery_from_logs(files: list[str]) -> dict:
    """What the current recovery chain did, from bot logs (field._walk_missed: a point not reached → smash a prop /
    NavMesh detour "… 돌아서" → next point; 3 failures in a row → 'stuck'). The 2 Hz tracks hold few mid-walk stalls,
    the logs every "못 감" line. → {fails: [{t, tag, detour, why, k, dist, dy}], …}"""
    import hotspots as H
    fails = []
    for fn in files:
        for line in open(fn, encoding="utf-8", errors="replace"):
            m = H._T.match(line.rstrip())
            if not m:
                continue
            f = H._FAIL.search(m.group(2))
            d = _FAIL_ME.search(m.group(2))
            if not f or not d:
                continue
            q = [float(v) for v in f.group("q").split(",")]
            me = [float(v) for v in d.group(1).split(",")]
            tag = f.group("tag").strip()
            fails.append({"file": Path(fn).name, "t": float(m.group(1)), "tag": tag, "detour": tag.endswith("돌아서"),
                          "i": int(f.group("i")), "why": f.group("why"), "k": int(f.group("k")),
                          "dist": float(d.group(2)), "dy": q[1] - me[1]})
    base = [x for x in fails if not x["detour"]]
    followed = [x for x in base if any(y["detour"] and y["file"] == x["file"] and 0 < y["t"] - x["t"] <= 10.0
                                       and y["tag"].startswith(x["tag"]) for y in fails)]
    near = [x for x in fails if x["dist"] <= REC_NEAR_M and abs(x["dy"]) <= REC_NEAR_DY]
    dt = [x for x in fails if x["detour"]]
    return {"fails": fails, "files": len(files), "base": len(base), "detour_failed": len(followed),
            "detour_lines": len(dt), "detour_near": sum(x["dist"] <= REC_NEAR_M and abs(x["dy"]) <= REC_NEAR_DY for x in dt),
            "near": len(near), "near_stuck": sum(x["why"] == "stuck" for x in near),
            "k": {k: sum(x["k"] == k for x in fails) for k in (1, 2, 3)},
            "why": {w: sum(x["why"] == w for x in fails) for w in ("stuck", "timeout", "unreachable")}}


def recovery_eval(runs: list[dict], limits=(1, 2, 3)) -> dict:
    """Over all runs: stalls by kind; for the mid-walk ones, recovery rate by how far the old escape backed off,
    distance to the last safe anchor, and for each retry limit N (safe stop at the (N+1)-th stall at one place before
    getting through): premature stops (it did get through later) vs right ones (never did, seconds saved)."""
    ev = [dict(e, run=r["file"]) for r in runs for e in recovery_events(r)]
    kinds = {k: [e for e in ev if e["kind"] == k] for k in ("start", "mid", "end")}
    mid = kinds["mid"]
    bins = [("< 0.3 m", 0.0, 0.3), ("0.3–1 m", 0.3, 1.0), ("≥ 1 m", 1.0, math.inf)]
    by_back = [{"bin": n, "tries": sum(lo <= e["back"] < hi for e in mid),
                "ok": sum(lo <= e["back"] < hi and e["ok"] for e in mid)} for n, lo, hi in bins]
    places: list[dict] = []                              # mid stalls grouped by run + place, in time order
    for e in sorted(mid, key=lambda e: (e["run"], e["t"])):
        for pl in places:
            if pl["run"] == e["run"] and math.hypot(pl["p"][0] - e["p"][0], pl["p"][2] - e["p"][2]) <= REC_PLACE_R:
                pl["tries"].append(e)
                break
        else:
            places.append({"run": e["run"], "p": e["p"], "tries": [e]})
    for pl in places:
        pl["ok"] = pl["tries"][-1]["ok"]
    lim = []
    for N in limits:
        hit = [p for p in places if len(p["tries"]) > N]
        right = [p for p in hit if not p["ok"]]
        lim.append({"N": N, "stops": len(hit), "premature": len(hit) - len(right), "right": len(right)})
    causes = {c: [e for e in kinds["start"] if e.get("cause") == c] for c in START_CAUSES}
    return {"kinds": {k: len(v) for k, v in kinds.items()}, "start_causes": causes,
            "mid": mid, "mid_ok": sum(e["ok"] for e in mid), "ok_s": sorted(e["ok_s"] for e in mid if e["ok"]),
            "by_back": by_back, "anchors": sorted(e["anchor"] for e in mid if e["anchor"] is not None),
            "no_anchor": sum(e["anchor"] is None for e in mid), "places": places, "limits": lim}


def walk_table(walks: list[dict]) -> str:
    """Unperturbed: per walk, lateral error (no foe near), corners passed on the inside, check events."""
    lines = []
    for w in walks:
        lens = G.seg_lengths(w["path"])
        k, along, lats = 0, None, []
        for f in w["fr"]:
            pr = G.locate(w["path"], f["p"], k, lens=lens, along_hint=along)
            k, along = pr.seg, pr.along
            if not f["foe"]:
                lats.append(abs(pr.lat))
        lats.sort()
        p95 = lats[int(0.95 * (len(lats) - 1))] if lats else 0.0
        cuts = G.corner_cuts(w["path"], [f["p"] for f in w["fr"] if not f["foe"]])
        inside = [c for c in cuts if c["inside"] and c["dist"] > 0.5]
        ev = run_checks(w, Params())
        kinds = {}
        for e in ev:
            kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
        lines.append(f"  {w['fr'][0]['t']:7.1f} s  {w['tag']}: {len(w['path'])} pts, |lat| p95 {p95:.2f} m max "
                     f"{(lats[-1] if lats else 0):.2f} m, corners {len(cuts)} (inside >0.5 m: {len(inside)})"
                     + (f", checks {kinds}" if kinds else ""))
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("files", nargs="*")
    ap.add_argument("-n", type=int, default=200, help="variants per walk")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--window", type=float, nargs="+", default=[Params.window])
    ap.add_argument("--min-gain", type=float, nargs="+", default=[Params.min_gain])
    ap.add_argument("--walks", action="store_true", help="per-walk table of the unperturbed recording")
    ap.add_argument("--gate", type=float, nargs="+", metavar="S",
                    help="evaluate the switching rule (walkgeom.Gate) at these switch_s values instead, e.g. --gate 0.8 0.9 0.95")
    ap.add_argument("--recovery", action="store_true",
                    help="evaluate recovery after a stall instead: back-off size vs success, anchor distance, retry limit")
    ap.add_argument("--hits", action="store_true",
                    help="evaluate the stop-on-hit/stun condition instead: hits taken while walking and which rule sees them")
    ap.add_argument("--lookahead", nargs="+", metavar="L",
                    help="evaluate look-ahead settings instead: '1.5' fixed, '1.5/0.5' shrunk at sharp corners, "
                         "e.g. --lookahead 0.5 1.0 1.5 2.5 1.5/0.5 2.5/0.5")
    ap.add_argument("--release", type=float, nargs="+", default=[G.RELEASE_LAT], metavar="M",
                    help="with --gate: Gate release_lat values in m (-1 = no release; default walkgeom.RELEASE_LAT), "
                         "e.g. --release -1 0.5 1.0")
    a = ap.parse_args()
    files = a.files or sorted(glob.glob(str(ROOT / "data" / "samples" / "*.track.jsonl")))
    walks = load_walks(files)
    if not walks:
        print("no walks — give track files (data/runs/*.track.jsonl) or radar recordings")
        return
    print(f"{len(files)} files, {len(walks)} walks, {sum(len(truth(w)) for w in walks)} real stalls")
    if a.walks:
        print(walk_table(walks))
        return
    if a.recovery:
        r = recovery_eval(load_runs(files))
        q = lambda xs, f: xs[int(f * (len(xs) - 1))] if xs else 0.0
        k = r["kinds"]
        print(f"walking stalls (≥ {TR.STALL_S:.0f} s, no foe, plain anim): start {k['start']} (standing before setting off), "
              f"end {k['end']} (arriving), mid-walk {k['mid']} — open loop: the old nav.goto escape / detours recovered")
        print(f"  why it stood at a walk's start (log lines around it, foes in the frames):")
        for c, es in r["start_causes"].items():
            if es:
                print(f"    {c:>28}: {len(es):2d}  ({sum(e['s'] for e in es):.1f} s)  e.g. {es[0]['run'][:30]} {es[0]['t']:.1f} s {es[0]['tag']}")
        mid = r["mid"]
        if mid:
            print(f"  mid-walk: got {REC_OK_M:.0f} m past within {REC_GIVE_S:.0f} s {r['mid_ok']}/{len(mid)} "
                  f"(time to it p50 {q(r['ok_s'], .5):.1f} s, max {q(r['ok_s'], 1):.1f} s) at {len(r['places'])} places")
            print(f"  by how far it backed off along the path within {REC_BACK_S:.0f} s:")
            for b in r["by_back"]:
                print(f"    {b['bin']:>8}: {b['ok']}/{b['tries']} got through" + (f" ({b['ok'] / b['tries']:.0%})" if b["tries"] else ""))
            an = r["anchors"]
            print(f"  last safe anchor (moving ≥ {ANCHOR_V:.0f} m/s for {ANCHOR_S:.0f} s) behind: "
                  + (f"p50 {q(an, .5):.1f} m, max {q(an, 1):.1f} m; " if an else "") + f"none in the walk {r['no_anchor']}")
            for l in r["limits"]:
                print(f"  retry limit N={l['N']}: safe stops {l['stops']} — premature (got through later) {l['premature']}, "
                      f"right (never did) {l['right']}")
            for e in mid:
                anc = "—" if e["anchor"] is None else f"{e['anchor']:.1f} m"
                res = f"through in {e['ok_s']:.1f} s" if e["ok"] else "NOT through"
                print(f"    {e['run'][:28]:28} {e['t']:6.1f} s {e['tag'][:14]:14} ({e['p'][0]:.1f}, {e['p'][1]:.1f}, {e['p'][2]:.1f}) "
                      f"back {e['back']:.1f} m away {e['away']:.1f} m anchor {anc} {res}")
        logs = sorted(glob.glob(str(ROOT / "data" / "samples" / "*.txt")))
        L = recovery_from_logs(logs)
        n = max(1, len(L["fails"]))
        print(f"\nbot logs ({L['files']} in data/samples): {len(L['fails'])} '못 감' (point not reached) — "
              f"stuck {L['why']['stuck']}, timeout {L['why']['timeout']}, unreachable {L['why']['unreachable']}")
        print(f"  retries at one walk (the 'N번째' count): 1st {L['k'][1]}, 2nd {L['k'][2]}, 3rd {L['k'][3]} "
              f"— today's limit (3 in a row → 'stuck') never reached")
        print(f"  almost there (≤ {REC_NEAR_M} m from the point, |dy| ≤ {REC_NEAR_DY} m): {L['near']} ({L['near'] / n:.0%}), "
              f"all 'stuck' {L['near_stuck']} — the arrival radius (1 m / corner 0.5 / stairs 0.4) not met, not a blockage")
        print(f"  NavMesh detour ('… 돌아서') after a first miss that failed too: {L['detour_failed']}/{L['base']} "
              f"({L['detour_failed'] / max(1, L['base']):.0%}); of the detours' own misses {L['detour_near']}/{L['detour_lines']} "
              f"are almost there too")
        return
    if a.hits:
        r = hit_eval(walks)
        n = max(1, r["hits"])
        print(f"hits taken while walking (HP −{HIT_MIN}+ between frames, plain anim and moving the second before): {r['hits']}")
        print(f"  stop rule sees it:  anim (stun) {r['anim']} ({r['anim'] / n:.0%})   HP drop {r['hits']} (100 %)   "
              f"today (HP drop + foe ≤ {HIT_R:.0f} m) {r['now']} ({r['now'] / n:.0%})")
        print(f"  {'nearest awake foe':>18} | {'hits':>4} {'HP lost':>7} | {'anim sees':>9} {'today stops':>11} | "
              f"{'hit again ≤' + str(int(HIT_REPEAT_S)) + ' s':>14}")
        for row in r["rows"]:
            h = max(1, row["hits"])
            print(f"  {row['band']:>18} | {row['hits']:4d} {row['dmg']:7d} | {row['anim'] / h:9.0%} {row['now'] / h:11.0%} | "
                  f"{row['repeat']:5d} ({row['repeat'] / h:.0%})")
        missed = [e for e in r["events"] if not (e["foe_d"] is not None and e["foe_d"] <= HIT_R) and e["repeat"]]
        if missed:
            print(f"\nwalking hits today's rule doesn't stop for, then hit again within {HIT_REPEAT_S:.0f} s:")
            for e in missed[:15]:
                fd = "—" if e["foe_d"] is None else f"{e['foe_d']:.1f} m"
                print(f"  {e['t']:7.1f} s  {e['tag']}  −{e['dmg']}  foe {fd}  at ({e['p'][0]:.1f}, {e['p'][1]:.1f}, {e['p'][2]:.1f})")
        return
    if a.lookahead:
        print(f"look-ahead: open loop — aim from the recorded positions at sharp corners (unperturbed + {a.n} variants)")
        print(f"{'setting':>9} | {'corner passes cut >' + str(LA_CUT_M) + ' m':>24} {'≥90° only':>10} | {'frame cut p90':>13} | "
              f"{'aim turn deg/m p50':>18} {'p90':>6}")
        for spec in a.lookahead:
            b, sh = parse_la(spec)
            r = lookahead_eval(walks, b, sh, a.n, a.seed)
            print(f"{spec:>9} | {r['pass_cut']:17.2f} of {r['passes']:<4} {r['pass_cut90']:10.2f} | {r['cut_p90']:11.2f} m | "
                  f"{r['turn_p50']:18.1f} {r['turn_p90']:6.1f}")
        return
    if a.gate:
        print(f"Gate: open loop — where the recorded walk moved on before s reached switch_s (unperturbed + {a.n} variants)")
        print(f"{'switch_s':>8} {'release':>7} | {'points short':>18} {'sharp short':>16} | {'held s/min':>10} "
              f"{'stuck walks':>12} | {'lag p50':>7} {'p90':>6}")
        for rel in a.release:
            rl = None if rel < 0 else rel
            for sw in a.gate:
                r = gate_eval(walks, sw, a.n, a.seed, rl)
                pt = f"{r['short']}/{r['points']} {r['short'] / max(1, r['points']):.2f}"
                sh = f"{r['short_sharp']}/{r['sharp']} {r['short_sharp'] / max(1, r['sharp']):.2f}"
                print(f"{sw:8.2f} {('—' if rl is None else f'{rl:.1f} m'):>7} | {pt:>18} {sh:>16} | "
                      f"{r['held_s'] / max(r['minutes'], 1e-9):10.1f} {r['stuck']:>5}/{r['walks']:<6} | "
                      f"{r['lag_p50']:7.1f} {r['lag_p90']:6.1f}")
        sw = min(a.gate, key=lambda v: abs(v - G.SWITCH_S))
        places = gate_places(walks, sw, None)
        if places:
            print(f"\nwhere plain Gate {sw} (no release) is first held (unperturbed), most first:")
            for c, tag, i, x, y, z in places[:15]:
                print(f"  {c}x  {tag} point {i}  ({x}, {y}, {z})")
        return
    print(f"{'window':>6} {'gain':>5} | {'stall recall':>14} {'false/min':>9} | {'jump recall':>13} {'bad/min':>8} | {'off/min':>7}")
    for win in a.window:
        for g in a.min_gain:
            r = evaluate(walks, replace(Params(), window=win, min_gain=g), a.n, a.seed)
            rec = f"{r['hit']}/{r['stalls']} {r['recall']:.2f}" if r["recall"] is not None else "—"
            jr = f"{r['caught']}/{r['jumps']} {r['jump_recall']:.2f}" if r["jump_recall"] is not None else "—"
            print(f"{win:6.1f} {g:5.2f} | {rec:>14} {r['false_per_min']:9.2f} | {jr:>13} {r['bad_false_per_min']:8.2f} | "
                  f"{r['off_line_per_min']:7.2f}")


if __name__ == "__main__":
    main()
