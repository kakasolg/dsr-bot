# P-91/P-92 minimal 패치 — 게임 확인 계획 (초안, 실행 안 함)

상태: 2026-10-27 작성, 같은 날 MoKa 지적으로 보완. 같은 날 `experiments/freeze_probe_live.py`의 J 변형(quit · nudge)만 만들고, 게임 없이 `tests/freeze_probe_live_test.py`로 확인했다(가짜 vgamepad 위 실제 Pad, 가짜·패치한 quit-out). C 변형은 없다. 게임에서는 아직 실행하지 않았다. 실행하려면 MoKa 승인이 필요하다.
구현에서 계획과 달라진 점: 시험 호출이 기대와 다른 값을 돌려주면(`probe_unsafe`) 소유자 본문 전에 중단한다. 중단 경로(시험 예외·unsafe·join 타임아웃·join 중 Ctrl+C)는 정상 unfreeze 없이 `release_all` → `close`로 끝난다.
패치는 커밋 전이고, 지금까지는 가짜 장치 테스트로만 확인했다.
단계 1·2는 **낙사·전투를 의도적으로 유발하지 않는 제한된 검증**이다. 위험이 없다는 뜻은 아니다. 실제 퀵 종료는 세이브를 쓰고, nudge는 캐릭터를 0.35 s 움직인다.

## 진입점 확인 결과

| 후보 | 무엇을 하나 | 이 검증에 쓸 수 있나 |
|---|---|---|
| `quitout.py drill` | `quit_out`만 부른다. freeze 없음 | 아니오 — freeze 구간이 없다 |
| `run.py` `quit_test` (:562) | 미션 시작 → 적 1마리 처치 → `esc.fire("퀵 종료 실측", "shake")` | 아니오 — 전투가 들어 있고, 시험 호출을 끼울 곳이 없다 |
| `watchdog.py` | `quit_out` 직접 | 아니오 — freeze 없음 |
| `Escape.fire` / `Escape._nudge` (`souls/watch.py`) | freeze → (메뉴 / 스틱) → finally `neutral` → `unfreeze` | 구조는 맞지만 **시험 스레드를 freeze 뒤에 시작하고 unfreeze 전에 끝내는 고리가 없다** |

결론: **기존 진입점은 없다.** 아래 임시 하네스 변경안을 제안하고 멈춘다. 제품 코드와 `NUDGE_S`는 바꾸지 않는다.

## 임시 하네스 변경안 (`experiments/freeze_probe_live.py`, 새 파일 한 개 — 아직 안 만듦)

봇은 `experiments/`를 import하지 않는다(P-15). 하네스는 제품 코드를 바꾸지 않고, **자기가 만든 `Pad` 인스턴스의 `freeze`·`unfreeze`만 감싼다**.

1. 준비
   - `control.focus_game()`, `ctl.start(...)`(= `--ctl`과 같은 `.ctl.jsonl`), `pad = control.Pad()`, `esc = watch.Escape(pad, nms=[], log=…)`.
   - Escape 감시 스레드는 시작하지 않는다(`start()` 안 부름). 하네스가 `fire`·`_nudge`를 직접 부른다.
2. 감싼 `pad.freeze(take)`
   - 진짜 `freeze`가 True를 돌려주고 부른 스레드가 하네스 주 스레드일 때만 시험 스레드를 시작한다.
   - 시작 순서는 freeze 획득 뒤로 정해진다. 시간 대기나 freeze 상태 polling이 아니라, freeze가 돌아온 그 자리에서 시작하기 때문이다.
   - 변형 **J**(기본): 같은 자리에서 시험 스레드를 `join(timeout=2 s)`한 뒤 돌아간다. 시험 호출이 모두 **홀더의 첫 `neutral`과 메뉴 입력 전에** 끝난다. 경합표 K1/K2와 같은 순서다.
   - 변형 **C**: join하지 않고 돌아가, 메뉴 입력과 겹쳐 돈다. 아래 3이 unfreeze 전에 끝남을 보장한다.
3. 감싼 `pad.unfreeze()`
   - 시험 스레드가 있으면 진짜 `unfreeze` 전에 `join(timeout=2 s)`하고, `is_alive()`가 False인지 확인한다.
   - 시간 안에 안 끝나면 그 실행을 **FAIL(하네스)**로 적는다. 그래도 진짜 `unfreeze`는 부른다. 패드를 얼린 채 두지 않기 위해서다.
   - 변형 J에서는 2에서 이미 끝나 있어야 한다.
4. 시험 스레드(이름 `probe`)
   - 유한한 호출 목록을 차례로 한 번씩 부른다: `keep_guard(now+5)` · `guard(True)` · `sprint(True)` · `tap(A, 0.05)` · `hold(Y, True)` · `release_due()` · `neutral()` · `kick(0, 1)`.
   - 호출마다 하네스 기록 `.probe.jsonl`에 한 줄을 남긴다: 이름, 시작 `perf_counter_ns`, 끝 `perf_counter_ns`, 반환값, 예외, `pad._frozen_by`, `pad.epoch` 전·후.
   - 비홀더 출력은 패치 전에도 `_NullPad`로 갔다. 그래서 이 호출들이 장치에 직접 쓸 수는 없고, 위험은 의도를 통한 간접 출력뿐이다.
5. 낙사용 byte 대체 경로 끄기
   - `fire(tm=…)`에 하네스가 감싼 `tm`을 넘기고, 그 `quit_to_title`은 아무것도 쓰지 않고 False를 돌려준다.
   - 메뉴 퀵 종료가 실패해도 게임 메모리 쓰기(byte)로 넘어가지 않고, `close_menu` 뒤 실패로 끝난다.
6. 복구 확인(unfreeze 뒤)
   - 주 스레드에서 `t_req = perf_counter_ns()`를 적고 `guard(True)`를 한 번 부른 뒤, `guard(False)`와 `neutral`을 부른다.
7. 끝: `finally`에서 `pad.release_all()` → `pad.close()` → ctl 닫기.

## 무엇으로 무엇을 보나

| 확인할 것 | 수단 | 비고 |
|---|---|---|
| 시험 호출이 실행됐고 무엇을 돌려줬는지 (막혔는지) | 하네스 `.probe.jsonl` | **막힌 호출은 `_send`까지 안 가서 `pad.drop`에 안 남는다.** `pad.drop` 유무로 판단하지 않는다 |
| 장치에 무엇이 쓰였는지 | `.ctl.jsonl` `pad` 레코드 (`th` 스레드 이름, `caller`, 버튼·스틱, `seq`, `pc`) | 쓴 것까지만 안다 |
| 장치 상태를 독립적으로 보기 | 읽기 전용 패드 오버레이(XInput) | 기록 기능이 있는지 확인 안 함. 없으면 화면 녹화로 사람이 본다 |
| freeze·unfreeze 시각 | `esc` `freeze` / `unfreeze`(ok, ep) 레코드의 `pc` | |
| 게임이 입력을 받았는지 (메뉴 이동, 가드 자세) | 메뉴는 quit_out의 화면 확인(`LAST_STEPS`)과 `quit` ok. 가드 자세는 수단 없음 | 가드가 게임에 먹혔는지는 **측정 못 함** |

## 예정 입력 (실제 메뉴, `quitout.quit_out` · `reload` · `fire`)

홀더(`th` = 하네스 주 스레드)가 장치에 쓸 예정인 것을 순서대로 적으면 다음과 같다. 각 press는 누름 보고 → 뗌(전부 꺼짐) 보고, `HOLD` 0.05 s다.

1. `neutral` (전부 꺼짐)
2. `START` ×1–5 (메뉴 열림 확인까지)
3. `DPAD_LEFT` ×1–2 (시스템 탭)
4. `A`
5. `DPAD_UP` ×1–2 (Quit Game)
6. `A`
7. `DPAD_LEFT` ×1–3 (확인창 OK)
8. `A`
9. 타이틀 뒤 `reload`: `A`를 0.5 s마다, 월드에 들어올 때까지
10. 1 s 대기
11. `neutral`
12. `unfreeze`

실패 경로에는 `close_menu`의 `B` ×≤6이 들어간다. 실패 경로는 곧 중단이다.

**합격 = 예정 입력 보존 + 비소유자의 추가 입력 없음**:

- **예정 입력 보존**
  - 홀더 `pad` 레코드의 버튼 순서가 위 목록과 맞는다(재시도 횟수는 범위 안).
  - 각 누름 보고에는 그 버튼 하나만 있고, 스틱·트리거는 0이다.
  - `quit` ok=True이고 how=menu다.
- **비소유자의 추가 입력 없음**
  - freeze~unfreeze 사이 홀더 보고에 예정 밖 버튼(LB, B, RB, Y, 스틱)이 하나도 없다.
  - `th=probe`인 `pad` 레코드가 없다.
  - `.probe.jsonl`에서 `keep_guard`는 False를 돌려줬고, 모든 호출의 epoch 전·후가 같다.

nudge의 예정 입력: 홀더의 `move(st)` 보고(스틱만, 버튼 없음) → 0.35 s 뒤 `neutral`(전부 꺼짐) → `unfreeze`. 합격 기준은 같다. 이 두 보고 외에 홀더 보고가 없어야 하고, 예정 밖 버튼이 없어야 한다.

## unfreeze 순서와 복구 지연

- `_nudge`의 순서는 `finally: neutral() → unfreeze() → emit nudge_end`이다. **`nudge_end`는 실제 unfreeze 뒤에** 찍힌다.
- `fire`는 `finally: neutral() → unfreeze()`이고, 끝 이벤트가 없다.
- 그래서 unfreeze 시각은 둘 다 `esc` `unfreeze` ok=True 레코드의 `pc`로 잡는다. `nudge_end`로 잡지 않는다.
- 하네스의 unfreeze 감싸기가 join을 먼저 하므로, `unfreeze` 레코드는 시험 스레드가 끝난 뒤에 찍힌다.
- 측정하는 것: **요청 → 장치 쓰기** = `t_req`(guard(True) 부른 시각)부터, 그 뒤 첫 LB `pad` 레코드의 `pc`까지.
  - `pc`는 `update()`가 돌아온 뒤 찍힌다. 그래서 이 값은 ViGEm에 쓴 시각까지만 포함한다.
- 측정하지 못하는 것 (측정했다고 쓰지 않는다):
  - unfreeze부터 실제 봇의 재요청까지. guardkeep의 다음 poll이 위협을 다시 판단하는 시간이고, 하네스는 guardkeep을 돌리지 않는다.
  - 장치 쓰기부터 게임이 LB를 받아 가드 자세를 잡기까지.
  - `POLL_S` 0.02 s는 이 어느 것의 상한도 아니다.

## 단계

| 단계 | 장소 | 실행 | 비고 |
|---|---|---|---|
| 1 quit-out | 적 없는 화톳불 옆 평지 | 변형 J 1회 → 합격이면 변형 C 1회 | 시작 전 세이브 폴더 백업(해시 확인) |
| 2 nudge | 같은 평지, 턱 없는 바닥 | `_nudge((0, 0.5))` 변형 J 1회 → C 1회 | 스틱 방향은 그 자리에서 벽·평지 쪽으로 정한다. `NUDGE_S` 그대로 |
| 3+ | 실제 턱, 적 근처, 낙사 | MoKa 결정 뒤에만 | 낙사·피격 위험. 게임 메모리 쓰기(무적 등)는 쓰지 않음 |

## 중단·해제 절차

- **즉시 중단**
  - 홀더 보고에 예정 밖 버튼이 나온다.
  - 하네스 join 시간 초과.
  - `quit` 실패 / 메뉴가 열린 채 멈춤.
  - 패드 입력이 무시된다.
  - 캐릭터가 예상 밖으로 움직이거나 바닥을 벗어난다.
- **해제**
  1. 하네스 터미널에서 Ctrl+C. `fire`·`_nudge`의 `finally`(neutral → unfreeze)가 돈 뒤, 하네스 `finally`가 `release_all` → `close`를 한다.
  2. 메뉴가 남았으면 키보드 스캔코드로 닫는다.
  3. 패드가 무시되면 실제 패드가 XInput 슬롯 0을 잡고 있지 않은지 보고, 필요하면 게임을 재시작한다.
  4. 프로세스를 강제 종료했다면 가상 패드가 사라진다. 게임 안에서 버튼이 눌린 채 남았는지 화면으로 확인한다.
- **실행 뒤**: `.ctl.jsonl`·`.probe.jsonl`·세이브 해시를 보존하고, 결과를 이 문서와 P-91/P-92 줄에 적는다.

## 실행 명령 (하네스를 만든 뒤, 승인 시에만)

```
.venv/Scripts/python.exe experiments/freeze_probe_live.py quit  --variant J --note "P-91/92 stage 1"
.venv/Scripts/python.exe experiments/freeze_probe_live.py nudge --variant J --stick 0 0.5 --note "P-91/92 stage 2"
```

## 실행 기록

### 시도 0 — 2026-10-27 (게임 시작 19:09 전, 정확한 시각 기록 없음), 사전 조건 미충족 (패치 검증 결과 아님)
- 승인: 채팅 질문 "실행 전 확인 6가지 … quit --variant J 한 번 실행을 승인하나요?"에 MoKa가 "확인 완료, 실행"이라고 답함.
- 결과: `env.make_telemetry` → `pymem.ProcessNotFound: DarkSoulsRemastered.exe`. 게임이 꺼져 있었다. Pad·ctl·freeze·기록 파일 없음.
- 그래서 그때 확인했다는 6가지 중 "적 없는 곳에서 정지"·"게임 포커스"는 실제로는 충족되지 않은 상태였다.

### 실행 1 — 2026-10-27 19:10:36, run `20261027_191035_freeze_probe_quit` (부분 합격, 로그 기준)
- 승인: 게임을 켠 뒤 MoKa 채팅 "게임 실행했어, 타이트 화면 상태야" → (월드 진입 요청) → "월드 진입, 실행".
  이 실행 직전에 6가지 체크리스트를 다시 하나씩 확인한 기록은 **없다**. 시도 0 때의 확인과 "월드 진입, 실행"만 있다.
- 명령: `.venv/Scripts/python.exe experiments/freeze_probe_live.py quit --variant J --note "P-91/92 stage 1"`, 종료 코드 0.
- 코드: ctl 헤더 commit 9eb185e + 커밋 안 한 minimal 패치(control.py 수정 17:09, sha256 6492743e…, 실행 뒤 바뀌지 않음).
  ctl 헤더는 커밋 안 한 변경을 기록하지 않는다. 시험 호출이 막힌 것(keep_guard False)이 패치가 적용됐다는 간접 근거다.
- 기록: `data/runs/20261027_191035_freeze_probe_quit.probe.jsonl`(29줄), `.ctl.jsonl`(54줄, written 54 · dropped 0 · lost 0 · write_errors 0).

| 시각 (ctl wall 정렬, 대략) | 사건 |
|---|---|
| 19:10:38.209 | `fire_start`, `freeze`, 하네스 `freeze_ok` |
| 19:10:38.210 | 시험 호출 8개 끝(`probe_exit`, 1.67 ms) → `owner_resume` 19:10:38.211 |
| 19:10:38.263 – 19:10:39.290 | 메뉴 입력 START … 마지막 A |
| 19:10:40.309 | `quit` ok (월드에서 사라짐), 텔레메트리 값 없음 시작 |
| 19:10:40.327 – 19:10:45.648 | reload A ×11 |
| 19:10:46.003 | 텔레메트리 복귀 |
| 19:10:47.004 | 마지막 neutral → `unfreeze` → 복구 `guard(True)` → LB 출력 기록 → `release_all` → `close` |

결과 표현:
- **소프트웨어 출력 로그**: 시험 호출 8개 모두 막힘(반환 keep_guard False, 나머지 None, epoch 2 그대로). freeze 구간 홀더 출력은
  예정 버튼 START·LEFT·A·UP·A·LEFT·A(재시도 없음)와 reload A ×11뿐, 각 보고 버튼 1개·스틱·트리거 0. 예정 밖 버튼 없음. `pad.drop` 0건(막힌 호출은 출력까지 안 감).
- **메뉴 종료·reload**: 프로그램 판정 기준 성공 — quit_out 화면 확인 단계 전부 통과, quit 2.05 s, reload 5.7 s, 같은 자리(27.39, 26.6, 100.81) HP 786.
- **화면·XInput**: 미확인. 실행 시각(19:10)의 녹화 파일을 찾지 못했다 — OBS 기록 폴더 `C:\Users\moka\Videos`의 가장 최근 파일은 10-03,
  OBS 프로세스 없음, 사용자 폴더·D:·E: 깊이 3까지 18:30 이후 동영상 없음. 다른 장치로 녹화했는지는 모른다. 독립 검증 미완료로 둔다.
- **86 µs**: 이 하네스의 `guard(True)` 요청(`recover_req`)부터 LB 출력 기록(`pad` 레코드 pc, ViGEm update 반환 뒤)까지. 장치 쓰기 47 µs 포함.
- **실제 guardkeep 재요청 지연, 게임이 LB를 받아 가드를 올리기까지**: 미측정.
- fallback 차단: 메뉴 종료가 성공해 byte 경로에 가지 않았다 — 실기에서는 확인되지 않았다(게임 없는 테스트로만 확인).

기록의 두 가지 구분:
- **같은 보고 접기(`dup`)**: Pad는 직전과 똑같은 장치 보고를 새 줄로 쓰지 않고 다음 줄의 `dup`으로 센다. freeze 직후·quit_out 첫 neutral·fire 끝 neutral은
  모두 전부 꺼짐이라 따로 `pad` 줄이 없다(첫 START 줄 dup 2, 복구 LB 줄 dup 1). 이 neutral들은 `neutral` 레코드로는 남아 있다. 정보가 빠진 게 아니라 같은 값이 압축된 것이다.
- **누락 0**: ctl writer가 받은 레코드를 큐 초과·쓰기 오류로 잃지 않았다는 뜻(dropped 0 · lost 0 · write_errors 0). 기록할 대상이 아닌 것(막힌 호출, 게임 쪽 입력 수신)이 없다는 뜻은 아니다.
