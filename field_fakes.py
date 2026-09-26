"""souls.field 오프라인 테스트용 가짜들 — 게임·패드 없이 Field.clear/_liveness/_hold_at 을 돌린다.

  world = World(player=(x, y, z))
  world.add(ptr=3, handle=0x1003, npc=254000, pos=(0, -40, 0), hp=75)
  f = make_field(world)          # Field 를 __init__ 없이 만들고 fight/lure/recover/walk_to 를 기록기로 바꾼다
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from telemetry import Chr, Snapshot
from souls import duel as D
from souls import field as F


class World:
    def __init__(self, player=(0.0, -49.4, 0.0), sp=106, max_sp=106, hp=793):
        self.t = 0.0
        self.player = Chr(ptr=1, npc_param=0, team=1, hp=hp, max_hp=793, x=player[0], y=player[1], z=player[2],
                          sp=sp, max_sp=max_sp, anim=-1, heading=0.0)
        self.chars: dict[int, Chr] = {}
        self.handles: dict[int, int] = {}
        self.hidden: set[int] = set()              # read_chr 실패 흉내 — 목록에서 빠진다

    def add(self, ptr, handle, npc, pos, hp=75, max_hp=75, anim=-1, team=6):
        self.chars[ptr] = Chr(ptr=ptr, npc_param=npc, team=team, hp=hp, max_hp=max_hp, x=pos[0], y=pos[1], z=pos[2],
                              anim=anim, heading=0.0)
        self.handles[ptr] = handle
        return self.chars[ptr]

    def move(self, ptr, pos):
        c = self.chars[ptr]
        c.x, c.y, c.z = pos

    def snapshot(self, within: float = 60.0):
        self.t += 0.05
        p = self.player
        out = []
        for ptr, c in self.chars.items():
            if ptr in self.hidden:
                continue
            c.dist = math.dist((p.x, p.y, p.z), (c.x, c.y, c.z))
            if c.dist <= within:
                out.append(c)
        out.sort(key=lambda c: c.dist)
        return Snapshot(t=self.t, player=p, chars=out, cam_yaw=0.0)


class FakeTm:
    def __init__(self, world: World):
        self.w = world

    def handle(self, p):
        return self.w.handles.get(p)

    def lock_target(self):
        return -1


class FakePad:
    def __init__(self):
        self.calls: list[tuple] = []

    def move(self, x, y):
        self.calls.append(("move", round(x, 3), round(y, 3)))

    def neutral(self):
        self.calls.append(("neutral",))

    def look(self, x, y):
        self.calls.append(("look", x, y))

    def guard(self, on):
        self.calls.append(("pad_guard", on))


class FakeMv:
    def __init__(self, world: World):
        self.w = world
        self.tm = FakeTm(world)
        self.pad = FakePad()
        self.guards: list[bool] = []
        self.faced: list[int] = []

    def snap(self, within: float = 40.0):
        return self.w.snapshot(within)

    @staticmethod
    def find(s, ptr):
        return next((x for x in s.chars if x.ptr == ptr), None) if s else None

    def guard(self, on: bool) -> None:
        self.guards.append(on)
        self.pad.calls.append(("guard", on))

    def stick_to(self, s, x: float, z: float, scale: float = 1.0):
        p = s.player
        d = max(1e-6, ((x - p.x) ** 2 + (z - p.z) ** 2) ** 0.5)
        return ((x - p.x) / d * scale, (z - p.z) / d * scale)

    def face(self, s, c, deg: float = 20.0) -> bool:
        self.faced.append(c.ptr)
        return True


class FakeEsc:
    escaping = False
    gen = 0


class FakeReflex:
    def __init__(self):
        self.bs_attack = True
        self.ticks = 0
        self.bs_seen: list[bool] = []

    def update(self, s):
        pass

    def tick(self, s) -> bool:
        self.ticks += 1
        self.bs_seen.append(self.bs_attack)
        return False


def make_field(world: World, fight_kills: bool = True) -> F.Field:
    f = F.Field.__new__(F.Field)
    f.mv = FakeMv(world)
    f.esc = FakeEsc()
    f.logs: list[str] = []
    f.log = f.logs.append
    f.evs: list[tuple] = []
    f.events = lambda kind, **kw: f.evs.append((kind, kw))
    f.reflex = FakeReflex()
    f.fights: list[dict] = []
    f.lures: list[dict] = []
    f.recovers: list[str] = []
    f.walks: list[tuple] = []

    def fight(ptr, nm, tag, arena=None, desperate=False, limit=45.0, wait_far=False, leash=None, may_approach=None):
        f.fights.append(dict(ptr=ptr, tag=tag, limit=limit, wait_far=wait_far, leash=leash, may=may_approach))
        if fight_kills and ptr in world.chars:
            world.chars[ptr].hp = 0
            return D.DuelResult("killed")
        return D.DuelResult("cancel")

    def lure(ptr, spawn, nm, tag, arena=None, lure_at=None):
        f.lures.append(dict(ptr=ptr, tag=tag, lure_at=lure_at))
        return f.lure_result

    f.lure_result = "no_reaction"
    f.fight = fight
    f.lure = lure
    f.recover = lambda why, nm=None: (f.recovers.append(why), True)[1]
    f.walk_to = lambda goal, nm, tag, mode="walk", tol=None, done=None: (f.walks.append((tuple(goal), tag)), "arrived")[1]
    f.alive = lambda: True
    f.wait_escape = lambda timeout=40.0: None
    f.estus_left = lambda: 5
    return f
