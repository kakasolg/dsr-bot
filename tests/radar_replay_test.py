"""radar recording / replay / controller / floor offline test — no game.

  python tests/radar_replay_test.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import radar_mesh
import radar_pad
import radar_record as R
import radar_server as S

fails = 0


def check(name, cond):
    global fails
    print(("  ok   " if cond else "  FAIL ") + name)
    fails += 0 if cond else 1


def snap(x, t):
    return {"type": "snap", "t": t, "player": {"x": x, "y": 0.0, "z": 0.0, "hp": 100, "max_hp": 100}, "chars": []}


print("기록")
d = Path(tempfile.mkdtemp())
st = S.State(props=[], items=[], enemies={})
st.recorder = R.Recorder(d)
for k in range(5):
    st.put(snap(float(k), k))
    time.sleep(0.02)
st.put({"type": "pad", "i": 0, "btn": 0x200, "lt": 0, "rtr": 0, "lx": 100, "ly": 0, "rx": 0, "ry": 0})
st.put({"type": "say", "t": 9, "line": "교전: 망자"})
st.recorder.close()
lines = [json.loads(l) for l in st.recorder.path.read_text(encoding="utf-8").splitlines()]
check("받은 메시지가 모두 한 줄씩, 시간(rt) 포함", len(lines) == 7 and all("rt" in l for l in lines) and lines[0]["rt"] <= lines[4]["rt"])
check("패드 상태가 State 에 남음", st.get()["pads"]["0"]["btn"] == 0x200)

print("재생")
msgs = R.load(st.recorder.path)
st2 = S.State(props=[], items=[], enemies={})
rp = R.Replay(st2, msgs, "t")
rp.seek(0.0)
check("처음: 첫 프레임만", st2.get()["snap"]["player"]["x"] == 0.0)
rp.seek(10.0)
check("끝으로 이동: 마지막 프레임·판단 줄(번역)·패드", st2.get()["snap"]["player"]["x"] == 4.0 and st2.get()["says"][-1]["line"] == "fight: Hollow"
      and st2.get()["pads"]["0"]["lx"] == 100)
rp.seek(msgs[2]["rt"] - msgs[0]["rt"])
check("중간으로 되감기: 그 시점 상태로 다시 만듦", st2.get()["snap"]["player"]["x"] == 2.0 and not st2.get()["says"])
rp.command("step", 1)
check("한 프레임 앞으로 (일시정지 됨)", not rp.status()["playing"] and rp.status()["t"] >= msgs[2]["rt"] - msgs[0]["rt"])
check("/state 에 replay 상태", st2.replay is None and "replay" not in st2.get())
st2.replay = rp
check("/state 에 replay 상태 (재생 중)", st2.get()["replay"]["len"] == round(msgs[-1]["rt"] - msgs[0]["rt"], 2))

print("사람 시범 녹화 (observe_record) 재생")
obs = R.load("data/samples/observe_ramp_fight_60s.jsonl")
kinds = {m["type"] for m in obs}
s0 = next(m for m in obs if m["type"] == "snap")
p0 = next(m for m in obs if m["type"] == "pad")
check(f"화면 프레임·패드로 바뀜 ({len(obs)}개)", kinds <= {"snap", "pad", "say"} and "snap" in kinds and "pad" in kinds)
check("플레이어·적 위치 모양이 radar 와 같음", {"x", "y", "z", "heading", "anim", "hp"} <= s0["player"].keys()
      and all(c["team"] == 6 for c in s0["chars"]))
check("오른쪽 트리거는 rtr (rt 는 시간)", "rtr" in p0 and isinstance(p0["rt"], float))

print("컨트롤러")
dp = radar_pad.demo_pad(0.05)
check("데모 입력: RB 눌림, 왼스틱 움직임", dp["btn"] & radar_pad.BUTTONS["rb"] and dp["lx"] != 0)
if sys.platform != "win32":                    # on Windows start() really opens XInput (the pad reader thread)
    check("윈도우가 아니면 읽을 것 없음", radar_pad.start(lambda m: None) is False)

print("바닥 (NavMesh)")
mv = radar_mesh.MeshView([radar_mesh.rect_mesh([(0, 0, 7, 3, 0.0), (7, 0, 10, 3, 0.0), (7, 3, 10, 10, 0.0), (20, 0, 22, 2, 9.0)])])
faces = mv.near(5.0, 0.0, 1.0)
check("근처·같은 층 면만 (9 m 위 면은 빠짐)", len(faces) == 6 and all(abs(f[6]) < 1 for f in faces))
inner = [f for f in faces if (f[0], f[1]) == (7.0, 0.0) or (f[2], f[3]) == (7.0, 0.0)]
shared = sum(bin(f[7]).count("1") for f in faces)
check(f"조각 사이 이음매는 끝(벽)으로 안 봄 — 가장자리 변 {shared}개", shared == 8)
st3 = S.State(props=[], items=[], enemies={})
st3.mesh = mv
st3.put(snap(5.0, 0))
check("/state 에 mesh", len(st3.get()["mesh"]) == 6)

print("전부 통과" if not fails else f"실패 {fails}")
sys.exit(1 if fails else 0)
