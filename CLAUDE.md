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
- [win], [MoKa], Mac Claude and [cloud] share the private MCP board (`board_*`). [win]/Mac call the server
  `maswarm-watchlist`; [cloud] reaches the same server as `maswarm-cloud` (`.mcp.json`, URL only): the cloud environment
  allows `mcp-maswarm.moko.fyi` and its proxy adds the cloud-only Cloudflare Access headers (Network secrets — never put
  them in the repo). [cloud]'s board name is `cloud-claude` (read and post checked 2026-10-27, again 2026-11-14).
  Early in a session: `board_unread(reader="cloud-claude")`; post when something the others depend on changes.
- A cloud session whose checkout has no `.mcp.json` (started from a `main` older than 2026-11-11) gets no board tools,
  but the server still answers MCP over HTTP at `https://mcp-maswarm.moko.fyi/mcp` (`initialize` → `tools/call`
  `board_unread` / `board_post`; the proxy adds the headers). Checked 2026-11-14.
- On [win]/Mac, decline `maswarm-cloud` when Claude Code asks (no proxy there, it fails at Cloudflare).
  The repo is public: don't open GitHub issues (#2–#15 are old records).
- The ROADMAP "Relay" section is the old repo-file channel from before [cloud] could post. New messages go on the board;
  entries still open there are handled as before (`→ done` / `→ moved` after the tag). Only settled things go into
  items or the problem log.

## Code and tests
- Python 3.12. Offline tests (no game): `python -m pytest` (all) · `python -m pytest -k radar` (one) · `python tests/radar_test.py`
  (one script). New tests: `tests/<name>_test.py`, picked up automatically.
- Folders: root = modules and tools the bot runs with (radar, overlay, extraction) · `souls/` = layers · `tests/` = offline
  tests · `experiments/` = old experiments/measurements the bot never imports (`python experiments/x.py`) · `boss/` =
  boss experiments · `legacy/` = old code. The bot must not import from `experiments/` or `legacy/` (P-15, P-43).
- Fight rules (`souls/duel.py` `RULES`) fire top-down, first match wins. After changing a rule or the order,
  `python tests/duel_golden_test.py` shows which situations changed; if intended, re-record with `--record` and say why in the commit message.
- Game-memory writes (invincible, invisible, warp) are for offline use only.
- Rule and number sources: LAYERS.md. Record formats: OBSERVE.md.

## [win] after every bot run
Run `python hotspots.py` (this run vs earlier: NEW · AGAIN · GONE), `python track_report.py` (planned path vs actual,
stall spots) and `python blind_report.py` (decision gaps in fights — status line silent > 2 s and the damage taken
meanwhile, by cause; if this grows while the average tick stays the same, the bot got slower). Copy the run's
`data/runs/<time>_<name>.track.jsonl` and log to `data/samples/` and commit. An AGAIN, the same stall spot in 2+ runs,
or decision-gap damage clearly above earlier runs goes into the problem log even if the bot recovered (a mistake that
didn't kill is still a defect).
