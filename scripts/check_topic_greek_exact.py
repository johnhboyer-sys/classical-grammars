#!/usr/bin/env python3
"""Every Greek word a topic page quotes, compared with the witness exactly.

`verify_topic_pages.py` folds accents, breathings and macrons away before
it compares, because that is what makes the check robust across the
grammars' different conventions. The cost is that a quotation differing
from the print only in an accent or a macron passes it. That is not a
small thing here: the editorial law says a macron difference defers to
the editor, and a page that drops one has printed a form the witness does
not supply.

This is the stricter pass, run by hand rather than in CI, because three
of its classes are the page being right rather than wrong:

  * a grave for an acute. Greek writes the grave on an oxytone before
    another word, and a word quoted alone takes the acute. Folded here.
  * a capital at the head of the print's own example sentence, quoted
    lowercase in the middle of the page's sentence. Folded here.
  * the print's line-break and syllable hyphens. Folded here, as in the
    verifier.

What is left is a real divergence. Four were found and fixed when this
was written: the page had ψῡχαῖς for Goodell's ψῦχαῖς, and θηλυνομένων,
συγκαλέσᾱς and ἡμέρᾱς with the macron dropped.

Usage: python3 scripts/check_topic_greek_exact.py [page ...]
Exit 1 when anything differs.
"""
from __future__ import annotations

import importlib.util
import os
import re
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    "verify_topic_pages", HERE / "verify_topic_pages.py")
V = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(V)

GRAVE = "̀"
ACUTE = "́"


def norm(text: str) -> str:
    text = unicodedata.normalize("NFD", text).replace(GRAVE, ACUTE)
    text = unicodedata.normalize("NFC", text)
    for mark in "’᾽῾ʼ":
        text = text.replace(mark, "'")
    return " ".join(text.lower().split())


def haystack(rows: dict, numbers: list[int]) -> str:
    parts: list[str] = []
    for n in numbers:
        row = rows.get(n)
        if row:
            parts.append(row.get("head", ""))
            parts.append(row.get("plain", ""))
    folded = norm(" ".join(parts))
    return " ".join((folded, re.sub(r"-\s+", "", folded), folded.replace("-", "")))


def numbers_of(parts: list[str]) -> list[int]:
    out: list[int] = []
    for part in parts:
        part = part.replace("–", "-")
        if "-" in part:
            first, last = part.split("-", 1)
            out.extend(range(int(first), int(last) + 1))
        elif part.isdigit():
            out.append(int(part))
    return out


def main(argv: list[str]) -> int:
    pages = [Path(a) for a in argv] or sorted((HERE.parent / "topics").glob("*.md"))
    corpus = V.Corpus()
    total = 0
    for page in pages:
        front, body = V.split_front_matter(page.read_text(encoding="utf-8"))
        meta = V.parse_front_matter(front)
        pool = []
        for work, parts in (meta.get("sections") or {}).items():
            rows = corpus.get(work)
            if rows is not None:
                pool.append(haystack(rows, numbers_of(parts)))
        pool = " ".join(pool)
        misses = []
        for sentence in V.sentences(body):
            stripped = V.CITATION_RE.sub(" ", sentence)
            for run in V.GREEK_RUN_RE.findall(stripped):
                exact = norm(run).strip(" '")
                if len(exact.replace(" ", "")) < 2 or exact in pool:
                    continue
                for word in exact.split():
                    if len(word.strip("'")) >= 2 and word not in pool:
                        misses.append((word, sentence.strip()[:90]))
        if misses:
            total += len(misses)
            print(f"{page.name}: {len(misses)}")
            for word, sentence in misses:
                print(f"    {word!r} in: {sentence}")
    print(f"{total} Greek words differ from the witness by more than "
          f"a grave, a capital or the print's hyphens")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
