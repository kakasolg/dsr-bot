# 사다리 사망 대응 근거 (2026-11-01)

타우로스 사다리 루틴(`souls/missions.py` `Missions._before` 사다리 경로)이 사망 뒤에도 입력을 이어 간 문제의 수정 근거와
"dead" 반환 직후 입력 상태 조사. **작업 트리에 복사만 된 상태 — 커밋·푸시 전이라 영구 보존이 아니다.**
이 폴더의 파일은 원본 임시 폴더(scratchpad)에서 바이트 그대로 복사했다 (`SHA256SUMS`, 복사 전후 해시 동일).
변경 범위와 의존성: `CHANGE_MAP.md`. Git·파일 기준점: `git_baseline.txt`.

## A. 문제와 변경

- 실행 `20261101_002546_taurus`: 입구 생존 확인(nav.goto 끝 82.51 s) 뒤 HP 0(82.53 s), 그 뒤 A가 82.66 · 84.02 · 85.38 s에
  세 번 나갔다 (시도마다 A → 안 붙음 → 다음 시도). 원본 로그는 복제하지 않음 — 위치는 E 참조.
- **초기 3줄 수정** (`deathfix-base` → `deathfix2-base`): 시도 시작마다 `self.f.alive()`, 거짓이면 `neutral()` + `"dead"`.
  시도 시작 지점만 막았다. 돌기 중 · 오르기 중 · A 실패 뒤 재시도 정렬 중 사망은 그대로였다 (`ladder_death_phases.py`로 특성화:
  돌기 중 사망 → 돌기 스틱 + A, 오르기 중 → LADDER_CLIMB_S(15 s) 동안 스틱 위, 재시도 → 정렬 탭).
- **후속 보완 a~d** (`deathfix2-base` → `deathfix3`, diff = `deathfix3/this_change.diff`): 새 `_ladder_dead(s, tag)`로
  돌기 루프 조건 · A 직전 · A 안 잡힘 분기(재시도 정렬 전) · 오르기 루프 매 읽기 · 오르기 뒤 재시도 정렬 전에서 판정.
  시도마다 부르던 `alive()`는 A 직전 판정으로 대체.
- **판정**: 이미 읽은 스냅숏의 `player.hp <= 0` = 사망, `alive()` 재확인 없음 (DS1에서 HP 0은 되돌아오지 않고
  `Field.alive`도 읽기 한 번으로 판정). 스냅숏 없음 = 읽기 실패 → 입구와 같은 기존 정책(`Field.alive`: 다시 읽고 없으면 거짓).
  로그도 구분: "스냅숏 HP 0 → 중단" / "스냅숏 없음, alive() 거짓 → 'dead' (읽기 실패, HP 0은 못 봄)".
- **적용 범위**: `_before`의 사다리 경로만. 반환 규약('ok' · 'dead' · 'fail')과 호출자(missions.py:352, taurus.py:222 · 476)
  처리는 그대로. 공용 `Field._settle` · `Field.alive` · `control.Pad`는 안 바꿈. 정상 경로 읽기 수는 늘지 않음
  (가짜 세계에서 31 → 30), 읽기가 하나 느는 곳은 "A 안 잡힘" 분기뿐.

## B. 검증 근거 (전부 오프라인 — 가짜 패드·가짜 스냅숏)

| 단계 | 수정 전 | 수정 후 | 파일 |
|---|---|---|---|
| 3줄 수정 (`burg_upper_test.py` 002546 검사 4개) | 3 FAIL | 전부 ok | `deathfix-base/before_fix.txt`, `deathfix-base/after_fix.txt` |
| a~d (`burg_upper_ladder_death_test.py` 13검사) | 5 FAIL (돌기 · 오르기 · 재시도 · force_guard · sprint) | 13 ok | 수정 전: `deathfix3/before.txt`. 수정 후 출력은 **파일 없음** (대화 기록에만) |

- 관련 검사·전체 pytest (대화 기록에만, 결과 파일 없음): 3줄 단계 관련 6 passed, 전체 127 passed / 1 failed.
  a~d 단계 `-k "burg_upper or roll or taurus or boss_ready or pad_freeze or freeze_probe"` 10 passed, 전체 128 passed / 1 failed.
- 남은 실패 1개는 기존 `tests/ground_test.py` ("all 80 recorded falls still read 'no floor'", P-97) — ground·nav만 import, 이번 변경과 무관.
- 새 검사(`burg_upper_ladder_death_test.py`, after_dead_state)는 **실제 `control.Pad` 코드를 가짜 vgamepad(`tests/pad_fakes.py`) 위에서**
  돌린 것. 실제 ViGEm 장치·게임 반응은 확인 안 함. 이번 보존 단계에서 어떤 검사도 다시 돌리지 않았다 — 보존 완료 ≠ 재현 검증 완료.

## C. "dead" 반환 직후 입력 상태 (`deathfix4/out.txt`, 가짜 장치)

- 일반 경로: HP 0을 읽은 뒤 루틴의 호출은 `neutral()` 1번, 보고 1건. 장치의 A·좌우 스틱 해제. Pad `_due`에 이미 꺼진 A의 묵은 예약이
  남는다 (`neutral()`은 `_due`에서 B만 뺀다) — 장치 입력에는 영향 없음.
- B·LB는 조건에 따라 남고 후속 정리 호출에 의존:
  - LB: guardkeep 스레드의 `keep_guard(until)` 구간 중이면 `neutral()`이 LB를 다시 누른다. 풀리는 곳 = guardkeep의 다음 poll
    (구간이 끝난 뒤의 `unkeep`), `gk.stop()`, 구간 뒤의 `neutral()`. (`force_guard = True` setter는 bot 코드에 없음 — 테스트 전용)
  - B: 0.45 s(SPRINT_MIN_HOLD_S) 안에 눌린 달리기 B는 남고 `_due[B]`로 예약. 풀리는 곳 = 시각이 지난 뒤의 `release_due`,
    0.45 s 뒤의 `neutral()`, `release_all`/`close`. 사다리 루틴 자신은 B를 누르지 않는다.
- freeze(다른 스레드 소유) 중: 루틴의 `release_due` 3번·`neutral` 1번이 차단되어 보고 0건. 장치가 중립인 건 freeze 시작 때의 reset
  때문 — holder(souls/watch.py의 finally `neutral` → `unfreeze`)의 정리에 의존.
- 시간만 흐르면 아무것도 안 풀린다 (+1 s · +3 s, Pad 호출 없음 → 장치 그대로). 예약 해제는 누군가 호출해야 실행된다.
- 호출자 종료 처리: **run.py를 실행한 결과가 아니라** run.py finally를 읽고 그 Pad 호출 순서(`neutral` → 대기 → `gk.stop()` →
  `neutral`)를 가짜 장치에서 재생한 결과. 그 순서 뒤엔 전 조건에서 장치 중립. 첫 `neutral`이 0.45 s 안이면 B는 그때 남는다(3b).
  이것은 정상 반환·KeyboardInterrupt·예외가 finally에 닿는 경우의 코드 경로일 뿐, 강제 종료(TerminateProcess)나 finally에 못 닿는
  상황의 보장이 아니다 (control.py 주석: hard kill 시 ViGEm 동작 UNKNOWN).
- 미해결: 사다리에 붙은 뒤 오르기 동안 A가 눌린 채 남음(`_ladder_grabbed`가 0.1 s 해제 예약 전에 반환, 오르기 루프는
  `release_due`를 안 부름 — 가짜 장치에서 관찰, 게임 영향 미확인). 진입 `_settle`(공용 `Field._settle`) 중 사망. `_ladder_ready` ·
  `_ladder_grabbed` 안에서 HP 0이 보여도 그 함수가 끝날 때까지 대기(새 입력은 없음). 실제 사망 순간과 그 읽기 사이의 입력.

## D. pstack 활용

- 이번 입력 상태 조사: `pstack@cursor-plugins` 0.15.36의 `principle-prove-it-works` SKILL.md를 **읽고 따른** 방식 (스크립트로 확인하고
  결과를 남김). 슬래시 명령 호출·`how` 스킬의 서브에이전트 절차·전체 플레이북은 쓰지 않음.
- 앞선 버그 수정 단계(3줄 수정)의 pstack 적용은 별개 단계이며 여기 기록의 대상이 아니다 (그 단계 내용은 세션 기록 참조).

## E. 재사용

| 파일 | 용도 |
|---|---|
| `deathfix-base/` | 3줄 수정 **전** `souls/missions.py`·`tests/burg_upper_test.py`, 당시 `git status`(status.txt), diffstat, 3줄 수정 전후 검사 출력 |
| `deathfix2-base/` | 3줄 수정 **후**·a~d **전** 두 파일 (status.txt는 deathfix-base 것과 같은 바이트) |
| `deathfix3/` | a~d 수정 전 새 검사 출력(`before.txt`), 이번 변경 diff, 수정 후 두 파일 사본 (`*.after.py` = 현재 작업 트리와 같은 해시) |
| `deathfix4/after_dead_state.py`, `out.txt` | "dead" 반환 직후·run.py 종료 순서 재생 뒤·가정된 release_due 뒤 상태 |
| `ladder_death_phases.py` | 단계별 사망 뒤 입력 특성화 (3줄 수정 시점 코드 대상). **출력 파일은 저장 안 됨 — 누락** |
| `final-tree/tests/burg_upper_ladder_death_test.py` | 작업 트리의 미추적 새 검사 사본 (같은 해시) |
| `git_baseline.txt` | 브랜치·HEAD·HEAD blob id·작업 트리 해시·`git status` (이 폴더를 만들기 직전) |

- 기준점: HEAD `6ccafc0f636c…`, 브랜치 `claude/dsr-bot-project-review-r3hh9f`, 그 위 미커밋 작업 트리 (`git_baseline.txt`).
  `deathfix*`의 코드 사본은 HEAD 위 미커밋 패치(선행 사다리 수정 등)를 포함한 상태 — HEAD만으로는 재구성 안 됨.
- 의존성: 저장소의 `control.py`(HEAD와 같음), `tests/pad_fakes.py`(HEAD와 같음), `souls/missions.py` 등 `souls/` 모듈.
- 알려진 환경: Windows 11 Pro 10.0.26300, `.venv` Python 3.12.10, Git Bash. 게임·vgamepad 불필요(가짜 장치). 그 밖의 패키지 버전 미기록 — 미확인.
- 재실행 (저장소 루트에서; 이번에는 실행 안 함):
  - `.venv/Scripts/python.exe -I experiments/ladder_death_2026_11_01/deathfix4/after_dead_state.py D:/dev/dsr-bot` — 저장소 경로를 인자로 받음.
    `time.time`/`time.sleep`을 전역으로 바꾸므로 따로 프로세스로 돌릴 것. 결과는 현재 작업 트리 코드 기준.
  - `.venv/Scripts/python.exe experiments/ladder_death_2026_11_01/ladder_death_phases.py` — **`sys.path`에 `D:\dev\dsr-bot` 고정**.
    다른 위치면 그 줄을 맞춘 사본이 필요. 지금 코드에 돌리면 수정 후 동작을 보여 주므로 당시 출력과 다르다.
  - 수정 전 결과 재현은 `souls/missions.py`를 `deathfix-base/` 또는 `deathfix2-base/` 사본으로 바꿔야 함 = 봇 코드 교체 —
    별도 작업 트리(worktree)에서, 승인 뒤에만.
- 원본 (복제 안 함):
  - 실행 로그 `data/runs/20261101_002546_taurus.{log,jsonl,ctl.jsonl,frames.jsonl,hits.jsonl,track.jsonl,settings.json,diff}` — `.gitignore`의 `data/*`로 무시됨, 이 PC에만 있음.
  - 샘플 `data/samples/20261101_002546_taurus.{txt,jsonl,settings.json,track.jsonl}` — 미추적, 이번 작업에서 안 건드림.
  - 세션 기록 `C:\Users\moka\.claude\projects\D--dev-dsr-bot\27855c87-f4a7-4693-b937-fcda3713d341.jsonl` (수정 후 출력·pytest 결과는 여기만).
  - 임시 원본 `C:\Users\moka\AppData\Local\Temp\claude\D--dev-dsr-bot\27855c87-f4a7-4693-b937-fcda3713d341\scratchpad\` (삭제 안 함, 세션 종료 시 사라질 수 있음).
- `pytest`는 `testpaths = tests`라 이 폴더를 수집하지 않는다. `tests/pad_press_test.py`는 `experiments/**/*.py`를 vgamepad 직접 쓰기
  정규식으로 훑는다 — 복사한 `.py`에 해당 패턴 없음(정규식 검색으로 확인, 테스트 실행은 안 함).
