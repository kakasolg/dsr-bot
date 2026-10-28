"""Condense a TLC error trace: per step, the action that fired and only the fields that changed.

    python docs/formal/pad_freeze/trace.py out/<name>.log
"""
import re
import sys


def fields(v: str) -> dict:
    """'[a |-> 1, b |-> [x |-> 2]]' → {'a': '1', 'b': '[x |-> 2]'} (top level only); anything else → {'': v}."""
    v = v.strip()
    if not (v.startswith("[") and "|->" in v):
        return {"": v}
    out, depth, cur = {}, 0, ""
    for ch in v[1:-1] + ",":
        if ch in "[{(":
            depth += 1
        elif ch in "]})":
            depth -= 1
        if ch == "," and depth == 0:
            k, _, val = cur.partition("|->")
            out[k.strip()] = " ".join(val.split())
            cur = ""
        else:
            cur += ch
    return out


with open(sys.argv[1], encoding="utf-8", errors="replace") as f:
    txt = f.read().split("The behavior up to this point is:")[-1]
steps, cur = [], None
for line in txt.splitlines():
    m = re.match(r"State (\d+): <(\w+)", line)
    if m:
        cur = [m.group(1), m.group(2), {}]
        steps.append(cur)
    elif cur and line.startswith("/\\ ") and " = " in line:
        k, v = line[3:].split(" = ", 1)
        cur[2][k] = v
    elif cur and line.startswith(" ") and cur[2]:
        k = list(cur[2])[-1]
        cur[2][k] += " " + line.strip()
prev: dict = {}
for n, act, st in steps:
    flat = {(var + "." + k if k else var): v for var, val in st.items() for k, v in fields(val).items()}
    ch = {k: v for k, v in flat.items() if prev.get(k) != v and (n != "1" or k.startswith("pc"))}
    print(f"{n:>2} {act:<12} " + "; ".join(f"{k}={v}" for k, v in ch.items()))
    prev = flat
