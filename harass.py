"""
시청자 방해 시뮬레이터 — 순찰 중 무작위 시점에 몹을 소환한다 (시드 기반 = 랜덤런의 시드).

CE 브릿지의 파일 큐에 직접 명령을 넣는다 (어댑터 불필요). 플레이어 옆 6 m 에 스폰.
"""
from __future__ import annotations

import os
import random
import time
from pathlib import Path

CMD = Path(os.environ.get("CHAOS_BRIDGE_DIR") or Path(os.environ["TEMP"]) / "chzzk-souls-chaos") / "cmd.txt"

# (chrId, NpcParamId, 이름, 가중치, 마릿수)
POOL = [
    ("c4080", 40800000, "Rat", 5, 3),
    ("c4160", 41600000, "Dog", 4, 2),
    ("c4070", 40700000, "Wolf", 3, 2),
    ("c4200", 42000000, "Bat", 3, 3),
    ("c4210", 42100000, "Warhawk", 2, 1),
    ("c3000", 30000000, "Exiled Soldier", 2, 1),
    ("c4250", 42500000, "Fingercreeper", 2, 2),
    ("c4150", 41500000, "Basilisk", 1, 1),
]


def send(line: str) -> None:
    CMD.parent.mkdir(parents=True, exist_ok=True)
    # CE 쪽이 큐 파일을 읽고 비우는 찰나에 열면 Windows 공유 위반(PermissionError) — 잠깐 물러났다 다시 (한 시간 런 중 한 번꼴)
    for _ in range(20):
        try:
            with CMD.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
            return
        except PermissionError:
            time.sleep(0.05)
    print(f"harass: cmd.txt 20회 잠김 — 명령 버림: {line}", flush=True)


def spawn_near(chr_id: str, count: int = 1, offset: float = 6.0) -> None:
    for _ in range(count):
        send(f"lua chaosSpawn('{chr_id}', nil, nil, {offset})")


class Harasser:
    """interval_s 마다 확률 p 로 풀에서 하나 골라 소환. 같은 시드면 같은 순서."""

    def __init__(self, seed: int, interval_s: float = 20.0, p: float = 0.7, log=print):
        self.rng = random.Random(seed)
        self.interval = interval_s
        self.p = p
        self.log = log
        self.next_t = time.time() + interval_s
        self.events: list[dict] = []

    def tick(self) -> dict | None:
        now = time.time()
        if now < self.next_t:
            return None
        self.next_t = now + self.interval
        if self.rng.random() > self.p:
            return None
        chr_id, npc, name, _w, n = self.rng.choices(POOL, weights=[p[3] for p in POOL])[0]
        spawn_near(chr_id, n)
        ev = {"t": round(now, 3), "event": "harass", "chr": chr_id, "npc": npc, "name": name, "count": n}
        self.events.append(ev)
        self.log(f"  harass: {name} x{n}")
        return ev
