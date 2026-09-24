"""feed.Feed 논리 테스트 — 게임 없이 가짜 텔레메트리로.  python feed_test.py"""
from __future__ import annotations

import sys
import threading
import time

sys.path.insert(0, ".")
import feed
from telemetry import Chr, Snapshot


class Fake:
    """snapshot() 마다 READ_S 걸리고, 호출 수를 센다. 적 셋: 2 m / 10 m / 60 m."""
    READ_S = 0.004

    def __init__(self):
        self.calls = 0
        self.lock = threading.Lock()
        self.loading = False

    def snapshot(self, within=60.0):
        with self.lock:
            self.calls += 1
        time.sleep(self.READ_S)
        if self.loading:
            return None
        p = Chr(1, 0, 0, 659, 659, 0, 0, 0)
        cs = [Chr(10, 254000, 6, 75, 75, 2, 0, 0, dist=2.0), Chr(11, 254000, 6, 75, 75, 10, 0, 0, dist=10.0),
              Chr(12, 254000, 6, 75, 75, 60, 0, 0, dist=60.0)]
        return Snapshot(t=time.time(), player=p, chars=[c for c in cs if c.dist <= within], cam_yaw=0.0)

    def right_weapon(self):
        return 1000


def main() -> None:
    fk = Fake()
    f = feed.Feed(fk).start()
    assert f.frames >= 1, "첫 프레임을 못 받음"

    # 1) within 으로 걸러진다 / 위임된다
    s = f.snapshot(within=5.0)
    assert [c.ptr for c in s.chars] == [10], s.chars
    assert f.right_weapon() == 1000

    # 2) 여러 층이 동시에 100 번 읽어도 아래 읽기는 프레임 수만큼만
    c0, fr0 = fk.calls, f.frames
    t0 = time.time()
    for _ in range(100):
        f.snapshot(within=5.0)
        f.snapshot(within=15.0)
        f.snapshot(within=40.0)
    dt = time.time() - t0
    under = fk.calls - c0
    print(f"300 회 스냅샷 {dt*1000:.0f} ms, 아래 읽기 {under} 회 (예전엔 300 회 = {300*Fake.READ_S*1000:.0f} ms)")
    assert under <= 300 * 0.5, under

    # 3) 반경 밖은 직접 읽는다
    d0 = f.served["direct"]
    s = f.snapshot(within=200.0)
    assert [c.ptr for c in s.chars] == [10, 11, 12] and f.served["direct"] == d0 + 1

    # 4) 낡은 프레임은 안 준다: 읽기를 멈추게 한 뒤 요청하면 기다렸다 None 이 아니라 새 프레임
    f.stop()
    time.sleep(0.1)
    assert not f.alive()
    s = f.snapshot(within=5.0)          # 스레드 죽음 → 직접 폴백
    assert s is not None and f.served["direct"] == d0 + 2

    # 5) 로딩 중 None
    f2 = feed.Feed(fk).start()
    fk.loading = True
    time.sleep(0.05)
    assert f2.snapshot(within=5.0) is None
    fk.loading = False
    time.sleep(0.05)
    assert f2.snapshot(within=5.0) is not None
    f2.stop()
    print("통계", f.stats())
    print("OK")


if __name__ == "__main__":
    main()
