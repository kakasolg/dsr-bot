# sim — Godot practice room (MoKa M1109-47/50/51)

- `godot/` — Godot 4.7.2 project. Godot itself: `D:/dev/tools/godot` (override with `GODOT_PATH`).
- `godot_link.py` — bot side: room state → `telemetry.Snapshot` (UDP 47811), UDP pad input (47812).
- `build_actions.py` — `godot/actions.json` from the DSR player TAE (`player_tae_extract.py` → `data/gamefiles/tae_c0000.json`).
- Test: `python tests/godot_room_test.py` (headless; skipped without Godot).

## Character assets (not in git)
`godot/assets/UAL1_Standard.glb`, `godot/assets/UAL2_Standard.glb` — Quaternius *Universal Animation Library* 1 and 2,
Standard (free), CC0. Downloaded 2026-11-09 from quaternius.itch.io (`universal-animation-library`, 15 MB;
`universal-animation-library-2`, 17 MB); the zips sit in `D:/dev/tools/assets/quaternius`. Copy the non-root-motion
`Unreal-Godot/*_Standard.glb` files here. Without them the room falls back to a capsule.

What comes from where (tags in `godot/main.gd`): **[game]** DSR game files · **[meas]** measured in DSR ·
**[guess]** made up for the room. The clips' look is Quaternius, not DSR; the action timings (length, invincible,
no-turn, attack window, cancel times) are DSR's.
