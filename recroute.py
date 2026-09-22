"""구역을 넘는 경로를 사람이 걸어서 기록한다.

  python recroute.py <이름>     걷는 동안 5 Hz 로 위치를 기록. Ctrl+C 로 끝.

왜 필요한가: 내비메시 길찾기는 **한 구역 안에서만** 된다 (DS1 은 구역마다 좌표계가 따로고 MSB 에 구역 간
오프셋도 없다). 화톳불 성역(m10_02) → 성벽 교회(m10_01) 처럼 구역을 넘는 이동은 길찾기로 한 번에 못 뽑는다.
그래서 사람이 한 번 걸어서 **구역이 바뀌는 지점**만 잡아 두면, 나중에 봇이
"구역 안은 내비메시 길찾기 + 구역 경계는 기록된 통과점" 으로 이어 갈 수 있다.

저장: data/routes/<이름>.json
  {"segments": [{"map": 맵ID, "points": [[x,y,z], ...]}, ...], "end": [x,y,z], "end_map": 맵ID}
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import env
import navwalk

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "routes"
MIN_STEP = 1.5      # 이만큼 움직여야 한 점으로 기록
SAVE_EVERY = 10     # **반드시 중간 저장** — 끝날 때만 저장하면 강제 종료에 전부 날아간다 (실측: 770점 손실)


def save(name, segs):
    OUT.mkdir(parents=True, exist_ok=True)
    data = {"segments": segs, "end": segs[-1]["points"][-1] if segs and segs[-1]["points"] else None,
            "end_map": segs[-1]["map"] if segs else None,
            "note": "사람이 걸어서 기록. 구역 안은 내비메시로 길찾기하고, 구역이 바뀌는 지점만 이 기록을 따른다"}
    (OUT / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__); return
    name = sys.argv[1]
    tm = env.make_telemetry({})
    segs: list[dict] = []
    last = None
    cur_map = None
    print(f"기록 시작: {name} — 걸으세요. Ctrl+C 로 끝", flush=True)
    try:
        while True:
            s = tm.snapshot(within=1.0)
            if not s or s.player.gx is None or s.player.hp <= 0:
                time.sleep(0.3); continue
            p = s.player
            here = (round(p.x, 2), round(p.y, 2), round(p.z, 2))
            if last is not None and math.dist(here, last) < MIN_STEP:
                time.sleep(0.2); continue
            found = navwalk.locate(tm, p)
            mid = found[0] if found else None
            if mid != cur_map:
                cur_map = mid
                segs.append({"map": mid, "points": []})
                print(f"  ── 구역 {mid} 진입  ({here[0]:.1f},{here[1]:.1f},{here[2]:.1f})", flush=True)
            segs[-1]["points"].append(list(here))
            segs[-1].setdefault("times", []).append(round(time.time(), 1))   # 다른 기록과 맞춰 보려면 시각이 필요하다
            last = here
            n = sum(len(sg["points"]) for sg in segs)
            if n % SAVE_EVERY == 0:
                save(name, segs)
            if n % 10 == 0:
                print(f"  {n}점  현재 {mid} ({here[0]:.1f},{here[1]:.1f},{here[2]:.1f})", flush=True)
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    if not segs:
        print("기록된 점 없음"); return
    save(name, segs)
    print(f"저장: {OUT / (name + '.json')}  구역 {len(segs)}개, 점 {sum(len(sg['points']) for sg in segs)}개")
    for sg in segs:
        print(f"   {sg['map']}: {len(sg['points'])}점  {sg['points'][0]} → {sg['points'][-1]}")


if __name__ == "__main__":
    main()
