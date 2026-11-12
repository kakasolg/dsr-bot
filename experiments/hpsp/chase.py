import json, glob, collections, statistics, os, math, sys
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from souls import moves as M
REPO=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
foe_v=collections.defaultdict(list); gap=[]; me_v=[]
for f in sorted(glob.glob(REPO+"/data/samples/*.track.jsonl")):
    n=os.path.basename(f)
    if "room" in n or "taurus" in n: continue
    S=[]
    for l in open(f,encoding="utf-8",errors="replace"):
        try: d=json.loads(l)
        except: continue
        if d.get("type")=="snap" and d.get("player"): S.append(d)
    for a,b in zip(S,S[1:]):
        dt=b["rt"]-a["rt"]
        if not 0.3<=dt<=0.8: continue
        pa,pb=a["player"],b["player"]
        vm=math.hypot(pb["x"]-pa["x"],pb["z"]-pa["z"])/dt
        A={c.get("ptr"):c for c in a.get("chars",[])}
        for c in b.get("chars",[]):
            c0=A.get(c.get("ptr"))
            if not c0 or (c.get("hp") or 0)<=0 or c.get("team") not in (6,7,24,25,27,33): continue
            if c0.get("anim") in M.ATTACK or c.get("anim") in M.ATTACK: continue
            d0=math.hypot(c0["x"]-pa["x"],c0["z"]-pa["z"]); d1=math.hypot(c["x"]-pb["x"],c["z"]-pb["z"])
            if d0>12 or abs(c["y"]-pb["y"])>2: continue
            v=math.hypot(c["x"]-c0["x"],c["z"]-c0["z"])/dt
            if d1<d0-0.3 and v>1.0:   # chasing us
                foe_v[c.get("npc")].append(v)
            if vm>1.5 and d0<5 and v>1.0:   # I'm moving away-ish while a foe within 5 m moves
                gap.append(((d1-d0)/dt, vm, v))
print("foe chase speed (m/s, moving toward us, not attacking):")
for k,v in sorted(foe_v.items(),key=lambda x:-len(x[1]))[:8]:
    v=sorted(v); print(f"  {k}: n={len(v)} median {statistics.median(v):.2f} p75 {v[3*len(v)//4]:.2f} p90 {v[9*len(v)//10]:.2f}")
g=sorted(x[0] for x in gap); print(f"gap change while I move (>1.5 m/s) with a moving foe <5 m: n={len(g)} median {statistics.median(g):+.2f} m/s, share opening (>0) {sum(x>0 for x in g)/len(g):.0%}")
print("my speed then median", round(statistics.median(x[1] for x in gap),2), "foe", round(statistics.median(x[2] for x in gap),2))
