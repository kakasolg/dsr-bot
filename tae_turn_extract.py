"""Turning and flag events of foe attack animations (cloud request 11-16, c4a93727 item 1) → data/gamefiles/tae_turn.json.

    python tae_turn_extract.py [c2540 c2550 c2560 …]

Per model, per attack animation 3000–3999 of every TAE section (a00 = id, a01 = 10000 + id, a02 = 20000 + id — some NPCs
play a01/a02, see parry_drill.SECTION): hit windows (type 1), SetTurnSpeed (type 224, p[0] read as f32), and every
ChrActionFlag (type 0, flag = p[0]) with start/end. Flag names as player_tae_extract.FLAG_NAMES (7 "disable turning",
73 "parry possible" …) — names come from DSAnimStudio's DS1 template, meaning not checked in game ("file" evidence).
Kept as its own file so tae.json (the bot's hit table) does not change shape.
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

import player_tae_extract as P
import tae_extract as TE
from navmesh import GAME_DIR

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

OUT = Path(__file__).resolve().parent / "data" / "gamefiles" / "tae_turn.json"


def model_events(model: str) -> dict:
    from soulstruct.containers import Binder
    P._patch()
    out = {}
    for f in sorted((GAME_DIR / "chr").glob(f"{model}*.anibnd.dcx")):
        for ent in Binder.from_path(f).entries:
            if not ent.name.lower().endswith(".tae"):
                continue
            sec = P.section_of(ent.name) or 0
            for aid, a in TE.read_tae(bytes(ent.data))["animations"].items():
                if not 3000 <= aid % 10000 < 4000:
                    continue
                full = aid if aid >= 10000 else sec * 10000 + aid
                hit, turn, flags = [], [], []
                for ev in a["events"]:
                    s, e = ev["start"], ev["end"]
                    if ev["type"] == 1:
                        hit.append([s, e])
                    elif ev["type"] == 224 and ev["p"]:
                        turn.append([s, e, round(struct.unpack("<f", struct.pack("<i", ev["p"][0]))[0], 4)])
                    elif ev["type"] == 0 and ev["p"]:
                        flags.append([s, e, ev["p"][0]])
                if hit or turn or flags or a.get("ref") is not None:
                    out[str(full)] = {"hit": sorted(hit), "turn": sorted(turn), "flags": sorted(flags),
                                                   "ref": a.get("ref")}
    return dict(sorted(out.items(), key=lambda kv: int(kv[0])))


def main() -> None:
    models = sys.argv[1:] or ["c2540", "c2550", "c2560"]
    data = {"evidence": "file", "source": "chr/<model>*.anibnd.dcx", "flag_names": P.FLAG_NAMES,
            "rows": "hit [start, end] · turn [start, end, SetTurnSpeed] · flags [start, end, flag]",
            "models": {m: model_events(m) for m in models}}
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    for m, d in data["models"].items():
        print(m, len(d), "attack anims")


if __name__ == "__main__":
    main()
