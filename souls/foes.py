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
    circle_behind: bool = False     # 방패는 정면 부채꼴만 막는다 — 가만히 있으면 등 뒤로 돌아 약공(제일 효과적, 사용자 2026-09-25)
    ranged: bool = False            # 멀리서 던진다(화염병) — 기다리면 안 오고 계속 던진다 → 달려가 붙는다
    avoid: bool = False             # 지금 레벨로는 상대 안 함 (길을 돌아간다)
    singles: tuple = ()             # 한 방으로 끝나는 공격 애니 — 막고 나서 바로 반격해도 된다
    combos: tuple = ()              # 이어지는 공격의 시작 애니 — 끝까지 막고 반격
    unblockable: tuple = ()         # 막으면 안 되는 공격 (가드 브레이크 등) — 반사가 방패 대신 피한다
    punish_hits: int | None = None  # 휘청(막기에 튕김) 반격 약공 수 — None 이면 무기대로. 휘청이 짧은 놈은 1
    windup: tuple = ()              # 시작하고 한참 뒤에 닿는 공격 — windup_act_s 안이면 먼저 발차기로 끊고, 넘으면 막는다
    windup_act_s: float = 1.2
    kick_on_stagger: bool = False   # 공격 뒤 휘청(3500)에 곧장 발차기 — 곧 물러나 닿는 거리를 벗어난다
    note: str = ""


# 망자 c2540 (Lua 2026-09-24): 가까우면 절반이 단발 3008, 나머지가 2~3타 콤보(3003→3004→3009, 3005~3007)
# 2026-09-25 실측(254001): 3009 를 몇 초씩 막다 스태미나 6까지 떨어지고 죽음(반사×29 연속, 준 피해 0, 받은 376) —
# SHIELD 뿐 아니라 망자 콤보의 3009 도 막으면 안 된다 (같은 애니 번호, 같은 위험). unblockable 에 추가.
_HOLLOW = dict(kind="hollow", singles=(3008,), combos=(3003, 3005), unblockable=(3009,))
HOLLOW = Foe("망자(칼)", **_HOLLOW)
FIREBOMB_HOLLOW = Foe("망자(화염병)", ranged=True, **_HOLLOW,
                      note="경사로 4번: 4.9 m 위 턱에서 안 내려오고 화염병만 — 방패로 받아도 56~224. 달려 올라가 근접")
# 2026-09-26 관찰 녹화(observe 090241·091308·092141) 경사로 2번 255010, 사용자: "한 템포 빨리 발차기가 들어가야 함":
#  · 3004 는 다가오는 속도(0.1~1.3 m/s)와 상관없이 시작 2.0~2.1 s 뒤에 닿는다 (4번). 1.6 s 넘어 친 두 번 −220·−323,
#    0.4~0.7 s 에 친 두 번은 공격이 끊기고 0 → windup=(3004,), 1.2 s 안이면 발차기, 넘으면 막기
#  · 3005 돌진(4 m 에서 3~4.5 m/s, +1.0 s 에 닿음)은 막으면 1~2 — 그대로 막기
#  · 3500 은 0.8~1.3 s, 그 사이 1.5~1.9 m/s 로 물러난다(1 m → 3~4.7 m) — 곧장 발차기 (예전엔 '끌어오기'로 평지로 뛰어가 버림)
SHIELD = Foe("방패 병사", kind="shield", kick_when_idle=True, circle_behind=False, unblockable=(3009,), punish_hits=1,
             windup=(3004,), windup_act_s=1.2, kick_on_stagger=True,
             note="가만히 서면 방패를 들어 약공이 12 씩만 (6번 쳐도 못 잡음). 가드 올린 채면 발차기로 휘청 (위키). "
                  "내가 가드만 하면 가드 브레이크 3009 로 깨러 온다 (Lua IsTargetGuard) — 2026-09-24 실측: 3009 를 막다 가드가 깨져"
                  "(내 애니 160) 스태미나 42→14, 밀려나 경사로에서 낙사. 3009 는 막지 말고 피한다. "
                  "휘청이 짧다 — 휘청 반격 2연타의 두 번째 사이에 100~115 를 되받아쳤다 (세 번 중 두 번) → 한 대만. "
                  "circle_behind 는 꺼둠(2026-09-25, 사용자: '도는게 너무 느려, 발차기 약공이 더 좋아 보여') — 아래 참고")
SKELETON = Foe("묘지 해골", kind="skeleton", avoid=True, singles=(3003, 3004, 3005), combos=(3000,),
               note="스텝인(700)으로 한 번에 붙고 구르기로 피한다. 한 대 111~167 — 기사 레벨로는 못 이김 (사용자 2026-09-24)")
ASYLUM_DEMON = Foe("수용소 데몬", kind="boss", note="boss/README.md — 필드 규칙과 섞지 않는다")

BY_NPC: dict[int, Foe] = {
    254000: HOLLOW, 254002: HOLLOW, 254010: HOLLOW, 254011: HOLLOW,
    254001: FIREBOMB_HOLLOW, 254012: FIREBOMB_HOLLOW,
    250000: Foe("망자(성벽 마을)", kind="hollow", combos=(3000, 3004), unblockable=(3009,)),
    255000: SHIELD, 255010: SHIELD,
    # 255002 는 방패병이 아니라 석궁병 — 3000/3001 이 가드 자세가 아니라 쏘는 동작이다. 애니 구조체 +0xA0 이 1 로 켜지고
    # 0.3~0.7 s 뒤 내 방패에 충격(내 애니 140, SP −7)이 2.7 s 마다 (2026-09-25 실측, 사용자 "화살 맞고 있다니깐, 바로 앞에 있어").
    # SHIELD 로 두니 wait_far 가 "안 다가온다"며 막고만 8 분 서 있었다. 발사 동작 번호가 안 바뀌어 애니 변화로는 안 보인다.
    255002: Foe("석궁 병사", kind="shield", ranged=True, kick_when_idle=True, unblockable=(3009,), punish_hits=1,
                note="3000/3001 = 석궁 발사 (방패 들고 쏜다). 기다리지 말고 붙어 발차기 → 약공"),
    # 254013·254014 (성벽 마을 화톳불 옆, HP150): 방패병이 아니라 몸 없는 유령이었다 — 사용자 "아무것도 없는데 왜 휘두르지"
    # (2026-09-25). 254013 은 비활성 플래그로, 254014 는 몸 겹침(dsr_telemetry.PHANTOM_R)으로 0층에서 걸러진다. 아래 등록은 남겨 둔다.
    254013: SHIELD, 254014: SHIELD,
    290000: SKELETON, 290002: SKELETON, 290003: SKELETON, 290004: SKELETON, 291000: SKELETON,
    223200: ASYLUM_DEMON,
}

UNKNOWN = Foe("모르는 적", kind="other")


def of(npc: int | None) -> Foe:
    return BY_NPC.get(npc, UNKNOWN) if npc is not None else UNKNOWN
