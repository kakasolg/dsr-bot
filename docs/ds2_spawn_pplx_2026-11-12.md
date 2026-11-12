# DS2 SotFS 몹 소환 — Perplexity 조사 (2026-11-12)

MoKa 요청: "다크소울2 스콜라에선 되는지 퍼플렉시티에게 조사 시켜봐". Perplexity 답(소스 68개)을 요약했다. 아래는 Perplexity가 공개 문서·소스를
읽고 한 말이고, 우리가 게임이나 코드로 확인한 것은 없다.

## 1. 실행 중 소환
- 엘든링 Hexinton "Spawn Debug Character"처럼 chr/param/think/좌표를 주면 바로 만드는 공개 CE 기능은 **확인되지 않음**
  (Boblord 테이블 = Atvaark → Lord Radai 계열, 1.03 / Calib 2.02 대상; 적 생성 스크립트는 못 찾음).
- 대신 **NPC Companions DLL**(공개 소스)이 실행 중 캐릭터를 부른다. 방식:
  - 맵에 전용 generator를 미리 넣어 둔다
  - 실행 중에 그 generator의 GeneratorRegistParam(적 정의 + AI/logic id)을 바꾼다
  - 이벤트 플래그로 켜고 끈다
  - 위치를 옮긴다
  - 캐릭터·AI 리소스는 게임의 리소스 로더로 직접 읽는다 (`resources.h`: +0x412970 / +0x412DF0, 그 exe 기준)
  - 즉 "CreateEnemy(chr, param, think, xyz)" 같은 함수가 아니라, 준비된 generator를 돌려쓰는 방식이다.

## 2. 맵 파일(param) 수정
- DS2는 MSB 캐릭터 대신 맵별 param 3개로 몹을 둔다:
  - `generatorlocation_<map>` 행 G: 위치·회전
  - `generatorparam_<map>` 행 G (같은 id): GeneratorRegistParam=R, AIThinkID, 등장·사망·적대 이벤트, AggroGroup
  - `generatorregistparam_<map>` 행 R: EnemyParamID, LogicParamID, DefaultLogicParamID, SpawnState, DrawGroup
- 한 마리 추가: 보통 몹 행을 복사해 새 G로 location+param을 만들고 위치를 바꾼다. R은 그대로 써도 된다.
  복사한 이벤트 참조는 원본과 조건을 공유할 수 있다. 게임을 껐다 켜야 반영된다.
- 도구: DSMapStudio(DS2 generator를 맵 개체로 보여 줌), Smithbox, Mod Engine for DS2(로딩만), 랜덤마이저(1.0.3 기준).
- 제한:
  - 메모리 한계가 있다. 랜덤마이저는 구역당 적 종류 8–12를 쓰고 heap fix를 넣는다. 고정된 개체 수 상한은 확인되지 않았다.
  - 보통 몹은 약 12번 죽이면 다시 안 나온다. EnemyParam Spawn Limit 12 → 255로 바꾼 모드가 있다.
  - 새로 넣은 몹이 그 카운터를 따로 갖는지는 확인되지 않았다.

## DSR(지금 게임)과 비교
- DSR은 MSB에 캐릭터를 직접 추가한다. soulstruct로 복사하고 저장한 뒤 다시 읽는 것까지 오프라인에서 통과했다. 게임 안에서는 아직 확인하지 않았다.
- DS2는 param 3개를 맞춰야 하고, 실행 중 소환은 DLL 방식의 선례만 있다.
