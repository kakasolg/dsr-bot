"""TAE verification — three levels kept apart (docs/tae-verify.md):

  1 parsed           tae_extract.py read the file; counts + judge numerator / denominator (tae.json). Says the reader
                     runs and p[2] lines up with BehaviorParam — not that times or ids mean what we think.
  2 independent tool the same animations read by DSAnimStudio: id, event type, start / end, params equal.
  3 runtime          in the game: the foe's animation id when the player is hit, and how long into it.

  python tae_verify.py sheet c2540 3000 3003 3008   level 2: what to compare in DSAnimStudio (seconds and 30 fps frames)
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
    """frames: [{t, hp, foes: [{ptr, npc, anim, d}]}] in time order. For each HP drop: the nearest foe within HIT_REACH
    whose current animation has a TAE attack window; its age = t − first frame of that animation (continuous).
    Resolution = the gap between frames (`dt`), reported per hit."""
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
            cands = []
            for f in sorted(fr["foes"], key=lambda f: f["d"]):
                m = models.get(f["npc"])
                if f["d"] > HIT_REACH or m not in tae["models"]:
                    continue
                w = windows(tae["models"][m]["animations"], f["anim"])
                if w:
                    cands.append((f, m, w))
            row = {"t": fr["t"], "lost": prev["hp"] - fr["hp"], "dt": round(fr["t"] - prev["t"], 4)}
            if not cands:
                row["status"] = "no_attacker"
                row["foes"] = [(f["npc"], f["anim"], f["d"]) for f in fr["foes"] if f["d"] <= HIT_REACH]
            else:
                f, m, w = cands[0]
                age = fr["t"] - start[f["ptr"]][1]
                first_seen_late = start[f["ptr"]][1] == frames[0]["t"]
                inside = [ev for ev in w if ev["start"] - row["dt"] <= age <= ev["end"] + row["dt"]]
                row.update({"npc": f["npc"], "model": m, "anim": f["anim"], "d": f["d"], "age": round(age, 4),
                            "windows": [(ev["start"], ev["end"]) for ev in w],
                            "status": "unknown_start" if first_seen_late else ("inside" if inside else "outside")})
            hits.append(row)
        prev = fr
    by = {}
    for h in hits:
        by[h["status"]] = by.get(h["status"], 0) + 1
    return {"frames": len(frames), "mean_dt": round((frames[-1]["t"] - frames[0]["t"]) / max(1, len(frames) - 1), 4) if frames else None,
            "hits": len(hits), "status": by, "rows": hits}


def probe(secs: float, out: Path, within: float = 8.0) -> None:
    """[win]: poll the game and write frames for `timing`. Read-only. Stand near a hollow and let it hit you
    (offline; `tm.set_dbg(tm.DBG_PLAYER_NO_DEAD, True)` first if you want to stay alive)."""
    import env
    tm = env.make_telemetry({})
    n = 0
    t_end = time.time() + secs
    with out.open("w", encoding="utf-8") as fh:
        while time.time() < t_end:
            s = tm.snapshot(within=within)
            if s is None:
                continue
            t = time.perf_counter()
            fh.write(json.dumps({"t": round(t, 4), "hp": s.player.hp, "foes": [
                {"ptr": c.ptr, "npc": c.npc_param, "anim": c.anim, "d": round(c.dist, 2)}
                for c in s.chars if c.hp > 0 and c.anim is not None]}) + "\n")
            n += 1
    print(f"{n} 프레임, {secs:.0f} s (평균 {secs / max(1, n) * 1000:.1f} ms) → {out}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("sheet"); p.add_argument("model"); p.add_argument("anims", nargs="+", type=int)
    p = sub.add_parser("blame"); p.add_argument("model", nargs="?")
    p = sub.add_parser("probe"); p.add_argument("secs", nargs="?", type=float, default=120.0)
    p = sub.add_parser("timing"); p.add_argument("file", type=Path)
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
    elif a.cmd == "timing":
        frames = [json.loads(l) for l in a.file.read_text(encoding="utf-8").splitlines() if l.strip()]
        r = timing(tae, combat, frames)
        for h in r["rows"]:
            print(h)
        print({k: v for k, v in r.items() if k != "rows"})


if __name__ == "__main__":
    main()
