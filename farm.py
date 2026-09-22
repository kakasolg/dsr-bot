"""반복 사냥 학습 — 한 자리를 왕복하며 전투 파라미터를 다듬는다.

  python farm.py --episodes 30 [--spot burg-approach] [--no-learn]
  python farm.py --report

에피소드 한 판:  화톳불에서 쉼(적 리스폰·HP·성배 충전) → 내비메시 경로로 사냥터 → 적을 정리 → 화톳불로 복귀.

왜 이 구조인가 (사용자와 정한 것):
 · 묘지 해골은 한 방에 HP 1/3 이 날아가고 떼로 온다. 그 난이도에서 파라미터를 최적화하면 루프가 찾는 답은
   "절대 싸우지 말 것"이 된다 — 지표는 오르지만 배우고 싶은 게 아니다. **해골 쪽은 가지 않는다.**
 · HP 75~85 짜리 적은 공격성과 안전 사이에 실제 트레이드오프가 있어서 attack_range·attack_cooldown·
   retreat_hp_pct 같은 값이 의미를 갖는다.
 · 지표가 "죽었다/살았다" 이진값이 아니라 **등급**이 된다: 적 하나당 잃은 HP, 명중률, 스태미나 고갈 횟수.
   이진 신호보다 분산이 작아 30판으로 판정이 선다.

점수(낮을수록 좋다) = 적 하나당 잃은 HP. 적을 못 잡으면 판이 무효(집계 제외).
기록: data/playbook-dsr/farm-results.jsonl
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

import control
import danger
import env
import nav
import navmesh
import navwalk
import patrol
import playbook as pbm

ROOT = Path(__file__).resolve().parent
SPOTS = json.loads((ROOT / "data" / "spots.json").read_text(encoding="utf-8"))
RESULTS = ROOT / "data" / "playbook-dsr" / "farm-results.jsonl"
LOG = ROOT / "data" / "playbook-dsr" / "farm.log"
EVIDENCE = 2          # 같은 제안이 이만큼 나와야 적용
EVAL_EPISODES = 3     # 새 버전으로 이만큼 뛴 뒤 평가
ROLLBACK_RATIO = 1.25 # 점수(낮을수록 좋음)가 이 배 넘게 나빠지면 되돌린다


def log(msg: str) -> None:
    print(msg, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")


# ── 한 판 ──────────────────────────────────────────────
def rest(tm, pad, nm, bonfire) -> bool:
    """화톳불까지 가서 앉는다 — 적 리스폰·HP·성배 충전. 앉는 데 2.5 s 걸린다(anim2 -1 → 7710 → 7711)."""
    import vgamepad
    s = tm.snapshot(within=1.0)
    if not s:
        return False
    for wp in nm.find_path((s.player.x, s.player.y, s.player.z), tuple(bonfire["stand"]))[1:]:
        if nav.goto(tm, pad, wp, tolerance=2.0, timeout=30, log=lambda *a: None,
                    mode_fn=lambda _s: "sprint") == "dead":
            break
    pad.neutral()
    for _ in range(4):
        tm.pos_warp(*bonfire["stand"], bonfire["heading"])
        time.sleep(0.9)
        pad.interact()
        for _ in range(16):
            time.sleep(0.25)
            if tm.sitting():
                break
        if tm.sitting():
            break
    if not tm.sitting():
        return False
    time.sleep(1.0)
    for _ in range(6):                      # 일어나기
        if not tm.sitting():
            break
        pad.tap(vgamepad.XUSB_BUTTON.XUSB_GAMEPAD_B, 0.1)
        time.sleep(1.0)
    return True


def goal_xyz(nm, spot) -> tuple:
    """목표를 반드시 보행면 위로 — 손으로 적은 좌표나 MSB 평균은 면 밖일 수 있고, 그러면 경로가 0 점이 된다."""
    import numpy as np
    t = tuple(spot["pos"])
    if nm.floor_at(t[0], t[2], t[1]) is not None and nm.find_path(t, t) is not None:
        ok = nm.walkable()
        d = np.linalg.norm(nm.centroid - np.array(t), axis=1)
        d = np.where(ok, d, np.inf)
        i = int(d.argmin())
        if d[i] < 3.0:
            return tuple(float(v) for v in nm.centroid[i])
    return t


def episode(tm, pad, nm, guard, dng, spot, max_seconds: float) -> dict:
    """사냥터로 가서 적을 정리하고 돌아온다. 등급 지표를 돌려준다."""
    spot_xyz = tuple(spot["pos"])
    spot_y = (spot_xyz[1],)
    st = {"hp0": None, "hp_lost": 0, "kills": 0, "swings": 0, "hits": 0,
          "stam_out": 0, "blocks": 0, "death": False, "pend": None,
          "last_y": None, "fell": False, "fall_at": None, "y_max": -9999.0, "reached": False}
    seen_hp: dict[int, int] = {}

    def on_tick(s, _dist=None):
        p = s.player
        if st["hp0"] is None:
            st["hp0"] = p.hp
        if st["pend"] is not None:          # 직전 스윙 판정
            at, ptr, hp0 = st["pend"]
            cur = next((c for c in s.chars if c.ptr == ptr), None)
            if cur is not None and cur.hp < hp0:
                st["hits"] += 1
                st["pend"] = None
            elif time.time() - at > 1.2:
                st["pend"] = None
        for c in s.chars:                   # 처치 집계 — hostile() 만 보면 죽는 순간 목록에서 빠질 수 있다
            if c.dist > 30 or c.max_hp <= 0:
                continue
            if seen_hp.get(c.ptr, -1) > 0 and c.hp <= 0:
                st["kills"] += 1
            seen_hp[c.ptr] = c.hp
        # 낙사 감지 — 순식간에 크게 떨어지면 그 자리를 기억한다 (사용자 경고: 이 구간은 낙사 위험)
        if st["last_y"] is not None and st["last_y"] - p.y > 4.0:
            st["fell"] = True
            st["fall_at"] = (round(p.x, 1), round(st["last_y"], 1), round(p.z, 1))
        st["last_y"] = p.y
        st["y_max"] = max(st["y_max"], p.y)          # 얼마나 올라갔나 — 목표가 위층이면 도달 여부 확인용
        if abs(p.y - spot_y[0]) < 2.5 and math.dist((p.x, p.y, p.z), spot_xyz) < 6.0:
            st["reached"] = True
        was = guard.recovering
        a = guard.tick(s)
        if guard.recovering and not was:
            st["stam_out"] += 1
        if a in ("attack", "counter", "combo") and guard.engage is not None:
            st["swings"] += 1
            if st["pend"] is None:
                st["pend"] = (time.time(), guard.engage.ptr, guard.engage.hp)
        if a == "blocked":
            st["blocks"] += 1

    t0 = time.time()
    s = tm.snapshot(within=1.0)
    st["hp0"] = s.player.hp if s else None
    path = nm.find_path((s.player.x, s.player.y, s.player.z), goal_xyz(nm, spot))
    res = navwalk.walk(path, tm, pad, log=lambda *a: None, guard=guard, dng=dng, extra_tick=on_tick)
    # 남은 적 정리 (경로 끝에서 주변 적이 없어질 때까지)
    while time.time() - t0 < max_seconds:
        s = tm.snapshot(within=25.0)
        if not s or s.player.hp <= 0:
            st["death"] = True
            break
        live = [c for c in s.hostile(20.0) if c.hp > 0 and abs(c.y - s.player.y) < 3.0]
        if not live:
            break
        tgt = (live[0].x, live[0].y, live[0].z)
        nav.goto(tm, pad, tgt, tolerance=guard.pb.attack_range - 0.3, timeout=12,
                 log=lambda *a: None, on_tick=on_tick, mode_fn=lambda _s: guard.mode,
                 engage_fn=lambda _s: guard.engage_pos())
    pad.guard(False)
    pad.neutral()
    s = tm.snapshot(within=1.0)
    hp_end = s.player.hp if s else 0
    if hp_end <= 0:
        st["death"] = True
    st["hp_lost"] = max(0, (st["hp0"] or 0) - hp_end) if not st["death"] else (st["hp0"] or 0)
    st["seconds"] = round(time.time() - t0, 1)
    st["fails"] = res.get("fails", [])
    st["retreats"] = res.get("retreats", 0)
    st["score"] = round(st["hp_lost"] / st["kills"], 1) if st["kills"] else None
    st["hit_rate"] = round(st["hits"] / st["swings"], 2) if st["swings"] else None
    st.pop("pend", None)
    st.pop("last_y", None)
    st["y_max"] = round(st["y_max"], 1)
    return st


# ── 제안 ───────────────────────────────────────────────
def propose(r: dict, pb) -> list[dict]:
    """등급 지표에서 플레이북 수정 후보를 만든다 (결정론 규칙, 근거가 2회 쌓여야 적용된다)."""
    out = []
    if r.get("hit_rate") is not None and r["hit_rate"] < 0.35 and pb.attack_range > 1.3:
        out.append({"key": "attack_range", "op": "add", "value": -0.1,
                    "why": f"명중률 {r['hit_rate']:.0%} — 너무 먼 거리에서 휘두른다 (사거리 -0.1)"})
    if r["stam_out"] >= 3:
        out.append({"key": "attack_cooldown", "op": "add", "value": 0.2,
                    "why": f"스태미나 고갈 {r['stam_out']}회 — 덜 자주 친다 (쿨 +0.2)"})
    if r["stam_out"] >= 3 and pb.stam_backoff < 0.45:
        out.append({"key": "stam_backoff", "op": "add", "value": 0.05,
                    "why": f"스태미나 고갈 {r['stam_out']}회 — 더 일찍 물러난다 (+0.05)"})
    if r["death"]:
        out.append({"key": "retreat_hp_pct", "op": "add", "value": 0.05,
                    "why": "사망 — 더 일찍 후퇴 (+0.05)"})
    if r.get("score") is not None and r["score"] > 60 and not r["death"]:
        out.append({"key": "flask_hp_pct", "op": "add", "value": 0.05,
                    "why": f"적당 잃은 HP {r['score']} — 더 일찍 회복 (+0.05)"})
    if r["retreats"] == 0 and r.get("score") is not None and r["score"] > 80:
        out.append({"key": "retreat_dist", "op": "add", "value": 3.0,
                    "why": f"적당 잃은 HP {r['score']} 인데 후퇴가 없었다 — 후퇴 거리 +3 m"})
    return out


# ── 기록·평가 ───────────────────────────────────────────
def record(row: dict) -> None:
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    with RESULTS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def rows() -> list[dict]:
    if not RESULTS.exists():
        return []
    return [json.loads(l) for l in RESULTS.read_text(encoding="utf-8").splitlines() if l.strip()]


def median_score(version: int) -> float | None:
    vals = [r["score"] for r in rows() if r["version"] == version and r.get("score") is not None]
    return statistics.median(vals) if vals else None


def report() -> None:
    by_v: dict[int, list[dict]] = {}
    for r in rows():
        by_v.setdefault(r["version"], []).append(r)
    if not by_v:
        print("기록 없음"); return
    print("버전별 성적 (점수 = 적 하나당 잃은 HP, 낮을수록 좋음)")
    for v, rs in sorted(by_v.items()):
        sc = [r["score"] for r in rs if r.get("score") is not None]
        hr = [r["hit_rate"] for r in rs if r.get("hit_rate") is not None]
        print(f"  v{v}: n={len(rs)}  점수 중앙 {statistics.median(sc):.1f}" if sc else f"  v{v}: n={len(rs)}  점수 없음",
              f" 명중률 {statistics.mean(hr):.0%}" if hr else "",
              f" 사망 {sum(1 for r in rs if r['death'])}  처치 {sum(r['kills'] for r in rs)}")


# ── 메인 ───────────────────────────────────────────────
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=int, default=30)
    ap.add_argument("--spot", default="burg-approach")
    ap.add_argument("--max-seconds", type=float, default=150.0)
    ap.add_argument("--no-learn", action="store_true")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()
    if args.report:
        report(); return

    spot, bonfire = SPOTS[args.spot], SPOTS["firelink-bonfire"]
    pbm.set_dir(pbm.DIR.parent / "playbook-dsr")
    pb = pbm.load_current()
    tm = env.make_telemetry({})
    control.focus_game()
    pad = control.Pad()
    nm = navmesh.Navmesh(spot["map"])
    dng = danger.Danger(spot["map"])
    log(f"사냥 학습 시작: {args.spot} {args.episodes}판  v{pb.version} "
        f"(사거리 {pb.attack_range} 쿨 {pb.attack_cooldown} 후퇴HP {pb.retreat_hp_pct} 스태미나 {pb.stam_backoff}/{pb.stam_resume})")

    pending: Counter = Counter()
    props: dict[str, dict] = {}
    since_change, eval_pending, prev_median = 0, False, None

    for i in range(args.episodes):
        if not rest(tm, pad, nm, bonfire):
            log("  화톳불 휴식 실패 — 중단"); break
        guard = patrol.Guard(pad, pb, log=lambda *a: None)
        r = episode(tm, pad, nm, guard, dng, spot, args.max_seconds)
        r.update(version=pb.version, episode=i + 1, t=time.time())
        record(r)
        if r.get("fell"):
            dng.add(*r["fall_at"], 999)          # 낙하 지점을 위험 지점으로 (다음 판부터 그 근처는 아주 천천히)
            log(f"  ⚠ 낙하 감지 {r['fall_at']} — 위험 지점 기록")
        log(f"── {i+1}/{args.episodes} v{pb.version}: 처치 {r['kills']}  잃은HP {r['hp_lost']}  "
            f"점수 {r['score']}  명중률 {r['hit_rate']}  스태고갈 {r['stam_out']}  후퇴 {r['retreats']}  {'목표도달' if r['reached'] else f"미도달(최고 y {r['y_max']})"}  "
            f"{'사망' if r['death'] else '생존'}  {r['seconds']}s")
        if r["kills"] == 0:
            log("  처치 0 — 집계 제외"); continue
        since_change += 1

        if not args.no_learn:
            for prop in propose(r, pb):
                cid = pbm.change_id(prop)
                if cid in pb.rejected:
                    continue
                pending[cid] += 1
                props[cid] = prop
                if pending[cid] >= EVIDENCE:
                    log(f"  제안 {pending[cid]}/{EVIDENCE}: {prop['why']}")

        if eval_pending and since_change >= EVAL_EPISODES and prev_median:
            eval_pending = False
            cur = median_score(pb.version)
            if cur is not None and cur > prev_median * ROLLBACK_RATIO:
                bad = pbm.load_version(pb.version)
                pb = pbm.load_version(pb.version - 1)
                pb.rejected = sorted(set(pb.rejected + [bad.change]))
                pb.version = bad.version + 1
                pb.change, pb.note = "", f"rollback of v{bad.version}"
                pbm.save(pb)
                log(f"  ✖ 롤백: v{bad.version} 점수 {cur:.1f} > 이전 {prev_median:.1f}×{ROLLBACK_RATIO} → v{pb.version}")
                since_change = 0
            else:
                log(f"  ✔ v{pb.version} 유지 (점수 {cur if cur is None else round(cur,1)} vs 이전 {prev_median:.1f})")

        ready = [cid for cid, n in pending.items() if n >= EVIDENCE]
        if ready and not eval_pending and not args.no_learn:
            cid = ready[0]
            new = pbm.apply(pb, props[cid])
            if new is None:
                log(f"  범위 밖/중복 — 폐기: {props[cid]['why']}")
            else:
                prev_median = median_score(pb.version)
                pb = new
                pbm.save(pb)
                since_change = 0
                eval_pending = prev_median is not None
                log(f"  ★ 플레이북 v{pb.version}: {pb.note}")
            del pending[cid]; del props[cid]

    log("종료 — 화톳불로 복귀")
    rest(tm, pad, nm, bonfire)
    report()


if __name__ == "__main__":
    main()
