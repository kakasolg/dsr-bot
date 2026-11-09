"""Taurus: when is an in-fight Estus sip safe? (P-142 follow-up, [cloud] 2026-11-09) — read-only, game not needed.

  python experiments/taurus_sip_check.py

Three tables, all from files already in the repo:
  1. TAE (data/gamefiles/tae.json, c2250) active windows per 3000-series anim vs souls/taurus.py HIT_AT (blackbox, runtime)
  2. attacks that started while we were drinking (taurus_report.py instances, me == 에스트): distance at start, hit or not
  3. every in-fight sip in data/samples/*_taurus*.jsonl and whether a hit landed during it / just after
Evidence: 1 = file (TAE) next to runtime (blackbox); 2 and 3 = runtime (bot runs), distance = at the attack's start.
"""
from __future__ import annotations

import glob
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SIP_S = 2.6          # drink(): ~0.4 s select + 2.2 s wait; the estus event is written at the end
AFTER_S = 2.0        # a hit this long after the sip ended still counts (the swing started during it)


def tae_table():
    from souls.taurus import HIT_AT
    tae = json.load(open(ROOT / "data/gamefiles/tae.json", encoding="utf-8"))["models"]["c2250"]["animations"]
    print("1. TAE 공격 판정 구간 (c2250) vs HIT_AT (블랙박스)")
    print("   애니  첫 판정 시작  마지막 판정 끝  HIT_AT  차이")
    for a in range(3000, 3010):
        ev = [e for e in tae.get(str(a), {}).get("events", []) if e["type"] in (1, 2)]
        if not ev:
            continue
        first, last = min(e["start"] for e in ev), max(e["end"] for e in ev)
        h = HIT_AT.get(a)
        d = "" if h is None else f"{h - first:+.2f}"
        print(f"   {a}  {first:10.2f}  {last:12.2f}  {'' if h is None else f'{h:6.2f}'}  {d}")


def estus_start_attacks():
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "tr.json"
        subprocess.run([sys.executable, str(ROOT / "taurus_report.py"), "--json", str(out)], cwd=ROOT,
                       capture_output=True, check=True)
        d = json.load(open(out, encoding="utf-8"))
    e = sorted((x["h"], x["anim"], x["dmg"]) for x in d if x["me"] == "에스트")
    print(f"\n2. 내가 에스트 중일 때 시작한 보스 공격: {len(e)}번, 맞음 {sum(1 for x in e if x[2] > 0)}번")
    print("   시작 거리 m (애니, 피해): " + " · ".join(f"{h:.2f} ({a}, {g})" for h, a, g in e))
    for lo, hi in ((0, 3), (3, 5), (5, 8), (8, 99)):
        xs = [x for x in d if lo <= x["h"] < hi and 3000 <= x["anim"] <= 3006]
        print(f"   3000–3006 시작 거리 {lo}–{hi} m: 맞음 {sum(1 for x in xs if x['dmg'] > 0)}/{len(xs)}")


def sips():
    tot = hit = 0
    print("\n3. 싸움 중 에스트 (data/samples): 끝난 시각, HP 전→후, 그 사이·직후 맞은 것")
    for f in sorted(glob.glob(str(ROOT / "data/samples/*_taurus*.jsonl"))):
        if f.endswith(".track.jsonl"):
            continue
        ev = [json.loads(line) for line in open(f, encoding="utf-8")]
        hits = [e for e in ev if e.get("ev") == "hit"]
        for e in ev:
            if e.get("ev") != "estus" or not e.get("ok"):
                continue
            t1 = e["t"]
            hh = [x for x in hits if t1 - SIP_S - 0.2 <= x["t"] <= t1 + AFTER_S]
            tot += 1
            hit += bool(hh)
            if hh:
                b = [(x["lost"], (x.get("blame") or [{}])[0].get("anim"), (x.get("blame") or [{}])[0].get("d")) for x in hh]
                print(f"   {Path(f).name[:15]} {t1:6.1f} s  HP {e.get('hp')}  맞음 {b}")
    print(f"   전부 {tot}번 (싸움 전 마신 것 포함), 마시는 중·직후 {AFTER_S} s 안에 맞음 {hit}번")


if __name__ == "__main__":
    tae_table()
    estus_start_attacks()
    sips()
