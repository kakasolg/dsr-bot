"""Camera follow — keeps turning the camera toward the enemy the bot is fighting.

User 2026-09-26: "The bot should actively turn the camera to face the enemy. Since the bot doesn't actually look at the
camera … when I watch, the camera points elsewhere and I often can't tell what it's doing." — bot decisions use telemetry only,
so camera direction doesn't matter to them, but it matters to the human watching the screen (and to R3 auto lock-on).

  cam = CamFollow(mv, esc, log).start()   # run.py
  mv.cam_target = ptr                      # set by layer 4 (field.fight·lure); duel keeps it = its current target each tick

What to look at — one owner, one order (P-65, [MoKa] 10-11 "카메라가 다시 잘 따라 오지 못함" · "정렬이 우선순위 높음"):
  1. mv.cam_target (the fight's current target — duel updates it when it switches)
  2. a foe attacking now (anim 3000–3499) within FOCUS_R — the thrower 18 m up, whoever swings at us while we back off
  3. the last fight target / attacker, for STICKY_S after it stopped being one, while alive, within FOCUS_R and not back
     asleep — after a fight ends in 'shot' / 'low_hp' / a pull, the one we back away from (before P-65: nothing outside a fight)
  4. the nearest moving foe within AUTO_R
Hands off when:
  · locked on — the right stick switches the lock-on target
  · mv.cam_busy — layer 1 is using the camera directly (knife lock-on)
  · emergency escape — the pad is frozen
Walk/attack directions recompute the stick every tick from the current cam_yaw (control.world_to_stick), so body direction stays the same even as the camera turns.
"""
from __future__ import annotations

import threading
import time

DEADBAND = 10.0      # don't turn within this (was 25 — the screen shook less, but the camera sat 20°+ off the foe during fights)
AUTO_R = 12.0        # radius for awake enemies to look at when there's no cam_target
FOCUS_R = 25.0       # attackers and the last followed foe are looked at this far (duel.SHOT_SCAN_R — a thrower on a ledge)
STICKY_S = 8.0       # the last fight target / attacker stays in view this long after it stops being one (backing off, a pull)
TICK = 0.05          # was 0.12
ALIGN_EVERY = 0.5    # "align" event this often (the per-tick numbers go into stats() at the end)
# ── 카메라·캐릭터·적 정렬 ([MoKa] 2026-10-01) ─────────────────────────────
#  "액션할 때 카메라 시점과 캐릭터와 적의 정렬이 잘되면 생각하는 플레이가 잘 나오는데, 아니면 안 될 확률이 높아 — 봇만이 아니라 이 게임을 하는
#   모든 플레이어가 겪는 현상. 카메라 따라오는 것도 더 빠르고, 신경 써서 잡는 것도 확인하는 게 좋겠다" → 더 빨리·더 가까이 따라가고,
#   싸움 중 카메라가 목표에서 얼마나 벗어나 있었는지 재서(stats) 실행 끝에 남긴다


class CamFollow:
    def __init__(self, mv, esc=None, log=print, events=None):
        self.mv, self.esc, self.log, self.events = mv, esc, log, events
        # target–body–camera every tick ([MoKa] 10-11 "정렬이 우선순위 높음"): what we look at (src = rule 1–4 of the docstring),
        # how far it is off the body and the camera, locked or not — {True: in a fight, False: outside} → stats(); an "align"
        # event every ALIGN_EVERY s; attack presses come in through on_attack (Moves.align_sink)
        self.align: dict = {True: [], False: []}
        self.attacks: list[dict] = []
        self.src = None
        self._t_align = 0.0
        self._stop = False
        self.pulses = 0
        self.errs: list[float] = []          # |camera − target| (°) each tick a fight target was set — stats() at the end
        self.errs_out: list[float] = []      # … each tick it followed a foe outside a fight (P-65: these went uncounted)
        self.last, self.last_t = None, 0.0   # rule 3: the last fight target / attacker and when it last was one
        self.had_sign = mv.LOOK_SIGN is not None
        self.th = threading.Thread(target=self._run, daemon=True)

    def start(self) -> "CamFollow":
        self.th.start()
        return self

    @staticmethod
    def _summary(errs: list) -> str | None:
        e = sorted(errs)
        if not e:
            return None
        q = lambda f: e[min(len(e) - 1, int(f * len(e)))]
        return f"중앙 {q(0.5):.0f}° · 90 % {q(0.9):.0f}° · {DEADBAND:.0f}° 안 {sum(1 for x in e if x <= DEADBAND) / len(e):.0%} ({len(e)}번)"

    def measure(self, s, c) -> dict | None:
        """One target–body–camera row for this tick (Moves.align_of) → self.align; an "align" event every ALIGN_EVERY s."""
        try:
            row = self.mv.align_of(s, c)
        except Exception:
            return None
        fight = self.mv.cam_target is not None
        self.align[fight].append((row["body"], row["cam"], row["lock"], row["ok"]))
        now = time.time()
        if self.events is not None and now - self._t_align >= ALIGN_EVERY:
            self._t_align = now
            self.events("align", src=self.src, fight=fight, **row)
        return row

    def on_attack(self, **row) -> None:
        """Moves.align_sink: one attack press — alignment at the press and the damage it did."""
        self.attacks.append(row)
        if self.events is not None:
            self.events("attack_align", **row)

    @staticmethod
    def _align_summary(rows: list) -> str | None:
        body = sorted(abs(b) for b, _c, _l, _ok in rows if b is not None)
        if not body:
            return None
        n = len(rows)
        return (f"몸 중앙 {body[len(body) // 2]:.0f}° · 30° 안 {sum(1 for b in body if b <= 30) / len(body):.0%} · "
                f"정렬 {sum(1 for r in rows if r[3]) / n:.0%} ({n}틱)")

    def align_stats(self) -> str:
        """End-of-run line: per-tick alignment in / out of fights, and at attack presses (aligned or not, and how often each hit)."""
        parts = [f"{k} {v}" for k, v in (("싸움 중", self._align_summary(self.align[True])),
                                         ("싸움 밖", self._align_summary(self.align[False]))) if v]
        if self.attacks:
            ok = [a for a in self.attacks if a.get("ok")]
            bad = [a for a in self.attacks if not a.get("ok")]
            rate = lambda xs: "-" if not xs else f"{sum(1 for a in xs if (a.get('dmg') or 0) > 0)}/{len(xs)}"
            parts.append(f"공격 {len(self.attacks)}번: 정렬 {len(ok) / len(self.attacks):.0%} · 맞힘 정렬 {rate(ok)} / 어긋남 {rate(bad)}")
        return "정렬 (몸 30° 또는 락온): " + (" | ".join(parts) if parts else "기록 없음")

    def stats(self) -> str:
        """Camera off the followed foe: median / 90th percentile / share within DEADBAND (°), in fights and outside."""
        a, b = self._summary(self.errs), self._summary(self.errs_out)
        if a is None and b is None:
            return "카메라 정렬: 기록 없음"
        return "카메라 정렬: " + " | ".join(x for x in (a and f"싸움 중 목표에서 {a}", b and f"싸움 밖 {b}") if x)

    def stop(self) -> None:
        self._stop = True
        self.th.join(timeout=1.0)
        self.mv.pad.look(0.0, 0.0)

    def target(self, s):
        """What to look at, in the order of the module docstring (1 cam_target · 2 attacker · 3 last followed · 4 nearest moving)."""
        now = time.time()
        t = self.mv.find(s, self.mv.cam_target) if self.mv.cam_target is not None else None
        if t is not None and t.hp > 0:
            self.last, self.last_t, self.src = t.ptr, now, "fight"
            return t
        near = [c for c in s.hostile(FOCUS_R) if c.hp > 0]
        swinging = [c for c in near if c.anim is not None and 3000 <= c.anim < 3500]
        if swinging:
            t = min(swinging, key=lambda c: c.dist)
            self.last, self.last_t, self.src = t.ptr, now, "attacker"
            return t
        last = next((c for c in near if c.ptr == self.last), None)
        if last is not None and now - self.last_t < STICKY_S and not (last.anim is not None and 9000 <= last.anim < 9100):
            self.src = "last"
            return last
        awake = [c for c in s.hostile(AUTO_R) if c.anim not in (-1, None) and not 9000 <= c.anim < 9100]   # not a dormant pose
        self.src = "nearest"
        return min(awake, key=lambda c: c.dist, default=None)

    def _run(self) -> None:
        self.had_sign = self.mv.LOOK_SIGN is not None
        while not self._stop:
            time.sleep(TICK)
            try:
                self.step()
            except Exception as ex:                        # don't stop the run because of the camera
                self.log(f"   카메라 따라가기 오류: {type(ex).__name__}: {ex}")
                time.sleep(1.0)

    def step(self) -> None:
        """One camera tick: pick what to look at, measure how far off it is, one pulse if beyond DEADBAND."""
        if self.esc is not None and self.esc.escaping:
            return
        locked = self.mv.tm.lock_target() not in (None, -1)
        s = self.mv.snap(FOCUS_R + 30.0)
        c = self.target(s) if s is not None else None
        if c is None:
            return
        self.measure(s, c)                                 # also while locked on / layer 1 holds the camera — those count too
        if self.mv.cam_busy or locked:
            return
        err = self.mv.cam_err(s, c.x, c.z)
        if err is not None:
            (self.errs if self.mv.cam_target is not None else self.errs_out).append(abs(err))
        if err is None or abs(err) <= DEADBAND:
            return
        self.mv.look_pulse(err)                            # tap size from the measured turn speed (Moves.look_pulse)
        self.pulses += 1
        if not self.had_sign and self.mv.LOOK_SIGN is not None:
            self.had_sign = True
            self.log(f"   카메라: 오른스틱 +x → cam_yaw {'+' if self.mv.LOOK_SIGN > 0 else '−'} (+/− 펄스 한 쌍으로 배움)")
        if self.had_sign and self.mv.LOOK_SIGN is None:
            self.had_sign = False                          # Moves.look_pulse found it backwards and will learn it again
            self.log("   카메라: 오른스틱 방향이 거꾸로였음 — 다시 배움")
