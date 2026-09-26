"""observe_record 오프라인 테스트 — 게임·컨트롤러 없이 가짜 읽기기로 검증한다 (Phase 1, 2026-09-26).

  python observe_record_test.py

검사:
  · 출력 가능한 모듈(vgamepad·control·env·feed·souls·botlock)을 import 도 생성도 하지 않고 유효한 세션을 쓴다
  · 소스에 입력 주입·메모리 쓰기 호출이 없다 (AST), GameReader 가 쓰기 메서드를 막는다
  · F9 마커: 상승 에지 + 300 ms 디바운스, 패드 줄에 영향 없음
  · 핸들 → 포인터 대체(id_src), 못 찾은 락온 핸들
  · 적 읽기 실패 = 그 스냅샷에서 빠짐(빈칸), 가짜 적 없음. bot_phantom 은 진단값일 뿐 적을 빼지 않는다
  · Ctrl+C 로 끝내면 hdr 로 시작, sys:end(요약 포함)로 끝
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import observe_record as O

HERE = Path(__file__).resolve().parent
FORBIDDEN_MODS = ("vgamepad", "control", "env", "feed", "souls", "botlock")
TMP = Path(tempfile.mkdtemp(prefix="observe_test_"))


# ── 가짜들 ──

class FakeClock:
    def __init__(self):
        self.ns = 0

    def __call__(self) -> int:
        return self.ns

    def adv(self, ms: float) -> None:
        self.ns += int(ms * 1e6)


def chr_(npc, x, y, z, hp=75, mhp=75, anim=-1, team=6, heading=1.0, sp=0, msp=0):
    return SimpleNamespace(npc_param=npc, x=x, y=y, z=z, hp=hp, max_hp=mhp, anim=anim, team=team, heading=heading, sp=sp, max_sp=msp)


class FakeReader:
    """GameReader 와 같은 겉모습. chars: ptr → (Chr, handle). fail: 이번 틱에 read_chr 가 None 을 줄 ptr."""
    pid = 4242

    def __init__(self):
        self.pp = 0x1000
        self.player = chr_(0, 0.0, 0.0, 0.0, hp=500, mhp=500, anim=0, team=1, sp=90, msp=100)
        self.chars: dict[int, tuple] = {}
        self.fail: set[int] = set()
        self.lock = -1

    def player_ptr(self):
        return self.pp

    def chr_ptrs(self):
        return [self.pp, *self.chars]

    def read_chr(self, p):
        if p == self.pp:
            return self.player
        if p in self.fail:
            return None
        return self.chars[p][0]

    def handle(self, p):
        return 0x10000001 if p == self.pp else self.chars[p][1]

    def lock_target(self):
        return self.lock

    def cam_yaw(self):
        return 0.5

    def pos_xz(self, p):
        c = self.chars[p][0]
        return c.x, c.z

    def flags1(self, p):
        return 0x808400

    def vt_kind(self, p):
        return "enemy"


class FakePads:
    def __init__(self):
        self.state = {0: (1, 0, 0, 0, 0, 0, 0, 0), 1: None, 2: None, 3: None}

    def read(self):
        return dict(self.state)


class FakeKeys:
    def __init__(self):
        self.down = False

    def f9_down(self):
        return self.down


def rows_of(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def make(name: str, reader=None, clock=None):
    return O.Observer(reader or FakeReader(), FakePads(), FakeKeys(), TMP / name, clock=clock or FakeClock(), wall=lambda: 1_790_300_000_000_000_000)


def world_rows(obs) -> list[dict]:
    return [r for r in list(obs.q.queue) if r["k"] == "w"]


# ── 검사 ──

def test_imports_and_static() -> None:
    # (1) 새 인터프리터에서 observe_record 와 그것이 쓰는 dsr_telemetry 를 불러도 출력 가능한 모듈이 안 올라온다
    code = ("import sys; sys.path.insert(0, '.'); import observe_record, dsr_telemetry; "
            f"print([m for m in {FORBIDDEN_MODS!r} if m in sys.modules or any(k.startswith(m + '.') for k in sys.modules)])")
    out = subprocess.run([sys.executable, "-c", code], cwd=HERE, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "[]", out.stdout
    # (2) 소스 AST: 금지 import 없음, 입력 주입·메모리 쓰기 호출 없음
    tree = ast.parse((HERE / "observe_record.py").read_text(encoding="utf-8"))
    mods = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    mods |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert not mods & set(FORBIDDEN_MODS), mods & set(FORBIDDEN_MODS)
    names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    bad = {x for x in names if x.startswith("write_") or x in {
        "SendInput", "keybd_event", "mouse_event", "SetWindowsHookExW", "SetWindowsHookExA", "XInputSetState",
        "WriteProcessMemory", "set_dbg", "pos_warp", "safe_warp", "bonfire_warp", "set_last_bonfire", "kill_player",
        "quit_to_title", "set_hp", "face", "VX360Gamepad", "VDS4Gamepad"}}
    assert not bad, bad
    # (3) GameReader: 쓰기·워프 메서드는 이름부터 막히고, 속성도 못 바꾼다
    class Spy:
        def __getattr__(self, n):
            raise AssertionError(f"GameReader 가 '{n}' 를 넘겼다")
    g = O.GameReader(Spy())
    for n in ("pm", "write_int", "set_dbg", "pos_warp", "safe_warp", "bonfire_warp", "set_last_bonfire", "kill_player", "quit_to_title", "set_hp", "face"):
        try:
            getattr(g, n)
            raise AssertionError(f"{n} 가 막히지 않았다")
        except AttributeError:
            pass
    try:
        g.x = 1
        raise AssertionError("GameReader 속성을 바꿀 수 있다")
    except AttributeError:
        pass
    # (4) 이 테스트 프로세스에서도 세션을 다 돈 뒤 금지 모듈이 안 올라왔다 (맨 끝에서 다시 본다)
    print("ok  import·정적 검사: 금지 모듈 없음, 쓰기/주입 호출 없음, GameReader 차단")


def test_marker_debounce() -> None:
    clk = FakeClock()
    obs = make("mk.jsonl", clock=clk)
    obs.open()
    obs.pad_step()                                     # 첫 폴링: pad_found + 첫 상태
    base_pad = [r for r in list(obs.q.queue) if r["k"] == "pad"]
    # F9: 누름(0) · 뗌(50) · 다시 누름(100 — 디바운스 안) · 계속 누름 · 뗌 · 누름(450 — 통과) · 누른 채 유지
    seq = [(0, True), (50, False), (100, True), (150, True), (200, False), (450, True), (500, True), (900, True)]
    last = 0
    for t, d in seq:
        clk.adv(t - last)
        last = t
        obs.keys.down = d
        obs.pad_step()
    mk = [r for r in list(obs.q.queue) if r["k"] == "mk"]
    assert [r["n"] for r in mk] == [1, 2], mk
    assert [r["ms"] for r in mk] == [0.0, 450.0], mk
    pads = [r for r in list(obs.q.queue) if r["k"] == "pad"]
    assert pads == base_pad and len(pads) == 1, pads      # F9 는 패드 줄을 만들지도 바꾸지도 않는다
    assert obs.pads.state[0] == (1, 0, 0, 0, 0, 0, 0, 0)
    # 진짜 패드 변화는 한 줄, packet 번호만 바뀐 건 줄 없음
    obs.pads.state[0] = (2, 0, 0, 0, 0, 0, 0, 0)
    obs.pad_step()
    obs.pads.state[0] = (3, 4096, 0, 255, -1200, 32767, 0, 0)
    obs.pad_step()
    pads = [r for r in list(obs.q.queue) if r["k"] == "pad"]
    assert len(pads) == 2 and pads[-1]["btn"] == 4096 and pads[-1]["ly"] == 32767, pads
    obs.pads.state[0] = None
    obs.pad_step()
    assert any(r.get("ev") == "pad_lost" for r in list(obs.q.queue))
    s = obs.close("test")
    assert s["markers"] == 2
    print("ok  F9 디바운스: 마커 2개(0 ms, 450 ms), 패드 줄 영향 없음, pad_lost 기록")


def test_identity_and_lock() -> None:
    fr = FakeReader()
    fr.chars = {0x2000: (chr_(254000, 3.0, 0.2, 4.0), 0x10000abc),       # 핸들 있음
                0x3000: (chr_(255010, 6.0, -0.5, 0.0, hp=85, mhp=85), 0)}  # 핸들 0 → 포인터 대체
    fr.lock = 0x10000abc
    obs = make("id.jsonl", reader=fr)
    obs.open()
    obs.world_step()
    w = world_rows(obs)[-1]
    by = {e["npc"]: e for e in w["e"]}
    assert by[254000]["id"] == "h:10000abc#0" and by[254000]["id_src"] == "handle", by[254000]
    assert by[255010]["id"] == "p:3000#0" and by[255010]["id_src"] == "ptr", by[255010]
    assert w["lock"] == {"h": 0x10000abc, "resolved": True, "id": "h:10000abc#0"}, w["lock"]
    assert "lock" in by[254000]["why"] and "near" in by[254000]["why"]
    e = by[255010]
    assert e["hp_raw"] == 85 and e["max_hp_raw"] == 85 and e["alive_derived"] is True and e["alive_rule"] == "hp_gt_zero"
    assert "alive" not in e and "is_attacking" not in e
    # 목록 어디에도 없는 락온 핸들
    fr.lock = 0x1000dead
    obs.world_step()
    w = world_rows(obs)[-1]
    assert w["lock"] == {"h": 0x1000dead, "resolved": False, "id": None}, w["lock"]
    assert obs.lock_unresolved == 1
    # 락온 없음(-1)
    fr.lock = -1
    obs.world_step()
    assert world_rows(obs)[-1]["lock"] == {"h": -1, "resolved": None, "id": None}
    obs.close("test")
    print("ok  신원: handle→ptr 대체(id_src), 락온 resolved / unresolved / 없음")


def test_gap_not_synthetic() -> None:
    fr = FakeReader()
    fr.chars = {0x2000: (chr_(254000, 3.0, 0.0, 4.0), 0x10000001),
                0x4000: (chr_(254013, 5.0, 0.0, 5.0, hp=150, mhp=150), 0x10000002)}   # PHANTOM_NPC
    obs = make("gap.jsonl", reader=fr)
    obs.open()
    obs.world_step()
    fr.fail = {0x2000}
    obs.world_step()
    fr.fail = set()
    obs.world_step()
    ws = world_rows(obs)
    ids = [[e["id"] for e in w["e"]] for w in ws]
    assert ids[0] == ["h:10000001#0", "h:10000002#0"], ids
    assert ids[1] == ["h:10000002#0"], ids                      # 빈칸 — 이전 값을 복사하거나 보간하지 않음
    assert ids[2] == ["h:10000001#0", "h:10000002#0"], ids
    assert [w["e_fail"] for w in ws] == [0, 1, 0] and obs.enemy_read_fail == 1
    ph = [e for e in ws[0]["e"] if e["npc"] == 254013][0]
    assert ph["bot_phantom"] is True and ph["team_bot"] == 6        # 진단값만, 적은 그대로 남는다
    # 로딩: 플레이어를 못 읽으면 월드 줄 없이 loading, 돌아오면 epoch+1 로 신원이 새로 붙는다
    fr.pp = None
    obs.world_step()
    fr.pp = 0x1000
    obs.world_step()
    assert world_rows(obs)[-1]["e"][0]["id"].endswith("#1")
    evs = [r.get("ev") for r in list(obs.q.queue) if r["k"] == "sys"]
    assert "loading" in evs and "loaded" in evs
    obs.close("test")
    print("ok  읽기 실패 = 빈칸(e_fail), 가짜 적 없음 · bot_phantom 은 표시만 · 로딩 뒤 epoch+1")


def test_ctrl_c_session() -> None:
    fr = FakeReader()
    fr.chars = {0x2000: (chr_(254000, 3.0, 0.0, 4.0), 0x10000001)}
    obs = O.Observer(fr, FakePads(), FakeKeys(), TMP / "run.jsonl")     # 진짜 시계·스레드
    calls = {"n": 0}

    def sleep(s):
        calls["n"] += 1
        time.sleep(s)
        if calls["n"] == 5:                              # 약 1 s 뒤 사용자가 Ctrl+C
            raise KeyboardInterrupt

    s = obs.run(sleep=sleep)
    rows = rows_of(TMP / "run.jsonl")
    assert rows[0]["k"] == "hdr" and rows[0]["v"] == O.SCHEMA_V and rows[0]["ms"] == 0.0
    assert rows[-1]["k"] == "sys" and rows[-1]["ev"] == "end" and rows[-1]["reason"] == "ctrl_c"
    for k in ("world_rows", "pad_rows", "markers", "enemy_read_fail", "read_ms_p50", "read_ms_p95", "path"):
        assert k in rows[-1], k
    assert all("k" in r and "ms" in r for r in rows)
    for k in ("w", "pad"):
        ms = [r["ms"] for r in rows if r["k"] == k]
        assert ms == sorted(ms), k                        # 같은 종류 안에서는 시간 순
    nw = sum(r["k"] == "w" for r in rows)
    assert 8 <= nw <= 13, nw                             # 약 1 s × 10 Hz
    assert s["world_rows"] == nw and s["path"].endswith("run.jsonl")
    O.print_summary(s)
    print(f"ok  Ctrl+C: hdr … sys:end, 월드 {nw} 줄, 요약 필드 전부")


if __name__ == "__main__":
    test_imports_and_static()
    test_marker_debounce()
    test_identity_and_lock()
    test_gap_not_synthetic()
    test_ctrl_c_session()
    leaked = [m for m in FORBIDDEN_MODS if m in sys.modules or any(k.startswith(m + ".") for k in sys.modules)]
    assert not leaked, leaked
    print(f"ok  세션 뒤에도 금지 모듈 없음  ·  출력: {TMP}")
    print("전부 통과")
