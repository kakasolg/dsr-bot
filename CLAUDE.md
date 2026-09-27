# CLAUDE.md

- 작업 전에 **ROADMAP.md**를 먼저 읽는다. 계획, 체크리스트, 역할 분담([cloud]/[win]/[사람]), 문제 기록이 모두 거기 있다.
- 작업을 시작하면 해당 항목을 `[~]`로, 끝나면 `[x]` + 확인 방법·결과 한 줄로 바꾸고 커밋·푸시한다.
- 막히거나 예상과 다르면 ROADMAP.md "8. 문제 기록"에 추가한다 (지우지 않는다).
- 작업 브랜치: `claude/dsr-bot-project-review-r3hh9f`. 시작 전 `git pull`.
- Python 3.12. 오프라인 테스트: `python field_*_test.py`, `duel_shadow_test.py`, `moves_test.py`, `observe_record_test.py`, `feed_test.py`, `msb_extract_test.py`, `radar_test.py`, `props_test.py`, `overlay_test.py`, `translate_test.py` (게임 불필요).
- 게임 메모리 쓰기 기능(무적·투명·워프)은 오프라인에서만 쓴다.
- 규칙과 수치 근거는 LAYERS.md, 기록 형식은 OBSERVE.md.
