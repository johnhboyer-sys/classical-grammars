#!/usr/bin/env python3
"""Independently verify data/smyth/index-greek.json and print a full report.

Stdlib only. Mirrors verify_index_english.py where the two indexes share
structure, plus the checks specific to the Greek pipeline:

  1  deterministic rebuild: build_index_greek.py reproduces the checked-in
     file byte-for-byte
  2  every section number cited exists in sections.jsonl (1-3048), and
     every range runs forward with both ends real
  3  single-letter anchors exist on the cited section (letters[]); misses
     are listed as WARN, the print's known quirks included
  4  dialect refs point at sections that actually carry dialect notes
  5  text hygiene: NFC, no Latin macron vowels in Greek runs, no
     leftover glyph placeholders, no reader/parser artifacts ('|', '**')
  6  every headword begins with Greek (after the one recorded stray
     quote), no empty or adjacent-duplicate headwords
  7  entries run in Greek alphabetical order, with a tolerance for the
     print's own filing quirks
  8  fraction entries: each ο/ε headword carries searchKeys and its
     glued corpus form appears in the corpus text
  9  cross-references resolve to another entry's headword (prefix match;
     misses WARN)
 10  transcription QA: sampled Greek headwords appear diacritic-exactly
     in a section they cite (the unanimity-audit check, re-run on the
     final artifact); suspects are listed, never deleted

Exit status is non-zero if any check FAILs. WARNs are tolerated only
inside their stated rate floors (letter anchors 5%, cross-refs 40%);
past those the same condition FAILs.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECTIONS = ROOT / "data" / "smyth" / "sections.jsonl"
INDEX = ROOT / "data" / "smyth" / "index-greek.json"
BUILDER = ROOT / "scripts" / "build_index_greek.py"
MAX_SECTION = 3048
GR = r"Ͱ-Ͽἀ-῿"
GREEK_RUN = re.compile(rf"[{GR}][{GR}̀-ͯ]*")
LATIN_MACRON = re.compile(r"[āīūăĭŭēō]")


class Report:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.failed = False

    def check(self, ok: bool, title: str, detail: str = "") -> None:
        tag = "PASS" if ok else "FAIL"
        if not ok:
            self.failed = True
        self.lines.append(f"[{tag}] {title}")
        if detail:
            self.lines.append(f"  {detail}")

    def warn(self, title: str, detail: str = "") -> None:
        self.lines.append(f"[WARN] {title}")
        if detail:
            self.lines.append(f"  {detail}")

    def dump(self) -> None:
        print("\n".join(self.lines))
        print("\nVERIFY REPORT SUMMARY")
        print("  overall:", "FAIL" if self.failed else "PASS")


# Greek collation: base letter order, ignoring diacritics/case. Mirrors
# the print's own filing (which also ignores breathings and length).
ALPHA = "αβγδεζηθικλμνξοπρστυφχψω"
ORDER = {c: i for i, c in enumerate(ALPHA)}


def collation_key(head: str) -> list[int]:
    base = unicodedata.normalize("NFD", head.lower())
    key = []
    for ch in base:
        if ch == "ς":                 # final sigma files as sigma
            key.append(ORDER["σ"] * 10)
        elif ch == "ϝ":               # digamma files after ε in the print
            key.append(ORDER["ε"] * 10 + 5)
        elif ch in ORDER:
            key.append(ORDER[ch] * 10)
    return key


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=40)
    args = ap.parse_args()
    rep = Report()

    doc = json.loads(INDEX.read_text(encoding="utf-8"))
    entries = doc["entries"]

    sections: dict[int, dict] = {}
    with SECTIONS.open(encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            sections[r["n"]] = r

    # ---- 1 deterministic rebuild ----------------------------------------
    # re-run the builder and require byte-identical outputs; snapshot and
    # restore so a differing rebuild can never silently replace the
    # checked-in files (the verifier must not mutate what it verifies)
    adj_path = ROOT / "data" / "smyth" / "index-greek-adjudication.json"
    before = INDEX.read_bytes()
    before_adj = adj_path.read_bytes()
    result = subprocess.run([sys.executable, str(BUILDER)],
                            capture_output=True, text=True)
    after = INDEX.read_bytes()
    after_adj = adj_path.read_bytes()
    same = before == after and before_adj == after_adj
    if not same:
        INDEX.write_bytes(before)
        adj_path.write_bytes(before_adj)
    rep.check(result.returncode == 0 and same,
              "re-running the builder reproduces both outputs byte-for-byte"
              " (originals restored on mismatch)",
              result.stderr.strip()[:200] if result.returncode else
              f"index {len(after)} bytes; adjudication {len(after_adj)} bytes")

    # ---- 2 section numbers and ranges -----------------------------------
    bad_n, bad_range, checked = [], [], 0
    for e in entries:
        for ref in e["refs"]:
            checked += 1
            n = ref["n"]
            if n not in sections:
                bad_n.append((e["headword"], ref.get("verbatim"), n))
            if "to" in ref:
                if ref["to"] <= n or ref["to"] not in sections:
                    bad_range.append((e["headword"], ref.get("verbatim")))
    rep.check(not bad_n, f"all {checked} refs cite existing sections",
              "; ".join(f"{h}: {v} -> {n}" for h, v, n in bad_n[:10]))
    rep.check(not bad_range, "all ranges run forward between real sections",
              "; ".join(f"{h}: {v}" for h, v in bad_range[:10]))

    # ---- 2a every ref is the reference its own verbatim writes ------------
    # Check 2 reads ref["n"] and asks whether that section exists.  3048 of
    # them do, so any number in range passes, and the verbatim string beside
    # it, which is what the transcriber read off the page, was never
    # consulted.  A ref could say "489 e" and point at §498 and every check
    # in this file would report PASS: check 3's anchor test would look for
    # "e" on §498 and, when it did not find it, WARN.
    #
    # So this reads the verbatim.  The first number written there is n; the
    # last is "to" where a range was read; an anchor the build did not mark
    # inherited is written there too; a ref the build did mark inherited
    # takes the n of the last ref that was not, and ends on the same token
    # the verbatim ends on ("ἄμμε" files "325 D 1, 3", and the second half
    # is §325 anchor "D 3"); and every verbatim stands in its entry's own
    # raw line.
    squeeze = lambda value: re.sub(r"\s+", "", value or "")  # noqa: E731
    ref_wrong: list[str] = []
    ref_read = 0
    for e in entries:
        line = squeeze(e.get("raw", ""))
        carried: int | None = None
        for ref in e["refs"]:
            ref_read += 1
            verbatim = ref.get("verbatim", "")
            head = e["headword"]
            anchor = str(ref.get("anchor") or "")
            written = re.findall(r"\d+", verbatim)
            if squeeze(verbatim) and squeeze(verbatim) not in line:
                ref_wrong.append(f"{head!r}: {verbatim!r} is not in its own "
                                 "raw line")
            if ref.get("inherited"):
                if ref.get("n") is not None and ref["n"] != carried:
                    ref_wrong.append(
                        f"{head!r}: {verbatim!r} inherits {ref['n']}, but the "
                        f"ref before it is {carried}")
                if (anchor and verbatim
                        and anchor.split()[-1] != verbatim.split()[-1]):
                    ref_wrong.append(
                        f"{head!r}: inherited anchor {anchor!r} does not end "
                        f"on {verbatim!r}")
                continue
            if anchor and squeeze(anchor) not in squeeze(verbatim):
                ref_wrong.append(f"{head!r}: anchor {anchor!r} is not written "
                                 f"in {verbatim!r}")
            if ref.get("n") is not None:
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
              "; ".join(ref_wrong[:10]))

    # ---- 3 letter anchors ------------------------------------------------
    letter_re = re.compile(r"^[a-h]$")
    miss, ok_n = [], 0
    for e in entries:
        for ref in e["refs"]:
            anchor = str(ref.get("anchor", ""))
            if not letter_re.match(anchor) or ref["n"] not in sections:
                continue
            if anchor in sections[ref["n"]].get("letters", []):
                ok_n += 1
            else:
                miss.append((e["headword"], ref.get("verbatim"),
                             ref["n"], anchor))
    total_l = ok_n + len(miss)
    if miss and len(miss) <= 0.05 * total_l:
        rep.warn(f"{len(miss)} of {total_l} single-letter anchors "
                 "not in the target section's letters[] (known corpus "
                 "granularity: prose-lettered sections like 944 b)",
                 "; ".join(f"{h}: {v} -> {n} {a}"
                           for h, v, n, a in miss[:15]))
    else:
        rep.check(not miss, f"single-letter anchors exist on their "
                  f"sections ({ok_n}/{total_l}; FAIL past 5% misses)",
                  "; ".join(f"{h}: {v} -> {n} {a}"
                            for h, v, n, a in miss[:15]))

    # ---- 4 dialect refs --------------------------------------------------
    dmiss, dok = [], 0
    for e in entries:
        for ref in e["refs"]:
            anchor = str(ref.get("anchor", ""))
            if "D" not in anchor.split() or ref["n"] not in sections:
                continue
            sec = sections[ref["n"]]
            if sec.get("dialectNotes"):
                dok += 1
            else:
                dmiss.append((e["headword"], ref.get("verbatim"), ref["n"]))
    if dmiss:
        rep.warn(f"{len(dmiss)} of {dok + len(dmiss)} dialect refs point "
                 "at sections without dialectNotes",
                 "; ".join(f"{h}: {v} -> {n}" for h, v, n in dmiss[:15]))
    else:
        rep.check(True, f"all {dok} dialect refs point at sections that "
                  "carry dialect notes")

    # ---- 5 text hygiene --------------------------------------------------
    dirty = []
    for e in entries:
        raw = e["raw"]
        if raw != unicodedata.normalize("NFC", raw):
            dirty.append((e["headword"], "not NFC"))
        for run in GREEK_RUN.findall(raw):
            if LATIN_MACRON.search(run):
                dirty.append((e["headword"], "latin macron in greek run"))
        if re.search(r"\[[α-ω]+\]|\[[A-Za-z]+ ?\]", raw):
            dirty.append((e["headword"], "glyph placeholder"))
        if "|" in raw or "**" in raw:
            dirty.append((e["headword"], "reader artifact"))
    rep.check(not dirty, "text hygiene: NFC, no Latin macrons in Greek, "
              "no placeholders, no reader artifacts",
              "; ".join(f"{h}: {w}" for h, w in dirty[:10]))

    # ---- 6 headwords -----------------------------------------------------
    head_re = re.compile(rf"^[-(]?[{GR}]")
    bad_head = [e["headword"] for e in entries
                if not head_re.match(e["headword"])]
    dup_adj = [entries[i]["headword"] for i in range(1, len(entries))
               if entries[i]["headword"] == entries[i - 1]["headword"]
               and entries[i]["raw"] == entries[i - 1]["raw"]]
    rep.check(not bad_head, "every headword begins with Greek",
              "; ".join(bad_head[:10]))
    rep.check(not dup_adj, "no adjacent duplicate entries",
              "; ".join(dup_adj[:10]))

    # ---- 7 alphabetical order -------------------------------------------
    # Frozen allowlist of the print's own filing quirks (sense-order
    # pairs like 'ἀ- or ἀν-' before 'ἀ- or ἀ-', suffixes filed among
    # words, digraph and breathing choices), audited 2026-08-04 against
    # the adjudicated frame; re-audited same day after the Opus vision
    # pass. ANY new descent is a segmentation defect.
    # Vision-pass changes: '-αζω' removed (was an -αξε/-αζε transcription
    # error, not a print quirk); 'οὐ γάρ' and 'μέντοι οὐδέ' removed (were
    # false entries from a dropped italic οὐ at p775 l94, now
    # continuations); 'μηδέ' removed (its descent was the false entry
    # 'ὅ τι (ὅσον) μή' from the p772 l30 split); 'πετάννῡμι' removed (its
    # descent was the false entry 'ὤν omitted w.' from the p777 l62
    # split); 'ἢ' respelled 'ἤ' (crop-verified headword accent, p767 l72);
    # 'ἀ- or ἀ-' respelled 'ἀ- or ἁ-' (John's ruling 2026-08-04: second
    # copulative alternate is rough, per crop + Smyth §885.4).
    allowed_descents = {
        "ἀ- or ἁ-", "ᾱ", "ᾱ (Dor., Aeol.) for η", "ἄνα", "-δε",
        "δέω", "-ει", "εἷς", "-εναι", "ἐνταῦθα", "ἐσθίω", "εὔαδε", "ἤ",
        "ἡγέομαι", "-μεν", "μοί", "μονᾱ", "-νῡμι", "ὅθεν",
        "οἴκαδε (οἶκόνδε)", "-οο", "οὗ",
        "ποταμός", "πταίω", "τοιγαροῦν", "ὑπαί", "ὦ",
        "ω-verbs", "-ως",
    }
    descents = []
    prev_key = None
    for e in entries:
        k = collation_key(e["headword"])
        if prev_key is not None and k and prev_key and k < prev_key:
            descents.append(e["headword"])
        if k:
            prev_key = k
    new_desc = [h for h in descents if h not in allowed_descents]
    rep.check(not new_desc,
              f"alphabetical order: {len(descents)} descents, all on the "
              "frozen print-quirk allowlist",
              "NEW descents (segmentation suspects): "
              + ", ".join(new_desc[:15]) if new_desc else "")

    # ---- 8 fraction searchKeys ------------------------------------------
    fracs = [e for e in entries if re.search(r"[οηω]/[εη]", e["headword"])]
    frac_bad = []
    corpus_text = " ".join(
        s.get("plain", "") or "" for s in sections.values())
    for e in fracs:
        keys = e.get("searchKeys", [])
        if not keys:
            frac_bad.append((e["headword"], "missing searchKeys"))
            continue
        stems = [k.strip("-.,") for k in keys]
        if not any(s and s in corpus_text for s in stems):
            frac_bad.append((e["headword"],
                             f"no searchKey form found in corpus: {stems}"))
    rep.check(len(fracs) == 10 and not frac_bad,
              f"10 fraction entries (8 ο/ε, 1 η/ε, 1 ω/η) carry searchKeys "
              f"with a corpus-matching form (found {len(fracs)})",
              "; ".join(f"{h}: {w}" for h, w in frac_bad[:10]))

    # ---- 9 cross-references ---------------------------------------------
    heads = [e["headword"] for e in entries]
    xmiss, xok = [], 0
    for e in entries:
        for tgt in e.get("crossRefs", []):
            m = GREEK_RUN.search(tgt)
            probe = m.group(0) if m else tgt.split()[0] if tgt else ""
            if probe and any(h.lstrip("-(").startswith(probe)
                             for h in heads):
                xok += 1
            else:
                xmiss.append((e["headword"], tgt))
    total_x = xok + len(xmiss)
    if xmiss and len(xmiss) <= 0.4 * total_x:
        rep.warn(f"{len(xmiss)} of {total_x} cross-references have no "
                 "matching headword (known: English-index targets like "
                 "Digamma/Article, and diacritic-variant heads)",
                 "; ".join(f"{h} -> {t}" for h, t in xmiss[:15]))
    else:
        rep.check(not xmiss,
                  f"cross-references resolve ({xok}/{total_x}; "
                  "FAIL past 40% misses)",
                  "; ".join(f"{h} -> {t}" for h, t in xmiss[:15]))

    # ---- 10 sampled headword-in-section QA ------------------------------
    import random
    rng = random.Random(20260803)
    greek_heads = [e for e in entries
                   if GREEK_RUN.match(e["headword"].lstrip("-(“”\" "))
                   and e["refs"]]
    sample = rng.sample(greek_heads, min(args.sample, len(greek_heads)))
    suspects = []
    hits = 0
    for e in sample:
        probe_m = GREEK_RUN.search(e["headword"])
        if not probe_m:
            continue
        probe = probe_m.group(0)
        found = False
        for ref in e["refs"]:
            lo = ref["n"]
            hi = ref.get("to", ref["n"])
            for n in range(lo, min(hi, lo + 30) + 1):
                sec = sections.get(n)
                if sec and probe in (sec.get("plain") or ""):
                    found = True
                    break
            if found:
                break
        if found:
            hits += 1
        else:
            suspects.append(e["headword"])
    qa_ok = len(sample) == 0 or hits / len(sample) >= 0.7
    rep.check(qa_ok, f"sampled QA: {hits}/{len(sample)} headwords appear "
              "diacritic-exactly in a cited section (floor 70%)",
              "suspects (reviewable, not deleted): "
              + ", ".join(suspects[:12]))

    # ---- meta ------------------------------------------------------------
    meta = doc["_meta"]
    rep.check(meta["entryCount"] == len(entries)
              and meta["refCount"] == sum(len(e["refs"]) for e in entries),
              "meta counts match the data",
              f"entries {meta['entryCount']}  refs {meta['refCount']}")

    rep.dump()
    return 1 if rep.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
