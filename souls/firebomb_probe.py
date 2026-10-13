"""Firebomb measurement (ROADMAP firebomb-measure; [MoKa] 2026-10-13 "앞으로 화염병 위주로 플레이 해봐").

  python run.py firebomb-probe [--dists 5,8,12,15]

Per distance: rest at the Undead Burg bonfire (every foe back, HP · Estus full) → walk toward burg-upper zone 1's first
254010 (−10.1, −11.5, −68.1) until it is `d` m away (horizontal) → one locked-on firebomb (Moves.throw_firebomb) → watch
WATCH_S: the target's damage and whether it woke, and **which other foes within OTHERS_R woke** (anim set, or moved
> MOVED_M) — the crossbowman 255002 stands 4.1 m from it, another 254010 7.9 m. Then fight whoever came (Field.fight
through hunt-style handling) and walk back. One 'firebomb_probe' event per throw; a summary table at the end.

── 이 측정의 한계 ──────────────────────────────
 · 거리마다 한 번 (화염병 수가 정해져 있음) — 명중·피해는 경향만
 · 깨어남은 애니·위치 변화로 봄: 원래 서성이는 적(순찰)은 화염병과 상관없이 움직일 수 있음
"""
from __future__ import annotations

import math
import time

from . import moves as M

TARGET = {"npc": 254010, "pos": (-10.1, -11.5, -68.1)}
OTHERS_R = 15.0
MOVED_M = 0.8
WATCH_S = 3.0
COME_R = 12.0


def _state(s, ptr0) -> dict:
    """ptr → (npc, x, y, z, anim, hp) for live hostiles within OTHERS_R of the target spot."""
    tx, ty, tz = TARGET["pos"]
    out = {}
    for c in s.hostile(60.0):
        if c.hp > 0 and math.hypot(c.x - tx, c.z - tz) < OTHERS_R:
            out[c.ptr] = (c.npc_param, c.x, c.y, c.z, c.anim, c.hp)
    return out


def _woke(before: tuple, now: tuple) -> bool:
    return now[4] not in (None, -1) or math.dist(before[1:4], now[1:4]) > MOVED_M


def trial(ms, d: float, log) -> dict:
    f, mv = ms.f, ms.mv
    from .missions import MAP_B, SPOTS
    nb = ms.nms[MAP_B]
    ok = f.rest_at(nb, SPOTS["burg-bonfire"])
    log(f"── 화염병 {d:g} m: 성벽 마을 휴식 {'됨' if ok else '안 됨'}")
    c = f.find_at(TARGET["npc"], TARGET["pos"], 3.0) or f.find_at(TARGET["npc"], TARGET["pos"], 8.0)
    if c is None:
        return {"d": d, "result": "no_target"}
    ptr = c.ptr

    def near_enough(sn) -> bool:
        t = mv.find(sn, ptr)
        return t is None or M.horiz(sn.player, t) <= d
    r = f.walk_to(TARGET["pos"], nb, f"화염병 {d:g} m 자리로", done=near_enough)
    if r == "dead":
        return {"d": d, "result": "died"}
    s0 = mv.snap(60.0)
    t0c = mv.find(s0, ptr) if s0 else None
    if t0c is None:
        return {"d": d, "result": "lost", "walk": r}
    if t0c.anim not in (None, -1):
        log(f"   화염병 {d:g} m: 던지기 전에 이미 깨어 있음 (애니 {t0c.anim}) — 이번 거리는 버림")
        return {"d": d, "result": "awake_before", "walk": r}
    before = _state(s0, ptr)
    stood = round(M.horiz(s0.player, t0c), 2)
    tr = mv.throw_firebomb(ptr, watch=WATCH_S)
    s1 = mv.snap(60.0)
    now = _state(s1, ptr) if s1 else {}
    woke = [(v[0], round(math.hypot(v[1] - t0c.x, v[3] - t0c.z), 1)) for p, v in before.items()
            if p != ptr and p in now and _woke(v, now[p])]
    res = {"d": d, "stood": stood, "result": "thrown" if tr.get("ok") else "not_thrown", "locked": tr.get("locked"),
           "hit": tr.get("hit"), "target_woke": tr.get("woke"), "others_woke": woke, "left": tr.get("knives"), "why": tr.get("why")}
    log(f"   화염병 {d:g} m (선 자리 {stood} m): 락온 {res['locked']} · 피해 {res['hit']} · 목표 깸 {res['target_woke']} · "
        f"옆에 깬 적 {woke or '없음'} · 남은 {res['left']} {('· ' + res['why']) if res['why'] else ''}")
    ms.f.events("firebomb_probe", **res)
    # whoever came: fight them one by one (nearest awake within COME_R), then go on — the next trial rests anyway
    for _ in range(4):
        s = mv.snap(COME_R + 2.0)
        if s is None or not f.alive():
            break
        come = [x for x in s.hostile(COME_R) if x.hp > 0 and x.anim not in (None, -1) and abs(x.y - s.player.y) < 2.5]
        if not come:
            break
        x = min(come, key=lambda x: M.horiz(s.player, x))
        fr = f.fight(x.ptr, nb, f"화염병 {d:g} m 뒤 {x.npc_param}")
        log(f"   화염병 {d:g} m 뒤 싸움 {x.npc_param}: {fr.result}")
        if fr.result == "me_dead":
            res["result"] += "/died"
            break
    return res


def run(ms, dists, log) -> str:
    rows = []
    for d in dists:
        if not ms.f.alive():
            ms.f.wait_respawn()
        if (ms.mv.tm.goods_count(M.ITEM_FIREBOMB) or 0) <= 0:
            log("   화염병 없음 — 멈춤")
            break
        rows.append(trial(ms, d, log))
    log("══ 화염병 측정: 거리 · 선 자리 · 락온 · 피해 · 목표 깸 · 옆에 깬 적")
    for r in rows:
        log(f"   {r['d']:>4g} m · {r.get('stood')} · {r.get('locked')} · {r.get('hit')} · {r.get('target_woke')} · "
            f"{r.get('others_woke')} · {r['result']}")
    return "done"
