"""적 드롭 표 연결 오프라인 테스트 — drop_tables.py (MoKa 2026-11-01: 경로의 적 ↔ 드롭 표, 관측 후보 고르기용. 게임 관측 아님).

  python tests/drop_tables_test.py

Fake params: missing lot row, empty-only lot, several lots, chain (lot+1 …), chain running into another NpcParam's base lot,
flag -2 / 0, cumulative lot, unknown category, NpcParam row missing, all -1. Then, only when the DSR install is there: the
same rows read by an independent byte parser (PARAM row table + ItemLotParam / NpcParam field order) must equal soulstruct's,
and the Firelink treasure flags in data/gamefiles/m10_02_00_00.json must equal what this tool reads for the same lots.
Not checked: anything in the game (whether / how a lot is rolled, luck, what a drop looks like).
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import json
import struct
import sys
from pathlib import Path
from types import SimpleNamespace as NS

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import drop_tables as DT

GOOD, WEAPON = 2 ** 30, 0


def lot(flag=-1, slots=(), cum_flag=-1, cum_max=0):
    """slots: (category, id, count, points[, luck])"""
    r = {"ItemFlag": flag, "FirstCumulativeFlag": cum_flag, "MaxCumulativeAdditions": cum_max}
    for k in range(1, 9):
        s = slots[k - 1] if k <= len(slots) else (-1, 0, 0, 0)
        r.update({f"Item{k}Category": s[0], f"Item{k}ID": s[1], f"Item{k}Count": s[2], f"Item{k}ChancePoints": s[3],
                  f"Item{k}LuckEnabled": (s[4] if len(s) > 4 else False), f"Item{k}Flag": 0,
                  f"Item{k}CumulativePoints": 0, f"Item{k}ResetCumulativePointsOnDrop": False})
    return NS(**r)


def npc(*ids, hum=-1, drop=0):
    ids = list(ids) + [-1] * (6 - len(ids))
    return NS(**{f"ItemLotID{k}": ids[k - 1] for k in range(1, 7)}, HumanityLotID=hum, ItemDropAppearance=drop)


LOTS = {
    100: lot(slots=((-1, 0, 0, 88, True), (GOOD, 292, 1, 10), (GOOD, 292, 2, 2))),   # weighted, empty slot
    101: lot(flag=-2, slots=((-1, 0, 0, 99, True), (2 ** 28, 520000, 1, 1))),          # chain row, flag -2
    200: lot(flag=51010960, slots=((WEAPON, 500000, 1, 100),)),                        # one-time flag, single outcome
    300: lot(slots=((-1, 0, 0, 100, True),)),                                          # empty only
    400: lot(flag=0, slots=((GOOD, 500, 1, 100),)),                                    # flag 0
    500: lot(slots=((-1, 0, 0, 98, True), (WEAPON, 1102000, 1, 2)), cum_flag=9164, cum_max=7),
    501: lot(slots=((GOOD, 1120, 1, 100, True),)),
    600: lot(slots=((12345, 7, 1, 100),)),                                             # unknown category
    700: lot(slots=((GOOD, 1, 1, 100),)),
    701: lot(slots=((GOOD, 2, 1, 100),)),                                              # 701 is also NpcParam 70's base lot
}
NPCS = {1: npc(100), 2: npc(200), 3: npc(300), 4: npc(400), 5: npc(500), 6: npc(600), 7: npc(999),
        8: npc(100, 200), 9: npc(), 60: npc(700), 70: npc(701), 11: npc(0)}
ENEMIES = [{"name": f"c_{n}", "model": "c2540", "kind": "enemy", "entity_id": 1000 + n, "pos": [0, 0, n], "npc_param_id": n}
           for n in (1, 2, 3, 4, 5, 6, 7, 8, 9, 60, 70, 11, 12)]


class Param(dict):
    def __getitem__(self, k):
        return dict.__getitem__(self, k)


def by_id(out):
    return {n["npc_param_id"]: n for n in out["npcs"]}


def test_fake_params() -> None:
    out = by_id(DT.build({"enemies": ENEMIES}, Param(NPCS), Param(LOTS), {("good", 292): "Firebomb"},
                         seen={1: ["a", "b"]}))
    a = out[1]["lots"][0]
    assert a["status"] == "ok" and a["class"] == "chain_unresolved" and [r["row"] for r in a["rows"]] == [100, 101]
    assert a["flags_raw"] == [-1, -2] and a["any_unresolved"] and a["rows"][1]["flag_meaning"] == "unresolved"
    s = a["rows"][0]["slots"]
    assert [x["category"] for x in s] == ["empty", "good", "good"] and s[1]["name"] == "Firebomb"
    assert [x["weight_share"] for x in s] == [0.88, 0.1, 0.02] and a["rows"][0]["has_empty_slot"]
    assert out[1]["seen_runs"] == 2 and out[2]["seen_runs"] == 0
    print("ok  weighted lot: empty slot kept as 'empty', shares 0.88/0.10/0.02 (no probability claim), chain row flag -2 unresolved")
    b = out[2]["lots"][0]
    assert b["class"] == "table_single_outcome" and b["flags_raw"] == [51010960] and b["rows"][0]["flag_meaning"] == "one_time_flag"
    print("ok  single slot, flag 51010960 → 'table_single_outcome' + one_time_flag, flag taken from the row (not 50,000,000 + lot)")
    assert out[3]["lots"][0]["class"] == "table_empty_only"
    assert out[4]["lots"][0]["rows"][0]["flag_meaning"] == "unresolved"
    print("ok  empty-only lot → 'table_empty_only'; flag 0 → unresolved (not 'none')")
    c = out[5]["lots"][0]
    assert c["class"] == "chain_unresolved" and c["rows"][0]["cumulative"] == {"first_flag": 9164, "max_additions": 7, "used": True}
    assert not c["rows"][0]["table_single_outcome"]
    print("ok  cumulative lot: kept raw, chain → unresolved; the chained row's single slot doesn't make the lot single-outcome")
    assert out[6]["lots"][0]["class"] == "unsupported" and out[6]["lots"][0]["any_unresolved"]
    print("ok  unknown category → 'unsupported', not a drop")
    assert out[7]["lots"][0]["status"] == "missing_row" and out[7]["lots"][0]["rows"] == []
    print("ok  lot id with no row → 'missing_row' (not an empty drop)")
    assert [l["lot"] for l in out[8]["lots"]] == [100, 200]
    print("ok  two lot ids → both kept in order")
    assert out[9]["status"] == "no_lot_ids(all -1)" and out[9]["lots"] == []
    assert out[11]["lots"][0]["status"] == "unresolved_id"
    assert out[12]["status"] == "npc_row_missing" and "lots" not in out[12]
    print("ok  all -1 → 'no_lot_ids'; lot id 0 → 'unresolved_id'; NpcParam row missing → 'npc_row_missing'")
    d = out[60]["lots"][0]
    assert d["status"] == "chain_stops_at_other_base" and [r["row"] for r in d["rows"]] == [700]
    assert [r["row"] for r in out[70]["lots"][0]["rows"]] == [701]
    print("ok  chain stops before another NpcParam's base lot (700 doesn't swallow 701)")


def test_chain_cap() -> None:
    lots = Param({1000 + i: lot(slots=((GOOD, 1, 1, 100),)) for i in range(DT.CHAIN_MAX + 5)})
    out = by_id(DT.build({"enemies": [dict(ENEMIES[0], npc_param_id=1)]}, Param({1: npc(1000)}), lots, {}))
    l = out[1]["lots"][0]
    assert l["status"] == "chain_cap" and l["class"] == "unsupported" and len(l["rows"]) == DT.CHAIN_MAX + 1
    print(f"ok  chain longer than CHAIN_MAX ({DT.CHAIN_MAX}) → 'chain_cap', marked unsupported (not cut silently)")


def test_read_error_propagates() -> None:
    class Broken(dict):
        def __getitem__(self, k):
            raise OSError("read failed")
    try:
        DT.build({"enemies": ENEMIES[:1]}, Param(NPCS), Broken(), {})
    except OSError:
        print("ok  a read error other than 'no such row' propagates (not turned into 'no drop')")
        return
    raise AssertionError("read error swallowed")


# ── independent byte parser (only with the DSR install) ─────────────────────
ITEMLOT = struct.Struct("<8i8i8H8H8iiiBB8B2s")          # 0x94: ids, categories, base points, cumulative points, slot flags,
                                                       # getItemFlagId, cumulateNumFlagId, cumulateNumMax, rarity, counts, bits
assert ITEMLOT.size == 0x94


def raw_rows(data: bytes) -> tuple[dict[int, int], int]:
    """PARAM: u32 strings_off, u16 data_off, …, u16 row_count at 0x0A; 12-byte row table (id, data_off, name_off) from 0x30."""
    n = struct.unpack_from("<H", data, 0x0A)[0]
    rows = {}
    for i in range(n):
        rid, off, _ = struct.unpack_from("<III", data, 0x30 + 12 * i)
        rows[rid] = off
    return rows, n


def test_raw_vs_soulstruct() -> None:
    try:
        import navmesh  # noqa: F401
        from navmesh import GAME_DIR
    except Exception as ex:  # noqa: BLE001
        print(f"skip raw: {ex!r}")
        return
    gp_path = GAME_DIR / "param" / "GameParam" / "GameParam.parambnd.dcx"
    mj = Path(DT.ROOT) / "data" / "gamefiles" / "m10_01_00_00.json"
    if not gp_path.exists() or not mj.exists():
        print(f"skip raw: {gp_path} not here")
        return
    from soulstruct.containers import Binder
    from soulstruct.darksouls1r.params import GameParamBND
    raw = {Path(e.path).name: e.get_uncompressed_data() for e in Binder.from_path(gp_path).entries}
    lots_b, npc_b = raw["ItemLotParam.param"], raw["NpcParam.param"]
    lot_off, n_lot = raw_rows(lots_b)
    npc_off, n_npc = raw_rows(npc_b)
    gp = GameParamBND.from_path(gp_path)
    npc_ids = sorted({e["npc_param_id"] for m in ("m10_01_00_00", "m10_02_00_00")
                      for e in json.loads((Path(DT.ROOT) / "data" / "gamefiles" / f"{m}.json").read_text(encoding="utf-8"))["enemies"]})
    checked_npc = checked_lot = 0
    lot_ids: set[int] = set()
    for nid in npc_ids:
        if nid not in npc_off:
            assert DT._get(gp.Characters, nid) is None, nid
            continue
        # NpcParam itemLotId_1..6 at +0x2C, humanityLotId at +0x44 (soulsmodding ds1-refmat NpcParam offsets)
        ids = list(struct.unpack_from("<6i", npc_b, npc_off[nid] + 0x2C))
        hum = struct.unpack_from("<i", npc_b, npc_off[nid] + 0x44)[0]
        r = gp.Characters[nid]
        assert ids == [getattr(r, f"ItemLotID{k}") for k in range(1, 7)] and hum == r.HumanityLotID, nid
        checked_npc += 1
        for i in ids:
            x = i
            while i > 0 and x in lot_off:
                lot_ids.add(x)
                x += 1
    for lid in sorted(lot_ids):
        v = ITEMLOT.unpack_from(lots_b, lot_off[lid])
        r = gp.ItemLots[lid]
        mine = {"ids": list(v[0:8]), "cats": list(v[8:16]), "pts": list(v[16:24]), "flag": v[40], "cum": v[41],
                "cum_max": v[42], "counts": list(v[44:52])}
        theirs = {"ids": [getattr(r, f"Item{k}ID") for k in range(1, 9)],
                  "cats": [getattr(r, f"Item{k}Category") for k in range(1, 9)],
                  "pts": [getattr(r, f"Item{k}ChancePoints") for k in range(1, 9)], "flag": r.ItemFlag,
                  "cum": r.FirstCumulativeFlag, "cum_max": r.MaxCumulativeAdditions,
                  "counts": [getattr(r, f"Item{k}Count") for k in range(1, 9)]}
        assert mine == theirs, (lid, mine, theirs)
        checked_lot += 1
    print(f"ok  raw bytes = soulstruct: {checked_npc} NpcParam rows (lot ids, humanity id) · {checked_lot} ItemLotParam rows "
          f"(ids, categories, points, counts, flag, cumulative) of Burg + Firelink enemies; tables {n_npc} / {n_lot} rows")
    fl = json.loads((Path(DT.ROOT) / "data" / "gamefiles" / "m10_02_00_00.json").read_text(encoding="utf-8"))["treasures"]
    same = 0
    for t in fl:
        flags = [f for f in (DT.lot_row(gp.ItemLots[l], {})["item_flag"] for l in t["item_lots"] if DT._get(gp.ItemLots, l))
                 if f > 0]
        assert flags == t["flags"], (t["name"], flags, t["flags"])
        same += 1
    print(f"ok  Firelink treasures: flags read here = msb_extract's for {same}/{len(fl)} (incl. 宝死体00 lot 1020000 → 51020000)")


if __name__ == "__main__":
    test_fake_params()
    test_chain_cap()
    test_read_error_propagates()
    test_raw_vs_soulstruct()
    print("all ok")
