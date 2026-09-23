"""
톰슨 샘플링 — 몇 개 안 되는 선택지(전술) 중 하나를 판마다 고르고, 판 결과(0..1 보상)로 믿음을 고친다. 게임을 모른다.

  python bandit.py report <파일>      지금까지의 기록으로 선택지별 사후 분포 요약 (평균·90 % 구간·최선일 확률)
  python bandit.py sim                가짜 선택지로 수렴하는지 자체 점검 (게임 불필요)

각 선택지의 "잘 되는 정도"를 Beta(α, β) 로 믿고, 판마다 선택지별로 한 번씩 뽑아 가장 큰 것을 고른다.
결과 r ∈ [0, 1] 은 α += r, β += 1 − r 로 반영한다 (성공/실패만 있으면 보통의 베르누이 밴딧과 같다).
예전 방식(안 해 본 것 먼저 → 성적 최고 + 20 % 무작위)과 다른 점: 판이 적을 땐 알아서 골고루, 쌓일수록
나은 쪽으로 몰린다. 탐색 비율을 손으로 정하지 않는다.

── 알려진 한계 ──────────────────────────────
 · 봇 코드가 바뀌면 옛 기록은 다른 봇의 성적이다 (예: 돌아서기 버그를 고치면 fight 성적이 달라진다).
   그래서 판마다 git 커밋(rev)을 남긴다 — `since_rev` 로 그 커밋 이후 기록만 쓸 수 있다.
 · 선택지끼리 독립이라고 본다. "폭탄 전술이 잘 되면 fight 도 잘 될 것" 같은 공유는 없다.
"""
from __future__ import annotations

import json
import math
import random
import subprocess
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def git_rev() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=Path(__file__).resolve().parent,
                              capture_output=True, text=True, timeout=5).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


class Thompson:
    def __init__(self, arms: list[str], path: Path, prior: tuple[float, float] = (1.0, 1.0),
                 since_rev: str | None = None, rng: random.Random | None = None):
        self.arms = list(arms)
        self.path = Path(path)
        self.prior = prior
        self.since_rev = since_rev
        self.rng = rng or random.Random()
        self.history: list[dict] = []
        if self.path.exists():
            self.history = json.loads(self.path.read_text(encoding="utf-8")).get("history", [])

    def _used(self) -> list[dict]:
        """since_rev 가 있으면 그 커밋이 처음 나온 판부터만 쓴다."""
        if not self.since_rev:
            return self.history
        start = next((i for i, h in enumerate(self.history) if h.get("rev") == self.since_rev), len(self.history))
        return self.history[start:]

    def posterior(self) -> dict[str, tuple[float, float, int]]:
        post = {a: [self.prior[0], self.prior[1], 0] for a in self.arms}
        for h in self._used():
            if h["arm"] in post:
                r = min(1.0, max(0.0, float(h["reward"])))
                post[h["arm"]][0] += r
                post[h["arm"]][1] += 1.0 - r
                post[h["arm"]][2] += 1
        return {a: tuple(v) for a, v in post.items()}

    def pick(self) -> tuple[str, dict[str, float]]:
        """선택지와, 이번에 뽑힌 값들 (기록·로그용)."""
        draws = {a: self.rng.betavariate(al, be) for a, (al, be, _n) in self.posterior().items()}
        return max(draws, key=draws.get), draws

    def record(self, arm: str, reward: float, **extra) -> None:
        self.history.append({"t": round(time.time(), 1), "arm": arm, "reward": round(float(reward), 4), "rev": git_rev(), **extra})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"arms": self.arms, "prior": list(self.prior), "history": self.history},
                                        ensure_ascii=False, indent=1), encoding="utf-8")

    def report(self, draws: int = 20000) -> list[dict]:
        """선택지별 n, 평균, 90 % 신용구간, 최선일 확률 (몬테카를로)."""
        post = self.posterior()
        rng = random.Random(0)
        best = {a: 0 for a in self.arms}
        samples = {a: [] for a in self.arms}
        for _ in range(draws):
            d = {a: rng.betavariate(al, be) for a, (al, be, _n) in post.items()}
            best[max(d, key=d.get)] += 1
            for a, v in d.items():
                samples[a].append(v)
        out = []
        for a, (al, be, n) in post.items():
            s = sorted(samples[a])
            out.append({"arm": a, "n": n, "mean": al / (al + be), "lo": s[int(0.05 * draws)], "hi": s[int(0.95 * draws) - 1],
                        "p_best": best[a] / draws})
        return out

    def format_report(self) -> str:
        rows = [f"  {'선택지':<14} {'판':>3} {'평균':>6} {'90% 구간':>14} {'최선일 확률':>10}"]
        for r in sorted(self.report(), key=lambda r: -r["p_best"]):
            rows.append(f"  {r['arm']:<14} {r['n']:>3} {r['mean']:6.2f} {r['lo']:6.2f} ~ {r['hi']:4.2f} {r['p_best']:10.0%}")
        return "\n".join(rows)


# 가짜 환경: 전술 → (성공 확률, 실패했을 때 진행도 평균). 하나에 맞추면 자기 맞춤이라 성격이 다른 셋을 본다.
SIM_TRUTHS = {
    "A 기본": {"fight": (0.10, 0.35), "bomb_stop": (0.30, 0.55), "bomb_sprint": (0.20, 0.45), "sprint": (0.05, 0.60)},
    "B 전부 낮음": {"fight": (0.02, 0.30), "bomb_stop": (0.08, 0.50), "bomb_sprint": (0.05, 0.40), "sprint": (0.00, 0.45)},
    "C 진행도 함정": {"fight": (0.15, 0.30), "bomb_stop": (0.25, 0.35), "bomb_sprint": (0.10, 0.50), "sprint": (0.00, 0.75)},
}


def _sim(runs: int = 100, seeds: int = 300, lams=(0.8, 0.5, 0.25, 0.1, 0.0)) -> None:
    """톰슨(실패 보상 = λ × 진행도)과 예전 방식(안 해 본 것 → 성공×2+진행도 최고, 20 % 무작위)을 100판 성공 수로 비교."""
    import statistics as st

    def outcome(rng, truth, arm):
        p, prog = truth[arm]
        if rng.random() < p:
            return True, 1.0
        return False, min(0.99, max(0.0, rng.gauss(prog, 0.15)))

    def run_ts(truth, lam, seed):
        rng = random.Random(seed)
        ts = Thompson(list(truth), Path("__sim_never_written__.json"), rng=random.Random(seed + 10_000))
        wins = 0
        for _ in range(runs):
            a, _ = ts.pick()
            ok, prog = outcome(rng, truth, a)
            wins += ok
            ts.history.append({"arm": a, "reward": 1.0 if ok else lam * prog})   # 파일 쓰기 없이
        return wins

    def run_old(truth, seed):
        rng = random.Random(seed)
        stats = {a: [0, 0, 0.0] for a in truth}
        wins = 0
        for _ in range(runs):
            untried = [a for a in truth if stats[a][0] == 0]
            if untried:
                a = untried[0]
            elif rng.random() < 0.2:
                a = rng.choice(list(truth))
            else:
                a = max(truth, key=lambda a: stats[a][1] / stats[a][0] * 2 + stats[a][2] / stats[a][0])
            ok, prog = outcome(rng, truth, a)
            wins += ok
            stats[a][0] += 1
            stats[a][1] += ok
            stats[a][2] += 1.0 if ok else prog   # merchantrun 은 성공하면 진행도 1.0
        return wins

    print(f"{'':<14}" + "".join(f"{k:>16}" for k in SIM_TRUTHS) + f"   ({runs}판 성공 수 중앙값 [하위 10 %], 반복 {seeds})")

    def row(name, f):
        cells = []
        for tr in SIM_TRUTHS.values():
            w = sorted(f(tr, s) for s in range(seeds))
            cells.append(f"{st.median(w):>10.0f} [{w[seeds // 10]:>2}]")
        print(f"{name:<14}" + "".join(f"{c:>16}" for c in cells))

    row("예전(20%탐색)", run_old)
    for lam in lams:
        row(f"톰슨 λ={lam}", lambda tr, s, lam=lam: run_ts(tr, lam, s))
    print(f"{'이상적':<14}" + "".join(f"{max(p for p, _ in tr.values()) * runs:>16.0f}" for tr in SIM_TRUTHS.values()))


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "sim":
        _sim()
    elif len(sys.argv) >= 3 and sys.argv[1] == "report":
        doc = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
        print(Thompson(doc["arms"], Path(sys.argv[2]), prior=tuple(doc.get("prior", (1, 1)))).format_report())
    else:
        print(__doc__)
