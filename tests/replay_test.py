"""Godot scene replay (MoKa M1109-55/56): the room shows each recorded character where the replay file says, at
snapshot times and between them (linear interpolation), and loads the map. Headless; skipped without Godot, the
replay file (data/replays, sim/replay_extract.py) or the converted map (sim/flver_glb.py --map).

Checks the room against the replay file — not the replay file against the game (that is the OBS comparison).

python tests/replay_test.py"""
from __future__ import annotations
import sys as _sys, pathlib as _pl
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8")

import json
import math
import subprocess

from godot_room_test import check
from sim import godot_link as GL

ROOT = _pl.Path(__file__).resolve().parent.parent
RUN = "20261109_021816_burg-bonfire"
REPLAY = ROOT / "data" / "replays" / f"{RUN}.json"
MAP = ROOT / "sim" / "godot" / "assets" / "m10_01_00_00.glb"


def expected(rp: dict, key: str, t: float):
    """Same rule as replay.gd sample(): last snapshot at or before t, lerp to the next if the character is in both."""
    ts = [f["t"] for f in rp["frames"]]
    i = max(0, max((k for k, x in enumerate(ts) if x <= t), default=0))
    row = lambda j: rp["frames"][j]["p"] if key == "p" else rp["frames"][j]["c"].get(key)
    a = row(i)
    if a is None:
        return None
    b = row(i + 1) if i + 1 < len(ts) else None
    if b is None or t <= ts[i]:
        return a
    u = min(max((t - ts[i]) / max(ts[i + 1] - ts[i], 1e-6), 0.0), 1.0)
    dh = (b[3] - a[3] + math.pi) % (2 * math.pi) - math.pi
    return [a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u, a[2] + (b[2] - a[2]) * u, a[3] + dh * u, a[4], a[5]]


def main() -> None:
    for need, what in ((GL.GODOT, "Godot"), (REPLAY, "replay file"), (MAP, "converted map")):
        if not need.exists():
            print(f"skip: {what} not found at {need}")
            return
    rp = json.loads(REPLAY.read_text(encoding="utf-8"))
    fights = rp["fights"]
    ts = [f["t"] for f in rp["frames"]]
    # snapshot times, midpoints inside each of the first six fights, and a hit
    times = [ts[5], ts[400]]
    for fg in fights[:6]:
        i = next(k for k, x in enumerate(ts) if x >= fg["t"] + 1.0)
        times += [ts[i], round((ts[i] + ts[i + 1]) / 2, 4)]
    times.append(rp["hits"][0]["t"])
    r = subprocess.run([str(GL.GODOT), "--headless", "--path", str(ROOT / "sim" / "godot"), "res://replay.tscn", "--",
                        "--dump=" + ",".join(str(x) for x in times)], capture_output=True, text=True, encoding="utf-8",
                       timeout=300)
    line = next((x for x in r.stdout.splitlines() if x.startswith("REPLAY_DUMP ")), None)
    check("replay scene loads and answers the dump", line is not None)
    got = json.loads(line[len("REPLAY_DUMP "):])
    for glb in sorted(MAP.parent.glob("m??_??_00_00.glb")):
        gl = glb.read_bytes()
        n_json = int.from_bytes(gl[12:16], "little")
        prims = sum(len(m["primitives"]) for m in json.loads(gl[20:20 + n_json])["meshes"])
        shown = got[0]["map_surfaces"].get(glb.stem)
        check(f"map {glb.stem} loaded whole: {shown} surfaces of the glb's {prims} (Godot drops past 256 per mesh)",
              shown == prims)
    worst, missing, extra, n = 0.0, [], [], 0
    for g in got:
        t = g["t"]
        want = {}
        for key in ["p", *rp["chars"].keys()]:
            e = expected(rp, key, t)
            if e is None:
                continue
            before = expected(rp, key, t - 2.0)          # replay.gd DEATH_SHOW
            if key == "p" or e[5] > 0 or (before is not None and before[5] > 0):
                want[key] = e
        missing += [(t, k) for k in want if k not in g["chars"]]
        extra += [(t, k) for k in g["chars"] if k not in want]
        for k, e in want.items():
            if k in g["chars"]:
                p = g["chars"][k]
                worst = max(worst, math.dist(p[:3], e[:3]))
                n += 1
    check(f"every recorded character shown, none extra ({n} positions over {len(got)} times)",
          not missing and not extra)
    check(f"positions match the replay file (worst {worst * 100:.1f} cm, rounding 1 mm)", worst < 0.01)
    print("replay_test: 전부 통과")


if __name__ == "__main__":
    main()
