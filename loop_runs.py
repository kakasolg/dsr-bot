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


def between_rounds(i: int) -> None:
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
    print(f"[{i}] 판 사이: HP {s.player.hp}, 소울 {souls}, 불의 제전까지 {d:.0f} m, 10 m 안 적 {len(s.hostile(10.0))}", flush=True)
    if d > 15 and souls < 500 and not s.hostile(15.0):
        control.focus_game()
        pad = control.Pad()
        mv = moves.Moves(tm, pad)
        ok = mv.darksign(missions.FIRELINK["stand"])
        pad.neutral()
        print(f"[{i}] 다크사인 {ok}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--style", default="backstep")
    a = ap.parse_args()
    for i in range(1, a.n + 1):
        between_rounds(i)
        t0 = time.time()
        r = subprocess.run([PY, "run.py", "clear-ramp", "--style", a.style], cwd=str(ROOT), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=600)
        tail = [l for l in r.stdout.splitlines() if "══ 결과" in l or "Traceback" in l]
        print(f"[{i}/{a.n}] {time.time() - t0:.0f} s  {tail[-1] if tail else r.stdout[-200:]}", flush=True)
        time.sleep(2.0)
    print("완료", flush=True)


if __name__ == "__main__":
    main()
