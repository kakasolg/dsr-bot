"""Picking up enemy drops as a common step of the mission flow — one Loot per Field (Field.loot), one DropBook per run.

  Loot.reset(why)              new baseline now (run start · rest · respawn · warp · quit-out)
  Loot.collect(nm, tag, back)  at a mission's stop point, after its own fights: pick up what the book knows of

The missions call collect() where their fighting is over and the next step starts with its own walk (souls/missions.py
Missions._loot). Inside, a foe that comes at us is fought with Field.fight like walk()'s chaser; anything else near a drop
puts that drop off (DropBook.held) and the mission goes on.

── 지원 대상 (2026-11-01) ──────────────────────────────
 · 지원: 적이 죽은 뒤 생긴 드롭 기록 (drops.py). 본편 확인은 clear-ramp 단일 드롭 4회뿐 — 다른 연결 지점은 오프라인 검사만.
 · 이름으로 정한 고정 보물 하나(TREASURES, 11-01 불의 제전 인간성 ×3)만 Field.pick_treasure로 — 오프라인 검사만.
 · 미지원: 그 밖의 경로 주변 고정 보물(시체 위 보물)·보물 상자. 보상 추출에 연쇄 lot 누락(msb_extract)이 남아 있고, 상자 여는 입력·
   획득 확인을 봇 흐름에서 해 본 적이 없다. 그래서 여기서 찾지도, 표시하지도 않는다 (SUPPORTED).
 · 일반 수집에서 빼는 것: NPC 근처(A가 말 걸기), 화톳불 옆(A가 앉기 = 적 부활 — Field.pick_drops가 거름), 미믹·숨은 보물·
   잠긴 문·이벤트 전제가 있는 대상(고정 보물 미지원이라 지금은 해당 없음).

── 알려진 한계 ──────────────────────────────
 · 기준(baseline)은 "기준을 잡을 때 메모리에 있던 기록 전부"를 뺀다. 실행 하나에 책 하나라 같은 실행 안의 재시도
   (pass_ramp 재시도 등)는 첫 회에 못 주운 드롭을 그대로 다시 본다. 단 퀵 종료(esc.gen 바뀜)·휴식·부활·워프 뒤에는
   기준을 새로 잡으므로 그 앞에 생겨 못 주운 드롭은 빠진다 — 재로딩 뒤 드롭이 땅에 남는지는 확인 안 함.
 · 기준을 잡은 뒤 생긴 기록은 모두 후보다. 옛 기록을 새 드롭으로 볼 위험은 같은 주소 재사용뿐이고, 그건 DropBook이
   (주소·아이템·개수·주인)으로 가르고, 기준과 같은 바이트면 한 번만 가 본다(REUSED_TRIES).
 · collect()마다 메모리 스캔 ~1.5 s (처치가 없어도 함).
"""
from __future__ import annotations

import math
import time

import drops as drops_

SUPPORTED = {"drops": "enemy drops after death (drops.DropBook)",
             "treasure:named": "only the corpses in TREASURES, by name (Field.pick_treasure) — no scan, no general fixed-treasure pickup"}
# 이름으로 정한 고정 보물만 — [MoKa] 11-01 "humanity 아이템 확보 하는 것도 점검". 판정은 ItemFlag(event_flag)와 개수 차이.
# 宝死体00: 11-01 humanity_probe가 같은 세이브에서 A 1회로 flag False→True · 개수 1→4를 봄 (1회, 봇 흐름 밖 실험 코드)
TREASURES = {
    "firelink-humanity": {"name": "宝死体00", "label": "Humanity ×3", "pos": (-39.37, -58.16, 53.44), "flag": 51020000,
                          "item": 500, "count": 3},
}
NOT_SUPPORTED = {
    "treasure": "fixed treasure in general (scan / route-side) — msb_extract chained-lot gap; only TREASURES by name",
    "chest": "treasure chests — open input and item check never done in the bot flow",
}
LOOT_FIGHTS = 2          # foes fought inside one collect() (one that comes at us while picking up); more → put off
NPC_R = 3.0              # m — a drop this close to a living non-hostile character is put off (A would talk)


class Loot:
    def __init__(self, f, scan=None, window=None):
        self.f = f
        self.on = False                                   # run.py turns it on (--no-loot keeps it off)
        self.book = drops_.DropBook()
        self.busy = False                                 # collect() never runs inside collect()
        self.gen = None                                   # esc.gen at the last baseline — a quit-out changes it
        self.scan = scan or (lambda: drops_.scan(self.f.mv.tm))
        self.window = window or (lambda: drops_.itemget_nodes(self.f.mv.tm))
        self.last: dict | None = None

    def reset(self, why: str) -> None:
        """Forget every drop and take a new baseline right now — before the kills that follow (a later baseline would swallow
        their drops). Owner HP too, so those kills count as deaths."""
        if not self.on:
            return
        self.book.reset(why)
        self.gen = getattr(getattr(self.f, "esc", None), "gen", None)
        s = self.f.mv.snap(60.0)
        if s is not None:
            self.book.observe_chars(s.chars, time.time())
        self.book.observe(self.scan(), time.time())
        self.f.log(f"   드롭 기준 ({why}): {self.book.log[-1]}")

    def collect(self, nm, tag: str, back=None) -> dict:
        """Pick up what the book knows of near here. back: walk there afterwards (only where the caller's next step needs that
        spot; otherwise the next step's own walk finds its way from here). → {'result', 'visits', 'taken', 'fights', 'held'}
        result: off · busy · dead · reset (quit-out since the baseline — new baseline, nothing picked) · done · visit_cap ·
        held (a foe near a drop that we don't fight here) · no_snapshot"""
        out = {"result": "off", "visits": 0, "taken": 0, "fights": 0, "held": 0}
        if not self.on:
            return out
        if self.busy:
            out["result"] = "busy"
            return out
        self.busy = True
        try:
            self._collect(nm, tag, back, out)
        finally:
            self.busy = False
            self.f.mv.pad.move(0.0, 0.0)
        self.last = out
        return out

    def _collect(self, nm, tag: str, back, out: dict) -> None:
        f = self.f
        if not f.alive():
            out["result"] = "dead"
            return
        gen = getattr(getattr(f, "esc", None), "gen", None)
        if gen != self.gen:
            self.reset("quit-out (esc.gen)")
            out["result"] = "reset"
            return
        scan = self._scan_without_npcs()
        while True:
            r = f.pick_drops(nm, self.book, scan=scan, window=self.window)
            out["visits"] += r["visits"]
            out["taken"] += r["taken"]
            out["result"] = r["result"]
            if r["result"] != "foes_near":
                break
            s = f.mv.snap(60.0)
            c = f._chaser(s, set()) if s is not None else None
            if c is None or out["fights"] >= LOOT_FIGHTS:
                why = "foe near, not coming at us" if c is None else f"{LOOT_FIGHTS} fights already"
                gone = self.book.held(r.get("at", []), why)
                out["held"] += len(r.get("at", []))
                out["result"] = "held"
                f.log(f"   {tag} 드롭 보류: {why}" + (f" — 포기 {[f'{d.rec.item:#x}' for d in gone]}" if gone else ""))
                break
            from .field import COMING_LIMIT
            out["fights"] += 1
            res = f.fight(c.ptr, nm, f"{tag} 줍는 중 온 {c.npc_param}", wait_far=True, limit=COMING_LIMIT)
            if res.result == "me_dead" or not f.alive():
                out["result"] = "dead"
                return
            if res.result != "killed":
                gone = self.book.held(r.get("at", []), f"fight {res.result}")
                out["held"] += len(r.get("at", []))
                out["result"] = "held"
                f.log(f"   {tag} 드롭 보류: 싸움 {res.result}")
                break
        if back is not None and out["result"] in ("done", "visit_cap") and f.alive():
            w = f.walk_to(tuple(back), nm, "드롭 뒤 제자리로")
            f.log(f"   드롭 뒤 제자리로: {w}")

    def _scan_without_npcs(self):
        """self.scan minus records next to a living character that isn't hostile (merchant, Solaire …): A there talks.
        Such a record never becomes a candidate (one already in the book turns 'gone')."""
        s = self.f.mv.snap(60.0)
        if s is None or not hasattr(s, "hostile"):
            return self.scan
        foes = {c.ptr for c in s.hostile(1e9)}
        npcs = [(c.x, c.y, c.z) for c in s.chars if (c.hp or 0) > 0 and c.ptr not in foes]
        if not npcs:
            return self.scan
        return lambda: [r for r in self.scan() if not any(math.dist(r.pos, q) < NPC_R for q in npcs)]
