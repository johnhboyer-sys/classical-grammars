#!/usr/bin/env python3
"""Independently verify the Bennett HTML conversion and report its state."""

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
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "grammar-bennett"
DEFAULT_SECTIONS = ROOT / "data" / "bennett" / "sections.jsonl"
DEFAULT_META = ROOT / "data" / "bennett" / "meta.json"
DEFAULT_CONVERTER = ROOT / "scripts" / "convert_bennett.py"
LAST_SECTION = 375
# Counted independently of the converter: the anchors 1-375 plus the printed
# insert 222A between 222 and 223.
EXPECTED_SECTIONS = LAST_SECTION + 1
SECTION_FILES = ("part1.htm", "part2.htm", "part3.htm", "part4.htm", "part5.htm", "part6.htm", "supplement.htm")
ID_RE = re.compile(r"^bennett:(\d+)([A-Z]?)$")
MARKER_SOURCE_RE = re.compile(r'name="sect(\d+[A-Z]?)"')
NOTE_REF_SOURCE_RE = re.compile(r'name="NtA_(\d+)"')
FOOTNOTE_SOURCE_RE = re.compile(r'name="Nt_(\d+)"')
TABLE_SOURCE_RE = re.compile(r"<table\b")
RAW_TAG_RE = re.compile(r"<[^>]+>")
RAW_ENTITY_RE = re.compile(r"&(?:#\d+|#x[0-9A-Fa-f]+|[A-Za-z][A-Za-z0-9]+);")
UNKNOWN_ENTITY_RE = re.compile(r"&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[0-9A-Fa-f]+;)[A-Za-z][A-Za-z0-9]+;")
CHROME = ("Bennett.css", "DOCTYPE", "xmlns", "iso-8859-1", "TABLE OF CONTENTS")
REQUIRED_KEYS = {
    "work", "n", "id", "letters", "notes", "path", "head", "html",
    "plain", "examples", "refs", "refRanges", "citedBy", "prev", "next",
}
NOTE_KEYS = {"anchor", "label", "kind", "html", "plain"}
EXAMPLE_KEYS = {"la", "gloss", "cite"}
# What Bennett prints between a Latin phrase and its translation: a comma, and
# then at most an opening quote or bracket and the word he uses to introduce a
# literal rendering.  Sections 180 and 374 are the six places that carry one.
EXAMPLE_JOIN_RE = re.compile(r",\s*(?:literally,|lit\.)?\s*[('‘“\"]?")
WHITESPACE_RE = re.compile(r"\s+")


def norm(value: str) -> str:
    """Collapse runs of whitespace so a printed line compares as one line."""
    return WHITESPACE_RE.sub(" ", value).strip()
VOID_TAGS = {"br", "hr", "img", "meta", "link", "input"}


class AuditHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.unbalanced: list[str] = []
        self.refs: list[str] = []
        self.notes: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "a" and values.get("data-ref"):
            self.refs.append(values["data-ref"] or "")
        if tag == "sup" and values.get("data-note"):
            self.notes.append(values["data-note"] or "")
        if tag not in VOID_TAGS:
            self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if not self.stack or self.stack[-1] != tag:
            self.unbalanced.append(f"</{tag}>")
        else:
            self.stack.pop()


class Report:
    def __init__(self) -> None:
        self.results: list[bool] = []

    def add(self, number: int, ok: bool, title: str, detail: str) -> None:
        self.results.append(ok)
        print(f"[{'PASS' if ok else 'FAIL'}] {number}. {title}")
        for line in detail.splitlines():
            print(f"  {line}")

    def finish(self) -> int:
        failed = len(self.results) - sum(self.results)
        print("\nVERIFY REPORT SUMMARY")
        print(f"  acceptance checks: {len(self.results) - failed} passed, {failed} failed")
        print(f"  overall: {'PASS' if not failed else 'FAIL'}")
        return 0 if not failed else 1


def records_from(path: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line:
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number}: record is not an object")
            records.append(value)
    return records


def all_strings(value: object, *, skip_html: bool = False):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from all_strings(item, skip_html=skip_html)
    elif isinstance(value, dict):
        for key, item in value.items():
            if skip_html and key == "html":
                continue
            yield from all_strings(item, skip_html=skip_html)


def audit_html(source: str) -> AuditHTML:
    parser = AuditHTML()
    parser.feed(source)
    parser.close()
    return parser


def hash_outputs(sections: Path, meta: Path) -> str:
    digest = hashlib.sha256()
    digest.update(sections.read_bytes())
    digest.update(b"\0")
    digest.update(meta.read_bytes())
    return digest.hexdigest()


def sort_key(label: str) -> tuple[int, str]:
    match = re.fullmatch(r"(\d+)([A-Z]?)", label)
    return (int(match.group(1)), match.group(2)) if match else (0, label)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--sections", type=Path, default=DEFAULT_SECTIONS)
    parser.add_argument("--meta", type=Path, default=DEFAULT_META)
    parser.add_argument("--converter", type=Path, default=DEFAULT_CONVERTER)
    args = parser.parse_args()
    report = Report()
    records = records_from(args.sections)
    meta = json.loads(args.meta.read_text(encoding="utf-8"))
    source_texts = {name: (args.input / name).read_text(encoding="iso-8859-1") for name in SECTION_FILES}

    # 1. Coverage: every source marker becomes exactly one record, in printed
    # order, and the numeric run 1-375 is complete.
    source_markers = [match.group(1) for name in SECTION_FILES for match in MARKER_SOURCE_RE.finditer(source_texts[name])]
    labels = [str(record.get("id", "")).split(":", 1)[-1] for record in records]
    ids = [str(record.get("id", "")) for record in records]
    duplicates = [label for label, count in collections.Counter(labels).items() if count > 1]
    missing = [number for number in range(1, LAST_SECTION + 1) if str(number) not in labels]
    report.add(
        1,
        len(records) == EXPECTED_SECTIONS
        and sorted(source_markers, key=sort_key) == labels
        and labels == sorted(labels, key=sort_key)
        and not duplicates
        and not missing
        and meta.get("counts", {}).get("sections") == len(records),
        "complete section coverage matching the source markers",
        f"records={len(records)}; source markers={len(source_markers)}; expected={EXPECTED_SECTIONS}; "
        f"missing={missing}; duplicates={duplicates}; meta sections={meta.get('counts', {}).get('sections')}",
    )

    # 2. Record shape.
    bad_shape: list[object] = []
    empty: list[object] = []
    for record in records:
        label = str(record.get("id", "")).split(":", 1)[-1]
        n = record.get("n")
        n_matches = (str(n) == label) and (isinstance(n, int) if label.isdigit() else isinstance(n, str))
        note_ok = all(isinstance(note, dict) and set(note) == NOTE_KEYS and str(note.get("plain", "")).strip() for note in record.get("notes", []))
        example_ok = all(isinstance(item, dict) and set(item) == EXAMPLE_KEYS and item.get("la") for item in record.get("examples", []))
        path = record.get("path")
        head_ok = isinstance(path, list) and (not path or record.get("head") == path[-1])
        if (
            set(record) != REQUIRED_KEYS
            or record.get("work") != "bennett"
            or not ID_RE.fullmatch(str(record.get("id", "")))
            or not n_matches
            or record.get("letters") != []
            or not note_ok
            or not example_ok
            or not head_ok
        ):
            bad_shape.append(record.get("id"))
        if not str(record.get("plain", "")).strip():
            empty.append(record.get("id"))
    report.add(2, not bad_shape and not empty, "canonical record shape and nonempty bodies", f"bad shape={bad_shape[:12]}; empty bodies={empty[:12]}")

    # 3. NFC text and no source chrome.
    non_nfc = [
        (record["id"], value[:80])
        for record in records
        for value in all_strings(record)
        if unicodedata.normalize("NFC", value) != value
    ]
    chrome = [(record["id"], phrase) for record in records for phrase in CHROME if phrase in str(record.get("plain", ""))]
    report.add(3, not non_nfc and not chrome, "NFC text and no source chrome in plain bodies", f"non-NFC={non_nfc[:4]}; chrome leaks={chrome[:8]}")

    # 4. HTML integrity: raw markup only in html fields, balanced tags, and
    # data-ref/data-note attributes agreeing with the record's refs and notes.
    raw_fields: list[object] = []
    bad_html: list[object] = []
    ref_mismatch: list[object] = []
    note_mismatch: list[object] = []
    heading_footnotes = meta.get("anomalies", {}).get("headingFootnotes", [])
    for record in records:
        for string in all_strings(record, skip_html=True):
            if RAW_TAG_RE.search(string) or RAW_ENTITY_RE.search(string):
                raw_fields.append((record["id"], string[:80]))
        section_audit = audit_html(str(record.get("html", "")))
        refs_seen = list(section_audit.refs)
        notes_seen = list(section_audit.notes)
        sources = [str(record.get("html", ""))]
        for note in record.get("notes", []):
            note_audit = audit_html(str(note.get("html", "")))
            refs_seen.extend(note_audit.refs)
            sources.append(str(note.get("html", "")))
            if note_audit.stack or note_audit.unbalanced:
                bad_html.append((record["id"], "note", note.get("anchor")))
        if section_audit.stack or section_audit.unbalanced or any(UNKNOWN_ENTITY_RE.search(source) for source in sources):
            bad_html.append((record["id"], section_audit.unbalanced[:2], section_audit.stack[:4]))
        if list(dict.fromkeys(refs_seen)) != record.get("refs", []):
            ref_mismatch.append(record["id"])
        # A footnote whose printed marker sits in a heading has no data-note
        # in the body html; those cases are declared in the meta anomalies.
        label = str(record.get("id", "")).split(":", 1)[-1]
        heading_anchors = {f"fn{item['footnote']}" for item in heading_footnotes if str(item.get("n")) == label}
        anchors = [note.get("anchor") for note in record.get("notes", [])]
        body_anchors = [anchor for anchor in anchors if anchor not in heading_anchors]
        if list(dict.fromkeys(notes_seen)) != body_anchors or len(set(anchors)) != len(anchors):
            note_mismatch.append(record["id"])
    report.add(
        4, not raw_fields and not bad_html and not ref_mismatch and not note_mismatch,
        "well-formed HTML with matching ref and note markers",
        f"raw non-HTML fields={raw_fields[:4]}; malformed HTML={bad_html[:4]}; ref mismatches={ref_mismatch[:8]}; note mismatches={note_mismatch[:8]}",
    )

    # 5. Chain and citation inversion.
    by_id = {str(record["id"]): record for record in records}
    chain_errors: list[object] = []
    inverse: dict[str, list[object]] = {record_id: [] for record_id in by_id}
    for index, record in enumerate(records):
        if record.get("prev") != (records[index - 1]["id"] if index else None) or record.get("next") != (records[index + 1]["id"] if index + 1 < len(records) else None):
            chain_errors.append(record["id"])
        for target in record.get("refs", []):
            if target in inverse:
                inverse[target].append(record["id"])
    inverse_errors = [record_id for record_id, record in by_id.items() if record.get("citedBy") != inverse[record_id]]
    report.add(5, not chain_errors and not inverse_errors, "valid prev/next chain and reference inversion", f"chain errors={chain_errors[:12]}; citedBy errors={inverse_errors[:12]}")

    # 6. Cross-references resolve; ranges are ordered and inside the grammar.
    unresolved = [(record["id"], target) for record in records for target in record.get("refs", []) if target not in by_id]
    bad_ranges = [
        (record["id"], item)
        for record in records
        for item in record.get("refRanges", [])
        if set(item) != {"start", "end"}
        or not (1 <= item["start"] < item["end"] <= LAST_SECTION)
        or f"bennett:{item['start']}" not in record.get("refs", [])
    ]
    report.add(6, not unresolved and not bad_ranges, "cross-references resolve and ranges are sane", f"unresolved={unresolved[:8]}; bad ranges={bad_ranges[:8]}")

    # 7. Tables: the records carry every table the source sets in its sections.
    source_tables = sum(len(TABLE_SOURCE_RE.findall(source_texts[name])) for name in SECTION_FILES)
    record_tables = sum(str(record.get("html", "")).count("<table>") for record in records)
    report.add(
        7, source_tables == record_tables == meta.get("counts", {}).get("tables"),
        "every source table preserved and counted in meta",
        f"source tables={source_tables}; record tables={record_tables}; meta tables={meta.get('counts', {}).get('tables')}",
    )

    # 8. Footnotes: independently recount the source's Nt_/NtA_ anchors and
    # confirm the attached notes plus the recorded front and back matter
    # account for every footnote in footnotes.htm.
    footnote_text = (args.input / "footnotes.htm").read_text(encoding="iso-8859-1")
    source_notes = sorted(int(number) for number in FOOTNOTE_SOURCE_RE.findall(footnote_text))
    section_note_refs = sorted({int(number) for name in SECTION_FILES for number in NOTE_REF_SOURCE_RE.findall(source_texts[name])})
    attached = sorted({int(note["label"]) for record in records for note in record.get("notes", [])})
    outside = meta.get("anomalies", {}).get("footnotesOutsideSections", {})
    accounted = sorted(set(attached) | set(outside.get("frontMatter", [])) | set(outside.get("backMatter", [])))
    report.add(
        8,
        attached == section_note_refs and accounted == source_notes and len(source_notes) == len(set(source_notes)),
        "every source footnote attached or accounted for",
        f"source footnotes={len(source_notes)}; referenced in sections={len(section_note_refs)}; attached={len(attached)}; "
        f"outside sections={sorted(set(outside.get('frontMatter', [])) | set(outside.get('backMatter', [])))}; unaccounted={sorted(set(source_notes) - set(accounted))}",
    )

    # 9. Deterministic double conversion.
    hashes: list[str] = []
    error = ""
    current = hash_outputs(args.sections, args.meta)
    try:
        with tempfile.TemporaryDirectory(prefix="verify-bennett-") as temp_name:
            temp = Path(temp_name)
            for run in (1, 2):
                sections = temp / f"sections-{run}.jsonl"
                meta_path = temp / f"meta-{run}.json"
                result = subprocess.run([sys.executable, str(args.converter), "--input", str(args.input), "--sections", str(sections), "--meta", str(meta_path)], text=True, capture_output=True, check=False)
                if result.returncode:
                    raise RuntimeError(result.stderr.strip() or result.stdout.strip())
                hashes.append(hash_outputs(sections, meta_path))
    except Exception as exc:
        error = str(exc)
    report.add(9, not error and len(hashes) == 2 and hashes[0] == hashes[1] == current, "deterministic double conversion", f"current hash={current}; run hashes={hashes}; error={error or 'none'}")

    # 10. Examples against the print's own text.
    #
    # Nothing before this check looks at what an example says.  Check 2 asks
    # that each one be a dict with three keys and a non-empty "la", and that
    # is the whole of the coverage 1,221 examples had: no count, no comparison
    # with the source, no reading of a single character.  Any wrong pairing
    # ships.  Dropping one clause of extract_examples, the test that the text
    # between the bold Latin and the italic translation begins with a comma,
    # adds 36 examples that are not examples at all (Section 3 pairs the letter
    # "c" with "k", Section 336 pairs "audio te loquentem" with "you"), and
    # all nine checks above report PASS on them.
    #
    # This check knows nothing of blockquotes, <b>, <i>, or paragraph
    # children.  It reads the section's own text and asks that the print set
    # the phrase and its translation together there, in that order, joined the
    # way Bennett joins them.
    unpaired: list[object] = []
    joins: collections.Counter[str] = collections.Counter()
    for record in records:
        printed = norm(str(record["plain"]))
        for example in record["examples"]:
            latin = norm(str(example["la"]))
            gloss = norm(str(example["gloss"]))
            joined = ""
            start = 0
            while True:
                at = printed.find(latin, start)
                if at < 0:
                    break
                after = at + len(latin)
                gloss_at = printed.find(gloss, after)
                if gloss_at < 0:
                    break
                between = printed[after:gloss_at]
                if EXAMPLE_JOIN_RE.fullmatch(between):
                    joined = between
                    break
                start = at + 1
            if joined:
                joins[joined] += 1
            else:
                unpaired.append((record["id"], latin[:40], gloss[:40]))
    report.add(
        10,
        not unpaired,
        "every example is a pair the print itself sets",
        f"examples={sum(len(r['examples']) for r in records)}; "
        f"joins the print uses={joins.most_common(6)}\n"
        f"pairs the section's own text does not set together={len(unpaired)}; "
        f"examples={unpaired[:8]}",
    )

    print("\nSAMPLE FIELD DUMPS")
    for label in ("1", "222A", "375"):
        record = by_id.get(f"bennett:{label}")
        print(f"§{label}:")
        print(json.dumps(record, ensure_ascii=False, indent=2) if record is not None else "MISSING")
    return report.finish()


if __name__ == "__main__":
    raise SystemExit(main())
