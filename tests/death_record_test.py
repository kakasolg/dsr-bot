"""Death record: the black box splits fall damage from hits, and one "death" event per death (record only). No game.

  python tests/death_record_test.py

Why ([cloud] 2026-10-12, docs/analysis-death-2026-10-12.md): of 38 deaths in data/samples, 7 were falls and the black box
blamed a nearby foe for 4 of them (e.g. 20261012_003442: "254010 −669" — really −59 hit + −610 fall); `✝ 죽음` had no cause.
Frames here are the runs' own track snapshots (0.5 s) around each death.
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import json
import sys
import tempfile
import types
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import blackbox as BB
from souls import watch

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "data" / "samples"


def check(name: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        raise SystemExit(1)


def frames_of(run: str, t_from: float, t_to: float) -> list:
    out = []
    for line in open(SAMPLES / f"{run}.track.jsonl", encoding="utf-8"):
        d = json.loads(line)
        if d.get("type") == "snap" and t_from <= d["rt"] <= t_to and d.get("player"):
            p = d["player"]
            out.append({"t": d["rt"], "hp": p["hp"], "max": p["max_hp"], "anim": p["anim"], "pos": [p["x"], p["y"], p["z"]], "foes": []})
    return out


def bundle(frames: list) -> dict:
    """The hit bundle the black box would have made: from the first HP drop to the last one."""
    ep = None
    for a, b in zip(frames, frames[1:]):
        if b["hp"] < a["hp"]:
            if ep is None:
                ep = {"t0": b["t"], "hp0": a["hp"], "t_last": b["t"], "lo": b["hp"]}
            ep["t_last"], ep["lo"] = b["t"], min(ep["lo"], b["hp"])
    return ep


def main() -> None:
    # 10-12 zone 1 (P-71): −59 from 254010, pushed off the ledge, dead mid-air 10 m down
    fr = frames_of("20261012_003442_burg-upper", 76.0, 84.0)
    f = BB.fall_split(fr, bundle(fr))
    check(f"003442: fall, −59 hit + −610 fall ({f})", f is not None and f["lost_hit"] == 59 and f["lost_fall"] == 610 and f["drop_m"] >= 9.0)

    # 10-06a: slid off after a quit-out, −520 in 0 s with nobody swinging close — all fall
    fr = frames_of("burg-bonfire-2026-10-06a", 100.0, 106.0)
    f = BB.fall_split(fr, bundle(fr))
    check(f"10-06a: pure fall, no hit part ({f})", f is not None and f["lost_hit"] == 0 and f["lost_fall"] == 520)

    # zone 8 crossbowman death: hit to 0, the body slid 9 m afterwards — not a fall
    fr = frames_of("20261012_010457_burg-upper", 562.0, 569.0)
    check("010457: killed by hits, body slid after HP 0 → no fall", BB.fall_split(fr, bundle(fr)) is None)

    # an ordinary hit bundle on flat ground
    fr = frames_of("20261011_171918_burg-upper_p68fix-zone8-death", 500.0, 506.0)
    check("171918: flat-ground hits → no fall", BB.fall_split(fr, bundle(fr)) is None)

    # BlackBox end to end: frames in → "hit" event with the split, blame dropped for a pure fall, last_fatal for Blood
    with tempfile.TemporaryDirectory() as tmp:
        events, lines = [], []
        bb = BB.BlackBox(types.SimpleNamespace(), Path(tmp) / "run.jsonl", events=lambda ev, **k: events.append((ev, k)),
                         log=lines.append)
        foe = types.SimpleNamespace(team=6, hp=75, dist=1.0, x=0.0, y=0.0, z=0.0, npc_param=254000, ptr=1, anim=3000, heading=None)
        for fr in frames_of("burg-bonfire-2026-10-06a", 98.0, 106.0):
            p = types.SimpleNamespace(hp=fr["hp"], max_hp=fr["max"], anim=fr["anim"], sp=100, x=fr["pos"][0], y=fr["pos"][1], z=fr["pos"][2])
            bb.on_frame(types.SimpleNamespace(t=fr["t"], player=p, chars=[foe]))
        if bb._ep is not None:
            bb._close(bb._ep)
        bb._q.put(None)
        bb._writer()
        hit = [k for ev, k in events if ev == "hit"]
        check("hit event carries fall / drop_m / lost_fall, blame empty for a pure fall",
              hit and hit[-1].get("fall") is True and hit[-1]["lost_fall"] == 520 and hit[-1]["blame"] == [])
        check("log line says 낙하, not a foe", "낙하 -520" in lines[-1] and "254000" not in lines[-1])
        fatal = bb.take_fatal()
        check("take_fatal: cause fall, once", fatal and fatal["cause"] == "fall" and bb.take_fatal() is None)

    # Blood: one "death" event joining the stain, the death-moment context and the black box cause
    rows, log_lines = [], []

    class Log:                                             # run.py's Log: callable + .event
        def __call__(self, line):
            log_lines.append(line)

        def event(self, ev, **k):
            rows.append((ev, k))
    blood = watch.Blood(log=Log())
    blood.cause = lambda: {"cause": "fall", "lost_hit": 59, "lost_fall": 610, "drop_m": 10.1, "blame": [{"npc": 254010}], "n": 1}
    blood._death_event({"pos": [-11.07, -14.65, -65.3], "souls": 3114, "humanity": 1},
                       {"zone": "burg-upper:1", "escape": "busy", "since_fall_s": 11.0})
    ev, row = rows[-1]
    check("death event: cause, split, stain and context in one line",
          ev == "death" and row["cause"] == "fall" and row["lost_fall"] == 610 and row["souls"] == 3114 and row["zone"] == "burg-upper:1"
          and row["escape"] == "busy")
    check("death log line names the fall", log_lines and "낙하 10.1 m" in log_lines[-1] and "피격 -59" in log_lines[-1])
    blood.cause = lambda: None
    blood._death_event({"pos": [0, 0, 0], "souls": 10, "humanity": 0}, None)
    check("no black box → cause unknown", rows[-1][1]["cause"] == "unknown")
    print("death_record: all ok")


if __name__ == "__main__":
    main()
