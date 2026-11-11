"""P-53: sprinting back to the burg-upper zone 1 safe spot, the bot ran 3 m past the 55° corner at (−5.4, −9.9, −69.6) and fell
4 m (10-09 234512, 115.1–116.6 s, quit-out). nav.follow now approaches a corner with a drop past it jogging, not sprinting
(nav.brake_points / nav.braked). Past that corner the NavMesh's only floor is a roof 19 m up, which ground_ahead takes as floor —
brake_points reads floor at our level only (nav._level_floor)."""
from __future__ import annotations

import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(1, str(_pl.Path(__file__).resolve().parent))

from types import SimpleNamespace as NS

import motion
import nav

NM = motion.load_navmeshes()["m10_01_00_00"]
SAFE1 = (-0.8, -10.0, -62.5)                                # burg-upper zone 1 safe spot
CORNER = (-5.38, -9.95, -69.63)


def check(what: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + what)
    if not ok:
        raise SystemExit(1)


class Flat:
    """Endless floor at y 0, or (drop_x) floor 5 m lower east of x = drop_x."""
    def __init__(self, drop_x=None):
        self.drop_x = drop_x

    def floor_at(self, x, z, near_y):
        return (-5.0 if self.drop_x is not None and x > self.drop_x else 0.0, 0)

    def drop_dist(self, x, y, z, dy=2.0):
        return float("inf") if self.drop_x is None else abs(self.drop_x - x)


def main() -> None:
    start = (-16.51, -13.37, -69.28)                        # track 112.06 s: where the run back began
    path = nav.trim_path(NM.find_path(start, SAFE1)[1:], SAFE1)
    br = nav.brake_points(path, NM)
    corner = [q for q, b in zip(path, br) if b and abs(q[0] - CORNER[0]) < 0.2 and abs(q[2] - CORNER[2]) < 0.4]
    check(f"P-53 run back: the 55° corner (−5.4, −69.6) brakes ({sum(br)} of {len(path)} points)", bool(corner))
    p = NS(gx=CORNER[0], gy=CORNER[1], gz=CORNER[2])
    check("… past it ground_ahead sees the roof 19 m up as floor; the level check doesn't",
          nav.ground_ahead(NM, p, 1.0, 0.0, reach=3.0) and not nav._level_floor(NM, CORNER, 1.0, 0.0, 3.0))

    turn = [(0.0, 0.0, 0.0), (5.0, 0.0, 0.0), (5.0, 0.0, 5.0)]        # 90° left at (5, 0, 0)
    check("a corner on open floor doesn't brake", nav.brake_points(turn, Flat()) == [False, False, False])
    check("… a drop 1 m past it does", nav.brake_points(turn, Flat(drop_x=6.0)) == [False, True, False])
    straight = [(0.0, 0.0, 0.0), (5.0, 0.0, 0.0), (10.0, 0.0, 0.0)]
    check("no turn, no brake (even toward a drop)", nav.brake_points(straight, Flat(drop_x=6.0)) == [False, False, False])
    check("no terrain → never brakes", nav.brake_points(turn, None) == [False, False, False])

    at = lambda x: NS(player=NS(gx=x, gz=0.0))
    fn = nav.braked(lambda s: "sprint", (5.0, 0.0, 0.0))
    check("braked: sprint far from the corner, walk (no B) within BRAKE_R",
          fn(at(0.0)) == "sprint" and fn(at(5.0 - nav.BRAKE_R + 0.1)) == "walk")
    check("braked: other modes pass through", nav.braked(lambda s: "retreat", (5.0, 0.0, 0.0))(at(4.0)) == "retreat"
          and nav.braked(lambda s: "guard", (5.0, 0.0, 0.0))(at(4.0)) == "guard")
    fn = nav.braked(None, (20.0, 0.0, 0.0))
    check("braked with goto's default modes: sprint beyond SPRINT_BEYOND, walk inside",
          fn(at(0.0)) == "sprint" and fn(at(19.0)) == "walk")

    seen = []
    goto0 = nav.goto
    nav.goto = lambda tm, pad, q, mode_fn=None, **k: (seen.append((q, mode_fn)), "arrived")[1]
    try:
        base = lambda s: "sprint"
        r = nav.follow(None, NS(neutral=lambda: None, sprint=lambda on: None, guard=lambda on: None, move=lambda x, y: None),
                       turn, terrain=Flat(drop_x=6.0), mode_fn=base)
    finally:
        nav.goto = goto0
    check("follow: only the brake corner gets the braked mode_fn",
          r == "arrived" and seen[0][1] is base and seen[1][1] is not base and seen[1][1](at(3.0)) == "walk" and seen[2][1] is base)
    print("brake_test: 전부 통과")


if __name__ == "__main__":
    main()
