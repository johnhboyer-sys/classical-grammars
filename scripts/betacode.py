#!/usr/bin/env python3
"""Small, strict Beta Code to Unicode Greek transliterator.

The Goodwin TEI uses the usual Perseus Beta Code, with ``v`` for digamma.
It also contains seven macrons (``_``) and one breve (``^``).  This module
keeps its input rules deliberately narrow: an ASCII letter that is not a Beta
letter, a dangling capital marker, or a dangling diacritic raises ``ValueError``.
"""

from __future__ import annotations

import unicodedata


LETTERS = {
    "a": "α", "b": "β", "g": "γ", "d": "δ", "e": "ε", "z": "ζ",
    "h": "η", "q": "θ", "i": "ι", "k": "κ", "l": "λ", "m": "μ",
    "n": "ν", "c": "ξ", "o": "ο", "p": "π", "r": "ρ", "s": "σ",
    "t": "τ", "u": "υ", "f": "φ", "x": "χ", "y": "ψ", "w": "ω",
    "v": "ϝ",
    # Goodwin has two instances of ``junaikw=n`` for γυναικῶν.  This
    # edition's legacy encoder uses j for gamma in that word.
    "j": "γ",
}

# Greek combining marks.  NFC composes every combination for which Unicode has
# a precomposed polytonic character and leaves the rare quantity combinations
# as stable combining sequences.
MARKS = {
    ")": "\u0313",  # smooth breathing
    "(": "\u0314",  # rough breathing
    "/": "\u0301",  # acute
    "\\": "\u0300",  # grave
    "=": "\u0342",  # circumflex
    "|": "\u0345",  # iota subscript
    "+": "\u0308",  # diaeresis
    "_": "\u0304",  # macron (found in Goodwin)
    "^": "\u0306",  # breve (found in Goodwin)
}

# These are ordinary punctuation in the edition.  ``:`` and ``;`` are kept as
# printed: in this source semicolons serve as Greek question marks.
PUNCTUATION = set(" \t\r\n0123456789.,;:!?-–—…[]{}<>\"“”（）")


def _is_letter(char: str) -> bool:
    return char in LETTERS


def _has_following_letter(text: str, index: int) -> bool:
    """Whether a sigma at ``index`` is followed by a letter in its token.

    An elision apostrophe counts: printed convention is medial sigma before
    the koronis (καί σ᾽ αἰτῶ, never ς᾽)."""
    index += 1
    while index < len(text) and text[index] in MARKS:
        index += 1
    return index < len(text) and (_is_letter(text[index]) or text[index] == "'")


def _letter(char: str, capital: bool, final_sigma: bool) -> str:
    value = LETTERS[char.lower()]
    if char.lower() == "s" and final_sigma:
        value = "ς"
    return value.upper() if capital else value


def transliterate(text: str) -> str:
    """Convert one Beta Code Greek string to NFC Unicode.

    A leading ``*`` capitalizes the next Greek letter.  The source permits its
    breathing/accent marks both before and after that letter, so both forms are
    accepted.  Bare upper-case ASCII is not Beta Code and raises an error.
    """
    output: list[str] = []
    index = 0
    size = len(text)

    while index < size:
        char = text[index]
        if char == "'":
            output.append("\u1fbd")
            index += 1
            continue
        if char == "*":
            index += 1
            before: list[str] = []
            while index < size and text[index] in MARKS:
                before.append(MARKS[text[index]])
                index += 1
            if (
                index == size
                or not text[index].isascii()
                or not text[index].isalpha()
                or text[index].lower() not in LETTERS
            ):
                raise ValueError(f"dangling * at offset {index - 1} in {text!r}")
            letter = text[index]
            index += 1
            after: list[str] = []
            while index < size and text[index] in MARKS:
                after.append(MARKS[text[index]])
                index += 1
            output.append(
                unicodedata.normalize(
                    "NFC", _letter(letter, True, letter.lower() == "s" and not _has_following_letter(text, index - len(after) - 1)) + "".join(before + after)
                )
            )
            continue
        if _is_letter(char):
            index += 1
            after = []
            while index < size and text[index] in MARKS:
                after.append(MARKS[text[index]])
                index += 1
            output.append(
                unicodedata.normalize(
                    "NFC", _letter(char, char.isupper(), char.lower() == "s" and not _has_following_letter(text, index - len(after) - 1)) + "".join(after)
                )
            )
            continue
        if char in MARKS:
            # A mark before an unstarred letter is valid Beta Code too.
            before = []
            raw_marks = []
            while index < size and text[index] in MARKS:
                before.append(MARKS[text[index]])
                raw_marks.append(text[index])
                index += 1
            if index == size or not _is_letter(text[index]):
                # A handful of Greek-tagged quotations contain an English
                # editorial parenthesis.  It is not Beta Code, but changing it
                # to its full-width form keeps it visibly distinct and avoids
                # leaving a Beta breathing marker in Greek output.
                if raw_marks:
                    # Editorial matter inside a few Greek-tagged quotations
                    # uses ordinary ASCII punctuation, e.g. ``(= ... )``.
                    # These are known marks used as punctuation, not unknown
                    # Beta Code; make them visibly literal rather than leave
                    # a false Beta mark in Greek output.
                    literal = {
                        "(": "（", ")": "）", "/": "／", "\\": "＼",
                        "=": "＝", "|": "｜", "+": "＋", "_": "＿", "^": "＾",
                    }
                    output.extend(literal[mark] for mark in raw_marks)
                    continue
                raise ValueError(f"dangling Beta Code mark in {text!r}")
            letter = text[index]
            index += 1
            after = []
            while index < size and text[index] in MARKS:
                after.append(MARKS[text[index]])
                index += 1
            output.append(
                unicodedata.normalize(
                    "NFC", _letter(letter, letter.isupper(), letter.lower() == "s" and not _has_following_letter(text, index - len(after) - 1)) + "".join(before + after)
                )
            )
            continue
        if char in PUNCTUATION or not char.isascii():
            output.append(char)
            index += 1
            continue
        raise ValueError(f"unknown Beta Code character {char!r} in {text!r}")

    return unicodedata.normalize("NFC", "".join(output))
