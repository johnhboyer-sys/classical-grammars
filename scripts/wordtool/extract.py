#!/usr/bin/env python3
"""Extract dictionary entries from the wordtool packs by folded key."""
import gzip, json, sys, unicodedata, re
import os
_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

# The packs this repo builds. The site's design tools import this module
# too and read the same files; the builder repoints PACKDIR at its own
# --out while it is writing.
PACKDIR = os.path.join(_REPO, "data", "wordtool")
if not os.path.exists(os.path.join(PACKDIR, "grc-lsj.idx.json")):
    PACKDIR = os.path.expanduser("~/Developer/grammars/data/wordtool")

GREEK_BASE = {
    'α':'a','β':'b','γ':'g','δ':'d','ε':'e','ζ':'z','η':'h','θ':'q',
    'ι':'i','κ':'k','λ':'l','μ':'m','ν':'n','ξ':'c','ο':'o','π':'p',
    'ρ':'r','σ':'s','ς':'s','τ':'t','υ':'u','φ':'f','χ':'x','ψ':'y',
    'ω':'w','ϝ':'v',
}

def fold_greek(q):
    out = []
    for ch in unicodedata.normalize('NFD', q).lower():
        if ch in GREEK_BASE: out.append(GREEK_BASE[ch])
        elif 'a' <= ch <= 'z': out.append(ch)
    return ''.join(out)

def fold_latin(q):
    s = unicodedata.normalize('NFD', q).lower().replace('j','i').replace('v','u')
    return re.sub(r'[^a-z]', '', s)

def bucket_name(folded):
    return folded[:2] if len(folded) >= 2 else (folded or '_')

def load_bucket(dataset, bucket):
    idx = json.load(open(f"{PACKDIR}/{dataset}.idx.json"))
    span = idx['buckets'].get(bucket)
    if not span: return None
    off, length = span
    with open(f"{PACKDIR}/{dataset}.pack", 'rb') as f:
        f.seek(off)
        blob = f.read(length)
    return json.loads(gzip.decompress(blob))

def get(dataset, word):
    fold = fold_greek if dataset.startswith('grc') else fold_latin
    folded = fold(word)
    b = load_bucket(dataset, bucket_name(folded))
    if not b: return []
    return b.get(folded, [])

if __name__ == '__main__':
    dataset, word = sys.argv[1], sys.argv[2]
    for e in get(dataset, word):
        if 'html' not in e:
            print(json.dumps(e, ensure_ascii=False, indent=2))
        else:
            print(f"=== key={e['key']} head={e['head']} len={len(e['html'])}")
            if '--full' in sys.argv:
                print(e['html'])
            else:
                print(e['html'][:600])
        print()
