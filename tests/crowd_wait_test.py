"""P-140 붙어 선 무리에 나이프 없이 달려들지 않음 (Missions._lure). [MoKa] 11-08 "계단 위에 있을때 이미 적 하나가 캐릭터를 봐서
기다리면 하나만 와. 그걸 기다리면 되는데 달려드네". Fakes only — no game, no pad.  python tests/crowd_wait_test.py"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

from types import SimpleNamespace as NS

if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8")

from souls import missions as MS

SAFE = (11.2, -6.6, -92.8)                                         # 구역 4 계단 위 안전 자리


def mission(knife: bool, came: bool, crowd: bool = True):
    # 221120 233.8 s: 254011 (17.8, −103.7) · 254010 (15.5, −103.6) · 254012 — 서로 2–3 m, 아무도 안 움직임
    t = NS(ptr=5, npc_param=254011, x=17.8, y=-5.7, z=-103.7, hp=75, anim=-1)
    nb_ = NS(ptr=6, npc_param=254010, x=15.5 if crowd else 30.0, y=-5.7, z=-103.6, hp=75, anim=-1)
    snap = NS(player=NS(x=SAFE[0], y=SAFE[1], z=SAFE[2], hp=682), hostile=lambda r: [t, nb_])
    calls, logs = [], []
    m = MS.Missions.__new__(MS.Missions)
    m.log = logs.append
    m.zone_n = 4
    m.hold_why = None
    m._has = lambda item: knife
    m.mv = NS(snap=lambda r: snap, find=lambda s, ptr: t, pad=NS())
    m.f = NS(lure=lambda *a, **k: calls.append(("knife",)) or "lured", alive=lambda: True)
    m._wait_at_safe = lambda ptr, safe_, secs, **k: calls.append(("wait", secs)) or came
    m._sprint = lambda *a, **k: calls.append(("sprint",)) or "arrived"
    return m, t, calls, logs


def main() -> None:
    m, t, calls, logs = mission(knife=False, came=True)
    r = m._lure(t, t.ptr, SAFE, None, "구역4-1 254011", {})
    assert r == "here" and calls == [("wait", MS.CROWD_WAIT_S)], (r, calls)
    print(f"ok  crowd, no knife → guard at the safe spot {MS.CROWD_WAIT_S:g} s; one came → 'here' (no run in)")

    m, t, calls, logs = mission(knife=False, came=False)
    m._lure(t, t.ptr, SAFE, None, "구역4-1 254011", {})
    assert calls[0] == ("wait", MS.CROWD_WAIT_S) and ("sprint",) in calls, calls
    assert any("기다려도 안 옴" in line for line in logs), logs
    print("ok  nobody came in that time → the old body run (logged)")

    m, t, calls, logs = mission(knife=True, came=True)
    r = m._lure(t, t.ptr, SAFE, None, "구역4-1 254011", {})
    assert r == "here" and calls[0] == ("knife",) and ("wait", MS.CROWD_WAIT_S) not in calls, calls
    print("ok  with knives the knife lure stays first (no extra crowd wait)")

    m, t, calls, logs = mission(knife=False, came=True, crowd=False)
    m._lure(t, t.ptr, SAFE, None, "구역4-1 254011", {})
    assert ("wait", MS.CROWD_WAIT_S) not in calls, calls
    print("ok  a lone target → no crowd wait (unchanged)")


if __name__ == "__main__":
    main()
