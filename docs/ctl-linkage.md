# ctl linkage — 관측 → 사이클 → 규칙 → 동작 → 패드 출력 (ROADMAP `ctl-linkage`)

[MoKa] 2026-10-30 요청: 어떤 판단 모델을 시험하든 쓸 수 있게, 이미 있는 ctl 기록(`scene`, `dec.rule`, `pad`) 사이에 **연결 고리만** 넣는다.
판단·행동·센서·모델·기록 주기·반경은 바꾸지 않는다. 범위는 `souls/duel.py` `duel()` 루프 한 경로 — 걷기(`Field._walk`, `nav.goto`)는 계측하지 않는다.

켜기: `python run.py <cmd> --ctl-spans` (`--ctl`을 함께 켬; `--ctl-scenes`와 같이 써도 됨). 꺼져 있으면 아래 기록은 하나도 안 나간다.
코드: `ctlspan.py` (ID·기록), `souls/duel.py` (`_duel_loop`), `souls/moves.py` (`_span`, `_watch`의 끝난 이유), `control.py` (`Pad._record`, `_override_rec`).
테스트: `tests/ctl_spans_test.py`.

## 기록

| k | ev | 언제 | 주요 필드 |
|---|---|---|---|
| `span.fight` | start / end | `duel()` 한 번 | `fight_id`, `parent`(이 스레드에 열린 구간 — 지금은 늘 null; 나중에 걷기 → 싸움 중첩용), `ptr` / `result` |
| `span.cycle` | start | while 한 바퀴 시작 (`_sense` 전) | `cycle_id`, `parent` = fight |
| `span.cycle` | end | 그 바퀴 끝 | `kind`(sense_result · sense_cont · rule_cont · rule_result · no_rule · exception · abandoned), `picked`, `rule_id`, `none_n`(None을 돌려준 규칙 호출 수), `none_pad`(그중 패드에 쓴 규칙 이름), `sense_pc`, `src`(feed / direct), `radius`(`SEEK_R`), `snap_t`, `fseq`, `resnap`(prep_face가 새 스냅샷을 넣었나), `my_anim` |
| `span.rule` | — (한 줄) | **고른 규칙만** 반환 뒤 | `rule_id`, `parent` = cycle, `rule`, `enter_pc`, `first_action_pc`, `first_pad_pc`, `ret_pc`, `out` |
| `span.action` | start | `Moves`의 막는 동작 시작 (light · heavy · kick · kick_combo · backstep · backstep_attack · combo · roll_toward · drink · lock_target · look_at) | `action_id`, `parent`(바깥 action, 없으면 cycle), `parent_kind`, `rule_id`(그때 불리던 규칙 — 그 규칙이 None을 돌려주면 span.rule이 없다), `action`, `params`(원시값과 `<인자>_ptr`) |
| `span.action` | end | 끝 | `end`(window 창 만료 · early 조기 종료 · dead 표적 사망 · gone 표적 사라짐 · returned `_watch` 없는 동작 · exception), `exc`, `hit`(Hit 원본 복사: kind · presses · dmg · dead · taken · e_anims · my_anims · skipped · others) 또는 `ret` |
| `pad` / `pad.drop` | — | 기존 기록 + | `cycle_id`, `action_id` — **기록을 쓴 스레드 자신의** 열린 구간만. 기존 필드(th, caller, frz, ep, dup)는 그대로 |
| `pad.override` | — | keep_guard가 LB를 붙잡은 채 `guard(False)` / `neutral()`이 불림 | `m`(guard_off / neutral), `kept`, `caller`, `ep`, ids — 개입 참조용 |

시각은 모두 `pc`(QPC, ns). "선택이 완료된 시각"은 만들지 않는다 — 규칙은 반환해야 골랐는지 알 수 있으므로 `enter_pc ~ first_action_pc / first_pad_pc` **구간**만 남긴다.

## ID 규칙
- 스레드별 (`threading.local`). 전역 변수 하나로 나누지 않는다. CamFollow · GuardKeep · Escape 스레드는 구간을 열지 않으므로 그 스레드의 패드 기록엔 id가 없다 (연결을 확인 못 하면 비워 둠).
- 같은 보고가 이어질 때 접는 `dup` 키에 id를 넣었다 — 다른 action의 같은 보고는 한 줄로 접히지 않는다 (기록 줄 수만 달라짐, 장치 보고는 그대로).
- 큐에 넣는 값은 원시값·새 복사본뿐 (Hit의 목록도 복사).

## 알려진 한계 (이번 작업에서 바꾸지 않음)
- **고른 범위의 연결이다.** None을 돌려주면서 패드에 쓴 규칙의 출력은 규칙 없이 `cycle_id`만 붙는다 ([MoKa] 10-30 "cycle에만 붙이기"):
  `prep_face`(몸이 맞을 때 `pad.move(0, 0)`), 조건 안에서 `face()`를 부르는 `rule_finish_first` · `rule_early_kick` · `rule_hit_first` · `rule_finish`
  (`face()`가 False면 이미 스틱을 민 뒤). 그 규칙 이름은 cycle 끝의 `none_pad`에만 남는다. 0단계 확인: golden 80,640틱 중 prep_face 2,099틱;
  face() 조건 규칙은 golden 상황에선 늘 정면이라 0 — 코드 읽기로만 찾음.
- 규칙 호출 전 출력: `_keep_lock`의 `release_due`와 R3 — cycle_id만.
- scene의 개체 목록은 25 m까지이고, 일부 규칙은 상태가 바뀔 때만 저장된다 (scenes.py, 그대로).
- `dec.rule.snap_age_ms`는 규칙이 **반환한 뒤** 잰 값이라 동작 시간이 들어 있다 (`_RuleRec` 주석). 지우지 않음.
- `src`는 스냅샷의 `fseq` 유무로 정한다: `feed.Feed`는 내주는 프레임마다 `fseq`를 붙이고 직접 읽기는 붙이지 않는다.

## 확인 (2026-10-30)
- 오프라인 (`tests/ctl_spans_test.py`, `tests/duel_golden_test.py`, pytest 전체): 결과는 `docs/roadmap/plan.md` `ctl-linkage` 줄.
- 게임 부하 비교(경사로, 같은 세이브, `--ctl --ctl-scenes` 켬/끔 1회씩)는 [MoKa] 승인 뒤 [win].

## 관측 본문 (`span.obs`, 2026-10-30 2차)
- 목적: 각 싸움 cycle이 `_sense`에서 읽은 스냅샷 본문을 원본 파일만으로 복원 ([MoKa] "각 cycle이 참조한 입력 본문").
- `span.obs` 레코드 (기존 `obs` 종류 = 피드·NoObs 관측 품질 전환 기록과는 별개): `ctlspan.Fight.sensed()`가 `_sense`가 이미 읽은 `T.s`를 복사해 한 줄로 남긴다. 게임 메모리를 더 읽지 않는다.
  cycle 끝 기록의 `obs_id`가 이 레코드를 가리킨다. id는 span id와 같은 카운터라 겹치지 않는다(direct 읽기도).
- 담는 것: Snapshot 필드 전부(t, pc, fseq, cam_yaw, cam_pitch, arm_style, flask_hp, max_flask_hp), 플레이어와
  `s.chars`(SEEK_R 100 m, 같은 순서)의 Chr 필드 전부, `Tick.now`, 목표 ptr(`T.c.ptr`).
- 담지 않는 것: Fight 상태(`F.*`), `Moves.swung`(모든 스레드의 읽기로 채워짐), reflex·care·shadow 상태, 단일 값 읽기
  (grip, lock_target, handle, goods_count), sense 뒤의 스냅샷 재읽기(F.cancel의 far/leash, 규칙, prep_face, 동작의
  `_watch`, nav.goto). 재읽기는 횟수만 센다: `snap_reads_sense` / `snap_reads_after`(`ctlspan.snap_read()`,
  `dsr_telemetry.snapshot`과 피드 캐시 경로에서 호출, cycle이 열린 스레드에서만).
- 복사 시점과 소유권: duel 스레드에서 규칙이 돌기 전에, 새 dict(원시값만)로 복사한다. 레코드만 그 dict를 갖고,
  writer 스레드가 나중에 직렬화한다.
- `python ctl_check.py <run>.ctl.jsonl`: cycle마다 `sense_only` · `partial` · `reads_uncounted` · `dropped` · `missing`
  · `no_obs`. writer `complete`(end 레코드)와 연결 검사와 입력 복원은 따로 보고한다. `sense_only`도 "스냅샷 본문 복원
  가능"까지만이다. 위의 "담지 않는 것"은 들어 있지 않다.
- 확인: `tests/ctl_span_obs_test.py`, `tests/ctl_spans_test.py`(span.obs 켠 golden). 게임 실행 확인 범위와 남은 한계:
  [`ctl-experience-data.md`](ctl-experience-data.md) (2026-10-31 마무리).

## 네 가지 완전성 — 서로 대신하지 않는다 (2026-10-30 3차)
- **writer complete**: end 레코드의 `complete`. writer가 stop 표시까지 갔고 버림·잃음·쓰기 오류가 0이라는 뜻이다. 기록이
  끝났다는 사실만 말하고, 무엇이 기록됐는지는 말하지 않는다.
- **linkage validity**: span의 짝·부모, picked ↔ span.rule, 스레드별 패드 id가 서로 맞는다는 뜻이다(`ctl_check.py`).
- **sense_only**: 보존된 최초 스냅샷 말고는 그 cycle 동안 duel 스레드의 `snapshot()` 호출이 세지지 않았다는 뜻이다.
  아래 셋이 없었다는 뜻은 **아니다**.
  - 다른 스레드가 바꾸는 공유 상태: CamFollow·GuardKeep, 모든 스레드의 읽기로 채워지는 `Moves.swung`.
  - 단일 값 읽기: grip, lock_target, handle, goods_count는 세지 않는다.
  - Fight 기억.
- **full decision replay**: 스냅샷, Fight 기억, 파생 상태, 단일 값 읽기, 그 순간 다른 스레드 상태까지 갖춰 그때 판단을
  그대로 다시 돌리는 것. 지금 어떤 파일도 이것을 갖고 있지 않다. sense_only는 full decision replay가 아니다.
- `ctl_check.py --vs-scene`은 같은 스냅샷 객체에서 나온 두 기록(scene, span.obs)이 같은지 보는, 저장 경로 일관성 검사다.
  독립 센서로 확인한 것이 아니다.
