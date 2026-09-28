# DSR bot layer structure

Translated from Korean (2026-09). Log strings quoted in backticks are the literal (Korean) messages the bot prints.

2026-09-24 user: "Basic moves, per-weapon usage, how to kill enemies in the field, item farming, how to fight bosses — they're all mixed together, so it's hard to manage."
Everything was mixed together in `hunt.py` (3,267 lines), so fixing one rule left the old behavior still coming out of another path.
Examples: heavy attack was pressed in two places, estus after a kill was separate per plan, kick existed only inside heavy-attack mode.

**Lower layers do not know about upper layers.** Each rule lives in exactly one place in one layer.

| Layer | Files | Knows | Does not know |
|---|---|---|---|
| 0 Game link | `control.py` `dsr_telemetry.py` `feed.py` `env.py` `nav.py` `navmesh.py` `quitout.py` `farm.py` | Memory reads (one feed thread reads, everyone sees the same frame), pad reports, going to one path point, menus, **path recovery** (if off the mesh, snap to a mesh point at the same height; start/end correction; a step too high to walk up = no path) | Weapon, enemies, goals |
| 1 Basic moves | `souls/moves.py` | Light/heavy attack, kick, backstep, roll, drinking estus, choosing items, walking a path, quit-out, resting | Whom to hit, when to drink |
| 2 Weapon usage | `souls/weapons.py` | Per weapon ID: reach, number of chained hits, heavy-attack use, required strength | Enemies, buttons |
| Reflex (above layer 1, below layer 3) | `souls/reflex.py` | If anyone within 2.5 m starts swinging (for 1.3 s), keep it in front and shield; if hit by something unseen, shield toward the nearest one. Layers 3 and 4 call it **first every tick**, and skip any tick in which the reflex moved | Weapon, goals |
| 3 Enemy handling | `souls/foes.py` (data) `souls/duel.py` (one enemy) | Response per enemy type, the choice for one tick (block, close in, kick, hit) | Other enemies, estus, path |
| 4 Playbook | `souls/field.py` `souls/watch.py` · bosses in `boss/` | **Engagement queue** (awake, approaching enemies nearest first → only when none, the next one on the spawn list), recovery, peeling enemies off, walking paths, bloodstains, resting | Mission destination |
| Style | `souls/style.py` | Shield or not, grip, evasion style, backstep attack, punish-after-whiff values in one object (guard / backstep). Every layer only reads it | — |
| 5 Missions | `souls/missions.py` → `run.py` | Which playbooks in what order | Control details |

## Where each rule lives (one place only)

| Rule (source) | Where |
|---|---|
| Attack buttons 0.16 s after releasing the stick — forward+R1 = kick, forward+R2 = jump attack (user, control chart) | `control.Pad.release_stick` — enforced by `tap(R1)`/`heavy()`. Exceptions: `kick()`, `jump_attack()`, `tap(stick_ok=True)` (plunging attack) |
| Sprint B is held for the whole path — releasing at each point makes a short B = roll/jump (review) | `nav.follow` keeps one Mover to the end of the path |
| No jumping (user) | Layer 1 has no jump move |
| Estus: re-check safety after selecting the slot; success only if the count drops (review) | `moves.drink` |
| Estus ID is per upgrade level; new character 201 | `moves.estus_id` |
| Broadsword: 2-hit light chain, no heavy attack, reach 1.4 m (user, wiki, measured) | `weapons.BROADSWORD` |
| Zweihander: heavy attack is an overhead slam; two-handed needs 16 strength (wiki) | `weapons.ZWEIHANDER` |
| Kick a shield soldier standing still and facing me (user, wiki) | `foes.SHIELD.kick_when_idle` → `duel` 5) |
| Firebomb hollows don't come down — run up to them | `foes.FIREBOMB_HOLLOW.ranged` → `duel._approach` |
| Close in via path even on enemies atop a high ledge (#4, #5, #6 timed out) | `duel` 3) — horizontal distance + height difference 1 m |
| Stalemate is "15 s with 0 damage" (previously: 6 hits → abandon the run) | `duel.STALEMATE_S` |
| Don't go to the graveyard skeletons at the current level (user) | `foes.SKELETON.avoid` |
| After a kill, drink estus if HP below 70 % (user: "doesn't drink estus"); pre-select the estus slot before fighting | `field.fight` |
| One failed enemy doesn't abandon the run — recover and retry the same one (three times) | `field.clear` |
| Quit-out resets only position/aggro; dead enemies don't come back (user confirmed, 2026-09-24). **Correction/caution (2026-09-26, observe R1 `101202`)**: after a quit-out/reload (Escape), in the new generation a fresh entity with raw HP 85/85 (`h:10008018#1`) stood at #2's spawn — the previous generation's #2 had raw HP 0 and the run was logged as `cleared`. **Quit-out/reload = new-life boundary**; don't merge enemies across it (`field._liveness` drops old identities on an `esc.gen` change). **You restart on the spot** — next to an enemy spawn, it engages again immediately (repeated 5 times, 659 → 24; user: "bad spot for a force-quit right now") → don't use it to peel enemies off | `watch.Escape` (lethal falls / imminent death only) |
| Fight gone wrong, enemy close, HP below 60 %: back off toward the bonfire and drink once safe | `field.recover` |
| **Never use the Darksign** — like resting, every killed enemy revives (user), and you also lose souls and humanity = worse than dying (dying leaves a bloodstain). Used while engaged, you get killed during its 2–3 s. After reloading via quit-out/Darksign, enemies that were alive have full HP again | `moves.darksign` kept but nothing calls it |
| Shield soldier: kick → the moment the guard breaks (9600, 0.45–0.6 s) immediately a 2-hit light chain as one move (user: "the gap between the kick and the attack is so long the shield soldier guards again"). Against a shield soldier standing with shield up, the finisher also starts with a kick (finishing light attacks do only 1 each) | `moves.kick_combo` · `duel` |
| **When two engage together, separate them** (user 2026-09-26 (a)) — only when the target and another enemy are both within 4 m (same height) **and none of them is swinging** (between attacks — turning to run mid-lunge got me hit in the back −281, observe 094231), sprint 5 m away from their midpoint (toward the arena if it lies that way). Only to a spot on the navmesh with an unbroken straight line (clear_line); if none, don't run. 5 s cooldown, up to 3 times per fight; don't run in front of a staggered / downed / one-hit-kill enemy. From the hollow next to a shield soldier −161 → stamina −5 → guard broken at 3210 −103 (observe 092612) | `duel._pair_close`·`_separate`·`SEP_*` |
| **Kick shield soldiers one beat early — currently shadow only** (Patch D, 2026-09-26: the meaning of raw anims 3004/3500 is unverified, so auto-kick is off and `duel.ShadowKick` only logs a candidate event plus the outcome 1.5 s later per (handle, generation, anim, start). Real kicks (`early_kick="act"`) only in separately approved experiments). Original basis (user 2026-09-26) — 3004 lands 2.0–2.1 s after start regardless of approach speed: within 1.2 s, interrupt with a kick (both hits at 0.4–0.7 s took 0); past that, block (treating it as 'standing' past 1.6 s and kicking → −220, −323). The post-attack stagger 3500 soon retreats (0.8–1.3 s, 1 m → 3–4.7 m), so kick immediately — checked before reflex and lure (previously on 3500 it ran off to the arena via 'lure'). 3005 lunge: still block (1–2) | `foes.SHIELD.windup`·`windup_act_s`·`kick_on_stagger`·`early_kick` → `duel._early_kick_candidate`·`ShadowKick` |
| Shield soldier: only one stagger punish hit (between the second, it counters for 100–115) | `foes.SHIELD.punish_hits` |
| Lure: when it notices (moves or within 8 m), back off to flat ground (arena) and fight there (user: "drag them to the terrain you want"; at spot #2, firebombs from the ledge above landed for 275 in 1 s) | `duel` 0--) · `PULL_R` |
| Estus safety: unsafe if an awake thrower (firebomb) is within 25 m (checking only 8 m got me interrupted mid-drink and killed) | `field.safe` · `RANGED_R` |
| Reflex keeps whoever it started blocking in front for the duration of that attack, preferring the fight opponent (switching to the nearest every tick alternated between front and back ones and got me hit from the side/back) | `reflex._lock` · `prefer` |
| A non-swinging opponent that dies in one hit gets hit before the reflex (died just holding a shield in front of HP 18) | `duel` finisher at the very top |
| Broadsword reach 1.2 m — pre-emptive hits and finishers only within it (all 8 light attacks swung at 1.3–1.6 m whiffed, terrace) | `weapons.BROADSWORD.reach` |
| Stamina recovery and the reflex's 'back off' are **in place, facing forward** — without lock-on, pushing the stick backward turns and walks away, taking hits in the back (user: "can't align direction, attacks in a weird direction") | `duel` 4) · `reflex.step_away` |
| If it can neither back off nor drink, the next fight goes to the end (every 0.1 s it spun 'low → can't retreat → can't drink', standing there getting killed) | `field` desperate |
| The retreat spot is inside that zone — in Undead Burg, the entrance (B0) (no path to Firelink Shrine → no_path) | `missions` → `field.home` |
| **Hit first** — if a hollow in reach has just started an attack (within 0.35 s) or is standing still, light attack before shield (user: "if you'd swung even once that enemy would have backed off"; one light attack causes flinch 2000/2002). Not for shield soldiers; block first if another enemy beside is swinging | `duel.INTERRUPT_S` |
| Light attack: next tick as soon as my attack anim ends (it used to sit through the full 1.5 s seeing nothing) — the loop does one thing at a time, so cut holding time | `moves.light` early_exit |
| An attack anim (3000s) lasting over 1.6 s is not a swing — for block, hit-first, and kick decisions (a spear shield soldier stayed in 3001 with shield up; 15 s of blocking only, no kick) | `duel.SWING_S` |
| Switch targets only if more than 0.8 m closer, hold for 3 s after switching (switching every 1–2 s between two at similar distance got me hit in the back) | `duel.SWITCH_MARGIN`·`SWITCH_HOLD` |
| **Interlopers first** — if an awake enemy closer than the target is within 2.5 m at the same height, hit it, then back to the original target after the kill (user: "can't you attack the nearby enemy?"; watching only the map target, took 387 from the side in 13 s and died). 'Peel off to flat ground' was removed — it clashed with lure/reposition and spun | `duel.SWITCH_R` |
| **Ranged first, then interlopers** — if a thrower (foes.ranged) is throwing, go for it regardless of distance/height (within 25 m): otherwise it handles only the opponent in front while being hit from above (or far away), ending up defensive (user 2026-09-25: "the one shooting arrows from above is attacking, so it's set to defense mode — deal with that one first") | `duel.RANGED_SWITCH_R` |
| Fog wall: if blocked twice while walking a path, turn toward the next point and press A when the prompt ("Traverse the white light") appears (user: "press A at the fog wall", "align direction"). The Undead Burg fog doesn't reappear once passed (user) | `field.fog_through` |
| If not near its spawn, search up to 30 m (skipped #4, which had followed, as 'already dead') | `field.clear` |
| Lure/reposition only when the enemy can follow — not for enemies on a ledge more than 3 m in height from the arena (#5 just kept going up and down, blocked three times) | `duel.LEDGE_DY` |
| Even while it's swinging, if it's out of reach, approach with shield up (blocking in place can't reach an enemy repeating 3008 from afar) | `duel` 1) |
| **Knife lock-on starts with the camera** — R3 locks the enemy at camera center (auto lock-on). Before pressing, use the right stick to put the camera within 5° of it; if it catches the neighbor, release, re-aim camera → R3, up to 3 times (user: "release, point the camera at the enemy you want, press the stick"). Turning just the body and pressing R3 twice caught #3 beside it both times (clear-ramp 2026-09-26 090241). The right-stick sign is learned from the first pulse | `moves.look_at`·`look_pulse`·`throw_knife` |
| **The camera faces the enemy being engaged** — not needed for bot decisions, but so a human watching the screen can tell what it's doing (user 2026-09-26). The fought/lured enemy (`mv.cam_target`); otherwise the nearest awake, moving enemy within 12 m. Only turns when off by more than 25°. Hands off during lock-on (right stick switches target), knife lock-on, and emergency escape. Walk/attack directions are recomputed from the current camera each tick, so no effect | `souls/camera.CamFollow` (enabled by run.py) · `field.fight`/`lure` set `cam_target` |
| Ramp order 1 → 3 → **2** → 4 → 5 → 6 (order from the user's two demo runs, 2026-09-26). #2 shield soldier is woken with a knife **only from the flat ground (-30.35,-49.43,27.91) at 13–14.5 m** — closer is firebomb range; even if lock-on fails, don't move closer (user: "only from a distance as far as where I threw"). **If the lure fails, don't walk to the shield soldier; hold the throwing spot** — wait 8 s, take approaching enemies (#3 etc.) there, throw again; after 3 failures, move it to the end (user: "you have to hold the spot where you killed the first enemy; near there the shield soldier doesn't notice you"; the bot was spotted every time at 8.8–9.1 m from the shield soldier, the user never went within 12 m). Range cap 15 m. **Patch B (2026-09-26)**: don't go seek it even after deferring — try one more round of throws, and if that fails, neutral input and end with `partial deferred_unreachable #2` (the caller doesn't continue down the path). **Patch C**: don't keep the shield up while waiting (section below). Previously #2 was last, and if the flat ground was over 13 m away, the lure walked up to 10 m along the path to throw | `missions.RAMP_ORDER`·`RAMP_LURE_AT` → `field.lure(lure_at=)` |
| (Next candidate) firebomb throwers first, top to bottom (user, hunt.py note) | — |
| Blocked only counts beyond 3 m / if its HP is below 40, don't bail until my HP 12 % | `duel` 3) · `FINISH_KEEP_HP` |
| Resting revives all enemies → only when starting a fresh run | `field.rest_at`, `missions.start_fresh` |
| Kill enemies chasing on the path first (user: "there's an enemy, why don't you respond") | `field.walk` chaser |
| Quit-out only when about to die — two or more within 3.5 m and projected HP below 15 % in 2.8 s, once per 60 s (298 → 24 in 2.4 s) | `watch.Escape._dps` |
| Record a bloodstain only if souls dropped after respawn; don't press A within 6 m of a bonfire (fake death → sat down, enemies revived; measured twice) | `watch.Blood`, `field.pick_blood` |
| Block with the attacker **in front** — blocking to the side/back took 74, in front 34 (log analysis). Also for enemies other than the opponent | `reflex.Reflex.tick` |
| A threat is only the 1.3 s after an attack anim starts — 3000s linger for seconds, so the old reflex attacked just once in 87 s | `reflex.THREAT_S` |
| Shield only on a threat — holding it cuts stamina regen by 80 % (wiki) | `reflex` · `duel` 1) 4) |
| Unblockable attacks (shield soldier guard break 3009): backstep; if there's a drop behind, side roll (blocking got the guard broken, pushed off, fell to death, 2026-09-24) | `foes.SHIELD.unblockable` → `reflex.dodge` (layer 4 passes the check function) |
| If its HP is within one light attack (25), finish with as little as 15 stamina (shield soldier survived 4 s on HP 10) | `duel.FINISH_HP` |
| Don't fight next to a drop — if footing safety (nav.footing) is bad, back off to flat ground (ramp: ARENA) when it isn't swinging and meet it there. Quit-out can't save a fall (menu won't open while falling or flinching; user: "force-quit is slow") | `duel` 0-) · `missions.RAMP_ARENA` |
| Below 25 stamina, the reflex backs off instead of blocking, and the fight also backs off to recover instead of shielding (blocking at SP 12–22 got the guard broken, pushed off, fell to death) | `reflex.GUARD_SP` · `duel` 4) |
| During a quit-out, layer 4 and the runner wait (without waiting, it 'cancelled' the five remaining enemies in 0.5 s, and the program exited mid-quit-out) | `field.wait_escape` · `run.py` finally |
| Falls: also judge by fall speed (2.5 m in 0.4 s); quit-out if the ground is more than 8 m below (the 15 m threshold missed 10–12 m falls beside the ramp) | `watch.Escape.LETHAL_DROP`·`FALL_V` |
| Stagger (3500–3599) is not an attack but an **opening** — if it bounces off my block, light attack immediately (treating 3000–3599 as attacks, it blocked for 12 s straight) | `moves.ATTACK`/`STAGGER`, `duel` 1-) |
| Estus mid-fight: HP below 50 %, only in an opening (enemy down, or not swinging and beyond 3 m, others beyond 5 m). If engaged, backstep (user: "drink when it's safe") | `duel.opening` (opening) · `field.Care` (whether to drink) |
| While walking, if HP below 60 %, drink up to 70 % when safe (user) | `field.walk` |
| No lock-on (user, measured) | `moves.face` (align body by heading) |
| **Wake them one at a time** — hit a single enemy with a throwing knife (290) from beyond 13 m so it comes to the flat ground (arena), and fight there (user: "best is to pull them one at a time", "you have throwing knives, from afar"). Lock-on only when throwing (old measurement: without lock-on, enemies within 1.2° / above didn't get hit). Asleep is judged by anim -1 + 0.4 s stationary (comparing against map spawn coords misread one standing 6 m away as 'awake'). First run 2026-09-24: 6/6 killed, 0 force-quits, shield soldier also on flat ground. Warn below 5 knives — buying from the merchant later. Compare with `--no-lure` | `moves.throw_knife`·`aim`·`lock_state` · `field.lure`·`_asleep` · `field.clear(lure=)` |
| Knives **within 10 m** (lock-on at 12 m missed 2/3, 10.8 m hit). Thrown without lock-on, it flies along **camera direction/pitch**, so reset the camera behind the body with R3 before throwing (user: "align direction when throwing"). Melee whiffs are about range, not direction — within 5° and within 1.2 m 95 %, 1.2–1.6 m 70 % (110-swing analysis) | `field.LURE_R` · `moves.reset_camera`·`throw_knife` |
| Bonfire: walk to the spot (0.35 m) without warping, turn toward the bonfire and press A; warp after two failures (user: "can't even get to the bonfire precisely, it goes to the designated position") | `farm.rest` |
| Where the floor is unknown (navmesh gaps: stair tops, bridges), a lethal fall needs more than 4 m drop in 0.8 s — a "99 m below" false alarm wasted two 10 s force-quits | `watch.Escape.FREEFALL`·`floor_drop` → None |
| Force-quit takes game limit 2.5 s + reload 5.6 s — menu steps proceed immediately after screen confirmation (VERIFIED_GAP), except after START, press LEFT only once the menu text is visible (pressing after 0.02 s gets eaten, losing 1.3 s). Reload A every 0.5 s. Per-step times are in the escape event's quit_steps | `quitout.quit_out`·`reload`·`LAST_STEPS` |
| No coordinate warps across zones — terrain doesn't load, fatal fall (Undead Burg → Firelink Shrine). `set_last_bonfire` + Darksign (**check souls first** — lost 680) | `dsr_telemetry.set_last_bonfire`·`moves.darksign` |
| Game memory is read by **a single feed thread** — reading per layer (duel 4, field 17, moves 6, watch thread) overlapped reads in one tick and each layer saw a different moment. Frames within 50 ms are used as-is; if stale, wait for the next frame; beyond 40 m or dead thread, read directly. Disable with `BOT_FEED=0`. Measured with `experiments/feed_bench.py` | `feed.Feed` · `env.make_telemetry` (one per process) |

## Evidence-grade gate (2026-09-26, user) — before adding or changing a policy

Before adding or changing a movement/combat policy, classify **every number and physical claim** it uses into exactly one of the five grades below.

| Grade | Allowed scope |
|---|---|
| `human_verified` / `repeated_observer_evidence` | May justify a **narrow, map-specific** policy with its scope stated |
| `navmesh_or_data_derived` | Only for **blocking** dangerous actions — not proof that a movement/combat action is physically safe |
| `code_constant_only` | Only timeouts, retries, conservative wait limits. Not a basis for approaching, sprinting, rolling, kicking, or crossing floors |
| `unknown` | Must **never** trigger automatic movement, attack, evasion, guard, sprint, or path choice |

- For each claim, record the map, enemy NPC type, weapon/equipment, player state, and confidence.
- Raw anim numbers (3004, 3500, etc.) are **only evidence** until their meaning for that enemy is proven by video/manual calibration.
- Player collision, slope response, knockback, projectile arcs, hitbox timing, and camera collision are `unknown` until controlled observer/video experiments.

### Places where the code disagreed (2026-09-26 audit → fixed the same day)

After the fix: the 3004/3500 kicks were already `early_kick="shadow"`, log only (no change) · ranged exception removed · sprinting up to ranged enemies removed
· four `sprint` → `walk` · side roll removed (if backstep impossible, stay facing forward) · the one step at an edge walked in the direction NavMesh chose → shield + face forward.
The NavMesh path walk back to flat ground was kept — its destination (RAMP_ARENA) is human_verified and it's a walk.

(Table at audit time)

| Place | Action | Evidence grade | Rule violated |
|---|---|---|---|
| `foes.SHIELD` `windup=(3004,)`, `windup_act_s=1.2`, `kick_on_stagger` → `duel.py:152` | Kick | Raw anim number (observed 4 times, meaning uncalibrated) | 6 |
| `field._approach_guard` ranged exception (`abs(dy) < 1.2` + approach if shield soldier beyond 12 m) | Approach | dy 1.2 and 12 m are `code_constant_only` | 3 |
| `duel.py:297` `"sprint"` toward ranged enemies | Sprinting to close in | Projectile arc `unknown`, sprint safety a NavMesh estimate | 2·4·7 |
| `duel.py:134`/`:563`, `field.py:219` `walk_path(..., "sprint")` | Sprint | Paths were walk recordings; sprinting is a NavMesh estimate | 2 |
| `reflex` roll direction, `duel` footing retreat (moving in the direction `nav.footing` **chose**) | Evasion/movement | `navmesh_or_data_derived` | 2 (may only block, not choose direction) |
| `field.MOVED_WAIT_DY = 1.2` judging 'different floor' | Wait (don't approach) | `code_constant_only` | Within rule 3 — a wait limit, so allowed |

## Target liveness, deferral, hold the spot, shadow kick (Patch A–D, 2026-09-26)

Fixes from the R1–R3 (observe `101202`, `101538`, `101913`) V0-Lite results. Each patch has its own commit and offline test:

- **A Target liveness** (`field._bind`·`_liveness`, `tests/field_liveness_test.py`): don't infer death from spawn distance. Only the first resolution uses `find_at`; after that,
  runtime identity (ptr, handle, `esc.gen`). Death = raw HP 0 in the same generation on two consecutive distinct snapshots. Missing from the list = missing (not dead);
  over 5 s or a generation change → unknown → rebind at the spawn as a new life. If never found, the result shows `#i?`.
- **B No chasing after deferral** (`field.clear`·`_deferred_unreachable`, `risk_report` partial flag, `tests/field_defer_test.py`).
- **C Hold-the-spot stamina** (`field._hold_at`·`_defend_in_place`·`_zone_leash`·`LureBlock`, `tests/field_hold_test.py`): shield down when quiet,
  shield up only when something approaches (0.3 m in 0.5 s). Contact below 25 % stamina = defend in place only (stick neutral, reflex counterattack off, recover if HP below 25 %) —
  fight() is not called. Only contact inside the zone with enough stamina gets a fight bound to the initial identity (broken off on leaving the zone, identity/generation change, or a second enemy within 3 m;
  no target switching). The lure block lifts only after 0.5 s of **continuous** quiet within 5 m. The 'approaching enemy' branch still goes first.
- **E-1 Moved targets are waited for on flat ground** (user 2026-09-26, `field.clear`·`_hold_tick`, `tests/field_moved_wait_test.py`): if a non-hold target (#1, #3, etc.)
  has moved and is somewhere more than 1.2 m in height from the flat ground (arena), don't go seek it via lure/fight; wait on flat ground (same _hold_tick as
  the shield soldier hold-the-spot). If it comes down and swings, the 'approaching enemy' branch takes it. If it doesn't come down after two 20 s waits, `left #i~`. After Patch A, the bot walked up to
  #3's old spot (up the ramp) while #3 was coming down, leaving the flat ground by 6 m (observe 131752, 132053). Targets that moved at the same height, and
  ledge targets still at their spawn, are unchanged.
- **E-2/E-3 Approach safety checks** (user 2026-09-26, `duel._approach`·`duel(may_approach=)`·`field._approach_guard`, `tests/field_approach_guard_test.py`):
  E-2: while closing in, if the enemy moves more than 3 m from where the path was planned, stop and re-evaluate from its current position (don't go all the way to the old spot); if the re-evaluated
  spot is unsafe, end with `unsafe_approach`, and clear doesn't retreat but switches to waiting on flat ground. E-3: in the approaching-enemy fight, `안옴→붙기` (not coming → close in) is also not switched to
  if unsafe; it keeps waiting. Safe = a listed target still at its spawn, or one that moved but doesn't meet the E-1b wait conditions (different height, outside the flat-ground zone, within 12 m of
  the shield soldier spawn). Unlisted enemies are checked only when the player is near the flat ground (ledge fights unchanged). Evidence: 131752, 132053, 133827.
- **D Shadow kick** (`duel._early_kick_candidate`·`ShadowKick`, `foes.Foe.early_kick`, `tests/duel_shadow_test.py`).

**Known validation issue (after A–D, not fixed yet)**: the 1.5 m hold-spot tolerance conflicts with the 13 m lure minimum — the throwing spot is 13.66 m from
#2's spawn, but standing somewhere within 1.5 m of the spot can put it inside 13 m. In R3 (`101913`), `too_close` twice at 12.8 m → deferral → (old) chase.

## Where enemy AI (Lua) fits

The Lua in the game files is **a source for extracting enemy data**. We don't write Lua. Once per enemy, extract with `boss/luadump.py`/`boss/luatab.py` and
record it in `foes.py` (single/combo anims, danger distance). Lua is not read at runtime.
Currently `duel` only uses "block if it's swinging" and doesn't yet distinguish single vs. combo — that's where to hook it in next.

## Running

```bash
python run.py status          # status only, no input
python run.py quit-test       # does quit-out revive dead enemies? (user confirmed 'no' — 2026-09-26 R1 observed a full-HP #2 in a new generation, see correction above)
python run.py clear-ramp      # rest, then the 6 on the ramp
python run.py burg-bonfire    # mission: light the Undead Burg bonfire
```
Logs: `data/runs/<시각>_<명령>.log` (<time>_<command>) · `.jsonl` · `.hits.jsonl` (black box)

Tools that write game memory (warp, quit-out, invincibility, item insertion, etc.) are all in one place: `OFFLINE_TOOLS.md`.

**Judge a run by its risk verdict, not the final result** (user 2026-09-25: "the failures are hidden"):
- When a run ends, `run.py` prints one line `══ 위험 판정: 깨끗/주의/위험/사망` (risk verdict: clean/caution/danger/dead). The criteria live in one place, the `risk_report.py` docstring.
- `python risk_report.py --since <시각> [--cmd burg-loop]` (<time>) — per-run table + summary grouped by same command/style/character. Use this for group comparisons.
- Layer 0 `blackbox.py`: holds the last 8 s of feed frames; on a hit over 80 HP (or dropping below 25 %), writes all surrounding frames to `.hits.jsonl`,
  and `vital` (0.5 s HP) / `hit` (culprit estimate) events to `.jsonl`. Replay frame by frame with `python risk_report.py --hits <판>` (<run>).
  The culprit estimate is "a nearby enemy facing me with an attack anim in the preceding 1.5 s" — only an estimate; look at the frames directly.

## Validation status (2026-09-24)

- **Goal reached**: via the `burg-bonfire` flow, lit and sat at the Undead Burg bonfire — last bonfire 1022960 (Firelink Shrine) → **1012962 (Undead Burg)**.
  (Not in one go: ramp → #5 left, `clear-ramp --no-rest` → `merchant` → stuck at the spear shield soldier, code fix, then `light-burg`.)
- The ramp's 6 are cleared every run (many runs take 0 damage from the four hollows). Undead Burg hollows, the shield soldier by the chest, and the spear shield soldier killed.
- Baseline (old hunt.py, 23 ramp runs): 5,987 damage; 16 hits taken to the side/back while shielding, 1,560.
- **The respawn point is now Undead Burg** — code assuming Firelink Shrine (`missions.start_fresh`, `RAMP`, `FIRELINK` home) will be wrong if run as-is. Fix before the next mission.
- Remaining weaknesses: two or more engaging at once → **knife lure** gave 6/6 on the first run (2026-09-24, Battle Axe). Enemies that won't come down from ledges, missed kicks, and spin prevention (desperate) still have little live validation. Knife rebuying (merchant) not implemented.
- Old `hunt.py` kept for reference (`control.py`/`nav.py` changes apply there too).

## Attack combos (layer 1 `moves.COMBOS`)

User (2026-09-24): "Make attack combos a single sequence — roll light attack, jump heavy attack, backstep light attack, that kind of thing." A combo is a table of (time, action) rows, and the result is checked with a single watch.
A new combo is one row in the table; upper layers only call `mv.combo("이름", s, c, nm)` ("name"). Current rows: `backstep_r1` (B → R1 at 0.45 s, used live), `roll_r1`/`jump_r2` (values from the old control chart / estimates, not measured).

## User demo recording (2026-09-24, `experiments/demo_record.py` → `data/demo/20260924_162859.jsonl`)

- Knives: **hit only on flat ground at the same height** — from (-28.5, -49.0, 28.2) to the #2 shield soldier at 13.1 m, height diff -0.7 → 34 damage, woke it. Two thrown 7 m downward from a ledge and one thrown 6 m upward all did 0 (the hollow hit upward woke up despite 0). From the second throw on, the shield soldier blocked with its shield (1).
  - **Addendum (2026-09-26, observe recording)**: the user **used lock-on** and also hit upward — height diff +3.2 to +3.4 m at 9.6–9.8 m for 45 and 30, +5.6 m at 12.3 m for 43. On the shield soldier from flat ground, 13.65 m and 13.7 m, 34 both times. The "same height only" above is an observation of the bot's throws.
- What the backstep attack really is: the user's backstep anim is **695** (the bot's B tap is 690), followed by **304500** as the backstep attack (two-handed) — a different move from the 304040 (normal light attack) the bot produced with R1. Interval **0.95–0.97 s**, consistent 4/4, followed by a 304000/304040 light chain. Knife throw anim 7540, estus 7585–7587.
- Candidate reasons for the bot's 0/18 backstep attacks: R1 after 690 is a normal light attack and doesn't lunge. What makes 695→304500 happen (lock-on? stick? B hold length?) to be measured next.
- **Correction (2026-09-25, user): 0.95–0.97 s is not a fixed interval** — "I went in after seeing the mob's timing or opening." Each time it was a reaction to a specific opening of that enemy; the four being similar was just the same enemy with the same pattern. `reflex.dodge(attack=...)` (souls/reflex.py:120,149) has no such judgment — as long as `bs_ok` (not a shield) and the floor pass, it counterattacks unconditionally after every dodge. So the current backstep attack is not "read the opening and hit" but "always hit after dodging" — this can backfire against enemies that immediately re-attack or combo, not just shield soldiers (no such case yet; only a design risk).


## Layer design improvements (2026-09-25, user: "improve everything starting from #1 and test again")

1. **Layer 0 owns recovery**: `navmesh.on_mesh`/`nearest_walkable`/`ledge_step`; `find_path` snaps off-mesh start/end to points at the same height and returns an empty list for step-up paths. When blocked, `nav.goto` first checks whether it's off the mesh and returns to the mesh. Layer 4's temporary `reset_spot` removed. Offline check: the path from the pocket (-24.5,-48.3,26.0) → #4 starts at (-27.1,-48.8,25.5); Firelink Shrine, flat ground, all 6, and summit paths all preserved.
2. **Layer 4 engagement queue**: `field.clear` changed to "approaching enemies first; the spawn list is the intent" (`_clear_old` kept for reference).
3. **Style object**: `souls/style.py`. The `--style` string is turned into the object once at entry.
4. **Layer 1 offline test**: `tests/moves_test.py` (fake pad) — the first run caught a bug where combo-table times were absolute, making the R1 interval 0.29 s → steps after B are relative to B.
5. **Old code cleanup**: moved to `legacy/` (hunt, merchantrun, reflex, old test scripts). `souls` no longer imports `patrol` (`moves.rel_angle`). `vision_probe` kept because boss/ uses it.

## Round trip (Undead Burg bonfire → walk back, 2026-09-25)

User: "Don't rest at the Undead Burg bonfire; walk back to Firelink" — instead of `light_burg_bonfire()` (sits, changes the respawn point),
`missions.to_firelink()` (reverse of to_merchant, doesn't roll the barrel) + `missions.burg_bonfire_round_trip()` (ramp → merchant → bonfire spot → return without sitting).
CLI `python run.py burg-loop`, `experiments/loop_runs.py --mission burg-loop`.
- **Quit-out (quit+reload) is not the Darksign** — it doesn't move you; you continue right where you were (measured: quit_out+reload next to a bonfire leaves coordinates unchanged).
  Changing only the bonfire pointer via `set_last_bonfire` affects only the next **death/Darksign** — can't be used for teleporting between runs. (The old
  "quit-out between burg-bonfire runs" branch in experiments/loop_runs.py was built on this misunderstanding — dead code that can be deleted; don't use it.)
- **Missed in the legacy/ cleanup**: `import ladder_test` in `souls/field.py:fog_through()` was left as-is after the move to `legacy/` → crash during clear_ramp
  when blocked at the fog wall. `legacy/ladder_test.py`/`experiments/vision_probe.py` also bare-`import merchantrun` from each other (moved to legacy/ together) — neither is
  needed for the functions actually used (prompt_px, window_rect), so moved to lazy imports. **After moving modules to legacy/, re-check that nothing on the run path still uses them.**
- A shield soldier (npc 254013, HP150) stands near the Undead Burg bonfire (around -8,-10,-69) — 6 backstep-style light attacks did 0 damage (blocked); took 174 and died from a fall.
  Same problem as the ramp shield soldier ([[ds1-player-mechanics-tips]] "bot's backstep attacks 0/18"). This stretch retried with the guard style (user's choice, 2026-09-25).
- The Darksign (`moves.darksign`, item 117) wasn't selected even after cycling `select_item` for 15 s — apparently not in the quick-item cycle list (cause unconfirmed, look next time).
- **Next (user 2026-09-25): first see whether guard clears this round trip, later re-measure whether backstep also clears it.**
  The only known difference right now is the one shield soldier by the bonfire (254013) — backstep light attacks were blocked for 0 damage. Compare after the guard result.
- **Root cause (user 2026-09-25): 254013/254014 were not in `foes.py`, so they leaked through as "unknown enemies" (kind=other)** — escaping the shield exclusion (the "hit first" rule
  only checks `foe.kind != "shield"`), it threw 18 light attacks in a row for 0 damage and took 515. Fixed by registering them as SHIELD.
- **User principle: "Guard + light attack, kick + light attack, backstep + light attack, go behind + light attack — you have to choose by situation. If possible, a light attack from behind is the most effective."**
  Added circling behind to `duel.py` (`Foe.circle_behind`, all SHIELD): if a still shield soldier (anim -1) is within the behind angle (`CIRCLE_BEHIND_DEG`=130°),
  circle behind it instead of kick/light attack.
  - **First attempt (`_circle_step`, stopping at each step, 30° at a time) failed** — reached 157° (nearly directly behind) yet all 16 hits did 0 damage (measured by `experiments/backstab_probe.py`).
  - **Cause and fix confirmed from the user's demo** (`experiments/record_play.py`, `data/trace/play_20260925_062345.jsonl`, 4 events analyzed): a real backstab must go in along
    **one large continuous arc without stopping** (3.5–3.8 s, heading curving about 150–200°, distance 5 m → 1 m, right stick moving continuously too) —
    stopping at each step lets the enemy turn and keep up. The anim is **303000, same as a normal light attack** (no backstab-specific anim), but the damage is **54 (63 % of HP 85)**
    rather than 34–41 — the hit angle, not the anim, decides it.
  - Replaced `_circle_step` → **`_circle_sweep`**: every tick (0.05 s) re-target a point 60° ahead and circle without stopping, max `CIRCLE_SWEEP_S`=4 s,
    stop immediately if the enemy starts moving (no longer idle). Past `CIRCLE_MAX_SWEEPS` (2), give up and kick.
  - **Live result (2026-09-25, `circle_sweep_isolated.log`): bad — turned off with `SHIELD.circle_behind=False`.** An enemy just lured by knife or one cutting in during a melee
    isn't truly idle (-1); its anim changes within a few ticks, so `_circle_sweep` barely circled (`등뒤돌기:0` (circle-behind: 0), `등뒤돌기:3`) before breaking off —
    wasting those attempts (`CIRCLE_MAX_SWEEPS`) and leading to bad trades (dealt 40, took 216), taking the run all the way to death. User: "Circling is too slow;
    kick + light attack looks better." Against the isolated target by the Undead Burg bonfire (circled to 157° fine, `experiments/backstab_probe.py`) the technique itself worked, but
    live (shield soldier in a melee) the kick is better — code kept (`Foe.circle_behind`, `_circle_sweep`) but off by default.
  - **User: "It's hard because the shield soldier's pattern is good."** — not a flaw in the circling logic itself; this enemy AI (guard, turn tracking) is well designed, so
    positioning tricks don't easily break it. The kick (kick_when_idle) was already the proven standard answer for this pattern.
- **User: "When you change areas, the enemies outside come back to life."** — crossing a zone boundary (MAP_A on the Firelink Shrine side ↔ MAP_B on the Undead Burg side) respawns that zone's
  enemies. Enemies cleared on the way out may be there again on the way back — `to_firelink()` (return) must not assume "already killed, so they won't
  appear". Reflect this in round-trip design and expected combat density (not in code yet).

## Undead Burg progression order (user demo, 2026-09-25, `experiments/record_play.py` → `data/trace/play_20260925_091805.jsonl`)

The user walked it personally, demonstrating in the order "from right here you can handle 2, don't go up" / "killed 3, come into the room, next
I'll deal with the archer" / "archer dealt with, finally the two shield soldiers". There is a spot where the two terrace shield soldiers can be drawn out and fought **from
below without going up (to the terrace)**, and the order is **3-enemy stretch → inside the room → archer → the two shield soldiers last**.

**First recording analysis (autonomous pass, 2026-09-25)**: parsed `data/trace/play_20260925_091805.jsonl` (10598 lines, 17 min) to extract enemy appearance order and
player coordinates. Notably: **254013/254014 (the numbers registered as SHIELD earlier today) never appear in this recording** — the "two shield soldiers"
the user actually fought in the demo are likely different ptrs (presumably the 255000 family; around t≈294–296 s, 254010/255000×2/254011/
255002 appear all at once) — **not confirmed yet; the exact npc numbers need to be checked against the actual screen in the next live session.** The t≈316–332 s stretch
matches a trajectory walking straight to the bonfire (BURG_BONFIRE ≈ (3.2,-10,-61.2)) without combat
(y converging -13 → -10, final position (-0.9,-10.0,-60.9), 4 m in front of the bonfire) — the room (storeroom) appears to be right next to the bonfire.

**User, this session (arrived during an autonomous check) 2026-09-25: "Why do you keep running at the two shield soldiers on the terrace? If you're going to do that, just
run to the bonfire inside the castle first. Handling it from there looks better." "If you're in that room, at least the archer's arrows can't
hit you."** — strategy change: right now `to_merchant()`/`burg_bonfire_round_trip()` **fight every enemy met while walking** the Undead Burg stretch (B)
(`walk()`'s `chaser()` keeps pulling in nearby awake enemies) → in that open area it gets surrounded by the archer (254012) and shield soldiers and
repeatedly takes heavy damage (this session's round 2b death followed this pattern too). **User's direction: don't fight in that area; first rush to the bonfire/room
(where the archer's line of sight is blocked), use it as a safe base, and clear outward from there.**
- **Next (not in code yet)**: add a "pass by without fighting followers" mode to `field.walk()` (e.g. `no_chase=True` —
  even if `chaser()` finds one, don't switch to "retreat"; just keep `mode` (sprint etc.)), and apply it to the stretch from the Undead Burg entrance to the bonfire. Exactly where to
  "rush" from and to (from the Undead Burg entrance R["b"][0]? from where the archer is encountered?) must be confirmed by the user watching the screen — decide together in a live session.

**Second recording, order fixed (same session, `play_20260925_095925.jsonl`, 5.7 min)**: user: **"Record again. Code it to kill in the order
I kill them."** → **"It's not a good method, but for now it breaks the order too much, so there's no choice"** (acknowledging that hard-coding the demo order
as a script instead of generalized judgment isn't perfect but is needed at this stage).
- From the trace, the point where each enemy "was last observed and then disappeared" (= death; `s.hostile()` returns only hp>0, so a dead enemy just drops
  from the list — no HP=0 event is recorded) was taken as its death time to extract the order: **254011 → 254012 (firebomb, early) →
  254010 → 254010 (2nd) → 255002 (shield soldier) → 255000 (shield soldier, last)**. Consistent with the existing principle that the two shield soldiers come last.
- **Important correction**: we previously guessed "the two terrace shield soldiers = 254013/254014" and registered both as SHIELD, but in these two
  recordings (091805, 095925) 254013/254014 never appear. The two shield soldiers the user actually fought are **255000 and
  255002** (already registered as SHIELD, correct by coincidence) — registering 254013/254014 probably wasn't wrong in itself, but they're likely not "those two on the
  terrace". Needs confirmation.
- **Bonfire room safety check (measured)**: after entering roughly the region x∈[-8,+3], y≈-10.0, z∈[-58,-69] (near the bonfire (3.2,-10,-61.2)),
  **0 damage for over 7.5 s even while fighting** — "if you're in that room, at least the archer's arrows can't hit you" is confirmed by data too.
  Before reaching this area (the open courtyard), only one melee hit of 97 from 254011; across the whole recording,
  0 archer (254012) arrow hits recorded — meaning the user fully avoided the arrows.
- **Coded**: `data/burg-town-map.json` (6 enemies, npc + last observed coords, in order) + `BURG_TOWN`/`Missions.clear_burg_town()` in `missions.py`
  + a new `run.py` command `clear-burg-town` (standalone/testing).

**First measurement (2026-09-25, right after wiring into `to_merchant()`, burg-loop 101100; user: "you're at Firelink Shrine, so try from the
beginning. Be sure to keep the order.")**: the first version, reusing `field.clear()` as-is, **succeeded on #1–3 (254011, 254012, 254010, close)**
but **#4–6 (254010 2nd, 255002, 255000 — near the bonfire room, far and behind walls) all repeated "stuck" 4 times each**,
wasting 110 s+ in place, then `left #4 #5 #6` → right after (7 s later) **the character died**. Cause: when finding the next target, `field.clear()`
only uses `duel()`'s local approach (`_approach`, no real pathfinding); unlike the ramp (6 enemies gathered on one flat area), in Undead Burg the
targets are much farther and behind walls/structures, so the local approach couldn't reach them.
- **Fix**: rewrote `clear_burg_town()` so that, instead of `field.clear()`, for each target it first **walks to that spot with `walk_to()` (real navmesh pathfinding)**
  (awake enemies on the way are handled by `walk()`'s chaser — sometimes the target itself is killed on the way)
  and, on arrival, **`fight()`s it if alive**. **Not yet re-verified live with this new version** — check next time.

## Ranged first, getting surrounded (2026-09-25, `duel.py`)

- **Ranged first**: if a thrower (foes.ranged) is throwing, switch the target to it regardless of distance/height (`RANGED_SWITCH_R`=25 m) — the existing
  `cut` (interloper) only looked at 2.5 m and the same height, so a thrower on a ledge above was never caught (user: "the one shooting arrows from above is attacking, so it's set to
  defense mode — deal with that one first").
- **When approaching a ranged target, sprint only when the surroundings are quiet.** The first version always used `sprint` (can't raise shield) if `foe.ranged`, but mid-melee
  it got hit defenseless while running and didn't notice other enemies until they entered `SWITCH_R` (2.5 m), getting surrounded (user 2026-09-25: "trying to catch the shooter,
  your response was slow and other mobs surrounded you", "you completely fell for the mob placement tactic" — an intentional enemy-placement trap). If another awake enemy is within 8 m (`OTHERS_ATTACK_R`),
  approach with `guard` (walking with shield up) instead of `sprint` — the fast but defenseless rush only when truly alone.
- **A hollow combo's 3009 must not be blocked either** — only SHIELD had `unblockable=(3009,)`, but in a measurement (254001, firebomb hollow) blocking 3009 for over 4 s
  (reflex ×29 in a row, 0 damage dealt) drained stamina 46 → 6 and it died. The hollow combo comment (`_HOLLOW`) already said "3003→3004→3009",
  but it wasn't in the `unblockable` field — added to `_HOLLOW` and all Undead Burg hollows (250000). **Not yet re-verified live.**
- **Next (user 2026-09-25, from the next batch — rules don't change mid-run): "Two-hand it, and if you can't kill the interfering mob in one hit, it's better
  to run."** Interlopers (cut) are currently always fought to the end (`fight()`) — it can drag on, as in the case of 21 s and 428 damage taken until death.
  Add a condition: if it doesn't die in one hit (or a set number of attempts), stop holding on and back off to the original target / escape route. Review together with two-handing (grip).
    positioning tricks don't easily break it. The kick (kick_when_idle) was already the proven standard answer for this pattern.
- **During the round trip, "if there are mobs on the way back too, clear them all" (user)** — `field.walk()` already tries to fight followers (label `따라온 …` (followed …)),
  but in the corridor (return) stretch that fight only repeated `_approach()`'s `step` (no-path fallback), letting two 45 s windows pass and becoming `stuck` —
  it seems no path is found to a still enemy (anim -1, not attacking). Cause (navmesh connectivity?) unconfirmed — if it reproduces in the next batch, start with that spot's coordinates.

## Character progression (user principle, 2026-09-25)

"Leveling up, choosing/upgrading weapons, and allocating stats well matters — the current build only raises vitality, endurance, and strength." Changes results more than bot rules do.
- Versus Knight starting stats: VIT +6, END +8, STR +5 (SL 24) — other stats unchanged from start (basis for confirming dump labels). Weapon Battle Axe +0, Wolf Ring (poise).
- Each run leaves a `char` event (stats, equipment) (`run.py`). **Compare groups only within the same char state.**
- The "progression layer" above layer 5 (leveling, restocking, upgrading) is still done by the user. To automate: if souls ≥ next level cost, cycle VIT→END→STR at the bonfire; if knives < 20, merchant; if titanite, Andre.

## rush style (2026-09-25, `souls/style.py`)

Two-handed, reflex (block/evade) off — keep attacking, survive on estus. **User: "Rush mode is plan B for when other methods don't work, not something to use as
the main one."** guard is the default, rush the alternative — what's recorded here are bugs fixed before turning it off; further polishing of rush is low priority.
- Switching to two-hand sometimes didn't take on the first try → `fight()` retries until confirmed (commit above).
- Even without `style.shield` it took the "block while it's swinging" branch and got beaten for the opponent's whole combo (8 s+) with 0 attacks (shield soldier, 676 damage) → added
  a `style.shield` gate to that branch (commit above). After the fix, the same shield soldier went 21 s → 6 s.
- **Not fixed yet (measured 2026-09-25, 20260925_074542_clear-ramp.log)**: near ramp #6, against an opponent with 4 m height difference, `붙기:stopped` (close in: stopped)
  repeated for over 8 s (0 attacks), took 624 and died — `_approach()`'s `stop()` keeps returning true, and `field.fight()` apparently fails to catch that new
  interloper (cause unconfirmed). A different bug from the shield soldier issue.

## Height limit on ranged switching (2026-09-25, `duel.py`)

`RANGED_SWITCH_R` (ranged first, getting surrounded) had a distance limit but no height limit — when the target switched to 254012 (archer on the terrace, height diff +6 to +8.5 m),
`_approach()` endlessly tried to close a distance it couldn't walk, taking arrows for 20–30 s (burg-loop 091110, HP 695 → 137;
forced retreat via `low_hp`, but even that failed with `no_path`). Measured (several logs): every successful ranged switch that closed in had height diff ≤ +3.0 m —
added `RANGED_REACHABLE_DY = 4.0` so anything above that is treated as unreachable and ignored.

## When to wait / when to act (2026-09-25, `duel.py` `wait_far`)

**User: "It would have come if you'd waited, why did you rush up and blow the chance", "Your sense of when to wait and when to act is really bad."** — kept as a
bot-wide judgment problem, not just this one bug (add here if similar patterns appear elsewhere).

- Measured (burg-loop 093619, ramp): during a knife lure another awake enemy approached to 5.9 m → `field.clear()`'s "approaching enemy" branch
  walked straight in with `fight()` → meanwhile the first enemy also arrived, two at once → 0 attacks in 8 s, 493 damage, finally
  a forced quit-out for "surrounded by 2" (HP 793 → 164). Had it waited in place instead of walking, they would have come one at a time.
- Fix: `duel(..., wait_far=True)` — if out of reach, don't approach via `_approach()`; block and wait in place, reacting only once the opponent
  comes into reach on its own. Applied to `field.clear()`'s "approaching enemy" (interloper) engagement (the `fight()`
  call site in `field.py`). Not applied to normal engagements seeking out a fixed spawn target — those genuinely need to approach, a different situation.
- If the opponent doesn't come within 15 s (`STALEMATE_S`), it just exits as "stalemate" — doesn't wait forever.

**Live regression (2026-09-25, burg-loop 094803, character died)**: `wait_far` itself created a new risk. While fighting 255000 (shield soldier) in Undead Burg,
the tracked target stayed 4.3–4.5 m away, **not swinging (anim -1) and not approaching** — yet during 11 s of just "waiting",
HP dropped 490 → 242 (another cause, apparently being hit by an untracked enemy — neither cut nor ranged_cut caught it). This loss led straight
to `low_hp` (below 25 %) → `no_path`, couldn't retreat → `desperate` (to the end) re-engagement → force-quit for surrounded by 2 (HP 118 → 3, barely survived) →
the very next re-engagement ended in **`me_dead` (actual death)**. **User: "The enemies lull you and pile on the danger.
This game is never easy. Everything is designed." "You stack up risk and end up dying." "The failures are hidden."** — looking only at the final result
string (`cleared`/`dead`) shows none of the large HP losses or near-death history along the way.
- Fix: `WAIT_HURT_HP = 120.0` — losing this much (about 15 %) while waiting means it's being hit from elsewhere, not "safely waiting",
  so it exits to `low_hp` immediately. Cuts off much earlier than the existing global 25 % threshold (which allowed ~300+ HP loss).
- **Not fixed yet**: what exactly hit it during those 11 s (tracked target also anim -1; cut, ranged_cut, and reflex all didn't react) is
  unconfirmed — the log is a 1 Hz summary, so not visible at frame level. `WAIT_HURT_HP` mitigates the symptom (exits fast), not a root-cause
  fix. If it recurs, next time look more densely with real-time telemetry at which enemy and which anim.
- **Lesson on evaluation**: don't count a run as "success" from its final result ("cleared" etc.) alone — for every run, scan the whole log for
  `⚠` (force-quit), `low_hp`, `timeout`, `stuck`, `me_dead` to see the real risk (user: "the failures are hidden").

## BIOS layer (watchdog) — on hold (2026-09-25)

`watchdog.py` is a monitoring layer in a separate process from `run.py` (the main body) that rescues the character via Darksign/quit-out if it's stuck (position/anim unchanged for `STALL_S`).
Redesigned three times (all detailed in `watchdog.py`'s own docstring):
1. Timestamp heartbeat file — discarded due to false positives from read contention.
2. `botlock.py` (OS file lock, fencing) + danger judged by HP/nearby threats — failed two ways: misjudged normal waiting between runs as an emergency (repeated Darksign) / conversely
   saw it once, judged it safe, moved on, and then kept getting hit until death ("it stops and just gets beaten").
3. **Final**: "if stopped for 3 s or more" (specified directly by the user) — on the principle that judging game danger is the combat AI's job, not the watchdog's
   ("then it's not a watchdog"), it only checks whether the character is stopped.

**User 2026-09-25: "Let's give up on the watchdog. It's too unstable; I'll evaluate it later, just leave the docs."** — the final design was also unstable live
(signs of false positives/misses, cause undetermined). The code stays but **from now on it is not turned on** — sets run with `run.py` alone,
relying on its own quit-out on bot errors (`esc.fire`, the `except` block in `run.py`). Re-evaluating the watchdog is a later task.
