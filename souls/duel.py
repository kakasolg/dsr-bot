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
SWITCH_MARGIN, SWITCH_HOLD = 0.8, 3.0
SWITCH_R = 2.5           # 이 안(수평·같은 높이)에 목표보다 가까운 깨어 있는 놈이 있으면 그놈부터
RANGED_SWITCH_R = 25.0   # 던지는/쏘는 놈(foes.ranged)이 휘두르는 중(던지는 중)이면 거리·높이 상관없이 이 안이면 그놈부터 (사용자: "위에 화살 쏘는 놈부터")
LEDGE_DY = 3.0           # 그놈이 arena 보다 이만큼 높거나 낮으면 끌어오지 않는다 (따라오지 않는다)
SWING_S = 1.6            # 공격 애니가 시작된 지 이만큼 넘으면 휘두르는 중으로 안 본다
PULL_R = 8.0             # 끌어오기: 그놈이 이 안이면(움직이지 않아도) 물러나기 시작
SEEK_R = 100.0           # 그놈을 이 반경 안에서 찾는다 — 40 m 로 뒀더니 화톳불에서 42 m 인 1번을 못 보고 전부 '놓침' 이었다
CIRCLE_BEHIND_DEG = 130  # 그놈 정면 기준 이 각 넘게 벗어나면 '등 뒤' — 방패는 정면 부채꼴만 막는다 (사용자 2026-09-25: "방패병도 뒤를 공격 해야함")
CIRCLE_LEAD_DEG = 60     # 매 틱 목표점을 이만큼 앞서 잡아 — 멈추지 않고 계속 돈다 (사용자 시범: 3.5~3.8 s 큰 원호, 걸음마다 서면 그놈이 회전을 따라잡았다)
CIRCLE_SWEEP_S = 4.0     # 한 번에 도는 최대 시간 (실측 3.5~3.8 s + 여유)
CIRCLE_MAX_SWEEPS = 2    # 이만큼 돌아도 등 뒤가 안 되면 포기(길 막힘 등) — 발차기로 대신 (무한 루프 방지)


def _circle_sweep(mv, s, c, cancel) -> float:
    """그놈 둘레를 멈추지 않고 계속 돈다 — 사용자 시범(2026-09-25, play_20260925_062345.jsonl): 3.5~3.8 s 이어지는 큰
    원호로 등 뒤(150~180°)까지 붙어 약공 한 대(303000, 보통 약공과 같은 애니)로 54 피해(HP 85의 63 %) — 걸음마다 서던 예전
    _circle_step 은 그 사이 그놈이 몸을 돌려 따라잡았다. → 마지막 등 뒤 각(절대값, deg)."""
    ptr = c.ptr
    t0 = time.time()
    behind_deg = abs(math.degrees(M.rel_angle(c, s.player)))
    while time.time() - t0 < CIRCLE_SWEEP_S and not cancel():
        s = mv.snap(8.0)
        if s is None or s.cam_yaw is None:
            break
        c = mv.find(s, ptr)
        if c is None or (c.anim or -1) != -1:               # 그놈이 움직이기 시작하면(더는 idle) 멈춘다
            break
        p = s.player
        ang = M.rel_angle(c, p)
        behind_deg = abs(math.degrees(ang))
        if behind_deg >= CIRCLE_BEHIND_DEG:
            break
        sign = 1.0 if ang >= 0 else -1.0
        th = math.radians(CIRCLE_LEAD_DEG) * sign
        dx, dz = p.x - c.x, p.z - c.z
        rx = dx * math.cos(th) + dz * math.sin(th)          # atan2(x, z) 규약 — bearing 을 +th 만큼 돌리는 회전식
        rz = dz * math.cos(th) - dx * math.sin(th)
        mv.pad.move(*mv.stick_to(s, c.x + rx, c.z + rz, 0.7))
        time.sleep(0.05)
    mv.pad.move(0.0, 0.0)
    return behind_deg


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
        # 높이차가 크면(안 내려오는 놈, 못 오르는 턱) '휘두르는 중 + 가까움'만으로 멈추면 거기서 굳는다 — 높이차 안에서만
        # 조기 정지, 아니면 경로를 끝까지 따라간다(있으면 돌아가는 길로) (사용자 2026-09-25: "전투 중에 멈춰 있으려면 돌아가야지",
        # "위험 구역에 왜 머무르고 있어" — 실측: 높이차 1.7~1.9 m 에서 45 s+ "붙기:stopped" 무한 반복, 공격 0회)
        return (d <= weapon.reach and abs(cc.y - sn.player.y) <= 1.0) or (
            (cc.anim or -1) in M.ATTACK and d < NEAR and abs(cc.y - sn.player.y) <= 1.2)

    def mode(sn) -> str:
        cc = mv.find(sn, ptr)                               # 30 m 밖이면 None — 그땐 그냥 걷는다
        if cc is not None and M.horiz(sn.player, cc) < NEAR:
            return "guard"                                  # 가까우면 방패 든 채 걷는다
        if foe.ranged and not any(x.ptr != ptr and x.hp > 0 and not (9000 <= (x.anim or 0) < 9100)
                                   and M.horiz(sn.player, x) < OTHERS_ATTACK_R for x in sn.hostile(OTHERS_ATTACK_R + 2.0)):
            return "sprint"                                 # 던지는 놈은 기다리면 계속 던진다 — 달려 붙는다, 단 주변이 조용할 때만
        # 다른 놈이 8 m 안에 있으면 뛰지 않는다 — 뛰는 동안은 못 막아 2.5 m(SWITCH_R) 안에 들어올 때까지 무방비로 맞는다
        # (사용자 2026-09-25: "쏘는 놈을 잡으려는데 대응이 느려서 다른 몹들에게 둘러싸여") → 방패 들고 걷는다
        return "guard" if foe.ranged else "walk"
    return mv.walk_path(path, nm, mode, stop, timeout_per=6.0)


PUNISH_AFTER = 1.1       # 백스텝 스타일: 공격 시작 뒤 이만큼 지나야 칼이 지나갔다 (1.0 s 안에 들어간 11회 중 8회 맞음, 1.0~1.3 s 는 3/3 무피해)
PUNISH_MIN_R = 1.8       # 이보다 붙어 있으면 헛친 뒤 치기 대신 반사에 맡긴다 (≤1.6 m 에서 들어간 7회 중 5회가 다음 타에 맞음)
PUNISH_R = 1.6           # 닿는 거리 + 이만큼 안이면 걸어 들어가 친다 (0.9 로는 2.5 m 에서 6 s 동안 못 들어감)


def duel(mv: M.Moves, weapon, ptr, nm, log=print, limit: float = 45.0, low_hp: float = 0.25,
         cancel=lambda: False, care=None, reflex=None, arena=None, style=None) -> DuelResult:
    """care: 4층이 주는 회복 담당 — care.wants(s) (마시고 싶나), care.take(recheck) (마신다; recheck(s) 로 틈을 다시 본다).
    틈인지는 여기(3층)가 본다: opening(). 붙어 있으면 백스텝으로 벌리고 다음 틱에 다시 본다.
    reflex: 반사(souls/reflex.py) — 매 틱 가장 먼저. 움직였으면 이 틱은 쉰다 (상대가 아닌 놈의 공격도 정면으로 막는다).
    arena: 이 근처 평평한 자리 — 발밑이 낭떠러지 쪽이면(nav.footing) 그놈이 안 휘두를 때 거기로 물러나 맞이한다.
      사용자 원칙: "애초에 위험한 위치에 있으면 안 되는 게 먼저" — 추락은 퀵 종료로 못 구한다 (떨어지는 중엔 메뉴가 안 열림, 2026-09-24)."""
    from . import style as style_
    style = style_.of(style or "guard")
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
    circle_n = 0                                            # 등 뒤로 도는 시도 횟수 (foe.circle_behind) — 무한 루프 방지
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
                f"나 HP {p_.hp} SP {p_.sp} 애니 {p_.anim} 각 {math.degrees(M.rel_angle(p_, c_)) if p_.heading is not None else 0:+.0f}° | "
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
        ranged_cut = [x for x in s.hostile(RANGED_SWITCH_R) if x.ptr != ptr and x.hp > 0
                      and foes_.of(x.npc_param).ranged and (x.anim or -1) in M.ATTACK]
        # 위(또는 멀리)에서 쏘는 놈은 가까운 끼어든 놈(cut, 아래)과 달리 거리·높이 제한이 없다 — 맞으면서 눈앞 상대만 방어 위주로
        # 상대하게 됐다 (사용자 2026-09-25: "화살 쏘는 애가 공격하니 방어 위주로 세팅됨 — 그놈부터 처리해야 함")
        if ranged_cut and now - switch_t > SWITCH_HOLD:
            x = min(ranged_cut, key=lambda y: M.horiz(p, y))
            if orig_ptr is None:
                orig_ptr = ptr
            log(f"      원거리부터: {x.npc_param} ({M.horiz(p, x):.1f} m, 높이차 {x.y - p.y:+.1f}) — 원래 목표 {h:.1f} m")
            ptr, c, switch_t = x.ptr, x, now
            last_seen, foe = x, foes_.of(x.npc_param)
            h, dy, a = M.horiz(p, c), c.y - p.y, (c.anim if c.anim is not None else -1)
        cut = [x for x in s.hostile(SWITCH_R + 2.0) if x.ptr != ptr and x.hp > 0 and not (9000 <= (x.anim or 0) < 9100)
               and M.horiz(p, x) < min(SWITCH_R, h - SWITCH_MARGIN) and abs(x.y - p.y) < 1.2]
        # 거리가 비슷한 둘 사이에서 1~2 s 마다 목표를 바꿔 몸을 돌리다 등을 맞았다 (±140~166°, 25 s 에 442) —
        # 확실히 더 가까울 때만(SWITCH_MARGIN), 바꾼 뒤 SWITCH_HOLD 동안은 그대로
        if cut and now - switch_t > SWITCH_HOLD:
            # 끼어든 놈부터 (옛 hunt.py 규칙, 사용자: "가까운 적 공격 못해?") — 지도 목표만 보다 옆에서 치는 놈에게 13 s 에 387 맞고 죽었다.
            # 그놈을 잡으면 원래 목표로 돌아간다
            x = min(cut, key=lambda y: M.horiz(p, y))
            if orig_ptr is None:
                orig_ptr = ptr
            log(f"      목표 바꿈: {x.npc_param} ({M.horiz(p, x):.1f} m, 애니 {x.anim}) — 원래 목표 {h:.1f} m")
            ptr, c, switch_t = x.ptr, x, now
            last_seen, foe = x, foes_.of(x.npc_param)
            h, dy, a = M.horiz(p, c), c.y - p.y, (c.anim if c.anim is not None else -1)

        if (c.hp <= FINISH_HP and a not in M.ATTACK and h <= weapon.reach and abs(dy) <= 1.0
                and not (foe is not None and foe.kick_when_idle and a == -1)
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
        if a in M.ATTACK and age is not None and age > SWING_S:
            # 3000 번대가 SWING_S 넘게 이어지면 휘두르는 중이 아니다 (공격이 끝나도 1.5~5.3 s 남는다 — 기록 분석).
            # 창 방패병(255002)은 3001 에 머문 채 방패를 들고 있어, 15 s 내내 1.4 m 에서 막기만 했고 발차기도 안 나갔다
            a = -1
        if (foe.kind != "shield" and h <= weapon.reach and abs(dy) <= 1.0 and (p.sp or 0) >= weapon.sp_min
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
            bh = getattr(reflex, "last_hit", None)
            if bh is not None:                             # 백스텝 공격(한 동작) 결과 — 기록
                reflex.last_hit = None
                d = bh.as_dict()
                res.hits.append({k: d[k] for k in ("kind", "presses", "dmg", "dead", "taken")})
                if bh.dmg > 0:
                    last_dmg_t = time.time()
                    res.dealt += bh.dmg
                log(f"      백스텝 공격 → 피해 {bh.dmg}, 내 피해 {bh.taken} ({h:.1f} m) 내 애니 {bh.my_anims[:6]} 그놈 {bh.e_anims[:5]}")
                note("백스텝공격", s, c)
                if bh.dead and orig_ptr is None:
                    return done("killed")
                continue
            note("반사", s, c)
            time.sleep(0.02)
            continue
        ledge = arena is not None and abs(c.y - arena[1]) > LEDGE_DY
        # 턱 위에 선 놈(경사로 5번 y -39 vs 평지 -49)은 안 내려온다 — 평지로 끌어오거나 물러나면 오르내리기만 반복했다 (세 번 '막힘')
        if (not pulled and not ledge and nm is not None and a not in M.ATTACK and (a != -1 or h < PULL_R)
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
            if arena is not None and not ledge and math.dist((p.x, p.y, p.z), tuple(arena)) > 1.5:
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

        if (a in M.STAGGER or a == M.GUARD_BROKEN) and h <= weapon.reach + 0.3 and abs(dy) <= 1.0 and (p.sp or 0) >= weapon.sp_min:
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
        if style.evade and a in M.ATTACK and h < NEAR:
            # 1b) 백스텝 스타일 (사용자 2026-09-24: "고수들은 백스텝을 적절하게 사용, 백스텝 + 약공, 양손이면 더 강함, 가드 스태미나도 안 씀")
            #     휘두르기 시작은 반사가 백스텝으로 피했다(뒤에 바닥 있을 때). 칼이 지나간 뒤(PUNISH_AFTER)면 한 걸음 들어가 약공.
            if (age is not None and age >= style.punish_after and style.punish_min_r <= h <= weapon.reach + PUNISH_R and abs(dy) <= 1.0
                    and (p.sp or 0) >= weapon.sp_min and mv.face(s, c, deg=30.0)):
                if h > weapon.reach and s.cam_yaw is not None:
                    mv.pad.move(*mv.stick_to(s, c.x, c.z, 0.8))
                    time.sleep(min(0.45, 0.12 + (h - weapon.reach) * 0.22))   # 2.5 m/s 걷기 — 남은 거리만큼
                    mv.pad.move(0.0, 0.0)
                hit = mv.light(s, c, n=weapon.combo, sp_second=weapon.sp_min)
                d = hit.as_dict()
                res.hits.append({k: d[k] for k in ("kind", "presses", "dmg", "dead", "taken")})
                if hit.dmg > 0:
                    last_dmg_t = time.time()
                    res.dealt += hit.dmg
                note("뒤치기", s, c)
                log(f"      헛친 뒤 → {hit.kind}×{hit.presses} 피해 {hit.dmg}, 내 피해 {hit.taken} ({h:.1f} m, {age:.2f} s)")
                if hit.dead and orig_ptr is None:
                    return done("killed")
                continue
            mv.guard(False)
            mv.face(s, c, deg=25.0)                        # 정면에 둔 채 칼이 지나가길 기다린다 (방패 없이)
            note("피함대기", s, c)
            time.sleep(0.02)
            continue
        if style.shield and a in M.ATTACK and h < NEAR:     # 1) 휘두르는 중 → 막는다 (방패 있는 스타일만 —
            # rush(방패 없음·안 피함)는 여기서 서서 맞기만 하면 상대 콤보가 안 끊겨 8 s+ 0 공격으로 676 받았다, 2026-09-25)
            mv.guard(True)
            if h > weapon.reach + 0.3 and abs(dy) <= 1.0 and s.cam_yaw is not None and (
                    nm is None or nav.ground_ahead(nm, p, c.x - p.x, c.z - p.z, reach=0.8)):
                # 닿는 거리 밖에서 제자리로 막기만 하면 멀리서 휘두르는 놈(3008 반복)에게 영영 못 닿는다 — 방패 든 채 다가간다
                mv.pad.move(*mv.stick_to(s, c.x, c.z, 0.6))
                note("막으며다가감", s, c)
            else:
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
            # 수평 거리만 보고 "3 m 안이면 막힌 게 아니다"로 두면, 안 내려오는 놈(높이차만 큰 경우)에서 h 가 계속 <3 이라
            # best_t 가 매 틱 갱신돼 stuck 판정이 영영 안 났다 (실측 2026-09-25: 높이차 1.7~1.9 m 에서 45 s+ "붙기:stopped" 반복,
            # 공격 0회 — 사용자: "전투 중에 멈춰 있으려면 돌아가야지", "위험 구역에 왜 머무르고 있어"). 높이차까지 좁아져야 진전으로 친다.
            if h < 3.0 and abs(dy) <= 1.2:
                best_h, best_t = h, now                    # 진짜 닿는 거리 안(높이도)이면 막힌 게 아니다
            elif best_h is None or h < best_h - 0.5:
                best_h, best_t = h, now
            elif now - best_t > 8.0:
                return done("stuck")
            r = _approach(mv, weapon, s, c, nm, foe, cancel, log)
            last_dmg_t = time.time()                       # 붙는 데 걸린 시간은 교착이 아니다 (한 번에 17 s 걸었다)
            note(f"붙기:{r}", s, c)
            if r == "dead":
                return done("me_dead")
            continue
        if (c.hp <= FINISH_HP and (p.sp or 0) >= FINISH_SP and not (foe.kick_when_idle and a == -1)
                and mv.face(s, c, deg=30.0)):   # 방패 든 채 서 있는 방패병은 마무리도 막힌다 (22 → 21 → 20, 되받아 114) — 발차기로
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
        if (p.sp or 0) < weapon.sp_min:                    # 4) 스태미나 — 방패를 내리고(회복 80 % 감소, 위키) 그놈을 정면에 둔 채 선다
            # 물러나게 했더니 락온 없이 반대쪽으로 스틱을 밀어 **뒤돌아 걸어가** 등을 맞았다 (몸-그놈 ±180°, 사용자: "방향 정렬 못하고")
            mv.guard(False)
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
        if a in M.ATTACK and reflex is not None and (reflex.attack_age(ptr) or 0.0) > SWING_S:
            a = -1                                         # 가드 자세로 머문 3000 번대 — 선 것으로 (발차기)
        behind_deg = abs(math.degrees(M.rel_angle(c, s.player))) if c.heading is not None else 0.0
        looks_at_me = behind_deg < 60
        if (foe.circle_behind and a == -1 and behind_deg < CIRCLE_BEHIND_DEG and circle_n < CIRCLE_MAX_SWEEPS
                and h <= weapon.reach + 1.5 and (nm is None or nav.ground_ahead(nm, p, c.x - p.x, c.z - p.z, reach=1.0))):
            # 방패는 정면 부채꼴만 막는다 — 도는 동안은 공격하지 않는다(무기대로 치면 또 막힌다). CIRCLE_MAX_SWEEPS 넘으면 포기하고 아래(발차기 등)로
            circle_n += 1
            behind_deg = _circle_sweep(mv, s, c, cancel)
            note(f"등뒤돌기:{behind_deg:.0f}", s, c)
            continue
        circle_n = 0
        if foe.kick_when_idle and a == -1 and looks_at_me and now - kick_t > KICK_COOLDOWN:
            kick_t = now
            hit = mv.kick_combo(s, c, n=weapon.combo)       # 발차기 → 곧장 약공 (간격이 크면 방패병이 다시 가드, 사용자)
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
