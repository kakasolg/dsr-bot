"""
에피소드 학습 루프 — 순찰 → (방해) → 사망/시간종료 → 복기 → 플레이북 수정 → 평가/롤백.

  python learn.py <route> --episodes 10 [--max-seconds 240] [--harass-interval 20] [--seed-base 1000]

A/B (규칙만 vs 판단 모델이 복기 후보를 고름) — 같은 시작 플레이북, 같은 시드열, 팔마다 별도 디렉터리:
  python learn.py <route> --episodes 10 --seeds-fixed --arm jev   --jev live
  python learn.py <route> --episodes 10 --seeds-fixed --arm rules --jev off
  python ab_report.py jev rules

규칙 (트레이딩의 워크포워드와 같은 규율):
  · 한 번 죽었다고 바꾸지 않는다: 같은 제안이 EVIDENCE 회 이상 누적돼야 적용
  · 새 버전으로 EVAL_EPISODES 개를 뛴 뒤, 생존시간 중앙값이 직전 버전의 ROLLBACK_RATIO 배 미만이면 롤백하고 그 제안은 rejected 에 기록
  · 시드는 에피소드마다 다르다 (특정 시드 외우기 방지)

결과: data/playbook/results.jsonl 에 에피소드마다 (버전, 시드, 생존초, 랩, 종료사유) 한 줄.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import env
import harass
import patrol
import playbook as pbm
import postmortem

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
    ap.add_argument("--jev", choices=["off", "shadow", "live"], default="off",
                    help="복기 후보 선택에 판단 모델을 씀. shadow: 선택을 기록만 / live: 선택을 적용 (게이트 미달·NONE 이면 규칙). 키는 .env")
    ap.add_argument("--jev-tick", action="store_true",
                    help="틱 단위 이동모드·후퇴 질문도 켠다 (--jev shadow 면 기록만, live 면 따름). 실측상 규칙과 다를 게 없어 기본 꺼짐")
    ap.add_argument("--arm", default=None, help="A/B 팔 이름 — data/playbook/arms/<이름>/ 에 플레이북·성적을 따로 둔다 (첫 실행 때 현재 플레이북을 복사)")
    ap.add_argument("--seeds-fixed", action="store_true", help="시드 = seed-base + i (시각 무관) — 두 팔에 같은 방해 스케줄")
    args = ap.parse_args()
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")

    global LOG
    if args.arm:
        # 두 팔이 같은 v7 에서 갈라져 각자 v8, v9… 를 만들므로 버전/성적/로그를 디렉터리로 분리한다
        src = pbm.load_current()
        pbm.set_dir(pbm.DIR / "arms" / args.arm)
        LOG = pbm.DIR / "learn.log"
        if not (pbm.DIR / "current.json").exists():
            pbm.save(src)

    route = json.loads((patrol.ROUTES / f"{args.route}.json").read_text())
    route_pts = route["points"]
    names = env.load_names()
    if env.GAME == "dsr" and not args.arm:
        pbm.set_dir(pbm.DIR.parent / "playbook-dsr")   # 게임별 플레이북 (DSR 은 점프 없음 → 기본 모드 guard)
        LOG = pbm.DIR / "learn.log"
    pb = pbm.load_current()
    if env.GAME == "dsr" and pb.mode_near_enemy == "guardjump":
        pb.mode_near_enemy = "guard"
        pbm.save(pb)
    pending: Counter = Counter()         # 제안 id → 누적 횟수
    proposals: dict[str, dict] = {}
    since_change = 0                     # 현재 버전으로 뛴 에피소드 수
    eval_pending = False                 # 이번 프로세스에서 새 변경을 적용했고 아직 평가(EVAL_EPISODES)를 안 끝냈는가
    prev_version_median: float | None = None
    log(f"학습 시작[{env.GAME}]: route={args.route} playbook v{pb.version} (crowd {pb.crowd_threshold}, atk {pb.attack_range}/{pb.attack_cooldown}, lock {pb.lock_range}) episodes={args.episodes} jev={args.jev}"
        f"{' tick' if args.jev_tick else ''}{' arm=' + args.arm if args.arm else ''}{' seeds-fixed' if args.seeds_fixed else ''}")
    import jev as jevm
    if args.jev != "off":
        if jevm.available():
            log(f"  jev 백엔드: {jevm.describe()}")
        else:
            log("  jev 사용 불가 (TYPESAFE_API_KEY 없음 / 로컬 LLM 서버 응답 없음) — jev=off 로 진행")
            args.jev = "off"

    # 매 에피소드 전에 시작 축복으로 워프해 잔존 몹을 정리하고 HP/성배를 채운다 (랜덤런의 "새 캐릭터"에 해당)
    import control
    tm0 = env.make_telemetry(names)
    pad0 = control.Pad()  # 프로세스에 하나만 (에피소드마다 만들면 입력이 씹힘)
    grace = args.grace or route.get("grace") or (route.get("bonfires") or [{}])[0].get("id")
    reset_expect = (route_pts[0][0], route_pts[0][2])
    if env.GAME == "dsr" and route.get("bonfires"):
        # 시작점(경로 첫 점)에 가장 가까운 화톳불 = 에피소드 시작 화톳불 (편도 경로면 위쪽 끝)
        bf = min(route["bonfires"], key=lambda b: math.hypot(b["pos"][0] - route_pts[0][0], b["pos"][2] - route_pts[0][2]))
        grace, reset_expect = bf["id"], tuple(bf["pos"]) + ((bf["heading"],) if bf.get("heading") is not None else ())
    log(f"리셋 축복 ID: {grace} 위치 {reset_expect}")

    for i in range(args.episodes):
        # 리스폰 축복 근처에 잔존 몹이 있으면 워프가 막혀 죽은 채로 에피소드가 시작될 수 있다 → 성공할 때까지 최대 3회
        for attempt in range(3):
            if patrol.reset_episode(tm0, pad0, grace, reset_expect, log, start=route.get("start")):
                break
            log(f"  리셋 실패 — 재시도 {attempt + 1}/2")
        else:
            log("  리셋 3회 실패 — 학습 중단")
            break
        seed = args.seed_base + i if args.seeds_fixed else args.seed_base + int(time.time()) % 100000 + i
        hz = harass.Harasser(seed, interval_s=args.harass_interval, log=log) if env.GAME != "dsr" else None   # DSR: 소환 없음, 자연 적
        log(f"── 에피소드 {i+1}/{args.episodes}  v{pb.version} seed={seed}")
        shadow = jevm.Shadow(pb, names, mode=args.jev, log=log) if args.jev != "off" and args.jev_tick else None
        r = patrol.run_episode(args.route, pb, hz, max_seconds=args.max_seconds, log=log, pad=pad0, tm=tm0, jev=shadow)
        pbm.record_result(pb.version, seed, r["seconds"], r["laps"], r["reason"],
                          {"episode": r["episode"], "jev": args.jev, "jev_backend": jevm.backend() if args.jev != "off" else None,
                           "jev_tick": bool(shadow), "jev_calls": shadow.calls if shadow else 0, "jev_min_conf": jevm.MIN_CONF if args.jev != "off" else None, "arm": args.arm})
        if r["reason"] == "stall":   # 입력 불능 — 플레이북 평가에 넣지 않고 다음 에피소드로 (리셋이 축복으로 데려간다)
            log("  멈춤 에피소드 — 성적·평가에서 제외")
            continue
        since_change += 1

        # ── 복기 ──
        if r["reason"] == "death" and r["death_file"] and not args.no_learn:
            diag = postmortem.diagnose(Path(r["death_file"]), route_pts, names)
            log(f"  복기: killers={[(k['name'] or k['npc'], k['dmg']) for k in diag['killers']]} first_hit_hp={diag['first_hit_hp']} "
                f"hostile={diag['hostile_count']} seg={diag['segment']} flask={diag['flask_used']} retreated={diag['retreated']}")
            cands = postmortem.propose_all(diag, pb)
            prop = cands[0] if cands else None
            if args.jev != "off" and cands:
                # 판단 모델에게 후보 중 고르게 한다. shadow: 기록만, live: 그 선택을 쓴다 (NONE/저신뢰면 규칙대로)
                rk = jevm.rank_proposals(diag, pb, cands)
                if rk:
                    pick = rk["proposal"]
                    shown = pick['why'] if pick else (f"(게이트 미달) {rk['would_pick']['why']}" if rk.get('would_pick') else 'NONE')
                    log(f"  jev[{args.jev}] 복기 선택: {shown} (conf {rk['confidence']}, probs {rk.get('probs')}, avoidable {rk['avoidable']}) "
                        f"/ 규칙: {prop['why']}")
                    if args.jev == "live" and pick:
                        prop = pick
            if prop:
                cid = pbm.change_id(prop)
                if cid in pb.rejected:
                    log(f"  제안(거부됨, 재제안 안 함): {prop['why']}")
                else:
                    pending[cid] += 1
                    proposals[cid] = prop
                    log(f"  제안 {pending[cid]}/{EVIDENCE}: {prop['why']}")

        # ── 평가/롤백 (이번에 적용한 새 버전으로 EVAL_EPISODES 개 뛰었을 때만 — 롤백된 버전을 다시 평가하지 않는다) ──
        if eval_pending and since_change == EVAL_EPISODES and prev_version_median:
            eval_pending = False
            cur = pbm.median_survival(pb.version)
            if cur is not None and cur < prev_version_median * ROLLBACK_RATIO:
                bad = pbm.load_version(pb.version)
                pb = pbm.load_version(pb.version - 1)
                pb.rejected = sorted(set(pb.rejected + [bad.change]))
                pb.version = bad.version + 1
                pb.change = ""
                pb.note = f"rollback of v{bad.version}"
                pbm.save(pb)
                log(f"  ✖ 롤백: v{bad.version} 중앙값 {cur:.0f}s < 변경 전 {prev_version_median:.0f}s×{ROLLBACK_RATIO} → v{pb.version}")
                since_change = 0
            else:
                log(f"  ✔ v{pb.version} 유지 (중앙값 {cur:.0f}s vs 이전 {prev_version_median:.0f}s)")

        # ── 적용 (근거 충분 + 현재 버전 평가가 끝났을 때) ──
        ready = [cid for cid, n in pending.items() if n >= EVIDENCE]
        if ready and not eval_pending:
            cid = ready[0]
            new = pbm.apply(pb, proposals[cid])
            if new is None:
                log(f"  제안 범위 밖/중복 — 폐기: {proposals[cid]['why']}")
            else:
                prev_version_median = pbm.median_survival(pb.version)
                pb = new
                pbm.save(pb)
                since_change = 0
                eval_pending = prev_version_median is not None
                log(f"  ★ 플레이북 v{pb.version}: {pb.note}")
            del pending[cid]
            del proposals[cid]

    # 런이 끝나도 캐릭터를 길 위에 세워 두지 않는다 — 축복으로 돌아가 쉰다
    log("런 종료 — 축복으로 복귀")
    patrol.reset_episode(tm0, pad0, grace, reset_expect, log)

    # ── 요약 ──
    rows = pbm.results()
    by_v: dict[int, list[float]] = {}
    for row in rows:
        if row.get("reason") != "stall":
            by_v.setdefault(row["version"], []).append(row["seconds"])
    log("요약 (버전: 에피소드 수, 생존 중앙값):")
    for v, secs in sorted(by_v.items()):
        log(f"  v{v}: n={len(secs)} median={statistics.median(secs):.0f}s max={max(secs):.0f}s")


if __name__ == "__main__":
    main()
