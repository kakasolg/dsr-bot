"""
순찰 봇 — 웨이포인트 루프 + 결정론적 Guard.

  python patrol.py record <이름>      직접(실제 패드로) 걸으면 4 m 마다 웨이포인트를 저장 → data/routes/<이름>.json  (Ctrl+C 로 끝)
  python patrol.py run <이름> [--laps N]   웨이포인트를 A→B→A 로 왕복 순찰. 사망하면 리스폰을 기다렸다가 계속

캐릭터 상태 규칙 (에피소드마다 확인 — 사람이 게임 안에서 바꿀 수 있다):
  · 왼손이 빈 캐릭터라 **오른손 무기를 양손으로(ArmStyle 3)** 잡고 있을 때만 LB 가 가드다. 한손이면 LB 는 주먹(공격)이라
    guardjump 가 "가드+점프" 가 아니라 "주먹질+점프" 가 된다 → 시작 때 Y+RB 로 맞추고, 도중에 풀리면 가드 모드를 끈다.
  · 캐릭터는 길 위에 서 있으면 안 된다 (이 게임은 멈춘 캐릭터를 용납하지 않는다 — 쉬는 건 축복에서). 살아 있는데
    STALL_WINDOW 초 동안 STALL_MOVE m 도 못 움직이면 입력이 씹힌 것(포커스 상실·팝업·패드 재인식)으로 보고 흔들고,
    STALL_MAX 번이면 에피소드를 "stall" 로 끝내 축복으로 돌아간다 (성적 집계에서 제외).

  · 성배병(진홍)이 REST_FLASKS_LEFT 병 남으면 **무조건** 가까운 축복으로 가서 쉰다 (HP·성배병 충전) — rest_at_grace.
    축복 앞에서 Y 로 앉고 회복이 확인되면 B 로 일어난다. Y 가 안 먹으면 브릿지 warp 로 대신.

Guard (매 틱, 결정론):
  · 피격(HP 감소) 직후          → 구르기 (피격 방향 반대 대신, 진행 방향 유지한 채 B 탭)
  · HP < flask_hp_pct(50%)      → 성배병 (X). FLASK_SAFE_DIST 안에 적이 있으면 먼저 후퇴해서 거리를 벌린 뒤 마신다
  · HP < 35%                    → 후퇴: 직전 웨이포인트로 돌아감 (적에게서 멀어지는 방향)
  · 20 m 내 적 3마리 이상        → 현재 구간 달리기(스프린트) 로 통과

Policy (구간 단위): 지금은 "다음 웨이포인트로" 만. 플레이북(3단계)이 여기에 붙는다.
기록: record.py 와 같은 형식으로 data/episodes/ 에 에피소드를 남긴다 (사망 시 death.json).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import control
import env
import nav
import telemetry
from record import Episode, compact

ROOT = Path(__file__).resolve().parent
ROUTES = ROOT / "data" / "routes"
STALL_WINDOW = 4.0    # 초 — 성배병(1.5 s)·경직/넘어짐(최대 3.5 s 실측)보다 길게
STALL_MOVE = 0.5      # m
STALL_MAX = 3         # 이만큼 흔들어도 안 움직이면 에피소드 종료
RETREAT_DIST = 8.0     # 후퇴/도망 때 뒤로 달리는 거리 (m) — 경로를 따라 이만큼 떨어진 점까지 한 번에
ENEMY_ATTACK_ANIMS = range(3000, 3500)   # DS1 적 공격 애니 (실측: 3000/3001/3005/3007/3008 직후 피격)


def player_locked(anim) -> bool:
    """내가 행동 불능인 애니 — 이때 넣는 공격 입력은 버려지거나 버퍼돼서 경직 풀리자마자 멋대로 나간다 (2연타 적에게 그대로 맞음).
    실측(16 에피소드, 피격 이벤트와 대조): 2000~2052 피격 경직(0.4~0.9 s), 160 hold 중 1.5 s 경직(가드 브레이크로 추정),
    7585~7587 에스트. 가드 피격(710~712)과 내 공격(303xxx)은 제외 — 막고→한 대 / 콤보가 입력 버퍼에 기대고 있다."""
    a = anim or 0
    return 2000 <= a < 2100 or a == 160 or 7585 <= a <= 7587
FLASK_SAFE_DIST = 4.0  # m — 이 안에 적이 있으면 마시다 맞는다(1.5 s) → 후퇴로 거리부터 벌린다
REST_FLASKS_LEFT = 1   # 성배병이 이만큼 남으면 무조건 축복에 가서 쉰다 (사용자 규칙 — 학습 대상 아님)


def record_route(name: str, spacing: float = 4.0) -> None:
    """사람이 걷는 동안 spacing m 마다 좌표를 저장한다. 점이 생길 때마다 파일을 쓰므로 프로세스를 죽여도 잃지 않는다.
    DSR: 마지막 화톳불 ID 가 바뀌면(= 새 화톳불에서 쉼) 그 자리를 bonfires 에 기록하고, 애니메이션 변화도 찍는다 (앉기 애니 ID 확인용)."""
    import env
    ROUTES.mkdir(parents=True, exist_ok=True)
    tm = env.make_telemetry({})
    pts: list[list[float]] = []
    bonfires: list[dict] = []
    last_bf = tm.last_bonfire() if hasattr(tm, "last_bonfire") else None
    last_anim = None
    out = ROUTES / f"{name}.json"
    def save():
        doc = {"name": name, "game": env.GAME, "points": pts}
        if bonfires or last_bf:
            doc["bonfires"] = bonfires or [{"id": last_bf, "pos": pts[0] if pts else None}]
        out.write_text(json.dumps(doc, ensure_ascii=False, indent=1))
    print(f"경로 녹화 시작: {name} ({env.GAME}) — 걸으세요. {spacing} m 마다 저장. Ctrl+C 로 종료. 시작 화톳불={last_bf}", flush=True)
    try:
        while True:
            s = tm.snapshot(within=1.0)
            if s and s.player.gx is not None:
                x, y, z = s.player.gx, s.player.gy, s.player.gz
                if not pts or math.hypot(x - pts[-1][0], z - pts[-1][2]) >= spacing:
                    pts.append([round(x, 2), round(y, 2), round(z, 2)])
                    print(f"  #{len(pts)} ({x:.1f}, {y:.1f}, {z:.1f}) hp={s.player.hp} hostile20={len(s.hostile(20))}", flush=True)
                    save()
                if s.player.anim != last_anim:
                    print(f"    anim {last_anim} → {s.player.anim} at ({x:.1f}, {y:.1f}, {z:.1f})", flush=True)
                    last_anim = s.player.anim
                if hasattr(tm, "last_bonfire"):
                    bf = tm.last_bonfire()
                    if bf and bf != last_bf:
                        bonfires.append({"id": bf, "pos": [round(x, 2), round(y, 2), round(z, 2)]})
                        print(f"  ★ 화톳불 {bf} 에서 쉼 — 위치 ({x:.1f}, {y:.1f}, {z:.1f})", flush=True)
                        last_bf = bf
                        save()
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    save()
    print(f"저장: {out} ({len(pts)} points, bonfires {bonfires})")


class Guard:
    """결정론적 안전 규칙. 플레이북 파라미터를 읽고 순찰 루프의 매 틱에서 불린다.
    조향은 nav 가 하고 여기선 끼어들기(구르기·성배병)와 상태 플래그(후퇴·도망·스프린트)만 결정한다."""

    def __init__(self, pad: control.Pad, pb, log=print, jev=None):
        self.pad = pad
        self.pb = pb
        self.log = log
        self.jev = jev         # jev.Shadow — 없으면 규칙만
        self.last_hp: int | None = None
        self.last_flask = 0.0
        self.last_dodge = 0.0
        self.retreat = False   # HP 낮음 → 직전 웨이포인트로
        self.flee = None       # avoid 타입이 가까움 → 그 적 (Chr)
        self.crowded = False   # 적 다수 → 스프린트
        self.flask_empty = False
        self.hp_at_flask: int | None = None
        self.stamina_low = False
        self.mode = "sprint"
        self.two_hand = True   # ArmStyle 3 — False 면 LB 를 쓰지 않는다 (guardjump → sprint)
        self.last_rehand = 0.0
        self.need_rest = False # 성배병이 REST_FLASKS_LEFT 이하 → 축복으로
        self.flasks: int | None = None
        # DSR 전투 상태
        self.locked = False
        self.lock_ptr = None
        self.last_attack = 0.0
        self.last_lock = 0.0
        self.engage = None          # 교전 중인 적 (Chr)
        self.engage_since = 0.0
        self.engage_hp0 = None      # 교전 시작 때 적 HP / 내 HP — 8 s 동안 둘 다 안 변하면 닿지 않는 적(창살 너머)으로 보고 포기
        self.my_hp0 = None
        self.ignore: dict[int, float] = {}   # ptr → 무시 만료 시각
        self.last_sp: int | None = None
        self.last_block = 0.0
        self.blocks = 0
        self.engage_prev_attacking = False
        self.dist_hist: dict[int, list] = {}   # ptr → [(t, dist)] 최근 1.5 s — "다가오는 중" 판정
        self.flee_until = 0.0    # 도망 결정의 히스테리시스 (틱마다 뒤집히지 않게)
        self.fleeing = False
        self.creep = False
        self.wait_until = 0.0    # 도망 뒤 제자리에서 기다리는 시간
        self.combo_at = 0.0      # 막고 반격한 뒤 2타를 넣을 시각
        self.engage_pos0 = None  # 교전 중 우리 위치 (못 다가가는 적 판정)
        self.lured: set = set()  # 벽 치기 유인을 시도한 적
        self.ranged_since = 0.0  # 때릴 적은 없는데 맞고 있는 시각 (위층 투척병 등)
        self.circled: set = set()
        self.circle_until = 0.0
        self.retreat_block_until = 0.0
        self.pull_count = 0
        self.pull_pause = 0.0
        self.engage_move_t = 0.0

    def engage_pos(self):
        return (self.engage.x, self.engage.z) if self.engage is not None else None

    def _dsr_combat(self, s, hostile, now) -> str | None:
        """사용자 원칙 1: **막고 → 한 대**.
        lock_range 안에 (같은 층의) 적이 오면 락온하고 그 적에게 가드 올린 채 다가간다(engage) → attack_range 안이면 멈춰서(hold)
        attack_cooldown 마다 RB 한 대. 8 s 동안 적 HP 도 내 HP 도 안 변하면 닿지 않는 적(창살 너머·다른 층)으로 보고 60 s 무시.
        (다수 대응·투척 유인·측면 돌기는 다음 단계)"""
        p = s.player
        act = None
        # 막기 감지: 가드 든 상태에서 HP 는 그대로인데 스태미나가 한 틱에 8 넘게 빠지면 막은 것 (화살 포함).
        # 우리 공격/구르기 직후 0.6 s 는 제외 (그것도 스태미나를 쓴다). 막았으면 "막고 → 한 대": 쿨다운 무시하고 바로 친다.
        blocked = False
        if (self.last_sp is not None and self.mode in ("guard", "hold", "engage") and p.sp < self.last_sp - 8
                and self.last_hp is not None and p.hp >= self.last_hp and now - self.last_attack > 0.6 and now - self.last_dodge > 0.6):
            blocked = True
            self.blocks += 1
            self.last_block = now
            self.log(f"  guard: blocked (sp {self.last_sp}→{p.sp}, hostile {len(hostile)})")
        self.last_sp = p.sp
        # 같은 층의 적 전부(무시 목록도 3 m 안이면 포함 — 창살 너머라 믿었던 놈이 붙어서 때리는 일이 있었다)
        # 위층에서 던지는 적(화염병 등)은 같은 층 판정에 안 걸려 "적 없음"이 된다 → 봇이 가만히 서서 맞는다.
        # 맞고 있는데 근처에 때릴 적이 없으면 **그 자리를 뜬다** (사용자 보고: 위에서 폭탄 맞다가 사망).
        if self.last_hp is not None and p.hp < self.last_hp:
            if not any(abs(c.y - p.y) < 2.0 and c.dist <= self.pb.hold_range * 1.5 for c in hostile):
                if now - self.ranged_since > 3.0:
                    self.log(f"  guard: 때릴 적이 없는데 맞고 있다 (hp {p.hp}) — 멈추지 말 것")
                self.ranged_since = now
        floor = [c for c in hostile if abs(c.y - p.y) < 2.0]
        cands = [c for c in floor if self.ignore.get(c.ptr, 0) < now or c.dist <= 3.0]
        for c in floor:
            h = self.dist_hist.setdefault(c.ptr, [])
            h.append((now, c.dist))
            del h[:-30]
        def approaching(c):
            h = [d for t, d in self.dist_hist.get(c.ptr, []) if now - t <= 1.0]
            return len(h) >= 5 and h[0] - h[-1] > 0.8
        # 사용자 원칙 3: 몰려오면 도망 — 같은 층 6 m 안에 crowd_threshold 마리 이상이면(또는 교전 중인데 다른 놈이 8 m 안으로
        # 다가오면) 교전 풀고 경로 뒤로 달린다. 쫓아오는 속도가 달라 먼저 온 놈과 1:1 이 된다. 후퇴/도망 중엔 가드 대신 달리기.
        crowd = [c for c in cands if c.dist <= 6.0]
        # 교전 중 두 번째 놈이 3 m 안까지 붙으면 도망 (8 m 는 너무 예민해서 둘이 같이 오는 한 영원히 도망만 했다)
        second = [c for c in cands if self.engage is not None and c.ptr != self.engage.ptr and c.dist <= 3.0]
        hp_pct_now = p.hp / max(1, p.max_hp)
        # 둘이 같이 오는 건 방패로 감당된다(실측: 0 피해로 셋 처치). 기본은 crowd_threshold 이상일 때만 도망.
        # "둘째가 붙으면 도망"은 플레이북 스위치(flee_on_second) — 덧대니 같은 모퉁이에서 세 번 죽어서 기본 꺼짐
        if len(crowd) >= self.pb.crowd_threshold or (getattr(self.pb, "flee_on_second", False) and second and hp_pct_now < 0.6):
            if not self.fleeing:
                self.log(f"  guard: {len(crowd)}마리 몰려옴{' (교전 중 추가 접근)' if second else ''} — 도망")
                self.fleeing = True
            self.flee_until = now + 1.5
            self.engage = None
        if self.retreat_block_until > now:
            self.flee_until = 0.0        # 막힌 후퇴를 반복하지 않는다 — 4 s 는 서서 막는다 (HP 기준 후퇴·성배병 후퇴도 포함)
            self.fleeing = False
            self.retreat = False
        if self.flee_until > now:
            self.retreat = True
        elif self.fleeing:
            self.fleeing = False
            self.wait_until = now + 5.0   # 돌아서서 제자리 가드 — 먼저 오는 놈을 맞는다 (앞으로 걸어가 둘을 다시 만나지 않게)
            self.log("  guard: 떼어 놓음 — 돌아서서 기다린다")
        # 사용자 원칙: 여럿이 보이면 천천히 — 같은 층 15 m 안에 2마리 이상이면 반속(creep)으로 접근
        # 살금살금: 둘 이상이 25 m 안에 보이거나, 하나라도 12 m 안이면 (사용자: "적 근처에선 전진 스틱을 조금만")
        self.creep = self.engage is None and (len([c for c in cands if c.dist <= 25.0]) >= 2 or any(c.dist <= 12.0 for c in cands))
        # 사용자 원칙 2: 다수면 하나만 끌어낸다 — 교전 전, 12 m 안에 2마리 이상인데 그중 하나가 다가오기 시작하면
        # (1 s 에 0.8 m 이상 접근) 뒤로 빠져 나머지와 떼어 놓는다. 먼저 온 놈과 1:1.
        group = [c for c in cands if c.dist <= 12.0]
        if getattr(self.pb, "pull_one", False) and self.engage is None and len(group) >= 2 and not self.retreat and self.retreat_block_until <= now and self.wait_until <= now:
            comers = [c for c in group if approaching(c)]
            others = [c for c in group if not approaching(c)]
            if comers and others and min(c.dist for c in others) < 10.0 and self.pull_pause <= now:
                if not self.fleeing:
                    self.pull_count += 1
                    self.log(f"  guard: {len(group)}마리 중 1마리 다가옴 — 뒤로 빠져 유인 ({self.pull_count}회)")
                    self.fleeing = True
                    if self.pull_count >= 3:     # 세 번 빠져도 안 떨어지는 짝이면 그냥 둘을 상대한다 (방패로 감당됨). 20 s 뒤 다시 시도
                        self.pull_pause = now + 20.0
                        self.pull_count = 0
                        self.log("  guard: 유인 3회 실패 — 20 s 동안 유인 없이 싸운다")
                self.flee_until = now + 1.5      # retreat 는 아래 flee_until 로만 켠다 (막힌 후퇴 차단이 먹도록)
        if self.retreat or self.flee:
            self.mode = "retreat"
            if self.locked:
                self.pad.lock_on()
                self.locked, self.lock_ptr = False, None
            return act
        if self.creep and self.mode in ("guard", "sprint", "walk"):
            self.mode = "creep"
        if self.wait_until > now and self.engage is None and any(c.dist <= 12.0 for c in cands):
            self.mode = "hold"   # 기다리기: 가드 올린 채 제자리
        near = next((c for c in cands if self.ignore.get(c.ptr, 0) < now), None)   # 무시 중인 놈은 교전 대상이 아니다 (3 m 안이라 cands 엔 있어도)
        # 교전 대상 갱신 (죽었거나 멀어지면 해제)
        if self.engage is not None:
            cur = next((c for c in hostile if c.ptr == self.engage.ptr), None)
            if cur is None or cur.hp <= 0 or cur.dist > self.pb.lock_range * 2 or self.ignore.get(cur.ptr, 0) > now:
                if cur is not None and cur.hp <= 0:
                    self.pull_count = 0
                self.engage = None
            else:
                self.engage = cur
                if cur.hp != self.engage_hp0 or p.hp != self.my_hp0:   # 서로 HP 가 변했으면 "교착" 타이머 리셋
                    self.engage_since, self.engage_hp0, self.my_hp0 = now, cur.hp, p.hp
                if self.engage_pos0 is None or math.hypot(p.x - self.engage_pos0[0], p.z - self.engage_pos0[1]) > 0.5:
                    self.engage_pos0, self.engage_move_t = (p.x, p.z), now   # 우리가 움직이면 교착 타이머 리셋
                stuck_engage = now - self.engage_move_t > 6.0 and cur.dist > self.pb.attack_range
                if stuck_engage and cur.ptr not in self.lured:
                    # 사용자 제안 1: 홈에 낀/안 오는 적은 벽을 쳐서 소리로 끌어내 본다 — 한 번만, 4 s 기다려 본다
                    self.lured.add(cur.ptr)
                    self.pad.attack()
                    self.last_attack = now
                    self.engage_move_t = now - 2.0
                    self.log(f"  guard: 안 오는 적 — 벽 치기로 소리 유인 (npc {cur.npc_param}, {cur.dist:.1f} m)")
                    stuck_engage = False
                elif stuck_engage and cur.ptr not in self.circled:
                    # 사용자 제안 2: 그래도 안 오면 주변을 빙글빙글 돌아 움직임을 보여 준다 (3 s)
                    self.circled.add(cur.ptr)
                    self.circle_until = now + 3.0
                    self.engage_move_t = now + 1.0
                    self.log(f"  guard: 안 오는 적 — 빙글빙글 돌아 유인 (npc {cur.npc_param}, {cur.dist:.1f} m)")
                    stuck_engage = False
                lured_now = self.engage_move_t > now - 2.5 and cur.ptr in (self.lured | self.circled)   # 유인 직후엔 포기 판정 보류
                # 이미 사거리 안(붙어서 막는 중)이면 "교착"으로 포기하지 않는다 — 계속 막기만 하고 못 때려도 그건 싸움이지 닿지 않는 게 아니다.
                # 실측: 붙은 채 8 s 순수 방어(HP·적 HP 둘 다 그대로)만 하다가 이 규칙이 포기시키고, 그 직후 무방비 후퇴로 이어져 사망.
                stalemate = now - self.engage_since > 8.0 and not approaching(cur) and cur.dist > self.pb.attack_range
                if (stalemate or stuck_engage) and not lured_now:
                    self.ignore[cur.ptr] = now + 60.0
                    self.log(f"  guard: {'6 s 동안 못 다가감' if stuck_engage else '8 s 동안 서로 안 맞음'} — 닿지 않는 적, 60 s 무시 (npc {cur.npc_param}, {cur.dist:.1f} m, hp {cur.hp})")
                    self.engage = None
        engage_at = (self.pb.attack_range + 0.7) if self.wait_until > now else self.pb.lock_range
        if self.engage is None and near is not None and near.dist <= engage_at and not self.retreat and not self.flee:
            self.engage, self.engage_since, self.engage_hp0, self.my_hp0 = near, now, near.hp, p.hp
            self.engage_pos0, self.engage_move_t = (p.x, p.z), now
            act = "engage"
        # 락온은 교전 대상과 같이 간다
        want_lock = self.engage is not None
        if self.locked and not want_lock:
            self.pad.lock_on()
            self.locked, self.lock_ptr = False, None
            act = act or "unlock"
        elif want_lock and (not self.locked or self.lock_ptr != self.engage.ptr) and now - self.last_lock > 1.0:
            if self.locked:
                self.pad.lock_on()        # 다른 대상이면 풀고 다시
                time.sleep(0.1)
            self.pad.lock_on()
            self.locked, self.lock_ptr, self.last_lock = True, self.engage.ptr, now
            act = act or "lock"
        if self.engage is None and now - self.ranged_since < 3.0:
            self.mode = "sprint"      # 원거리 피격 중 — 서 있으면 계속 맞는다
            return act
        if self.engage is not None:
            sp_pct = p.sp / max(1, p.max_sp) if p.max_sp else 1.0
            attacking = (self.engage.anim or 0) in ENEMY_ATTACK_ANIMS
            recovering = self.engage_prev_attacking and not attacking   # 공격 애니가 방금 끝남 = 빈틈
            self.engage_prev_attacking = attacking
            if self.engage.dist <= self.pb.attack_range:
                self.mode = "hold"
                # 막고 → 한 대: 적이 휘두르는 중엔 절대 안 치고 가드. 막았거나(스태미나) 적 공격이 끝난 직후에 친다.
                # 적이 가만히 있으면 attack_cooldown 마다 한 대 (할로우는 느려서 선공도 통한다)
                if sp_pct > 0.25 and not attacking and not player_locked(p.anim) and (blocked or recovering or now - self.last_attack > self.pb.attack_cooldown):
                    self.pad.attack()
                    self.last_attack = now
                    self.combo_at = now + 0.55 if blocked else 0.0   # 방패에 튕기면 자세가 무너진다 (사용자) → 한 대 더
                    act = "counter" if (blocked or recovering) else "attack"
                elif self.combo_at and now >= self.combo_at and not attacking and sp_pct > 0.2:
                    self.pad.attack()
                    self.last_attack = now
                    self.combo_at = 0.0
                    act = "combo"
            else:
                self.mode = "engage"
            if self.circle_until > now:
                self.mode = "circle"
        return act

    def tick(self, s: telemetry.Snapshot) -> str | None:
        p = s.player
        now = time.time()
        hostile = s.hostile(20.0)
        action = None
        if self.last_hp is not None and p.hp < self.last_hp and now - self.last_dodge > 0.8 and env.GAME != "dsr":
            # DSR 에선 피격 구르기를 안 쓴다 — 통로 가장자리에서 굴러 12 m 아래로 떨어진 적이 있다. 방패로 막는 게 기본 (사용자 원칙)
            self.pad.dodge()
            self.last_dodge = now
            action = "dodge"
        hp_pct = p.hp / max(1, p.max_hp)
        # 성배병을 마셨는데 3초 뒤에도 HP 가 안 올랐으면 빈 병 → 이번 에피소드엔 더 안 마심
        if self.hp_at_flask is not None and now - self.last_flask > 3.0:
            if p.hp <= self.hp_at_flask:
                self.flask_empty = True
                self.log("  guard: 성배병 효과 없음 — 빈 병으로 간주")
            self.hp_at_flask = None
        self.flasks = s.flask_hp
        have_flask = (self.flasks > 0) if self.flasks is not None else (not self.flask_empty)
        want_flask = hp_pct < self.pb.flask_hp_pct and have_flask
        enemy_close = any(c.dist < FLASK_SAFE_DIST for c in hostile)
        if want_flask and not enemy_close and now - self.last_flask > 4.0:
            self.pad.use_item()
            self.last_flask = now
            self.hp_at_flask = p.hp
            action = "flask"
        # HP 낮음 → 후퇴. 마셔야 하는데 적이 붙어 있어도 후퇴 (거리를 벌려서 마신다)
        self.retreat = (hp_pct < self.pb.retreat_hp_pct and bool(hostile)) or (want_flask and enemy_close)
        self.need_rest = self.flasks is not None and self.flasks <= REST_FLASKS_LEFT
        self.flee = next((c for c in hostile if c.npc_param in self.pb.avoid_types and c.dist <= self.pb.flee_distance), None)
        self.crowded = len(hostile) >= self.pb.crowd_threshold
        # 이동 모드: 스태미나 바닥이면 걷기(회복), 적이 가까우면 가드+점프 전진, 아니면 스프린트
        sp_pct = p.sp / max(1, p.max_sp) if p.max_sp else 1.0
        if sp_pct < self.pb.stamina_walk_pct:
            self.stamina_low = True
        elif sp_pct > 0.6:
            self.stamina_low = False
        if self.stamina_low:
            self.mode = "walk"
        elif hostile or self.crowded:
            self.mode = self.pb.mode_near_enemy
        else:
            self.mode = self.pb.mode_open
        if env.GAME == "dsr" and self.mode == "guardjump":
            self.mode = "guard"   # DS1 은 점프 없음
        if env.GAME == "dsr":
            action = self._dsr_combat(s, hostile, now) or action
        if self.jev:
            # 규칙이 먼저 정하고, Jev 는 그림자(기록)거나 live 일 때만 confident 응답으로 덮어쓴다.
            # 스태미나 바닥 걷기·구르기·성배병은 항상 규칙 — Jev 는 이동 모드와 후퇴만 건드린다.
            self.jev.maybe_ask(s, self.mode, damaged=(self.last_hp is not None and p.hp < self.last_hp))
            jmode, jretreat = self.jev.override()
            if jmode and not self.stamina_low:
                self.mode = jmode
            if jretreat and hostile:
                self.retreat = True
        # 양손 상태가 풀리면 LB 는 주먹이 된다 — 가드 모드를 쓰지 않고, 적이 멀 때 다시 양손으로
        if s.arm_style is not None and (s.arm_style == 3) != self.two_hand:
            self.two_hand = s.arm_style == 3
            self.log(f"  guard: ArmStyle {s.arm_style} — {'양손, 가드 가능' if self.two_hand else '한손 → LB 는 주먹, 가드 모드 끔'}")
        if not self.two_hand:
            if self.mode == "guardjump":
                self.mode = "sprint"
            if not any(c.dist < 10 for c in hostile) and now - self.last_rehand > 5.0:
                self.pad.two_hand_right()
                self.last_rehand = now
                action = "twohand"
        self.last_hp = p.hp
        if action:
            self.log(f"  guard: {action} (hp {p.hp}/{p.max_hp}, hostile {len(hostile)})")
        return action


def run_episode(route: str, pb, harasser=None, max_seconds: float = 240.0, laps: int = 99, log=print,
                pad: control.Pad | None = None, tm: telemetry.Telemetry | None = None, jev=None) -> dict:
    """한 에피소드: 순찰하다 죽거나(사망) 시간이 다 되면 끝. 결과 dict 를 돌려준다.
    pad 는 프로세스 전체에서 **하나만** 만들어 넘겨야 한다 — 에피소드마다 새 가상 패드를 만들면 게임/Steam 이
    새 장치를 다시 잡느라 입력이 씹힌다 (실측: 2번째 에피소드부터 캐릭터가 안 움직임)."""
    rt = json.loads((ROUTES / f"{route}.json").read_text())
    pts = rt["points"]
    grace_id = rt.get("grace")
    gp = rt.get("grace_pos") or pts[0]   # 축복 정확한 위치 (워프 도착점) — 없으면 wp0
    grace_heading = None
    if rt.get("bonfires"):               # DSR: 화톳불 여러 개 — 쉴 땐 가장 가까운 것 (TODO: 지금은 첫 번째)
        grace_id = rt["bonfires"][0]["id"]
        gp = rt["bonfires"][0]["pos"]
        grace_heading = rt["bonfires"][0].get("heading")
    grace_pos = (gp[0], gp[2])
    tm = tm or env.make_telemetry(env.load_names())
    pad = pad or control.Pad()
    guard = Guard(pad, pb, log, jev=jev)
    control.focus_game()
    time.sleep(0.5)
    s0 = tm.snapshot()
    if s0 is None or s0.player.hp <= 0:   # 리셋이 꼬여 죽은 채로 들어오면 0초 사망으로 기록되어 통계를 망친다
        log("  에피소드 시작 시 사망 상태 — 리스폰 대기")
        wait_respawn(tm, pad, log)
    guard.two_hand = ensure_two_hand(tm, pad, log) if env.GAME != "dsr" else True
    # 녹화에 낙하(2D 6 m 안에서 2 m 넘게 내려감)가 있으면 그 경로는 편도 — 거꾸로는 못 올라간다
    drops = [i for i in range(1, len(pts)) if pts[i][1] - pts[i - 1][1] < -2.0 and math.hypot(pts[i][0] - pts[i - 1][0], pts[i][2] - pts[i - 1][2]) < 6.0]
    one_way = bool(drops) or bool(rt.get("one_way"))
    if drops:
        log(f"  경로에 낙하 구간 {drops} — 편도로 순찰 (끝에 닿으면 에피소드 종료)")
    order = list(range(len(pts))) if one_way else list(range(len(pts))) + list(range(len(pts) - 2, 0, -1))
    s0 = tm.snapshot()
    if s0 and s0.player.gx is not None:
        gy = s0.player.gy if s0.player.gy is not None else 0.0
        nearest = min(range(len(pts)), key=lambda i: math.hypot(pts[i][0] - s0.player.gx, pts[i][2] - s0.player.gz) + 2.0 * abs(pts[i][1] - gy))
        k0 = order.index(nearest)
        order = order[k0:] + order[:k0] if not one_way else order[k0:]
    ep = Episode()
    ep.write({"t": round(time.time(), 3), "event": "playbook", "version": pb.version})
    ep.write({"t": round(time.time(), 3), "event": "armstyle", "arm_style": tm.arm_style(), "two_hand": guard.two_hand,
              "flasks": tm.flasks()[0], "max_flasks": tm.flasks()[1]})
    t0 = time.time()
    result = {"reason": "time", "laps": 0, "seconds": 0.0, "episode": ep.name, "death_file": None}
    stop = False
    still = {"pos": None, "since": 0.0, "n": 0, "kick": 0.0}   # 멈춤 감시

    focus_check = {"t": 0.0}

    def on_tick(s, dist):
        nonlocal stop
        # 사람이 다른 창에 타이핑하면(IME 패널 등) 게임이 포그라운드를 잃고 패드 입력이 전부 죽는다 — 0.5 s 마다 확인해 되찾는다
        if time.time() - focus_check["t"] > 0.5:
            focus_check["t"] = time.time()
            if not control.game_in_front():
                control.focus_game()
        prev_hp = guard.last_hp
        a = guard.tick(s)
        # ── 멈춤 감시: 살아 있는데 안 움직이면 입력이 안 먹는 것 — 포커스 다시 잡고 B(팝업이면 닫기, 게임이면 구르기) ──
        now = time.time()
        if guard.mode in ("hold", "engage"):
            still["pos"], still["since"], still["n"] = (s.player.gx, s.player.gz), now, 0   # 싸우는 중엔 멈춤이 아니다
        elif s.player.gx is not None:
            if still["pos"] is None or math.hypot(s.player.gx - still["pos"][0], s.player.gz - still["pos"][1]) >= STALL_MOVE:
                still["pos"], still["since"], still["n"] = (s.player.gx, s.player.gz), now, 0
            elif now - still["since"] > STALL_WINDOW and now - still["kick"] > STALL_WINDOW:
                still["n"] += 1
                still["kick"] = now
                log(f"  ⚠ 멈춤 #{still['n']} ({now - still['since']:.0f} s, anim={s.player.anim}, hostile={len(s.hostile(20.0))}, "
                    f"cam={'ok' if s.cam_yaw is not None else 'none'}, arm={s.arm_style}) — 포커스·입력 재설정")
                ep.write({"t": round(now, 3), "event": "stall", "n": still["n"], "anim": s.player.anim, "hostile": len(s.hostile(20.0))})
                if still["n"] >= STALL_MAX:
                    result["reason"] = "stall"
                    stop = True
                    raise _Stop()
                control.focus_game()
                pad.dodge()
        if harasser:
            ev = harasser.tick()
            if ev:
                ep.write(ev)
        row = compact(s, 40.0)
        row["nav_dist"] = round(dist, 1)
        row["wpos"] = [round(s.player.gx, 1), round(s.player.gz, 1)] if s.player.gx is not None else None
        row["mode"] = guard.mode
        row["sp"] = s.player.sp
        if a:
            row["guard"] = a
        if guard.last_block and time.time() - guard.last_block < 0.06:
            row["blocked"] = True
        if jev:
            j = jev.take()
            if j:
                row["jev"] = {k: j[k] for k in ("mode", "mode_conf", "retreat", "threat", "rule_mode")}
        if prev_hp is not None and s.player.hp < prev_hp:
            row["event"] = "damage"
            row["dmg"] = prev_hp - s.player.hp
            row["by"] = [[c.npc_param, round(c.dist, 1), c.anim] for c in s.hostile(20.0)[:3]]
        ep.tick(row)
        if time.time() - t0 > max_seconds:
            stop = True
            raise _Stop()

    def nearest_k():
        s = tm.snapshot()
        if not s or s.player.gx is None:
            return 0
        return order.index(min(range(len(pts)), key=lambda i: math.hypot(pts[i][0] - s.player.gx, pts[i][2] - s.player.gz)))

    try:
        lap = 0
        fails = 0
        k = 0
        last_rest_try = 0.0
        while lap < laps and not stop:
            # ── 성배병이 바닥이면 축복으로 가서 쉰다 (실패하면 30 s 뒤 다시) ──
            if guard.need_rest and time.time() - last_rest_try > 30.0:
                last_rest_try = time.time()
                ok = rest_at_grace(tm, pad, guard, grace_pos, grace_id, log, on_tick, ep)
                still["since"] = time.time()   # 앉아 있던 시간을 멈춤으로 세지 않는다
                if ok:
                    k = nearest_k()            # 축복에서 다시 순찰
                    continue
            if k >= len(order):
                lap += 1
                k = 0
                ep.write({"t": round(time.time(), 3), "event": "lap", "lap": lap})
                log(f"  ✔ lap {lap}")
                if one_way:
                    result["reason"] = "end"   # 편도 완주 = 생존 성공
                    break
                continue
            idx = order[k]
            if True:
                target = (pts[idx][0], pts[idx][1], pts[idx][2])
                # 후퇴/도망: 서서 기다리지 않고 경로를 따라 RETREAT_DIST m 뒤 점까지 **한 번에** 달린다 (도중에 마음 안 바꿈).
                # 도착하면 루프 머리로 — 아직 몰려 있으면 또 뒤로, 떼어 놓였으면 먼저 온 놈과 1:1
                if (guard.retreat or guard.flee) and k > 0:
                    s_now = tm.snapshot()
                    tk = 0
                    if s_now and s_now.player.gx is not None:
                        for j in range(k - 1, -1, -1):
                            if math.hypot(pts[order[j]][0] - s_now.player.gx, pts[order[j]][2] - s_now.player.gz) >= RETREAT_DIST:
                                tk = j
                                break
                    why = "flee " + (guard.flee.name or str(guard.flee.npc_param)) if guard.flee else "retreat"
                    log(f"  {why} → wp {order[tk]} ({k - tk} 점 뒤)")
                    ep.write({"t": round(time.time(), 3), "guard": "retreat", "why": why})
                    p3 = pts[order[tk]]
                    rr = nav.goto(tm, pad, (p3[0], p3[1], p3[2]), tolerance=1.5, timeout=12, on_tick=on_tick, log=log,
                                  mode_fn=lambda s: "sprint", abort_on_stuck=True)
                    if rr == "dead":
                        result["reason"] = "death"
                        break
                    if rr == "stuck":
                        # 도망길이 막혔다 — 가드 내리고 옆걸음하다 맞는 게 사망 원인이었다. 돌아서서 막고 싸운다
                        log("  후퇴로 막힘 — 돌아서서 막는다")
                        guard.flee_until, guard.fleeing = 0.0, False
                        guard.retreat_block_until = time.time() + 4.0
                        guard.wait_until = time.time() + 4.0
                        continue
                    k = tk
                    continue
                r = nav.goto(tm, pad, target, tolerance=2.0, timeout=90, on_tick=on_tick, log=log,
                             mode_fn=lambda s: guard.mode, engage_fn=lambda s: guard.engage_pos())
                if r == "dead":
                    result["reason"] = "death"
                    break
                if r == "retreat":
                    continue      # 같은 목표를 다시 — 루프 머리의 후퇴 처리가 뒤로 데려간다
                if r == "timeout" and rt.get("interacts"):
                    s_now = tm.snapshot()
                    if s_now and any(math.hypot(it["pos"][0] - s_now.player.gx, it["pos"][2] - s_now.player.gz) < 2.5 for it in rt["interacts"]):
                        log("  녹화된 상호작용 지점 옆에서 막힘 — 문? A")
                        control.focus_game()
                        pad.tap(control.B.XUSB_GAMEPAD_A, 0.12)
                        time.sleep(2.0)
                        r = nav.goto(tm, pad, target, tolerance=2.0, timeout=30, on_tick=on_tick, log=log, mode_fn=lambda s: guard.mode)
                if r == "unreachable":
                    # 높이 차로 못 가는 점 = 십중팔구 떨어졌다 (전투 중 넉백 등). 다음 순서 점이 아니라
                    # 지금 있는 높이에서 가장 가까운 점으로 다시 잡는다 — 안 그러면 계단으로 돌아가지 못하고 영원히 "위" 점만 본다.
                    s_now = tm.snapshot()
                    if s_now and s_now.player.gx is not None:
                        gy = s_now.player.gy if s_now.player.gy is not None else 0.0
                        renear = min(range(len(order)), key=lambda j: math.hypot(pts[order[j]][0] - s_now.player.gx, pts[order[j]][2] - s_now.player.gz) + 2.0 * abs(pts[order[j]][1] - gy))
                        if renear != k:
                            log(f"  높이 차로 못 감 — 지금 높이에 맞는 점으로 재조준 (wp{order[k]} → wp{order[renear]})")
                            k = renear
                            continue
                if r in ("timeout", "lost", "unreachable"):
                    fails += 1
                    log(f"  wp {idx} 실패({r}) — 다음으로 ({fails} 연속)")
                    if fails >= 3:   # 연속으로 못 가면 조향/입력이 죽은 것 — 서 있지 말고 끝낸다
                        result["reason"] = "stall"
                        break
                else:
                    fails = 0
                k += 1
    except _Stop:
        pass
    finally:
        pad.neutral()
    result["laps"] = lap
    result["seconds"] = round(time.time() - t0, 1)
    if result["reason"] == "death":
        path = ep.close("death", {"lap": lap})
        result["death_file"] = str(path.with_suffix("")) + ".death.json"
        log(f"☠ 사망 — {result['seconds']} s, {lap} laps")
        wait_respawn(tm, pad, log)
    elif result["reason"] == "stall":
        ep.close("stall", {"laps": lap})
        log(f"⚠ 멈춤으로 종료 — {result['seconds']} s, {lap} laps (성적 제외, 축복으로 복귀)")
    elif result["reason"] == "end":
        ep.close("end", {"laps": lap})
        log(f"🏁 편도 완주 — {result['seconds']} s")
    else:
        ep.close("time", {"laps": lap})
        log(f"⏱ 시간 종료 — {result['seconds']} s, {lap} laps")
    return result


def rest_at_grace(tm, pad, guard, grace_pos, grace_id, log, on_tick, ep) -> bool:
    """가까운 축복(지금은 경로 시작 축복)으로 가서 앉는다 → HP·성배병 충전. 가는 길에도 on_tick(Guard·방해)이 돈다.
    축복 앞에서 Y 로 앉으면 메뉴가 뜨고 그 순간 회복된다 → 회복 확인 후 B 로 닫고 일어난다.
    Y 가 안 먹으면(범위 밖) 조금 더 다가가 재시도, 그래도 안 되면 브릿지 warp — 적이 붙어 있으면 워프가 막혀 실패(호출자가 30 s 뒤 재시도)."""
    cur, mx = tm.flasks()
    log(f"  성배병 {cur}/{mx} — 축복으로 가서 쉼")
    ep.write({"t": round(time.time(), 3), "event": "rest", "phase": "go", "flasks": cur})
    if nav.goto(tm, pad, grace_pos, tolerance=2.0, timeout=120, on_tick=on_tick, log=log, mode_fn=lambda s: guard.mode) == "dead":
        return False
    if env.GAME == "dsr":
        ok = rest_at_bonfire(tm, pad, (gp[0], gp[1], gp[2]), log, on_tick, ep, heading=grace_heading)
        if ok and grace_heading is None and getattr(tm, "last_rest_heading", None) is not None:
            rt["bonfires"][0]["heading"] = round(tm.last_rest_heading, 3)   # 배운 각도를 기억
            (ROUTES / f"{route}.json").write_text(json.dumps(rt, ensure_ascii=False, indent=1))
            log(f"  화톳불 각도 학습 → 경로 파일에 저장 ({tm.last_rest_heading:.2f})")
        return ok
    # 앉기 판정 반경이 0.7 m 도 안 된다 (실측: 격자 0.7 m 에서 한 점만 성공) → 정확한 지점 + 주변 4점을 0.35 m 오차로 밟으며 Y
    spots = [grace_pos] + [(grace_pos[0] + dx, grace_pos[1] + dz) for dx, dz in ((0.4, 0), (-0.4, 0), (0, 0.4), (0, -0.4))]
    for attempt, spot in enumerate(spots):
        nav.goto(tm, pad, spot, tolerance=0.35, timeout=10, on_tick=on_tick, log=log, mode_fn=lambda s: "walk")
        pad.neutral()
        time.sleep(0.3)
        control.focus_game()
        pad.interact()               # Y: 축복에 앉기 (메뉴가 뜨고 그 순간 HP·성배병이 찬다)
        time.sleep(1.5)
        s = tm.snapshot()
        cur, mx = tm.flasks()
        if s and s.player.hp >= s.player.max_hp and (mx is None or cur is None or cur >= mx):
            time.sleep(0.5)
            pad.tap(control.B.XUSB_GAMEPAD_B, 0.1)   # 메뉴 닫기 = 일어나기
            time.sleep(1.0)
            log(f"  ✔ 휴식 — HP {s.player.hp}/{s.player.max_hp}, 성배병 {cur}/{mx}")
            ep.write({"t": round(time.time(), 3), "event": "rest", "phase": "done", "flasks": cur, "spot": attempt})
            return True
        log(f"  앉기 안 됨 ({attempt + 1}/{len(spots)}, hp {s.player.hp if s else '?'}, 성배병 {cur})")
    # 브릿지 warp 는 위치만 옮기고 성배병을 채우지 않는다 (실측) — 폴백 없음, 순찰 계속하고 30 s 뒤 다시
    log("  휴식 실패 — 순찰 계속, 30 s 뒤 재시도")
    ep.write({"t": round(time.time(), 3), "event": "rest", "phase": "fail"})
    return False


SIT_ANIMS_DSR = {303000, 303040, 303300}   # DS1 화톳불 앉기/일어나기 계열 (녹화 실측: 303000→303040, 140→303300)


def rest_at_bonfire(tm, pad, spot, log, on_tick, ep, heading: float | None = None) -> bool:
    """DSR: 화톳불에서 쉰다. spot = (x, y, z) 프롬프트가 뜨는 자리, heading = 그때 캐릭터 각도 (녹화/사람 실측).
    DS1 은 프롬프트에 정면 정렬이 필요하고 제자리 회전이 안 되므로(스틱을 치면 걷는다), 걸어서 2 m 안까지 온 뒤
    **좌표 워프로 자리·각도를 스냅**하고 A → 앉음(ChrIns+0xA48 == 1, +0xA44 == 77x1) → B 로 메뉴 닫기 → 일어남 확인.
    각도를 모르면 45° 씩 8 방향을 워프로 돌려 가며 시도하고 되는 각도를 tm.last_rest_heading 에 남긴다."""
    x, y, z = spot
    if nav.goto(tm, pad, (x, z), tolerance=2.0, timeout=120, on_tick=on_tick, log=log, mode_fn=lambda s: "walk") == "dead":
        return False
    pad.neutral()
    time.sleep(0.3)
    control.focus_game()
    headings = [heading, heading] if heading is not None else [k * math.pi / 4 - math.pi for k in range(8)]   # 아는 각도는 2회 시도
    tm.last_rest_heading = None
    for h in headings:
        tm.pos_warp(x, y, z, h)
        time.sleep(0.8)
        pad.tap(control.B.XUSB_GAMEPAD_A, 0.12)
        for _ in range(14):          # 앉는 데 ~2.4 s (7720 → 7721)
            time.sleep(0.25)
            if tm.sitting():
                break
        if not tm.sitting():
            continue
        tm.last_rest_heading = h
        time.sleep(1.0)
        for _ in range(3):           # 메뉴 닫기 = 일어나기
            pad.tap(control.B.XUSB_GAMEPAD_B, 0.1)
            for _ in range(8):
                time.sleep(0.25)
                if not tm.sitting():
                    break
            if not tm.sitting():
                break
        s2 = tm.snapshot()
        log(f"  ✔ 휴식 — HP {s2.player.hp if s2 else '?'} (각도 {h:.2f})")
        ep.write({"t": round(time.time(), 3), "event": "rest", "phase": "done", "heading": round(h, 3)})
        return True
    log("  휴식 실패 (앉기 안 됨) — 순찰 계속, 30 s 뒤 재시도")
    ep.write({"t": round(time.time(), 3), "event": "rest", "phase": "fail"})
    return False


def ensure_two_hand(tm, pad, log=print, tries: int = 3) -> bool:
    """오른손 무기를 양손으로 (ArmStyle 3). 왼손이 빈 캐릭터는 이 상태에서만 LB 가 가드다 — 한손이면 LB 가 주먹(공격).
    사람이 게임 안에서 바꿀 수 있으니 에피소드마다 확인한다. 못 맞추면 False → Guard 가 가드 모드를 쓰지 않는다."""
    for i in range(tries):
        a = tm.arm_style()
        if a == 3:
            return True
        if a is None:
            log("  ArmStyle 을 읽을 수 없음 (GameDataMan 없음?) — 양손이라고 가정")
            return True
        log(f"  양손 잡기: ArmStyle {a} → Y+RB ({i + 1}/{tries})")
        control.focus_game()
        pad.two_hand_right()
        time.sleep(0.8)
    log(f"  양손 잡기 실패 (ArmStyle {tm.arm_style()}) — 이번 에피소드는 가드 없이 (guardjump → sprint)")
    return False


class _Stop(Exception):
    pass


def wait_respawn(tm, pad, log=print, timeout: float = 120.0) -> bool:
    """사망 후 리스폰까지. 게임이 "부활할 곳" 선택창을 띄우면 A 로 첫 번째(마리카의 쐐기/축복)를 고른다."""
    t0 = time.time()
    pressed = 0
    while time.time() - t0 < timeout:
        s = tm.snapshot(within=1.0)
        if s and s.player.hp > 0:
            time.sleep(3.0)
            return True
        if env.GAME != "dsr" and time.time() - t0 > 6 and pressed < 20:  # 엘든링: 사망 연출 뒤 "부활할 곳" 선택 — 오른쪽(마지막 축복) → A. DS1 은 자동
            control.focus_game()
            pad.tap(control.B.XUSB_GAMEPAD_DPAD_RIGHT, 0.1)
            time.sleep(0.3)
            pad.tap(control.B.XUSB_GAMEPAD_A, 0.1)
            pressed += 1
        time.sleep(2.0)
    log("  리스폰 대기 시간 초과")
    return False


def reset_to_grace(tm, grace_id: int, expect: tuple[float, float] | None = None, log=print, timeout: float = 60.0) -> bool:
    """축복으로 워프 → 잔존 몹 정리 + HP/성배 회복.
    로딩 중엔 플레이어를 못 읽는 게 보통이지만 짧으면 놓치므로, 기대 좌표(expect)에 도착했는지로 판정한다."""
    import harass
    harass.send(f"warp {grace_id}")
    t0 = time.time()
    saw_load = False
    while time.time() - t0 < timeout:
        s = tm.snapshot(within=1.0)
        if s is None or s.player.gx is None:
            saw_load = True
        elif s.player.hp > 0:
            if expect is not None:
                # 20 m: 축복 옆을 지나는 트롤 마차가 캐릭터를 10 m 넘게 밀어낸 적이 있다 (실측 12.9 m)
                if math.hypot(s.player.gx - expect[0], s.player.gz - expect[1]) < 20.0 and time.time() - t0 > 3.0:
                    time.sleep(2.0)
                    return True
            elif saw_load:
                time.sleep(2.0)
                return True
        time.sleep(0.5)
    log("  워프 대기 시간 초과")
    return False


def reset_episode(tm, pad, grace_id: int | None, expect: tuple[float, float] | None, log=print, start=None) -> bool:
    """에피소드 리셋 = 랜덤런의 새 캐릭터: 살아 있으면 즉사시켜 축복에서 리스폰(잔존 몹 정리, HP/성배 회복),
    그 다음 시작 축복으로 워프. 적이 근처에 있으면 워프가 막히므로 반드시 리스폰 뒤에 워프한다."""
    s = tm.snapshot(within=1.0)
    if env.GAME == "dsr":
        # DSR 리셋 = 시작 화톳불로 좌표 워프 → 앉기 (HP·에스트 충전, 적 리스폰). 죽어 있으면 자동 리스폰을 기다린다.
        if not (s and s.player.hp > 0):
            if not wait_respawn(tm, pad, log):
                return False
            time.sleep(4.0)   # 리스폰 직후 페이드/일어나기 동안은 상호작용이 안 먹는다
        if expect is not None and len(expect) >= 3:
            log("  리셋: 시작 화톳불로 워프 → 앉기")
            tm.pos_warp(expect[0], expect[1], expect[2])
            time.sleep(1.0)
            class _EP:
                def write(self, o): pass
            heading = expect[3] if len(expect) > 3 else None
            if not rest_at_bonfire(tm, pad, (expect[0], expect[1], expect[2]), log, lambda s, d: None, _EP(), heading=heading):
                log("  앉기 실패 — HP/에스트 충전 없이 시작")
        if start is not None:          # 편도 코스: 출발점이 화톳불이 아니면 거기로
            log(f"  리셋: 출발점으로 워프 {tuple(round(v, 1) for v in start[:3])}")
            tm.pos_warp(start[0], start[1], start[2], start[3] if len(start) > 3 else 0.0)
            time.sleep(1.0)
        return True
    if s and s.player.hp > 0:
        log("  리셋: 즉사 → 리스폰")
        if env.GAME == "dsr":
            tm.kill_player()          # DS1: 마지막으로 쉰 화톳불에서 자동 리스폰 (에스트 충전, 적 리스폰)
        else:
            import harass
            harass.send("activate 1337304928")
        for _ in range(20):
            time.sleep(0.5)
            s = tm.snapshot(within=1.0)
            if s and s.player.hp <= 0:
                break
    if not wait_respawn(tm, pad, log):
        return False
    if env.GAME == "dsr":
        return True
    if grace_id:
        log("  리셋: 시작 축복으로 워프")
        return reset_to_grace(tm, grace_id, expect, log)
    return True


def last_grace(tm) -> int | None:
    """GameMan+0xB30 = 마지막으로 방문한 축복 ID (Hexinton LastGrace)."""
    gm = tm.symbols.get("GameMan")
    if not gm:
        return None
    p = tm.q(int(gm, 16))
    return tm.i32(p + 0xB30) if p else None


def run_route(name: str, laps: int) -> None:
    import playbook
    r = run_episode(name, playbook.load_current(), None, max_seconds=3600, laps=laps)
    print(r)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record"); r.add_argument("name"); r.add_argument("--spacing", type=float, default=4.0)
    u = sub.add_parser("run"); u.add_argument("name"); u.add_argument("--laps", type=int, default=3)
    a = ap.parse_args()
    if a.cmd == "record":
        record_route(a.name, a.spacing)
    else:
        run_route(a.name, a.laps)
