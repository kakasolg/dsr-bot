"""radar_server port test — a second server must fail to bind instead of sharing the ports (Windows SO_REUSEADDR let an
old server keep UDP 47800 while a new one served the page, 2026-09-28). No game.

  python tests/radar_port_test.py
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import socket
import subprocess
import sys
from http.server import ThreadingHTTPServer

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import radar_server as S

fails = 0


def check(name, cond):
    global fails
    print(("  ok   " if cond else "  FAIL ") + name)
    fails += 0 if cond else 1


def fails_to(fn) -> bool:
    try:
        x = fn()
    except OSError:
        return True
    x.close() if hasattr(x, "close") else x.server_close()
    return False


def free_port(kind) -> int:
    s = socket.socket(socket.AF_INET, kind)
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


print("UDP")
udp = free_port(socket.SOCK_DGRAM)
a = S.bind_udp(udp)
check("두 번째 bind_udp 실패", fails_to(lambda: S.bind_udp(udp)))


def reuse_udp():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", udp))
    return s


check("SO_REUSEADDR 로 끼어들기도 실패", fails_to(reuse_udp))
a.close()
check("닫으면 다시 잡힘", not fails_to(lambda: S.bind_udp(udp)))

print("HTTP")
http = free_port(socket.SOCK_STREAM)
h = S.RadarHTTPServer(("127.0.0.1", http), None)
check("두 번째 RadarHTTPServer 실패", fails_to(lambda: S.RadarHTTPServer(("127.0.0.1", http), None)))
check("예전 서버(ThreadingHTTPServer, SO_REUSEADDR)도 끼어들지 못함", fails_to(lambda: ThreadingHTTPServer(("127.0.0.1", http), None)))
h.server_close()

print("main: 포트가 쓰이고 있으면 바로 멈춤")
b = S.bind_udp(udp)
r = subprocess.run([sys.executable, "radar_server.py", "--http", str(free_port(socket.SOCK_STREAM)), "--udp", str(udp),
                    "--no-pad", "--no-record", "--no-mesh"], cwd=str(_pl.Path(__file__).resolve().parent.parent),
                   capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
b.close()
check(f"종료 코드 1, 안내 ({r.stderr.strip().splitlines()[0][:70] if r.stderr.strip() else '없음'})",
      r.returncode == 1 and "already in use" in r.stderr and "--http 47802" in r.stderr)

print("실패 0" if not fails else f"실패 {fails}")
sys.exit(1 if fails else 0)
