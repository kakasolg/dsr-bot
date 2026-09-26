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
    # 약공 한 번의 세 단계 (초, 사용자 2026-09-25: "길이가 길어지면 선 딜레이·공격·후 딜레이 중 몇 개가 길어져.
    # 배틀액스는 극단적으로 딜레이가 없는 무기 — 대신 붙어서 싸워야 하는 게 약점").
    # 선 딜레이: 누르고 칼이 닿기까지(이 사이에 맞으면 끊긴다) · 공격: 판정이 살아 있는 구간 · 후 딜레이: 거두는 동안(방패 못 든다)
    # 재는 법: 허공에 R1 — 내 애니 구조체 +0xA0 이 판정 구간에 5/257, 스태미나가 판정 시작에 준다 (OFFLINE_TOOLS.md).
    # None 이면 아직 안 잰 무기 — 예전 고정값(브로드소드·배틀 액스 때 맞춘 것)을 쓴다.
    startup: float | None = None
    active: float | None = None
    recovery: float | None = None
    heavy_punish: bool = False   # 방패병 휘청 틈에 강공(duel.HEAVY_SP 이상일 때)
    max_dur: int | None = None   # 최대 내구도 — 이 비율 아래면 수리 분말 (moves.repair). None 이면 안 본다
    note: str = ""

    @property
    def swing(self) -> float | None:
        return None if self.startup is None else self.startup + self.active + self.recovery

    # 아래는 moves.light 가 쓰는 시각 (첫 R1 기준). 세 단계에서 계산 — 클레이모어 실측과 맞춰 본 식:
    # 두 번째 R1 은 판정이 끝나기 직전(0.45 s 에 누르면 무시됨, 0.8 s 면 이어짐), 이어진 두 번째 휘두르기는 판정 끝 +0.2 s 에 시작.
    @property
    def chain_at(self) -> float:
        return 0.45 if self.startup is None else self.startup + self.active - 0.04

    @property
    def second_start(self) -> float:
        return self.startup + self.active + 0.2

    @property
    def guard1(self) -> float:
        return 0.35 if self.startup is None else self.swing - 0.1

    @property
    def guard2(self) -> float:
        return 1.05 if self.startup is None else self.second_start + self.swing - 0.1

    @property
    def watch1(self) -> float:
        return 0.9 if self.startup is None else self.swing + 0.1

    @property
    def watch2(self) -> float:
        return 1.5 if self.startup is None else self.second_start + self.swing + 0.1


# 위키(Fextralife): 모델이 작고 사거리가 짧지만 스트레이트 소드 중 공격력이 가장 높다. 약·강공이 쉽게 이어진다.
# 사용자(2026-09-24): "평범하게 약공이 좋아. 대신 약공 2대", "브로드소드 짧은 대신 연타가 유리", 점프 공격 모션이 안 좋다.
# 실측: 처치는 전부 1.2 m 안, 1.6 m 넘으면 5/5 헛침. 2026-09-24 테라스: 1.3~1.6 m 에서 휘두른 약공 8 번이 전부 헛침 → 1.2 m.
# 망자(HP 75)는 약공 2연타 두 번(41+34)
# 한손 + 왼손 방패 (2026-09-24 status: arm_style 한손). 반사·막기가 방패 전제 — 양손이면 방패가 빠지고 무기 가드는 약하다 (사용자)
BROADSWORD = Weapon("브로드소드", 202000, reach=1.2, combo=2, use_heavy=False, two_hand=False, str_req=10,
                    note="강공(스틱 놓고 R2)은 가로 베기 — 약공과 섞는 건 아직 안 시험함")

# 위키: 요구 근력 24·기량 10 (양손이면 근력 16). 강공은 적을 넘어뜨리는 내려찍기, 약공은 넓게 휘두르기.
# 실측(2026-09-23): 강공 스태미나 120, 2.3 m 안에서만 잘 맞음(넘으면 4/14)
ZWEIHANDER = Weapon("츠바이헨더", 350000, reach=2.3, combo=1, use_heavy=True, two_hand=True, str_req=24, sp_min=60,
                    note="강공 내려찍기로 경직·넘어뜨림")

# 배틀 액스 701000 (밴딧 시작 무기). 사용자(2026-09-24): "브로드소드보다 도끼가 퍼포먼스가 좋아 — 비슷한 동작인데 더 효과적".
# 위키: 요구 근력 14·기량 8, 약공은 세로 내려찍기(인간형 경직이 큼), 이어 치기 됨. 옛 기록(playbook-notes·reach.py): 사거리 1.8 m, 불사원 망자 2~3타.
# 닿는 거리는 브로드소드 실측(1.2)보다 길게 두되 옛 1.8 은 낙관적 — 1.5 로 시작하고 헛침이 나오면 reach.py 로 다시 잰다.
BATTLE_AXE = Weapon("배틀 액스", 701000, reach=1.5, combo=2, use_heavy=False, two_hand=False, str_req=14, sp_min=55,
                    note="약공 세로 찍기 2연타. 강공(R2 큰 내려찍기)은 아직 안 시험함 — 넘어뜨리면 방패병에 쓸 후보")

# 클레이모어 301000 (대검). 사용자(2026-09-25): 불사교구에서 얻음, "배틀액스보다 좋은 무기이니 앞으로 이걸로".
# 위키: 요구 근력 16·기량 10 — 지금 근력 16 이라 한손으로 든다(왼손 방패 유지). 한손 약공은 넓은 가로 베기라
# 옆에 붙은 놈까지 맞고, 대검이라 도끼(1.5 m)보다 길다. 강공은 찌르기. 스태미나를 도끼보다 많이 먹는다.
# **아직 실측 전** — reach 1.8·combo 2·sp_min 60 은 위키 기반 첫 값. 헛침이 나오면 reach.py 로 다시 잰다.
# 허공 실측(2026-09-25, 애니 253000→253001): 칼 닿는 순간(스태미나 −30) 0.68 s, 한 번 끝 1.46 s. 두 번째 R1 을 0.45 s 에
# 누르면 **무시돼 한 번만** 휘둘렀고(사용자: "가드·공격 타이밍이 어긋나"), 0.8 s 면 이어져 두 번째 닿음 1.65 s·끝 2.40 s.
CLAYMORE = Weapon("클레이모어", 301000, reach=1.8, combo=2, use_heavy=False, two_hand=False, str_req=16, sp_min=60,
                  startup=0.68, active=0.16, recovery=0.62, max_dur=200, heavy_punish=False,
                  # heavy_punish 끔 (2026-09-25): 방패병 휘청 틈 찌르기 2번 = 피해 0(받은 87)·36 — 같은 틈 발차기+약공 79~85.
                  # 선 딜레이 0.76 s 동안 휘청이 풀리는 것으로 보인다
                  note="한손 약공 가로 베기 2연타(옆 적도 맞는다 — 사용자). 강공(찌르기)은 아직 안 씀. reach 는 실측 전")

KNOWN = {w.base_id: w for w in (BROADSWORD, ZWEIHANDER, BATTLE_AXE, CLAYMORE)}


def of(weapon_id: int | None) -> Weapon:
    """오른손 무기 ID → 사용법. 모르는 무기면 브로드소드 값으로 (짧고 약공 위주 = 가장 보수적) 쓰되 알린다."""
    if weapon_id is not None and weapon_id - weapon_id % 100 in KNOWN:
        return KNOWN[weapon_id - weapon_id % 100]
    print(f"   ⚠ 모르는 무기 {weapon_id} — 브로드소드 사용법으로 (souls/weapons.py 에 추가할 것)", flush=True)
    return BROADSWORD


def can_two_hand(w: Weapon, strength: int | None) -> bool | None:
    return None if strength is None else strength * 1.5 >= w.str_req
