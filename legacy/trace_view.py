"""
위치 기록(data/trace/*.jsonl) 을 위에서 본 지도로 — 사용자: "몹들과 캐릭터 위치를 1초 단위로 저장해서 나중에 리뷰".

  python trace_view.py data/trace/hunt_....jsonl [--from 40 --to 90]   → 같은 이름 .png

바닥: 내비메시 높이 (검정 = 바닥 없음/낭떠러지, 밝을수록 높음). 파랑 = 나(1 s 점, 방패를 든 점은 테두리),
빨강 계열 = 지도 적(번호), 노랑 × = 맞은 곳(크기 ∝ 피해), 초록 원 = ARENA.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import merchantrun as mr
import navmesh

ROOT = Path(__file__).resolve().parent
X0, X1, Z0, Z1 = -42.0, -8.0, 4.0, 38.0      # 불의 제전 경사로 무리 둘레
PX = 24                                    # 1 m = 24 px
Y_LO, Y_HI = -52.0, -36.0
COLORS = {"1": (230, 60, 60), "2": (255, 140, 0), "3": (200, 40, 160), "4": (150, 90, 255), "5": (0, 170, 170), "6": (120, 200, 60)}


def to_px(x, z):
    return (x - X0) * PX, (Z1 - z) * PX            # 위 = +z


def floor_layer(nm) -> Image.Image:
    w, h = int((X1 - X0) * PX), int((Z1 - Z0) * PX)
    img = Image.new("RGB", (w, h), (0, 0, 0))
    px = img.load()
    step = 0.25
    zz = Z0
    while zz < Z1:
        xx = X0
        while xx < X1:
            best = None
            for yref in (-49.5, -44.0, -39.5, -35.0):
                f = nm.floor_at(xx, zz, yref)
                if f is not None and (best is None or f[0] > best):
                    best = f[0]
            if best is not None:
                v = int(60 + 150 * max(0.0, min(1.0, (best - Y_LO) / (Y_HI - Y_LO))))
                x0, y0 = to_px(xx, zz + step)
                for dx in range(int(step * PX)):
                    for dy in range(int(step * PX)):
                        a, b = int(x0) + dx, int(y0) + dy
                        if 0 <= a < w and 0 <= b < h:
                            px[a, b] = (v, v, v)
            xx += step
        zz += step
    return img


def main() -> None:
    args = sys.argv[1:]
    path = Path(args[0])
    t_from = float(args[args.index("--from") + 1]) if "--from" in args else -1e9
    t_to = float(args[args.index("--to") + 1]) if "--to" in args else 1e9
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    nm = navmesh.Navmesh(mr.MAP_A)
    cache = ROOT / "data" / "trace" / "_floor.png"
    if cache.exists():
        img = Image.open(cache).convert("RGB")
    else:
        img = floor_layer(nm)
        img.save(cache)
    dr = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("malgun.ttf", 14)
    except OSError:
        font = ImageFont.load_default()
    import hunt
    ax, az = hunt.ARENA[0], hunt.ARENA[2]
    cx, cy = to_px(ax, az)
    dr.ellipse((cx - 1.5 * PX, cy - 1.5 * PX, cx + 1.5 * PX, cy + 1.5 * PX), outline=(0, 220, 0), width=2)
    for i, e in enumerate(hunt.MAP, 1):
        sx, sy = to_px(e["pos"][0], e["pos"][2])
        dr.rectangle((sx - 4, sy - 4, sx + 4, sy + 4), outline=COLORS.get(str(i), (255, 255, 255)), width=2)
        dr.text((sx + 6, sy - 8), f"#{i}", fill=COLORS.get(str(i), (255, 255, 255)), font=font)
    pos_rows = [r for r in rows if "me" in r and t_from <= r["t"] <= t_to]
    prev = {}
    for r in pos_rows:
        me = r["me"]
        x, y = to_px(me[0], me[2])
        if "me" in prev:
            dr.line((*prev["me"], x, y), fill=(60, 140, 255), width=2)
        dr.ellipse((x - 3, y - 3, x + 3, y + 3), fill=(60, 140, 255), outline=(255, 255, 255) if me[7] else None)
        prev["me"] = (x, y)
        for k, v in r["e"].items():
            if k.startswith("?") or v[4] <= 0:
                continue
            ex, ey = to_px(v[0], v[2])
            col = COLORS.get(k, (255, 255, 255))
            if k in prev:
                dr.line((*prev[k], ex, ey), fill=col, width=1)
            dr.ellipse((ex - 2, ey - 2, ex + 2, ey + 2), fill=col)
            prev[k] = (ex, ey)
    # 맞은 곳 — 이벤트 직전 1 s 위치
    for ev in (r for r in rows if r.get("ev") == "hit" and t_from <= r["t"] <= t_to):
        before = [r for r in pos_rows if r["t"] <= ev["t"]]
        if not before:
            continue
        me = before[-1]["me"]
        x, y = to_px(me[0], me[2])
        s = 3 + min(14, ev["dmg"] / 25)
        dr.line((x - s, y - s, x + s, y + s), fill=(255, 230, 0), width=3)
        dr.line((x - s, y + s, x + s, y - s), fill=(255, 230, 0), width=3)
        if ev["dmg"] >= 60:
            dr.text((x + s + 2, y - 7), f"{ev['dmg']} t{ev['t']:.0f}", fill=(255, 230, 0), font=font)
    phases = []
    for r in pos_rows:
        if not phases or phases[-1][1] != r["phase"]:
            phases.append((r["t"], r["phase"]))
    dr.text((8, 8), path.name + "  |  " + "  ".join(f"{t:.0f}s {p}" for t, p in phases), fill=(255, 255, 255), font=font)
    out = path.with_suffix(".png")
    img.save(out)
    print(out)


if __name__ == "__main__":
    main()
