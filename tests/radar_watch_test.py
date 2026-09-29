"""radar watch offline test — the read-only sender for hand play sends snapshots and the game state (off / title / world /
dead), reconnects after the title or a game restart, never touches pad or game memory;
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

    def menu_open(self):
        return False

    def __getattr__(self, name):
        if name not in ("listeners", "pm"):  # hasattr probes: a feed? a process handle (game_alive)?
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
st_msgs = [m for m in got if m.get("type") == "status"]
check(f"게임 상태 패킷 ({len(st_msgs)}개) — 인게임, 메뉴 닫힘", st_msgs and st_msgs[-1]["game"] == "world" and st_msgs[-1]["menu"] is False)

print("게임 상태 판정 (status_dict)")
now = 1000.0
check("게임 꺼짐", radar.status_dict(False, now, 500, None, now)["game"] == "off")
check("플레이어 방금 봄 → world", radar.status_dict(True, now - 0.2, 500, True, now) == {
    "type": "status", "t": now, "game": "world", "menu": True, "away": None})
check("HP 0 → dead", radar.status_dict(True, now - 0.2, 0, False, now)["game"] == "dead")
t = radar.status_dict(True, now - 12.0, 500, True, now)
check("플레이어 안 보임 → title (타이틀·로딩), 몇 초째인지, 메뉴 값은 버림", t["game"] == "title" and t["away"] == 12.0 and t["menu"] is None)
check("처음부터 안 보임 → title, away None", radar.status_dict(True, 0.0, None, None, now)["away"] is None)
check("tm 없음 = 게임 꺼짐", radar.game_alive(None) is False)

print("다시 붙기 (watch)")
rc = radar.Radar()
calls = []
rc.tm, rc._attached, rc._seen = tm, now, now
check("플레이어 보이면 그대로", rc.reconnect(lambda: calls.append(1), now=now + 5) is False and calls == [])
check("게임은 도는데 30 s 넘게 플레이어 없음 → 다시 붙음", rc.reconnect(lambda: FakeTm(), now=now + radar.REATTACH_S + 1) is True
      and rc.tm is not tm)
rc.tm = None
check("게임 꺼짐 + 못 붙음 → tm None 유지", rc.reconnect(lambda: None, now=now + 100) is False and rc.tm is None)
new = FakeTm()
check("게임 다시 켜짐 → 붙음", rc.reconnect(lambda: new, now=now + 105) is True and rc.tm is new)
check(f"다시 붙는 동안에도 쓰기 없음 {new.writes}", new.writes == [])

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
