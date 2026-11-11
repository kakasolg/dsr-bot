# sim — Godot practice room (MoKa M1109-47/50/51)

- `godot/` — Godot 4.7.2 project. Godot itself: `D:/dev/tools/godot` (override with `GODOT_PATH`).
- `godot_link.py` — bot side: room state → `telemetry.Snapshot` (UDP 47811), UDP pad input (47812).
- `build_actions.py` — `godot/actions.json` from the DSR player TAE (`player_tae_extract.py` → `data/gamefiles/tae_c0000.json`).
  `--weapon <EquipParamWeapon row>` (default Claymore 301000, MoKa 11-10): the light attacks are that weapon's attack-animation
  category (x3000 / x3001) — every weapon of one category has the same TAE times whatever its weight or length
  (`weapon_report.py` sheet 무기_묶음) — and the cancels are the game-measured ones of that category (`MEASURED`, one or two weapons
  measured per category), or TAE − 0.1 s [guess] for a category nobody measured. The room loads `assets/<equip.right.model>.glb`
  (`python sim/flver_glb.py WP_A_xxxx`, local; all 24 weapon-table models converted 11-10), and `godot_link` reports that row.
- `flver_glb.py` — DSR weapon / shield models (`parts/WP_A_xxxx.partsbnd.dcx`) → `godot/assets/*.glb` + Godot import;
  dummy points → `data/gamefiles/weapon_models.json`. Then `build_actions.py` (equipment rows, AtkParam_Pc hitboxes).
- Scene replay (MoKa M1109-55/56): `python sim/replay_view.py [<run>] [--at <s>]` opens `godot/replay.tscn` on
  `data/replays/<run>.json` (`replay_extract.py`: radar recording + run events, made on first use). Maps:
  `python sim/flver_glb.py --map m10_01_00_00` and `--map m10_02_00_00` (local only). Keys at the top of `godot/replay.gd`.
  DSR is left-handed: the replay and the converted maps use Godot x = −DSR x (the practice room `main.gd` keeps DSR numbers
  and shows its camera picture flipped left-right instead — `MIRROR`, M1109-67; camera FOV 43° from LockCamParam).
- Real foe models (MoKa M1109-57): `python sim/chr_glb.py c2540` → `godot/assets/c2540.glb` (FLVER skin + every
  anibnd animation; Havok decoded by DSAnimStudio's SoulsAssetPipeline through `hkx_dump.ps1`, needs `D:/tools/dsas`)
  and `data/gamefiles/chr_models.json` (bone check, animation lengths, NpcParam display masks). The replay then draws
  every NPC row of that model with its own model and plays the recorded animation id; ids the game blends on top of
  (c2540 2255 → 2250 still pose, −1) get a walk / run / stand clip by recorded speed [guess]. `godot/chr_probe.tscn`
  renders clip sheets (`--clips= --steps= --view=front`) or dumps bone positions (`--bones=`).
- Hitboxes (MoKa M1109-59): the replay draws each foe's AtkParam_Npc hit capsules (orange, FLVER model points, only
  inside the TAE type-1 window) and the model's ragdoll capsules (cyan, H toggles) — those are [candidate] body
  capsules: read from `<model>.hkx` by `sim/hkx_ragdoll.py` under `HAVOK_PYTHON` (a separate venv with
  `soulstruct-havok==1.2.2`, default `D:/dev/tools/havok-venv`; without it no body capsules). Whether DS1 tests hits
  against them is not known. `python sim/replay_hits.py [<run>]` compares the recorded big hits with the attackers'
  capsules (`data/replays/<run>.hits_check.json`; the bot's body is a [guess] vertical axis).
- Ramp room (MoKa M1109-65): `python sim/ramp_scene.py` → `godot/assets/ramp_scene.json` (Firelink NavMesh as floor,
  walls on its open edges pushed out 0.4 m, the six ramp placements with NpcParam / think / AtkParam windows, the 11-09
  observations as [meas] values, the bot's NavMesh graph for foe path finding — M1109-66; a foe stands while floor is within 0.3 m of its centre), `godot/ramp.tscn` (`ramp.gd` on top of `main.gd`: foes with wake / approach /
  attack / guard / firebomb, player guard, stamina, Estus heal). The bot plays it with `BOT_GAME=sim`: `env.make_telemetry`
  gives `godot_link.RoomTelemetry` (also records the room to `data/runs/<time>_room.jsonl`) and `run.py` makes
  `godot_link.room_pad()` (control.Pad's code, the ViGEm device swapped for UDP). Start the room first, then e.g.
  `BOT_GAME=sim python run.py clear-ramp --no-rest --no-lure --no-quit --no-loot --no-recover --no-firebomb`;
  `python foe_view.py --room data/runs/<time>_room.jsonl` gives the same foe-side table as the real runs.
- Sketchfab "Dark Souls Map" (9S, CC BY-NC, made from the game's collision; local only in `D:/dev/tools/assets/sketchfab_ds_map`,
  MoKa M1111-19..21): inside each area node the model's local (a, b, c) = DSR (z, y, x), offset 0 (checked against the NavMesh).
  `godot/sk_view.tscn` shows it with a walked path (`-- --path=<json> --shot=<png>`). Ramp room: `RAMP_SK_COLLISION=1` puts its
  Firelink area in as the player's walls instead of the NavMesh-edge walls — walls only (floors and risers under 0.5 m dropped:
  with every face the player stuck on 0.2 m step boards at the ramp's foot). `godot_ramp_test.py` passes with and without it (11-11).
  Look (M1111-23/24): by default, when the Sketchfab file is there, no DSR map on screen — the Sketchfab terrain shape drawn with
  `godot/natural_ground.gdshader` (Godot noise only, no image files: steep = rock, flat = grass / moss / dirt); `RAMP_LOOK=dsr` brings
  the DSR map back (and then the SK walls show blue). Look only, no collision change.
  Burg (M1111-27): `python sim/burg_scene.py` → `assets/burg_scene.json` (m10_01 NavMesh, Sketchfab "Undead Burg" walls, no foes, route
  bonfire → burg-upper safe spots → Taurus fog → bridge); `python sim/burg_walk.py [--headless] [--hold 20]` walks it with Moves.walk_path.
  SK walls drop faces under 0.5 m tall and faces standing on NavMesh floor (a 2 m box at the barrel stairs crossed the NavMesh path).
  Stairs (M1111-29): sun shadows; faces on sloped NavMesh are marked stairs (`_stair_mask`, vertex colour) and drawn as stone with a
  step every 0.22 m of height — most route stairs are slabs in the Sketchfab data, so the steps are painted. `RAMP_LOOK=grey` and
  `-- --shots=<views.json>` (fixed cameras → contact sheet) for checking shapes.
  Ladders (M1111-30): scene `ladders` (Taurus ladder, Burg bonfire ladder; position, facing, floor heights from game tracks). Wooden
  rails + rungs, and a DSR-like climb in `ramp.gd` (`_ladder_*`): A at the bottom facing it (7010) or at the top edge facing it (7020),
  stick up/down one 0.62 m step per 0.5 s (7011/7012, 7021/7022), auto step-off at the top (7013) and bottom (7023), B held going
  down = slide (guess). No gravity, no attacks while on it; the body pose is the UAL `ClimbUp_1m` clip as a stand-in.
  `burg_walk.py --ladders` climbs each ladder up and back down the way the bot does (face, A, stick).
  Firelink → Taurus (M1111-31): `python sim/burg_scene.py --full` → `assets/firelink_taurus_scene.json` (both NavMesh sheets
  m10_02 + m10_01 merged, Sketchfab areas `"Firelink Shrine|Undead Burg"`, scene `legs` = the bot's own route: ramp top, passage,
  Burg, storeroom, merchant, Burg bonfire, burg-upper safe spots, fog, bridge); `python sim/burg_walk.py --scene firelink_taurus`.
  Burg scenes stand only on NavMesh triangles the bot's path graph uses (no Disable / Degenerate / Wall 8 / Hole 2048 — `_floor`).
  Taurus → Titanite Demon (M1111-32): `python sim/burg_scene.py --demon` → `assets/firelink_demon_scene.json` = the Firelink → Taurus
  legs + bridge → altar (the bot's burg-altar route), altar → Andre's bonfire (NavMesh path — no recording exists), Andre → demon
  (MoKa's walk, `data/routes/andre-demon-20261111.json`; NavMesh has no path there, so scene `floor_patch` strips fill the gaps).
  `burg_walk.py --from N` starts at leg N.
  Demon → Firelink by the parish elevator (M1111-35): `python sim/burg_scene.py --loop` → `assets/firelink_loop_scene.json` =
  the firelink_demon legs + demon → Andre (MoKa's walk backwards), Andre → the elevator doors (NavMesh), `board` (stick straight
  into the car — the car is off the NavMesh and the bot's path follow stepped back onto the mesh), `ride`, out, Firelink bonfire.
  Scene `elevators`: car spot, top / bottom height, acceleration and top speed from the 11-11 game walk (M1111-18) [meas];
  wait 1 s, braking and car size [guess]. The car is floor where it is (`_ground`) and carries a body standing on it; it goes
  down once. Scene `sk_cut` drops the Sketchfab faces that model the car / door at the top as fixed walls.
  `burg_walk.py --scene firelink_loop --from 24` starts at the demon; `tests/godot_elevator_test.py`.
  Viewer camera (M1111-34): the window shows `view_cam` (`godot/cam_director.gd`): hands-off follow toward the planned route
  5 m ahead, section profiles corridor / stairs / bridge (scene `cam_path`, ~1 m points with a tag — legs by name, stairs by
  slope; `burg_scene.py` builds it), a side shot on ladders, enter 0.25 s / hold 1.5 s, sphere check against walls. The play
  camera (`cam`, `cam_yaw`) still moves as before and is what the bot steers by — only not drawn. F2 or `-- --cam=play` shows it;
  `-- --view-snaps=<dir>,<s>` saves the window every s seconds. Numbers are guesses. `burg_walk.py` prints section changes and
  passes `--room-arg=…` on. `python tests/godot_viewcam_test.py` checks the director's rules on made-up routes (not the picture).
- Flat arena (MoKa M1109-75/76/78): `python sim/arena_scene.py [--set hollows|mixed]` → `godot/assets/arena_scene.json` (40 m flat square,
  two heavy Hollows 255010 by default, `mixed` = heavy Hollow + heavy knight 257002, arena AI switches); hits show a red ball on the
  nearest bone for 0.8 s (`ramp.gd` `_hit_mark`, state `hit_marks`); open with `-- --scene=arena`, bot with
  `BOT_GAME=sim python run.py arena --no-quit --no-loot --no-firebomb`. Arena only: a blocked hit costs
  StaminaAttackPower × (1 − shield GuardStaminaDefense / 100) and lets 100 − PhysicalGuardPercentage % through; the
  player's damage on a foe is a² / (a + NpcParam PhysicalDefense) — values [game], formulas [guess]. Turns (MoKa 11-10,
  scene `turns`): one foe attacks at a time, the other waits 4.5 m off behind its shield; a hit attacker backs off (701) and
  hands the turn over; an Estus sip still brings both [guess]. The heavy Hollow's shield is 9910 and deliberately more
  defensive than the game (seen 7 % of bot swings blocked, biased sample) — state `guard_blocks` / `player_hits` = block rate.
- Player stamina (MoKa M1111-03/05/07, `ramp.gd`, measured at the Titanite Demon 11-11): an attack costs the weapon's
  BehaviorParam StaminaCost (`actions.json` hit.stamina; Claymore 1H R1 30) taken at the blade window, any stamina > 0 lets
  an action start and go below 0, roll 30 · backstep 20, regen 45 per s while no action runs, max 98 (END 14) —
  `-- --max-sp=160` (END 40) or scene `player_max_sp`; END → max stamina table in `docs/weapons/weapon_frames_LS_CL_ZW.pdf` 8-7.
  Heavy armour (load > 50 %) not measured. `python tests/godot_stamina_test.py`.
- A fresh clone has no Godot import cache (`godot/.godot`, not in git): `godot_link.ensure_imported()` runs `--import` once before
  the room / replay starts (P-156). Linux: set `GODOT_PATH` to the Godot 4.7.2 binary.
- Without the game folder (cloud): `run.py` in the room reads the NavMesh from `data/samples/navmesh_<map>.npz` (room only,
  logged), so the two commands above run from a fresh clone on the committed scene JSONs (ramp; arena = two heavy Hollows).
  `ramp_scene.py` / `arena_scene.py` themselves need the game files — `--set mixed` cannot be made there.
- Tests: `python tests/godot_room_test.py`, `python tests/godot_combat_test.py`, `python tests/godot_ramp_test.py`, `python tests/godot_stamina_test.py`, `python tests/replay_test.py`, `python tests/chr_glb_test.py`
  (headless; skipped without Godot / data).

## Character and weapon assets
CC0, **in git** (MoKa M1110-10, so a fresh clone / cloud session has a full room):
- `godot/assets/UAL1_Standard.glb`, `UAL2_Standard.glb` — Quaternius *Universal Animation Library* 1 and 2, Standard
  (free), CC0. Downloaded 2026-11-09 from quaternius.itch.io; the zips sit in `D:/dev/tools/assets/quaternius`
  (non-root-motion `Unreal-Godot/*_Standard.glb`). The player's body and, without the DSR foe models, the foes' body.
- `godot/assets/cc0/*.fbx` — Quaternius *Medieval Weapons* (CC0, `cc0/License.txt`), downloaded 2026-11-10 from the
  Google Drive folder linked on quaternius.com/packs/medievalweapons.html (all files in
  `D:/dev/tools/assets/quaternius/medieval_weapons`). Claymore + Shield_Round for the player, Sword / Spear for the foes.

DSR-derived, **local only** (the repo is public): weapon / shield models (`python sim/flver_glb.py`), foe models
(`sim/chr_glb.py`), maps. When they are there the room uses them; when they are missing it uses the CC0 stand-ins:
- player: the weapon node stays where the DSR model would sit, so the hit capsules (DSR dummy points, AtkParam_Pc radius)
  are the same; the CC0 Claymore inside it is only the look, scaled so its tip is DSR's tip dummy (1.28 m).
- foes: UAL body; hit capsules = AtkParam_Npc radius from hand_r out to the DSR dummy distance along the weapon
  (c2540 0.56 / 0.64 m), laid along the stand-in blade; timings = TAE windows and DSR clip lengths. The swing path is the
  UAL sword clip time-warped to the TAE window [stand-in].
Checked 11-10 headless with only the CC0 files present: godot_room · combat · ramp tests pass (the ramp guard check needs
a foe melee hit — it failed with no models at all, because foe capsules came from the DSR skeleton).

What comes from where (tags in `godot/main.gd`): **[game]** DSR game files · **[meas]** measured in DSR ·
**[guess]** made up for the room. The clips' look is Quaternius, not DSR; the action timings (length, invincible,
no-turn, attack window, cancel times) are DSR's.
