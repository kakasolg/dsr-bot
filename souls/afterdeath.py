"""After a death: go back for the bloodstain, or not ([MoKa] 2026-10-12).

  "죽으면 잃어버린 소울과 인간성을 평가해서 많으면 회수 하고, 너무 적으면 무시하자. 아니면 연속으로 동일 지역에서 죽어도
   사실 큰 문제는 캐릭터 레벨과 무기 강화 수치가 낮은 거라 재시도가 의미가 없음."

Until now a death ended the run and the stain was never fetched (38 deaths in data/samples, 0 pickup trips). Now one of:
  recover — worth a trip: start over from the bonfire (burg-upper zone 1 rests there anyway; every foe is back after a death)
            and pick the stain up after the zone that reaches it (`Field.pick_blood`)
  ignore  — too little to be worth the trip: end the run, the stain stays where it is
  stop    — died again in the zone of the last death: a retry won't fix level / weapon — end the run (that stain is lost)
"""
from __future__ import annotations

RECOVER_SOULS = 2000      # 10-11/10-12 runs (SL 15-18) dropped 439-4,127 per death; the small ones are deaths early in a run
RECOVER_HUMANITY = 2      # 1 humanity alone (most deaths carry it) is not worth a trip
MAX_TRIPS = 2             # recovery trips per run — a run that keeps dying somewhere new still ends
PICK_NEAR = 40.0          # after each zone of a recovery trip: walk to the stain if it is this close (m)


def worth(stain: dict | None) -> bool:
    if not stain:
        return False
    return stain.get("souls", 0) >= RECOVER_SOULS or stain.get("humanity", 0) >= RECOVER_HUMANITY


def plan(stain: dict | None, zone, last_zone, trips: int) -> tuple[str, str]:
    """stain = Blood.read() after the respawn, zone = where we died, last_zone = the previous death's zone in this run (None = first),
    trips = recovery trips already made. → (action, why); action is 'recover' | 'ignore' | 'stop'."""
    if last_zone is not None and zone == last_zone:
        return "stop", f"구역 {zone}에서 연속 사망 — 재시도 의미 없음 (레벨·무기)"
    if not stain:
        return "ignore", "핏자국 기록 없음"
    what = f"소울 {stain.get('souls', 0)}, 인간성 {stain.get('humanity', 0)}"
    if not worth(stain):
        return "ignore", f"{what} — 적어서 무시 (기준 소울 {RECOVER_SOULS} · 인간성 {RECOVER_HUMANITY})"
    if trips >= MAX_TRIPS:
        return "stop", f"{what} — 회수 시도 {trips}번 다 씀"
    return "recover", f"{what} — 회수하러 감"


def fresh_stain(read, before, wait_s: float = 5.0, sleep=None) -> dict | None:
    """The stain this death left: Blood writes it once the respawn shows the souls gone (its 't' changes). None if nothing new
    came (a death with 0 souls and 0 humanity leaves no stain)."""
    import time
    sleep = sleep or time.sleep
    t_old = (before or {}).get("t")
    for _ in range(max(1, int(wait_s / 0.25))):
        st = read()
        if st and st.get("t") != t_old:
            return st
        sleep(0.25)
    return None


def run_zones(first: int, last: int, play, *, alive, respawn, read_stain, pick, log=print, event=None, set_zone=None,
              restart: int = 1, recover: bool = True, ends=("died", "no_estus", "휴식 실패"), label=None, sleep=None) -> str:
    """Zones first..last with play(n) → result. After a death: respawn(), then plan() on the new stain — 'recover' starts over at
    `restart` and, after every zone of that trip, pick() (Field.pick_blood: None = no stain / too far, 'got', 'miss',
    'near_bonfire', or a walk result) until it is got. recover=False = the old way: a death ends the run. → last zone result"""
    event = event or (lambda *a, **k: None)
    set_zone = set_zone or (lambda n: None)
    trips, last_dead, start, target, r = 0, None, first, None, None
    while True:
        died_in = None
        before = read_stain()
        for n in range(start, last + 1):
            set_zone(n)
            r = play(n)
            log(f"══ 구역 {n} ({label(n)}) 끝: {r}" if label else f"══ 구역 {n} 끝: {r}")
            if alive() and target is not None:
                got = pick()
                if got is not None:
                    log(f"   핏자국 회수 (구역 {n}): {got}")
                    event("blood_pick", zone=n, result=got, souls=target.get("souls"), humanity=target.get("humanity"))
                    if got in ("got", "near_bonfire"):
                        target = None
            if not alive():
                died_in = n
                break
            if r in ends:
                break
        if died_in is None:
            return r
        set_zone(None)
        if target is not None:
            log(f"   핏자국 못 찾고 다시 죽음 — 소울 {target.get('souls')}, 인간성 {target.get('humanity')} 잃음")
            event("blood_lost", souls=target.get("souls"), humanity=target.get("humanity"))
            target = None
        if not recover:
            return r
        respawn()
        st = fresh_stain(read_stain, before, sleep=sleep)
        act, why = plan(st, died_in, last_dead, trips)
        log(f"══ 사망 뒤 (구역 {died_in}): {act} — {why}")
        event("after_death", zone=died_in, action=act, why=why, trips=trips,
              souls=(st or {}).get("souls"), humanity=(st or {}).get("humanity"), pos=(st or {}).get("pos"))
        if act != "recover":
            return r
        trips, last_dead, start, target = trips + 1, died_in, restart, st
