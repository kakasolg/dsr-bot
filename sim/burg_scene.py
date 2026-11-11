"""Undead Burg scene for the Godot practice room — bonfire to the Taurus Demon bridge, no foes (MoKa M1111-27: "이제 토우러스
보스 있는데까지 지형 맵 만들수 있어. 만들었으면, 몹은 만들지 말고, 캐릭터가 움직이게 해서 보여줘").

  python sim/burg_scene.py          → sim/godot/assets/burg_scene.json (local only — NavMesh from the game files)
  python sim/burg_scene.py --full   → sim/godot/assets/firelink_taurus_scene.json: from the Firelink Shrine bonfire, the bot's
                                      own merchant route (souls/missions.py _route), then the same Burg route (MoKa M1111-31)
  python sim/burg_scene.py --demon  → sim/godot/assets/firelink_demon_scene.json: the --full route, then on past the Taurus
                                      bridge to the Sunlight Altar, Andre's bonfire and the Titanite Demon (MoKa M1111-32)
  open:  Godot … --path sim/godot res://ramp.tscn -- --scene=burg   (or firelink_taurus / firelink_demon)

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
NAV_A = ROOT / "data" / "samples" / "navmesh_m10_02_00_00.npz"      # Firelink Shrine side — same game coordinates as m10_01
OUT_FULL = ROOT / "sim" / "godot" / "assets" / "firelink_taurus_scene.json"
OUT_DEMON = ROOT / "sim" / "godot" / "assets" / "firelink_demon_scene.json"
ALTAR_ROUTE = ROOT / "data" / "routes" / "altar-demo-20261012.json"     # the bot's burg-altar route (souls/altar.py)
DEMON_ROUTE = ROOT / "data" / "routes" / "andre-demon-20261111.json"    # MoKa's walk, Andre's bonfire → Titanite Demon
ALTAR_STAND = [23.8, 9.5, -23.0]       # [meas] spots.json altar-bonfire stand (11-09 light-altar sat here)
ANDRE_STAND = [88.46, 14.97, 106.96]   # [meas] spots.json andre-bonfire stand
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


def _floor(d) -> np.ndarray:
    """Triangles the room may stand on: not Disable / Degenerate (navmesh.BLOCKED), Wall (8) or Hole (2048) — the same set the
    bot's path graph uses (navmesh.py graph). With Wall faces in the height lookup the body walked up the steep Wall sheet
    beside the Taurus fog (y 16.8 → 19.4, run 20261111_124501 leg 16 stuck at the bridge parapet, M1111-31)."""
    keep = (d["flags"].astype(np.int64) & (1 | 16 | 8 | 2048)) == 0
    return d["t"][keep]


def full_legs() -> list[dict]:
    """Firelink Shrine bonfire → Taurus bridge as the bot walks it (souls/missions.py burg_bonfire: pass_ramp → to_merchant →
    light_burg_bonfire, then burg-upper / taurus). 'follow' = the recorded points the bot walks as they are, 'find' = NavMesh
    path to the point; map = the NavMesh the bot uses there (A = m10_02, B = m10_01). No foes, no boxes: the box roll
    between b and c (R["roll"]) is a plain walk here."""
    import sys
    sys.path.insert(0, str(ROOT))
    from souls import missions as MI
    spots = json.loads((ROOT / "data" / "spots.json").read_text(encoding="utf-8"))
    top, way, R = MI._route()
    legs = [{"name": "경사 꼭대기", "kind": "find", "map": "A", "pts": [list(top)]},
            {"name": "통로", "kind": "follow", "map": "A", "pts": [list(q) for q in MI._with_entry_corner(way)]},
            {"name": "성벽 마을", "kind": "follow", "map": "B", "pts": R["b"]},
            {"name": "창고 방", "kind": "follow", "map": "B", "pts": R["c"]},
            {"name": "상인", "kind": "find", "map": "B", "pts": [R["stand"]]},
            {"name": "성벽 마을 화톳불", "kind": "find", "map": "B", "pts": [START]}]
    for i, q in enumerate(route()[1:], 1):
        legs.append({"name": f"타우로스 길 {i}", "kind": "find", "map": "B", "pts": [q]})
    return legs, spots["firelink-bonfire"]


def demon_legs() -> list[dict]:
    """Taurus bridge end → Titanite Demon (MoKa M1111-32). Bridge → altar = the bot's burg-altar route without the Hellkite waits
    (souls/altar.py run: ① bridge entry, sprint ①→②, ② → ③ cover, sprint ③→④, altar bonfire). Altar → Andre: no bot or MoKa
    recording exists (souls/altar_andre.py is an unrun scaffold) — NavMesh path, not a walked route. Andre → demon: MoKa's own
    walk (observe 11-11); the NavMesh has no path there."""
    alt = json.loads(ALTAR_ROUTE.read_text(encoding="utf-8"))
    dem = json.loads(DEMON_ROUTE.read_text(encoding="utf-8"))
    m = alt["markers"]
    return [{"name": "헬카이트 다리 입구 (①)", "kind": "find", "map": "B", "pts": [m["1_bridge_entry"]]},
            {"name": "① → ② 계단 아래", "kind": "follow", "map": "B", "pts": alt["sprint_1_to_2"]},
            {"name": "② → ③ 엄폐 자리", "kind": "find", "map": "B", "pts": [m["3_stairs_cover"]]},
            {"name": "③ → ④ 헬카이트 떠나는 자리", "kind": "follow", "map": "B", "pts": alt["sprint_3_to_4"]},
            {"name": "태양의 제단 화톳불", "kind": "find", "map": "B", "pts": [ALTAR_STAND]},
            {"name": "제단 → 안드레이 화톳불 (녹화 없음, NavMesh 길)", "kind": "find", "map": "B", "pts": [ANDRE_STAND]},
            {"name": "안드레이 → 데몬 (MoKa 11-11 걸음)", "kind": "follow", "map": "B", "pts": dem["points"]}]


def floor_patches(legs: list[dict], d) -> list[list[list[float]]]:
    """Strips of floor (1.6 m wide) along 'follow' legs wherever the NavMesh has no standable triangle within 1 m of a recorded
    point — the recorded body positions are where a character really stood [meas]. Andre's forge floor (y 5.4) and the slope
    below it have none (M1111-32)."""
    import sys
    sys.path.insert(0, str(ROOT))
    import navmesh
    nm = navmesh.Navmesh.from_npz(NAV)
    ok = (nm.flags & (1 | 16 | 8 | 2048)) == 0

    def has_floor(q) -> bool:
        return any(ok[i] and abs(h - q[1]) < 1.0 for h, _, i in nm.tris_at(q[0], q[2]))

    out = []
    for L in legs:
        if L["kind"] != "follow" or L["map"] != "B":
            continue
        P = L["pts"]
        for a, b in zip(P, P[1:]):
            if has_floor(a) and has_floor(b):
                continue
            dx, dz = b[0] - a[0], b[2] - a[2]
            n = max(1e-6, (dx * dx + dz * dz) ** 0.5)
            ox, oz = -dz / n * 0.8, dx / n * 0.8
            q = [[a[0] + ox, a[1], a[2] + oz], [a[0] - ox, a[1], a[2] - oz], [b[0] - ox, b[1], b[2] - oz], [b[0] + ox, b[1], b[2] + oz]]
            q = [[round(v, 3) for v in r] for r in q]
            out += [[q[0], q[1], q[2]], [q[0], q[2], q[3]]]
    return out


# Viewer-camera sections by leg (MoKa M1111-34) — the first name fragment that matches wins; stairs come from the slope below
CAM_LEG_TAGS = [("통로", "corridor"), ("창고", "corridor"), ("타우로스 길 9", "bridge"), ("타우로스 길 10", "bridge"),
                ("헬카이트 다리", "bridge"), ("① → ②", "bridge"), ("안드레이 → 데몬", "corridor")]
STAIRS_SLOPE = 0.3      # [guess] |dy| / horizontal over ±2 m above this = stairs (or a steep ramp)
STAIRS_DY = 0.6         # [guess] and at least this much height change over that window
CAM_MIN_RUN = 4         # [guess] points (~4 m): a shorter section is noise, not a section


def cam_path(legs: list[dict], start: list[float]) -> list[list]:
    """The planned route as ~1 m points [x, y, z, leg, tag] for the viewer camera (sim/godot/cam_director.gd): 'follow' legs
    as recorded, 'find' legs as NavMesh find_path from the previous leg's end — what sim/burg_walk.py walks, planned once
    here (the walk can differ when it re-plans)."""
    import math
    import sys
    sys.path.insert(0, str(ROOT))
    import navmesh
    nms = {"A": navmesh.Navmesh.from_npz(NAV_A), "B": navmesh.Navmesh.from_npz(NAV)}
    raw, here = [], tuple(start)
    for i, L in enumerate(legs):
        if L["kind"] == "follow":
            pts = [tuple(q) for q in L["pts"]]
        else:
            pts = [tuple(q) for q in (nms[L["map"]].find_path(here, tuple(L["pts"][-1])) or [L["pts"][-1]])]
        tag = next((t for k, t in CAM_LEG_TAGS if k in L["name"]), "default")
        for q in [here] + pts:
            raw.append((q, i, tag))
        here = pts[-1]
    out = []                                          # resample to ~1 m (long NavMesh segments get inner points)
    for (a, i, tag), (b, _, _) in zip(raw, raw[1:] + [raw[-1]]):
        n = max(1, int(math.dist(a, b)))
        for k in range(n):
            q = [a[j] + (b[j] - a[j]) * k / n for j in range(3)]
            if not out or math.dist(q, out[-1][:3]) > 0.5:
                out.append([round(q[0], 2), round(q[1], 2), round(q[2], 2), i, tag])
    for k, p in enumerate(out):                       # slope → stairs
        a, b = out[max(0, k - 2)], out[min(len(out) - 1, k + 2)]
        h = math.hypot(b[0] - a[0], b[2] - a[2])
        if abs(b[1] - a[1]) >= STAIRS_DY and abs(b[1] - a[1]) / max(h, 0.1) > STAIRS_SLOPE:
            p[4] = "stairs"
    runs, k = [], 0                                   # sections shorter than CAM_MIN_RUN points take the one before
    while k < len(out):
        j = k
        while j < len(out) and out[j][4] == out[k][4]:
            j += 1
        runs.append((k, j))
        k = j
    for r, (k, j) in enumerate(runs):
        if j - k < CAM_MIN_RUN and r > 0:
            for p in out[k:j]:
                p[4] = out[k - 1][4]
    return out


def main() -> None:
    import sys
    demon = "--demon" in sys.argv
    full = "--full" in sys.argv or demon
    d = np.load(NAV)
    v, t = d["v"], _floor(d)
    if full:
        da = np.load(NAV_A)
        t = np.concatenate([_floor(da), t + len(da["v"])])    # two sheets in one height lookup (same world coordinates)
        v = np.concatenate([da["v"], v])
    out = {"source": "sim/burg_scene.py", "name": "burg", "sk_area": "Undead Burg", "sk_walls": True,
           "walls": [], "graph": [], "centroid": [], "graph_same_mesh": [], "bonfire": BONFIRE, "start": START,
           "start_heading": START_HEADING, "route": route(), "ladders": LADDERS,
           "nav": {"v": [[round(float(x), 3) for x in p] for p in v.tolist()], "t": t.tolist()}, "foes": []}
    dst = OUT
    if full:
        legs, fb = full_legs()
        out.update({"name": "firelink_taurus", "sk_area": "Firelink Shrine|Undead Burg", "legs": legs,
                    "bonfire": fb["object"], "start": fb["stand"], "start_heading": fb["heading"],
                    "route": [fb["stand"]] + [L["pts"][-1] for L in legs]})
        dst = OUT_FULL
    if demon:
        legs = out["legs"] + demon_legs()
        out.update({"name": "firelink_demon", "legs": legs, "route": [out["start"]] + [L["pts"][-1] for L in legs],
                    "floor_patch": floor_patches(legs, d)})
        dst = OUT_DEMON
        print(f"floor patches: {len(out['floor_patch'])} triangles")
    legs = out.get("legs") or [{"name": f"구간 {i}", "kind": "find", "map": "B", "pts": [q]}   # as sim/burg_walk.py
                               for i, q in enumerate(out["route"][1:], 1)]
    out["cam_path"] = cam_path(legs, out["start"])
    tags = {}
    for p in out["cam_path"]:
        tags[p[4]] = tags.get(p[4], 0) + 1
    print(f"cam_path: {len(out['cam_path'])} points {tags}")
    dst.write_text(json.dumps(out), encoding="utf-8")
    print(f"{dst.relative_to(ROOT)}: NavMesh {len(v)} v / {len(t)} t, route {len(out['route'])} points, no foes")


if __name__ == "__main__":
    main()
