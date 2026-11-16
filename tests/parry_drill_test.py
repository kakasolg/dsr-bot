"""parry_drill.parry_due — when L2 goes out, against MoKa's 11-15 demo numbers (M1115-01). Pure; no game, no game files."""
from __future__ import annotations

import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(1, str(_pl.Path(__file__).resolve().parent))

import parry_drill as PD

W3000 = [(0.8667, 0.9667)]                       # c2550 3000 (game file)
assert PD.parry_due(W3000, 0.60) is None          # too early: contact would land at parry anim ≈ 0.27 s
assert PD.parry_due(W3000, 0.75) == 0             # 0.117 s left → press
assert PD.parry_due(W3000, 0.85) is None          # 0.017 s left → too late (demo fail at 0.007)
assert PD.parry_due(W3000, 0.75, done={0}) is None
# c2560 3000: real parry 0.14 s before the file window (2 demo cases) → pressed earlier
assert PD.parry_due([(0.8667, 1.0)], 0.62, offset=-0.14) == 0
assert PD.parry_due([(0.8667, 1.0)], 0.75, offset=-0.14) is None
# two windows (c2560 3005): the second one after the first was used
W3005 = [(0.6667, 0.8333), (1.1667, 1.3)]
assert PD.parry_due(W3005, 0.60) == 0
assert PD.parry_due(W3005, 1.10, done={0}) == 1
assert PD.parry_due(None or [], 0.5) is None
assert PD.model_of(255041) == "c2550" and PD.model_of(256002) == "c2560"
print("ok  parry_due: press 0.03–0.12 s before the hit window (offset per attack), once per window")

# memory anim id → the TAE section the foe really plays (11-15 drill 1 + MoKa demo)
WIN = {("c2550", 3004): [(0.3667, 0.5333)], ("c2550", 13004): [(2.0333, 2.1667)], ("c2550", 3009): [(0.7667, 0.9)],
       ("c2560", 3000): [(0.8667, 1.0)], ("c2560", 23000): [(0.7333, 1.0)]}
assert PD.windows_for(WIN, 255041, 3004) == [(2.0333, 2.1667)]      # a01
assert PD.windows_for(WIN, 255041, 3009) == [(0.7667, 0.9)]         # no a01 copy → a00
assert PD.windows_for(WIN, 256002, 3000) == [(0.7333, 1.0)]         # a02
assert PD.windows_for(WIN, 256000, 3000) == [(0.8667, 1.0)]         # a00
assert ("c2550", 3009) in PD.NO_PARRY
print("ok  windows_for: 255041 → a01, 256002 → a02, others a00; c2550 3009 not parried")
assert PD.MAX_PARRY_M < 2.31   # drill 4: 3003 fails at 2.31-2.87 m, all successes <= 1.91 m
