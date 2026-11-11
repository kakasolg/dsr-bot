"""P-89 scene 20261019_212954 bundle n2 (HP 611 → 354) replayed through today's souls.reflex.Reflex — pins which foe it guards
against, no game.  python tests/p89_reflex_scene_test.py

Source: data/samples/20261019_p89_ab_run3_timelines.txt, bundle n2 (t = s before the drop). 255041 = ptr 5904, 255042 = ptr
99248 (duel's target, so Reflex.prefer = 99248 every tick as duel sets it). Distances and angles off my facing come from the
nearest frame / scene line; the player faces +z (heading −π) and 255042 sits about in front, as the scene lines say.

Times not printed in the log but derived from it:
  · 255041's 3004 first seen by reflex at −2.056 = −1.892 − 0.164 (the "age 0.164" line) — the −2.079 frame is the feed's read,
    not reflex's update; only update() is called there (whether a tick acted at −2.056 isn't logged)
  · 255042's 3003 start −2.842 = −2.572 − 0.27 (the "age 0.27" line)
  · 255041's earlier 3009 start isn't logged → seeded as "anim 3009, no start" (never a threat; only makes 3004 a change)

Pins the current behaviour against the recorded reflex lines (not a judgement that it is right):
  · −2.572 guard vs 255042 (prefer, age 0.27)       · −1.892 guard vs 255041 (lock on 255042 lapsed: 3500 is stagger)
  · −1.434 … −0.903 the "rule reflex" ticks keep guarding 255041. The log has no per-tick reflex target: dec.reflex is written
    only when (act, target) changes, and dec.rule says reflex acted but not against whom. No new dec.reflex line there (ctl end:
    dropped 0, lost 0) does not contradict this test, but it is not direct per-tick evidence of the target
  · −0.722 … −0.575 (stagger_punish ticks, rule_reflex ran first) reflex does nothing: 255041 still in 3004 at 0.90 m but
    its age 1.33 s > THREAT_S 1.3 → not a threat
  · −0.502 guard vs 255042, age 0 (255041 not a threat then either — the only threat, prefer doesn't decide it)
Ticks where rule_face_first fired (−1.503, −1.337, …) never reached rule_reflex (duel.RULES order) and aren't replayed.
P-89 candidate B (threat window up to windup_land_s) would change the −0.722 … −0.502 lines; this test is the place to see it.
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import math
import sys
from types import SimpleNamespace as NS

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from souls import reflex as R
from telemetry import Chr, Snapshot

A41, A42 = 5904, 99248
T0 = 1000.0          # fake clock origin = the drop (t 0)


def check(name: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        raise SystemExit(1)


def foe(ptr: int, npc: int, anim: int, d: float, deg: float) -> Chr:
    a = math.radians(deg)              # off my facing, + = right; facing +z (heading −π) → (x, z) = d·(sin, cos)
    return Chr(ptr=ptr, npc_param=npc, team=6, hp=200, max_hp=200, x=d * math.sin(a), y=0.0, z=d * math.cos(a), anim=anim, dist=d)


def snap(t: float, hp: int, f41: tuple, f42: tuple) -> Snapshot:
    p = Chr(ptr=1, npc_param=0, team=1, hp=hp, max_hp=800, x=0.0, y=0.0, z=0.0, sp=100, max_sp=100, heading=-math.pi)
    cs = sorted([foe(A41, 255041, *f41), foe(A42, 255042, *f42)], key=lambda c: c.dist)
    return Snapshot(t=T0 + t, player=p, chars=cs)


#           t       hp   255041 (anim, d, deg)   255042 (anim, d, deg)   expected (act, ptr) — None = reflex did nothing
TICKS = [(-2.572, 613, (3009, 1.39, 8), (3003, 0.89, 17), ("guard", A42)),
         (-2.056, 613, (3004, 0.98, 0), (3003, 0.85, 20), "update"),       # reflex first sees 255041's 3004 (update only)
         (-1.892, 611, (3004, 0.96, -141), (3500, 0.85, 2), ("guard", A41)),
         (-1.434, 611, (3004, 0.85, -131), (3500, 1.44, 0), ("guard", A41)),
         (-1.266, 611, (3004, 0.85, -133), (3500, 1.41, 0), ("guard", A41)),
         (-1.119, 611, (3004, 0.85, -136), (3500, 1.32, 0), ("guard", A41)),
         (-0.903, 611, (3004, 0.85, -143), (3500, 1.24, 1), ("guard", A41)),
         (-0.722, 611, (3004, 0.90, -148), (3500, 1.18, 0), None),
         (-0.654, 611, (3004, 0.90, -149), (3500, 1.15, 0), None),
         (-0.620, 611, (3004, 0.90, -149), (3500, 1.15, 1), None),
         (-0.575, 611, (3004, 0.90, -149), (3500, 1.15, 1), None),
         (-0.502, 611, (3004, 0.90, 0), (3004, 1.15, 5), ("guard", A42))]


def main() -> None:
    clock = [0.0]
    saved = R.time
    R.time = NS(time=lambda: clock[0], sleep=lambda s: None)
    try:
        pad = NS(guard=lambda on: None, move=lambda x, y: None)
        mv = NS(pad=pad, face=lambda s, c, deg=0.0: None)
        r = R.Reflex(mv)
        acts = []
        real_act = r._act
        r._act = lambda act, c=None, s=None, start=None: (acts.append((act, getattr(c, "ptr", None))), real_act(act, c, s, start))[1]
        r._anim = {A41: 3009, A42: 3003}
        r._start = {A42: T0 - 2.842}

        for t, hp, f41, f42, want in TICKS:
            clock[0] = T0 + t
            if want == "update":
                r.update(snap(t, hp, f41, f42))
                check(f"{t:+.3f} update: 255041 3004 시작 기록 ({r._start.get(A41) - T0:+.3f})", abs(r._start[A41] - (T0 + t)) < 1e-9)
                continue
            r.prefer = A42                                        # duel sets it every tick (target 255042)
            acts.clear()
            s = snap(t, hp, f41, f42)
            ret = r.tick(s)
            got = acts[-1] if acts and acts[-1][0] is not None else None
            age41, age42 = r.attack_age(A41), r.attack_age(A42)
            th = sorted(c.ptr for c in r.threats(s))
            detail = (f"{t:+.3f} → {got}  threats {th}  age 255041 {age41 if age41 is None else round(age41, 3)}"
                      f" · 255042 {age42 if age42 is None else round(age42, 3)}")
            check(detail, got == want and ret == (want is not None))
            if t == -1.892:
                check(f"   기록 age 0.164 와 같음 ({age41:.3f})", abs(age41 - 0.164) < 1e-6)
                check(f"   잠금 = 255041, {R.THREAT_S} s 뒤 −0.756 까지", r._lock[0] == A41 and abs(r._lock[1] - (T0 - 0.756)) < 1e-9)
            if t == -0.722:
                check(f"   255041 0.90 m · 3004 인데 age {age41:.3f} > THREAT_S {R.THREAT_S} → 위협 아님",
                      age41 > R.THREAT_S and A41 not in th)
            if t == -0.502:
                check(f"   255042 age 0 (기록 0.001) · 위협은 255042 하나 {th}", abs(age42) < 1e-9 and th == [A42])
    finally:
        R.time = saved
    print("p89_reflex_scene_test: all ok")


if __name__ == "__main__":
    main()
