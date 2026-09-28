# Observation Recorder (Phase 1) — `observe_record.py`

Translated from Korean (2026-09).

While a human plays, it **only reads** game memory, the controller, and F9, and writes them to a single file.
This is an observability experiment unrelated to combat policy, learning, or navigation (user, 2026-09-26).
Viewer v0 (Phase 2, `observe_view.html` — see the "Viewer" section below) also exists. Notes (Phase 3), video sync, slot assignment, and semantic labels do not exist yet.

```
python observe_record.py                 # data/observe/<YYYYmmdd_HHMMSS>.jsonl, stop with Ctrl+C
python observe_record.py --minutes 1.5   # stops by itself after 90 s
python observe_record.py --radius 20
python tests/observe_record_test.py            # offline test (no game, no pad)
```

On exit it prints a summary: world line count, pad line count, marker count, enemy read failures, lock-on not found, read_ms p50/p95, file path.
The same summary is also in the file's last line (`sys:end`).

## Limitations — read first

- **`observe_record.py` is an independent read-only telemetry reader that runs separately from the bot.** It duplicates the two AOBs
  (`WorldChrBase`, `ChrFollowCam`) and two vtable constants from `dsr_telemetry.py`. Therefore **do not assume values in this recording
  match the bot telemetry (`DSRTelemetry.snapshot`·`feed`) output** — read timing, radius, and filtering rules differ, and if only one
  side's constants change, they will diverge.
- **`team_bot` and `bot_phantom` are diagnostic judgments, not raw game facts.** Neither is used to filter characters out of the raw
  observation — anything within the radius (or the lock-on target) is recorded regardless of these values.
- **`alive_derived` is derived solely from `hp_raw > 0`.** It is not a raw game death flag.
- **F9 is polled globally.** Markers are created even when the DSR window lacks focus (F9 pressed in another window). Markers may
  contain accidental noise.

- **World snapshots are 10 Hz. They are for context and trajectories, not frame-level animation semantics.**
  The game runs at 60 fps, so 6 frames pass between lines. Short animations (tens of ms) may be missed entirely,
  and the start time of a captured animation ID can be up to 100 ms (+ read_ms) late.
- The pad is polled at 120 Hz and written **only on change**. Which frame the game received that input on is unknown.
- **With Steam Input enabled, the pad recording may differ from the input the game received — disable Steam Input for DSR before recording.**
  The recorder reads XInput, and Steam Input can intercept or alter input in between. In the first smoke recordings on 2026-09-26 (`075757`, `080150`),
  3 RB attacks (anim 303000) did not appear in any pad line — Steam Input state was not checked at that time. After disabling it (`081905`), all 3 RB
  presses were logged as `btn=512` just before the attack animation. Pad input while focus is outside the game window (terminal, etc.) is not verified.
- `alive_rule: "hp_gt_zero"` is the name of the derivation rule. The raw death flag is still unknown.
- `team_bot` is not a raw team number. The team field has not been found in DS1 yet; it is a classification by `dsr_telemetry.read_chr` from
  vtable·FRIENDLY·flags1. The underlying raw values are kept separately as `flags1_raw`·`vt`.
- `bot_phantom` is a **diagnostic value** following the "no body" rule of `dsr_telemetry.snapshot` (header `bot_phantom_rule`). It does not exclude enemies.
- Animation IDs are kept only as evidence. No judgments like attacking / recovery / opening are made.

## Read-only guarantees

- Opens the game process with only `PROCESS_VM_READ | PROCESS_QUERY_INFORMATION`. The handle has no write rights, so even an accidental write is rejected by the OS.
  `SeDebugPrivilege` is not enabled either (`DSRTelemetry.__init__` is not called because it uses `PROCESS_ALL_ACCESS` + debug privilege).
- Game reads go through `GameReader` — only `player_ptr, chr_ptrs, read_chr, handle, lock_target, cam_yaw, q, i32, f32` pass; any other name raises `AttributeError`.
- Pad: `XInputGetState` only (no `XInputSetState`, no vibration). F9: only polling the high bit of `GetAsyncKeyState` — no input consumption/injection, `SendInput`, `keybd_event`, or low-level hooks.
- Does not import `vgamepad, control, env, feed, souls, botlock` (the test checks this in a fresh interpreter). Does not take `bot.lock`.
- Output file uses `open("x")` — never overwrites an existing file. Existing `data/demo`, `data/trace`, `data/episodes` are untouched.

## Schema (v1)

One JSONL line = one event. Every line has `k` (kind) and `ms` (milliseconds since session start, `perf_counter_ns` monotonic clock).
The three threads (pad 120 Hz · world 10 Hz · writer) share the same clock, so **sort by `ms`, not by line order in the file**
(within the same kind, order is also chronological).

| k | When | Fields |
|---|---|---|
| `hdr` | first line | `v`, `wall_ns` (wall-clock reference), `pid`, `hz_world`, `hz_pad_poll`, `radius_m`, `read_access`, `alive_rule`, `marker_key`, `marker_debounce_ms`, `bot_phantom_rule` |
| `w` | 10 Hz | `read_ms` (time taken to read this snapshot), `epoch`, `p`, `cam_yaw`, `lock`, `e`, `e_fail` |
| `pad` | 120 Hz polling, only on change | `i` (pad index), `pkt` (XInput packet number), `btn`, `lt`, `rt`, `lx`, `ly`, `rx`, `ry` — all raw values |
| `mk` | F9 rising edge, 300 ms debounce | `n` (from 1) |
| `sys` | situational | `ev`: `sync` (`wall_ns` every 10 s), `loading`/`loaded` (`epoch`), `pad_found`/`pad_lost`, `error` (`where`, `msg`), `end` (summary) |

`w.p` (player): `pos[x,y,z]`, `hd` (heading, raw angle at +0x4), `anim`, `hp_raw`, `max_hp_raw`, `sp`, `max_sp`, `handle`

`w.lock`: `{"h": raw lock-on handle, "resolved": true|false|null, "id": enemy id|null}`
— `h=-1` means no lock-on (`resolved:null`), `h=null` means unreadable, `resolved:false` if not found in the list.

`w.e[]` (enemies/NPCs — everything within the radius regardless of team, plus the lock-on target even outside the radius):

| Field | Meaning |
|---|---|
| `id`, `id_src` | runtime identity (below) |
| `handle`, `ptr` | raw handle / pointer |
| `npc` | NPC param ID |
| `team_bot`, `flags1_raw`, `vt` | bot classification / raw flags / vtable kind (`player`·`enemy`·`other`) |
| `pos`, `hd`, `d`, `dy` | coordinates, heading, 3D distance to player, height difference (enemy − me) |
| `hp_raw`, `max_hp_raw`, `alive_derived`, `alive_rule` | raw HP / derived alive / rule name |
| `anim` | raw animation ID |
| `why` | reason recorded: `near` (within radius), `lock` (lock-on target) |
| `bot_phantom` | diagnostic value (see Limitations above) |

### Runtime identity

- `id = "h:<handle as 8-digit hex>#<epoch>"`, `id_src:"handle"` — the game's own character handle (+0x8), same value the lock-on points to.
- If the handle is 0, -1, or unreadable: `id = "p:<pointer hex>#<epoch>"`, `id_src:"ptr"`.
- `epoch` increments by 1 each time a loading period (player unreadable) ends — this separates handle/pointer reuse after a quit-out or warp.
- If an enemy read (`read_chr`) fails, it is **simply omitted** from that snapshot's `e` and `e_fail` increments. No copying of previous values or interpolation → blank in the viewer.
  Pointers whose coordinates couldn't even be read aren't counted as failures, since it's unknown whether they're within the radius.
- Slot (enemy-map number) assignment is not in Phase 1.

### Synchronization

- All lines: `ms` from the same monotonic clock. Aligned to wall clock via header `wall_ns` + `sys:sync` (`ms`↔`wall_ns` pair every 10 s).
- Video (OBS) sync doesn't exist yet. For later: doing a "clap" such as one roll at every recording start lets you find the offset between the data's `anim` change and the video's first frame.

### Size (measured with fake output, before real measurement)

| Case | World line | 60 s |
|---|---|---|
| 1 enemy (arena) | ~0.7 KB | world ~0.4 MB + pad 0.05–0.5 MB |
| 9 enemies (ramp 4+2 + surroundings) | ~4.3 KB | world ~2.6 MB + pad |

Pad is normally 10–30 lines/s (~90 B), worst case (stick constantly moving) 120 lines/s.

## Manual checklist (real game, after user approval)

Code (no game, verified by the test):
- [ ] `python tests/observe_record_test.py` all pass

Real game:
- [ ] No extra virtual pad appears in Device Manager or the `vgamepad` list during recording (compare before/during)
- [ ] Press each button/stick one at a time for 30 s before, during, and after recording — game response is the same
- [ ] Pressing F9 in-game causes no game reaction and adds exactly one `mk` line
- [ ] Start and stop the recorder during `run.py clear-ramp --no-rest` — bot behavior and logs don't change, and only the bot holds `bot.lock`
- [ ] Ctrl+C → last line is `sys:end`, no half-written line, summary is printed
- [ ] Quit-out · reload → `loading`/`loaded`, `epoch` increments, recording continues
- [ ] Unplug and replug the controller → `pad_lost`/`pad_found`, recording continues
- [ ] 60 s recording: size and line counts within the table above, `read_ms` p95 < 20 ms
- [ ] Existing file hashes identical before and after recording: `data/demo/20260924_162859.jsonl`, `data/trace/play_*`

First data order: in a safe flat arena, one ordinary hollow → one shield soldier. 60–90 s each, F9 2–3 times at moments of judgment.
The ramp 4+2 group is a later verification target.

## Smoke test results (2026-09-26, user manual control, on the ramp near Firelink Shrine)

| File | Length | World / pad / markers | p95 read_ms | Notes |
|---|---|---|---|---|
| `20260926_075757` | 225 s | 2248 / 447 / 0 | 4.32 | Pad not detected for the first 210 s (`pad_found` 210.6 s), mostly stationary |
| `20260926_080150` | 168 s | 1682 / 1417 / 5 | 4.48 | 3 RB attacks missing from pad lines (Steam Input suspected, see Limitations) |
| `20260926_081905` | 46 s | 463 / 40 / 1 | 4.14 | Steam Input off. 3× RB → 303000·303001·303002, B → 690, 1× F9 = 1 marker |

- All three files: 0 broken lines, `sys:end` (`ctrl_c`), 0 errors, 0 enemy read failures, world 10.0 lines/s, max gap 113 ms.
- Input → animation latency (±100 ms due to 10 Hz): RB→attack ~45–145 ms, B→backstep ~150–220 ms.
- Unverified: lock-on tracking (not used), pad with focus outside the game window.
- Size: ~1.5–2.4 MB per minute with 6–12 characters.

## Viewer v0 (Phase 2) — `observe_view.html`

Open the file directly in a browser (double-click → "기록 파일 열기" ("Open recording file") or drag and drop). No server, network, or external libraries
(network requests are blocked by CSP). It only reads the raw recording and writes nothing. Not connected to the game or pad.

- Top-down map: horizontal x, vertical z. Player = blue arrow (heading), characters = per-id colored dots + trails. Next to each dot: `npc`·`y`·raw anim.
  Lock-on target = yellow ring, `alive_derived=false` = hollow circle. Characters absent from that snapshot (read failure, outside radius) are not drawn and their trail is broken.
- Right-side table: the player at the current time (pos·y·hd·anim·HP·SP·cam_yaw·lock) and characters (by distance: id·npc·y·dy·d·anim·HP·team_bot·bot_phantom·why).
- Bottom: play/pause, timeline (marker ticks), speed (0.25–4×), jump to previous/next marker.
- ±2 s event view: pad changes, markers, sys, player anim changes, and character anim changes within 2 s before/after the current time, chronologically, as a lane chart and a list.
- Button names (A·B·LB·RB…) are just XInput bit names. No semantic labels like attack or guard are attached.
- Keys: Space play/pause · ←/→ 0.1 s · Shift+←/→ 1 s · `[` `]` previous/next marker.
- Older formats (`data/demo`, `data/trace`) are not read — only files with `hdr.v == 1`.

## Analysis rules (project-wide)

Always follow these when analyzing observation recordings, bot logs, and the black box.

1. **Quit-out (Escape) · reload = new-life boundary.** When the observation recording's epoch (`epoch`, `sys:loading`/`loaded`) or the bot's `esc.gen` changes,
   do not merge an enemy's life across the boundary — treat each `handle#epoch` life separately. Even if it was "cleared" before, do not assume
   it is cleared afterward.
   Evidence (2026-09-26 R1, `data/observe/20260926_101202.jsonl`): in epoch 0, #2 (`h:10008018#0`) reached raw HP 0 at 76.9 s, and
   after Escape, in epoch 1 (loading 88.2–94.8 s), a new standing-idle entity with raw HP 85/85 and active flag (`h:10008018#1`) was at the same spawn spot.
   The bot log said `cleared`. (Bot-side fix: `field._liveness` discards old identities on epoch change and rebinds fresh.)
2. **Identity = observation recording's `handle#epoch` + raw HP.** `find_at`, task labels (`#n`), and log text are secondary. For intervals where identity breaks (`e_fail`,
   epoch change), set that interval's conclusion to `unknown` and exclude it from aggregate conclusions.
3. Raw animation IDs are only evidence — attach no meaning until verified by repeated observation.
4. Bot log times and observation times are aligned via run file names (1 s) and the black box, so note a ±1.5 s error. Short windows (e.g. 1.8 s after a knife)
   are anchored on events inside the observation recording (e.g. start of my animation).

**Known verification task (after Patches A–D)**: pulling ramp #2 — the in-place tolerance of 1.5 m conflicts with the minimum distance of 13 m (the throw spot is
13.66 m from #2's spawn). In R3 (`20260926_101913`), `too_close` twice at 12.8 m. Not fixed by A–D — next verification target.

## Rollback

Phase 1 is only 3 new files — delete `observe_record.py`, `tests/observe_record_test.py`, `OBSERVE.md`, and
optionally `data/observe/`. Phase 2 is just `observe_view.html` — delete it and you're done.
No existing code or data was changed, so there is nothing else to revert.
