"""One bot run → a replay file the Godot room plays back (MoKa M1109-55/56: replay a scene as a game, not as video).

  python sim/replay_extract.py 20261109_021816_burg-bonfire      → data/replays/<run>.json

Sources (all recorded during the run, nothing re-measured):
  data/radar/<session>.jsonl         radar_server recording: ~9 snapshots/s of the player and every character the
                                     telemetry sees — position, heading, HP, animation id — and the camera yaw
  data/runs/<run>.jsonl              run events: fights (duel: who, result, dealt / taken), group spots, estus, result
  data/runs/<run>.hits.jsonl         each big hit taken: when, HP before / lowest, which foe and its animation
  data/runs/<run>.ctl.jsonl          fight decisions (scene: the rule that fired and what it did)
  data/runs/<run>.track.jsonl        the bot's log lines ("say") with run time

Times in the replay are seconds since the run started (ctl header wall clock). Radar snapshots are what the bot read
from memory; between two snapshots (≈0.11 s) the room interpolates — a fast move inside that gap is not in the data.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "data" / "runs"
RADAR = ROOT / "data" / "radar"
OUT = ROOT / "data" / "replays"


def _lines(path: Path):
    if not path.exists():
        return
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def run_window(run: str) -> tuple[float, float]:
    """(start, end) wall clock seconds from the ctl header and its last sync record."""
    t0 = t1 = None
    for d in _lines(RUNS / f"{run}.ctl.jsonl"):
        if d.get("k") == "hdr":
            t0 = d["wall_ns"] / 1e9
        elif d.get("k") == "sync":
            t1 = d["wall1"] / 1e9
    if t0 is None:
        raise SystemExit(f"no ctl header for {run} (run with --ctl)")
    return t0, (t1 or t0 + 3600.0)


def radar_file(t0: float) -> Path:
    """The radar session that was recording at t0: the newest one whose first timestamp is ≤ t0."""
    best = None
    for f in sorted(RADAR.glob("*.jsonl")):
        with f.open(encoding="utf-8") as fh:
            for line in fh:
                i = line.find('"t": ')
                if i >= 0:
                    t = float(line[i + 5:line.index(",", i)])
                    if t <= t0:
                        best = f
                    break
    if best is None:
        raise SystemExit("no radar recording covers this run")
    return best


def frames(path: Path, t0: float, t1: float) -> tuple[list, dict]:
    """[{t, cam, p: [x, y, z, heading, anim, hp], c: {id: [...]}}], {id: {npc, team, max_hp}}. ids are small ints."""
    out, chars, ids = [], {}, {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            if '"chars"' not in line:
                continue
            i = line.find('"t": ')
            t = float(line[i + 5:line.index(",", i)])
            if t < t0:
                continue
            if t > t1:
                break
            d = json.loads(line)
            p = d["player"]
            fr = {"t": round(t - t0, 3), "cam": d.get("cam_yaw"), "p": _row(p), "c": {}}
            for c in d["chars"]:
                k = ids.setdefault(c["ptr"], len(ids))
                chars.setdefault(k, {"npc": c["npc"], "team": c["team"], "max_hp": c["max_hp"]})
                fr["c"][k] = _row(c)
            out.append(fr)
    return out, chars, ids


def _row(c: dict) -> list:
    return [round(c["x"], 3), round(c["y"], 3), round(c["z"], 3), round(c["heading"], 3), c["anim"], c["hp"]]


def events(run: str, t0: float, ids: dict) -> dict:
    fights, marks = [], []
    for d in _lines(RUNS / f"{run}.jsonl"):
        ev = d.get("ev")
        if ev == "duel":
            fights.append({"t_end": d["t"], "t": round(d["t"] - d.get("secs", 0.0), 2), "tag": d.get("tag", ""),
                           "npc": d.get("npc"), "result": d.get("result"), "dealt": d.get("dealt"),
                           "taken": d.get("taken"), "id": d.get("fight")})
        elif ev in ("group_spot", "estus", "roll", "break_out", "escape_pick", "wall_bounce", "result", "fog_cross"):
            marks.append({"t": d.get("t"), "ev": ev, **{k: v for k, v in d.items() if k in ("zone", "result", "near")}})
    hits = []
    for d in _lines(RUNS / f"{run}.hits.jsonl"):
        b = d.get("blame") or [{}]
        hits.append({"t": round(d["t0"] - t0, 2), "hp0": d["hp0"], "lo": d["lo"], "npc": b[0].get("npc"),
                     "id": ids.get(b[0].get("ptr")), "anim": b[0].get("anim"), "d": b[0].get("d")})
    rules = []
    for d in _lines(RUNS / f"{run}.ctl.jsonl"):
        if d.get("k") == "scene":
            rules.append({"t": round(d["t_wall"] - t0, 2), "rule": d.get("rule"), "out": d.get("out"),
                          "style": d.get("style")})
    says = [{"t": d["rt"], "line": d["line"]} for d in _lines(RUNS / f"{run}.track.jsonl") if d.get("type") == "say"]
    return {"fights": fights, "marks": marks, "hits": hits, "rules": rules, "says": says}


def extract(run: str) -> dict:
    t0, t1 = run_window(run)
    rf = radar_file(t0)
    fr, chars, ids = frames(rf, t0, t1)
    settings = RUNS / f"{run}.settings.json"
    st = json.loads(settings.read_text(encoding="utf-8")) if settings.exists() else {}
    return {"schema": "dsr-replay/1", "run": run, "radar": rf.name, "t0_wall": t0, "length": round(t1 - t0, 2),
            "map": "m10_01_00_00", "argv": st.get("argv"), "frames": fr,
            "chars": {str(k): v for k, v in chars.items()}, **events(run, t0, ids)}


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    run = sys.argv[1] if len(sys.argv) > 1 else "20261109_021816_burg-bonfire"
    d = extract(run)
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"{run}.json"
    out.write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    foes = sum(1 for c in d["chars"].values() if c["team"] == 6)
    print(f"{out.name}: {len(d['frames'])} frames over {d['length']} s from {d['radar']}, {len(d['chars'])} characters "
          f"({foes} hostile), {len(d['fights'])} fights, {len(d['hits'])} big hits, {len(d['rules'])} decisions, "
          f"{out.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
