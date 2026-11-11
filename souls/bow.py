"""Bow — skeleton only (ROADMAP bow, [MoKa] 2026-10-12: firebombs and a bow from the Undead Merchant make the game much easier;
"after the firebomb"). Nothing here runs in a bot run yet: no run.py command or flag calls it.

Steps, as the ROADMAP line has them: buy → switch shield ↔ bow → locked-on shot → measure. What is known and what isn't:

  buy      not built. The merchant's list was only ever seen on its first tab (consumables, docs/shop-undead-merchant.md "활
           (다른 상인 탭?)"); whether he sells a bow and how the tabs are switched is unrecorded → [win] screenshots first.
  switch   left-hand slot cycling with D-pad ←, checked in memory after each press (like Moves.select_item does for items).
           LEFT_WEAPON_OFF / LEFT_SLOT_OFF are **candidates**: right_weapon() reads slot k at PlayerGameData+0x328 + 8k with the
           slot in hand at +0x310 (dsr_telemetry, checked 09-28); the left hand interleaved one i32 before (+0x324 + 8k, slot
           index +0x30C) is the usual DS1 layout, never read in this game.
  shot     lock on (Moves.lock_target) → L1 with the bow in the left hand. Which button fires a left-hand bow, and whether the
           shot follows lock-on without aiming, are unmeasured.
  measure  per shot: distance, lock, damage, the foe woke or not, arrows left (ARROW_OFF candidate) — the same fields the knife
           and firebomb throws log (docs/throwables.md), so the three can be compared.

BOW_IDS are DS1 weapon param ids (names from the param tables), not yet seen in this game's memory.
"""
from __future__ import annotations

import time

import control
from souls import moves as M

B = control.B
SWITCH_LEFT = B.XUSB_GAMEPAD_DPAD_LEFT
FIRE = B.XUSB_GAMEPAD_LEFT_SHOULDER          # candidate: L1 fires a bow held in the left hand (unmeasured)

BOW_IDS = {1200000: "Short Bow", 1201000: "Longbow", 1202000: "Black Bow of Pharis", 1203000: "Composite Bow"}   # candidates
LEFT_SLOT_OFF = 0x30C                        # candidate — left slot in hand (0 / 1), cf. right +0x310
LEFT_WEAPON_OFF = 0x324                      # candidate — left slot k id at +0x324 + 8k, cf. right +0x328 + 8k
ARROW_OFF = 0x334                            # candidate — arrow slot 1 id
SWITCH_TRIES = 3                             # a hand holds 2 slots (+ bare) — 3 presses go round once
SWITCH_WAIT = 0.6
SHOT_WATCH = 1.8


def _pgd(tm):
    cb = tm.q(tm.static["ChrClassBase"])
    return tm.q(cb + 0x10) if cb else None


def left_weapon(tm) -> int | None:
    """Left-hand weapon id in hand (candidate offsets — see the module note). None if unreadable."""
    pgd = _pgd(tm)
    if not pgd:
        return None
    k = tm.i32(pgd + LEFT_SLOT_OFF)
    return tm.i32(pgd + LEFT_WEAPON_OFF + 8 * (k if k in (0, 1) else 0))


class Bow:
    def __init__(self, mv: M.Moves, log=print, events=None, read_left=left_weapon):
        self.mv, self.tm, self.pad, self.log = mv, mv.tm, mv.pad, log
        self.events = events or (lambda *a, **k: None)
        self.read_left = read_left

    def in_hand(self) -> bool | None:
        w = self.read_left(self.tm)
        return None if w is None else w in BOW_IDS

    def switch(self, want_bow: bool = True) -> str:
        """D-pad ← until the left hand holds (or no longer holds) a bow, checked in memory after each press.
        → 'ok' | 'unreadable' (the left-hand read failed — don't press blind) | 'not_found' (went round, no bow in a slot)"""
        now = self.in_hand()
        if now is None:
            return "unreadable"
        for n in range(SWITCH_TRIES):
            if now == want_bow:
                return "ok"
            self.pad.press(SWITCH_LEFT, 0.08)
            time.sleep(SWITCH_WAIT)
            now = self.in_hand()
            if now is None:
                return "unreadable"
        return "ok" if now == want_bow else "not_found"

    def shoot(self, ptr) -> dict:
        """One locked-on shot at ptr. Never fires without lock-on (a knife thrown unlocked hit 0/8 — throwables.md).
        → {"ok": fired, "locked", "hit": damage, "dist", "why"}"""
        if self.in_hand() is not True:
            return {"ok": False, "locked": False, "why": "활이 손에 없음"}
        s = self.mv.snap(40.0)
        c = self.mv.find(s, ptr)
        if c is None:
            return {"ok": False, "locked": False, "why": "그놈 없음"}
        dist = round(M.horiz(s.player, c), 1)
        if not self.mv.lock_target(ptr):
            return {"ok": False, "locked": False, "dist": dist, "why": "락온 안 됨"}
        hp0 = c.hp
        self.pad.press(FIRE, 0.1)
        t0, hit = time.time(), 0
        while time.time() - t0 < SHOT_WATCH:
            c = self.mv.find(self.mv.snap(40.0), ptr)
            if c is None or c.hp < hp0:
                hit = hp0 - (c.hp if c is not None else 0)
                break
            time.sleep(0.05)
        r = {"ok": True, "locked": True, "hit": hit, "dist": dist, "why": None}
        self.log(f"   활: {dist} m, 락온 → 피해 {hit}")
        self.events("bow", **r)
        return r
