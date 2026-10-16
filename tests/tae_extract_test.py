"""tae_extract offline test — a fake DSR TAE built byte by byte in the layout tae_extract reads, no game files.

This checks the reader against that layout; whether the layout (and p[2] = BehaviorJudgeID) matches the real files is
what the [win] run's judge_check shows.

  python tests/tae_extract_test.py
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import json
import struct
import tempfile
from pathlib import Path
from types import SimpleNamespace

import tae_extract as X


def build_tae(anims: dict, tae_id=0, borrow: dict | None = None) -> bytes:
    """anims: {anim_id: [(type, start, end, [i32 params])]}; borrow: {anim_id: other id} (no events, file type 1)."""
    borrow = borrow or {}
    ids = sorted(set(anims) | set(borrow))
    buf = bytearray(0xC0)
    buf[0:4] = b"TAE "
    buf[4:8] = bytes([0, 0, 0, 0xFF])
    struct.pack_into("<ii", buf, 8, 0x1000C, 0)
    struct.pack_into("<ii", buf, 0x50, tae_id, len(ids))
    anims_off = len(buf)
    struct.pack_into("<q", buf, 0x58, anims_off)
    buf += bytes(16 * len(ids))
    for k, aid in enumerate(ids):
        a = len(buf)
        struct.pack_into("<qq", buf, anims_off + 16 * k, aid, a)
        buf += bytes(0x30)
        evs = anims.get(aid, [])
        ev_off = len(buf)
        buf += bytes(24 * len(evs))
        for j, (etype, start, end, p) in enumerate(evs):
            ts = len(buf)
            buf += struct.pack("<ff", start, end)
            data = len(buf)
            buf += struct.pack("<qq", etype, data + 16) + struct.pack(f"<{len(p)}i", *p) + bytes(4 * (4 - len(p)))
            struct.pack_into("<qqq", buf, ev_off + 24 * j, ts, ts + 4, data)
        f = len(buf)
        buf += struct.pack("<qqqii", 1 if aid in borrow else 0, f + 16, 0, borrow.get(aid, 0), 0) + bytes(16)
        struct.pack_into("<qqqq", buf, a, ev_off, 0, 0, f)
        struct.pack_into("<iii", buf, a + 0x20, len(evs), 0, 0)
    struct.pack_into("<i", buf, 12, len(buf))
    return bytes(buf)


HOLLOW = {
    3000: [(1, 0.5, 0.7, [0, 0, 100, 0]), (128, 0.4, 0.5, [1, 2]), (0, 0.0, 1.2, [4])],
    3001: [(1, 0.9333, 1.1, [0, 0, 101, 0]), (2, 1.2, 1.3, [0, 0, 180, 0])],
    3005: [(1, 0.3, 0.4, [0, 0, 999, 0])],                    # judge id not in combat.json → shows in judge_check
    3500: [(5, 0.0, 0.2, [0, 16])],                           # 'common': p[2] is not a judge id → not in attacks
}


def test_read_tae():
    t = X.read_tae(build_tae(HOLLOW, tae_id=7, borrow={3009: 3000}))
    assert t["tae_id"] == 7 and list(t["animations"]) == [3000, 3001, 3005, 3009, 3500]
    a = t["animations"][3000]
    assert a["events"] == [{"type": 1, "start": 0.5, "end": 0.7, "p": [0, 0, 100, 0]}]   # time-sorted, kept types only
    assert a["other_types"] == {"0": 1, "128": 1} and a["ref"] is None
    assert t["animations"][3001]["events"][0]["start"] == 0.9333
    assert t["animations"][3009] == {"events": [], "other_types": {}, "ref": 3000}


def test_read_tae_rejects():
    good = build_tae(HOLLOW)
    for bad in (b"XXXX" + good[4:], good[:7] + b"\x00" + good[8:], good[:8] + struct.pack("<i", 0x1000B) + good[12:]):
        try:
            X.read_tae(bad)
        except X.TAEError:
            continue
        raise AssertionError("bad TAE accepted")


def build_tae32(anims: dict, tae_id=0, borrow: dict | None = None) -> bytes:
    """32-bit layout (version 0x1000B) — what the real chr/*.anibnd.dcx hold (10-16 [win] run, c2540 bytes)."""
    borrow = borrow or {}
    ids = sorted(set(anims) | set(borrow))
    buf = bytearray(0xC0)
    buf[0:4] = b"TAE "
    struct.pack_into("<ii", buf, 8, 0x1000B, 0)
    anims_off = len(buf)
    struct.pack_into("<iii", buf, 0x50, tae_id, len(ids), anims_off)
    buf += bytes(8 * len(ids))
    for k, aid in enumerate(ids):
        a = len(buf)
        struct.pack_into("<ii", buf, anims_off + 8 * k, aid, a)
        buf += bytes(0x1C)
        evs = anims.get(aid, [])
        ev_off = len(buf)
        buf += bytes(12 * len(evs))
        for j, (etype, start, end, p) in enumerate(evs):
            ts = len(buf)
            buf += struct.pack("<ff", start, end)
            data = len(buf)
            buf += struct.pack("<ii", etype, data + 8) + struct.pack(f"<{len(p)}i", *p) + bytes(4 * (4 - len(p)))
            struct.pack_into("<iii", buf, ev_off + 12 * j, ts, ts + 4, data)
        f = len(buf)
        buf += struct.pack("<iiii", 1 if aid in borrow else 0, f + 16, f + 16, borrow.get(aid, 0)) + bytes(16)
        struct.pack_into("<ii", buf, a, len(evs), ev_off)
        struct.pack_into("<i", buf, a + 0x18, f)
    struct.pack_into("<i", buf, 12, len(buf))
    return bytes(buf)


def test_read_tae32_same_as_64():
    assert X.read_tae(build_tae32(HOLLOW, tae_id=7, borrow={3009: 3000})) == \
        X.read_tae(build_tae(HOLLOW, tae_id=7, borrow={3009: 3000}))


def test_extract_attacks_and_check():
    entries = [SimpleNamespace(name="c2540.tae", data=build_tae(HOLLOW)), SimpleNamespace(name="c2540.hkxbnd", data=b"")]
    d = X.extract("c2540", entries, known={100, 101, 180, 400})
    assert d["status"] == "parsed"
    assert d["attacks"]["100"] == [{"anim": 3000, "type": "attack", "active_start": 0.5, "active_end": 0.7}]
    assert d["attacks"]["180"] == [{"anim": 3001, "type": "bullet", "active_start": 1.2, "active_end": 1.3}]
    assert "0" not in d["attacks"] and "16" not in d["attacks"]           # type 5 left out
    assert d["animations"]["3000"]["tae"] == "c2540.tae"
    assert d["counts"] == {"animations": 4, "borrowed": 0, "events": {"attack": 3, "bullet": 1, "common": 1}, "other_events": 2}
    assert d["judge_check"] == {
        "attack": {"n": 3, "in_combat_json": 2, "share": 0.667, "mismatch": [{"anim": 3005, "value": 999}]},
        "bullet": {"n": 1, "in_combat_json": 1, "share": 1.0, "mismatch": []}}, d["judge_check"]
    json.dumps(d)


def test_models_from_combat():
    with tempfile.TemporaryDirectory() as t:
        p = Path(t) / "combat.json"
        p.write_text(json.dumps({"foes": {"254010": {"model": "c2540", "behaviors": {"0": {}, "100": {}}},
                                          "254001": {"model": "c2540", "behaviors": {"180": {}}},
                                          "999": {"behaviors": {"1": {}}}}}), encoding="utf-8")
        assert X.models_from_combat(p) == {"c2540": {0, 100, 180}}


def test_rebuild_matches_extract():
    """--rebuild (no game files) gives the same as a fresh extract from the raw animations it stored."""
    entries = [SimpleNamespace(name="c2540.tae", data=build_tae32(HOLLOW, borrow={3009: 3000}))]
    d = json.loads(json.dumps(X.extract("c2540", entries, known={100, 101, 180})))
    again = X.summarize("c2540", {int(k): v for k, v in d["animations"].items()}, {100, 101, 180})
    assert json.loads(json.dumps(again)) == d and d["counts"]["borrowed"] == 1


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
