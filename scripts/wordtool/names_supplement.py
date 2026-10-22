#!/usr/bin/env python3
"""Proper-name supplement for the Greek T8 packs.

LSJ has no entry for many names (Πυλάδης, Αἴγισθος, Εὐρυσθεύς), so T8
printed "Entry not found in the vendored lexicon" for them even though the
form index knows the word. This step adds a short entry per name
(data/names/names.jsonl) to grc-lsj-t8 and attaches its key to the
grc-analyses rows of that lemma, so both lookup paths find it with no
change to lookup.js: a form lookup reads the row's dictionary key; a word
the form index lacks falls through to the exact T8 headword.

Idempotent: earlier supplement docs and keys are removed before adding.
Runs at the end of the Greek build (build_wordtool.main) and standalone on
the committed packs:

  python3 scripts/wordtool/names_supplement.py [--out data/wordtool]

Sources (data/names/README.md): Smith's Dictionary of Greek and Roman
Biography and Mythology (1849) and Dictionary of Greek and Roman Geography
(1854), Perseus TEI, CC BY-SA 4.0; entries marked "own" are written here.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_wordtool import (  # noqa: E402
    DEFAULT_OUT, LICENSE, beta_fold, beta_to_unicode, bucket_name, homonym_split, write_pack,
)

NAMES = Path(__file__).resolve().parents[2] / "data" / "names" / "names.jsonl"
SRC = "names"  # marks a supplement doc in grc-lsj-t8

# A short credit after the entry (the row's citation chips); the full
# Perseus licence notice is in data/names/README.md and the manifest.
CREDIT = {
    "smith-bio": "Smith, Biography and Mythology (1849)",
    "smith-geo": "Smith, Geography (1854)",
    "own": "",
}


def load(path: Path = NAMES) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    keys = [r["key"] for r in rows]
    dup = {k for k in keys if keys.count(k) > 1}
    if dup:
        raise ValueError(f"duplicate supplement keys: {sorted(dup)[:10]}")
    return rows


def display(key: str) -> str:
    """The lemma as grc-analyses shows it (finalize_analyses)."""
    bare, hom = homonym_split(key)
    disp = beta_to_unicode(bare)
    return f"{disp} ({hom})" if hom else disp


def to_doc(entry: dict) -> dict:
    text, en = escape(entry["text"], quote=False), escape(entry["en"], quote=False)
    z = f'<b class="cue">{en}</b>{text[len(en):]}' if en and text.startswith(en) else text
    row = {"lv": 0, "n": "", "z": z}
    credit = CREDIT[entry["source"].split(":", 1)[0]]
    if credit:
        row["au"] = [credit]
    return {
        "head": beta_to_unicode(homonym_split(entry["key"])[0]),
        "rows": [row],
        "key": entry["key"],
        "src": SRC,
    }


def read_pack(out_dir: Path, name: str) -> tuple[dict, dict]:
    idx = json.loads((out_dir / f"{name}.idx.json").read_text(encoding="utf-8"))
    raw = (out_dir / f"{name}.pack").read_bytes()
    buckets = {
        bk: json.loads(gzip.decompress(raw[off:off + n]))
        for bk, (off, n) in idx["buckets"].items()
    }
    return idx, buckets


def _meta(idx: dict) -> dict:
    return {k: v for k, v in idx.items() if k not in ("format", "pack", "sha256", "buckets")}


def apply(out_dir: Path, entries: list[dict]) -> dict:
    """Patch grc-lsj-t8 and grc-analyses in out_dir; return their manifest
    entries. Raises if a supplement key is already a lexicon key."""
    keys = {e["key"] for e in entries}  # plus earlier supplement keys, below

    t8_idx, t8 = read_pack(out_dir, "grc-lsj-t8")
    for bucket in t8.values():
        for folded in list(bucket):
            keys |= {d["key"] for d in bucket[folded] if d.get("src") == SRC}
            bucket[folded] = [d for d in bucket[folded] if d.get("src") != SRC]
            if not bucket[folded]:
                del bucket[folded]
    for e in entries:
        folded = beta_fold(e["key"])
        slot = t8.setdefault(bucket_name(folded), {}).setdefault(folded, [])
        if any(d.get("key") == e["key"] for d in slot):
            raise ValueError(f"supplement key {e['key']!r} is already a lexicon key")
        slot.append(to_doc(e))

    an_idx, an = read_pack(out_dir, "grc-analyses")
    by_display = {display(e["key"]): e["key"] for e in entries}
    attached = set()
    for bucket in an.values():
        for forms in bucket.values():
            for rows in forms.values():
                for row in rows:
                    row[1] = [k for k in row[1] if k not in keys]
                    key = by_display.get(row[0])
                    if key and not row[1]:
                        row[1] = [key]
                        attached.add(key)
    # The form index sometimes files the name under another spelling of the
    # lemma (Λάσος for Λᾶσος, Ὀϊκλέης under the form Ὀικλῆς). The lookup
    # renders every row in the folded slot of the word it is given, so a
    # keyless capitalised row in the head's own slot takes the key too.
    for e in entries:
        folded = beta_fold(e["key"])
        for rows in an.get(bucket_name(folded), {}).get(folded, {}).values():
            for row in rows:
                if not row[1] and row[0][:1].isupper():
                    row[1] = [e["key"]]
                    attached.add(e["key"])

    t8_meta = {**_meta(t8_idx), "names_supplement": len(entries)}
    an_meta = {**_meta(an_idx), "names_attached": len(attached)}
    return {
        "grc-lsj-t8": write_pack(out_dir, "grc-lsj-t8", t8, t8_meta),
        "grc-analyses": write_pack(out_dir, "grc-analyses", an, an_meta),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--names", type=Path, default=NAMES)
    args = ap.parse_args()
    entries = load(args.names)
    datasets = apply(args.out, entries)
    mpath = args.out / "manifest.json"
    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    manifest["datasets"].update(datasets)
    manifest["license"] = LICENSE
    mpath.write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"names: {len(entries)} entries; analyses keys attached for "
          f"{datasets['grc-analyses']['names_attached']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
