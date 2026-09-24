import struct,sys
b=open(sys.argv[1],'rb').read(); i=5
endian,isz,ssz,insz,op,a,bb,c,nsz=b[i:i+9]; i+=9
i+=nsz  # test number
def I():
    global i; v=struct.unpack_from('<i',b,i)[0]; i+=4; return v
def S():
    global i; n=struct.unpack_from('<Q',b,i)[0]; i+=8; s=b[i:i+n-1].decode('cp932','replace') if n else None; i+=n; return s
OPS="MOVE LOADK LOADBOOL LOADNIL GETUPVAL GETGLOBAL GETTABLE SETGLOBAL SETUPVAL SETTABLE NEWTABLE SELF ADD SUB MUL DIV POW UNM NOT CONCAT JMP EQ LT LE TEST CALL TAILCALL RETURN FORLOOP TFORLOOP TFORPREP SETLIST SETLISTO CLOSE CLOSURE".split()
def F(depth, dis):
    global i
    src=S(); line=I(); nups,npar,va,ms=b[i:i+4]; i+=4
    n=I(); i+=4*n
    n=I()
    for _ in range(n): S(); I(); I()
    n=I()
    for _ in range(n): S()
    n=I(); K=[]
    for _ in range(n):
        t=b[i]; i+=1
        if t==3: K.append(struct.unpack_from('<d',b,i)[0]); i+=8
        elif t==4: K.append(S())
        else: K.append(None)
    n=I(); P=[]
    for _ in range(n): P.append(i); F(depth+1,dis) if False else None; P[-1]=F(depth+1,dis)
    n=I(); code=struct.unpack_from('<%dI'%n,b,i); i+=4*n
    name=next((k for k in K if isinstance(k,str) and k.startswith('MiniGreater')),'')
    print('  '*depth+f'-- func line {line} params {npar}')
    if dis:
        for ins in code:
            o=ins&63; A=ins>>24; B=(ins>>15)&511; C=(ins>>6)&511; Bx=(ins>>6)&0x3FFFF
            def rk(x): return f'K[{K[x-250]!r}]' if x>=250 else f'R{x}'
            nm=OPS[o] if o<len(OPS) else o
            if nm in('LOADK','GETGLOBAL','SETGLOBAL'): s=f'{nm} R{A} {K[Bx]!r}'
            elif nm in('GETTABLE','SELF'): s=f'{nm} R{A} R{B} {rk(C)}'
            elif nm in('SETTABLE','ADD','SUB','MUL','DIV','EQ','LT','LE'): s=f'{nm} {A} {rk(B)} {rk(C)}'
            elif nm=='JMP': s=f'JMP {Bx-131071}'
            else: s=f'{nm} {A} {B} {C}'
            print('  '*depth+'   '+s)
    else:
        print('  '*depth+'   K:',K)
    return None
F(0, len(sys.argv)>2)
