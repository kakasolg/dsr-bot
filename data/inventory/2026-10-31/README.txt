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

--- Follow-up request (G2 scene links), same day, read only ---

Scene links - aggregated (120 runs read, 0 read errors, 1868 scenes).
  g2_scene_links.jsonl: one line per scene, no snapshot body. ~1.2 MB (over the few-tens-of-KB guideline above:
  one line per scene was asked for). Definitions are in the script docstring
  (experiments/inventory_2026_10_31/inv_g2_scenes.py). Counts:
  - scene's dec.rule: matched by snap_t 1319, by adjacent same rule 122 (its snap_t differs), null 427
    (367 "same rule only earlier, not adjacent and snap_t differs", 60 "no dec.rule with this rule before the scene").
  - pad window (only when a dec.rule matched): empty 1093, non-empty 348. In G2 files dec.rule is written after the
    rule returns, often right after the previous dec.rule, so the pads a rule wrote usually sit before that window.
  - next scene of the same fight: present 1164, fight_end 624, no_next_scene 80.
  - fight key = ptr@start time (G2 scenes have no fight id); hostile = hp > 0 and team != player team, within the
    scene list (<= 25 m).

Unsampled metadata - aggregated (17 runs, 0 read errors).
  g2_unsampled_meta.json: runs with no git-tracked *settings.json whose name holds the run stamp (sample.py may add a
  label, so matching by exact file name gives 83 - not used). Fields from data/runs/<run>.settings.json.
  4 runs have no "game" block (weapon / max HP null): 20261010_010907, 20261012_215320, _215457, _215541.

--- Follow-up request (G2 scene extract for the manifest), same day, read only ---

g2_scene_manifest.tsv: Cloud's g2_scene_manifest_compact.tsv as given (header line kept; 55 runs, 1475 scenes incl.
pending 22). Its sha256 equals the one in the request (ab637fcb...8dbe; "compressed TSV" = this compact TSV, not gzip).
The extract was first run from the TSV pasted in the request; it equals this file minus the header line.
g2_scene_manifest_scenes.jsonl, g2_scene_manifest_runs.json: Cloud's other two manifest files, as given. Checked against
the extract: same (run, scene_seq) set, split and schema; rule_expected = ctl rule and fight_key_est =
g2_scene_links.jsonl fight for all 1475; runs.json commit / dirty / cmd / seg / weapon name / split / n_scenes equal
the extract for all 55. 0 differences.
Target check - aggregated: 1475/1475 are k="scene" with rule equal to g2_scene_links.jsonl; 0 missing / mismatched.
g2_scene_extract.jsonl - aggregated: 1475 lines (train 730, val 134, test 233, shift_zone 292, shift_ref 64,
  pending 22), 10,994,695 bytes (under 20 MB, so not gzipped). Values copied from the scene record as captured; meta
  from data/runs/<run>.settings.json (all 55 read, incl. the 2 runs whose settings are not in git).
g2_scene_fight_keys.json - aggregated: fight dict keys with scene counts, by run and by commit.
g2_scene_extract_check.json - aggregated: target check, counts by split, missing (absent or null) per field, style
  per run, fight.arena not null, whether the 9 uncommitted diffs change duel.py / scenes.py, size stats.
Script: experiments/inventory_2026_10_31/inv_g2_extract.py <manifest.tsv>
