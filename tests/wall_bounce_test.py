"""무기가 벽에 튕기면 같은 자리에서 다시 안 휘두름 (P-139, [MoKa] 2026-11-08 "무기가 벽에 부딪혀서 공격 실패함" ·
"가운데가 차라리 낫지" · "감지가 되면 다른데로 가야지"). Fakes only — no game, no pad.  python tests/wall_bounce_test.py"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import math
from types import SimpleNamespace as NS

if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8")

from souls import duel as D
from souls import moves as M
from souls import reflex as R


class Corridor:
    """Floor only where lo ≤ x ≤ hi (a passage running along z)."""
    def __init__(self, lo, hi):
        self.lo, self.hi = lo, hi

    def floor_at(self, x, z, y):
        return (0.0,) if self.lo - 1e-9 <= x <= self.hi + 1e-9 else None


def me(x=0.0, z=0.0, heading=0.0):
    return NS(x=x, y=0.0, z=z, gx=x, gy=0.0, gz=z, hp=500, sp=80, anim=-1, heading=heading)


def hit(seq, dmg=0):
    return M.Hit("light", presses=1, dmg=dmg, my_anims=[(0.1 * i, a) for i, a in enumerate(seq)])


def test_detect() -> None:
    # 221120 구역 4 기록 그대로
    assert R.wall_bounced(hit([-1, 303000, 303150, -1]))
    assert R.wall_bounced(hit([-1, 303000, 303150, 2003]))
    assert not R.wall_bounced(hit([-1, 303000, -1], dmg=59))
    assert not R.wall_bounced(hit([140, 303000, 2003, -1]))           # cut off before the blade came out — not a wall
    assert not R.wall_bounced(hit([-1, 140, 2150]))                    # small anims (…150 below 100000) are not attack anims
    print("ok  303000 → 303150 = wall bounce; a hit, an interrupted swing or a small anim = not")


def test_spot() -> None:
    rf = R.Reflex(NS())
    assert rf.note_bounce(me(1.0, 2.0), hit([-1, 303000, 303150]))
    assert not rf.note_bounce(me(1.0, 2.0), hit([-1, 303000, -1]))
    assert rf.at_bounce(me(1.3, 2.2)) is not None and rf.at_bounce(me(1.0, 2.8)) is None
    rf.note_bounce(me(1.1, 2.0), hit([303000, 303150]))
    assert len(rf.bounces) == 1, rf.bounces                            # same spot, not a second one
    print(f"ok  bounce spot remembered within {R.BOUNCE_SPOT_R} m; the same spot again stays one spot")


def test_guard_counter_skips_spot() -> None:
    lights = []
    mv = NS(weapon=NS(reach=1.6, sp_min=30), light=lambda s_, c, n=1: lights.append(c.ptr) or M.Hit("light"))
    rf = R.Reflex(mv)
    p = me()
    p.anim = 140
    sw = next(a for a in (3000, 3005) if a in M.ATTACK)
    foe = NS(ptr=5, x=0.0, y=0.0, z=-1.2, anim=sw, hp=75, npc_param=254010)
    s = NS(player=p, hostile=lambda r: [foe])
    rf.bounces.append([0.0, 0.0, __import__("time").time(), 0])
    assert rf.guard_counter(s, prefer=5) is None and not lights and "벽" in rf.gc_last[3], rf.gc_last
    print("ok  guard counter: no light from a bounce spot (why: 벽에 튕긴 자리)")


def fight(corr, p, foe_anim=-1):
    taps, logs, notes, backs = [], [], [], []
    state = {"p": p}
    foe = NS(ptr=5, x=0.0, y=0.0, z=-1.3, anim=foe_anim, hp=16, npc_param=254010)

    def snap(r=5.0):
        return NS(player=state["p"], cam_yaw=0.0, hostile=lambda rr: [foe])

    def move(x, y):
        if x or y:
            taps.append((x, y))
    def stick_to(sn, gx, gz, scale):
        assert scale >= 0.4, scale
        q = sn.player
        state["p"] = me(gx, gz, q.heading)                               # one tap lands on the goal (fake)
        return (gx - q.x, gz - q.z)
    mv = NS(snap=snap, stick_to=stick_to, pad=NS(move=move), guard=lambda on: None, backstep=lambda: backs.append(1))
    rf = R.Reflex(mv)
    F = NS(reflex=rf, nm=corr, mv=mv, style=NS(shield=True), log=logs.append, note=lambda k, *a: notes.append(k), backstep_t=0.0)
    T = NS(p=p, s=snap(), c=foe, a=foe_anim, h=M.horiz(p, foe), now=10.0)
    return F, T, taps, logs, notes, backs, state


def test_rule() -> None:
    # 오른쪽 벽에 붙음 (facing −z: right = −x): right 0.1, left 0.9 → middle is +0.4 m to the left (+x)
    p = me(-0.1, 0.0, heading=0.0)
    F, T, taps, logs, notes, backs, state = fight(Corridor(-0.2, 0.8), p)
    assert D.rule_wall_bounce(F, T) is None                              # no bounce yet → other rules
    F.reflex.note_bounce(p, hit([-1, 303000, 303150, -1]))
    assert D.rule_wall_bounce(F, T) == D.CONT and taps and notes[-1] == "벽튕김가운데", (taps, notes)
    q = state["p"]
    assert abs(q.x - 0.3) < 0.06, q.x                                   # 0.1 / 0.9 → 0.5 / 0.5
    print(f"ok  bounce against the right wall → step to the middle (x {q.x:.2f}): {logs[-1].strip()}")
    # still on the spot (the step failed): next time a backstep, then hand back to the other rules
    T.p = p
    assert D.rule_wall_bounce(F, T) == D.CONT and backs == [1] and notes[-1] == "벽튕김백스텝", (backs, notes)
    assert D.rule_wall_bounce(F, T) is None and "옮길 데 없음" in logs[-1], logs
    print("ok  still on the spot → backstep once → then nothing more to try (other rules)")
    # foe swinging at us on the spot → shield first (rule steps aside)
    sw = next(a for a in (3000, 3005) if a in M.ATTACK)
    F, T, taps, logs, notes, backs, _ = fight(Corridor(-0.2, 0.8), me(-0.1, 0.0), foe_anim=sw)
    F.reflex.note_bounce(T.p, hit([303000, 303150]))
    assert D.rule_wall_bounce(F, T) is None and not taps and not backs
    print("ok  foe swinging → rule steps aside (shield first)")
    # already in the middle (0.5 / 0.5) → no sideways step, backstep
    F, T, taps, logs, notes, backs, _ = fight(Corridor(-0.5, 0.5), me(0.0, 0.0))
    F.reflex.note_bounce(T.p, hit([303000, 303150]))
    assert D.rule_wall_bounce(F, T) == D.CONT and not taps and backs == [1], (taps, backs)
    print("ok  already in the middle → backstep (go somewhere else)")


def test_order_and_record() -> None:
    i = D.RULES.index
    assert i(D.rule_wall_bounce) < i(D.rule_finish_first) < i(D.prep_reflex), [r.__name__ for r in D.RULES[:5]]
    logs = []
    rf = R.Reflex(NS())
    F = D.Fight.__new__(D.Fight)
    F.reflex, F.log = rf, logs.append
    F.mv = NS(snap=lambda r: NS(player=me(2.0, 3.0)))
    F.res = NS(hits=[], dealt=0)
    F.record(hit([-1, 303000, 303150, -1]))
    assert len(rf.bounces) == 1 and "벽에 튕김" in logs[-1], (rf.bounces, logs)
    print("ok  RULES: wall_bounce before finish_first and reflex; Duel.record remembers the spot")


def main() -> None:
    test_detect()
    test_spot()
    test_guard_counter_skips_spot()
    test_rule()
    test_order_and_record()


if __name__ == "__main__":
    main()
