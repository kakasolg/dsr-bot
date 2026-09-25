"""스타일 — 가로지르는 관심사를 한 객체에 (2026-09-25 층 설계 3단계). 각 층은 읽기만 한다.

  guard    : 한손 + 방패. 반사는 정면 두기·막기, 휘청에 친다.                (기준선 10/10, 피해 중앙 282)
  backstep : 양손, 방패 없음. 반사는 백스텝(+공격), 헛친 뒤 1.1 s·1.8 m 밖에서 친다. (피해 두 배 — 넓은 평지·망자 전용 실험)
  rush     : 양손, 방패 없음, 반사(막기·피하기) 자체를 끈다 — 계속 공격, 에스트로 버틴다
             (사용자 2026-09-25: "쏘는 놈한테 가는데 다른 다가오는 놈은 양잡으로 없애고 가. 방어도 하지 말고, 에스트 마시면서")
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Style:
    name: str
    shield: bool            # 방패를 드나 (False 면 moves.guard 가 무시된다)
    grip: int               # 1 한손 | 3 양손 (싸움 전에 맞춘다)
    evade: bool             # 반사가 막지 않고 피하나
    bs_attack: bool         # 피할 때 백스텝 공격(B → R1)을 붙이나 (방패 든 놈 제외는 4층이 bs_ok 로)
    punish_after: float     # 헛친 뒤 치기: 공격 시작 뒤 이만큼 지나야
    punish_min_r: float     # 헛친 뒤 치기: 이보다 붙어 있으면 안 한다
    reflex_on: bool = True  # 반사(막기·피하기)를 쓰나 — False 면 반사는 기록만 하고 움직이지 않는다, 공격 루프가 안 끊긴다


GUARD = Style("guard", shield=True, grip=1, evade=False, bs_attack=False, punish_after=1.1, punish_min_r=1.8)
BACKSTEP = Style("backstep", shield=False, grip=3, evade=True, bs_attack=True, punish_after=1.1, punish_min_r=1.8)
RUSH = Style("rush", shield=False, grip=3, evade=False, bs_attack=False, punish_after=1.1, punish_min_r=1.8, reflex_on=False)
BY_NAME = {s.name: s for s in (GUARD, BACKSTEP, RUSH)}


def of(name) -> Style:
    return name if isinstance(name, Style) else BY_NAME[name]
