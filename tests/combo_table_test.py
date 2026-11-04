"""P-121 combo decision table: MoKa's cells give the right plan, and judge() names a reason for each outcome (no game).
  python tests/combo_table_test.py
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import sys
from types import SimpleNamespace as NS

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import combo_report
from souls import combo_table as T
from souls.moves import Hit

HOLLOW, SHIELD, XBOW = NS(kind="other", ranged=False), NS(kind="shield", ranged=False), NS(kind="other", ranged=True)


def check(name: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        raise SystemExit(1)


def plan(h, foe, anim):
    return T.plan(T.key(h, foe, anim, True, True))[0]


def main() -> None:
    # MoKa 11-03 cells
    check("붙은 망자 → 백스텝 콤보", plan(1.0, HOLLOW, 3000) == ["backstep_r1"])
    check("1.15–2.2 m 망자 → 약공 (봇 평가: 백스텝 헛침)", plan(1.6, HOLLOW, -1) == ["light"])
    check("1.15–2.2 m 휘두르는 중 → 안 침", plan(1.6, HOLLOW, 3000) == [])
    check("1.15–2.2 m 방패병 서 있음 → 발차기", plan(1.6, SHIELD, -1) == ["kick_combo"])
    check("붙은 망자, 백스텝만 (구르기로 대신 안 함)", "roll_r1" not in plan(2.0, HOLLOW, -1))
    check("붙은 방패병, 방패 들고 서 있음 → 발차기 콤보", plan(1.0, SHIELD, -1) == ["kick_combo"])
    check("붙은 방패병, 휘두른 직후 → 백스텝 콤보", plan(1.0, SHIELD, 3500) == ["backstep_r1"])
    check("거리 있는 망자 → 구르기 콤보", plan(3.0, HOLLOW, -1) == ["roll_r1"])
    check("거리 있는 석궁병 → 구르기 콤보 먼저", plan(4.0, XBOW, 3001)[0] == "roll_r1")
    check("먼 망자는 미정 칸", "미정" in T.plan(T.key(5.0, HOLLOW, -1, True, True))[1])

    # MoKa 11-03 "기본 약공": near and every table move blocked by floor → light; otherwise nothing
    near = T.key(1.3, XBOW, -1, True, False)
    check("붙음 + 앞 바닥 없음 → 기본 약공", T.fallback(near, ["backstep_r1: 앞에 바닥 없음"]) == "light")
    check("붙음 + 몸이 딴 데 → 대신 안 함", T.fallback(near, ["backstep_r1: 몸이 딴 데"]) is None)
    check("중간 거리 + 바닥 없음 → 대신 안 함", T.fallback(T.key(3.0, HOLLOW, -1, False, False), ["roll_r1: 앞에 바닥 없음"]) is None)
    lit = Hit("light", presses=1, dmg=40, my_anims=[(0.1, 303000)])
    check("약공 맞힘 → 성공", T.judge("light", lit, [], 1.3, 1.2, -1, 1.6)[0] == "성공")

    ghost = Hit("backstep_r1", presses=2, dmg=59, dead=True, my_anims=[(0.1, -1)])
    check("내 공격 애니 없이 피해 → 불명", T.judge("backstep_r1", ghost, [], 0.7, 1.0, -1, 1.6)[0] == "불명")

    why = T.why_not_combo("light", ["backstep_r1: 뒤에 바닥 없음"], T.key(1.0, HOLLOW, -1, False, True), 1.0)
    check(f"약공 — 콤보 못 한 이유: 바닥 ({why})", "뒤에 바닥 없음" in why)
    why = T.why_not_combo("light", [], T.key(1.6, HOLLOW, -1, True, True), 1.6)
    check(f"약공 — 콤보 안 한 이유: 거리 ({why})", "reach" in why)
    check("콤보를 썼으면 이유 없음", T.why_not_combo("backstep_r1", [], T.key(1.0, HOLLOW, -1, True, True), 1.0) is None)

    # 진입 계획 (MoKa 11-03 "플랜 없이 마구잡이")
    ek = lambda h, foe, a: T.entry_plan(T.key(h, foe, a, True, True))[0]
    check("3 m 망자 → 구르기 콤보로 진입", ek(3.0, HOLLOW, -1) == ["roll_r1"])
    check("4 m 망자 → 점프 공격 먼저", ek(4.0, HOLLOW, -1)[0] == "jump_r2")
    check("석궁병 → 구르기 먼저", ek(4.0, XBOW, -1)[0] == "roll_r1")
    check("방패병 서 있음 → 걸어서 (발차기)", ek(3.0, SHIELD, -1) == [])
    check("휘두르는 중 → 진입 안 함", ek(3.0, HOLLOW, 3000) == [])
    line = T.engage_line(3.0, HOLLOW, -1)
    check(f"계획 한 줄 ({line})", "진입 roll_r1" in line and "붙으면 backstep_r1" in line)

    # judge: one reason per outcome
    ok = Hit("backstep_r1", presses=2, dmg=70, my_anims=[(0.1, 690), (0.9, 303500)])
    check("맞히고 안 맞음 → 성공", T.judge("backstep_r1", ok, [], 1.4, 1.0, -1, 1.6)[0] == "성공")
    trade = Hit("roll_r1", presses=2, dmg=48, taken=95, my_anims=[(0.1, 710), (1.1, 303900)])
    check("맞히고 맞음 → 맞교환", T.judge("roll_r1", trade, [], 2.5, 1.0, 3000, 1.6)[0] == "맞교환")
    cut = Hit("roll_r1", presses=2, taken=126, my_anims=[(0.1, 710), (0.4, 2004)])
    v, why = T.judge("roll_r1", cut, [], 0.9, 1.0, 3004, 1.6)
    check(f"맞아서 끊김 → 실패, 이유 ({why})", v == "실패" and "끊김" in why and "휘두르는 중" in why)
    mid = Hit("backstep_r1", presses=2, taken=141, my_anims=[(0.1, 690), (0.9, 303500), (1.1, 2002)])
    check("콤보 나온 뒤 맞음 → 공격 중 끊김", "공격 중 맞아 끊김" in T.judge("backstep_r1", mid, [], 0.9, 1.0, -1, 1.6)[1])
    plain = Hit("roll_r1", presses=2, my_anims=[(0.1, 710), (1.1, 303000)])
    check("콤보 모션 안 나옴", "모션 안 나옴" in T.judge("roll_r1", plain, [], 2.5, 1.0, -1, 1.6)[1])
    far = Hit("roll_r1", presses=2, my_anims=[(0.1, 710), (1.1, 303900)])
    check("끝나고 멀어짐 → 헛침: 거리", "헛침" in T.judge("roll_r1", far, [], 2.5, 3.0, -1, 1.6)[1])
    v, why = T.judge(None, None, ["backstep_r1: 뒤에 바닥 없음"], 1.0, None, -1, 1.6)
    check(f"못 씀 → 지형 이유 ({why})", v == "못함" and "뒤에 바닥 없음" in why)

    # report groups by cell
    rows = [dict(dist="near", kind="other", state="swing", back=True, front=True, plan=["backstep_r1"], src="MoKa",
                 used="backstep_r1", verdict="성공", reason="맞힘 70, 안 맞음", dmg=70, taken=0)] * 2
    lines = combo_report.report(rows)
    check(f"report: one cell, 2 tries ({lines[0]})", lines[0].startswith("[near/other/swing 뒤O 앞O] 2번") and "성공 2" in lines[0])


if __name__ == "__main__":
    main()
