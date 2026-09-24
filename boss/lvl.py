"""화톳불 메뉴에서 버튼 누르기: python boss/lvl.py DOWN A ... → 마지막에 스크린샷."""
import sys, time, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import control, quitout, ladder_test as L
B = quitout.B
pad = control.Pad(); pad.reconnect(); control.focus_game()
for k in sys.argv[1:-1]:
    quitout._press(pad, getattr(B, "XUSB_GAMEPAD_" + ("DPAD_" + k if k in ("UP", "DOWN", "LEFT", "RIGHT") else k)), 0.35)
print(L.shot(sys.argv[-1]))
