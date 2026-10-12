"""Shop routine (souls/shop.py) against a fake Undead Merchant that behaves like [win]'s step record
(docs/shop-undead-merchant.md, data/shop/20261012/). No game.

  python tests/shop_test.py

The fake: A in the game opens a greeting of `lines` lines (menu_open already True) — each line runs LINE_AUTO s on its own,
an A during a line only advances it ([win] game check 1: a 4-line greeting shifted every fixed-time press) — then Purchase Item /
Talk / Leave; the list opens with the cursor on row 1; A on a row opens the quantity window at qty 1 with CANCEL selected;
UP = +1, RIGHT = OK; A on OK buys and goes back to the list with the cursor kept; B steps back out. The fake Screen reports
what the fake game shows (menu / list / qty / None for a line or the game), like souls.shop.Screen does from the window.
Inputs can be swallowed (the nth press of a button) to test the checks and the retry. Screen.state() is also run on the record
screenshots themselves.
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import sys
from types import SimpleNamespace as NS

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from souls import shop as S

A, B, UP, DOWN, RIGHT = S.A_, S.B_, S.UP, S.DOWN, S.RIGHT
NAME = {A: "A", B: "B", UP: "UP", DOWN: "DOWN", RIGHT: "RIGHT"}


def check(name: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        raise SystemExit(1)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def time(self):
        return self.t

    def sleep(self, s):
        self.t += max(0.0, s)


class Merchant:
    """The game side: state, souls, goods, and what each button does."""
    ROWS = {1: (280, 500), 2: (290, 10), 3: (292, 50), 4: (999, 500)}

    LINE_AUTO = 3.0

    def __init__(self, clock, souls=4042, goods=None, swallow=(), talks=True, lines=1):
        self.clock, self.souls, self.goods = clock, souls, dict(goods or {290: 0, 292: 47})
        self.state, self.cursor, self.qty, self.ok, self.until = "game", 1, 1, False, 0.0
        self.swallow, self.talks, self.presses, self.lines, self.left = set(swallow), talks, [], lines, 0
        self.seen: dict = {}

    def _tick(self):
        while self.state == "greeting" and self.clock.t >= self.until:
            self.left -= 1
            if self.left <= 0:
                self.state = "menu"
            else:
                self.until += self.LINE_AUTO
        if self.state == "farewell" and self.clock.t >= self.until:
            self.state = "game"

    def screen(self):
        self._tick()
        return self.state if self.state in ("menu", "list", "qty") else None

    def menu_open(self):
        self._tick()
        return self.state != "game"

    def press(self, button, hold):
        self._tick()
        name = NAME.get(button, str(button))
        self.presses.append(name)
        self.seen[name] = self.seen.get(name, 0) + 1
        self.clock.sleep(hold)
        if (name, self.seen[name]) in self.swallow:
            return
        st = self.state
        if st == "game" and button == A and self.talks:
            self.state, self.left, self.until = "greeting", self.lines, self.clock.t + (1.9 if self.lines == 1 else self.LINE_AUTO)
        elif st == "greeting" and button == A:          # A during a line: the next line (or the menu after the last)
            self.left -= 1
            self.state = "menu" if self.left <= 0 else "greeting"
            self.until = self.clock.t + self.LINE_AUTO
        elif st == "menu":
            if button == A:
                self.state, self.cursor = "list", 1
            elif button == B:
                self.state, self.until = "farewell", self.clock.t + 1.0
        elif st == "list":
            if button == DOWN:
                self.cursor = min(4, self.cursor + 1)
            elif button == UP:
                self.cursor = max(1, self.cursor - 1)
            elif button == A:
                self.state, self.qty, self.ok = "qty", 1, False
            elif button == B:
                self.state = "menu"
        elif st == "qty":
            if button == UP:
                self.qty += 1
            elif button == RIGHT:
                self.ok = True
            elif button == B:
                self.state = "list"
            elif button == A:
                g, price = self.ROWS[self.cursor]
                if self.ok and self.souls >= price * self.qty:
                    self.souls -= price * self.qty
                    self.goods[g] = self.goods.get(g, 0) + self.qty
                self.state = "list"


def rig(**kw):
    clock = Clock()
    S.time = clock                                     # the module's time.time / time.sleep
    game = Merchant(clock, **kw)
    me = NS(x=0.0, y=0.0, z=0.0, heading=0.0)
    npc = NS(ptr=9, npc_param=251001, x=0.0, y=0.0, z=1.5)
    snap = NS(player=me, chars=[npc], cam_yaw=0.0)
    pad = NS(press=game.press, neutral=lambda: None, move=lambda x, y: None)
    tm = NS(menu_open=game.menu_open, souls=lambda: game.souls, goods_count=lambda g: game.goods.get(g, 0))
    mv = NS(tm=tm, pad=pad, snap=lambda within=40.0: snap, aim=lambda ptr, deg=1.5, timeout=3.0: 3.0,
            stick_to=lambda s, x, z, scale=1.0: (0.0, scale))
    events = []
    screen = NS(ready=lambda: True, state=game.screen, ok_selected=lambda: game.ok if game.state == "qty" else None, last={})
    shop = S.Shop(mv, log=lambda *a: None, events=lambda ev, **k: events.append(k), screen=screen)
    return shop, game, events


def main() -> None:
    check("parse_items '290:30,292:20'", S.parse_items("290:30,292:20") == [(290, 30), (292, 20)])

    # the recorded purchase: knives × 30, firebombs × 20 from 4042 souls → 2742, 47 → 67 firebombs (docs 12, 17)
    shop, game, ev = rig()
    out = shop.buy([(290, 30), (292, 20)])
    check(f"record replayed: ok, souls 4042 → {game.souls}, knives {game.goods[290]}, firebombs {game.goods[292]}",
          out["result"] == "ok" and game.souls == 2742 and game.goods[290] == 30 and game.goods[292] == 67)
    want = ["A", "A", "DOWN", "A"] + ["UP"] * 29 + ["RIGHT", "A", "DOWN", "A"] + ["UP"] * 19 + ["RIGHT", "A", "B", "B"]
    check("buttons in the recorded order (cursor kept on row 2 → one DOWN to row 3; RIGHT before each A on the quantity)",
          game.presses == want)
    check("left the conversation (menu closed)", not game.menu_open() and shop.row is None)
    check("one 'shop' event per item with counts and souls",
          [(e["goods"], e["bought"], e["souls0"], e["souls1"], e["result"]) for e in ev] == [(290, 30, 4042, 3742, "ok"),
                                                                                            (292, 20, 3742, 2742, "ok")])

    # [win] game check 1: a 4-line greeting — fixed waits pressed into the dialogue. Now: wait for the menu, A to advance lines
    shop, game, ev = rig(lines=4)
    out = shop.buy([(290, 30), (292, 20)])
    a_talk = game.presses[:game.presses.index("DOWN")]
    check(f"4-line greeting: A's advance the lines until the menu, then Purchase Item → bought ({a_talk})",
          out["result"] == "ok" and game.goods[290] == 30 and game.goods[292] == 67 and all(x == "A" for x in a_talk)
          and len(a_talk) >= 3)
    shop, game, ev = rig(lines=2)
    game.LINE_AUTO = 1.0                                # lines that pass on their own before LINE_S → no extra A
    out = shop.buy([(290, 1)])
    check("short lines pass by themselves → only A (talk) and A (Purchase Item)", game.presses[:3] == ["A", "A", "DOWN"]
          and out["result"] == "ok")

    # CANCEL is the default: a swallowed RIGHT is seen on screen (still CANCEL) → RIGHT again → bought first try
    shop, game, ev = rig(swallow={("RIGHT", 1)})
    out = shop.buy([(290, 5)])
    check(f"swallowed RIGHT → OK check → second RIGHT → bought on the first try ({ev[-1]['tries']} try)",
          out["result"] == "ok" and game.goods[290] == 5 and ev[-1]["tries"] == 1 and game.presses.count("RIGHT") == 2)
    # both RIGHTs swallowed → B closes the window (no A on CANCEL) → leave, talk again, buy on the second try
    shop, game, ev = rig(swallow={("RIGHT", 1), ("RIGHT", 2)})
    out = shop.buy([(290, 5)])
    check(f"RIGHT twice swallowed → window closed with B, retried after a new talk → {ev[-1]['tries']} tries",
          out["result"] == "ok" and game.goods[290] == 5 and ev[-1]["tries"] == 2 and game.souls == 4042 - 50)
    # A on the row swallowed → the quantity window never shows → nothing more pressed into the list; retry from a new talk
    shop, game, ev = rig(swallow={("A", 3)})           # A talk, A Purchase Item, [A row]
    out = shop.buy([(290, 3)])
    i_row = [k for k, x in enumerate(game.presses) if x == "A"][2]
    check("A on the row swallowed → no UP / RIGHT into the list; bought on the retry",
          game.presses[i_row + 1] != "UP" and out["result"] == "ok" and game.goods[290] == 3)

    # two misses → shop_fail, stop, menu closed
    shop, game, ev = rig(swallow={("RIGHT", 1), ("RIGHT", 2), ("RIGHT", 3), ("RIGHT", 4)})
    out = shop.buy([(290, 5), (292, 1)])
    check(f"two misses → shop_fail, the next item not tried → {out['result']}",
          out["result"] == "shop_fail" and len(out["items"]) == 1 and game.goods[292] == 47 and not game.menu_open())

    # no reference masks → no_screen, nothing pressed
    shop, game, ev = rig()
    shop.screen = NS(ready=lambda: False)
    check("no screen references → no_screen, no buttons", shop.buy([(290, 1)])["result"] == "no_screen" and game.presses == [])

    # not enough souls: as many as we can pay for
    shop, game, ev = rig(souls=300)
    out = shop.buy([(292, 20)])
    check(f"300 souls, firebombs × 20 at 50 → 6 bought ({ev[-1]})", game.goods[292] == 53 and ev[-1]["asked"] == 6 and game.souls == 0)
    shop, game, ev = rig(souls=40)
    out = shop.buy([(292, 1), (290, 4)])
    check("40 souls: no firebomb (no_souls, no buttons for it), 4 knives", [e["result"] for e in ev] == ["no_souls", "ok"]
          and game.goods[290] == 4 and game.goods[292] == 47)

    # an item this merchant doesn't sell
    shop, game, ev = rig()
    out = shop.buy([(1234, 1)])
    check("not on this merchant's list → not_sold, partial", ev[-1]["result"] == "not_sold" and out["result"] == "partial")

    # no talk prompt (not facing / A does nothing) → no_talk, nothing pressed beyond the A tries
    shop, game, ev = rig(talks=False)
    out = shop.buy([(290, 1)])
    check(f"menu never opens → no_talk after one re-aim ({game.presses})", out["result"] == "no_talk" and game.presses == ["A", "A"])

    # merchant not in sight
    shop, game, ev = rig()
    shop.mv.snap = lambda within=40.0: NS(player=NS(x=0.0, y=0.0, z=0.0, heading=0.0), chars=[], cam_yaw=0.0)
    check("merchant not found → not_found, no buttons", shop.buy([(290, 1)])["result"] == "not_found" and game.presses == [])
    # the real Screen on the record screenshots (data/shop/20261012): every state named right, CANCEL / OK told apart
    from pathlib import Path
    from PIL import Image
    shots = Path(__file__).resolve().parent.parent / "data" / "shop" / "20261012"
    want = {"05": "menu", "06": "list", "07": "list", "08": "qty", "09": "qty", "12": "list", "14": "qty", "16": "qty",
            "17": "list", "18": "menu", "24": "menu", "26": "list", "27": "menu",
            "01": None, "02": None, "03": None, "04": None, "19": None, "20": None, "21": None, "22": None, "23": None}
    got = {}
    for f in sorted(shots.glob("*.jpg")):
        sc = S.Screen(grab=lambda f=f: Image.open(f))
        got[f.name[:2]] = (sc.state(), sc.ok_selected())
    bad = {k: got[k][0] for k in want if got.get(k, (0,))[0] != want[k]}
    check(f"Screen.state() on {len(want)} record shots: menu / list / qty / dialogue-or-game all right {bad or ''}", not bad)
    check("ok_selected: CANCEL on 08 / 14 / 15, OK on 09 / 11 / 16",
          [got[k][1] for k in ("08", "14", "15")] == [False] * 3 and [got[k][1] for k in ("09", "11", "16")] == [True] * 3)

    # run.py wiring: --buy parsed and handed to Shop.buy with Field.walk_to for the approach
    import run
    seen = {}

    class FakeShop:
        def __init__(self, mv, nm, log=None, events=None, shoot=None, walk_to=None, screen=None):
            seen.update(nm=nm, shoot=shoot, walk_to=walk_to)

        def buy(self, items):
            seen["items"] = items
            return {"result": "ok", "items": [{"goods": g, "bought": n, "want": n} for g, n in items]}
    real, S.Shop = S.Shop, FakeShop
    try:
        lines = []

        class Log:                                     # run.py's Log: callable + .event
            def __call__(self, line):
                lines.append(line)

            def event(self, ev, **k):
                pass
        log = Log()
        r = run._shop(NS(buy="290:30,292:20", shop_shots=False), NS(), "nmB", NS(walk_to="fld.walk_to"), log)
        check(f"run._shop: items parsed, NavMesh and walk_to passed, no shots → {r}", r == "shop ok"
              and seen == {"nm": "nmB", "shoot": None, "walk_to": "fld.walk_to", "items": [(290, 30), (292, 20)]})
        check("run._shop without --buy → nothing bought", run._shop(NS(buy=None, shop_shots=False), NS(), None, NS(), log)
              == "shop: --buy 없음")
    finally:
        S.Shop = real
    print("shop_test: all ok")


if __name__ == "__main__":
    main()
