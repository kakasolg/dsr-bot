"""steam_state offline test — which Steam user's offline setting counts, and the offline verdict. No Steam, no game.

  python tests/steam_state_test.py
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import steam_state as S

fails = 0


def check(name, cond):
    global fails
    print(("  ok   " if cond else "  FAIL ") + name)
    fails += 0 if cond else 1


def user(sid, name, offline, recent=None):
    extra = f'\n\t\t"MostRecent"\t\t"{recent}"' if recent is not None else ""
    return f'''\t"{sid}"\n\t{{\n\t\t"AccountName"\t\t"{name}"\n\t\t"WantsOfflineMode"\t\t"{offline}"{extra}\n\t}}\n'''


def vdf(*users):
    return '"users"\n{\n' + "".join(users) + "}\n"


print("loginusers.vdf")
check("사용자 하나 → 그 값", S.parse_loginusers(vdf(user(1, "a", 1))) is True)
check("MostRecent 사용자 값", S.parse_loginusers(vdf(user(1, "a", 1, 0), user(2, "b", 0, 1))) is False)
check("MostRecent 소문자 키도", S.parse_loginusers(vdf(user(1, "a", 0), user(2, "b", 1)).replace('"WantsOfflineMode"\t\t"1"',
      '"WantsOfflineMode"\t\t"1"\n\t\t"mostrecent"\t\t"1"')) is True)
check("MostRecent 없으면 AutoLoginUser", S.parse_loginusers(vdf(user(1, "a", 0), user(2, "B", 1)), auto_login="b") is True)
check("여럿인데 고를 수 없음 → None", S.parse_loginusers(vdf(user(1, "a", 0), user(2, "b", 1))) is None)
check("설정 줄 없음 → None", S.parse_loginusers('"users"\n{\n\t"1"\n\t{\n\t\t"AccountName"\t\t"a"\n\t}\n}') is None)
check("빈 파일 → None", S.parse_loginusers("") is None)

print("판정")
check("설정 오프라인 + 연결 0 → offline", S.judge(True, True, 0, 0)["offline"] is True)
check("설정 온라인 → False", S.judge(False, True, 0, 0)["offline"] is False)
check("설정 오프라인이어도 steam.exe 외부 연결 → False", S.judge(True, True, 2, 0)["offline"] is False)
check("게임 외부 연결 → False", S.judge(True, True, 0, 1)["offline"] is False)
check("Steam 안 켜짐 → None (모름 = 오프라인 아님)", S.judge(True, False, None, 0)["offline"] is None)
check("설정 못 읽음 → None", S.judge(None, True, 0, 0)["offline"] is None)
check("못 읽어도 온라인 증거가 있으면 False", S.judge(None, True, 3, 0)["offline"] is False)
check("이유 목록", S.judge(True, True, 0, 0)["why"] == ["Steam set offline", "steam.exe 0 outside conn", "game 0 outside conn"])

print("외부 주소")
check("127.x 는 안쪽", not S._outside(bytes([127, 0, 0, 1])))
check("0.0.0.0 은 안쪽", not S._outside(bytes(4)))
check("공인 IPv4 는 바깥", S._outside(bytes([155, 133, 1, 2])))
check("::1 은 안쪽", not S._outside(bytes(15) + b"\1"))
check("::ffff:127.0.0.1 은 안쪽", not S._outside(bytes(10) + b"\xff\xff\x7f\0\0\1"))
check("IPv6 공인은 바깥", S._outside(b"\x26\x02" + bytes(13) + b"\1"))

v = S.check()
check(f"check()는 예외 없이 형태를 돌려줌 ({v['offline']}: {', '.join(v['why'])})", v["offline"] in (True, False, None) and v["why"])

print("실패 0" if not fails else f"실패 {fails}")
sys.exit(1 if fails else 0)
