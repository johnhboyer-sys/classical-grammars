#!/usr/bin/env python3
"""Verify data/smyth/constructions.json against sections.jsonl and the builder.

Runs build_constructions.py twice and requires byte-identical output, so it
rewrites data/smyth/constructions.json in place (idempotently).
Exit 0 = all checks pass. Stdlib only.
"""

import hashlib
import json
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(REPO, "scripts", "build_constructions.py")
SOURCE = os.path.join(REPO, "grammar-agdt", "AGDT2", "guidelines",
                      "Greek_guidelines_2.5.md")
SECTIONS = os.path.join(REPO, "data", "smyth", "sections.jsonl")
OUT = os.path.join(REPO, "data", "smyth", "constructions.json")

ESTIMATED_LINKS = 623      # prior research estimate
ESTIMATED_SECTIONS = 273   # prior research estimate
TOLERANCE = 0.10

failures = []
notes = []


def check(ok, label, detail=""):
    print("%-5s %s%s" % ("ok" if ok else "FAIL", label,
                         (" -- " + detail) if detail else ""))
    if not ok:
        failures.append(label)


def sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def main():
    # 1. determinism: existing file must equal two fresh builds
    before = sha(OUT) if os.path.exists(OUT) else None
    hashes = []
    for _ in range(2):
        subprocess.run([sys.executable, BUILD], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        hashes.append(sha(OUT))
    check(hashes[0] == hashes[1], "determinism: two builds byte-identical",
          "%s vs %s" % (hashes[0][:12], hashes[1][:12]))
    check(before == hashes[0], "committed file matches a fresh build",
          "committed %s, built %s" % ((before or "missing")[:12], hashes[0][:12]))

    with open(OUT, encoding="utf-8") as fh:
        doc = json.load(fh)
    meta, entries = doc["meta"], doc["entries"]
    counts = meta["counts"]

    # 2. link count vs the source and vs the prior estimate
    with open(SOURCE, encoding="utf-8") as fh:
        raw = fh.read()
    in_source = len(re.findall(r"doc=Smy\w*\+grammar\+\d+", raw))
    check(counts["totalLinks"] == in_source,
          "every Smyth link in the source is accounted for",
          "meta %d, source %d" % (counts["totalLinks"], in_source))
    dev = abs(counts["totalLinks"] - ESTIMATED_LINKS) / ESTIMATED_LINKS
    check(dev <= TOLERANCE, "link count within 10%% of the ~%d estimate"
          % ESTIMATED_LINKS,
          "actual %d (%.1f%%)" % (counts["totalLinks"], dev * 100))
    dev = abs(counts["distinctSectionsLinked"] - ESTIMATED_SECTIONS) \
        / ESTIMATED_SECTIONS
    check(dev <= TOLERANCE, "distinct sections within 10%% of the ~%d estimate"
          % ESTIMATED_SECTIONS,
          "actual %d (%.1f%%)" % (counts["distinctSectionsLinked"], dev * 100))

    # 2b. the sections the entries cite are the sections the source links.
    #
    # The check above compares two integers: how many Smyth links the source
    # holds, and how many the meta says it read. Equal counts say nothing
    # about which sections they are. A build that read 624 links and filed
    # them under 624 wrong section numbers would pass it, pass the two 10%
    # estimates, and pass every shape check below, so long as the numbers it
    # invented exist in sections.jsonl -- and 3048 of them do.
    #
    # This compares the sets. Every section the source links is cited by some
    # entry, and no entry cites a section the source does not link. The
    # verifier reads the numbers out of the source itself with its own
    # regex, and the meta's own count of them has to agree.
    linked = {int(n) for n in
              re.findall(r"doc=Smy\w*\+grammar\+(\d+)", raw)}
    named = set()
    for e in entries:
        for s in e["sections"]:
            named.add(s["n"])
            if s.get("to") is not None:
                named.add(s["to"])
    check(linked == named
          and counts["distinctSectionsLinked"] == len(linked),
          "the sections the entries cite are the sections the source links",
          "source links %d distinct sections, entries name %d; "
          "linked but never cited: %s; cited but never linked: %s; "
          "meta.distinctSectionsLinked %d"
          % (len(linked), len(named), sorted(linked - named)[:8],
             sorted(named - linked)[:8],
             counts["distinctSectionsLinked"]))

    # 3. every section resolves in sections.jsonl
    valid = set()
    with open(SECTIONS, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                valid.add(json.loads(line)["n"])
    missing, bad_range = set(), []
    covered = set()
    for e in entries:
        for s in e["sections"]:
            end = s.get("to", s["n"])
            if end < s["n"]:
                bad_range.append((e["construction"], s))
            for n in range(s["n"], max(end, s["n"]) + 1):
                covered.add(n)
                if n not in valid:
                    missing.add(n)
    check(not missing, "every cited section exists in sections.jsonl",
          "missing: %s" % sorted(missing)[:20] if missing else
          "%d sections covered once ranges are expanded" % len(covered))
    check(not bad_range, "no range ends before it starts", str(bad_range[:5]))

    # 4/5. entry sanity
    empty = [e for e in entries if not e["sections"]]
    check(not empty, "no entry has an empty section list", str(len(empty)))
    unnamed = [e for e in entries if not e["construction"].strip()]
    check(not unnamed, "every entry has a non-empty construction name",
          str(len(unnamed)))
    noctx = [e for e in entries if not e["agdtContext"].strip()]
    check(not noctx, "every entry has a non-empty agdtContext", str(len(noctx)))
    nofile = [e for e in entries if not e.get("sourceFile")]
    check(not nofile, "every entry names its source file", str(len(nofile)))

    # 6. internal consistency
    check(counts["entries"] == len(entries), "meta entry count matches entries",
          "%d vs %d" % (counts["entries"], len(entries)))
    keys = [(e["construction"], e["agdtContext"], e["contextKind"],
             e["sourceHeading"]) for e in entries]
    check(len(keys) == len(set(keys)), "entry keys are unique")
    order = sorted(entries, key=lambda e: (e["construction"].lower(),
                                           e["agdtContext"], e["contextKind"],
                                           e["sourceHeading"]))
    check(order == entries, "entries are in canonical sort order")
    dupes = [e["construction"] for e in entries
             if len(e["sections"]) != len({(s["n"], s.get("to"),
                                            s.get("anchor"))
                                           for s in e["sections"]})]
    check(not dupes, "no duplicate sections inside an entry", str(dupes[:5]))

    # 7. nothing dropped silently
    check(not meta["unmappableLinks"], "no unmappable links",
          "%d listed in meta" % len(meta["unmappableLinks"]))
    check(not meta["unnamedContexts"], "no links lost to unnamed contexts",
          "%d listed in meta" % len(meta["unnamedContexts"]))
    if meta["malformedLinks"]:
        notes.append("%d malformed source URLs recovered and kept (see "
                     "meta.malformedLinks)" % len(meta["malformedLinks"]))

    for n in notes:
        print("note  " + n)
    print("\n%d checks failed" % len(failures) if failures else
          "\nall checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
