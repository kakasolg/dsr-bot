"""walkgeom offline test — progress / lateral error / switching gate / look-ahead / corner cuts on a fake L. No game.

  python tests/walkgeom_test.py
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import walkgeom as G

fails = 0


def check(name, cond):
    global fails
    print(("  ok   " if cond else "  FAIL ") + name)
    fails += 0 if cond else 1


L = [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (10.0, 0.0, 10.0)]     # 10 m +x, then 10 m +z (a left turn on a x-right/z-up map)
UP = [(0.0, 0.0, 0.0), (0.0, 0.0, 10.0)]

print("project")
pr = G.project(UP, (-1.0, 0.0, 4.0), 0)
check("s = 0.4 at 4 m of 10", abs(pr.s - 0.4) < 1e-9)
check("heading +z, point at -x → lat +1 (left)", abs(pr.lat - 1.0) < 1e-9)
check("right side → lat −", G.project(UP, (2.0, 0.0, 4.0), 0).lat < 0)
check("behind the start → s < 0, along clamped 0", G.project(UP, (0.0, 0.0, -2.0), 0).s < 0 and G.project(UP, (0.0, 0.0, -2.0), 0).along == 0)
pr = G.project(L, (10.0, 0.0, 5.0), 1)
check("second leg: along 15 of 20, frac 0.75", abs(pr.along - 15.0) < 1e-9 and abs(pr.frac - 0.75) < 1e-9)
check("2-tuple points (x, z) work too", abs(G.project([(0, 0), (0, 10)], (0.0, 0.0, 5.0), 0).s - 0.5) < 1e-9)

print("locate (measurement)")
check("cut inside the corner at (9, 1) → already on leg 2", G.locate(L, (9.0, 0.0, 1.5), 0).seg == 1)
check("mid first leg → leg 1", G.locate(L, (4.0, 0.0, 0.5), 0).seg == 0)
S = [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (10.0, 0.0, 1.0), (0.0, 0.0, 1.0)]   # switchback: leg 3 runs back 1 m beside leg 1
check("switchback: point nearer leg 3 (z 0.6) but walking leg 1 → leg 1", G.locate(S, (3.0, 0.0, 0.6), 0, along_hint=2.5).seg == 0)
check("… unbounded it would be leg 3 (why the window exists)",
      G.locate(S, (3.0, 0.0, 0.6), 0, back_m=99, ahead_m=99).seg == 2)
check("… and coming back along leg 3 it is leg 3", G.locate(S, (3.0, 0.0, 0.6), 2, along_hint=18.0).seg == 2)

print("locate window in metres")
dense = [(0.3 * i, 0.0, 0.0) for i in range(101)]            # recorded route: a point every 0.3 m (30 m)
k, a, lag = 0, None, 0
for step in range(1, 17):                                    # a run at 2 Hz: 1.85 m per frame (> 6 segments)
    x = 1.85 * step
    pr = G.locate(dense, (x, 0.0, 0.1), k, along_hint=a)
    lag += abs(pr.along - x) > 0.05
    k, a = pr.seg, pr.along
check("dense route, 1.85 m per frame → never falls behind (old 3-segment window did)", lag == 0)
k, a = 0, None
for x in (3.7, 7.4, 11.1):                                   # a dropped frame: 3.7 m per frame
    pr = G.locate(dense, (x, 0.0, 0.1), k, along_hint=a)
    k, a = pr.seg, pr.along
check("one dropped frame (3.7 m) still followed", abs(a - 11.1) < 0.05)
sparse = [(0.0, 0.0, 0.0), (6.0, 0.0, 0.0), (6.0, 0.0, 6.0)]  # NavMesh path: long segments
check("long segment: next segment reachable from mid-segment", G.locate(sparse, (6.3, 0.0, 1.0), 0, along_hint=4.5).seg == 1)
check("knocked back 1 m onto the previous segment → found",
      G.locate(dense, (5.0, 0.0, 0.0), 20, along_hint=6.0).seg in (16, 17))
far = G.locate(dense, (20.0, 0.0, 0.0), 0, along_hint=0.0, relocate_m=99)
check("10+ m ahead, relocation off → held at the window front (≤ 4 m + one segment)", far.along <= G.LOCATE_AHEAD_M + 0.3 + 1e-9)
check("walk starting 6 m into the path → relocated on the first frame",
      abs(G.locate(dense, (6.0, 0.0, 0.2), 0).along - 6.0) < 0.05)
check("pushed 8 m ahead by a fight → relocated", abs(G.locate(dense, (14.0, 0.0, 0.5), 20, along_hint=6.0).along - 14.0) < 0.05)
check("switchback legs 1 m apart never relocate (walking leg 1, beside leg 3)",
      G.locate(S, (5.0, 0.0, 0.9), 0, along_hint=4.5).seg == 0)
check("k_hint is always a candidate (even far outside the metre window)",
      G.locate(dense, (29.0, 0.0, 0.0), 95, along_hint=0.0, relocate_m=99).seg >= 95)

print("Gate (switch only at s ≥ 0.95)")
g = G.Gate(L)
check("s 0.90 → stays on A→B", g.update((9.0, 0.0, 0.3)).seg == 0 and g.k == 0)
check("cut inside the corner (on leg 2's line) still A→B", g.update((9.2, 0.0, 1.0)).seg == 0)
check("s 0.96 → B→C", g.update((9.6, 0.0, 0.0)).seg == 1)
check("never goes back", g.update((2.0, 0.0, 0.0)).seg == 1)
g2 = G.Gate(L, switch_s=0.5)
check("switch_s is a parameter", g2.update((6.0, 0.0, 0.0)).seg == 1)

print("look-ahead")
lens = G.seg_lengths(L)
check("far from the corner → full 1.5 m", G.lookahead_dist(L, G.project(L, (3.0, 0.0, 0.0), 0)) == G.LOOKAHEAD_M)
check("1.0 m before a 90° corner → 1.0 m", abs(G.lookahead_dist(L, G.project(L, (9.0, 0.0, 0.0), 0)) - 1.0) < 1e-9)
check("right at the corner → floor 0.5 m", G.lookahead_dist(L, G.project(L, (9.9, 0.0, 0.0), 0)) == G.LOOKAHEAD_MIN_M)
gentle = [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (20.0, 0.0, 3.0)]      # 17° bend
check("gentle bend doesn't shrink", G.lookahead_dist(gentle, G.project(gentle, (9.5, 0.0, 0.0), 0)) == G.LOOKAHEAD_M)
check("point_at 15 m = (10, 0, 5)", G.point_at(L, 15.0, lens) == (10.0, 0.0, 5.0))
check("point_at past the end = last point", G.point_at(L, 99.0, lens) == L[-1])

print("corner cuts")
c = G.corner_cuts(L, [(8.0, 0.0, 0.0), (9.0, 0.0, 1.0), (10.0, 0.0, 3.0)])
check("one sharp corner found (90°)", len(c) == 1 and c[0]["i"] == 1 and abs(c[0]["deg"] - 90.0) < 1.0)
check("passing at (9, 1) = inside, 1.41 m", c[0]["inside"] and abs(c[0]["dist"] - 1.41) < 0.01)
c = G.corner_cuts(L, [(10.8, 0.0, -0.8)])
check("swinging wide at (10.8, −0.8) = outside", len(c) == 1 and not c[0]["inside"])
check("corner never approached → not listed", G.corner_cuts(L, [(0.0, 0.0, 0.0)]) == [])
check("turn_deg matches nav.turn_deg definition (90° at L)", abs(G.turn_deg(L, 1) - 90.0) < 1e-6)

print(f"\n{'all ok' if not fails else f'{fails} FAILED'}")
sys.exit(1 if fails else 0)
