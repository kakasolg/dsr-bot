"""
Recorder — 텔레메트리를 에피소드 단위 JSONL 로 기록한다.

  python record.py [--hz 10] [--within 40]

출력: bot/data/episodes/<YYYYmmdd-HHMMSS>.jsonl
  한 줄 = 한 틱: {"t", "hp", "mhp", "pos":[x,y,z], "anim", "near":[[npc, team, hp, mhp, dist, anim], ...]}
  이벤트 줄: {"t", "event": "start"|"damage"|"death"|"respawn"|"load", ...}

에피소드 경계:
  · 시작: 플레이어를 읽을 수 있게 된 순간
  · 사망: hp 가 0 이 되는 순간 → "death" 이벤트, 파일 닫고 다음 파일로
  · 로딩(플레이어 못 읽음)이 3초 넘게 지속되면 "load" 이벤트 (텔포·휴식·리스폰)

사망 직전 30초는 복기(post-mortem)의 핵심 재료라 별도로 <파일명>.death.json 에 잘라 저장한다.
"""
from __future__ import annotations

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # Windows 콘솔 cp1252 대비

import argparse
import collections
import json
import time
from pathlib import Path

from dotenv import load_dotenv  # type: ignore

import telemetry

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "episodes"


def compact(s: telemetry.Snapshot, within: float) -> dict:
    p = s.player
    return {
        "t": round(s.t, 3),
        "hp": p.hp, "mhp": p.max_hp,
        "pos": [round(p.x, 2), round(p.y, 2), round(p.z, 2)],
        "anim": p.anim,
        "near": [[c.npc_param, c.team, c.hp, c.max_hp, round(c.dist, 1), c.anim] for c in s.chars if c.dist <= within][:16],
    }


class Episode:
    def __init__(self, tail_seconds: float = 30.0, hz: float = 10.0):
        DATA.mkdir(parents=True, exist_ok=True)
        self.name = time.strftime("%Y%m%d-%H%M%S")
        self.path = DATA / f"{self.name}.jsonl"
        self.f = self.path.open("w", encoding="utf-8")
        self.tail = collections.deque(maxlen=int(tail_seconds * hz))
        self.ticks = 0
        self.started = time.time()
        self.write({"t": round(self.started, 3), "event": "start"})

    def write(self, obj: dict) -> None:
        self.f.write(json.dumps(obj, ensure_ascii=False) + "\n")

    def tick(self, row: dict) -> None:
        self.write(row)
        self.tail.append(row)
        self.ticks += 1
        if self.ticks % 50 == 0:
            self.f.flush()

    def close(self, reason: str, extra: dict | None = None) -> Path:
        self.write({"t": round(time.time(), 3), "event": "end", "reason": reason, "seconds": round(time.time() - self.started, 1), **(extra or {})})
        self.f.close()
        if reason == "death":
            (DATA / f"{self.name}.death.json").write_text(json.dumps({"episode": self.name, "tail": list(self.tail)}, ensure_ascii=False))
        return self.path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hz", type=float, default=10.0)
    ap.add_argument("--within", type=float, default=40.0)
    args = ap.parse_args()

    load_dotenv(ROOT.parent / ".env")
    tm = telemetry.Telemetry(telemetry.load_names())
    period = 1.0 / args.hz

    ep: Episode | None = None
    last_hp: int | None = None
    unreadable_since: float | None = None
    print(f"recording → {DATA}  ({args.hz} Hz, within {args.within} m). Ctrl+C 로 종료", flush=True)
    try:
        while True:
            t0 = time.time()
            s = tm.snapshot(within=args.within)
            if s is None:
                if unreadable_since is None:
                    unreadable_since = t0
                elif ep and t0 - unreadable_since > 3.0 and ep.ticks > 0:
                    ep.write({"t": round(t0, 3), "event": "load"})
                    ep.ticks = 0  # 로드 이벤트는 한 번만
                time.sleep(period)
                continue
            if unreadable_since is not None and ep is not None:
                ep.write({"t": round(t0, 3), "event": "respawn" if last_hp == 0 else "loaded"})
            unreadable_since = None

            if ep is None:
                if s.player.hp <= 0:  # 사망 직후 리스폰 전 — 새 에피소드는 살아난 뒤에
                    last_hp = 0
                    time.sleep(period)
                    continue
                ep = Episode(hz=args.hz)
                print(f"episode {ep.name} 시작 (hp {s.player.hp}/{s.player.max_hp})", flush=True)

            row = compact(s, args.within)
            hp = s.player.hp
            if last_hp is not None and hp < last_hp:
                nearest = s.hostile(20.0)
                row["event"] = "damage"
                row["dmg"] = last_hp - hp
                row["by"] = [[c.npc_param, round(c.dist, 1), c.anim] for c in nearest[:3]]
            ep.tick(row)

            if hp == 0 and last_hp not in (0, None):
                killers = [[c.npc_param, c.name, round(c.dist, 1)] for c in s.hostile(20.0)[:3]]
                path = ep.close("death", {"killers": killers})
                print(f"☠ 사망 — {path.name}  killers={killers}", flush=True)
                ep = None
            last_hp = hp
            time.sleep(max(0.0, period - (time.time() - t0)))
    except KeyboardInterrupt:
        if ep:
            ep.close("stopped")
        print("stopped")


if __name__ == "__main__":
    main()
