# 메뉴 명령은 키보드로 (DSR PC 기본 키)

[MoKa] 2026-10-13: "컨트롤러로 조작 하는 것보다, 메뉴 명령은 키보드가 정확해." · "앞으로 메뉴는 키보드로 해."

## 왜

- 10-13 오후: MoKa가 실제 컨트롤러로 시연한 뒤 뺐더니 화면에 "컨트롤러 연결 해제됨 (Xbox 360 Controller)" ×2 —
  그 뒤 게임이 봇의 가상 패드(ViGEm)를 **전혀** 안 받음. XInput 0번은 비어 있고 우리 패드가 0번을 잡았는데도 스틱 0 m,
  `savepoint.py restore`의 메뉴 퀵 종료 3번 실패, 타이틀 Continue 40 s 무반응. `pad.reconnect()`도 소용없음.
- 같은 때 **키보드는 그대로 먹음** — MoKa가 화면을 보며 키를 하나씩 불러 줘서 타이틀까지 나가고, 게임을 완전히 끔.
- 메뉴는 화면에 키 안내가 그대로 나옴 (`↕:Select E:Enter Q:Close`, 위 탭 줄 `HOME < … > END`) — 키 이름 = 화면 안내.
  패드는 연결 상태·슬롯·포커스에 따라 조용히 씹히는데, 키보드는 그런 상태가 없음.
- 게임 플레이(이동·싸움)는 지금처럼 패드. 키보드는 **메뉴·타이틀·확인 창**에만.

## 보내는 법

`control.focus_game()` 뒤 `user32.keybd_event(vk, scan, flags, 0)` — **스캔 코드 플래그 필수** (`KEYEVENTF_SCANCODE` 0x0008, 게임이 스캔 코드로 읽음).
방향키는 확장 키 플래그 `KEYEVENTF_EXTENDEDKEY` 0x0001도. 누름 0.1 s, 키 사이 ~0.6 s (메뉴 전환 시간).

| 키 | vk | scan | 확장 |
|---|---|---|---|
| ESC | 0x1B | 0x01 | |
| E | 0x45 | 0x12 | |
| Q | 0x51 | 0x10 | |
| Enter | 0x0D | 0x1C | |
| ← ↑ → ↓ | 0x25 0x26 0x27 0x28 | 0x4B 0x48 0x4D 0x50 | ✓ |

- 포커스를 잡은 직후 **첫 키 하나가 씹힌 적 있음** (10-13: 첫 E 무반응, 두 번째 E는 먹음) → 단계마다 화면/메모리로 확인하고 안 바뀌었으면 한 번 더.
- 단계 확인: 화면 캡처(`screen_prompt.window_rect()` + `PIL.ImageGrab`) 또는 메모리(`tm.menu_open()`, 위치 읽힘 = 게임 안).

## 순서 (10-13 MoKa가 화면 보며 불러 준 그대로, 화면마다 확인함)

### 게임 안 → 저장하고 타이틀로
| 키 | 화면 |
|---|---|
| ESC | 메뉴 열림, 첫 탭 아이템 ("Browse and use items") |
| ← | 맨 오른쪽 탭으로 넘어감 = 시스템 ("Configure options or quit the game") |
| E | 시스템 목록: Options · Brightness · Key settings · Network settings · PC settings · Quit Game (Options 선택) |
| ↑ | 맨 아래로 넘어감 = **Quit Game** ("Save the game and return to Title Menu") |
| E | 확인 창 "Are you sure you want to save the game and return to Title Menu?" — **기본 CANCEL** |
| ← | OK |
| E | 저장 → 타이틀 "PRESS ANY BUTTON" |

### 타이틀 → 이어하기
| 키 | 화면 |
|---|---|
| E | "PRESS ANY BUTTON" 넘김 → "Game will start in offline mode." OK |
| E | 타이틀 메뉴 Continue · Load Game · New Game · System (아래에 더) — Continue 선택돼 있음 |
| E | Continue → 로딩 → 마지막 자리 |

### 타이틀 → 게임 완전 종료
| 키 | 화면 |
|---|---|
| ↓ ×5 | Continue → Load Game → New Game → System → Log In → **Quit Game** (↑는 맨 위에서 안 넘어감) |
| E | 게임 꺼짐 (확인 창 없이, 10-13) |

## 게임 켜기 · 끄기 — [win]이 직접 해도 됨

[MoKa] 2026-10-13: "너가 직접 켜 봐. 내가 통제 않해도 그 정도는 해도 됨." — 게임을 켜고 끄는 건 MoKa에게 묻지 않고 [win]이 함.
- **켜기**: `steam_state.check()`로 Steam 오프라인 확인 (`offline: True`, 바깥 연결 0) → `Start-Process 'steam://rungameid/570940'`
  (DSR 앱 번호 570940, 9-28에도 이렇게 켬) → 프로세스 `DarkSoulsRemastered` 뜨면 ~20 s → 타이틀 "PRESS ANY BUTTON" → 위 **타이틀 → 이어하기** (E · E · E).
  10-13: 켜고 이어하기까지 키보드로 됨, 이어하기 뒤 봇 패드도 다시 먹음 (스틱 0.76 m).
- **끄기**: 게임 안이면 **저장하고 타이틀로** 순서 → **타이틀 → 게임 완전 종료** (↓ ×5 → E). 프로세스 0개 확인.
- 패드가 안 먹는 상태(위 "왜")는 껐다 켜면 풀림 — 10-13 확인.
- 10-13: 저장하고 타이틀로 7키를 한 번에 보내도 됨 (키 사이 0.6 s, 타이틀까지 확인).

## 지금 상태 · 다음

- 문서만 (10-13). 코드에서 메뉴 키를 보내는 곳: `quitout.py` (메뉴 퀵 종료 — 패드 START ×N…), `savepoint.py` (`to_title`, `back_in`),
  `souls/shop.py` (상인 메뉴), `control.focus_game` (ESC · ALT로 포커스). 이것들을 키보드 순서로 바꾸거나, 패드가 안 먹을 때 키보드로 넘어가게 하는 건
  ROADMAP `keyboard-menus`.
- 패드가 계속 안 먹을 땐 위 순서로 타이틀 → 게임 종료 → MoKa가 다시 켬 (메모리 `keyboard-when-pad-ignored`).
