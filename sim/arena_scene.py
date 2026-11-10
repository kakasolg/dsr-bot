"""Flat arena for the Godot practice room (MoKa M1109-75: "평평한 공간에서 할로우 방패병, 대검 병사 둘이 공격 잘하게
세팅해서, 봇과 싸움을 붙여봐" — MoKa picked the heavy Hollow 255010 and the heavy knight greatsword 257002).

  python sim/arena_scene.py          → sim/godot/assets/arena_scene.json (local only — built from game files)
  python sim/arena_scene.py --set mixed   → the 11-09 pair (heavy Hollow + heavy knight); default "hollows" = two heavy Hollows
                                           (MoKa M1109-78: "중기사를 빼고 작은 병사 2로만")
  open it:  Godot … res://ramp.tscn -- --scene=arena        bot:  BOT_GAME=sim python run.py arena

What goes in, and where it comes from:
  floor      navmesh.Navmesh.flat(): a 40 m square at y 0 — the bot's run.py arena uses the same call [not a DSR map]
  foes       NpcParam (HP), NpcThinkParam (battle start), model, display masks, AtkParam windows (chr_models.json via
             sim/chr_glb.py c2550 / c2570) [game]; positions in the arena [guess]
  behaviour  "attack well" (MoKa's words) as named switches per foe, each tagged: which attacks are lunges / swings and
             which follow which (TAE lengths + root motion [game], the choice [guess]); steps (701–703 root motion [game],
             when they are used [guess]); punish an Estus sip (MoKa M1109-71 "에스트 캐치" — seen from the graveyard skeletons
             11-09 [meas], given to these two foes [guess]); punish a whiffed swing [guess]; guard after an attack
             (the heavy Hollow's shield) [guess]; poise — the knight keeps swinging through a light hit [guess]
Room coordinates are game-like (x, y, z metres), not a place in a DSR map.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import navmesh  # noqa: E402

OUT = ROOT / "sim" / "godot" / "assets" / "arena_scene.json"
HALF = 20.0                                  # arena half size, m [guess]
START = [0.0, 0.0, -8.0]
START_HEADING = PI = 3.141592653589793       # facing +z (heading + π is the facing)
WALK_V, RUN_V = 1.6, 3.5                     # as the ramp room ([guess] / [meas] 11-09 hollows)

# HP: NpcParam MaximumHP [game] (soulstruct read 11-09: 255010 85, 257002 310)
FOES = [
    {"name": "heavy Hollow · longsword + shield", "model": "c2550", "npc": 255010, "think": 25500, "max_hp": 85,
     "pos": [-2.5, 0.0, 6.0], "battle_start": 9, "wake": 20.0, "wake_tag": "guess (arena: both start at once)",
     # TAE root motion [game]: 3005 2.4 m · 3008 2.6 m forward; 3007 three hits 3.4 m; 3000/3003/3004/3006 ≤ 1.4 m
     "lunge": [3005, 3008], "swing": [3000, 3003, 3004, 3006], "combo": {"3000": 3001, "3001": 3002, "3004": 3006},
     "combo_share": 0.6, "long": [3007], "long_share": 0.2,
     "lunge_m": 2.8, "engage_m": 5.5, "think_s": [0.15, 0.45],
     "guard_clip": 3500, "guard_share": 0.45, "guard_s": [0.8, 1.4],
     # c2550 TAE has 701 back 3.5 m, 702 / 703 sideways 3.5 m [game]
     "steps": {"back": 701, "right": 702, "left": 703}, "step_after_attack": 0.35, "step_vs_swing": 0.5,
     "punish_estus": 9.0, "punish_whiff": True, "stagger_share": 1.0,
     # MoKa 11-09 "방패 막는 타이밍 너무 않좋잖아": 내 휘두름을 보고 방패 (ramp.gd _aggro) [guess]
     "guard_vs_swing": 0.85, "guard_react_s": [0.15, 0.3], "guard_react_m": 3.2, "guard_sp_cost": 40, "sp_regen": 30.0},
    {"name": "heavy knight · greatsword", "model": "c2570", "npc": 257002, "think": 25700, "max_hp": 310,
     "pos": [2.5, 0.0, 7.0], "battle_start": 20, "wake": 20.0, "wake_tag": "game",
     # 3005 6.3 m lunge, 3000 / 3001 / 3006 2.25 m, 3002–3004 ~1.5 m, 3007 0.6 m [game root motion]
     "lunge": [3005, 3000], "swing": [3002, 3003, 3004, 3006, 3007], "combo": {"3000": 3001, "3002": 3004, "3003": 3002},
     # MoKa M1109-76 "2타 맞을 확률이 매우 높아": 막힌 뒤에도 이어 치는 비율을 높임 [guess 0.75]
     "combo_share": 0.75, "long": [], "long_share": 0.0,
     "lunge_m": 3.2, "engage_m": 7.5, "think_s": [0.3, 0.8],
     "guard_clip": 0, "guard_share": 0.0, "guard_s": [0, 0],
     "steps": {}, "step_after_attack": 0.0, "step_vs_swing": 0.0,          # c2570 has no 70x steps in its TAE [game]
     "punish_estus": 11.0, "punish_whiff": True, "stagger_share": 0.25},    # [guess] heavy armour: most light hits don't stagger
]


# ── 캐릭터에 맞춘 능력치 (MoKa 11-09 "병사들 스텟을 캐릭터 스텟과 맞추거나 조금 더 강하게 … 기존 스탯을 낮추지는 말고") ──
#  · HP: "맞춘다" = 서로 죽이는 데 드는 타수가 같게. 캐릭터가 이 적의 평균 공격 (AtkParam physical [game])에 죽는 타수 ×
#    클레이모어 약공 한 대 (103² / (103 + PhysicalDefense) — 연습장 공식 [guess]) × STRONGER. 게임 HP보다 낮으면 게임 값
#  · 기력: 캐릭터 98 × STRONGER, NpcParam MaxStamina보다 낮으면 그 값. 공격력·방어력은 게임 값 그대로
PLAYER_HP, PLAYER_SP, CLAYMORE_BASE = 849, 98, 103      # [meas] 11-09 character · [game] EquipParamWeapon 301000
STRONGER = 1.1


def _match_player(f: dict, attacks: dict, npc) -> dict:
    phys = [w["physical"] for k, ws in attacks.items() if int(k) < 4000 for w in ws if w.get("physical")]
    avg = sum(phys) / len(phys) if phys else 150
    to_die = -(-PLAYER_HP // int(avg))                    # hits that kill the character
    per_hit = CLAYMORE_BASE ** 2 / (CLAYMORE_BASE + int(npc.PhysicalDefense))
    hp = max(f["max_hp"], round(to_die * per_hit * STRONGER))
    sp = max(int(npc.MaxStamina), round(PLAYER_SP * STRONGER))
    return {"max_hp": hp, "max_sp": sp, "game_hp": f["max_hp"], "game_sp": int(npc.MaxStamina),
            "match": f"character dies in {to_die} hits (avg {avg:.0f}); Claymore light {per_hit:.0f} × {to_die} × {STRONGER}"}


SETS = {"mixed": [0, 1], "hollows": [0, 0]}   # FOES indices; a repeated foe goes to the next slot's position
SLOTS = [[-2.5, 0.0, 6.0], [2.5, 0.0, 7.0]]


def _params():
    """NpcParam defence and AtkParam_Npc StaminaAttackPower [game] (MoKa M1109-76)."""
    from soulstruct.darksouls1r.params import GameParamBND
    gp = GameParamBND.from_path(navmesh.GAME_DIR / "param" / "GameParam" / "GameParam.parambnd.dcx")
    return gp.Characters, gp.NonPlayerAttacks


def main(which: str = "hollows") -> None:
    nm = navmesh.Navmesh.flat(HALF)
    models = json.loads((ROOT / "data" / "gamefiles" / "chr_models.json").read_text(encoding="utf-8"))
    npcs, atks = _params()
    foes = []
    for i, k in enumerate(SETS[which]):
        f = {**FOES[k], "pos": SLOTS[i]}
        m = models.get(f["model"], {})
        if not m:
            raise SystemExit(f"{f['model']} not in chr_models.json — python sim/chr_glb.py {f['model']}")
        attacks = json.loads(json.dumps(m.get("npc_attacks", {}).get(str(f["npc"]), {})))
        for wins in attacks.values():
            for w in wins:
                if "atk" in w:
                    w["stamina"] = int(atks[int(w["atk"])].StaminaAttackPower)     # SP the player loses on a block [game]
        n = npcs[f["npc"]]
        if which == "hollows":
            f.update(_match_player(f, attacks, n))
        foes.append({"n": i + 1, "heading": 0.0, "floor": True, "dmg": 0, "role": f["name"],
                     "sight": 20, "masks": m.get("npc_masks", {}).get(str(f["npc"]), []),
                     "phys_def": int(n.PhysicalDefense), "guard_cut": int(n.PhysicalGuardCutRate),   # [game]
                     "attacks": attacks, **f})
    # walls on the square's edge (open NavMesh edges), as the ramp room
    walls = []
    for ti, row in enumerate(nm.adj):
        for k in range(3):
            if row[k] < 0:
                p0, p1 = nm.v[nm.t[ti][k]], nm.v[nm.t[ti][(k + 1) % 3]]
                walls.append([round(float(x), 3) for x in (*p0, *p1)])
    g = nm.graph()
    graph = [[[int(n), round(float(w), 3)] for n, w in g.get(i, [])] for i in range(len(nm.t))]
    out = {"source": "sim/arena_scene.py", "name": "arena", "set": which, "flat": HALF, "walls": walls, "graph": graph,
           "centroid": [[round(float(x), 3) for x in c] for c in nm.centroid], "graph_same_mesh": True,
           "bonfire": [HALF - 1.0, 0.0, -HALF + 1.0], "start": START, "start_heading": START_HEADING,
           "walk_v": WALK_V, "run_v": RUN_V,
           "nav": {"v": [[round(float(x), 3) for x in p] for p in nm.v], "t": nm.t.tolist()}, "foes": foes}
    OUT.write_text(json.dumps(out), encoding="utf-8")
    print(f"{OUT}: {len(nm.t)} floor triangles, {len(walls)} wall edges, "
          + ", ".join(f"#{f['n']} {f['model']} {f['npc']} HP {f['max_hp']} SP {f.get('max_sp', '-')} def {f['phys_def']} ({f.get('match', 'game values')})" for f in foes))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", choices=sorted(SETS), default="hollows")
    main(ap.parse_args().set)
