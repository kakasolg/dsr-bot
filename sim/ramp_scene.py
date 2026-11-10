"""Ramp scene for the Godot practice room (MoKa M1109-65: the bot plays the Firelink ramp in the room).

  python sim/ramp_scene.py          → sim/godot/assets/ramp_scene.json (local only — built from game files)

What goes in, and where it comes from:
  floor      Firelink NavMesh (data/samples/navmesh_m10_02_00_00.npz, game coordinates) as the walkable surface —
             the room has no map collision; off the NavMesh there is no floor (cliffs drop, like the game) [guess:
             walls and steps the NavMesh leaves out are not there]
  foes       the six ramp placements (m10_02 MSB = data/enemy-map.json spawns): position, facing, NpcParam, model,
             NpcThinkParam (battle start / sight), AtkParam attack windows via chr_models.json [game]
  behaviour  what the three runs of 11-09 showed (bot 171230, MoKa 17:19 and 17:25 — docs/moka_ledger.jsonl
             M1109-62/63/64) where the files can't say: see FOES below, each value tagged [game] / [meas] / [guess]
Room coordinates are game coordinates (as main.gd); the map model is mirrored back in the room.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "sim" / "godot" / "assets" / "ramp_scene.json"
NAV = ROOT / "data" / "samples" / "navmesh_m10_02_00_00.npz"
MSB = ROOT / "data" / "gamefiles" / "m10_02_00_00.json"
SPAWNS = ROOT / "data" / "enemy-map.json"

BONFIRE = [-54.06, -59.95, 58.07]           # [game] Firelink bonfire
START = [-47.4, -59.8, 53.3]                # [meas] the Firelink arrival save's stand (run.py status after restore)
START_HEADING = -2.6                         # [guess] facing the ramp side

# per ramp foe (order = data/enemy-map.json): role from NpcThinkParam names [game]; wake = when it starts toward the
# player. [game] battle start distance; #4 [meas] never woke with the player 19 m away on the flat below, woke at
# 6.0 / 9.4 / 7.1 m on its own ledge → 10 m and same level (|dy| < 3 m) [guess from 3 runs].
# #5 firebomb [meas]: never left its spawn in 3 runs; a 3008 every 3.5–3.8 s from ~21 m in; the hit lands 2.4–2.8 s
# after the 3008 starts (5 cases), −107…−111 open, −30 through the shield. Melee damage per hit [meas] means of the
# 11-09 runs' HP drops by that foe (player defence differs per character — Claymore 849 vs Battle Axe 682).
FOES = [
    {"role": "sword · hold (専守)", "wake": 9.0, "wake_tag": "game", "dmg": 110},
    {"role": "longsword heavy · hold (専守)", "wake": 9.0, "wake_tag": "game", "dmg": 140},
    {"role": "sword", "wake": 20.0, "wake_tag": "game", "dmg": 110},
    {"role": "axe", "wake": 10.0, "wake_tag": "meas", "same_level": 3.0, "dmg": 110},
    {"role": "sword · firebomb", "wake": 21.0, "wake_tag": "meas", "dmg": 110, "stay": True,
     "throw": {"every": 3.6, "land": 2.5, "dmg": 109, "dmg_guard": 30, "radius": 1.5, "min": 2.5}},
    {"role": "sword · hold (専守)", "wake": 9.0, "wake_tag": "game", "dmg": 110},
]
# [meas] radar 11-09 (3 runs): approach speed of woken hollows on open ground
WALK_V = 1.6     # [guess] within 4 m they walk (strafe-ish)
WALL_OUT = 0.4   # [guess] NavMesh agent radius — how far past the NavMesh edge the room's walls stand
RUN_V = 3.5      # [meas] ≈ the player's jog — #3 covered ~14 m in 5.6 s incl. the start (171230)


def _floor_under(v, t, pos, below: float = 1.5) -> bool:
    """Is there a NavMesh triangle under pos (xz inside, top within `below` m under it)?"""
    px, py, pz = pos
    for a, b, c in v[t]:
        d = (b[2] - c[2]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[2] - c[2])
        if abs(d) < 1e-9:
            continue
        l1 = ((b[2] - c[2]) * (px - c[0]) + (c[0] - b[0]) * (pz - c[2])) / d
        l2 = ((c[2] - a[2]) * (px - c[0]) + (a[0] - c[0]) * (pz - c[2])) / d
        l3 = 1 - l1 - l2
        if min(l1, l2, l3) >= -1e-6 and -below <= l1 * a[1] + l2 * b[1] + l3 * c[1] - py <= 0.3:
            return True
    return False


def main() -> None:
    z = np.load(NAV)
    v = z["v"].astype(float)
    t = z["t"].astype(int)
    msb = json.loads(MSB.read_text(encoding="utf-8"))
    spawns = json.loads(SPAWNS.read_text(encoding="utf-8"))["enemies"]
    models = json.loads((ROOT / "data" / "gamefiles" / "chr_models.json").read_text(encoding="utf-8"))
    foes = []
    for i, s in enumerate(spawns):
        e = min(msb["enemies"], key=lambda e: float(np.linalg.norm(np.array(e["pos"]) - np.array(s["pos"]))))
        th = e["think"]
        m = models.get(e["model"], {})
        foes.append({"n": i + 1, "name": e["name"], "model": e["model"], "npc": e["npc_param_id"], "think": e["ai_id"],
                     "pos": e["pos"], "heading": float(np.radians(e["rot_y"])), "max_hp": s["hp"],
                     "battle_start": th["BattleStartDistance"], "sight": th["SightDistance"],
                     "masks": m.get("npc_masks", {}).get(str(e["npc_param_id"]), []),
                     "attacks": m.get("npc_attacks", {}).get(str(e["npc_param_id"]), {}),
                     # no NavMesh under the spawn (#5's spot on 11-09) → the room puts a 3 m pad there [guess size]
                     "floor": _floor_under(v, t, e["pos"]),
                     **FOES[i]})
    # walls: open NavMesh edges with no walkable floor beyond them (0.8 m out) at or below the edge's height (+0.5 m) —
    # i.e. a void, a building side or a face up to higher ground. The room stands a 2.8 m invisible wall there; an
    # edge with floor anywhere below stays open (you step or fall down, as in the game). Not navmesh.edge_kinds()'s
    # "wall": that one also calls a 0.5–1.5 m step down a wall, and the 2nd room run (11-09 17:50) stuck 5 min at
    # (−40.8, −59.0, 50.8) between two overlapping NavMesh pieces whose open edges stood there.
    # [guess] a void edge in the game may be a fall to death; the room blocks it
    sys.path.insert(0, str(ROOT))
    import navmesh
    nm = navmesh.Navmesh("m10_02_00_00")
    ti, ei = np.nonzero(nm.adj < 0)
    walls = []
    for k in range(len(ti)):
        a, b = {0: (0, 1), 1: (1, 2), 2: (0, 2)}[int(ei[k])]
        p0, p1 = nm.v[nm.t[ti[k], a]], nm.v[nm.t[ti[k], b]]
        mid = (p0 + p1) / 2.0
        d = mid - nm.centroid[ti[k]]
        n = float(np.hypot(d[0], d[2]))
        if n < 1e-6:
            continue
        q = mid + np.array([d[0] / n * 0.8, 0.0, d[2] / n * 0.8])
        ys = [y for y, f, _ in nm.tris_at(float(q[0]), float(q[2])) if not (f & navmesh.BLOCKED)]
        if not any(y - mid[1] <= 0.5 for y in ys):
            # pushed out by WALL_OUT: a NavMesh stops an agent radius short of the real wall, and walls right on its
            # edge left the ramp's foot (−40.8, −59.0, 50.8) narrower than the player (3rd room run, 11-09 17:57)
            e = p1 - p0
            nx, nz = e[2], -e[0]
            ln = float(np.hypot(nx, nz)) or 1.0
            sgn = 1.0 if nx * d[0] + nz * d[2] > 0 else -1.0
            off = np.array([nx / ln * sgn * WALL_OUT, 0.0, nz / ln * sgn * WALL_OUT])
            walls.append([round(float(x), 3) for x in (*(p0 + off), *(p1 + off))])
    # foe path finding (MoKa M1109-66: #6 never came down in the 5th room run — straight-line chasing stopped at the
    # ledge): the bot's own NavMesh graph (navmesh.graph(): neighbours within a piece and across pieces, A* weights)
    # and triangle centroids — the room runs A* on it. [guess] DSR's AI moves on its own NavMesh; that it picks the
    # same route as this graph's A* is not known
    g = nm.graph()
    graph = [[[int(n), round(float(w), 3)] for n, w in g.get(i, [])] for i in range(len(nm.t))]
    cent = [[round(float(x), 3) for x in c] for c in nm.centroid]
    same = len(nm.t) == len(t) and bool(np.allclose(nm.v, v))
    out = {"source": "sim/ramp_scene.py", "walls": walls, "graph": graph, "centroid": cent, "graph_same_mesh": same, "bonfire": BONFIRE, "start": START, "start_heading": START_HEADING,
           "walk_v": WALK_V, "run_v": RUN_V,
           "nav": {"v": [[round(x, 3) for x in p] for p in v.tolist()], "t": t.tolist()}, "foes": foes}
    OUT.write_text(json.dumps(out), encoding="utf-8")
    print(f"{OUT}: {len(t)} floor triangles, {len(walls)} wall edges, graph {sum(map(len, graph))} links (same mesh {same}), {len(foes)} foes "
          + ", ".join(f"#{f['n']} {f['model']} {f['npc']} attacks {len(f['attacks'])}"
                     + ("" if f["floor"] else " (no NavMesh under it)") for f in foes))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
