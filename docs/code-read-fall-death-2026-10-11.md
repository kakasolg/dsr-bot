# 코드 읽기: 싸움 규칙 순서 · 낙사 · 사망 기록 (2026-10-11, [win])

MoKa가 "코드를 수정하지 말고 읽기만 해서, 추측 없이 코드에서 확인한 것만" 답하라고 한 질문 네 개와, 그 뒤에 한
관측 전용 변경(`death_seen` 이벤트) 하나를 정리한다. 분석과 사실 확인이지 결정이 아니다.
줄 번호는 이 문서를 커밋한 시점 기준 (`souls/watch.py`의 Blood 부분은 `death_seen` 추가로 원래보다 2줄 밀림).

---

## 1. 싸움 규칙은 어떤 순서로 평가되나

루프: `souls/duel.py:1715` `for rule in RULES:` — 순서는 `RULES` 목록(`duel.py:1630-1633`) 그대로.

| # | 규칙 | 파일:줄 | 정하는 것 | 맞으면 바로 끝나나 |
|---|---|---|---|---|
| 1 | `rule_shot` | duel.py:803 | 종료 ('shot') | 예 |
| 2 | `rule_separate` | duel.py:835 | 이동 (떼어놓기) | 예 — 단 `no_spot`이면 이미 움직인 뒤 None (다음 규칙으로) |
| 3 | `rule_finish_first` | duel.py:850 | 공격 | 예 |
| 4 | `prep_reflex` | duel.py:891 | 준비 (`T.age`, `T.near45`) | 아니오 (항상 None) |
| 5 | `rule_footing` | duel.py:953 | 이동 (발밑) | 예 — `FOOTING` 켜졌을 때만 |
| 6 | `rule_after_swing` | duel.py:1003 | 공격 | 예 |
| 7 | `rule_face_first` | duel.py:868 | 방향 | 예 |
| 8 | `rule_early_kick` | duel.py:1052 | 공격 (발차기) | `act` 모드만 예, `shadow`는 기록만 하고 None |
| 9 | `rule_late_windup_block` | duel.py:1074 | 막기 | 예 |
| 10 | `prep_linger` | duel.py:1085 | 준비 (`T.a` 고침, `T.room`, `T.wall`) | 아니오 |
| 11 | `rule_hit_first` | duel.py:1106 | 공격 | 예 |
| 12 | `rule_backstab_swing` | duel.py:1183 | 공격 (뒤잡기) | 예 |
| 13 | `rule_reflex` | duel.py:1192 | 막기 (반사) | 예 |
| 14 | `rule_lure` | duel.py:1222 | 이동 (끌어오기) | 예 — 경로 없으면 None (`F.pulled`는 이미 True) |
| 15 | `rule_edge` | duel.py:1235 | 이동/막기 | 예 — `FOOTING` 꺼졌을 때만 |
| 16 | `rule_estus` | duel.py:1252 | 회복 | 예 |
| 17 | `rule_stagger_punish` | duel.py:1271 | 공격 | 예 |
| 18 | `rule_evade` | duel.py:1294 | 회피 | 예 |
| 19 | `rule_block` | duel.py:1318 | 막기 | 예 |
| 20 | `rule_downed` | duel.py:1347 | 막기 (대기) | 예 |
| 21 | `prep_backstab_chance` | duel.py:1358 | 준비 | 아니오 |
| 22 | `rule_wait_far` | duel.py:1380 | 대기 | 예 |
| 23 | `rule_approach` | duel.py:1409 | 이동 | 예 |
| 24 | `rule_finish` | duel.py:1433 | 공격 | 예 |
| 25 | `rule_stamina` | duel.py:1445 | 회복 (SP) | 예 |
| 26 | `prep_face` | duel.py:1456 | 방향 | 도는 중이면 CONT, 다 돌면 None + `T.s/T.c/T.a` 바꿈 |
| 27 | `rule_backstab` | duel.py:1474 | 공격 | 예 — 안 맞으면 `F.circle_n = 0` |
| 28 | `rule_attack` | duel.py:1612 | 공격 | 예 (항상 결과를 냄, 마지막) |

- 목록은 28개. `rule_*` 24개 + `prep_*` 4개. `prep_*` 중 3개는 계산만 하고 항상 None, `prep_face`만 행동(돌기)도 한다
  → 행동을 고르는 것은 25개, `rule_footing`/`rule_edge`는 `FOOTING`으로 한쪽만 동작하므로 한 실행에서는 24개.
  `docs/review-v2-2026-10-11.md`는 "27개"로 적혀 있다.
- None 아닌 값 → `break`(duel.py:1738) 또는 `return`(1737). 그 틱의 뒤 규칙은 평가되지 않는다.
- **None을 돌려준 규칙도 이미 입력을 넣었을 수 있다.** 조건식 안의 `F.mv.face()`(moves.py:165)는 각도가 벗어나면 스틱을
  움직이고 False를 돌려준다 (finish_first, hit_first, stagger_punish, evade, finish, early_kick). `rule_separate`의
  `no_spot`, `rule_lure`의 경로 없음도 마찬가지.
- 기록(`_RuleRec.add`)은 None 아닌 규칙만 남긴다 → None을 내며 움직인 것은 로그로 확인할 수 없다.
- 루프 앞의 `_sense`(duel.py:1700)가 CONT / 결과를 내면 그 틱엔 규칙이 하나도 평가되지 않는다.

## 2. 낙사는 어디서 어떻게 다뤄지나

| 위치 | 함수 | 감지 (값/조건) | 하는 일 | 다른 것보다 먼저? |
|---|---|---|---|---|
| watch.py:77 | `Escape._run` (50 Hz 별도 스레드) | 애니 1550·121500 또는 0.4 s에 2.5 m 넘게 내려감 → 발밑 바닥이 8 m 넘게 아래, 또는 바닥을 모르면 0.8 s에 4 m 넘게. 쿨다운 4 s | `fire()`: `Pad.freeze` → 퀵 종료(byte 먼저, 안 되면 menu) → 다시 불러오기 → 가까운 바닥으로 | 예 (freeze 중 다른 스레드 입력은 `_NULL_PAD`, control.py:216). `--no-quit`이면 로그만 |
| watch.py:110 | `Escape._back_to_mesh` | 낙사 퀵 종료 직후 | 8 m 안 가장 가까운 걸을 수 있는 바닥으로 최대 2.5 s | 예 (freeze 안) |
| watch.py:140 | `Escape._ledge` | 떨어지는 중 아님 + 발밑 바닥 없음/3 m 아래 + 안전 자리보다 0.6 m 넘게 내려옴 + 1 s에 0.5 m 미만 이동 | 0.35 s 동안 안전 자리 쪽으로 스틱 | 예 (단 퀵 종료 중이면 양보, `freeze(take=False)`) |
| duel.py:953 | `rule_footing` | 발밑 바닥 없음, 또는 footing < 0.6 + 3 m 안 적이 밀면 1.5 m 뒤 바닥 없음 | 방패 든 채 한 걸음 | 아니오 (규칙 5번째, `FOOTING` 켜졌을 때만) |
| duel.py:1235 | `rule_edge` | `nav.footing` < 0.6 | 평지 자리로, 없으면 방패+마주보기 | 아니오 (15번째, `FOOTING` 꺼졌을 때만) |
| duel.py:193, 215, 243 | `_room_behind` / `_circle_floor` / `_back_to_safe` | 뒤잡기로 도는 길의 같은 높이 바닥 | 뒤잡기 안 함 / `"edge"`로 멈춤 / 시작 자리로 돌아감 | 아니오 (뒤잡기 안에서만) |
| duel.py:1263, 1328, 1371, 1479 | estus / block / backstab_chance / backstab 조건식 | `nav.ground_ahead` (2.2 / 0.8 / 1.0 / 1.0 m) | 그 동작을 안 함 | 아니오 |
| reflex.py:139, 169 | `safe_turn`, `dodge` | 0.8 m 앞, 2.6 m 뒤, 2.2 m 앞 바닥 | 안 돌기 / 백스텝 대신 버팀 (옆 구르기는 제거됨) | 아니오 (규칙 13번째 안) |
| moves.py:338, 370 | `backstep_attack` / `combo` | 뒤·앞 바닥 거리 | `skipped = "뒤에 바닥 없음"` 등 | 불확실 — 동작 직전 검사라 부르는 쪽 순서에 달림 |
| nav.py:118–196 | `footing` / `ground_ahead` / `safe_heading` / `footing_state` / `safe_back` | NavMesh `floor_at`으로 바닥·큰 낙차 | 판정 함수 (직접 행동 없음) | 해당 없음 |
| nav.py:491–625 | `follow` 모드별 분기 | 막힘 탈출 양옆, hold footing, circle/backoff/probe/creep/face/engage 각각 | 바닥 없는 쪽으론 스틱 안 넣음 / 멈춤 / 돌림, 양옆 낭떠러지면 `"stuck"` | 아니오 (모드마다 따로, 공통 우선순위 없음) |
| nav.py:294, 317 | `brake_points` / `braked` | 모퉁이를 3 m 지나치면 바닥 없음 + 낙차 가장자리 3.5 m 안 | 그 점 3.5 m 앞부터 sprint → walk | 아니오 (경로에서 정해짐) |
| souls/escape.py:148 | `pick` | 후보 자리 `drop_dist < DROP_R` | 후보 제외 (`"drop"`) | 아니오 |
| souls/field.py:510, 566 | 벽 자리 / `_gap` | `drop_dist < WALL_SPOT_DROP` / 2.5 m 앞 바닥 | 후보 제외 | 아니오 |
| souls/missions.py:636 | `_roll_dir` (구역 8) | `ROLL_M` 앞 바닥 | 바닥 있는 쪽으로만 구름 | 아니오 |

- 낙사 처리는 `rule_footing` / `rule_edge` 두 곳만이 아니다: watch.py(감지·퀵 종료), nav.py(걷기), reflex.py, moves.py,
  escape.py, field.py, missions.py, duel.py 뒤잡기. asylum.py:203·508·553은 일부 구간에서 감시를 일부러 끈다.
  run.py:248 — 감시는 `--ground`여도 기본 NavMesh.
- **먼저 실행되는 것은 `Escape`(떨어지는 중·미끄러지는 중) 하나뿐**이고, 예방 검사는 동작마다 따로 하며 공통 우선순위가 없다.
- `Escape.last_fall_pos`(watch.py:260)는 "위 층이 가장자리에서 물러나도록" 저장하지만, tests/experiments/legacy 밖에서 읽는 곳이 없다.

**낙사 원인이 기록에 남나?** 일부만.
- 퀵 종료가 실행되면 예: `⚠ 퀵 종료: 낙사 (…) @ [x,y,z]`(watch.py:230), `⚠ 퀵 종료 결과: {'why': '낙사 …', 'kind': 'fall', …}`(269),
  `.jsonl`의 `escape` 이벤트(`kind: "fall"`), `risk_report`의 `강종×n(fall)`. 미끄러짐은 `⤺ 턱 위 미끄러짐` + `ledge` 이벤트.
- **떨어져 죽으면 아니오**: `✝ 죽음 — 핏자국 …`(watch.py:327)만, 원인 없음. `risk_report`도 "사망"만 (risk_report.py:93 주석: 낙사는 싸움 밖이라 `me_dead`도 없음).
- 감지 안 되는 경우: `--no-quit`이면 `(퀵 종료 꺼짐) 낙사 …` 로그만(이벤트 없음). 발밑 바닥을 아는데 8 m 이하로 떨어지면 아무 기록도 없음.

## 3. 사망을 감지하는 지점은 죽기 직전 상태를 알 수 있나

먼저: `✝ 죽음` 로그(watch.py:327)는 **부활한 뒤**(HP > 0으로 돌아오고 소울이 줄어든 걸 확인한 때) 찍힌다.
죽은 순간을 보는 곳은 watch.py:339–340 (`pending = dict(last)`). `Blood`는 `Blood(log=log)`로만 만들어져(run.py:259)
`Escape`·`BlackBox`·이벤트 함수 중 어느 것도 받지 않는다.

| 정보 | Blood에서 지금 읽을 수 있나 | 어디서 | 과거 값 보관 |
|---|---|---|---|
| 내 위치 | 예 | `last["pos"]` (watch.py:338, 땅 위·살아 있는 마지막 프레임) | Blood는 1개만. `BlackBox.buf`는 ~10.5 s (접근 못 함) |
| 최근 높이 변화 | 아니오 | `Escape._y` (watch.py:59, 40개 ≈ 0.8 s), `BlackBox.buf`의 `pos[1]` | 예 (메모리만). 327행 시점엔 부활 후 값에 밀렸을 수 있음 — 불확실 |
| 발밑 바닥 높이 | 아니오 | `Escape.floor_drop(p)` (watch.py:65) — 그때 계산 | 아니오 |
| 마지막 안전 자리 | 아니오 | `Escape.safe_pos` (watch.py:52, 147) | 아니오 (1개를 덮어씀) |
| 내 애니 | 현재 값만 | `p.anim` (땅 판정에만), `BlackBox` 프레임 `"anim"` | Blood 아니오, BlackBox 예 |
| 직전에 이긴 싸움 규칙 | 아니오 | `Fight.res.rules`는 횟수 사전이고 `Fight`는 `duel()` 지역 객체. `--ctl`일 때만 `.ctl.jsonl`의 `dec.rule` | 아니오 ("마지막 규칙" 변수 없음) |
| 적 거리 | 현재 값만 | 스냅샷 `s.hostile()`(안 씀), `BlackBox` 프레임 `foes[].d/dy`, `vital`의 `near` | BlackBox 예, `vital`은 파일에 0.5 s마다 |
| 체력 변화 | 현재 값만 | `Escape._hp`(60개), `BlackBox` 프레임 `"hp"`, `vital` 이벤트 | 예 (`vital` 파일). 큰 피격 묶음은 `.hits.jsonl`에 앞 8 s — 죽을 때 묶음이 언제 닫히는지는 불확실 |

- 이벤트 파일 형식 (run.py:59–65): 한 줄 JSON `{"t": 실행 시작부터 초, "ev": 이름, "zone": (있으면), ...}`.
  **사망 전용 이벤트는 없다** — `duel` 이벤트의 `result: "me_dead"`(field.py:769: tag, npc, result, secs, dealt, taken, fight —
  싸움 루프 안에서 HP ≤ 0을 본 경우만, duel.py:672), 실행 끝 `result`(run.py:372). `data/bloodstain.json`은 핏자국 파일.

## 4. 계획 검토: Blood에 BlackBox를 넘겨 죽기 전 5 s를 남기기 (아직 안 함)

| 단계 | 가능? | 막는 것 / 주의 |
|---|---|---|
| run.py:259에서 BlackBox·`Log.event`를 넘김 | 예 (순서 바꾸면) | BlackBox는 그 뒤 261행에서 생성. `Blood.__init__`은 `log`만 받음. 피드가 없으면(`BOT_FEED=0`) BlackBox `buf`는 비어 있음 |
| 339행에서 `buf` 최근 5 s 복사 | 불확실 | 이 조건은 HP None에도 들어감. 소울·인간성이 모두 0이면 조건 자체에 안 들어감. `buf`는 잠금 없이 피드 스레드가 바꿈. "최근 5 s"는 지금 시각이 아니라 `buf` 마지막 프레임의 `t` 기준이어야 함 (로딩 중 프레임이 안 쌓임) |
| 327행(부활 뒤)에서 `death` 이벤트 | 예 | 소울·인간성이 줄었을 때만 실행. 5 s치 프레임(~58 Hz)을 `.jsonl` 한 줄에 넣으면 매우 큼 → `.hits.jsonl`처럼 다른 파일이 맞을 수 있음 |

- 생성 순서: Blood(259) → BlackBox(261). 종료: `blood.stop()`(413) → `bbox.stop()`(414). run.py는 끝낼 때 부활을 기다린다(405–407).
- 스레드: `buf`는 일반 `deque`, 잠금 없음. 피드 스레드가 `append`/`popleft`. 다른 스레드에서 순회는 코드상 보장 없음 → 잠금이나 피드 스레드 쪽 복사가 필요.
- 겹침: BlackBox는 `max_hp`가 없으면 프레임을 버리고(blackbox.py:93–95), Blood 339행은 HP None/≤ 0에서 실행 → 로딩 중엔 둘이 겹칠 수 있다.
  버리는 동안엔 오래된 프레임도 안 지워져(지우기는 추가할 때만, 99행) 죽기 직전 프레임은 프레임이 다시 들어올 때까지 남는다.
  죽는 순간 게임이 HP 0과 `max_hp`를 어떻게 주는지는 코드로 확인 불가.

## 5. 한 변경: `death_seen` 이벤트 (관측만, 동작 그대로)

사망 판정이 얼마나 맞는지 재기 위해 `souls/watch.py` `Blood._run`에 기록 한 줄을 넣었다.

- `pending = dict(last)`가 만들어지는 바로 그 조건 안에서 `.jsonl`에 `death_seen` 이벤트:
  `hp`(None이면 null), `max_hp`, `anim`, `pos`. 시각은 `Log.event`가 붙이는 `t`(다른 이벤트와 같은 형식) —
  `t`를 따로 넘기면 덮어써져 `risk_report`의 판 길이(`max(t)`)가 틀어지므로 넘기지 않았다.
- 한 번 보낸 뒤엔 HP > 0을 다시 볼 때까지 안 보낸다 (`seen_sent`). 기존 구조(`pending is None`)도 같은 걸 막고 있음.
- `log`에 `event`가 없으면(기본 `print`) 아무것도 안 함. 기록 중 예외는 삼킨다 — Blood 스레드가 멈추지 않게.
- `pending` 조건, 소울/인간성 판정, `✝` 로직은 그대로. 기존 테스트 84개 통과.

읽을 때 주의: 이 조건은 HP None(로딩)에도 들어가므로 `hp: null` 줄이 섞일 수 있다 — 같은 판의 `✝ 죽음`과 맞춰 봐야
진짜 사망인지 안다. 소울·인간성이 0이면 `death_seen`도 없다.

## 6. [cloud]에게 (MoKa: "Cloud가 어떻게 분석하는지 보자")

위는 사실 확인뿐이다. 무엇을 바꿀지는 아직 정하지 않았다 (`docs/research-control-priority-2026-10-11.md` §4의 방향 결정 대기).
[cloud]가 이 자료로 어떻게 분석하는지 — 예: 낙사·사망 기록을 어떤 형식으로 남길지, 예방 검사들을 한 곳으로 모을지,
`last_fall_pos`처럼 저장만 하고 안 읽는 값 — 를 relay로 답해 주면 MoKa가 본다.
