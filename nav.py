"""
네비게이션 프리미티브 — 글로벌 좌표의 목표 지점까지 걸어간다.

  goto(tm, pad, (x, z)) : 카메라 yaw 기준으로 스틱을 계속 조향하며 목표까지 이동.
                          2초 동안 0.3m 도 못 가면 "막힘" → 점프 + 옆걸음으로 빠져나가기 시도.
  실측 (2026-09-21): 스틱 앞 = cam_yaw 방향, 오른쪽 = +90°. 걷기 ~2.5 m/s, B 홀드 달리기 ~3.7 m/s.

── 알려진 한계 ──────────────────────────────
 · 장애물 회피 없음 (직선 조향). 웨이포인트를 촘촘히 두는 것으로 대신한다.
 · 높이(y) 는 무시한다. 낙하 위험 구간은 웨이포인트로 우회.
"""
from __future__ import annotations

import math
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import control
import env
import telemetry

YAW_OFFSET = 0.0
FLIP_X = False
SPRINT_BEYOND = 8.0     # 이보다 멀면 달리기
STUCK_WINDOW = 2.0      # 초
STUCK_MIN_PROGRESS = 0.3  # m
PROBE_FWD, PROBE_BACK, PROBE_HOLD = 0.8, 0.35, 0.45   # probe 한 주기: 전진/후퇴/정지 (초). 순증 약 0.7 m
CREEP_STICK = 0.45        # 실측(가드 든 채): 스틱 <0.4 = 정지, 0.4~0.7 = 걷기 1.64 m/s, 1.0 = 조깅 3.24 m/s. 걷기가 최저 속도
ENGAGE_STICK = 0.5        # 교전 접근도 걷기
ARRIVE_DY = 2.0         # 도착 판정에 높이도 본다 — 수평 거리만 보면 10 m 위의 경로점도 "도착"이 되어
                        # 나선형 경사에서 길을 통째로 건너뛰고 목표 아래에 서서 맞는다 (실측)
UNREACHABLE_DY = 2.5      # m — 2D 로 5 m 안인데 높이 차가 이보다 크면 절벽/층 차이


JUMP_PERIOD = 1.2       # guardjump 모드: 이 주기로 점프
JUMP_GUARD_OFF = 0.35   # 점프 직전·직후 LB 를 놓는 시간


class Mover:
    """이동 모드 상태기. 매 틱 set(mode) 로 원하는 모드를 주면 필요한 버튼 상태를 유지한다.
      walk       아무 것도 안 누름 (스태미나 회복)
      sprint     B 홀드
      guardjump  LB 홀드 + JUMP_PERIOD 마다 (LB 해제 → A 점프 → LB) — 빠르고, 점프 무적 + 가드로 보호 (엘든링)
      guard      LB 홀드만 (DSR — 점프 없음. DS1 점프는 달리기+B 라 사고만 남)
    """

    def __init__(self, pad: control.Pad):
        self.pad = pad
        self.mode = "walk"
        self.next_jump = 0.0
        self.guard_on = False
        self.jump_at = None

    def set(self, mode: str) -> None:
        now = time.time()
        if mode != self.mode:
            self.pad.sprint(mode == "sprint")
            if mode not in ("guardjump", "guard") and self.guard_on:
                self.pad.guard(False)
                self.guard_on = False
            if mode == "guardjump":
                self.next_jump = now + JUMP_PERIOD * 0.5
            self.mode = mode
        if mode == "guard":
            if not self.guard_on:
                self.pad.guard(True)
                self.guard_on = True
        elif mode == "guardjump":
            if self.jump_at is not None:
                if now - self.jump_at > JUMP_GUARD_OFF and not self.guard_on:
                    self.pad.guard(True)
                    self.guard_on = True
                    self.jump_at = None
            elif now >= self.next_jump:
                if self.guard_on:
                    self.pad.guard(False)
                    self.guard_on = False
                self.pad.jump()
                self.jump_at = now
                self.next_jump = now + JUMP_PERIOD
            elif not self.guard_on:
                self.pad.guard(True)
                self.guard_on = True

    def stop(self) -> None:
        self.pad.neutral()
        self.mode, self.guard_on, self.jump_at = "walk", False, None


BACK_PROBE = 1.4          # 뒤로 갈 때 이만큼 앞을 미리 본다 (m)
BACK_MAX_DROP = 1.2       # 그 자리 바닥이 지금보다 이만큼 넘게 낮으면 안 간다


FACE_STICK = 0.45         # 실측(가드 든 채): 0.4 미만은 회전도 안 한다(데드존), 0.45 는 0.6 s 에 84° 돌고 0.75 m 걷는다
FACE_TOL = math.radians(20)
FOOTING_R = 1.6           # 발밑 안전도를 재는 반경 (m)
FOOTING_MIN = 0.6         # 이보다 나쁘면 그 자리에서 싸우지 않는다


def footing(terrain, p, r: float = FOOTING_R):
    """지금 자리의 **발밑 안전도** — 주위 12방향 중 바닥이 있는 비율, 그리고 가장 안전한 방향.

    사용자 원칙: "애초에 위험한 위치에 있으면 안 되는 게 먼저다." 뒷걸음질하다 떨어진 뒤에 감지하는 것보다,
    낭떠러지 옆에서 싸움을 시작하지 않는 쪽이 낫다. 싸움은 몇 초씩 이어지고 그 동안 밀리고 돌게 된다."""
    if terrain is None:
        return 1.0, None
    ok, best, best_n = 0, None, -1
    for k in range(12):
        a = k * math.pi / 6
        qx, qz = p.gx + math.sin(a) * r, p.gz + math.cos(a) * r
        hit = terrain.floor_at(qx, qz, p.gy)
        good = hit is not None and hit[0] > p.gy - BACK_MAX_DROP
        if good:
            ok += 1
            # 그 방향으로 한 칸 더 갔을 때도 바닥이 있으면 더 좋은 방향
            q2 = terrain.floor_at(p.gx + math.sin(a) * r * 2, p.gz + math.cos(a) * r * 2, p.gy)
            n = 2 if (q2 is not None and q2[0] > p.gy - BACK_MAX_DROP) else 1
            if n > best_n:
                best_n, best = n, (math.sin(a), math.cos(a))
    return ok / 12.0, best


def ground_ahead(terrain, p, dx: float, dz: float, reach: float = 1.2) -> bool:
    """그 방향으로 reach m 앞에 발 디딜 바닥이 있나 (내비메시, 큰 낙차 없음). terrain 이 없으면 True.

    전투 이동(적에게 다가가기·돌아서기·빙글빙글)은 경로점이 아니라 적 쪽으로 스틱을 미는 것이라 내비메시를 벗어날 수 있다.
    실측(상인 달리기 1판): 경사로에서 싸우다 가장자리로 밀려 22 m 추락사 — 가만히 설 때(hold)만 발밑을 봤었다."""
    if terrain is None:
        return True
    n = math.hypot(dx, dz)
    if n < 1e-6:
        return True
    for step in (reach * 0.5, reach):
        qx, qz = p.gx + dx / n * step, p.gz + dz / n * step
        hit = terrain.floor_at(qx, qz, p.gy)
        if hit is None or hit[0] < p.gy - BACK_MAX_DROP:
            return False
    return True


def safe_heading(terrain, p, dx: float, dz: float, reach: float = 1.2):
    """(dx, dz) 쪽에 바닥이 있으면 그대로, 없으면 ±30°·±60° 로 틀어 본다. 다 없으면 None (멈춘다).
    경로점으로 곧장 갈 때도 쓴다 — 싸우다 경로에서 밀려난 뒤 경로점을 직선으로 향하면 그 사이가 낭떠러지일 수 있다
    (실측: 상인 달리기에서 같은 자리 (-21.9, 12.6) 에서 두 번 22 m 추락)."""
    if ground_ahead(terrain, p, dx, dz, reach):
        return dx, dz
    base = math.atan2(dx, dz)
    for deg in (30, -30, 60, -60):
        a = base + math.radians(deg)
        if ground_ahead(terrain, p, math.sin(a), math.cos(a), reach):
            return math.sin(a), math.cos(a)
    return None


def safe_back(terrain, p, dx: float, dz: float):
    """뒤로 물러날 방향을 지형에 맞춰 고른다 — 없으면 None(제자리).

    backoff·probe 의 후퇴는 적 반대쪽으로 그냥 밀 뿐이라 뒤가 낭떠러지여도 간다 (사용자: 뒷걸음질하다 낙사).
    내비메시로 BACK_PROBE 앞의 바닥을 확인하고, 막혔으면 방향을 30°씩 돌려 갈 수 있는 쪽을 찾는다."""
    if terrain is None:
        return dx, dz
    n = math.hypot(dx, dz)
    if n < 1e-6:
        return None
    base = math.atan2(dx, dz)
    for deg in (0, 30, -30, 60, -60, 90, -90, 120, -120):
        a = base + math.radians(deg)
        qx, qz = p.gx + math.sin(a) * BACK_PROBE, p.gz + math.cos(a) * BACK_PROBE
        hit = terrain.floor_at(qx, qz, p.gy)
        if hit is not None and hit[0] > p.gy - BACK_MAX_DROP:
            return math.sin(a), math.cos(a)
    return None


def goto(tm: telemetry.Telemetry, pad: control.Pad, target: tuple[float, float], tolerance: float = 1.5,
         timeout: float = 60.0, on_tick=None, log=print, sprint_always: bool = False, mode_fn=None,
         mover: "Mover | None" = None, engage_fn=None, abort_on_stuck: bool = False,
         terrain=None) -> str:
    """반환: 'arrived' | 'timeout' | 'dead' | 'lost' | 'unreachable'.
    target 은 (x, z) 또는 (x, y, z). y 를 주면 2D 로 가까운데 높이 차가 UNREACHABLE_DY 를 넘을 때 'unreachable' — 절벽 아래에서 위 점을
    밀고 있는 상황 (실내 경로의 낙하 구간을 거꾸로 갈 때). mode_fn(snapshot) -> 'walk'|'sprint'|'guardjump'|'guard' 가 매 틱 이동 모드."""
    if len(target) == 3:
        tx, ty, tz = target
    else:
        (tx, tz), ty = target, None
    t_start = time.time()
    last_progress_t, last_progress_d = t_start, None
    escapes = 0
    no_cam_since = None
    mover = mover or Mover(pad)
    probe_t0 = time.time()
    probe_off = [False]      # probe 로 전진이 안 되면 이 goto 동안은 보통 걷기로
    try:
        while True:
            now = time.time()
            if now - t_start > timeout:
                return "timeout"
            s = tm.snapshot(within=30.0)
            if s is None or s.player.gx is None or s.cam_yaw is None:
                pad.neutral()
                time.sleep(0.1)
                if now - t_start > 15 and s is None:
                    return "lost"
                if s is not None and s.cam_yaw is None:   # camadr 가 죽으면 조향 불가 — 서서 timeout 을 기다리지 않는다
                    no_cam_since = no_cam_since or now
                    if now - no_cam_since > 5:
                        log("  카메라 yaw 없음 5 s — lost")
                        return "lost"
                continue
            no_cam_since = None
            p = s.player
            if p.hp <= 0:
                pad.neutral()
                return "dead"
            dx, dz = tx - p.gx, tz - p.gz
            dist = math.hypot(dx, dz)
            if on_tick:
                on_tick(s, dist)
            if dist <= tolerance and (ty is None or abs(p.gy - ty) <= ARRIVE_DY):
                pad.neutral()
                return "arrived"

            # 막힘 감지
            if last_progress_d is None or last_progress_d - dist >= STUCK_MIN_PROGRESS:
                last_progress_d, last_progress_t = dist, now
            elif now - last_progress_t > STUCK_WINDOW:
                if abort_on_stuck:          # 후퇴 중 막히면 옆걸음(가드 내림)으로 맞지 말고 즉시 돌아서서 막는다
                    pad.neutral()
                    return "stuck"
                escapes += 1
                # 막혔는데 목표가 위/아래로 멀면 계단이 아니라 절벽·층 차이 — 계단은 막히지 않고 오르므로 막힘 뒤에만 판단
                if escapes >= 2 and ty is not None and p.gy is not None and abs(ty - p.gy) > UNREACHABLE_DY:
                    pad.neutral()
                    log(f"  막힘 + 높이 차 {ty - p.gy:+.1f} m — 못 가는 점")
                    return "unreachable"
                log(f"  stuck at {dist:.1f} m — escape #{escapes}")
                mover.set("walk")
                if env.GAME != "dsr":   # DS1 의 A 는 점프가 아니라 상호작용 (NPC 대화창이 뜨면 멈춤)
                    pad.jump()
                side = 1.0 if escapes % 2 else -1.0
                sx, sy = control.world_to_stick(dx, dz, s.cam_yaw, YAW_OFFSET, FLIP_X)
                pad.move(-sx * 0.8, -sy * 0.8)        # 벽에 박힌 채 밀지 말고 먼저 뒤로 물러난다
                time.sleep(0.5)
                pad.move(sx * 0.4 + side * 0.9, sy * 0.4)   # 옆으로 틀어 재접근
                time.sleep(0.7)
                last_progress_d, last_progress_t = dist, time.time()
                if escapes >= 6:
                    pad.neutral()
                    return "timeout"
                continue

            mode = mode_fn(s) if mode_fn else ("sprint" if (sprint_always or dist > SPRINT_BEYOND) else "walk")
            if mode == "retreat":
                pad.neutral()               # Guard 가 후퇴/도망을 원한다 — 경로 루프가 뒤로 간다
                return "retreat"
            if mode == "hold":
                # 서서 싸우기 전에 발밑부터 본다 — 낭떠러지 옆이면 자리를 옮기고 나서 싸운다 (사용자 원칙)
                fs, safe_dir = footing(terrain, p)
                if fs < FOOTING_MIN and safe_dir is not None:
                    sx, sy = control.world_to_stick(safe_dir[0], safe_dir[1], s.cam_yaw, YAW_OFFSET, FLIP_X)
                    pad.move(sx * CREEP_STICK, sy * CREEP_STICK)
                else:
                    pad.move(0.0, 0.0)      # 적이 붙었다 — 전진 대신 제자리 가드 (막힘 감지도 리셋)
                mover.set("guard")
                last_progress_d, last_progress_t = dist, now
            elif mode == "circle":
                a = now * 2.5             # 제자리 근처를 빙글빙글 (유인) — 스틱 방향을 돌린다
                if ground_ahead(terrain, p, math.sin(a + s.cam_yaw), math.cos(a + s.cam_yaw)):
                    pad.move(math.sin(a) * 0.6, math.cos(a) * 0.6)
                else:
                    pad.move(0.0, 0.0)
                mover.set("guard")
                last_progress_d, last_progress_t = dist, now
            elif mode == "backoff" and engage_fn and engage_fn(s):
                # 스태미나가 바닥나면 가드가 깨진다 — 적에게서 물러나 회복한다.
                # DS1 은 방패를 든 채로는 스태미나 회복이 거의 안 되므로, 충분히 떨어지면 가드를 내린다.
                ex, ez = engage_fn(s)
                dx2, dz2 = p.gx - ex, p.gz - ez
                far = math.hypot(dx2, dz2)
                safe = safe_back(terrain, p, dx2, dz2)
                if safe is None:
                    pad.move(0.0, 0.0)          # 뒤가 낭떠러지 — 물러나지 말고 버틴다
                else:
                    sx, sy = control.world_to_stick(safe[0], safe[1], s.cam_yaw, YAW_OFFSET, FLIP_X)
                    pad.move(sx * CREEP_STICK, sy * CREEP_STICK)
                mover.set("guard" if far < 4.0 else "walk")
                last_progress_d, last_progress_t = dist, now
            elif mode == "probe" and not probe_off[0]:
                # 사용자 원칙: 위험한 자리 근처에서는 앞으로 갔다 뒤로 갔다 하며 순증 1 m 정도로만 전진한다.
                # 곧장 걸어 들어가면 잠든 적을 한꺼번에 깨우고 도망칠 거리도 안 남는다. 가드는 내내 든 채.
                ph = (now - probe_t0) % (PROBE_FWD + PROBE_BACK + PROBE_HOLD)
                sx, sy = control.world_to_stick(dx, dz, s.cam_yaw, YAW_OFFSET, FLIP_X)
                if ph < PROBE_FWD:
                    pad.move(sx * CREEP_STICK, sy * CREEP_STICK)
                elif ph < PROBE_FWD + PROBE_BACK:
                    back = safe_back(terrain, p, -dx, -dz)
                    if back is None:
                        pad.move(0.0, 0.0)      # 뒤가 낭떠러지 — 물러나는 대신 멈춘다
                    else:
                        bx, by = control.world_to_stick(back[0], back[1], s.cam_yaw, YAW_OFFSET, FLIP_X)
                        pad.move(bx * CREEP_STICK, by * CREEP_STICK)
                else:
                    pad.move(0.0, 0.0)
                mover.set("guard")
                # 일부러 느리게 가는 것이라 막힘 판정을 **완화**하되 끄지는 않는다.
                # 껐더니 못 올라가는 턱 앞에서 0.4 m 를 영원히 왕복했다 (사용자: "같은 곳에서 빙글빙글").
                if dist < last_progress_d - 0.3:
                    last_progress_d, last_progress_t = dist, now
                elif now - last_progress_t > STUCK_WINDOW * 3:
                    log(f"  probe 로 전진 못 함 ({dist:.1f} m) — 보통 걷기로 전환")
                    probe_off[0] = True
                    last_progress_d, last_progress_t = dist, now
            elif mode == "creep":
                h = safe_heading(terrain, p, dx, dz)
                if h is None:
                    pad.move(0.0, 0.0)
                else:
                    sx, sy = control.world_to_stick(h[0], h[1], s.cam_yaw, YAW_OFFSET, FLIP_X)
                    pad.move(sx * CREEP_STICK, sy * CREEP_STICK)   # 적이 여럿 보이면 천천히 — 한꺼번에 어그로를 안 끌도록 (사용자 원칙)
                mover.set("guard")
            elif mode == "face" and engage_fn and engage_fn(s):
                ex, ez = engage_fn(s)       # 제자리에서 그 적을 바라본다 (락온 없이)
                off = 0.0
                if p.heading is not None:
                    off = (math.atan2(ex - p.gx, ez - p.gz) - (p.heading + math.pi) + math.pi) % (2 * math.pi) - math.pi
                reach = min(1.2, max(0.4, math.hypot(ex - p.gx, ez - p.gz) - 0.3))   # 적이 서 있는 데까지는 바닥이다
                if abs(off) > FACE_TOL and ground_ahead(terrain, p, ex - p.gx, ez - p.gz, reach):
                    sx, sy = control.world_to_stick(ex - p.gx, ez - p.gz, s.cam_yaw, YAW_OFFSET, FLIP_X)
                    pad.move(sx * FACE_STICK, sy * FACE_STICK)
                else:
                    pad.move(0.0, 0.0)
                mover.set("guard")
                last_progress_d, last_progress_t = dist, now
            elif mode == "engage" and engage_fn and engage_fn(s):
                ex, ez = engage_fn(s)       # 적에게 다가간다 (가드 올린 채, 걷기 — 뛰어들지 않고 오게 만든다)
                # 확인 거리는 적까지만 — 1.2 m 로 고정했더니 0.9 m 앞 적 **너머**(경사로 밖)를 보고 막혀서,
                # 돌아서지도 못하고 "돌아선다" 만 천 번 넘게 반복했다 (상인 달리기 실측)
                reach = min(1.2, max(0.4, math.hypot(ex - p.gx, ez - p.gz) - 0.3))
                if ground_ahead(terrain, p, ex - p.gx, ez - p.gz, reach):
                    sx, sy = control.world_to_stick(ex - p.gx, ez - p.gz, s.cam_yaw, YAW_OFFSET, FLIP_X)
                    pad.move(sx * ENGAGE_STICK, sy * ENGAGE_STICK)
                else:
                    pad.move(0.0, 0.0)      # 그쪽은 낭떠러지 — 적이 오게 둔다
                mover.set("guard")
                last_progress_d, last_progress_t = dist, now
            else:
                h = safe_heading(terrain, p, dx, dz)
                if h is None:
                    pad.move(0.0, 0.0)          # 어느 쪽도 바닥이 없다 — 서서 막힘 처리에 맡긴다
                else:
                    sx, sy = control.world_to_stick(h[0], h[1], s.cam_yaw, YAW_OFFSET, FLIP_X)
                    pad.move(sx, sy)
                mover.set(mode)
            pad.release_due()        # 예약된 버튼 떼기 (tap 이 자지 않으므로 여기서 처리)
            time.sleep(0.02)         # snapshot 이 4 ms 로 줄어 틱을 더 촘촘히 돌 수 있다
    finally:
        mover.stop()


if __name__ == "__main__":
    # 테스트: 카메라 방향으로 8 m 앞 지점까지 갔다가 출발점으로 복귀
    tm = telemetry.Telemetry()
    pad = control.Pad()
    s = tm.snapshot()
    p = s.player
    start = (p.gx, p.gz)
    ahead = (p.gx + 8 * math.sin(s.cam_yaw), p.gz + 8 * math.cos(s.cam_yaw))
    print(f"start={start[0]:.1f},{start[1]:.1f} → ahead={ahead[0]:.1f},{ahead[1]:.1f}")
    r = goto(tm, pad, ahead, on_tick=lambda s, d: None)
    print("leg 1:", r, "pos=", round(tm.snapshot().player.gx, 1), round(tm.snapshot().player.gz, 1))
    time.sleep(0.5)
    r = goto(tm, pad, start)
    print("leg 2:", r, "pos=", round(tm.snapshot().player.gx, 1), round(tm.snapshot().player.gz, 1))
