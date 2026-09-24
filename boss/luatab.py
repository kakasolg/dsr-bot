"""battle.lua → Activate 의 거리·조건별 행동 확률 + Act 함수별 공격 애니."""
import struct,sys,re
OPS="MOVE LOADK LOADBOOL LOADNIL GETUPVAL GETGLOBAL GETTABLE SETGLOBAL SETUPVAL SETTABLE NEWTABLE SELF ADD SUB MUL DIV POW UNM NOT CONCAT JMP EQ LT LE TEST CALL TAILCALL RETURN FORLOOP TFORLOOP TFORPREP SETLIST SETLISTO CLOSE CLOSURE".split()
def parse(b):
    i=[22]
    def I():
        v=struct.unpack_from('<i',b,i[0])[0]; i[0]+=4; return v
    def S():
        n=struct.unpack_from('<Q',b,i[0])[0]; i[0]+=8; s=b[i[0]:i[0]+n-1].decode('cp932','replace') if n else None; i[0]+=n; return s
    def F():
        S(); line=I(); i[0]+=4
        n=I(); i[0]+=4*n
        n=I()
        for _ in range(n): S(); I(); I()
        n=I()
        for _ in range(n): S()
        n=I(); K=[]
        for _ in range(n):
            t=b[i[0]]; i[0]+=1
            if t==3: K.append(struct.unpack_from('<d',b,i[0])[0]); i[0]+=8
            elif t==4: K.append(S())
            else: K.append(None)
        n=I(); P=[F() for _ in range(n)]
        n=I(); code=struct.unpack_from('<%dI'%n,b,i[0]); i[0]+=4*n
        return dict(line=line,K=K,P=P,code=code)
    return F()
def dis(f):
    K=f['K']; out=[]
    rk=lambda x: (K[x-250] if x>=250 else f'R{x}')
    for ins in f['code']:
        o=ins&63; A=ins>>24; B=(ins>>15)&511; C=(ins>>6)&511; Bx=(ins>>6)&0x3FFFF
        nm=OPS[o] if o<len(OPS) else str(o)
        if nm=='SELF': out.append(('call',rk(C)))
        elif nm=='GETGLOBAL': out.append(('g',K[Bx]))
        elif nm in('LT','LE','EQ'): out.append((nm,A,rk(B),rk(C)))
        elif nm=='SETTABLE' and A==2: out.append(('P',rk(B),rk(C)))
        elif nm=='JMP': out.append(('J',Bx-131071))
    return out
name=sys.argv[1]; root=parse(open(name,'rb').read())
funcs=root['P']
names=[k for k in root['K'] if isinstance(k,str) and '_Act' in k and 'After' not in k]
# Act 함수들: Activate 뒤 순서대로
act=funcs[1:]
print('==',name)
anims=[]
for n,f in enumerate(act,1):
    a=sorted({int(k) for k in f['K'] if isinstance(k,float) and 3000<=k<3200})
    if a: anims.append(f"Act{n:02d}:{a}")
print('  공격:',' '.join(anims))
line=[]
for t in dis(funcs[0]):
    if t[0]=='call' and t[1] in('GetDist','IsInsideObserve','GetHpRate','GetRandam_Int','IsTargetGuard','GetEventRequest','IsInsideTargetRegion','IsSearchTarget','IsTargetOutOfRangeAngle','IsInsideTarget'): line.append(t[1])
    elif t[0] in('LT','LE'): line.append(f"{'<=' if t[0]=='LE' else '<'}{t[2]}|{t[3]}")
    elif t[0]=='P': line.append(f"Act{int(t[1]):02d}={int(t[2])}")
    elif t[0]=='g' and t[1] in('TARGET_ENE_0',): pass
print('  ',' '.join(line))
