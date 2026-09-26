"""clear-ramp 를 N 판 반복 — 판 사이에 HP·주변 적·소울을 보고 불의 제전으로 돌아간 뒤 시작한다.

  python loop_runs.py --n 10 --style backstep

판 사이 규칙 (2026-09-24 실수에서): 죽었으면 부활을 기다리고, 10 m 안에 깨어 있는 적이 있으면 30 s 까지 기다리고,
불의 제전에서 15 m 넘게 떨어져 있으면 소울 1500 아래·적 없음일 때만 다크사인 (아니면 run.py 가 걸어 올라간다).
결과는 style_report.py 로 본다.
"""
from __future__ import annotations

import argparse
import math
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, ".")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
PY = str(ROOT / ".venv" / "Scripts" / "python.exe")
RUN_TIMEOUT = 900       # 한 판 상한 (s) — burg-loop 한 판이 300~470 s


def between_rounds(i: int, mission: str) -> None:
    import control
    import env
    from souls import missions, moves
    tm = env.make_telemetry({})
    t0 = time.time()
    while time.time() - t0 < 60:
        s = tm.snapshot(within=15.0)
        if s and s.player.hp and s.player.hp > 0:
            break
        time.sleep(1.0)
    s = tm.snapshot(within=15.0)
    if s is None:
        print(f"[{i}] 스냅샷 없음", flush=True)
        return
    t0 = time.time()
    while time.time() - t0 < 30:
        awake = [c for c in s.hostile(10.0) if c.anim not in (-1, None)]
        if not awake:
            break
        time.sleep(1.0)
        s = tm.snapshot(within=15.0) or s
    d = math.dist((s.player.x, s.player.y, s.player.z), tuple(missions.FIRELINK["stand"]))
    souls = tm.souls() or 0
    lb = tm.last_bonfire()
    print(f"[{i}] 판 사이: HP {s.player.hp}, 소울 {souls}, 화톳불 {lb}, 불의 제전까지 {d:.0f} m, 10 m 안 적 {len(s.hostile(10.0))}", flush=True)
    # burg-loop(to_firelink 로 걸어서 귀환)는 화톳불을 안 바꾸니 보통 여기 안 걸린다.
    # 화톳불에서 멀면 게임의 화톳불 워프(dsr_telemetry.bonfire_warp)로 불의 제전에 — 다크사인과 달리 소울·인간성을 안 잃는다
    # (2026-09-25: 예전 다크사인이 판 시작마다 소울을 날렸다). 퀵 종료는 자리를 안 바꿔 소용없다.
    # 적이 있어도 워프한다 — 게임의 화톳불 워프는 시전 동작 없이 곧장 로딩이라 옆 적이 끊을 수 없다(다크사인과 다름).
    # 적 조건을 두었더니 유령 254014·깨어 있는 망자 때문에 워프를 건너뛰고 137 m 떨어진 채 판을 시작해 휴식에 실패했다 (2026-09-25)
    if d > 15:
        ok = tm.bonfire_warp(missions.FIRELINK_ID)
        print(f"[{i}] 불의 제전으로 워프 {ok}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--style", default="backstep")
    ap.add_argument("--mission", default="clear-ramp", choices=["clear-ramp", "burg-bonfire", "burg-loop"])
    a = ap.parse_args()
    for i in range(1, a.n + 1):
        between_rounds(i, a.mission)
        t0 = time.time()
        try:
            r = subprocess.run([PY, "run.py", a.mission, "--style", a.style], cwd=str(ROOT), capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=RUN_TIMEOUT)
            out = r.stdout
        except subprocess.TimeoutExpired as ex:
            # 한 판이 멈췄다고 세트 전체가 죽으면 안 된다 (2026-09-25: 턱 위 낙사 반복 뒤 멈춰 1판에서 세트가 끝났다).
            # 그 판은 시간 초과로 적고, 게임이 타이틀에 있을 수 있으니 이어하기를 눌러 둔다
            out = (ex.stdout or b"").decode("utf-8", "replace") if isinstance(ex.stdout, bytes) else (ex.stdout or "")
            out += "\n══ 결과: 시간 초과"
            try:
                import control
                import quitout
                control.focus_game()
                pad = control.Pad()
                quitout.reload(pad, timeout=30.0)
                pad.neutral()
            except Exception as ex2:
                print(f"[{i}] 시간 초과 뒤 이어하기 실패: {ex2!r}", flush=True)
        tail = [l for l in out.splitlines() if "══ 결과" in l or "Traceback" in l]
        print(f"[{i}/{a.n}] {time.time() - t0:.0f} s  {tail[-1] if tail else out[-200:]}", flush=True)
        time.sleep(2.0)
    print("완료", flush=True)


if __name__ == "__main__":
    main()
