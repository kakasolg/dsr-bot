"""Combo judging set — MoKa judges the bot's technique choices on video clips, together with Claude (MoKa 11-02:
"같은 동영상을 보고 평가 하라고 하면 할 수 있는데, 나중에 하라고 하면, 나도 판단 하기 힘들어"). No training, nothing reaches the bot.

  python combo_judge.py build [--runs r1,r2,...]   pick scenes from Claymore burg-upper logs → data/labels/combo_scenes.jsonl,
                                                    clips → ~/Videos/dsr-clips/judge/<id>.mp4 (not the repo — public, large)
  python combo_judge.py show <id>                  what MoKa sees before judging (no bot verdict, plan or reason)
  python combo_judge.py label <id> --choice right|wrong|unsure [--better T] [--timing ok|early|late|unsure]
                              [--seen hit|kill|whiff|trade|got_hit|unclear] [--conf low|mid|high] [--note "MoKa 말"]  (omitted = not said)
  python combo_judge.py reveal <id>                after the first label: the bot's own verdict and the log window
  python combo_judge.py report                     labeled / revealed counts, MoKa's "seen" vs the bot's verdict

Labels: data/labels/combo_labels.jsonl, label_source "human_verified", one line per save (the last per scene counts).
A label written after `reveal` for that scene is stage "post_reveal" — kept, but not the blind first judgement.
The bot's verdict ("성공 / 실패 / 헛침") is the rules' own reading of the log, so it stays hidden until MoKa has judged
(decision_models.md §12.4-2). Clip matching is clip.py's: run t 0 = log name time, video start = obs_<stamp>.json, ±2 s.
"""
from __future__ import annotations

import argparse
import collections
import datetime as D
import hashlib
import json
import re
import sys
from pathlib import Path

import clip as C

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
LABELS = ROOT / "data" / "labels"
SCENES = LABELS / "combo_scenes.jsonl"
LABEL_FILE = LABELS / "combo_labels.jsonl"
REVEALS = LABELS / "combo_reveals.jsonl"
OUT = C.VIDEOS / "dsr-clips" / "judge"
SCENE_SCHEMA, LABEL_SCHEMA = "dsr-combo-scene/0.1", "dsr-combo-label/0.1"

# 11-04 클레이모어 세이브 (backup-20261104-073131-firelink-claymore-hp1018) 4번 — 같은 무기·레벨·코드 계열
RUNS = ["20261104_075710_burg-upper", "20261104_081156_burg-upper", "20261104_083206_burg-upper",
        "20261104_095201_burg-upper"]

TECH = ("backstep_combo", "jump", "backstab", "kick", "roll_combo", "light", "guard", "backstep", "roll_away",
        "wait", "retreat", "knife", "none")
CHOICE, TIMING = ("right", "wrong", "unsure"), ("ok", "early", "late", "unsure")
SEEN = ("hit", "kill", "whiff", "trade", "got_hit", "unclear")
CONF = ("low", "mid", "high")

MOVE_KO = {"backstep_r1": "백스텝 콤보", "jump_r2": "점프 공격", "roll_r1": "구르기 콤보", "kick_combo": "발차기 콤보",
           "light": "약공", "없음": "안 침"}

LT = re.compile(r"^\[\s*([0-9.]+)\]")
COMBO = re.compile(r"^\[\s*([0-9.]+)\]\s+(콤보|진입) \[([^\]]*)\] ([0-9.]+) m.*?→ (\S+)(?: \(계획 [^)]*\))?: (\S+)")
ZONE = re.compile(r"구역(\d+)(?:-\d+)?")

# 종류별 몇 개 — 실패·드문 것은 다, 흔한 성공은 몇 개만 (전체 ~120 중 ~28)
QUOTA = {"combo:backstep_r1:성공": 4, "combo:backstep_r1:실패": 9, "entry:jump_r2:성공": 3, "entry:jump_r2:실패": 9,
         "combo:roll_r1": 9, "combo:kick_combo": 1, "combo:light:성공": 3, "combo:light:실패": 3, "combo:light:불명": 1,
         "entry:없음": 1, "stab": 3, "guard_wait": 2, "far_guard": 2}
# 판정 줄은 공격이 끝난 뒤 찍힘 → 앞쪽을 길게; 가드 줄은 시작에 찍힘 → 뒤쪽을 길게
WINDOW = {"combo": (7.0, 2.0), "entry": (6.0, 2.0), "stab": (6.0, 2.0), "guard_wait": (2.0, 9.0), "far_guard": (2.0, 9.0)}   # MoKa 10번: 가드만 보여 다음 공격을 모름 → 뒤를 9 s로


def log_lines(run: str) -> list[str]:
    p = C.RUNS / f"{run}.log"
    if not p.exists():
        p = ROOT / "data" / "samples" / f"{run}.txt"
    return p.read_text(encoding="utf-8", errors="replace").splitlines()


def candidates(run: str) -> list[dict]:
    out, zone = [], None
    for l in log_lines(run):
        z = ZONE.search(l)
        if z and "구역" in l[:30]:
            zone = int(z[1])
        m = LT.match(l)
        if not m:
            continue
        t = float(m[1])
        c = COMBO.match(l)
        if c:
            kind = "combo" if c[2] == "콤보" else "entry"
            move, verdict = c[5], c[6]
            key = f"{kind}:{move}:{verdict}"
            if f"{kind}:{move}" in QUOTA:
                key = f"{kind}:{move}"
            if move == "없음":
                key = "entry:없음"
            dist = float(c[4])
            shown = f"봇이 {MOVE_KO.get(move, move)} ({move}) — 그때 거리 {dist} m, 칸 [{c[3]}]"
            out.append(dict(kind=kind, key=key, t=t, zone=zone, move=move, dist=dist, shown=shown, hidden=l.strip()))
        elif "뒤잡기 → stabbed" in l:
            out.append(dict(kind="stab", key="stab", t=t, zone=zone, move="backstab", dist=None,
                            shown="봇이 뒤잡기 (backstab)", hidden=l.strip()))
        elif "휘두르는 중 (" in l:
            out.append(dict(kind="guard_wait", key="guard_wait", t=t, zone=zone, move="guard", dist=None,
                            shown="봇이 콤보 안 하고 가드 들고 기다림 (휘두르는 적 앞, P-128)", hidden=l.strip()))
        elif "넘음, 가드" in l:
            out.append(dict(kind="far_guard", key="far_guard", t=t, zone=zone, move="guard", dist=None,
                            shown="봇이 휘두름 백스텝 콤보 대신 가드 (1.8 m 넘음, P-130)", hidden=l.strip()))
    return out


def scene_id(run: str, t: float, kind: str) -> str:
    return hashlib.sha1(f"{run}|{t:.1f}|{kind}".encode()).hexdigest()[:10]


def pick(runs: list[str]) -> list[dict]:
    by = collections.defaultdict(list)
    for r in runs:
        for c in candidates(r):
            c["run"] = r
            by[c["key"]].append(c)
    chosen: list[dict] = []
    for key, n in QUOTA.items():
        pool = by.get(key, [])
        if key == "combo:light:성공":
            pool = sorted(pool, key=lambda c: "안 지킴" not in c["hidden"])     # 계획 안 지킨 약공 먼저
        # 실행마다 고르게: 실행 순서대로 번갈아 뽑음 (무작위 아님 — 다시 만들어도 같은 셋)
        rr = collections.defaultdict(list)
        for c in pool:
            rr[c["run"]].append(c)
        order = []
        while any(rr.values()):
            for r in runs:
                if rr[r]:
                    order.append(rr[r].pop(0))
        for c in order:
            if sum(1 for x in chosen if x["key"] == key) >= n:
                break
            if any(x["run"] == c["run"] and abs(x["t"] - c["t"]) < 4.0 for x in chosen):
                continue          # 클립이 겹치면 하나만
            chosen.append(c)
    return sorted(chosen, key=lambda c: (c["run"], c["t"]))


def ctl_scenes(run: str, t0: D.datetime, a: float, b: float) -> list[dict]:
    """The bot's own scene records (dsr-scene-input) inside the clip window — the model-side input for later."""
    p = C.RUNS / f"{run}.ctl.jsonl"
    if not p.exists():
        return []
    e0, out = t0.timestamp(), []
    for i, l in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if '"k": "scene"' not in l:
            continue
        tr = json.loads(l)["t_wall"] - e0
        if a <= tr <= b:
            out.append({"line": i, "t": round(tr, 2)})
    return out


def build(runs: list[str]) -> int:
    import subprocess
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for c in pick(runs):
        t0 = C.run_of(c["run"])[1]
        before, after = WINDOW[c["kind"]]
        sid = scene_id(c["run"], c["t"], c["kind"])
        v, off = C.cover(t0, c["t"])
        clip = None
        if v is not None:
            o = OUT / f"{sid}.mp4"
            if not o.exists():
                subprocess.run([C.ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{max(0.0, off - before):.2f}",
                                "-i", str(v), "-t", f"{before + after:.2f}", "-vf", "scale=1280:-2", "-c:v", "libx264",
                                "-preset", "veryfast", "-crf", "26", "-an", str(o)], check=True)
            clip = str(o)
        rows.append({"schema": SCENE_SCHEMA, "scene_id": sid, "run": c["run"], "t": c["t"], "kind": c["kind"],
                     "key": c["key"], "zone": c["zone"], "move": c["move"], "dist": c["dist"],
                     "clip": clip, "video": v.name if v else None, "video_at": round(off, 1) if v else None,
                     "window": [round(c["t"] - before, 1), round(c["t"] + after, 1)],
                     "shown": c["shown"], "hidden": {"verdict_line": c["hidden"],
                                                     "log": C.log_window(c["run"], c["t"] - before, c["t"] + after)},
                     "ctl_scenes": ctl_scenes(c["run"], t0, c["t"] - before, c["t"] + after)})
        print(f"{sid}  {c['run'][:15]} t {c['t']:6.1f}  {c['key']:24s} {'clip ok' if clip else 'NO VIDEO'}")
    SCENES.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    print(f"{len(rows)} scenes → {SCENES}  ({sum(1 for r in rows if r['clip'])} clips in {OUT})")
    return 0


def scenes() -> dict[str, dict]:
    return {r["scene_id"]: r for r in map(json.loads, SCENES.read_text(encoding="utf-8").splitlines())}


def jl(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()] if p.exists() else []


def show(sid: str) -> int:
    s = scenes()[sid]
    order = list(scenes()).index(sid) + 1
    print(f"[{order}/{len(scenes())}] {sid} — {s['run'][:15]} 구역 {s['zone']}, 실행 {s['window'][0]}–{s['window'][1]} s")
    print(f"  {s['shown']}")
    print(f"  클립: {s['clip']}")
    print("  물음: 기술 선택 맞나 (아니면 뭐가 나았나) · 타이밍 · 화면에 보인 결과")
    return 0


def label(a) -> int:
    s = scenes()[a.id]
    if a.choice == "wrong" and not a.better:
        print("--choice wrong needs --better")
        return 1
    stage = "post_reveal" if any(r["scene_id"] == a.id for r in jl(REVEALS)) else "pre_reveal"
    row = {"schema": LABEL_SCHEMA, "scene_id": a.id, "label_source": "human_verified", "labeler_id": "MoKa",
           "labeled_at": D.datetime.now().astimezone().isoformat(timespec="seconds"), "stage": stage,
           "bot_move": s["move"], "choice": a.choice, "better": a.better, "timing": a.timing, "seen": a.seen,
           "confidence": a.conf, "note": a.note, "recorded_by": "claude (MoKa가 채팅으로 답한 것을 옮김)"}
    with LABEL_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"{a.id}: {stage} label saved")
    return 0


def reveal(sid: str) -> int:
    s = scenes()[sid]
    if not any(r["scene_id"] == sid for r in jl(LABEL_FILE)):
        print(f"{sid}: no label yet — judge first (the reveal makes later labels post_reveal)")
        return 1
    with REVEALS.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"scene_id": sid, "at": D.datetime.now().astimezone().isoformat(timespec="seconds")}) + "\n")
    print(s["hidden"]["verdict_line"])
    for l in s["hidden"]["log"]:
        print("   " + l)
    return 0


def report() -> int:
    sc, last = scenes(), {}
    for r in jl(LABEL_FILE):
        if r["stage"] == "pre_reveal":
            last[r["scene_id"]] = r
    rev = {r["scene_id"] for r in jl(REVEALS)}
    print(f"scenes {len(sc)} · blind labels {len(last)} · revealed {len(rev)}")
    by = collections.Counter((sc[k]["key"], r["choice"]) for k, r in last.items())
    for (key, ch), n in sorted(by.items()):
        print(f"  {key:24s} {ch:7s} {n}")
    vs = collections.Counter()
    for k, r in last.items():
        m = re.search(r"\): (\S+)|: (\S+) —", sc[k]["hidden"]["verdict_line"])
        vs[(m and (m[1] or m[2]), r["seen"])] += 1
    if vs:
        print("  bot verdict × MoKa seen:")
        for (v, s), n in sorted(vs.items(), key=str):
            print(f"    {v} × {s}: {n}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    b = sp.add_parser("build")
    b.add_argument("--runs", default=",".join(RUNS))
    sp.add_parser("show").add_argument("id")
    sp.add_parser("reveal").add_argument("id")
    sp.add_parser("report")
    lb = sp.add_parser("label")
    lb.add_argument("id")
    lb.add_argument("--choice", choices=CHOICE, required=True)
    lb.add_argument("--better", choices=TECH)
    lb.add_argument("--timing", choices=TIMING)            # MoKa가 말 안 한 칸은 비워 둠 (채우지 않음)
    lb.add_argument("--seen", choices=SEEN)
    lb.add_argument("--conf", choices=CONF)
    lb.add_argument("--note", default="")
    a = ap.parse_args()
    if a.cmd == "build":
        return build(a.runs.split(","))
    if a.cmd == "show":
        return show(a.id)
    if a.cmd == "reveal":
        return reveal(a.id)
    if a.cmd == "report":
        return report()
    return label(a)


if __name__ == "__main__":
    sys.exit(main())
