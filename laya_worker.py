"""Laya shadow worker — runs in its own venv (torch + laya), never in the bot process (LAYA.md).

  .venv-laya\\Scripts\\python laya_worker.py --download                  fetch the pinned checkpoint once (network)
  .venv-laya\\Scripts\\python laya_worker.py --out x.laya.jsonl          read requests (one JSON per line) on stdin
  python laya_worker.py --out x.laya.jsonl --backend fake:guard          no model — for tests

Answers go to --out only; nothing is written back to the bot. HF_HUB_OFFLINE=1 unless --download, so a missing
checkpoint fails to load instead of reaching the network mid-run.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", help="answers (.laya.jsonl)")
    ap.add_argument("--backend", default="laya", help="laya | fake:<tactic> | fake:slow:<s> | fake:raise | fake:garbage")
    ap.add_argument("--model", default="convaiinnovations/laya")
    ap.add_argument("--subfolder", default=None)
    ap.add_argument("--revision", default=None, help="default: the reviewed commit pinned in laya_shadow.PINNED_REVISION")
    ap.add_argument("--device", default=None, help="cpu | cuda (default: laya's own choice)")
    ap.add_argument("--min-conf", type=float, default=None)
    ap.add_argument("--download", action="store_true", help="download the checkpoint and exit (the only networked step)")
    a = ap.parse_args()
    if not a.download:
        os.environ["HF_HUB_OFFLINE"] = "1"
    import laya_shadow as LS
    kw = dict(model=a.model, subfolder=a.subfolder, revision=a.revision or LS.PINNED_REVISION, device=a.device)
    if a.download:
        b = LS.LayaBackend(**kw)
        print(json.dumps(b.info))
        return
    out = open(a.out, "a", encoding="utf-8")

    def write(row: dict) -> None:
        out.write(json.dumps(row, ensure_ascii=False) + "\n")
        out.flush()

    try:
        backend = LS.make_backend(a.backend, **kw)
    except Exception as e:                               # bot keeps going; its channel sees the closed pipe and stops sending
        write({"type": "error", "stage": "load", "t": time.time(), "why": repr(e)[:300]})
        return
    min_conf = LS.MIN_CONF if a.min_conf is None else a.min_conf
    write({"type": "ready", "t": time.time(), "pid": os.getpid(), "min_conf": min_conf, **backend.info})
    for line in sys.stdin.buffer:
        try:
            req = json.loads(line)
        except Exception as e:
            write({"type": "error", "stage": "parse", "t": time.time(), "why": repr(e)[:200]})
            continue
        write(LS.answer(req, backend, min_conf))
    write({"type": "bye", "t": time.time()})


if __name__ == "__main__":
    main()
