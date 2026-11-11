"""souls/route_fp — route parse / validation / fingerprint, pure (texts in, no files, no game).  python tests/route_fp_test.py"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import copy
import dataclasses
import hashlib
import json

from souls import route_fp as F

MAP = "m10_01_00_00"
ROOT = _pl.Path(__file__).resolve().parent.parent


def route(**over) -> dict:
    R = {"schema": F.SCHEMA, "map": MAP, "_source": "data/observe/x.jsonl",
         "validation": {"traversal": {"status": "unvalidated"}}, "review": "r", "note": "n",
         "requires": [{"what": "bell", "flag": 11010700, "want": True}],
         "legs": [{"tag": "a", "mode": "walk", "points": [[24.77, 9.5, -22.87], [30, 10, 0]], "ignore_npcs": [7, 3]},
                  {"tag": "b", "points": [[30, 10, 0], [88.46, 14.97, 106.96]]}]}
    R.update(over)
    return R


def spots(**over) -> dict:
    S = {"parish-bonfire": {"map": MAP, "stand": [24.77, 9.5, -22.87], "heading": 2.597, "bonfire_id": 1012961,
                            "sitting_verified": True, "note": "x"},
         "andre-bonfire": {"map": MAP, "stand": [88.46, 14.97, 106.96], "heading": 2.34, "bonfire_id": 1012964,
                           "sitting_verified": True, "note": "y"},
         "other": {"anything": "goes — not a spot this route uses"}}
    S.update(over)
    return S


def parse(R=None, S=None, rt=None, st=None):
    return F.parse(rt if rt is not None else json.dumps(route() if R is None else R),
                   st if st is not None else json.dumps(spots() if S is None else S), "parish-bonfire", "andre-bonfire")


def refused(*a, has: str = "", **k) -> list[str]:
    try:
        parse(*a, **k)
    except F.RouteError as e:
        assert has in "; ".join(e.problems), (has, e.problems)
        return e.problems
    raise AssertionError("accepted")


def test_parses_into_frozen_route():
    r = parse()
    assert r.schema == F.SCHEMA and r.map == MAP and len(r.legs) == 2
    assert r.legs[0].points[1] == (30.0, 10.0, 0.0) and all(type(c) is float for p in r.legs[0].points for c in p)
    assert r.legs[0].ignore_npcs == (3, 7) and r.legs[1].mode == "walk" and r.legs[1].ignore_npcs == ()
    assert r.requires[0] == F.Require("bell", 11010700, True) and type(r.requires[0].flag) is int
    assert r.start.bonfire_id == 1012961 and r.end.heading == 2.34 and r.end.object is None
    assert r.fingerprint == hashlib.sha256(F.canonical(r.payload()).encode()).hexdigest()


def test_immutable():
    r = parse()
    for obj, field in ((r, "map"), (r.legs[0], "tag"), (r.start, "stand"), (r.requires[0], "want")):
        try:
            setattr(obj, field, None)
        except dataclasses.FrozenInstanceError:
            continue
        raise AssertionError(f"{type(obj).__name__}.{field} writable")
    assert isinstance(r.legs, tuple) and isinstance(r.legs[0].points, tuple) and isinstance(r.legs[0].points[0], tuple)


def test_real_spots_file_entries_parse():
    st = (ROOT / "data" / "spots.json").read_text(encoding="utf-8")   # read-only; heading present, object absent
    r = parse(st=st)
    assert r.start.stand == (24.77, 9.5, -22.87) and r.end.bonfire_id == 1012964 and r.end.object is None


def test_bad_text_refused():
    refused(rt="", has="JSON 아님")
    refused(rt="﻿" + json.dumps(route()), has="BOM")
    refused(rt="[]", has="객체 아님")
    refused(rt='{"schema": "a", "schema": "b"}', has="키 중복")
    refused(st='{"x": 1, "x": 2}', has="키 중복")


def test_non_finite_and_bool_numbers_refused():
    base = json.dumps(route())
    for lit in ("NaN", "Infinity", "-Infinity"):
        refused(rt=base.replace("[30, 10, 0]", f"[30, {lit}, 0]", 1), has="숫자 아님")
    refused(rt=base.replace("[30, 10, 0]", "[30, 1e999, 0]", 1), has="유한하지 않음")
    R = route()
    R["legs"][0]["points"][0] = [True, 9.5, -22.87]
    refused(R, has="숫자 아님")
    R = route()
    R["requires"][0]["flag"] = True
    refused(R, has="정수 아님")
    R = route()
    R["requires"][0]["want"] = 1
    refused(R, has="bool 아님")
    S = spots()
    S["andre-bonfire"]["bonfire_id"] = 1012964.0
    refused(S=S, has="정수 아님")


def test_schema_fields_and_shapes_refused():
    refused(route(schema="altar-andre-route/2"), has="route.schema")
    R = route()
    del R["schema"]
    refused(R, has="필드 없음 'schema'")
    refused(route(extra=1), has="모르는 필드 'extra'")
    R = route()
    R["legs"][0]["speed"] = 2
    refused(R, has="모르는 필드 'speed'")
    R = route()
    R["requires"][0]["note"] = "x"
    refused(R, has="모르는 필드 'note'")
    refused(route(legs=[]), has="route.legs")
    R = route()
    R["legs"][0]["points"] = [[1, 2, 3]]
    refused(R, has="점 두 개 이상")
    R = route()
    R["legs"][0]["points"][1] = [1, 2]
    refused(R, has="[x, y, z]")
    refused(route(legs=[{"tag": "a", "mode": "run", "points": [[0, 0, 0], [1, 1, 1]]}]), has="mode")
    refused(route(legs=[{"tag": "", "points": [[0, 0, 0], [1, 1, 1]]}]), has="tag")


def test_spot_problems_refused():
    S = spots()
    del S["andre-bonfire"]
    refused(S=S, has="'andre-bonfire': 없음")
    S = spots()
    S["andre-bonfire"]["verified_by"] = "x"
    refused(S=S, has="모르는 필드 'verified_by'")
    S = spots()
    del S["parish-bonfire"]["stand"]
    refused(S=S, has="필드 없음 'stand'")
    S = spots()
    S["andre-bonfire"]["map"] = "m12_00_00_00"
    refused(S=S, has="≠ route.map")


def test_optional_spot_values_missing_is_none():
    S = spots()
    del S["andre-bonfire"]["heading"]
    a = parse(S=S)
    S["andre-bonfire"]["heading"] = None
    b = parse(S=S)
    assert a.end.heading is None and a.end.object is None and a.fingerprint == b.fingerprint
    assert a.fingerprint != parse().fingerprint            # heading given vs absent differ
    S["andre-bonfire"]["object"] = [89, 15, 108]
    c = parse(S=S)
    assert c.end.object == (89.0, 15.0, 108.0) and c.fingerprint != a.fingerprint


def test_canonical_equivalences():
    base = parse().fingerprint
    R = route()
    R["legs"][0]["points"][1] = [30.0, 10.0, 0.0]          # 1 ≡ 1.0
    assert parse(R).fingerprint == base
    R["legs"][0]["points"][1] = [30.0, 10.0, -0.0]         # −0.0 ≡ 0.0
    assert parse(R).fingerprint == base
    R = route()
    R["legs"][0]["ignore_npcs"] = [3, 7, 7]                # a set: order and repeats don't matter
    assert parse(R).fingerprint == base
    R = route()
    R["legs"][1]["mode"] = "walk"                          # absent mode = walk
    R["legs"][1]["ignore_npcs"] = []                       # absent ignore_npcs = []
    assert parse(R).fingerprint == base
    R = route()
    rt = json.dumps(dict(reversed(list(R.items()))), indent=2)   # key order, whitespace
    assert parse(rt=rt).fingerprint == base
    R = route()
    del R["requires"]
    assert parse(route(requires=[])).fingerprint == parse(R).fingerprint


def test_metadata_excluded():
    base = parse().fingerprint
    for k, v in (("_source", "other.jsonl"), ("validation", {"traversal": {"status": "validated", "by": "MoKa"}}),
                 ("review", {"by": "MoKa"}), ("note", "changed"), ("fingerprint", "0" * 64)):
        assert parse(route(**{k: v})).fingerprint == base, k
    R = route()
    for k in ("_source", "validation", "review", "note"):
        del R[k]
    assert parse(R).fingerprint == base
    R = route()
    R["legs"][0]["note"] = "leg note"
    assert parse(R).fingerprint == base
    S = spots()
    S["andre-bonfire"]["note"], S["andre-bonfire"]["sitting_verified"] = "other", False
    S["other"] = {"changed": True}                         # spots this route doesn't use
    assert parse(S=S).fingerprint == base


def test_execution_changes_change_fingerprint():
    base = parse().fingerprint
    changes = []
    R = route()
    R["legs"][0]["points"][1][0] = 30.001
    changes.append(parse(R))
    R = route()
    R["legs"][0]["points"].reverse()
    changes.append(parse(R))
    R = route()
    R["legs"].reverse()
    changes.append(parse(R))
    R = route()
    R["legs"][0]["mode"] = "sprint"
    changes.append(parse(R))
    R = route()
    R["legs"][0]["tag"] = "a2"
    changes.append(parse(R))
    R = route()
    R["legs"][0]["ignore_npcs"] = [3]
    changes.append(parse(R))
    R = route()
    R["requires"][0]["want"] = False
    changes.append(parse(R))
    R = route()
    R["requires"][0]["flag"] = 11010701
    changes.append(parse(R))
    for spot, key, val in (("andre-bonfire", "stand", [88.46, 14.97, 106.97]), ("andre-bonfire", "heading", 2.35),
                           ("andre-bonfire", "bonfire_id", 1012965), ("parish-bonfire", "stand", [24.78, 9.5, -22.87])):
        S = copy.deepcopy(spots())
        S[spot][key] = val
        changes.append(parse(S=S))
    R, S = route(map="m10_01_00_01"), spots()
    for name in ("parish-bonfire", "andre-bonfire"):
        S[name]["map"] = "m10_01_00_01"
    changes.append(parse(R, S))
    fps = [c.fingerprint for c in changes]
    assert base not in fps and len(set(fps)) == len(fps)


def test_route_does_not_follow_later_edits_of_the_input():
    R, S = route(), spots()
    rt, st = json.dumps(R), json.dumps(S)
    r = F.parse(rt, st, "parish-bonfire", "andre-bonfire")
    R["legs"][0]["points"][0][0] = 999.0                   # the parsed Route keeps what was read
    S["andre-bonfire"]["stand"][0] = 999.0
    assert r.legs[0].points[0][0] == 24.77 and r.end.stand[0] == 88.46
    assert r.fingerprint == hashlib.sha256(F.canonical(r.payload()).encode()).hexdigest()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
