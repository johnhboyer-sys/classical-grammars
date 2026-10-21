#!/usr/bin/env python3
"""Assemble data/smyth/index-greek.json from the adjudicated Greek Index
pipeline in work/greek-index/.

The pipeline (four independent transcribers -> token-level comparison ->
owner adjudication of every dispute -> corrected line frame -> entry
segmentation) runs in work/greek-index/; its committed end product is
greek-entries-raw.json, one record per printed index entry. This script
is the final, deterministic stage: parse each entry's reference list
into the structure index-english.json uses, and write the index plus an
adjudication summary. Nothing here reads an image or invents a number.

Ref grammar (built from a shape survey of all 1,465 entries):

  ref      = N ['. ' SUB] [LETTER] [DNOTE] | N '-' N | N ' ff.'
  N        = 1-4 digits (a Smyth section number)
  SUB      = 1-2 digit sub-anchor, optionally followed by a letter
             ('885. 1', '219. 2 b', '1734. 20')
  LETTER   = a-h subsection letter ('1982 a'); the print's two capital
             anchors are kept verbatim
  DNOTE    = 'D' ['.'] [notenums] -- dialect note; notenums are the
             following comma-separated numbers <= 12 ('325 D 1, 2'),
             a larger number starts a new ref ('214 D 5, 225.')
  'and D'  = dialect note of the SAME section ('127 and D')
  'N.'     = Note marker after a section/letter ('819 N.', '180 d N.')
  inherit  = a bare number <= 12 straight after an anchored ref is an
             inherited sub-anchor ('858. 6, 9' -> 858.9; '840 b, 5');
             bare a-h letters after a lettered ref inherit its section
             ('1797 a, b'; '489 e, f')
  'see X'  = cross-reference to another headword
  ordinals = '1 decl.', '2 aor.', '2d pers.' are prose, never refs
  'Introd./Intr. ...' = introduction reference -> unresolved (the
             English index records these the same way)

Python stdlib only. Deterministic: two runs produce identical output.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "work" / "greek-index"
OUT = ROOT / "data" / "smyth" / "index-greek.json"
OUT_ADJ = ROOT / "data" / "smyth" / "index-greek-adjudication.json"
ARCHIVE_ID = "greekgrammarforc0000herb"
GR = r"Ͱ-Ͽἀ-῿"

# D-note item list: '1' / '5 b' / '5 b and 8' / '1, 2' -- never crossing
# into a 3-digit section number (the \b after \d{1,2} stops it)
_DITEMS = r"\d{1,2}\b(?:\s[a-h]\b)?(?:\s*(?:,|and)\s*\d{1,2}\b(?:\s[a-h]\b)?)*"

TOK = re.compile(rf"""
    (?P<intro>\bIntr(?:od?)?\.\s*[A-E]\b
       (?:\s*,\s*N\.\s*\d+(?:\s*,\s*\d+)*)?)                # Intr. C, N. 1, 4
  | (?P<see>\b[Ss]ee\s+(?P<seetgt>[^;.]+))                  # see X
  | (?P<numgloss>\b\d{{1,3}},\d{{3}}\b)                     # '10,000' gloss
  | (?P<range>\b(?P<r1>[1-9]\d{{0,3}})-(?P<r2>[1-9]\d{{0,3}})\b) # 2110-2112
  | (?P<ff>\b(?P<fn>[1-9]\d{{0,3}})\s+ff\.)                 # 211 ff. (' f.' is
                                                            # letter f: every
                                                            # ' f.' cite has f
                                                            # in letters[])
  | (?P<ref>\b(?P<n>[1-9]\d{{0,3}})\b
       (?:\.\s(?P<sub>\d{{1,2}})(?:\s(?P<subl>[a-h])\b)?)?  # . 6 / . 2 b
       (?:\s(?P<letter>[a-hA-B])\b\.?)?                     # ' a' / ' A'
       (?:\s?(?P<andd>and\sD)\b\.?(?:\s(?P<andnums>{_DITEMS}))?)?  # 268 and D 2
       (?:\s(?P<dnote>D)\b\.?(?:\s(?P<dnums>{_DITEMS}))?)?  # 214 D 5 b and 8
       (?:\s(?P<nmark>N\.)(?:\s(?P<nnum>\d{{1,2}})\b)?)?    # 180 d N. / N. 2
    )
""", re.X)

ORDINAL_AFTER = re.compile(
    r"\s+(?:decl|aor|perf|pers|plur|sing|sg|conj|fut|du|dual|pl)\b")
ORDINAL_D = re.compile(r"\d[dh]\b")  # 2d / 3d pers. -- prose ordinals

# continuation items directly after a ref, all inheriting its section:
#   ', d'        letter list ('1797 a, b'; '238 c, d') -- lettered refs only
#   ', D' /
#   ', and D.'   trailing dialect note ('465 b, D'; '238 c, d, and D.')
#   'and f.'     conjoined letter ('2651 and f.')
#   ', N. 2'     note cite ('424 c, N. 2') -- must not fall through to the
#                bare-number inherited-anchor rule
CONT_ITEM = re.compile(r"""
    \s*,?\s*and\s(?:(?P<aD>D)\b\.?(?:\s(?P<aDn>\d{1,2}\b))?
                    |(?P<al>[a-h])\b\.?(?=[\s,;]|$))
  | \s*,\s*N\.\s*(?P<note>\d{1,2})\b
  | \s*,\s*(?P<bD>D)\b\.?(?=[\s,;]|$)
  | \s*,\s*(?P<letter>[a-h])\b\.?(?=[\s,;]|$)
""", re.X)


def parse_refs(text: str):
    """Scan descriptor text for refs.

    Returns (refs, crossRefs, unresolved, leftover_digit_spans)."""
    refs, cross, unresolved = [], [], []
    consumed = []
    last_anchored = False
    last_n = None
    for m in TOK.finditer(text):
        # continuation items (', N. 2', ', d') are consumed out-of-band;
        # the scanner must not re-match their digits as fresh refs
        if any(s <= m.start() < e for (s, e) in consumed):
            continue
        consumed.append((m.start(), m.end()))
        if m.group("numgloss"):
            # '10,000' (the meaning of μύριοι) -- prose, not refs
            last_anchored = False
            continue
        if m.group("intro"):
            unresolved.append({"verbatim": m.group("intro").strip(),
                               "reason": "introduction reference"})
            last_anchored = False
            continue
        if m.group("see"):
            cross.append(m.group("seetgt").strip().rstrip(","))
            last_anchored = False
            continue
        if m.group("range"):
            refs.append({"verbatim": m.group("range"),
                         "n": int(m.group("r1")), "to": int(m.group("r2"))})
            last_anchored, last_n = False, int(m.group("r1"))
            continue
        if m.group("ff"):
            refs.append({"verbatim": m.group("ff").strip(),
                         "n": int(m.group("fn")), "ff": True})
            last_anchored, last_n = False, int(m.group("fn"))
            continue
        # A parenthesized number after punctuation is the print's outline
        # marker for a long entry's numbered divisions ('μή, ... (1) In
        # indep. clauses'), never a citation: the eight markers on μή and ἤ
        # became refs to Sec. 1-5 and false inherited anchors, and the site
        # linked them (caught by grok's review of the index page,
        # 2026-08-05).  A parenthesized number after a LETTERED anchor is a
        # real sub-item citation and stays ('πάσχω, 463 b (1) D').
        ns, ne = m.start("n"), m.end("n")
        if text[ns - 1:ns] == "(" and text[ne:ne + 1] == ")":
            prev = text[:ns - 1].rstrip()
            if not prev or prev[-1] in ".,;:":
                last_anchored = False
                continue
        n1 = int(m.group("n"))
        verb = m.group("ref").strip().rstrip(".")
        anchor_bits = []
        if m.group("sub"):
            anchor_bits.append(m.group("sub"))
            if m.group("subl"):
                anchor_bits.append(m.group("subl"))
        if m.group("letter"):
            anchor_bits.append(m.group("letter"))
        has_d = bool(m.group("andd") or m.group("dnote"))
        # D-note items ('D 1, 2' / 'D 5 b and 8'): one ref per item, as
        # anchor strings the way index-english anchors D ('448 D' ->
        # anchor 'D'). A bare-number item > 12 is really the NEXT
        # section ('37 D 2, 39'), emitted as its own plain ref.
        d_items, d_extras = [], []
        if has_d:
            src = m.group("dnums") or m.group("andnums")
            if src:
                for part in re.split(r"\s*(?:,|and)\s*", src):
                    part = part.strip()
                    if part.isdigit() and int(part) > 12:
                        d_extras.append(int(part))
                    elif part:
                        d_items.append(part)
            if not d_items and not d_extras:
                d_items = [""]
        if (not anchor_bits and not has_d and not m.group("nmark")
                and ORDINAL_AFTER.match(text, m.end())):
            last_anchored = False
            continue
        if (not anchor_bits and not m.group("nmark")
                and last_anchored and n1 <= 12):
            anchor = str(n1) + (" D" if has_d else "")
            refs.append({"verbatim": verb, "n": last_n,
                         "anchor": anchor, "inherited": True})
            continue
        ref = {"verbatim": verb, "n": n1}
        if anchor_bits:
            ref["anchor"] = " ".join(anchor_bits)
        if m.group("nmark"):
            ref["note"] = m.group("nnum") or ""
        if m.group("dnote") and not anchor_bits and "note" not in ref:
            # bare 'N D ...': the first D item anchors this ref itself;
            # 'N and D ...' keeps the plain ref AND adds the D refs
            ref["anchor"] = ("D " + d_items[0]).strip() if d_items else "D"
            d_items = d_items[1:]
        refs.append(ref)
        for it in d_items:
            refs.append({"verbatim": it or "D", "n": n1,
                         "anchor": ("D " + it).strip(),
                         "inherited": True})
        for extra in d_extras:
            refs.append({"verbatim": str(extra), "n": extra})
        last_anchored = bool(anchor_bits) or has_d
        last_n = n1
        pos = m.end()
        while True:
            cm = CONT_ITEM.match(text, pos)
            if not cm:
                break
            if cm.group("letter"):
                # bare letter lists attach only to already-lettered refs;
                # after a plain number a lone ', d' is prose
                if not anchor_bits:
                    break
                refs.append({"verbatim": cm.group("letter"), "n": n1,
                             "anchor": cm.group("letter"),
                             "inherited": True})
            elif cm.group("al"):
                refs.append({"verbatim": "and " + cm.group("al"), "n": n1,
                             "anchor": cm.group("al"), "inherited": True})
            elif cm.group("aD") or cm.group("bD"):
                dn = (cm.group("aDn") or "").strip()
                refs.append({"verbatim": ("and D" if cm.group("aD")
                                          else "D") + (" " + dn if dn else ""),
                             "n": n1,
                             "anchor": ("D " + dn).strip() if dn else "D",
                             "inherited": True})
            elif cm.group("note"):
                refs.append({"verbatim": "N. " + cm.group("note"), "n": n1,
                             "note": cm.group("note"), "inherited": True})
            consumed.append((pos, cm.end()))
            pos = cm.end()
    leftovers = []
    for dm in re.finditer(r"\d+", text):
        if any(s <= dm.start() < e for (s, e) in consumed):
            continue
        if ORDINAL_D.match(text, dm.start()):
            continue  # '2d pers.', '3d pers.' -- prose
        leftovers.append(text[max(0, dm.start() - 15):dm.end() + 10])
    return refs, cross, unresolved, leftovers


def split_head(raw: str) -> tuple[str, str]:
    """Head = up to the first comma OUTSIDE parentheses; rest follows.

    A plain comma split truncated parenthetical heads:
    'ᾱ (Dor., Aeol.) for η, 31, ...' must keep '(Dor., Aeol.)' whole.
    Strips the one recorded stray transcription quote off the head.
    """
    depth = 0
    cut = len(raw)
    for i, ch in enumerate(raw):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif ch == "," and depth == 0:
            cut = i
            break
    head = re.sub(r'^["“”]\s*', "", raw[:cut].strip())
    return head, raw[cut + 1:]


def main() -> None:
    raw_entries = json.loads(
        (WORK / "greek-entries-raw.json").read_text(encoding="utf-8"))
    entries, unresolved_all, leftovers_all = [], [], []
    for e in raw_entries:
        raw = e["raw"]
        head, body = split_head(raw)
        refs, cross, unresolved, left = parse_refs(body)
        if re.search(r"\d", head):
            # a parenthetical head can carry refs of its own ('οὔ (οὐκ,
            # οὐχ, 133 a, 137, ...)') -- they precede the body's refs
            hrefs, hcross, hunres, hleft = parse_refs(head)
            refs = hrefs + refs
            cross = hcross + cross
            unresolved = hunres + unresolved
            left = hleft + left
        ent = {"headword": unicodedata.normalize("NFC", head),
               "raw": unicodedata.normalize("NFC", raw),
               "pages": [e["page"]],
               "refs": refs}
        if cross:
            ent["crossRefs"] = cross
        fm = re.search(r"([οηω])/([εη])", head)
        if fm:
            # the print stacks one vowel over another (either/or suffix
            # vowel: 8x ο/ε, 1x η/ε, 1x ω/η); the corpus text carries
            # Perseus's flattened glued form with the acute on the first
            # vowel (-ανόε-, -ώη-), so a lookup must hit under every
            # notation
            acute = {"ο": "ό", "η": "ή", "ω": "ώ"}
            ent["searchKeys"] = [
                head.replace(fm.group(0), acute[fm.group(1)] + fm.group(2)),
                head.replace(fm.group(0), fm.group(1)),
                head.replace(fm.group(0), fm.group(2)),
            ]
        ent["src"] = {"startLine": e["startLine"], "indent": e["indent"]}
        entries.append(ent)
        for u in unresolved:
            unresolved_all.append({"headword": head, **u})
        for l in left:
            leftovers_all.append({"headword": head, "at": l})

    ref_count = sum(len(e["refs"]) for e in entries)
    doc = {
        "work": "smyth",
        "source": {
            "archiveId": ARCHIVE_ID,
            "edition": ("Herbert Weir Smyth, A Greek Grammar for Colleges, "
                        "New York: American Book Company, 1920"),
            "pages": "757-784",
            "leaves": "777-804",
            "url": f"https://archive.org/details/{ARCHIVE_ID}",
        },
        "entries": entries,
        "_meta": {
            "status": "print-1920",
            "entryCount": len(entries),
            "refCount": ref_count,
            "crossRefCount": sum(len(e.get("crossRefs", []))
                                 for e in entries),
            "unresolvedRefs": unresolved_all,
            "parserLeftovers": leftovers_all,
            "pipeline": "work/greek-index/ (four-reader adjudication)",
        },
    }
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n",
                   encoding="utf-8")

    # adjudication summary: counts + the machine transforms, with
    # pointers into the committed primary record in work/greek-index/
    def load(name):
        return json.loads((WORK / name).read_text(encoding="utf-8"))

    s3 = load("apply-stage3-report.json")
    adj = {
        "work": "smyth",
        "primaryRecord": "work/greek-index/",
        "decisions": {
            "part1": "work/greek-index/greek-decisions-part1.json",
            "part2": "work/greek-index/greek-decisions-part2.json",
            "unanimityAudit": "work/greek-index/greek-decisions-audit.json",
            "calibration":
                "work/greek-index/greek-decisions-calibration.json",
            "consolidated":
                "work/greek-index/greek-rulings-consolidated.json",
        },
        "stage1": load("apply-stage1-report.json"),
        "stage2": load("apply-stage2-report.json"),
        "stage3": s3,
        "stage4": {
            "unresolvedRefs": unresolved_all,
            "parserLeftovers": leftovers_all,
        },
    }
    OUT_ADJ.write_text(json.dumps(adj, indent=1, ensure_ascii=False) + "\n",
                       encoding="utf-8")
    print(f"entries {len(entries)}  refs {ref_count}  "
          f"crossRefs {doc['_meta']['crossRefCount']}  "
          f"unresolved {len(unresolved_all)}  "
          f"leftovers {len(leftovers_all)}  -> {OUT}")


if __name__ == "__main__":
    main()
