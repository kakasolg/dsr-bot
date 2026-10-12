"""Buying from a merchant — the first NPC interaction (ROADMAP "NPC interaction"; [MoKa] 2026-10-12: firebombs make the game much
easier, and the bot has to buy them itself).

Built from [win]'s step-by-step record of the Undead Merchant (docs/shop-undead-merchant.md, screenshots data/shop/20261012/):
  face the merchant ≤ 1.7 m (the talk prompt only shows while looking at him) → A → ~2 s greeting (menu_open is True already)
  → A "Purchase Item" → the list (cursor on row 1) → per item: DOWN/UP to its row → A → quantity window (qty 1, CANCEL
  selected) → UP × (n − 1) → RIGHT (CANCEL → OK) → A → back on the list, cursor stays on that row → … → B (list → menu)
  → B (menu → farewell → game).

Success is read from memory, not the screen: the item's count went up by n and souls went down by price × n. If neither moved,
we don't know where the menu is (an input may have been swallowed), so we leave the conversation and talk again — the cursor
is back on row 1 — and try that item once more; a second miss stops ('shop_fail').

  shop = Shop(mv, nm, log=log, events=log.event)
  shop.buy([(290, 30), (292, 20)])    # throwing knives × 30, firebombs × 20
"""
from __future__ import annotations

import math
import time

import control
from souls import moves as M

B = control.B
A_, B_, UP, DOWN, RIGHT = (B.XUSB_GAMEPAD_A, B.XUSB_GAMEPAD_B, B.XUSB_GAMEPAD_DPAD_UP, B.XUSB_GAMEPAD_DPAD_DOWN,
                           B.XUSB_GAMEPAD_DPAD_RIGHT)

# The Undead Merchant (male) in the Undead Burg — fixed list (docs/shop-undead-merchant.md 06): goods id → (row, price)
UNDEAD_MERCHANT = {"npc": 251001, "pos": (-38.02, -19.80, -66.50), "name": "망자 상인",
                   "rows": {280: (1, 500), M.ITEM_KNIFE: (2, 10), M.ITEM_FIREBOMB: (3, 50)}}   # row 4 Lloyd's Talisman 500 (id unrecorded)

TALK_R = 1.7          # stand this close (record 03: the prompt showed at 1.7 m facing him, not at 1.2 m facing away)
TALK_DEG = 12.0       # … facing him this well
APPROACH_S = 6.0
GREET_S = 2.0         # A → greeting line → the menu (Purchase Item / Talk / Leave) after ~2 s (record 04 → 05)
OPEN_S = 1.2          # A on Purchase Item → the list
MOVE_S = 0.5          # a cursor step on the list / OK↔CANCEL
SELECT_S = 0.8        # A on a row → the quantity window
QTY_GAP = 0.25        # UP × 28 at this spacing all went in (record 11)
BUY_S = 1.0           # A on OK → bought, back on the list
CHECK_S = 1.5         # poll memory this long for the purchase to show
LEAVE_S = 5.0         # B, B, then wait for menu_open to go False
HOLD = 0.1


class Shop:
    def __init__(self, mv, nm=None, log=print, events=None, merchant: dict = UNDEAD_MERCHANT, shoot=None, walk_to=None):
        """mv: souls.moves.Moves · nm: NavMesh for the approach · shoot(tag): optional screenshot after each step (run.py
        --shop-shots, the way pad_step.py recorded it) · walk_to(goal, nm, tag) → 'arrived' …: Field.walk_to, used only when
        the merchant is farther than a few metres."""
        self.mv, self.tm, self.pad, self.nm = mv, mv.tm, mv.pad, nm
        self.log, self.events, self.m, self.shoot, self.walk_to = log, events or (lambda *a, **k: None), merchant, shoot, walk_to
        self.row = None        # where the list cursor is (None = list not open)

    # ── buttons ───────────────────────────────────────────────
    def _press(self, button, wait: float, tag: str = "", n: int = 1, gap: float = QTY_GAP) -> None:
        for i in range(n):
            self.pad.press(button, HOLD)
            if i < n - 1:
                time.sleep(gap)
        time.sleep(wait)
        if self.shoot is not None and tag:
            try:
                self.shoot(tag)
            except Exception:
                pass

    # ── the merchant ──────────────────────────────────────────
    def find(self, s):
        return next((c for c in (s.chars if s else ()) if c.npc_param == self.m["npc"]), None)

    def approach(self) -> str:
        """Within TALK_R of the merchant, facing him within TALK_DEG. → 'ok' | 'not_found' | 'far' | a walk result"""
        self.pad.neutral()
        s = self.mv.snap(30.0)
        c = self.find(s)
        if c is None:
            return "not_found"
        d = M.horiz(s.player, c)
        if d > 4.0:
            if self.walk_to is None:
                return "far"
            p = (c.x, c.y, c.z)
            r = self.walk_to(p, self.nm, self.m["name"])
            if r not in ("arrived", "stuck", "unreachable", "timeout"):
                return r
        t0 = time.time()
        while time.time() - t0 < APPROACH_S:                # short steps in — a sitting NPC: walking into him is harmless
            s = self.mv.snap(30.0)
            c = self.find(s)
            if c is None:
                return "not_found"
            d = M.horiz(s.player, c)
            if d <= TALK_R:
                break
            self.pad.move(*self.mv.stick_to(s, c.x, c.z, 0.35))
            time.sleep(min(0.25, 0.08 + (d - TALK_R) * 0.15))
            self.pad.move(0.0, 0.0)
            time.sleep(0.15)
        self.pad.move(0.0, 0.0)
        off = self.mv.aim(c.ptr, deg=TALK_DEG, timeout=3.0)  # taps that turn without walking (face() would push the stick)
        s = self.mv.snap(30.0)
        c = self.find(s)
        d = M.horiz(s.player, c) if c is not None else None
        self.log(f"   상점: {self.m['name']} {d if d is None else round(d, 2)} m, 몸 {off if off is None else round(off)}°")
        if c is None or d > TALK_R + 0.4 or off is None or abs(off) > TALK_DEG:
            return "not_facing"
        return "ok"

    def talk(self) -> bool:
        """A → greeting → A on 'Purchase Item' → the list (cursor row 1). False if the menu never opened (no talk prompt)."""
        self._press(A_, 0.0, "")
        t0 = time.time()
        while time.time() - t0 < 1.5:
            if self.tm.menu_open():
                break
            time.sleep(0.05)
        else:
            return False
        time.sleep(max(0.0, GREET_S - (time.time() - t0)))
        if self.shoot is not None:
            self.shoot("after-greeting")
        self._press(A_, OPEN_S, "purchase-item")
        self.row = 1
        return True

    def leave(self) -> bool:
        """B (list → menu), B (menu → farewell → game); wait for menu_open False. → closed"""
        self._press(B_, 0.8, "close-shop")
        self._press(B_, 0.0, "")
        t0 = time.time()
        while time.time() - t0 < LEAVE_S:
            if not self.tm.menu_open():
                self.row = None
                time.sleep(0.5)
                return True
            if time.time() - t0 > 3.0:
                self._press(B_, 0.5)                       # still in a line of dialogue
            time.sleep(0.1)
        return False

    # ── one item ──────────────────────────────────────────────
    def _counts(self, goods: int) -> tuple[int, int]:
        return self.tm.goods_count(goods) or 0, self.tm.souls() or 0

    def _buy_one(self, goods: int, n: int, row: int, price: int) -> tuple[int, int]:
        """On the open list: move to row, A, n − 1 × UP, RIGHT (CANCEL → OK), A. → (bought, souls spent) read from memory."""
        g0, s0 = self._counts(goods)
        step = row - self.row
        if step:
            self._press(DOWN if step > 0 else UP, MOVE_S, f"to-{goods}", n=abs(step))
        self.row = row
        self._press(A_, SELECT_S, f"select-{goods}")
        if n > 1:
            self._press(UP, MOVE_S, f"qty-{n}", n=n - 1)
        self._press(RIGHT, MOVE_S, "ok")                   # the window opens on CANCEL (record 08 → 09)
        self._press(A_, BUY_S, f"buy-{goods}")
        t0 = time.time()
        g1, s1 = g0, s0
        while time.time() - t0 < CHECK_S:
            g1, s1 = self._counts(goods)
            if g1 != g0 or s1 != s0:
                break
            time.sleep(0.1)
        return g1 - g0, s0 - s1

    def buy(self, items: list[tuple[int, int]]) -> dict:
        """items = [(goods id, count), …]. → {'result': 'ok' | 'partial' | 'shop_fail' | approach result, 'items': [rows]}"""
        out = {"result": "ok", "items": []}
        r = self.approach()
        if r != "ok":
            self.log(f"   상점: 다가가기 {r}")
            self.events("shop", result=r)
            return {"result": r, "items": []}
        if not self.talk():
            r = self.approach()                            # the prompt didn't show — re-aim once
            if r != "ok" or not self.talk():
                self.log("   상점: 말 걸기 안 됨 (메뉴 안 열림)")
                self.events("shop", result="no_talk")
                return {"result": "no_talk", "items": []}
        try:
            for goods, want in items:
                row = self._item(goods, want)
                out["items"].append(row)
                if row["result"] == "shop_fail":
                    out["result"] = "shop_fail"
                    break
                if row["result"] != "ok" and out["result"] == "ok":
                    out["result"] = "partial"
        finally:
            if self.row is not None and not self.leave():
                self.log("   상점: 나가기 — 메뉴가 안 닫힘")
                out["closed"] = False
        return out

    def _item(self, goods: int, want: int) -> dict:
        if goods not in self.m["rows"]:
            row = {"goods": goods, "want": want, "bought": 0, "result": "not_sold"}
            self.log(f"   상점: {goods} — 이 상인 목록에 없음")
            self.events("shop", **row)
            return row
        r, price = self.m["rows"][goods]
        g0, s0 = self._counts(goods)
        n = min(want, s0 // price)
        if n <= 0:
            row = {"goods": goods, "want": want, "bought": 0, "souls0": s0, "souls1": s0, "result": "no_souls"}
            self.log(f"   상점: {goods} ×{want} — 소울 {s0} < {price}, 안 삼")
            self.events("shop", **row)
            return row
        if n < want:
            self.log(f"   상점: {goods} ×{want} → 소울 {s0}로 {n}개만")
        tries, got, spent = 0, 0, 0
        while tries < 2:
            tries += 1
            if self.row is None:                           # a miss left the list somewhere unknown — talk again
                if self.approach() != "ok" or not self.talk():
                    break
            got, spent = self._buy_one(goods, n, r, price)
            if got or spent:
                break
            self.log(f"   상점: {goods} ×{n} — 개수·소울 그대로 ({tries}번째) — 나갔다 다시 말 걸기")
            closed = self.leave()
            self.row = None                                # where the cursor is, we no longer know
            if not closed:
                break
        g1, s1 = self._counts(goods)
        result = ("ok" if got == n and spent == price * n else "shop_fail" if not got and not spent
                  else "mismatch" if got else "souls_only")
        row = {"goods": goods, "want": want, "asked": n, "bought": got, "price": price, "souls0": s0, "souls1": s1,
               "count0": g0, "count1": g1, "tries": tries, "result": result}
        self.log(f"   상점: {goods} ×{n} → {result} (개수 {g0}→{g1}, 소울 {s0}→{s1}, {tries}번)")
        self.events("shop", **row)
        return row


def parse_items(text: str) -> list[tuple[int, int]]:
    """'290:30,292:20' → [(290, 30), (292, 20)]"""
    out = []
    for part in (text or "").split(","):
        if part.strip():
            g, _, n = part.partition(":")
            out.append((int(g), int(n or 1)))
    return out
