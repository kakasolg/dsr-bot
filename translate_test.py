"""translate offline test — the bot's Korean log lines shown in English on the radar / overlay.

  python translate_test.py
"""
from __future__ import annotations

import glob
import re
import sys

sys.path.insert(0, ".")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import translate as T

fails = 0


def check(name, cond):
    global fails
    print(("  ok   " if cond else "  FAIL ") + name)
    fails += 0 if cond else 1


H = re.compile("[가-힣]")
cases = {
    "휘청 → light×2 피해 75, 옆 0, 내 피해 0": "stagger punish → light×2 dealt 75, others 0, took 0",
    "먼저 치기 → light×2 피해 4, 옆 0, 내 피해 240": "first strike → light×2 dealt 4, others 0, took 240",
    "목표 바꿈: 254010 (1.0 m, 애니 3003) — 원래 목표 1.8 m": "switch target: 254010 (1.0 m, anim 3003) — original target 1.8 m",
    "끼어든 254010 처치 — 원래 목표로": "interloper 254010 killed — back to the original target",
    "후퇴 모드: guard (가장 가까운 255000 1.9 m)": "retreat mode: guard (nearest 255000 1.9 m)",
    "후퇴 모드: walk": "retreat mode: walk",
    "#6 이동: 막힘 감지 (2 s 동안 0.3 m 미만) — 앞길에 o1132 (o1132_06, 2.7 m)": "#6 move: stuck (under 0.3 m in 2 s) — o1132 (o1132_06) ahead, 2.7 m",
    "화톳불로: arrived": "to the bonfire: arrived",
    "성벽 마을": "Undead Burg",
    "no korean here": "no korean here",
}
print("규칙·사전")
for ko, en in cases.items():
    got = T.line(ko)
    check(f"{ko[:30]} → {got[:60]}", got == en)
check("None·빈 문자열", T.line(None) is None and T.line("") == "")
check("짧은 단어는 단어 경계에서만 ('나' 가 '나이프' 를 깨지 않음)", T.line("나이프 없음") == "knife none")

print("실제 로그 (data/samples)")
tot = left = 0
for f in glob.glob("data/samples/burg-bonfire-radar-*.txt"):
    for l in open(f, encoding="utf-8"):
        l = re.sub(r"^\[ *[\d.]+\] *", "", l.rstrip())
        if H.search(l):
            tot += 1
            left += bool(H.search(T.line(l)))
check(f"한국어 줄 {tot}개 중 {tot - left}개 완전 번역 (95 % 이상)", tot > 0 and left / tot < 0.05)

print("전부 통과" if not fails else f"실패 {fails}")
sys.exit(1 if fails else 0)
