# sim — Godot practice room (MoKa M1109-47/50/51)

- `godot/` — Godot 4.7.2 project. Godot itself: `D:/dev/tools/godot` (override with `GODOT_PATH`).
- `godot_link.py` — bot side: room state → `telemetry.Snapshot` (UDP 47811), UDP pad input (47812).
- `build_actions.py` — `godot/actions.json` from the DSR player TAE (`player_tae_extract.py` → `data/gamefiles/tae_c0000.json`).
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
- Flat arena (MoKa M1109-75/76/78): `python sim/arena_scene.py [--set hollows|mixed]` → `godot/assets/arena_scene.json` (40 m flat square,
  two heavy Hollows 255010 by default, `mixed` = heavy Hollow + heavy knight 257002, arena AI switches); hits show a red ball on the
  nearest bone for 0.8 s (`ramp.gd` `_hit_mark`, state `hit_marks`); open with `-- --scene=arena`, bot with
  `BOT_GAME=sim python run.py arena --no-quit --no-loot --no-firebomb`. Arena only: a blocked hit costs
  StaminaAttackPower × (1 − shield GuardStaminaDefense / 100) and lets 100 − PhysicalGuardPercentage % through; the
  player's damage on a foe is a² / (a + NpcParam PhysicalDefense) — values [game], formulas [guess].
- Tests: `python tests/godot_room_test.py`, `python tests/godot_combat_test.py`, `python tests/godot_ramp_test.py`, `python tests/replay_test.py`, `python tests/chr_glb_test.py`
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
