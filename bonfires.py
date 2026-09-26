"""0층 — 불 붙인 화톳불 목록. 워프(dsr_telemetry.bonfire_warp)는 안 붙인 화톳불로도 보내므로, 갈 수 있는 곳을 우리가 쌓는다.

게임 메모리에서 "불 붙임" 목록은 못 찾았다 (2026-09-25: 이벤트 플래그 bonfire_flag+0..7 전부 0, 불 붙이기 전후 ID 검색 차이 없음).
대신 **마지막 화톳불 ID** 는 확실히 읽힌다 — 쉬면 그 화톳불로 바뀐다. 그래서 쉴 때마다 그 ID 를 data/bonfires-lit.json 에 더한다.

  python bonfires.py          목록 (+ 지금 마지막 화톳불을 더함)
이름: data/dsr-bonfires.txt (DSR-Gadget Resources/Bonfires.txt)
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DATA = Path(__file__).resolve().parent / "data"
LIT = DATA / "bonfires-lit.json"
# 2026-09-25 사용자와 확인한 것 (쉬었거나 워프로 도착)
SEED = {1022960: "2026-09-24", 1012962: "2026-09-24", 1012964: "2026-09-25", 1012961: "2026-09-25"}


def names() -> dict[int, str]:
    out = {}
    try:
        for line in (DATA / "dsr-bonfires.txt").read_text(encoding="utf-8-sig").splitlines():
            k, _, v = line.strip().partition(" ")
            if k.lstrip("-").isdigit():
                out[int(k)] = v
    except OSError:
        pass
    return out


def load() -> dict[int, str]:
    try:
        d = {int(k): v for k, v in json.loads(LIT.read_text(encoding="utf-8")).items()}
    except (OSError, ValueError):
        d = {}
    return {**{k: v for k, v in SEED.items()}, **d}


def note(tm, log=print) -> int | None:
    """지금 마지막 화톳불을 목록에 더한다. 새로 더했으면 그 ID."""
    bid = tm.last_bonfire()
    if not bid or bid <= 0:
        return None
    lit = load()
    if bid in lit:
        return None
    lit[bid] = time.strftime("%Y-%m-%d")
    LIT.write_text(json.dumps({str(k): v for k, v in sorted(lit.items())}, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"   화톳불 목록에 추가: {bid} {names().get(bid, '')}")
    return bid


def main() -> None:
    import env
    note(env.make_telemetry({}))
    nm = names()
    for bid, day in sorted(load().items()):
        print(f"{bid}  {nm.get(bid, '?'):<45} {day}")


if __name__ == "__main__":
    main()
