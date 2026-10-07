"""Layer 3 data — how to fight each enemy type. npc number (NpcParamId) → what it is and how to fight it.
Sources: game Lua AI (`script\\<map>.luabnd.dcx` → `<npc>_battle.lua`, extracted with boss/luadump.py·luatab.py), measurements, user tips.
Lua is **only a data source** — extract once, write it here, never read at runtime.
When meeting a new enemy, add one line here. The combat loop (duel.py) changes behavior based only on these values.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Foe:
    name: str
    kind: str                       # hollow | shield | skeleton | boss | other
    kick_when_idle: bool = False    # raises shield when standing still (anim -1) → break it with a kick, then hit
    circle_behind: bool = False     # shield only blocks a frontal cone — if idle, circle behind and light attack (most effective, user 2026-09-25)
    ranged: bool = False            # throws from afar (firebomb) — won't come if we wait, keeps throwing → run in and close
    avoid: bool = False             # don't fight at current level (route around)
    singles: tuple = ()             # single-hit attack anims — safe to counter right after blocking
    combos: tuple = ()              # start anims of chained attacks — block to the end, then counter
    unblockable: tuple = ()         # attacks that must not be blocked (guard break etc.) — reflex evades instead of shielding
    punish_hits: int | None = None  # light attacks in a stagger (bounced off guard) counter — None = per weapon. 1 for foes with short stagger
    windup: tuple = ()              # attacks that land long after starting — within windup_act_s, kick first to interrupt; beyond it, block
    windup_act_s: float = 1.2
    kick_on_stagger: bool = False   # kick immediately on post-attack stagger (3500) — it soon backs out of reach
    # How to do the early kick under the windup·kick_on_stagger conditions above (Patch D, 2026-09-26):
    #   "off"    — do nothing
    #   "shadow" — no kick, only log candidate events (duel.ShadowKick). Default, since the meaning of raw anims 3004·3500 is unverified
    #   "act"    — actually kick. No Foe data uses this value — enabling it needs a separately approved experiment-only change
    early_kick: str = "off"
    note: str = ""


# Hollow c2540 (Lua 2026-09-24): when close, half are single 3008, the rest 2–3 hit combos (3003→3004→3009, 3005~3007)
# 2026-09-25 measured (254001): blocked 3009 for several seconds, stamina fell to 6 and died (reflex×29 in a row, 0 dealt, 376 taken) —
# not just SHIELD, the hollow combo's 3009 must not be blocked either (same anim number, same danger). Added to unblockable.
_HOLLOW = dict(kind="hollow", circle_behind=True, singles=(3008,), combos=(3003, 3005), unblockable=(3009,))
HOLLOW = Foe("망자(칼)", **_HOLLOW)
FIREBOMB_HOLLOW = Foe("망자(화염병)", ranged=True, **_HOLLOW,
                      note="위 턱에서 안 내려오고 화염병만 — 방패로 받아도 56~224. 경사로에선 #5(254002)가 던진다 — 시범 140708: 스폰 자리에서 3.5 s 마다 3008, 나이프 두 번(75→31→0)으로 죽음")
# 2026-09-26 observation recordings (observe 090241·091308·092141), ramp #2 255010, user: "the kick has to come in one beat earlier":
#  · 3004 lands 2.0–2.1 s after start regardless of approach speed (0.1–1.3 m/s) (4 times). Two hits after 1.6 s took −220·−323,
#    two at 0.4–0.7 s interrupted the attack for 0 → windup=(3004,), kick within 1.2 s, block beyond
#  · 3005 lunge (from 4 m at 3–4.5 m/s, lands at +1.0 s) costs 1–2 when blocked — keep blocking
#  · 3500 lasts 0.8–1.3 s, during which it backs off at 1.5–1.9 m/s (1 m → 3–4.7 m) — kick immediately (previously 'lure' ran off to the flat ground)
# Ramp #4 (254001): [MoKa] 2026-10-01 "다른 망자는 방패와 칼, #4만 방패 없이 도끼를 양손으로 잡고 공격" · "가드를 너무 일찍 내렸음".
#  Blackbox r1·r4: after blocking 3003 the follow-up 3004 lands 1.69–1.70 s after it starts; prep_linger (SWING_S 1.6) called it idle,
#  hit_first swung and took −118 both times. windup=(3004,), windup_act_s=1.0 → rule_late_windup_block keeps the shield up until it lands.
#  ranged stays True for now: the lure/waiting the ramp runs do with it is what MoKa approved — the 'thrower' label is wrong
#  (LAYA.md 13), fixing it changes those decisions and needs its own runs.
AXE_HOLLOW = Foe("망자(도끼 양손)", ranged=True, windup=(3004,), windup_act_s=1.0, **_HOLLOW,
                 note="경사로 #4. 방패 없이 도끼를 양손으로 — 3003 뒤 3004가 1.7 s에 떨어짐, 1.0 s부터 그때까지 막기 유지 (MoKa 2026-10-01)")
SHIELD = Foe("방패 병사", kind="shield", kick_when_idle=True, circle_behind=False, unblockable=(3009,), punish_hits=1,
             windup=(3004,), windup_act_s=1.2, kick_on_stagger=True, early_kick="shadow",
             note="가만히 서면 방패를 들어 약공이 12 씩만 (6번 쳐도 못 잡음). 가드 올린 채면 발차기로 휘청 (위키). "
                  "내가 가드만 하면 가드 브레이크 3009 로 깨러 온다 (Lua IsTargetGuard) — 2026-09-24 실측: 3009 를 막다 가드가 깨져"
                  "(내 애니 160) 스태미나 42→14, 밀려나 경사로에서 낙사. 3009 는 막지 말고 피한다. "
                  "휘청이 짧다 — 휘청 반격 2연타의 두 번째 사이에 100~115 를 되받아쳤다 (세 번 중 두 번) → 한 대만. "
                  "circle_behind 는 꺼둠(2026-09-25, 사용자: '도는게 너무 느려, 발차기 약공이 더 좋아 보여') — 아래 참고")
SKELETON = Foe("묘지 해골", kind="skeleton", avoid=True, singles=(3003, 3004, 3005), combos=(3000,),
               note="스텝인(700)으로 한 번에 붙고 구르기로 피한다. 한 대 111~167 — 기사 레벨로는 못 이김 (사용자 2026-09-24)")
ASYLUM_DEMON = Foe("수용소 데몬", kind="boss", note="boss/README.md — 필드 규칙과 섞지 않는다")

BY_NPC: dict[int, Foe] = {
    254000: HOLLOW, 254010: HOLLOW, 254011: HOLLOW,
    # 254002: previously treated as a sword hollow, but in demo 140708 the firebomb thrower was #5 (254002). 254001 (#4) has a record of throwing in 134451, so both are ranged
    254001: AXE_HOLLOW, 254002: FIREBOMB_HOLLOW, 254012: FIREBOMB_HOLLOW,
    250000: Foe("망자(성벽 마을)", kind="hollow", combos=(3000, 3004), unblockable=(3009,)),
    255000: SHIELD, 255010: SHIELD,
    # 255001: [MoKa] 2026-10-06 "255000은 방패, 롱소드 망자이고, 255001은 방패, 창 망자" — 성벽 마을 위쪽(구역 2·5). 등록 전엔 기본값이라
    # 3004(창 찌르기) 중 '먼저 치기' 두 번에 −232씩, 친 건 방패에 0 (P-46, 10-06h)
    255001: SHIELD,
    # 255002 is a crossbowman, not a shield soldier — 3000/3001 are firing motions, not a guard stance. Anim struct +0xA0 turns 1 and
    # 0.3–0.7 s later an impact hits my shield (my anim 140, SP −7) every 2.7 s (2026-09-25 measured, user "I'm getting hit by arrows, it's right in front").
    # As SHIELD, wait_far said "not approaching" and just blocked for 8 minutes. The fire motion number doesn't change, so anim changes don't reveal it.
    255002: Foe("석궁 병사", kind="shield", ranged=True, kick_when_idle=True, unblockable=(3009,), punish_hits=1,
                note="3000/3001 = 석궁 발사 (방패 들고 쏜다). 기다리지 말고 붙어 발차기 → 약공. 뒤잡기 안 됨 — 벽에 붙어 서 있음 (사용자 2026-09-28)"),
    # 254013·254014 (next to the Undead Burg bonfire, HP150): not shield soldiers but bodiless phantoms — user "there's nothing there, why is it swinging"
    # (2026-09-25). 254013 is filtered at layer 0 by its inactive flag, 254014 by body overlap (dsr_telemetry.PHANTOM_R). The entries below are kept.
    254013: SHIELD, 254014: SHIELD,
    290000: SKELETON, 290002: SKELETON, 290003: SKELETON, 290004: SKELETON, 291000: SKELETON,
    223200: ASYLUM_DEMON,
}

UNKNOWN = Foe("모르는 적", kind="other")


def of(npc: int | None) -> Foe:
    return BY_NPC.get(npc, UNKNOWN) if npc is not None else UNKNOWN
