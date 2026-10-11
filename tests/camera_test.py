"""P-65 ([MoKa] 10-11 "카메라가 다시 잘 따라 오지 못함", alignment is high priority): what the camera looks at is decided in one
place (souls/camera.CamFollow.target, one order), duel keeps mv.cam_target = its current target, and the right-stick direction is
learned from a +/− pulse pair and forgotten when pulses keep turning the camera the wrong way (20261011_060748 learned it backwards
from one pulse and turned away the whole run)."""
from __future__ import annotations

import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(1, str(_pl.Path(__file__).resolve().parent))

import math
import time
from types import SimpleNamespace as NS

from souls import camera
from souls import moves as M


def check(what: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + what)
    if not ok:
        raise SystemExit(1)


def foe(ptr, dist, anim=-1, hp=75):
    return NS(ptr=ptr, x=0.0, z=dist, dist=dist, anim=anim, hp=hp, npc_param=254000)


def snap(chars):
    return NS(chars=chars, hostile=lambda r: [c for c in chars if c.dist <= r])


def cam(cam_target=None):
    mv = NS(cam_target=cam_target, find=lambda s, p: next((c for c in s.chars if c.ptr == p), None), LOOK_SIGN=1)
    return camera.CamFollow(mv, log=lambda *a: None)


class Cam:
    """cam_yaw that turns true_sign·RATE rad/s per unit of right stick x, plus a steady drift (rad/s)."""
    RATE = 0.6

    def __init__(self, true_sign, drift=0.0):
        self.sign, self.drift, self.x, self.yaw, self.t = true_sign, drift, 0.0, 0.0, time.monotonic()

    def _go(self):
        now = time.monotonic()
        self.yaw += (self.drift + self.sign * self.RATE * self.x) * (now - self.t)
        self.t = now

    def look(self, x, y):
        self._go()
        self.x = x

    def snap(self, within=5.0):
        self._go()
        return NS(cam_yaw=self.yaw)


def mover(c):
    m = M.Moves.__new__(M.Moves)
    m.pad, m.snap = NS(look=c.look), c.snap
    return m


def main() -> None:
    # ── what to look at ──
    t = cam(cam_target=7)
    s = snap([foe(7, 3.0), foe(8, 1.0, anim=3003)])
    check("1. the fight target first, even with another swinging closer", t.target(s).ptr == 7)
    t = cam()
    s = snap([foe(5, 18.4, anim=3008), foe(6, 6.0, anim=-1)])
    check("2. no fight: a thrower throwing 18.4 m off (beyond the old 12 m, P-65 'shot') is looked at", t.target(s).ptr == 5)
    t = cam(cam_target=9)
    t.target(snap([foe(9, 2.0, anim=3500)]))               # fought 9, then the fight ended (low_hp / shot / pull)
    t.mv.cam_target = None
    check("3. the last fight target, idle 6 m away while we back off, stays in view", t.target(snap([foe(9, 6.0)])).ptr == 9)
    check("   … not once it is back asleep (9000s)", t.target(snap([foe(9, 6.0, anim=9001)])) is None)
    check("   … not once dead", t.target(snap([foe(9, 6.0, hp=0)])) is None)
    t.last_t -= camera.STICKY_S + 0.1
    check(f"   … not after STICKY_S ({camera.STICKY_S:.0f} s)", t.target(snap([foe(9, 6.0)])) is None)
    check("4. else the nearest moving foe within AUTO_R", cam().target(snap([foe(1, 9.0, anim=7000), foe(2, 13.0, anim=7000)])).ptr == 1)

    # ── alignment is measured outside fights too ──
    t = cam()
    t.mv.cam_busy, t.esc = False, None
    t.mv.tm = NS(lock_target=lambda: None)
    t.mv.snap = lambda r=40.0: snap([foe(5, 18.4, anim=3008)])
    t.mv.cam_err = lambda s_, x, z: 4.0
    t.step()
    check(f"stats(): outside-fight following counted ({t.stats()})", len(t.errs_out) == 1 and "싸움 밖" in t.stats())

    # ── right-stick direction ──
    keep = M.Moves.LOOK_SIGN
    try:
        c = Cam(true_sign=-1, drift=0.6)                    # the camera drifts + while we learn, stick +x really turns it −
        M.Moves.LOOK_SIGN = None
        d1 = mover(c)._yaw_step(0.6, 0.08)
        check(f"one +x pulse alone would read the drift ({d1:+.3f} rad → '+', the 060748 mistake)", d1 > 0)
        M.Moves.LOOK_SIGN = None
        mover(c).look_pulse(20.0)
        check(f"a +/− pulse pair cancels the drift → learned {M.Moves.LOOK_SIGN} (true −1)", M.Moves.LOOK_SIGN == -1)

        c = Cam(true_sign=-1)
        M.Moves.LOOK_SIGN, M.Moves._look_wrong = 1, 0       # learned backwards
        m = mover(c)
        for _ in range(M.Moves.LOOK_WRONG):
            m.look_pulse(20.0)
        check(f"{M.Moves.LOOK_WRONG} pulses in a row turning the wrong way → forgotten, relearned next pulse", M.Moves.LOOK_SIGN is None)
        m.look_pulse(20.0)
        check(f"… relearned → {M.Moves.LOOK_SIGN}", M.Moves.LOOK_SIGN == -1)
        c = Cam(true_sign=-1)
        M.Moves.LOOK_SIGN, M.Moves._look_wrong = -1, 0
        m = mover(c)
        y0 = c.snap().cam_yaw
        for _ in range(4):
            m.look_pulse(20.0)
        check(f"right sign: kept, and the camera turned toward the target ({c.snap().cam_yaw - y0:+.2f} rad)",
              M.Moves.LOOK_SIGN == -1 and M.Moves._look_wrong == 0 and c.snap().cam_yaw > y0)
    finally:
        M.Moves.LOOK_SIGN, M.Moves._look_wrong = keep, 0

    # ── duel keeps cam_target = its current target ──
    import duel_golden_test as G
    seen = {}

    def hook(mv, w):
        w.add(5, 0x1005, 254002, (0.0, -49.4, 5.9), anim=3008)
        seen["mv"] = mv
    G.run(dict(foe="hollow", anim=-1, h=7.0, sp=90, low=False, back=False, room=False, other=False, wait=False,
               style="guard", reflex=False), mv_hook=hook)
    check(f"duel: after a 'ranged first' switch the camera target is the new one (cam_target {getattr(seen['mv'], 'cam_target', None)})",
          getattr(seen["mv"], "cam_target", None) == 5)
    print("camera_test: 전부 통과")


if __name__ == "__main__":
    main()
