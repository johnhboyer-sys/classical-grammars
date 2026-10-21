#!/usr/bin/env python3
"""Independently verify the Gildersleeve TEI conversion and report."""

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
DEFAULT_INPUT = ROOT / "grammar-gildersleeve" / "src" / "gildersleeve-1999.04.0074.xml"
DEFAULT_SECTIONS = ROOT / "data" / "gildersleeve" / "sections.jsonl"
DEFAULT_META = ROOT / "data" / "gildersleeve" / "meta.json"
DEFAULT_CONVERTER = ROOT / "scripts" / "convert_gildersleeve.py"

TEI_NS = "{http://www.tei-c.org/ns/1.0}"
LAST_SECTION = 674
CONTENT_TAGS = {"p", "table", "list", "note", "signed"}
ID_RE = re.compile(r"^gildersleeve:(\d+)$")
MACRON_VOWELS = "āīūăĭŭ"
BETA_CODE_RE = re.compile(
    r"(?:\b[A-Za-z]+\\[A-Za-z]+\b|\b[A-Za-z]+\)[A-Za-z]+(?:[/=+|][A-Za-z]+)*\b|"
    r"\b[A-Za-z]{2,}/[A-Za-z]{2,}\b|\*[A-Za-z]+)"
)
RAW_TAG_RE = re.compile(r"<[^>]+>")
RAW_ENTITY_RE = re.compile(r"&(?:#\d+|#x[0-9A-Fa-f]+|[A-Za-z][A-Za-z0-9]+);")
HTML_UNKNOWN_ENTITY_RE = re.compile(
    r"&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[0-9A-Fa-f]+;)[A-Za-z][A-Za-z0-9]+;"
)
TEI_LEAK_RE = re.compile(
    r"TEIform|xmlns|xml:lang|<(?:foreign|gloss|emph|hi|ref|cit|bibl|milestone|"
    r"item|cell|row|note|l)\b"
)
BLOCK_TAGS = {"p", "table", "ul", "ol", "li", "tr", "td", "aside", "section"}
REQUIRED_KEYS = {
    "work", "n", "id", "part", "letters", "notes", "path", "head", "html",
    "plain", "examples", "refs", "refRanges", "citedBy", "prev", "next",
}
SOURCE_TEXT_FIXES = (
    (re.compile(r"matro\\s\s+a\)mfo/teroi"), "ματρὸς ἀμφότεροι"),
    (re.compile(r"&lt;([^&<>]+)&gt;"), r"⟨\1⟩"),
)
PREFIXES = {78: "78.", 111: "III.", 642: "642."}
VOID_TAGS = {"br", "hr", "img", "meta", "link", "input"}
PLAIN_BOUNDARY_TAGS = {"note", "bibl"}

# The source stacks a combining macron OUTERMOST, over breathing and accent,
# the same transmission defect Smyth's print corrects innermost (see
# convert_smyth.py's STACKED_MACRON_RE comment for the full rule and its two
# kept subclasses). Defined independently here, not imported from the
# converter, so a bug in the shared restack rule cannot pass its own check.
GREEK_MACRON = "̄"
GREEK_BREVE = "̆"
STACKED_MACRON_RE = re.compile(r"([Ͱ-Ͽἀ-῿])̄")
GREEK_VOWELS = "αειουηωΑΕΙΟΥΗΩ"
# Counted from the raw TEI source, not the converter: 1 real site (ἄ̄ν at
# §459), 5 bare vowels already innermost (η, ω have no precomposed long
# form), and 3 sites where iota subscript (ccc 240) sits outside the macron's
# ccc 230 -- canonically equivalent to the unrestacked spelling either way, so
# restacking would only denormalize the corpus for no printed difference.
EXPECTED_SOURCE_MACRONS = {"stacked": 1, "anceps": 0, "bare": 5, "subscriptEquivalent": 3}
EXPECTED_MACRON_REPAIRS = {
    "macronsRestacked": 1,
    "ancepsMacronsKept": 0,
    "subscriptMacronsKept": 3,
}
GREEK_YPOGEGRAMMENI = "ͅ"
# Instances over the records' html and plain fields: the 3 kept subscript
# sites (x 2 fields) and the 5 bare vowels that were already innermost (x 2
# fields).  The one real restack is alpha-based (ἄ̄ν -> ᾱ̓́ν), and alpha has a
# precomposed macron form, so its macron is absorbed into the base letter and
# leaves no standalone combining mark for this walk to find -- pinned instead
# as a frozen reading below, the way check 12 in verify_smyth.py does.
EXPECTED_SUBSCRIPT_INSTANCES = 6
EXPECTED_BARE_INSTANCES = 10
MACRON_READINGS = ((459, "ᾱ̓́ν"),)


def norm(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def text_of(elem: ET.Element) -> str:
    return norm("".join(elem.itertext()))


def _needs_boundary(left: str, right: str) -> bool:
    return bool(
        left
        and right
        and not left[-1].isspace()
        and not right[0].isspace()
        and right[0] not in ",.;:!?)]}\u00bb\u201d\u2019"
    )


def _plain_text(elem: ET.Element) -> str:
    value = elem.text or ""
    for child in elem:
        child_text = _plain_text(child)
        if child.tag in PLAIN_BOUNDARY_TAGS and _needs_boundary(value, child_text):
            value += " "
        value += child_text
        tail = child.tail or ""
        if child.tag in PLAIN_BOUNDARY_TAGS and _needs_boundary(value, tail):
            value += " "
        value += tail
    return value


def plain_text_of(elem: ET.Element) -> str:
    return norm(_plain_text(elem))


def _text_excluding(elem: ET.Element, excluded: set[str]) -> str:
    value = elem.text or ""
    for child in elem:
        tail = child.tail or ""
        if child.tag not in excluded:
            value += _text_excluding(child, excluded)
        elif _needs_boundary(value, tail):
            value += " "
        value += tail
    return value


def text_excluding(elem: ET.Element, excluded: set[str]) -> str:
    return norm(_text_excluding(elem, excluded))


def clean_cite(value: str) -> str:
    """Trailing ":" and a trailing "." after a digit or ")" are the print's, not
    the reference's; an abbreviation's own dot stays."""
    value = value.rstrip()
    while value.endswith(":") or (value.endswith(".") and value[-2:-1] in "0123456789)"):
        value = value[:-1].rstrip()
    return value


def citation_cite(citation: ET.Element) -> str:
    values: list[str] = []
    for bibl in citation.iter("bibl"):
        value = clean_cite(norm(bibl.get("n") or text_of(bibl)))
        if value and value not in values:
            values.append(value)
    return "; ".join(values)


EXAMPLE_JOIN_RE = re.compile(r"^[\s,;:.]*$")
SUPPLEMENT_RE = re.compile(r"(?:\bsc\.|\(|\[)\s*$")
QUOTE_REFERENCE_RE = re.compile(r"\b\d+\.\d+|\b\d+\s*:")
TRUNCATED_TAIL_RE = re.compile(r"(?:^|\s)[Ͱ-Ͽἀ-῿]$")


def bare_pair_is_sound(grc: str, cite: str) -> bool:
    """An un-wrapped pair ships only if the quotation holds no untagged further
    reference, does not end in an abbreviation cut short by the markup, and the
    citation carries a locator."""
    words = grc.split()
    if not words or not cite:
        return False
    if len(words) > 1 and QUOTE_REFERENCE_RE.search(" ".join(words[1:])):
        return False
    if TRUNCATED_TAIL_RE.search(grc):
        return False
    return bool(re.search(r"\d", cite))


def citation_follows_quote(join: str) -> bool:
    """Whether the print's punctuation puts the citation after the quotation.

    A comma, the Greek question mark, or nothing (the comma being inside the
    quoted words) joins a quotation to its own citation.  A full stop closes
    an entry whose citation has already been given, and a colon marks the
    quote before it as a lemma; after either, the citation belongs to what
    follows it.
    """
    join = norm(join)
    return not join or join.endswith(",") or join.endswith(";")


def bibl_closes_previous(children: list[ET.Element], index: int) -> bool:
    """Whether the ``bibl`` at ``index`` is the citation of the quote before it.

    The print sets a citation either before its quotation, closing it with a
    colon, or after it, joined by the quotation's own closing punctuation.  A
    ``bibl`` with no colon standing after a quotation on such a join belongs
    to that quotation, whatever follows it.
    """
    if index == 0 or children[index - 1].tag != "quote":
        return False
    if not citation_follows_quote(children[index - 1].tail or ""):
        return False
    return not text_of(children[index]).endswith(":")


def expected_examples(parent: ET.Element) -> list[tuple[str, str]]:
    """(grc, cite) of every example under ``parent``, wrapped or bare.

    Re-derives the converter's three shapes independently: a ``cit``; a
    ``bibl`` whose next sibling is a ``quote`` across punctuation only and
    which is not the citation of the quote before it; and a ``quote`` whose
    next sibling is a ``bibl`` across punctuation only, unless that ``bibl``
    ends in a colon, or the join does (a lemma), or the quote is a
    "(sc. ...)" supplement.

    This function is a transcription of the converter and can only catch a
    typo in it.  Check 13 tests the shipped pairs against the print's own
    punctuation instead, and is the check that has to hold.
    """
    found: list[tuple[str, str]] = []
    children = list(parent)
    index = 0
    while index < len(children):
        child = children[index]
        after = children[index + 1] if index + 1 < len(children) else None
        if child.tag == "cit":
            quote = child.find("quote")
            if quote is not None:
                found.append((text_excluding(quote, {"note", "bibl"}), citation_cite(child)))
            index += 1
            continue
        joined = EXAMPLE_JOIN_RE.match(child.tail or "") is not None
        if (
            child.tag == "bibl"
            and after is not None
            and after.tag == "quote"
            and joined
            and not bibl_closes_previous(children, index)
        ):
            pair = (text_excluding(after, {"note", "bibl"}), citation_cite(child))
            if bare_pair_is_sound(*pair):
                found.append(pair)
            index += 2
            continue
        if child.tag == "quote" and after is not None and after.tag == "bibl" and joined:
            before = (children[index - 1].tail if index > 0 else parent.text) or ""
            opens_next = text_of(after).endswith(":") or not citation_follows_quote(
                child.tail or ""
            )
            if not opens_next and not SUPPLEMENT_RE.search(before):
                pair = (text_excluding(child, {"note", "bibl"}), citation_cite(after))
                if bare_pair_is_sound(*pair):
                    found.append(pair)
                index += 2
                continue
        found.extend(expected_examples(child))
        index += 1
    return found


def load_source(path: Path) -> ET.Element:
    value = unicodedata.normalize("NFC", path.read_text(encoding="utf-8"))
    for pattern, replacement in SOURCE_TEXT_FIXES:
        value = pattern.sub(replacement, value)
    root = ET.fromstring(value)
    for elem in root.iter():
        if isinstance(elem.tag, str) and elem.tag.startswith(TEI_NS):
            elem.tag = elem.tag[len(TEI_NS) :]
    body = root.find("text/body")
    if body is None:
        raise ValueError("no TEI body in the source")
    return body


def parent_map(root: ET.Element) -> dict[ET.Element, ET.Element]:
    return {child: parent for parent in root.iter() for child in parent}


def part_of(elem: ET.Element, parents: dict[ET.Element, ET.Element]) -> int:
    current: ET.Element | None = elem
    while current is not None:
        if current.tag == "div" and current.get("type") == "part":
            return int(current.get("n") or 0)
        current = parents.get(current)
    raise ValueError("element outside a part")


def source_sections(
    body: ET.Element,
) -> tuple[dict[int, list[ET.Element]], dict[int, int], dict[str, list[ET.Element]]]:
    """Rebuild source ownership, including the three printed implicit starts."""
    parents = parent_map(body)
    blocks: dict[int, list[ET.Element]] = collections.defaultdict(list)
    parts: dict[int, int] = {}
    prefaces: dict[str, list[ET.Element]] = collections.defaultdict(list)
    current: int | None = None
    preface: str | None = None
    for elem in body.iter():
        if elem.tag == "milestone" and elem.get("unit") == "smythp":
            label = elem.get("n") or ""
            if label.startswith("pref"):
                current = None
                preface = label
            else:
                current = int(label)
                parts[current] = part_of(elem, parents)
                preface = None
            continue
        parent = parents.get(elem)
        if parent is None or parent.tag != "div" or elem.tag not in CONTENT_TAGS:
            continue
        if preface is not None:
            prefaces[preface].append(elem)
            continue
        if current is None:
            continue
        value = text_of(elem)
        inferred = None
        if current == 77 and value.startswith("78."):
            inferred = 78
        elif current == 110 and value.startswith("III. Even here the plural"):
            inferred = 111
        elif current == 641 and value.startswith("642."):
            inferred = 642
        if inferred is not None:
            current = inferred
            parts[current] = part_of(elem, parents)
        blocks[current].append(elem)
    return blocks, parts, prefaces


def restack_macron_text(text: str) -> str:
    """Independently reproduce the innermost-macron rule for text comparison.

    Duplicated rather than imported so check 12 (which tests the converter's
    own restack rule) stays independent of it; this copy exists only so check
    2's exact source/data text comparison accounts for the one authorized
    rewrite instead of flagging it as lost text.
    """

    def restack(match: re.Match[str]) -> str:
        letter = match.group(1)
        parts = unicodedata.normalize("NFD", letter)
        base, marks = parts[0], parts[1:]
        if base not in GREEK_VOWELS or not marks:
            return match.group()
        if GREEK_BREVE in marks:
            return match.group()
        candidate = unicodedata.normalize("NFC", base + GREEK_MACRON) + marks
        if unicodedata.normalize("NFC", candidate) == unicodedata.normalize("NFC", match.group()):
            return match.group()
        return candidate

    return STACKED_MACRON_RE.sub(restack, text)


def block_plain(block: ET.Element, number: int) -> str:
    value = plain_text_of(block)
    prefix = PREFIXES.get(number)
    if prefix and value.startswith(prefix):
        value = value[len(prefix) :].lstrip()
    return restack_macron_text(value)


def ref_target(elem: ET.Element) -> int | None:
    match = re.fullmatch(r"s(\d+)", elem.get("target") or "")
    return int(match.group(1)) if match else None


def ref_range(elem: ET.Element) -> tuple[int, int] | None:
    match = re.search(r"(\d+)\s*[-–—]\s*(\d+)", text_of(elem))
    return (int(match.group(1)), int(match.group(2))) if match else None


class HtmlAudit(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, str]] = []
        self.ids: list[str] = []
        self.refs: list[str] = []
        self.block_in_p: list[str] = []
        self.unbalanced: list[str] = []
        self.greek_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.append(values["id"] or "")
        if tag == "a" and values.get("data-ref"):
            self.refs.append(values["data-ref"] or "")
        if tag in BLOCK_TAGS and any(open_tag == "p" for open_tag, _ in self.stack):
            self.block_in_p.append(f"{tag} inside p")
        inherited = self.stack[-1][1] if self.stack else ""
        language = values.get("lang") or inherited
        if tag not in VOID_TAGS:
            self.stack.append((tag, language))

    def handle_endtag(self, tag: str) -> None:
        tags = [open_tag for open_tag, _ in self.stack]
        if tag not in tags:
            self.unbalanced.append(f"stray </{tag}>")
            return
        if self.stack[-1][0] != tag:
            self.unbalanced.append(f"</{tag}> closes {self.stack[-1][0]}")
        index = len(tags) - 1 - tags[::-1].index(tag)
        self.stack = self.stack[:index]

    def handle_data(self, data: str) -> None:
        if self.stack and self.stack[-1][1] == "grc":
            self.greek_text.append(data)


class Report:
    def __init__(self) -> None:
        self.results: list[tuple[bool, str]] = []

    def add(self, number: int, ok: bool, title: str, detail: str) -> None:
        status = "PASS" if ok else "FAIL"
        self.results.append((ok, title))
        print(f"[{status}] {number}. {title}")
        for line in detail.splitlines():
            print(f"  {line}")

    def summary(self) -> bool:
        passed = sum(ok for ok, _ in self.results)
        failed = len(self.results) - passed
        print("\nVERIFY REPORT SUMMARY")
        print(f"  acceptance checks: {passed} passed, {failed} failed")
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


def all_strings(value: object):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from all_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from all_strings(item)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--sections", type=Path, default=DEFAULT_SECTIONS)
    parser.add_argument("--meta", type=Path, default=DEFAULT_META)
    parser.add_argument("--converter", type=Path, default=DEFAULT_CONVERTER)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    report = Report()
    body = load_source(args.input)
    blocks, source_parts, prefaces = source_sections(body)
    records = load_records(args.sections)
    meta = json.loads(args.meta.read_text(encoding="utf-8"))
    record_by_n = {int(record["n"]): record for record in records}
    record_by_id = {str(record["id"]): record for record in records}

    # 1. Source markers, repaired numbering, and exact record coverage.
    markers = [
        elem for elem in body.iter("milestone") if elem.get("unit") == "smythp"
    ]
    labels = [elem.get("n") or "" for elem in markers]
    source_numbers = [int(value) for value in labels if value.isdigit()]
    counts = collections.Counter(source_numbers)
    missing = [number for number in range(1, LAST_SECTION + 1) if not counts[number]]
    duplicates = {number: count for number, count in counts.items() if count > 1}
    expected_numbers = list(range(1, LAST_SECTION + 1))
    one_ok = (
        len(records) == LAST_SECTION
        and [int(record["n"]) for record in records] == expected_numbers
        and sorted(record_by_n) == expected_numbers
        and sorted(blocks) == expected_numbers
        and missing == [78, 111, 642]
        and duplicates == {88: 2}
        and [value for value in labels if value.startswith("pref")] == ["pref1", "pref2"]
    )
    report.add(
        1,
        one_ok,
        "section extraction and numbering",
        f"source milestones={len(markers)}; numeric markers={len(source_numbers)}; "
        f"unique numeric markers={len(set(source_numbers))}; records={len(records)}\n"
        f"source missing={missing}; source duplicates={duplicates}; repaired=[78, 111, 642]\n"
        f"preface markers={[value for value in labels if value.startswith('pref')]}",
    )

    # 2. Every source body block appears once and in order after known repairs.
    expected_text = norm(
        " ".join(
            block_plain(block, number)
            for number in expected_numbers
            for block in blocks[number]
        )
    )
    actual_text = norm(" ".join(str(record["plain"]) for record in records))
    coverage_ok = expected_text == actual_text
    difference = ""
    if not coverage_ok:
        limit = min(len(expected_text), len(actual_text))
        first = next((i for i in range(limit) if expected_text[i] != actual_text[i]), limit)
        difference = (
            f"\nfirst difference at {first}:\n"
            f"source={expected_text[max(0, first-60):first+60]!r}\n"
            f"data={actual_text[max(0, first-60):first+60]!r}"
        )
    report.add(
        2,
        coverage_ok and int(meta["counts"]["skippedTextElements"]) == 0,
        "full section-body text coverage",
        f"source blocks={sum(len(value) for value in blocks.values())}; "
        f"source chars={len(expected_text)}; record chars={len(actual_text)}\n"
        f"skipped text elements={meta['counts']['skippedTextElements']}{difference}",
    )

    # 3. Canonical shape, IDs, and non-empty bodies.
    bad_shape: list[object] = []
    for record in records:
        number = record.get("n")
        record_id = str(record.get("id", ""))
        if (
            set(record) != REQUIRED_KEYS
            or record.get("work") != "gildersleeve"
            or not ID_RE.fullmatch(record_id)
            or record_id != f"gildersleeve:{number}"
            or not str(record.get("plain", "")).strip()
            or not str(record.get("html", "")).strip()
            or record.get("letters") != []
        ):
            bad_shape.append({"n": number, "keys": sorted(set(record)), "id": record_id})
    report.add(
        3,
        not bad_shape,
        "record shape, canonical IDs, and non-empty text",
        f"required keys={sorted(REQUIRED_KEYS)}\n"
        f"bad records={len(bad_shape)}; examples={bad_shape[:4]}",
    )

    # 4. Tagged section references, ranges, and citedBy inversion.
    expected_refs: dict[int, list[str]] = {}
    expected_ranges: dict[int, list[dict[str, int]]] = {}
    malformed: list[object] = []
    source_ref_count = 0
    for number in expected_numbers:
        refs: list[str] = []
        ranges: list[dict[str, int]] = []
        for block in blocks[number]:
            for ref in block.iter("ref"):
                source_ref_count += 1
                target = ref_target(ref)
                if target is None:
                    malformed.append((number, dict(ref.attrib), text_of(ref)))
                    continue
                target_id = f"gildersleeve:{target}"
                if target_id not in refs:
                    refs.append(target_id)
                found_range = ref_range(ref)
                if found_range:
                    item = {"start": found_range[0], "end": found_range[1]}
                    if item not in ranges:
                        ranges.append(item)
        expected_refs[number] = refs
        expected_ranges[number] = ranges
    ref_mismatches = [
        number
        for number in expected_numbers
        if record_by_n[number]["refs"] != expected_refs[number]
        or record_by_n[number]["refRanges"] != expected_ranges[number]
    ]
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
    unresolved = [
        target for refs in expected_refs.values() for target in refs if target not in record_by_id
    ]
    four_ok = (
        not malformed
        and not ref_mismatches
        and not inverse_mismatches
        and not unresolved
        and source_ref_count == int(meta["counts"]["sectionCrossRefs"])
    )
    report.add(
        4,
        four_ok,
        "cross-references, ranges, and citedBy",
        f"source ref uses={source_ref_count}; unique record edges="
        f"{sum(len(record['refs']) for record in records)}; ranges="
        f"{sum(len(record['refRanges']) for record in records)}\n"
        f"malformed={malformed[:4]}; unresolved={unresolved}; "
        f"record mismatches={ref_mismatches[:8]}; inverse mismatches={inverse_mismatches[:8]}",
    )

    # 5. Notes, footnotes, examples, and two heading-note exceptions.
    source_notes = [
        note for number in expected_numbers for block in blocks[number] for note in block.iter("note")
    ]
    data_notes = [note for record in records for note in record["notes"]]
    source_citations = [
        cit for number in expected_numbers for block in blocks[number] for cit in block.iter("cit")
    ]
    data_examples = [example for record in records for example in record["examples"]]
    bad_notes = [
        note
        for note in data_notes
        if set(note) != {"anchor", "label", "kind", "html", "plain"}
        or note.get("kind") not in {"note", "footnote"}
        or not str(note.get("plain", "")).strip()
    ]
    bad_examples = [
        example
        for example in data_examples
        if set(example) != {"grc", "gloss", "cite"} or not str(example.get("grc", "")).strip()
    ]
    expected_example_core: list[tuple[str, str]] = []
    for number in expected_numbers:
        for block in blocks[number]:
            expected_example_core.extend(expected_examples(block))
    wrapped_examples = sum(1 for citation in source_citations if citation.find("quote") is not None)
    actual_example_core = [
        (str(example.get("grc", "")), str(example.get("cite", "")))
        for example in data_examples
    ]
    example_core_mismatches = [
        index
        for index, (expected, actual) in enumerate(
            zip(expected_example_core, actual_example_core, strict=False)
        )
        if expected != actual
    ]
    parents = parent_map(body)
    heading_notes = [
        note for note in body.iter("note") if parents.get(note) is not None and parents[note].tag == "head"
    ]
    five_ok = (
        len(data_notes) == len(source_notes)
        and len(data_examples) == len(expected_example_core)
        and wrapped_examples <= len(expected_example_core)
        and not bad_notes
        and not bad_examples
        and expected_example_core == actual_example_core
        and len(heading_notes) == 2
        and len(meta["anomalies"]["unassignedElements"]) == 2
    )
    report.add(
        5,
        five_ok,
        "notes, footnotes, and examples",
        f"section notes source/data={len(source_notes)}/{len(data_notes)} "
        f"(inline={meta['counts']['notes']}, footnotes={meta['counts']['footnotes']})\n"
        f"examples source/data={len(expected_example_core)}/{len(data_examples)} "
        f"(cit-wrapped={wrapped_examples} of {len(source_citations)} cit tags); "
        f"bad note records={len(bad_notes)}; bad examples={len(bad_examples)}\n"
        f"filtered Greek/cite mismatches={example_core_mismatches[:8]}\n"
        f"notes attached to structural headings and inventoried={len(heading_notes)}",
    )

    # 6. NFC Greek, forbidden Latin quantity marks, and Beta Code residue.
    audits: dict[int, HtmlAudit] = {}
    not_nfc: list[object] = []
    replacement_chars: list[object] = []
    bad_macrons: list[object] = []
    beta_residue: list[object] = []
    greek_char_count = 0
    for record in records:
        number = int(record["n"])
        audit = HtmlAudit()
        audit.feed(str(record["html"]))
        audits[number] = audit
        for value in all_strings(record):
            if unicodedata.normalize("NFC", value) != value:
                not_nfc.append((number, value[:80]))
            if "\ufffd" in value or any(0xD800 <= ord(char) <= 0xDFFF for char in value):
                replacement_chars.append((number, value[:80]))
        for chunk in audit.greek_text:
            greek_char_count += sum(
                0x0370 <= ord(char) <= 0x03FF or 0x1F00 <= ord(char) <= 0x1FFF
                for char in chunk
            )
            found_macrons = sorted(set(chunk) & set(MACRON_VOWELS))
            if found_macrons:
                bad_macrons.append((number, "".join(found_macrons), chunk[:100]))
            found_beta = BETA_CODE_RE.findall(chunk)
            if found_beta:
                beta_residue.append((number, found_beta[:5], chunk[:120]))
    six_ok = (
        not not_nfc
        and not replacement_chars
        and not bad_macrons
        and not beta_residue
        and greek_char_count > 0
    )
    report.add(
        6,
        six_ok,
        "NFC polytonic Greek and residue rejection",
        f"Greek-script characters audited={greek_char_count}; non-NFC strings={len(not_nfc)}; "
        f"invalid/replacement strings={len(replacement_chars)}\n"
        f"Latin macron/breve vowels inside Greek spans={bad_macrons[:5]}\n"
        f"Beta Code residue inside Greek spans={beta_residue[:5]}",
    )

    # 7. HTML balance and absence of raw TEI, tags, or unresolved entities.
    block_in_p = [
        (number, item) for number, audit in audits.items() for item in audit.block_in_p
    ]
    unbalanced = [
        (number, item) for number, audit in audits.items() for item in audit.unbalanced
    ] + [
        (number, f"unclosed {[tag for tag, _ in audit.stack]}")
        for number, audit in audits.items()
        if audit.stack
    ]
    duplicate_ids = [
        (number, [value for value, count in collections.Counter(audit.ids).items() if count > 1])
        for number, audit in audits.items()
        if any(count > 1 for count in collections.Counter(audit.ids).values())
    ]
    tei_leaks = [record["id"] for record in records if TEI_LEAK_RE.search(str(record["html"]))]
    raw_plain_tags = [record["id"] for record in records if RAW_TAG_RE.search(str(record["plain"]))]
    raw_plain_entities = [
        record["id"] for record in records if RAW_ENTITY_RE.search(str(record["plain"]))
    ]
    unknown_html_entities = [
        record["id"] for record in records if HTML_UNKNOWN_ENTITY_RE.search(str(record["html"]))
    ]
    html_refs = [value for audit in audits.values() for value in audit.refs]
    seven_ok = (
        not block_in_p
        and not unbalanced
        and not duplicate_ids
        and not tei_leaks
        and not raw_plain_tags
        and not raw_plain_entities
        and not unknown_html_entities
        and len(html_refs) == source_ref_count
        and all(ID_RE.fullmatch(value) for value in html_refs)
    )
    report.add(
        7,
        seven_ok,
        "HTML validity and XML leakage",
        f"block-in-p={block_in_p[:5]}; unbalanced={unbalanced[:5]}; duplicate ids={duplicate_ids[:5]}\n"
        f"TEI leaks={tei_leaks[:5]}; raw tags in plain={raw_plain_tags[:5]}; "
        f"raw entities in plain={raw_plain_entities[:5]}; unknown HTML entities={unknown_html_entities[:5]}\n"
        f"HTML reference links={len(html_refs)}; source reference uses={source_ref_count}",
    )

    # 8. Part split, heading paths, and prev/next chain.
    chain_errors: list[object] = []
    part_errors: list[object] = []
    for index, record in enumerate(records):
        number = int(record["n"])
        expected_prev = records[index - 1]["id"] if index else None
        expected_next = records[index + 1]["id"] if index + 1 < len(records) else None
        if record["prev"] != expected_prev or record["next"] != expected_next:
            chain_errors.append((number, record["prev"], record["next"]))
        if int(record["part"]) != source_parts[number]:
            part_errors.append((number, record["part"], source_parts[number]))
        path = record["path"]
        expected_part_label = "PART I" if record["part"] == 1 else "PART II"
        if (
            not isinstance(path, list)
            or len(path) < 2
            or path[0] != expected_part_label
            or record["head"] != path[-1]
        ):
            part_errors.append((number, "path", path))
    part_one = [int(record["n"]) for record in records if record["part"] == 1]
    part_two = [int(record["n"]) for record in records if record["part"] == 2]
    sane_boundary = (
        part_one == list(range(1, 468))
        and part_two == list(range(468, LAST_SECTION + 1))
        and max(part_one) < min(part_two)
    )
    report.add(
        8,
        not chain_errors and not part_errors and sane_boundary,
        "part boundary, heading paths, and navigation",
        f"part I={min(part_one)}-{max(part_one)} ({len(part_one)}); "
        f"part II={min(part_two)}-{max(part_two)} ({len(part_two)}); sane={sane_boundary}\n"
        f"part/path errors={part_errors[:6]}; chain errors={chain_errors[:6]}",
    )

    # 9. Two fresh conversions must match each other and the current data.
    determinism_error = ""
    hashes: list[str] = []
    current_hash = combined_hash(args.sections, args.meta)
    try:
        with tempfile.TemporaryDirectory(prefix="verify-gildersleeve-") as temp_name:
            temp = Path(temp_name)
            for run in (1, 2):
                out_sections = temp / f"sections-{run}.jsonl"
                out_meta = temp / f"meta-{run}.json"
                completed = subprocess.run(
                    [
                        sys.executable, str(args.converter), "--input", str(args.input),
                        "--sections", str(out_sections), "--meta", str(out_meta),
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                if completed.returncode != 0:
                    raise RuntimeError(f"converter run {run} failed: {completed.stderr.strip()}")
                hashes.append(combined_hash(out_sections, out_meta))
    except Exception as error:
        determinism_error = str(error)
    nine_ok = (
        not determinism_error and len(hashes) == 2 and hashes[0] == hashes[1] == current_hash
    )
    report.add(
        9,
        nine_ok,
        "deterministic conversion",
        f"current hash={current_hash}\nrun hashes={hashes}\nerror={determinism_error or 'none'}",
    )

    # 10. Print three exact source/data samples for visual review.
    samples_ok = True
    sample_lines: list[str] = []
    for number in (1, 400, 674):
        record = record_by_n.get(number)
        source_plain = norm(" ".join(block_plain(block, number) for block in blocks[number]))
        if record is None or record["plain"] != source_plain:
            samples_ok = False
            sample_lines.append(f"§{number}: MISMATCH")
            continue
        sample = str(record["plain"])
        excerpt = sample if len(sample) <= 420 else sample[:417] + "..."
        sample_lines.append(
            f"§{number} [{record['path'][0]} — {record['head']}] chars={len(sample)}\n    {excerpt}"
        )
    report.add(10, samples_ok, "sample sections 1, 400, and 674", "\n".join(sample_lines))

    # 11. Reject editorial Latin in extracted Greek and lost inline boundaries.
    latin_in_grc: list[tuple[int, int, str]] = []
    greek_ascii_glue: list[tuple[int, int, str]] = []
    for record in records:
        number = int(record["n"])
        for index, example in enumerate(record["examples"]):
            grc = str(example.get("grc", ""))
            if re.search(r"[A-Za-z]", grc):
                latin_in_grc.append((number, index, grc[:120]))
        plain = str(record["plain"])
        for index in range(len(plain) - 1):
            left, right = plain[index], plain[index + 1]
            if (
                right in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                and unicodedata.category(left).startswith("L")
                and "GREEK" in unicodedata.name(left, "")
            ):
                greek_ascii_glue.append(
                    (number, index, plain[max(0, index - 40) : index + 82])
                )
    report.add(
        11,
        not latin_in_grc and not greek_ascii_glue,
        "pure extracted Greek and plain-text subtree boundaries",
        f"examples with ASCII letters in grc={len(latin_in_grc)}; "
        f"samples={latin_in_grc[:5]}\n"
        f"Greek-letter + ASCII-capital glue in plain={len(greek_ascii_glue)}; "
        f"samples={greek_ascii_glue[:5]}",
    )

    # 12. Macron stacking. Independently re-derive the source counts from the
    # raw TEI text (not the converter's own tally) and check the positional
    # invariant on the built records: no combining macron may follow a letter
    # carrying any other mark, except a subscript site left canonically
    # equivalent on purpose (see the constants above).
    source_nfc = unicodedata.normalize("NFC", args.input.read_text(encoding="utf-8"))
    source_macrons = {"stacked": 0, "anceps": 0, "bare": 0, "subscriptEquivalent": 0}
    for match in STACKED_MACRON_RE.finditer(source_nfc):
        letter = match.group(1)
        parts = unicodedata.normalize("NFD", letter)
        base, marks = parts[0], parts[1:]
        if base not in GREEK_VOWELS or not marks:
            source_macrons["bare"] += 1
        elif GREEK_BREVE in marks:
            source_macrons["anceps"] += 1
        else:
            candidate = unicodedata.normalize("NFC", base + GREEK_MACRON) + marks
            if unicodedata.normalize("NFC", candidate) == unicodedata.normalize("NFC", match.group()):
                source_macrons["subscriptEquivalent"] += 1
            else:
                source_macrons["stacked"] += 1
    stacked_left: list[object] = []
    orphan_macrons: list[object] = []
    # Anything that reaches this bucket is neither absorbed into a precomposed
    # base (the alpha/iota/upsilon case, which leaves no standalone macron to
    # find here at all) nor one of the two known shapes below -- a tripwire
    # for a restack shape this corpus does not currently have.
    unclassified_instances = 0
    subscript_instances = 0
    bare_instances = 0
    for record in records:
        for field in ("html", "plain"):
            text = str(record.get(field, ""))
            for index in [m.start() for m in re.finditer(GREEK_MACRON, text)]:
                back = index
                while back and unicodedata.combining(text[back - 1]):
                    back -= 1
                carrier = text[back - 1] if back else ""
                between = text[back:index]
                parts = unicodedata.normalize("NFD", carrier)
                context = text[max(0, index - 20) : index + 6]
                if not re.match(r"[Ͱ-Ͽἀ-῿]", carrier):
                    orphan_macrons.append((record["n"], context))
                elif GREEK_BREVE in parts[1:] or GREEK_BREVE in between:
                    stacked_left.append((record["n"], "unexpected anceps", context))
                elif between:
                    stacked_left.append((record["n"], context))
                elif len(parts) == 1:
                    bare_instances += 1
                elif parts[1:] == GREEK_YPOGEGRAMMENI:
                    subscript_instances += 1
                else:
                    unclassified_instances += 1
    macron_repairs = {
        key: meta["anomalies"]["sourceMarkRepairs"][key] for key in EXPECTED_MACRON_REPAIRS
    }
    # The one real restack is alpha-based, so its macron is absorbed into the
    # precomposed base (ᾱ) and never appears as a standalone mark above --
    # confirmed here instead by the exact printed reading it must produce.
    macron_misread = [
        (number, reading)
        for number, reading in MACRON_READINGS
        if reading not in str(record_by_n.get(number, {}).get("plain", ""))
    ]
    report.add(
        12,
        source_macrons == EXPECTED_SOURCE_MACRONS
        and macron_repairs == EXPECTED_MACRON_REPAIRS
        and not stacked_left
        and not orphan_macrons
        and not unclassified_instances
        and subscript_instances == EXPECTED_SUBSCRIPT_INSTANCES
        and bare_instances == EXPECTED_BARE_INSTANCES
        and not macron_misread,
        "macron stacking",
        f"source macrons={source_macrons}, expected {EXPECTED_SOURCE_MACRONS}\n"
        f"restacked={macron_repairs}, expected {EXPECTED_MACRON_REPAIRS}\n"
        f"macrons still outside another mark={len(stacked_left)}; examples={stacked_left[:5]}\n"
        f"macrons on a non-Greek carrier={len(orphan_macrons)}; examples={orphan_macrons[:5]}\n"
        f"unclassified standalone-macron instances={unclassified_instances}\n"
        f"kept-subscript instances={subscript_instances}, expected {EXPECTED_SUBSCRIPT_INSTANCES}\n"
        f"already-bare instances={bare_instances}, expected {EXPECTED_BARE_INSTANCES}\n"
        f"audited readings checked={len(MACRON_READINGS)}, not reproduced={macron_misread}",
    )

    # 13. The print's own punctuation, read without the converter's algorithm.
    #
    # Check 5 re-derives collect_examples and so can only find a typo in the
    # transcription of it; it certified 56 stolen citations as correct.  The
    # three tests here read the print instead and ask what the shipped rows
    # say, which is why they are the ones that have to hold.
    # Every shipped (grc, cite) must stand together in the print at least as
    # many times as it is shipped: inside one cit, or as a quote and the bibl
    # right after it, or as a quote and the bibl right before it when the
    # print's punctuation has not already given that bibl to the quote before
    # THAT.  Counting rather than matching keeps a section that prints the
    # same short quotation twice from covering a stolen citation.
    unlawful: list[tuple[int, str, str, int, int]] = []
    closing_bibls = 0
    for number in expected_numbers:
        lawful: collections.Counter[tuple[str, str]] = collections.Counter()
        for block in blocks[number]:
            for parent in [block] + list(block.iter()):
                children = list(parent)
                for index, child in enumerate(children):
                    if child.tag != "quote":
                        continue
                    grc = text_excluding(child, {"note", "bibl"})
                    if parent.tag == "cit":
                        lawful[(grc, citation_cite(parent))] += 1
                    after = children[index + 1] if index + 1 < len(children) else None
                    if after is not None and after.tag == "bibl":
                        lawful[(grc, citation_cite(after))] += 1
                    if index and children[index - 1].tag == "bibl":
                        if bibl_closes_previous(children, index - 1):
                            closing_bibls += 1
                            continue
                        lawful[(grc, citation_cite(children[index - 1]))] += 1
        shipped = collections.Counter(
            (str(example["grc"]), str(example["cite"]))
            for example in record_by_n[number]["examples"]
        )
        for pair, count in shipped.items():
            if count > lawful[pair]:
                unlawful.append((number, pair[0][:60], pair[1], count, lawful[pair]))

    # A quotation that carries a reference of its own holds more than one
    # passage, and whatever citation it ships under is wrong for the rest.
    packed = [
        (int(record["n"]), str(example["grc"])[:60], str(example["cite"]))
        for record in records
        for example in record["examples"]
        if len(str(example["grc"]).split()) > 1
        and QUOTE_REFERENCE_RE.search(" ".join(str(example["grc"]).split()[1:]))
    ]
    report.add(
        13,
        not unlawful and not packed,
        "shipped citations against the print's punctuation",
        f"bibls the print gives to the quotation before them, so not counted "
        f"for the one after={closing_bibls}\n"
        f"shipped pairs the print does not set together that often="
        f"{len(unlawful)}; examples={unlawful[:5]}\n"
        f"quotations shipped with a reference of their own={len(packed)}; "
        f"examples={packed[:5]}",
    )

    return 0 if report.summary() else 1


if __name__ == "__main__":
    raise SystemExit(main())
