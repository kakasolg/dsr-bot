# HP · stamina analysis of recorded game runs (offline, read-only; docs/hp-stamina-2026-11-12.md).
# Outputs go to data/analysis/hpsp_20261112/. The bot never imports this (experiments/).
import os as _os
REPO = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
_os.chdir(_os.path.join(REPO, 'data', 'analysis', 'hpsp_20261112'))   # reads / writes the CSVs there
import csv,collections,sys
B=[b for b in csv.DictReader(open('big_hits.csv')) if b['fall']=='0']
def binsp(b):
    s=float(b['sp_before'])
    return '<0' if s<0 else '0-20' if s<20 else '20-50' if s<50 else '50-80' if s<80 else '80+'
for crit in ('ge20','ge100'):
  for g in ('taurus','general'):
    X=[b for b in B if b['group']==g and (b['ge20']=='1' if crit=='ge20' else int(b['drop'])>=100)]
    runs=len(set(b['run'] for b in X))
    print(f'== {crit} {g} n={len(X)} runs={runs}')
    c=collections.Counter(binsp(b) for b in X); print(' sp bins', sorted(c.items()))
    c=collections.Counter(b['act_before'] for b in X); print(' act_before', c.most_common())
    # act before with hit_stun replaced by act_before2
    c=collections.Counter((b['act_before2'] if b['act_before'] in ('hit_stun','guard_block') else b['act_before']) for b in X)
    fr=[float(b['sp_frac']) for b in X if b['sp_frac']]
    fr.sort(); print(' sp_frac median', fr[len(fr)//2] if fr else None, ' share sp_frac<0.25', round(sum(f<0.25 for f in fr)/len(fr),2) if fr else None)
    c=collections.Counter(b['foe_npc'] or '?' for b in X); print(' foe', c.most_common(8))
    c=collections.Counter(b['foe_src'] or 'none' for b in X); print(' src', c.most_common())
    if g=='taurus':
        c=collections.Counter(b['bot_me_label'] or '-' for b in X); print(' bot label', c.most_common())
        c=collections.Counter(b['foe_anim'] for b in X if b['foe_npc']=='225000'); print(' boss anim', c.most_common(12))
    print(' killed by this hit', sum(b['killed']=='1' for b in X))
    # sp by action
    for a in ('attack','guard_block','estus','roll','stand','walk','hit_stun'):
        Y=[float(b['sp_before']) for b in X if b['act_before']==a]
        if Y: Y.sort(); print(f'   sp {a}: n={len(Y)} median={Y[len(Y)//2]}')
