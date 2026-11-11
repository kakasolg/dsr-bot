"""Enemy drop tables from the game files — placed enemy → NpcParam → itemLotId → ItemLotParam rows, before any play.

  python drop_tables.py m10_01_00_00 [m10_02_00_00 ...]        → data/gamefiles/<mapID>-drops.json
  python drop_tables.py m10_01_00_00 --tracks "data/samples/*burg-upper*.track.jsonl"   + runs whose live snapshots saw each NpcParam

Reads: data/gamefiles/<mapID>.json (msb_extract.py output: enemies[].npc_param_id, entity_id, pos) and the DSR install's
param/GameParam/GameParam.parambnd.dcx (NpcParam, ItemLotParam through soulstruct, already a dependency — GPL-3.0-or-later; no
code copied from it or from any mod) and msg/ENGLISH item names (msb_extract.load_item_names). msb_extract.py is not changed.
The output keeps the sha256 of every input file. Nothing here touches the game process.

Evidence grade "file": what the game data says. Not seen in play: whether a lot is rolled at death, how the chain is walked,
what luck / cumulative points do, what a drop looks like. Read-failure / missing row / unknown structure are kept as their own
status — never turned into "no drop".
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent
OUT_DIR = ROOT / "data" / "gamefiles"
CHAIN_MAX = 16          # rows followed after the base lot; more is reported as "chain_cap", not cut silently

# lotItemCategory (soulstruct ITEMLOT_ITEMCATEGORY: 0 weapon · 0x10000000 armor · 0x20000000 ring · 0x40000000 good); -1 + id 0 = empty slot
CATEGORY = {0: "weapon", 2 ** 28: "armor", 2 ** 29: "ring", 2 ** 30: "good"}

# ── 해석하지 않고 원값으로 남기는 것 ─────────────────────────────
#  · 가중치(ChancePoints)는 행 안의 상대값일 뿐 — 운(LuckEnabled), 누적(Cumulative*), 묶음 처리 방식이 게임에서 확인되지 않아
#    "weight_share"로만 쓰고 확률이라 부르지 않는다. 합이 100이 아닌 행도 있다 (25500004: 984 + 16).
#  · 묶음(lot, lot+1, …): 다음 번호 행이 있으면 이어 읽는다 (soulsmodding wikidot ItemLotParam, FogMod ItemReader.cs의 lot+1 반복 —
#    외부 서술, 게임 미확인). 이어진 행의 ItemFlag가 -2인 경우가 많은데 -2의 뜻은 출처가 없다 → "flag_meaning": "unresolved".
#  · ItemFlag > 0 = 줍는 순간 켜지는 이벤트 플래그로 보는 근거는 보물 1건(51020000, 11-01 게임에서 False→True)뿐. 적 lot의 플래그는
#    게임에서 읽어 본 적이 없다. 그리고 적 lot의 플래그는 50,000,000 + lot이 아니다 (25100100 → 51010960) — 그 규칙을 쓰지 않는다.
#  · 플래그가 켜져 있다 = "이미 받았다"는 추정이고, "지금 바닥/시체에 드롭이 있다"는 뜻이 아니다. 이 도구는 후자를 전혀 모른다.
#  · NpcParam humanityLotId: soulstruct 설명이 "I think" (인간성 카운터 시작 플래그?) → 원값만, lot으로 따라가지 않는다.
#  · NpcParam dropType: 0/1의 모양 설명이 soulstruct와 soulsmodding 위키가 엇갈림 → 원값만.
#  · 보스 보상·대화·이벤트로 주는 아이템은 이벤트 스크립트(emevd) 쪽이라 여기 안 나온다.


def sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _get(param, row_id: int):
    """Row or None (missing). Read errors other than a missing key propagate — they are not 'no row'."""
    try:
        return param[row_id]
    except (KeyError, IndexError):
        return None


def lot_row(row, names: dict) -> dict:
    """One ItemLotParam row as raw values + light labels."""
    slots, total = [], 0
    for k in range(1, 9):
        cat_raw = getattr(row, f"Item{k}Category")
        iid = getattr(row, f"Item{k}ID")
        pts = getattr(row, f"Item{k}ChancePoints")
        if not pts and not iid:
            continue
        total += pts
        if iid == 0 and cat_raw in (-1, 0xFFFFFFFF):
            cat = "empty"
        else:
            cat = CATEGORY.get(cat_raw, "unknown_category")
        slots.append({
            "slot": k, "category": cat, "category_raw": cat_raw, "id": iid,
            "name": names.get((cat, iid)) if cat not in ("empty", "unknown_category") else None,
            "count": getattr(row, f"Item{k}Count"), "points": pts,
            "luck": bool(getattr(row, f"Item{k}LuckEnabled")),
            "slot_flag_raw": getattr(row, f"Item{k}Flag"),
            "cumulative_points": getattr(row, f"Item{k}CumulativePoints"),
            "reset_cumulative": bool(getattr(row, f"Item{k}ResetCumulativePointsOnDrop")),
        })
    for s in slots:
        s["weight_share"] = round(s["points"] / total, 4) if total else None
    flag = row.ItemFlag
    items = [s for s in slots if s["category"] not in ("empty",)]
    out = {
        "item_flag": flag,
        "flag_meaning": ("one_time_flag" if flag > 0 else "none(-1)" if flag == -1 else "unresolved"),
        "cumulative": {"first_flag": row.FirstCumulativeFlag, "max_additions": row.MaxCumulativeAdditions,
                       "used": row.FirstCumulativeFlag not in (-1, 0) or bool(row.MaxCumulativeAdditions)},
        "points_total": total, "slots": slots,
        "has_empty_slot": any(s["category"] == "empty" and s["points"] > 0 for s in slots),
        "unknown_category": any(s["category"] == "unknown_category" for s in slots),
    }
    # "table_single_outcome": one item slot holds every point and no empty slot — what the table says, not a verified guarantee
    out["table_single_outcome"] = (len(items) == 1 and total > 0 and items[0]["points"] == total
                                   and not out["unknown_category"] and not out["cumulative"]["used"])
    return out


def lot_chain(lots, base: int, names: dict, base_lots: set[int]) -> dict:
    """Base lot and the rows after it (lot+1, …) while they exist."""
    if base == -1:
        return {"lot": base, "status": "none(-1)", "rows": []}
    if base <= 0:
        return {"lot": base, "status": "unresolved_id", "rows": []}
    row = _get(lots, base)
    if row is None:
        return {"lot": base, "status": "missing_row", "rows": []}
    rows, x, status = [], base, "ok"
    while row is not None:
        rows.append({"row": x, **lot_row(row, names)})
        x += 1
        if x in base_lots:              # the next row is some NpcParam's own base lot — don't swallow it
            status = "chain_stops_at_other_base"
            break
        if len(rows) > CHAIN_MAX:
            status = "chain_cap"
            break
        row = _get(lots, x)
    flags = [r["item_flag"] for r in rows]
    unresolved = any(r["flag_meaning"] == "unresolved" or r["unknown_category"] for r in rows)
    first = rows[0]
    # lot-level reading of the table (not of the game): a later row's single slot says nothing about the lot as a whole
    if status != "ok" or first["unknown_category"]:
        cls = "unsupported"
    elif len(rows) == 1 and first["table_single_outcome"]:
        cls = "table_single_outcome"
    elif len(rows) == 1 and first["points_total"] and not any(s["category"] != "empty" for s in first["slots"]):
        cls = "table_empty_only"
    elif len(rows) == 1:
        cls = "weighted_one_row"
    else:
        cls = "chain_unresolved"          # several rows: how each row is rolled / granted is not known
    return {"lot": base, "status": status, "class": cls,
            "chain_rule": "next row while it exists (external description, not seen in play)",
            "rows": rows, "flags_raw": flags,
            "any_one_time_flag": any(f > 0 for f in flags), "any_unresolved": unresolved}


def seen_in_tracks(pattern: str | None) -> tuple[dict[int, list[str]], list[str]]:
    """{npc_param: [run files whose live snapshots listed it]} from *.track.jsonl (recorded reads, past runs)."""
    if not pattern:
        return {}, []
    files = sorted(glob.glob(pattern))
    seen: dict[int, set[str]] = {}
    for f in files:
        name = Path(f).name
        for line in Path(f).read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("type") != "snap":
                continue
            for ch in r.get("chars") or ():
                n = ch.get("npc")
                if n:
                    seen.setdefault(int(n), set()).add(name)
    return {k: sorted(v) for k, v in seen.items()}, files


def build(map_json: dict, npc, lots, names: dict, seen: dict[int, list[str]] | None = None) -> dict:
    """npc / lots: soulstruct Param-like (param[row_id] → row or KeyError)."""
    by_npc: dict[int, list[dict]] = {}
    for e in map_json.get("enemies", []):
        by_npc.setdefault(e["npc_param_id"], []).append(e)
    # every base lot any NpcParam in the file points to (chains must not run into another's base)
    base_lots: set[int] = set()
    rows_npc = {}
    for nid in by_npc:
        r = _get(npc, nid)
        rows_npc[nid] = r
        if r is not None:
            base_lots |= {getattr(r, f"ItemLotID{k}") for k in range(1, 7)} - {-1, 0}
    out = []
    for nid, ents in sorted(by_npc.items()):
        r = rows_npc[nid]
        entry = {"npc_param_id": nid, "kind": sorted({e.get("kind") for e in ents}),
                 "models": sorted({e.get("model") for e in ents}),
                 "placed": [{"name": e["name"], "entity_id": e.get("entity_id"), "pos": e.get("pos")} for e in ents],
                 "seen_runs": None if seen is None else len(seen.get(nid, []))}
        if r is None:
            entry["status"] = "npc_row_missing"
            out.append(entry)
            continue
        ids = [getattr(r, f"ItemLotID{k}") for k in range(1, 7)]
        entry.update({
            "status": "ok", "item_lot_ids_raw": ids,
            "humanity_lot_id_raw": r.HumanityLotID, "drop_type_raw": r.ItemDropAppearance,
            "lots": [lot_chain(lots, i, names, base_lots - {i}) for i in ids if i != -1],
        })
        if not entry["lots"]:
            entry["status"] = "no_lot_ids(all -1)"
        out.append(entry)
    return {"npcs": out}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("map_ids", nargs="+")
    ap.add_argument("--tracks", help='glob of *.track.jsonl, e.g. "data/samples/*burg-upper*.track.jsonl"')
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    import navmesh  # noqa: F401 — stubs soulstruct modules whose data files the wheel lacks
    from navmesh import GAME_DIR
    from msb_extract import load_item_names
    from soulstruct.darksouls1r.params import GameParamBND
    from importlib.metadata import version
    ss_version = version("soulstruct")
    gp_path = GAME_DIR / "param" / "GameParam" / "GameParam.parambnd.dcx"
    if not gp_path.exists():
        raise SystemExit(f"GameParam 없음: {gp_path} — 빈 드롭으로 쓰지 않고 멈춤")
    gp = GameParamBND.from_path(gp_path)
    names = load_item_names(GAME_DIR)
    seen, track_files = seen_in_tracks(a.tracks)
    msg_dir = GAME_DIR / "msg" / "ENGLISH"
    for map_id in a.map_ids:
        mj_path = ROOT / "data" / "gamefiles" / f"{map_id}.json"
        data = build(json.loads(mj_path.read_text(encoding="utf-8")), gp.Characters, gp.ItemLots, names,
                     seen if a.tracks else None)
        data = {
            "map_id": map_id, "evidence": "file",
            "source": {
                "map_json": {"path": str(mj_path.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256(mj_path)},
                "gameparam": {"path": "param/GameParam/GameParam.parambnd.dcx", "sha256": sha256(gp_path)},
                "item_names": {"path": "msg/ENGLISH/item.msgbnd.dcx", "sha256": sha256(msg_dir / "item.msgbnd.dcx")},
                "parser": f"soulstruct {ss_version} (GPL-3.0-or-later), darksouls1r GameParamBND",
                "tracks": {"pattern": a.tracks, "files": len(track_files)} if a.tracks else None,
            },
            "notes": "weight_share is a share of points inside one row, not a probability. Flags: see drop_tables.py header.",
            **data,
        }
        path = a.out / f"{map_id}-drops.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        st = {}
        for n in data["npcs"]:
            st[n["status"]] = st.get(n["status"], 0) + 1
        print(f"{map_id}: NpcParam {len(data['npcs'])} {st} → {path}")


if __name__ == "__main__":
    main()
