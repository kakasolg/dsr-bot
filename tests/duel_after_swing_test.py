"""휘두름 끝 반격 오프라인 테스트 — souls/duel.rule_after_swing ([MoKa] 2026-10-06).

  "상대가 휘두르는 애니 끝나면 무조건 공격해야해 … 다음 텀 기다리면 다대일 되서 좋을게 없어"
  끝난 틱(공격 애니에서 벗어남 / SWING_S 넘김) 뒤 AFTER_SWING_S 안: 45° 안이면 바로, 닿는 거리 + 1.2 m 안이면 한 걸음 들어가 침,
  방패병은 발차기 콤보, 옆에 다른 적이 있으면 한 번만, 다른 놈이 휘두르는 중이면 안 침

  python tests/duel_after_swing_test.py
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import sys
import time
from types import SimpleNamespace as NS

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from souls import duel as D
from souls import moves as M
from souls import weapons

fails = 0


def check(name, cond):
    global fails
    print(("  ok   " if cond else "  FAIL ") + name)
    fails += 0 if cond else 1


D._slam = lambda F, s, c, swinging=False: None          # no wall heavy in these cases


def setup(h=1.2, shield=False, others=(), aimed=True, sp=98):
    calls = []
    foe = NS(ptr=7, x=0.0, y=0.0, z=h, hp=75, anim=3003, npc_param=254010)
    chars = [foe] + list(others)
    player = NS(x=0.0, y=0.0, z=0.0, hp=742, max_hp=742, sp=sp, anim=-1, heading=0.0)
    s = NS(player=player, chars=chars, cam_yaw=0.0, hostile=lambda r: [c for c in chars if M.horiz(player, c) < r])
    mv = NS(face=lambda s_, c_, deg=20.0: calls.append(("face", deg)) or aimed,
            pad=NS(move=lambda x, y: calls.append(("move", round(x, 2), round(y, 2)))),
            stick_to=lambda s_, x, z, sc=1.0: (0.0, sc), snap=lambda r=5.0: s,
            find=lambda s_, ptr: next((c for c in chars if c.ptr == ptr), None),
            light=lambda s_, c_, n=1, sp_second=None: calls.append(("light", n)) or M.Hit("light", presses=n, dmg=75, dead=True),
            kick_combo=lambda s_, c_, n=1: calls.append(("kick", n)) or M.Hit("kick+light", presses=n + 1, dmg=85, dead=True),
            guard=lambda on: calls.append(("guard", on)))
    F = NS(weapon=weapons.BATTLE_AXE, ptr=7, foe=NS(kick_when_idle=shield), mv=mv, reflex=NS(_start={7: time.time() - 0.9}),
           record=lambda hit: None, note=lambda *a: None, log=lambda *a: None, killed_if=lambda dead: "killed" if dead else D.CONT)
    T = NS(a=3003, age=0.9, now=time.time(), h=h, dy=0.0, p=player, c=foe, s=s)
    return F, T, foe, calls


def swing_then_end(F, T, foe, end_anim=-1):
    D.rule_after_swing(F, T)                           # still swinging → remembers the anim, does nothing
    foe.anim, T.a, T.age, T.now = end_anim, end_anim, None, time.time()
    return D.rule_after_swing(F, T)


F, T, foe, calls = setup()
r0 = D.rule_after_swing(F, T)
check("mid-swing → nothing yet", r0 is None and calls == [])
foe.anim, T.a, T.age, T.now = -1, -1, None, time.time()
r = D.rule_after_swing(F, T)
check("swing ends (3003 → −1) within reach → light at once", r == "killed" and ("light", F.weapon.combo) in calls)

F, T, foe, calls = setup(h=F.weapon.reach + 0.8)
r = swing_then_end(F, T, foe)
check("swing ends 0.8 m beyond reach → step in, then strike (no waiting)",
      r == "killed" and any(c[0] == "move" for c in calls) and any(c[0] == "light" for c in calls))

F, T, foe, calls = setup(h=F.weapon.reach + 2.0)
check("too far (2 m beyond reach) → not this rule", swing_then_end(F, T, foe) is None)

F, T, foe, calls = setup(shield=True)
r = swing_then_end(F, T, foe)
check("shield soldier → kick combo (it raises the shield when idle)", r == "killed" and ("kick", F.weapon.combo) in calls)

other = NS(ptr=9, x=3.0, y=0.0, z=0.0, hp=75, anim=-1, npc_param=254011)
F, T, foe, calls = setup(others=[other])
r = swing_then_end(F, T, foe)
check("another foe 3 m away → one hit, then the shield", ("light", 1) in calls and ("guard", True) in calls)

swinger = NS(ptr=9, x=1.5, y=0.0, z=0.0, hp=75, anim=3000, npc_param=254011)
F, T, foe, calls = setup(others=[swinger])
check("another foe mid-swing next to us → don't (block it)", swing_then_end(F, T, foe) is None)

F, T, foe, calls = setup(aimed=False)
r = swing_then_end(F, T, foe)
check("more than 45° off → this tick turns (CONT), no strike yet", r == D.CONT and not any(c[0] == "light" for c in calls))

F, T, foe, calls = setup()
D.rule_after_swing(F, T)
foe.anim, T.a, T.age, T.now = -1, -1, None, time.time() + D.AFTER_SWING_S + 0.1
D.rule_after_swing(F, T)
F._swing_end_t = time.time() - D.AFTER_SWING_S - 0.1
check("window passed → not this rule", D.rule_after_swing(F, T) is None)

F, T, foe, calls = setup()
T.age = D.SWING_S + 0.1                                # a long 30xx that lingers (prep_linger's rule): counts as the end
r = D.rule_after_swing(F, T)
check("attack anim lingering past SWING_S → counts as ended → strike", r == "killed")

F, T, foe, calls = setup(sp=5)
check("no stamina → not this rule", swing_then_end(F, T, foe) is None)

print(f"\n{'all ok' if not fails else f'{fails} FAILED'}")
sys.exit(1 if fails else 0)
