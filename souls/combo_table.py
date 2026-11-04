"""Combo decision table (P-121): situation → which combo, and after each one why it worked or failed.

[MoKa] 2026-11-03: "뭔가 decision model같은게 필요해 … 이 거리, 이 지형에서는 이 공격이 좋다는 것이 없는 것으로 보여."
"표만 있는게 아니고 수행후 실패 이유, 성공 이유가 들어가야해."

  key(...)    situation key: distance band · foe kind · foe state · floor behind / toward it
  plan(key)   moves to try in order + where the cell came from (a MoKa quote, or 미정 = the bot's default, not judged)
  judge(...)  after the move: verdict (성공 / 맞교환 / 실패) and one reason, from what happened (anims, damage, distance)

Used only with run.py --combo-only (duel.COMBO_ONLY). Each decision is written as a "combo" event; combo_report.py <run>
prints the table per cell (tries, hits, damage, reasons). The table is never changed automatically — MoKa reads the
report / clips and the cell is edited by hand.
"""
from __future__ import annotations

from . import moves as M

NEAR_R = 2.2      # 붙음 — MoKa "붙으면 백스텝 콤보", 1.6 → 2.2 after "지금도 거리가 가까운데 구르기 공격 하네"
BS_MAX = 1.15     # 백스텝 콤보가 닿은 거리 — 이보다 멀면(1.15–2.2 m, "reach") 약공 (봇 평가 11-03, 아래 TABLE 참고)
MID_R = 3.5       # 중간 → 구르기 (moved 2.9–5.5 m in the room); farther → 점프 (3.25 m)

# Our anim's last three digits per combo (one-handed 303xxx / two-handed 304xxx, room 11-03): the combo really came out
COMBO_ANIM = {"backstep_r1": 500, "roll_r1": 900, "jump_r2": 600}

# (dist, kind, state) → (moves in order, source). kind: shield | ranged | other. state: idle | swing | open (stagger·guard
# broken·down) | other. "*" = any. First matching row wins (most specific rows first).
TABLE = [
    # 봇 평가 (MoKa 판단 아님, 표본 작음): 백스텝 콤보는 모션이 다 나와도 1.2·1.58·1.95 m에서 헛침 3번 (125142·125647, 그놈 애니
    # 3000·2012·3500 → 물러나는 중), 0.85–1.35 m에서 맞힘 2번. 약공은 1.49–1.69 m에서 맞힘 3/3. → 1.15 m 넘으면 약공
    (("reach", "shield", "idle"), ["kick_combo"], 'MoKa 11-03 "붙어 있는데 상대가 방패가 있으면 발차기 콤보"'),
    (("reach", "*", "swing"), [], "봇 평가 11-03 130055: 휘두르는 놈에 1.17 m 약공 → 나가기 전에 맞아 끊김 −55 → 안 침 (반사가 피함)"),
    (("reach", "*", "*"), ["light"], "봇 평가 11-03: 1.15–2.2 m 백스텝 콤보 헛침 3/3, 약공 맞힘 3/3 (125142·125647)"),
    (("near", "shield", "idle"), ["kick_combo"], 'MoKa 11-03 "붙어 있는데 상대가 방패가 있으면 발차기 콤보"'),
    (("near", "shield", "*"), ["backstep_r1"], 'MoKa 11-03 "지금 방패병이 딱 백스텝 콤보 였는데" (휘두른 직후)'),
    (("near", "*", "*"), ["backstep_r1"], 'MoKa 11-03 "붙으면 백스텝 콤보" · "가까운데 구르기" 금지'),
    (("mid", "ranged", "*"), ["roll_r1", "jump_r2"], 'MoKa 11-03 "석궁병 다가 갈때 구르기 콤보로 공격 했어야지"'),
    (("mid", "*", "*"), ["roll_r1"], 'MoKa 11-03 "거리가 있으면 구르기 콤보"'),
    (("far", "ranged", "*"), ["roll_r1", "jump_r2"], 'MoKa 11-03 "미리 거리가 있을때 하면서 들어가야지"'),
    (("far", "*", "*"), ["jump_r2", "roll_r1"], "미정 (봇 기본: 멀면 점프 공격)"),
]


# 붙었는데 표의 콤보가 바닥 때문에 다 막히면 → 기본 약공 ([MoKa] 2026-11-03 "기본 약공"; 123636 경사로 끝에서 321번 "못함"
# 하고 공격 없이 서 있다 낙사). 바닥 말고 다른 이유(몸이 딴 데 등)로 못 한 때는 대신하지 않음.
NO_FLOOR_FALLBACK = ("light", 'MoKa 11-03 "기본 약공" (붙음 + 바닥 없음)')


def fallback(k: dict, skipped: list[str]) -> str | None:
    """Move to use when every table move was skipped, or None."""
    if k["dist"] in ("near", "reach") and skipped and all("바닥 없음" in w for w in skipped):
        return NO_FLOOR_FALLBACK[0]
    return None


# ── 진입 계획 ([MoKa] 11-03 "공격을 할때 미리 어떤 식으로 콤보, 점프 공격 하겠다는 플랜 없이 마구잡이로 하는 느낌") ──────────
#  · 그놈이 2.2–4.5 m에 있을 때 미리 정한다: 어떻게 들어갈지(진입) + 붙은 뒤 무엇을 할지(이어서). 걸어 붙은 다음에 고르지 않음.
#  · 진입이 []이면 걸어서 붙음 (방패병) 또는 기다림 (휘두르는 중 — 반사가 피함).
ENTRY_MAX = 4.5   # 점프 공격 3.25 m 이동 + 무기 닿는 거리 ~1.3 m (11-03 방 실측)
ENTRY = [
    (("*", "shield", "idle"), [], 'MoKa 11-03 "방패가 있으면 발차기 콤보" → 걸어 붙어 발차기'),
    (("*", "*", "swing"), [], "봇 평가 11-03 130055: 휘두르는 놈에 들어가면 끊김 → 기다림 (반사가 피함)"),
    (("*", "ranged", "*"), ["roll_r1", "jump_r2"], 'MoKa 11-03 "석궁병 다가 갈때 구르기 콤보로 공격 했어야지"'),
    (("mid", "*", "*"), ["roll_r1"], 'MoKa 11-03 "거리가 있으면 구르기 콤보"'),
    (("far", "*", "*"), ["jump_r2", "roll_r1"], "봇 기본 (MoKa 판단 전): 3.5 m 넘으면 점프 공격 (3.25 m 이동)"),
]


def entry_plan(k: dict) -> tuple[list[str], str]:
    """How to close in from k (dist mid/far): moves to try in order + source. [] = walk in or wait."""
    for (d, kd, st), moves, src in ENTRY:
        if d in ("*", k["dist"]) and kd in ("*", k["kind"]) and st in ("*", k["state"]):
            return list(moves), src
    return [], "진입 표에 없음 — 걸어서"


def engage_line(h: float, foe, anim) -> str:
    """One line: the plan for this foe — entry, then what to do once close."""
    k = key(h, foe, anim, True, True)
    entry, esrc = entry_plan(k) if k["dist"] in ("mid", "far") and h <= ENTRY_MAX else ([], "")
    near_k = key(1.0, foe, -1, True, True)
    follow = plan(near_k)[0]
    how = " 또는 ".join(entry) if entry else ("걸어서 붙음" if k["state"] != "swing" else "기다림")
    return f"계획 {h:.1f} m [{k['kind']}/{k['state']}]: 진입 {how} → 붙으면 {' / '.join(follow) or '없음'}" + (f"  ({esrc})" if esrc else "")


def why_not_combo(used: str | None, skipped: list[str], k: dict, h: float) -> str | None:
    """Plain light instead of a combo — why: the combos the floor ruled out, or the distance cell that picks light."""
    if used != "light":
        return None
    if skipped:
        return " · ".join(skipped)
    if k["dist"] == "reach":
        return f"{h:.1f} m — 백스텝 콤보는 {BS_MAX} m 넘으면 헛침 (reach 칸), 구르기는 {NEAR_R} m 안에서 금지"
    return "표가 약공을 고름"


def dist_band(h: float) -> str:
    return "near" if h <= BS_MAX else "reach" if h <= NEAR_R else "mid" if h <= MID_R else "far"


def foe_state(anim) -> str:
    if anim in (-1, None):
        return "idle"
    if anim in M.ATTACK:
        return "swing"
    if anim in M.STAGGER or anim == M.GUARD_BROKEN or anim in M.DOWNED:
        return "open"
    return "other"


def foe_kind(foe) -> str:
    return "shield" if getattr(foe, "kind", None) == "shield" else "ranged" if getattr(foe, "ranged", False) else "other"


def key(h: float, foe, anim, back_ok: bool | None, front_ok: bool | None) -> dict:
    return {"dist": dist_band(h), "kind": foe_kind(foe), "state": foe_state(anim), "back": back_ok, "front": front_ok}


def plan(k: dict) -> tuple[list[str], str]:
    for (d, kd, st), moves, src in TABLE:
        if d == k["dist"] and kd in ("*", k["kind"]) and st in ("*", k["state"]):
            return list(moves), src
    return [], "표에 없음"


def judge(move: str | None, hit, skipped: list[str], h0: float, h1: float | None, foe_anim0, reach: float) -> tuple[str, str]:
    """→ (verdict, reason). verdict: 성공 | 맞교환 | 실패 | 못함. One reason, the first that fits, from recorded facts only."""
    if move is None or hit is None or not hit.presses:
        return "못함", "지형: " + (" · ".join(skipped) if skipped else "쓸 수 있는 콤보 없음")
    mine = [a for _t, a in hit.my_anims if a is not None]
    want = COMBO_ANIM.get(move)
    came = want is None or any(a >= 300000 and a % 1000 == want for a in mine)
    stunned = any(a in M.HIT_STUN for a in mine)
    if hit.dmg > 0 and not any(a >= 300000 for a in mine):
        # 내 공격 애니가 하나도 없는데 피해 — 직전 공격이 늦게 잡혔거나 다른 원인 (125142 151 s: 애니 [-1]인데 "성공 59")
        return "불명", f"피해 {hit.dmg}{' (처치)' if hit.dead else ''} 들어왔지만 내 공격 애니 없음 — 이 콤보 때문 아님"
    if hit.dmg > 0:
        what = "처치" if hit.dead else f"맞힘 {hit.dmg}"
        if hit.taken > 0:
            return "맞교환", f"{what}, 그 사이 {hit.taken} 맞음" + (" (공격 중 경직)" if stunned else "")
        return "성공", f"{what}, 안 맞음" + ("" if came else " (콤보 모션은 안 나옴)")
    if stunned and hit.taken > 0 and came and want is not None:
        return "실패", f"공격 중 맞아 끊김 (−{hit.taken}, 콤보 모션은 나옴)" + (", 그놈 휘두르는 중에 시작" if foe_anim0 in M.ATTACK else "")
    if stunned and hit.taken > 0:
        return "실패", f"공격 나가기 전에 맞아 끊김 (−{hit.taken})" + (", 그놈 휘두르는 중에 시작" if foe_anim0 in M.ATTACK else "")
    if not came:
        return "실패", "콤보 모션 안 나옴 (입력이 보통 동작으로 들어감)"
    if h1 is not None and h1 > reach + 0.3:
        return "실패", f"헛침: 끝나고 {h1:.1f} m — {'못 미침' if h1 >= h0 else '지나치거나 그놈이 물러남'}"
    if hit.taken > 0:
        return "실패", f"헛침, {hit.taken} 맞음" + (" — 그놈 휘두르는 중에 시작" if foe_anim0 in M.ATTACK else "")
    return "실패", "헛침: 닿는 거리였는데 피해 0 (막힘·무적 시간?) — 클립 확인"
