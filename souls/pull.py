"""Body pull — wake one foe by walking just into its notice range, then run back ([MoKa] 2026-10-11).

  "불의 제사장 구역에서는 투척 나이프나 화염병이 없는 상태임 … 그 전에는 하나씩 순차적으로 처리 해야 하고 플레이어는 감각적으로
   투척 나이프 없이도 대략적인 상대가 캐릭터가 어느 정도 움직이면 끌려 오니깐 하나만 나를 인지하게 해서 유인을 하는데 이 과정이
   지금 없는 것 같음."

Pure parts (tests/pull_test.py); Field.notice_pull walks it:
  notice_r()  how close a foe lets us come before it notices — data/notice.json (experiments/notice_probe.py on the recorded
              runs: shield soldiers ~9 m, burg hollows ~7.5 m, ramp hollows ~5 m), DEFAULT_R for a foe not in it
  plan()      the stretch of the path to the target we may walk: it ends where we would come within notice_r + MARGIN of
              another calm foe (that one would wake too) or MIN_R of the target
  Watch       has the target noticed us? anim / moved → it is coming (run back); body turned to us → stop stepping and watch
              (on the records only 15 of 104 such turns were followed by the foe coming — a turn alone is not a wake)
"""
from __future__ import annotations

import json
import math
from pathlib import Path

TABLE_PATH = Path(__file__).resolve().parent.parent / "data" / "notice.json"
DEFAULT_R = 8.0        # notice distance for a foe the table doesn't know (median of the table)
MIN_N = 3              # a table row (per side) needs this many events, else the foe's "all" row
MARGIN = 1.0           # keep this much outside another calm foe's notice distance
MIN_R = 3.0            # never step closer than this to a calm target (the Asylum sleeper strikes at 1.2 m as it wakes)
STEP = 0.7             # inside notice_r + NEAR: walk this far, then …
LOOK_S = 0.3           # … stand this long watching
NEAR = 2.5             # stepping starts this far outside the target's notice distance; before that, plain walking
WAIT_S = 2.0           # at the end of the plan (or after a turn), stand guarding this long for it to come
CALM_M = 0.7           # the target moved this far from where it stood → awake (notice_probe CALM_M)
TURN_FROM, TURN_TO = 45.0, 25.0
NEAR_BACK_R = 4.0      # an awake foe this close → don't turn our back to run (P-45: hit three times running 2 m from the spot)
DY_MAX = 3.0           # foes more than this above / below are another level — left out


def load_table(path: Path = TABLE_PATH) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("table", {})
    except Exception:
        return {}


def facing(heading, cx, cz, mx, mz) -> float | None:
    """Angle (deg) between a character's forward and the direction to (mx, mz): 0 = looking at it. forward = (−sin h, −cos h)
    (checked on 3,042 moving-foe frames, notice_probe)."""
    if heading is None:
        return None
    fx, fz = -math.sin(heading), -math.cos(heading)
    dx, dz = mx - cx, mz - cz
    n = math.hypot(dx, dz) or 1e-6
    return math.degrees(math.acos(max(-1.0, min(1.0, (fx * dx + fz * dz) / n))))


def side(f: float | None) -> str:
    return "?" if f is None else "front" if f < 60 else "side" if f < 120 else "back"


def notice_r(table: dict, npc, face_deg: float | None = None) -> float:
    row = table.get(str(npc)) or {}
    r = row.get(side(face_deg)) or {}
    if r.get("n", 0) < MIN_N:
        r = row.get("all") or {}
    return float(r["d"]) if r.get("n", 0) >= MIN_N else DEFAULT_R


def _resample(path: list, step: float) -> list:
    out = [tuple(path[0])]
    for a, b in zip(path, path[1:]):
        d = math.dist(a, b)
        k = 1
        while k * step < d:
            t = k * step / d
            out.append(tuple(a[i] + (b[i] - a[i]) * t for i in range(3)))
            k += 1
        out.append(tuple(b))
    return out


def plan(path: list, target, others: list, rt: float) -> tuple[list, str, float]:
    """path: points from us to the target. target (x, y, z). others: [(x, y, z, r)] calm foes with their notice distance.
    → (points to walk, why it ends: 'min_r' | 'other' | 'end', distance from the last point to the target).
    The target is expected to notice us once that distance ≤ rt."""
    if not path:
        return [], "end", float("inf")
    pts = _resample(path, 0.25)
    keep, why = [], "end"
    for q in pts:
        if math.hypot(q[0] - target[0], q[2] - target[2]) < MIN_R:
            why = "min_r"
            break
        if any(math.hypot(q[0] - o[0], q[2] - o[2]) < o[3] + MARGIN and abs(q[1] - o[1]) <= DY_MAX for o in others):
            why = "other"
            break
        keep.append(q)
    last = keep[-1] if keep else tuple(path[0])
    return keep, why, math.hypot(last[0] - target[0], last[2] - target[2])


def split(points: list, target, rt: float) -> tuple[list, list]:
    """→ (walk straight through, stops): stopping starts NEAR outside rt, one stop every STEP m and one at the end."""
    far, near = [], []
    for q in points:
        if not near and math.hypot(q[0] - target[0], q[2] - target[2]) > rt + NEAR:
            far.append(q)
        else:
            near.append(q)
    stops, acc, last = [], 0.0, (far[-1] if far else (near[0] if near else None))
    for q in near:
        acc += math.dist(q, last)
        last = q
        if acc >= STEP - 1e-6:
            stops.append(q)
            acc = 0.0
    if near and (not stops or stops[-1] != near[-1]):
        stops.append(near[-1])
    return far, stops


class Watch:
    """Has the target noticed us? update(c, me, now) → 'anim' | 'move' (it is coming) · 'turn' (looked at us) · None."""

    def __init__(self, c):
        self.x, self.z = c.x, c.z
        self.face0 = None
        self.turn_t = None

    def update(self, c, me, now: float) -> str | None:
        a = c.anim
        if a not in (None, -1) and not (9000 <= a < 9100):
            return "anim"
        if math.hypot(c.x - self.x, c.z - self.z) > CALM_M:
            return "move"
        f = facing(getattr(c, "heading", None), c.x, c.z, me[0], me[2])
        if f is None:
            return None
        if self.face0 is None:
            self.face0 = f
        if self.face0 > TURN_FROM and f < TURN_TO:
            return "turn"
        return None
