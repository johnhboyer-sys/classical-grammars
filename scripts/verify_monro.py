#!/usr/bin/env python3
"""Verify the DCC Monro conversion and print an acceptance report."""

from __future__ import annotations

import argparse
import collections
import hashlib
import html
import json
import re
import subprocess
import sys
import tempfile
import unicodedata
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "grammar-monro" / "src" / "dcc"
DEFAULT_SECTIONS = ROOT / "data" / "monro" / "sections.jsonl"
DEFAULT_META = ROOT / "data" / "monro" / "meta.json"
DEFAULT_CONVERTER = ROOT / "scripts" / "convert_monro.py"
LAST_SECTION = 405
REQUIRED_KEYS = {
    "work", "n", "id", "letters", "notes", "path", "head", "html",
    "plain", "examples", "refs", "refRanges", "citedBy", "prev", "next",
}
ID_RE = re.compile(r"^monro:(\d+)$")
RAW_TAG_RE = re.compile(r"<[^>]+>")
RAW_ENTITY_RE = re.compile(r"&(?:#\d+|#x[0-9A-Fa-f]+|[A-Za-z][A-Za-z0-9]+);")
UNKNOWN_ENTITY_RE = re.compile(
    r"&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[0-9A-Fa-f]+;)[A-Za-z][A-Za-z0-9]+;"
)
MARKER_RE = re.compile(
    r'<p\b[^>]*>\s*(?:<a\b[^>]*>\s*</a>\s*)*'
    r'<(?P<tag>strong|b)\b[^>]*>(?P<label>.*?)</(?P=tag)>',
    re.I | re.S,
)
MARKER_LABEL_RE = re.compile(r"^(\d{1,3})(?:\.(\d+))?\.?\s*(\*)?\.?$")
GREEK_RE = re.compile(r"[\u0370-\u03ff\u1f00-\u1fff]")
ASCII_RE = re.compile(r"[A-Za-z]")
SCRIPT_WORD_RE = re.compile(
    r"[A-Za-z\u00c0-\u024f\u1e00-\u1eff\u0370-\u03ff\u1f00-\u1fff\u0300-\u036f]+"
)
CENSUS_TOKEN_RE = re.compile(
    r"[A-Za-z\u00c0-\u024f\u1e00-\u1eff\u0370-\u03ff\u1f00-\u1fff\u0300-\u036f]+"
    r"(?:[-‐‑–—][A-Za-z\u00c0-\u024f\u1e00-\u1eff\u0370-\u03ff\u1f00-\u1fff\u0300-\u036f]+)*"
)
LATIN_QUANTITY_VOWELS = frozenset("āēīōūăĕĭŏŭĀĒĪŌŪĂĔĬŎŬ")
CHROME_STRINGS = (
    "Skip to main content", "Dickinson College", "Creative Commons",
    "Toggle navigation menu", "Suggested Citation", "Core Vocabulary",
)
ALLOWED_TAGS = {
    "section", "p", "ol", "ul", "li", "table", "thead", "tbody", "tr",
    "td", "th", "blockquote", "h2", "h3", "h4", "em", "strong", "sup",
    "sub", "span", "q", "a", "br",
}
BLOCK_TAGS = {
    "section", "p", "ol", "ul", "li", "table", "thead", "tbody", "tr",
    "td", "th", "blockquote", "h2", "h3", "h4",
}
VOID_TAGS = {"br"}


def norm(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def is_latin_letter(char: str) -> bool:
    return char.isalpha() and unicodedata.name(char, "").startswith("LATIN ")


def is_greek_letter(char: str) -> bool:
    return char.isalpha() and unicodedata.name(char, "").startswith("GREEK ")


def all_strings(value: object):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from all_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from all_strings(item)


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


def source_marker_census(source_dir: Path) -> tuple[list[int], list[tuple[int, str]], list[str]]:
    primary: list[int] = []
    stars: list[tuple[int, str]] = []
    unnumbered: list[str] = []
    for path in sorted(source_dir.glob("*.html"), key=lambda item: item.name):
        source = path.read_text(encoding="utf-8")
        start = source.find("<article ")
        end = source.find("</article>", start)
        article = source[start:end] if start >= 0 and end >= 0 else ""
        candidates: list[tuple[int, bool]] = []
        for match in MARKER_RE.finditer(article):
            label = norm(html.unescape(RAW_TAG_RE.sub("", match.group("label"))).replace("\u00a0", " "))
            parsed = MARKER_LABEL_RE.fullmatch(label)
            if parsed:
                candidates.append((int(parsed.group(1)), bool(parsed.group(3))))
        current: int | None = None
        accepted: list[tuple[int, bool]] = []
        for number, starred in candidates:
            if current is None or (not starred and number > current):
                accepted.append((number, starred))
                current = number
        if not accepted:
            unnumbered.append(path.stem)
        for number, starred in accepted:
            if starred:
                stars.append((number, path.stem))
            else:
                primary.append(number)
    return primary, stars, unnumbered


class PrintedBlocks(HTMLParser):
    """Split a section's HTML into the blocks the reader sees.

    For each block it keeps the whole of its text and, separately, the text
    of each italic run in it, in order.  That is all this check needs: the
    DCC sets a Homeric example as one paragraph holding the reference, then
    the verse, then the translation in italics.

    It knows nothing of how the converter finds an example.  It reads the
    rendered section, which ``convert_monro.py`` builds from the DCC's own
    markup without consulting its example rule.
    """

    BREAKS = {
        "p", "li", "blockquote", "td", "th", "tr", "section", "ol", "ul",
        "table", "h2", "h3", "h4", "thead", "tbody",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[tuple[str, list[str]]] = []
        self.text: list[str] = []
        self.italics: list[str] = []
        self.depth = 0

    def flush(self) -> None:
        if self.text:
            self.blocks.append(("".join(self.text), list(self.italics)))
        self.text = []
        self.italics = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.BREAKS:
            self.flush()
        if tag == "em":
            self.depth += 1
            self.italics.append("")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.BREAKS:
            self.flush()
        if tag == "em" and self.depth:
            self.depth -= 1

    def handle_data(self, data: str) -> None:
        self.text.append(data)
        if self.depth and self.italics:
            self.italics[-1] += data


def squeeze(value: str) -> str:
    """Drop every space, so that the print's "Il. 20. 306" and the field's
    "Il. 20.306" are the same string."""
    return re.sub(r"\s+", "", value or "")


def printed_blocks(markup: str) -> list[tuple[str, list[str]]]:
    parser = PrintedBlocks()
    parser.feed(markup)
    parser.close()
    parser.flush()
    return [(squeeze(text), [squeeze(run) for run in runs])
            for text, runs in parser.blocks]


class HtmlAudit(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.errors: list[str] = []
        self.ids: list[str] = []
        self.refs: list[str] = []
        self.text: list[str] = []
        self.tags: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        self.tags.append(tag)
        if tag not in ALLOWED_TAGS:
            self.errors.append(f"unknown tag <{tag}>")
        if tag in BLOCK_TAGS and "p" in self.stack:
            self.errors.append(f"{tag} inside p")
        allowed_attrs = {"id"} if tag == "section" else ({"data-ref"} if tag == "a" else set())
        extra = sorted(set(values) - allowed_attrs)
        if extra:
            self.errors.append(f"{tag} attrs {extra}")
        if values.get("id"):
            self.ids.append(values["id"] or "")
        if tag == "a":
            target = values.get("data-ref") or ""
            self.refs.append(target)
            if not ID_RE.fullmatch(target):
                self.errors.append(f"bad data-ref {target!r}")
        if tag not in VOID_TAGS:
            self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag not in self.stack:
            self.errors.append(f"stray </{tag}>")
            return
        if self.stack[-1] != tag:
            self.errors.append(f"</{tag}> closes {self.stack[-1]}")
        index = len(self.stack) - 1 - self.stack[::-1].index(tag)
        self.stack = self.stack[:index]

    def handle_data(self, data: str) -> None:
        self.text.append(data)


class Report:
    def __init__(self) -> None:
        self.results: list[bool] = []

    def add(self, number: int, ok: bool, title: str, detail: str) -> None:
        self.results.append(ok)
        print(f"[{'PASS' if ok else 'FAIL'}] {number}. {title}")
        for line in detail.splitlines():
            print(f"  {line}")

    def summary(self) -> bool:
        passed = sum(self.results)
        failed = len(self.results) - passed
        print("\nVERIFY REPORT SUMMARY")
        print(f"  acceptance checks: {passed} passed, {failed} failed")
        print(f"  overall: {'PASS' if failed == 0 else 'FAIL'}")
        return failed == 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--sections", type=Path, default=DEFAULT_SECTIONS)
    parser.add_argument("--meta", type=Path, default=DEFAULT_META)
    parser.add_argument("--converter", type=Path, default=DEFAULT_CONVERTER)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    report = Report()
    records = load_records(args.sections)
    meta = json.loads(args.meta.read_text(encoding="utf-8"))
    by_n = {int(record["n"]): record for record in records}
    by_id = {str(record["id"]): record for record in records}
    expected = list(range(1, LAST_SECTION + 1))

    primary, stars, unnumbered = source_marker_census(args.input)
    counts = collections.Counter(primary)
    missing = [number for number in expected if not counts[number]]
    duplicates = {number: count for number, count in counts.items() if count > 1}
    expected_stars = [
        (246, "verbal-adjectives"),
        (324, "ellipse-apodosis"),
        (378, "contraction-homer"),
    ]
    one_ok = (
        len(list(args.input.glob("*.html"))) == 205
        and sorted(primary) == expected
        and len(primary) == LAST_SECTION
        and missing == []
        and duplicates == {}
        and sorted(stars) == expected_stars
        and sorted(unnumbered) == ["editors-note", "paradigm-charts", "preface"]
        and [int(record["n"]) for record in records] == expected
    )
    report.add(
        1, one_ok, "source pages, section markers, and numbering",
        f"pages={len(list(args.input.glob('*.html')))}; primary markers={len(primary)}; records={len(records)}\n"
        f"missing={missing}; duplicates={duplicates}; continuations={sorted(stars)}\n"
        f"unnumbered pages={sorted(unnumbered)}",
    )

    bad_shape: list[object] = []
    for record in records:
        number = record.get("n")
        record_id = str(record.get("id", ""))
        if (
            set(record) != REQUIRED_KEYS
            or record.get("work") != "monro"
            or not ID_RE.fullmatch(record_id)
            or record_id != f"monro:{number}"
            or record.get("letters") != []
            or not str(record.get("plain", "")).strip()
            or not str(record.get("html", "")).strip()
            or not isinstance(record.get("path"), list)
            or record.get("head") != record.get("path", [None])[-1]
        ):
            bad_shape.append({"n": number, "keys": sorted(record), "id": record_id})
    report.add(
        2, not bad_shape, "canonical record shape and nonempty bodies",
        f"required keys={sorted(REQUIRED_KEYS)}\nbad records={len(bad_shape)}; samples={bad_shape[:4]}",
    )

    source_rows = meta.get("sectionSources", [])
    source_errors: list[object] = []
    if not isinstance(source_rows, list) or len(source_rows) != LAST_SECTION:
        source_errors.append(f"sectionSources length={len(source_rows) if isinstance(source_rows, list) else 'not-list'}")
    else:
        for number, row in enumerate(source_rows, 1):
            slug = str(row.get("slug", ""))
            if row.get("n") != number or not (args.input / f"{slug}.html").is_file():
                source_errors.append((number, row))
    continuation_meta = meta.get("extraction", {}).get("crossPageContinuations", [])
    license_ok = (
        meta.get("license") == "CC BY-SA 4.0"
        and meta.get("attribution") == "Text: Dickinson College Commentaries edition (CC BY-SA 4.0)"
    )
    report.add(
        3, not source_errors and license_ok and len(continuation_meta) == 3,
        "source slugs, attribution, and continuation inventory",
        f"source rows={len(source_rows) if isinstance(source_rows, list) else 'invalid'}; errors={source_errors[:4]}\n"
        f"license/attribution exact={license_ok}; continuation rows={continuation_meta}",
    )

    unresolved: list[object] = []
    inverse: dict[str, list[str]] = {record_id: [] for record_id in by_id}
    bad_ranges: list[object] = []
    for record in records:
        seen: set[str] = set()
        for target in record["refs"]:
            if target in seen or target not in by_id:
                unresolved.append((record["n"], target))
            seen.add(target)
            if target in inverse:
                inverse[target].append(record["id"])
        for item in record["refRanges"]:
            if set(item) != {"start", "end"} or not (1 <= item["start"] <= item["end"] <= LAST_SECTION):
                bad_ranges.append((record["n"], item))
    inverse_errors = [record_id for record_id, record in by_id.items() if record["citedBy"] != inverse[record_id]]
    report.add(
        4, not unresolved and not inverse_errors and not bad_ranges,
        "cross-references, ranges, and citedBy",
        f"unique edges={sum(len(record['refs']) for record in records)}; ranges={sum(len(record['refRanges']) for record in records)}\n"
        f"unresolved/duplicate={unresolved[:6]}; inverse errors={inverse_errors[:6]}; bad ranges={bad_ranges[:6]}",
    )

    not_nfc: list[object] = []
    replacements: list[object] = []
    greek_quantity: list[object] = []
    mixed: list[object] = []
    retained_quantity: collections.Counter[str] = collections.Counter()
    greek_chars = 0
    for record in records:
        for value in all_strings(record):
            if value != unicodedata.normalize("NFC", value):
                not_nfc.append((record["n"], value[:80]))
            if "\ufffd" in value or any(0xD800 <= ord(char) <= 0xDFFF for char in value):
                replacements.append((record["n"], value[:80]))
        plain = str(record["plain"])
        greek_chars += len(GREEK_RE.findall(plain))
        for match in SCRIPT_WORD_RE.finditer(plain):
            token = match.group()
            has_greek = any(is_greek_letter(char) for char in token)
            has_latin = any(is_latin_letter(char) for char in token)
            if has_greek and any(char in LATIN_QUANTITY_VOWELS for char in token):
                greek_quantity.append((record["n"], token))
            if has_greek and has_latin:
                mixed.append((record["n"], token))
        for match in CENSUS_TOKEN_RE.finditer(plain):
            token = match.group()
            if (
                any(char in LATIN_QUANTITY_VOWELS for char in token)
                and any(is_latin_letter(char) for char in token)
                and not any(is_greek_letter(char) for char in token)
            ):
                retained_quantity[token] += 1
    decisions = (
        meta.get("extraction", {})
        .get("sourceTextNormalization", {})
        .get("latinQuantityContextDecisions", {})
    )
    decision_ok = (
        isinstance(decisions, dict)
        and isinstance(decisions.get("greekContextTokens"), int)
        and isinstance(decisions.get("latinContextTokens"), int)
        and decisions.get("greekContextTokens", 0) > 0
        and decisions.get("latinContextTokens", 0) > 0
    )
    required_retained = {
        "amāmus": retained_quantity["amāmus"],
        "docēmus": retained_quantity["docēmus"],
        "nāv-em": retained_quantity["nāv-em"],
    }
    census = " ".join(
        f"{token}×{count}" for token, count in sorted(
            retained_quantity.items(), key=lambda item: (item[0].casefold(), item[0])
        )
    )
    report.add(
        5,
        not not_nfc
        and not replacements
        and not greek_quantity
        and not mixed
        and greek_chars > 10000
        and decision_ok
        and all(required_retained.values()),
        "NFC and Latin/Greek quantity policy",
        f"Greek chars={greek_chars}; non-NFC={len(not_nfc)}; replacement chars={len(replacements)}\n"
        f"Greek runs with Latin quantity={greek_quantity[:8]}; mixed Latin/Greek runs={mixed[:8]}\n"
        f"bare-quantity context decisions={decisions}; required retained={required_retained}\n"
        f"retained Latin quantity tokens={len(retained_quantity)}; occurrences={sum(retained_quantity.values())}\n"
        f"retained-token census: {census}",
    )

    plain_tags: list[object] = []
    plain_entities: list[object] = []
    chrome: list[object] = []
    for record in records:
        plain = str(record["plain"])
        if RAW_TAG_RE.search(plain):
            plain_tags.append((record["n"], RAW_TAG_RE.findall(plain)[:3]))
        if RAW_ENTITY_RE.search(plain):
            plain_entities.append((record["n"], RAW_ENTITY_RE.findall(plain)[:3]))
        for phrase in CHROME_STRINGS:
            if phrase.lower() in plain.lower():
                chrome.append((record["n"], phrase))
    report.add(
        6, not plain_tags and not plain_entities and not chrome,
        "plain text has no raw markup, entities, or DCC chrome",
        f"raw tags={plain_tags[:5]}; raw entities={plain_entities[:5]}; chrome={chrome[:5]}",
    )

    html_errors: list[object] = []
    duplicate_ids: list[str] = []
    unknown_entities: list[object] = []
    html_refs: list[str] = []
    all_ids: list[str] = []
    for record in records:
        value = str(record["html"])
        audit = HtmlAudit()
        audit.feed(value)
        audit.close()
        if audit.stack:
            audit.errors.append(f"unclosed={audit.stack}")
        if audit.errors:
            html_errors.append((record["n"], audit.errors[:6]))
        if audit.ids != [f"s{record['n']}"]:
            html_errors.append((record["n"], f"ids={audit.ids}"))
        if any(phrase.lower() in norm("".join(audit.text)).lower() for phrase in CHROME_STRINGS):
            html_errors.append((record["n"], "chrome text"))
        found_unknown = UNKNOWN_ENTITY_RE.findall(value)
        if found_unknown:
            unknown_entities.append((record["n"], found_unknown[:4]))
        all_ids.extend(audit.ids)
        html_refs.extend(audit.refs)
    duplicate_ids = [value for value, count in collections.Counter(all_ids).items() if count > 1]
    report.add(
        7, not html_errors and not duplicate_ids and not unknown_entities,
        "safe, balanced canonical HTML",
        f"HTML errors={html_errors[:8]}; duplicate ids={duplicate_ids[:5]}; unknown entities={unknown_entities[:5]}\n"
        f"HTML link uses={len(html_refs)}",
    )

    chain_errors: list[object] = []
    for index, record in enumerate(records):
        expected_prev = records[index - 1]["id"] if index else None
        expected_next = records[index + 1]["id"] if index + 1 < len(records) else None
        if record["prev"] != expected_prev or record["next"] != expected_next:
            chain_errors.append((record["n"], record["prev"], record["next"]))
    report.add(
        8, not chain_errors and records[0]["prev"] is None and records[-1]["next"] is None,
        "navigation chain",
        f"links checked={len(records) * 2}; errors={chain_errors[:8]}",
    )

    bad_examples: list[object] = []
    example_count = 0
    for record in records:
        for example in record["examples"]:
            example_count += 1
            grc = str(example.get("grc", ""))
            if (
                set(example) != {"grc", "gloss", "cite"}
                or not re.fullmatch(r"(?:Il|Od)\.\s*\d+\.\d+(?:[-–—]\d+)?", str(example.get("cite", "")))
                or not GREEK_RE.search(grc)
                or ASCII_RE.search(grc)
                # A verse never opens on a number.  When one does, the DCC has
                # split the line number and the citation stops inside it
                # ("Od. 11. 4 19 ὡς ἀμφὶ κρητῆρα" is Od. 11.419), so the
                # citation shipped with it is not the verse's.
                or grc[:1].isdigit()
                # Nor does a verse open a bracket it never closes: that is an
                # editor's note the extraction cut in half.
                or grc.count("(") != grc.count(")")
                or grc.count("[") != grc.count("]")
            ):
                bad_examples.append((record["n"], example))
    report.add(
        9, example_count > 1000 and not bad_examples,
        "cheap Homeric example extraction",
        f"examples={example_count}; pattern=indented Il./Od. book.line paragraph; bad={bad_examples[:5]}",
    )

    # 10. Every example is a paragraph the print itself sets.
    #
    # Check 9 reads the citation's shape, and it reads the Greek for stray
    # ASCII, a leading digit and unbalanced brackets.  It never reads the
    # translation at all, and it never asks whether the three fields belong
    # to each other.  Give an example its neighbour's translation, or its
    # neighbour's reference, and check 9 still passes: both strings are
    # perfectly well formed, they are simply not this verse's.
    #
    # This check reads the rendered section.  The DCC sets a Homeric example
    # as one paragraph: the reference, then the verse, then the translation
    # in italics, the last of these sometimes broken into several italic runs
    # around a parenthesis of the editor's ("accepted the cup from Themis"
    # (as a compliment) "to take as an attendant does", §143).  So the check
    # asks that one printed block hold the citation before the Greek, and
    # that the gloss be a run of that block's own italics.
    #
    # Verified to fail on a mispairing: swapping the two glosses of §78 in a
    # copy of sections.jsonl, so that "Il. 20.306 ἤδη . . . ἤχθηρε" carries
    # "come to hate you as I now love you have got to love" and "Il. 3.415"
    # carries "has now come to hate", leaves checks 1 to 9 reporting PASS and
    # fails here on both.  (Check 11 also fails on that file, because a
    # doctored file is by definition not what the converter produces; that is
    # its job, and it is not what proves this one.)
    unseated: list[object] = []
    example_total = 0
    for record in records:
        blocks = printed_blocks(str(record["html"]))
        for example in record["examples"]:
            example_total += 1
            grc = squeeze(str(example.get("grc", "")))
            gloss = squeeze(str(example.get("gloss", "")))
            cite = squeeze(str(example.get("cite", "")))
            found = False
            for text, italics in blocks:
                if cite not in text or grc not in text:
                    continue
                if text.index(cite) > text.index(grc):
                    continue
                if gloss and not any(
                    "".join(italics[first:last]) == gloss
                    for first in range(len(italics))
                    for last in range(first + 1, len(italics) + 1)
                ):
                    continue
                found = True
                break
            if not found:
                unseated.append((record["n"], example.get("cite"),
                                 str(example.get("grc", ""))[:40]))
    report.add(
        10, not unseated,
        "every example is a paragraph the print itself sets",
        f"examples={example_total}; seated in the section's own printed "
        f"blocks={example_total - len(unseated)}\n"
        f"examples the print does not set as one block={len(unseated)}; "
        f"first={unseated[:6]}",
    )

    hashes: list[str] = []
    error = ""
    current_hash = combined_hash(args.sections, args.meta)
    try:
        with tempfile.TemporaryDirectory(prefix="verify-monro-") as temp_name:
            temp = Path(temp_name)
            for run in (1, 2):
                out_sections = temp / f"sections-{run}.jsonl"
                out_meta = temp / f"meta-{run}.json"
                completed = subprocess.run(
                    [
                        sys.executable, str(args.converter), "--input", str(args.input),
                        "--sections", str(out_sections), "--meta", str(out_meta),
                    ],
                    check=False, capture_output=True, text=True,
                )
                if completed.returncode:
                    raise RuntimeError(f"run {run}: {completed.stderr.strip()}")
                hashes.append(combined_hash(out_sections, out_meta))
    except Exception as caught:
        error = str(caught)
    report.add(
        11, not error and len(hashes) == 2 and hashes[0] == hashes[1] == current_hash,
        "deterministic double-run hash",
        f"current={current_hash}\nruns={hashes}\nerror={error or 'none'}",
    )

    sample_lines: list[str] = []
    samples_ok = True
    for number in (1, 200, 405):
        record = by_n.get(number)
        if record is None or not str(record["plain"]).strip():
            samples_ok = False
            sample_lines.append(f"§{number}: MISSING")
            continue
        value = str(record["plain"])
        excerpt = value if len(value) <= 360 else value[:357] + "..."
        sample_lines.append(f"§{number} [{record['head']}] chars={len(value)}\n    {excerpt}")
    report.add(12, samples_ok, "sample sections 1, 200, and 405", "\n".join(sample_lines))

    return 0 if report.summary() else 1


if __name__ == "__main__":
    raise SystemExit(main())
