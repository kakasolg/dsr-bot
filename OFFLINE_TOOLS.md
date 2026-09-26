# DSR 오프라인 도구 — 게임 함수 호출·메모리 쓰기

**오프라인 전용** (온라인이면 소프트밴). 전부 `dsr_telemetry.DSRTelemetry` 에 있거나, 아직 안 만든 것은 방법만 적는다.
출처: [DSR-Gadget](https://github.com/JKAnderson/DSR-Gadget) (JKAnderson) `DSRHook.cs`·`DSROffsets.cs`·`Resources/Assembly/*.txt`.
캐릭터에 되돌릴 수 없는 손실(소울·핏자국)이 걸린 조작은 실행 전에 사용자에게 방법과 위험을 말하고 확인받는다.

## 만들어 둔 것 (2026-09-25 실측)

| 하는 일 | 함수 | 방식 | 실측 |
|---|---|---|---|
| 화톳불로 워프 (구역 간) | `bonfire_warp(id)` | 마지막 화톳불 쓰기 + 게임 워프 함수 호출 (`BONFIRE_WARP_AOB`, `func(*ChrClassBase, 1)`) | 성벽 마을 ↔ 불의 제전 2.5~2.8 s. `bonfires.py` 목록(불 붙인 곳)만 간다 |
| 같은 구역 짧은 이동 | `safe_warp(x,y,z)` | NoDead 켜고 좌표를 붙잡아 바닥이 서는지 확인, 실패면 제자리로 | 불의 제전 안 8 m 1.4 s |
| 좌표만 바꾸기 | `pos_warp` | ChrMapData +0x108/+0x110.. | **먼 구역 금지** — 땅을 뚫고 떨어져 죽었다 (소울 3840) |
| 퀵 종료 (메뉴 없이) | `quit_to_title()` | ChrClassWarp **+0x19 = 1** → 곧장 타이틀 | 0.58 s (메뉴 방식 2~2.8 s). `Moves.quit_reload` 가 먼저 쓴다 |
| 플레이어 무적 | (아직 함수 없음, 직접 씀) | 플레이어 ChrData1 **+0x524** (`ChrFlags2` 0x514 + 1.03 보정 0x10) 에 `NoDead 0x20 \| NoDamage 0x40` | 0x0 → 0x60 켬. NoDamage 면 회복도 안 된다. 로딩 뒤 풀릴 수 있음 |

## 인간성 아이템 넣기 — 방법만 (아직 안 씀, 사용자 2026-09-25 "지금은 그대로")

불 키우기(에스트 5 → 10 → …)에 인간 상태 + 인간성 1개가 필요한데 지금 없다. 넣는 방법:

1. 게임의 아이템 얻기 함수 주소: AOB `48 89 5C 24 18 89 54 24 10 55 56 57 41 54 41 55 41 56 41 57 48 8D 6C 24 F9` (DSR-Gadget `ItemGetAOB`, 절대 주소 — `bonfire_warp` 처럼 `pattern_scan_module`).
2. 아이템: 분류 **0x40000000**(소모품, 인벤토리 판독 `goods_count` 와 같은 코드), 번호 **500 = 인간성**, **501 = 쌍둥이 인간성**.
3. 기계어 (DSR-Gadget `GetItem.txt`, 0xFE 자리에 값을 채운다):
   ```
   0x00 mov edx, <분류>            ; ba ....
   0x05 mov r9d, <개수>            ; 41 b9 ....
   0x0b mov r8d, <번호>            ; 41 b8 ....
   0x11 mov r12d, 0xfefefefe       ; (그대로 둔다)
   0x17 movabs rax, [<ChrClassBase>]   ; 48 a1 ........  (static ChrClassBase 주소)
   0x21 mov byte [rsp+0x38], 1
   0x26 mov byte [rsp+0x30], dil
   0x2b mov byte [rsp+0x28], 1
   0x30 mov r15, [rax+0x10]
   0x34 mov byte [rsp+0x20], 1
   0x39 lea rcx, [r15+0x280]
   0x40 sub rsp, 0x38
   0x44 movabs r14, <아이템 얻기 함수>
   0x4e call r14
   0x51 add rsp, 0x38
   0x55 ret
   ```
   채우는 자리: +0x1 분류, +0x7 개수, +0xD 번호, +0x19 ChrClassBase(8바이트), +0x46 함수 주소(8바이트).
   원본 바이트는 DSR-Gadget `Resources/Assembly/GetItem.txt` 에서 그대로 가져온다 (위는 읽기용).
4. `pm.allocate` → `write_bytes` → `start_thread` → `free` (`bonfire_warp` 와 같은 순서).
5. 확인: `goods_count(500)` 이 늘었나.

주의: 봇 성적 비교 실험 중이면 에스트 수가 바뀌어 묶음 비교가 흐려진다 — `run.py` 의 `char` 사건처럼 기록을 남기고 묶음을 나눈다.

## 불의 강도 (kindle)

- 에스트 개수 = 불 강도 / 2 + 5. 보통 화톳불 초기 0 → 5 개. 불의 제전은 스크립트상 초기 10(→10 개), 플래그 11020108 이면 30(→20 개).
- 지금 불의 제전 20 개는 **사용자가 직접 키운 것** (플래그 11020108 은 꺼져 있음). 키운 값의 메모리 위치는 못 찾음.
- 키우기: 인간 상태 + 인간성 1개씩, 한 번에 +5. 불 키우기 비술 없이는 10 까지로 알고 있음(미확인).

## 못 찾은 것

- **불 붙인 화톳불 목록**: 이벤트 플래그(`RegisterBonfire` 의 bonfire_flag +0..7)는 전부 0, 불 붙이기 전후 ID 검색 차이 없음. → `bonfires.py` 가 쉴 때마다 마지막 화톳불을 쌓아 대신한다.
- 메모리 칸 뜻은 사용자가 화면을 확인하기 전엔 단정하지 않는다 — ChrClassWarp+0x19 를 처음엔 워프로 잘못 읽었다 (`warp_re.py` 로 찾음).
