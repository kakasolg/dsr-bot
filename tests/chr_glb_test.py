"""Real character model in the replay room (MoKa M1109-57): Godot plays sim/chr_glb.py's glb with every bone where the
Havok animation puts it, and the animation's attack timing agrees with the TAE. Skipped without Godot or the local files
(sim/chr_glb.py c2540 makes them; game files, so not in git).

What each check covers:
  bind        FLVER bind pose (mesh) and HKX reference pose (animation) agree for every shared bone (chr_models.json)
  playback    Godot's bone world positions = the HKX local transforms chained in Python and mirrored (x → −x), at
              frame times and between frames — checks glb assembly + Godot import/playback, not the Havok decoder
  tae         the right hand's fastest moment of each c2540 melee attack lies inside its TAE type-1 window — the motion
              (DSAnimStudio's decoder) and the hit timing (own TAE reader, checked against DSAnimStudio and in the game
              for 3000's start) are separate sources
  body        ragdoll capsules (Havok physics data, sim/hkx_ragdoll.py) sit on the FLVER bone they follow in the bind
              pose (each segment within BODY_TOL of its bone's origin) — two independent sources agree on where the
              body is; and the replay room draws all of them on a Hollow, upright around its position. Whether DSR uses
              these capsules as the hurtbox is NOT checked here (not known).

python tests/chr_glb_test.py"""
from __future__ import annotations
import sys as _sys, pathlib as _pl
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8")

import json
import subprocess

import numpy as np

from godot_room_test import check
from sim import godot_link as GL
from sim.chr_glb import CACHE, MODELS_JSON, hkx_local, worlds

ROOT = _pl.Path(__file__).resolve().parent.parent
MODEL = "c2540"
GLB = ROOT / "sim" / "godot" / "assets" / f"{MODEL}.glb"
HKX = CACHE / MODEL / "hkx.json"
TAE = ROOT / "data" / "gamefiles" / "tae.json"
CLIPS = ["a00_3000", "a00_3003", "a00_0200"]
TIMES = [0.0, 0.5, 0.9167, 0.93, 1.2833, 2.0]
BODY_TOL = 0.12                 # m — a capsule may start a little past its joint (thigh 3 cm, hand 7 cm)
REPLAY_AT, REPLAY_FOE = 64.71, "24"     # 11-09 02:18 run: #24 (254010) mid-attack next to the bot


def _slerp(q0, q1, u):
    q0 = q0 / np.linalg.norm(q0)
    q1 = q1 / np.linalg.norm(q1)
    d = float(np.clip(np.dot(q0, q1), -1.0, 1.0))
    if d > 0.9995:
        q = q0 * (1 - u) + q1 * u
        return q / np.linalg.norm(q)
    th = np.arccos(d)
    return (np.sin((1 - u) * th) * q0 + np.sin(u * th) * q1) / np.sin(th)


def expected(hk: dict, clip: str, t: float) -> dict:
    """Bone world positions at t: per-frame local transforms interpolated the way glTF LINEAR sampling does
    (translation lerp, rotation slerp), chained, mirrored."""
    a = hk["anims"][clip]
    fs, nf = 1.0 / round(1.0 / a["frame_s"]), a["frames"]     # as sim/chr_glb.py
    f = min(t / fs, nf - 1)
    i0 = int(np.floor(f))
    i1 = min(i0 + 1, nf - 1)
    u = f - i0
    loc = []
    for b in range(len(hk["bones"])):
        p0, p1 = np.array(a["pose"][i0][b]), np.array(a["pose"][i1][b])
        q0, q1 = p0[3:7], p1[3:7]
        if np.dot(q0, q1) < 0:
            q1 = -q1
        v = p0 * (1 - u) + p1 * u
        v[3:7] = _slerp(q0, q1, u)          # glTF LINEAR rotation = slerp (nlerp is off by mm in the fastest swings)
        loc.append(hkx_local(v))
    w = worlds(loc, [x["parent"] for x in hk["bones"]])
    return {x["name"]: [-w[i][0, 3], w[i][1, 3], w[i][2, 3]] for i, x in enumerate(hk["bones"])}


def main() -> None:
    for need, what in ((GL.GODOT, "Godot"), (GLB, "c2540.glb"), (HKX, "hkx dump"), (MODELS_JSON, "chr_models.json")):
        if not need.exists():
            print(f"skip: {what} not found at {need}")
            return
    info = json.loads(MODELS_JSON.read_text(encoding="utf-8"))[MODEL]
    bc = info["bind_check_m"]
    check(f"bind pose: {bc['bones']} shared bones, worst {bc['worst'] * 1000:.2f} mm ({bc['worst_bone']})",
          bc["worst"] < 0.001)
    ok = [k for k, v in info["anims"].items() if "frames" in v]
    check(f"every animation decoded: {len(ok)}/{len(info['anims'])}", len(ok) == len(info["anims"]))

    hk = json.loads(HKX.read_text(encoding="utf-8-sig"))
    r = subprocess.run([str(GL.GODOT), "--headless", "--path", str(ROOT / "sim" / "godot"), "res://chr_probe.tscn", "--",
                        "--clips=" + ",".join(CLIPS), "--bones=" + ",".join(str(x) for x in TIMES)],
                       capture_output=True, text=True, encoding="utf-8", timeout=300)
    line = next((x for x in r.stdout.splitlines() if x.startswith("BONE_DUMP ")), None)
    check("Godot answers the bone dump", line is not None)
    worst, n, missing = 0.0, 0, set()
    for g in json.loads(line[len("BONE_DUMP "):]):
        want = expected(hk, g["clip"], min(g["t"], hk["anims"][g["clip"]]["duration"]))
        for name, p in want.items():
            if name not in g["bones"]:
                missing.add(name)
                continue
            worst = max(worst, float(np.linalg.norm(np.array(g["bones"][name]) - np.array(p))))
            n += 1
    check(f"every HKX bone is a Godot bone (missing {sorted(missing)})", not missing)
    check(f"playback: {n} bone positions over {len(CLIPS)} clips × {len(TIMES)} times, worst {worst * 1000:.2f} mm",
          worst < 0.002)

    tae = json.loads(TAE.read_text(encoding="utf-8"))["models"][MODEL]["animations"]
    names = [x["name"] for x in hk["bones"]]
    par = [x["parent"] for x in hk["bones"]]
    hand = names.index("R Hand")
    rows = []
    for aid, an in sorted(tae.items()):
        win = [(e["start"], e["end"]) for e in an.get("events", []) if e["type"] == 1]
        clip = f"a00_{int(aid):04d}"
        if not win or clip not in hk["anims"]:
            continue
        a = hk["anims"][clip]
        pos = np.array([worlds([hkx_local(v) for v in fr], par)[hand][:3, 3] for fr in a["pose"]])
        sp = np.linalg.norm(np.diff(pos, axis=0), axis=1) / a["frame_s"]
        t_peak = (int(np.argmax(sp)) + 0.5) * a["frame_s"]
        inside = any(s - 1e-6 <= t_peak <= e + a["frame_s"] for s, e in win)
        rows.append((aid, t_peak, win, inside))
    bad = [r for r in rows if not r[3]]
    check(f"tae: fastest right-hand moment inside the TAE type-1 window for {len(rows) - len(bad)}/{len(rows)} attacks"
          + (f" (outside: {[(a, round(t, 3), w) for a, t, w, _ in bad]})" if bad else ""), not bad)
    body = info.get("body", {})
    caps = body.get("caps", [])
    check(f"body: ragdoll capsules read ({len(caps)}, skipped {body.get('skipped')}, {body.get('missing', '')})",
          len(caps) >= 15 and not body.get("skipped"))
    far = [(c["rag"], round(_seg_point(c["a"], c["b"], [0, 0, 0]), 3)) for c in caps
           if _seg_point(c["a"], c["b"], [0, 0, 0]) > BODY_TOL]
    check(f"body: every capsule within {BODY_TOL} m of its bone in the bind pose (far: {far})", not far)
    r = subprocess.run([str(GL.GODOT), "--headless", "--path", str(ROOT / "sim" / "godot"), "res://replay.tscn", "--",
                        f"--dump={REPLAY_AT}", "--dump-body"], capture_output=True, text=True, encoding="utf-8", timeout=600)
    line = next((x for x in r.stdout.splitlines() if x.startswith("REPLAY_DUMP ")), None)
    if line is None:
        print("skip: replay dump (no replay data)")
    else:
        g = json.loads(line[len("REPLAY_DUMP "):])[0]
        bc = g.get("body", {}).get(REPLAY_FOE, [])
        pos = g["chars"].get(REPLAY_FOE)
        ys = [p[1] - pos[1] for cap in bc for p in cap[:2]] if pos else []
        xz = [np.hypot(p[0] - pos[0], p[2] - pos[2]) for cap in bc for p in cap[:2]] if pos else []
        check(f"body in the replay: #{REPLAY_FOE} has {len(bc)} capsules, height {min(ys or [0]):.2f}–{max(ys or [0]):.2f} m, "
              f"widest {max(xz or [0]):.2f} m from its position", len(bc) == len(caps) and -0.1 < min(ys) and
              1.0 < max(ys) < 2.0 and max(xz) < 1.2)   # a crouched attack pose tops out near 1.2 m
    print("chr_glb_test: 전부 통과")


def _seg_point(a, b, p) -> float:
    a, b, p = (np.asarray(x, float) for x in (a, b, p))
    d = b - a
    u = 0.0 if d @ d < 1e-12 else float(np.clip((p - a) @ d / (d @ d), 0, 1))
    return float(np.linalg.norm(a + d * u - p))


if __name__ == "__main__":
    main()
