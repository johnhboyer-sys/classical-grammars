#!/usr/bin/env python3
"""Build the reverse citation index for every grammar but Smyth, and the
combined cross-grammar index.

Writes:

* ``data/<work>/citations.json`` for goodwin-gmt, gildersleeve, monro,
  goodell and ag -- same shape as ``data/smyth/citations.json``, which
  ``build_citations_index.py`` still owns and which this script never
  touches.
* ``data/citations-index.json`` -- one passage key -> every (work, section)
  in the corpus that cites it, Smyth included, so "which sections of any
  grammar we own discuss Thucydides 1.9?" is a single lookup.

Citations are read from two places per section and merged: every
``<cite data-cite="...">`` in the section's ``html`` and in each of its
``notes[].html`` (Goodwin, Gildersleeve and A&G carry these), and every
``examples[].cite`` (all five do; Monro and Goodell have only these). An
example cite that the tag scan already produced for the same section is not
counted twice.

Every citation string is resolved against a hand-built, closed per-grammar
table in ``citation_tables.py``. A prefix that is not in the table -- or a
locator that does not parse -- is recorded in ``_meta.unparsedCitations``
rather than guessed at. Python stdlib only; no network; all output sorted,
so two runs are byte-identical.
"""

from __future__ import annotations

import argparse
import collections
import html
import json
import re
import sys
from pathlib import Path
from typing import Iterable, Iterator

sys.path.insert(0, str(Path(__file__).resolve().parent))

from citation_tables import (  # noqa: E402
    BOOK_COUNTS, MIN_LOCATOR_DEPTH, Row, TABLES,
)

ROOT = Path(__file__).resolve().parents[1]
WORKS = ["goodwin-gmt", "gildersleeve", "monro", "goodell", "ag"]
SMYTH_CITATIONS = ROOT / "data" / "smyth" / "citations.json"
DEFAULT_COMBINED = ROOT / "data" / "citations-index.json"

# --- citation-string cleaning ---------------------------------------------
# Applied identically to every grammar before the table is consulted. Each
# rule exists because some grammar's cite field carries the noise it removes;
# none of them changes which passage a citation names. See SPEC-citations.md.
_FOOTNOTE_RE = re.compile(r"\[fn\].*?\[/fn\]", re.DOTALL)
_ZERO_WIDTH_RE = re.compile(r"[​‌‍﻿]")
_LEAD_PAREN_RE = re.compile(r"^\([^()]*\)[\s.,;:]*")
_TRAIL_PAREN_RE = re.compile(r"[\s.,;:]*\([^()]*\)[\s.,;:]*$")
_DASHES_RE = re.compile(r"[‐‑‒–—―]")


def clean(raw: str) -> str:
    """Normalize a raw cite string: unescape, drop editorial noise, collapse
    whitespace, strip trailing sentence punctuation. Never rewrites an
    author, a work or a number."""
    text = html.unescape(raw)
    text = _FOOTNOTE_RE.sub(" ", text)
    text = _ZERO_WIDTH_RE.sub("", text)
    text = _DASHES_RE.sub("-", text)
    # A leading or trailing parenthesis carries Goodell's running gloss
    # ("(Historical Present)", "(i.e., he did this on various occasions)").
    # Only stripped when something is left over to key on.
    for pattern in (_LEAD_PAREN_RE, _TRAIL_PAREN_RE):
        while True:
            stripped = pattern.sub("", text).strip()
            if not stripped or stripped == text.strip():
                break
            text = stripped
    text = " ".join(text.split())
    return text.strip(" .,;:")


# --- locator parsing -------------------------------------------------------
# A locator is one or more components separated by "." or whitespace or both
# ("Thuc. 1. 137", "Xen. Cyrop. 7. 5. 30", "Od.20.294"). A component is
# either arabic digits with an optional single trailing letter (a Stephanus
# or Bekker letter: "17b", "1278a", Cicero's "1.5a") or a roman numeral
# ("Xen. Hell. iii. 5"). Roman numerals normalize to arabic and letters
# lowercase, so every grammar's spelling of one passage yields one key.
_ROMAN_RE = re.compile(r"^(?:[IVXLCDM]+|[ivxlcdm]+)$")
_ARABIC_RE = re.compile(r"^([0-9]+)([A-Za-z])?$")
_ROMAN_VALUES = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500,
                 "m": 1000}


def roman_to_arabic(token: str) -> int | None:
    """Strict roman -> int; None if the token is not a well-formed roman
    numeral that round-trips (so "mm", "ic" and the like are rejected)."""
    lowered = token.lower()
    total = 0
    previous = 0
    for char in reversed(lowered):
        value = _ROMAN_VALUES[char]
        total += -value if value < previous else value
        previous = max(previous, value)
    return total if total and arabic_to_roman(total) == lowered else None


def arabic_to_roman(number: int) -> str:
    pairs = [(1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"),
             (90, "xc"), (50, "l"), (40, "xl"), (10, "x"), (9, "ix"),
             (5, "v"), (4, "iv"), (1, "i")]
    out: list[str] = []
    for value, glyph in pairs:
        while number >= value:
            out.append(glyph)
            number -= value
    return "".join(out)


def parse_locator(text: str) -> str | None:
    """Return the canonical locator for the text after a matched prefix, or
    None. A range ("Il. 1.3-5", "Plato Apology 17c-d") is keyed at its
    opening locator only -- see SPEC-citations.md."""
    text = text.strip(" .,;:")
    if "-" in text:
        text = text.split("-", 1)[0].strip(" .,;:")
    if not text:
        return None
    components = [part for part in re.split(r"[.\s]+", text) if part]
    if not components:
        return None
    out: list[str] = []
    for component in components:
        arabic = _ARABIC_RE.match(component)
        if arabic:
            number, letter = arabic.groups()
            out.append(number.lstrip("0") or "0")
            if letter:
                out[-1] += letter.lower()
            continue
        # A Stephanus letter the grammar set off with a space ("Plat. Crito
        # 52 B") belongs to the number before it, not to a component of its
        # own. Only a-e, only after a bare number, so it can never swallow a
        # roman-numeral book ("Xen. Hell. iii. 5").
        if (len(component) == 1 and component.lower() in "abcde" and out
                and out[-1].isdigit()):
            out[-1] += component.lower()
            continue
        if _ROMAN_RE.match(component):
            value = roman_to_arabic(component)
            if value is None:
                return None
            out.append(str(value))
            continue
        return None
    return ".".join(out)


# --- table lookup ----------------------------------------------------------

def build_lookup(table: dict[str, Row]) -> list[tuple[str, str, Row]]:
    """(lowercased prefix, original prefix, row), longest prefix first."""
    rows = [(prefix.lower(), prefix, row) for prefix, row in table.items()]
    rows.sort(key=lambda item: (-len(item[0]), item[0]))
    return rows


def work_name(row: Row) -> str:
    _author_full, author_slug, _work_full, work_slug = row
    return author_slug if work_slug is None else f"{author_slug}.{work_slug}"


def classify(
    cleaned: str, lookup: list[tuple[str, str, Row]]
) -> tuple[tuple[str, Row, str] | None, str]:
    """Longest listed prefix wins. The prefix match is case-insensitive and
    must not end in the middle of a word.

    Returns ((prefix, row, locator), "") on success, or (None, reason) --
    the reason being the one from the longest prefix that matched at all, so
    a rejected citation says why it was rejected rather than just "unknown".
    """
    lowered = cleaned.lower()
    first_reason = ""
    for lowered_prefix, prefix, row in lookup:
        if not lowered.startswith(lowered_prefix):
            continue
        rest = cleaned[len(lowered_prefix):]
        if rest[:1].isalpha():
            continue
        reason = ""
        locator = parse_locator(rest)
        if locator is None:
            reason = f"locator after {prefix!r} does not parse"
        else:
            components = locator.split(".")
            minimum = MIN_LOCATOR_DEPTH.get((row[1], row[3]), 1)
            ceiling = BOOK_COUNTS.get((row[1], row[3]))
            head = int(re.match(r"[0-9]+", components[0]).group())
            if len(components) < minimum:
                reason = (
                    f"locator {locator!r} has {len(components)} component"
                    f"{'' if len(components) == 1 else 's'}, and "
                    f"{work_name(row)} is cited to a depth of {minimum}: a "
                    "reference truncated in the print"
                )
            elif ceiling is not None and head > ceiling:
                reason = (
                    f"locator {locator!r} begins at {head}, and "
                    f"{work_name(row)} has only {ceiling}: a reference whose "
                    "leading element the print's compressed list dropped"
                )
            else:
                return (prefix, row, locator), ""
        first_reason = first_reason or reason
    return None, first_reason or "no prefix in this grammar's table"


def reason_class(reason: str) -> str:
    """Bucket an unparsed reason for _meta.unparsedByReason."""
    if "cited to a depth of" in reason:
        return "locator truncated (too shallow for the work)"
    if "has only" in reason:
        return "leading element impossible for the work"
    if "does not parse" in reason:
        return "locator does not parse"
    if reason == "empty after cleaning":
        return "not a citation"
    return "no prefix in this grammar's table"


def build_key(row: Row, locator: str) -> str:
    _author_full, author_slug, _work_full, work_slug = row
    if work_slug is None:
        return f"{author_slug}.{locator}"
    return f"{author_slug}.{work_slug}.{locator}"


# --- section scanning ------------------------------------------------------
_TAG_RE = re.compile(
    r'<(?:strong|p|span|div|li)\b[^>]*\bid="([^"]+)"'
    r'|<cite\b[^>]*\bdata-cite="([^"]*)"'
)


def section_id(record: dict[str, object]) -> int | str:
    """The grammar's own identifier for a section: its number where it has
    one, else the suffix of its stable id (Goodwin's seven unnumbered
    appendix sections, "app-1" .. "app-7")."""
    if "n" in record:
        value = record["n"]
        return int(value) if isinstance(value, int) else str(value)
    return str(record["id"]).split(":", 1)[1]


def iter_section_citations(
    record: dict[str, object],
) -> Iterator[tuple[str, str | None]]:
    """Yield (raw cite text, anchor or None) for one section.

    First every <cite data-cite> in the section html and in each note's html,
    in document order, carrying the nearest preceding lettered-subsection
    anchor (only ids the record itself declares in ``letters`` count, so a
    note id like "n1" is never mistaken for a subsection). Then any
    ``examples[].cite`` the tag scan did not already yield for this section.
    """
    letters = {str(letter) for letter in (record.get("letters") or [])}
    seen: collections.Counter[str] = collections.Counter()
    htmls = [str(record.get("html") or "")]
    htmls += [str(note.get("html") or "")
              for note in (record.get("notes") or [])]
    for markup in htmls:
        anchor: str | None = None
        for match in _TAG_RE.finditer(markup):
            id_value, cite_value = match.groups()
            if id_value is not None:
                if id_value in letters:
                    anchor = id_value
                continue
            text = html.unescape(cite_value)
            seen[text] += 1
            yield text, anchor
    for example in (record.get("examples") or []):
        text = example.get("cite")
        if not text:
            continue
        if seen[text] > 0:
            seen[text] -= 1
            continue
        yield text, None


def load_records(path: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                records.append(json.loads(line))
    return records


def build(work: str, records: Iterable[dict[str, object]]) -> dict[str, object]:
    lookup = build_lookup(TABLES[work])
    citations: dict[str, set[tuple[str, str | None]]] = (
        collections.defaultdict(set))
    sort_keys: dict[str | int, tuple[int, int, str]] = {}
    by_author: collections.Counter[str] = collections.Counter()
    unparsed: list[dict[str, object]] = []
    total = 0
    parsed = 0

    for record in records:
        section = section_id(record)
        sort_keys[str(section)] = (
            0 if isinstance(section, int) else 1,
            section if isinstance(section, int) else 0,
            str(section),
        )
        for raw_cite, anchor in iter_section_citations(record):
            total += 1
            cleaned = clean(raw_cite)
            classified, reason = (
                classify(cleaned, lookup) if cleaned
                else (None, "empty after cleaning"))
            if classified is None:
                unparsed.append({"text": raw_cite, "section": section,
                                 "anchor": anchor, "reason": reason})
                continue
            _prefix, row, locator = classified
            citations[build_key(row, locator)].add((str(section), anchor))
            by_author[row[1]] += 1
            parsed += 1

    def entry_sort(pair: tuple[str, str | None]) -> tuple[int, int, str, str]:
        section, anchor = pair
        rank = sort_keys.get(section, (1, 0, section))
        return (*rank, anchor or "")

    def revive(section: str) -> int | str:
        return int(section) if sort_keys.get(section, (1,))[0] == 0 else section

    sorted_citations = {
        key: [
            {"section": revive(section),
             **({"anchor": anchor} if anchor else {})}
            for section, anchor in sorted(citations[key], key=entry_sort)
        ]
        for key in sorted(citations)
    }
    unparsed_sorted = sorted(
        unparsed,
        key=lambda item: (str(item["text"]), str(item["section"])),
    )
    result: dict[str, object] = dict(sorted_citations)
    result["_meta"] = {
        "work": work,
        "sourceCitations": total,
        "parsed": parsed,
        "unparsed": len(unparsed_sorted),
        "unparsedRate": round(len(unparsed_sorted) / total, 4) if total else 0,
        "uniqueKeys": len(sorted_citations),
        "tablePrefixes": len(TABLES[work]),
        "byAuthor": dict(sorted(by_author.items(),
                                key=lambda kv: (-kv[1], kv[0]))),
        "unparsedByReason": dict(sorted(
            collections.Counter(reason_class(str(item["reason"]))
                                for item in unparsed_sorted).items(),
            key=lambda kv: (-kv[1], kv[0]))),
        "unparsedCitations": unparsed_sorted,
    }
    return result


def combine(per_work: dict[str, dict[str, object]]) -> dict[str, object]:
    """One passage key -> every (work, section) in the corpus that cites it."""
    combined: dict[str, list[dict[str, object]]] = collections.defaultdict(list)
    by_work: dict[str, int] = {}
    for work in sorted(per_work):
        data = per_work[work]
        count = 0
        for key, entries in data.items():
            if key == "_meta":
                continue
            for entry in entries:
                combined[key].append({"work": work, **entry})
                count += 1
        by_work[work] = count

    def entry_sort(entry: dict[str, object]) -> tuple[str, int, int, str, str]:
        section = entry["section"]
        return (
            str(entry["work"]),
            0 if isinstance(section, int) else 1,
            section if isinstance(section, int) else 0,
            str(section),
            str(entry.get("anchor") or ""),
        )

    result: dict[str, object] = {
        key: sorted(combined[key], key=entry_sort) for key in sorted(combined)
    }
    shared = sorted(
        (key for key, entries in combined.items()
         if len({str(entry["work"]) for entry in entries}) > 1),
    )
    result["_meta"] = {
        "works": sorted(per_work),
        "uniqueKeys": len(combined),
        "entries": sum(by_work.values()),
        "entriesByWork": by_work,
        "keysCitedByMoreThanOneWork": len(shared),
    }
    return result


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False)
        + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "data")
    parser.add_argument("--combined", type=Path, default=DEFAULT_COMBINED)
    parser.add_argument("--smyth-citations", type=Path,
                        default=SMYTH_CITATIONS)
    parser.add_argument(
        "--no-write", action="store_true",
        help="parse and report, but write nothing (used by the verifier)")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    per_work: dict[str, dict[str, object]] = {}
    for work in WORKS:
        records = load_records(args.data / work / "sections.jsonl")
        result = build(work, records)
        per_work[work] = result
        if not args.no_write:
            write_json(args.data / work / "citations.json", result)
        meta = result["_meta"]
        print(
            f"{work}: {meta['sourceCitations']} citations, "
            f"{meta['parsed']} parsed, {meta['unparsed']} unparsed "
            f"({meta['unparsedRate']:.2%}), {meta['uniqueKeys']} keys",
            file=sys.stderr,
        )

    # Smyth's index is read as built; build_citations_index.py owns it.
    per_work["smyth"] = json.loads(
        args.smyth_citations.read_text(encoding="utf-8"))
    combined = combine(per_work)
    if not args.no_write:
        write_json(args.combined, combined)
    meta = combined["_meta"]
    print(
        f"combined: {meta['uniqueKeys']} keys, {meta['entries']} entries, "
        f"{meta['keysCitedByMoreThanOneWork']} keys cited by 2+ grammars",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
