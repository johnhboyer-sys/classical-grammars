#!/usr/bin/env python3
"""CI integrity tests for the committed word-tool packs (stdlib only).

Validates what a static host and the /words client depend on, without
needing Diogenes: index checksums match the packs, every byte range
decompresses to valid JSON, folded keys live in the bucket their prefix
names, and rows have the format-2 shape (dictKeys as a list).

Run: python3 scripts/wordtool/test_packs.py
"""

from __future__ import annotations

import gzip
import hashlib
import json
import sys
import re
import unicodedata
import unittest
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / "data" / "wordtool"
DATASETS = ["grc-analyses", "lat-analyses", "grc-lsj", "lat-ls", "grc-ml"]


def load(name: str):
    idx = json.loads((DATA / f"{name}.idx.json").read_text(encoding="utf-8"))
    pack = (DATA / f"{name}.pack").read_bytes()
    return idx, pack


def sample_buckets(idx: dict) -> list[str]:
    names = sorted(idx["buckets"])
    return [names[0], names[len(names) // 2], names[-1]]


class PackIntegrity(unittest.TestCase):
    def test_files_exist(self):
        for name in DATASETS:
            self.assertTrue((DATA / f"{name}.pack").exists(), name)
            self.assertTrue((DATA / f"{name}.idx.json").exists(), name)
        self.assertTrue((DATA / "manifest.json").exists())

    def test_sha256_matches(self):
        manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
        for name in DATASETS:
            idx, pack = load(name)
            sha = hashlib.sha256(pack).hexdigest()
            self.assertEqual(sha, idx["sha256"], f"{name}: idx sha vs pack")
            self.assertEqual(
                sha, manifest["datasets"][name]["sha256"], f"{name}: manifest sha"
            )

    def test_ranges_tile_the_pack(self):
        for name in DATASETS:
            idx, pack = load(name)
            spans = sorted(idx["buckets"].values())
            total = 0
            for offset, length in spans:
                self.assertEqual(offset, total, f"{name}: gap or overlap at {offset}")
                self.assertGreater(length, 0, name)
                total += length
            self.assertEqual(total, len(pack), f"{name}: ranges must cover the pack")

    def test_buckets_decompress_and_keep_prefix(self):
        for name in DATASETS:
            idx, pack = load(name)
            for bucket in sample_buckets(idx):
                offset, length = idx["buckets"][bucket]
                payload = json.loads(gzip.decompress(pack[offset : offset + length]))
                self.assertIsInstance(payload, dict, f"{name}/{bucket}")
                self.assertGreater(len(payload), 0, f"{name}/{bucket}")
                for folded in payload:
                    want = folded[:2] if len(folded) >= 2 else folded or "_"
                    self.assertEqual(
                        want, bucket, f"{name}: key {folded!r} in bucket {bucket!r}"
                    )

    def test_analyses_row_shape(self):
        for name in ["grc-analyses", "lat-analyses"]:
            idx, pack = load(name)
            bucket = sample_buckets(idx)[1]
            offset, length = idx["buckets"][bucket]
            payload = json.loads(gzip.decompress(pack[offset : offset + length]))
            for folded, forms in list(payload.items())[:20]:
                for form, rows in forms.items():
                    self.assertIsInstance(form, str)
                    for row in rows:
                        self.assertEqual(len(row), 5, f"{name} row {row!r}")
                        lemma, keys, gloss, parse, variant = row
                        self.assertIsInstance(lemma, str)
                        self.assertIsInstance(keys, list, "dictKeys must be a list")
                        self.assertIsInstance(gloss, str)
                        self.assertIsInstance(parse, str)
                        self.assertTrue(variant is None or isinstance(variant, str))

    def test_lexicon_entry_shape(self):
        for name in ["grc-lsj", "lat-ls", "grc-ml"]:
            idx, pack = load(name)
            bucket = sample_buckets(idx)[1]
            offset, length = idx["buckets"][bucket]
            payload = json.loads(gzip.decompress(pack[offset : offset + length]))
            for folded, entries in list(payload.items())[:20]:
                self.assertIsInstance(entries, list)
                for entry in entries:
                    self.assertIn("key", entry)
                    self.assertIn("head", entry)
                    self.assertIn("html", entry)

    def test_middle_liddell_entries_are_clean(self):
        """grc-ml is repaired on the way in (ml_fragment_fix): every
        entry must have a head and a body, Greek must be NFC, and none
        of the source's Beta Code or length-mark leaks may survive."""
        idx, pack = load("grc-ml")
        for bucket in sample_buckets(idx):
            offset, length = idx["buckets"][bucket]
            payload = json.loads(gzip.decompress(pack[offset : offset + length]))
            for entries in payload.values():
                for entry in entries:
                    who = f"grc-ml {entry.get('key')!r}"
                    self.assertTrue(entry["head"].strip(), who)
                    self.assertTrue(entry["html"].strip(), who)
                    for text in (entry["head"], entry["html"]):
                        self.assertEqual(
                            unicodedata.normalize("NFC", text), text, who
                        )
                    self.assertNotRegex(entry["html"], r"[Ͱ-Ͽἀ-῿][̀-ͯ]*-?[_^]", who)
                    self.assertNotRegex(entry["html"], r'lang="grc">[^<]*[a-z][()/\\=|]', who)
                    self.assertNotIn("lx-sense-n\">0.", entry["html"], who)


T8_DATASETS = ["grc-lsj-t8", "lat-ls-t8"]
_ROMAN = re.compile(r"^[IVX]+$")


def _children(rows: list, i: int):
    """Indexes of the rows nested under rows[i]."""
    depth = rows[i].get("lv", 0)
    for j in range(i + 1, len(rows)):
        if rows[j].get("lv", 0) <= depth:
            return
        yield j


class T8Structure(unittest.TestCase):
    """Structural invariants of the presentation packs.

    These read every entry, not a sample: the defect this guards was
    invisible in the thirteen seed words and in every bucket sample taken
    of it, and showed up only in a full census.
    """

    def test_no_roman_divisions_under_a_supplied_arabic(self):
        """A supplied numeral must never outrank the print's own divisions.

        `sense_numbers` fills a blank address from the next sibling. When
        it read a grandchild's "2." as that sibling it supplied "1." to a
        row the print calls "I.", and the entry's real II, III, IV stayed
        nested underneath the supplied 1 — so LSJ χείρ rendered "Special
        usages" as a sub-sense of "the hand". 408 Greek entries shipped
        that shape. The address we invent is never allowed to swallow an
        address the print actually wrote.
        """
        for name in T8_DATASETS:
            idx, pack = load(name)
            bad = []
            for bucket in sorted(idx["buckets"]):
                offset, length = idx["buckets"][bucket]
                payload = json.loads(gzip.decompress(pack[offset : offset + length]))
                for entries in payload.values():
                    for entry in entries:
                        rows = entry.get("rows") or []
                        for i, row in enumerate(rows):
                            n = (row.get("n") or "").rstrip(".")
                            if not (row.get("s") and n.isdigit()):
                                continue
                            stranded = [
                                rows[j].get("n")
                                for j in _children(rows, i)
                                if _ROMAN.match((rows[j].get("n") or "").rstrip("."))
                            ]
                            if stranded:
                                bad.append(
                                    f"{entry.get('head')} ({entry.get('key')}): "
                                    f"supplied {row.get('n')!r} over {stranded}"
                                )
                                break
            self.assertEqual(
                bad[:12], [], f"{name}: {len(bad)} entries strand roman divisions"
            )

    def test_a_supplied_numeral_never_duplicates_one_below_it(self):
        """We must not invent an address the entry already uses.

        An unnumbered first sense followed one level down by "I." is a
        headword PREAMBLE — the general meaning the print states before it
        subdivides — and the romans under it are its own subdivisions,
        correctly nested. ἁγνός opens "pure, chaste, holy" and then
        divides I., II., III. Supplying "I." to that preamble would put
        our invented address directly above the print's real one. The
        philosophy readers measured this class from their own direction:
        8,091 genuinely demoted series against 209 preambles.

        Today two separate things prevent it — the predecessor table has
        no entry for "I", and the lift requires the first roman to be
        "II". Either alone would hold, which is exactly why this is
        asserted rather than left to them: a table that gained an "I" for
        consistency would silently make the other the only guard.
        """
        for name in T8_DATASETS:
            idx, pack = load(name)
            bad = []
            for bucket in sorted(idx["buckets"]):
                offset, length = idx["buckets"][bucket]
                payload = json.loads(gzip.decompress(pack[offset : offset + length]))
                for entries in payload.values():
                    for entry in entries:
                        rows = entry.get("rows") or []
                        for i, row in enumerate(rows):
                            if not row.get("s"):
                                continue
                            n = (row.get("n") or "").rstrip(".")
                            # Roman only. The corruption this guards is a
                            # supplied "I." landing on a preamble above the
                            # print's own "I." Known residue outside that:
                            # L&S comprimo nests an adverb block inside a
                            # "—Hence, compressus, P. a." participle block,
                            # so its supplied "1." stands three levels above
                            # the adverb's own "1." Different series runs,
                            # not an invented address colliding with a real
                            # one, and untangling L&S participle blocks is
                            # its own piece of work.
                            if not _ROMAN.match(n):
                                continue
                            clash = [
                                j for j in _children(rows, i)
                                if (rows[j].get("n") or "").rstrip(".") == n
                            ]
                            if clash:
                                bad.append(
                                    f"{entry.get('head')} ({entry.get('key')}): "
                                    f"supplied {n!r} above its own {n!r}"
                                )
                                break
            self.assertEqual(
                bad[:12], [], f"{name}: {len(bad)} entries invent an address they already use"
            )



class AuthorChips(unittest.TestCase):
    """A chip names an author, not one of that author's works.

    `short_authors` once collected every marked title in a short entry,
    so ἀέροψ, whose only citation is "Sch. Ar. Av. 1354", shipped the
    chips "Ar., Av.": Aristophanes and his own Birds, as two authors.
    2,198 Greek chips and 294 Latin. Nothing could see it: the row is
    well formed, the census reads sense lines, and the pack diff had
    nothing to compare against.

    The witness is each dictionary's own front matter, parsed into
    `scripts/wordtool/data/*-abbrevs.json`. An abbreviation those tables
    list as a work and never as an author or a publication cannot be a
    chip. A title they give no author (AP, h.Merc., Ev.Matt., IG, POxy.)
    is not in the works table and is left alone, and so are the 70 Greek
    and 29 Latin abbreviations that are both (Pl., Ar., Il., Quint.),
    because the tables cannot say which is meant.

    Two cases are certain and are what this checks: the author who owns
    the work is a chip on the same row, so the reader has him already;
    and the tables give the abbreviation to more than one author, so it
    identifies nobody ("Fr." is Fragmenta and 24 authors have one). A
    work the tables give to exactly one author whom no chip claims is
    left standing, because the works lists are too thin to drop a name
    the print gives: "Al." is Nicander's Alexipharmaca to the table and
    LSJ cites "Al. Le. 11.19" for a reading in Leviticus.
    """

    def work_owners(self, table: dict) -> dict[str, set[str]]:
        """Work abbreviation to the authors the tables give it, for the
        works that are never an author or a publication themselves."""
        names = set(table.get("authors") or {}) | set(table.get("publications") or {})
        owners: dict[str, set[str]] = {}
        for author, works in (table.get("works") or {}).items():
            for work in works or ():
                key = work.strip().rstrip(".")
                if key and key not in names and work not in names:
                    owners.setdefault(key, set()).add(author)
        return owners

    def test_no_chip_is_a_work_title(self):
        here = Path(__file__).resolve().parent
        for dataset, abbrev in (("grc-lsj-t8", "lsj-abbrevs.json"),
                                ("lat-ls-t8", "ls-abbrevs.json")):
            table = json.loads((here / "data" / abbrev).read_text(encoding="utf-8"))
            owners = self.work_owners(table)
            idx, pack = load(dataset)
            bad = []
            for name, (off, length) in idx["buckets"].items():
                bucket = json.loads(gzip.decompress(pack[off:off + length]).decode("utf-8"))
                for docs in bucket.values():
                    for doc in docs:
                        for row in doc.get("rows") or ():
                            chips = list(row.get("au") or ())
                            for chip in chips:
                                own = owners.get(chip.strip().rstrip("."))
                                if own and ((own & set(chips)) or len(own) > 1):
                                    bad.append((doc.get("head"), chip))
            self.assertEqual(
                bad[:8], [],
                f"{dataset}: {len(bad)} chips name a work, not an author")


class CompoundLemmas(unittest.TestCase):
    """A hyphenated Morpheus lemma joins by the ordinary rules."""

    def test_join(self):
        import build_wordtool as B
        for lemma, want in [
            ("ἀπό-ἅζομαι", "ἀφάζομαι"),      # elision, then aspiration
            ("ἐπί-ἅζομαι", "ἐφάζομαι"),
            ("ἐκ-ὀνίνημι", "ἐξονίνημι"),
            ("ἐν-λείβω", "ἐλλείβω"),
            ("σύν-ὀμάζω", "συνομάζω"),
            ("σύν-πλέκω", "συμπλέκω"),
            ("ἐν-κηρύσσω", "ἐγκηρύσσω"),
            ("κατά-ἰόομαι", "κατιόομαι"),
            ("περί-ἄγω", "περιάγω"),        # περί keeps its vowel
            ("ἀντί-ὑφαιρέω", "ἀνθυφαιρέω"),
        ]:
            self.assertEqual(B.join_compound(lemma), want, lemma)
        self.assertIsNone(B.join_compound("ἐπί,ἀμφί-ἰάομαι"))   # two prefixes
        self.assertIsNone(B.join_compound("ἄζομαι"))

if __name__ == "__main__":
    sys.exit(unittest.main())
