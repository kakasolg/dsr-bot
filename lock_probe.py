"""Lock-on probe at a throw spot (MoKa 11-15 "락온 시험부터", P-179).

    python lock_probe.py [--at x,y,z] [--r 16] [--switch]

Stands at the spot (default: burg-upper zone 4 safe spot, where the 194303 knife locked a neighbour and both firebomb tries
locked nothing) and, for every live foe within r, without walking closer:
  1. camera onto it (yaw within 2°), R3 → which foe the lock landed on (target · other <npc> · none);
  2. with --switch and a neighbour locked: right-stick flicks toward the target side (DSR switches lock targets that way),
     up to 4, logging where the lock went after each.
Unlocks between foes. Records to data/runs/<time>_altar-andre-route.lockprobe.jsonl. Reads and presses R3 / right stick only:
no throws, no memory writes. Foes asleep before/after are logged (lock-on should not wake them — checked here, not assumed).
"""
from __future__ import annotations

import json
import math
import sys
import time

import andre_route

ZONE4_SAFE = (11.2, -6.6, -92.8)


def bearing(p, c) -> float:
    return math.degrees(math.atan2(c.x - p.x, c.z - p.z))


class Probe(andre_route.Route):
    def __init__(self, at, r: float, switch: bool):
        super().__init__()
        self.at, self.r, self.switch = at, r, switch
        self.out = open(str(self.log.path).replace(".jsonl", ".lockprobe.jsonl"), "a", encoding="utf-8")

    def rec(self, kind, **kw):
        d = {"t": round(time.time(), 2), "kind": kind, **kw}
        self.out.write(json.dumps(d, ensure_ascii=False) + "\n"); self.out.flush()
        self.say(f"  {kind} {kw}")

    def who(self, s, h):
        if h in (None, -1):
            return None
        for c in s.chars:
            if self.tm.handle(c.ptr) == h:
                return c.npc_param
        return "?"

    def go(self):
        mv, tm = self.mv, self.tm
        s = mv.snap(30.0)
        d0 = math.dist((s.player.x, s.player.y, s.player.z), self.at)
        if d0 > 1.0:
            r = self.walk([self.at], f"락온 시험 자리 {self.at}", ignore={c.npc_param for c in s.chars})
            self.rec("walk", at=self.at, r=r, was=round(d0, 1))
        mv.unlock()
        s = mv.snap(30.0)
        p = s.player
        foes = sorted([c for c in s.hostile(self.r) if c.hp > 0 and c.npc_param != 100000], key=lambda c: c.dist)
        self.rec("start", me=[round(p.x, 2), round(p.y, 2), round(p.z, 2)], hp=p.hp,
                 foes=[(c.npc_param, round(c.dist, 1), round(bearing(p, c), 1), round(c.y - p.y, 1), c.anim) for c in foes])
        for c in foes:
            mv.unlock()
            err = mv.look_at(c.ptr, tol=2.0, timeout=2.5)
            s = mv.snap(30.0)
            k = mv.find(s, c.ptr)
            if k is None:
                continue
            mv._r3(0.4)
            st = mv.lock_state(c.ptr)
            got = self.who(mv.snap(30.0), tm.lock_target())
            row = {"npc": c.npc_param, "d": round(k.dist, 1), "bear": round(bearing(s.player, k), 1),
                   "dy": round(k.y - s.player.y, 1), "cam_err": None if err is None else round(err, 1), "lock": st, "got": got}
            if st == "other" and self.switch:
                tries = []
                for n in range(4):
                    s2 = mv.snap(30.0)
                    k2 = mv.find(s2, c.ptr)
                    g = next((x for x in s2.chars if self.tm.handle(x.ptr) == tm.lock_target()), None)
                    if k2 is None or g is None:
                        break
                    side = 1.0 if (bearing(s2.player, k2) - bearing(s2.player, g) + 540) % 360 - 180 > 0 else -1.0
                    self.pad.look(0.8 * side * (mv.LOOK_SIGN or 1), 0.0)
                    time.sleep(0.12)
                    self.pad.look(0.0, 0.0)
                    time.sleep(0.35)
                    st2 = mv.lock_state(c.ptr)
                    tries.append({"side": side, "lock": st2, "got": self.who(mv.snap(30.0), tm.lock_target())})
                    if st2 == "target":
                        break
                row["switch"] = tries
            self.rec("lock", **row)
            mv.unlock()
            time.sleep(0.4)
        s = mv.snap(30.0)
        self.rec("end", hp=s.player.hp,
                 foes=[(c.npc_param, round(c.dist, 1), c.anim) for c in s.hostile(self.r) if c.hp > 0])
        self.pad.close()


if __name__ == "__main__":
    a = sys.argv[1:]
    at = tuple(float(v) for v in a[a.index("--at") + 1].split(",")) if "--at" in a else ZONE4_SAFE
    r = float(a[a.index("--r") + 1]) if "--r" in a else 16.0
    Probe(at, r, "--switch" in a).go()
