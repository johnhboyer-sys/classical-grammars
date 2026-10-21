#!/usr/bin/env python3
"""Regression tests for Greek/Latin script mixing in the Goodell conversion.

The DCC source mixes the two scripts in both directions: Latin lookalikes
inside Greek words ("tί" for τί) and Greek lookalikes inside English words
("alsο" for also). The converter repaired only the first direction, and its
adjacency rule spread the second one across the rest of the word. Joining
text nodes without a separator then fed a Greek headword straight into its
English gloss, so `plain` corrupted glosses the `html` had kept clean.

Run: python3 scripts/test_goodell_script_mixing.py
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import convert_goodell as cg

ROOT = Path(__file__).resolve().parents[1]
SECTIONS = ROOT / "data" / "goodell" / "sections.jsonl"

GREEK = re.compile(r"[Ͱ-Ͽἀ-῿]")
LATIN = re.compile(r"[A-Za-z]")
TOKEN = re.compile(r"[A-Za-zͰ-Ͽἀ-῿̀-ͯ’']+")
TAG = re.compile(r"<[^>]+>")


def mixed_tokens(text: str) -> list[str]:
    return [t for t in TOKEN.findall(text) if LATIN.search(t) and GREEK.search(t)]


class CleanChars(unittest.TestCase):
    def test_latin_lookalike_in_greek_word_becomes_greek(self):
        # The repair the converter already performed; it must survive.
        self.assertEqual(cg.clean_chars("tί"), "τί")
        self.assertEqual(cg.clean_chars("mή"), "μή")
        self.assertEqual(cg.clean_chars("Oὐ"), "Οὐ")

    def test_greek_lookalike_in_english_word_becomes_latin(self):
        self.assertEqual(cg.clean_chars("alsο"), "also")
        self.assertEqual(cg.clean_chars("knοw"), "know")
        self.assertEqual(cg.clean_chars("hοw"), "how")
        self.assertEqual(cg.clean_chars("οf"), "of")
        self.assertEqual(cg.clean_chars("οr"), "or")

    def test_no_cascade_across_a_single_stray_letter(self):
        # A lone Greek omicron must not drag its Latin neighbours with it.
        self.assertEqual(cg.clean_chars("wοrkshop"), "workshop")
        self.assertEqual(cg.clean_chars("Νοrway"), "Norway")

    def test_word_final_latin_s_in_a_greek_word(self):
        self.assertEqual(cg.clean_chars("ὡs"), "ὡς")
        self.assertEqual(cg.clean_chars("οὗτοs"), "οὗτος")

    def test_final_sigma_after_a_combining_mark(self):
        # A Greek body ending in a combining accent is still a Greek body.
        self.assertEqual(cg.clean_chars("ᾱ́s"), "ᾱ́ς")

    def test_hyphen_continuation_keeps_a_medial_sigma(self):
        # The grammar hyphenates stems ("στεφ-ανός"); the sigma before the
        # hyphen is medial, not final.
        self.assertEqual(cg.clean_chars("προs-έρχομαι"), "προσ-έρχομαι")
        self.assertEqual(cg.clean_chars("λύs-ω"), "λύσ-ω")

    def test_final_sigma_still_fires_at_a_real_word_end(self):
        self.assertEqual(cg.clean_chars("ὡs, καί"), "ὡς, καί")
        self.assertEqual(cg.clean_chars("λόγοs-"), "λόγος-")

    def test_non_ascii_latin_counts_as_latin_evidence(self):
        # "German ä" appears in the alphabet table, so Latin-1 letters occur.
        self.assertEqual(cg.clean_chars("têtε"), "tête")
        self.assertEqual(cg.clean_chars("tête"), "tête")

    def test_glued_greek_and_english_is_left_alone(self):
        # Evidence for both scripts: not a lookalike substitution, so the
        # character policy must not guess. plain() keeps them apart instead.
        for glued in ("ἐγγύςfar", "δεινοῦοut", "ἙλλάςGreece"):
            self.assertEqual(cg.clean_chars(glued), glued)

    def test_pure_text_is_untouched(self):
        for text in ("out of danger", "ἄξιος τῆς πόλεως", "also", "know"):
            self.assertEqual(cg.clean_chars(text), text)


class PlainSeparation(unittest.TestCase):
    def parse(self, markup: str):
        parser = cg.TreeBuilder()
        parser.feed(markup)
        return parser.root

    def test_line_break_separates_headword_from_gloss(self):
        node = self.parse("<p><strong>Ἀξίως τῆς πόλεως</strong><br><em>in a manner "
                          "worthy of the state</em></p>")
        self.assertEqual(cg.plain(node),
                         "Ἀξίως τῆς πόλεως in a manner worthy of the state")

    def test_gloss_and_citation_do_not_fuse(self):
        node = self.parse("<p><strong>ἔξω τοῦ δεινοῦ</strong><br><em>out of danger"
                          "</em><br>Xen. <em>Anabasis</em> 2.6.12</p>")
        self.assertEqual(cg.plain(node),
                         "ἔξω τοῦ δεινοῦ out of danger Xen. Anabasis 2.6.12")

    def test_adjacent_blocks_do_not_fuse(self):
        node = self.parse("<div><p>ἡ πόλις</p><p>the city</p></div>")
        self.assertEqual(cg.plain(node), "ἡ πόλις the city")

    def test_inline_emphasis_does_not_gain_a_space(self):
        node = self.parse("<p>a <em>far</em>-off <em>sound</em>s</p>")
        self.assertEqual(cg.plain(node), "a far-off sounds")


class CommittedData(unittest.TestCase):
    """The shipped data must carry no mixed-script word in either field."""

    @classmethod
    def setUpClass(cls):
        if not SECTIONS.exists():
            raise unittest.SkipTest(f"{SECTIONS} not built")
        with SECTIONS.open() as handle:
            cls.records = [json.loads(line) for line in handle]

    # What the DCC source leaves genuinely ambiguous, recorded in
    # grammar-goodell/DCC-ERRATA.md.  Both scripts are attested inside each of
    # these words, so the character policy declines to guess.
    RESIDUE = {177: ["wίse"], 412: ["στέφωput"], 456: ["cσmpleted"]}

    def test_html_has_no_mixed_script_words(self):
        bad = {r["n"]: mixed_tokens(TAG.sub(" ", r["html"])) for r in self.records}
        self.assertEqual({n: t for n, t in bad.items() if t}, self.RESIDUE)

    def test_plain_has_no_mixed_script_words(self):
        bad = {r["n"]: mixed_tokens(r["plain"]) for r in self.records}
        # §379 adds one more: the DCC markup itself omits the space in
        # "<strong>οὗ</strong>retain".
        expected = {**self.RESIDUE, 379: ["οὗretain"]}
        self.assertEqual({n: t for n, t in bad.items() if t}, expected)

    def test_the_other_non_smyth_works_stay_clean(self):
        for work in ("gildersleeve", "goodwin-gmt", "monro", "bennett"):
            path = ROOT / "data" / work / "sections.jsonl"
            if not path.exists():
                continue
            with self.subTest(work=work):
                bad = {}
                with path.open() as handle:
                    for line in handle:
                        record = json.loads(line)
                        found = (mixed_tokens(TAG.sub(" ", record["html"]))
                                 + mixed_tokens(record["plain"]))
                        if found:
                            bad[record["n"]] = found
                self.assertEqual(bad, {})

    def test_plain_keeps_headword_and_gloss_apart(self):
        record = next(r for r in self.records if r["n"] == 518)
        self.assertIn("τοῦ δεινοῦ out of danger", record["plain"])
        self.assertIn("τῆς πόλεως in a manner worthy", record["plain"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
