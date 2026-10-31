# 분기 감사 출처 (2026-10-31, [cloud])

## 이 디렉터리의 파일

- `rows.json` — 장면별 분기 판정 결과. 대상은 P-80 이후 코드의 stagger_punish 전 장면이다.
  - 분기 종류: late_guard / strike / turn_only / pre_P80
  - 함께 담은 값: 경과 시간, 경계 여유, 핵심 조건 여부
- `consts.json` — 커밋별 `stagger_s`와 무기 값(startup, reach, sp_min).
- `branch_consts.cmd.txt`, `branch_classify.cmd.txt` — `consts.json`과 `rows.json`을 만든 명령 원문.
  - 원래 스크립트 파일 없이 표준 입력으로 실행했다. 그래서 **세션 기록에서 복원한 원문**이다.
  - 이 저장소 경로에서 다시 실행해 보지 않았다.
  - 명령 안의 경로(`/tmp/inv3`, `/tmp/spaudit_consts`, `/tmp/stagmem/run`)는 상위 `README.md`의 대응표를 따른다.

## 커밋별 상수 원본 (사본은 커밋하지 않음)

- 감사 때는 아래 커밋의 `souls/foes.py`와 `souls/weapons.py`를 `git show <commit>:<path>`로 꺼냈다.
- 꺼낸 파일은 격리된 임시 디렉터리에서 데이터 모듈로만 import했다. 봇 로직은 실행하지 않았다.
- 그 사본 22개는 아래 git 객체와 sha256이 같다. 11개 커밋은 모두 `origin/ccr-0daec3e4-ierxrw`에 들어 있다.

| 상태 | 모듈 | 커밋 | sha256 (`git show <commit>:souls/<모듈>.py`) |
|---|---|---|---|
| OK | foes | `13f152b62420ccf3e842d1ed34866228c135de0e` | `d8ebdb87e98d78e44be5fd8e8bce6939be74af5e17c9004d3700deeddd0564b6` |
| OK | foes | `26278c0c4983c24468e475c49471a53885f3ffee` | `d8ebdb87e98d78e44be5fd8e8bce6939be74af5e17c9004d3700deeddd0564b6` |
| OK | foes | `361796be434c628909f7b2d356dccab654057fa3` | `d8ebdb87e98d78e44be5fd8e8bce6939be74af5e17c9004d3700deeddd0564b6` |
| OK | foes | `4796a4b5f68e2558d120866a9df963596986eb05` | `d8ebdb87e98d78e44be5fd8e8bce6939be74af5e17c9004d3700deeddd0564b6` |
| OK | foes | `5ba6854d3ff41f56b307482d6a8c782ef9afbc9e` | `d8ebdb87e98d78e44be5fd8e8bce6939be74af5e17c9004d3700deeddd0564b6` |
| OK | foes | `66cebffa1207f8fc9283d53eb00d06045765bde4` | `d8ebdb87e98d78e44be5fd8e8bce6939be74af5e17c9004d3700deeddd0564b6` |
| OK | foes | `69b15c98e35b389b01c56729445e5822fcde4449` | `d8ebdb87e98d78e44be5fd8e8bce6939be74af5e17c9004d3700deeddd0564b6` |
| OK | foes | `af93953cb115e69ac8b68bf6131cad7974038669` | `d8ebdb87e98d78e44be5fd8e8bce6939be74af5e17c9004d3700deeddd0564b6` |
| OK | foes | `dbc5bda660b3af9a1411dbfcc1212e7199ffd816` | `d8ebdb87e98d78e44be5fd8e8bce6939be74af5e17c9004d3700deeddd0564b6` |
| OK | foes | `f36afcd60ab11793ac0b04c618f06c9f593cab5e` | `01153c4e7f00efe9a2c19427b1902f1e6d4bf9d316d410e0dadde5efc51c9b88` |
| OK | foes | `fdba4c59a5f71509e1837ab756be91a7f8434ad5` | `d8ebdb87e98d78e44be5fd8e8bce6939be74af5e17c9004d3700deeddd0564b6` |
| OK | weapons | `13f152b62420ccf3e842d1ed34866228c135de0e` | `7c6b506304b5e8daf1da3ee47ff395db6ce7e39448d92667703a5a1b00c02136` |
| OK | weapons | `26278c0c4983c24468e475c49471a53885f3ffee` | `7c6b506304b5e8daf1da3ee47ff395db6ce7e39448d92667703a5a1b00c02136` |
| OK | weapons | `361796be434c628909f7b2d356dccab654057fa3` | `7c6b506304b5e8daf1da3ee47ff395db6ce7e39448d92667703a5a1b00c02136` |
| OK | weapons | `4796a4b5f68e2558d120866a9df963596986eb05` | `8c9a6ae0db3d5c87c59ae9de8f634f6c0bc703297d2b4d6df36e2c15dcafe480` |
| OK | weapons | `5ba6854d3ff41f56b307482d6a8c782ef9afbc9e` | `8c9a6ae0db3d5c87c59ae9de8f634f6c0bc703297d2b4d6df36e2c15dcafe480` |
| OK | weapons | `66cebffa1207f8fc9283d53eb00d06045765bde4` | `7c6b506304b5e8daf1da3ee47ff395db6ce7e39448d92667703a5a1b00c02136` |
| OK | weapons | `69b15c98e35b389b01c56729445e5822fcde4449` | `7c6b506304b5e8daf1da3ee47ff395db6ce7e39448d92667703a5a1b00c02136` |
| OK | weapons | `af93953cb115e69ac8b68bf6131cad7974038669` | `7c6b506304b5e8daf1da3ee47ff395db6ce7e39448d92667703a5a1b00c02136` |
| OK | weapons | `dbc5bda660b3af9a1411dbfcc1212e7199ffd816` | `8c9a6ae0db3d5c87c59ae9de8f634f6c0bc703297d2b4d6df36e2c15dcafe480` |
| OK | weapons | `f36afcd60ab11793ac0b04c618f06c9f593cab5e` | `7c6b506304b5e8daf1da3ee47ff395db6ce7e39448d92667703a5a1b00c02136` |
| OK | weapons | `fdba4c59a5f71509e1837ab756be91a7f8434ad5` | `8c9a6ae0db3d5c87c59ae9de8f634f6c0bc703297d2b4d6df36e2c15dcafe480` |
