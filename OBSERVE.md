# 관찰 기록기 (Phase 1) — `observe_record.py`

사람이 플레이하는 동안 게임 메모리·컨트롤러·F9 를 **읽기만** 해서 한 파일에 남긴다.
전투 정책·학습·항법과 무관한 관찰(observability) 실험이다 (사용자 2026-09-26).
뷰어 v0(Phase 2, `observe_view.html` — 아래 "뷰어" 절)까지 있다. 메모(Phase 3)·영상 동기화·슬롯 배정·의미 라벨은 아직 없다.

```
python observe_record.py                 # data/observe/<YYYYmmdd_HHMMSS>.jsonl, Ctrl+C 로 끝
python observe_record.py --minutes 1.5   # 90 s 뒤 스스로 끝
python observe_record.py --radius 20
python observe_record_test.py            # 오프라인 테스트 (게임·패드 없이)
```

끝나면 요약을 찍는다: 월드 줄 수, 패드 줄 수, 마커 수, 적 읽기 실패, 락온 못 찾음, read_ms p50/p95, 파일 경로.
같은 요약이 파일 마지막 줄(`sys:end`)에도 있다.

## 한계 — 먼저 읽을 것

- **`observe_record.py` 는 봇과 따로 도는 독립 읽기 전용 텔레메트리 리더다.** `dsr_telemetry.py` 의 AOB 두 개(`WorldChrBase`,
  `ChrFollowCam`)와 vtable 상수 두 개를 복제해 쓴다. 그래서 **이 기록의 값이 봇 텔레메트리(`DSRTelemetry.snapshot`·`feed`)
  출력과 같다고 가정하면 안 된다** — 읽는 시점·반경·거르는 규칙이 다르고, 한쪽 상수만 바뀌면 어긋난다.
- **`team_bot` 과 `bot_phantom` 은 진단용 판정이지 원시 게임 사실이 아니다.** 어느 쪽도 원시 관찰에서 캐릭터를 걸러내는 데
  쓰지 않는다 — 반경 안(또는 락온 대상)이면 값과 상관없이 기록된다.
- **`alive_derived` 는 `hp_raw > 0` 에서만 만든 값이다.** 원시 게임 사망 플래그가 아니다.
- **F9 는 전역 폴링이다.** DSR 창에 포커스가 없어도(다른 창에서 F9 를 눌러도) 마커가 생긴다. 마커에는 실수로 생긴 잡음이
  섞일 수 있다.

- **월드 스냅샷은 10 Hz 다. 맥락·궤적을 보는 용도이지, 프레임 단위 애니 의미 판정용이 아니다.**
  게임은 60 fps 라 한 줄 사이에 6 프레임이 지나간다. 짧은 애니(수십 ms)는 통째로 안 찍힐 수 있고,
  찍힌 애니 번호의 시작 시각은 최대 100 ms(+ read_ms) 늦다.
- 패드는 120 Hz 로 보고 **바뀔 때만** 쓴다. 게임이 그 입력을 몇 프레임째 받았는지는 모른다.
- **Steam Input 이 켜져 있으면 패드 기록이 게임이 받은 입력과 다를 수 있다 — DSR 의 Steam Input 을 끄고 기록할 것.**
  기록기는 XInput 을 읽고, Steam Input 은 입력을 가운데서 가로채거나 바꿀 수 있다. 2026-09-26 첫 스모크 녹화(`075757`, `080150`)에서
  RB 공격 3번(애니 303000)이 패드 줄에 하나도 없었다 — 그때 Steam Input 상태는 확인 못 했다. 끈 뒤(`081905`)에는 RB 3번이 모두
  `btn=512` 로 공격 애니 직전에 찍혔다. 게임 창이 아닌 곳(터미널 등)에 포커스가 있을 때의 패드 입력은 검증하지 않았다.
- `alive_rule: "hp_gt_zero"` 가 파생 규칙 이름이다. 원시 사망 플래그는 아직 모른다.
- `team_bot` 은 원시 팀 번호가 아니다. DS1 은 팀 필드를 아직 못 찾았고, `dsr_telemetry.read_chr` 가 vtable·FRIENDLY·flags1 로
  분류한 값이다. 근거가 되는 원시 값은 `flags1_raw`·`vt` 로 따로 남긴다.
- `bot_phantom` 은 `dsr_telemetry.snapshot` 의 "몸 없음" 규칙(헤더 `bot_phantom_rule`)을 따라 한 **진단값**이다. 적을 빼지 않는다.
- 애니 번호는 증거로만 남긴다. 공격 중·후딜·빈틈 같은 판정은 하지 않는다.

## 읽기 전용 보장

- 게임 프로세스를 `PROCESS_VM_READ | PROCESS_QUERY_INFORMATION` 으로만 연다. 쓰기 권한이 없는 핸들이라 실수로 쓰려 해도 OS 가 거부한다.
  `SeDebugPrivilege` 도 켜지 않는다 (`DSRTelemetry.__init__` 은 `PROCESS_ALL_ACCESS` + 디버그 권한이라 부르지 않는다).
- 게임 읽기는 `GameReader` 를 거친다 — `player_ptr, chr_ptrs, read_chr, handle, lock_target, cam_yaw, q, i32, f32` 만 통과, 나머지 이름은 `AttributeError`.
- 패드는 `XInputGetState` 만 (`XInputSetState`·진동 없음). F9 는 `GetAsyncKeyState` 상위 비트 폴링만 — 입력 소비·주입·`SendInput`·`keybd_event`·저수준 훅 없음.
- `vgamepad, control, env, feed, souls, botlock` 을 import 하지 않는다 (테스트가 새 인터프리터에서 확인). `bot.lock` 을 잡지 않는다.
- 출력 파일은 `open("x")` — 이미 있는 파일은 덮지 않는다. 기존 `data/demo`·`data/trace`·`data/episodes` 는 건드리지 않는다.

## 스키마 (v1)

JSONL 한 줄 = 한 사건. 모든 줄에 `k`(종류)와 `ms`(세션 시작 뒤 밀리초, `perf_counter_ns` 단조 시계) 가 있다.
세 스레드(패드 120 Hz · 월드 10 Hz · 쓰기)가 같은 시계를 쓰므로 **파일 안 줄 순서가 아니라 `ms` 로 정렬**한다
(같은 종류 안에서는 순서도 시간순이다).

| k | 언제 | 필드 |
|---|---|---|
| `hdr` | 첫 줄 | `v`, `wall_ns`(벽시계 기준점), `pid`, `hz_world`, `hz_pad_poll`, `radius_m`, `read_access`, `alive_rule`, `marker_key`, `marker_debounce_ms`, `bot_phantom_rule` |
| `w` | 10 Hz | `read_ms`(이 스냅샷 읽는 데 걸린 시간), `epoch`, `p`, `cam_yaw`, `lock`, `e`, `e_fail` |
| `pad` | 120 Hz 폴링, 바뀔 때만 | `i`(패드 번호), `pkt`(XInput 패킷 번호), `btn`, `lt`, `rt`, `lx`, `ly`, `rx`, `ry` — 전부 원시 값 |
| `mk` | F9 상승 에지, 300 ms 디바운스 | `n`(1부터) |
| `sys` | 상황 | `ev`: `sync`(10 s 마다 `wall_ns`), `loading`/`loaded`(`epoch`), `pad_found`/`pad_lost`, `error`(`where`, `msg`), `end`(요약) |

`w.p` (플레이어): `pos[x,y,z]`, `hd`(heading, +0x4 원시 각), `anim`, `hp_raw`, `max_hp_raw`, `sp`, `max_sp`, `handle`

`w.lock`: `{"h": 원시 락온 핸들, "resolved": true|false|null, "id": 적 id|null}`
— `h=-1` 이면 락온 없음(`resolved:null`), `h=null` 이면 못 읽음, 목록에서 못 찾으면 `resolved:false`.

`w.e[]` (적·NPC — 반경 안이면 팀과 무관하게 전부, 반경 밖이라도 락온 대상):

| 필드 | 뜻 |
|---|---|
| `id`, `id_src` | 런타임 신원 (아래) |
| `handle`, `ptr` | 원시 핸들·포인터 |
| `npc` | NPC 파라미터 번호 |
| `team_bot`, `flags1_raw`, `vt` | 봇 분류값 / 원시 플래그 / vtable 종류(`player`·`enemy`·`other`) |
| `pos`, `hd`, `d`, `dy` | 좌표, heading, 플레이어와 3D 거리, 높이차(적 − 나) |
| `hp_raw`, `max_hp_raw`, `alive_derived`, `alive_rule` | HP 원시 값 / 파생 생존 / 규칙 이름 |
| `anim` | 원시 애니 번호 |
| `why` | 기록된 이유: `near`(반경 안), `lock`(락온 대상) |
| `bot_phantom` | 진단값 (위 한계 참고) |

### 런타임 신원

- `id = "h:<핸들 8자리 hex>#<epoch>"`, `id_src:"handle"` — 게임 자신의 캐릭터 핸들(+0x8), 락온이 가리키는 값과 같다.
- 핸들이 0·-1·못 읽음이면 `id = "p:<포인터 hex>#<epoch>"`, `id_src:"ptr"`.
- `epoch` 는 로딩(플레이어를 못 읽는 구간)이 끝날 때마다 1 씩 는다 — 퀵 종료·워프 뒤 핸들·포인터 재사용을 가른다.
- 적 읽기(`read_chr`)가 실패하면 그 스냅샷의 `e` 에서 **빠지기만** 하고 `e_fail` 이 는다. 이전 값 복사·보간 없음 → 뷰어에서 빈칸.
  좌표조차 못 읽은 포인터는 반경 안인지 몰라서 실패로 세지 않는다.
- 슬롯(enemy-map 번호) 배정은 Phase 1 에 없다.

### 동기화

- 모든 줄: 같은 단조 시계의 `ms`. 헤더 `wall_ns` + `sys:sync`(10 s 마다 `ms`↔`wall_ns` 쌍)로 벽시계와 맞춘다.
- 영상(OBS) 동기화는 아직 없다. 나중을 위해: 녹화 시작마다 구르기 한 번 같은 "박수"를 치면 데이터의 `anim` 변화와 영상 첫 프레임으로 어긋남을 잡을 수 있다.

### 크기 (가짜 출력으로 잰 값, 실측 전)

| 경우 | 월드 줄 | 60 s |
|---|---|---|
| 적 1 (아레나) | 약 0.7 KB | 월드 약 0.4 MB + 패드 0.05–0.5 MB |
| 적 9 (경사로 4+2 + 주변) | 약 4.3 KB | 월드 약 2.6 MB + 패드 |

패드는 평소 초당 10–30 줄(약 90 B), 최악(스틱 계속 움직임) 초당 120 줄.

## 수동 점검표 (실제 게임, 사용자 승인 뒤)

코드 (게임 없이, 테스트가 확인):
- [ ] `python observe_record_test.py` 전부 통과

실제 게임:
- [ ] 기록 중 장치 관리자·`vgamepad` 목록에 가상 패드가 늘지 않는다 (기록 전/중 비교)
- [ ] 기록 전·중·후 30 초씩 버튼·스틱을 하나씩 눌러 본다 — 게임 반응이 같다
- [ ] 게임 안에서 F9 를 눌러도 게임은 아무 반응이 없고 `mk` 한 줄만 는다
- [ ] `run.py clear-ramp --no-rest` 도중 기록기를 켰다 끈다 — 봇 동작·로그가 달라지지 않고, `bot.lock` 은 봇만 잡고 있다
- [ ] Ctrl+C → 마지막 줄이 `sys:end`, 반쯤 잘린 줄 없음, 요약이 찍힌다
- [ ] 퀵 종료·다시 불러오기 → `loading`/`loaded`, `epoch` 증가, 기록 계속
- [ ] 컨트롤러 뽑았다 꽂기 → `pad_lost`/`pad_found`, 기록 계속
- [ ] 60 s 기록: 크기·줄 수가 위 표 범위, `read_ms` p95 < 20 ms
- [ ] 기존 파일 해시가 기록 전후 같다: `data/demo/20260924_162859.jsonl`, `data/trace/play_*`

첫 데이터 순서: 안전한 평지 아레나에서 보통 망자 하나 → 방패병 하나. 각 60–90 s, 판단한 순간에 F9 2–3 번.
경사로 4+2 무리는 나중 검증 대상.

## 스모크 테스트 결과 (2026-09-26, 사용자 수동 조작, 불의 제전 근처 경사로 위)

| 파일 | 길이 | 월드 / 패드 / 마커 | p95 read_ms | 비고 |
|---|---|---|---|---|
| `20260926_075757` | 225 s | 2248 / 447 / 0 | 4.32 | 처음 210 s 패드 안 잡힘(`pad_found` 210.6 s), 거의 정지 |
| `20260926_080150` | 168 s | 1682 / 1417 / 5 | 4.48 | RB 공격 3번이 패드 줄에 없음 (Steam Input 의심, 위 한계) |
| `20260926_081905` | 46 s | 463 / 40 / 1 | 4.14 | Steam Input 끔. RB 3번 → 303000·303001·303002, B → 690, F9 1번 = 마커 1 |

- 세 파일 모두: 깨진 줄 0, `sys:end`(`ctrl_c`), 오류 0, 적 읽기 실패 0, 월드 초당 10.0 줄·최대 간격 113 ms.
- 입력 → 애니 간격(10 Hz 라 ±100 ms): RB→공격 약 45–145 ms, B→백스텝 약 150–220 ms.
- 미검증: 락온 추적(안 씀), 게임 창 밖 포커스에서의 패드.
- 크기: 캐릭터 6–12 명일 때 분당 약 1.5–2.4 MB.

## 뷰어 v0 (Phase 2) — `observe_view.html`

브라우저에서 파일을 직접 연다(더블클릭 → "기록 파일 열기" 또는 끌어 놓기). 서버·네트워크·외부 라이브러리 없음
(CSP 로 네트워크 요청을 막아 둔다). 원시 기록을 읽기만 하고 아무것도 쓰지 않는다. 게임·패드와 연결되지 않는다.

- 위에서 본 지도: 가로 x, 세로 z. 플레이어 = 파란 화살표(heading), 캐릭터 = id 별 색 점 + 궤적. 점 옆에 `npc`·`y`·원시 anim.
  락온 대상 = 노란 고리, `alive_derived=false` = 속 빈 원. 그 스냅샷에 없는 캐릭터(읽기 실패·반경 밖)는 그리지 않고 궤적도 끊는다.
- 오른쪽 표: 지금 시각의 플레이어(pos·y·hd·anim·HP·SP·cam_yaw·lock)와 캐릭터(거리순, id·npc·y·dy·d·anim·HP·team_bot·bot_phantom·why).
- 아래: 재생/정지, 시간 막대(마커 눈금), 속도(0.25–4×), 앞뒤 마커로 이동.
- ±2 s 사건 보기: 지금 시각 앞뒤 2 초의 패드 변화·마커·sys·플레이어 anim 변화·캐릭터 anim 변화를 시간순으로, 레인 그림과 목록으로.
- 버튼 이름(A·B·LB·RB…)은 XInput 비트 이름일 뿐이다. 공격·가드 같은 의미 라벨은 붙이지 않는다.
- 키: Space 재생/정지 · ←/→ 0.1 s · Shift+←/→ 1 s · `[` `]` 이전/다음 마커.
- 이전 형식(`data/demo`, `data/trace`)은 읽지 않는다 — `hdr.v == 1` 인 파일만.

## 되돌리기

Phase 1 은 새 파일 3개뿐이다 — `observe_record.py`, `observe_record_test.py`, `OBSERVE.md` 를 지우고,
원하면 `data/observe/` 를 지운다. Phase 2 는 `observe_view.html` 하나 — 지우면 끝이다.
기존 코드·데이터는 바뀐 게 없어서 되돌릴 것이 없다.
