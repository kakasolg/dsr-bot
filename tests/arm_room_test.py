"""P-135 arm room before a knife throw (nav.side_room + Field._arm_room) and the wait after a knife with no reaction
(Missions._lure). MoKa 11-08: right wall close in a narrow passage → the right arm hits it and the throw fails; the sound wakes a
foe, and the bot ran in instead of waiting. Fakes only — no game, no pad.  python tests/arm_room_test.py"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

from types import SimpleNamespace as NS

if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8")

import nav
from souls import field as F
from souls import missions as MS


class Corridor:
    """Floor only where lo ≤ x ≤ hi (a passage running along z)."""
    def __init__(self, lo, hi):
        self.lo, self.hi = lo, hi

    def floor_at(self, x, z, y):
        return (0.0,) if self.lo - 1e-9 <= x <= self.hi + 1e-9 else None


def me(x=0.0, z=0.0):
    return NS(x=x, y=0.0, z=z, gx=x, gy=0.0, gz=z, hp=1018)


def main() -> None:
    # facing −z (target straight ahead at z −12): right = (fz, −fx) = (−1, 0) → −x
    r, l = nav.side_room(Corridor(-0.2, 0.8), me(), 0.0, -12.0)
    assert abs(r - 0.2) < 0.06 and abs(l - 0.8) < 0.06, (r, l)
    print(f"ok  side_room: right {r} m (−x) · left {l} m (+x) facing −z")

    def field(corr, pos):
        f = F.Field.__new__(F.Field)
        f.log = lambda *a, **k: None
        state = {"p": me(*pos)}
        target = NS(ptr=9, x=0.0, y=0.0, z=-12.0, hp=75)
        f.mv = NS(snap=lambda r: NS(player=state["p"]), find=lambda s, ptr: target)
        f.goals = []

        def settle(goal, tol=None, tries=10, scale=0.45):
            assert scale >= 0.4, scale                         # 202047: 0.25 is inside the stick deadzone — moved 0.00 m
            f.goals.append(goal)
            state["p"] = me(goal[0], goal[2])
            return 0.0
        f._settle = settle
        return f

    f = field(Corridor(-0.2, 0.8), (0.0, 0.0))                     # 194800: right 0.2 · left 0.8
    out = f._arm_room(9, Corridor(-0.2, 0.8), "t")
    assert f.goals and abs(f.goals[0][0] - 0.65) < 0.06 and abs(f.goals[0][2]) < 1e-6, f.goals
    assert out["right_after"] >= 0.8, out
    print(f"ok  right 0.2 / left 0.8 → hug the left (x {f.goals[0][0]:.2f}, 0.15 m kept), right after {out['right_after']}")

    f = field(Corridor(-0.1, 0.5), (0.0, 0.0))                     # 0.6 m passage → still the left side (MoKa 11-08)
    f._arm_room(9, Corridor(-0.1, 0.5), "t")
    assert f.goals and abs(f.goals[0][0] - 0.35) < 0.06, f.goals
    print(f"ok  narrow 0.6 m passage → left side (x {f.goals[0][0]:.2f})")

    f = field(Corridor(-2.0, 2.0), (0.0, 0.0))                     # wide → stay
    out = f._arm_room(9, Corridor(-2.0, 2.0), "t")
    assert not f.goals and out["moved"] == 0.0, (f.goals, out)
    print("ok  wide floor → no move")

    # Missions._lure: knife thrown, no reaction → wait at the safe spot; someone comes → 'here' (no body run)
    safe = (11.2, -6.6, -92.8)
    t = NS(ptr=5, npc_param=254011, x=17.8, y=-5.7, z=-103.7, hp=75, anim=-1)
    nb_ = NS(ptr=6, npc_param=254010, x=15.5, y=-5.7, z=-103.6, hp=75, anim=-1)
    snap = NS(player=NS(x=safe[0], y=safe[1], z=safe[2], hp=1018), hostile=lambda r: [t, nb_])
    calls = []
    m = MS.Missions.__new__(MS.Missions)
    m.log = lambda *a, **k: None
    m.zone_n = 4
    m._has = lambda item: True
    m.mv = NS(snap=lambda r: snap, find=lambda s, ptr: t)
    m.f = NS(lure=lambda *a, **k: "no_reaction", alive=lambda: True)
    m._wait_at_safe = lambda ptr, safe_, secs, **k: calls.append(("wait", secs)) or True
    m._sprint = lambda *a, **k: calls.append(("sprint",)) or "arrived"
    r = m._lure(t, t.ptr, safe, None, "구역4-1 254011", {})
    assert r == "here" and calls == [("wait", MS.NOISE_WAIT_S)], (r, calls)
    print(f"ok  no_reaction → wait {MS.NOISE_WAIT_S:g} s at the safe spot, a foe came → 'here' (no sprint)")


if __name__ == "__main__":
    main()
