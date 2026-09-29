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
SEG_END = {1: "첫 화톳불"}
PRESS_TOL = 0.35         # stand this close to where the human pressed A
FACE_DEG = 20.0          # …and face within this of their heading
PRESS_GAP = 0.3          # between repeated A presses (item messages, dialogue)
CLIMB_S = 15.0           # give up a ladder after this
DROP_S = 4.0
MENU_GAP = 0.35          # menu inputs (control buffer tangles when faster — user)
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
        end = next((i for i in range(start, len(steps)) if steps[i].get("label", "").startswith(SEG_END[k])), None)
        if end is None:
            raise ValueError(f"segment {k}: no step labelled '{SEG_END[k]}…'")
        if k == n:
            out = steps[start:end + 1]
            first = next((i for i, x in enumerate(out) if x["type"] == "press"), len(out))
            return [x for i, x in enumerate(out) if not (x["type"] == "menu" and i < first)]
        start = end + 1
    return []


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
        self.mv: M.Moves = fld.mv
        self.tm, self.pad = self.mv.tm, self.mv.pad
        self.events = events or (lambda *a, **k: None)

    # ── steps ────────────────────────────────────────────────
    def run(self, steps: list[dict], tag: str = "수용소") -> str:
        for i, st in enumerate(steps):
            what = st.get("label") or st["type"]
            r = getattr(self, "_" + st["type"])(st, f"{tag} {i + 1}/{len(steps)}")
            self.events("asylum_step", i=i, type=st["type"], label=st.get("label"), result=r)
            if r in ("dead", "fail"):
                self.log(f"   {tag} {i + 1}/{len(steps)} {st['type']} ({what}): {r} — 멈춤")
                return f"{r} at {i + 1} {st['type']} {what}"
            if not self.f.alive():
                return f"dead at {i + 1} {st['type']} {what}"
        return "done"

    def _walk(self, st, tag) -> str:
        pts = [tuple(p) for p in st["pts"]]
        s = self.mv.snap(5.0)
        if s is not None and len(pts) > 1 and math.dist((s.player.x, s.player.y, s.player.z), pts[0]) < 1.0:
            pts = pts[1:]
        r = self.f.walk(pts, self.nm, f"{tag} 걷기", mode="sprint" if st.get("run") else "walk")
        if r == "dead":
            return "dead"
        s = self.mv.snap(5.0)
        d = None if s is None else math.dist((s.player.x, s.player.y, s.player.z), pts[-1])
        if d is not None and d > 2.0:
            self.log(f"   {tag} 걷기: {r}, 끝 점까지 {d:.1f} m")
            return "fail"
        return "ok"

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
        return "ok"

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
        control.focus_game()
        for k in st["keys"]:
            if k in BTN:
                self.mv.press(BTN[k], gap=MENU_GAP)
        self.log(f"   {tag} 메뉴 {' '.join(st['keys'])} ({st.get('label') or '?'})")
        return "ok"

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
        return "ok"
