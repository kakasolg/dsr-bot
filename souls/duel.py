"""3층 — 한 마리 상대. 무기 사용법(2층)과 적 종류(foes)를 보고 1층 동작을 고른다.
결과만 돌려준다. 에스트를 마실지·퀵 종료할지·다음에 누구를 칠지는 4층(field)이 정한다.

한 틱의 순서:
  1) 그놈이 휘두르는 중이고 4 m 안 → 방패 들고 그쪽을 본다 (맞바꾸지 않는다)
  2) 넘어져 있으면 방패 들고 기다린다
  3) 닿는 거리(무기 reach, 수평) 밖이거나 높이가 1 m 넘게 다르면 → 경로를 따라 붙는다 (높은 턱 위도 올라간다)
  4) 스태미나가 모자라면 방패
  5) 몸을 그놈에 맞추고: 방패 든 놈이 나를 보고 서 있으면 발차기, 아니면 무기대로 (브로드소드: 약공 2연타)
  0) (맨 앞) 4층이 마시고 싶어 하면: 틈(opening)이면 마시고, 붙어 있으면 백스텝으로 벌린다
끝나는 조건: 처치 · 내 죽음 · 내 HP 낮음 · 놓침 · 15 s 동안 피해를 못 줌(교착) · 시간 초과 · 취소(탈출 중)
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

import nav
import patrol

from . import foes as foes_
from . import moves as M

STALEMATE_S = 15.0       # 이만큼 피해를 못 주면 교착 — 예전엔 '6번 쳐도 안 죽음'(발차기·막힌 약공도 셌다)으로 판을 버렸다
NEAR = 4.0               # 이 안에서 그놈이 휘두르면 방패
KICK_COOLDOWN = 2.5
OPEN_R = 3.0             # 싸우는 중 에스트 '틈': 그놈이 넘어졌거나, 휘두르지 않고 이만큼 떨어져 있을 때
OTHERS_R, OTHERS_ATTACK_R = 5.0, 8.0   # 그리고 다른 깨어 있는 놈이 5 m 안에 없고, 8 m 안에 휘두르는 놈이 없을 때
CARE_RETRY = 3.0


def _others_quiet(s, ptr) -> bool:
    for x in s.hostile(OTHERS_ATTACK_R):
        if x.ptr == ptr or 9000 <= (x.anim or 0) < 9100:
            continue
        if x.dist < OTHERS_R or (x.anim or -1) in M.ATTACK:
            return False
    return True


def opening(s, ptr) -> bool:
    """지금 마실 틈인가 — 그놈이 넘어져 있거나(일어나는 중 제외), 휘두르지 않고 OPEN_R 넘게 떨어져 있고, 다른 놈은 조용할 때."""
    c = next((x for x in s.chars if x.ptr == ptr), None)
    if c is None:
        return _others_quiet(s, ptr)
    a = c.anim if c.anim is not None else -1
    down = a in M.DOWNED and a != M.GETTING_UP
    return (down or (a not in M.ATTACK and M.horiz(s.player, c) >= OPEN_R)) and _others_quiet(s, ptr)


@dataclass
class DuelResult:
    result: str                      # killed | me_dead | low_hp | lost | stalemate | stuck | timeout | cancel
    npc: int | None = None
    secs: float = 0.0
    dealt: int = 0
    taken: int = 0
    hits: list = field(default_factory=list)

    def line(self) -> str:
        kinds = [h["kind"] + ("" if h["dmg"] else "×") for h in self.hits]
        return f"{self.result} — {self.secs:.0f} s, 준 피해 {self.dealt}, 받은 피해 {self.taken}, 공격 {' '.join(kinds) or '없음'}"


def _approach(mv: M.Moves, weapon, s, c, nm, foe, cancel) -> str:
    """경로를 따라 그놈에게 붙는다. 붙거나 / 그놈이 휘두르기 시작하거나 / 취소면 그 틱에 멈춘다."""
    p, ptr = s.player, c.ptr
    goal = (c.x, c.y, c.z)
    path = nm.find_path((p.x, p.y, p.z), goal) if nm is not None else None
    if not path or len(path) < 2:
        if s.cam_yaw is None:
            return "no_cam"
        mv.pad.move(*mv.stick_to(s, c.x, c.z, 0.8))        # 경로가 없으면 한 걸음만
        time.sleep(0.15)
        mv.pad.move(0.0, 0.0)
        return "step"
    path = nav.trim_path(path[1:], goal, within=weapon.reach)

    def stop(sn) -> bool:
        cc = mv.find(sn, ptr)
        if cc is None or cc.hp <= 0 or cancel():
            return True
        d = M.horiz(sn.player, cc)
        return (d <= weapon.reach and abs(cc.y - sn.player.y) <= 1.0) or ((cc.anim or -1) in M.ATTACK and d < NEAR)

    def mode(sn) -> str:
        cc = mv.find(sn, ptr)
        if cc is not None and M.horiz(sn.player, cc) < NEAR:
            return "guard"                                  # 가까우면 방패 든 채 걷는다
        return "sprint" if foe.ranged else "walk"           # 던지는 놈은 기다리면 계속 던진다 — 달려 붙는다
    return mv.walk_path(path, nm, mode, stop, timeout_per=6.0)


def duel(mv: M.Moves, weapon, ptr, nm, log=print, limit: float = 45.0, low_hp: float = 0.25,
         cancel=lambda: False, care=None, reflex=None) -> DuelResult:
    """care: 4층이 주는 회복 담당 — care.wants(s) (마시고 싶나), care.take(recheck) (마신다; recheck(s) 로 틈을 다시 본다).
    틈인지는 여기(3층)가 본다: opening(). 붙어 있으면 백스텝으로 벌리고 다음 틱에 다시 본다.
    reflex: 반사(souls/reflex.py) — 매 틱 가장 먼저. 움직였으면 이 틱은 쉰다 (상대가 아닌 놈의 공격도 정면으로 막는다)."""
    t0 = time.time()
    s0 = mv.snap()
    hp_start = s0.player.hp if s0 else 0
    res = DuelResult("timeout")
    last_dmg_t, kick_t = t0, 0.0
    best_h, best_t = None, t0
    last_seen, foe = None, None
    care_t, backstep_t = 0.0, 0.0

    def done(result: str) -> DuelResult:
        mv.pad.guard(False)
        mv.pad.move(0.0, 0.0)
        s_ = mv.snap(5.0)
        res.result, res.secs = result, time.time() - t0
        res.taken = max(0, hp_start - (s_.player.hp if s_ else 0))
        return res

    while True:
        if cancel():
            return done("cancel")
        now = time.time()
        if now - t0 > limit:
            return done("timeout")
        s = mv.snap(40.0)
        if s is None:
            time.sleep(0.05)
            continue
        p = s.player
        if p.hp is not None and p.hp <= 0:
            return done("me_dead")
        c = mv.find(s, ptr)
        if c is None:
            # 목록에서 빠졌다 — 죽은 시체가 빠진 것일 수도, 퀵 종료로 포인터가 바뀐 것일 수도. 같은 종류가 근처에 살아 있으면 그놈
            if last_seen is not None:
                again = [x for x in s.chars if x.npc_param == last_seen.npc_param and x.hp > 0
                         and math.dist((x.x, x.y, x.z), (last_seen.x, last_seen.y, last_seen.z)) < 3.0]
                if again:
                    ptr = again[0].ptr
                    continue
                if res.hits and res.hits[-1]["dead"]:
                    return done("killed")
            return done("lost")
        if c.hp <= 0:
            return done("killed")
        last_seen = c
        if foe is None:
            foe = foes_.of(c.npc_param)
            res.npc = c.npc_param
        if p.hp < p.max_hp * low_hp:
            return done("low_hp")
        if now - last_dmg_t > STALEMATE_S:
            return done("stalemate")
        h, dy, a = M.horiz(p, c), c.y - p.y, (c.anim if c.anim is not None else -1)

        if reflex is not None and reflex.tick(s):          # 반사: 2.5 m 안 누구든 휘두르기 시작하면 정면으로 막는다
            time.sleep(0.02)
            continue
        if care is not None and now - care_t > CARE_RETRY and care.wants(s):   # 0) 싸우는 중 에스트 (사용자: 안전하면 마셔)
            if opening(s, ptr):
                care_t = now
                r = care.take(lambda sn: opening(sn, ptr))
                log(f"      싸우는 중 에스트: {r}")
                continue
            if (a not in M.ATTACK and h < OPEN_R and now - backstep_t > 2.0 and p.heading is not None and _others_quiet(s, ptr)
                    and nav.ground_ahead(nm, p, math.sin(p.heading), math.cos(p.heading), reach=2.2)):
                backstep_t = now                           # 붙어 있다 — 뒤에 바닥이 있으면 백스텝으로 벌린다
                mv.backstep()
                continue

        if a in M.ATTACK and h < NEAR:                     # 1) 휘두르는 중 → 막는다
            mv.guard(True)
            mv.face(s, c)
            time.sleep(0.02)
            continue
        if a in M.DOWNED and a != M.GETTING_UP:            # 2) 누워 있다
            mv.guard(True)
            mv.face(s, c)
            time.sleep(0.03)
            continue
        if h > weapon.reach or abs(dy) > 1.0:              # 3) 붙는다
            if best_h is None or h < best_h - 0.5:
                best_h, best_t = h, now
            elif now - best_t > 8.0:
                return done("stuck")
            r = _approach(mv, weapon, s, c, nm, foe, cancel)
            if r == "dead":
                return done("me_dead")
            continue
        if (p.sp or 0) < weapon.sp_min:                    # 4) 스태미나
            mv.guard(True)
            mv.face(s, c)
            time.sleep(0.03)
            continue
        if not mv.face(s, c):                              # 5) 몸 맞추기
            time.sleep(0.02)
            continue
        s = mv.snap(40.0)
        c = mv.find(s, ptr) if s else None
        if c is None:
            continue
        a = c.anim if c.anim is not None else -1
        looks_at_me = c.heading is not None and abs(math.degrees(patrol.rel_angle(c, s.player))) < 60
        if foe.kick_when_idle and a == -1 and looks_at_me and now - kick_t > KICK_COOLDOWN:
            kick_t = now
            hit = mv.kick(s, c)
        elif weapon.use_heavy:
            hit = mv.heavy(s, c)
        else:
            hit = mv.light(s, c, n=weapon.combo, sp_second=weapon.sp_min)
        d = hit.as_dict()
        res.hits.append({k: d[k] for k in ("kind", "presses", "dmg", "dead", "taken")})
        if hit.dmg > 0:
            last_dmg_t = time.time()
            res.dealt += hit.dmg
        log(f"      {hit.kind}×{hit.presses} → 피해 {hit.dmg}, 내 피해 {hit.taken}, 그놈 애니 {hit.e_anims[:4]}")
        if hit.dead:
            return done("killed")
