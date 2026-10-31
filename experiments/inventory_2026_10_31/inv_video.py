"""Videos in ~/Videos (OBS record path) vs bot runs and observe recordings by local wall time. Read only. python inv_video.py <repo> <out> <videos_meta.json>"""
import datetime as D, json, re, subprocess, sys
from pathlib import Path
repo, out, meta = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
V = json.loads(meta.read_text(encoding="utf-8-sig"))
def hms(s):
    h, m, x = (int(v) for v in s.split(":")); return h * 3600 + m * 60 + x
LT = re.compile(r"^\[\s*([0-9.]+)\]")
runs = []
for lg in (repo / "data/runs").glob("*.log"):
    try:
        t0 = D.datetime.strptime(lg.name[:15], "%Y%m%d_%H%M%S")
    except ValueError:
        continue
    last = None
    with open(lg, encoding="utf-8", errors="replace") as f:
        for l in f:
            m = LT.match(l)
            if m: last = float(m.group(1))
    if last is not None:
        runs.append((lg.name[:-4], t0, t0 + D.timedelta(seconds=last)))
obs = []
for r in json.loads((out / "observe_list.json").read_text(encoding="utf-8"))["files"]:
    n = Path(r["file"]).stem
    t0 = D.datetime.strptime(n, "%Y%m%d_%H%M%S")
    obs.append((r["file"], t0, t0 + D.timedelta(seconds=r.get("length_s") or 0)))
docs = subprocess.run(["git", "grep", "-l", "-F", "Videos/"], cwd=repo, capture_output=True, text=True).stdout.split()
rows = []
for v in V:
    s = D.datetime.fromisoformat(v["created"]); L = hms(v["length"]); e = s + D.timedelta(seconds=L)
    ov = lambda a, b: (a < e and b > s)
    stem = v["file"][:-4]
    mention = subprocess.run(["git", "grep", "-l", "-F", stem], cwd=repo, capture_output=True, text=True).stdout.split()
    rows.append({"file": f"~/Videos/{v['file']}", "bytes": v["bytes"], "start_local": v["created"], "length_s": L,
                 "resolution": f"{v['w']}x{v['h']}", "fps": re.sub(r"[^0-9.]", "", v["fps"]) or None,
                 "overlapping_bot_runs": sorted(n for n, a, b in runs if ov(a, b)),
                 "overlapping_observe": sorted(n for n, a, b in obs if ov(a, b)),
                 "mentioned_in_repo_files": mention,
                 "sync_marks": "none found in run / observe files; video start known only from file creation time (1 s); on-screen markers not checked"})
(out / "video_list.json").write_text(json.dumps({
    "scope": "~/Videos/*.mp4 (OBS FilePath = ~/Videos; subfolders Captures / NVIDIA / Radeon ReLive hold no video files); files not sent",
    "method": "metadata from Windows shell properties (Length, Frame width/height, Frame rate) and file creation time (local, = OBS start time in the name); "
              "bot run interval = log file name time + last [t] in the log; observe interval = file name time + length_s; overlap = any shared second (clock offsets not corrected)",
    "other": "~/Videos/2026-09-26 18-10-51.en.srt exists (subtitle, not opened)",
    "videos": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
for r in rows: print(r["file"], r["length_s"], r["overlapping_bot_runs"], r["overlapping_observe"], r["mentioned_in_repo_files"])
