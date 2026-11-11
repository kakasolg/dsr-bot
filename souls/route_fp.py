"""Route data for a fixed-route mission (Altar → Andre first): parse + validate once into an immutable Route, and fingerprint
only what the run executes. Pure — no file reads, no game, no imports of the bot. Not wired into any mission yet.

  parse(route_text, spots_text, start, end) -> Route        raises RouteError(problems)

Accepted route (schema "altar-andre-route/1"):
  {"schema": "altar-andre-route/1", "map": str,
   "requires": [{"what": str, "flag": int, "want": bool}],                       (optional, default [])
   "legs": [{"tag": str, "mode": "walk" | "sprint",                               (mode optional, default "walk")
             "points": [[x, y, z], …≥2], "ignore_npcs": [int, …]}],               (ignore_npcs optional, default [])
   "_source" / "validation" / "review" / "note" / "fingerprint": metadata — accepted, never fingerprinted}
Spot entries (start / end in spots.json): map (== route map), stand [x, y, z], bonfire_id int required; heading float and
object [x, y, z] optional (None when absent — arrival-only traversal needs neither); note / sitting_verified are metadata.
Anything else is refused, at every level.

Fingerprint = sha256 of the canonical JSON of Route.payload(): schema, map, requires (in order), legs (tag, mode, points,
ignore_npcs sorted and deduplicated), start / end spot (name, map, stand, bonfire_id, heading, object).
Numbers: finite only, no bools; coordinates and heading as float (1 ≡ 1.0, −0.0 ≡ 0.0); ids / flags stay int, want stays bool.
Canonical JSON: sort_keys, separators (",", ":"), ensure_ascii False, floats by Python repr.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass

SCHEMA = "altar-andre-route/1"
MODES = ("walk", "sprint")
META = frozenset({"_source", "validation", "review", "note", "fingerprint"})
SPOT_META = frozenset({"note", "sitting_verified"})


class RouteError(ValueError):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = list(problems)


@dataclass(frozen=True)
class Leg:
    tag: str
    mode: str
    points: tuple[tuple[float, float, float], ...]
    ignore_npcs: tuple[int, ...]


@dataclass(frozen=True)
class Require:
    what: str
    flag: int
    want: bool


@dataclass(frozen=True)
class Spot:
    name: str
    map: str
    stand: tuple[float, float, float]
    bonfire_id: int
    heading: float | None
    object: tuple[float, float, float] | None


@dataclass(frozen=True)
class Route:
    schema: str
    map: str
    requires: tuple[Require, ...]
    legs: tuple[Leg, ...]
    start: Spot
    end: Spot
    fingerprint: str

    def payload(self) -> dict:
        return _payload(self.schema, self.map, self.requires, self.legs, self.start, self.end)


def _payload(schema, map_, requires, legs, start, end) -> dict:
    spot = lambda s: {"name": s.name, "map": s.map, "stand": list(s.stand), "bonfire_id": s.bonfire_id,   # noqa: E731
                      "heading": s.heading, "object": None if s.object is None else list(s.object)}
    return {"schema": schema, "map": map_,
            "requires": [{"what": q.what, "flag": q.flag, "want": q.want} for q in requires],
            "legs": [{"tag": g.tag, "mode": g.mode, "points": [list(p) for p in g.points], "ignore_npcs": list(g.ignore_npcs)}
                     for g in legs],
            "start": spot(start), "end": spot(end)}


def canonical(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _no_dupes(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise RouteError([f"키 중복 {k!r}"])
        out[k] = v
    return out


def _no_constant(name):
    raise RouteError([f"숫자 아님 {name}"])          # NaN / Infinity / -Infinity literals


def _load(text, what: str):
    if not isinstance(text, str):
        raise RouteError([f"{what}: 텍스트 아님"])
    if text.startswith("﻿"):
        raise RouteError([f"{what}: BOM"])
    try:
        return json.loads(text, object_pairs_hook=_no_dupes, parse_constant=_no_constant)
    except RouteError as e:
        raise RouteError([f"{what}: {p}" for p in e.problems]) from None
    except ValueError as e:
        raise RouteError([f"{what}: JSON 아님 ({e})"]) from None


def _num(v, where: str, bad: list) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        bad.append(f"{where}: 숫자 아님 ({v!r})")
        return None
    f = float(v)                                     # 1e999 parses as inf; huge ints overflow here
    if not math.isfinite(f):
        bad.append(f"{where}: 유한하지 않음")
        return None
    return 0.0 if f == 0.0 else f                    # −0.0 ≡ 0.0


def _int(v, where: str, bad: list) -> int | None:
    if isinstance(v, bool) or not isinstance(v, int):
        bad.append(f"{where}: 정수 아님 ({v!r})")
        return None
    return v


def _str(v, where: str, bad: list) -> str | None:
    if not isinstance(v, str) or not v:
        bad.append(f"{where}: 빈 문자열이거나 문자열 아님 ({v!r})")
        return None
    return v


def _xyz(v, where: str, bad: list):
    if not isinstance(v, list) or len(v) != 3:
        bad.append(f"{where}: [x, y, z] 아님")
        return None
    n = len(bad)
    p = tuple(_num(c, f"{where}[{i}]", bad) for i, c in enumerate(v))
    return p if len(bad) == n else None


def _fields(d, where: str, required: set, optional: set, meta: frozenset, bad: list) -> bool:
    if not isinstance(d, dict):
        bad.append(f"{where}: 객체 아님")
        return False
    for k in sorted(set(d) - required - optional - meta):
        bad.append(f"{where}: 모르는 필드 {k!r}")
    for k in sorted(required - set(d)):
        bad.append(f"{where}: 필드 없음 {k!r}")
    return True


def _spot(spots, name: str, bad: list) -> Spot | None:
    where = f"spot {name!r}"
    if not isinstance(spots, dict) or name not in spots:
        bad.append(f"{where}: 없음")
        return None
    e = spots[name]
    n = len(bad)
    if not _fields(e, where, {"map", "stand", "bonfire_id"}, {"heading", "object"}, SPOT_META, bad):
        return None
    m = _str(e.get("map"), f"{where}.map", bad)
    stand = _xyz(e.get("stand"), f"{where}.stand", bad)
    bid = _int(e.get("bonfire_id"), f"{where}.bonfire_id", bad)
    heading = None if e.get("heading") is None else _num(e["heading"], f"{where}.heading", bad)
    obj = None if e.get("object") is None else _xyz(e["object"], f"{where}.object", bad)
    if len(bad) != n:
        return None
    return Spot(name, m, stand, bid, heading, obj)


def parse(route_text: str, spots_text: str, start: str, end: str) -> Route:
    """Both texts parsed once here; the Route is what a run executes and what the fingerprint covers."""
    R = _load(route_text, "route")
    S = _load(spots_text, "spots")
    bad: list[str] = []
    if not _fields(R, "route", {"schema", "map", "legs"}, {"requires"}, META, bad):
        raise RouteError(bad)
    if R.get("schema") != SCHEMA:
        bad.append(f"route.schema {R.get('schema')!r} ≠ {SCHEMA!r}")
    map_ = _str(R.get("map"), "route.map", bad)
    reqs = []
    rq = R.get("requires", [])
    if not isinstance(rq, list):
        bad.append("route.requires: 목록 아님")
        rq = []
    for i, q in enumerate(rq):
        w = f"requires[{i}]"
        if _fields(q, w, {"what", "flag", "want"}, set(), frozenset(), bad):
            what, flag = _str(q.get("what"), f"{w}.what", bad), _int(q.get("flag"), f"{w}.flag", bad)
            want = q.get("want")
            if not isinstance(want, bool):
                bad.append(f"{w}.want: bool 아님 ({want!r})")
            reqs.append(Require(what, flag, want))
    legs = []
    lg = R.get("legs")
    if not isinstance(lg, list) or not lg:
        bad.append("route.legs: 비었거나 목록 아님")
        lg = []
    for i, g in enumerate(lg):
        w = f"legs[{i}]"
        if not _fields(g, w, {"tag", "points"}, {"mode", "ignore_npcs"}, frozenset({"note"}), bad):
            continue
        tag = _str(g.get("tag"), f"{w}.tag", bad)
        mode = g.get("mode", "walk")
        if mode not in MODES:
            bad.append(f"{w}.mode {mode!r}")
        pts = g.get("points")
        if not isinstance(pts, list) or len(pts) < 2:
            bad.append(f"{w}.points: 점 두 개 이상 아님")
            pts = []
        points = tuple(_xyz(p, f"{w}.points[{j}]", bad) for j, p in enumerate(pts))
        ign = g.get("ignore_npcs", [])
        if not isinstance(ign, list):
            bad.append(f"{w}.ignore_npcs: 목록 아님")
            ign = []
        ids = [_int(x, f"{w}.ignore_npcs[{j}]", bad) for j, x in enumerate(ign)]
        legs.append(Leg(tag, mode, points, tuple(sorted({x for x in ids if x is not None}))))
    sp_start, sp_end = _spot(S, start, bad), _spot(S, end, bad)
    for sp in (sp_start, sp_end):
        if sp is not None and map_ is not None and sp.map != map_:
            bad.append(f"spot {sp.name!r}.map {sp.map!r} ≠ route.map {map_!r}")
    if bad:
        raise RouteError(bad)
    reqs, legs = tuple(reqs), tuple(legs)
    fp = hashlib.sha256(canonical(_payload(SCHEMA, map_, reqs, legs, sp_start, sp_end)).encode("utf-8")).hexdigest()
    return Route(SCHEMA, map_, reqs, legs, sp_start, sp_end, fp)
