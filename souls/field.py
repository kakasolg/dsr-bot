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
from . import moves as M
from .reflex import Reflex
from .watch import Blood

FOLLOW_R = 4.5           # 길을 걷다 이 안(수평)에 깨어 있는 놈이 붙으면 싸운다
FOLLOW_DY = 2.5          # 계단에서 따라오는 놈 — 높이차 이만큼까지
SAFE_R = 6.0             # 에스트: 이 안에 깨어 있는 적이 없고
SAFE_ATTACK_R = 8.0      #          이 안에 휘두르는 놈이 없을 때
BONFIRE_NO_A = 6.0
FIGHT_HEAL = 0.5         # 싸우는 중: HP 가 이 아래면 틈(duel.opening)에 마신다
WALK_HEAL = 0.6          # 걷는 중: 이 아래고 안전하면 70 % 까지


def awake(c) -> bool:
    return c.hp > 0 and not (9000 <= (c.anim or 0) < 9100)


class Field:
    def __init__(self, mv: M.Moves, weapon, escape, bonfires: list, log=print, events=None):
        self.mv, self.w, self.esc, self.log = mv, weapon, escape, log
        self.bonfires = [tuple(b) for b in bonfires]      # 핏자국 줍기(A) 금지 구역
        self.events = events or (lambda *a, **k: None)
        self.reflex = Reflex(mv)                           # 반사 — 싸우든 걷든 매 틱 먼저 (발밑 확인용 내비메시는 쓸 때 넣는다)

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
        return not any(awake(c) and (c.dist < SAFE_R or ((c.anim or -1) in M.ATTACK and c.dist < SAFE_ATTACK_R))
                       for c in s.hostile(SAFE_ATTACK_R))

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

    def shake_off(self, why: str) -> dict:
        """퀵 종료로 적을 스폰으로 돌려보낸다 (경계 풀림, 죽은 적은 그대로)."""
        return self.esc.fire(why, "shake")

    def recover(self, why: str) -> bool:
        """싸움이 틀어졌을 때: 적이 가까우면 떼어내고, 에스트로 90 % 까지. → 계속 싸울 만한가"""
        s = self.mv.snap(15.0)
        if s and not self.safe(s):
            self.shake_off(why)
        self.heal(0.9, sips=4)
        s = self.mv.snap(5.0)
        return bool(s and s.player.hp >= s.player.max_hp * 0.6)

    # ── 싸움 ─────────────────────────────────────────────────
    def fight(self, ptr, nm, tag: str) -> D.DuelResult:
        g0 = self.esc.gen
        e = self.mv.estus_id()
        if e is not None and self.mv.tm.selected_item() != e:
            self.mv.select_item(e)                         # 미리 골라 둔다 — 틈이 났을 때 칸 돌리는 1~3 s 가 없게
        self.reflex.nm = nm
        r = D.duel(self.mv, self.w, ptr, nm, log=self.log, cancel=lambda: self.esc.escaping or self.esc.gen != g0,
                   care=Care(self), reflex=self.reflex)
        self.log(f"   {tag}: {r.line()}")
        self.events("duel", tag=tag, npc=r.npc, result=r.result, secs=round(r.secs, 1), dealt=r.dealt, taken=r.taken)
        if r.result == "killed":
            self.heal(0.7)
        return r

    def find_at(self, npc: int, pos, r: float = 3.0):
        s = self.mv.snap(200.0)
        if s is None:
            return None
        cands = [c for c in s.chars if c.npc_param == npc and c.hp > 0 and math.dist((c.x, c.y, c.z), tuple(pos)) < r]
        return min(cands, key=lambda c: math.dist((c.x, c.y, c.z), tuple(pos)), default=None)

    def clear(self, targets: list[dict], nm, tries: int = 3) -> str:
        """스폰 지도 순서대로 하나씩. targets = [{"npc":…, "pos":[x,y,z]}, …]. → 'cleared' | 'died' | 'no_estus'
        없는 놈은 건너뛴다 (이미 죽었다 — 퀵 종료로는 안 살아난다)."""
        for i, e in enumerate(targets, 1):
            for k in range(tries):
                if not self.alive():
                    return "died"
                c = self.find_at(e["npc"], e["pos"], 3.0) or self.find_at(e["npc"], e["pos"], 12.0)
                if c is None:
                    self.log(f"   #{i} {e['npc']}: 스폰 근처에 없음 — 이미 죽음")
                    break
                r = self.fight(c.ptr, nm, f"#{i} {e['npc']}" + (f" ({k + 1}번째)" if k else ""))
                if r.result == "killed":
                    break
                if r.result == "me_dead":
                    return "died"
                if not self.recover(f"#{i} {r.result}") and self.mv.estus_left() <= 0:
                    return "no_estus"
        return "cleared"

    # ── 길 ───────────────────────────────────────────────────
    def walk(self, path: list, nm, tag: str, tol: float = 1.0, tight: dict | None = None, mode: str = "walk") -> str:
        """경로를 걷다가 쫓아와 붙는 놈은 먼저 잡는다. → 'arrived' | 'dead' | 'stuck' | 'no_estus'
        점마다 바닥 확인은 목표와 지금 자리 둘 다 이 내비메시 위일 때만 (경계·다리 위는 내비메시가 비어 있다).
        tight = {"center": [x,y,z], "r": m} 안(난간 없는 좁은 다리)은 0.45 m 로 좁게 밟는다."""
        path = [tuple(q) for q in path]
        self.reflex.nm = nm
        mover = nav.Mover(self.mv.pad)
        i, fails, fights = 0, 0, 0
        ignore: set = set()
        try:
            while i < len(path):
                if self.esc.escaping:
                    time.sleep(0.2)
                    continue
                q = path[i]
                t = tol
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
                        res = self.fight(c.ptr, nm, f"{tag}: 따라온 {c.npc_param}")
                        if res.result == "me_dead":
                            return "dead"
                        if res.result != "killed":
                            if not self.recover(f"{tag} {res.result}") and self.mv.estus_left() <= 0:
                                return "no_estus"
                            if res.result in ("stuck", "lost"):
                                ignore.add(c.ptr)          # 못 닿는 놈 — 이 길에선 무시 (쫓아오면 퀵 종료가 떼어낸다)
                    continue
                if r != "arrived":
                    fails += 1
                    if fails >= 3:
                        return "stuck"
                else:
                    fails = 0
                i += 1
            return "arrived"
        finally:
            mover.stop()

    def walk_to(self, goal, nm, tag: str, mode: str = "walk") -> str:
        s = self.mv.snap(5.0)
        if s is None:
            return "no_snapshot"
        path = nm.find_path((s.player.x, s.player.y, s.player.z), tuple(goal))
        if not path:
            return "no_path"                               # 경로가 없으면 직선으로 걷지 않는다 (낭떠러지)
        return self.walk(nav.trim_path(path[1:], tuple(goal)), nm, tag, mode=mode)

    # ── 핏자국 ────────────────────────────────────────────────
    def pick_blood(self, nm, near: float = 20.0) -> str | None:
        b = Blood.read()
        if not b:
            return None
        pos = tuple(b["pos"])
        if any(math.dist(pos, bf) < BONFIRE_NO_A for bf in self.bonfires):
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
