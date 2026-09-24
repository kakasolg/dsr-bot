"""긴급 탈출(메뉴 → Quit Game → 이어하기) 시험 — 사용자: "적이 몰려 있거나, 낙사할 때도 시도해 봐".

  BOT_GAME=dsr python escape_test.py fall   다리 가장자리(사용자가 강공으로 떨어져 죽은 자리)에서 걸어 떨어지며 곧바로 종료
                                            → 떨어지는 중에 메뉴가 열리나, 바닥에 닿기 전에 나가지나, 다시 들어오면 어디에 서나
  BOT_GAME=dsr python escape_test.py mob    경사로 무리에게 둘러싸이면 종료 → 다시 들어오면 적 위치·경계가 풀리나

안 죽음(PlayerNoDead)만 켜고 한다 — 실패해도 죽지 않게. fall 은 올라가는 동안 적이 못 보게(Hide·NoAttack)도 켠다.
끝나면 다크사인으로 화톳불에 돌아와 플래그를 끈다 (화톳불 옆이 아니면 켜 둔다).
"""
from __future__ import annotations

import json
import math
import sys
import threading
import time
from pathlib import Path

import control
import env
import merchantrun as mr
import nav
import quitout
from hunt import ARENA, MAP, Hunter

ROOT = Path(__file__).resolve().parent
EDGE = (-26.4, -33.71, 8.42)          # 사용자 녹화 play_20260923_163749 t=156.8: 여기서 강공 → 157.7 떨어짐(1550) → 160.0 죽음(y -76.5)
EDGE_DIR = (-0.72, 0.69)              # 떨어진 방향 (-26.96, 8.92) → (-27.42, 9.36)
FALL_ANIMS = {1500, 1550, 121500}


class Sampler:
    """종료가 도는 동안(블록됨) 따로 붙은 텔레메트리로 y·HP·애니·메뉴 플래그를 50 Hz 로 적는다."""

    def __init__(self):
        self.rows: list = []
        self._stop = False
        self.t0 = time.time()
        self.th = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        tm = env.make_telemetry({})
        while not self._stop:
            try:
                s = tm.snapshot(within=1.0)
                m = tm.menu_open()
            except Exception:
                s, m = None, None
            t = round(time.time() - self.t0, 2)
            row = (t, None) if s is None else (t, round(s.player.y, 2), s.player.hp, s.player.anim, m)
            if not self.rows or self.rows[-1][1:] != row[1:]:
                self.rows.append(row)
            time.sleep(0.02)

    def start(self):
        self.th.start()
        return self

    def stop(self):
        self._stop = True
        self.th.join(timeout=1.0)


def reattach(h: Hunter) -> None:
    h.run.tm = env.make_telemetry({})
    h.tm = h.run.tm


def escape(h: Hunter, why: str) -> dict:
    """메뉴로 나갔다 들어온다. → {'quit_s', 'reload_s', 'pos', 'hp'}"""
    t0 = time.time()
    q = quitout.quit_out(h.tm, h.pad, gap=quitout.MENU_GAP, settle=0.1)
    out = {"why": why, "quit_s": None if q is None else round(q, 2)}
    if q is None:
        quitout.close_menu(h.tm, h.pad)
        return out
    r = quitout.reload(h.pad)
    out["reload_s"] = None if r is None else round(r, 1)
    time.sleep(1.0)
    reattach(h)
    s = h.tm.snapshot(within=40.0)
    if s:
        out["pos"] = [round(s.player.x, 2), round(s.player.y, 2), round(s.player.z, 2)]
        out["hp"] = s.player.hp
    out["total_s"] = round(time.time() - t0, 1)
    return out


def home(h: Hunter, flags) -> None:
    reattach(h)
    s = h.tm.snapshot(within=5.0)
    if s and math.dist((s.player.x, s.player.y, s.player.z), tuple(mr.BONFIRE["stand"])) > 15.0 and "--darksign" in sys.argv:
        # 사용자: "이제 다크사인 쓰지 마" — --darksign 을 줄 때만
        print("   다크사인으로 복귀:", h.run.darksign(), flush=True)
        reattach(h)
    s = h.tm.snapshot(within=5.0)
    if s and math.dist((s.player.x, s.player.y, s.player.z), tuple(mr.BONFIRE["stand"])) < 15.0:
        for o in flags:
            h.tm.set_dbg(o, False)
        print(f"   플래그 끔: {[h.tm.get_dbg(o) for o in flags]}", flush=True)
    else:
        print("   화톳불 옆이 아니라 플래그를 켜 둠", flush=True)


def fall(h: Hunter) -> None:
    tm = h.tm
    flags = (tm.DBG_PLAYER_NO_DEAD, tm.DBG_PLAYER_HIDE, 0xB)
    for o in flags:
        tm.set_dbg(o, True)
    try:
        top = tuple(json.loads((ROOT / "data" / "climb-goal.json").read_text(encoding="utf-8"))["top"])
        print("── 계단 꼭대기로:", h.climb_to(top), flush=True)
        A = [tuple(q) for q in mr.ROUTE["segments"][0]["points"]]
        nav.follow(h.tm, h.pad, A[67:71] + [(-25.59, -33.68, 7.21)], mode_fn=lambda _s: "walk", default_tol=0.8,
                   log=lambda *a: None)
        nav.goto(h.tm, h.pad, EDGE, tolerance=0.35, timeout=8, log=lambda *a: None)
        h.pad.neutral()
        time.sleep(0.8)
        s = h.tm.snapshot(within=5.0)
        y0 = s.player.y
        print(f"── 가장자리 {tuple(round(v, 2) for v in (s.player.x, s.player.y, s.player.z))} — 떨어지는 쪽으로 걷는다", flush=True)
        smp = Sampler().start()
        t_walk = time.time()
        fell_at = None
        while time.time() - t_walk < 6.0:
            s = h.tm.snapshot(within=1.0)
            if s is None:
                continue
            if s.player.anim in FALL_ANIMS or s.player.y < y0 - 0.8:
                fell_at = round(time.time() - smp.t0, 2)
                break
            st = control.world_to_stick(EDGE_DIR[0], EDGE_DIR[1], s.cam_yaw, nav.YAW_OFFSET, nav.FLIP_X)
            h.pad.move(0.6 * st[0], 0.6 * st[1])
            time.sleep(0.02)
        h.pad.neutral()
        if fell_at is None:
            smp.stop()
            print("   6 s 걸어도 안 떨어짐 — 멈춤", flush=True)
            return
        print(f"   떨어짐 감지 +{fell_at}s (애니 {s.player.anim}, y {s.player.y:.2f}) → 곧바로 종료", flush=True)
        res = escape(h, "fall")
        smp.stop()
        print("   결과:", res, flush=True)
        print("   떨어지는 동안 (t, y, hp, 애니, 메뉴열림):", smp.rows[:60], flush=True)
        (ROOT / "data" / "trace" / f"escape_fall_{time.strftime('%H%M%S')}.json").write_text(
            json.dumps({"res": res, "rows": smp.rows, "fell_at": fell_at}, ensure_ascii=False), encoding="utf-8")
    finally:
        h.pad.neutral()
        home(h, flags)


def fallwatch(h: Hunter) -> None:
    """fall 과 같은 자리에서 떨어지되, 종료는 봇에 넣은 EscapeWatch 가 스스로 하게 둔다 (판단 루프는 계속 스틱을 민다)."""
    from hunt import EscapeWatch
    tm = h.tm
    flags = (tm.DBG_PLAYER_NO_DEAD, tm.DBG_PLAYER_HIDE, 0xB)
    for o in flags:
        tm.set_dbg(o, True)
    esc = None
    try:
        top = tuple(json.loads((ROOT / "data" / "climb-goal.json").read_text(encoding="utf-8"))["top"])
        print("── 계단 꼭대기로:", h.climb_to(top), flush=True)
        A = [tuple(q) for q in mr.ROUTE["segments"][0]["points"]]
        nav.follow(h.tm, h.pad, A[67:71] + [(-25.59, -33.68, 7.21)], mode_fn=lambda _s: "walk", default_tol=0.8,
                   log=lambda *a: None)
        nav.goto(h.tm, h.pad, EDGE, tolerance=0.35, timeout=8, log=lambda *a: None)
        h.pad.neutral()
        time.sleep(0.8)
        if "--noflag" in sys.argv:
            # 사용자: "플래그 없이 한 번 해 봐" — 올라오는 동안만 켜 두고(적이 못 보게), 떨어지기 직전에 전부 끈다
            for o in flags:
                h.tm.set_dbg(o, False)
            print(f"   플래그 전부 끔 (안 죽음 포함): {[h.tm.get_dbg(o) for o in flags]}", flush=True)
        smp = Sampler().start()
        esc = EscapeWatch(h).start()
        gen0 = h.escape_gen
        t_walk = time.time()
        while time.time() - t_walk < 20.0 and h.escape_gen == gen0:
            s = h.tm.snapshot(within=1.0)
            if s is not None and s.cam_yaw is not None:
                st = control.world_to_stick(EDGE_DIR[0], EDGE_DIR[1], s.cam_yaw, nav.YAW_OFFSET, nav.FLIP_X)
                h.pad.move(0.6 * st[0], 0.6 * st[1])       # 탈출 중엔 얼어서 게임에 안 간다
            time.sleep(0.02)
        h.pad.neutral()
        smp.stop()
        last_in = [r for r in smp.rows if r[1] is not None and r[1] < -33.0]
        low = min((r[1] for r in smp.rows if r[1] is not None), default=None)
        print(f"   탈출 {'됨' if h.escape_gen != gen0 else '안 됨'} — 가장 낮게 내려간 y {low}", flush=True)
        s = h.tm.snapshot(within=5.0)
        print(f"   지금 {tuple(round(v, 2) for v in (s.player.x, s.player.y, s.player.z))} HP {s.player.hp}", flush=True)
        (ROOT / "data" / "trace" / f"escape_fallwatch_{time.strftime('%H%M%S')}.json").write_text(
            json.dumps({"rows": smp.rows}, ensure_ascii=False), encoding="utf-8")
    finally:
        if esc is not None:
            esc.stop()
        h.pad.neutral()
        home(h, flags)


def mob(h: Hunter) -> None:
    tm = h.tm
    flags = (tm.DBG_PLAYER_NO_DEAD,)
    for o in flags:
        tm.set_dbg(o, True)
    try:
        print("── 화톳불 휴식 (적 되살리기)", flush=True)
        h.run.rest()
        reattach(h)
        print("── 평지로:", h.climb_to(ARENA), flush=True)
        spawns = [tuple(e["pos"]) for e in MAP[:6]]
        center = tuple(sum(p[i] for p in spawns[:3]) / 3 for i in range(3))    # 1·2·3번 스폰 가운데로 걸어 들어간다
        t0 = time.time()
        before = None
        while time.time() - t0 < 40.0:
            s = h.tm.snapshot(within=12.0)
            if s is None:
                continue
            near = [c for c in s.hostile(3.5) if c.hp > 0]
            if len(near) >= 2:
                before = [(c.npc_param, round(c.dist, 1), c.anim, [round(c.x, 1), round(c.y, 1), round(c.z, 1)]) for c in s.hostile(12.0) if c.hp > 0]
                break
            nav.goto(h.tm, h.pad, center, tolerance=1.5, timeout=0.5, log=lambda *a: None, mode_fn=lambda _s: "walk")
        h.pad.neutral()
        if before is None:
            print("   40 s 안에 둘러싸이지 않음 — 멈춤", flush=True)
            return
        s = h.tm.snapshot(within=5.0)
        print(f"── 둘러싸임: HP {s.player.hp}, 12 m 안 적 {before}", flush=True)
        res = escape(h, "mob")
        print("   결과:", res, flush=True)
        s = h.tm.snapshot(within=40.0)
        after = []
        for c in (s.hostile(40.0) if s else []):
            if c.hp <= 0:
                continue
            sp = min(spawns, key=lambda p: math.dist(p, (c.x, c.y, c.z)))
            after.append((c.npc_param, round(c.dist, 1), c.anim, round(math.dist(sp, (c.x, c.y, c.z)), 1)))
        print("   다시 들어온 뒤 적 (npc, 나와 거리, 애니, 스폰까지):", sorted(after, key=lambda x: x[1])[:8], flush=True)
        time.sleep(3.0)
        s = h.tm.snapshot(within=12.0)
        print("   3 s 뒤 4 m 안 적:", [(c.npc_param, round(c.dist, 1), c.anim) for c in (s.hostile(4.0) if s else []) if c.hp > 0], flush=True)
    finally:
        h.pad.neutral()
        home(h, flags)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    what = sys.argv[1] if len(sys.argv) > 1 else "fall"
    h = Hunter()
    {"fall": fall, "fallwatch": fallwatch, "mob": mob}[what](h)


if __name__ == "__main__":
    main()
