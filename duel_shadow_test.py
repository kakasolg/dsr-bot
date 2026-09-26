"""Patch D 오프라인 테스트 — 방패병 빠른 발차기(원시 애니 3004·3500)는 기본 'shadow': 발차기 안 하고 후보 사건만.

  python duel_shadow_test.py
"""
from __future__ import annotations

import sys
from dataclasses import replace

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from field_fakes import FakeMv, World
from souls import duel as D
from souls import foes
from souls import moves as M
from souls import weapons

AXE = weapons.BATTLE_AXE


def test_candidate_truth_table() -> None:
    S = foes.SHIELD
    cand = lambda a, age, h, sp=90, oth=False, dy=0.0, foe=S: D._early_kick_candidate(foe, a, age, h, dy, sp, AXE, oth)
    assert cand(3004, 0.5, 1.2) is True
    assert cand(3004, 1.3, 1.2) is False                      # windup_act_s 넘음
    assert cand(3500, None, 1.5) is True                      # STAGGER
    assert cand(3500, None, 1.5, oth=True) is False           # 옆에서 다른 놈이 휘두름
    assert cand(3500, None, 1.5, sp=AXE.sp_min - 1) is False  # 스태미나 모자람
    assert cand(3500, None, AXE.reach + 0.5) is False         # 닿는 거리 밖
    assert cand(3500, None, 1.5, dy=1.5) is False             # 높이차
    assert cand(3500, None, 1.5, foe=foes.HOLLOW) is False    # 방패병 아님
    print("ok  _early_kick_candidate truth table (windup age, STAGGER, other attacker, SP, reach, dy, foe)")


def test_shadow_dedupe_and_outcome() -> None:
    evs = []
    sk = D.ShadowKick(log=lambda *a: None, events=lambda k, **kw: evs.append((k, kw)), gen=0)
    w = World()
    w.add(2, 0x1018, 255010, (1.0, -49.4, 0.0), hp=85, max_hp=85)
    t = 100.0
    for k in range(10):                                        # 같은 시작의 3500 을 10 틱 동안 봄
        sk.note_anim(2, 3500, t + 0.05 * k)
        sk.observe(t + 0.05 * k, 2, 0x1018, 255010, 3500, None, 1.2, 0.0, 90, 106, 0, 793, 85)
    assert [k for k, _ in evs] == ["shadow_kick"], evs
    e = evs[0][1]
    for f in ("key", "handle", "gen", "ptr", "anim", "age", "h", "dy", "sp", "max_sp", "hostiles_4_5m"):
        assert f in e, f
    assert e["gen"] == 0 and e["key"].startswith(f"{0x1018}|g0|3500|"), e
    w.chars[2].hp = 51
    w.player.hp = 790
    sk.tick(t + 0.5, w.snapshot())
    assert len(evs) == 1                                       # 아직 1.5 s 전
    sk.tick(t + 1.6, w.snapshot())
    out = [kw for k, kw in evs if k == "shadow_kick_outcome"]
    assert len(out) == 1 and out[0]["player_hp_delta"] == -3 and out[0]["target_hp_delta"] == -34 and out[0]["key"] == e["key"], out
    # 애니가 바뀌었다 돌아오면 새 시작 → 새 사건
    sk.note_anim(2, -1, t + 2.0)
    sk.note_anim(2, 3500, t + 2.5)
    sk.observe(t + 2.5, 2, 0x1018, 255010, 3500, None, 1.2, 0.0, 90, 106, 0, 790, 51)
    # 세대가 바뀌면 같은 핸들·애니·시작이라도 새 사건
    sk.gen = 1
    sk.observe(t + 2.5, 2, 0x1018, 255010, 3500, None, 1.2, 0.0, 90, 106, 0, 790, 51)
    keys = [kw["key"] for k, kw in evs if k == "shadow_kick"]
    assert len(keys) == 3 and len(set(keys)) == 3 and "|g1|" in keys[2], keys
    print(f"ok  one shadow event per handle+gen+anim+onset (10 ticks → 1), outcome after 1.5 s, new onset/gen → new key")


class DuelMv(FakeMv):
    """duel() 이 부르는 것만 — 모르는 걸 부르면 바로 실패한다."""

    def __init__(self, world, target_ptr):
        super().__init__(world)
        self.kicks, self.lights = [], []
        self.target = target_ptr

    def __getattr__(self, name):
        raise AssertionError(f"duel 이 가짜 Moves 에 없는 '{name}' 을 불렀다")

    def light(self, s, c, n=2, sp_second=None):
        self.lights.append(c.ptr)
        return M.Hit("light", presses=n)

    def heavy(self, s, c):
        return M.Hit("heavy", presses=1)

    def kick_combo(self, s, c, n=2):
        self.kicks.append(c.ptr)
        self.w.chars[c.ptr].hp = 0
        return M.Hit("kick+light", presses=1 + n, dmg=85, dead=True)


def run_duel(foe_obj, ticks=12):
    w = World(player=(0.0, -49.4, 0.0), sp=90)
    w.add(2, 0x1018, 255010, (1.2, -49.4, 0.0), hp=85, max_hp=85, anim=3500)
    mv = DuelMv(w, 2)
    evs, logs = [], []
    old = foes.of
    foes.of = lambda npc: foe_obj
    n = {"k": 0}

    def cancel():
        n["k"] += 1
        return n["k"] > ticks
    try:
        r = D.duel(mv, AXE, 2, None, log=logs.append, cancel=cancel, reflex=None, gen=3,
                   events=lambda k, **kw: evs.append((k, kw)))
    finally:
        foes.of = old
    return r, mv, evs, logs


def test_duel_shadow_never_kicks() -> None:
    r, mv, evs, logs = run_duel(foes.SHIELD)
    assert foes.SHIELD.early_kick == "shadow"
    assert mv.kicks == [], mv.kicks                            # 발차기 안 함
    sk = [kw for k, kw in evs if k == "shadow_kick"]
    assert len(sk) == 1 and sk[0]["gen"] == 3 and sk[0]["anim"] == 3500 and "|g3|3500|" in sk[0]["key"], sk
    assert any(k == "shadow_kick_outcome" for k, _ in evs), evs   # 끝날 때(취소) 남은 결과를 잘린 채 남김
    assert mv.lights, "shadow 뒤엔 예전 가지(휘청 반격)로 흘러가야 한다"
    print(f"ok  duel with SHIELD (shadow): kick_combo never called, 1 shadow event (gen 3), falls through to old branch "
          f"(light ×{len(mv.lights)}), result {r.result}")


def test_duel_act_is_test_only() -> None:
    assert all(getattr(f, "early_kick", "off") != "act" for f in foes.BY_NPC.values()) if hasattr(foes, "BY_NPC") else True
    act = replace(foes.SHIELD, early_kick="act")
    r, mv, evs, logs = run_duel(act)
    assert mv.kicks == [2] and r.result == "killed", (mv.kicks, r.result)
    assert not any(k == "shadow_kick" for k, _ in evs)
    print("ok  'act' (test-only Foe) → kick_combo once → killed; no shipped Foe uses 'act'")


def test_non_shield_no_events() -> None:
    r, mv, evs, logs = run_duel(foes.HOLLOW)
    assert not any(k.startswith("shadow_kick") for k, _ in evs) and mv.kicks == []
    print("ok  non-shield foe → no shadow events, no kick")


if __name__ == "__main__":
    test_candidate_truth_table()
    test_shadow_dedupe_and_outcome()
    test_duel_shadow_never_kicks()
    test_duel_act_is_test_only()
    test_non_shield_no_events()
    print("전부 통과")
