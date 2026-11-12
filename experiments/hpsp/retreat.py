import json, glob, collections, statistics, os, math, sys
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
REPO=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))); HOST=(6,7,24,25,27,33)
eps=[]
for f in sorted(glob.glob(REPO+"/data/samples/*.track.jsonl")):
    n=os.path.basename(f)
    if "room" in n or "taurus" in n: continue
    S=[];SAY=[]
    for l in open(f,encoding="utf-8",errors="replace"):
        try: d=json.loads(l)
        except: continue
        if d.get("type")=="snap" and d.get("player"): S.append(d)
        elif d.get("type")=="say": SAY.append((d["rt"],d.get("line","")))
    starts=[t for t,s in SAY if "후퇴 모드" in s]
    last=-99
    for t0 in starts:
        if t0-last<20: continue
        last=t0
        W=[d for d in S if t0<=d["rt"]<=t0+20]
        if len(W)<4: continue
        def near(d):
            p=d["player"]; cs=[c for c in d.get("chars",[]) if (c.get("hp") or 0)>0 and c.get("team") in HOST and abs(c["y"]-p["y"])<3]
            return min((math.hypot(c["x"]-p["x"],c["z"]-p["z"]) for c in cs), default=None)
        d0=near(W[0])
        if d0 is None or d0>6: continue
        t12=None; died=False; minhp=W[0]["player"]["hp"]; hp0=W[0]["player"]["hp"]
        for d in W:
            nd=near(d); minhp=min(minhp,d["player"]["hp"])
            if d["player"]["hp"]<=0: died=True; break
            if (nd is None or nd>=12.5) and t12 is None: t12=d["rt"]-t0
        dist_path=sum(math.hypot(b["player"]["x"]-a["player"]["x"],b["player"]["z"]-a["player"]["z"]) for a,b in zip(W,W[1:]))
        eps.append((n,round(t0,1),round(d0,1),t12,died,hp0-minhp,round(dist_path/(W[-1]["rt"]-W[0]["rt"]),2)))
print("retreats starting with a foe ≤ 6 m:",len(eps))
got=[e for e in eps if e[3] is not None]; print("reached ≥ 12.5 m from every foe within 20 s:",len(got), "median time", statistics.median(e[3] for e in got) if got else None)
print("died within 20 s:",sum(e[4] for e in eps), " HP lost median", statistics.median(e[5] for e in eps), " my speed median m/s", statistics.median(e[6] for e in eps))
for e in eps[:12]: print(e)
