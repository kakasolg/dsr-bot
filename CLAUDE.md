# CLAUDE.md

- 작업 전에 **ROADMAP.md**를 먼저 읽는다. 계획, 체크리스트, 역할 분담([cloud]/[win]/[사람]), 문제 기록이 모두 거기 있다.
- 작업을 시작하면 해당 항목을 `[~]`로, 끝나면 `[x]` + 확인 방법·결과 한 줄로 바꾸고 커밋·푸시한다.
- 막히거나 예상과 다르면 ROADMAP.md "8. 문제 기록"에 추가한다 (지우지 않는다).
- **게시판 = GitHub Issues** (`kakasolg/dsr-bot`). 역할 라벨 `cloud`·`win`·`사람`, 종류 라벨 `결과`·`질문`·`문제`·`결정`. 템플릿: `.github/ISSUE_TEMPLATE/`.
  - 작업 시작 전: 내 역할 라벨이 붙은 **열린 이슈**를 먼저 확인한다 (ROADMAP과 같이).
  - 주고받는 것(실행 결과 보고, 질문, 결정 요청, 토론)은 이슈와 댓글로. **확정된 것만** ROADMAP.md에 옮기고 항목 끝에 `→ #번호`를 단다.
  - 문제는 ROADMAP "8. 문제 기록"에 P-번호를 만들고, 같은 번호로 이슈(`문제` 라벨)를 연다. 커밋 메시지에 `#번호`를 쓰면 이슈에 연결된다.
  - 다른 작업자에게 넘길 일은 그 역할 라벨을 붙인다. 끝나면 결과를 댓글로 남기고 닫는다.
- 작업 브랜치: `claude/dsr-bot-project-review-r3hh9f`. 시작 전 `git pull`.
- Python 3.12. 오프라인 테스트 (게임 불필요): `python -m pytest` (전부) · `python -m pytest -k radar` (하나) · `python tests/radar_test.py` (스크립트 직접). 테스트는 `tests/`, 새 테스트는 `tests/<이름>_test.py`로 만들면 자동 포함.
- 폴더: 루트 = 봇 실행에 쓰이는 모듈과 도구(레이더·오버레이·추출), `souls/` = 층, `tests/` = 오프라인 테스트, `experiments/` = 봇이 쓰지 않는 옛 실험·측정 스크립트(`python experiments/x.py`로 실행), `boss/` = 보스 실험, `legacy/` = 옛 코드.
- [win] 봇을 실행한 뒤에는 매번 `python hotspots.py`(이번 실행 vs 이전: NEW·AGAIN·GONE)와 `python track_report.py`(계획 경로 vs 실제, 멈칫 자리)를 돌리고, 그 실행의 `data/runs/<시각>_<이름>.track.jsonl`과 로그를 `data/samples/`에 복사해 커밋한다. AGAIN이나 2번 이상 실행에서 같은 멈칫 자리는, 봇이 스스로 회복했더라도 ROADMAP "8. 문제 기록"에 올린다 (죽지 않은 실수도 결함).
- 싸움 규칙(`souls/duel.py`의 `RULES`)은 위에서부터 먼저 걸리는 순서다. 규칙을 고치거나 순서를 바꾸면 `python tests/duel_golden_test.py`가 달라진 상황을 보여 준다 — 의도한 변화면 `--record`로 다시 찍고 커밋 메시지에 이유를 쓴다.
- 게임 메모리 쓰기 기능(무적·투명·워프)은 오프라인에서만 쓴다.
- 규칙과 수치 근거는 LAYERS.md, 기록 형식은 OBSERVE.md.
