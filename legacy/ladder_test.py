"""사다리 오르내리기 실측 — 사용자: "사다리 오르는 거 해 보자".

  BOT_GAME=dsr python ladder_test.py go-burg     성벽 마을 계단 꼭대기 층계참 서쪽 사다리 위까지 걸어간다 (적이 못 보게)
  BOT_GAME=dsr python ladder_test.py scan        8 방향으로 돌며 화면 아래 안내창에 글자가 뜨는 쪽을 찾아 그쪽을 보고 스크린샷 (A 안 누름)
  BOT_GAME=dsr python ladder_test.py down|up     A 한 번 → 스틱 아래/위 → 모션·높이 기록, 끝에서 스크린샷
  BOT_GAME=dsr python ladder_test.py flags-off   플래그 끄기 (화톳불 옆에서만)

사다리 자리: 내비메시 'Ladder'(1024) 삼각형 쌍. 불의 제전 맵 계단 꼭대기 옆(아래 -39.25/위 -30.8)은 내비메시엔 있지만
게임엔 사다리가 없다 (8 방향 모두 안내 없음, 사용자 확인 "사다리 안 보여").
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import vgamepad
from PIL import ImageGrab

import control
import env
import nav
import navmesh
import vision_probe as vp

ROOT = Path(__file__).resolve().parent
LADDERS = {
    # 이름: (아래 칸, 위 칸) — 사다리 삼각형 쌍의 가운데
    "burg": ((-71.87, -28.87, -24.95), (-72.33, -23.07, -24.23)),
    # 성벽 마을 화톳불 방 사다리 (사용자: "화톳불 방에 사다리 있음") — 화톳불(3.2, -10, -61.2)에서 6 m
    "burg_fire": ((-2.97, -10.02, -62.79), (-3.47, -0.27, -63.62)),
}


def shot(name: str) -> str:
    ImageGrab.grab(bbox=vp.window_rect()).convert("RGB").save(vp.IMG_DIR / name, quality=88)
    return name


def prompt_px() -> int:
    """화면 아래 가운데 안내창('A: …') 이 떴나 — 안내창은 거의 검은 틀이라 어두운 픽셀 비율로 본다 (×1000).
    실측: 안내 있음 900~920, 없음 590~710 (밝은 글자 수로 재면 배경 빛에 흔들려 못 썼다)."""
    x0, y0, x1, y1 = vp.window_rect()
    w, h = x1 - x0, y1 - y0
    im = ImageGrab.grab(bbox=(x0 + int(0.30 * w), y0 + int(0.80 * h), x0 + int(0.70 * w), y0 + int(0.86 * h))).convert("L")
    a = np.asarray(im)
    dark = int(1000 * float((a < 40).mean()))
    # 어두운 방(수용소 오스카 방)에선 안내가 없어도 어두움 902 — 안내창엔 흰 글자가 있다 (밝은 글자 픽셀이 있어야 인정)
    return dark if int((a > 200).sum()) >= 60 else min(dark, 700)


PROMPT_ON = 820


def face(tm, pad, d, mag=0.45, t=0.18) -> None:
    s = tm.snapshot(within=3.0)
    st = control.world_to_stick(d[0], d[1], s.cam_yaw, nav.YAW_OFFSET, nav.FLIP_X)
    pad.move(mag * st[0], mag * st[1])
    time.sleep(t)
    pad.move(0.0, 0.0)
    time.sleep(0.4)


def press_a(pad) -> None:
    pad.tap(vgamepad.XUSB_BUTTON.XUSB_GAMEPAD_A, 0.1)
    time.sleep(0.15)
    pad.release_due()


def watch(tm, pad, stick, secs, until=None):
    """스틱을 민 채 모션·높이를 적는다 → [(t, y, anim)]. until(snapshot) 가 참이면 멈춘다."""
    rows, t0 = [], time.time()
    while time.time() - t0 < secs:
        if stick is not None:
            pad.move(*stick)
        s = tm.snapshot(within=3.0)
        if s:
            r = (round(time.time() - t0, 2), round(s.player.y, 2), s.player.anim)
            if not rows or rows[-1][1:] != r[1:]:
                rows.append(r)
            if until is not None and until(s):
                break
        time.sleep(0.03)
    pad.move(0.0, 0.0)
    return rows


def main() -> None:
    import legacy.merchantrun as mr           # scan·down·up·flags-off·prompt_px() 는 안 씀 — CLI 시험용(go-burg 등)만 필요
    sys.stdout.reconfigure(encoding="utf-8")
    what = sys.argv[1] if len(sys.argv) > 1 else "scan"
    name = sys.argv[2] if len(sys.argv) > 2 else "burg"
    bottom, top = LADDERS[name]
    tm = env.make_telemetry({})
    pad = control.Pad()
    pad.reconnect()
    control.focus_game()
    flags = (tm.DBG_PLAYER_NO_DEAD, tm.DBG_PLAYER_HIDE, 0xB)
    if what == "go-burg":
        for o in flags:
            tm.set_dbg(o, True)
        na, nb = navmesh.Navmesh(mr.MAP_A), navmesh.Navmesh(mr.MAP_B)
        R = json.loads((ROOT / "data" / "routes" / "passage-merchant.json").read_text(encoding="utf-8"))
        climb_top = tuple(json.loads((ROOT / "data" / "climb-goal.json").read_text(encoding="utf-8"))["top"])
        s = tm.snapshot(within=5.0)
        here = (s.player.x, s.player.y, s.player.z)
        p1 = nav.trim_path((na.find_path(here, climb_top) or [climb_top])[1:], climb_top)
        print("꼭대기로:", nav.follow(tm, pad, p1, terrain=na, mode_fn=lambda _s: "walk", default_tol=0.8, log=lambda *a: None), flush=True)
        rec = [tuple(q) for q in R["top_bridge"] + R["a"]] + [tuple(q) for q in R["b"][:23]]
        tols_ok = nav.follow(tm, pad, rec, terrain=None, mode_fn=lambda _s: "walk", default_tol=0.8, log=lambda *a: None)
        print("층계참까지:", tols_ok, flush=True)
        if tols_ok != "arrived":
            # 여기서 '못 감' 인데도 성벽 마을 맵 경로를 불의 제전 맵 자리에서 따라가다 다리 밖으로 걸어 나가 떨어졌다 (y -175)
            pad.neutral()
            print("층계참까지 못 감 — 멈춤")
            return
        s = tm.snapshot(within=5.0)
        p3 = nb.find_path((s.player.x, s.player.y, s.player.z), top)
        print("사다리 위로:", nav.follow(tm, pad, [tuple(q) for q in p3[1:]] + [top], terrain=None, mode_fn=lambda _s: "walk",
                                        default_tol=0.6, log=lambda *a: None), flush=True)
        nav.goto(tm, pad, top, tolerance=0.3, timeout=6, log=lambda *a: None, mode_fn=lambda _s: "walk")
        pad.neutral()
        s = tm.snapshot(within=5.0)
        print(f"사다리 위 칸까지 {math.dist((s.player.x, s.player.y, s.player.z), top):.2f} m — 스크린샷 {shot('ladder_burg_top.jpg')}")
    elif what == "go-bottom":
        # 같은 층에서 사다리 아래 칸으로만 — 다른 층·다른 맵 경로를 이어 따라가지 않는다 (다리에서 떨어진 사고)
        nb = navmesh.Navmesh(mr.MAP_B)
        s = tm.snapshot(within=5.0)
        here = (s.player.x, s.player.y, s.player.z)
        if abs(here[1] - bottom[1]) > 1.5 or math.dist(here, bottom) > 20.0:
            print(f"사다리 아래와 층이 다르거나 멀다 ({math.dist(here, bottom):.1f} m, 높이차 {here[1] - bottom[1]:+.1f}) — 안 감")
            return
        path = [tuple(q) for q in (nb.find_path(here, bottom) or [])[1:]] + [bottom]
        r = nav.follow(tm, pad, path, terrain=None, mode_fn=lambda _s: "walk", default_tol=0.5, log=lambda *a: None)
        nav.goto(tm, pad, bottom, tolerance=0.3, timeout=6, log=lambda *a: None, mode_fn=lambda _s: "walk")
        pad.neutral()
        s = tm.snapshot(within=5.0)
        print(f"사다리 아래: {r}, {math.dist((s.player.x, s.player.y, s.player.z), bottom):.2f} m — 스크린샷 {shot(f'ladder_{name}_bottom.jpg')}")
    elif what == "scan":
        time.sleep(0.8)
        best = None
        for k in range(8):
            a = k * math.pi / 4
            d = (math.sin(a), math.cos(a))
            face(tm, pad, d)
            n = prompt_px()
            s = tm.snapshot(within=3.0)
            print(f"  방향 {k} (dx {d[0]:+.2f}, dz {d[1]:+.2f}) → 안내 글자 {n}", flush=True)
            if best is None or n > best[0]:
                best = (n, k, d)
        face(tm, pad, best[2])
        print("가장 밝은 쪽", best, "스크린샷", shot(f"ladder_{name}_scan.jpg"))
    elif what in ("down", "up"):
        s0 = tm.snapshot(within=3.0)
        press_a(pad)
        rows = watch(tm, pad, None, 2.0)                    # 사다리에 붙는 모션
        goal = bottom[1] if what == "down" else top[1]
        stick = (0.0, -1.0) if what == "down" else (0.0, 1.0)
        rows += watch(tm, pad, stick, 20.0,
                      until=lambda s: s.player.anim == -1 and abs(s.player.y - goal) < 0.6 and time.time() > 0)
        s = tm.snapshot(within=3.0)
        print(f"{what}: y {s0.player.y:.2f} → {s.player.y:.2f} (목표 {goal}), 모션 {rows}")
        print("스크린샷", shot(f"ladder_{name}_{what}.jpg"))
        (ROOT / "data" / "trace" / f"ladder_{name}_{what}_{time.strftime('%H%M%S')}.json").write_text(json.dumps(rows), encoding="utf-8")
    elif what == "flags-off":
        s = tm.snapshot(within=5.0)
        if math.dist((s.player.x, s.player.y, s.player.z), tuple(mr.BONFIRE["stand"])) < 12.0:
            for o in flags:
                tm.set_dbg(o, False)
        print("플래그", [tm.get_dbg(o) for o in flags])
    pad.neutral()


if __name__ == "__main__":
    main()
