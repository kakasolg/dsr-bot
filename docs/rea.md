# REA — 이 프로젝트에서 쓰는 법 · 결과 원장

ROADMAP `rea-anim-time`. 1 · 2차 시험 기록(설치, 덤프, 시험 B 5/5)은 [`rea-trial.md`](rea-trial.md). 여기는 **지금 쓰는 방법**,
**찾은 것의 원장**, **진행 중인 지시문**만 둔다.

## 쓰는 법 (2026-10-19, REA 6.5.0 · Ghidra 12.1.4 · Windows)

- 대상은 디스크 exe가 아니라 **실행 중 덤프** (`exe_dump.py`): 디스크 exe는 코드가 암호화돼 있다 (rea-trial 1차).
- Ghidra 자동 분석은 `REA_GHIDRA_DISABLED_ANALYZERS`로 15개를 끄면 약 3분 (rea-trial 2차). MCP 서버는 **사용자 환경 변수**로 뜨므로 `setx` 후 Claude Code 재시작.
1. **CLI 대신 MCP 세션.** CLI는 명령마다 별도 프로세스라 Ghidra를 새로 띄운다(2차: 질문 하나 2.5–3분). MCP는 `open_binary` 한 번 →
   같은 세션에서 `search_bytes` · `xrefs` · `procedure_pseudo_code` · `read_bytes` … → 끝에 `close_binary`. 같은 질문 반복엔 CLI `--snapshot <json>` 캐시.
2. **런타임 닻에서 시작.** 2차가 강했던 건 패턴 → 주소라는 닻이 있었기 때문이고, 시험 C(피해 계산식)가 막힌 건 닻이 없었기 때문.
   읽기 전용 Python으로 후보(오프셋 · 객체 vtable · 아는 주소)를 먼저 잡고, REA로 그 코드를 읽고, 다시 게임에서 확인한다.
3. **이 문서가 원장.** Windows Ghidra P0는 Ghidra DB에 이름 · 주석을 저장하지 못한다. 함수 주소 · 오프셋 · Evidence ID는 아래 "원장"에.
- 못 하는 것: 게임 데이터 파일(TAE 등 — `unsupported binary format`, TAE는 `tae_extract.py`). Frida는 REA 문서상 검증이 Linux만, Windows 미확인 ·
  게임 프로세스에 코드를 넣는 일이라 쓰려면 MoKa 결정. Cheat Engine "쓰는 코드 찾기"도 디버거를 붙이므로 같음.
- 결과는 CLAUDE.md "How to state results"대로: 후보 / 정적으로 읽음(Evidence ID) / 게임에서 확인(n/n)을 나눠 적는다.

## 원장 (찾은 것)

| 무엇 | 주소 · 오프셋 | 근거 | 상태 |
|---|---|---|---|
| ChrDbg 플래그 배열 16바이트 이름 | `0x141c77e59` +0x0…+0xF | 게임 디버그 메뉴 `CHR DBG` 이름표 (rea-trial 2차 표) | 정적으로 읽음, 15개 `dsr_telemetry.DBG_*`; +0xA AllNoHit 효과는 tae-verify probe 4 |
| CHR DBG 메뉴를 만드는 함수 | `0x1403744xx`–`0x1403748xx` | 2차 decompile | 정적으로 읽음 |
| AllNoDamage(+0x9)를 읽는 곳 | `FUN_140322925` | 2차 xrefs | 정적으로 읽음 — 피해 계산식(시험 C)의 출발점 후보 |
| 애니 재생 시간 | ? | 3차 | 아직 |

## 3차 지시문 — 애니 재생 시간 필드, MCP 세션으로 ([cloud] 2026-10-19, MoKa: "애니 재생 시간 필드부터 MCP 세션 방식으로")

목적: `docs/design-player-options.md` "Known blind spots" 1 — **같은 ID 재시작**. 지금은 애니 ID(`[ChrIns+0x68]+0x48 → +0x80`)만 읽어서,
할로우가 3000을 두 번 이어 휘두르면 하나로 보이고 `restart_possible`로 버린다(probe 3 · options pilot에서 7/100). 게임이 들고 있는
**애니 재생 시간**을 읽으면 두 번째 3000이 보이고 "age"가 게임 자신의 값이 된다.

방법은 위 "쓰는 법" 1–3 그대로 (MCP 세션 · 런타임 닻 · 이 문서의 원장). Frida · Cheat Engine은 쓰지 않는다. 찾은 것은 "원장" 표에도 한 줄.

### 지킬 것
- 게임 메모리는 **읽기만**. ChrDbg 플래그 쓰기도 이번엔 필요 없음. Steam 오프라인, 봇 실행 중이 아닐 때.
- 덤프 · 디컴파일 결과는 커밋하지 않는다(`D:\tools\rea-target\` · 스크래치에만). 커밋하는 건 이 문서의 결과 글과 `experiments/` 스크립트.
- 시간 상한 **2.5시간**. 아래 각 단계의 멈춤 조건을 지킨다.

### 0. 준비 (15분)
- 사용자 환경 변수 두 개를 넣고 Claude Code 재시작 (MCP 서버는 사용자 환경 변수로 뜬다 — 2차 메모):
  `setx REA_GHIDRA_DISABLED_ANALYZERS "Windows x86 PE Exception Handling,PE RTTI Analyzer,Decompiler Switch Analysis,Call Convention ID,Function ID,Demangler Microsoft,Non-Returning Functions - Discovered,Create Address Tables,Embedded Media,Apply Data Archives,Shared Return Calls,x86 Constant Reference Analyzer,PDB Universal,Stack,ASCII Strings"`
  (2차 결과 2.의 15개 그대로 — 2차에 쓴 문자열과 한 글자라도 다르면 REA가 바로 멈추니, 2차 셸 기록이 있으면 그걸 쓴다) ·
  `setx REA_GHIDRA_STARTUP_TIMEOUT_MS 900000`.
  Claude는 자기 설정을 못 바꾸므로 MoKa가 실행할 수 있다.
- 재시작 뒤 `binary_session` `{}` → `result.tool_availability`에서 `open_binary` · `search_bytes` · `xrefs` · `read_bytes` ·
  `procedure_pseudo_code` · `procedure_callers`가 available인지. 아니면 reason · remediation을 적고 멈춘다.
- 덤프: 지금 `DarkSoulsRemastered.exe`의 SHA-256이 10-16과 같으면(게임 업데이트 없음) 2차 덤프 `D:\tools\rea-target\dsr.dump.exe`
  (sha256 `88d8d84e…e5cf`)를 그대로 쓴다. 다르면 `python exe_dump.py --out …`로 새로 뜨고 `OK`(AOB 6개 모두 1번) 확인.
- `open_binary`(덤프, provider ghidra) **한 번**. 걸린 시간을 적는다(2차 CLI `rea analyze` 2분 41초와 비교). 10분 넘으면 멈춘다.

### 1. 런타임 후보 찾기 — 읽기 전용 Python (30분)
`experiments/anim_time_scan.py`를 새로 짠다(봇은 import 안 함). 플레이어 ChrIns에서:
- 애니 상태 구조체 `A = [[ChrIns+0x68]+0x48]`의 `+0x000…+0x400`을 약 60 Hz로 읽어 float32 / int32로 jsonl에 기록. 같은 줄에 `A+0x80`
  (애니 ID)과 QPC 시각. `A`의 첫 8바이트(vtable 후보, base 상대값)도 한 번 적는다. 선택: ChrIns 자체 `+0x000…+0x1000`.
- 동작(`control.Pad`): 서 있기 5 s → 구르기 1 → 서 있기 3 s → 약공 1 → 서 있기 3 s → **구르기 2번 연속**(같은 ID 재시작) → 서 있기.
- 후보 조건: (a) 애니 ID가 바뀔 때 0 근처로 돌아감, (b) 애니 동안 기울기 ≈ 1.0 (게임 시간 / 실제 시간; 30 fps 계단 가능),
  (c) **같은 ID 연속 재시작에서도 0으로 돌아감** — 이게 핵심. 덤으로 "애니 길이" 후보(애니 동안 상수, 애니마다 다름).
- 적을 것: 후보 표(오프셋 · 형식 · 기울기 · ID 변경 시 리셋 n/n · 같은 ID 재시작 리셋 n/n · 길이 후보면 그 값).
- 후보가 0개면 시간 값이 이 구조체 밖(예: 애니 상태가 가리키는 다른 객체)에 있다는 뜻 → 2에서 vtable로 시작해 찾는다.

### 2. REA로 확인 — 한 MCP 세션 안에서 (60분)
- a. **vtable 닻**: 1에서 읽은 `A`의 vtable 주소를 덤프에서 `read_bytes` → 메서드 포인터 목록 → 각 메서드를 `procedure_pseudo_code`.
  "필드 X에 dt를 더함", "X = 0", "새 애니로 바꿀 때 부르는 경로"를 찾는다. 1에서 후보가 있으면 그 오프셋을 쓰는 줄부터.
- b. 같은 ID 재시작이 **리셋 경로를 지나는지**: 애니를 정하는 함수에 "이전 ID와 같으면 건너뜀" 같은 비교가 있는지. 있으면 이 필드로도 재시작이
  안 보일 수 있다는 뜻 — 그대로 적는다.
- c. (닻이 안 잡힐 때만) `search_strings`로 애니 · TAE 관련 문자열(`TimeAct`, `hkb`, `Anim` …) → `xrefs` → 디컴파일.
- 결론마다 **관찰 / 추론 / 모름**을 나누고 REA Evidence ID를 단다. 60분에 닻이 하나도 안 잡히면 멈추고 무엇을 해 봤는지 적는다.

### 3. 게임에서 다시 확인 (20분)
- 플레이어: 같은 ID 구르기 연속 재시작 **3/3** 리셋.
- 적: options pilot 세이브(`backup-20261016-234951-options-pilot-ready-A-only`, 할로우 A만)에서 할로우의 같은 필드(EnemyIns도 같은 ChrIns 구조)를
  읽는다. 3000 **5번 이상**에서 시작값 ≈ 0, 끝값 ≈ `data/gamefiles/tae.json`의 c2540 3000 길이(±0.05 s), 이어 휘두른 3000이 있으면 리셋되는지.
- 이 단계를 통과하지 못하면 "후보"로만 적는다(확인됐다고 쓰지 않는다 — CLAUDE.md "How to state results").

### 4. 결과 (아래 "3차 결과"에) · ROADMAP
- 0의 `open_binary` 시간 · 질문 수 · 총 시간(2차 CLI 방식과 비교 — MCP 세션이 실제로 얼마나 빨랐나).
- 1의 후보 표, 2의 함수 주소 · 오프셋 · Evidence ID 표, 3의 n/n.
- [win] 한 줄 의견: MCP 세션 방식이 다음 질문(시험 C 피해 계산식 · 3000 판정 끝)에도 쓸 만한가.
- 확인되면 [cloud]가 `dsr_telemetry`에 재생 시간 읽기를 넣고 `tae_verify.py` · `options_pilot.py`의 `restart_possible`(1.5 × 중앙값 추정)을
  이 값으로 바꾼다 — 그 전엔 바꾸지 않는다.

## 3차 결과

(아직 없음)
