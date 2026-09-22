"""
복기(post-mortem) — 사망 스냅샷(직전 30초)과 에피소드 기록에서 "왜 죽었나"를 뽑고,
플레이북 수정 제안을 **하나** 만든다. 결정론 규칙만 쓴다 (LLM 은 나중에 같은 인터페이스로 붙일 수 있음).

진단(diagnosis):
  killers        사망 전 20 m 내 적 타입별 피해 기여 (damage 이벤트의 by 목록으로 집계)
  first_hit_hp   치명 시퀀스의 첫 피격 때 HP 비율
  hostile_count  첫 피격 때 20 m 내 적 수
  segment        사망 지점에서 가장 가까운 웨이포인트 번호
  flask_used     마지막 30초 안에 성배병을 썼는지 (guard 이벤트)
  retreated      후퇴가 발동됐는지

제안 규칙 (증거는 여러 에피소드에 걸쳐 누적된다 — learn.py 가 같은 제안이 2회 이상 나와야 적용):
  R1 같은 타입에게 죽음            → avoid_types 에 추가 (보이면 후퇴)
  R2 적 다수(≥ crowd_threshold)에 죽음 → crowd_threshold -1 (더 빨리 스프린트)
  R3 첫 피격 HP 가 이미 낮았음(< retreat)  → flask_hp_pct +0.1 (더 일찍 마심)
  R4 후퇴 없이 죽음, HP 가 retreat 근처   → retreat_hp_pct +0.05 (더 일찍 후퇴)
  R5 같은 구간에서 죽음                  → sprint_segments 에 구간 추가
"""
from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path

from playbook import Playbook


def diagnose(death_json: Path, route_points: list[list[float]], names: dict[int, str] | None = None) -> dict:
    d = json.loads(death_json.read_text(encoding="utf-8"))
    tail = d["tail"]
    names = names or {}
    dmg_events = [r for r in tail if r.get("event") == "damage"]
    guard_events = [r for r in tail if r.get("guard")]
    killers: Counter = Counter()
    for r in dmg_events:
        for npc, dist, _anim in r.get("by", [])[:1]:   # 가장 가까운 적에게 귀속
            killers[npc] += r.get("dmg", 0)
    last = tail[-1] if tail else {}
    pos = last.get("pos", [0, 0, 0])
    # 사망 지점 → 가장 가까운 웨이포인트 (기록의 pos 는 로컬 좌표라 wpos 가 있으면 그걸 씀)
    wpos = last.get("wpos")
    segment = None
    if wpos and route_points:
        segment = min(range(len(route_points)), key=lambda i: math.hypot(route_points[i][0] - wpos[0], route_points[i][2] - wpos[1]))
    # 치명 시퀀스: 마지막 피격부터 거꾸로 5초 이상 공백이 없는 구간
    first = None
    if dmg_events:
        seq = [dmg_events[-1]]
        for r in reversed(dmg_events[:-1]):
            if seq[-1]["t"] - r["t"] <= 5.0:
                seq.append(r)
            else:
                break
        first = seq[-1]
    first_hit_hp = (first["hp"] + first["dmg"]) / max(1, first["mhp"]) if first else None
    hostile_count = len([n for n in (first or {}).get("near", []) if n[1] in (6, 7, 24, 25, 27, 33) and n[2] > 0 and n[4] <= 20]) if first else 0
    return {
        "episode": d.get("episode"),
        "killers": [{"npc": k, "name": names.get(k, ""), "dmg": v} for k, v in killers.most_common(3)],
        "first_hit_hp": round(first_hit_hp, 2) if first_hit_hp is not None else None,
        "hostile_count": hostile_count,
        "segment": segment,
        "flask_used": any(g.get("guard") == "flask" for g in guard_events),
        "retreated": any(g.get("guard") == "retreat" for g in guard_events),
        "dodges": sum(1 for g in guard_events if g.get("guard") == "dodge"),
        "seconds_of_tail": round(tail[-1]["t"] - tail[0]["t"], 1) if len(tail) > 1 else 0,
    }


def propose_all(diag: dict, pb: Playbook) -> list[dict]:
    """진단 → 적용 가능한 플레이북 수정 후보 전부 (우선순위 순). 규칙만 쓸 땐 첫 번째, 판단 모델이 있으면 이 중에서 고른다."""
    out = []
    top = diag["killers"][0] if diag["killers"] else None
    if top and top["npc"] not in pb.avoid_types:
        out.append({"key": "avoid_types", "op": "append", "value": top["npc"],
                    "why": f"{top['name'] or top['npc']} 에게 죽음 ({top['dmg']} 피해) — 보이면 후퇴"})
    if top and top["npc"] in pb.avoid_types:
        # 회피 목록에 있는데도 죽음 = 도망이 안 통하는 적 (날아다니는 것 등) — 회피를 거둔다
        out.append({"key": "avoid_types", "op": "remove", "value": top["npc"],
                    "why": f"{top['name'] or top['npc']} 를 피해 도망쳤는데도 죽음 ({top['dmg']} 피해) — 도망 대신 가드 전진"})
    if diag["hostile_count"] >= pb.crowd_threshold and pb.crowd_threshold > 2:
        out.append({"key": "crowd_threshold", "op": "add", "value": -1,
                    "why": f"적 {diag['hostile_count']}마리에게 죽음 — 더 일찍 스프린트"})
    fh = diag["first_hit_hp"]
    if fh is not None and fh < pb.retreat_hp_pct + 0.1 and not diag["flask_used"] and pb.flask_hp_pct < 0.8:
        out.append({"key": "flask_hp_pct", "op": "add", "value": 0.1,
                    "why": f"첫 피격 때 이미 HP {fh:.0%} 인데 성배병을 안 마심 — 더 일찍 회복"})
    if not diag["retreated"] and fh is not None and fh < 0.5 and pb.retreat_hp_pct < 0.6:
        out.append({"key": "retreat_hp_pct", "op": "add", "value": 0.05,
                    "why": f"후퇴 없이 죽음 (첫 피격 HP {fh:.0%}) — 더 일찍 후퇴"})
    # ── DSR 전투 파라미터 (사용자 원칙: 막고 한 대 / 다수면 유인 / 몰려오면 도망) ──
    import env
    if env.GAME == "dsr":
        if diag["hostile_count"] >= 2 and hasattr(pb, "lock_range") and pb.lock_range > 3.0:
            out.append({"key": "lock_range", "op": "add", "value": -1.0,
                        "why": f"적 {diag['hostile_count']}마리 앞에서 죽음 — 더 가까이 올 때까지 교전 안 함 (lock_range −1)"})
        if diag["hostile_count"] <= 1 and hasattr(pb, "attack_cooldown") and pb.attack_cooldown < 4.0:
            out.append({"key": "attack_cooldown", "op": "add", "value": 0.5,
                        "why": f"1:1 에서 죽음 — 선공을 줄이고 막기 위주로 (attack_cooldown +0.5)"})
    if diag["segment"] is not None and diag["segment"] not in pb.sprint_segments:
        out.append({"key": "sprint_segments", "op": "append", "value": diag["segment"],
                    "why": f"구간 wp{diag['segment']} 에서 죽음 — 그 구간은 달려서 통과"})
    return out


def propose(diag: dict, pb: Playbook) -> dict | None:
    """진단 → 플레이북 수정 제안 1개 (우선순위 순). 없으면 None."""
    cands = propose_all(diag, pb)
    return cands[0] if cands else None
