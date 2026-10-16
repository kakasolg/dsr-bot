"""Foe combat table from the game files — what GameParam says a foe's attacks do, before any play.

  python combat_extract.py                    every npc_param_id in data/gamefiles/m*.json → data/gamefiles/combat.json
  python combat_extract.py 254010 225000      only these NpcParam rows

Reads (DSR install folder, DSR_GAME_DIR like navmesh.py):
  param/GameParam/GameParam.parambnd.dcx
    NpcParam       (Characters)        HP, poise, defenses, BehaviorVariationID
    BehaviorParam  (NonPlayerBehaviors) rows with that VariationID: BehaviorJudgeID → attack / bullet / special effect
    AtkParam_Npc   (NonPlayerAttacks)  damage by type, poise / guard-break / stamina damage, hitbox radii, unblockable, roll-proof
    Bullet         (Bullets)           projectile speed / life / radius and its AtkParam_Npc row

The chain is NpcParam.BehaviorVariationID = BehaviorParam.VariationID; a TAE event in the foe's animation names a
BehaviorJudgeID, so the table is keyed by judge id — step 2 (TAE, chr/cXXXX.anibnd.dcx) adds which animation and
which frames each judge id swings in (ROADMAP combat-table).

Evidence grade: "file" (LAYERS.md) — what the data says, not yet seen in play. Damage numbers are the attack's own
power before the player's defense; radii are raw param units (metres in DS1, not yet checked in play).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import navmesh   # noqa: F401 — stubs the soulstruct modules whose data files the wheel lacks (see navmesh.py)
from navmesh import GAME_DIR

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

OUT_DIR = Path(__file__).parent / "data" / "gamefiles"
OUT_NAME = "combat.json"

NPC_FIELDS = (
    "MaximumHP", "MaxPoise", "MaxStamina", "SoulReward", "TeamType", "GuardLevel", "GuardAngle",
    "PhysicalDefense", "SlashDefense", "StrikeDefense", "ThrustDefense", "MagicDefense", "FireDefense", "LightningDefense",
    "PhysicalGuardCutRate", "HitRadius", "HitHeight", "TurnVelocity", "LockOnDistance",
)
ATK_FIELDS = (
    "PhysicalAttackPower", "MagicAttackPower", "FireAttackPower", "LightningAttackPower",
    "StaminaAttackPower", "GuardAttackPower", "GuardBreakPower", "PoiseAttackPower", "ObjectDamage",
    "KnockbackDistance", "ImpactLevel", "AttackAttribute", "ElementAttribute",
    "IgnoreGuard", "IgnoreGuardPercentage", "IgnoreInvincibilityFrames", "IsPhysicalProjectile", "ThrowID",
)
BULLET_FIELDS = ("InitialSpeed", "MaxSpeed", "LifeTime", "InitialHitRadius", "FinalHitRadius", "LaunchInterval",
                 "HomingStartDistance", "GravityBeforeAttenuation")
ATTACK_KIND = {0: "none", 1: "slash", 2: "strike", 3: "thrust", 4: "neutral"}   # ATKPARAM_ATKATTR_TYPE
REF_ATTACK, REF_BULLET, REF_SPEFFECT = 0, 1, 2                                     # BEHAVIOR_REF_TYPE


def _get(param, row_id):
    if param is None or row_id is None or row_id < 0:
        return None
    try:
        return param[row_id]
    except (KeyError, IndexError):
        return None


def _fields(row, names) -> dict:
    out = {}
    for f in names:
        if hasattr(row, f):
            v = getattr(row, f)
            out[f] = round(v, 3) if isinstance(v, float) else (int(v) if not isinstance(v, bool) else v)
    return out


def attack(atk_param, atk_id: int) -> dict | None:
    """One AtkParam_Npc row, trimmed: zero radii dropped, attack kind named."""
    row = _get(atk_param, atk_id)
    if row is None:
        return None
    a = {"atk_id": atk_id, **_fields(row, ATK_FIELDS)}
    a["radii"] = [round(float(getattr(row, f"Hitbox{k}Radius", 0) or 0), 3) for k in range(4)]
    a["radii"] = [r for r in a["radii"] if r > 0]
    a["kind"] = ATTACK_KIND.get(a.get("AttackAttribute"), "?")
    return a


def behaviors(params, variation: int) -> dict:
    """{judge_id: entry} for every BehaviorParam row with VariationID == variation."""
    beh, atk, bullets = params["behaviors"], params["attacks"], params["bullets"]
    out = {}
    for row_id, row in (beh.items() if beh is not None else ()):
        if row is None or getattr(row, "VariationID", None) != variation:
            continue
        judge, ref, ref_type = int(row.BehaviorJudgeID), int(row.ReferenceID), int(row.ReferenceType)
        e = {"behavior_id": int(row_id), "stamina_cost": int(getattr(row, "StaminaCost", 0) or 0)}
        if ref_type == REF_ATTACK:
            e["type"], e["attack"] = "attack", attack(atk, ref)
        elif ref_type == REF_BULLET:
            b = _get(bullets, ref)
            e["type"] = "bullet"
            e["bullet"] = None if b is None else {"bullet_id": ref, **_fields(b, BULLET_FIELDS)}
            e["attack"] = attack(atk, int(b.BulletAttack)) if b is not None else None
        elif ref_type == REF_SPEFFECT:
            e["type"], e["sp_effect"] = "sp_effect", ref
        else:
            e["type"], e["ref"] = f"ref{ref_type}", ref
        out[judge] = e
    return dict(sorted(out.items()))


def foe(params, npc_id: int) -> dict | None:
    row = _get(params["npcs"], npc_id)
    if row is None:
        return None
    variation = int(getattr(row, "BehaviorVariationID", 0) or 0)
    beh = behaviors(params, variation)
    hits = [e["attack"] for e in beh.values() if e.get("attack")]
    return {
        "npc_param_id": npc_id, **_fields(row, NPC_FIELDS), "variation": variation,
        "summary": {
            "behaviors": len(beh), "attacks": len(hits),
            "max_physical": max((h.get("PhysicalAttackPower", 0) for h in hits), default=0),
            "max_radius": max((max(h["radii"], default=0) for h in hits), default=0),
            "unblockable": sorted(j for j, e in beh.items() if (e.get("attack") or {}).get("IgnoreGuard")),
            "roll_proof": sorted(j for j, e in beh.items() if (e.get("attack") or {}).get("IgnoreInvincibilityFrames")),
            "bullets": sorted(j for j, e in beh.items() if e["type"] == "bullet"),
        },
        "behaviors": {str(j): e for j, e in beh.items()},
    }


def load_params(game_dir: Path) -> dict:
    path = game_dir / "param" / "GameParam" / "GameParam.parambnd.dcx"
    if not path.exists():
        raise SystemExit(f"GameParam 없음: {path}")
    from soulstruct.darksouls1r.params import GameParamBND
    gp = GameParamBND.from_path(path)
    return {"npcs": gp.Characters, "behaviors": gp.NonPlayerBehaviors, "attacks": gp.NonPlayerAttacks, "bullets": gp.Bullets}


def foes_in_maps(folder: Path = OUT_DIR) -> dict[int, dict]:
    """{npc_param_id: {"model", "maps", "count"}} for the enemies msb_extract wrote (humans c0000 left out)."""
    out: dict[int, dict] = {}
    for f in sorted(folder.glob("m*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        for e in d.get("enemies", []):
            nid = e.get("npc_param_id")
            if e.get("kind") != "enemy" or nid is None or nid < 0:
                continue
            o = out.setdefault(int(nid), {"model": e.get("model"), "maps": [], "count": 0})
            o["count"] += 1
            if d["map_id"] not in o["maps"]:
                o["maps"].append(d["map_id"])
    return out


def extract(params, npc_ids, where: dict | None = None) -> dict:
    where = where or {}
    foes, missing = {}, []
    for nid in sorted(set(npc_ids)):
        f = foe(params, nid)
        if f is None:
            missing.append(nid)
            continue
        foes[str(nid)] = {**where.get(nid, {}), **f}
    return {"evidence": "file", "source": "param/GameParam/GameParam.parambnd.dcx",
            "counts": {"foes": len(foes), "missing": len(missing)}, "missing": missing, "foes": foes}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("npc_ids", nargs="*", type=int, help="NpcParam rows (default: every foe in data/gamefiles/m*.json)")
    ap.add_argument("--out", type=Path, default=OUT_DIR / OUT_NAME)
    a = ap.parse_args()
    where = foes_in_maps()
    ids = a.npc_ids or list(where)
    if not ids:
        raise SystemExit("적 없음 — 먼저 msb_extract.py 로 data/gamefiles/m*.json 을 만들거나 NpcParam 번호를 주세요")
    data = extract(load_params(GAME_DIR), ids, where)
    a.out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    for nid, f in data["foes"].items():
        s = f["summary"]
        print(f"{nid} {f.get('model', '')}: HP {f.get('MaximumHP')} 강인도 {f.get('MaxPoise')} — 공격 {s['attacks']} "
              f"(최대 물리 {s['max_physical']}, 최대 반경 {s['max_radius']}, 막기 불가 {len(s['unblockable'])}, "
              f"구르기 무시 {len(s['roll_proof'])}, 투사체 {len(s['bullets'])})")
    print(f"적 {data['counts']['foes']} (NpcParam 에 없음 {data['missing']}) → {a.out}")


if __name__ == "__main__":
    main()
