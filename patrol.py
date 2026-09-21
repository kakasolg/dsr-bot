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
    """결정론적 안전 규칙. 순찰 루프의 매 틱에서 불린다. 이동 조향은 nav 가 하고, 여기선 끼어들기만."""

    def __init__(self, pad: control.Pad, log=print):
        self.pad = pad
        self.log = log
        self.last_hp: int | None = None
        self.last_flask = 0.0
        self.last_dodge = 0.0
        self.retreat = False

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
        if hp_pct < 0.5 and not any(c.dist < 8 for c in hostile) and now - self.last_flask > 4.0:
            self.pad.use_item()
            self.last_flask = now
            action = "flask"
        self.retreat = hp_pct < 0.35 and bool(hostile)
        self.crowded = len(hostile) >= 3
        self.last_hp = p.hp
        if action:
            self.log(f"  guard: {action} (hp {p.hp}/{p.max_hp}, hostile {len(hostile)})")
        return action


def run_route(name: str, laps: int) -> None:
    pts = json.loads((ROUTES / f"{name}.json").read_text())["points"]
    if len(pts) < 2:
        raise SystemExit("웨이포인트가 2개 이상 필요합니다")
    tm = telemetry.Telemetry(telemetry.load_names())
    pad = control.Pad()
    guard = Guard(pad)
    if not control.focus_game():
        print("경고: 게임 창을 앞으로 가져오지 못함 — 패드 입력이 안 먹을 수 있음", flush=True)
    time.sleep(0.5)
    order = list(range(len(pts))) + list(range(len(pts) - 2, 0, -1))  # A→B→A (끝점 중복 없이)
    # 지금 서 있는 곳에서 가장 가까운 지점부터 시작 (경로 끝에 서 있으면 거꾸로 출발)
    s0 = tm.snapshot()
    if s0 and s0.player.gx is not None:
        nearest = min(range(len(pts)), key=lambda i: math.hypot(pts[i][0] - s0.player.gx, pts[i][2] - s0.player.gz))
        k0 = order.index(nearest)
        order = order[k0:] + order[:k0]
        print(f"가장 가까운 지점 wp {nearest} ({math.hypot(pts[nearest][0]-s0.player.gx, pts[nearest][2]-s0.player.gz):.1f} m) 부터 시작", flush=True)
    ep = Episode()
    lap = 0
    completed = 0
    print(f"순찰 시작: {name} ({len(pts)} points), {laps} laps", flush=True)

    def on_tick(s, dist):
        guard.tick(s)
        row = compact(s, 40.0)
        row["nav_dist"] = round(dist, 1)
        ep.tick(row)

    try:
        while lap < laps:
            for k, idx in enumerate(order):
                target = (pts[idx][0], pts[idx][2])
                if guard.retreat and k > 0:
                    prev = pts[order[k - 1]]
                    print(f"  retreat → wp {order[k-1]}", flush=True)
                    nav.goto(tm, pad, (prev[0], prev[2]), tolerance=2.0, timeout=20, on_tick=on_tick)
                    time.sleep(2.0)
                r = nav.goto(tm, pad, target, tolerance=2.0, timeout=90, on_tick=on_tick)
                print(f"  wp {idx}: {r}", flush=True)
                if r == "dead":
                    ep.close("death", {"lap": lap, "wp": idx})
                    print(f"☠ 사망 (lap {lap}, wp {idx}) — 리스폰 대기", flush=True)
                    while True:
                        s = tm.snapshot(within=1.0)
                        if s and s.player.hp > 0:
                            break
                        time.sleep(1.0)
                    time.sleep(3.0)
                    ep = Episode()
                    guard = Guard(pad)
                    break
                if r in ("timeout", "lost"):
                    print(f"  wp {idx} 실패({r}) — 다음으로", flush=True)
            else:
                lap += 1
                completed += 1
                ep.write({"t": round(time.time(), 3), "event": "lap", "lap": lap})
                print(f"✔ lap {lap} 완료", flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        pad.neutral()
        ep.close("stopped", {"laps": completed})
        print(f"종료: laps={completed}")


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
