"""Sunlight Altar bonfire (1012961) → Andre's bonfire (1012964) — **scaffold only, cannot run yet**.

[MoKa] 11-03: "bounded altar-to-Andre mission scaffold and unexecuted test source files" — no route recording exists, nothing
here has run in the game, and it is not wired into run.py (run.py holds another session's uncommitted P-121 changes).
Review 11-03 corrections: no souls.moves import (buttons injected), walk results other than arrived/stuck hand off, deadline
passed into Field.walk as done=, "no progress + foe near" no longer called an unsupported encounter, bonfire A blocked by
default, NavMesh check fails closed, lock path checked, route lifecycle below.

  AltarToAndre(field, nm, data_dir, lock=bot_lock).run()
    → 'refused: …' | 'died' | 'handoff: …' | 'arrived_area: …' | 'rest_unconfirmed: …' | 'rested_seated: …' | 'rested'

Route data: data/routes/altar-to-andre.json — **does not exist**. Until a recording reviewed by MoKa and game-validated is saved
there with validation.traversal.status "validated", every run() is refused before any controller input. Accepted shape
(souls/route_fp parses route + the two spots once into an immutable Route — that object is what check() and the walks use;
route_problems adds the validation / provenance / link checks):
  {"schema": "altar-andre-route/1", "_source": "<recording, e.g. data/observe/<time>.jsonl>", "map": "m10_01_00_00",
   "validation": {"traversal": {"status": "validated", "by": "MoKa", "date": "YYYY-MM-DD", "evidence": "<what was checked>",
                                "route_sha256": "<route_fp fingerprint of the route + spots that were validated>"},
                  "rest":      {"status": "unvalidated" | "validated", …same fields}},
   "requires": [{"what": "<progression>", "flag": <event flag id>, "want": true}],
   "legs": [{"tag": "<name>", "mode": "walk" | "sprint", "points": [[x, y, z], …], "ignore_npcs": [<npc_param>, …]}]}

Validation is split in two stages, because bonfire A is blocked by default (INTERACT_ENABLED False) and a run can't end
'rested' until it is unblocked — one combined "validated after 'rested'" status could never be reached:
  traversal   the legs: altar stand → Andre bonfire area. Evidence = a run that ended 'arrived_area'. Required to start.
  rest        light / sit / last_bonfire 1012964 at Andre's bonfire. Evidence = a run that ended 'rested'. Not required to start
              (with A blocked the mission stops at 'arrived_area'); reported in check() facts only. Turning INTERACT_ENABLED on
              is a separate MoKa decision, not something this status does.
The old flat shape (validation.status) is refused, not read as traversal.

Route lifecycle per stage (documented only — nothing below the "validated" line is accepted by this module today, no bypass):
  structure     route_problems() — computed on load, never stored as a status
  provenance    _source (recording file) + its hash, recorded by / date             → status "recorded"
  reviewed      review {by: "MoKa", date, notes} — MoKa looked at the points       → status "reviewed"
  validated     validation.<stage> {status "validated", run_id, by, date, evidence} — written only after a validation run
                ended with that stage's result ('arrived_area' / 'rested') and MoKa confirmed it in chat
  authorization to run a validation run is NOT a field in the file: it is MoKa's per-session approval in chat. A future
  caller argument (e.g. validation_run="<MoKa's approval quote>") could let exactly one run accept a "reviewed" traversal and
  record its run_id; it is not implemented, and without it the default stays refusal — so the first traversal validation
  still cannot happen through this module (알려진 한계).

Start and end spots come from data/spots.json (missions.SPOTS):
  start "parish-bonfire" 1012961, stand (24.77, 9.5, −22.87), sitting_verified — the Sunlight Altar bonfire: altar route's
        altar_bonfire (22.4, 9.4, −25.5) and burg-to-altar.md's (22.0, 9.5, −25.0) are 3.5 m from it (same id in bonfires.SEED).
  end   "andre-bonfire" 1012964, stand (88.46, 14.97, 106.96), heading 2.34, sitting_verified, no "object" (bonfire position).

Reused, not changed: Field.walk / Field.walk_to (path following; a foe closing within field.FOLLOW_R is fought by the existing
fight → duel RULES — this module adds no combat rule), Field.alive, Field.safe, Pad.neutral/sprint/guard, boss_ready.Verdict,
the light_burg_bonfire pattern (A until seated, success = seated and last_bonfire changed, B only while seated);
seated is read with tm.sitting_state() (True / False / None), not sitting().
Not reused: farm.rest — it falls back to tm.safe_warp (a memory write) and runs the kindle / level-up hooks.

/**
 * ── 알려진 한계 · 막힌 연결 ──────────────────────────────
 *  · 현재 맵을 읽는 텔레메트리가 없다 (dsr_telemetry 스냅숏 map_id는 늘 0, 맵 읽기 함수 없음). 위치 좌표만으로는 맵을
 *    가를 수 없다 → tm.current_map()이 생기기 전까지 시작 검사가 늘 "현재 맵 확인 불가"로 멈춘다. 오프셋을 추측해 넣지 않는다.
 *  · 경로 녹화가 없다. 좌표·적 배치를 지어내지 않는다. 시작 검사가 경로 없음으로 먼저 멈춘다.
 *  · 검증을 이동·쉼 두 단계로 나눴지만, 첫 이동 검증 주행을 허가하는 길(validation_run 인자)은 아직 없다.
 *    시작에는 이동 검증이 필요하고, 이동 검증에는 주행이 필요하다 → 이 모듈만으로는 아직 첫 검증을 못 한다.
 *  · 600 s 제한은 끝까지 지켜지지 않는다: walk/walk_to에 done=(마감)을 넘기지만 Field는 이동 틱에서만 done을 본다.
 *    싸움(1회 45 s·한 경로 15번), 탈출 대기(field.py _walk esc.escaping), 스냅숏 없음 반복 안에서는 마감이 닿지 않는다.
 *    완전한 마감은 Field 수정이 필요하다 (이 작업 범위 밖).
 *  · 진행 판정은 구간 끝까지의 수평 직선 거리다 — 처음엔 멀어지는 우회·높이만 바뀌는 계단·싸움 뒤 밀려남을 "진행 없음"으로 본다.
 *  · 진행 없음 + 근처 깨어 있는 적 = 관찰일 뿐이다. 그 적이 막은 원인인지, 갈 수 있는 적인지, 걷기 안에서 이미 싸웠는지 모른다
 *    → "원인 미확정"으로 넘기고 적 목록을 이벤트에 남긴다.
 *  · 화톳불 A는 기본으로 막는다 (INTERACT_ENABLED False). 상호작용은 정면을 봐야 하는데 (dsr_telemetry face 설명, 실측)
 *    안드레 화톳불 "object"가 spots에 없고 heading 2.34가 화톳불 쪽인지 확인 안 됐다. A가 다른 대상에 걸릴 수도 있다 (확인 안 됨).
 *    앉음은 sitting_state()로 읽는다 (None = 못 읽음). sitting()은 못 읽으면 False라 쓰지 않는다. 읽기 함수가 없거나
 *    None이면 시작을 거부하고, 쉼 단계에선 앉음으로 치지 않는다. menu_open()은 START 메뉴에서만 실측.
 *  · 쉼 확인 = sitting_state() True + last_bonfire가 1012964로 바뀜. 둘 중 하나라도 못 보면 성공이라 하지 않는다 (가까움·A 누름은 증거 아님).
 *  · 잠금: BotLock은 OS 파일 잠금이지만 파일이 체크아웃마다 따로다 (<체크아웃>/data/bot.lock, pad.lock도 같음).
 *    다른 worktree 세션·실물 패드·키보드·다른 Claude 세션의 화면 조작·radar 워프(메모리 쓰기)는 막지 못한다 → 게임 단독 소유 아님.
 *    ACTIVE는 이 모듈만 쓰는 목록 — 다른 AltarToAndre만 막는다. 사람·세션 사이 조율은 보드와 MoKa 확인으로만.
 *  · 손 넘김(handoff) 때 이 모듈은 안전한 자리로 되돌아가지 않는다 — 어디서나 안전한 복구 동작은 없다.
 *    입력만 놓고 결과를 돌려준다. 그 뒤는 사람(MoKa)이 맡는다. 봇 잠금 풀기는 부른 쪽(run.py 규칙) 일.
 */
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

import botlock
from . import route_fp
from boss_ready import Verdict

ROUTE = "altar-to-andre.json"
MAP = "m10_01_00_00"
START_SPOT, END_SPOT = "parish-bonfire", "andre-bonfire"
START_BONFIRE, END_BONFIRE = 1012961, 1012964
# 아래 수치는 전부 미측정 기본값 — 실측으로 정한 안전 한계가 아니다
START_R = 6.0            # start region around the start stand (the altar route's bonfire point is 3.5 m from it)
SPOT_DY = 2.5            # same level (field.FOLLOW_DY)
LINK_R = 3.0             # route's first point / last point must be this close to the start / end stand
LEG_DONE_R = 1.5         # leg end reached
END_R = 2.0              # bonfire area reached
PROGRESS_M = 1.0         # a walk attempt that got the leg end less than this much closer (straight line) = no progress
RECOVERY_BUDGET = 4      # re-walks (Field.walk_to toward the leg end) for the whole mission, then hand off
MISSION_MAX_S = 600.0    # whole mission; checked between walks and passed into them as done= (see 알려진 한계)
FOE_NEAR_R = 8.0         # foes listed in the hand-off evidence when a walk made no progress
INTERACT_MAX = 3         # A presses at the bonfire (light + sit, one spare — light_burg_bonfire)
SIT_WAIT_S = 6.0
STAND_TRIES = 6
MODES = ("walk", "sprint")
STAGES = ("traversal", "rest")   # validation stages; only traversal is required to start
WALK_OK = ("arrived", "stuck")   # Field.walk / walk_to results that go on to the distance check; anything else hands off
INTERACT_ENABLED = False # bonfire A stays blocked until MoKa verifies the interaction target and facing at Andre's bonfire

ACTIVE: list[str] = []   # AltarToAndre running in this process (this module only — not other missions)


def route_problems(R, route) -> list[str]:
    """Why this route data can't be used ([] = usable). R = the raw route dict (validation / _source, never executed),
    route = the parsed route_fp.Route (None when parsing refused it — those problems come from load_route)."""
    out = []
    v = R.get("validation") if isinstance(R.get("validation"), dict) else {}
    if "status" in v:
        out.append("검증 모양이 옛 형식 (validation.status) — traversal / rest 단계로 나눠야 함")
    for name in STAGES:
        if name in v and not isinstance(v[name], dict):
            out.append(f"검증 단계 {name} 모양이 틀림")
    t = v.get("traversal") if isinstance(v.get("traversal"), dict) else {}
    if t.get("status") != "validated":
        out.append(f"이동 경로 검증 안 됨 (validation.traversal.status {t.get('status')!r})")
    if not t.get("by") or not t.get("evidence"):
        out.append("이동 검증한 사람·근거 없음 (validation.traversal.by / evidence)")
    if not t.get("route_sha256"):
        out.append("이동 검증의 경로 지문 없음 (validation.traversal.route_sha256)")
    elif route is not None and t["route_sha256"] != route.fingerprint:
        out.append("경로 지문 다름 — 검증한 뒤 경로나 화톳불 자리가 바뀜 (validation.traversal.route_sha256)")
    if not R.get("_source"):
        out.append("녹화 출처 없음 (_source)")
    if route is None:
        return out
    if route.map != MAP:
        out.append(f"맵 다름 ({route.map!r} ≠ {MAP})")
    if math.dist(route.legs[0].points[0], route.start.stand) > LINK_R:
        out.append("첫 점이 제단 화톳불에서 멂")
    if math.dist(route.legs[-1].points[-1], route.end.stand) > LINK_R:
        out.append("끝 점이 안드레 화톳불에서 멂")
    return out


def stage_status(R) -> dict:
    """{stage: status or None} — for check() facts; rest's status gates nothing here."""
    v = (R or {}).get("validation")
    v = v if isinstance(v, dict) else {}
    return {k: v[k].get("status") if isinstance(v.get(k), dict) else None for k in STAGES}


def load_route(data_dir):
    """Route + spots files read once each → (route_fp.Route or None, raw route dict or None, problems).
    The Route is what check() and the walks use; nothing is read again during the run."""
    p = Path(data_dir) / "routes" / ROUTE
    if not p.exists():
        return None, None, [f"경로 데이터 없음 (data/routes/{ROUTE}) — 녹화·검토 전"]
    try:
        rt = p.read_text(encoding="utf-8")
        st = (Path(data_dir) / "spots.json").read_text(encoding="utf-8")
    except (OSError, ValueError) as ex:
        return None, None, [f"경로·화톳불 파일 못 읽음 ({ex})"]
    route, out = None, []
    try:
        route = route_fp.parse(rt, st, START_SPOT, END_SPOT)
    except route_fp.RouteError as ex:
        out += [f"경로 데이터 형식: {q}" for q in ex.problems]
    try:
        R = json.loads(rt)                                 # same text, for validation / _source only (route_fp ignores them)
    except ValueError:
        R = None
    if not isinstance(R, dict):
        return None, None, out or ["경로 데이터가 객체 아님"]
    return route, R, out + route_problems(R, route)


def _horiz(p, q) -> float:
    return math.hypot(p.x - q[0], p.z - q[2])


def _floor_mesh(nm):
    """The NavMesh that answers floor_at (run.py --ground wraps it as nm.nm — same lookup as Field._walk), or None."""
    base = getattr(nm, "nm", None)
    base = base if hasattr(base, "floor_at") else nm
    return base if hasattr(base, "floor_at") else None


class AltarToAndre:
    def __init__(self, field, nm, data_dir, lock=None, log=print, events=lambda *a, **k: None,
                 clock=time.monotonic, sleep=time.sleep, awake=None, buttons=None):
        self.f, self.mv, self.nm = field, field.mv, nm
        self.tm, self.pad = field.mv.tm, field.mv.pad
        self.lock, self.log, self.events = lock, log, events
        self.clock, self.sleep = clock, sleep
        self._awake = awake
        self._buttons = buttons          # needs .XUSB_GAMEPAD_A / .XUSB_GAMEPAD_B; None = control.B, imported only when pressing
        self.route, self.R, self.problems = load_route(data_dir)
        self.start = self.route.start if self.route else None
        self.end = self.route.end if self.route else None
        self.recoveries = 0
        self._ignore0 = None

    def awake(self, c) -> bool:
        if self._awake is None:
            from .field import awake
            self._awake = awake
        return self._awake(c)

    def _btn(self, name: str):
        if self._buttons is None:
            import control
            self._buttons = control.B
        return getattr(self._buttons, name)

    # ── start contract: reads only, no input ─────────────────────────────
    def check(self) -> Verdict:
        stop, facts = list(self.problems), {"validation": stage_status(self.R)}
        if self.lock is None or getattr(self.lock, "_f", None) is None:
            stop.append("봇 잠금(BotLock)을 쥐지 않음")
        else:
            held = Path(getattr(self.lock, "path", None) or botlock.LOCK_PATH).resolve()
            facts["lock"] = str(held)
            if held != botlock.LOCK_PATH.resolve():
                stop.append(f"쥔 잠금이 봇 잠금이 아님 ({held.name})")
        if ACTIVE:
            stop.append(f"다른 미션 진행 중 ({ACTIVE[0]})")
        if getattr(self.f, "denial", None):
            stop.append(f"Field에 앞선 거부가 남아 있음 ({self.f.denial.get('op')}) — 지우는 건 부른 쪽 일")
        if self.pad is None:
            stop.append("패드 없음")
        s = self.mv.snap(5.0)
        if s is None:
            stop.append("스냅숏 없음 (로딩·타이틀?)")
        else:
            p = s.player
            facts["pos"] = (round(p.x, 2), round(p.y, 2), round(p.z, 2))
            facts["hp"] = p.hp
            if not p.hp or p.hp <= 0:
                stop.append("HP 0 또는 못 읽음")
        if s is not None and self.start is not None:
            p = s.player
            st = self.start.stand
            d = _horiz(p, st)
            facts["start_d"] = round(d, 2)
            if d > START_R or abs(p.y - st[1]) > SPOT_DY:
                stop.append(f"시작 자리 밖 (제단 화톳불에서 {d:.1f} m, Δy {p.y - st[1]:+.1f})")
        menu = self.tm.menu_open()
        facts["menu_open"] = menu
        if menu is None:
            stop.append("메뉴 상태 못 읽음")
        elif menu:
            stop.append("메뉴 열림")
        sit = self._sitting()
        facts["sitting"] = sit
        if not callable(getattr(self.tm, "sitting_state", None)):
            stop.append("앉음 읽기 없음 (tm.sitting_state)")
        elif sit is None:
            stop.append("앉음 상태 못 읽음")
        elif sit:
            stop.append("화톳불에 앉아 있음 — 일어선 뒤 시작")
        reader = getattr(self.tm, "current_map", None)
        cur = reader() if callable(reader) else None
        facts["map"] = cur
        if cur is None:
            stop.append("현재 맵 확인 불가 (텔레메트리에 맵 읽기 없음)")
        elif cur != MAP:
            stop.append(f"현재 맵 {cur} ≠ {MAP}")
        lb = self.tm.last_bonfire()
        facts["last_bonfire"] = lb
        if lb != START_BONFIRE:
            stop.append(f"마지막 화톳불 {lb} ≠ {START_BONFIRE}")
        if self.route is not None:
            facts["route_sha256"] = self.route.fingerprint
        for q in (self.route.requires if self.route else ()):
            have = self.tm.event_flag(q.flag)
            facts[f"flag {q.flag}"] = have
            if have is None:
                stop.append(f"진행 조건 못 읽음 ({q.what})")
            elif bool(have) != q.want:
                stop.append(f"진행 조건 안 맞음 ({q.what}: {have})")
        if self.route and not self.problems:
            mesh = _floor_mesh(self.nm)
            if mesh is None:
                stop.append("NavMesh 없음 — 경로 점 바닥 확인 불가")
            else:
                off = [k + 1 for k, leg in enumerate(self.route.legs)
                       if any(mesh.floor_at(x, z, y) is None for x, y, z in leg.points)]
                if off:
                    stop.append(f"NavMesh 밖 점이 있는 구간 {off}")
        return Verdict(ok=not stop, stop=stop, facts=facts)

    # ── run ─────────────────────────────
    def run(self) -> str:
        v = self.check()
        self.log(f"   제단 → 안드레 시작 검사: {v.line()}")
        self.events("altar_andre", what="start", ok=v.ok, stop=v.stop, facts={k: str(x) for k, x in v.facts.items()})
        if not v.ok:
            return "refused: " + " · ".join(v.stop)        # nothing pressed, nothing moved, lock untouched
        ACTIVE.append("altar-andre")
        self._ignore0 = getattr(self.f, "ignore_npcs", set())
        smash0 = getattr(self.f, "smash_ok", True)
        self.f.smash_ok = False                            # opt-in: a blocking prop ends the walk (Field.denial), never a swing
        t0 = self.clock()
        try:
            for k, leg in enumerate(self.route.legs):
                r = self._leg(k, leg, t0)
                if r != "ok":
                    return r
            return self._rest()
        finally:
            ACTIVE.clear()
            self._release()
            self.f.smash_ok = smash0                       # the denial itself stays on the Field, as evidence

    def _sitting(self):
        """tm.sitting_state() → True · False · None; None also when the reader is missing (never read as 'not seated')."""
        fn = getattr(self.tm, "sitting_state", None)
        return fn() if callable(fn) else None

    def _release(self) -> None:
        self.f.ignore_npcs = self._ignore0 if self._ignore0 is not None else set()
        for name, arg in (("sprint", False), ("guard", False)):
            fn = getattr(self.pad, name, None)
            if callable(fn):
                fn(arg)
        self.pad.neutral()

    def _handoff(self, tag: str, why: str, **evidence) -> str:
        self._release()
        self.log(f"   ⚠ 제단 → 안드레 {tag}: {why} — 입력 놓고 멈춤, 사람이 맡음 (자리로 되돌아가지 않음)")
        self.events("altar_andre", what="handoff", leg=tag, why=why, recoveries=self.recoveries, **evidence)
        return f"handoff: {tag} {why}"

    def _foes_near(self, s) -> list[dict]:
        """Hand-off evidence: what was around, not a cause."""
        out = []
        for c in s.hostile(FOE_NEAR_R):
            if c.hp <= 0 or not self.awake(c):
                continue
            out.append({"npc": c.npc_param, "ptr": getattr(c, "ptr", None), "d": round(_horiz(s.player, (c.x, c.y, c.z)), 2),
                        "dy": round(c.y - s.player.y, 2), "anim": getattr(c, "anim", None), "hp": c.hp,
                        "ignored": c.npc_param in self.f.ignore_npcs})
        return sorted(out, key=lambda e: e["d"])

    def _leg(self, k: int, leg: route_fp.Leg, t0: float) -> str:
        tag, mode = leg.tag, leg.mode
        pts = list(leg.points)
        goal = pts[-1]
        self.f.ignore_npcs = set(leg.ignore_npcs)
        s = self.mv.snap(5.0)
        if s is None:
            return self._handoff(tag, "스냅숏 없음 (걷기 전)")
        best = _horiz(s.player, goal)
        late = lambda _s: self.clock() - t0 > MISSION_MAX_S   # Field sees this only on movement ticks (알려진 한계)
        r = self.f.walk(pts, self.nm, tag, mode=mode, done=late)
        while True:
            self.events("altar_andre", what="leg", leg=tag, result=r, recoveries=self.recoveries)
            if r == "dead" or not self.f.alive():
                self._release()
                self.log(f"   제단 → 안드레 {tag}: 사망 — 다시 하지 않음")
                return "died"
            denial = getattr(self.f, "denial", None)
            if denial:                                     # before WALK_OK: a refusal is not 'stuck' and gets no re-walk
                return self._handoff(tag, f"거부됨 ({denial['op']}): {denial['reason']}", walk=r, denial=denial)
            if r not in WALK_OK:
                return self._handoff(tag, f"걷기 결과 {r}", walk=r)
            s = self.mv.snap(FOE_NEAR_R + 2.0)
            if s is None:
                return self._handoff(tag, "스냅숏 없음", walk=r)
            d = _horiz(s.player, goal)
            if d <= LEG_DONE_R and abs(s.player.y - goal[1]) <= SPOT_DY:
                return "ok"
            if late(s):
                return self._handoff(tag, f"시간 넘음 ({MISSION_MAX_S:.0f} s, 끝까지 {d:.1f} m)", walk=r)
            progressed = best - d >= PROGRESS_M
            best = min(best, d)
            if not progressed:
                foes = self._foes_near(s)
                why = (f"진행 없음 — 깨어 있는 적 근처 {foes[0]['npc']} ({foes[0]['d']:.1f} m), 원인 미확정"
                       if foes else "진행 없음")
                return self._handoff(tag, f"{why} (끝까지 {d:.1f} m, 걷기 {r})", walk=r, d=round(d, 2), foes=foes)
            if self.recoveries >= RECOVERY_BUDGET:
                return self._handoff(tag, f"복구 {RECOVERY_BUDGET}번 다 씀 (끝까지 {d:.1f} m)", walk=r)
            self.recoveries += 1
            r = self.f.walk_to(goal, self.nm, f"{tag} (다시 {self.recoveries})", mode=mode, done=late)

    # ── bonfire: arrival ≠ interaction ≠ confirmed rest ─────────────────────────────
    def _rest(self) -> str:
        stand = self.end.stand
        s = self.mv.snap(FOE_NEAR_R + 2.0)
        if s is None:
            return self._handoff("화톳불", "스냅숏 없음")
        d = _horiz(s.player, stand)
        if d > END_R or abs(s.player.y - stand[1]) > SPOT_DY:
            return self._handoff("화톳불", f"화톳불 자리 못 옴 ({d:.1f} m)")
        self.events("altar_andre", what="arrived_area", d=round(d, 2))
        blocked = ([] if INTERACT_ENABLED else ["상호작용 확인 전 (INTERACT_ENABLED)"]) + \
                  ([] if self.end.object is not None else ["안드레 화톳불 대상 위치(object) 없음"])
        if blocked:
            self.events("altar_andre", what="interact_blocked", why=blocked)
            return "arrived_area: 상호작용 막힘 — " + " · ".join(blocked) + " (A 안 누름)"
        if not self.f.safe(s):
            return self._handoff("화톳불", "화톳불 앞 적 — 점화·앉기 안 함")
        before = self.tm.last_bonfire()
        if before == END_BONFIRE:
            return self._handoff("화톳불", f"마지막 화톳불이 이미 {END_BONFIRE} — 바뀜으로 쉼 확인 불가, A 안 누름")
        presses, sat = 0, False
        for _ in range(INTERACT_MAX):
            menu = self.tm.menu_open()
            if menu is not False:                          # True or unreadable, never pressed into
                return self._handoff("화톳불", f"예상 밖 메뉴 상태 ({menu}) — A 안 누름", presses=presses)
            self.mv.press(self._btn("XUSB_GAMEPAD_A"))
            presses += 1
            t1 = self.clock()
            while self.clock() - t1 < SIT_WAIT_S and self._sitting() is not True:
                self.sleep(0.25)
            sit = self._sitting()
            if sit is True:
                sat = True
                break
            if sit is None:                                # unknown is never seated — and no more A on a state we can't see
                break
        self.events("altar_andre", what="interact", presses=presses, sat=sat, sitting=sit)
        if not sat:
            self._release()
            seen = "앉음 상태 못 읽음" if sit is None else "앉음 안 보임"
            return f"rest_unconfirmed: A {presses}번, {seen} (마지막 화톳불 {before})"
        self.sleep(1.0)
        after = self.tm.last_bonfire()
        b = 0
        for _ in range(STAND_TRIES):                       # B only while seated / in the bonfire menu (otherwise it's a backstep)
            if not (self._sitting() is True or self.tm.menu_open() is True):
                break
            self.mv.press(self._btn("XUSB_GAMEPAD_B"))
            b += 1
            self.sleep(1.0)
        seated = self._sitting()
        ok = before != END_BONFIRE and after == END_BONFIRE
        self.events("altar_andre", what="rest", ok=ok, before=before, after=after, b=b, seated=seated)
        self.log(f"── 안드레 화톳불: 앉음 {sat}, 마지막 화톳불 {before} → {after}, B {b}번, 지금 앉음 {seated} — "
                 f"{'쉼 확인' if ok else '쉼 확인 못 함'}")
        if not ok:
            return f"rest_unconfirmed: 앉음 보임, 마지막 화톳불 {before} → {after}"
        if seated is None:
            return f"rested: B {b}번 뒤 지금 앉음 상태 못 읽음"
        return f"rested_seated: B {b}번 뒤에도 앉음" if seated else "rested"
