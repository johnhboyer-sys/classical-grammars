#!/usr/bin/env python3
"""Independently verify the non-Smyth citation indexes and the combined one.

Checks data/<work>/citations.json for goodwin-gmt, gildersleeve, monro,
goodell and ag, plus data/citations-index.json, and prints a full report.
Run with --sample to print the 30-key QA sample described in
SPEC-citations.md.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import subprocess
import sys
import tempfile
from html import unescape as html_unescape
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_citations_all as builder  # noqa: E402
import citation_tables  # noqa: E402

WORKS = builder.WORKS
SMYTH_CITATIONS = ROOT / "data" / "smyth" / "citations.json"

# Ceiling on the share of a grammar's citations that may go unkeyed.
# Justified in SPEC-citations-all.md: the worst grammar today is Gildersleeve
# at 5.29%, four-fifths of it the fragment references (Nauck, Bergk, Meineke,
# Kock) that are deliberately excluded because their numbering is
# edition-specific. 6% leaves room for a source edit to add a few more
# without breaking CI, while a new *class* of unkeyed citation trips it.
UNPARSED_CEILING = 0.06

# Result of the manual QA pass recorded in SPEC-citations-all.md: 30 random
# passage keys were read against the citation text each came from. All 30 key
# exactly what their citation string says; 29 were confirmed to name a real
# passage of the work named. The 30th, Gildersleeve §49's "Dem. 5" -> dem.5,
# is faithful to the string and names a real oration, but sits in the class
# of bare oration numbers the print's compressed lists produce, so it may be
# a truncation; it could not be confirmed either way and is counted against
# us. Re-run with --sample and update both numbers together if the tables
# change.
QA_SAMPLE_SIZE = 30
QA_SAMPLE_CONFIRMED = 29
QA_SAMPLE_SEED = 20260907

# Spot-fixtures: passage key -> (work, section) that must cite it. Chosen so
# that each grammar and each shape of prefix is represented.
FIXTURES = [
    ("hom.il.2.77", "monro", 12),           # "Il. 2.77"
    ("hom.od.20.294", "monro", 283),        # "Od.20.294", no space
    ("plat.soph.262c", "gildersleeve", 1),  # "Plat. Soph. 262C"
    ("hdt.2.39", "gildersleeve", 258),      # "HDT.2.39" in the printed text
    ("xen.anab.2.1.4", "goodell", 454),     # "Xen. Anabasis 2.1.4"
    ("soph.ot.413", "goodell", 456),        # "Soph. Oedipus the King 413"
    ("verg.a.6.653", "ag", 92),             # "Verg. A. 6.653"
    ("cic.n-d.2.93", "ag", 1),              # "Cic. N.D. 2.93"
    ("hom.il.1.262", "goodwin-gmt", 6),     # "Hom. Il. 1.262"
    ("aesch.seven.754", "goodwin-gmt", 148),  # "Sept. 754"
]


class CiteScanner(HTMLParser):
    """Re-extract (cite text, anchor) with the stdlib tokenizer instead of
    the builder's regex, so a broken scan is caught rather than echoed."""

    def __init__(self, letters: set[str]) -> None:
        super().__init__(convert_charrefs=True)
        self.letters = letters
        self.cites: list[tuple[str, str | None]] = []
        self.anchor: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        id_value = values.get("id")
        if id_value and id_value in self.letters:
            self.anchor = id_value
        if tag == "cite" and "data-cite" in values:
            self.cites.append((values["data-cite"] or "", self.anchor))


def rescan(record: dict[str, object]) -> list[tuple[str, str | None]]:
    """The verifier's own reading of one section's citations, mirroring
    builder.iter_section_citations but built on html.parser."""
    letters = {str(letter) for letter in (record.get("letters") or [])}
    found: list[tuple[str, str | None]] = []
    seen: dict[str, int] = {}
    markups = [str(record.get("html") or "")]
    markups += [str(note.get("html") or "")
                for note in (record.get("notes") or [])]
    for markup in markups:
        scanner = CiteScanner(letters)
        scanner.feed(markup)
        scanner.close()
        for text, anchor in scanner.cites:
            found.append((text, anchor))
            seen[text] = seen.get(text, 0) + 1
    for example in (record.get("examples") or []):
        text = example.get("cite")
        if not text:
            continue
        if seen.get(text, 0) > 0:
            seen[text] -= 1
            continue
        found.append((text, None))
    return found


# --- reading the numbers and the prefix the print itself writes -------------
# None of this consults build_citations_all.clean, parse_locator, classify or
# build_key.  It reads the citation string as characters: the numbers it
# contains, in order, with roman numerals valued; and the prefix it opens
# with, after undoing the escaping and the zero-width padding the mirrors
# leave in (Goodell sets seven U+200B before "Soph. Antigone 605").
_ROMAN_VALUES = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500,
                 "m": 1000}
_NUMBER_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9])[ivxlcdmIVXLCDM]+(?![A-Za-z0-9])|[0-9]+")
_ZERO_WIDTH_RE = re.compile("[​‌‍﻿]")
_LEAD_PAREN_RE = re.compile(r"^\([^()]*\)[\s.,;:]*")
_LOCATOR_PART_RE = re.compile(r"[0-9]+[a-z]?")


def numbers_written(text: str) -> list[str]:
    """The numbers this citation string writes, in order, romans valued."""
    written: list[str] = []
    for match in _NUMBER_TOKEN_RE.finditer(text):
        token = match.group()
        if token.isdigit():
            written.append(token.lstrip("0") or "0")
            continue
        total = 0
        previous = 0
        for char in reversed(token.lower()):
            value = _ROMAN_VALUES[char]
            total += -value if value < previous else value
            previous = max(previous, value)
        written.append(str(total))
    return written


def opening_text(raw: str) -> str:
    """The citation as the reader meets it, lowercased, ready for a prefix
    test: entities resolved, zero-width padding gone, whitespace collapsed,
    and Goodell's leading bracketed remark set aside."""
    text = " ".join(_ZERO_WIDTH_RE.sub("", html_unescape(raw)).split()).lower()
    while True:
        stripped = _LEAD_PAREN_RE.sub("", text).strip()
        if not stripped or stripped == text:
            break
        text = stripped
    return text


def split_key(key: str) -> tuple[str, list[str]]:
    """A passage key into its slug path and its locator components."""
    parts = key.split(".")
    cut = len(parts)
    while cut and _LOCATOR_PART_RE.fullmatch(parts[cut - 1]):
        cut -= 1
    return ".".join(parts[:cut]), parts[cut:]


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


def entry_triples(data: dict[str, object]) -> set[tuple[str, str, str]]:
    return {
        (key, str(entry["section"]), str(entry.get("anchor") or ""))
        for key, entries in data.items() if key != "_meta"
        for entry in entries
    }


def print_sample(datasets: dict[str, dict[str, object]],
                 records: dict[str, list[dict[str, object]]]) -> None:
    """Print QA_SAMPLE_SIZE random passage keys next to the raw citation
    text each was built from, for a human to read."""
    rows: list[tuple[str, str, str, str]] = []
    for work in WORKS:
        lookup = builder.build_lookup(citation_tables.TABLES[work])
        for record in records[work]:
            section = builder.section_id(record)
            for raw, _anchor in builder.iter_section_citations(record):
                cleaned = builder.clean(raw)
                classified = (builder.classify(cleaned, lookup)[0]
                              if cleaned else None)
                if classified is None:
                    continue
                _prefix, row, locator = classified
                rows.append((builder.build_key(row, locator), work,
                             str(section), raw))
    rows.sort()
    sample = random.Random(QA_SAMPLE_SEED).sample(
        rows, min(QA_SAMPLE_SIZE, len(rows)))
    print(f"\nQA SAMPLE ({len(sample)} random keys, seed {QA_SAMPLE_SEED})")
    for key, work, section, raw in sorted(sample):
        print(f"  {key:<34} <- {work} §{section}: {raw!r}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "data")
    parser.add_argument("--combined", type=Path,
                        default=ROOT / "data" / "citations-index.json")
    parser.add_argument("--sample", action="store_true",
                        help="print the QA sample of passage keys")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    report = Report()
    records = {
        work: builder.load_records(args.data / work / "sections.jsonl")
        for work in WORKS
    }
    datasets = {
        work: json.loads((args.data / work / "citations.json")
                         .read_text(encoding="utf-8"))
        for work in WORKS
    }
    combined = json.loads(args.combined.read_text(encoding="utf-8"))
    smyth = json.loads(SMYTH_CITATIONS.read_text(encoding="utf-8"))

    # 1. Citation totals reconcile with an independent rescan of the source.
    lines = []
    one_ok = True
    for work in WORKS:
        source_total = sum(len(rescan(r)) for r in records[work])
        meta = datasets[work]["_meta"]
        ok = (
            source_total == meta["sourceCitations"]
            and meta["parsed"] + meta["unparsed"] == meta["sourceCitations"]
            and len(meta["unparsedCitations"]) == meta["unparsed"]
        )
        one_ok = one_ok and ok
        lines.append(
            f"{work}: html.parser rescan={source_total}, "
            f"meta.sourceCitations={meta['sourceCitations']}, "
            f"parsed={meta['parsed']} + unparsed={meta['unparsed']}"
        )
    report.add(1, one_ok, "citation totals reconcile with the source",
               "\n".join(lines))

    # 2. Every section a per-work index references exists in that grammar.
    dangling: list[object] = []
    for work in WORKS:
        known = {str(builder.section_id(r)) for r in records[work]}
        for key, entries in datasets[work].items():
            if key == "_meta":
                continue
            for entry in entries:
                if str(entry["section"]) not in known:
                    dangling.append((work, key, entry))
    report.add(2, not dangling, "every referenced section exists",
               f"dangling references={len(dangling)}; "
               f"examples={dangling[:5]}")

    # 3. Deterministic build: two runs byte-identical to each other and to
    # the checked-in files. Run with a private --data copy so the real files
    # are never rewritten by the verifier.
    determinism_error = ""
    mismatched: list[str] = []
    try:
        with tempfile.TemporaryDirectory(prefix="verify-citations-all-") as tmp:
            outputs: list[dict[str, bytes]] = []
            for run in (1, 2):
                run_dir = Path(tmp) / f"run{run}"
                for work in WORKS:
                    (run_dir / work).mkdir(parents=True, exist_ok=True)
                    (run_dir / work / "sections.jsonl").write_bytes(
                        (args.data / work / "sections.jsonl").read_bytes())
                combined_path = run_dir / "citations-index.json"
                completed = subprocess.run(
                    [sys.executable,
                     str(ROOT / "scripts" / "build_citations_all.py"),
                     "--data", str(run_dir),
                     "--combined", str(combined_path),
                     "--smyth-citations", str(SMYTH_CITATIONS)],
                    check=False, capture_output=True, text=True,
                )
                if completed.returncode != 0:
                    raise RuntimeError(
                        f"builder run {run} failed: {completed.stderr.strip()}")
                outputs.append({
                    **{w: (run_dir / w / "citations.json").read_bytes()
                       for w in WORKS},
                    "_combined": combined_path.read_bytes(),
                })
            for name in outputs[0]:
                if outputs[0][name] != outputs[1][name]:
                    mismatched.append(f"{name}: run 1 != run 2")
            for work in WORKS:
                if outputs[0][work] != (args.data / work
                                        / "citations.json").read_bytes():
                    mismatched.append(f"{work}: rebuild != checked-in file")
            if outputs[0]["_combined"] != args.combined.read_bytes():
                mismatched.append("combined: rebuild != checked-in file")
    except Exception as error:  # report, do not hide the other checks
        determinism_error = str(error)
    report.add(3, not determinism_error and not mismatched,
               "deterministic build, matching the checked-in files",
               f"error={determinism_error or 'none'}\n"
               f"mismatches={mismatched or 'none'}")

    # 4. Unparsed rate per grammar stays under the ceiling.
    rate_lines = []
    four_ok = True
    for work in WORKS:
        meta = datasets[work]["_meta"]
        rate = meta["unparsed"] / meta["sourceCitations"]
        four_ok = four_ok and rate <= UNPARSED_CEILING
        rate_lines.append(
            f"{work}: {meta['unparsed']}/{meta['sourceCitations']} "
            f"= {rate:.2%}"
            f"{'' if rate <= UNPARSED_CEILING else '  OVER CEILING'}")
    report.add(4, four_ok,
               f"unparsed rate under the {UNPARSED_CEILING:.0%} ceiling",
               "\n".join(rate_lines))

    # 5. Slugs mean one thing. Across every table at once an author_slug must
    # name one author -- the combined index merges on slugs, so "soph" may
    # not be Sophocles here and the Sophist there. Within one grammar's
    # table, an (author_slug, work_slug) pair must name one work; the same
    # pair is deliberately reached from differently spelled prefixes in
    # different grammars ("Soph. OT" in Goodwin, "Soph. Oedipus the King" in
    # Goodell), which is the point of the shared slug vocabulary.
    authors: dict[str, str] = {}
    slug_pairs: set[tuple[str, str | None]] = set()
    collisions: list[object] = []
    for work, table in citation_tables.TABLES.items():
        works_seen: dict[tuple[str, str | None], str | None] = {}
        for prefix, (author_full, author_slug, work_full,
                     work_slug) in table.items():
            if authors.setdefault(author_slug, author_full) != author_full:
                collisions.append((work, prefix, author_slug,
                                   authors[author_slug], author_full))
            slugs = (author_slug, work_slug)
            slug_pairs.add(slugs)
            if works_seen.setdefault(slugs, work_full) != work_full:
                collisions.append((work, prefix, slugs, works_seen[slugs],
                                   work_full))
    report.add(5, not collisions,
               "every slug names one author, and one work per grammar",
               f"author slugs={len(authors)}; "
               f"distinct (author, work) slug pairs={len(slug_pairs)}; "
               f"collisions={collisions or 'none'}")

    # 6. The combined index is exactly the union of the per-work indexes,
    # Smyth's included, and adds nothing of its own.
    expected: set[tuple[str, str, str, str]] = set()
    for work in WORKS:
        expected |= {(work, *triple) for triple in
                     entry_triples(datasets[work])}
    expected |= {("smyth", *triple) for triple in entry_triples(smyth)}
    actual = {
        (str(entry["work"]), key, str(entry["section"]),
         str(entry.get("anchor") or ""))
        for key, entries in combined.items() if key != "_meta"
        for entry in entries
    }
    report.add(6, expected == actual,
               "combined index is the exact union of the per-work indexes",
               f"per-work entries={len(expected)}; combined={len(actual)}\n"
               f"missing from combined={len(expected - actual)}; "
               f"examples={sorted(expected - actual)[:3]}\n"
               f"extra in combined={len(actual - expected)}; "
               f"examples={sorted(actual - expected)[:3]}")

    # 7. Spot-fixtures resolve, in the per-work file and in the combined one.
    fixture_errors: list[str] = []
    for key, work, section in FIXTURES:
        entries = datasets[work].get(key)
        if not entries or section not in {e["section"] for e in entries}:
            fixture_errors.append(f"{key}: not in {work} §{section}")
            continue
        merged = combined.get(key) or []
        if not any(e["work"] == work and e["section"] == section
                   for e in merged):
            fixture_errors.append(f"{key}: {work} §{section} "
                                  "missing from the combined index")
    report.add(7, not fixture_errors, "spot-fixtures resolve",
               f"fixtures checked={len(FIXTURES)}\n"
               f"errors={fixture_errors or 'none'}")

    # 8. The cross-grammar question the index exists to answer. A locator is
    # a dot-path, so "Thucydides 1.9" is the key thuc.1.9 plus every key
    # under it -- Gildersleeve cites Thucydides one level finer than Smyth
    # and Goodwin do. See SPEC-citations.md.
    query = "thuc.1.9"
    hits = [entry for key, entries in combined.items()
            if key != "_meta" and (key == query or key.startswith(query + "."))
            for entry in entries]
    works_hit = sorted({str(entry["work"]) for entry in hits})
    report.add(8, len(works_hit) >= 3,
               "cross-grammar lookup answers 'who discusses Thuc. 1.9?'",
               f"prefix query {query!r} -> {len(hits)} sections "
               f"in {works_hit}")

    # 9. Smyth's index is untouched by this pipeline.
    smyth_meta = smyth["_meta"]
    report.add(9, smyth_meta["sourceCitations"] == 5193
               and "work" not in smyth_meta,
               "Smyth's citations.json is not rewritten here",
               f"data/smyth/citations.json still reports "
               f"{smyth_meta['sourceCitations']} source citations and no "
               f"'work' key (build_citations_index.py's format)")

    # 10. No key names a book its work does not have. Checked against the
    # written index rather than by trusting the builder, because this is the
    # defect class the minimum-depth rule missed: the print's compressed
    # back-reference runs drop a leading book and leave "THUC., 76.4", which
    # keyed naively is Thucydides book 76 of eight.
    impossible: list[object] = []
    smyth_notes: list[object] = []
    checked = 0
    for work in [*WORKS, "smyth"]:
        data = datasets[work] if work in datasets else smyth
        for key in data:
            if key == "_meta":
                continue
            for (author_slug, work_slug), ceiling in (
                    citation_tables.BOOK_COUNTS.items()):
                stem = (author_slug if work_slug is None
                        else f"{author_slug}.{work_slug}")
                if not key.startswith(stem + "."):
                    continue
                digits = re.match(r"[0-9]+", key[len(stem) + 1:].split(".")[0])
                if not digits:
                    continue
                checked += 1
                if int(digits.group()) > ceiling:
                    # Smyth's index belongs to build_citations_index.py and is
                    # frozen; a finding there is reported, not failed on.
                    (smyth_notes if work == "smyth" else impossible).append(
                        (work, key, stem, ceiling))
                break
    report.add(10, not impossible,
               "no key names a book its work does not have",
               f"keys checked against a book count={checked} "
               f"({len(citation_tables.BOOK_COUNTS)} works have one)\n"
               f"impossible keys in the five indexes built here="
               f"{len(impossible)}; examples={impossible[:5]}\n"
               f"noted in Smyth's frozen index (not a failure here)="
               f"{len(smyth_notes)}; {smyth_notes[:5]}")

    # 11. Every index entry is explained by a citation printed in that
    # section, prefix, numbers and anchor.
    #
    # Check 1 already rescans every section's citations with html.parser,
    # independently of the builder's regex, and then throws all of it away
    # but the length. It compares three integers. So does check 4. Check 2
    # asks that a section exist, check 6 that two sets be equal, check 3 that
    # a rebuild be identical, and none of them ever asks whether a key says
    # what the citation it came from says. The whole content coverage of
    # 14,869 entries was check 7's ten fixtures and check 10's book
    # ceilings.
    #
    # This check uses the rescan's own output. For an entry to be explained,
    # the section must print a citation that (a) opens with a prefix this
    # grammar's table maps to the key's author and work, (b) writes the
    # key's locator numbers, in that order and next to each other, reading
    # roman numerals as numbers and leaving a Stephanus letter attached to
    # the number before it, and (c) sits under the anchor the entry records. Nothing here calls clean, parse_locator, classify or
    # build_key.
    #
    # Worked example of what it catches. iter_section_citations counts an id
    # as a lettered-subsection anchor only when the record itself declares it
    # in "letters". Drop that gate and 620 of the corpus's 13,145 citations
    # take a different anchor, mostly a note's own id: Gildersleeve §8's
    # three citations are anchored "n1" and §12's five "fn1", neither of
    # which is a subsection of anything. Built that way, 585 entries carry an
    # anchor no subsection has. Every count stays exactly what it was, so
    # checks 1 and 4 pass, the rebuild is still deterministic so check 3
    # passes, and the combined index is still the union of the per-work ones
    # so check 6 passes. Checks 1 to 10 all report PASS; this check reports
    # FAIL on all 585.
    unexplained: list[object] = []
    explained = 0
    for work in WORKS:
        prefixes_by_slug: dict[str, list[str]] = {}
        for prefix, row in citation_tables.TABLES[work].items():
            _author_full, author_slug, _work_full, work_slug = row
            slug = (author_slug if work_slug is None
                    else f"{author_slug}.{work_slug}")
            prefixes_by_slug.setdefault(slug, []).append(prefix.lower())
        printed: dict[str, list[tuple[str, list[str], str]]] = {}
        for record in records[work]:
            printed[str(builder.section_id(record))] = [
                (opening_text(raw), numbers_written(raw), anchor or "")
                for raw, anchor in rescan(record)
            ]
        for key, entries in datasets[work].items():
            if key == "_meta":
                continue
            slug, locator = split_key(key)
            wanted = [re.match(r"[0-9]+", part).group() for part in locator]
            allowed = prefixes_by_slug.get(slug, [])
            for entry in entries:
                anchor = str(entry.get("anchor") or "")
                found = False
                for text, written, seen_anchor in printed.get(
                        str(entry["section"]), []):
                    if seen_anchor != anchor:
                        continue
                    if not any(text.startswith(item) for item in allowed):
                        continue
                    if any(written[at:at + len(wanted)] == wanted
                           for at in range(len(written) - len(wanted) + 1)):
                        found = True
                        break
                if found:
                    explained += 1
                else:
                    unexplained.append((work, key, entry))
    report.add(11, not unexplained,
               "every entry is explained by a citation printed there",
               f"entries explained by the print's own prefix, numbers and "
               f"anchor={explained}\n"
               f"entries no citation in their section explains="
               f"{len(unexplained)}; examples={unexplained[:5]}")

    if args.sample:
        print_sample(datasets, records)
    else:
        print(f"\nQA sample: {QA_SAMPLE_CONFIRMED}/{QA_SAMPLE_SIZE} keys "
              f"confirmed correct in the recorded manual pass "
              f"(seed {QA_SAMPLE_SEED}); re-run with --sample to reread it.")

    return 0 if report.summary() else 1


if __name__ == "__main__":
    raise SystemExit(main())
