"""Replay props.steer_around on a run's planned paths that pass learned props — print why each was not bent (no game).

  python experiments/steer_debug.py data/runs/<run>.track.jsonl
"""
import json, math, sys, pathlib
sys.path[:0] = [str(pathlib.Path(__file__).resolve().parent.parent)]
sys.stdout.reconfigure(encoding="utf-8")
import navmesh
from souls import props as P

track = sys.argv[1]
paths = {}
for line in open(track, encoding="utf-8"):
    m = json.loads(line)
    if m.get("type") == "snap" and m.get("path"):
        key = tuple(tuple(q) for q in m["path"])
        paths.setdefault(key, (m.get("path_tag"), m["rt"]))

MAPS = ["m10_01_00_00", "m10_02_00_00"]
props = {mid: P.load(mid) for mid in MAPS}
steer = P.learned()
print("learned:", steer)
for mid in MAPS:
    print(mid, "breakables:", len(props[mid]), "learned here:", [(o["name"], o["pos"]) for o in props[mid] if o["name"] in steer])
nms = {}
for path, (tag, rt) in paths.items():
    for mid in MAPS:
        for o in props[mid]:
            if o["name"] not in steer:
                continue
            q = o["pos"]
            near = [i for i in range(1, len(path)) if abs(q[1] - path[i][1]) <= P.DY and P._seg_dist(q, path[i - 1], path[i]) < P.CLEAR]
            if not near:
                continue
            nm = nms.setdefault(mid, navmesh.Navmesh(mid))
            print(f"\n{rt:7.1f} s {tag}: {len(path)} pts, passes {o['name']} ({mid}) — min dist "
                  f"{min(P._seg_dist(q, path[i-1], path[i]) for i in near):.2f} m, segments {near}")
            inside = lambda p: math.hypot(p[0] - q[0], p[2] - q[2]) < P.CLEAR
            j, k = near[0] - 1, near[-1]
            while j >= 0 and inside(path[j]): j -= 1
            while k < len(path) and inside(path[k]): k += 1
            print(f"   j={j} k={k} len={len(path)}")
            if j < 0 or k >= len(path) or k - j > 4:
                print("   → skipped: starts/ends at prop or loop"); continue
            a, b = path[j], path[k]
            print(f"   a={tuple(round(v,2) for v in a)} b={tuple(round(v,2) for v in b)} |ab|={math.hypot(b[0]-a[0], b[2]-a[2]):.2f} dy={b[1]-a[1]:.2f}")
            if math.hypot(b[0] - a[0], b[2] - a[2]) < 0.5 or abs(b[1] - a[1]) > P.DY / 2:
                print("   → skipped: too short or stairs"); continue
            y = (a[1] + b[1]) / 2
            for side in (-1, 1):
                new = [a] + P._detour(a, b, q, side, y) + [b]
                for c in new[1:-1]:
                    print(f"   side {side:+d} pt {tuple(round(v,2) for v in c)} on_mesh={nm.on_mesh(*c)} border={nm.border_dist(*c):.2f}")
                for u, v in zip(new, new[1:]):
                    bad = [o2['name'] for o2 in props[mid] if o2['name'] in steer and abs(o2['pos'][1]-u[1]) <= P.DY and P._seg_dist(o2['pos'], u, v) < P.CLEAR*0.9]
                    print(f"      leg clear_line={nm.clear_line(u, v, step=P.LINE_STEP)} props={bad}")
                print(f"   side {side:+d} ok={P._ok(new, nm, [x for x in props[mid] if x['name'] in steer], P.DY)}")

