import json, glob, collections, statistics, re, os, sys
REPO=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
rows=[]; words=collections.Counter()
for f in sorted(glob.glob(REPO+"/data/samples/*.track.jsonl")):
    n=os.path.basename(f)
    if "room" in n: continue
    cmd=re.sub(r"^\d+_\d+_","",n.replace(".track.jsonl","")).split("_")[0]
    if cmd=="taurus": continue
    S=[];SAY=[]
    for l in open(f,encoding="utf-8",errors="replace"):
        try: d=json.loads(l)
        except: continue
        if d.get("type")=="snap" and d.get("player"): S.append((d["rt"],d["player"]))
        elif d.get("type")=="say": SAY.append((d["rt"],d.get("line","")))
    above=True
    for i,(t,p) in enumerate(S):
        mh=p.get("max_hp") or 0; hp=p.get("hp")
        if not mh or hp is None: continue
        if hp<=0: above=False; continue
        if hp>=0.3*mh: above=True; continue
        if not above: continue
        above=False
        t0=t; res=None; dt=None
        for t2,p2 in S[i:]:
            if t2-t0>30: break
            a=p2.get("anim")
            if a is not None and 7585<=a%100000<=7587: res="drank"; dt=t2-t0; break
            if (p2.get("hp") or 0)<=0: res="died"; dt=t2-t0; break
            if (p2.get("hp") or 0)>=0.3*mh and t2>t0: res="rose_no_drink"; dt=t2-t0; break
        says=[s for ts,s in SAY if t0-0.5<=ts<=t0+(dt or 10)]
        for s in says:
            for w in ("low_hp","recover","물러","뒤로","안 마심","에스트","desperate","safe","crowd","losing","끝까지","싸움"):
                if w in s: words[w]+=1
        rows.append((n,round(t0,1),hp,mh,res,None if dt is None else round(dt,2),says[:6]))
print("episodes",len(rows))
c=collections.Counter(r[4] for r in rows); print(c)
d=[r[5] for r in rows if r[4]=="drank"]
print("delay to drink: n",len(d),"median",statistics.median(d),"p25",sorted(d)[len(d)//4],"p75",sorted(d)[3*len(d)//4], "<=0.5:",sum(x<=0.5 for x in d),"<=1:",sum(x<=1 for x in d),">3:",sum(x>3 for x in d))
dd=[r[5] for r in rows if r[4]=="died"]; print("died: n",len(dd),"median t",statistics.median(dd) if dd else None)
print(words.most_common())

