"""sim/build_actions.py --weapon (MoKa 11-10 "연습장 무기에서도 이것을 적용해줘"): the room's light attacks follow the
weapon's attack-animation category, and the game-measured cancels are shared by every weapon of that category
(weapon_report.py '무기_묶음': same category → same TAE times whatever the weight / length). Needs the DSR game folder
(GameParam); skipped without it. No Godot."""
from __future__ import annotations

import sys as _sys, pathlib as _pl
ROOT = _pl.Path(__file__).resolve().parent.parent
_sys.path.insert(0, str(ROOT))
_sys.path.insert(1, str(ROOT / "sim"))


def check(what: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + what)
    if not ok:
        raise SystemExit(1)


import build_actions as B

check("actions_for: category 38 → light 383000, light2 383001",
      {x[0]: k for k, x in B.actions_for(38, "Halberd").items() if x[0] in ("light", "light2")} == {"light": 383000, "light2": 383001})
check("every measured key is an R1 1st id (x3000) with the three cancels",
      all(k % 10000 == 3000 and set(v) == {"cancel_r", "cancel_roll", "cancel_move"} for k, v in B.MEASURED.items()))

try:
    from navmesh import GAME_DIR
    have_game = (GAME_DIR / "param" / "GameParam" / "GameParam.parambnd.dcx").exists()
except Exception:
    have_game = False
if not have_game:
    print("room_weapon_test: 게임 폴더 없음 — 나머지 건너뜀")
    raise SystemExit(0)

d = B.build(300000)                                            # Bastard Sword: category 25 like the Claymore, never measured
a = d["actions"]["light"]
check(f"Bastard Sword → 253000 with the Claymore's measured cancels {a['cancel_r']} · {a['cancel_roll']} · {a['cancel_move']}",
      a["anim"] == 253000 and (a["cancel_r"], a["cancel_roll"], a["cancel_move"]) == (1.033, 1.267, 1.433)
      and "Claymore" in a["timing"]["cancel_r"])
d = B.build(100000)                                            # Dagger: category 20, no weapon of it measured
a = d["actions"]["light"]
check(f"Dagger (category not measured) → TAE {a['tae']['cancel_r']} {B.DEFAULT_SHIFT:+} = {a['cancel_r']}, marked guess",
      a["anim"] == 203000 and abs(a["cancel_r"] - (a["tae"]["cancel_r"] + B.DEFAULT_SHIFT)) < 1e-6
      and a["timing"]["cancel_r"].startswith("guess"))
l2 = d["actions"]["light2"]
check("light2 keeps the measured / guessed shift of light (R1 2nd never measured)", l2["timing"]["cancel_r"].startswith("guess"))
d = B.build(301000)
check("default Claymore: equip right row 301000, model WP_A_0266", d["equip"]["right"]["row"] == 301000
      and d["equip"]["right"]["model"] == "WP_A_0266")
print("room_weapon_test: 전부 통과")
