#!/usr/bin/env python3
"""Verify data/goodell/index-english.json against its DCC source.

Checks (stdlib only, in the manner of verify_index_english.py):

1. the committed JSON is exactly what build_index_goodell.py derives from
   grammar-goodell/src/dcc/english-index.html — no drift;
2. entry invariants the site's facet parser depends on: every headword is
   a literal prefix of its entry's raw text, and every ref's verbatim
   locates in the raw text left to right;
2b. source coverage, independent of the parser (the Codex-review class
   of defect the drift check is structurally blind to): every digit run
   in an entry's raw text must be accounted for by its refs' verbatims,
   no two adjacent single-§ refs may straddle a bare range dash, and a
   mid-entry "; Capitalized," clause that sorts between this headword
   and the next is flagged as a possible fused entry;
3. every `n` and `to` cites a section that exists in sections.jsonl
   (1-683), and every range runs forward;
4. the DCC links agree with our own conversion: each citation's href
   names the chapter page whose sourceSlug carries that section, and a
   numeric fragment decodes to the ref's own section number;
5. entries are alphabetical to the print's tolerance, and the first
   letters match the index's own A-X navigation line;
6. cross-references ("see Accent") resolve to another entry's headword;
7. a seeded QA sample: the cited section's text should mention the
   headword — misses are suspects to look at, never verdicts.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path

import build_index_goodell as big

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "goodell"
ORDER_TOLERANCE = 6

failures: list[str] = []
warnings: list[str] = []


def check(ok: bool, message: str) -> None:
    if not ok:
        failures.append(message)


def load_sections() -> dict[int, dict]:
    sections = {}
    with open(DATA / "sections.jsonl", encoding="utf-8") as f:
        for line in f:
            record = json.loads(line)
            sections[record["n"]] = record
    return sections


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=int, default=30)
    parser.add_argument("--seed", type=int, default=683)
    args = parser.parse_args()

    committed = json.loads((DATA / "index-english.json").read_text(encoding="utf-8"))
    derived = big.extract()
    sections = load_sections()

    # 1. no drift
    check(big.strip_internal(json.loads(json.dumps(derived))) == committed,
          "committed JSON differs from what the source derives — rerun "
          "scripts/build_index_goodell.py")

    entries = derived["entries"]
    check(len(entries) == committed["_meta"]["entryCount"],
          "entryCount does not match the entries")

    link_mismatches = 0
    for entry in entries:
        raw, headword = entry["raw"], entry["headword"]
        # 2. facet-parser contract
        check(raw.startswith(headword),
              f"{headword!r}: raw does not start with the headword")
        offset = 0
        for ref in entry["refs"]:
            at = raw.find(ref["verbatim"], offset)
            check(at != -1,
                  f"{headword!r}: ref {ref['verbatim']!r} not locatable in order")
            if at != -1:
                offset = at + len(ref["verbatim"])
            # 3. citations exist
            for key in ("n", "to"):
                n = ref.get(key)
                if n is not None:
                    check(n in sections,
                          f"{headword!r}: {ref['verbatim']!r} cites missing §{n}")
            if "to" in ref:
                check(ref["n"] < ref["to"],
                      f"{headword!r}: backwards range {ref['verbatim']!r}")
            # 4. DCC links vs our conversion
            n = ref.get("n")
            slug = ref.get("_slug")
            if n is not None and n in sections and slug:
                ours = sections[n]["sourceSlug"]
                if slug != ours:
                    link_mismatches += 1
                    warnings.append(
                        f"{headword!r}: DCC links {ref['verbatim']!r} to "
                        f"{slug!r}, our §{n} sits in {ours!r}")
            frag = ref.get("_fragment_n")
            if n is not None and frag is not None and frag != n:
                warnings.append(
                    f"{headword!r}: fragment decodes to {frag}, ref says {n}")

    # 2c. every ref is the reference its own verbatim writes.
    #
    # Check 2 asks that a verbatim be findable in the raw text, left to
    # right.  Check 2b asks that the entry's digit runs and its refs' digit
    # runs be the same multiset.  Check 3 asks that the cited section exist.
    # None of the three ties a ref's n to the verbatim standing beside it, so
    # two refs of one entry can swap their numbers and pass all three: the
    # verbatims are still findable in order, the multiset of digits is
    # unchanged, and both sections exist.
    #
    # This ties them.  The first number the verbatim writes is n, the last is
    # "to" wherever a range was read, an anchor the build did not mark
    # inherited is written there too, and a ref the build did mark inherited
    # takes the n of the last ref that was not ("93.b" then a bare "c" is
    # §93 anchor c).
    for entry in entries:
        carried = None
        for ref in entry["refs"]:
            verbatim = ref.get("verbatim", "")
            written = re.findall(r"\d+", verbatim)
            head = entry["headword"]
            if ref.get("inherited"):
                check(ref.get("n") == carried,
                      f"{head!r}: {verbatim!r} inherits {ref.get('n')}, but "
                      f"the ref before it is {carried}")
                continue
            anchor = ref.get("anchor")
            if anchor is not None:
                check(str(anchor) in verbatim,
                      f"{head!r}: anchor {anchor!r} is not written in "
                      f"{verbatim!r}")
            if ref.get("n") is not None:
                carried = ref["n"]
                check(bool(written) and written[0] == str(ref["n"]),
                      f"{head!r}: {verbatim!r} does not write {ref['n']}")
            if ref.get("to") is not None:
                check(len(written) >= 2 and written[-1] == str(ref["to"]),
                      f"{head!r}: {verbatim!r} does not write the range end "
                      f"{ref['to']}")

    # 2b. source coverage, independent of the parser
    for i, entry in enumerate(entries):
        raw_digits = re.findall(r"\d+", entry["raw"])
        ref_digits = [d for r in entry["refs"]
                      for d in re.findall(r"\d+", r["verbatim"])]
        check(sorted(raw_digits) == sorted(ref_digits),
              f"{entry['headword']!r}: numerals in raw {raw_digits} are not "
              f"the refs' numerals {ref_digits} — a citation was dropped or "
              "invented")
        singles = [r for r in entry["refs"]
                   if r.get("n") is not None and "to" not in r]
        for a, b in zip(entry["refs"], entry["refs"][1:]):
            if a in singles and b in singles and "anchor" not in a and "anchor" not in b:
                pa = entry["raw"].find(a["verbatim"])
                pb = entry["raw"].find(b["verbatim"], pa + len(a["verbatim"]))
                if pa != -1 and pb != -1:
                    gap = entry["raw"][pa + len(a["verbatim"]):pb].strip()
                    check(gap not in {"-", "–"},
                          f"{entry['headword']!r}: {a['verbatim']} {gap} "
                          f"{b['verbatim']} is an unjoined printed range")
        nxt = entries[i + 1]["headword"] if i + 1 < len(entries) else None
        for m in re.finditer(r"; ([A-Z][A-Za-zΐ-ῼ]+),", entry["raw"]):
            word = m.group(1)
            if (word.lower() > entry["headword"].lower()
                    and (nxt is None or word.lower() < nxt.lower())):
                warnings.append(
                    f"{entry['headword']!r}: mid-entry clause {word!r} sorts "
                    "between this entry and the next — possible fused entry")

    # 5. order and letter coverage
    def sort_key(headword: str) -> str:
        return re.sub(r"[^a-z]", "", headword.lower())

    descents = [
        (a["headword"], b["headword"])
        for a, b in zip(entries, entries[1:])
        if sort_key(a["headword"]) > sort_key(b["headword"])
    ]
    check(len(descents) <= ORDER_TOLERANCE,
          f"{len(descents)} alphabetical descents (tolerance {ORDER_TOLERANCE}): "
          f"{descents}")
    letters = {e["headword"][0].upper() for e in entries}
    nav = set("ABCDEFGHILMNOPQRSTVWX")
    check(letters == nav,
          f"first letters {sorted(letters)} do not match the A-X navigation "
          f"{sorted(nav)}")

    # 6. cross-references resolve
    headwords = {e["headword"].lower() for e in entries}
    for entry in entries:
        for target in entry.get("crossRefs", []):
            t = target.lower().rstrip(".")
            hits = [h for h in headwords
                    if h == t or h.startswith(t.split(" of ")[0])]
            if not hits:
                warnings.append(
                    f"{entry['headword']!r}: cross-ref {target!r} resolves to "
                    "no entry")

    # 7. seeded QA sample
    rng = random.Random(args.seed)
    cited = [(e, r) for e in entries for r in e["refs"] if r.get("n") in sections]
    suspects = []
    for entry, ref in rng.sample(cited, min(args.sample, len(cited))):
        stem = re.sub(r"[^a-z]", "", entry["headword"].split()[0].lower())[:6]
        span = range(ref["n"], ref.get("to", ref["n"]) + 1)
        # The section's own title counts: Goodell's "Liquids" entry cites
        # a section headed "Liquids" whose body never repeats the word.
        text = " ".join(
            (sections[n]["plain"] + " " + (sections[n].get("head") or "")).lower()
            for n in span if n in sections)
        if stem and stem not in text:
            suspects.append(f"{entry['headword']!r} at §{ref['n']}")
    if suspects:
        warnings.append(f"QA sample suspects ({len(suspects)}/{args.sample}): "
                        + "; ".join(suspects))

    for message in warnings:
        print(f"WARN: {message}")
    if link_mismatches:
        print(f"WARN: {link_mismatches} DCC link targets disagree with our "
              "conversion (listed above)")
    if failures:
        for message in failures:
            print(f"FAIL: {message}")
        print(f"\n{len(failures)} failures")
        return 1
    print(f"\nall checks pass: {len(entries)} entries, "
          f"{committed['_meta']['refCount']} refs, "
          f"{len(warnings)} warnings")
    return 0


if __name__ == "__main__":
    sys.exit(main())
