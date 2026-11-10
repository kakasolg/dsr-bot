"""souls/npc.Npc — the talk steps every NPC shares (ROADMAP npc-module), on a made-up NPC that is not the merchant: greeting
lines advanced with A until its own menu shows, then B out. The merchant path through Npc is tests/shop_test.py. No game."""
from __future__ import annotations

import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(1, str(_pl.Path(__file__).resolve().parent))

from types import SimpleNamespace as NS

from souls import npc as N


def check(what: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + what)
    if not ok:
        raise SystemExit(1)


class Clock:
    def __init__(self):
        self.t = 0.0

    def time(self):
        return self.t

    def sleep(self, s):
        self.t += max(s, 0.01)


class Smith:
    """An NPC that greets with `lines` dialogue lines, then shows its 'smith' menu; B closes after one farewell line."""
    def __init__(self, lines: int):
        self.lines, self.open, self.state, self.presses = lines, False, None, []

    def press(self, b, hold):
        name = {N.A_: "A", N.B_: "B"}[b]
        self.presses.append(name)
        if name == "A" and not self.open:
            self.open, self.state = True, (None if self.lines else "smith")
        elif name == "A" and self.state is None:
            self.lines -= 1
            self.state = None if self.lines else "smith"
        elif name == "B" and self.state == "smith":
            self.state = "bye"
        elif name == "B" and self.state == "bye":
            self.open, self.state = False, None


def rig(lines: int):
    N.time = Clock()
    game = Smith(lines)
    mv = NS(tm=NS(menu_open=lambda: game.open), pad=NS(press=game.press))
    who = {"npc": 999999, "name": "대장장이 (시험)", "pos": (0.0, 0.0, 0.0)}
    return N.Npc(mv, who, screen=NS(state=lambda: game.state if game.state == "smith" else None), tag="NPC"), game


npc, game = rig(2)
check("two greeting lines → A, A, A → its menu", npc.greet(("smith",)) == "smith" and game.presses == ["A", "A", "A"])
check("close: B, then B again while the farewell line holds menu_open", npc.close() and not game.open and game.presses[-2:] == ["B", "B"])
npc, game = rig(20)
check(f"no menu within LINES_MAX ({N.LINES_MAX}) lines → None", npc.greet(("smith",)) is None)
npc, game = rig(0)
npc.pad.press = lambda b, hold: game.presses.append(b)    # the A never opens a conversation (no talk prompt)
check("no talk prompt (menu_open stays False) → None after one A", npc.greet(("smith",)) is None and len(game.presses) == 1)


# ── P-155 (20261110_061503): a hurt or attacking NPC is not approached, and nothing is pressed ──
def rig_approach(hp: int, anim: int = 9000, after_walk_hp: int | None = None):
    calls = []
    me = NS(x=0.0, y=0.0, z=4.5)
    them = NS(npc_param=999999, ptr=1, x=0.0, y=0.0, z=0.0, hp=hp, max_hp=360, anim=anim)
    pad = NS(press=lambda b, hold: calls.append("press"), neutral=lambda: calls.append("neutral"),
             move=lambda x, y: calls.append("move"))
    mv = NS(tm=NS(menu_open=lambda: False), pad=pad, snap=lambda within: NS(player=me, chars=[them]),
            stick_to=lambda s, x, z, f: (0.0, 0.0), aim=lambda ptr, deg, timeout: 0.0)

    def walk_to(goal, nm, tag):
        calls.append("walk")
        me.z = 1.0
        if after_walk_hp is not None:
            them.hp = after_walk_hp
        return "arrived"
    who = {"npc": 999999, "name": "상인 (시험)", "pos": (0.0, 0.0, 0.0)}
    return N.Npc(mv, who, walk_to=walk_to, log=lambda m: None), calls


N.time = Clock()
npc, calls = rig_approach(hp=216)                          # the run's numbers: 360 → 216 before the bot's first line
check("hurt NPC (216/360) → 'hostile', no walk, no pad call", npc.approach() == "hostile" and calls == [])
npc, calls = rig_approach(hp=360, anim=3004)
check("full HP but in an attack anim (3004) → 'hostile', no pad call", npc.approach() == "hostile" and calls == [])
npc, calls = rig_approach(hp=360)
check("unhurt, idle NPC → walks in and ends 'ok'", npc.approach() == "ok" and "walk" in calls)
npc, calls = rig_approach(hp=360, after_walk_hp=288)
check("hurt during the walk → 'hostile' after it, no step or press afterwards",
      npc.approach() == "hostile" and "move" not in calls and "press" not in calls)
print("npc_test: 전부 통과")
