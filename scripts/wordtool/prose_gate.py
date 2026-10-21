#!/usr/bin/env python3
"""English wording present in the baseline packs must still be present.

The pack diff (diff_packs.py) reports that a gloss was reworded; this
says whether any of its WORDS went missing. A rule that trims citation
debris off the end of a gloss and a rule that eats the gloss look the
same to a "reworded" count, and the second one shipped once (the
abbreviation-period rule took "for the soil is on fire in different
places" out of L&S ardeo) before this existed.

For every entry, the set of 3-word runs of plain English in the reader-
visible text (z, i, p, gl, ex.e, f, gr) of the baseline against the
working tree. A run that disappears is reported unless it is citation
apparatus (a link abbreviation or a locus). Usage:
    python3 scripts/wordtool/prose_gate.py [REF] [dataset ...]

Exit 1 on any loss; every entry it names wants reading, and the
explanation belongs in the commit.
"""
import sys, re, html as H, collections
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import diff_packs as D
TAG = re.compile(r'<[^>]+>')
ref = sys.argv[1] if len(sys.argv) > 1 else 'HEAD'
names = sys.argv[2:] or D.DATASETS
APP = re.compile(r'\b(?:cf|ap|al|ib|ibid|sq|sqq|etc|v|vv|s|l|c|ll|cc|q|p|pp|fr|id|eund|sch)\b', re.I)
def runs(rec):
    parts = [rec.get('i'), rec.get('p'), rec.get('gl')]
    for r in rec.get('rows') or []:
        parts.append(r.get('z'))
        for e in r.get('ex') or []:
            parts.append(e.get('e'))
    for lab, body in (rec.get('f') or []) + (rec.get('gr') or []):
        parts.append(body)
    out = set()
    for p in parts:
        text = H.unescape(TAG.sub(' ', p or ''))
        # Runs inside one field only, of plain lowercase English words —
        # an abbreviation, a capital or a digit is apparatus, not prose.
        for m in re.finditer(r"(?:\b[a-z][a-z'’-]+(?![.\w]) ){2,}[a-z][a-z'’-]+(?![.\w])", text):
            words = m.group(0).split()
            for i in range(len(words) - 2):
                out.add(' '.join(words[i:i+3]))
    return out
bad = 0
for name in names:
    old = D.load(None, name, ref); new = D.load(D.DATA, name, None)
    lost = collections.Counter(); ex = []
    gained = 0
    for key in sorted(set(old) & set(new)):
        a, b = runs(old[key]), runs(new[key])
        gone = a - b
        gained += len(b - a)
        if gone:
            lost[old[key].get('head') or key[0]] += len(gone)
            if len(ex) < 40:
                ex.append((old[key].get('head') or key[0], sorted(gone)[:3]))
    print(f'=== {name}: entries losing an English run: {len(lost)}  (runs gained across entries: {gained})')
    for h, g in ex:
        print(f'  {h}\t{g}')
    bad += len(lost)
sys.exit(1 if bad else 0)
