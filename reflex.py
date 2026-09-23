"""반사 계층 — 판단 루프와 따로, 5 ms 마다 가까운 적의 애니만 보고 **적 공격이 시작되는 순간** 가드를 올린다.

왜 따로 두나: 판단 루프는 한 틱에 스냅샷(전체 캐릭터 읽기)·판단·이동을 다 해서 25 ms 이고, 폭탄 던지기·
맞은 뒤 대기처럼 몇백 ms 동안 적을 안 보는 구간이 있었다. 게다가 "HP 가 줄면 반응" 은 이미 맞은 뒤다.
사용자: "반응이 100 ms 이하여야 한다. 적은 10 프레임 단위로 반응한다."

그래서 척수 반사처럼 나눈다:
  · 반사(이 스레드): 4 m 안 적의 애니 주소만 5 ms 마다 읽는다 (한 번에 수십 µs). 공격 애니로 바뀌면
    즉시 pad.force_guard=True + 가드. 공격 애니가 끝날 때까지 threat=True → 판단 루프는 공격·투척을 하지 않는다.
  · 판단(patrol.Guard): 누구를 칠지·언제 던질지·어디로 갈지. watch 목록만 틱마다 넘겨준다.

측정도 한다: 적 공격 시작 → 가드 누른 시각(반응), 적 공격 시작 → 내 HP 감소(적의 선딜 = 우리가 쓸 수 있는 시간).
모든 애니 전환을 기록해서 **해골의 공격 애니 번호**도 사후에 맞춰 본다 (지금 범위는 할로우 실측).
"""
from __future__ import annotations

import threading
import time

import control

ENEMY_ATTACK_ANIMS = range(3000, 3600)   # patrol 과 같은 값 (3500 도 공격 — 해골 실측)
WATCH_RADIUS = 4.0
PERIOD = 0.005


class Reflex(threading.Thread):
    def __init__(self, tm, pad: control.Pad, attack_anims=ENEMY_ATTACK_ANIMS, log=print):
        super().__init__(daemon=True)
        self.tm, self.pad, self.log = tm, pad, log
        self.attack_anims = attack_anims
        self._watch: dict[int, tuple[int, int]] = {}   # ptr → (애니 주소, npc)
        self._lock = threading.Lock()
        self._halt = threading.Event()
        self.threat = False            # 판단 루프가 읽는다 — True 면 공격·투척 금지
        self.threat_ptr = None
        self.transitions: list[tuple] = []   # (t, npc, ptr, 이전 애니, 새 애니)
        self.attacks: list[dict] = []        # 공격 시작 이벤트: t, npc, anim, guard_t(가드 누른 시각)
        self.hits: list[tuple] = []          # (t, 피해)
        self.loop_ms: list[float] = []

    # ── 판단 루프가 틱마다 부른다 ──
    def update(self, s) -> None:
        w = {}
        for c in s.hostile(WATCH_RADIUS):
            if c.hp <= 0:
                continue
            addr = self._anim_addr(c.ptr)
            if addr:
                w[c.ptr] = (addr, c.npc_param)
        with self._lock:
            self._watch = w

    def _anim_addr(self, ptr: int) -> int | None:
        mapd = self.tm.q(ptr + 0x68)
        st = self.tm.q(mapd + 0x48) if mapd else None
        return st + 0x80 if st else None

    def stop(self) -> None:
        self._halt.set()

    def run(self) -> None:
        import dsr_telemetry as d
        prev: dict[int, int] = {}
        attacking: dict[int, float] = {}
        pp = self.tm.player_ptr()
        last_hp = self.tm.i32(pp + d.OFF_HP) if pp else None
        last = time.perf_counter()
        while not self._halt.is_set():
            t = time.perf_counter()
            self.loop_ms.append((t - last) * 1000)
            last = t
            with self._lock:
                watch = dict(self._watch)
            for ptr, (addr, npc) in watch.items():
                a = self.tm.i32(addr)
                if a is None:
                    continue
                pa = prev.get(ptr)
                if a != pa:
                    self.transitions.append((time.time(), npc, ptr, pa, a))
                    prev[ptr] = a
                    if a in self.attack_anims and ptr not in attacking:
                        attacking[ptr] = time.time()
                        self.pad.force_guard = True
                        self.pad.guard(True)
                        self.attacks.append({"t": attacking[ptr], "npc": npc, "anim": a, "guard_t": time.time()})
                    elif a not in self.attack_anims and ptr in attacking:
                        del attacking[ptr]
            for ptr in list(attacking):              # 목록에서 빠진(멀어진/죽은) 놈
                if ptr not in watch:
                    del attacking[ptr]
            self.threat = bool(attacking)
            self.threat_ptr = next(iter(attacking), None)
            if not attacking and self.pad.force_guard:
                self.pad.force_guard = False          # 가드를 내리지는 않는다 — 판단 루프가 모드에 맞게 정한다
            # 내 HP — 피격 시각 (선딜 측정용)
            pp = self.tm.player_ptr()
            hp = self.tm.i32(pp + d.OFF_HP) if pp else None
            if hp is not None and last_hp is not None and hp < last_hp:
                # 맞은 순간 내 상태 — 가드를 들고도 맞았으면 원인이 셋 중 하나다:
                # 스태미나 바닥(가드 깨짐) / 옆·뒤에서 맞음 / 내가 휘두르던 중(303xxx)
                me = self.tm.read_chr(pp)
                self.hits.append((time.time(), last_hp - hp, {
                    "my_anim": me.anim if me else None, "sp": me.sp if me else None,
                    "guard_btn": self.pad.guard_held(), "force": self.pad.force_guard,
                    "facing": self._facing(me, watch) if me else None}))
            last_hp = hp
            dt = PERIOD - (time.perf_counter() - t)
            if dt > 0:
                time.sleep(dt)
        self.pad.force_guard = False

    def _facing(self, me, watch) -> list:
        """가까운 적마다 '내 정면에서 몇 도 옆에 있나' — 방패는 정면만 막는다."""
        import math
        out = []
        for ptr in watch:
            c = self.tm.read_chr(ptr)
            if c is None or me.heading is None:
                continue
            ang = math.atan2(c.x - me.x, c.z - me.z)
            fwd = me.heading + math.pi              # 실측: 월드 yaw = heading + π
            off = (ang - fwd + math.pi) % (2 * math.pi) - math.pi
            out.append((c.npc_param, round(math.hypot(c.x - me.x, c.z - me.z), 1), round(math.degrees(off))))
        return out

    # ── 사후 분석 ──
    def report(self) -> dict:
        import statistics as st
        out = {"loop_ms_median": round(st.median(self.loop_ms), 2) if self.loop_ms else None,
               "loop_ms_p90": round(sorted(self.loop_ms)[int(len(self.loop_ms) * 0.9)], 2) if self.loop_ms else None,
               "attacks": len(self.attacks), "hits": len(self.hits)}
        react = [(a["guard_t"] - a["t"]) * 1000 for a in self.attacks]
        if react:
            out["react_ms_max"] = round(max(react), 1)
        # 피격마다 직전 1 s 안에 시작된 적 애니 전환 — 어떤 애니가 공격이었나, 선딜이 얼마였나
        pre = []
        for ht, dmg, *_ in self.hits:
            cands = [(ht - t, npc, new) for t, npc, _p, _o, new in self.transitions if 0 < ht - t < 1.2]
            pre.append({"dmg": dmg, "before": [(round(dt * 1000), npc, a) for dt, npc, a in sorted(cands)[:4]]})
        for h, (_ht, _dmg, *me) in zip(pre, self.hits):
            if me:
                h["me"] = me[0]
        out["hit_context"] = pre
        windup = [(ht - a["t"]) * 1000 for ht, *_ in self.hits for a in self.attacks if 0 < ht - a["t"] < 1.5]
        if windup:
            out["windup_ms_min"] = round(min(windup))
            out["windup_ms_median"] = round(st.median(windup))
        return out
