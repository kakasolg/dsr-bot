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
print("npc_test: 전부 통과")
