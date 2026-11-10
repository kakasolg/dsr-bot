# sim — Godot practice room (MoKa M1109-47/50/51)

- `godot/` — Godot 4.7.2 project. Godot itself: `D:/dev/tools/godot` (override with `GODOT_PATH`).
- `godot_link.py` — bot side: room state → `telemetry.Snapshot` (UDP 47811), UDP pad input (47812).
- `build_actions.py` — `godot/actions.json` from the DSR player TAE (`player_tae_extract.py` → `data/gamefiles/tae_c0000.json`).
- `flver_glb.py` — DSR weapon / shield models (`parts/WP_A_xxxx.partsbnd.dcx`) → `godot/assets/*.glb` + Godot import;
  dummy points → `data/gamefiles/weapon_models.json`. Then `build_actions.py` (equipment rows, AtkParam_Pc hitboxes).
- Scene replay (MoKa M1109-55/56): `python sim/replay_view.py [<run>] [--at <s>]` opens `godot/replay.tscn` on
  `data/replays/<run>.json` (`replay_extract.py`: radar recording + run events, made on first use). Maps:
  `python sim/flver_glb.py --map m10_01_00_00` and `--map m10_02_00_00` (local only). Keys at the top of `godot/replay.gd`.
  DSR is left-handed: the replay and the converted maps use Godot x = −DSR x (the practice room `main.gd` does not yet,
  so it is drawn mirrored).
- Real foe models (MoKa M1109-57): `python sim/chr_glb.py c2540` → `godot/assets/c2540.glb` (FLVER skin + every
  anibnd animation; Havok decoded by DSAnimStudio's SoulsAssetPipeline through `hkx_dump.ps1`, needs `D:/tools/dsas`)
  and `data/gamefiles/chr_models.json` (bone check, animation lengths, NpcParam display masks). The replay then draws
  every NPC row of that model with its own model and plays the recorded animation id; ids the game blends on top of
  (c2540 2255 → 2250 still pose, −1) get a walk / run / stand clip by recorded speed [guess]. `godot/chr_probe.tscn`
  renders clip sheets (`--clips= --steps= --view=front`) or dumps bone positions (`--bones=`).
- Tests: `python tests/godot_room_test.py`, `python tests/godot_combat_test.py`, `python tests/replay_test.py`, `python tests/chr_glb_test.py`
  (headless; skipped without Godot / data).

## Character assets (not in git)
`godot/assets/UAL1_Standard.glb`, `godot/assets/UAL2_Standard.glb` — Quaternius *Universal Animation Library* 1 and 2,
Standard (free), CC0. Downloaded 2026-11-09 from quaternius.itch.io (`universal-animation-library`, 15 MB;
`universal-animation-library-2`, 17 MB); the zips sit in `D:/dev/tools/assets/quaternius`. Copy the non-root-motion
`Unreal-Godot/*_Standard.glb` files here. Without them the room falls back to a capsule.

Weapon / shield: `python sim/flver_glb.py` converts them from the local DSR install (MoKa M1109-54, local only — the
`.glb` / `.png` are gitignored; the repo is public). Without them the room uses the old [guess] weapon segment.

What comes from where (tags in `godot/main.gd`): **[game]** DSR game files · **[meas]** measured in DSR ·
**[guess]** made up for the room. The clips' look is Quaternius, not DSR; the action timings (length, invincible,
no-turn, attack window, cancel times) are DSR's.
