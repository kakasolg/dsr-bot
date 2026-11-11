"""스크린샷 리뷰 도구 오프라인 테스트 — shot_review.py 의 창 없는 부분 ([MoKa] 2026-10-31 "다음장으로 연속으로 넘기고 코멘트").

  python tests/shot_review_test.py
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import shot_review as S


def _fake(tmp: Path) -> tuple[Path, Path]:
    runs = tmp / "runs"
    runs.mkdir()
    name = "20261031_164248_burg-upper"
    (runs / f"{name}.settings.json").write_text(json.dumps({"started": "2026-10-31T16:42:48-07:00"}), encoding="utf-8")
    (runs / f"{name}.log").write_text("[    0.1] run start\n[  225.1] ══ 구역 4 끝\n[  226.0] 구역5 시작\n[  300.0] 나중\n",
                                      encoding="utf-8")
    snap = {"x": 19.9, "y": -5.72, "z": -103.7, "hp": 500}
    (runs / f"{name}.track.jsonl").write_text(
        json.dumps({"rt": 0.0, "type": "run"}) + "\n" + json.dumps({"rt": 225.5, "type": "snap", "player": snap}) + "\n",
        encoding="utf-8")
    shots = tmp / "shots_20261031_164247_burg-upper"
    shots.mkdir()
    for n in ("164247_788.jpg", "164633_500.jpg", "164634_501.jpg", "notes.txt"):
        (shots / n).write_bytes(b"")
    return runs, shots


def test_data() -> None:
    with tempfile.TemporaryDirectory() as d:
        runs, shots = _fake(Path(d))
        files = S.shots(shots)
        assert [f.name for f in files] == ["164247_788.jpg", "164633_500.jpg", "164634_501.jpg"]
        assert S.shot_time(files[1], "20261031") == datetime(2026, 10, 31, 16, 46, 33, 500000)
        settings = S.find_run(shots, runs)
        assert settings is not None and settings.name.startswith("20261031_164248"), settings
        run = S.RunData(settings)
        c = S.context(files[1], "20261031", run)                   # 16:46:33.5 = run 225.5 s
        assert c["rt"] == 225.5 and c["hp"] == 500 and c["place"] == "상층 4 · 송진 문", c
        assert run.lines(c["rt"]) == ["[  225.1] ══ 구역 4 끝", "[  226.0] 구역5 시작"]
        assert S.context(files[0], "20261031", run)["hp"] is None   # before the first snapshot
        print("ok  data: shot names → time → run 225.5 s, 상층 4 · 송진 문, HP 500, log lines around it")


def test_review_store() -> None:
    with tempfile.TemporaryDirectory() as d:
        _, shots = _fake(Path(d))
        rv = S.Review(shots)
        rv.set("164633_500.jpg", "  문 앞을 그냥 지나감 ", {"rt": 225.5, "place": "상층 4 · 송진 문"})
        again = S.Review(shots)                                   # read back from review.json
        assert again.get("164633_500.jpg") == "문 앞을 그냥 지나감"
        assert again.data["164633_500.jpg"]["place"] == "상층 4 · 송진 문"
        again.set("164633_500.jpg", "   ", {})                    # empty = delete
        assert S.Review(shots).data == {}
        print("ok  review.json: save (trimmed, with context) · read back · empty deletes")


def test_viewer_keeps_typed_text() -> None:
    """[MoKa] 10-31 "처음만 제대로 저장 되고, 그 다음부터 저장이 잘 않됨": typed text survives moving on, Enter saves."""
    try:
        import tkinter as tk
        tk.Tk().destroy()
    except Exception as e:                                         # no display
        print(f"skip viewer: {e}")
        return
    from PIL import Image
    with tempfile.TemporaryDirectory() as d:
        runs, shots = _fake(Path(d))
        for f in S.shots(shots):
            Image.new("RGB", (32, 18)).save(f)
        v = S.Viewer(shots, S.RunData(S.find_run(shots, runs)))
        try:
            v.edit()
            v.entry.insert(0, "첫 코멘트")
            v.save()                                                 # Enter (the delay is only for the IME)
            v.go(1)
            v.edit()
            v.entry.insert(0, "두번째 — Enter 없이 넘김")
            v.go(1)                                                  # moved on without Enter → kept
            v.go(-1)
            assert v.entry.get() == "두번째 — Enter 없이 넘김"
            v.entry.delete(0, "end")
            v.entry.insert(0, "두번째 고침")
            v.save()
            v.edit()
            v.entry.delete(0, "end")
            v.go(-1)                                                 # emptied but no Enter → not deleted
            got = S.Review(shots).data
            assert {k: c["comment"] for k, c in got.items()} == {"164247_788.jpg": "첫 코멘트",
                                                                  "164633_500.jpg": "두번째 고침"}, got
        finally:
            v.root.destroy()
    print("ok  viewer: Enter saves · moving on keeps typed text · second save on another shot works · empty without Enter keeps")


if __name__ == "__main__":
    test_data()
    test_review_store()
    test_viewer_keeps_typed_text()
    print("전부 통과")
