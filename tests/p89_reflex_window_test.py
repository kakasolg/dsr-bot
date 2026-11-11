"""P-89 offline comparison: Reflex threat / lock windows (Reflex(threat_s=, lock_s=)). An experiment, not a policy the bot uses —
nothing in the bot passes threat_s / lock_s.  python tests/p89_reflex_window_test.py

Three configurations, compared as separate policy candidates on the same input:
  · now  — threat window THREAT_S, lock window THREAT_S (the defaults)
  · B-t  — threat window windup_s(c), lock window THREAT_S
  · B    — threat window windup_s(c), lock window windup_s(c)
windup_s(c) uses the attacking foe's own entry foes.of(c.npc_param): max(THREAT_S, windup_land_s + duel.LAND_PAD) when c.anim is
in its windup and windup_land_s is set, else THREAT_S. Same shape as duel.swing_over (max(SWING_S, land + LAND_PAD)).
LAND_PAD 0.2 is the existing swing_over policy value reused (P-66, 0aa4dac) — not a measured margin; not tuned to this scene.
255041 3004 → 2.1 + 0.2 = 2.3000000000000003 s (float); 255042 has no windup → THREAT_S.

Part 1 replays 212954 n2 (the input of tests/p89_reflex_scene_test.py, which stays the baseline) under all three and prints per
tick: threats with attack age and applied window, the lock used (target, expiry, valid), prefer, the final choice. Expected
choices were worked out by hand before the run (HAND); the checks compare the run against them.
Part 2: boundaries (defaults = old behaviour, fallback, window edge, anim change, two threats).
Covers Reflex's threat recognition and target choice only — not whether a hit is prevented, not face_first, not the shield.

Limit of B, recorded only (no lock or float change): a lock that is still valid keeps the expiry of the attack it was set on —
tick() refreshes _lock only when it re-chooses — so after an anim change (3004 → 3000) the new attack's window applies to the
lock only once the old expiry has passed (Part 2 "애니 전환"). B's longer lock window makes that stale span longer.
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import math
import sys
from types import SimpleNamespace as NS

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import p89_reflex_scene_test as S
from souls import duel as D
from souls import foes
from souls import reflex as R
from telemetry import Chr, Snapshot

A41, A42, T0 = S.A41, S.A42, S.T0


def check(name: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        raise SystemExit(1)


def windup_s(c) -> float:
    f = foes.of(c.npc_param)
    land = f.windup_land_s
    a = c.anim if c.anim is not None else -1
    return max(R.THREAT_S, land + D.LAND_PAD) if land and a in f.windup else R.THREAT_S


CONFIGS = {"now": {}, "B-t": {"threat_s": windup_s}, "B": {"threat_s": windup_s, "lock_s": windup_s}}

# hand-worked before the run: t → (now, B-t, B); None = reflex does nothing
HAND = {-2.572: (A42, A42, A42), -1.892: (A41, A41, A41), -1.434: (A41, A41, A41), -1.266: (A41, A41, A41),
        -1.119: (A41, A41, A41), -0.903: (A41, A41, A41), -0.722: (None, A41, A41), -0.654: (None, A41, A41),
        -0.620: (None, A41, A41), -0.575: (None, A41, A41), -0.502: (A42, A42, A41)}


class Clock:
    def __init__(self):
        self.t = 0.0

    def time(self):
        return self.t

    def sleep(self, s):
        pass


def make(clock, **kw):
    mv = NS(pad=NS(guard=lambda on: None, move=lambda x, y: None), face=lambda s, c, deg=0.0: None)
    r = R.Reflex(mv, **kw)
    acts = []
    real = r._act
    r._act = lambda act, c=None, s=None, start=None: (acts.append((act, getattr(c, "ptr", None))), real(act, c, s, start))[1]
    return r, acts


def step(r, acts, clock, s, prefer):
    """One tick; → row dict with what the choice was made from."""
    now = clock.t
    lp, lu = r._lock
    lock_used = (lp, None if lp is None else round(lu - T0, 3), lp is not None and now < lu)
    r.prefer = prefer
    acts.clear()
    ret = r.tick(s)
    got = acts[-1][1] if acts and acts[-1][0] is not None else None
    th = []
    for c in sorted(r.threats(s), key=lambda c: c.ptr):
        th.append((c.ptr, round(now - r._start[c.ptr], 3), round(r.threat_s(c), 3)))
    return {"t": round(now - T0, 3), "threats": th, "lock_used": lock_used, "prefer": prefer, "got": got, "ret": ret,
            "lock_after": (r._lock[0], None if r._lock[0] is None else round(r._lock[1] - T0, 3))}


def replay(kw) -> list[dict]:
    clock = Clock()
    saved = R.time
    R.time = clock
    try:
        r, acts = make(clock, **kw)
        r._anim = {A41: 3009, A42: 3003}                      # as the baseline: 255041's 3009 start isn't logged
        r._start = {A42: T0 - 2.842}
        rows = []
        for t, hp, f41, f42, want in S.TICKS:
            clock.t = T0 + t
            s = S.snap(t, hp, f41, f42)
            if want == "update":
                r.update(s)
                continue
            rows.append(step(r, acts, clock, s, A42))
        return rows
    finally:
        R.time = saved


NAME = {A41: "255041", A42: "255042", None: "-"}


def fmt(row) -> str:
    th = " ".join(f"{NAME[p]}(age {a:.3f}<{w:.3g})" for p, a, w in row["threats"]) or "없음"
    lp, lu, ok = row["lock_used"]
    lock = f"{NAME[lp]}~{lu:+.3f} {'유효' if ok else '만료'}" if lp is not None else "없음"
    return f"위협 [{th}] · 잠금 {lock} · prefer {NAME[row['prefer']]} → {NAME[row['got']]}"


def part1() -> None:
    print("== 1. 212954 n2, 세 구성 (실행 결과; 기대 = 손계산 HAND) ==")
    runs = {k: replay(kw) for k, kw in CONFIGS.items()}
    for i, row in enumerate(runs["now"]):
        t = row["t"]
        print(f"{t:+.3f}")
        for j, k in enumerate(CONFIGS):
            rw = runs[k][i]
            want = HAND[t][j]
            check(f"   {k:3s} {fmt(rw)}  (손계산 {NAME[want]})", rw["got"] == want and rw["ret"] == (want is not None))
    b = {r["t"]: r for r in runs["B"]}
    bt = {r["t"]: r for r in runs["B-t"]}
    check(f"B   −1.892 잠금 255041 만료 = −2.056 + {windup_s(NS(npc_param=255041, anim=3004)):.17g} → {b[-1.892]['lock_after'][1]:+.3f}",
          b[-1.892]["lock_after"] == (A41, 0.244))
    check(f"B-t −1.892 잠금 255041 만료 −0.756 (THREAT_S)", bt[-1.892]["lock_after"] == (A41, -0.756))
    check("−0.502 B-t: 두 적 다 위협, 잠금 만료 → prefer 255042",
          [p for p, _, _ in bt[-0.502]["threats"]] == [A41, A42] and not bt[-0.502]["lock_used"][2])
    check("−0.502 B : 두 적 다 위협, 잠금 255041 유효 → 255041",
          [p for p, _, _ in b[-0.502]["threats"]] == [A41, A42] and b[-0.502]["lock_used"][:1] == (A41,) and b[-0.502]["lock_used"][2])
    # explicit defaults = no arguments, row for row
    same = replay({"threat_s": lambda c: R.THREAT_S, "lock_s": lambda c: R.THREAT_S}) == runs["now"]
    check("기본값 명시(THREAT_S 두 개) = 인자 없음, 모든 틱 동일", same)


def chr_(ptr, npc, anim, d, deg=0.0) -> Chr:
    return S.foe(ptr, npc, anim, d, deg)


def snapshot(*cs) -> Snapshot:
    p = Chr(ptr=1, npc_param=0, team=1, hp=500, max_hp=500, x=0.0, y=0.0, z=0.0, sp=100, max_sp=100, heading=-math.pi)
    return Snapshot(t=0.0, player=p, chars=sorted(cs, key=lambda c: c.dist))


def run_seq(kw, seq, prefer=None):
    """seq: [(t, [foes])] from a fresh Reflex; t absolute on a 1024 s clock (binary-exact sums). → [(got, row)]"""
    clock = Clock()
    saved = R.time
    R.time = clock
    try:
        r, acts = make(clock, **kw)
        out = []
        for t, cs in seq:
            clock.t = 1024.0 + t
            row = step(r, acts, clock, snapshot(*cs), prefer)
            out.append((row["got"], row, r))
        return out
    finally:
        R.time = saved


def part2() -> None:
    print("== 2. 경계 ==")
    # fallback
    w = lambda npc, a: windup_s(NS(npc_param=npc, anim=a))
    check(f"fallback: 255041 3004 → {w(255041, 3004):.17g} (= 2.1 + 0.2, float으로 2.3보다 큼)", w(255041, 3004) == 2.1 + 0.2 > 2.3)
    check(f"fallback: 255041 3000 (windup 아닌 공격) → {w(255041, 3000)}", w(255041, 3000) == R.THREAT_S)
    check(f"fallback: 255042 3004 (windup 없음) → {w(255042, 3004)}", w(255042, 3004) == R.THREAT_S)
    check(f"fallback: 모르는 npc 999999 · npc None → {w(999999, 3004)} · {w(None, 3004)}",
          w(999999, 3004) == R.THREAT_S and w(None, 3004) == R.THREAT_S)
    check(f"fallback: 254001 3004 (도끼 망자 windup 1.7) → {w(254001, 3004):.3g} · 254000 3004 → {w(254000, 3004)}",
          abs(w(254001, 3004) - 1.9) < 1e-9 and w(254000, 3004) == R.THREAT_S)

    # window edge: dyadic windows so start + age is exact. threat is age < window; lock is now < start + window
    W = 2.25
    eps = 1 / 64
    for kw, name in (({"threat_s": lambda c: W}, "위협 창"), ({"threat_s": lambda c: W, "lock_s": lambda c: W}, "위협+잠금 창")):
        res = run_seq(kw, [(0.0, [chr_(7, 1, 3004, 1.0)]), (W - eps, [chr_(7, 1, 3004, 1.0)]),
                           (W, [chr_(7, 1, 3004, 1.0)]), (W + eps, [chr_(7, 1, 3004, 1.0)])])
        got = [g for g, _, _ in res]
        check(f"{name} {W}: age 0 · {W - eps} · {W} · {W + eps} → {got} (age < 창만 위협, 정확히 경계는 아님)",
              got == [7, 7, None, None])
    # lock edge on its own: two threats, lock window shorter than the threat window. Lock on 7 (prefer) holds until exactly 1.25,
    # at 1.25 the lock has lapsed and prefer (switched to 8) decides
    kw = {"threat_s": lambda c: 2.25, "lock_s": lambda c: 1.25}
    clock = Clock()
    saved = R.time
    R.time = clock
    try:
        r, acts = make(clock, **kw)
        seq = []
        for t, pref in ((0.0, 7), (1.25 - eps, 8), (1.25, 8)):
            clock.t = 1024.0 + t
            seq.append(step(r, acts, clock, snapshot(chr_(7, 1, 3004, 1.0), chr_(8, 2, 3004, 1.5)), pref)["got"])
    finally:
        R.time = saved
    check(f"잠금 경계 1.25: 0 (prefer 7) · {1.25 - eps} (prefer 8, 잠금 유효) · 1.25 (잠금 만료) → {seq}", seq == [7, 7, 8])

    # anim change: 3004 → 3000 resets the attack start; a valid lock keeps its old expiry (set only when re-chosen)
    for kw, name, want_until in (({"threat_s": lambda c: 1.25, "lock_s": lambda c: 1.25}, "1.25/1.25 (THREAT_S 대용, 2진 정확값)", 1.25),
                                 ({"threat_s": lambda c: 2.25, "lock_s": lambda c: 2.25}, "2.25/2.25", 2.25)):
        res = run_seq(kw, [(0.0, [chr_(7, 1, 3004, 1.0)]), (1.0, [chr_(7, 1, 3000, 1.0)])])
        r = res[-1][2]
        check(f"애니 전환 {name}: 1.0 s에 3004→3000 → 시작 {r._start[7] - 1024:.2f}로 재설정, 잠금 만료는 옛 시작 기준 {r._lock[1] - 1024:.2f}",
              r._start[7] - 1024 == 1.0 and r._lock == (7, 1024.0 + want_until) and res[-1][0] == 7)
        # past the old lock expiry, still threatened by the new attack → re-chosen, lock from the new start
        res = run_seq(kw, [(0.0, [chr_(7, 1, 3004, 1.0)]), (1.0, [chr_(7, 1, 3000, 1.0)]), (want_until + 0.5, [chr_(7, 1, 3000, 1.0)])])
        r = res[-1][2]
        new_until = 1.0 + kw["lock_s"](None)
        alive = want_until + 0.5 - 1.0 < kw["threat_s"](None)
        check(f"애니 전환 {name}: {want_until + 0.5} s → 새 공격 {'위협' if alive else '창 지남'}, 잠금 {r._lock[1] - 1024:.2f}",
              (res[-1][0] == 7 and r._lock == (7, 1024.0 + new_until)) if alive else res[-1][0] is None)
    # stagger in between (3004 → 3500 → 3004): the second 3004 is a new attack
    res = run_seq({}, [(0.0, [chr_(7, 1, 3004, 1.0)]), (0.5, [chr_(7, 1, 3500, 1.0)]), (0.75, [chr_(7, 1, 3004, 1.0)])])
    check(f"3004→3500→3004: 경직 중 위협 아님 ({res[1][0]}), 다시 3004면 시작 0.75 ({res[2][2]._start[7] - 1024})",
          res[1][0] is None and res[2][0] == 7 and res[2][2]._start[7] - 1024 == 0.75)

    # two threats: lock > prefer > nearest
    near, far = chr_(7, 1, 3004, 1.0), chr_(8, 2, 3004, 2.0)
    res = run_seq({}, [(0.0, [near, far])], prefer=8)
    check(f"두 위협, 잠금 없음, prefer 8(먼 쪽) → {res[0][0]}", res[0][0] == 8)
    res = run_seq({}, [(0.0, [near, far])], prefer=None)
    check(f"두 위협, prefer 없음 → 가까운 쪽 {res[0][0]}", res[0][0] == 7)
    res = run_seq({}, [(0.0, [near, far])], prefer=99)
    check(f"두 위협, prefer가 위협 아님 → 가까운 쪽 {res[0][0]}", res[0][0] == 7)
    clock = Clock()
    saved = R.time
    R.time = clock
    try:
        r, acts = make(clock)
        clock.t = 1024.0
        a = step(r, acts, clock, snapshot(chr_(7, 1, 3004, 1.0), chr_(8, 2, 3000, 2.0)), 7)["got"]
        clock.t = 1024.5
        b = step(r, acts, clock, snapshot(chr_(7, 1, 3004, 1.0), chr_(8, 2, 3000, 2.0)), 8)["got"]
    finally:
        R.time = saved
    check(f"두 위협, 잠금 7 유효 + prefer 8 → 잠금이 이김 ({a} → {b})", (a, b) == (7, 7))


def main() -> None:
    part1()
    part2()
    print("p89_reflex_window_test: all ok")


if __name__ == "__main__":
    main()
