"""Turn-and-dodge record — where we stand when the foe's hit window opens (MoKa 11-16 "돌아서 피하기 시험", M1116-03;
[cloud] board c118a5b9 item 4 design: success = at the hit start we are ≥ 30° (better ≥ 60°) off the foe's facing, circling at
about 1 m; flag-7 stretches of 3000 / 3003 are where the angle is won).

duel._backstab (the circle round a swinging hollow) feeds every tick it already reads; nothing here presses anything.
For each (foe, attack anim, hit window) it records once, at the first tick at or after the window start:
  off = how far we are off the foe's facing (deg, |rel_angle(foe, me)|), d = distance (m), at = foe anim time,
and HIT_S later lost = HP we lost since then → one "turn_dodge" event.
Hit windows come from the game files (souls/parry.load_windows / windows_for, section table there).
"""
from __future__ import annotations

import math
import time

from . import parry as PARRY

HIT_S = 0.4          # HP drop within this after the window start counts as hit by it (tick ~0.05 s, hit lands in the window)


class TurnWatch:
    def __init__(self, events=None, log=None, label: str = ""):
        self.events = events or (lambda *_a, **_k: None)
        self.log = log
        self.label = label
        self.seen: set = set()
        self.pending: list = []        # (t, row)

    def tick(self, tm, s, c, now: float | None = None) -> None:
        now = time.time() if now is None else now
        p = s.player if s is not None else None
        if p is not None and p.hp is not None:
            self._flush(p.hp, now)
        if c is None or p is None or c.anim is None or not 3000 <= c.anim < 4000:
            return
        wins = PARRY.windows_for(PARRY.load_windows(), c.npc_param, c.anim)
        at = getattr(tm, "anim_time", lambda _p: None)(c.ptr)
        if not wins or at is None:
            return
        for i, (w0, _w1) in enumerate(wins):
            key = (c.ptr, c.anim, i)
            if key in self.seen or at < w0:
                continue
            self.seen.add(key)
            off = abs(math.degrees(rel(c, p)))
            d = math.hypot(c.x - p.x, c.z - p.z)
            self.pending.append((now, {"npc": c.npc_param, "anim": c.anim, "win": i, "w0": w0, "at": round(at, 3),
                                       "off": round(off), "d": round(d, 2), "hp": p.hp, "how": self.label}))

    def _flush(self, hp_now, now) -> None:
        keep = []
        for t, row in self.pending:
            if now - t >= HIT_S:
                self._emit(row, hp_now)
            else:
                keep.append((t, row))
        self.pending = keep

    def close(self, hp_now) -> None:
        for _t, row in self.pending:
            self._emit(row, hp_now)
        self.pending = []

    def _emit(self, row, hp_now) -> None:
        row = {**row, "lost": max(0, row["hp"] - (hp_now if hp_now is not None else row["hp"]))}
        self.events("turn_dodge", **row)
        if self.log is not None:
            self.log(f"      돌아 피하기: {row['npc']} {row['anim']} 판정 시작 때 정면에서 {row['off']}° · {row['d']} m "
                     f"→ {'맞음 −' + str(row['lost']) if row['lost'] else '안 맞음'}")


def rel(c, p) -> float:
    """How far p is off c's facing (rad, −π..π) — same rule as moves.rel_angle (world yaw = heading + π)."""
    if c.heading is None:
        return 0.0
    fwd = c.heading + math.pi
    return (math.atan2(p.x - c.x, p.z - c.z) - fwd + math.pi) % (2 * math.pi) - math.pi
