"""After a death: recover the stain or not, and falls without quit-out ([MoKa] 2026-10-12). No game.

  python tests/afterdeath_test.py

  "낙사시 퀵 종료 포기하고, 최대한 도망치던가 반격 하던가 하는 것으로 정책을 바꾸자. 그리고 죽으면 잃어버린 소울과 인간성을
   평가해서 많으면 회수 하고, 너무 적으면 무시하자. 아니면 연속으로 동일 지역에서 죽어도 사실 큰 문제는 캐릭터 레벨과 무기 강화
   수치가 낮은 거라 재시도가 의미가 없음."
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import sys
import types

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from souls import afterdeath as A
from souls import watch


def check(name: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        raise SystemExit(1)


class Game:
    """Zones as a script: deaths = {(life, zone)}; the stain record changes ('t') after each respawn."""

    def __init__(self, deaths: dict, stains: list, pick_at=None):
        self.deaths, self.stains, self.pick_at = deaths, list(stains), pick_at or {}
        self.life, self.dead, self.stain, self.played, self.events, self.picks = 0, False, None, [], [], []

    def play(self, n):
        self.played.append((self.life, n))
        if (self.life, n) in self.deaths:
            self.dead = True
            return "died"
        return "cleared"

    def alive(self):
        return not self.dead

    def respawn(self):
        self.dead = False
        self.life += 1
        if self.stains:
            s = self.stains.pop(0)
            self.stain = None if s is None else {**s, "t": f"life{self.life}"}

    def pick(self):
        r = self.pick_at.get((self.life, self.played[-1][1]))
        self.picks.append((self.life, self.played[-1][1], r))
        return r

    def run(self, first=1, last=8, **kw):
        return A.run_zones(first, last, self.play, alive=self.alive, respawn=self.respawn, read_stain=lambda: self.stain,
                           pick=self.pick, log=lambda *a: None, event=lambda ev, **k: self.events.append((ev, k)),
                           sleep=lambda s: None, **kw)


def main() -> None:
    rich = {"souls": 3114, "humanity": 1, "pos": [-11.07, -14.65, -65.3]}
    poor = {"souls": 512, "humanity": 0, "pos": [-22.25, -51.9, 12.86]}

    # plan(): value, same zone, trip cap
    check("rich stain → recover", A.plan(rich, 5, None, 0)[0] == "recover")
    check("poor stain → ignore", A.plan(poor, 5, None, 0)[0] == "ignore")
    check("2 humanity alone is worth it", A.plan({"souls": 0, "humanity": 2}, 5, None, 0)[0] == "recover")
    check("same zone twice → stop, however rich", A.plan(rich, 5, 5, 1)[0] == "stop")
    check("no stain record → ignore", A.plan(None, 3, None, 0)[0] == "ignore")
    check(f"trip cap {A.MAX_TRIPS} → stop", A.plan(rich, 3, 5, A.MAX_TRIPS)[0] == "stop")

    # recover: die in zone 5 → from zone 1 again, pick after zone 5, go on to 8
    g = Game({(0, 5): 1}, [rich], pick_at={(1, 5): "got"})
    r = g.run()
    check("rich death in zone 5 → second life replays 1..8", r == "cleared" and [n for l, n in g.played if l == 1] == list(range(1, 9)))
    check("picked after zone 5, no picks before (too far → None)",
          [p for p in g.picks if p[2] is not None] == [(1, 5, "got")] and ("blood_pick", {"zone": 5, "result": "got", "souls": 3114, "humanity": 1}) in g.events)
    check("no picks after it was got", all(p[1] <= 5 for p in g.picks))

    # ignore: poor stain → the run ends where it died
    g = Game({(0, 3): 1}, [poor])
    check("poor death in zone 3 → run ends, no second life", g.run() == "died" and max(l for l, _ in g.played) == 0)
    check("after_death event says ignore", any(ev == "after_death" and k["action"] == "ignore" for ev, k in g.events))

    # stop: died in zone 5, went back, died in zone 5 again → stop, the stain is lost
    g = Game({(0, 5): 1, (1, 5): 1}, [rich, rich])
    check("same zone twice → stop after the second death", g.run() == "died" and g.life == 2
          and [k["action"] for ev, k in g.events if ev == "after_death"] == ["recover", "stop"])
    check("dying before the pick → blood_lost", any(ev == "blood_lost" for ev, _ in g.events))

    # --no-recover: the old way
    g = Game({(0, 4): 1}, [rich])
    check("recover=False → a death ends the run, no respawn wait", g.run(recover=False) == "died" and g.life == 0)

    # --seg 5-8 died in 5 → recovery trip restarts at zone 1 (every foe is back)
    g = Game({(0, 6): 1}, [rich], pick_at={(1, 6): "got"})
    g.run(first=5)
    check("--seg 5-8: first life 5..6, recovery trip 1..8", [n for l, n in g.played if l == 0] == [5, 6]
          and [n for l, n in g.played if l == 1] == list(range(1, 9)))

    # a death that left no new stain record (0 souls, 0 humanity) → ignore, don't reuse the old file
    g = Game({(0, 2): 1}, [None])
    g.stain = {**rich, "t": "old"}
    check("no fresh stain after respawn → ignore (old record not reused)", g.run() == "died"
          and [k["action"] for ev, k in g.events if ev == "after_death"] == ["ignore"])

    # Escape: a fall is recorded only — no freeze, no quit-out, cooldown kept
    pad = types.SimpleNamespace(froze=0, freeze=lambda *a, **k: setattr(pad, "froze", pad.froze + 1))
    rows, lines = [], []
    esc = watch.Escape(pad, [], log=lines.append, events=lambda ev, **k: rows.append((ev, k)))
    esc.fire = lambda *a, **k: (_ for _ in ()).throw(AssertionError("fire() on a fall"))
    check("default policy: fall_quit off", esc.fall_quit is False)
    p = types.SimpleNamespace(x=-10.31, y=-16.72, z=-66.43, hp=669)
    esc.fall_seen("낙사 (바닥 모름, 0.8 s 에 4.3 m)", p)
    check("fall_seen: 'fall' event, not 'escape' (risk_report counts those as quit-outs)",
          rows == [("fall", {"why": "낙사 (바닥 모름, 0.8 s 에 4.3 m)", "kind": "fall", "pos0": [-10.31, -16.72, -66.43], "hp": 669})])
    check("fall_seen: pad untouched, cooldown + last_fall_pos set, gen unchanged",
          pad.froze == 0 and esc.last_fall > 0 and esc.last_fall_pos == [-10.31, -16.72, -66.43] and esc.gen == 0)
    # Field.pick_blood: only with no foe near me or the stain; a foe coming during the walk stops it ([MoKa] 10-12)
    from souls import field as F
    stain = {"pos": [10.0, 0.0, 10.0], "souls": 3114, "humanity": 1, "t": "x"}
    F.Blood.read = staticmethod(lambda: stain)

    def chr_at(x, z, me=(0.0, 0.0)):
        return types.SimpleNamespace(npc_param=254010, x=x, y=0.0, z=z, hp=75, team=6, dist=((x - me[0]) ** 2 + (z - me[1]) ** 2) ** 0.5)

    def snap(chars, me=(0.0, 0.0)):
        sn = types.SimpleNamespace(player=types.SimpleNamespace(x=me[0], y=0.0, z=me[1]), chars=chars)
        sn.hostile = lambda within: [c for c in chars if c.hp > 0 and c.dist <= within]
        return sn

    def fake(chars, walk_snaps=()):
        walked = []
        souls = iter([100, 100, 3214])

        def walk_to(pos, nm, tag, done=None):
            walked.append(pos)
            for sn in walk_snaps:
                if done is not None and done(sn):
                    return "arrived"
            return "arrived"
        mv = types.SimpleNamespace(snap=lambda w: snap(chars), press=lambda b: None,
                                   tm=types.SimpleNamespace(souls=lambda: next(souls, 3214)))
        return types.SimpleNamespace(bonfires=[], mv=mv, log=lambda *a: None, walk_to=walk_to, _foes_by=F.Field._foes_by), walked

    F.time.sleep = lambda s: None
    me_ok, walked = fake([chr_at(60.0, 60.0)])
    check("no foe within 15 m of me or the stain → walk and pick", F.Field.pick_blood(me_ok, None, near=40.0) == "got" and walked)
    near_stain, walked = fake([chr_at(14.0, 18.0)])
    check("a sleeping foe 8.9 m from the stain → foes_near, no walk", F.Field.pick_blood(near_stain, None, near=40.0) == "foes_near" and not walked)
    near_me, walked = fake([chr_at(-5.0, 3.0)])
    check("a foe 5.8 m from me → foes_near, no walk", F.Field.pick_blood(near_me, None, near=40.0) == "foes_near" and not walked)
    came, walked = fake([], walk_snaps=[snap([]), snap([chr_at(6.0, 4.0, me=(5.0, 5.0))], me=(5.0, 5.0))])
    check("a foe comes during the walk → walk stops, foes_near, no A", F.Field.pick_blood(came, None, near=40.0) == "foes_near" and walked)
    print("afterdeath: all ok")


if __name__ == "__main__":
    main()
