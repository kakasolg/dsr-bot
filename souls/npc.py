"""Talking to an NPC — the part every NPC interaction shares (ROADMAP npc-module; [MoKa] 2026-10-12: NPC interaction is getting
important — talk / shop / later quests as one module). The Undead Merchant (souls/shop.Shop) is the first case; its steps
come from [win]'s record (docs/shop-undead-merchant.md):

  walk to the NPC's stand spot (or ≤ TALK_R) → face him within TALK_DEG (the talk prompt only shows while looking at him)
  → A → menu_open turns True → dialogue lines (an A during a line only advances it) until a menu shows → … → B until
  menu_open is False again.

What is NPC-specific stays with the caller: which screens count as "a menu" (Screen.state(), e.g. the shop's text masks) and
what to do in it (Shop.buy). An NPC is a dict like shop.UNDEAD_MERCHANT: npc (NpcParam id), pos, name, optional stand.

Only the merchant has been run in game (shop: [win] checks 10-12 · 11-02); a second NPC (Andre, quests) has not.
"""
from __future__ import annotations

import math
import time

import control
from souls import moves as M

B = control.B
A_, B_ = B.XUSB_GAMEPAD_A, B.XUSB_GAMEPAD_B

TALK_R = 1.7          # stand this close (shop record 03: the prompt showed at 1.7 m facing him, not at 1.2 m facing away)
TALK_DEG = 12.0       # … facing him this well
APPROACH_S = 6.0
STAND_R = 0.5         # this close to the NPC's "stand" counts as there
LINE_S = 2.5          # a dialogue line this long with no menu → A to advance it (greeting: 1–4 lines, [win] shop check 1)
LINES_MAX = 8
LEAVE_S = 9.0         # B, then wait for menu_open to go False — [win] 10-12: the farewell line keeps it True 6.1 s after the B
HOLD = 0.1
POLL = 0.1
GAP = 0.25            # spacing of repeated presses


class Npc:
    def __init__(self, mv, who: dict, nm=None, log=print, events=None, shoot=None, walk_to=None, screen=None, tag: str = "NPC"):
        """mv: souls.moves.Moves · who: the NPC dict · nm: NavMesh for the approach · shoot(tag): optional screenshot after a step
        · walk_to(goal, nm, tag) → 'arrived' …: Field.walk_to, only when the NPC is farther than a few metres · screen: .state()
        → the menu name the NPC shows now, or None (a dialogue line / the game) · tag: log prefix."""
        self.mv, self.tm, self.pad, self.nm = mv, mv.tm, mv.pad, nm
        self.log, self.events, self.m, self.shoot, self.walk_to = log, events or (lambda *a, **k: None), who, shoot, walk_to
        self.screen, self.tag = screen, tag

    # ── screen and buttons ────────────────────────────────────
    def _wait(self, want: tuple, secs: float) -> str | None:
        """Poll the screen until it is one of `want` → that state, else None."""
        t0 = time.time()
        while True:
            st = self.screen.state()
            if st in want:
                return st
            if time.time() - t0 >= secs:
                return None
            time.sleep(POLL)

    def _press(self, button, wait: float, tag: str = "", n: int = 1, gap: float = GAP) -> None:
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

    # ── finding and facing ────────────────────────────────────
    def find(self, s):
        return next((c for c in (s.chars if s else ()) if c.npc_param == self.m["npc"]), None)

    def hostile(self, c) -> str | None:
        """Why this NPC must not be approached (→ no input), or None.
        ── 맞은 NPC = 적대로 봄 (P-155, 20261110_061503) ──────────────────────────
         · 시작 준비 중 누군가의 약공 2번으로 상인 HP 360 → 216, 적대. 그 뒤 walk_to가 그를 '따라온 적'으로 싸워 죽임.
         · team은 맞기 전후 모두 6이라 못 씀 → HP가 최대보다 낮거나 공격 애니(3000번대)면 다가가지 않고 멈춤.
         · 다쳤지만 적대는 아닌 NPC도 멈춤 (구분 못 함) — 사람이 보고 정함.
        """
        hp, mx, anim = getattr(c, "hp", None), getattr(c, "max_hp", None), getattr(c, "anim", -1)
        if hp is not None and mx and hp < mx:
            return f"HP {hp}/{mx}"
        if anim is not None and 3000 <= anim < 4000:
            return f"공격 애니 {anim}"
        return None

    def approach(self) -> str:
        """Within TALK_R of the NPC (or on its stand spot), facing it within TALK_DEG. → 'ok' | 'not_found' | 'far' |
        'not_facing' | 'hostile' (hurt or attacking: nothing pressed) | a walk result"""
        s = self.mv.snap(30.0)
        c = self.find(s)
        why = self.hostile(c) if c is not None else None
        if why:
            self.log(f"   {self.tag}: {self.m['name']} 다쳤거나 적대 ({why}) — 다가가지 않음, 입력 없음 (P-155)")
            return "hostile"
        self.pad.neutral()
        if c is None:
            return "not_found"
        # ── 상자 사이에 앉은 상인 ([win] 11-02 try 12) ──────────────────────────────
        #  그의 몸 중심으로 걸으면 상자에 막혀 3.7 m에서 timeout × 4 → not_facing. 기록된 서는 자리(1.74 m)로 간다
        stand = self.m.get("stand")
        goal = stand or (c.x, c.y, c.z)
        d = M.horiz(s.player, c)
        far = math.hypot(s.player.x - goal[0], s.player.z - goal[2]) > STAND_R if stand else d > 4.0
        if far and d > TALK_R:
            if self.walk_to is None:
                return "far"
            r = self.walk_to(goal, self.nm, self.m["name"])
            if r not in ("arrived", "stuck", "unreachable", "timeout"):
                return r
            c2 = self.find(self.mv.snap(30.0))              # hit on the way (a walk fight can swing next to him) → stop here
            if c2 is not None and self.hostile(c2):
                self.pad.neutral()
                self.log(f"   {self.tag}: {self.m['name']} 걷는 동안 다침 ({self.hostile(c2)}) — 멈춤 (P-155)")
                return "hostile"
        t0 = time.time()
        while time.time() - t0 < APPROACH_S:                # short steps in — a sitting NPC: walking into him is harmless
            s = self.mv.snap(30.0)
            c = self.find(s)
            if c is None:
                return "not_found"
            d = M.horiz(s.player, c)
            if d <= TALK_R or (stand and math.hypot(s.player.x - stand[0], s.player.z - stand[2]) <= STAND_R):
                break
            gx, gz = stand[0] if stand else c.x, stand[2] if stand else c.z
            self.pad.move(*self.mv.stick_to(s, gx, gz, 0.35))
            time.sleep(min(0.25, 0.08 + (d - TALK_R) * 0.15))
            self.pad.move(0.0, 0.0)
            time.sleep(0.15)
        self.pad.move(0.0, 0.0)
        off = self.mv.aim(c.ptr, deg=TALK_DEG, timeout=3.0)  # taps that turn without walking (face() would push the stick)
        s = self.mv.snap(30.0)
        c = self.find(s)
        d = M.horiz(s.player, c) if c is not None else None
        self.log(f"   {self.tag}: {self.m['name']} {d if d is None else round(d, 2)} m, 몸 {off if off is None else round(off)}°")
        if c is None or d > TALK_R + 0.4 or off is None or abs(off) > TALK_DEG:
            return "not_facing"
        return "ok"

    # ── talking ───────────────────────────────────────────────
    def greet(self, menus: tuple) -> str | None:
        """A → menu_open → dialogue lines (A advances a line) until the screen is one of `menus` → that menu.
        None if the conversation never opened (no talk prompt) or no menu showed within LINES_MAX lines."""
        self._press(A_, 0.0, "")
        t0 = time.time()
        while time.time() - t0 < 1.5:
            if self.tm.menu_open():
                break
            time.sleep(0.05)
        else:
            return None
        for line in range(LINES_MAX):
            st = self._wait(menus, LINE_S)
            if st:
                return st
            self._press(A_, 0.0, f"line-{line + 1}")      # still a line of dialogue → next line
        return None

    def close(self, tag: str = "close") -> bool:
        """From the NPC's top menu: B → farewell → game; wait for menu_open False (B again if a line still holds it). → closed"""
        self._press(B_, 0.0, tag)
        t0 = time.time()
        while time.time() - t0 < LEAVE_S:
            if not self.tm.menu_open():
                time.sleep(0.5)
                return True
            if time.time() - t0 > 3.0:
                self._press(B_, 0.5)                       # still in a line of dialogue
            time.sleep(0.1)
        return False
