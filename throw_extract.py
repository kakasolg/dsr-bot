"""Backstab / riposte (parry throw) conditions from the game files: ThrowParam (THROW_INFO_BANK) → data/gamefiles/throw_params.json.

    python throw_extract.py

Every row with its soulstruct field names (Name is the game's Japanese label: 背面 = backstab, パリィ = riposte after a
parry, 【強化】 = the stronger variant, "→PC パリィ投げ" = a foe riposting the player). A model with a パリィ row can be
riposted after a parry; one without (e.g. c2570) cannot — that is the file's word, not checked in game for every model.
Evidence "file". [win] only (reads the DSR install, DSR_GAME_DIR like navmesh.py).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import navmesh  # noqa: F401 — stubs soulstruct data files the wheel lacks
from navmesh import GAME_DIR

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

OUT = Path(__file__).resolve().parent / "data" / "gamefiles" / "throw_params.json"


def main() -> None:
    from soulstruct.darksouls1r.params import GameParamBND
    gp = GameParamBND.from_path(GAME_DIR / "param" / "GameParam" / "GameParam.parambnd.dcx")
    rows = {}
    for i in sorted(gp.Throws.rows):
        d = gp.Throws[i].to_dict()
        d.pop("RawName", None)
        rows[str(i)] = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in d.items()}
    ripostable = sorted({r["DefendingCharacterModel"] for r in rows.values()
                         if "パリィ" in (r.get("Name") or "") and "→PC" not in r["Name"] and r.get("DefendingCharacterModel")})
    OUT.write_text(json.dumps({"evidence": "file", "source": "param/GameParam ThrowParam", "rows": rows,
                               "ripostable_models": [f"c{m:04d}" for m in ripostable]},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{OUT}  rows {len(rows)} · ripostable models {len(ripostable)}")


if __name__ == "__main__":
    main()
