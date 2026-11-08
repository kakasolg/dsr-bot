"""combo_judge.py offline: scene parsing from log lines, quota/overlap picking, blind → post_reveal stage."""
import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import combo_judge as J

LOG = """[   10.0]    구역1-1 254000: 시작
[   20.0]       콤보 [near/other/open 뒤O 앞O] 1.0 m 락온 target → backstep_r1 (계획 backstep_r1): 성공 — 처치, 안 맞음 | 내 애니 [690, 253500]
[   22.0]       콤보 [near/other/open 뒤O 앞O] 0.9 m 락온 target → backstep_r1: 성공 — 처치, 안 맞음 | 내 애니 [690, 253500]
[   40.0]       진입 [far/other/idle 뒤O 앞O] 7.5 m (다가옴 3.6 m/s → 닿을 때 4.3 m) 락온 target → jump_r2: 실패 — 공격 중 맞아 끊김 (−152)
[   50.0]    구역2-1 255001: 시작
[   55.0]       뒤잡기 → stabbed
[   60.0]       휘두르는 중 (3004, 1.2 m) — 콤보 안 함, 가드 들고 기다림 (표)
"""
ok = True


def check(name, cond):
    global ok
    print(("ok  " if cond else "FAIL") + "  " + name)
    ok &= bool(cond)


J.log_lines = lambda run: LOG.splitlines()
c = J.candidates("r")
check("다섯 줄 읽음", [x["key"] for x in c] == ["combo:backstep_r1:성공", "combo:backstep_r1:성공", "entry:jump_r2:실패",
                                             "stab", "guard_wait"])
check("구역 따라감", [x["zone"] for x in c] == [1, 1, 1, 2, 2])
check("보여줄 말에 판정 없음", all("성공" not in x["shown"] and "실패" not in x["shown"] for x in c))
p = J.pick(["r"])
check("4 s 안 겹치는 클립은 하나만", sum(1 for x in p if x["key"] == "combo:backstep_r1:성공") == 1)

tmp = Path(__file__).resolve().parent / "_combo_judge_tmp"
tmp.mkdir(exist_ok=True)
J.SCENES, J.LABEL_FILE, J.REVEALS = tmp / "s.jsonl", tmp / "l.jsonl", tmp / "r.jsonl"
for f in (J.LABEL_FILE, J.REVEALS):
    f.unlink(missing_ok=True)
J.SCENES.write_text(json.dumps({"scene_id": "a1", "move": "backstep_r1", "key": "combo:backstep_r1:성공",
                                "hidden": {"verdict_line": "x → backstep_r1: 성공 — 처치", "log": []}}) + "\n", encoding="utf-8")
args = dict(id="a1", choice="right", better=None, timing="ok", seen="kill", conf="high", note="")
check("판정 전엔 reveal 안 됨", J.reveal("a1") == 1)
J.label(types.SimpleNamespace(**args))
J.reveal("a1")
J.label(types.SimpleNamespace(**{**args, "choice": "wrong", "better": "jump"}))
st = [json.loads(l)["stage"] for l in J.LABEL_FILE.read_text(encoding="utf-8").splitlines()]
check("첫 판정 pre_reveal, reveal 뒤 post_reveal", st == ["pre_reveal", "post_reveal"])
check("wrong이면 --better 필요", J.label(types.SimpleNamespace(**{**args, "choice": "wrong"})) == 1)
for f in tmp.iterdir():
    f.unlink()
tmp.rmdir()
sys.exit(0 if ok else 1)
