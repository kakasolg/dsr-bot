"""duel() decision snapshot — runs thousands of one/two-tick situations and compares every decision with
tests/duel_golden.json, so duel() can be restructured without changing what it does (ROADMAP 0-c). No game.

  python tests/duel_golden_test.py            compare
  python tests/duel_golden_test.py --record   rewrite the snapshot (only when a behavior change is intended)

A situation = foe type × its anim × distance × our SP × its HP × facing × room behind × other foe swinging × wait_far ×
style × reflex. The trace = every Moves call, every helper the duel hands work to (approach, backstab, separate …),
every log line and the result.
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import gzip
import itertools
import json
import re
import math
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from field_fakes import World
from souls import duel as D
from souls import moves as M
from souls import weapons

GOLDEN = Path(__file__).with_name("duel_golden.json.gz")
_CLOCK = re.compile(r"\d{9,}\.\d+")     # wall-clock stamps in shadow-kick keys
FOES = {"hollow": 254000, "shield": 255010, "firebomb": 254001}
ANIMS = [-1, 3003, 3004, 3500, 9910, 9600]
DISTS = [0.9, 1.4, 2.2, 4.0, 7.0]


class Mv:
    def __init__(self, w, trace):
        self.w, self.t = w, trace
        self.tm = type("Tm", (), {"handle": staticmethod(lambda p: p + 0x1000)})()
        self.pad = type("Pad", (), {"move": lambda _s, x, y: trace.append(("move", round(x, 2), round(y, 2))),
                                    "guard": lambda _s, on: trace.append(("pad_guard", on))})()
        self.cam_busy = False

    def snap(self, within=40.0):
        return self.w.snapshot(within)

    @staticmethod
    def find(s, ptr):
        return next((x for x in s.chars if x.ptr == ptr), None) if s else None

    def _hit(self, kind, c, n):
        self.t.append((kind, c.ptr, n))
        return M.Hit(kind, presses=n, dmg=10)

    def light(self, s, c, n=2, sp_second=None):
        return self._hit("light", c, n)

    def heavy(self, s, c):
        return self._hit("heavy", c, 1)

    def kick_combo(self, s, c, n=2):
        return self._hit("kick", c, n)

    def face(self, s, c, deg=20.0):
        self.t.append(("face", c.ptr, deg))
        return True

    def guard(self, on):
        self.t.append(("guard", on))

    def backstep(self):
        self.t.append(("backstep",))

    def stick_to(self, s, x, z, scale=1.0):
        return (0.0, scale)

    def walk_path(self, *a, **k):
        self.t.append(("walk_path",))
        return "arrived"


class Reflex:
    def __init__(self, fires, trace):
        self.fires, self.t, self.prefer, self.last_hit = fires, trace, None, None

    def update(self, s):
        pass

    def attack_age(self, ptr):
        return 0.3

    def tick(self, s):
        if self.fires:
            self.t.append(("reflex",))
        return self.fires


def situations():
    keys = ("foe", "anim", "h", "sp", "low", "back", "room", "other", "wait", "style", "reflex")
    for v in itertools.product(FOES, ANIMS, DISTS, (90, 10), (False, True), (False, True), (False, True),
                               (False, True), (False, True), ("guard", "backstep"), (False, True)):
        yield dict(zip(keys, v))


class Nm:
    """Just enough navmesh for the arena / cliff / split rules; footing and ground are set per situation."""
    def find_path(self, a, b):
        return [a, b]


class Care:
    def __init__(self, trace):
        self.t = trace

    def wants(self, s):
        return True

    def take(self, recheck):
        self.t.append(("estus",))
        return "drank"


def situations_terrain():
    """Second set: navmesh, arena, cliff edge, Estus wanted, a second foe standing close (split)."""
    keys = ("foe", "anim", "h", "edge", "arena", "care", "pair", "ground")
    for v in itertools.product(FOES, ANIMS, (0.9, 2.2, 5.0), (False, True), (None, "near", "far", "ledge"), (False, True),
                               (False, True), (False, True)):
        yield dict(zip(keys, v), sp=90, low=False, back=False, room=False, other=False, wait=False, style="guard", reflex=False)


def run(sc) -> list:
    trace = []
    w = World(player=(0.0, -49.4, 0.0), sp=sc["sp"])
    w.player.heading = -math.pi                                   # facing +z (facing = heading + π)
    c = w.add(2, 0x1002, FOES[sc["foe"]], (0.0, -49.4, sc["h"]), hp=5 if sc["low"] else 85, max_hp=85, anim=sc["anim"])
    c.heading = math.pi if sc["back"] else 0.0                    # back: facing +z, away from us
    if sc["other"]:
        o = w.add(3, 0x1003, 254000, (1.3, -49.4, 0.3), hp=75, anim=3003)
        o.heading = -math.pi / 2
    if sc.get("pair"):
        w.add(4, 0x1004, 254000, (0.8, -49.4, sc["h"] + 0.5), hp=75, anim=2000)   # awake, moving, close to the target
    nm = care = arena = None
    if "edge" in sc:
        nm, w.player.gx = Nm(), 0.0
        care = Care(trace) if sc["care"] else None
        arena = {None: None, "near": [0.5, -49.4, 0.5], "far": [0.0, -49.4, -8.0], "ledge": [0.0, -45.0, -8.0]}[sc["arena"]]
    mv = Mv(w, trace)
    ticks = {"n": 0}

    def cancel():
        ticks["n"] += 1
        return ticks["n"] > 2

    rec = lambda name, ret: (lambda *a, **k: (trace.append((name,)), ret)[1])
    saved = {k: getattr(D, k) for k in ("_backstab", "_back_to_safe", "_separate", "_approach", "_room_behind")}
    nav_saved = (D.nav.footing, D.nav.ground_ahead)
    D.nav.footing = lambda nm_, p, r=1.0: (0.2 if sc.get("edge") else 3.0,)
    D.nav.ground_ahead = lambda *a, **k: bool(sc.get("ground", True))
    sleep = D.time.sleep
    D._backstab, D._back_to_safe = rec("backstab", "not_behind"), rec("back_to_safe", None)
    D._separate, D._approach = rec("separate", "no_spot"), rec("approach", "stopped")
    D._room_behind = lambda nm, p, c_, r=1.0: sc["room"]
    D.time.sleep = lambda s: None
    try:
        r = D.duel(mv, weapons.BROADSWORD, 2, nm, log=lambda line: trace.append(("log", _CLOCK.sub("T", line))), cancel=cancel,
                   reflex=Reflex(sc["reflex"], trace), style=sc["style"], wait_far=sc["wait"], care=care, arena=arena)
        trace.append(("result", r.result))
    except Exception as e:                                        # a crash is a decision too — it must stay the same
        trace.append(("error", type(e).__name__, str(e)))
    finally:
        for k, v in saved.items():
            setattr(D, k, v)
        D.time.sleep = sleep
        D.nav.footing, D.nav.ground_ahead = nav_saved
    return [list(x) for x in trace]


def main() -> None:
    got = {json.dumps(sc, sort_keys=True): run(sc) for sc in itertools.chain(situations(), situations_terrain())}
    if "--record" in sys.argv:
        GOLDEN.write_bytes(gzip.compress(json.dumps(got, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), mtime=0))
        print(f"recorded {len(got)} situations → {GOLDEN.name}")
        return
    want = json.loads(gzip.decompress(GOLDEN.read_bytes()).decode("utf-8"))
    bad = [k for k in want if got.get(k) != want[k]]
    for k in bad[:5]:
        print("DIFF", k, "\n  want", want[k][:12], "\n  got ", got.get(k, [])[:12])
    kinds = {}
    for t in want.values():
        first = next((x[0] for x in t if x[0] not in ("log", "face", "move", "pad_guard")), "?")
        kinds[first] = kinds.get(first, 0) + 1
    print(f"{len(want)} situations, first decisions: " + ", ".join(f"{k}×{v}" for k, v in sorted(kinds.items(), key=lambda kv: -kv[1])))
    if bad:
        print(f"FAIL {len(bad)} situations differ")
        sys.exit(1)
    print("ok  every decision same as the snapshot")


if __name__ == "__main__":
    main()
