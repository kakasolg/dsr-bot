"""스타일 — 가로지르는 관심사를 한 객체에 (2026-09-25 층 설계 3단계). 각 층은 읽기만 한다.

  guard    : 한손 + 방패. 반사는 정면 두기·막기, 휘청에 친다.                (기준선 10/10, 피해 중앙 282)
  backstep : 양손, 방패 없음. 반사는 백스텝(+공격), 헛친 뒤 1.1 s·1.8 m 밖에서 친다. (피해 두 배 — 넓은 평지·망자 전용 실험)
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


GUARD = Style("guard", shield=True, grip=1, evade=False, bs_attack=False, punish_after=1.1, punish_min_r=1.8)
BACKSTEP = Style("backstep", shield=False, grip=3, evade=True, bs_attack=True, punish_after=1.1, punish_min_r=1.8)
BY_NAME = {s.name: s for s in (GUARD, BACKSTEP)}


def of(name) -> Style:
    return name if isinstance(name, Style) else BY_NAME[name]
