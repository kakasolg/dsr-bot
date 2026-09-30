"""Walk replay harness, layer 1 (open loop) — recorded walks, perturbed hundreds of times, fed to the stop checks. No game.

  python walk_replay.py                                  data/samples/*.track.jsonl, 200 variants
  python walk_replay.py data/runs/x.track.jsonl -n 500   other files / more variants
  python walk_replay.py --window 1.5 2 3                 compare settings (one row each)
  python walk_replay.py --walks                          per-walk progress / lateral error / corners (no perturbation)
  python walk_replay.py --gate 0.8 0.9 0.95 -n 20        the 0.95 switching rule (walkgeom.Gate, release 1.0 m) on the
                                                         recorded walks; --release -1 0.5 1.0 compares release values

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
import math
import random
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
