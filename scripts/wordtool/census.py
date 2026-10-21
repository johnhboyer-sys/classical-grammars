#!/usr/bin/env python3
"""Defect census of the T8 packs: every row, classed by what is wrong with it.

The pack diff says what changed and the prose gate what went missing;
neither says what is still wrong. This reads every sense line in both
T8 packs and counts the shapes a reader would notice — a gloss that
ends on its governor ("Dim. of"), a separator or bracket left by a
stripped citation, a locus with no author, an "Id." chip nothing
resolved — with a few examples of each, so a round can start from the
largest class and be measured after.

Every class is a heuristic and some hits are the print's own wording
(a gloss can end on "with"; a row can open on "also"). The counts are
for ranking and for before/after comparison, not a gate.

Usage:
    python3 scripts/wordtool/census.py [grc-lsj-t8|lat-ls-t8] [--examples N]
"""
from __future__ import annotations

import collections
import html as H
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import extract  # noqa: E402

TAG = re.compile(r'<[^>]+>')


def text(s):
    return H.unescape(TAG.sub('', s or ''))


# The print's own wording, not damage. LSJ and L&S write senses that
# continue the one above ("also of the mind, perception", "as Subst.
# περίαπτον, τό", "hence, ward, quarter of a town") and glosses that end
# on the preposition the Greek verb governs ("fall in with", "make an
# example of"). Both shapes were counted as defects in the first census
# and both were read and found to be the print. They are reported apart
# so a round is not started on 3,000 rows that are already right.
STYLE = frozenset((
    'opens on a connective',
    'ends on a governor or connective',
    'under three characters',
))


# LSJ writes its ellipsis with two dots and the print's own spacing
# ("ὁ μέν.., ὁ δέ..", "Εἰλείθυιαι . . ὠδῖνας"). Both dots are the
# witness's, so a row is not spaced wrongly for holding one. The mark is
# folded to a single character before the spacing tests read the line.
ELLIPSIS = re.compile(r'\.\s*\.(?:\s*\.)*')


def classes(z):
    s = text(z).strip()
    if not s:
        return ['empty']
    out = []
    plain = ELLIPSIS.sub('…', s)
    if plain.startswith('…'):
        # The tail of a quotation that moved to the drawer, left at the
        # head of the sense line (μέν: the print's "μέν . . , δέ . . ").
        out.append('opens on the print\'s ellipsis')
    elif re.match(r'^[,;:.)\]]', s):
        out.append('opens on a separator or bracket')
    if re.search(r'[,;:(\[]$', s):
        out.append('ends on a separator or bracket')
    if re.search(r'\b(?:or|and|hence|as|of|with|the|a|an|opp\.?|esp\.?|i\.\s*e\.?|e\.\s*g\.?|cf\.?)$', s):
        out.append('ends on a governor or connective')
    if re.match(r'^(?:or|and|hence|also|but|as|so|opp\.|i\.e\.|e\.g\.)\b', s):
        out.append('opens on a connective')
    if re.search(r',,| ,|;;| ;| \.', plain):
        out.append('separator spacing')
    if s.count('(') != s.count(')'):
        out.append('unbalanced parentheses')
    if re.search(r'\(\s*\)|\[\s*\]', s):
        out.append('empty brackets')
    if re.search(r'(?<![A-Za-z.])\d+\s*\.\s*\d+', s) and not re.search(r'[A-Z][a-z]*\.\s*\d', s):
        out.append('locus with no author')
    if re.search(r'\bId\.', s):
        out.append('"Id." in the gloss')
    if len(s) < 3:
        out.append('under three characters')
    if not re.search(r'[A-Za-zͰ-Ͽἀ-῿]', s):
        out.append('no letters')
    if re.search(r'<(?!/?(?:b|span)\b)', z or ''):
        out.append('markup outside the closed vocabulary')
    return out


def census(dataset, examples):
    idx = json.load(open(os.path.join(extract.PACKDIR, f'{dataset}.idx.json')))
    count = collections.Counter()
    sample = collections.defaultdict(list)
    entries = rows = 0

    def hit(cls, head, what):
        count[cls] += 1
        if len(sample[cls]) < examples:
            sample[cls].append((head, what[:90]))

    for bucket in sorted(idx['buckets']):
        for _key, docs in (extract.load_bucket(dataset, bucket) or {}).items():
            for d in docs:
                entries += 1
                head = d.get('head', '')
                for r in d.get('rows') or []:
                    rows += 1
                    for cls in classes(r.get('z', '')):
                        hit(cls, head, text(r.get('z', '')))
                    for a in r.get('au') or []:
                        if re.match(r'(?:id|ib|ibid)\.?$', a, re.I):
                            hit('chip reads "Id." or "ib."', head, a)
                for field in ('i', 'p', 'gl'):
                    v = d.get(field)
                    if v and re.search(r'[,;:(]\s*$', text(v)):
                        hit(f'{field} ends on a separator or bracket', head, text(v))
                # The build gate's own test: an entry that shows the
                # reader nothing at all. Some sources stop after the
                # headword and its gender (ἐξάρθρωμα, abstractus), and
                # those still render an identity line.
                if not any(d.get(f) for f in ('rows', 'p', 'au', 'gl', 'i', 'f', 'g')):
                    hit('entry renders nothing', head, '')
    print(f'=== {dataset}: {entries} entries, {rows} rows')
    for label, wanted in (('defects', False), ("the print's own shapes", True)):
        chosen = [(c, n) for c, n in count.most_common() if (c in STYLE) is wanted]
        print(f'  -- {label}: {sum(n for _c, n in chosen)}')
        for cls, n in chosen:
            print(f'{n:7d}  {cls}')
            for head, what in sample[cls]:
                print(f'           {head}: {what}')


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    examples = 3
    if '--examples' in sys.argv:
        examples = int(sys.argv[sys.argv.index('--examples') + 1])
        args = [a for a in args if a != str(examples)]
    for ds in args or ('grc-lsj-t8', 'lat-ls-t8'):
        census(ds, examples)


if __name__ == '__main__':
    main()
