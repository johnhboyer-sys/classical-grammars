#!/usr/bin/env python3
"""Independently verify data/smyth/topics.json and data/smyth/section-topics.json
and print a full report.

Checks the derived topic list and the same join read backwards against
data/smyth/sections.jsonl, data/smyth/index-english.json,
data/smyth/index-greek.json, data/smyth/constructions.json and a fresh re-run
of scripts/build_topics.py. Python stdlib only.

  1  every cited section (section, range end, hub section) exists
  2  every range runs forwards; no topic has an empty section list
  3  slugs unique, lowercase ASCII, and the file is sorted by slug
  4  every English index entry that cites a section appears in some topic
  5  every non-prose construction entry appears in some topic
  6  every topic names at least one source, and provenance matches sources
  7  aliases never repeat the topic name; related slugs resolve
  8  hub sections meet the threshold the file declares
  9  meta counts agree with the topics array
 10  determinism: a fresh build reproduces both committed files byte for byte
 11  section-topics.json has one row per section, in order, with sorted,
     deduplicated slugs that all exist in topics.json
 12  the join agrees both ways: every section a topic covers names that
     topic's slug, and every slug named on a section covers it
 13  every Greek index entry either seeds exactly one topic or is excluded by
     one of the two rules the file declares, and the counts add up
 14  every Greek topic covers exactly the sections its entries cite, is named
     by the headword the print gives, carries the transliteration as an alias,
     and holds a slug the slug rule produces

The distribution of topics per section is printed as a note under check 11.

Exit status is non-zero if any check FAILs.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SECTIONS = ROOT / "data" / "smyth" / "sections.jsonl"
DEFAULT_INDEX = ROOT / "data" / "smyth" / "index-english.json"
DEFAULT_INDEX_GREEK = ROOT / "data" / "smyth" / "index-greek.json"
DEFAULT_CONSTRUCTIONS = ROOT / "data" / "smyth" / "constructions.json"
DEFAULT_TOPICS = ROOT / "data" / "smyth" / "topics.json"
DEFAULT_SECTION_TOPICS = ROOT / "data" / "smyth" / "section-topics.json"
DEFAULT_BUILDER = ROOT / "scripts" / "build_topics.py"


class Report:
    def __init__(self) -> None:
        self.results: list[str] = []

    def add(self, number: int, ok: bool, title: str, detail: str = "") -> None:
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
        print(f"  overall: {'FAIL' if failed else 'PASS'}")
        return failed == 0


def load_sections(path: Path) -> dict[int, dict]:
    rows: dict[int, dict] = {}
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                row = json.loads(line)
                rows[row["n"]] = row
    return rows


def index_refs(entry: dict) -> list[dict]:
    refs = list(entry.get("refs", []))
    for sub in entry.get("sub", []):
        refs.extend(sub.get("refs", []))
    return refs


# The transliteration table and the two Greek rules are written out again
# here rather than imported, so that a change in build_topics.py has to be
# made twice before both halves agree that it is right.
GREEK_TO_LATIN = {
    "α": "a", "β": "b", "γ": "g", "δ": "d", "ε": "e", "ζ": "z", "η": "e",
    "θ": "th", "ι": "i", "κ": "k", "λ": "l", "μ": "m", "ν": "n", "ξ": "x",
    "ο": "o", "π": "p", "ρ": "r", "σ": "s", "ς": "s", "τ": "t", "υ": "u",
    "φ": "ph", "χ": "ch", "ψ": "ps", "ω": "o",
}
SMOOTH_BREATHING = "̓"
ROUGH_BREATHING = "̔"


def transliterate(text: str) -> str:
    """Lowercase ASCII, hyphen separated; a rough breathing at the start of a
    word becomes h-, or rh- on rho."""
    nfd = unicodedata.normalize("NFD", text)
    out: list[str] = []
    start = True
    for i, ch in enumerate(nfd):
        if unicodedata.combining(ch):
            continue
        base = ch.lower()
        if base in GREEK_TO_LATIN:
            latin = GREEK_TO_LATIN[base]
            if start:
                marks = ""
                j = i + 1
                while j < len(nfd) and unicodedata.combining(nfd[j]):
                    marks += nfd[j]
                    j += 1
                if ROUGH_BREATHING in marks:
                    latin = "rh" if base == "ρ" else "h" + latin
            out.append(latin)
            start = False
        elif base.isascii() and base.isalnum():
            out.append(base)
            start = False
        else:
            out.append("-")
            start = True
    return re.sub(r"-+", "-", "".join(out)).strip("-")


def head_form(headword: str) -> str:
    """The headword without its parenthetical gloss."""
    return re.sub(r"\([^)]*\)", " ", headword)


def is_alphabet_letter(headword: str) -> bool:
    """One Greek letter carrying no breathing: the letter, not a word."""
    nfd = unicodedata.normalize("NFD", headword.strip())
    bases = [ch for ch in nfd if not unicodedata.combining(ch)]
    if len(bases) != 1:
        return False
    if bases[0].lower() not in GREEK_TO_LATIN and bases[0] not in ("Ϝ", "ϝ"):
        return False
    return SMOOTH_BREATHING not in nfd and ROUGH_BREATHING not in nfd


def greek_entry_sections(entry: dict, sections: dict[int, dict]) -> list[tuple[int, int]]:
    """(n, to) per usable ref, deduplicated and sorted. A ref's anchor is a
    lettered subdivision; the section is what a topic covers."""
    out = set()
    for ref in entry.get("refs", []):
        if ref.get("nonSection"):
            continue
        n = ref.get("n")
        if not isinstance(n, int) or n not in sections:
            continue
        to = ref.get("to")
        out.add((n, to) if isinstance(to, int) and to in sections and to >= n else (n, n))
    return sorted(out)


def short(items: list, limit: int = 10) -> str:
    text = ", ".join(str(i) for i in items[:limit])
    if len(items) > limit:
        text += f" (+{len(items) - limit} more)"
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sections", type=Path, default=DEFAULT_SECTIONS)
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--constructions", type=Path, default=DEFAULT_CONSTRUCTIONS)
    parser.add_argument("--index-greek", type=Path, default=DEFAULT_INDEX_GREEK)
    parser.add_argument("--topics", type=Path, default=DEFAULT_TOPICS)
    parser.add_argument("--section-topics", type=Path, default=DEFAULT_SECTION_TOPICS)
    parser.add_argument("--builder", type=Path, default=DEFAULT_BUILDER)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    report = Report()
    sections = load_sections(args.sections)
    doc = json.loads(args.topics.read_text(encoding="utf-8"))
    topics = doc["topics"]
    meta = doc["meta"]
    index_doc = json.loads(args.index.read_text(encoding="utf-8"))
    constructions_doc = json.loads(args.constructions.read_text(encoding="utf-8"))
    index_greek_doc = json.loads(args.index_greek.read_text(encoding="utf-8"))

    # 1. every cited section exists
    missing = []
    for t in topics:
        for s in t["sections"]:
            if s["n"] not in sections:
                missing.append((t["slug"], s["n"]))
            if "to" in s and s["to"] not in sections:
                missing.append((t["slug"], s["to"]))
        for n in t["hub"]["hubSections"]:
            if n not in sections:
                missing.append((t["slug"], n))
        for a in t["anchors"]:
            if a["n"] not in sections:
                missing.append((t["slug"], a["n"]))
    cited = {s["n"] for t in topics for s in t["sections"]}
    report.add(
        1,
        not missing,
        "every cited section exists in sections.jsonl",
        f"topics={len(topics)}; distinct sections cited={len(cited)}; missing={short(missing)}",
    )

    # 2. ranges forward, no empty lists
    backwards = [
        (t["slug"], s) for t in topics for s in t["sections"] if "to" in s and s["to"] < s["n"]
    ]
    empty = [t["slug"] for t in topics if not t["sections"]]
    anchor_mismatch = [
        t["slug"]
        for t in topics
        if [(a["n"], a.get("to")) for a in t["anchors"]]
        != [(s["n"], s.get("to")) for s in t["sections"]]
    ]
    report.add(
        2,
        not backwards and not empty and not anchor_mismatch,
        "every range runs forwards, no topic is empty, anchors mirror sections",
        f"backwards={short(backwards)}; empty={short(empty)}; anchors off={short(anchor_mismatch)}",
    )

    # 3. slugs
    slugs = [t["slug"] for t in topics]
    dupes = sorted({s for s in slugs if slugs.count(s) > 1})
    bad_chars = [s for s in slugs if not (s and s.isascii() and s == s.lower() and " " not in s)]
    is_sorted = slugs == sorted(slugs)
    report.add(
        3,
        not dupes and not bad_chars and is_sorted,
        "slugs are unique, lowercase ASCII, and sorted",
        f"slugs={len(slugs)}; duplicates={short(dupes)}; bad={short(bad_chars)}; sorted={is_sorted}",
    )

    # 4. every index entry with section refs appears in some topic
    seeded = {}
    for t in topics:
        for e in t["provenance"]["indexEntries"]:
            seeded.setdefault((e["headword"], e["raw"]), []).append(t["slug"])
    aliased = {a for t in topics for a in t["aliases"]} | {t["name"] for t in topics}
    unseeded = []
    entries_with_refs = 0
    for entry in index_doc["entries"]:
        has_ref = any(
            isinstance(r.get("n"), int) and not r.get("nonSection") for r in index_refs(entry)
        )
        if not has_ref:
            continue
        entries_with_refs += 1
        if (entry["headword"].strip(), entry["raw"]) not in seeded:
            unseeded.append(entry["headword"])
    refless_unplaced = [
        entry["headword"]
        for entry in index_doc["entries"]
        if not any(isinstance(r.get("n"), int) for r in index_refs(entry))
        and entry["headword"].strip() not in aliased
    ]
    report.add(
        4,
        not unseeded,
        "every English index entry with section refs appears in some topic",
        f"index entries={len(index_doc['entries'])}; with refs={entries_with_refs}; "
        f"missing={short(unseeded)}\n"
        f"entries without refs and not placed as an alias (audited, not failed): "
        f"{short(refless_unplaced)}",
    )

    # 5. every non-prose construction appears in some topic
    kinds = set(meta["rules"]["constructionKinds"])
    placed = {
        (c["construction"], c["agdtContext"], c["contextKind"], c["sourceHeading"])
        for t in topics
        for c in t["provenance"]["constructions"]
    }
    unplaced = [
        e["construction"]
        for e in constructions_doc["entries"]
        if e["contextKind"] in kinds
        and (e["construction"], e["agdtContext"], e["contextKind"], e["sourceHeading"]) not in placed
    ]
    total_kinds = sum(1 for e in constructions_doc["entries"] if e["contextKind"] in kinds)
    report.add(
        5,
        not unplaced,
        f"every construction of kind {sorted(kinds)} appears in some topic",
        f"construction entries of those kinds={total_kinds}; placed={len(placed)}; "
        f"missing={short(unplaced)}",
    )

    # 6. sources
    known = {"index-english", "index-greek", "constructions", "hub"}
    bad_sources = []
    for t in topics:
        src = set(t["sources"])
        if not src or not src <= known:
            bad_sources.append((t["slug"], t["sources"]))
            continue
        if ("index-english" in src) != bool(t["provenance"]["indexEntries"]):
            bad_sources.append((t["slug"], "index provenance"))
        if ("constructions" in src) != bool(t["provenance"]["constructions"]):
            bad_sources.append((t["slug"], "construction provenance"))
        if ("index-greek" in src) != bool(t["provenance"].get("indexGreek")):
            bad_sources.append((t["slug"], "greek index provenance"))
        if ("hub" in src) != bool(t["hub"]["hubSections"]):
            bad_sources.append((t["slug"], "hub sections"))
        if "index-greek" in src and src - {"index-greek", "hub"}:
            bad_sources.append((t["slug"], "greek topic merged with another source"))
    report.add(
        6,
        not bad_sources,
        "every topic names its sources and the provenance agrees",
        f"offenders={short(bad_sources)}",
    )

    # 7. aliases and related
    slug_set = set(slugs)
    self_alias = [t["slug"] for t in topics if t["name"] in t["aliases"]]
    dup_alias = [t["slug"] for t in topics if len(set(t["aliases"])) != len(t["aliases"])]
    bad_related = [
        (t["slug"], r) for t in topics for r in t["related"] if r not in slug_set or r == t["slug"]
    ]
    report.add(
        7,
        not self_alias and not dup_alias and not bad_related,
        "aliases never repeat the name; related slugs resolve",
        f"self-alias={short(self_alias)}; duplicate alias={short(dup_alias)}; "
        f"bad related={short(bad_related)}",
    )

    # 8. hub threshold
    hub_min = meta["rules"]["hubMinSyntax"]
    syntax_part = meta["rules"]["syntaxPart"]
    weak = []
    for t in topics:
        for n in t["hub"]["hubSections"]:
            citers = set()
            for c in sections[n].get("citedBy", []):
                m = int(c.rsplit(":", 1)[1])
                if m != n and m in sections and sections[m]["path"][0] == syntax_part:
                    citers.add(m)
            if len(citers) < hub_min:
                weak.append((t["slug"], n, len(citers)))
    hub_sections = {n for t in topics for n in t["hub"]["hubSections"]}
    report.add(
        8,
        not weak,
        f"every hub section has at least {hub_min} inbound Part IV refs",
        f"hub sections={len(hub_sections)}; below threshold={short(weak)}",
    )

    # 9. meta counts
    counts = meta["counts"]
    expected = {
        "topics": len(topics),
        "withAliases": sum(1 for t in topics if t["aliases"]),
        "merged": sum(1 for t in topics if {"index-english", "constructions"} <= set(t["sources"])),
        "hubSections": len(hub_sections),
    }
    by_source = {k: sum(1 for t in topics if k in t["sources"]) for k in known}
    count_problems = [k for k, v in expected.items() if counts.get(k) != v]
    count_problems += [k for k, v in by_source.items() if counts["bySource"].get(k) != v]
    report.add(
        9,
        not count_problems,
        "meta counts agree with the topics array",
        f"topics={counts['topics']}; bySource={counts['bySource']}; merged={counts['merged']}; "
        f"withAliases={counts['withAliases']}; hubSections={counts['hubSections']}; "
        f"disagreements={short(count_problems)}",
    )

    # 10. determinism, both outputs
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "topics.json"
        out_sections = Path(tmp) / "section-topics.json"
        result = subprocess.run(
            [
                sys.executable,
                str(args.builder),
                "--sections",
                str(args.sections),
                "--index",
                str(args.index),
                "--constructions",
                str(args.constructions),
                "--index-greek",
                str(args.index_greek),
                "--out",
                str(out),
                "--out-sections",
                str(out_sections),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            det_ok, det_detail = False, f"builder exited {result.returncode}: {result.stderr}"
        else:
            differs = [
                name
                for name, fresh, committed in (
                    ("topics.json", out, args.topics),
                    ("section-topics.json", out_sections, args.section_topics),
                )
                if fresh.read_text(encoding="utf-8") != committed.read_text(encoding="utf-8")
            ]
            det_ok = not differs
            det_detail = (
                "fresh build identical to both committed files"
                if det_ok
                else f"fresh build differs from the committed {', '.join(differs)} "
                f"(rebuild and commit)"
            )
    report.add(
        10,
        det_ok,
        "re-running the builder reproduces topics.json and section-topics.json byte-for-byte",
        det_detail,
    )

    # 11. section-topics.json shape
    rev_doc = json.loads(args.section_topics.read_text(encoding="utf-8"))
    rows = rev_doc["sections"]
    rev_meta = rev_doc["meta"]
    row_numbers = [r["n"] for r in rows]
    covers_every_section = row_numbers == sorted(sections)
    unsorted_slugs = [r["n"] for r in rows if r["topics"] != sorted(r["topics"])]
    repeated_slugs = [r["n"] for r in rows if len(set(r["topics"])) != len(r["topics"])]
    unknown_slugs = sorted(
        {(r["n"], s) for r in rows for s in r["topics"] if s not in slug_set}
    )
    histogram = {}
    for row in rows:
        histogram[len(row["topics"])] = histogram.get(len(row["topics"]), 0) + 1
    declared = {d["topics"]: d["sections"] for d in rev_meta["counts"]["distribution"]}
    rev_counts_ok = (
        declared == histogram
        and rev_meta["counts"]["sections"] == len(rows)
        and rev_meta["counts"]["sectionsWithTopics"] == sum(1 for r in rows if r["topics"])
        and rev_meta["counts"]["sectionsWithoutTopics"] == sum(1 for r in rows if not r["topics"])
        and rev_meta["counts"]["assignments"] == sum(len(r["topics"]) for r in rows)
        and rev_meta["counts"]["maxTopicsOnASection"] == max(histogram)
    )
    buckets = ", ".join(
        f"{k} topic{'' if k == 1 else 's'}: {histogram.get(k, 0)}" for k in (0, 1, 2, 3)
    )
    top_ten = [
        f"{r['n']}={len(r['topics'])}"
        for r in sorted(rows, key=lambda r: (-len(r["topics"]), r["n"]))[:10]
    ]
    broadest = [f"{b['slug']}={b['sections']}" for b in rev_meta["broadestTopics"]]
    report.add(
        11,
        covers_every_section
        and not unsorted_slugs
        and not repeated_slugs
        and not unknown_slugs
        and rev_counts_ok,
        "section-topics.json has one sorted row per section and names only known slugs",
        f"rows={len(rows)}; covers every section={covers_every_section}; "
        f"unsorted={short(unsorted_slugs)}; repeated={short(repeated_slugs)}; "
        f"unknown slugs={short(unknown_slugs)}; meta counts agree={rev_counts_ok}\n"
        f"note, distribution: {buckets}, 4 or more topics: "
        f"{sum(v for k, v in histogram.items() if k >= 4)} "
        f"(mean {sum(len(r['topics']) for r in rows) / len(rows):.2f}, "
        f"max {max(histogram)})\n"
        f"note, most covered sections: {short(top_ten, 10)}\n"
        f"note, broadest topics: {short(broadest, 5)}",
    )

    # 12. the join agrees both ways
    forward: dict[int, set[str]] = {n: set() for n in sections}
    for t in topics:
        for s in t["sections"]:
            for n in range(s["n"], s.get("to", s["n"]) + 1):
                if n in forward:
                    forward[n].add(t["slug"])
    backward = {r["n"]: set(r["topics"]) for r in rows}
    missing_on_section = sorted(
        (n, s) for n in forward for s in forward[n] - backward.get(n, set())
    )
    extra_on_section = sorted(
        (n, s) for n in backward for s in backward[n] - forward.get(n, set())
    )
    report.add(
        12,
        not missing_on_section and not extra_on_section,
        "every section a topic covers names that topic, and every named topic covers it",
        f"assignments={sum(len(v) for v in forward.values())}; "
        f"claimed by a topic but absent from the section={short(missing_on_section)}; "
        f"named on the section but not claimed by the topic={short(extra_on_section)}",
    )

    # 13. every Greek index entry is seeded once or excluded by a stated rule
    greek_topics = [t for t in topics if "index-greek" in t["sources"]]
    seeded_greek: dict[tuple[str, str], list[str]] = {}
    for t in greek_topics:
        for e in t["provenance"]["indexGreek"]:
            seeded_greek.setdefault((e["headword"], e["raw"]), []).append(t["slug"])
    stray = [
        t["slug"]
        for t in topics
        if "index-greek" not in t["sources"] and t["provenance"].get("indexGreek")
    ]
    excluded_rules = meta["rules"]["greekExclusions"]
    excluded_letter, excluded_no_sections, unplaced_greek, twice = [], [], [], []
    for entry in index_greek_doc["entries"]:
        headword = entry["headword"].strip()
        key = (headword, entry["raw"])
        placed = seeded_greek.get(key, [])
        if is_alphabet_letter(headword):
            excluded_letter.append(headword)
            if placed:
                twice.append((headword, "excluded as a letter but seeded", placed))
            continue
        if not greek_entry_sections(entry, sections):
            excluded_no_sections.append(headword)
            if placed:
                twice.append((headword, "excluded for citing no section but seeded", placed))
            continue
        if not placed:
            unplaced_greek.append(headword)
        elif len(set(placed)) != 1:
            twice.append((headword, "seeded more than one topic", placed))
    declared_excluded = meta["counts"]["indexGreekEntriesExcluded"]
    entries_total = len(index_greek_doc["entries"])
    counts_add_up = (
        len(seeded_greek) + len(excluded_letter) + len(excluded_no_sections) == entries_total
        and declared_excluded.get("alphabet-letter") == len(excluded_letter)
        and declared_excluded.get("no-section-refs") == len(excluded_no_sections)
        and meta["counts"]["indexGreekEntriesSeeded"]
        == sum(len(t["provenance"]["indexGreek"]) for t in greek_topics)
        and meta["counts"]["indexGreekEntriesSeeded"] == len(seeded_greek)
        and set(excluded_rules) == {"alphabet-letter", "no-section-refs"}
    )
    report.add(
        13,
        not unplaced_greek and not twice and not stray and counts_add_up,
        "every Greek index entry seeds one topic or is excluded by a declared rule",
        f"greek entries={entries_total}; seeded={len(seeded_greek)} into "
        f"{len(greek_topics)} topics; excluded as a letter={len(excluded_letter)}; "
        f"excluded for citing no section={len(excluded_no_sections)}; counts add up="
        f"{counts_add_up}\n"
        f"unplaced={short(unplaced_greek)}; placed twice or wrongly={short(twice)}; "
        f"greek provenance on a non-greek topic={short(stray)}\n"
        f"note, letters excluded: {short(excluded_letter, 8)}\n"
        f"note, cross-reference entries excluded: {short(excluded_no_sections, 8)}",
    )

    # 14. every Greek topic's sections, name, alias and slug are re-derivable
    refs_by_key = {
        (e["headword"].strip(), e["raw"]): greek_entry_sections(e, sections)
        for e in index_greek_doc["entries"]
    }
    section_mismatch, name_wrong, alias_missing, slug_wrong = [], [], [], []
    by_headword: dict[str, list[str]] = {}
    all_slugs = {t["slug"] for t in topics}
    for t in greek_topics:
        from_index = sorted(
            {s for e in t["provenance"]["indexGreek"] for s in refs_by_key[(e["headword"], e["raw"])]}
        )
        got = sorted((s["n"], s.get("to", s["n"])) for s in t["sections"])
        if got != from_index:
            section_mismatch.append(t["slug"])
        heads = {e["headword"] for e in t["provenance"]["indexGreek"]}
        if heads != {t["name"]}:
            name_wrong.append(t["slug"])
        by_headword.setdefault(t["name"], []).append(t["slug"])
        base = transliterate(head_form(t["name"]))
        if base not in {transliterate(a) for a in t["aliases"]}:
            alias_missing.append((t["slug"], base))
        qualified = f"{base}-{t['sections'][0]['n']}"
        if t["slug"] != base and not t["slug"].startswith(qualified):
            slug_wrong.append((t["slug"], base))
        if t["slug"] != base and base not in all_slugs:
            slug_wrong.append((t["slug"], f"{base} was free"))
    split = [(h, s) for h, s in by_headword.items() if len(s) > 1]
    report.add(
        14,
        not section_mismatch
        and not name_wrong
        and not alias_missing
        and not slug_wrong
        and not split,
        "every Greek topic covers the sections its entries cite and follows the slug rule",
        f"greek topics={len(greek_topics)}; sections wrong={short(section_mismatch)}; "
        f"name not the printed headword={short(name_wrong)}; "
        f"transliteration not the first alias={short(alias_missing)}; "
        f"slug off the rule={short(slug_wrong)}; one headword split over topics={short(split)}\n"
        f"note, slugs qualified by a section number: "
        f"{sum(1 for t in greek_topics if t['slug'] != transliterate(head_form(t['name'])))}",
    )

    # 15. every English and construction topic covers the sections its own
    # provenance cites, and is named by one of them.
    #
    # Check 14 does this for the 1,418 Greek topics.  Nothing did it for the
    # other 830.  Check 4 asks only that an index entry appear in SOME topic,
    # check 5 the same for a construction, and check 6 asks that the sources
    # list and the provenance agree about which kinds are present, never
    # about which sections they carry.  Check 12's two-way join is derived
    # from the topic's own section list, so it agrees with whatever that list
    # says.  A topic could therefore cover a section none of its entries
    # cites, or drop one they all do, and every check would report PASS.
    seed_wrong: list[object] = []
    seed_checked = 0
    entries_by_key = {
        (entry["headword"].strip(), entry["raw"]): entry
        for entry in index_doc["entries"]
    }
    constructions_by_key = {
        (item["construction"], item["agdtContext"], item["contextKind"],
         item["sourceHeading"]): item
        for item in constructions_doc["entries"]
    }
    for topic in topics:
        if not {"index-english", "constructions"} & set(topic["sources"]):
            continue
        seed_checked += 1
        cited_by_seeds: set[tuple[int, int]] = set()
        names: set[str] = set()
        for seed in topic["provenance"]["indexEntries"]:
            entry = entries_by_key.get((seed["headword"], seed["raw"]))
            if entry is None:
                seed_wrong.append((topic["slug"], "index entry not in the index"))
                continue
            names.add(entry["headword"].strip().lower())
            for ref in index_refs(entry):
                if isinstance(ref.get("n"), int) and not ref.get("nonSection"):
                    cited_by_seeds.add((ref["n"], ref.get("to", ref["n"])))
        for seed in topic["provenance"]["constructions"]:
            item = constructions_by_key.get(
                (seed["construction"], seed["agdtContext"], seed["contextKind"],
                 seed["sourceHeading"]))
            if item is None:
                seed_wrong.append(
                    (topic["slug"], "construction not in constructions.json"))
                continue
            names.add(str(seed["construction"]).lower())
            for span in item.get("sections", []):
                cited_by_seeds.add((span["n"], span.get("to", span["n"])))
        covered = {(span["n"], span.get("to", span["n"]))
                   for span in topic["sections"]}
        if covered != cited_by_seeds:
            seed_wrong.append(
                (topic["slug"], "cited but not covered",
                 sorted(cited_by_seeds - covered)[:3],
                 "covered but not cited", sorted(covered - cited_by_seeds)[:3]))
        if topic["name"].strip().lower() not in names:
            seed_wrong.append(
                (topic["slug"], "name", topic["name"], sorted(names)[:3]))
    report.add(
        15,
        not seed_wrong,
        "every English and construction topic covers the sections its own "
        "provenance cites, and is named by one of them",
        f"topics checked={seed_checked}; offenders={short(seed_wrong)}",
    )

    print(
        f"\ntopics {len(topics)}  index-english {by_source['index-english']}  "
        f"index-greek {by_source['index-greek']}  "
        f"constructions {by_source['constructions']}  hub {by_source['hub']}  "
        f"merged {expected['merged']}  aliases {sum(len(t['aliases']) for t in topics)}  "
        f"sections cited {len(cited)}  hub sections {len(hub_sections)}\n"
        f"sections {len(rows)}  with a topic {sum(1 for r in rows if r['topics'])}  "
        f"without {sum(1 for r in rows if not r['topics'])}  "
        f"assignments {sum(len(r['topics']) for r in rows)}"
    )
    return 0 if report.summary() else 1


if __name__ == "__main__":
    raise SystemExit(main())
