# 설계안: 사람이 확인한 장면을 테스트 기대값으로 (2026-10-09, [cloud])

`docs/analysis-2026-10-09.md` §3 제안 4의 설계. **아직 결정 아님** — §7의 질문에 [MoKa]가 답한 뒤 단계 1부터.
관련: P-31, P-33, P-34, 1-j("`duel_golden_test`는 규칙이 스스로 낸 결과가 기준"), LAYA.md(라벨 파일럿·경계 장면), ROADMAP 2 "Ramp 24-scene labels"·"300-label eval set".

한 줄 요약: `duel_golden_test`는 "**바뀌었나**"만 본다(기준 = 규칙 자신). 이 설계는 "**맞나**"를 보는 두 번째 테스트 `duel_expect_test`를
더한다: 장면 하나 = 상황 + [MoKa]가 허용/금지한 전술 + 출처. 이미 있는 사람 라벨 87개로 오늘 재 보니 **장면 재구성이 봇 자신의 선택과
60 %만 같아서**(§2-b) 라벨을 그대로 옮기면 안 되고, **휘청(3500) 장면 45개에서 [MoKa]의 답이 반반으로 갈려** 지금 특징으로는 규칙을
못 세운다(§2-c, P-33). 그래서: 기대값은 (1) 재구성이 봇과 같은 장면 (2) [MoKa]의 말로 정한 규칙 (3) 앞으로는 **봇의 실제 입력을 그대로 저장한 장면**에서 만든다.

---

## 1. 지금 있는 것

| 무엇 | 기준 | 한계 |
|---|---|---|
| `tests/duel_golden_test.py` | 40,320 상황의 판단 기록 (`--record`로 다시 찍음) | 규칙이 틀려도 통과. 바뀐 이유는 커밋 메시지뿐 |
| 손으로 쓴 규칙 테스트 (`duel_after_swing_test`, `axe_hollow_test`, `duel_third_test` …) | [MoKa] 지시를 테스트로 | 형식·출처 표기가 제각각, 지시 문장과 연결이 커밋·ROADMAP에만 |
| 사람 라벨 `data/labels/{pilot,ramp,boundary}_labels.jsonl` (LAYA.md) | [MoKa]의 허용·금지·최선 전술 | 봇 판단과 연결 안 됨 — Laya 평가에만 씀 |
| `laya_shadow.RULE_TACTIC` / `policy_tactic` | 규칙 이름 → 전술 9개 (`attack`·`guard`·`approach`·`hold_position`·`reposition`·`retreat`·`heal`·`evade`·`backstab`) | — (이 설계가 그대로 씀) |

## 2. 오늘 확인한 사실 (재현: `python experiments/label_probe.py [--basic] [--json]`)

### a. 쓸 수 있는 라벨 87개 — 성격이 다르다
| 묶음 | 수 | 방식 | 확신 | 비고 |
|---|---|---|---|---|
| boundary | 54 | **blind** (봇 행동 안 보고) | high 35 · mid 19 | 봇 자신의 틱 특징(`laya_shadow` 기록) — 애니 번호 대신 상태 범주만 |
| ramp | 24 | **review_bot** (봇 행동을 미리 채워 보여 줌) | high 24 | **24개 모두 미리 채운 값 그대로** → 봇을 따라간 라벨일 수 있음 |
| pilot | 9 | blind | — | **금지 전술**이 있는 유일한 묶음 (6개) |
(87 = human_verified · unsure 아님 · 허용 전술 있음 · 확신 low 아님. unsure·low 7개 제외.)

### b. 장면을 가짜 세계로 다시 만들어 오늘의 `duel()`에 넣으면
재구성: 적 npc·애니(boundary는 상태 → 대표 애니)·거리·높이·HP·SP·내 방향 오차·적 방향·옆 적 하나·스타일·무기, 반사는 "적이 4 m 안에서 휘두르면 막음"으로 흉내.
NavMesh·arena·에스트·휘두른 지 몇 초·옆 적 둘 이상은 재구성 못 함.

| | [MoKa] 허용 안에 듦 |
|---|---|
| **봇이 그때 실제로 한 것** (장면 기록) | **69/82 (84 %)** |
| 오늘 규칙, 재구성 (기본 설정) | 27/87 (31 %) — 뒤잡기가 켜져 있어 휘두르는 망자에게 `backstab` |
| 오늘 규칙, 재구성 (`--basic`: 뒤잡기·강공 끔) | 49/87 (56 %) |
| 재구성한 선택 = 봇이 그때 한 선택 | **49/82 (60 %)** |

- 장면 기록엔 **그 실행이 `--basic`이었는지가 없다** — 설정에 따라 31 % ↔ 56 %. = 제안 5(실행 설정 기록)가 이 설계의 전제.
- 재구성이 봇과 40 % 다르다 = 재구성으로 "오늘 규칙이 틀렸다"고 말할 수 없다 (P-34: 레이더로 다시 만든 특징도 85~94 %만 일치).

### c. 휘청(3500) 장면 45개 — [MoKa]의 답이 반반
- guard만 허용 22 · attack 허용 21 (나머지 2). **거리로도 안 갈림** (guard만: 0.8~2.1 m, attack 허용: 0.9~2.1 m).
- 봇이 실제로 [MoKa]와 다르게 한 13개 중 **9개가 휘청 장면**(대부분 봇 attack ↔ [MoKa] guard). P-33("막은 뒤 휘청에 바로 반격 — 막았어야")과 같은 이야기.
- 그런데 10-06 [MoKa] 지시는 "상대가 휘두르는 애니 끝나면 **무조건 공격**"(`rule_after_swing`). 라벨(10-01)과 지시(10-06)가 겉으로는 부딪힌다.
- → 지금 장면 특징(애니·거리·SP·옆 적)만으로는 [MoKa]의 판단을 재현할 수 없다. 빠진 것으로 보이는 것: 휘청이 **내 막기에 튕겨서인지**,
  휘청 시작 뒤 몇 초인지, 적 종류별 휘청 길이(P-33 "[win] 적별 휘청 애니 확인" 대기 중). 이건 [MoKa]가 말로 정해야 테스트가 된다.

## 3. 설계

### 3.1 기대값 파일 `tests/expect/duel.jsonl` — 한 줄 = 장면 하나
```json
{"id": "p33-a1-26", "source": {"kind": "label|moka|problem", "ref": "boundary:77f59d63f1 | P-33 | 10-06 MoKa '끝나면 무조건 공격'",
  "labeler": "MoKa", "date": "2026-10-01", "mode": "blind"},
 "situation": {"foe": 254001, "anim": 3500, "dist": 0.9, "dy": 0.0, "foe_hp": 1.0, "my_sp": 0.75, "facing_err": 5, "foe_facing": 0,
               "after_block": true, "others": [], "style": "guard", "weapon": "battle_axe", "flags": {"BACKSTAB": false, "HEAVY": false},
               "reflex": "auto"},
 "expect": {"acceptable": ["guard"], "forbidden": ["attack"]},
 "status": "pass | known_fail:P-33 | needs_snapshot",
 "why": "막은 직후 휘청 — [MoKa] 재검토 라벨은 guard만"}
```
- `situation`은 사람이 읽을 수 있는 몇 개 값 — 가짜 세계 만드는 코드 하나(`tests/scene_world.py`, golden의 `run()`과 `label_probe`에서 뽑음)가 해석.
- 나중에 snapshot 장면(3.3)은 `situation` 대신 `"snapshot": "<파일>#<틱>"`.
- `status`: `pass` = 지금 통과해야 함 · `known_fail:P-n` = 결정 대기로 지금은 실패가 맞음(통과하기 시작하면 테스트가 "상태 바꿀 것"으로 실패 —
  고친 줄 모르고 지나가지 않게) · `needs_snapshot` = 재구성을 못 믿음, 실행 안 함(목록만).

### 3.2 테스트 `tests/duel_expect_test.py`
- 장면마다 `duel()`을 몇 틱 돌려 **방향 돌기 뒤 첫 전술**(`laya_shadow.policy_tactic`)이 `acceptable` 안이고 `forbidden` 밖인지.
- 출력: 출처별 통과/known_fail/needs_snapshot 수, 실패한 장면은 상황 한 줄 + 출처 + 고른 규칙.
- `pytest`에 자동 포함(`tests/<name>_test.py`). golden을 다시 찍을 때 이 테스트가 깨지면 "의도한 변경이 [MoKa] 판단과 부딪힘" — 커밋 전에 보임.

### 3.3 앞으로의 장면: 봇의 실제 입력을 그대로 (`--ctl`)
- 재구성 60 %(§2-b)의 근본 해결은 **결정 틱의 입력 자체를 저장**하는 것: `ctl`의 `dec.rule`(이미 있음)에 그 틱의 `T`(스냅숏 중 15 m 안 캐릭터·
  내 상태)와 `F`의 판단용 값(무기·스타일·arena·`sep_n`·`edge_until`·직전 애니 시각 등 `duel`이 읽는 것)을 붙임 — `--ctl-scenes`일 때만,
  `FOLD_RULES` 아닌 규칙(공격·뒤잡기·에스트·발차기) + 휘청·쓰러짐 틱만.
- 재생기 `scene_replay`: 저장한 `T`·`F`를 그대로 넣고 `RULES`를 돌림 — 가짜 세계 재구성 없음. 첫 확인: 저장한 실행의 결정이 재생에서 **100 % 같을 것**.
- 라벨 페이지(`label_pilot.py serve`)는 이 장면을 그대로 보여 줌 → [MoKa] 라벨이 곧바로 `snapshot` 기대값.

### 3.4 [MoKa]의 말 → 장면 (지시 하나에 장면 몇 개)
지시가 나올 때마다 [cloud]가 그 지시가 말하는 상황 2~5개를 `source.kind = "moka"`로 쓰고 `why`에 문장 그대로. 지금 있는 지시에서 먼저:

| 지시 | 장면 |
|---|---|
| 10-06 "휘두르는 애니 끝나면 무조건 공격" (`rule_after_swing`) | 휘두름 끝 0.3 s, 45° 안, 닿는 거리 → attack · 옆 적이 휘두르는 중 → attack 금지 |
| 10-01 "둘 이상이면 뒤잡기 안 함" (`NO_BACKSTAB_N`) | 망자 둘 4 m 안, 목표 등 돌림 → backstab 금지 |
| 10-01 "타겟 설정되면 방향 정렬 최우선" (`rule_face_first`) | 몸 50° 벗어남, 6 m → 공격·접근 금지(돌기) |
| 10-06 255001 = 방패 창 (`foes.SHIELD`, 3004 windup) | 255001 3004 1.0 s 안 1.5 m → attack(발차기) · 1.5 s 뒤 → guard |
| P-33 (결정 대기) | 막은 직후 휘청 0.9 m → `known_fail:P-33`, 허용 guard |
| P-31 (결정 대기) | 목표 한 방 남음, 3.0 m, 뒤잡기 기회 → `known_fail:P-31`, attack 금지 |

손으로 쓴 규칙 테스트(`duel_after_swing_test` 등)는 그대로 둔다 — 같은 지시를 이 파일에도 한 줄씩 적어 출처를 한곳에 모으는 것.

### 3.5 라벨 → 장면 규칙
- **blind 라벨**(boundary·pilot): 재구성 선택 = 봇이 그때 한 선택인 장면만 `pass`/`known_fail`로(재구성을 믿을 근거가 있는 장면), 나머지는 `needs_snapshot`.
- **review_bot 라벨**(ramp 24): 봇이 미리 채운 값을 그대로 둔 것이라 **봇이 옳다는 근거로 쓰지 않음** — 회귀 방지용 `pass`로만, 규칙을 바꿀 근거로는 안 씀.
- 확신 low·unsure·"정보 부족"은 넣지 않음. 휘청 장면(§2-c)은 [MoKa] 규칙(§7-②)이 정해질 때까지 `needs_snapshot`.

## 4. 코드 배치
- `tests/scene_world.py`(새): `situation` → 가짜 세계·Mv·반사·플래그. golden `run()`의 세계 만들기 부분을 여기로 옮기고 golden은 그걸 부름 (golden 결과 그대로여야 함).
- `tests/expect/duel.jsonl`(새), `tests/duel_expect_test.py`(새).
- `tools`: `python label_pilot.py expect` — 라벨 → 장면 초안(3.5 규칙 적용)을 출력, 사람이 골라 붙임 (자동으로 파일에 쓰지 않음).
- 3.3: `souls/duel.py` `_RuleRec`에 장면 저장(`--ctl-scenes`, 기록만 — 판단은 아무것도 다시 안 읽음, P1-C와 같은 원칙), `scene_replay.py`(새, 루트).

## 5. 확인 계획
1. golden이 `scene_world`로 옮긴 뒤에도 40,320 상황 그대로.
2. 첫 기대값 묶음(§3.4 지시 장면 + §3.5로 고른 라벨 장면)이 `pass`는 전부 통과, `known_fail`은 전부 실패.
3. 일부러 규칙 하나를 망가뜨려(예: `rule_face_first` 끔, `NO_BACKSTAB_N` 99) 이 테스트가 잡는지 — golden만이 아니라.
4. 3.3: [win] `--ctl-scenes`로 구간 하나 → 재생 일치 100 %, 파일 크기(실행당 MB 이하 목표).

## 6. 단계
1. [cloud] `scene_world.py` 분리(golden 그대로) + `duel_expect_test` + §3.4 지시 장면 (~15개). `known_fail`: P-31, P-33.
2. [cloud] `label_pilot.py expect` → blind 라벨 중 재구성 = 봇 선택인 장면 초안 → [MoKa] 훑어봄(10분) → 파일에 붙임.
3. [cloud] 3.3 장면 저장·재생 (`--ctl-scenes`, 기록만).
4. [win] `--ctl-scenes`로 경사로·위 마을 한 번씩 → [MoKa] 라벨 페이지에서 30~50개 (LAYA.md의 300 라벨 계획을 이 형식으로).
5. 앞으로 [MoKa] 지시마다: 규칙 바꾸는 커밋에 장면 2~5개를 같이 (CLAUDE.md "Code and tests"에 한 줄 추가 제안).

## 7. [MoKa] 결정할 것
1. 기대값 파일을 테스트에 넣는 것 — `known_fail`(결정 대기 중인 문제는 실패가 맞음으로 표시)이 있어도 되는지.
2. **휘청(3500) 뒤에 언제 치고 언제 막는지** — 라벨 45개가 반반(§2-c)이고 10-06 "끝나면 무조건 공격"과도 부딪힘. 예: "내 막기에 튕긴 휘청은
   치기(=after_swing), 맞고 비틀거린 휘청은 …" 처럼 말로 정해 주면 장면으로 옮김. P-33과 같은 결정.
3. ramp 24개(봇 행동을 미리 채워 보여 준 라벨)를 회귀 방지용으로만 쓰는 것.
4. 3.3 장면 저장 — 기록 파일이 커짐(공격·휘청 틱만, 실행당 수 MB 예상). `--ctl-scenes`를 기본으로 켤지.

## 8. 한계
- 재구성은 **한 순간**이다 — "막은 직후", "휘두른 지 0.8 s" 같은 앞뒤 맥락은 `situation`에 값으로 넣은 만큼만 들어간다(3.3이 근본 해결).
- 전술 9개로 접으면 "어떤 공격(약공·발차기·강공)인지"는 안 본다. 필요하면 `expect`에 `"attack_kind"`를 나중에 더함.
- [MoKa] 라벨도 화면·확대 화면에 따라 바뀐 적이 있다(P-33 1차 저화질 라벨은 attack 허용 → 재검토 guard만). 장면마다 `source.date`·`mode`를 남겨 다시 볼 수 있게.
