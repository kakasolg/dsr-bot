# 미커밋 변경 지도 — 사다리 사망 대응 커밋 준비용 (2026-11-01)

기준: HEAD `6ccafc0`, 브랜치 `claude/dsr-bot-project-review-r3hh9f`, staged 없음 (`git_baseline.txt`).
이 문서는 코드를 나누거나 Git 인덱스를 바꾸지 않고 읽기로만 정리한 것이다. "독립 보존·검토 가능"은 아래 근거에 대한 판단이며,
분리 커밋으로 테스트를 돌려 확인한 것이 아니다 — 독립 커밋 가능 여부는 **미확인**.

## 1. 사다리 사망 대응 코드 (3줄 수정 + a~d 보완)

- 파일/범위: `souls/missions.py` `_before` 사다리 경로 — 돌기 루프 조건 `not self._ladder_dead(s)`, A 직전 판정, "A 안 잡힘"
  분기의 판정, 오르기 루프의 `died` 플래그·판정, 오르기 뒤 재시도 전 판정, 새 메서드 `_ladder_dead`. 차이 = `deathfix3/this_change.diff`
  (3줄 수정은 그 diff의 `-` 3줄로 대체됨).
- 의존: 같은 함수의 선행 사다리 수정(§3) — 판정 지점이 `_ladder_ready`·`_ladder_grabbed`·돌기 루프 안에 있다. Pad 의미(`neutral`,
  freeze 차단, P-70)는 HEAD의 `control.py`.
- 독립 보존·검토: diff는 따로 읽을 수 있음. 같은 hunk 안에 §3이 섞여 있어 HEAD에 이것만 적용하면 문맥이 맞지 않음 (git hunk 단위 분리 불가로 판단, 시도 안 함).
- 빠지면 깨지는 것: §2의 `burg_upper_ladder_death_test.py` 13검사 중 5개, `burg_upper_test.py` 002546 검사.

## 2. 관련 테스트

- `tests/burg_upper_ladder_death_test.py` (미추적 새 파일) — 실제 `control.Pad` + `tests/pad_fakes.py`(HEAD), 가짜 시계·스냅숏.
- `tests/burg_upper_test.py` — 사다리 블록(가짜 `lad_snap`·`lad_A`·`release_due`, 사다리 검사들, 002546 블록 `dies_in_settle`) 중
  사망 대응분: 002546 블록과 `lad_snap`의 `hp=pos.get("hp")`·`pos["hp"]` 설정·`pos.pop("hp")`.
- 의존: §1, §3 (사다리 블록 대부분은 §3의 검사). `MS.LADDER_GRAB_S`·`LADDER_BUSY_S`를 줄여 쓰므로 §3의 상수가 있어야 import 뒤 대입이 의미 있음.
- 독립 보존·검토: 새 테스트 파일은 독립 파일. `burg_upper_test.py`는 §3과 같은 블록이라 분리 불가로 판단.
- 빠지면 깨지는 것: CLAUDE.md의 관련 검사(`-k burg_upper`)가 이 회귀를 잡지 못함.

## 3. 선행 사다리 수정 (10-31 · 11-01 실행들)

- 파일/범위: `souls/missions.py` — `NS` import(+13), `LADDER_BUSY_S`·`LADDER_FREE_S`·`LADDER_FACE_DEG`·`LADDER_TURN_S`·
  `LADDER_GRAB_S` 상수(+89~93), `_before` 사다리 경로의 `_ladder_ready` 대기·돌기 루프·`_ladder_grabbed` 확인·"안 잡히면 오르기 입력 안 함"·
  A 떼기 `neutral()`, 새 메서드 `_ladder_ready`·`_ladder_grabbed`. `tests/burg_upper_test.py` 사다리 블록(+326~ 대부분).
- 의존: HEAD의 `souls/moves.py` `HIT_STUN`·`rel_angle` (HEAD에 있음 — 확인), `control.Pad.release_due`.
- 독립 보존·검토: §1·§2와 같은 함수·블록. 사망 대응과 함께 검토해야 함.
- 빠지면 깨지는 것: §1 전체 (판정 지점이 이 코드 안에 있음), `burg_upper_test.py` 사다리 검사들.

## 4. 의존하는 미커밋 Pad 보호 패치

- 찾지 못함: `control.py`·`tests/pad_fakes.py`는 작업 트리가 HEAD와 같다 (`git status`에 없음; 마지막 커밋 `7b33bd6` 2026-10-30).
  사망 대응과 새 테스트는 커밋된 Pad 동작(P-70 sprint 최소 유지, P-91/P-92 freeze 차단)에 의존한다.
- 공용 `souls/field.py`도 미커밋 변경 없음 (`git status`에 없음).

## 5. 회피·경로 변경 (타우로스)

- 파일/범위: `souls/taurus.py` — `HIT_AT`·`ROLL_LEAD`·`DODGE_FAR`, `ladder_way`, `_back_up`의 시각 맞춘 회피, `WAY_NEXT_M`/`WAY_EVERY_S`,
  `run()`의 `boss_ready.taurus` 진입 검사. `souls/moves.py` `roll_toward(hold=...)`. 테스트 `tests/taurus_dodge_test.py`·
  `tests/taurus_way_test.py`(미추적), `tests/roll_test.py`(hold 검사).
- 의존: `boss_ready.py`·`tests/boss_ready_test.py`(미추적) — `Taurus.run`이 함수 안에서 `import boss_ready`. `_back_up`이
  `roll_toward(..., hold=True)`를 부르므로 `moves.py` 변경 필요. 사다리 진입은 §1·§3의 `_before`를 호출.
- 독립 보존·검토: 사망 대응과 다른 문제(회피 시각·복귀 경로). 파일은 다르지만 호출 관계가 있음 — 따로 검토는 가능, 따로 커밋 시 테스트 통과는 미확인.
- 빠지면 깨지는 것: `boss_ready.py` 없이 `taurus` 명령은 import 오류. `moves.py` 없이 `_back_up`의 `hold=True` 호출이 TypeError.

## 6. 문서 변경

- `CLAUDE.md` — pstack 절, 사다리·roll·taurus 변경 시 검사 줄, 이전 세션의 "Before a run / After a death" 블록.
- `ROADMAP.md` 타우로스 줄 + 문제 색인 97행, `docs/roadmap/problems.md` P-97 항목, `docs/boss-taurus.md`, `docs/stages/burg-upper.md`.
- 의존: `tests/roadmap_test.py`는 P-번호마다 색인 1행을 요구 — `problems.md`의 P-97과 ROADMAP 색인은 함께 있어야 함.
- 독립 보존·검토: 코드 없이 읽을 수 있음. 내용 일부는 §1·§5를 설명.

## 7. 별개 변경 (사망 대응과 무관)

- `souls/missions.py` `light_burg_bonfire`의 levelup 훅(+1145~1147, `if sat: import levelup; levelup.maybe(...)`) — 미추적
  `levelup.py`·`tests/levelup_test.py`에 의존 (함수 안 import라 모듈 import는 안 깨지지만 화톳불에 앉으면 `levelup.py`가 필요).
  **사다리 변경과 같은 파일**이라 파일 단위로 커밋하면 함께 들어간다.
- `run.py` (`--level-up`·`ESTUS_HOME`·`--pick-stain`·`_stain_carry`·`burg-altar` 진입 검사 `boss_ready.altar`), `souls/afterdeath.py`
  (`low`·`carry`), `tests/afterdeath_test.py`, `places.py`·`tests/places_test.py`, `farm.py`, `overlay.py`, `radar_server.py`,
  `.claude/launch.json`, `data/stages/burg-upper.json`, `shot_review.py`·`tests/shot_review_test.py`, `experiments/g4_2026_10_31/` — 이번 근거와 무관, 내용 미검토.
- 미추적 `data/samples/*` — 실행 샘플, 이번 작업에서 안 건드림.
