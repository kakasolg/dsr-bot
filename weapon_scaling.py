"""Attack rating by STR / DEX and upgrade level, computed from the DSR game files — step 1 of MoKa's weapon test
(11-10 "1단계 계산표부터 만들어줘, 그런데 카테고리를 나누어서, 근력, 반반, 기량 이렇게 나누어서").

  python weapon_scaling.py   → data/gamefiles/weapon_scaling.json   (needs the game folder; weapon_report.py reads it)

From the game files [게임 파일]: base physical attack, requirements, STR / DEX scaling (EquipParamWeapon), upgrade
multipliers (ReinforceParamWeapon, row WeaponUpgradeID + level) and the stat curve (CalcCorrectGraph row
ScalingFormulaType — soulstruct calls it GrowthCurves: StageMaxIntercept0..4 = stat points, StageMaxSlope0..4 = % at
those points, AdjustmentMaxSlope = exponent of each segment).

The formula is the community one [추정, not checked in game yet — step 2]:
  AR = floor(base·up + base·up · (STR scaling·up_s / 100) · curve(STR) / 100 + same for DEX)
  two-handed: STR × 1.5 (floor) for the requirement and the curve. A requirement not met → no number (the game's
  penalty is not known here; Pike at STR 16 gave the slow 363030 swing and damage 1, 11-10).
Categories by the +0 scaling share STR / (STR + DEX): ≥ 0.6 근력 · ≤ 0.4 기량 · else 반반.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "data" / "gamefiles" / "weapon_scaling.json"
LEVELS = (0, 1, 5, 15)
# 카테고리별로 올리는 능력치 줄 (MoKa 11-10 "근력, 반반, 기량"): 캐릭터는 SL14 STR 14 DEX 9 (BASE 세이브)
LINES = {
    "근력": [(s, 10) for s in (14, 16, 20, 24, 28, 32, 40)],            # DEX 10 = 기량 요구 10 무기를 들 최소
    "반반": [(14, 10), (16, 12), (18, 14), (20, 16), (20, 20), (25, 25), (30, 30), (40, 40)],
    "기량": [(16, d) for d in (12, 14, 16, 20, 25, 30, 40)],             # 근력 16 = 할버드 요구 (MoKa 대표 무기)
}
# MoKa 11-10 대표 무기 (인기 무기, 게임에서 잴 것): 근력 츠바이헨더·배틀 액스, 반반 롱소드·클레이모어, 기량 할버드·레이피어.
# 할버드는 보정 근 38 / 기 50 (근력 몫 0.43)이라 비율로는 반반이지만 MoKa가 기량 대표로 정함 → 기량으로 옮김
PICKS = {"근력": ["Zweihander", "Battle Axe"], "반반": ["Longsword", "Claymore"], "기량": ["Halberd", "Rapier"]}
CATEGORY_OVERRIDE = {"Halberd": "기량"}


def curve(row, stat: float) -> float:
    xs = [row.StageMaxIntercept0, row.StageMaxIntercept1, row.StageMaxIntercept2, row.StageMaxIntercept3, row.StageMaxIntercept4]
    ys = [row.StageMaxSlope0, row.StageMaxSlope1, row.StageMaxSlope2, row.StageMaxSlope3, row.StageMaxSlope4]
    ex = [row.AdjustmentMaxSlope0, row.AdjustmentMaxSlope1, row.AdjustmentMaxSlope2, row.AdjustmentMaxSlope3]
    if stat <= xs[0]:
        return ys[0]
    for i in range(4):
        if stat <= xs[i + 1]:
            r = (stat - xs[i]) / (xs[i + 1] - xs[i])
            e = ex[i]
            r = r ** e if e > 0 else 1 - (1 - r) ** -e
            return ys[i] + (ys[i + 1] - ys[i]) * r
    return ys[4]


def category(s: float, d: float) -> str:
    sh = s / (s + d) if s + d else 0.5
    return "근력" if sh >= 0.6 else "기량" if sh <= 0.4 else "반반"


def main() -> None:
    import navmesh
    import weapon_table
    from soulstruct.darksouls1r.params import GameParamBND
    gp = GameParamBND.from_path(navmesh.GAME_DIR / "param" / "GameParam" / "GameParam.parambnd.dcx")
    out = {}
    for name, rid in weapon_table.WEAPONS.items():
        w = gp.Weapons[rid]
        cv = gp.GrowthCurves[w.ScalingFormulaType]
        cat = CATEGORY_OVERRIDE.get(name) or category(w.StrengthScaling, w.DexterityScaling)
        rows = []
        for lv in LEVELS:
            up = gp.WeaponUpgrades[w.WeaponUpgradeID + lv]
            base = w.BasePhysicalDamage * up.PhysicalDamageMultiplier
            sc_s = w.StrengthScaling * up.StrengthScalingMultiplier
            sc_d = w.DexterityScaling * up.DexterityScalingMultiplier
            for grip in ("1H", "2H"):
                for line, pts in LINES.items():
                    for s, d in pts:
                        se = math.floor(s * 1.5) if grip == "2H" else s
                        ok = se >= w.RequiredStrength and d >= w.RequiredDexterity
                        bs = base * sc_s / 100 * curve(cv, se) / 100
                        bd = base * sc_d / 100 * curve(cv, d) / 100
                        rows.append({"level": lv, "grip": grip, "line": line, "str": s, "dex": d, "ok": ok,
                                     "base": math.floor(base + 1e-3), "bonus_str": round(bs, 1), "bonus_dex": round(bd, 1),
                                     "ar": math.floor(base + bs + bd + 1e-3) if ok else None})
        out[name] = {"row": rid, "category": cat, "pick": name in PICKS[cat], "req_str": int(w.RequiredStrength), "req_dex": int(w.RequiredDexterity),
                     "scale_str": float(w.StrengthScaling), "scale_dex": float(w.DexterityScaling),
                     "curve": int(w.ScalingFormulaType), "weight": float(w.Weight), "rows": rows}
    curves = {}
    for cid in sorted({v["curve"] for v in out.values()}):
        cv = gp.GrowthCurves[cid]
        curves[cid] = {"name": cv.Name, "points": [[cv.StageMaxIntercept0, cv.StageMaxSlope0], [cv.StageMaxIntercept1, cv.StageMaxSlope1],
                                                    [cv.StageMaxIntercept2, cv.StageMaxSlope2], [cv.StageMaxIntercept3, cv.StageMaxSlope3],
                                                    [cv.StageMaxIntercept4, cv.StageMaxSlope4]],
                       "exp": [cv.AdjustmentMaxSlope0, cv.AdjustmentMaxSlope1, cv.AdjustmentMaxSlope2, cv.AdjustmentMaxSlope3],
                       "at": {str(x): round(curve(cv, x), 1) for x in (10, 14, 16, 20, 24, 30, 40, 50, 99)}}
    OUT.write_text(json.dumps({"source": "weapon_scaling.py", "lines": LINES, "picks": PICKS, "levels": LEVELS, "curves": curves,
                               "weapons": out}, ensure_ascii=False), encoding="utf-8")
    print(OUT, "curves", curves)
    for c in ("근력", "반반", "기량"):
        print(c, [n for n, v in out.items() if v["category"] == c])


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
