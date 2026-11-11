"""Measure each weapon's one-handed light attack in the game (MoKa M1110-03: "캐릭터도 무적, 몹도 무적으로 해서 … 약공으로 때리면
데이타가 나올까?" — 무기별 선 딜레이, 실제 무기 움직이는 시간, 후 딜레이, M1110-01).

  python weapon_probe.py --weapons 301003,201000,701000,200000,1050000 [--reps 5] [--foe 255041] [--dist 1.4]
  python weapon_probe.py --report data/probe/<file>.jsonl        table again from a saved file (no game)

OFFLINE ONLY (Steam offline) — it writes game memory:
  · ChrDbg flags: PLAYER_NO_DEAD, ALL_NO_ATTACK, ALL_NO_MOVE, ALL_NO_UPDATE_AI, ALL_NO_STAMINA_CONSUME — all back to 0 at the end
  · the foe's HP back to its max before every swing (with ALL_NO_DEAD a foe sits at HP 1 after two hits and hides the
    next hit; here no NO_DEAD on foes, the swing just never takes the full max)
  · the player's position (pos_warp, same area) to stand `--dist` m in front of the foe
  · the right-hand slots: weapon → the slot not in hand (inventory index +0x2A4.., item id +0x324..), then D-pad → so the game
    itself switches and loads the model (11-10: Longsword this way, HUD and model changed). The original slots come back.

Per weapon, `--reps` times each, locked on, one-handed:
  single  R1 once → press→start (wall s), hit (anim time at the first frame the foe's HP fell), natural end (last anim time
          before the animation changed)
  chain   R1, then R1 mashed → R cancel (last anim time of attack 1 before attack 2 started)
  roll    R1, then stick back + B mashed → roll cancel
  move    R1, then stick back held → move cancel
Times are the game's own animation clock (dsr_telemetry.anim_time), sampled every few ms — read at 60 fps, so ±1 frame
(0.017 s). Compare: weapon_table.py (TAE: startup = first hitbox frame, cancel_r / cancel_roll / cancel_move = first flag).
The hit frame is when HP changed in memory, which can be a frame after the hitbox touched — and depends on distance.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import struct
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "probe"
TABLE = ROOT / "data" / "gamefiles" / "weapon_table.json"
SLOT_IDX, SLOT_ID, HELD_R = 0x2A4, 0x324, 0x310     # hand slots: L1 R1 L2 R2 (inventory index · item id); right slot in hand
MODES = ("single", "chain", "roll", "move")
POLL = 0.002
WINDOW_S = 3.2
MASH = 0.05


# ── analysis (pure — tests/weapon_probe_test.py) ─────────────────────────────
def analyze(samples: list, t_press: float, attack: set, hp0: int, mode: str) -> dict:
    """samples: [(wall, anim, anim_time, foe_hp)] after the press. attack: this weapon's light-attack anim ids."""
    out = {"mode": mode}
    first = next((i for i, s in enumerate(samples) if s[1] in attack), None)
    if first is None:
        out["error"] = "no attack anim"
        return out
    a1 = samples[first][1]
    out["anim"] = a1
    out["press_to_start"] = round(samples[first][0] - t_press, 3)
    last_t = None
    for s in samples[first:]:
        if s[1] != a1:
            out["next_anim"] = s[1]
            out["end"] = last_t
            break
        if s[2] is not None:
            last_t = round(s[2], 3)
        if "hit" not in out and s[3] is not None and hp0 is not None and s[3] < hp0:
            out["hit"] = last_t
            out["damage"] = hp0 - s[3]
    else:
        out["error"] = "attack did not end in the window"
    seq, prev = [], None
    for s in samples:
        if s[1] != prev:
            seq.append([s[1], None if s[2] is None else round(s[2], 3), round(s[0] - t_press, 3)])
            prev = s[1]
    out["seq"] = seq[:10]                               # (anim, its clock at first sight, wall s after press) — for checking
    na = out.get("next_anim")
    # x3040–3049: 같은 판정에 끊기 플래그가 0.33 s 늦은 변형 (배틀 액스, 대상에 1 m 안으로 붙었을 때만 나옴, 11-10) ·
    # x3150: 벽 튕김 — 둘 다 끊기가 아니라 다른 애니로 넘어간 것
    if na is not None and na >= 0 and (40 <= na % 1000 < 50 or na % 1000 == 150):
        out["note"] = f"switched to {na}, not a cancel"
        return out
    if mode == "chain" and "next_anim" in out and out["next_anim"] not in attack:
        out["note"] = "ended without the next attack"
    if mode == "roll" and "next_anim" in out and out["next_anim"] in attack:
        out["note"] = "next was an attack, not a roll"
    return out


def fight_stats(hits: list, taken: list, kill_t: float | None, secs: float, hp0: int) -> dict:
    """hits: [(t, dmg, sp)] on the foe, taken: [(t, dmg)] on the player. kill_t None = not killed within the limit."""
    dmg = sum(h[1] for h in hits)
    t = kill_t if kill_t is not None else secs
    return {"killed": kill_t is not None, "kill_s": kill_t, "secs": round(secs, 1), "foe_hp0": hp0, "hits": len(hits),
            "damage_total": dmg, "per_hit": sorted({h[1] for h in hits}), "dps": round(dmg / t, 1) if t > 0 else None,
            "first_hit_s": hits[0][0] if hits else None, "taken_hits": len(taken), "taken_total": sum(x[1] for x in taken)}


def summary(rows: list, table: dict | None = None) -> list[str]:
    """Median per weapon and mode, next to weapon_table.py's TAE numbers when that row exists."""
    lines = []
    by: dict = {}
    for r in rows:
        by.setdefault(r["weapon"], {}).setdefault(r["mode"], []).append(r)
    trow = {v["row"]: (k, v) for k, v in (table or {}).get("weapons", {}).items()}

    def med(rs, key):
        v = [r[key] for r in rs if r.get(key) is not None and not r.get("note") and not r.get("error")]
        return (round(statistics.median(v), 3), len(v)) if v else (None, 0)

    for w, modes in by.items():
        name, tr = trow.get(w - w % 100, (str(w), None))
        lt = (tr or {}).get("light") or {}
        lines.append(f"{name} ({w})")
        st, n1 = med(modes.get("single", []), "hit")
        ps, _ = med(modes.get("single", []), "press_to_start")
        en, _ = med(modes.get("single", []), "end")
        rc, n2 = med(modes.get("chain", []), "end")
        ro, n3 = med(modes.get("roll", []), "end")
        mv, n4 = med(modes.get("move", []), "end")
        f = lambda v: "-" if v is None else f"{v:.3f}"
        lines.append(f"  hit {f(st)} (n {n1}, TAE blade {f(lt.get('startup'))}–{f(lt.get('blade_end'))}) · press→start {f(ps)} s wall "
                     f"· natural end {f(en)}")
        lines.append(f"  R cancel {f(rc)} (n {n2}, TAE {f(lt.get('cancel_r'))}) · roll {f(ro)} (n {n3}, TAE {f(lt.get('cancel_roll'))}) "
                     f"· move {f(mv)} (n {n4}, TAE {f(lt.get('cancel_move'))})")
    return lines


# ── game side ─────────────────────────────────────────────────────────────────
class Probe:
    def __init__(self, tm, pad, mv, log=print):
        self.tm, self.pad, self.mv, self.log = tm, pad, mv, log
        cb = tm.q(tm.static["ChrClassBase"])
        self.pgd = tm.q(cb + 0x10)
        self.orig = [(tm.i32(self.pgd + SLOT_IDX + 4 * k), tm.i32(self.pgd + SLOT_ID + 4 * k)) for k in range(4)]
        self.orig_held = tm.i32(self.pgd + HELD_R)

    def inv_index(self, item: int) -> int | None:
        import dsr_telemetry as D
        raw = self.tm.pm.read_bytes(self.pgd, 0x8000)
        for i in range((len(raw) - D.INV_BASE) // D.INV_ENTRY):
            cat, iid, q = struct.unpack_from("<Iii", raw, D.INV_BASE + i * D.INV_ENTRY)
            if cat == 0 and iid == item and q > 0:
                return i
        return None

    def _slot(self, k: int, idx: int, item: int) -> None:
        self.tm.pm.write_int(self.pgd + SLOT_IDX + 4 * k, idx)
        self.tm.pm.write_int(self.pgd + SLOT_ID + 4 * k, item)

    def _toggle(self) -> None:
        import control
        self.pad.press(control.B.XUSB_GAMEPAD_DPAD_RIGHT, 0.1)
        time.sleep(2.0)

    def equip(self, item: int) -> bool:
        """Into the right slot not in hand, then D-pad → (the game switches and loads it)."""
        if self.tm.right_weapon() == item:
            return True
        idx = self.inv_index(item)
        if idx is None:
            self.log(f"   {item}: 인벤토리에 없음")
            return False
        held = self.tm.i32(self.pgd + HELD_R)
        other = 3 if held == 0 else 1                 # slot list L1 R1 L2 R2: R1 = 1, R2 = 3
        self._slot(other, idx, item)
        time.sleep(0.3)
        self._toggle()
        ok = self.tm.right_weapon() == item
        self.log(f"   장착 {item}: {'ok' if ok else 'FAIL'} (손 {self.tm.i32(self.pgd + HELD_R)})")
        return ok

    def restore_slots(self) -> None:
        r1, r2 = self.orig[1], self.orig[3]
        held = self.tm.i32(self.pgd + HELD_R)
        want = (r1 if self.orig_held == 0 else r2)[1]
        if self.tm.right_weapon() != want:
            self.equip(want)
        held = self.tm.i32(self.pgd + HELD_R)
        if held == (0 if self.orig_held == 0 else 1):
            self._slot(3 if held == 0 else 1, *(r2 if held == 0 else r1))
        else:                                         # wanted weapon ended in the other slot: put both back as they were
            self._slot(1, *r1)
            self._slot(3, *r2)
            self._toggle()
        self.log(f"   손 슬롯 복원: {[(self.tm.i32(self.pgd + SLOT_IDX + 4 * k), self.tm.i32(self.pgd + SLOT_ID + 4 * k)) for k in range(4)]} "
                 f"손 {self.tm.i32(self.pgd + HELD_R)}")

    def place(self, foe, dist: float, nm=None, angles=None, back: float | None = None) -> bool:
        """Stand dist m in front of the foe (forward = (−sin h, −cos h), souls/pull.facing) — at the angle within ±90° of its
        front whose spot and the SAFE_BACK m behind it (rolls and walking go there, away from the foe) are NavMesh floor at
        its height. False if no such angle (then don't measure here)."""
        h = math.atan2(-math.sin(foe.heading), -math.cos(foe.heading))
        for off in angles or (0, 15, -15, 30, -30, 45, -45, 60, -60, 75, -75, 90, -90):   # 등 뒤는 안 감 (백스탭)
            a = h + math.radians(off)
            ux, uz = math.sin(a), math.cos(a)
            if nm is not None and not safe_line(nm, foe.x, foe.y, foe.z, ux, uz, dist, dist + (SAFE_BACK if back is None else back)):
                continue
            self.tm.pos_warp(foe.x + ux * dist, foe.y + 0.3, foe.z + uz * dist)
            time.sleep(1.0)
            self.y0 = foe.y
            return True
        return False

    def alive_here(self) -> str | None:
        """None if fine, else why to stop: dead · fell (≥ FALL_M below where we stood) · no player (loading)."""
        s = self.tm.snapshot(within=1.0)
        if s is None:
            return "no player"
        if s.player.hp <= 0:
            return "dead"
        if getattr(self, "y0", None) is not None and s.player.y < self.y0 - FALL_M:
            return f"fell to y {s.player.y:.1f}"
        return None

    def find(self, ptr):
        s = self.tm.snapshot(within=30.0)
        if s is None:
            return None, None
        return s, next((c for c in s.chars if c.ptr == ptr), None)

    def swing(self, foe_ptr: int, mode: str, attack: set, after_blade: float = 0.8) -> dict:
        """after_blade: wall s after the press when the stick / roll mash starts — past the blade window. 11-10 시험: 0.15 s에
        스틱을 뒤로 밀면 휘두르는 중에 몸이 돌아 벽에 튕김 (233150 = 튕김, TAE 플래그 41) → 맞지도 않고 구르기도 못 잼."""
        import control
        from dsr_telemetry import OFF_HP, OFF_MAXHP
        B = control.B
        self.pad.move(0.0, 0.0)
        pp = self.tm.player_ptr()
        t_idle = time.time()                            # 11-10 시험: 앞 판의 연타가 남아 다음 판이 공격 2·3으로 시작 — 가만히 설 때까지 기다림
        quiet = 0.0
        while time.time() - t_idle < 6.0 and quiet < 0.8:
            a_ = self._anim(pp)
            quiet = quiet + 0.05 if a_ not in attack and a_ is not None and not (700 <= (a_ or 0) < 800) else 0.0
            time.sleep(0.05)
        time.sleep(0.4)
        mhp = self.tm.i32(foe_ptr + OFF_MAXHP)
        self.tm.pm.write_int(foe_ptr + OFF_HP, mhp)
        time.sleep(0.1)
        hp0 = self.tm.i32(foe_ptr + OFF_HP)
        # 누르는 순간의 거리·높이 차 (P-157: 판 기록의 dist는 다시 세우기 전 값이라 튕긴 판의 실제 거리를 몰랐음)
        s_, f_ = self.find(foe_ptr)
        geo = {} if f_ is None else {"dist_press": round(math.hypot(f_.x - s_.player.x, f_.z - s_.player.z), 2),
                                     "dy_press": round(s_.player.y - f_.y, 2), "foe_anim_press": f_.anim}
        samples = []
        t0 = time.time()
        self.pad.hold(B.XUSB_GAMEPAD_RIGHT_SHOULDER, True)
        released, down = False, False
        next_mash = t0 + (0.15 if mode == "chain" else after_blade)
        mash_btn = {"chain": B.XUSB_GAMEPAD_RIGHT_SHOULDER, "roll": B.XUSB_GAMEPAD_B}.get(mode)
        shot_at = [0.6, 0.95]
        a1, cut = None, None                           # P-152: 끊긴 뒤에도 스틱을 창 끝까지 밀어 판마다 5~10 m 뒤로 감 → 끊기면 0.3 s 뒤 놓음
        while time.time() - t0 < WINDOW_S:
            now = time.time()
            if mode in ("roll", "move") and cut is not None and now - cut > 0.3:
                break
            if not released and now - t0 >= 0.06:
                self.pad.hold(B.XUSB_GAMEPAD_RIGHT_SHOULDER, False)
                released = True
            if mode in ("roll", "move") and now - t0 >= after_blade:
                self.pad.move(0.0, -1.0)
            if mash_btn is not None and now >= next_mash:
                down = not down
                self.pad.hold(mash_btn, down)
                next_mash = now + MASH / 2
            if getattr(self, "shots", None) and shot_at and now - t0 >= shot_at[0]:
                # P-157: 튕기는 순간 화면 (맞기 직전 0.6 s · 튕김 0.95 s). 별도 스레드 — 폴링을 안 멈춤
                threading.Thread(target=_grab, args=(self.shots / f"{time.strftime('%H%M%S')}_{mode}_{shot_at.pop(0):.2f}.jpg",),
                                 daemon=True).start()
            an = self._anim(pp)
            hp = self.tm.i32(foe_ptr + OFF_HP)
            samples.append((now, an, self.tm.anim_time(pp), hp))
            if hp < mhp:
                # 연타 중 바로 다시 채움 — 11-10 배틀 액스 연타(4 × 56)가 HP 63 적을 죽였고, 그 뒤 HP를 써 넣어도 시체라
                # 휘두르기가 x3040으로 바뀌고 피해 0 (첫 기록 3번 뒤 전부)
                self.tm.pm.write_int(foe_ptr + OFF_HP, mhp)
            if a1 is None and an in attack:
                a1 = an
            elif a1 is not None and cut is None and an != a1:
                cut = now
            time.sleep(POLL)
        if mash_btn is not None:
            self.pad.hold(mash_btn, False)
        self.pad.move(0.0, 0.0)
        self.tm.pm.write_int(foe_ptr + OFF_HP, mhp)
        return {**analyze(samples, t0, attack, hp0, mode), **geo}

    def sustain(self, foe_ptr: int, attack: set, secs: float = 15.0, regen_s: float = 4.0) -> dict:
        """R1을 secs초 동안 계속 누름 — 스태미나 소모 켠 채 (MoKa M1111-03: DPS엔 스태미나가 주는 동안 때릴 수 있는 횟수가 들어가야).
        스태미나를 가득 채우고 시작. 적 HP가 줄 때마다 한 타로 세고 (피해 = 줄어든 만큼) 반 아래로 가면 다시 채움.
        끝나고 regen_s초 손을 떼고 스태미나가 차는 속도를 잼."""
        import control
        from dsr_telemetry import OFF_HP, OFF_MAXHP, OFF_SP, OFF_MAXSP
        B = control.B
        self.pad.move(0.0, 0.0)
        pp = self.tm.player_ptr()
        time.sleep(1.0)
        mhp = self.tm.i32(foe_ptr + OFF_MAXHP)
        self.tm.pm.write_int(foe_ptr + OFF_HP, mhp)
        msp = self.tm.i32(pp + OFF_MAXSP)
        self.tm.pm.write_int(pp + OFF_SP, msp)
        time.sleep(0.2)
        prev = self.tm.i32(foe_ptr + OFF_HP)
        hits, trace = [], []
        t0 = time.time()
        down, next_mash, empty_at = False, t0, None
        while time.time() - t0 < secs:
            now = time.time()
            if now >= next_mash:
                down = not down
                self.pad.hold(B.XUSB_GAMEPAD_RIGHT_SHOULDER, down)
                next_mash = now + MASH
            hp = self.tm.i32(foe_ptr + OFF_HP)
            sp = self.tm.i32(pp + OFF_SP)
            if hp < prev:
                hits.append((round(now - t0, 3), prev - hp, sp))
            if hp < mhp // 2:
                self.tm.pm.write_int(foe_ptr + OFF_HP, mhp)
                hp = mhp
            prev = hp
            if empty_at is None and sp <= 0:
                empty_at = round(now - t0, 3)
            if not trace or now - t0 - trace[-1][0] >= 0.05:
                trace.append((round(now - t0, 3), sp, self._anim(pp)))
            time.sleep(POLL)
        self.pad.hold(B.XUSB_GAMEPAD_RIGHT_SHOULDER, False)
        t_stop = time.time()
        regen = []
        while time.time() - t_stop < regen_s:
            regen.append((round(time.time() - t_stop, 3), self.tm.i32(pp + OFF_SP)))
            time.sleep(0.05)
        self.tm.pm.write_int(foe_ptr + OFF_HP, mhp)
        # 첫 바 = 스태미나가 처음 0 이하가 된 타까지 (11-11 롱소드+1: 98→78→58→38→18→−2 다섯 타, 그 뒤는 회복분으로 1.4 s에 한 타)
        k = next((i for i, h in enumerate(hits) if h[2] <= 0), len(hits) - 1)
        first_bar = hits[:k + 1]
        # 회복 속도: 손 뗀 뒤 처음 오르기 시작한 때부터 가득 차기 전까지의 기울기
        rise = [(t, v) for t, v in regen if v < msp]
        moving = [(t, v) for (t, v), (_, v0) in zip(rise[1:], rise) if v > v0]
        rate = None
        if len(moving) >= 2 and moving[-1][0] > moving[0][0]:
            rate = round((moving[-1][1] - moving[0][1]) / (moving[-1][0] - moving[0][0]), 1)
        delay = round(moving[0][0], 2) if moving else None
        total = sum(h[1] for h in hits)
        return {"mode": "sustain", "secs": secs, "max_stamina": msp, "hits": len(hits), "damage_total": total,
                "dps": round(total / secs, 1), "empty_at": empty_at, "first_bar_hits": len(first_bar),
                "first_bar_damage": sum(h[1] for h in first_bar), "per_hit": sorted({h[1] for h in hits}),
                "regen_per_s": rate, "regen_delay": delay, "hit_log": hits, "stamina_trace": trace[::4]}

    def fight(self, foe_ptr: int, attack: set, limit: float = 240.0, reach: float = 2.3, mortal: bool = False) -> dict:
        """실전 (MoKa M1111-08): 적은 AI·공격·이동 그대로, 적 HP도 안 건드림. 플레이어만 NO_DEAD + HP 반 아래면 다시 채움.
        정책은 모든 무기 같음 — 락온, reach m 밖이면 걸어 붙고, 안이면 스태미나 > 0일 때 R1 연타 (회피·가드 없음).
        죽을 때까지 (또는 limit초) — 처치 시간, 타수, 받은 피격, 거리 밖에 있던 시간을 남김."""
        import control
        from dsr_telemetry import OFF_HP, OFF_MAXHP, OFF_SP, OFF_MAXSP
        B = control.B
        pp = self.tm.player_ptr()
        php_max = self.tm.i32(pp + OFF_MAXHP)
        self.tm.pm.write_int(pp + OFF_SP, self.tm.i32(pp + OFF_MAXSP))
        if mortal:                                          # 착지 낙하 피해를 지우고 무적 끔 (P-158)
            # 11-11 0545..: 1 s 뒤 채운 두 판은 착지 피해가 그 뒤에 들어와 542·570으로 시작 → HP가 1 s 동안 가득 있을 때까지 다시 채움
            t_ = time.time()
            full_since = None
            while time.time() - t_ < 8.0:
                if self.tm.i32(pp + OFF_HP) < php_max:
                    self.tm.pm.write_int(pp + OFF_HP, php_max)
                    full_since = None
                elif full_since is None:
                    full_since = time.time()
                elif time.time() - full_since >= 1.0:
                    break
                time.sleep(0.1)
            self.tm.set_dbg(self.tm.DBG_PLAYER_NO_DEAD, False)
            time.sleep(0.1)
        hp0 = prev = self.tm.i32(foe_ptr + OFF_HP)
        my_prev = self.tm.i32(pp + OFF_HP)
        hits, taken, trace = [], [], []          # trace: (t, 거리, 스태미나, 내 HP, 데몬 HP, 내 동작, 데몬 동작)
        t0 = last = time.time()
        far_s = empty_s = 0.0
        down, next_mash, next_lock, kill_t, stop = False, t0, t0, None, None
        while time.time() - t0 < limit:
            now = time.time()
            dt, last = now - last, now
            s, f = self.find(foe_ptr)
            hp = self.tm.i32(foe_ptr + OFF_HP)
            sp = self.tm.i32(pp + OFF_SP)
            my = self.tm.i32(pp + OFF_HP)
            if hp < prev:
                hits.append((round(now - t0, 3), prev - hp, sp))
            prev = hp
            fa = self._anim(foe_ptr)                         # 데몬 동작 번호 (MoKa M1111-10) — 어떤 공격에 맞았나
            if my < my_prev:
                taken.append((round(now - t0, 3), my_prev - my, fa))
            if not mortal and my < php_max // 2:
                self.tm.pm.write_int(pp + OFF_HP, php_max)
                my = php_max
            my_prev = my
            if hp <= 0:
                kill_t = round(now - t0, 2)
                break
            stop = self.alive_here()
            if my <= 0 or (stop and (mortal or stop != "dead")):     # --mortal (M1111-09): 죽으면 끝
                stop = stop or "dead"
                break
            stop = None
            if s is None or f is None:
                time.sleep(0.02)
                continue
            d = math.hypot(f.x - s.player.x, f.z - s.player.z)
            if now >= next_lock and self.mv.lock_state(foe_ptr) != "target":
                self.mv.lock_target(foe_ptr, tries=1, aim=False)
                next_lock = time.time() + 2.0
            if d > reach:
                far_s += dt
                if down:
                    down = False
                    self.pad.hold(B.XUSB_GAMEPAD_RIGHT_SHOULDER, False)
                self.pad.move(*self.mv.stick_to(s, f.x, f.z))
            else:
                self.pad.move(0.0, 0.0)
                if sp <= 0:
                    empty_s += dt
                if sp > 0 and now >= next_mash:
                    down = not down
                    self.pad.hold(B.XUSB_GAMEPAD_RIGHT_SHOULDER, down)
                    next_mash = now + MASH
                elif sp <= 0 and down:
                    down = False
                    self.pad.hold(B.XUSB_GAMEPAD_RIGHT_SHOULDER, False)
            if not trace or now - t0 - trace[-1][0] >= 0.1:
                trace.append((round(now - t0, 2), round(d, 2), sp, my, hp, self._anim(pp), fa))
            time.sleep(0.01)
        self.pad.hold(B.XUSB_GAMEPAD_RIGHT_SHOULDER, False)
        self.pad.move(0.0, 0.0)
        hp_end = max(0, self.tm.i32(foe_ptr + OFF_HP) or 0)
        return dict(fight_stats(hits, taken, kill_t, time.time() - t0, hp0), mode="fight", stop=stop, reach=reach, mortal=mortal,
                    foe_hp_end=hp_end, foe_cut_pct=round(100 * (hp0 - hp_end) / hp0, 1) if hp0 else None,
                    far_s=round(far_s, 1), empty_s=round(empty_s, 1), player_max_hp=php_max, hit_log=hits, taken_log=taken,
                    trace=trace)

    def _anim(self, pp):
        from dsr_telemetry import OFF_MAPDATA
        if not pp:                                      # 11-10: 위치 쓰기 직후 한 번 player_ptr가 비어 멈춤
            return None
        mapd = self.tm.q(pp + OFF_MAPDATA)
        st = self.tm.q(mapd + 0x48) if mapd else None
        return self.tm.i32(st + 0x80) if st else None


def _game_box():
    import ctypes
    import ctypes.wintypes
    h = ctypes.windll.user32.FindWindowW(None, "DARK SOULS™: REMASTERED")
    r = ctypes.wintypes.RECT()
    if not h or ctypes.windll.dwmapi.DwmGetWindowAttribute(h, 9, ctypes.byref(r), ctypes.sizeof(r)) or r.right <= r.left:
        return None
    return (r.left, r.top, r.right, r.bottom)


def _grab(path: Path) -> None:
    try:
        from PIL import ImageGrab
        path.parent.mkdir(parents=True, exist_ok=True)
        im = ImageGrab.grab(bbox=_game_box(), all_screens=True).convert("RGB")
        im.thumbnail((2400, 1350))
        im.save(path, quality=80)
    except Exception as e:
        print("   화면 캡처 실패:", e)


NPC_NEVER = {264000, 251001}
# ── P-152 (11-10): 교구 다리 위 병사 앞에서 뒤로 구르기 연타 → 판마다 2.6 → 10 m 밀려나 낙사, 소울 37350 잃음 ──
#  NO_DEAD는 낙사를 못 막음. 서는 자리 뒤 SAFE_BACK m까지 같은 높이 바닥이어야 재고, 판 전후로 사망·추락이면 바로 멈춤
SAFE_BACK = 6.0
FALL_M = 2.5


def safe_line(nm, fx, fy, fz, ux, uz, r0, r1, step=0.5, dy=0.6) -> bool:
    """Floor at the foe's height (± dy) every step m from r0 to r1 along (ux, uz) from the foe."""
    r = r0
    while r <= r1 + 1e-6:
        f = nm.floor_at(fx + ux * r, fz + uz * r, fy)
        if f is None or abs(f[0] - fy) > dy:
            return False
        r += step
    return True
FLAGS = ("DBG_PLAYER_NO_DEAD", "DBG_ALL_NO_ATTACK", "DBG_ALL_NO_MOVE", "DBG_ALL_NO_UPDATE_AI", "DBG_ALL_NO_STAMINA_CONSUME")


def run(a) -> None:
    import control
    import env
    from botlock import BotLock
    from souls import moves
    from navmesh import GAME_DIR
    import navmesh  # noqa: F401
    from soulstruct.darksouls1r.params import GameParamBND
    gp = GameParamBND.from_path(GAME_DIR / "param" / "GameParam" / "GameParam.parambnd.dcx")
    weapons = [int(x) for x in a.weapons.split(",")]
    # ── --foe-no-dead (11-10, 츠바이헨더 양손) ──────────────────────────────
    #  한 대 피해가 적 최대 HP를 넘으면 (성벽 마을 적 53–102) 첫 판에 죽고, 죽은 적은 HP를 써 넣어도 x3040 변형·피해 0 (P-153).
    #  ALL_NO_DEAD면 HP가 1에서 멈춤 → 맞은 순간(HP 감소)은 그대로 읽히고 swing()이 바로 최대치로 되돌림. 피해 값은 최대 HP − 1로 잘림.
    flags = FLAGS + (("DBG_ALL_NO_DEAD",) if a.foe_no_dead else ())
    if "sustain" in a.modes.split(","):
        flags = tuple(f for f in flags if f != "DBG_ALL_NO_STAMINA_CONSUME")   # 스태미나가 줄어야 의미가 있음 (M1111-03)
    if "fight" in a.modes.split(","):
        # 실전 (M1111-08): 적을 묶는 플래그 없이 — 플레이어 NO_DEAD만. 적 NO_DEAD도 안 씀 (죽어야 처치 시간)
        # --mortal (M1111-09)도 자리 옮길 때는 NO_DEAD를 켬 — fight()가 시작 직전에 HP를 채우고 끔.
        # 11-11 053225..054203: 끄고 옮기자 화톳불(y 15) → 데몬(y −2.6) 17 m 낙하 피해로 12판이 싸우기 전·직후 죽음 (P-158)
        flags = ("DBG_PLAYER_NO_DEAD",)
    lock = BotLock()
    if not lock.acquire():
        raise SystemExit("봇이 돌고 있음 (data/bot.lock)")
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{time.strftime('%Y%m%d_%H%M%S')}_weapon_probe.jsonl"
    rows = []
    table = json.loads(TABLE.read_text(encoding="utf-8")) if TABLE.exists() else None
    tm = pad = pr = home = stop = None
    try:
        control.focus_game()
        time.sleep(0.8)
        tm = env.make_telemetry({})
        pad = control.Pad()
        time.sleep(2.0)
        mv = moves.Moves(tm, pad)
        pr = Probe(tm, pad, mv)
        pr.shots = (OUT / "shots" / path.stem) if a.shots else None
        s0 = tm.snapshot(within=1.0)
        home = (s0.player.x, s0.player.y + 0.3, s0.player.z) if s0 else None
        s = tm.snapshot(within=80.0)
        # 안드레이(264000)·상인(251001)도 team 6으로 읽힘 (11-10 교구) — 절대 대상으로 고르지 않음
        # 타이타나이트 데몬(230001)은 깨기 전 team 0으로 읽힘 (11-11) → --foe로 지정한 적은 team을 안 봄
        cands = [c for c in s.chars if c.hp > 0 and (a.foe is None or c.npc_param == a.foe)
                 and (c.team == 6 or a.foe is not None) and c.npc_param not in NPC_NEVER]
        if not cands:
            raise SystemExit(f"대상 적 없음 (--foe {a.foe})")
        for f in flags:
            tm.set_dbg(getattr(tm, f), True)
        from souls import missions
        import navmesh as navmesh_
        nm = navmesh_.Navmesh(a.map or missions.MAP_B)
        # 가까운 순으로, 뒤로 SAFE_BACK m 바닥이 있는 자리를 찾을 수 있는 첫 적 (11-10: 첫 255041이 계단 위라 자리 없음)
        foe = next((c for c in sorted(cands, key=lambda c: c.dist if a.at is None else math.hypot(c.x - a.at[0], c.z - a.at[1])) if pr.place(c, a.dist, nm, a.angles, a.safe_back)), None)
        if foe is None:
            raise SystemExit(f"후보 {len(cands)}마리 모두 앞에 뒤로 {SAFE_BACK} m 바닥이 있는 자리가 없음 (P-152)")
        print(f"대상 {foe.npc_param} {foe.name} HP {foe.hp}/{foe.max_hp} at ({foe.x:.1f}, {foe.y:.1f}, {foe.z:.1f}) {foe.dist:.1f} m "
              f"· 벽 {nm.wall_dist(foe.x, foe.y, foe.z):.1f} m · 낭떠러지 {nm.drop_dist(foe.x, foe.y, foe.z):.1f} m")
        stop = None
        for w in weapons:
            if stop:
                break
            if not pr.equip(w):
                continue
            base = w - w % 100
            cat = gp.Weapons[base].AttackAnimationCategory
            sp_cat = gp.Weapons[base].SpecialAttackCategory
            two = a.grip == "2h"
            off = 4000 if two else 3000
            attack = {c * 10000 + off + k for c in (cat, sp_cat) if c for k in range(0, 40)}
            lt = next((v.get("light") or {} for v in (table or {}).get("weapons", {}).values() if v["row"] == base), {})
            after_blade = float(lt.get("blade_end") or 0.75) + 0.05
            if two:
                # 양손 R1 1타 판정 끝은 TAE에서 직접 (weapon_table.json은 한손만)
                tae = json.loads((ROOT / "data" / "gamefiles" / "tae_c0000.json").read_text(encoding="utf-8"))["animations"]
                ev = (tae.get(str(cat * 10000 + 4000)) or {}).get("events", [])
                ends = [e["end"] for e in ev if e["type"] == 1]
                after_blade = (max(ends) if ends else 0.8) + 0.05
                # 양손 = 근력 1.5배 (MoKa M1110-07: 파이크 요구 근력 24, 캐릭터 16 → 16×1.5 = 24)
                for _ in range(3):
                    if tm.grip() == 3:
                        break
                    pad.two_hand_right()
                    time.sleep(0.8)
                print(f"   양손 잡기: grip {tm.grip()}")
                if tm.grip() != 3:
                    print("   양손으로 못 바꿈 — 건너뜀")
                    continue
            s, f_ = pr.find(foe.ptr)
            if s is None or f_ is None:
                print("   대상이 안 보임 — 멈춤")
                break
            if not two and tm.grip() == 3:
                print("   양손 상태 — 한손으로 재야 함, 건너뜀")
                continue
            if not mv.lock_target(foe.ptr):
                print("   락온 실패 — 그래도 잼 (몸이 대상 쪽인지 기록으로 확인)")
            for mode in a.modes.split(","):
                if stop:
                    break
                for k in range(a.reps):
                    stop = pr.alive_here()
                    if stop:
                        print(f"   멈춤: {stop} (P-152)")
                        break
                    s, f_ = pr.find(foe.ptr)
                    if f_ is None:
                        stop = "foe not seen"
                        print("   멈춤: 대상이 안 보임")
                        break
                    # 너무 가까워도 다시 세움 — 배틀 액스는 휘두를 때 앞으로 나가 0.2~1 m까지 붙고 x3040 변형이 나옴 (11-10)
                    # --tol: 츠바이헨더 양손 R1(264000)은 1.3 m 안에서 치면 264150(튕김)으로 넘어감 — 1.46 m는 안 튕김 (11-10 082453).
                    # 판마다 0.2 m쯤 앞으로 나가므로 0.3 여유로는 세 번째 판부터 튕김 → 여유를 줄여 매 판 다시 세움
                    if abs(math.hypot(f_.x - s.player.x, f_.z - s.player.z) - a.dist) > a.tol:
                        if not pr.place(f_, a.dist, nm, a.angles, a.safe_back):
                            stop = "no safe spot"
                            break
                        mv.lock_target(foe.ptr)
                    time.sleep(a.rest)
                    if mode == "fight":
                        r = pr.fight(foe.ptr, attack, a.fight_s, a.reach, a.mortal)
                        if r.get("stop") == "dead":
                            stop = "dead"
                    elif mode == "sustain":
                        r = pr.sustain(foe.ptr, attack, a.sustain_s)
                    else:
                        r = pr.swing(foe.ptr, mode, attack, after_blade)
                    r.update({"wall_foe": round(nm.wall_dist(f_.x, f_.y, f_.z), 2), "wall_me": round(nm.wall_dist(s.player.x, s.player.y, s.player.z), 2)})
                    r.update({"weapon": w, "category": cat, "grip": "2H" if two else "1H", "rep": k, "dist": round(math.hypot(f_.x - s.player.x, f_.z - s.player.z), 2) if f_ else None})
                    rows.append(r)
                    with path.open("a", encoding="utf-8") as fh:
                        fh.write(json.dumps(r, ensure_ascii=False) + "\n")
                    print(f"   {w} {mode} #{k}: " + ", ".join(f"{k2} {v}" for k2, v in r.items() if k2 not in ("weapon", "mode", "rep", "category", "hit_log", "taken_log", "trace", "stamina_trace")))
    finally:
        # --mortal로 죽었으면 (M1111-09) 패드·워프로 정리하지 않음 — 사망 화면·로딩 중. 세이브 복원으로 되돌림
        if pr is not None and stop != "dead":
            try:
                mv.unlock()
            except Exception:
                pass
            try:
                for _ in range(3):
                    if tm.grip() != 3:
                        break
                    pad.two_hand_right()
                    time.sleep(0.8)
            except Exception:
                pass
            pr.restore_slots()
        if tm is not None and home is not None and stop != "dead":
            # 플래그를 끄기 전에 시작 자리(화톳불 근처)로 — 11-10: 적 옆에 둔 채 플래그를 끄자 교구 위 망자 무리 사이에서
            # 몇 분 서 있다 죽은 것으로 보임 (P-153)
            try:
                tm.pos_warp(*home)
                time.sleep(1.0)
            except Exception as e:
                print("   시작 자리로 못 돌아감:", e)
        if tm is not None:
            for f in flags:
                tm.set_dbg(getattr(tm, f), False)
            print("디버그 플래그 끔:", [tm.get_dbg(getattr(tm, f)) for f in flags])
        if pad is not None:
            pad.close()
        lock.release()
    table = json.loads(TABLE.read_text(encoding="utf-8")) if TABLE.exists() else None
    print("\n".join(summary(rows, table)))
    print(f"→ {path}")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--weapons", default="301003")
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--modes", default=",".join(MODES))
    ap.add_argument("--foe", type=int, default=None, help="NpcParam id of the foe to hit (default: nearest hostile)")
    ap.add_argument("--dist", type=float, default=1.4)
    ap.add_argument("--map", default=None, help="NavMesh map for the floor check (default souls.missions.MAP_B)")
    ap.add_argument("--angles", type=lambda v: [float(x) for x in v.split(",")], default=None,
                    help="degrees off the foe's front to stand at, tried in order (default 0,±15 … ±90)")
    ap.add_argument("--at", type=lambda v: [float(x) for x in v.split(",")], default=None,
                    help="x,z — try the foe nearest this point first (죽은 적은 HP를 써 넣으면 살아 있는 것처럼 읽힘, 11-10)")
    ap.add_argument("--grip", choices=("1h", "2h"), default="1h", help="2h: Y+RB로 양손 잡고 x4000 R1을 잼")
    ap.add_argument("--tol", type=float, default=0.3, help="stand again when the distance is this far off --dist (m)")
    ap.add_argument("--foe-no-dead", action="store_true",
                    help="also set ALL_NO_DEAD: for a weapon whose one hit exceeds the foe's max HP (damage reads max HP − 1)")
    ap.add_argument("--safe-back", type=float, default=SAFE_BACK, help="floor needed behind the standing spot (m); below 6 only without roll / move modes (P-152)")
    ap.add_argument("--shots", action="store_true", help="screen at 0.6 s and 0.95 s after each press → data/probe/shots/<run>/")
    ap.add_argument("--rest", type=float, default=0.0, help="extra wait before each swing (s) — lets a knocked-down foe stand up")
    ap.add_argument("--sustain-s", type=float, default=15.0, help="sustain mode: seconds of R1 mashing with stamina use on")
    ap.add_argument("--fight-s", type=float, default=240.0, help="fight mode: give up after this many seconds")
    ap.add_argument("--reach", type=float, default=2.3, help="fight mode: swing when the foe is within this (m), else walk in")
    ap.add_argument("--mortal", action="store_true", help="fight mode: no invincibility, no HP refill, stop when the character dies (M1111-09)")
    ap.add_argument("--report", default=None)
    a = ap.parse_args()
    if a.report:
        rows = [json.loads(l) for l in Path(a.report).read_text(encoding="utf-8").splitlines() if l.strip()]
        table = json.loads(TABLE.read_text(encoding="utf-8")) if TABLE.exists() else None
        print("\n".join(summary(rows, table)))
        return
    run(a)


if __name__ == "__main__":
    main()
