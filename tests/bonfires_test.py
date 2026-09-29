"""bonfires offline test — lit bonfires are kept per character; the old single list belongs to LEGACY_CHAR. No game.

  python tests/bonfires_test.py
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import json
import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import bonfires as B

fails = 0


def check(name, cond):
    global fails
    print(("  ok   " if cond else "  FAIL ") + name)
    fails += 0 if cond else 1


tmp = Path(tempfile.mkdtemp())
B.LIT = tmp / "bonfires-lit.json"
quiet = lambda m: None

print("파일 없음")
check("봇 캐릭터는 기본 4곳", set(B.load(B.LEGACY_CHAR)) == set(B.SEED))
check("새 캐릭터는 빈 목록", B.load("NewGuy") == {})
check("캐릭터 모름(None) → 빈 목록", B.load(None) == {})

print("예전 형식 파일 (캐릭터 구분 없음)")
B.LIT.write_text(json.dumps({"1022961": "2026-09-26"}), encoding="utf-8")
check("예전 목록은 봇 캐릭터 것 + 기본 4곳", set(B.load(B.LEGACY_CHAR)) == set(B.SEED) | {1022961})
check("새 캐릭터에겐 안 보임", B.load("NewGuy") == {})

print("더하기")
check("새 캐릭터가 쉰 화톳불 → 그 캐릭터 목록에", B.note_id("NewGuy", 1812960, log=quiet) == 1812960)
check("같은 것 다시 → None", B.note_id("NewGuy", 1812960, log=quiet) is None)
check("새 캐릭터 목록", set(B.load("NewGuy")) == {1812960})
check("봇 캐릭터 목록은 그대로", set(B.load(B.LEGACY_CHAR)) == set(B.SEED) | {1022961})
saved = json.loads(B.LIT.read_text(encoding="utf-8"))
check("파일이 캐릭터별 모양으로 바뀜", set(saved) == {B.LEGACY_CHAR, "NewGuy"} and "1022961" in saved[B.LEGACY_CHAR])
check("캐릭터 모름·ID 없음 → 안 더함", B.note_id(None, 1022960, log=quiet) is None and B.note_id("NewGuy", -1, log=quiet) is None)


class Tm:
    def char_name(self):
        return "Third"

    def last_bonfire(self):
        return 1012962


check("note(tm) 는 tm 의 캐릭터에", B.note(Tm(), log=quiet) == 1012962 and set(B.load("Third")) == {1012962})

print("실패 0" if not fails else f"실패 {fails}")
sys.exit(1 if fails else 0)
