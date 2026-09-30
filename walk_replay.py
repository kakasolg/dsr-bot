"""Walk replay harness, layer 1 (open loop) — recorded walks, perturbed hundreds of times, fed to the stop checks. No game.

  python walk_replay.py                                  data/samples/*.track.jsonl, 200 variants
  python walk_replay.py data/runs/x.track.jsonl -n 500   other files / more variants
  python walk_replay.py --window 1.5 2 3                 compare settings (one row each)
  python walk_replay.py --walks                          per-walk progress / lateral error / corners (no perturbation)

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
