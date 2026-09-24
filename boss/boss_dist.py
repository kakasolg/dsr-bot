"""데몬 거리 분석 — 모든 boss_*.json (반지름 R 열이 있는 판) 을 모아 R 별로:
시간, 맞은 피해/분, 내가 준 피해/분, 데몬 공격 수·맞음·헛침, 실제 거리 평균."""
import collections, glob, json, os, sys
sys.stdout.reconfigure(encoding="utf-8")
agg = collections.defaultdict(lambda: collections.Counter())
dist_sum = collections.defaultdict(float)
files = sorted(glob.glob(r"D:/dev/chzzk-souls-chaos/bot/data/trace/boss_*.json"), key=os.path.getmtime)
for f in files:
    J = json.load(open(f, encoding="utf-8"))
    if not isinstance(J, dict):
        continue
    F = J["fine"]
    F = [r for r in F if len(r) > 10 and r[9] is not None]
    if not F:
        continue
    for a, b in zip(F, F[1:]):
        R = a[9]; dt = b[0] - a[0]
        if dt > 1.0:
            continue
        c = agg[R]
        c["초"] += dt
        dist_sum[R] += a[6] * dt
        c[f"모드초:{a[10]}"] += dt
        if b[1] < a[1] - 20:
            c["맞은피해"] += a[1] - b[1]; c["맞은횟수"] += 1
            c[f"맞음@{a[10]}"] += 1
        if a[4] is not None and b[4] is not None and b[4] < a[4]:
            c["준피해"] += a[4] - b[4]
    # 데몬 공격 한 번 한 번: 그 동안 내가 맞았나
    last = None; seg = []
    for i, r in enumerate(F):
        if r[5] != last:
            if last is not None and 3000 <= last < 3100 and last not in (3020, 3022):
                seg.append((i0, i))
            last, i0 = r[5], i
    for i0, i1 in seg:
        part = F[i0:i1]; R = part[0][9]
        hit = any(q[1] < p_[1] - 20 for p_, q in zip(part, part[1:]))
        agg[R]["데몬공격"] += 1
        agg[R]["공격맞음" if hit else "공격헛침"] += 1
print(f"{'R':>4} {'초':>6} {'평균거리':>7} {'맞은피해/분':>9} {'준피해/분':>8} {'공격':>4} {'맞음%':>6}  맞은 때 모드")
for R in sorted(agg):
    c = agg[R]; m = c["초"] / 60 or 1
    hitpct = 100 * c["공격맞음"] / max(1, c["데몬공격"])
    modes = {k[3:]: v for k, v in c.items() if k.startswith("맞음@")}
    print(f"{R:>4} {c['초']:6.0f} {dist_sum[R] / max(1, c['초']):7.1f} {c['맞은피해'] / m:9.0f} {c['준피해'] / m:8.0f} {c['데몬공격']:4d} {hitpct:6.0f}  {modes}")
