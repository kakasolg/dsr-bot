# CLAUDE.md

- 작업 전에 **ROADMAP.md**를 먼저 읽는다. 계획, 체크리스트, 역할 분담([cloud]/[win]/[사람]), 문제 기록이 모두 거기 있다.
- 작업을 시작하면 해당 항목을 `[~]`로, 끝나면 `[x]` + 확인 방법·결과 한 줄로 바꾸고 커밋·푸시한다.
- 막히거나 예상과 다르면 ROADMAP.md "8. 문제 기록"에 추가한다 (지우지 않는다).
- 작업 브랜치: `claude/dsr-bot-project-review-r3hh9f`. 시작 전 `git pull`.
- Python 3.12. 오프라인 테스트 (게임 불필요): `python -m pytest` (전부) · `python -m pytest -k radar` (하나) · `python tests/radar_test.py` (스크립트 직접). 테스트는 `tests/`, 새 테스트는 `tests/<이름>_test.py`로 만들면 자동 포함.
- 폴더: 루트 = 봇 실행에 쓰이는 모듈과 도구(레이더·오버레이·추출), `souls/` = 층, `tests/` = 오프라인 테스트, `experiments/` = 봇이 쓰지 않는 옛 실험·측정 스크립트(`python experiments/x.py`로 실행), `boss/` = 보스 실험, `legacy/` = 옛 코드.
- 게임 메모리 쓰기 기능(무적·투명·워프)은 오프라인에서만 쓴다.
- 규칙과 수치 근거는 LAYERS.md, 기록 형식은 OBSERVE.md.
