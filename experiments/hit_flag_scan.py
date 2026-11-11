"""Find a memory value that is on exactly while a foe's attack hitbox is live (10-19 analysis item 1, MoKa "1번 … 진행해 줘").

  python experiments/hit_flag_scan.py record [secs=120] [--prep BACKUP]   stand next to hollow A, dump its blocks every read
  python experiments/hit_flag_scan.py analyze FILE.npz                      rank bits / bytes against the TAE windows

Why: placing the player in front of the foe (tae-verify B-15 … B-17) mixes "window over" with "blade already passed this
spot". A value the game sets while a TAE attack event (type 1 / 2) is live would give the window directly. Same method as
the anim time (docs/rea.md 3차): log raw blocks, line them up with a clock we trust — here the foe's anim time `at`
against `tae.json`'s windows for its current anim (83/83 hits fell inside them, 10-19).

Blocks per read (foe A): ChrIns +0x0…+0x1200, ChrCtrl ([+0x68]) +0x0…+0x400, ActionCtrl ([ChrCtrl+0x48]) +0x0…+0x560,
active EzState machine ([ActionCtrl+0x50]) +0x0…+0x200 (Overhaul PlayerInsStruct.h layout). Read only, except what
probe_setup does (PlayerNoDead, warp, HP) and the HP refill. The dump stays local (data/scratch/, not committed).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "scratch"
HZ = 240                # reads per s (the game's anim time steps by 1/60 s)
BLOCKS = (("chrins", None, 0x1200), ("chrctrl", (0x68,), 0x400), ("actionctrl", (0x68, 0x48), 0x560),
          ("ezstate", (0x68, 0x48, 0x50), 0x200))
NPC_A = 254010


def _addr(tm, ptr: int, chain) -> int | None:
    a = ptr
    for off in chain or ():
        a = tm.q(a + off) if a else None
    return a


def record(secs: float, prep: str | None, refill=(500, 793)) -> Path:
    import dsr_telemetry
    tm = dsr_telemetry.DSRTelemetry({})
    setup = None
    try:
        if prep:
            import probe_setup
            setup = probe_setup.prep(tm, prep)
        s = tm.snapshot(30)
        a = next((c for c in s.hostile(30) if c.npc_param == NPC_A), None)
        if a is None:
            raise SystemExit(f"{NPC_A} 없음")
        ptr = a.ptr
        n_max = int(secs * HZ) + 10           # paced: unpaced reads ran ~4400/s and filled the arrays in 6.8 s (10-19 first try)
        dumps = {name: np.zeros((n_max, size), np.uint8) for name, _c, size in BLOCKS}
        ok = {name: np.zeros(n_max, bool) for name, _c, _s in BLOCKS}
        t = np.zeros(n_max)
        anim = np.full(n_max, -2, np.int32)
        at = np.full(n_max, np.nan)
        hp = np.zeros(n_max, np.int32)
        dist = np.full(n_max, np.nan)
        t0 = time.perf_counter()
        n = 0
        while n < n_max and (now := time.perf_counter() - t0) < secs:
            for name, chain, size in BLOCKS:
                ad = _addr(tm, ptr, chain)
                if ad:
                    try:
                        dumps[name][n] = np.frombuffer(tm.pm.read_bytes(ad, size), np.uint8)
                        ok[name][n] = True
                    except Exception:
                        pass
            ac = _addr(tm, ptr, (0x68, 0x48))
            anim[n] = tm.i32(ac + 0x80) if ac else -2
            v = tm.anim_time(ptr)
            at[n] = v if v is not None else np.nan
            pp = tm.player_ptr()
            hp[n] = tm.i32(pp + 0x3E8) or 0
            if refill and hp[n] < refill[0]:
                tm.set_hp(refill[1])
            t[n] = now
            if n % 20 == 0:
                c = tm.read_chr(ptr)
                s = tm.snapshot(5)
                dist[n] = ((c.x - s.player.x) ** 2 + (c.z - s.player.z) ** 2) ** 0.5 if c and s else np.nan
            n += 1
            nxt = t0 + n / HZ
            while time.perf_counter() < nxt:
                pass
        OUT.mkdir(parents=True, exist_ok=True)
        out = OUT / time.strftime("%Y%m%d_%H%M%S_hit-flag-scan.npz")
        np.savez_compressed(out, t=t[:n], anim=anim[:n], at=at[:n], hp=hp[:n], dist=dist[:n],
                            **{f"d_{k}": v[:n] for k, v in dumps.items()}, **{f"ok_{k}": v[:n] for k, v in ok.items()},
                            meta=json.dumps({"npc": NPC_A, "secs": secs, "blocks": [(b[0], b[1], b[2]) for b in BLOCKS],
                                             "prep": {k: v for k, v in (setup or {}).items() if k != "home"}}))
        print(f"{n} reads in {t[n - 1]:.1f} s ({n / max(t[n - 1], 1e-9):.0f}/s) → {out}")
        return out
    finally:
        if setup is not None:
            import probe_setup
            probe_setup.finish(tm, setup["nodead_before"])


def active(anim: np.ndarray, at: np.ndarray, windows: dict[int, list[tuple[float, float]]]) -> np.ndarray:
    """1 where the foe's current anim has a TAE attack window (type 1 / 2) containing its anim time, 0 where it has none,
    -1 where unknown (no anim time, or within one frame of a window edge — the read can't tell which side)."""
    out = np.zeros(len(anim), np.int8)
    edge = 1 / 60
    for i, (a, x) in enumerate(zip(anim, at)):
        if np.isnan(x):
            out[i] = -1
            continue
        ws = windows.get(int(a), [])
        if any(s - edge <= x <= s + edge or e - edge <= x <= e + edge for s, e in ws):
            out[i] = -1
        elif any(s < x < e for s, e in ws):
            out[i] = 1
    return out


def tae_windows(model: str = "c2540") -> dict[int, list[tuple[float, float]]]:
    tae = json.loads((ROOT / "data" / "gamefiles" / "tae.json").read_text(encoding="utf-8"))
    out = {}
    for k, v in tae["models"][model]["animations"].items():
        ws = [(e["start"], e["end"]) for e in v["events"] if e["type"] in (1, 2)]
        if ws and k.isdigit():
            out[int(k)] = ws
    return out


def rank(dump: np.ndarray, valid: np.ndarray, act: np.ndarray, top: int = 15) -> list[dict]:
    """Score every bit (and every byte != its most common value) by how well it equals `act` (1 / 0) on the reads where
    act is known and the block was read. Score = min(recall on act=1, specificity on act=0) — a constant bit scores 0."""
    m = valid & (act >= 0)
    a = act[m] == 1
    d = dump[m]
    if a.sum() == 0 or (~a).sum() == 0:
        return []
    res = []
    bits = np.unpackbits(d[:, :, None], axis=2)[:, :, ::-1]           # [read, byte, bit0..7]
    on1 = bits[a].mean(axis=0)                                          # P(bit = 1 | active)
    on0 = bits[~a].mean(axis=0)                                         # P(bit = 1 | inactive)
    for pol, s in (("set", np.minimum(on1, 1 - on0)), ("clear", np.minimum(1 - on1, on0))):
        for off, bit in zip(*np.unravel_index(np.argsort(-s, axis=None)[:top], s.shape)):
            res.append({"kind": "bit", "off": int(off), "bit": int(bit), "when_active": pol, "score": round(float(s[off, bit]), 4),
                        "p_active": round(float(on1[off, bit]), 3), "p_inactive": round(float(on0[off, bit]), 3)})
    mode = np.array([np.bincount(d[~a, j]).argmax() for j in range(d.shape[1])])
    nz1 = (d[a] != mode).mean(axis=0)
    nz0 = (d[~a] != mode).mean(axis=0)
    s = np.minimum(nz1, 1 - nz0)
    for off in np.argsort(-s)[:top]:
        res.append({"kind": "byte", "off": int(off), "rest_value": int(mode[off]), "score": round(float(s[off]), 4),
                    "p_active": round(float(nz1[off]), 3), "p_inactive": round(float(nz0[off]), 3)})
    return sorted(res, key=lambda r: -r["score"])[:top]


def analyze(path: Path, top: int = 12) -> dict:
    z = np.load(path, allow_pickle=False)
    act = active(z["anim"], z["at"], tae_windows())
    meta = json.loads(str(z["meta"]))
    out = {"reads": int(len(z["t"])), "active_reads": int((act == 1).sum()), "inactive_reads": int((act == 0).sum()),
           "attack_anims": sorted({int(a) for a, x in zip(z["anim"], act) if x == 1}), "blocks": {}}
    for name, _c, _s in meta["blocks"]:
        out["blocks"][name] = rank(z[f"d_{name}"], z[f"ok_{name}"], act, top)
    return out


def edges(path: Path, block: str, off: int, bit: int | None = None, set_when_active: bool = True) -> list[dict]:
    """For one candidate: per attack-anim run, the anim times where it turned on / off, next to the TAE windows."""
    z = np.load(path, allow_pickle=False)
    ws = tae_windows()
    v = z[f"d_{block}"][:, off]
    on = ((v >> bit) & 1).astype(bool) if bit is not None else v != np.bincount(v).argmax()
    if not set_when_active:
        on = ~on
    out, i, n = [], 0, len(v)
    while i < n:
        a = int(z["anim"][i])
        j = i
        while j < n and int(z["anim"][j]) == a:
            j += 1
        if a in ws:
            ups = [round(float(z["at"][k]), 4) for k in range(i + 1, j) if on[k] and not on[k - 1]]
            downs = [round(float(z["at"][k]), 4) for k in range(i + 1, j) if not on[k] and on[k - 1]]
            out.append({"anim": a, "windows": ws[a], "on_at": ups, "off_at": downs})
        i = j
    return out


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "record"
    if cmd == "record":
        secs = float(sys.argv[2]) if len(sys.argv) > 2 and not sys.argv[2].startswith("-") else 120.0
        prep = sys.argv[sys.argv.index("--prep") + 1] if "--prep" in sys.argv else None
        record(secs, prep)
    elif cmd == "analyze":
        print(json.dumps(analyze(Path(sys.argv[2])), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
