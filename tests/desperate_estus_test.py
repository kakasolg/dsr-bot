"""석궁만 남은 저HP 에스트 · 구역 8 사다리 전 에스트 — 오프라인 테스트 (MoKa 11-01 "가)+나) 고치기", run 214607).

  python tests/desperate_estus_test.py

Fake snapshots / fields only — not a game check.
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import sys
from types import SimpleNamespace as NS

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from souls import field as F
from souls import missions as MS

CROSSBOW, SPEAR = 255002, 255001


def snap(hp, foes):
    cs = [NS(npc_param=n, dist=d, hp=85, anim=a) for n, d, a in foes]
    return NS(player=NS(hp=hp, max_hp=719), hostile=lambda r: [c for c in cs if c.dist <= r])


def test_desperate_only_throwers() -> None:
    d = lambda s: F.Field.desperate(None, s)       # noqa: E731 — uses no instance state
    # 214607 445.0 s: HP 116, crossbows at 6.8 m (3000) and 8.1 m (3001) → was "안 마심"; now drinks
    assert d(snap(116, [(CROSSBOW, 6.8, 3000), (CROSSBOW, 8.1, 3001)]))
    assert not d(snap(400, [(CROSSBOW, 6.8, 3000)]))                    # not low: the old rule stands
    assert not d(snap(116, [(CROSSBOW, 3.0, 3000)]))                    # a crossbow inside DESPERATE_R still blocks
    assert not d(snap(116, [(CROSSBOW, 8.0, 3000), (SPEAR, 5.0, -1)]))  # an awake melee foe within SAFE_R blocks
    assert d(snap(116, [(CROSSBOW, 8.0, 3000), (SPEAR, 7.0, -1)]))      # melee beyond SAFE_R: drinks
    assert d(snap(116, [(SPEAR, 2.0, 9000)]))                           # asleep (9000s) doesn't count
    print("ok  desperate: HP < 30 %, only throwers awake and none within 4 m → drink; melee < 6 m or anything < 4 m → no")


def test_heal_uses_desperate() -> None:
    sips = []
    s = snap(116, [(CROSSBOW, 6.8, 3000)])
    f = F.Field.__new__(F.Field)
    f.log = lambda *a, **k: None
    f.repair = lambda: None
    f.events = lambda *a, **k: None
    f.estus_left = lambda: 5
    f.mv = NS(snap=lambda t: s, drink=lambda ok: sips.append(ok(s)) or {"ok": True})
    f.heal(0.7, sips=1)
    assert sips == [True], sips
    sips.clear()
    s = snap(116, [(SPEAR, 1.5, 3000)])
    f.heal(0.7, sips=1)
    assert sips == [], sips
    print("ok  heal: crossbow-only low HP → drink (and the re-check after selecting passes); spear at 1.5 m → no sip")


def test_zone8_ladder_heals_first() -> None:
    lad = next(st["ladder"] for st in MS.UPPER["zones"][7]["before"] if "ladder" in st)
    assert lad.get("heal_first") == 0.9
    calls = []
    m = MS.Missions.__new__(MS.Missions)
    m.log = lambda *a, **k: None
    hp = [521]
    m.mv = NS(snap=lambda t: NS(player=NS(hp=hp[0], max_hp=719, y=0.0)))
    m.f = NS(heal=lambda frac, sips=3: calls.append(frac), walk_to=lambda *a, **k: "dead", alive=lambda: False)
    step = {"ladder": dict(lad, approach=None)}
    m._before(step, None, "구역8")                  # walk_to → 'dead' ends it right after the heal check
    assert calls == [0.9], calls
    calls.clear()
    hp[0] = 700
    m._before(step, None, "구역8")
    assert calls == [], calls
    print("ok  zone 8 ladder: HP 521/719 (214607) → estus to 90 % before climbing; 700/719 → straight up")


def test_zone8_hold_no_retreat() -> None:
    """hold: wait at F9#8, then fight with desperate=True (no low_hp exit), drink between fights — no recover() back-off."""
    from souls import field as F_
    foe = NS(ptr=1, npc_param=CROSSBOW, x=61.0, y=23.7, z=-117.0, hp=85, anim=3000)
    calls = []
    m = MS.Missions.__new__(MS.Missions)
    m.log = lambda *a, **k: None
    m._wait_at_safe = lambda ptr, safe, secs: calls.append(("wait", secs)) or True
    m._first_foe = lambda ptr: ptr
    m.mv = NS(snap=lambda r: NS(), find=lambda s, ptr: foe if foe.hp > 0 else None)

    def fight(ptr, nb, tag, desperate=False, **k):
        calls.append(("fight", desperate))
        if len([c for c in calls if c[0] == "fight"]) == 2:
            foe.hp = 0
            return NS(result="killed")
        return NS(result="low_hp")
    m.f = NS(alive=lambda: True, fight=fight, heal=lambda frac, sips=3: calls.append(("heal", frac)),
             find_at=lambda npc, pos, r: foe, recover=lambda *a, **k: calls.append(("recover",)) or True)
    r = m._pull_to_safe(CROSSBOW, (52.9, 23.8, -119.8), (61.95, 23.7, -116.93), None, "구역8-1", {"hold": 20})
    assert r == "killed", r
    assert calls == [("wait", 20.0), ("fight", True), ("heal", MS.UPPER_HEAL_FRAC), ("fight", True), ("heal", MS.UPPER_HEAL_FRAC)], calls
    print("ok  zone 8 hold: wait 20 s at F9#8 → fight with no retreat → drink → fight again; recover() never called")


if __name__ == "__main__":
    test_desperate_only_throwers()
    test_heal_uses_desperate()
    test_zone8_ladder_heals_first()
    test_zone8_hold_no_retreat()
