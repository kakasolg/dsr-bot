"""Kindle at the Undead Burg bonfire — use Humanity up to 2, reverse Hollowing, kindle (Estus 5 → 10).

[MoKa] 11-01: "에스트가 10병이 아니면 보스까지 가기 힘들어" · "인간성 2개 사용 하고, reverse hollowing, kindle도 포함 시켜줘".

  python run.py … --kindle            farm.rest at the Burg bonfire (last bonfire 1012962) does this while seated, after the level-up
  python kindle.py                    standing next to the Burg bonfire: rest, do it, stand up

Steps (measured by hand 11-01 18:00 at the Burg bonfire, every step checked on screen and in memory):
  1. standing: Humanity (goods 500) into a quick slot (tm.equip_quick_item — memory write, Steam offline only), switch with the
     **mouse wheel** until selected_item() == 500, use with **R** (Key settings, Keyboard & Mouse: Switch item = wheel, Use item = R;
     pad D-pad ↓ and keyboard ↓ did not switch to the written slot), 4 s apart, until the humanity counter reads 2. Wheel back to Estus.
  2. seated, bonfire menu Leave · Level Up · Kindle · Reverse Hollowing (cursor on Leave): ↓×3 A → "Offer humanity and reverse
     Hollowing?" (opens on NO) ← A → counter 2 → 1, cursor back on Leave.
  3. ↓×2 A → "Offer humanity and kindle flame?" (opens on NO) ← A → counter 1 → 0, Estus count 10.

/**
 * ── 알려진 한계 ──────────────────────────────
 *  · 망자(할로우)인지 메모리로 못 읽는다. 인간성 수치가 줄었는지로만 되살리기가 됐는지 본다 — 이미 사람이면 메뉴 대답이 다를 수
 *    있고(11-01엔 안 겪음), 그땐 "안 줄어듦"을 남기고 불 지피기만 해 본다.
 *  · 메뉴 칸 위치는 화면을 안 읽고 누르는 횟수로 간다(levelup과 같음). 끝나고 에스트 수·인간성 수치를 읽어 확인한다.
 *  · 불 지피기는 의식의 도구 없이 10병까지만 — 이미 10병 이상이면 아무것도 안 한다.
 */
"""
from __future__ import annotations

import ctypes
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ON = False                     # run.py --kindle
BURG_BONFIRE = 1012962         # only here (MoKa's ask; Firelink rests stay as they are)
HUMANITY = 500
WANT_HUMANITY = 2              # MoKa: "인간성 2개 사용"
ESTUS_KINDLED = 10
ESTUS_IDS = range(200, 216)
USE_GAP_S = 4.0                # Humanity use anim (11-01: 0 → 1 → 2 at 4 s apart)
OFFER_S = 8.0                  # confirm → counter / Estus written (11-01: read after 8 s)
WHEEL_TRIES = 5

R_KEY = (0x52, 0x13)           # vk, scan
KEYEVENTF_SCANCODE, KEYEVENTF_KEYUP, MOUSEEVENTF_WHEEL = 0x0008, 0x0002, 0x0800


def _wheel_down() -> None:
    ctypes.windll.user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, ctypes.c_uint32(-120 & 0xFFFFFFFF).value, 0)


def _press_r() -> None:
    u = ctypes.windll.user32
    u.keybd_event(R_KEY[0], R_KEY[1], KEYEVENTF_SCANCODE, 0)
    time.sleep(0.1)
    u.keybd_event(R_KEY[0], R_KEY[1], KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP, 0)


def _select(tm, want) -> bool:
    """Wheel through the quick slots until selected_item() is in `want` (a set of item ids)."""
    import control
    control.focus_game()
    time.sleep(0.3)
    for _ in range(WHEEL_TRIES):
        if tm.selected_item() in want:
            return True
        _wheel_down()
        time.sleep(1.0)
    return tm.selected_item() in want


def use_humanity(tm, log=print) -> str:
    """Standing: use Humanity items until the counter reads WANT_HUMANITY. → what happened (for the log)."""
    import steam_state
    have = tm.humanity() or 0
    if have >= WANT_HUMANITY:
        return f"인간성 이미 {have}"
    items = tm.goods_count(HUMANITY) or 0
    if items < WANT_HUMANITY - have:
        return f"인간성 아이템 부족 ({items}개, 수치 {have})"
    if HUMANITY not in (tm.quick_items() or []):
        if steam_state.check().get("offline") is not True:
            return "Steam 오프라인 아님 — 퀵슬롯 쓰기 안 함"
        slot = tm.equip_quick_item(HUMANITY)
        log(f"   불 지피기: 인간성 퀵슬롯 {slot} (메모리 쓰기)")
        if slot is None:
            return "인간성 퀵슬롯 못 넣음"
    if not _select(tm, {HUMANITY}):
        return f"휠로 인간성 못 고름 (선택 {tm.selected_item()})"
    while (tm.humanity() or 0) < WANT_HUMANITY:
        before = tm.humanity() or 0
        if tm.selected_item() != HUMANITY:           # never press use on an unchecked slot (11-01: pad X drank Estus)
            break
        _press_r()
        time.sleep(USE_GAP_S)
        if (tm.humanity() or 0) <= before:
            break
    back = _select(tm, set(ESTUS_IDS))
    have = tm.humanity() or 0
    return f"인간성 수치 {have} (아이템 {tm.goods_count(HUMANITY)}개 남음){'' if back else ' — 에스트로 못 돌림'}"


def offer(tm, tap, log=print) -> str:
    """Seated, cursor on Leave: reverse Hollowing, then kindle. tap(key) with key in A · LEFT · DOWN (levelup's convention)."""
    def estus():
        return max((tm.goods_count(i) or 0) for i in ESTUS_IDS)

    out = []
    h0 = tm.humanity() or 0
    if h0 >= 1:
        for k in ("DOWN", "DOWN", "DOWN", "A", "LEFT", "A"):
            tap(k)
        time.sleep(OFFER_S)
        h1 = tm.humanity() or 0
        out.append(f"되살리기 인간성 {h0}→{h1}" + ("" if h1 < h0 else " (안 줄어듦 — 이미 사람?)"))
    h0, e0 = tm.humanity() or 0, estus()
    if h0 < 1:
        out.append("불 지피기 못 함 — 인간성 0")
        return " · ".join(out)
    for k in ("DOWN", "DOWN", "A", "LEFT", "A"):
        tap(k)
    time.sleep(OFFER_S)
    out.append(f"불 지피기 에스트 {e0}→{estus()}, 인간성 {h0}→{tm.humanity()}")
    return " · ".join(out)


def maybe(tm, tap, stand_up, sit_down, log=print) -> str | None:
    """Seated (farm.rest, after the level-up). Burg bonfire only, Estus below 10 only.
    stand_up() / sit_down() → bool: farm.rest's B-out and A-in (items can't be used seated)."""
    if not ON or tm.last_bonfire() != BURG_BONFIRE:
        return None
    e = max((tm.goods_count(i) or 0) for i in ESTUS_IDS)
    if e >= ESTUS_KINDLED:
        r = f"에스트 이미 {e}병 — 안 함"
        log(f"   불 지피기: {r}")
        return r
    if (tm.humanity() or 0) < WANT_HUMANITY:
        if not stand_up():
            r = "일어나기 실패"
            log(f"   불 지피기: {r}")
            return r
        log(f"   불 지피기: {use_humanity(tm, log)}")
        if not sit_down():
            r = "다시 앉기 실패"
            log(f"   불 지피기: {r}")
            return r
        time.sleep(1.0)
    r = offer(tm, tap, log)
    log(f"   불 지피기: {r}")
    return r


def main() -> None:
    import control
    import env
    import farm
    import ground
    import navmesh
    from souls import missions
    global ON
    ON = True
    tm = env.make_telemetry({})
    control.focus_game()
    pad = control.Pad()
    time.sleep(2.0)                                     # a new virtual pad is read ~2 s after connect (11-01)
    spot = missions.SPOTS["burg-bonfire"]
    nm = ground.for_map(navmesh.Navmesh(spot["map"]))
    ok = farm.rest(tm, pad, nm, spot)
    print(f"휴식+불 지피기: {'ok' if ok else '실패'} · 인간성 {tm.humanity()} · 에스트 "
          f"{max((tm.goods_count(i) or 0) for i in ESTUS_IDS)}")


if __name__ == "__main__":
    main()
