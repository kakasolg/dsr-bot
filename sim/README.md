# sim — Godot practice room (MoKa M1109-47/50/51)

- `godot/` — Godot 4.7.2 project. Godot itself: `D:/dev/tools/godot` (override with `GODOT_PATH`).
- `godot_link.py` — bot side: room state → `telemetry.Snapshot` (UDP 47811), UDP pad input (47812).
- `build_actions.py` — `godot/actions.json` from the DSR player TAE (`player_tae_extract.py` → `data/gamefiles/tae_c0000.json`).
- `flver_glb.py` — DSR weapon / shield models (`parts/WP_A_xxxx.partsbnd.dcx`) → `godot/assets/*.glb` + Godot import;
  dummy points → `data/gamefiles/weapon_models.json`. Then `build_actions.py` (equipment rows, AtkParam_Pc hitboxes).
- Tests: `python tests/godot_room_test.py`, `python tests/godot_combat_test.py` (headless; skipped without Godot).

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
