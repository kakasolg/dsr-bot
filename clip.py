"""Cut a short clip of a bot run out of the OBS recording, to judge the moment together with MoKa (obs_rec.py records it).

  python clip.py <run> <t> [--before 12] [--after 5]     one clip around run time t (the [   t] in the log)
  python clip.py <run> --deaths                          one clip per death_seen event
  python clip.py <run> --list                            which video covers the run, and the offset used

<run> = 20261102_055642_taurus (or a path to its .log). Clips go to ~/Videos/dsr-clips/<run>_t<t>.mp4 (not the repo —
public, and large). Next to each clip it prints the log lines of the same window: what the bot chose there.

Matching: run t = 0 is the log name's local time (1 s steps); the video's start is data/runs/obs_<stamp>.json
(StartRecord answered) or else the video file name (OBS's local start time, 1 s). So a clip is off by up to ~2 s;
the window is wide enough for that.
"""
from __future__ import annotations

import argparse
import datetime as D
import json
import re
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
RUNS = ROOT / "data" / "runs"
VIDEOS = Path.home() / "Videos"
OUT = VIDEOS / "dsr-clips"
LT = re.compile(r"^\[\s*([0-9.]+)\]")


def ffmpeg() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def video_len(p: Path) -> float | None:
    err = subprocess.run([ffmpeg(), "-hide_banner", "-i", str(p)], capture_output=True, text=True,
                         encoding="utf-8", errors="replace").stderr
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err)
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else None


def videos() -> list[tuple[Path, D.datetime, float]]:
    marks = []
    for j in RUNS.glob("obs_*.json"):
        marks.append(D.datetime.fromtimestamp(json.loads(j.read_text(encoding="utf-8"))["start_epoch"]))
    out = []
    for v in VIDEOS.glob("*.mp4"):
        try:
            s = D.datetime.strptime(v.stem, "%Y-%m-%d %H-%M-%S")
        except ValueError:
            continue
        near = [m for m in marks if abs((m - s).total_seconds()) <= 3]
        n = video_len(v)
        if n:
            out.append((v, min(near, key=lambda m: abs((m - s).total_seconds())) if near else s, n))
    return out


def run_of(arg: str) -> tuple[str, D.datetime]:
    name = Path(arg).name.removesuffix(".log")
    return name, D.datetime.strptime(name[:15], "%Y%m%d_%H%M%S")


def cover(t0: D.datetime, t: float):
    at = t0 + D.timedelta(seconds=t)
    for v, s, n in videos():
        off = (at - s).total_seconds()
        if 0 <= off <= n:
            return v, off
    return None, None


def log_window(name: str, a: float, b: float) -> list[str]:
    p = RUNS / f"{name}.log"
    if not p.exists():
        p = ROOT / "data" / "samples" / f"{name}.txt"
    rows = []
    for l in p.read_text(encoding="utf-8", errors="replace").splitlines():
        m = LT.match(l)
        if m and a <= float(m[1]) <= b:
            rows.append(l)
    return rows


def cut(name: str, t0: D.datetime, t: float, before: float, after: float) -> int:
    v, off = cover(t0, t)
    if v is None:
        print(f"t {t:.1f}: no video covers {t0 + D.timedelta(seconds=t):%H:%M:%S}")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    o = OUT / f"{name}_t{t:.0f}.mp4"
    s = max(0.0, off - before)
    subprocess.run([ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{s:.2f}", "-i", str(v),
                    "-t", f"{before + after:.2f}", "-vf", "scale=1280:-2", "-c:v", "libx264", "-preset", "veryfast",
                    "-crf", "26", "-c:a", "aac", "-b:a", "96k", str(o)], check=True)
    print(f"t {t:.1f} → {o}  ({v.name} at {off:.1f} s)")
    for l in log_window(name, t - before, t + after):
        print("   " + l)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("t", nargs="?", type=float)
    ap.add_argument("--before", type=float, default=12.0)
    ap.add_argument("--after", type=float, default=5.0)
    ap.add_argument("--deaths", action="store_true")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    name, t0 = run_of(a.run)
    if a.list:
        v, off = cover(t0, 0.0)
        print(f"{name}: " + (f"{v.name}, run t 0 = video {off:.1f} s" if v else "no video covers the run start"))
        return 0
    ts = [a.t] if a.t is not None else []
    if a.deaths:
        ev = RUNS / f"{name}.jsonl"
        ts = [json.loads(l)["t"] for l in ev.read_text(encoding="utf-8").splitlines() if '"death_seen"' in l]
        if not ts:
            print(f"{name}: no death_seen")
    return max([cut(name, t0, t, a.before, a.after) for t in ts], default=0)


if __name__ == "__main__":
    sys.exit(main())
