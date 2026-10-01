# Laya 섀도 모드 — 구조 분석 · 경계 · 평가 계획

2026-10-01 [win]. 목표: 로컬 판단 모델 [Laya](https://github.com/NandhaKishorM/laya)가 싸움 상태를 보고 **이미 구현된 전술 후보** 중 하나를 고르게 하되,
**기록만** 하고 패드·규칙에는 절대 반영하지 않는다. 미세조정·실제 반영은 범위 밖.

## 1. 지금 구조 (코드로 확인한 것)

| 무엇 | 어디 | 메모 |
|---|---|---|
| 게임 상태 읽기 | `dsr_telemetry.py` `Telemetry.snapshot()` → `Snapshot(player, chars)` | 메모리 읽기 전용. `env.make_telemetry` |
| 상태 정규화 (싸움) | `souls/duel.py` `_sense(F)` → `Tick(s, p, c, h, dy, a, now)` | 목표 따라가기·끼어든 적·원거리 우선, **끝 조건**(`low_hp`·`losing`·`crowd`·`stalemate`…)도 여기 |
| 싸움 판단 | `souls/duel.py` `RULES` (25개, 위에서 먼저 걸리는 순서) · `duel()` 루프 | 규칙 함수가 **판단과 실행을 한 번에** 함 (`F.mv.*` 호출 = 패드 입력). `prep_*`는 계산만 |
| 끝난 뒤 판단 | `souls/field.py` `Field.fight` → `recover`·`fall_back`·`back_to_wall` | 후퇴·에스트는 `DuelResult.result`로 Field가 결정 |
| 안전 규칙 | 규칙 안의 조건들: `_other_swinging`(옆 적 휘두르면 공격 안 함), `opening`(에스트 틈), `low_hp` 0이면 후퇴 없음(`desperate`), `BACKSTAB`/`HEAVY`(`--basic`), `_heavy_ok`, `T.room`(뒤 공간), `nav.ground_ahead`(낭떠러지) | 별도 '안전 계층' 모듈은 없음 — 조건이 규칙마다 흩어져 있음 |
| 반사 | `souls/reflex.py` `Reflex.tick` | 2.5 m 안 휘두름 → 막기/백스텝. 패드 입력 |
| 실제 입력 | `control.py` `Pad` (vgamepad, ViGEm 가상 360 패드) ← `souls/moves.py` `Moves` | 그 밖에 `camera.CamFollow`·`watch.Escape` 스레드도 패드를 씀 |
| 기록 | 로그 `data/runs/<시각>_<이름>.jsonl` + `.txt`, `track.Track`(2 Hz, `tm.listeners`, 읽기 전용), `blackbox.py`, 싸움 상태 줄(`Fight.note`, 1 s마다) | 상태 줄 = 거리·높이·적 애니·HP·SP·각도 + 그 1 s 동안 한 행동 횟수. 샘플 로그 70개에 3,120줄 |
| 오프라인 테스트 | `tests/duel_golden_test.py` — 47,000여 상황의 duel 결정 전부를 스냅샷과 비교 | 가짜 `Moves`가 모든 패드·이동 호출을 trace로 남김 → **판단이 바뀌었는지 정확히 알 수 있음** |

예전 실험: `experiments/jev.py` (Jev API·로컬 LLM, choice/score/noul 같은 모양, 엘든링 순찰용, 지금 봇은 안 씀).

## 2. Laya 패키지 (PyPI 0.3.23 휠을 받아 소스로 확인)

- `laya.load(repo, device=, revision=)` → `Agent`; `agent.predict(state, questions)` → `{"answers": {qid: {"choice", "probabilities", "confidence"}}, "usage": {...}}`
- 의존성(휠 메타데이터): `torch>=2.0`, `transformers>=4.48`, `safetensors`, `huggingface_hub`, `numpy`. **이 PC의 봇 venv에는 torch·transformers·laya 없음**
- 체크포인트: `convaiinnovations/laya` 루트(영어). 검토된 커밋 `PINNED_REVISIONS["convaiinnovations/laya"] = 55cf4c4e…` 로 고정해서 받음. 크기·파라미터 수(문서상 ModernBERT-large 421M, ~1.5 GB)는 **받기 전엔 미확인**
- 네트워크: 첫 `snapshot_download`만. 그 뒤는 `HF_HUB_OFFLINE=1`로 캐시만 씀. 핵심 경로(agent)에 다른 네트워크 호출 없음(소스 grep)
- `Router`는 언어별 체크포인트를 고르는 것뿐 — DSR 전투를 배운 모델이 아님. 이 작업은 Router를 안 쓰고 체크포인트를 직접 지정
- 영상의 0.12 s(M4 Pro)·Jev 0.56 s는 **이 프로젝트에서 잰 값이 아님**. 목표치로 쓰지 않음

## 3. 끼우는 경계 (가장 좁게)

```
snapshot → _sense(정규화) → RULES (기존 안전 조건 + 실행) ──→ 패드          ← 그대로
                                   │ 규칙이 동작한 틱마다 (실행 뒤)
                                   ▼
                 advisor.observe(F, T, 규칙 이름)   ← 읽기만, 예외 삼킴, put_nowait (꽉 차면 버림)
                                   ▼
             숫자 dict (관측값 + 허용 후보 + 규칙이 한 전술)
                                   ▼   stdin JSON 한 줄
             laya_worker.py (별도 프로세스, WSL Ubuntu venv)  → Laya 예측 → data/runs/<시각>.laya.jsonl
```

- `duel()`에 `advisor=None` 인자 하나, 루프에 `if advisor is not None:` 두 곳. `Field.fight`가 `self.advisor`를 넘김. `run.py --laya-shadow`일 때만 만듦. 기본값은 None → **골든 테스트 47,000여 상황이 그대로여야 함**
- 돌려받는 길이 없음: 워커는 파일에만 쓰고, 봇 쪽은 워커 출력을 읽지 않음. advisor는 `F.mv`·패드를 건드리지 않음 (테스트로 확인)
- 별도 프로세스인 이유: torch가 봇 프로세스에 들어오면 GIL·메모리·크래시가 판단 루프(초당 21~25 틱)를 흔들 수 있음. 워커가 죽거나 느리면 큐가 넘쳐 버려질 뿐
- 별도 venv인 이유: 봇 venv·`requirements-lock.txt`·CI를 안 바꿈

## 4. Laya 입력/출력

**상태** (관측값만, 이미 봇이 읽는 것. 적의 의도·다음 공격 예측은 넣지 않음):
`my_hp_pct`, `my_stamina_pct`, `stamina_for_attack`, `target_kind`(망자/방패병/원거리…, `foes.py`), `target_state`(idle/swinging/staggered/guard_broken/downed/asleep — 애니 번호 범위), `target_swing_age_s`, `target_hp_pct`, `target_one_hit`, `distance_m`, `height_diff_m`, `weapon_reach_m`, `in_reach`, `facing_error_deg`, `target_facing_me_deg`, `others_within_4_5m`, `other_swinging_near`, `estus_wanted`, `estus_opening`, `taken_this_fight_pct`, 봇 자신의 설정 `fighting_style`·`let_it_come`(wait_far)

**후보** (이미 있는 규칙 묶음 → 전술 이름), 기존 조건으로 **먼저 거른 것만** 질문에 넣음:

| 전술 | 규칙 | 허용 조건 (기존 규칙의 조건에서) |
|---|---|---|
| attack | finish_first · hit_first · stagger_punish · finish · attack · early_kick | 닿는 거리+0.3 안, 높이 1 m 안, SP ≥ 무기 sp_min (한 방이면 15), 옆 적이 안 휘두름 (한 방이면 무관) |
| guard | reflex · block · late_windup_block · downed · (arena 없는) edge | 방패 스타일 |
| evade | reflex (백스텝 스타일) | `style.evade` |
| approach | approach | 닿는 거리 밖 |
| hold_position | wait_far · stamina | 늘 |
| heal | estus | `care.wants` (에스트 남음 + HP 기준) |
| reposition | lure · edge | arena·NavMesh 있음 |
| retreat | (끝 조건 `low_hp`·`losing`·`crowd`) | `low_hp > 0` (끝까지 싸우기 모드가 아님) |
| backstab | backstab · backstab_swing | `T.room` (`BACKSTAB` 켜짐 + 뒤 공간 + 1:1) — `--basic`이면 늘 빠짐 |

방향 돌기(`face_first`·`face`)·떼어놓기·백스텝 스타일 대기는 비교에서 뺌(전술이 아니라 준비 동작 또는 드묾).
**판단 보류** = confidence < `min_conf`(기본 0.5)이면 abstain.

**출력 행**: 규칙 이름·규칙 전술·허용 후보·Laya 선택·확률·confidence·상태(ok/abstain/invalid/error)·시간(봇 쪽 상태 만들기, 큐, 워커 준비, 추론, 합계).

## 5. 오프라인 평가 (게임 없음)

데이터 셋 둘 + 나중에 하나:
1. **golden** — `duel_golden_test`의 상황을 advisor를 붙여 돌려 (상태, 규칙 전술)을 정확히 얻음. 격자 상황이라 실제 분포와 다름
2. **logs** — `data/samples/*.txt`의 싸움 상태 줄. 실제 분포지만 관측값 일부만(옆 적·에스트 없음), 라벨은 그 1 s에 가장 많이 한 전술(둘 이상 섞이면 `mixed`로 따로 셈)
3. (게임 확인 허락 뒤) **shadow** — `--laya-shadow` 실행의 `.laya.jsonl`

나누기: 같은 장면의 거의 같은 프레임이 양쪽에 안 가게 **묶음 단위**로 dev/test (golden: 적 종류·애니·거리 묶음, logs: 실행 파일 단위, shadow: 실행 단위). 같은 (상태, 후보, 라벨)은 하나로 줄임.
지금은 학습을 안 하므로 dev는 임계값(min_conf) 고르기·실패 사례 보기에만 쓰고 숫자는 test로 보고.

측정: 규칙과 일치율(비교 가능한 것만) · 다수 클래스 기준선 · 혼동표 · **금지 후보 제안율**(허용 밖·잘못된 출력) · **규칙 행동이 마스크 밖인 비율**(마스크가 너무 좁은지) · 판단 보류율과 보류 임계값별 일치율/범위 · 라벨별 사례 수·실패 사례 · 시간 p50/p95 (상태 준비·추론·합계).
일치율 하나로 성공을 말하지 않음 — 규칙 자체가 정답이 아니고(P-29·P-30처럼 규칙이 틀린 장면이 있음), 일치율이 높아도 '규칙 흉내'일 뿐.

## 6. 설치·다운로드 — WSL Ubuntu ([MoKa] 2026-10-01 제안, 승인 전 — 아직 안 함)

WSL Ubuntu(WSL2, Python 3.12.3, RTX 5080·드라이버 610.88이 WSL 안에서 보임, 여유 830 GB)에 둠. 봇 venv·`requirements-lock.txt`·CI는 그대로.
봇은 `wsl -e sh -c 'exec "$HOME/laya-venv/bin/python" "$@"' sh /mnt/d/dev/dsr-bot/laya_worker.py --out /mnt/d/…`로 워커를 띄움 (`laya_shadow.worker_cmd`).

```
wsl -e bash -lc 'python3 -m venv ~/laya-venv && ~/laya-venv/bin/pip install -U pip'
wsl -e bash -lc '~/laya-venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cu128'
wsl -e bash -lc '~/laya-venv/bin/pip install laya==0.3.23'
wsl -e bash -lc 'cd /mnt/d/dev/dsr-bot && ~/laya-venv/bin/python laya_worker.py --download'     ← 체크포인트, 이때만 네트워크
```
추정(받기 전이라 미확인): torch CUDA 휠 ~3 GB(설치 후 ~5~6 GB, nvidia 라이브러리 포함), transformers 등 ~0.3 GB, 체크포인트 ~1.5~1.7 GB. 시간: 회선에 따라 10~20분. 학습 없음.

WSL에서 달라지는 점 (재 본 것):
- 전달: 가짜 백엔드 워커를 WSL 기본 python3로 띄워 200건 — 버림 0, 봇 쪽 offer 최악 1.09 ms, 큐+전송 p50 0.24 ms·p95 0.57 ms. 단 **Windows와 WSL은 시계가 둘**이라 `queue_ms`·`total_ms`는 근사(`clock_cross`). `infer_ms`는 워커 안 시계라 정확
- `wsl.exe` 시작 ~70 ms (실행 시작 때 한 번)
- 워커 우선순위: Windows 쪽 `BELOW_NORMAL`은 `wsl.exe`에만 걸리고 WSL VM 안 계산엔 안 걸림 — 게임 프레임에 영향이 있는지는 게임 실행으로만 앎 (허락 뒤)
- 오프라인 평가 점수 매기기도 WSL에서: `wsl -e bash -lc 'cd /mnt/d/dev/dsr-bot && ~/laya-venv/bin/python laya_eval.py score data/laya/cases_golden.jsonl --device cuda'` (`laya_eval`·`laya_shadow`는 표준 라이브러리만 import)

## 8. 지금까지 결과 (2026-10-01, 모델 없이)

- 바뀐 동작 없음: `python tests/duel_golden_test.py` 40,320 상황 그대로. `tests/laya_shadow_test.py`: 골든 10,080 상황을 advisor 3가지(정상 기록·보내기 실패·특징 계산 실패)로 돌려 trace(모든 Moves·패드 호출·로그·결과)가 advisor 없을 때와 같음, 그동안 `F.mv`를 만지면 실패하는 가짜로 바꿔 둠 → 접근 0. 느린 워커(0.3 s)에 60건: offer 최악 0.08 ms, 새것만 남기고 버림. 모델·워커 없음: 오류 한 줄 기록, 싸움 쪽 영향 없음. 전체 pytest 52 통과
- 마스크 점검 (golden 58,432 틱 → 서로 다른 11,620, test 묶음 8,126): 처음엔 규칙 행동의 21.7 %가 마스크 밖 → 원인은 마스크(백스텝 스타일의 반사는 막기가 아니라 백스텝, arena 없는 `rule_edge`는 제자리 막기) → 고친 뒤 1.6 %, 남은 건 둘: (1) golden의 가짜 반사는 안 터져서 옆 적이 휘두를 때 `rule_attack` (게임에선 반사가 먼저) (2) **`rule_finish`가 닿는 거리 밖(2.2~4.0 m)에서 침** — 뒤잡기 기회면 `rule_approach`를 건너뛰기 때문 → ROADMAP P-31. logs 0.3 %
- 일치율 상한: golden은 같은 상태·후보에 규칙 전술이 둘 이상인 사례가 75 % — 가짜 반사 켜짐/꺼짐·`back`처럼 상태에 안 보이는 격자 축 때문. 그래서 golden 일치율은 '규칙 흉내' 정도로만 읽어야 함. logs는 0.4 %지만 1 s 안에 전술이 섞인 줄이 56 %라 비교에서 빠짐
- 기준선 (test): 가짜 백엔드 'guard가 후보에 있으면 guard, 없으면 첫 후보' golden 49.6 % · logs 38.9 %, 늘 같은 답(다수 클래스) golden 28.1 % · logs 38.9 %, 후보 중 무작위 golden 23.8 % · logs 20.8 % — Laya 숫자는 이 셋과 같이 봐야 함 (마스크만으로 이미 절반 가까이 맞힘)
## 9. 실제 Laya 결과 (2026-10-01, [MoKa] 설치 승인 뒤)

**환경**: WSL2 Ubuntu (커널 6.6.114.1), Python 3.12.3, `~/laya-venv` 6.9 GB — torch 2.11.0+cu128 · transformers 5.18.0 · laya 0.3.23. RTX 5080 16 GB(드라이버 610.88), CPU i9-13900K(WSL vCPU 32). 게임은 안 켬.
**체크포인트**: `convaiinnovations/laya` 루트(영어), 커밋 `55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851`, `model.safetensors` 804 MB, ModernBERT 28층·hidden 1024, **421.3 M 파라미터**. 로드 1.9 s(캐시, 오프라인), 첫 다운로드 포함 31.7 s.
로드 때 경고: "체크포인트의 choice 11개 이상 온도 값이 잘못됨 → 0.5로 대체, 해당 confidence는 보정 안 됨" — 우리 후보는 많아야 9개라 해당 없음으로 봄(추정).

**결과 (test 묶음, CUDA)** — 금지·잘못된 제안 **0**, 상태 잘림 0 (상태 토큰 p50 golden 206·logs 94):
| | golden test (8,126) | logs test (1,016 비교 가능) |
|---|---|---|
| 보류율 (`confidence` < 0.5) | **99.9 %** | **99.9 %** |
| 보류 없이 답했을 때 규칙과 일치 | 45.9 % | 38.4 % |
| 늘 같은 답 / 후보 중 무작위 | 28.1 % / 23.8 % | 38.9 % / 20.8 % |
| 단순 규칙 'guard 우선' (가짜 백엔드) | 49.6 % | 38.9 % |
| `top_p` ≥ 0.4로 거르면 (범위 · 일치) | 29.9 % · 52.3 % | 40.0 % · 40.1 % |

라벨별 (golden test, 보류 무시): guard 1,920/2,284 · evade 1,045/1,848 · attack 438/655 · hold_position 328/1,360 · **approach 0/1,537** · backstab 0/332 · heal 0/40 · reposition 0/70. logs: hold_position 238/254 · attack 146/148 · **guard 0/395** · approach 0/136.
→ Laya는 후보 9개 중 4~5개만 답하고, **approach는 6,958번 후보에 있었지만 한 번도 안 고름**. 일치율은 '늘 같은 답'(logs)·'guard 우선'(golden) 기준선과 같거나 낮음.

**실패 원인 점검** (dev·무작위 표본):
- `confidence`는 선택지 확률이 아니라 Laya의 보정값(중앙 0.05). 선택지 확률은 `answer_confidence`(= `top_p`, 예: 후보 4개 중 0.40) — 둘 다 기록하게 고침. 하지만 `top_p`로 걸러도 logs 일치율은 안 오름 → 확률이 판단 품질을 가르지 못함
- **후보 순서에 민감**: 같은 상태·후보를 순서만 뒤집으면 200건 중 86건(43 %)의 답이 바뀜. 정방향에선 첫 후보를 82 % 고름
- 상태는 읽음: 상태를 "정보 없음"으로 바꾸면 100건 중 76건의 답이 바뀜
- 상태를 영어 문장으로 줘 봄 (dev 300건씩): golden 40.7 → 48.7 %, logs 41.3 → 26.3 % — 엇갈림, dict 유지

**지연시간** (단일 요청, 배치 없음):
| | p50 | p95 | 최대 | n |
|---|---|---|---|---|
| CUDA 추론 (채점, golden test) | 19.8 ms | 21.6 ms | 25.3 ms | 8,126 |
| CUDA 추론 (채점, logs test) | 18.9 ms | 20.7 ms | 56.1 ms | 2,287 |
| CUDA 실제 경로 (Windows `WorkerChannel` → WSL 워커, 5 Hz 300건, 버림 0) — 요청→답 | 23.7 ms | 44.0 ms | 402 ms | 300 |
| CPU 추론 (logs 500건) | 321~333 ms | 393~396 ms | 618 ms | 500 |
| 봇 쪽 상태 준비 · offer | 0.01 ms · 최악 0.30 ms | | | |
실제 경로 측정은 CPU 채점이 같이 돌던 때라 p95가 넓을 수 있음, 최대 402 ms는 첫 요청. 게임이 GPU를 쓰는 중의 값은 아님 — 게임 실행에서만 앎.

**판단**: 경로(섀도·격리·지연)는 쓸 만함 — CUDA p95 ~22~44 ms는 싸움 틱(~45 ms)과 비슷한 크기. **모델 판단은 이대로는 쓸 수 없음**: 보류 99.9 %, 기준선 수준 일치, approach를 전혀 안 고름, 후보 순서에 따라 답이 43 % 바뀜. 영상의 0.12 s와는 다른 환경이고 이 숫자로 비교하지 않음.
다음 단계 후보 (결정은 [MoKa]): (a) 여기서 멈추고 경로만 남김 (b) 질문을 전술 하나 고르기 대신 noul 여러 개("지금 막아야 하나?")로 나눠 순서 민감도를 없애고 다시 평가 — 미세조정 없음 (c) 미세조정 — 이번 범위 밖. 게임 섀도 실행(`--laya-shadow`)은 (b)든 무엇이든 정한 뒤, 허락받고

**맥락 (Laya 0.3.23 README, 개발자 주장 — 재현 안 함)**: 기본 체크포인트는 제로샷에서 거의 우연 수준(typed-decisions 벤치마크 0.362, 다수 클래스 0.461보다 낮음), 그 도메인 ~30k 질문으로 미세조정하면 0.766 — "Treat Laya as a fast base to specialise, not as a zero-shot decision engine". 후보 위치 편향은 알려진 문제(#131, `option_order` 회전으로 평균), noul은 라벨(false/true)을 따라가는 문제(#156, criteria·중립 라벨 권장). **즉 위 제로샷 결과는 예상 범위이고, DSR 데이터 미세조정의 가능성을 기각하는 근거가 아님.**

## 10. 라벨 출처 · 분할 · 소규모 미세조정 계획 (2026-10-01, [MoKa] 요청 — 학습·실제 행동 연결은 안 함)

### 10.0 짧은 noul 진단 (제로샷, dev 묶음만, 진단용)
README 권고대로 criteria + 중립 라벨(A/B). 3문항을 한 번의 forward로 (p50 20~22 ms):
| 질문 | 정답 출처 | golden dev (400) AUC · acc@0.5 (다수) | logs dev (388) AUC · acc@0.5 (다수) |
|---|---|---|---|
| 지금 막아야 하나? | 규칙 (guard였나) | 0.593 · 0.605 (0.740) | 0.603 · 0.719 (0.714) |
| 지금 쳐도 안전한가? | 규칙 (attack였나) | 0.509 · 0.850 (0.890) | **0.175** · 0.348 (0.874) |
| 목표가 무기 거리 밖인가? | **숫자** (`distance_m > weapon_reach_m`) | **0.405** · 0.383 (0.618) | **0.158** · 0.265 (0.735) |
마지막 문항은 규칙과 상관없이 상태 안의 숫자(그리고 `in_reach` 불리언)만 읽으면 맞히는 질문인데 우연보다 낮고 방향이 뒤집힘 → **제로샷 Laya는 이 JSON 상태의 숫자·불리언을 읽지 못함**. 미세조정 때 입력 형식(숫자 → 구간 범주, 핵심 불리언을 앞에, 문장형)이 중요한 변수일 것 (README의 browser-agent 사례도 "input-format change mattered most"라고 함 — 개발자 주장).

### 10.1 지금 있는 라벨의 출처 (조사 결과)
| 출처 | 양 | 라벨이 뜻하는 것 | 사람 검증 |
|---|---|---|---|
| **golden** (`duel_golden_test` 격자) | 58,432틱 · 서로 다른 11,620 | 지금 규칙(`RULES`)의 출력. 상황은 인공 격자(가짜 반사는 안 터짐, 같은 상태에 라벨 둘 이상 75 %) | **없음** |
| **logs** (싸움 상태 줄, 1 s) | 커밋된 샘플 3,107줄(53 실행) · 로컬 `data/runs` 340 실행 13,563줄 · 싸움 2,576번 406분 | 그 실행 때의 규칙이 실제 게임에서 한 행동. 규칙은 09-24~10-01 사이 매일 바뀜(같은 상황, 다른 날, 다른 라벨). 1 s 안에 전술이 섞인 줄 56 % | **없음** |
| 결과 기록 | 싸움 결과 2,576 (killed 1,984 · stuck 113 · stalemate 112 · low_hp 46 · crowd 24 · me_dead 18 …) · 블랙박스 164 실행 661 피격 묶음(앞뒤 프레임 포함) | 행동의 결과(받은·준 피해) — 고른 행동의 결과만 있고 다른 선택의 결과는 없음 | 없음 (측정값) |
| **사람 시범** (`data/observe`, 로컬 1.2 GB, 커밋 안 됨) | 42파일 중 사람 패드(slot 0)만인 것 21개: 가까운 싸움 **1,019 s, 153번, 적 192**, 성벽 마을 경사로·마을 + 수용소. 나머지 21개는 봇 실행을 녹화기로 본 것(slot 1) | [MoKa]가 실제로 누른 것(LB·R1·R2·B·X·스틱) → 전술은 규칙으로 유도해야 함. 실수도 포함(그동안 피격 98프레임) | 시범이지 "정답 확인"은 아님 |
| [MoKa] 판정 (ROADMAP 인용) | 약 35개 발언 — 대부분 원칙("적이 다가오면 미리 방향 정렬하고 가드"), 일부는 특정 장면(실행·시각: P-29, P-30, 10-01 구역 1 31.7 s 등) | 사람의 판단 | 사람이지만 틱 단위 라벨이 아님 |

→ **사람이 확인한 결정 단위 전술 정답은 지금 0개.** golden·logs의 "정답"은 전부 규칙 출력이라, 그것으로 학습·평가하면 "규칙 흉내"를 재는 것.

### 10.2 정답을 따로 만드는 방법 (제안, 아직 안 만듦)
행마다 `label_source`를 하나로 고정하고 섞지 않음:
- `human_verified` — [MoKa]가 장면을 보고 표시. 레이더 재생(`radar_server.py --replay`, 이미 있음)에 결정 지점 ±2 s를 띄우고 **"받아들일 수 있는 전술"(여러 개 가능)**과 "봇의 행동은 괜찮았나"를 고름. 전술이 하나로 정해지지 않는 장면이 많아 '정답 하나'보다 '허용 집합'이 덜 흔들림. 고를 장면 우선순위: 블랙박스 큰 피격 직전, `low_hp`·`losing`·`me_dead` 직전, P-기록 장면, Laya·규칙 불일치
- `human_demo` — 사람 패드에서 자동 유도 (LB 유지 → guard, R1/R2 → attack, B → evade, X + 에스트 수 감소 → heal, 스틱이 적 쪽/반대 → approach/retreat). 보조 학습용, 평가는 따로
- `rule` — 지금 golden·logs. 사전 학습·회귀 확인용
- `outcome` — 뒤 1.5 s 받은/준 피해. 정답이 아니라 검토 후보 고르기·보조 지표

### 10.3 분할안 (전투·적·구간 단위)
단위: 실행 → 구역(경사로·비밀 통로·마을 #1~#3·#4~#6·상인·화톳불, 수용소 구간 1~5) → 싸움(duel 시작~끝) → 틱. **싸움 안에서는 절대 안 나눔**, 틱은 결정 지점(같은 전술이 이어지면 하나, 바뀔 때 새 행)으로 줄임.
| 세트 | 무엇 | 왜 |
|---|---|---|
| train | 남은 실행의 싸움. 경사로 비중을 40 % 이하로 제한 | 지금 실제 싸움의 72 %가 경사로 |
| dev | 따로 고른 실행들 (train과 같은 구역) | 임계값·조기 종료 |
| test-ID | 가장 최근 코드의 실행 통째로 (10-01 이후) | 같은 구역, 다른 실행 |
| test-구역 밖 | **마을 #4~#6(구역 4) 전체** — P-29·P-30 장면 포함 | 처음 보는 지형에서도 되는지 |
| test-적 밖 (진단) | 한 적 종류 통째로, 예: 석궁병 255002 (싸움 132) | 처음 보는 적 |
| test-맵 밖 (진단) | 수용소 사람 시범 2파일 | 다른 맵 |
사람 시범은 녹화 파일(세션) 단위. 규칙 라벨은 날마다 바뀌었으므로 **실행마다 코드 커밋을 기록**해야 같은 규칙 버전끼리 묶을 수 있음 (지금 로그엔 커밋이 없음 — 작은 추가 필요, 아직 안 함).

### 10.4 데이터 형식 (제안)
결정 지점 한 줄:
```json
{"id": "...", "run": "20261001_..", "code_commit": "f22cc0e", "segment": "burg-town-4", "fight": "..#3", "t": 412.3,
 "npc": 254010, "state": {"...": "laya_shadow.features 그대로"}, "allowed": ["attack", "guard", "..."],
 "label_source": "human_verified", "acceptable": ["guard", "retreat"], "best": "guard", "bot_action": "attack",
 "verifier": "MoKa", "outcome": {"taken_1_5s": 145, "dealt_1_5s": 0, "fight_result": "low_hp"},
 "clip": {"file": "data/radar/....jsonl", "t0": 410.3, "t1": 414.3}}
```
학습용으로 바꿀 때: choice(허용 후보, `option_order` 회전으로 위치 편향 상쇄) + 전술별 noul("받아들일 만한가") 두 가지. Laya 미세조정 노트북의 실제 입력 형식은 휠에 없어 **아직 확인 안 함** (GitHub `notebooks/` — 읽기만 하면 됨).

### 10.5 필요한 라벨 수 (추정)
- **평가가 먼저**: test에 사람 확인 결정 **300개 이상**(구역 밖 test 포함). 정확도 50 % 근처에서 300개면 95 % 구간 ±5.7 %p — 규칙·기준선과 차이를 말할 수 있는 최소
- **작은 미세조정**: 사람 확인(또는 사람이 검토한 규칙·시범) 결정 **1,500~3,000개**, 흔한 전술(guard·attack·approach·hold_position·evade)은 각 100개 이상, 드문 것(heal·reposition·retreat·backstab)은 각 50개 이상 — 지금 기록에서 후퇴로 끝난 싸움은 70번(low_hp 46 + crowd 24), 에스트는 샘플 로그에 7번뿐이라 **따로 모아야 함**. 검토 시간 결정당 10~20 s로 잡으면 4~17시간([MoKa] 시간, 추정)
- 보조로 `human_demo` 약 2,000개(1,019 s를 0.5 s 결정 지점으로), `rule` 수만 개는 사전 학습용
- 근거: Laya README의 미세조정 예 ~30k 질문(4개 업무)·browser-agent 사례 — 우리 과제보다 크고 다르므로 숫자는 참고만. 더 싼 대안: 인코더는 얼리고 결정 머리만 학습(README가 소개한 stuntd 방식) — 수백~수천 개로 시작 가능(추정)

### 10.6 예상 자원 (추정 — 학습 안 돌려 봄)
- RTX 5080 16 GB (WSL에서 CUDA 됨). 421 M 전체 미세조정: 가중치·기울기 bf16 ~1.7 GB + AdamW 상태 fp32 ~3.4 GB + 마스터 가중치 ~1.7 GB ≈ 7 GB + 활성값 → 그래디언트 체크포인팅·작은 배치·상태 ~100~220 토큰이면 16 GB 안 (추정)
- 시간: README는 2×T4로 ~30k 질문 4 epoch 4~5시간 → 3k 질문 4 epoch는 RTX 5080에서 수십 분 정도로 추정(미측정). 머리만 학습은 수 분
- 디스크: 체크포인트 하나 0.8~1.7 GB. 게임이 GPU를 쓰는 동안엔 학습 안 함

### 10.7 평가 기준 (미세조정 뒤에 쓸 것)
1. **사람 확인 test에서 '허용 집합 안에 듦' 비율** — 기존 규칙(봇 행동이 허용 집합 안), 다수 클래스, guard 우선, 무작위와 나란히. test-구역 밖에서도 규칙 이상이어야 다음 단계 의미 있음
2. 위험: 금지 후보 제안 0(구조상), **[MoKa]가 '안 됨'으로 표시한 행동을 제안한 비율** — 특히 큰 피격 직전 장면
3. 보정: ECE, 보류 임계값별 범위·정확도 (임계값은 dev에서 고름)
4. 견고성: 후보 순서만 바꿨을 때 답이 바뀌는 비율 < 5 % (지금 43 %), 숫자 읽기 점검("거리 밖인가?" AUC > 0.95, 지금 0.16~0.41)
5. 지연: 게임 켠 채 CUDA p95 ≤ 45 ms (게임 실행은 허락받고)
6. 구역·적·전술별 표와 실패 사례 목록. 정확도 하나로 성공을 말하지 않음

## 11. 라벨링 파일럿 명세 (2026-10-01, [MoKa] 승인: 30~50장면, 학습·행동 연결 없음)

### 11.1 라벨링 단위 = 장면 (`dsr-scene/0.1`, `data/labels/pilot_scenes.jsonl` 한 줄)
한 장면 = 한 싸움 안의 **결정 시점 하나** `t_d`. 레이더 재생으로 `t_d − 6 s ~ t_d`(앞)와 `t_d ~ t_d + 4 s`(뒤)를 봄.
| 묶음 | 필드 | 모델 입력? |
|---|---|---|
| 신원 | `scene_id`, `schema`, `source` (`bot` \| `human_demo`), `source_file`, `run_id`, `fight_id`, `t_d`, `segment` (`places.zone`), `enemy` {`npc`, `kind`}, `event`(왜 골랐나: swing·opening·close_idle·far·before_big_hit·before_retreat·before_death), `code_commit` (봇: 실행 시각 이전 마지막 커밋, `code_commit_approx: true` — 작업 트리 수정분은 모름 · 사람 시범: null) | 아니오 (분할·분석용) |
| 결정 시점 관측 `obs` | `laya_shadow.features`와 같은 키 중 스냅샷에서 계산되는 것: 내 HP·SP 비율, 목표 종류·상태(애니 범주)·HP 비율, 거리·높이 차·무기 거리·닿음, 정면 각도, 목표가 나를 보는 각도, 4.5 m 안 다른 적 수·휘두르는 적, 에스트 남은 수 | **예** |
| 직전 맥락 `context` (`t_d − 3 s ~ t_d`) | 목표 애니 범주 변화(시각), 내 HP 변화, **행동 주체가 그동안 한 것**(봇: 상태 줄의 행동, 사람: 누른 버튼) | **예** (과거) |
| 후보 `allowed` | `laya_shadow.allowed(obs)` — 그 시점 규칙상 가능했던 전술. 모르는 관측은 허용으로 보고 `allowed_basis`에 적음 | 예 (질문의 선택지) |
| 이후 `after` (참고만) | 행동 주체가 실제로 한 것: 봇 `bot_action`(다음 1 s 상태 줄) · 사람 `human_pressed`(다음 1.5 s 버튼), 결과: 내 HP 변화 1.5 s·3 s, 목표 HP 변화, 싸움 결과(봇: 종료 줄 · 사람: 목표 HP 0), 뒤 4 s 안 큰 피격 | **아니오 — 모델 입력에 절대 안 섞음** |
| 누락 `missing` | 계산 못 한 `obs` 키와 이유 (예: 사람 시범은 무기 거리 없음, 10 Hz라 휘두른 시간 부정확) | — |
| 분할 | `test_candidate` (라벨 전에 규칙으로 고정: 구역 '마을 #4 길'·'석궁병 자리', 적 255002, 수용소 사람 시범), `selection` (뽑힌 층) | — |

### 11.2 라벨러가 남기는 값 (`dsr-label/0.1`, `data/labels/pilot_labels.jsonl` 한 줄, 고칠 때도 새 줄 — 마지막 줄이 유효)
`scene_id`, `schema`, `label_source: "human_verified"`(이 화면에서 사람이 고른 것만), `labeler_id`, `labeled_at`(ISO), `duration_s`(장면 연 뒤 저장까지), `saw_after`(저장 전에 '이후 보기'를 열었나),
`acceptable`[전술] · `forbidden`[전술] (둘 다 아니면 '중립') · `best`(선택, acceptable 중 하나) · `unsure`(판단 불가) + `unsure_reason`(정보 부족·화면으로 안 보임·전술 정의가 애매·기타) · `rationale`(짧은 근거) · `evidence`[근거가 된 `obs`/`context` 키] · `definition_note`(전술 정의가 모호했으면).
**지키는 것**: 봇 행동·규칙 출력·사람이 실제 누른 버튼은 `after`에만 있고 라벨 필드로 복사되지 않음 (`human_pressed` ≠ `acceptable`). 화면에 Laya·규칙의 제안은 안 보여 줌. 봇 로그 줄은 '이후 보기' 전에는 재생에서 뺌(규칙 판단에 끌리지 않게). `test_candidate`도 화면에 안 보임.

### 11.3 장면 고르기 (파일럿 40개 목표)
- 원본: 봇 레이더 녹화 `data/radar/*.jsonl`(10 Hz, 09-27~10-01) · 사람 시범 `data/observe/` 사람 패드만인 21파일
- 후보: 봇은 싸움 상태 줄마다 `t_d = 줄 시각 − 1 s`(그 줄의 행동이 `t_d` 뒤 1 s), 사람은 싸움 구간에서 목표 애니 범주가 바뀐 때·맞은 때·싸움 시작
- **싸움당 1장면**(긴 싸움만 사건이 다르고 5 s 이상 떨어지면 2), 실행당 4 이하, 경사로 8 이하, 사건·결과·구역·적·출처를 골고루 (씨앗 고정, 고른 이유를 `selection`에)
- 연속 프레임은 독립 표본이 아님 → 통계는 `fight_id` 단위로

### 11.4 화면 (기존 레이더 재생 재사용)
`python label_pilot.py serve` → `radar_server`의 `State`·`make_handler`·`radar_record.Replay`를 그대로 쓰고, 장면을 바꿀 때 재생 내용만 갈아 끼움. 왼쪽은 `radar.html` 그대로(타임라인·패드·바닥), 결정 시점은 타임라인 표시(F9 마커 자리). 오른쪽은 관측·맥락·후보별 [허용/금지] 단추·판단 불가·근거·저장, '이후 보기' 단추.

## 12. 학습·평가에서 '허용 전술 집합'을 표현하는 법 (설계만, 학습 안 함)

**공식 미세조정 코드에서 확인한 것** (`notebooks/laya_finetune_typed_decisions_mps.py`·Kaggle 노트북, GitHub main `4aa6761`, 2026-10-01 읽음):
- 데이터 한 행 = `state`(JSON) · `questions`(qid → choice/noul/score 정의) · `gold`(qid → `{"probabilities": {...}}`). choice는 선택지 키별 확률, noul은 `{"false": p, "true": p}`. 합이 1이 되게 정규화 → **목표는 분포(soft target)**, label = 최댓값
- 손실 = 그 분포에 대한 교차 엔트로피 + proper scoring rule 보상의 RL 항(RLCD). 학습 뒤 질문 종류별 온도 맞춤(보정 표본은 학습 표본에서 떼어 냄 — README도 따로 둔 평가 데이터로 확인하라고 함)
- **학습 코드는 `option_order`를 안 씀** — 선택지는 criteria 순서대로 놓임. 패키지의 `build_sequence(..., option_order=)`·`unpermute_probs`는 추론 때 회전 평균용

**설계**:
1. choice 질문 (후보 = 그 장면의 `allowed`): gold = `acceptable`에 균등(+ `best`가 있으면 best 0.5, 나머지 acceptable이 0.5를 나눔), `forbidden`과 중립은 0. 위치 편향 대응으로 **장면마다 선택지 순서를 2~3가지로 섞은 행**을 만들고(같은 `fight_id`라 분할은 함께), 평가 때는 k개 회전(`option_order`)의 확률을 `unpermute_probs`로 되돌려 평균
2. 전술별 noul ("지금 X는 받아들일 만한가") — acceptable = true, forbidden = false, **중립은 질문을 안 만듦**. 그래야 '허용'·'금지'·'모름'의 세 가지가 섞이지 않음. #156(라벨 따라가기) 때문에 criteria를 주고 라벨을 중립(A/B)으로, A/B 순서도 섞음
3. `unsure` 장면은 학습에서 뺌 (평가에선 '보류해야 맞는 장면'으로 따로 셈)
4. `label_source`가 `human_verified`인 행만 정답. `bot_action`·`human_pressed`는 따로 둔 보조 세트(`label_source: rule` / `human_demo`)로만, 섞지 않음
5. 평가 지표: **집합 적중**(argmax ∈ acceptable), **금지 적중**(argmax ∈ forbidden — 낮을수록 좋음, 안전 지표), 보류 범위별 두 지표, 전술별 noul AUC(acceptable vs forbidden), 회전 불변성(순서만 바꿔 답이 바뀌는 비율), 보정(ECE: confidence vs 집합 적중). 같은 지표를 규칙(`bot_action`)에도 계산해 나란히

### 10.8 다음에 할 일 (학습 전, 결정 대기)
1. 평가 세트부터: 레이더 재생에 '결정 지점 라벨 달기' 화면 → [MoKa]가 test 300개 표시
2. 실행 로그·섀도 행에 `code_commit`·구역·싸움 id 남기기 (작은 코드 변경)
3. Laya 미세조정 노트북 읽고 입력 형식·학습 방법 확인 (읽기만)
4. 그 뒤 '머리만 학습' vs '전체 미세조정' 결정

## 7. 다음 단계로 넘어가기 전 기준 (제안)

- 골든 테스트 그대로 · 섀도 켠 게임 실행에서 판단 공백(`blind_report.py`)·틱 수가 끈 실행과 차이 없음
- 금지 후보 제안 0 · 잘못된 출력 0
- 추론 p95가 싸움 틱 간격(~45 ms)과 견줄 만한지 — 아니면 '틱마다 조언'은 불가, '이벤트마다'만 가능
- 일치율은 다수 클래스 기준선보다 뚜렷이 높고, 불일치 사례를 [MoKa]가 봤을 때 Laya 쪽이 나은 장면이 있는지 (규칙이 틀린 P-기록 장면 위주)
