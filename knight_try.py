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
import nav

# ── c2570 공격 판정 (게임 파일: chr_models.json c2570 npc_attacks 257001, TAE 창, 초) ────────────────
#  · 판정 시작 0.83~2.27 s — 느림. 피해 195~323 (내 HP 849). 칼 더미 1→11 = 2.1 m, 3005는 앞으로 6.3 m 돌진
#  · 11-12 030049 첫 시도: 메모리 anim id는 3002인데 5.0 s 넘게 이어짐 = a00_3002 (2.67 s)가 아니라 a01_3002 (=13002, 5.33 s).
#    445 피해가 a00 창 (0.83~1.00) 밖, a01 창 (2.27~2.40) 안에서 들어옴 (1.63~3.13 s 사이, 틱 공백). 어느 쪽이 재생되는지
#    메모리로는 구별 못 하므로 3000~3007은 a00·a01 두 창을 모두 위험으로 보고, 길이도 긴 쪽을 씀
A00 = {3000: (1.07, 1.23), 3001: (1.67, 1.80), 3002: (0.83, 1.00), 3003: (1.03, 1.33), 3004: (0.83, 0.97),
       3005: (1.27, 1.40), 3006: (1.03, 1.30), 3007: (1.37, 1.60)}
A01 = {3000: (1.53, 1.67), 3001: (0.93, 1.07), 3002: (2.27, 2.40), 3003: (1.43, 1.57), 3004: (1.07, 1.20),
       3005: (1.27, 1.40)}
WINDOWS = {a: sorted({A00[a]} | ({A01[a]} if a in A01 else set())) for a in A00}
WINDOWS.update({a + 10000: [w] for a, w in A01.items()})
# chr_models.json anims duration, a00 / a01 중 긴 쪽
DURATION = {3000: 3.5, 3001: 4.0, 3002: 5.33, 3003: 3.67, 3004: 3.33, 3005: 3.43, 3006: 3.0, 3007: 3.5,
            13000: 3.5, 13001: 2.87, 13002: 5.33, 13003: 3.67, 13004: 3.33, 13005: 3.43}
LUNGE = {3000: 2.25, 3001: 2.25, 3002: 2.25, 3003: 1.69, 3004: 1.49, 3005: 6.3, 3006: 2.25, 3007: 0.61}  # root motion, m (큰 쪽)
REACH_M = 2.1 + 0.6   # sword dummy 1→11 + margin
ROLL_LEAD = 0.7       # [guess] roll_toward = 0.3 s turn + tap; i-frames ≈ 0.1–0.4 s into the roll
ROLL_M = 2.6          # floor needed for a roll (nav.can_move)
KEEP_M = 3.5          # [guess] distance to wait at
HIT_M = 2.2           # [meas] Claymore light hits to ~2.1 m (10-13)
STEP_IN_M = 1.2       # punish only when this little walking is needed
HIT_NEED_S = 1.3      # [meas] 030049: mv.light blocked 1.5 s, hit lands ~0.5 s in → need this much anim left
APPROACH_M = 4.5      # beyond this walk in
HEAL_HP = 0.45
WALL_OK_M = 1.5      # wait with at least this much floor to the nearest wall
HEAL_CLEAR_M = 6.5    # Field.safe needs no awake foe within SAFE_R 6 m
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
        # 030049: 곧장 6 m 앞 = 교회 입구 쪽 구석 (16.9, 117.2) — 어느 쪽도 바닥 2.6 m 없음. 내 쪽 반원 중 벽에서 가장 먼 점으로
        best = None
        for i in range(24):
            r = math.radians(i * 15)
            ux, uz = math.sin(r), math.cos(r)
            if ux * (p.x - k.x) + uz * (p.z - k.z) < 0:
                continue
            x, z = k.x + ux * 5.0, k.z + uz * 5.0
            h = self.nm.floor_at(x, z, k.y)
            if h is None or abs(h[0] - k.y) > 1.0:
                continue
            w = self.nm.wall_dist(x, h[0], z)
            if best is None or w > best[0]:
                best = (w, (x, h[0], z))
        if best:
            goal = best[1]
            self.say(f"  넓은 자리: 벽까지 {best[0]:.1f} m")
        self.say(f"  기사 {self.npc} at ({k.x:.1f}, {k.y:.1f}, {k.z:.1f}) {k.dist:.1f} m, HP {k.hp} → 6 m 앞 ({goal[0]:.1f}, {goal[2]:.1f})")
        return self.walk([goal], "기사 6 m 앞", ignore={self.npc})

    def open_dir(self, s, k, m=ROLL_M):
        """Away from the knight, turned toward the most floor: straight back, ±45°, ±90°, ±135° — each scored by how far the
        NavMesh floor goes (nav.can_move at m, 2.0, 1.5, 1.0 m), small turns preferred on ties. → (x, z, deg, floor_m).
        030049: straight-back rolls hit the church wall 0.3–0.66 m behind (got None); at (16.9, 117.2) no way had 2.6 m."""
        p = s.player
        bx, bz = p.x - k.x, p.z - k.z
        n = max(math.hypot(bx, bz), 0.1)
        bx, bz = bx / n, bz / n
        best = None
        for deg in (0, 45, -45, 90, -90, 135, -135):
            r = math.radians(deg)
            dx, dz = bx * math.cos(r) + bz * math.sin(r), -bx * math.sin(r) + bz * math.cos(r)
            L = next((L for L in (m, 2.0, 1.5, 1.0) if nav.can_move(self.nm, p, dx, dz, L)), 0.0)
            score = L - 0.002 * abs(deg)
            if best is None or score > best[0]:
                best = (score, dx, dz, deg, L)
        _, dx, dz, deg, L = best
        return p.x + dx * m, p.z + dz * m, deg, L

    def open_spot(self, s, k):
        """A point KEEP_M from the knight with the most room to its walls (navmesh wall_dist) — where to wait for his swing."""
        p = s.player
        best = None
        for i in range(12):
            r = math.radians(i * 30)
            x, z = k.x + math.sin(r) * KEEP_M, k.z + math.cos(r) * KEEP_M
            h = self.nm.floor_at(x, z, p.y)
            if h is None or abs(h[0] - p.y) > 1.0:
                continue
            w = self.nm.wall_dist(x, h[0], z)
            if best is None or w > best[0]:
                best = (w, x, z)
        return best

    def in_danger(self, a, at, d):
        """A window of this anim still ahead (or on) and we are within its reach (sword + forward root motion)."""
        wins = WINDOWS.get(a)
        if not wins or at is None:
            return None
        reach = REACH_M + LUNGE.get(a % 10000, 2.25)
        for w in wins:
            if at < w[1] and d < reach:
                return w
        return None

    def duel(self):
        mv, pad = self.mv, self.pad
        t_end = time.time() + LIMIT_S
        rolled = set()         # (anim start key, window) already rolled for
        hit_for = None         # anim start key already punished
        last_anim = None
        heal_try = 0.0
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
            key = (a, round(time.time() - (at or 0), 1))
            w = self.in_danger(a, at, k.dist)
            # 1) 판정 직전 → 열린 바닥 쪽으로 구르기 (창마다 한 번)
            if w and at >= w[0] - ROLL_LEAD and (key, w) not in rolled:
                ax, az, deg, L = self.open_dir(s, k)
                self.rec("roll", anim=a, at=round(at, 3), d=round(k.dist, 2), win=w, turn=deg, floor=L)
                r = mv.roll_toward(s, ax, az)
                rolls += 1
                rolled.add((key, w))
                s2 = mv.snap(20.0); k2 = self.knight(s2)
                self.rec("roll_done", r=r, d=None if not k2 else round(k2.dist, 2), hp=s2.player.hp if s2 else None,
                         k_anim=None if not k2 else k2.anim, k_at=None if not k2 else self.tm.anim_time(k2.ptr))
                continue
            # 2) 힐: 6.5 m 밖으로 빠진 뒤에만 (030049: 3 m에서 Field.heal 거부 → 같은 자리에서 수십 번 재시도)
            if p.hp < HEAL_HP * p.max_hp and mv.estus_left() > 0 and not w:
                if k.dist < HEAL_CLEAR_M:
                    ax, az, _, _ = self.open_dir(s, k, 2.0)
                    pad.guard(False)
                    pad.move(*mv.stick_to(s, ax, az, 1.0))
                    time.sleep(0.08)
                    continue
                if time.time() - heal_try > 2.0:
                    pad.move(0, 0)
                    heal_try = time.time()
                    self.rec("heal", hp=p.hp, d=round(k.dist, 2))
                    self.f.heal(0.7, sips=1)
                    continue
            # 3) 이 공격의 판정이 다 지나고 동작이 충분히 남음 → 들어가서 한 대
            wins = WINDOWS.get(a)
            if wins and at is not None and at > wins[-1][1] + 0.05 and hit_for != key:
                left = DURATION.get(a, 3.0) - at
                if left > HIT_NEED_S and k.dist <= HIT_M + STEP_IN_M:
                    if k.dist > HIT_M:
                        pad.guard(False)
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
            if wins:
                pad.guard(True); pad.move(0, 0); time.sleep(0.03)
                continue
            # 4) 공격 안 할 때: 3.5 m 근처 유지 (멀면 다가가 공격을 끌어냄, 가까우면 열린 쪽으로 물러남)
            pad.guard(True)
            if k.dist > APPROACH_M:
                pad.move(*mv.stick_to(s, k.x, k.z, 0.6))
            elif k.dist < KEEP_M - 1.0:
                ax, az, _, _ = self.open_dir(s, k, 1.5)
                pad.move(*mv.stick_to(s, ax, az, 0.6))
            elif self.nm.wall_dist(p.x, p.y, p.z) < WALL_OK_M and (o := self.open_spot(s, k)) and o[0] > WALL_OK_M                     and math.hypot(o[1] - p.x, o[2] - p.z) > 0.6:
                pad.move(*mv.stick_to(s, o[1], o[2], 0.6))      # 벽에 등 대지 않게: 기사 둘레 3.5 m 중 가장 넓은 자리로
            else:
                pad.move(0, 0)
                mv.face(s, k)
            time.sleep(0.05)
        return f"timeout (rolls {rolls}, hits {hits})"

    def go(self):
        result = "?"
        try:
            self.state("start")
            self.heal_if(0.9)              # 11-12 시작 HP 671/849 — 기사 한 방 195~323 (기사 근처에선 Field.heal이 안 마심)
            r = self.go_near()
            self.state("near")
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
