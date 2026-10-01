"""Laya shadow mode must not change a single fight decision, never block the fight loop, and only ever record
tactics the rules permit (LAYA.md). No game, no model (fake backends).

  python tests/laya_shadow_test.py
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import itertools
import json
import sys
import tempfile
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import duel_golden_test as G
import laya_shadow as LS

ROOT = Path(__file__).resolve().parent.parent


class Boom:
    """Stands in for F.mv while the advisor runs — any use of Moves / the pad fails loudly."""
    def __getattr__(self, name):
        raise AssertionError(f"advisor touched Moves.{name}")


class NoMovesAdvisor(LS.Advisor):
    def observe(self, F, T, rule, out=None):
        saved, F.mv = F.mv, Boom()
        try:
            super().observe(F, T, rule, out)
        finally:
            F.mv = saved

    def end(self, F, res, T=None, rule=None):
        saved, F.mv = F.mv, Boom()
        try:
            super().end(F, res, T, rule)
        finally:
            F.mv = saved


def sample(step: int = 4):
    sits = itertools.chain(G.situations(), G.situations_terrain(), G.situations_axe())
    return [sc for i, sc in enumerate(sits) if i % step == 0]


def test_same_decisions() -> None:
    """Every duel trace (all Moves/pad calls, logs, result) is identical with and without an advisor — also when the
    advisor's send fails or its feature reading breaks."""
    sits = sample()
    sent: list = []

    def raising_send(req):
        raise RuntimeError("worker gone")

    real_features = LS.features
    variants = {
        "recording": lambda: NoMovesAdvisor(sent.append, min_interval=0.0),
        "send raises": lambda: LS.Advisor(raising_send, min_interval=0.0),
    }
    base = [G.run(sc) for sc in sits]
    for name, make in variants.items():
        advs = []
        for sc, want in zip(sits, base):
            adv = make()
            advs.append(adv)
            got = G.run(sc, advisor=adv)
            assert got == want, f"{name}: decision changed in {sc}\n want {want[:8]}\n got  {got[:8]}"
        errs = sum(a.errors for a in advs)
        if name == "recording":
            assert errs == 0, f"advisor errors: {[a.last_error for a in advs if a.errors][:3]}"
            assert len(sent) > len(sits), len(sent)
        else:
            assert errs > 0                                  # failures were swallowed and counted, not raised
    LS.features = lambda F, T: 1 / 0                         # broken feature code
    try:
        for sc, want in zip(sits[:300], base[:300]):
            assert G.run(sc, advisor=LS.Advisor(sent.append, min_interval=0.0)) == want
    finally:
        LS.features = real_features
    print(f"ok  {len(sits)} golden situations × 3 advisor variants: same decisions ({len(sent)} requests recorded)")


def test_requests_only_permitted() -> None:
    """Requests carry only observed numbers; the rule's own tactic is (almost always) inside the mask; the questions
    offer exactly the permitted tactics."""
    reqs: list = []
    for sc in sample(10):
        G.run(sc, advisor=LS.Advisor(reqs.append, min_interval=0.0))
    assert reqs
    outside = [r for r in reqs if r["policy"] not in r["allowed"]]
    for r in reqs:
        st = LS.state_for(r["feat"])
        assert not any(k.startswith("_") for k in st) and None not in st.values()
        assert set(LS.questions_for(r["allowed"])["tactic"]["criteria"]) == set(r["allowed"])
        json.dumps(r)                                        # must cross the pipe as JSON
    # known, documented gaps (LAYA.md 8): fake reflex in the golden harness never fires (attack with another foe swinging),
    # rule_finish has no reach check (finish while out of reach)
    def known(r):
        f = r["feat"]
        return ((r["rule"] == "attack" and f["other_swinging_near"])
                or (r["rule"] == "finish" and f["distance_m"] > f["weapon_reach_m"] + 0.3))
    unknown = [r for r in outside if not known(r)]
    assert not unknown, {(r["rule"], r["policy"], json.dumps(LS.state_for(r["feat"]))) for r in unknown[:3]}
    print(f"ok  {len(reqs)} requests: state is observed fields only, {len(outside)} rule attacks outside the mask (known)")


def test_mask() -> None:
    base = dict(distance_m=1.0, height_diff_m=0.0, weapon_reach_m=1.6, _sp_ok=True, other_swinging_near=False, _shield=True,
                estus_wanted=False, _arena=False, _may_retreat=True, _room=False, target_one_hit=False, _reflex_on=True)
    assert LS.allowed(base) == ["attack", "guard", "hold_position", "retreat"]
    assert "attack" not in LS.allowed({**base, "distance_m": 2.5})
    assert "approach" in LS.allowed({**base, "distance_m": 2.5})
    assert "attack" not in LS.allowed({**base, "height_diff_m": 1.5})
    assert "attack" not in LS.allowed({**base, "_sp_ok": False})
    assert "attack" not in LS.allowed({**base, "other_swinging_near": True})
    assert "attack" in LS.allowed({**base, "other_swinging_near": True, "target_one_hit": True})
    assert "retreat" not in LS.allowed({**base, "_may_retreat": False})            # desperate: fight to the end
    assert "backstab" not in LS.allowed(base) and "backstab" in LS.allowed({**base, "_room": True})
    assert "heal" in LS.allowed({**base, "estus_wanted": True})
    assert "guard" not in LS.allowed({**base, "_shield": False})
    print("ok  mask follows the rule conditions")


def test_read_answer() -> None:
    al = ["guard", "hold_position"]
    ok = {"answers": {"tactic": {"choice": "guard", "confidence": 0.8, "probabilities": {"guard": 0.8, "hold_position": 0.2}}}}
    assert LS.read_answer(ok, al)["status"] == "ok"
    assert LS.read_answer(ok, al, min_conf=0.9)["status"] == "abstain"
    bad = {"answers": {"tactic": {"choice": "attack", "confidence": 0.99}}}
    r = LS.read_answer(bad, al)
    assert r["status"] == "invalid" and r["choice"] is None
    for junk in (None, {}, {"answers": "x"}, {"answers": {"tactic": {"choice": "guard", "confidence": "high"}}},
                 {"answers": {"tactic": {"choice": "guard", "confidence": 7}}}):
        assert LS.read_answer(junk, al)["status"] == "invalid", junk
    req = {"feat": {"distance_m": 1.0}, "allowed": al, "t_offer": time.time()}
    assert LS.answer(req, LS.FakeBackend("fake:raise"))["status"] == "error"
    assert LS.answer(req, LS.FakeBackend("fake:garbage"))["status"] == "invalid"
    assert LS.answer(req, LS.FakeBackend("fake:outside"))["status"] == "invalid"
    assert LS.answer(req, LS.FakeBackend("fake:guard"))["choice"] == "guard"
    LS.Advisor(lambda r: None).observe(None, None, "attack", None)   # nonsense in → nothing raised
    LS.Advisor(lambda r: None).end(None, None)
    print("ok  only permitted tactics come out; errors and junk become invalid/error rows")


def _req(i):
    return {"seq": i, "feat": {"distance_m": 1.0, "target_state": "idle"}, "allowed": ["guard", "hold_position"],
            "policy": "guard", "rule": "block", "t_offer": time.time(), "bot_os": sys.platform}


def test_worker_never_blocks() -> None:
    """A slow worker: offers return at once, the newest is kept, old ones are dropped and counted."""
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "x.laya.jsonl"
        ch = LS.WorkerChannel(LS.worker_cmd(out, sys.executable, backend="fake:slow:0.3"), log=lambda *a: None)
        worst = 0.0
        for i in range(60):
            t0 = time.perf_counter()
            ch.offer(_req(i))
            worst = max(worst, time.perf_counter() - t0)
            time.sleep(0.01)
        summary = ch.close()
        rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()]
        ans = [r for r in rows if r.get("type") == "answer"]
        assert rows[0]["type"] == "ready", rows[0]
        assert worst < 0.005, f"offer took {worst * 1000:.1f} ms"
        assert ch.dropped > 0 and 0 < len(ans) < 60, (ch.dropped, len(ans))
        assert all(r["status"] == "ok" and r["choice"] in r["allowed"] for r in ans)
        assert ans[0]["infer_ms"] >= 290                     # the worker's own clock
    print(f"ok  slow worker: worst offer {worst * 1000:.2f} ms, {summary}")


def test_worker_missing_model() -> None:
    """No laya/torch where the worker runs: it writes a load error and exits; the bot side keeps offering without error."""
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "x.laya.jsonl"
        ch = LS.WorkerChannel([sys.executable, str(ROOT / "laya_worker.py"), "--out", str(out), "--model", str(Path(d) / "nope")],
                              log=lambda *a: None)
        for i in range(40):
            ch.offer(_req(i))
            time.sleep(0.02)
        ch.close()
        rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()]
        assert rows and rows[0]["type"] == "error" and rows[0]["stage"] == "load", rows[:1]
        bad = LS.WorkerChannel(["no-such-program-laya"], log=lambda *a: None)    # can't even start
        bad.offer(_req(0))
        assert bad.dead and bad.dropped == 1
        bad.close()
    print("ok  missing model / missing worker: error recorded, fight side unaffected")


def test_wsl_command() -> None:
    cmd = LS.worker_cmd(Path("D:/dev/dsr-bot/data/runs/a.laya.jsonl"), "wsl", device="cuda")
    assert cmd[:2] == ["wsl", "-e"] and "/mnt/d/dev/dsr-bot/data/runs/a.laya.jsonl" in cmd and cmd[-2:] == ["--device", "cuda"]
    assert LS.wsl_path("C:\\x\\y.txt") == "/mnt/c/x/y.txt"
    print("ok  WSL worker command")


if __name__ == "__main__":
    test_mask()
    test_read_answer()
    test_wsl_command()
    test_requests_only_permitted()
    test_same_decisions()
    test_worker_never_blocks()
    test_worker_missing_model()
