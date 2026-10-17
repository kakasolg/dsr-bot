# Player options vs foe attacks — can the bot choose from state values alone?

2026-10-16 [win] → [cloud]. ROADMAP `player-options`. Builds on `docs/tae-verify.md` (probe 3 · 4) and `docs/duel-sim.md`.

## MoKa 2026-10-16 (quotes)

- "플레이어는 적에 따라, 방패 플레이 않되면, 적 오르쪽으로 돌다 공격, 아니면 반대로 돌다 공격, 구르기 후 공격, 멀리 물러 났다 공격, 보통 이런 선택을 해."
- "사람은 비디오 판독을 하니깐 이게 효율적인데, 봇은 상태값 만으로 해서 가능 한지는 나도 모르겠어."
- 앞선 질문: "더 심화 하면, 어떻게 하면 피격을 덜 당하는지에 대한 데이타도 가지게 될까?" · "적의 행동을 보고 어떤 선택지가 있는지 알 방법이 있을까?"

So the goal is a table per foe — foe animation (× age, × distance) → which of the player's options works — and first an honest answer
to MoKa's doubt: **do state values alone separate the outcomes, or does something only video shows decide them?**

## The five player options

| Option | What decides whether it works | Where the data comes from |
|---|---|---|
| **Shield** (block, then hit back) | the attack's guard-break / stamina damage vs the shield's cut and stability | `combat.json` (GuardBreakPower, StaminaAttackPower) + the bot's shield EquipParamWeapon — files only |
| **Circle right, then attack** | which side the swing sweeps, how far the foe turns to track during the attack | swing side: **not in state values** — measure per anim; tracking: foe heading over time (readable, not recorded yet) |
| **Circle left, then attack** | same, other side | same |
| **Roll, then attack** | player roll i-frames vs the attack's active window; gap after the roll before the next foe attack | player TAE (roll i-frames, not extracted) + foe TAE windows (3000 start runtime-checked) + jump table |
| **Back off far, then attack** | reach, foe chase speed, what the AI picks at that distance (a lunge?) | AI Lua distance bands + measured reach / speed |

The foe reacts to these too: the AI's `Interupt` helpers are reactions to the player — `FindAttack_Step_or_Guard` (player swings →
foe steps or guards), `Damaged_Step`, `MissSwing_Int`, `RebByOpGuard_Step` (`data/gamefiles/ai/`). An option "works" only if the
counter-attack also survives that reaction.

## State values vs video (what the bot has)

| What a human reads off the video | Bot state value | Verdict |
|---|---|---|
| which attack started (wind-up pose) | foe anim ID | bot is **earlier and exact** — the ID changes on the first frame |
| when it will land | anim ID + age + TAE window | bot knows it **as a number**: 3000 lands 0.89–0.92 s after start standing at 0.85 m (probe 3, runtime) |
| distance | distance (cm) | bot exact |
| which way the swing sweeps | **none** | human only — but fixed per anim, so it can be measured once and tabled |
| does the foe track me while swinging | foe heading | readable; not yet recorded in probes |
| walls / drops | NavMesh | roughly (floor checks exist) |
| the same attack again | **anim ID does not change** | **bot blind spot** — probe 2/3 could not tell a second 3000 from the first (1.2 s copies) |
| asleep / unreadable foe | anim −1 | bot blind spot — can't tell why |

Observed follow-ups (probe 3 + 4, one sword hollow, player standing — not a verdict, a starting point for the table):
3000 → 3001 43/44 · 3001 → 3002 36/42 · 3002 → 3003 16 · 3000 13 · 3010 7 · 3003 → 3004 21/26 · 3004 → 3009 10 · 3000 6 · 3010 → 3000 11 · 3003 4.
So dodging 3000 alone is not enough — 3001 follows almost always.

## Step 1 — feasibility pilot (do this before the big table)

Question: with the bot's inputs fixed, do the options give **consistent, different** outcomes against one attack?

- Setup as probe 3 / 4: one isolated sword hollow 254010 (25 m clear of active foes), awake, 3 ms reads, pre-check, `--refill`;
  revive between sets with the **byte quit-out** (`tm.quit_to_title()`, revives killed foes — P-25, re-checked 10-16) instead of resting.
- Scope: foe anim **3000** only. Player options: **circle right**, **circle left**, **roll** — each started at one fixed age τ after
  3000 first appears (e.g. τ = 0.6 s, before the 0.89 s contact), the same pad input every time; 20 repetitions each.
- Record per line, besides probe 3's fields: foe heading, player position / heading / anim (to see the roll and the circle happen),
  the pad input sent and its time.
- Per repetition: hit or not (HP drop inside that 3000), damage, distance and relative angle at contact, did the foe turn (heading change).
- Pass for "state values are enough" (proposed; MoKa may change): each option's hit rate is stable across two halves of its 20, and at
  least one pair of options differs clearly. Fail = the same input gives scattered results → something not in state values matters.
- Out of scope for the pilot: counter-attack success, shield, back-off, other anims, other foes.

### Pilot tool — `options_pilot.py` (2026-10-17 [cloud]; built, fake-game tests only, not run in the game)

- Options in turn, one per 3000: `stand` (control) · `circle_cw` · `circle_ccw` · `roll_cw`. τ = 0.6 s after the 3000's first read
  (first read past it). Circles: stick along the tangent around the foe, re-aimed every read for 1.0 s. Roll: tangent stick + B, stick
  let go after 0.15 s. No lock-on. **cw / ccw = clockwise / counter-clockwise seen from above in world x-z (x right, z up)** — which one
  is "the foe's right" (MoKa's wording) is not assumed: each row's `turn` (player's angle moved around the foe, + = clockwise) shows it.
- Lines (tae_verify `record3`, now also player anim `pa` / heading `ph`, camera `cam`, each foe's `x` `z` heading `h`): every read
  from the 3000's start to 10 reads after; `rep` / `opt`, `pad` (input) / `pad_t`, `pad_stop`, `rep_end`, `home`.
- After each 3000 the player is warped back to the first rep's spot (offline game-memory write) — try 2 of probe 4 drifted ~6 m.
- `check`: probe 3's exclusions (isolation 25 m, start bound, run open, same-ID restart, refill, HP floor) + `no_input`,
  `input_late` (> τ + 0.05 s), `no_stick`, `multi_hit_in_run`. Per rep: hit, damage, hit age, `d_hit`, `angle_hit` (foe front → player,
  assumes the foe's heading has the player's convention), `foe_turn`, `turn`, `roll_seen`.
- Verdict (rule **proposed**, MoKa may change): every option ≥ 16 valid; each option's two halves within 0.3 of each other (else
  **흩어짐**); some pair at Fisher p < 0.01 → **상태값으로 갈림 (이 조건만)**; else 차이 없음. `stand` below 0.8 = setup not like probe 3 (reported).

[win] steps (same spot as probe 3 / 4, hollow awake without hitting it, nothing else within 25 m, 4 m of flat floor around):
1. `python options_pilot.py run 900 --refill 500 793` (~80 reps if the hollow uses 3000 as often as in probe 4; hands off the pad).
   Short first if unsure: `run 120` and look at a few reps (did the circle / roll happen — `pa` 7xx, `turn`).
2. `python options_pilot.py check <file> [more files]` — all output + the records committed. Hand-check a few reps against the lines.
3. Not enough reps → run again and pool the files in one `check`.

**[win] 2026-10-16 setup saved (MoKa: "준비만 하고 세이브 해 놔")** — `savepoint.py restore backup-20261016-234951-options-pilot-ready-A-only`:
standing on the start spot (0.07, −10.02, −58.88), HP 793/793, estus 8, knives 90, last bonfire 1012961. Only hollow A
(254010 at (−15.9, −13.4, −58.7), HP 75, asleep) is alive within 25 m. B, the stair hollow and the crossbowman are dead, and stay dead
through the menu reload (checked). Steps taken: restored the 10-13 save (MoKa) → A was dead there too → byte quit-out revived all →
killed the crossbowman and the stair hollow (each one swing beside it, PlayerNoDead on the whole time, P-87) → B woke and followed →
killed it on the start spot. A has to be woken at run time without hitting it (B-11: whiffs at 3.5 m).
[win] notes on the tool before the run (not fixed):
- A 3000 that starts far away still counts as a rep. Probe 4 try 2's 3000 starts were 0.39–1.21 m, plus 4 of 35 at 1.73–1.75 m. `d_start` is
  in each row, but no rule drops these reps yet.
- Nothing guards against falls (probe 4 has `fell`). Circles and rolls move the player 2–3 m, and the floor ends east between x 4.3 and 5.4 → run with PlayerNoDead on
  (the precheck allows it).
- The home spot is the first rep's spot: fine if the run starts on the start spot (same issue as probe 4 try 2 otherwise).
- 255040–42 on the wall (y +9.5, 20.6 m) were team 6 at one read and team 0 at others — they can break the 25 m isolation.

### Pilot run 1 — 2026-10-17 [win]: **표본 부족**, and the circle reps did not test circling

Records `data/samples/20261017_003758_options(-pre).jsonl` (120 s, 12 reps) + `20261017_004056_options(-pre).jsonl` (900 s, 88 reps); the
first 900 s try `20261017_004023_options-pre.jsonl` stopped at the precheck (HP 1: A kept hitting between runs with PlayerNoDead on).
Setup: save `backup-20261016-234951-options-pilot-ready-A-only`; A woken by whiffs at 3.5 m (3rd swing), PlayerNoDead on, `--refill 500 793`.
Pooled `check` (`data/samples/20261017_options_check_pooled.txt`): 100 reps, valid 51, excluded not_isolated 30 · refill_in_run 10 ·
restart_possible 7 · run_open 2 → verdict 표본 부족 (rule: ≥ 16 valid per option).
stand 7 / 7 hit · circle_cw 13 / 13 · circle_ccw 14 / 14 · roll_cw 0 / 17 (roll anim seen 17 / 17).

[win] 2중 점검 (raw lines):
1. **The 900 s run stood stuck in one place**: its home (= first rep spot) was (8.38, −10.02, −60.53) — A had pushed the player there
   between runs. In the 0.3 s after the input the player moved 0.01 m (circle_cw median) · 0.02 m (circle_ccw) · 0.02 m (roll, though
   roll anims show). The 120 s run (home (2.13, −10.02, −57.34)) moved 0.34 m (circles) and 1.74 m (roll). A stick test on the start spot
   right after: 0.6 s of full stick = 1.72–1.84 m in all four directions → the pad works; the 900 s spot is wedged. No input
   had a hit in the 1 s before it (not hit-stun). → the 900 s circle reps measure "standing", not circling. Its rolls avoided 0 / 17 while
   barely moving — roll i-frames alone, not the displacement.
2. **`turn` was not the player circling**: the short run's ±22° came mostly from A moving (player 0.34 m). Read `turn` with the player's
   own displacement.
3. **Isolation broken by two sleeping 254012** at 22.5–24.7 m (anim −1 throughout, at (5.1, −1.8, −84.1) / (3.5, −1.8, −86.5)) —
   30 of 100 reps excluded for them.
4. In the 120 s run (where moving worked) circles at τ 0.6 still got hit 6 / 6 (3 valid) — 0.34 m in 0.3 s is not enough to leave 3000.

What this says (scope: c2540 3000, τ 0.6 s, start 0.85–2.3 m, one hollow): rolling avoided it every time (17 / 17 stuck + 4 / 4 moving),
standing and walking in a circle never did. Not a verdict under the rule (too few valid, the circle reps mostly invalid).
Before a rerun: home = a fixed tested spot (like probe 4 `--home`), drop the sleeping-foe isolation breaks (or kill the two 254012),
a moved-distance check per rep (e.g. "circle moved < 0.2 m → excluded"), refill so it does not land inside a 3000 (10 lost).

## Step 2 — the table (only if step 1 passes)

foe anim × option × τ (× distance band) → hit rate, damage, counter-attack landed (foe HP), what the foe did next. Then into
`duel_sim.py` (replace its guard / speed / reach guesses) and compare with `souls/duel.py` RULES. Shield column can start from files.

## Known blind spots to work on in parallel

1. **Same-ID restart**: find the animation play-time value in memory (the way rea-trial round 2 named the ChrDbg flags: memory dump +
   REA / Ghidra). With it, a second 3000 is visible and the "age" is the game's own.
2. **Window end / reach**: probe 4 showed AllNoHit uses the hit up (0/12 late releases hit) — the end needs a distance-based method
   (start out of reach, step in late), which is the "back off" option's data anyway.
3. **Swing side**: if the dummy-poly / hitbox path of each attack can be read from the chr files, the left/right columns get a file-based
   prior; until then they are measured.

How to state results (CLAUDE.md): say which foe, which anim, which options, which τ; "state values are enough" only for what the pilot covered.
