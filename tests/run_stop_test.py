"""P0-B: user stop (Ctrl+C) in run.py — neutral first, no quit-out; the final neutral comes before the bot lock is released.
run.main() with every collaborator faked (no game, no pad, no files outside a temp folder).  python tests/run_stop_test.py

Checks:
  · KeyboardInterrupt in a mission: the first thing after it is pad.neutral(); Escape.fire is never called; quit-out and
    ledge nudges are switched off for the cleanup; camera follow is stopped; a user_stop event is written
  · other exceptions: unchanged — Escape.fire(..., "shake") as before
  · every path: the last pad call is neutral and it comes before the bot lock's release, even if cleanup raises
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import json
import sys
import tempfile
import types
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import blackbox
import botlock
import control
import env
import navmesh
import run
import track
from souls import camera, field, missions, moves, props, watch, weapons

TRACE: list = []


def check(name: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        print("     trace:", TRACE)
        raise SystemExit(1)


class FakePad:
    def __init__(self):
        TRACE.append("pad.create")

    def neutral(self):
        TRACE.append("neutral")

    def __getattr__(self, name):                  # any other pad input is recorded as such
        return lambda *a, **k: TRACE.append(f"pad.{name}")


class FakeTm:
    def right_weapon(self): return 0
    def char_stats(self): return {}
    def equipment(self): return {}
    def snapshot(self, within=0.0): return None
    def stats(self): return {}


class FakeEsc:
    last = None

    def __init__(self, pad, nms, log=None, events=None):
        self.escaping, self.quit_ok, self.nudge_ok = False, True, True
        FakeEsc.last = self

    def start(self): return self
    def stop(self): TRACE.append("esc.stop")

    def fire(self, why, kind, *a):
        TRACE.append(("fire", kind))
        return {}


class FakeCam:
    def __init__(self, *a, **k): pass
    def start(self): return self
    def stop(self): TRACE.append("cam.stop")
    def stats(self): return "cam"


class FakeLock:
    def acquire(self): return True
    def release(self): TRACE.append("lock.release")


class FakeBox:
    boom = False

    def __init__(self, *a, **k): pass
    def start(self): return self

    def stop(self):
        TRACE.append("bbox.stop")
        if FakeBox.boom:
            raise RuntimeError("cleanup failed")


class FakeMissions:
    exc: BaseException | None = None

    def __init__(self, *a, **k): pass

    def to_merchant(self):
        TRACE.append("mission")
        raise FakeMissions.exc


def install(tmp: Path) -> None:
    run.ROOT = tmp
    control.pad_lock_held = lambda: False
    control.focus_game = lambda: TRACE.append("focus") or True
    control.Pad = FakePad
    env.make_telemetry = lambda names=None: FakeTm()
    track.Track = lambda path: types.SimpleNamespace(attach=lambda tm: types.SimpleNamespace(
        say=lambda m: None, follow=lambda mv: None))
    navmesh.Navmesh = lambda m: types.SimpleNamespace(edge_kinds=lambda: None)
    props.attach = lambda nms, log: None
    moves.Moves = lambda tm, pad: types.SimpleNamespace(weapon=None)
    weapons.of = lambda w: types.SimpleNamespace(name="x", combo=1, reach=1.0, use_heavy=False)
    watch.Escape = FakeEsc
    watch.Blood = lambda log=None: types.SimpleNamespace(start=lambda: types.SimpleNamespace(stop=lambda: None))
    blackbox.BlackBox = FakeBox
    field.Field = lambda *a, **k: types.SimpleNamespace(alive=lambda: True, wait_respawn=lambda t: True)
    camera.CamFollow = FakeCam
    missions.Missions = FakeMissions
    botlock.BotLock = FakeLock


def go(exc: BaseException, boom: bool = False) -> BaseException | None:
    TRACE.clear()
    FakeMissions.exc, FakeBox.boom = exc, boom
    sys.argv = ["run.py", "merchant"]
    try:
        run.main()
    except BaseException as e:                    # noqa: BLE001 — the test wants to see whatever main lets out
        return e
    return None


def after(x) -> list:
    return TRACE[TRACE.index(x) + 1:]


def final_order_ok() -> bool:
    pad_calls = [i for i, x in enumerate(TRACE) if x == "neutral" or (isinstance(x, str) and x.startswith("pad."))]
    rel = TRACE.index("lock.release")
    return bool(pad_calls) and TRACE[pad_calls[-1]] == "neutral" and pad_calls[-1] < rel


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="runstop_"))
    install(tmp)

    # 1) Ctrl+C mid-mission
    e = go(KeyboardInterrupt())
    check("Ctrl+C: KeyboardInterrupt 그대로 나감", isinstance(e, KeyboardInterrupt))
    check("Ctrl+C: 미션 바로 다음이 neutral", after("mission")[:1] == ["neutral"])
    check("Ctrl+C: 퀵 종료(fire) 안 부름", not any(isinstance(x, tuple) and x[0] == "fire" for x in TRACE))
    check("Ctrl+C: 정리 중 퀵 종료·턱 되돌림 꺼짐", FakeEsc.last.quit_ok is False and FakeEsc.last.nudge_ok is False)
    check("Ctrl+C: 카메라 따라가기를 정리 대기 전에 멈춤", "cam.stop" in after("mission")[:3])
    check("Ctrl+C: 마지막 패드 호출은 neutral, 잠금 풀기 전", final_order_ok())
    events = [json.loads(l) for f in (tmp / "data" / "runs").glob("*_merchant.jsonl") for l in f.read_text(encoding="utf-8").splitlines()]
    check("Ctrl+C: user_stop 사건 기록", any(ev.get("ev") == "user_stop" for ev in events))

    # 2) other exception: unchanged — shake quit-out
    e = go(RuntimeError("bug"))
    check("오류: 예외 그대로 나감", isinstance(e, RuntimeError))
    check("오류: 예전처럼 fire(shake)", ("fire", "shake") in TRACE)
    check("오류: 마지막 패드 호출은 neutral, 잠금 풀기 전", final_order_ok())

    # 3) cleanup itself raises — the final neutral and the release still happen, in that order
    e = go(KeyboardInterrupt(), boom=True)
    check("정리 실패: 그래도 neutral → 잠금 풀기", "lock.release" in TRACE and final_order_ok())
    check("정리 실패: fire 안 부름", not any(isinstance(x, tuple) and x[0] == "fire" for x in TRACE))
    print("run_stop_test: 전부 통과")


if __name__ == "__main__":
    main()
