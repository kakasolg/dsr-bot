# Clean motion — what MoKa means by it, what exists, what is open

Status: **notes only** (2026-10-28). Nothing here is built for this goal yet, and nothing is decided. Order and go: MoKa.

## MoKa 2026-10-28 (quotes)

- "적을 공격 할때 앞에서 공격 하는 게 아니라 옆으로 돌면서 때려야 나는 않 맞고, 상대는 공격 데미지가 더 들어가는데, 지금은 문제가 않되는데,
  나중으로 갈수록 그게 중요 해 질거야."
- "그래서 뒤잡도 중요한데, 아직은 모션이 불안정해서 뒤잡이 이상하게 되고 있어."
- "그리고 방패로 패링도 가능해 저야 하는데, 이게 모션이 깔끔하다고 하는 정의야."
- "그래서 상태 머신 같은게 필요한 가 그런 생각을 하는 데, 한번에 고려 할게 너무 많아서 사실상 힘드네."

Why now is fine but later is not: today the Claymore+5 one-shots most foes (P-89 parked for that reason), so trading hits from the
front costs little. Later areas (stronger foes, bosses, Blighttown / Sen's Fortress — `docs/stages/later-barriers.md`) punish it.

## The definition — three motions

| # | Motion | Goal | What exists today | Known problems |
|---|---|---|---|---|
| 1 | **Circle, then hit** (side attack) | I am not in the swing's path; my hit lands | Circling exists only as the backstab approach (`duel.py` `BACKSTAB_R` 0.9 m, `CIRCLE_MAX_SWEEPS`). Options pilot measured circling vs one attack | Pilot run 2 (`docs/design-player-options.md`): circle cw/ccw **hit 18/18 · 21/21** — c2540 hollow, anim 3000, start ~0.9 m, τ 0.6 s only. Earlier / farther circling not measured. Swing side not in state values |
| 2 | **Backstab** | Riposte from behind (big damage, foe locked in the animation) | `duel.py` backstab rules: lock-on kept while circling, `BACKSTAB_DEG` 140°, `BACKSTAB_MAX_R` 1.3 m, from 3 human demos (2026-09-28) | MoKa: motion unstable, backstabs come out wrong. Logged: P-78 (`not_behind` between two foes → death), P-83 (`no_lock` twice → death). Off with 2+ on us (`NO_BACKSTAB_N`) |
| 3 | **Shield parry** | Parry the swing → riposte | **Nothing** in the bot code (searched 2026-10-28) | Needs the parry window per foe attack (TAE timing — `docs/tae-verify.md` has some windup data) and the parry input / result anims |

What the three share: each is a **short sequence with timing** (move → wait for a moment → press), not a one-tick decision. That is the
part today's per-tick RULES do badly: the in-between state lives in `Fight` fields and time windows, and an earlier rule can take a tick
in the middle of the sequence.

## The state-machine question (open)

MoKa's worry is right: doing all three at once means one machine with many states and many foe cases. A smaller split that fits what
the code already does (proposal, not decided):

- **Decision stays a rule list** (`duel.RULES`, first match wins): *which* motion to start, from the situation.
- **Each motion becomes its own small state machine** that runs to its end or aborts on a few listed conditions (hit, foe changes anim,
  floor edge, second foe in reach). `moves.kick_combo` is already this shape (kick → light, no decision loop in between).
- One motion at a time, each with its own offline test (scene + fake game) and its own game measurement before the next one starts.
- Suggested order (MoKa decides): 2 backstab first (exists, known failures, clear success signal — the riposte anim) → 1 circle-hit
  (needs the "when to start circling" measurement) → 3 parry (new; needs timing data first).

## How to judge "clean" (proposal)

Per motion, from run logs: tries, success (backstab / parry anim seen, or my hit landed), hits taken during the motion, aborted and why.
`blind_report.py` and `hotspots.py` already give the damage-taken side; a per-motion count is new.
