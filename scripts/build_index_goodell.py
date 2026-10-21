#!/usr/bin/env python3
"""Extract Goodell's English Index from the DCC mirror.

Source: grammar-goodell/src/dcc/english-index.html (the same mirror
convert_goodell.py reads). The index is born-digital — one <br>-separated
line per entry, every section citation wrapped in a link whose href names
the target chapter page — so unlike Smyth's scan-transcribed index there
are no page files and no transcription passes; this script is the whole
pipeline, and verify_index_goodell.py re-derives its output and checks
the links against data/goodell/sections.jsonl.

Output: data/goodell/index-english.json, in the Smyth reference
vocabulary (SPEC-index-english.md §4): every ref keeps `verbatim` exactly
as printed, with `n`/`to`/`anchor` normalised alongside, `inherited` for
anchors the print elides ("456.b & c"), and `nonSection` for the
Introduction citations. Entry shape matches Smyth's minus the fields that
only exist for a scan (pages, wrapped, sub).
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import unquote, urlparse

import convert_goodell as cg

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "grammar-goodell" / "src" / "dcc" / "english-index.html"
OUT = ROOT / "data" / "goodell" / "index-english.json"
LAST_SECTION = 683

# One citation token as DCC links it: "391", "9-15", "402 – 414", "5.b",
# "445 b", "362 (3)", plus "&"-compounds handled in parse_ref_token.
TOKEN_RE = re.compile(
    r"^(\d+)"  # section
    r"(?:\s*[-–]\s*(\d+))?"  # range end
    r"(?:\.(\w+)|\s+([a-z])\b|\s*\((\d+)\))?"  # anchor: .b / 445 b / (3)
    r"\.?$"
)


def decode_fragment(fragment: str) -> int | None:
    """DCC fragments spell the section digit by digit: three-nine-one -> 391.

    Split on every non-letter run, not just '-': a few index hrefs have
    broken attribute quoting ("#four-three-three target=") that would
    otherwise truncate the number.
    """
    digits = "".join(
        cg.WORD_NUMBER[word]
        for word in re.split(r"[^a-z]+", fragment.lower())
        if word in cg.WORD_NUMBER
    )
    return int(digits) if digits else None


# Defects in the DCC index page itself, corrected here so the entry can
# align and slugify; each repair keeps the source string in _meta.repairs.
HEADWORD_REPAIRS = {
    "Relexive pronouns": "Reflexive pronouns",  # DCC typo; §§197-201 spell it Reflexive
}

# DCC sets these alphabetically distinct entries on one <br> line; the
# marker text starts the entry that must be split off. Recorded in
# _meta.repairs.
LINE_SPLITS = ["Consonants, classified"]


def line_items(block: cg.Node) -> list[list[dict]]:
    """Split a block into <br>-separated lines of {text, href, link} items.

    Link text and plain text stay separate items, in document order, so a
    citation keeps the href that names its target chapter page. `link` is
    true for any <a> — a few of the page's citation links carry no href
    at all, and their text is still a citation.
    """
    lines: list[list[dict]] = [[]]

    def walk(node: cg.Node | str, href: str | None, link: bool) -> None:
        if isinstance(node, str):
            lines[-1].append({"text": node, "href": href, "link": link})
        elif node.tag == "br":
            lines.append([])
        elif node.tag == "a":
            for child in node.children:
                walk(child, node.attrs.get("href") or None, True)
        elif node.tag not in {"script", "style", "meta", "img", "iframe", "form", "input"}:
            for child in node.children:
                walk(child, href, link)

    walk(block, None, False)
    merged: list[list[dict]] = []
    for line in lines:
        items: list[dict] = []
        for item in line:
            if items and items[-1]["href"] == item["href"] and items[-1]["link"] == item["link"]:
                items[-1]["text"] += item["text"]
            else:
                items.append(dict(item))
        if cg.norm("".join(i["text"] for i in items)):
            merged.append(items)
    return merged


def split_fused(lines: list[list[dict]]) -> tuple[list[list[dict]], list[dict]]:
    """Split the known fused lines (LINE_SPLITS) into separate entries."""
    out: list[list[dict]] = []
    repairs: list[dict] = []
    for items in lines:
        text = cg.norm("".join(i["text"] for i in items))
        marker = next((m for m in LINE_SPLITS if f"; {m}" in text), None)
        if not marker:
            out.append(items)
            continue
        first: list[dict] = []
        second: list[dict] = []
        target = first
        for item in items:
            at = item["text"].find(marker)
            semi = item["text"].rfind(";", 0, at) if at != -1 else -1
            if target is first and at != -1 and semi != -1:
                head = dict(item, text=item["text"][:semi])
                tail = dict(item, text=item["text"][at:])
                if cg.norm(head["text"]):
                    first.append(head)
                target = second
                target.append(tail)
            else:
                target.append(item)
        if target is first:
            raise SystemExit(f"LINE_SPLITS marker {marker!r} matched the line "
                             "but not inside a single item")
        out.extend([first, second])
        repairs.append({
            "split": marker.split(",")[0],
            "source": "two entries on one line in the DCC page",
        })
    return out, repairs


def parse_ref_token(verbatim: str, href: str | None) -> list[dict] | None:
    """One linked token -> its refs, or None when it is not a citation.

    Compound tokens yield several refs, whether joined by "&" or commas:
    "349 & 349.a" is two explicit refs; "456.b & c" and "638.a, b, d & e"
    carry inherited anchors — the print elides the repeated section
    number, so each elided ref is flagged `inherited`.
    """
    slug = ""
    fragment_n = None
    if href:
        parsed = urlparse(href)
        path = unquote(parsed.path).rstrip("/")
        tail = path.rsplit("/", 1)[-1]
        # A few citations link "chapters/Chapter-NNN" instead of a chapter
        # page: the number is a section hint, and there is no slug to check.
        chapter = re.fullmatch(r"Chapter-(\d+)", tail)
        if chapter:
            fragment_n = int(chapter.group(1))
        else:
            slug = tail
            fragment_n = decode_fragment(parsed.fragment) if parsed.fragment else None

    verbatim = verbatim.strip().strip(",").rstrip(".")
    if verbatim == "Introduction":
        return [{
            "verbatim": "Introduction", "nonSection": True,
            "_slug": slug, "_fragment_n": fragment_n,
        }]

    refs: list[dict] = []
    base_n: int | None = None
    for i, part in enumerate(re.split(r"\s*[&,]\s*", verbatim)):
        part = part.strip()
        m = TOKEN_RE.match(part)
        if m:
            n = int(m.group(1))
            ref: dict = {"verbatim": part.rstrip("."), "n": n}
            if m.group(2):
                ref["to"] = int(m.group(2))
            anchor = m.group(3) or m.group(4) or (f"({m.group(5)})" if m.group(5) else "")
            if anchor:
                ref["anchor"] = anchor
            base_n = n
        elif i and base_n is not None and re.fullmatch(r"[a-z]\.?", part):
            ref = {
                "verbatim": part.rstrip("."), "n": base_n,
                "anchor": part.rstrip("."), "inherited": True,
            }
        else:
            return None
        ref["_slug"] = slug
        ref["_fragment_n"] = fragment_n
        refs.append(ref)
    return refs


CROSS_REF_RE = re.compile(r"\b[Ss]ee (?:also )?([^;.]+)")


DASH_RE = re.compile(r"^[-–]$")


def parse_entry(items: list[dict]) -> dict:
    raw = cg.norm("".join(item["text"] for item in items))
    refs: list[dict] = []
    first_ref_start: int | None = None
    consumed = 0
    # last single-§ ref, kept only while the text after it is empty or a
    # bare range dash — DCC links each endpoint of "38 – 56" separately.
    open_range: dict | None = None
    between = ""
    for item in items:
        text = cg.norm(item["text"])
        if item["link"] and text:
            parsed = parse_ref_token(text, item["href"])
            if parsed is None:
                if re.search(r"\d", text):
                    raise SystemExit(
                        f"unparsed citation link {text!r} in line: {raw[:80]!r}")
            else:
                if first_ref_start is None:
                    first_ref_start = raw.index(text, consumed)
                if (open_range is not None and DASH_RE.match(between.strip())
                        and len(parsed) == 1 and parsed[0].get("n") is not None
                        and "anchor" not in parsed[0] and "to" not in parsed[0]
                        and parsed[0]["n"] > open_range["n"]):
                    # the two linked endpoints of one printed range
                    open_range["to"] = parsed[0]["n"]
                    open_range["verbatim"] += f" {between.strip()} {parsed[0]['verbatim']}"
                else:
                    refs.extend(parsed)
                last = refs[-1]
                open_range = (
                    last if last.get("n") is not None
                    and "to" not in last and "anchor" not in last else None
                )
                between = ""
        elif text:
            between += (" " if between else "") + text
            if not DASH_RE.match(between.strip()):
                open_range = None
        if text:
            consumed = raw.index(text, consumed) + len(text)

    head_limit = first_ref_start if first_ref_start is not None else len(raw)
    comma = raw.find(",")
    if 0 <= comma < head_limit:
        headword = raw[:comma]
    else:
        headword = raw[:head_limit].rstrip()
    headword = headword.rstrip(" ,.")
    if not headword:
        raise SystemExit(f"empty headword for line: {raw[:80]!r}")

    entry: dict = {"headword": headword, "raw": raw, "refs": refs}
    if headword in HEADWORD_REPAIRS:
        fixed = HEADWORD_REPAIRS[headword]
        entry["headword"] = fixed
        entry["raw"] = fixed + raw[len(headword):]
        entry["_repair"] = {"headword": fixed, "source": headword}
    cross = [
        name.strip().rstrip(",")
        for m in CROSS_REF_RE.finditer(raw)
        for name in re.split(r",| and ", m.group(1))
        if name.strip()
    ]
    if cross:
        entry["crossRefs"] = cross
    return entry


def extract(source: Path = SOURCE) -> dict:
    parser = cg.TreeBuilder()
    parser.feed(unicodedata.normalize("NFC", source.read_text(encoding="utf-8")))
    parser.close()
    body = cg.article_body(cg.find_article(parser.root))

    lines: list[list[dict]] = []
    for block in cg.relevant_blocks(body):
        lines.extend(line_items(block))

    preamble = cg.norm("".join(i["text"] for i in lines[0]))
    letter_nav = cg.norm("".join(i["text"] for i in lines[1]))
    if not preamble.startswith("The Indices") or "|" not in letter_nav:
        raise SystemExit("english-index.html no longer opens with the "
                         "preamble and letter navigation this script expects")

    entry_lines, split_repairs = split_fused(lines[2:])
    entries = [parse_entry(items) for items in entry_lines]

    unresolved = [
        {"headword": e["headword"], "verbatim": r["verbatim"],
         "reason": "not a section reference"}
        for e in entries for r in e["refs"] if "n" not in r
    ]
    repairs = [e.pop("_repair") for e in entries if "_repair" in e] + split_repairs
    doc = {
        "work": "goodell",
        "source": {
            "edition": ("Thomas Dwight Goodell, A School Grammar of Attic "
                        "Greek, DCC corrected edition, ed. Meagan Ayer et al."),
            "url": "https://dcc.dickinson.edu/grammar/goodell/english-index",
            "file": "grammar-goodell/src/dcc/english-index.html",
            "license": "CC BY-SA",
            "preamble": preamble,
        },
        "entries": entries,
        "_meta": {
            "status": "dcc-digital",
            "entryCount": len(entries),
            "refCount": sum(len(e["refs"]) for e in entries),
            "crossRefCount": sum(len(e.get("crossRefs", [])) for e in entries),
            "inheritedCount": sum(
                1 for e in entries for r in e["refs"] if r.get("inherited")),
            "unresolvedRefs": unresolved,
            "repairs": repairs,
        },
    }
    return doc


def strip_internal(doc: dict) -> dict:
    for entry in doc["entries"]:
        for ref in entry["refs"]:
            ref.pop("_slug", None)
            ref.pop("_fragment_n", None)
    return doc


def main() -> None:
    doc = strip_internal(extract())
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    meta = doc["_meta"]
    print(f"entries {meta['entryCount']}  refs {meta['refCount']}  "
          f"inherited {meta['inheritedCount']}  "
          f"unresolved {len(meta['unresolvedRefs'])}  -> {OUT}")


if __name__ == "__main__":
    main()
