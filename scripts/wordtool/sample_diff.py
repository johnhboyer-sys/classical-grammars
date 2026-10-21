#!/usr/bin/env python3
"""Fast pre-build check: HEAD's transform against the working tree's.

A rebuild is six minutes and the pack diff comes after it. This runs
both versions of t8rows in one process over a random sample of entries
and prints every reader-visible field that differs, so a rule can be
read against real entries before it costs a build. Every regression
the polish round's second commit shipped in a build had been visible
here in seconds.

Usage:
    python3 scripts/wordtool/sample_diff.py [N] [grc-lsj|lat-ls] [seed]
"""
import sys, re, json, random, importlib.util, html as H
import os, subprocess, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
S = tempfile.mkdtemp()
head = subprocess.run(['git', 'show', 'HEAD:scripts/wordtool/t8rows.py'], capture_output=True, text=True, cwd=HERE).stdout
open(S + '/t8rows_head.py', 'w').write(head)
import t8rows as new, extract
spec = importlib.util.spec_from_file_location('t8rows_head', S + '/t8rows_head.py'); old = importlib.util.module_from_spec(spec); spec.loader.exec_module(old)
TAG = re.compile(r'<[^>]+>'); t = lambda s: H.unescape(TAG.sub('', s or ''))
n = int(sys.argv[1]) if len(sys.argv) > 1 else 300
ds = sys.argv[2] if len(sys.argv) > 2 else 'grc-lsj'
if ds.startswith('lat'):
    for m in (old, new): m.configure('lat-ls', 'lat-analyses', 'la')
idx = json.load(open(f'{extract.PACKDIR}/{ds}.idx.json'))
random.seed(int(sys.argv[3]) if len(sys.argv) > 3 else 7)
buckets = random.sample(sorted(idx['buckets']), min(40, len(idx['buckets'])))
keys = []
for b in buckets:
    for k, recs in extract.load_bucket(ds, b).items():
        keys.append((k, recs))
random.shuffle(keys); keys = keys[:n]
def flat(doc):
    # Text AND markup. Stripping the tags hid a whole class of change:
    # the headword marks (<b class="hw">) that say which word of a
    # quotation is the entry's own, and the language spans. A round that
    # moved 495 marks off their punctuation and added 1,186 more was
    # reported here as zero differences on both packs.
    out = {'i': t(doc.get('i')), 'p': t(doc.get('p')), 'gl': t(doc.get('gl')), 'f': json.dumps(doc.get('f'), ensure_ascii=False), 'gr': json.dumps(doc.get('gr'), ensure_ascii=False), 'au': json.dumps(doc.get('au'))}
    for i, r in enumerate(doc.get('rows') or []):
        out[f'z{i}'] = t(r.get('z')); out[f'au{i}'] = json.dumps(r.get('au'))
        out[f'z{i} markup'] = r.get('z') or ''
        for j, e in enumerate(r.get('ex') or []):
            out[f'ex{i}.{j}'] = f"{t(e.get('g'))} | {t(e.get('e'))} | {e.get('c')}"
            out[f'ex{i}.{j} markup'] = e.get('g') or ''
    return out
diffs = 0
for k, recs in keys:
    for rec in recs:
        try:
            a = flat(old.to_doc(old.model(k, rec), k)); b = flat(new.to_doc(new.model(k, rec), k))
        except Exception as e:
            print('ERR', rec.get('head'), e); continue
        for f in sorted(set(a) | set(b)):
            if a.get(f) != b.get(f):
                diffs += 1
                print(f"{rec.get('head')}\t{f}\n   - {a.get(f, '')[:140]}\n   + {b.get(f, '')[:140]}")
print(f'--- {len(keys)} keys, {diffs} field differences')
