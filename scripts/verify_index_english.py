#!/usr/bin/env python3
"""Independently verify data/smyth/index-english.json and print a full report.

Stdlib only. The data is hand-transcribed from page images, so there is nothing
deterministic to re-derive from a builder the way citations.json is checked.
Instead this script checks the things a bad transcription would break:

  1  every page file present, well formed, and honest about its own counts
  2  the final JSON is derivable from the page files (concatenation + stitching)
  3  every section number cited exists in sections.jsonl (1-3048)
  4  letter anchors that look like Smyth letters exist on the cited section
  5  no empty or duplicated-adjacent headwords
  6  entries run in alphabetical order, with a tolerance for the print's quirks
  7  ref-count sanity per page
  8  letter coverage A-Z
  9  transcription QA: for 30 sampled entries, does the cited section actually
     talk about the headword?  Suspects are listed, never deleted.

Exit status is non-zero if any check FAILs. WARN never fails the run.
"""

from __future__ import annotations

import argparse
import json
import random
import collections
import re
import sys
import unicodedata
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECTIONS = ROOT / "data" / "smyth" / "sections.jsonl"
INDEX = ROOT / "data" / "smyth" / "index-english.json"
PAGE_DIR = ROOT / "data" / "smyth" / "index-english-pages"
FIRST_PAGE, LAST_PAGE = 723, 756
MAX_SECTION = 3048

# Ordering tolerance. The 1920 print is not machine-sorted: it files some
# entries by the sense of the phrase rather than by letter, and a handful of
# headwords sit out of strict order. Anything at or under this many descents is
# reported and accepted; above it the check fails.
ORDER_TOLERANCE = 25

# QA heuristic: index shorthand -> words that may stand for it in a section.
ABBREV = {
    "vbs": "verb", "vb": "verb", "adjs": "adjectiv", "adj": "adjectiv",
    "advs": "adverb", "adv": "adverb", "substs": "substantiv",
    "subst": "substantiv", "gen": "genitiv", "dat": "dativ", "acc": "accusativ",
    "nom": "nominativ", "voc": "vocativ", "inf": "infinitiv",
    "part": "particip", "parts": "particip", "prep": "preposition",
    "preps": "preposition", "pron": "pronoun", "conj": "conjunction",
    "decl": "declension", "compar": "comparison", "superl": "superlativ",
    "cl": "clause", "cls": "clause", "sent": "sentence", "constr": "construction",
    "opt": "optativ", "subjv": "subjunctiv", "imper": "imperativ",
    "indic": "indicativ", "perf": "perfect", "aor": "aorist", "fut": "future",
    "imperf": "imperfect", "plup": "pluperfect", "pres": "present",
    "mid": "middle", "pass": "passive", "act": "active", "suff": "suffix",
    "compos": "composition", "cpds": "compound", "sing": "singular",
    "pl": "plural", "dual": "dual", "neg": "negativ", "interrog": "interrogativ",
    "rel": "relativ", "dir": "direct", "ind": "indirect", "disc": "discourse",
    "temp": "temporal", "prin": "principal", "apod": "apodosis",
    "prot": "protasis", "condit": "condition", "condits": "condition",
}

STOP = {
    "of", "the", "and", "in", "to", "by", "with", "w", "a", "an", "or", "for",
    "as", "from", "see", "use", "uses", "used", "how", "its", "their", "after",
    "before", "not", "at", "on", "into", "expressed", "denoting", "signifying",
    "general", "case", "cases", "form", "forms", "etc",
}


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    @property
    def text(self) -> str:
        return " ".join("".join(self.parts).split())


def strip_html(html: str) -> str:
    parser = TextExtractor()
    parser.feed(html)
    return parser.text


def fold(value: str) -> str:
    """Lowercase, drop diacritics and punctuation, squeeze spaces."""
    value = unicodedata.normalize("NFD", value)
    value = "".join(c for c in value if unicodedata.category(c) != "Mn")
    value = re.sub(r"[^0-9a-zA-ZͰ-Ͽἀ-῿ ]+", " ", value)
    return " ".join(value.lower().split())


class Report:
    def __init__(self) -> None:
        self.failed = False
        self.n = 0

    def check(self, ok: bool, title: str, detail: str = "") -> None:
        self.n += 1
        status = "PASS" if ok else "FAIL"
        if not ok:
            self.failed = True
        print(f"{self.n:>2}. [{status}] {title}")
        if detail:
            for line in detail.splitlines():
                print(f"        {line}")

    def warn(self, title: str, detail: str = "") -> None:
        self.n += 1
        print(f"{self.n:>2}. [WARN] {title}")
        if detail:
            for line in detail.splitlines():
                print(f"        {line}")

    def note(self, title: str, detail: str = "") -> None:
        self.n += 1
        print(f"{self.n:>2}. [INFO] {title}")
        if detail:
            for line in detail.splitlines():
                print(f"        {line}")


def all_refs(entry: dict) -> list[dict]:
    refs = list(entry.get("refs", []))
    for sub in entry.get("sub", []):
        refs.extend(sub.get("refs", []))
    return refs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=30,
                    help="entries to spot-check against section text")
    ap.add_argument("--seed", type=int, default=1920)
    args = ap.parse_args()

    rep = Report()

    sections = {}
    for line in SECTIONS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            sections[row["n"]] = row

    doc = json.loads(INDEX.read_text(encoding="utf-8"))
    entries = doc["entries"]

    # ---- 1  page files -----------------------------------------------------
    page_files = {}
    problems = []
    for n in range(FIRST_PAGE, LAST_PAGE + 1):
        path = PAGE_DIR / f"page-{n:04d}.json"
        if not path.exists():
            problems.append(f"page {n}: file missing")
            continue
        try:
            page = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            problems.append(f"page {n}: not valid JSON ({exc})")
            continue
        page_files[n] = page
        if page.get("page") != n:
            problems.append(f"page {n}: 'page' field says {page.get('page')}")
        if page.get("leaf") != n + 13:
            problems.append(f"page {n}: leaf should be {n + 13}")
        counts = page.get("counts", {})
        c1 = sum(1 for ln in page.get("lines", []) if ln.get("col") == 1)
        c2 = sum(1 for ln in page.get("lines", []) if ln.get("col") == 2)
        if counts.get("linesCol1") != c1 or counts.get("linesCol2") != c2:
            problems.append(f"page {n}: counts col1/col2 "
                            f"{counts.get('linesCol1')}/{counts.get('linesCol2')} "
                            f"but arrays hold {c1}/{c2}")
        if counts.get("lines") != len(page.get("lines", [])):
            problems.append(f"page {n}: counts.lines wrong")
        if counts.get("entries") != len(page.get("entries", [])):
            problems.append(f"page {n}: counts.entries wrong")
        cols = [ln.get("col") for ln in page.get("lines", [])]
        if cols != sorted(cols):
            problems.append(f"page {n}: lines are not in column reading order")
    rep.check(not problems,
              f"all {LAST_PAGE - FIRST_PAGE + 1} page files present, well formed, "
              "counts honest, column order kept",
              "\n".join(problems[:20]))

    # ---- 2  final JSON derivable from page files ---------------------------
    from_pages = 0
    stitched = 0
    for page in page_files.values():
        for e in page["entries"]:
            if e.get("wrapNote") == "continued from previous page":
                stitched += 1
            else:
                from_pages += 1
    rep.check(from_pages == len(entries),
              "final entry count equals page-file entries minus page-break "
              "continuations",
              f"page files: {from_pages + stitched} records, {stitched} of them "
              f"continuations -> {from_pages} expected; final JSON has "
              f"{len(entries)}")

    page_raw = []
    for page in page_files.values():
        for e in page["entries"]:
            page_raw.append(fold(e["raw"]))
    joined_pages = " ".join(page_raw)
    missing_raw = [e["headword"] for e in entries
                   if fold(e["raw"]).split(" ")[0] not in joined_pages.split(" ")]
    rep.check(not missing_raw,
              "every final entry's text traces back to a page file",
              f"untraceable: {missing_raw[:10]}")

    # ---- 2a  the final entries ARE the page files' entries -----------------
    # The two checks above are arithmetic and a membership test. The first
    # compares two integers. The second folds each final entry's raw text,
    # takes its FIRST WORD, and asks whether that word appears anywhere in
    # the 34 page files joined end to end; "Ablative" passes because the word
    # "ablative" occurs somewhere in the index, whatever the rest of the
    # entry says and whatever its refs point at. Nothing compared a ref in
    # index-english.json with the ref the transcriber typed on the page.
    #
    # This check does. It walks the page files in order, grouping each
    # continuation onto the entry it continues, and requires the final
    # entry's headword, its pages, and its whole ref list, ref by ref and
    # field by field, to be the group's own. The one exception is the single
    # range the page turn splits ("496-" on p. 733 closed by "531" on p. 734),
    # which the build marks splitAcrossPages and which the check counts and
    # reports rather than compares.
    groups: list[list[tuple[int, dict]]] = []
    for n in sorted(page_files):
        for e in page_files[n]["entries"]:
            if e.get("wrapNote") == "continued from previous page" and groups:
                groups[-1].append((n, e))
            else:
                groups.append([(n, e)])

    def refs_in(entry: dict) -> list[dict]:
        found = [dict(r) for r in entry.get("refs", [])]
        for sub in entry.get("sub", []):
            found.extend(dict(r) for r in sub.get("refs", []))
        return found

    def ref_key(ref: dict) -> str:
        return json.dumps({k: v for k, v in ref.items()
                           if k != "splitAcrossPages"},
                          ensure_ascii=False, sort_keys=True)

    page_mismatch: list[str] = []
    split_ranges = 0
    if len(groups) != len(entries):
        page_mismatch.append(f"{len(groups)} page-file groups but "
                             f"{len(entries)} final entries")
    for group, final in zip(groups, entries):
        head = group[0][1].get("headword")
        if final.get("headword") != head:
            page_mismatch.append(
                f"headword {final.get('headword')!r} != page {head!r}")
            continue
        pages_seen = sorted({n for n, _ in group})
        if final.get("pages") != pages_seen:
            page_mismatch.append(
                f"{head!r}: pages {final.get('pages')} != {pages_seen}")
        typed: list[dict] = []
        for _, fragment in group:
            typed.extend(refs_in(fragment))
        built = refs_in(final)
        joined = [r for r in built if r.get("splitAcrossPages")]
        split_ranges += len(joined)
        if joined:
            if len(typed) != len(built) + len(joined):
                page_mismatch.append(
                    f"{head!r}: {len(typed)} refs typed, {len(built)} built, "
                    f"{len(joined)} closed across the page turn")
            continue
        if [ref_key(r) for r in typed] != [ref_key(r) for r in built]:
            page_mismatch.append(
                f"{head!r}: {len(typed)} refs typed, {len(built)} built, "
                f"first difference "
                f"{next((f'{a} vs {b}' for a, b in zip(typed, built) if ref_key(a) != ref_key(b)), 'length')}")
    rep.check(not page_mismatch,
              f"every entry's headword, pages and refs are the page files' "
              f"own ({len(groups)} groups, {split_ranges} range closed across "
              f"a page turn)",
              "\n".join(page_mismatch[:15]))

    # ---- 2b  every ref is the reference its own verbatim writes ------------
    # A ref carries the transcriber's verbatim string beside the numbers the
    # build read out of it. Nothing checked that they agree, so a ref could
    # say "1348 b" and point at §1384 and pass every check here: check 3 only
    # asks that the number exist, and §1384 does.
    #
    # So: the first number written in the verbatim is n; the last is "to"
    # where a range was read; an anchor the build did not mark inherited is
    # written there too; a ref marked inherited takes the n of the last ref
    # that was not; and the verbatim stands in the entry's own raw line.
    squeeze = lambda value: re.sub(r"\s+", "", value or "")  # noqa: E731
    ref_wrong: list[str] = []
    ref_read = 0
    for entry in entries:
        blocks = [(entry.get("raw", ""), entry.get("refs", []))]
        blocks += [(sub.get("raw", ""), sub.get("refs", []))
                   for sub in entry.get("sub", [])]
        for raw, refs in blocks:
            line = squeeze(raw)
            carried: int | None = None
            for ref in refs:
                ref_read += 1
                verbatim = ref.get("verbatim", "")
                head = entry["headword"]
                if (squeeze(verbatim) and squeeze(verbatim) not in line
                        and not ref.get("splitAcrossPages")):
                    ref_wrong.append(
                        f"{head!r}: {verbatim!r} is not in its own line")
                anchor = ref.get("anchor")
                if (anchor and not ref.get("inherited")
                        and squeeze(str(anchor)) not in squeeze(verbatim)):
                    ref_wrong.append(
                        f"{head!r}: anchor {anchor!r} is not written in "
                        f"{verbatim!r}")
                written = re.findall(r"\d+", verbatim)
                if ref.get("inherited"):
                    if ref.get("n") is not None and ref.get("n") != carried:
                        ref_wrong.append(
                            f"{head!r}: {verbatim!r} inherits {ref.get('n')}, "
                            f"but the ref before it is {carried}")
                    continue
                if ref.get("n") is None:
                    continue
                carried = ref["n"]
                if not written or written[0] != str(ref["n"]):
                    ref_wrong.append(
                        f"{head!r}: {verbatim!r} does not write {ref['n']}")
                if ref.get("to") is not None and (
                        len(written) < 2 or written[-1] != str(ref["to"])):
                    ref_wrong.append(
                        f"{head!r}: {verbatim!r} does not write the range end "
                        f"{ref['to']}")
    rep.check(not ref_wrong,
              f"every ref is the reference its own verbatim writes "
              f"({ref_read} refs read)",
              "\n".join(ref_wrong[:15]))

    # ---- 3  section numbers exist -----------------------------------------
    bad_n, ranges_backwards = [], []
    total_refs = 0
    for entry in entries:
        for ref in all_refs(entry):
            total_refs += 1
            n = ref.get("n")
            if n is None:
                continue
            if not isinstance(n, int) or not (1 <= n <= MAX_SECTION) or n not in sections:
                bad_n.append((entry["headword"], ref.get("verbatim"), n))
            to = ref.get("to")
            if to is not None:
                if not isinstance(to, int) or not (1 <= to <= MAX_SECTION) or to not in sections:
                    bad_n.append((entry["headword"], ref.get("verbatim"), to))
                elif isinstance(n, int) and to < n:
                    ranges_backwards.append((entry["headword"], ref.get("verbatim")))
    rep.check(not bad_n,
              f"every cited section number exists in sections.jsonl (1-{MAX_SECTION})",
              "\n".join(f"{h!r} {v!r} -> {n}" for h, v, n in bad_n[:20]))
    rep.check(not ranges_backwards,
              "every range runs forwards",
              "\n".join(f"{h!r} {v!r}" for h, v in ranges_backwards[:20]))

    # ---- 4  letter anchors -------------------------------------------------
    letter_re = re.compile(r"^[a-o]$")
    anchor_miss = []
    anchor_checked = 0
    for entry in entries:
        for ref in all_refs(entry):
            anchor = str(ref.get("anchor", ""))
            n = ref.get("n")
            if not letter_re.match(anchor) or n not in sections:
                continue
            anchor_checked += 1
            # A range cites its anchor on the section the anchor belongs
            # to, which need not be the first: "2110-2112 a N." means
            # §2112 a. Any section in the range satisfies it.
            span = range(n, int(ref.get("to") or n) + 1)
            if not any(anchor in sections.get(m, {}).get("letters", []) for m in span):
                anchor_miss.append((entry["headword"], ref.get("verbatim"), n, anchor))
    if anchor_miss:
        rep.warn(f"{len(anchor_miss)} of {anchor_checked} single-letter anchors "
                 "are not in the target section's letters[]",
                 "The TEI only marks a subset of Smyth's lettered subdivisions, "
                 "so a miss is weak evidence.\n"
                 + "\n".join(f"{h!r} {v!r} -> s{n} lacks '{a}'"
                             for h, v, n, a in anchor_miss[:15]))
    else:
        rep.check(True, f"all {anchor_checked} single-letter anchors exist on "
                        "their target section")

    # ---- 5  headwords ------------------------------------------------------
    empty = [i for i, e in enumerate(entries) if not e.get("headword", "").strip()]
    rep.check(not empty, "no empty headwords", f"indices: {empty[:20]}")

    dup_adjacent = [entries[i]["headword"] for i in range(1, len(entries))
                    if fold(entries[i]["headword"]) == fold(entries[i - 1]["headword"])]
    if dup_adjacent:
        rep.warn(f"{len(dup_adjacent)} adjacent headword repeats "
                 "(may be a real split entry, or a page stitched twice)",
                 ", ".join(dup_adjacent[:15]))
    else:
        rep.check(True, "no adjacent duplicate headwords")

    norefs = [e["headword"] for e in entries
              if not all_refs(e) and not e.get("crossRefs")]
    if norefs:
        rep.warn(f"{len(norefs)} entries carry neither a ref nor a cross-reference",
                 ", ".join(norefs[:15]))
    else:
        rep.check(True, "every entry carries a ref or a cross-reference")

    # ---- 6  alphabetical order --------------------------------------------
    keys = [fold(e["headword"]) for e in entries]
    descents = [(entries[i - 1]["headword"], entries[i]["headword"],
                 entries[i]["pages"])
                for i in range(1, len(keys)) if keys[i] < keys[i - 1]]
    rep.check(len(descents) <= ORDER_TOLERANCE,
              f"entries run in alphabetical order "
              f"({len(descents)} descents, tolerance {ORDER_TOLERANCE})",
              "\n".join(f"p{p}: {a!r} then {b!r}" for a, b, p in descents[:25]))

    # ---- 7  ref-count sanity per page -------------------------------------
    per_page: dict[int, int] = {}
    for page in page_files.values():
        per_page[page["page"]] = sum(
            len(e.get("refs", [])) + sum(len(s.get("refs", []))
                                         for s in e.get("sub", []))
            for e in page["entries"])
    values = sorted(per_page.values())
    median = values[len(values) // 2] if values else 0
    thin = {p: c for p, c in per_page.items()
            if p not in (FIRST_PAGE, LAST_PAGE) and c < median * 0.55}
    rep.check(not thin,
              f"no page is suspiciously thin (median {median} refs/page, "
              f"floor {median * 0.55:.0f})",
              "\n".join(f"page {p}: {c} refs" for p, c in sorted(thin.items())))
    rep.note("refs per page",
             f"min {values[0] if values else 0}, median {median}, "
             f"max {values[-1] if values else 0}, total {total_refs}")

    # ---- 8  letter coverage ------------------------------------------------
    letters = {}
    for entry in entries:
        head = fold(entry["headword"])
        if head:
            letters.setdefault(head[0].upper(), 0)
            letters[head[0].upper()] += 1
    alphabet = [chr(c) for c in range(ord("A"), ord("Z") + 1)]
    missing = [L for L in alphabet if L not in letters]
    if missing:
        rep.warn(f"letters with no entry: {', '.join(missing)}",
                 "Check against the print before treating this as a gap. X is "
                 "genuinely absent from this index: p. 756 runs Wondering, Yes, "
                 "Yes and No questions, Yielding, Yod, Zeugma.")
    else:
        rep.check(True, "every letter A-Z has at least one entry")
    rep.note("entries per letter",
             "  ".join(f"{L}:{letters.get(L, 0)}" for L in alphabet))

    # ---- 9  transcription QA sample ---------------------------------------
    rng = random.Random(args.seed)
    pool = [e for e in entries if all_refs(e)]
    sample = rng.sample(pool, min(args.sample, len(pool)))
    suspects = []
    for entry in sample:
        head_tokens = set()
        for tok in fold(entry["headword"]).split():
            if tok in STOP or len(tok) < 3:
                continue
            head_tokens.add(ABBREV.get(tok, tok)[:5])
        if not head_tokens:
            continue
        haystack = []
        for ref in all_refs(entry)[:6]:
            n = ref.get("n")
            if n not in sections:
                continue
            row = sections[n]
            haystack.append(fold(" ".join(row.get("path", []))))
            haystack.append(fold(row.get("head", "")))
            haystack.append(fold(strip_html(row.get("html", "")))[:2500])
        blob = " ".join(haystack)
        if not any(tok in blob for tok in head_tokens):
            first = all_refs(entry)[0]
            suspects.append((entry["headword"], first.get("verbatim"),
                             entry["pages"]))
    hit = len(sample) - len(suspects)
    rep.note(f"QA sample: {hit}/{len(sample)} sampled entries match text at a "
             "cited section",
             "\n".join(f"suspect: {h!r} (first ref {v!r}, p{p})"
                       for h, v, p in suspects) or "no suspects")

    # ---- summary -----------------------------------------------------------
    print()
    print(f"entries {len(entries)}  refs {total_refs}  "
          f"pages {len(page_files)}  "
          f"unresolved {len(doc['_meta'].get('unresolvedRefs', []))}"
          + (" (" + ", ".join(
              f"{n} {reason}" for reason, n in sorted(collections.Counter(
                  r.get("reason", "?") for r in doc["_meta"]["unresolvedRefs"]
              ).items())) + ")"
             if doc["_meta"].get("unresolvedRefs") else ""))
    print("RESULT:", "FAIL" if rep.failed else "OK")
    return 1 if rep.failed else 0


if __name__ == "__main__":
    sys.exit(main())
