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

Rules for keeping this file small (CLAUDE.md has the full working rules):
- An item lives here while it is `[ ]` / `[~]` / `[!]`. When it becomes `[x]` or `[-]`, move the line (with its one-line
  check result) to the matching section of `docs/roadmap/plan.md` and delete it here.
- Details, run logs and numbers go in the archive or in `data/samples/`; here one line + a pointer.
- Status marks: `[ ]` todo · `[~]` in progress · `[!]` blocked · `[x]` done · `[-]` cancelled. Roles: `[cloud]` `[win]` `[MoKa]` (old `[사람]` = MoKa).

---

## 1. Now — Undead Burg bonfire → Taurus Demon (1-m, MoKa 2026-10-06)

Bot already clears cell → Undead Burg bonfire in one run (10-03e). `run.py burg-upper` = MoKa's safe-spot zones 1–8
(`data/burg-upper-map.json`). Test save: `backup-20261006-155749-burg-bonfire-hp742-before-taurus`.
10-06 bot runs cleared zones 1–8 one or a few at a time (zone 4 lowest HP 40 %); the `--seg 5-8` run died at the
zone 8 crossbowmen (P-47).

- [ ] [win] Zone 8: at the ladder top **roll twice** away from the two crossbowmen, then fight (MoKa 10-06) → P-47
- [ ] [cloud]+[win] Taurus: bridge F9#7 calls the boss → run to ladder, climb → **gold pine resin** → plunge (~40 % of boss HP) → ~4 light attacks, keep stamina > 0; start with ≥ 1 Estus (MoKa 10-06)
- [ ] [cloud] Firebomb hollow "close in fast" rule — unless the way there is a fall-risk zone (ledge 254012 is ignored) → check with `duel_golden_test`
- [~] [win] Zone-by-zone bot runs; after each: `blind_report.py` · `hotspots.py` · `track_report.py`, logs to `data/samples/`
- [~] [MoKa] Recordings of the route (3 done, Taurus killed in the 3rd) — more only if a zone needs it

## 2. Open by area

**Fight rules / reflexes (1-j: "basic reflexes done right", MoKa 10-02)**
- [~] [cloud] Multi-foe = spot choice (analysis proposal 1): design drafted `docs/design-multi-foe-spot.md`; step 1 (measure only) waits for MoKa's answers (§8)
- [~] [win] P-32 axe hollow `AXE_HOLLOW` guard — game check on the ramp (needs MoKa's go)
- [ ] [MoKa] P-31 decide: `rule_finish` only within `reach + 0.3` (re-record golden)
- [ ] [MoKa] P-33 decide: no `stagger_punish` right after a block; [win] first checks per-foe stagger anims in old logs (read-only)
- [ ] [win] Read-only: `control.Pad` stuck-input detection; reflex order inside a walk tick
- [ ] [win] Read-only: retreat/Estus decisions when ≥ 2 foes were close, from old runs
- [ ] [win] #4 `ranged` (thrower) classification fix — changes lure/wait, compare in its own runs
- [~] [win] Battle-axe vertical heavy against walls (two-handed only; shield soldiers: heavy → light) — game checks
- [ ] [cloud]+[win] Boss fight default = two-handed + dodging (9-30 principle); Taurus is the first case

**Walking / navigation (6-a harness, 1-f, 1-g)**
- [~] [cloud] Harness layer-2 trust check: reproduces the passage-entrance point-70 before/after (direction yes, size exaggerated)
- [ ] [cloud] Compare target walk rules (progress switch · lateral slow-down · look-ahead · stop · recover) inside `_follow` on layer 2, then [win] A/B
- [ ] [win] [urgent since 09-30] "almost arrived" rule check in game (`거의 도착 … 다음 점으로` lines, asylum 1 m-short spots)
- [~] [win] 1-f A: early-turn / rubbing at corners reduced? (`hotspots.py`)
- [ ] [cloud] 1-f C: at a stuck corner go 1 m further along the incoming direction before turning — parked behind 1-g
- 1-g learning (parked, MoKa 09-28/09-30): step 1 motion model = 6-a layer 2 (done); step 2 imitation policy after layer-2 trust check

**Instrumentation / run records**
- [ ] [win] P1-D observation quality · Escape · watchdog events (`--ctl-frames` off by default) (1-l)
- [ ] [win] P1-E ordering · queue overflow · write failure · on/off-equal tests (1-l)
- [ ] [MoKa] decide run settings file `<run>.settings.json` + `code_commit` / zone / fight id in logs (1-i, 1-j)
- [ ] [MoKa] Laya: keep off / freeze; move label tool's `why_not` out of `laya_shadow.py`?
- [ ] [MoKa] Ramp 24-scene labels (review mode) → `python label_pilot.py report --set ramp`; then size of the 300-label eval set
- [ ] [MoKa] Town entry: zone-boundary F9 walk plan · B-hit design (not approved)

**Game files · radar · overlay (2, 4, 5)**
- [~] [win] Re-run `msb_extract.py m10_02_00_00 m10_01_00_00` for `treasures`
- [~] [win] Borderless overlay + bot: overlay visible, clicks pass through, bot does not stop
- [~] [win] Radar upgrade check (navmesh drawn, pad slots, recording, `--replay`)
- [ ] [win] Radar AI ranges (sight cone, hearing circle, leash) match the game
- [ ] [cloud] Feed a recording back into the bot's decision code ("what would the bot have done")

**Later / parked (3, 6, 7)**
- [ ] [cloud] Collision mesh: read `map/*.hkxbhd` with soulstruct-havok; classify NavMesh edges wall/cliff → `EDGE_PENALTY`
- [ ] [cloud] 2D simulator: enemy sense/chase/leash from NavMesh + ThinkParam, plug `souls/field.py` in, separate/lure strategy experiments
- [ ] [cloud] Explore mode (offline only, invincible + invisible), Lua decompile, TAE timing → attack prediction

## 3. Problem index

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
| 25 | Killed foes come back after a quit-out (game bug, sometimes) | open (partly handled) |
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

## 4. Relay — [cloud] ↔ board

[cloud] cannot reach the private MCP board (CLAUDE.md). Format: `- date [cloud→board] text` / `- date [board→cloud] text`;
whoever moves or handles an entry adds `→ moved` / `→ done` (old entries: `[cloud→게시판]`, `→ 옮김` / `→ 처리` — same thing). When every entry here is `→ moved`/`→ done`, cut them
to the bottom of `docs/roadmap/relay.md`.

- 2026-10-09 [cloud→board] ROADMAP slimmed 307 KB → this file; all old text moved verbatim to `docs/roadmap/` (sections 0–7 → `plan.md`, problem log → `problems.md`, relay → `relay.md`, change log → `changelog.md`). Found while doing it: commit `2c5daf8` (10-02, P-37 edit) deleted the `## 10. 게시판 중계` heading, so the relay entries sat inside P-43 and CLAUDE.md pointed to a missing section — restored in `relay.md`.
- 2026-10-09 [cloud→board] **[MoKa] decide**: (1) ~~section 3 "Old open items"~~ → all cancelled by MoKa 2026-10-09 → done (2) ~~close public issues #2 #5 #7 #9 #10 #14~~ → closed 2026-10-09 with a pointer to the index (#9 completed, others not planned) → done (3) ~~merge the work branch into `main`~~ → `main` fast-forwarded to the work branch 2026-10-09 (247 commits) → done; keep doing it from time to time (the session-start hook warns when `main` lags).
- 2026-10-09 [cloud→board] **[MoKa] decide**: which proposals from `docs/analysis-2026-10-09.md` §3 to take up — (1) multi-foe = pick a spot where ≤ 1 foe can reach us (general rule; `burg-upper` safe spots as candidates) (2) walking: curvature slow-down + minimum approach speed + progress check → replan (Nav2 RPP style, tested in `walksim.py`) (3) one look-ahead floor check (4) human-checked scenes as test expectations (5) run settings record.
- 2026-10-09 [cloud→board] Proposal 1 design draft: `docs/design-multi-foe-spot.md`. Found offline: P-29's third hollow ran in at 3.5 m/s with anim −1 (counted as 'standing' by `_crowd`); MoKa's `burg-upper` safe spots are mostly open ground (5/8), what they share is distance — ≥ 11 m by path from their foes and from the ledge firebombs (zone 3, dropped by MoKa, is 7.7 m; zone 8, P-47, is 6–7 m from the crossbows). **[MoKa] decide** §8: (1) human spots = candidate + bonus or must-use (2) run to the spot (3) spots next to a drop: penalty or filter (zones 4·8 read 0.5 m) (4) zone 8 → spot ~11 m east like the recording? (5) knife to wake one at a time?

## 5. Change log (newest first; older entries in `docs/roadmap/changelog.md`)

- 2026-10-09: `main` and the work branch fast-forwarded to the same commit (09-28 … 10-06 work + this restructure).
- 2026-10-09: [MoKa] old public issues #2 #5 #7 #9 #10 #14 closed (P-17/18/21/25 stay tracked in the problem index).
- 2026-10-09: [MoKa] cancelled all 11 "old open items" (15 archive lines marked `[-]` in `docs/roadmap/plan.md`); section removed.
- 2026-10-09: ROADMAP restructured — open items only, English; history moved verbatim to `docs/roadmap/`; relay section restored; problem index added. `tests/roadmap_test.py` keeps this file small and the index complete.
