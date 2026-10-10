"""Which way to back off / roll out (souls/escape.py, [MoKa] 2026-10-10). No game.

  python tests/escape_test.py

  "20m 이내에 적이 어디 있는지 파악 하고, 없는 쪽으로 가야 하는게 기본이지. 보통 진입했던 반대 방향인데, 그것도 체크는 해야지."
  "주변에 적이 애워싸면, 빈틈이 있다면 그 방향으로 구르고, 없으면 한 두대 약공 때리고 상대가 틈을 만들어 주면 그 방향으로
   비벼 들어가서 빠져 나가야지."

Checks on the real Firelink NavMesh (data/samples/navmesh_m10_02_00_00.npz) and on the recorded deaths:
  · the way we came is the usual answer, but not when an awake foe stands on it — then another way
  · the P-56 ramp-ledge death (low_hp 90.4 s): the old "roll straight away" had no floor; now there is a gap toward the way we came
  · gap_dir: three around → the open side; four around (1 m) → none; a staggered one opens its side; no floor → none
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import json
import math
import sys
import types
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import motion
import nav
from souls import escape as E
from souls import moves as M

ROOT = Path(__file__).resolve().parent.parent
HOSTILE = (6, 7, 24, 25, 27, 33)


def check(name: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        raise SystemExit(1)


def scene(name: str, t_at: float):
    trail, snap = [], None
    for line in open(ROOT / "data" / "samples" / f"{name}.track.jsonl", encoding="utf-8"):
        d = json.loads(line)
        if d.get("type") != "snap":
            continue
        if d["rt"] > t_at:
            break
        p = d["player"]
        q = (p["x"], p["y"], p["z"])
        if not trail or math.dist(q, trail[-1]) >= 1.0:
            trail.append(q)
        snap = d
    p = snap["player"]
    me = (p["x"], p["y"], p["z"])
    hostile = [c for c in snap["chars"] if c["hp"] > 0 and c["team"] in HOSTILE]
    foes = [(c["x"], c["y"], c["z"], c["anim"] not in (-1, None) or math.hypot(c["x"] - me[0], c["z"] - me[2]) < 2) for c in hostile]
    close = [(c["x"], c["z"], (c["anim"] or -1) not in M.STAGGER and (c["anim"] or -1) not in M.DOWNED)
             for c in hostile if math.hypot(c["x"] - me[0], c["z"] - me[2]) < E.GAP_R]
    return me, foes, close, trail


def main() -> None:
    nm = motion.load_navmeshes()["m10_02_00_00"]

    me, foes, close, trail = scene("20261010_064342_burg-bonfire_ab-on2-died", 90.4)
    ch = E.pick(nm, me, foes, trail)
    check(f"P-56 ledge: back off the way we came ({ch.line()})", ch.src == "T" and ch.point is not None)
    P = types.SimpleNamespace(gx=me[0], gy=me[1], gz=me[2])
    ok = lambda dx, dz: nav.ground_ahead(nm, P, dx, dz, reach=2.5)
    c = min(close, key=lambda f: math.hypot(f[0] - me[0], f[1] - me[2]))
    d = math.hypot(c[0] - me[0], c[1] - me[2])
    g = E.gap_dir(me, close, ok, ch.point)
    check("P-56 ledge: 'roll straight away' had no floor (it fought on and died); now a gap with floor exists",
          not ok((me[0] - c[0]) / d, (me[2] - c[1]) / d) and g is not None)

    # the way we came, taken: put an awake foe on our own trail 8 m back → another way (or none), never through it
    blocker = E._trail_points(trail, me)[1] if len(E._trail_points(trail, me)) > 1 else trail[-8]
    ch2 = E.pick(nm, me, foes + [(blocker[0], blocker[1], blocker[2], True)], trail)
    check(f"trail taken by an awake foe: not through it ({ch2.line()})",
          ch2.point is None or all(math.hypot(q[0] - blocker[0], q[2] - blocker[2]) >= E.PASS_R for q in ch2.path + [ch2.point]))

    # gap_dir on flat ground
    flat = lambda dx, dz: True
    o = (0.0, 0.0, 0.0)
    g3 = E.gap_dir(o, [(0.0, 1.0, True), (1.0, 0.0, True), (-1.0, 0.0, True)], flat)
    check("three around (front, left, right) → the open side behind", g3 is not None and g3[1] < -0.9)
    ring = [(0.0, 1.0, True), (1.0, 0.0, True), (-1.0, 0.0, True), (0.0, -1.0, True)]
    check("four around at 1 m → no gap", E.gap_dir(o, ring, flat) is None)
    opened = [(0.0, 1.0, True), (1.0, 0.0, True), (-1.0, 0.0, True), (0.0, -1.0, False)]
    g4 = E.gap_dir(o, opened, flat)
    check("the one behind staggers → its side opens", g4 is not None and g4[1] < -0.7)
    check("no floor anywhere → no gap", E.gap_dir(o, [(0.0, 1.0, True)], lambda dx, dz: False) is None)
    gp = E.gap_dir(o, [(0.0, 1.0, True)], flat, prefer=(5.0, 0.0, 0.0))
    check("one in front, prefer to the right → roll right-ish (open and toward where we back off to)", gp is not None and gp[0] > 0.7)
    print("escape_test: 전부 통과")


if __name__ == "__main__":
    main()
