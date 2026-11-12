# HP · stamina analysis of recorded game runs (offline, read-only; docs/hp-stamina-2026-11-12.md).
# Outputs go to data/analysis/hpsp_20261112/. The bot never imports this (experiments/).
import os as _os
REPO = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
_os.chdir(_os.path.join(REPO, 'data', 'analysis', 'hpsp_20261112'))   # reads / writes the CSVs there
import json, glob, analyze as A
for f in sorted(glob.glob(REPO + '/data/runs/20261109_taurus_anim_probe*.jsonl')):
    L=[json.loads(l) for l in open(f)]; H=L[0]; R=[d for d in L[1:] if 'hp' in d]
    t00=R[0]['t']; print('==',f.split('/')[-1],H, 'rows',len(R),'dt med',round(sorted(b['t']-a['t'] for a,b in zip(R,R[1:]))[len(R)//2],4))
    # hits
    for i in range(1,len(R)):
        a,b=R[i-1],R[i]
        if b['hp']<a['hp']:
            # my anim 0.3 s before
            back=[r for r in R[max(0,i-60):i] if r['t']>=b['t']-0.4]
            pa_prev=back[0]['pa'] if back else a['pa']
            print(f"  HIT t={b['t']-t00:7.2f} {a['hp']}->{b['hp']} (-{a['hp']-b['hp']}) my_pa_0.4s_before={pa_prev}({A.cat(pa_prev)}) my_pa_at={a['pa']}({A.cat(a['pa'])}) pat={a['pat']} boss={a.get('ba')} bat={a.get('bat')} d={a.get('d')}")
    # estus
    for i in range(1,len(R)):
        a,b=R[i-1],R[i]
        if b['pa']==7585 and a['pa']!=7585:
            t0=b['t']; hp0=a['hp']
            W=[r for r in R[i:] if r['t']<=t0+3.0]
            rise=next((r['t']-t0 for r in W if r['hp']>hp0),None)
            drop=next((r['t']-t0 for k,r in enumerate(W) if k and r['hp']<W[k-1]['hp']),None)
            end=next((r['t']-t0 for r in W if not 7585<=r['pa']<=7587),None)
            seq=[]
            for r in W:
                if not seq or seq[-1][0]!=r['pa']: seq.append((r['pa'],round(r['t']-t0,2)))
            print(f"  ESTUS t={t0-t00:7.2f} hp0={hp0} boss={a.get('ba')} bat={a.get('bat')} d={a.get('d')} rise@{None if rise is None else round(rise,2)} drop@{None if drop is None else round(drop,2)} anim_end@{None if end is None else round(end,2)} hp3s={W[-1]['hp']} seq={seq[:6]}")
