# control.Pad freeze — "minimal" 계약 · 합격 테스트 · 최소 패치안

상태: MoKa가 2026-10-27에 minimal 구현과 오프라인 검증을 조건부 승인했다. 같은 날 kick 차단과 tap 검사 위치를 보완했다(§1-1). 게임 실행·commit/push는 승인되지 않았다. 같은 날 control.py에 적용(커밋 안 함): 합격 테스트 패치 전 FAIL 11 → 패치 후 SAFE 14 · VIOLATED known 2(평상시 S5/S6) · FAIL 0, pytest 118 통과, duel golden 변화 없음·expect 상태대로(오프라인만, 게임 실행 없음). pad_freeze_race_test의 known K1–K3은 검사 행 F10–F12로 옮겼다. 근거는 세 가지다.
- 유한 범위 TLA+ 모델의 안전성 검사 결과 (REPORT.md §4)
- 실제 Pad 재현 결과 (REPORT.md §1)
- control.py 커밋 9eb185e를 읽은 것

유한 범위 모델(o·n 호출 3~4회)에서 "both"와 "minimal" 두 변형 모두 freeze 관련 성질을 만족했다: S1, S1b, S2, S3, S4, S5f, 그리고 n의 guard 호출을 뺀 S6/S6_post.
두 변형 모두 남는 위반은 freeze와 무관한 평상시 결함 후보 S5(hold)와 S6(guard 포함)이다(REPORT.md §3, §5).
이 문서는 둘 중 코드 변경이 더 작은 **minimal**을 고른다.
minimal = 비홀더 쓰기 차단 + freeze 진입 때 guard·keep 의도 폐기. 홀더의 neutral은 그대로 둔다.
"both"의 계약 중 다른 부분은 §1 끝에 따로 적었다.

## 1. 계약 (minimal)

말 정의:
- **홀더**: `_frozen_by` 스레드.
- **비홀더**: freeze 중에 홀더가 아닌 모든 스레드.
- **의도 상태**: `_force_until`, `_kept`, `_guard_want`, `_b_since`, `_due`.

| 시점 | guard 의도 (`_force_until` · `_kept` · `_guard_want`) | sprint 의도 (`_b_since`) | 해제 예약 (`_due`) | 장치 | epoch |
|---|---|---|---|---|---|
| **freeze 진입** (take=True, 또는 take=False이고 홀더 없음) | **모두 버림** (`_force_until=0`, `_kept=False`, `_guard_want=False`) — 바뀌는 부분 | 버림 (`None`) — 현재와 같음 | 전부 비움 — 현재와 같음 | reset + 보고 1회 — 현재와 같음 | +1 |
| freeze(take=False) 거절 | 바꾸지 않음 | 바꾸지 않음 | 바꾸지 않음 | 바꾸지 않음 | 그대로 |
| **freeze 중, 비홀더의** `neutral` `keep_guard` `unkeep` `hold`/`guard` `sprint` `tap` `kick` `release_due` | **아무것도 안 바꿈** (lock 안에서 바로 return, `keep_guard`는 False 반환) — 바뀌는 부분 | 안 바꿈 | 안 바꿈 | 안 바꿈 (현재도 `_NullPad`) | **안 올림** — 바뀌는 부분 (현재는 비홀더 neutral도 올림) |
| freeze 중, 비홀더의 `move` `look` `press` `jump_attack` `_r2`/`heavy` | 현재와 같음 (`_NullPad`로 버림). 이 메서드들은 출력과 스틱 기록(`_note_stick`)만 쓰고 의도·예약은 쓰지 않음. `move`/`jump_attack`의 `_note_stick`은 그대로 바뀜 | — | — | 안 바꿈 | — |
| **freeze 중, 홀더의 정상 입력** (`move` `press` `tap` `hold` `sprint` `neutral` …) | 평소 규칙 그대로 | 평소 그대로 | 평소 그대로 | 장치에 들어감 | 평소 그대로 |
| **홀더의 neutral** | `_guard_want=False`. `force_guard`면 LB를 누름 — 코드는 그대로지만 freeze가 의도를 비웠고 비홀더는 다시 못 채우므로, 홀더가 직접 `keep_guard`를 부르지 않는 한 LB를 누르지 않음 | 어린 hold면 B를 유지하고 예약, 아니면 버림 — 그대로. 같은 이유로 홀더 자신의 sprint만 해당 | B 예약만 갱신 | reset | +1 |
| **unfreeze** (홀더만) | 그대로 | 그대로 | 그대로 (홀더가 남긴 A 예약은 남을 수 있음 — §3 A8) | 그대로 | +1 → nav.Mover 다시 맞춤 |
| **unfreeze 뒤** | 새 요청 1번으로 회복: `keep_guard` 1번 → LB, `guard(True)` 1번 → LB | `sprint(True)` 1번 → B (`_b_since`가 None으로 보장되므로) | — | — | — |
| **release_all** (종료 경로) | 현재와 같음: lock을 1 s 기다리고, 홀더와 상관없이 전부 끔. `_due`·`_b_since` 비움. guard 의도는 그대로 | | | | |
| `force_guard = False` 대입 (guardkeep.stop) | lock 없는 속성 대입이라 차단 대상 아님. 그대로 | | | | |

### 1-1. 보완 (MoKa 2026-10-27)

- **kick**은 차단 대상이다.
  - 이전 판에서는 "현재와 같음"으로 분류했는데, 이건 잘못이었다. kick은 lock 블록 안에서 `_due[RB] = now + 0.06`을 쓰는 예약 메서드라서, 비홀더 kick도 freeze 중 예약을 남긴다(S5f와 같은 종류).
  - 처리: lock 블록 첫 줄에서 소유권을 검사하고, 차단되면 `_note_stick`·출력·예약 전에 반환한다. 그래서 비홀더 kick은 스틱 기록도 바꾸지 않는다. 비홀더 `move`가 스틱 기록을 바꾸는 것과 다르다.
  - 호출자: `souls/moves.py:372` `kick`, `:391` `kick_combo`(결정 루프). control.py 안에서 kick을 부르는 메서드는 없다. 두 호출자 모두 kick 뒤 0.12 s 동안 직접 `release_due`를 돈다. 차단된 kick 뒤의 그 `release_due`도 차단되므로 아무 일도 없다.
  - kick은 TLA+ 모델에 없다. 판정 근거는 코드 테스트(A14, A15)뿐이다.
- **tap 검사 위치**: `release_stick`(lock 밖 move(0,0)와 sleep)은 그대로 두고, 그 뒤 기존 lock 블록 첫 줄에서 소유권을 검사한다. 따로 사전 검사를 하지 않고, sleep을 lock 안으로 옮기지 않는다. 계약상 예외는 둘이다.
  - 기존 `release_stick` 대기와 그 안의 스틱 기록(`move(0,0)` → `_note_stick`)은 그대로 둔다. 비홀더 R1 tap은 freeze 중에도 STICK_RELEASE_S까지 기다릴 수 있다.
  - 버튼 출력·의도(`_b_since`)·해제 예약을 허용할지는 **lock 안에서 소유권을 검사하는 그 시점**으로 정한다. 대기 중에 freeze가 시작되면 아무것도 쓰지 않고, 대기 중에 freeze가 풀리면 정상으로 쓴다.
- **호출자 조사** (패치 전, 코드 읽기):
  - `keep_guard`의 반환값을 쓰는 곳은 `souls/guardkeep.py:88`의 `pressed` 카운트와 이벤트 기록뿐이다. guardkeep은 반환값과 상관없이 매 poll마다 다시 부른다(`POLL_S` 0.02 s는 poll 간격 설정값이다).
  - epoch를 읽는 곳은 `nav.Mover._resync`(nav.py:62-68)뿐이다(watch.py:232는 그 동작을 설명하는 주석). 비홀더 neutral이 막혀 epoch를 올리지 않아도 unfreeze가 epoch를 +1 하므로 Mover가 다시 맞춘다. freeze 중 `Mover.stop()`은 그때 epoch를 저장하므로 역시 unfreeze 뒤 다시 맞춘다.
  - 호출자 쪽에 상태를 캐시하는 곳은 Mover(`mode`, `guard_on`, epoch로 다시 맞춤)뿐이다. `souls/reflex.py:138/197`과 `souls/moves.py`의 guard 호출은 매 틱 상태로 다시 계산한다.
  - `_b_since`·`_due`·`_kept`·`_guard_want`를 control.py 밖에서 읽는 봇 코드는 없다. 밖에서 쓰는 곳은 `force_guard = False`(guardkeep.stop) 하나다.
  - 결론: unfreeze 뒤 새 요청을 건너뛰는 경로는 찾지 못했다. freeze 중 요청은 지금도 `_NullPad`로 장치에 없으므로, 패치 뒤 달라지는 점은 "다음 요청이 다시 먹힌다"는 것뿐이다.
  - `release_all`, `close`, `reconnect`는 홀더와 상관없이 lock을 잡고 동작한다(종료·복구 경로). 그대로 둔다.

"both" 변형은 freeze 때 의도를 버리지 않는다. 그 대신 홀더 neutral이 `force_guard`와 어린 `_b_since`를 무시하고 장치·`_b_since`·B 예약을 모두 비운다.
모델 검사 결과는 minimal과 같았다(REPORT.md §4). 다만 "both"에서는 freeze 전 keep_guard 의도가 unfreeze 뒤까지 남는다. 그래서 그 사이 unfreeze 직후 `unkeep`/`hold(LB, False)`의 동작이 의도와 장치 사이 차이에 기대게 된다. minimal을 고른 이유다.

## 2. 수정 후 합격 테스트 (먼저 작성. 패치 전에는 S 줄이 VIOLATED known으로 나와야 함)

모든 테스트는 실제 Pad와 fake vgamepad를 쓴다. 비홀더는 오래 사는 이름 붙은 스레드(Actor)로 돌리고 Event로 순서를 고정한다. 시간은 `control.time`을 Clock으로 바꿔 넣어 조절한다(`repro_new.py`의 도구를 그대로 씀). 판정은 SAFE / VIOLATED (known P-n) / FAIL 셋으로 나누고, VIOLATED는 통과 수에 넣지 않는다.

| id | 모델 성질 | 순서 | 합격 조건 |
|---|---|---|---|
| A1 K1-in | S1 | freeze → guardkeep `keep_guard(t+1)` → 홀더 neutral → press(A) | 메뉴 보고 어디에도 LB 없음. `keep_guard` 반환 False |
| A2 K1-pre | S1 | guardkeep `keep_guard(t+1)` → freeze → 홀더 neutral → press(A) | 메뉴 보고에 LB 없음. freeze 뒤 `force_guard`가 False이고 `_kept`가 False |
| A3 K2 | S1b | freeze → nav `sprint(True)` → 홀더 neutral → press(A) | 메뉴 보고에 B 없음. `_b_since` None |
| A4 K3 | S2 | freeze → 홀더 `tap(A)` → 시계 +1 → nav `release_due` | nav 호출 뒤 `_due`에 A가 남음. 이후 홀더 neutral → A 꺼짐. unfreeze 뒤 nav `release_due` → 장치 변화 없음 |
| A5 스테일 sprint | S4 | freeze → 홀더 neutral → nav `sprint(True)` → unfreeze → nav `sprint(True)` 1번 | B가 장치에 있음. Mover 경유(`repro_new` mover-b 순서)도 같음 |
| A6 인계 | S3 | nudge 스레드 freeze(take=False) → quit-out freeze() → nudge `neutral()` → nudge `unfreeze()` → 홀더 press(A) | 홀더가 끝까지 quit-out. nudge의 neutral이 epoch·의도·장치를 바꾸지 않음. 홀더 입력이 장치에 들어감. 홀더 unfreeze 뒤 owner None |
| A7 회복 | S4 | 각 경우: freeze 중 비홀더가 guard(True)/keep_guard/sprint(True) → unfreeze → 같은 요청 **1번** | LB / LB / B가 장치에 있음 (Mover는 epoch로 다시 맞추므로 1번 부름) |
| A8 오래된 예약 | S5f | (a) 홀더 neutral이 어린 B를 예약 → unfreeze → nav sprint(True) → 시계 +1 → release_due. (b) unfreeze 뒤 nav sprint(True) → sprint(False) (어림, 예약) → sprint(True) → 시계 +1 → release_due. (c) 홀더 tap(A) 예약 → 홀더 press(A) 시작 → nav release_due. (d) `repro_new` S5f 순서: freeze 중 nav tap(Y) → unfreeze → nav hold(Y, True) → 시계 +0.2 → release_due | (a)(b) B 유지. (c) 홀더 press(A) 중 A 유지 (차단으로 nav 호출 무효). (d) freeze 중 tap이 `_due`를 남기지 않음 → Y 유지 |
| A8' 평상시 오래된 예약 (별도 결함, 이 패치 범위 밖) | S5 | 얼지 않은 상태에서 tap(Y) → hold(Y, True) → 시계 +0.2 → release_due | 이 패치 뒤에도 VIOLATED known(새 P 후보). 따로 고칠 때 SAFE가 되어야 함 |
| A9 홀더 정상 입력 | — | F2, F4, F9 그대로 | 현재와 같음 |
| A10 release_all 예외 | — | F8 그대로 + freeze 중 비홀더 release_all | 장치 전부 꺼짐 (차단되지 않음) |
| A11 비홀더 무변화 | S1 근거 | freeze 중 비홀더가 차단 대상 메서드를 하나씩 부름 | 부를 때마다 (`_force_until`, `_kept`, `_guard_want`, `_b_since`, `_due`, `epoch`, 장치 보고 수) 스냅샷이 같음 |
| A12 평상시 회귀 | — | 기존 117개 오프라인 테스트, duel golden/expect, pad_* 테스트 | 모두 통과. 바뀐 줄이 있으면 이유를 적음 |
| A13 tap 대기 중 freeze | (모델 밖) | 비홀더 R1 tap이 `release_stick` sleep 안에 있는 동안 다른 스레드가 freeze → sleep 끝 | 그 tap 뒤 버튼 출력 없음(장치 보고에 비홀더 RB 없음), `_due`에 RB 없음, `_b_since` 그대로 |
| A14 비홀더 kick | (모델 밖) | freeze → 비홀더 `kick` | 장치 보고·`_due`·`_note_stick` 상태·의도·epoch 변화 없음 |
| A15 홀더 kick·평상시 kick | (모델 밖) | 평상시 kick, 그리고 freeze 중 홀더 kick | 같은 보고에 스틱+RB, `_due[RB]` 예약, release_due로 RB 꺼짐 — 지금과 같음 |

기존 `pad_freeze_race_test.py`의 K1/K2/K3 `known()` 줄은 A1/A3/A4로 바꾼다. 패치 전에는 VIOLATED known이고, 패치 뒤에는 SAFE여야 한다.

## 3. 최소 패치안 (적용 안 함)

### 바꿀 메서드 (control.py)
1. **새 helper** `_blocked(self) -> bool`: `self._frozen_by is not None and threading.get_ident() != self._frozen_by`. 반드시 `_lock` 안에서 부른다.
2. **`freeze`** (:231-243): 기존 `_due.clear()`·`_b_since=None` 옆에 `_force_until = 0.0`, `_kept = False`, `_guard_want = False`를 추가한다.
3. 다음 메서드의 lock 블록 맨 앞에 `if self._blocked(): return` 추가 (`keep_guard`는 `return False`):
   - `neutral` (:420): epoch 증가보다 앞에 둔다
   - `keep_guard` (:507)
   - `unkeep` (:518)
   - `hold` (:531, `guard`·`two_hand_right`의 Y도 이것을 거침)
   - `sprint` (:611)
   - `tap` (:462). lock 블록 첫 줄에서 검사한다. `release_stick` (:460-461)은 그대로 둔다(§1-1)
   - `kick` (:598). lock 블록 첫 줄에서 검사한다(§1-1)
   - `release_due` (:486). :484의 lock 밖 확인은 그대로 둔다

### 보존할 동작
- 홀더의 모든 입력이 장치에 들어감 (F2, F4)
- `freeze(take=False)` 거절 (F4)과 take=True로 가져가기 (F5)
- 홀더만 unfreeze 할 수 있음 (F6)
- unfreeze의 epoch +1 → Mover가 다시 맞춤 (F7)
- `release_all`은 홀더와 상관없이 전부 끔 (F8)
- 홀더의 neutral이 오래된 sprint를 정리함 (F9)
- 비홀더의 `move`/`look`/`press`/`jump_attack`/`_r2`는 지금처럼 `_NullPad`로 버림
- 비홀더 R1 tap의 `release_stick` 대기와 스틱 기록 (§1-1)
- 평상시(얼지 않은 때) 동작은 모두 그대로. P-70의 짧은 B 떼기 미루기, keep_guard 우선, guardkeep 동작 포함

### 의도적으로 바꾸는 동작
- freeze 중 비홀더 호출은 의도 상태를 바꾸지 않고 epoch도 올리지 않는다. 지금은 `_NullPad`로 출력만 버리고 상태는 바꾼다.
- freeze 진입 때 freeze 전의 keep_guard·guard 의도를 버린다. unfreeze 뒤 위협이 계속되면 guardkeep이 다음 poll에서 다시 `keep_guard`를 부른다. `POLL_S` 0.02 s는 poll 설정값이지 가드 복구 지연의 상한이 아니다: 실제 지연은 그 poll이 위협을 다시 판단하는 데 쓰는 상태(적 위치·애니 읽기)가 언제 갱신되는지, 스레드 스케줄링, 게임이 입력을 받는 프레임에 달려 있고 측정하지 않았다.
- 비홀더 `keep_guard`는 freeze 중 False를 돌려준다. 지금은 `_NullPad`의 guard_held가 False라서 True를 돌려주는데, 그러면 guardkeep의 `pressed` 카운트가 실제와 다르게 늘었다.

### 남는 위험
1. **호출자 쪽 기록이 어긋남**: 차단된 요청을 호출자는 했다고 여긴다. 조사한 범위에서 상태를 캐시하는 호출자는 Mover뿐이고, Mover는 epoch로 다시 맞춘다(§1-1). 조사는 grep과 읽기로 했고, 테스트로 확인한 것은 Mover(A5, A7)와 guardkeep(A7)뿐이다.
2. **unfreeze 직후 보호 공백**: freeze 전 keep_guard를 버리므로 unfreeze 직후 LB는 guardkeep의 다음 poll까지 없다. quit-out이 끝나면 게임은 메뉴/로딩이라 영향은 작아 보이지만, nudge(`_nudge`, 0.35 s)는 전투 중에도 돌 수 있다. 측정하지 않았다.
3a. **평상시 오래된 예약 (S5, P-94로 추적, 이 패치에서 안 고침)**: `hold(button, True)`와 `press`는 `_due[button]`을 건드리지 않는다. 그래서 같은 버튼의 앞선 `tap` 예약이 새 hold를 뗀다. 실제 겹치는 버튼은 Y다(`two_hand_toggle` :551 tap, `two_hand_right` :630 hold). 지금은 `two_hand_right`가 결정 루프를 막고 있는 동안 `release_due`를 부르는 다른 스레드가 없어서, 실제로 일어나는 경로는 찾지 못했다. 고친다면 `sprint(True)`의 :613처럼 `hold(…, True)`가 `_due.pop(button)`을 하는 방식이다. 이 패치와 따로 결정한다.
3. **평상시 LB 고아 (S6, P-93으로 추적, 이 패치에서 안 고침)**: `keep_guard` 중에 `guard(True)` → `guard(False)`(조기 return) 또는 `neutral`을 거치면, `force_guard`가 끝난 뒤 아무도 원하지 않는 LB가 남는다. freeze와 무관하고 이 패치로도 고쳐지지 않는다.
4. **홀더가 직접 tap**하고 `release_due`를 부르지 않으면 A는 홀더의 neutral까지 남는다. 지금은 그런 홀더가 없다.
5. `_note_stick`(스틱 놓은 시각)은 비홀더 `move`에도 바뀐다. 모델 밖이고, R1 `release_stick` 대기에 영향이 있는지 확인하지 않았다.
6. 비홀더 R1 tap의 차단 전 `release_stick` 대기와 그 안의 스틱 기록(`move(0,0)` → `_note_stick`)은 기존대로 남는 예외다(§1-1). freeze 중에도 기다리고 스틱 기록을 바꾼 뒤, lock 안 검사에서 막힌다.
6a. kick은 TLA+ 모델에 없다. 근거는 코드 테스트뿐이다.
7. 모델 범위 밖: o·n 호출 각 3~4번, 버튼 3개, 스틱 없음, 시간은 순서로만 추상화. 패치 코드를 모델에 다시 대응시키는 일은 패치 뒤에 할 일이다.
