"""Layer 2 — how to use each weapon. Every weapon has different motions (user: "each weapon has its own motion traits").
This layer holds only numbers and choices: reach, how many chained hits, whether to use heavy attacks. Buttons are layer 1 (moves); whom to hit is layer 3 and up.

Weapon ID is at PlayerGameData+0x328 (tm.right_weapon()). The upgrade level is the last two digits (Broadsword+5 = 202005) → round down to the hundred.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Weapon:
    name: str
    base_id: int
    reach: float            # horizontal distance (m) to the enemy's center that a light attack reaches. Only press within this
    combo: int              # number of chained light attacks (moves.light n)
    use_heavy: bool         # use heavy attacks (release stick then R2 — forward+R2 is a jump attack)
    two_hand: bool          # two-hand it (Y)
    str_req: int            # one-hand strength requirement. Two-handing counts 1.5x → str_req / 1.5 or more is enough
    sp_min: int = 40        # below this stamina, don't attack — guard
    # the three phases of one light attack (seconds; user 2026-09-25: "when it gets longer, some of startup, attack and recovery get longer.
    # the battle axe is a weapon with extremely little delay — its weakness is that you have to fight up close").
    # startup: press until the blade connects (getting hit here interrupts) · active: hitbox is live · recovery: withdrawing (can't raise shield)
    # how to measure: R1 into the air — my anim struct +0xA0 reads 5/257 during the active window; stamina drops at active start (OFFLINE_TOOLS.md).
    # None = weapon not yet measured — use the old fixed values (tuned for Broadsword/Battle Axe).
    startup: float | None = None
    active: float | None = None
    recovery: float | None = None
    heavy_punish: bool = False   # heavy attack in a shield soldier's stagger window (when at or above duel.HEAVY_SP)
    max_dur: int | None = None   # max durability — below this ratio use repair powder (moves.repair). None = not checked
    note: str = ""

    @property
    def swing(self) -> float | None:
        return None if self.startup is None else self.startup + self.active + self.recovery

    # the times below are used by moves.light (relative to the first R1). Derived from the three phases — formula checked against Claymore measurements:
    # second R1 just before the active window ends (pressed at 0.45 s it's ignored, at 0.8 s it chains); the chained second swing starts at active end +0.2 s.
    @property
    def chain_at(self) -> float:
        return 0.45 if self.startup is None else self.startup + self.active - 0.04

    @property
    def second_start(self) -> float:
        return self.startup + self.active + 0.2

    @property
    def guard1(self) -> float:
        return 0.35 if self.startup is None else self.swing - 0.1

    @property
    def guard2(self) -> float:
        return 1.05 if self.startup is None else self.second_start + self.swing - 0.1

    @property
    def watch1(self) -> float:
        return 0.9 if self.startup is None else self.swing + 0.1

    @property
    def watch2(self) -> float:
        return 1.5 if self.startup is None else self.second_start + self.swing + 0.1


# Wiki (Fextralife): small model and short range, but the highest attack among straight swords. Light and heavy chain easily.
# user (2026-09-24): "plain light attacks are good. But 2 light hits", "broadsword is short but good for chaining", jump-attack motion is bad.
# measured: all kills within 1.2 m; beyond 1.6 m, 5/5 whiffed. 2026-09-24 terrace: all 8 light attacks swung at 1.3~1.6 m whiffed → 1.2 m.
# a hollow (HP 75) takes two 2-hit light combos (41+34)
# one-handed + left-hand shield (2026-09-24 status: arm_style one-hand). Reflex/guard assume a shield — two-handing drops it and weapon guard is weak (user)
BROADSWORD = Weapon("브로드소드", 202000, reach=1.2, combo=2, use_heavy=False, two_hand=False, str_req=10,
                    note="강공(스틱 놓고 R2)은 가로 베기 — 약공과 섞는 건 아직 안 시험함")

# Wiki: STR 24 / DEX 10 required (STR 16 two-handed). Heavy is a knockdown overhead slam, light is a wide swing.
# measured (2026-09-23): heavy costs 120 stamina, hits reliably only within 2.3 m (beyond that 4/14)
ZWEIHANDER = Weapon("츠바이헨더", 350000, reach=2.3, combo=1, use_heavy=True, two_hand=True, str_req=24, sp_min=60,
                    note="강공 내려찍기로 경직·넘어뜨림")

# Battle Axe 701000 (Bandit starting weapon). user (2026-09-24): "the axe performs better than the broadsword — similar motion but more effective".
# Wiki: STR 14 / DEX 8 required; light is a vertical chop (big stagger on humanoids), chains. Old notes (playbook-notes, reach.py): reach 1.8 m, Undead Asylum hollows in 2~3 hits.
# reach set longer than the measured Broadsword (1.2), but the old 1.8 is optimistic — start at 1.5 and re-measure with reach.py on whiffs.
BATTLE_AXE = Weapon("배틀 액스", 701000, reach=1.5, combo=2, use_heavy=False, two_hand=False, str_req=14, sp_min=55,
                    note="약공 세로 찍기 2연타. 강공(R2 큰 내려찍기)은 아직 안 시험함 — 넘어뜨리면 방패병에 쓸 후보")

# Claymore 301000 (greatsword). user (2026-09-25): obtained in Undead Parish, "it's a better weapon than the battle axe, so use this from now on".
# Wiki: STR 16 / DEX 10 required — STR is 16 now so it's one-handed (left-hand shield kept). One-handed light is a wide horizontal slash, so
# it also hits enemies alongside, and as a greatsword it outreaches the axe (1.5 m). Heavy is a thrust. Costs more stamina than the axe.
# **not yet measured** — reach 1.8, combo 2, sp_min 60 are first values from the wiki. Re-measure with reach.py on whiffs.
# air-swing measurement (2026-09-25, anim 253000→253001): blade connects (stamina −30) at 0.68 s, one swing ends at 1.46 s. Second R1 pressed at 0.45 s
# was **ignored, only one swing** (user: "guard and attack timing are off"); at 0.8 s it chains, second connects 1.65 s, ends 2.40 s.
CLAYMORE = Weapon("클레이모어", 301000, reach=1.8, combo=2, use_heavy=False, two_hand=False, str_req=16, sp_min=60,
                  startup=0.68, active=0.16, recovery=0.62, max_dur=200, heavy_punish=False,
                  # heavy_punish off (2026-09-25): 2 thrusts in a shield soldier's stagger window = 0 dmg (took 87) and 36 — kick + light in the same window 79~85.
                  # the stagger seems to wear off during the 0.76 s startup
                  note="한손 약공 가로 베기 2연타(옆 적도 맞는다 — 사용자). 강공(찌르기)은 아직 안 씀. reach 는 실측 전")

# Bandit's Knife 103000 (dagger). user (2026-09-28): switched to it for backstabs/ripostes (big critical damage).
# Wiki: STR 6 / DEX 12 required, light is a quick short slash, cheap on stamina, critical 110 (highest among daggers besides Priscilla's).
# user (2026-09-28): "think of it as almost parry/backstab only" — light attacks are the fallback, not the plan.
# air-swing measurement (2026-09-28, +3, experiments/swing_probe.py, 6/6 alike, anim 203000): stamina −14 at 0.34 s,
# +0xA0 0x100 bit (261→257) 0.34~0.46 s, back to idle 1.36 s. Holding LB: same startup, back to idle at 0.76 s (LB cancels recovery).
# Second R1 at 0.25 s is ignored; 0.35~0.95 s always chains (second stamina drop at 0.84 s, or press +0.24 s when later).
# reach (2026-09-28): experiments/reach.py direct walked straight off the Burg bonfire ledge (no NavMesh) — no usable swings.
# Instead: black-box frames of 13 knife runs (data/runs 20260927_191346~213020 *.hits.jsonl, experiments/knife_hits.py),
# foe distance at blade-out → HP drop within 0.25 s:
# 0.8 m 28/41 · 1.0 m 19/22 · 1.2 m 0/2 · 1.4 m 3/3 · 1.6 m 12/19 · 1.8 m 1/6 · 2.0 m 2/8 · ≥2.2 m 0/16 (HP drops seen up to 1.4~1.7 m).
# Edge ≈ 1.6 m → reach 1.3 (edge − 0.3, reach.py guidance). Misses at 0.85 m are mostly a side foe, not the one swung at.
BANDITS_KNIFE = Weapon("밴딧 나이프", 103000, reach=1.3, combo=2, use_heavy=False, two_hand=False, str_req=6, sp_min=30,
                       startup=0.34, active=0.12, recovery=0.90,
                       note="단검 — 거의 뒤잡기·패링 전용 (사용자). 약공은 보조. 스태미나 14/회")

KNOWN = {w.base_id: w for w in (BROADSWORD, ZWEIHANDER, BATTLE_AXE, CLAYMORE, BANDITS_KNIFE)}


def of(weapon_id: int | None) -> Weapon:
    """Right-hand weapon ID → usage. Unknown weapons use Broadsword values (short, light-attack focused = most conservative), with a warning."""
    if weapon_id is not None and weapon_id - weapon_id % 100 in KNOWN:
        return KNOWN[weapon_id - weapon_id % 100]
    print(f"   ⚠ 모르는 무기 {weapon_id} — 브로드소드 사용법으로 (souls/weapons.py 에 추가할 것)", flush=True)
    return BROADSWORD


def can_two_hand(w: Weapon, strength: int | None) -> bool | None:
    return None if strength is None else strength * 1.5 >= w.str_req
