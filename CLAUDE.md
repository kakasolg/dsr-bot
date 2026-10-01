# CLAUDE.md

- 작업 전에 **ROADMAP.md**를 먼저 읽는다. 계획, 체크리스트, 역할 분담([cloud]/[win]/[MoKa] — 사람 작업자는 MoKa, 옛 기록의 `[사람]`도 MoKa), 문제 기록이 모두 거기 있다.
- 작업을 시작하면 해당 항목을 `[~]`로, 끝나면 `[x]` + 확인 방법·결과 한 줄로 바꾸고 커밋·푸시한다.
- 막히거나 예상과 다르면 ROADMAP.md "8. 문제 기록"에 추가한다 (지우지 않는다).
- **게시판**: [win]·[MoKa]·Mac Claude는 비공개 MCP 게시판(`maswarm-watchlist`, `board_*`)을 쓴다. **[cloud]는 그 MCP에 못 닿는다** (네트워크 허용 목록·환경변수 미설정, 2026-09-29 확인). 그래서 [cloud]와는 **저장소 파일(ROADMAP.md)과 커밋 메시지**로만 주고받는다. 공개 저장소이므로 새 GitHub Issues는 올리지 않는다 (#2~#14는 옛 기록).
  - 작업 시작 전: `git pull` 뒤 ROADMAP.md의 `[cloud]` 항목·"8. 문제 기록"·"10. 게시판 중계"를 먼저 읽는다.
  - [cloud]가 보낼 것(결과 보고, 질문, 결정 요청)은 ROADMAP "10. 게시판 중계"에 `[cloud→게시판]`으로 적는다. 게시판을 쓰는 쪽이 그것을 게시판에 옮기고 처리 표시(`→ 옮김`)를 단다.
  - 게시판에서 [cloud]로 넘길 일·답은 게시판을 쓰는 쪽이 "10. 게시판 중계"에 `[게시판→cloud]`로 옮겨 적는다. 확정된 것만 옛 항목·문제 기록에 반영한다.
  - 문제는 예전처럼 "8. 문제 기록"에 P-번호로 남긴다 (이슈는 열지 않는다).
  - 3번 전환(클라우드 전용 서비스 토큰으로 MCP 직접 연결)은 [MoKa]가 환경 설정을 끝낸 뒤에. 그때까지 이 규칙을 쓴다.
- 작업 브랜치: `claude/dsr-bot-project-review-r3hh9f`. 시작 전 `git pull`.
- Python 3.12. 오프라인 테스트 (게임 불필요): `python -m pytest` (전부) · `python -m pytest -k radar` (하나) · `python tests/radar_test.py` (스크립트 직접). 테스트는 `tests/`, 새 테스트는 `tests/<이름>_test.py`로 만들면 자동 포함.
- 폴더: 루트 = 봇 실행에 쓰이는 모듈과 도구(레이더·오버레이·추출), `souls/` = 층, `tests/` = 오프라인 테스트, `experiments/` = 봇이 쓰지 않는 옛 실험·측정 스크립트(`python experiments/x.py`로 실행), `boss/` = 보스 실험, `legacy/` = 옛 코드.
- [win] 봇을 실행한 뒤에는 매번 `python hotspots.py`(이번 실행 vs 이전: NEW·AGAIN·GONE), `python track_report.py`(계획 경로 vs 실제, 멈칫 자리), `python blind_report.py`(싸움 중 판단 공백 — 상태 줄이 2 s 넘게 끊긴 구간과 그동안 받은 피해, 원인별; 평균 틱이 같아도 이게 늘면 봇이 느려진 것)를 돌리고, 그 실행의 `data/runs/<시각>_<이름>.track.jsonl`과 로그를 `data/samples/`에 복사해 커밋한다. AGAIN이나 2번 이상 실행에서 같은 멈칫 자리, 판단 공백 피해가 이전 실행들보다 뚜렷이 늘어난 원인은, 봇이 스스로 회복했더라도 ROADMAP "8. 문제 기록"에 올린다 (죽지 않은 실수도 결함).
- 싸움 규칙(`souls/duel.py`의 `RULES`)은 위에서부터 먼저 걸리는 순서다. 규칙을 고치거나 순서를 바꾸면 `python tests/duel_golden_test.py`가 달라진 상황을 보여 준다 — 의도한 변화면 `--record`로 다시 찍고 커밋 메시지에 이유를 쓴다.
- 게임 메모리 쓰기 기능(무적·투명·워프)은 오프라인에서만 쓴다.
- 규칙과 수치 근거는 LAYERS.md, 기록 형식은 OBSERVE.md.
