"""3+ foes coming = failure (souls/watch.Escape._crowd3): far → menu quit-out, close → warp only with --crowd-warp (no game).
  python tests/crowd3_test.py

[MoKa] 2026-11-04: "5명이 몰려 오면, 고수 들도 답이 없어. 그냥 quit menu 해서 몹들이 원위치로 보내는 것이 최선이야. 문제는 적들
근처에서는 quit menu도 소용 없으니 그때는 화톳불 근처로 워프가 다음 해법이지. 일단 3명 이상 몰려 오면 실패라고 생각해야되."
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import sys
from types import SimpleNamespace as NS

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from souls.watch import Escape


def check(name: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        raise SystemExit(1)


def esc(warp=False):
    ev = []
    e = Escape(pad=None, nms=[], log=lambda *_: None, events=lambda _ev, **k: ev.append((_ev, k)))
    e.crowd_warp = warp
    return e, ev


def snap(dists, anim=-1, dy=0.0):
    me = NS(x=0.0, y=0.0, z=0.0)
    cs = [NS(x=d, y=dy, z=0.0, hp=50, anim=anim) for d in dists]
    return NS(player=me, hostile=lambda r: [c for c in cs if abs(c.x) <= r]), me


def run(e, s, p, t0=100.0):
    first = e._crowd3(s, p, t0)
    return first, e._crowd3(s, p, t0 + Escape.CROWD3_HOLD + 0.01)


def main() -> None:
    e, ev = esc()
    s, p = snap([6.0, 7.5, 9.0])
    first, (why, kind) = run(e, s, p)
    check("셋 깨어 6–9 m, 0.3 s 이어짐 → 메뉴 퀵 종료", first == (None, None) and kind == "crowd3" and "실패" in why)
    check("crowd3 이벤트 action quit", ev and ev[-1][0] == "crowd3" and ev[-1][1]["action"] == "quit")
    e, ev = esc()
    s, p = snap([6.0, 7.5])
    check("둘이면 안 함", run(e, s, p)[1] == (None, None) and not ev)
    e, ev = esc()
    s, p = snap([6.0, 7.5, 9.0], anim=9000)
    check("자는 놈 (애니 9000대) 셋 → 안 함", run(e, s, p)[1] == (None, None))
    e, ev = esc()
    s, p = snap([6.0, 7.5, 9.0], dy=4.0)
    check("높이 차 4 m (다른 층) 셋 → 안 함", run(e, s, p)[1] == (None, None))
    e, ev = esc()
    s, p = snap([1.5, 3.0, 5.0])
    check("붙어 있음 (1.5 m) · 워프 꺼짐 → 안 나감, 기록만", run(e, s, p)[1] == (None, None)
          and ev[-1][1]["action"] == "close_no_warp")
    e, ev = esc(warp=True)
    s, p = snap([1.5, 3.0, 5.0])
    check("붙어 있음 · --crowd-warp → 워프", run(e, s, p)[1][1] == "crowd3_warp" and ev[-1][1]["action"] == "warp")
    e, ev = esc()
    e.crowd3_n = Escape.CROWD3_MAX
    s, p = snap([6.0, 7.5, 9.0])
    check(f"이 실행에서 {Escape.CROWD3_MAX}번 나간 뒤 → 기록만", run(e, s, p)[1] == (None, None) and ev[-1][1]["action"] == "capped")

    # P-126: a successful warp counts in Escape.warps; the burg-upper zone stops on a change ('warped' → run_zones rests and restarts)
    from souls import missions as M
    e, ev = esc(warp=True)
    e.pad = NS(freeze=lambda: None, neutral=lambda: None, unfreeze=lambda: None)
    import time as _t
    sleep0, _t.sleep = _t.sleep, lambda s: None
    try:
        e.warp_last("test", NS(last_bonfire=lambda: 1012962, bonfire_warp=lambda bid, log=None: True), None)
        ok1 = e.warps == 1
        e.warp_last("test", NS(last_bonfire=lambda: 1012962, bonfire_warp=lambda bid, log=None: False), None)
    finally:
        _t.sleep = sleep0
    check("워프 성공만 warps에 셈", ok1 and e.warps == 1)
    ms = M.Missions.__new__(M.Missions)
    ms.f, ms.log = NS(esc=e), (lambda *_: None)
    check("구역: warps 그대로면 계속, 바뀌면 'warped'", not ms._warped(1, "t") and ms._warped(0, "t"))


if __name__ == "__main__":
    main()
