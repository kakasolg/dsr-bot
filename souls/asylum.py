"""Northern Undead Asylum (m18_01) for a fresh character — follow the step list asylum_steps.py made from MoKa's first pass.

  run.py asylum --seg 1        cell → ladder → first bonfire (no fights)

The Asylum's first pass has one-time events, so the bot does not plan it — it replays the human's steps (data/routes/asylum-fresh.json):
walk on the NavMesh (Field.walk — chasers are fought as usual), stand where the human pressed A and face the same way, climb
ladders (A at the bottom was the previous press step, then stick up), drop where the human dropped, replay menu inputs.
Segments are cut at labelled steps so each piece can be checked with its own new character (ROADMAP 1-h).
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

import control
import nav

from . import moves as M

ROUTE = Path(__file__).resolve().parent.parent / "data" / "routes" / "asylum-fresh.json"
MAP = "m18_01_00_00"
# segment n = steps after the end of segment n-1 up to and including the first step whose label starts with END[n]
SEG_END = {1: "첫 화톳불", 2: "시작 장비 줍기 2", 3: "오스카 대화", 4: "위층 기사 뒤", 5: ""}   # "" = to the end (the crow)
# 데몬: 위 안개벽을 지나면 곧바로 뛰어내리며 친다 — 발판에서 기다리면 ~8.5 s 뒤 데몬이 도약해 발판까지 친다
# (boss/boss.py 9번째 죽음, 2026-09-29 구간 ④를 안개벽 뒤에서 끝냈다가 죽음) → 구간 ④는 안개벽 앞에서 끝
PLUNGE_AT = "데몬 위 안개벽"
TWO_HAND = 3             # tm.grip(): 3 = two-handed, 1 = one-handed
# 안개벽은 문 가운데에 서야 통과된다 ([MoKa]: "문 한쪽에 치우치면 안개벽 통과 못해"). 데몬 위 안개벽: 사람이 누른 자리 x 3.33·3.82
# (둘 다 통과), 봇 x 4.18 은 못 지나감 (2026-09-29) → 가운데 x 3.55, 0.15 m 안으로 맞추고 안내가 뜨면 A (Field.fog_through)
FOG_CENTER = {PLUNGE_AT: (3.55, 210.11, -34.72)}
FOG_TOL = 0.15
DEMON_LIMIT = 240.0
# 데몬 싸움 — 가드·구르기 안 함 ([MoKa]: "가드 무조건 밀리지"; "계속 때리던가, 뒤잡 하듯이 보스 뒤로 돌던가").
# 사람 두 녹화의 약공 9번: 거리 2.0~3.5 m, 데몬 정면에서 9~158°(대부분 옆 60~100°), 거의 매번 한 대 치고 6~7 m 밖으로 빠졌다가 옆으로
# 다시 들어감. 첫 봇 판은 "100° 넘게 뒤일 때만" 치게 해서 한 대도 못 치고 3.8 m 로 돌기만 하다 정면(0~12°)에서 회전 공격에 맞아 죽음
DEMON_HIT_R = 3.5        # swing within this (horizontal, to its center — its body is big, 2 m is about as close as it gets)
DEMON_SIDE_DEG = 45.0    # …when we're at least this far off its facing, or it's standing still (anim -1)
DEMON_BACK_DEG = 110.0   # "behind" = at least this far off its facing — only then step in close
DEMON_WIDE_R = 5.5       # not behind yet: circle at this radius toward its back ([MoKa]: "뒤로 크게 돌았어야 했어" — 3.8 m was too
DEMON_ORBIT_STEP = 45.0  #   tight, it kept turning to face us), aiming this many degrees further round each tick
DEMON_IN_R = 2.6         # behind it: go in to this and swing
DEMON_OUT_R = 6.5        # after each swing run out to this, then come back in (hit and run)
DEMON_OUT_S = 2.5        # …for at most this long
DEMON_SLAM = 3008        # jump butt slam — run out of DEMON_SLAM_R when it starts
DEMON_SLAM_R = 8.4
DEMON_SLAM_S = 4.3
DEMON_ESTUS_HP = 0.4     # drink below this when the demon is DEMON_ESTUS_R away and not swinging
DEMON_ESTUS_R = 6.0
RESUME_NEAR = 5.0        # farther than this from the first step → start from the nearest step (after dying / a restart)
# 데몬 처음 만남: 큰 방 문을 연 뒤부터 도망친 방 화톳불까지는 달리고, 데몬과 싸우지 않는다 (사람도 도망침)
FLEE = ("큰 방 문", "도망친 방 화톳불")


class _Everyone(frozenset):
    """ignore_npcs that holds every NPC — walks fight nobody (between the shield and the Battle Axe)."""
    def __contains__(self, npc) -> bool:
        return True


EVERYONE = _Everyone()
DEMON = 223200
# 시작 장비 (산적): 첫 번째로 줍는 게 방패, 두 번째가 배틀 액스 — [MoKa] 항상 같음. 메뉴 장착 뒤 확인
GEAR = {"방패": ("왼손1", 1462000), "배틀 액스": ("오른손1", 701000)}
START_HP = 0.5          # don't start a segment below this HP with no Estus (the gap between segment 2 and 3 left us at 152/616)
LAST_STAND_R = 6.0       # failing with an awake foe this close: fight it out instead of standing there (died idle, 2026-09-29 seg 3)
PRESS_TOL = 0.35         # stand this close to where the human pressed A
FACE_DEG = 20.0          # …and face within this of their heading
PRESS_GAP = 0.3          # between repeated A presses (item messages, dialogue)
CLIMB_S = 15.0           # give up a ladder after this
DROP_S = 4.0
MENU_GAP = 0.35          # menu inputs when the recording has no gaps (control buffer tangles when faster — user)
MENU_GAP_MIN = 0.25
# START·A·B는 메뉴 화면을 바꾼다 — 메모리 화면 값(quitout._screen)이 누른 지 ~0.15 s 뒤 바뀐다. 녹화 간격만 믿고 누르니
# 장비 화면이 다 열리기 전에 DOWN이 씹혀 방패 대신 검 자루가 왼손으로 감 (09-29 구간 2, 10-03b 다시 — P-40).
# 1 s 간격으로 천천히 누르면 같은 키로 맞게 장착됨 (10-03 실측). 방향키·장착 A는 화면 값이 안 바뀜 → 그건 녹화 간격대로
MENU_SCREEN_KEYS = {"START", "A", "B"}
MENU_SCREEN_WAIT = 1.2   # wait this long for the screen value to change after START / A / B (equip A and B in the world don't change it)
MENU_SETTLE = 0.45       # after it changed: let the new screen finish drawing before the next key
KEEP_GAP_M = 1.5         # a press/menu right after another one within this distance keeps the human's pause between them
KEEP_GAP_MAX = 6.0
BTN = {"A": control.B.XUSB_GAMEPAD_A, "B": control.B.XUSB_GAMEPAD_B, "START": control.B.XUSB_GAMEPAD_START,
       "UP": control.B.XUSB_GAMEPAD_DPAD_UP, "DOWN": control.B.XUSB_GAMEPAD_DPAD_DOWN,
       "LEFT": control.B.XUSB_GAMEPAD_DPAD_LEFT, "RIGHT": control.B.XUSB_GAMEPAD_DPAD_RIGHT,
       "X": control.B.XUSB_GAMEPAD_X, "Y": control.B.XUSB_GAMEPAD_Y}


def load(path: Path = ROUTE) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["steps"]


def segment(steps: list[dict], n: int) -> list[dict]:
    """Steps of segment n (1-based). Menu steps before the segment's first press are dropped — at the very start they are the human
    skipping the intro / character creation (START START), and pressed in game they would open the menu."""
    start = 0
    for k in range(1, n + 1):
        if SEG_END[k] == "":
            return steps[start:] if k == n else []
        end = next((i for i in range(start, len(steps)) if steps[i].get("label", "").startswith(SEG_END[k])), None)
        if end is None:
            raise ValueError(f"segment {k}: no step labelled '{SEG_END[k]}…'")
        # the end is the whole run of steps with that label (mark → press → menu), one-point walks in between included
        j = end + 1
        while j < len(steps) and (steps[j].get("label", "").startswith(SEG_END[k])
                                  or (steps[j]["type"] == "walk" and len(steps[j]["pts"]) <= 1)):
            if steps[j].get("label", "").startswith(SEG_END[k]):
                end = j
            j += 1
        if k == n:
            out = steps[start:end + 1]
            first = next((i for i, x in enumerate(out) if x["type"] == "press"), len(out))
            return [x for i, x in enumerate(out) if not (x["type"] == "menu" and i < first)]
        start = end + 1
    return []


def step_pos(st: dict, near=None):
    """A representative position of a step (for resuming): walk → its point nearest to near, others → pos / from."""
    if st["type"] == "walk":
        pts = st["pts"]
        return min(pts, key=lambda q: math.dist(q, near)) if near is not None else pts[0]
    return st.get("pos") or st.get("from")


def resume(steps: list[dict], here) -> tuple[int, list[dict]]:
    """Index of the step nearest to here, and the steps from there (a walk is cut to start at its nearest point)."""
    def d(i):
        q = step_pos(steps[i], here)
        return math.dist(q, here) if q else 1e9
    best = min(range(len(steps)), key=d)
    out = [dict(x) for x in steps[best:]]
    if out and out[0]["type"] == "walk":
        pts = out[0]["pts"]
        k = min(range(len(pts)), key=lambda j: math.dist(pts[j], here))
        out[0]["pts"] = pts[k:]
    return best, out


def heading_vec(hd: float) -> tuple[float, float]:
    """Unit (dx, dz) the character faces for a raw heading (world yaw = heading + π, moves.rel_angle)."""
    f = hd + math.pi
    return math.sin(f), math.cos(f)


def heading_off(cur: float, want: float) -> float:
    """Degrees from heading cur to want (−180..180)."""
    return math.degrees((want - cur + math.pi) % (2 * math.pi) - math.pi)


class Asylum:
    def __init__(self, fld, nm, log=print, events=None):
        self.f, self.nm, self.log = fld, nm, log
        fld.ignore_npcs = set()
        self.mv: M.Moves = fld.mv
        self.tm, self.pad = self.mv.tm, self.mv.pad
        self.events = events or (lambda *a, **k: None)

    # ── steps ────────────────────────────────────────────────
    def run(self, steps: list[dict], tag: str = "수용소") -> str:
        fleeing = False
        last = None                                        # (recorded t, pos, wall time) of the last press / menu
        skip_to = -1                                       # steps the plunge + demon fight replaced
        for i, st in enumerate(steps):
            if i < skip_to:
                continue
            if (st["type"] in ("press", "menu") and last is not None and st.get("t") is not None and st.get("pos")
                    and math.dist(st["pos"], last[1]) <= KEEP_GAP_M):
                # 줍기 A → (아이템 획득 창) → 닫기 A 사이를 사람처럼 기다린다. 0.6 s 만에 누르니 창이 안 닫힌 채 메뉴 입력이
                # 한 칸씩 밀려 검 자루가 왼손으로 감 (2026-09-29 구간 2, 사람은 3.5 s 기다림)
                wait = min(KEEP_GAP_MAX, st["t"] - last[0]) - (time.time() - last[2])
                if wait > 0:
                    time.sleep(wait)
            lab = st.get("label", "")
            if st["type"] == "press" and lab.startswith(FLEE[0]):
                fleeing = True
            # 방패는 들었는데 아직 배틀 액스 전: 검 자루로는 한 번에 4 — 망자 250021과 45 s 싸워 준 38·받은 300, 에스트 없이 멈춤
            # (10-03c). [MoKa] "배틀 액스 확보할 때까지는 빨리" → 달리고, 아무와도 안 싸움
            rushing = st["type"] == "walk" and not fleeing and self._shield_on() and not self._armed()
            if fleeing or rushing:
                st = dict(st, run=True) if st["type"] == "walk" else st
            self.f.ignore_npcs = EVERYONE if rushing else {DEMON} if fleeing else set()
            if st["type"] == "press" and lab.startswith(FLEE[1]):
                fleeing = False
            what = st.get("label") or st["type"]
            fog = next((c for k, c in FOG_CENTER.items() if st["type"] == "press" and lab.startswith(k)), None)
            if fog is not None:
                if lab.startswith(PLUNGE_AT):
                    self.f.heal(0.9, sips=3)                   # boss room next — went in at 487/616 after the knight (2026-09-29)
                beyond = next((w["pts"][-1] for w in steps[i + 1:] if w["type"] == "walk"), None)
                r = self._fog(fog, beyond, f"{tag} {i + 1}/{len(steps)}")
            else:
                r = getattr(self, "_" + st["type"])(st, f"{tag} {i + 1}/{len(steps)}")
            if r == "ok" and st["type"] == "press" and lab.startswith(PLUNGE_AT):
                # the recording's plunge + fight (circling walks, the drop, fight rows) → our own plunge, then the demon fight.
                # 낙사 퀵 종료·턱 보정은 데몬을 잡을 때까지 끔: 떨어지는 동안 턱 보정이 3번 끌어당겼고, 착지 0.1 s 뒤 "바닥 16 m 아래"
                # (데몬 방 바닥 NavMesh 빈 곳) 로 퀵 종료 → 안개벽 앞에서 되살아난 망자 둘에게 죽음 (2026-09-29, P-25). 데몬 방엔 떨어질 곳 없음
                esc = self.f.esc
                saved = (esc.quit_ok, getattr(esc, "nudge_ok", True))
                esc.quit_ok, esc.nudge_ok = False, False
                try:
                    r = self._plunge(f"{tag} {i + 1}/{len(steps)}")
                    if r == "ok":
                        r = self._demon(f"{tag} {i + 1}/{len(steps)}")
                finally:
                    esc.quit_ok, esc.nudge_ok = saved
                skip_to = 1 + max((j for j in range(i, len(steps)) if steps[j]["type"] == "fight" and steps[j].get("npc") == DEMON),
                                  default=i)
            self.events("asylum_step", i=i, type=st["type"], label=st.get("label"), result=r)
            if r in ("dead", "fail"):
                self.log(f"   {tag} {i + 1}/{len(steps)} {st['type']} ({what}): {r} — 멈춤")
                if r == "fail":
                    self._last_stand(tag)
                return f"{r} at {i + 1} {st['type']} {what}"
            if st["type"] in ("press", "menu") and st.get("t") is not None and st.get("pos"):
                last = (st["t"] + (sum(st.get("dt", [])) if st["type"] == "menu" else 0.0), st["pos"], time.time())
            elif st["type"] not in ("walk", "mark") or len(st.get("pts", [])) > 1:
                last = None
            if not self.f.alive():
                return f"dead at {i + 1} {st['type']} {what}"
        return "done"

    def ready(self) -> str | None:
        """Why this segment shouldn't start now (low HP and no Estus), or None."""
        s = self.mv.snap(10.0)
        if s is None:
            return "no snapshot"
        p = s.player
        if p.hp < p.max_hp * START_HP and self.f.estus_left() <= 0:
            return f"HP {p.hp}/{p.max_hp}, 에스트 없음"
        return None

    def _last_stand(self, tag) -> None:
        """Stopping next to an awake foe = dying idle once the bot exits — fight it to the end first."""
        from .field import awake
        for _ in range(3):
            s = self.mv.snap(LAST_STAND_R + 2.0)
            near = [] if s is None else [c for c in s.hostile(LAST_STAND_R + 1.0) if awake(c) and c.anim not in (None, -1)
                                         and M.horiz(s.player, c) < LAST_STAND_R and c.npc_param not in self.f.ignore_npcs]
            if not near:
                return
            c = min(near, key=lambda x: M.horiz(s.player, x))
            r = self.f.fight(c.ptr, self.nm, f"{tag} 멈추기 전 {c.npc_param}", desperate=True)
            if r.result == "me_dead":
                return

    def _walk(self, st, tag) -> str:
        pts = [tuple(p) for p in st["pts"]]
        s = self.mv.snap(5.0)
        if s is not None and len(pts) > 1 and math.dist((s.player.x, s.player.y, s.player.z), pts[0]) < 1.0:
            pts = pts[1:]
        mode = "sprint" if st.get("run") else ("guard" if self._shield_on() else "walk")
        r = self.f.walk(pts, self.nm, f"{tag} 걷기", mode=mode)
        if r == "dead":
            return "dead"
        s = self.mv.snap(5.0)
        d = None if s is None else math.dist((s.player.x, s.player.y, s.player.z), pts[-1])
        if d is not None and d > 2.0:
            self.log(f"   {tag} 걷기: {r}, 끝 점까지 {d:.1f} m")
            return "fail"
        return "ok"

    def _shield_on(self) -> bool:
        """방패를 들었으면 걸을 때 가드를 올린다 ([MoKa] 2026-10-03: 방패 장착 뒤 화살 쏘는 망자에게 계속 맞음)."""
        try:
            left = self.tm.equipment().get(GEAR["방패"][0])
        except Exception:
            return False
        return left is not None and left // 100 * 100 == GEAR["방패"][1]

    def _armed(self) -> bool:
        """Battle Axe in the right hand — until then a fight is the sword hilt (4 a hit)."""
        try:
            right = self.tm.equipment().get(GEAR["배틀 액스"][0])
        except Exception:
            return True                                    # unreadable: behave as before (fight when chased)
        return right is not None and right // 100 * 100 == GEAR["배틀 액스"][1]

    def _stand(self, pos, hd) -> bool:
        """Walk to pos (within PRESS_TOL) and turn to heading hd with short stick nudges (DS1 can't turn in place — farm.rest)."""
        nav.goto(self.tm, self.pad, tuple(pos), tolerance=PRESS_TOL, timeout=10, log=lambda *a: None, terrain=self.nm,
                 mode_fn=lambda _s: "walk")
        self.pad.neutral()
        if hd is None:
            return True
        for _ in range(4):
            s = self.tm.snapshot(within=2.0)
            if s is None or s.cam_yaw is None or s.player.heading is None:
                return False
            if abs(heading_off(s.player.heading, hd)) <= FACE_DEG:
                return True
            dx, dz = heading_vec(hd)
            stx, sty = control.world_to_stick(dx, dz, s.cam_yaw, nav.YAW_OFFSET, nav.FLIP_X)
            self.pad.move(stx * 0.45, sty * 0.45)
            time.sleep(0.15)
            self.pad.move(0.0, 0.0)
            time.sleep(0.35)
        return False

    def _press(self, st, tag) -> str:
        faced = self._stand(st["pos"], st.get("hd"))
        control.focus_game()
        for k in range(st.get("n", 1)):
            self.mv.press(BTN["A"], gap=PRESS_GAP)
        self.log(f"   {tag} A ×{st.get('n', 1)} ({st.get('label') or '?'}){'' if faced else ' — 방향 못 맞춤'}")
        if "화톳불" in st.get("label", ""):
            # 이미 불 붙은 화톳불(죽은 뒤 이어갈 때)이면 A = 앉기 → 메뉴가 열린 채 다음 걷기가 막힌다. 앉았으면 B 로 일어남 (farm.rest)
            time.sleep(2.5)
            for _ in range(6):
                if not (self.tm.sitting() or self.tm.menu_open() is True):
                    break
                self.mv.press(BTN["B"], gap=1.0)
            else:
                self.log(f"   {tag} 화톳불에서 못 일어남")
                return "fail"
        return "ok"

    def _fog(self, center, beyond, tag) -> str:
        """Fog wall: stand at the door's center (FOG_TOL), face the far side, A when the prompt shows (Field.fog_through)."""
        for k in range(3):
            nav.goto(self.tm, self.pad, tuple(center), tolerance=0.3, timeout=8, log=lambda *a: None, terrain=self.nm,
                     mode_fn=lambda _s: "walk")
            self.pad.neutral()
            left = self.f._settle(tuple(center), tol=FOG_TOL)
            if self.f.fog_through(tuple(beyond)):
                self.log(f"   {tag} 안개벽 통과 ({k + 1}번째, 가운데에서 {left:.2f} m)")
                return "ok"
            self.log(f"   {tag} 안개벽 못 지나감 ({k + 1}번째, 가운데에서 {left:.2f} m)")
        return "fail"

    def _climb(self, st, tag) -> str:
        y0, y1 = st["from"][1], st["to"][1]
        if y1 < y0:
            return self._drop(st, tag)
        s = self.mv.snap(3.0)
        start_y = s.player.y if s else y0
        t0 = time.time()
        moved = False
        while time.time() - t0 < CLIMB_S:
            self.pad.move(0.0, 1.0)                        # stick up = climb
            time.sleep(0.1)
            s = self.mv.snap(3.0)
            if s is None:
                continue
            moved = moved or s.player.y > start_y + 0.4
            if s.player.y >= y1 - 0.3:
                time.sleep(0.8)                            # keep pushing — step off the top
                break
            if not moved and time.time() - t0 > 2.5:
                self.pad.neutral()
                self.log(f"   {tag} 사다리: 안 올라감 (y {s.player.y:.1f}) — A 다시")
                self.mv.press(BTN["A"])
                t0, start_y = time.time(), s.player.y
                moved = True                               # one retry
        self.pad.neutral()
        s = self.mv.snap(3.0)
        ok = s is not None and s.player.y >= y1 - 0.5
        self.log(f"   {tag} 사다리 {y0:.1f} → {y1:.1f}: {'올라감' if ok else '실패'} (y {None if s is None else round(s.player.y, 1)})")
        return "ok" if ok else "fail"

    def _drop(self, st, tag) -> str:
        """Step off where the human dropped (boulder dodge): push toward the landing spot until we've come down."""
        to = st["to"]
        t0 = time.time()
        s = self.mv.snap(3.0)
        y_start = s.player.y if s else st["from"][1]
        while time.time() - t0 < DROP_S:
            s = self.mv.snap(3.0)
            if s is None or s.cam_yaw is None:
                time.sleep(0.05)
                continue
            if s.player.y < y_start - 1.5:
                break
            self.pad.move(*self.mv.stick_to(s, to[0], to[2], 0.7))
            time.sleep(0.05)
        time.sleep(0.8)
        self.pad.neutral()
        s = self.mv.snap(3.0)
        ok = s is not None and s.player.y < y_start - 1.5
        self.log(f"   {tag} 떨어지기: {'됨' if ok else '실패'}")
        return "ok" if ok else "fail"

    def _menu(self, st, tag) -> str:
        want = next((v for k, v in GEAR.items() if k in st.get("label", "")), None)
        before = self.tm.equipment() if want else {}
        if want and (before.get(want[0]) or 0) // 100 * 100 == want[1]:
            self.log(f"   {tag} 메뉴 건너뜀 — {want[0]} 이미 {before.get(want[0])}")    # resumed after dying: already equipped
            return "ok"
        if not want and st.get("label", "").startswith("까마귀"):
            # 사람은 까마귀 장면을 START 로 넘김 — 장면 밖에서 누르면 메뉴가 열린다
            self.log(f"   {tag} 메뉴 건너뜀 (까마귀 장면 넘기기)")
            return "ok"
        control.focus_game()
        dts = st.get("dt") or []
        for j, k in enumerate(st["keys"]):
            if j + 1 < len(dts):                           # wait the human's gap before the next key (menu open ~0.7 s)
                gap = max(MENU_GAP_MIN, min(3.0, dts[j + 1]))
            else:
                gap = MENU_GAP
            if k in BTN:
                self._menu_key(k, gap)
        time.sleep(0.5)
        self.log(f"   {tag} 메뉴 {' '.join(st['keys'])} ({st.get('label') or '?'})")
        if want is None:
            return "ok"
        slot, item = want
        now = self.tm.equipment().get(slot)
        ok = now is not None and now // 100 * 100 == item               # +n upgrades keep the base id's hundreds
        self.log(f"      장착 확인 {slot}: {before.get(slot)} → {now} ({'맞음' if ok else f'원함 {item}'})")
        return "ok" if ok else "fail"

    def _menu_key(self, k: str, gap: float) -> None:
        """One menu key. START / A / B: wait until the menu screen value changes, then MENU_SETTLE (at least the human's gap);
        a START that changed nothing (menu didn't open) is pressed once more. Screen unreadable → the recorded gap as before."""
        import quitout
        before = quitout._screen(self.tm) if k in MENU_SCREEN_KEYS else None
        if before is None:
            self.mv.press(BTN[k], gap=gap)
            return
        for attempt in range(2 if k == "START" else 1):
            t0 = time.time()
            self.mv.press(BTN[k], gap=0.0)
            while time.time() - t0 < MENU_SCREEN_WAIT and quitout._screen(self.tm) == before:
                time.sleep(0.02)
            if quitout._screen(self.tm) != before:
                time.sleep(max(MENU_SETTLE, gap - (time.time() - t0)))
                return
        # no change: the equip A in a list, a B out in the world — or a swallowed key; carry on, the equipment check decides

    def _fight(self, st, tag) -> str:
        s = self.mv.snap(15.0)
        cands = [] if s is None else [c for c in s.hostile(10.0) if c.npc_param == st["npc"] and c.hp > 0]
        if not cands:
            return "ok"                                    # already dealt with while walking
        c = min(cands, key=lambda x: x.dist)
        r = self.f.fight(c.ptr, self.nm, f"{tag} {st['npc']}")
        return "dead" if r.result == "me_dead" else "ok"

    def _mark(self, st, tag) -> str:
        return "ok"

    def _jump(self, st, tag) -> str:
        """The crow: stand where the human was grabbed and wait for the position to jump (cutscene → Firelink Shrine)."""
        s0 = self.mv.snap(5.0)
        if s0 is None:
            return "fail"
        here0 = (s0.player.x, s0.player.y, s0.player.z)
        t0 = time.time()
        # 까마귀가 옮기면 위치가 270 m 바뀜 → 낙사 감시가 "0.8 s 에 271 m 떨어짐" 으로 퀵 종료 (2026-09-29, 불의 제전에서) — 그동안 끔
        esc = self.f.esc
        saved, esc.quit_ok = esc.quit_ok, False
        try:
            return self._wait_crow(st, tag, here0, t0)
        finally:
            time.sleep(3.0)                                # let the watcher's fall window pass the jump before re-arming
            esc.quit_ok = saved

    def _wait_crow(self, st, tag, here0, t0) -> str:
        while time.time() - t0 < 45.0:
            s = self.mv.snap(5.0)
            if s is not None and math.dist((s.player.x, s.player.y, s.player.z), here0) > 15.0:
                self.pad.neutral()
                self.log(f"   {tag} 까마귀 → ({s.player.x:.1f}, {s.player.y:.1f}, {s.player.z:.1f})")
                return "ok"
            if s is not None and s.cam_yaw is not None and math.dist((s.player.x, s.player.z), (st["from"][0], st["from"][2])) > 0.8:
                self.pad.move(*self.mv.stick_to(s, st["from"][0], st["from"][2], 0.5))
            else:
                self.pad.neutral()
            time.sleep(0.1)
        self.pad.neutral()
        self.log(f"   {tag} 까마귀: 45 s 안에 안 옮겨짐")
        return "fail"

    # ── the Asylum Demon (boss/boss.py plunge, adapted) ─────────────────────────
    @staticmethod
    def _demon_c(s):
        return None if s is None else next((c for c in s.chars if c.npc_param == DEMON and c.hp > 0), None)

    def _two_hand(self, tag) -> bool:
        """Two hands for the demon — plunge and light hit harder (boss/README.md; MoKa pressed Y right before jumping, recording
        20260929_061447 at 423.9 s). Field.fight keeps it through grip_want (it resets the grip to the style's at every fight start)."""
        self.f.grip_want = TWO_HAND
        for _ in range(3):
            if self.tm.grip() == TWO_HAND:
                break
            self.pad.two_hand_right()
            time.sleep(0.5)
        g = self.tm.grip()
        self.log(f"   {tag} 양손 잡기: grip {g}{'' if g == TWO_HAND else ' — 안 바뀜'}")
        return g == TWO_HAND

    def _plunge(self, tag) -> str:
        """After the upper fog: go as soon as the demon faces us (or starts its leap 3023), stick toward it, R1 every 0.15 s
        while actually falling (R1 before the drop is eaten — boss.py 10th try). The fall quit-out is off meanwhile (~10 m drop)."""
        t_w = time.time()
        while time.time() - t_w < 4.0:
            s = self.mv.snap(40.0)
            d = self._demon_c(s)
            if d is not None and (d.anim == 3023 or (d.heading is not None and d.anim in (3020, 3021, -1)
                                                        and abs(math.degrees(M.rel_angle(d, s.player))) < 25)):
                break
            time.sleep(0.05)
        s = self.mv.snap(40.0)
        d = self._demon_c(s)
        if s is None or d is None:
            self.log(f"   {tag} 떨어지며 치기: 데몬 안 보임")
            return "fail"
        y0, hp0 = s.player.y, d.hp
        self._two_hand(tag)
        pressed_t, last_rb, t1 = None, 0.0, time.time()
        try:
            self.pad.sprint(True)
            while time.time() - t1 < 6.0:
                s = self.mv.snap(40.0)
                if s is None:
                    time.sleep(0.03)
                    continue
                d = self._demon_c(s) or d
                if s.cam_yaw is not None:
                    self.pad.move(*self.mv.stick_to(s, d.x, d.z, 1.0))
                falling = s.player.anim == 1500 or s.player.y < y0 - 1.0
                if falling and s.player.y > y0 - 11.0 and time.time() - last_rb > 0.15:
                    self.pad.sprint(False)
                    self.mv.press(control.B.XUSB_GAMEPAD_RIGHT_SHOULDER, hold=0.06, gap=0.0)
                    last_rb = time.time()
                    pressed_t = pressed_t or time.time()
                    continue
                if pressed_t and time.time() - pressed_t > 1.5 and s.player.y < y0 - 8.0:
                    break
                time.sleep(0.02)
        finally:
            self.pad.sprint(False)
            self.pad.neutral()
        s = self.mv.snap(40.0)
        d2 = self._demon_c(s)
        landed = s is not None and s.player.y < y0 - 8.0
        self.log(f"   {tag} 떨어지며 치기: 데몬 HP {hp0} → {d2.hp if d2 else 0}, 내 HP {None if s is None else s.player.hp}"
                 f"{'' if landed else ' — 안 떨어짐'}")
        self.events("plunge", demon_hp=[hp0, d2.hp if d2 else 0], landed=landed)
        return "ok" if landed else "fail"

    def _demon(self, tag) -> str:
        """The Asylum Demon without the field duel (its hits push through the guard): hit and run like MoKa — one light from its
        side (or when it stands still) within DEMON_HIT_R, then out to DEMON_OUT_R, back in at its side. Run from the butt slam.
        Two hands (grip_want) and no guard meanwhile."""
        guard_ok, self.mv.guard_ok = getattr(self.mv, "guard_ok", True), False
        t0, hits = time.time(), 0
        slam_until, out_until, prev_anim = 0.0, 0.0, None
        try:
            while time.time() - t0 < DEMON_LIMIT:
                if not self.f.alive():
                    return "dead"
                s = self.mv.snap(40.0)
                d = self._demon_c(s)
                if s is None:
                    time.sleep(0.05)
                    continue
                if d is None:
                    self.log(f"   {tag} 데몬 처치 — {time.time() - t0:.0f} s, 약공 {hits}번")
                    return "ok"
                p = s.player
                h = M.horiz(p, d)
                off = abs(math.degrees(M.rel_angle(d, p))) if d.heading is not None else 180.0   # 0 = right in front of it
                a = d.anim if d.anim is not None else -1
                now = time.time()
                if a == DEMON_SLAM and prev_anim != DEMON_SLAM:  # the anim id lingers after the move — only its start counts
                    slam_until = now + DEMON_SLAM_S
                prev_anim = a
                if now < slam_until and h < DEMON_SLAM_R:
                    self._demon_move(s, d, "out", DEMON_SLAM_R + 1.0)
                    continue
                if now < out_until and h < DEMON_OUT_R:
                    self._demon_move(s, d, "out", DEMON_OUT_R + 0.5)
                    continue
                if p.hp < p.max_hp * DEMON_ESTUS_HP and h > DEMON_ESTUS_R and a not in M.ATTACK:
                    self.pad.sprint(False)
                    self.pad.neutral()
                    r = self.mv.drink(lambda sn: self._demon_c(sn) is None or M.horiz(sn.player, self._demon_c(sn)) > DEMON_ESTUS_R - 1.5)
                    self.log(f"   {tag} 데몬 싸움 중 에스트: {r}")
                    continue
                if h <= DEMON_HIT_R and (off >= DEMON_SIDE_DEG or a == -1):
                    self.pad.sprint(False)
                    if self.mv.face(s, d, deg=35.0):
                        hit = self.mv.light(s, d, n=1, sp_second=999)
                        hits += 1
                        out_until = time.time() + DEMON_OUT_S
                        self.events("demon_hit", dmg=hit.dmg, taken=hit.taken, h=round(h, 2), off=round(off), anim=a)
                    continue
                self._demon_move(s, d, "in", DEMON_IN_R)
            return "fail"
        finally:
            self.pad.sprint(False)
            self.pad.neutral()
            self.mv.guard_ok = guard_ok
            self.f.grip_want = None

    def _demon_move(self, s, d, how: str, r_to: float) -> None:
        """One stick tick. out = straight away from it to r_to. in = behind it (DEMON_BACK_DEG off its facing) → step in to r_to
        right behind; not behind yet → circle wide (DEMON_WIDE_R) toward its back the shorter way round."""
        p = s.player
        dx, dz = p.x - d.x, p.z - d.z
        r = math.hypot(dx, dz) or 1e-6
        if how == "out":
            tx, tz = d.x + dx / r * r_to, d.z + dz / r * r_to
        else:
            fx, fz = heading_vec(d.heading) if d.heading is not None else (0.0, 1.0)
            back = math.atan2(-fx, -fz)                    # direction from its center to right behind it
            cur = math.atan2(dx, dz)
            diff = (back - cur + math.pi) % (2 * math.pi) - math.pi
            if abs(math.degrees(diff)) <= 180.0 - DEMON_BACK_DEG:
                ang, rr = back, r_to
            else:
                ang = cur + math.copysign(min(abs(diff), math.radians(DEMON_ORBIT_STEP)), diff)
                rr = DEMON_WIDE_R
            tx, tz = d.x + math.sin(ang) * rr, d.z + math.cos(ang) * rr
        if s.cam_yaw is not None:
            self.pad.sprint(how == "out" or math.hypot(tx - p.x, tz - p.z) > 3.0)
            self.pad.move(*self.mv.stick_to(s, tx, tz, 1.0))
        time.sleep(0.05)
