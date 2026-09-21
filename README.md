# bot/ — 에피소드 학습 봇 (작업 중)

스트리머용 어댑터(상위 폴더)와 별개로, **엘든링을 자율 순찰하고 실패에서 배우는 봇**을 만드는 곳입니다.
목표와 단계는 [docs/DEVELOPMENT.md](../docs/DEVELOPMENT.md) 의 "에피소드 학습" 항목 참고.

## 1단계 (완료): 텔레메트리 + Recorder

```
Cheat Engine 브릿지 ── symbols.json ──▶ telemetry.py (pymem, 읽기 전용) ──▶ record.py (JSONL 에피소드)
```

- `telemetry.py` — 플레이어·주변 캐릭터(537개 중 반경 내) 상태를 초당 수십 회 읽음. 포인터 경로는 Hexinton 8.0.4 테이블에서 가져옴
- `record.py` — 10Hz 로 에피소드 파일 기록. 사망 시 직전 30초를 `.death.json` 으로 따로 저장 (복기 재료)

### 실행

```bash
# 게임 오프라인 실행 → 캐릭터 로드 → (상위 폴더에서) npm run attach   ← symbols.json 을 내보냄
cd bot
.venv\Scripts\python.exe telemetry.py      # 실시간 표시
.venv\Scripts\python.exe record.py         # 기록 시작 (Ctrl+C 로 종료)
```

venv 만들기 (처음 한 번): `uv venv .venv --python 3.12 && uv pip install --python .venv/Scripts/python.exe pymem python-dotenv`

### 읽는 값 (실측)

| 값 | 경로 | 비고 |
|---|---|---|
| 플레이어 ChrIns | `[[[WorldChrMan]+0x10EF8]+0]` | |
| 캐릭터 목록 | `[[WorldChrMan]+0x1F1B8]..+0x1F1C0` 포인터 배열 | 림그레이브 시작 지점에서 537개 |
| HP / MaxHP | `[[ChrIns+0x190]+0]+0x138 / +0x13C` | |
| 좌표 | `[[ChrIns+0x190]+0x68]+0x70..0x78` | |
| 팀 | `ChrIns+0x6C` | 1 플레이어, 6 적, 47 영체, 48 (미확인) |
| NpcParamId | `ChrIns+0x60` | 테이블 CharNames 로 이름 변환 |
| 애니메이션 | `[[ChrIns+0x190]+0x80]+0x90` | 12000000 대기, 17002/18002 사망, 쥐 20 = 엎드림 |
| 글로벌 좌표 | `ChrIns+0x6C0/0x6C4/0x6C8` (x, 높이, z) | 청크를 넘어도 연속. 테이블 표기(6B0)와 달리 실측 6C0 |
| 방향 | `ChrIns+0x6CC` (rad) | |
| MapID | `ChrIns+0x6D0` | FieldArea.MapID 와 동일 (예: 0x3C2A2500 = 림그레이브 시작 청크) |
| 카메라 yaw/pitch | `[camadr]+0xB4 / +0xB8` | 브릿지 `symbols` 가 테이블의 카메라 섹션을 켜고 심볼을 내보냄 |

### 기록 형식

```jsonc
{"t": 1789987164.4, "hp": 499, "mhp": 499, "pos": [3.8, 7.2, 9.8], "anim": 12000000,
 "near": [[40800000, 6, 162, 162, 0.9, 20], ...]}          // [npcParam, team, hp, maxHp, dist, anim]
{"t": ..., "event": "damage", "dmg": 250, "by": [[40800000, 0.9, 20]], ...}
{"t": ..., "event": "end", "reason": "death", "seconds": 81.5, "killers": [[40800000, "Rat", 0.9]]}
```

## 2단계 (완료): 순찰 봇

```
telemetry (좌표·카메라 yaw) ──▶ nav.goto (조향 루프 20Hz, 막힘 탈출) ──▶ control.Pad (ViGEmBus 가상 Xbox 패드)
                                     ▲
                              patrol.py (웨이포인트 A→B→A, Guard, 에피소드 기록)
```

- `control.py` — vgamepad 래퍼. 실측: 왼스틱 앞 = 카메라 yaw 방향, 오른쪽 = +90°, 걷기 2.5 m/s / 달리기 3.7 m/s
- `nav.py` — `goto((x, z))`: 카메라 기준 조향, 2초간 0.3 m 미만 진행이면 점프+옆걸음 탈출
- `patrol.py record <이름>` — 실제 패드로 걸으면 4 m 마다 웨이포인트 저장
- `patrol.py run <이름> --laps N` — 왕복 순찰 + Guard(피격 시 구르기, HP<50% 성배병, HP<35% 후퇴, 적 3+ 스프린트) + 에피소드 기록

실측(2026-09-21): 최초의 계단 → 다음 축복 204 m 경로(42 지점)를 **혼자 왕복 완주** (82 지점 도착, 사망 0, Guard 구르기 1회).

### 좌표 주의
`ChrIns+0x6C0` 의 좌표는 **256 m 타일 기준 상대값**이라 타일 경계에서 124 → -128 로 튄다.
`telemetry.tile_to_world()` 가 MapID(0xAAXXZZ00)의 타일 번호 × 256 을 더해 연속 좌표로 만든다. 경로·순찰은 전부 이 연속 좌표를 쓴다.

### 필요한 것
- **ViGEmBus 드라이버** (`winget install --id ViGEm.ViGEmBus -e`) — 가상 패드
- 게임 창이 포그라운드여야 패드 입력이 먹음. CE 의 Lua Engine 창이 뜨면 포커스를 뺏으므로 브릿지가 CE 의 `print` 를 파일 로그로 돌려 놓음

## 다음 단계
3. 플레이북 + 복기(post-mortem) + 롤백 — "에피소드 1~10 보다 21~30 이 오래 사는가". 적이 없는 경로엔 학습거리가 없으니 어댑터의 소환 효과를 "시청자 방해 시뮬레이터"로 주기적으로 넣는다.
