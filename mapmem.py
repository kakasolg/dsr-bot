"""
기억하는 지도 — 다크소울은 지도를 안 주니 봇이 걸어 본 자리를 스스로 기억한다.

  python mapmem.py record <이름>              사람/봇이 걷는 동안 5 Hz 로 좌표를 0.5 m 격자에 찍는다 (Ctrl+C 로 끝, 매 20 점마다 저장)
  python mapmem.py scan <이름> [반경] [간격]   자율주행차 스캔 방식 — 무적 상태로 현재 위치 주변을 격자 순간이동하며
                                              중력으로 바닥 높이를 잰다 (걷지 않고 지형을 먼저 통째로 파악).
                                              warp 가능한(롤부셀 이후) 캐릭터로 화톳불에 서서 실행. 반경 기본 25m, 간격 기본 1m.
  python mapmem.py render <이름> [out.html]   높이를 색으로 칠한 지형도 HTML (사람이 보는 용도)
  python mapmem.py stats <이름>               칸 수·범위

저장: data/maps/<이름>.json  {"cell": 0.5, "cells": {"x,z": {"y": 높이, "n": 방문 수, "wall": ["N","E",..]}}}
  · 칸 = 갈 수 있는 자리. 높이(y)는 평균 — 이웃 칸과 1.5 m 넘게 차이 나면 연결 안 함 (층·절벽)
  · wall = 그 방향으로 밀었는데 안 움직인 기록 (봇의 막힘 감지가 채운다)
길찾기(A*)는 nav 쪽에서 이 격자를 읽어 쓴다 (다음 단계).

scan 의 한계: 수직으로 떨어뜨려 바닥만 재는 방식이라 기둥 같은 얇은 수직 장애물은 못 잡는다 (그 자리 바닥은 잡힘).
가로 막힘은 여전히 record 의 wall 기록(실제로 걸으며 부딪힌 기록)이나 나중의 진짜 레이캐스트가 맡는다.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
MAPS = ROOT / "data" / "maps"
CELL = 0.5


class MapMemory:
    def __init__(self, name: str):
        self.path = MAPS / f"{name}.json"
        self.cells: dict[str, dict] = {}
        if self.path.exists():
            self.cells = json.loads(self.path.read_text(encoding="utf-8")).get("cells", {})

    @staticmethod
    def key(x: float, z: float) -> str:
        return f"{int(x // CELL)},{int(z // CELL)}"

    def visit(self, x: float, y: float, z: float) -> bool:
        """칸을 방문 처리. 새 칸이면 True."""
        k = self.key(x, z)
        c = self.cells.get(k)
        if c is None:
            self.cells[k] = {"y": round(y, 2), "n": 1}
            return True
        c["y"] = round((c["y"] * c["n"] + y) / (c["n"] + 1), 2)
        c["n"] += 1
        return False

    def wall(self, x: float, z: float, direction: str) -> None:
        k = self.key(x, z)
        c = self.cells.setdefault(k, {"y": 0.0, "n": 0})
        c.setdefault("wall", [])
        if direction not in c["wall"]:
            c["wall"].append(direction)

    def save(self) -> None:
        MAPS.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"cell": CELL, "cells": self.cells}, ensure_ascii=False), encoding="utf-8")

    def stats(self) -> str:
        if not self.cells:
            return "빈 지도"
        xs = [int(k.split(",")[0]) for k in self.cells]
        zs = [int(k.split(",")[1]) for k in self.cells]
        ys = [c["y"] for c in self.cells.values()]
        return (f"칸 {len(self.cells)} (≈{len(self.cells) * CELL * CELL:.0f} m²)  x {min(xs) * CELL:.0f}..{max(xs) * CELL:.0f}  "
                f"z {min(zs) * CELL:.0f}..{max(zs) * CELL:.0f}  y {min(ys):.0f}..{max(ys):.0f}  벽 기록 {sum(1 for c in self.cells.values() if c.get('wall'))}")


def record(name: str) -> None:
    import env
    tm = env.make_telemetry({})
    mm = MapMemory(name)
    print(f"탐색 기록 시작: {name} — {mm.stats()}. 걸으세요. Ctrl+C 로 끝", flush=True)
    new = 0
    try:
        while True:
            s = tm.snapshot(within=1.0)
            if s and s.player.gx is not None and s.player.hp > 0:
                if mm.visit(s.player.gx, s.player.gy, s.player.gz):
                    new += 1
                    if new % 20 == 0:
                        mm.save()
                        print(f"  +{new} 칸  ({s.player.gx:.1f}, {s.player.gy:.1f}, {s.player.gz:.1f})  {mm.stats()}", flush=True)
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    mm.save()
    print(f"저장: {mm.path}  {mm.stats()}")


def scan(name: str, radius: float = 25.0, step: float = 1.0, drop: float = 2.0, max_wait: float = 1.8,
         budget: int = 4000) -> None:
    """무적 상태로 지형을 순간이동하며 바닥 높이를 잰다 (자율주행차식 사전 스캔).

    **넓이 우선 탐색**: 중심에서 시작해 바닥을 찾은 칸의 이웃만 큐에 넣는다. 허공은 거기서 멈춘다 —
    격자를 통째로 훑으면 절벽 바깥 허공에 시간을 다 쓴다 (실측: 바닥 0.77 s/점 vs 허공 2.5 s/점).
    각 칸의 기준 높이는 **그 칸을 큐에 넣은 이웃이 착지한 높이** — 계단·경사를 자연스럽게 따라간다.
    이웃보다 MAX_STEP_DOWN 넘게 아래에 착지하면 절벽으로 보고 기록만 하고 퍼지지 않는다 — 안 그러면 절벽 아래
    (불의 제전 기준 85 m 밑 신 론도)까지 타고 내려가 서로 못 걸어가는 두 지역이 한 지도에 섞인다 (실측).

    각 점: 기준+drop 으로 워프 → 떨어뜨림 → 높이가 안정되면 바닥으로 기록.
    실측(불의 제전): 워프 반영 0.12 s, 낙하 첫 0.25 s 는 0.2 m 밖에 안 움직인다 → 이 구간을 "정지=착지"로 보면 안 된다
    (SETTLE_LAG 동안 판정 안 함). 지형 안에 갇혀 아예 안 떨어진 경우를 거르려고 최소 낙하량도 본다.

    ── 반드시 지켜야 하는 것 ─────────────────────
    워프는 위치만 바꾸고 **낙하 속도는 그대로 둔다**. 허공을 프로브한 뒤엔 빠르게 떨어지는 상태라, 그 속도로
    다음 점(바닥 2 m 위)에 놓으면 다음 물리 프레임에 바닥을 뚫는다. 실측: 이걸 안 하고 돌렸더니 캐릭터가
    y −60 → −630 까지 떨어져 죽었다. → 허공 뒤에는 settle() 로 실제 착지시켜 속도를 0 으로 되돌린다.
    """
    import env
    from collections import deque
    tm = env.make_telemetry({})
    if not hasattr(tm, "set_hp") or not hasattr(tm, "pos_warp"):
        print("이 게임 텔레메트리는 스캔(무적/워프)을 지원하지 않음"); return
    SETTLE_LAG, STABLE_N, STABLE_EPS, MIN_FALL = 0.30, 3, 0.04, 0.15
    MAX_STEP_DOWN = 3.0   # 이웃 칸이 이보다 많이 내려가면 "걸어갈 수 있는 바닥"이 아니라 절벽(낙사) — 거기서 더 퍼지지 않는다
    mm = MapMemory(name)
    s0 = tm.snapshot(within=1.0)
    if not s0 or s0.player.gx is None:
        print("캐릭터 위치를 못 읽음 — 게임에서 스캔할 자리에 서 있는지 확인"); return
    if getattr(tm, "sitting", lambda: False)():
        print("앉아 있는 상태 — 워프하면 캐릭터가 굳는다. 먼저 일어나세요"); return
    cx, cy0, cz, max_hp = s0.player.gx, s0.player.gy, s0.player.gz, s0.player.max_hp
    time.sleep(0.4)
    s1 = tm.snapshot(within=1.0)
    if not s1 or s1.player.gy is None or abs(s1.player.gy - cy0) > 0.1:
        print("캐릭터가 지금 떨어지는 중 — 땅에 선 뒤 다시 실행"); return

    def pos():
        pp = tm.player_ptr()
        mapd = tm.q(pp + 0x68) if pp else None
        posd = tm.q(mapd + 0x28) if mapd else None
        return (tm.f32(posd + 0x10), tm.f32(posd + 0x14), tm.f32(posd + 0x18)) if posd else (None, None, None)

    def settle(x, y, z, tries: int = 3) -> bool:
        """낙하 속도를 지운다 — 같은 자리에 연속으로 워프해 붙들어 두고, 지면에 닿아 멈추는 걸 확인한다."""
        for _ in range(tries):
            for _ in range(6):
                tm.set_hp(max_hp)
                tm.pos_warp(x, y + 0.5, z, 0.0)
                time.sleep(0.04)
            t0, hist = time.time(), []
            while time.time() - t0 < 1.2:
                time.sleep(0.04)
                tm.set_hp(max_hp)
                _, cur, _ = pos()
                if cur is None:
                    continue
                hist.append(cur)
                del hist[:-STABLE_N]
                if len(hist) == STABLE_N and max(hist) - min(hist) < STABLE_EPS:
                    return True
        return False

    def probe(x, z, top, wait):
        """(x,z) 위 top 높이에서 떨어뜨린다. → (바닥 높이, 종류).

        바닥을 찾으면 (y, "floor"). 못 찾은 경우 **왜 못 찾았는지가 중요하다**:
          · 거의 안 떨어졌다 = 고체 안에 놓인 것 → ("solid") 벽·기둥. 실측: 지금 지도의 허공 89칸 중 52칸이
            바닥에 2면 이상 둘러싸여 있었다(8칸은 사방 전부) — 바깥 경계가 아니라 폐허의 벽 위치.
          · 계속 떨어지는데 안 멈춘다 = ("air") 절벽 바깥·깊은 구덩이."""
        tm.set_hp(max_hp)
        tm.pos_warp(x, top, z, 0.0)
        t0, hist, last = time.time(), [], top
        while time.time() - t0 < wait:
            time.sleep(0.04)
            tm.set_hp(max_hp)
            _, y, _ = pos()
            if y is None or time.time() - t0 < SETTLE_LAG:
                continue
            last = y
            hist.append(y)
            del hist[:-STABLE_N]
            if len(hist) == STABLE_N and max(hist) - min(hist) < STABLE_EPS and y < top - MIN_FALL:
                return y, "floor"
        return None, ("solid" if top - last < 0.5 else "air")

    n = max(1, int(radius / step))
    print(f"스캔 시작: 중심 ({cx:.1f},{cy0:.1f},{cz:.1f}) 반경 {radius}m 간격 {step}m 최대 {budget}점 — 넓이 우선, 무적 워프. Ctrl+C 로 끝", flush=True)
    q = deque([(0, 0, cy0, (cx, cy0, cz))])
    seen = {(0, 0)}
    new_cells = done = voids = ledges = solids = 0
    t_start = time.time()
    stop_file = MAPS / f"{name}.stop"
    if stop_file.exists():
        stop_file.unlink()
    print(f"  (멈출 때는 강제 종료 대신: touch {stop_file} — 착지 복구까지 하고 끝난다)", flush=True)
    try:
        while q and done < budget:
            if stop_file.exists():
                stop_file.unlink()
                print("  (정지 요청)")
                break
            gi, gj, ref_y, parent = q.popleft()
            x, z = cx + gi * step, cz + gj * step
            y, kind = probe(x, z, ref_y + drop, max_wait)
            if y is None:
                if kind == "air":
                    settle(*parent)                                     # 속도 리셋 — 안 하면 다음 점에서 바닥을 뚫는다
                y, kind2 = probe(x, z, ref_y + 12.0, max_wait + 1.2)    # 지형이 위로 솟은 경우 한 번 더
                if y is None:
                    kind = kind2 if kind2 == "floor" else kind
                    settle(*parent)
            done += 1
            if y is not None and y < ref_y - MAX_STEP_DOWN:
                ledges += 1
                mm.cells.setdefault(MapMemory.key(x, z), {"n": 0}).update({"y": round(y, 2), "ledge": True})
                settle(*parent)     # 절벽 아래로 떨어진 상태 — 이웃 자리로 되돌려 속도까지 지운다
                y = None
            if y is not None:
                if mm.visit(x, y, z):
                    new_cells += 1
                for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    ni, nj = gi + di, gj + dj
                    if (ni, nj) in seen or max(abs(ni), abs(nj)) > n:
                        continue
                    seen.add((ni, nj))
                    q.append((ni, nj, y, (x, y, z)))
            else:
                voids += 1
                if kind == "solid":
                    solids += 1
                mm.cells.setdefault(MapMemory.key(x, z), {"y": ref_y, "n": 0})["void"] = kind
            if done % 25 == 0:
                mm.save()
                rate = (time.time() - t_start) / done
                print(f"  {done}점 ({rate:.2f}s/점)  +{new_cells} 칸  벽 {solids}  허공 {voids-solids}  절벽 {ledges}  대기 {len(q)}  "
                      f"예상 남은 {min(len(q), budget-done)*rate/60:.0f}분  {mm.stats()}", flush=True)
    except KeyboardInterrupt:
        print("  (중단)")
    mm.save()
    ok = settle(cx, cy0, cz)   # 끝에도 반드시 착지 — 속도가 남으면 스크립트 종료 뒤 바닥을 뚫고 떨어진다
    print(f"저장: {mm.path}  {mm.stats()}  점 {done} (벽 {solids}, 허공 {voids-solids}, 절벽 {ledges})  복귀착지 {'OK' if ok else '실패 — 게임 확인 필요'}")


def render(name: str, out: str | None = None, mark: tuple[float, float] | None = None) -> str:
    """지형도를 HTML(SVG)로 그린다 — 높이는 색, 허공은 검정. 봇이 아니라 사람이 보라고 만든 것."""
    mm = MapMemory(name)
    if not mm.cells:
        raise SystemExit(f"빈 지도: {name}")
    cells = {tuple(int(v) for v in k.split(",")): c for k, c in mm.cells.items()}
    solid = {k: c["y"] for k, c in cells.items() if not c.get("void") and not c.get("ledge")}
    if not solid:
        raise SystemExit("바닥 칸이 없다")
    xs = [x for x, _ in cells]; zs = [z for _, z in cells]
    x0, x1, z0, z1 = min(xs), max(xs), min(zs), max(zs)
    lo, hi = min(solid.values()), max(solid.values())
    px = 10   # 칸 한 변 (화면 픽셀)
    w, h = (z1 - z0 + 1) * px, (x1 - x0 + 1) * px

    def color(y):
        t = 0.0 if hi - lo < 1e-6 else (y - lo) / (hi - lo)
        # 낮음=남색 → 중간=청록/초록 → 높음=모래색
        stops = [(0.0, (26, 44, 92)), (0.35, (22, 106, 120)), (0.6, (60, 150, 90)), (0.8, (170, 170, 90)), (1.0, (222, 208, 170))]
        for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
            if t <= t1:
                f = 0 if t1 == t0 else (t - t0) / (t1 - t0)
                return "#%02x%02x%02x" % tuple(int(a + (b - a) * f) for a, b in zip(c0, c1))
        return "#ded0aa"

    rects = []
    for (x, z), c in cells.items():
        sx, sy = (z - z0) * px, (x - x0) * px
        if c.get("void"):
            solid_wall = c.get("void") == "solid"
            rects.append(f'<rect x="{sx}" y="{sy}" width="{px}" height="{px}" fill="{"#6b6f78" if solid_wall else "#0a0a0c"}">'
                         f'<title>{"벽/기둥 (고체)" if solid_wall else "허공 (바닥 없음)"}</title></rect>')
        elif c.get("ledge"):
            rects.append(f'<rect x="{sx}" y="{sy}" width="{px}" height="{px}" fill="#7a1f2b">'
                         f'<title>절벽: {c["y"]:.1f} m 아래</title></rect>')
        else:
            rects.append(f'<rect x="{sx}" y="{sy}" width="{px}" height="{px}" fill="{color(c["y"])}">' 
                         f'<title>x {x*CELL:.1f}  z {z*CELL:.1f}  y {c["y"]:.2f}</title></rect>')
    marker = ""
    if mark:
        mx, mz = int(mark[0] // CELL), int(mark[1] // CELL)
        marker = (f'<circle cx="{(mz-z0)*px+px/2}" cy="{(mx-x0)*px+px/2}" r="{px*0.9}" fill="none" stroke="#ff5a5a" stroke-width="2"/>')
    legend = "".join(
        f'<rect x="{i*44}" y="0" width="44" height="14" fill="{color(lo + (hi-lo)*i/5)}"/>'
        f'<text x="{i*44+22}" y="28" fill="#aaa" font-size="11" text-anchor="middle">{lo + (hi-lo)*i/5:.0f}</text>'
        for i in range(6))
    n_solid, n_void = len(solid), len(cells) - len(solid)
    html = f"""<!doctype html><meta charset="utf-8"><title>{name} 지형도</title>
<style>body{{background:#141416;color:#ddd;font:14px/1.5 system-ui,sans-serif;margin:24px}}
svg{{background:#1a1a1d;border:1px solid #333}} .meta{{margin:12px 0;color:#999}}</style>
<h2>{name} — 지형 높이 지도</h2>
<div class="meta">바닥 {n_solid}칸 · 허공 {n_void}칸 · 칸 {CELL} m · 높이 {lo:.1f} ~ {hi:.1f} m ·
x {x0*CELL:.0f}~{x1*CELL:.0f}, z {z0*CELL:.0f}~{z1*CELL:.0f} (가로=z, 세로=x, 칸에 마우스를 올리면 좌표)</div>
<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}">{''.join(rects)}{marker}</svg>
<div class="meta">높이(m) <svg width="270" height="34">{legend}</svg> &nbsp; <span style="color:#6b6f78">■</span> 회색 = 벽/기둥 &nbsp; 검정 = 허공 &nbsp; <span style="color:#c94f5f">■</span> 빨강 = 절벽(한참 아래에 바닥)</div>"""
    path = Path(out) if out else (MAPS / f"{name}.html")
    path.write_text(html, encoding="utf-8")
    return str(path)


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "record":
        record(sys.argv[2])
    elif len(sys.argv) >= 3 and sys.argv[1] == "scan":
        r = float(sys.argv[3]) if len(sys.argv) >= 4 else 25.0
        st = float(sys.argv[4]) if len(sys.argv) >= 5 else 1.0
        scan(sys.argv[2], radius=r, step=st)
    elif len(sys.argv) >= 3 and sys.argv[1] == "render":
        print(render(sys.argv[2], sys.argv[3] if len(sys.argv) >= 4 else None))
    elif len(sys.argv) >= 3 and sys.argv[1] == "stats":
        print(MapMemory(sys.argv[2]).stats())
    else:
        print(__doc__)
