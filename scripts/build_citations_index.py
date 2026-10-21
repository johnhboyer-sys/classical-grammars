#!/usr/bin/env python3
"""Build data/smyth/citations.json: a reverse index, passage -> Smyth §§.

Every classical-text citation in Smyth renders (via convert_smyth.py) to
``<cite data-cite="...">`` inside a section's ``html`` field: both the
citations paired with a Greek quotation (also duplicated in
``examples[].cite``) and the ones attached directly to bare foreign text,
which never made it into ``examples[]``. This script scans ``html`` for every
``<cite data-cite="...">`` tag, so it covers all of them from one source of
truth.

Each citation string is classified with a hand-built author/work
normalization table (see SPEC-citations.md) into a canonical passage key:

    <author-slug>.<locator>               single-work corpora (Thuc., Dem., ...)
    <author-slug>.<work-slug>.<locator>   multi-work authors (Plat., Hom., ...)

Anything that does not match a known shape, or whose prefix is not in the
table, is recorded in the output's ``_meta.unparsedCitations`` list rather
than dropped or guessed at.

Reads data/smyth/sections.jsonl (not modified). Writes
data/smyth/citations.json. Python stdlib only; no network access; the JSON
key order and every list are sorted, so two runs produce byte-identical
output.
"""

from __future__ import annotations

import argparse
import collections
import html
import json
import re
import sys
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SECTIONS = ROOT / "data" / "smyth" / "sections.jsonl"
DEFAULT_OUTPUT = ROOT / "data" / "smyth" / "citations.json"

# A citation is "<author/work prefix> <locator>", where locator is a run of
# 1-3 dot-separated numbers with an optional trailing Stephanus letter
# (a-e). No citation in the source contains a range (hyphen/dash/comma) --
# see SPEC-citations.md.
CITATION_RE = re.compile(
    r"^([A-Za-z][A-Za-z.' ]*?)\s+([0-9]+(?:\.[0-9]+)*[a-e]?)$"
)

# "Plat. Alc. 1 110d" / "Plat. Alc. 2 113c": the dialogue number sits between
# the work abbreviation and the Stephanus locator, so the whole citation
# doesn't match CITATION_RE (which allows no space inside the locator).
# Checked directly against the raw citation, before CITATION_RE.
ALCIBIADES_RE = re.compile(r"^Plat\. Alc\. ([12]) ([0-9]+[a-e]?)$")

# Author/work normalization table: exact citation prefix (as it appears in
# Smyth, after stripping the trailing locator) -> (author_full, author_slug,
# work_full or None, work_slug or None). None/None marks a single-work
# corpus, keyed "<author_slug>.<locator>"; otherwise the key is
# "<author_slug>.<work_slug>.<locator>". Slugs are the abbreviation
# lowercased, periods stripped, internal spaces turned into hyphens. This is
# a closed table built from the 96 distinct prefixes actually present in
# data/smyth/sections.jsonl -- not a general-purpose parser -- so a prefix
# introduced by a future source edit is reported as unparsed, never guessed.
AUTHOR_WORK_TABLE: dict[str, tuple[str, str, str | None, str | None]] = {}

# -- single-work corpora: "<Author> <book>.<section>" ------------------------
AUTHOR_WORK_TABLE["Thuc."] = ("Thucydides", "thuc", None, None)
AUTHOR_WORK_TABLE["Dem."] = ("Demosthenes", "dem", None, None)
AUTHOR_WORK_TABLE["Lys."] = ("Lysias", "lys", None, None)
AUTHOR_WORK_TABLE["Isoc."] = ("Isocrates", "isoc", None, None)
AUTHOR_WORK_TABLE["Aeschin."] = ("Aeschines", "aeschin", None, None)
AUTHOR_WORK_TABLE["Hdt."] = ("Herodotus", "hdt", None, None)
AUTHOR_WORK_TABLE["Andoc."] = ("Andocides", "andoc", None, None)
AUTHOR_WORK_TABLE["Antiph."] = ("Antiphon", "antiph", None, None)
AUTHOR_WORK_TABLE["Isaeus"] = ("Isaeus", "isaeus", None, None)
AUTHOR_WORK_TABLE["Diog. Laert."] = ("Diogenes Laertius", "diog-laert", None, None)

# -- multi-work authors: "<Author> <Work> <locator>" -------------------------
_XEN = ("Xenophon", "xen")
for _abbr, _slug in {
    "Anab.": "anab",
    "Cyrop.": "cyrop",
    "Hell.": "hell",
    "Mem.": "mem",
    "Ec.": "ec",
    "Sym.": "sym",
    "Hiero": "hiero",
    "Ages.": "ages",
    "Apol.": "apol",
    "Ways": "ways",
    "Horse.": "horse",
    "Hunt.": "hunt",
    "Cav.": "cav",
}.items():
    AUTHOR_WORK_TABLE[f"Xen. {_abbr}"] = (*_XEN, _abbr, _slug)

_PLAT = ("Plato", "plat")
for _abbr, _slug in {
    "Apol.": "apol",
    "Rep.": "rep",
    "Gorg.": "gorg",
    "Phaedo": "phaedo",
    "Laws": "laws",
    "Prot.": "prot",
    "Theaet.": "theaet",
    "Euthyd.": "euthyd",
    "Lach.": "lach",
    "Charm.": "charm",
    "Menex.": "menex",
    "Euthyph.": "euthyph",
    "Phileb.": "phileb",
    "Lysis": "lysis",
    "Soph.": "soph",
    "Crat.": "crat",
    "Meno": "meno",
    "Hipp. Maj.": "hipp-maj",
    "Tim.": "tim",
    "Stat.": "stat",
    "Criti.": "criti",
    "Parm.": "parm",
    "Sym.": "sym",
    "Phaedrus": "phaedrus",
    "Crito": "crito",
}.items():
    AUTHOR_WORK_TABLE[f"Plat. {_abbr}"] = (*_PLAT, _abbr, _slug)
# Alcibiades I/II: dialogue number folded in before lookup (see ALCIBIADES_RE).
AUTHOR_WORK_TABLE["Plat. Alc. 1"] = (*_PLAT, "Alc. 1", "alc-1")
AUTHOR_WORK_TABLE["Plat. Alc. 2"] = (*_PLAT, "Alc. 2", "alc-2")

_HOM = ("Homer", "hom")
AUTHOR_WORK_TABLE["Hom. Il."] = (*_HOM, "Il.", "il")
AUTHOR_WORK_TABLE["Hom. Od."] = (*_HOM, "Od.", "od")

_SOPH = ("Sophocles", "soph")
for _abbr, _slug in {
    "Ant.": "ant",
    "OT": "ot",
    "OC": "oc",
    "El.": "el",
    "Phil.": "phil",
    "Aj.": "aj",
    "Trach.": "trach",
}.items():
    AUTHOR_WORK_TABLE[f"Soph. {_abbr}"] = (*_SOPH, _abbr, _slug)

_EUR = ("Euripides", "eur")
for _abbr, _slug in {
    "Med.": "med",
    "Orest.": "orest",
    "Hec.": "hec",
    "Alc.": "alc",
    "Hipp.": "hipp",
    "IT": "it",
    "Ion": "ion",
    "El.": "el",
    "Andr.": "andr",
    "Hel.": "hel",
    "Ba.": "ba",
    "Phoen.": "phoen",
    "Her.": "her",
    "Supp.": "supp",
    "IA": "ia",
    "Tro.": "tro",
}.items():
    AUTHOR_WORK_TABLE[f"Eur. {_abbr}"] = (*_EUR, _abbr, _slug)

_AESCH = ("Aeschylus", "aesch")
for _abbr, _slug in {
    "Ag.": "ag",
    "PB": "pb",
    "Lib.": "lib",
    "Eum.": "eum",
    "Pers.": "pers",
    "Seven": "seven",
    "Supp.": "supp",
}.items():
    AUTHOR_WORK_TABLE[f"Aesch. {_abbr}"] = (*_AESCH, _abbr, _slug)

_ARISTOPH = ("Aristophanes", "aristoph")
for _abbr, _slug in {
    "Cl.": "cl",
    "Wasps": "wasps",
    "Ach.": "ach",
    "Frogs": "frogs",
    "Birds": "birds",
    "Kn.": "kn",
    "Eccl.": "eccl",
    "Pl.": "pl",
    "Thes.": "thes",
    "Lys.": "lys",
    "Peace": "peace",
}.items():
    AUTHOR_WORK_TABLE[f"Aristoph. {_abbr}"] = (*_ARISTOPH, _abbr, _slug)

AUTHOR_WORK_TABLE["Men. Sent."] = ("Menander", "men", "Sent.", "sent")
AUTHOR_WORK_TABLE["Pind. O."] = ("Pindar", "pind", "O.", "o")
AUTHOR_WORK_TABLE["Stob. Flor."] = ("Stobaeus", "stob", "Flor.", "flor")
AUTHOR_WORK_TABLE["Ps. Xen. Const. Ath."] = (
    "Pseudo-Xenophon",
    "ps-xen",
    "Const. Ath.",
    "const-ath",
)

# -- html scanning -------------------------------------------------------
# Track, in document order, the most recent lettered-subsection id ("a",
# "b1", ...) an element opened; attach it to every <cite> that follows until
# the next one. Dialect-note/footnote ids ("D", "D1", "fn1", "fn2") don't
# match the pattern and are ignored, per SPEC-citations.md. The result is the
# nearest *preceding* anchor -- a scroll target, not a containment claim; see
# the anchor section of SPEC-citations.md for the two cases where the
# citation is not actually inside the subsection it names.
_TAG_RE = re.compile(
    r'<(?:strong|p|span)\b[^>]*\bid="([^"]+)"|<cite\b[^>]*\bdata-cite="([^"]*)"'
)
_LETTER_ID_RE = re.compile(r"^[a-z]\d?$")


def iter_html_citations(html_text: str) -> Iterable[tuple[str, str | None]]:
    """Yield (raw cite text, anchor letter or None), in document order."""
    anchor: str | None = None
    for match in _TAG_RE.finditer(html_text):
        id_value, cite_value = match.groups()
        if id_value is not None:
            if _LETTER_ID_RE.match(id_value):
                anchor = id_value
            continue
        yield html.unescape(cite_value), anchor


def classify(raw_cite: str) -> tuple[str, str] | None:
    """Return (table_key, locator) for a citation string, or None if it
    doesn't match a recognizable "<prefix> <locator>" shape at all."""
    alc = ALCIBIADES_RE.match(raw_cite)
    if alc:
        digit, locator = alc.groups()
        return f"Plat. Alc. {digit}", locator
    match = CITATION_RE.match(raw_cite)
    if not match:
        return None
    return match.group(1), match.group(2)


def build_key(entry: tuple[str, str, str | None, str | None], locator: str) -> str:
    _author_full, author_slug, _work_full, work_slug = entry
    if work_slug is None:
        return f"{author_slug}.{locator}"
    return f"{author_slug}.{work_slug}.{locator}"


def load_records(path: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                records.append(json.loads(line))
    return records


def build(records: list[dict[str, object]]) -> dict[str, object]:
    citations: dict[str, set[tuple[int, str | None]]] = collections.defaultdict(set)
    by_author: collections.Counter[str] = collections.Counter()
    unparsed: list[dict[str, object]] = []
    total = 0
    parsed = 0

    for record in records:
        section = int(record["n"])
        for raw_cite, anchor in iter_html_citations(str(record["html"])):
            total += 1
            classified = classify(raw_cite)
            entry = AUTHOR_WORK_TABLE.get(classified[0]) if classified else None
            if classified is None or entry is None:
                unparsed.append(
                    {"text": raw_cite, "section": section, "anchor": anchor}
                )
                continue
            _, locator = classified
            key = build_key(entry, locator)
            citations[key].add((section, anchor))
            by_author[entry[1]] += 1
            parsed += 1

    sorted_citations = {
        key: [
            {"section": section, **({"anchor": anchor} if anchor else {})}
            for section, anchor in sorted(
                citations[key], key=lambda pair: (pair[0], pair[1] or "")
            )
        ]
        for key in sorted(citations)
    }
    unparsed_sorted = sorted(
        unparsed, key=lambda item: (str(item["text"]), int(item["section"]))
    )

    meta = {
        "sourceCitations": total,
        "parsed": parsed,
        "unparsed": len(unparsed_sorted),
        "uniqueKeys": len(sorted_citations),
        "byAuthor": dict(sorted(by_author.items(), key=lambda kv: (-kv[1], kv[0]))),
        "unparsedCitations": unparsed_sorted,
    }

    result: dict[str, object] = dict(sorted_citations)
    result["_meta"] = meta
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sections", type=Path, default=DEFAULT_SECTIONS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    records = load_records(args.sections)
    result = build(records)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    meta = result["_meta"]
    print(
        f"citations: {meta['sourceCitations']} total, {meta['parsed']} parsed, "
        f"{meta['unparsed']} unparsed, {meta['uniqueKeys']} unique keys",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
