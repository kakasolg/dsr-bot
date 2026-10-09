# 설계안: 실행 설정 기록 (2026-10-09, [cloud])

`docs/analysis-2026-10-09.md` §3 제안 5의 설계. **아직 결정 아님** — §7의 질문에 [MoKa]가 답한 뒤 단계 1부터.
관련: ROADMAP 2 "[MoKa] decide run settings file `<run>.settings.json` + `code_commit` / zone / fight id in logs (1-i, 1-j)", P-34, 제안 1~4의 A/B·라벨 비교.

한 줄 요약: 실행마다 **무슨 코드로(커밋 + 커밋 안 한 수정), 무슨 인자로, 무슨 상수·데이터로, 어떤 캐릭터 상태에서** 돌았는지를
`<run>.settings.json` 하나에 남기고, 로그 첫 줄과 track 첫 줄에도 짧게 찍는다. 싸움마다 `fight_id`, 구역마다 `zone`.
지금은 `data/samples/` 로그 115개 중 **커밋이 적힌 것 0개**, 실행 시각이 남은 것 8개, 인자(`--basic` 등)가 적힌 것 0개다.

---

## 1. 지금 무엇이 남나

| 파일 (`data/runs/<stamp>_<cmd>.*`) | 커밋 | 인자 | 비고 |
|---|---|---|---|
| `.log` (→ `data/samples/*.txt`로 복사) | 없음 | 없음 | 무기 줄 `무기: … 닿는 거리 …`만 |
| `.jsonl` (이벤트) | 없음 | 없음 | |
| `.track.jsonl` (→ samples) | 없음 | 없음 | |
| `.ctl.jsonl` (`--ctl`일 때만) | `hdr.commit` (`.git`에서 읽음) | `life.start.args` | **samples로 복사 안 됨** (0개) |
| attack audit (`--attack-audit`) | commit + dirty (git 실행) | — | 동결 (schema 0.3) |
| 라벨 장면 (`label_pilot build`) | `code_commit` + **`code_commit_approx: true`** (실행 시각으로 추정) | 없음 | |

## 2. 오늘 확인한 사실

### a. samples엔 실행을 다시 찾을 단서가 거의 없다
- `data/samples/*.txt` 115개: 커밋 0 · 인자 0 · 이름에 시각(`…-2026-10-06-195804`)이 있는 것 **8개**, 나머지 107개는 날짜+글자(`…-10-06h`)뿐 →
  `git log`와 시각으로 맞춰 볼 수도 없다 (시각은 [win]의 `data/runs/` 원래 이름에만 있음).

### b. 시각으로 맞춘 8개도 다 믿을 수는 없다 (10-06 저녁, 태평양 시간)
| 실행 | 바로 앞 커밋 | 실제 코드 |
|---|---|---|
| 19:18:13 | `d5bd3a8` 19:18:01 (12 s 전) | 아마 그 커밋 |
| 19:58:04 | `93aff16` 19:57:51 (13 s 전) | 아마 그 커밋 |
| **20:03:35 · 20:07:29** | `93aff16` 19:57:51 | **아님** — P-46 기록: 그 사이 [MoKa] "기다리지 말고"로 구역 5 `wait`를 빼고, "안개벽 처리 않해?"로 구역 8 안개벽 단계를 되살린 뒤 돌림 → **커밋 안 한 수정**으로 돈 실행. 그 수정은 20:09:12 `cc0d272`에 들어감 |
| 20:15:50 | `c5be676` 20:15:39 (11 s 전) | 아마 그 커밋 |
- 커밋 → 바로 실행(10~13 s)이 흔하고, **커밋 전에 고친 채로 돌리는 일**도 있다. 시각 추정은 맞을 때도 "아마"이고 틀릴 때는 모른다.

### c. 인자를 모르면 결과 해석이 갈린다
- `experiments/label_probe.py`(design-scene-expectations §2-b): 같은 87장면이 `--basic`(뒤잡기·강공 끔)이냐 아니냐에 따라 오늘 규칙의 [MoKa] 일치가
  **31 % ↔ 56 %**. 장면엔 그 실행이 `--basic`이었는지가 없다.
- 싸움 상수(module 대문자 상수)는 `souls/duel.py` 79 · `field.py` 79 · `missions.py` 26 · `nav.py` 27 등 **약 250개, JSON 5 KB** — 통째로 남겨도 작다.
  `--basic`처럼 인자가 상수를 바꾸므로(`duel.BACKSTAB`, `duel.HEAVY`) 인자만으로는 부족하고 **적용된 뒤의 값**이 필요하다.

## 3. 설계

### 3.1 `data/runs/<stamp>_<cmd>.settings.json` — 실행 시작 때 한 번, 끝날 때 `end`만 덧붙임
```json
{"schema": "dsr-run/0.1", "run": "20261006_200335_burg-upper", "started": "2026-10-06T20:03:35-07:00",
 "code": {"commit": "93aff16…", "branch": "claude/dsr-bot-project-review-r3hh9f", "dirty": true,
          "dirty_files": ["souls/missions.py", "data/burg-upper-map.json"], "diff_sha1": "…", "diff_file": "20261006_200335_burg-upper.diff"},
 "argv": ["run.py", "burg-upper", "--seg", "5-8", "--basic", "--radar", "--ctl"],
 "args": {"cmd": "burg-upper", "seg": "5-8", "basic": true, "style": "guard", "no_lure": false, …},
 "constants": {"souls.duel": {"BACKSTAB": false, "HEAVY": false, "NO_BACKSTAB_N": 2, …}, "souls.field": {…}, "nav": {…}, …},
 "constants_sha1": "…",
 "data": {"data/burg-upper-map.json": "sha1…", "data/safe-zones.json": "sha1…", "souls/foes.py": "sha1…", "navmesh m10_01_00_00": "tri 7217"},
 "game": {"hp": [742, 742], "weapon": [<id>, "Battle Axe"], "grip": 1, "estus": 10, "souls": …, "humanity": …, "knives": …,
          "quick_items": […], "last_bonfire": …, "pos": [x, y, z]},
 "note": "save backup-20261006-155749-burg-bonfire-hp742-before-taurus",
 "end": {"at": "…", "secs": 312.4, "result": "cleared|left #i|dead|user_stop|exception", "deaths": 0, "estus_left": 3}}
```
- **커밋**: `.git`에서 읽음(`ctl._commit`처럼, git 실행 파일 없이). **dirty**: `git status --porcelain --untracked-files=no` (git이 없으면 `null` — 모른다고 적음).
- **diff**: dirty면 `git diff HEAD`를 `<run>.diff`로 (§7-①). 20:03:35 같은 실행을 나중에 정확히 다시 만들 수 있는 유일한 길.
- **constants**: 위 모듈들의 대문자 `int/float/bool/str/tuple` — 인자 적용 **뒤** 값. 한 줄 모듈 목록(`SETTINGS_MODULES`)만 관리.
- **game**: `run.py status`가 이미 읽는 값 — 패드 없이 읽기만, 실패하면 그 칸만 `null`.
- **note**: `--note "…"` (세이브 이름 등 사람이 붙이는 한 줄). 없으면 빈칸.
- 쓰기 실패는 실행을 멈추지 않음 — 로그에 `⚠ settings 못 씀` 한 줄.

### 3.2 짧은 표시 — 복사돼도 남게
- 로그 첫 줄: `run 20261006_200335_burg-upper · code 93aff16+dirty(2) · --seg 5-8 --basic --radar --ctl · settings 9f3c…`
  → `data/samples/*.txt`로 복사돼도 커밋·인자가 따라간다. `hotspots.py`·`track_report.py`·`blind_report.py`가 이 줄을 읽어 표 머리에 찍음.
- track 첫 줄 `{"type": "run", "run": …, "commit": …, "dirty": …, "settings_sha1": …}`, `ctl` hdr·laya 행에 `run`·`settings_sha1`.

### 3.3 `fight_id`·`zone`
- `fight_id = <run>#f<NNN>`: `Field.fight` 시작마다 하나 (`_fight_once` 묶음 단위 — 묶기로 끊고 다시 받은 것도 같은 싸움). duel 상태 줄·`duel` 이벤트·블랙박스·라벨 장면에.
- `zone`: `Missions`가 구역·구간을 시작할 때 `field.zone = "burg-upper:5"`(asylum `asylum:3`, burg-bonfire `burg:4`) — 이벤트마다 붙음. 지금 로그의 `══ 구역 N … 끝` 줄과 같은 값.
- `blind_report`·`hotspots`가 구역별로 묶을 수 있게 됨 (지금은 좌표로만).

### 3.4 samples 복사 — 이름에 시각 유지
- 지금 [win]은 실행 뒤 log·track을 `data/samples/<무엇>-<날짜><글자>.*`로 복사(CLAUDE.md "after every bot run"). 제안: `python sample.py <run> [이름]`이
  `<stamp>_<cmd>[_이름].{txt,track.jsonl,settings.json,diff}`로 한 번에 복사 — 시각이 이름에 남고 settings가 같이 감. 옛 이름 파일은 그대로.
- `.ctl.jsonl`은 크면 복사 안 함(지금처럼), settings가 대신 커밋·인자를 갖는다.

### 3.5 읽는 쪽
- `label_pilot.py build`: settings가 있으면 `code_commit`을 거기서, `code_commit_approx` 없앰, 장면에 `flags`(BACKSTAB·HEAVY…) — design-scene-expectations의 재구성 설정을 정확히.
- **`python ab.py <run> <run> …`**(새, 작음): 두 묶음 실행의 settings 차이(커밋·dirty·인자·상수·데이터·시작 HP·에스트)를 먼저 보여 주고, 결과(사망·최저 HP·
  `hotspots`·`blind_report` 숫자)를 나란히. **의도한 차이(예: `--spot`) 말고 다른 것도 다르면 경고** — 제안 1~3의 A/B가 이것을 씀.
- settings 없는 옛 실행: 모든 도구가 "settings 없음"으로 그대로 동작.

## 4. 코드 배치
- `runinfo.py`(새, 루트): `collect(args, tm=None) → dict`, `write(path, d)`, `end(path, **kw)`, `short(d) → str`, `read(path)`. 게임 의존 없음(`tm`이 없으면 `game` 비움).
- `run.py`: `Log` 만든 직후 `runinfo.write(…)` + 첫 줄, `--basic` 등 플래그 적용 **뒤** 상수 수집(지금 플래그 적용 위치 다음으로), 끝·예외 경로에서 `runinfo.end(…)`
  (`ctl.emit("life", …)`가 있는 자리와 같음). `--note`.
- `souls/field.py` `fight_id` 카운터·`zone`, `track.py` 첫 줄, `ctl.start`에 `settings_sha1`.
- `sample.py`(새), `ab.py`(새). CLAUDE.md "[win] after every bot run"의 복사 문장을 `python sample.py`로 (MoKa 승인 뒤).
- 테스트 `tests/runinfo_test.py`: 임시 git 저장소에서 clean/dirty·diff, `--basic`이 상수에 반영됨, git 없을 때 `null`, 쓰기 실패해도 예외 없음, `short()` 형식. 판단 코드는 안 건드림 → golden 그대로.

## 5. 확인 계획
1. 오프라인: `tests/runinfo_test.py` · pytest 전체 · golden 그대로 · `python run.py status`는 settings를 안 씀(읽기 전용 명령).
2. [win] 아무 실행 하나 (`--seg` 짧게): `.settings.json`·첫 줄·track 첫 줄이 있는지, 일부러 한 줄 고친 채 한 번 더 → `dirty: true`와 `.diff`.
3. `python sample.py`로 복사 → `hotspots.py`·`track_report.py`·`blind_report.py` 머리에 커밋·인자가 찍히는지.
4. `ab.py`로 그 두 실행 → "dirty 다름" 경고가 나오는지.

## 6. 단계
1. [cloud] `runinfo.py` + `run.py` 연결 + `fight_id`·`zone` + 테스트. (봇 판단 변화 없음)
2. [cloud] `sample.py`·`ab.py`·리포트 머리줄·`label_pilot` 읽기.
3. [win] §5-2·3·4 한 번.
4. [MoKa] CLAUDE.md 복사 절차를 `sample.py`로 바꾸는 것 승인 → 그 뒤 모든 실행.
5. 제안 1~4의 A/B는 `ab.py`로 비교.

## 7. [MoKa] 결정할 것
1. **커밋 안 한 수정의 diff를 `<run>.diff`로 남기는 것** — 저장소가 공개라 samples로 복사하면 아직 다듬지 않은 코드가 그대로 올라감. 대안: diff는 `data/runs/`(로컬)에만,
   samples엔 바뀐 파일 이름과 해시만.
2. samples 이름 규칙을 `<stamp>_<cmd>[_이름]`으로 (시각 유지) — 지금의 `<무엇>-<날짜><글자>` 대신. 옛 파일은 그대로 둠.
3. 게임 상태(소울·인간성·위치 포함)를 settings에 남기는 것 — 공개 저장소에 올라가도 괜찮은지.
4. dirty 상태로 돌리는 것을 막지는 않고 **기록만** (제안) — 아니면 dirty면 경고 한 줄 뒤 계속.

## 8. 한계
- 게임 쪽 상태 중 메모리에서 못 읽는 것(세이브 파일 이름, 레벨업 내역)은 `--note`로 사람이 적어야 한다.
- 상수 수집은 모듈 목록에 있는 것만 — 새 모듈의 상수는 목록에 넣어야 남는다(테스트가 "duel·field·missions·nav는 꼭 있음"을 확인).
- 이미 지난 107개 실행의 커밋은 되살릴 수 없다. [win]의 `data/runs/` 원래 이름(시각)과 `git log`로 "아마"까지만.
