"""4층 — 필드 플레이북. 여러 마리·지형·길. 목표는 **살아서 목적지까지**, 잡은 적은 버리지 않는다.
3층(duel)에 한 마리씩 맡기고, 그 결과를 보고 다음을 정한다:
  · 잡으면 → HP 70 % 아래면 에스트 (안전할 때만)
  · 내 HP 낮음·교착·놓침·막힘 → 퀵 종료로 적을 떼어내고(죽은 적은 그대로) 에스트 → 같은 놈 다시 (세 번까지)
  · 에스트가 없으면 → 그만 (위층이 쉴지 정한다)
  · 길을 걷다 쫓아오는 놈이 붙으면 → 그놈부터 (등 보이고 걷지 않는다 — 사용자: "적이 있는데 왜 대응 안해")
쉬기(화톳불)는 **적이 전부 살아나므로** 이 층에서 함부로 하지 않는다. 핏자국 줍기(A)도 화톳불 6 m 안에선 안 한다 (앉아 버린다).
"""
from __future__ import annotations

import math
import time

import nav

from . import duel as D
from . import foes as foes_
from . import moves as M
from .reflex import Reflex
from . import style as style_
from .watch import Blood

FOLLOW_R = 4.5           # 길을 걷다 이 안(수평)에 깨어 있는 놈이 붙으면 싸운다
FOLLOW_DY = 2.5          # 계단에서 따라오는 놈 — 높이차 이만큼까지
SAFE_R = 6.0             # 에스트: 이 안에 깨어 있는 적이 없고
SAFE_ATTACK_R = 8.0      #          이 안에 휘두르는 놈이 없을 때
RANGED_R = 25.0          #          그리고 이 안에 깨어 움직이는 '던지는 놈'(foes.ranged)이 없을 때
BONFIRE_NO_A = 6.0
FIGHT_HEAL = 0.5         # 싸우는 중: HP 가 이 아래면 틈(duel.opening)에 마신다
WALK_HEAL = 0.6          # 걷는 중: 이 아래고 안전하면 70 % 까지


def awake(c) -> bool:
    return c.hp > 0 and not (9000 <= (c.anim or 0) < 9100)


SEEK_R = 100.0           # 그놈을 찾는 반경 (duel.SEEK_R 과 같게)
LURE_R = 10.0            # 나이프를 던지는 거리 — 락온 상태로 11.9·11.4 m 는 빗나가고 10.8 m 에서 맞음 (2026-09-24, 던진 물건은 ~10 m 날아간다)
LURE_TRIES = 3
LURE_DY = 1.5            # 던질 자리와 목표·지금 자리의 높이차 상한 — 절벽 아래 놈에게 뛰어내리지 않게 (2026-09-24 8판)
LURE_ABORT_R = 10.0              # 던지는 중 이 안에 깨어 움직이는 다른 놈이 있으면 중단
LURE_MIN, LURE_MAX = 6.0, 13.0   # 평지에서 던지는 조건 — 이보다 가까우면 걸어가는 것만으로 깨고, 멀면 락온이 안 걸린다
KNIFE_LOW = 5            # 이 아래면 경고 — 상인에게 사러 가는 건 나중 과제 (사용자 2026-09-24)


class Field:
    def __init__(self, mv: M.Moves, weapon, escape, bonfires: list, log=print, events=None, style="guard"):
        self.mv, self.w, self.esc, self.log = mv, weapon, escape, log
        self.style = style_.of(style)                      # souls/style.py — 각 층은 이 객체를 읽기만 한다
        self.bonfires = [tuple(b) for b in bonfires]      # 핏자국 줍기(A) 금지 구역
        self.home = self.bonfires[0] if self.bonfires else None   # 마지막으로 쉰 화톳불 (물러날 곳, 다크사인 도착 확인)
        self.events = events or (lambda *a, **k: None)
        # 반사 — 싸우든 걷든 매 틱 먼저 (발밑 확인용 내비메시는 쓸 때 넣는다). 막으면 안 되는 공격은 적 데이터(3층)에서
        self.reflex = Reflex(mv, unblockable=lambda c: (c.anim or -1) in foes_.of(c.npc_param).unblockable,
                             bs_ok=lambda c: foes_.of(c.npc_param).kind != "shield")
        self.reflex.evade = self.style.evade
        self.reflex.bs_attack = self.style.bs_attack
        self.reflex.reflex_on = self.style.reflex_on
        mv.guard_ok = self.style.shield
        self.reflex.events = self.events

    # ── 상태 ─────────────────────────────────────────────────
    def alive(self) -> bool:
        s = self.mv.snap(5.0)
        return bool(s and s.player.hp and s.player.hp > 0)

    def wait_respawn(self, timeout: float = 45.0) -> bool:
        """죽었으면 화톳불에서 일어날 때까지 기다린다 (로딩 중엔 스냅샷이 없다)."""
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                s = self.mv.snap(5.0)
            except Exception:
                s = None
            if s and s.player.hp and s.player.hp > 0 and s.player.hp >= s.player.max_hp * 0.99:
                time.sleep(1.0)
                return True
            time.sleep(0.5)
        return False

    def safe(self, s) -> bool:
        """에스트를 마셔도 되나 — 가까운 적이 없고, 휘두르는 놈이 없고, **던지는 놈(화염병)이 RANGED_R 안에 깨어 있지 않을 때**.
        8 m 만 봤더니 위 턱의 화염병 망자에게 마시는 도중 맞아 끊기고 죽었다 (2026-09-24)."""
        for c in s.hostile(RANGED_R):
            if not awake(c):
                continue
            if c.dist < SAFE_R or ((c.anim or -1) in M.ATTACK and c.dist < SAFE_ATTACK_R):
                return False
            if foes_.of(c.npc_param).ranged and (c.anim not in (None, -1)):
                return False
        return True

    # ── 회복 ─────────────────────────────────────────────────
    def heal(self, frac: float = 0.7, sips: int = 3) -> None:
        for _ in range(sips):
            s = self.mv.snap(15.0)
            if not s or s.player.hp >= s.player.max_hp * frac:
                return
            if self.mv.estus_left() <= 0:
                self.log("      에스트 없음")
                return
            if not self.safe(s):
                self.log("      에스트: 근처에 적 — 안 마심")
                return
            r = self.mv.drink(self.safe)
            self.log(f"      에스트: {r}")
            self.events("estus", **r)
            if not r["ok"]:
                return

    def care(self) -> "Care":
        return Care(self)

    def wait_escape(self, timeout: float = 40.0) -> None:
        """퀵 종료가 끝날 때까지 기다린다 — 안 기다렸더니 그 10 s 동안 남은 적 다섯을 0.5 s 만에 전부 '취소' 로 넘겼다."""
        t0 = time.time()
        while self.esc.escaping and time.time() - t0 < timeout:
            time.sleep(0.2)

    def shake_off(self, why: str) -> dict:
        """퀵 종료로 적을 스폰으로 돌려보낸다 (경계 풀림, 죽은 적은 그대로)."""
        return self.esc.fire(why, "shake")

    def retreat(self, nm, home) -> str:
        """화톳불 쪽으로 경로를 따라 물러난다 — 안전해지면 멈춘다 (적은 경계 범위를 벗어나면 돌아간다)."""
        s = self.mv.snap(5.0)
        if s is None or home is None:
            return "no_home"
        path = nm.find_path((s.player.x, s.player.y, s.player.z), tuple(home)) if nm is not None else None
        if not path:
            return "no_path"                               # (헛돌기는 recover 가 False → 다음 싸움을 끝까지로 막는다)
        t0 = time.time()
        return self.mv.walk_path(nav.trim_path(path[1:], tuple(home)), nm, "sprint",
                                 stop=lambda sn: time.time() - t0 > 3.0 and self.safe(sn))

    def recover(self, why: str, nm=None) -> bool:
        """싸움이 틀어졌을 때. → 계속 싸울 만한가
          · 안전하면 에스트로 90 % 까지
          · 적이 가까운데 HP 가 낮으면: 화톳불 쪽으로 물러나 안전해지면 마신다
          · 퀵 종료로 떼어내지 않는다 — 같은 자리에서 다시 시작해 곧바로 다시 붙었다 (5 번 반복, HP 659 → 24, 사용자:
            "지금 위치 강종하기 안 좋아")"""
        s = self.mv.snap(15.0)
        if s is None:
            return False
        low = s.player.hp < s.player.max_hp * 0.6
        if not self.safe(s) and low:
            # 다크사인은 쓰지 않는다 — 쉬는 것처럼 잡은 적이 전부 살아나고(사용자 2026-09-24) 소울·인간성까지 잃는다.
            # 죽는 것보다도 나쁘다 (죽으면 핏자국으로 되찾을 수 있다). 붙은 채 쓰면 쓰는 2~3 s 동안 맞아 죽기도 했다
            r = self.retreat(nm, self.home)
            self.log(f"   {why}: 적이 가깝고 HP {s.player.hp} — 화톳불 쪽으로 물러남: {r}")
        self.heal(0.9, sips=4)
        s = self.mv.snap(5.0)
        return bool(s and s.player.hp >= s.player.max_hp * 0.6)

    # ── 싸움 ─────────────────────────────────────────────────
    def fight(self, ptr, nm, tag: str, arena=None, desperate: bool = False) -> D.DuelResult:
        g0 = self.esc.gen
        e = self.mv.estus_id()
        if e is not None and self.mv.tm.selected_item() != e:
            self.mv.select_item(e)                         # 미리 골라 둔다 — 틈이 났을 때 칸 돌리는 1~3 s 가 없게
        self.reflex.nm = nm
        want = self.style.grip
        if self.mv.tm.grip() not in (None, want):
            # 첫 판(막 쉬고 난 뒤)엔 토글 한 번·0.5 s 로는 안 바뀐 채 싸운 적이 있다(2026-09-25, rush 스타일 1번째 표적이
            # grip 1 그대로 싸움) — 실제로 바뀐 걸 확인할 때까지 다시 시도한다
            for _ in range(3):
                self.mv.pad.two_hand_right()               # Y 홀드 + RB 토글
                time.sleep(0.5)
                g = self.mv.tm.grip()
                if g == want:
                    break
            self.log(f"   잡기: grip {self.mv.tm.grip()} (원함 {want})")
        r = D.duel(self.mv, self.w, ptr, nm, log=self.log, cancel=lambda: self.esc.escaping or self.esc.gen != g0,
                   care=Care(self), reflex=self.reflex, arena=arena, low_hp=0.0 if desperate else 0.25, style=self.style)
        self.log(f"   {tag}{' (끝까지)' if desperate else ''}: {r.line()}")
        self.events("duel", tag=tag, npc=r.npc, result=r.result, secs=round(r.secs, 1), dealt=r.dealt, taken=r.taken)
        if r.result == "killed":
            self.heal(0.7)
        return r

    def _asleep(self, ptr, hold: float = 0.4) -> bool:
        """서 있는 채(애니 -1) hold 동안 안 움직였나. 지도 스폰 좌표와 비교하지 않는다 — 적이 스폰에서 6 m 떨어져 서 있어
        '이미 깸' 으로 오판했다 (2026-09-24 3번)."""
        s0 = self.mv.snap(SEEK_R)
        c0 = self.mv.find(s0, ptr)
        if c0 is None or c0.anim not in (-1, None):
            return False
        time.sleep(hold)
        c1 = self.mv.find(self.mv.snap(SEEK_R), ptr)
        return c1 is not None and c1.anim in (-1, None) and math.dist((c0.x, c0.y, c0.z), (c1.x, c1.y, c1.z)) < 0.3

    def lure(self, ptr, spawn, nm, tag: str, arena=None) -> str:
        """한 놈만 깨운다 (사용자 2026-09-24: "가장 좋은 건 하나씩 불러와서 때려야 함", "투척 나이프 있으니 멀리서 하나씩").
        arena 가 그놈에서 LURE_R+3 안이면 거기서, 아니면 경로를 따라 LURE_R 까지만 다가가 나이프를 던진다.
        → 'lured' (움직였다) | 'awake' (이미 깨어 있어 안 던짐) | 'no_reaction' | 'no_knife' | 'no_path' | 'dead'"""
        s = self.mv.snap(SEEK_R)
        c = self.mv.find(s, ptr)
        if c is None:
            return "dead"
        if not self._asleep(ptr):
            return "awake"
        knives = self.mv.tm.goods_count(M.ITEM_KNIFE) or 0
        if not knives:
            return "no_knife"
        if knives <= KNIFE_LOW:
            self.log(f"   ⚠ 투척 나이프 {knives} 개 — 상인에게 사야 한다")
        here = (s.player.x, s.player.y, s.player.z)
        goal = (c.x, c.y, c.z)
        d_arena = math.dist(tuple(arena), goal) if arena is not None else None
        if d_arena is not None and LURE_MIN <= d_arena <= LURE_MAX:
            spot = tuple(arena)
        else:
            # 평지가 너무 가깝거나(1번: 5 m — 걸어가면 그냥 깬다) 멀면 경로 위에서 LURE_R 안에 드는 첫 점
            path = nm.find_path(here, goal)
            if not path:
                return "no_path"
            spot = next((tuple(q) for q in path if math.dist(tuple(q), goal) <= LURE_R and abs(q[1] - goal[1]) <= LURE_DY), None)
            if spot is None:
                return "no_spot"                              # 절벽 아래·위 놈은 던질 자리가 없다 — 평소 길로 (8판: 절벽 아래 2번에게 뛰어내림)
        if math.dist(here, spot) > 1.5:
            r = self.walk_to(spot, nm, f"{tag} 던질 자리로")
            if r == "dead":
                return "dead"
            if r != "arrived":
                self.log(f"   {tag}: 던질 자리까지 {r} — 지금 자리에서 던진다")
        c = self.mv.find(self.mv.snap(SEEK_R), ptr)
        if c is None:
            return "dead"
        if c.dist > LURE_MAX:
            # 락온 범위 밖 — 6번(22 m, 위 턱)에 나이프 3 개를 허공에 던졌다 (2026-09-24)
            self.log(f"   {tag}: 던질 자리에서 {c.dist:.1f} m — 너무 멀어 안 던진다")
            return "too_far"
        locked_once = False
        for n in range(1, LURE_TRIES + 1):
            s = self.mv.snap(SEEK_R)
            if self.mv.find(s, ptr) is None:
                return "dead"
            # 던지는 동안 다른 깨어 있는 놈이 다가오면 그만둔다 — 던지기 루프엔 방어가 없어 742 → 154 (2026-09-24 1번)
            near = [x for x in s.hostile(LURE_ABORT_R) if x.ptr != ptr and awake(x) and x.anim not in (-1, None)]
            if near:
                self.log(f"   {tag}: 다른 놈 {len(near)} 접근 ({near[0].dist:.1f} m) — 끌어오기 중단, 그놈부터")
                return "interrupted"
            if not self._asleep(ptr):
                return "lured" if n > 1 else "awake"
            if n > 1 and not locked_once:
                # 락온이 안 걸렸다 = 가려졌거나 멀다 (사용자: "벽이 가리는데 던져서 안 맞음") — 허공에 던지지 말고 길 따라 4 m 더
                c = self.mv.find(self.mv.snap(SEEK_R), ptr)
                if c is None:
                    return "dead"
                path = nm.find_path((s.player.x, s.player.y, s.player.z), (c.x, c.y, c.z)) if (s := self.mv.snap(5.0)) else None
                want = max(LURE_MIN, c.dist - 4.0)
                nxt = next((tuple(q) for q in (path or []) if math.dist(tuple(q), (c.x, c.y, c.z)) <= want and abs(q[1] - c.y) <= LURE_DY
                            and abs(q[1] - s.player.y) <= LURE_DY), None)
                if nxt is None:
                    return "no_spot"
                self.log(f"   {tag}: 락온 안 걸림 — {want:.0f} m 까지 다가감")
                if self.walk_to(nxt, nm, f"{tag} 더 가까이") == "dead":
                    return "dead"
                if not self._asleep(ptr):
                    return "lured"
            r = self.mv.throw_knife(ptr, require_lock=True)
            locked_once = locked_once or bool(r.get("locked"))
            s2 = self.mv.snap(25.0)
            others = [x for x in (s2.hostile(25.0) if s2 else []) if x.ptr != ptr and awake(x) and x.anim not in (-1, None)]
            self.log(f"   {tag}: 나이프 {n} ({r.get('dist')} m, 락온 {r.get('locked')}, 조준 {r.get('aim_off')}°) → "
                     f"피해 {r.get('hit')}, {'움직임' if r.get('woke') else '반응 없음'}{' | ' + r['why'] if r.get('why') else ''}"
                     f"{' | 다른 놈 깸 ' + str(len(others)) if others else ''}")
            self.events("lure", tag=tag, n=n, **{k: r.get(k) for k in ("dist", "locked", "aim_off", "hit", "woke", "knives")})
            if r.get("woke"):
                return "lured"
            if not r.get("ok"):
                time.sleep(0.5)
        return "no_reaction"

    def find_at(self, npc: int, pos, r: float = 3.0, dy_max: float = 3.0):
        """스폰 pos 근처의 그 종류. 넓게(30 m) 찾을 때도 **높이차 dy_max 안**만 — 경사로 아래에서 위 턱의 6번을 1번으로 잡아
        15 m 절벽을 향해 걷다 17 s 씩 세 번 막혔다 (2026-09-24 밤 3판, 5 분 낭비)."""
        s = self.mv.snap(200.0)
        if s is None:
            return None
        cands = [c for c in s.chars if c.npc_param == npc and c.hp > 0 and math.dist((c.x, c.y, c.z), tuple(pos)) < r
                 and abs(c.y - pos[1]) <= dy_max]
        return min(cands, key=lambda c: math.dist((c.x, c.y, c.z), tuple(pos)), default=None)

    def clear(self, targets: list[dict], nm, tries: int = 3, arena=None, lure: bool = False) -> str:
        """교전 큐 (2026-09-25 층 설계 2단계): **깨어서 오는 놈이 있으면 가까운 순으로 먼저**, 없을 때만 스폰 목록의 다음 놈을
        끌어오거나 찾아간다. 실제 처치 대부분이 '가는 길에 쫓아온 놈' 이었는데 예전 코드는 그걸 walk 안의 예외로 다뤘다.
        targets = [{"npc":…, "pos":[x,y,z], "label":n, "lure":bool}, …] 는 '다음에 깨울 놈' 의도.
        → 'cleared' | 'left #2 #4' (세 번 해도 못 잡은 놈) | 'died' | 'no_estus'"""
        pending = list(targets)
        left: list[str] = []
        tried: dict = {}                                   # 스폰 번호 / ptr → 시도 수
        ignore: set = set()                                # 세 번 못 잡은 오는 놈 (퀵 종료 감시에 맡긴다)
        desperate = False
        while pending:
            if not self.alive():
                return "died"
            self.wait_escape()
            s = self.mv.snap(SEEK_R)
            if s is None:
                time.sleep(0.1)
                continue
            coming = [c for c in s.hostile(FOLLOW_R + 2.0) if awake(c) and c.ptr not in ignore and c.anim not in (None, -1)
                      and M.horiz(s.player, c) < FOLLOW_R + 2.0 and abs(c.y - s.player.y) < FOLLOW_DY]
            if coming:
                c = min(coming, key=lambda x: M.horiz(s.player, x))
                tried[c.ptr] = tried.get(c.ptr, 0) + 1
                r = self.fight(c.ptr, nm, f"오는 놈 {c.npc_param}" + (f" ({tried[c.ptr]}번째)" if tried[c.ptr] > 1 else ""),
                               arena=arena, desperate=desperate)
                if r.result == "me_dead":
                    return "died"
                if r.result != "killed":
                    ok = self.recover(f"오는 놈 {r.result}", nm)
                    if not ok and self.mv.estus_left() <= 0:
                        return "no_estus"
                    desperate = not ok
                    if tried[c.ptr] >= tries or r.result in ("stuck", "lost"):
                        ignore.add(c.ptr)
                else:
                    desperate = False
                continue
            e = pending[0]
            i = e.get("label", 0)
            c = (self.find_at(e["npc"], e["pos"], 3.0) or self.find_at(e["npc"], e["pos"], 12.0)
                 or self.find_at(e["npc"], e["pos"], 30.0))
            if c is None:
                self.log(f"   #{i} {e['npc']}: 스폰 30 m 안에 없음 — 이미 죽음")
                pending.pop(0)
                continue
            k = tried.get(i, 0)
            if lure and k == 0 and e.get("lure", True):
                lr = self.lure(c.ptr, e["pos"], nm, f"#{i}", arena=arena)
                self.log(f"   #{i} 끌어오기: {lr}")
                tried[i] = 1
                if lr == "dead":
                    pending.pop(0)
                continue                                   # 깨어 오면 위의 '오는 놈' 이 받는다; 안 오면 다음 바퀴에 찾아간다
            tried[i] = k + 1
            r = self.fight(c.ptr, nm, f"#{i} {e['npc']}" + (f" ({tried[i]}번째)" if tried[i] > 1 else ""), arena=arena, desperate=desperate)
            if r.result == "killed":
                pending.pop(0)
                desperate = False
                continue
            if r.result == "me_dead":
                return "died"
            self.wait_escape()
            if not self.alive():
                return "died"
            ok = self.recover(f"#{i} {r.result}", nm)
            if not ok and self.mv.estus_left() <= 0:
                return "no_estus"
            desperate = not ok                             # 물러나지도 마시지도 못했으면 다음엔 끝까지
            if tried[i] >= tries + 1:
                left.append(f"#{i}")
                pending.pop(0)
        return "cleared" if not left else "left " + " ".join(left)

    def _clear_old(self, targets: list[dict], nm, tries: int = 3, arena=None, lure: bool = False) -> str:
        """(예전) 스폰 지도 순서대로 하나씩. targets = [{"npc":…, "pos":[x,y,z]}, …].
        → 'cleared' | 'left #2 #4' (세 번 해도 못 잡은 놈) | 'died' | 'no_estus'
        없는 놈은 건너뛴다 (이미 죽었다 — 퀵 종료로는 안 살아난다)."""
        left = []
        for n, e in enumerate(targets, 1):
            i = e.get("label", n)                          # 지도 번호 (순서를 바꿔도 기록은 지도 번호로)
            killed, desperate = False, False
            for k in range(tries):
                if not self.alive():
                    return "died"
                # 쫓아오느라 스폰에서 멀어진 놈도 있다 — 12 m 만 봤더니 살아 있는 4번을 '이미 죽음' 으로 건너뛰고 등을 맞았다
                c = (self.find_at(e["npc"], e["pos"], 3.0) or self.find_at(e["npc"], e["pos"], 12.0)
                     or self.find_at(e["npc"], e["pos"], 30.0))
                if c is None:
                    self.log(f"   #{i} {e['npc']}: 스폰 30 m 안에 없음 — 이미 죽음")
                    killed = True
                    break
                self.wait_escape()
                if lure and k == 0 and e.get("lure", True):
                    lr = self.lure(c.ptr, e["pos"], nm, f"#{i}", arena=arena)
                    self.log(f"   #{i} 끌어오기: {lr}")
                    if lr == "dead":
                        killed = True
                        break
                    if lr == "interrupted":
                        s_ = self.mv.snap(SEEK_R)
                        near = [x for x in s_.hostile(LURE_ABORT_R) if x.ptr != c.ptr and awake(x) and x.anim not in (-1, None)] if s_ else []
                        if near:
                            r0 = self.fight(near[0].ptr, nm, f"#{i} 끼어든 {near[0].npc_param}", arena=arena)
                            if r0.result == "me_dead":
                                return "died"
                            c = self.find_at(e["npc"], e["pos"], 30.0) or c
                r = self.fight(c.ptr, nm, f"#{i} {e['npc']}" + (f" ({k + 1}번째)" if k else ""), arena=arena, desperate=desperate)
                if r.result == "killed":
                    killed = True
                    break
                if r.result == "me_dead":
                    return "died"
                self.wait_escape()
                if not self.alive():
                    return "died"
                ok = self.recover(f"#{i} {r.result}", nm)
                if not ok and self.mv.estus_left() <= 0:
                    return "no_estus"
                # 물러나지도 마시지도 못했다 — 다음엔 HP 가 낮아도 빠지지 않고 끝까지 (0.1 s 마다 '낮음→못 물러남→못 마심' 을 되풀이하며
                # 방패도 안 들고 서서 맞아 죽었다, 2026-09-24)
                desperate = not ok
            if not killed:
                left.append(f"#{i}")
        return "cleared" if not left else "left " + " ".join(left)

    # ── 길 ───────────────────────────────────────────────────
    def walk(self, path: list, nm, tag: str, tol: float | None = None, tight: dict | None = None, mode: str = "walk") -> str:
        """경로를 걷다가 쫓아와 붙는 놈은 먼저 잡는다. → 'arrived' | 'dead' | 'stuck' | 'no_estus'
        점마다 바닥 확인은 목표와 지금 자리 둘 다 이 내비메시 위일 때만 (경계·다리 위는 내비메시가 비어 있다).
        tight = {"center": [x,y,z], "r": m} 안(난간 없는 좁은 다리)은 0.45 m 로 좁게 밟는다."""
        path = [tuple(q) for q in path]
        # tol 이 없으면(내비메시 경로) 가파른 구간(계단·경사로)만 0.4 m 로 정확히 밟는다 (nav.path_tolerances) — 전부 1 m 로 밟았더니
        # 경사로 위 턱에서 계단 꼭대기로 못 올라가 '통로 막힘' (2026-09-24). 사람이 녹화한 길은 부르는 쪽이 tol(0.8)을 준다
        # — 녹화 점을 0.4 m 로 좁히면 계단 끝에서 0.6~0.7 m 넘게 못 다가가 막혔다 (hunt.walk_fight)
        tols = nav.path_tolerances(path, 1.0) if tol is None else [tol] * len(path)
        self.reflex.nm = nm
        mover = nav.Mover(self.mv.pad)
        i, fails, fights = 0, 0, 0
        ignore: set = set()
        desperate = False
        try:
            while i < len(path):
                if self.esc.escaping:
                    time.sleep(0.2)
                    continue
                q = path[i]
                t = tols[i]
                if tight and math.dist((q[0], q[2]), (tight["center"][0], tight["center"][2])) < tight["r"]:
                    t = 0.45
                s = self.mv.snap(40.0)
                if s is None:
                    time.sleep(0.1)
                    continue
                if s.player.hp < s.player.max_hp * WALK_HEAL and self.safe(s) and self.mv.estus_left() > 0:
                    mover.stop()                           # 걷다 맞은 피해(화염병 등) — 다음 싸움까지 미루지 않는다
                    self.heal(0.7)
                f_q = nm.floor_at(q[0], q[2], q[1]) if len(q) > 2 else None
                f_p = nm.floor_at(s.player.x, s.player.z, s.player.y)
                terr = nm if (f_q is not None and abs(f_q[0] - q[1]) < 2.0 and f_p is not None and abs(f_p[0] - s.player.y) < 2.0) else None

                def chaser(sn):
                    return next((c for c in sn.hostile(FOLLOW_R + 1.0) if awake(c) and c.ptr not in ignore
                                 and M.horiz(sn.player, c) < FOLLOW_R and abs(c.y - sn.player.y) < FOLLOW_DY
                                 and (c.anim not in (None, -1) or c.dist < 2.0)), None)
                g0 = self.esc.gen
                r = nav.goto(self.mv.tm, self.mv.pad, q, tolerance=t if terr is not None else max(t, 0.8), timeout=15,
                             log=lambda *a: None, terrain=terr, mover=mover,
                             mode_fn=lambda sn: "retreat" if (self.reflex.threat_now(sn) or chaser(sn) or self.esc.escaping
                                                              or self.esc.gen != g0) else mode)
                if r == "dead":
                    return "dead"
                if self.esc.gen != g0:                     # 퀵 종료로 나갔다 왔다 — 가장 가까운 점부터 다시
                    s2 = self.mv.snap(5.0)
                    if s2:
                        i = min(range(len(path)), key=lambda j: math.dist(path[j], (s2.player.x, s2.player.y, s2.player.z)))
                    continue
                if r == "retreat":
                    mover.stop()
                    self.reflex.hold()                     # 걷다 공격이 오면 먼저 정면으로 막고
                    s2 = self.mv.snap(40.0)
                    c = chaser(s2) if s2 else None
                    if c is not None and fights >= 15:
                        ignore.add(c.ptr)                  # 한 길에서 너무 많이 싸웠다 — 이놈은 퀵 종료 감시에 맡긴다
                    elif c is not None:
                        fights += 1
                        mover.stop()
                        res = self.fight(c.ptr, nm, f"{tag}: 따라온 {c.npc_param}", desperate=desperate)
                        if res.result == "me_dead":
                            return "dead"
                        desperate = False
                        if res.result != "killed":
                            ok = self.recover(f"{tag} {res.result}", nm)
                            if not ok and self.mv.estus_left() <= 0:
                                return "no_estus"
                            desperate = not ok
                            if res.result in ("stuck", "lost"):
                                ignore.add(c.ptr)          # 못 닿는 놈 — 이 길에선 무시 (쫓아오면 퀵 종료가 떼어낸다)
                    continue
                if r != "arrived":
                    fails += 1
                    if fails >= 2 and self.fog_through(q):
                        fails = 0                          # 안개벽을 지났다 — 가장 가까운 점부터 다시
                        s2 = self.mv.snap(5.0)
                        if s2:
                            i = min(range(len(path)), key=lambda j: math.dist(path[j], (s2.player.x, s2.player.y, s2.player.z)))
                        continue
                    if fails >= 3:
                        return "stuck"
                else:
                    fails = 0
                i += 1
            return "arrived"
        finally:
            mover.stop()

    def fog_through(self, toward) -> bool:
        """안개벽 앞에서 막혔으면: 다음 경로점 쪽으로 몸을 돌리고, 안내창이 뜨면 A (사용자: "안개벽 A 눌러", "방향 정렬").
        안개 옆에 서서 벽을 보고 밀기만 해 '막힘' 이었다 (2026-09-24). 안내창은 몸이 안개를 봐야 뜬다.
        → 지나갔나 (2 m 넘게 움직임)"""
        import legacy.ladder_test as L                    # 안내창 판별(화면 아래 가운데 어두운 비율, 뜨면 ~900)
        s = self.mv.snap(5.0)
        if s is None or s.cam_yaw is None:
            return False
        p0 = (s.player.x, s.player.y, s.player.z)
        for scale in (0.5, 0.7):
            self.mv.pad.move(*self.mv.stick_to(s, toward[0], toward[2], scale))
            time.sleep(0.3)
            self.mv.pad.move(0.0, 0.0)
            time.sleep(0.4)
            if L.prompt_px() >= 850:
                self.mv.press(M.B.XUSB_GAMEPAD_A, 0.3)
                time.sleep(4.5)
                s2 = self.mv.snap(5.0)
                moved = math.dist(p0, (s2.player.x, s2.player.y, s2.player.z)) if s2 else 0.0
                self.log(f"   안개벽: A → {moved:.1f} m 이동")
                return moved > 2.0
            s = self.mv.snap(5.0) or s
        return False

    def walk_to(self, goal, nm, tag: str, mode: str = "walk") -> str:
        s = self.mv.snap(5.0)
        if s is None:
            return "no_snapshot"
        path = nm.find_path((s.player.x, s.player.y, s.player.z), tuple(goal))
        if not path:
            return "no_path"                               # 경로가 없으면 직선으로 걷지 않는다 (낭떠러지)
        return self.walk(nav.trim_path(path[1:], tuple(goal)), nm, tag, mode=mode)

    # ── 핏자국 ────────────────────────────────────────────────
    def pick_blood(self, nm, near: float = 20.0, bonfire_ok: bool = False) -> str | None:
        """bonfire_ok: 어차피 이 화톳불에 앉을 거라 A 가 앉기로 잘못 들어가도 괜찮을 때 (성벽 마을 화톳불 옆 핏자국)."""
        b = Blood.read()
        if not b:
            return None
        pos = tuple(b["pos"])
        if not bonfire_ok and any(math.dist(pos, bf) < BONFIRE_NO_A for bf in self.bonfires):
            self.log(f"   핏자국 {pos} 이 화톳불 옆 — A 를 누르면 앉아 버려(적 전부 부활) 안 줍는다. 기록은 남긴다")
            return "near_bonfire"
        s = self.mv.snap(5.0)
        if s is None or math.dist((s.player.x, s.player.y, s.player.z), pos) > near:
            return None
        r = self.walk_to(pos, nm, "핏자국")
        if r != "arrived":
            return r
        souls0 = self.mv.tm.souls() or 0
        self.mv.press(M.B.XUSB_GAMEPAD_A)
        time.sleep(1.5)
        got = (self.mv.tm.souls() or 0) > souls0
        self.log(f"   핏자국: {'회수' if got else '못 주움'} (소울 {souls0} → {self.mv.tm.souls()})")
        return "got" if got else "miss"

    # ── 쉬기 ─────────────────────────────────────────────────
    def rest_at(self, nm, bonfire: dict) -> bool:
        """화톳불까지 싸우며 걸어가서 쉰다. **적이 전부 살아난다** — 판을 새로 시작할 때만."""
        if not self.alive() and not self.wait_respawn():
            return False
        s = self.mv.snap(5.0)
        stand = tuple(bonfire["stand"])
        if s and math.dist((s.player.x, s.player.y, s.player.z), stand) > 5.0:
            r = self.walk_to(stand, nm, "화톳불로")
            self.log(f"   화톳불로: {r}")
            if r == "dead":
                self.wait_respawn()
        return self.mv.rest(nm, bonfire)


class Care:
    """싸우는 중 회복 (duel 의 care). 마실지는 여기(4층), 틈인지는 duel.opening(3층).
    에스트 개수는 매 틱 읽으면 무겁다(32 KB) — 마실 때만 다시 센다."""

    def __init__(self, f: Field):
        self.f = f
        self.left = f.mv.estus_left()

    def wants(self, s) -> bool:
        return self.left > 0 and s.player.hp < s.player.max_hp * FIGHT_HEAL

    def take(self, recheck) -> dict:
        r = self.f.mv.drink(recheck)
        self.left = r.get("left", self.f.mv.estus_left())
        self.f.events("estus", fight=True, **r)
        return r
