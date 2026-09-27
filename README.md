# dsr-bot — a rule-based Dark Souls Remastered bot

**Offline only.** A Python bot that plays Dark Souls Remastered (PC, Steam) by reading game memory, pathfinding with A\* on the
game's NavMesh, and fighting with a hand-tuned rule table.
It currently gets from **Firelink Shrine → the 6 hollows on the Undead Burg ramp → Undead Burg → the merchant → the Undead Burg
bonfire** on its own.

**Video (7:43, turn on CC to see what the bot is deciding):** https://youtu.be/_ihMBcxvG5w
— one run with controller input only, no quit-outs or teleports (`run.py burg-bonfire --no-quit`).

> Do not use it while connected online. Some features write to game memory (bonfire warp, quit to title), which risks a ban
> online and can affect other players. This repository is for research and learning.

## How it "sees" the game

It doesn't. There is no screen capture, image recognition or video analysis. The bot reads values straight from game memory —
positions, HP and stamina, enemy IDs, which animation each enemy is playing (i.e. which attack is coming), facing, camera angle,
lock-on target, item counts — and makes every decision from those numbers plus the NavMesh from the game files.

## Status (2026-09)

- No LLM or machine-learning model runs during play — it is all rules and numbers. (`tactic_llm.py`, `bandit.py`, `learn.py`
  etc. are old experiments.)
- Development: most of the code was written by an AI coding assistant (Claude); a human did the play demonstrations, decisions
  and verification. See the `Co-Authored-By` lines in the commits.
- Recent runs: ramp 6/6, Undead Burg bonfire reached. With minimal gear the lowest HP is 27–47% — fights where several enemies
  close in at once are the weak point.
- The original author can't keep working on it and is releasing it. **Anyone who wants to take it over or join in is welcome** —
  especially if you'd like to plug an LLM or a JEPA-style model into one of the layers.

## Layout

```
dsr_telemetry.py / telemetry.py   game memory reads (pymem) — position, HP, animation, enemies, camera
navmesh.py / nav.py               game NavMesh (via soulstruct) → triangle graph, A* pathfinding, footing checks
souls/                            layered — lower layers never know about upper ones (LAYERS.md)
  moves.py     layer 1: controls (virtual pad via vgamepad)
  duel.py      layer 2: one-on-one combat rules
  foes.py      per-enemy data (animation IDs, attacks that must not be blocked, ...)
  field.py     layer 4: field play — engagement queue, luring with throwing knives, holding a spot, safe zones
  missions.py  layer 5: missions — ramp / Undead Burg / merchant / bonfire
run.py                            entry point
observe_record.py                 read-only observation recorder (human demos and bot runs in the same format)
risk_report.py, blackbox.py       run evaluation — big hits, lowest HP, getting stuck
```

The rules and their justification live in one place, [LAYERS.md](LAYERS.md) (written in Korean). In particular the
**evidence-grade gate**: every number is tagged with what backs it — human demo / repeated observation / NavMesh estimate /
code constant / unknown — and only actions that grade allows are taken. The recording format is in [OBSERVE.md](OBSERVE.md).
Code comments and logs are mostly in Korean.

## Running it

You need: Windows, DSR (Steam), [ViGEmBus](https://github.com/nefarius/ViGEmBus) for the virtual Xbox pad, Python 3.12,
[uv](https://docs.astral.sh/uv/). Turn Steam Input off (Steam intercepts the pad input otherwise).

```bash
uv venv .venv --python 3.12
uv pip install --python .venv/Scripts/python.exe -r requirements-lock.txt
# if DSR is installed elsewhere: set DSR_GAME_DIR=...\DARK SOULS REMASTERED
BOT_GAME=dsr .venv/Scripts/python run.py clear-ramp                 # ramp only
BOT_GAME=dsr .venv/Scripts/python run.py burg-bonfire               # Firelink → Undead Burg bonfire
BOT_GAME=dsr .venv/Scripts/python run.py burg-bonfire --no-quit     # no quit-outs, no bonfire teleport (for recording)
.venv/Scripts/python observe_record.py --minutes 15                 # read-only recording (F9 = marker)
```

Offline tests (fake world, no game needed): `python field_*_test.py`, `duel_shadow_test.py`, `moves_test.py`, etc.

`data/` only contains the small files the missions need — routes a human walked and recorded (`data/routes/`), enemy spawn
maps, and user-marked safe zones (`safe-zones.json`). Observation recordings and run logs (1 GB+) are not included; open an
issue if you need them.

## Worth trying next

- Fights with several enemies at once (the biggest source of damage now) — separating them, choosing where to fight
- Predicting enemy attacks — the meaning of the animation IDs (e.g. 3004/3500 in `foes.py`) is not yet verified on video
- Learning from human demos — observation recordings use the same format for humans and the bot, so they can be compared or
  used as training data
- Smoothing NavMesh paths (funnel algorithm), recognising breakable objects

## Older docs

The Elden Ring-era README is [README-legacy.md](README-legacy.md). This bot started as a subfolder of
[chzzk-souls-chaos](https://github.com/kakasolg/chzzk-souls-chaos) (a Chzzk-donation → game-effect adapter).
