"""Guard keeper — a watcher thread like watch.Escape: while a foe within 2.5 m is swinging, the shield stays up whatever the
decision loop is doing (walking, luring, turning the camera, a backstab try).

    ── 미리 방패를 내림 ([MoKa] 2026-10-12) ──────────────────────────────
     "미리 방패를 내리잖아." — 10-12 구역 4 사망: 적 칼이 닿은 14번 중 막음 1번, 맞음 13번 중 10번은 LB가 떼어져 있었다
     (goto · hold 끝 · look_pulse · 뒤잡기가 내림). 배틀 액스 56런도 2.5 m 안 피격의 51 %가 LB 뗀 상태 — 무기와 무관.
     reflex.tick은 판단 루프가 부를 때만 방패를 들어서, 걷기·끌어오기·카메라 돌리기 중엔 아무도 안 들었다.
     · 여기선 방패만 든다(몸 돌리기·회피는 reflex 몫). Pad.keep_guard → 그 시각까지 guard(False)·neutral()이 LB를 못 뗀다
     · 안 듦: 막을 수 없는 공격(foes.unblockable — reflex가 피함), 스태미나 < GUARD_SP(가드 깨짐 → 낭떠러지), 방패 없는 스타일,
       내가 공격·구르기·에스트 중(free_or_blocking 아님)
"""
from __future__ import annotations

import threading
import time

import env

from . import foes as foes_
from . import moves as M
from .duel import free_or_blocking
from .reflex import GUARD_SP, THREAT_R, THREAT_S


def threat_until(s, starts: dict, now: float, unblockable) -> float | None:
    """Latest 'keep the shield up until' time from foes within THREAT_R that started a blockable attack < THREAT_S ago, or None."""
    p = s.player
    until = None
    for c in s.hostile(THREAT_R + 2.0):
        a = c.anim if c.anim is not None else -1
        st = starts.get(c.ptr)
        if (c.hp <= 0 or a not in M.ATTACK or st is None or now - st >= THREAT_S or M.horiz(p, c) >= THREAT_R
                or unblockable(c)):
            continue
        until = max(until or 0.0, st + THREAT_S)
    return until


class GuardKeep:
    POLL_S = 0.02

    def __init__(self, pad, shield=lambda: True, log=print, events=None):
        self.pad, self.shield, self.log = pad, shield, log
        self.events = events or (lambda *a, **k: None)
        self.unblockable = lambda c: (c.anim or -1) in foes_.of(c.npc_param).unblockable
        self.pressed = 0          # times we raised the shield ourselves
        self._anim: dict = {}
        self._start: dict = {}
        self._stop = False
        self.th = threading.Thread(target=self._run, daemon=True)

    def _update(self, s, now: float) -> None:
        for c in s.hostile(8.0):
            a = c.anim if c.anim is not None else -1
            if a in M.ATTACK and self._anim.get(c.ptr) != a:
                self._start[c.ptr] = now
            self._anim[c.ptr] = a

    def step(self, s, now: float) -> bool:
        """One poll. → pressed LB this time."""
        self._update(s, now)
        p = s.player
        until = threat_until(s, self._start, now, self.unblockable)
        if (until is None or not self.shield() or (p.sp or 0) < GUARD_SP or not free_or_blocking(p.anim)
                or p.hp is None or p.hp <= 0):
            self.pad.unkeep()
            return False
        if self.pad.keep_guard(until):
            self.pressed += 1
            self.events("guard_keep", until=round(until - now, 2))
            return True
        return False

    def _run(self) -> None:
        tm = env.make_telemetry({})
        while not self._stop:
            try:
                s = tm.snapshot(within=5.0)
                if s is not None:
                    self.step(s, time.time())
            except Exception:
                pass
            time.sleep(self.POLL_S)

    def start(self) -> "GuardKeep":
        self.th.start()
        return self

    def stop(self) -> None:
        self._stop = True
        self.th.join(timeout=1.0)
        try:
            self.pad.force_guard = False
            self.pad.unkeep()
        except Exception:
            pass

    def stats(self) -> str:
        return f"가드 유지: 휘두르는 적 2.5 m 안에서 방패 직접 듦 {self.pressed}번"
