# CLAUDE.md

## Before you start
- Work branch: `claude/dsr-bot-project-review-r3hh9f`. `git pull` first. If your session started on another branch
  (cloud sessions start from `main`, which lags far behind), bring the work branch in first:
  `git fetch origin claude/dsr-bot-project-review-r3hh9f && git merge --ff-only FETCH_HEAD`. The session-start hook warns when this is needed.
- Read **ROADMAP.md** (short: open items, problem index, relay). History is in `docs/roadmap/` — look things up there
  by id (`grep -n "P-29\|6-a\." docs/roadmap/*.md`), don't read it whole.
- Roles: `[cloud]` (this cloud session, no game) · `[win]` (Windows + game) · `[MoKa]` (the human; old `[사람]` = MoKa).

## Keeping ROADMAP.md current
- Start an item: `[ ]` → `[~]`, commit. Finish: `[x]` + one line on how it was checked and the result, then move the
  line to its section in `docs/roadmap/plan.md` (ROADMAP keeps only open items). Commit and push.
- Problems (blocked, unexpected, or a mistake the bot recovered from): append a full entry `### P-<n> …` (symptom /
  cause / fix) to the bottom of `docs/roadmap/problems.md` and add one row to the ROADMAP "Problem index". Never delete
  entries; when fixed, write the fix under the entry and update the index status.
- `tests/roadmap_test.py` fails if ROADMAP.md grows past its size limit or a P-number is missing from the index.

## Board
- [win], [MoKa] and Mac Claude use the private MCP board (`maswarm-watchlist`, `board_*`). **[cloud] cannot reach it**
  (network allow-list / env not set, checked 2026-09-29), so [cloud] talks only through repo files and commit messages.
  The repo is public: don't open GitHub issues (#2–#15 are old records).
- [cloud] → board: add `- <date> [cloud→board] …` to ROADMAP "4. Relay". Board → [cloud]: the board side adds
  `[board→cloud]` there. Whoever handles an entry marks `→ moved` / `→ done`. Only settled things go into items or the problem log.
- Direct MCP access for [cloud] (cloud-only service token) waits for MoKa's environment setup.

## Code and tests
- Python 3.12. Offline tests (no game): `python -m pytest` (all) · `python -m pytest -k radar` (one) · `python tests/radar_test.py`
  (one script). New tests: `tests/<name>_test.py`, picked up automatically.
- Folders: root = modules and tools the bot runs with (radar, overlay, extraction) · `souls/` = layers · `tests/` = offline
  tests · `experiments/` = old experiments/measurements the bot never imports (`python experiments/x.py`) · `boss/` =
  boss experiments · `legacy/` = old code. The bot must not import from `experiments/` or `legacy/` (P-15, P-43).
- Fight rules (`souls/duel.py` `RULES`) fire top-down, first match wins. After changing a rule or the order,
  `python tests/duel_golden_test.py` shows which situations changed; if intended, re-record with `--record` and say why in the commit message.
- `python tests/duel_expect_test.py` checks the rules against scenes MoKa judged (`tests/expect/duel.jsonl`: situation +
  allowed / forbidden tactics + source; status `pass` · `known_fail:P-n` · `review`). golden = "changed?", this = "right?".
  A new MoKa instruction about fighting → add 2–5 scenes (source.kind `moka`, quote it) in the same commit as the rule change;
  when a decision closes a `known_fail`, set those lines to `pass`. `python tests/scene_world.py labels` drafts lines from labels.
- Game-memory writes (invincible, invisible, warp) are for offline use only.
- Rule and number sources: LAYERS.md. Record formats: OBSERVE.md.

## [win] after every bot run
Run `python hotspots.py` (this run vs earlier: NEW · AGAIN · GONE), `python track_report.py` (planned path vs actual,
stall spots) and `python blind_report.py` (decision gaps in fights — status line silent > 2 s and the damage taken
meanwhile, by cause; if this grows while the average tick stays the same, the bot got slower). Copy the run with
`python sample.py [<run>] [name]` (newest run by default: log → `.txt`, track, `.settings.json`, timestamp kept in the name;
the uncommitted `.diff` stays in `data/runs/`) and commit. Every run writes `data/runs/<time>_<name>.settings.json` (commit,
uncommitted changes, arguments, constants, character) and puts it in short on the log's first line; `python ab.py <run> <run>`
compares two runs' settings before their results. `--note "…"` adds a line (e.g. the save used). An AGAIN, the same stall spot in 2+ runs,
or decision-gap damage clearly above earlier runs goes into the problem log even if the bot recovered (a mistake that
didn't kill is still a defect).
