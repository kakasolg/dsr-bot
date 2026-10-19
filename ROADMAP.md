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
| `docs/design-*.md` · `review-v2-2026-10-11.md` | designs · v2.0 review (structure problems, features, order) |
| `docs/analysis-*.md` · `research-` / `guide-control-priority*` · `code-read-fall-death-*` | analyses (10-09, 38 deaths) · consistency rules · fall code |
| `docs/boss-taurus.md` · `shop-undead-merchant.md` · `stages/` | Taurus · merchant · per-stage notes |

---

## v1.0 / v2.0 (MoKa 10-11: kept apart)

Tag `v1.0` = `b234344` (MoKa 10-12). v1.0 structure (field.py loops, zones in code): sections 1–2. v2.0 (section 3) = items
needing the tick loop, route data, settings object or WorldState.

## 1. Now (v1.0) — Undead Burg bonfire → Taurus Demon (1-m, MoKa 2026-10-06)

`run.py burg-upper` = MoKa's safe-spot zones 1–8 (`data/burg-upper-map.json`); test save `backup-20261006-155749-…-before-taurus`.

- [~] taurus | win | doing | `run.py taurus` plunge loop; bonfire → Taurus killed 2× (005650, 025057) | docs/boss-taurus.md · plan:taurus
- [~] fall-death-policy | win | verify | no fall quit-out + after-death pickup: (1)(2) seen in 3 runs; (3) death record, (4) alignment next runs | P-71 · P-72 · plan:fall-death-policy
- [ ] boss-two-hand-dodge | cloud+win | todo | boss default = two-handed + dodging (9-30); Taurus first, general boss module is v2.0 | plan:boss-two-hand-dodge
- [~] stage-analysis | MoKa | decide | burg-upper zones 1–8 analysed (auto + hand draft); MoKa: fix intent / response, zone 4 safe spot 0.5 m from a drop | docs/stages/burg-upper.md · plan:stage-analysis
- [ ] firebomb-hollow-close-in | cloud | todo | firebomb hollow: close in fast unless the way is a fall-risk zone (ledge 254012 ignored); golden | plan:firebomb-hollow-close-in
- [~] zone-runs | win | doing | zone-by-zone runs; after each the three reports + `sample.py` (CLAUDE.md) | plan:zone-runs
- [~] route-recordings | MoKa | doing | route recordings (3 done, Taurus killed in the 3rd) — more only if a zone needs it | plan:route-recordings

**Firebombs · bow from the Undead Merchant (MoKa 10-12: "난이도가 급격히 줄어"); the bot must buy them itself. In order:**
- [~] shop | win | verify | merchant save 3/3 bought; from Firelink 0/2 (ramp deaths) | docs/shop-undead-merchant.md · plan:shop
- [~] lock-sight | win | verify | lure spot prefers a clear line (`clear_sight`: 30/31 locked, 5/6 failed); none → lock-on decides as before; next: `--throw` lock rate 2–10 m | docs/throwables.md · plan:lock-sight
- [~] heavy-lock | win | verify | `duel._keep_lock` + heavies only locked; zones 1–2: locks in 1:1, lets go for a 2nd foe; watch more runs | docs/throwables.md
- [~] firebomb-measure | win | verify | hollow ~5 m: 75 one-shot 2/2 · 7 m: 18 · ≥ 9 m: no lock. crossbow 5 m: died (P-83) | plan:firebomb-measure
- [ ] firebomb-candidate | cloud | todo | firebomb as a candidate next to knife / melee (lure opener · 2+ foes · ledge); no limit, none = as now | plan:firebomb-candidate
- [ ] bow | cloud+win | todo | bow: buy, switch shield ↔ bow, locked-on shot, measure — after the firebomb | plan:bow
- [ ] npc-module | cloud | todo | NPC interaction as one module (talk / shop / quests); the merchant is the first case | souls/shop.py · plan:npc-module

## 1-b. Taurus → Sunlight Altar, Claymore as main (MoKa 10-12)

- [~] altar-route-rec | MoKa | doing | demo 1 read (§2-b); next: what calls the landing? | stages/burg-to-altar.md
- [ ] claymore-grip | MoKa | decide | STR 16 = one-hand OK (154037); two-hand? default? | stages/burg-to-altar.md
- [~] altar-mission | win | verify | full chain today 3/5 arrived (incl. a real no-landing → shortcut → arrived); P-86 altar-burg left low HP | stages/burg-to-altar.md
- [ ] keyboard-menus | win | todo | menus by keyboard scancodes (MoKa 10-13: more exact than the pad) — quitout / savepoint / shop | docs/keyboard-menus.md

## 2. v1.0 — open by area

**Fight rules / reflexes (1-j: "basic reflexes done right", MoKa 10-02)**
- [~] scene-expectations | MoKa | decide | steps 1–3 done offline (54 scenes, replay 687/687); step 4: label 30–50 scenes from `--ctl-scenes` runs | docs/design-scene-expectations.md · plan:scene-expectations
- [ ] label-review | MoKa | decide | skim duel.jsonl label lines (10 min) + the 4 `review` scenes | tests/expect/duel.jsonl · plan:label-review
- [~] floor-check | win | verify | backstep / reflex / combos / rolls → `nav.can_move` (10-13); [win]: `뒤에 바닥 없음` count + falls in runs; walks wait for ground-default | docs/design-floor-check.md · P-49 · P-73 · plan:floor-check
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
- [~] corner-early-turn | win | doing | 1-f A: early turn / rubbing at corners reduced? (`hotspots.py`) | plan:corner-early-turn

**Instrumentation / run records**
- [ ] p1e-tests | win | todo | P1-E ordering · queue overflow · write failure · on/off-equal tests (1-l) | plan:p1e-tests
- [ ] laya | MoKa | decide | Laya: keep off / freeze; move the label tool's `why_not` out of `laya_shadow.py`? | plan:laya
- [ ] ramp-labels | MoKa | todo | ramp 24-scene labels (review mode) → `label_pilot.py report --set ramp`; then size of the eval set | plan:ramp-labels

**Game files · radar · overlay (2, 4, 5)**
- [~] msb-treasures | win | doing | re-run `msb_extract.py m10_02_00_00 m10_01_00_00` for `treasures` | plan:msb-treasures
- [~] overlay-borderless | win | doing | borderless overlay + bot: overlay visible, clicks pass through, bot keeps going | plan:overlay-borderless
- [~] radar-upgrade | win | doing | radar upgrade check (navmesh drawn, pad slots, recording, `--replay`) | plan:radar-upgrade
- [ ] radar-ai-ranges | win | todo | radar AI ranges (sight cone, hearing circle, leash) match the game | plan:radar-ai-ranges
- [ ] combat-table | MoKa | parked | 3000 start ok, end not | docs/tae-verify.md
- [~] player-options | cloud | doing | run 1: too few, stuck | docs/design-player-options.md
- [~] rea-anim-time | cloud | decide | ctrl +0x10 = anim time; A's 7 attacks 83/83 hits in TAE windows; 3000 restart 0/25; next: use it for restart_possible? | docs/rea.md

## 3. v2.0 (`docs/review-v2-2026-10-11.md`; go, done bar N/10 and order: MoKa)

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
- [ ] harness-trust | cloud | parked | layer-2 trust check: passage-entrance point 70 (direction yes, size exaggerated) — after the batch runner | plan:harness-trust
- [ ] corner-1m | cloud | todo | 1-f C: at a stuck corner go 1 m further along the incoming direction before turning | plan:corner-1m
- [ ] boss-module | cloud | todo | boss fight module (its own loop; Taurus first) | docs/boss-taurus.md
- [ ] restart-segment | cloud | todo | after a death: save mission progress, restart from the broken segment (pickup is in v1.0, P-72) | plan:restart-segment
- [ ] recording-feedback | cloud | todo | feed a recording into the decision code ("what would the bot have done") | plan:recording-feedback
- [ ] town-entry | MoKa | decide | town entry: zone-boundary F9 walk plan · B-hit design (not approved) — as route data | plan:town-entry

**Later / parked (not in 2.0)**
- 1-g learning: after the batch runner (plan.md `1-g`)
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
| 87 | probe prep: fell, died | open |
| 56 | Ramp ledge (−20,−39,14), `--ground` on: 254002 + axe 254001 swinging together, died (no fall) | verify — + 'ranged first' no longer turns to the axe hollow / away from a foe < 2 m |
| 57 | Passage start (−20,−39.3,14.4): 1.5 s stall + retry, AGAIN 10-11 4/15 runs | verify — path-finds first |
| 58 | Ramp ledge (−22,−44,15) in a fight: fell 4.4 m, quit-out, walk-back timed out, died (`--ground` round 2 on #3) | verify — `rule_footing` (`--footing`, off by default), A/B |
| 59 | `rule_shot` may read a 254010 lunge landing from > 4 m as a throw (4 track cases) → ends the fight, backs off | verify — thrower = `Foe.thrower` only, axe hollow not one, melee 6 m + duel-start window |
| 63 | `ground_ahead` / `footing` / `safe_back` take a floor far above (a roof) as floor | partly — strict only for sprint braking; rest → v2.0 floor check |
| 64 | Passage exit (−26,−33.7,8.5): walk stalls 2–3× (4.5 s, passage 33 s) — 2/27 runs; same spot as P-63's missing-floor NavMesh | open → [cloud] |
| 65 | Camera not steered outside fights (leave_fire / escape.pick back-off / body pull); `LOOK_SIGN` learned backwards from one pulse once | verify — one look order in `CamFollow`; stick sign from a ± pair |
| 66 | Shield soldier's late 3004 called over at 1.6 s → kicked into it (−228); read as a thrower's hit | verify — `swing_over` (windup lands) + `Moves.swung` |
| 67 | Zone 1 lure: B re-pressed at every sprint point → jump off ledge into 3× 254010; `_sprint` had no hit exit → dead | verify — game 10-11: zones 1–4 cleared, `threat` stop 6×, no jump; 3 short B holds left |
| 68 | Zone 5: heavy into 255000's shield 0 dmg → low_hp, Estus refused 3×, 255001 joins → dead; bot kept acting after death (TypeError) | death part: fixed — game 10-11 zone 8 death ended the zone at once, no error; shield part open |
| 69 | Zone 1: the foe fell off the ledge mid-fight, the bot walked after it and fell | verify — falling / > 2.5 m below target ends the duel 'lost' before face() walks |
| 70 | Zone 1 stairs: fall off the stair side on the sprint back to the safe spot | verify — 10-13 death was the stick left pushed while `lock_target` turned the camera (not the sprint); `b29d59a` centers it |
| 71 | Fall deaths: a second fall right after a fall quit-out, `Escape` blind, pad frozen; black box blames the foe | verify — MoKa 10-12: no quit-out on falls (`fall_seen`) |
| 72 | Deaths never fetched their bloodstain (38 deaths, 0 pickup trips) | verify — `souls/afterdeath.py`: worth it → back from zone 1, pick only with no foe within 15 m; small / same zone → end |
| 73 | Ramp #5: low_hp break-out roll went −126° instead of −30° (camera turned during the roll) → 22.4 m fall | verify — camera held during rolls, fresh stick, `nav.can_move` |
| 74 | Zone 2-1: two foes on us 13 m out; tether cut at tick 0 three times, guard walk back timed out → 37 s, −1565 | verify — no cut with a foe < 2.5 m; failed way back ends it; back-offs within 8 m |
| 75 | Zone 2-2: run-in read a target 30.5 m out as 'met' (30 m snapshot) → walk-out / tether loop 3×, 35 s | verify — missing target checked wide |
| 77 | Walk stalls with the body not moving (~160 s, ~110 s); almost-arrived skips can't help | open |
| 78 | Zone 4-1: backstab try between 254010 + 254011 → not_behind, 6 s, −452, then no retreat spot → died | open |
| 79 | Death on the walk to the bonfire (`화톳불로`): no stain decision, walks back into the same foes | open |
| 80 | Stagger counter pressed 0.9 s into a shield soldier's stagger (waited for SP) → hit first, died | verify — `Foe.stagger_s`; 10-13 same scene → shield, then killed it, 0 taken |
| 81 | Zone 5: foes standing 3 m below read as 'fell' (P-69) → never pulled, both came in zone 6, died; ledge nudge 23× mid-fight | verify (fall = own drop; nudge stops after 2 in place) |
| 82 | Shop walk: merchant's body read as a prop block → swung at the crate beside him → he turned hostile, bot killed the Undead Merchant | verify — no prop swing within 3 m of a known NPC; restore = MoKa |
| 83 | Firebomb probe in the crossbow's line: throw cut, then no-lock backstabs ×2 with the foe behind → died; bloodstain not where `Blood` recorded it | open |
| 84 | Altar bonfire approach sticks 1.9 m short of (27.4, 9.7, −25.4) every run, 4–5 s, recovers | open |
| 85 | `burg-altar` dies at ③: bridge hollows follow (lunges, 2 at once), and a stain pickup walked into the breath line | open — 2/5 arrived; fight + recover at ③, pickup removed |
| 86 | `altar-burg` left the altar at HP 41 % (no rest) → perched Hellkite + bridge soldier → died | open — Estus before leaving; rest at the altar = MoKa |

## 5. Relay — [cloud] ↔ board

[cloud] can't reach the board: `- date [cloud→board] …` / `- date [board→cloud] …`. Whoever handles an entry starts it with
`→ done` / `→ moved` right after the tag; `tidy` then moves it to `docs/roadmap/relay.md`.

- 2026-10-12 [cloud→board] **Ramp on the shop run** = P-56 again (swarm hits). Next Firelink → merchant: today's code + `--pull` (knives now: lure on).

