"""Level up at a bonfire — spend the souls held on one stat ([MoKa] 2026-10-31: "소울이 모일때 마다 Vitality를 계속 올려봐").

  python run.py … --level-up VIT        every rest (farm.rest) levels VIT as far as the souls held allow, then stands up
  python levelup.py STR=16 altar-bonfire  only up to 16 (one stat per rest: the menu cursor after B is not checked)
  python levelup.py VIT [spot]          rest at a bonfire from data/spots.json (default firelink-bonfire; must be near it),
                                        level up, stand up — one screenshot per press into data/runs/shots_…_levelup-steps

Menu path (DSR, pad): seated → bonfire menu, cursor on "Leave" → ↓ "Level Up" → A → level screen, cursor on Vitality → ↓ to the stat →
→ once per level (the game stops at what the souls cover) → ↓ to ACCEPT → A → confirm dialog (opens on CANCEL) ← OK → A. Checked afterwards by
reading SL·stat·souls from memory (char_stats) — the menu itself is not read.

/**
 * ── 알려진 한계 ──────────────────────────────
 *  · 메뉴 위치(커서 시작 칸, 확인 창의 기본 선택)는 화면을 읽지 않고 누르는 횟수로만 간다. 화톳불 메뉴 항목 순서가 다르면
 *    (예: 인간성이 있어 "불 지피기"가 위에 생김) 다른 메뉴로 들어갈 수 있다 → 끝나고 SL·능력치를 다시 읽어 확인하고,
 *    안 올랐으면 "안 오름"으로 남긴다.
 *  · 레벨 비용은 위키 표/식으로 계산한다(SL 12까지 표, 그 위는 식). 틀리면 → 를 더 눌러도 게임이 막으니 손해는 없다.
 */
"""
from __future__ import annotations

import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

WANT: str | None = None          # run.py --level-up sets the stat; None = never level (the low-level challenge default)
ROWS = ["VIT", "ATN", "END", "STR", "DEX", "RES", "INT", "FTH"]   # level screen order (10-31 screenshot), ACCEPT after FTH
LOW_COST = {2: 673, 3: 690, 4: 707, 5: 724, 6: 741, 7: 758, 8: 775, 9: 793, 10: 811, 11: 829, 12: 847}
OPEN_S = 1.5                     # bonfire menu → level screen fade
ACCEPT_S = 2.0                   # confirm → stats written
SHOT = None                      # callable(label) — one screenshot per press (python levelup.py, [MoKa] 10-31 "스크린샷 하나씩")


def cost(target: int) -> int:
    """Souls to go from SL target−1 to target."""
    if target in LOW_COST:
        return LOW_COST[target]
    x = target
    return round(0.02 * x ** 3 + 3.06 * x ** 2 + 105.6 * x - 895)


def affordable(sl: int, souls: int) -> int:
    n = 0
    while souls >= cost(sl + n + 1):
        souls -= cost(sl + n + 1)
        n += 1
    return n


def level(tm, press, stat: str, log=print, up_to: int | None = None) -> str:
    """Seated with the bonfire menu open → level `stat` as far as the souls go, back to the bonfire menu.
    press(name) taps one pad button ('A', 'B', 'DOWN', 'LEFT', 'RIGHT'). → 'SL a→b, VIT x→y, souls s→t' | reason nothing happened."""
    if stat not in ROWS:
        return f"모르는 능력치 {stat}"
    st = tm.char_stats() or {}
    sl, souls = st.get("SL"), st.get("소울")
    if sl is None or souls is None:
        return "능력치 못 읽음"
    n = affordable(sl, souls)
    if up_to is not None:                            # "STR=16": only up to that value ([MoKa] 11-09 클레이모어 STR 16 · DEX 10)
        have = st.get(stat) or 0
        if have >= up_to:
            return f"{stat} 이미 {have} ≥ {up_to}"
        n = min(n, up_to - have)
    if n < 1:
        return f"소울 부족 ({souls} < {cost(sl + 1)})"
    log(f"   레벨업: SL {sl} 소울 {souls} → {stat} +{n} (비용 {sum(cost(sl + k + 1) for k in range(n))})")

    def step(key: str, label: str, wait: float = 0.3) -> None:
        press(key)
        time.sleep(wait)
        if SHOT is not None:
            SHOT(label)

    if SHOT is not None:
        SHOT("bonfire_menu")
    step("DOWN", "on_level_up")                     # bonfire menu opens on "Leave"; "Level Up" is next (10-31 screenshot)
    step("A", "level_screen", OPEN_S)
    row = ROWS.index(stat)
    for k in range(row):
        step("DOWN", f"down{k + 1}")
    for k in range(n):
        step("RIGHT", f"{stat}+{k + 1}")
    for k in range(len(ROWS) - row):                # → ACCEPT
        step("DOWN", f"to_accept{k + 1}")
    step("A", "accept", 0.8)                        # ACCEPT → "Confirm reinforcement" OK | CANCEL, cursor on CANCEL
    step("LEFT", "on_ok")
    step("A", "confirm_ok", ACCEPT_S)
    after = tm.char_stats() or {}
    step("B", "back", 1.0)                          # level screen → bonfire menu
    got = (f"SL {sl}→{after.get('SL')}, {stat} {st.get(stat)}→{after.get(stat)}, 소울 {souls}→{after.get('소울')}"
           f", 다음 레벨 {cost(sl + n + 1)}")
    if after.get("SL") != sl + n or after.get(stat) != (st.get(stat) or 0) + n:
        return "안 오름 — " + got
    return got


def maybe(tm, tap, log=print, want: str | None = None) -> str | None:
    """Seated at a bonfire: level `want` if set (farm.rest, missions.light_burg_bonfire). tap(vgamepad button) = farm.rest press · Moves.press.
    want: the run's value (Settings.get("levelup", "WANT"), settings-object step 3); None = this module's WANT."""
    want = WANT if want is None else want
    if not want:
        return None
    import vgamepad
    B = vgamepad.XUSB_BUTTON
    keys = {"A": B.XUSB_GAMEPAD_A, "B": B.XUSB_GAMEPAD_B, "DOWN": B.XUSB_GAMEPAD_DPAD_DOWN,
            "LEFT": B.XUSB_GAMEPAD_DPAD_LEFT, "RIGHT": B.XUSB_GAMEPAD_DPAD_RIGHT}
    stat, _, cap = want.partition("=")             # "STR" (as far as souls go) or "STR=16" (up to 16)
    r = level(tm, lambda k: tap(keys[k]), stat, log, up_to=int(cap) if cap else None)
    log(f"   레벨업 ({want}): {r}")
    return r


def main() -> None:
    import control
    import env
    import farm
    import ground
    import navmesh
    from souls import missions

    from pathlib import Path

    from PIL import ImageGrab

    import levelup                                  # the module farm.rest reads — not this __main__ copy
    import screen_prompt
    stat = (sys.argv[1] if len(sys.argv) > 1 else "VIT").upper()
    levelup.WANT = stat
    out = Path("data/runs") / time.strftime("shots_%Y%m%d_%H%M%S_levelup-steps")
    out.mkdir(parents=True, exist_ok=True)
    seq = [0]

    def shot(label: str) -> None:
        r = screen_prompt.window_rect()
        if r:
            seq[0] += 1
            ImageGrab.grab(bbox=r, all_screens=True).save(out / f"{seq[0]:02d}_{label}.jpg", quality=85)
    levelup.SHOT = shot
    tm = env.make_telemetry({})
    control.focus_game()
    pad = control.Pad()
    spot = missions.SPOTS[sys.argv[2] if len(sys.argv) > 2 else "firelink-bonfire"]
    nm = ground.for_map(navmesh.Navmesh(spot["map"]))
    ok = farm.rest(tm, pad, nm, spot)
    print(f"휴식+레벨업: {'ok' if ok else '실패'} · {tm.char_stats()} · 스크린샷 {seq[0]}장 {out}")


if __name__ == "__main__":
    main()
