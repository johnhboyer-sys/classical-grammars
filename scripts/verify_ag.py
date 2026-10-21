#!/usr/bin/env python3
"""Independently verify the Allen & Greenough TEI conversion and report."""

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

from convert_ag import repair


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = (
    ROOT
    / "grammar-ag-tei"
    / "data"
    / "viaf39744457"
    / "001"
    / "viaf39744457.001.perseus-eng1.xml"
)
DEFAULT_SECTIONS = ROOT / "data" / "ag" / "sections.jsonl"
DEFAULT_META = ROOT / "data" / "ag" / "meta.json"
DEFAULT_CONVERTER = ROOT / "scripts" / "convert_ag.py"

TEI_NS = "{http://www.tei-c.org/ns/1.0}"
GLOSSARY_HEAD = "GLOSSARY: OF TERMS USED IN GRAMMAR, RHETORIC, AND PROSODY"
LAST_PRINTED_SECTION = 638
CONTENT_TAGS = {"p", "table", "list", "note", "pb", "milestone"}
ID_RE = re.compile(r"^ag:(\d+)$")
LETTER_RE = re.compile(r"^[a-z]$")
NOTE_ANCHOR_RE = re.compile(r"^(?:n\d*|fn\d+)(?:-\d+)?$")
MACRONS = "āēīōūȳăĕĭŏŭ"
# What the print may set between a quotation and its translation: its citation
# in brackets, and nothing else but punctuation.
PRINTED_CITATION_RE = re.compile(
    r"^[\s,;:.—–-]*(?:\([^()]*\)|\[[^\[\]]*\])?[\s,;:.—–-]*$"
)
# A source reference in brackets: a digit with either an abbreviation closed by
# a period or a book.line locus.  "(March 28)", inside a real translation at
# Sec. 424, has neither and so is not one.
UNTAGGED_REFERENCE_RE = re.compile(
    r"\((?=[^()]*\d)[^()]*?(?:[A-Za-z]\.\s|\d+\.\d)[^()]*\)"
)
# HTML that a <p> may not contain.
BLOCK_TAGS = {"p", "table", "ol", "ul", "li", "tr", "td", "aside", "h4", "section"}
REQUIRED_KEYS = {
    "work",
    "n",
    "id",
    "letters",
    "notes",
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
VOID_TAGS = {"br", "hr", "img", "meta", "link", "input"}
# a long vowel with a spacing breve (U+02D8) typed after it: Perseus's way of
# writing a vowel the print marks with both signs at once (A&G §10)
# Perseus's names for signs it could not type, and the pause sign typed as ˆ;
# the converter writes each as the print shows it (MARKS in convert_ag.py)
MARK_PLACEHOLDER = re.compile(r"\[(?:acutemacr|acutebreve|macrcirc|gtbreve|wacute)\]|ˆ")
LOOSE_BREVE = re.compile("[\u0101\u0113\u012b\u014d\u016b\u0233\u0100\u0112\u012a\u014c\u016a\u0232]\u02d8")


def norm(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def text_of(elem: ET.Element) -> str:
    return norm("".join(elem.itertext()))


def load_source(path: Path) -> ET.Element:
    # read through the converter's own repair() (checks 12 and 13), so
    # coverage compares like with like
    root = ET.fromstring(repair(path.read_text(encoding="utf-8")))
    for elem in root.iter():
        if isinstance(elem.tag, str) and elem.tag.startswith(TEI_NS):
            elem.tag = elem.tag[len(TEI_NS) :]
    body = root.find("text/body")
    if body is None:
        raise ValueError("no TEI body in the source")
    return body


def glossary_elements(body: ET.Element) -> set[ET.Element]:
    members: set[ET.Element] = set()
    for div in body.iter("div"):
        if any(
            child.tag == "head" and text_of(child) == GLOSSARY_HEAD for child in div
        ):
            members.update(div.iter())
    return members


def source_blocks(body: ET.Element) -> list[ET.Element]:
    """List the block-level children of divs that belong to printed sections."""
    parents = {child: parent for parent in body.iter() for child in parent}
    glossary = glossary_elements(body)
    blocks: list[ET.Element] = []
    started = False
    for elem in body.iter():
        if (
            elem.tag == "milestone"
            and elem.get("unit") == "smythp"
            and elem not in glossary
        ):
            started = True
            continue
        parent = parents.get(elem)
        if parent is None or parent.tag != "div" or elem.tag not in CONTENT_TAGS:
            continue
        if started and elem not in glossary:
            blocks.append(elem)
    return blocks


def source_ranges(body: ET.Element) -> list[tuple[int, int]]:
    """Derive cross-ref ranges without using converter code or metadata."""
    found: list[tuple[int, int]] = []

    def number(elem: ET.Element) -> int | None:
        match = re.search(r"\d+", elem.get("n") or text_of(elem))
        return int(match.group()) if match else None

    def add(start: int | None, end: int | None) -> None:
        if start is not None and end is not None and (start, end) not in found:
            found.append((start, end))

    for parent in body.iter():
        children = list(parent)
        for index, child in enumerate(children):
            if child.tag != "ref":
                continue
            tail = child.tail or ""
            numeric = re.match(r"^\s*[-–—]\s*(\d+)", tail)
            if numeric:
                add(number(child), int(numeric.group(1)))
            elif (
                re.fullmatch(r"\s*[-–—]\s*", tail)
                and index + 1 < len(children)
                and children[index + 1].tag == "ref"
            ):
                add(number(child), number(children[index + 1]))
    return found


class HtmlAudit(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.ids: list[str] = []
        self.refs: list[str] = []
        self.ref_anchors: list[str] = []
        self.block_in_p: list[str] = []
        self.unbalanced: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.append(values["id"] or "")
        if tag == "a" and values.get("data-ref"):
            self.refs.append(values["data-ref"] or "")
            if values.get("data-anchor"):
                self.ref_anchors.append(values["data-anchor"] or "")
        if tag in BLOCK_TAGS and "p" in self.stack:
            self.block_in_p.append(f"{tag} inside p")
        if tag not in VOID_TAGS:
            self.stack.append(tag)

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.append(values["id"] or "")

    def handle_endtag(self, tag: str) -> None:
        if tag not in self.stack:
            self.unbalanced.append(f"stray </{tag}>")
            return
        if self.stack[-1] != tag:
            self.unbalanced.append(f"</{tag}> closes {self.stack[-1]}")
        index = len(self.stack) - 1 - self.stack[::-1].index(tag)
        self.stack = self.stack[:index]


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
    body = load_source(args.input)
    glossary = glossary_elements(body)
    records = load_records(args.sections)
    meta = json.loads(args.meta.read_text(encoding="utf-8"))
    record_by_id = {str(record.get("id")): record for record in records}
    record_by_n = {int(record["n"]): record for record in records if "n" in record}

    # 1. Section extraction and numbering.
    markers = [
        elem
        for elem in body.iter()
        if elem.tag == "milestone" and elem.get("unit") == "smythp"
    ]
    printed = [int(elem.get("n") or 0) for elem in markers if elem not in glossary]
    glossary_markers = [int(elem.get("n") or 0) for elem in markers if elem in glossary]
    counts = collections.Counter(printed)
    duplicates = {number: count for number, count in counts.items() if count > 1}
    gaps = [
        number for number in range(1, LAST_PRINTED_SECTION + 1) if counts[number] == 0
    ]
    data_gaps = [
        number for number in range(1, LAST_PRINTED_SECTION + 1) if number not in record_by_n
    ]
    one_ok = (
        len(markers) == int(meta["counts"]["sectionMarkers"])
        and len(printed) == LAST_PRINTED_SECTION
        and len(records) == LAST_PRINTED_SECTION
        and not gaps
        and not duplicates
        and not data_gaps
        and set(record_by_n) == set(printed)
        and sorted(glossary_markers) == list(meta["anomalies"]["backMatter"]["sourceSectionNumbers"])
    )
    report.add(
        1,
        one_ok,
        "section extraction and numbering",
        f"source section markers={len(markers)}; printed={len(printed)}; "
        f"back-matter markers={sorted(glossary_markers)}; records={len(records)}\n"
        f"coverage gaps={gaps}; duplicates={duplicates}; data gaps={data_gaps}\n"
        f"printed range={min(printed)}-{max(printed)}",
    )

    # 2. Complete text coverage: every source block lands in exactly one record,
    #    in document order, with nothing added and nothing dropped.
    blocks = source_blocks(body)
    expected_text = norm(" ".join(text_of(block) for block in blocks))
    actual_text = norm(" ".join(str(record["plain"]) for record in records))
    coverage_ok = expected_text == actual_text
    diff = ""
    if not coverage_ok:
        limit = min(len(expected_text), len(actual_text))
        first = next(
            (i for i in range(limit) if expected_text[i] != actual_text[i]), limit
        )
        diff = (
            f"\nfirst difference at {first}:\n"
            f"  source: {expected_text[first - 60:first + 60]!r}\n"
            f"  data:   {actual_text[first - 60:first + 60]!r}"
        )
    report.add(
        2,
        coverage_ok,
        "full text coverage of every source block",
        f"source blocks={len(blocks)}; source chars={len(expected_text)}; "
        f"record chars={len(actual_text)}{diff}",
    )

    # 3. Record shape, IDs, and non-empty text.
    bad_shape: list[object] = []
    for record in records:
        missing = sorted(REQUIRED_KEYS - set(record))
        record_id = str(record.get("id", ""))
        number = record.get("n")
        if (
            missing
            or set(record) != REQUIRED_KEYS
            or record.get("work") != "ag"
            or not ID_RE.fullmatch(record_id)
            or record_id != f"ag:{number}"
            or not str(record.get("html", "")).strip()
            or not str(record.get("plain", "")).strip()
        ):
            bad_shape.append({"n": number, "missing": missing, "id": record_id})
    report.add(
        3,
        not bad_shape,
        "record shape, IDs, and text",
        f"keys={sorted(REQUIRED_KEYS)}\n"
        f"bad records={len(bad_shape)}; examples={bad_shape[:5]}",
    )

    # 4. Cross-references and ranges.
    refs = [elem for elem in body.iter("ref")]
    section_refs = [elem for elem in refs if elem not in glossary]
    def ref_target(elem: ET.Element) -> int | None:
        match = re.search(r"\d+", elem.get("n") or text_of(elem))
        return int(match.group()) if match else None

    malformed = [elem for elem in section_refs if ref_target(elem) is None]
    unresolved_source = sorted(
        {
            ref_target(elem)
            for elem in section_refs
            if ref_target(elem) is not None and ref_target(elem) not in record_by_n
        }
    )
    reported_unresolved = sorted(
        {int(item["target"]) for item in meta["anomalies"]["unresolvedRefs"]}
    )
    bad_record_refs = [
        (record["id"], target)
        for record in records
        for target in record["refs"]
        if not ID_RE.fullmatch(str(target))
    ]
    expected_ranges = source_ranges(body)
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
        if value[0] not in record_by_n or value[1] not in record_by_n or value[0] > value[1]
    ]
    record_range_set = set(record_ranges)
    ranges_outside = [value for value in expected_ranges if value not in record_range_set]
    reported_outside = [
        (int(item["start"]), int(item["end"]))
        for item in meta["anomalies"]["rangesOutsideSections"]
    ]
    four_ok = (
        not malformed
        and unresolved_source == reported_unresolved
        and not bad_record_refs
        and not bad_ranges
        and expected_ranges == meta_ranges
        and len(section_refs) == int(meta["counts"]["sectionCrossRefs"])
        and len(refs) == int(meta["counts"]["sourceCrossRefs"])
        and ranges_outside == reported_outside
    )
    report.add(
        4,
        four_ok,
        "cross-references and ranges",
        f"source refs={len(refs)}; in printed sections={len(section_refs)}; "
        f"in back matter={len(refs) - len(section_refs)}\n"
        f"unique record edges={sum(len(r['refs']) for r in records)}; "
        f"malformed={len(malformed)}\n"
        f"unresolved targets (source)={unresolved_source}; reported in meta={reported_unresolved}\n"
        f"distinct source ranges={len(expected_ranges)}; meta ranges={len(meta_ranges)}; "
        f"record range uses={len(record_ranges)}; bad endpoints={bad_ranges[:5]}\n"
        f"ranges={expected_ranges}",
    )

    # 5. citedBy inversion.
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
        5,
        not inverse_mismatches,
        "citedBy exact inverse",
        f"citedBy entries={sum(len(r['citedBy']) for r in records)}; "
        f"ref edges={sum(1 for r in records for t in r['refs'] if t in record_by_id)}\n"
        f"mismatched records={len(inverse_mismatches)}; examples={inverse_mismatches[:10]}",
    )

    # 6. Examples and citations.
    citations = [elem for block in blocks for elem in block.iter("cit")]
    output_examples = [ex for record in records for ex in record["examples"]]
    empty_latin = [ex for ex in output_examples if not str(ex.get("la", "")).strip()]
    bad_example_keys = [ex for ex in output_examples if set(ex) != {"la", "gloss", "cite"}]
    source_quotes = [elem for block in blocks for elem in block.iter("quote")]
    six_ok = (
        len(output_examples) == len(citations)
        and len(output_examples) == int(meta["counts"]["examples"])
        and not empty_latin
        and not bad_example_keys
        and len(source_quotes) == int(meta["counts"]["quotes"])
    )
    report.add(
        6,
        six_ok,
        "examples and citations",
        f"source cit elements in sections={len(citations)}; output examples={len(output_examples)}\n"
        f"examples with no Latin={len(empty_latin)}; bad key sets={len(bad_example_keys)}\n"
        f"without gloss={meta['anomalies']['examplesWithoutGloss']}; "
        f"without cite={meta['anomalies']['examplesWithoutCite']}",
    )

    # 7. Anchors: letters, notes, footnotes.  Every declared anchor must exist
    #    in the HTML, and no HTML id may repeat inside a section.
    audits: dict[int, HtmlAudit] = {}
    bad_anchors: list[object] = []
    duplicate_ids: list[object] = []
    for record in records:
        audit = HtmlAudit()
        audit.feed(str(record["html"]))
        audits[int(record["n"])] = audit
        repeated = [
            value for value, count in collections.Counter(audit.ids).items() if count > 1
        ]
        if repeated:
            duplicate_ids.append((record["id"], repeated))
        for anchor in record["letters"]:
            if not LETTER_RE.fullmatch(str(anchor)) or anchor not in audit.ids:
                bad_anchors.append((record["id"], "letter", anchor))
        seen: list[str] = []
        footnote_index = 0
        for note in record["notes"]:
            anchor = str(note.get("anchor", ""))
            kind = note.get("kind")
            if (
                not NOTE_ANCHOR_RE.fullmatch(anchor)
                or anchor in seen
                or anchor not in audit.ids
                or kind not in {"note", "footnote"}
                or set(note) != {"anchor", "label", "kind", "html", "plain"}
            ):
                bad_anchors.append((record["id"], "note", anchor))
            seen.append(anchor)
            if kind == "footnote":
                footnote_index += 1
                if anchor != f"fn{footnote_index}":
                    bad_anchors.append((record["id"], "footnote order", anchor))
            elif note.get("label") and anchor.split("-")[0] != f"n{note['label']}":
                bad_anchors.append((record["id"], "note label", anchor))
    source_letters = sum(
        1
        for block in blocks
        for elem in block.iter()
        if elem.tag == "milestone" and elem.get("unit") == "smythsub"
    )
    source_notes = [elem for block in blocks for elem in block.iter("note")]
    data_notes = sum(len(record["notes"]) for record in records)
    implicit = len(meta["anomalies"]["implicitLetterAnchors"])
    seven_ok = (
        not bad_anchors
        and not duplicate_ids
        and data_notes == len(source_notes)
        and data_notes == int(meta["counts"]["notes"]) + int(meta["counts"]["footnotes"])
        and sum(len(record["letters"]) for record in records) == source_letters + implicit
    )
    report.add(
        7,
        seven_ok,
        "letter, note, and footnote anchors",
        f"sections with letters={sum(bool(r['letters']) for r in records)}; "
        f"letter anchors={sum(len(r['letters']) for r in records)} "
        f"(source markers={source_letters} + implicit={implicit})\n"
        f"notes in source sections={len(source_notes)}; note records={data_notes} "
        f"(notes={meta['counts']['notes']}, footnotes={meta['counts']['footnotes']})\n"
        f"bad anchors={bad_anchors[:8]}; duplicate HTML ids={duplicate_ids[:5]}",
    )

    # 8. HTML rules: balance, no block inside <p>, no TEI leakage, NFC, macrons.
    block_in_p = [
        (number, item) for number, audit in audits.items() for item in audit.block_in_p
    ]
    unbalanced = [
        (number, item) for number, audit in audits.items() for item in audit.unbalanced
    ]
    leaks = [
        record["id"]
        for record in records
        if re.search(
            r"TEIform|xmlns|xml:lang|<(?:foreign|gloss|emph|ref|cit|bibl|milestone|item|cell|row)\b",
            str(record["html"]),
        )
    ]
    bad_placeholders = [
        (number, value)
        for number, audit in audits.items()
        for value in audit.refs
        if not ID_RE.fullmatch(value)
    ]
    bad_ref_anchors = [
        value
        for audit in audits.values()
        for value in audit.ref_anchors
        if not LETTER_RE.fullmatch(value)
    ]
    # "§ 598. f" cites a subsection: the source splits it into a ref, a "." in
    # the tail, and an emph holding the letter.  Re-derive the count here.
    lettered_in_sections = 0
    for block in blocks:
        for parent in block.iter():
            children = list(parent)
            for index, child in enumerate(children):
                if child.tag != "ref" or norm(child.tail) != ".":
                    continue
                following = children[index + 1] if index + 1 < len(children) else None
                if (
                    following is not None
                    and following.tag == "emph"
                    and re.fullmatch(r"[a-z]\.?", text_of(following))
                ):
                    lettered_in_sections += 1
    html_lettered = sum(len(audit.ref_anchors) for audit in audits.values())
    html_ref_count = sum(len(audit.refs) for audit in audits.values())
    unnormalized = [
        record["id"]
        for record in records
        if unicodedata.normalize("NFC", str(record["html"])) != str(record["html"])
        or unicodedata.normalize("NFC", str(record["plain"])) != str(record["plain"])
    ]
    source_macrons = collections.Counter(
        char for block in blocks for char in text_of(block) if char in MACRONS
    )
    data_macrons = collections.Counter(
        char for record in records for char in str(record["plain"]) if char in MACRONS
    )
    eight_ok = (
        not block_in_p
        and not unbalanced
        and not leaks
        and not bad_placeholders
        and not bad_ref_anchors
        and not unnormalized
        and html_ref_count == int(meta["counts"]["sectionCrossRefs"])
        and html_lettered == lettered_in_sections
        and source_macrons == data_macrons
    )
    report.add(
        8,
        eight_ok,
        "HTML validity, TEI leakage, NFC, and macrons",
        f"block elements inside <p>={len(block_in_p)}; examples={block_in_p[:5]}\n"
        f"unbalanced tags={len(unbalanced)}; examples={unbalanced[:5]}\n"
        f"records with TEI leakage={len(leaks)}; bad data-ref values={bad_placeholders[:5]}\n"
        f"HTML ref placeholders={html_ref_count}; source refs in sections={meta['counts']['sectionCrossRefs']}\n"
        f"lettered placeholders={html_lettered}; lettered source refs in sections={lettered_in_sections} "
        f"(whole body={meta['counts']['letteredCrossRefs']})\n"
        f"records not in Unicode NFC={len(unnormalized)}\n"
        f"macron counts source={dict(sorted(source_macrons.items()))}\n"
        f"macron counts data  ={dict(sorted(data_macrons.items()))}",
    )

    # 9. Navigation chains, paths, and TOC coverage.
    chain_errors: list[object] = []
    for index, record in enumerate(records):
        expected_prev = records[index - 1]["id"] if index else None
        expected_next = records[index + 1]["id"] if index + 1 < len(records) else None
        if record["prev"] != expected_prev or record["next"] != expected_next:
            chain_errors.append((record["id"], record["prev"], record["next"]))
        path = record["path"]
        if (
            not isinstance(path, list)
            or not path
            or any(not str(item).strip() for item in path)
            or record["head"] != path[-1]
        ):
            chain_errors.append((record["id"], "bad path", path))
    toc = meta.get("toc", [])
    toc_ok = bool(toc)
    covered: set[int] = set()
    for part in toc:
        if not part["chapters"]:
            toc_ok = False
            continue
        for chapter in part["chapters"]:
            covered |= set(range(int(chapter["start"]), int(chapter["end"]) + 1))
            for section in chapter["sections"]:
                if not (
                    int(chapter["start"]) <= int(section["start"]) <= int(section["end"]) <= int(chapter["end"])
                ):
                    toc_ok = False
        if int(part["start"]) != min(int(c["start"]) for c in part["chapters"]) or int(
            part["end"]
        ) != max(int(c["end"]) for c in part["chapters"]):
            toc_ok = False
    uncovered = sorted(set(record_by_n) - covered)
    stray = sorted(covered - set(record_by_n))
    report.add(
        9,
        not chain_errors and toc_ok and not uncovered and not stray,
        "navigation chains, paths, and TOC",
        f"chain/path errors={len(chain_errors)}; examples={chain_errors[:5]}\n"
        f"TOC parts={len(toc)}; chapters={sum(len(p['chapters']) for p in toc)}; bounds valid={toc_ok}\n"
        f"sections absent from every TOC chapter={len(uncovered)}; examples={uncovered[:8]}\n"
        f"TOC numbers with no record={len(stray)}",
    )

    # 10. Determinism.
    determinism_error = ""
    hashes: list[str] = []
    current_hash = combined_hash(args.sections, args.meta)
    try:
        with tempfile.TemporaryDirectory(prefix="verify-ag-") as temp_name:
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
    except Exception as error:  # report the failure instead of hiding other checks
        determinism_error = str(error)
    ten_ok = (
        not determinism_error
        and len(hashes) == 2
        and hashes[0] == hashes[1]
        and hashes[0] == current_hash
    )
    report.add(
        10,
        ten_ok,
        "deterministic conversion",
        f"checked-in hash={current_hash}\nrun hashes={hashes}\nerror={determinism_error or 'none'}",
    )

    # 11. Examples read against the print's own characters.
    #
    # Check 6 is arithmetic over lengths: it counts cit elements, counts
    # examples, and compares the two integers.  Nothing in it looks at a
    # single character of a quotation, a translation, or a citation, so no
    # wrong value can reach it.  A gloss that swallows the next passage and
    # its translation leaves the two counts exactly where they were, and did:
    # Sec. 382 shipped "men brave enough and thoroughly honest. Cf. ero frugi
    # bonae (Plaut. Pseud. 468), I will be good for something." as one
    # translation of one line, and Sec. 395 pulled a footnote and its citation
    # into another.  Check 6 passed both.
    #
    # These three tests read the section's own text, in the record the
    # converter wrote, and know nothing about extract_examples or
    # trailing_gloss:
    #   a. an example's Latin is a run of its section's text, and its
    #      translation is another run standing after it with nothing between
    #      the two but the citation the print sets in brackets.
    #   b. no translation holds a source reference of its own.  A translation
    #      carrying a second passage's citation is a translation of more than
    #      one passage, and whichever it ships under is wrong for the rest.
    #   c. no translation runs past the quotation of the example after it.
    not_in_print: list[object] = []
    not_a_citation: list[object] = []
    holds_reference: list[object] = []
    runs_past: list[object] = []
    for record in records:
        printed = norm(str(record["plain"]))
        pairs = [
            (norm(str(example["la"])), norm(str(example["gloss"])))
            for example in record["examples"]
        ]
        spans: list[tuple[int, int] | None] = []
        cursor = 0
        for latin, gloss in pairs:
            start = printed.find(latin, cursor)
            if start < 0:
                start = printed.find(latin)
            if start < 0:
                not_in_print.append((record["id"], "quotation", latin[:50]))
                spans.append(None)
                continue
            end = start + len(latin)
            if not gloss:
                spans.append((start, end))
                cursor = end
                continue
            gloss_at = printed.find(gloss, end)
            if gloss_at < 0:
                not_in_print.append((record["id"], "translation", gloss[:50]))
                spans.append((start, end))
                cursor = end
                continue
            between = printed[end:gloss_at]
            if not PRINTED_CITATION_RE.match(between):
                not_a_citation.append((record["id"], latin[:30], between[:50]))
            spans.append((start, gloss_at + len(gloss)))
            cursor = gloss_at + len(gloss)
            found = UNTAGGED_REFERENCE_RE.search(gloss)
            if found:
                holds_reference.append(
                    (record["id"], latin[:30], found.group(0), gloss[:60])
                )
        for first, second in zip(spans, spans[1:]):
            if first and second and first[1] > second[0]:
                runs_past.append((record["id"], printed[second[0] : second[0] + 40]))
    eleven_ok = (
        not not_in_print
        and not not_a_citation
        and not holds_reference
        and not runs_past
    )
    report.add(
        11,
        eleven_ok,
        "examples against the print's own text",
        f"examples read={sum(len(r['examples']) for r in records)}; "
        f"of them with a translation={sum(1 for r in records for e in r['examples'] if str(e['gloss']).strip())}\n"
        f"quotations or translations absent from the section's text={len(not_in_print)}; "
        f"examples={not_in_print[:5]}\n"
        f"translations not joined to their quotation by a printed citation="
        f"{len(not_a_citation)}; examples={not_a_citation[:5]}\n"
        f"translations holding a source reference of their own={len(holds_reference)}; "
        f"examples={holds_reference[:5]}\n"
        f"translations running past the next quotation={len(runs_past)}; "
        f"examples={runs_past[:5]}",
    )

    # 12. A vowel the print marks both long and short (sū̆bus) carries the
    #     breve as a mark on the letter, never as a loose ˘ typed after it.
    #     A ˘ standing alone is a metrical sign and stays.
    loose = [
        (record["id"], match.group(0))
        for record in records
        for field in ("html", "plain")
        for match in LOOSE_BREVE.finditer(str(record[field]))
    ]
    report.add(
        12,
        not loose,
        "doubly marked vowels carry the breve on the letter",
        f"loose breves after a long vowel={len(loose)}; examples={loose[:5]}",
    )

    # 13. No mark left under Perseus's placeholder name ([acutemacr]) or
    #     typed as a look-alike (ˆ for the pause sign ∧).
    unmarked = [
        (record["id"], match.group(0))
        for record in records
        for field in ("html", "plain")
        for match in MARK_PLACEHOLDER.finditer(str(record[field]))
    ]
    report.add(
        13,
        not unmarked,
        "metrical and accented signs written as the print shows them",
        f"placeholders left={len(unmarked)}; examples={unmarked[:5]}",
    )

    # Sanity warnings for anomalies that are real but expected.
    anomalies = meta["anomalies"]
    if anomalies["unassignedElements"]:
        report.warn(
            "elements outside every section",
            f"{len(anomalies['unassignedElements'])} element(s) sit in structural "
            f"headings and so belong to no section: {anomalies['unassignedElements']}",
        )
    if anomalies["letterSequenceGaps"]:
        report.warn(
            "letter sequences with gaps",
            f"{anomalies['letterSequenceGaps']}",
        )
    if anomalies["unmarkedLetterLabels"]:
        report.warn(
            "printed letter labels the source did not mark",
            f"{anomalies['unmarkedLetterLabels']}",
        )

    return 0 if report.summary() else 1


if __name__ == "__main__":
    raise SystemExit(main())
