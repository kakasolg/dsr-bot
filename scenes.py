"""Exact-input fight scenes (docs/design-scene-expectations.md 3.3) — what duel() saw right before a decision, so the
decision can be replayed later without rebuilding a fake world from radar values (P-34: 85–94 % per feature).

  run.py --ctl-scenes  sets duel.SCENE_TAP = Tap(): every tick copies the rules' input (snapshot within 15 m, the Fight's
                       plain state, the reflex's swing age, Estus wish, duel flags) before RULES run; when the tick ends in an
                       attack / backstab / Estus / kick … (not a pose rule — duel.FOLD_RULES), or a pose rule while the
                       target staggers or winds up, the copy goes to the .ctl.jsonl as a "scene" record with the rule that acted.
  python scene_replay.py <run>.ctl.jsonl  replays them (scene_replay.py).

Record only: nothing here is read back by the fight, every hook swallows its own errors (like attack_audit / laya_shadow).
Timestamps are stored relative to the tick's `now` so a replay can shift them to its own clock.
"""
from __future__ import annotations

import time
from dataclasses import asdict

SCHEMA = "dsr-scene-input/0.2"   # 0.2: reflex.anim (a fake reflex without _anim leaves it out)
CHAR_R = 15.0                    # characters within this of us are kept (the rules look at most ~10 m)
ABS_T = 1e9                      # a float above this in the Fight's state is a wall-clock time → stored relative to now
SKIP_F = {"mv", "nm", "log", "cancel", "care", "reflex", "style", "weapon", "foe", "last_seen", "shadow", "no_obs",
          "res", "may_approach", "acts", "note_t"}


def _plain(v, now: float):
    """JSON-safe copy of a Fight attribute, or NotImplemented when it isn't plain data (objects are left out)."""
    if v is None or isinstance(v, (bool, int, str)):
        return v
    if isinstance(v, float):
        return {"_t": v - now} if v > ABS_T else v
    if isinstance(v, (list, tuple)):
        out = [_plain(x, now) for x in v]
        return NotImplemented if any(x is NotImplemented for x in out) else out
    if isinstance(v, set):
        out = [_plain(x, now) for x in v]
        return NotImplemented if any(x is NotImplemented for x in out) else {"_set": out}
    if isinstance(v, dict):
        out = [[_plain(k, now), _plain(x, now)] for k, x in v.items()]
        return NotImplemented if any(a is NotImplemented or b is NotImplemented for a, b in out) else {"_dict": out}
    return NotImplemented


def restore(v, now: float):
    """Inverse of _plain with a new `now`."""
    if isinstance(v, list):
        return [restore(x, now) for x in v]
    if isinstance(v, dict):
        if "_t" in v:
            return now + v["_t"]
        if "_set" in v:
            return {restore(x, now) for x in v["_set"]}
        if "_dict" in v:
            return {restore(k, now): restore(x, now) for k, x in v["_dict"]}
    return v


def capture(F, T) -> dict:
    """The rules' input this tick — call before RULES run (they change F)."""
    from souls import duel as D
    now = T.now
    s, p = T.s, T.p
    chars = [asdict(c) for c in s.chars if getattr(c, "dist", 0.0) <= CHAR_R]
    fight = {}
    for k, v in vars(F).items():
        if k in SKIP_F:
            continue
        pv = _plain(v, now)
        if pv is not NotImplemented:
            fight[k] = pv
    rf = F.reflex
    res = F.res
    care = F.care
    try:
        wants = bool(care.wants(s)) if care is not None else None
    except Exception:
        wants = None
    return {"schema": SCHEMA, "t_wall": now,
            "snap": {"t": s.t - now if s.t and s.t > ABS_T else s.t, "player": asdict(p), "chars": chars,
                     "cam_yaw": s.cam_yaw, "arm_style": getattr(s, "arm_style", None), "flask_hp": getattr(s, "flask_hp", None)},
            "tick": {"ptr": T.c.ptr, "h": T.h, "dy": T.dy, "a": T.a},
            "fight": fight,
            "res": {"dealt": res.dealt, "hits": list(res.hits), "npc": res.npc, "wall_back": res.wall_back},
            "weapon": {"id": getattr(F.weapon, "base_id", None), "name": getattr(F.weapon, "name", None)},
            "style": getattr(F.style, "name", None),
            "reflex": None if rf is None else {"age": rf.attack_age(F.ptr),
                                               "start": _plain(dict(getattr(rf, "_start", {}) or {}), now),
                                               "prefer": getattr(rf, "prefer", None),
                                               **({"anim": _plain(dict(rf._anim), now)} if hasattr(rf, "_anim") else {})},
            "care": None if care is None else {"wants": wants},
            "nm": getattr(F.nm, "map_id", None) if F.nm is not None else None,
            "ground": type(F.nm).__name__ == "Ground",       # run.py --ground: floor checks read NavMesh + walked cells
            "flags": {k: getattr(D, k) for k in ("BACKSTAB", "HEAVY", "BACKSTAB_ONLY")}}


class Tap:
    """duel.SCENE_TAP. sink(record) — default ctl.emit("scene", …). keep(rule, T, F) decides which decisions are kept."""

    def __init__(self, sink=None):
        if sink is None:
            import ctl
            sink = lambda rec: ctl.emit("scene", **rec)
        self.sink = sink
        self.pre = None
        self.last = {}                   # fight id → (rule, ptr, anim) last kept for a pose rule — one per change, not per tick
        self.kept = self.errors = 0
        self.cost_ns = 0

    def tick(self, F, T) -> None:
        t0 = time.perf_counter_ns()
        try:
            self.pre = capture(F, T)
        except Exception:
            self.pre = None
            self.errors += 1
        self.cost_ns += time.perf_counter_ns() - t0

    def decided(self, F, T, rule: str, out) -> None:
        try:
            if self.pre is None or not self.keep(rule, T, F):
                return
            from souls import duel as D
            rec = dict(self.pre, rule=rule, out="result" if isinstance(out, D.DuelResult) else str(out))
            self.pre = None
            self.kept += 1
            self.sink(rec)
        except Exception:
            self.errors += 1

    def keep(self, rule: str, T, F) -> bool:
        from souls import duel as D
        from souls import moves as M
        if rule not in D.FOLD_RULES:
            return True                  # attacks, backstab, Estus, kicks, after_swing, finish …
        foe = getattr(F, "foe", None)
        if T.a in M.STAGGER or (foe is not None and T.a in getattr(foe, "windup", ())):
            key = (rule, T.c.ptr, T.a)
            if self.last.get(id(F)) != key:
                self.last[id(F)] = key
                return True
        return False

    def summary(self) -> str:
        return f"scenes kept {self.kept}, errors {self.errors}, capture {self.cost_ns / 1e6:.0f} ms total"
