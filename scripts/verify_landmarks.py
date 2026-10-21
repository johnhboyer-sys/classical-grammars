#!/usr/bin/env python3
"""Independently verify the landmark data files and print a full report.

Checks data/smyth/verbs.json and particles.json against
data/smyth/sections.jsonl and against a fresh re-run of
build_landmarks.py. The print indexes (index-english.json,
index-greek.json) are built and verified by their own pipelines and are
out of scope here. Python stdlib only.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import unicodedata
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SECTIONS = ROOT / "data" / "smyth" / "sections.jsonl"
DEFAULT_DATA_DIR = ROOT / "data" / "smyth"
DEFAULT_BUILDER = ROOT / "scripts" / "build_landmarks.py"
DEFAULT_TEI = ROOT / "grammar-smyth" / "src" / "smyth_eng_u.xml"


class Report:
    def __init__(self) -> None:
        self.results: list[str] = []

    def add(self, number: int, ok: bool | None, title: str, detail: str) -> None:
        # ok=None means the check could not run. It is reported as SKIP and
        # counted separately -- never as a pass, which would let an unrun
        # check read as a verified one.
        status = "SKIP" if ok is None else ("PASS" if ok else "FAIL")
        self.results.append(status)
        print(f"[{status}] {number}. {title}")
        for line in detail.splitlines():
            print(f"  {line}")

    def summary(self) -> bool:
        passed = self.results.count("PASS")
        failed = self.results.count("FAIL")
        skipped = self.results.count("SKIP")
        print("\nVERIFY REPORT SUMMARY")
        print(
            f"  acceptance checks: {passed} passed, {failed} failed, "
            f"{skipped} skipped"
        )
        overall = "FAIL" if failed else ("PASS WITH SKIPS" if skipped else "PASS")
        print(f"  overall: {overall}")
        return failed == 0


def load_section_numbers(path: Path) -> set[int]:
    numbers: set[int] = set()
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                numbers.add(json.loads(line)["n"])
    return numbers


def is_nfc(text: str) -> bool:
    return unicodedata.normalize("NFC", text) == text


def load_sections(path: Path) -> dict[int, dict]:
    rows: dict[int, dict] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                row = json.loads(line)
                rows[row["n"]] = row
    return rows


class GreekSpans(HTMLParser):
    """The text of each ``lang="grc"`` span, in the order the entry sets them."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.spans: list[str] = []
        self.depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "span" and dict(attrs).get("lang") == "grc":
            self.depth += 1
            self.spans.append("")

    def handle_endtag(self, tag: str) -> None:
        if tag == "span" and self.depth:
            self.depth -= 1

    def handle_data(self, data: str) -> None:
        if self.depth and self.spans:
            self.spans[-1] += data


def greek_spans(markup: str) -> list[str]:
    parser = GreekSpans()
    parser.feed(markup)
    parser.close()
    return [span.strip() for span in parser.spans]


def fold_greek(text: str) -> str:
    """Lowercase, drop diacritics, and file a final sigma as a medial one."""
    nfd = unicodedata.normalize("NFD", (text or "").lower())
    return "".join(ch for ch in nfd
                   if not unicodedata.combining(ch)).replace("\u03c2", "\u03c3")


def greek_words(row: dict | None) -> set[str]:
    """Every Greek word the section prints, in its body and in its head,
    folded.  Words, not substrings: "ἄν" is not printed by "ἄνθρωπος"."""
    if row is None:
        return set()
    text = f"{row.get('plain') or ''} {row.get('head') or ''}"
    return {fold_greek(word)
            for word in re.findall(r"[\u0370-\u03ff\u1f00-\u1fff]+", text)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sections", type=Path, default=DEFAULT_SECTIONS)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--builder", type=Path, default=DEFAULT_BUILDER)
    parser.add_argument("--tei-source", type=Path, default=DEFAULT_TEI)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    report = Report()
    section_numbers = load_section_numbers(args.sections)
    sections_by_n = load_sections(args.sections)

    verbs_doc = json.loads((args.data_dir / "verbs.json").read_text(encoding="utf-8"))
    particles_doc = json.loads(
        (args.data_dir / "particles.json").read_text(encoding="utf-8")
    )
    verbs = verbs_doc["verbs"]
    particles = particles_doc["particles"]

    # 1. Every verb section reference exists in sections.jsonl, and the
    #    builder dropped nothing on the way: an appendix <p> with no Greek
    #    headword is skipped by extract_verbs and only recorded in
    #    _meta.entriesWithoutLemma, so that list has to stay empty for the
    #    761 entries to be the whole appendix.
    bad_verb_refs = [
        (v["lemma"], n)
        for v in verbs
        for n in v["sections"]
        if n not in section_numbers
    ]
    verbs_meta = verbs_doc["_meta"]
    dropped = verbs_meta["entriesWithoutLemma"]
    invalid_refs = verbs_meta["invalidSectionRefs"]
    count_ok = verbs_meta["count"] == len(verbs)
    report.add(
        1,
        not bad_verb_refs and not dropped and not invalid_refs and count_ok,
        "every verbs.json section reference exists in sections.jsonl",
        f"verbs={len(verbs)}; bad refs={bad_verb_refs[:10]}"
        + (f" (+{len(bad_verb_refs) - 10} more)" if len(bad_verb_refs) > 10 else "")
        + f"\nentries dropped for want of a lemma={dropped}; "
        f"out-of-range refs={invalid_refs}; _meta.count matches={count_ok}",
    )

    # 2. Every particle section reference exists in sections.jsonl.
    bad_particle_refs = [
        (p["particle"], entry["n"])
        for p in particles
        for entry in p["sections"]
        if entry["n"] not in section_numbers
    ]
    report.add(
        2,
        not bad_particle_refs,
        "every particles.json section reference exists in sections.jsonl",
        f"particles={len(particles)}; bad refs={bad_particle_refs[:10]}",
    )

    # 3. Every particle has at least one primary section.
    no_primary = [
        p["particle"]
        for p in particles
        if not any(e["role"] == "primary" for e in p["sections"])
    ]
    report.add(
        3,
        not no_primary,
        "every particle has at least one primary section",
        f"particles without a primary section: {no_primary}",
    )

    # 4. NFC normalization holds everywhere Greek text appears.
    non_nfc: list[str] = []
    for v in verbs:
        if not is_nfc(v["lemma"]):
            non_nfc.append(f"verb lemma {v['lemma']!r}")
    for p in particles:
        if not is_nfc(p["particle"]):
            non_nfc.append(f"particle {p['particle']!r}")
    report.add(
        4,
        not non_nfc,
        "NFC normalization holds for every lemma/particle string",
        f"non-NFC strings: {non_nfc[:10]}",
    )

    # 5. Particle slugs are unique.
    slugs = [p["slug"] for p in particles]
    dup_slugs = sorted({s for s in slugs if slugs.count(s) > 1})
    report.add(
        5,
        not dup_slugs,
        "particle slugs are collision-free",
        f"slug count={len(slugs)}; unique={len(set(slugs))}; duplicates={dup_slugs}",
    )

    # 6. Particle slugs are lowercase ASCII (URL-safe per SPEC-section-ids.md).
    bad_slug_chars = [s for s in slugs if not (s and s.isascii() and s == s.lower())]
    report.add(
        6,
        not bad_slug_chars,
        "particle slugs are lowercase ASCII",
        f"offending slugs: {bad_slug_chars}",
    )

    # 7. verbs.json is sorted by the documented Greek collation (base
    # letters, in Greek-alphabet order, accents ignored).
    sys.path.insert(0, str(args.builder.parent))
    import build_landmarks as builder  # type: ignore

    lemma_keys = [builder.collation_key(v["lemma"]) for v in verbs]
    is_sorted = lemma_keys == sorted(lemma_keys)
    first_bad = next(
        (
            i
            for i in range(1, len(lemma_keys))
            if lemma_keys[i] < lemma_keys[i - 1]
        ),
        None,
    )
    detail = f"verbs={len(verbs)}; sorted={is_sorted}"
    if first_bad is not None:
        detail += (
            f"; first inversion at index {first_bad}: "
            f"{verbs[first_bad - 1]['lemma']!r} before {verbs[first_bad]['lemma']!r}"
        )
    report.add(7, is_sorted, "verbs.json is sorted by Greek collation", detail)

    # 8. The letter-count in verbs.json matches the 24-letter Greek
    # alphabet the appendix actually covers.
    letters_ok = verbs_doc["_meta"]["letterGroups"] == 24
    report.add(
        8,
        letters_ok,
        "verbs cover all 24 letters",
        f"verbs letterGroups={verbs_doc['_meta']['letterGroups']}",
    )

    # 8a. Every lemma is the headword its own entry prints, and every
    # particle reference points at a section that prints the particle.
    #
    # Checks 1 to 8 are counts, set membership and shape: a section number
    # exists, a slug is unique and ASCII, a string is NFC, a list is sorted,
    # a number is 24.  Not one of them reads a word of what the entry or the
    # section says.  A verb could carry another verb's entry, and a particle
    # could point at a run of sections that never mentions it, and every
    # check would report PASS.
    #
    # So: a verb's lemma must be the first Greek span the entry prints, which
    # is the headword the appendix sets; a "mention" must print the particle
    # in the section's own text or head; and each contiguous run of a
    # particle's "primary" sections must print it somewhere in the run.  The
    # run, not the single section, because Smyth heads §§2930-2941 "οὐδέ,
    # οὔτε (μηδέ, μήτε)" and then discusses οὐδέ for eleven sections; μήτε
    # and οὔτε are primary there on the strength of that heading, and 20 of
    # the 337 primary references stand on it.
    lemma_wrong: list[object] = []
    for verb in verbs_doc["verbs"]:
        spans = greek_spans(str(verb.get("entryHtml", "")))
        if not spans or spans[0] != verb["lemma"]:
            lemma_wrong.append((verb["lemma"], spans[:2]))
    particle_wrong: list[object] = []
    runs_checked = 0
    mentions_checked = 0
    for particle in particles_doc["particles"]:
        wanted = fold_greek(particle["particle"])
        primary = sorted(s["n"] for s in particle["sections"]
                         if s.get("role") == "primary")
        runs: list[list[int]] = []
        for number in primary:
            if runs and number == runs[-1][-1] + 1:
                runs[-1].append(number)
            else:
                runs.append([number])
        for run in runs:
            runs_checked += 1
            if not any(wanted in greek_words(sections_by_n.get(number))
                       for number in run):
                particle_wrong.append(
                    (particle["particle"], f"primary §§{run[0]}-{run[-1]}"))
        for entry in particle["sections"]:
            if entry.get("role") != "mention":
                continue
            mentions_checked += 1
            row = sections_by_n.get(entry["n"])
            if row is not None and wanted not in greek_words(row):
                particle_wrong.append(
                    (particle["particle"], f"mention §{entry['n']}"))
    report.add(
        "8a",
        not lemma_wrong and not particle_wrong,
        "every lemma is its entry's own headword, and every particle "
        "reference points at a section that prints it",
        f"verbs={len(verbs_doc['verbs'])}; lemmas that are not the entry's "
        f"first Greek span={len(lemma_wrong)}; examples={lemma_wrong[:5]}\n"
        f"primary runs={runs_checked}; mentions={mentions_checked}; "
        f"references the print does not bear out={len(particle_wrong)}; "
        f"examples={particle_wrong[:5]}",
    )

    # 9. Determinism: re-running the builder against the same inputs
    # reproduces every output file byte-for-byte.
    determinism_ok: bool | None = True
    determinism_detail = []
    if args.tei_source.exists():
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            result = subprocess.run(
                [
                    sys.executable,
                    str(args.builder),
                    "--tei-source",
                    str(args.tei_source),
                    "--sections",
                    str(args.sections),
                    "--out-dir",
                    str(tmp_dir),
                ],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                determinism_ok = False
                determinism_detail.append(f"builder exited {result.returncode}: {result.stderr}")
            else:
                for filename in (
                    "verbs.json",
                    "particles.json",
                ):
                    fresh = (tmp_dir / filename).read_text(encoding="utf-8")
                    current = (args.data_dir / filename).read_text(encoding="utf-8")
                    if fresh != current:
                        determinism_ok = False
                        determinism_detail.append(f"{filename} differs from a fresh build")
    else:
        determinism_ok = None
        determinism_detail.append(
            f"not run: TEI source not found at {args.tei_source} "
            "(pass --tei-source; grammar-smyth/ is gitignored and absent in worktrees)"
        )
    report.add(
        9,
        determinism_ok,
        "re-running the builder reproduces every output byte-for-byte",
        "\n".join(determinism_detail) or "both files identical to a fresh build",
    )

    return 0 if report.summary() else 1


if __name__ == "__main__":
    raise SystemExit(main())
