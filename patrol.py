"""
순찰 봇 — 웨이포인트 루프 + 결정론적 Guard.

  python patrol.py record <이름>      직접(실제 패드로) 걸으면 4 m 마다 웨이포인트를 저장 → data/routes/<이름>.json  (Ctrl+C 로 끝)
  python patrol.py run <이름> [--laps N]   웨이포인트를 A→B→A 로 왕복 순찰. 사망하면 리스폰을 기다렸다가 계속

Guard (매 틱, 결정론):
  · 피격(HP 감소) 직후          → 구르기 (피격 방향 반대 대신, 진행 방향 유지한 채 B 탭)
  · HP < 50% 이고 8 m 내 적 없음 → 성배병 (X)
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
import nav
import telemetry
from record import Episode, compact

ROOT = Path(__file__).resolve().parent
ROUTES = ROOT / "data" / "routes"


def record_route(name: str, spacing: float = 4.0) -> None:
    ROUTES.mkdir(parents=True, exist_ok=True)
    tm = telemetry.Telemetry()
    pts: list[list[float]] = []
    print(f"경로 녹화 시작: {name} — 실제 패드로 걸으세요. {spacing} m 마다 저장. Ctrl+C 로 종료", flush=True)
    try:
        while True:
            s = tm.snapshot(within=1.0)
            if s and s.player.gx is not None:
                x, y, z = s.player.gx, s.player.gy, s.player.gz
                if not pts or math.hypot(x - pts[-1][0], z - pts[-1][2]) >= spacing:
                    pts.append([round(x, 2), round(y, 2), round(z, 2)])
                    print(f"  #{len(pts)} ({x:.1f}, {y:.1f}, {z:.1f}) map={s.player.map_id:#x}", flush=True)
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    (ROUTES / f"{name}.json").write_text(json.dumps({"name": name, "points": pts}, ensure_ascii=False, indent=1))
    print(f"저장: {ROUTES / (name + '.json')} ({len(pts)} points)")


class Guard:
    """결정론적 안전 규칙. 플레이북 파라미터를 읽고 순찰 루프의 매 틱에서 불린다.
    조향은 nav 가 하고 여기선 끼어들기(구르기·성배병)와 상태 플래그(후퇴·도망·스프린트)만 결정한다."""

    def __init__(self, pad: control.Pad, pb, log=print):
        self.pad = pad
        self.pb = pb
        self.log = log
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

    def tick(self, s: telemetry.Snapshot) -> str | None:
        p = s.player
        now = time.time()
        hostile = s.hostile(20.0)
        action = None
        if self.last_hp is not None and p.hp < self.last_hp and now - self.last_dodge > 0.8:
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
        if (hp_pct < self.pb.flask_hp_pct and not self.flask_empty and not any(c.dist < 8 for c in hostile)
                and now - self.last_flask > 4.0):
            self.pad.use_item()
            self.last_flask = now
            self.hp_at_flask = p.hp
            action = "flask"
        self.retreat = hp_pct < self.pb.retreat_hp_pct and bool(hostile)
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
        self.last_hp = p.hp
        if action:
            self.log(f"  guard: {action} (hp {p.hp}/{p.max_hp}, hostile {len(hostile)})")
        return action


def run_episode(route: str, pb, harasser=None, max_seconds: float = 240.0, laps: int = 99, log=print) -> dict:
    """한 에피소드: 순찰하다 죽거나(사망) 시간이 다 되면 끝. 결과 dict 를 돌려준다."""
    pts = json.loads((ROUTES / f"{route}.json").read_text())["points"]
    tm = telemetry.Telemetry(telemetry.load_names())
    pad = control.Pad()
    guard = Guard(pad, pb, log)
    control.focus_game()
    time.sleep(0.5)
    order = list(range(len(pts))) + list(range(len(pts) - 2, 0, -1))
    s0 = tm.snapshot()
    if s0 and s0.player.gx is not None:
        nearest = min(range(len(pts)), key=lambda i: math.hypot(pts[i][0] - s0.player.gx, pts[i][2] - s0.player.gz))
        k0 = order.index(nearest)
        order = order[k0:] + order[:k0]
    ep = Episode()
    ep.write({"t": round(time.time(), 3), "event": "playbook", "version": pb.version})
    t0 = time.time()
    result = {"reason": "time", "laps": 0, "seconds": 0.0, "episode": ep.name, "death_file": None}
    stop = False

    def on_tick(s, dist):
        nonlocal stop
        prev_hp = guard.last_hp
        a = guard.tick(s)
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
        if prev_hp is not None and s.player.hp < prev_hp:
            row["event"] = "damage"
            row["dmg"] = prev_hp - s.player.hp
            row["by"] = [[c.npc_param, round(c.dist, 1), c.anim] for c in s.hostile(20.0)[:3]]
        ep.tick(row)
        if time.time() - t0 > max_seconds:
            stop = True
            raise _Stop()

    try:
        lap = 0
        while lap < laps and not stop:
            for k, idx in enumerate(order):
                target = (pts[idx][0], pts[idx][2])
                if (guard.retreat or guard.flee) and k > 0:
                    prev = pts[order[k - 1]]
                    why = "flee " + (guard.flee.name or str(guard.flee.npc_param)) if guard.flee else "retreat"
                    log(f"  {why} → wp {order[k-1]}")
                    ep.write({"t": round(time.time(), 3), "guard": "retreat", "why": why})
                    nav.goto(tm, pad, (prev[0], prev[2]), tolerance=2.0, timeout=20, on_tick=on_tick, log=log,
                             mode_fn=lambda s: guard.mode)
                    time.sleep(2.0)
                r = nav.goto(tm, pad, target, tolerance=2.0, timeout=90, on_tick=on_tick, log=log,
                             mode_fn=lambda s: guard.mode)
                if r == "dead":
                    result["reason"] = "death"
                    break
                if r in ("timeout", "lost"):
                    log(f"  wp {idx} 실패({r}) — 다음으로")
            else:
                lap += 1
                ep.write({"t": round(time.time(), 3), "event": "lap", "lap": lap})
                log(f"  ✔ lap {lap}")
                continue
            break
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
    else:
        ep.close("time", {"laps": lap})
        log(f"⏱ 시간 종료 — {result['seconds']} s, {lap} laps")
    return result


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
        if time.time() - t0 > 6 and pressed < 20:  # 사망 연출이 끝난 뒤부터 2초마다: 오른쪽(마지막 축복) → A
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
                if math.hypot(s.player.gx - expect[0], s.player.gz - expect[1]) < 10.0 and time.time() - t0 > 3.0:
                    time.sleep(2.0)
                    return True
            elif saw_load:
                time.sleep(2.0)
                return True
        time.sleep(0.5)
    log("  워프 대기 시간 초과")
    return False


def reset_episode(tm, pad, grace_id: int | None, expect: tuple[float, float] | None, log=print) -> bool:
    """에피소드 리셋 = 랜덤런의 새 캐릭터: 살아 있으면 즉사시켜 축복에서 리스폰(잔존 몹 정리, HP/성배 회복),
    그 다음 시작 축복으로 워프. 적이 근처에 있으면 워프가 막히므로 반드시 리스폰 뒤에 워프한다."""
    import harass
    s = tm.snapshot(within=1.0)
    if s and s.player.hp > 0:
        log("  리셋: 즉사 → 리스폰")
        harass.send("activate 1337304928")
        for _ in range(20):
            time.sleep(0.5)
            s = tm.snapshot(within=1.0)
            if s and s.player.hp <= 0:
                break
    if not wait_respawn(tm, pad, log):
        return False
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
