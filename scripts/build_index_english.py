#!/usr/bin/env python3
"""Assemble data/smyth/index-english.json from the per-page transcriptions.

The per-page files in data/smyth/index-english-pages/ are the primary record:
one file per printed page, holding the raw lines a transcriber read and the
structured parse of each entry. This script is pure concatenation plus the two
normalisations documented in SPEC-index-english.md:

  1. entries flagged "continued from previous page" are stitched onto the
     fragment that ends the previous page;
  2. page/column bookkeeping is folded into a `pages` list per entry.

Nothing here reads an image or invents a number.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE_DIR = ROOT / "data" / "smyth" / "index-english-pages"
OUT = ROOT / "data" / "smyth" / "index-english.json"
FIRST_PAGE, LAST_PAGE = 723, 756
ARCHIVE_ID = "smyth-greek-grammar-for-colleges-1920"


def load_pages() -> list[dict]:
    pages = []
    for n in range(FIRST_PAGE, LAST_PAGE + 1):
        path = PAGE_DIR / f"page-{n:04d}.json"
        if not path.exists():
            raise SystemExit(f"missing page file: {path}")
        pages.append(json.loads(path.read_text(encoding="utf-8")))
    return pages


def join_text(head: str, tail: str) -> str:
    """Join two halves of one paragraph split by a page break.

    Three cases, decided by what the break falls on:
      'preced-' + 'ing'   -> word division: drop the hyphen, no space
      'stems, 496-' + '531' -> a section range: keep the hyphen, no space
      'of pred.' + 'adj.' -> ordinary break: one space
    """
    head, tail = head.rstrip(), tail.lstrip()
    if not head:
        return tail
    if not tail:
        return head
    if head.endswith("-"):
        if head[-2:-1].isdigit() and tail[0].isdigit():
            return head + tail
        return head[:-1] + tail
    return head + " " + tail


def join_refs(head_refs: list[dict], tail_refs: list[dict]) -> list[dict]:
    """Concatenate two ref lists, closing a range broken by the page turn."""
    if head_refs and tail_refs:
        last, first = head_refs[-1], tail_refs[0]
        if (last.get("verbatim", "").endswith("-") and "to" not in last
                and "n" in last and first.get("n") is not None
                and not first.get("anchor") and first["n"] > last["n"]):
            last["to"] = first["n"]
            last["verbatim"] = last["verbatim"] + first.get("verbatim", "")
            last["splitAcrossPages"] = True
            tail_refs = tail_refs[1:]
    return head_refs + tail_refs


def merge(prev: dict, frag: dict) -> None:
    """Stitch a page-break continuation onto the entry it belongs to.

    The break can fall in the middle of the main paragraph or in the middle of
    a sub-entry. An unfinished sub-entry is one whose text does not end in a
    full point; the fragment then belongs to it, not to the main paragraph.
    """
    subs = prev.setdefault("sub", []) if prev.get("sub") else []
    open_sub = subs[-1] if subs and not subs[-1]["raw"].rstrip().endswith(".") else None

    frag_subs = list(frag.get("sub", []))
    if frag.get("raw"):
        if open_sub is not None:
            open_sub["raw"] = join_text(open_sub["raw"], frag["raw"])
            open_sub["refs"] = join_refs(open_sub.get("refs", []), frag["refs"])
        else:
            prev["raw"] = join_text(prev["raw"], frag["raw"])
            prev["refs"] = join_refs(prev["refs"], frag["refs"])
    elif frag["refs"]:
        prev["refs"] = join_refs(prev["refs"], frag["refs"])
    elif (open_sub is not None and frag_subs
          and frag_subs[0]["label"] == open_sub["label"]):
        # the sub-entry itself runs over the page turn
        head = frag_subs.pop(0)
        open_sub["raw"] = join_text(open_sub["raw"], head["raw"])
        open_sub["refs"] = join_refs(open_sub.get("refs", []), head.get("refs", []))
        if head.get("crossRefs"):
            open_sub.setdefault("crossRefs", []).extend(head["crossRefs"])

    if frag_subs:
        prev.setdefault("sub", []).extend(frag_subs)
    if frag.get("crossRefs"):
        prev.setdefault("crossRefs", []).extend(frag["crossRefs"])
    notes = [t for t in (prev.get("notes"), frag.get("notes")) if t]
    if notes:
        prev["notes"] = " ".join(notes)
    prev["wrapped"] = True
    prev["pages"] = sorted(set(prev["pages"] + frag["pages"]))


def main() -> None:
    pages = load_pages()
    entries: list[dict] = []
    unresolved: list[dict] = []

    for page in pages:
        pno = page["page"]
        for raw_entry in page["entries"]:
            entry = {
                "headword": raw_entry["headword"],
                "raw": raw_entry["raw"],
                "pages": [pno],
                "wrapped": bool(raw_entry.get("wrapped")),
                "refs": [dict(r) for r in raw_entry.get("refs", [])],
            }
            for key in ("sub", "crossRefs", "notes"):
                if raw_entry.get(key):
                    entry[key] = raw_entry[key]

            if raw_entry.get("wrapNote") == "continued from previous page":
                if not entries:
                    raise SystemExit(
                        f"page {pno}: continuation with nothing to attach it to")
                merge(entries[-1], entry)
            else:
                entries.append(entry)

    for entry in entries:
        for ref in entry["refs"] + [r for s in entry.get("sub", [])
                                    for r in s.get("refs", [])]:
            if "n" not in ref:
                unresolved.append({
                    "headword": entry["headword"],
                    "pages": entry["pages"],
                    "verbatim": ref.get("verbatim", ""),
                    "reason": ("unreadable" if ref.get("unreadable")
                               else "not a section reference"),
                })

    ref_count = sum(len(e["refs"]) + sum(len(s.get("refs", []))
                                         for s in e.get("sub", []))
                    for e in entries)

    doc = {
        "work": "smyth",
        "source": {
            "archiveId": ARCHIVE_ID,
            "edition": ("Herbert Weir Smyth, A Greek Grammar for Colleges, "
                        "New York: American Book Company, 1920"),
            "pages": f"{FIRST_PAGE}-{LAST_PAGE}",
            "leaves": f"{FIRST_PAGE + 13}-{LAST_PAGE + 13}",
            "url": f"https://archive.org/details/{ARCHIVE_ID}",
        },
        "entries": entries,
        "_meta": {
            "status": "print-1920",
            "entryCount": len(entries),
            "refCount": ref_count,
            "pageCount": len(pages),
            "perPageSource": "data/smyth/index-english-pages/page-NNNN.json",
            "unresolvedRefs": unresolved,
        },
    }
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(f"entries {len(entries)}  refs {ref_count}  "
          f"unresolved {len(unresolved)}  -> {OUT}")


if __name__ == "__main__":
    main()
