"""WorldState (ROADMAP `worldstate`, docs/review-v2-2026-10-11.md §2-④) — step 1.

What the bot knows about the world across the events that change it: a bonfire rest, a death and respawn, a bonfire
warp, a quit-out (byte or menu). Before this each feature handled them on its own (P-18 · P-25 · P-44 · P-55): a rest
dropped pointer memory and the loot list, a missions warp only the loot list, an Escape warp neither, a byte quit-out only
bumped `Escape.gen` and left "were the killed ones revived?" to `Missions.pass_ramp`.

Step 1: every such event goes through `WorldState.event(kind)`, which
  · counts it, keeps a short history and writes a `world` event to the run log,
  · knows from `EVENTS` whether killed foes come back and whether foe pointers change,
  · calls the listeners (Field: forget pointer memory, reset the loot list) — the same side effects as before, now the same
    for the same kind wherever it happens,
  · keeps the kills (npc, place, at which revive count) so `killed(npc, pos)` can say dead / alive again / unknown.
Readers (field.clear's identity binding, pass_ramp, passage_drill) still use their own checks; step 2 moves them here.

  revive  True = killed foes are back (rest, respawn, warp, byte quit-out — 2026-10-10 game check, P-25)
          False = killed foes stay dead (menu quit-out — the same check, 4/4)
          None = not known (run start: the save decides)
  ptrs    True = foe pointers change (a load screen) — `Escape.gen` is bumped by the quit-out / warp code itself
"""
from __future__ import annotations

import math
import time

EVENTS: dict[str, dict] = {
    "run_start": {"revive": None, "ptrs": True},
    "rest":      {"revive": True, "ptrs": False},   # foes respawn in place; a revived foe can keep its pointer (Field.forget_foes)
    "respawn":   {"revive": True, "ptrs": True},    # died → woke at the bonfire (a load)
    "warp":      {"revive": True, "ptrs": True},    # bonfire warp = a load
    "quit_byte": {"revive": True, "ptrs": True},    # ChrClassWarp+0x19: the area's killed foes come back (P-25, 10-10 3/3)
    "quit_menu": {"revive": False, "ptrs": True},   # Quit Game: killed foes stay dead (10-10 4/4)
}
KILL_R = 6.0          # a kill matches a foe of the same NpcParam within this of where it died (m) — about a spawn's wander
HISTORY = 50


class WorldState:
    def __init__(self, log=None, events=None):
        self.log = log or (lambda *a: None)
        self.events = events or (lambda *a, **k: None)
        self.n = 0                       # events so far
        self.revives = 0                 # events after which killed foes are back, or may be (revive True or None)
        self._rev_kinds: list = []       # revive value (True / None) of each of those, in order
        self.last: str | None = None
        self.history: list[tuple[float, str, str]] = []
        self.kills: list[dict] = []      # {"npc", "pos", "t", "rev"}: rev = self.revives when it died
        self._listeners: list = []

    def on(self, fn) -> None:
        """fn(kind, info) after every event — info = EVENTS[kind] plus the call's own fields."""
        self._listeners.append(fn)

    def event(self, kind: str, why: str = "", **info) -> dict:
        if kind not in EVENTS:
            raise ValueError(f"unknown world event {kind!r} (EVENTS: {sorted(EVENTS)})")
        spec = dict(EVENTS[kind])
        self.n += 1
        self.last = kind
        if spec["revive"] is not False:
            self.revives += 1
            self._rev_kinds.append(spec["revive"])
        self.history = (self.history + [(time.time(), kind, why)])[-HISTORY:]
        out = {"kind": kind, "why": why, **spec, "n": self.n, "revives": self.revives, **info}
        try:
            self.events("world", **out)
        except Exception:
            pass
        for fn in list(self._listeners):
            fn(kind, out)
        return out

    def kill(self, npc: int | None, pos: tuple | None) -> None:
        """A foe died (Field.fight 'killed')."""
        self.kills.append({"npc": npc, "pos": tuple(pos) if pos else None, "t": time.time(), "rev": self.revives})
        try:
            self.events("world_kill", npc=npc, pos=[round(v, 2) for v in pos] if pos else None, rev=self.revives,
                        kills=len(self.kills))
        except Exception:
            pass

    def killed(self, npc: int, pos: tuple, r: float = KILL_R) -> bool | None:
        """Is the foe of this NpcParam near pos dead now? True = killed since the last revive · False = never killed here, or
        killed before a revive (alive again) · None = killed before an event whose effect is not known (run start)."""
        hit = [k for k in self.kills if k["npc"] == npc and k["pos"] is not None and math.dist(k["pos"], pos) <= r]
        if not hit:
            return False
        later = self._rev_kinds[max(k["rev"] for k in hit):]     # revive-type events after the latest such kill
        if not later:
            return True
        return False if any(v is True for v in later) else None

    def since(self, n: int) -> list[str]:
        """Kinds of the events after the n-th (n = a reader's saved `self.n`)."""
        return [k for _t, k, _w in self.history[-(self.n - n):]] if self.n > n else []

    def revived_since(self, n: int) -> bool:
        """Did killed foes come back (or might have) since the n-th event?"""
        return any(EVENTS[k]["revive"] is not False for k in self.since(n))
