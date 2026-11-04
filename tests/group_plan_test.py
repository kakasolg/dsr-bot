"""P-121 group plan: each foe gets an attack in order, and the spot keeps floor behind us away from the first foe (no game).
  python tests/group_plan_test.py

[MoKa] 2026-11-03: "첫 번째 적은 백스텝 콤보, 두번째 적은 점프 공격, 세번째 방패병은 백스텝 공격 이런 식의 미리 계획을 하고,
거기에 맞는 플랜, 좋은 위치를 확보 해야"
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import math
import sys
from types import SimpleNamespace as NS

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from souls import group_plan as GP

HOLLOW, SHIELD = NS(kind="other", ranged=False), NS(kind="shield", ranged=False)
KINDS = {254000: HOLLOW, 254002: HOLLOW, 252000: SHIELD}


def check(name: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        raise SystemExit(1)


def me(x=0.0, z=0.0):
    return NS(x=x, y=0.0, z=z, gx=x, gy=0.0, gz=z)


def foe(ptr, npc, x, z, anim=-1):
    return NS(ptr=ptr, npc_param=npc, x=x, y=0.0, z=z, anim=anim, hp=80)


class Floor:
    """Floor where ok(x, z); drop edge at distance edge(x, z)."""
    def __init__(self, ok, edge=lambda x, z: 99.0):
        self.ok, self.edge = ok, edge

    def floor_at(self, x, z, y):
        return (0.0, 0) if self.ok(x, z) else None

    def drop_dist(self, x, y, z):
        return self.edge(x, z)


def main() -> None:
    foes = [foe(1, 254000, 0.0, 3.0), foe(2, 254002, 0.5, 7.5), foe(3, 252000, -1.0, 10.0)]
    plan = GP.make(me(), foes, None, foe_of=KINDS.get, here_only=True)
    atk = [st.attack for st in plan.steps]
    check(f"순서는 가까운 놈부터 ({[st.npc for st in plan.steps]})", [st.npc for st in plan.steps] == [254000, 254002, 252000])
    # [MoKa] 11-04 "적이 2인 경우는 백스텝 콤보, 적이 근처에 하나이고, 지형으로 막히지 않으면 뒤잡 공격, 가드 브레이크는 점프 공격"
    check(f"3놈: 첫 망자 → 백스텝 콤보 ({atk})", atk[0] == "backstep_r1")
    check(f"3놈: 두 번째 망자도 → 백스텝 콤보 ({atk})", atk[1] == "backstep_r1")
    check(f"방패병 → 점프 공격 (가드 브레이크) ({atk})", atk[2] == "jump_r2")
    one = [foe(1, 254000, 0.0, 3.0)]
    check("근처 하나 · 돌 바닥 있음 → 뒤잡", GP.make(me(), one, None, foe_of=KINDS.get, here_only=True).steps[0].attack == "backstab")
    check("근처 하나 · 돌 바닥 막힘 → 백스텝 콤보 (뒤로만)", GP.make(me(), one, None, foe_of=KINDS.get, here_only=True,
                                                         arc_of=lambda c: False).steps[0].attack == "backstep_r1")
    check("방패병 하나 → 점프 공격", GP.make(me(), [foe(2, 252000, 0.0, 3.0)], None, foe_of=KINDS.get,
                                       here_only=True).steps[0].attack == "jump_r2")
    check("계획 줄 있음", len(plan.lines()) == 4 and "1)" in plan.lines()[1])

    # 첫 놈은 +z 쪽 → 백스텝은 −z로 2.6 m 바닥이 필요. 어디로 옮겨도 그런 자리가 없으면 그 이유가 계획에 남음
    nm = Floor(lambda x, z: z >= -1.0 and abs(x) <= 0.5)     # 좁은 통로, 뒤는 1 m뿐 — 어디로 옮겨도 안 됨
    plan = GP.make(me(), foes[:1], nm, foe_of=KINDS.get)
    check(f"뒤 바닥 없는 자리면 이유에 남음 ({plan.spot_why})", "뒤 바닥 없음" in plan.spot_why)

    # 지금 자리 (0, −2)는 뒤 2.6 m가 z −4.6 → 바닥(z ≥ −4) 밖. 앞으로 조금 나간 자리를 고름
    nm = Floor(lambda x, z: z >= -4.0 and z <= 20.0 and abs(x) <= 6.0)
    plan = GP.make(me(0.0, -2.0), [foe(1, 254000, 0.0, 3.0)], nm, foe_of=KINDS.get)
    check(f"뒤 바닥 있는 자리로 옮김 (자리 {plan.spot}, {plan.spot_why})", plan.spot[2] >= -1.4 and "뒤 바닥 없음" not in plan.spot_why)
    check("첫 놈 쪽으로 1 m 넘게 다가가지 않음", math.hypot(plan.spot[0] - 0.0, plan.spot[2] - 3.0) >= 5.0 - 1.0 - 1e-6)

    # 낭떠러지 가까운 자리는 피함
    nm = Floor(lambda x, z: abs(x) <= 10 and abs(z) <= 10, edge=lambda x, z: abs(x - 5.0))
    plan = GP.make(me(4.0, 0.0), [foe(1, 254000, 4.0, 6.0)], nm, foe_of=KINDS.get)
    check(f"낭떠러지에서 떨어진 자리 (x {plan.spot[0]:.1f})", abs(plan.spot[0] - 5.0) >= GP.EDGE_MIN - 1e-6)


if __name__ == "__main__":
    main()
