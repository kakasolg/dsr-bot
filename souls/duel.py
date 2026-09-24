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

STALEMATE_S = 15.0       # 닿는 거리 안에서 이만큼 피해를 못 주면 교착 — 예전엔 '6번 쳐도 안 죽음'(발차기·막힌 약공도 셌다)으로 판을 버렸다
NEAR = 4.0               # 이 안에서 그놈이 휘두르면 방패
KICK_COOLDOWN = 2.5
OPEN_R = 3.0             # 싸우는 중 에스트 '틈': 그놈이 넘어졌거나, 휘두르지 않고 이만큼 떨어져 있을 때
OTHERS_R, OTHERS_ATTACK_R = 5.0, 8.0   # 그리고 다른 깨어 있는 놈이 5 m 안에 없고, 8 m 안에 휘두르는 놈이 없을 때
CARE_RETRY = 3.0
FINISH_KEEP_HP = 40     # 그놈 HP 가 이 아래면 내 HP 가 낮아도(12 % 까지) 빠지지 않는다 (다크사인 뒤 방패병이 10 → 85)
FINISH_HP, FINISH_SP = 25, 15   # 그놈 HP 가 약공 한 대(실측 34~41) 안쪽이면 스태미나 15 만 있어도 친다
INTERRUPT_S = 0.35       # 그놈 공격이 시작된 지 이만큼 안이면 막지 말고 먼저 친다 (약공이 닿는 게 더 빠르다)
SWITCH_R = 2.5           # 이 안(수평·같은 높이)에 목표보다 가까운 깨어 있는 놈이 있으면 그놈부터
PULL_R = 8.0             # 끌어오기: 그놈이 이 안이면(움직이지 않아도) 물러나기 시작
SEEK_R = 100.0           # 그놈을 이 반경 안에서 찾는다 — 40 m 로 뒀더니 화톳불에서 42 m 인 1번을 못 보고 전부 '놓침' 이었다


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


def _approach(mv: M.Moves, weapon, s, c, nm, foe, cancel, log=lambda *a: None) -> str:
    """경로를 따라 그놈에게 붙는다. 붙거나 / 그놈이 휘두르기 시작하거나 / 취소면 그 틱에 멈춘다.
    경로는 **출발할 때 그놈 자리**로 짠다 — 그놈이 움직이면 도착한 뒤 다시 짠다 (1 s 마다 그놈 위치를 기록)."""
    p, ptr = s.player, c.ptr
    goal = (c.x, c.y, c.z)
    seen_t = [time.time()]
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
        if cancel():
            return True
        cc = mv.find(sn, ptr)
        if time.time() - seen_t[0] >= 1.0:
            seen_t[0] = time.time()
            where = "30 m 밖(안 보임)" if cc is None else f"그놈 ({cc.x:.1f}, {cc.y:.1f}, {cc.z:.1f}) 애니 {cc.anim}, 거리 {M.horiz(sn.player, cc):.1f}"
            log(f"        붙는 중: 나 ({sn.player.x:.1f}, {sn.player.y:.1f}, {sn.player.z:.1f}) → 목표 {tuple(round(v, 1) for v in goal)} | {where}")
        if cc is None:
            return False          # goto 의 스냅샷은 30 m 안만 담는다 — 멀리 있는 그놈이 안 보이는 건 사라진 게 아니다
        if cc.hp <= 0:
            return True
        d = M.horiz(sn.player, cc)
        if any(x.ptr != ptr and x.hp > 0 and not (9000 <= (x.anim or 0) < 9100) and M.horiz(sn.player, x) < SWITCH_R
               and abs(x.y - sn.player.y) < 1.2 for x in sn.hostile(SWITCH_R + 2.0)):
            return True           # 걸어가는데 다른 놈이 붙었다 — 멈추고 그놈부터 (duel 이 목표를 바꾼다)
        return (d <= weapon.reach and abs(cc.y - sn.player.y) <= 1.0) or ((cc.anim or -1) in M.ATTACK and d < NEAR)

    def mode(sn) -> str:
        cc = mv.find(sn, ptr)                               # 30 m 밖이면 None — 그땐 그냥 걷는다
        if cc is not None and M.horiz(sn.player, cc) < NEAR:
            return "guard"                                  # 가까우면 방패 든 채 걷는다
        return "sprint" if foe.ranged else "walk"           # 던지는 놈은 기다리면 계속 던진다 — 달려 붙는다
    return mv.walk_path(path, nm, mode, stop, timeout_per=6.0)


def duel(mv: M.Moves, weapon, ptr, nm, log=print, limit: float = 45.0, low_hp: float = 0.25,
         cancel=lambda: False, care=None, reflex=None, arena=None) -> DuelResult:
    """care: 4층이 주는 회복 담당 — care.wants(s) (마시고 싶나), care.take(recheck) (마신다; recheck(s) 로 틈을 다시 본다).
    틈인지는 여기(3층)가 본다: opening(). 붙어 있으면 백스텝으로 벌리고 다음 틱에 다시 본다.
    reflex: 반사(souls/reflex.py) — 매 틱 가장 먼저. 움직였으면 이 틱은 쉰다 (상대가 아닌 놈의 공격도 정면으로 막는다).
    arena: 이 근처 평평한 자리 — 발밑이 낭떠러지 쪽이면(nav.footing) 그놈이 안 휘두를 때 거기로 물러나 맞이한다.
      사용자 원칙: "애초에 위험한 위치에 있으면 안 되는 게 먼저" — 추락은 퀵 종료로 못 구한다 (떨어지는 중엔 메뉴가 안 열림, 2026-09-24)."""
    t0 = time.time()
    s0 = mv.snap()
    hp_start = s0.player.hp if s0 else 0
    res = DuelResult("timeout")
    last_dmg_t, kick_t = t0, 0.0
    best_h, best_t = None, t0
    last_seen, foe = None, None
    care_t, backstep_t, move_t = 0.0, 0.0, 0.0
    pulled = arena is None
    orig_ptr, switch_t = None, 0.0
    acts: dict = {}                                        # 1 s 동안 한 일 (기록용)
    note_t = [t0]

    def note(act: str, s_, c_) -> None:
        """틱마다 한 일을 세고, 1 s 마다 한 줄 — 어디서 막히는지 보이게 (2026-09-24: 4 m 앞에서 18 s 동안 못 친 원인을 몰랐다)."""
        acts[act] = acts.get(act, 0) + 1
        if time.time() - note_t[0] < 1.0:
            return
        note_t[0] = time.time()
        p_ = s_.player
        a_ = c_.anim if c_.anim is not None else -1
        line = (f"      [{time.time() - t0:4.1f}s] 거리 {M.horiz(p_, c_):.1f} 높이 {c_.y - p_.y:+.1f} 그놈 애니 {a_} HP {c_.hp} | "
                f"나 HP {p_.hp} SP {p_.sp} 애니 {p_.anim} 각 {math.degrees(patrol.rel_angle(p_, c_)) if p_.heading is not None else 0:+.0f}° | "
                + " ".join(f"{k}×{v}" for k, v in acts.items()))
        log(line)
        acts.clear()

    hp_min = [hp_start]

    def done(result: str) -> DuelResult:
        mv.pad.guard(False)
        mv.pad.move(0.0, 0.0)
        s_ = mv.snap(5.0)
        if s_ and s_.player.hp is not None:
            hp_min[0] = min(hp_min[0], s_.player.hp)
        res.result, res.secs = result, time.time() - t0
        res.taken = max(0, hp_start - hp_min[0])          # 가장 낮았던 HP 기준 (중간에 마신 에스트가 가리지 않게)
        return res

    while True:
        if cancel():
            return done("cancel")
        now = time.time()
        if now - t0 > limit:
            return done("timeout")
        s = mv.snap(SEEK_R)
        if s is None:
            time.sleep(0.05)
            continue
        p = s.player
        if p.hp is not None:
            hp_min[0] = min(hp_min[0], p.hp)
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
            if orig_ptr is not None and orig_ptr != ptr:   # 끼어든 놈이 사라졌다 (죽어서 빠짐) — 원래 목표로
                ptr, orig_ptr, last_seen = orig_ptr, None, None
                continue
            if last_seen is not None and res.hits and res.hits[-1]["dead"]:
                return done("killed")
            return done("lost")
        if c.hp <= 0:
            if orig_ptr is not None and orig_ptr != ptr:
                log(f"      끼어든 {c.npc_param} 처치 — 원래 목표로")
                ptr, orig_ptr = orig_ptr, None
                last_seen = None
                continue
            return done("killed")
        last_seen = c
        if foe is None:
            foe = foes_.of(c.npc_param)
            res.npc = c.npc_param
        if p.hp < p.max_hp * low_hp and not (c.hp <= FINISH_KEEP_HP and p.hp >= p.max_hp * 0.12):
            return done("low_hp")                          # 거의 잡은 놈 앞에선 안 빠진다 — 빠졌다 오면 살아 있던 놈은 HP 가 다시 찬다
        if now - last_dmg_t > STALEMATE_S:
            return done("stalemate")
        h, dy, a = M.horiz(p, c), c.y - p.y, (c.anim if c.anim is not None else -1)
        cut = [x for x in s.hostile(SWITCH_R + 2.0) if x.ptr != ptr and x.hp > 0 and not (9000 <= (x.anim or 0) < 9100)
               and M.horiz(p, x) < min(SWITCH_R, h) and abs(x.y - p.y) < 1.2]
        if cut and now - switch_t > 1.0:
            # 끼어든 놈부터 (옛 hunt.py 규칙, 사용자: "가까운 적 공격 못해?") — 지도 목표만 보다 옆에서 치는 놈에게 13 s 에 387 맞고 죽었다.
            # 그놈을 잡으면 원래 목표로 돌아간다
            x = min(cut, key=lambda y: M.horiz(p, y))
            if orig_ptr is None:
                orig_ptr = ptr
            log(f"      목표 바꿈: {x.npc_param} ({M.horiz(p, x):.1f} m, 애니 {x.anim}) — 원래 목표 {h:.1f} m")
            ptr, c, switch_t = x.ptr, x, now
            last_seen, foe = x, foes_.of(x.npc_param)
            h, dy, a = M.horiz(p, c), c.y - p.y, (c.anim if c.anim is not None else -1)

        if (c.hp <= FINISH_HP and a not in M.ATTACK and h <= weapon.reach + 0.2 and abs(dy) <= 1.0
                and (p.sp or 0) >= FINISH_SP and mv.face(s, c, deg=30.0)):
            # 한 대면 죽고 지금 안 휘두른다 — 반사보다 먼저 친다 (HP 18 인 놈 앞에서 반사가 매 틱 방패만 쥐다 죽었다)
            hit = mv.light(s, c, n=1)
            d = hit.as_dict()
            res.hits.append({k: d[k] for k in ("kind", "presses", "dmg", "dead", "taken")})
            if hit.dmg > 0:
                last_dmg_t = time.time()
                res.dealt += hit.dmg
            note("마무리", s, c)
            if hit.dead and orig_ptr is None:
                return done("killed")
            continue
        if reflex is not None:
            reflex.prefer = ptr
            reflex.update(s)
        age = reflex.attack_age(ptr) if reflex is not None else None
        if (foe.kind != "shield" and h <= weapon.reach + 0.2 and abs(dy) <= 1.0 and (p.sp or 0) >= weapon.sp_min
                and (a == -1 or (a in M.ATTACK and age is not None and age < INTERRUPT_S))
                and not any(x.ptr != ptr and (x.anim or -1) in M.ATTACK and M.horiz(p, x) < 2.5 for x in s.hostile(4.5))
                and mv.face(s, c, deg=30.0)):
            # 먼저 친다 (사용자: "한 대라도 휘두르면 그 적이 물러났을 텐데") — 망자는 약공 한 대에 경직(2000·2002)돼 물러난다.
            # 공격을 막 시작했을 때(INTERRUPT_S 안)나 가만히 서 있을 때. 방패병은 방패에 막히니 제외, 옆에서 다른 놈이 휘두르면 막기부터
            hit = mv.light(s, c, n=weapon.combo, sp_second=weapon.sp_min)
            d = hit.as_dict()
            res.hits.append({k: d[k] for k in ("kind", "presses", "dmg", "dead", "taken")})
            if hit.dmg > 0:
                last_dmg_t = time.time()
                res.dealt += hit.dmg
            note("먼저치기", s, c)
            log(f"      먼저 치기 → {hit.kind}×{hit.presses} 피해 {hit.dmg}, 내 피해 {hit.taken}")
            if hit.dead and orig_ptr is None:
                return done("killed")
            continue
        if reflex is not None and reflex.tick(s):          # 반사: 2.5 m 안 누구든 휘두르기 시작하면 정면으로 막는다
            note("반사", s, c)
            time.sleep(0.02)
            continue
        if (not pulled and nm is not None and a not in M.ATTACK and (a != -1 or h < PULL_R)
                and math.dist((p.x, p.y, p.z), tuple(arena)) > 3.0):
            # 0--) 끌어오기 (사용자: "원하는 지형까지 끌고 가기") — 그놈이 알아채면(움직이거나 가까우면) arena 로 물러난다.
            # 경사로 2번 자리는 위 턱의 화염병이 떨어지는 곳이라, 거기서 붙었더니 1 s 에 275 를 맞았다 (2026-09-24)
            pulled = True
            path = nm.find_path((p.x, p.y, p.z), tuple(arena))
            if path:
                r = mv.walk_path(nav.trim_path(path[1:], tuple(arena), within=0.8), nm, "sprint",
                                 stop=lambda sn: cancel() or any((x.anim or -1) in M.ATTACK and M.horiz(sn.player, x) < NEAR
                                                                 for x in sn.hostile(NEAR + 1.0)))
                note(f"끌어오기:{r}", s, c)
                continue
        if (nm is not None and a not in M.ATTACK and now - move_t > 3.0 and p.gx is not None
                and nav.footing(nm, p)[0] < nav.FOOTING_MIN):
            # 0-) 낭떠러지 옆 — 평평한 자리로 (그놈은 따라온다). arena 가 없으면 바닥이 가장 넓은 쪽으로 한 걸음
            move_t = now
            if arena is not None and math.dist((p.x, p.y, p.z), tuple(arena)) > 1.5:
                path = nm.find_path((p.x, p.y, p.z), tuple(arena))
                if path:
                    r = mv.walk_path(nav.trim_path(path[1:], tuple(arena), within=0.8), nm, "walk",
                                     stop=lambda sn: cancel() or any((x.anim or -1) in M.ATTACK and M.horiz(sn.player, x) < NEAR
                                                                     for x in sn.hostile(NEAR + 1.0)))
                    note(f"자리옮김:{r}", s, c)
                    continue
            best = nav.footing(nm, p)[1]
            if best is not None and s.cam_yaw is not None:
                mv.pad.guard(False)
                mv.pad.move(*mv.stick_to(s, p.x + best[0], p.z + best[1]))
                time.sleep(0.35)
                mv.pad.move(0.0, 0.0)
                note("가장자리벗어남", s, c)
                continue
        if care is not None and now - care_t > CARE_RETRY and care.wants(s):   # 0) 싸우는 중 에스트 (사용자: 안전하면 마셔)
            if opening(s, ptr):
                care_t = now
                r = care.take(lambda sn: opening(sn, ptr))
                log(f"      싸우는 중 에스트: {r}")
                note("에스트", s, c)
                continue
            if (a not in M.ATTACK and h < OPEN_R and now - backstep_t > 2.0 and p.heading is not None and _others_quiet(s, ptr)
                    and nav.ground_ahead(nm, p, math.sin(p.heading), math.cos(p.heading), reach=2.2)):
                backstep_t = now                           # 붙어 있다 — 뒤에 바닥이 있으면 백스텝으로 벌린다
                mv.backstep()
                note("백스텝", s, c)
                continue

        if a in M.STAGGER and h <= weapon.reach + 0.6 and abs(dy) <= 1.0 and (p.sp or 0) >= weapon.sp_min:
            # 1-) 휘청 = 틈. 몸만 맞으면 곧장 친다 (막기에 튕긴 뒤 바로 — 옛 메모 "3500 휘청 — 붙어 있으면 바로 친다")
            if mv.face(s, c, deg=30.0):
                hit = mv.light(s, c, n=foe.punish_hits or weapon.combo, sp_second=weapon.sp_min)
                d = hit.as_dict()
                res.hits.append({k: d[k] for k in ("kind", "presses", "dmg", "dead", "taken")})
                if hit.dmg > 0:
                    last_dmg_t = time.time()
                    res.dealt += hit.dmg
                note("휘청반격", s, c)
                log(f"      휘청 → {hit.kind}×{hit.presses} 피해 {hit.dmg}, 내 피해 {hit.taken}")
                if hit.dead and orig_ptr is None:
                    return done("killed")
            else:
                note("휘청돌기", s, c)
            continue
        if a in M.ATTACK and h < NEAR:                     # 1) 휘두르는 중 → 막는다
            mv.guard(True)
            mv.face(s, c)
            note("막기", s, c)
            time.sleep(0.02)
            continue
        if a in M.DOWNED and a != M.GETTING_UP:            # 2) 누워 있다
            mv.guard(True)
            mv.face(s, c)
            note("누움대기", s, c)
            time.sleep(0.03)
            continue
        if h > weapon.reach or abs(dy) > 1.0:              # 3) 붙는다
            last_dmg_t = now                               # 교착은 닿는 거리 안에서만 센다 (42 m 걸어가는 동안 '교착' 이었다)
            if h < 3.0 or best_h is None or h < best_h - 0.5:
                best_h, best_t = h, now                    # 3 m 안이면 막힌 게 아니다 (1.5~1.8 m 에 붙은 방패병을 HP 10 남기고 '막힘')
            elif now - best_t > 8.0:
                return done("stuck")
            r = _approach(mv, weapon, s, c, nm, foe, cancel, log)
            last_dmg_t = time.time()                       # 붙는 데 걸린 시간은 교착이 아니다 (한 번에 17 s 걸었다)
            note(f"붙기:{r}", s, c)
            if r == "dead":
                return done("me_dead")
            continue
        if c.hp <= FINISH_HP and (p.sp or 0) >= FINISH_SP and mv.face(s, c, deg=30.0):
            # 3+) 한 대면 죽는다 — 스태미나가 조금 모자라도 친다 (방패병이 HP 10 으로 4 s 버티는 동안 가드가 깨졌다)
            hit = mv.light(s, c, n=1)
            d = hit.as_dict()
            res.hits.append({k: d[k] for k in ("kind", "presses", "dmg", "dead", "taken")})
            if hit.dmg > 0:
                last_dmg_t = time.time()
                res.dealt += hit.dmg
            note("마무리", s, c)
            if hit.dead and orig_ptr is None:
                return done("killed")
            continue
        if (p.sp or 0) < weapon.sp_min:                    # 4) 스태미나 — 방패를 들면 회복이 80 % 준다(위키). 붙어 있으면 물러나 회복
            mv.guard(False)
            if h < 2.5 and s.cam_yaw is not None:
                d = nav.safe_back(nm, p, p.x - c.x, p.z - c.z) if nm is not None else (p.x - c.x, p.z - c.z)
                if d is not None:
                    mv.pad.move(*mv.stick_to(s, p.x + d[0], p.z + d[1], 0.7))
                else:
                    mv.pad.move(0.0, 0.0)
            else:
                mv.face(s, c)
            note("SP회복", s, c)
            time.sleep(0.05)
            continue
        if not mv.face(s, c):                              # 5) 몸 맞추기
            note("돌기", s, c)
            time.sleep(0.02)
            continue
        s = mv.snap(SEEK_R)
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
        note(hit.kind, s, c)
        log(f"      {hit.kind}×{hit.presses} → 피해 {hit.dmg}, 내 피해 {hit.taken}, 그놈 애니 {hit.e_anims[:4]}")
        if hit.dead and orig_ptr is None:
            return done("killed")
