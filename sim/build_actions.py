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
sys.path.insert(0, str(ROOT))
SRC = ROOT / "data" / "gamefiles" / "tae_c0000.json"
OUT = ROOT / "sim" / "godot" / "actions.json"
MODELS = ROOT / "data" / "gamefiles" / "weapon_models.json"     # sim/flver_glb.py

# The room's equipment (MoKa M1109-54): the 11-09 character's Claymore and Wooden Shield. EquipParamWeapon rows;
# a weapon's AttackAnimationCategory is the TAE section of its attacks (Claymore 25 → a25 → 25xxxx), and
# BehaviorParam_PC row = 100000000 + BehaviorVariationID × 1000 + the attack event's judge id (TAE type 1, p[2]).
RIGHT, LEFT = 301000, 1400000

# DSR id → (name, clip, clip library, note). Which roll family (700 / 710 / 720) a character gets depends on equip load
# — 710 (mid roll) is [guess] for the room's default character.
ACTIONS = {
    700: ("roll_fast", "Roll", "", "fast roll forward (equip load < 25 %)"),
    710: ("roll", "Roll", "", "mid roll forward — room default [guess]"),
    690: ("backstep", "Roll", "", "backstep — no CC0 clip: Roll played backward [stand-in]"),
    253000: ("light", "Sword_Regular_A", "ual2", "Claymore one-handed light 1 (BehaviorParam_PC 102505000)"),
    253001: ("light2", "Sword_Regular_B", "ual2", "Claymore one-handed light 2 (BehaviorParam_PC 102505010)"),
    7585: ("estus", "Consume", "ual2", "Estus"),
    8000: ("lever", "Interact", "", "pull lever (ObjActParam 1200 PlayerActionAnimation)"),
}

# Where the stand-in clip's blade is furthest forward, as a fraction of the clip (sampled in Godot: hand_r + 1.28 m
# along the blade, 2026-11-09). The room time-warps the clip so this moment falls in the middle of the DSR attack
# window — the hitbox size is DSR's, the swing path is still the Quaternius clip's [stand-in].
CLIP_CONTACT = {"Sword_Regular_A": 0.575, "Sword_Regular_B": 0.475}


def windows(events: list, flag: int) -> list:
    return [[e["start"], e["end"]] for e in events if e["type"] == 0 and e["p"] and e["p"][0] == flag]


def first(events: list, flag: int):
    w = windows(events, flag)
    return min(s for s, _ in w) if w else None


def equipment(anims: dict) -> dict:
    """Weapon / shield rows, and each attack's AtkParam_Pc hitboxes (dummy-point capsules on the weapon model)."""
    import navmesh  # noqa: F401 — stubs soulstruct modules the wheel lacks data for
    from navmesh import GAME_DIR
    from soulstruct.darksouls1r.params import GameParamBND
    gp = GameParamBND.from_path(GAME_DIR / "param" / "GameParam" / "GameParam.parambnd.dcx")
    models = json.loads(MODELS.read_text(encoding="utf-8")) if MODELS.exists() else {}
    out = {}
    for hand, rid in (("right", RIGHT), ("left", LEFT)):
        w = gp.Weapons[rid]
        model = f"WP_A_{w.WeaponModel:04d}"
        dm = {}
        for d in models.get(model, {}).get("dummies", []):
            dm.setdefault(str(d["ref"]), d["pos"])
        out[hand] = {"row": rid, "name": w.Name, "model": model, "weight": w.Weight,
                     "attack_section": w.AttackAnimationCategory, "behavior_variation": w.BehaviorVariationID,
                     "base_physical": w.BasePhysicalDamage, "physical_guard_pct": w.PhysicalGuardPercentage,
                     "guard_stamina_defense": w.GuardStaminaDefense, "parry": bool(w.ParryEnabled),
                     "required_str_dex": [w.RequiredStrength, w.RequiredDexterity], "dummies": {
                         k: v for k, v in dm.items() if k in ("100", "110", "120", "130")}}
    attacks = {}
    var = out["right"]["behavior_variation"]
    for aid, (name, *_r) in ACTIONS.items():
        ev = [e for e in anims[str(aid)]["events"] if e["type"] == 1]
        if not ev:
            continue
        judge = ev[0]["p"][2]
        b = gp.PlayerBehaviors[100000000 + var * 1000 + judge]
        a = gp.PlayerAttacks[b.ReferenceID]
        hb = []
        for i in range(4):
            s0, s1 = getattr(a, f"Hitbox{i}StartModelPoint"), getattr(a, f"Hitbox{i}EndModelPoint")
            if s0 >= 0:
                hb.append({"from": s0, "to": s1 if s1 >= 0 else s0, "radius": round(getattr(a, f"Hitbox{i}Radius"), 4)})
        attacks[name] = {"behavior": 100000000 + var * 1000 + judge, "behavior_name": b.Name, "stamina": b.StaminaCost,
                         "atk_param": b.ReferenceID, "atk_name": a.Name, "physical_pct": a.PhysicalAttackPowerPercentage,
                         "hitstop": round(a.HitStopTime, 4), "model_point_source": a.ModelPointSource, "hitboxes": hb}
    return {"equip": out, "attacks": attacks}


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
            # input windows: a press inside is kept and runs at the matching cancel time (DSR's buffer).
            # flag 1 = R-attack input, 25 = roll input. An action without one: the room keeps the press from any time
            # in the action ([guess] — DSR may buffer outside the TAE flags too).
            "input_r": windows(ev, 1), "input_roll": windows(ev, 25),
            "clip": clip, "lib": lib, "clip_until": move if move is not None else length,
        }
        if clip in CLIP_CONTACT:
            out[name]["clip_contact"] = CLIP_CONTACT[clip]
    eq = equipment(anims)
    for name, a in eq["attacks"].items():
        out[name]["hit"] = a
    return {"source": "data/gamefiles/tae_c0000.json (player_tae_extract.py) + GameParam (EquipParamWeapon, "
                      "BehaviorParam_PC, AtkParam_Pc) + weapon model dummies (sim/flver_glb.py) — DSR game files; not "
                      "yet checked against DSAnimStudio or the game", "equip": eq["equip"], "actions": out}


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
