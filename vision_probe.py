"""
적 단계(준비·경계·공격) 화면 판정 프로브 — 캐릭터를 몰고 가며 스크린샷을 모은다 (상인 달리기 경로, 불의 제전 쪽).

  python vision_probe.py [시도 수]

사용자: "적이 근처에 있으면 정렬하고 스크린샷 찍고 분석하면?" / "네가 캐릭터를 움직여 가면서 조정해 봐."
봇은 적이 봇을 **알아챘는지**를 메모리에서 모른다 (행동으로 추정할 뿐 — 알아챘지만 아직 안 움직이는 적을 놓친다).
사람은 화면으로 안다. 그래서 화면을 Gemini 에게 보여 주고, 같은 순간의 메모리 값·그 뒤 3 s 행동과 나란히 남긴다.

한 시도: 화톳불 휴식(적 초기화) → 경로를 **천천히** 걷다가 15 m 안에 적이 보이면 멈춤 → 오른스틱으로 카메라를 그 적에
정렬(락온은 안 쓴다 — 게임과 기록이 어긋난 적이 있다) → 창 캡처 → 가운데를 잘라 Gemini 두 모델에 동시에 → 3 s 서서
그 적이 다가오는지·휘두르는지 본다 (행동 정답) → 알아챘으면 화톳불로 돌아가 다음 시도, 아니면 3 m 더 가서 다시.

남기는 것: data/vision_probe.jsonl (한 장에 한 줄), data/vision/<시각>.jpg (잘라낸 그림 — 사람이 보고 준비/경계를 적을 수 있게)
"""
from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes
import io
import json
import math
import sys
import threading
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import control
import merchantrun as mr
import nav
import patrol
import tactic_llm

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "vision_probe.jsonl"
IMG_DIR = ROOT / "data" / "vision"
MODELS = ["gemini-3.5-flash-lite"]   # 3.8 Flash 는 뺐다 — 이미지에 2.5~6.6 s (생각 기본값), 서서 판단하기에도 느리다
STATES = ["none", "unaware", "alert", "attacking"]
SEE = 15.0              # 이 안에 적이 보이면 멈춰서 찍는다
STEP_CLOSER = 3.0       # 모르는 것 같으면 이만큼 더 다가가서 다시
CLOSEST = 4.0           # 이보다 가까워지면 그만 (싸움이 된다)
PROMPT = ("Dark Souls Remastered screenshot, cropped around an enemy about {d:.0f} m away (near the centre). "
          "The player character may be visible from behind in the lower part. Classify that enemy by what it is doing: "
          "'none' if no enemy is visible, 'unaware' if it is idle and has not noticed the player (slumped, facing elsewhere, weapon down), "
          "'alert' if it has noticed the player (turned toward the player, weapon or shield raised, stepping toward the player), "
          "'attacking' if it is swinging, lunging or throwing. Reply with the JSON object only.")


def window_rect() -> tuple[int, int, int, int] | None:
    """게임 창의 클라이언트 영역 (화면 좌표)."""
    u = ctypes.windll.user32
    h = u.FindWindowW(None, "DARK SOULS™: REMASTERED")
    if not h:
        return None
    r = ctypes.wintypes.RECT()
    u.GetClientRect(h, ctypes.byref(r))
    pt = ctypes.wintypes.POINT(0, 0)
    u.ClientToScreen(h, ctypes.byref(pt))
    return pt.x, pt.y, pt.x + r.right, pt.y + r.bottom


VFOV_DEG = 47.0   # 세로 시야각 — 불의 제전 화톳불에서 캐릭터 발(0 m)·머리(1.7 m)를 투영해 화면 키(약 260/540)와 맞춘 값


def cam_matrix(tm):
    """ChrFollowCam 4x4 — 행 0 오른쪽, 1 위, 2 정면, 3 위치. 위 행은 (0,1,0) 이지만 **정면 행 y 에 상하 기울기가 들어 있다**
    (2026-09-23 실측: 오른 스틱으로 −40°→+40° 가 정면 y −0.65→+0.64). 투영의 세로는 위 행 때문에 여전히 어긋난다 → 자를 때 세로를 넉넉히."""
    import numpy as np
    c1 = tm.q(tm.static["ChrFollowCam"])
    c2 = tm.q(c1 + 0x60) if c1 else None
    cam = tm.q(c2 + 0x60) if c2 else None
    if not cam:
        return None
    m = [[tm.f32(cam + 0x10 + 4 * (4 * r + k)) for k in range(3)] for r in range(4)]
    if any(v is None for row in m for v in row):
        return None
    return np.array(m)


def project(tm, x, y, z, w, h):
    """월드 점 → 화면 (px). 카메라 뒤면 None."""
    import numpy as np
    m = cam_matrix(tm)
    if m is None:
        return None
    v = np.array([x, y, z]) - m[3]
    zc = float(v @ m[2])
    if zc < 0.5:
        return None
    f = (h / 2) / math.tan(math.radians(VFOV_DEG) / 2)
    return w / 2 + float(v @ m[0]) / zc * f, h / 2 - float(v @ m[1]) / zc * f


def capture_crop(tm=None, target=None):
    """창 캡처 → 적(target 의 가슴 높이) 투영점 주변을 원본 해상도로 자른다 (가로 35 %, 세로 55 % — 세로는 기울기를 몰라 넉넉히).
    투영을 못 하면 가운데. → (자른 그림, JPEG base64, 투영점을 표시한 전체 화면 축소본)"""
    from PIL import ImageDraw, ImageGrab
    rc = window_rect()
    if not rc:
        return None, None, None
    img = ImageGrab.grab(bbox=rc, all_screens=True)
    w, h = img.size
    pt = project(tm, target.x, target.y + 1.0, target.z, w, h) if (tm is not None and target is not None) else None
    cx, cy = pt if pt else (w / 2, h * 0.45)
    bw, bh = w * 0.20, h * 0.35      # 35 %×55 % 로는 11 m 할로우가 40 px — 방패를 들었는지 안 보였다. 투영 가로가 정확해 좁힌다
    x0 = int(min(max(cx - bw / 2, 0), w - bw))
    y0 = int(min(max(cy - bh / 2, 0), h - bh))
    crop = img.crop((x0, y0, x0 + int(bw), y0 + int(bh)))
    buf = io.BytesIO()
    crop.convert("RGB").save(buf, "JPEG", quality=85)
    full = img.copy()
    dr = ImageDraw.Draw(full)
    if pt:
        dr.ellipse((cx - 14, cy - 14, cx + 14, cy + 14), outline="red", width=4)
    dr.rectangle((x0, y0, x0 + int(bw), y0 + int(bh)), outline="yellow", width=3)
    full = full.resize((640, round(h * 640 / w)))
    return crop, base64.b64encode(buf.getvalue()).decode(), full


def rel_to_camera(s, c) -> float:
    """적 방향 − 카메라 방향 (rad, −π..π). 둘 다 atan2(x, z) 기준."""
    return (math.atan2(c.x - s.player.x, c.z - s.player.z) - s.cam_yaw + math.pi) % (2 * math.pi) - math.pi


def facing_player(c, p) -> float | None:
    """적의 정면이 플레이어에서 몇 도 벗어나 있나 (0 = 정면으로 봄). 실측: 월드 yaw = heading + π."""
    if c.heading is None:
        return None
    fwd = c.heading + math.pi
    to_p = math.atan2(p.x - c.x, p.z - c.z)
    return abs(math.degrees((to_p - fwd + math.pi) % (2 * math.pi) - math.pi))


class Probe:
    def __init__(self):
        self.run = mr.Runner()          # 텔레메트리·패드·내비메시·휴식을 같이 쓴다
        self.tm, self.pad = self.run.tm, self.run.pad
        # 새 프로세스의 가상 패드를 게임이 못 잡을 때가 있다 (화면 안내가 패드 A 대신 키보드 E — 첫 시도 휴식 2번 실패).
        # 한 번 뺐다 꽂으면 A 로 앉기·B 로 일어나기가 됐다.
        self.pad.reconnect()
        control.focus_game()
        self.hist: dict[int, list] = {}  # ptr → [(t, 적 heading, 나를 보는 각도, 거리)] — 적이 내 움직임을 따라 도는가
        self.stick_sign = 1.0           # 오른스틱 x 부호 — 처음 정렬 때 실측으로 정한다
        self.sign_known = False
        IMG_DIR.mkdir(parents=True, exist_ok=True)

    def align(self, ptr) -> float | None:
        """오른스틱으로 카메라를 그 적에게 (8° 안). 남은 각도(도)를 돌려준다."""
        err_prev = None
        for _ in range(30):
            s = self.tm.snapshot(within=SEE + 5)
            c = next((x for x in s.hostile(SEE + 5) if x.ptr == ptr), None) if s else None
            if not c or s.cam_yaw is None:
                self.pad.look(0, 0)
                return None
            self.note(s)
            err = rel_to_camera(s, c)
            if abs(err) < math.radians(8):
                self.pad.look(0, 0)
                return math.degrees(err)
            if err_prev is not None and not self.sign_known:
                if abs(err) > abs(err_prev):     # 반대로 돌았다
                    self.stick_sign = -self.stick_sign
                self.sign_known = True
            amt = max(0.35, min(0.8, abs(err) / math.radians(60)))
            self.pad.look(self.stick_sign * amt * (1 if err > 0 else -1), 0)
            time.sleep(0.08)
            self.pad.look(0, 0)
            time.sleep(0.05)
            err_prev = err
        self.pad.look(0, 0)
        return None

    def ask_all(self, b64: str, dist: float) -> dict:
        out = {}

        def one(m):
            pick, ms, extra = tactic_llm.gemini_choice(m, "You judge enemy awareness in a game screenshot.", PROMPT.format(d=dist),
                                                       STATES, timeout=20.0, retry_429=0, image_jpeg_b64=b64)
            out[m] = {"state": pick, "ms": round(ms), **({"error": extra["error"][:120]} if extra.get("error") else {})}
        th = [threading.Thread(target=one, args=(m,)) for m in MODELS]
        for t in th:
            t.start()
        for t in th:
            t.join(25)
        return out

    def watch(self, ptr, seconds: float = 3.0) -> dict:
        """찍은 뒤 서서 그 적을 본다 — 행동 정답: 얼마나 다가왔나, 공격 애니가 있었나."""
        t0 = time.time()
        d0 = None
        dmin, attacked, anims = 99.0, False, []
        while time.time() - t0 < seconds:
            s = self.tm.snapshot(within=SEE + 5)
            c = next((x for x in s.hostile(SEE + 5) if x.ptr == ptr), None) if s else None
            if s:
                self.note(s)
            if c:
                d0 = c.dist if d0 is None else d0
                dmin = min(dmin, c.dist)
                if c.anim is not None and (not anims or anims[-1] != c.anim):
                    anims.append(c.anim)
                attacked = attacked or (3000 <= (c.anim or 0) < 3600)
            time.sleep(0.1)
        closed = (d0 - dmin) if d0 is not None else 0.0
        hw = [x for x in self.hist.get(ptr, []) if x[0] >= t0 and x[2] is not None]
        f0, f1 = (hw[0][2], hw[-1][2]) if hw else (None, None)
        turned_to_me = f0 is not None and f1 is not None and f0 - f1 > 30 and f1 < 45   # 내가 서 있는데 나를 향해 30° 넘게 돌았다
        return {"closed_m": round(closed, 1), "attack_anim": attacked, "anims": anims[:8],
                "facing_watch": [None if f0 is None else round(f0), None if f1 is None else round(f1)],
                "turned_to_me": turned_to_me,
                "aware_by_behavior": bool(closed > 1.5 or attacked or turned_to_me)}

    def note(self, s) -> None:
        """25 m 안 적마다 (시각, 몸 방향, 나를 보는 각도, 거리) — 걷는 중·정렬 중·지켜보는 중 전부."""
        now = time.time()
        for c in s.hostile(25.0):
            hh = self.hist.setdefault(c.ptr, [])
            hh.append((now, c.heading, facing_player(c, s.player), c.dist))
            del hh[:-200]

    def tracking(self, ptr, now: float) -> dict:
        """찍기 직전 4 s: 적 몸 방향이 얼마나 돌았나, 그동안 나를 보는 각도는. 내가 움직이는데 적이 따라 돌며 계속 나를 보면 = 알아챔 후보.
        (예전엔 '지금부터 3 s' 로 잘라서 정렬에 몇 초 걸리면 기록이 다 빠졌다 — 첫 3시도 전부 None)"""
        h = [x for x in self.hist.get(ptr, []) if now - x[0] <= 4.0 and x[1] is not None]
        if len(h) < 2:
            return {"turned_deg": None, "facing_3s_ago": None}
        turned = abs(math.degrees((h[-1][1] - h[0][1] + math.pi) % (2 * math.pi) - math.pi))
        return {"turned_deg": round(turned), "facing_3s_ago": None if h[0][2] is None else round(h[0][2])}

    def trial(self, k: int, start_m: float = 0.0) -> None:
        print(f"── 시도 {k} (경로 {start_m:.0f} m 부터): 화톳불 휴식 (적 초기화)", flush=True)
        if not self.run.rest():
            print("   휴식 실패 — 중단", flush=True)
            return
        nm = self.run.nm[mr.MAP_A]
        self.run.cur_nm = nm
        s = self.tm.snapshot(within=1.0)
        path = nm.find_path((s.player.x, s.player.y, s.player.z), mr.BOUND_A)
        if start_m > 0:
            # 첫 할로우만 찍히지 않게 경로 중간으로 워프 (쉬어서 적은 이미 초기화됐다). 방향은 다음 경로점 쪽.
            acc, j = 0.0, 1
            while j < len(path) - 1 and acc < start_m:
                acc += math.dist(path[j - 1], path[j])
                j += 1
            a, b = path[j - 1], path[j]
            self.tm.pos_warp(a[0], a[1], a[2], math.atan2(b[0] - a[0], b[2] - a[2]) - math.pi)   # 월드 yaw = heading + π
            time.sleep(1.5)
            path = path[j - 1:]
        self.hist.clear()
        last_shot_d: dict[int, float] = {}
        stop = {"ptr": None, "near": False}

        def on_tick(sn, _d=None):
            p = sn.player
            stop["near"] = any(c.hp > 0 and not patrol.dormant(c) for c in sn.hostile(25.0))
            self.note(sn)
            for c in sn.hostile(SEE):
                if c.hp <= 0 or patrol.dormant(c) or abs(c.y - p.y) > 4.0:
                    continue
                if c.ptr not in last_shot_d or last_shot_d[c.ptr] - c.dist >= STEP_CLOSER:
                    stop["ptr"] = c.ptr
                    return

        def mode_fn(_s):
            if stop["ptr"]:
                return "retreat"                           # goto 를 곧바로 빠져나오는 신호
            return "creep" if stop["near"] else "walk"     # 적 25 m 안에선 스틱 조금만 (사용자 원칙: 같은 속도로 가면 전부 어그로)

        i = 1
        while i < len(path):
            r = nav.goto(self.tm, self.pad, path[i], tolerance=1.5, timeout=20, log=lambda *a: None,
                         on_tick=on_tick, mode_fn=mode_fn, terrain=nm)
            if r == "dead":
                print("   사망", flush=True)
                return
            if stop["ptr"] is None:
                i += 1
                continue
            ptr = stop["ptr"]
            self.pad.neutral()
            time.sleep(0.3)
            s = self.tm.snapshot(within=SEE + 5)
            c = next((x for x in s.hostile(SEE + 5) if x.ptr == ptr), None) if s else None
            if not c:
                stop["ptr"] = None
                continue
            left = self.align(ptr)
            s = self.tm.snapshot(within=SEE + 5)
            c = next((x for x in s.hostile(SEE + 5) if x.ptr == ptr), None) if s else None
            if not c:
                stop["ptr"] = None
                continue
            feats = {"dist": round(c.dist, 1), "dy": round(c.y - s.player.y, 1), "anim": c.anim, "npc": c.npc_param,
                     "facing_deg": None if facing_player(c, s.player) is None else round(facing_player(c, s.player)),
                     "cam_err_deg": None if left is None else round(left, 1), "start_m": start_m,
                     "pos": [round(c.x, 1), round(c.y, 1), round(c.z, 1)], **self.tracking(ptr, time.time())}
            img, b64, full = capture_crop(self.tm, c)
            ts = time.strftime("%H%M%S")
            name = f"{ts}_{k}_{ptr & 0xFFFF:04x}_{c.dist:.0f}m.jpg"
            if img is not None:
                img.save(IMG_DIR / name, quality=85)
                full.save(IMG_DIR / name.replace(".jpg", "_full.jpg"), quality=80)   # 투영점(빨강)·자른 곳(노랑) 확인용
            ans = self.ask_all(b64, c.dist) if b64 else {}
            self.pad.guard(True)                  # 전투 판단이 안 도니 지켜보는 동안 방패만 든다
            beh = self.watch(ptr)
            self.pad.guard(False)
            row = {"t": time.time(), "trial": k, "img": name, "ptr": ptr, **feats, "gemini": ans, **beh}
            with OUT.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            g = "  ".join(f"{m.split('-')[1]}:{a.get('state')}({a.get('ms')}ms)" for m, a in ans.items())
            print(f"   {c.dist:4.1f} m npc {c.npc_param} anim {c.anim} 나를 보는 각 {feats['facing_deg']}° (3 s 전 {feats['facing_3s_ago']}°, 몸 {feats['turned_deg']}° 돎) | {g} | "
                  f"3 s 행동: {beh['closed_m']} m 다가옴, 공격애니 {beh['attack_anim']}, 보는 각 {beh['facing_watch'][0]}→{beh['facing_watch'][1]}° "
                  f"→ {'알아챔' if beh['aware_by_behavior'] else '모름'}  [{name}]",
                  flush=True)
            last_shot_d[ptr] = c.dist
            stop["ptr"] = None
            if beh["aware_by_behavior"] or c.dist < CLOSEST:
                print("   적이 알아챔/가까움 — 화톳불로", flush=True)
                return
        print("   경로 끝", flush=True)


def main() -> None:
    """python vision_probe.py [시도 수] [--start 0,70,100]  — 시도마다 시작 지점(경로 m)을 돌려 쓴다."""
    args = sys.argv[1:]
    starts = [0.0]
    if "--start" in args:
        starts = [float(x) for x in args[args.index("--start") + 1].split(",")]
        del args[args.index("--start"):args.index("--start") + 2]
    n = int(args[0]) if args else 1
    pr = Probe()
    for k in range(1, n + 1):
        pr.trial(k, starts[(k - 1) % len(starts)])
    pr.pad.neutral()
    pr.run.rest()


if __name__ == "__main__":
    main()
