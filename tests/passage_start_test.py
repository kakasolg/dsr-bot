"""P-57: the passage walk stalled 1.5–2.6 s at its start (−20,−39.3,14.4) and turned around in 3 of the 3 seg 1-2 runs whose ramp
fight ended on the top platform, 4.0–4.3 m from A0 (the stair top, 3.3 m higher, reached around the east side) — _to_merchant only
path-found when the nearest route point was over 6 m away, so it walked straight at A0 into the ledge (the P-49 / P-58 fall spot).
Runs starting 20+ m off path-found first and never stalled there."""
from __future__ import annotations

import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(1, str(_pl.Path(__file__).resolve().parent))

import math
from types import SimpleNamespace

import motion
from souls import missions as MS

NM = motion.load_navmeshes()[MS.MAP_A]
MS._VOID_NM = NM                                           # _route's void check reads the offline NavMesh, not the game folder
TOP, ROUTE, _R = MS._route()

# where the passage walk started in the stalled runs (log "통로: 0/N번 점 … 못 감 — 나 (…)", or the track at "상인 길")
STALLED = {"20261010_064154 ab-off2": (-20.0, -39.3, 14.3), "20261010_072349 r2-off2": (-20.1, -39.3, 14.5),
           "20261011_061145 pull-off2": (-21.81, -40.44, 14.15)}   # track at 135.1 s, the first 통로 snap


def check(what: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + what)
    if not ok:
        raise SystemExit(1)


def fake(here):
    m = object.__new__(MS.Missions)
    m.lines, m.calls = [], []
    m.log = m.lines.append
    m.nms = {MS.MAP_A: NM, MS.MAP_B: None}
    s = SimpleNamespace(player=SimpleNamespace(x=here[0], y=here[1], z=here[2]))

    def walk_to(goal, nm, tag, **kw):
        m.calls.append(("walk_to", tuple(goal), tag))
        return "arrived"

    def walk(path, nm, tag, **kw):
        m.calls.append(("walk", tuple(path[0]), tag))
        return "arrived"
    m.f = SimpleNamespace(snap_settled=lambda t=5.0: s, walk_to=walk_to, walk=walk, home=None)
    return m


def main() -> None:
    for run, here in STALLED.items():
        d = math.dist(here, TOP)
        check(f"{run}: A0 {d:.1f} m away but {TOP[1] - here[1]:+.1f} m up → off_route", d <= MS.ROUTE_NEAR_M and MS.off_route(here, TOP))
        path = NM.find_path(here, TOP)
        check(f"… the NavMesh has a way up from there ({len(path or [])} points, via the east side x > −17)",
              bool(path) and max(q[0] for q in path) > -17.0)
        m = fake(here)
        r = m._to_merchant("passage", None)
        check(f"… _to_merchant path-finds to A0 first ('꼭대기로'), then walks the passage from A0 → {r}, {[c[0] for c in m.calls]}",
              r == "통로 끝" and m.calls[0] == ("walk_to", TOP, "꼭대기로") and m.calls[1][0] == "walk" and m.calls[1][1] == TOP)

    a1 = ROUTE[1]
    m = fake((a1[0], a1[1], a1[2] + 0.1))
    m._to_merchant("passage", None)
    check(f"on the route (A1, 0.1 m — 072034) → straight into the passage walk, no path-find ({[c[0] for c in m.calls]})",
          [c[0] for c in m.calls] == ["walk"] and m.calls[0][1] == a1)

    far = (-26.5, -48.3, 28.6)                             # ramp flat, 20+ m off (the runs that never stalled)
    m = fake(far)
    m._to_merchant("passage", None)
    check("20+ m off → walk_to the top first, as before", m.calls[0] == ("walk_to", TOP, "꼭대기로") and m.calls[1][1] == TOP)
    print("passage_start_test: 전부 통과")


if __name__ == "__main__":
    main()
