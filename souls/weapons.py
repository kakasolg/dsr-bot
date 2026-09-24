"""2층 — 무기 사용법. 무기마다 모션이 다르다 (사용자: "무기별 모션 특성이 있어").
이 층은 숫자와 선택만 담는다: 닿는 거리, 몇 번 이어 치나, 강공을 쓰나. 버튼은 1층(moves), 누구를 칠지는 3층 이상.

무기 ID 는 PlayerGameData+0x328 (tm.right_weapon()). 강화 단계가 끝 두 자리 (브로드소드+5 = 202005) → 100 단위로 내림.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Weapon:
    name: str
    base_id: int
    reach: float            # 약공이 닿는 그놈 중심까지 수평 거리 (m). 이 안에서만 누른다
    combo: int              # 약공 몇 번 이어 치나 (moves.light n)
    use_heavy: bool         # 강공을 쓰나 (스틱을 놓고 R2 — 앞+R2 는 점프 공격)
    two_hand: bool          # 양손으로 잡나 (Y)
    str_req: int            # 한손 근력 요구치. 양손은 1.5 배로 계산 → str_req / 1.5 이상이면 됨
    sp_min: int = 40        # 이 스태미나 아래면 치지 말고 방패
    note: str = ""


# 위키(Fextralife): 모델이 작고 사거리가 짧지만 스트레이트 소드 중 공격력이 가장 높다. 약·강공이 쉽게 이어진다.
# 사용자(2026-09-24): "평범하게 약공이 좋아. 대신 약공 2대", "브로드소드 짧은 대신 연타가 유리", 점프 공격 모션이 안 좋다.
# 실측: 중심 거리 1.4 m 까지는 맞고 1.6 m 넘으면 5/5 헛침. 망자(HP 75)는 약공 2연타 두 번(41+34)
# 한손 + 왼손 방패 (2026-09-24 status: arm_style 한손). 반사·막기가 방패 전제 — 양손이면 방패가 빠지고 무기 가드는 약하다 (사용자)
BROADSWORD = Weapon("브로드소드", 202000, reach=1.4, combo=2, use_heavy=False, two_hand=False, str_req=10,
                    note="강공(스틱 놓고 R2)은 가로 베기 — 약공과 섞는 건 아직 안 시험함")

# 위키: 요구 근력 24·기량 10 (양손이면 근력 16). 강공은 적을 넘어뜨리는 내려찍기, 약공은 넓게 휘두르기.
# 실측(2026-09-23): 강공 스태미나 120, 2.3 m 안에서만 잘 맞음(넘으면 4/14)
ZWEIHANDER = Weapon("츠바이헨더", 350000, reach=2.3, combo=1, use_heavy=True, two_hand=True, str_req=24, sp_min=60,
                    note="강공 내려찍기로 경직·넘어뜨림")

KNOWN = {w.base_id: w for w in (BROADSWORD, ZWEIHANDER)}


def of(weapon_id: int | None) -> Weapon:
    """오른손 무기 ID → 사용법. 모르는 무기면 브로드소드 값으로 (짧고 약공 위주 = 가장 보수적) 쓰되 알린다."""
    if weapon_id is not None and weapon_id - weapon_id % 100 in KNOWN:
        return KNOWN[weapon_id - weapon_id % 100]
    print(f"   ⚠ 모르는 무기 {weapon_id} — 브로드소드 사용법으로 (souls/weapons.py 에 추가할 것)", flush=True)
    return BROADSWORD


def can_two_hand(w: Weapon, strength: int | None) -> bool | None:
    return None if strength is None else strength * 1.5 >= w.str_req
