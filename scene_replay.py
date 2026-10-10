"""Replay exact-input fight scenes (scenes.py, run.py --ctl-scenes) through today's RULES — no fake world rebuilt from
radar values, the bot's own input as it was (docs/design-scene-expectations.md 3.3). No game.

  python scene_replay.py data/runs/<run>.ctl.jsonl [more …]     same rule as the bot picked then? (first check: 100 %)
  python scene_replay.py <file> --list                         every scene: rule then → rule now

replay(rec) → the rule that acts now. The Moves calls are faked (nothing moves), helpers that run their own loops
(backstab, approach, separate, back-to-safe) only report that they were called, time.sleep is skipped. The reflex fires
exactly when it fired then (rule "reflex") — what it does inside isn't replayed. NavMesh: the map's npz from
data/samples/ when the scene names one (navmesh_<map>.npz), else none; wrapped in ground.Ground when the run used --ground.
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import scenes
import telemetry
from souls import duel as D
from souls import foes as foes_
from souls import moves as M
from souls import style as style_
from souls import weapons

ROOT = Path(__file__).resolve().parent
_NM: dict = {}


class Mv:
    """Moves with nothing behind it: snap() returns the scene's snapshot, attacks return a plain Hit, the rest records."""
    def __init__(self, snap):
        self.s, self.calls, self.cam_busy, self.cam_target = snap, [], False, None
        self.tm = type("Tm", (), {"handle": staticmethod(lambda p: p + 0x1000), "grip": staticmethod(lambda: None),
                                  "selected_item": staticmethod(lambda: None)})()
        rec = lambda name: (lambda *a, **k: self.calls.append(name))
        self.pad = type("Pad", (), {"move": lambda _s, x, y: self.calls.append("move"),
                                    "guard": lambda _s, on: self.calls.append("pad_guard"),
                                    "__getattr__": lambda _s, n: rec(f"pad.{n}")})()

    def snap(self, within=40.0):
        return self.s

    @staticmethod
    def find(s, ptr):
        return next((x for x in s.chars if x.ptr == ptr), None) if s else None

    def _hit(self, kind, n=1):
        self.calls.append(kind)
        return M.Hit(kind, presses=n, dmg=0)

    def light(self, s, c, n=2, sp_second=None):
        return self._hit("light", n)

    def heavy(self, s, c):
        return self._hit("heavy")

    def kick_combo(self, s, c, n=2):
        return self._hit("kick", n)

    def face(self, s, c, deg=20.0):
        """Same answer as Moves.face for this snapshot: off by more than deg (or no heading / camera) → False.
        2026-10-09 run: always-True turned a 42.5° after_swing scene into finish_first (deg 30)."""
        self.calls.append("face")
        p = s.player
        return p.heading is not None and s.cam_yaw is not None and abs(math.degrees(M.rel_angle(p, c))) <= deg

    def stick_to(self, s, x, z, scale=1.0):
        return (0.0, scale)

    def walk_path(self, *a, **k):
        self.calls.append("walk_path")
        return "arrived"

    def __getattr__(self, name):
        return lambda *a, **k: self.calls.append(name)


class Reflex:
    def __init__(self, rec: dict, fired: bool, now: float):
        r = rec or {}
        self.age, self.fired, self.prefer, self.last_hit = r.get("age"), fired, r.get("prefer"), None
        self._start = scenes.restore(r.get("start") or {"_dict": []}, now)

    def update(self, s):
        pass

    def attack_age(self, ptr):
        return self.age

    def tick(self, s):
        return self.fired


class Care:
    def __init__(self, wants):
        self._w = wants

    def wants(self, s):
        return bool(self._w)

    def take(self, recheck):
        return {"ok": False, "why": "replay"}


def _weapon(rec: dict):
    wid = (rec or {}).get("id")
    for v in vars(weapons).values():
        if isinstance(v, weapons.Weapon) and v.base_id == wid:
            return v
    return weapons.of(wid)


def _navmesh(map_id):
    if map_id is None:
        return None
    if map_id not in _NM:
        p = ROOT / "data" / "samples" / f"navmesh_{map_id}.npz"
        try:
            import navmesh
            _NM[map_id] = navmesh.Navmesh.from_npz(p) if p.exists() else None
        except Exception:
            _NM[map_id] = None
    return _NM[map_id]


def _chr(d: dict):
    return telemetry.Chr(**{k: v for k, v in d.items() if k in telemetry.Chr.__dataclass_fields__})


def replay(rec: dict) -> str | None:
    """→ the name of the rule that acts on this input now (None: none did)."""
    now = time.time()
    sn = rec["snap"]
    t = sn.get("t")
    s = telemetry.Snapshot(t=(now + t) if isinstance(t, (int, float)) and abs(t) < 1e6 and t <= 0 else (t or now),
                           player=_chr(sn["player"]), chars=[_chr(c) for c in sn["chars"]], cam_yaw=sn.get("cam_yaw"),
                           arm_style=sn.get("arm_style"), flask_hp=sn.get("flask_hp"))
    mv = Mv(s)
    F = D.Fight.__new__(D.Fight)
    for k, v in rec["fight"].items():
        setattr(F, k, scenes.restore(v, now))
    nm = _navmesh(rec.get("nm"))
    if nm is not None and rec.get("ground"):               # the run used --ground: the same floor map
        import ground
        nm = ground.for_map(nm)
    F.mv, F.nm, F.log, F.cancel = mv, nm, (lambda *a: None), (lambda: False)
    F.weapon, F.style = _weapon(rec.get("weapon")), style_.of(rec.get("style") or "guard")
    F.reflex = Reflex(rec.get("reflex"), rec.get("rule") == "reflex", now) if rec.get("reflex") is not None else None
    F.care = Care(rec["care"]["wants"]) if rec.get("care") is not None else None
    F.may_approach, F.acts, F.note_t = None, {}, now
    r = rec.get("res") or {}
    F.res = D.DuelResult("timeout", npc=r.get("npc"), dealt=r.get("dealt", 0), hits=list(r.get("hits", [])),
                         wall_back=r.get("wall_back", False))
    F.shadow = D.ShadowKick(log=lambda *a: None)
    F.no_obs = D.control.NoObs(mv.pad)
    tk = rec["tick"]
    c = mv.find(s, tk["ptr"])
    if c is None:
        return "error:no_target"
    F.last_seen, F.foe = c, foes_.of(c.npc_param)
    T = D.Tick(s=s, p=s.player, c=c, h=tk["h"], dy=tk["dy"], a=tk["a"], now=now)
    rec_ = lambda ret: (lambda *a, **k: ret)
    saved = {k: getattr(D, k) for k in ("_backstab", "_back_to_safe", "_separate", "_approach")}
    flags = {k: getattr(D, k) for k in rec.get("flags", {})}
    sleep = D.time.sleep
    D._backstab, D._back_to_safe, D._separate, D._approach = rec_("not_behind"), rec_(None), rec_("no_spot"), rec_("stopped")
    D.time.sleep = lambda x: None
    for k, v in rec.get("flags", {}).items():
        setattr(D, k, v)
    try:
        for rule in D.RULES:
            if rule(F, T) is not None:
                return rule.__name__.removeprefix("rule_").removeprefix("prep_")
        return None
    except Exception as e:
        return f"error:{type(e).__name__}"
    finally:
        for k, v in saved.items():
            setattr(D, k, v)
        for k, v in flags.items():
            setattr(D, k, v)
        D.time.sleep = sleep


def load(paths) -> list[dict]:
    out = []
    for p in paths:
        for line in open(p, encoding="utf-8", errors="replace"):
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("k") == "scene" or d.get("schema") == scenes.SCHEMA:
                out.append(d.get("f", d) if isinstance(d.get("f"), dict) else d)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("files", nargs="+")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    recs = load(a.files)
    if not recs:
        print("no scene records (run with --ctl-scenes)")
        return
    same, pairs = 0, collections.Counter()
    for r in recs:
        now = replay(r)
        same += now == r.get("rule")
        pairs[(r.get("rule"), now)] += 1
        if a.list:
            print(f"  {r.get('rule'):18} → {now}")
    print(f"{len(recs)} scenes: same rule now as then {same} ({same / len(recs):.0%})")
    for (then, now), n in pairs.most_common():
        if then != now:
            print(f"  {n:4} × then {then} → now {now}")


if __name__ == "__main__":
    main()
