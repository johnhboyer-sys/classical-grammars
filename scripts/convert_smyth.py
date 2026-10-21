#!/usr/bin/env python3
"""Convert the Perseus TEI P4 Smyth grammar to deterministic JSON data.

The source has no DTD or custom entity declarations, so the stdlib
xml.etree.ElementTree parser can read it as-is.  The converter folds every
``type="smythp"`` node with a suffixed ``n`` (chiefly dialect notes) into the
record for its printed section number.  It also attaches unnumbered main-text
blocks to the prior printed section; the separate verb appendix stays out of
section records.  It performs no network access.
"""

from __future__ import annotations

import argparse
import bisect
import collections
import html
import json
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable, Iterator


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "grammar-smyth" / "src" / "smyth_eng_u.xml"
DEFAULT_SECTIONS = ROOT / "data" / "smyth" / "sections.jsonl"
DEFAULT_META = ROOT / "data" / "smyth" / "meta.json"
SECTION_RE = re.compile(r"^\s*(\d+)(.*)$")
RANGE_RE = re.compile(r"\b(\d{1,4})\s*[-\u2013\u2014]\s*(\d{1,4})\b")
DIV_RE = re.compile(r"div\d+")
LETTER_START_RE = re.compile(
    r"^(?:.{0,80}?\u2014)?(?:(\d+)\.\s*)?([a-z])\."
)
# An "a." label may follow lead-in prose ("With single words: a. ...").  The
# token just before the label separates prose from abbreviations and class
# labels: it needs two or more letters including a Latin lower-case one and no
# internal dot, and must end in "." or ":" (a close paren may precede).  This
# rejects "IV. a." verb-class labels, "1. 2. a." table headings, "v. a."
# (verbal adjective), and paragraph-initial "e.g."/"i.e.".
LETTER_LEADIN_RE = re.compile(r"^.{0,100}?(\S+)\s+a\.(?=\s)")
LEADIN_TOKEN_RE = re.compile(r"[^.\s]+[.:]")
LSJ_PREFIX = "Perseus:text:1999.04.0057:entry="
GREEK_RUN_RE = re.compile(r"[\u0370-\u03ff\u1f00-\u1fff][\u0300-\u036f\u0370-\u03ff\u1f00-\u1fff]*")
TAG_RE = re.compile(r"<[^>]+>")
# The parts of an un-wrapped example (see ``bare_example``) are joined by
# punctuation alone; after a gloss a parenthesis may close or open as well.
EXAMPLE_JOIN_RE = re.compile(r"^[\s,;:.]*$")
# Two Greek runs are one quotation only when nothing but Greek punctuation
# stands between them.  A colon is the print introducing an example after a
# headword, not a mark inside the quotation: Greek writes its colon "·" and
# its question mark ";".  Admitting it merged the bold lemma into the quotation
# at Sec. 1596, Sec. 1752 and Sec. 2479 ("ὥσπερ εἰ: θαυμάζω δέ σε . . ." was shipped
# as one Greek run with the colon dropped).
EXAMPLE_MERGE_RE = re.compile(r"^[\s,;.]*$")
GLOSS_TAIL_RE = re.compile(r"^[\s,;:.()]*$")
# A parenthesis on a Greek run's tail is a phrase the print cut in two, and a
# chain refuses to cross one.  It must equally refuse to START after one.  The
# bracket may hold an equivalent "( = X)", a word supplied "(scil. X)", a
# variant reading "(v.l. X)" or a cross reference "(1481)", and the markup is
# identical in all four, so nothing in the source says whether the bracket
# stands inside the quotation or is an aside about it.  Starting on the far
# side published the quotation cut short of its beginning under a translation
# of the whole of it: Sec. 978 shipped "ὤν, πόλεως τῆς μεγίστης" glossed "being an
# Athenian, a citizen of the greatest city" for the print's "Ἀθηναῖος ( =
# Ἀθηνῶν) ὤν, πόλεως τῆς μεγίστης".  Since the converter cannot tell the two
# brackets apart it takes no example at all, which costs 40 examples in the
# records (41 chains in the file) and invents nothing.
PAREN_OPENS_RE = re.compile(r"^[\s,;:.]*\(")
PAREN_CLOSES_RE = re.compile(r"^[\s,;:.]*\)[\s,;]*$")
# The whole bracket can also sit in one tail, when nothing inside it is marked
# up: "τὰ ὑπὸ γῆς (a fixed phrase) ἅπαντα" (Sec. 1698), "φθάνουσιν (hist. pres.)
# ἐπὶ τῷ ἄκρῳ γενόμενοι" (Sec. 2096).  Same cut, same refusal.
PAREN_ASIDE_RE = re.compile(r"^[\s,;:.]*\([^()]*\)[\s,;]*$")
# Perseus's own gap sigil.  The source writes "&lt;*&gt;" at 147 places where its
# text is defective ("ἡ <*> τεθνεώτων ἀρετή", "οἱ Ἡρᾱ<*>λέες"), which is the
# witness saying it has a gap.  Gaps stay explicit here, so the rule is: the
# sigil is a witness character like any other.  It is carried verbatim into
# every plain-text field the converter writes -- head, path, plain, and the
# examples' grc -- and escaped, not stripped, in html, where it has always been
# written "&lt;*&gt;".  Nothing rewrites it and nothing removes it, and
# verify_smyth.py counts it on both sides so a later tidy-up cannot drop it in
# silence.  Replacing it with a mark of our own would put a character in the
# data that no witness supplies, which is the defect the law names first.
GAP_SIGIL = "<*>"
# The source XML has literal bracketed placeholders for glyphs its authoring
# tool couldn't render as precomposed Unicode.  Each name is the glyph's
# description with every letter swapped for its Greek look-alike (i->iota,
# g->gamma, etc.), e.g. "iglide" -> "[\u03b9\u03b3\u03bb\u03b9\u03b4\u03b5]".  Replace with the actual
# glyph before parsing: non-syllabic vowels (glide) take a combining inverted
# breve below (no precomposed form exists), and the numeral marks are actual
# archaic Greek characters confirmed against the source's worked examples
# (Sec. 348: "[\u03c4\u03bd\u03c5\u03bc ]\u03b1[\u03c3\u03b1\u03bc\u03c0\u03b9 ]\u03b9#" = 1910 = 1000 + 900 + 10).
#
# A second group names the glyph in plain English instead ([macrdot], [Eunc],
# etc.).  Both were first matched against what was described as a CCEL Unicode
# edition of Smyth; no such text exists -- CCEL carries only page scans, and its
# reader reports no compatible version -- so both were re-read from the 1920
# print, and both targets changed as a result.
#
# [Eunc ] (Sec. 2, "capitals as \u0395, uncials as [Eunc ]") is a capital-height
# LUNATE epsilon: a C-shaped bowl with a short mid-bar, set in deliberate
# contrast with the square \u0395 four words earlier, the contrast being the point
# of the sentence ("the minuscules ... are cursive forms of the uncials").  A
# plain \u03b5 collapses it.  Unicode has no capital-height lunate epsilon: U+03F5
# has the right shape at x-height, U+2C88 COPTIC CAPITAL LETTER EIE the right
# shape and height but the wrong script.  U+03F5 wins, because a Coptic letter
# inside Greek text would break every Greek-aware consumer downstream, while
# cap height is a matter for the stylesheet.
#
# [macrdot] (24x, Homeric dialect notes, e.g. Sec. 146 D "[\u03b5]\u03bd\u1f76 \u03bc\u03b5\u03b3\u03ac\u03c1\u03bf\u03b9\u03c3\u03b9
# ([macrdot]\u02d8\u02d8[macrdot]\u02d8)") is a macron with a round dot centred above it,
# and it marks the long syllable carrying the rhythmic accent, the ictus: the
# sentence introducing that example says "syllable having the rhythmic accent",
# and Sec. 148 D. 2 speaks of "when the rhythmic accent falls upon the final
# syllable".  It is not the doubtful quantity a previous reading took it for, so
# U+23D2 METRICAL LONG OVER SHORT (which draws a macron over a *breve*) is both
# the wrong shape and the wrong sense.  Unicode has no precomposed ictus-long,
# so it is spelled as the spacing macron the source already pairs with U+02D8
# BREVE in these scansions, plus a combining dot above.
GLYPH_FIXES = {
    "[\u03b9\u03b3\u03bb\u03b9\u03b4\u03b5]": "\u03b9\u032f",  # \u03b9\u032f i-glide (non-syllabic iota, yod)
    "[\u03c5\u03b3\u03bb\u03b9\u03b4\u03b5]": "\u03c5\u032f",  # \u03c5\u032f u-glide (non-syllabic upsilon, digamma sound)
    "[\u03b5\u03b3\u03bb\u03b9\u03b4\u03b5]": "\u03b5\u032f",  # \u03b5\u032f e-glide (non-syllabic epsilon)
    "[\u03c3\u03b1\u03bc\u03c0\u03b9 ]": "\u03e1",  # \u03e1 sampi (numeral 900)
    "[sampi ]": "\u03e1",
    "[\u03c4\u03bd\u03c5\u03bc ]": "\u0375",  # \u0375 lower numeral sign (keraia below, marks thousands)
    "[macrdot]": "\u00af\u0307",  # spacing macron + dot above (the ictus-long)
}
# [Eunc ] wraps a source line break and indentation, so it can't be a literal
# GLYPH_FIXES key; matched by regex instead, right before the dict pass.
EUNC_RE = re.compile(r"\[Eunc\s*\]")
# [smooth] / [rough ] (Sec. 14, the archaic letter Heta splitting into the
# rough and smooth breathings) and [lins ] (Sec. 2 a, the pre-403 BC Attic
# letter form for lambda) stay unfixed.  Both decisions survive re-reading
# against the print, though the reasons given for them did not.
#
# Sec. 14 prints the two halves of a capital H with the arm at mid-height,
# \u22a2 and \u22a3, not the baseline "|_" / "_|" a previous reading reported, and says
# in as many words that the modern breathings "come from" them -- so folding
# them onto U+1FFE/U+1FBF would erase a derivation the sentence is drawing.
# Exact shape matches exist (U+22A2, U+22A3, or the box-drawing pair), but none
# is a Greek character, and half of Heta has no Greek encoding.
#
# [lins ] is not the acknowledged gap it was taken for: Sec. 2 a prints a
# definite narrow capital vee, the Old Attic lambda, and shows it standing at
# the lambda of BO\u2c65EI = \u03b2\u03bf\u03c5\u03bb\u1fc7 in the inscription that follows.  It stays
# unfixed because Unicode encodes no archaic letterform variant of lambda --
# unlike koppa, sampi, digamma and heta, which carry distinct values and are
# encoded -- not because the print leaves a hole.

# Wherever the Perseus transcription met a small mark it did not place on a
# letter, it typed an ASCII apostrophe, and the betacode-to-Unicode pass turned
# every one into U+1FBD GREEK KORONIS standing *after* the letter instead of a
# diacritic sitting *on* it.  Three unrelated marks hide behind that one
# character, so no single rule undoes it:
#
#   * a breathing, on the second vowel of a diphthong or on a lone vowel
#     (ει᾽ for εἰ, ου᾽ for οὐ, ε᾽ for the augment ἐ), including the coronis of
#     crasis (κει᾽ for κεἰ, χοι᾽ for χοἰ) -- 103 sites;
#   * the numeral keraia, throughout the numeral table of Sec. 347, where all
#     35 signs are affected (α᾽ for αʹ, ια᾽ for ιαʹ);
#   * an accent, at 3 sites: Sec. 1089 δη᾽ for δὴ, Sec. 1689 Δεκελεικου᾽ for
#     Δεκελεικοῦ, and Sec. 574 D, where the apostrophe took the acute of
#     ὄρνυμι and a stray ")" landed as its breathing.
#
# The same character is also the *correct* apostrophe at 32 further sites, listed
# under VOWEL_ELISIONS, so a blanket replacement would corrupt real text.
# Repairs are keyed to a whole Greek token, and to the printed section when one
# token has two readings.
#
# Rough cannot be told from smooth inside the file, because the apostrophe
# records neither, so every οι᾽ is read from its context and against the print:
# Sec. 274's is the stem οἰ- of οἶς (from ὀϝι-), and the paradigm beside it spells
# οἰ-ῶν, οἰ-σί; Sec. 1692 and 2196 quote the article οἱ.  Sec. 68 c, 326 and 779
# each print the contrasting breathings in one line (καὶ ἡ = χἠ; (ἐ)μο-, ἡμε-;
# ἐ-ἑ-μεν), so the collapse there loses a distinction the page is making.
KORONIS = "᾽"
# A middle dot counts as word-interior: the source drops one inside Sec. 1252's
# ἀλιτηρίους, and the repair has to see the whole word to take it out again.
GREEK_TOKEN_RE = re.compile(r"[̀-ͯͰ-Ͽἀ-῿]+(?:·[̀-ͯͰ-Ͽἀ-῿]+)*")
VOWEL_KORONIS_RE = re.compile(r"[αειουηωΑΕΙΟΥΗΩ][̀-ͯ]*᾽")
# Elision can leave a vowel exposed: διά loses its alpha, and so do the vocative
# Ἀντίνοε (Sec. 1011, Od. 2.310) and the neuter plural αἴτια (Sec. 1481).  The
# 1920 print carries a trailing apostrophe at three more such words, all in the
# Homeric notes on vowel quantity, where a mark on the vowel might have been
# expected instead: γέρα᾽ (Sec. 264 D), κλέα᾽ (Sec. 265 D), ἥρω᾽ (Sec. 267 D),
# each standing for the form with its second vowel lost.  Read off the scans at
# archive.org/details/greekgrammarforc0000herb and .../smyth-greek-grammar-for-
# colleges-1920, which agree; the betacode corroborates them as the only
# apostrophe-after-vowel words that already carry their accent.  All six stay.
VOWEL_ELISIONS = {
    "δι᾽",
    "Ἀντίνο᾽",
    "αἴτι᾽",
    "γέρα᾽",
    "κλέα᾽",
    "ἥρω᾽",
}
# Unambiguous whole tokens: no Greek word ends in a bare -ου or -ει that could
# then elide, so these readings do not depend on the section they sit in.
TOKEN_FIXES = {
    "ου᾽": "οὐ",
    "ει᾽": "εἰ",
    "αι᾽": "αἰ",  # the Aeolic and Doric form of εἰ, and αἰ(ϝ)ών in Sec. 861
    "κει᾽": "κεἰ",  # crasis, καὶ εἰ
    "κου᾽": "κοὐ",  # crasis, καὶ οὐ
    "χοι᾽": "χοἰ",  # crasis, καὶ οἱ
    "χη᾽": "χἠ",  # crasis, καὶ ἡ
}
# One-off sites, and tokens whose reading changes with the section.  Sec. 61's
# υ᾽ is the tail of an "ἦ ο" ligature holding ἦ οὐ (Il. 15.18); Sec. 2763's
# token also lost its elision apostrophe into a combining comma on the lambda,
# and the same sentence prints ἀλλ᾽ οὐδέ correctly two words earlier.
SECTION_FIXES = {
    (61, "υ᾽"): "ὐ",
    (274, "οι᾽"): "οἰ",
    (285, "ο᾽"): "ὀ",  # ὀ(υ̯)ατ-, the stem behind οὖς
    (326, "ε᾽"): "ἐ",  # (ἐ)με-, (ἐ)μο-
    (464, "η᾽"): "ἠ",  # ἦα for ἠ(σ)α
    (485, "ε᾽"): "ἐ",  # (ἐ)θέλω
    (549, "ε᾽"): "ἐ",  # (ἐ)κέκλετο
    (574, "ο᾽̓ρνυμι"): "ὄρνυμι",  # the apostrophe took the acute, ")" the breathing
    (779, "ε᾽"): "ἐ",  # the augment
    (885, "α᾽"): "ἀ",  # ἀ(ν)- privative
    (898, "α᾽"): "ἀ",  # ἀ(ν)-negative
    (1089, "δη᾽"): "δὴ",  # T. 3.17, ἐν τοῖς πλεῖσται δὴ νῆες
    (1252, "α᾽·λιτηρίους"): "ἀλιτηρίους",  # Lyc. 117; the print has no dot
    (1689, "Δεκελεικου᾽"): "Δεκελεικοῦ",  # D. 22.15
    (1692, "οι᾽"): "οἱ",
    (2196, "οι᾽"): "οἱ",
    (2283, "η᾽"): "ἠ",  # another form of εἰ, whence ἐά̄ν
    (2763, "ἀλλ̓ου᾽"): "ἀλλ᾽ οὐ",
}
# Sec. 347's table and Sec. 348's prose about it carry three further defects of
# the same kind as the koronis: a character that merely resembles the printed
# sign standing in for the sign itself.
#
#   * 6 and 16 print the obsolete sign stigma, ϛ; the source has plain sigma.
#     Sigma is *correct* at 200, so this cannot be keyed on the token -- only on
#     the numeral the row is for, which is why the table below is read off the
#     first cell of each row rather than off the Greek.
#   * 90 prints the archaic Q-shaped koppa, ϙ (U+03D9); the source has the
#     Z-shaped numeral koppa, ϟ (U+03DF).  Sec. 348 glosses it "in the same
#     order as Lat. q", which holds only of the Q-shape, so the printed
#     letterform is the one to keep.
#   * 90 and 900 are the only two signs the source leaves without a keraia,
#     which is why counting koronis finds 35 signs where the print has 37.
#
# Sec. 348's prose repeats the same three signs and adds a fourth defect: there
# the keraia survives as betacode's bare ASCII "#", the only four in the corpus.
# The psili family of spacing marks -- U+1FBF and the three that carry an accent
# with it -- strands 31 marks, and unlike the koronis these are not one shape but
# three, so the classification is again philological rather than mechanical:
#
#   * 15 sit before a capital vowel, often with a stray space, because Perseus
#     had no precomposed capital to put the breathing on (᾿ Αττικός for Ἀττικός).
#   * 6 sit after a vowel inside a word, where the breathing belongs on the vowel
#     they follow (ει᾿ς for εἰς, αυ᾿τοῦ for αὐτοῦ).
#   * 9 are correct as they stand: the mark of aphaeresis, where a word has lost
#     its own initial vowel and the apostrophe records it (μὴ ᾿νταῦθα, Sec. 76).
#
# What separates them is not the neighbouring letters.  Aphaeresis always
# precedes a consonant, but so does Sec. 333's "ε ᾿κείνη", where the mark belongs
# on the epsilon behind it; and a vowel stands before the mark in both Sec. 333
# and Sec. 76's "μὴ ᾿νταῦθα".  Hence a table.
#
# Each replacement below was computed from the mark's own decomposition -- the
# combining marks of U+1FBF, U+1FCD, U+1FCE and U+1FCF applied to the letter and
# renormalized -- and every one of the 21 agrees with an independent reading of
# the 1920 print, so the two derivations corroborate each other.
#
# Whitespace inside a key matches any run of whitespace, because the source
# breaks several of these across a line.
# The spacing accents are a different defect with the same look.  Here the
# betacode is *correct* -- lo/gois, a)kou/w, pro\\s, kai\\ -- so nothing was
# mis-keyed; the betacode-to-Unicode pass simply failed to compose these 30
# accents and left them standing after their letter, where NFC turns U+1FFD
# GREEK OXIA into U+00B4 and U+1FEF GREEK VARIA into U+0060.  Position is
# therefore reliable and the repair is a rule, not a table: the accent belongs
# on the letter it follows.
#
# Two guards.  A Greek accent only ever sits on a vowel, which excludes
# Sec. 2578's "ὁρῶ ς` νοσεῖς", where the betacode itself reads "s\\" -- a
# mis-keyed letter, not a stranded mark, and one for the print to settle.  And
# the letter has to be Greek, which leaves the nine spacing acutes of the
# Sanskrit transliterations (bhā´mi, mā´, tvē´) alone, along with three that
# follow Perseus's own "<*>" gap marker and belong to the letter inside the gap.
SPACING_ACCENTS = {"´": "\u0301", "`": "\u0300"}
# One stranded accent falls across an element boundary: Sec. 503 splits "-εο"
# and "´ε-" into two spans, so neither node holds both the accent and the vowel
# it belongs to.  The betacode's parallel in the same sentence -- "eu" + "o/e-"
# for ευόε- -- fixes the reading as -εόε-, and the two nodes are corrected
# together.
SPLIT_ACCENT_FIXES = {
    (503, "-εο"): "-εό",
    (503, "´ε-"): "ε-",
}
STRANDED_ACCENT_RE = re.compile(r"(.)([´`])")
GREEK_VOWELS = "αειουηωΑΕΙΟΥΗΩ"
# Aphaeresis and elision are the same apostrophe doing the same work -- marking
# a vowel lost, at the front of a word or the back of one -- so the corpus
# spells both U+1FBD.  The nine that survive the psili table above are all
# aphaeresis, and this is what makes them uniform with the elisions around them.
APHAERESIS_MARK = "\u1fbf"

# What these repairs deliberately do NOT do.  The print sometimes carries a mark
# the source lacks -- chiefly the macron of a long vowel, as at Sec. 574 D, where
# the print reads ὄρνῡμι and the source ὄρνυμι.  Supplying them is tempting and
# wrong, because Smyth's own printing is inconsistent: Sec. 948 sets ἐὰν and ἐὰ̄ν
# four lines apart, Sec. 2016 νῑκᾶν beside νικᾶν in one clause.  The source is
# faithfully reproducing an irregular page.  Every repair above corrects a
# transmission error and restores something the page plainly shows; supplying an
# omitted mark would instead improve on the page, which is emendation, and
# belongs in a separate and visible layer if it is ever wanted.  Roughly 20-50
# sites, ruled out of scope 2026-08-04.

SPACING_PSILI_FIXES = {
    (78, "᾿ Αττικός"): "Ἀττικός",
    (81, "᾿ Ατθίς"): "Ἀτθίς",
    (81, "᾿ Οδυσεύς"): "Ὀδυσεύς",
    (81, "᾿ Οδυσσεύς"): "Ὀδυσσεύς",
    (81, "᾿ Αχιλεύς"): "Ἀχιλεύς",
    (81, "᾿ Αχιλλεύς"): "Ἀχιλλεύς",
    (83, "᾿ Αττικός"): "Ἀττικός",
    (83, "᾿ Ατθίς"): "Ἀτθίς",
    (105, "῎ Ερεβος"): "Ἔρεβος",
    (106, "᾿ Αθήναζε"): "Ἀθήναζε",
    (106, "᾿ Αθήνασ-δε"): "Ἀθήνασ-δε",
    (134, "᾿ Αθήνησιν"): "Ἀθήνησιν",
    (148, "᾿ Οδυσῆι"): "Ὀδυσῆι",
    (2428, "῎ Ολυνθον"): "Ὄλυνθον",
    (2552, "῎ Αλκηστις"): "Ἄλκηστις",
    (333, "ε ᾿κείνη"): "ἐκείνη",
    (383, "ει῏μεν"): "εἶμεν",
    (1199, "αυ᾿τοῦ"): "αὐτοῦ",
    (1603, "ει᾿ς"): "εἰς",
    (1689, "η῍ ἐπὶ"): "ἢ ἐπὶ",
    (2315, "αι᾿τιᾶσθαι"): "αἰτιᾶσθαι",
}
# The nine aphaeresis marks stay.  Four of them carry a stray space as well,
# where the print sets the mark tight against the word it has docked onto.
APHAERESIS_SPACING_FIXES = {
    (76, "᾿ νταῦθα"): "᾿νταῦθα",
    (76, "᾿ μέ"): "᾿μέ",
    (76, "᾿ μαυτόν"): "᾿μαυτόν",
    (76, "᾿ ξῆλθεν"): "᾿ξῆλθεν",
}
NUMERAL_SIGN_FIXES = {"6": "ϛʹ", "16": "ιϛʹ", "90": "ϙʹ", "900": "ϡʹ"}
NUMERAL_MARK = "#"
# Substring-keyed: this koppa sits untagged in the English prose, so the
# surrounding words are available to pin it down.
NUMERAL_PROSE_FIXES = {(348, "6; ϟ ("): "6; ϙ ("}
# Whole-node-keyed: this sigma is a text node holding nothing else, and a bare
# "ς" as a substring would rewrite the final sigma of every word around it.
NUMERAL_NODE_FIXES = {(348, "ς"): "ϛ"}
# Sec. 347 prints the alphabetic numerals; every koronis in it is a keraia.
KERAIA_SECTION = 347
KERAIA = unicodedata.normalize("NFC", "ʹ")

# Six more placeholder characters hide in the source for the same reason as
# the koronis: Perseus typed a spacing mark wherever it could not put a real
# combining diacritic on a letter, or (in two cases) used a spacing mark as
# running notation rather than a diacritic at all. Each table below is a
# closed, hand-audited enumeration -- every source occurrence of the mark in
# question was surveyed, cross-checked against the 1920 print scan and the
# independent Perseus/neelsmith betacode sources, and classified. Section
# numbers are the printed Smyth section the token belongs to.
DASIA = "\u1ffe"  # GREEK DASIA, spacing rough breathing
DASIA_OXIA = "\u1fde"  # GREEK DASIA AND OXIA, spacing rough breathing + acute
DASIA_PERISPOMENI = "\u1fdf"  # GREEK DASIA AND PERISPOMENI, rough breathing + circumflex
PERISPOMENI = "\u1fc0"  # GREEK PERISPOMENI, spacing circumflex
DIAERESIS_SPACING = "\u00a8"  # DIAERESIS, standing alone rather than combining
MIDDLE_DOT = "\u00b7"

DASIA_FIXES = {
    (26, "\u1ffe\u1ff7"): "\u1fa7",
    (149, "\u1ffe \u0395\u03bb\u03bb\u03ac\u03b4\u03bf\u03c2"): "\u1f19\u03bb\u03bb\u03ac\u03b4\u03bf\u03c2",
    (1178, "\u03bf\u03c5\u1ffe\u03c4\u03bf\u03c3\u03af\u0304"): "\u03bf\u1f51\u03c4\u03bf\u03c3\u03af\u0304",
    (2977, "\u1ffe\u03c4\u1f14"): "(\u03c4\u03ad)",
    # This site's section_of() lookup lands on 3048 by the bisect fallback,
    # not a real ancestor: the text sits in the Part V verb appendix (a
    # rhegnymi stem note), outside every numbered smythp div, so it never
    # reaches a section record -- only verbs.json, via build_landmarks.py's
    # own call to this same function. 3048 is simply whatever section_of()
    # actually returns for this element; keep it as the key even though the
    # printed section 3048 (Zeugma) has nothing to do with this text.
    (3048, "\u03c1\u1ffe\u03c9\u03b3-"): "\u1fe5\u03c9\u03b3-",
}

CAPITAL_ACCENT_FIXES = {
    (152, "\u1fde \u0391\u03b9\u03b4\u03b7\u03c2"): "\u1f0d\u03b9\u03b4\u03b7\u03c2",
    (153, "\u1fde \u039f\u03bc\u03b7\u03c1\u03bf\u03c2"): "\u1f4d\u03bc\u03b7\u03c1\u03bf\u03c2",
    (153, "\u1fdf \u03a9\u03c1\u03b1\u03b9"): "\u1f6f\u03c1\u03b1\u03b9",
    (2225, "\u1fde \u0395\u03bb\u03bb\u03b7\u03bd\u03b5\u03c2"): "\u1f1d\u03bb\u03bb\u03b7\u03bd\u03b5\u03c2",
    (2511, "<*>\u1fde"): "\u1f45",
    (2532, "\u03bf\u03b9\u1fdf\u03bf\u03b9"): "\u03bf\u1f37\u03bf\u03b9",
}

PERISPOMENI_FIXES = {
    (401, "-\u03b7, \u1fc0\u03bf\u03bd"): "-\u03b7, -\u03bf\u03bd",
    (759, "\u03c3\u03c4\u03b7\u1fc0-\u03b8\u03b9"): "\u03c3\u03c4\u1fc6-\u03b8\u03b9",
    (1066, "\u03bc\u03b1\u1fc0\u03bb\u03bb\u03bf\u03bd"): "\u03bc\u1fb6\u03bb\u03bb\u03bf\u03bd",
    (2725, "\u03b5\u1f30\u1fc0\u03bd\u03b1\u03af"): "\u03b5\u1f36\u03bd\u03b1\u03af",
    # Like 2511 above, the "<*>" here is Perseus's own gap marker, not
    # something this pass introduced; the print (p. 625: "\u03bf\u1f50\u03c7 \u03bf\u1f37\u03cc\u03bd \u03c4\u1fbd \u03b5\u1f36\u03bd\u03b1\u03b9")
    # and the betacode ("oi<*>=o/n", circumflex attached where the gap sits)
    # agree the missing content is a rough breathing on this iota, so it
    # composes here too rather than leaving the placeholder stranded.
    (2749, "\u03bf\u03b9<*>\u1fc0\u03cc\u03bd"): "\u03bf\u1f37\u03cc\u03bd",
    (2796, "\u03c4\u03b1\u03b9\u1fc0\u03c2"): "\u03c4\u03b1\u1fd6\u03c2",
}

DIAERESIS_TARGET = "+"

MIDDOT_FIXES = {
    (750, "\u03b9\u00b7\u03c3\u03c4\u03ac-\u03b9\u03b5-\u03bd"): "\u1f31\u03c3\u03c4\u03b1-\u1fd6\u03b5-\u03bd",
    (845, "\u00b7\u03b9\u03b4"): "\u03b9\u03b4",
    (1074, "\u03b9\u00b7\u03c0\u03c0\u03ad\u1fb1\u03c2"): "\u1f31\u03c0\u03c0\u03ad\u1fb1\u03c2",
    (1145, "\u03b7\u00b7\u0300"): "\u1f22",
    (1201, "\u03bf\u00b7\u03c1\u1fb7"): "\u1f41\u03c1\u1fb7",
    (1322, "\u03b1\u00b7\u0300"): "\u1f03",
}

STAR_FIXES = {
    (2, "*\u03c3"): "\u03a3",
    (3018, "*\u1fbf\u03b1"): "\u1f08",
}

PROSE_FIXES = {
    (2282, "(and Doric' form"): "(and Doric) form",
}

# Perseus typed a LATIN combining circumflex (U+0302) at eight sites where a
# Greek mark belongs.  Every one is now repaired against the 1920 print (the
# archive.org scan, greekgrammarforc0000herb) with the Perseus betacode read
# alongside it; the betacode names the slip in each case, and the print says
# what the page actually sets.  Only Sec. 305 involves a macron.
#
# Sec. 305 sits in the ἄκων paradigm: the neuter is spelled smooth + U+0302 +
# macron, and the Latin circumflex standing between the letter and the macron
# hides the site from the restack rule below (the character before U+0304 is
# not a Greek letter).  Repaired here by table -- the perispomeni is Greek and
# the macron goes innermost -- so the neuter matches its restacked neighbors
# ᾱ̓́κων, ᾱ̓́κουσα.
#
# The other seven are one defect family: the Latin circumflex marks the spot
# where the transcriber could not set a Greek mark on the letter it belongs to,
# and whatever was typed instead stayed on the page beside it.
#   1087 o(=ios     both marks on the omicron; the same line spells οἷα
#                   correctly (oi(=a), so the convention is the neighbour's
#   1195 oi/=       an acute typed where the rough breathing belongs; Homeric
#                   οἷ, the orthotone pronoun the section is about
#   1369 u(/o=atos  a mis-keyed LETTER, not a mark: the print reads ὕδατος in
#                   ἡ πηγὴ ῥεῖ ψῡχροῦ ὕδατος (P. Phae. 230b)
#   1973 ei/=nai    an acute typed where the smooth breathing belongs
#   2172 oi)kou=|si a stray ypogegrammeni; the print sets οἰκοῦσι plain, and
#                   the subscript two words later belongs to μιᾷ
#   2747 o(=o/n     both marks on the omicron AND the iota dropped; the print
#                   sets four letters, οἷόν, as Sec. 2749 does two sections on
#   2806 fronw\=    a grave typed beside the circumflex; the print sets φρονῶ,
#                   matching φιλῶ three words later in the same verse
LATIN_CIRCUMFLEX_FIXES = {
    (305, "ἀ̂̄κον"): "ᾱ̓͂κον",
    (1087, "ὁ̂ιος"): "οἷος",
    (1195, "οί̂"): "οἷ",
    (1369, "ὕο̂ατος"): "ὕδατος",
    (1973, "εί̂ναι"): "εἶναι",
    (2172, "οἰκου̂ͅσι"): "οἰκοῦσι",
    (2747, "ὁ̂όν"): "οἷόν",
    (2806, "φρονὼ̂"): "φρονῶ",
}

# The source stacks every combining macron OUTERMOST: a precomposed accented or
# breathing-bearing vowel with U+0304 on top (φύ̄ω, ὑ̄μέτερος, ἵ̄ -- 3,226
# tree sites).  The print sets the macron against the letter with breathing and
# accent above it, and the two spellings are not canonically equivalent (the
# macron and the accents all carry combining class 230, which Unicode
# normalization never reorders), so left as-is the corpus's φύ̄ω would never
# match the index's φῡ́ω.  Restacked innermost as the print stacks them: the
# macron-precomposed base where one exists (ᾱ ῑ ῡ and capitals), else the bare
# vowel keeping a combining macron (ε η ο have no precomposed long form), with
# the letter's other marks following in their canonical breathing-before-accent
# order.  This is the same rule the index data already applies, adopted there
# 2026-08-03 from the index pages of the same print.
#
# One subclass is left alone: breve and macron together (ῐ̄, ῠ̄ -- Sec. 607's
# "verb-stems ending in ῐ̄, ῠ̄", δεικνῠ̄-, and 17 more) is Smyth's mark for a
# vowel that scans short or long.  Both marks are genuinely printed, so neither
# is a transmission error; which of the two sits closer to the letter is a
# print question no one has re-read yet, and reordering them would change the
# rendered stack.  The tally keeps them countable.
#
# A second subclass is left alone for a different reason: iota subscript
# (ypogegrammeni, U+0345) carries combining class 240, above the macron's 230,
# so a subscript-bearing vowel restacked innermost (e.g. ῃ̄ -> η + macron +
# ypogegrammeni) is canonically equivalent to the untouched spelling -- Unicode
# composes straight through the intervening macron either way.  Restacking
# would only trade one NFC string for a differently-ordered string that
# normalizes right back to it, denormalizing the corpus for no printed
# difference.  Left as the source has it; the tally keeps these countable too.
MACRON = "̄"
BREVE = "̆"
STACKED_MACRON_RE = re.compile(r"([Ͱ-Ͽἀ-῿])̄")


def norm(text: str | None) -> str:
    """Collapse source formatting whitespace without changing other text."""
    return re.sub(r"\s+", " ", text or "").strip()


# The file has been through an XML pretty-printer, which puts a child element on
# its own indented line.  Collapsing that indentation to a space -- as any plain
# `"".join(elem.itertext())` does -- prints spaces the edition does not have:
# `ᾰ : as a in Germ. hat` for `ᾰ: as a`, `stem τελεσ- )` for `stem τελεσ-)`,
# `η ( ᾱ after ε, ι, ρ, 31)` for `η (ᾱ after`.  The same defect in the table
# extraction was sending John questions whose answer the witness already held
# (work/tables/FINDING-tei-whitespace.md).
#
# Indentation is layout in exactly two places: before an element's first child,
# and before its closing tag.  Whitespace BETWEEN siblings is the word space the
# edition typed -- `<emph>a.</emph>\n<foreign>ε</foreign>` is `a. ε`, not `a.ε`
# -- and every other whitespace run, including a newline standing where a space
# was typed, still collapses to one space.
def is_layout_space(text: str | None) -> bool:
    return bool(text) and text.strip() == "" and "\n" in text


def lead_text(elem: ET.Element) -> str:
    """``elem.text``, minus the indentation before its first child."""
    if len(elem) and is_layout_space(elem.text):
        return ""
    return elem.text or ""


def tail_text(elem: ET.Element, index: int) -> str:
    """The tail of child ``index``, minus indentation before the parent's close."""
    child = elem[index]
    if index == len(elem) - 1 and is_layout_space(child.tail):
        return ""
    return child.tail or ""


def all_text(elem: ET.Element) -> str:
    """``itertext`` with the pretty-printer's layout whitespace dropped."""
    parts = [lead_text(elem)]
    for index, child in enumerate(elem):
        parts.append(all_text(child))
        parts.append(tail_text(elem, index))
    return "".join(parts)


def json_line(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def section_parts(elem: ET.Element) -> tuple[int, str]:
    match = SECTION_RE.match(elem.get("n", ""))
    if not match:
        raise ValueError(f"invalid smythp n attribute: {elem.get('n')!r}")
    return int(match.group(1)), match.group(2).strip()


def is_base_section(elem: ET.Element) -> bool:
    return elem.get("type") == "smythp" and section_parts(elem)[1] == ""


def text_of(elem: ET.Element) -> str:
    return norm(all_text(elem))


def nearest_smythp(
    elem: ET.Element, parents: dict[ET.Element, ET.Element]
) -> ET.Element | None:
    current: ET.Element | None = elem
    while current is not None:
        if current.get("type") == "smythp":
            return current
        current = parents.get(current)
    return None


def repair_marks(
    root: ET.Element, parents: dict[ET.Element, ET.Element]
) -> dict[str, object]:
    """Put the source's stranded marks back onto their letters.

    Rewrites text in place and returns a tally for meta, listing every koronis
    token left alone, so that a token this converter has never classified
    shows up as a report line rather than as silent corruption.  The other
    six mark classes are closed, hand-audited enumerations (see the tables
    above), so they need no such catch-all: every source occurrence is either
    a table entry or, for the two bulk notation sweeps, an intentional
    blanket replacement.
    """
    composed = 0
    restored = 0
    elisions = 0
    unclassified: collections.Counter[tuple[int | None, str]] = collections.Counter()
    dasia_composed = 0
    capital_accent_composed = 0
    perispomeni_composed = 0
    perispomeni_notation = 0
    diaeresis_notation = 0
    middot_composed = 0
    star_composed = 0
    prose_fixed = 0
    numeral_prose_fixed = 0
    numeral_marks = 0
    psili_composed = 0
    aphaeresis_tightened = 0
    accents_composed = 0
    aphaeresis_unified = 0
    split_accent_nodes = 0
    latin_circumflex_fixed = 0

    # The preposition list of Sec. 1685-1692 puts its examples in structural
    # divs between numbered siblings, so some text has no smythp ancestor at
    # all.  Such text belongs to the prior printed section, the same rule
    # supplemental_blocks applies later.
    positions = {elem: index for index, elem in enumerate(root.iter())}
    markers = sorted(
        (positions[elem], section_parts(elem)[0])
        for elem in positions
        if elem.get("type") == "smythp"
    )
    marker_offsets = [offset for offset, _ in markers]

    def section_of(elem: ET.Element | None) -> int | None:
        if elem is None:
            return None
        owner = nearest_smythp(elem, parents)
        if owner is not None:
            return section_parts(owner)[0]
        place = bisect.bisect_right(marker_offsets, positions[elem]) - 1
        return markers[place][1] if place >= 0 else None

    def apply_one_off(
        value: str,
        number: int | None,
        table: dict[tuple[int, str], str],
    ) -> tuple[str, int]:
        """Apply every table entry whose section matches, tallying hits."""
        hits = 0
        for (section, old), new in table.items():
            if section == number and old in value:
                value = value.replace(old, new)
                hits += 1
        return value, hits

    def apply_flexible(
        value: str,
        number: int | None,
        table: dict[tuple[int, str], str],
    ) -> tuple[str, int]:
        """Like apply_one_off, but a space in the key matches any whitespace."""
        hits = 0
        for (section, old), new in table.items():
            if section != number:
                continue
            pattern = r"\s+".join(re.escape(part) for part in old.split(" "))
            # A function replacement, so nothing in the Greek is read as a
            # backreference.
            value, count = re.subn(pattern, lambda _, new=new: new, value)
            hits += count
        return value, hits

    def apply_node(
        value: str,
        number: int | None,
        table: dict[tuple[int, str], str],
    ) -> tuple[str, int]:
        """Fix a text node holding nothing but the key.

        Needed where the key is too short to match as a substring safely -- a
        bare "ς" would otherwise rewrite the final sigma of every word near it.
        """
        hits = 0
        for (section, old), new in table.items():
            if section == number and value.strip() == old:
                value = value.replace(old, new)
                hits += 1
        return value, hits

    def repair(value: str, number: int | None) -> str:
        nonlocal composed, restored, elisions
        nonlocal dasia_composed, capital_accent_composed, perispomeni_composed
        nonlocal perispomeni_notation, diaeresis_notation, middot_composed
        nonlocal star_composed, prose_fixed
        nonlocal numeral_prose_fixed, numeral_marks
        nonlocal psili_composed, aphaeresis_tightened
        nonlocal accents_composed, aphaeresis_unified, split_accent_nodes
        nonlocal latin_circumflex_fixed

        # One-off section-keyed fixes run first, so their marks never reach
        # the blanket sweeps below.
        value, hits = apply_one_off(value, number, DASIA_FIXES)
        dasia_composed += hits
        value, hits = apply_one_off(value, number, CAPITAL_ACCENT_FIXES)
        capital_accent_composed += hits
        value, hits = apply_one_off(value, number, PERISPOMENI_FIXES)
        perispomeni_composed += hits
        value, hits = apply_one_off(value, number, MIDDOT_FIXES)
        middot_composed += hits
        value, hits = apply_one_off(value, number, STAR_FIXES)
        star_composed += hits
        value, hits = apply_one_off(value, number, PROSE_FIXES)
        prose_fixed += hits
        value, hits = apply_one_off(value, number, LATIN_CIRCUMFLEX_FIXES)
        latin_circumflex_fixed += hits

        value, hits = apply_flexible(value, number, SPACING_PSILI_FIXES)
        psili_composed += hits
        value, hits = apply_flexible(value, number, APHAERESIS_SPACING_FIXES)
        aphaeresis_tightened += hits

        value, hits = apply_one_off(value, number, NUMERAL_PROSE_FIXES)
        numeral_prose_fixed += hits
        value, hits = apply_node(value, number, NUMERAL_NODE_FIXES)
        numeral_prose_fixed += hits
        # Two node edits for one accent, so this keeps its own tally rather
        # than inflating the count of accents composed.
        value, hits = apply_node(value, number, SPLIT_ACCENT_FIXES)
        split_accent_nodes += hits

        # Betacode's keraia, never converted; all four sit in Sec. 348.
        if NUMERAL_MARK in value:
            numeral_marks += value.count(NUMERAL_MARK)
            value = value.replace(NUMERAL_MARK, KERAIA)

        # The remaining PERISPOMENI/DIAERESIS instances are Smyth's own
        # "becomes" / "+" notation, not diacritics; see the tables above.
        if PERISPOMENI in value:
            perispomeni_notation += value.count(PERISPOMENI)
            value = value.replace(PERISPOMENI, "=")
        if DIAERESIS_SPACING in value:
            diaeresis_notation += value.count(DIAERESIS_SPACING)
            value = value.replace(DIAERESIS_SPACING, DIAERESIS_TARGET)

        def compose_accent(match: re.Match[str]) -> str:
            nonlocal accents_composed
            letter, mark = match.group(1), match.group(2)
            if unicodedata.normalize("NFD", letter)[:1] not in GREEK_VOWELS:
                return match.group()
            accents_composed += 1
            return unicodedata.normalize("NFC", letter + SPACING_ACCENTS[mark])

        value = STRANDED_ACCENT_RE.sub(compose_accent, value)

        # After the psili table above, every U+1FBF still standing is an
        # aphaeresis mark, and takes the same U+1FBD the elisions use.
        if APHAERESIS_MARK in value:
            aphaeresis_unified += value.count(APHAERESIS_MARK)
            value = value.replace(APHAERESIS_MARK, KORONIS)

        if KORONIS not in value:
            return value
        if number == KERAIA_SECTION:
            restored += value.count(KORONIS)
            return value.replace(KORONIS, KERAIA)

        def repair_token(match: re.Match[str]) -> str:
            # Substituting on the match keeps each word's repair inside that
            # word: a plain replace would also rewrite the ου᾽ that sits inside
            # Δεκελεικου᾽, and which word went first would depend on set order.
            nonlocal composed, elisions
            token = match.group()
            # A koronis after a consonant is an ordinary elision (δ᾽, ἀλλ᾽).
            # The test runs on the decomposed token so that an accented vowel
            # counts whichever way the source happened to spell it.
            if not VOWEL_KORONIS_RE.search(unicodedata.normalize("NFD", token)):
                return token
            fixed = SECTION_FIXES.get((number, token), TOKEN_FIXES.get(token))
            if fixed is not None:
                composed += 1
                return fixed
            if token in VOWEL_ELISIONS:
                elisions += 1
            else:
                unclassified[(number, token)] += 1
            return token

        return GREEK_TOKEN_RE.sub(repair_token, value)

    for elem in root.iter():
        if elem.text:
            elem.text = repair(elem.text, section_of(elem))
        if elem.tail:
            # A tail sits in the parent's run of text, not inside the element.
            elem.tail = repair(elem.tail, section_of(parents.get(elem)))
    return {
        "koronisComposed": composed,
        "keraiaRestored": restored,
        "koronisKeptAsElision": elisions,
        "koronisUnclassified": [
            {"section": number, "token": token, "count": count}
            for (number, token), count in sorted(
                unclassified.items(), key=lambda item: (item[0][0] or 0, item[0][1])
            )
        ],
        "dasiaComposed": dasia_composed,
        "capitalAccentComposed": capital_accent_composed,
        "perispomeniComposed": perispomeni_composed,
        "perispomeniNotation": perispomeni_notation,
        "diaeresisNotation": diaeresis_notation,
        "middotComposed": middot_composed,
        "starComposed": star_composed,
        "proseFixed": prose_fixed,
        "numeralProseFixed": numeral_prose_fixed,
        "numeralMarksRestored": numeral_marks,
        "psiliComposed": psili_composed,
        "aphaeresisTightened": aphaeresis_tightened,
        "accentsComposed": accents_composed,
        "splitAccentNodes": split_accent_nodes,
        "aphaeresisUnified": aphaeresis_unified,
        "latinCircumflexFixed": latin_circumflex_fixed,
    }


def repair_numeral_signs(root: ET.Element) -> int:
    """Correct Sec. 347's sign column, keyed on the numeral each row is for.

    The sign lives in the second cell of a row whose first cell is the printed
    value, and reading it that way is the only way to tell the sigma that is
    wrong at 6 from the sigma that is right at 200.
    """
    fixed = 0
    for div in root.iter():
        if div.get("type") != "smythp" or section_parts(div)[0] != KERAIA_SECTION:
            continue
        for row in div.iter("row"):
            cells = list(row.iter("cell"))
            if len(cells) < 2:
                continue
            wanted = NUMERAL_SIGN_FIXES.get(norm("".join(cells[0].itertext())))
            if wanted is None:
                continue
            # The sign sits in a bold emph inside a foreign span; if the source
            # ever drops the emph, the cell itself is the next best target.
            holder = next(iter(cells[1].iter("emph")), cells[1])
            holder.text = wanted
            for child in list(holder):
                holder.remove(child)
            fixed += 1
    return fixed


def restack_macron_text(text: str, tally: dict[str, int]) -> str:
    """Move each combining macron in `text` innermost, tallying into `tally`.

    The rule and its two deliberately-kept subclasses (breve+macron anceps,
    NFC-equivalent ypogegrammeni sites) live in the comment above
    STACKED_MACRON_RE.  Shared by every converter whose source inherits the
    same outer-macron stacking, so the rule is defined once and applied
    identically everywhere it is needed.
    """

    def restack(match: re.Match[str]) -> str:
        letter = match.group(1)
        parts = unicodedata.normalize("NFD", letter)
        base, marks = parts[0], parts[1:]
        # A bare vowel with a macron is already innermost (and NFC at the door
        # already composed it wherever a precomposed form exists, so this is
        # ἄλλο̄ς-class notation on ε, η, ο).  A consonant never takes one.
        if base not in GREEK_VOWELS or not marks:
            return match.group()
        if BREVE in marks:
            tally["ancepsMacronsKept"] = tally.get("ancepsMacronsKept", 0) + 1
            return match.group()
        candidate = unicodedata.normalize("NFC", base + MACRON) + marks
        if unicodedata.normalize("NFC", candidate) == unicodedata.normalize("NFC", match.group()):
            tally["subscriptMacronsKept"] = tally.get("subscriptMacronsKept", 0) + 1
            return match.group()
        tally["macronsRestacked"] = tally.get("macronsRestacked", 0) + 1
        return candidate

    return STACKED_MACRON_RE.sub(restack, text)


def restack_macrons(root: ET.Element) -> dict[str, int]:
    """Move each combining macron innermost, under breathing and accent.

    Runs over the whole tree after every other repair, so that repaired output
    (DASIA_FIXES restores Sec. 1178's οὑτοσί̄ with the source's outer macron)
    is restacked along with the rest.
    """
    tally = {"macronsRestacked": 0, "ancepsMacronsKept": 0, "subscriptMacronsKept": 0}
    for elem in root.iter():
        if elem.text:
            elem.text = restack_macron_text(elem.text, tally)
        if elem.tail:
            elem.tail = restack_macron_text(elem.tail, tally)
    return tally


def first_head(elem: ET.Element) -> str | None:
    for child in elem:
        if child.tag == "head":
            value = text_of(child)
            return value or None
    return None


def ancestor_path(
    elem: ET.Element, parents: dict[ET.Element, ET.Element]
) -> list[str]:
    path: list[str] = []
    current = parents.get(elem)
    while current is not None:
        if DIV_RE.fullmatch(current.tag) and current.get("type") != "smythp":
            head = first_head(current)
            if head:
                path.append(head)
        current = parents.get(current)
    path.reverse()
    return path


def dotless_label(container: ET.Element) -> ET.Element | None:
    """Return a bold single-letter emph opening the container, if any.

    The source drops the dot from one printed label ("b Objects already
    mentioned", 1120).  Requiring the bold emph keeps plain prose such as
    "a spurious diphthong" from becoming an anchor.
    """
    if norm(container.text):
        return None
    for child in container:
        if (
            child.tag == "emph"
            and child.get("rend") == "bold"
            and re.fullmatch(r"[a-z]", text_of(child))
        ):
            return child
        return None
    return None


def find_letter_markers(
    base: ET.Element,
) -> tuple[list[str], dict[ET.Element, str]]:
    """Find printed lower-case subsection labels in source order.

    Labels at the start of paragraphs or cells become anchors.  A printed
    numeric parent such as ``1. a.`` becomes ``a1``.  The numeric parent stays
    in force for following letters in the same numbered group.  An ``a.`` may
    also follow lead-in prose when LEADIN_TOKEN_RE accepts the word before it,
    and a bold single letter without a dot opening a paragraph is a label with
    the dot dropped in the source.  If the source repeats a bare label in a
    table, only its first occurrence owns the anchor.
    """
    letters: list[str] = []
    markers: dict[ET.Element, str] = {}
    current_number = ""

    for container in base.iter():
        if container.tag not in {"p", "cell"}:
            continue
        visible = text_of(container)
        letter = ""
        forced_marker: ET.Element | None = None
        match = LETTER_START_RE.match(visible)
        if match:
            if match.group(1):
                current_number = match.group(1)
            letter = match.group(2)
        else:
            leadin = LETTER_LEADIN_RE.match(visible)
            token = leadin.group(1) if leadin else ""
            if (
                LEADIN_TOKEN_RE.fullmatch(token)
                and re.search(r"[a-z]", token)
                and len(re.findall(r"[^\W\d_]", token)) >= 2
            ):
                letter = "a"
            else:
                forced_marker = dotless_label(container)
                if forced_marker is not None:
                    letter = text_of(forced_marker)
        if not letter:
            continue
        anchor = f"{letter}{current_number}"
        if anchor in letters:
            continue

        marker = forced_marker
        if marker is None:
            for candidate in container.iter("emph"):
                if candidate.get("rend") != "bold":
                    continue
                label = text_of(candidate)
                direct = re.match(
                    rf"^(?:{re.escape(current_number)}\.\s*)?{letter}\.", label
                )
                heading = re.search(rf"\u2014{letter}\.$", label)
                if direct or heading:
                    marker = candidate
                    break
        if marker is None:
            marker = container
        letters.append(anchor)
        markers[marker] = anchor
    return letters, markers


def parse_ref(elem: ET.Element) -> tuple[int | None, tuple[int, int] | None]:
    value = elem.get("target") or elem.get("n") or text_of(elem)
    target_match = re.search(r"\d+", value)
    target = int(target_match.group()) if target_match else None
    range_match = RANGE_RE.search(text_of(elem))
    found_range = (
        (int(range_match.group(1)), int(range_match.group(2)))
        if range_match
        else None
    )
    return target, found_range


def ref_letter(elem: ET.Element) -> tuple[int, str] | None:
    """Read a ``2326 d`` style cross-reference into its section and anchor.

    A bare ``f.`` is the print abbreviation for "and following", not a letter.
    """
    match = re.fullmatch(r"\s*(\d+)\s+([a-z])\.?\s*", elem.get("n", ""))
    if not match or match.group(2) == "f":
        return None
    return int(match.group(1)), match.group(2)


def find_ref_ranges(
    root: ET.Element,
) -> tuple[list[dict[str, int]], dict[ET.Element, list[dict[str, int]]]]:
    """Find ranges inside refs, across two refs, or in a ref's tail."""
    all_ranges: list[dict[str, int]] = []
    by_ref: dict[ET.Element, list[dict[str, int]]] = collections.defaultdict(list)

    def add(ref: ET.Element, start: int | None, end: int | None) -> None:
        if start is None or end is None:
            return
        value = {"start": start, "end": end}
        if value not in by_ref[ref]:
            by_ref[ref].append(value)
        if value not in all_ranges:
            all_ranges.append(value)

    for parent in root.iter():
        children = list(parent)
        for index, child in enumerate(children):
            if child.tag != "ref":
                continue
            start, inside = parse_ref(child)
            if inside:
                add(child, inside[0], inside[1])
            tail = child.tail or ""
            plain_end = re.match(r"\s*[-\u2013\u2014]\s*(\d+)", tail)
            if plain_end:
                add(child, start, int(plain_end.group(1)))
                continue
            if (
                re.match(r"\s*[-\u2013\u2014]\s*$", tail)
                and index + 1 < len(children)
                and children[index + 1].tag == "ref"
            ):
                end, _ = parse_ref(children[index + 1])
                add(child, start, end)
    return all_ranges, by_ref


class Renderer:
    """Small, explicit TEI-to-HTML renderer with no source attributes leaked."""

    def __init__(self, letter_markers: dict[ET.Element, str]) -> None:
        self.letter_markers = letter_markers
        self.footnote = 0

    @staticmethod
    def _text(value: str | None, in_greek: bool = False) -> str:
        if not value:
            return ""
        escaped = html.escape(re.sub(r"\s+", " ", value), quote=False)
        if in_greek:
            return escaped
        return GREEK_RUN_RE.sub(lambda match: f'<span lang="grc">{match.group()}</span>', escaped)

    def inner(self, elem: ET.Element, in_greek: bool = False) -> str:
        chunks = [self._text(lead_text(elem), in_greek)]
        for index, child in enumerate(elem):
            chunks.append(self.element(child, in_greek))
            chunks.append(self._text(tail_text(elem, index), in_greek))
        return "".join(chunks)

    def element(self, elem: ET.Element, in_greek: bool = False) -> str:
        tag = elem.tag
        is_greek = tag in {"foreign", "quote"} and elem.get("lang", "").lower() in {
            "greek",
            "grc",
        }
        anchor = self.letter_markers.get(elem)
        anchor_attr = f' id="{html.escape(anchor, quote=True)}"' if anchor else ""

        if tag == "p":
            return self.paragraph(elem, in_greek or is_greek, anchor_attr)
        if tag == "table":
            return self.table(elem, in_greek or is_greek, anchor_attr)

        content = self.inner(elem, in_greek or is_greek)
        if tag == "foreign":
            language = elem.get("lang", "").lower()
            if language in {"greek", "grc"}:
                return f'<span lang="grc"{anchor_attr}>{content.strip()}</span>'
            lang_attr = (
                f' lang="{html.escape(language, quote=True)}"' if language else ""
            )
            return f"<span{lang_attr}{anchor_attr}>{content.strip()}</span>"
        if tag == "quote":
            if elem.get("lang", "").lower() in {"greek", "grc"}:
                return f'<q lang="grc"{anchor_attr}>{content.strip()}</q>'
            if any(child.tag == "quote" for child in elem):
                return f'<span class="quote"{anchor_attr}>{content.strip()}</span>'
            return f"<q{anchor_attr}>{content.strip()}</q>"
        if tag == "gloss":
            return f'<span class="gloss"{anchor_attr}>{content.strip()}</span>'
        if tag == "emph":
            rendered = "strong" if elem.get("rend") == "bold" else "em"
            return f"<{rendered}{anchor_attr}>{content.strip()}</{rendered}>"
        if tag == "ref":
            target, _ = parse_ref(elem)
            if target is None:
                return content.strip()
            lettered = ref_letter(elem)
            anchor_ref = (
                f' data-anchor="{lettered[1]}"'
                if lettered and lettered[0] == target
                else ""
            )
            return (
                f'<a data-ref="smyth:{target}"{anchor_ref}>{content.strip()}</a>'
            )
        if tag == "bibl":
            cite = elem.get("n") or text_of(elem)
            cite_attr = html.escape(cite, quote=True)
            return f'<cite data-cite="{cite_attr}"{anchor_attr}>{content.strip()}</cite>'
        if tag == "cit":
            return f'<span class="example"{anchor_attr}>{content.strip()}</span>'
        if tag == "row":
            return f"<tr{anchor_attr}>{content.strip()}</tr>"
        if tag == "cell":
            attrs = anchor_attr
            if (cols := elem.get("cols")) and cols.isdigit() and cols != "1":
                attrs += f' colspan="{cols}"'
            if (rows := elem.get("rows")) and rows.isdigit() and rows != "1":
                attrs += f' rowspan="{rows}"'
            return f"<td{attrs}>{content.strip()}</td>"
        if tag == "pb":
            page = html.escape(elem.get("n", ""), quote=True)
            return f'<span class="page-break" data-page="{page}"></span>'
        if tag == "note":
            if elem.get("place") == "inline":
                return f'<span class="footnote">{content.strip()}</span>'
            self.footnote += 1
            return (
                f'<aside class="footnote" id="fn{self.footnote}">'
                f"{content.strip()}</aside>"
            )
        if tag == "head":
            return f"<h4{anchor_attr}>{content.strip()}</h4>"
        if tag == "figure":
            return f'<span class="figure"{anchor_attr}>{content.strip()}</span>'
        if tag in {"term", "title", "author", "name", "mentioned"}:
            css = html.escape(tag, quote=True)
            return f'<span class="{css}"{anchor_attr}>{content.strip()}</span>'

        # Unknown TEI wrappers lose their tag and attributes, but keep all text.
        if anchor:
            return f'<span id="{html.escape(anchor, quote=True)}">{content.strip()}</span>'
        return content

    @staticmethod
    def is_block(elem: ET.Element) -> bool:
        """Report whether the element renders as HTML that <p> cannot contain."""
        if elem.tag == "table":
            return True
        return elem.tag == "note" and elem.get("place") != "inline"

    def paragraph(self, elem: ET.Element, in_greek: bool, anchor_attr: str) -> str:
        """Render a TEI p, lifting block children out to sibling level.

        The source puts tables and footnotes inside p.  Nesting them in the HTML
        p would be invalid, and a browser closes the p at the block and leaves an
        empty one behind, so the prose around a block becomes one p per run.
        """
        parts: list[tuple[bool, str]] = []  # (wrap in a p, html)
        buffer: list[str] = [self._text(lead_text(elem), in_greek)]

        def flush() -> None:
            text = "".join(buffer).strip()
            buffer.clear()
            if not text:
                return
            # A run of nothing but page-break markers gets no paragraph box.
            has_words = bool(TAG_RE.sub("", text).strip())
            parts.append((has_words, text))

        for index, child in enumerate(elem):
            if self.is_block(child):
                flush()
                parts.append((False, self.element(child, in_greek)))
            else:
                buffer.append(self.element(child, in_greek))
            buffer.append(self._text(tail_text(elem, index), in_greek))
        flush()

        if not parts:
            # An empty p is worth keeping only when it carries a subsection anchor.
            return f"<p{anchor_attr}></p>" if anchor_attr else ""

        # The anchor marks where the subsection starts, so it stays first in
        # document order: on the opening p, or on its own marker when the
        # paragraph opens with something that is not a p.
        opens_with_p = parts[0][0]
        chunks = [] if opens_with_p or not anchor_attr else [f"<span{anchor_attr}></span>"]
        for index, (wrap, rendered) in enumerate(parts):
            attrs = anchor_attr if index == 0 and opens_with_p else ""
            chunks.append(f"<p{attrs}>{rendered}</p>" if wrap else rendered)
        return "".join(chunks)

    def table(self, elem: ET.Element, in_greek: bool, anchor_attr: str) -> str:
        """Render a TEI table, lifting non-row children out in front of it.

        The source puts paradigm titles (63 heads) and a few page markers
        inside table.  An HTML table takes only rows and row groups, so a
        browser foster-parents such a child out to just before the table:
        emitting it there makes the markup match the rendered tree, and keeps
        the title out of the site's horizontal scroll box, where a <caption>
        would slide off with the columns.
        """
        before: list[str] = []
        rows: list[str] = []
        for index, child in enumerate(elem):
            if child.tag == "row":
                rows.append(self.element(child, in_greek))
                # Only whitespace ever separates rows; keep it between them.
                rows.append(self._text(tail_text(elem, index), in_greek))
            else:
                before.append(self.element(child, in_greek))
        return (
            f"{''.join(before)}<table{anchor_attr}>"
            f"{''.join(rows).strip()}</table>"
        )

    def children(self, elem: ET.Element) -> str:
        chunks: list[str] = []
        if lead_text(elem).strip():
            chunks.append(self._text(lead_text(elem)))
        for index, child in enumerate(elem):
            chunks.append(self.element(child))
            if tail_text(elem, index).strip():
                chunks.append(self._text(tail_text(elem, index)))
        return "".join(chunks).strip()


def cit_example(citation: ET.Element) -> dict[str, str] | None:
    outer_quote = citation.find("quote")
    bibl = citation.find("bibl")
    if outer_quote is None:
        return None
    if outer_quote.get("lang", "").lower() == "greek":
        greek_quote = outer_quote
        gloss = ""
    else:
        greek_quote = next(
            (
                q
                for q in outer_quote.iter("quote")
                if q.get("lang", "").lower() == "greek"
            ),
            None,
        )
        gloss_elem = outer_quote.find("gloss")
        gloss = text_of(gloss_elem) if gloss_elem is not None else ""
    if greek_quote is None:
        return None
    cite = ""
    if bibl is not None:
        cite = bibl.get("n") or text_of(bibl)
    return {"grc": text_of(greek_quote), "gloss": gloss, "cite": cite}


def is_greek_foreign(elem: ET.Element) -> bool:
    return elem.tag == "foreign" and elem.get("lang", "").lower() == "greek"


def resumes_after_paren(children: list[ET.Element], start: int) -> bool:
    """True when ``start`` is the far side of a bracket cut into a quotation.

    Reads only the print's own punctuation, in two shapes.  Either the whole
    bracket sits in the tail of the Greek run before ``start`` and nothing else
    does (``PAREN_ASIDE_RE``); or the bracket holds marked-up material, in which
    case the sibling before ``start`` ends it and adds nothing but join
    punctuation, nothing between opens or closes another one, and the bracket
    opened on the tail of a Greek run with no words of running prose in front
    of it (``PAREN_OPENS_RE``).
    """
    if start == 0:
        return False
    if is_greek_foreign(children[start - 1]) and PAREN_ASIDE_RE.match(
        children[start - 1].tail or ""
    ):
        return True
    if not PAREN_CLOSES_RE.match(children[start - 1].tail or ""):
        return False
    index = start - 1
    while index > 0:
        tail = children[index - 1].tail or ""
        if ")" in tail:
            return False
        if "(" in tail:
            return bool(PAREN_OPENS_RE.match(tail)) and is_greek_foreign(children[index - 1])
        index -= 1
    return False


def joined(parts: list[tuple[str, str]]) -> str:
    """Join text taken from siblings, keeping the separator the print set.

    ``parts`` is (text, tail) in document order.  Joining on a single space
    instead threw the print's own punctuation away: the source's
    ``<gloss>10</gloss>,<gloss>400 horse</gloss>`` shipped as "10 400 horse",
    and a bracketed alternative ran into the translation as continuous text
    ("I have am resolved" for "I have (am) resolved" at Sec. 1945).

    The last tail leads out of the example, to the ``bibl``, so it is dropped --
    except for a bracket it closes that a part left open, as in Sec. 1120's
    ``<gloss>Solon the wisest of the Seven</gloss> (<gloss>Sages</gloss>) ``,
    where the opener is a separator and the closer is in that last tail.
    """
    out = ""
    for position, (text, tail) in enumerate(parts):
        out += text
        separator = re.sub(r"\s+", " ", tail)
        if position + 1 == len(parts):
            unclosed = out.count("(") - out.count(")")
            separator = ")" * min(max(unclosed, 0), separator.count(")"))
        out += separator
    return norm(out)


def bare_example(children: list[ET.Element], start: int) -> tuple[dict[str, str] | None, int]:
    """Read an un-wrapped example starting at a Greek ``foreign`` sibling.

    Besides the 3,047 ``cit`` elements, Smyth sets some 650 examples as a
    ``foreign lang="greek"`` (sometimes two, split by a comma), optional
    ``gloss`` elements, and a ``bibl``, as direct siblings joined by nothing
    but punctuation ("ἀσπὶς μῡρίᾱ καὶ τετρακοσίᾱ 10,400 horse X. A. 1.7.10").
    Words between the parts mean running prose ("πόλιος (two syllables) Φ
    567"), and a parenthesis on the Greek's tail a phrase cut in two, so
    both are left alone, and a chain neither crosses a bracket nor starts on
    the far side of one (``resumes_after_paren``).  ``children`` has had page
    breaks removed (see ``iter_examples``); a Greek fragment ending in "-" was
    divided at the foot of a page and is rejoined without the hyphen
    ("γιγνομέ-" + "νων").  Every other part keeps the punctuation the print set
    between it and the next (``joined``).
    Returns the example and the index after the ``bibl``, or ``(None, start)``.
    """
    if resumes_after_paren(children, start):
        return None, start
    end = start
    while (
        end + 1 < len(children)
        and is_greek_foreign(children[end + 1])
        and EXAMPLE_MERGE_RE.match(children[end].tail or "")
    ):
        end += 1
    if not EXAMPLE_JOIN_RE.match(children[end].tail or ""):
        return None, start
    index = end + 1
    glosses: list[tuple[str, str]] = []
    while (
        index < len(children)
        and children[index].tag == "gloss"
        and GLOSS_TAIL_RE.match(children[index].tail or "")
    ):
        glosses.append((text_of(children[index]), children[index].tail or ""))
        index += 1
    if index >= len(children) or children[index].tag != "bibl":
        return None, start
    fragments: list[tuple[str, str]] = []
    for item in range(start, end + 1):
        fragment = text_of(children[item])
        if fragments and fragments[-1][0].endswith("-") and not fragments[-1][1].strip():
            head, _ = fragments.pop()
            fragment = head[:-1] + fragment
        fragments.append((fragment, children[item].tail or ""))
    grc = joined(fragments)
    if not grc:
        return None, start
    bibl = children[index]
    gloss = joined([part for part in glosses if part[0]])
    return {"grc": grc, "gloss": gloss, "cite": bibl.get("n") or text_of(bibl)}, index + 1


def iter_examples(parent: ET.Element) -> Iterator[tuple[str, dict[str, str]]]:
    """Yield ``("cit" | "bare", example)`` under ``parent`` in document order."""
    # A page break carrying no text of its own is invisible to the sibling
    # chain (8 bare examples straddle one); a ``pb`` with words in its tail
    # stays and breaks the chain like any other element.
    children = [
        child
        for child in parent
        if not (child.tag == "pb" and EXAMPLE_JOIN_RE.match(child.tail or ""))
    ]
    index = 0
    while index < len(children):
        child = children[index]
        if child.tag == "cit":
            example = cit_example(child)
            if example is not None:
                yield "cit", example
            index += 1
            continue
        if is_greek_foreign(child):
            example, after = bare_example(children, index)
            if example is not None:
                yield "bare", example
                index = after
                continue
        yield from iter_examples(child)
        index += 1


def extract_examples(nodes: Iterable[ET.Element]) -> list[dict[str, str]]:
    return [example for node in nodes for _, example in iter_examples(node)]


def bare_example_count(nodes: Iterable[ET.Element]) -> int:
    return sum(1 for node in nodes for kind, _ in iter_examples(node) if kind == "bare")


def descendants_for_number(
    grouped: dict[int, list[ET.Element]], number: int
) -> list[ET.Element]:
    return grouped[number]


def supplemental_blocks(
    root: ET.Element,
    parents: dict[ET.Element, ET.Element],
    base_sections: dict[int, ET.Element],
) -> tuple[dict[int, list[ET.Element]], dict[ET.Element, int]]:
    """Assign unnumbered main-text blocks to the prior printed section.

    Smyth's preposition list and a few paradigms place prose in structural
    ``div`` elements between numbered ``smythp`` siblings.  Such blocks belong
    to the prior printed section.  The separate verb appendix (Part V) remains
    outside section records, as the binding spec gives it its own route.
    """
    ordered = list(root.iter())
    positions = {elem: index for index, elem in enumerate(ordered)}
    base_by_part: dict[ET.Element, list[tuple[int, int]]] = collections.defaultdict(list)

    def containing_part(elem: ET.Element) -> ET.Element | None:
        current: ET.Element | None = elem
        while current is not None:
            if (current.get("type") or "").lower() == "part":
                return current
            current = parents.get(current)
        return None

    for number, elem in base_sections.items():
        part = containing_part(elem)
        if part is not None:
            base_by_part[part].append((positions[elem], number))
    for values in base_by_part.values():
        values.sort()

    assigned: dict[int, list[ET.Element]] = collections.defaultdict(list)
    for elem in ordered:
        if elem.tag not in {"head", "p", "table"}:
            continue
        if nearest_smythp(elem, parents) is not None:
            continue
        # Keep only maximal prose/table blocks.
        if elem.tag in {"p", "table"}:
            ancestor = parents.get(elem)
            if ancestor is not None and ancestor.tag in {"p", "table"}:
                continue
        # A structural head is metadata unless its own div has no smythp child.
        if elem.tag == "head":
            owner_div = parents.get(elem)
            if owner_div is None or any(
                descendant.get("type") == "smythp" for descendant in owner_div.iter()
            ):
                continue
        if any(descendant.get("type") == "smythp" for descendant in elem.iter()):
            continue
        part = containing_part(elem)
        if part is None or part.get("n") == "5":
            continue
        choices = base_by_part.get(part, [])
        if not choices:
            continue
        offsets = [item[0] for item in choices]
        place = bisect.bisect_right(offsets, positions[elem]) - 1
        # Material before the first marker belongs with that first marker.
        number = choices[place if place >= 0 else 0][1]
        assigned[number].append(elem)
    return assigned, positions


def build_toc(
    base_sections: dict[int, ET.Element],
    parents: dict[ET.Element, ET.Element],
) -> list[dict[str, object]]:
    """Build Part -> Chapter -> Section-head TOC entries with numeric bounds."""
    hierarchy: collections.OrderedDict[
        tuple[ET.Element, str],
        collections.OrderedDict[
            tuple[ET.Element, str], collections.OrderedDict[tuple[ET.Element, str], list[int]]
        ],
    ] = collections.OrderedDict()
    chapter_numbers: dict[tuple[ET.Element, str], list[int]] = collections.defaultdict(list)
    part_numbers: dict[tuple[ET.Element, str], list[int]] = collections.defaultdict(list)

    for number, elem in base_sections.items():
        ancestors: list[ET.Element] = []
        current = parents.get(elem)
        while current is not None:
            if DIV_RE.fullmatch(current.tag) and current.get("type") != "smythp":
                ancestors.append(current)
            current = parents.get(current)
        ancestors.reverse()
        part = next(
            (a for a in ancestors if (a.get("type") or "").lower() == "part"),
            None,
        )
        chapter = next(
            (a for a in ancestors if (a.get("type") or "").lower() == "chapter"),
            None,
        )
        section = next(
            (a for a in ancestors if (a.get("type") or "").lower() == "section"),
            None,
        )
        if part is None:
            continue
        part_key = (part, first_head(part) or "")
        # Sixteen sections (822-837) sit directly under their part with no
        # chapter div.  They stay in the TOC under a chapter that reuses the
        # part heading, which is also the head those records already carry.
        chapter_key = (
            (chapter, first_head(chapter) or "")
            if chapter is not None
            else part_key
        )
        part_bucket = hierarchy.setdefault(part_key, collections.OrderedDict())
        section_bucket = part_bucket.setdefault(chapter_key, collections.OrderedDict())
        part_numbers[part_key].append(number)
        chapter_numbers[chapter_key].append(number)
        if section is not None:
            section_key = (section, first_head(section) or "")
            section_bucket.setdefault(section_key, []).append(number)

    toc: list[dict[str, object]] = []
    for part_key, chapters in hierarchy.items():
        part_values = part_numbers[part_key]
        part_record: dict[str, object] = {
            "head": part_key[1],
            "start": min(part_values),
            "end": max(part_values),
            "chapters": [],
        }
        chapter_records: list[dict[str, object]] = []
        for chapter_key, sections in chapters.items():
            chapter_values = chapter_numbers[chapter_key]
            section_records: list[dict[str, object]] = []
            for section_key, values in sections.items():
                section_records.append(
                    {
                        "head": section_key[1],
                        "start": min(values),
                        "end": max(values),
                    }
                )
            chapter_records.append(
                {
                    "head": chapter_key[1],
                    "start": min(chapter_values),
                    "end": max(chapter_values),
                    "sections": section_records,
                }
            )
        part_record["chapters"] = chapter_records
        toc.append(part_record)
    return toc


def convert(source: Path) -> tuple[list[dict[str, object]], dict[str, object]]:
    # The source mixes precomposed and decomposed Greek: the same word can be
    # spelled u + rough breathing + macron in one place and precomposed there
    # plus a macron in another.  NFC at the door makes every downstream string
    # -- html, plain, examples -- comparable and searchable.  Marks that have
    # no precomposed form (chiefly the macron) stay combining, as they must.
    text = source.read_text(encoding="utf-8")
    text = EUNC_RE.sub("\u03f5", text)
    for placeholder, glyph in GLYPH_FIXES.items():
        text = text.replace(placeholder, glyph)
    root = ET.fromstring(unicodedata.normalize("NFC", text))
    parents = {child: parent for parent in root.iter() for child in parent}
    # Stranded diacritics are repaired on the tree, where each one's printed
    # section is known, and before anything reads the text.  The composed forms
    # are precomposed characters, so the NFC guarantee above still holds.
    mark_repairs = repair_marks(root, parents)
    # Runs after the mark repairs, so it has the last word on the four signs
    # the keraia sweep cannot get right on its own.
    mark_repairs["numeralSignsCorrected"] = repair_numeral_signs(root)
    # Last of the repairs, so restacking also covers their output.
    mark_repairs.update(restack_macrons(root))
    smythp_nodes = [elem for elem in root.iter() if elem.get("type") == "smythp"]
    grouped: dict[int, list[ET.Element]] = collections.defaultdict(list)
    base_sections: dict[int, ET.Element] = {}
    base_duplicates: dict[int, list[str]] = collections.defaultdict(list)

    for elem in smythp_nodes:
        number, suffix = section_parts(elem)
        grouped[number].append(elem)
        if suffix == "":
            if number in base_sections:
                base_duplicates[number].append(elem.get("n", ""))
            else:
                base_sections[number] = elem

    numbers = sorted(base_sections)
    gaps = [number for number in range(1, 3049) if number not in base_sections]
    supplements, positions = supplemental_blocks(root, parents, base_sections)
    all_ranges, ranges_by_ref = find_ref_ranges(root)
    malformed_refs: list[dict[str, object]] = []
    unresolved_refs: list[dict[str, object]] = []
    missing_cites: list[dict[str, object]] = []
    ref_occurrences = 0
    bare_in_records = 0
    records: list[dict[str, object]] = []
    letter_refs: set[tuple[int, str]] = set()
    implicit_letter_anchors: list[dict[str, object]] = []
    declared_letter_refs: dict[int, set[str]] = collections.defaultdict(set)
    for ref in root.iter("ref"):
        lettered = ref_letter(ref)
        if lettered:
            declared_letter_refs[lettered[0]].add(lettered[1])

    for index, number in enumerate(numbers):
        base = base_sections[number]
        source_nodes = descendants_for_number(grouped, number)
        dialect_nodes = [node for node in source_nodes if node is not base]
        nodes = sorted(source_nodes + supplements.get(number, []), key=positions.get)
        bare_in_records += bare_example_count(nodes)
        letters: list[str] = []
        letter_markers: dict[ET.Element, str] = {}
        for section_node in source_nodes:
            node_letters, node_markers = find_letter_markers(section_node)
            for anchor in node_letters:
                if anchor not in letters:
                    letters.append(anchor)
            for marker, anchor in node_markers.items():
                if anchor not in letter_markers.values():
                    letter_markers[marker] = anchor
        synthetic_letters = sorted(declared_letter_refs[number] - set(letters))
        letters.extend(synthetic_letters)
        implicit_letter_anchors.extend(
            {"section": number, "anchor": anchor} for anchor in synthetic_letters
        )
        renderer = Renderer(letter_markers)

        synthetic_html = "".join(f'<span id="{anchor}"></span>' for anchor in synthetic_letters)
        body_html = synthetic_html + renderer.children(base)
        dialect_notes: list[dict[str, object]] = []
        extra_html: list[str] = []
        dialect_by_node: dict[ET.Element, dict[str, object]] = {}
        for dialect_index, dialect in enumerate(dialect_nodes):
            anchor = "D" if dialect_index == 0 else f"D{dialect_index}"
            note_renderer = Renderer(letter_markers)
            note_html = note_renderer.children(dialect)
            note_plain = text_of(dialect)
            label = dialect.get("n", "")
            dialect_notes.append(
                {
                    "anchor": anchor,
                    "label": label,
                    "html": note_html,
                    "plain": note_plain,
                    "dialect": True,
                }
            )
            dialect_by_node[dialect] = dialect_notes[-1]

        supplement_renderer = Renderer({})
        for node in nodes:
            if node is base:
                continue
            if node in dialect_by_node:
                note = dialect_by_node[node]
                extra_html.append(
                    f'<aside class="dialect-note" id="{note["anchor"]}" '
                    f'data-dialect="true">{note["html"]}</aside>'
                )
            else:
                extra_html.append(supplement_renderer.element(node))

        refs: list[str] = []
        ranges: list[dict[str, int]] = []
        for node in nodes:
            for ref in node.iter("ref"):
                ref_occurrences += 1
                target, found_range = parse_ref(ref)
                if target is None:
                    malformed_refs.append(
                        {"section": number, "text": text_of(ref), "attrs": dict(ref.attrib)}
                    )
                    continue
                target_id = f"smyth:{target}"
                if target_id not in refs:
                    refs.append(target_id)
                if target not in base_sections:
                    unresolved_refs.append(
                        {"section": number, "target": target, "text": text_of(ref)}
                    )
                lettered = ref_letter(ref)
                if lettered:
                    letter_refs.add((target, lettered[1]))
                for range_record in ranges_by_ref.get(ref, []):
                    if range_record not in ranges:
                        ranges.append(range_record)

        for node in nodes:
            for bibl in node.iter("bibl"):
                if not bibl.get("n"):
                    missing_cites.append(
                        {"section": number, "text": text_of(bibl)}
                    )

        path = ancestor_path(base, parents)
        head = path[-1] if path else f"Smyth section {number}"
        combined_html = f'<section id="s{number}">{body_html}{"".join(extra_html)}</section>'
        combined_plain = norm(" ".join(text_of(node) for node in nodes))
        records.append(
            {
                "work": "smyth",
                "n": number,
                "id": f"smyth:{number}",
                "letters": letters,
                "dialectNotes": dialect_notes,
                "path": path,
                "head": head,
                "html": combined_html,
                "plain": combined_plain,
                "examples": extract_examples(nodes),
                "refs": refs,
                "refRanges": ranges,
                "citedBy": [],
                "prev": f"smyth:{numbers[index - 1]}" if index else None,
                "next": f"smyth:{numbers[index + 1]}" if index + 1 < len(numbers) else None,
            }
        )

    record_by_id = {record["id"]: record for record in records}
    for source_record in records:
        for target_id in source_record["refs"]:
            target_record = record_by_id.get(target_id)
            if target_record is not None:
                target_record["citedBy"].append(source_record["id"])

    quote_count = sum(1 for _ in root.iter("quote"))
    bibliography_count = sum(1 for _ in root.iter("bibl"))
    lsj_count = sum(
        1
        for bibl in root.iter("bibl")
        if (bibl.get("n") or "").startswith(LSJ_PREFIX)
    )
    passage_values = [
        bibl.get("n") or text_of(bibl)
        for bibl in root.iter("bibl")
        if (bibl.get("n") or text_of(bibl))
        and not (bibl.get("n") or "").startswith(LSJ_PREFIX)
    ]
    passage_count = len(passage_values)
    missing_letter_anchors = [
        {"section": number, "anchor": anchor}
        for number, anchor in sorted(letter_refs)
        if number not in base_sections
        or anchor not in next(
            record["letters"] for record in records if record["n"] == number
        )
    ]
    source_repeats = [
        {"n": number, "labels": [node.get("n", "") for node in grouped[number]]}
        for number in sorted(grouped)
        if len(grouped[number]) > 1
    ]
    record_range_values = {
        (item["start"], item["end"])
        for record in records
        for item in record["refRanges"]
    }
    ranges_outside_sections = [
        item
        for item in all_ranges
        if (item["start"], item["end"]) not in record_range_values
    ]

    anomalies: dict[str, object] = {
        "numberingGaps": gaps,
        "baseSectionDuplicates": [
            {"n": number, "labels": labels}
            for number, labels in sorted(base_duplicates.items())
        ],
        "sourceNumberRepeats": source_repeats,
        "malformedRefs": malformed_refs,
        "unresolvedRefs": unresolved_refs,
        "biblWithoutN": missing_cites,
        "letterRefsMissingAnchor": missing_letter_anchors,
        "implicitLetterAnchors": implicit_letter_anchors,
        "rangesOutsideSections": ranges_outside_sections,
        "sourceMarkRepairs": mark_repairs,
        "passageCitationExpectation": {
            "expected": "approximately 4900-5000",
            "actual": passage_count,
            "withinExpectedRange": 4900 <= passage_count <= 5000,
            "examples": passage_values[-5:],
        },
    }
    meta: dict[str, object] = {
        "work": "smyth",
        "source": "grammar-smyth/src/smyth_eng_u.xml",
        "toc": build_toc(base_sections, parents),
        "counts": {
            "sections": len(records),
            "smythpNodes": len(smythp_nodes),
            "sourceCrossRefs": sum(1 for _ in root.iter("ref")),
            "sectionCrossRefs": ref_occurrences,
            "crossRefsOutsideSections": sum(1 for _ in root.iter("ref"))
            - ref_occurrences,
            "uniqueRefEdges": sum(len(record["refs"]) for record in records),
            "crossRefRanges": len(all_ranges),
            "quotes": quote_count,
            "bibliographies": bibliography_count,
            "passageCitations": passage_count,
            "lsjCitations": lsj_count,
            "examples": sum(len(record["examples"]) for record in records),
            # Un-wrapped foreign/gloss/bibl examples (see bare_example); the
            # ones outside sit in the verb appendix and front matter.
            "bareExamples": bare_in_records,
            "bareExamplesOutsideSections": bare_example_count([root]) - bare_in_records,
            "sectionsWithLetters": sum(bool(record["letters"]) for record in records),
            "letterAnchors": sum(len(record["letters"]) for record in records),
            "sectionsWithDialectNotes": sum(
                bool(record["dialectNotes"]) for record in records
            ),
            "dialectNotes": sum(len(record["dialectNotes"]) for record in records),
        },
        "crossRefRanges": all_ranges,
        "anomalies": anomalies,
    }
    return records, meta


def write_outputs(
    records: list[dict[str, object]],
    meta: dict[str, object],
    sections_path: Path,
    meta_path: Path,
) -> None:
    sections_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    section_bytes = ("\n".join(json_line(record) for record in records) + "\n").encode(
        "utf-8"
    )
    meta_bytes = (
        json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    ).encode("utf-8")
    sections_path.write_bytes(section_bytes)
    meta_path.write_bytes(meta_bytes)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--sections", type=Path, default=DEFAULT_SECTIONS)
    parser.add_argument("--meta", type=Path, default=DEFAULT_META)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    records, meta = convert(args.input)
    write_outputs(records, meta, args.sections, args.meta)
    counts = meta["counts"]
    print(
        f"wrote {counts['sections']} sections, {counts['sourceCrossRefs']} source refs, "
        f"and {counts['examples']} examples"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
