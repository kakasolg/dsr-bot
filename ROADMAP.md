# ROADMAP — what is open now

Only open work, **one checked line per item**; everything else lives in `docs/roadmap/` (Korean, verbatim, nothing deleted).
`python roadmap.py check` (also `tests/roadmap_test.py`) · `tidy` (moves finished things out) · `queue win|cloud|MoKa` · `show <id>`.

```
- [~] some-id | cloud | doing | what is true now and what comes next | docs/x.md · plan:some-id
  mark  id    who     stage   now / next (≤ 150 chars)                             where the details are
```
mark `[ ]` `[~]` `[!]` blocked, `[x]` done / `[-]` dropped (→ `tidy`) · who = whose move it is now (`cloud` `win` `MoKa`, `+`)
· stage `todo` `doing` `verify` (built, waits for a game check) `decide` (MoKa) `blocked` `parked` · `plan:<id>` = history in
plan.md "Open-item details". On a change: rewrite the line (now / next only); results, numbers and quotes go to the details.

| File | Holds |
|---|---|
| `docs/roadmap/plan.md` | sections 0 … 7, every done item, "Open-item details" (per id), "Done items" (from `tidy`) |
| `docs/roadmap/problems.md` | problem log P-1 … (**new problems appended here**) + "Closed problem index" (fixed / won't fix) |
| `docs/roadmap/relay.md` · `changelog.md` | handled relay entries · old change log |
| `docs/analysis-2026-10-09.md` | problem analysis, public cases, proposals |
| `docs/design-*.md` | multi-foe-spot · walk-follow · floor-check · scene-expectations · run-settings designs |
| `docs/review-v2-2026-10-11.md` | v1.0 → v2.0 review: structure problems, 2.0 features and order |
| `docs/research-control-priority-2026-10-11.md` · `guide-control-priority.md` | consistency research (MoKa 10-11) · rules for fixes |
| `docs/code-read-fall-death-2026-10-11.md` · `analysis-death-2026-10-12.md` | fall / death code reading · 38-death analysis |
| `docs/boss-taurus.md` · `shop-undead-merchant.md` | Taurus Demon guide · merchant menus + shop routine |

---

## v1.0 / v2.0 (MoKa 2026-10-11: keep them apart)

- **v1.0** = today's structure (`souls/field.py`'s own loops, zones in `souls/missions.py`, module constants). Sections 1–2:
  game checks of what is built, MoKa decisions, small fixes. No structure work here.
- **v2.0** = section 3, the structure from `docs/review-v2-2026-10-11.md`. Starts after the `v1.0` tag (which commit: MoKa).
- A new item goes to v2.0 when it needs the tick loop, route data, the settings object or WorldState; otherwise v1.0.

## 1. Now (v1.0) — Undead Burg bonfire → Taurus Demon (1-m, MoKa 2026-10-06)

`run.py burg-upper` = MoKa's safe-spot zones 1–8 (`data/burg-upper-map.json`); test save `backup-20261006-155749-…-before-taurus`.

- [~] alignment | win | verify | target–body–camera record in (10-12); runs → end line `정렬 (…)`, then decide what to fix (MoKa: high priority) | plan:alignment
- [~] taurus | win | doing | `run.py taurus` plunge loop; bonfire → Taurus killed 2× (005650, 025057) | docs/boss-taurus.md · plan:taurus
- [~] fall-death-policy | win | verify | no fall quit-out + after-death pickup: (1)(2) seen in 3 runs; (3) death record, (4) alignment next runs | P-71 · P-72 · plan:fall-death-policy
- [ ] boss-two-hand-dodge | cloud+win | todo | boss default = two-handed + dodging (9-30); Taurus first, general boss module is v2.0 | plan:boss-two-hand-dodge
- [~] stage-analysis | MoKa | decide | burg-upper zones 1–8 analysed (auto + hand draft); MoKa: fix intent / response, zone 4 safe spot 0.5 m from a drop | docs/stages/burg-upper.md · plan:stage-analysis
- [ ] firebomb-hollow-close-in | cloud | todo | firebomb hollow: close in fast unless the way is a fall-risk zone (ledge 254012 ignored); golden | plan:firebomb-hollow-close-in
- [~] zone-runs | win | doing | zone-by-zone runs; after each the three reports + `sample.py` (CLAUDE.md) | plan:zone-runs
- [~] route-recordings | MoKa | doing | route recordings (3 done, Taurus killed in the 3rd) — more only if a zone needs it | plan:route-recordings

**Firebombs · bow from the Undead Merchant (MoKa 10-12: "난이도가 급격히 줄어"); the bot must buy them itself. In order:**
- [~] shop | win | verify | merchant save: 3/3 bought after [win] fixes (live refs, OK by comparison, LEAVE_S 9 s); next: one run from Firelink with --buy | docs/shop-undead-merchant.md · plan:shop
- [ ] firebomb-measure | win | todo | locked-on firebomb at 254010 from 5 · 8 · 12 · 15 m: hit, damage, others woken (67 held) | plan:firebomb-measure
- [ ] firebomb-candidate | cloud | todo | firebomb as a candidate next to knife / melee (lure opener · 2+ foes · ledge); no limit, none = as now | plan:firebomb-candidate
- [ ] bow | cloud+win | todo | bow: buy, switch shield ↔ bow, locked-on shot, measure — after the firebomb | plan:bow
- [ ] npc-module | cloud | todo | NPC interaction as one module (talk / shop / quests); the merchant is the first case | souls/shop.py · plan:npc-module

## 2. v1.0 — open by area

**Fight rules / reflexes (1-j: "basic reflexes done right", MoKa 10-02)**
- [~] scene-expectations | cloud | doing | steps 1–3 done offline (54 scenes, scene_replay 687/687) | docs/design-scene-expectations.md · plan:scene-expectations
- [ ] label-review | MoKa | decide | skim duel.jsonl label lines (10 min) + the 4 `review` scenes | tests/expect/duel.jsonl · plan:label-review
- [~] floor-check | cloud | doing | floor map + `--ground` (walks) + `rule_footing` (`--footing`) done offline | docs/design-floor-check.md · P-49 · plan:floor-check
- [ ] ground-default | MoKa | decide | `--ground` (walks only) on by default, or more runs that reach the passage? | relay.md 10-11 · plan:ground-default
- [!] ground-ab-2 | win | blocked | A/B `--ground` round 2: 6 runs done (report in relay.md); waits for ground-default | P-56 · plan:ground-ab-2
- [~] no-spot-split | win | verify | `no_spot` → first ≤ 7 m of escape.pick's path; game so far 4× escape_arrived | plan:no-spot-split
- [~] rule-shot | win | verify | hit by a thrower → 'shot' → leave_fire beyond 11 m; game: `사선 밖으로` 4× → arrived 4/4 | P-61 · plan:rule-shot
- [!] axe-guard | win | blocked | P-32 axe hollow guard — game check on the ramp, needs MoKa's go | P-32 · plan:axe-guard
- [ ] p31-finish-reach | MoKa | decide | P-31: `rule_finish` only within reach + 0.3 (re-record golden) | P-31
- [ ] p33-stagger-after-block | MoKa | decide | P-33: no `stagger_punish` right after a block; [win] checks stagger anims in old logs first | P-33
- [ ] pad-stuck-read | win | todo | read-only: `control.Pad` stuck-input detection; reflex order inside a walk tick | plan:pad-stuck-read
- [ ] multi-foe-retreat-read | win | todo | read-only: retreat / Estus decisions when ≥ 2 foes were close, old runs | plan:multi-foe-retreat-read
- [ ] ranged-class-fix | win | todo | #4 `ranged` (thrower) classification fix — changes lure / wait, compare in its own runs | P-59 · plan:ranged-class-fix
- [~] axe-wall-heavy | win | doing | battle-axe vertical heavy against walls (two-handed only; shield soldiers heavy → light) — game checks | plan:axe-wall-heavy

**Walking / navigation (1-f)**
- [ ] almost-arrived | win | todo | "almost arrived" rule check in game (`거의 도착 … 다음 점으로`, asylum 1 m-short spots) — urgent since 09-30 | plan:almost-arrived
- [~] corner-early-turn | win | doing | 1-f A: early turn / rubbing at corners reduced? (`hotspots.py`) | plan:corner-early-turn

**Instrumentation / run records**
- [ ] p1e-tests | win | todo | P1-E ordering · queue overflow · write failure · on/off-equal tests (1-l) | plan:p1e-tests
- [~] run-settings | cloud | doing | steps 1–2 done offline (`runinfo.py`, `sample.py`, `ab.py`, report headers) | docs/design-run-settings.md · plan:run-settings
- [ ] laya | MoKa | decide | Laya: keep off / freeze; move the label tool's `why_not` out of `laya_shadow.py`? | plan:laya
- [ ] ramp-labels | MoKa | todo | ramp 24-scene labels (review mode) → `label_pilot.py report --set ramp`; then size of the eval set | plan:ramp-labels

**Game files · radar · overlay (2, 4, 5)**
- [~] msb-treasures | win | doing | re-run `msb_extract.py m10_02_00_00 m10_01_00_00` for `treasures` | plan:msb-treasures
- [~] overlay-borderless | win | doing | borderless overlay + bot: overlay visible, clicks pass through, bot keeps going | plan:overlay-borderless
- [~] radar-upgrade | win | doing | radar upgrade check (navmesh drawn, pad slots, recording, `--replay`) | plan:radar-upgrade
- [ ] radar-ai-ranges | win | todo | radar AI ranges (sight cone, hearing circle, leash) match the game | plan:radar-ai-ranges

## 3. v2.0 — after the `v1.0` tag (`docs/review-v2-2026-10-11.md`; go, done bar N/10 and order: MoKa)

**Structure (review §2; proposed order §4: settings → WorldState → tick loop → route data → spots → batch runner → boss)**
- [ ] settings-object | cloud | todo | one settings object instead of ~228 module constants `run.py` overwrites; `runinfo` saves it | docs/review-v2-2026-10-11.md
- [ ] worldstate | cloud | todo | WorldState: who is alive / where after a rest, quit-out or warp, in one place (P-18 · P-25 · P-44 · P-55) | docs/review-v2-2026-10-11.md
- [ ] tick-loop | cloud | todo | one tick loop (read → state → one action → input) instead of field.py's loops; walking first | docs/review-v2-2026-10-11.md · plan:tick-loop
- [ ] route-data | cloud | todo | route data (walk / safe spot / pull / fight / ladder / fog wall …) + one runner; `burg-upper` first | docs/review-v2-2026-10-11.md · plan:route-data
- [ ] batch-ab | cloud+win | todo | batch A/B runner: save restore · warp · N runs · `ab.py` → pass rate n/10 per segment | docs/review-v2-2026-10-11.md

**Features (review §3)**
- [~] multi-foe-spot | MoKa | decide | multi-foe = spot choice: design drafted; step 1 (measure only) waits for MoKa's answers (§8) | docs/design-multi-foe-spot.md
- [ ] floor-check-everywhere | cloud | todo | `rule_footing` onto the tick loop for walks / recover too, with collision-mesh edges | plan:floor-check-everywhere
- [ ] collision-mesh | cloud | todo | read `map/*.hkxbhd` (soulstruct-havok); NavMesh edges wall / cliff → `EDGE_PENALTY` | plan:collision-mesh
- [~] walk-follow | MoKa | decide | target walk rules inside `_follow` on layer 2, then [win] A/B — waits for MoKa (§7) | docs/design-walk-follow.md
- [~] harness-trust | cloud | doing | harness layer-2 trust check: passage-entrance point 70 before / after (direction yes, size exaggerated) | plan:harness-trust
- [ ] corner-1m | cloud | todo | 1-f C: at a stuck corner go 1 m further along the incoming direction before turning | plan:corner-1m
- [ ] boss-module | cloud | todo | boss fight module (its own loop; Taurus first) | docs/boss-taurus.md
- [ ] restart-segment | cloud | todo | after a death: save mission progress, restart from the broken segment (pickup is in v1.0, P-72) | plan:restart-segment
- [ ] recording-feedback | cloud | todo | feed a recording into the decision code ("what would the bot have done") | plan:recording-feedback
- [ ] town-entry | MoKa | decide | town entry: zone-boundary F9 walk plan · B-hit design (not approved) — as route data | plan:town-entry

**Later / parked (not in 2.0)**
- 1-g learning (MoKa 09-28/09-30): step 1 motion model = 6-a layer 2 (done); step 2 imitation policy after layer-2 trust check — needs the batch runner first
- [ ] sim-2d | cloud | parked | 2D simulator: sense / chase / leash from NavMesh + ThinkParam, plug `souls/field.py` in | plan:sim-2d
- [ ] explore-mode | cloud | parked | explore mode (offline), Lua decompile, TAE timing → attack prediction; foe reaction table | plan:explore-mode

## 4. Problem index

Open rows only (fixed / won't fix → problems.md "Closed problem index" by `tidy`). Status: open · parked · decide (MoKa) · verify.

| P | Problem | Status |
|---|---|---|
| 6 | Burg: stuck behind a ledge foe; path through crates | verify |
| 7 | Two shield soldiers: no separation spot (`no_spot`), late reaction to the side foe | open → same family as P-29 |
| 8 | Died to two shield soldiers (light attacks into raised shields) | open → P-29 family |
| 10 | Late on a shield soldier's advancing first attack (3009) | open, low priority |
| 11 | Real controller ignored after bot runs / save swaps (ViGEm) | workaround: reboot |
| 12 | Same stalls every run (`#3 이동` (−52.2,−22.8,−26.9), crates `o1150_01`, `o1132_06`, `o1321_0021`) | open |
| 14 | Fell off the ramp edge right after a backstab | verify |
| 16 | Fell through a gap while circling for a backstab | verify |
| 17 | Secret-passage exit: stuck / fell | parked → 1-g |
| 18 | Ramp `left #N?` after a quit-out ended the mission | verify (`pass_ramp`) |
| 19 | `experiments/reach.py direct` walked off a railing | open, low priority |
| 21 | steam.exe outside connection right after restart (CDN) | decide (a/b/c) |
| 25 | Killed foes come back after a quit-out — cause: the byte quit-out (game test) | verify — `shake` now uses the menu, only falls use byte (+ revive_risk) |
| 26 | Crowd retreat broke every 1–2 s, 16 times, 0 attacks | open (`CROWD_FALL_BACK` off, capped) |
| 28 | Asylum: same 3 stall spots (self-recovered) | open |
| 29 | Burg `#4 이동`: three 254010 at once, 0 attacks, died (twice) | open — top cause of deaths |
| 30 | Ignored foe hit for 10 s, then fell 5 m through a gap; lock-on blocked by line of sight | partly fixed |
| 31 | `rule_finish` swings from 2.2–4.0 m | decide |
| 32 | Dropped guard too early vs axe hollow 254001 | verify |
| 33 | `stagger_punish` right after a block (should keep blocking) | decide |
| 38 | Mover didn't re-press guard/sprint after a neutral | verify (P0-D) |
| 44 | Restoring a save does not restore the radar warp list | decide |
| 47 | "HP low" 0 s fight loops; zone 8 death; 'cleared' with survivors | verify — zone 8: two rolls off the ladder-top ledge, fight from the landing |
| 48 | 6-a "48 % of sharp corners cut inside" is a 2 Hz sampling artifact (10 Hz: 20 %, two places) | open (measure fix) |
| 49 | Ramp ledge (−22,−40,13): knocked off 3× fighting the axe hollow, standing off-mesh; `rule_edge` only raised the shield | verify — `--footing` A/B (P-58) |
| 51 | `burg-upper` zone 3 (5,−92): hit twice while backing off the edge after backstabs, −181 | open |
| 53 | `burg-upper` zone 1 (−1.9,−14,−70): fell 4 m right after a hit, quit-out recovered | verify — sprint overshot a corner over a drop; now jogs into such corners (`nav.brake_points`) |
| 55 | `passage-drill`: the bonfire warp revives the ramp foes → died on the way to the top | open (A/B moved to seg 1-2) |
| 56 | Ramp ledge (−20,−39,14), `--ground` on: 254002 + axe 254001 swinging together, died (no fall) | verify — + 'ranged first' no longer turns to the axe hollow / away from a foe < 2 m |
| 57 | Passage start (−20,−39.3,14.4): 1.5 s stall + turn-around retry, in 2 `--ground`-off runs (0 in the 2 on runs that got there); AGAIN 10-11, 4/15 runs | verify — cause: walked straight at A0 3.3 m up from 4 m; now path-finds first |
| 58 | Ramp ledge (−22,−44,15) in a fight: fell 4.4 m, quit-out, walk-back timed out, died (`--ground` round 2 on #3) | verify — `rule_footing` (`--footing`, off by default), A/B |
| 59 | `rule_shot` may read a 254010 lunge landing from > 4 m as a throw (4 track cases) → ends the fight, backs off | verify — thrower = `Foe.thrower` only, axe hollow not one, melee 6 m + duel-start window |
| 63 | `ground_ahead` / `footing` / `safe_back` take a floor far above (a roof) as floor | partly — strict only for sprint braking; rest → v2.0 floor check |
| 64 | Passage exit (−26,−33.7,8.5): walk stalls 2–3× (4.5 s, passage 33 s) — 2/27 runs; same spot as P-63's missing-floor NavMesh | open → [cloud] |
| 65 | Camera not steered outside fights (leave_fire / escape.pick back-off / body pull); `LOOK_SIGN` learned backwards from one pulse once | verify — one look order in `CamFollow`; stick sign from a ± pair |
| 66 | Shield soldier's late 3004: `rule_after_swing` (6th) called it ended at 1.6 s and kicked before `rule_late_windup_block` (9th) — hit −228; `rule_shot` read that hit as a thrower's | verify — `duel.swing_over` (windup ends when it lands) + `Moves.swung` from every snapshot |
| 67 | Zone 1 lure: B re-pressed at every sprint point → jump off ledge into 3× 254010; `_sprint` had no hit exit → dead | verify — game 10-11: zones 1–4 cleared, `threat` stop 6×, no jump; 3 short B holds left |
| 68 | Zone 5: heavy into 255000's shield 0 dmg → low_hp, Estus refused 3×, 255001 joins → dead; bot kept acting after death (TypeError) | death part: fixed — game 10-11 zone 8 death ended the zone at once, no error; shield part open |
| 69 | Zone 1: the foe fell off the ledge mid-fight, the bot walked after it and fell (fall quit-out, recovered) | open → [cloud] |
| 70 | Zone 1 stairs: 0.1 s sprint B between braked points = roll off the stairs; 3 runs dead | verify — `Pad.sprint` holds B ≥ 0.45 s; 10-12 3 full runs: zone 1 cleared 3/3, no roll |
| 71 | Fall deaths: a second fall right after a fall quit-out, `Escape` blind, pad frozen; black box blames the foe | verify — MoKa 10-12: no quit-out on falls (`fall_seen`) |
| 72 | Deaths never fetched their bloodstain (38 deaths, 0 pickup trips) | verify — `souls/afterdeath.py`: worth it → back from zone 1, pick only with no foe within 15 m; small / same zone → end |
| 73 | Ramp #5: low_hp gap roll slid off the ledge → 22.4 m fall (no-quit policy) | open → [cloud] |

## 5. Relay — [cloud] ↔ board

[cloud] can't reach the board: `- date [cloud→board] …` / `- date [board→cloud] …`. Whoever handles an entry starts it with
`→ done` / `→ moved` right after the tag; `tidy` then moves it to `docs/roadmap/relay.md`.

- 2026-10-12 [board→cloud] **[win] changed `souls/shop.py` (MoKa OK)**: live refs `<k>_live.npy` next to the record refs (record ones read the live menu at 0.36); `ok_selected` = left > right (OK's bar is 0.007 live, `> 0.005` missed → 2nd RIGHT back to CANCEL); `LEAVE_S` 9 s (farewell 6.1 s). Merchant save 3/3 ok. Details: end of `docs/shop-undead-merchant.md`.

- 2026-10-12 [cloud→board] → done 10-12 [win] **shop fixed (`git pull`)**: steps wait on the screen (menu / list / qty), greeting lines → A until the menu, OK checked before A. Game check 2 = end of `docs/shop-undead-merchant.md`.

- 2026-10-12 [cloud→board] **Stage analysis (MoKa 10-12)**: `python stage_report.py` → `data/stages/burg-upper.json` + auto block of `docs/stages/burg-upper.md` (terrain · foes · our runs per zone; hand-written intent / response above it). [win]: rerun it after `sample.py` of a burg-upper run.

- 2026-10-12 [cloud→board] **ROADMAP format changed (MoKa 10-12)** — one checked line per item `- [m] id | who | stage | now / next | where`, `python roadmap.py check / tidy / queue win / show <id>`; closed problem rows → problems.md, item histories → plan.md "Open-item details" (nothing lost). Rules: CLAUDE.md "Keeping ROADMAP.md current". Your list: `python roadmap.py queue win`.

- 2026-10-12 [cloud→board] **`git pull` — fall / death policy changed (MoKa 10-12)**: (1) no quit-out on a fall (`--fall-quit` = old); (2) `burg-upper` after a death: worth it → back from zone 1 and pick up with no foe within 15 m, else end (`--no-recover` = old); (3) black box splits fall from hits, one `death` event (`✝ 사망 원인: …`); (4) end line `정렬 (…)`; (5) P-66: a windup isn't 'ended' before it lands — shield soldier 3004 blocked to 2.3 s, then counter. (6) **shop routine ready**: `run.py merchant-buy --buy 290:30,292:20 --shop-shots` from the merchant save, test plan at the end of `docs/shop-undead-merchant.md`. Why: `docs/analysis-death-2026-10-12.md`. → (1) · (2) checked 10-12 [win] with `6341df3` (entry below); (3) · (4) · (5) next runs
