#!/usr/bin/env python3
"""Independently verify data/smyth/crosswalk.json and print a full report.

Checks the cross-grammar crosswalk against data/smyth/topics.json, every
work's sections.jsonl and a fresh re-run of scripts/build_crosswalk.py.
Python stdlib only.

  1  one record per topic in topics.json that the Greek index did not seed,
     in the same order, with the same Smyth sections, and no record for a
     topic it did seed (meta.inputs.topicsScope says why)
  2  every candidate section exists in its work, ranges run forwards with
     no gap, and the work is one the file declares
  3  every candidate clears the declared threshold, at most maxPerWork per
     work, sorted best first, and every piece of evidence names a section
     of the candidate
  4  Latin candidates carry heading evidence only, exact and at 1.0
  5  citation evidence points at Smyth sections inside the topic
  6  every topic with a hub anchor in Part IV Syntax has a candidate in
     some other Greek grammar or is listed in meta.audit.uncovered
  7  meta counts agree with the topics array
  8  sampled QA: 40 candidates at random (a fixed seed hashed with each
     candidate's identity, so the sample survives small changes to the
     file), printed with the topic name, the Smyth anchor head and the
     candidate's head, so a person can read them; --sample-texts prints
     the section texts too. The count a person judged right is recorded
     in SPEC-crosswalk.md
  9  determinism: a fresh build is byte-identical to the committed file
 10  the heads a reader sees are the sections' own heads, the heading
     evidence quotes the topic's own name and the candidate's own head,
     the Goodell-index evidence names an entry that stands in that index
     and cites the sections it claims, and a citation chain runs through
     sections that exist and quotes text the candidate has

Exit status is non-zero if any check FAILs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DEFAULT_TOPICS = DATA / "smyth" / "topics.json"
DEFAULT_CROSSWALK = DATA / "smyth" / "crosswalk.json"
DEFAULT_BUILDER = ROOT / "scripts" / "build_crosswalk.py"
SAMPLE_SEED = 20260907
SAMPLE_SIZE = 40
SYNTAX_PART = "Part IV: Syntax"


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


def load_sections(work: str) -> dict[int, dict]:
    rows: dict[int, dict] = {}
    with (DATA / work / "sections.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                row = json.loads(line)
                if isinstance(row.get("n"), int):
                    rows[row["n"]] = row
    return rows


def short(items: list, limit: int = 8) -> str:
    text = ", ".join(str(i) for i in items[:limit])
    if len(items) > limit:
        text += f" (+{len(items) - limit} more)"
    return text


def span(sections: list[dict]) -> str:
    s = sections[0]
    return f"§{s['n']}" if "to" not in s else f"§§{s['n']}-{s['to']}"


def expand(entries: list[dict]) -> list[int]:
    out = []
    for e in entries:
        out.extend(range(e["n"], e.get("to", e["n"]) + 1))
    return out


def evidence_line(ev: dict) -> str:
    kind = ev["kind"]
    if kind == "heading":
        where = "ancestor" if ev.get("ancestor") else "head"
        return f"heading {ev['score']}: {ev['topicString']!r} ~ {ev['sectionString']!r} ({where}; shared {', '.join(ev['matched'])})"
    if kind == "greek-terms":
        via = f"Smyth §{ev['smythSections'][0]}" if ev.get("smythSections") else "pooled"
        return (
            f"greek-terms {ev['score']}: cosine {ev['cosine']} ({via}; {ev['sharedTerms']} shared, "
            f"idf {ev['sharedIdf']}): {' '.join(ev['terms'][:8])}"
        )
    if kind == "goodell-index":
        return f"goodell-index {ev['score']}: {ev['headword']!r} = {ev['topicString']!r}; {ev['raw'][:80]!r}"
    if kind == "citation-chain":
        return f"citation-chain {ev['score']}: via {', '.join(ev['via'])}: {'; '.join(ev['matched'])!r}"
    return f"{kind} {ev['score']}: Smyth {ev.get('smythSections')}: {'; '.join(ev.get('matched', []))!r}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topics", type=Path, default=DEFAULT_TOPICS)
    parser.add_argument("--crosswalk", type=Path, default=DEFAULT_CROSSWALK)
    parser.add_argument("--builder", type=Path, default=DEFAULT_BUILDER)
    parser.add_argument("--sample-texts", action="store_true", help="print section texts for the QA sample")
    parser.add_argument("--text-chars", type=int, default=700)
    parser.add_argument("--skip-determinism", action="store_true")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    report = Report()
    doc = json.loads(args.crosswalk.read_text(encoding="utf-8"))
    meta = doc["meta"]
    records = doc["topics"]
    topics_doc = json.loads(args.topics.read_text(encoding="utf-8"))
    topics = topics_doc["topics"]
    greek_works = meta["works"]["greek"]
    latin_works = meta["works"]["latin"]
    all_works = greek_works + latin_works
    sections = {w: load_sections(w) for w in ["smyth"] + all_works}
    smyth = sections["smyth"]

    # 1. one record per in-scope topic, same order, same sections
    topic_by_slug = {t["slug"]: t for t in topics}
    in_scope = [t for t in topics if "index-greek" not in t["sources"]]
    out_of_scope = [t["slug"] for t in topics if "index-greek" in t["sources"]]
    order_ok = [r["slug"] for r in records] == [t["slug"] for t in in_scope]
    greek_present = sorted({r["slug"] for r in records} & set(out_of_scope))
    mismatched = [
        r["slug"]
        for r in records
        if r["slug"] in topic_by_slug
        and (
            r["smyth"] != topic_by_slug[r["slug"]]["sections"]
            or r["name"] != topic_by_slug[r["slug"]]["name"]
            or r["aliases"] != topic_by_slug[r["slug"]]["aliases"]
        )
    ]
    report.add(
        1,
        order_ok and not mismatched and not greek_present,
        "one record per topic the Greek index did not seed, same order, same name, "
        "aliases and Smyth sections",
        f"records={len(records)}; topics={len(topics)}; in scope={len(in_scope)}; "
        f"seeded by the Greek index and out of scope={len(out_of_scope)}; order={order_ok}; "
        f"mismatched={short(mismatched)}; greek topics with a record={short(greek_present)}",
    )

    # 2. sections exist, ranges forward and gap-free, work declared
    missing = []
    bad_work = []
    backwards = []
    candidates = 0
    for r in records:
        for c in r["candidates"]:
            candidates += 1
            if c["work"] not in all_works:
                bad_work.append((r["slug"], c["work"]))
                continue
            rows = sections[c["work"]]
            for s in c["sections"]:
                if "to" in s and s["to"] < s["n"]:
                    backwards.append((r["slug"], c["work"], s))
                for n in range(s["n"], s.get("to", s["n"]) + 1):
                    if n not in rows:
                        missing.append((r["slug"], c["work"], n))
    report.add(
        2,
        not missing and not bad_work and not backwards,
        "every candidate section exists in its work; ranges forward and gap-free; works declared",
        f"candidates={candidates}; missing={short(missing)}; undeclared work={short(bad_work)}; "
        f"backwards={short(backwards)}",
    )

    # 3. threshold, cap, order, evidence sections
    keep_min = meta["rules"]["keepMin"]
    max_per_work = meta["rules"]["maxPerWork"]
    below = []
    over_cap = []
    unsorted = []
    stray_evidence = []
    for r in records:
        per_work: dict[str, list[dict]] = {}
        for c in r["candidates"]:
            per_work.setdefault(c["work"], []).append(c)
            if c["score"] < keep_min:
                below.append((r["slug"], c["work"], span(c["sections"]), c["score"]))
            members = set(expand(c["sections"]))
            for ev in c["evidence"]:
                if not ev["sections"] or not set(ev["sections"]) <= members:
                    stray_evidence.append((r["slug"], c["work"], span(c["sections"]), ev["kind"]))
            if sorted(c["evidenceKinds"]) != sorted({e["kind"] for e in c["evidence"]}):
                stray_evidence.append((r["slug"], c["work"], span(c["sections"]), "evidenceKinds"))
        for work, cs in per_work.items():
            if len(cs) > max_per_work:
                over_cap.append((r["slug"], work, len(cs)))
            scores = [c["score"] for c in cs]
            if scores != sorted(scores, reverse=True):
                unsorted.append((r["slug"], work))
        works_seen = [c["work"] for c in r["candidates"]]
        if works_seen != sorted(works_seen, key=all_works.index):
            unsorted.append((r["slug"], "work order"))
    report.add(
        3,
        not below and not over_cap and not unsorted and not stray_evidence,
        f"every candidate scores at least {keep_min}, at most {max_per_work} per work, best first; "
        "evidence names sections of the candidate",
        f"below threshold={short(below)}; over cap={short(over_cap)}; unsorted={short(unsorted)}; "
        f"stray evidence={short(stray_evidence)}",
    )

    # 4. Latin: heading only, exact
    latin_bad = []
    latin_count = 0
    for r in records:
        for c in r["candidates"]:
            if c["work"] not in latin_works:
                continue
            latin_count += 1
            kinds = {e["kind"] for e in c["evidence"]}
            if kinds != {"heading"} or any(e["score"] != 1.0 or e.get("ancestor") for e in c["evidence"]):
                latin_bad.append((r["slug"], c["work"], span(c["sections"]), sorted(kinds)))
    report.add(
        4,
        not latin_bad,
        "Latin candidates carry exact heading evidence only",
        f"latin candidates={latin_count}; offenders={short(latin_bad)}",
    )

    # 5. citation evidence points inside the topic
    cite_bad = []
    cite_count = 0
    for r in records:
        members = set(expand(r["smyth"]))
        for c in r["candidates"]:
            for ev in c["evidence"]:
                if ev["kind"] in ("cites-smyth", "cited-by-smyth"):
                    cite_count += 1
                    if not ev["smythSections"] or not set(ev["smythSections"]) <= members:
                        cite_bad.append((r["slug"], c["work"], span(c["sections"])))
                    for m in ev["smythSections"]:
                        if m not in smyth:
                            cite_bad.append((r["slug"], "smyth", m))
    report.add(
        5,
        not cite_bad,
        "citation evidence names Smyth sections inside the topic",
        f"citation evidence={cite_count}; offenders={short(cite_bad)}",
    )

    # 6. syntax hub coverage
    uncovered_listed = {u["slug"] for u in meta["audit"]["uncovered"]}
    hub_topics = 0
    unlisted = []
    wrongly_listed = []
    for r in records:
        t = topic_by_slug.get(r["slug"])
        if t is None:
            continue
        syntax_hub = [
            a["n"]
            for a in t["anchors"]
            if a["n"] in t["hub"]["hubSections"] and a["path"][0] == SYNTAX_PART
        ]
        has_greek = any(c["work"] in greek_works for c in r["candidates"])
        if syntax_hub:
            hub_topics += 1
            if not has_greek and r["slug"] not in uncovered_listed:
                unlisted.append(r["slug"])
        if r["slug"] in uncovered_listed and (has_greek or not syntax_hub):
            wrongly_listed.append(r["slug"])
    report.add(
        6,
        not unlisted and not wrongly_listed,
        "every topic with a hub anchor in Part IV Syntax has a Greek-grammar candidate or is audited as uncovered",
        f"topics with a Part IV hub anchor={hub_topics}; audited uncovered={len(uncovered_listed)}; "
        f"unlisted={short(unlisted)}; listed but covered={short(wrongly_listed)}",
    )

    # 7. meta counts
    counts = meta["counts"]
    by_work = {w: sum(1 for r in records for c in r["candidates"] if c["work"] == w) for w in all_works}
    by_kind: dict[str, int] = {}
    for r in records:
        for c in r["candidates"]:
            for k in c["evidenceKinds"]:
                by_kind[k] = by_kind.get(k, 0) + 1
    expected = {
        "topics": len(records),
        "topicsWithCandidates": sum(1 for r in records if r["candidates"]),
        "topicsWithGreekCandidates": sum(
            1 for r in records if any(c["work"] in greek_works for c in r["candidates"])
        ),
        "candidates": candidates,
    }
    problems = [k for k, v in expected.items() if counts.get(k) != v]
    if counts.get("byWork") != by_work:
        problems.append("byWork")
    if counts.get("byEvidenceKind") != dict(sorted(by_kind.items())):
        problems.append("byEvidenceKind")
    report.add(
        7,
        not problems,
        "meta counts agree with the topics array",
        f"topics={counts['topics']}; with Greek candidates={counts['topicsWithGreekCandidates']}; "
        f"candidates={counts['candidates']}; byWork={counts['byWork']}; "
        f"byEvidenceKind={counts['byEvidenceKind']}; disagreements={short(problems)}",
    )

    # 8. sampled QA
    pairs = [(r, c) for r in records for c in r["candidates"]]

    def sample_key(pair: tuple[dict, dict]) -> str:
        r, c = pair
        ident = f"{SAMPLE_SEED}:{r['slug']}:{c['work']}:{c['sections'][0]['n']}"
        return hashlib.sha1(ident.encode("utf-8")).hexdigest()

    sample = sorted(pairs, key=sample_key)[:SAMPLE_SIZE]
    lines = [
        f"seed={SAMPLE_SEED}; the {len(sample)} of {len(pairs)} candidates with the smallest "
        "sha1(seed:slug:work:first section). A person reads each pair and counts the ones that "
        "treat the same phenomenon; the count is recorded in SPEC-crosswalk.md."
    ]
    for i, (r, c) in enumerate(sample, 1):
        t = topic_by_slug[r["slug"]]
        cited = sorted({m for e in c["evidence"] for m in e.get("smythSections", []) if m in smyth})
        # The Smyth side: the anchor sections the evidence names, else the
        # topic's own anchors (heading and index evidence name none).
        anchor_ns = cited or [a["n"] for a in t["anchors"]]
        anchor_desc = "; ".join(f"§{n} {smyth[n]['head']}" for n in anchor_ns[:3])
        if len(anchor_ns) > 3:
            anchor_desc += f" (+{len(anchor_ns) - 3} anchors)"
        lines.append(
            f"{i:2}. {r['name']!r} [{r['slug']}] Smyth {anchor_desc} -> "
            f"{c['label']} {span(c['sections'])} {c['heads'][0]!r} score {c['score']}"
        )
        for ev in c["evidence"][:3]:
            lines.append(f"      {evidence_line(ev)}")
        if args.sample_texts:
            for n in anchor_ns[:2]:
                lines.append(f"      SMYTH §{n}: {smyth[n]['plain'][: args.text_chars]}")
            rows = sections[c["work"]]
            first = c["sections"][0]["n"]
            shown = [first] + [n for n in expand(c["sections"]) if n != first][:1]
            for n in shown:
                lines.append(f"      {c['label'].upper()} §{n}: {rows[n]['plain'][: args.text_chars]}")
    report.add(8, True, f"sampled QA: {len(sample)} candidates for a person to read", "\n".join(lines))

    # 9. determinism
    if args.skip_determinism:
        report.add(9, True, "determinism check skipped (--skip-determinism)")
    else:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "crosswalk.json"
            result = subprocess.run(
                [sys.executable, str(args.builder), "--topics", str(args.topics), "--out", str(out)],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                det_ok, det_detail = False, f"builder exited {result.returncode}: {result.stderr}"
            else:
                det_ok = out.read_text(encoding="utf-8") == args.crosswalk.read_text(encoding="utf-8")
                det_detail = (
                    "fresh build identical to the committed file"
                    if det_ok
                    else "fresh build differs from the committed file (rebuild and commit)"
                )
        report.add(9, det_ok, "re-running the builder reproduces crosswalk.json byte-for-byte", det_detail)

    # 10. the heads and the evidence say what the grammars say.
    #
    # Checks 1 to 7 are structure and arithmetic: a section exists, a range
    # runs forwards, a score clears a threshold, a list is sorted, a count
    # agrees. Check 3 asks that a piece of evidence name sections OF the
    # candidate, never that it say anything true about them. Check 8 prints
    # 40 candidates for a person to read and always passes. So the heads the
    # reader sees beside a candidate, the strings the heading evidence
    # quotes, the Goodell entry the index evidence names and the sections a
    # citation chain runs through were all unchecked.
    #
    # This check reads them against the grammars themselves. A candidate's
    # "heads" are the distinct heads of the sections it covers, in order; a
    # topic's "smythHeads" are the head of each span it lists. A piece of
    # heading evidence quotes the topic's own name or one of its aliases, and
    # quotes a head of the candidate, or one of its path ancestors where the
    # evidence says ancestor. Goodell-index evidence names an entry that
    # stands in data/goodell/index-english.json with that exact printed line,
    # and every section it claims is a section that entry cites. A citation
    # chain runs through sections that exist, and the strings it says it
    # matched stand in the candidate's own text.
    #
    # Not checked, and recorded rather than guessed at: the "matched" tokens
    # of heading evidence are the builder's own stemmed and transliterated
    # forms ("amphi" for ἀμφί, "clause" for "clauses"), so testing them
    # against the two quoted strings would mean writing the builder's
    # tokenizer a second time. 75 of the 934 would fail such a test while
    # being right.
    heads_wrong: list[object] = []
    evidence_wrong: list[object] = []
    heading_seen = index_seen = chain_seen = 0
    goodell_index_path = DATA / "goodell" / "index-english.json"
    goodell_entries: dict[str, dict] = {}
    if goodell_index_path.exists():
        goodell_entries = {
            entry["headword"]: entry for entry in
            json.loads(goodell_index_path.read_text(encoding="utf-8"))["entries"]
        }

    def fold(value: str) -> str:
        nfd = unicodedata.normalize("NFD", (value or "").lower())
        return "".join(ch for ch in nfd if not unicodedata.combining(ch))

    for r in records:
        listed = [smyth[s["n"]].get("head") for s in r["smyth"] if s["n"] in smyth]
        if r["smythHeads"] != listed:
            heads_wrong.append((r["slug"], "smythHeads"))
        strings = {r["name"], *r["aliases"]}
        for c in r["candidates"]:
            table = sections.get(c["work"], {})
            rows = [table[n] for n in expand(c["sections"]) if n in table]
            distinct: list[str] = []
            for row in rows:
                if row.get("head") not in distinct:
                    distinct.append(row.get("head"))
            if c["heads"] != distinct:
                heads_wrong.append((r["slug"], c["work"], c["heads"][:2], distinct[:2]))
            head_set = {row.get("head") for row in rows}
            path_set = {step for row in rows for step in (row.get("path") or [])}
            body = " ".join(fold(row.get("plain")) for row in rows)
            for ev in c["evidence"]:
                if ev["kind"] == "heading":
                    heading_seen += 1
                    if ev["topicString"] not in strings:
                        evidence_wrong.append(
                            (r["slug"], "heading quotes a name the topic does "
                             "not carry", ev["topicString"]))
                    pool = path_set if ev.get("ancestor") else head_set
                    if ev["sectionString"] not in pool:
                        evidence_wrong.append(
                            (r["slug"], c["work"], "heading quotes a head the "
                             "candidate does not have", ev["sectionString"]))
                elif ev["kind"] == "goodell-index":
                    index_seen += 1
                    entry = goodell_entries.get(ev["headword"])
                    if entry is None or entry["raw"] != ev["raw"]:
                        evidence_wrong.append(
                            (r["slug"], "Goodell entry not in the index",
                             ev["headword"]))
                        continue
                    cited: set[int] = set()
                    for ref in entry["refs"]:
                        if isinstance(ref.get("n"), int):
                            cited.update(range(ref["n"],
                                               ref.get("to", ref["n"]) + 1))
                    outside = sorted(set(ev["sections"]) - cited)
                    if outside:
                        evidence_wrong.append(
                            (r["slug"], "Goodell entry does not cite",
                             outside[:4]))
                elif ev["kind"] == "citation-chain":
                    chain_seen += 1
                    for via in ev.get("via", []):
                        work_name, _, number = via.partition(":")
                        table_via = sections.get(work_name, {})
                        if not number.isdigit() or int(number) not in table_via:
                            evidence_wrong.append(
                                (r["slug"], "chain runs through a section that "
                                 "does not exist", via))
                    for quoted in ev.get("matched", []):
                        if fold(quoted) not in body:
                            evidence_wrong.append(
                                (r["slug"], c["work"], "chain quotes text the "
                                 "candidate does not have", quoted))
    report.add(
        10,
        not heads_wrong and not evidence_wrong,
        "the heads and the evidence say what the grammars say",
        f"candidates={candidates}; heading evidence={heading_seen}; "
        f"Goodell-index evidence={index_seen}; citation chains={chain_seen}\n"
        f"heads that are not the sections' own={short(heads_wrong)}\n"
        f"evidence the grammars do not bear out={short(evidence_wrong)}",
    )

    print(
        f"\ntopics {len(records)}  with candidates {expected['topicsWithCandidates']}  "
        f"with Greek candidates {expected['topicsWithGreekCandidates']}  candidates {candidates}  "
        f"byWork {by_work}  uncovered syntax hubs {len(uncovered_listed)}"
    )
    return 0 if report.summary() else 1


if __name__ == "__main__":
    raise SystemExit(main())
