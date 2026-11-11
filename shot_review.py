"""Screenshot review — page through a run's 1/s game screenshots and write a comment on any of them ([MoKa] 2026-10-31:
"스크린샷에 내가 리뷰 할 수 있게 다음장으로 연속으로 넘기고 코멘트 달게").

  python shot_review.py <shots dir>              e.g. data/runs/shots_20261031_164247_burg-upper
  python shot_review.py <shots dir> --run <run>  the bot run it belongs to (default: found by time and name in data/runs)
  python shot_review.py <shots dir> --list       print the comments, no window

Each shot is shown with what the run knew at that moment: run time, place (places.where), HP, and the bot's log lines
from the second before it. Comments go to <shots dir>/review.json, written on every Enter, with that context (time,
place, position, HP) so they can be found again from a log time or a place.

Keys (image focused):  → Space D next · ← A previous · PgDn/PgUp ±10 · Home/End · P play/pause · [ ] slower/faster
                       C or Enter write a comment · N / B next / previous commented shot
In the comment box:    Enter save (empty = delete) · Esc back without saving
"""
from __future__ import annotations

import bisect
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
RUNS = ROOT / "data" / "runs"
REVIEW = "review.json"
SHOT_RE = re.compile(r"^(\d{6})_(\d{3})\.jpe?g$", re.I)
DIR_RE = re.compile(r"shots_(\d{8})_(\d{6})_(.+)$")
LOG_RE = re.compile(r"^\[\s*([\d.]+)\]\s?(.*)$")
LOG_BEFORE_S = 1.5         # log lines shown for a shot: this long before it …
LOG_AFTER_S = 0.5          # … to this long after (the shot is taken at the start of its second)
IME_WAIT_MS = 80           # Enter → read the box this much later (Korean IME commits its last syllable after the key)
RUN_MATCH_S = 30           # a run whose start is this close to the first shot, same name, is the shots' run


# ── Data (no window) ────────────────────────────────────────────────────────
def shots(folder: Path) -> list[Path]:
    return sorted(p for p in folder.iterdir() if SHOT_RE.match(p.name))


def shot_time(p: Path, day: str) -> datetime | None:
    """Wall-clock time from the name (HHMMSS_mmm.jpg) and the folder's date (YYYYMMDD)."""
    m = SHOT_RE.match(p.name)
    if not m:
        return None
    return datetime.strptime(day + m.group(1), "%Y%m%d%H%M%S") + timedelta(milliseconds=int(m.group(2)))


def find_run(folder: Path, runs: Path = RUNS) -> Path | None:
    """data/runs/<YYYYMMDD_HHMMSS>_<name>.settings.json started within RUN_MATCH_S of the folder's own time."""
    m = DIR_RE.search(folder.name)
    if not m:
        return None
    t0 = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
    best = None
    for p in runs.glob(f"{m.group(1)}_*_{m.group(3)}.settings.json"):
        try:
            t = datetime.strptime(p.name[:15], "%Y%m%d_%H%M%S")
        except ValueError:
            continue
        d = abs((t - t0).total_seconds())
        if d <= RUN_MATCH_S and (best is None or d < best[0]):
            best = (d, p)
    return best[1] if best else None


class RunData:
    """A run's log lines and position track by run time; empty when there is no run."""

    def __init__(self, settings: Path | None):
        self.start: datetime | None = None
        self.log: list[tuple[float, str]] = []
        self.snaps: list[tuple[float, dict]] = []
        self.name = None
        if settings is None:
            return
        self.name = settings.name[: -len(".settings.json")]
        try:
            st = json.loads(settings.read_text(encoding="utf-8")).get("started")
            self.start = datetime.fromisoformat(st).replace(tzinfo=None) if st else None
        except (OSError, ValueError):
            pass
        if self.start is None:
            self.start = datetime.strptime(self.name[:15], "%Y%m%d_%H%M%S")
        base = settings.with_name(self.name)
        try:
            for ln in base.with_suffix(".log").read_text(encoding="utf-8", errors="replace").splitlines():
                m = LOG_RE.match(ln)
                if m:
                    self.log.append((float(m.group(1)), m.group(2)))
        except OSError:
            pass
        try:
            with open(str(base) + ".track.jsonl", encoding="utf-8") as f:
                for ln in f:
                    try:
                        r = json.loads(ln)
                    except ValueError:
                        continue
                    if r.get("type") == "snap" and r.get("player"):
                        self.snaps.append((r["rt"], r["player"]))
        except OSError:
            pass
        self._log_t = [t for t, _ in self.log]
        self._snap_t = [t for t, _ in self.snaps]

    def rt(self, when: datetime | None) -> float | None:
        return None if when is None or self.start is None else (when - self.start).total_seconds()

    def lines(self, rt: float | None) -> list[str]:
        if rt is None or not self.log:
            return []
        i = bisect.bisect_left(self._log_t, rt - LOG_BEFORE_S)
        j = bisect.bisect_right(self._log_t, rt + LOG_AFTER_S)
        return [f"[{t:7.1f}] {s}" for t, s in self.log[i:j]]

    def player(self, rt: float | None) -> dict | None:
        """Last snapshot at or before rt (within 2 s)."""
        if rt is None or not self.snaps:
            return None
        i = bisect.bisect_right(self._snap_t, rt) - 1
        if i < 0 or rt - self._snap_t[i] > 2.0:
            return None
        return self.snaps[i][1]


def place(p: dict | None) -> str | None:
    if not p or p.get("x") is None:
        return None
    try:
        import places
        return places.where(p["x"], p["y"], p["z"])
    except Exception:
        return None


class Review:
    """{shot name: {comment, rt, place, pos, hp, at}} in <folder>/review.json, rewritten whole on every change."""

    def __init__(self, folder: Path):
        self.path = folder / REVIEW
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8")).get("comments", {})
        except (OSError, ValueError):
            self.data = {}

    def get(self, name: str) -> str:
        return (self.data.get(name) or {}).get("comment", "")

    def set(self, name: str, text: str, ctx: dict) -> None:
        text = text.strip()
        if text:
            self.data[name] = {"comment": text, **ctx, "at": datetime.now().isoformat(timespec="seconds")}
        else:
            self.data.pop(name, None)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"schema": "shot-review/0.1", "comments": dict(sorted(self.data.items()))},
                                  ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        tmp.replace(self.path)


def context(shot: Path, day: str, run: RunData) -> dict:
    rt = run.rt(shot_time(shot, day))
    p = run.player(rt)
    return {"rt": None if rt is None else round(rt, 1), "place": place(p),
            "pos": None if not p else [p.get("x"), p.get("y"), p.get("z")],
            "hp": None if not p else p.get("hp"), "run": run.name}


def folder_day(folder: Path) -> str:
    m = DIR_RE.search(folder.name)
    return m.group(1) if m else datetime.fromtimestamp(folder.stat().st_mtime).strftime("%Y%m%d")


# ── Window ──────────────────────────────────────────────────────────────────
class Viewer:
    SPEEDS = [2000, 1000, 500, 250, 100]       # ms per shot while playing

    def __init__(self, folder: Path, run: RunData):
        import tkinter as tk
        from PIL import Image, ImageTk
        self.tk, self.Image, self.ImageTk = tk, Image, ImageTk
        self.folder, self.run, self.day = folder, run, folder_day(folder)
        self.files = shots(folder)
        if not self.files:
            raise SystemExit(f"no screenshots (HHMMSS_mmm.jpg) in {folder}")
        self.review = Review(folder)
        self.i, self.playing, self.speed = 0, False, 1
        self._img = None

        r = self.root = tk.Tk()
        r.title(f"shot review — {folder.name}")
        r.geometry("1400x980")
        r.configure(bg="#111")
        self.head = tk.Label(r, anchor="w", justify="left", bg="#111", fg="#eee", font=("Malgun Gothic", 12, "bold"))
        self.head.pack(fill="x", padx=8, pady=(6, 2))
        self.canvas = tk.Canvas(r, bg="#000", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, padx=8)
        self.logbox = tk.Text(r, height=7, bg="#1b1b1b", fg="#ccc", font=("Consolas", 10), wrap="none", relief="flat")
        self.logbox.pack(fill="x", padx=8, pady=(4, 2))
        row = tk.Frame(r, bg="#111")
        row.pack(fill="x", padx=8, pady=(2, 2))
        tk.Label(row, text="코멘트", bg="#111", fg="#fc6", font=("Malgun Gothic", 11, "bold")).pack(side="left")
        self.entry = tk.Entry(row, font=("Malgun Gothic", 12), bg="#222", fg="#fff", insertbackground="#fff")
        self.entry.pack(side="left", fill="x", expand=True, padx=6)
        self.status = tk.Label(row, text="", bg="#111", fg="#8c8", font=("Malgun Gothic", 10))
        self.status.pack(side="left")
        self.scale = tk.Scale(r, from_=1, to=len(self.files), orient="horizontal", showvalue=False, bg="#111",
                              fg="#eee", troughcolor="#333", highlightthickness=0, command=self._on_scale)
        self.scale.pack(fill="x", padx=8, pady=(0, 2))
        tk.Label(r, text="→/Space 다음 · ← 이전 · PgDn/PgUp ±10 · Home/End · P 재생/멈춤 · [ ] 속도 · "
                         "C/Enter 코멘트 쓰기 (Enter 저장, 빈칸 = 지움, Esc 취소) · N/B 코멘트 단 장면으로",
                 bg="#111", fg="#888", font=("Malgun Gothic", 9)).pack(fill="x", padx=8, pady=(0, 6))

        for k, f in {"<Right>": lambda e: self.go(1), "<space>": lambda e: self.go(1), "d": lambda e: self.go(1),
                     "<Left>": lambda e: self.go(-1), "a": lambda e: self.go(-1),
                     "<Next>": lambda e: self.go(10), "<Prior>": lambda e: self.go(-10),
                     "<Home>": lambda e: self.show(0), "<End>": lambda e: self.show(len(self.files) - 1),
                     "p": lambda e: self.toggle_play(), "[": lambda e: self.faster(-1), "]": lambda e: self.faster(1),
                     "c": lambda e: self.edit(), "<Return>": lambda e: self.edit(),
                     "n": lambda e: self.jump_commented(1), "b": lambda e: self.jump_commented(-1)}.items():
            self.canvas.bind(k, f)
        # 한글 입력기: 조합 중인 마지막 글자는 Enter 직후에야 칸에 들어감 → 잠깐 뒤에 읽는다
        self.entry.bind("<Return>", lambda e: self.root.after(IME_WAIT_MS, self.save))
        self.entry.bind("<Escape>", lambda e: self.leave())
        self.entry.bind("<KeyRelease>", lambda e: self.mark())
        self.entry.bind("<FocusOut>", lambda e: self.root.after(IME_WAIT_MS, self.flush))
        self.canvas.bind("<Button-1>", lambda e: self.canvas.focus_set())
        self.canvas.bind("<Configure>", lambda e: self.draw())
        self.canvas.focus_set()
        self.show(0)

    def run_loop(self) -> None:
        self.root.mainloop()

    # navigation
    def go(self, d: int) -> None:
        self.show(max(0, min(len(self.files) - 1, self.i + d)))

    def _on_scale(self, v) -> None:
        if int(float(v)) - 1 != self.i:
            self.show(int(float(v)) - 1)

    def jump_commented(self, d: int) -> None:
        names = [f.name for f in self.files]
        idx = [k for k, n in enumerate(names) if n in self.review.data]
        nxt = [k for k in idx if (k > self.i if d > 0 else k < self.i)]
        if nxt:
            self.show(nxt[0] if d > 0 else nxt[-1])
        else:
            self.status.config(text="코멘트 단 장면 없음 (이 방향)", fg="#c88")

    def toggle_play(self) -> None:
        self.playing = not self.playing
        if self.playing:
            self._tick()
        self.header()

    def faster(self, d: int) -> None:
        self.speed = max(0, min(len(self.SPEEDS) - 1, self.speed + d))
        self.header()

    def _tick(self) -> None:
        if not self.playing:
            return
        if self.i >= len(self.files) - 1:
            self.playing = False
            self.header()
            return
        self.go(1)
        self.root.after(self.SPEEDS[self.speed], self._tick)

    # comment
    def edit(self) -> None:
        self.playing = False
        self.entry.focus_set()
        self.entry.icursor("end")

    def save(self, leave: bool = True) -> None:
        f = self.files[self.i]
        text = self.entry.get()
        self.review.set(f.name, text, context(f, self.day, self.run))
        self.status.config(text=("저장됨" if text.strip() else "지움") + f" ({len(self.review.data)}개)", fg="#8c8")
        if leave:
            self.leave(keep=True)
        self.header()

    def unsaved(self) -> bool:
        return self.entry.get().strip() != self.review.get(self.files[self.i].name)

    def flush(self) -> None:
        """Typed but not saved (moved on, clicked the picture): keep it — only Enter on an empty box deletes."""
        if self.unsaved() and self.entry.get().strip():
            self.save(leave=False)

    def mark(self) -> None:
        if self.unsaved():
            self.status.config(text="저장 안 됨 — Enter", fg="#fa6")

    def leave(self, keep: bool = False) -> None:
        if not keep:
            self.entry.delete(0, "end")
            self.entry.insert(0, self.review.get(self.files[self.i].name))
        self.canvas.focus_set()

    # drawing
    def show(self, i: int) -> None:
        if getattr(self, "_ctx", None) is not None and i != self.i:
            self.flush()
        self.i = i
        if int(self.scale.get()) != i + 1:
            self.scale.set(i + 1)
        f = self.files[i]
        self._pil = self.Image.open(f)
        self.entry.delete(0, "end")
        self.entry.insert(0, self.review.get(f.name))
        self.status.config(text="")
        ctx = context(f, self.day, self.run)
        self.logbox.config(state="normal")
        self.logbox.delete("1.0", "end")
        self.logbox.insert("end", "\n".join(self.run.lines(ctx["rt"])) or "(이 시점 로그 없음)")
        self.logbox.config(state="disabled")
        self._ctx = ctx
        self.header()
        self.draw()

    def header(self) -> None:
        f, c = self.files[self.i], self._ctx
        t = shot_time(f, self.day)
        parts = [f"{self.i + 1}/{len(self.files)}", f.name, t.strftime("%H:%M:%S") if t else ""]
        if c["rt"] is not None:
            parts.append(f"실행 {c['rt']:.1f} s")
        if c["place"]:
            parts.append(c["place"])
        if c["hp"] is not None:
            parts.append(f"HP {c['hp']}")
        if self.review.get(f.name):
            parts.append("● 코멘트 있음")
        if self.playing:
            parts.append(f"▶ {1000 / self.SPEEDS[self.speed]:.1f}장/s")
        self.head.config(text="  ·  ".join(p for p in parts if p))

    def draw(self) -> None:
        w, h = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        im = self._pil
        k = min(w / im.width, h / im.height)
        im = im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))), self.Image.BILINEAR)
        self._img = self.ImageTk.PhotoImage(im)
        self.canvas.delete("all")
        self.canvas.create_image(w // 2, h // 2, image=self._img)


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return
    folder = Path(args[0])
    if not folder.is_dir():
        raise SystemExit(f"not a folder: {folder}")
    if "--run" in args:
        name = args[args.index("--run") + 1]
        settings = RUNS / (Path(name).name.removesuffix(".settings.json") + ".settings.json")
    else:
        settings = find_run(folder)
    run = RunData(settings if settings and settings.exists() else None)
    if "--list" in args:
        rv = Review(folder)
        for name, c in rv.data.items():
            rt = f"{c['rt']:7.1f} s" if c.get("rt") is not None else "      ?"
            print(f"{name}  {rt}  {c.get('place') or '-'}  HP {c.get('hp')}  — {c['comment']}")
        print(f"{len(rv.data)} comments · {folder / REVIEW}")
        return
    print(f"run: {run.name or '없음 (로그·위치 없이 봄)'} · {len(shots(folder))} shots · comments → {folder / REVIEW}")
    Viewer(folder, run).run_loop()


if __name__ == "__main__":
    main()
