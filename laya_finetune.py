"""Small DSR fine-tune of Laya on the ramp decisions MoKa endorsed (LAYA.md 14) — offline only, nothing reaches the bot.

Runs in the WSL venv (torch + laya):
  ~/laya-venv/bin/python laya_finetune.py --mode head          # decision head only, encoder frozen
  ~/laya-venv/bin/python laya_finetune.py --mode full          # whole model (official recipe's learning rates)
  ~/laya-venv/bin/python laya_finetune.py --eval-only base     # the shipped checkpoint on the same test, for comparison

Data: data/samples/clear-ramp-shadow-2026-10-01-a*.laya.jsonl — per-tick (bot's own features, the rule that fired) from the
ramp runs MoKa endorsed ("가장 원하는 플레이", "#4 가드 빼고 좋았음"). label_source = endorsed_run: the bot's tactic in a run a
person approved, not a per-tick human label. Split by run: a1+a2 train, a3 test (the set's last run, rule fixed before).
Model input = laya_shadow.state_for(features) — exactly what the shadow worker sends. Question = choice over the
permitted tactics (laya_shadow.questions_for), options shuffled per training copy (position bias, Laya #131).

Recipe follows NandhaKishorM/laya notebooks/laya_finetune_typed_decisions_mps.py (Apache-2.0): soft-target cross-entropy
plus the proper-scoring-rule policy-gradient term. Checkpoints go to ~/laya-ft/<name> (WSL home, not the repo); the
metrics go to data/laya/ft_<name>.json.
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import random
import statistics
import sys
import time
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import laya_shadow as LS  # noqa: E402

DATA = sorted(glob.glob(str(ROOT / "data" / "samples" / "clear-ramp-shadow-2026-10-01-a*.laya.jsonl")))
TRAIN_RUNS, TEST_RUNS = ("a1", "a2"), ("a3",)
# MoKa's correction (LAYA.md 13): #4 254001 is a two-handed axe hollow; the bot's features called it 'ranged'
FIX_KIND = {254001: "hollow"}


def load_cases() -> list:
    out = []
    for fn in DATA:
        run = Path(fn).name.split("-")[-1].split(".")[0]
        for line in open(fn, encoding="utf-8"):
            r = json.loads(line)
            if r.get("type") != "answer" or r.get("policy") not in r.get("allowed", []):
                continue
            f = dict(r["feat"])
            if r.get("npc") in FIX_KIND and f.get("target_kind") == "ranged":
                f["target_kind"] = FIX_KIND[r["npc"]]
            out.append({"run": run, "fight": f"{run}:{r['fight']}", "feat": f, "allowed": r["allowed"], "label": r["policy"],
                        "label_source": "endorsed_run", "rule": r["rule"]})
    return out


def model_dir() -> str:
    """The pinned checkpoint as laya cached it (only the 5 files laya needs — the repo's other files were never fetched)."""
    from huggingface_hub.constants import HF_HUB_CACHE
    p = Path(HF_HUB_CACHE) / "models--convaiinnovations--laya" / "snapshots" / LS.PINNED_REVISION
    if not (p / "model.safetensors").exists():
        raise SystemExit(f"checkpoint not cached at {p} — run laya_worker.py --download first")
    return str(p)


def items_for(cases, tok, cfg, perms: int, seed: int) -> list:
    from laya.common import QTYPES, build_sequence, render_options
    rng = random.Random(seed)
    out = []
    for c in cases:
        al = list(c["allowed"])
        orders = [al] + [rng.sample(al, len(al)) for _ in range(perms - 1)]
        for order in orders:
            q = LS.questions_for(order)["tactic"]
            crit = q["criteria"]
            target = [1.0 if k == c["label"] else 0.0 for k in crit]
            seq, markers = build_sequence(tok, LS.state_for(c["feat"]), {"t": "choice", "ins": q["instructions"], "crit": crit},
                                          cfg["max_len"], cfg["head_max_len"])
            if len(markers) != len(render_options({"t": "choice", "crit": crit})):
                continue
            out.append({"ids": seq, "markers": markers, "qtype": QTYPES["choice"], "target": target})
    return out


def collate(items, pad_id):
    import torch
    b, n = len(items), max(len(i["ids"]) for i in items)
    k = max(len(i["markers"]) for i in items)
    ids = torch.full((b, n), pad_id, dtype=torch.long)
    att = torch.zeros((b, n), dtype=torch.long)
    pos = torch.zeros((b, k), dtype=torch.long)
    mask = torch.zeros((b, k), dtype=torch.bool)
    tgt = torch.zeros((b, k))
    for i, it in enumerate(items):
        ids[i, :len(it["ids"])] = torch.tensor(it["ids"])
        att[i, :len(it["ids"])] = 1
        pos[i, :len(it["markers"])] = torch.tensor(it["markers"])
        mask[i, :len(it["markers"])] = True
        tgt[i, :len(it["target"])] = torch.tensor(it["target"])
    return ids, att, pos, mask, tgt, torch.tensor([it["qtype"] for it in items])


def train(name: str, mode: str, epochs: int, perms: int, micro: int, seed: int) -> str:
    import torch
    from safetensors.torch import load_file, save_file
    from transformers import AutoTokenizer
    from laya.agent import _fix_tokenizer_config
    from laya.common import build_model, proper_reward
    torch.manual_seed(seed)
    md = model_dir()
    _fix_tokenizer_config(md)
    cfg = json.load(open(Path(md) / "rl_agent_config.json"))
    tok = AutoTokenizer.from_pretrained(Path(md) / "tokenizer")
    cases = [c for c in load_cases() if c["run"] in TRAIN_RUNS]
    items = items_for(cases, tok, cfg, perms, seed)
    model = build_model(cfg, encoder_dir=str(Path(md) / "encoder"))
    model.load_state_dict(load_file(str(Path(md) / "model.safetensors")), strict=True)
    model.float()
    dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    enc = [p for n, p in model.named_parameters() if "encoder." in n]
    head = [p for n, p in model.named_parameters() if "encoder." not in n]
    if mode == "head":
        for p in enc:
            p.requires_grad_(False)
        groups = [{"params": head, "lr": 1e-4}]
    else:
        model.encoder.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
        model.head_checkpointing = True
        groups = [{"params": enc, "lr": 2.5e-5}, {"params": head, "lr": 1e-4}]
    model.to(dev).train()
    opt = torch.optim.AdamW(groups, weight_decay=0.01)
    steps = max(1, math.ceil(len(items) / micro) * epochs)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=steps, eta_min=1e-6)
    t0, log = time.time(), []
    for ep in range(epochs):
        random.Random(seed + ep).shuffle(items)
        sigma = 0.4 + (0.1 - 0.4) * ep / max(1, epochs - 1)
        tot = 0.0
        for s in range(0, len(items), micro):
            ids, att, pos, mask, tgt, qt = [x.to(dev) for x in collate(items[s:s + micro], tok.pad_token_id)]
            logits, act = model(ids, att, pos, mask, qt)
            logits = logits.float()
            k = mask.sum(-1, keepdim=True).float()
            eps = torch.randn((4,) + logits.shape, device=dev) * sigma * mask
            eps = (eps - eps.sum(-1, keepdim=True) / k) * mask
            noisy = logits.detach().unsqueeze(0) + eps
            probs = torch.softmax(noisy.masked_fill(~mask, -1e4), -1)
            with torch.no_grad():
                rew = proper_reward(probs, tgt.unsqueeze(0), qt, mask, w_sph=0.75, w_rps=1.0)
                adv = (rew - rew.mean(0, keepdim=True)) / (rew.std() + 1e-6)
            logp = -(((noisy - logits.unsqueeze(0)) ** 2) * mask).sum(-1) / (2 * sigma ** 2)
            loss = -(adv * logp).mean() - (tgt * torch.log_softmax(logits.masked_fill(~mask, -1e4), -1)).sum(-1).mean() + 0.0 * act.sum()
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            sched.step()
            tot += loss.item()
        log.append({"epoch": ep + 1, "loss": round(tot / math.ceil(len(items) / micro), 4)})
        print(f"epoch {ep + 1}/{epochs} loss {log[-1]['loss']}", flush=True)
    out = Path.home() / "laya-ft" / name
    out.mkdir(parents=True, exist_ok=True)
    save_file({n: v.detach().half().cpu().contiguous() for n, v in model.state_dict().items()}, str(out / "model.safetensors"))
    model.encoder.config.save_pretrained(out / "encoder")
    tok.save_pretrained(out / "tokenizer")
    cfg2 = dict(cfg, fine_tuned=True, model_name=f"dsr-{name}",
                training={"data": [Path(d).name for d in DATA], "train_runs": TRAIN_RUNS, "cases": len(cases), "items": len(items),
                          "mode": mode, "epochs": epochs, "perms": perms, "seconds": round(time.time() - t0), "log": log})
    json.dump(cfg2, open(out / "rl_agent_config.json", "w"), indent=2)
    print(f"saved {out} ({time.time() - t0:.0f} s)")
    return str(out)


def evaluate(name: str, path: str | None) -> dict:
    """Test run(s): agreement with the endorsed tactic, majority baseline, per tactic, option-order flips, confidence, latency."""
    import torch
    import laya
    agent = laya.load(path or "convaiinnovations/laya", revision=None if path else LS.PINNED_REVISION,
                      device="cuda" if torch.cuda.is_available() else "cpu")
    test = [c for c in load_cases() if c["run"] in TEST_RUNS]
    for c in test[:3]:
        agent.predict(LS.state_for(c["feat"]), LS.questions_for(c["allowed"]))            # warm-up
    rows, ms = [], []
    for c in test:
        st = LS.state_for(c["feat"])
        t0 = time.perf_counter()
        a = agent.predict(st, LS.questions_for(c["allowed"]))["answers"]["tactic"]
        ms.append((time.perf_counter() - t0) * 1000)
        rev = agent.predict(st, LS.questions_for(list(reversed(c["allowed"]))))["answers"]["tactic"]
        rows.append({"label": c["label"], "choice": a["choice"], "top_p": a.get("answer_confidence"), "conf": a.get("confidence"),
                     "rev_choice": rev["choice"], "fight": c["fight"]})
    n = len(rows)
    labels = sorted({r["label"] for r in rows})
    maj = max(labels, key=lambda l: sum(r["label"] == l for r in rows))
    ms.sort()
    res = {"name": name, "checkpoint": path or f"convaiinnovations/laya@{LS.PINNED_REVISION[:7]}", "test_runs": TEST_RUNS, "n": n,
           "fights": len({r["fight"] for r in rows}),
           "agreement": round(sum(r["choice"] == r["label"] for r in rows) / n, 3),
           "majority_baseline": {"label": maj, "rate": round(sum(r["label"] == maj for r in rows) / n, 3)},
           "per_label": {l: f"{sum(r['choice'] == l for r in rows if r['label'] == l)}/{sum(r['label'] == l for r in rows)}" for l in labels},
           "chosen": {l: sum(r["choice"] == l for r in rows) for l in sorted({r["choice"] for r in rows})},
           "order_flip_rate": round(sum(r["choice"] != r["rev_choice"] for r in rows) / n, 3),
           "top_p_median": round(statistics.median(r["top_p"] for r in rows if r["top_p"] is not None), 3),
           "latency_ms": {"p50": round(ms[n // 2], 1), "p95": round(ms[int(.95 * (n - 1))], 1)},
           "mistakes": [r for r in rows if r["choice"] != r["label"]][:12]}
    out = ROOT / "data" / "laya" / f"ft_{name}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k != "mistakes"}, ensure_ascii=False))
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["head", "full"], default="head")
    ap.add_argument("--name", default=None)
    ap.add_argument("--epochs", type=int, default=4)
    ap.add_argument("--perms", type=int, default=3)
    ap.add_argument("--micro", type=int, default=4)
    ap.add_argument("--seed", type=int, default=20261001)
    ap.add_argument("--eval-only", default=None, help="'base' = the shipped checkpoint, or a checkpoint path")
    ap.add_argument("--test", default="a3", help="held-out run (the others train) — rotate for a by-run estimate")
    a = ap.parse_args()
    global TRAIN_RUNS, TEST_RUNS
    TEST_RUNS = (a.test,)
    TRAIN_RUNS = tuple(r for r in ("a1", "a2", "a3") if r != a.test)
    if a.eval_only:
        evaluate(("base" if a.eval_only == "base" else Path(a.eval_only).name) + f"-test-{a.test}", None if a.eval_only == "base" else a.eval_only)
        return
    name = a.name or f"ramp-v0-{a.mode}" + ("" if a.test == "a3" else f"-test-{a.test}")
    evaluate(name, train(name, a.mode, a.epochs, a.perms, a.micro, a.seed))


if __name__ == "__main__":
    main()
