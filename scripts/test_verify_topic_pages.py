#!/usr/bin/env python3
"""Cases for the topic-page verifier's own text rules (stdlib only).

The verifier is the only reader authored prose gets, and it now carries
enough logic to be wrong: a sentence splitter, a fold, three spellings of
a hyphenated word, and the Greek check that decides whether a form on the
page has a witness behind it. Each case here was a hole a page found.

Run: python3 scripts/test_verify_topic_pages.py
"""

from __future__ import annotations

import importlib.util
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "verify_topic_pages", os.path.join(HERE, "verify_topic_pages.py"))
V = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(V)


class Sentences(unittest.TestCase):
    def split(self, line):
        return V.SENTENCE_SPLIT_RE.split(line)

    def test_a_parenthesised_citation_stays_with_its_sentence(self):
        # "did I not say so? (§2025)" split in two, and the half with the
        # Greek then carried no citation and was never read.
        self.assertEqual(
            len(self.split('οὐκ ἠγόρευον; did I not say so? (§2025)')), 1)
        # The break after a real sentence still lands.
        self.assertEqual(
            len(self.split('Is it so? (GMT §787) That is the rule. '
                           'The next one (§2).')), 2)

    def test_the_prints_spaced_ellipsis_does_not_end_a_sentence(self):
        # Smyth sets ". . ." inside a quotation, and ἐστιν begins with an
        # accented vowel the splitter read as the next sentence's capital.
        self.assertEqual(
            len(self.split('τὸ μέν . . . ἐστιν ἀγαθόν (§2025)')), 1)

    def test_a_real_sentence_break_still_splits(self):
        self.assertEqual(
            len(self.split('This is one (§2025). This is another (§2026).')), 2)


class Blocks(unittest.TestCase):
    def test_a_hard_wrapped_paragraph_is_one_block(self):
        body = ("the substantive-making power of the article\n"
                "(§1153) and the predicate position of adjectives (§1168).\n")
        self.assertEqual(len(V.blocks(body)), 1)
        # and so the citation is read with the words that support it
        self.assertEqual(len(V.sentences(body)), 1)

    def test_a_list_item_and_a_heading_start_their_own_block(self):
        body = "## Recognition\n\n- one item (§1).\n- another (§2).\n"
        self.assertEqual(V.blocks(body), ["Recognition", "one item (§1).",
                                          "another (§2)."])

    def test_a_blank_line_ends_a_block(self):
        self.assertEqual(len(V.blocks("one\ntwo\n\nthree\n")), 2)


class Hyphens(unittest.TestCase):
    def test_a_line_break_hyphen_joins(self):
        self.assertEqual(V.dehyphenate("γιγνομέ- νων"), "γιγνομένων")

    def test_a_syllable_hyphen_joins(self):
        self.assertEqual(V.unhyphenate("δηλό-τερος"), "δηλότερος")

    def test_the_haystack_carries_every_spelling(self):
        rows = {1: {"head": "", "plain": "γιγνομέ- νων δηλό-τερος"}}
        hay = V.haystack(rows, [1])
        self.assertIn("γιγνομε- νων", hay)     # as the print sets it
        self.assertIn("γιγνομενων", hay)       # the line break joined
        self.assertIn("δηλοτερος", hay)        # the syllable hyphen gone


class GreekCheck(unittest.TestCase):
    def missing(self, sentence, section_text):
        rows = {1: {"head": "", "plain": section_text}}
        return V.greek_missing(sentence, V.haystack(rows, [1]))

    def test_a_word_the_section_does_not_hold_is_reported(self):
        out = self.missing("Find ἐᾱ́ν and read on (§1).", "πρότασις ἀπόδοσις")
        self.assertEqual([w for _run, w in out], ["εαν"])

    def test_accents_and_macrons_do_not_matter(self):
        self.assertEqual(self.missing("Find ἐᾱ́ν (§1).", "ἐάν τι ἔχῃ"), [])

    def test_a_run_may_be_quoted_across_the_prints_gap(self):
        # The page joins what Smyth prints with an ellipsis between.
        self.assertEqual(
            self.missing("Read οἷα δὴ ἀπιόντων (§1).", "οἷα δὴ . . . ἀπιόντων"),
            [])

    def test_one_letter_is_not_checked(self):
        # A single letter is a name for the letter, not a quotation.
        self.assertEqual(self.missing("The letter ἀ (§1).", "nothing"), [])


class ExactCheck(unittest.TestCase):
    """The stricter pass in scripts/check_topic_greek_exact.py."""

    def setUp(self):
        spec = importlib.util.spec_from_file_location(
            "check_topic_greek_exact",
            os.path.join(HERE, "check_topic_greek_exact.py"))
        self.C = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.C)

    def test_a_grave_and_an_acute_are_the_same_word(self):
        self.assertEqual(self.C.norm("μητρὶ"), self.C.norm("μητρί"))

    def test_a_capital_at_the_head_of_the_prints_example_is_folded(self):
        self.assertEqual(self.C.norm("Ἐνταῦθα"), self.C.norm("ἐνταῦθα"))

    def test_a_macron_is_not_folded(self):
        # The law says a macron difference defers to the editor, so the
        # page must carry the print's own.
        self.assertNotEqual(self.C.norm("ἡμέρας"), self.C.norm("ἡμέρᾱς"))


class Citations(unittest.TestCase):
    def test_a_bare_number_after_a_prefix_is_read_as_smyth(self):
        m = list(V.CITATION_RE.finditer("GMT §594, §595"))
        self.assertEqual([x.group(1) for x in m], ["GMT", None])

    def test_a_range_is_read_whole(self):
        m = V.CITATION_RE.search("§§2054-2087")
        self.assertEqual((m.group(3), m.group(4)), ("2054", "2087"))

    def test_a_lettered_anchor_is_read(self):
        m = V.CITATION_RE.search("§2072 a)")
        self.assertEqual(m.group(5), "a")


if __name__ == "__main__":
    unittest.main(verbosity=2 if "-v" in sys.argv else 1)
