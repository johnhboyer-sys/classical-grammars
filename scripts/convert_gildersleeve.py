#!/usr/bin/env python3
"""Convert the Perseus TEI P5 Gildersleeve grammar to deterministic JSON.

The source marks printed sections with ``milestone unit="smythp"`` elements.
Three printed numbers lost their milestones: 78 and 642 remain at the start of
their first paragraphs, while the scan read printed 111 as ``III``.  Section
88 has two markers.  The converter repairs those source defects explicitly,
then assigns each block to the section marker in force.  Both part prefaces
remain outside the 674 numbered records and are inventoried in the metadata.
The converter performs no network access.
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

import convert_smyth


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "grammar-gildersleeve" / "src" / "gildersleeve-1999.04.0074.xml"
DEFAULT_SECTIONS = ROOT / "data" / "gildersleeve" / "sections.jsonl"
DEFAULT_META = ROOT / "data" / "gildersleeve" / "meta.json"

TEI_NS = "{http://www.tei-c.org/ns/1.0}"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
LAST_SECTION = 674
CONTENT_TAGS = {"p", "table", "list", "note", "signed"}
KNOWN_CONTENT_TAGS = {
    "p", "table", "list", "note", "signed", "quote", "bibl", "cit",
    "emph", "hi", "l", "gloss", "foreign", "item", "cell", "ref",
    "title", "term", "row", "date",
}
TAG_RE = re.compile(r"<[^>]+>")
IMPLICIT_PREFIXES = {78: "78.", 111: "III.", 642: "642."}
SOURCE_TEXT_FIXES = (
    (re.compile(r"matro\\s\s+a\)mfo/teroi"), "ματρὸς ἀμφότεροι", "Beta Code"),
    (re.compile(r"&lt;([^&<>]+)&gt;"), r"⟨\1⟩", "editorial angle brackets"),
)
PART_LABELS = {1: "PART I", 2: "PART II"}
PLAIN_BOUNDARY_TAGS = {"note", "bibl"}
GREEK_RE = re.compile(r"[Ͱ-Ͽἀ-῿]")
# The parts of a bare example (see ``collect_examples``) are joined by
# punctuation alone; the text just before a quote marks it as a supplement.
EXAMPLE_JOIN_RE = re.compile(r"^[\s,;:.]*$")
SUPPLEMENT_RE = re.compile(r"(?:\bsc\.|\(|\[)\s*$")
DIGITS_AND_PAREN = frozenset("0123456789)")
# A reference the source left as untagged text inside a quotation ("... αἰσχύνη.
# 19.81: ἡ γὰρ ἀλήθεια ..."): book.line, or, just as often in this print, a
# bare section number closed by a colon ("... Πυθίων. 145: εὖ δ᾽ ἴστε ...").
QUOTE_REFERENCE_RE = re.compile(r"\b\d+\.\d+|\b\d+\s*:")
# A quotation ending in a lone Greek capital is an abbreviated name whose
# printed period the TEI leaves outside the quote ("εἰς Π." -> "εἰς Π").
TRUNCATED_TAIL_RE = re.compile(r"(?:^|\s)[Ͱ-Ͽἀ-῿]$")
CITE_LOCATOR_RE = re.compile(r"\d")


def norm(value: str | None) -> str:
    """Collapse source formatting whitespace without changing other text."""
    return re.sub(r"\s+", " ", value or "").strip()


def json_line(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def text_of(elem: ET.Element) -> str:
    return norm("".join(elem.itertext()))


def _needs_boundary(left: str, right: str) -> bool:
    """Return whether abutting retained text needs a separating space."""
    return bool(
        left
        and right
        and not left[-1].isspace()
        and not right[0].isspace()
        and right[0] not in ",.;:!?)]}\u00bb\u201d\u2019"
    )


def _plain_text(elem: ET.Element) -> str:
    """Serialize text while marking note and bibliography boundaries."""
    value = elem.text or ""
    for child in elem:
        child_text = _plain_text(child)
        if child.tag in PLAIN_BOUNDARY_TAGS and _needs_boundary(value, child_text):
            value += " "
        value += child_text
        tail = child.tail or ""
        if child.tag in PLAIN_BOUNDARY_TAGS and _needs_boundary(value, tail):
            value += " "
        value += tail
    return value


def plain_text_of(elem: ET.Element) -> str:
    return norm(_plain_text(elem))


def _text_excluding(elem: ET.Element, excluded: set[str]) -> str:
    """Serialize an element without excluded subtrees, retaining their tails."""
    value = elem.text or ""
    for child in elem:
        tail = child.tail or ""
        if child.tag not in excluded:
            value += _text_excluding(child, excluded)
        elif _needs_boundary(value, tail):
            value += " "
        value += tail
    return value


def text_excluding(elem: ET.Element, excluded: set[str]) -> str:
    return norm(_text_excluding(elem, excluded))


def clean_cite(value: str) -> str:
    """Drop the print's punctuation after a reference.

    A ``bibl`` without an ``n`` falls back to its printed text, which carries
    the colon that introduces the quotation ("fr. 2.1171:") or the period that
    closes the sentence ("Dem. 9.26."); neither belongs to the reference.  The
    period is dropped only after a digit or a closing parenthesis, so an
    abbreviation keeps its own dot ("Id. Eq.", "LYS. fr. 4 (Sch.)").
    """
    value = value.rstrip()
    while value.endswith(":") or (value.endswith(".") and value[-2:-1] in DIGITS_AND_PAREN):
        value = value[:-1].rstrip()
    return value


def citation_cite(citation: ET.Element) -> str:
    """Collect direct and quote-nested bibliography strings in source order."""
    values: list[str] = []
    for bibl in citation.iter("bibl"):
        value = clean_cite(norm(bibl.get("n") or text_of(bibl)))
        if value and value not in values:
            values.append(value)
    return "; ".join(values)


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
    found: list[ET.Element] = []
    current = parents.get(elem)
    while current is not None:
        if current.tag == "div":
            found.append(current)
        current = parents.get(current)
    found.reverse()
    return found


def part_of(elem: ET.Element, parents: dict[ET.Element, ET.Element]) -> int:
    current: ET.Element | None = elem
    while current is not None:
        if current.tag == "div" and current.get("type") == "part":
            value = current.get("n") or ""
            if value.isdigit():
                return int(value)
        current = parents.get(current)
    raise ValueError("content outside a numbered part")


def parse_ref(elem: ET.Element) -> int | None:
    match = re.fullmatch(r"s(\d+)", elem.get("target") or "")
    return int(match.group(1)) if match else None


def parse_ref_range(elem: ET.Element) -> dict[str, int] | None:
    match = re.search(r"(\d+)\s*[-–—]\s*(\d+)", text_of(elem))
    if not match:
        return None
    return {"start": int(match.group(1)), "end": int(match.group(2))}


def strip_implicit_prefix(value: str, number: int) -> str:
    prefix = IMPLICIT_PREFIXES.get(number)
    if prefix and value.startswith(prefix):
        return value[len(prefix) :].lstrip()
    return value


class Renderer:
    """Small, explicit TEI-to-HTML renderer with no source attributes leaked."""

    def __init__(
        self,
        parents: dict[ET.Element, ET.Element],
        note_anchors: dict[ET.Element, tuple[str, str]],
        prefix_strips: dict[ET.Element, str],
    ) -> None:
        self.parents = parents
        self.note_anchors = note_anchors
        self.prefix_strips = prefix_strips

    @staticmethod
    def _text(value: str | None) -> str:
        if not value:
            return ""
        return html.escape(re.sub(r"\s+", " ", value), quote=False)

    def opening_text(self, elem: ET.Element) -> str:
        value = elem.text or ""
        prefix = self.prefix_strips.get(elem)
        if prefix and value.lstrip().startswith(prefix):
            leading = value[: len(value) - len(value.lstrip())]
            value = leading + value.lstrip()[len(prefix) :].lstrip()
        return self._text(value)

    def inner(self, elem: ET.Element) -> str:
        chunks = [self.opening_text(elem)]
        for child in elem:
            chunks.append(self.element(child))
            chunks.append(self._text(child.tail))
        return "".join(chunks)

    def note_is_block(self, elem: ET.Element) -> bool:
        return (
            elem.tag == "note"
            and elem.get("place") == "unspecified"
            and self.parents.get(elem) is not None
            and self.parents[elem].tag == "p"
        )

    def is_block(self, elem: ET.Element) -> bool:
        return elem.tag in {"table", "list"} or self.note_is_block(elem)

    def element(self, elem: ET.Element) -> str:
        tag = elem.tag
        if tag == "p":
            return self.paragraph(elem)
        if tag == "table":
            return self.table(elem)
        if tag == "list":
            return self.listing(elem)

        content = self.inner(elem).strip()
        if tag == "quote":
            return f'<q lang="grc">{content}</q>'
        if tag == "foreign":
            language = language_of(elem)
            code = {"greek": "grc"}.get(language, language)
            attr = f' lang="{html.escape(code, quote=True)}"' if code else ""
            return f"<span{attr}>{content}</span>"
        if tag in {"emph", "title"}:
            css = ' class="title"' if tag == "title" else ""
            return f"<em{css}>{content}</em>"
        if tag == "hi":
            if (elem.get("rend") or "").lower() == "bold":
                return f"<strong>{content}</strong>"
            return f'<span class="hi">{content}</span>'
        if tag == "gloss":
            return f'<span class="gloss">{content}</span>'
        if tag == "term":
            return f'<span class="term">{content}</span>'
        if tag == "cit":
            return f'<span class="example">{content}</span>'
        if tag == "bibl":
            cite = html.escape(elem.get("n") or text_of(elem), quote=True)
            return f'<cite data-cite="{cite}">{content}</cite>'
        if tag == "ref":
            target = parse_ref(elem)
            if target is None:
                return content
            return f'<a data-ref="gildersleeve:{target}">{content}</a>'
        if tag == "note":
            anchor, kind = self.note_anchors[elem]
            if self.note_is_block(elem):
                return f'<aside class="{kind}" id="{anchor}">{content}</aside>'
            return f'<span class="{kind}" id="{anchor}">{content}</span>'
        if tag == "l":
            return f'<span class="line">{content}</span>'
        if tag == "item":
            return f"<li>{content}</li>"
        if tag == "row":
            return f"<tr>{content}</tr>"
        if tag == "cell":
            return f"<td>{content}</td>"
        if tag in {"signed", "date"}:
            return f'<span class="{tag}">{content}</span>'

        # Unknown wrappers lose their tag and attributes, but never their text.
        return content

    def paragraph(self, elem: ET.Element) -> str:
        parts: list[tuple[bool, str]] = []
        buffer: list[str] = [self.opening_text(elem)]

        def flush() -> None:
            value = "".join(buffer).strip()
            buffer.clear()
            if value:
                parts.append((bool(TAG_RE.sub("", value).strip()), value))

        for child in elem:
            if self.is_block(child):
                flush()
                parts.append((False, self.element(child)))
            else:
                buffer.append(self.element(child))
            buffer.append(self._text(child.tail))
        flush()
        return "".join(f"<p>{value}</p>" if wrap else value for wrap, value in parts)

    def table(self, elem: ET.Element) -> str:
        rows = "".join(self.element(child) for child in elem if child.tag == "row")
        return f"<table>{rows}</table>"

    def listing(self, elem: ET.Element) -> str:
        items = "".join(self.element(child) for child in elem if child.tag == "item")
        return f"<ul>{items}</ul>"

    def blocks(self, elems: Iterable[ET.Element]) -> str:
        return "".join(self.element(elem) for elem in elems).strip()


def note_anchors_for(notes: list[ET.Element]) -> dict[ET.Element, tuple[str, str]]:
    anchors: dict[ET.Element, tuple[str, str]] = {}
    notes_seen = 0
    footnotes_seen = 0
    for note in notes:
        if note.get("place") == "unspecified":
            footnotes_seen += 1
            anchors[note] = (f"fn{footnotes_seen}", "footnote")
        else:
            notes_seen += 1
            anchors[note] = (f"n{notes_seen}", "note")
    return anchors


def is_gloss(elem: ET.Element) -> bool:
    """A ``gloss``, or an ``emph`` holding no Greek (the print's italic gloss)."""
    if elem.tag == "gloss":
        return True
    return elem.tag == "emph" and not GREEK_RE.search("".join(elem.itertext()))


def trailing_gloss(siblings: list[ET.Element], index: int) -> str:
    """The English gloss following the example's last element, ``siblings[index]``."""
    last = siblings[index]
    if index + 1 >= len(siblings) or not is_gloss(siblings[index + 1]):
        return ""
    if not EXAMPLE_JOIN_RE.match(last.tail or ""):
        return ""
    pieces = [last.tail or ""]
    end = 0
    for sibling in siblings[index + 1 :]:
        if sibling.tag in {"cit", "bibl", "quote"}:
            break
        pieces.append("".join(sibling.itertext()))
        if is_gloss(sibling):
            end = len(pieces)
        pieces.append(sibling.tail or "")
    return norm("".join(pieces[:end])).lstrip(";,.").strip()


def quote_grc(quote: ET.Element) -> str:
    return text_excluding(quote, {"note", "bibl"})


def bare_pair_is_sound(grc: str, cite: str) -> bool:
    """Whether an un-wrapped quote/bibl pair may ship as an example.

    Three ways the source defeats the pairing, each of which would hand a
    quotation a reference that is wrong for part of it:

    * The quotation carries further references the TEI never tagged, so one
      element holds several parallels ("... αἰσχύνη. 19.81: ἡ γὰρ ἀλήθεια
      ...", §473).  Splitting those needs a citation parser over running text,
      which this converter does not have, so the pair is dropped whole rather
      than shipped mis-paired.
    * The quotation ends in a lone Greek capital, an abbreviated name whose
      printed period the markup left outside the quote ("εἰς Π.", §557).
    * Nothing in the citation looks like a locator.
    """
    words = grc.split()
    if not words or not cite:
        return False
    if len(words) > 1 and QUOTE_REFERENCE_RE.search(" ".join(words[1:])):
        return False
    if TRUNCATED_TAIL_RE.search(grc):
        return False
    return bool(CITE_LOCATOR_RE.search(cite))


def citation_follows_quote(join: str) -> bool:
    """Whether the print's punctuation puts the citation after the quotation.

    Gildersleeve separates a quotation from the citation that follows it with
    a comma ("τῆς Ἀραβίης χώρης, HDT.2.11."), or with nothing at all where the
    comma is inside the quoted words, or with the Greek question mark.  A full
    stop is the other thing: it closes an entry whose citation has already
    been given, so what comes after it starts afresh ("AR. Vesp. 535: ὃ μὴ
    γένοιτο. AR. Lys. 147 ..."), and a colon marks the quote before it as a
    lemma.
    """
    join = norm(join)
    return not join or join.endswith(",") or join.endswith(";")


def bibl_closes_previous(
    children: list[ET.Element], index: int, parent: ET.Element
) -> bool:
    """Whether the ``bibl`` at ``index`` is the citation of the quote before it.

    Gildersleeve prints his citations both ways round, and the difference is
    in the punctuation, not in the markup.  "BIBL: quote" closes the
    bibliography with a colon and the quotation follows it.  "quote, BIBL."
    sets the citation after the quotation it belongs to, joined by the
    quotation's own closing punctuation, and the next quotation then starts
    a fresh pair.  Reading such a ``bibl`` as the opening of the following
    quotation gives that quotation the citation of the one before it, and,
    in a run of them, moves every citation in the run one place along.

    Which way round a bare pair runs is read off the punctuation, by
    ``citation_follows_quote`` for the join and by the colon for the ``bibl``
    itself.  A quote joined to the ``bibl`` by a colon is not a quotation but
    a lemma heading a list of parallels ("Σινδική: Hdt.4.86 ἐκ τῆς Σινδικῆς",
    §548), and there the ``bibl`` does belong to what follows it.

    The join need not be punctuation alone.  Gildersleeve often puts his
    note between the quotation and its citation ("τὸ Αἰγάλεων (adjective)
    ὄρος, THUC.2.19.2.", §560), and the citation is still the quotation's
    own.  Such a pair is not published in either direction, since the
    quote-first branch takes only punctuation joins, but the ``bibl`` is
    not handed on to the next quotation either.
    """
    if index == 0:
        return False
    previous = children[index - 1]
    if previous.tag != "quote":
        return False
    if not citation_follows_quote(previous.tail or ""):
        return False
    return not text_of(children[index]).endswith(":")


def collect_examples(parent: ET.Element, examples: list[dict[str, str]]) -> None:
    """Append the examples under ``parent`` in document order.

    Only 2,124 of Gildersleeve's examples are wrapped in a ``cit``; about as
    many again stand as bare siblings in the print's own order, "BIBL: quote"
    (1,679), and a smaller class runs the other way, "quote, BIBL;" (about
    360), in his lists of parallels.  Both are taken when nothing but
    punctuation joins the parts.  Which convention a bare pair follows is
    decided by ``bibl_closes_previous`` and by the colon: a ``bibl`` ending
    in one opens the quotation after it, and a quotation joined to its
    ``bibl`` by a colon is a lemma rather than an example.  A quote-first
    pair is also skipped when the quote is a supplement ("(sc. οἶνον). Ibid.
    573").  Where the two conventions collide the pair is dropped whole: no
    citation is better than the neighbour's.
    """
    children = list(parent)
    index = 0
    while index < len(children):
        child = children[index]
        following = children[index + 1] if index + 1 < len(children) else None
        if child.tag == "cit":
            quote = child.find("quote")
            if quote is not None:
                examples.append(
                    {
                        "grc": quote_grc(quote),
                        "gloss": trailing_gloss(children, index),
                        "cite": citation_cite(child),
                    }
                )
            index += 1
            continue
        if (
            child.tag == "bibl"
            and following is not None
            and following.tag == "quote"
            and EXAMPLE_JOIN_RE.match(child.tail or "")
            and not bibl_closes_previous(children, index, parent)
        ):
            grc = quote_grc(following)
            cite = citation_cite(child)
            if bare_pair_is_sound(grc, cite):
                examples.append(
                    {"grc": grc, "gloss": trailing_gloss(children, index + 1), "cite": cite}
                )
            index += 2
            continue
        if (
            child.tag == "quote"
            and following is not None
            and following.tag == "bibl"
            and EXAMPLE_JOIN_RE.match(child.tail or "")
        ):
            before = (children[index - 1].tail if index > 0 else parent.text) or ""
            # A ``bibl`` closing in a colon opens the quotation after it, and
            # so does one the print has separated from this quote by a full
            # stop or a colon.  Nothing else about what follows can decide the
            # pairing: reading a following quote as proof that the ``bibl``
            # opens it is what moved 56 citations one place along.
            opens_next = text_of(following).endswith(":") or not citation_follows_quote(
                child.tail or ""
            )
            if not opens_next and not SUPPLEMENT_RE.search(before):
                grc = quote_grc(child)
                cite = citation_cite(following)
                if bare_pair_is_sound(grc, cite):
                    examples.append({"grc": grc, "gloss": "", "cite": cite})
                index += 2
                continue
        collect_examples(child, examples)
        index += 1


def extract_examples(blocks: Iterable[ET.Element]) -> list[dict[str, str]]:
    examples: list[dict[str, str]] = []
    for block in blocks:
        collect_examples(block, examples)
    return examples


def strip_namespace(root: ET.Element) -> None:
    for elem in root.iter():
        if isinstance(elem.tag, str) and elem.tag.startswith(TEI_NS):
            elem.tag = elem.tag[len(TEI_NS) :]


def convert(source: Path) -> tuple[list[dict[str, object]], dict[str, object]]:
    source_text = unicodedata.normalize("NFC", source.read_text(encoding="utf-8"))
    source_text_fix_counts: list[dict[str, object]] = []
    for pattern, replacement, label in SOURCE_TEXT_FIXES:
        source_text, count = pattern.subn(replacement, source_text)
        source_text_fix_counts.append(
            {"kind": label, "pattern": pattern.pattern, "replacement": replacement, "count": count}
        )
    root = ET.fromstring(source_text)
    strip_namespace(root)
    # The source stacks a combining macron OUTERMOST, over breathing and
    # accent, the same transmission defect Smyth's print corrects innermost.
    # Restacked here with the shared rule (see convert_smyth.restack_macrons)
    # before any block text is read.
    mark_repairs = convert_smyth.restack_macrons(root)
    body = root.find("text/body")
    if body is None:
        raise ValueError("no TEI body in the source")
    parents = {child: parent for parent in body.iter() for child in parent}

    blocks_by_section: dict[int, list[ET.Element]] = collections.defaultdict(list)
    marker_by_section: dict[int, ET.Element] = {}
    part_by_section: dict[int, int] = {}
    prefix_strips: dict[ET.Element, str] = {}
    prefaces: dict[str, list[ET.Element]] = collections.defaultdict(list)
    current: int | None = None
    current_preface: str | None = None
    source_numbers: list[int] = []
    duplicate_markers: list[int] = []
    implicit_sections: list[dict[str, object]] = []

    for elem in body.iter():
        if elem.tag == "milestone" and elem.get("unit") == "smythp":
            label = elem.get("n") or ""
            if label.startswith("pref"):
                current = None
                current_preface = label
                continue
            if not label.isdigit():
                raise ValueError(f"bad section marker {label!r}")
            number = int(label)
            source_numbers.append(number)
            if number in marker_by_section:
                duplicate_markers.append(number)
            marker_by_section[number] = elem
            part_by_section[number] = part_of(elem, parents)
            current = number
            current_preface = None
            continue

        parent = parents.get(elem)
        if parent is None or parent.tag != "div" or elem.tag not in CONTENT_TAGS:
            continue
        if current_preface is not None:
            prefaces[current_preface].append(elem)
            continue
        if current is None:
            continue

        plain = text_of(elem)
        inferred: int | None = None
        if current == 77 and plain.startswith("78."):
            inferred = 78
        elif current == 110 and plain.startswith("III. Even here the plural"):
            inferred = 111
        elif current == 641 and plain.startswith("642."):
            inferred = 642
        if inferred is not None:
            current = inferred
            marker_by_section[current] = elem
            part_by_section[current] = part_of(elem, parents)
            prefix = IMPLICIT_PREFIXES[current]
            prefix_strips[elem] = prefix
            implicit_sections.append(
                {"n": current, "sourcePrefix": prefix, "text": plain[:120]}
            )
        blocks_by_section[current].append(elem)

    numbers = sorted(marker_by_section)
    records: list[dict[str, object]] = []
    malformed_refs: list[dict[str, object]] = []
    ref_occurrences = 0
    source_citations = 0

    for index, number in enumerate(numbers):
        blocks = blocks_by_section[number]
        notes = [elem for block in blocks for elem in block.iter("note")]
        note_anchors = note_anchors_for(notes)
        renderer = Renderer(parents, note_anchors, prefix_strips)
        note_records = [
            {
                "anchor": note_anchors[note][0],
                "label": "",
                "kind": note_anchors[note][1],
                "html": renderer.inner(note).strip(),
                "plain": text_of(note),
            }
            for note in notes
        ]

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
                target_id = f"gildersleeve:{target}"
                if target_id not in refs:
                    refs.append(target_id)
                range_record = parse_ref_range(ref)
                if range_record and range_record not in ranges:
                    ranges.append(range_record)
            source_citations += sum(1 for _ in block.iter("cit"))

        part = part_by_section[number]
        divs = ancestor_divs(marker_by_section[number], parents)
        path = [PART_LABELS[part]] + [head for div in divs if (head := first_head(div))]
        head = path[-1] if len(path) > 1 else f"Gildersleeve section {number}"
        body_html = renderer.blocks(blocks)
        plain_parts = []
        for block in blocks:
            value = plain_text_of(block)
            if block in prefix_strips:
                value = strip_implicit_prefix(value, number)
            plain_parts.append(value)
        records.append(
            {
                "work": "gildersleeve",
                "n": number,
                "id": f"gildersleeve:{number}",
                "part": part,
                "letters": [],
                "notes": note_records,
                "path": path,
                "head": head,
                "html": f'<section id="s{number}">{body_html}</section>',
                "plain": norm(" ".join(plain_parts)),
                "examples": extract_examples(blocks),
                "refs": refs,
                "refRanges": ranges,
                "citedBy": [],
                "prev": f"gildersleeve:{numbers[index - 1]}" if index else None,
                "next": (
                    f"gildersleeve:{numbers[index + 1]}"
                    if index + 1 < len(numbers)
                    else None
                ),
            }
        )

    record_by_id = {record["id"]: record for record in records}
    unresolved_refs: list[dict[str, object]] = []
    for source_record in records:
        for target_id in source_record["refs"]:
            target = record_by_id.get(target_id)
            if target is None:
                unresolved_refs.append({"section": source_record["n"], "target": target_id})
            else:
                target["citedBy"].append(source_record["id"])

    section_members = {
        elem
        for blocks in blocks_by_section.values()
        for block in blocks
        for elem in block.iter()
    }
    unknown_wrappers = collections.Counter(
        elem.tag for elem in section_members if elem.tag not in KNOWN_CONTENT_TAGS
    )
    skipped_text = [
        {"tag": elem.tag, "text": text_of(elem)[:160]}
        for elem in section_members
        if elem.tag not in KNOWN_CONTENT_TAGS and text_of(elem)
    ]
    # Unknown wrappers are rendered as their full inner content, so none of
    # the entries above represents skipped text.  Keep the audit separate.
    stripped_wrappers = dict(sorted(unknown_wrappers.items()))
    skipped_text = []
    claimed = section_members | {
        elem for blocks in prefaces.values() for block in blocks for elem in block.iter()
    }
    unassigned = [
        {"tag": elem.tag, "text": text_of(elem)[:200]}
        for elem in body.iter()
        if elem.tag in {"note", "cit", "table", "list"} and elem not in claimed
    ]

    meta: dict[str, object] = {
        "work": "gildersleeve",
        "title": "Syntax of Classical Greek from Homer to Demosthenes",
        "source": "grammar-gildersleeve/src/gildersleeve-1999.04.0074.xml",
        "edition": "Part I, 1900; Part II, 1911",
        "counts": {
            "sections": len(records),
            "sourceNumericMarkers": len(source_numbers),
            "sourceUniqueNumericMarkers": len(set(source_numbers)),
            "prefaceMarkers": len(prefaces),
            "sectionCrossRefs": ref_occurrences,
            "uniqueRefEdges": sum(len(record["refs"]) for record in records),
            "crossRefRanges": sum(len(record["refRanges"]) for record in records),
            "examples": sum(len(record["examples"]) for record in records),
            "sourceCitations": source_citations,
            "notes": sum(
                1 for record in records for note in record["notes"] if note["kind"] == "note"
            ),
            "footnotes": sum(
                1
                for record in records
                for note in record["notes"]
                if note["kind"] == "footnote"
            ),
            "tables": sum(1 for elem in section_members if elem.tag == "table"),
            "lists": sum(1 for elem in section_members if elem.tag == "list"),
            "skippedTextElements": len(skipped_text),
        },
        "anomalies": {
            "missingSourceMarkers": [78, 111, 642],
            "duplicateSourceMarkers": duplicate_markers,
            "implicitSections": implicit_sections,
            "sourceTextFixes": source_text_fix_counts,
            "sourceMarkRepairs": mark_repairs,
            "malformedRefs": malformed_refs,
            "unresolvedRefs": unresolved_refs,
            "strippedWrappers": stripped_wrappers,
            "skippedTextElements": skipped_text,
            "unassignedElements": unassigned,
            "prefaces": [
                {
                    "marker": marker,
                    "part": int(marker[-1]),
                    "blocks": len(blocks),
                    "characters": len(norm(" ".join(text_of(block) for block in blocks))),
                    "text": norm(" ".join(text_of(block) for block in blocks)),
                }
                for marker, blocks in sorted(prefaces.items())
            ],
        },
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
    sections_path.write_bytes(
        ("\n".join(json_line(record) for record in records) + "\n").encode("utf-8")
    )
    meta_path.write_bytes(
        (json.dumps(meta, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    )


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
        f"{counts['examples']} examples, and {counts['notes'] + counts['footnotes']} notes"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
