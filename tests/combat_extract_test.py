"""combat_extract offline test — fake GameParam tables built from soulstruct's real DSR row types, no game files.

  python tests/combat_extract_test.py
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import json
import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import combat_extract as X
from soulstruct.darksouls1r.params.paramdef import NPC_PARAM_ST, BEHAVIOR_PARAM_ST, ATK_PARAM_ST, BULLET_PARAM_ST


def fake_params() -> dict:
    npcs = {
        254010: NPC_PARAM_ST(MaximumHP=150, MaxPoise=20, BehaviorVariationID=2540, PhysicalDefense=40),
        225000: NPC_PARAM_ST(MaximumHP=80, BehaviorVariationID=2250),
    }
    behaviors = {
        202540000: BEHAVIOR_PARAM_ST(VariationID=2540, BehaviorJudgeID=0, ReferenceType=0, ReferenceID=2540000, StaminaCost=10),
        202540100: BEHAVIOR_PARAM_ST(VariationID=2540, BehaviorJudgeID=100, ReferenceType=1, ReferenceID=2540100),
        202540200: BEHAVIOR_PARAM_ST(VariationID=2540, BehaviorJudgeID=200, ReferenceType=2, ReferenceID=5000),
        202540300: BEHAVIOR_PARAM_ST(VariationID=2540, BehaviorJudgeID=300, ReferenceType=0, ReferenceID=999),  # no such attack
        202250000: BEHAVIOR_PARAM_ST(VariationID=2250, BehaviorJudgeID=0, ReferenceType=0, ReferenceID=2250000),
    }
    attacks = {
        2540000: ATK_PARAM_ST(PhysicalAttackPower=120, PoiseAttackPower=30, Hitbox0Radius=0.4, Hitbox1Radius=0.25,
                              AttackAttribute=1, IgnoreGuard=True),
        2540100: ATK_PARAM_ST(PhysicalAttackPower=60, FireAttackPower=80, Hitbox0Radius=0.3, AttackAttribute=3,
                              IgnoreInvincibilityFrames=True),
        2250000: ATK_PARAM_ST(PhysicalAttackPower=50, Hitbox0Radius=0.35, AttackAttribute=2),
    }
    bullets = {2540100: BULLET_PARAM_ST(BulletAttack=2540100, InitialSpeed=20.0, LifeTime=2.5)}
    return {"npcs": npcs, "behaviors": behaviors, "attacks": attacks, "bullets": bullets}


def test_foe_chain():
    f = X.foe(fake_params(), 254010)
    assert f["MaximumHP"] == 150 and f["MaxPoise"] == 20 and f["variation"] == 2540
    b = f["behaviors"]
    assert list(b) == ["0", "100", "200", "300"], list(b)          # only this foe's variation, sorted by judge id
    melee = b["0"]
    assert melee["type"] == "attack" and melee["stamina_cost"] == 10
    assert melee["attack"]["PhysicalAttackPower"] == 120 and melee["attack"]["kind"] == "slash"
    assert melee["attack"]["radii"] == [0.4, 0.25]                    # zero slots dropped
    shot = b["100"]
    assert shot["type"] == "bullet" and shot["bullet"]["InitialSpeed"] == 20.0
    assert shot["attack"]["FireAttackPower"] == 80                    # bullet → its AtkParam_Npc row
    assert b["200"] == {"behavior_id": 202540200, "stamina_cost": 0, "type": "sp_effect", "sp_effect": 5000}
    assert b["300"]["attack"] is None                                 # missing attack row kept, not dropped
    s = f["summary"]
    assert s == {"behaviors": 4, "attacks": 2, "max_physical": 120, "max_radius": 0.4,
                 "unblockable": [0], "roll_proof": [100], "bullets": [100]}, s


def test_extract_missing_and_where():
    d = X.extract(fake_params(), [225000, 254010, 999999, 254010], {254010: {"model": "c2540", "maps": ["m10_01_00_00"], "count": 3}})
    assert d["evidence"] == "file" and d["counts"] == {"foes": 2, "missing": 1} and d["missing"] == [999999]
    assert list(d["foes"]) == ["225000", "254010"]
    assert d["foes"]["254010"]["model"] == "c2540" and d["foes"]["254010"]["count"] == 3
    assert d["foes"]["225000"]["summary"]["max_physical"] == 50
    json.dumps(d)                                                     # writable as is


def test_foes_in_maps():
    with tempfile.TemporaryDirectory() as t:
        p = Path(t)
        for map_id, enemies in (("m10_01_00_00", [("c2540", "enemy", 254010), ("c2540", "enemy", 254010), ("c0000", "human", 6000)]),
                                ("m10_00_00_00", [("c2540", "enemy", 254010), ("c2250", "enemy", -1)])):
            (p / f"{map_id}.json").write_text(json.dumps({"map_id": map_id, "enemies": [
                {"model": m, "kind": k, "npc_param_id": n} for m, k, n in enemies]}), encoding="utf-8")
        (p / "combat.json").write_text("{}", encoding="utf-8")       # the output itself is not an input
        w = X.foes_in_maps(p)
    assert w == {254010: {"model": "c2540", "maps": ["m10_00_00_00", "m10_01_00_00"], "count": 3}}, w


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
