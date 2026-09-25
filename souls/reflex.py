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
  4) 스태미나가 GUARD_SP 아래면 막지 않는다 (가드가 깨지면 밀려나 떨어진다) — 그놈을 정면에 둔 채 선다 (등 돌려 물러나지 않는다)
  3) 막으면 안 되는 공격(가드 브레이크 3009 등 — 무엇이 그런지는 4층이 unblockable(c) 로 알려 준다)은
     방패 대신 백스텝, 뒤가 낭떠러지면 옆으로 구른다 (막다가 가드가 깨져 밀려나 낙사, 2026-09-24)
  몸을 돌릴 때 그쪽 발밑이 없으면 돌지 않는다 (경사로 추락 2 번 기록).
  (둘 이상이 2.5 m 안에 붙는 건 watch.Escape 가 퀵 종료로 푼다)
"""
from __future__ import annotations

import math
import time

import nav

from . import moves as M

THREAT_R = 2.5           # 수평
EVADE_DELAY = 0.0        # 공격 시작 뒤 이만큼 지나서 피한다 — 즉시 피하면 그놈이 추적해 따라 들어온다 (10판: 백스텝 51회 중 절반 맞음)
EVADE_R = 1.8            # 백스텝 스타일: 이 안에서 휘두를 때만 피한다 — 2.5~3 m 에서도 피하니 계속 밀려나 6 s 동안 못 들어갔다 (2026-09-24)
MIXED_R = 4.0            # 백스텝 스타일이라도 다른 놈이 이 안에 깨어 있으면 방패로 (방패 없이 둘에게 250)
GUARD_SP = 25            # 이 아래로 막으면 가드가 깨진다 (SP 12~22 에서 막다 깨져 밀려나 낙사, 2026-09-24) — 대신 물러난다
THREAT_S = 1.3           # 공격 애니가 시작된 뒤 이만큼만 위협
HIT_R = 3.0


class Reflex:
    def __init__(self, mv: M.Moves, nm=None, unblockable=lambda c: False, bs_ok=lambda c: True):
        self.mv, self.nm, self.unblockable, self.bs_ok = mv, nm, unblockable, bs_ok
        # bs_ok(c): 이 놈에게 백스텝 공격을 써도 되나 — 방패병은 파고드는 도끼가 방패에 막히고 그 콤보에 351 (2026-09-24 진단)
        self.evade = False       # True 면 막지 않고 **모든** 공격을 백스텝·구르기로 피한다 (백스텝 스타일 — 양손, 방패 안 씀)
        self.bs_attack = False   # 피할 때 백스텝 공격(B → R1)을 붙이나 (Style.bs_attack)
        self.reflex_on = True    # False 면 tick() 이 기록(update)만 하고 움직이지 않는다 — rush 스타일: 막지도 피하지도 않고 계속 공격
        self.events = None       # 4층이 넣어 주면 회피마다 'evade' 사건 (kind·거리·그 뒤 1.3 s 안에 맞았나) — style_report.py 가 센다
        self._pending: dict | None = None
        self.last_hit = None     # 마지막 백스텝 공격 결과 (duel 이 기록용으로 가져간다)
        self._dodged: dict = {}        # ptr → 피한 공격의 시작 시각 (한 공격에 한 번만 피한다)
        self.prefer = None             # 지금 싸우는 상대 (duel 이 매 틱 넣는다) — 위협이 여럿이면 이놈 먼저
        self._lock = (None, 0.0)       # (ptr, 까지) — 한 공격 동안 막기 시작한 놈을 계속 정면에
        # 가장 가까운 놈으로 매 틱 바꿨더니 앞뒤로 붙은 둘을 번갈아 보며 옆·뒤를 맞았다 (몸-그놈 -117~-141°, 188 → 0, 2026-09-24)
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
        if self._pending is not None:
            pe = self._pending
            if hp is not None:
                pe["min_hp"] = min(pe["min_hp"], hp)
            if now - pe["t"] >= THREAT_S:
                self._pending = None
                if self.events:
                    self.events("evade", kind=pe["kind"], dist=pe["dist"], eanim=pe["eanim"], npc=pe["npc"], taken=pe["hp0"] - pe["min_hp"])

    def attack_age(self, ptr) -> float | None:
        """그놈의 지금 공격이 시작된 지 몇 초 (공격 중이 아니면 None)."""
        a = self._anim.get(ptr)
        return time.time() - self._start[ptr] if a in M.ATTACK and ptr in self._start else None

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
        if not self.reflex_on:
            return False         # rush: 기록(attack_age 등)만 하고 막지도 피하지도 않는다 — 공격 루프가 안 끊긴다
        th = self.threats(s)
        now = time.time()
        lock_ptr, lock_until = self._lock
        c = next((x for x in th if x.ptr == lock_ptr), None) if now < lock_until else None
        if c is None and th:
            c = next((x for x in th if x.ptr == self.prefer), None) or min(th, key=lambda x: M.horiz(s.player, x))
            self._lock = (c.ptr, self._start.get(c.ptr, now) + THREAT_S)
        if c is None and time.time() - self._hit_t < 0.4:
            c = self._nearest(s, HIT_R)                    # 2) 어디서 맞았는지 모를 때 — 가장 가까운 놈
        if c is None:
            return False
        p = s.player
        start = self._start.get(c.ptr)
        evade_now = self.evade and M.horiz(p, c) <= EVADE_R          # 둘이어도 피한다 — 방패는 안 쓴다 (사용자)
        if evade_now and start is not None and now - start < EVADE_DELAY and self._dodged.get(c.ptr) != start:
            self.step_away(s, c)                           # 아직 이르다 — 정면만 두고 기다린다 (칼이 궤도에 든 뒤 피해야 추적을 못 한다)
            self.acted += 1
            return True
        if c.anim is not None and start is not None and (evade_now or self.unblockable(c)):
            if self._dodged.get(c.ptr) != start:
                self._dodged[c.ptr] = start
                kind = self.dodge(s, c, attack=evade_now and self.bs_attack)
                self._pending = {"t": now, "kind": kind, "dist": round(M.horiz(p, c), 2), "eanim": c.anim, "npc": c.npc_param,
                                 "hp0": p.hp or 0, "min_hp": p.hp or 0}
            else:
                self.step_away(s, c)                       # 한 번 피했으면 그 공격 동안 방패 없이 거리를 둔다
            self.acted += 1
            return True
        if (p.sp or 0) < GUARD_SP or self.evade:
            self.step_away(s, c)                       # 백스텝 스타일: 못 피하는 상황(멀다)이면 정면만 본다, 방패 없이
            self.acted += 1
            return True
        self.mv.pad.guard(True)
        safe_turn = self.nm is None or nav.ground_ahead(self.nm, p, c.x - p.x, c.z - p.z, reach=0.8)
        if safe_turn:
            self.mv.face(s, c, deg=25.0)
        else:
            self.mv.pad.move(0.0, 0.0)
        self.acted += 1
        return True

    def _others_near(self, s, c) -> bool:
        return any(x.ptr != c.ptr and x.hp > 0 and x.anim not in (-1, None) and M.horiz(s.player, x) < MIXED_R for x in s.hostile(MIXED_R + 1))

    def dodge(self, s, c, attack: bool = False) -> str:
        """막으면 안 되는 공격 — 뒤에 바닥이 있으면 백스텝, 없으면 바닥이 있는 옆으로 구른다. 둘 다 없으면 방패 (어쩔 수 없다)."""
        p = s.player
        if p.heading is not None and self.nm is not None:
            back = (math.sin(p.heading), math.cos(p.heading))          # heading 방향 = 몸 뒤 (hunt.backstep_attack 과 같은 규약)
            if nav.ground_ahead(self.nm, p, back[0], back[1], reach=2.6):
                if attack and self.bs_ok(c) and nav.ground_ahead(self.nm, p, -back[0], -back[1], reach=2.2):   # 첫 타는 시작 자리 근처, 3.0 은 경사로에서 거의 항상 실패
                    h = self.mv.backstep_attack(s, c, self.nm)     # 백스텝 + R1 한 동작 (사용자)
                    if h.presses:
                        self.last_hit = h
                        return "bsattack"
                self.mv.backstep()
                return "backstep"
            if self.evade:
                # 백스텝 스타일: 뒤에 바닥이 없으면 구르지 않는다 — 옆 2.5 m 검사를 통과하고도 굴러서 16 m 추락사 (2026-09-24 4판).
                # 한 대 맞는 게 낙사보다 싸다. 정면만 본다.
                self.step_away(s, c)
                return "hold"
            for side in ((back[1], -back[0]), (-back[1], back[0])):
                if nav.ground_ahead(self.nm, p, side[0], side[1], reach=2.5) and s.cam_yaw is not None:
                    self.mv.roll_toward(s, p.x + side[0] * 3.0, p.z + side[1] * 3.0)
                    return "roll"
        self.mv.guard(True)                                # 뒤도 옆도 바닥이 없다 — guard_ok 가 아니면 정면만
        return "guard"

    def step_away(self, s, c) -> None:
        """방패 없이 그놈을 정면에 둔 채 선다. 예전엔 반대쪽으로 스틱을 밀었는데 락온이 없으면 **뒤돌아 걸어가** 등을 맞았다
        (몸-그놈 ±180°, 2026-09-24 테라스 — 사용자: "방향 정렬 못하고 엉뚱한 데로 공격")."""
        self.mv.pad.guard(False)
        self.mv.face(s, c, deg=25.0)

    def hold(self, max_s: float = 2.0) -> None:
        """위협이 지나갈 때까지 반사만 돈다 (걷다가 멈췄을 때)."""
        t0 = time.time()
        while time.time() - t0 < max_s:
            s = self.mv.snap(15.0)
            if s is None or not self.tick(s):
                break
            time.sleep(0.02)
        self.mv.pad.move(0.0, 0.0)
