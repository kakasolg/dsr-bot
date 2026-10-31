# 경험 데이터 수집·연결 구조 — 마무리 (2026-10-31, ROADMAP `ctl-linkage`)

한 줄 요약: 봇의 **관측 → 판단/동작 → 가상 패드 출력 → 이후 관측·결과**를 한 파일 안에서 서로 가리키게 기록하는 구조를
만들었고, 오프라인 테스트와 실제 게임 3회에서 기록이 끝까지 쓰이고 연결이 맞는지를 확인했다. 그 이상은 확인하지 않았다.

필드 정의·ID 규칙·완전성 용어는 [`ctl-linkage.md`](ctl-linkage.md)에 있다. 이 문서는 그 구조를 **어디까지 시험했고 무엇이
남았는지**만 적는다 (같은 내용을 두 곳에 쓰지 않는다).

## A. 목적과 범위

- 향후 모델 실험(SIMA형 에이전트, decision model 등)에 다시 쓸 수 있도록, 지금 룰 봇이 실제로 본 것·고른 것·누른 것·그 뒤에
  일어난 것을 **연결된 원본 기록**으로 남길 수 있는지 제한된 범위에서 확인한 작업이다 ([MoKa] 2026-10-30 ~ 10-31 요청).
- 특정 모델이 룰보다 낫다는 것을 검증한 작업이 **아니다**. 모델은 학습·도입하지 않았다.
- SIMA 공식 데이터셋 형식을 구현하거나 SIMA와의 호환성을 검증한 것이 **아니다**.
- decision model을 바로 학습할 만큼 데이터가 모였다는 뜻이 **아니다** (실제 게임 기록 3회, 싸움 17번).
- 판단·행동·센서·기록 주기·반경·룰·상수는 바꾸지 않았다. 기록만 더했다.

## B. 구현한 구조와 켜는 옵션

| 무엇 | 레코드 / 파일 | 켜는 옵션 | 코드 |
|---|---|---|---|
| 패드·판단 타이밍 기록 (기존 P1) | `<run>.ctl.jsonl`: `hdr`(commit·argv), `sync`(QPC↔벽시계), `pad`, `neutral`, `dec.*`, `life`, `end` | `--ctl` | `ctl.py` |
| fight / cycle / rule / action 연결 | `span.fight` · `span.cycle` · `span.rule` · `span.action` (부모 id, `pc` 시각, 동작 매개변수, Hit 복사) | `--ctl-spans` (`--ctl`을 함께 켬) | `ctlspan.py`, `souls/duel.py`, `souls/moves.py` |
| 스레드별 ID와 가상 패드 상태 | `pad` / `pad.drop`에 **그 기록을 쓴 스레드의** `cycle_id` · `action_id`, `th`, `caller`; `pad.override` (keep_guard가 LB를 붙잡은 채 guard(False)/neutral()) | `--ctl-spans` | `control.py` (`Pad._record`, `_override_rec`) |
| 관측 본문과 참조 | `span.obs`(cycle이 `_sense`에서 읽은 스냅샷 전부: Snapshot 필드 + 플레이어 + `s.chars` 100 m) · cycle 끝의 `obs_id` | `--ctl-spans` | `ctlspan.Fight.sensed` |
| 관측 출처·범위·시각, 추가 읽기 횟수 | cycle 끝: `src`(feed / direct), `radius`, `snap_t`, `fseq`, `resnap`, `snap_reads_sense` / `snap_reads_after` | `--ctl-spans` | `ctlspan.snap_read()` (`dsr_telemetry.snapshot`, 피드 캐시 경로) |
| 결정 순간 입력 (기존) | `scene` (개체 25 m, 일부 규칙은 상태가 바뀔 때만) | `--ctl-scenes` (`--ctl`을 함께 켬) | `scenes.py` |
| 실행 설정·코드·세이브·종료 상태 | `<run>.settings.json` (`code.commit/dirty_files/diff_sha256`, `inputs`, `game`(장비·에스트·세이브 sl2 sha256), `end.end_read`(`src`·`fseq`·`age_s`) / `last_valid_obs` / `end_state_known`), `<run>.diff` | **늘 켜짐** (모든 실행) | `runinfo.py` |
| writer 종료 완전성 | `end` 레코드의 `writer_joined` · `complete` (+ `written` · `dropped` · `lost` · `write_errors`) | `--ctl` | `ctl.Sink.stop` |
| 검사 도구 | `python ctl_check.py <run>.ctl.jsonl` (writer · 연결 · cycle별 관측 보존 상태) · `--vs-scene` (scene ↔ span.obs 저장 일관성) · `--cycles a,b` (본문 출력) | 오프라인 | `ctl_check.py` |

`--attack-audit`(공격 규칙 입력·결과 proxy, `attack_audit.py`)와 `--ctl-frames`(피드 프레임 매 줄)는 이전부터 있던 별도 기록이다.

## C. 실제 검증 범위

### 오프라인 (게임 없음)
- 2026-10-31 지금 작업 트리: `python -m pytest` **123 passed**. ctl 관련 스크립트 `tests/ctl_spans_test.py` ·
  `ctl_span_obs_test.py` · `ctl_writer_test.py` · `runinfo_test.py` · `ctl_obs_test.py` 각각 단독 실행 exit 0.
- 확인 내용(테스트가 보는 것): spans 켬/끔에 golden 판단이 같음, 큐가 가득 차거나 sink가 예외를 내도 판단이 같음, span 짝·부모,
  span.obs 복원·id 겹침 없음·dropped/missing/broken 표시, writer 종료 순서. 오프라인 수치는 `docs/roadmap/plan.md` `ctl-linkage` 줄.

### 실제 게임 3회 (원본: `data/runs/<run>.*`, 해시: [`ctl-experience-data.sha256`](ctl-experience-data.sha256))

검사 출력은 모두 `python ctl_check.py data/runs/<run>.ctl.jsonl [--vs-scene]` (checker sha256 `9deb9fefba46b45a…`)의 값이다.

| | 20261030_225853_parish-group1 | 20261030_233127_parish-group1 | 20261031_005154_burg-bonfire |
|---|---|---|---|
| 목적 | 연결 기록(7b33bd6)의 게임 확인 | span.obs 보존·복원, scene 일관성 | 초기 캐릭터 세이브에서 현재 룰 실행·기록 확인 |
| 명령 | `parish-group1 --radar --ctl-spans --ctl-scenes` | 같음 | `burg-bonfire --seg 1 --no-lure --basic --radar --ctl --attack-audit --ctl-spans --ctl-scenes` |
| 코드 | 7b33bd6 + dirty 3 (Sink.stop) | 7b33bd6 + dirty 10 (span.obs) | 7b33bd6 + dirty 12 |
| 시작 (settings `game`) | Claymore+5, HP 793/793, 에스트 10, 세이브 복원 없음 | HP 789/793 (1회 직후 그대로), 복원 없음 | SL4 배틀 액스, HP 616/616, 에스트 2(휴식 전), 마지막 화톳불 1022960 — `backup-20261003-164637…` (sl2 `829d5ae2…`)을 덮어쓰고 이어하기 |
| 봇이 보고한 결과 | cleared, 56.0 s, 끝 HP 789/793 | cleared, 107.8 s, 끝 HP 616/793 | 경사로 cleared, 110.0 s, 최저 HP 503/616, 에스트 1회 |
| writer | `complete True`, written 2148, dropped 0 | `complete True`, written 4285, dropped 0 | `complete True`, written 4911, dropped 0 |
| 연결 | fight 3 · cycle 91 · action 3 모두 짝, picked↔span.rule 불일치 0, 주 스레드 패드 id 위반 0 | fight 2 · cycle 68 · action 3, 위반 0 | fight 12 · cycle 366 · action 7, 위반 0 |
| 관측 보존 | span.obs 없음 (그 코드 전) — no_obs 91 | sense_only 61 · partial 6 · no_obs 1 | sense_only 344 · partial 16 · no_obs 6 |
| scene ↔ span.obs | — | 3/3 같음 | 17/17 같음 |
| 기록 크기 | — | span.obs 1.54 MB / 파일 2.54 MB | span.obs 13.5 MB / 파일 14.8 MB (개체 74–128) |

- 이 세 실행과 `ctl_check.py` 검사 범위에서 연결 불변식 위반 0건. 세 번째 실행은 사람 개입 없음(그 세션 기록 기준).
- 세 번째 실행의 처치 관측: 경사로 적 6 중 5는 저장된 span.obs에 HP 0이 남아 있다. #6(254000)은 마지막 span.obs가 공격
  직전(HP 75)이라 저장 관측으로는 처치를 보여 줄 수 없다 — 근거는 동작 끝에 봇이 읽은 `dead`와 track에서 사라진 것뿐.
- 2회차 실행 안의 −174 피격 분석은 `problems.md` P-95, 세 번째 실행의 과거(10-03) 비교는 `plan.md` `ctl-linkage` 줄.

### 증거의 한계
- 실행 3회, 같은 구간 반복 없음. "안정적으로 동작"이라고 말할 근거가 아니다.
- 부하(켬/끔 비교)는 재지 않았다. 세 번째 실행의 ctl 파일은 대부분이 span.obs다.
- 1회차 `hits.jsonl`은 0바이트(큰 피격 없음). 영상은 이 세 실행에서 녹화하지 않았다.

## D. 지금 모이는 자료와 재사용

| 자료 | 어디 |
|---|---|
| 원시 개체 스냅샷 (플레이어·적 위치·HP·애니·거리, 카메라) | `span.obs` (cycle마다, `--ctl-spans`) · `scene` (결정마다 25 m) · `track.jsonl` (0.5 s) |
| 판단과 동작의 연결·시각·매개변수 | `span.cycle` → `span.rule`(고른 규칙, enter/first_pad/ret `pc`) → `span.action`(params, end, Hit) · `dec.rule` |
| 가상 패드 출력과 출력 주체 | `pad`(버튼·스틱, `th`, `caller`, `cycle_id`/`action_id`) · `pad.override` |
| 이후 관측과 결과 | 다음 cycle의 span.obs · `span.action.end`(dead/early…) · `span.fight.end.result` · `hits.jsonl`(큰 피격 전후 프레임) · settings `end` |
| 실행 환경·장비·세이브·코드 버전 | settings (`code`, `game.save.sha256`, `inputs`), `<run>.diff`, ctl `hdr` |

이 연결이 있으면 나중에 (1) 그 상황에서 룰이 고른 동작을 따라 하는 정책 모방, (2) 동작 뒤 HP·처치 같은 결과 예측,
(3) 어떤 decision model이 같은 관측에서 무엇을 골랐을지 오프라인 비교에 같은 원본을 다시 쓸 수 있다. **지금 데이터만으로
기존 룰보다 나은 정책을 학습할 수 있다는 뜻은 아니다** — 양이 적고, 룰이 고른 행동만 있어 다른 행동의 결과가 없다.

## E. 지금의 한계

네 가지는 서로를 대신하지 않는다 (정의: [`ctl-linkage.md` 네 가지 완전성](ctl-linkage.md)).
- **writer complete** — 기록이 끝까지 쓰였다는 것만. 무엇이 기록됐는지는 말하지 않는다.
- **linkage validity** — span 짝·부모·패드 id가 서로 맞는다는 것만.
- **관측 보존 범위 (sense_only / partial / no_obs)** — sense_only도 전체 판단 입력 보존이 아니다. 빠진 것: Fight 기억(`F.*`),
  반사·care·shadow 상태, `Moves.swung`, 단일 값 읽기(grip, lock_target, handle, goods_count), sense 뒤 재관측의 본문(횟수만 셈).
  다른 스레드(CamFollow·GuardKeep·Escape)가 바꾸는 공유 상태는 재현하지 않는다.
- **full decision replay** — 지금 어떤 파일도 갖고 있지 않다.

그 밖에:
- 가상 패드 출력은 기록된 장치 상태다. 게임이 그 입력을 받아들였다는 직접 증거가 아니다.
- `--vs-scene`은 같은 스냅샷에서 나온 두 기록의 저장 일관성 검사다. 독립 센서 확인이 아니다.
- 걷기(`Field._walk`, `nav.goto`)는 span을 열지 않는다. 다른 스레드의 패드 기록엔 id가 없다.
- None을 돌려주면서 패드에 쓴 규칙(prep_face 등)은 `cycle_id`만 붙는다.
- 영상·스크린샷은 필요할 때 따로 썼지만, 전 실행의 동기화된 시각 학습 데이터 수집은 만들지 않았다.
- 미검증: 세 실행에서 나온 동작은 light·kick_combo뿐이다 — 나머지 동작(heavy·backstep·roll·drink 등)의 span, 취소, Escape 경로,
  실전 큐 포화, 켬/끔 부하 영향은 게임에서 확인하지 않았다.
- 투사체는 읽지 않는다 — 원거리 피격의 원인 개체는 기록으로 특정할 수 없다(P-95 및 세 번째 실행의 −113).

## F. 보관과 재사용

- **원본**: `data/runs/<run>.{ctl.jsonl,log,jsonl,track.jsonl,hits.jsonl,settings.json,diff}` (+ 세 번째는 `attack_audit.jsonl`).
  `data/runs/`는 git에 안 들어간다 — [win] PC에만 있다. 사본 일부(`.txt` 로그, track, settings, jsonl)는 `data/samples/`.
  ctl.jsonl·diff·hits는 samples에 없다.
- **해시 확인**: 저장소 루트에서 `grep -v '^#' docs/ctl-experience-data.sha256 | sha256sum -c` (34개, 2026-10-31 통과).
  각 실행의 미커밋 diff는 settings `code.diff_sha256`과 `<run>.diff`로 대조한다.
- **세이브 백업** (`Documents\NBGI\DARK SOULS REMASTERED\`, sl2 sha256):
  초기 `backup-20261003-164637-asylum-10-03h-done-before-burg` `829d5ae24122242d…` (원본, 바뀌지 않음) ·
  시험 전 진행 `backup-20261031-005019-r7-current-progress-before-initial-test` `6a078518fe1a8eac…` ·
  시험 직후 `backup-20261031-005457-r7-after-initial-save-test` `7c0a634d47cb473f…`.
- **검사 예**:
  ```
  python ctl_check.py data/runs/20261031_005154_burg-bonfire.ctl.jsonl
  python ctl_check.py data/runs/20261030_233127_parish-group1.ctl.jsonl --vs-scene
  python ctl_check.py data/runs/20261030_233127_parish-group1.ctl.jsonl --cycles 805,814
  ```
  한 cycle의 관측 본문: `ctl_check.restore(ctl_check.load(Path(f)), obs_id)` → dict(`player`, `chars`, `t`, …).
- **스키마**: span·패드 필드 [`ctl-linkage.md`](ctl-linkage.md) · ctl 공통(`ctl/1`) `ctl.py` 머리말 · scene `scenes.py`
  (`dsr-scene-input/0.2`) · settings [`design-run-settings.md`](design-run-settings.md) · attack audit `attack_audit.py`
  (`dsr-attack-audit/0.3`) · 기타 기록 형식 `OBSERVE.md`.
- **코드 상태**: HEAD 7b33bd6. 이 작업의 미커밋 변경 — `ctl.py`, `ctlspan.py`, `dsr_telemetry.py`, `feed.py`, `runinfo.py`,
  `ctl_check.py`(새), `tests/ctl_spans_test.py`, `tests/ctl_writer_test.py`, `tests/runinfo_test.py`, `tests/ctl_span_obs_test.py`(새),
  `docs/ctl-linkage.md`, `docs/ctl-experience-data.md`·`.sha256`(새), `docs/roadmap/problems.md`, `docs/roadmap/plan.md`,
  `ROADMAP.md`, `data/samples/` 세 실행. `.claude/launch.json`은 이 작업 전부터 바뀌어 있던 사용자 변경이다.
- 임시 폴더의 분석 스크립트는 `ctl_check.py`(`--vs-scene` 포함)로 옮겨져 있어 따로 보존하지 않았다.

## G. 종료 결론

경험 데이터 수집·연결 구조를 구현했고, 오프라인 테스트와 제한된 실제 실행(3회)에서 기록이 끝까지 쓰이고 연결이 맞는 것을
확인했다. 향후 쓸 모델과 용도가 정해지면 E의 부족분 중 필요한 것만 보완한다. 이 문서는 다음 작업을 정하지 않는다.
