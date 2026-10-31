import json, math, collections, sys, hashlib
cfg = json.load(open('config.json'))
X = [json.loads(l) for l in open('/tmp/inv3/data/inventory/2026-10-31/g2_scene_extract.jsonl')]
X = [x for x in X if x['split'] not in cfg['exclude_splits']]
HOST = {6, 7, 24, 25, 27, 33}
def anim_cat(a):
    if a is None or a == -1: return 'idle'
    if 3000 <= a < 3500: return 'attack'
    if 3500 <= a < 3600: return 'stagger'
    if 2000 <= a < 2100: return 'hit_stun'
    if 9900 <= a < 10000: return 'downed'
    if a == 9600: return 'guard_broken'
    if 9000 <= a < 9100: return 'dormant'
    if a in (1500, 1550, 121500): return 'falling'
    return 'other'
E_ = cfg['distance_bins_m']['edges']; LBL = cfg['distance_bins_m']['labels']
def dist_bin(h):
    for e, l in zip(E_, LBL):
        if h < e: return l
    return LBL[-1]
def near_bin(x):
    p = x['snap']['player']; n = 0
    for c in x['snap']['chars']:
        if c['team'] in HOST and (c['hp'] or 0) > 0 and math.hypot(c['x'] - p['x'], c['z'] - p['z']) < 4.0: n += 1
    return str(n) if n < 3 else '3+'
for x in X: x['_k'] = (anim_cat(x['tick']['a']), dist_bin(x['tick']['h']), near_bin(x))

def fit(train):
    freq = collections.Counter(x['rule'] for x in train)
    maj = sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    def best(cnt):
        return sorted(cnt.items(), key=lambda kv: (-kv[1], -freq[kv[0]], kv[0]))[0][0]
    tables = []
    for depth in (3, 2, 1):
        t = collections.defaultdict(collections.Counter)
        for x in train: t[x['_k'][:depth]][x['rule']] += 1
        tables.append({k: best(v) for k, v in t.items() if sum(v.values()) >= cfg['lookup']['min_train_count']})
    return maj, tables, freq
def predict_lookup(x, tables, maj):
    for lvl, (depth, t) in enumerate(zip((3, 2, 1), tables)):
        k = x['_k'][:depth]
        if k in t: return t[k], lvl
    return maj, 3

def metrics(rows, preds):
    y = [r['rule'] for r in rows]; classes = sorted(set(y) | set(preds))
    runs_of = collections.defaultdict(set)
    for r in rows: runs_of[r['rule']].add(r['run'])
    per = {}
    for c in classes:
        tp = sum(1 for a, b in zip(y, preds) if a == c and b == c); fp = sum(1 for a, b in zip(y, preds) if a != c and b == c); fn = sum(1 for a, b in zip(y, preds) if a == c and b != c)
        P = tp / (tp + fp) if tp + fp else 0.0; R = tp / (tp + fn) if tp + fn else 0.0; F = 2 * P * R / (P + R) if P + R else 0.0
        per[c] = dict(n=tp + fn, runs=len(runs_of[c]), pred_n=tp + fp, P=round(P, 3), R=round(R, 3), F1=round(F, 3))
    prim = [c for c in per if per[c]['n'] >= 10 and per[c]['runs'] >= 3]
    sec = [c for c in per if per[c]['n'] >= 1]
    mf = lambda cs: round(sum(per[c]['F1'] for c in cs) / len(cs), 3) if cs else None
    cm = collections.Counter(zip(y, preds))
    byrun = collections.defaultdict(lambda: [0, 0])
    for r, p in zip(rows, preds): byrun[r['run']][0] += 1; byrun[r['run']][1] += (r['rule'] == p)
    return dict(n=len(rows), runs=len({r['run'] for r in rows}), acc=round(sum(a == b for a, b in zip(y, preds)) / len(rows), 3) if rows else None,
                macro_f1_primary=mf(prim), primary_classes=sorted(prim), macro_f1_all_true=mf(sec), n_true_classes=len(sec), per_class=per,
                confusion={f"{a}->{b}": n for (a, b), n in sorted(cm.items(), key=lambda kv: -kv[1])},
                per_run={k: dict(n=v[0], acc=round(v[1] / v[0], 3)) for k, v in sorted(byrun.items())})

out = {'config_sha256': hashlib.sha256(open('config.json', 'rb').read()).hexdigest(), 'variants': {}}
evsets = {s: [x for x in X if x['split'] == s] for s in cfg['eval_splits']}
drop = cfg['eval_variants']['shift_ref_no_dirty_duel']['drop']
evsets['shift_ref_no_dirty_duel'] = [x for x in evsets['shift_ref'] if x['run'] not in drop]
for vn, v in cfg['variants'].items():
    train = [x for x in X if x['split'] == 'train' and x['run'] not in v['train_drop']]
    maj, tables, freq = fit(train)
    res = {'train_n': len(train), 'train_runs': len({x['run'] for x in train}), 'majority_rule': maj,
           'train_rule_freq': dict(freq.most_common()), 'table_cells': {d: len(t) for d, t in zip(('full', 'anim+dist', 'anim'), tables)},
           'table_full': {'|'.join(k): r for k, r in sorted(tables[0].items())}, 'eval': {}}
    for en, rows in evsets.items():
        pm = [maj] * len(rows)
        pl, lv = zip(*[predict_lookup(x, tables, maj) for x in rows]) if rows else ([], [])
        fb = collections.Counter(lv)
        res['eval'][en] = {'majority': metrics(rows, pm), 'lookup': metrics(rows, list(pl)),
                           'lookup_fallback': {['full_cell', 'anim+dist', 'anim', 'majority'][k]: dict(n=v, share=round(v / len(rows), 3)) for k, v in sorted(fb.items())}}
    out['variants'][vn] = res
json.dump(out, open('results.json', 'w'), ensure_ascii=False, indent=1)
print('ok')
