"""[cloud] 10-01 검토에서 고친 셋 — 오프라인 테스트 (ROADMAP "10. 게시판 중계" 2026-10-01 [win] 작업 검토 2~4번).

  2. 'losing'으로 끝난 싸움은 HP가 60 % 위여도 물러남 (Field.recover)
  3. rule_face_first는 prep_reflex 뒤 — 도는 틱에도 반사에 스냅이 들어감. 목표가 4 m 밖이어도 옆 다른 적이 휘두르면 방패 듦
  4. 휴식·리스폰 뒤 끌어오기 실패 기억(_careful_lured)을 비움 (Field.forget_foes)

  python tests/review_1001_test.py
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import math
import sys
import types

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from field_fakes import World, make_field
from souls import duel as D
from souls import field as F


def _recover_field(hp: int):
    w = World(player=(0.0, -49.4, 0.0), hp=hp)
    w.add(2, 0x1018, 254010, (0.0, -49.4, 5.0), anim=-1)          # awake-ish foe 5 m off: not 'safe', not stuck on us (no roll)
    f = make_field(w)
    f.recover = types.MethodType(F.Field.recover, f)
    f.safe = lambda s: False
    f.retreats = []
    f.retreat = lambda nm, home: (f.retreats.append(home), "safe")[1]
    f.heal = lambda *a, **k: None
    f.home = (0.0, -49.4, -20.0)
    return f


def test_losing_backs_off() -> None:
    hp = int(793 * 0.65)                                               # a full start minus LOSING_TAKEN
    f = _recover_field(hp)
    f.recover("#3 losing", None)
    assert f.retreats, f.logs
    f = _recover_field(hp)
    f.recover("#3 timeout", None)                                      # anything else above 60 %: stays as before
    assert not f.retreats, f.logs
    print("ok  'losing' at 65 % HP backs off; 'timeout' at 65 % does not")


def test_face_first_after_reflex_and_guards_for_others() -> None:
    assert D.RULES.index(D.prep_reflex) < D.RULES.index(D.rule_face_first), "face-first must come after prep_reflex"
    pad = []
    mv = types.SimpleNamespace(guard=lambda on: pad.append(("guard", on)), face=lambda s, c, deg=20.0: pad.append(("face",)))
    Fi = types.SimpleNamespace(style=types.SimpleNamespace(shield=True), mv=mv, note=lambda *a: None)
    p = types.SimpleNamespace(x=0.0, y=0.0, z=0.0, heading=0.0, anim=-1)         # facing −z (facing = heading + π)
    c = types.SimpleNamespace(x=0.0, y=0.0, z=6.0, anim=-1)                       # target 6 m behind us (+z)
    other = types.SimpleNamespace(x=2.0, y=0.0, z=-1.0, anim=3000)                # another foe swinging 2.2 m off
    T = types.SimpleNamespace(s=types.SimpleNamespace(cam_yaw=0.0), c=c, p=p, h=6.0, near45=[other])
    assert D.rule_face_first(Fi, T) is D.CONT
    assert ("guard", True) in pad and ("face",) in pad, pad
    pad.clear()
    other.anim = -1                                                              # nobody swinging, target 6 m: turn without the shield
    assert D.rule_face_first(Fi, T) is D.CONT
    assert ("guard", True) not in pad and ("face",) in pad, pad
    print("ok  face-first runs after prep_reflex; shield up while turning when another foe within 4.5 m swings")


def test_forget_foes_on_rest() -> None:
    w = World(player=(0.0, -49.4, 0.0))
    f = make_field(w)
    f._careful_lured = {0x2000: 2}
    f.mv.rest = lambda nm, bonfire: True
    assert F.Field.rest_at(f, None, {"stand": (0.0, -49.4, 0.0)})
    assert "_careful_lured" not in vars(f)
    f._careful_lured = {0x2000: 2}
    f.mv.snap = lambda within=5.0: w.snapshot()                                   # standing at full HP after a respawn
    assert F.Field.wait_respawn(f, timeout=2.0)
    assert "_careful_lured" not in vars(f)
    print("ok  rest / respawn forgets the failed pulls (revived foes can reuse a pointer)")


if __name__ == "__main__":
    test_losing_backs_off()
    test_face_first_after_reflex_and_guards_for_others()
    test_forget_foes_on_rest()
    print("전부 통과")
