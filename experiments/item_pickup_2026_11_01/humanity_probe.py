"""Firelink 宝死体00 (Humanity ×3, ItemFlag 51020000) — one pickup, with the readings before and after recorded. Not a bot command.

  python experiments/item_pickup_2026_11_01/humanity_probe.py [--note "…"] [--close-a]

Readings at each step: event_flag(51020000), goods_count(500), humanity(), player x/y/z/heading/anim, menu_open(). A failed read
is kept as unread (null) or the exception text, never turned into False / 0. Every input sent is written with its time.
Record: experiments/item_pickup_2026_11_01/runs/<time>_humanity.jsonl (not data/runs — the bot's learned inputs read *.log there).

Steps: locks (data/bot.lock, then the pad lock — either held → stop, no input) → before → flag True: "already" / None: "unknown"
→ walk (NavMesh path, bounded time, stall check) → before-A → A (PICK_TRIES = 1, then PICK_WAIT_S of reads) → after.
Result = the pickup only (flag / count): "got" also when the window is still open. The window is a separate "ui" record —
window_shown / close_approved (--close-a) / close_sent_t / close_confirmed — and close_confirmed stays None here: no memory
value read here is known to show the window (menu_open() stayed False while it was open, 11-01), so confirmation is MoKa's
look, kept in <run>.observation.jsonl next to the untouched run file. The window is not closed by default; --close-a (only
after that look) sends one A as a separate "close" step. Same pattern as the bot's one pickup, souls/altar.py `_claymore`
(walk_to → A → flag → A to close, the close A unconditional there).
Import alone touches neither the game nor the pad (game modules are imported inside main()).
11-01 run 20261101_042509_humanity: flag False → True 0.38 s after one A, Humanity 1 → 4; window shown, gone after one close A
(both MoKa's look) — docs/item-pickup.md.

/**
 * ── 알려진 한계 ──────────────────────────────
 *  · 줍기가 되는 거리를 모른다 — STOP_M 1.0 m는 시험값이고, 거리만으로 상호작용 가능·안전이 보장되지 않는다.
 *    시체(MSB 위치)는 NavMesh 밖이라 경로 끝과 1.95 m 떨어져 있다 (11-01 오프라인 계산) → 마지막 한 구간은 시체 쪽으로 직진한다.
 *  · goods_count는 소지품 칸 모양을 앞 0x8000 바이트에서 찾는다: 0은 "못 찾음"이지 확정 미보유가 아니다. 500(인간성)은 게임
 *    파일 근거만 있고 메모리로 읽어 본 적이 없다.
 *  · menu_open()은 START 메뉴·하위 메뉴에서만 측정됐고, 11-01 획득 창이 떠 있는 동안 False였다 → 이 값으로는 창을 못 본다.
 *    다른 메모리 값으로 창을 볼 수 있는지는 찾아보지 않았다 (없다는 뜻이 아님).
 *  · Firelink 플래그는 51020000 하나만 게임에서 False → True를 봤다 (11-01, 1회). 다른 목표·반복은 미검증.
 *  · pymem 기본 핸들은 쓰기 권한도 있지만 이 스크립트는 읽기 함수만 부른다.
 */
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent

MAP = "m10_02_00_00"
FLAG = 51020000                       # data/gamefiles/m10_02_00_00.json 宝死体00 ItemLot 1020000 ItemFlag
ITEM = 500                            # same lot: good 500 "Humanity" ×3 (game file; memory read unverified)
COUNT = 3
CORPSE = (-39.37, -58.16, 53.44)      # MSB position of 宝死体00
BONFIRE = (-47.4, -59.8, 53.3)        # Firelink bonfire 1022960 (run.py status after the 10-31 restore)
BONFIRE_NO_A = 6.0                    # souls/field.py BONFIRE_NO_A — A this close may sit at the bonfire
STOP_M = 1.0                          # horizontal distance to the corpse to stop at (trial value)
WAYPOINT_M = 0.6
WALK_S = 25.0                         # whole walk
STALL_S, STALL_M = 3.0, 0.3           # no 0.3 m closer in 3 s → stuck
UNREAD_MAX = 10                       # consecutive missing snapshots while walking → stop
TICK_S = 0.1
PICK_TRIES = 1                        # A presses for the pickup, at most
# 2였을 때 두 번째 A는 "menu_open False = 창 없음"을 전제했다. 11-01 획득 창은 menu_open False인 채 떠 있었다 (MoKa 눈 확인) →
# 창이 떠 있을 수 있는 상태에서 보내는 검증 안 된 A가 되므로 1로 줄임. 다시 늘리려면 창을 구분하는 관측이 먼저다.
PICK_WAIT_S = 2.0                     # reads after each A
POLL_S = 0.25
CLOSE_WAIT_S = 3.0
LOCK_TRIES, LOCK_GAP = 10, 0.2        # run.py's retry (watchdog.py grabs the bot lock for an instant)


def _read(fn, *a):
    """→ {"v": value} | {"v": None, "unread": True} | {"err": "..."} — a failure stays a failure."""
    try:
        v = fn(*a)
    except Exception as e:                                   # noqa: BLE001 — recorded, not hidden
        return {"err": f"{type(e).__name__}: {e}"[:160]}
    return {"v": v} if v is not None else {"v": None, "unread": True}


def _val(r):
    return r.get("v") if "err" not in r else None


class Probe:
    """The steps above on injected parts — tm (event_flag, goods_count, humanity, menu_open), snap() → snapshot or None,
    pad (control.Pad), stick(s, x, z) → (sx, sy), path(start, goal) → points, rec(dict) writes one record line."""

    def __init__(self, tm, snap, pad, stick, path, rec, now=None, sleep=None, close_a=False):
        self.tm, self.snap, self.pad, self.stick, self.path, self.rec = tm, snap, pad, stick, path, rec
        self.now, self.sleep = now or (lambda: time.time()), sleep or (lambda s: time.sleep(s))
        self.close_a = close_a
        self.t0 = self.now()
        self.presses = 0
        # the pickup (flag / count) and the window are separate states: no memory value here is known to show the window
        self.ui = {"window_shown": None, "close_approved": close_a, "close_sent_t": None, "close_confirmed": None,
                   "confirm_by": "observation file (MoKa's look) — menu_open() did not change for this window (11-01)"}

    # ── records ──
    def state(self, step: str, **extra) -> dict:
        s = _read(self.snap)
        p = getattr(_val(s), "player", None)
        st = {"k": "state", "step": step, "t": round(self.now() - self.t0, 3),
              "flag": _read(self.tm.event_flag, FLAG), "goods": _read(self.tm.goods_count, ITEM),
              "humanity": _read(self.tm.humanity), "menu_open": _read(self.tm.menu_open),
              "player": None if p is None else {k: getattr(p, k, None) for k in ("x", "y", "z", "heading", "anim", "hp")},
              **({"snap": s} if p is None else {}), **extra}
        if p is not None:
            st["d_corpse"] = round(math.hypot(p.x - CORPSE[0], p.z - CORPSE[2]), 3)
            st["d_bonfire"] = round(math.dist((p.x, p.y, p.z), BONFIRE), 3)
        self.rec(st)
        return st

    def sent(self, what: str, **kw) -> None:
        self.rec({"k": "input", "t": round(self.now() - self.t0, 3), "what": what, **kw})

    # ── steps ──
    def run(self) -> str:
        st = self.state("before")
        f = st["flag"]
        if "err" in f or f.get("v") is None:
            return "unknown_flag"
        if f["v"] is True:
            return "already"
        r = self.walk()
        if r != "arrived":
            return r
        st = self.state("before_A")
        if st["player"] is None:
            return "unread_before_A"
        if st["d_corpse"] > STOP_M:
            return "not_reached"
        if st["d_bonfire"] < BONFIRE_NO_A:
            return "bonfire_close"
        return self.pick()

    def walk(self) -> str:
        s = _val(_read(self.snap))
        if s is None:
            return "unread_walk"
        p = s.player
        pts = list(self.path((p.x, p.y, p.z), CORPSE) or [])
        self.rec({"k": "path", "n": len(pts), "pts": [[round(c, 2) for c in q] for q in pts]})
        if not pts:
            return "no_path"
        pts.append(CORPSE)                                   # last leg straight to the corpse (it lies off the mesh)
        i, t_start, unread, last_move = 0, self.now(), 0, None
        best, t_best = math.inf, self.now()
        while True:
            if self.now() - t_start > WALK_S:
                return "walk_timeout"
            r = _read(self.snap)
            s = _val(r)
            if s is None:
                self.rec({"k": "unread", "step": "walk", "t": round(self.now() - self.t0, 3), "snap": r})
                unread += 1
                if unread >= UNREAD_MAX:
                    return "unread_walk"
                self.sleep(TICK_S)
                continue
            unread = 0
            p = s.player
            d = math.hypot(p.x - CORPSE[0], p.z - CORPSE[2])
            if d <= STOP_M:
                self.pad.neutral()
                self.sent("neutral", why="arrived")
                self.sleep(0.5)
                return "arrived"
            if d < best - STALL_M:
                best, t_best = d, self.now()
            elif self.now() - t_best > STALL_S:
                return "stuck"
            while i < len(pts) - 1 and math.hypot(p.x - pts[i][0], p.z - pts[i][2]) < WAYPOINT_M:
                i += 1
            sx, sy = self.stick(s, pts[i][0], pts[i][2])
            mv = (round(sx, 2), round(sy, 2))
            self.pad.move(sx, sy)
            if mv != last_move:
                self.sent("move", stick=list(mv), wp=i)
                last_move = mv
            self.sleep(TICK_S)

    def _a(self, step: str) -> None:
        self.pad.tap(self._A(), 0.1)
        self.sent("A", step=step)
        self.sleep(0.13)
        self.pad.release_due()

    @staticmethod
    def _A():
        import control
        return control.B.XUSB_GAMEPAD_A

    def pick(self) -> str:
        for k in range(PICK_TRIES):
            self._a(f"pick{k + 1}")
            self.presses += 1
            end = self.now() + PICK_WAIT_S
            got = False
            while self.now() < end:
                self.sleep(POLL_S)
                st = self.state(f"after_A{k + 1}")
                if st["flag"].get("v") is True:
                    got = True
                    break
            if got:
                self.sleep(0.5)
                after = self.state("after")
                if self.close_a:
                    self._a("close")
                    self.ui["close_sent_t"] = round(self.now() - self.t0, 3)
                    end = self.now() + CLOSE_WAIT_S
                    while self.now() < end:
                        self.sleep(POLL_S)
                        self.state("after_close")
                    self.rec({"k": "ask", "what": "닫기 A를 한 번 보냈다 — 획득 창이 사라졌는지 한 번 봐 주세요 (사라짐 / 아직 떠 있음)"})
                else:
                    self.rec({"k": "ask", "what": "획득 창이 화면에 떠 있는지 한 번 봐 주세요 (떠 있음 / 없음). 닫기 입력은 안 보냈다",
                              "menu_open": after["menu_open"]})
                self.rec({"k": "ui", **self.ui})
                return "got"
            last = self.state(f"end_A{k + 1}")
            if last["menu_open"].get("v") is True:          # something opened, and it is not known what — no second A on a guess
                self.rec({"k": "ask", "what": "A 뒤 menu_open True, 플래그는 그대로 — 화면에 무엇이 떠 있는지 한 번 봐 주세요"})
                return "window_unclear"
        self.rec({"k": "ask", "what": "A 한 번 뒤 플래그 그대로 — menu_open False는 창이 없다는 뜻이 아니다. 화면을 한 번 봐 주세요"})
        return "not_got"


def judge(records: list[dict]) -> dict:
    """Flag change and count change, each on its own; unread stays unread."""
    states = [r for r in records if r.get("k") == "state"]
    if not states:
        return {}
    first, last = states[0], states[-1]

    def pair(key):
        a, b = _val(first[key]), _val(last[key])
        return {"before": first[key], "after": last[key], "delta": (b - a) if isinstance(a, int) and isinstance(b, int) and
                not isinstance(a, bool) else None}
    flag_on = next((r["t"] for r in states if r["flag"].get("v") is True), None)
    g = pair("goods")
    return {"flag_before": first["flag"], "flag_after": last["flag"], "flag_on_at": flag_on,
            "goods": {**g, "vs_lot": None if g["delta"] is None else ("match" if g["delta"] == COUNT else "mismatch")},
            "humanity": pair("humanity"), "menu_open": {"before": first["menu_open"], "after": last["menu_open"]}}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--note", default="")
    ap.add_argument("--close-a", action="store_true", help="after the pickup, one A to close the window (only after looking at the screen)")
    a = ap.parse_args(argv)
    sys.path.insert(0, str(ROOT))
    import os
    os.environ.setdefault("BOT_GAME", "dsr")
    out = HERE / "runs" / f"{time.strftime('%Y%m%d_%H%M%S')}_humanity.jsonl"
    out.parent.mkdir(exist_ok=True)
    f = out.open("a", encoding="utf-8")
    records: list[dict] = []

    def rec(d):
        records.append(d)
        f.write(json.dumps(d, ensure_ascii=False, default=str) + "\n")
        f.flush()
        print(json.dumps(d, ensure_ascii=False, default=str)[:300])

    rec({"k": "hdr", "argv": sys.argv, "note": a.note, "flag": FLAG, "item": ITEM, "corpse": CORPSE, "wall": time.time()})
    import control
    from botlock import BotLock

    def make_tm():
        import dsr_telemetry
        return dsr_telemetry.DSRTelemetry({})

    def make_pad():
        control.focus_game()
        return control.Pad()

    def parts(tm, pad):
        import navmesh
        from souls import moves
        mv = moves.Moves(tm, pad)
        return (lambda: tm.snapshot(within=5.0)), mv.stick_to, navmesh.Navmesh(MAP).find_path

    try:
        result = execute(rec, records, BotLock, control.pad_lock_held, make_tm, make_pad, control.PadBusy, parts, close_a=a.close_a)
    finally:
        f.close()
    print(f"result: {result} → {out}")
    return 0 if result in ("already", "got") else 1


def execute(rec, records, make_lock, pad_lock_held, make_tm, make_pad, pad_busy, parts, close_a=False,
            now=None, sleep=None) -> str:
    """Locks → telemetry → pad → Probe, and whatever happens: pad neutral + released + closed, locks released, end record.
    A lock that can't be had ends before telemetry or the pad exist (no input). now / sleep default to time.time / time.sleep
    looked up at call time (the Pad reads the same clock)."""
    now, sleep = now or (lambda: time.time()), sleep or (lambda s: time.sleep(s))
    result, lock, pad = "exception", None, None
    try:
        lock = make_lock()
        for _ in range(LOCK_TRIES):
            if lock.acquire():
                break
            sleep(LOCK_GAP)
        else:
            lock, result = None, "bot_lock_held"
            return result
        if pad_lock_held():
            result = "pad_lock_held"
            return result
        tm = make_tm()
        try:
            pad = make_pad()
        except pad_busy:
            result = "pad_lock_held"
            return result
        snap, stick, path = parts(tm, pad)
        result = Probe(tm, snap, pad, stick, path, rec, now=now, sleep=sleep, close_a=close_a).run()
        return result
    except KeyboardInterrupt:
        result = "user_stop"
        return result
    except Exception as e:                                   # noqa: BLE001 — recorded, then the cleanup below
        result = f"exception:{type(e).__name__}"
        rec({"k": "error", "exc": f"{type(e).__name__}: {e}"[:300]})
        return result
    finally:
        try:
            if pad is not None:
                try:
                    pad.neutral()
                    pad.release_all()
                finally:
                    pad.close()
                rec({"k": "input", "what": "cleanup", "neutral": True, "closed": True})
        finally:
            if lock is not None:
                lock.release()
            rec({"k": "end", "result": result, "judge": judge(records)})


if __name__ == "__main__":
    sys.exit(main())
