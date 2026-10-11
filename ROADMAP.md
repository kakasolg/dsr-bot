# ROADMAP — what is open now

Short on purpose: **only open work, one line each**. Full history (Korean, verbatim, nothing deleted) lives in
`docs/roadmap/` — find any section id (`1-m`, `6-a`, `P-29` …) there with `grep -n "1-m\." docs/roadmap/*.md`.

| File | Holds |
|---|---|
| `docs/roadmap/plan.md` | sections 0 … 7 in full (old rules, every `[x]` item with its check result, measurements, MoKa quotes) |
| `docs/roadmap/problems.md` | section 8 problem log P-1 … in full — **new problems are appended here** |
| `docs/roadmap/relay.md` | old section 10 board relay (2026-09-30 … 10-01) |
| `docs/roadmap/changelog.md` | old section 9 change log |
| `docs/analysis-2026-10-09.md` | problem analysis, public cases that solved similar problems, proposals (not decided) |
| `docs/design-multi-foe-spot.md` | design for proposal 1 (multi-foe = spot choice): measurements, design, steps, questions for MoKa |
| `docs/design-walk-follow.md` | design for proposal 2 (walking: progress check → replan, pass-through arrival, curvature slow-down deferred) |
| `docs/design-floor-check.md` | design for proposal 3 (one floor check: footing rule in fights, per-move look-ahead table, NavMesh + walked-cells floor map) |
| `docs/design-scene-expectations.md` | design for proposal 4 (human-checked scenes as test expectations: `duel_expect_test`, exact-input scenes) |
| `docs/design-run-settings.md` | design for proposal 5 (run settings record: `<run>.settings.json`, first log line, `fight_id`/`zone`, `sample.py`, `ab.py`) |
| `docs/review-v2-2026-10-11.md` | v1.0 → v2.0 review: last 7 days, structure problems, 2.0 features and order (not decided) |

Rules for keeping this file small (CLAUDE.md has the full working rules):
- An item lives here while it is `[ ]` / `[~]` / `[!]`. When it becomes `[x]` or `[-]`, move the line (with its one-line
  check result) to the matching section of `docs/roadmap/plan.md` and delete it here.
- Details, run logs and numbers go in the archive or in `data/samples/`; here one line + a pointer.
- Status marks: `[ ]` todo · `[~]` in progress · `[!]` blocked · `[x]` done · `[-]` cancelled. Roles: `[cloud]` `[win]` `[MoKa]` (old `[사람]` = MoKa).

---

## v1.0 / v2.0 (MoKa 2026-10-11: keep them apart)

- **v1.0** = today's structure (`souls/field.py`'s own loops, zones in `souls/missions.py`, module constants). Sections 1–2:
  game checks of what is built, MoKa decisions, small fixes. No structure work here.
- **v2.0** = section 3, the structure from `docs/review-v2-2026-10-11.md`. Starts after the `v1.0` tag (which commit: MoKa).
- A new item goes to v2.0 when it needs the tick loop, route data, the settings object or WorldState; otherwise v1.0.

## 1. Now (v1.0) — Undead Burg bonfire → Taurus Demon (1-m, MoKa 2026-10-06)

Bot already clears cell → Undead Burg bonfire in one run (10-03e). `run.py burg-upper` = MoKa's safe-spot zones 1–8
(`data/burg-upper-map.json`). Test save: `backup-20261006-155749-burg-bonfire-hp742-before-taurus`.
10-06 bot runs cleared zones 1–8 one or a few at a time (zone 4 lowest HP 40 %); the `--seg 5-8` run died at the
zone 8 crossbowmen (P-47).

- [ ] [win] Zone 8: at the ladder top **roll twice** away from the two crossbowmen, then fight (MoKa 10-06) → P-47
- [ ] [cloud]+[win] Taurus: bridge F9#7 calls the boss → run to ladder, climb → **gold pine resin** → plunge (~40 % of boss HP) → ~4 light attacks, keep stamina > 0; start with ≥ 1 Estus (MoKa 10-06)
- [ ] [cloud]+[win] Boss fight default = two-handed + dodging (9-30 principle); Taurus is the first case (the general boss module is v2.0)
- [ ] [cloud] Firebomb hollow "close in fast" rule — unless the way there is a fall-risk zone (ledge 254012 is ignored) → check with `duel_golden_test`
- [~] [win] Zone-by-zone bot runs; after each: `blind_report.py` · `hotspots.py` · `track_report.py`, logs to `data/samples/`
- [~] [MoKa] Recordings of the route (3 done, Taurus killed in the 3rd) — more only if a zone needs it

## 2. v1.0 — open by area

**Fight rules / reflexes (1-j: "basic reflexes done right", MoKa 10-02)**
- [~] [cloud] Scene expectations (proposal 4, `docs/design-scene-expectations.md`) — steps 1–2 done 2026-10-09: `tests/scene_world.py`, `tests/duel_expect_test.py`, `tests/expect/duel.jsonl` 48 scenes (13 from MoKa instructions / P-31 / P-33, 35 from blind labels whose rebuild = the bot's own choice): pass 34 · known_fail P-33 9 · P-31 1 · review 4; catches 4/4 deliberate rule breaks. Step 3 done offline 2026-10-10: `scenes.py` (`duel.SCENE_TAP`, `run.py --ctl-scenes`), `scene_replay.py` — round trip 687/687 same rule, tap changes no decision, ~40 µs/tick, ~2–4 KB per kept decision; `label_pilot` takes commit + `--basic` flags from the run's settings record (`runinfo.covering`)
- [ ] [MoKa] Skim `tests/expect/duel.jsonl` label lines (10 min) and the 4 `review` scenes: idle hollow 8.7–8.9 m (you: hold/reposition, bot approached) ×2, swing at 2.2 m (you: reposition, bot guarded), 'other' anim 2.0 m (you: attack/guard, bot approached)
- [~] [cloud] One floor check (proposal 3, P-49, `docs/design-floor-check.md`) — C floor map done offline 2026-10-10: `ground.py` (`Ground` = NavMesh + walked cells, `data/walked/<map>.npz` 38,598 positions / 160 KB); leave-one-run-out (`experiments/floor_map_check.py`): false "no floor" on real steps 2.1 % → 0.5 %, the 5 recorded falls still "no floor" 5/5; `tests/ground_test.py`. `run.py --ground` (off by default): walks and fights read floor through Ground, the fall / ledge watch keeps the plain NavMesh, and whether a walk checks floor at all stays the NavMesh's call. Walk harness, passage entrance pre-fix route: stall 11.6–13.7 s → 1.6–2.1 s (game 1.8–4.4 s), after-fix route unchanged. A `rule_footing` → v2.0 (section 3)
- [ ] [MoKa] `--ground` (walks only) on by default, or more runs that reach the passage? (round 2 numbers on the board 2026-10-11)
- [ ] [win] Check MoKa's 10-10 escape rules in game (`souls/escape.py`, P-56): log lines `물러날 쪽: 온 길/옆길/화톳불 쪽 …`, `빈틈 쪽 (…°)으로 … 구른 뒤 물러남`, `빈틈 없음 — … 약공 (n/2)`. Ramp runs `burg-bonfire --seg 1-2`; a roll into a drop or back into a foe → stop and report to [cloud] — 10-11 `070611`: none of the three lines fired (passage end, no death, low 62 %); more runs
- [~] [win] A/B `--ground` **round 2** (cloud answer 10-10, P-56; round 1 stopped at a ramp-ledge death): `--ground` now = walks only (fights / recover / reflex keep the NavMesh). `burg-bonfire --seg 1-2 --no-lure` ×3 without, ×3 with, same save, alternate off/on — **10-10 [win]: 6 runs done, report in relay.md; waits for the MoKa item above**
- [~] [cloud] Body pull `notice_pull` (MoKa 10-11: no knives before the merchant) — offline done 10-11: `experiments/notice_probe.py` → `data/notice.json` (534 clean wakes: shield soldiers ~9 m, burg hollows ~7.5 m, ramp hollows ~5 m; a body turn alone came only 15/104), `souls/pull.py`, `Field.notice_pull`, `run.py --pull` (off), `tests/pull_test.py`
- [ ] [win] A/B `--pull`: `burg-bonfire --seg 1-2 --no-lure` ×3 without, ×3 with (`--pull`), same save; log `몸으로 끌기 — … 알아채는 거리 … m` / `… 깸 — 돌아감` / `달려서 … 돌아감`; report to [cloud] first — **10-11: stopped after 3 runs; [cloud] fixed the thrower pull + P-60 → run 3+3 again** (new log lines `던지는 적 — … 끌지 않음`, `깼지만 … 안 옴`)
- [~] [cloud] Split `no_spot` (74 of 112 in data/samples) → first ≤ 7 m of `escape.pick`'s path (`duel._escape_way`, `SEP_ESCAPE`) — offline done 10-11, golden unchanged; [win]: log `떼어놓기 n: … → escape_arrived` — 10-11 `070611`: 1× in game (254001 1.4 m + 254002 1.1 m → escape_arrived, no hit after)
- [~] [cloud] Hit by a thrower (no foe swinging within 4 m) → `duel.rule_shot` ends the fight 'shot' → `Field.leave_fire` backs off beyond 11 m of it (holds the first shot while a melee foe is on us) — offline done 10-11; [win]: log `원거리 피격 −…` / `사선 밖으로` — 10-11 `070611`: 1× `버팀` (254002 18.2 m, +10.8 m up, 254000 at 1.6 m), no `사선 밖으로` yet
- [~] [win] P-32 axe hollow `AXE_HOLLOW` guard — game check on the ramp (needs MoKa's go)
- [ ] [MoKa] P-31 decide: `rule_finish` only within `reach + 0.3` (re-record golden)
- [ ] [MoKa] P-33 decide: no `stagger_punish` right after a block; [win] first checks per-foe stagger anims in old logs (read-only)
- [ ] [win] Read-only: `control.Pad` stuck-input detection; reflex order inside a walk tick
- [ ] [win] Read-only: retreat/Estus decisions when ≥ 2 foes were close, from old runs
- [ ] [win] #4 `ranged` (thrower) classification fix — changes lure/wait, compare in its own runs
- [~] [win] Battle-axe vertical heavy against walls (two-handed only; shield soldiers: heavy → light) — game checks

**Walking / navigation (1-f)**
- [ ] [win] [urgent since 09-30] "almost arrived" rule check in game (`거의 도착 … 다음 점으로` lines, asylum 1 m-short spots)
- [~] [win] 1-f A: early-turn / rubbing at corners reduced? (`hotspots.py`)

**Instrumentation / run records**
- [ ] [win] P1-E ordering · queue overflow · write failure · on/off-equal tests (1-l)
- [~] [cloud] Run settings record (proposal 5, `docs/design-run-settings.md`) — steps 1–2 done offline 2026-10-09: `runinfo.py` (`<run>.settings.json` + first log line + track `run` line), `fight_id`/`zone` in events, `sample.py`, `ab.py`, report headers; `tests/runinfo_test.py` + `run_stop_test` 20/20 checks, golden same
- [ ] [MoKa] Laya: keep off / freeze; move label tool's `why_not` out of `laya_shadow.py`?
- [ ] [MoKa] Ramp 24-scene labels (review mode) → `python label_pilot.py report --set ramp`; then size of the 300-label eval set

**Game files · radar · overlay (2, 4, 5)**
- [~] [win] Re-run `msb_extract.py m10_02_00_00 m10_01_00_00` for `treasures`
- [~] [win] Borderless overlay + bot: overlay visible, clicks pass through, bot does not stop
- [~] [win] Radar upgrade check (navmesh drawn, pad slots, recording, `--replay`)
- [ ] [win] Radar AI ranges (sight cone, hearing circle, leash) match the game

## 3. v2.0 — after the `v1.0` tag (`docs/review-v2-2026-10-11.md`; go, done bar N/10 and order: MoKa)

**Structure (review §2; proposed order §4: settings → WorldState → tick loop → route data → spots → batch runner → boss)**
- [ ] [cloud] Settings object: one object passed in instead of ~228 module constants that `run.py` overwrites; `runinfo` saves that object
- [ ] [cloud] WorldState: who is alive / where after a bonfire rest, quit-out (byte/menu) or warp, fixed in one place (P-18, P-25, P-44, P-55)
- [ ] [cloud] One tick loop (read → update state → pick one action → input) instead of `field.py`'s own loops; walking first, one part at a time, guarded by `scene_replay` + `duel_golden_test`; v1.0 keeps running meanwhile
- [ ] [cloud] Route data (walk / careful walk / safe spot / pull / fight / ladder / fog wall / Estus bar) + one runner; `burg-upper` moved first, then new segments without zone code
- [ ] [cloud]+[win] Batch A/B runner: save restore · warp · N runs · `ab.py` report → "pass rate n/10 per segment"

**Features (review §3)**
- [~] [cloud] Multi-foe = spot choice (analysis proposal 1): design drafted `docs/design-multi-foe-spot.md`; step 1 (measure only) waits for MoKa's answers (§8)
- [ ] [cloud] Same floor check everywhere: A `rule_footing` (`docs/design-floor-check.md`, needs MoKa §7) on the one tick loop, with collision-mesh edges (below)
- [ ] [cloud] Collision mesh: read `map/*.hkxbhd` with soulstruct-havok; classify NavMesh edges wall/cliff → `EDGE_PENALTY`
- [~] [cloud] Compare target walk rules inside `_follow` on layer 2, then [win] A/B — design drafted `docs/design-walk-follow.md` (proposal 2); waits for MoKa (§7)
- [~] [cloud] Harness layer-2 trust check: reproduces the passage-entrance point-70 before/after (direction yes, size exaggerated)
- [ ] [cloud] 1-f C: at a stuck corner go 1 m further along the incoming direction before turning
- [ ] [cloud] Boss fight module (its own loop; Taurus from section 1 as the first case)
- [ ] [cloud] After a death: save mission progress, recover the bloodstain, restart from the broken segment
- [ ] [cloud] Feed a recording back into the bot's decision code ("what would the bot have done")
- [ ] [MoKa] Town entry: zone-boundary F9 walk plan · B-hit design (not approved) — as route data

**Later / parked (not in 2.0)**
- 1-g learning (MoKa 09-28/09-30): step 1 motion model = 6-a layer 2 (done); step 2 imitation policy after layer-2 trust check — needs the batch runner first
- [ ] [cloud] 2D simulator: enemy sense/chase/leash from NavMesh + ThinkParam, plug `souls/field.py` in, separate/lure strategy experiments
- [ ] [cloud] Explore mode (offline only, invincible + invisible), Lua decompile, TAE timing → attack prediction; foe reaction table from game data (review ⑥)

## 4. Problem index

Full entries: `docs/roadmap/problems.md`. Status: **open** · **parked** · **decide** (waits for MoKa) ·
**verify** (fixed offline, game check pending) · **fixed** · **won't fix**.

| P | Problem | Status |
|---|---|---|
| 1 | Offline tests failed on Linux (Windows-only imports, `TEMP`) | fixed |
| 2 | Python 3.11 f-string syntax error | fixed (3.12) |
| 3 | soulstruct import fails on Linux (missing JSON) | fixed (stub modules) |
| 4 | `msb_extract` summary counts / missing ObjectParam rows | fixed |
| 5 | `.gitignore` let local run files show as untracked | fixed (allow-list) |
| 6 | Burg: stuck behind a ledge foe; path through crates | verify |
| 7 | Two shield soldiers: no separation spot (`no_spot`), late reaction to the side foe | open → same family as P-29 |
| 8 | Died to two shield soldiers (light attacks into raised shields) | open → P-29 family |
| 9 | Overlay mini-radar marks unreadable; restored items stayed hidden | fixed |
| 10 | Late on a shield soldier's advancing first attack (3009) | open, low priority |
| 11 | Real controller ignored after bot runs / save swaps (ViGEm) | workaround: reboot |
| 12 | Same stalls every run (`#3 이동` (−52.2,−22.8,−26.9), crates `o1150_01`, `o1132_06`, `o1321_0021`) | open |
| 13 | Web radar hid the human pad (bot slot stayed) | fixed |
| 14 | Fell off the ramp edge right after a backstab | verify |
| 15 | Bot imported a moved experiment module mid-run | fixed (see P-43) |
| 16 | Fell through a gap while circling for a backstab | verify |
| 17 | Secret-passage exit: stuck / fell | parked → 1-g |
| 18 | Ramp `left #N?` after a quit-out ended the mission | verify (`pass_ramp`) |
| 19 | `experiments/reach.py direct` walked off a railing | open, low priority |
| 20 | Two radar servers bound the same port | fixed (exclusive bind) |
| 21 | steam.exe outside connection right after restart (CDN) | decide (a/b/c) |
| 22 | Throwing knife not in a quick slot → lure always fails | fixed (start check) |
| 23 | Read weapon slot 1 instead of the held weapon | fixed |
| 24 | `--no-lure` ignored by `burg-bonfire`; `no_knife` retried | fixed |
| 25 | Killed foes come back after a quit-out — cause: the byte quit-out (game test) | verify — `shake` now uses the menu, only falls use byte (+ revive_risk) |
| 26 | Crowd retreat broke every 1–2 s, 16 times, 0 attacks | open (`CROWD_FALL_BACK` off, capped) |
| 27 | Asylum: bot idle between segments got hit; died beside a foe | fixed |
| 28 | Asylum: same 3 stall spots (self-recovered) | open |
| 29 | Burg `#4 이동`: three 254010 at once, 0 attacks, died (twice) | open — top cause of deaths |
| 30 | Ignored foe hit for 10 s, then fell 5 m through a gap; lock-on blocked by line of sight | partly fixed |
| 31 | `rule_finish` swings from 2.2–4.0 m | decide |
| 32 | Dropped guard too early vs axe hollow 254001 | verify |
| 33 | `stagger_punish` right after a block (should keep blocking) | decide |
| 34 | Radar-rebuilt features ≠ bot's real features (audit gate failed) | won't fix (audit frozen 10-02) |
| 35 | Audit: unobserved outcome window classified primary | fixed |
| 36 | Audit checker double-counted exclusion reasons | fixed |
| 37 | Audit can't attribute an outcome to one foe (no projectile data) | fixed; frozen at schema 0.3 |
| 38 | Mover didn't re-press guard/sprint after a neutral | verify (P0-D) |
| 39 | Asylum ④: light instead of wall heavy vs two hollows | fixed |
| 40 | Asylum ② menu: DOWN eaten before the equip screen opened | fixed |
| 41 | Burg fog wall before `#4 이동` not passed | fixed |
| 42 | `careful_walk` back-and-forth at one spot | fixed (verified 10-03d) |
| 43 | CI red 22 times (Linux pipe size, `vgamepad` via legacy import) | fixed |
| 44 | Restoring a save does not restore the radar warp list | decide |
| 45 | `burg-upper` zone 2: chaser caught the bot mid-walk, died 13 m from the safe spot | fixed (run back to safe spot) |
| 46 | `burg-upper` zone 5: no rules for 255001 (shield + spear) | fixed (`foes.SHIELD`, wait/lure) |
| 47 | "HP low" 0 s fight loops; zone 8 death; 'cleared' with survivors | partly fixed; zone 8 → section 1 |
| 48 | 6-a "48 % of sharp corners cut inside" is a 2 Hz sampling artifact (10 Hz: 20 %, two places) | open (measure fix) |
| 49 | Ramp ledge (−22,−40,13): knocked off 3× fighting the axe hollow, standing off-mesh; `rule_edge` only raised the shield | open → design-floor-check |
| 50 | `scene_replay` fake `face()` always True → a 42.5° scene replayed as `finish_first` (97 %) | fixed |
| 51 | `burg-upper` zone 3 (5,−92): hit twice while backing off the edge after backstabs, −181 | open |
| 52 | Dirty run: first log line's settings hash ≠ the record's (`code.diff_file` was hashed) | fixed |
| 53 | `burg-upper` zone 1 (−1.9,−14,−70): fell 4 m right after a hit, quit-out recovered | open |
| 54 | `scene_replay` fake reflex kept a fixed age — a mid-chain anim change (3000→3002) replayed as `hit_first` | fixed |
| 55 | `passage-drill`: the bonfire warp revives the ramp foes → died on the way to the top | open (A/B moved to seg 1-2) |
| 56 | Ramp ledge (−20,−39,14), `--ground` on: 254002 + axe 254001 swinging together, died (no fall) | verify — back off toward no foes, roll through a gap / lights to open one (MoKa 10-10) |
| 57 | Passage start (−20,−39.3,14.4): 1.5 s stall + turn-around retry, in 2 `--ground`-off runs (0 in the 2 on runs that got there); AGAIN 10-11, 4/15 runs | open → [cloud] |
| 58 | Ramp ledge (−22,−44,15) in a fight: fell 4.4 m, quit-out, walk-back timed out, died (`--ground` round 2 on #3) | open → P-49 |
| 59 | `rule_shot` may read a 254010 lunge landing from > 4 m as a throw (4 track cases) → ends the fight, backs off | verify — thrower = `Foe.thrower` only, axe hollow not one, melee 6 m + duel-start window |
| 60 | After a body pull, `unsafe_approach` 0 s fights opened and closed 24× in 1.4 s (no guard) | verify — queue branch waits on the flat |

## 5. Relay — [cloud] ↔ board

[cloud] cannot reach the private MCP board (CLAUDE.md). Format: `- date [cloud→board] text` / `- date [board→cloud] text`;
whoever moves or handles an entry adds `→ moved` / `→ done` (old entries: `[cloud→게시판]`, `→ 옮김` / `→ 처리` — same thing). When every entry here is `→ moved`/`→ done`, cut them
to the bottom of `docs/roadmap/relay.md`.

(empty — handled entries moved to `docs/roadmap/relay.md` 2026-10-11)

- 2026-10-11 [board→cloud] **ROADMAP split into v1.0 / v2.0 (MoKa 10-11: keep them apart)**: sections 1–2 = v1.0 (today's structure: game checks, decisions, small fixes); new section 3 = v2.0 (settings object, WorldState, one tick loop, route data, batch runner, then multi-foe spots, `rule_footing` + collision mesh, walk follow, boss module, resume after death). A new item goes to v2.0 when it needs the tick loop / route data / settings object / WorldState. v2.0 go, the N/10 bar and the `v1.0` commit are still MoKa's (asked on the board). Section numbers moved: Problem index 4, Relay 5. → done (read; [cloud] files new items by that rule)

- 2026-10-11 [cloud→board] **`--pull` fixes done offline** (`git pull`, both v1.0 small fixes): (1) no body pull for throwers (`Foe.thrower`: firebomb hollows, crossbowman) → `thrower`, the bot goes on as without `--pull`; (2) after running back it watches 2 s — `came` only if the target left its spot (≥ 1.5 m) toward us, else `stayed`; axe hollow 254001 is still pulled; (3) P-60: the queue target now waits / defends on the flat after `unsafe_approach` (was 24 fights in 1.4 s). pytest 79. **[win]**: `--pull` A/B 3+3 again (section 2 item).

- 2026-10-11 [board→cloud] **v1.0 check run `070611`** (`64e52cb`, `--seg 1-2 --no-lure --ctl-scenes`, ground/pull off): passage end 127 s, no death, low 62 %, big hits 2 (−216), blind 29.9 s −216 (usual). In game: `no_spot` split 1× → `escape_arrived` (the P-56 pair 254001 + 254002, no hit after); `rule_shot` 1× held (254002 18.2 m up a level, melee 254000 at 1.6 m). Escape lines (`물러날 쪽` …) did not fire. P-57 spot AGAIN (4/15 runs, stalls 2.5 s + 1.5 s, passage walk itself clean). Scenes 10/10. Sample `*_v1check-passage`.

## 6. Change log (newest first; older entries in `docs/roadmap/changelog.md`)

- (moved to `docs/roadmap/changelog.md` 2026-10-11 to keep this file under its size limit)
