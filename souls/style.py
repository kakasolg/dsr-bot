"""Style — cross-cutting concerns in one object (2026-09-25 layer design, step 3). Each layer only reads it.

  guard    : one-handed + shield. Reflex faces and blocks, hits on stagger.          (baseline 10/10, median damage 282)
  backstep : two-handed, no shield. Reflex backsteps (+attack), punishes after a whiff at 1.1 s, beyond 1.8 m. (double damage — experiment for wide flat ground / hollows only)
  rush     : two-handed, no shield, reflex (block/evade) turned off entirely — keep attacking, survive on Estus
             (user 2026-09-25: "On the way to the shooter, kill the others coming at you two-handed. Don't defend either, just drink Estus")
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Style:
    name: str
    shield: bool            # raise the shield? (if False, moves.guard is ignored)
    grip: int               # 1 one-handed | 3 two-handed (set before the fight)
    evade: bool             # reflex evades instead of blocking?
    bs_attack: bool         # add a backstep attack (B → R1) when evading? (layer 4 excludes shield users via bs_ok)
    punish_after: float     # punish after whiff: only this long after the attack starts
    punish_min_r: float     # punish after whiff: skip if closer than this
    reflex_on: bool = True  # use reflex (block/evade)? — if False, reflex only logs and does not move, so the attack loop is not interrupted


GUARD = Style("guard", shield=True, grip=1, evade=False, bs_attack=False, punish_after=1.1, punish_min_r=1.8)
BACKSTEP = Style("backstep", shield=False, grip=3, evade=True, bs_attack=True, punish_after=1.1, punish_min_r=1.8)
RUSH = Style("rush", shield=False, grip=3, evade=False, bs_attack=False, punish_after=1.1, punish_min_r=1.8, reflex_on=False)
BY_NAME = {s.name: s for s in (GUARD, BACKSTEP, RUSH)}


def of(name) -> Style:
    return name if isinstance(name, Style) else BY_NAME[name]
