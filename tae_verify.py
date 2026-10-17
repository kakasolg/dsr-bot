"""TAE verification — three levels kept apart (docs/tae-verify.md):

  1 parsed           tae_extract.py read the file; counts + judge numerator / denominator (tae.json). Says the reader
                     runs and p[2] lines up with BehaviorParam — not that times or ids mean what we think.
  2 independent tool the same animations read by DSAnimStudio: id, event type, start / end, params equal.
  3 runtime          in the game: the foe's animation id when the player is hit, and how long into it.

  python tae_verify.py sheet c2540 3000 3003 3008   level 2: what to compare in DSAnimStudio (seconds and 30 fps frames)
  python tae_verify.py dsas [tae_check_c2540_dsas.json]  level 2 re-check: tae.json vs DSAnimStudio's own reading
  python tae_verify.py blame [c2540]                level 3a: recorded hits (data/samples `hit` events) — was the
                                                    hitting foe's animation one with a TAE attack event? (ids only)
  python tae_verify.py probe [secs]                 level 3b, [win], game running: record player HP + nearby foes'
                                                    animation ids as fast as memory reads go → data/samples/<time>_tae-probe.jsonl
  python tae_verify.py timing <probe.jsonl>         level 3b, offline: each HP drop vs the hitting foe's animation age
                                                    and its TAE active window
  python tae_verify.py probe3 [secs] [--refill 150 793]  probe 3, [win]: c2540 3000 only, one isolated hollow — short
                                                    pre-record + automatic pre-check, then the real record
  python tae_verify.py check3 <probe3.jsonl> [--anim 3001]  probe 3, offline: samples, valid, exclusion reasons, match / mismatch

Names: TAE times are the "active window" (`active_start` / `active_end`, when the attack behavior runs). The time the
player's HP drops is the "hit time". The two are compared here, never merged.
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).parent
TAE = ROOT / "data" / "gamefiles" / "tae.json"
COMBAT = ROOT / "data" / "gamefiles" / "combat.json"
SAMPLES = ROOT / "data" / "samples"
FPS = 30
TYPE_NAME = {1: "attack", 2: "bullet", 5: "common"}
HIT_REACH = 4.0          # a foe further than this is not blamed for an HP drop (m)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def npc_models(combat: dict) -> dict[int, str]:
    return {int(k): f["model"] for k, f in combat["foes"].items() if f.get("model")}


def resolve(anims: dict, anim: int) -> dict | None:
    """The animation entry, following a borrowed one (`ref`) once."""
    a = anims.get(str(anim))
    if a is not None and not a["events"] and a.get("ref") is not None:
        return anims.get(str(a["ref"]), a)
    return a


def windows(anims: dict, anim: int, types=(1, 2)) -> list[dict]:
    a = resolve(anims, anim)
    return [] if a is None else [ev for ev in a["events"] if ev["type"] in types]


# ── level 2: DSAnimStudio sheet ──
def sheet(model: dict, anim_ids: list[int]) -> list[str]:
    out = []
    for aid in anim_ids:
        a = model["animations"].get(str(aid))
        if a is None:
            out.append(f"{aid}: TAE에 없음")
            continue
        ref = f" (빌림 → {a['ref']})" if a.get("ref") is not None else ""
        other = ", ".join(f"type {t} ×{n}" for t, n in a["other_types"].items())
        out.append(f"── {model['model']} 애니 {aid} [{a.get('tae', '')}]{ref} — 그 밖 이벤트: {other or '없음'}")
        for ev in a["events"]:
            out.append(f"   type {ev['type']} {TYPE_NAME.get(ev['type'], '?'):6} {ev['start']:.4f}–{ev['end']:.4f} s"
                       f"  = 프레임 {ev['start'] * FPS:.1f}–{ev['end'] * FPS:.1f}  p={ev['p']}")
        if not a["events"]:
            out.append("   (공격·투사체·공통 이벤트 없음)")
    return out


def _num(v):
    """DSAnimStudio's dump writes param values as text ("300")."""
    try:
        return int(v)
    except (TypeError, ValueError):
        return v


def dsas_compare(model: dict, dsas: dict, tol: float = 5e-5) -> dict:
    """Level 2 re-check against DSAnimStudio's own reading (tae_check_<model>_dsas.json, collected by [win] with
    experiments/dsas_tae.ps1). Per animation: total event count, other-type counts, and every kept event (type, start,
    end within `tol` — ours is rounded to 4 decimals —, params in template order). Returns rows + every difference."""
    rows, diffs = [], []
    for an in dsas["anims"]:
        aid, theirs = an["anim"], an["events"]
        ours = model["animations"].get(str(aid))
        if ours is None:
            diffs.append({"anim": aid, "what": "missing in tae.json"})
            continue
        n_ours = len(ours["events"]) + sum(ours["other_types"].values())
        if n_ours != len(theirs):
            diffs.append({"anim": aid, "what": "event count", "ours": n_ours, "theirs": len(theirs)})
        other_theirs: dict[str, int] = {}
        for e in theirs:
            if e["type"] not in TYPE_NAME:
                other_theirs[str(e["type"])] = other_theirs.get(str(e["type"]), 0) + 1
        if other_theirs != ours["other_types"]:
            diffs.append({"anim": aid, "what": "other types", "ours": ours["other_types"], "theirs": other_theirs})
        kept = sorted((e for e in theirs if e["type"] in TYPE_NAME), key=lambda e: (round(e["start"], 4), e["type"]))
        if len(kept) != len(ours["events"]):
            diffs.append({"anim": aid, "what": "kept count", "ours": len(ours["events"]), "theirs": len(kept)})
        for o, t in zip(ours["events"], kept):
            vals = [_num(v) for v in t["params"].values()]
            for what, ok in (("type", o["type"] == t["type"]),
                             ("start", abs(o["start"] - t["start"]) <= tol),
                             ("end", abs(o["end"] - t["end"]) <= tol),
                             ("params", o["p"] == vals)):
                if not ok:
                    diffs.append({"anim": aid, "what": what, "ours": o, "theirs": {k: t[k] for k in ("type", "start", "end", "params")}})
        rows.append({"anim": aid, "events": len(theirs), "kept": len(kept)})
    return {"rows": rows, "diffs": diffs, "pass": not diffs}


# ── level 3a: animation ids of recorded hits ──
def blame_check(tae: dict, combat: dict, hit_rows: list[dict], model_filter: str | None = None) -> dict:
    """hit_rows: `hit` events ({blame: [{npc, anim, d}]}). Every blamed (npc, anim) → has a TAE attack/bullet event?"""
    models = npc_models(combat)
    kinds: dict[str, int] = {}
    samples: dict[str, dict] = {}
    for h in hit_rows:
        for b in h.get("blame", []):
            m = models.get(b.get("npc"))
            if model_filter and m != model_filter:
                continue
            if m is None or m not in tae["models"]:
                k = "no_model"
            elif resolve(tae["models"][m]["animations"], b.get("anim")) is None:
                k = "anim_not_in_tae"
            elif windows(tae["models"][m]["animations"], b.get("anim")):
                k = "attack_anim"
            else:
                k = "no_attack_event"
            kinds[k] = kinds.get(k, 0) + 1
            key = f"{b.get('npc')}/{m}/{b.get('anim')}"
            s = samples.setdefault(k, {})
            s[key] = s.get(key, 0) + 1
    total = sum(kinds.values())
    return {"rows": total, "kinds": kinds, "attack_share": round(kinds.get("attack_anim", 0) / total, 3) if total else None,
            "samples": {k: dict(sorted(v.items(), key=lambda kv: -kv[1])[:12]) for k, v in samples.items()}}


def hit_rows_from_samples(folder: Path = SAMPLES) -> list[dict]:
    rows = []
    for f in sorted(glob.glob(str(folder / "*.jsonl"))):
        if f.endswith((".track.jsonl", ".ctl.jsonl")):
            continue
        for line in open(f, encoding="utf-8"):
            if '"ev": "hit"' in line:
                rows.append(json.loads(line))
    return rows


# ── level 3b: timing from a probe recording ──
def timing(tae: dict, combat: dict, frames: list[dict]) -> dict:
    """frames: [{t, dt?, hp, foes: [{ptr, npc, anim, d}]}] in time order. For each HP drop: the nearest foe within
    HIT_REACH whose current animation has a TAE attack window; its age = t − first frame of that animation (continuous).
    Resolution `dt` = the read interval before that frame (the probe writes it; old recordings: gap to the previous line).
    Statuses: inside / outside the active window (± dt) · unknown_start (animation already running when recording began)
    · anim_unknown (a foe in reach reads anim −1 — asleep / not loaded) · no_attacker (nobody in reach with an attack)."""
    models = npc_models(combat)
    start: dict[int, tuple[int, float]] = {}       # ptr → (anim, first t seen)
    hits = []
    prev = None
    for fr in frames:
        for f in fr["foes"]:
            s = start.get(f["ptr"])
            if s is None or s[0] != f["anim"]:
                start[f["ptr"]] = (f["anim"], fr["t"])
        if prev is not None and fr["hp"] < prev["hp"]:
            near = [f for f in sorted(fr["foes"], key=lambda f: f["d"]) if f["d"] <= HIT_REACH]
            cands = []
            for f in near:
                m = models.get(f["npc"])
                if m in tae["models"]:
                    w = windows(tae["models"][m]["animations"], f["anim"])
                    if w:
                        cands.append((f, m, w))
            dt = fr.get("dt", fr["t"] - prev["t"])
            row = {"t": fr["t"], "lost": prev["hp"] - fr["hp"], "dt": round(dt, 4)}
            if not cands:
                row["status"] = "anim_unknown" if any(f["anim"] in (None, -1) for f in near) else "no_attacker"
                row["foes"] = [(f["npc"], f["anim"], f["d"]) for f in fr["foes"]]
            else:
                f, m, w = cands[0]
                age = fr["t"] - start[f["ptr"]][1]
                first_seen_late = start[f["ptr"]][1] == frames[0]["t"]
                inside = [ev for ev in w if ev["start"] - dt <= age <= ev["end"] + dt]
                row.update({"npc": f["npc"], "model": m, "anim": f["anim"], "d": f["d"], "age": round(age, 4),
                            "windows": [(ev["start"], ev["end"]) for ev in w],
                            "status": "unknown_start" if first_seen_late else ("inside" if inside else "outside")})
            hits.append(row)
        prev = fr
    by = {}
    for h in hits:
        by[h["status"]] = by.get(h["status"], 0) + 1
    dts = [fr["dt"] for fr in frames if "dt" in fr]
    return {"frames": len(frames), "mean_dt": round(sum(dts) / len(dts), 4) if dts else (
        round((frames[-1]["t"] - frames[0]["t"]) / max(1, len(frames) - 1), 4) if frames else None),
            "hits": len(hits), "status": by, "rows": hits}


def frame_key(hp: int, foes: list[dict]) -> tuple:
    """What makes a frame worth writing: HP, and each foe's (ptr, anim). Distance alone does not (heartbeat lines do)."""
    return hp, tuple(sorted((f["ptr"], f["anim"]) for f in foes))


def probe(secs: float, out: Path, within: float = 25.0, heartbeat: float = 0.5, say_every: float = 5.0) -> None:
    """[win]: read the game directly (not env.make_telemetry — that is the background feed, whose snapshot is cached:
    probe 1 wrote the same frame 16.9 M times) and write a line when HP or any foe's animation changes, plus one every
    `heartbeat` s. Each line has `dt` = the read interval before it (the timing resolution). Read-only.
    Every `say_every` s it prints the nearby foes' animations — anim −1 = asleep / not loaded, wake it first."""
    import dsr_telemetry
    tm = dsr_telemetry.DSRTelemetry({})
    n = written = 0
    last_key, last_write, last_say, last_read = None, 0.0, 0.0, None
    t_end = time.perf_counter() + secs
    with out.open("w", encoding="utf-8") as fh:
        while (now := time.perf_counter()) < t_end:
            s = tm.snapshot(within=within)
            if s is None:
                continue
            t = time.perf_counter()
            dt = t - last_read if last_read is not None else 0.0
            last_read = t
            n += 1
            foes = [{"ptr": c.ptr, "npc": c.npc_param, "anim": c.anim, "d": round(c.dist, 2)}
                    for c in s.chars if c.hp > 0 and c.team not in (0, 1)]
            key = frame_key(s.player.hp, foes)
            if key != last_key or t - last_write >= heartbeat:
                fh.write(json.dumps({"t": round(t, 4), "dt": round(dt, 4), "hp": s.player.hp, "foes": foes}) + "\n")
                written += 1
                last_key, last_write = key, t
            if t - last_say >= say_every:
                print(f"{secs - (t_end - now):5.0f}s  hp {s.player.hp}  " +
                      "  ".join(f"{f['npc']}:{f['anim']}@{f['d']}m" for f in foes[:4]), flush=True)
                last_say = t
    print(f"읽기 {n}번 ({secs / max(1, n) * 1000:.1f} ms 마다), 기록 {written}줄 → {out}")


# ── level 3b, probe 3: one attack (c2540 3000) on one isolated hollow (docs/tae-verify.md B-4, MoKa 10-17) ──
# The attacker is fixed by the setup (one target, nobody else near), never by whether the hit fits a TAE window. No memory
# value for the animation's play position is known, so "age" = time since the ID was first observed (`age_since_seen`),
# with both ends bounded by reads: the ID changed between two reads, the HP dropped between two reads.
P3_ANIM = 3000
P3_TARGET = (254010,)   # c2540 sword hollow
ISO_R = 25.0            # any other living foe this close (prev or this read) → ambiguous (m)
ATTRIB_R = 6.0          # the target farther than this cannot have hit — an attribution sanity bound, not a reach measurement
MAX_GAP = 0.02          # a read bound wider than this is too coarse (s)
TOL = 1 / 30            # allowance each side of the active window (one game frame), reported with every row
RESTART_FACTOR = 1.5    # a 3000 run longer than this × the median closed run → a same-ID restart cannot be ruled out
N_MIN = 10              # valid samples needed before "pass" (proposal)
HP_MIN = 200            # pre-check: HP must stay above this (NoDead clamps at 1 and hides hits)
MAX_LINES = 100_000     # record cap (lines); the recorder stops at it
DBG_ALLOWED = {"PlayerNoDead"}   # other CHR DBG flags fail the pre-check: their effect is not assumed from the name


def dbg_names() -> dict[int, str]:
    """ChrDbg byte offset → the game's menu label (dsr_telemetry DBG_* constants)."""
    import dsr_telemetry
    out = {}
    for k, v in vars(dsr_telemetry.DSRTelemetry).items():
        if k.startswith("DBG_"):
            out[v] = "".join(w.capitalize() for w in k[4:].split("_")).replace("Mp", "MP")
    return out


def dbg_on(hexs: str | None) -> list[str]:
    if not hexs:
        return []
    names = dbg_names()
    return [names.get(i, f"+0x{i:X}") for i, b in enumerate(bytes.fromhex(hexs)) if b]


def _bounds(prev: dict | None, fr: dict) -> tuple[float, float]:
    """(lo, hi): a change seen in `fr` happened after the previous read began and before this read ended.
    probe3 lines carry `pt0` (previous read's start); older lines only `dt` or the previous line's time."""
    if "pt0" in fr:
        return fr["pt0"], fr["t"]
    if "dt" in fr and fr["dt"] > 0:
        return fr["t"] - fr["dt"], fr["t"]
    return (prev["t"] if prev else fr["t"]), fr["t"]


def _frames(lines: list[dict]) -> tuple[dict, list[dict]]:
    head = next((l for l in lines if l.get("kind") == "header"), {})
    return head, [l for l in lines if "kind" not in l]


def _near(fr: dict, iso_r: float, target: tuple) -> tuple[list[dict], list[dict]]:
    """(targets, others) within iso_r; friendly NPCs (dsr_telemetry.FRIENDLY) never attack and are left out."""
    from dsr_telemetry import FRIENDLY
    fs = [f for f in fr["foes"] if f["d"] <= iso_r and f["npc"] not in FRIENDLY]
    return [f for f in fs if f["npc"] in target], [f for f in fs if f["npc"] not in target]


def anim_runs(frames: list[dict]) -> dict[int, list[dict]]:
    """Per foe ptr: runs of one animation ID — {anim, i0, i1 (frame index range), start (lo, hi) | None if the run began
    before the ptr was first seen, end (lo, hi) | None if still running at the end of the recording}."""
    runs: dict[int, list[dict]] = {}
    gone = object()
    last: dict = {}
    for i, fr in enumerate(frames):
        prev = frames[i - 1] if i else None
        here = {f["ptr"]: f["anim"] for f in fr["foes"]}
        for ptr in set(here) | set(last):
            a, b = last.get(ptr, gone), here.get(ptr, gone)
            if a == b:
                continue
            rs = runs.setdefault(ptr, [])
            if a is not gone:       # left the list (died, out of range): the run stops being seen, its end is unknown
                rs[-1].update(i1=i, end=_bounds(prev, fr) if b is not gone else None)
            if b is not gone:
                rs.append({"anim": b, "i0": i, "i1": None, "start": _bounds(prev, fr) if a is not gone else None, "end": None})
        last = here
    return runs


def _run_at(runs: list[dict], i: int) -> dict | None:
    return next((r for r in runs if r["i0"] <= i and (r["i1"] is None or i < r["i1"])), None)


def timing3(tae: dict, combat: dict, lines: list[dict], anim: int = P3_ANIM, target: tuple = P3_TARGET,
            iso_r: float = ISO_R, tol: float = TOL, n_min: int = N_MIN) -> dict:
    """Every HP drop is a sample. Valid only if: the target is the one living foe within iso_r in this and the previous
    read, within ATTRIB_R, in `anim` at both reads, the run's start was seen with both read bounds ≤ MAX_GAP, the drop's
    own bound ≤ MAX_GAP, the run ended inside the recording, is the only drop of its run, has no HP refill / HP floor in
    it, and is not long enough to hide a same-ID restart. Valid → age_since_seen interval vs the TAE active window ± tol:
    match / mismatch (with the offset). Speed, reach, guard and damage are not part of the verdict."""
    head, frames = _frames(lines)
    models = npc_models(combat)
    w = [(ev["start"], ev["end"]) for ev in windows(tae["models"][models[target[0]]]["animations"], anim, (1,))]
    runs = anim_runs(frames)
    closed = [(p, r) for p, rs in runs.items() for r in rs if r["anim"] == anim and r["start"] and r["end"]]
    lens = sorted((r["end"][0] + r["end"][1] - r["start"][0] - r["start"][1]) / 2 for _p, r in closed)
    median = lens[len(lens) // 2] if lens else None
    hits, base = [], None
    for i, fr in enumerate(frames):
        prev = frames[i - 1] if i else None
        if prev is None or base is None or fr["hp"] >= base:
            base = fr.get("refill", fr["hp"])
            continue
        lo, hi = _bounds(prev, fr)
        row = {"t": fr["t"], "lost": base - fr["hp"], "obs": [round(lo, 4), round(hi, 4)], "obs_width": round(hi - lo, 4)}
        base = fr.get("refill", fr["hp"])
        why = []
        tg, ot = _near(fr, iso_r, target)
        ptg, pot = _near(prev, iso_r, target)
        if not tg:
            why.append("no_target")
        if len(tg) > 1 or len(ptg) > 1 or ot or pot:
            why.append("not_isolated")
            row["others"] = sorted({(f["npc"], f["d"]) for f in ot + pot + tg[1:] + ptg[1:]})
        if tg:
            f = tg[0]
            pf = next((p for p in prev["foes"] if p["ptr"] == f["ptr"]), None)
            r = _run_at(runs.get(f["ptr"], []), i)
            row.update(npc=f["npc"], d=f["d"], anim=f["anim"])
            if f["d"] > ATTRIB_R:
                why.append("target_far")
            if pf is None or pf["anim"] != f["anim"]:
                why.append("anim_changed_in_interval")
            if f["anim"] in (None, -1):
                why.append("anim_unknown")
            elif f["anim"] != anim:
                why.append("other_anim")
            elif r is None or r["start"] is None:
                why.append("start_unseen")
            else:
                row["start_obs"] = [round(r["start"][0], 4), round(r["start"][1], 4)]
                if r["start"][1] - r["start"][0] > MAX_GAP:
                    why.append("start_gap")
                if r["end"] is None:
                    why.append("run_open")
                else:
                    ln = (r["end"][0] + r["end"][1] - r["start"][0] - r["start"][1]) / 2
                    row["run_len"] = round(ln, 4)
                    if median is None or len(lens) < 3:
                        why.append("restart_unchecked")
                    elif ln > RESTART_FACTOR * median:
                        why.append("restart_possible")
                seg = frames[r["i0"]:(r["i1"] if r["i1"] is not None else len(frames))]
                if any("refill" in s for s in seg):      # a hit between the read and the refill write would be hidden
                    why.append("refill_in_run")
                if any(s["hp"] <= 1 for s in seg) or prev["hp"] <= 1:
                    why.append("hp_floor_in_run")
                row["run"] = (f["ptr"], r["i0"])
        if hi - lo > MAX_GAP:
            why.append("obs_gap")
        row["reasons"] = why
        if not why:
            a_lo, a_hi = lo - r["start"][1], hi - r["start"][0]
            row["age_since_seen"] = [round(a_lo, 4), round(a_hi, 4)]
            row["windows"] = w
            fits = [(s, e) for s, e in w if a_hi >= s - tol and a_lo <= e + tol]
            row["status"] = "match" if fits else "mismatch"
            if not fits:
                s, e = min(w, key=lambda se: min(abs(a_lo - se[1]), abs(a_hi - se[0])))
                row["offset"] = round(a_lo - (e + tol), 4) if a_lo > e + tol else round(a_hi - (s - tol), 4)
        hits.append(row)
    per_run: dict = {}
    for h in hits:
        if "run" in h:
            per_run.setdefault(h["run"], []).append(h)
    for hs in per_run.values():
        if len(hs) > 1:
            for h in hs:
                h["reasons"].append("multi_hit_in_run")
                h.pop("status", None), h.pop("offset", None)
    hit_runs = set(per_run)
    excluded: dict[str, int] = {}
    for h in hits:
        if h["reasons"]:
            h["status"] = "excluded:" + h["reasons"][0]
            excluded[h["reasons"][0]] = excluded.get(h["reasons"][0], 0) + 1
        h.pop("run", None)
    valid = [h for h in hits if not h["reasons"]]
    match = [h for h in valid if h["status"] == "match"]
    mismatch = [h for h in valid if h["status"] == "mismatch"]
    verdict = ("불일치" if mismatch else "통과" if len(valid) >= n_min else "표본 부족")
    widths = sorted(h["obs_width"] for h in hits)
    dbgs = sorted({fr.get("dbg") for fr in frames if fr.get("dbg")})
    return {"anim": anim, "target": list(target), "windows": w, "tol": round(tol, 4), "iso_r": iso_r,
            "age": "age_since_seen = time since the animation ID was first observed (play position not read)",
            "frames": len(frames), "samples": len(hits), "valid": len(valid), "excluded": excluded,
            "match": len(match), "mismatch": len(mismatch), "verdict": verdict, "n_min": n_min,
            "obs_width": {"median": widths[len(widths) // 2], "max": widths[-1]} if widths else None,
            "runs": {"closed": len(closed), "median_len": round(median, 4) if median else None,
                     "without_hit": sum(1 for p, r in closed if (p, r["i0"]) not in hit_runs)},
            "dbg": {d: dbg_on(d) for d in dbgs}, "header": head,
            "rows_match": match, "rows_mismatch": mismatch, "rows_excluded": [h for h in hits if h["reasons"]]}


def precheck(lines: list[dict], secs: float, plan_secs: float, target: tuple = P3_TARGET, iso_r: float = ISO_R,
             max_lines: int = MAX_LINES, hp_min: int = HP_MIN, allow: set = DBG_ALLOWED) -> dict:
    """Short pre-record, checked automatically before the real one: HP, target state, isolation, the new reads
    (read bounds, CHR DBG flags), and the record size for plan_secs."""
    head, frames = _frames(lines)
    checks = []

    def add(name, ok, detail):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    hps = [fr["hp"] for fr in frames]
    add("hp", frames and min(hps) >= hp_min, f"min {min(hps) if hps else None} (≥ {hp_min}; NoDead holds HP at 1 and hides hits)")
    tcount = [len(_near(fr, iso_r, target)[0]) for fr in frames]
    anims = [f["anim"] for fr in frames for f in _near(fr, iso_r, target)[0]]
    add("target_one", frames and all(c == 1 for c in tcount), f"target {target} within {iso_r} m per read: {sorted(set(tcount))}")
    add("target_awake", any(a not in (None, -1) for a in anims) and len(set(anims)) >= 2,
        f"anims seen {sorted(set(a for a in anims if a is not None))[:12]} (−1 = asleep: wake it; one ID only = not acting)")
    others = sorted({(f["npc"], round(f["d"], 1)) for fr in frames for f in _near(fr, iso_r, target)[1]})
    add("isolated", not others, f"other foes within {iso_r} m: {others[:10]}")
    ok_reads = all("t0" in fr and "pt0" in fr and fr["pt0"] <= fr["t0"] <= fr["t"] for fr in frames)
    gaps = sorted(fr["t"] - fr["pt0"] for fr in frames if "pt0" in fr)
    add("read_bounds", ok_reads and gaps and gaps[len(gaps) // 2] <= MAX_GAP,
        f"pt0 ≤ t0 ≤ t on every line: {ok_reads}; bound median {round(gaps[len(gaps) // 2], 4) if gaps else None} s (≤ {MAX_GAP})")
    dbgs = sorted({fr.get("dbg") for fr in frames})
    bad = sorted({n for d in dbgs if d for n in dbg_on(d)} - set(allow))
    add("dbg_flags", None not in dbgs and len(dbgs) == 1 and not bad,
        f"CHR DBG read {dbgs} → on {[dbg_on(d) for d in dbgs if d]}; not allowed {bad} (check their effect first, then --allow)")
    est = len(frames) / max(secs, 1e-6) * plan_secs
    add("volume", est <= max_lines, f"{len(frames)} lines in {secs} s → ~{est:.0f} for {plan_secs} s (cap {max_lines})")
    return {"ok": all(c["ok"] for c in checks), "checks": checks, "header": head}


def record3(tm, secs: float, out: Path, header: dict, within: float = ISO_R, heartbeat: float = 0.5,
            refill: tuple[int, int] | None = None, max_lines: int = MAX_LINES, say_every: float = 5.0) -> dict:
    """[win]: like `probe`, plus each line's read bounds (`t0` start, `t` end, `pt0` previous read's start), the 16 CHR DBG
    bytes (`dbg`, hex), and the HP refill this recorder did itself (`refill`: the value written after this read).
    Writes on HP / foe anim / flag change + heartbeat; stops at max_lines. Writes nothing but HP (refill, offline)."""
    n = written = 0
    last_key, last_write, last_say, pt0 = None, 0.0, 0.0, None
    t_end = time.perf_counter() + secs
    stopped = "secs"
    with out.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"kind": "header", **header}) + "\n")
        while time.perf_counter() < t_end:
            t0 = time.perf_counter()
            s = tm.snapshot(within=within)
            if s is None:
                continue
            dbg = tm.pm.read_bytes(tm.static["ChrDbg"], 16).hex()
            t = time.perf_counter()
            n += 1
            foes = [{"ptr": c.ptr, "npc": c.npc_param, "anim": c.anim, "d": round(c.dist, 2)}
                    for c in s.chars if c.hp > 0 and c.team not in (0, 1)]
            line = {"t0": round(t0, 5), "t": round(t, 5), "pt0": round(pt0 if pt0 is not None else t0, 5),
                    "hp": s.player.hp, "foes": foes, "dbg": dbg}
            pt0 = t0
            if refill and s.player.hp < refill[0]:
                tm.set_hp(refill[1])
                line["refill"] = refill[1]
            key = (frame_key(s.player.hp, foes), dbg)
            if key != last_key or t - last_write >= heartbeat or "refill" in line:
                fh.write(json.dumps(line) + "\n")
                written += 1
                last_key, last_write = key, t
                if written >= max_lines:
                    stopped = "max_lines"
                    break
            if t - last_say >= say_every:
                print(f"hp {s.player.hp}  " + "  ".join(f"{f['npc']}:{f['anim']}@{f['d']}m" for f in foes[:4]), flush=True)
                last_say = t
        fh.write(json.dumps({"kind": "end", "reads": n, "written": written, "stopped": stopped}) + "\n")
    return {"reads": n, "written": written, "stopped": stopped}


def probe3(secs: float, pre: float, refill: tuple[int, int] | None, allow: set, force: bool, max_lines: int) -> None:
    """[win]: pre-record `pre` s → precheck → only if every check passes (or --force) the real record.
    Refill threshold: ≥ HP_MIN + the foe's biggest hit (c2540: 181 → 400, probe 3), or the hp check fails."""
    import dsr_telemetry
    tm = dsr_telemetry.DSRTelemetry({})
    stamp = time.strftime('%Y%m%d_%H%M%S')
    header = {"probe": 3, "anim": P3_ANIM, "target": list(P3_TARGET), "iso_r": ISO_R, "refill": refill,
              "age": "age_since_seen (play position not read)"}
    pre_out = SAMPLES / f"{stamp}_tae-probe3-pre.jsonl"
    record3(tm, pre, pre_out, {**header, "pre": True}, refill=refill, max_lines=max_lines)
    pc = precheck([json.loads(l) for l in pre_out.read_text(encoding="utf-8").splitlines() if l.strip()],
                  pre, secs, max_lines=max_lines, allow=DBG_ALLOWED | allow)
    for c in pc["checks"]:
        print(f"  {'OK ' if c['ok'] else 'FAIL'} {c['check']:13} {c['detail']}")
    if not pc["ok"] and not force:
        print(f"예비 점검 실패 — 본 기록 안 함 ({pre_out}). 고치고 다시, 또는 --force (그 기록은 판정에 못 씀).")
        return
    out = SAMPLES / f"{stamp}_tae-probe3.jsonl"
    r = record3(tm, secs, out, {**header, "precheck": pc["checks"], "forced": not pc["ok"]}, refill=refill, max_lines=max_lines)
    print(f"읽기 {r['reads']}번, 기록 {r['written']}줄 ({r['stopped']}) → {out}\n다음: python tae_verify.py check3 {out}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("sheet"); p.add_argument("model"); p.add_argument("anims", nargs="+", type=int)
    p = sub.add_parser("blame"); p.add_argument("model", nargs="?")
    p = sub.add_parser("probe"); p.add_argument("secs", nargs="?", type=float, default=120.0)
    p = sub.add_parser("timing"); p.add_argument("file", type=Path)
    p = sub.add_parser("probe3"); p.add_argument("secs", nargs="?", type=float, default=120.0)
    p.add_argument("--pre", type=float, default=5.0); p.add_argument("--refill", type=int, nargs=2, metavar=("BELOW", "TO"))
    p.add_argument("--allow", nargs="*", default=[]); p.add_argument("--force", action="store_true")
    p.add_argument("--max-lines", type=int, default=MAX_LINES)
    p = sub.add_parser("check3"); p.add_argument("file", type=Path); p.add_argument("--pre", action="store_true")
    p.add_argument("--anim", type=int, default=P3_ANIM)
    p = sub.add_parser("dsas"); p.add_argument("file", type=Path, nargs="?", default=ROOT / "data" / "gamefiles" / "tae_check_c2540_dsas.json")
    a = ap.parse_args()
    if a.cmd == "probe":
        out = SAMPLES / f"{time.strftime('%Y%m%d_%H%M%S')}_tae-probe.jsonl"
        probe(a.secs, out)
        return
    if a.cmd == "probe3":
        probe3(a.secs, a.pre, tuple(a.refill) if a.refill else None, set(a.allow), a.force, a.max_lines)
        return
    tae, combat = load(TAE), load(COMBAT)
    if a.cmd == "sheet":
        print("\n".join(sheet(tae["models"][a.model], a.anims)))
    elif a.cmd == "blame":
        print(json.dumps(blame_check(tae, combat, hit_rows_from_samples(), a.model), ensure_ascii=False, indent=1))
    elif a.cmd == "dsas":
        d = load(a.file)
        model = d["files"][0]["name"].replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0]
        r = dsas_compare(tae["models"][model], d)
        print(json.dumps(r, ensure_ascii=False, indent=1))
        print(f"{model}: {'통과' if r['pass'] else '다름'} — 애니 {len(r['rows'])}, 차이 {len(r['diffs'])}")
    elif a.cmd == "timing":
        frames = [json.loads(l) for l in a.file.read_text(encoding="utf-8").splitlines() if l.strip()]
        r = timing(tae, combat, frames)
        for h in r["rows"]:
            print(h)
        print({k: v for k, v in r.items() if k != "rows"})
    elif a.cmd == "check3":
        lines = [json.loads(l) for l in a.file.read_text(encoding="utf-8").splitlines() if l.strip()]
        if a.pre:
            for c in precheck(lines, 0, 0)["checks"]:
                print(f"  {'OK ' if c['ok'] else 'FAIL'} {c['check']:13} {c['detail']}")
            return
        r = timing3(tae, combat, lines, anim=a.anim)
        for k in ("rows_match", "rows_mismatch", "rows_excluded"):
            print(f"── {k} ({len(r[k])})")
            for h in r[k]:
                print(" ", h)
        print(json.dumps({k: v for k, v in r.items() if not k.startswith("rows_")}, ensure_ascii=False, indent=1))
        print(f"{r['anim']}: {r['verdict']} — 표본 {r['samples']}, 유효 {r['valid']} (일치 {r['match']} · 불일치 {r['mismatch']}), "
              f"제외 {r['excluded']}")


if __name__ == "__main__":
    main()
