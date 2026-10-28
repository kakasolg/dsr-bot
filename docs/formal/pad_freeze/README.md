# control.Pad freeze — 다시 쓰는 법

봇 안의 여러 스레드(판단 루프·nav·guardkeep·Escape)가 패드 하나를 같이 쓴다. 한 스레드가 `freeze()`로 패드를 잡은 동안
다른 스레드가 버튼을 남기지 못하게 하는 규칙("minimal" 계약)과, 그 규칙을 검사하는 도구가 이 폴더에 있다.
발견한 결함: P-91·P-92 (minimal 패치로 막음), P-93·P-94 (평상시 결함, 추적만) — `docs/roadmap/problems.md`.

## 무엇이 어디에

| 파일 | 내용 |
|---|---|
| [REPORT.md](REPORT.md) | TLA+ 모델 검사 결과 (200회), 성질 식, 반례, 제외한 가정 |
| [PATCH_PLAN.md](PATCH_PLAN.md) | minimal 계약, 합격 테스트, 패치 설계, 남는 위험 |
| [GAME_CHECK_PLAN.md](GAME_CHECK_PLAN.md) | 게임 확인 계획과 실행 기록 (quit-out 1회) |
| `PadFreeze.tla`, `cfg/` | 모델과 검사 설정. 변형 `current` · `block` · `ownerNeutral` · `both` · `minimal`(= 지금 `control.py`) |
| `run_tlc.py` · `table.py` · `trace.py` | TLC 배치 실행 · 결과 표 · 반례를 바뀐 필드만 보기 |
| `repro_new.py` | 모델 반례를 실제 Pad 코드(가짜 장치)로 재현 — 테스트 아님, 출력만 |
| `tests/pad_freeze_race_test.py` | 순서를 고정한 경합표 F1–F12 |
| `tests/pad_freeze_accept_test.py` | minimal 계약 합격 줄 (S5-normal·S6-normal = P-94·P-93, VIOLATED known) |
| `tests/freeze_probe_live_test.py` | 게임 하네스 `experiments/freeze_probe_live.py`를 게임 없이 검사 |

## 언제 다시 돌리나

- `control.py`의 `Pad`(freeze·neutral·guard·keep_guard·sprint·tap·hold·release_due·kick 등)를 바꿨을 때 → 1
- 패드를 만지는 **새 메서드나 새 스레드**를 추가했을 때 → 아래 "새 동작 추가" 후 1, 2
- P-93·P-94를 고칠 때 → 1, 2 (고치면 accept 테스트의 KNOWN에서 그 줄을 뺀다 — 안 빼면 FAIL)

## 명령

1. 오프라인 테스트 (게임 없음, 몇 초):
   `python -m pytest -k "pad_freeze or freeze_probe"`
2. TLA+ 모델 검사 (Java 11+ — 지난번 Temurin 21 — 와 `tla2tools.jar` 필요, 저장소에 없음 — github.com/tlaplus/tlaplus releases에서 받음,
   지난번은 v1.7.4. 200회 전체는 수 분):
   `python docs/formal/pad_freeze/run_tlc.py <tla2tools.jar 경로> [이름 일부]` → `out/results.tsv`
   반례 보기: `python docs/formal/pad_freeze/trace.py docs/formal/pad_freeze/out/<이름>.log`
   (`out/*.log`는 .gitignore — 결과 표만 남는다)

## 새 동작 추가

1. `tests/pad_freeze_race_test.py`에 "main frozen · other <새 호출>" 줄을 넣는다 (장치 보고에 나오면 안 됨).
2. 상태(`_due`·`_kept`·`_b_since` 같은)를 바꾸는 호출이면 `PadFreeze.tla`에 행동으로 넣고, 관련 성질(S1–S6)을 다시 돌린다.
   모델과 `control.py`가 같은지는 사람이 줄 단위로 대조한다 — 도구로 확인하지 않는다.
3. 홀더(`Escape.fire`·`_nudge`)가 새 버튼을 쓰기 시작하면 REPORT §6 "제외한 가정"을 다시 본다 (예: 홀더가 `tap`을 쓰면 P-92의 K3 경로 — 지금은 F12로 막힘).

## 확인된 범위 (2026-10-27)

- 오프라인: 가짜 장치 테스트, TLC 유한 범위 (m3/m4) 검사.
- 게임: quit-out 1회, 봇의 출력 로그 기준. 화면·XInput 독립 확인 안 됨. nudge·낙사·전투 경로는 게임 미확인.
