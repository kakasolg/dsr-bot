"""
에피소드 학습 루프 — 순찰 → (방해) → 사망/시간종료 → 복기 → 플레이북 수정 → 평가/롤백.

  python learn.py <route> --episodes 10 [--max-seconds 240] [--harass-interval 20] [--seed-base 1000]

규칙 (트레이딩의 워크포워드와 같은 규율):
  · 한 번 죽었다고 바꾸지 않는다: 같은 제안이 EVIDENCE 회 이상 누적돼야 적용
  · 새 버전으로 EVAL_EPISODES 개를 뛴 뒤, 생존시간 중앙값이 직전 버전의 ROLLBACK_RATIO 배 미만이면 롤백하고 그 제안은 rejected 에 기록
  · 시드는 에피소드마다 다르다 (특정 시드 외우기 방지)

결과: data/playbook/results.jsonl 에 에피소드마다 (버전, 시드, 생존초, 랩, 종료사유) 한 줄.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import harass
import patrol
import playbook as pbm
import postmortem
import telemetry

EVIDENCE = 2
EVAL_EPISODES = 3
ROLLBACK_RATIO = 0.8
LOG = Path(__file__).resolve().parent / "data" / "playbook" / "learn.log"


def log(msg: str) -> None:
    line = time.strftime("%H:%M:%S ") + msg
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("route")
    ap.add_argument("--episodes", type=int, default=10)
    ap.add_argument("--max-seconds", type=float, default=240.0)
    ap.add_argument("--harass-interval", type=float, default=20.0)
    ap.add_argument("--seed-base", type=int, default=1000)
    ap.add_argument("--no-learn", action="store_true", help="복기·수정 없이 기록만")
    ap.add_argument("--grace", type=int, default=None, help="에피소드 시작 축복 ID (기본: 경로 파일의 grace, 없으면 워프 안 함)")
    args = ap.parse_args()

    route = json.loads((patrol.ROUTES / f"{args.route}.json").read_text())
    route_pts = route["points"]
    names = telemetry.load_names()
    pb = pbm.load_current()
    pending: Counter = Counter()         # 제안 id → 누적 횟수
    proposals: dict[str, dict] = {}
    since_change = 0                     # 현재 버전으로 뛴 에피소드 수
    prev_version_median: float | None = pbm.median_survival(pb.version - 1) if pb.version > 1 else None
    log(f"학습 시작: route={args.route} playbook v{pb.version} episodes={args.episodes}")

    # 매 에피소드 전에 시작 축복으로 워프해 잔존 몹을 정리하고 HP/성배를 채운다 (랜덤런의 "새 캐릭터"에 해당)
    import control
    tm0 = telemetry.Telemetry()
    pad0 = control.Pad()
    grace = args.grace or route.get("grace")
    log(f"리셋 축복 ID: {grace}")

    for i in range(args.episodes):
        patrol.reset_episode(tm0, pad0, grace, (route_pts[0][0], route_pts[0][2]), log)
        seed = args.seed_base + int(time.time()) % 100000 + i
        hz = harass.Harasser(seed, interval_s=args.harass_interval, log=log)
        log(f"── 에피소드 {i+1}/{args.episodes}  v{pb.version} seed={seed}")
        r = patrol.run_episode(args.route, pb, hz, max_seconds=args.max_seconds, log=log)
        pbm.record_result(pb.version, seed, r["seconds"], r["laps"], r["reason"], {"episode": r["episode"]})
        since_change += 1

        # ── 복기 ──
        if r["reason"] == "death" and r["death_file"] and not args.no_learn:
            diag = postmortem.diagnose(Path(r["death_file"]), route_pts, names)
            log(f"  복기: killers={[(k['name'] or k['npc'], k['dmg']) for k in diag['killers']]} first_hit_hp={diag['first_hit_hp']} "
                f"hostile={diag['hostile_count']} seg={diag['segment']} flask={diag['flask_used']} retreated={diag['retreated']}")
            prop = postmortem.propose(diag, pb)
            if prop:
                cid = pbm.change_id(prop)
                if cid in pb.rejected:
                    log(f"  제안(거부됨, 재제안 안 함): {prop['why']}")
                else:
                    pending[cid] += 1
                    proposals[cid] = prop
                    log(f"  제안 {pending[cid]}/{EVIDENCE}: {prop['why']}")

        # ── 평가/롤백 (새 버전으로 EVAL_EPISODES 개 뛰었을 때) ──
        if pb.version > 1 and since_change == EVAL_EPISODES and prev_version_median:
            cur = pbm.median_survival(pb.version)
            if cur is not None and cur < prev_version_median * ROLLBACK_RATIO:
                bad = pbm.load_version(pb.version)
                pb = pbm.load_version(pb.version - 1)
                pb.rejected = sorted(set(pb.rejected + [bad.change]))
                pb.version = bad.version + 1
                pb.change = ""
                pb.note = f"rollback of v{bad.version}"
                pbm.save(pb)
                log(f"  ✖ 롤백: v{bad.version} 중앙값 {cur:.0f}s < v{bad.version-1} {prev_version_median:.0f}s×{ROLLBACK_RATIO} → v{pb.version}")
                since_change = 0
            else:
                log(f"  ✔ v{pb.version} 유지 (중앙값 {cur:.0f}s vs 이전 {prev_version_median:.0f}s)")

        # ── 적용 (근거 충분 + 현재 버전 평가가 끝났을 때) ──
        ready = [cid for cid, n in pending.items() if n >= EVIDENCE]
        if ready and (pb.version == 1 or since_change >= EVAL_EPISODES):
            cid = ready[0]
            new = pbm.apply(pb, proposals[cid])
            if new is None:
                log(f"  제안 범위 밖/중복 — 폐기: {proposals[cid]['why']}")
            else:
                prev_version_median = pbm.median_survival(pb.version)
                pb = new
                pbm.save(pb)
                since_change = 0
                log(f"  ★ 플레이북 v{pb.version}: {pb.note}")
            del pending[cid]
            del proposals[cid]

    # ── 요약 ──
    rows = pbm.results()
    by_v: dict[int, list[float]] = {}
    for row in rows:
        by_v.setdefault(row["version"], []).append(row["seconds"])
    log("요약 (버전: 에피소드 수, 생존 중앙값):")
    for v, secs in sorted(by_v.items()):
        log(f"  v{v}: n={len(secs)} median={statistics.median(secs):.0f}s max={max(secs):.0f}s")


if __name__ == "__main__":
    main()
