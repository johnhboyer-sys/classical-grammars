#!/usr/bin/env python3
"""Convert the Perseus TEI P5 Allen & Greenough grammar to deterministic JSON.

Unlike the Smyth source, which nests every section in its own ``div``, this
text marks sections with empty ``milestone`` elements: a section owns every
block-level child of a ``div`` that follows its marker in document order, which
means a section routinely runs past the end of the ``div`` it started in.  The
converter walks the body once in document order and assigns blocks to the
marker in force.

The printed grammar ends at section 638.  The source numbers the closing
glossary 639-642 as if those were printed sections; that glossary is back
matter, so it stays out of the section records and is inventoried in the meta
instead.  The converter performs no network access.
"""

from __future__ import annotations

import argparse
import collections
import html
import json
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = (
    ROOT
    / "grammar-ag-tei"
    / "data"
    / "viaf39744457"
    / "001"
    / "viaf39744457.001.perseus-eng1.xml"
)
DEFAULT_SECTIONS = ROOT / "data" / "ag" / "sections.jsonl"
DEFAULT_META = ROOT / "data" / "ag" / "meta.json"

XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
TEI_NS = "{http://www.tei-c.org/ns/1.0}"
# The head of the div holding the closing glossary, which the source numbers
# 639-642 although the printed grammar stops at 638.
GLOSSARY_HEAD = "GLOSSARY: OF TERMS USED IN GRAMMAR, RHETORIC, AND PROSODY"
LAST_PRINTED_SECTION = 638
# Block-level children of a div; everything else nests inside one of these.
CONTENT_TAGS = {"p", "table", "list", "note", "pb", "milestone"}
DASH = "[-–—]"
RANGE_TAIL_RE = re.compile(rf"^\s*{DASH}\s*(\d+)")
BARE_DASH_RE = re.compile(rf"^\s*{DASH}\s*$")
LABEL_RE = re.compile(r"([a-z])\.")
LOOSE_LABEL_RE = re.compile(r"^([a-z])\.\s")
TAG_RE = re.compile(r"<[^>]+>")
# A source reference the print sets in brackets and the source left untagged:
# "(Plaut. Pseud. 468)", "(Aen. 5.488)".  It holds a digit and either an
# abbreviation closed by a period or a book.line locus.  "(March 28)", which
# stands inside a real translation at Sec. 424, has neither and is not one.
UNTAGGED_REFERENCE_RE = re.compile(
    r"\((?=[^()]*\d)[^()]*?(?:[A-Za-z]\.\s|\d+\.\d)[^()]*\)"
)


LOOSE_BREVE = re.compile("([\u0101\u0113\u012b\u014d\u016b\u0233\u0100\u0112\u012a\u014c\u016a\u0232])\u02d8")
# Signs Perseus could not type, left under a placeholder name, and the pause
# sign typed as a look-alike; each written as the 1903 print shows it (§§ 608
# ff., checked on the scans). No character exists for > set over a breve, so
# that one is a breve with a combining right arrowhead above.
MARKS = {
    "[acutemacr]": "\u00af\u0301",   # long, with ictus
    "[acutebreve]": "\u02d8\u0301",  # short, with ictus
    "[macrcirc]": "\u22bc",          # pause of two morae
    "[gtbreve]": "\u02d8\u0350",     # irrational long or short
    "[wacute]": "\u1e83",            # floẃerets
    "\u02c6": "\u2227",              # pause of one mora, typed as ˆ
}


def repair(text: str) -> str:
    """The source as the print reads, before any parsing: NFC, a doubly
    marked vowel's breve back on its letter, and each placeholder sign
    written out. A ˘ standing alone is a metrical sign and stays."""
    text = LOOSE_BREVE.sub("\\1\u0306", unicodedata.normalize("NFC", text))
    for name, sign in MARKS.items():
        text = text.replace(name, sign)
    return text


def norm(text: str | None) -> str:
    """Collapse source formatting whitespace without changing other text."""
    return re.sub(r"\s+", " ", text or "").strip()


def json_line(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def text_of(elem: ET.Element) -> str:
    return norm("".join(elem.itertext()))


def language_of(elem: ET.Element) -> str:
    return (elem.get(XML_LANG) or elem.get("lang") or "").lower()


def first_head(elem: ET.Element) -> str | None:
    for child in elem:
        if child.tag == "head":
            return text_of(child) or None
    return None


def ancestor_divs(
    elem: ET.Element, parents: dict[ET.Element, ET.Element]
) -> list[ET.Element]:
    """Return the titled ancestor divs of an element, outermost first."""
    found: list[ET.Element] = []
    current = parents.get(elem)
    while current is not None:
        if current.tag == "div" and current.get("type") != "edition":
            found.append(current)
        current = parents.get(current)
    found.reverse()
    return found


def parse_ref(elem: ET.Element) -> int | None:
    value = elem.get("n") or text_of(elem)
    match = re.search(r"\d+", value)
    return int(match.group()) if match else None


def ref_letter(
    ref: ET.Element, siblings: list[ET.Element], index: int
) -> str | None:
    """Read the subsection letter of a ``§ 598. f`` cross-reference.

    The source splits such a citation across three nodes: the ``ref`` holding
    the number, a "." in its tail, and an ``emph`` holding the bare letter.
    """
    if norm(ref.tail) != ".":
        return None
    following = siblings[index + 1] if index + 1 < len(siblings) else None
    if following is None or following.tag != "emph":
        return None
    match = re.fullmatch(r"([a-z])\.?", text_of(following))
    return match.group(1) if match else None


def find_ref_ranges(
    root: ET.Element,
) -> tuple[list[dict[str, int]], dict[ET.Element, list[dict[str, int]]]]:
    """Find ranges written as a ref, a dash, and either a ref or a number."""
    all_ranges: list[dict[str, int]] = []
    by_ref: dict[ET.Element, list[dict[str, int]]] = collections.defaultdict(list)

    def add(ref: ET.Element, start: int | None, end: int | None) -> None:
        if start is None or end is None:
            return
        value = {"start": start, "end": end}
        if value not in by_ref[ref]:
            by_ref[ref].append(value)
        if value not in all_ranges:
            all_ranges.append(value)

    for parent in root.iter():
        children = list(parent)
        for index, child in enumerate(children):
            if child.tag != "ref":
                continue
            start = parse_ref(child)
            tail = child.tail or ""
            numeric_end = RANGE_TAIL_RE.match(tail)
            if numeric_end:
                add(child, start, int(numeric_end.group(1)))
                continue
            if (
                BARE_DASH_RE.match(tail)
                and index + 1 < len(children)
                and children[index + 1].tag == "ref"
            ):
                add(child, start, parse_ref(children[index + 1]))
    return all_ranges, by_ref


class Renderer:
    """Small, explicit TEI-to-HTML renderer with no source attributes leaked."""

    def __init__(
        self,
        parents: dict[ET.Element, ET.Element],
        letter_markers: dict[ET.Element, str],
        note_anchors: dict[ET.Element, tuple[str, str]],
        ref_anchors: dict[ET.Element, str],
    ) -> None:
        self.parents = parents
        self.letter_markers = letter_markers
        self.note_anchors = note_anchors
        self.ref_anchors = ref_anchors

    @staticmethod
    def _text(value: str | None) -> str:
        if not value:
            return ""
        return html.escape(re.sub(r"\s+", " ", value), quote=False)

    def inner(self, elem: ET.Element) -> str:
        chunks = [self._text(elem.text)]
        for child in elem:
            chunks.append(self.element(child))
            chunks.append(self._text(child.tail))
        return "".join(chunks)

    def is_block(self, elem: ET.Element) -> bool:
        """Report whether the element renders as HTML that <p> cannot contain."""
        return elem.tag in {"table", "list"} or self.note_is_aside(elem)

    def note_is_aside(self, elem: ET.Element) -> bool:
        """A note becomes an <aside> unless it sits in phrasing-only markup."""
        if elem.tag != "note":
            return False
        parent = self.parents.get(elem)
        return parent is None or parent.tag in {"p", "div", "item", "cell", "table", "list"}

    def element(self, elem: ET.Element) -> str:
        tag = elem.tag
        anchor = self.letter_markers.get(elem)
        anchor_attr = f' id="{html.escape(anchor, quote=True)}"' if anchor else ""

        if tag == "p":
            return self.paragraph(elem, anchor_attr)
        if tag == "table":
            return self.table(elem, anchor_attr)
        if tag == "list":
            return self.listing(elem, anchor_attr)
        if tag == "milestone":
            return self.milestone(elem)

        content = self.inner(elem)
        if tag == "foreign":
            language = language_of(elem)
            code = {"greek": "grc"}.get(language, language)
            lang_attr = f' lang="{html.escape(code, quote=True)}"' if code else ""
            return f"<span{lang_attr}{anchor_attr}>{content.strip()}</span>"
        if tag == "quote":
            language = language_of(elem)
            code = {"greek": "grc"}.get(language, language)
            lang_attr = f' lang="{html.escape(code, quote=True)}"' if code else ""
            return f"<q{lang_attr}{anchor_attr}>{content.strip()}</q>"
        if tag == "gloss":
            return f'<span class="gloss"{anchor_attr}>{content.strip()}</span>'
        if tag == "emph":
            rend = (elem.get("rend") or "").lower()
            if rend in {"", "ital"}:
                return f"<em{anchor_attr}>{content.strip()}</em>"
            if rend == "strikethrough":
                return f"<s{anchor_attr}>{content.strip()}</s>"
            css = html.escape(rend, quote=True)
            return f'<span class="rend-{css}"{anchor_attr}>{content.strip()}</span>'
        if tag == "ref":
            target = parse_ref(elem)
            if target is None:
                return content.strip()
            letter = self.ref_anchors.get(elem)
            letter_attr = f' data-anchor="{letter}"' if letter else ""
            return f'<a data-ref="ag:{target}"{letter_attr}>{content.strip()}</a>'
        if tag == "bibl":
            cite = elem.get("n") or text_of(elem)
            cite_attr = html.escape(cite, quote=True)
            return f'<cite data-cite="{cite_attr}"{anchor_attr}>{content.strip()}</cite>'
        if tag == "cit":
            return f'<span class="example"{anchor_attr}>{content.strip()}</span>'
        if tag == "item":
            attrs = anchor_attr
            if (value := elem.get("n")) and value.isdigit():
                attrs += f' value="{value}"'
            return f"<li{attrs}>{content.strip()}</li>"
        if tag == "row":
            return f"<tr{anchor_attr}>{content.strip()}</tr>"
        if tag == "cell":
            attrs = anchor_attr
            if (cols := elem.get("cols")) and cols.isdigit() and cols != "1":
                attrs += f' colspan="{cols}"'
            if (rows := elem.get("rows")) and rows.isdigit() and rows != "1":
                attrs += f' rowspan="{rows}"'
            return f"<td{attrs}>{content.strip()}</td>"
        if tag == "pb":
            page = html.escape(elem.get("n", ""), quote=True)
            return f'<span class="page-break" data-page="{page}"></span>'
        if tag == "note":
            note_anchor, kind = self.note_anchors.get(elem, ("", "note"))
            id_attr = (
                f' id="{html.escape(note_anchor, quote=True)}"' if note_anchor else ""
            )
            if not self.note_is_aside(elem):
                # A note inside phrasing-only markup keeps its anchor on a span.
                return f'<span class="{kind}"{id_attr}>{content.strip()}</span>'
            label = elem.get("n")
            label_attr = (
                f' data-label="{html.escape(label, quote=True)}"' if label else ""
            )
            return (
                f'<aside class="{kind}"{id_attr}{label_attr}>{content.strip()}</aside>'
            )
        if tag == "figure":
            return f'<span class="figure"{anchor_attr}>{content.strip()}</span>'
        if tag == "gap":
            return '<span class="gap"></span>'
        if tag == "term":
            return f'<span class="term"{anchor_attr}>{content.strip()}</span>'

        # Unknown TEI wrappers lose their tag and attributes, but keep all text.
        if anchor:
            return f'<span id="{html.escape(anchor, quote=True)}">{content.strip()}</span>'
        return content

    def milestone(self, elem: ET.Element) -> str:
        """Render a subsection marker as an empty anchor at its printed place.

        The source strips the printed "a." label and keeps only this marker, so
        the anchor has no text of its own.  Section, sub-subsection, and
        third-level markers carry no citable label and render as nothing.
        """
        if elem.get("unit") != "smythsub":
            return ""
        anchor = self.letter_markers.get(elem)
        if not anchor:
            return ""
        return f'<span class="subsection" id="{html.escape(anchor, quote=True)}"></span>'

    def paragraph(self, elem: ET.Element, anchor_attr: str) -> str:
        """Render a TEI p, lifting block children out to sibling level.

        The source puts lists, tables, and notes inside p.  Nesting them in the
        HTML p would be invalid, and a browser closes the p at the block and
        leaves an empty one behind, so the prose around a block becomes one p
        per run.
        """
        parts: list[tuple[bool, str]] = []  # (wrap in a p, html)
        buffer: list[str] = [self._text(elem.text)]

        def flush() -> None:
            text = "".join(buffer).strip()
            buffer.clear()
            if not text:
                return
            # A run of nothing but markers gets no paragraph box.
            has_words = bool(TAG_RE.sub("", text).strip())
            parts.append((has_words, text))

        for child in elem:
            if self.is_block(child):
                flush()
                parts.append((False, self.element(child)))
            else:
                buffer.append(self.element(child))
            buffer.append(self._text(child.tail))
        flush()

        if not parts:
            # An empty p is worth keeping only when it carries an anchor.
            return f"<p{anchor_attr}></p>" if anchor_attr else ""

        # The anchor marks where the subsection starts, so it stays first in
        # document order: on the opening p, or on its own marker when the
        # paragraph opens with something that is not a p.
        opens_with_p = parts[0][0]
        chunks = (
            [] if opens_with_p or not anchor_attr else [f"<span{anchor_attr}></span>"]
        )
        for index, (wrap, rendered) in enumerate(parts):
            attrs = anchor_attr if index == 0 and opens_with_p else ""
            chunks.append(f"<p{attrs}>{rendered}</p>" if wrap else rendered)
        return "".join(chunks)

    def table(self, elem: ET.Element, anchor_attr: str) -> str:
        """Render a TEI table, lifting non-row children out in front of it.

        The source puts notes and page markers inside table.  An HTML table
        takes only rows and row groups, so a browser foster-parents such a child
        out to just before the table: emitting it there makes the markup match
        the rendered tree.
        """
        before: list[str] = []
        rows: list[str] = []
        for child in elem:
            if child.tag == "row":
                rows.append(self.element(child))
                # Only whitespace ever separates rows; keep it between them.
                rows.append(self._text(child.tail))
            else:
                before.append(self.element(child))
        return f"{''.join(before)}<table{anchor_attr}>{''.join(rows).strip()}</table>"

    def listing(self, elem: ET.Element, anchor_attr: str) -> str:
        """Render a TEI list, lifting non-item children out in front of it."""
        before: list[str] = []
        items: list[str] = []
        for child in elem:
            if child.tag == "item":
                items.append(self.element(child))
                items.append(self._text(child.tail))
            else:
                before.append(self.element(child))
        name = "ol" if elem.get("type") == "ordered" else "ul"
        return (
            f"{''.join(before)}<{name}{anchor_attr}>"
            f"{''.join(items).strip()}</{name}>"
        )

    def blocks(self, elems: Iterable[ET.Element]) -> str:
        return "".join(self.element(elem) for elem in elems).strip()


def note_anchors_for(notes: list[ET.Element]) -> dict[ET.Element, tuple[str, str]]:
    """Assign unique in-section anchors to notes and footnotes.

    A printed "Note 2" anchors as ``#n2``.  The source restarts note numbering
    inside each lettered subsection, so a repeated label takes a ``-2``, ``-3``
    suffix in document order.  Footnotes have no printed label and number
    straight through the section as ``#fn1``, ``#fn2``.
    """
    anchors: dict[ET.Element, tuple[str, str]] = {}
    used: collections.Counter[str] = collections.Counter()
    footnote = 0
    for note in notes:
        if note.get("place") == "foot":
            footnote += 1
            anchors[note] = (f"fn{footnote}", "footnote")
            continue
        base = f"n{note.get('n') or ''}"
        used[base] += 1
        anchor = base if used[base] == 1 else f"{base}-{used[base]}"
        anchors[note] = (anchor, "note")
    return anchors


def build_toc(
    section_divs: dict[int, list[ET.Element]],
) -> list[dict[str, object]]:
    """Build Part -> Chapter -> Section TOC entries with numeric bounds."""
    parts: collections.OrderedDict[ET.Element, dict[str, object]] = (
        collections.OrderedDict()
    )
    for number, divs in sorted(section_divs.items()):
        part = next((d for d in divs if d.get("subtype") == "part"), None)
        chapter = next((d for d in divs if d.get("subtype") == "section"), None)
        if part is None or chapter is None:
            continue
        part_record = parts.setdefault(
            part,
            {"head": first_head(part) or "", "numbers": [], "chapters": collections.OrderedDict()},
        )
        part_record["numbers"].append(number)
        chapters: collections.OrderedDict = part_record["chapters"]
        chapter_record = chapters.setdefault(
            chapter,
            {
                "head": first_head(chapter) or "",
                "numbers": [],
                "sections": collections.OrderedDict(),
            },
        )
        chapter_record["numbers"].append(number)
        leaf = next((d for d in divs if d.get("subtype") == "subsection"), None)
        if leaf is not None:
            sections: collections.OrderedDict = chapter_record["sections"]
            section_record = sections.setdefault(
                leaf, {"head": first_head(leaf) or "", "numbers": []}
            )
            section_record["numbers"].append(number)

    toc: list[dict[str, object]] = []
    for part_record in parts.values():
        chapters_out: list[dict[str, object]] = []
        for chapter_record in part_record["chapters"].values():
            sections_out = [
                {
                    "head": item["head"],
                    "start": min(item["numbers"]),
                    "end": max(item["numbers"]),
                }
                for item in chapter_record["sections"].values()
            ]
            chapters_out.append(
                {
                    "head": chapter_record["head"],
                    "start": min(chapter_record["numbers"]),
                    "end": max(chapter_record["numbers"]),
                    "sections": sections_out,
                }
            )
        toc.append(
            {
                "head": part_record["head"],
                "start": min(part_record["numbers"]),
                "end": max(part_record["numbers"]),
                "chapters": chapters_out,
            }
        )
    return toc


def extract_examples(
    blocks: Iterable[ET.Element], parents: dict[ET.Element, ET.Element]
) -> list[dict[str, str]]:
    """Pull the Latin citations out of a section.

    A ``cit`` holds the Latin quotation and its source; the English rendering
    follows it as sibling ``gloss`` elements.  A translation is often split
    across several of them, with the words the print sets in small capitals
    left bare between the pieces, so the whole run counts as the gloss: it
    starts at the ``cit`` and ends with the last ``gloss`` before the next
    ``cit`` or ``bibl``.  A ``cit`` whose next sibling is not a ``gloss`` has
    no translation at all.
    """
    examples: list[dict[str, str]] = []
    for block in blocks:
        for citation in block.iter("cit"):
            quote = citation.find("quote")
            if quote is None:
                continue
            bibl = citation.find("bibl")
            cite = ""
            if bibl is not None:
                cite = bibl.get("n") or text_of(bibl)
            examples.append(
                {
                    "la": text_of(quote),
                    "gloss": trailing_gloss(citation, parents),
                    "cite": cite,
                }
            )
    return examples


def trailing_gloss(
    citation: ET.Element, parents: dict[ET.Element, ET.Element]
) -> str:
    parent = parents.get(citation)
    if parent is None:
        return ""
    siblings = list(parent)
    index = siblings.index(citation)
    if index + 1 >= len(siblings) or siblings[index + 1].tag != "gloss":
        return ""
    # The run ends where the print gives a second passage its own source, since
    # the translation after that source renders that passage and not this one.
    # Three shapes say so.  A sibling ``cit`` or ``bibl`` is one.  A sibling
    # holding one is another: Sec. 395 wraps "cf. traiecto fune (Aen. 5.488)"
    # in a ``note``, and the run walked straight through it.  The third is a
    # bracketed reference the source never tagged at all, which Sec. 382 sets
    # as running text after a bare ``foreign`` ("ero frugi bonae
    # (Plaut. Pseud. 468)") and Sec. 317 splits across three of them
    # (" (" + <foreign>id</foreign> + ". 11.20), "), so it is looked for in the
    # run as assembled rather than in any one tail.  "(March 28)" at Sec. 424
    # stands inside a real translation and is not a reference; see
    # UNTAGGED_REFERENCE_RE.
    running = citation.tail or ""
    end = 0
    for sibling in siblings[index + 1 :]:
        if sibling.tag in {"cit", "bibl"}:
            break
        if any(nested.tag in {"cit", "bibl"} for nested in sibling.iter()):
            break
        running += "".join(sibling.itertext())
        if sibling.tag == "gloss":
            if UNTAGGED_REFERENCE_RE.search(running):
                break
            end = len(running)
        running += sibling.tail or ""
    return norm(running[:end]).lstrip(",").strip()


def strip_namespace(root: ET.Element) -> None:
    for elem in root.iter():
        if isinstance(elem.tag, str) and elem.tag.startswith(TEI_NS):
            elem.tag = elem.tag[len(TEI_NS) :]


def convert(source: Path) -> tuple[list[dict[str, object]], dict[str, object]]:
    # The macrons that mark Latin vowel length are precomposed in this source
    # (a with macron is U+0101, not a + U+0304).  NFC at the door keeps them
    # that way and makes every downstream string comparable and searchable.
    # repair() undoes the source's transmission errors: a doubly marked
    # vowel typed with a loose breve (sū˘bus for sū̆bus, A&G §10), and signs
    # left under placeholder names ([acutemacr]).
    root = ET.fromstring(repair(source.read_text(encoding="utf-8")))
    strip_namespace(root)
    body = root.find("text/body")
    if body is None:
        raise ValueError("no TEI body in the source")
    parents = {child: parent for parent in body.iter() for child in parent}

    glossary_divs = {
        div
        for div in body.iter("div")
        if any(child.tag == "head" and text_of(child) == GLOSSARY_HEAD for child in div)
    }
    glossary_members: set[ET.Element] = set()
    for div in glossary_divs:
        glossary_members.update(div.iter())

    # 1. Walk the body once, assigning each block-level child of a div to the
    #    section marker in force.  A section keeps running past the end of the
    #    div that opened it until the next marker appears.
    order = list(body.iter())
    current: int | None = None
    blocks_by_section: dict[int, list[ET.Element]] = collections.defaultdict(list)
    marker_by_section: dict[int, ET.Element] = {}
    front_matter: list[ET.Element] = []
    back_matter: list[ET.Element] = []
    back_matter_numbers: list[int] = []
    milestone_units: collections.Counter[str] = collections.Counter()
    duplicate_markers: list[dict[str, object]] = []

    for elem in order:
        in_glossary = elem in glossary_members
        if elem.tag == "milestone":
            milestone_units[elem.get("unit") or ""] += 1
            if elem.get("unit") == "smythp":
                number = int(elem.get("n") or 0)
                if in_glossary:
                    back_matter_numbers.append(number)
                    continue
                if number in marker_by_section:
                    duplicate_markers.append({"n": number})
                else:
                    marker_by_section[number] = elem
                current = number
                continue
        parent = parents.get(elem)
        if parent is None or parent.tag != "div" or elem.tag not in CONTENT_TAGS:
            continue
        if in_glossary:
            back_matter.append(elem)
        elif current is None:
            front_matter.append(elem)
        else:
            blocks_by_section[current].append(elem)

    numbers = sorted(marker_by_section)

    # 2. Letters.  The source encodes a printed "a." as a smythsub marker whose
    #    label is stripped from the text; three sections instead leave the label
    #    in the paragraph, which the narrow rule below recovers.
    letters_by_section: dict[int, list[str]] = {}
    markers_by_section: dict[int, dict[ET.Element, str]] = {}
    implicit_letter_anchors: list[dict[str, object]] = []
    letter_sequence_gaps: list[dict[str, object]] = []
    unmarked_letter_labels: list[dict[str, object]] = []

    for number in numbers:
        blocks = blocks_by_section[number]
        markers: dict[ET.Element, str] = {}
        letters: list[str] = []
        for block in blocks:
            for elem in block.iter():
                if elem.tag == "milestone" and elem.get("unit") == "smythsub":
                    letter = (elem.get("n") or "").strip()
                    if letter and letter not in letters:
                        letters.append(letter)
                        markers[elem] = letter
        # A label the source left in the text: the paragraph opens with an emph
        # holding exactly "x.".  Accept it only when the letter appears once,
        # is not already a marker, and completes an unbroken a, b, c, ... run.
        candidates: list[tuple[str, ET.Element]] = []
        for block in blocks:
            if block.tag != "p" or (block.text or "").strip():
                continue
            children = list(block)
            if not children or children[0].tag != "emph":
                continue
            match = LABEL_RE.fullmatch(text_of(children[0]))
            if match:
                candidates.append((match.group(1), children[0]))
        counts = collections.Counter(letter for letter, _ in candidates)
        accepted = [
            (letter, elem)
            for letter, elem in candidates
            if counts[letter] == 1 and letter not in letters
        ]
        proposed = sorted(letters + [letter for letter, _ in accepted])
        if accepted and proposed == [chr(ord("a") + i) for i in range(len(proposed))]:
            for letter, elem in accepted:
                markers[elem] = letter
                implicit_letter_anchors.append({"section": number, "anchor": letter})
            letters = sorted(letters + [letter for letter, _ in accepted])
        letters_by_section[number] = letters
        markers_by_section[number] = markers
        if letters and letters != [chr(ord("a") + i) for i in range(len(letters))]:
            letter_sequence_gaps.append({"section": number, "letters": letters})
        # Printed labels still loose in the prose, reported but not anchored.
        loose = [
            match.group(1)
            for block in blocks
            for paragraph in block.iter("p")
            for match in [LOOSE_LABEL_RE.match(text_of(paragraph))]
            if match and match.group(1) not in letters
        ]
        if loose:
            unmarked_letter_labels.append(
                {"section": number, "labels": sorted(set(loose)), "count": len(loose)}
            )

    # 3. Cross-references.
    all_ranges, ranges_by_ref = find_ref_ranges(body)
    ref_letters: dict[ET.Element, str] = {}
    for parent in body.iter():
        children = list(parent)
        for index, child in enumerate(children):
            if child.tag != "ref":
                continue
            letter = ref_letter(child, children, index)
            if letter:
                ref_letters[child] = letter

    malformed_refs: list[dict[str, object]] = []
    unresolved_refs: list[dict[str, object]] = []
    missing_cites: list[dict[str, object]] = []
    ref_occurrences = 0
    records: list[dict[str, object]] = []

    for index, number in enumerate(numbers):
        blocks = blocks_by_section[number]
        notes = [elem for block in blocks for elem in block.iter("note")]
        note_anchors = note_anchors_for(notes)
        renderer = Renderer(
            parents, markers_by_section[number], note_anchors, ref_letters
        )

        note_records: list[dict[str, object]] = []
        for note in notes:
            anchor, kind = note_anchors[note]
            note_records.append(
                {
                    "anchor": anchor,
                    "label": note.get("n") or "",
                    "kind": kind,
                    "html": renderer.inner(note).strip(),
                    "plain": text_of(note),
                }
            )

        refs: list[str] = []
        ranges: list[dict[str, int]] = []
        for block in blocks:
            for ref in block.iter("ref"):
                ref_occurrences += 1
                target = parse_ref(ref)
                if target is None:
                    malformed_refs.append(
                        {"section": number, "text": text_of(ref), "attrs": dict(ref.attrib)}
                    )
                    continue
                target_id = f"ag:{target}"
                if target_id not in refs:
                    refs.append(target_id)
                for range_record in ranges_by_ref.get(ref, []):
                    if range_record not in ranges:
                        ranges.append(range_record)
            for bibl in block.iter("bibl"):
                if not bibl.get("n"):
                    missing_cites.append({"section": number, "text": text_of(bibl)})

        divs = ancestor_divs(marker_by_section[number], parents)
        path = [head for div in divs if (head := first_head(div))]
        head = path[-1] if path else f"Allen and Greenough section {number}"
        body_html = renderer.blocks(blocks)
        records.append(
            {
                "work": "ag",
                "n": number,
                "id": f"ag:{number}",
                "letters": letters_by_section[number],
                "notes": note_records,
                "path": path,
                "head": head,
                "html": f'<section id="s{number}">{body_html}</section>',
                "plain": norm(" ".join(text_of(block) for block in blocks)),
                "examples": extract_examples(blocks, parents),
                "refs": refs,
                "refRanges": ranges,
                "citedBy": [],
                "prev": f"ag:{numbers[index - 1]}" if index else None,
                "next": f"ag:{numbers[index + 1]}" if index + 1 < len(numbers) else None,
            }
        )

    record_by_id = {record["id"]: record for record in records}
    for source_record in records:
        for target_id in source_record["refs"]:
            target_record = record_by_id.get(target_id)
            if target_record is not None:
                target_record["citedBy"].append(source_record["id"])

    for record in records:
        for target_id in record["refs"]:
            if target_id not in record_by_id:
                unresolved_refs.append(
                    {"section": record["n"], "target": int(target_id.split(":")[1])}
                )

    section_divs = {
        number: ancestor_divs(marker_by_section[number], parents) for number in numbers
    }
    body_refs = [ref for ref in body.iter("ref")]
    body_bibls = [bibl for bibl in body.iter("bibl")]
    record_range_values = {
        (item["start"], item["end"])
        for record in records
        for item in record["refRanges"]
    }
    ranges_outside_sections = [
        item
        for item in all_ranges
        if (item["start"], item["end"]) not in record_range_values
    ]
    gaps = [
        number
        for number in range(1, LAST_PRINTED_SECTION + 1)
        if number not in marker_by_section
    ]

    # Anything carrying text that no section, the front matter, or the back
    # matter claims: the source hides two footnotes inside structural headings.
    claimed: set[ET.Element] = set()
    for group in (blocks_by_section.values(), [front_matter], [back_matter]):
        for chunk in group:
            for block in chunk:
                claimed.update(block.iter())
    unassigned = [
        {"tag": elem.tag, "text": text_of(elem)[:200]}
        for elem in body.iter()
        if elem.tag in {"note", "cit", "table", "list", "figure"}
        and elem not in claimed
    ]

    anomalies: dict[str, object] = {
        "numberingGaps": gaps,
        "duplicateSectionMarkers": duplicate_markers,
        "malformedRefs": malformed_refs,
        "unresolvedRefs": unresolved_refs,
        "biblWithoutN": missing_cites,
        "implicitLetterAnchors": implicit_letter_anchors,
        "letterSequenceGaps": letter_sequence_gaps,
        "unmarkedLetterLabels": unmarked_letter_labels,
        "rangesOutsideSections": ranges_outside_sections,
        "unassignedElements": unassigned,
        "examplesWithoutGloss": sum(
            1
            for record in records
            for example in record["examples"]
            if not example["gloss"]
        ),
        "examplesWithoutCite": sum(
            1
            for record in records
            for example in record["examples"]
            if not example["cite"]
        ),
        "frontMatter": [
            {"tag": elem.tag, "text": text_of(elem)} for elem in front_matter
        ],
        "backMatter": {
            "head": GLOSSARY_HEAD,
            "sourceSectionNumbers": sorted(back_matter_numbers),
            "blocks": len(back_matter),
            "crossRefs": sum(1 for elem in back_matter for _ in elem.iter("ref")),
            "characters": sum(len(text_of(elem)) for elem in back_matter),
            "note": "printed grammar ends at 638; the source numbers this glossary as sections",
        },
        "index": {
            "present": False,
            "note": "the TEI carries no index; the printed English/Latin index is not in this file",
        },
    }

    meta: dict[str, object] = {
        "work": "ag",
        "title": "Allen and Greenough's New Latin Grammar for Schools and Colleges",
        "source": "grammar-ag-tei/data/viaf39744457/001/viaf39744457.001.perseus-eng1.xml",
        "sourceRepository": "https://github.com/PerseusDL/canonical-pdlrefwk",
        "sourceCommit": "02768b0c37d6102be4899fc0eb57f9d348195243",
        "license": "CC BY-SA 4.0 (Perseus Digital Library)",
        "edition": "Ginn and Company, 1903",
        "toc": build_toc(section_divs),
        "counts": {
            "sections": len(records),
            "sectionMarkers": milestone_units["smythp"],
            "backMatterMarkers": len(back_matter_numbers),
            "letterMarkers": milestone_units["smythsub"],
            "subSubMarkers": milestone_units["old_Subsub"] + milestone_units["old_Sub3"],
            "sourceCrossRefs": len(body_refs),
            "sectionCrossRefs": ref_occurrences,
            "crossRefsOutsideSections": len(body_refs) - ref_occurrences,
            "uniqueRefEdges": sum(len(record["refs"]) for record in records),
            "letteredCrossRefs": len(ref_letters),
            "crossRefRanges": len(all_ranges),
            "quotes": sum(1 for _ in body.iter("quote")),
            "bibliographies": len(body_bibls),
            "examples": sum(len(record["examples"]) for record in records),
            "sectionsWithLetters": sum(bool(record["letters"]) for record in records),
            "letterAnchors": sum(len(record["letters"]) for record in records),
            "sectionsWithNotes": sum(bool(record["notes"]) for record in records),
            "notes": sum(
                1
                for record in records
                for note in record["notes"]
                if note["kind"] == "note"
            ),
            "footnotes": sum(
                1
                for record in records
                for note in record["notes"]
                if note["kind"] == "footnote"
            ),
            "tables": sum(1 for _ in body.iter("table")),
            "lists": sum(1 for _ in body.iter("list")),
            "figures": sum(1 for _ in body.iter("figure")),
            "pageBreaks": sum(1 for _ in body.iter("pb")),
        },
        "crossRefRanges": all_ranges,
        "anomalies": anomalies,
    }
    return records, meta


def write_outputs(
    records: list[dict[str, object]],
    meta: dict[str, object],
    sections_path: Path,
    meta_path: Path,
) -> None:
    sections_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    section_bytes = ("\n".join(json_line(record) for record in records) + "\n").encode(
        "utf-8"
    )
    meta_bytes = (
        json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    ).encode("utf-8")
    sections_path.write_bytes(section_bytes)
    meta_path.write_bytes(meta_bytes)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--sections", type=Path, default=DEFAULT_SECTIONS)
    parser.add_argument("--meta", type=Path, default=DEFAULT_META)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    records, meta = convert(args.input)
    write_outputs(records, meta, args.sections, args.meta)
    counts = meta["counts"]
    print(
        f"wrote {counts['sections']} sections, {counts['sectionCrossRefs']} section refs, "
        f"and {counts['examples']} examples"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
