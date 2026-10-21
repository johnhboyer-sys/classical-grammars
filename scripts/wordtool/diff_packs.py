#!/usr/bin/env python3
"""Row-level diff of the working-tree packs against a committed baseline.

The gate the other gates cannot be: `build_wordtool.py` proves the packs
are well-formed, `test_packs.py` proves their invariants hold, and the
site's audit proves the renderer can read them. None of the three proves
the packs still SAY what they said. Three silent losses shipped through
all of them in one branch (PR #33):

  * ~4,000 rows became banners, and a banner ships `ex: []` and `au: []`,
    so an example vanished from 3,504 entries and an author chip from
    4,149. μένος I. "might, force" kept its gloss and lost all four of
    its quotations.
  * L&S dapsilis lost its "α." while rows, glosses, examples and chips
    were all byte-identical. Only `n` had changed.
  * 23 entries were shipping duplicate invented numerals — Latin `as`
    had thirty-one rows numbered "I.", one real and thirty not.

Every delta this prints must be EXPLAINED before shipping, not merely
small. The 40 example losses in that branch were gloss promotions
(ἀγκύλιον's "Dim. of" became "Dim. of ἀγκύλη, loop in noose" by pulling
the example onto the sense line) and the 86 numeral losses were the
duplicates above. Both looked like regressions and both were fixes.
Size tells you nothing; only the explanation does.

Usage:
    python3 scripts/wordtool/diff_packs.py [--ref REF] [--examples N]
                                           [dataset ...]

Exits 0 only when nothing differs. Any delta at all exits 1, because
"explained" is not a property an exit code can check — a difference has
to stop the line and put a person in front of it.
"""

from __future__ import annotations

import argparse
import collections
import difflib
import gzip
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "wordtool"
DATASETS = ["grc-lsj-t8", "lat-ls-t8"]

# Everything a row carries. Compared as values and in both directions:
# the branch that lost 5 author chips on ἀραρίσκω's A. gained 3 examples
# and 2 chips on its I. row in the same move, and a one-directional diff
# shows the loss, hides the compensation, and reads a trade as a
# regression.
ROW_FIELDS = ["lv", "n", "b", "s", "u"]
ROW_COUNTS = ["ex", "au"]
# Entry-level fields. A regression in head_bits or form_bar touches none
# of the rows and would otherwise pass this diff untouched.
ENTRY_FIELDS = ["head", "i", "g", "gr", "p", "f", "au", "hom", "gl"]


def load(root: Path | None, name: str, ref: str | None) -> dict:
    """{(key, index): record} for one dataset, from disk or from git."""
    if ref is None:
        idx = json.loads((root / f"{name}.idx.json").read_text("utf-8"))
        pack = (root / f"{name}.pack").read_bytes()
    else:
        idx = json.loads(git_show(f"{ref}:data/wordtool/{name}.idx.json"))
        pack = git_show(f"{ref}:data/wordtool/{name}.pack")
    out = {}
    for offset, length in idx["buckets"].values():
        payload = json.loads(gzip.decompress(pack[offset:offset + length]))
        for key, recs in payload.items():
            for i, rec in enumerate(recs):
                out[(key, i)] = rec
    return out


def git_show(spec: str) -> bytes:
    """Packs are binary, so this stays in bytes — no text mode anywhere."""
    proc = subprocess.run(["git", "show", spec], cwd=ROOT,
                          capture_output=True)
    if proc.returncode != 0:
        sys.exit(f"diff_packs: git show {spec} failed:\n"
                 f"{proc.stderr.decode('utf-8', 'replace').strip()}")
    return proc.stdout


def sig(row: dict) -> str:
    """What identifies a row across a change to its numbering.

    Rows carry no id, and pairing them by position is what let the old
    scratchpad diff go blind exactly when it mattered: `zip` truncates,
    so one added row shifted every comparison after it and silently
    dropped the tail. The gloss is the field a numbering fix does not
    touch — χείρ's bug moved `n` and `lv` and left every `z` alone — so
    it is the anchor here. A change that rewrites glosses instead (P14's
    definition segmenting) will report its rows as added and removed
    rather than paired, which is the honest answer: those rows are not
    the same rows.

    Not truncated. An 80-character cap looked harmless and was not: two
    long glosses sharing a prefix collapse to one signature, the matcher
    calls them equal, and the pairing goes back to being positional for
    exactly the rows most likely to have moved.

    Residual, accepted and visible: rows whose gloss is genuinely empty
    all share the empty signature, so the matcher can pair a blank row
    with the wrong blank row. That misreports which row changed, but it
    misreports it LOUDLY — the deltas still print, as a numeral change
    plus an add rather than as one add. Noise, not silence.
    """
    return " ".join((row.get("z") or "").split())


def align(old: list, new: list):
    """(pairs, dropped, added) — rows matched on gloss, then the rest.

    autojunk off: it treats an element appearing in more than 1% of a
    long sequence as noise, and an entry with many blank-gloss rows is
    exactly that shape.
    """
    matcher = difflib.SequenceMatcher(
        None, [sig(r) for r in old], [sig(r) for r in new], autojunk=False)
    pairs, dropped, added = [], [], []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            pairs.extend(zip(old[i1:i2], new[j1:j2]))
            continue
        # A replace block is two runs of rows that did not match. Pair
        # them positionally as far as they go — same position in the
        # same entry is the best evidence left once the gloss changed —
        # and report the remainder as gone or arrived.
        overlap = min(i2 - i1, j2 - j1)
        pairs.extend(zip(old[i1:i1 + overlap], new[j1:j1 + overlap]))
        dropped.extend(old[i1 + overlap:i2])
        added.extend(new[j1 + overlap:j2])
    return pairs, dropped, added


class Deltas:
    """Counts and example headwords, one bucket per kind of change."""

    def __init__(self, keep: int):
        self.keep = keep
        self.counts = collections.Counter()
        self.examples = collections.defaultdict(list)

    def note(self, kind: str, head: str, detail: str = "") -> None:
        self.counts[kind] += 1
        seen = self.examples[kind]
        if len(seen) < self.keep:
            seen.append(f"{head} {detail}".strip())

    def report(self) -> list[str]:
        lines = []
        for kind, n in sorted(self.counts.items(), key=lambda kv: -kv[1]):
            eg = "; ".join(self.examples[kind])
            lines.append(f"  {kind}: {n}" + (f"    e.g. {eg}" if eg else ""))
        return lines


def compare(name: str, ref: str, keep: int) -> bool:
    """True when the two builds of one dataset are identical."""
    old = load(None, name, ref)
    new = load(DATA, name, None)
    print(f"\n=== {name}: baseline({ref}) {len(old)} entries, "
          f"working tree {len(new)} entries")

    d = Deltas(keep)
    gone, arrived = set(old) - set(new), set(new) - set(old)
    # sorted, not set order: the rest of the report is deterministic and
    # these two lines would have shuffled their example headwords with
    # PYTHONHASHSEED the first time an entry was actually lost.
    for key in sorted(gone)[:keep]:
        d.note("entry LOST", old[key].get("head") or key[0])
    for key in sorted(arrived)[:keep]:
        d.note("entry GAINED", new[key].get("head") or key[0])
    d.counts["entry LOST"] = len(gone)
    d.counts["entry GAINED"] = len(arrived)
    if not gone:
        del d.counts["entry LOST"]
    if not arrived:
        del d.counts["entry GAINED"]

    numerals = collections.Counter()
    rows_old = rows_new = 0
    for key in sorted(set(old) & set(new)):
        a, b = old[key], new[key]
        head = a.get("head") or key[0]
        ra, rb = a.get("rows") or [], b.get("rows") or []
        rows_old += len(ra)
        rows_new += len(rb)

        for field in ENTRY_FIELDS:
            va, vb = a.get(field), b.get(field)
            if va == vb:
                continue
            if va and not vb:
                d.note(f"entry.{field} LOST", head, repr(va)[:48])
            elif vb and not va:
                d.note(f"entry.{field} GAINED", head, repr(vb)[:48])
            else:
                d.note(f"entry.{field} changed", head,
                       f"{va!r}->{vb!r}"[:64])

        pairs, dropped, added = align(ra, rb)
        for row in dropped:
            d.note("row DROPPED", head, repr(sig(row))[:48])
        for row in added:
            d.note("row ADDED", head, repr(sig(row))[:48])

        for x, y in pairs:
            for field in ROW_FIELDS:
                va, vb = x.get(field), y.get(field)
                if va == vb:
                    continue
                d.note(f"row.{field}: {va!r} -> {vb!r}", head)
                if field == "n":
                    numerals[(va or "-", vb or "-")] += 1
            for field in ROW_COUNTS:
                va, vb = x.get(field) or [], y.get(field) or []
                if len(va) != len(vb):
                    word = "lost" if len(vb) < len(va) else "gained"
                    d.note(f"row.{field} {word}", head, f"{len(va)}->{len(vb)}")
                elif va != vb:
                    # Counting was the whole check here once, and a
                    # quotation swapped for another quotation kept the
                    # count: μένος keeping four examples that are no
                    # longer the same four would have printed "no
                    # differences". Equality is the test; the contents
                    # stay out of the report, because a content dump over
                    # 195,069 rows buries the line this gate exists for.
                    d.note(f"row.{field} rewritten", head, f"{len(va)} items")
            # Emptiness separately from the text: a gloss going blank is
            # the loss the banner path causes, and it is worth its own
            # line rather than being one more "z changed".
            za, zb = (x.get("z") or "").strip(), (y.get("z") or "").strip()
            if za and not zb:
                d.note("row.z BLANKED", head, repr(za)[:48])
            elif zb and not za:
                d.note("row.z filled", head, repr(zb)[:48])
            elif za != zb:
                d.note("row.z reworded", head)

    print(f"  rows: {rows_old} -> {rows_new} ({rows_new - rows_old:+d})")
    lines = d.report()
    if not lines:
        print("  no differences")
        return True
    print("\n".join(lines))
    if numerals:
        print("  numeral transitions:")
        for (va, vb), n in numerals.most_common(12):
            print(f"    {va} -> {vb}: {n}")
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("datasets", nargs="*", default=DATASETS,
                    help=f"default: {' '.join(DATASETS)}")
    ap.add_argument("--ref", default="HEAD",
                    help="git ref holding the baseline packs (default HEAD)")
    ap.add_argument("--examples", type=int, default=6,
                    help="headwords to name per delta class (default 6)")
    args = ap.parse_args()

    clean = True
    for name in (args.datasets or DATASETS):
        clean &= compare(name, args.ref, args.examples)
    print()
    if clean:
        print("diff_packs: identical to baseline.")
        return 0
    print("diff_packs: the packs changed. Every delta above needs an "
          "explanation before these ship.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
