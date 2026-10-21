#!/usr/bin/env python3
"""Independently verify the Goodell DCC HTML conversion and report its state."""

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
DEFAULT_INPUT = ROOT / "grammar-goodell" / "src" / "dcc"
DEFAULT_SECTIONS = ROOT / "data" / "goodell" / "sections.jsonl"
DEFAULT_META = ROOT / "data" / "goodell" / "meta.json"
DEFAULT_CONVERTER = ROOT / "scripts" / "convert_goodell.py"
LAST_SECTION = 683
ID_RE = re.compile(r"^goodell:(\d+)$")
GREEK_RE = re.compile(r"[\u0370-\u03ff\u1f00-\u1fff]")
MACRON_RE = re.compile(r"[ĀĒĪŌŪȲāēīōūȳ]|[AEIOUYaeiouy]\u0304")
RAW_TAG_RE = re.compile(r"<[^>]+>")
RAW_ENTITY_RE = re.compile(r"&(?:#\d+|#x[0-9A-Fa-f]+|[A-Za-z][A-Za-z0-9]+);")
UNKNOWN_ENTITY_RE = re.compile(r"&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[0-9A-Fa-f]+;)[A-Za-z][A-Za-z0-9]+;")
CHROME = ("Skip to main content", "Dickinson College", "Creative Commons", "Log in")
REQUIRED_KEYS = {
    "work", "n", "id", "sourceSlug", "letters", "notes", "path", "head", "html",
    "plain", "examples", "refs", "refRanges", "citedBy", "prev", "next",
}
VOID_TAGS = {"br", "hr", "img", "meta", "link", "input"}

# DCC stacks a combining macron OUTERMOST, over breathing and accent, the same
# transmission defect Smyth's print corrects innermost (see convert_smyth.py's
# STACKED_MACRON_RE comment for the full rule and its two kept subclasses).
# Defined independently here, not imported from the converter, so a bug in the
# shared restack rule cannot pass its own check.
GREEK_MACRON = "̄"
GREEK_BREVE = "̆"
STACKED_MACRON_RE = re.compile(r"([Ͱ-Ͽἀ-῿])̄")
GREEK_VOWELS = "αειουηωΑΕΙΟΥΗΩ"
# Counted from the raw DCC source, not the converter: 8 real sites needing the
# fix (the printed capitals Ἰ̄, Ἄ̄, Ἱ̄ among them) and 1 anceps pair (ῐ̄, DCC's
# short-or-long mark) that stays as printed.
# Counted over ALL of the DCC HTML files: 5 of the 8 stacked sites sit on
# pages that produce no section records (4 on verb-list.html, 1 on
# greek-index.html), so only 3 restacks reach sections.jsonl -- the frozen
# readings below.  A source edit on those chrome/index pages would move
# these pins without touching published records; that is intended, since the
# converter still restacks whatever it reads from them.
EXPECTED_SOURCE_MACRONS = {"stacked": 8, "anceps": 1, "bare": 0}
EXPECTED_MACRON_REPAIRS = {
    "macronsRestacked": 8,
    "ancepsMacronsKept": 1,
    "subscriptMacronsKept": 0,
}
# One frozen reading per section-visible restack (the counts and positional
# walk alone would stay green under a restack that lands on the wrong base
# or drops a breathing).  Same pattern as verify_smyth's MACRON_READINGS.
MACRON_READINGS = (
    (521, "Ῑ̓λίῳ"),
    (589, "Ᾱ̓́κοντος"),
    (636, "Ῑ̔κόμην"),
)
# Instances over the records' html, plain, and examples fields (the anceps
# site at §115 has no examples entry, so 1 tree site x 2 fields).
EXPECTED_ANCEPS_INSTANCES = 2


class AuditHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.unbalanced: list[str] = []
        self.refs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "a" and values.get("data-ref"):
            self.refs.append(values["data-ref"] or "")
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


def all_strings(value: object):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from all_strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from all_strings(item)


def hash_outputs(sections: Path, meta: Path) -> str:
    digest = hashlib.sha256()
    digest.update(sections.read_bytes())
    digest.update(b"\0")
    digest.update(meta.read_bytes())
    return digest.hexdigest()


def ascii_in_greek(value: str) -> list[str]:
    """Find an ASCII letter touching Greek script, a clear mixed-script run."""
    found: list[str] = []
    for index, char in enumerate(value):
        if not char.isascii() or not char.isalpha():
            continue
        left = value[index - 1] if index else ""
        right = value[index + 1] if index + 1 < len(value) else ""
        if GREEK_RE.fullmatch(left) and GREEK_RE.fullmatch(right):
            found.append(value[max(0, index - 18):index + 19])
    return found


# goodell:500 is the one place the print sets the reference itself in brackets
# ("(see Xen. Memorabilia 4.4.19)"), so the cite keeps them.  Named here rather
# than allowed for by a looser rule, because a second one is worth reading.
BRACKETED_CITES = {"(see Xen. Memorabilia 4.4.19)"}

# What the print is allowed to set between the three lines of an example.
# Nothing at all between the Greek and its translation; between the
# translation and the reference, only the bracketed remark ``citation_of``
# drops ("(i.e., no one was likely to be found).", "(The king is thought of
# as the central figure.)") and the punctuation it strips.
GRC_GLOSS_JOIN_RE = re.compile(r"\s*")
GLOSS_CITE_JOIN_RE = re.compile(r"[\s.,;:]*(?:\([^()]*\)[\s.,;:]*)*")


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
    numbers = [record.get("n") for record in records]
    ids = [str(record.get("id", "")) for record in records]
    expected = list(range(1, LAST_SECTION + 1))
    missing = [number for number in expected if number not in numbers]
    duplicates = [number for number, count in collections.Counter(numbers).items() if count > 1]
    report.add(
        1, numbers == expected and not duplicates,
        "complete, contiguous section coverage and unique IDs",
        f"records={len(records)}; expected={LAST_SECTION}; missing={missing}; duplicate n={duplicates}; duplicate ids={[item for item, count in collections.Counter(ids).items() if count > 1]}",
    )

    bad_shape = [record.get("n") for record in records if set(record) != REQUIRED_KEYS or record.get("work") != "goodell" or not ID_RE.fullmatch(str(record.get("id", "")))]
    empty = [record.get("n") for record in records if not str(record.get("plain", "")).strip()]
    report.add(2, not bad_shape and not empty, "canonical record shape and nonempty bodies", f"bad shape={bad_shape[:12]}; empty bodies={empty[:12]}")

    non_nfc: list[object] = []
    macrons: list[object] = []
    mixed: list[object] = []
    for record in records:
        for value in all_strings(record):
            if unicodedata.normalize("NFC", value) != value:
                non_nfc.append((record["n"], value[:80]))
            if MACRON_RE.search(value):
                macrons.append((record["n"], MACRON_RE.search(value).group(), value[:100]))
            for item in ascii_in_greek(value):
                mixed.append((record["n"], item))
    report.add(3, not non_nfc and not macrons and not mixed, "NFC Greek, no Latin macrons, and no ASCII in Greek runs", f"non-NFC={non_nfc[:4]}; Latin macrons={macrons[:4]}; mixed runs={mixed[:4]}")

    chrome = [(record["n"], phrase) for record in records for phrase in CHROME if phrase in str(record.get("plain", ""))]
    report.add(4, not chrome, "no DCC chrome in plain body text", f"chrome leaks={chrome[:12]}")

    raw_fields: list[object] = []
    bad_html: list[object] = []
    html_ref_mismatch: list[object] = []
    for record in records:
        for key, value in record.items():
            if key == "html":
                continue
            for string in all_strings(value):
                if RAW_TAG_RE.search(string) or RAW_ENTITY_RE.search(string):
                    raw_fields.append((record["n"], key, string[:100]))
        source = str(record.get("html", ""))
        parser_html = AuditHTML()
        parser_html.feed(source)
        parser_html.close()
        if parser_html.stack or parser_html.unbalanced or UNKNOWN_ENTITY_RE.search(source):
            bad_html.append((record["n"], parser_html.unbalanced[:2], parser_html.stack[:4]))
        if list(dict.fromkeys(parser_html.refs)) != record.get("refs", []):
            html_ref_mismatch.append(record["n"])
    report.add(5, not raw_fields and not bad_html and not html_ref_mismatch, "no raw source HTML or unescaped entities", f"raw non-HTML fields={raw_fields[:4]}; malformed HTML={bad_html[:4]}; HTML-ref mismatches={html_ref_mismatch[:12]}")

    by_id = {str(record["id"]): record for record in records}
    chain_errors: list[object] = []
    inverse = {record_id: [] for record_id in by_id}
    for index, record in enumerate(records):
        if record.get("prev") != (records[index - 1]["id"] if index else None) or record.get("next") != (records[index + 1]["id"] if index + 1 < len(records) else None):
            chain_errors.append(record["n"])
        for target in record.get("refs", []):
            if target in inverse:
                inverse[target].append(record["id"])
    inverse_errors = [record_id for record_id, record in by_id.items() if record.get("citedBy") != inverse[record_id]]
    report.add(6, not chain_errors and not inverse_errors, "valid prev/next chain and reference inversion", f"chain errors={chain_errors[:12]}; citedBy errors={inverse_errors[:12]}")

    # 7. Macron stacking. Independently re-derive the source counts from the
    # raw DCC HTML (not the converter's own tally) and check the positional
    # invariant on the built records: no combining macron may follow a letter
    # carrying any other mark, except the one anceps pair kept as printed.
    source_macrons = {"stacked": 0, "anceps": 0, "bare": 0}
    for path in sorted(args.input.glob("*.html")):
        text = unicodedata.normalize("NFC", path.read_text(encoding="utf-8"))
        for match in STACKED_MACRON_RE.finditer(text):
            parts = unicodedata.normalize("NFD", match.group(1))
            if parts[0] not in GREEK_VOWELS or len(parts) == 1:
                source_macrons["bare"] += 1
            elif GREEK_BREVE in parts[1:]:
                source_macrons["anceps"] += 1
            else:
                source_macrons["stacked"] += 1
    stacked_left: list[object] = []
    orphan_macrons: list[object] = []
    anceps_instances = 0
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
                if not GREEK_RE.match(carrier):
                    orphan_macrons.append((record["n"], context))
                elif GREEK_BREVE in parts[1:] or GREEK_BREVE in between:
                    anceps_instances += 1
                elif len(parts) > 1 or between:
                    stacked_left.append((record["n"], context))
    macron_repairs = {key: meta["anomalies"]["sourceMarkRepairs"][key] for key in EXPECTED_MACRON_REPAIRS}
    by_n = {record.get("n"): record for record in records}
    macron_misread = [
        (number, reading)
        for number, reading in MACRON_READINGS
        if reading not in str(by_n.get(number, {}).get("plain", ""))
    ]
    report.add(
        7,
        source_macrons == EXPECTED_SOURCE_MACRONS
        and macron_repairs == EXPECTED_MACRON_REPAIRS
        and not stacked_left
        and not orphan_macrons
        and anceps_instances == EXPECTED_ANCEPS_INSTANCES
        and not macron_misread,
        "macron stacking",
        f"source macrons={source_macrons}, expected {EXPECTED_SOURCE_MACRONS}\n"
        f"restacked={macron_repairs}, expected {EXPECTED_MACRON_REPAIRS}\n"
        f"macrons still outside another mark={len(stacked_left)}; examples={stacked_left[:5]}\n"
        f"macrons on a non-Greek carrier={len(orphan_macrons)}; examples={orphan_macrons[:5]}\n"
        f"anceps (breve+macron) instances={anceps_instances}, expected {EXPECTED_ANCEPS_INSTANCES}\n"
        f"audited readings checked={len(MACRON_READINGS)}, not reproduced={macron_misread}",
    )

    hashes: list[str] = []
    error = ""
    current = hash_outputs(args.sections, args.meta)
    try:
        with tempfile.TemporaryDirectory(prefix="verify-goodell-") as temp_name:
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
    report.add(8, not error and len(hashes) == 2 and hashes[0] == hashes[1] == current, "deterministic double conversion", f"current hash={current}; run hashes={hashes}; error={error or 'none'}")

    # 9. Every citation is a reference.
    # The label strip let label-bearing paragraphs through, and their extra
    # lines are grammatical labels, so goodell:506 shipped a cite of
    # "(Possessive Genitive)" where the print gives no reference at all and
    # goodell:498 shipped a note in front of one.  Every reference in this
    # grammar names an author, a work and a number, so a cite without a numeral
    # is not a reference, and a cite still carrying a bracket or a footnote is
    # carrying something that is not part of one.
    label_cites = [
        (record.get("n"), example.get("cite"))
        for record in records
        for example in record.get("examples", [])
        if str(example.get("cite", "")) not in BRACKETED_CITES
        and (
            not re.search(r"\d", str(example.get("cite", "")))
            or re.search(r"[()]|\[fn\]", str(example.get("cite", "")))
        )
    ]
    report.add(
        9,
        not label_cites,
        "every example citation is a reference",
        f"cites holding a label, a note or a footnote instead of, or beside, a "
        f"reference={len(label_cites)}; examples={label_cites[:8]}",
    )

    # 10. Every example is a run the print itself sets.
    #
    # Check 9 reads the citation field, and it is the only check that reads
    # any part of an example.  It asks whether a cite looks like a reference,
    # never whether it is this example's reference.  So a citation borrowed
    # from a neighbour passes it, a translation taken from the line below
    # passes it, and 768 examples had no check at all on the pairing.
    #
    # This check reads the section's own printed text instead.  ``plain`` is
    # built by ``plain()`` walking the section's blocks; it never sees
    # ``lines_of``, ``citation_of`` or ``extract_examples``.  The check asks
    # that the Greek, the translation and the reference stand there in that
    # order, with nothing between the Greek and the translation, and between
    # the translation and the reference only the bracketed remark the
    # converter drops.
    #
    # Worked example of what it catches.  DCC sets 151 examples as two lines,
    # Greek and translation with no reference of their own.  Let
    # ``extract_examples`` take those too and carry the last reference
    # forward, which is a rule the print seems to invite, since it does set
    # one reference over a run of quotations.  That adds 69 examples, each
    # pairing a quotation with another quotation's reference: goodell:456
    # then reads "ἕστηκα / (have become set), stand (§ 363) / Soph. Oedipus
    # the King 1117", and five more entries in that section carry the same
    # borrowed reference.  Checks 1 to 9 all report PASS on them, check 9
    # included, because "Soph. Oedipus the King 1117" is a perfectly
    # well-formed reference.  This check fails on all 69.
    unseated: list[object] = []
    joins: collections.Counter[str] = collections.Counter()
    for record in records:
        printed = re.sub(r"\s+", " ", str(record.get("plain", ""))).strip()
        for example in record.get("examples", []):
            grc = re.sub(r"\s+", " ", str(example.get("grc", ""))).strip()
            gloss = re.sub(r"\s+", " ", str(example.get("gloss", ""))).strip()
            cite = re.sub(r"\s+", " ", str(example.get("cite", ""))).strip()
            seated = ""
            start = 0
            while True:
                at = printed.find(grc, start)
                if at < 0 or not grc:
                    break
                after_grc = at + len(grc)
                at_gloss = printed.find(gloss, after_grc)
                if at_gloss >= 0 and GRC_GLOSS_JOIN_RE.fullmatch(printed[after_grc:at_gloss]):
                    after_gloss = at_gloss + len(gloss)
                    at_cite = printed.find(cite, after_gloss)
                    if at_cite >= 0 and GLOSS_CITE_JOIN_RE.fullmatch(printed[after_gloss:at_cite]):
                        seated = printed[after_gloss:at_cite] or " "
                        break
                start = at + 1
            if seated:
                joins[seated] += 1
            else:
                unseated.append((record.get("n"), grc[:40], gloss[:32], cite))
    report.add(
        10,
        not unseated,
        "every example is a run the print itself sets",
        f"examples={sum(len(record.get('examples', [])) for record in records)}; "
        f"remarks the print sets between the translation and the "
        f"reference={joins.most_common(5)}\n"
        f"examples the section's own text does not set as one run="
        f"{len(unseated)}; first={unseated[:6]}",
    )

    print("\nSAMPLE FIELD DUMPS")
    for number in (1, 342, 683):
        record = next((item for item in records if item.get("n") == number), None)
        print(f"§{number}:")
        print(json.dumps(record, ensure_ascii=False, indent=2) if record is not None else "MISSING")
    return report.finish()


if __name__ == "__main__":
    raise SystemExit(main())
