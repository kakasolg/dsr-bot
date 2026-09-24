"""캐릭터가 오래 서 있으면 화면을 찍는다 — 봇과 같이 띄우는 읽기 전용 감시 (메모리 읽기 + 스크린샷만, 입력 없음).

사용자: "캐릭터가 너무 멈춰 있으면, 스크린샷 찍고, 비교해줘."
STILL_S 초 동안 STILL_M m 안에서만 움직였으면 data/vision/stall_HHMMSS.jpg 를 남기고,
가장 가까운 사용자 체크포인트 사진(data/passage-entry.json marks)과 상인 경로(data/routes/passage-merchant.json) 위치를 같이 적는다.

  BOT_GAME=dsr python stall_watch.py [--minutes 20]
"""
from __future__ import annotations

import json
import math
import sys
import time
from collections import deque
from pathlib import Path

from PIL import ImageGrab

import env
import merchantrun as mr
import vision_probe as vp

ROOT = Path(__file__).resolve().parent
STILL_S = 10.0
STILL_M = 0.8
COOLDOWN_S = 20.0


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    minutes = float(sys.argv[sys.argv.index("--minutes") + 1]) if "--minutes" in sys.argv else 20.0
    tm = env.make_telemetry({})
    marks = json.loads((ROOT / "data" / "passage-entry.json").read_text(encoding="utf-8")).get("marks", [])
    R = json.loads((ROOT / "data" / "routes" / "passage-merchant.json").read_text(encoding="utf-8"))
    route = [(k, i, tuple(q)) for k in ("a", "b", "c") for i, q in enumerate(R[k])]
    bonfire = tuple(mr.BONFIRE["stand"])
    hist: deque = deque()
    last_shot = 0.0
    t_end = time.time() + minutes * 60
    print(f"감시 시작 — {STILL_S:.0f} s 동안 {STILL_M} m 안이면 찍는다 ({minutes:.0f} 분)", flush=True)
    while time.time() < t_end:
        time.sleep(0.5)
        s = tm.snapshot(within=6.0)
        if s is None or s.player.hp is None:
            hist.clear()
            continue
        p = s.player
        now = time.time()
        pos = (p.x, p.y, p.z)
        hist.append((now, pos))
        while hist and now - hist[0][0] > STILL_S:
            hist.popleft()
        if p.hp <= 0 or now - hist[0][0] < STILL_S - 0.6 or now - last_shot < COOLDOWN_S:
            continue
        if math.dist(pos, bonfire) < 10.0:
            continue                                      # 화톳불 앞에서 쉬거나 기다리는 건 멈춤이 아니다 (다크사인 도착 자리는 8.3 m)
        spread = max(math.dist(pos, q) for _, q in hist)
        if spread > STILL_M:
            continue
        last_shot = now
        name = f"stall_{time.strftime('%H%M%S')}.jpg"
        try:
            ImageGrab.grab(bbox=vp.window_rect()).convert("RGB").save(vp.IMG_DIR / name, quality=90)
        except Exception as e:                            # 창을 못 찾으면 위치만 남긴다
            name = f"(스크린샷 실패: {e})"
        mk = min(marks, key=lambda m: math.dist(m["pos"], pos)) if marks else None
        seg, idx, q = min(route, key=lambda r: math.dist(r[2], pos))
        foes = sorted((c for c in s.hostile(6.0) if c.hp > 0), key=lambda c: c.dist)
        print(json.dumps({
            "t": time.strftime("%H:%M:%S"), "shot": name, "pos": [round(v, 2) for v in pos], "heading": round(p.heading, 2),
            "hp": p.hp, "anim": p.anim, "still_s": STILL_S, "spread": round(spread, 2),
            "route": f"{seg}[{idx}]", "route_d": round(math.dist(q, pos), 2),
            "mark": mk and mk["shot"], "mark_d": mk and round(math.dist(mk["pos"], pos), 1), "mark_note": mk and mk.get("note"),
            "foes": [[c.npc_param, round(c.dist, 1), c.anim] for c in foes[:3]],
        }, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
