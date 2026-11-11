"""Undead Burg scene for the Godot practice room — bonfire to the Taurus Demon bridge, no foes (MoKa M1111-27: "이제 토우러스
보스 있는데까지 지형 맵 만들수 있어. 만들었으면, 몹은 만들지 말고, 캐릭터가 움직이게 해서 보여줘").

  python sim/burg_scene.py          → sim/godot/assets/burg_scene.json (local only — NavMesh from the game files)
  open:  Godot … --path sim/godot res://ramp.tscn -- --scene=burg

floor   m10_01 NavMesh (data/samples/navmesh_m10_01_00_00.npz, game coordinates) as the height lookup, as in the ramp room
walls   the Sketchfab "Undead Burg" area (scene sk_area / sk_walls; local file, ramp.gd _sk_faces) — no NavMesh-edge walls
look    natural_ground.gdshader on that area (ramp.gd default look, M1111-24/26)
route   Undead Burg bonfire → each burg-upper zone's safe spot (data/burg-upper-map.json) → Taurus fog wall → bridge
        trigger (souls/taurus.py TRIGGER) — the walk a bot does with `burg-upper --seg 1-8` then `taurus`, minus fights
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "sim" / "godot" / "assets" / "burg_scene.json"
NAV = ROOT / "data" / "samples" / "navmesh_m10_01_00_00.npz"
UPPER = ROOT / "data" / "burg-upper-map.json"

BONFIRE = [3.2, -10.0, -61.2]          # [game] o0200_0002 (souls/missions.py SPOTS burg-bonfire object)
START = [1.7, -10.02, -61.2]           # [meas] burg-bonfire stand
START_HEADING = -1.5708                # [meas] burg-bonfire heading
FOG = {"front": [52.07, 17.21, -118.55], "beyond": [49.62, 16.79, -118.74]}   # souls/taurus.py FOG
TRIGGER = [22.9, 15.9, -120.9]         # souls/taurus.py TRIGGER — the boss jumps down at the bridge's far end
# 사다리 (MoKa M1111-30): at = 매달린 동안의 몸 위치 (x, z), face = 사다리를 볼 때의 방향, y_bot / y_top = 아래·위 바닥 높이.
# 전부 실제 게임 녹화 트랙에서 [meas]
LADDERS = [
    {"name": "taurus", "at": [49.07, -117.08], "face": [0.974, 0.225], "y_bot": 15.82, "y_top": 24.82,
     "src": "tracks 20261011_174753 · 20261012_000026 / 000208 (climb up, 7010→7013)"},
    {"name": "burg-bonfire", "at": [-2.98, -62.61], "face": [-0.42, -0.91], "y_bot": -10.02, "y_top": -0.05,
     "src": "tracks 20261013_043024 · 20261013_181000 (down 7020→7023, up 7010→7013)"},
]


def route() -> list[list[float]]:
    zones = json.loads(UPPER.read_text(encoding="utf-8"))["zones"]
    pts = [START] + [z["safe"] for z in zones[:7]]       # zone 8's safe spot is up the ladder past the fog — not on the way
    return pts + [FOG["front"], FOG["beyond"], TRIGGER]


def main() -> None:
    d = np.load(NAV)
    v, t = d["v"], d["t"]
    out = {"source": "sim/burg_scene.py", "name": "burg", "sk_area": "Undead Burg", "sk_walls": True,
           "walls": [], "graph": [], "centroid": [], "graph_same_mesh": [], "bonfire": BONFIRE, "start": START,
           "start_heading": START_HEADING, "route": route(), "ladders": LADDERS,
           "nav": {"v": [[round(float(x), 3) for x in p] for p in v.tolist()], "t": t.tolist()}, "foes": []}
    OUT.write_text(json.dumps(out), encoding="utf-8")
    print(f"{OUT.relative_to(ROOT)}: NavMesh {len(v)} v / {len(t)} t, route {len(out['route'])} points, no foes")


if __name__ == "__main__":
    main()
