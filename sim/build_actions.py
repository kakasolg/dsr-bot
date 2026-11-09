"""Player actions for the practice room (sim/godot/actions.json) from the DSR player TAE (data/gamefiles/tae_c0000.json,
player_tae_extract.py). One entry per DSR animation the room plays, with the windows the room's character obeys
(MoKa M1109-51: the room's character moves by DSR's own timings).

  python sim/build_actions.py

Per action: DSR anim id, length (last event end), invincible / turn-disabled / attack windows, and the first time the
animation can be left by moving (flag 11), by a roll (26), by the next R attack (4). The visual clip is a CC0
Quaternius clip (sim/godot/assets, not in git) stretched over `clip_until` — what it looks like is not DSR.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "gamefiles" / "tae_c0000.json"
OUT = ROOT / "sim" / "godot" / "actions.json"

# DSR id → (name, clip, clip library, note). Which roll family (700 / 710 / 720) a character gets depends on equip load
# — 710 (mid roll) is [guess] for the room's default character.
ACTIONS = {
    700: ("roll_fast", "Roll", "", "fast roll forward (equip load < 25 %)"),
    710: ("roll", "Roll", "", "mid roll forward — room default [guess]"),
    690: ("backstep", "Roll", "", "backstep — no CC0 clip: Roll played backward [stand-in]"),
    304000: ("light", "Sword_Regular_A", "ual2", "1st right-hand light attack, section 30 weapon"),
    7585: ("estus", "Consume", "ual2", "Estus"),
    8000: ("lever", "Interact", "", "pull lever (ObjActParam 1200 PlayerActionAnimation)"),
}


def windows(events: list, flag: int) -> list:
    return [[e["start"], e["end"]] for e in events if e["type"] == 0 and e["p"] and e["p"][0] == flag]


def first(events: list, flag: int):
    w = windows(events, flag)
    return min(s for s, _ in w) if w else None


def build() -> dict:
    anims = json.loads(SRC.read_text(encoding="utf-8"))["animations"]
    out = {}
    for aid, (name, clip, lib, note) in ACTIONS.items():
        ev = anims[str(aid)]["events"]
        length = max(e["end"] for e in ev)
        move = first(ev, 11)
        out[name] = {
            "anim": aid, "length": round(length, 4), "note": note,
            "invincible": windows(ev, 8), "no_turn": windows(ev, 7),
            "attack": [[e["start"], e["end"]] for e in ev if e["type"] == 1],
            "cancel_move": move, "cancel_roll": first(ev, 26), "cancel_r": first(ev, 4),
            "clip": clip, "lib": lib, "clip_until": move if move is not None else length,
        }
    return {"source": "data/gamefiles/tae_c0000.json (player_tae_extract.py) — DSR game files; not yet checked against "
                      "DSAnimStudio or the game", "actions": out}


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    d = build()
    OUT.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    for k, a in d["actions"].items():
        print(f"{k:9s} {a['anim']:6d} len {a['length']:.2f}  inv {a['invincible']}  move-cancel {a['cancel_move']}  "
              f"attack {a['attack']}")


if __name__ == "__main__":
    main()
