"""Longsword · Claymore · Zweihander comparison sheet + Korean PDF report (MoKa 11-10, Perplexity's 비교표 had the frame /
stamina cells empty). Reads only files — no game, no soulstruct:
  data/gamefiles/weapon_motions.json   (python weapon_motions.py — game files)
  data/probe/*_weapon_probe.jsonl      (python weapon_probe.py — measured in game, 11-10)

  uv run --no-project --with openpyxl --with reportlab python weapon_report.py
  → docs/weapons/weapon_frames_LS_CL_ZW.xlsx, docs/weapons/weapon_frames_LS_CL_ZW.pdf

Grades written next to every number: [게임 파일] read from DSR's files · [게임 실측] measured in the running game ·
[외부] Perplexity / community (APS, wiki poise).
"""
from __future__ import annotations

import json
import math
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MOT = ROOT / "data" / "gamefiles" / "weapon_motions.json"
PROBE = sorted((ROOT / "data" / "probe").glob("*_weapon_probe.jsonl"))
OUTDIR = ROOT / "docs" / "weapons"
NAME = {201000: "롱소드", 301000: "클레이모어", 350000: "츠바이헨더"}
OTHER = {701000: "배틀 액스", 200000: "숏소드", 1050000: "파이크",
         1100000: "할버드", 802000: "모닝스타"}      # measured 11-10, not in the 3-weapon table — 게임_실측 only
WTABLE = ROOT / "data" / "gamefiles" / "weapon_table.json"


def tae_r1(mot, w):
    """1H R1 1st from weapon_motions.json, else weapon_table.json's light attack (same TAE fields)."""
    if w in mot:
        return next(x for x in mot[w]["motions"] if x["grip"] == "1H" and x["motion"] == "R1 1")
    lt = next(v["light"] for v in json.loads(WTABLE.read_text(encoding="utf-8"))["weapons"].values() if v["row"] == w)
    return lt


def tae_2h(w):
    """2H R1 1st straight from the TAE (category·10000 + 4000): startup, cancel flags."""
    cat = next(v["category"] for v in json.loads(WTABLE.read_text(encoding="utf-8"))["weapons"].values() if v["row"] == w)
    ev = json.loads((ROOT / "data" / "gamefiles" / "tae_c0000.json").read_text(encoding="utf-8"))["animations"][str(cat * 10000 + 4000)]["events"]
    first = lambda f: min([round(e["start"], 3) for e in ev if e["type"] == 0 and e["p"] and e["p"][0] == f] or [None])
    return {"startup": round(min(e["start"] for e in ev if e["type"] == 1), 3), "cancel_r": first(4), "cancel_roll": first(26),
            "cancel_move": first(11)}


KO_MOTION = {"R1 1": "R1 1타", "R1 2": "R1 2타", "R1 3": "R1 3타", "R2 1": "R2 1타", "R2 2": "R2 2타",
             "roll R1": "구르기 R1", "backstep/sprint R1": "백스텝·달리기 R1", "jump (fwd+R2)": "점프 (앞+R2)"}
# Perplexity 11-10 sheet (APS from r/darksouls 'attacks-per-second', poise from the Fandom wiki) — [외부]
PPLX_APS = {(201000, "1H"): 1.52, (201000, "2H"): 1.40, (301000, "1H"): 1.01, (350000, "2H"): 0.75}
PPLX_POISE = {(201000, "1H"): 20, (201000, "2H"): 30, (301000, "1H"): 35, (301000, "2H"): 52.5, (350000, "1H"): 50,
              (350000, "2H"): 75}
TARGET_POISE = [0, 20, 40, 53, 60, 80]
# Perplexity 11-10 (MoKa "강화별로 강화 수치"): regular upgrade +0..+15 base physical attack and scaling letters STR/DEX,
# sources darksouls.wikidot.com upgrade tables (Battle Axe: darksouls.fandom.com) — [외부]
UPG = ROOT / "data" / "gamefiles" / "weapon_upgrades.json"        # weapon_upgrades.py [게임 파일]
PPLX_UPGRADE = {
    "Shortsword": [78, 85, 93, 101, 109, 117, 124, 132, 140, 148, 156, 163, 171, 179, 187, 195],
    "Longsword": [80, 88, 96, 104, 112, 120, 128, 136, 144, 152, 160, 168, 176, 184, 192, 200],
    "Claymore": [103, 113, 123, 133, 144, 154, 164, 175, 185, 195, 206, 216, 226, 236, 247, 257],
    "Zweihander": [130, 143, 156, 169, 182, 195, 208, 221, 234, 247, 260, 273, 286, 299, 312, 325],
    "Battle Axe": [95, 104, 113, 123, 133, 142, 152, 161, 171, 180, 190, 199, 209, 218, 228, 237],
    "Morning Star": [83, 91, 99, 107, 116, 124, 132, 141, 149, 157, 166, 174, 182, 190, 199, 207],
    "Pike": [86, 94, 103, 111, 120, 129, 137, 146, 154, 163, 172, 180, 189, 197, 206, 215],
    "Halberd": [110, 121, 132, 143, 154, 165, 176, 187, 198, 209, 220, 231, 242, 253, 264, 275]}
PPLX_LETTERS = {"Shortsword": [("C/C", 0)], "Longsword": [("C/C", 0)], "Claymore": [("C/C", 0)], "Zweihander": [("C/D", 0)],
                "Battle Axe": [("C/D", 0)], "Morning Star": [("C/-", 0), ("B/-", 6)], "Pike": [("D/C", 0), ("D/B", 14)],
                "Halberd": [("D/D", 0), ("D/C", 1)]}          # (letters, from level)
KO_W = {"Shortsword": "숏소드", "Longsword": "롱소드", "Claymore": "클레이모어", "Zweihander": "츠바이헨더",
        "Battle Axe": "배틀 액스", "Morning Star": "모닝스타", "Pike": "파이크", "Halberd": "할버드",
        "Dagger": "대거", "Bandit's Knife": "도적의 단도", "Broadsword": "브로드소드", "Uchigatana": "우치가타나",
        "Mace": "메이스", "Spear": "스피어", "Bastard Sword": "바스타드 소드", "Greatsword": "그레이트소드",
        "Great Club": "그레이트 클럽", "Scimitar": "시미터", "Rapier": "레이피어", "Hand Axe": "핸드 액스", "Club": "클럽",
        "Reinforced Club": "강화 클럽", "War Pick": "워 픽", "Caestus": "세스터스"}


SCL = ROOT / "data" / "gamefiles" / "weapon_scaling.json"       # weapon_scaling.py [게임 파일 + 추정 공식]


# 11-10 게임 상태 화면에서 읽은 한손 공격력 (data/shop/20261110_upgrade 스크린샷 21·28·33·80·85): (무기, 강화, 근, 기, 숫자)
AR_SEEN = [("Battle Axe", 1, 14, 9, 118), ("Battle Axe", 1, 24, 10, 138), ("Zweihander", 1, 24, 10, 189),
           ("Zweihander", 5, 24, 10, 257), ("Battle Axe", 5, 24, 10, 188),
           ("Zweihander", 5, 32, 10, 279), ("Battle Axe", 5, 32, 10, 204),
           # 반반 (BASE 복원 뒤, data/shop/20261110_upgrade_half 19·65 및 status-p5-20-20 / 75)
           ("Longsword", 1, 16, 12, 105), ("Claymore", 1, 16, 12, 136), ("Longsword", 5, 16, 12, 144), ("Claymore", 5, 16, 12, 185),
           ("Longsword", 5, 20, 20, 171), ("Claymore", 5, 20, 20, 220), ("Longsword", 5, 25, 25, 185), ("Claymore", 5, 25, 25, 239),
           # 기량 (BASE 복원 뒤, data/shop/20261110_upgrade_dex)
           ("Halberd", 1, 16, 12, 141), ("Rapier", 1, 16, 12, 92), ("Halberd", 5, 16, 12, 192), ("Rapier", 5, 16, 12, 125),
           ("Halberd", 5, 16, 20, 216), ("Rapier", 5, 16, 20, 148), ("Halberd", 5, 16, 30, 236), ("Rapier", 5, 16, 30, 166)]


# 11-11 타이타나이트 데몬에 R1 1타, 근16/기30: +5 = data/probe/20261111_002707·002855, +1 = 20261111_003727·003915 (BASE 복원 뒤 같은 능력치)
# (무기, 잡기, 모션 %, +1 공격력, +1 피해, +5 공격력, +5 피해) — 공격력은 계산값
DEMON_HITS = [("Rapier", "한손", "100", 122, 21, 166, 44), ("Longsword", "한손", "100", 129, 24, 176, 52),
              ("Battle Axe", "한손", "100", 142, 34, 193, 74), ("Claymore", "한손", "100", 166, 45, 227, 97),
              ("Halberd", "한손", "100", 173, 55, 236, 117), ("Zweihander", "양손", "120?", 211, 119, 288, 206)]


# 11-11 스태미나 소모 켜고 R1 12초 연타 (weapon_probe.py --modes sustain): +1 = data/probe/20261111_013349·013433·013610,
# +5 = 20261111_013727·013923. (무기, 잡기, 한 타 스태미나, 첫 바 타수, 첫 바 끝 s, 바닥난 뒤 타 간격 s, +1 피해, +5 피해)
# 롱소드+1 첫 바는 6으로 찍혔지만 첫 바 셈을 고치기 전 기록 — 로그로는 5타 3.12 s (+5와 같음)
SUSTAIN = [("Rapier", "한손", 20, 5, 3.04, 1.25, 21, 44), ("Longsword", "한손", 20, 5, 3.14, 1.45, 24, 52),
           ("Battle Axe", "한손", 25, 4, 3.72, 1.73, 34, 74), ("Claymore", "한손", 30, 4, 3.72, 2.29, 45, 97),
           ("Halberd", "한손", 30, 4, 3.82, 2.04, 55, 117), ("Zweihander", "양손", 60, 2, 2.23, 2.72, 119, 206)]


# 11-11 지구력 → 최대 스태미나 (데몬 백업 세이브, 화톳불 레벨업 뒤 메모리 +0x3FC로 읽음, MoKa M1111-05)
END_STAMINA = [(14, 98), (16, 102), (18, 106), (20, 110), (22, 115), (23, 117), (24, 119), (25, 121), (26, 124), (28, 129),
               (30, 133), (32, 139), (34, 144), (36, 149), (38, 154), (40, 160)]


def scaling_tables():
    """MoKa 11-10 1단계: per category (근력 · 반반 · 기량) the AR of every weapon of that category along that category's
    stat line, +1 and +5, one- and two-handed. → (curves, {cat: (points, rows)}) or None without the JSON.
    rows: [weapon, req 'S/D', grip, ar+1 per point..., ar+5 per point...]; None = requirement not met."""
    if not SCL.exists():
        return None
    d = json.loads(SCL.read_text(encoding="utf-8"))
    out = {}
    for cat, pts in d["lines"].items():
        pts = [tuple(p) for p in pts]
        rows = []
        for name, v in sorted(d["weapons"].items(), key=lambda x: x[1]["row"]):
            if v["category"] != cat:
                continue
            for grip in ("1H", "2H"):
                ar = {(r["level"], r["str"], r["dex"]): r["ar"] for r in v["rows"] if r["grip"] == grip and r["line"] == cat}
                rows.append([("★ " if v.get("pick") else "") + KO_W.get(name, name), f"{v['req_str']}/{v['req_dex']}", grip,
                             [ar[(1, s, dx)] for s, dx in pts], [ar[(5, s, dx)] for s, dx in pts]])
        out[cat] = (pts, rows)
    return d["curves"], out


def _pplx_letter(name, lv):
    return [l for l, f in PPLX_LETTERS[name] if lv >= f][-1]


def upgrade_rows():
    """Game file upgrade values vs Perplexity (+0..+15), one row per weapon and level. [] without the JSON."""
    if not UPG.exists():
        return []
    rows = []
    for name, v in json.loads(UPG.read_text(encoding="utf-8"))["weapons"].items():
        for lv in v["levels"]:
            l, g, p = lv["level"], lv["phys"], PPLX_UPGRADE[name][lv["level"]]
            fl = math.floor(g + 1e-3)          # 소수 배율의 103.9999… 오차를 넘겨 내림
            rows.append([KO_W[name], l, lv["phys_rate"], g, fl, p, p - fl, lv["str"], lv["dex"], _pplx_letter(name, l)])
    return rows
F = lambda t: None if t is None else round(t * 30)          # TAE steps are 1/30 s


def load():
    mot = json.loads(MOT.read_text(encoding="utf-8"))["weapons"]
    probe = [dict(json.loads(l), _file=p.stem) for p in PROBE for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    return {int(k): v for k, v in mot.items()}, probe


def measured(probe, grip="1H"):
    """{(weapon row base, mode): (median, n)} for hit / R / roll / move — R1 1st in that grip (2H: --grip 2h, 11-10 Pike)."""
    off = 3000 if grip == "1H" else 4000
    out = {}
    for w in {r["weapon"] - r["weapon"] % 100 for r in probe}:
        for mode, key in (("single", "hit"), ("chain", "end"), ("roll", "end"), ("move", "end")):
            v = [r[key] for r in probe if r["weapon"] - r["weapon"] % 100 == w and r["mode"] == mode and r.get(key) is not None
                 and r.get("grip", "1H") == grip
                 and not r.get("note") and (mode != "single" or r.get("damage"))
                 # 츠바이헨더 한손 R1은 애니가 3.2 s 창보다 길어 'did not end'로 남음 — 맞는 순간(hit)은 그대로 씀 (11-10 180530)
                 and (not r.get("error") or (key == "hit" and r["error"] == "attack did not end in the window"))
                 and r.get("anim") is not None and r["anim"] % 10000 == off        # R1 1st only (Pike gave 363030, 11-10)
                 and not (40 <= (r.get("next_anim") or 0) % 1000 < 50)             # x3040: swing on a dead foe (P-153)
                 and (r.get("next_anim") or 0) % 1000 != 150]          # x3150 = wall bounce (first-run stick bug), not a cancel
            if v:
                out[(w, mode)] = (round(statistics.median(v), 3), len(v))
    return out


def r1_cycle(ws_motions, grip):
    """Steady R1 mash: 1 → 2 → 3 → 2 → 3 … (seen in game: 233000 → 233001 → 233002 → 233001 …). Cycle = mean R-cancel of 2 and 3."""
    m = {x["motion"]: x for x in ws_motions if x["grip"] == grip}
    c = [m[k]["cancel_r"] for k in ("R1 2", "R1 3") if k in m and m[k]["cancel_r"]]
    return round(sum(c) / len(c), 3) if c else None


def rows_dps(mot, meas, meas2=None):
    out = []
    for rid, e in mot.items():
        for grip in ("1H", "2H"):
            ms = [x for x in e["motions"] if x["grip"] == grip and x["motion"].startswith("R1")]
            if not ms:
                continue
            cyc = r1_cycle(e["motions"], grip)
            h = ms[0]["hits"][0]
            mv, poise, sp = h["mv"], h["poise"], ms[0]["stamina"]
            ar = e["base_physical"]
            shift = None
            mm_ = meas if grip == "1H" else (meas2 or {})
            if (rid, "chain") in mm_ and ms[0]["cancel_r"]:
                shift = round(mm_[(rid, "chain")][0] - ms[0]["cancel_r"], 3)        # measured R-cancel of R1 1 − its TAE flag
            cyc_game = round(cyc + shift, 3) if (cyc and shift is not None) else None
            aps_pplx = PPLX_APS.get((rid, grip))
            out.append({"weapon": NAME[rid], "row": rid, "grip": grip, "mv": mv, "ar": ar, "dmg_hit": round(ar * mv / 100, 1),
                        "poise": poise, "stamina": sp, "cycle_tae": cyc, "aps_tae": round(1 / cyc, 3) if cyc else None,
                        "shift": shift, "cycle_game": cyc_game, "aps_pplx": aps_pplx,
                        "cycle_pplx": round(1 / aps_pplx, 3) if aps_pplx else None,
                        "dps_tae": round(ar * mv / 100 / cyc, 1) if cyc else None,
                        "poise_s": round(poise / cyc, 1) if cyc else None, "sp_s": round(sp / cyc, 1) if cyc else None,
                        "dmg_per_sp": round(ar * mv / 100 / sp, 2) if sp else None, "startup": ms[0]["startup"]})
    return out


def build_xlsx(mot, probe, meas, dps, path: Path, meas2=None):
    meas2 = meas2 or {}
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    wb = Workbook()
    head = Font(bold=True, color="FFFFFF")
    fill = PatternFill("solid", fgColor="44546A")
    inp = PatternFill("solid", fgColor="DDEBF7")

    def sheet(title, header, rows, widths=None):
        ws = wb.create_sheet(title)
        ws.append(header)
        for c in ws[1]:
            c.font, c.fill = head, fill
            c.alignment = Alignment(wrap_text=True, vertical="center")
        for r in rows:
            ws.append(r)
        ws.freeze_panes = "A2"
        for i, h in enumerate(header, 1):
            ws.column_dimensions[get_column_letter(i)].width = (widths or {}).get(i, max(9, min(28, len(str(h)) + 4)))
        return ws

    wb.remove(wb.active)
    sheet("읽어보기", ["항목", "설명"], [
        ["범위", "Dark Souls Remastered, 무기 +0, 오른손. 롱소드(201000) · 클레이모어(301000) · 츠바이헨더(350000), 한손(1H)·양손(2H)."],
        ["등급", "[게임 파일] = DSR 설치 폴더의 TAE(c0000)·EquipParamWeapon·BehaviorParam_PC·AtkParam_Pc에서 읽은 값. "
                 "[게임 실측] = 실행 중 게임에서 잰 값 (weapon_probe.py, 2026-11-10, R1 1타만: 롱소드 한손·양손, 클레이모어 한손, 츠바이헨더 한손·양손; "
                 "비교용 배틀 액스·숏소드·할버드·모닝스타 한손, 파이크 한손·양손). "
                 "[외부] = Perplexity 시트의 APS(커뮤니티)·강인도(위키)."],
        ["시간·프레임", "초(s)와 30 fps 프레임(f). TAE 이벤트는 1/30 s 단위. 60 fps 프레임 = 30 fps 프레임 × 2."],
        ["선딜", "애니메이션 시작 → 첫 공격 판정 시작 (TAE type 1). 누름 → 애니 시작은 게임 실측 0.003~0.018 s (1프레임 안)."],
        ["활성", "공격 판정 구간 합. '판정 끝' = 마지막 판정 끝."],
        ["후딜", "판정 끝 → 그 행동이 처음 허용되는 순간: 다음 R (TAE 플래그 4) · 구르기 (26) · 이동 (11). '끝까지' = 애니 전체 길이."],
        ["실측과의 차이", "게임에서 잰 R1 1타의 끊기가 TAE 플래그보다 0.08~0.13 s 일렀음 (다음 R·구르기·이동 모두, 잰 무기 8종). "
                         "예외 하나: 할버드 한손 구르기는 0.20 s 이름 (0.967 vs 1.167, 5판 모두 같음 — 원인 안 봄). "
                         "그래서 파일의 후딜은 '늦어도 이때' 값. 맞는 순간은 판정 시작 뒤 1~3 프레임."],
        ["강인도", "무기 BasePoiseDamage × AtkParam PoiseAttackPercentage / 100. 공식은 추정이나, 결과가 위키 값(Perplexity S3)과 6개 R1 모두 같음."],
        ["스태미나", "BehaviorParam_PC StaminaCost (휘두를 때 드는 기력). '가드 깎기'는 AtkParam StaminaAttackPower (상대 방패 기력)."],
        ["DPS 지수", "+0, 능력치 보정 없음, 적 방어 무시: 무기 기본 물리 공격력 × 모션 배율(%) / R1 연타 주기. 실제 피해 비교가 아니라 같은 조건의 상대 비교."],
        ["모션 이름", "게임에서 한 번씩 해 보고 애니 번호로 확인 (11-10, 클레이모어): R1 x3000→x3001→x3002, R2 x3300, 구르기 R1 x3900, "
                    "백스텝 R1·달리기 R1 둘 다 x3500, 앞+R2 점프 x3600, 양손 +1000. R2 2타(x3301)는 번호 규칙으로 붙임 (안 해 봄)."],
        ["츠바이헨더 실측", "양손 R1: 옆에 벽이 있으면 칼끝이 닿아 튕김(264150)으로 넘어감 — "
                          "튕긴 판은 뺐고, 끊기 값은 벽이 옆에 없는 자리의 5판씩 (P-157). 맞는 시각은 거리에 따라 0.783 (1.6 m 이내) ~ 0.850 s (3.0 m). "
                          "한손 R1: 근력 24가 된 뒤 11-10 저녁에 잼 (전엔 16이라 미달). 한 대마다 적이 밀려 벽에 붙으면 튕김(263150)이 나와 "
                          "20판 중 다수를 뺐음 — 다음 R1 3판 · 구르기 6판 · 이동 6판, 맞는 순간 1.067 s (1.6 m, 5판)."],
        ["빈칸", "클레이모어 양손 R2 (744300): 게임에서 이 애니가 나왔지만 추출한 TAE에 판정 이벤트가 없음 (다른 애니를 가리키는 이벤트만) — 채우지 않음. "
                "츠바이헨더는 R2 2타 애니가 없음."],
    ], {1: 14, 2: 120})
    hdr = ["무기", "잡기", "모션", "애니", "선딜 s", "선딜 f", "활성 s", "활성 f", "판정 끝 s", "판정 수", "다음R 허용 s", "구르기 허용 s",
           "이동 허용 s", "후딜→R f", "후딜→구르기 f", "후딜→이동 f", "애니 길이 s", "스태미나", "모션 배율 %", "강인도 1타", "강인도 2타",
           "가드 깎기", "게임에서 확인", "등급"]
    rows = []
    for rid, e in mot.items():
        for m in e["motions"]:
            hs = m["hits"]
            p2 = hs[1]["poise"] if len(hs) > 1 and hs[1].get("atk") != hs[0].get("atk") else None
            rows.append([NAME[rid], m["grip"], KO_MOTION.get(m["motion"], m["motion"]), m["anim"], m["startup"], F(m["startup"]),
                         m["active"], F(m["active"]), m["blade_end"], len(hs), m["cancel_r"], m["cancel_roll"], m["cancel_move"],
                         F(m["rec_r"]), F(m["rec_roll"]), F(m["rec_move"]), m["length"], m["stamina"], hs[0].get("mv"),
                         hs[0].get("poise"), p2, hs[0].get("stamina_dmg"), "애니 번호 확인" if m["seen_in_game"] else "번호 규칙",
                         "게임 파일"])
        if rid == 301000:
            rows.append([NAME[rid], "2H", "R2 1타", 744300] + [None] * 18 + ["애니 번호 확인", "빈칸 — TAE에 판정 이벤트 없음"])
    sheet("모션_프레임", hdr, rows, {3: 16, 23: 14, 24: 26})
    hdr = ["무기", "잡기", "R1 모션 배율 %", "기본 공격력", "1타 피해 지수", "강인도/타", "스태미나/타", "R1 연타 주기 s (파일)",
           "초당 타수 (파일)", "실측 보정 s", "R1 연타 주기 s (실측 보정)", "Perplexity APS", "APS 주기 s", "DPS 지수 (파일)",
           "강인도/초", "스태미나/초", "피해/스태미나", "R1 선딜 s"]
    sheet("R1연타_DPS", hdr, [[d["weapon"], d["grip"], d["mv"], d["ar"], d["dmg_hit"], d["poise"], d["stamina"], d["cycle_tae"],
                              d["aps_tae"], d["shift"], d["cycle_game"], d["aps_pplx"], d["cycle_pplx"], d["dps_tae"],
                              d["poise_s"], d["sp_s"], d["dmg_per_sp"], d["startup"]] for d in dps])
    # stagger: hits needed and time to the staggering hit, target poise is an input cell (blue)
    ws = wb.create_sheet("경직_비교")
    ws.append(["상대 강인도 (입력)", 53])
    ws["B1"].fill = inp
    ws.append([])
    ws.append(["무기", "잡기", "강인도/타", "R1 선딜 s", "R1 연타 주기 s", "필요 명중 수", "경직까지 s (첫 누름부터)", "전제"])
    for c in ws[3]:
        c.font, c.fill = head, fill
    for i, d in enumerate(dps, start=4):
        ws.append([d["weapon"], d["grip"], d["poise"], d["startup"], d["cycle_tae"],
                   f"=IF(C{i}>0,MAX(1,CEILING($B$1/C{i},1)),\"\")",
                   f"=IF(ISNUMBER(F{i}),D{i}+(F{i}-1)*E{i},\"\")",
                   "강인도 회복·면역 없음, 모든 타 명중, 주기는 TAE (실측은 0.1 s 빠름)"])
    for col, wdt in zip("ABCDEFGH", (14, 6, 10, 10, 14, 12, 22, 50)):
        ws.column_dimensions[col].width = wdt
    hdr = ["무기", "잡기·모션", "잰 것", "실측 중앙값 s", "횟수", "TAE 값 s", "차이 s"]
    rows = []
    for (w, mode), (v, n) in sorted(meas.items()):
        m = tae_r1(mot, w)
        tae = {"single": m["startup"], "chain": m["cancel_r"], "roll": m["cancel_roll"], "move": m["cancel_move"]}[mode]
        what = {"single": "맞는 순간 (적 HP가 준 프레임)", "chain": "다음 R1 시작", "roll": "구르기 시작", "move": "이동 시작"}[mode]
        rows.append([NAME.get(w) or OTHER.get(w, w), "1H R1 1타", what, v, n, tae, round(v - tae, 3)])
    for (w, mode), (v, n) in sorted(meas2.items()):
        m = tae_2h(w)
        tae = {"single": m["startup"], "chain": m["cancel_r"], "roll": m["cancel_roll"], "move": m["cancel_move"]}[mode]
        what = {"single": "맞는 순간 (적 HP가 준 프레임)", "chain": "다음 R1 시작", "roll": "구르기 시작", "move": "이동 시작"}[mode]
        rows.append([NAME.get(w) or OTHER.get(w, w), "2H R1 1타", what, v, n, tae, round(v - tae, 3)])
    sheet("게임_실측", hdr, rows, {3: 30})
    hdr = ["무기", "잡기", "Perplexity 강인도", "게임 파일 강인도", "같음?", "Perplexity APS", "파일 주기로 본 APS", "실측 보정 APS"]
    sheet("Perplexity_대조", hdr, [[d["weapon"], d["grip"], PPLX_POISE.get((d["row"], d["grip"])), d["poise"],
                                   "같음" if PPLX_POISE.get((d["row"], d["grip"])) == d["poise"] else "다름",
                                   d["aps_pplx"], d["aps_tae"], round(1 / d["cycle_game"], 3) if d["cycle_game"] else None]
                                  for d in dps])
    crow, r2, by_cat, differ, off = class_table(meas)
    sheet("무기_묶음", ["무기", "보고서 이름", "애니 묶음", "무게", "칼 길이 m", "선딜 s", "다음R 허용 s", "구르기 허용 s", "이동 허용 s",
                       "스태미나", "실측 맞음 s", "실측 다음R s", "실측 구르기 s", "실측 이동 s"], crow, {1: 16, 2: 12})
    ws = wb["무기_묶음"]
    ws.append([])
    ws.append(["읽는 법", "한손 R1 1타. 애니 묶음 = EquipParamWeapon AttackAnimationCategory (TAE 구역). [게임 파일] + 실측 칸 [게임 실측]."])
    ws.append(["결론", "같은 묶음 안의 무기는 무게·길이가 달라도 선딜·끊기 시점이 모두 같음 "
                       f"(묶음 {len(by_cat)}개 중 다른 값이 있는 묶음 {len(differ)}개). 게임 실측도 숏소드 = 롱소드 (4개 값 모두 같음)."])
    ws.append(["무게·길이 상관 (R², 23종)", " · ".join(f"{k}: 무게 {a} / 길이 {b}" for k, (a, b) in r2.items())
               + " — 무거운 무기가 느린 묶음에 많아서 생긴 상관. 같은 묶음 안에서는 영향 0. 스태미나만 묶음 안에서도 다를 수 있음 (스피어 25 · 파이크 30)."])
    ws.append(["실측 − TAE (묶음별)", " · ".join(f"{c}: " + ", ".join(f"{n} {m} {d:+.3f}" for n, m, d in v) for c, v in sorted(off.items()))])
    urows = upgrade_rows()
    if urows:
        sheet("강화_대조", ["무기", "강화", "물리 배율", "게임 파일 물리 (계산)", "파일 내림", "Perplexity 물리", "차이 (P − 내림)", "근력 보정 수치",
                          "기량 보정 수치", "Perplexity 등급 근/기"], urows, {1: 12})
        ws = wb["강화_대조"]
        ws.append([])
        ws.append(["읽는 법", "일반 강화 +0~+15. 게임 파일 = EquipParamWeapon 기본 공격력 × ReinforceParamWeapon 배율, 보정 수치도 같은 식 "
                             "[게임 파일, weapon_upgrades.py]. Perplexity = 위키 강화표 (wikidot, 배틀 액스는 fandom) [외부]."])
        ws.append(["결론", "8종 모두 같은 강화표 (배율 +1마다 0.1, +15 = 2.5배). 위키 물리값 = 파일 계산의 소수점 내림, 128칸 중 "
                           "배틀 액스 +2 하나만 1 다름 (파일 114, fandom 113). 메뉴에 뜨는 값은 안 봄. 마법·화염·번개는 전 단계 0 (파일)."])
        ws.append(["등급 글자", "게임 파일엔 숫자만 있고 글자 기준이 없어 판정 못 함. 위키 글자는 한 기준으로 설명됨: 50 이하 D · 51~77 C · "
                              "82.5부터 B — 모닝스타 +6 B, 파이크 +14 B, 할버드 +1 C가 파일 숫자가 그 선을 넘는 단계와 맞음 [추정 기준]."])
    sc = scaling_tables()
    if sc:
        curves, cats = sc
        for cat, (pts, rows) in cats.items():
            lab = [f"근{s}/기{d}" for s, d in pts]
            sheet(f"계산_{cat}", ["무기", "요구 근/기", "잡기"] + [f"+1 {x}" for x in lab] + [f"+5 {x}" for x in lab],
                  [[r[0], r[1], r[2]] + ["미달" if a is None else a for a in r[3]] + ["미달" if a is None else a for a in r[4]]
                   for r in rows], {1: 14})
            ws = wb[f"계산_{cat}"]
            ws.append([])
            ws.append(["읽는 법", "공격력(물리) = 기본×강화 + 기본×강화×(보정×강화 배율/100)×곡선(능력치)/100, 근력·기량 각각 더함, 내림. "
                                 "양손은 근력×1.5. 값은 [게임 파일], 공식은 [추정 — 2단계에서 게임으로 확인]. '미달' = 요구치 못 채움 (페널티 모름)."])
            ws.append(["곡선 (CalcCorrectGraph 0, 24종 모두)", " · ".join(f"능력치 {k} → {v}%" for k, v in curves["0"]["at"].items())])
    sheet("출처", ["ID", "내용"], [
        ["게임 파일", "weapon_motions.py → data/gamefiles/weapon_motions.json (DSR: c0000.anibnd TAE, GameParam)"],
        ["게임 실측", "weapon_probe.py → data/probe/20261110_*.jsonl (2026-11-10. 새벽: 교구 병사 255041, 락온 1.4 m. "
                      "롱소드 한손·양손: 성벽 마을 병사 255001, 1.4 m. 츠바이헨더 양손: 성벽 마을 망자 병사 254010, 1.6 m. "
                      "저녁 (근력 24): 할버드·모닝스타·파이크 한손 망자 254011 1.4 m, 츠바이헨더 한손 254010 · 254011 1.4~1.6 m)"],
        ["모션 번호", "게임에서 모션 한 번씩 (교구 화톳불, 클레이모어 한손·양손, 2026-11-10)"],
        ["외부 S1", "r/darksouls 'Comprehensive List of Attacks-Per-Second Multipliers' (Perplexity 시트의 APS)"],
        ["외부 S3", "darksouls.fandom.com Poise (Dark Souls) (Perplexity 시트의 강인도)"],
    ], {2: 110})
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def build_pdf(mot, meas, dps, path: Path, meas2=None, probe=()):
    meas2 = meas2 or {}
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    pdfmetrics.registerFont(TTFont("Malgun", r"C:\Windows\Fonts\malgun.ttf"))
    pdfmetrics.registerFont(TTFont("MalgunB", r"C:\Windows\Fonts\malgunbd.ttf"))
    H1 = ParagraphStyle("h1", fontName="MalgunB", fontSize=15, leading=20, spaceAfter=6)
    H2 = ParagraphStyle("h2", fontName="MalgunB", fontSize=11.5, leading=16, spaceBefore=8, spaceAfter=4)
    P = ParagraphStyle("p", fontName="Malgun", fontSize=9, leading=13.5)
    S = ParagraphStyle("s", fontName="Malgun", fontSize=7.5, leading=10)

    def table(data, widths):
        t = Table([[Paragraph(str("" if c is None else c), S) for c in r] for r in data], colWidths=widths, repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#44546A")),
                               ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
                               ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
        for c in t._cellvalues[0]:
            c.style = ParagraphStyle("hd", parent=S, textColor=colors.white, fontName="MalgunB")
        return t

    f = lambda v: "-" if v is None else (f"{v:.2f}" if isinstance(v, float) else str(v))
    st = []
    st.append(Paragraph("롱소드 · 클레이모어 · 츠바이헨더 프레임 비교 (Dark Souls Remastered)", H1))
    st.append(Paragraph("2026-11-10 · 숫자 옆 등급: [게임 파일] 게임 데이터에서 읽음 · [게임 실측] 실행 중 게임에서 잼 · [외부] Perplexity·커뮤니티", P))
    st.append(Paragraph("1. 무엇을 만들었고 어디까지 확인했나", H2))
    st.append(Paragraph(
        "세 무기의 한손·양손 모션(R1 1~3타, R2, 구르기 R1, 백스텝·달리기 R1, 점프 공격)마다 선딜·활성·판정 끝·다음 행동 허용 시점·"
        "스태미나·모션 배율·강인도를 DSR 게임 파일에서 뽑았다 [게임 파일]. 모션 이름은 게임에서 한 번씩 해 보고 애니 번호로 맞췄다. "
        "강인도는 Perplexity 시트의 위키 값과 R1 여섯 칸이 모두 같았다 (독립 출처 대조 통과). 프레임은 R1 1타만 게임에서 쟀다 [게임 실측]: "
        "롱소드 한손·양손, 클레이모어 한손, 츠바이헨더 한손·양손 (한손은 근력 24가 된 뒤 잼, 튕긴 판이 많아 횟수 적음). "
        "R1 2·3타와 나머지 모션, 클레이모어 양손은 파일 값만 있다. 클레이모어 양손 R2는 빈칸이다.", P))
    st.append(Paragraph("2. R1 연타: DPS 지수 · 강인도/초 · 스태미나/초 [게임 파일]", H2))
    data = [["무기", "잡기", "선딜 s", "연타 주기 s", "실측 보정 주기", "Perplexity APS 주기", "1타 피해 지수", "DPS 지수", "강인도/타",
             "강인도/초", "스태미나/타", "스태미나/초"]]
    for d in dps:
        data.append([d["weapon"], d["grip"], f(d["startup"]), f(d["cycle_tae"]), f(d["cycle_game"]), f(d["cycle_pplx"]),
                     f(d["dmg_hit"]), f(d["dps_tae"]), f(d["poise"]), f(d["poise_s"]), d["stamina"], f(d["sp_s"])])
    st.append(table(data, [16 * mm, 10 * mm] + [14 * mm] * 10))
    st.append(Spacer(1, 3 * mm))
    st.append(Paragraph(
        "DPS 지수 = 기본 물리 공격력 × R1 모션 배율 / 연타 주기 (+0, 능력치·적 방어 없음). 연타 주기는 R1 2·3타의 '다음 R 허용' TAE 플래그 평균. "
        "실측 보정은 게임에서 잰 R1 1타의 '다음 R1 시작'이 플래그보다 이른 만큼을 2·3타 주기에서 뺀 값이다 (잰 조합만; 2·3타 자체는 안 잼). "
        "Perplexity의 커뮤니티 APS 주기(롱소드 0.66 s, 클레이모어 0.99 s)는 파일 플래그보다 실측 보정 값에 더 가깝다 — "
        "게임이 플래그보다 조금 일찍 다음 입력을 받는다는 실측과 맞는 방향이다 (원인은 확인 안 함).", P))
    st.append(Paragraph("3. 핵심 비교", H2))
    for line in summary_lines(mot, dps):
        st.append(Paragraph("· " + line, P))
    st.append(Paragraph("4. 게임 실측 (R1 1타, 락온 1.4~1.6 m)", H2))
    data = [["무기", "잰 것", "실측 s", "횟수", "TAE s", "차이 s"]]
    for (w, mode), (v, n) in sorted(meas.items()):
        m = tae_r1(mot, w)
        tae = {"single": m["startup"], "chain": m["cancel_r"], "roll": m["cancel_roll"], "move": m["cancel_move"]}[mode]
        what = {"single": "맞는 순간", "chain": "다음 R1 시작", "roll": "구르기 시작", "move": "이동 시작"}[mode]
        data.append([NAME.get(w) or OTHER.get(w, w), what, f(v), n, f(tae), f(round(v - tae, 3))])
    for (w, mode), (v, n) in sorted(meas2.items()):
        m = tae_2h(w)
        tae = {"single": m["startup"], "chain": m["cancel_r"], "roll": m["cancel_roll"], "move": m["cancel_move"]}[mode]
        what = {"single": "맞는 순간", "chain": "다음 R1 시작", "roll": "구르기 시작", "move": "이동 시작"}[mode]
        data.append([(NAME.get(w) or OTHER.get(w, w)) + " (양손)", what, f(v), n, f(tae), f(round(v - tae, 3))])
    st.append(table(data, [25 * mm, 35 * mm, 20 * mm, 15 * mm, 20 * mm, 20 * mm]))
    st.append(Paragraph(
        "배틀 액스·숏소드(비교용)와 클레이모어 '이동'은 11-10 두 번째 측정에서 잼. 파이크는 R1에 보통 첫 공격(363000) 대신 느린 363030이 나와 "
        "한손으로는 못 잼 — 요구 근력 24, 캐릭터 16 (MoKa: 요구 스탯 미달). 양손(근력 ×1.5 = 24)으로 잼. 근력 24가 된 뒤(11-10 저녁) 한손 R1은 "
        "보통 첫 공격 363000으로 나와 20판 모두 잼 — 미달 때 363030이 나온 것과 맞음. 적이 연타에 죽은 뒤의 판(x3040)·벽 튕김(x3150)은 뺐음 (P-153). 횟수는 표에 있음. "
        "츠바이헨더 양손 R1은 옆에 벽이 있으면 칼끝이 닿아 튕김(264150)으로 넘어간다 (화면으로 확인, P-157) — 튕긴 판은 빼고 벽이 옆에 없는 자리에서 잰 값이다. "
        "맞는 시각은 거리에 따라 0.783 (1.6 m 이내) ~ 0.850 s (3.0 m). 츠바이헨더 한손도 한 대마다 적이 밀려 벽에 붙으면 튕겨(263150) 튕긴 판을 뺐다. "
        "할버드·모닝스타 한손은 5판씩 튕김 없음. 할버드 한손 구르기만 플래그보다 0.20 s 이름 (다른 무기는 0.08~0.13 s).", P))
    st.append(Paragraph("5. 경직(강인도) 비교", H2))
    data = [["무기", "잡기", "강인도/타"] + [f"상대 {p}: 타수 / 초" for p in TARGET_POISE[1:]]]
    for d in dps:
        row = [d["weapon"], d["grip"], f(d["poise"])]
        for p in TARGET_POISE[1:]:
            n = max(1, math.ceil(p / d["poise"])) if d["poise"] else None
            t = d["startup"] + (n - 1) * d["cycle_tae"] if (n and d["cycle_tae"]) else None
            row.append(f"{n} / {f(t)}")
        data.append(row)
    st.append(table(data, [18 * mm, 10 * mm, 15 * mm] + [24 * mm] * 5))
    st.append(Paragraph(
        "타수 = 올림(상대 강인도 / 강인도 1타), 시간 = 선딜 + (타수−1) × 연타 주기 [계산]. 강인도 회복·경직 면역·피격 뒤 리셋은 넣지 않았다. "
        "강인도 1타 공식(무기 기본 강인도 × AtkParam %)은 추정이지만 위키 값과 같다.", P))
    st.append(Paragraph("6. 무게·길이와 프레임: 규칙은 '무기 종류(애니 묶음)'", H2))
    crow, r2, by_cat, differ, off = class_table(meas)
    st.append(Paragraph(
        f"게임 파일의 무기 {len(crow)}종(세스터스는 한손 R1 값이 없어 뺌)을 공격 애니 묶음(EquipParamWeapon AttackAnimationCategory = TAE 구역)으로 "
        f"나누면, 같은 묶음 안의 무기는 무게·칼 길이가 달라도 선딜·다음 R·구르기·이동 허용 시점이 모두 같다 (묶음 {len(by_cat)}개 중 다른 값이 있는 묶음 "
        f"{len(differ)}개) [게임 파일]. 예: 스피어 3.5 / 1.72 m와 파이크 10 / 2.48 m, 숏소드 2.0 / 1.10 m와 롱소드 3.0 / 1.31 m. "
        "게임에서도 숏소드와 롱소드의 맞음 · 다음 R1 · 구르기 · 이동 네 값이 같았다 [게임 실측]. 즉 무게나 길이로 계산하는 공식은 없고, "
        "묶음마다 정해진 표다.", P))
    data = [["묶음", "무기 (무게)", "선딜", "다음R", "구르기", "이동"]]
    tab_w = {r[0]: r[3] for r in crow}
    for c, m in sorted(by_cat.items()):
        t = m[0][1]
        data.append([c, ", ".join(f"{n} ({tab_w[n]:g})" for n, _ in m)] + [f(x) for x in t])
    st.append(table(data, [12 * mm, 90 * mm, 17 * mm, 17 * mm, 17 * mm, 17 * mm]))
    st.append(Spacer(1, 3 * mm))
    st.append(Paragraph(
        "23종을 한꺼번에 보면 무거울수록 느리다 — R² " + " · ".join(f"{k} 무게 {a} / 길이 {b}" for k, (a, b) in r2.items()) +
        ". 무거운 무기가 느린 묶음에 많아서 생긴 상관이고, 같은 묶음 안에서는 영향이 없다. 그래서 weapon_table.py의 평균식"
        "(선딜 ≈ a + b·길이 + c·무게)은 묶음 사이 경향일 뿐 무기 하나의 값을 맞히는 공식이 아니다. 스태미나만 묶음 안에서도 다를 수 있다 "
        "(스피어 25 · 파이크 30). 봇에 쓸 때: 새 무기는 묶음 번호만 보고, 같은 묶음에서 잰 값을 쓴다.", P))
    st.append(Paragraph(
        "실측 − TAE 끊기 플래그 (묶음별): " + " · ".join(f"{c}: " + ", ".join(f"{n} {m} {d:+.3f}" for n, m, d in v)
                                                     for c, v in sorted(off.items())) +
        ". 대부분 −0.1 s (30 fps 3프레임), 대검·특대검(25 · 26)은 −0.133 s (4프레임), 할버드 구르기만 −0.2 s — 묶음마다 1~2종만 재서 "
        "이 차이가 묶음 규칙인지는 아직 가설이다.", P))
    urows = upgrade_rows()
    if urows:
        st.append(Paragraph("7. 강화 수치 (일반 +0~+15): 파일 vs Perplexity", H2))
        st.append(Paragraph(
            "Perplexity에 테스트한 무기 8종의 일반 강화표를 물었고 (출처 darksouls.wikidot 강화표, 배틀 액스는 fandom) [외부], "
            "게임 파일 (EquipParamWeapon 기본 공격력 × ReinforceParamWeapon 배율) [게임 파일]과 대조했다. "
            "8종 모두 같은 강화표를 쓴다: 물리 배율 +1마다 0.1, +15에서 2.5배. 보정 수치 배율은 +1·+6·+11·+14에서 오르고 +15에서 1.2배. "
            "위키 물리값은 파일 계산값의 소수점 내림과 같다 (클레이모어 +5: 154.5 → 154) — 128칸 중 배틀 액스 +2 하나만 1 다르다 "
            "(파일 114, fandom 113). 게임 메뉴에 실제로 뜨는 값은 안 봤다. 마법·화염·번개는 전 단계 0 [게임 파일].", P))
        data = [["무기", "+0", "+5", "+10", "+15", "위키와 다른 단계 (위키 − 파일 내림)", "근력 보정 +0→+15", "기량 보정 +0→+15", "위키 등급 근/기"]]
        by = {}
        for r in urows:
            by.setdefault(r[0], []).append(r)
        for n, rs in by.items():
            dif = ", ".join(f"+{r[1]} {r[6]:+d}" for r in rs if r[6]) or "없음"
            let = " → ".join(f"{l}" + (f" (+{fr}부터)" if fr else "") for l, fr in PPLX_LETTERS[next(k for k, v in KO_W.items() if v == n)])
            data.append([n] + [str(rs[i][4]) for i in (0, 5, 10, 15)] + [dif, f"{rs[0][7]:g} → {rs[15][7]:g}",
                                                                      f"{rs[0][8]:g} → {rs[15][8]:g}", let])
        st.append(table(data, [17 * mm, 11 * mm, 11 * mm, 11 * mm, 11 * mm, 44 * mm, 20 * mm, 20 * mm, 37 * mm]))
        st.append(Spacer(1, 3 * mm))
        st.append(Paragraph(
            "보정 등급 글자는 게임 파일 (GameParam)에 없고 숫자만 있어 위키 글자를 판정하지 못했다. 다만 위키 글자는 한 기준으로 모순 없이 "
            "설명된다: 50 이하 D (할버드 기량 50) · 51~77 C (클레이모어 51, 파이크 기량 77) · 82.5부터 B (모닝스타 +6). 그 기준이면 "
            "모닝스타 +6 B, 파이크 +14 B, 할버드 +1 C가 파일 숫자가 선을 넘는 단계와 정확히 맞는다 [추정 기준]. 단계별 전체 값은 xlsx '강화_대조'.", P))
    sc = scaling_tables()
    if sc:
        curves, cats = sc
        st.append(Paragraph("8. 능력치·강화별 공격력 계산표 (1단계): 근력 · 반반 · 기량", H2))
        at = curves["0"]["at"]
        st.append(Paragraph(
            "MoKa 11-10: +1과 +5를 비교하고, 근력·기량별로 어떤 무기가 강한지 — 먼저 게임 파일로 계산하고, 게임에서는 몇 점만 확인한다. "
            "무기 24종을 +0 보정 비율로 셋으로 나눴다: 근력 보정 몫 0.6 이상 '근력', 0.4 이하 '기량', 나머지 '반반'. 카테고리마다 올릴 능력치 줄을 "
            "BASE 세이브(SL14, 근력 14, 기량 9)에서 시작해 정했다 (기량 줄은 할버드 요구 근력 16에 맞춰 근력 16). ★ = MoKa가 고른 대표 무기 (인기 무기, 게임에서 잴 것): "
            "근력 츠바이헨더·배틀 액스, 반반 롱소드·클레이모어, 기량 할버드·레이피어 — 할버드는 비율로는 반반(근력 몫 0.43)이지만 MoKa가 기량 대표로 정해 기량으로 옮겼다. "
            "나머지는 추가 보강. 값: 기본 공격력·요구치·보정·강화 배율·능력치 곡선은 [게임 파일], "
            "공식(기본×강화 + 기본×강화×보정×곡선, 양손 근력×1.5, 내림)은 [추정] — 2단계에서 상태 화면 숫자와 실제 피해로 확인한다. "
            "요구치 미달 칸은 비웠다 (게임의 페널티 값을 모름; 파이크 근력 16에서 느린 363030과 피해 1이 나온 것만 실측). "
            f"능력치 곡선 (24종 모두 같은 CalcCorrectGraph 0): 10 → {at['10']}% · 20 → {at['20']}% · 30 → {at['30']}% · "
            f"40 → {at['40']}% · 99 → {at['99']}% — 10~20 구간이 1당 3.5%로 가장 가파르고, 20~40은 1당 2.25%, 40 뒤는 1당 0.25%.", P))
        f0 = lambda a: "-" if a is None else str(a)
        for cat, (pts, rows) in cats.items():
            st.append(Paragraph(f"8-{'근반기'.index(cat[0]) + 1}. {cat} — 한손, 칸 = +1 / +5", P))
            data = [["무기", "요구 근/기"] + [f"근{s}<br/>기{d}" for s, d in pts]]
            for r in rows:
                if r[2] != "1H":
                    continue
                data.append([r[0], r[1]] + [f"{f0(a)} / {f0(b)}" for a, b in zip(r[3], r[4])])
            best = ["가장 셈 (+5)", ""]
            for i in range(len(pts)):
                c = [(r[4][i], r[0]) for r in rows if r[2] == "1H" and r[4][i] is not None]
                best.append(max(c)[1] if c else "-")
            data.append(best)
            n = len(pts)
            st.append(table(data, [22 * mm, 13 * mm] + [(182 - 35) / n * mm] * n))
            st.append(Spacer(1, 2 * mm))
        sw = json.loads(SCL.read_text(encoding="utf-8"))["weapons"]
        calc = lambda n, lv, s, d: next(r["ar"] for r in sw[n]["rows"] if r["level"] == lv and r["grip"] == "1H" and r["str"] == s and r["dex"] == d)
        data = [["무기", "강화", "근/기", "상태 화면", "계산", "같음"]]
        for n, lv, s, d, seen in AR_SEEN:
            c = calc(n, lv, s, d) if (s, d) != (14, 9) else 118
            data.append([KO_W.get(n, n), f"+{lv}", f"{s}/{d}", str(seen), str(c), "O" if c == seen else "X"])
        st.append(Paragraph(
            "8-4. 게임 대조 (근력·반반·기량, 한손) — 상태 화면 R Weapon 숫자 vs 계산. 11-10 BASE 세이브에서 화톳불(무기 강화상자)로 레벨업·강화하며 "
            "읽었고, 카테고리마다 BASE로 되돌려 다시 시작했다. "
            f"{sum(r[-1] == 'O' for r in data[1:])}/{len(data) - 1} 같음 → 공식은 대표 무기 6종·이 능력치에서 [게임 확인]. "
            "상태 화면 숫자만 본 것이고 실제 피해(적 방어·모션 배율)는 아직 안 쟀다. 근14/기9 계산은 표 줄 밖이라 직접 계산(118.47).", P))
        st.append(table(data, [30 * mm, 14 * mm, 18 * mm, 24 * mm, 18 * mm, 14 * mm]))
        st.append(Spacer(1, 2 * mm))
        data = [["무기", "잡기", "공격력<br/>+1 / +5", "피해<br/>+1 / +5", "공격력<br/>배수", "피해<br/>배수", "피해/공격력<br/>+1 / +5", "죽이는 타수<br/>+1 / +5"]]
        for n, g, mv, a1, d1, a5, d5 in DEMON_HITS:
            data.append([KO_W.get(n, n), g, f"{a1} / {a5}", f"{d1} / {d5}", f"{a5 / a1:.2f}", f"{d5 / d1:.2f}",
                         f"{d1 / a1:.2f} / {d5 / a5:.2f}", f"{math.ceil(1506 / d1)} / {math.ceil(1506 / d5)}"])
        st.append(Paragraph(
            "8-5. 타이타나이트 데몬(NpcParam 230001, HP 1506, 물리 방어 파일값 168)에 R1 1타 — 11-11, 근16/기30 SL37, 6종 모두 +5. "
            "weapon_probe.py (캐릭터 무적·적 공격/이동/AI 끔, 매 타 전에 적 HP 되돌림), 무기마다 3번 쳐서 3번 모두 같은 값. "
            "공격력은 계산값(할버드·레이피어 한손은 이 능력치에서 상태 화면 확인, 나머지는 공식으로만). 모션 % = AtkParam_Pc 첫 타 "
            "PhysicalAttackPowerPercentage — 한손 R1은 6종 모두 100, 츠바이 양손은 첫 타 행이 어느 것인지 안 확인 [추정 120]. "
            "같은 모션 100인데 공격력 166→236 (1.42배)에서 피해는 44→117 (2.66배): 방어가 높은 적에게는 공격력 차이가 피해에서 크게 벌어진다. "
            "+1 → +5 (같은 근16/기30, +1은 BASE 복원 뒤 다시 올려 잼): 공격력은 모두 1.36배인데 한손 피해는 2.10~2.18배, 츠바이 양손은 1.73배. "
            "레이피어+5(166)와 클레이모어+1(166)이 44·45 — 모션이 같으면 피해는 무기가 아니라 공격력으로 정해짐. "
            "후보 식 [추정]: DS3식 방어 곡선에 방어 216을 넣으면 한손 10점이 평균 4.3 차이로 맞음 (파일 168 × 1.2 = 202 근처, HP도 파일 1255 → 게임 1506 = 1.2배).", P))
        st.append(table(data, [22 * mm, 11 * mm, 22 * mm, 20 * mm, 16 * mm, 16 * mm, 26 * mm, 24 * mm]))
        st.append(Spacer(1, 2 * mm))
        data = [["무기", "잡기", "한 타<br/>스태미나", "첫 바<br/>타수 / 초", "몰아치기 DPS<br/>+1 / +5", "바닥 뒤<br/>타 간격", "지속 DPS<br/>+1 / +5",
                 "1506 잡는 시간 s<br/>+1 / +5"]]
        for n, g, cost, k, tk, gap, d1, d5 in SUSTAIN:
            def kill(d):
                n_ = math.ceil(1506 / d)
                return tk / max(k - 1, 1) * (min(n_, k) - 1) + max(0, n_ - k) * gap
            data.append([KO_W.get(n, n), g, str(cost), f"{k} / {tk:.1f}", f"{d1 * k / tk:.0f} / {d5 * k / tk:.0f}", f"{gap:.2f}",
                         f"{d1 / gap:.0f} / {d5 / gap:.0f}", f"{kill(d1):.0f} / {kill(d5):.0f}"])
        st.append(Paragraph(
            "8-6. 스태미나를 넣은 DPS (MoKa M1111-03) — 같은 데몬, 스태미나 소모를 켜고 R1을 12초 계속 누름 (캐릭터 무적, 데몬 공격·AI 끔). "
            "최대 스태미나 98 (지구력 14), 회복은 6종 모두 초당 45 (게임에서 잰 값, 손 뗀 뒤 0.05~1.3 s 지나 시작). 스태미나는 휘두를 때 빠지고 0 아래로 내려가도 "
            "그 타는 나감 (98→…→−2). '첫 바' = 가득 찬 상태에서 바닥날 때까지, '바닥 뒤 타 간격' = 그 뒤 회복분으로 한 타씩 칠 때의 간격. "
            "타수·간격은 +1과 +5가 같고 피해만 바뀜. 실제 싸움에서는 구르기·막기용 스태미나를 남기므로 이 값은 위쪽 한계. "
            "죽이는 시간 = 첫 바를 쓰고 바닥 뒤 간격으로 계속 쳤을 때 [계산, 측정 로그로].", P))
        st.append(table(data, [22 * mm, 11 * mm, 16 * mm, 20 * mm, 26 * mm, 16 * mm, 24 * mm, 28 * mm]))
        st.append(Spacer(1, 2 * mm))
        st.append(Paragraph(
            "8-7. 츠바이헨더 두 타에 필요한 지구력 (MoKa M1111-05: '츠바이는 두 번 때릴 수 있게 지구력을 올리는 게 보통'). "
            "한 타 스태미나는 게임 파일 BehaviorParam_PC (츠바이 양손 R1 = 60, 한손 R1 = 45; 양손 R1 모션 120) — 실측과 같음. "
            "구르기 30 · 백스텝 20 (데몬 앞에서 잼). 지구력 1당 최대 스태미나 +2~3: "
            + " · ".join(f"{e}→{s}" for e, s in END_STAMINA) + ". "
            "두 타(120)가 마이너스 없이 = 지구력 25 (121). 두 타 + 구르기(150) = 지구력 37 근처 (36→149, 38→154). "
            "지구력 40 (160)에서 같은 데몬 연타: 츠바이 양손 첫 바 3타 (160→100→40→−20), 12초 DPS 86 → 103; 할버드 6타, 78 → 88. "
            "회복은 지구력과 상관없이 초당 45. 무게: 장비 무게 46% (24.9/54)와 23% (18.4/80)에서 한 타 소모·회복이 같았음 — "
            "50% 넘는 무거운 장비는 아직 안 잼 (MoKa M1111-06: 방어구·전체 무게도 영향).", P))
        fr = fight_rows(probe)
        if fr:
            ends = sorted({k[2] for k in fr})
            data = [["무기", "잡기", "한 타<br/>피해"] + [f"지구력 {SP_END.get(e, '?')} (최대 {e})<br/>처치 s · 타수 · 쫓은 s · 피격" for e in ends]]
            for (w, g) in sorted({k[:2] for k in fr}, key=lambda k: min(r["kill_s"] or 999 for kk, rs in fr.items() if kk[:2] == k for r in rs)):
                cells = []
                for e in ends:
                    rs = fr.get((w, g, e), [])
                    cells.append("<br/>".join(f"{r['kill_s']:.0f} · {r['hits']} · {r['far_s']:.0f} · {r['taken_hits']}" if r["killed"]
                                              else f"못 잡음 {r['secs']:.0f} s" for r in rs) or "-")
                top = max((statistics.mode([h[1] for h in r["hit_log"]]) for (w_, g_, _), rs in fr.items() if (w_, g_) == (w, g)
                           for r in rs if r["hit_log"]), default=None)
                data.append([NAME.get(w) or OTHER.get(w) or KO_W.get(RAPIER.get(w, ""), str(w)), "양손" if g == "2H" else "한손", str(top)] + cells)
            st.append(Paragraph(
                "8-8. 실전 처치 시간 (MoKa M1111-08: '제한 시키지 말고 실제 전투를 시키고, 캐릭터는 무적') — 같은 데몬 (HP 1506), 데몬의 AI·공격·이동을 켜고 "
                "스태미나 소모도 켬. 플레이어만 죽지 않게 (NO_DEAD, HP 반 아래면 다시 채움). 모든 무기 같은 정책: 락온, 2.3 m 밖이면 걸어 붙고 안이면 스태미나 > 0일 때 R1 연타 "
                "— 회피·가드·구르기 없음, 데몬 공격도 다 맞음. 4 m 앞에서 시작, 무기 +5, 근력 16 · 기량 30, 판마다 데몬 살아 있는 세이브 복원. "
                "'처치 s' = 시작부터 HP 0까지, '쫓은 s' = 2.3 m 밖이라 걷던 시간 (데몬이 물러나거나 맞아서 밀린 시간 포함), '피격' = 맞은 횟수 "
                "(무적이 아니면 피격 합이 최대 HP 849를 넘은 판은 죽었음). 판마다 데몬 행동이 달라 같은 무기도 차이가 큼 — 한두 판이라 순위는 [잠정]. "
                "한 타 피해 = 가장 많이 나온 값 (그 밖의 작은 값은 마지막 타의 남은 HP, 큰 값은 데몬이 공격 중일 때 맞은 것으로 보임 [추정]). "
                "읽은 것: 처치에 드는 타수는 무기마다 거의 고정 (한 타 피해로 정해짐), 시간 차이는 대부분 '쫓은 s' — 데몬이 물러나고 밀어내는 데서 생김. "
                "2.3 m 안에서 스태미나가 바닥나 못 친 시간은 판마다 0~9 s라, 지구력 40의 효과는 이 판수로는 쫓은 시간 차이에 묻힘. "
                "받은 피해 합이 최대 HP 849 아래인 판은 할버드 지구력 40 한 판 (828)뿐 — 회피 없이 맞받아 치면 나머지는 다 죽음.", P))
            st.append(table(data, [24 * mm, 12 * mm, 14 * mm] + [(182 - 50) / len(ends) * mm] * len(ends)))
            st.append(Spacer(1, 2 * mm))
        fm = fight_rows(probe, mortal=True)
        if fm:
            ends = sorted({k[2] for k in fm})
            data = [["무기", "잡기"] + [f"지구력 {SP_END.get(e, '?')} (최대 {e})<br/>깎은 % · 버틴 s · 타수 · 피격" for e in ends]]
            def cut(k):
                v = [r["foe_cut_pct"] for kk, rs in fm.items() if kk[:2] == k for r in rs]
                return -sum(v) / len(v)
            for (w, g) in sorted({k[:2] for k in fm}, key=cut):
                cells = []
                for e in ends:
                    rs = fm.get((w, g, e), [])
                    cells.append("<br/>".join((f"처치 {r['secs']:.0f} s · {r['hits']} · {r['taken_hits']}" if r["killed"] else
                                               f"{r['foe_cut_pct']:.0f}% · {r['secs']:.0f} · {r['hits']} · {r['taken_hits']}") for r in rs) or "-")
                data.append([NAME.get(w) or OTHER.get(w) or KO_W.get(RAPIER.get(w, ""), str(w)), "양손" if g == "2H" else "한손"] + cells)
            st.append(Paragraph(
                "8-9. 무적 끄고 죽을 때까지 (MoKa M1111-09: '무적도 꺼버리고 … 하던 방식 그대로 … 캐릭터 죽을때 까지') — 8-8과 같은 정책·무기·세이브, "
                "무적(NO_DEAD)은 데몬 앞으로 옮겨 착지할 때까지만 (P-158: 끄고 옮기면 17 m 낙하 피해) — HP 가득이 1 s 유지된 뒤 끄고 시작, HP를 다시 채우지 않음, 에스트 안 마심. "
                "'깎은 %' = 죽을 때 데몬 HP가 1506에서 얼마나 줄었나. 캐릭터 최대 HP 849. 무기별 공략 방법은 일부러 안 씀 (같은 조건 비교). "
                "읽은 것: 모든 판이 데몬에게 4~6대 맞고 죽음 (한 대 200~290), 버틴 시간 9~34 s. 같은 무기도 판마다 5~90%로 갈려 판수 2~3으로는 순위가 [잠정] — "
                "중앙값은 할버드·츠바이가 위, 배틀 액스·레이피어가 아래. 지구력 40의 효과는 안 보임. 시작 HP가 덜 찬 판과 P-158 무효 판은 표에서 뺌. "
                "뒤쪽 4판부터 데몬 동작 번호도 남김 (trace 7번째, 피격 기록 3번째: 3000~3006 = 공격으로 보임 [추정]).", P))
            st.append(table(data, [24 * mm, 12 * mm] + [(182 - 36) / len(ends) * mm] * len(ends)))
            st.append(Spacer(1, 2 * mm))
        st.append(Spacer(1, 2 * mm))
        st.append(Paragraph(
            "양손 값과 +0·+15는 xlsx '계산_근력 · 계산_반반 · 계산_기량'과 data/gamefiles/weapon_scaling.json. '가장 셈'은 한 대 공격력(물리)만 본 것 — "
            "연타 속도·모션 배율·적 방어를 넣은 DPS는 3단계.", P))
    st.append(Paragraph("9. 남은 것", H2))
    for line in ("R1 2·3타, R2·구르기·백스텝·점프 공격, 클레이모어 양손의 프레임을 게임에서 재기 (지금은 파일 값만). 츠바이헨더 한손은 튕김 때문에 3~6판뿐.",
                 "실측이 플래그보다 0.08~0.13 s 빠른 이유 (입력 선행 받기인지, 애니 시계를 읽는 방식 탓인지), 할버드 구르기 0.2 s.",
                 "클레이모어 양손 R2(744300)의 판정 — TAE 다른 애니 참조를 따라가 읽기.",
                 "실제 피해: 능력치·강화·적 방어를 넣은 DPS (지금은 +0 지수)."):
        st.append(Paragraph("· " + line, P))
    SimpleDocTemplate(str(path), pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=14 * mm,
                      bottomMargin=14 * mm, title="롱소드·클레이모어·츠바이헨더 프레임 비교").build(st)


SP_END = {v: k for k, v in END_STAMINA}
RAPIER = {601000: "Rapier"}


def fight_rows(probe, mortal=False):
    """{(weapon base, grip, max stamina): [fight rows]} — weapon_probe.py --modes fight (M1111-08). Max stamina = the first
    trace sample (fight() fills stamina before it starts)."""
    out = {}
    for r in probe:
        if r.get("mode") != "fight" or not r.get("trace") or bool(r.get("mortal")) != mortal:
            continue
        if r.get("mortal") and "20261111_053225" <= r.get("_file", "") <= "20261111_054203_weapon_probe":   # P-158: 낙하 피해로 무효
            continue
        if r.get("mortal") and r["trace"][0][3] < r.get("player_max_hp", 0):          # 착지 피해가 남은 채 시작 (P-158 두 번째)
            continue
        out.setdefault((r["weapon"] - r["weapon"] % 100, r.get("grip", "1H"), r["trace"][0][2]), []).append(r)
    return out


def _r2(xs, ys):
    """R² of a one-variable least-squares line (pure python — the report runs without numpy)."""
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    syy = sum((y - my) ** 2 for y in ys)
    return round(sxy * sxy / (sxx * syy), 2) if sxx and syy else None


def class_table(meas):
    """MoKa 11-10 "길이나 무게에 의한 규칙이나 공식": every weapon in weapon_table.json by attack-animation category
    (TAE section) with weight, blade reach, the 1H R1 1st TAE times and the game measurement where there is one.
    → (rows, per-key R² for weight / reach, categories whose members differ, measured − TAE per category)."""
    tab = json.loads(WTABLE.read_text(encoding="utf-8"))["weapons"]
    ws = sorted(((n, v) for n, v in tab.items() if v.get("light")), key=lambda x: (x[1]["category"], x[1]["weight"]))
    keys = ("startup", "cancel_r", "cancel_roll", "cancel_move")
    rows, by_cat, off = [], {}, {}
    for n, v in ws:
        lt, rid = v["light"], v["row"]
        m = [meas.get((rid, mode)) for mode in ("single", "chain", "roll", "move")]
        rows.append([n, NAME.get(rid) or OTHER.get(rid, ""), v["category"], v["weight"], lt.get("hit_reach")]
                    + [lt[k] for k in keys] + [lt["stamina"]] + [x[0] if x else None for x in m])
        by_cat.setdefault(v["category"], []).append((n, tuple(lt[k] for k in keys)))
        for mode, k in (("chain", "cancel_r"), ("roll", "cancel_roll"), ("move", "cancel_move")):
            if (rid, mode) in meas:
                off.setdefault(v["category"], []).append((n, mode, round(meas[(rid, mode)][0] - lt[k], 3)))
    pts = [(v["weight"], v["light"]["hit_reach"], v["light"]) for _, v in ws if v["light"].get("hit_reach")]
    r2 = {k: (_r2([p[0] for p in pts], [p[2][k] for p in pts]), _r2([p[1] for p in pts], [p[2][k] for p in pts]))
          for k in keys + ("stamina",)}
    differ = {c: m for c, m in by_cat.items() if len({t for _, t in m}) > 1}
    return rows, r2, by_cat, differ, off


def summary_lines(mot, dps):
    by = {(d["row"], d["grip"]): d for d in dps}
    ls, cl, zw = by.get((201000, "1H")), by.get((301000, "1H")), by.get((350000, "2H"))
    out = []
    if ls and cl:
        out.append(f"한손 R1 선딜: 롱소드 {ls['startup']:.2f} s ({F(ls['startup'])} f), 클레이모어 {cl['startup']:.2f} s ({F(cl['startup'])} f), "
                   f"츠바이헨더 {by[(350000, '1H')]['startup']:.2f} s — 무게 3 · 6 · 10 순으로 늦어짐.")
        out.append(f"한손 DPS 지수: 롱소드 {ls['dps_tae']} · 클레이모어 {cl['dps_tae']} · 츠바이헨더 {by[(350000, '1H')]['dps_tae']} "
                   f"(+0 기본 공격력 80 · 103 · 130). 무거운 무기는 1타가 세지만 주기가 길어 지수가 비슷하거나 낮다.")
    if zw:
        out.append(f"양손 츠바이헨더: 강인도/타 {zw['poise']} (롱소드 한손의 {zw['poise'] / ls['poise']:.1f}배), "
                   f"강인도/초 {zw['poise_s']} — 경직을 거는 힘은 가장 크지만 선딜 {zw['startup']:.2f} s.")
    for rid in mot:
        r = [m for m in mot[rid]["motions"] if m["motion"] == "roll R1"]
        if r:
            out.append(f"{NAME[rid]} 구르기 R1 선딜 {r[0]['startup']:.2f} s — 같은 무기 R1 1타보다 훨씬 빠름 (파일 값, 게임에서 안 잼).")
    return out


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    mot, probe = load()
    meas = measured(probe)
    dps = rows_dps(mot, meas, measured(probe, "2H"))
    x, p = OUTDIR / "weapon_frames_LS_CL_ZW.xlsx", OUTDIR / "weapon_frames_LS_CL_ZW.pdf"
    meas2 = measured(probe, "2H")
    build_xlsx(mot, probe, meas, dps, x, meas2)
    build_pdf(mot, meas, dps, p, meas2, probe)
    print("2H", meas2)
    for d in dps:
        print(d)
    print(meas)
    print(f"→ {x}\n→ {p}")


if __name__ == "__main__":
    main()
