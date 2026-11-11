# 설계안: 지능형 가상 컨트롤러 층 (2026-10-15, VersionSandbox 세션 초안)

**아직 결정 아님** — §12의 질문에 [MoKa]가 답한 뒤 단계 1부터. v2.0 항목이다. v1.0 실행과 규칙은 건드리지 않는다.
관련: ROADMAP 3 `tick-loop` · `route-data` · `batch-ab` · `recording-feedback`, "Later / parked" 1-g 학습 2단계(행동 모방),
[`LAYERS.md`](../LAYERS.md), [`LAYA.md`](../LAYA.md), [`review-v2-2026-10-11.md`](review-v2-2026-10-11.md).

한 줄 요약: 봇을 더 똑똑하게 만드는 대신, **0~1층(패드·기본 동작·경로)을 "의도를 받아 책임지고 완수하거나, 왜 못 했는지 말해 주는 컨트롤러"로** 만든다.
지능은 싼 것부터 쌓는다 — 계약과 결과 → 입력 중재 → 자기 보정 → 성공 예측(첫 AI 자리) → 시범 학습. AI는 맨 뒤다.

---

## 1. 왜

- Jev(9-21 섀도·라이브 훅 → 9-24 오프라인 재생 탈락)와 Laya(10-01 섀도 모드·첫 미세조정 오프라인 85% vs 다수결 57% → 10-02 "Laya 불필요")는
  **"무엇을 할까"** 칸을 맡으려 했다. 상태가 깨끗해지자 그 칸은 규칙으로 풀렸다.
- 시간이 가장 많이 든 곳은 **실행**이다: 스틱을 놓고 0.16 s 뒤 공격, 이동 중 B 유지, 사다리는 0.45 m에서 걸어가며 A(서서 A는 3/3 실패),
  키보드 낙하 종료는 0.15 s 간격. 이 지식은 이미 `control.py`(680줄)·`souls/moves.py`(888줄)·`nav.py`(695줄)에 있지만,
  판단 쪽(`souls/duel.py` 1,881줄, `souls/field.py` 2,245줄)이 실행 세부와 섞여 있다 — LAYA.md 표의 "규칙 함수가 판단과 실행을 한 번에 함".
- 실행을 결과까지 책임지는 층으로 올리면 위층은 "무엇을"만 말하면 된다. `tick-loop`의 "행동 하나 → 입력"에서 그 "행동"이 이 층의 의도가 된다.

## 2. 지금 코드 (읽어서 확인한 것)

| 무엇 | 어디 | 지금 돌려주는 것 |
|---|---|---|
| 패드 | `control.Pad` (vgamepad / ViGEm) | 없음(입력만). `release_stick`으로 0.16 s 규칙 강제, `freeze()`로 한 스레드만 패드를 쓰게 함(긴급 탈출), `PadBusy`(패드 잠금) |
| 공격 | `Moves.light / heavy / kick / kick_combo / backstep_attack / combo` | `Hit(kind, presses, dmg, dead, taken, e_anims, my_anims, skipped, others)` |
| 에스트 | `Moves.drink(safe)` | `{"ok": 개수가 줄었나, "hp", "left", "why"}` — 칸 고른 뒤 안전 재확인 |
| 경로 | `Moves.walk_path` → `nav.follow` | `'arrived' \| 'stopped' \| 'dead' \| goto 실패값` |
| 사다리 | `souls/altar.py` `_ladder_up / _ladder_down` (구간 전용) | 문자열 |
| 종료 후 이어하기 | `Moves.quit_reload` | `{"ok", "how": menu \| byte, "quit_s", "reload_s"}` (P-25: byte는 죽인 적을 되살림) |
| 패드를 쓰는 곳 | 싸움 루프(`F.mv`), `souls/reflex.py`, `camera.CamFollow`, `watch.Escape`(freeze), `keys.py`(메뉴는 키보드) | — |
| 기록 | `ctl.emit()` → `<run>.ctl.jsonl`(P1, QPC 시계, 절대 막지 않음) | — |

결과를 돌려주는 기술은 이미 절반쯤 있다. 형식이 기술마다 다르고, 실패 이유가 없는 곳(`walk_path`의 일부, 사다리)이 있을 뿐이다.

## 3. 단계 1 — 계약과 결과 (기록만, 동작 변경 없음)

기술마다 **전조건**(텔레메트리로 확인), **성공 확인**, **제한 시간**, **실패 이유**를 선언한다. 처음 다섯 개는 이미 성공률 기준이 있는 것이다.

| 기술 | 지금 함수 | 전조건 | 성공 확인 | 실패 이유 후보 | 기존 기준 |
|---|---|---|---|---|---|
| `walk_to` / `walk_path` | `Moves.walk_path` | 경로가 있음, 메뉴 아님, 서 있음 | 마지막 점 tol 안 | `stopped`(호출자) · `dead` · `stuck`(진전 없음) · `timeout` · `fell` | `track_report.py`의 정체 지점 |
| `drink` | `Moves.drink` | 에스트 > 0, `safe(s)` | 개수가 줄었다 | `no_estus` · `slot_failed` · `unsafe_after_select` · `interrupted`(개수 그대로) | 지금 `why` 문자열 그대로 매핑 |
| `climb_ladder` | `altar._ladder_up` 일반화 | 아래쪽 0.6 m 안, 방향 | 높이가 위쪽 근처, 사다리에서 내림 | `mount_failed`(A가 안 먹음) · `interrupted` · `fell` · `timeout` | 걸어가며 A 0.45 m 3/3, 서서 A 0/3 |
| `quit_reload` | `Moves.quit_reload` | 낙하 중 아님(낙하는 `Escape._quit`), 메뉴 닫힘 | 이어하기 끝, 플레이어 로드됨 | `menu_failed`(→byte 대체) · `reload_timeout` | 키보드 메뉴 ESC → 타이틀 2.9 s(`keys.py`, 10-13) |
| `attack(kind)` | `Moves.light / heavy / kick` | 사거리(`weapons.py`), SP ≥ sp_min, 옆 적이 안 휘두름 | `dmg > 0` 또는 적 피격 애니 | `skipped`(기존 값) · `out_of_range` · `no_stamina` · `interrupted`(`taken > 0`) · `whiff` | 골든·기대 테스트 |

공통 결과 형식:

```python
@dataclass
class Result:
    skill: str
    ok: bool
    reason: str | None   # 위 표의 이름. 모르면 "unknown" — 단계 1의 목표는 이 비율을 낮추는 것
    took_ms: int
    evidence: dict       # 판정에 쓴 전·후 값 (개수, 높이, 거리 …)
    detail: dict         # 기존 반환값 그대로 (Hit.as_dict(), drink dict, walk_path 문자열 …)
```

**만드는 법:** 기존 함수를 고치지 않고 감싸는 얇은 층(예: `souls/skills.py`)을 만든다. 감싼 함수는 기존 값을 그대로 돌려주고, 판정만
`ctl.emit("skill", **asdict(result))`로 남긴다 — Laya 섀도 모드와 같은 "기록만". 호출자는 바꾸지 않는다.

**완료 기준:**
- `python tests/duel_golden_test.py` 결정 변화 0, `tests/duel_expect_test.py` 상태 변화 0.
- 새 오프라인 테스트: 가짜 텔레메트리로 다섯 기술의 성공·실패 판정과 `reason`을 확인.
- [win] 다음 N번 실행에서 기술별 성공률과 **실패 중 `reason`이 `unknown`이 아닌 비율 ≥ 95%** (모자라면 표를 보강).

## 4. 단계 2 — 입력 중재 (먼저 재고, 그다음 강제)

지금 패드를 쓰는 곳은 넷 이상이다(§2). `freeze()`는 긴급 탈출용이고, 평소의 충돌(예: 발차기가 0.16 s를 지키는 동안 카메라가 스틱을 건드림)은 규칙이 없다.

1. **재기만:** 패드 쓰기마다 출처(`duel` · `reflex` · `camera` · `escape` · `skill:<이름>`)를 `ctl.emit`으로 남기고,
   50 ms 안에 서로 다른 출처가 같은 입력(스틱·버튼)을 건드린 횟수를 센다. `CamFollow`가 정확히 무엇을 쓰는지(오른쪽 스틱만인지)도 먼저 확인.
2. **충돌이 실제로 있으면** 우선순위로 강제: 탈출(freeze) > 반사 > 기술 실행 > 카메라.

완료 기준: 1의 충돌 수와 그때의 결과(피격·실패)를 실행 보고에 붙인다. 충돌이 0에 가깝고 피해가 없으면 2는 하지 않는다.

## 5. 단계 3 — 자기 보정 (측정 보고만)

손으로 찾은 값(0.16 s, 0.15 s, 0.45 m, 무기 사거리)을 컨트롤러가 직접 잰다. **값을 자동으로 바꾸지는 않는다** — 차이만 보고한다.

- 입력 → 반응 지연: 버튼 누른 시각(`ctl`의 `pc`)부터 내 애니 번호가 바뀐 프레임까지. 피드 스레드 속도(초당 21~25 틱)라 해상도는 약 40~50 ms임을 같이 적는다.
- 동작별 스태미나 소모: `player.sp` 전후.
- 무기별 실제 사거리: `dmg > 0`이었던 공격의 거리 분포 vs `weapons.py`.
- 1-g 학습 1단계 "motion model(6-a layer 2)"이 이미 있다 — 겹치는 측정은 그쪽 것을 쓴다.

## 6. 단계 4 — 성공 예측 (첫 AI 자리, `batch-ab` 뒤)

단계 1이 되면 **모든 기술 시도가 자동으로 정답 데이터가 된다**("이 상태에서 이 기술을 시도해서 됐다/안 됐다"). 사람 라벨이 필요 없다.

1. 먼저 모델 없이: 기술별·구간별(거리·높이·SP·근처 적 수) 성공률 표.
2. 그다음 작은 분류기(로지스틱 회귀나 결정 트리). 보정된 확률이 필요하면 Laya도 후보 — `laya_worker.py` 별도 프로세스 구조를 그대로 쓴다.
3. 위층은 `can(skill, state) → p`를 물을 수 있다. **어떻게 쓸지(예: p < 0.2면 건너뜀)는 이 단계에서 정하지 않는다.**

완료 기준: 예측 확률과 실제 성공률이 구간별로 맞는지(보정 곡선)를 `batch-ab`의 N회 실행으로 확인.

Jev·Laya가 실패한 "무엇을 할까"와 달리 정답이 공짜로 생기고 범위가 좁다. 이 칸이 AI가 맞는 자리라는 판단은 VersionSandbox의 Hotpla 작업
(날짜는 코드, 이름은 OCR, 모델은 극성만)과 같은 결론이다.

## 7. 단계 5 — 시범으로 기술 배우기 ("Later / parked" 1-g 2단계와 같은 것)

`radar_pad.py`·`observe_record.py`가 사람의 패드 입력을 60 Hz로 읽고(읽기 전용), 같은 시각의 텔레메트리가 있다. 경로 녹화도 3개 있다.

1. 시범을 기술 단위로 자른다(사다리 오르기 한 번 등).
2. **학습 없이** 타이밍 통계와 재생부터: 예) A를 누를 때 사다리까지 거리·방향의 분포 → 손으로 찾은 0.45 m와 비교.
3. 그걸로 안 되는 기술에만 작은 정책 학습.
4. 손으로 짠 기술과 번갈아 돌려 성공률 비교(`batch-ab`).

## 8. v2.0 항목과의 관계

| v2.0 항목 | 이 설계와의 관계 |
|---|---|
| `tick-loop` (읽기 → 상태 → 행동 하나 → 입력) | "행동 하나"를 이 층의 의도로. 단계 1의 `Result`가 다음 틱의 입력이 된다 |
| `route-data` (걷기 / 안전 지점 / 사다리 / 안개벽 …) | 경로 데이터의 각 단계가 의도 하나(`walk_to`, `climb_ladder` …)와 짝. `altar._ladder_up`의 일반화가 여기 들어간다 |
| `batch-ab` | 단계 4·5의 평가 도구. 그 전에는 단계 1~3만 |
| `recording-feedback` | 단계 5와 같은 데이터(녹화)를 쓴다 |
| `worldstate` | 전조건 확인이 WorldState를 읽게 되면 기술마다 따로 텔레메트리를 읽지 않아도 된다 |

순서 제안: `settings-object` → **단계 1(기록만)** → `worldstate` → `tick-loop`(의도 API 사용) → `route-data` → 단계 2·3 → `batch-ab` → 단계 4·5.
단계 1은 기록만이라 v2.0 어느 지점에 넣어도 v1.0 실행을 바꾸지 않는다.

## 9. 단계별로 볼 숫자

| 지표 | 무엇을 보여 주나 |
|---|---|
| `duel.py`·`field.py` 줄 수 (tick-loop로 옮긴 뒤) | 위층이 덜 하게 됐나 |
| 기술별 성공률 | 컨트롤러를 믿을 수 있나 |
| 실패 중 이유가 붙은 비율 | 단계 1 계약이 충분한가 |
| 입력 충돌 횟수와 그때의 피해 | 단계 2가 필요한가 |
| 보정값 vs 손으로 찾은 값 | 단계 3 측정이 맞나 |
| 예측 확률 vs 실제 성공률 | 단계 4를 믿어도 되나 |

## 10. 하지 않을 것

- 전술(누구를 칠지, 언제 물러날지)을 이 층에 넣지 않는다 — 그건 3~4층.
- 화면을 보는 강화학습이나 끝에서 끝까지 학습으로 시작하지 않는다.
- 공개 저장소 `kakasolg/controller-response-overlay`에 쓰기 기능을 넣지 않는다(읽기 전용 원칙, 소스 검사 테스트로 잠김). 이 층은 별개 구성 요소다.
- 온라인 플레이에 쓰지 않는다(공정성, 안티치트 제재). 오프라인 싱글 전용 — "Game-memory writes … offline use only"와 같은 범위.
- `experiments/`·`legacy/`에서 가져오지 않는다(P-15, P-43).

## 11. 역할 (제안)

- [cloud]: 단계 1 코드(감싸는 층·`Result`·오프라인 테스트), 단계 2의 출처 기록, 단계 3·4의 분석 스크립트.
- [win]: 단계 1 이후 실행에서 기술별 성공률·`reason` 비율 보고, 단계 2 충돌 수 보고.
- [MoKa]: §12 결정, 단계 5의 시범.

ROADMAP 줄 제안(결정되면 [cloud]가 추가):
`- [ ] smart-controller | cloud | todo | 기술 5개 계약 + Result, 기록만(design-smart-controller.md 단계 1); 다음은 입력 충돌 세기 | docs/design-smart-controller.md`

## 12. [MoKa]에게 묻는 것

1. 이 방향(봇 대신 컨트롤러를 똑똑하게)을 v2.0에 넣을까? 넣는다면 §8의 순서가 괜찮은가?
2. 단계 1의 다섯 기술(`walk_to`, `drink`, `climb_ladder`, `quit_reload`, `attack`)이 맞나? 빼거나 더할 것은?
3. `reason` 이름은 영어(코드·로그 검색용)로 두고, 화면·로그 문장은 지금처럼 한국어로 둘까?
4. 단계 1을 "기록만"으로 먼저 하는 데 동의하나? (동작 변경 없음, 골든 테스트로 확인)
