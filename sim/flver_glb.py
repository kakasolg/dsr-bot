"""DSR weapon / shield model (parts/WP_A_xxxx.partsbnd.dcx) → glTF .glb for the practice room, plus its dummy points
(MoKa M1109-54: the real game models, local only — the repo is public, so the .glb stays in gitignored sim/godot/assets).

  python sim/flver_glb.py WP_A_0266 WP_A_1521        → sim/godot/assets/<name>.glb (then Godot --import),
                                                       dummies → data/gamefiles/weapon_models.json

Reads FLVER2 (DSR version 0x2000C) by hand — soulstruct 2.3.2 has no FLVER reader. Layout as in SoulsFormats FLVER2
(header 0x80, dummy 0x40, material 0x20, bone 0x80, mesh 0x30, face set 0x20, vertex buffer 0x20, layout 0x10, member
0x14). Only what a rigid weapon needs: positions, normals, first UV, triangle strips → triangles, the diffuse texture
(TPF DDS → PNG via Pillow). Bone weights are ignored: weapon vertices are taken in model space.
"""
from __future__ import annotations

import io
import json
import math
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "sim" / "godot" / "assets"
DUMMY_JSON = ROOT / "data" / "gamefiles" / "weapon_models.json"

# LayoutType → byte size; LayoutSemantic ids
SIZES = {0x01: 8, 0x02: 12, 0x03: 16, 0x10: 4, 0x11: 4, 0x12: 4, 0x13: 4, 0x15: 4, 0x16: 8, 0x18: 8, 0x1A: 8,
         0x2E: 8, 0x2F: 4}
POS, WEIGHT, BONE_IDX, NORMAL, UV = 0, 1, 2, 3, 5
UV_FACTOR = 1024.0          # FLVER versions below 0x2000F


def _s(b, o, fmt):
    return struct.unpack_from("<" + fmt, b, o)


def _name(b, off, unicode_):
    if off <= 0:
        return ""
    if unicode_:
        e = off
        while b[e:e + 2] != b"\0\0":
            e += 2
        return b[off:e].decode("utf-16-le")
    e = b.index(b"\0", off)
    return b[off:e].decode("shift_jis", "replace")


def read_flver(b: bytes) -> dict:
    assert b[:6] == b"FLVER\0" and b[6:8] == b"L\0", "not a little-endian FLVER"
    (version, data_off, _dlen, n_dummy, n_mat, n_bone, n_mesh, n_vbuf) = _s(b, 0x08, "8i")
    vidx_size, unicode_ = b[0x48], bool(b[0x49])
    n_faceset, n_layout, n_tex = _s(b, 0x50, "3i")
    o = 0x80
    dummies = []
    for _ in range(n_dummy):
        px, py, pz = _s(b, o, "3f")
        fx, fy, fz = _s(b, o + 0x10, "3f")
        ref, parent = _s(b, o + 0x1C, "2h")
        ux, uy, uz = _s(b, o + 0x20, "3f")
        attach, = _s(b, o + 0x2C, "h")
        dummies.append({"ref": ref, "pos": [px, py, pz], "fwd": [fx, fy, fz], "up": [ux, uy, uz],
                        "parent_bone": parent, "attach_bone": attach})
        o += 0x40
    mats = []
    for _ in range(n_mat):
        name_o, mtd_o, tcount, tindex = _s(b, o, "4i")
        mats.append({"name": _name(b, name_o, unicode_), "mtd": _name(b, mtd_o, unicode_), "tex": (tindex, tcount)})
        o += 0x20
    bones = []
    for _ in range(n_bone):
        t = _s(b, o, "3f")
        name_o, = _s(b, o + 0x0C, "i")
        r = _s(b, o + 0x10, "3f")
        parent, child = _s(b, o + 0x1C, "2h")
        s = _s(b, o + 0x20, "3f")
        bones.append({"name": _name(b, name_o, unicode_), "t": t, "r": r, "s": s, "parent": parent})
        o += 0x80
    meshes = []
    for _ in range(n_mesh):
        mat, = _s(b, o + 4, "i")
        default_bone, n_bones, _bb, _bo, n_fs, fs_o, n_vb, vb_o = _s(b, o + 0x10, "8i")
        fsi = list(_s(b, fs_o, f"{n_fs}i"))
        vbi = list(_s(b, vb_o, f"{n_vb}i"))
        meshes.append({"mat": mat, "facesets": fsi, "vbufs": vbi})
        o += 0x30
    facesets = []
    for _ in range(n_faceset):
        flags, = _s(b, o, "I")
        strip, cull = b[o + 4], b[o + 5]
        count, idx_off, _ilen, _z, size = _s(b, o + 8, "5i")
        size = size or vidx_size
        fmt = "H" if size == 16 else "I"
        idx = list(_s(b, data_off + idx_off, f"{count}{fmt}"))
        facesets.append({"flags": flags, "strip": bool(strip), "idx": idx, "restart": 0xFFFF if size == 16 else 0xFFFFFFFF})
        o += 0x20
    vbufs = []
    for _ in range(n_vbuf):
        _bi, layout, vsize, vcount, _a, _b2, _blen, boff = _s(b, o, "8i")
        vbufs.append({"layout": layout, "vsize": vsize, "count": vcount, "off": data_off + boff})
        o += 0x20
    layouts = []
    for _ in range(n_layout):
        n_mem, _a, _b2, mem_o = _s(b, o, "4i")
        mem = []
        for k in range(n_mem):
            _u, soff, typ, sem, index = _s(b, mem_o + k * 0x14, "5i")
            mem.append((soff, typ, sem, index))
        layouts.append(mem)
        o += 0x10
    textures = []
    for _ in range(n_tex):
        path_o, type_o = _s(b, o, "2i")
        textures.append({"path": _name(b, path_o, unicode_), "type": _name(b, type_o, unicode_)})
        o += 0x20
    for m in mats:
        i, n = m["tex"]
        m["textures"] = textures[i:i + n]
    return {"version": version, "dummies": dummies, "materials": mats, "bones": bones, "meshes": meshes,
            "facesets": facesets, "vbufs": vbufs, "layouts": layouts}


def _vertex(b, base, members):
    v = {}
    for soff, typ, sem, index in members:
        o = base + soff
        if sem == POS and typ == 0x02:
            v["pos"] = _s(b, o, "3f")
        elif sem == NORMAL and typ in (0x10, 0x11, 0x13, 0x2F):
            n = [(x - 127) / 127.0 for x in b[o:o + 3]]
            v["nrm"] = n
        elif sem == NORMAL and typ == 0x02:
            v["nrm"] = _s(b, o, "3f")
        elif sem == UV and "uv" not in v:
            if typ in (0x15, 0x16):
                u, w = _s(b, o, "2h")
                v["uv"] = (u / UV_FACTOR, w / UV_FACTOR)
            elif typ == 0x01:
                v["uv"] = _s(b, o, "2f")
    return v


def _triangles(fs) -> list:
    idx, out = fs["idx"], []
    if not fs["strip"]:
        return [tuple(idx[i:i + 3]) for i in range(0, len(idx) - 2, 3)]
    flip = False
    for i in range(len(idx) - 2):
        a, b_, c = idx[i], idx[i + 1], idx[i + 2]
        if fs["restart"] in (a, b_, c):
            flip = False
            continue
        if a != b_ and b_ != c and a != c:
            out.append((a, c, b_) if flip else (a, b_, c))
        flip = not flip
    return out


def mesh_data(b: bytes, fl: dict) -> list:
    """[(material, positions, normals, uvs, triangles)] using each mesh's LOD-0 face set (the first one)."""
    out = []
    for m in fl["meshes"]:
        verts = []
        for vbi in m["vbufs"]:
            vb = fl["vbufs"][vbi]
            mem = fl["layouts"][vb["layout"]]
            for k in range(vb["count"]):
                d = _vertex(b, vb["off"] + k * vb["vsize"], mem)
                if k < len(verts):
                    verts[k].update(d)
                else:
                    verts.append(d)
        fs = fl["facesets"][m["facesets"][0]]
        tris = _triangles(fs)
        pos = [v.get("pos", (0, 0, 0)) for v in verts]
        nrm = [v.get("nrm", (0, 1, 0)) for v in verts]
        uv = [v.get("uv", (0, 0)) for v in verts]
        out.append((m["mat"], pos, nrm, uv, tris))
    return out


def _pad4(x: bytes, fill=b"\0") -> bytes:
    return x + fill * ((4 - len(x) % 4) % 4)


def write_glb(path: Path, parts: list, images: dict, mats: list) -> None:
    """parts: [(mat_index, pos, nrm, uv, tris)]; images: {mat_index: png bytes}. One node, one mesh, a primitive each."""
    bin_ = bytearray()
    views, accessors, prims = [], [], []

    def add(data: bytes, target=None) -> int:
        nonlocal bin_
        while len(bin_) % 4:
            bin_ += b"\0"
        views.append({"buffer": 0, "byteOffset": len(bin_), "byteLength": len(data), **({"target": target} if target else {})})
        bin_ += data
        return len(views) - 1

    gl_mats, gl_tex, gl_img, gl_samp = [], [], [], [{"magFilter": 9729, "minFilter": 9987}]
    mat_map = {}
    for mi, png in images.items():
        v = add(png)
        gl_img.append({"bufferView": v, "mimeType": "image/png"})
        gl_tex.append({"sampler": 0, "source": len(gl_img) - 1})
        mat_map[mi] = len(gl_mats)
        gl_mats.append({"name": mats[mi]["name"], "pbrMetallicRoughness": {
            "baseColorTexture": {"index": len(gl_tex) - 1}, "metallicFactor": 0.3, "roughnessFactor": 0.6},
            "alphaMode": "MASK", "alphaCutoff": 0.5, "doubleSided": True})
    for mi, pos, nrm, uv, tris in parts:
        if not tris:
            continue
        p = b"".join(struct.pack("<3f", *x) for x in pos)
        n = b"".join(struct.pack("<3f", *(_unit(x))) for x in nrm)
        t = b"".join(struct.pack("<2f", *x) for x in uv)
        i = b"".join(struct.pack("<3I", *x) for x in tris)
        lo = [min(x[k] for x in pos) for k in range(3)]
        hi = [max(x[k] for x in pos) for k in range(3)]
        base = len(accessors)
        accessors += [
            {"bufferView": add(p, 34962), "componentType": 5126, "count": len(pos), "type": "VEC3", "min": lo, "max": hi},
            {"bufferView": add(n, 34962), "componentType": 5126, "count": len(nrm), "type": "VEC3"},
            {"bufferView": add(t, 34962), "componentType": 5126, "count": len(uv), "type": "VEC2"},
            {"bufferView": add(i, 34963), "componentType": 5125, "count": len(tris) * 3, "type": "SCALAR"},
        ]
        prim = {"attributes": {"POSITION": base, "NORMAL": base + 1, "TEXCOORD_0": base + 2}, "indices": base + 3}
        if mi in mat_map:
            prim["material"] = mat_map[mi]
        prims.append(prim)
    gltf = {"asset": {"version": "2.0", "generator": "dsr-bot sim/flver_glb.py"}, "scene": 0,
            "scenes": [{"nodes": [0]}], "nodes": [{"name": path.stem, "mesh": 0}],
            "meshes": [{"name": path.stem, "primitives": prims}], "accessors": accessors, "bufferViews": views,
            "buffers": [{"byteLength": len(bin_)}], "materials": gl_mats, "textures": gl_tex, "images": gl_img,
            "samplers": gl_samp}
    js = _pad4(json.dumps(gltf).encode(), b" ")
    bb = _pad4(bytes(bin_))
    total = 12 + 8 + len(js) + 8 + len(bb)
    path.write_bytes(struct.pack("<4sII", b"glTF", 2, total) + struct.pack("<I4s", len(js), b"JSON") + js
                     + struct.pack("<I4s", len(bb), b"BIN\0") + bb)


def _unit(v):
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def convert(name: str) -> dict:
    import navmesh  # noqa: F401 — stubs soulstruct modules the wheel lacks data for
    from navmesh import GAME_DIR
    from soulstruct.containers import TPF, Binder
    from PIL import Image

    bnd = Binder.from_path(GAME_DIR / "parts" / f"{name}.partsbnd.dcx")
    flv = next(e for e in bnd.entries if e.name.lower() == f"{name.lower()}.flver")
    tpf = next((e for e in bnd.entries if e.name.lower().endswith(".tpf")), None)
    b = flv.data
    fl = read_flver(b)
    tex = {}
    if tpf is not None:
        for t in TPF.from_bytes(tpf.data).textures:
            tex[t.stem.lower()] = t.data
    images = {}
    for mi, m in enumerate(fl["materials"]):
        for t in m["textures"]:
            stem = Path(t["path"].replace("\\", "/")).stem.lower()
            if stem in tex and not stem.endswith(("_n", "_s")):
                buf = io.BytesIO()
                Image.open(io.BytesIO(tex[stem])).save(buf, "PNG")
                images[mi] = buf.getvalue()
                break
    parts = mesh_data(b, fl)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_glb(OUT_DIR / f"{name}.glb", parts, images, fl["materials"])
    allp = [p for _, pos, _, _, _ in parts for p in pos]
    lo = [round(min(p[k] for p in allp), 4) for k in range(3)]
    hi = [round(max(p[k] for p in allp), 4) for k in range(3)]
    return {"version": hex(fl["version"]), "bounds": [lo, hi],
            "bones": [{"name": x["name"], "t": [round(v, 4) for v in x["t"]], "r": [round(v, 4) for v in x["r"]],
                       "parent": x["parent"]} for x in fl["bones"]],
            "materials": [{"name": m["name"], "mtd": m["mtd"]} for m in fl["materials"]],
            "triangles": sum(len(p[4]) for p in parts), "vertices": len(allp),
            "dummies": [{**d, "pos": [round(v, 4) for v in d["pos"]], "fwd": [round(v, 4) for v in d["fwd"]],
                         "up": [round(v, 4) for v in d["up"]]} for d in fl["dummies"]]}


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    names = sys.argv[1:] or ["WP_A_0266", "WP_A_1521"]
    out = json.loads(DUMMY_JSON.read_text(encoding="utf-8")) if DUMMY_JSON.exists() else {}
    out.setdefault("source", "DSR parts/*.partsbnd.dcx FLVER2 dummies (sim/flver_glb.py); positions in model space, metres")
    for n in names:
        d = convert(n)
        out[n] = d
        refs = sorted({x["ref"] for x in d["dummies"]})
        print(f"{n}: {d['vertices']} verts {d['triangles']} tris, bounds {d['bounds']}, dummies {refs}")
    DUMMY_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    # a new .glb loads in the room only after Godot imported it (writes assets/*.import, extracts the textures)
    import subprocess
    from sim.godot_link import GODOT
    if GODOT.exists():
        subprocess.run([str(GODOT), "--headless", "--path", str(ROOT / "sim" / "godot"), "--import"],
                       capture_output=True, timeout=300)
        print("Godot import done")


if __name__ == "__main__":
    main()
