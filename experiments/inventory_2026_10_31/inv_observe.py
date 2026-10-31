"""data/observe/*.jsonl list: size, length, world/pad/marker lines, pad lines per slot (i), hdr radius_m. Read only. python inv_observe.py <repo> <out>"""
import collections, json, math, re, sys
from pathlib import Path
repo, out = Path(sys.argv[1]), Path(sys.argv[2])
MS = re.compile(rb'"ms":(-?[0-9.]+)')
spots = json.loads((repo / "data/spots.json").read_text(encoding="utf-8"))
pts = [(n, v.get("map"), v[k]) for n, v in spots.items() for k in ("pos", "stand", "object") if isinstance(v.get(k), list)]
rows = []
for f in sorted((repo / "data/observe").glob("*.jsonl")):
    r = {"file": f"data/observe/{f.name}", "bytes": f.stat().st_size}
    try:
        k = collections.Counter(); slots = collections.Counter(); lo = hi = None; hdr = end = first_p = None; broken = 0
        with open(f, "rb") as fh:
            for line in fh:
                m = MS.search(line)
                if m:
                    v = float(m.group(1)); lo = v if lo is None else min(lo, v); hi = v if hi is None else max(hi, v)
                if line.startswith(b'{"k":"w"'):
                    k["w"] += 1
                    if first_p is None:
                        try: first_p = json.loads(line)["p"]["pos"]
                        except Exception: broken += 1
                elif line.startswith(b'{"k":"pad"'):
                    k["pad"] += 1
                    try: slots[json.loads(line).get("i")] += 1
                    except Exception: broken += 1
                elif line.startswith(b'{"k":"mk"'):
                    k["mk"] += 1
                elif line.startswith(b'{"k":"hdr"'):
                    hdr = json.loads(line)
                elif b'"ev":"end"' in line:
                    try: end = json.loads(line)
                    except Exception: broken += 1
                else:
                    try: k[json.loads(line).get("k")] += 1
                    except Exception: broken += 1
        sl = {str(s): n for s, n in slots.items()}
        kind = ("human (slot 0)" if set(slots) == {0} else "bot (slot 1)" if set(slots) == {1}
                else "mixed" if len(slots) > 1 else "no pad lines" if not slots else f"slot {list(slots)[0]}")
        near = None
        if first_p:
            n, mp, p = min(pts, key=lambda t: math.dist(t[2], first_p))
            d = math.dist(p, first_p)
            near = {"spot": n, "spot_map": mp, "dist_m": round(d, 1)} if d <= 20 else None
        r.update(length_s=(round((hi - lo) / 1000, 1) if lo is not None else None),
                 end_duration_s=(end or {}).get("duration_s"), end_reason=(end or {}).get("reason"),
                 world_lines=k["w"], pad_lines=k["pad"], pad_lines_by_slot=sl, markers_f9=k["mk"],
                 hdr_radius_m=(hdr or {}).get("radius_m"), hdr_present=hdr is not None, play_kind=kind,
                 first_player_pos=first_p, zone_hint=near, broken_or_unparsed=broken)
    except Exception as e:
        r["read_error"] = repr(e)[:200]
    rows.append(r)
    print(f.name, r.get("length_s"), r.get("play_kind"), r.get("markers_f9"))
tot = collections.defaultdict(lambda: {"files": 0, "length_s": 0.0, "markers": 0})
for r in rows:
    t = tot[r.get("play_kind", "read_error")]; t["files"] += 1; t["length_s"] = round(t["length_s"] + (r.get("length_s") or 0), 1); t["markers"] += r.get("markers_f9") or 0
(out / "observe_list.json").write_text(json.dumps({
    "scope": "data/observe/*.jsonl (observe_record.py recordings)",
    "method": "length_s = max(ms) - min(ms) over all lines; play_kind from pad line slot i (0 = human pad, 1 = bot virtual pad per request); "
              "zone_hint = nearest data/spots.json point within 20 m of the first world line's player pos (coordinates only — the recording has no map id), else null; "
              "no melee / combat time is computed (needs a definition)",
    "totals_by_kind": tot, "files": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
