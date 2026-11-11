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
F = lambda t: None if t is None else round(t * 30)          # TAE steps are 1/30 s


def load():
    mot = json.loads(MOT.read_text(encoding="utf-8"))["weapons"]
    probe = [json.loads(l) for p in PROBE for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
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


def build_pdf(mot, meas, dps, path: Path, meas2=None):
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
    st.append(Paragraph("7. 남은 것", H2))
    for line in ("R1 2·3타, R2·구르기·백스텝·점프 공격, 클레이모어 양손의 프레임을 게임에서 재기 (지금은 파일 값만). 츠바이헨더 한손은 튕김 때문에 3~6판뿐.",
                 "실측이 플래그보다 0.08~0.13 s 빠른 이유 (입력 선행 받기인지, 애니 시계를 읽는 방식 탓인지), 할버드 구르기 0.2 s.",
                 "클레이모어 양손 R2(744300)의 판정 — TAE 다른 애니 참조를 따라가 읽기.",
                 "실제 피해: 능력치·강화·적 방어를 넣은 DPS (지금은 +0 지수)."):
        st.append(Paragraph("· " + line, P))
    SimpleDocTemplate(str(path), pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=14 * mm,
                      bottomMargin=14 * mm, title="롱소드·클레이모어·츠바이헨더 프레임 비교").build(st)


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
    build_pdf(mot, meas, dps, p, meas2)
    print("2H", meas2)
    for d in dps:
        print(d)
    print(meas)
    print(f"→ {x}\n→ {p}")


if __name__ == "__main__":
    main()
