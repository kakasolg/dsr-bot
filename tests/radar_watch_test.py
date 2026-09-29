"""radar watch offline test — the read-only sender for hand play sends snapshots, never touches pad or game memory;
the server's "age" follows snapshots only (pad packets alone must not make a frozen map look live). No game.

  python tests/radar_watch_test.py
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import json
import socket
import sys
import threading
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import radar
import radar_server as S
from telemetry import Chr, Snapshot

fails = 0


def check(name, cond):
    global fails
    print(("  ok   " if cond else "  FAIL ") + name)
    fails += 0 if cond else 1


class FakeTm:
    """Polled telemetry (no feed listeners). Any other attribute asked for (set_*, warp, write_*, quit…) is recorded —
    watch must ask for none."""
    def __init__(self):
        self.writes = []

    def snapshot(self, within=None):
        p = Chr(ptr=1, name="me", npc_param=0, team=1, hp=500, max_hp=500, sp=100, max_sp=100,
                x=1.0, y=2.0, z=3.0, dist=0.0, heading=0.0, anim=0)
        return Snapshot(t=time.time(), player=p, chars=[])

    def event_flag(self, fl):
        return False

    def __getattr__(self, name):
        if name != "listeners":              # radar.attach probes for a feed with hasattr
            self.writes.append(name)
        raise AttributeError(name)


sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("127.0.0.1", 0))
sock.settimeout(0.2)
port = sock.getsockname()[1]
radar.PORT = port
_orig = radar.Radar.__init__
radar.Radar.__init__ = lambda self, host="127.0.0.1", port=port: _orig(self, host, port)

print("watch (읽기 전용 발신)")
tm = FakeTm()
r = radar.watch(tm, forever=False)
got, t_end = [], time.time() + 1.0
while time.time() < t_end:
    try:
        got.append(json.loads(sock.recv(65535).decode("utf-8")))
    except socket.timeout:
        pass
kinds = [m.get("type") for m in got]
check("say 한 줄 'radar watch: read-only'", any(m.get("line") == "radar watch: read-only" for m in got))
check(f"스냅샷 계속 보냄 ({kinds.count('snap')}개)", kinds.count("snap") >= 3)
check("플레이어 위치 그대로", any(m.get("type") == "snap" and m["player"]["x"] == 1.0 for m in got))
check(f"게임 쓰기·입력 호출 없음 {tm.writes}", tm.writes == [])
check("패드(control) 안 불러옴", "control" not in sys.modules)
check("Moves 안 따라감 (의도 없음)", r.mv is None)

print("서버 age = 마지막 스냅샷 기준")
st = S.State(props=[], items=[], enemies={})
check("아무것도 없으면 age None", st.get()["age"] is None)
st.put({"type": "pad", "i": 0, "btn": 0})
g = st.get()
check("패드만 오면 age None (waiting), age_any 있음", g["age"] is None and g["age_any"] is not None)
st.put({"type": "snap", "t": 0, "player": {"x": 0, "y": 0, "z": 0}, "chars": []})
st.t_snap -= 30                                  # the last snapshot was 30 s ago…
st.put({"type": "pad", "i": 0, "btn": 1})        # …and pad packets keep coming
g = st.get()
check(f"스냅샷 멈추면 age가 커짐 ({g['age']} s) — 패드가 가리지 않음", g["age"] >= 29)
check(f"age_any는 방금 ({g['age_any']} s)", g["age_any"] < 1)

print("실패 0" if not fails else f"실패 {fails}")
sys.exit(1 if fails else 0)
