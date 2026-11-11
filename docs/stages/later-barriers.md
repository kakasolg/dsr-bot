# Later barriers — Blighttown and Sen's Fortress

Status: **problem notes only** (MoKa 2026-10-28: "일단 어느 문서에 그런 문제가 있다는 것만 작성하자"). No work planned yet. Ideas below
are untested; none of them has been checked in files, memory or the game.

## Why these two are hard for this bot

The bot has no video or sound. It has things a player lacks: every foe's position (also behind walls), the NavMesh map, extracted
numbers (windup times, reach, AI scripts). So it does better where a place can be **known in advance** than where it must be **seen
and reacted to**.

## Blighttown (병자의 마을)

| Problem (MoKa) | What the bot has today | Idea (untested) |
|---|---|---|
| Poison builds up easily | Nothing (no poison code) | Read the poison build-up value from memory, treat it like HP (cure / back off). Poison sources' positions are known |
| Many ladders | One ladder climbed (`souls/altar.py`, `LADDER_A_R` 0.45 m, from MoKa's demo) | Ladder positions from map data (soulstruct is installed) as links between NavMesh pieces |
| Few ways through; hard boss | — | Route data per segment (v2.0 `route-data`); boss is its own topic |

## Sen's Fortress (센의 고성)

| Problem (MoKa) | What the bot has today | Idea (untested) |
|---|---|---|
| Narrow walkways: a sideways stagger = fall death | Exact own position, NavMesh edges, `rule_footing` / floor check | Walk the centre line; the real risk is being knocked off (blade, snakemen) |
| Giant swinging blades on the path: a hit = fall | Nothing | A blade moves on a fixed cycle → predictable if its **phase** is known: (1) read the blade's position / rotation from memory (map objects — not known if readable); (2) map data for blade count and placement; (3) measure the cycle offline (invincible / warp are allowed offline); (4) last resort: a narrow screen check for this one object |

Suggested first step when this comes up: (1)+(2) for the blades, offline, no game.
