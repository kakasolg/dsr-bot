"""Per-weapon length, startup and recovery from the DSR game files (MoKa M1109-82: "칼 길이, 선 딜레이, 후 딜레이 표" —
"이 것으로 무기별 밸런스를 맞추는 데 이게 없으면 공정성을 잃게 되는 거지"; M1109-83: "나름의 평균 공식은 있을거야, 그걸
개별 무기 마다 약간 변경 시키는 거지").

  python weapon_table.py            → data/gamefiles/weapon_table.json + a printed table + the class-average fit

Perplexity (11-09, docs/weapon_frames_pplx_2026-11-09.md) found no verified per-weapon timing table on the web and pointed
at the game's TAE. So every number here is read from the game files [game], none from the web:
  EquipParamWeapon   weight, AttackAnimationCategory (= the TAE section of its attacks), BehaviorVariationID, model
  c0000 TAE          (data/gamefiles/tae_c0000.json, player_tae_extract.py) one-handed light 1 = c·10000 + 3000,
                     one-handed heavy 1 = c·10000 + 3300: blade window (type-1 events), first cancel by move (flag 11),
                     roll (26), next R (4)
  BehaviorParam_PC   100000000 + variation·1000 + the event's judge id → stamina cost and the AtkParam_Pc row
  AtkParam_Pc        hitbox model points + radius; the points' positions come from the weapon model's FLVER dummies
                     (parts/WP_A_<model>.partsbnd.dcx) → "blade" = farthest hitbox point from the grip + its radius
What is not here: reach from the player's centre (arm length and the swing path add to the blade — the 10-13 black box
measured the Claymore at ~1.8–2.0 m, souls/weapons.py), input lag before the animation starts, and two-handed attacks.
Times are animation time (s) from the start of the attack animation.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TAE = ROOT / "data" / "gamefiles" / "tae_c0000.json"
OUT = ROOT / "data" / "gamefiles" / "weapon_table.json"

# English name → EquipParamWeapon row (names in the param file are Japanese; rows checked 11-09)
WEAPONS = {
    "Dagger": 100000, "Bandit's Knife": 103000, "Broadsword": 202000, "Longsword": 201000, "Uchigatana": 500000,
    "Battle Axe": 701000, "Mace": 801000, "Spear": 1000000, "Claymore": 301000, "Bastard Sword": 300000,
    "Zweihander": 350000, "Greatsword": 351000, "Great Club": 850000, "Halberd": 1100000,
    # bought 11-10 (M1110-01/02) — measured in game by weapon_probe.py
    "Shortsword": 200000, "Scimitar": 400000, "Rapier": 601000, "Hand Axe": 700000, "Club": 800000,
    "Reinforced Club": 809000, "War Pick": 803000, "Caestus": 901000, "Pike": 1050000,
    "Morning Star": 802000,     # 11-10 장착 확인 (손 슬롯 802000, 화면의 철퇴 아이콘) — weapon_probe 측정
}
FLAG_MOVE, FLAG_ROLL, FLAG_R = 11, 26, 4


def _first(events, flag):
    ts = [e["start"] for e in events if e["type"] == 0 and e["p"] and e["p"][0] == flag]
    return round(min(ts), 3) if ts else None


def _dummies(model: int) -> dict:
    from navmesh import GAME_DIR
    from soulstruct.containers import Binder
    sys.path.insert(0, str(ROOT / "sim"))
    from flver_glb import read_flver
    name = f"WP_A_{model:04d}"
    bnd = Binder.from_path(GAME_DIR / "parts" / f"{name}.partsbnd.dcx")
    flv = next(e for e in bnd.entries if e.name.lower() == f"{name.lower()}.flver")
    out = {}
    for d in read_flver(flv.data)["dummies"]:
        out.setdefault(int(d["ref"]), d["pos"])
    return out


def _attack(gp, anims, aid: int, var: int, dm: dict) -> dict | None:
    a = anims.get(str(aid))
    if a is None:
        return None
    ev = a["events"]
    hits = [e for e in ev if e["type"] == 1]
    if not hits:
        return None
    start, end = round(min(e["start"] for e in hits), 3), round(max(e["end"] for e in hits[:1]), 3)
    judge = hits[0]["p"][2]
    beh = gp.PlayerBehaviors[100000000 + var * 1000 + judge]
    atk = gp.PlayerAttacks[beh.ReferenceID]
    blade = 0.0
    for i in range(4):
        r = getattr(atk, f"Hitbox{i}Radius")
        for k in (getattr(atk, f"Hitbox{i}StartModelPoint"), getattr(atk, f"Hitbox{i}EndModelPoint")):
            if k >= 0 and k in dm:
                blade = max(blade, math.dist((0, 0, 0), dm[k]) + r)
    mv, rl, rr = _first(ev, FLAG_MOVE), _first(ev, FLAG_ROLL), _first(ev, FLAG_R)
    return {"anim": aid, "startup": start, "active": round(end - start, 3), "blade_end": end,
            "cancel_move": mv, "cancel_roll": rl, "cancel_r": rr,
            "recovery_move": None if mv is None else round(mv - end, 3),
            "recovery_roll": None if rl is None else round(rl - end, 3),
            "stamina": beh.StaminaCost, "atk_param": beh.ReferenceID, "hit_reach": round(blade, 3) if blade else None}


def build() -> dict:
    import navmesh  # noqa: F401 — stubs soulstruct modules the wheel lacks data for
    from navmesh import GAME_DIR
    from soulstruct.darksouls1r.params import GameParamBND
    gp = GameParamBND.from_path(GAME_DIR / "param" / "GameParam" / "GameParam.parambnd.dcx")
    anims = json.loads(TAE.read_text(encoding="utf-8"))["animations"]
    rows = {}
    for name, rid in WEAPONS.items():
        w = gp.Weapons[rid]
        c, var = w.AttackAnimationCategory, w.BehaviorVariationID
        dm = _dummies(w.WeaponModel)
        rows[name] = {"row": rid, "jp": w.Name, "weight": w.Weight, "category": c, "variation": var,
                      "model": w.WeaponModel, "base_physical": w.BasePhysicalDamage,
                      "light": _attack(gp, anims, c * 10000 + 3000, var, dm),
                      "heavy": _attack(gp, anims, c * 10000 + 3300, var, dm)}
    return rows


def fit(rows: dict, key: str, xs=("hit_reach", "weight")) -> dict:
    """Least squares key ≈ a + b·hit_reach + c·weight over the light attacks — the 'average formula'; each weapon's
    residual is how far it is from it."""
    import numpy as np
    pts = [(r["light"][xs[0]], r["weight"], r["light"][key], n) for n, r in rows.items()
           if r["light"] and r["light"].get(key) is not None and r["light"].get(xs[0])]
    X = np.array([[1.0, p[0], p[1]] for p in pts])
    y = np.array([p[2] for p in pts])
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    pred = X @ coef
    ss = float(((y - y.mean()) ** 2).sum()) or 1.0
    return {"key": key, "a": round(float(coef[0]), 4), "per_m_reach": round(float(coef[1]), 4),
            "per_weight": round(float(coef[2]), 4), "r2": round(1 - float(((y - pred) ** 2).sum()) / ss, 3),
            "residual": {p[3]: round(float(y[i] - pred[i]), 3) for i, p in enumerate(pts)}}


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    rows = build()
    fits = {k: fit(rows, k) for k in ("startup", "recovery_move", "stamina")}
    OUT.write_text(json.dumps({"source": "weapon_table.py — DSR game files", "weapons": rows, "fit": fits},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{'weapon':15} {'wt':>5} {'cat':>3} {'reach':>5} | {'R1 start':>8} {'act':>5} {'mv':>5} {'roll':>5} {'R':>5} "
          f"{'rec':>5} {'sp':>3} | {'R2 start':>8} {'rec':>5} {'sp':>3}")
    for n, r in sorted(rows.items(), key=lambda x: x[1]["weight"]):
        lt, hv = r["light"] or {}, r["heavy"] or {}
        f = lambda v: "-" if v is None else f"{v:.2f}"
        print(f"{n:15} {r['weight']:5.1f} {r['category']:3d} {f(lt.get('hit_reach')):>5} | {f(lt.get('startup')):>8} "
              f"{f(lt.get('active')):>5} {f(lt.get('cancel_move')):>5} {f(lt.get('cancel_roll')):>5} {f(lt.get('cancel_r')):>5} "
              f"{f(lt.get('recovery_move')):>5} {lt.get('stamina', '-'):>3} | {f(hv.get('startup')):>8} "
              f"{f(hv.get('recovery_move')):>5} {hv.get('stamina', '-'):>3}")
    for k, ft in fits.items():
        print(f"fit {k}: {ft['a']} + {ft['per_m_reach']}·reach + {ft['per_weight']}·weight  (R² {ft['r2']})  "
              f"residual {ft['residual']}")
    print(f"→ {OUT}")


if __name__ == "__main__":
    main()
