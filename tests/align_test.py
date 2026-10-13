"""Target–body–camera alignment record ([MoKa] 10-11: "공격 대상과 캐릭터 정렬, 카메라 방향 일치도 우선순위가 높은 작업";
10-01: alignment decides whether a move works). Record only — nothing here changes what the bot does. No game.

  python tests/align_test.py

  · Moves.align_of: one row — body / camera off the target (°), distance, lock, ok (body ≤ 30° or locked)
  · @_aligned: an attack press is recorded once (with its damage) when Moves.align_sink is set, and costs nothing when it isn't
  · CamFollow.measure / on_attack / align_stats: per-tick rows in / out of fights, an "align" event every ALIGN_EVERY s,
    the end-of-run line with "hit when aligned vs not"
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import math
import sys
from types import SimpleNamespace as NS

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from souls import camera
from souls import moves as M


def check(name: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        raise SystemExit(1)


def snap(body_deg: float, cam_deg: float, d: float = 2.0):
    """Me at the origin, the target straight ahead along +z at d m; body turned body_deg and camera cam_deg away from it
    (+ = the target is to the right). world yaw = heading + π (moves.rel_angle)."""
    p = NS(x=0.0, y=0.0, z=0.0, heading=-math.pi - math.radians(body_deg))
    return NS(player=p, cam_yaw=-math.radians(cam_deg)), NS(ptr=7, x=0.0, y=0.5, z=d, npc_param=254010)


def moves(lock_on=None):
    m = M.Moves.__new__(M.Moves)
    m.tm = NS(lock_target=lambda: lock_on, handle=lambda ptr: 70 if ptr == 7 else None)
    m.align_sink = None
    return m


def main() -> None:
    m = moves()
    s, c = snap(12.0, 4.0)
    r = m.align_of(s, c)
    check(f"align_of: body +12°, camera +4°, 2 m, not locked → ok ({r})",
          abs(r["body"] - 12.0) < 0.2 and abs(r["cam"] - 4.0) < 0.2 and r["d"] == 2.0 and r["dy"] == 0.5 and not r["lock"] and r["ok"])
    s, c = snap(-45.0, 4.0)
    check("align_of: body −45° → not ok", m.align_of(s, c)["ok"] is False and m.align_of(s, c)["body"] < -44)
    s, c = snap(10.0, 35.0)
    check("align_of: camera 35° off, body +10° → ok (camera not judged, MoKa 10-13)", m.align_of(s, c)["ok"] is True)
    lm = moves(lock_on=70)
    check("align_of: camera 35° off but locked on it → ok (lock-on holds the camera)", lm.align_of(s, c)["ok"] and lm.align_of(s, c)["lock"])
    s.player.heading = None
    check("align_of: no heading → body None, not ok (not locked)", m.align_of(s, c)["body"] is None and not m.align_of(s, c)["ok"])

    # the decorator: one row per press, with the damage; nothing when no sink
    class Fake(M.Moves):
        def __init__(self):
            self.tm, self.align_sink, self.calls = NS(lock_target=lambda: None, handle=lambda p: None), None, 0

        @M._aligned(0)
        def light(self, s, c, n=1):
            self.calls += 1
            return NS(kind="light", dmg=31)

        @M._aligned(1)
        def combo(self, name, s, c):
            self.calls += 1
            return NS(kind=name, dmg=0)
    f = Fake()
    s, c = snap(5.0, 2.0)
    f.light(s, c)
    check("no sink → the attack runs, nothing recorded", f.calls == 1)
    rows = []
    f.align_sink = lambda **k: rows.append(k)
    f.light(s, c, n=2)
    f.combo("backstep_r1", *snap(50.0, 2.0))
    check("sink → one row per press with kind, damage and alignment at the press",
          [(r["kind"], r["dmg"], r["ok"]) for r in rows] == [("light", 31, True), ("backstep_r1", 0, False)] and f.calls == 3)
    f.align_sink = lambda **k: 1 / 0
    check("a failing sink never breaks the attack", f.light(s, c).dmg == 31)

    # CamFollow: per-tick rows, throttled events, attacks, the end line
    ev = []
    mv = NS(cam_target=7, align_of=m.align_of, LOOK_SIGN=1)
    cf = camera.CamFollow(mv, log=lambda *a: None, events=lambda e, **k: ev.append((e, k)))
    cf.src = "fight"
    for b in (5.0, 10.0, 20.0, 60.0):
        cf.measure(*snap(b, 3.0))
    mv.cam_target = None
    cf.src = "last"
    cf.measure(*snap(120.0, 3.0))
    check("measure: 4 rows in the fight, 1 outside", len(cf.align[True]) == 4 and len(cf.align[False]) == 1)
    check(f"'align' events throttled to one per {camera.ALIGN_EVERY} s, with src and fight",
          len([e for e, _ in ev if e == "align"]) == 1 and ev[0][1]["src"] == "fight" and ev[0][1]["fight"] is True)
    cf.on_attack(kind="light", dmg=40, ok=True, body=5.0)
    cf.on_attack(kind="light", dmg=0, ok=False, body=50.0)
    cf.on_attack(kind="kick", dmg=0, ok=True, body=8.0)
    line = cf.align_stats()
    check(f"align_stats: in-fight 75 % ≤ 30°, attacks aligned 67 %, hit 1/2 aligned vs 0/1 not ({line})",
          "싸움 중 몸 중앙" in line and "30° 안 75%" in line and "공격 3번: 정렬 67%" in line and "맞힘 정렬 1/2 / 어긋남 0/1" in line
          and "싸움 밖" in line)
    check("attack_align events", len([e for e, _ in ev if e == "attack_align"]) == 3)
    check("nothing recorded → '기록 없음'", camera.CamFollow(NS(cam_target=None, LOOK_SIGN=1), log=print).align_stats().endswith("기록 없음"))
    print("align_test: all ok")


if __name__ == "__main__":
    main()
