#!/usr/bin/env python3
"""Independently verify data/smyth/citations.json and print a full report."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from html import unescape as html_unescape
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SECTIONS = ROOT / "data" / "smyth" / "sections.jsonl"
DEFAULT_CITATIONS = ROOT / "data" / "smyth" / "citations.json"
DEFAULT_BUILDER = ROOT / "scripts" / "build_citations_index.py"
CITE_TAG_RE = re.compile(r'<cite\b[^>]*\bdata-cite="([^"]*)"')

# Spot-fixtures: passage key -> at least one Smyth section that must cite it,
# per the SPEC's worked examples.
FIXTURES = {
    "plat.apol.17b": 1270,
    "hom.il.21.567": 44,
    "xen.anab.1.2.2": 188,
}


LETTER_ID_RE = re.compile(r"^[a-z]\d?$")


class CiteScanner(HTMLParser):
    """Re-extract (cite text, anchor) pairs with a real HTML parser.

    The builder scans the html field with a regex. This walks the same markup
    through the stdlib tokenizer instead, so check 6 catches both a broken
    scan and an index entry the builder dropped after scanning it.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.cites: list[tuple[str, str | None]] = []
        self.anchor: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        id_value = values.get("id")
        if id_value and tag in ("strong", "p", "span") and LETTER_ID_RE.match(id_value):
            self.anchor = id_value
        if tag == "cite" and "data-cite" in values:
            self.cites.append((values["data-cite"] or "", self.anchor))


class Report:
    def __init__(self) -> None:
        self.results: list[str] = []

    def add(self, number: int, ok: bool, title: str, detail: str) -> None:
        status = "PASS" if ok else "FAIL"
        self.results.append(status)
        print(f"[{status}] {number}. {title}")
        for line in detail.splitlines():
            print(f"  {line}")

    def summary(self) -> bool:
        passed = self.results.count("PASS")
        failed = self.results.count("FAIL")
        print("\nVERIFY REPORT SUMMARY")
        print(f"  acceptance checks: {passed} passed, {failed} failed")
        print(f"  overall: {'PASS' if failed == 0 else 'FAIL'}")
        return failed == 0


def load_records(path: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                records.append(json.loads(line))
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sections", type=Path, default=DEFAULT_SECTIONS)
    parser.add_argument("--citations", type=Path, default=DEFAULT_CITATIONS)
    parser.add_argument("--builder", type=Path, default=DEFAULT_BUILDER)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    report = Report()
    records = load_records(args.sections)
    section_numbers = {int(r["n"]) for r in records}
    data = json.loads(args.citations.read_text(encoding="utf-8"))
    meta = data["_meta"]
    passage_keys = {k: v for k, v in data.items() if k != "_meta"}

    # 1. Total citation count reconciles with the TEI source (<cite> tags in
    # every section's html field, independent of the builder's own count).
    source_total = sum(
        len(CITE_TAG_RE.findall(str(r["html"]))) for r in records
    )
    parsed_instances = sum(len(v) for v in passage_keys.values())
    # parsed_instances can be less than meta["parsed"] because identical
    # (section, anchor) pairs for the same key are collapsed; every parsed
    # citation instance must still be accounted for by meta["parsed"].
    one_ok = (
        source_total == 5193
        and source_total == meta["sourceCitations"]
        and meta["parsed"] + meta["unparsed"] == source_total
        and len(meta["unparsedCitations"]) == meta["unparsed"]
        and parsed_instances <= meta["parsed"]
    )
    report.add(
        1,
        one_ok,
        "citation count reconciles with source",
        f"<cite> tags in sections.jsonl html={source_total} (expected 5193)\n"
        f"meta.sourceCitations={meta['sourceCitations']}; "
        f"meta.parsed={meta['parsed']} + meta.unparsed={meta['unparsed']} "
        f"= {meta['parsed'] + meta['unparsed']}\n"
        f"unparsedCitations list length={len(meta['unparsedCitations'])}\n"
        f"deduplicated (section, anchor) entries actually stored={parsed_instances}",
    )

    # 2. Every section referenced by the index exists in sections.jsonl.
    bad_refs: list[object] = []
    for key, entries in passage_keys.items():
        for entry in entries:
            if entry["section"] not in section_numbers:
                bad_refs.append((key, entry))
    report.add(
        2,
        not bad_refs,
        "every referenced section exists",
        f"dangling section references={len(bad_refs)}; examples={bad_refs[:5]}",
    )

    # 3. Spot-fixtures resolve to known sections.
    fixture_errors: list[str] = []
    for key, expected_section in FIXTURES.items():
        entries = passage_keys.get(key)
        if not entries:
            fixture_errors.append(f"{key}: missing from index")
            continue
        sections = {e["section"] for e in entries}
        if expected_section not in sections:
            fixture_errors.append(
                f"{key}: expected section {expected_section} in {sorted(sections)}"
            )
    report.add(
        3,
        not fixture_errors,
        "spot-fixtures resolve",
        f"fixtures checked={list(FIXTURES)}\nerrors={fixture_errors or 'none'}",
    )

    # 4. Determinism: running the builder twice gives byte-identical output.
    determinism_error = ""
    outputs: list[bytes] = []
    try:
        with tempfile.TemporaryDirectory(prefix="verify-citations-") as tmp_name:
            tmp = Path(tmp_name)
            for run in (1, 2):
                out_path = tmp / f"citations-{run}.json"
                completed = subprocess.run(
                    [
                        sys.executable,
                        str(args.builder),
                        "--sections",
                        str(args.sections),
                        "--output",
                        str(out_path),
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                if completed.returncode != 0:
                    raise RuntimeError(f"builder run {run} failed: {completed.stderr.strip()}")
                outputs.append(out_path.read_bytes())
    except Exception as error:  # report the failure instead of hiding the other checks
        determinism_error = str(error)
    four_ok = (
        not determinism_error
        and len(outputs) == 2
        and outputs[0] == outputs[1]
        and outputs[0] == args.citations.read_bytes()
    )
    report.add(
        4,
        four_ok,
        "deterministic build (two runs byte-identical, matches checked-in file)",
        f"error={determinism_error or 'none'}",
    )

    # 5. No key collisions between different works: the author/work
    # normalization table used by the builder must be injective -- no two
    # distinct (author_full, work_full) identities may share an
    # (author_slug, work_slug) pair.
    sys.path.insert(0, str(args.builder.parent))
    import build_citations_index as builder  # noqa: E402

    by_slugs: dict[tuple[str, str | None], tuple[str, str | None]] = {}
    slug_collisions: list[object] = []
    for prefix, (author_full, author_slug, work_full, work_slug) in (
        builder.AUTHOR_WORK_TABLE.items()
    ):
        slug_key = (author_slug, work_slug)
        identity = (author_full, work_full)
        if slug_key in by_slugs and by_slugs[slug_key] != identity:
            slug_collisions.append((prefix, slug_key, by_slugs[slug_key], identity))
        by_slugs[slug_key] = identity
    report.add(
        5,
        not slug_collisions,
        "no key collisions between different works",
        f"distinct (author_slug, work_slug) pairs={len(by_slugs)}; "
        f"collisions={slug_collisions or 'none'}",
    )

    # 6. Every source <cite> is accounted for. Check 1 only reconciles
    # totals, so it cannot see an entry the builder scanned, classified, and
    # then failed to store. Re-extract every citation with the stdlib HTML
    # parser (not the builder's regex) and require each one to land either as
    # a stored (key, section, anchor) triple or in unparsedCitations.
    stored: dict[str, set[tuple[int, str | None]]] = {
        key: {(e["section"], e.get("anchor")) for e in entries}
        for key, entries in passage_keys.items()
    }
    listed_unparsed = {
        (u["text"], u["section"]) for u in meta["unparsedCitations"]
    }
    dropped: list[object] = []
    unlisted: list[object] = []
    scanned = 0
    for record in records:
        section = int(record["n"])
        scanner = CiteScanner()
        scanner.feed(str(record["html"]))
        scanner.close()
        for raw_cite, anchor in scanner.cites:
            scanned += 1
            classified = builder.classify(raw_cite)
            table_entry = (
                builder.AUTHOR_WORK_TABLE.get(classified[0]) if classified else None
            )
            if table_entry is None:
                if (raw_cite, section) not in listed_unparsed:
                    unlisted.append((raw_cite, section))
                continue
            key = builder.build_key(table_entry, classified[1])
            if (section, anchor) not in stored.get(key, ()):
                dropped.append((raw_cite, section, anchor, key))
    six_ok = scanned == source_total and not dropped and not unlisted
    report.add(
        6,
        six_ok,
        "every source citation is stored or listed as unparsed",
        f"citations re-extracted with html.parser={scanned} "
        f"(regex scan found {source_total})\n"
        f"stored-index misses={len(dropped)}; examples={dropped[:5]}\n"
        f"unparsed but absent from _meta.unparsedCitations={len(unlisted)}; "
        f"examples={unlisted[:5]}",
    )

    # 7. Every key is the reference its own citation string writes.
    #
    # Check 6 re-extracts the citations with html.parser rather than the
    # builder's regex, and then hands each one to builder.classify and
    # builder.build_key -- the very functions that made the index. It can
    # see a citation the builder scanned and then dropped; it cannot see a
    # citation the builder read wrongly, because it reads it the same way.
    # Check 1 compares totals, check 2 asks that a section exist, check 3
    # tests three fixtures, check 4 rebuilds, check 5 tests the table for
    # injectivity. So a locator that lost a component, or a citation filed
    # under the neighbouring author, would ship.
    #
    # This check does not call classify. For every stored (key, section), the
    # section must print a <cite> that opens with a prefix the table maps to
    # that key's author and work, and whose closing numbers are the key's
    # locator, reading roman numerals as numbers and leaving a Stephanus
    # letter attached to the number before it.
    roman_values = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500,
                    "m": 1000}
    number_token = re.compile(
        r"(?<![A-Za-z0-9])[ivxlcdmIVXLCDM]+(?![A-Za-z0-9])|[0-9]+")
    locator_part = re.compile(r"[0-9]+[a-z]?")

    def numbers_written(text: str) -> list[str]:
        written: list[str] = []
        for match in number_token.finditer(text):
            token = match.group()
            if token.isdigit():
                written.append(token.lstrip("0") or "0")
                continue
            total = previous = 0
            for char in reversed(token.lower()):
                value = roman_values[char]
                total += -value if value < previous else value
                previous = max(previous, value)
            written.append(str(total))
        return written

    prefixes_by_slug: dict[str, list[str]] = {}
    for prefix, row in builder.AUTHOR_WORK_TABLE.items():
        _author_full, author_slug, _work_full, work_slug = row
        slug = (author_slug if work_slug is None
                else f"{author_slug}.{work_slug}")
        prefixes_by_slug.setdefault(slug, []).append(prefix.lower())
    printed_by_section: dict[int, list[tuple[str, list[str]]]] = {}
    for record in records:
        printed_by_section[int(record["n"])] = [
            (" ".join(html_unescape(raw).split()).lower(), numbers_written(raw))
            for raw in CITE_TAG_RE.findall(str(record["html"]))
        ]
    key_wrong: list[object] = []
    keys_read = 0
    for key, entries in passage_keys.items():
        parts = key.split(".")
        cut = len(parts)
        while cut and locator_part.fullmatch(parts[cut - 1]):
            cut -= 1
        slug = ".".join(parts[:cut])
        wanted = [re.match(r"[0-9]+", part).group() for part in parts[cut:]]
        allowed = prefixes_by_slug.get(slug, [])
        for entry in entries:
            keys_read += 1
            if not any(
                any(text.startswith(item) for item in allowed)
                and wanted
                and written[len(written) - len(wanted):] == wanted
                for text, written in printed_by_section.get(entry["section"], [])
            ):
                key_wrong.append((key, entry))
    report.add(
        7,
        not key_wrong,
        "every key is the reference its own citation string writes",
        f"stored (key, section) entries={keys_read}\n"
        f"entries no citation printed in their section explains="
        f"{len(key_wrong)}; examples={key_wrong[:5]}",
    )

    return 0 if report.summary() else 1


if __name__ == "__main__":
    raise SystemExit(main())
