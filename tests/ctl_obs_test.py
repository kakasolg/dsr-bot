"""P1-D: observation quality, frames, Escape and watchdog records — no game, fake telemetry / fake vgamepad.
python tests/ctl_obs_test.py

Checks:
  · Snapshot's two optional fields (fseq, pc) default to None; keyword construction and to_dict() are unchanged
  · Feed: each frame gets fseq (+1 per read) and pc; _view keeps them; snapshot() returns the same values with ctl off and on
  · Feed stalls (none → stale → back): obs records only at transitions, 'recovered' with how long the stretch lasted
  · --ctl-frames only: one frame record per feed read in its own <run>.frames.jsonl (hdr kind=frames, consecutive fseq);
    without it frame() is a no-op and no file appears
  · NoObs: noobs_stick0 → noobs_full → noobs_recovered, and the pad gets exactly the same reports with ctl off and on
  · Escape: nudge_start / nudge_end, nudge_yield while a quit-out holds the pad, fire_skipped with quit-out off,
    fire_start → quit → fire_end on a fake quit; the pad reports are the same off and on
  · watchdog.rescue with the pad lock held: wd bot_lock + skip (at probe), no Pad made
  · run.py: --ctl --ctl-frames opens both files; --ctl-frames without --ctl opens none
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import json
import sys
import tempfile
import threading
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import control
import ctl
import feed
import pad_fakes
import quitout
from telemetry import Chr, Snapshot
from souls import watch


def check(name: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        raise SystemExit(1)


def rows(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def player() -> Chr:
    return Chr(1, 0, 1, 500, 500, 1.0, 2.0, 3.0, sp=80, max_sp=100, anim=0, gx=1.0, gy=2.0, gz=3.0, heading=0.5)


class FakeTm:
    """mode: 'ok' (fresh frame), 'none' (loading), 'stale' (a frame 1 s old)."""

    def __init__(self):
        self.mode = "ok"
        self.reads = 0

    def snapshot(self, within: float = 40.0):
        self.reads += 1
        if self.mode == "none":
            return None
        t = time.time() - (1.0 if self.mode == "stale" else 0.0)
        return Snapshot(t=t, player=player(), chars=[], cam_yaw=0.25)


def test_snapshot_fields() -> None:
    s = Snapshot(t=1.0, player=player())
    check("Snapshot: fseq·pc 기본값 None", s.fseq is None and s.pc is None)
    check("Snapshot.to_dict(): 키가 예전 그대로 (t·player·chars)", set(s.to_dict()) == {"t", "player", "chars"})
    s2 = Snapshot(1.0, player(), [], 0.1)
    check("위치 인자 생성도 그대로 (t, player, chars, cam_yaw)", s2.cam_yaw == 0.1 and s2.fseq is None)


def feed_session(rec_on: bool, tmp: Path):
    tm = FakeTm()
    path = tmp / ("feed_on.ctl.jsonl" if rec_on else "feed_off.ctl.jsonl")
    if rec_on:
        ctl.start(path, run="t", argv=["x"], cmd="test")
    f = feed.Feed(tm).start()
    out = []
    s = f.snapshot(within=5.0)
    out.append(("ok", s is not None and s.player.x == 1.0))
    fseq_a = s.fseq if s else None
    pc_ok = bool(s and isinstance(s.pc, int))
    time.sleep(0.05)
    s_b = f.snapshot(within=5.0)
    tm.mode = "none"
    time.sleep(0.08)
    out.append(("none", f.snapshot(within=5.0) is None))
    tm.mode = "stale"
    time.sleep(0.08)
    out.append(("stale", f.snapshot(within=5.0) is None))
    tm.mode = "ok"
    time.sleep(0.08)
    s3 = f.snapshot(within=5.0)
    out.append(("back", s3 is not None and s3.cam_yaw == 0.25))
    f.stop()
    time.sleep(0.05)
    if rec_on:
        ctl.stop()
    return out, fseq_a, s_b.fseq if s_b else None, pc_ok, (rows(path) if rec_on else []), dict(f.served)


def test_feed(tmp: Path) -> None:
    out0, a0, b0, pc0, _, served0 = feed_session(False, tmp)
    out1, a1, b1, pc1, r, served1 = feed_session(True, tmp)
    check("feed: 켜기/끄기 돌려주는 값 같음 (있음 → None → None → 있음)", out0 == out1 and all(ok for _, ok in out0))
    check("feed: 프레임마다 fseq 증가, pc 정수 (_view가 옮김)", a1 is not None and b1 > a1 and pc0 and pc1)
    check("feed: served 종류별 계수 같은 모양 (none·stale 각 1 이상)", served1["none"] >= 1 and served1["stale"] >= 1
          and served0["none"] >= 1 and served0["stale"] >= 1)
    obs = [x for x in r if x["k"] == "obs"]
    check("obs: none → stale → recovered, 전환 때만 (각 1번)", [x["ev"] for x in obs] == ["none", "stale", "recovered"])
    check("obs recovered: was=stale, dur_ms > 0 (none부터 잼)", obs[-1]["was"] == "stale" and obs[-1]["dur_ms"] > 50)


def test_frames(tmp: Path) -> None:
    check("frames: 시작 전 꺼짐, frame()은 아무것도 안 함", not ctl.frames_on())
    ctl.frame(fseq=1)
    p = tmp / "fr.ctl.jsonl"
    fp = tmp / "fr.frames.jsonl"
    ctl.start(p, run="t", argv=["x"], cmd="test")
    f = feed.Feed(FakeTm()).start()
    time.sleep(0.2)
    check("--ctl만: frames 파일 없음", not fp.exists() and not ctl.frames_on())
    ctl.start_frames(fp, run="t")
    time.sleep(0.3)
    f.stop()
    time.sleep(0.05)
    ctl.stop()
    check("stop 뒤 frames도 꺼짐", not ctl.frames_on())
    r = rows(fp)
    fr = [x for x in r if x["k"] == "frame"]
    check("frames 파일: hdr(kind=frames) → sync → frame… → end", r[0]["k"] == "hdr" and r[0]["kind"] == "frames"
          and r[1]["k"] == "sync" and r[-1]["k"] == "end")
    check(f"frame 기록 {len(fr)}개 (~60 Hz × 0.3 s), fseq 하나씩 이어짐", len(fr) >= 8
          and all(b["fseq"] == a["fseq"] + 1 for a, b in zip(fr, fr[1:])))
    check("frame 필드: snap_t·pc_read_end·read_ms·위치·hp·cam_yaw", all(
        {"snap_t", "pc_read_end", "read_ms", "x", "y", "z", "hp", "sp", "anim", "cam_yaw"} <= set(x) for x in fr)
        and fr[0]["x"] == 1.0)
    check("ctl 이벤트 파일엔 frame 기록이 안 섞임", not any(x["k"] == "frame" for x in rows(p)))


def noobs_session(tmp: Path, rec_on: bool):
    vg = pad_fakes.install(tmp)
    path = tmp / "noobs.ctl.jsonl"
    if rec_on:
        ctl.start(path, run="t", argv=["x"], cmd="test")
    pad = control.Pad()
    no = control.NoObs(pad)
    pad.move(0.6, 0.0)
    no.missing()
    no.missing()
    time.sleep(control.NO_OBS_NEUTRAL_S + 0.05)
    no.missing()
    no.missing()
    no.seen()
    no.seen()
    pad.close()
    if rec_on:
        ctl.stop()
    return [list(d.sent) for d in vg.devices], (rows(path) if rec_on else [])


def test_noobs(tmp: Path) -> None:
    (tmp / "n0").mkdir()
    (tmp / "n1").mkdir()
    sent0, _ = noobs_session(tmp / "n0", False)
    sent1, r = noobs_session(tmp / "n1", True)
    check("NoObs: 켜기/끄기 장치가 받은 보고 같음", [[{k: v for k, v in s.items() if k != "th"} for s in d] for d in sent0]
          == [[{k: v for k, v in s.items() if k != "th"} for s in d] for d in sent1])
    ev = [x["ev"] for x in r if x["k"] == "obs"]
    check("NoObs obs: noobs_stick0 → noobs_full → noobs_recovered (전환 때만)", ev == ["noobs_stick0", "noobs_full", "noobs_recovered"])
    rec = [x for x in r if x["k"] == "obs" and x["ev"] == "noobs_recovered"][0]
    check("noobs_recovered: dur_ms ≥ NO_OBS_NEUTRAL_S, full=True", rec["dur_ms"] >= control.NO_OBS_NEUTRAL_S * 1000 and rec["full"])


class QuitTm(FakeTm):
    def quit_to_title(self, timeout: float = 2.0) -> bool:
        return True


def escape_session(tmp: Path, rec_on: bool):
    vg = pad_fakes.install(tmp)
    path = tmp / "esc.ctl.jsonl"
    if rec_on:
        ctl.start(path, run="t", argv=["x"], cmd="test")
    pad = control.Pad()
    esc = watch.Escape(pad, [], log=lambda *a: None)
    esc.NUDGE_S = 0.02
    nudged = esc._nudge((0.5, -0.5))
    held, go = threading.Event(), threading.Event()

    def holder():
        pad.freeze()
        held.set()
        go.wait(5)
        pad.unfreeze()
    t = threading.Thread(target=holder, name="quitout")
    t.start()
    held.wait(5)
    yielded = esc._nudge((0.5, 0.5))
    go.set()
    t.join(5)
    esc.quit_ok = False
    skipped = esc.fire("test skip", "shake")
    esc.quit_ok = True
    orig = (quitout.reload, watch.env.make_telemetry, watch.time.sleep)
    quitout.reload = lambda p: 1.5
    watch.env.make_telemetry = lambda *_: QuitTm()
    try:
        fired = esc.fire("test", "shake", QuitTm(), player())
    finally:
        quitout.reload, watch.env.make_telemetry = orig[0], orig[1]
    pad.close()
    if rec_on:
        ctl.stop()
    return (nudged, yielded, skipped.get("skipped"), fired.get("how"), esc.gen), [list(d.sent) for d in vg.devices], \
        (rows(path) if rec_on else [])


def test_escape(tmp: Path) -> None:
    (tmp / "e0").mkdir()
    (tmp / "e1").mkdir()
    res0, sent0, _ = escape_session(tmp / "e0", False)
    res1, sent1, r = escape_session(tmp / "e1", True)
    check("Escape: 켜기/끄기 결과 같음 (nudge 됨, 양보, 건너뜀, byte, gen 1)", res0 == res1 == (True, False, True, "byte", 1))
    strip = lambda sent: [[{k: v for k, v in s.items() if k != "th"} for s in d] for d in sent]
    check("Escape: 켜기/끄기 장치가 받은 보고 같음", strip(sent0) == strip(sent1))
    ev = [x["ev"] for x in r if x["k"] == "esc"]
    want = ["freeze", "nudge_start", "unfreeze", "nudge_end",       # nudge (Pad.freeze / unfreeze records from P1-B)
            "freeze", "freeze", "nudge_yield", "unfreeze",           # the holder's freeze, the nudge's refused freeze
            "fire_skipped", "fire_start", "freeze", "quit", "unfreeze", "fire_end"]
    check(f"esc 순서: {ev}", ev == want)
    fe = [x for x in r if x["k"] == "esc" and x["ev"] == "fire_end"][0]
    check("fire_end: kind·gen·dt_ms·how·quit_s·reload_s", fe["kind"] == "shake" and fe["gen"] == 1 and fe["dt_ms"] > 900
          and fe["how"] == "byte" and fe["reload_s"] == 1.5)
    ne = [x for x in r if x["k"] == "esc" and x["ev"] == "nudge_end"][0]
    check("nudge_end: dt_ms ≥ NUDGE_S", ne["dt_ms"] >= 20)


def test_watchdog(tmp: Path) -> None:
    import watchdog
    from botlock import BotLock
    pad_fakes.install(tmp / "wd")
    (tmp / "wd").mkdir(exist_ok=True)
    holder = control.Pad()                                # holds the pad lock (like a live bot)
    watchdog.LOG_FILE = tmp / "wd" / "watchdog.log"
    watchdog.BotLock = lambda: BotLock(tmp / "wd" / "bot.lock")
    made = []
    orig = control.Pad.__init__
    path = tmp / "wd.ctl.jsonl"
    ctl.start(path, run="t", argv=["x"], cmd="watchdog")
    control.Pad.__init__ = lambda self: made.append(1)
    try:
        watchdog.rescue(None)
    finally:
        control.Pad.__init__ = orig
    ctl.stop()
    holder.close()
    wd = [(x["ev"], x.get("reason"), x.get("at")) for x in rows(path) if x["k"] == "wd"]
    check("watchdog: 패드 잠금 잡혀 있음 → wd bot_lock, skip(probe), Pad 안 만듦",
          wd == [("bot_lock", None, None), ("skip", "pad_lock_held", "probe")] and made == [])


def test_run_flags(tmp: Path) -> None:
    """run.py wiring: --ctl --ctl-frames opens both files; --ctl-frames alone opens nothing (frames need --ctl)."""
    import run_stop_test as rst
    rst.install(tmp)
    import run
    runs = tmp / "data" / "runs"
    for argv, want_ctl, want_frames in ((["run.py", "merchant", "--ctl", "--ctl-frames"], 1, 1),
                                        (["run.py", "merchant", "--ctl-frames"], 0, 0)):
        rst.TRACE.clear()
        rst.FakeMissions.exc = KeyboardInterrupt()
        sys.argv = argv
        try:
            run.main()
        except BaseException:
            pass
        ctl.stop()                                     # in a real run atexit does this
        c, fr = sorted(runs.glob("*.ctl.jsonl")), sorted(runs.glob("*.frames.jsonl"))
        check(f"run.main {' '.join(argv[2:])}: ctl 파일 {want_ctl}개, frames 파일 {want_frames}개",
              len(c) == want_ctl and len(fr) == want_frames and not ctl.on() and not ctl.frames_on())
        if fr:
            r = rows(fr[0])
            check("frames 파일: hdr(kind=frames) … end", r[0]["kind"] == "frames" and r[-1]["k"] == "end")
        for x in c + fr:
            x.unlink()


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="ctlobs_"))
    test_snapshot_fields()
    test_feed(tmp)
    test_frames(tmp)
    test_noobs(tmp)
    test_escape(tmp)
    test_watchdog(tmp)
    test_run_flags(tmp / "run")
    check("끝: ctl·frames 꺼짐", not ctl.on() and not ctl.frames_on())
    print("ctl_obs_test: 전부 통과")


if __name__ == "__main__":
    main()
