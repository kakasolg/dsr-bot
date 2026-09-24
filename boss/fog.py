"""두 번째 화톳불 → 보스 안개 앞 (3.4, 210.1, -34.8). 끝에서 HP 80% 밑이면 에스트."""
import sys, time
sys.path.insert(0, r"D:\dev\chzzk-souls-chaos\bot")
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent)); sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import ah
from ah import tm, pad, go, L, nav, control


def leg(name, q):
    r = go(q)
    s = ah.snap(20)
    print(name, r, (round(s.player.x, 1), round(s.player.y, 1), round(s.player.z, 1)), "HP", s.player.hp, "에스트", tm.goods_count(201), "소울", tm.souls(), flush=True)
    return r


def main():
    ok = False
    try:
        ok = leg("롱소드 통로", (38.6, 195.4, 17.0)) == "arrived" and leg("위층 안개 앞", (6.3, 201.8, 20.0)) == "arrived"
        if ok:
            s = ah.snap(5)
            st = control.world_to_stick(4.2 - s.player.x, 19.6 - s.player.z, s.cam_yaw, nav.YAW_OFFSET, nav.FLIP_X)
            pad.move(0.5 * st[0], 0.5 * st[1]); time.sleep(0.15); pad.move(0, 0); time.sleep(0.5)
            L.press_a(pad); time.sleep(3.5)
            for name, q in (("통로 끝", (-8.9, 201.8, 14.9)), ("계단 꼭대기", (-7.9, 208.4, -6.8)), ("복도 끝", (-8.2, 208.4, -29.8)), ("안개 계단 아래", (3.6, 209.2, -36.5))):
                if leg(name, q) != "arrived":
                    ok = False; break
        if ok:
            nav.goto(tm, pad, (3.4, 210.1, -34.8), tolerance=0.35, timeout=5, log=lambda *a_: None, mode_fn=lambda _s: "walk")
            pad.neutral(); time.sleep(0.4)
            s = ah.snap(8)
            if s.player.hp < s.player.max_hp * 0.8 and tm.goods_count(201):
                pad.use_item(); time.sleep(0.2); pad.release_due(); time.sleep(2.4)
            s = ah.snap(8)
            print("안개 앞", (round(s.player.x, 1), round(s.player.y, 1), round(s.player.z, 1)), "HP", s.player.hp, "에스트", tm.goods_count(201), "안내", L.prompt_px(), flush=True)
    finally:
        ah.safe_end()
    return ok


if __name__ == "__main__":
    print("결과", main())
