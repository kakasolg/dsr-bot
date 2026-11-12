"""Heavy knight (c2570, NpcParam 257001) in the Undead Parish church — one try of MoKa's plan (M1111-85):
"중갑 기사는 느리니 무기를 들어올리면 뒤로 피하고 한대 때리면 됨".

  python knight_try.py [npc_param] [--brawl]   --brawl = v4: two-handed, keep hitting (M1111-90); default 257001 (10.7, 29.3, 119.0); 257002 (−1.6, 28.5, 108.1) is the 744-HP one

Loop: keep ~3.5 m. When the knight starts an attack anim (TAE window table below, chr_models.json npc_attacks) roll straight
back so the roll's i-frames sit on the hit window; when the window has passed and he is still in that anim, step in and hit
once (Claymore light), then back off. Every tick logs the knight's anim, anim_time, distance and both HPs to
data/runs/<log>.knight.jsonl for the analysis. Ends when he dies, my HP < 35 % with no Estus, or 150 s; then guards in place.
Uses andre_route.Route for setup (lock, pad, NavMesh, Field, Andre flag stop).

v3 (MoKa one-hand demo M1111-87, observe 20261112_062835): wait at the plaza stair foot (LURE) for the knight to come out;
during a swing window walk out of reach (WAIT_M) instead of rolling — roll only when walking can't make it in time;
after the window, walk in and hit once while ≥ HIT_NEED_S of the anim is left (counting the walk); no punish after 3000
(3000 → 3001 chain hit MoKa); one hit as he walks in (3200/3210); prefer staying inside the plaza box.
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
# ── v3: MoKa 한손 시연 (M1111-87, observe 062835) ─────────────────────────────────
#  · 3002 (d 4.0)·3003 (d 3.5)·3000 (d 3.3) 창 동안 그 거리에 서 있었고 안 맞음; 3002 d 1.3에선 걸어서 4.9 m로 물러남
#  · 맞은 건 3000 끝나고 바로 이어진 3001에 0.39 s째 들어간 한 번 (−227) → 3000 뒤엔 안 들어감
#  · 때릴 때: 창이 지나고 남은 동작 1.2 s 이상, 2.8~3.5 m에서 걸어 들어가며 R1 → 맞을 때 1.2~2.2 m
WAIT_M = 4.0          # [MoKa 062835] 창 동안 기다린 거리 3.3~4.9 m
LUNGE_FAR = {3005: 6.3 + 2.7}   # 3005만 6.3 m 돌진 (게임 파일) — 이건 시연에 안 나옴
WALK_MPS = 2.0        # [guess] 걸어서 물러나는 속도 (stick 1.0)
HIT_M = 2.6           # [MoKa 062835] R1을 2.8~3.5 m에서 눌러 1.2~2.2 m에서 맞음 → 2.6 m부터 누름
PUNISH_FROM_M = 4.8   # 이 안이면 창 뒤에 걸어 들어감 (남은 시간이 걸음+공격에 충분할 때만)
HIT_NEED_S = 1.2      # [MoKa 062835 ②] 3003 남은 1.2 s에 들어가 맞춤
NO_PUNISH_AFTER = {3000, 13000}   # [MoKa 062835 ④] 3000 → 3001 연속; 030049에도 3000 → 3003 → 3004
WALK_IN = {3200, 3210}            # [MoKa 062835 ⑤] 다가오는 동작(뜻 미확인)에 한 대 — 한 번 관찰
APPROACH_M = 6.0      # beyond this the knight isn't fighting yet
BAIT_AFTER_S = 5.0    # [guess] LURE에서 이만큼 기다려도 안 오면 깨우러 감 (시연: 8.6 s에 나타남; 065353은 150 s 동안 안 옴)
DOOR = (17.0, 28.4, 109.6)        # 교회 문 (3b 경로 (16.4, 109.0) → (11.3, 109.8)); 깨우기는 여기, 안 되면 INSIDE까지만
INSIDE = (13.5, 28.4, 109.5)
STEP_M = 1.3          # [meas observe 062525·062835] 판정 때까지 기사가 앞으로 온 거리: 3002 1.2 · 3003 1.0 · 3000 1.25 · 3001 1.3 m
SAFE_EXTRA_M = 0.6    # 공격 중 사거리+이만큼 안이면 서 있지 말고 물러남 (3b: 3000 d 4.0 '기다림' → 1.43 s에 3.7 m, 늦은 구르기)
WAKE_M = 5.5          # 깨우러 갈 때 이 거리까지만 (NavMesh 길) — 그 전에 움직이면 멈춤
BAIT_TRIES = 3
LURE = (23.5, 26.6, 108.3)        # [MoKa 062835] 계단 아래 광장 — 여기 서 있자 기사가 교회에서 나옴
PLAZA = (20.5, 36.5, 101.0, 114.0)  # [guess] 두 시연의 싸움 자리 x 22~35, z 104~109 + 여유; 밖으로 나가는 쪽은 감점
HEAL_HP = 0.45
WALL_OK_M = 1.5      # wait with at least this much floor to the nearest wall
HEAL_CLEAR_M = 6.5    # Field.safe needs no awake foe within SAFE_R 6 m
LIMIT_S = 150.0
BRAWL_HIT_M = 2.4     # [guess] 2H R1 — MoKa 양손 시연은 1.7 · 3.9(걸어 들어가며) · 2.8 m에서 누름
BRAWL = "--brawl" in sys.argv


def in_plaza(x, z):
    return PLAZA[0] <= x <= PLAZA[1] and PLAZA[2] <= z <= PLAZA[3]


def reach_of(a):
    return LUNGE_FAR.get(a % 10000, WAIT_M)


def decide(a, at, d):
    """v3 one tick, pure (tests/knight_try_test.py). a = knight anim, at = its anim time (s), d = distance (m).
    → ("away", window) walk out of reach · ("roll", window) walking can't make it · ("step_in"|"hit", left) punish ·
      ("hit_walkin", None) · ("wait", None) attack on but nothing to do · None = not attacking."""
    wins = WINDOWS.get(a)
    if a in WALK_IN:
        return ("hit_walkin", None) if d <= HIT_M + 0.3 else None
    if not wins or at is None:
        return None
    reach = reach_of(a)
    for w in wins:
        if at < w[1] and d < reach + SAFE_EXTRA_M:
            t_left = w[0] - at
            need = reach + 0.3 - d
            if need / WALK_MPS <= t_left - 0.15:
                return ("away", w)
            return ("roll", w) if at >= w[0] - ROLL_LEAD else ("away", w)
    if at > wins[-1][1] + 0.05 and a not in NO_PUNISH_AFTER:
        left = DURATION.get(a, 3.0) - at
        walk = max(0.0, d - HIT_M)
        if d <= PUNISH_FROM_M and left > HIT_NEED_S + walk / WALK_MPS:
            return ("hit", round(left, 2)) if walk == 0 else ("step_in", round(left, 2))
    return ("wait", None)


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
            lx, lz = LURE[0] - p.x, LURE[2] - p.z
            ln = max(math.hypot(lx, lz), 0.1)
            toward_lure = (dx * lx + dz * lz) / ln       # P-169: 교회 안에선 모든 방향이 광장 밖 → 감점이 무의미, 남쪽으로 밀림
            score = L - 0.002 * abs(deg) + 0.8 * toward_lure * (ln > 2.0)
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

    def bait(self):
        """P-168: 기사가 LURE를 못 봄 (065353: 17 m, anim −1, 150 s). stick 직선 접근은 교회 문에 막힘 (10.84 m).
        NavMesh 길로 기사에게 걸어가다 반응하면 (anim ≠ −1, 0.5 m 넘게 움직임, 또는 WAKE_M 안) 멈추고, LURE로 돌아감 —
        기사가 4.5 m 안에 오면 그 자리에서 싸움으로 넘김. → (wake 결과, 돌아가기 결과)"""
        s = self.mv.snap(60.0)
        k = self.knight(s)
        if not k:
            return ("no knight", None)
        x0, z0 = k.x, k.z

        def woke(sn):
            kk = self.knight(sn)
            return kk is None or kk.anim != -1 or math.hypot(kk.x - x0, kk.z - z0) > 0.5 or kk.dist < WAKE_M

        self.f.ignore_npcs = {self.npc, andre_route.BOAR}
        try:
            r1 = "no"
            for goal, tag in ((DOOR, "교회 문까지 (깨우기)"), (INSIDE, "문 안 조금 (깨우기)")):
                r1 = self.f.walk_to(goal, self.nm, tag, done=woke)
                s = self.mv.snap(60.0); k = self.knight(s)
                self.rec("bait", to=tag, r=r1, d=None if not k else round(k.dist, 2), anim=None if not k else k.anim,
                         moved=None if not k else round(math.hypot(k.x - x0, k.z - z0), 2))
                if r1 == "done" or (s and woke(s)):
                    break
            # P-169: 깨었든 안 깨었든 항상 LURE로 돌아감 (3b는 'arrived'라 안 돌아가고 교회 안에서 싸움)
            r2 = self.f.walk_to(LURE, self.nm, "LURE로 돌아감",
                                done=lambda sn: (kk := self.knight(sn)) is not None and kk.dist < 4.5 and kk.anim != -1)
            s = self.mv.snap(60.0); k = self.knight(s)
            self.rec("bait_back", r=r2, d=None if not k else round(k.dist, 2), anim=None if not k else k.anim)
            return (r1, r2)
        finally:
            self.f.ignore_npcs = set()

    def decide_logged(self, a, at, d):
        act = decide(a, at, d)
        if act and act[0] != getattr(self, "_last_act", None):
            self.rec("act", act=act[0], anim=a, at=None if at is None else round(at, 3), d=round(d, 2))
        self._last_act = act[0] if act else None
        return act

    def duel(self):
        mv, pad = self.mv, self.pad
        t_end = time.time() + LIMIT_S
        rolled = set()         # (anim start key, window) already rolled for
        hit_for = None         # anim start key already punished
        last_anim = None
        heal_try = 0.0
        rolls = hits = 0
        far_since = None
        baits = 0
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
            act = self.decide_logged(a, at, k.dist)
            kind = act[0] if act else None
            # 1) 판정이 다가옴 → 사거리 밖으로 걸어서 (MoKa 062835 ③); 걸어서 못 빠지면 구르기 (창마다 한 번)
            if kind == "roll" and (key, act[1]) not in rolled:
                ax, az, deg, L = self.open_dir(s, k)
                self.rec("roll", anim=a, at=round(at, 3), d=round(k.dist, 2), win=act[1], turn=deg, floor=L)
                r = mv.roll_toward(s, ax, az)
                rolls += 1
                rolled.add((key, act[1]))
                s2 = mv.snap(20.0); k2 = self.knight(s2)
                self.rec("roll_done", r=r, d=None if not k2 else round(k2.dist, 2), hp=s2.player.hp if s2 else None,
                         k_anim=None if not k2 else k2.anim, k_at=None if not k2 else self.tm.anim_time(k2.ptr))
                continue
            if kind in ("away", "roll"):
                ax, az, deg, L = self.open_dir(s, k, 2.0)
                pad.guard(False)
                pad.move(*mv.stick_to(s, ax, az, 1.0))
                time.sleep(0.05)
                continue
            # 2) 힐: 6.5 m 밖으로 빠진 뒤에만 (030049: 3 m에서 Field.heal 거부 → 같은 자리에서 수십 번 재시도)
            if p.hp < HEAL_HP * p.max_hp and mv.estus_left() > 0:
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
            # 3) 창이 지나고 남은 동작이 걸음+공격에 충분 → 걸어 들어가 한 대 (MoKa 062835 ①②③); 다가오는 동작에도 한 대 (⑤)
            if kind == "step_in" and hit_for != key:
                pad.guard(False)
                pad.move(*mv.stick_to(s, k.x, k.z, 1.0)); time.sleep(0.05)
                continue
            if (kind == "hit" or kind == "hit_walkin") and hit_for != key:
                pad.guard(False); pad.move(0, 0)
                self.rec(kind, anim=a, at=None if at is None else round(at, 3), d=round(k.dist, 2), left=act[1])
                h = mv.light(s, k, n=1)
                hits += 1
                hit_for = key
                s2 = mv.snap(20.0); k2 = self.knight(s2)
                self.rec("hit_done", dealt=h.dmg, taken=h.taken, skipped=h.skipped,
                         khp=None if not k2 else k2.hp, hp=s2.player.hp if s2 else None,
                         k_anim=None if not k2 else k2.anim)
                continue
            if kind == "wait":
                pad.move(0, 0); mv.face(s, k); time.sleep(0.03)
                continue
            # 4) 공격 안 할 때: 멀면 LURE에서 기다림 (시연: 8.6 s 뒤 기사가 나옴), 오래 안 오면 천천히 다가감; 가까우면 물러남
            pad.guard(False)
            if k.dist > APPROACH_M:
                if far_since is None:
                    far_since = time.time()
                if time.time() - far_since > BAIT_AFTER_S and baits < BAIT_TRIES:
                    pad.move(0, 0)
                    baits += 1
                    self.bait()
                    far_since = None
                    continue
                elif math.hypot(p.x - LURE[0], p.z - LURE[2]) > 1.5:
                    pad.move(*mv.stick_to(s, LURE[0], LURE[2], 0.8))
                else:
                    pad.move(0, 0); mv.face(s, k)
            elif k.dist < WAIT_M - 0.8:
                far_since = None
                ax, az, _, _ = self.open_dir(s, k, 1.5)
                pad.move(*mv.stick_to(s, ax, az, 0.6))
            else:
                far_since = None
                pad.move(0, 0)
                mv.face(s, k)
            time.sleep(0.05)
        return f"timeout (rolls {rolls}, hits {hits})"

    def two_hand(self):
        """Y 홀드 + RB 토글을 grip 3 (양손)이 될 때까지 (souls/field.py와 같은 방식, 최대 3번)."""
        for _ in range(3):
            if self.tm.grip() == 3:
                break
            self.pad.two_hand_right()
            time.sleep(0.5)
        self.rec("grip", grip=self.tm.grip())
        return self.tm.grip() == 3

    def brawl(self):
        """v4 (MoKa 11-12 '양잡고 계속 때리기', M1111-90): 양손 클레이모어로 붙어서 계속 친다 — 피하기 없음.
        MoKa 양손 시연 (M1111-86, observe 062525): 2H R1 133 × 3 = 372, 16 s, 맞은 건 1번 (−318).
        LURE에서 기다리기·깨우기는 v3.2와 같고, 기사가 다가오면 (APPROACH_M 안) 그때부터 친다.
        힐: HP < HEAL_HP면 6.5 m 밖으로 걸어 나가서 (v2와 같은 규칙)."""
        mv, pad = self.mv, self.pad
        t_end = time.time() + LIMIT_S
        far_since = None
        baits = swings = 0
        heal_try = 0.0
        while time.time() < t_end:
            if self.dead():
                return "dead"
            if self.andre_bad():
                return "andre"
            s = mv.snap(20.0)
            k = self.knight(s)
            if not k:
                self.rec("knight_gone")
                return f"killed (swings {swings})"
            p = s.player
            at = self.tm.anim_time(k.ptr)
            self.rec("tick", anim=k.anim, at=None if at is None else round(at, 3), d=round(k.dist, 2), khp=k.hp, hp=p.hp,
                     sp=p.sp, my_anim=p.anim, grip=self.tm.grip())
            if self.tm.grip() != 3:
                pad.move(0, 0)
                self.two_hand()
                continue
            if p.hp < HEAL_HP * p.max_hp and mv.estus_left() > 0:
                if k.dist < HEAL_CLEAR_M:
                    ax, az, _, _ = self.open_dir(s, k, 2.0)
                    pad.guard(False)
                    pad.move(*mv.stick_to(s, ax, az, 1.0))
                    time.sleep(0.05)
                    continue
                if time.time() - heal_try > 2.0:
                    pad.move(0, 0)
                    heal_try = time.time()
                    self.rec("heal", hp=p.hp, d=round(k.dist, 2))
                    self.f.heal(0.7, sips=1)
                    continue
            if k.dist > APPROACH_M and k.anim == -1:
                # 아직 안 깬 기사: LURE에서 기다렸다가 깨우기 (v3.2)
                if far_since is None:
                    far_since = time.time()
                if time.time() - far_since > BAIT_AFTER_S and baits < BAIT_TRIES:
                    pad.move(0, 0)
                    baits += 1
                    self.bait()
                    far_since = None
                    continue
                if math.hypot(p.x - LURE[0], p.z - LURE[2]) > 1.5:
                    pad.move(*mv.stick_to(s, LURE[0], LURE[2], 0.8))
                else:
                    pad.move(0, 0); mv.face(s, k)
                time.sleep(0.05)
                continue
            far_since = None
            if k.dist > BRAWL_HIT_M:
                pad.guard(False)
                pad.move(*mv.stick_to(s, k.x, k.z, 1.0))
                time.sleep(0.03)
                continue
            pad.move(0, 0)
            self.rec("swing", anim=k.anim, at=None if at is None else round(at, 3), d=round(k.dist, 2), khp=k.hp, hp=p.hp)
            h = mv.light(s, k, n=2)
            swings += 1
            s2 = mv.snap(20.0); k2 = self.knight(s2)
            self.rec("swing_done", dealt=h.dmg, taken=h.taken, khp=None if not k2 else k2.hp,
                     hp=s2.player.hp if s2 else None, k_anim=None if not k2 else k2.anim)
        return f"timeout (swings {swings})"

    def go(self):
        result = "?"
        try:
            self.state("start")
            self.heal_if(0.9)              # 11-12 시작 HP 671/849 — 기사 한 방 195~323 (기사 근처에선 Field.heal이 안 마심)
            r = self.walk([LURE], "광장 계단 아래 (LURE)", ignore={self.npc})   # v3: 교회에 안 들어가고 기사를 광장으로
            self.state("lure")
            if r not in ("arrived",) and not (isinstance(r, str) and r.startswith("cleared")):
                self.say(f"  다가가기: {r} — 그래도 싸움 시작")
            if BRAWL:
                self.two_hand()
            result = self.brawl() if BRAWL else self.duel()
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
    _args = [a for a in sys.argv[1:] if not a.startswith('--')]
    KnightTry(int(_args[0]) if _args else 257001).go()
