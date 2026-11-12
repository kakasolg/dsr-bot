"""Heavy knight (c2570, NpcParam 257001) in the Undead Parish church — one try of MoKa's plan (M1111-85):
"중갑 기사는 느리니 무기를 들어올리면 뒤로 피하고 한대 때리면 됨".

  python knight_try.py [npc_param]      default 257001 (10.7, 29.3, 119.0); 257002 (−1.6, 28.5, 108.1) is the 744-HP one

Loop: keep ~3.5 m. When the knight starts an attack anim (TAE window table below, chr_models.json npc_attacks) roll straight
back so the roll's i-frames sit on the hit window; when the window has passed and he is still in that anim, step in and hit
once (Claymore light), then back off. Every tick logs the knight's anim, anim_time, distance and both HPs to
data/runs/<log>.knight.jsonl for the analysis. Ends when he dies, my HP < 35 % with no Estus, or 150 s; then guards in place.
Uses andre_route.Route for setup (lock, pad, NavMesh, Field, Andre flag stop).
"""
from __future__ import annotations

import json
import math
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

import andre_route

# ── c2570 공격 판정 (게임 파일: chr_models.json c2570 npc_attacks 257001, TAE 창, 초) ────────────────
#  · 판정 시작 0.83~2.27 s — 느림. 피해 195~323 (내 HP 849). 칼 더미 1→11 = 2.1 m, 3005는 앞으로 6.3 m 돌진
#  · 13xxx = 다른 손잡이(더미 1→20) 같은 창 구조 — 게임에서 어느 때 나오는지 아직 모름
WINDOWS = {3000: (1.07, 1.23), 3001: (1.67, 1.80), 3002: (0.83, 1.00), 3003: (1.03, 1.33), 3004: (0.83, 0.97),
           3005: (1.27, 1.40), 3006: (1.03, 1.30), 3007: (1.37, 1.60),
           13000: (1.53, 1.67), 13001: (0.93, 1.07), 13002: (2.27, 2.40), 13003: (1.43, 1.57), 13004: (1.07, 1.20),
           13005: (1.27, 1.40)}
DURATION = {3000: 3.0, 3001: 4.0, 3002: 2.67, 3003: 2.63, 3004: 2.67, 3005: 3.43, 3006: 3.0, 3007: 3.5}
ROLL_LEAD = 0.6       # [guess] roll_toward = 0.3 s turn + tap; i-frames ≈ 0.1–0.4 s into the roll → start this long before the window
KEEP_M = 3.5          # [guess] distance to wait at
HIT_M = 2.2           # [meas] Claymore light hits to ~2.1 m (10-13)
APPROACH_M = 4.5      # beyond this walk in
LIMIT_S = 150.0


class KnightTry(andre_route.Route):
    def __init__(self, npc: int):
        super().__init__()
        self.npc = npc
        self.klog = open(str(self.log.path).replace(".jsonl", ".knight.jsonl"), "a", encoding="utf-8")
        self.t0 = time.time()
        self.events = []

    def rec(self, kind, **kw):
        d = {"t": round(time.time() - self.t0, 3), "kind": kind, **kw}
        self.klog.write(json.dumps(d) + "\n"); self.klog.flush()
        if kind != "tick":
            self.say(f"  [{d['t']:6.2f}] {kind} {kw}")

    def knight(self, s):
        ks = [c for c in s.chars if c.npc_param == self.npc and c.hp > 0] if s else []
        return min(ks, key=lambda c: c.dist) if ks else None

    def go_near(self):
        s = self.mv.snap(60.0)
        k = self.knight(s)
        if not k:
            return "no knight"
        p = s.player
        d = max(k.dist, 0.1)
        goal = (k.x + (p.x - k.x) / d * 6.0, k.y, k.z + (p.z - k.z) / d * 6.0)
        self.say(f"  기사 {self.npc} at ({k.x:.1f}, {k.y:.1f}, {k.z:.1f}) {k.dist:.1f} m, HP {k.hp} → 6 m 앞 ({goal[0]:.1f}, {goal[2]:.1f})")
        return self.walk([goal], "기사 6 m 앞", ignore={self.npc})

    def away_point(self, s, k, m=4.0):
        p = s.player
        d = max(math.hypot(p.x - k.x, p.z - k.z), 0.1)
        return p.x + (p.x - k.x) / d * m, p.z + (p.z - k.z) / d * m

    def duel(self):
        mv, pad = self.mv, self.pad
        t_end = time.time() + LIMIT_S
        dodged = None          # (anim, anim start wall time) we already rolled for
        hit_for = None         # attack anim we already punished
        last_anim = None
        rolls = hits = 0
        while time.time() < t_end:
            if self.dead():
                return "dead"
            if self.andre_bad():
                return "andre"
            s = mv.snap(20.0)
            k = self.knight(s)
            if not k:
                self.rec("knight_gone")
                return f"killed (rolls {rolls}, hits {hits})"
            p = s.player
            at = self.tm.anim_time(k.ptr)
            a = k.anim
            self.rec("tick", anim=a, at=None if at is None else round(at, 3), d=round(k.dist, 2), khp=k.hp, hp=p.hp,
                     sp=p.sp, my_anim=p.anim, kh=None if k.heading is None else round(k.heading, 3))
            if a != last_anim:
                self.rec("anim", anim=a, at=None if at is None else round(at, 3), d=round(k.dist, 2), khp=k.hp, hp=p.hp)
                last_anim = a
            if p.hp < 0.45 * p.max_hp and k.dist > 3.0 and (a not in WINDOWS):
                self.rec("heal", hp=p.hp, d=round(k.dist, 2))
                self.f.heal(0.7)
                if mv.estus_left() == 0 and p.hp < 0.35 * p.max_hp:
                    return "low hp, no estus"
                continue
            win = WINDOWS.get(a)
            if win and at is not None:
                key = (a, round(time.time() - at, 1))
                # 1) 무기 올림 → 판정 직전에 뒤로 구르기
                if dodged != key and at >= win[0] - ROLL_LEAD and at < win[1] and k.dist < 6.5:
                    ax, az = self.away_point(s, k)
                    self.rec("roll", anim=a, at=round(at, 3), d=round(k.dist, 2), win=win)
                    r = mv.roll_toward(s, ax, az)
                    rolls += 1
                    dodged = key
                    s2 = mv.snap(20.0); k2 = self.knight(s2)
                    self.rec("roll_done", r=r, d=None if not k2 else round(k2.dist, 2), hp=s2.player.hp if s2 else None,
                             k_anim=None if not k2 else k2.anim, k_at=None if not k2 else self.tm.anim_time(k2.ptr))
                    continue
                # 2) 판정 지남, 아직 그 동작 중 → 들어가서 한 대
                left = DURATION.get(a, 2.6) - at
                if at > win[1] + 0.05 and hit_for != key and left > 0.9:
                    if k.dist > HIT_M:
                        pad.move(*mv.stick_to(s, k.x, k.z, 1.0)); time.sleep(0.08)
                        continue
                    pad.move(0, 0)
                    self.rec("hit", anim=a, at=round(at, 3), d=round(k.dist, 2), left=round(left, 2))
                    h = mv.light(s, k, n=1)
                    hits += 1
                    hit_for = key
                    s2 = mv.snap(20.0); k2 = self.knight(s2)
                    self.rec("hit_done", dealt=h.dmg, taken=h.taken, skipped=h.skipped,
                             khp=None if not k2 else k2.hp, hp=s2.player.hp if s2 else None,
                             k_anim=None if not k2 else k2.anim)
                    continue
                pad.move(0, 0); time.sleep(0.03)
                continue
            # 3) 공격 안 할 때: 3.5 m 근처 유지 (너무 멀면 다가가서 깨움, 너무 가까우면 물러남)
            if k.dist > APPROACH_M:
                pad.guard(True)
                pad.move(*mv.stick_to(s, k.x, k.z, 0.6))
            elif k.dist < KEEP_M - 1.0:
                ax, az = self.away_point(s, k, 2.0)
                pad.guard(True)
                pad.move(*mv.stick_to(s, ax, az, 0.6))
            else:
                pad.guard(True)
                pad.move(0, 0)
                mv.face(s, k)
            time.sleep(0.05)
        return f"timeout (rolls {rolls}, hits {hits})"

    def go(self):
        result = "?"
        try:
            self.state("start")
            r = self.go_near()
            self.state("near")
            self.heal_if(0.9)              # 11-12 시작 HP 671/849 — 기사 한 방 195~323
            if r not in ("arrived",) and not (isinstance(r, str) and r.startswith("cleared")):
                self.say(f"  다가가기: {r} — 그래도 싸움 시작")
            result = self.duel()
        finally:
            self.pad.guard(False); self.pad.neutral()
            s = self.state("end")
            print(f"RESULT knight {self.npc}: {result} · log {self.log.path}")
            self.klog.close()
            if not self.dead() and not self.andre_bad():
                try:
                    while not self.andre_bad():
                        self.clear(5.0, 60, "대기 가드")
                except KeyboardInterrupt:
                    pass
            try:
                self.esc.stop()
            except Exception:
                pass
            self.pad.close()
            self.lock.release()


if __name__ == "__main__":
    KnightTry(int(sys.argv[1]) if len(sys.argv) > 1 else 257001).go()
