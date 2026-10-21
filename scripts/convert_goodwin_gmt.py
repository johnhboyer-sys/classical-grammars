#!/usr/bin/env python3
"""Convert the Perseus TEI P4 Goodwin grammar into section JSONL.

Goodwin's printed sections are empty ``milestone unit="smythp"`` elements.
The active marker owns each following direct block of a div until the next
marker, even when the source div contains many printed sections.
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
from html.parser import HTMLParser
from pathlib import Path

from betacode import MARKS, transliterate


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "grammar-goodwin-gmt" / "src" / "goodwin-gmt-dltext.xml"
DEFAULT_OUTPUT = ROOT / "data" / "goodwin-gmt" / "sections.jsonl"
DEFAULT_META = ROOT / "data" / "goodwin-gmt" / "meta.json"
SECTION_COUNT = 926
DIV_TAGS = {"div1", "div2", "div3"}
BLOCK_TAGS = {"p", "table", "list", "l"}
GREEK_TAGS = {"foreign", "quote", "note", "gloss"}
GREEK_LANGS = {"greek", "grc"}
TAG_RE = re.compile(r"<[^>]+>")
EDITORIAL_GREEK_RE = re.compile(r"\(subjunctive\)")
RAW_LATIN_RE = re.compile(r"[A-Z]+(?:\.[A-Z]+)*\.?")
STAR_CAPITAL_RE = re.compile(r"(\*(?:[)(/\\=|+_^])*)([A-Z])")
EDITORIAL_BRACKETS_RE = re.compile(r"<([^<>]+)>")
# An un-wrapped example (see ``bare_example``) is Greek, gloss and citation as
# sibling elements.  Between the Greek and what follows only punctuation, an
# "i.e."/"e.g." lead-in, or Goodwin's "(?)" doubt mark may stand; after the
# gloss also a closing parenthesis and "etc.".
EXAMPLE_JOIN_RE = re.compile(r"^[\s,;:.]*(?:i\.e\.|e\.g\.|\(\?\))?[\s,;:.]*$")
# Two Greek runs are the same quotation only when the print runs them
# together.  A colon between them does not: it introduces the second, and the
# first is a word of Goodwin's own sentence ("Without ὡς: τὸ σύμπαν εἰπεῖν",
# §777, whose merged reading contained the very word the print says the
# example lacks; also §287, §725 and §781).
FOREIGN_MERGE_RE = re.compile(r"^[\s,;.]*(?:i\.e\.|e\.g\.|\(\?\))?[\s,;.]*$")
GLOSS_TAIL_RE = re.compile(r"^[\s,;:.()]*(?:etc\.)?[\s,;:.()]*$")
GLOSS_TAGS = {"quote", "emph", "gloss"}
# A full stop inside a Greek run, after a Greek word of four letters or more
# and before more Greek, ends a sentence.  The TEI sometimes puts two of Goodwin's examples in one
# ``foreign``, the first one's reference left as untagged prose before it
# ("So i. 18, οὐδαμοὶ ὅ τι μὴ Χῖοι μοῦνοι. Οὐ γὰρ ἦν κρήνη ...", §550), or
# the first not a quotation at all but Goodwin's own constructed phrase
# (§745, §749).  The shorter words are excluded because the stop after them
# is an abbreviation's: κ.τ.λ., a speaker's ΠΡ., or the residue of a Beta
# Code reading the source itself has mangled.
FUSED_GREEK_RE = re.compile(r"[Ͱ-Ͽἀ-῿]{4}\.\s+[Ͱ-Ͽἀ-῿]")


def norm(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def text_of(elem: ET.Element) -> str:
    return norm("".join(elem.itertext()))


def json_line(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def language(elem: ET.Element) -> str:
    return (elem.get("lang") or "").lower()


def is_greek(elem: ET.Element) -> bool:
    return elem.tag in GREEK_TAGS and language(elem) in GREEK_LANGS


def beta_inventory(body: ET.Element) -> collections.Counter[str]:
    """Count Beta marks in declared Greek content, not XML markup."""
    marks = set("*()\\/=|+_^'")
    found: collections.Counter[str] = collections.Counter()
    for elem in body.iter():
        if is_greek(elem):
            found.update(char for char in "".join(elem.itertext()) if char in marks)
    return found


class PlainText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def value(self) -> str:
        return norm(" ".join(self.parts))


def plain_html(value: str) -> str:
    parser = PlainText()
    parser.feed(value)
    parser.close()
    return parser.value()


def section_target(elem: ET.Element) -> int | None:
    match = re.fullmatch(r"s(\d+)", elem.get("target", ""))
    return int(match.group(1)) if match else None


class Renderer:
    """Explicit P4 renderer.  Its fallback keeps text for uncommon tags."""

    def __init__(self) -> None:
        self.editorial_bracket_fixes = 0

    def greek_text(self, value: str) -> str:
        """Transliterate Greek, preserving editorial supplements as brackets."""
        value, fixes = EDITORIAL_BRACKETS_RE.subn(r"⟨\1⟩", value)
        self.editorial_bracket_fixes += fixes
        return transliterate(value)

    def text(self, value: str | None, greek: bool = False) -> str:
        if not value:
            return ""
        value = re.sub(r"\s+", " ", value)
        if greek:
            # A few Greek-tagged quotations include Latin speaker labels and
            # one English editorial note.  Keep them as explicit non-Greek
            # spans instead of treating bare ASCII capitals as Beta Code.
            value = STAR_CAPITAL_RE.sub(lambda match: match.group(1) + match.group(2).lower(), value)
            split = re.compile(r"\(subjunctive\)|[A-Z]+(?:\.[A-Z]+)*\.?")
            parts: list[str] = []
            cursor = 0
            for match in split.finditer(value):
                parts.append(html.escape(self.greek_text(value[cursor:match.start()]), quote=False))
                if match.group() == "(subjunctive)":
                    parts.append('<span lang="en">（subjunctive）</span>')
                else:
                    parts.append(f'<span lang="en">{html.escape(match.group(), quote=False)}</span>')
                cursor = match.end()
            parts.append(html.escape(self.greek_text(value[cursor:]), quote=False))
            return "".join(parts)
        return html.escape(value, quote=False)

    def inner(self, elem: ET.Element, greek: bool = False) -> str:
        chunks = [self.text(elem.text, greek)]
        for child in elem:
            chunks.append(self.element(child, greek))
            chunks.append(self.text(child.tail, greek))
        return "".join(chunks)

    def element(self, elem: ET.Element, inherited_greek: bool = False) -> str:
        tag = elem.tag
        greek = inherited_greek or is_greek(elem)
        content = self.inner(elem, greek).strip()

        if tag == "p":
            return f"<p>{content}</p>"
        if tag == "table":
            return f"<table>{content}</table>"
        if tag == "row":
            return f"<tr>{content}</tr>"
        if tag == "cell":
            attrs = ""
            for name, html_name in (("cols", "colspan"), ("rows", "rowspan")):
                value = elem.get(name)
                if value and value.isdigit() and value != "1":
                    attrs += f' {html_name}="{value}"'
            return f"<td{attrs}>{content}</td>"
        if tag == "list":
            ordered = any((child.get("n") or "").isdigit() for child in elem if child.tag == "item")
            name = "ol" if ordered else "ul"
            return f"<{name}>{content}</{name}>"
        if tag == "item":
            value = elem.get("n")
            attr = f' value="{html.escape(value, quote=True)}"' if value and value.isdigit() else ""
            return f"<li{attr}>{content}</li>"
        if tag == "l":
            return f'<div class="line">{content}</div>'
        if tag in {"foreign", "gloss"}:
            if greek:
                return f'<span lang="grc">{content}</span>'
            lang = language(elem)
            attr = f' lang="{html.escape(lang, quote=True)}"' if lang else ""
            css = "gloss" if tag == "gloss" else "foreign"
            return f'<span class="{css}"{attr}>{content}</span>'
        if tag == "quote":
            attr = ' lang="grc"' if greek else ""
            return f"<q{attr}>{content}</q>"
        if tag == "emph":
            name = "strong" if elem.get("rend") == "bold" else "em"
            return f"<{name}>{content}</{name}>"
        if tag == "bibl":
            cite = elem.get("n") or text_of(elem)
            return f'<cite data-cite="{html.escape(norm(cite), quote=True)}">{content}</cite>'
        if tag == "ref":
            target = section_target(elem)
            if target is None:
                return content
            return f'<a data-ref="goodwin-gmt:{target}">{content}</a>'
        if tag == "cit":
            return f'<span class="example">{content}</span>'
        if tag == "note":
            # Notes occur inside paragraphs and quotations, so a span is valid
            # in every source location and retains all of their text.
            kind = "note"
            return f'<span class="{kind}">{content}</span>'
        if tag == "label":
            return f'<span class="label">{content}</span>'
        if tag == "gap":
            reason = elem.get("reason") or "gap"
            return f'<span class="gap" data-reason="{html.escape(reason, quote=True)}">{content}</span>'
        # The P4 source has a few inline structural tags not needing a special
        # HTML shape.  Keeping their rendered children prevents silent loss.
        return content


def ancestors(elem: ET.Element, parents: dict[ET.Element, ET.Element]) -> list[ET.Element]:
    found: list[ET.Element] = []
    current = parents.get(elem)
    while current is not None:
        if current.tag in DIV_TAGS:
            found.append(current)
        current = parents.get(current)
    return list(reversed(found))


def direct_head(elem: ET.Element) -> ET.Element | None:
    return next((child for child in elem if child.tag == "head"), None)


def greek_of(elem: ET.Element) -> str:
    """Get highest declared Greek fragments from one citation."""
    fragments: list[str] = []

    def visit(node: ET.Element, inside: bool = False) -> None:
        current = is_greek(node)
        if current and not inside:
            raw = STAR_CAPITAL_RE.sub(lambda match: match.group(1) + match.group(2).lower(), norm("".join(node.itertext())))
            raw = RAW_LATIN_RE.sub("", EDITORIAL_GREEK_RE.sub("", raw))
            raw = EDITORIAL_BRACKETS_RE.sub(r"⟨\1⟩", raw)
            fragments.append(transliterate(raw))
            return
        for index, child in enumerate(node):
            if not current and is_gloss(child):
                # The quotation stops where the print starts translating it.
                # Greek set inside or after the English translation is
                # Goodwin's own explanation, not a further part of the
                # quotation.  Reading it as quotation glued the direct form
                # onto the end of the indirect one at §116 ("Περικλῆς
                # προηγόρευε, ὅτι Ἀρχίδαμός οἱ ξένος εἴη" + "ξένος μοί
                # ἐστιν") and Goodwin's cross-reference onto the quotation at
                # §92 ("cf. the following δείξεις δὲ μᾶλλον").  The gloss
                # keeps it, where the print puts it.
                break
            if not current and fragments:
                # Words between two Greek runs mean the second run is the
                # print's own prose, not a continuation of the first: §124
                # sets "(i.e. ἔνθα ἂν . . . ἀφικώμεθα, θύσομεν)" and §121
                # "(we said ἕκαστον ἓν δεῖ ἐπιτηδεύειν ...)" after the
                # translation, and both were being read as more of the
                # quotation.  This is the join ``bare_example`` already
                # requires between siblings.
                tail = node[index - 1].tail if index else node.text
                if not EXAMPLE_JOIN_RE.match(tail or ""):
                    break
            visit(child, inside or current)

    visit(elem)
    return norm(" ".join(fragments))


def gloss_text(elem: ET.Element) -> str:
    """Plain text of an English gloss, transliterating any Greek it embeds."""
    parts: list[str] = [elem.text or ""]
    for child in elem:
        parts.append(greek_of(child) if is_greek(child) else gloss_text(child))
        parts.append(child.tail or "")
    return norm("".join(parts))


def cite_of(bibl: ET.Element | None) -> str:
    if bibl is None:
        return ""
    return norm(bibl.get("n") or text_of(bibl))


def is_gloss(elem: ET.Element) -> bool:
    return elem.tag in GLOSS_TAGS and not is_greek(elem) and language(elem) not in GREEK_LANGS


def bare_example(children: list[ET.Element], start: int) -> tuple[dict[str, str] | None, int]:
    """Read an un-wrapped example starting at a Greek ``foreign`` sibling.

    Fewer than half of Goodwin's examples sit in a ``cit``.  The rest are a
    ``foreign lang="greek"`` (sometimes two, split by "(?)"), an optional
    gloss in a bare ``quote``, ``emph`` or ``gloss``, and a ``bibl``, as
    direct siblings joined by nothing but punctuation.  Words between the
    parts mean running prose ("a)/goito in Il. iv. 19"), not an example, and
    so does a colon (``FOREIGN_MERGE_RE``).  A run that turns out to hold two
    sentences (``FUSED_GREEK_RE``) is two examples with two citations, only
    one of which the markup gives, and is dropped whole.
    Returns the example and the index after the ``bibl``, or ``(None, start)``.
    """
    end = start
    while (
        end + 1 < len(children)
        and children[end + 1].tag == "foreign"
        and is_greek(children[end + 1])
        and FOREIGN_MERGE_RE.match(children[end].tail or "")
    ):
        end += 1
    if not EXAMPLE_JOIN_RE.match(children[end].tail or ""):
        return None, start
    index = end + 1
    glosses: list[str] = []
    while index < len(children) and is_gloss(children[index]) and GLOSS_TAIL_RE.match(children[index].tail or ""):
        glosses.append(gloss_text(children[index]))
        index += 1
    if index >= len(children) or children[index].tag != "bibl":
        return None, start
    grc = norm(" ".join(greek_of(children[item]) for item in range(start, end + 1)))
    if not grc:
        return None, start
    if FUSED_GREEK_RE.search(grc):
        # Two examples in one run, and the markup gives one citation.  Drop
        # the run, and with it any sibling that only continues its sentence:
        # resume at the first element the print starts a new sentence with.
        resume = next(
            (
                item
                for item in range(start + 1, end + 1)
                if greek_of(children[item - 1]).endswith(".")
            ),
            end + 1,
        )
        return None, resume
    gloss = norm(" ".join(value for value in glosses if value))
    return {"grc": grc, "gloss": gloss, "cite": cite_of(children[index])}, index + 1


def cit_example(citation: ET.Element, children: list[ET.Element], index: int) -> dict[str, str] | None:
    grc = greek_of(citation)
    if not grc:
        return None
    bibl = next((item for item in citation.iter("bibl")), None)
    gloss_quote = next((item for item in citation.iter("quote") if not is_greek(item)), None)
    gloss = gloss_text(gloss_quote) if gloss_quote is not None else ""
    if not gloss and EXAMPLE_JOIN_RE.match(citation.tail or ""):
        # The gloss of a ``cit`` sometimes follows it as a sibling ("<cit/>,
        # <gloss>...</gloss>"), on the same terms as an un-wrapped example.
        following = children[index + 1] if index + 1 < len(children) else None
        if following is not None and is_gloss(following) and GLOSS_TAIL_RE.match(following.tail or ""):
            gloss = gloss_text(following)
    return {"grc": grc, "gloss": gloss, "cite": cite_of(bibl)}


def collect_examples(parent: ET.Element, examples: list[dict[str, str]]) -> None:
    """Append the examples under ``parent`` in document order."""
    children = list(parent)
    index = 0
    while index < len(children):
        child = children[index]
        if child.tag == "cit":
            example = cit_example(child, children, index)
            if example is not None:
                examples.append(example)
            index += 1
            continue
        if child.tag == "foreign" and is_greek(child):
            example, after = bare_example(children, index)
            if example is not None:
                examples.append(example)
                index = after
                continue
            if after > index:
                # A dropped run, and the siblings that only continue it.
                index = after
                continue
        collect_examples(child, examples)
        index += 1


def examples_of(blocks: list[ET.Element]) -> list[dict[str, str]]:
    examples: list[dict[str, str]] = []
    for block in blocks:
        collect_examples(block, examples)
    return examples


def is_descendant(
    elem: ET.Element, ancestor: ET.Element, parents: dict[ET.Element, ET.Element]
) -> bool:
    current: ET.Element | None = elem
    while current is not None:
        if current is ancestor:
            return True
        current = parents.get(current)
    return False


def appendix_divisions(appendix: ET.Element) -> list[ET.Element]:
    """Return nonempty appendix div2/div3 divisions in printed order."""
    return [
        elem
        for elem in appendix.iter()
        if elem.tag in {"div2", "div3"} and any(child.tag in BLOCK_TAGS for child in elem)
    ]


def refs_of(blocks: list[ET.Element]) -> list[str]:
    refs: list[str] = []
    for block in blocks:
        for ref in block.iter("ref"):
            target = section_target(ref)
            value = f"goodwin-gmt:{target}" if target is not None else None
            if value and value not in refs:
                refs.append(value)
    return refs


def build_meta(
    records: list[dict[str, object]],
    owned: list[ET.Element],
    skipped: int,
    editorial_bracket_fixes: int,
) -> dict[str, object]:
    """Describe the conversion: work identity, source terms, and counts."""
    ref_uses = sum(
        1 for block in owned for ref in block.iter("ref") if section_target(ref) is not None
    )
    return {
        "work": "goodwin-gmt",
        "title": "Syntax of the Moods and Tenses of the Greek Verb",
        "author": "William Watson Goodwin",
        "source": "grammar-goodwin-gmt/src/goodwin-gmt-dltext.xml",
        "license": (
            'Perseus Digital Library, availability status "free": the text may be '
            "freely distributed provided you credit Perseus, leave the availability "
            "statement intact, use it for non-commercial purposes only, and offer "
            "Perseus any modifications you make"
        ),
        "attribution": (
            "Text provided by Perseus Digital Library, with funding from The "
            "National Endowment for the Humanities. Original version available "
            "for viewing and download at http://www.perseus.tufts.edu/hopper/."
        ),
        "edition": "Macmillan, 1889; reprint: St. Martin's Press, 1965",
        "counts": {
            "sections": SECTION_COUNT,
            "appendixRecords": len(records) - SECTION_COUNT,
            "sectionCrossRefs": ref_uses,
            "uniqueRefEdges": sum(len(record["refs"]) for record in records),  # type: ignore[arg-type]
            "examples": sum(len(record["examples"]) for record in records),  # type: ignore[arg-type]
            "tables": sum(1 for block in owned for _ in block.iter("table")),
            "lists": sum(1 for block in owned for _ in block.iter("list")),
        },
        "anomalies": {
            "preMarkerBodyBlocks": skipped,
            "editorialBracketSupplements": editorial_bracket_fixes,
        },
    }


def convert(
    source: Path, output: Path, meta_output: Path
) -> tuple[list[dict[str, object]], collections.Counter[str], int, int]:
    root = ET.parse(source).getroot()
    body = root.find("text/body")
    if body is None:
        raise ValueError("source has no text/body")
    parents = {child: parent for parent in body.iter() for child in parent}
    renderer = Renderer()
    inventory = beta_inventory(body)
    appendix = next(
        (elem for elem in body if elem.tag == "div1" and elem.get("n") == "appendix"),
        None,
    )
    if appendix is None:
        raise ValueError("source has no appendix div1")
    appendix_parts = appendix_divisions(appendix)
    if not appendix_parts:
        raise ValueError("source appendix has no nonempty divisions")
    blocks: dict[int, list[ET.Element]] = collections.defaultdict(list)
    markers: dict[int, ET.Element] = {}
    current: int | None = None
    skipped = 0

    for elem in body.iter():
        if elem.tag == "milestone" and elem.get("unit") == "smythp":
            raw = elem.get("n", "")
            if not raw.isdigit():
                raise ValueError(f"non-numeric Goodwin milestone: {raw!r}")
            current = int(raw)
            if current in markers:
                raise ValueError(f"duplicate milestone {current}")
            markers[current] = elem
            continue
        parent = parents.get(elem)
        if parent is not None and parent.tag in DIV_TAGS and elem.tag in BLOCK_TAGS:
            if is_descendant(elem, appendix, parents):
                continue
            if current is None:
                skipped += 1
            else:
                blocks[current].append(elem)

    if sorted(markers) != list(range(1, SECTION_COUNT + 1)):
        raise ValueError("source milestones are not exactly 1 through 926")

    records: list[dict[str, object]] = []
    for number in range(1, SECTION_COUNT + 1):
        owned = blocks[number]
        divs = ancestors(markers[number], parents)
        path: list[str] = []
        for div in divs:
            head = direct_head(div)
            if head is not None:
                rendered = renderer.inner(head).strip()
                value = plain_html(rendered)
                if value:
                    path.append(value)
        head = path[-1] if path else ""
        rendered_blocks = "".join(renderer.element(block) for block in owned)
        section_html = f'<section id="s{number}">{rendered_blocks}</section>'
        records.append(
            {
                "work": "goodwin-gmt",
                "n": number,
                "id": f"goodwin-gmt:{number}",
                "letters": [],
                "notes": [],
                "path": path,
                "head": head,
                "html": section_html,
                "plain": plain_html(section_html),
                "examples": examples_of(owned),
                "refs": refs_of(owned),
                "refRanges": [],
                "citedBy": [],
                "prev": f"goodwin-gmt:{number - 1}" if number > 1 else None,
                "next": f"goodwin-gmt:{number + 1}" if number < SECTION_COUNT else "goodwin-gmt:app-1",
            }
        )

    for index, division in enumerate(appendix_parts, 1):
        # ``plain_html`` puts one normalized separator between adjacent source
        # blocks.  Preserve that separator at each newly exposed record cut so
        # the sum of ``plain`` lengths still equals the former whole-book run.
        records[-1]["plain"] = str(records[-1]["plain"]) + " "
        owned = [child for child in division if child.tag in BLOCK_TAGS]
        path: list[str] = []
        for div in ancestors(division, parents) + [division]:
            head = direct_head(div)
            if head is not None:
                value = plain_html(renderer.inner(head).strip())
                if value:
                    path.append(value)
        head = path[-1] if path else ""
        html_value = f'<section id="app-{index}">' + "".join(
            renderer.element(block) for block in owned
        ) + "</section>"
        records.append(
            {
                "work": "goodwin-gmt",
                "id": f"goodwin-gmt:app-{index}",
                "letters": [],
                "notes": [],
                "path": path,
                "head": head,
                "html": html_value,
                "plain": plain_html(html_value),
                "examples": examples_of(owned),
                "refs": refs_of(owned),
                "refRanges": [],
                "citedBy": [],
                "prev": f"goodwin-gmt:{SECTION_COUNT}" if index == 1 else f"goodwin-gmt:app-{index - 1}",
                "next": f"goodwin-gmt:app-{index + 1}" if index < len(appendix_parts) else None,
            }
        )

    reverse: dict[str, list[str]] = collections.defaultdict(list)
    for record in records:
        for ref in record["refs"]:  # type: ignore[index]
            reverse[ref].append(record["id"])  # type: ignore[arg-type]
    for record in records:
        record["citedBy"] = reverse[record["id"]]  # type: ignore[index]

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(json_line(record) for record in records) + "\n", encoding="utf-8")
    owned_all = [block for number in range(1, SECTION_COUNT + 1) for block in blocks[number]]
    owned_all += [
        child for division in appendix_parts for child in division if child.tag in BLOCK_TAGS
    ]
    meta = build_meta(records, owned_all, skipped, renderer.editorial_bracket_fixes)
    meta_output.parent.mkdir(parents=True, exist_ok=True)
    meta_output.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return records, inventory, skipped, renderer.editorial_bracket_fixes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--meta", type=Path, default=DEFAULT_META)
    args = parser.parse_args()
    try:
        records, inventory, skipped, editorial_bracket_fixes = convert(args.input, args.output, args.meta)
    except (ET.ParseError, ValueError) as error:
        print(f"conversion failed: {error}", file=sys.stderr)
        return 1
    marks = " ".join(f"{mark}:{inventory[mark]}" for mark in "*()\\/=|+_^'" if inventory[mark])
    print(f"wrote {SECTION_COUNT} sections and {len(records) - SECTION_COUNT} appendix records to {args.output}")
    print(f"wrote conversion metadata to {args.meta}")
    print(f"Beta Code marks in declared Greek content: {marks}")
    print(f"direct body blocks before first section skipped: {skipped}")
    print(f"editorial angle-bracket supplements converted: {editorial_bracket_fixes}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
