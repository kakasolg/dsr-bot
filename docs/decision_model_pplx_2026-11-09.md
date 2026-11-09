# Decision model from MoKa's instructions — Perplexity answer (2026-11-09)

Asked in the built-in browser (Perplexity, GitHub connector on `kakasolg/dsr-bot`, branch
`claude/dsr-bot-project-review-r3hh9f`). Question: the situation (first-match RULES, combo_table, group_plan,
MoKa ledger of 171 instructions with per-case conditions, MoKa's "bad outcome ≠ wrong instruction", 1v1 hides
mistakes, conflicting instructions, small data) and which current (2025–2026) approaches fit.
Below is a condensed summary of its answer, not a copy. Papers/dates are as Perplexity gave them — not re-read.

## What it read in the repo (checked by [win] against the code, 11-09)
Perplexity read `moka_ledger.py`, `souls/group_plan.py`, and the beginning of `souls/duel.py` (the read was cut off).
Its points about the ledger are correct:
- `ctx()` takes context from earlier log lines; its own docstring says SP and distance can be 1–2 s old.
- `foes` is the planned group size ("전투 계획 N놈"), not the foes threatening at that moment.
- guard counter: "followed" = a light attack was pressed, but each case's ○/× comes from whether it hit. This mixes "did as told" with "how it went".
- low-HP estus counts only lines where an estus decision was logged; low-HP moments without a decision line are missed.
- multi-fight backstab is counted per run, not per fight (the docstring says so).
- damaged-target switch counts switches only; it has no denominator ("kept the target" cases).

Conclusion: the ledger works for accountability. It is not yet clean training data.

## Recommendation (its synthesis, project-specific)
- **Hybrid.** Keep the existing rules, combo table and group plan as *candidate generators*, plus safety filters.
  Choose among the candidates with a small utility/preference model whose weights start from MoKa's judgement.
  Don't start with end-to-end RL or a full behavior-tree rewrite.
- **Store each instruction by its kind.** Keep the quote, and next to it the executable reading with scope and
  proposed exceptions (for MoKa to review). Kinds:
  - temporal contract, e.g. block → instant light;
  - positioning option, e.g. wait on the stairs;
  - default preference, e.g. keep the damaged target;
  - exception, e.g. side attacker first;
  - opportunity-conditioned, e.g. backstab only when given;
  - recovery goal, e.g. HP < 30 % → estus.
- **Keep five quantities apart instead of one success rate per instruction:**
  1. the situation applied;
  2. the bot chose the response;
  3. the input executed;
  4. the outcome;
  5. whether another choice would have been better.

  Use Beta–Binomial only for narrow execution events. Use pooled/regularized models for sparse contexts.
  Keep two separate priors: expert confidence in the tactic, and engineering confidence in the bot's execution.
- **First learned model: preference learning on conflicts.**
  - MoKa judges one decision snapshot on its own, apart from how it turned out:
    - "keep the damaged target / take the side threat / neither";
    - the deciding condition.
  - A small pairwise (Bradley–Terry style) linear ranker is enough.
  - Spend MoKa's time where it teaches the most: cases where instructions disagree, where the new selector disagrees with the old rules, multi-foe exceptions, and cases one condition away from a reviewed one. Add some random cases too.
- **Contextual bandits come later and stay narrow.** The current logs never show the outcome of the choice not taken,
  so off-policy estimates have no support. Log the candidates, the choice, the selection probability and the
  policy version first. A first bounded test could be immediate light vs. short reassess after a verified block.
- **LLM: compiler and challenger first, controller later.**
  - Offline, it turns quotes into conditions, conflict pairs and positive/negative/boundary tests. This fits `tests/expect/duel.jsonl`.
  - As a shadow policy, it picks on frozen snapshots and is scored on agreement with MoKa, latency and invalid picks.
- **Confounders to record before each decision:**
  - foes threatening now;
  - attack phase;
  - other attackers' angle and timing;
  - weapon startup and reach;
  - fresh SP;
  - guard and lock-on state;
  - room;
  - the action in progress;
  - policy and instruction versions.

  Adjust only for variables known before the decision.
- **Order:**
  1. Make one conflict learnable: keep the damaged target vs. the side threat. Add a structured decision event at the choice point. Replace `ok` with separate fields:
     - applicable
     - chosen_as_intended
     - input_emitted
     - execution_confirmed
     - damage_dealt / damage_taken
     - interrupted
     - expert_preference
  2. Collect a few dozen reviewed conflict cases. Compare the current first-match rules, a hand-weighted utility, a ranker and an LLM challenger. Hold out whole fights.
  3. Run in shadow mode, and record later overrides.
  4. Give it control of that one decision class and measure:
     - switches;
     - threat resolution;
     - damage;
     - time to kill the first foe;
     - deaths and stalls;
     - MoKa's rating.

## Sources it named (dates as given)
- BT-ACTION (arXiv Apr 2025 / RO-MAN Aug 2025, code 1Eggbert7/BT_LLM): test-driven LLM → behavior tree from user instructions.
- Code-BT (IJCAI 2025): constrained condition/action APIs, validated generated code.
- "Achieving adaptive tasks from human instructions … LLMs and behavior trees" (ScienceDirect, May 2025).
- Hirota et al., active reward learning from comparative language feedback (online Nov 12 2025, issue Aug 2026).
- Vowpal Wabbit contextual bandits (docs updated Feb 1 2026).
- SIMA 2 (DeepMind, Nov 13 2025; report Dec 4 2025): direction only, not a template for this data size.
- DROC (Stanford-ILIAD, 2023): distill and retrieve language corrections.
- Yell At Your Robot (RSS 2024).

## Status
Research note only. Nothing is built from it. The conflict it names first, "keep the damaged target vs. side attacker
first", is ledger line M1108-10 (not built, waiting for MoKa's call).
