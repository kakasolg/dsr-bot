"""Start / stop the OBS recording for a bot chain, so death scenes can be cut into clips (clip.py) and judged with MoKa.

  python obs_rec.py start     launch OBS (tray) if it isn't running, then start recording
  python obs_rec.py stop      stop recording → prints the video path
  python obs_rec.py status

Talks to obs-websocket v5 on 127.0.0.1:4455 with the password from OBS's own config (never copied into the repo).
OBS records the "DSR Capture" game-capture source (DarkSoulsRemastered.exe) to ~/Videos as hybrid mp4; the file name is
OBS's local start time. On start this also writes data/runs/obs_<YYYYmmdd_HHMMSS>.json with the wall time OBS answered
StartRecord, which clip.py prefers over the file name.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
OBS = Path(r"C:\Program Files\obs-studio\bin\64bit\obs64.exe")
CFG = Path(os.environ.get("APPDATA", "")) / "obs-studio" / "plugin_config" / "obs-websocket" / "config.json"
HOST, PORT = "127.0.0.1", 4455


class Ws:
    """Just enough of RFC 6455 for obs-websocket's text frames (client → server masked, no fragmentation)."""

    def __init__(self, timeout: float = 5.0):
        self.s = socket.create_connection((HOST, PORT), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall((f"GET / HTTP/1.1\r\nHost: {HOST}:{PORT}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                        f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n"
                        "Sec-WebSocket-Protocol: obswebsocket.json\r\n\r\n").encode())
        head = b""
        while b"\r\n\r\n" not in head:
            head += self.s.recv(1)
        if b" 101 " not in head.split(b"\r\n")[0]:
            raise ConnectionError(head.decode(errors="replace"))

    def _read(self, n: int) -> bytes:
        b = b""
        while len(b) < n:
            c = self.s.recv(n - len(b))
            if not c:
                raise ConnectionError("closed")
            b += c
        return b

    def send(self, obj: dict) -> None:
        data = json.dumps(obj).encode()
        n = len(data)
        hdr = bytes([0x81]) + (bytes([0x80 | n]) if n < 126 else bytes([0x80 | 126]) + struct.pack(">H", n))
        mask = os.urandom(4)
        self.s.sendall(hdr + mask + bytes(c ^ mask[i % 4] for i, c in enumerate(data)))

    def recv(self) -> dict:
        while True:
            b0, b1 = self._read(2)
            n = b1 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8))[0]
            data = self._read(n)
            if b0 & 0x0F == 1:
                return json.loads(data)


def connect() -> Ws:
    ws = Ws()
    hello = ws.recv()["d"]
    ident = {"rpcVersion": 1}
    if "authentication" in hello:
        pw = json.loads(CFG.read_text(encoding="utf-8"))["server_password"]
        a = hello["authentication"]
        secret = base64.b64encode(hashlib.sha256((pw + a["salt"]).encode()).digest()).decode()
        ident["authentication"] = base64.b64encode(hashlib.sha256((secret + a["challenge"]).encode()).digest()).decode()
    ws.send({"op": 1, "d": ident})
    if ws.recv().get("op") != 2:
        raise ConnectionError("not identified")
    return ws


def call(ws: Ws, kind: str, ready_s: float = 20.0, **data) -> dict:
    end = time.time() + ready_s
    while True:
        rid = f"{kind}-{time.time()}"
        ws.send({"op": 6, "d": {"requestType": kind, "requestId": rid, "requestData": data}})
        while True:
            m = ws.recv()
            if m.get("op") == 7 and m["d"]["requestId"] == rid:
                break
        st = m["d"]["requestStatus"]
        if st["result"]:
            return m["d"].get("responseData") or {}
        if st.get("code") == 207 and time.time() < end:   # 207 NotReady: OBS still loading right after launch
            time.sleep(1.0)
            continue
        raise RuntimeError(f"{kind}: {st.get('code')} {st.get('comment', '')}")


def running() -> bool:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq obs64.exe"], capture_output=True, text=True).stdout
    return "obs64.exe" in out


def ensure_obs(wait_s: float = 30.0) -> Ws:
    if not running():
        # OBS has to start from its own bin folder (it finds its data relative to cwd)
        subprocess.Popen([str(OBS), "--minimize-to-tray", "--disable-shutdown-check"], cwd=str(OBS.parent),
                         creationflags=subprocess.DETACHED_PROCESS)
    end = time.time() + wait_s
    while True:
        try:
            return connect()
        except OSError:
            if time.time() > end:
                raise
            time.sleep(1.0)


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "start":
        ws = ensure_obs()
        if call(ws, "GetRecordStatus").get("outputActive"):
            print("obs: already recording")
            return 0
        call(ws, "StartRecord")
        t = time.time()
        stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(t))
        (ROOT / "data" / "runs" / f"obs_{stamp}.json").write_text(json.dumps({"start_epoch": round(t, 3)}), encoding="utf-8")
        print(f"obs: recording from {stamp}")
    elif cmd == "stop":
        ws = connect()
        if not call(ws, "GetRecordStatus").get("outputActive"):
            print("obs: not recording")
            return 0
        print(f"obs: stopped → {call(ws, 'StopRecord').get('outputPath')}")
    else:
        try:
            print(f"obs: {call(connect(), 'GetRecordStatus')}")
        except OSError as e:
            print(f"obs: not reachable ({e})")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
