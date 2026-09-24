import zlib,sys
G="D:/SteamLibrary/steamapps/common/DARK SOULS REMASTERED/script/"
for m in sys.argv[1:]:
    b=open(G+m+".luabnd.dcx",'rb').read(); raw=zlib.decompressobj().decompress(b[b.find(b'\x78\xda'):])
    n=int.from_bytes(raw[0x10:0x14],'little')
    for k in range(n):
        e=raw[0x20+k*0x18:0x38+k*0x18]
        f,sz,off,fid,no,us=[int.from_bytes(e[j:j+4],'little') for j in range(0,24,4)]
        name=raw[no:raw.index(b'\0',no)].decode('cp932').replace(chr(92),'/').split('/')[-1]
        if name.endswith('.lua'):
            open(f"lua_{name}c",'wb').write(raw[off:off+sz]); print(m,name,sz)
