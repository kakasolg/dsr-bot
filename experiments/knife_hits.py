"""Light-attack reach from black-box recordings (data/runs/*.hits.jsonl) — no game needed.

  python experiments/knife_hits.py [anim_lo anim_hi]     (default 203000 203999 = dagger light attacks)

For each swing (my anim in range and stamina drops = blade out), every foe within 3 m: its distance at that moment, and
whether its HP dropped within 0.25 s (active window 0.34~0.46 s after R1 → blade-out +0.12 s, with margin).

── 이 측정의 한계 ──────────────────────────────
 · 블랙박스는 내가 크게 맞은 앞뒤만 남아서 표본이 한쪽으로 쏠림 (싸움이 꼬인 장면)
 · 3 m 안의 적을 모두 세므로, 0.85 m 에서 "빗나감" 은 대개 옆에 붙은 다른 적 (휘두른 대상이 아님)
 · 거리는 적 중심까지 — 0.85 m 부근이 몸끼리 붙은 한계
"""
import collections
import glob
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

RUNS = Path(__file__).resolve().parent.parent / "data" / "runs"
HIT_WINDOW = 0.25


def main():
    lo, hi = (int(sys.argv[1]), int(sys.argv[2])) if len(sys.argv) > 2 else (203000, 203999)
    seen = set()
    rows = []   # (run, d at blade-out, hit, dmg, dy, face, anim, d at HP drop)
    for f in sorted(glob.glob(str(RUNS / "*.hits.jsonl"))):
        for line in open(f, encoding="utf-8"):
            try:
                r = json.loads(line)
            except Exception:
                continue
            fr = r.get("frames") or []
            for i in range(1, len(fr)):
                a, b = fr[i - 1], fr[i]
                if not (lo <= (b.get("anim") or -1) <= hi) or a.get("sp") is None or b.get("sp") is None:
                    continue
                if not b["sp"] < a["sp"] - 5:
                    continue
                key = round(b["t"], 2)             # the same swing appears in overlapping black-box windows
                if key in seen:
                    continue
                seen.add(key)
                for foe in b.get("foes", []):
                    if foe.get("d") is None or foe["d"] > 3.0:
                        continue
                    hit, d_hit = 0, None
                    for c in fr[i:]:
                        if c["t"] - b["t"] > HIT_WINDOW:
                            break
                        for g in c.get("foes", []):
                            if g["ptr"] == foe["ptr"] and g["hp"] < foe["hp"]:
                                hit = max(hit, foe["hp"] - g["hp"])
                                d_hit = g["d"] if d_hit is None else d_hit
                    rows.append((Path(f).name[:15], foe["d"], hit > 0, hit, foe.get("dy"), foe.get("face"), b["anim"], d_hit))

    print("runs:", sorted({r[0] for r in rows}))
    print("swing × foe pairs:", len(rows), " anims:", dict(collections.Counter(r[6] for r in rows)))
    bucket = collections.defaultdict(lambda: [0, 0])
    for r in rows:
        k = round(r[1] * 5) / 5
        bucket[k][0] += 1
        bucket[k][1] += r[2]
    for k in sorted(bucket):
        n, h = bucket[k]
        print(f"  {k:.1f} m: {h}/{n}")
    far = [(round(r[1], 2), round(r[7], 2)) for r in rows if r[2] and r[1] > 1.2]
    print("hits beyond 1.2 m (d at blade-out → d at HP drop):", far)


if __name__ == "__main__":
    main()
