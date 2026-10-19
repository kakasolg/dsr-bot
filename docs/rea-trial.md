# REA (Reverse Engineer Anything) 시험 — [win] 지시문

MoKa 2026-10-16: "Win local에게 R E Anything 으로 테스트 해 보라는 지시문 내려줘. 뭔지는 보자."
ROADMAP `rea-trial`. 목적은 **써 보고 판단할 자료를 모으는 것**. 봇에 붙이지 않는다.

## 미리 알 것

- REA = 코딩 에이전트(Claude Code 등)에 역분석 도구를 MCP로 붙여 주는 오픈소스 (github.com/morluto/rea, npm `rea-agents`, MIT).
  네이티브 exe는 REA 자체가 아니라 **Ghidra / IDA / Hopper를 따로 설치해서** 붙인다. 공식 README: Windows의 Ghidra 지원은 **"experimental"**.
- 블로그에 돌던 "재구성 의무 원장 · Coverage Score · 120개 이상 툴"은 공식 페이지에 없다 ([cloud] 10-16 확인). 시뮬레이션 기능도 없다.
- 판마다 호환이 깨진 적이 있다는 글이 있다 → **버전을 고정**하고 적어 둔다.
- 분석은 로컬에서 돌지만 결과는 에이전트(모델)로 간다.

## 지킬 것

1. **게임을 끄고**, 게임 폴더 밖에 `DarkSoulsRemastered.exe` **복사본**을 만들어 그걸로만 분석한다. Steam 폴더의 원본은 건드리지 않는다.
2. exe, 디컴파일한 코드, 덤프는 **커밋하지 않는다** (공개 저장소 · 저작권). 커밋하는 건 이 문서의 결과 글뿐.
3. REA가 게임 메모리에 붙거나 실행 중인 게임을 건드리는 기능(디버거 · 런타임 추적)은 이번에 **쓰지 않는다**. 정적 분석만.
4. 시간 상한은 **전체 2시간**. Ghidra나 REA 설치가 30분 안에 안 되면 거기서 멈추고 무엇이 막혔는지만 적는다.

## 순서

**0. 준비**
- `node -v` → 22 이상인지. 아니면 Node 22 LTS 설치.
- Ghidra가 없으면 설치 (JDK 21 필요). 이미 IDA가 있으면 IDA도 된다. 어느 쪽을 썼는지 적는다.

**1. 설치**
- `npm view rea-agents version` 으로 지금 버전을 보고, 그 버전으로 고정해서 설치: `npm install --global rea-agents@<버전>`.
- `rea-agents setup` (또는 `npx rea-agents@<버전> setup`). **어떤 설정 파일을 바꿨는지** 출력에서 적는다.
- Claude Code를 다시 열고 REA 툴이 보이는지, 몇 개인지 확인.

**2. 시험 A — 열리기는 하나** (10분)
- 복사한 exe를 대상으로: 형식(PE64), import 목록, 문자열 몇 개. 걸린 시간 (Ghidra 첫 분석은 오래 걸릴 수 있다 — 시간 적기).

**3. 시험 B — 답을 아는 문제** (핵심, 40분)
우리가 이미 정답을 아는 것으로 REA의 정확도를 본다. 에이전트에게 이렇게 묻는다:
> 이 exe에서 바이트 패턴 `80 3D ? ? ? ? 00 48 8B 8F ? ? ? ? 0F B6 DB` 를 찾고, `80 3D` 가 비교하는 전역 바이트 배열의 주소를 구해라.
> 그 배열(디버그 플래그 배열)의 각 바이트를 읽는 함수들을 찾아, 바이트 위치마다 그것이 무엇을 하는지 증거(호출 위치, 디컴파일 줄)와 함께 표로 만들어라.

정답 (`dsr_telemetry.py` · DSR-Gadget · 실측):

| 위치 | 뜻 | 근거 |
|---|---|---|
| +0x0 | PlayerNoDead (안 죽음) | 실측 |
| +0x1 | PlayerExterminate (즉사) | 실측 (`kill_player`) |
| +0x6 | PlayerHide (적이 못 봄) | DSR-Gadget, legacy 사용 |
| +0x9 | AllNoDamage (피해 없음) | DSR-Gadget |
| +0xB | AllNoAttack (아무도 공격 안 함) | DSR-Gadget, legacy 사용 |

적을 것: 주소를 맞혔나, 다섯 개 중 몇 개를 맞혔나, 틀린 것·지어낸 것(증거 없이 단정)이 있었나, 우리가 모르는 위치를 새로 알려 줬나.

**4. 시험 C — 모르는 문제** (선택, 40분)
`data/gamefiles/combat.json` 의 공격 위력(AtkParam `PhysicalAttackPower`)이 플레이어가 실제로 받는 피해로 바뀌는 **피해 계산식**을 찾게 한다.
> 적 공격이 플레이어에게 맞을 때 피해를 계산하는 함수를 찾아, 공격력 · 방어력 · 막기 감소율이 어떻게 섞이는지 식으로 써라. 근거 주소를 함께.
답은 모르니 **확인 방법**만 적어 둔다: 할로우 254010 공격 위력 177 vs 우리 기록의 실제 피해(`data/samples` 로그)로 식이 맞는지 [cloud]가 나중에 대조.

**5. (선택) TAE**
REA가 `chr/c2540.anibnd.dcx` 같은 게임 데이터 파일을 다루는지 한 번만 시도. 못 하면 "못 함" 한 줄.

## 결과 적기 (이 문서 아래 "결과"에, 그리고 커밋)

- 버전, 사용한 디스어셈블러, 설치에 걸린 시간, 바뀐 설정 파일
- 시험 A · B · C 각각: 걸린 시간, 결과, 맞은 것 / 틀린 것 / 지어낸 것
- 쓴 토큰이나 비용 (보이면)
- [win]의 한 줄 의견: 계속 쓸 만한가, 어디에
- ROADMAP `rea-trial` 줄을 `cloud | verify`(또는 막혔으면 `blocked`)로 바꾸고 push → [cloud]가 읽고 판단 정리

## 결과

2026-10-16 [win] 12:37–13:50 (73분). **시험 A 실패 — Ghidra 첫 분석이 60분 안에 안 끝남. 시험 B · C · TAE 못 함.**

**설치 (12:37–12:40 + setup, 약 15분 — 문제 없음)**
- rea-agents **6.5.0** (npm 2026-10-14 게시, 설치 스크립트 없음, 178 패키지). 디스어셈블러: **Ghidra 12.1.4** (NSA GitHub 릴리스, SHA-256
  `ddac49f9…d4db` 릴리스 노트와 같음) + **Temurin JDK 21.0.12** (winget). 이 PC의 기존 Java는 17이라 Ghidra에 안 맞았음.
- `rea doctor`: Ghidra 9개 점검 모두 통과 (win32/x64, headless, native decompiler, JDK 21, Job Object 격리).
- `rea setup --client claude_code`: 바뀐 파일 `C:\Users\moka\.claude.json` (MCP 서버 `rea` 추가, 백업 `.claude.json.rea.backup`)
  + `C:\Users\moka\.claude\skills\reverse-engineer-anything` (스킬). Claude는 자기 설정이라 못 바꿔서(자동 모드 거부) MoKa가 직접 실행.
  주의: setup은 실행한 셸의 `GHIDRA_INSTALL_DIR` · `JAVA_HOME`만 MCP 등록에 적음 — MoKa 셸엔 없어서 빠짐 → 사용자 환경 변수(setx)로 넣어야 함.
- CLI 명령 153개. [cloud]가 "공식 페이지에 없다"고 한 `build-reconstruction-obligation-ledger` · `evaluate-reconstruction-coverage`는 **6.5.0 CLI에 있음**.
  시뮬레이션 명령은 없음. Claude Code 재시작 전이라 MCP 툴 수는 못 셈 (CLI로 대신 시험).

**시험 A — 열리기는 하나**
- exe 복사본 `D:\tools\rea-target\` (원본과 SHA-256 같음, 게임 꺼진 상태). `rea analyze <exe> --provider ghidra`.
- 1회: 기본 상한 330 s에서 `provider_timeout` (operation `list_documents`). README대로 `REA_GHIDRA_STARTUP_TIMEOUT_MS=3600000` →
  2회: **60분 뒤 같은 `provider_timeout`**. Ghidra는 PE64 `x86:LE:64:default:windows`로 불러와 import(d3d11, dinput8, dxgi, XInput1_3, ws2_32 …)까지
  잡았지만 자동 분석 단계에서 안 끝남. 로그: 예외 처리 표 해석 실패 2087번(`EHDataTypeUtilities`), `CreateEHFuncInfo` 375번, 디컴파일
  "Unable to read bytes" 193번, "body contains referring thunk" — 난독화된 코드에서 보이는 꼴. REA는 분석이 끝나야 답을 주므로 형식 · import · 문자열 결과 0.
- 남긴 것 없음: REA 임시 폴더(`%TEMP%\rea-ghidra-*`)는 스스로 지움, Ghidra 프로세스 종료됨.

**시험 B를 미리 대 본 것 (REA 아님, Python으로 exe 바이트 직접)**
- 패턴 `80 3D ? ? ? ? 00 48 8B 8F ? ? ? ? 0F B6 DB` — **파일에 0번**. 앞부분 `80 3D ? ? ? ? 00`은 1632번, 뒷부분 `48 8B 8F ? ? ? ? 0F B6 DB`는 0번.
  `dsr_telemetry.py`는 실행 중 메모리에서 찾음 → 이 코드는 **디스크에선 암호화돼 있다가 실행 중에 풀림**(Arxan 계열 보호로 추정; `.text` 두 개,
  첫 `.text` 엔트로피 6.90). 그러니 시험 B는 정적 분석으로는 원래 못 푸는 문제 — REA가 끝까지 돌았다면 "못 찾음"이라 했는지 지어냈는지가 시험이 됐을 것.

**재시작 뒤 MCP 확인 (2026-10-16 [win])**: MoKa가 `setx GHIDRA_INSTALL_DIR` · `JAVA_HOME` 후 Claude Code 재시작 → `rea` MCP 툴 약 230개 보임,
`rea doctor` Ghidra 점검 모두 healthy. Ghidra 없이 도는 `inspect_pe_resources`는 몇 초에 끝남: PE32+ x86-64, 리소스 122개(문자열 표 99 · 아이콘 그룹 11 ·
`DATA` 10), coverage complete. Ghidra를 쓰는 툴(`open_binary` · `search_bytes`)은 위 1시간+ 분석에 같이 걸리므로 다시 안 돌림.

**토큰 · 비용**: REA CLI 자체는 모델 호출 없음. 이 세션 토큰 외 추가 비용 없음.

**[win] 의견**: 이 exe에는 쓸 만하지 않음 — 정적으로는 보호된 코드가 안 보이고, Ghidra 전체 분석이 1시간 넘게 걸림. 다시 해 본다면
(1) Ghidra를 REA 밖에서 headless로 끝까지 한 번 분석해 프로젝트를 만들고 REA에 그 DB를 주거나, (2) 실행 중 덤프(게임 메모리 — 이번 규칙상 금지,
MoKa 결정)가 있어야 시험 B가 의미 있음. 지금의 메모리 패턴 + DSR-Gadget 방식이 더 빠름.

**[cloud] 판단 (2026-10-16)**
- 바로잡기: 의무 원장(`build-reconstruction-obligation-ledger`) · 커버리지 평가 명령은 6.5.0에 **있다** — 10-16 [cloud]가 README만 보고 "없다"고 한 건 틀림.
- 막힌 이유는 REA가 아니라 대상: DSR exe는 디스크에서 코드가 암호화돼 있어(ChrDbg 패턴 0번) 정적 분석으로는 핵심 코드를 볼 수 없다.
  Ghidra를 밖에서 끝까지 돌려도(1안) 암호화된 부분은 그대로라 시험 B · C는 여전히 못 푼다. 2안(실행 중 메모리 덤프)은 게임 메모리를
  통째로 읽어 파일로 남기는 일 — 오프라인 전용 규칙과 저작권(덤프는 커밋 금지) 아래서 MoKa가 정할 일.
- 제안: **중단(`[-]`)**. 피해 계산식처럼 꼭 필요한 식이 생기면, 덤프 대신 우리 기록(공격 위력 combat.json vs 실제 받은 피해)으로 맞춰 본다.
  REA · Ghidra 설치는 지워도 되고 둬도 된다(다른 보호 없는 프로그램엔 쓸 수 있음).

## 2차 — 메모리 덤프로 끝까지 (MoKa 2026-10-16: "끝까지 가자. 20년도 넘은 게임에 너무 민감하게 할 필요 없어.")

1차의 "지킬 것" 중 3번(게임 메모리 금지)은 이번엔 풀림. 바뀐 것만:
- 게임 메모리를 **읽기만** 한다 (`exe_dump.py`는 쓰기 없음). 게임은 오프라인(Steam 오프라인 모드)으로, 봇 실행 중이 아닐 때.
- 덤프(`.exe`)는 여전히 **커밋하지 않는다** — 수십 MB 바이너리라 저장소에 둘 것이 아님. `data/dump/`는 git이 무시함.
- 시간 상한 3시간 (Ghidra 전체 분석을 밤새 돌리는 건 따로, 아래 2-b).

**1. 덤프** (10분)
- 게임을 켜고 **세이브를 불러 게임 안까지** 들어간다 (타이틀보다 실행된 코드가 많음).
- `python exe_dump.py --out D:\tools\rea-target\dsr.dump.exe`
- 확인: 마지막 줄 `OK` = `dsr_telemetry.AOBS` 6개가 덤프 안에서 **모두 정확히 1번**. 못 읽은 페이지 수도 적기.
  1이 아닌 게 있으면 그 이름과 수를 적고 2번으로 넘어감 (보호가 실행 뒤 다시 암호화하는 함수가 있을 수 있음 — 그럼 게임 안에서 조금 움직인 뒤 한 번 더 떠서 비교).

**2. Ghidra에 넣기 — 전체 자동 분석을 하지 않는다**
1차는 자동 분석이 1시간 넘게 안 끝나서 막혔다. 이번엔:
- a. `rea analyze --help` · `rea --help`에서 **분석 없이 열기 / 기존 Ghidra 프로젝트 쓰기 / 분석 시간 한도** 같은 옵션이 있는지 먼저 본다. 있으면 그걸로.
- b. 없으면 Ghidra로 직접: `analyzeHeadless D:\tools\rea-target\proj dsr -import D:\tools\rea-target\dsr.dump.exe -noanalysis`
  (몇 분). 그 뒤 필요한 곳만 분석: Ghidra GUI에서 프로젝트를 열고 주소로 가서 `D`(디스어셈블) · `F`(함수 만들기). REA가 이 프로젝트를 열 수 있으면 REA로 계속,
  못 열면 시험 B는 Ghidra만으로 하고 "REA는 이 경로를 못 씀"이라 적는다.
- c. (선택) 전체 자동 분석은 `analyzeHeadless … -process dsr.dump.exe -analysisTimeoutPerFile 10800` 으로 밤에 따로 돌려 끝나는지만 본다.

**3. 시험 B** — 1차 그대로 (패턴 → ChrDbg 주소 → 바이트 위치별 뜻, 증거와 함께). 이제 패턴이 덤프에 있다.
`exe_dump.py`가 찍은 base와 `dsr_telemetry`가 쓰는 주소가 같은 체계라, 답한 주소를 그대로 대 볼 수 있다. 정답표는 1차 시험 B.

**4. 시험 C** — 1차 그대로 (피해 계산식, 선택).

**5. 결과** — 아래 "2차 결과"에: 덤프(크기, 못 읽은 페이지, AOB 수), 2-a/b/c 중 쓴 길과 걸린 시간, 시험 B 맞힌 수 / 틀린 것 / 지어낸 것, 시험 C.
ROADMAP `rea-trial` → `cloud | verify` 로 바꾸고 push.

## 2차 결과

2026-10-16 [win] 14:38–15:20 (약 40분). **시험 B 5/5 맞힘 + 모르던 위치 10개 이름까지. 시험 C 안 함, TAE 못 함.**

**1. 덤프** — 게임 켜기(키보드로 이어하기) 14:39 → `exe_dump.py --out D:\tools\rea-target\dsr.dump.exe` → 타이틀 → 종료.
- 52,015,104 바이트, 못 읽은 페이지 **0 / 12699**, AOB 6개 **모두 1번** (`OK`). base 0x140000000. sha256 `88d8d84e…e5cf`.
- Steam은 오프라인 설정이지만 켤 때 steam.exe 바깥 연결 2개(80 · 443) 잡힘. 게임은 바깥 연결 0.
- `keys.py quit`가 타이틀 바로 뒤엔 안 먹음 — 3 s 뒤 한 번 더 보내니 꺼짐.

**2. Ghidra에 넣기 — 2-a로 됨 (REA 안에서, 2분 41초)**
- REA에 "분석 없이 열기"는 없음. 대신 **`REA_GHIDRA_DISABLED_ANALYZERS`** (쉼표로 이름, 최대 32개, 모르는 이름이면 바로 멈춤)로 1차에서 오류를 쏟던
  분석기를 끔: Windows x86 PE Exception Handling · PE RTTI Analyzer · Decompiler Switch Analysis · Call Convention ID · Function ID · Demangler Microsoft ·
  Non-Returning Functions - Discovered · Create Address Tables · Embedded Media · Apply Data Archives · Shared Return Calls · x86 Constant Reference Analyzer ·
  PDB Universal · Stack · ASCII Strings. 그 상태로 `rea analyze` = **2분 41초**, 함수 97,863 · 문자열 16,453 · 섹션 11.
- REA CLI는 부를 때마다 Ghidra를 새로 띄움(덤프 기준 한 번에 약 2.5–3분). 그래서 질문은 4개씩 병렬로 보냄 (RAM 2 GB/개).
  MCP 서버는 사용자 환경 변수로 뜨므로, MCP로 같은 걸 하려면 `REA_GHIDRA_DISABLED_ANALYZERS`도 setx로 넣고 재시작해야 함 (이번엔 CLI만).
- 2-b(Ghidra 직접) · 2-c(밤새 전체 분석)는 필요 없어서 안 함.

**3. 시험 B — 5/5, 지어낸 것 0**
- `search-bytes` 패턴 → **1개, 0x1403358c1** (`FUN_140335890` 안) — 우리가 덤프에서 직접 계산한 값과 같음.
- `instructions` → `CMP byte ptr [0x141c77e59], 0x0` → 배열 **0x141c77e59** — 맞음 (같은 체계: `dsr_telemetry`가 실행 중 찾는 주소).
- `xrefs` 바이트 16개 각각 → 1–5곳씩. `0x1403744xx`–`0x1403748xx`에 모든 바이트가 몰림 → `decompile` 하니 게임 안 디버그 메뉴 **`L"CHR DBG"`**를 만드는 함수,
  바이트마다 이름표를 달아 등록 (`FUN_140469010(menu, &label, &DAT_141c77e59+n, 1)`). 이름표는 `read-bytes`(UTF-16)로 읽음:

| 위치 | 게임 속 이름표 | 정답표 |
|---|---|---|
| +0x0 | Player No Dead | ✔ PlayerNoDead |
| +0x1 | Player Exterminate | ✔ PlayerExterminate |
| +0x2 | All No Stamina Consume | (새로 앎) |
| +0x3 | All No MP Consume | (새로 앎) |
| +0x4 | All No Arrow Consume | (새로 앎) |
| +0x5 | All No MagicQty Consume | (새로 앎) |
| +0x6 | Player Hide | ✔ PlayerHide |
| +0x7 | Player Silence | (새로 앎) |
| +0x8 | All No Dead | (새로 앎) |
| +0x9 | All No Damage | ✔ AllNoDamage |
| +0xA | All No Hit | (새로 앎) |
| +0xB | All No Attack | ✔ AllNoAttack |
| +0xC | All No Move | (새로 앎) |
| +0xD | All No Update Ai | (새로 앎) |
| +0xE | — (이 함수에선 이름표 못 찾음, xref 1곳 0x140375465) | |
| +0xF | (All's quiet mode) 全員省略モード | (새로 앎) |

- 근거가 게임 자체의 메뉴 문자열이라 추측이 없음. 같은 함수 위쪽은 이 바이트들을 다른 함수(`FUN_14018c4f0` …)로 고쳐 쓰는 블록(조건 `DAT_141c77e6c`) — 뜻은 안 봄.
- 쓰는 곳 디컴파일도 받아 둠(+0 `FUN_140335890` 26줄, +1 `0x1402fc4a0` 188줄, +6 `0x1403258d4` 47줄, +9 `0x140322925` 48줄, +B `0x140392f81` · `0x14039342d`) — 표는 메뉴 이름표만으로 채움.
- 덤프 · 디컴파일 결과는 `D:\tools\rea-target\` · 스크래치에만, 커밋 안 함.

**4. 시험 C — 안 함.** 피해 계산 함수로 들어갈 실마리(문자열 · 알려진 패턴)가 없어, 한 번에 3분 걸리는 CLI 질문을 수십 번 해야 함. 하려면 MCP 세션
(한 번 열면 Ghidra 유지)으로, 또는 `FUN_140322925`(+9 AllNoDamage를 읽는 곳 = 피해 처리 근처일 가능성)에서 시작하는 게 빠름.

**5. TAE** — `rea analyze c2540.anibnd.dcx` → `unsupported binary format` (1 s). 못 함.

**[win] 의견**: 보호된 exe는 **덤프 + 분석기 끄기**면 REA가 3분 안에 열리고, 답을 아는 문제는 증거와 함께 다 맞힘. 디버그 메뉴 이름표 같은 게임 속
문자열을 따라가면 강함. 약점: CLI는 질문마다 Ghidra 재시작(3분), 게임 데이터 파일(TAE 등)은 못 다룸. 쓸 곳 = 메모리 값의 뜻 찾기(새 디버그 플래그 ·
구조체 필드). 이번에 나온 +0x8 All No Dead · +0xA All No Hit · +0xC All No Move · +0xD All No Update Ai는 오프라인 시험(적 멈추기 등)에 바로 쓸 만함.

**[cloud] 판단 (2026-10-16, 2차)**
- 결론: **쓸 만함, 단 용도는 좁게** — "메모리 값의 뜻 찾기"(디버그 플래그, 구조체 필드). 덤프(`exe_dump.py`) + `REA_GHIDRA_DISABLED_ANALYZERS`가 이 게임에서의 사용법.
  답을 아는 문제 5/5, 근거는 게임 자체의 메뉴 문자열이라 지어낸 것 0. 1차 실패는 REA가 아니라 디스크 exe의 암호화 때문이었음.
- 반영: `dsr_telemetry.DSRTelemetry.DBG_*` 에 16바이트 중 15개 이름 (게임 메뉴 이름표 그대로; legacy가 쓰던 `0xB` = `DBG_ALL_NO_ATTACK`).
  `kill_player`도 상수를 씀. 쓰기는 여전히 오프라인 전용.
- 못 한 것과 다음 후보 (지금 항목은 닫음 — 필요해질 때 새 항목으로):
  - 시험 C(피해 계산식): MCP 세션(Ghidra 유지)으로 `FUN_140322925`(+0x9 AllNoDamage를 읽는 곳)에서 시작. 또는 Cheat Engine "이 주소에 쓰는 코드"를
    플레이어 HP에 걸고 한 대 맞기 — 피해 함수 주소가 바로 나옴. 결과는 combat.json 위력 vs 실제 피해로 [cloud]가 대조.
  - TAE는 REA 밖: soulstruct엔 TAE 읽기가 없으니 [cloud]가 읽는 코드를 짜고, [win]이 DSAnimStudio로 c2540 공격 한두 개 타이밍을 정답표로.
  - 적 AI: soulstruct에 DSR AI Lua 디컴파일러(`DSLuaDecompiler.exe`, Windows)가 들어 있음 → 적의 공격 고르는 규칙.
  - `All No Update Ai`(+0xD) · `All No Move`(+0xC): 적을 세워 두고 재는 오프라인 측정(사거리 · 타이밍)에 바로 쓸 수 있음.

## 3차 — 애니 재생 시간 필드, MCP 세션으로 ([cloud] 2026-10-19, MoKa: "애니 재생 시간 필드부터 MCP 세션 방식으로")

목적: `docs/design-player-options.md` "Known blind spots" 1 — **같은 ID 재시작**. 지금은 애니 ID(`[ChrIns+0x68]+0x48 → +0x80`)만 읽어서,
할로우가 3000을 두 번 이어 휘두르면 하나로 보이고 `restart_possible`로 버린다(probe 3 · options pilot에서 7/100). 게임이 들고 있는
**애니 재생 시간**을 읽으면 두 번째 3000이 보이고 "age"가 게임 자신의 값이 된다.

### 2차보다 효율을 올리는 세 가지 (10-19 [cloud]가 REA 문서 · 스킬 가이드에서 확인한 것)

1. **CLI 대신 MCP 세션.** CLI는 부를 때마다 별도 프로세스라 Ghidra를 새로 띄운다(2차: 질문 하나에 2.5–3분). MCP는 `open_binary` 한 번 →
   같은 세션에서 `search_bytes` · `xrefs` · `procedure_pseudo_code` · `read_bytes` … → 끝에 `close_binary`. 같은 질문을 반복할 땐 CLI의
   `--snapshot <json>` 캐시도 있지만 새 질문엔 소용없다.
2. **맹목 검색 대신 런타임에서 닻을 잡고 시작.** 2차가 강했던 건 패턴 → 주소라는 닻이 있었기 때문이고, 시험 C가 막힌 건 닻이 없었기 때문.
   이번엔 (1) 읽기 전용 Python으로 후보 오프셋을 좁히고 (2) 그 구조체의 vtable(런타임에서 읽은 첫 8바이트)로 REA에서 코드를 찾고
   (3) 다시 게임에서 확인한다.
3. **결과는 이 문서가 원장.** Windows Ghidra P0는 Ghidra DB에 이름 · 주석을 저장하지 못한다(`annotate_native_function` 등 변경 불가).
   함수 주소 · 오프셋 · REA Evidence ID를 아래 표에 남겨 다음 세션이 다시 찾지 않게 한다.

Frida(`start_frida_session` 등)는 이번에 **안 쓴다** — REA 문서상 검증은 Linux만이고 Windows는 미확인, 게임 프로세스에 코드를 넣는 일이라
읽기 전용 범위를 넘는다(쓰려면 MoKa 결정). Cheat Engine "이 주소에 쓰는 코드"도 디버거를 붙이는 일이라 같은 이유로 이번엔 빼 둔다.

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
