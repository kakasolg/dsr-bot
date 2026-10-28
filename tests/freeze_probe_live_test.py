"""experiments/freeze_probe_live.py (variant J) without the game — real control.Pad on a fake vgamepad, fake / patched quit-out.
python tests/freeze_probe_live_test.py

  1  probe calls start only after a successful freeze (quit-like owner and the real Escape._nudge)
  2  J: every probe call returns before the owner body runs
  3  the normal unfreeze runs only after the probe thread is confirmed dead
  4  freeze refused (another thread holds it) → no probe thread
  5  probe exception / unsafe return / join timeout / Ctrl+C in the join / Ctrl+C in the owner body → cleanup
  6  the byte fallback (quit_to_title) is blocked on the reference the real Escape._quit uses; pm writes blocked
  7  --help and argument errors import nothing that touches the pad or the game, and write no records
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder, then experiments/
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]
_sys.path.insert(2, str(_pl.Path(__file__).resolve().parent.parent / "experiments"))

import _thread
import json
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import control
import env
import freeze_probe_live as fp
import pad_fakes
import quitout
from control import B
from souls import watch

ROOT = Path(__file__).resolve().parent.parent
LB_N, B_N = "XUSB_GAMEPAD_LEFT_SHOULDER", "XUSB_GAMEPAD_B"
FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("ok   " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        FAILED.append(name)


def fresh():
    vg = pad_fakes.install(Path(tempfile.mkdtemp(prefix="fprobe_")))
    pad = control.Pad()
    return pad, vg.devices[-1]


def seq(h, ev, **match) -> int | None:
    for e in h.events:
        if e["ev"] == ev and all(e.get(k) == v for k, v in match.items()):
            return e["seq"]
    return None


def seqs(h, ev) -> list[int]:
    return [e["seq"] for e in h.events if e["ev"] == ev]


class FakeEscape:
    """fire()'s shape: freeze() outside the try, owner body, finally neutral → unfreeze."""

    def __init__(self, pad, h, mid=None):
        self.pad, self.h, self.mid = pad, h, mid

    def fire(self):
        self.pad.freeze()
        try:
            self.h.mark("owner_body")
            self.pad.neutral()
            self.pad.press(B.XUSB_GAMEPAD_START, 0.0)
            if self.mid:
                self.mid()
            self.pad.press(B.XUSB_GAMEPAD_A, 0.0)
        finally:
            self.pad.neutral()
            self.pad.unfreeze()
        return "done"


class FakeTm:
    def __init__(self):
        self.real_quit_calls = 0

    def snapshot(self, within=None):
        return None

    def menu_open(self):
        return False

    def quit_to_title(self, timeout=2.0):
        self.real_quit_calls += 1
        return True


def counted(h, rec) -> None:
    """Every harness event also carries n = how many device reports existed at that moment (test-only instance override)."""
    h.mark = lambda ev, **kw: fp.Harness.mark(h, ev, n=len(rec.sent), **kw)


def n_at(h, ev) -> int:
    return next(e["n"] for e in h.events if e["ev"] == ev)


def guard_only_after_recover(h, rec, n0: int) -> tuple[bool, str]:
    """No LB / B on the device from n0 until the harness's recover request; LB reaches the device after it."""
    nr = n_at(h, "recover_req")
    before = [r["buttons"] for r in rec.sent[n0:nr] if LB_N in r["buttons"] or B_N in r["buttons"]]
    after = any(LB_N in r["buttons"] for r in rec.sent[nr:])
    return not before and after, f"LB/B before recover: {before}, LB after: {after}"


def order_ok(h) -> tuple[bool, str]:
    calls, rets = seqs(h, "call"), seqs(h, "ret")
    fo, pe, pj, ob = seq(h, "freeze_ok"), seq(h, "probe_exit"), seq(h, "probe_joined"), seq(h, "owner_body")
    uc, ud = seq(h, "unfreeze_check", probe_alive=False), seq(h, "unfreeze_done")
    parts = [fo is not None, bool(calls), all(fo < c for c in calls), max(rets) < pe < pj, uc is not None and ud is not None,
             pe < uc < ud]
    if ob is not None:
        parts.append(pj < ob < uc)
    return all(parts), str(parts)


def main() -> None:
    # 1-3 quit-like owner, normal path
    pad, rec = fresh()
    h = fp.Harness(pad, [])
    h.calls = fp.default_calls(pad, B)
    counted(h, rec)
    n0 = len(rec.sent)
    s = fp.execute(h, FakeEscape(pad, h).fire)
    ok, why = order_ok(h)
    check("1-3 quit형: freeze 성공 뒤 시험 호출 → 호출 끝 → 소유자 본문 → 스레드 종료 확인 → 정상 unfreeze", ok, why)
    check("   정상 종료 outcome=normal, 시험 호출 8개 모두 막힘(keep_guard False, epoch 그대로)",
          s["ok"] and s["outcome"] == "normal" and len(seqs(h, "ret")) == 8 and all(e["ok"] for e in h.events if e["ev"] == "ret"),
          json.dumps(s, ensure_ascii=False))
    ok, why = guard_only_after_recover(h, rec, n0)
    check("   복구 요청 전까지 장치 보고에 LB·B 없음, 요청 뒤 LB 들어감 (recover_ret held)",
          ok and any(e["ev"] == "recover_ret" and e["held"] for e in h.events), why)
    check("   시험 호출은 probe 스레드, 소유자 본문은 주 스레드",
          all(e["th"] == "probe" for e in h.events if e["ev"] in ("call", "ret"))
          and all(e["th"] == threading.current_thread().name for e in h.events if e["ev"] in ("owner_body", "unfreeze_done")))
    pad.close()

    # 1-3 real Escape._nudge
    pad, rec = fresh()
    h = fp.Harness(pad, [])
    h.calls = fp.default_calls(pad, B)
    esc = watch.Escape(pad, nms=[], log=lambda *a: None)
    counted(h, rec)
    n0 = len(rec.sent)
    s = fp.execute(h, lambda: esc._nudge((0.0, 0.5)))
    ok, why = order_ok(h)
    check("1-3 실제 Escape._nudge: 같은 순서, outcome=normal, _frozen_by 풀림", ok and s["ok"] and pad._frozen_by is None, why + json.dumps(s))
    nu = n_at(h, "unfreeze_done")
    owner = rec.sent[n0:nu]
    ok2, why2 = guard_only_after_recover(h, rec, n0)
    check("   nudge 소유자 보고 = 스틱만(버튼 없음) → 전부 꺼짐; LB는 복구 요청 뒤에만",
          ok2 and owner and all(not r["buttons"] for r in owner) and any(abs(r["ly"] - 0.5) < 1e-6 for r in owner)
          and rec.sent[nu - 1]["ly"] == 0, why2 + str(owner))
    check("   Escape 감시 스레드는 시작 안 함", not esc.th.is_alive() and esc.th.ident is None)
    pad.close()

    # 4 freeze refused
    pad, rec = fresh()
    hold_it, let_go = threading.Event(), threading.Event()

    def other():
        pad.freeze()
        hold_it.set()
        let_go.wait(5)
        pad.unfreeze()
    th = threading.Thread(target=other, name="other_holder")
    th.start()
    hold_it.wait(5)
    h = fp.Harness(pad, [])
    h.calls = fp.default_calls(pad, B)
    esc = watch.Escape(pad, nms=[], log=lambda *a: None)
    s = fp.execute(h, lambda: esc._nudge((0.0, 0.5)))
    check("4 freeze 거절(take=False, 다른 홀더) → 시험 스레드 시작 안 함, outcome=refused, 실패",
          s["outcome"] == "refused" and not s["probe_started"] and not seqs(h, "call") and not s["ok"], json.dumps(s))
    let_go.set()
    th.join(5)
    pad.close()

    # 5a probe exception
    pad, rec = fresh()
    h = fp.Harness(pad, [])

    def boom():
        raise RuntimeError("probe boom")
    h.calls = [("guard(True)", lambda: pad.guard(True), None), ("boom", boom, None), ("neutral", pad.neutral, None)]
    s = fp.execute(h, FakeEscape(pad, h).fire)
    err = [e for e in h.events if e["ev"] == "call_error"]
    check("5a 시험 호출 예외 → outcome=probe_error, 전체 실패, traceback 기록, 이후 호출 안 함",
          s["outcome"] == "probe_error" and not s["ok"] and err and "RuntimeError" in err[0]["tb"]
          and "neutral" not in [e.get("name") for e in h.events if e["ev"] == "call"], json.dumps(s))
    check("   소유자 본문·정상 unfreeze 없음, release_all 뒤 장치 전부 꺼짐",
          seq(h, "owner_body") is None and seq(h, "unfreeze_done") is None and seq(h, "released") is not None and rec.is_neutral())
    pad.close()

    # 5a' unsafe return (e.g. an unpatched keep_guard that pressed)
    pad, rec = fresh()
    h = fp.Harness(pad, [("keep_guard", lambda: True, False)])
    s = fp.execute(h, FakeEscape(pad, h).fire)
    check("5a' 막혔어야 할 호출이 다른 값 → outcome=probe_unsafe, 소유자 본문 없음",
          s["outcome"] == "probe_unsafe" and not s["ok"] and seq(h, "owner_body") is None, json.dumps(s))
    pad.close()

    # 5b join timeout
    pad, rec = fresh()
    gate = threading.Event()
    h = fp.Harness(pad, [], join_timeout=0.3)
    h.calls = [("slow", lambda: gate.wait(5) and None, None), ("neutral", pad.neutral, None)]
    t0 = time.monotonic()
    s = fp.execute(h, FakeEscape(pad, h).fire)
    took = time.monotonic() - t0
    check("5b join 타임아웃 → outcome=join_timeout, 정상 흐름 복귀 없음(소유자 본문·unfreeze 없음)",
          s["outcome"] == "join_timeout" and s["probe_alive"] and seq(h, "owner_body") is None and seq(h, "unfreeze_done") is None
          and took < 2.0, json.dumps(s) + f" {took:.2f}s")
    check("   타임아웃 뒤에도 release_all로 장치 전부 꺼짐, freeze는 하네스가 쥔 채(정상 unfreeze 안 함)",
          rec.is_neutral() and pad._frozen_by == threading.get_ident())
    gate.set()
    h.th.join(5)
    check("   중단 신호 뒤 남은 호출 안 함 (probe_stopped)", not h.th.is_alive() and seq(h, "probe_stopped", before="neutral") is not None)
    pad.close()

    # 5c Ctrl+C while the owner waits on the probe
    pad, rec = fresh()
    h = fp.Harness(pad, [])

    def ctrl_c():
        _thread.interrupt_main()
        h.stop.wait(2)
    h.calls = [("ctrl_c", ctrl_c, None), ("neutral", pad.neutral, None)]
    s = fp.execute(h, FakeEscape(pad, h).fire)
    h.th.join(5)
    check("5c join 중 Ctrl+C → outcome=interrupted, 중단 신호, 소유자 본문·정상 unfreeze 없음, 장치 꺼짐",
          s["outcome"] == "interrupted" and seq(h, "interrupt") is not None and seq(h, "owner_body") is None
          and seq(h, "unfreeze_done") is None and rec.is_neutral() and seq(h, "probe_stopped", before="neutral") is not None,
          json.dumps(s))
    pad.close()

    # 5d Ctrl+C in the owner body (probe already done)
    pad, rec = fresh()
    h = fp.Harness(pad, [])
    h.calls = fp.default_calls(pad, B)

    def kb():
        raise KeyboardInterrupt
    s = fp.execute(h, FakeEscape(pad, h, mid=kb).fire)
    check("5d 소유자 본문 중 Ctrl+C → outcome=interrupted, 소유자 finally의 unfreeze는 스레드 종료 확인 뒤, 복구 요청 없음",
          s["outcome"] == "interrupted" and seq(h, "unfreeze_check", probe_alive=False) is not None
          and seq(h, "unfreeze_done") is not None and seq(h, "recover_req") is None and pad._frozen_by is None and rec.is_neutral(),
          json.dumps(s))
    pad.close()

    # 6 byte fallback blocked on the real Escape._quit path
    pad, rec = fresh()
    h = fp.Harness(pad, [])
    h.calls = fp.default_calls(pad, B)
    esc = watch.Escape(pad, nms=[], log=lambda *a: None)
    ftm = FakeTm()
    keep = quitout.quit_out, quitout.close_menu, quitout.reload, env.make_telemetry
    closed = []
    quitout.quit_out = lambda tm, pad, **k: None                         # the menu quit fails → _quit tries byte
    quitout.close_menu = lambda tm, pad: closed.append(1)
    quitout.reload = lambda pad, timeout=40.0: (_ for _ in ()).throw(AssertionError("reload reached"))
    env.make_telemetry = lambda names=None: (_ for _ in ()).throw(AssertionError("make_telemetry reached"))
    try:
        s = fp.execute(h, lambda: esc.fire("t", "shake", tm=fp.GuardedTm(ftm, h)))
    finally:
        quitout.quit_out, quitout.close_menu, quitout.reload, env.make_telemetry = keep
    check("6 실제 Escape.fire(shake) 메뉴 실패 → _quit의 tm.quit_to_title 참조에서 차단, 진짜 quit_to_title 0번",
          s["outcome"] == "fallback_blocked" and ftm.real_quit_calls == 0 and s["blocked"] == ["quit_to_title"] and closed, json.dumps(s))
    check("   기록 뒤 실패: fallback_blocked 이벤트, 소유자 finally의 unfreeze는 스레드 종료 확인 뒤",
          seq(h, "fallback_blocked", name="quit_to_title") is not None and not s["ok"]
          and seq(h, "unfreeze_check", probe_alive=False) is not None)
    pad.close()

    class Pm:
        def read_uint(self, a):
            return 7

        def write_uchar(self, a, v):
            raise AssertionError("real write reached")
    ftm.pm, ftm.base = Pm(), 0
    h2 = fp.Harness(*fresh()[:1], [])
    g = fp.GuardedTm(ftm, h2)
    blocked = []
    for name in ("pm.write_uchar", "warp", "set_invincible"):
        try:
            (g.pm.write_uchar if name == "pm.write_uchar" else getattr(g, name))
        except fp.Abort:
            blocked.append(name)
    check("6' pm 쓰기·기타 쓰기 속성 차단, 읽기(pm.read_uint, menu_open)는 통과",
          blocked == ["pm.write_uchar", "warp", "set_invincible"] and g.pm.read_uint(0) == 7 and g.menu_open() is False, str(blocked))
    h2.pad.close()

    # 6'' real Escape.fire normal path (fake quit-out presses + fake reload): planned buttons only
    pad, rec = fresh()
    h = fp.Harness(pad, [])
    h.calls = fp.default_calls(pad, B)
    esc = watch.Escape(pad, nms=[], log=lambda *a: None)
    planned = [B.XUSB_GAMEPAD_START, B.XUSB_GAMEPAD_DPAD_LEFT, B.XUSB_GAMEPAD_A]

    def fake_quit(tm, p, **k):
        p.neutral()
        for b in planned:
            p.press(b, 0.0)
        return 1.0
    keep = quitout.quit_out, quitout.reload, env.make_telemetry
    quitout.quit_out = fake_quit
    quitout.reload = lambda p, timeout=40.0: 0.5
    env.make_telemetry = lambda names=None: FakeTm()
    n0 = len(rec.sent)
    try:
        s = fp.execute(h, lambda: esc.fire("t", "shake", tm=fp.GuardedTm(FakeTm(), h)))
    finally:
        quitout.quit_out, quitout.reload, env.make_telemetry = keep
    ud = next(e for e in h.events if e["ev"] == "unfreeze_done")
    names = {getattr(b, "name", b) for b in planned}
    owner = [r for r in rec.sent[n0:] if r["buttons"]]
    ok, why = order_ok(h)
    check("6'' 실제 Escape.fire 정상 경로: 순서 맞음, outcome=normal, 소유자 구간 버튼은 예정 목록(START·LEFT·A)뿐",
          ok and s["ok"] and ud and all(set(r["buttons"]) <= names for r in owner[:len(planned)]) and len(owner) >= len(planned),
          why + json.dumps(s))
    pad.close()

    # 7 --help / argument errors: no pad, no game, no records
    runs = ROOT / "data" / "runs"
    before = set(runs.glob("*freeze_probe*")) if runs.exists() else set()
    script = str(ROOT / "experiments" / "freeze_probe_live.py")
    rc = {a: subprocess.run([sys.executable, script, *a.split()], capture_output=True, text=True, timeout=60).returncode
          for a in ("--help", "bogus", "nudge --stick 2 0", "quit --variant C", "")}
    probe = ("import sys, json; sys.path.insert(0, r'%s'); import freeze_probe_live as m\n"
             "for argv in (['--help'], ['bogus'], ['nudge', '--stick', '2', '0'], []):\n"
             "    try: m.main(argv)\n"
             "    except SystemExit: pass\n"
             "bad = ['control', 'vgamepad', 'env', 'ctl', 'quitout', 'souls.watch', 'dsr_telemetry', 'pymem', 'botlock']\n"
             "print(json.dumps([n for n in bad if n in sys.modules]))") % str(ROOT / "experiments")
    r = subprocess.run([sys.executable, "-I", "-c", probe], capture_output=True, text=True, timeout=60)
    loaded = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else ["?"]
    after = set(runs.glob("*freeze_probe*")) if runs.exists() else set()
    check("7 --help 0, 인자 오류 2 (모드 없음·모르는 모드·스틱 범위·C 변형)",
          rc == {"--help": 0, "bogus": 2, "nudge --stick 2 0": 2, "quit --variant C": 2, "": 2}, str(rc))
    check("   그 경로에서 장치·게임 모듈을 import하지 않고 기록 파일도 안 만듦", loaded == [] and after == before,
          f"{loaded} {r.stderr[-300:]}")

    if FAILED:
        print("\nFAILED:\n  " + "\n  ".join(FAILED))
        raise SystemExit(1)
    print("freeze_probe_live_test: 전부 통과")


if __name__ == "__main__":
    main()
