"""Regular (+0..+15) upgrade values of the weapons we measured, from the DSR game files (MoKa 11-10 "퍼플렉시티로 … 강화별로
강화 수치 찾아 보라고해" → "게임 파일과 대조" → "보고서에 추가").

  python weapon_upgrades.py   → data/gamefiles/weapon_upgrades.json   (needs the game folder; weapon_report.py reads the JSON)

Per level: EquipParamWeapon base attack × ReinforceParamWeapon (row WeaponUpgradeID + level) multiplier, and the stat
scaling numbers (EquipParamWeapon correction × the level's multiplier). The game files hold numbers only — the scaling
letters the menu shows are not in GameParam.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "data" / "gamefiles" / "weapon_upgrades.json"
WEAPONS = {"Shortsword": 200000, "Longsword": 201000, "Claymore": 301000, "Zweihander": 350000, "Battle Axe": 701000,
           "Morning Star": 802000, "Pike": 1050000, "Halberd": 1100000}


def main() -> None:
    import navmesh
    from soulstruct.darksouls1r.params import GameParamBND
    gp = GameParamBND.from_path(navmesh.GAME_DIR / "param" / "GameParam" / "GameParam.parambnd.dcx")
    out = {}
    for name, rid in WEAPONS.items():
        w = gp.Weapons[rid]
        levels = []
        for lv in range(16):
            try:
                u = gp.WeaponUpgrades[w.WeaponUpgradeID + lv]
            except Exception:
                break
            levels.append({"level": lv, "phys_rate": round(float(u.PhysicalDamageMultiplier), 4),
                           "phys": round(w.BasePhysicalDamage * u.PhysicalDamageMultiplier, 3),
                           "str": round(w.StrengthScaling * u.StrengthScalingMultiplier, 2),
                           "dex": round(w.DexterityScaling * u.DexterityScalingMultiplier, 2),
                           "magic": round(w.BaseMagicDamage * u.MagicDamageMultiplier, 2),
                           "fire": round(w.BaseFireDamage * u.FireDamageMultiplier, 2),
                           "lightning": round(w.BaseLightningDamage * u.LightningDamageMultiplier, 2)})
        out[name] = {"row": rid, "upgrade_id": int(w.WeaponUpgradeID), "base_phys": int(w.BasePhysicalDamage),
                     "str": float(w.StrengthScaling), "dex": float(w.DexterityScaling), "levels": levels}
    OUT.write_text(json.dumps({"source": "weapon_upgrades.py (GameParam EquipParamWeapon + ReinforceParamWeapon)",
                               "weapons": out}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(OUT, {n: len(v["levels"]) for n, v in out.items()})


if __name__ == "__main__":
    main()
