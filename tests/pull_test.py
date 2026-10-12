"""Body pull, split with no spot, hit from afar (souls/pull.py, duel._escape_way / rule_shot, Field.notice_pull — 10-11). No game.

  python tests/pull_test.py

  [MoKa] 2026-10-11: "그 전에는 하나씩 순차적으로 처리 해야 하고 플레이어는 감각적으로 투척 나이프 없이도 대략적인 상대가 캐릭터가
  어느 정도 움직이면 끌려 오니깐 하나만 나를 인지하게 해서 유인을 하는데 이 과정이 지금 없는 것 같음."

Checks:
  · notice_r from data/notice.json (shield soldier ~9 m, unknown foe DEFAULT_R), plan() keeps out of other calm foes' notice
    range and MIN_R of the target, split() stops every STEP from rt + NEAR, Watch (anim / move / turn / idle / dormant)
  · Field.notice_pull in a fake world: stops advancing where the target wakes and runs back · stops short of a second foe and
    reports no_reaction · doesn't turn its back when the woken one is already close
  · duel._escape_way: no straight-line split spot → the first ≤ SEP_ESCAPE_M of escape.pick's path on the Firelink NavMesh;
    nothing on golden's stand-in NavMesh (no graph)
  · rule_shot: thrower hit with the melee foe staggered → 'shot'; a melee swing → not; a fall (no thrower) → not; a melee foe
    on us → hold the first shot, leave on the second
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import math
import sys
import types

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from souls import foes as foes_
from souls import duel as D
from souls import field as F
from souls import pull as P
import field_fakes as FF


def check(name: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        raise SystemExit(1)


class LineNm:
    """Straight paths on flat ground."""
    def find_path(self, a, b):
        return [tuple(a), tuple(b)]


def pure() -> None:
    t = P.load_table()
    check(f"notice_r: shield soldier 255000 ~9 m from the records ({P.notice_r(t, 255000, 10):.1f})", 8.0 <= P.notice_r(t, 255000, 10) <= 10.0)
    check("notice_r: a foe not in the table → DEFAULT_R", P.notice_r(t, 999999) == P.DEFAULT_R)
    check("notice_r: a side row with < MIN_N events → the foe's 'all' row",
          P.notice_r({"1": {"back": {"n": 1, "d": 2.0}, "all": {"n": 9, "d": 6.0}}}, 1, 170) == 6.0)

    tgt = (0.0, 0.0, 20.0)
    pts, why, reach = P.plan([(0.0, 0.0, 0.0), tgt], tgt, [], 8.0)
    check(f"plan, nobody else: walk up to MIN_R of the target ({why}, {reach:.2f} m)", why == "min_r" and abs(reach - P.MIN_R) < 0.3)
    other = (3.0, 0.0, 12.0, 5.0)
    pts, why, reach = P.plan([(0.0, 0.0, 0.0), tgt], tgt, [other], 8.0)
    worst = min(math.hypot(q[0] - other[0], q[2] - other[2]) for q in pts)
    check(f"plan, a calm foe beside the path: stops before its notice range + MARGIN ({why}, reach {reach:.1f} m, closest {worst:.2f})",
          why == "other" and worst >= other[3] + P.MARGIN - 1e-6 and reach > 8.0)
    pts, why, reach = P.plan([(0.0, 0.0, 0.0), tgt], tgt, [(3.0, 8.0, 12.0, 5.0)], 8.0)
    check("plan: a foe on another level (8 m up) doesn't stop it", why == "min_r")
    pts, _, _ = P.plan([(0.0, 0.0, 0.0), tgt], tgt, [], 8.0)
    far, stops = P.split(pts, tgt, 8.0)
    gaps = [math.dist(a, b) for a, b in zip(stops, stops[1:])]
    check(f"split: plain walk until rt + NEAR, then a stop every ~STEP ({len(stops)} stops)",
          math.hypot(far[-1][0] - tgt[0], far[-1][2] - tgt[2]) > 8.0 + P.NEAR - 0.3
          and math.hypot(stops[0][0] - tgt[0], stops[0][2] - tgt[2]) <= 8.0 + P.NEAR
          and all(g <= P.STEP + 0.26 for g in gaps) and stops[-1] == pts[-1])

    c = types.SimpleNamespace(x=0.0, z=10.0, anim=-1, heading=0.0)       # forward (−sin 0, −cos 0) = −z: looking at us at the origin
    w = P.Watch(c)
    me = (0.0, 0.0, 0.0)
    check("Watch: standing still → nothing", w.update(c, me, 0.0) is None)
    c.anim = 9001
    check("Watch: a dormant anim (9000–9099) → still nothing", w.update(c, me, 0.1) is None)
    c.anim = 3000
    check("Watch: an attack anim → 'anim'", w.update(c, me, 0.2) == "anim")
    c2 = types.SimpleNamespace(x=0.0, z=10.0, anim=-1, heading=math.pi)  # back to us
    w2 = P.Watch(c2)
    w2.update(c2, me, 0.0)
    c2.heading = 0.0
    check("Watch: back to us, then facing us → 'turn'", w2.update(c2, me, 0.1) == "turn")
    c2.x = 1.0
    check("Watch: moved 1 m → 'move'", w2.update(c2, me, 0.2) == "move")


def fake_world(wake_r: float, other=None, jump_to=None, chase: bool = True, npc: int = 254010):
    """Player at the origin, target npc at z 20 facing us; it wakes (anim 3000) once we're within wake_r and, with jump_to,
    stands that far from us at once; with chase it then comes 0.3 m toward us per look (else it stays on its spot).
    The fake walk_path moves the player 0.25 m at a time and asks stop() each time."""
    world = FF.World(player=(0.0, 0.0, 0.0))
    tgt = world.add(ptr=2, handle=0x1002, npc=npc, pos=(0.0, 0.0, 20.0))
    tgt.heading = 0.0
    if other is not None:
        o = world.add(ptr=3, handle=0x1003, npc=254011, pos=other)
        o.heading = math.pi
    f = FF.make_field(world)
    f.trail = []
    f.home = None
    modes = []
    real_snap = f.mv.snap

    def snap(within: float = 40.0):
        p = world.player
        if tgt.anim == -1 and math.hypot(tgt.x - p.x, tgt.z - p.z) < wake_r:
            tgt.anim = 3000
            if jump_to is not None:
                d = math.hypot(tgt.x - p.x, tgt.z - p.z)
                tgt.x, tgt.z = p.x + (tgt.x - p.x) / d * jump_to, p.z + (tgt.z - p.z) / d * jump_to
        elif chase and tgt.anim == 3000:
            d = math.hypot(tgt.x - p.x, tgt.z - p.z)
            if d > 1.0:
                tgt.x, tgt.z = tgt.x + (p.x - tgt.x) / d * 0.3, tgt.z + (p.z - tgt.z) / d * 0.3
        return real_snap(within)

    def walk_path(path, nm, mode="walk", stop=None, **kw):
        modes.append(mode)
        p = world.player
        for q in path:
            while math.hypot(q[0] - p.x, q[2] - p.z) > 0.01:
                d = math.hypot(q[0] - p.x, q[2] - p.z)
                k = min(0.25, d) / d
                p.x, p.z = p.x + (q[0] - p.x) * k, p.z + (q[2] - p.z) * k
                if stop is not None and stop(snap()):
                    return "stopped"
        return "arrived"

    f.mv.snap = snap
    f.mv.walk_path = walk_path
    return world, f, tgt, modes


def field_pull() -> None:
    P.LOOK_S, P.WAIT_S = 0.01, 0.05
    back = (0.0, 0.0, -2.0)
    world, f, tgt, modes = fake_world(wake_r=7.0)
    r = f.notice_pull(2, LineNm(), back, "#t")
    p = world.player
    check(f"notice_pull: the target wakes at ~7 m → 'came', ran back to the spot ({r}, modes {modes[-1]}, at z {p.z:.1f})",
          r == "came" and modes[-1] == "sprint" and math.hypot(p.x - back[0], p.z - back[2]) < 1.6)
    woke_at = next((ln for ln in f.logs if "깸" in ln), "")
    check(f"… logged who woke ({woke_at.strip()})", "254010" in woke_at)

    world, f, tgt, modes = fake_world(wake_r=2.0, other=(4.0, 0.0, 10.0))
    r = f.notice_pull(2, LineNm(), back, "#t")
    p = world.player
    d_other = math.hypot(p.x - 4.0, p.z - 10.0)
    r_other = P.notice_r(P.load_table(), 254011, 0.0)
    check(f"notice_pull: a calm 254011 beside the path → stopped {d_other:.1f} m from it (its range {r_other:.1f} + MARGIN), "
          f"target never woke → {r}", r == "no_reaction" and d_other >= r_other + P.MARGIN - 0.3 and "sprint" not in modes)

    world, f, tgt, modes = fake_world(wake_r=7.0, jump_to=2.0)
    r = f.notice_pull(2, LineNm(), back, "#t")
    check(f"notice_pull: the woken one is already 2 m away → no turning our back ({r}, modes {modes})",
          r == "came" and "sprint" not in modes and any("돌아서지 않고" in ln for ln in f.logs))

    world, f, tgt, modes = fake_world(wake_r=7.0)
    tgt.anim = 3000
    check("notice_pull: already awake → 'awake', no walking", f.notice_pull(2, LineNm(), back, "#t") == "awake" and not modes)

    P.COME_S = 0.2
    world, f, tgt, modes = fake_world(wake_r=7.0, chase=False)
    r = f.notice_pull(2, LineNm(), back, "#t")
    check(f"notice_pull: woke but stays on its spot (10-11 on#1) → 'stayed', not 'came' ({r})",
          r == "stayed" and any("안 옴" in ln for ln in f.logs))
    world, f, tgt, modes = fake_world(wake_r=7.0, npc=254002)
    r = f.notice_pull(2, LineNm(), back, "#t")
    check(f"notice_pull: firebomb hollow 254002 (a thrower) → '{r}', no walking", r == "thrower" and not modes)
    world, f, tgt, modes = fake_world(wake_r=7.0, npc=254001)
    r = f.notice_pull(2, LineNm(), back, "#t")
    check(f"notice_pull: axe hollow 254001 (ranged, not a thrower) is still pulled → {r}", r == "came")


def escape_way() -> None:
    import motion
    nm = motion.load_navmeshes()["m10_02_00_00"]
    here = (-26.5, -48.3, 28.6)                           # ramp flat (10-03e)
    s = types.SimpleNamespace(hostile=lambda r: [])
    trail = [(-30.0 + 0.0, -49.3, 40.0 - k) for k in range(12)]
    way = D._escape_way(s, nm, here, trail)
    length = sum(math.hypot(b[0] - a[0], b[2] - a[2]) for a, b in zip([here, *way], way))
    check(f"_escape_way on the Firelink NavMesh: {len(way)} points, {length:.1f} m ≤ SEP_ESCAPE_M", way and length <= D.SEP_ESCAPE_M + 1e-6)
    import duel_golden_test as G
    check("_escape_way on golden's stand-in NavMesh (no graph) → nothing (golden unchanged)", D._escape_way(s, G.Nm(), here, trail) == [])
    D.SEP_ESCAPE = False
    try:
        check("SEP_ESCAPE off → nothing (the old no_spot)", D._escape_way(s, nm, here, trail) == [])
    finally:
        D.SEP_ESCAPE = True


def shot() -> None:
    C = lambda ptr, npc, x, z, anim, y=0.0: types.SimpleNamespace(ptr=ptr, npc_param=npc, x=x, y=y, z=z, anim=anim, hp=50)

    def run(ticks, t0=-10.0):
        """ticks: [(hp, [chars], now)] → what rule_shot returned on the last tick, and the fight (started at t0)."""
        Fi = types.SimpleNamespace(t0=t0, shot_hp=None, shots=[], swung={}, log=lambda *a: None, note=lambda *a: None,
                                   res=D.DuelResult("timeout"), done=lambda r: ("done", r))
        out = None
        for hp, chars, now in ticks:
            p = types.SimpleNamespace(x=0.0, y=0.0, z=0.0, hp=hp)
            s = types.SimpleNamespace(hostile=lambda r, cs=chars: [c for c in cs if math.hypot(c.x, c.z) <= r])
            out = D.rule_shot(Fi, types.SimpleNamespace(s=s, p=p, now=now, c=chars[0]))
        return out, Fi

    bomber = lambda a: C(5, 254002, 0.0, 9.0, a, y=3.0)
    out, Fi = run([(616, [C(2, 255010, 0.0, 1.5, 3500), bomber(3008)], 0.0), (503, [C(2, 255010, 0.0, 1.5, 3500), bomber(-1)], 1.2)])
    check(f"rule_shot: −113 while the shield soldier next to us staggers, the ledge bomber threw 1.2 s ago → {out}",
          out == ("done", "shot") and Fi.res.shot_from[3] == 254002)
    out, _ = run([(616, [C(2, 255010, 0.0, 1.5, 3000), bomber(-1)], 0.0), (503, [C(2, 255010, 0.0, 1.5, 3000), bomber(-1)], 0.5)])
    check("rule_shot: the foe 1.5 m away is swinging → a melee hit, not a shot", out is None)
    out, _ = run([(616, [C(2, 255010, 0.0, 6.0, -1)], 0.0), (503, [C(2, 255010, 0.0, 6.0, -1)], 0.5)])
    check("rule_shot: nobody threw and no known thrower → a fall / unknown, not a shot", out is None)
    # P-59: melee hollows that swung from beyond the old 4 m, a mislabelled axe hollow, a swing from before the duel
    out, _ = run([(616, [C(2, 254010, 0.0, 5.7, 3004)], 0.0), (570, [C(2, 254010, 0.0, 7.0, -1)], 0.5)])
    check("rule_shot P-59: a sword hollow's 3004 from 5.7 m, hit at 7.0 m → a lunge, not a shot (09-28z)", out is None)
    out, _ = run([(616, [C(2, 254010, 0.0, 4.3, 3005), bomber(-1)], 0.0), (511, [C(2, 254010, 0.0, 5.2, 3005), bomber(-1)], 0.5)])
    check("rule_shot P-59: a 3005 lunge landing from 5.2 m with a bomber in view → melee (10-01a)", out is None)
    out, _ = run([(616, [C(2, 254010, 0.0, 7.4, 3008)], 0.0), (560, [C(2, 254010, 0.0, 7.4, -1)], 1.0)])
    check("rule_shot P-59: a sword hollow that swung 7.4 m off is not a thrower (09-30b)", out is None)
    out, _ = run([(616, [C(3, 254001, 0.0, 7.9, -1)], 0.0), (508, [C(3, 254001, 0.0, 7.9, -1)], 0.5)])
    check("rule_shot P-59: axe hollow 254001 (ranged for lure, throws=False) is not a thrower (061145 60.6 s)", out is None)
    near = C(4, 254000, 0.0, 0.9, 3006)
    out, _ = run([(616, [near, bomber(-1)], 0.3), (505, [near, bomber(-1)], 0.8)], t0=0.0)
    check("rule_shot P-59: 0.8 s into the duel, a hollow 0.9 m off mid-swing → melee (the swing started before the duel)", out is None)
    idle = C(4, 254000, 0.0, 3.0, -1)
    out, _ = run([(616, [idle, bomber(3008)], 0.3), (505, [idle, bomber(-1)], 0.8)], t0=0.0)
    check(f"rule_shot P-59: … but an idle one 3 m off doesn't hide the bomber's throw → {out}", out == ("done", "shot"))
    check("foes: AXE_HOLLOW still ranged (lure / waiting unchanged), not a thrower; bombers / crossbow are",
          foes_.of(254001).ranged and not foes_.of(254001).thrower and foes_.of(254002).thrower and foes_.of(255002).thrower
          and not foes_.of(254010).thrower)
    walk = C(2, 254010, 0.0, 2.0, 701)
    out, Fi = run([(616, [walk, bomber(3008)], 0.0), (520, [walk, bomber(-1)], 1.0)])
    check("rule_shot: an awake melee foe on us (2 m, not staggered) → hold the first shot", out is None and len(Fi.shots) == 1)
    out, Fi = run([(616, [walk, bomber(3008)], 0.0), (520, [walk, bomber(-1)], 1.0), (520, [walk, bomber(3008)], 5.0),
                   (430, [walk, bomber(-1)], 6.0)])
    check("rule_shot: … and leave on the second within SHOT_AGAIN_S", out == ("done", "shot") and len(Fi.shots) == 2)
    check("rule_shot is first in RULES (sees every tick)", D.RULES[0] is D.rule_shot)

    # P-66 b (161435 77.3–80.6 s): the shield soldier swung 3004 from 77.3 s, the kick combo ran 78.1–80.6 s (no rule ticks), its
    # 3004 hit −228 at 78.6 s; at 80.6 s it was staggered (2006) and the hit was read as the bomber's. The swing was seen only by
    # snapshots read inside the combo — Moves.swung keeps those for rule_shot
    import time as _time
    from souls import moves as Mv
    soldier = lambda a, z=1.7: C(2, 255010, 0.0, z, a)
    far_bomber = C(5, 254002, 0.0, 16.5, -1, y=10.1)
    base = _time.time() - 3.3

    def combo_case(shared: bool):
        m = Mv.Moves.__new__(Mv.Moves)
        Fi = types.SimpleNamespace(t0=base - 8.0, shot_hp=None, shots=[], swung=m.__dict__.setdefault("swung", {}) if shared else {},
                                   log=lambda *a: None, note=lambda *a: None, res=D.DuelResult("timeout"), done=lambda r: ("done", r))
        tick = lambda hp, chars, now: D.rule_shot(Fi, types.SimpleNamespace(
            s=types.SimpleNamespace(hostile=lambda r, cs=chars: [c for c in cs if math.hypot(c.x, c.z) <= r]),
            p=types.SimpleNamespace(x=0.0, y=0.0, z=0.0, hp=hp), now=now, c=chars[0]))
        tick(699, [soldier(3004, 2.4), far_bomber], base)                         # the last rule tick before the combo
        _time.sleep(0.05)
        m._note_swings(types.SimpleNamespace(chars=[soldier(3004, 1.5), far_bomber]))   # inside the combo's _watch
        out = tick(471, [soldier(2006), far_bomber], _time.time() + 1.0)           # the next rule tick, after the combo
        return out, Fi
    out, Fi = combo_case(shared=False)
    check("P-66 b before: a swing seen only inside the combo is lost → the −228 is counted as a shot", out is None and len(Fi.shots) == 1)
    out, Fi = combo_case(shared=True)
    check("P-66 b: Moves.swung (every snapshot) keeps it → a melee hit, no shot counted", out is None and Fi.shots == [])


def main() -> None:
    pure()
    field_pull()
    escape_way()
    shot()
    check("NOTICE_PULL is off by default (run.py --pull)", F.NOTICE_PULL is False)
    print("pull_test: 전부 통과")


if __name__ == "__main__":
    main()
