"""missions.step_up — where to stand for the second knife try after no lock-on (MoKa 11-15 M1115-17). Pure; no game."""
from __future__ import annotations

import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

from souls import missions as MS

SPOT = (11.2, -6.6, -92.8)                                   # burg-upper zone 4 knife_from spot
up = MS.step_up(SPOT, [(12.0, -6.3, -94.0), (14.0, -5.7, -99.0)])
assert up is not None and abs(((up[0] - SPOT[0]) ** 2 + (up[2] - SPOT[2]) ** 2 + (up[1] - SPOT[1]) ** 2) ** 0.5 - MS.STEP_UP_M) < 1e-6
assert up[1] > SPOT[1]                                       # on the stairs: one step higher
assert MS.step_up(SPOT, [(12.0, -7.6, -94.0)]) is None        # downhill → not a step up
assert MS.step_up(SPOT, []) is None and MS.step_up(SPOT, None) is None
assert MS.step_up(SPOT, [(11.4, -6.6, -93.0)]) is None        # path shorter than one step
up2 = MS.step_up(SPOT, [SPOT, (11.2, -6.6, -91.0)])           # zero-length first leg is skipped
assert up2 is not None and abs(up2[2] - (SPOT[2] + MS.STEP_UP_M)) < 1e-6
# 234637 zone 4: the NavMesh path dips first, then climbs the stairs → skip the low points, step up the stairs
PATH = [(10.94, -6.82, -93.05), (10.02, -7.59, -92.03), (12.58, -5.84, -93.92), (12.53, -5.71, -94.58), (14.36, -5.71, -96.26)]
up3 = MS.step_up(SPOT, PATH)
assert up3 is not None and up3[1] > SPOT[1] and up3[0] > SPOT[0], up3
print(f"ok  step_up: {MS.STEP_UP_M} m along the path toward the foe, never downhill")
