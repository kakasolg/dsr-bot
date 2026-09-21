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

## 다음 단계
2. 순찰 봇 — 웨이포인트 추종(vgamepad) + Guard(피격/저HP 시 회피·후퇴)
3. 플레이북 + 복기(post-mortem) + 롤백 — "에피소드 1~10 보다 21~30 이 오래 사는가"
