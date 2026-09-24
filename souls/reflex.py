"""반사 — 1층(moves) 위, 3층(duel) 아래. 싸우든 걷든 **매 틱 가장 먼저** 부른다 (숨 쉬듯).
반사가 움직인 틱(True)은 부른 쪽이 자기 행동을 한 틱 쉰다. 무기도 목적도 모른다.

근거 (2026-09-24 기록 분석, 경사로 23판 피해 5,987):
  · 방패 들고 **정면**에서 막으면 34 (안 들면 115) — 그런데 방패 든 채 **옆·뒤**로 맞은 게 16건 1,560 (평균 74, 안 든 것과 같음)
  · 싸우던 상대보다 **다른 놈**에게 더 맞았다 (12대 1,082 vs 5대 588). 75 % 가 2.5 m 안에 적이 있을 때
  · 옛 reflex.py 는 공격 시작에 0 초대로 방패를 들었지만 방향을 안 맞춰, 맞은 것의 81 % 가 방패를 든 뒤였다
  · 3000 번대 애니는 공격이 끝나도 1.5~5.3 s 남는다 — 그걸 위협으로 계속 보면 공격을 못 한다 (87 s 에 1 번)
  · 방패를 들면 스태미나 회복이 80 % 준다 (위키) — 늘 들지 말고 위협일 때만

그래서:
  1) 공격 애니가 **막 시작된 뒤 THREAT_S 동안**만 위협. 2.5 m 안 위협 중 가장 가까운 놈을 **몸 정면**에 두고 방패
  2) 위협이 없는데 방금 HP 가 깎였으면(보이지 않는 공격) → 3 m 안 가장 가까운 놈 쪽으로 방패
  몸을 돌릴 때 그쪽 발밑이 없으면 돌지 않는다 (경사로 추락 2 번 기록).
  (둘 이상이 2.5 m 안에 붙는 건 watch.Escape 가 퀵 종료로 푼다)
"""
from __future__ import annotations

import math
import time

import nav

from . import moves as M

THREAT_R = 2.5           # 수평
THREAT_S = 1.3           # 공격 애니가 시작된 뒤 이만큼만 위협
HIT_R = 3.0


class Reflex:
    def __init__(self, mv: M.Moves, nm=None):
        self.mv, self.nm = mv, nm
        self._anim: dict = {}          # ptr → 마지막 애니
        self._start: dict = {}         # ptr → 공격 애니가 시작된 시각
        self._hp = None
        self._hit_t = 0.0
        self.acted = 0

    def update(self, s) -> None:
        now = time.time()
        for c in s.hostile(8.0):
            a = c.anim if c.anim is not None else -1
            if a in M.ATTACK and self._anim.get(c.ptr) != a:
                self._start[c.ptr] = now
            self._anim[c.ptr] = a
        hp = s.player.hp
        if self._hp is not None and hp is not None and hp < self._hp:
            self._hit_t = now
        self._hp = hp

    def threats(self, s) -> list:
        now = time.time()
        return [c for c in s.hostile(THREAT_R + 2.0)
                if c.hp > 0 and M.horiz(s.player, c) < THREAT_R and now - self._start.get(c.ptr, 0.0) < THREAT_S
                and (c.anim if c.anim is not None else -1) in M.ATTACK]

    def threat_now(self, s) -> bool:
        self.update(s)
        return bool(self.threats(s)) or (time.time() - self._hit_t < 0.4 and self._nearest(s, HIT_R) is not None)

    def _nearest(self, s, r: float):
        near = [c for c in s.hostile(r + 2.0) if c.hp > 0 and not (9000 <= (c.anim or 0) < 9100) and M.horiz(s.player, c) < r]
        return min(near, key=lambda c: M.horiz(s.player, c), default=None)

    def tick(self, s) -> bool:
        """→ 이번 틱에 반사가 움직였나 (방패·몸 돌리기)."""
        self.update(s)
        th = self.threats(s)
        c = min(th, key=lambda x: M.horiz(s.player, x)) if th else None
        if c is None and time.time() - self._hit_t < 0.4:
            c = self._nearest(s, HIT_R)                    # 2) 어디서 맞았는지 모를 때 — 가장 가까운 놈
        if c is None:
            return False
        self.mv.pad.guard(True)
        p = s.player
        safe_turn = self.nm is None or nav.ground_ahead(self.nm, p, c.x - p.x, c.z - p.z, reach=0.8)
        if safe_turn:
            self.mv.face(s, c, deg=25.0)
        else:
            self.mv.pad.move(0.0, 0.0)
        self.acted += 1
        return True

    def hold(self, max_s: float = 2.0) -> None:
        """위협이 지나갈 때까지 반사만 돈다 (걷다가 멈췄을 때)."""
        t0 = time.time()
        while time.time() - t0 < max_s:
            s = self.mv.snap(15.0)
            if s is None or not self.tick(s):
                break
            time.sleep(0.02)
        self.mv.pad.move(0.0, 0.0)
