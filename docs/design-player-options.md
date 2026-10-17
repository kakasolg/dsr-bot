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
