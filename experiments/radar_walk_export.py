"""레이더 녹화에서 봇 걷기 구간만 잘라 내보내기 — 걷기 하네스 2층 움직임 모델용 ([cloud]는 data/radar/가 없음, ROADMAP 6-a).

  python experiments/radar_walk_export.py [--per 6] [--pad 1.0]

data/radar/*.jsonl에서 `path_tag`가 붙은 연속 snap = 봇 걷기 한 번. 장소별로 걷기를 골라(파일을 고루, 장소마다 --per개)
data/samples/radar_walk_<장소>.jsonl로:
  {"type": "walk", "src", "tag", "t0", "t1", "bot_slot"}   ← 걷기마다 머리 줄, 그 뒤 t0−pad ~ t1+pad 의 기록
  snap (cam_yaw·path·path_tag·player 그대로, chars는 15 m 안 적만) · pad (봇 패드 slot만, 120 Hz) · say (봇 로그 줄)
bot_slot: 그 걷기 동안 스틱을 크게(|lx| 또는 |ly| > 8000) 민 기록이 가장 많은 패드 slot. 사람 패드가 같이 꽂혀 있으면 봇은 1,
  봇 패드만 있으면 0 — 파일마다 다름 (2026-09-30 확인). 못 정하면 그 걷기는 뺌.
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
RADAR, OUT = ROOT / "data" / "radar", ROOT / "data" / "samples"
PLACES = {                                    # 장소 → 걷기 이름(path_tag)
    "passage": ("통로",),                                               # 비밀 통로 입구로 들어가는 길
    "passage_exit": ("통로(귀환)",) + tuple(f"드릴{k} 화톳불로" for k in range(1, 6)),   # 나가는 길 (passage-drill)
    "ramp_top": ("꼭대기로",),
    "storeroom": ("창고 방",),
}
BIG = 8000                                    # 스틱 크게 민 기록 (최대 32767)
CHAR_R = 15.0


def _load(line: str):
    try:
        return json.loads(line)
    except ValueError:
        return None


def scan(f: Path) -> list[dict]:
    """Walks in one recording: [{tag, t0, t1, slot}]."""
    out, cur = [], None
    for line in open(f, encoding="utf-8", errors="replace"):
        head = line[:60]
        if '"type": "pad"' in head:
            m = _load(line)
            if m and cur and max(abs(m.get("lx") or 0), abs(m.get("ly") or 0)) > BIG:
                cur["slots"][m.get("i")] += 1
            continue
        if '"type": "snap"' not in head:
            continue
        m = _load(line)
        if not m:
            continue
        tag = m.get("path_tag") if m.get("path") else None
        if tag is None:
            cur = None
            continue
        if cur is None or cur["tag"] != tag:
            cur = {"tag": tag, "t0": m["rt"], "t1": m["rt"], "slots": Counter()}
            out.append(cur)
        cur["t1"] = m["rt"]
    for w in out:
        w["slot"] = w["slots"].most_common(1)[0][0] if w["slots"] else None
        del w["slots"]
    return out


def pick(found: list[tuple[str, dict]], per: int) -> list[tuple[str, dict]]:
    """Up to `per` walks, spread over files (one per file first, then a second round …), skipping walks under 2 s."""
    by_file = defaultdict(list)
    for src, w in found:
        if w["slot"] is not None and w["t1"] - w["t0"] >= 2.0:
            by_file[src].append(w)
    out, k = [], 0
    while len(out) < per and any(len(v) > k for v in by_file.values()):
        for src in sorted(by_file):
            if len(by_file[src]) > k and len(out) < per:
                out.append((src, by_file[src][k]))
        k += 1
    return out


def cut(f: Path, wins: list[dict], pad: float) -> list[list[dict]]:
    """Records of each window (t0−pad … t1+pad) from one recording, in one pass."""
    got = [[] for _ in wins]
    for line in open(f, encoding="utf-8", errors="replace"):
        m = _load(line)
        if not m or "rt" not in m:
            continue
        for k, w in enumerate(wins):
            if not w["t0"] - pad <= m["rt"] <= w["t1"] + pad:
                continue
            ty = m.get("type")
            if ty == "pad":
                if m.get("i") == w["slot"]:
                    got[k].append(m)
            elif ty == "snap":
                p = m.get("player") or {}
                m = dict(m, chars=[c for c in m.get("chars") or [] if c.get("ptr") != p.get("ptr")
                                   and math.dist((c["x"], c["y"], c["z"]), (p.get("x", 0), p.get("y", 0), p.get("z", 0))) <= CHAR_R])
                got[k].append(m)
            elif ty == "say":
                got[k].append(m)
    return got


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per", type=int, default=6, help="장소마다 걷기 수")
    ap.add_argument("--pad", type=float, default=1.0, help="걷기 앞뒤로 붙일 초")
    a = ap.parse_args()
    files = [f for f in sorted(RADAR.glob("*.jsonl")) if f.stat().st_size > 0]
    found = defaultdict(list)                  # place → [(src, walk)]
    for f in files:
        for w in scan(f):
            for place, tags in PLACES.items():
                if w["tag"] in tags:
                    found[place].append((f.name, w))
    for place in PLACES:
        chosen = pick(found[place], a.per)
        by_src = defaultdict(list)
        for src, w in chosen:
            by_src[src].append(w)
        out = OUT / f"radar_walk_{place}.jsonl"
        with open(out, "w", encoding="utf-8", newline="\n") as fo:
            for src, ws in by_src.items():
                for w, recs in zip(ws, cut(RADAR / src, ws, a.pad)):
                    fo.write(json.dumps({"type": "walk", "src": src, "tag": w["tag"], "t0": w["t0"], "t1": w["t1"],
                                         "bot_slot": w["slot"]}, ensure_ascii=False) + "\n")
                    for r in recs:
                        fo.write(json.dumps(r, ensure_ascii=False) + "\n")
        secs = sum(w["t1"] - w["t0"] for _, w in chosen)
        print(f"{place}: 걷기 {len(chosen)}/{len(found[place])} ({len(by_src)} 파일, {secs:.0f} s) → {out.name} "
              f"({out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
