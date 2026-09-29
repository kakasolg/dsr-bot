"""Is Steam offline? — for the radar's status line and as the gate for anything that writes game memory (warp).

  python steam_state.py      prints the verdict and why

Reads only: the Steam offline setting (config/loginusers.vdf "WantsOfflineMode" of the most recent user, Steam folder from
the registry) and how many outside TCP connections steam.exe and the game have (iphlpapi GetExtendedTcpTable). Offline =
the setting is on AND neither process talks to anything outside this PC. The setting alone isn't enough — it is what Steam
was told at its last start, so the connection count is the second witness. Anything unreadable → None ("unknown"), which
callers must treat like "not offline". Windows only; elsewhere always None.
"""
from __future__ import annotations

import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

GAME_EXE = "DarkSoulsRemastered.exe"
STEAM_EXE = "steam.exe"
_STATES = (3, 4, 5)       # MIB_TCP_STATE: SYN_SENT, SYN_RCVD, ESTABLISHED — a connection being made or in use
_STATE_NAMES = {3: "SYN_SENT", 4: "SYN_RCVD", 5: "ESTABLISHED"}


# ── pure (tested in tests/steam_state_test.py) ─────────────────────────────
def parse_loginusers(text: str, auto_login: str | None = None) -> bool | None:
    """WantsOfflineMode of the Steam user that logs in: the one marked MostRecent, else AutoLoginUser, else the only one."""
    users = []
    for m in re.finditer(r'"\d+"\s*\{([^{}]*)\}', text):
        kv = {k.lower(): v for k, v in re.findall(r'"([^"]+)"\s+"([^"]*)"', m.group(1))}
        users.append(kv)
    if not users:
        return None
    pick = ([u for u in users if u.get("mostrecent") == "1"]
            or [u for u in users if auto_login and u.get("accountname", "").lower() == auto_login.lower()]
            or (users if len(users) == 1 else []))
    if not pick or "wantsofflinemode" not in pick[0]:
        return None
    return pick[0]["wantsofflinemode"] == "1"


def judge(pref: bool | None, steam_running: bool | None, steam_conns: int | None, game_conns: int | None) -> dict:
    """→ {"offline": True/False/None, "why": [short reasons]}. False as soon as anything says online."""
    why, online, unknown = [], False, False
    if pref is None:
        why.append("Steam setting unreadable"); unknown = True
    else:
        why.append("Steam set offline" if pref else "Steam set ONLINE"); online |= not pref
    if steam_running is False:
        why.append("Steam not running"); unknown = True
    elif steam_conns is None:
        why.append("steam.exe connections unreadable"); unknown = True
    else:
        why.append(f"steam.exe {steam_conns} outside conn"); online |= steam_conns > 0
    if game_conns is None:
        why.append("game connections unreadable"); unknown = True
    else:
        why.append(f"game {game_conns} outside conn"); online |= game_conns > 0
    return {"offline": False if online else None if unknown else True, "why": why}


def _outside(addr: bytes) -> bool:
    if len(addr) == 4:
        return not (addr[0] == 127 or addr == b"\0\0\0\0")
    return addr not in (bytes(15) + b"\1", bytes(16)) and not addr.startswith(b"\0" * 10 + b"\xff\xff\x7f")


# ── Windows reads ──────────────────────────────────────────────────────────
def _steam_dir() -> tuple[str | None, str | None]:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            path = winreg.QueryValueEx(k, "SteamPath")[0]
            try:
                auto = winreg.QueryValueEx(k, "AutoLoginUser")[0]
            except OSError:
                auto = None
        return path, auto
    except Exception:
        return None, None


def offline_setting() -> bool | None:
    path, auto = _steam_dir()
    if not path:
        return None
    try:
        with open(f"{path}/config/loginusers.vdf", encoding="utf-8", errors="replace") as f:
            return parse_loginusers(f.read(), auto)
    except OSError:
        return None


def pids(exe: str) -> list[int]:
    import ctypes
    from ctypes import wintypes

    class PE(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_void_p), ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                    ("szExeFile", ctypes.c_wchar * 260)]
    k = ctypes.windll.kernel32
    k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snap = k.CreateToolhelp32Snapshot(2, 0)          # TH32CS_SNAPPROCESS
    out, e = [], PE()
    e.dwSize = ctypes.sizeof(PE)
    try:
        ok = k.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            if e.szExeFile.lower() == exe.lower():
                out.append(e.th32ProcessID)
            ok = k.Process32NextW(snap, ctypes.byref(e))
    finally:
        k.CloseHandle(snap)
    return out


def outside_conns(pid_set: set[int]) -> int | None:
    """Outside TCP connections (IPv4 + IPv6) owned by these processes."""
    conns = outside_conn_list(pid_set)
    return None if conns is None else len(conns)


def outside_conn_list(pid_set: set[int]) -> list[str] | None:
    """The same connections as "address:port STATE" — so an ONLINE verdict says where Steam was talking to."""
    import ctypes
    import ipaddress
    ip = ctypes.windll.iphlpapi
    out = []
    for family, row_size, addr_at, pid_at, state_at, alen in ((2, 24, 12, 20, 0, 4), (23, 56, 24, 52, 48, 16)):
        size = ctypes.c_ulong(0)
        ip.GetExtendedTcpTable(None, ctypes.byref(size), False, family, 5, 0)     # TCP_TABLE_OWNER_PID_ALL
        buf = ctypes.create_string_buffer(size.value + 4096)
        size = ctypes.c_ulong(len(buf))
        if ip.GetExtendedTcpTable(buf, ctypes.byref(size), False, family, 5, 0) != 0:
            return None
        raw = buf.raw
        count = int.from_bytes(raw[:4], "little")
        for i in range(count):
            r = raw[4 + i * row_size: 4 + (i + 1) * row_size]
            pid = int.from_bytes(r[pid_at:pid_at + 4], "little")
            state = int.from_bytes(r[state_at:state_at + 4], "little")
            if pid in pid_set and state in _STATES and _outside(r[addr_at:addr_at + alen]):
                port_at = addr_at + (4 if alen == 4 else 20)                          # dwRemotePort, network order
                port = int.from_bytes(r[port_at:port_at + 2], "big")
                out.append(f"{ipaddress.ip_address(r[addr_at:addr_at + alen])}:{port} {_STATE_NAMES.get(state, state)}")
    return out


def check() -> dict:
    """The verdict now (≈ a few ms). Never raises."""
    if sys.platform != "win32":
        return {"offline": None, "why": ["not Windows"]}
    try:
        steam = set(pids(STEAM_EXE))
        game = set(pids(GAME_EXE))
        pref = offline_setting()
        sl = outside_conn_list(steam) if steam else None
        gl = outside_conn_list(game) if game else []     # game not running: nothing of its own to leak
        out = judge(pref, bool(steam), None if sl is None else len(sl), None if gl is None else len(gl))
        out["game_running"] = bool(game)
        out["conns"] = [f"steam.exe {c}" for c in (sl or [])[:3]] + [f"game {c}" for c in (gl or [])[:3]]
        return out
    except Exception as e:
        return {"offline": None, "why": [f"check failed: {type(e).__name__}"]}


if __name__ == "__main__":
    v = check()
    print({True: "OFFLINE", False: "ONLINE", None: "UNKNOWN"}[v["offline"]], "—", ", ".join(v["why"]))
