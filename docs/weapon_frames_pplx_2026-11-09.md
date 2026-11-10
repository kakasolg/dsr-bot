# Weapon length · startup · recovery (MoKa M1109-82/83, 2026-11-09)

MoKa: "퍼플렉시티 검색으로 칼 길이, 선 딜레이, 후 딜레이 표를 조사 시켜봐" · "이 것으로 무기별 밸런스를 맞추는 데 이게 없으면
공정성을 잃게 되는 거지" · "하나 하나는 몰라도 나름의 평균 공식은 있을거야, 그걸 개별 무기 마다 약간 변경 시키는 거지".

## 1. Perplexity (built-in browser, 11-09 23:37, 77 sources) — summary, not a copy
- It found **no verified per-weapon reach or startup / active / recovery numbers** in sources it could read. It filled
  only weights (wiki) and rough stamina estimates (an old Reddit post whose author warns the values may be wrong), and left
  every timing column "not verified" instead of guessing.
- Named datasets it could not read the numbers from: KC / The Lag Wizard `dark_souls_animation_data` (via Mimic's Ledger;
  Claymore under "Fast Greatsword" class data), undakovrist "Effective Weapon Ranges" (tests against an Undead Burg Hollow
  Soldier), an attacks-per-second list (explicitly not startup / recovery).
- Its view of the mechanism: timing comes from the weapon's **animation category** in the TAE (attack anim id = motion
  category + hand + action), not from a weight or length formula; weapons in one family can still differ per action
  (R2 especially). It pointed at the TAE (DSAnimStudio / Souls Modding docs) as the place to get real numbers.

## 2. From the game files — `python weapon_table.py` → `data/gamefiles/weapon_table.json`
Every number below is read from DSR's files [game]: EquipParamWeapon (weight, category), c0000 TAE (one-handed light 1 =
category·10000 + 3000, heavy 1 = +3300: blade window, first cancel by move / roll / next R), BehaviorParam_PC (stamina),
AtkParam_Pc hitbox points on the weapon model's FLVER dummies ("reach" = farthest hitbox point from the grip + radius —
**not** reach from the player's centre, which adds arm and swing). Times in s of animation time.

| weapon | weight | category | blade reach m | R1 startup | active | move cancel | roll cancel | R1 → R | recovery (move) | R1 SP | R2 startup | R2 recovery | R2 SP |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Dagger | 0.5 | 20 | 0.68 | 0.33 | 0.10 | 0.77 | 0.67 | 0.60 | 0.33 | 14 | 0.43 | 0.47 | 30 |
| Bandit's Knife | 1.0 | 20 | 0.80 | 0.33 | 0.10 | 0.77 | 0.67 | 0.60 | 0.33 | 14 | 0.43 | 0.47 | 30 |
| Broadsword | 3.0 | 23 | 1.17 | 0.53 | 0.13 | 1.03 | 0.90 | 0.77 | 0.37 | 20 | 0.73 | 0.50 | 32 |
| Longsword | 3.0 | 23 | 1.31 | 0.53 | 0.13 | 1.03 | 0.90 | 0.77 | 0.37 | 20 | 0.73 | 0.50 | 45 |
| Spear | 3.5 | 36 | 1.72 | 0.57 | 0.13 | 1.07 | 0.90 | 0.87 | 0.37 | 25 | 0.77 | 0.60 | 55 |
| Battle Axe | 4.0 | 30 | 1.02 | 0.63 | 0.13 | 1.23 | 1.10 | 1.10 | 0.47 | 25 | 0.83 | 0.70 | 50 |
| Mace | 4.0 | 33 | 1.01 | 0.63 | 0.13 | 1.30 | 1.17 | 1.17 | 0.53 | 25 | – | – | – |
| Uchigatana | 5.0 | 29 | 1.50 | 0.43 | 0.13 | 1.00 | 0.87 | 0.80 | 0.43 | 24 | 0.80 | 0.80 | 54 |
| Claymore | 6.0 | 25 | 1.68 | 0.67 | 0.13 | 1.57 | 1.40 | 1.17 | 0.77 | 30 | 0.90 | 0.83 | 70 |
| Bastard Sword | 6.0 | 25 | 1.45 | 0.67 | 0.13 | 1.57 | 1.40 | 1.17 | 0.77 | 30 | 0.90 | 0.83 | 60 |
| Halberd | 6.0 | 38 | 2.13 | 0.57 | 0.17 | 1.33 | 1.17 | 1.17 | 0.60 | 30 | 0.87 | 0.83 | 55 |
| Zweihander | 10.0 | 26 | 2.06 | 0.97 | 0.17 | 2.07 | 1.87 | 1.77 | 0.93 | 45 | 0.93 | 1.40 | 70 |
| Greatsword | 12.0 | 26 | 2.00 | 0.97 | 0.17 | 2.07 | 1.87 | 1.77 | 0.93 | 45 | 0.93 | 1.40 | 80 |
| Great Club | 12.0 | 35 | 2.06 | 1.00 | 0.17 | 2.17 | 1.97 | 1.97 | 1.00 | 35 | 1.27 | 1.60 | 80 |

Mace R2: no anim 333300 in the TAE — its heavy uses another id (not looked up).

**Checked against the game itself** (in-game measurements in `souls/weapons.py`, 09-25 … 10-13): Claymore startup 0.675 s,
idle 1.40 s (table 0.67 / roll-cancel 1.40); Battle Axe startup 0.64 (0.63); Bandit's Knife 0.34 (0.33). Only these three.

## 3. The average formula and each weapon's deviation (MoKa M1109-83)
- Same category = same timing: Broadsword = Longsword, Claymore = Bastard Sword, Zweihander = Greatsword. Within a class
  the game varies reach, stamina and damage, not speed.
- Across classes, weight alone explains most of it (least squares over the 14 light attacks):
  - startup ≈ 0.33 s + 0.056 s × weight (R² 0.89)
  - recovery (blade end → move) ≈ 0.24 s + 0.064 s × weight (R² 0.88)
  - first move cancel ≈ 0.68 s + 0.125 s × weight (R² 0.93)
- Deviations (actual − formula, startup): Uchigatana −0.17 s (fast for its weight), Halberd −0.10, Battle Axe / Mace /
  Zweihander +0.08, the rest within ±0.05. Claymore sits on the line (0.00) but has a long blade for its weight
  (1.68 m vs Bastard Sword 1.45) — the same timing with more reach.
- This is a fit to 14 weapons, not a rule found in the game: the game stores one TAE per category, not a formula.
