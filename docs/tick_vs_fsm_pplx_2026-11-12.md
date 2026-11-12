# Tick rules vs state machine for today's failures — Perplexity answer (2026-11-12, MoKa M1111-74)

MoKa: "퍼플렉시티 검색으로 지금 발생 한 문제를 틱 룰과 상태 머신을 비교해서 관련 자료 찾아 보라고 시켜봐". Asked in the
built-in browser (Perplexity, 30 sources, 00:41). The question was generic, with no repo or game name. It described two layers:
fight = ~35 ordered rules checked every ~30 ms, first match runs; route = a fixed step list. It named two failures: P-164 (a
"separate from two foes" sub-action ended with both still adjacent, then 5 s idle and death with full SP and 10 Estus) and
P-162 (fell from the ladder top, later steps assumed the upper floor). Below is a condensed summary, not a copy. Its fixes
are its own engineering proposals, not measured here. Cloud review of the same question: board thread 8ccf86e4.

## Its main point
Keep the tick rules for *choosing*. What's missing are two contracts, and neither comes from swapping the list for an FSM,
behaviour tree or utility AI on its own:
- **P-164 = execution / liveness failure.** An action used up time without reaching its goal, and nothing took control back.
  Fix: an interruptible action executor with start / tick / cancel, a checked success condition, progress and deadline checks,
  and a failure result that changes the next decision.
- **P-162 = plan-validity failure.** The step index says what was *attempted*, not where the character *is*. Fix: check the
  world state before each step (on the upper floor? standing?), invalidate on a fall, and recover from the region the
  character is in.

"Tick-based" and "state machine" are not opposites: an FSM or behaviour tree also runs every tick. The useful split is
choosing an action / keeping its execution state / checking the plan is still valid.

## Architectures vs the two failures (condensed)
| Structure | Stuck sub-action (P-164) | Fall, out of order (P-162) | Limit |
|---|---|---|---|
| Ordered tick rules (now) | fine if each tick returns fast; needs an action lifecycle + watchdog | a high-priority "route assumption broken" rule can stop and recover | timers and flags scatter |
| Flat FSM | good for one motion: start → move → verify → success / fail | FALLING → LANDING → RELOCALIZE states | one global FSM grows many cross transitions |
| Hierarchical FSM | parent handles interrupt / failure for child motions | strong for "pause route, recover, choose where to resume" | organizes recovery, doesn't invent routes |
| Behaviour tree | RUNNING / FAILURE / SUCCESS, timeout and reactive guards | reactive check can halt a running route subtree | a blocking leaf reproduces the same bug |
| Utility AI | picks retreat / guard / heal / attack | ranks recovery options | no completion or cancel protocol |

## P-164: three questions before blaming the rules
1. Did separation actually succeed? A finished movement is not separation; both foes adjacent = failure.
2. Did control come back? The 5 s gap can be: loop not ticking, no rule eligible, action still owning the pad, commands
   overwritten, or the game ignoring input during an animation. Each needs a different fix — log which.
3. Were roll / Estus really allowed then? Log the eligibility checks, anim and pad output before deciding.

Its proposed separation executor: choose escape direction → move → verify separation → success. Failure on no progress,
deadline, no safe direction. Cancel on emergency. Success = a tactical condition (e.g. one foe out of reach, or both no
longer able to pressure), not "moved N seconds". Don't restart it every tick while `rule_separate` still matches. Don't
re-pick the same failed tactic under the same conditions: try another direction or tactic, or escalate.

## P-162: separate kinds of fact
- Persistent: lever pulled.
- History: a ladder climb finished.
- Current: on the upper floor, standing, able to move.

After a fall, keep the persistent facts and drop the current ones. Recovery order: stop upper-floor commands → landing,
threats, heal → find the region by position + height + connectivity → pick a recovery subgoal → resume only steps whose
preconditions now hold. Not the "nearest waypoint", which may be right above on the other floor.

Three levels of route repair:
1. Guarded script (stop when assumptions fail).
2. **Recovery graph** of named regions and authored links (lower floor ↔ ladder base ↔ upper floor). Its recommended start.
3. A full planner (not needed now).

## Real examples it cited
- **Halo 2** (Isla 2005): a hierarchical behaviour DAG whose standard chooser is a prioritized list. Higher-priority
  siblings interrupt on later ticks, close to our fight selector.
- **F.E.A.R.** (Orkin 2006): a planner chooses action sequences. A small FSM (Goto / Animate / UseSmartObject) executes them.
- **Nav2** (robot navigation): local recovery first, escalate to system recovery after repeated failure, replan at its own rate.
- **Game AI Pro** (Dill): utility selectors added inside an existing tree instead of a rewrite.

## Proposed hybrid and migration (its order)
Snapshot → supervisor (death, falling, control validity, route-assumption check) → selector (current fight rules + current
route or recovery goal) → stateful action executor → one owner of the pad output.
1. **Instrument** the two failures without changing behaviour: rule chosen and why others were rejected, active action,
   phase and age, last progress, pad owner and output, route goal and observed region.
2. **Wrap only separation** in the executor; keep its rule and priority.
3. **Guard only the ladder-dependent route steps**: climb-success check, upper-floor precondition, fall invalidation, one
   return-to-ladder recovery.
4. Centralize pad output ownership.
5. Generalize only proven patterns. BT nodes or utility scoring only when a real conflict shows up.

## Testing it proposed
Regression scenes for the exact incidents:
- separation fails → failure is reported and control returns
- no progress → failure in time
- emergency mid-action → clean hand-off
- the same tactic fails again → no restart loop
- ladder-top fall → upper-floor commands are dropped
- lever stays pulled after the fall
- stale telemetry → no advance

Invariants:
- no success without its postcondition
- every running action has a deadline
- one owner per control
- a cancelled action emits nothing
- no upper-floor move while the floor check is false
- no route advance on elapsed time alone

Metrics:
- longest unexplained control gap
- no-progress detection time
- false-success count
- invalid route commands
- recovery success
- eligible-but-unused defence

Replay checks reactions only, not what a different action would have caused. Live runs check consequences. Change one action or
segment at a time against a baseline.

## Where this meets the repo (for MoKa / cloud, not built)
- Fight side: matches the middle option already in `docs/design-clean-motion.md` §32–38 (rules choose, each motion is a small
  state machine). The separation motion is the first candidate (P-164).
- Route side: `andre_route.py` today is a guarded script for one case (ladder 1 redo). Next level = a recovery graph of
  named regions (gate yard, upper floor, lower stairs, ladder base, ladder-1 top, plaza) read from position and height, plus
  event flags for lever and gate (`tm.event_flag`, ids not found yet).
- `blind_report.py` already measures part of "longest unexplained control gap" (status line silent > 2 s).

## Follow-up: is the gate / door open, is the fog wall there (MoKa "게이트 문 열었는지 닫았는지, 안개문 있는지는 어떻게 해야 하는지 이어서 질문 해봐", 00:5x, 30 sources)
Asked as a follow-up in the same thread, again generic. The question listed what the bot can read: position, height and
anim, the foe list, numbered event flags, screenshots / prompt pixels, and a navmesh that doesn't know door state.
It recognised the game on its own and pointed at Soulstruct, EventPocket and DarkShell.

**Main point.** Don't make "lever pulled", "gate open" and "passage crossable" one boolean. Keep three questions apart:
- **What has happened?** e.g. `altar_lever.activated`. Comes from a verified event flag.
- **What is the object doing now?** OPEN / CLOSED / OPENING / CLOSING / UNKNOWN. Comes from object or collision state, or from a
  flag only after script inspection shows the flag really means that.
- **Can the route cross now?** `crossable` TRUE / FALSE / UNKNOWN. Comes from current evidence, fresh.

A foe closing a door again is exactly the case that breaks a single boolean. For fog, also split the facts:
- visible
- interaction offered
- normal walking blocked
- crossing available
- destination

**Channels (its recommended roles):**
| Channel | Best for | Main trap | Role |
|---|---|---|---|
| Event flag | persistent progress ("lever was pulled", "boss dead") | may mean "activated once", not "open now" | primary for logical facts; current state only after script check + test |
| Object / collision state in memory | current pose, collision on/off | wrong instance, stale pointer, unloaded map, mid-animation | primary current-state evidence once the reader is validated |
| Interaction prompt pixels | "an interaction is offered here, now" | position, facing, UI; **absence proves little** | local confirmation, starting the interaction |
| Walk-through probe | "this crossing worked now" | no progress has many causes (foe, angle, anim) | last-mile check, bounded, abort on fight / fall |
| Vision | visible pose, fog | occlusion, light | cross-check, fallback |

**When they disagree:** decide per predicate by authority, freshness and known failure, not by vote. For example:
- lever flag true but collision blocks → keep "lever activated", mark crossing blocked, investigate.
- flag "open" but the object is still moving → transitioning, wait.

Rules:
- **Unknown is not open, and not closed either.** It blocks blind walking but allows looking, interacting or recovering.
- Prompt "not seen" splits into three cases: recognised / visible but none / not observable. Never turn "not observable" into "open".

**Finding which flag belongs to which gate** (its steps):
1. In Soulstruct, find the gate, lever and region entity ids in the map data.
2. Search the map's event script (EMEVD) by **entity id**, not by flag. Include helper events with parameters and the common events.
3. On a copied save, offline, record the flags live while doing: baseline → walk up without touching → pull once → wait until
   the motion ends → let a foe close it, if that happens → reopen → reload.
4. Weed out flags that only correlate. Does it stay set after the foe closes the door? Does it change when the motion ends?
   Does reload rebuild it? Does the script read it to set the door?
5. Write each mapping down: name, map and entity, flag id and polarity, script references, reset behaviour, test cases.

Don't find flags by toggling them on the normal save.

**Named facts for the route:** keep a small fact service between memory readers and the route.
- Raw observations are separate from derived facts. Each fact has a source, a time and the load it came from.
- Lifetimes:
  - persistent progress follows the save rules
  - reversible door state must be fresh
  - object reads expire on map reload
  - prompt reads are short-lived and tied to the pose
  - a successful crossing is history, not proof
- Overlay named passage edges on the static navmesh, e.g. `gate_yard ↔ inside: requires gate.crossable`.
- "Openable" is separate from "open": a closed lever gate should give a plan to interact, not "unreachable". Fog is its own
  crossing action.
- Before each step, and during steps whose assumptions can change, check that the needed facts are known, fresh and true,
  and that no reload happened. After pulling a lever, wait for the passage postcondition. Sending A is not "open".

**Verifying the detector itself:**
- Test every transition: closed, opening, open, closed by a foe, reload open / closed, map unloaded → unknown, prompt hidden
  or wrong facing, foe standing in an open doorway, fog event, stale read.
- Label tests with independent evidence (video, script trace, collision field, a safe real crossing), **not the same flag**.
- Measure false-open (the worst one, same failure as the ladder fall), false-closed, unknown coverage, transition latency,
  and stale state after reload.
- Run in **shadow mode** first: log the facts beside today's route decisions and review every disagreement before the facts
  get route authority.
- Start small: one reversible door, one lever gate, one event fog wall.

**Where this meets the repo (not built):**
- `tm.event_flag(id)` exists in `dsr_telemetry.py`. Soulstruct is installed in `.venv` with vanilla event scripts
  (`soulstruct/darksouls1ptde/events/vanilla/`); m10_01 is the map for altar → Andre.
- `screen_prompt.prompt_px()` is today's prompt channel. `andre_route.lever()`'s "walk inside the gate" is a walk-through probe.
- `field.FOG_WALLS` is a static list: it knows where fogs are, not whether they're up now.
- The altar lever / gate pair fits as the first case: lever already in `missions.SPOTS["altar-lever"]`; save backup 181431 =
  not pulled. MoKa M1111-15 also says a hollow closes a door on the way to the parish, which would be the reversible-door case.

## Follow-up 2: repo-aware (Perplexity reads kakasolg/dsr-bot at df3184b; 01:0x, MoKa M1111-76/77)
Perplexity has the repo connected (MoKa 11-12). It asked about the actual code: P-164 in `souls/duel.py` / `souls/field.py` /
`andre_route.py`, and the gate flags in the vanilla m10_01 script. It said its file reads were cut short: it did not see the
full `RULES`, `rule_separate` or `Field.fight` bodies, nor the gate events. It said what it could not confirm.

**P-164: its candidates, in the order it would check them:**
1. **The whole lethal stretch was inside `_separate()` → `Moves.walk_path()`** (its strongest candidate). `_separate` walks
   synchronously with only `cancel()` as the stop and `timeout_per=2.5` per point, not a total deadline. No other rule can
   run until it returns. The "떼어놓기 … escape_arrived" line, the 14.1 s status and `me_dead` share one timestamp (158.2),
   so the "5 s idle after separation" was probably still the separation walk. *Checked here against the track:* from
   152.7 to 157 s the player stood at (0.7, 38.5) with two foes at 0.8–1.3 m, HP 429 → 0. That is consistent with walking
   blocked inside the escape, not proven.
   Fix: a total deadline plus an emergency abort (HP drop, close pressure, death) checked inside the walk.
2. **The fight came from clear()'s return walk.** The tag "따라온 놈 back" = `walk_to(center)` met a follower and started
   its own fight. clear()'s low-HP logic can't run until that nested walk/fight returns.
   Fix: one absolute deadline passed down to nested walks and fights, or the return walk hands control back on contact.
3. `limit=6.0` is checked between actions, not pre-emptive. A long walk or a nested fight can run past it. (That patch was
   made after P-164 and is not game-checked.)
4. **`_separate()` reports movement success, not separation success.** No check after the walk that the two foes are apart.
   Fix: add `separation_result` from the after-snapshot and don't repeat the same escape in the same situation.
   `_pair_close()` can't be the success check as is (it returns empty when a foe is attacking).
5. The entry check (no foe in an attack anim) isn't repeated during the walk. 3500–3599 = stagger, not attack.
6. Estus can be refused legally next to two foes (`OPEN_R` 3.0, `SAFE_R` 6.0, `LAST_SIP_R` 3.5). 10 unused Estus is
   not proof of a bug. The new roll × 2 + heal can still be refused. Log the refusal reason and don't log "마심" until
   the count drops.
7. Rule starvation (`rule_hit_first`, `rule_stagger_punish`, `rule_attack` conditions) only matters once the trace shows
   ticks actually ran in that stretch.

It proposed narrow regression tests:
- separation walk overruns while HP drops → control returns in time
- arrival with both foes adjacent → not "separated"
- stagger turns into an attack mid-walk → re-check
- clear()'s return walk meets a foe → same deadline
- roll + heal gets no opening → no false "drank"

It noted `Moves._span` / ctlspan records already bracket blocking moves.

**Gates: it did not confirm any id (cut-off reads). Checked here instead** (`.venv` soulstruct
`darksouls1ptde/events/vanilla/m10_01_00_00.evs.py` + `data/gamefiles/m10_01_00_00.json` + live flag reads):
- **Sunlight Altar gate:**
  - Lever 1011120 (o1200_1001, obj_act 11010620) and gate 1011121 (o1201_1001, (19.0, 9.4, −21.9)).
  - Event 11010621: when its flag is on, the gate is set to its open end anim 4 and the lever is disabled. So it is open for
    good, as MoKa said.
  - **Flag 11010621:** False in backup 181431 (lever not pulled), True after try 4 pulled it. Checked by script + two save
    states. Not checked against the screen.
- **Second gate:**
  - Gate 1011101 (o1201_1000, (7.9, 19.8, 40.4)) and lever 1011100 ((2.9, 19.8, 42.3)), above the lower stairs.
  - State flag **61010610**: on → closed anim 2 and navmesh face 1013100 disabled (Constructor and Event 11010600).
  - Event 11015116: player in region 1012200, gate open, 11010607 off → 11015115 on → Event 11010609 activates lever 1011100.
    Soldier 6010 (c2550, starts (4.7, 17.8, 24.9)) is tied to the lever by 11010607.
  - Live: False in backup 181431, True after try 4 (which died at the lower stairs).
  - Whether this is the gate MoKa meant ("closes even when invisible, reopens after clearing from Andre's bonfire") is a
    hypothesis: position fits, reopening condition not traced.
- **Fog walls:**
  - `Event_11010090` slots: slot 0 obj 1011700 → flag 11010090 (already `field.FOG_FLAGS`); slot 1 obj 1011702 → its
    slot flag (likely 11010091, not checked).
  - `andre_route` appends the parish fog (0.7, 27.6, 37.1) to `FOG_WALLS` without a `FOG_FLAGS` entry. Missing mapping.
- **Existing door flags:** `field.DOOR_FLAGS` already maps 4 Burg doors to (record flag, state flag), e.g. 1011310 →
  (11010140, 61010510). Lever gates are not in it yet.
