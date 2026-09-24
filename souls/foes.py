"""3층 데이터 — 적 종류별 상대법. npc 번호(NpcParamId) → 어떤 놈이고 어떻게 상대하나.
출처: 게임 Lua AI(`script\\<맵>.luabnd.dcx` → `<npc>_battle.lua`, boss/luadump.py·luatab.py 로 뽑음), 실측, 사용자 팁.
Lua 는 **데이터 공급원**일 뿐이다 — 한 번 뽑아 여기 적고, 실행 중엔 안 읽는다.
새 적을 만나면 여기 한 줄을 더한다. 전투 루프(duel.py)는 이 값만 보고 행동을 바꾼다.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Foe:
    name: str
    kind: str                       # hollow | shield | skeleton | boss | other
    kick_when_idle: bool = False    # 가만히 설 때(애니 -1) 방패를 들고 있다 → 발차기로 깨고 친다
    ranged: bool = False            # 멀리서 던진다(화염병) — 기다리면 안 오고 계속 던진다 → 달려가 붙는다
    avoid: bool = False             # 지금 레벨로는 상대 안 함 (길을 돌아간다)
    singles: tuple = ()             # 한 방으로 끝나는 공격 애니 — 막고 나서 바로 반격해도 된다
    combos: tuple = ()              # 이어지는 공격의 시작 애니 — 끝까지 막고 반격
    unblockable: tuple = ()         # 막으면 안 되는 공격 (가드 브레이크 등) — 반사가 방패 대신 피한다
    punish_hits: int | None = None  # 휘청(막기에 튕김) 반격 약공 수 — None 이면 무기대로. 휘청이 짧은 놈은 1
    note: str = ""


# 망자 c2540 (Lua 2026-09-24): 가까우면 절반이 단발 3008, 나머지가 2~3타 콤보(3003→3004→3009, 3005~3007)
_HOLLOW = dict(kind="hollow", singles=(3008,), combos=(3003, 3005))
HOLLOW = Foe("망자(칼)", **_HOLLOW)
FIREBOMB_HOLLOW = Foe("망자(화염병)", ranged=True, **_HOLLOW,
                      note="경사로 4번: 4.9 m 위 턱에서 안 내려오고 화염병만 — 방패로 받아도 56~224. 달려 올라가 근접")
SHIELD = Foe("방패 병사", kind="shield", kick_when_idle=True, unblockable=(3009,), punish_hits=1,
             note="가만히 서면 방패를 들어 약공이 12 씩만 (6번 쳐도 못 잡음). 가드 올린 채면 발차기로 휘청 (위키). "
                  "내가 가드만 하면 가드 브레이크 3009 로 깨러 온다 (Lua IsTargetGuard) — 2026-09-24 실측: 3009 를 막다 가드가 깨져"
                  "(내 애니 160) 스태미나 42→14, 밀려나 경사로에서 낙사. 3009 는 막지 말고 피한다. "
                  "휘청이 짧다 — 휘청 반격 2연타의 두 번째 사이에 100~115 를 되받아쳤다 (세 번 중 두 번) → 한 대만")
SKELETON = Foe("묘지 해골", kind="skeleton", avoid=True, singles=(3003, 3004, 3005), combos=(3000,),
               note="스텝인(700)으로 한 번에 붙고 구르기로 피한다. 한 대 111~167 — 기사 레벨로는 못 이김 (사용자 2026-09-24)")
ASYLUM_DEMON = Foe("수용소 데몬", kind="boss", note="boss/README.md — 필드 규칙과 섞지 않는다")

BY_NPC: dict[int, Foe] = {
    254000: HOLLOW, 254002: HOLLOW, 254010: HOLLOW, 254011: HOLLOW,
    254001: FIREBOMB_HOLLOW, 254012: FIREBOMB_HOLLOW,
    250000: Foe("망자(성벽 마을)", kind="hollow", combos=(3000, 3004)),
    255000: SHIELD, 255002: SHIELD, 255010: SHIELD,
    290000: SKELETON, 290002: SKELETON, 290003: SKELETON, 290004: SKELETON, 291000: SKELETON,
    223200: ASYLUM_DEMON,
}

UNKNOWN = Foe("모르는 적", kind="other")


def of(npc: int | None) -> Foe:
    return BY_NPC.get(npc, UNKNOWN) if npc is not None else UNKNOWN
