# HP · stamina analysis of recorded game runs (offline, read-only; docs/hp-stamina-2026-11-12.md).
# Outputs go to data/analysis/hpsp_20261112/. The bot never imports this (experiments/).
import os as _os
REPO = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
_os.chdir(_os.path.join(REPO, 'data', 'analysis', 'hpsp_20261112'))   # reads / writes the CSVs there
"""Each attack start / Estus start while HP < 30 % (or < 50 %): what followed."""
import analyze as A, glob, os, csv, collections
rows=[]
for tr in sorted(glob.glob(REPO + '/data/samples/*.track.jsonl')):
    b=os.path.basename(tr)
    if b.startswith('room-') or '_room' in b: continue
    name=b[:-12]; cmd=A.cmd_of(name); g=A.group(cmd); S,_=A.load(tr); n=len(S)
    if n<3: continue
    cats=[A.cat(s['player']['anim']) for s in S]
    for i in range(1,n):
        c=cats[i]
        if c not in ('attack','estus') or cats[i-1]==c: continue
        p0=S[i-1]['player']; mx=p0['max_hp'] or 1
        if p0['hp']<=0 or p0['hp']>=0.5*mx: continue
        t0=S[i]['rt']
        w3=[k for k in range(i,n) if S[k]['rt']<=t0+3]; w10=[k for k in range(i,n) if S[k]['rt']<=t0+10]
        lost3=sum(max(0,S[k-1]['player']['hp']-S[k]['player']['hp']) for k in w3)
        died=next((round(S[k]['rt']-t0,1) for k in w10 if S[k]['player']['hp']<=0),'')
        hp3=S[w3[-1]]['player']['hp']
        fz=A.foes(S[i-1])
        rows.append(dict(run=name,cmd=cmd,group=g,rt=t0,action=c,hp=p0['hp'],max_hp=mx,hp_pct=round(100*p0['hp']/mx,1),sp=p0['sp'],max_sp=p0['max_sp'],
            band='<30' if p0['hp']<0.3*mx else '30-50', near_npc=fz[0][1]['npc'] if fz else '', near_d=round(fz[0][0],2) if fz else '',
            near_anim=fz[0][1].get('anim') if fz else '', hit_3s=int(lost3>0), lost_3s=lost3, hp_3s=hp3, died_10s=int(died!=''), t_death=died))
with open('low_hp_actions.csv','w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
for g in ('taurus','general'):
  for band in ('<30','30-50'):
    for a in ('attack','estus'):
        X=[r for r in rows if r['group']==g and r['band']==band and r['action']==a]
        if not X: print(g,band,a,'n=0'); continue
        print(f"{g:8} HP{band:6} {a:7} n={len(X):3} runs={len(set(r['run'] for r in X)):3} hit<=3s={sum(r['hit_3s'] for r in X):3} died<=10s={sum(r['died_10s'] for r in X):3} hp_up_at_3s={sum(r['hp_3s']>r['hp'] for r in X):3} sp_med={sorted(r['sp'] for r in X)[len(X)//2]} foe<4m={sum(1 for r in X if r['near_d']!='' and r['near_d']<4)}")
