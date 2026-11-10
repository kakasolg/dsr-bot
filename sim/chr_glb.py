"""DSR character model + its own animations → skinned glTF .glb for the replay room (MoKa M1109-57: the real Hollow
model and motion instead of a mannequin with stand-in clips; local only — the repo is public, so the .glb and the
extracted files stay in gitignored sim/godot/assets and data/chr).

  python sim/chr_glb.py c2540        → sim/godot/assets/c2540.glb (skin + every animation of chr/c2540.anibnd.dcx)
                                       + data/gamefiles/chr_models.json (bone check, animation lengths, display masks)

Sources and who decodes them:
  chr/<m>.chrbnd.dcx    FLVER (own reader, sim/flver_glb.py; here also bone indices / weights) + chrtpfbhd/bdt textures
  chr/<m>.anibnd.dcx    Skeleton.hkx + aXX_YYYY.hkx — Havok 2015 tagfiles, decoded by DSAnimStudio's SoulsAssetPipeline
                        through sim/hkx_dump.ps1 (local bone transforms per frame, 30 fps)
  NpcParam              ModelDisplayMask0..15 per NPC row: which "#NN#" meshes (weapons, shield) a foe shows
  data/gamefiles/m10_*  MSB: which NPC rows use the model

Skeleton: joints are the HKX skeleton (the animated hierarchy); the mesh is bound with the FLVER bones' bind pose
(FLVER merges Master into Pelvis and leaves the Nub bones parentless, so the two hierarchies differ at the root). The
script checks that every shared bone has the same world bind position in both (`bind_check`, metres).
Space: DSR is left-handed; like the maps (flver_glb.convert_map) everything is mirrored to Godot x = −DSR x
(positions, normals and bone translations x negated, quaternions (x, −y, −z, w), triangle winding flipped).
Root motion is not baked in: the replay keeps the recorded position (Havok reference frame reported only).
"""
from __future__ import annotations

import io
import json
import struct
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sim.flver_glb import OUT_DIR, _godot_import, _pad4, _s, _triangles, read_flver  # noqa: E402

CACHE = ROOT / "data" / "chr"
MODELS_JSON = ROOT / "data" / "gamefiles" / "chr_models.json"
DUMP_PS1 = ROOT / "sim" / "hkx_dump.ps1"
POS, WEIGHT, BONE_IDX, NORMAL, UV = 0, 1, 2, 3, 5
MIRROR = np.diag([-1.0, 1.0, 1.0, 1.0])


def anim_name(anim_id: int) -> str:
    """Animation id → anibnd entry stem (3000 → a00_3000, 13000 → a01_3000)."""
    return f"a{anim_id // 10000:02d}_{anim_id % 10000:04d}"


# ── math ────────────────────────────────────────────────────────────────
def _rx(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def _ry(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def _rz(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def _trs(t, r3, s) -> np.ndarray:
    m = np.eye(4)
    m[:3, :3] = r3 @ np.diag(s)
    m[:3, 3] = t
    return m


def _quat_mat(q) -> np.ndarray:
    x, y, z, w = q
    n = np.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def flver_local(b: dict) -> np.ndarray:
    """FLVER bone local matrix: SoulsFormats Scale · RotX · RotZ · RotY · Translation (row vectors) = T·Ry·Rz·Rx·S."""
    rx, ry, rz = b["r"]
    return _trs(b["t"], _ry(ry) @ _rz(rz) @ _rx(rx), b["s"])


def hkx_local(v) -> np.ndarray:
    return _trs(v[0:3], _quat_mat(v[3:7]), v[7:10])


def worlds(locals_: list, parents: list) -> list:
    out = [None] * len(locals_)

    def w(i):
        if out[i] is None:
            p = parents[i]
            out[i] = locals_[i] if p < 0 else w(p) @ locals_[i]
        return out[i]
    for i in range(len(locals_)):
        w(i)
    return out


def mirror_m(m):
    return MIRROR @ m @ MIRROR


def mirror_t(t):
    return [-t[0], t[1], t[2]]


def mirror_q(q):
    return [q[0], -q[1], -q[2], q[3]]


# ── extraction ──────────────────────────────────────────────────────────
def extract(model: str) -> Path:
    """chrbnd + anibnd entries and the texture binder → data/chr/<model>/ (once)."""
    import navmesh  # noqa: F401 — stubs soulstruct modules the wheel lacks data for
    from navmesh import GAME_DIR
    from soulstruct.containers import Binder
    d = CACHE / model
    if (d / f"{model}.flver").exists() and (d / "Skeleton.hkx").exists():
        return d
    d.mkdir(parents=True, exist_ok=True)
    for f in (f"{model}.chrbnd.dcx", f"{model}.anibnd.dcx"):
        for e in Binder.from_path(GAME_DIR / "chr" / f).entries:
            (d / e.name.split("\\")[-1]).write_bytes(e.data)
    bdt = GAME_DIR / "chr" / f"{model}.chrtpfbdt"
    bhd = d / f"{model}.chrtpfbhd"
    if bhd.exists() and bdt.exists():
        tex = d / "tex"
        tex.mkdir(exist_ok=True)
        for e in Binder.from_bytes(bhd.read_bytes(), bdt_data=bdt.read_bytes()).entries:
            (tex / e.name.split("\\")[-1]).write_bytes(e.data)
    return d


def hkx_dump(d: Path) -> dict:
    out = d / "hkx.json"
    if not out.exists():
        r = subprocess.run(["pwsh", "-NoProfile", "-File", str(DUMP_PS1), "-Dir", str(d), "-OutFile", str(out)],
                           capture_output=True, text=True)
        if r.returncode or not out.exists():
            raise SystemExit(f"hkx_dump failed: {r.stdout}\n{r.stderr}")
    return json.loads(out.read_text(encoding="utf-8-sig"))


def textures(d: Path) -> dict:
    """{texture stem: png bytes} from the extracted .tpf files."""
    from soulstruct.containers import TPF
    from PIL import Image
    out = {}
    for f in sorted((d / "tex").glob("*.tpf*")) if (d / "tex").exists() else []:
        if f.name.split(".")[0].lower().endswith(("_n", "_s")):
            continue
        for t in TPF.from_bytes(f.read_bytes()).textures:
            try:
                buf = io.BytesIO()
                Image.open(io.BytesIO(t.data)).save(buf, "PNG")
                out[t.stem.lower()] = buf.getvalue()
            except Exception:  # noqa: BLE001 — a texture Pillow cannot decode is left out (mesh drawn untextured)
                pass
    return out


# ── FLVER skinned meshes ────────────────────────────────────────────────
def skinned_meshes(b: bytes, fl: dict) -> list:
    """[{mat, mask, pos, nrm, uv, joints (FLVER bone index ×4), weights ×4, tris}] — LOD-0 face set of each mesh."""
    o = 0x80 + 0x40 * len(fl["dummies"]) + 0x20 * len(fl["materials"]) + 0x80 * len(fl["bones"])
    out = []
    for m in fl["meshes"]:
        dynamic = b[o]
        default_bone, n_bones, _bb, bone_o = _s(b, o + 0x10, "4i")
        o += 0x30
        bone_list = list(_s(b, bone_o, f"{n_bones}i")) if n_bones else []
        pos, nrm, uv, jt, wt = [], [], [], [], []
        for vbi in m["vbufs"][:1]:
            vb = fl["vbufs"][vbi]
            mem = fl["layouts"][vb["layout"]]
            for k in range(vb["count"]):
                base = vb["off"] + k * vb["vsize"]
                v = {}
                for soff, typ, sem, _i in mem:
                    p = base + soff
                    if sem == POS and typ == 0x02:
                        v["p"] = _s(b, p, "3f")
                    elif sem == NORMAL and typ in (0x10, 0x11, 0x13, 0x2F) and "n" not in v:
                        v["n"] = [(x - 127) / 127.0 for x in b[p:p + 3]]
                        v["nw"] = b[p + 3]
                    elif sem == UV and "uv" not in v and typ in (0x15, 0x16):
                        u, w = _s(b, p, "2h")
                        v["uv"] = (u / 1024.0, w / 1024.0)
                    elif sem == BONE_IDX and typ in (0x11, 0x2F, 0x13):
                        v["j"] = list(b[p:p + 4])
                    elif sem == WEIGHT and typ == 0x1A:
                        v["w"] = [x / 32767.0 for x in _s(b, p, "4h")]
                pos.append(v.get("p", (0, 0, 0)))
                nrm.append(v.get("n", (0, 1, 0)))
                uv.append(v.get("uv", (0, 0)))
                if dynamic:
                    js, ws = v.get("j", [0, 0, 0, 0]), v.get("w", [1, 0, 0, 0])
                else:   # static mesh: whole vertex on one bone, its index in the normal's w byte
                    js, ws = [v.get("nw", 0), 0, 0, 0], [1, 0, 0, 0]
                gj = [bone_list[j] if j < len(bone_list) else default_bone for j in js]
                s = sum(ws) or 1.0
                jt.append(gj)
                wt.append([x / s for x in ws])
        name = fl["materials"][m["mat"]]["name"]
        mask = int(name[1:3]) if len(name) > 3 and name[0] == "#" and name[3] == "#" and name[1:3].isdigit() else -1
        out.append({"mat": m["mat"], "mask": mask, "dynamic": bool(dynamic), "pos": pos, "nrm": nrm, "uv": uv,
                    "joints": jt, "weights": wt, "tris": _triangles(fl["facesets"][m["facesets"][0]])})
    return out


# ── glTF ────────────────────────────────────────────────────────────────
class _Buf:
    def __init__(self):
        self.bin = bytearray()
        self.views, self.acc = [], []

    def view(self, data: bytes, target=None) -> int:
        while len(self.bin) % 4:
            self.bin += b"\0"
        self.views.append({"buffer": 0, "byteOffset": len(self.bin), "byteLength": len(data),
                           **({"target": target} if target else {})})
        self.bin += data
        return len(self.views) - 1

    def accessor(self, arr: np.ndarray, kind: str, ctype=5126, target=None, minmax=False) -> int:
        fmt = {5126: np.float32, 5125: np.uint32, 5123: np.uint16}[ctype]
        a = np.ascontiguousarray(arr, dtype=fmt)
        n = a.shape[0]
        acc = {"bufferView": self.view(a.tobytes(), target), "componentType": ctype, "count": int(n), "type": kind}
        if minmax:
            flat = a.reshape(n, -1)
            acc["min"] = [float(x) for x in flat.min(0)]
            acc["max"] = [float(x) for x in flat.max(0)]
        self.acc.append(acc)
        return len(self.acc) - 1


def build(model: str) -> dict:
    d = extract(model)
    b = (d / f"{model}.flver").read_bytes()
    fl = read_flver(b)
    hk = hkx_dump(d)
    hb = hk["bones"]
    h_names = [x["name"] for x in hb]
    h_par = [x["parent"] for x in hb]
    h_world = worlds([hkx_local(x["ref"]) for x in hb], h_par)
    f_world = worlds([flver_local(x) for x in fl["bones"]], [x["parent"] for x in fl["bones"]])
    f_names = [x["name"] for x in fl["bones"]]
    # bind check: same bone name → same world bind position in FLVER and HKX. FLVER leaves the Nub (end) bones without
    # a parent, so their stored local offset reads as a world position — those are listed apart, not compared.
    diffs, loose = {}, []
    for i, n in enumerate(f_names):
        if n not in h_names:
            continue
        j = h_names.index(n)
        if fl["bones"][i]["parent"] < 0 and h_par[j] >= 0:
            loose.append(n)
            continue
        diffs[n] = float(np.linalg.norm(f_world[i][:3, 3] - h_world[j][:3, 3]))
    meshes = skinned_meshes(b, fl)
    used = sorted({j for m in meshes for js, ws in zip(m["joints"], m["weights"]) for j, w in zip(js, ws) if w > 0})

    buf = _Buf()
    nodes = []
    # joints: every HKX bone (local rest = HKX reference pose), then FLVER-only bones the mesh uses, as roots
    joint_of_flver = {}
    for i, x in enumerate(hb):
        v = x["ref"]
        nodes.append({"name": x["name"], "translation": mirror_t(v[0:3]), "rotation": mirror_q(v[3:7]),
                      "scale": v[7:10], "children": []})
    for i, x in enumerate(hb):
        if x["parent"] >= 0:
            nodes[x["parent"]]["children"].append(i)
    for fi, n in enumerate(f_names):
        if n in h_names:
            joint_of_flver[fi] = h_names.index(n)
        elif fi in used:
            m = mirror_m(f_world[fi])
            nodes.append({"name": n, "matrix": [float(v) for v in m.T.reshape(-1)], "children": []})
            joint_of_flver[fi] = len(nodes) - 1
    for nd in nodes:
        if not nd["children"]:
            del nd["children"]
    joints = list(range(len(nodes)))
    inv = []
    for j in joints:
        fi = next((k for k, v in joint_of_flver.items() if v == j), None)
        wm = f_world[fi] if fi is not None else h_world[j]
        inv.append(np.linalg.inv(mirror_m(wm)).T.reshape(-1))
    skin = {"joints": joints, "inverseBindMatrices": buf.accessor(np.array(inv), "MAT4"),
            "skeleton": h_par.index(-1)}

    tex = textures(d)
    images, gl_tex, gl_mats, mat_map = [], [], [], {}
    for mi, mt in enumerate(fl["materials"]):
        stem = next((Path(t["path"].replace("\\", "/")).stem.lower() for t in mt["textures"]
                     if t["path"] and not Path(t["path"].replace("\\", "/")).stem.lower().endswith(("_n", "_s"))), None)
        mat = {"name": mt["name"], "pbrMetallicRoughness": {"metallicFactor": 0.1, "roughnessFactor": 0.8},
               "alphaMode": "MASK", "alphaCutoff": 0.5, "doubleSided": True}
        if stem in tex:
            images.append({"bufferView": buf.view(tex[stem]), "mimeType": "image/png"})
            gl_tex.append({"sampler": 0, "source": len(images) - 1})
            mat["pbrMetallicRoughness"]["baseColorTexture"] = {"index": len(gl_tex) - 1}
        mat_map[mi] = len(gl_mats)
        gl_mats.append(mat)

    gl_meshes, mesh_nodes = [], []
    for k, m in enumerate(meshes):
        if not m["tris"]:
            continue
        pos = np.array(m["pos"], dtype=np.float64) * [-1, 1, 1]
        nrm = np.array(m["nrm"], dtype=np.float64) * [-1, 1, 1]
        nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-9)
        tris = np.array([(a, c, bb) for a, bb, c in m["tris"]], dtype=np.uint32)  # mirrored → flip winding
        jj = np.array([[joint_of_flver.get(j, 0) for j in js] for js in m["joints"]], dtype=np.uint16)
        prim = {"attributes": {
            "POSITION": buf.accessor(pos, "VEC3", target=34962, minmax=True),
            "NORMAL": buf.accessor(nrm, "VEC3", target=34962),
            "TEXCOORD_0": buf.accessor(np.array(m["uv"]), "VEC2", target=34962),
            "JOINTS_0": buf.accessor(jj, "VEC4", ctype=5123, target=34962),
            "WEIGHTS_0": buf.accessor(np.array(m["weights"]), "VEC4", target=34962)},
            "indices": buf.accessor(tris.reshape(-1), "SCALAR", ctype=5125, target=34963),
            "material": mat_map[m["mat"]]}
        label = f"mask{m['mask']:02d}" if m["mask"] >= 0 else "body"
        gl_meshes.append({"name": f"{label}_{k}", "primitives": [prim]})
        nodes.append({"name": f"{label}_{k}", "mesh": len(gl_meshes) - 1, "skin": 0})
        mesh_nodes.append(len(nodes) - 1)

    anims, lengths = [], {}
    for name, a in hk["anims"].items():
        if "pose" not in a:
            lengths[name] = {"error": a.get("error")}
            continue
        nf = a["frames"]
        fs = 1.0 / round(1.0 / a["frame_s"])   # the dump rounds to 5 decimals; 0.03333 instead of 1/30 drifts against
                                               # Godot's 30 fps import resampling (≈3 mm at the fastest swing)
        times = buf.accessor(np.arange(nf) * fs, "SCALAR", minmax=True)
        pose = np.array(a["pose"], dtype=np.float64)          # [frame, bone, 10]
        samplers, channels = [], []
        for j in range(len(hb)):
            t = pose[:, j, 0:3] * [-1, 1, 1]
            q = pose[:, j, 3:7] * [1, -1, -1, 1]
            for f in range(1, nf):                              # keep quaternion signs continuous for LINEAR
                if np.dot(q[f], q[f - 1]) < 0:
                    q[f] = -q[f]
            for path, arr, kind in (("translation", t, "VEC3"), ("rotation", q, "VEC4")):
                samplers.append({"input": times, "output": buf.accessor(arr, kind), "interpolation": "LINEAR"})
                channels.append({"sampler": len(samplers) - 1, "target": {"node": j, "path": path}})
            sc = pose[:, j, 7:10]
            if np.abs(sc - 1).max() > 1e-4:
                samplers.append({"input": times, "output": buf.accessor(sc, "VEC3"), "interpolation": "LINEAR"})
                channels.append({"sampler": len(samplers) - 1, "target": {"node": j, "path": "scale"}})
        anims.append({"name": name, "samplers": samplers, "channels": channels})
        rm = a.get("root_motion") or []
        lengths[name] = {"frames": nf, "duration": round((nf - 1) * fs, 5) if nf > 1 else a["duration"],
                         "root_motion_end": rm[-1] if rm else None}

    root = len(nodes)
    nodes.append({"name": model, "children": [h_par.index(-1)] + [i for i in range(len(hb), root)
                                                                  if i not in mesh_nodes] + mesh_nodes})
    gltf = {"asset": {"version": "2.0", "generator": "dsr-bot sim/chr_glb.py"}, "scene": 0,
            "scenes": [{"nodes": [root]}], "nodes": nodes, "meshes": gl_meshes, "skins": [skin],
            "animations": anims, "accessors": buf.acc, "bufferViews": buf.views,
            "buffers": [{"byteLength": len(buf.bin)}], "materials": gl_mats, "textures": gl_tex, "images": images,
            "samplers": [{"magFilter": 9729, "minFilter": 9987}]}
    js = _pad4(json.dumps(gltf).encode(), b" ")
    bb = _pad4(bytes(buf.bin))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{model}.glb"
    out.write_bytes(struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(js) + 8 + len(bb)) + struct.pack("<I4s", len(js), b"JSON")
                    + js + struct.pack("<I4s", len(bb), b"BIN\0") + bb)
    return {"model": model, "glb_mb": round(out.stat().st_size / 1e6, 1), "decoder": hk["tool"],
            "bones": {"hkx": len(hb), "flver": len(f_names), "joints": len(joints)},
            "bind_check_m": {"bones": len(diffs), "worst": round(max(diffs.values()), 5),
                             "worst_bone": max(diffs, key=diffs.get), "not_compared_parentless": loose},
            "meshes": [{"name": g["name"], "material": fl["materials"][m["mat"]]["name"], "mask": m["mask"],
                        "dynamic": m["dynamic"], "triangles": len(m["tris"])} for g, m in
                       zip(gl_meshes, [m for m in meshes if m["tris"]])],
            "textures": sorted(tex), "anims": lengths}


def npc_masks(model: str) -> dict:
    """{npc row: [display mask ids]} for every NPC row the Burg / Firelink MSBs give this model."""
    import navmesh  # noqa: F401
    from navmesh import GAME_DIR
    from soulstruct.darksouls1r.params import GameParamBND
    rows = set()
    for f in sorted((ROOT / "data" / "gamefiles").glob("m1*_00_00.json")):
        for e in json.loads(f.read_text(encoding="utf-8")).get("enemies", []):
            if e.get("model") == model and e.get("npc_param_id"):
                rows.add(e["npc_param_id"])
    gp = GameParamBND.from_path(GAME_DIR / "param" / "GameParam" / "GameParam.parambnd.dcx")
    npc = gp.get_param("NpcParam")
    out = {}
    for r in sorted(rows):
        try:
            row = npc[r]
        except KeyError:
            continue
        out[str(r)] = [k for k in range(16) if getattr(row, f"ModelDisplayMask{k}")]
    return out


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    models = sys.argv[1:] or ["c2540"]
    data = json.loads(MODELS_JSON.read_text(encoding="utf-8")) if MODELS_JSON.exists() else {}
    for model in models:
        info = build(model)
        info["npc_masks"] = npc_masks(model)
        data[model] = info
        ok = [k for k, v in info["anims"].items() if "frames" in v]
        print(f"{model}.glb {info['glb_mb']} MB: {len(ok)}/{len(info['anims'])} anims, joints {info['bones']}, "
              f"bind check worst {info['bind_check_m']['worst']} m ({info['bind_check_m']['worst_bone']}), "
              f"meshes {[(m['name'], m['triangles']) for m in info['meshes']]}, textures {len(info['textures'])}, "
              f"npc masks {info['npc_masks']}")
    MODELS_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    _godot_import()
    if any(_exact_import(m) for m in models):
        _godot_import()


def _exact_import(model: str) -> bool:
    """Turn off Godot's lossy animation optimizer for this glb (on by default: up to ~5 mm off at the fastest swing,
    tests/chr_glb_test.py). Returns True when the .import file changed (reimport needed)."""
    imp = OUT_DIR / f"{model}.glb.import"
    if not imp.exists():
        return False
    lines = imp.read_text(encoding="utf-8").split("\n")
    want = ["_subresources={", '"nodes": {', '"PATH:AnimationPlayer": {', '"optimizer/enabled": false', "}", "}", "}"]
    i = next((k for k, x in enumerate(lines) if x.startswith("_subresources=")), None)
    if i is None or lines[i:i + len(want)] == want:
        return False
    if lines[i] != "_subresources={}":
        raise SystemExit(f"{imp.name}: _subresources already set by hand — add optimizer/enabled=false yourself")
    imp.write_text("\n".join(lines[:i] + want + lines[i + 1:]), encoding="utf-8")
    return True


if __name__ == "__main__":
    main()
