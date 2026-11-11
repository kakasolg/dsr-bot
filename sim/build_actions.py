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
RIGHT, LEFT = 301000, 1400000          # right: default; `--weapon <row>` picks another (MoKa 11-10 "연습장 무기에서도 적용")

# DSR id → (name, clip, clip library, note). Which roll family (700 / 710 / 720) a character gets depends on equip load
# — 710 (mid roll) is [guess] for the room's default character. light / light2 are filled by actions_for(weapon).
BASE_ACTIONS = {
    700: ("roll_fast", "Roll", "", "fast roll forward (equip load < 25 %)"),
    710: ("roll", "Roll", "", "mid roll forward — room default [guess]"),
    690: ("backstep", "Roll", "", "backstep — no CC0 clip: Roll played backward [stand-in]"),
    7585: ("estus", "Consume", "ual2", "Estus"),
    8000: ("lever", "Interact", "", "pull lever (ObjActParam 1200 PlayerActionAnimation)"),
}


def actions_for(category: int, name: str) -> dict:
    """The weapon's one-handed R1 1st / 2nd = TAE section `category` (EquipParamWeapon AttackAnimationCategory) ·10000
    + 3000 / 3001. 11-10 (weapon_report.py '무기_묶음'): every weapon of one category has the same startup and cancel
    times whatever its weight or blade length — so the action follows the category, not the weapon."""
    a = dict(BASE_ACTIONS)
    a[category * 10000 + 3000] = ("light", "Sword_Regular_A", "ual2", f"{name} one-handed light 1 (category {category})")
    a[category * 10000 + 3001] = ("light2", "Sword_Regular_B", "ual2", f"{name} one-handed light 2 (category {category})")
    return a


ACTIONS = actions_for(25, "Claymore")

# Where the stand-in clip's blade is furthest forward, as a fraction of the clip (sampled in Godot: hand_r + 1.28 m
# along the blade, 2026-11-09). The room time-warps the clip so this moment falls in the middle of the DSR attack
# window — the hitbox size is DSR's, the swing path is still the Quaternius clip's [stand-in].
CLIP_CONTACT = {"Sword_Regular_A": 0.575, "Sword_Regular_B": 0.475}


# Game-measured cancels (MoKa M1110-08: "딜레이, 휘두르는 시간, 후 딜레이가 반영 된 상태"). weapon_probe.py 11-10, Claymore
# one-handed R1 1st (253000) at the Parish soldier: next R1 / roll / move began 0.13 s BEFORE the TAE flags (n 4 each; same
# −0.10…−0.13 s on Longsword, Battle Axe, Shortsword and 2H Pike). The hit landed 1 frame after the TAE window opened, so the
# attack window stays TAE. R1 2nd (253001) was not measured — it gets R1 1st's shift [guess].
# medians (s, n) of the measured cancels — data/probe/20261110_*_weapon_probe.jsonl (local, data/ is not in git), rows
# filtered as weapon_report.measured: R1 1st (x3000), damage seen, no x3040 / x3150 switch. Keyed by the R1 1st anim id,
# i.e. by animation category: 11-10 저녁 무기 8종 실측 — 같은 묶음이면 TAE가 같으므로 잰 무기의 값을 묶음 전체에 씀
# (233000 = 롱소드 + 숏소드 합친 판수, 실측도 둘이 같았음). 묶음마다 1~2종만 잼 — 묶음 안 다른 무기는 [class] 값.
MEASURED = {
    233000: {"cancel_r": (0.667, 13), "cancel_roll": (0.8, 14), "cancel_move": (0.933, 12)},     # Longsword · Shortsword
    253000: {"cancel_r": (1.033, 4), "cancel_roll": (1.267, 4), "cancel_move": (1.433, 4)},      # Claymore
    263000: {"cancel_r": (1.633, 3), "cancel_roll": (1.733, 6), "cancel_move": (1.933, 6)},      # Zweihander (튕김 뺌, P-157)
    303000: {"cancel_r": (1.0, 7), "cancel_roll": (1.017, 5), "cancel_move": (1.133, 5)},        # Battle Axe
    333000: {"cancel_r": (1.083, 5), "cancel_roll": (1.067, 5), "cancel_move": (1.2, 5)},        # Morning Star
    363000: {"cancel_r": (0.767, 5), "cancel_roll": (0.8, 5), "cancel_move": (0.967, 5)},        # Pike (근력 24)
    383000: {"cancel_r": (1.067, 5), "cancel_roll": (0.967, 5), "cancel_move": (1.233, 5)},      # Halberd (구르기 −0.2 s, 원인 안 봄)
}
MEASURED_BY = {233000: "Longsword+Shortsword", 253000: "Claymore", 263000: "Zweihander", 303000: "Battle Axe",
               333000: "Morning Star", 363000: "Pike", 383000: "Halberd"}
DEFAULT_SHIFT = -0.1        # [guess] 묶음을 안 잰 무기: 잰 묶음 대부분이 TAE보다 0.1 s 이름 (대검·특대검만 0.133)


def measured_cancels() -> dict:
    return MEASURED


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


def weapon_row(rid: int):
    import navmesh  # noqa: F401
    from navmesh import GAME_DIR
    from soulstruct.darksouls1r.params import GameParamBND
    gp = GameParamBND.from_path(GAME_DIR / "param" / "GameParam" / "GameParam.parambnd.dcx")
    return gp.Weapons[rid]


def build(weapon: int | None = None) -> dict:
    global RIGHT, ACTIONS
    if weapon is not None:
        RIGHT = weapon
        w = weapon_row(weapon)
        names = {v["row"]: n for n, v in json.loads((ROOT / "data" / "gamefiles" / "weapon_table.json").read_text(
            encoding="utf-8"))["weapons"].items()}
        ACTIONS = actions_for(w.AttackAnimationCategory, names.get(weapon - weapon % 100, str(weapon)))
    light1 = next(aid for aid, x in ACTIONS.items() if x[0] == "light")
    shift_from = {light1 + 1: light1}                       # R1 2nd not measured → R1 1st's shift [guess]
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
    meas = measured_cancels()
    for name, a in out.items():
        aid = a["anim"]
        if name not in ("light", "light2"):
            continue
        src = shift_from.get(aid, aid)
        ref = out[next(n for n, x in out.items() if x["anim"] == src)]
        a["tae"] = {k: a[k] for k in ("cancel_r", "cancel_roll", "cancel_move")}
        a["timing"] = {}
        by = MEASURED_BY.get(src)
        for k in ("cancel_r", "cancel_roll", "cancel_move"):
            if a[k] is None:
                continue
            if src not in meas:                               # 이 묶음은 안 잼 → 공통 차이 [guess]
                a[k] = round(a[k] + DEFAULT_SHIFT, 4)
                a["timing"][k] = f"guess: TAE {DEFAULT_SHIFT:+} (category not measured)"
                continue
            v, n = meas[src][k]
            if src == aid:
                a[k] = v
                a["timing"][k] = f"game n{n} ({by}, same category)"
            else:                                             # [guess] same shift as the measured action
                a[k] = round(a[k] + (v - ref["tae"][k]), 4)
                a["timing"][k] = f"guess: {src} shift"
        if a["cancel_move"] is not None:
            a["clip_until"] = a["cancel_move"]
    eq = equipment(anims)
    for name, a in eq["attacks"].items():
        out[name]["hit"] = a
    return {"source": "data/gamefiles/tae_c0000.json (player_tae_extract.py) + GameParam (EquipParamWeapon, "
                      "BehaviorParam_PC, AtkParam_Pc) + weapon model dummies (sim/flver_glb.py) — DSR game files; "
                      "light / light2 cancels from game measurement (weapon_probe.py 11-10, see each action's timing / tae)", "equip": eq["equip"], "actions": out}


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--weapon", type=int, default=RIGHT, help="EquipParamWeapon row in the right hand (default Claymore 301000)")
    d = build(ap.parse_args().weapon)
    OUT.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    for k, a in d["actions"].items():
        print(f"{k:9s} {a['anim']:6d} len {a['length']:.2f}  inv {a['invincible']}  move-cancel {a['cancel_move']}  "
              f"attack {a['attack']}")


if __name__ == "__main__":
    main()
