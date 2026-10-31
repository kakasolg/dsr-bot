Experience-data inventory, 2026-10-31 ([win], read only: no game run, no new data, no code/doc/ROADMAP change).
Paths are repo-relative; ~ = the user folder. Raw files were not uploaded.

Request 1 - G3 ctl_check: aggregated (3/3 runs read).
  g3_<run>.ctl_check.txt   python ctl_check.py data/runs/<run>.ctl.jsonl            (output as printed)
  g3_<run>.vs_scene.txt    python ctl_check.py data/runs/<run>.ctl.jsonl --vs-scene (ran for all 3; 225853 has no
                           span.obs, so its scene lines say "no span.obs")
  g3_<run>.json            counts, cycle kind, picked, action name / end, span.obs status, chars per span.obs, ctl end
  Cycles: 91 + 68 + 366 = 525.

Request 2 - record examples: aggregated.
  g3_record_examples.jsonl from data/runs/20261031_005154_burg-bonfire.ctl.jsonl, attack cycle 447 (fight 1,
  action 455 light): span.fight start/end, span.cycle start/end, span.rule, span.action start/end, span.obs,
  pad (with action_id 455), scene - raw lines; span.obs and scene chars cut to 3 with "_truncated": original count.
  pad.override: none inside cycle 447 -> the LAST line is the file's first pad.override (line 1165, cycle 2), raw.

Request 3 - G2 ctl presence: aggregated.
  g2_ctl_presence.json: data/runs/*.settings.json dated 20261009..20261027 with args.ctl or args.ctl_scenes true.
  120 runs, ctl.jsonl present 120, scene 1868, pad 511281, dec.rule 5596, end record 119 (missing: 20261012_215634_burg-upper).
  Not covered: runs without a settings.json.

Request 4 - observe recordings: aggregated (58 files, 0 read errors).
  observe_list.json. play_kind from pad line slot i: human (slot 0) 40 files / 11046.1 s / 72 F9 markers;
  mixed (slot 0 and 1 lines) 17 files / 16553.8 s (several have only 1-2 slot-0 lines - counts are in the file);
  no pad lines 1 file / 18641.8 s. Length = max(ms) - min(ms). zone_hint = nearest data/spots.json point within 20 m
  of the first player position (no map id in the recording), else null. No melee / combat time computed.

Request 5 - videos: aggregated (12 files, not sent).
  video_list.json: ~/Videos/*.mp4 (OBS record path). Shell metadata: length, resolution, fps; start = file creation
  time. 11 of 12 overlap a bot run by wall time (09-26 x2, 10-03 x9); none overlap an observe recording.
  No sync marks found in run / observe files; on-screen markers not checked.

Scripts: experiments/inventory_2026_10_31/ (not imported by the bot). Video metadata came from a PowerShell call
(Shell.Application GetDetailsOf: Length, Frame width, Frame height, Frame rate) saved to a temp JSON passed to inv_video.py.
