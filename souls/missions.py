"""5층 — 임무. 어느 플레이북을 어떤 순서로 쓸지만 정한다. 싸우는 법·걷는 법은 아래 층.

임무 목록:
  burg_bonfire   불의 제전 → 경사로 무리 하나씩 → 계단 꼭대기 → 다리·통로 → 성벽 마을 → 상인 → 성벽 마을 화톳불에 불 붙이고 앉기
  clear_ramp     경사로 무리만 하나씩 (시험용)
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

import nav

from . import moves as M
from .field import Field

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
MAP_A, MAP_B = "m10_02_00_00", "m10_01_00_00"        # 불의 제전 쪽 / 성벽 마을 쪽 내비메시
SPOTS = json.loads((DATA / "spots.json").read_text(encoding="utf-8"))
FIRELINK = SPOTS["firelink-bonfire"]
FIRELINK_ID = 1022960                                  # 마지막 화톳불 ID (2026-09-24 실측, 불의 제전)
BURG_BONFIRE_ID = 1012962                              # 성벽 마을 화톳불 (2026-09-24 불 붙이고 앉아 확인)
BURG_BONFIRE = (3.2, -10.0, -61.2)                     # 성벽 마을 화톳불(o0200_0002) — 상인에서 동쪽 42 m, 10 m 위
BURG_BONFIRE_SIDE = (1.7, -10.02, -61.2)               # 그 옆 바닥
RAMP = json.loads((DATA / "enemy-map.json").read_text(encoding="utf-8"))["enemies"]   # 경사로 6마리, 쉰 직후 스폰 자리
# 경사로 아래 평지 — 반경 3 m 16방향 바닥이 다 있고 가장 가까운 낙차까지 4.0 m (hunt.py 실측). 낭떠러지 옆에서 싸우지 않고 여기서 맞이한다
RAMP_ARENA = (-30.0, -49.25, 29.0)
# 잡는 순서 (지도 번호). 2번 방패병은 맨 나중 — 자리가 너무 안 좋다 (서쪽 낭떠러지 + 위 턱 화염병, 사용자 2026-09-24:
# "두번째 공격하러 가는 얘를 맨 나중에 해봐", "거기 위치 너무 안 좋아"). 거기서 먼저 붙으면 1 s 에 275 를 맞거나 떨어졌다
RAMP_ORDER = [1, 3, 4, 5, 6, 2]


def _route():
    """사용자가 직접 걸어 녹화한 길 (2026-09-23): 계단 꼭대기 → 다리 높이 → 통로 → 경계 → 성벽 마을 → 상자 → 창고 방 → 상인."""
    run = json.loads((DATA / "routes" / "firelink-merchant-run.json").read_text(encoding="utf-8"))
    R = json.loads((DATA / "routes" / "passage-merchant.json").read_text(encoding="utf-8"))
    top = tuple(json.loads((DATA / "climb-goal.json").read_text(encoding="utf-8"))["top"])
    A = [tuple(q) for q in run["segments"][0]["points"]]
    return top, [top] + A[67:71] + [tuple(q) for q in R["a"]], R


class Missions:
    def __init__(self, fld: Field, nms: dict, log=print):
        self.f, self.nms, self.log = fld, nms, log
        self.mv: M.Moves = fld.mv

    # ── 조각 ─────────────────────────────────────────────────
    def start_fresh(self) -> bool:
        """불의 제전에서 쉬고 시작 (적 전부 부활, HP·에스트 가득)."""
        last = self.mv.tm.last_bonfire()
        if last != FIRELINK_ID:
            self.log(f"   ⚠ 마지막 화톳불이 불의 제전이 아님 ({last}) — 죽으면 거기서 깬다")
        ok = self.f.rest_at(self.nms[MAP_A], FIRELINK)
        self.log(f"── 불의 제전 휴식: {'됨' if ok else '실패'}")
        return ok

    def clear_ramp(self) -> str:
        targets = [dict(RAMP[i - 1], label=i) for i in RAMP_ORDER]
        r = self.f.clear(targets, self.nms[MAP_A], arena=RAMP_ARENA)
        self.log(f"── 경사로: {r}")
        return r

    def to_merchant(self) -> str:
        """상인까지. 지금 자리에서 가장 가까운 구간·점부터 이어 간다 — 통로(A) · 성벽 마을(B) · 창고 방(C).
        예전엔 A 구간만 보고 '멀다' 며 계단 꼭대기로 되돌아가 막혔다 (성벽 마을 안에서 시작, 2026-09-24)."""
        na, nb = self.nms[MAP_A], self.nms[MAP_B]
        top, route, R = _route()
        pb = [tuple(q) for q in R["b"]]
        pc = [tuple(q) for q in R["c"]]
        t0 = time.time()
        s = self.mv.snap(5.0)
        here = (s.player.x, s.player.y, s.player.z)
        seg, k, d = min(((name, j, math.dist(q, here)) for name, pts in (("A", route), ("B", pb), ("C", pc))
                         for j, q in enumerate(pts)), key=lambda t: t[2])
        self.log(f"   상인 길: 가장 가까운 곳 {seg}{k} ({d:.1f} m)")
        if d > 6.0:
            if seg == "A":
                r = self.f.walk_to(top, na, "꼭대기로")
                if r != "arrived":
                    return f"꼭대기까지 {r}"
                seg, k = "A", 0
            else:
                pts = pb if seg == "B" else pc
                r = self.f.walk_to(pts[k], nb, "길로")
                if r != "arrived":
                    return f"길까지 {r}"
        if seg == "A":
            r = self.f.walk(route[k:], na, "통로", tol=0.8)
            if r != "arrived":
                return f"통로 {r}"
            self.log(f"   경계 {time.time() - t0:.0f} s")
            seg, k = "B", 0
        if seg in ("B", "C"):
            self.f.home = pb[0]                            # 성벽 마을에선 입구 쪽으로 물러난다 (불의 제전까지는 이 내비메시로 경로가 없다 — no_path 헛돌기)
        if seg == "B":
            r = self.f.walk(pb[k:], nb, "성벽 마을", tol=0.8, tight=R["small_bridge"])
            if r != "arrived":
                return f"성벽 마을 {r}"
            if not self._roll_boxes(R["roll"]["from"], R["roll"]["to"]):
                return "상자 못 지나감"
            seg, k = "C", 0
        rest = pc[k:]
        for extra in range(3):
            r = self.f.walk(rest, nb, "창고 방", tol=0.8)
            if r != "stuck" or extra == 2:
                break
            # 남은 상자가 계단을 막고 있었다 (2026-09-23 스크린샷) — 다음 점 쪽으로 한 번 더 굴러 깬다
            s = self.mv.snap(5.0)
            j = min(range(len(pc)), key=lambda i: math.dist(pc[i], (s.player.x, s.player.y, s.player.z)))
            nxt = pc[min(j + 1, len(pc) - 1)]
            self.mv.roll_toward(s, nxt[0], nxt[2])
            rest = pc[j:]
        s = self.mv.snap(5.0)
        d = math.dist((s.player.x, s.player.y, s.player.z), tuple(R["stand"])) if s else None
        res = "도착" if r == "arrived" and d is not None and d < 2.5 else f"창고 방 {r} (상인까지 {d if d is None else round(d, 1)} m)"
        self.log(f"── 상인: {res} — {time.time() - t0:.0f} s")
        return res

    def _roll_boxes(self, frm, to, tries: int = 3) -> bool:
        """상자 더미를 굴러 깨며 지나간다 (사용자: "굴러서 깨면서 들어가는 게 좋아"). 시작점에 0.3 m 안으로 서고 구른다."""
        def past(sn) -> bool:
            return sn.player.y < frm[1] - 0.5 or math.dist((sn.player.x, sn.player.z), (to[0], to[2])) < 1.5
        for _ in range(tries):
            s = self.mv.snap(5.0)
            if s is None or s.cam_yaw is None:
                return False
            if past(s):
                return True
            nav.goto(self.mv.tm, self.mv.pad, tuple(frm), tolerance=0.3, timeout=5, log=lambda *a: None)
            self.mv.pad.neutral()
            time.sleep(0.15)
            s = self.mv.snap(5.0)
            self.mv.roll_toward(s, to[0], to[2])
            s = self.mv.snap(5.0)
            if s and past(s):
                return True
        return False

    def light_burg_bonfire(self) -> str:
        """성벽 마을 화톳불에 불 붙이고 앉는다: 처음 A = 불 붙이기(BONFIRE LIT), 다음 A = 앉기.
        성공 = 앉았고 마지막 화톳불 ID 가 불의 제전이 아니게 됨. B(일어나기)는 **앉아 있을 때만** 누른다 (아니면 백스텝)."""
        nb = self.nms[MAP_B]
        _, _, R = _route()
        self.f.home = tuple(R["b"][0])                     # 물러날 곳 = 성벽 마을 입구 (이 내비메시 안)
        r = self.f.walk_to(BURG_BONFIRE_SIDE, nb, "화톳불로")
        if r != "arrived":
            return f"화톳불까지 {r}"
        # 화톳불 옆 핏자국부터 (2026-09-24: 여기서 죽어 소울 740) — 어차피 앉을 화톳불이라 A 가 앉기로 들어가도 괜찮다
        b = self.f.pick_blood(nb, near=10.0, bonfire_ok=True)
        if b:
            self.log(f"   핏자국: {b}")
        s = self.mv.snap(15.0)
        if s and not self.f.safe(s):
            self.f.shake_off("화톳불 앞 적")               # 적이 가까우면 불도 못 붙이고 앉지도 못한다
        s = self.mv.snap(5.0)
        if s and s.cam_yaw is not None:                     # 화톳불 쪽을 본다
            self.mv.pad.move(*self.mv.stick_to(s, BURG_BONFIRE[0], BURG_BONFIRE[2], 0.45))
            time.sleep(0.18)
            self.mv.pad.move(0.0, 0.0)
            time.sleep(0.5)
        tm = self.mv.tm
        before = tm.last_bonfire()
        sat = False
        for _ in range(3):
            self.mv.press(M.B.XUSB_GAMEPAD_A)
            t0 = time.time()
            while time.time() - t0 < 6.0 and not tm.sitting():
                time.sleep(0.25)
            if tm.sitting():
                sat = True
                break
        time.sleep(1.0)
        after = tm.last_bonfire()
        for _ in range(6):
            if not (tm.sitting() or tm.menu_open()):
                break
            self.mv.press(M.B.XUSB_GAMEPAD_B)
            time.sleep(1.0)
        ok = sat and after is not None and after != FIRELINK_ID
        self.log(f"── 성벽 마을 화톳불: 앉음 {sat}, 마지막 화톳불 {before} → {after} — {'귀환 지점 바뀜' if ok else '확인 못 함'}")
        return "lit" if ok else f"실패 (앉음 {sat}, {before}→{after})"

    # ── 임무 ─────────────────────────────────────────────────
    def burg_bonfire(self) -> str:
        if not self.f.alive():
            self.f.wait_respawn()
        if not self.start_fresh():
            return "휴식 실패"
        r = self.clear_ramp()
        if r != "cleared":
            return f"경사로 {r}"
        r = self.to_merchant()
        if r != "도착":
            return f"상인 {r}"
        return self.light_burg_bonfire()
