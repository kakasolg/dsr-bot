"""Shop routine (souls/shop.py) against a fake Undead Merchant that behaves like [win]'s step record
(docs/shop-undead-merchant.md, data/shop/20261012/). No game.

  python tests/shop_test.py

The fake: A in the game opens a ~2 s greeting (menu_open already True), then Purchase Item / Talk / Leave; the list opens with
the cursor on row 1; A on a row opens the quantity window at qty 1 with CANCEL selected; UP = +1, RIGHT = OK; A on OK buys
and goes back to the list with the cursor kept; B steps back out. Inputs can be swallowed to test the retry.
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

    def __init__(self, clock, souls=4042, goods=None, swallow=(), talks=True):
        self.clock, self.souls, self.goods = clock, souls, dict(goods or {290: 0, 292: 47})
        self.state, self.cursor, self.qty, self.ok, self.until = "game", 1, 1, False, 0.0
        self.swallow, self.talks, self.presses = set(swallow), talks, []

    def _tick(self):
        if self.state == "greeting" and self.clock.t >= self.until:
            self.state = "menu"
        if self.state == "farewell" and self.clock.t >= self.until:
            self.state = "game"

    def menu_open(self):
        self._tick()
        return self.state != "game"

    def press(self, button, hold):
        self._tick()
        i = len(self.presses)
        self.presses.append(NAME.get(button, str(button)))
        self.clock.sleep(hold)
        if i in self.swallow:
            return
        st = self.state
        if st == "game" and button == A and self.talks:
            self.state, self.until = "greeting", self.clock.t + 1.9
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
    shop = S.Shop(mv, log=lambda *a: None, events=lambda ev, **k: events.append(k))
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

    # CANCEL is the default: a swallowed RIGHT buys nothing → leave, talk again, cursor back on row 1, buy on the second try
    shop, game, ev = rig(swallow={2 + 1 + 1 + 4})      # A A DOWN A UP×4 → the RIGHT
    out = shop.buy([(290, 5)])
    check(f"swallowed RIGHT (still on CANCEL) → nothing bought → retried after a new talk → {ev[-1]}",
          out["result"] == "ok" and game.goods[290] == 5 and ev[-1]["tries"] == 2 and game.souls == 4042 - 50)
    i_b = game.presses.index("B")
    check("the retry left (B B) and talked again (A A) before DOWN to row 2 again",
          game.presses[i_b:i_b + 5] == ["B", "B", "A", "A", "DOWN"])

    # two misses → shop_fail, stop, menu closed
    shop, game, ev = rig(swallow={8, 20})                # both RIGHTs: A A DOWN A UP×4 [RIGHT] A · B B A A DOWN A UP×4 [RIGHT] A
    out = shop.buy([(290, 5), (292, 1)])
    check(f"two misses → shop_fail, the next item not tried → {out['result']}",
          out["result"] == "shop_fail" and len(out["items"]) == 1 and game.goods[292] == 47 and not game.menu_open())

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
    # run.py wiring: --buy parsed and handed to Shop.buy with Field.walk_to for the approach
    import run
    seen = {}

    class FakeShop:
        def __init__(self, mv, nm, log=None, events=None, shoot=None, walk_to=None):
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
