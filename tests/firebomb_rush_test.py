"""M1006-17 ([MoKa] 10-06 · 11-09 M1109-02): a firebomb hollow we can reach is closed in on straight away — sprint while far and
no other awake foe near, and a hit from it doesn't send us out of its line (rule_shot); a ledge one, or a way past a drop edge,
keeps rule_shot. Offline: duel.rush_check on the Burg NavMesh + fakes, and _approach's walk mode. Not a game check."""
from __future__ import annotations

import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(1, str(_pl.Path(__file__).resolve().parent))

from types import SimpleNamespace as NS

import motion
from souls import duel as D
from souls import weapons


def check(what: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + what)
    if not ok:
        raise SystemExit(1)


P = lambda x, y, z: NS(x=x, y=y, z=z)
C = lambda n, x, y, z, ptr=2, anim=-1, hp=75: NS(npc_param=n, x=x, y=y, z=z, ptr=ptr, anim=anim, hp=hp)


class Line:
    """Straight path, every point `drop` m from a drop edge."""
    def __init__(self, drop=9.0, path=True):
        self.drop, self.path = drop, path

    def find_path(self, a, b):
        return [tuple(a[i] + (b[i] - a[i]) * k / 4 for i in range(3)) for k in range(5)] if self.path else []

    def drop_dist(self, x, y, z, dy=2.0):
        return self.drop


# ── rush_check with fakes ───────────────────────────────────────────────────────────────────────────────────────────
me = P(0.0, -49.4, 0.0)
ok, why = D.rush_check(Line(), me, C(254002, 0.0, -49.4, 8.0))
check(f"254002 on the same level, straight way, no drop → close in ({why})", ok)
check("a sword hollow is never rushed", not D.rush_check(Line(), me, C(254010, 0.0, -49.4, 8.0))[0])
ok, why = D.rush_check(Line(drop=0.5), me, C(254002, 0.0, -49.4, 8.0))
check(f"drop edge 0.5 m off the way → no ({why})", not ok and "낙차" in why)
ok, why = D.rush_check(Line(), me, C(254002, 0.0, -43.4, 8.0))
check(f"+6 m up → no ({why})", not ok and "높이" in why)
check("no path → no", not D.rush_check(Line(path=False), me, C(254002, 0.0, -49.4, 8.0))[0])
check("no NavMesh → no", not D.rush_check(None, me, C(254002, 0.0, -49.4, 8.0))[0])

# ── on the Burg NavMesh (m10_01): MoKa's three ledge firebomb hollows (+6 m, plan.md 1-m 10-06) stay ignored ──────────────
nm = motion.load_navmeshes()["m10_01_00_00"]
for spot in ((0.23, -3.96, -90.2), (3.48, -1.75, -86.23), (5.13, -1.803, -84.1)):
    ok, why = D.rush_check(nm, P(-1.0, -10.0, -88.0), C(254012, *spot))
    check(f"ledge 254012 {spot} from below → no ({why})", not ok)
ok, why = D.rush_check(nm, P(14.5, -5.7, -99.4), C(254012, 18.32, -5.72, -105.48))
check(f"east stairs (C) 254012 from MoKa's C fighting spot → close in ({why})", ok)
ok, why = D.rush_check(nm, P(-40.0, -22.7, -30.0), C(254012, -47.26, -22.71, -27.98))
check(f"7.5 m away but a 16.5 m detour → no ({why})", not ok and "경로" in why)


# ── _approach: sprint while far with no one else near, guard-walk otherwise ────────────────────────────────────────────
class Mv:
    def __init__(self, snaps):
        self.snaps, self.modes = snaps, []

    def find(self, s, ptr):
        return next((c for c in s.chars if c.ptr == ptr), None)

    def walk_path(self, path, nm, mode, stop, timeout_per=6.0):
        self.modes = [mode(s) for s in self.snaps]
        return "arrived"


def snap(foe_h, other=None):
    chars = [C(254002, 0.0, -49.4, foe_h)] + ([other] if other else [])
    return NS(player=P(0.0, -49.4, 0.0), chars=chars, cam_yaw=0.0,
              hostile=lambda r, cs=chars: [c for c in cs if c.hp > 0])


foe = D.foes_.FIREBOMB_HOLLOW
mv = Mv([snap(9.0), snap(3.0)])
D._approach(mv, weapons.BATTLE_AXE, snap(9.0), C(254002, 0.0, -49.4, 9.0), Line(), foe, lambda: False, rush=True)
check(f"rush: 9 m → sprint, 3 m (inside NEAR) → guard ({mv.modes})", mv.modes == ["sprint", "guard"])
mv = Mv([snap(9.0)])
D._approach(mv, weapons.BATTLE_AXE, snap(9.0), C(254002, 0.0, -49.4, 9.0), Line(), foe, lambda: False, rush=False)
check(f"no rush: firebomb hollow is guard-walked as before ({mv.modes})", mv.modes == ["guard"])
mv = Mv([snap(9.0, C(254010, 3.0, -49.4, 3.0, ptr=3, anim=3003))])
D._approach(mv, weapons.BATTLE_AXE, snap(9.0), C(254002, 0.0, -49.4, 9.0), Line(), foe, lambda: False, rush=True)
check(f"rush but an awake hollow 4.2 m off → guard, not sprint ({mv.modes})", mv.modes == ["guard"])
print("firebomb_rush_test: 전부 통과")
