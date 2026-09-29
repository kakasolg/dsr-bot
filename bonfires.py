"""0층 — 불 붙인 화톳불 목록, **캐릭터마다 따로**. 워프(dsr_telemetry.bonfire_warp)는 안 붙인 화톳불로도 보내므로, 갈 수 있는 곳을 우리가 쌓는다.

게임 메모리에서 "불 붙임" 목록은 못 찾았다 (2026-09-25: 이벤트 플래그 bonfire_flag+0..7 전부 0, 불 붙이기 전후 ID 검색 차이 없음).
대신 **마지막 화톳불 ID** 는 확실히 읽힌다 — 쉬면 그 화톳불로 바뀐다. 그래서 쉴 때마다 그 ID 를 data/bonfires-lit.json 에 더한다
(봇의 farm.rest, 그리고 사람이 플레이할 때는 radar.py 발신기).

  python bonfires.py          지금 캐릭터의 목록 (+ 지금 마지막 화톳불을 더함)

파일 모양: {"캐릭터 이름": {"화톳불 ID": "더한 날"}}. 캐릭터 = 게임 속 이름(dsr_telemetry.char_name).
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
# 2026-09-25 사용자와 확인한 것 (쉬었거나 워프로 도착) — 봇을 만들며 쓴 캐릭터 것
LEGACY_CHAR = "Knight bot"
SEED = {1022960: "2026-09-24", 1012962: "2026-09-24", 1012964: "2026-09-25", 1012961: "2026-09-25"}

# ── 알려진 한계 ──────────────────────────────
#  · 캐릭터를 이름으로만 구별한다 — 이름이 같은 캐릭터 둘은 목록을 같이 쓴다. 새 캐릭터에는 다른 이름을 줄 것.
#  · 예전엔 목록이 PC에 하나라 새 캐릭터에게도 LEGACY_CHAR 가 붙인 4곳이 워프 목록에 나왔다 (2026-09-28 MoKa 질문으로 발견).


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


def _read() -> dict[str, dict[int, str]]:
    try:
        raw = json.loads(LIT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    if raw and all(str(k).lstrip("-").isdigit() for k in raw):
        raw = {LEGACY_CHAR: raw}                          # the old single-list file was LEGACY_CHAR's
    out = {str(c): {int(k): v for k, v in (d or {}).items()} for c, d in raw.items() if isinstance(d, dict)}
    out[LEGACY_CHAR] = {**SEED, **out.get(LEGACY_CHAR, {})}
    return out


def load(char: str | None) -> dict[int, str]:
    """{bonfire ID: date} this character has rested at. Unknown / unreadable character → empty (nothing to warp to)."""
    return dict(_read().get(char, {})) if char else {}


def note_id(char: str | None, bid: int | None, log=print) -> int | None:
    """Add bid to char's list. → bid if it was new, else None."""
    if not char or not bid or bid <= 0:
        return None
    every = _read()
    lit = every.setdefault(char, {})
    if bid in lit:
        return None
    lit[bid] = time.strftime("%Y-%m-%d")
    LIT.parent.mkdir(parents=True, exist_ok=True)
    LIT.write_text(json.dumps({c: {str(k): v for k, v in sorted(d.items())} for c, d in sorted(every.items())},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"   화톳불 목록에 추가 ({char}): {bid} {names().get(bid, '')}")
    return bid


def note(tm, log=print) -> int | None:
    """지금 캐릭터의 마지막 화톳불을 그 캐릭터 목록에 더한다. 새로 더했으면 그 ID."""
    return note_id(tm.char_name(), tm.last_bonfire(), log)


def main() -> None:
    import env
    tm = env.make_telemetry({})
    char = tm.char_name()
    note(tm)
    nm = names()
    print(f"캐릭터: {char!r}")
    for bid, day in sorted(load(char).items()):
        print(f"{bid}  {nm.get(bid, '?'):<45} {day}")


if __name__ == "__main__":
    main()
