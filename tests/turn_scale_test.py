"""Sharp turns: slower stick so the character doesn't slide sideways (user 2026-09-28, passage entrance)."""
from __future__ import annotations

import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import math

import nav

# heading 0 → facing world yaw π, i.e. toward −z
assert nav.turn_scale(0.0, 0.0, -1.0) == 1.0                                  # straight ahead
assert nav.turn_scale(0.0, math.sin(math.pi + 0.5), math.cos(math.pi + 0.5)) == 1.0   # 29° off
assert nav.turn_scale(0.0, 1.0, -1.0) == nav.TURN_SLOW_K[0] or nav.turn_scale(0.0, 1.0, -1.0) == 1.0   # 45° boundary
assert nav.turn_scale(0.0, 1.0, 0.0) == nav.TURN_SLOW_K[0]                    # 90°
assert nav.turn_scale(0.0, 0.0, 1.0) == nav.TURN_SLOW_K[1]                    # behind
assert nav.turn_scale(None, 1.0, 0.0) == 1.0
print("ok  turn_scale: full ahead, slower past 45°, slowest past 90°")
