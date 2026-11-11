"""Per-motion frame data for chosen weapons, one- and two-handed, from the DSR game files (MoKa 11-10: Perplexity's
롱소드 · 클레이모어 · 츠바이헨더 비교표 had empty frame / stamina cells — fill them from the game).

  python weapon_motions.py [--weapons 201000,301000,350000]   → data/gamefiles/weapon_motions.json
  (then the sheet + report: uv run --no-project --with openpyxl --with reportlab python weapon_report.py)

Which animation a motion plays [game 11-10, label_probe at the Parish bonfire with the Claymore, one try each]:
  1H: R1 x3000 → x3001 → x3002 · R2 x3300 → x3301 · roll + R1 x3900 · backstep + R1 and sprint + R1 both x3500 ·
  forward + R2 (jump attack) x3600.   2H: the same + 1000 (x4000 …).
  x = the weapon's AttackAnimationCategory, except when its SpecialAttackCategory has that animation in the TAE — then that
  category (Claymore 74: R2 743300 / 744300 and 2H roll attack 744900 were seen in game; 1H roll attack stayed 253900).
  Only x3000 / x3001 / x3002 / x3300 / x3500 / x3600 / x3900 and their 2H twins were seen; x3301 / x4301 (R2 2nd) and x3002
  are named by the pattern, not seen in this try.
From the TAE (c0000, player_tae_extract.py): hitbox windows (type 1), cancel flags (type 0, p[0]: 4 = next R, 26 = roll,
11 = move — the first start of each), length = the latest event end. From BehaviorParam_PC (100000000 + variation·1000 +
judge id): StaminaCost and the AtkParam_Pc row. From AtkParam_Pc: PhysicalAttackPowerPercentage (motion value, % of AR),
PoiseAttackPercentage, StaminaAttackPower. Poise damage = weapon BasePoiseDamage × PoiseAttackPercentage / 100 [formula:
guess — the % and base are game values]. TAE times are 30 fps steps (0.0333 s).
In game (weapon_probe.py, 11-10, Longsword / Claymore 1H R1 only): the hit landed 1–3 frames after the window opened, and
the next-R / roll / move cancels came 0.10–0.13 s BEFORE these flags — so cancel times here are an upper bound.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TAE = ROOT / "data" / "gamefiles" / "tae_c0000.json"
OUT = ROOT / "data" / "gamefiles" / "weapon_motions.json"
FLAG_MOVE, FLAG_ROLL, FLAG_R = 11, 26, 4
MOTIONS = [("R1 1", 3000), ("R1 2", 3001), ("R1 3", 3002), ("R2 1", 3300), ("R2 2", 3301),
           ("roll R1", 3900), ("backstep/sprint R1", 3500), ("jump (fwd+R2)", 3600)]
SEEN = {3000, 3001, 3300, 3500, 3600, 3900}         # offsets seen in game 11-10 (both grips; 3001 in weapon_probe chains)


def _first(ev, flag):
    ts = [e["start"] for e in ev if e["type"] == 0 and e["p"] and e["p"][0] == flag]
    return round(min(ts), 3) if ts else None


def motion(gp, anims: dict, w, off: int) -> dict | None:
    cat = w.AttackAnimationCategory
    sp = w.SpecialAttackCategory
    used = sp if sp and str(sp * 10000 + off) in anims else cat
    aid = used * 10000 + off
    a = anims.get(str(aid))
    if a is None:
        return None
    ev = a["events"]
    hits = sorted((e for e in ev if e["type"] == 1), key=lambda e: e["start"])
    if not hits:
        return None
    length = round(max(e["end"] for e in ev), 3)
    start, blade_end = round(hits[0]["start"], 3), round(max(e["end"] for e in hits), 3)
    per_hit, stamina = [], None
    for h in hits:
        judge = h["p"][2]
        try:
            beh = gp.PlayerBehaviors[100000000 + w.BehaviorVariationID * 1000 + judge]
        except KeyError:
            per_hit.append({"t": [round(h["start"], 3), round(h["end"], 3)], "judge": judge, "missing": "behavior"})
            continue
        stamina = beh.StaminaCost if stamina is None else stamina
        atk = gp.PlayerAttacks[beh.ReferenceID]
        per_hit.append({"t": [round(h["start"], 3), round(h["end"], 3)], "judge": judge, "atk": beh.ReferenceID,
                        "mv": atk.PhysicalAttackPowerPercentage, "poise_pct": atk.PoiseAttackPercentage,
                        "poise": round(w.BasePoiseDamage * atk.PoiseAttackPercentage / 100, 1),
                        "stamina_dmg": atk.StaminaAttackPower, "stamina_cost": beh.StaminaCost})
    mv, rl, rr = _first(ev, FLAG_MOVE), _first(ev, FLAG_ROLL), _first(ev, FLAG_R)
    # one row per distinct hitbox (same judge in back-to-back windows = one swing drawn in pieces)
    distinct = {(p.get("atk"), p.get("judge")) for p in per_hit}
    return {"anim": aid, "category": used, "startup": start, "blade_end": blade_end,
            "active": round(sum(h["end"] - h["start"] for h in hits), 3), "windows": len(hits), "length": length,
            "cancel_r": rr, "cancel_roll": rl, "cancel_move": mv,
            "rec_r": None if rr is None else round(rr - blade_end, 3),
            "rec_roll": None if rl is None else round(rl - blade_end, 3),
            "rec_move": None if mv is None else round(mv - blade_end, 3),
            "stamina": stamina, "hits": per_hit, "distinct_hitboxes": len(distinct)}


def build(rows: list[int]) -> dict:
    import navmesh  # noqa: F401
    from navmesh import GAME_DIR
    from soulstruct.darksouls1r.params import GameParamBND
    gp = GameParamBND.from_path(GAME_DIR / "param" / "GameParam" / "GameParam.parambnd.dcx")
    anims = json.loads(TAE.read_text(encoding="utf-8"))["animations"]
    out = {}
    for rid in rows:
        w = gp.Weapons[rid]
        ent = {"row": rid, "jp": w.Name, "weight": w.Weight, "category": w.AttackAnimationCategory,
               "special_category": w.SpecialAttackCategory, "base_poise": w.BasePoiseDamage,
               "base_physical": w.BasePhysicalDamage, "variation": w.BehaviorVariationID, "motions": []}
        for grip, add in (("1H", 0), ("2H", 1000)):
            for name, off in MOTIONS:
                m = motion(gp, anims, w, off + add)
                if m is not None:
                    m.update({"grip": grip, "motion": name, "seen_in_game": off in SEEN})
                    ent["motions"].append(m)
        out[rid] = ent
    return out


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--weapons", default="201000,301000,350000")
    a = ap.parse_args()
    data = build([int(x) for x in a.weapons.split(",")])
    OUT.write_text(json.dumps({"source": "weapon_motions.py — DSR game files (TAE c0000, EquipParamWeapon, BehaviorParam_PC, "
                                         "AtkParam_Pc)", "weapons": data}, ensure_ascii=False, indent=1), encoding="utf-8")
    f = lambda v: "-" if v is None else f"{v:.2f}"
    for rid, e in data.items():
        print(f"{rid} {e['jp']} wt {e['weight']} poise base {e['base_poise']} cat {e['category']}/{e['special_category']}")
        for m in e["motions"]:
            h = m["hits"][0] if m["hits"] else {}
            print(f"  {m['grip']} {m['motion']:20} {m['anim']}  start {f(m['startup'])} end {f(m['blade_end'])} act {f(m['active'])} "
                  f"len {f(m['length'])} | R {f(m['cancel_r'])} roll {f(m['cancel_roll'])} move {f(m['cancel_move'])} | "
                  f"sp {m['stamina']} mv {h.get('mv')}% poise {h.get('poise')} hits {m['distinct_hitboxes']}")
    print(f"→ {OUT}")


if __name__ == "__main__":
    main()
