# ROADMAP — 개선 계획 · 체크리스트 · 문제 기록

이 문서 하나로 두 작업자가 협업한다. **작업 전에 반드시 이 문서를 먼저 읽고, 작업 후 체크와 기록을 갱신한다.**

## 0. 작업 방식

| 작업자 | 환경 | 맡는 일 |
|---|---|---|
| **[cloud]** | 클라우드 Claude Code (게임 없음, Linux) | 계획, 게임 없이 되는 코드 (파서, 시뮬레이터, 뷰어, 테스트), 코드 리뷰 |
| **[win]** | 윈도우 로컬 Claude Code + 실제 게임 | 게임 파일 추출 실행, 실제 게임 테스트, 윈도우 전용 기능 (오버레이, 패드) |
| **[사람]** | 사용자 | 방향 결정, 실제 플레이 확인, 최종 판단 |

**규칙**
1. 작업 브랜치: `claude/dsr-bot-project-review-r3hh9f`. 시작 전에 `git pull`, 끝나면 커밋하고 푸시한다.
2. 항목을 시작하면 `[ ]` → `[~]`(진행 중)로 바꾸고 커밋한다. 둘이 같은 항목을 동시에 잡지 않게 하기 위해서다.
3. 끝나면 `[x]`로 바꾸고, **확인 방법과 결과**를 한 줄 적는다 (예: "field 테스트 11/11 통과", "Undead Burg에서 실행, 오브젝트 213개 추출").
4. 막히거나 예상과 다르면 **8. 문제 기록**에 항목을 추가한다. 해결되면 그 아래에 해결 방법을 적는다. 지우지 않는다.
5. [win]이 필요한 확인은 항목에 `→ [win] 확인 필요`라고 적어 둔다. 게임 파일이나 기록 샘플이 필요하면 `data/samples/`에 작은 것만 올린다 (대용량 금지).
6. 게임 메모리를 쓰는 기능(무적, 투명, 워프)은 **오프라인에서만** 쓴다.
7. 계획을 바꾸면 **9. 변경 이력**에 날짜와 이유를 적는다.

상태 표시: `[ ]` 할 일 · `[~]` 진행 중 · `[x]` 완료 · `[!]` 막힘 (문제 기록 참고) · `[-]` 취소

---

## 1. 기반 정리 — 게임 없이 테스트

- [x] [cloud] pymem/vgamepad 없이도 모듈이 불러와지게 함 (`telemetry.py`, `dsr_telemetry.py`, `control.py`, `quitout.py`) — Linux Python 3.12에서 오프라인 테스트 11/11 통과
- [ ] [win] 위 수정 후 실제 게임에서 `run.py burg-bonfire` 한 번 정상 동작 확인
- [ ] [cloud] 테스트를 `tests/`로 옮기고 pytest로 실행 (`axe_heavy_test.py`는 게임 측정 스크립트라 제외)
- [x] [cloud] GitHub Actions CI: Python 3.12, Windows 전용 패키지 뺀 의존성, 오프라인 테스트 실행 — `.github/workflows/test.yml`, 로컬 3.12에서 같은 명령 통과
- [x] [cloud] 클라우드 세션 시작 훅 (`.claude/hooks/session-start.sh`): Python 3.12 venv + 오프라인 테스트 의존성 자동 설치 — 훅 실행·재실행 OK, `moves_test.py` 통과
- [x] [cloud] `.gitignore`의 `data/` 규칙 정리 (필요한 파일이 무시되지 않게) — `data/*` + 예외(`*.json`, `*.txt`, `routes/`, `gamefiles/`, `samples/`), 새 파일로 추적·무시 확인
- [ ] [cloud] 루트 정리: 실험 스크립트는 `experiments/`로, `telemetry`/`dsr_telemetry`와 `nav`/`navmesh`의 관계를 문서화

## 2. 게임 파일에서 지형·적 정보 추출

- [x] [cloud] `msb_extract.py <mapID>` 작성 — `.msb`에서 추출해 `data/gamefiles/<mapID>.json`으로 저장 (`data/maps/`는 mapmem·navmesh 캐시가 쓰므로 분리) — 가짜 MSB로 `msb_extract_test.py` 통과, CI 포함. 실제 게임 파일로는 미확인 → [win] 확인 필요
  - 오브젝트: 위치, 모델명, 부서짐 여부 (ObjectParam)
  - 적: 위치, 방향, 순찰 경로, ThinkParam ID
- [x] [cloud] NpcThinkParam 추출: 시야 거리·각도, 청각 범위, 귀환 거리 → 적 데이터에 붙이기 — 같은 스크립트의 `think` 필드. 단위(미터 여부)는 게임에서 확인 필요
- [ ] [win] `python msb_extract.py m10_02_00_00 m10_01_00_00` 실행하고 `data/gamefiles/*.json` 커밋. 확인할 것: 오류 없이 도는지, 오브젝트·적 수가 그럴듯한지, 박스(`breakable: true`)가 실제로 부서지는지 몇 개. ObjectParam 행 번호 = 모델 번호 가정이 맞는지(`param_row_found`가 대부분 true인지)
- [ ] [사람] 결과가 실제 게임과 맞는지 몇 개 확인 (박스 위치, 적 대기 위치)
- [ ] [cloud] 증거 등급 추가: "파일 근거" (LAYERS.md에 반영)

## 3. 충돌 메시 — 벽과 낭떠러지 구분

- [ ] [cloud] `map/*.hkxbhd` 충돌 메시를 읽을 수 있는지 조사 (soulstruct 지원 여부)
- [ ] [cloud] NavMesh 경계를 벽/낭떠러지로 분류 → `navmesh.py`의 `EDGE_PENALTY` 활성화
- [ ] [win] 실제 경로에서 낭떠러지 회피 확인

## 4. 실시간 오버레이 · 레이더

- [ ] [cloud] 봇 상태 내보내기: 매 틱 짧은 상태(위치, 적, 목표, 판단 한 줄)를 로컬로 전송. 실패해도 봇은 계속 동작
- [ ] [cloud] 레이더 페이지: 기존 `observe_view.html` 그리기 재사용, 가짜 월드로 동작 확인
- [ ] [cloud] 오버레이 창 코드 (투명, 클릭 통과, **포커스 안 가져감** — `control.game_in_front()` 때문에 필수)
- [ ] [win] 테두리 없는 창 모드에서 오버레이가 보이고 봇 입력이 멈추지 않는지 확인
- [ ] [cloud] 표시 추가: 경로선, 안전 구역, 적 시야 부채꼴·귀환 거리 원 (2번 완료 후)

## 5. 기록 재생

- [ ] [win] 작은 관찰 기록 샘플을 `data/samples/`에 올림
- [ ] [cloud] 기록을 봇 판단 코드에 다시 넣어 "그때 봇이라면 뭘 했을지" 비교하는 도구
- [ ] [cloud] 레이더 페이지에서 기록 되감기 재생

## 6. 2D 시뮬레이터

- [ ] [cloud] NavMesh + 적 배치 + ThinkParam으로 적 감지·추격·귀환 모델링
- [ ] [cloud] 봇 판단 코드(`souls/field.py`)를 그대로 연결 (눈·손만 시뮬레이터로 교체)
- [ ] [cloud] 기록(5번)으로 시뮬레이터 값 맞추기
- [ ] [cloud] 여러 마리 분리·끌어오기 전략 대량 실험
- [ ] [win] 시뮬레이터에서 좋았던 전략을 실제 게임에서 검증

## 7. 탐험 모드 · 전투 예측 (후반)

- [ ] [cloud] 탐험 모드: 무적 + 투명 상태로 미확인 구역을 걸어서 검증, "관찰 확인" 등급으로 저장. 낙하 높이 기록 필수
- [ ] [win] 탐험 모드 실제 실행
- [ ] [cloud] AI Lua 디컴파일 가능 여부 조사
- [ ] [cloud] 애니메이션(TAE) 타이밍 + Lua 공격 후보 → 공격 예측

---

## 8. 문제 기록

새 문제는 아래 형식으로 **맨 아래에 추가**한다.

```
### P-번호 제목 (날짜, 작성자, 관련 항목)
- 증상:
- 원인 (추정/확인):
- 해결: (해결되면 작성, 미해결이면 "미해결")
```

### P-1 오프라인 테스트가 Linux에서 실행 안 됨 (2026-09-27, [cloud], 1번)
- 증상: `field_*_test.py` 등이 `ModuleNotFoundError: pymem`, 이어서 `vgamepad`, `KeyError: 'TEMP'`로 실패
- 원인 (확인): Windows 전용 import가 모듈 맨 위에 있었고, `TEMP` 환경변수에 의존함
- 해결: import를 try/except로 감싸고, 실제 연결 시에만 오류를 냄. `TEMP`가 없으면 `tempfile.gettempdir()` 사용

### P-2 Python 3.11에서 f-string 문법 오류 (2026-09-27, [cloud], 1번)
- 증상: `SyntaxError: f-string: expecting '}'`
- 원인 (확인): 코드가 Python 3.12 문법(f-string 안의 같은 따옴표)을 씀
- 해결: 3.12로 실행 (README 요구사항과 같음). CI도 3.12로 고정할 것

### P-3 soulstruct를 Linux에서 불러오면 오류 (2026-09-27, [cloud], 2번)
- 증상: `from soulstruct.darksouls1r.maps import MSB`가 `ds1-common.emedf.json` 없음으로 실패
- 원인 (확인): PyPI 휠에 JSON 데이터 파일이 빠져 있음 (윈도우도 같음)
- 해결: `navmesh.py`가 이미 쓰는 우회(events/ai/ezstate 모듈을 빈 모듈로 대체)를 재사용 — `msb_extract.py`는 `import navmesh`를 먼저 함

---

## 9. 변경 이력

- 2026-09-27: 문서 작성. 대화에서 정한 순서 반영 (기반 → 추출 → 충돌 메시 → 오버레이 → 기록 재생 → 시뮬레이터 → 탐험·전투)
- 2026-09-27: CD는 불필요(배포 대상 없음)로 판단, CI만 추가
