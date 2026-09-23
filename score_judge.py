"""
답 줄 채점(S3) 판단기 — 후보마다 "Tactic: <이름>" 한 줄 전체의 로그우도를 매겨 고르고, 1·2등 차(마진)를 신뢰도로 쓴다.

VersionSandbox(docs/escalation_gate_probe.md)에서 가져온 방식:
  · 모델이 적는 신뢰도는 오답에도 0.95 — 쓰지 않는다 (봇의 로컬 Qwen 도 늘 0.95 였다)
  · 라벨 한 단어만 채점하면 짧은/흔한 후보로 쏠린다 → 접두사 + 후보 + 공통 꼬리까지 줄 전체를 채점
  · 길이 보정·클래스 보정은 전부 더 나빴다 → 합계 로그우도 그대로
  · 게이트는 고정 임계값이 아니라 분위수 (τ 가 셋 사이에 옮겨지지 않았다)
LM Studio 의 logprobs 는 샘플링 뒤 분포(1.0/0.0)라 이 계산을 못 한다 → llama-cpp-python 으로 모델을 직접 돌린다.

  .venv-llm\\Scripts\\python.exe score_judge.py            상인 달리기 전술 시나리오 벤치 (사전 등록된 기대 답과 비교)

별도 venv(.venv-llm)를 쓴다 — llama-cpp-python 을 Vulkan 으로 빌드했고, 봇 venv 를 건드리지 않기 위해서다.
"""
from __future__ import annotations

import json
import math
import os
import statistics as st
import sys
import time
import urllib.request

import numpy as np

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

MODEL = os.environ.get("SCORE_MODEL", os.path.expanduser(r"~\.lmstudio\models\lmstudio-community\Qwen3-4B-GGUF\Qwen3-4B-Q4_K_M.gguf"))


class Scorer:
    """접두부 KV 를 재사용하며 후보 줄들을 채점한다. 같은 시스템 프롬프트는 한 번만 계산된다."""

    def __init__(self, model_path: str = MODEL, n_ctx: int = 1024, n_gpu_layers: int = -1):
        from llama_cpp import Llama
        self.llm = Llama(model_path=model_path, n_ctx=n_ctx, n_gpu_layers=n_gpu_layers, logits_all=True, verbose=False)
        self.cached: list[int] = []      # KV 캐시에 들어 있는 토큰열 (접두부 + 마지막 후보)

    def tok(self, text: str) -> list[int]:
        return self.llm.tokenize(text.encode("utf-8"), add_bos=False, special=True)

    def _eval_from(self, tokens: list[int]) -> None:
        """캐시와 겹치는 앞부분은 건너뛰고 나머지만 계산한다."""
        common = 0
        for a, b in zip(self.cached, tokens):
            if a != b:
                break
            common += 1
        common = min(common, len(tokens) - 1)    # 마지막 토큰은 다시 계산해야 그 위치의 로짓이 확실히 남는다
        self.llm.n_tokens = common
        self.llm.eval(tokens[common:])
        self.cached = list(tokens)

    def score(self, prefix: str, candidates: list[str]) -> list[float]:
        """각 후보 문자열(접두부 뒤에 이어질 텍스트)의 로그우도 합 (nats)."""
        pt = self.tok(prefix)
        self._eval_from(pt)
        base = len(pt)
        out = []
        for c in candidates:
            ct = self.tok(c)
            self.llm.n_tokens = base
            self.llm.eval(ct)
            self.cached = pt + ct
            lp = 0.0
            for j, t in enumerate(ct):
                row = np.asarray(self.llm.scores[base - 1 + j], dtype=np.float64)
                m = row.max()
                lp += row[t] - (m + math.log(np.exp(row - m).sum()))
            out.append(lp)
        return out


# ── 상인 달리기 전술 (merchantrun.TACTICS 와 같은 넷) ──
TACTICS = {
    "fight": "Firebombs plus melee: throw a bomb when the target is 4-9 m away, block and hit when it is close.",
    "bomb_stop": "Walk until 4-9.5 m from the nearest enemy, stop there and throw firebombs; melee only if one gets within 4 m.",
    "bomb_sprint": "Keep sprinting along the path; throw a bomb only when an enemy happens to be in range; never melee.",
    "sprint": "Do not fight at all; sprint past everything.",
}
SYSTEM = (
    "You pick the tactic for a Dark Souls Remastered bot that runs from the Firelink Shrine bonfire to the Undead Merchant. "
    "Hollows are slow and weak (75 HP; one firebomb kills). Principles from the player: enemies that block the path are cleared, "
    "not fled from - running away gets the bot cornered; on a narrow ramp prefer bombs over melee, because melee movement pushes the bot "
    "off the edge; standing still under ranged fire from above is bad; bombs are useless within 4 m. "
    "Answer with exactly one line: Tactic: <name>"
)


def prompt(state: dict) -> str:
    tactics = "\n".join(f"- {k}: {v}" for k, v in TACTICS.items())
    user = f"STATE:\n{json.dumps(state, ensure_ascii=False)}\n\nTACTICS:\n{tactics}"
    # Qwen3 chat 템플릿, non-thinking (빈 think 블록을 미리 채운다 — enable_thinking=False 와 같은 모양)
    return (f"<|im_start|>system\n{SYSTEM}<|im_end|>\n<|im_start|>user\n{user}<|im_end|>\n"
            f"<|im_start|>assistant\n<think>\n\n</think>\n\n")


def cand_lines() -> list[str]:
    return [f"Tactic: {k}<|im_end|>" for k in TACTICS]


def H(dist, blocking=True, attacking=False, height=0.0, where="on the path ahead"):
    return {"type": "hollow", "distance_m": dist, "height_diff_m": height, "blocking_path": blocking, "attacking": attacking, "where": where}


# ── 사전 등록 (실행 전에 고정. 결과를 보고 바꾸지 않는다) ──
# 기대 답의 근거는 playbook-notes H 절의 사용자 원칙. None = 원칙만으로 정답이 갈리지 않는 모호한 상황 (정확도에서 빼고 마진만 본다).
SCENARIOS = [
    ("s01 적 없음", {"terrain": "open courtyard", "path_left_m": 150, "hp_pct": 1.0, "bombs_left": 8, "enemies": []}, {"sprint"}),
    ("s02 먼 할로우, 길 밖", {"terrain": "open courtyard", "path_left_m": 120, "hp_pct": 1.0, "bombs_left": 8,
                            "enemies": [H(30, blocking=False, where="30 m to the side, off the path")]}, {"sprint"}),
    ("s03 좁은 경사로 막는 둘", {"terrain": "narrow ramp with a 20 m drop on one side", "path_left_m": 90, "hp_pct": 1.0, "bombs_left": 8,
                              "enemies": [H(8.0), H(9.0)]}, {"bomb_stop"}),
    ("s04 1.2 m 붙어서 공격", {"terrain": "flat stone path", "path_left_m": 100, "hp_pct": 0.9, "bombs_left": 8,
                             "enemies": [H(1.2, attacking=True)]}, {"fight"}),
    ("s05 폭탄 0, 6 m 막는 하나", {"terrain": "flat stone path", "path_left_m": 100, "hp_pct": 1.0, "bombs_left": 0,
                                "enemies": [H(6.0)]}, {"fight"}),
    ("s06 폭탄 0, 경사로 막는 둘", {"terrain": "narrow ramp with a 20 m drop on one side", "path_left_m": 90, "hp_pct": 1.0, "bombs_left": 0,
                                 "enemies": [H(7.0), H(8.0)]}, None),
    ("s07 셋, 5~9 m", {"terrain": "open courtyard", "path_left_m": 110, "hp_pct": 1.0, "bombs_left": 8,
                      "enemies": [H(5.0), H(7.0), H(9.0)]}, {"bomb_stop"}),
    ("s08 위층 폭탄 할로우, 길은 비었음", {"terrain": "stairs under a balcony", "path_left_m": 80, "hp_pct": 0.8, "bombs_left": 8,
                                    "enemies": [H(6.0, blocking=False, attacking=True, height=6.0, where="on a balcony above, throwing firebombs")]}, {"sprint"}),
    ("s09 HP 30 %, 7 m 추격", {"terrain": "flat stone path", "path_left_m": 20, "hp_pct": 0.3, "bombs_left": 5,
                             "enemies": [H(7.0, blocking=False, where="7 m behind, chasing")]}, None),
    ("s10 9 m 막는 하나", {"terrain": "open courtyard", "path_left_m": 100, "hp_pct": 1.0, "bombs_left": 8,
                         "enemies": [H(9.0)]}, {"fight", "bomb_stop"}),
    ("s11 뒤 15 m 추격, 앞은 빔", {"terrain": "flat stone path", "path_left_m": 60, "hp_pct": 1.0, "bombs_left": 8,
                               "enemies": [H(15.0, blocking=False, where="15 m behind, chasing")]}, {"sprint"}),
    ("s12 경사로 가장자리 둘 붙음", {"terrain": "narrow ramp with a 20 m drop on one side", "path_left_m": 85, "hp_pct": 0.7, "bombs_left": 8,
                                "enemies": [H(1.0, attacking=True), H(1.5, attacking=True)]}, {"fight"}),
]
# 판정선 (사전 등록): 쓸 만하다 = (1) 기대 답이 있는 10개 중 8개 이상 일치 (2) 모호한 둘(s06·s09)의 마진이 일치한 것들 마진의 중앙값보다 낮다
# (3) 게임을 켠 채 호출당 지연 p50 < 300 ms. 하나라도 못 넘으면 봇에 붙이지 않는다.


def lmstudio_pick(state: dict) -> tuple[str | None, float]:
    """비교용: 지금 jev.py 가 쓰는 LM Studio JSON 선택(C 모양 — 선택지만)."""
    body = {"model": "qwen/qwen3-4b", "temperature": 0, "max_tokens": 40,
            "messages": [{"role": "system", "content": SYSTEM.replace("Answer with exactly one line: Tactic: <name>", "Reply with the JSON object only.") + " /no_think"},
                         {"role": "user", "content": prompt(state).split("<|im_start|>user\n")[1].split("<|im_end|>")[0]}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "t", "strict": True, "schema": {
                "type": "object", "properties": {"tactic": {"type": "string", "enum": list(TACTICS)}}, "required": ["tactic"], "additionalProperties": False}}},
            "chat_template_kwargs": {"enable_thinking": False}}
    req = urllib.request.Request("http://127.0.0.1:1234/v1/chat/completions", data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            out = json.loads(r.read().decode())
        c = out["choices"][0]["message"]["content"]
        return json.loads(c[c.find("{"): c.rfind("}") + 1])["tactic"], (time.perf_counter() - t0) * 1000
    except Exception:
        return None, (time.perf_counter() - t0) * 1000


def main() -> None:
    t0 = time.perf_counter()
    sc = Scorer()
    print(f"모델 로드 {time.perf_counter() - t0:.1f} s  ({os.path.basename(MODEL)})")
    names = list(TACTICS)
    cands = cand_lines()
    sc.score(prompt(SCENARIOS[0][1]), cands)          # 워밍업
    lat: list[float] = []
    rows = []
    for rep in range(5):                              # 시나리오를 돌아가며 — 상태 부분은 매번 새로 계산된다 (시스템 부분만 캐시)
        for label, state, expect in SCENARIOS:
            t = time.perf_counter()
            s = sc.score(prompt(state), cands)
            lat.append((time.perf_counter() - t) * 1000)
            if rep == 0:
                rows.append((label, state, expect, s))
    print(f"\n{'시나리오':<28} {'기대':<18} {'S3':<12} {'마진':>6}  {'후보 확률 (fight/bomb_stop/bomb_sprint/sprint)':<44} {'LM Studio':<12}")
    hits, n_exp, margins_hit, margins_amb, disagree = 0, 0, [], [], 0
    lm_lat = []
    for label, state, expect, s in rows:
        order = sorted(range(len(s)), key=lambda i: -s[i])
        pick, margin = names[order[0]], s[order[0]] - s[order[1]]
        z = np.exp(np.array(s) - max(s))
        probs = z / z.sum()
        lm, ms = lmstudio_pick(state)
        lm_lat.append(ms)
        ok = None if expect is None else pick in expect
        if expect is not None:
            n_exp += 1
            hits += ok
            if ok:
                margins_hit.append(margin)
        else:
            margins_amb.append(margin)
        disagree += lm is not None and lm != pick
        mark = "·" if ok is None else ("O" if ok else "X")
        print(f"{label:<28} {'/'.join(sorted(expect)) if expect else '(모호)':<18} {pick:<12} {margin:6.2f}  "
              f"{' '.join(f'{p:.2f}' for p in probs):<44} {str(lm):<12} {mark}")
    lat.sort()
    print(f"\n일치 {hits}/{n_exp}   마진 중앙값: 일치 {st.median(margins_hit) if margins_hit else float('nan'):.2f} / 모호 {st.median(margins_amb):.2f}"
          f"   S3 ≠ LM Studio {disagree}/{len(rows)}")
    print(f"채점 지연 (후보 4개, 시스템 부분 캐시): p50 {st.median(lat):.0f} ms  p90 {lat[int(len(lat) * 0.9) - 1]:.0f} ms  "
          f"min {lat[0]:.0f}  max {lat[-1]:.0f}  (n={len(lat)})")
    print(f"LM Studio JSON 한 번: p50 {st.median(lm_lat):.0f} ms")
    ok1, ok2, ok3 = hits >= 8, (margins_hit and st.median(margins_amb) < st.median(margins_hit)), st.median(lat) < 300
    print(f"판정: (1) 일치 ≥ 8/10 {'통과' if ok1 else '미달'}  (2) 모호 마진 < 일치 마진 {'통과' if ok2 else '미달'}  (3) p50 < 300 ms {'통과' if ok3 else '미달'}")


if __name__ == "__main__":
    main()
