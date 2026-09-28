"""Passage entrance: the user's corner point goes back in between run point 69 and a0 on the way in (radar records 2026-09-27)."""
from __future__ import annotations

import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(1, str(_pl.Path(__file__).resolve().parent))

from souls import missions as MS

pts = [(-22.1, -34.88, 10.79), MS.ENTRY_AFTER, MS.PASSAGE_A0, (-26.64, -33.94, 5.44)]
out = MS._with_entry_corner(pts)
assert out[1] == MS.ENTRY_AFTER and out[2] == MS.ENTRY_CORNER and out[3:6] == MS.ENTRY_WALK and out[6] == MS.PASSAGE_A0, out
assert MS._with_entry_corner(pts[2:]) == pts[2:]                     # already past the entrance — nothing added
print("ok  entry corner + the user's walk-in points between run 69 and a0; not when starting at a0")
