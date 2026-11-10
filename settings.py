"""Run settings object (ROADMAP `settings-object`, docs/review-v2-2026-10-11.md §2-③) — step 1.

One object holds what a run changes from the module defaults. run.py builds it from the command line (`from_args`), applies
it in one place (`apply`), and runinfo saves it (`to_dict`) next to the full constants table. Before this, run.py set
`duel.BACKSTAB`, `field.NOTICE_PULL`, `levelup.WANT` … in separate blocks, and `levelup` / `kindle` were not in the record.

Step 1 does not change how the bot reads settings: the modules still read their own UPPER_CASE globals, `apply` writes
the overrides there. Later steps pass the object in instead (plan:settings-object). Behaviour must stay the same: the
constants after `apply` are the ones the old blocks produced (tests/settings_test.py).

  python settings.py --basic --pull            print the overrides those flags make
"""
from __future__ import annotations

import importlib
import sys
from contextlib import contextmanager

# run.py flag → (module, {CONSTANT: value}). A value that is a callable gets the parsed args (e.g. --drill's choice).
# Only flags that change a module constant; flags passed as arguments (--no-lure, --style …) stay in `args`.
FLAGS: dict[str, list[tuple[str, dict]]] = {
    "basic": [("souls.duel", {"BACKSTAB": False, "HEAVY": False})],          # [MoKa] 2026-10-01 방패 + 약공만
    "pull": [("souls.field", {"NOTICE_PULL": True})],                       # [MoKa] 2026-10-11 몸으로 끌기
    "footing": [("souls.duel", {"FOOTING": True})],                         # P-58 · P-49
    "combo_only": [("souls.duel", {"COMBO_ONLY": True})],                   # P-121
    "drill": [("souls.duel", {"COMBO_ONLY": True, "DRILL": lambda a: a.drill})],
    "level_up": [("levelup", {"WANT": lambda a: a.level_up.upper()})],
    "kindle": [("kindle", {"ON": True})],
}
# modules the flags above touch, outside runinfo.SETTINGS_MODULES before step 1 (their constants were not recorded)
EXTRA_MODULES = ("levelup", "kindle")

_MISSING = object()


def _mod(name: str):
    return sys.modules.get(name) or importlib.import_module(name)


class Settings:
    """{module: {NAME: value}} that differ from the module defaults for this run."""

    def __init__(self, overrides: dict | None = None):
        self.overrides: dict[str, dict] = {m: dict(v) for m, v in (overrides or {}).items()}
        self._saved: list[tuple[object, str, object]] = []

    @classmethod
    def from_args(cls, a) -> "Settings":
        """The overrides the run.py flags in `a` (argparse Namespace or anything with those attributes) make."""
        out: dict[str, dict] = {}
        for flag, parts in FLAGS.items():
            if not getattr(a, flag, None):
                continue
            for module, consts in parts:
                for k, v in consts.items():
                    out.setdefault(module, {})[k] = v(a) if callable(v) else v
        return cls(out)

    def set(self, module: str, name: str, value) -> "Settings":
        self.overrides.setdefault(module, {})[name] = value
        return self

    def apply(self) -> "Settings":
        """Write the overrides into the modules (remembering the old values for restore()). A name the module does not
        have is an error — a typo would otherwise create a new global nobody reads."""
        for module, consts in self.overrides.items():
            mod = _mod(module)
            for k, v in consts.items():
                if not hasattr(mod, k):
                    raise AttributeError(f"{module} has no setting {k}")
                self._saved.append((mod, k, getattr(mod, k)))
                setattr(mod, k, v)
        return self

    def restore(self) -> None:
        while self._saved:
            mod, k, old = self._saved.pop()
            setattr(mod, k, old)

    @contextmanager
    def applied(self):
        """with Settings(...).applied(): … — for tests and A/B code that must not leak globals."""
        self.apply()
        try:
            yield self
        finally:
            self.restore()

    def to_dict(self) -> dict:
        return {m: dict(sorted(v.items())) for m, v in sorted(self.overrides.items()) if v}

    def __repr__(self) -> str:
        return f"Settings({self.to_dict()})"


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    for f in FLAGS:
        if f in ("drill", "level_up"):
            ap.add_argument("--" + f.replace("_", "-"), default=None)
        else:
            ap.add_argument("--" + f.replace("_", "-"), action="store_true")
    print(Settings.from_args(ap.parse_args()).to_dict())
