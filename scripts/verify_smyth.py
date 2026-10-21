#!/usr/bin/env python3
"""Independently verify the Smyth TEI conversion and print a full report."""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import unicodedata
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "grammar-smyth" / "src" / "smyth_eng_u.xml"
DEFAULT_SECTIONS = ROOT / "data" / "smyth" / "sections.jsonl"
DEFAULT_META = ROOT / "data" / "smyth" / "meta.json"
DEFAULT_CONVERTER = ROOT / "scripts" / "convert_smyth.py"
SECTION_RE = re.compile(r"^\s*(\d+)(.*)$")
ID_RE = re.compile(r"^smyth:(\d+)$")
LETTER_RE = re.compile(r"^[a-z](?:\d+)?$")
GREEK_RE = re.compile(r"[\u0370-\u03ff\u1f00-\u1fff]")
LSJ_PREFIX = "Perseus:text:1999.04.0057:entry="
KORONIS = "᾽"
# NFC leaves U+0374 GREEK NUMERAL SIGN spelled as U+02B9.
KERAIA = unicodedata.normalize("NFC", "ʹ")
GREEK_TOKEN_RE = re.compile(r"[̀-ͯͰ-Ͽἀ-῿]+")
VOWEL_KORONIS_RE = re.compile(r"[αειουηωΑΕΙΟΥΗΩ][̀-ͯ]*᾽")
# διά elided, the vocative Ἀντίνοε (1011), αἴτια (1481), and γέρα᾽ (264 D),
# κλέα᾽ (265 D), ἥρω᾽ (267 D), all six of which the 1920 print really does spell
# with a trailing apostrophe.  Nothing else may keep a koronis after a vowel.
ALLOWED_VOWEL_KORONIS = {
    "δι᾽",
    "Ἀντίνο᾽",
    "αἴτι᾽",
    "γέρα᾽",
    "κλέα᾽",
    "ἥρω᾽",
}
# Composed onto a letter, restored as a keraia, kept as a real apostrophe.
EXPECTED_MARK_REPAIRS = (106, 35, 32)
# The source's bracketed glyph placeholders, and what each must have become in
# the data.  Nothing asserted these before, which is how two of them stayed
# wrong: [Eunc ] resolved to a plain epsilon where the print has a lunate one,
# and [macrdot] to a metrical anceps where the print marks the ictus.  Counted
# over the plain fields, where a placeholder outside every section record (the
# verb appendix, the front matter) simply does not appear -- hence 179 of the
# source's 193 i-glides.
RESOLVED_GLYPHS = {
    "ι̯": 179,
    "υ̯": 25,
    "ε̯": 1,
    "ϡ": 4,
    "͵": 8,
    "¯̇": 24,
    "ϵ": 1,
}
# Three placeholders stay: Unicode encodes no half of Heta and no archaic
# letterform variant of lambda.  Any other bracketed placeholder reaching the
# data is a glyph the converter failed to resolve.
UNRESOLVED_GLYPHS = {"[lins ]", "[rough ]", "[smooth]"}
GLYPH_PLACEHOLDER_RE = re.compile(r"\[[^\]<>]{1,12}\]")
# Sec. 347's sign column as the 1920 print gives it (pp. 103-104, confirmed on
# both scans), every sign carrying the keraia.  Stated in full rather than as
# the four corrections, because the whole column is cheap to check and the
# sigma at 200 is correct while the sigma the source also used at 6 and 16 is
# not -- a difference no token-level rule can see.
PRINTED_NUMERALS = {
    "1": "α", "2": "β", "3": "γ", "4": "δ", "5": "ε", "6": "ϛ", "7": "ζ",
    "8": "η", "9": "θ", "10": "ι", "11": "ια", "12": "ιβ", "13": "ιγ",
    "14": "ιδ", "15": "ιε", "16": "ιϛ", "17": "ιζ", "18": "ιη", "19": "ιθ",
    "20": "κ", "21": "κα", "30": "λ", "40": "μ", "50": "ν", "60": "ξ",
    "70": "ο", "80": "π", "90": "ϙ", "100": "ρ", "200": "σ", "300": "τ",
    "400": "υ", "500": "φ", "600": "χ", "700": "ψ", "800": "ω", "900": "ϡ",
}
# Sec. 348's prose names the same three obsolete signs and works the notation
# out in examples, where betacode's bare "#" stood for the keraia.
PRINTED_NUMERAL_PROSE = (
    "ϛ, a form identical with the late abbreviation for στ",
    "ϙ (koppa), in the same order as Lat. q, for 90",
    "for 900, ϡ sampi",
    "(αʹ = 1, ͵α = 1000)",
    "ρνζʹ 157, υαʹ 401, ͵αϡιʹ 1910",
)
EXPECTED_NUMERAL_REPAIRS = {
    "numeralSignsCorrected": 4,
    "numeralProseFixed": 2,
    "numeralMarksRestored": 4,
}
# Targets an earlier reading chose and the print ruled out; they must not return.
RETIRED_GLYPHS = ("\u23d2",)
# One audited reading per distinct repair, checked against the 1920 print (the
# two archive.org scans named in convert_smyth.py).  Counts alone would not
# notice a repair table edited to the wrong letter -- swap Sec. 1692's article
# to smooth and every tally stays put -- so these frozen strings, and not the
# converter's own bookkeeping, are what pins the readings down.
EXPECTED_READINGS = (
    (61, "ἦ οὐ"),
    (64, "καὶ οἱ and the = χοἰ"),
    (68, "καὶ οὐ = κοὐ, καὶ ἡ = χἠ, καὶ οἱ = χοἰ"),
    (274, "the stem is οἰ, representing ὀϝι"),
    (285, "whence ὀ(υ̯)ατ-"),
    (326, "(ἐ) με-"),
    (326, "(ἐ)μο-, ἡμε-"),
    (347, "1 αʹ"),
    (464, "ἦα was for ἠ(σ)α"),
    (485, "(ἐ)θέλω"),
    (549, "(ἐ)κέκλετο"),
    (574, "(ὄρνυμι rouse)"),
    (779, "ἐ is the augment"),
    # Recorded with the spaces our own extraction manufactured; the source
    # nests <foreign> on its own line and the reading is ἀ(ν)-, as Sec. 898
    # has always had it (work/tables/FINDING-tei-whitespace.md).
    (885, "ἀ(ν)-"),
    (898, "ἀ(ν)-negative"),
    (1089, "πλεῖσται δὴ νῆες"),
    (1252, "τοὺς ἀλιτηρίους"),
    (1689, "τοῦ Δεκελεικοῦ πολέμου"),
    (1692, "σῑτοῦνται οἱ παῖδες"),
    (1815, "αἰ γάρ, αἴθε"),
    (2196, "καὶ οἱ ἑλόμενοι"),
    (2283, "ἠ (another form of εἰ)"),
    (2297, "εἰ with present or perfect"),
    (2372, "κεἰ μὴ πέποιθα"),
    (2763, "ἀλλ᾽ οὐ (μή)"),
    (2877, "κοὐ βλέπεις"),
)

# Six more placeholder characters, repaired the same way as the koronis
# above; convert_smyth.py's tables explain the classification for each.
DASIA = "\u1ffe"
DASIA_OXIA = "\u1fde"
DASIA_PERISPOMENI = "\u1fdf"
PERISPOMENI = "\u1fc0"
DIAERESIS_SPACING = "\u00a8"
PSILI = "\u1fbf"
PSILI_VARIA = "\u1fcd"
PSILI_OXIA = "\u1fce"
PSILI_PERISPOMENI = "\u1fcf"
EXPECTED_SOURCE_MARK_COUNTS = {
    DASIA: 5,
    DASIA_OXIA: 4,
    DASIA_PERISPOMENI: 2,
    PERISPOMENI: 246,
    DIAERESIS_SPACING: 119,
    PSILI_VARIA: 1,
    PSILI_OXIA: 3,
    PSILI_PERISPOMENI: 1,
}
# All 26 U+1FBF sites end at zero, but for two different reasons: 17 were
# stranded breathings and got composed, and the 9 that are genuine aphaeresis
# keep their mark and take U+1FBD, the character the elisions use, so that one
# apostrophe serves both kinds of lost vowel.
EXPECTED_PSILI = {"source": 26, "remaining": 0}
# The spacing accents, which NFC leaves as U+00B4 and U+0060.  A count alone
# would not say the right ones survived, so the invariant is positional: no
# spacing accent may stand after a Greek vowel, because that is precisely where
# it should have been composed.  What remains is nine acutes in Sanskrit
# transliteration (bhā´mi, mā´, tvē´), which are Latin script and out of scope,
# and three marks belonging to a letter inside one of Perseus's "<*>" gaps --
# including Sec. 2578, where the betacode itself reads "s\\", a mis-keyed
# letter for the print to settle rather than a stranded mark.
SPACING_ACUTE = "´"
SPACING_GRAVE = "`"
EXPECTED_SPACING_ACCENTS = {SPACING_ACUTE: 9, SPACING_GRAVE: 3}
NEW_MARK_READINGS = (
    # The psili family: a breathing composed onto a capital, or back onto the
    # vowel it had drifted off, and the four aphaeresis marks pulled tight
    # against their word as the print sets them.
    (76, "μὴ ᾽νταῦθα, ἢ ᾽μέ, παρέξω ᾽μαυτόν, αὐτὴ ᾽ξῆλθεν"),
    (78, "On ττ in Ἀττικός see"),
    (81, "Ὀδυσεύς from Ὀδυσσεύς"),
    (105, "cp. Ἔρεβος"),
    (134, "Ἀθήνησιν ἦσαν"),
    (333, "ἐκεῖνος ἐκείνη ἐκεῖνο"),
    (383, "εἴημεν, εἶμεν"),
    (1199, "ἐμὸς αὐτοῦ, σὸς αὐτοῦ"),
    (1603, "prepositions εἰς, κατά, πρός"),
    (1689, "πλεῖον ἢ ἐπὶ δύο στάδια"),
    (2315, "ἂν αἰτιᾶσθαι αὐτόν"),
    (2428, "προὔδωκεν Ὄλυνθον"),
    (2552, "ὅπως Ἄλκηστις ἐς γῆρας"),
    # Spacing accents composed onto the vowel they had drifted off.
    (503, "Present Stems in -εόε- for ευόε-"),
    (1056, "εὐγένειαί τε καὶ δυνάμεις"),
    (1497, "πρὸς ὠφέλειαν"),
    (1499, "ὅμοια τοῖς λόγοις"),
    (1601, "τά τ᾽ ὄμματ᾽ εἶ"),
    (1935, "ὅτε τις δρῦς ἤριπεν"),
    (2112, "With ἀκούω and πυνθάνομαι"),
    (26, "\u03b8\u03ad\u03bb\u03c9 was \u03c4\u0314\u03ad\u03bb\u03c9, \u1f14\u03c7\u03c9 was \u1f14-\u03ba\u0314\u03c9. Cp. \u1f10\u03c6\u1fbd \u1fa7 for \u1f10\u03c0(\u1f76) \u1fa7, etc. Probably only one h was"),
    (149, "\u1f19\u03bb\u03bb\u03ac\u03b4\u03bf\u03c2"),
    # Restored with the source's outer macron, then restacked innermost by the
    # macron pass (check 12), so the frozen reading carries the final form.
    (1178, "\u03bf\u1f51\u03c4\u03bf\u03c3\u1fd1\u0301"),
    (2977, "(\u03c4\u03ad)"),
    (152, "\u1f0d\u03b9\u03b4\u03b7\u03c2"),
    (153, "\u1f4d\u03bc\u03b7\u03c1\u03bf\u03c2"),
    (153, "\u1f6f\u03c1\u03b1\u03b9"),
    (2225, "\u1f1d\u03bb\u03bb\u03b7\u03bd\u03b5\u03c2"),
    (2511, "\u1f45"),
    (2532, "\u03bf\u1f37\u03bf\u03b9"),
    (401, "(\u03c6\u03b1\u03bd\u03b5\u03cc\u03bc\u03b5\u03bd\u03bf\u03c2, \u03c6\u03b1\u03bd\u03bf\u03cd\u03bc\u03b5\u03bd\u03bf\u03c2, \u03c6\u03b1\u03bd\u03ad\u03bf\u03bd) \u03c6\u03b1\u03bd\u03bf\u1fe6\u03bd -\u03b7, -\u03bf\u03bd) -\u03b7, -\u03bf\u03bd (310) (287)"),
    (759, "\u03b8\u03ad-\u03bd\u03c4\u03c9\u03bd). \u1f35\u03c3\u03c4\u03b7\u03bc\u03b9 and \u03c3\u03b2\u03ad\u03bd\u03bd\u1fe1\u03bc\u03b9 have -\u03b8\u03b9 in \u03c3\u03c4\u1fc6-\u03b8\u03b9, \u03c3\u03b2\u1fc6-\u03b8\u03b9. For \u03c3\u03c4\u1fc6-\u03b8\u03b9 the poets may use -\u03c3\u03c4\u1fb1"),
    (1066, "T. 2.35. a. When the positive precedes, \u03bc\u1fb6\u03bb\u03bb\u03bf\u03bd alone may stand for the comparative; as in"),
    (2725, "\u03b5\u1f36\u03bd\u03b1\u03af"),
    (2749, "\u03bf\u1f37\u03cc\u03bd"),
    (2796, "\u03c4\u03b1\u1fd6\u03c2"),
    (750, "\u1f31\u03c3\u03c4\u03b1-\u1fd6\u03b5-\u03bd"),
    (845, "son of Telamon from \u03a4\u03b5\u03bb\u03b1\u03bc\u03ce\u03bd (-\u1ff6\u03bd\u03bf\u03c3) 4. \u03b9\u03b4\u1fb1 (nom. -\u03af\u03b4\u03b7-\u03c2, masc.), \u03b9\u03b4 (nom. -\u03af\u03c2, fem.):"),
    (1074, "\u1f31\u03c0\u03c0\u03ad\u1fb1\u03c2"),
    (1145, "\u1f22"),
    (1201, "\u1f41\u03c1\u1fb7"),
    (1322, "\u1f03"),
    (2, "\u03bb\u1fc7 \u03ba\u03b1\u1f76 \u03c4\u1ff7 \u03b4\u03ae\u03bc\u1ff3. \u03a7\u03a3\u03a5\u039b\u039b\u03a1\u0391\u03a6\u0395\u03a3\u03a7\u03a3\u03a5\u039d\u0395\u039b\u03a1\u0391\u03a6\u03a3\u0391\u039d \u03be\u03c5\u03b3\u03b3\u03c1\u03b1\u03c6\u1fc6\u03c2 \u03be\u03c5\u03bd\u03ad\u03b3\u03c1\u03b1\u03c8\u03b1\u03bd. \u0395\u0393\u0399\u03a4\u0395\u0394\u0395\u0399\u039f"),
    (3018, "verb is requisite to the meaning. Thus, (\u03bf\u1f31 \u1f08\u03b8\u03b7\u03bd\u03b1\u1fd6\u03bf\u03b9) \u03bc\u03b5\u03c4\u03ad\u03b3\u03bd\u03c9\u03c3\u03b1\u03bd \u039a\u03b5\u03c1\u03ba\u1fe1\u03c1\u03b1\u03af\u03bf\u03b9\u03c2 \u03be\u03c5\u03bc\u03bc\u03b1\u03c7\u03af\u1fb1\u03bd \u03bc\u1f74"),
    # The seven Latin-circumflex sites that carry no macron, so check 12's
    # macron readings cannot hold them.  Each is the printed reading, read off
    # the 1920 scan; the enough-context forms pin the letter the mark landed
    # on, which a bare word would not.  Sec. 305's, the eighth, is a macron
    # site and lives in MACRON_READINGS.
    (1087, "\u03bf\u1f37\u03bf\u03c2 may strengthen the superlative"),
    (1195, "\u03bf\u1f37 \u03c0\u03b1\u1fd6\u03b4\u03b1 \u1f10\u03bf\u03b9\u03ba\u03cc\u03c4\u03b1 \u03b3\u03b5\u03af\u03bd\u03b1\u03c4\u03bf"),
    (1369, "\u1fe5\u03b5\u1fd6 \u03c8\u1fe1\u03c7\u03c1\u03bf\u1fe6 \u1f55\u03b4\u03b1\u03c4\u03bf\u03c2"),
    (1973, "\u03c0\u03b1\u03c4\u03c1\u03b9\u03ba\u1f78\u03c2 \u03b1\u1f50\u03c4\u1ff7 \u03c6\u03af\u03bb\u03bf\u03c2 \u03b5\u1f36\u03bd\u03b1\u03b9"),
    (2172, "\u03bf\u1f30\u03ba\u03bf\u1fe6\u03c3\u03b9 \u03b4\u1fbd \u1f10\u03bd \u03bc\u03b9\u1fb7"),
    (2747, "\u03bf\u1f50\u03c7 \u03bf\u1f37\u03cc\u03bd \u03c4\u1fbd \u1f10\u03c3\u03c4\u03af"),
    (2806, "\u03bc\u1f74 \u03c6\u03c1\u03bf\u03bd\u1ff6 \u03b3\u1f70\u03c1 \u03bf\u1f50 \u03c6\u03b9\u03bb\u1ff6 \u03bb\u03ad\u03b3\u03b5\u03b9\u03bd"),
)
EXPECTED_NEW_MARK_REPAIRS = {
    # 33 accents composed by the rule, plus Sec. 503's pair of node edits, which
    # between them account for one more: 34 removed, 12 left, 46 in the source.
    "accentsComposed": 33,
    "splitAccentNodes": 2,
    "aphaeresisUnified": 9,
    "psiliComposed": 21,
    "aphaeresisTightened": 4,
    "dasiaComposed": 5,
    "capitalAccentComposed": 6,
    "perispomeniComposed": 6,
    "perispomeniNotation": 240,
    "diaeresisNotation": 119,
    "middotComposed": 6,
    "starComposed": 2,
    "proseFixed": 1,
}

# The source stacks every combining macron OUTERMOST -- a precomposed accented
# or breathing-bearing vowel with U+0304 on top (φύ̄ω, ὑ̄μέτερος) -- where the
# print sets the macron against the letter with breathing and accent above it.
# The two spellings are not canonically equivalent (macron and accents all
# combine at class 230, which normalization never reorders), so left alone the
# corpus would never match the index data, which already stacks innermost.
# convert_smyth.py restacks them; check 12 holds the invariant on the built
# records: no combining macron after a letter that carries any other mark.
# The one exception is breve + macron together (ῐ̄, ῠ̄), Smyth's mark for a
# vowel scanning short or long: both marks are printed, so the pair stays in
# source order until someone re-reads the print for which sits inner.
MACRON = "̄"
BREVE = "̆"
STACKED_MACRON_RE = re.compile(r"([Ͱ-Ͽἀ-῿])̄")
GREEK_VOWELS = "αειουηωΑΕΙΟΥΗΩ"
# Tree-level: 3,226 restacked, 8 anceps pairs kept, and (counted from the
# source, not the converter) 3 bare vowels whose macron is already innermost.
# One more macron hides behind a non-Greek carrier: Sec. 305's neuter carries
# a Latin U+0302 between the letter and the macron, which the restack rule
# cannot see -- it is repaired by table (LATIN_CIRCUMFLEX_FIXES) instead, and
# counted here as "hidden" so a new site of that shape fails this check
# rather than slipping past the letter-anchored regex.
EXPECTED_MACRON_REPAIRS = {
    "macronsRestacked": 3226,
    "ancepsMacronsKept": 8,
    "subscriptMacronsKept": 0,
    "latinCircumflexFixed": 8,
}
EXPECTED_SOURCE_MACRONS = {"stacked": 3226, "anceps": 8, "bare": 3, "hidden": 1}
# The Latin circumflex class is closed the same way the mark classes in check
# 10 are: the source count is exact and nothing may survive into the records.
# A hit-count alone would not catch a ninth site appearing in a re-fetched
# source -- the eight keys would still land, the tally would still read 8, and
# the new one would ship unrepaired.
LATIN_CIRCUMFLEX = "̂"
EXPECTED_SOURCE_LATIN_CIRCUMFLEX = 8
# Instances over the records' html and plain fields (8 tree sites, twice each).
EXPECTED_ANCEPS_INSTANCES = 16
# Frozen readings, print-audited like the rest: a restacked verb beside a kept
# anceps pair, the restacked rough breathing, a capital, the ἄλλο̄ς-class bare
# omicron beside a restacked iota, and the deictic iota DASIA_FIXES restores.
MACRON_READINGS = (
    (687, "φῡ́ω (φῠ̄-)"),
    # The whole Sec. 305 paradigm: two restacked by rule, the neuter by the
    # LATIN_CIRCUMFLEX_FIXES table.
    (305, "ᾱ̓́κων, ᾱ̓́κουσα, ᾱ̓͂κον"),
    (325, "ῡ̔μεῖς"),
    (9, "(Ᾱ̔́ιδης)"),
    (144, "ἄλλο̄ς πολῑ́της"),
    (607, "ending in ῐ̄, ῠ̄, or"),
    (1178, "οὑτοσῑ́"),
)

REQUIRED_KEYS = {
    "work",
    "n",
    "id",
    "letters",
    "dialectNotes",
    "path",
    "head",
    "html",
    "plain",
    "examples",
    "refs",
    "refRanges",
    "citedBy",
    "prev",
    "next",
}


def norm(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


BARE_JOIN_RE = re.compile(r"^[\s,;:.]*$")
BARE_MERGE_RE = re.compile(r"^[\s,;.]*$")
BARE_GLOSS_TAIL_RE = re.compile(r"^[\s,;:.()]*$")
BARE_PAREN_OPENS_RE = re.compile(r"^[\s,;:.]*\(")
BARE_PAREN_CLOSES_RE = re.compile(r"^[\s,;:.]*\)[\s,;]*$")
BARE_PAREN_ASIDE_RE = re.compile(r"^[\s,;:.]*\([^()]*\)[\s,;]*$")


def bare_example_counts(root: ET.Element) -> tuple[int, int]:
    """(everywhere, inside smythp nodes) counts of un-wrapped examples.

    Re-derives the converter's bare-example shape independently: one or more
    ``foreign lang="greek"`` siblings, then optional ``gloss`` siblings, then a
    ``bibl``, joined by punctuation alone and outside any ``cit``, and neither
    crossing a bracket nor starting on the far side of one.  The converter's
    records hold the ones inside ``smythp`` nodes plus those in the unnumbered
    blocks it attaches to a prior section, so its count must fall between the
    two numbers returned here.

    This is a headcount, and a headcount only.  It re-states the converter's
    chain rules, so it agrees with a converter that mis-chains; what it can
    prove is that ``meta.bareExamples`` is not fabricated.  Check 13 is the one
    that reads the print's own text.
    """
    parents = {child: parent for parent in root.iter() for child in parent}

    def within(elem: ET.Element, test) -> bool:
        current: ET.Element | None = elem
        while current is not None:
            if test(current):
                return True
            current = parents.get(current)
        return False

    def greek(elem: ET.Element) -> bool:
        return elem.tag == "foreign" and (elem.get("lang") or "").lower() == "greek"

    def after_bracket(children: list[ET.Element], start: int) -> bool:
        """The chain would start on the far side of a bracket cut into a run."""
        if start == 0:
            return False
        before = children[start - 1]
        if greek(before) and BARE_PAREN_ASIDE_RE.match(before.tail or ""):
            return True
        if not BARE_PAREN_CLOSES_RE.match(before.tail or ""):
            return False
        index = start - 1
        while index > 0:
            tail = children[index - 1].tail or ""
            if ")" in tail:
                return False
            if "(" in tail:
                return bool(BARE_PAREN_OPENS_RE.match(tail)) and greek(children[index - 1])
            index -= 1
        return False

    everywhere = inside = 0
    for parent in root.iter():
        # A page break with only punctuation in its tail does not break the
        # chain (the converter drops it the same way).
        children = [
            child
            for child in parent
            if not (child.tag == "pb" and BARE_JOIN_RE.match(child.tail or ""))
        ]
        index = 0
        while index < len(children):
            child = children[index]
            if not greek(child) or within(child, lambda item: item.tag == "cit"):
                index += 1
                continue
            if after_bracket(children, index):
                index += 1
                continue
            end = index
            while (
                end + 1 < len(children)
                and greek(children[end + 1])
                and BARE_MERGE_RE.match(children[end].tail or "")
            ):
                end += 1
            after = end + 1
            if BARE_JOIN_RE.match(children[end].tail or ""):
                while (
                    after < len(children)
                    and children[after].tag == "gloss"
                    and BARE_GLOSS_TAIL_RE.match(children[after].tail or "")
                ):
                    after += 1
                if after < len(children) and children[after].tag == "bibl" and norm(
                    "".join(text for item in children[index : end + 1] for text in item.itertext())
                ):
                    everywhere += 1
                    if within(child, lambda item: item.get("type") == "smythp"):
                        inside += 1
                    index = after + 1
                    continue
            index = end + 1
    return everywhere, inside


def section_number(elem: ET.Element) -> int | None:
    match = SECTION_RE.match(elem.get("n", ""))
    return int(match.group(1)) if match else None


def target_number(elem: ET.Element) -> int | None:
    value = elem.get("target") or elem.get("n") or norm("".join(elem.itertext()))
    match = re.search(r"\d+", value)
    return int(match.group()) if match else None


# Check 13 reads the print's own characters rather than the converter's chain
# rules.  A quotation the print cut in two with a bracket leaves a closing
# bracket and then Greek again, and the words on the far side are the end of
# the same quotation, not an example of their own.  RESUME_JOIN is what may
# stand between the bracket and the words without ending the sentence: a colon
# or a full stop does end it, and what follows is a fresh lemma or a fresh
# example, so neither is here.
RESUME_JOIN = " ,;"
GREEK_LAST_RE = re.compile(r"[Ͱ-Ͽἀ-῿]$")
# Trimmed off a word before the gap sigil is looked for in the built text.
GAP_WORD_TRIM = "()[],.;:·—-\"'“”‘’ "
# The one gap-sigil word that does not survive, and why: Sec. 2749's source reads
# "οι<*>῀όν", the sigil standing where the breathing belongs, and repair_marks
# reads the stranded circumflex and prints οἷόν.  Every other one is carried
# verbatim (see GAP_SIGIL in convert_smyth.py).  Any further loss fails.
GAP_WORDS_REPAIRED = {"οι<*>ον"}


def letters_only(value: str) -> str:
    """``value`` with every diacritic dropped, spacing marks included.

    The converter repairs stranded and spacing marks on the tree before it
    writes anything, so a source reading and its built reading differ in their
    marks by design.  Comparing the letters alone lets a check match the two
    without repeating any of that work.
    """
    stripped = "".join(
        char
        for char in unicodedata.normalize("NFD", value)
        if unicodedata.category(char) not in {"Mn", "Sk"}
    )
    return norm(unicodedata.normalize("NFC", stripped))


def resumes_after_bracket(plain: str, position: int) -> bool:
    """True when the print closed a bracket on Greek just before ``position``."""
    prefix = plain[:position].rstrip(RESUME_JOIN)
    if not prefix.endswith(")"):
        return False
    depth = 0
    index = len(prefix) - 1
    while index >= 0:
        if prefix[index] == ")":
            depth += 1
        elif prefix[index] == "(":
            depth -= 1
            if depth == 0:
                break
        index -= 1
    if index < 0:
        return False
    return bool(GREEK_LAST_RE.search(prefix[:index].rstrip(RESUME_JOIN)))


def source_ranges(root: ET.Element) -> list[tuple[int, int]]:
    """Derive cross-ref ranges without using converter code or metadata."""
    found: list[tuple[int, int]] = []

    def add(start: int | None, end: int | None) -> None:
        if start is not None and end is not None and (start, end) not in found:
            found.append((start, end))

    for parent in root.iter():
        children = list(parent)
        for index, child in enumerate(children):
            if child.tag != "ref":
                continue
            target = target_number(child)
            display = norm("".join(child.itertext()))
            inside = re.search(r"\b(\d+)\s*[-\u2013\u2014]\s*(\d+)\b", display)
            if inside:
                add(int(inside.group(1)), int(inside.group(2)))
            tail = child.tail or ""
            plain = re.match(r"\s*[-\u2013\u2014]\s*(\d+)", tail)
            if plain:
                add(target, int(plain.group(1)))
            elif (
                re.match(r"\s*[-\u2013\u2014]\s*$", tail)
                and index + 1 < len(children)
                and children[index + 1].tag == "ref"
            ):
                add(target, target_number(children[index + 1]))
    return found


class HtmlAudit(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, bool]] = []
        self.greek_outside_lang: list[str] = []
        self.refs: list[str] = []
        self.ids: list[str] = []
        self.ref_anchors: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        self.stack.append((tag, values.get("lang") == "grc"))
        if values.get("id"):
            self.ids.append(values["id"] or "")
        if tag == "a" and values.get("data-ref"):
            self.refs.append(values["data-ref"] or "")
            if values.get("data-anchor"):
                self.ref_anchors.append(values["data-anchor"] or "")

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.append(values["id"] or "")

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                self.stack = self.stack[:index]
                return

    def handle_data(self, data: str) -> None:
        if GREEK_RE.search(data) and not any(item[1] for item in self.stack):
            value = norm(data)
            if value:
                self.greek_outside_lang.append(value[:100])


class Report:
    def __init__(self) -> None:
        self.results: list[tuple[str, str, str]] = []

    def add(self, number: int, ok: bool, title: str, detail: str) -> None:
        status = "PASS" if ok else "FAIL"
        self.results.append((status, f"{number}. {title}", detail))
        print(f"[{status}] {number}. {title}")
        for line in detail.splitlines():
            print(f"  {line}")

    def warn(self, title: str, detail: str) -> None:
        self.results.append(("WARN", title, detail))
        print(f"[WARN] {title}")
        for line in detail.splitlines():
            print(f"  {line}")

    def summary(self) -> bool:
        passed = sum(status == "PASS" for status, _, _ in self.results)
        failed = sum(status == "FAIL" for status, _, _ in self.results)
        warned = sum(status == "WARN" for status, _, _ in self.results)
        print("\nVERIFY REPORT SUMMARY")
        print(f"  acceptance checks: {passed} passed, {failed} failed")
        print(f"  sanity warnings: {warned}")
        print(f"  overall: {'PASS' if failed == 0 else 'FAIL'}")
        return failed == 0


def load_records(path: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number}: record is not an object")
            records.append(value)
    return records


def combined_hash(sections: Path, meta: Path) -> str:
    digest = hashlib.sha256()
    digest.update(sections.read_bytes())
    digest.update(b"\0")
    digest.update(meta.read_bytes())
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--sections", type=Path, default=DEFAULT_SECTIONS)
    parser.add_argument("--meta", type=Path, default=DEFAULT_META)
    parser.add_argument("--converter", type=Path, default=DEFAULT_CONVERTER)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    report = Report()
    root = ET.parse(args.input).getroot()
    records = load_records(args.sections)
    meta = json.loads(args.meta.read_text(encoding="utf-8"))
    record_by_id = {str(record.get("id")): record for record in records}
    record_by_n = {int(record["n"]): record for record in records if "n" in record}

    # 1. Extraction and numbering.
    smythp = [elem for elem in root.iter() if elem.get("type") == "smythp"]
    base_labels: list[int] = []
    for elem in smythp:
        match = SECTION_RE.match(elem.get("n", ""))
        if match and not match.group(2).strip():
            base_labels.append(int(match.group(1)))
    base_counts = collections.Counter(base_labels)
    gaps = [number for number in range(1, 3049) if base_counts[number] == 0]
    duplicates = {
        number: count for number, count in sorted(base_counts.items()) if count > 1
    }
    data_gaps = [number for number in range(1, 3049) if number not in record_by_n]
    source_repeat_numbers = len(
        {
            section_number(elem)
            for elem in smythp
            if sum(section_number(other) == section_number(elem) for other in smythp) > 1
        }
    )
    one_ok = (
        len(smythp) == int(meta["counts"]["smythpNodes"])
        and len(base_labels) == 3048
        and len(records) == 3048
        and not gaps
        and not duplicates
        and not data_gaps
        and set(record_by_n) == set(base_labels)
    )
    report.add(
        1,
        one_ok,
        "section extraction and numbering",
        f"source smythp nodes={len(smythp)}; base sections={len(base_labels)}; records={len(records)}\n"
        f"coverage gaps={gaps}; base duplicates={duplicates}; data gaps={data_gaps}\n"
        f"numbers repeated only by suffixed source nodes={source_repeat_numbers} "
        f"(full labels are in meta anomalies)",
    )

    # 2. Shape, IDs, and non-empty text.
    bad_shape: list[object] = []
    for record in records:
        missing = sorted(REQUIRED_KEYS - set(record))
        record_id = str(record.get("id", ""))
        number = record.get("n")
        if (
            missing
            or record.get("work") != "smyth"
            or not ID_RE.fullmatch(record_id)
            or record_id != f"smyth:{number}"
            or not str(record.get("html", "")).strip()
            or not str(record.get("plain", "")).strip()
        ):
            bad_shape.append(
                {"n": number, "missing": missing, "id": record_id}
            )
    report.add(
        2,
        not bad_shape,
        "record shape, IDs, and text",
        f"bad records={len(bad_shape)}; examples={bad_shape[:5]}",
    )

    # 3. Cross-references and ranges.
    refs = list(root.iter("ref"))
    malformed_source_refs = [ref for ref in refs if target_number(ref) is None]
    unresolved_source_refs = [
        (target_number(ref), norm("".join(ref.itertext())))
        for ref in refs
        if target_number(ref) is not None and target_number(ref) not in record_by_n
    ]
    bad_record_refs = [
        (record["id"], target)
        for record in records
        for target in record["refs"]
        if target not in record_by_id
    ]
    expected_ranges = source_ranges(root)
    meta_ranges = [
        (int(item["start"]), int(item["end"])) for item in meta["crossRefRanges"]
    ]
    record_ranges = [
        (int(item["start"]), int(item["end"]))
        for record in records
        for item in record["refRanges"]
    ]
    bad_ranges = [
        value
        for value in meta_ranges + record_ranges
        if value[0] not in record_by_n
        or value[1] not in record_by_n
        or value[0] > value[1]
    ]
    ranges_match = expected_ranges == meta_ranges
    record_range_set = set(record_ranges)
    ranges_outside_records = [value for value in expected_ranges if value not in record_range_set]
    reported_outside_ranges = [
        (int(item["start"]), int(item["end"]))
        for item in meta["anomalies"]["rangesOutsideSections"]
    ]
    three_ok = (
        len(refs) >= 3700
        and not malformed_source_refs
        and not unresolved_source_refs
        and not bad_record_refs
        and not bad_ranges
        and ranges_match
        and ranges_outside_records == reported_outside_ranges
    )
    report.add(
        3,
        three_ok,
        "cross-references and ranges",
        f"source ref count={len(refs)} (sanity minimum 3700); "
        f"unique record edges={sum(len(record['refs']) for record in records)}; "
        f"source refs outside section records={meta['counts']['crossRefsOutsideSections']}\n"
        f"unresolved source singles={len(unresolved_source_refs)}; bad record refs={len(bad_record_refs)}\n"
        f"distinct source ranges={len(expected_ranges)}; meta ranges={len(meta_ranges)}; "
        f"record range uses={len(record_ranges)}; bad endpoints={bad_ranges[:5]}\n"
        f"ranges in structural headings or the verb appendix={ranges_outside_records}\n"
        f"ranges={expected_ranges}",
    )

    # 4. citedBy inversion.
    inverse: dict[str, list[str]] = {record_id: [] for record_id in record_by_id}
    for record in records:
        for target in record["refs"]:
            if target in inverse:
                inverse[target].append(record["id"])
    inverse_mismatches = [
        record_id
        for record_id, record in record_by_id.items()
        if record["citedBy"] != inverse[record_id]
    ]
    report.add(
        4,
        not inverse_mismatches,
        "citedBy exact inverse",
        f"mismatched records={len(inverse_mismatches)}; examples={inverse_mismatches[:10]}",
    )

    # 5. Quotes, bibliographies, passage cites, and example cites.
    quotes = list(root.iter("quote"))
    bibls = list(root.iter("bibl"))
    citations = list(root.iter("cit"))
    passage_bibls = [
        bibl
        for bibl in bibls
        if (bibl.get("n") or norm("".join(bibl.itertext())))
        and not (bibl.get("n") or "").startswith(LSJ_PREFIX)
    ]
    lsj_bibls = [
        bibl for bibl in bibls if (bibl.get("n") or "").startswith(LSJ_PREFIX)
    ]
    source_paired = [citation.find("bibl") for citation in citations]
    output_examples = [example for record in records for example in record["examples"]]
    missing_output_cites = [
        (record["id"], index)
        for record in records
        for index, example in enumerate(record["examples"])
        if not str(example.get("cite", "")).strip()
    ]
    bare_everywhere, bare_in_smythp = bare_example_counts(root)
    bare_reported = int(meta["counts"]["bareExamples"])
    bare_outside = int(meta["counts"]["bareExamplesOutsideSections"])
    five_ok = (
        len(output_examples) == len(citations) + bare_reported
        and bare_reported + bare_outside == bare_everywhere
        and bare_in_smythp <= bare_reported <= bare_everywhere
        and all(item is not None for item in source_paired)
        and not missing_output_cites
        and int(meta["counts"]["quotes"]) == len(quotes)
        and int(meta["counts"]["bibliographies"]) == len(bibls)
        and int(meta["counts"]["passageCitations"]) == len(passage_bibls)
    )
    report.add(
        5,
        five_ok,
        "example and citation counts",
        f"quote tags={len(quotes)}; bibl tags={len(bibls)}; cit/example pairs={len(citations)}\n"
        f"bare foreign/gloss/bibl examples: in records={bare_reported} (meta), "
        f"in smythp nodes={bare_in_smythp}, everywhere={bare_everywhere} "
        f"(outside records per meta={bare_outside}); output examples={len(output_examples)}\n"
        f"passage citations={len(passage_bibls)}; LSJ appendix citations={len(lsj_bibls)}\n"
        f"examples without paired cite={len(missing_output_cites)}; examples={missing_output_cites[:5]}",
    )
    if not 4900 <= len(passage_bibls) <= 5000:
        report.warn(
            "passage-citation sanity range",
            f"expected about 4900-5000, found {len(passage_bibls)}. "
            f"Examples beyond the range: {[b.get('n') or norm(''.join(b.itertext())) for b in passage_bibls[-5:]]}",
        )

    # 6. Letter and dialect anchors.
    bad_letters: list[object] = []
    duplicate_html_ids: list[object] = []
    dialect_count = 0
    sections_with_dialect = 0
    audits: dict[int, HtmlAudit] = {}
    for record in records:
        audit = HtmlAudit()
        audit.feed(str(record["html"]))
        audits[int(record["n"])] = audit
        repeated_ids = [
            value for value, count in collections.Counter(audit.ids).items() if count > 1
        ]
        if repeated_ids:
            duplicate_html_ids.append((record["id"], repeated_ids))
        for anchor in record["letters"]:
            if not LETTER_RE.fullmatch(str(anchor)) or anchor not in audit.ids:
                bad_letters.append((record["id"], anchor))
        notes = record["dialectNotes"]
        if notes:
            sections_with_dialect += 1
        dialect_count += len(notes)
        for index, note in enumerate(notes):
            expected_anchor = "D" if index == 0 else f"D{index}"
            if (
                note.get("anchor") != expected_anchor
                or note.get("dialect") is not True
                or expected_anchor not in audit.ids
            ):
                bad_letters.append((record["id"], note))
    source_dialects = [
        elem
        for elem in smythp
        if SECTION_RE.match(elem.get("n", ""))
        and SECTION_RE.match(elem.get("n", "")).group(2).strip()
    ]
    six_ok = (
        not bad_letters
        and not duplicate_html_ids
        and dialect_count == len(source_dialects)
        and dialect_count == int(meta["counts"]["dialectNotes"])
    )
    report.add(
        6,
        six_ok,
        "lettered subsections and dialect notes",
        f"sections with letters={sum(bool(record['letters']) for record in records)}; "
        f"letter anchors={sum(len(record['letters']) for record in records)}\n"
        f"sections with dialect notes={sections_with_dialect}; dialect notes={dialect_count}\n"
        f"bad anchors={bad_letters[:10]}; duplicate HTML IDs={duplicate_html_ids[:5]}",
    )

    # 7. HTML rules.
    greek_outside = [
        (number, text)
        for number, audit in audits.items()
        for text in audit.greek_outside_lang
    ]
    bad_tei = [
        record["id"]
        for record in records
        if re.search(
            r"TEIform|xmlns|lang=\"greek\"|<(?:TEI\.2|foreign|gloss|emph|ref|cit|bibl)\b",
            str(record["html"]),
        )
    ]
    bad_placeholders = [
        (number, value)
        for number, audit in audits.items()
        for value in audit.refs
        if not ID_RE.fullmatch(value)
    ]
    html_ref_count = sum(len(audit.refs) for audit in audits.values())
    anchor_ref_count = sum(len(audit.ref_anchors) for audit in audits.values())
    bad_ref_anchors = [
        value
        for audit in audits.values()
        for value in audit.ref_anchors
        if not re.fullmatch(r"[a-z]", value)
    ]
    # "2326 d" cites a subsection; the placeholder has to keep the "d".
    source_lettered = sum(
        1
        for ref in root.iter("ref")
        if re.fullmatch(r"\s*\d+\s+[a-eg-z]\.?\s*", ref.get("n", ""))
    )
    # Greek in the source mixes precomposed and decomposed spellings; the data
    # must land on one, so that equal words compare equal.
    unnormalized = [
        record["id"]
        for record in records
        if unicodedata.normalize("NFC", str(record["html"])) != str(record["html"])
        or unicodedata.normalize("NFC", str(record["plain"])) != str(record["plain"])
    ]
    seven_ok = (
        not greek_outside
        and not bad_tei
        and not bad_placeholders
        and not bad_ref_anchors
        and not unnormalized
        and html_ref_count == int(meta["counts"]["sectionCrossRefs"])
    )
    report.add(
        7,
        seven_ok,
        "normalized HTML",
        f"Greek text outside lang=grc={len(greek_outside)}; examples={greek_outside[:5]}\n"
        f"records with TEI leakage={len(bad_tei)}; bad data-ref values={bad_placeholders[:5]}\n"
        f"HTML ref placeholders={html_ref_count}; source refs assigned to sections={meta['counts']['sectionCrossRefs']}\n"
        f"subsection-anchored placeholders={anchor_ref_count} of {source_lettered} lettered source refs; "
        f"bad anchors={bad_ref_anchors[:5]}\n"
        f"records not in Unicode NFC={len(unnormalized)}; examples={unnormalized[:5]}",
    )

    # 8. Navigation and paths.
    chain_errors: list[object] = []
    for index, record in enumerate(records):
        expected_prev = records[index - 1]["id"] if index else None
        expected_next = records[index + 1]["id"] if index + 1 < len(records) else None
        if record["prev"] != expected_prev or record["next"] != expected_next:
            chain_errors.append(
                (record["id"], record["prev"], record["next"])
            )
        if (
            not isinstance(record["path"], list)
            or not record["path"]
            or any(not str(item).strip() for item in record["path"])
        ):
            chain_errors.append((record["id"], "bad path", record["path"]))
    toc_ok = bool(meta.get("toc")) and all(
        int(part["start"]) <= int(part["end"]) for part in meta["toc"]
    )
    # Bounds alone would not notice a chapter dropped from the tree, so walk
    # the chapters and demand that they reach every section that exists.
    toc_covered: set[int] = set()
    for part in meta.get("toc", []):
        for chapter in part["chapters"]:
            toc_covered |= set(range(int(chapter["start"]), int(chapter["end"]) + 1))
        if int(part["start"]) != min(
            int(chapter["start"]) for chapter in part["chapters"]
        ) or int(part["end"]) != max(
            int(chapter["end"]) for chapter in part["chapters"]
        ):
            toc_ok = False
    uncovered = sorted(set(record_by_n) - toc_covered)
    report.add(
        8,
        not chain_errors and toc_ok and not uncovered,
        "navigation chains, paths, and TOC",
        f"chain/path errors={len(chain_errors)}; examples={chain_errors[:5]}\n"
        f"TOC parts={len(meta.get('toc', []))}; TOC bounds valid={toc_ok}\n"
        f"sections absent from every TOC chapter={len(uncovered)}; examples={uncovered[:8]}",
    )

    # 9. Determinism.
    determinism_error = ""
    hashes: list[str] = []
    current_hash = combined_hash(args.sections, args.meta)
    try:
        with tempfile.TemporaryDirectory(prefix="verify-smyth-") as temp_name:
            temp = Path(temp_name)
            for run in (1, 2):
                out_sections = temp / f"sections-{run}.jsonl"
                out_meta = temp / f"meta-{run}.json"
                completed = subprocess.run(
                    [
                        sys.executable,
                        str(args.converter),
                        "--input",
                        str(args.input),
                        "--sections",
                        str(out_sections),
                        "--meta",
                        str(out_meta),
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                if completed.returncode != 0:
                    raise RuntimeError(
                        f"converter run {run} failed: {completed.stderr.strip()}"
                    )
                hashes.append(combined_hash(out_sections, out_meta))
    except Exception as error:  # report the failure instead of hiding the other checks
        determinism_error = str(error)
    nine_ok = (
        not determinism_error
        and len(hashes) == 2
        and hashes[0] == hashes[1]
        and hashes[0] == current_hash
    )
    report.add(
        9,
        nine_ok,
        "deterministic conversion",
        f"checked-in hash={current_hash}\nrun hashes={hashes}\nerror={determinism_error or 'none'}",
    )

    # 10. Stranded source diacritics.
    # Perseus keyed an ASCII apostrophe wherever it did not place a small mark
    # on a letter, so the source carries U+1FBD standing after a vowel where a
    # breathing, a numeral keraia, or an accent belongs; convert_smyth.py
    # explains the classification.  A koronis after a consonant is ordinary
    # elision and stays.  Only the six words the print really spells with a
    # trailing apostrophe may still show a koronis after a vowel, and every
    # distinct repair has to reproduce its audited reading, so that editing a
    # repair table without re-auditing the print fails here.
    source_text = unicodedata.normalize("NFD", args.input.read_text(encoding="utf-8"))
    source_vowel_sites = len(VOWEL_KORONIS_RE.findall(source_text))
    surviving: collections.Counter[str] = collections.Counter()
    for record in records:
        for field in ("html", "plain"):
            for token in GREEK_TOKEN_RE.findall(str(record[field])):
                if VOWEL_KORONIS_RE.search(unicodedata.normalize("NFD", token)):
                    surviving[token] += 1
    stray = sorted(set(surviving) - ALLOWED_VOWEL_KORONIS)
    misread = [
        (number, reading)
        for number, reading in EXPECTED_READINGS
        if reading not in str(record_by_n.get(number, {}).get("plain", ""))
    ]
    numerals = str(record_by_n.get(347, {}).get("plain", ""))
    repairs = meta["anomalies"]["sourceMarkRepairs"]
    counted = (
        repairs["koronisComposed"],
        repairs["keraiaRestored"],
        repairs["koronisKeptAsElision"],
    )

    # Six more placeholder characters, repaired the same way; each table in
    # convert_smyth.py is a closed, print-audited enumeration, so the source
    # counts, repair tallies, and audited readings below are all exact, not
    # just lower bounds.  Counted against an NFC (not NFD) copy of the source:
    # DASIA_OXIA and DASIA_PERISPOMENI have canonical decompositions into
    # DASIA plus a combining accent, so NFD -- used above for the koronis
    # check -- silently zeroes both counts and inflates DASIA's.
    source_nfc = unicodedata.normalize("NFC", args.input.read_text(encoding="utf-8"))
    new_mark_source_counts = {
        mark: source_nfc.count(mark) for mark in EXPECTED_SOURCE_MARK_COUNTS
    }
    new_mark_repairs = {key: repairs[key] for key in EXPECTED_NEW_MARK_REPAIRS}
    new_misread = [
        (number, reading)
        for number, reading in NEW_MARK_READINGS
        if reading not in str(record_by_n.get(number, {}).get("plain", ""))
    ]
    psili_counts = {
        "source": source_nfc.count(PSILI),
        "remaining": sum(
            str(record[field]).count(PSILI)
            for record in records
            for field in ("plain",)
        ),
    }
    accent_counts = {
        mark: sum(str(record["plain"]).count(mark) for record in records)
        for mark in EXPECTED_SPACING_ACCENTS
    }
    accents_on_vowels = [
        (record["n"], str(record["plain"])[max(0, index - 20) : index + 6])
        for record in records
        for mark in EXPECTED_SPACING_ACCENTS
        for index in [
            m.start() for m in re.finditer(re.escape(mark), str(record["plain"]))
        ]
        if index
        and unicodedata.normalize("NFD", str(record["plain"])[index - 1])[:1]
        in "αειουηωΑΕΙΟΥΗΩ"
    ]
    leftover_marks = {
        mark: sum(
            str(record[field]).count(mark)
            for record in records
            for field in ("html", "plain")
        )
        for mark in EXPECTED_SOURCE_MARK_COUNTS
    }

    ten_ok = (
        source_text.count(KORONIS) == 1428
        and source_vowel_sites == 149
        and not stray
        and not misread
        and not repairs["koronisUnclassified"]
        and counted == EXPECTED_MARK_REPAIRS
        and KORONIS not in numerals
        and numerals.count(KERAIA) == 37
        and new_mark_source_counts == EXPECTED_SOURCE_MARK_COUNTS
        and new_mark_repairs == EXPECTED_NEW_MARK_REPAIRS
        and not new_misread
        and not any(leftover_marks.values())
        and psili_counts == EXPECTED_PSILI
        and accent_counts == EXPECTED_SPACING_ACCENTS
        and not accents_on_vowels
    )
    report.add(
        10,
        ten_ok,
        "stranded source diacritics",
        f"source koronis={source_text.count(KORONIS)} of which after a vowel="
        f"{source_vowel_sites}\n"
        f"repaired (composed, keraia, kept as apostrophe)={counted}, "
        f"expected {EXPECTED_MARK_REPAIRS}\n"
        f"unclassified tokens={repairs['koronisUnclassified']}\n"
        f"words still showing a koronis after a vowel={dict(surviving)}\n"
        f"unexpected among them={stray}\n"
        f"audited readings checked={len(EXPECTED_READINGS)}, not reproduced={misread}\n"
        f"Sec. 347 numerals: keraia={numerals.count(KERAIA)} of 37, "
        f"koronis left={numerals.count(KORONIS)}\n"
        f"other placeholder marks in source={new_mark_source_counts}, "
        f"expected {EXPECTED_SOURCE_MARK_COUNTS}\n"
        f"other placeholder repairs={new_mark_repairs}, "
        f"expected {EXPECTED_NEW_MARK_REPAIRS}\n"
        f"other audited readings checked={len(NEW_MARK_READINGS)}, "
        f"not reproduced={new_misread}\n"
        f"other placeholder marks left in records={leftover_marks}\n"
        f"psili: {psili_counts}, expected {EXPECTED_PSILI} "
        f"(17 composed, 9 aphaeresis moved onto U+1FBD)\n"
        f"spacing accents left={accent_counts}, expected "
        f"{EXPECTED_SPACING_ACCENTS} (Sanskrit and gap markers)\n"
        f"spacing accents still standing after a Greek vowel="
        f"{accents_on_vowels}",
    )

    # 11. Resolved glyph placeholders.
    plain_all = "\n".join(str(record["plain"]) for record in records)
    glyph_counts = {target: plain_all.count(target) for target in RESOLVED_GLYPHS}
    stray_placeholders = sorted(
        {
            found
            for found in GLYPH_PLACEHOLDER_RE.findall(plain_all)
            # Smyth's own editorial brackets are not placeholders: they hold
            # Greek or a citation, never a lower-case ASCII glyph name.
            if re.fullmatch(r"\[[a-z][a-z ]*\]", found)
        }
        - UNRESOLVED_GLYPHS
    )
    numeral_plain = str(record_by_n.get(347, {}).get("plain", ""))
    numeral_prose = str(record_by_n.get(348, {}).get("plain", ""))
    wrong_signs = [
        (value, sign)
        for value, sign in PRINTED_NUMERALS.items()
        if numeral_plain.count(f" {value} {sign}{KERAIA} ") != 1
    ]
    missing_prose = [t for t in PRINTED_NUMERAL_PROSE if t not in numeral_prose]
    numeral_repairs = {k: repairs[k] for k in EXPECTED_NUMERAL_REPAIRS}
    retired_present = {
        target: plain_all.count(target)
        for target in RETIRED_GLYPHS
        if target in plain_all
    }
    eleven_ok = (
        glyph_counts == RESOLVED_GLYPHS
        and not stray_placeholders
        and not retired_present
        and not wrong_signs
        and not missing_prose
        and numeral_repairs == EXPECTED_NUMERAL_REPAIRS
    )
    report.add(
        11,
        eleven_ok,
        "resolved glyphs and the numeral table",
        f"resolved glyphs={glyph_counts}, expected {RESOLVED_GLYPHS}\n"
        f"placeholders left unresolved={sorted(UNRESOLVED_GLYPHS)} (no Unicode target)\n"
        f"unexpected placeholders reaching the data={stray_placeholders}\n"
        f"retired targets found again={retired_present}\n"
        f"Sec. 347 signs matching the print={len(PRINTED_NUMERALS) - len(wrong_signs)}"
        f" of {len(PRINTED_NUMERALS)}; wrong={wrong_signs}\n"
        f"Sec. 348 printed readings missing={missing_prose}\n"
        f"numeral repairs={numeral_repairs}, expected {EXPECTED_NUMERAL_REPAIRS}",
    )

    # 12. Macron stacking.
    # The invariant is positional, like the spacing-accent one in check 10: in
    # the built records no combining macron may follow a letter carrying any
    # other mark, because the converter must have moved it innermost.  The
    # source counts pin the converter's tallies to the source, and the frozen
    # readings pin the letters, so a restack rule edited to the wrong base
    # fails here rather than shipping.
    source_macrons = {"stacked": 0, "anceps": 0, "bare": 0, "hidden": 0}
    for match in STACKED_MACRON_RE.finditer(source_nfc):
        parts = unicodedata.normalize("NFD", match.group(1))
        if parts[0] not in GREEK_VOWELS or len(parts) == 1:
            source_macrons["bare"] += 1
        elif BREVE in parts[1:]:
            source_macrons["anceps"] += 1
        else:
            source_macrons["stacked"] += 1
    source_macrons["hidden"] = source_nfc.count(MACRON) - sum(source_macrons.values())
    # Walked back over combining marks to the carrier, so that a macron whose
    # letter is hidden behind another mark -- the shape that let Sec. 305's
    # ἀ̂̄κον through a letter-anchored regex -- lands in a bucket instead of
    # nowhere.  A carrier that is not a Greek letter at all is its own line.
    stacked_left: list[tuple[object, str]] = []
    orphan_macrons: list[tuple[object, str]] = []
    anceps_instances = 0
    for record in records:
        for field in ("html", "plain"):
            text = str(record[field])
            for index in [m.start() for m in re.finditer(MACRON, text)]:
                back = index
                while back and unicodedata.combining(text[back - 1]):
                    back -= 1
                carrier = text[back - 1] if back else ""
                between = text[back:index]
                parts = unicodedata.normalize("NFD", carrier)
                context = text[max(0, index - 20) : index + 6]
                if not GREEK_RE.match(carrier):
                    orphan_macrons.append((record["n"], context))
                elif BREVE in parts[1:] or BREVE in between:
                    anceps_instances += 1
                elif len(parts) > 1 or between:
                    stacked_left.append((record["n"], context))
    macron_repairs = {key: repairs[key] for key in EXPECTED_MACRON_REPAIRS}
    source_latin_circumflex = source_nfc.count(LATIN_CIRCUMFLEX)
    latin_circumflex_left = sum(
        str(record[field]).count(LATIN_CIRCUMFLEX)
        for record in records
        for field in ("html", "plain")
    )
    macron_misread = [
        (number, reading)
        for number, reading in MACRON_READINGS
        if reading not in str(record_by_n.get(number, {}).get("plain", ""))
    ]
    twelve_ok = (
        source_macrons == EXPECTED_SOURCE_MACRONS
        and macron_repairs == EXPECTED_MACRON_REPAIRS
        and not stacked_left
        and not orphan_macrons
        and anceps_instances == EXPECTED_ANCEPS_INSTANCES
        and not macron_misread
        and source_latin_circumflex == EXPECTED_SOURCE_LATIN_CIRCUMFLEX
        and not latin_circumflex_left
    )
    report.add(
        12,
        twelve_ok,
        "macron stacking",
        f"source macrons={source_macrons}, "
        f"expected {EXPECTED_SOURCE_MACRONS}\n"
        f"restacked={macron_repairs}, expected {EXPECTED_MACRON_REPAIRS}\n"
        f"macrons still outside another mark={len(stacked_left)}; "
        f"examples={stacked_left[:5]}\n"
        f"macrons on a non-Greek carrier={len(orphan_macrons)}; "
        f"examples={orphan_macrons[:5]}\n"
        f"anceps (breve+macron) instances={anceps_instances}, "
        f"expected {EXPECTED_ANCEPS_INSTANCES}\n"
        f"audited readings checked={len(MACRON_READINGS)}, "
        f"not reproduced={macron_misread}\n"
        f"Latin circumflexes in source={source_latin_circumflex}, "
        f"expected {EXPECTED_SOURCE_LATIN_CIRCUMFLEX}; "
        f"left in records={latin_circumflex_left}",
    )

    # 13. Examples against the print's own text.
    # Check 5 counts examples; it cannot see one.  Fed a truncated quotation it
    # reports the same two integers as a sound one, because both its rules and
    # the converter's are the same rules.  This check reads the characters the
    # print set instead, in the records the converter wrote, and knows nothing
    # about sibling chains:
    #   a. an example's Greek is a run of its own section's text.  A merge that
    #      swallowed a lemma across a colon (Sec. 2479's "ὥσπερ εἰ: θαυμάζω δέ σε")
    #      is not, because the colon between them is gone from it.
    #   b. no example begins where the print resumed a quotation it had cut with
    #      a bracket, unless the source itself wraps that Greek in a cit.  This
    #      is the shape the review found 40 of: Sec. 978's "ὤν, πόλεως τῆς μεγίστης"
    #      under the translation of "Ἀθηναῖος ( = Ἀθηνῶν) ὤν, πόλεως τῆς μεγίστης".
    #   c. the gap sigil the source writes survives into the built text, and the
    #      html field escapes exactly the sigils the plain field carries.
    # The cit exemption in (b) is not an excuse: the source's own cit elements
    # hold 110 examples of the same shape, because Perseus wrapped the fragment
    # and left the head of the quotation outside.  That is a defect in the cit
    # path, it is unchanged by this check, and it is reported as a warning with
    # its count so a rise in it is visible.
    cit_quotes = {
        letters_only("".join(quote.itertext()))
        for cit in root.iter("cit")
        for quote in cit.iter("quote")
        if (quote.get("lang") or "").lower() == "greek"
    }
    not_the_print: list[object] = []
    bare_resumed: list[object] = []
    cit_resumed = 0
    sigil_html_mismatch: list[int] = []
    built_letters: list[str] = []
    for record in records:
        plain = norm(str(record.get("plain", "")))
        built_letters.append(letters_only(str(record.get("plain", ""))))
        if str(record.get("plain", "")).count("<*>") != str(
            record.get("html", "")
        ).count("&lt;*&gt;"):
            sigil_html_mismatch.append(record.get("n"))
        # A Greek run divided at the foot of a page is rejoined without the
        # hyphen, so the print's text carries a hyphen the example does not.
        rejoined = re.sub(r"-\s+", "", plain)
        for example in record["examples"]:
            greek = norm(str(example.get("grc", "")))
            if not greek:
                continue
            spots = [match.start() for match in re.finditer(re.escape(greek), plain)]
            if not spots:
                if greek not in rejoined:
                    not_the_print.append((record.get("n"), greek[:60]))
                continue
            if all(resumes_after_bracket(plain, spot) for spot in spots):
                if letters_only(greek) in cit_quotes:
                    cit_resumed += 1
                else:
                    bare_resumed.append((record.get("n"), greek[:60]))
    parent_of = {child: parent for parent in root.iter() for child in parent}
    section_elements = {elem for elem in root.iter() if elem.get("type") == "smythp"}
    within_section: set[ET.Element] = set()
    for elem in root.iter():
        current: ET.Element | None = elem
        while current is not None:
            if current in section_elements:
                within_section.add(elem)
                break
            current = parent_of.get(current)
    gap_words: set[str] = set()
    gap_occurrences = 0
    for elem in within_section:
        pieces = [elem.text or ""] + [child.tail or "" for child in elem]
        for token in "".join(pieces).split():
            if "<*>" not in token:
                continue
            gap_occurrences += 1
            word = letters_only(token.strip(GAP_WORD_TRIM))
            if word:
                gap_words.add(word)
    all_built = " ".join(built_letters)
    gap_lost = sorted(
        word
        for word in gap_words
        if word not in all_built and word not in GAP_WORDS_REPAIRED
    )
    thirteen_ok = (
        not not_the_print
        and not bare_resumed
        and not gap_lost
        and not sigil_html_mismatch
    )
    report.add(
        13,
        thirteen_ok,
        "examples against the print's own text",
        f"examples checked={sum(len(record['examples']) for record in records)}\n"
        f"Greek not a run of its section's text={len(not_the_print)}; "
        f"examples={not_the_print[:5]}\n"
        f"examples starting where the print resumed after a bracket="
        f"{len(bare_resumed)}; examples={bare_resumed[:5]}\n"
        f"gap-sigil words in the source's sections={len(gap_words)} "
        f"({gap_occurrences} occurrences); lost from the built text={gap_lost}; "
        f"repaired away by design={sorted(GAP_WORDS_REPAIRED)}\n"
        f"records where html and plain disagree on the sigil={sigil_html_mismatch}",
    )
    if cit_resumed:
        report.warn(
            "cit examples that resume after a bracket",
            f"{cit_resumed} examples come from a source cit whose quote holds only "
            f"the far side of a bracket, so the Greek is short of the head the "
            f"gloss translates (Sec. 977 τοῦ ταλαιπώρου βίον for τὸν ἐμὸν ( = ἐμοῦ) "
            f"τοῦ ταλαιπώρου βίον). The markup is Perseus's; nothing in this round "
            f"changed it. Expected 110.",
        )

    return 0 if report.summary() else 1


if __name__ == "__main__":
    raise SystemExit(main())
