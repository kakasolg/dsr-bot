# Duel simulator — first vertical slice (c2540 sword hollow)

MoKa 2026-10-16: TAE 검증이 통과하면 c2540 하나로 AI Lua와 연결해 작은 전투 시뮬레이터의 첫 수직 슬라이스. [win] 10-16: type 1(근접)만으로 재개.
Code: `duel_sim.py` (offline, the bot does not import it) · test: `tests/duel_sim_test.py`.

## What the slice connects (end to end)

| Piece | From | Verified how far |
|---|---|---|
| Which act at which distance, with what odds | `data/gamefiles/ai/HusiFight_Sword254000Battle.lua` (`Activate` bands), `common_battle_func` (`Common_Battle_Activate` weighted pick) | file only (decompiled draft; read by hand into Python tables) |
| What each act does: approach to X m, then which animation(s), combo odds | same lua: `defAct01` (3010), `HumanCommon_Approach_and_ComboAtk` (3000→3001→3002), `Act03` (3003→3004→3009), `Act07` (3005 / 3006 / 3007 lunges) | file only |
| After-attack spacing (leave, sideways, step, nothing) | `GetWellSpace_Act_IncludeSidestep` with the goal's odds {100, 75, 9, 8, 0, 4, 4} | file only |
| When each attack is live | `tae.json` type 1 **active windows** | level 1 + level 2 (DSAnimStudio, c2540 3000 / 3003 / 3010) — not runtime |
| How much each hit does | `combat.json` judge → AtkParam `PhysicalAttackPower` (raw, before player defense) | level 1; records: 3000 110 → lost 118–120 (n=2), 3003 140 → 91–127 (n=4) |

Left out: type 2 bullets, type 5 common behaviors (steps as movement only), the `Interupt` reactions, player attacks, stamina, poise.

## Assumptions (ASSUME in `duel_sim.SOURCES`) — and how much each one decides

| Assumption | Value | Effect in the slice | Replace with |
|---|---|---|---|
| Guard blocks all physical damage | 100 % | `guard_on_swing` takes **0** — the result is the assumption | shield cut %, guard stamina, guard break (player param + runtime) |
| Walk speed (foe = player) | 1.5 m/s | `back_off` takes ~0 — the foe can never catch up | foe walk / dash speed from tracks or the probe |
| Dash speed | 3.5 m/s | approach time from far | same |
| Hit rule | once per window / once per AttackIndex | 3010: 6 hits (588) / 3 hits (294); records: one 3010 = 192 (~2) | probe 3 (still target, reference only): 6 · 6 · 5 hits, one per window → `window` rule; 45 per hit, not 98 (damage not checked) |
| Reach = the AI's attack distance | 1.6–2.2 m, lunges 2.0 m | whether a window connects | runtime hit vs distance (probe has distance) |
| Animation length / combo link | last window + 0.5 s / + 0.25 s | tempo of combos and how often the AI re-picks | runtime anim durations (probe) |
| Lunge speed | 3.5 m/s | 3005–3007 reach | duel.py note (3–4.5 m/s); probe |

## First results (200 episodes × 30 s, start 6 m, HP 742, `python duel_sim.py`)

| Player policy | Mean damage taken | Deaths | Note |
|---|---|---|---|
| stand | 796 (index rule 793) | 200 / 200 | most hits 3010 (window rule) or 3000 (index rule) |
| guard_on_swing (0.2 s reaction) | 0 | 0 | = the guard assumption, says nothing yet |
| back_off (walk away under 3 m) | 0.8 | 0 | = the equal-speed assumption, says nothing yet |

`python duel_sim.py --compare` (weak check): share of hits by animation, sim `stand` vs recorded hits where 254010 was the only foe blamed
(18 rows): recorded 3003 0.50 · 3000 0.22 · 3005 0.11 · 3006 0.11 · 3010 0.06, combo follow-ups 3001 / 3002 / 3004 **0**;
sim 3010 0.32 · 3000 0.19 · 3001 0.16 · 3002 0.12 · 3003 0.10. Not the same — but the recorded hits come from bot fights (the bot
blocks, rolls and hits back, so follow-ups rarely land), and 18 rows is little. It does not test the lua tables; the probe does.

## What the slice says to do next

1. **Runtime probe** (`python tae_verify.py probe`, docs/tae-verify.md B) — one recording answers four assumptions at once: foe speeds,
   animation lengths, reach (distance at each hit), the 3010 hit rule. And it is level 3b for the TAE windows.
2. Player side: shield physical cut and stability (EquipParamWeapon of the bot's shield 1462000) instead of "guard blocks all".
3. Then the Interupt reactions (the foe steps / guards when the player swings) — needed before the sim can judge attack timing.
