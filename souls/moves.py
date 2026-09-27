"""Layer 1 — basic moves. Knows **only buttons and timing**: what to press, and when.
Whom to hit·when to drink·where to go is decided by the layers above. This layer knows neither weapons nor enemies (weapon values come in as arguments).

Rules that live only in this layer (not repeated elsewhere):
  · Attack buttons (R1·R2) go 0.16 s after releasing the stick — enforced by control.Pad. Forward+R1 = kick, forward+R2 = jump attack (control chart)
  · Sprint (B hold) is kept for a whole path — releasing B at each point makes a 'short B' = roll·backstep·(while running) jump (nav.follow)
  · No jumping (user)
  · Estus: after selecting the item slot, re-check safety **then** drink. Success is judged by whether the count dropped
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

import control
import farm
import nav
import quitout

ATTACK = range(3000, 3500)       # enemy attack anims (common to DS1 humanoids)
GUARD_BROKEN = 9600              # guard broken, staggered (after kicking a shield soldier) — an opening
STAGGER = range(3500, 3600)      # stagger — bounced off my shield etc. **An opening, not an attack** (2026-09-24: treating this as an attack made it just guard for 12 s)
DOWNED = range(9900, 10000)      # knocked down·lying·getting up (9920 = getting up)
GETTING_UP = 9920
ESTUS_IDS = range(200, 216)      # Estus item ID varies by upgrade level (new character 201)
ITEM_DARKSIGN = 117
ITEM_KNIFE = 290                 # throwing knife (must be in a quick slot to be selectable)
ITEM_FIREBOMB = 292              # firebomb — emergencies only (user: 50 souls, 'a bomb is better than dying'). id from the DS1 goods table, not yet measured
PHANTOM_SWINGS = 3                # this many whiffs (in reach·0 damage·not moving) → treat as a phantom
OTHERS_R = 3.5                    # radius for checking who else got hit by a horizontal slash
REPAIR_POWDER = 280               # repair powder item ID
SECOND_R1_AT = 0.45              # light double hit: press again this long after the first R1 (input buffer)
BS_TO_R1 = 0.45                  # backstep attack: R1 this long after B (measured in old hunt.backstep_attack) — lunges 1.7~2.8 m forward
KICK_TO_R1 = 0.6                 # R1 at latest this long after the kick (or the moment it lands) — shield soldier hit 9600 at 0.45~0.61 s
B = control.B


@dataclass
class Hit:
    """Result of one attack (including chained hits)."""
    kind: str                     # light | heavy | kick
    presses: int = 0
    dmg: int = 0                  # target HP loss
    dead: bool = False            # target HP 0 (vanishing from the list also counts as dead)
    taken: int = 0                # HP I lost meanwhile
    e_anims: list = field(default_factory=list)
    my_anims: list = field(default_factory=list)
    skipped: str | None = None
    others: int = 0               # number of non-target enemies whose HP also dropped (Claymore horizontal slash — user: "nearby enemies take damage too")

    def as_dict(self) -> dict:
        return dict(self.__dict__)


def horiz(p, c) -> float:
    return math.hypot(c.x - p.x, c.z - p.z)


def rel_angle(p, c) -> float:
    """How many rad c is off my facing (−π..π, + is right). Measured: world yaw = heading + π. (old patrol.rel_angle — moved to layer 1)"""
    fwd = p.heading + math.pi
    return (math.atan2(c.x - p.x, c.z - p.z) - fwd + math.pi) % (2 * math.pi) - math.pi


class Moves:
    def __init__(self, tm, pad: control.Pad):
        self.tm, self.pad = tm, pad
        self._estus: int | None = None
        self._zero: dict = {}    # ptr → number of in-reach swings that ended with 0 damage (_phantom_check)
        self.weapon = None       # layer 2 weapons.Weapon — light attack timing (chain_at·guard·watch) differs per weapon. Set by run.py
        self.guard_ok = True     # False = never raise the shield (backstep style. User: "Don't guard when backstepping — dodge and attack, keep it simple")
        self.cam_target = None   # enemy ptr for the camera to face — set by layer 4 (field.fight·lure), followed by camera.CamFollow
        self.cam_busy = False    # this layer is using the camera directly (knife lock-on) — CamFollow stays hands off
        # what layer 4 is doing, for viewers only (radar.py reads these; nothing in the bot reads them back)
        self.show_path = None    # (tag, [(x, y, z), ...]) while field.walk follows a path
        self.show_spot = None    # (tag, (x, y, z), time) — last spot field._hold_at held
        self.show_smash = None   # (prop name, (x, y, z), time) — last prop field._smash_blocking swung at

    # ── Camera ───────────────────────────────────────────────
    # User 2026-09-26: "This game has auto lock-on, so … press the right stick again to release, point the camera at the enemy you want, press the stick".
    # R3 grabs the enemy nearest the camera center — turning only the body and pressing R3 twice still re-locked the neighbor (clear-ramp 090241, #3 instead of #2 shield soldier).
    # Which way cam_yaw turns when pushing right stick x positive is not yet measured, so it is learned from the first pulse.
    LOOK_SIGN: int | None = None

    def cam_err(self, s, x: float, z: float) -> float | None:
        """Angle (°) from camera forward (cam_yaw + nav.YAW_OFFSET — same rule as world_to_stick) to (x, z)."""
        if s is None or s.cam_yaw is None:
            return None
        ang = math.atan2(x - s.player.x, z - s.player.z)
        return math.degrees((ang - (s.cam_yaw + nav.YAW_OFFSET) + math.pi) % (2 * math.pi) - math.pi)

    def look_pulse(self, err: float, dur: float = 0.06) -> None:
        """One short right-stick pulse toward err. If the sign is unknown, learn it from this pulse."""
        if Moves.LOOK_SIGN is None:
            s0 = self.snap(5.0)
            self.pad.look(0.6, 0.0)
            time.sleep(0.08)
            self.pad.look(0.0, 0.0)
            time.sleep(0.12)
            s1 = self.snap(5.0)
            if s0 and s1 and s0.cam_yaw is not None and s1.cam_yaw is not None:
                d = (s1.cam_yaw - s0.cam_yaw + math.pi) % (2 * math.pi) - math.pi
                if abs(d) > math.radians(0.5):
                    Moves.LOOK_SIGN = 1 if d > 0 else -1
            return
        mag = min(1.0, max(0.35, abs(err) / 60.0))
        self.pad.look(Moves.LOOK_SIGN * (1 if err > 0 else -1) * mag, 0.0)
        time.sleep(dur)
        self.pad.look(0.0, 0.0)

    def look_at(self, ptr, tol: float = 5.0, timeout: float = 1.5) -> float | None:
        """Turn the camera toward the target (right stick). While locked on the right stick switches targets, so unlock before calling. → last remaining offset (°)."""
        t, err = time.time(), None
        while time.time() - t < timeout:
            s = self.snap(40.0)
            c = self.find(s, ptr)
            if c is None:
                return None
            err = self.cam_err(s, c.x, c.z)
            if err is None or abs(err) <= tol:
                break
            self.look_pulse(err, 0.08 if abs(err) > 30 else 0.04)
            time.sleep(0.06)
        self.pad.look(0.0, 0.0)
        return err

    # ── Observing ────────────────────────────────────────────────
    def snap(self, within: float = 40.0):
        return self.tm.snapshot(within=within)

    @staticmethod
    def find(s, ptr):
        return next((x for x in s.chars if x.ptr == ptr), None) if s else None

    def stick_to(self, s, x: float, z: float, scale: float = 1.0) -> tuple[float, float]:
        st = control.world_to_stick(x - s.player.x, z - s.player.z, s.cam_yaw, nav.YAW_OFFSET, nav.FLIP_X)
        return st[0] * scale, st[1] * scale

    # ── Turning ─────────────────────────────────────────────
    def face(self, s, c, deg: float = 20.0) -> bool:
        """Aim without lock-on (user: DS1 experts don't use lock-on). If the body is off the target by more than deg, nudge the stick that way → False.
        Within it, release the stick and True (the stick wait for attack buttons is handled by Pad)."""
        p = s.player
        if p.heading is None or s.cam_yaw is None:
            return False
        if abs(math.degrees(rel_angle(p, c))) > deg:
            self.pad.move(*self.stick_to(s, c.x, c.z, 0.55))     # at 0.35 it barely turned with the shield up
            return False
        self.pad.move(0.0, 0.0)
        return True

    def guard(self, on: bool) -> None:
        self.pad.guard(on and self.guard_ok)

    # ── Attacks ─────────────────────────────────────────────────
    def _watch(self, hit: Hit, ptr, hp0: int, ehp0: int, secs: float, on_tick=None, early_exit=None) -> None:
        t1 = time.time()
        my_min, e_min = hp0, ehp0
        s0 = self.snap(4.0)
        side0 = {c.ptr: c.hp for c in s0.hostile(OTHERS_R)} if s0 else {}
        side0.pop(ptr, None)
        side_min = dict(side0)
        while time.time() - t1 < secs:
            self.pad.release_due()
            if on_tick is not None:
                on_tick(time.time() - t1, hit)
            s2 = self.snap(10.0)
            if s2:
                my_min = min(my_min, s2.player.hp)
                c2 = self.find(s2, ptr)
                e_min = 0 if c2 is None else min(e_min, c2.hp)
                for x in s2.chars:
                    if x.ptr in side_min:
                        side_min[x.ptr] = min(side_min[x.ptr], x.hp)
                if c2 is not None and (not hit.e_anims or hit.e_anims[-1][1] != c2.anim):
                    hit.e_anims.append((round(time.time() - t1, 2), c2.anim))
                if not hit.my_anims or hit.my_anims[-1][1] != s2.player.anim:
                    hit.my_anims.append((round(time.time() - t1, 2), s2.player.anim))
                if e_min <= 0:
                    break
                # once an attack anim has played and returned to -1 (standing) with nothing left to press, finish — avoids waiting out the rest blind
                if (early_exit is not None and early_exit(time.time() - t1, hit) and len(hit.my_anims) >= 2
                        and hit.my_anims[-1][1] in (-1, None)):
                    break
            time.sleep(0.01)
        hit.dmg, hit.dead, hit.taken = ehp0 - e_min, e_min <= 0, hp0 - my_min
        hit.others = sum(1 for k, v in side0.items() if side_min[k] < v)

    def light(self, s, c, n: int = 1, sp_second: int = 40) -> Hit:
        """Light attack (R1) n times (1 or 2). The second at SECOND_R1_AT after the first R1, only if stamina exceeds sp_second.
        The shield goes up after the last attack anim starts (so the second R1 isn't overridden by guard)."""
        hit = Hit("light")
        ptr, hp0, ehp0 = c.ptr, s.player.hp, c.hp
        w = self.weapon
        chain = w.chain_at if w else SECOND_R1_AT
        g1, g2 = (w.guard1, w.guard2) if w else (0.35, SECOND_R1_AT + 0.6)
        w1, w2 = (w.watch1, w.watch2) if w else (0.9, 1.5)
        # With a shield, attack while **holding** LB — guard → attack → guard is seamless (user 2026-09-25: "It has to be natural").
        # Measured (Claymore, whiffing): holding LB ends the swing right at the cancel frame (1.39 s) and the shield comes back up on its own.
        # Releasing and re-pressing stretches the motion to 2.67 s, and mistimed re-presses leave the shield down. Cost: stamina regenerates slowly with the shield up.
        hold = self.guard_ok
        self.pad.guard(hold)
        self.pad.tap(B.XUSB_GAMEPAD_RIGHT_SHOULDER, 0.06)      # stick wait is handled by Pad
        hit.presses = 1
        want_second = n >= 2 and (s.player.sp or 0) >= sp_second
        state = {"second": not want_second, "guard": hold}

        def tick(t, h):
            if not state["second"] and t >= chain:
                state["second"] = True
                if not h.dead:
                    self.pad.tap(B.XUSB_GAMEPAD_RIGHT_SHOULDER, 0.06)
                    h.presses = 2
            # shield 0.6 s (0.35 s for a single hit) after the last R1 — pressing LB earlier can override the buffered R1 with guard
            if not state["guard"] and state["second"] and t >= (g2 if h.presses == 2 else g1):
                state["guard"] = True
                self.guard(True)
        # when holding, the game signals the end — exit as soon as my anim returns to -1 (cancel frame)
        exit_at = (lambda t, h: state["second"] and t > chain + 0.1) if hold else \
                  (lambda t, h: state["second"] and t > (g2 - 0.3 if h.presses == 2 else g1 - 0.05))
        self._watch(hit, ptr, hp0, ehp0, w2 if want_second else w1, tick, early_exit=exit_at)
        self.pad.move(0.0, 0.0)
        self._phantom_check(s, c, hit)
        return hit

    def _phantom_check(self, s, c, hit: Hit) -> None:
        """Swung in reach but 0 damage, the target never moved and has full HP — after PHANTOM_SWINGS times it's a bodiless one.
        Layer 0's "bodies overlap" (dsr_telemetry.PHANTOM_R) only triggers within 0.45 m, so it hit phantom 254013 standing at 0.6 m for 9 s
        and then fell off the edge of the bonfire room (2026-09-25 183328)."""
        reach = self.weapon.reach if self.weapon else 1.2
        still = all(a in (-1, None) for _t, a in hit.e_anims)
        if hit.dmg == 0 and still and c.hp >= c.max_hp and horiz(s.player, c) <= reach:
            n = self._zero.get(c.ptr, 0) + 1
            self._zero[c.ptr] = n
            if n >= PHANTOM_SWINGS and hasattr(self.tm, "phantom"):
                self.tm.phantom.add(c.ptr)
        else:
            self._zero.pop(c.ptr, None)

    def heavy(self, s, c) -> Hit:
        """Heavy attack (R2) — press with the stick released (forward+R2 is a jump attack). Called by upper layers only when the weapon uses heavies."""
        hit = Hit("heavy", presses=1)
        ptr, hp0, ehp0 = c.ptr, s.player.hp, c.hp
        # with a shield, hold LB like the light attack — the shield comes up on its own at the end (Claymore measured: ends 1.65 s, shield 1.67 s)
        hold = self.guard_ok
        self.pad.guard(hold)
        self.pad.heavy()
        if hold:
            self._watch(hit, ptr, hp0, ehp0, 2.0, early_exit=lambda t, h: t > 1.0)
        else:
            self._watch(hit, ptr, hp0, ehp0, 1.3,
                        lambda t, h: self.guard(True) if t > 0.9 else None)
        return hit

    def kick(self, s, c) -> Hit:
        """Kick = stick toward the target + R1 in the same input (control.kick). Breaks a shield guard (wiki: guarding enemies stagger)."""
        hit = Hit("kick", presses=1)
        ptr, hp0, ehp0 = c.ptr, s.player.hp, c.hp
        self.pad.guard(False)
        st = self.stick_to(s, c.x, c.z) if s.cam_yaw is not None else (0.0, 1.0)
        self.pad.kick(*st)
        t0 = time.time()
        while time.time() - t0 < 0.12:
            self.pad.release_due()
            time.sleep(0.01)
        self.pad.move(0.0, 0.0)
        self._watch(hit, ptr, hp0, ehp0, 1.2)
        return hit

    def kick_combo(self, s, c, n: int = 2) -> Hit:
        """Kick → n light hits right as the guard breaks (one move, bypasses the decision loop).
        User: "The gap between the kick and the attack is too long, the shield soldier guards again and it fails" — the kick lands and 9600 (guard broken)·9920
        happens at 0.45~0.6 s, but watching the kick result for 1.2 s then aligning and deciding delayed the light attack by over 1.5 s.
        R1 when the target anim changes from -1 (hit) or at latest at KICK_TO_R1 — R1 pressed before the kick motion ends goes into the buffer."""
        hit = Hit("kick+light", presses=1)
        ptr, hp0, ehp0 = c.ptr, s.player.hp, c.hp
        self.pad.guard(False)
        st = self.stick_to(s, c.x, c.z) if s.cam_yaw is not None else (0.0, 1.0)
        self.pad.kick(*st)
        t0 = time.time()
        while time.time() - t0 < 0.12:
            self.pad.release_due()
            time.sleep(0.01)
        self.pad.move(0.0, 0.0)
        state = {"r1": 0, "broke_t": None}

        def tick(t, h):
            if state["broke_t"] is None and h.e_anims and h.e_anims[-1][1] not in (-1, None) and t > 0.2:
                state["broke_t"] = t                       # the kick landed (9600 guard broken / 9920 etc.)
            due = state["broke_t"] is not None or t >= KICK_TO_R1
            if due and state["r1"] < n and t >= (state["broke_t"] or KICK_TO_R1) + state["r1"] * (self.weapon.chain_at if self.weapon else SECOND_R1_AT):
                if not h.dead:
                    self.pad.tap(B.XUSB_GAMEPAD_RIGHT_SHOULDER, 0.06, stick_ok=True)   # stick already released
                    state["r1"] += 1
                    h.presses = 1 + state["r1"]
            if state["r1"] >= n and t >= (state["broke_t"] or KICK_TO_R1) + n * (self.weapon.chain_at if self.weapon else SECOND_R1_AT) + 0.3:
                self.guard(True)
        self._watch(hit, ptr, hp0, ehp0, 2.4, tick,
                    early_exit=lambda t, h: state["r1"] >= n and t > (state["broke_t"] or KICK_TO_R1) + n * (self.weapon.chain_at if self.weapon else SECOND_R1_AT) + 0.3)
        self._phantom_check(s, c, hit)          # count kick combos too — counting only light attacks alternated with the phantom and stalled at 2
        return hit

    def backstep(self) -> None:
        """Stick neutral + tap B. DS1 registers on B release — press 0.1 s after releasing the stick (otherwise it rolls)."""
        self.pad.release_stick()
        self.pad.guard(False)
        self.pad.tap(B.XUSB_GAMEPAD_B, 0.06)
        t0 = time.time()
        while time.time() - t0 < 0.7:
            self.pad.release_due()
            time.sleep(0.02)

    def backstep_attack(self, s, c, nm=None) -> Hit:
        """Backstep + R1 as **one move** (user 2026-09-24: "Backstep then attack must not be two moves, it has to be one").
        Stick neutral → B → R1 after BS_TO_R1. Needs floor 2.6 m behind·3.0 m ahead (it lunges forward). Body must face the target within 40°."""
        hit = Hit("bsattack", presses=0)
        p = s.player
        if p.heading is None:
            hit.skipped = "heading 없음"
            return hit
        if nm is not None:
            back = (math.sin(p.heading), math.cos(p.heading))
            if not nav.ground_ahead(nm, p, back[0], back[1], reach=2.6):
                hit.skipped = "뒤에 바닥 없음"
                return hit
            if not nav.ground_ahead(nm, p, -back[0], -back[1], reach=2.2):
                hit.skipped = "앞에 바닥 없음"
                return hit
        if abs(math.degrees(rel_angle(p, c))) > 40:
            hit.skipped = "몸이 딴 데"
            return hit
        return self.combo("backstep_r1", s, c, nm=None)   # floor already checked above

    # ── Combo = sequence (user 2026-09-24: "Make attack combos a single sequence — roll light, jump heavy, backstep light, like that") ──
    # one row = (time s, action). Actions: "stick_fwd" stick toward target | "stick_off" release stick | "B" | "R1" | "R2" (trigger)
    # times: steps before B are relative to start, **steps after B are relative to the moment B was pressed** (so gaps hold even with the 0.16 s stick-release wait)
    # results observed with a single _watch. Add a new combo as one row here; upper layers call it by name only.
    COMBOS = {
        "backstep_r1": ((0.0, "stick_off"), (0.0, "B"), (BS_TO_R1, "R1")),                 # backstep light — lunges 1.7~2.8 m forward
        "roll_r1":     ((0.0, "stick_fwd"), (0.3, "B"), (0.55, "R1")),                      # roll light — R1 0.55 s after B (post-B times are relative to B)
        "jump_r2":     ((0.0, "stick_fwd"), (0.1, "R2"), (0.25, "stick_off")),             # jump heavy — forward+R2 (control chart)
    }
    COMBO_WATCH = {"backstep_r1": BS_TO_R1 + 1.1, "roll_r1": 2.0, "jump_r2": 1.8}

    def combo(self, name: str, s, c, nm=None, need_back: float = 0.0, need_front: float = 3.0) -> Hit:
        """One combo as one move. Floor check: need_back m behind·need_front m ahead (roll·jump move forward)."""
        hit = Hit(name, presses=0)
        p = s.player
        if p.heading is None or s.cam_yaw is None:
            hit.skipped = "heading 없음"
            return hit
        if nm is not None:
            back = (math.sin(p.heading), math.cos(p.heading))
            if need_back and not nav.ground_ahead(nm, p, back[0], back[1], reach=need_back):
                hit.skipped = "뒤에 바닥 없음"
                return hit
            if need_front and not nav.ground_ahead(nm, p, c.x - p.x, c.z - p.z, reach=need_front):
                hit.skipped = "앞에 바닥 없음"
                return hit
        if abs(math.degrees(rel_angle(p, c))) > 40:
            hit.skipped = "몸이 딴 데"
            return hit
        steps = list(self.COMBOS[name])
        hp0, ehp0 = p.hp, c.hp
        self.pad.guard(False)
        fwd = self.stick_to(s, c.x, c.z)
        state = {"i": 0}

        def do(act):
            if act == "stick_fwd":
                self.pad.move(*fwd)
            elif act == "stick_off":
                self.pad.move(0.0, 0.0)
                self.pad.release_stick()
            elif act == "B":
                self.pad.tap(B.XUSB_GAMEPAD_B, 0.06, stick_ok=True)
                hit.presses += 1
            elif act == "R1":
                self.pad.tap(B.XUSB_GAMEPAD_RIGHT_SHOULDER, 0.06, stick_ok=True)
                hit.presses += 1
            elif act == "R2":
                self.pad._r2(0.12)
                hit.presses += 1

        # times are **relative to the moment B was pressed** — with absolute times R1 moved earlier by the stick-release wait (0.16 s), turning 0.45 into 0.29 (caught by moves_test)
        state["anchor"] = None

        t_start = time.time()

        def tick(t, h):
            while state["i"] < len(steps):
                st_t, act = steps[state["i"]]
                now = time.time()                          # _watch's t is the tick start time and misses the wait inside do() (0.16 s) — use real time
                base = state["anchor"] if (state["anchor"] is not None and st_t > 0) else t_start
                if now - base < st_t:
                    break
                do(act)
                if act == "B" and state["anchor"] is None:
                    state["anchor"] = time.time()          # post-B step times are relative to the moment B was pressed
                state["i"] += 1
        self._watch(hit, c.ptr, hp0, ehp0, self.COMBO_WATCH[name] + 0.3, tick,
                    early_exit=lambda t, h: state["i"] >= len(steps) and time.time() > (state["anchor"] or t_start) + steps[-1][0] + 0.4)
        self.pad.move(0.0, 0.0)
        return hit

    def roll_toward(self, s, x: float, z: float) -> None:
        """Stick that way + tap B = roll (breaking boxes etc.)."""
        self.pad.move(*self.stick_to(s, x, z))
        time.sleep(0.3)                                      # time to turn the body
        self.pad.dodge()
        t0 = time.time()
        while time.time() - t0 < 1.2:
            self.pad.release_due()
            time.sleep(0.02)
        self.pad.move(0.0, 0.0)
        time.sleep(0.2)

    # ── Items ───────────────────────────────────────────────
    def estus_id(self) -> int | None:
        """Item ID of the Estus currently held (cached once found, re-searched when the count hits 0)."""
        if self._estus is not None and self.tm.goods_count(self._estus):
            return self._estus
        self._estus = next((i for i in ESTUS_IDS if self.tm.goods_count(i)), None)
        return self._estus

    def estus_left(self) -> int:
        e = self.estus_id()
        return (self.tm.goods_count(e) or 0) if e is not None else 0

    def select_item(self, item: int, timeout: float = 3.0) -> bool:
        t0 = time.time()
        while self.tm.selected_item() != item and time.time() - t0 < timeout:
            self.pad.item_next()
            t1 = time.time()
            while time.time() - t1 < 0.35:
                self.pad.release_due()
                time.sleep(0.01)
        return self.tm.selected_item() == item

    def drink(self, safe) -> dict:
        """One sip of Estus. Only when safe(snapshot) is true — selecting the slot takes up to 3 s, so check **again after selecting**.
        → {"ok": did the count drop, "hp": [before, after], "left": remaining count, "why": reason it couldn't drink}"""
        e = self.estus_id()
        if e is None:
            return {"ok": False, "why": "에스트 없음"}
        if not self.select_item(e):
            return {"ok": False, "why": "에스트 칸을 못 고름"}
        s = self.snap(15.0)
        if s is None or not safe(s):
            return {"ok": False, "why": "칸 고르는 사이 적이 옴"}
        n0, hp0 = self.tm.goods_count(e) or 0, s.player.hp
        self.pad.guard(False)
        self.pad.neutral()
        self.pad.use_item()
        t0 = time.time()
        while time.time() - t0 < 2.2:
            self.pad.release_due()
            time.sleep(0.02)
        s2 = self.snap(10.0)
        n1 = self.tm.goods_count(e) or 0
        return {"ok": n1 < n0, "hp": [hp0, s2.player.hp if s2 else None], "left": n1,
                "why": None if n1 < n0 else "끊김 (개수 그대로)"}

    def repair(self, safe) -> dict:
        """Repair powder (280) — must be in a quick slot (user 2026-09-25: "I put repair powder in the quick slot, use it from now on").
        Same order as drink: select slot → re-check safety → use → did the count drop and durability rise."""
        if REPAIR_POWDER not in self.tm.quick_items():
            return {"ok": False, "why": "퀵슬롯에 수리 분말 없음"}
        if not self.select_item(REPAIR_POWDER):
            return {"ok": False, "why": "수리 분말 칸을 못 고름"}
        s = self.snap(15.0)
        if s is None or not safe(s):
            return {"ok": False, "why": "칸 고르는 사이 적이 옴"}
        n0, d0 = self.tm.goods_count(REPAIR_POWDER) or 0, self.tm.weapon_durability()
        self.pad.guard(False)
        self.pad.neutral()
        self.pad.use_item()
        t0 = time.time()
        while time.time() - t0 < 3.0:
            self.pad.release_due()
            time.sleep(0.02)
        n1, d1 = self.tm.goods_count(REPAIR_POWDER) or 0, self.tm.weapon_durability()
        e = self.estus_id()
        if e is not None:
            self.select_item(e)                  # switch back to the Estus slot — so it does not use repair powder in an emergency
        return {"ok": n1 < n0, "dur": [d0, d1], "left": n1, "why": None if n1 < n0 else "안 씀 (개수 그대로)"}

    def darksign(self, bonfire_stand) -> bool:
        """Darksign — lose all souls·humanity and return to the last rested bonfire. Press A **only after confirming** the slot (117)·dialog text·YES option
        (YES is the default). After pressing A, **never use it again** even if the result can't be read (merchantrun measured: it arrived, reported 'failed', and used it again).
        Whether to use it is decided by upper layers (only when there's almost nothing to lose — user 2026-09-24 "Let's use the Darksign")."""
        import env
        for _ in range(3):
            s0 = self.snap(5.0)
            pre = (s0.player.x, s0.player.y, s0.player.z) if s0 else None
            self.pad.guard(False)
            self.pad.neutral()
            quitout.close_menu(self.tm, self.pad)
            if not self.select_item(ITEM_DARKSIGN):
                continue
            quitout._press(self.pad, B.XUSB_GAMEPAD_X, 0.0)
            ok = quitout._wait(lambda: quitout._is_screen("darksign_q") is True and quitout._is_screen("darksign_yes") is True, 1.5)
            if not ok:
                quitout._press(self.pad, B.XUSB_GAMEPAD_B, 0.4)      # if it's not the dialog, close and retry (may have been interrupted by a hit)
                continue
            quitout._press(self.pad, B.XUSB_GAMEPAD_A, 0.0)
            t0 = last = time.time()
            while time.time() - t0 < 40.0:                         # pointers change after loading — reattach every 4 s
                try:
                    s = self.tm.snapshot(within=1.0)
                except Exception:
                    s = None
                if s and s.player.hp and s.player.hp > 0:
                    here = (s.player.x, s.player.y, s.player.z)
                    if (pre is not None and math.dist(here, pre) > 20.0) or math.dist(here, tuple(bonfire_stand)) < 15.0:
                        time.sleep(1.5)
                        e = self.estus_id()
                        if e is not None:
                            self.select_item(e)                      # switch the slot back to Estus
                        return True
                if time.time() - last > 4.0:
                    last = time.time()
                    try:
                        self.tm = env.make_telemetry({})
                    except Exception:
                        pass
                time.sleep(0.3)
            return False
        return False

    # ── Throwing ───────────────────────────────────────────────
    def aim(self, ptr, deg: float = 1.5, timeout: float = 3.0) -> float | None:
        """Precise aim without lock-on — short 0.6 stick taps to turn the body toward the target (hunt.aim_fine measured: within 0.15~0.9° per tap).
        → last remaining offset (°), None if the target is gone."""
        t, off = time.time(), None
        while time.time() - t < timeout:
            s = self.snap(40.0)
            c = self.find(s, ptr)
            if c is None or s.player.heading is None or s.cam_yaw is None:
                return None
            off = math.degrees(rel_angle(s.player, c))
            if abs(off) <= deg:
                break
            self.pad.move(*[0.6 * v for v in self.stick_to(s, c.x, c.z)])
            time.sleep(0.08 if abs(off) > 10 else 0.05)
            self.pad.move(0.0, 0.0)
            time.sleep(0.25)
        self.pad.move(0.0, 0.0)
        time.sleep(0.16)
        return off

    def lock_state(self, ptr) -> str:
        """'target' | 'other' | 'none' — whether lock-on is on the target (PlayerIns+0xEF0 handle)."""
        h = self.tm.lock_target()
        if h is None or h == -1:
            return "none"
        return "target" if ptr and h == self.tm.handle(ptr) else "other"

    def unlock(self) -> None:
        if self.tm.lock_target() not in (None, -1):
            self.pad.lock_on()                    # R3 is a toggle
            time.sleep(0.15)

    def _r3(self, wait: float = 0.3) -> None:
        self.pad.lock_on()
        t = time.time()
        while time.time() - t < wait:
            self.pad.release_due()
            time.sleep(0.01)

    def reset_camera(self) -> None:
        """R3 = with no lock-on target, the camera resets behind the back at default height. Thrown without lock-on, knives fly along **camera direction·pitch**
        (old measurement: 3 thrown at 0.0° aim with the camera tilted down landed at my feet). If it locks on, press once more to release."""
        self._r3(0.35)
        if self.tm.lock_target() not in (None, -1):
            self._r3(0.2)

    def throw_firebomb(self, ptr, watch: float = 2.2) -> dict:
        """One emergency firebomb — same aim·lock-on path as the knife, only the slot differs."""
        return self.throw_knife(ptr, watch=watch, require_lock=True, item=ITEM_FIREBOMB)

    def throw_knife(self, ptr, watch: float = 1.8, require_lock: bool = False, item: int = ITEM_KNIFE) -> dict:
        """One throwing knife — lock on only when throwing (user: normally no lock-on. Old measurement: without lock-on it must be within 1.2° at 14 m
        and enemies standing above reacted 0/3; with lock-on even #5 20 m up got hit). If lock-on fails, throw with precise aim.
        → {"ok": thrown, "locked", "hit": damage, "woke": moved, "dist", "knives": remaining count, "why"}"""
        if not self.tm.goods_count(item):
            return {"ok": False, "why": f"{item} 없음"}
        if not self.select_item(item):
            return {"ok": False, "why": f"{item} 칸을 못 고름"}
        s = self.snap(40.0)
        c = self.find(s, ptr)
        if c is None:
            return {"ok": False, "why": "그놈 없음"}
        self.pad.guard(False)
        self.cam_busy = True
        try:
            return self._throw_knife(ptr, c, watch, require_lock, item)
        finally:
            self.cam_busy = False

    def _throw_knife(self, ptr, c, watch: float, require_lock: bool, item: int = ITEM_KNIFE) -> dict:
        self.aim(ptr, deg=8.0, timeout=1.5)       # turn the body toward it so lock-on grabs the target
        locked = False
        for _ in range(3):
            if self.lock_state(ptr) == "none":
                self.look_at(ptr, tol=5.0, timeout=2.5)   # R3 grabs the enemy at camera center — point the camera at the target first (user's method)
            self.pad.lock_on()
            t = time.time()
            while time.time() - t < 0.4:
                self.pad.release_due()
                time.sleep(0.02)
            st = self.lock_state(ptr)
            if st == "target":
                locked = True
                break
            if st == "other":
                self.pad.lock_on()                # locked the neighbor → release and retry
                time.sleep(0.15)
        off = None
        if not locked and require_lock:
            return {"ok": False, "locked": False, "why": "락온 안 걸림 — 안 던짐 (락온 없는 나이프는 오늘 0/5)", "dist": round(c.dist, 1)}
        if not locked:
            # User 2026-09-24: "Aim problem when throwing knives — align direction with the enemy". Resetting the camera behind the body after aligning the body
            # makes camera direction = body direction (before, the camera from walking was looking sideways)
            self.reset_camera()
            off = self.aim(ptr, deg=1.5, timeout=3.0)
            self.reset_camera()
        s = self.snap(40.0)
        c = self.find(s, ptr)
        if c is None:
            self.unlock()
            return {"ok": False, "why": "그놈 없음", "locked": locked}
        hp0, pos0, n0 = c.hp, (c.x, c.y, c.z), self.tm.goods_count(item) or 0
        self.pad.release_due()                    # a pending scheduled button release swallows X ("not thrown (count unchanged)" 2/3)
        time.sleep(0.05)
        self.pad.use_item()
        t, hit, woke = time.time(), 0, False
        while time.time() - t < watch:
            self.pad.release_due()
            s2 = self.snap(40.0)
            c2 = self.find(s2, ptr)
            if c2 is not None:
                hit = max(hit, hp0 - c2.hp)
                if math.dist((c2.x, c2.y, c2.z), pos0) > 0.8 or c2.anim not in (-1, None):
                    woke = True
                if hit > 0 and woke:
                    break
            time.sleep(0.03)
        self.unlock()
        n1 = self.tm.goods_count(item) or 0
        return {"ok": n1 < n0, "locked": locked, "aim_off": None if off is None else round(off, 1), "hit": hit, "woke": woke,
                "dist": round(c.dist, 1), "knives": n1, "why": None if n1 < n0 else "안 던져짐 (개수 그대로)"}

    # ── Movement ─────────────────────────────────────────────────
    def walk_path(self, path: list, nm, mode="walk", stop=None, on_tick=None, tol: float = 1.0,
                  timeout_per: float = 10.0) -> str:
        """Walk·sprint along a path. mode is 'walk'|'sprint'|'guard' or a function snapshot → that string.
        If stop(snapshot) is true, stop **on that tick** → 'stopped'. Steep spots are stepped tightly via nav.path_tolerances.
        → 'arrived' | 'stopped' | 'dead' | goto failure value"""
        if not path:
            return "arrived"
        mode_fn = mode if callable(mode) else (lambda _s: mode)

        def fn(sn):
            if stop is not None and stop(sn):
                return "retreat"          # goto returns immediately on 'retreat'
            return mode_fn(sn)
        r = nav.follow(self.tm, self.pad, [tuple(q) for q in path], terrain=nm, mode_fn=fn, on_tick=on_tick,
                       default_tol=tol, timeout_per=timeout_per)
        return "stopped" if r == "retreat" else r

    # ── Menu ─────────────────────────────────────────────────
    def quit_reload(self) -> dict:
        """Menu → Quit Game → Continue. Enemies return to their spawn spots and drop aggro. Dead enemies stay dead (user confirmed 2026-09-24).
        Resting (bonfire) revives all enemies, so use this when you only need to shake enemies off."""
        self.pad.neutral()
        # Skip the menu — ChrClassWarp+0x19 = 1 sends the game straight to the title (2026-09-25, user: "No need to operate the menu
        # to quit"). The menu way took 2~2.8 s and the menu won't open while falling, so it couldn't prevent fall deaths. Fall back to the menu if it fails.
        t0, how = time.time(), "byte"
        quitout.LAST_STEPS.clear()
        q = time.time() - t0 if self.tm.quit_to_title(timeout=2.0) else None
        if q is None:
            how = "menu"
            q = quitout.quit_out(self.tm, self.pad, gap=quitout.MENU_GAP, settle=0.1, ready_wait=0.05)
        if q is None:
            quitout.close_menu(self.tm, self.pad)
            return {"ok": False}
        r = quitout.reload(self.pad)
        time.sleep(1.0)
        return {"ok": r is not None, "how": how, "quit_s": round(q, 2), "reload_s": None if r is None else round(r, 1)}

    def rest(self, nm, bonfire: dict) -> bool:
        """Walk to the bonfire, sit, and stand up (farm.rest). All enemies revive and HP·Estus refill."""
        return farm.rest(self.tm, self.pad, nm, bonfire)

    def press(self, button, hold: float = 0.1, gap: float = 0.1) -> None:
        """Single press for menus (press, release, gap). Menu inputs 0.1 s apart (user: back-to-back inputs tangle the input buffer)."""
        self.pad.tap(button, hold)
        time.sleep(hold + 0.03)
        self.pad.release_due()
        time.sleep(gap)
