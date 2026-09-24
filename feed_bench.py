"""피드 실측 — 게임이 켜진 상태에서 직접 읽기 vs 피드.  python feed_bench.py [--secs 5]

재는 것 (같은 조건, 같은 시간):
  A. 직접: DSRTelemetry.snapshot(within=5) 를 한 틱에 3 번 (duel + reflex + care 가 각자 읽던 모양) → 틱 시간
  B. 피드: Feed.snapshot(within=5) 를 한 틱에 3 번 → 틱 시간, 아래 읽기 수(frames)
  C. watch 스레드까지: B 에 0.05 s 마다 읽는 스레드 하나를 더 얹었을 때 틱 시간
"""
from __future__ import annotations

import argparse
import statistics
import sys
import threading
import time

sys.path.insert(0, ".")
import dsr_telemetry
import feed


HZ = 20.0   # 실제 봇 루프처럼 틱 사이를 쉰다 — 안 쉬면 메인 스레드가 GIL 을 독점해 피드가 굶는다 (실측 52 ms/프레임)
AGES: list[float] = []


def ticks(snap, secs: float) -> list[float]:
    out, t_end = [], time.time() + secs
    while time.time() < t_end:
        t0 = time.time()
        for w in (5.0, 15.0, 5.0):
            s = snap(within=w)
            if s is not None:
                AGES.append((time.time() - s.t) * 1000)
        out.append((time.time() - t0) * 1000)
        rest = 1 / HZ - (time.time() - t0)
        if rest > 0:
            time.sleep(rest)
    return out


def show(name: str, ms: list[float]) -> None:
    ms = sorted(ms)
    print(f"  {name:10s} 틱 {len(ms):5d} 회  p50 {statistics.median(ms):5.2f} ms  p90 {ms[int(len(ms)*.9)]:5.2f} ms  "
          f"max {ms[-1]:5.1f} ms  (틱 사이 쉼 {HZ:.0f} Hz)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--secs", type=float, default=5.0)
    ap.add_argument("--hz", type=float, default=20.0)
    a = ap.parse_args()
    global HZ
    HZ = a.hz
    tm = dsr_telemetry.DSRTelemetry({})
    s = tm.snapshot(within=40.0)
    if s is None:
        print("스냅샷 None — 로딩 중이거나 게임이 아님")
        return
    print(f"플레이어 HP {s.player.hp}  40 m 안 캐릭터 {len(s.chars)}  (한 번 읽기 {(time.time()-s.t)*1000:.1f} ms)")

    show("A 직접", ticks(tm.snapshot, a.secs))
    print(f"             프레임 나이 평균 {statistics.mean(AGES):.1f} ms")
    AGES.clear()

    f = feed.Feed(tm).start()
    fr0 = f.frames
    show("B 피드", ticks(f.snapshot, a.secs))
    print(f"             아래 읽기 {f.frames - fr0} 프레임 ({(f.frames - fr0)/a.secs:.0f} Hz), 프레임당 {f.read_ms:.1f} ms, 프레임 나이 평균 {statistics.mean(AGES):.1f} ms, {f.stats()}")
    AGES.clear()

    stop = False

    def watcher():
        while not stop:
            f.snapshot(within=5.0)
            time.sleep(0.05)
    th = threading.Thread(target=watcher, daemon=True)
    th.start()
    fr1 = f.frames
    show("C 피드+감시", ticks(f.snapshot, a.secs))
    print(f"             아래 읽기 {(f.frames - fr1)/a.secs:.0f} Hz, 프레임당 {f.read_ms:.1f} ms, 프레임 나이 평균 {statistics.mean(AGES):.1f} ms")
    stop = True
    f.stop()


if __name__ == "__main__":
    main()
