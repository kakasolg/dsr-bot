"""Extract objects and enemies from the game files — what the MSB (map layout) and GameParam say, before any play.

  python msb_extract.py <mapID> [<mapID> ...]      → data/gamefiles/<mapID>.json
  python msb_extract.py m10_01_00_00 --no-params    MSB only (skip GameParam)

Reads (DSR install folder, DSR_GAME_DIR like navmesh.py):
  map/MapStudio/<mapID>.msb                     objects · enemies · patrol regions
  param/GameParam/GameParam.parambnd.dcx        ObjectParam (HP, breakable) · NpcThinkParam (sight, hearing, retreat)

Evidence grade of everything written here: "file" — it is what the game data says, not yet seen in play (LAYERS.md).
Units are raw param values; which ones are metres is still to be checked in play (ROADMAP.md 2).
  · ObjectParam row = object model number (o1200 → 1200) is the usual DS1 convention — unverified here, hence
    "param_row_found". An object with no row, or ObjectHP -1 / PreventAllDamage, is treated as not breakable.
  · "min_attack" = ObjectParam MinAttackForDamage. At or above STRONG_MIN_ATTACK a light attack may not break it (Burg: 12 objects at 90)
    — counted apart as "breakable_strong" (ROADMAP P-4).
  · counts: "enemies" = non-human characters only; "humans" = c0000 (NPCs, phantoms); "characters" = both.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import navmesh   # noqa: F401 — stubs the soulstruct modules whose data files the wheel lacks (see navmesh.py)
from navmesh import GAME_DIR

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

OUT_DIR = Path(__file__).parent / "data" / "gamefiles"
STRONG_MIN_ATTACK = 50

THINK_FIELDS = (
    "SightDistance", "SightRangeWidth", "SightRangeHeight", "SightForgetTime",
    "HearingDistance", "HearingCutDistance", "HearingRangeWidth", "HearingRangeHeight", "HearingForgetTime",
    "SmellDistance", "BattleStartDistance", "MaxRetreatDistance", "BattleRetreatDistance",
    "RetreatBattleStartDistance", "SearchTimeBeforeRetreat", "SearchDistanceBeforeRetreat",
    "NearDistance", "MidDistance", "FarDistance", "OutOfRangeDistance",
    "HelpGroupID", "HelpCallGroupID", "HelpCallFriendMaxDistance",
    "LogicID", "BattleID",
    "CanFallOffEdges", "CanNavigateLadders", "CanNavigateDoors",
)
OBJECT_FIELDS = (
    "ObjectHP", "MinAttackForDamage", "BrokenByPlayerCollision", "HasDestructionAnimation",
    "PreventAllDamage", "IsLadder", "IsMovingObject", "CharacterCollision",
)


def _vec(v) -> list[float]:
    return [round(float(v.x), 3), round(float(v.y), 3), round(float(v.z), 3)]


def _model_number(model_name: str) -> int | None:
    m = re.match(r"^[oc](\d+)", model_name or "")
    return int(m.group(1)) if m else None


def _row(param, row_id: int | None, fields: tuple[str, ...]) -> dict | None:
    if param is None or row_id is None or row_id < 0:
        return None
    try:
        row = param[row_id]
    except (KeyError, IndexError):
        return None
    if row is None:
        return None
    return {f: getattr(row, f) for f in fields if hasattr(row, f)}


def load_params(game_dir: Path):
    """(ObjectParam, NpcThinkParam) or (None, None) with a warning."""
    path = game_dir / "param" / "GameParam" / "GameParam.parambnd.dcx"
    if not path.exists():
        print(f"경고: GameParam 없음 — {path} (MSB 정보만 저장)")
        return None, None
    from soulstruct.darksouls1r.params import GameParamBND
    gp = GameParamBND.from_path(path)
    return gp.Objects, gp.AI


def is_breakable(p: dict | None) -> bool:
    if p is None:               # params loaded but no row for this model
        return False
    if p.get("PreventAllDamage") or p.get("IsLadder"):
        return False
    hp = p.get("ObjectHP")
    return hp is not None and hp > 0


def extract(map_id: str, game_dir: Path = GAME_DIR, with_params: bool = True, msb=None) -> dict:
    """msb can be passed in directly (tests); otherwise it is read from the install folder."""
    if msb is None:
        from soulstruct.darksouls1r.maps import MSB
        path = game_dir / "map" / "MapStudio" / f"{map_id}.msb"
        if not path.exists():
            raise SystemExit(f"MSB 없음: {path}")
        msb = MSB.from_path(path)
    obj_param, think_param = load_params(game_dir) if with_params else (None, None)

    objects = []
    for o in msb.objects:
        model = o.model.name if o.model else ""
        row_id = _model_number(model)
        p = _row(obj_param, row_id, OBJECT_FIELDS)
        objects.append({
            "name": o.name, "model": model, "entity_id": o.entity_id,
            "pos": _vec(o.translate), "rot_y": round(float(o.rotate.y), 2),
            "break_term": getattr(o, "break_term", None),
            "param_row_found": p is not None if obj_param is not None else None,
            "breakable": is_breakable(p) if obj_param is not None else None,
            "min_attack": (p or {}).get("MinAttackForDamage"),
            "param": p,
        })

    enemies = []
    for c in msb.characters:
        model = c.model.name if c.model else ""
        if model == "c0000":        # human-shaped: NPCs/phantoms — kept, flagged, the bot decides
            kind = "human"
        else:
            kind = "enemy"
        patrol = []
        for r in (getattr(c, "patrol_regions", None) or []):
            if r is not None and getattr(r, "translate", None) is not None:
                patrol.append({"name": r.name, "pos": _vec(r.translate)})
        enemies.append({
            "name": c.name, "model": model, "kind": kind, "entity_id": c.entity_id,
            "pos": _vec(c.translate), "rot_y": round(float(c.rotate.y), 2),
            "npc_param_id": c.character_id, "ai_id": c.ai_id, "talk_id": c.talk_id,
            "patrol_type": c.patrol_type, "patrol": patrol,
            "default_animation": c.default_animation,
            "think": _row(think_param, c.ai_id, THINK_FIELDS),
        })

    return {
        "map_id": map_id,
        "evidence": "file",
        "source": {"msb": f"map/MapStudio/{map_id}.msb",
                   "params": "param/GameParam/GameParam.parambnd.dcx" if obj_param is not None else None},
        "counts": {"objects": len(objects),
                   "breakable": sum(1 for o in objects if o["breakable"]),
                   "breakable_strong": sum(1 for o in objects if o["breakable"] and (o["min_attack"] or 0) >= STRONG_MIN_ATTACK),
                   "characters": len(enemies),
                   "enemies": sum(1 for e in enemies if e["kind"] == "enemy"),
                   "humans": sum(1 for e in enemies if e["kind"] == "human"),
                   "with_patrol": sum(1 for e in enemies if e["patrol"])},
        "objects": objects,
        "enemies": enemies,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("map_ids", nargs="+", help="e.g. m10_01_00_00")
    ap.add_argument("--no-params", action="store_true", help="skip GameParam (MSB only)")
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    for map_id in a.map_ids:
        data = extract(map_id, with_params=not a.no_params)
        path = a.out / f"{map_id}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        c = data["counts"]
        print(f"{map_id}: 오브젝트 {c['objects']} (부서짐 {c['breakable']}, 강공 필요 {c['breakable_strong']}), "
              f"캐릭터 {c['characters']} = 적 {c['enemies']} + 사람형 {c['humans']} (순찰 {c['with_patrol']}) → {path}")


if __name__ == "__main__":
    main()
