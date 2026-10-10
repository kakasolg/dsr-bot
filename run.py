"""DSR bot runner — entry point for the layer stack (souls/). Layers are described in LAYERS.md.

  python run.py status                   HP, Estus, weapon, last bonfire, bloodstain (sends no game input)
  python run.py burg-bonfire             Firelink Shrine → ramp one by one → merchant → light and rest at Undead Burg bonfire (changes respawn point)
  python run.py burg-loop                same route, but don't rest at the bonfire; walk back to Firelink Shrine (for repeated testing)
  python run.py clear-ramp [--no-rest]   only the 6 ramp enemies (--no-rest: no rest, from current state)
  python run.py hunt-one [--i 5]         from the Undead Burg bonfire, kill only BURG_TOWN #i and return (5 = crossbowman)
  python run.py clear-burg-town          from here (inside Undead Burg), kill 6 enemies in the user's kill order (BURG_TOWN)
  python run.py merchant                 from here to the merchant (no rest)
  python run.py light-burg               from here (Undead Burg), just light the bonfire
  python run.py burg-upper [--seg 1-7]   Undead Burg bonfire → Taurus fog wall, MoKa's safe-spot zones (ROADMAP 1-m; zone 1 rests first)
  python run.py quit-test                kill #1 and compare ramp enemy survival before/after quit-out (does quit-out revive dead enemies?)

  python run.py watch --radar            no bot: read-only radar while you play by hand (no pad input, no memory writes;
                                         same as `python radar.py watch`). Not together with a bot run using --radar.

  --radar                                send state + log lines to radar_server.py (http://127.0.0.1:47801)
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import threading
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent


class Log:
    """Screen + data/runs/<timestamp>.log; events go to .jsonl."""

    def __init__(self, name: str):
        d = ROOT / "data" / "runs"
        d.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        self.path = d / f"{stamp}_{name}.jsonl"
        self.txt = (d / f"{stamp}_{name}.log").open("a", encoding="utf-8")
        self.ev = self.path.open("a", encoding="utf-8")
        self._lock = threading.Lock()          # the black box writer thread writes to the same file
        self.t0 = time.time()
        self.on_line = None                    # radar hook (--radar): gets each log line, must not raise
        self.zone = None                       # "burg-upper:5" while a zone / segment runs — added to every event (runinfo, ROADMAP 1-i)

    def __call__(self, msg: str) -> None:
        line = f"[{time.time() - self.t0:7.1f}] {msg}"
        with self._lock:
            print(line, flush=True)
            self.txt.write(line + "\n")
            self.txt.flush()
        if self.on_line:
            self.on_line(msg)

    def event(self, _ev: str, **kw) -> None:
        # the arg used to be named kind; it collided with the quit-out result's kind and stopped the bot (2026-09-24)
        z = {"zone": self.zone} if self.zone and "zone" not in kw else {}
        line = json.dumps({"t": round(time.time() - self.t0, 2), "ev": _ev, **z, **kw}, ensure_ascii=False, default=str)
        with self._lock:
            self.ev.write(line + "\n")
            self.ev.flush()


def status() -> None:
    import env
    from souls import moves, weapons
    from souls.watch import Blood
    tm = env.make_telemetry({})
    s = tm.snapshot(within=5.0)
    mv = moves.Moves(tm, None)
    wid = tm.right_weapon()
    print(f"HP {s.player.hp}/{s.player.max_hp}  위치 ({s.player.x:.1f}, {s.player.y:.1f}, {s.player.z:.1f})  "
          f"에스트 {mv.estus_id()} × {mv.estus_left()}  소울 {tm.souls()}  인간성 {tm.humanity()}")
    print(f"무기 {wid} → {weapons.of(wid).name}  양손 {tm.arm_style() == 3}  마지막 화톳불 {tm.last_bonfire()}  핏자국 {Blood.read()}")


LURE_CMDS = {"burg-bonfire", "burg-loop", "clear-ramp", "clear-burg-town", "hunt-one"}   # knife lures (souls/field.py lure)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["status", "watch", "burg-bonfire", "burg-loop", "clear-ramp", "clear-burg-town", "hunt-one", "merchant", "light-burg", "burg-upper", "quit-test", "passage-drill", "asylum"])
    ap.add_argument("--no-rest", action="store_true")
    ap.add_argument("--no-quit", action="store_true", help="퀵 종료(메뉴로 나갔다 오기) 안 씀 — 영상 촬영용")
    ap.add_argument("--i", type=int, default=5, help="hunt-one: BURG_TOWN 몇 번째 (5 = 석궁병 255002)")
    ap.add_argument("--seg", default=None, help="asylum: 구간 번호 또는 범위 (기본 1; 1 = 감방 → 사다리 → 첫 화톳불, 2-3 = 이어서, ROADMAP 1-h). "
                    "burg-bonfire: 구역 하나 또는 범위만 하고 멈춤 — 1 경사로 · 2 비밀 통로 · 3 마을 #1~#3 · 4 마을 #4~#6 · 5 상인 · 6 화톳불 (기본: 전부). burg-upper: 안전 자리 구역 1~7 (기본: 전부, 7 = 안개벽 앞)")
    ap.add_argument("--basic", action="store_true", help="방패 + 약공만 — 뒤잡기·벽 강공·양손 전환 끔 ([MoKa] 2026-10-01, duel.BACKSTAB/HEAVY)")
    ap.add_argument("--radar", action="store_true", help="send state to the radar (view with radar_server.py / overlay.py)")
    ap.add_argument("--laya-shadow", action="store_true",
                    help="싸움 틱마다 Laya 제안을 기록만 (data/runs/<시각>.laya.jsonl) — 패드·규칙엔 반영 안 함 (LAYA.md)")
    ap.add_argument("--laya-worker", default="wsl", help="laya_worker.py 를 띄울 곳: wsl (기본, WSL Ubuntu venv) 또는 python 실행 파일 경로")
    ap.add_argument("--laya-device", default=None, help="cpu | cuda (기본: laya 가 고름)")
    ap.add_argument("--laya-backend", default=None, help="laya (기본) | fake:<전술> — 모델 없이 경로만 시험")
    ap.add_argument("--attack-audit", action="store_true",
                    help="공격 규칙 호출 직전 입력을 기록만 (data/runs/<시각>.attack_audit.jsonl, attack_audit.py) — 기본 꺼짐. "
                         "Laya 추론·행동 반영 없음, 패드·규칙엔 반영 안 함. outcome proxy, not human-verified tactical label, not a safety validation")
    ap.add_argument("--ctl", action="store_true",
                    help="P1: controller timing events → data/runs/<시각>_<명령>.ctl.jsonl (ctl.py) — 기본 꺼짐. 기록만, 패드·규칙엔 반영 안 함")
    ap.add_argument("--ctl-frames", action="store_true",
                    help="P1-D: --ctl 과 함께, 피드 프레임마다 한 줄 → data/runs/<시각>_<명령>.frames.jsonl (~9 KB/s) — 기본 꺼짐. 기록만")
    ap.add_argument("--ctl-scenes", action="store_true",
                    help="--ctl 에 더해 싸움 결정마다 그 순간의 입력을 .ctl.jsonl 에 'scene' 으로 (scenes.py) — python scene_replay.py 로 다시 돌림. 기록만")
    ap.add_argument("--ground", action="store_true",
                    help="걷기·싸움의 바닥 확인에 NavMesh + 걸어 본 자리(ground.py, data/walked/) — 통로·다리 아치처럼 NavMesh가 빈 곳을 낭떠러지로 안 봄. "
                         "낙하 감지·턱 되돌림(watch)은 NavMesh 그대로. 기본 꺼짐 (A/B용)")
    ap.add_argument("--note", default=None, help="한 줄 메모 — 실행 설정 기록(<run>.settings.json)과 로그 첫 줄에 남음 (예: 세이브 이름)")
    ap.add_argument("--no-lure", action="store_true", help="나이프로 한 놈씩 깨우지 않고 예전처럼 걸어가 붙는다 (비교용)")
    ap.add_argument("--style", choices=["guard", "backstep", "rush"], default="guard",
                    help="guard: 방패로 받고 휘청에 친다 (기본) | backstep: 양손, 백스텝으로 피하고 헛친 뒤 약공 | "
                         "rush: 양손, 막지도 피하지도 않고 계속 공격, 에스트로 버틴다 (사용자 제안, 실험)")
    a = ap.parse_args()
    if a.cmd == "status":
        return status()
    if a.cmd == "watch":                                    # read-only: no lock, no pad, no Log file — --radar implied
        import radar
        try:
            radar.watch()
        except KeyboardInterrupt:
            pass
        return

    import control
    import env
    import navmesh
    from botlock import BotLock
    from souls import missions, moves, props, weapons
    from souls.field import Field
    from souls.watch import Blood, Escape

    if a.basic:                                             # before the settings record, so it holds the constants this run uses
        from souls import duel as duel_
        duel_.BACKSTAB, duel_.HEAVY = False, False
    log = Log(a.cmd)
    import runinfo
    settings_path = Path(str(log.path).replace(".jsonl", ".settings.json"))
    t_run = time.time()
    info, diff = runinfo.collect(log.path.stem, sys.argv, vars(a), note=a.note)
    log(runinfo.short(info))                                # first line — travels with the log into data/samples/
    if not runinfo.write(settings_path, info, diff):
        log(f"   ⚠ 실행 설정 기록 못 씀: {settings_path}")

    def run_end(result) -> None:                            # once; never raises (runinfo.end)
        runinfo.end(settings_path, result=result, secs=round(time.time() - t_run, 1))
    import ctl
    if a.ctl_scenes:
        a.ctl = True                                        # the scenes go into the .ctl.jsonl
    if a.ctl:                                               # before the Pad exists: atexit then closes the pad first, this after
        ctl.start(str(log.path).replace(".jsonl", ".ctl.jsonl"), run=log.path.stem, argv=sys.argv, cmd=a.cmd)
        ctl.emit("life", ev="start", cmd=a.cmd, args=vars(a))
        log(f"ctl: 기록만 → {str(log.path).replace('.jsonl', '.ctl.jsonl')}")
        if a.ctl_frames:
            ctl.start_frames(str(log.path).replace(".jsonl", ".frames.jsonl"), run=log.path.stem)
            log(f"ctl: 프레임 기록 → {str(log.path).replace('.jsonl', '.frames.jsonl')}")
    elif a.ctl_frames:
        log("   ⚠ --ctl-frames 는 --ctl 과 함께만 — 프레임 기록 안 함")
    scene_tap = None
    if a.ctl_scenes:
        import scenes
        from souls import duel as duel_scenes
        scene_tap = duel_scenes.SCENE_TAP = scenes.Tap()
        log("ctl scenes: 싸움 결정마다 그 순간의 입력 기록 (scene_replay.py 로 다시 돌림, 판단엔 반영 안 함)")
    lock = BotLock()
    # watchdog.py also polls briefly, grabbing and releasing at once — overlapping that instant can fail once, so retry a few times
    # (measured 2026-09-25: with a single try and no retry, 6 of 10 runs overlapped and failed immediately)
    for _ in range(10):
        if lock.acquire():
            break
        time.sleep(0.2)
    else:
        log("   ⚠ 이미 다른 본체가 실행 중 — 겹쳐 켜면 패드가 부딪힌다, 멈춤")
        ctl.emit("life", ev="normal_exit", result="bot_lock_held")
        run_end("bot_lock_held")
        return
    tm = env.make_telemetry({})
    import track
    track_ = track.Track(str(log.path).replace(".jsonl", ".track.jsonl")).attach(tm)   # planned vs actual path (track_report.py)
    log.on_line = track_.say
    if hasattr(track_, "write"):
        track_.write({"type": "run", "run": info["run"], "commit": info["code"]["commit"], "dirty": info["code"]["dirty"],
                      "argv": info["argv"], "settings_sha1": info["settings_sha1"]})
    if a.radar:
        import radar
        radar_ = radar.Radar().attach(tm)
        log.on_line = lambda m: (track_.say(m), radar_.say(m))
        log("radar: sending — python radar_server.py -> http://127.0.0.1:47801, python overlay.py")
    if a.cmd in LURE_CMDS and not a.no_lure:
        quick = tm.quick_items()
        if moves.ITEM_KNIFE not in quick:
            # 퀵 슬롯에서 나이프를 빼면 가진 개수는 그대로라 매번 '290 칸을 못 고름' → 락온 실패 3번 → 경사로 partial 로 끝났다 (P-22)
            import steam_state
            have = tm.goods_count(moves.ITEM_KNIFE) or 0
            slot = tm.equip_quick_item(moves.ITEM_KNIFE) if have and steam_state.check().get("offline") is True else None
            if slot is None:
                why = ("나이프 없음" if not have else "빈 칸 없음" if -1 not in quick else
                       "Steam 오프라인 확인 안 됨" if steam_state.check().get("offline") is not True else "메모리 모양이 다름")
                log(f"   ⚠ 투척 나이프(290)가 퀵 슬롯에 없음 (슬롯 {quick}, 가진 수 {have}) — 못 넣음: {why}. "
                    f"넣고 다시 켜거나 --no-lure. 멈춤 (게임 입력 없음)")
                ctl.emit("life", ev="normal_exit", result="no_knife_slot")
                run_end("no_knife_slot")
                return
            log(f"   투척 나이프(290)가 퀵 슬롯에 없어서 {slot + 1}번째 빈 칸에 넣음 (가진 수 {have}) → 슬롯 {tm.quick_items()}")
    # one virtual pad per machine (P0-A): refuse before any input — focus_game already sends ALT / a title-bar click
    busy = "다른 프로세스가 가상 패드를 쥐고 있음" if control.pad_lock_held() else None
    if busy is None:
        control.focus_game()
        try:
            pad = control.Pad()
        except control.PadBusy as ex:
            busy = str(ex)
    if busy is not None:
        log(f"   ⚠ {busy} — 패드 둘이 부딪힌다, 멈춤 (게임 입력 없음)")
        ctl.emit("life", ev="normal_exit", result="pad_lock_held")
        run_end("pad_lock_held")
        lock.release()
        return
    if a.cmd == "asylum":
        from souls import asylum
        nms = {asylum.MAP: navmesh.Navmesh(asylum.MAP)}
    else:
        nms = {missions.MAP_A: navmesh.Navmesh(missions.MAP_A), missions.MAP_B: navmesh.Navmesh(missions.MAP_B)}
    props.attach(nms, log)                                  # crates earlier runs had to smash twice: paths bend around them (on each Navmesh)
    for nm_ in nms.values():
        nm_.edge_kinds()                                    # sort wall/drop/seam edges now — the first wall check mid-fight took ~1 s (2026-09-30)
    mv = moves.Moves(tm, pad)
    track_.follow(mv)
    if a.radar:
        radar_.follow(mv)                                   # target · path · held spot on the radar
    w = weapons.of(tm.right_weapon())
    mv.weapon = w
    log(f"무기: {w.name} (약공 {w.combo}연타, 닿는 거리 {w.reach} m, 강공 {'씀' if w.use_heavy else '안 씀'})")
    esc = Escape(pad, list(nms.values()), log=log, events=log.event)   # fall / ledge watch: always the plain NavMesh (also with --ground)
    if a.ground:                                            # walks and fights read floor through the walked-cell map (design-floor-check §3-C)
        import ground
        nms = {k: ground.for_map(v) for k, v in nms.items()}
        log("ground: 바닥 확인 = NavMesh + 걸어 본 자리 (" + ", ".join(f"{k} {len(g.walked)}칸" for k, g in nms.items())
            + ") — 낙하 감지는 NavMesh 그대로")
    esc.quit_ok = not a.no_quit
    if a.no_quit:
        import os
        os.environ["BOT_NO_WARP"] = "1"                   # also disable farm.rest's warp to the bonfire
    esc.start()
    blood = Blood(log=log).start()
    from blackbox import BlackBox
    bbox = BlackBox(tm, log.path, events=log.event, log=log).start()
    fld = Field(mv, w, esc, bonfires=[] if a.cmd == "asylum" else [missions.FIRELINK["stand"], missions.BURG_BONFIRE],
                log=log, events=log.event, style=a.style)
    from souls.camera import CamFollow
    cam = CamFollow(mv, esc, log=log).start()          # so a viewer can see what the bot is doing (user 2026-09-26)
    log(f"스타일: {a.style}")
    laya_ch = None
    if a.laya_shadow:
        import laya_shadow
        laya_out = str(log.path).replace(".jsonl", ".laya.jsonl")
        laya_ch = laya_shadow.WorkerChannel(laya_shadow.worker_cmd(laya_out, a.laya_worker, a.laya_device, a.laya_backend),
                                            err_path=laya_out.replace(".jsonl", ".err"), log=log)
        fld.advisor = laya_shadow.Advisor(laya_ch.offer)
        log(f"laya shadow: 기록만 → {laya_out} (워커 {a.laya_worker}, 패드·규칙엔 반영 안 함)")
    audit_tap = None
    if a.attack_audit:
        import attack_audit
        audit_out = str(log.path).replace(".jsonl", ".attack_audit.jsonl")
        run_id = Path(audit_out).name.split(".")[0]
        audit_tap = attack_audit.DecisionTap(
            attack_audit.AuditWriter(audit_out, attack_audit.run_header(run_id, a.cmd, vars(a), w.name, a.style)), run_id)
        fld.tap = audit_tap
        log(f"attack audit: 기록만 → {audit_out} (공격 규칙 호출 직전 입력, 패드·규칙엔 반영 안 함)")
        purpose = attack_audit.run_purpose()
        if purpose:
            log(f"attack audit 실행 목적: {purpose}")
    if a.basic:                                             # flags were set before the settings record (top of main)
        log("기본 플레이: 방패 + 약공만 (뒤잡기·강공 끔)")
    log.event("style", style=a.style)
    try:   # log character state each run — level-ups, rings (poise) and weapon change results, and without records batch comparisons got muddy (user 2026-09-25)
        st, eq = tm.char_stats(), tm.equipment()
        log(f"캐릭터: SL {st.get('SL')} VIT {st.get('VIT')} END {st.get('END')} STR {st.get('STR')} DEX {st.get('DEX')} | 반지 {eq.get('반지1')},{eq.get('반지2')} 왼손 {eq.get('왼손1')}")
        log.event("char", stats=st, equip=eq)
    except Exception as ex:
        log(f"캐릭터 상태 읽기 실패: {ex!r}")
    runinfo.update(settings_path, game=runinfo.game(tm, mv, w))
    fld.run_id = log.path.stem                              # fight ids: <run>#f001 … (Field.fight)
    ms = missions.Missions(fld, nms, log=log, lure=not a.no_lure)
    result = "exception"
    try:
        if a.cmd == "burg-bonfire" and a.seg:
            lo, _, hi = a.seg.partition("-")
            r = None
            for n in range(int(lo), int(hi or lo) + 1):
                log.zone = f"burg:{n}"
                r = ms.burg_segment(n)
                log(f"══ 구역 {n} ({ms.BURG_SEGMENTS[n]}) 끝: {r}")
                if not fld.alive():
                    break
        elif a.cmd == "burg-bonfire":
            r = ms.burg_bonfire()
        elif a.cmd == "burg-upper":
            lo, _, hi = (a.seg or f"1-{len(ms.UPPER_SEGMENTS)}").partition("-")
            r = None
            for n in range(int(lo), int(hi or lo) + 1):
                log.zone = f"burg-upper:{n}"
                r = ms.upper_segment(n)
                log(f"══ 구역 {n} ({ms.UPPER_SEGMENTS[n]}) 끝: {r}")
                if not fld.alive() or r in ("died", "no_estus", "휴식 실패"):
                    break
        elif a.cmd == "burg-loop":
            r = ms.burg_bonfire_round_trip()
        elif a.cmd == "passage-drill":
            r = ms.passage_drill(rounds=5)
        elif a.cmd == "clear-ramp":
            if not a.no_rest:
                ms.start_fresh()
            r = ms.clear_ramp(lure=not a.no_lure)
        elif a.cmd == "clear-burg-town":
            r = ms.clear_burg_town()
        elif a.cmd == "hunt-one":
            r = ms.hunt_one(a.i)
        elif a.cmd == "merchant":
            r = ms.to_merchant()
        elif a.cmd == "asylum":
            lo, _, hi = (a.seg or "1").partition("-")
            segs = list(range(int(lo), int(hi or lo) + 1))
            run_ = asylum.Asylum(fld, nms[asylum.MAP], log=log, events=log.event)
            why = run_.ready()
            if why:
                r = f"시작 안 함 — {why}"
            else:
                all_steps = asylum.load()
                plan = [(n, asylum.segment(all_steps, n)) for n in segs]
                s0 = tm.snapshot(within=5.0)
                here = (s0.player.x, s0.player.y, s0.player.z) if s0 else None
                first = asylum.step_pos(plan[0][1][0], here) if here else None
                if here and first and math.dist(first, here) > asylum.RESUME_NEAR:
                    # after dying / a restart we stand somewhere inside the range — start from the nearest step
                    flat = [(si, j, st) for si, (_, steps) in enumerate(plan) for j, st in enumerate(steps)]
                    si, j0, _ = min(flat, key=lambda x: math.dist(asylum.step_pos(x[2], here) or (1e9, 1e9, 1e9), here))
                    n0 = plan[si][0]
                    _, cut = asylum.resume(plan[si][1][j0:], here)
                    plan = [(n0, cut)] + plan[si + 1:]
                    log(f"수용소: 첫 단계에서 {math.dist(first, here):.0f} m — 가장 가까운 구간 {n0}의 {j0 + 1}번째 단계부터 이어감")
                for n, steps in plan:                      # back to back — standing idle between segments got us beaten to 152/616
                    log.zone = f"asylum:{n}"
                    log(f"수용소 구간 {n}: {len(steps)}단계 ({steps[0].get('label') or steps[0]['type']} → {steps[-1].get('label') or steps[-1]['type']})")
                    r = run_.run(steps, f"수용소{n}")
                    if r != "done":
                        r = f"구간 {n} {r}"
                        break
        elif a.cmd == "light-burg":
            r = ms.light_burg_bonfire()
        else:
            r = quit_test(ms, mv, esc, log)
        log.zone = None
        result = r
        log(f"══ 결과: {r}")
        log.event("result", cmd=a.cmd, result=r)
        ctl.emit("life", ev="normal_exit", result=r)
    except KeyboardInterrupt:
        # user stop (Ctrl+C): input off first, and from here on no quit-out, Darksign, ChrClassWarp write or menu input (P0-B).
        # A quit-out the Escape thread already started (a fall) is not ours to stop — the wait below lets it finish
        pad.neutral()
        esc.quit_ok = esc.nudge_ok = False      # the Escape thread keeps watching but only logs (fire → skipped)
        cam.stop()                              # camera follow would keep turning the right stick through the cleanup waits
        pad.neutral()
        log("══ 사용자 중지 (Ctrl+C) — 입력 중립, 퀵 종료 안 함")
        log.event("user_stop", cmd=a.cmd)
        ctl.emit("life", ev="user_stop")
        result = "user_stop"
        raise
    except BaseException as ex:
        # if the bot stops, the character stands idle next to enemies and dies (twice on 2026-09-24) — quit out to shake enemies before stopping
        import traceback
        log(f"══ 오류로 멈춤: {ex!r}\n{traceback.format_exc()}")
        ctl.emit("life", ev="exception_exit", exc=type(ex).__name__, msg=repr(ex)[:200])
        result = f"exception:{type(ex).__name__}"
        if not esc.escaping:
            try:
                esc.fire(f"봇 오류({type(ex).__name__}) — 적 떼어내고 멈춤", "shake")
            except Exception as ex2:
                log(f"   퀵 종료도 실패: {ex2!r}")
        raise
    finally:
        pad.neutral()      # first, so nothing stays held through the waits below (dropped while Escape holds the pad mid quit-out)
        try:
            t_wait = time.time()
            while esc.escaping and time.time() - t_wait < 40.0:  # exiting mid quit-out leaves the game stuck in menu/loading
                time.sleep(0.2)
            try:
                if not fld.alive():
                    fld.wait_respawn(30.0)                     # ending while dead leaves no bloodstain (it's confirmed by the soul drop after respawn)
                    time.sleep(1.5)
            except Exception:
                pass
            cam.stop()
            log(cam.stats())
            esc.stop()
            blood.stop()
            bbox.stop()
            if audit_tap is not None:
                log(f"attack audit: {audit_tap.close()}")
            if scene_tap is not None:
                log(f"ctl scenes: {scene_tap.summary()}")
            if a.ground:
                log("ground: 걸어 본 자리로 바닥이라 답한 횟수 " + ", ".join(f"{k} {getattr(g, 'filled', 0)}" for k, g in nms.items()))
            if laya_ch is not None:
                adv = getattr(fld, "advisor", None)
                log(f"laya shadow: {laya_ch.close()}" + (f" · advisor 오류 {adv.errors} ({adv.last_error})" if adv and adv.errors else ""))
            try:
                import risk_report
                log(risk_report.one_line(risk_report.score(log.path)))
            except Exception as ex:
                log(f"위험 요약 실패: {ex!r}")
        finally:
            pad.neutral()
            lock.release()     # only after the final neutral (P0-B) — the watchdog or the next bot may take over from here
            try:
                run_end(result)
                log(f"실행 설정 기록: {settings_path.name}")
            except Exception:
                pass
            if hasattr(tm, "stats"):
                log(f"텔레메트리 피드: {tm.stats()}")   # frames = underlying read count, fresh/waited = frames received by layers, direct = fallback


def quit_test(ms, mv, esc, log) -> str:
    """Does quit-out revive dead enemies — rest, kill only #1, compare survival at spawn spots before/after quit-out. Doesn't rest at the end."""
    from souls import missions

    def alive_map() -> str:
        s = mv.snap(200.0)
        out = []
        for i, e in enumerate(missions.RAMP, 1):
            ok = any(c.hp > 0 and c.npc_param == e["npc"] and math.dist((c.x, c.y, c.z), tuple(e["pos"])) < 6 for c in s.chars)
            out.append(f"#{i}{'살' if ok else '×'}")
        return " ".join(out)
    ms.start_fresh()
    r = ms.f.clear(missions.RAMP[:1], ms.nms[missions.MAP_A])
    before = alive_map()
    esc.fire("퀵 종료 실측", "shake")
    after = alive_map()
    log(f"   1번 처치 {r}: 종료 전 [{before}] → 종료 후 [{after}]")
    return "죽은 적 그대로" if before == after else "달라짐 — 확인 필요"


if __name__ == "__main__":
    main()
