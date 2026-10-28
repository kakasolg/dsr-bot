"""Run TLC on PadFreeze.tla for every (variant, script, bound, property) row below; write out/results.tsv and print it.

    python docs/formal/pad_freeze/run_tlc.py <path-to-tla2tools.jar> [filter-substring]

One property per run (plus TypeOK), so each counterexample is the shortest for that property. Probes (R*) are expected to
be VIOLATED: they show the interesting case of a property is reachable under that bound.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
VARIANTS = ["current", "block", "ownerNeutral", "both", "minimal"]
QUIT = ["S1_MenuClean", "S1b_MenuNoB", "S3_Handoff", "S4_ReSprint", "S4_ReGuard", "S5_StaleNoKill", "S6_NoOrphanLB"]
TAPPER = ["S2_NoOrphanA", "S5_StaleNoKill"]
PROBES_QUIT = ["R1_menuAfterBlockedCall", "R1_menuWithKeep", "R1_menuWithYoungB", "R3_nudgeUnfreezeLate",
               "R4_resprintAfterQuit", "R4_reguardAfterQuit", "R5_newerPressRipe"]
PROBES_TAPPER = ["R2_ripeAWhileFrozen", "R5_newerPressRipe"]


def rows():
    for v in VARIANTS:
        for ops in (3, 4):
            for p in QUIT:
                yield v, "quit", ops, True, p
            for p in ("S6_NoOrphanLB", "S6_post"):        # without n's guard calls: only the freeze-related LB family
                yield v, "quit", ops, False, p
            for p in TAPPER:
                yield v, "tapper", ops, True, p
        for p in PROBES_QUIT:
            yield v, "quit", 3, True, p
        yield v, "quit", 3, False, "R6_afterQuitWithKeep"
        for p in PROBES_TAPPER:
            yield v, "tapper", 3, True, p
        for script in ("quit", "tapper"):                 # S5 with n's hold of a tapped button (Y): normal-time path
            yield v, script, 3, True, "S5_StaleNoKill", True
            yield v, script, 3, True, "S5f_FrozenDueNoKill", True
            yield v, script, 4, True, "S5f_FrozenDueNoKill", True
            yield v, script, 3, True, "R5_newerPressRipe", True


def run(jar: str, v: str, script: str, ops: int, nguard: bool, prop: str, nhold: bool = False) -> dict:
    name = f"{v}_{script}_m{ops}{'' if nguard else '_noguard'}{'_hold' if nhold else ''}_{prop}"
    cfg = HERE / "cfg" / f"{name}.cfg"
    cfg.parent.mkdir(exist_ok=True)
    (HERE / "out").mkdir(exist_ok=True)
    cfg.write_text(
        "CONSTANTS\n"
        f'  Variant = "{v}"\n  Script = "{script}"\n  MaxOps = {ops}\n  UseNudge = TRUE\n'
        f"  NGuard = {'TRUE' if nguard else 'FALSE'}\n  NTap = TRUE\n  NHold = {'TRUE' if nhold else 'FALSE'}\n"
        f"SPECIFICATION Spec\nINVARIANT TypeOK\nINVARIANT {prop}\n", encoding="utf-8")
    cmd = ["java", "-XX:+UseParallelGC", "-cp", jar, "tlc2.TLC", "-deadlock", "-workers", "auto",
           "-metadir", str(HERE / "out" / f"states_{name}"), "-config", str(cfg), "PadFreeze"]
    res = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True, encoding="utf-8", errors="replace")
    log = res.stdout + res.stderr
    (HERE / "out" / f"{name}.log").write_text(log, encoding="utf-8")
    subprocess.run(["rm", "-rf", str(HERE / "out" / f"states_{name}")])
    if "Model checking completed. No error has been found" in log:
        verdict = "HOLDS"
    elif re.search(r"Invariant \w+ is violated", log):
        verdict = "VIOLATED"
        if "Invariant TypeOK is violated" in log:
            verdict = "TYPE-ERROR"
    else:
        verdict = "ERROR"
    gen = re.findall(r"(\d+) states generated, (\d+) distinct states found, (\d+) states left on queue", log)
    depth = re.search(r"depth of the complete state graph search is (\d+)", log)
    trace_len = len(re.findall(r"^State \d+: ", log, re.M))
    return {"name": name, "variant": v, "script": script, "maxops": ops, "nguard": nguard, "nhold": nhold, "prop": prop,
            "verdict": verdict, "completed": verdict == "HOLDS",
            "generated": gen[-1][0] if gen else "", "distinct": gen[-1][1] if gen else "",
            "depth": depth.group(1) if depth else "", "trace": trace_len or ""}


def main() -> None:
    jar = sys.argv[1]
    flt = sys.argv[2] if len(sys.argv) > 2 else ""
    out = []
    for r in rows():
        if flt and flt not in "_".join(map(str, r)):
            continue
        d = run(jar, *r)
        out.append(d)
        print(f"{d['variant']:<13}{d['script']:<7}m{d['maxops']}{'' if d['nguard'] else ' noguard':<9}"
              f"{' hold' if d['nhold'] else '':<6}{d['prop']:<26}{d['verdict']:<10}distinct={d['distinct']:<8}depth={d['depth']:<4}trace={d['trace']}",
              flush=True)
    keys = list(out[0])
    tsv = HERE / "out" / ("results.tsv" if not flt else f"results_{flt}.tsv")
    tsv.write_text("\t".join(keys) + "\n" + "".join("\t".join(str(d[k]) for k in keys) + "\n" for d in out),
                   encoding="utf-8")


if __name__ == "__main__":
    main()
