"""Open a recorded run as a replay in the Godot room (MoKa M1109-55/56).

  python sim/replay_view.py [<run>] [--at <s>]       default run 20261109_021816_burg-bonfire

Makes data/replays/<run>.json first if it is missing (sim/replay_extract.py). Needs the converted map
(python sim/flver_glb.py --map m10_01_00_00) and the Quaternius models (sim/README.md). Keys: top of sim/godot/replay.gd.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sim import replay_extract                     # noqa: E402
from sim.godot_link import GODOT, ensure_imported                   # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run", nargs="?", default="20261109_021816_burg-bonfire")
    ap.add_argument("--at", type=float, default=None)
    a = ap.parse_args()
    path = replay_extract.OUT / f"{a.run}.json"
    if not path.exists():
        sys.argv = ["replay_extract.py", a.run]
        replay_extract.main()
    ensure_imported()
    exe = GODOT.with_name(GODOT.name.replace("_console", ""))
    args = [str(exe), "--path", str(ROOT / "sim" / "godot"), "res://replay.tscn", "--", f"--replay={path}"]
    if a.at is not None:
        args.append(f"--at={a.at}")
    subprocess.Popen(args)


if __name__ == "__main__":
    main()
