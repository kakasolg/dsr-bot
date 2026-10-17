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


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("sheet"); p.add_argument("model"); p.add_argument("anims", nargs="+", type=int)
    p = sub.add_parser("blame"); p.add_argument("model", nargs="?")
    p = sub.add_parser("probe"); p.add_argument("secs", nargs="?", type=float, default=120.0)
    p = sub.add_parser("timing"); p.add_argument("file", type=Path)
    p = sub.add_parser("dsas"); p.add_argument("file", type=Path, nargs="?", default=ROOT / "data" / "gamefiles" / "tae_check_c2540_dsas.json")
    a = ap.parse_args()
    if a.cmd == "probe":
        out = SAMPLES / f"{time.strftime('%Y%m%d_%H%M%S')}_tae-probe.jsonl"
        probe(a.secs, out)
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


if __name__ == "__main__":
    main()
