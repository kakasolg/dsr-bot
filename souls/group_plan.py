"""Group plan before a fight (P-121): which attack for each foe, in which order, and where to stand for it.

[MoKa] 2026-11-03: "첫 번째 적은 백스텝 콤보, 두번째 적은 점프 공격, 세번째 방패병은 백스텝 공격 이런 식의 미리 계획을 하고, 거기에
맞는 플랜, 좋은 위치를 확보 해야 하는데 그런게 없어." — "그러지 않으면 데이타를 확보 못해."

  make(p, foes, nm)  → Plan: steps (foe → attack + why) and a spot (where to stand, facing the first foe) with its reasons
  The plan is written once per group (run.py --combo-only only); each combo event then carries planned / followed, so a
  report can tell "the plan was wrong" from "the plan was right but not carried out".

Pure: snapshots and a NavMesh in, no pad. Distances are the room measures (souls/combo_table.py).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from types import SimpleNamespace as NS

import nav
from . import combo_table as CTB

BACK_NEED = 2.6        # backstep combo: floor behind (moves.backstep_attack)
FRONT_NEED = 3.0       # roll / jump forward
EDGE_MIN = 2.0         # spot this far from a drop at least
SPOT_R = (0.0, 1.5, 3.0, 4.0)   # rings of candidate spots around us (m)
SPOT_DIRS = 12


@dataclass
class Step:
    ptr: int
    npc: int
    dist: float                     # from the chosen spot
    attack: str                     # backstep_r1 | roll_r1 | jump_r2 | backstab | kick_combo | light | wait
    why: str


@dataclass
class Plan:
    steps: list[Step] = field(default_factory=list)
    spot: tuple | None = None       # local (x, y, z)
    moved: float = 0.0
    spot_why: str = ""

    def attack_for(self, ptr: int) -> str | None:
        return next((st.attack for st in self.steps if st.ptr == ptr), None)

    def lines(self) -> list[str]:
        out = [f"전투 계획 {len(self.steps)}놈 — 자리: " + (f"({self.spot[0]:.1f}, {self.spot[2]:.1f}) {self.moved:.1f} m 옮김"
                                                         if self.spot and self.moved > 0.3 else "여기") + f" — {self.spot_why}"]
        out += [f"   {i}) {st.npc} {st.dist:.1f} m → {st.attack} — {st.why}" for i, st in enumerate(self.steps, 1)]
        return out


def attack_for(order: int, h: float, foe, anim, n: int = 1, arc_ok: bool = True) -> tuple[str, str]:
    """Planned attack for the order-th foe (0 = first) of n at distance h from our spot. arc_ok = floor to circle to its back.

    ── 상황별 기술 ([MoKa] 2026-11-04) ──────────────────────────────
     "뒤로만 물러나야 하는 상황, 적이 2인 경우는 백스텝 콤보, 적이 근처에 하나이고, 지형으로 막히지 않으면 뒤잡 공격,
      그리고 가드 브레이크는 점프 공격 이런식으로 세팅 해봐."
     · 방패 든 놈 → jump_r2 (가드 브레이크; 타이밍은 rule_jump_drill: 서 있는 놈 2.6–4.8 m · 헛친 뒤)
     · 석궁병 → roll_r1 ([MoKa] 11-03 "석궁병 다가 갈때 구르기 콤보")
     · 근처 하나 · 돌아갈 바닥 있음 → backstab
     · 둘 이상 · 돌 자리 막힘 (뒤로만 물러남) → backstep_r1
    """
    k = CTB.key(h, foe, anim, True, True)
    if k["kind"] == "shield":
        return "jump_r2", 'MoKa "가드 브레이크는 점프 공격"'
    if k["kind"] == "ranged":
        return "roll_r1", 'MoKa "석궁병 다가 갈때 구르기 콤보"'
    if n >= 2:
        return "backstep_r1", f'{n}놈 — MoKa "적이 2인 경우는 백스텝 콤보"'
    if arc_ok:
        return "backstab", 'MoKa "근처에 하나이고, 지형으로 막히지 않으면 뒤잡"'
    return "backstep_r1", 'MoKa "뒤로만 물러나야 하는 상황 … 백스텝 콤보" (돌 바닥 없음)'


def _g(p, x, y, z):
    """Local spot → an object with global coords for nav.can_move."""
    ox, oy, oz = (p.gx or p.x) - p.x, (p.gy or p.y) - p.y, (p.gz or p.z) - p.z
    return NS(x=x, y=y, z=z, gx=x + ox, gy=y + oy, gz=z + oz)


def _spot_score(nm, p, q, ordered, foes_info) -> tuple[float, list[str]]:
    """Lower is better. q = local (x, y, z). Checks the floor each planned attack needs from there."""
    P = _g(p, *q)
    first = ordered[0]
    fx, fz = first.x - q[0], first.z - q[2]
    score, notes = math.hypot(q[0] - p.x, q[2] - p.z) * 0.5, []
    if nm is not None:
        if not nav.can_move(nm, P, -fx, -fz, BACK_NEED):
            score += 10.0
            notes.append("첫 놈 반대쪽 뒤 바닥 없음")
        try:
            dd = nm.drop_dist(P.gx, P.gy, P.gz)
        except Exception:
            dd = math.inf
        if dd < EDGE_MIN:
            score += 6.0 * (EDGE_MIN - dd)
            notes.append(f"낭떠러지 {dd:.1f} m")
        for c, (atk, _w) in zip(ordered[1:], foes_info[1:]):
            if atk in ("roll_r1", "jump_r2") and not nav.can_move(nm, P, c.x - q[0], c.z - q[2],
                                                                  min(FRONT_NEED, math.hypot(c.x - q[0], c.z - q[2]))):
                score += 4.0
                notes.append(f"{c.npc_param} 쪽 앞 바닥 없음")
    # 다음 놈이 진입 거리(2.2–4.5 m)에 있으면 좋음 — 점프·구르기로 들어갈 수 있게
    for c in ordered[1:2]:
        d = math.hypot(c.x - q[0], c.z - q[2])
        if not (CTB.NEAR_R < d <= CTB.ENTRY_MAX):
            score += 1.0
    return score, notes


def make(p, foes: list, nm, foe_of=lambda npc: None, here_only: bool = False, rings: tuple = SPOT_R, arc_of=lambda c: True) -> Plan:
    """foes: snapshot chars (awake hostiles nearby). foe_of(npc) → foe profile (foes.of). Nearest first = the order they come.
    arc_of(c) → floor to circle round that foe to its back (duel._arc_open, from where we stand now)."""
    plan = Plan()
    if not foes:
        return plan
    ordered = sorted(foes, key=lambda c: math.hypot(c.x - p.x, c.z - p.z))
    arcs = {c.ptr: bool(arc_of(c)) for c in ordered}
    cands = [(p.x, p.y, p.z)] if here_only else [
        (p.x + r * math.sin(2 * math.pi * i / SPOT_DIRS), p.y, p.z + r * math.cos(2 * math.pi * i / SPOT_DIRS))
        for r in rings for i in (range(SPOT_DIRS) if r > 0 else range(1))]
    best = None
    for q in cands:
        if q != (p.x, p.y, p.z) and nm is not None:
            P0 = _g(p, p.x, p.y, p.z)
            if not nav.can_move(nm, P0, q[0] - p.x, q[2] - p.z, math.hypot(q[0] - p.x, q[2] - p.z)):
                continue                                   # can't walk there straight
            if any(math.hypot(c.x - q[0], c.z - q[2]) < math.hypot(c.x - p.x, c.z - p.z) - 1.0 for c in ordered[:1]):
                continue                                   # 첫 놈 쪽으로 다가가는 자리는 안 씀 — 그놈이 오게 둠
        info = [attack_for(i, math.hypot(c.x - q[0], c.z - q[2]), foe_of(c.npc_param), c.anim, len(ordered), arcs[c.ptr]) for i, c in enumerate(ordered)]
        sc, notes = _spot_score(nm, p, q, ordered, info)
        if best is None or sc < best[0]:
            best = (sc, q, info, notes)
    if best is None:
        q = (p.x, p.y, p.z)
        info = [attack_for(i, math.hypot(c.x - p.x, c.z - p.z), foe_of(c.npc_param), c.anim, len(ordered), arcs[c.ptr]) for i, c in enumerate(ordered)]
        best = (0.0, q, info, ["갈 수 있는 자리 없음"])
    _sc, q, info, notes = best
    plan.spot, plan.moved = q, math.hypot(q[0] - p.x, q[2] - p.z)
    plan.spot_why = "; ".join(notes) if notes else "첫 놈 반대쪽 뒤 바닥 2.6 m, 낭떠러지 멀고, 다음 놈은 진입 거리"
    plan.steps = [Step(c.ptr, c.npc_param, round(math.hypot(c.x - q[0], c.z - q[2]), 1), atk, why)
                  for c, (atk, why) in zip(ordered, info)]
    return plan
