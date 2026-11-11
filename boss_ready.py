"""Entry checks before the Taurus fight and the post-Taurus path ([MoKa] 2026-10-31: "전제 미충족 또는 확인 불가이면 중단·보고").

  altar(tm)             burg-altar: go on only when Taurus is confirmed dead → Verdict
  taurus(tm)            run.py taurus: crossbows on the tower dead, Gold Pine Resin held and in a quick slot, Estus ≥ 1 → Verdict

Verdict.ok False = stop before any move, attack or item use; Verdict.stop says why, Verdict.facts holds what was read (written to
the run's log/events). Reads only (snapshot, goods_count, quick_items, event_flag) — no pad, no memory writes.

/**
 * ── 알려진 한계 ──────────────────────────────
 *  · 타우로스 처치 기록(이벤트 플래그) 번호를 모른다 (저장소·gamefiles에 없음, MSB에는 배치 entity 1010700만 있음).
 *    그래서 TAURUS_KILLED_FLAG = None → burg-altar는 스냅숏에서 HP 0 두 번을 보지 않는 한 "처치 확인 불가"로 멈춘다.
 *    다른 세션·재접속·휴식 뒤에 죽은 보스가 스냅숏에 HP 0으로 남는지는 모른다 (미측정). 번호를 추측해 넣지 않는다.
 *  · 처치 확인 = 같은 적이 두 스냅숏 연속 HP 0 (Field 대상 생존 판정 Patch A와 같은 규칙). "안 보임"은 처치가 아니라
 *    관측 불가 → 멈춤. 근거: MoKa 원본 녹화 data/observe/20261006_173431.jsonl (반경 30 m, 같은 세션)에서 죽은 255002
 *    둘(377·383 s)과 225000(486.5 s)이 녹화 끝(578.5 s)까지 hp_raw 0으로 남았다. 봇 스냅숏(dsr_telemetry.snapshot)도 HP로
 *    거르지 않는다. 다른 거리·재접속·휴식 뒤는 미측정이라 일반화하지 않는다.
 *  · <run>.track.jsonl은 HP > 0, 12 m 안의 적만 남긴다 (track.py `hostile(12.0)`) — 거기 없다는 건 죽은 적이 스냅숏에
 *    없다는 증거가 아니다 (10-31 이 파일 첫 판에서 005650 track을 그 근거로 잘못 썼다).
 *  · 석궁병은 스폰 자리가 아니라 탑 위 전체(TOWER_R 15 m, 높이 ±3 m)에서 센다 — 시체는 죽은 자리에 남는다 (같은 녹화에서
 *    두 번째 시체가 스폰에서 7.9 m, MoKa 10-31 "규칙 변경 진행"). 탑 위 높이의 255002는 이 둘뿐 (MSB). 시체가 탑 아래로
 *    떨어지면 높이가 달라 "unseen" → 멈춤.
 *  · 송진 상자 기록(51010460)은 기록만 한다 — 먹었어도 다 썼을 수 있다. 판단은 송진 개수 + 퀵슬롯.
 *  · 문(송진 문) 열림 기록 번호도 모른다 → 늘 "확인 불가"로 남긴다.
 *  · 과거 실행 기록(10-12 성공 등)은 지금 세이브 상태의 증거가 아니다 — 여기서는 지금 읽은 값만 쓴다.
 */
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path

TAURUS = 225000
CROSSBOW = 255002
RESIN = 311                       # Gold Pine Resin (souls/taurus.py RESIN)
RESIN_CHEST_FLAG = 51010460       # data/treasures.json 宝箱01 (황금 송진 3) ItemFlag
TAURUS_KILLED_FLAG = None         # 모름 — 위 한계 참고
DOOR_FLAG = None                  # 모름
ESTUS_IDS = tuple(range(200, 216))   # souls/moves.py ESTUS_IDS
SPOT_R, SPOT_DY = 6.0, 3.0        # life(near=…): a foe belongs to a spot within this
TOWER_R = 15.0                    # crossbows(): 255002 on the tower top, around the middle of the two zone-8 spots
SNAP_R = 200.0
SNAP_GAP = 0.3

ORDER = "burg-upper --seg 1-8 → taurus"   # 10-12 성공 순서 (docs/boss-taurus.md §8)


@dataclass
class Verdict:
    ok: bool
    stop: list[str] = field(default_factory=list)
    facts: dict = field(default_factory=dict)

    def line(self) -> str:
        f = ", ".join(f"{k} {v}" for k, v in self.facts.items())
        return ("준비됨 — " if self.ok else "멈춤 — " + " · ".join(self.stop) + " | ") + f


def crossbow_spots() -> list[tuple]:
    z = json.loads((Path(__file__).resolve().parent / "data" / "burg-upper-map.json").read_text(encoding="utf-8"))
    z8 = next(zn for zn in z["zones"] if zn["n"] == 8)
    return [tuple(k[1]) for k in z8["kills"] if k[0] == CROSSBOW]


def snaps(tm, n: int = 2, gap: float = SNAP_GAP, sleep=time.sleep) -> list:
    """n snapshots a little apart (None entries = read failed)."""
    out = []
    for k in range(n):
        if k:
            sleep(gap)
        try:
            out.append(tm.snapshot(within=SNAP_R))
        except Exception:
            out.append(None)
    return out


def life(ss: list, npc: int, near=None) -> str:
    """'alive' (seen with HP > 0) · 'dead' (same ptr at HP 0 in every snapshot) · 'unseen' · 'unknown' (a snapshot failed)."""
    if not ss or any(s is None for s in ss):
        return "unknown"

    def match(c):
        if c.npc_param != npc:
            return False
        return near is None or (math.hypot(c.x - near[0], c.z - near[2]) <= SPOT_R and abs(c.y - near[1]) <= SPOT_DY)

    seen = [[c for c in s.chars if match(c)] for s in ss]
    if any(c.hp > 0 for cs in seen for c in cs):
        return "alive"
    zero = [{c.ptr for c in cs if c.hp == 0} for cs in seen]
    if zero and set.intersection(*zero):
        return "dead"
    return "unseen"


def crossbows(ss: list, spots: list) -> list[str]:
    """One state per zone-8 crossbow, counted over the whole tower top ([MoKa] 10-31 "규칙 변경 진행"): a corpse lies where it
    died, not on its spawn — MoKa's recording 20261006_173431 had one 7.9 m off. The tower has only these two 255002 at its
    height (MSB c2550_0008 · 0009; the next 255002 at that height is > 25 m away). → 'alive' for every spot if any is seen
    alive · 'unknown' if a snapshot failed · else one 'dead' per distinct ptr at HP 0 in every snapshot, 'unseen' for the rest."""
    n = len(spots)
    if not ss or any(s is None for s in ss):
        return ["unknown"] * n
    cx, cy, cz = (sum(q[0] for q in spots) / n, sum(q[1] for q in spots) / n, sum(q[2] for q in spots) / n)
    on = [[c for c in s.chars if c.npc_param == CROSSBOW and math.hypot(c.x - cx, c.z - cz) <= TOWER_R
           and abs(c.y - cy) <= SPOT_DY] for s in ss]
    if any(c.hp > 0 for cs in on for c in cs):
        return ["alive"] * n
    dead = set.intersection(*[{c.ptr for c in cs if c.hp == 0} for cs in on])
    k = min(len(dead), n)
    return ["dead"] * k + ["unseen"] * (n - k)


def _estus(tm):
    """Estus count, None if any read failed (moves.estus_left turns a failure into 0)."""
    counts = [tm.goods_count(i) for i in ESTUS_IDS]
    if any(c is None for c in counts):
        return None
    return sum(counts)


def _flag(tm, fid):
    if fid is None:
        return "확인 불가 (기록 번호 모름)"
    v = tm.event_flag(fid)
    return "확인 불가 (읽기 실패)" if v is None else ("있음" if v else "없음")


def altar(tm, ss: list | None = None) -> Verdict:
    """burg-altar 진입: 타우로스 처치가 확인돼야만 감."""
    ss = snaps(tm) if ss is None else ss
    seen = life(ss, TAURUS)
    flag = _flag(tm, TAURUS_KILLED_FLAG)
    facts = {"타우로스 스냅숏": seen, "타우로스 처치 기록": flag}
    if flag == "있음" or seen == "dead":
        return Verdict(True, [], facts)
    if seen == "alive":
        why = f"타우로스 살아 있음 — burg-altar는 타우로스를 잡은 캐릭터용. 먼저 {ORDER}"
    else:
        why = (f"타우로스 처치 확인 불가 (스냅숏 {seen}, 처치 기록 {flag}) — 안 보이는 건 처치가 아님. "
               f"처치한 캐릭터인지 MoKa 확인 필요, 아니면 {ORDER}")
    return Verdict(False, [why], facts)


def taurus(tm, ss: list | None = None, spots: list | None = None) -> Verdict:
    """run.py taurus 진입 (안개벽 앞): 석궁병 둘 처치 확인 · 송진 보유 + 퀵슬롯 · 에스트 ≥ 1. 이 경로는 송진 사용이 필수."""
    ss = snaps(tm) if ss is None else ss
    spots = crossbow_spots() if spots is None else spots
    stop, facts = [], {}

    cb = crossbows(ss, spots)
    facts["석궁병"] = " / ".join(cb)
    if "alive" in cb:
        stop.append(f"탑 위 석궁병 살아 있음 — 먼저 burg-upper 구역 8 ({ORDER})")
    elif any(x != "dead" for x in cb):
        stop.append("석궁병 처치 확인 불가 (안 보임 ≠ 처치) — 탑 위 석궁병 둘이 없는지 MoKa 화면 확인 필요")

    n = tm.goods_count(RESIN)
    try:
        q = tm.quick_items()
    except Exception:
        q = None
    q = q if q and all(v is not None for v in q) else None
    chest = _flag(tm, RESIN_CHEST_FLAG)
    facts.update({"송진 개수": "확인 불가" if n is None else n,
                  "송진 퀵슬롯": "확인 불가" if q is None else ("있음" if RESIN in q else "없음"),
                  "송진 상자 기록": chest, "송진 문": _flag(tm, DOOR_FLAG)})
    if n is None:
        stop.append("송진 개수 확인 불가")
    elif n < 1:
        stop.append("황금 송진 0개 — 상자 기록은 있지만 다 씀" if chest == "있음" else
                    "황금 송진 0개 — 송진 문을 열고 상자(31.3, −7.5, −111.1)를 먹었는지 MoKa 확인 필요")
    elif q is None:
        stop.append("퀵슬롯 확인 불가")
    elif RESIN not in q:
        stop.append(f"황금 송진 {n}개가 가방에만 있음 — 퀵슬롯에 넣어야 함 (MoKa, 자동 장착 안 함)")

    e = _estus(tm)
    facts["에스트"] = "확인 불가" if e is None else e
    if e is None:
        stop.append("에스트 개수 확인 불가")
    elif e < 1:
        stop.append("에스트 0개")
    return Verdict(not stop, stop, facts)
