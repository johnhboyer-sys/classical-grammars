#!/usr/bin/env python3
"""Convert DCC's mirrored Goodell HTML pages to canonical section JSONL.

The DCC article body is authoritative.  Each numbered section begins with a
``strong`` number at the start of a content block; all surrounding Drupal
chrome is deliberately ignored.
"""

from __future__ import annotations

import argparse
import collections
import html
import json
import re
import unicodedata
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterator
from urllib.parse import unquote, urlparse

import convert_smyth


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "grammar-goodell" / "src" / "dcc"
DEFAULT_SECTIONS = ROOT / "data" / "goodell" / "sections.jsonl"
DEFAULT_META = ROOT / "data" / "goodell" / "meta.json"
LAST_SECTION = 683
NUMBER_RE = re.compile(r"^(\d+)\.\s*")
NUMBER_ANY_RE = re.compile(r"\b(\d{1,3})\b")
GREEK_RE = re.compile(r"[\u0370-\u03ff\u1f00-\u1fff]")
# A lettered example ("a. \u039f\u1f50\u03b4\u03b5\u1f76\u03c2 \u1f14\u03c4\u03b9 \u1f21\u03bc\u1fd6\u03bd \u03bc\u03ac\u03c7\u03b5\u03c4\u03b1\u03b9.") carries its label on the
# Greek line.  The label is English, so without stripping it the line fails
# the no-Latin test below and the whole example is dropped (13 sites, chiefly
# the tense sections 454-462).
EXAMPLE_LABEL_RE = re.compile(r"^[a-z]\.\s+")
# The parts of a citation line that are not the citation (see ``citation_of``).
FOOTNOTE_RE = re.compile(r"\[fn\].*?\[/fn\]", re.DOTALL)
BRACKETED_RE = re.compile(r"\([^()]*\)")
DIGIT_RE = re.compile(r"\d")
LATIN_MACRONS = str.maketrans("ĀĒĪŌŪȲāēīōūȳ", "AEIOUYaeiouy")
LOOKALIKE_PAIRS = {
    "A": "Α", "B": "Β", "E": "Ε", "H": "Η", "I": "Ι", "K": "Κ", "M": "Μ",
    "N": "Ν", "O": "Ο", "P": "Ρ", "T": "Τ", "X": "Χ", "Y": "Υ", "Z": "Ζ",
    "a": "α", "b": "β", "e": "ε", "h": "η", "i": "ι", "k": "κ", "m": "μ",
    "n": "ν", "o": "ο", "p": "ρ", "t": "τ", "x": "χ", "y": "υ", "z": "ζ",
}
GREEK_LOOKALIKES = str.maketrans(LOOKALIKE_PAIRS)
LATIN_LOOKALIKES = str.maketrans({g: l for l, g in LOOKALIKE_PAIRS.items()})
LATIN_RANGE = "A-Za-z\u00c0-\u00d6\u00d8-\u00f6\u00f8-\u024f"
GREEK_RANGE = "\u0370-\u03ff\u1f00-\u1fff"
WORD_RE = re.compile(f"[{LATIN_RANGE}{GREEK_RANGE}\u0300-\u036f]+")
# A hyphen joining two letters continues the word, so a sigma before it is
# medial.  The grammar hyphenates stems constantly ("στεφ-ανός").
HYPHEN_CONTINUES = re.compile(f"[-\u2010\u2011][{LATIN_RANGE}{GREEK_RANGE}]")
WORD_NUMBER = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
}
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "wbr"}
BLOCK_TAGS = {"p", "div", "table", "ul", "ol", "dl", "blockquote", "pre", "hr"}
# Tags whose edges are word boundaries when the markup is flattened to text.
PLAIN_SEPARATORS = BLOCK_TAGS | {"br", "tr", "td", "th", "li", "dt", "dd"}


def norm(value: str | None) -> str:
    return re.sub(r"\s+", " ", clean_chars(value or "")).strip()


def _script_evidence(word: str) -> tuple[bool, bool]:
    """Report whether a word holds letters only one script can explain.

    A lookalike (Latin o / Greek omicron) proves nothing.  A Latin w, or a
    Greek omega or any accented vowel, settles which script the word is in.
    """
    latin = greek = False
    previous_greek = False
    for char in word:
        if unicodedata.combining(char):
            greek = greek or previous_greek
            continue
        is_greek = bool(GREEK_RE.fullmatch(char))
        if is_greek:
            greek = greek or ord(char) not in LATIN_LOOKALIKES
        elif char.isalpha():
            latin = latin or ord(char) not in GREEK_LOOKALIKES
        previous_greek = is_greek
    return latin, greek


def _final_sigma(word: str, *, word_continues: bool = False) -> str:
    """Restore a sigma the source typed as a Latin s.

    Only fires on a word whose sole Latin letter is that trailing s, so a
    Greek headword glued to an English gloss is never touched.  The word
    carrying on over a hyphen makes the sigma medial rather than final.
    """
    if not word.endswith(("s", "S")) or len(word) < 2:
        return word
    body = word[:-1]
    if re.search(rf"[{LATIN_RANGE}]", body):
        return word
    stem = body.rstrip("".join(c for c in body if unicodedata.combining(c)))
    if not stem or not GREEK_RE.fullmatch(stem[-1]):
        return word
    if not _script_evidence(body)[1]:
        return word
    if word.endswith("S"):
        return body + "Σ"
    return body + ("σ" if word_continues else "ς")


def _repair_word(word: str, *, word_continues: bool = False) -> str:
    """Move stray lookalikes into whichever script the word is written in."""
    word = _final_sigma(word, word_continues=word_continues)
    latin, greek = _script_evidence(word)
    if greek and not latin:
        return word.translate(GREEK_LOOKALIKES)
    if latin and not greek:
        return word.translate(LATIN_LOOKALIKES)
    if latin and greek:
        # Both scripts are attested: a Greek word run into an English gloss,
        # not a lookalike substitution.  Guessing here would damage real text.
        return word
    # Nothing but lookalikes.  Fall back to the neighbouring character, which
    # keeps short Greek fragments ("Mε") Greek.
    chars = list(word)
    for index, char in enumerate(chars):
        if ord(char) not in GREEK_LOOKALIKES:
            continue
        left = chars[index - 1] if index else ""
        right = chars[index + 1] if index + 1 < len(chars) else ""
        if GREEK_RE.fullmatch(left) or GREEK_RE.fullmatch(right):
            chars[index] = char.translate(GREEK_LOOKALIKES)
    return "".join(chars)


def clean_chars(value: str) -> str:
    """Apply the data set's Greek and Latin-quantity character policy."""
    value = unicodedata.normalize("NFC", value).translate(LATIN_MACRONS)

    def repair(match: re.Match[str]) -> str:
        rest = match.string[match.end():]
        return _repair_word(match.group(),
                            word_continues=bool(HYPHEN_CONTINUES.match(rest)))

    return WORD_RE.sub(repair, value)


def json_line(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class Node:
    def __init__(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tag = tag.lower()
        self.attrs = {key.lower(): value or "" for key, value in attrs}
        self.children: list[Node | str] = []
        self.parent: Node | None = None

    def add(self, child: Node | str) -> None:
        self.children.append(child)
        if isinstance(child, Node):
            child.parent = self

    def attr_words(self, name: str) -> set[str]:
        return set(self.attrs.get(name, "").split())


class TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("root", [])
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = Node(tag, attrs)
        self.stack[-1].add(node)
        if node.tag not in VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.stack[-1].add(Node(tag, attrs))

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        # The mirrors contain a few mismatched inline close tags.  Treating a
        # distant match as authoritative can eject the remaining article body.
        if len(self.stack) > 1 and self.stack[-1].tag == tag:
            self.stack.pop()

    def handle_data(self, data: str) -> None:
        self.stack[-1].add(data)


def descendants(node: Node) -> Iterator[Node]:
    for child in node.children:
        if isinstance(child, Node):
            yield child
            yield from descendants(child)


def text_of(node: Node, *, skip: set[str] | None = None) -> str:
    parts: list[str] = []
    def walk(value: Node | str) -> None:
        if isinstance(value, str):
            parts.append(value)
        elif value.tag not in (skip or set()):
            for item in value.children:
                walk(item)
    walk(node)
    return norm("".join(parts))


def find_article(root: Node) -> Node:
    for node in descendants(root):
        if node.tag == "article" and "grammar-goodell" in node.attr_words("class"):
            return node
    raise ValueError("no Goodell article found")


def page_title(root: Node) -> str:
    for node in descendants(root):
        if node.tag == "h1" and "page-title" in node.attr_words("class"):
            return text_of(node)
    raise ValueError("no page title found")


def article_body(article: Node) -> Node:
    for node in descendants(article):
        if node.tag != "div" or "field--name-body" not in node.attr_words("class"):
            continue
        current = node.parent
        while current is not None and current is not article:
            if current.attrs.get("id") == "node-grammar-goodell-full-group-main":
                return node
            current = current.parent
    raise ValueError("no Goodell article body found")


def marker_in(block: Node) -> tuple[int, Node] | None:
    """Find a numbered strong marker only when it starts a content block."""
    block_text = text_of(block)
    for node in descendants(block):
        if node.tag != "strong":
            continue
        label = text_of(node)
        match = NUMBER_RE.match(label)
        bare = re.fullmatch(r"(\d+)", label)
        number = int(match.group(1)) if match else int(bare.group(1)) if bare else None
        if number is not None and block_text.startswith(f"{number}."):
            return number, node
    # One DCC marker (523) splits its number across two adjacent strong tags.
    # Its full block still has the standard unambiguous leading ``N.`` form.
    strongs = [node for node in descendants(block) if node.tag == "strong"]
    if len(strongs) >= 2:
        match = NUMBER_RE.fullmatch(text_of(strongs[0]) + text_of(strongs[1]))
        if match and block_text.startswith(match.group(0)):
            return int(match.group(1)), block
    return None


def remove_marker(node: Node, marker: Node, number: int) -> Node:
    """Return a cloned tree with just the leading section number omitted."""
    in_marker = False
    number_removed = False
    needs_dot = False
    split_prefix = str(number) + "."
    split_started = marker is node
    split_done = False
    def clone(value: Node | str) -> Node | str | None:
        nonlocal in_marker, number_removed, needs_dot, split_prefix, split_started, split_done
        if isinstance(value, str):
            if split_started and not split_done:
                output: list[str] = []
                for char in value:
                    if split_prefix and char == split_prefix[0]:
                        split_prefix = split_prefix[1:]
                        continue
                    if not split_prefix:
                        split_done = True
                    output.append(char)
                return "".join(output)
            if in_marker and not number_removed:
                value, count = re.subn(rf"^\s*{number}\.\s*", "", value, count=1)
                if count:
                    number_removed = True
                else:
                    value, count = re.subn(rf"^\s*{number}\s*", "", value, count=1)
                    if count:
                        number_removed = True
                        needs_dot = True
            elif needs_dot:
                value, count = re.subn(r"^\.\s*", "", value, count=1)
                if count:
                    needs_dot = False
            return value
        was_marker = value is marker
        if was_marker:
            in_marker = True
        copied = Node(value.tag, list(value.attrs.items()))
        for child in value.children:
            item = clone(child)
            if item is not None:
                copied.add(item)
        if was_marker:
            in_marker = False
        return copied
    result = clone(node)
    assert isinstance(result, Node)
    return result


def relevant_blocks(body: Node) -> list[Node]:
    """Flatten layout divs while retaining real prose and table blocks."""
    blocks: list[Node] = []
    content_tags = {"p", "table", "ul", "ol", "dl", "blockquote", "pre", "h2", "h3", "h4", "h5", "h6", "hr"}

    def walk(node: Node) -> bool:
        found = False
        for child in node.children:
            if not isinstance(child, Node):
                continue
            classes = child.attr_words("class")
            if "group-extra" in classes or "region" in classes or "block" in classes:
                continue
            if child.tag in content_tags:
                blocks.append(child)
                found = True
            elif walk(child):
                found = True
            elif child.tag == "div" and text_of(child):
                blocks.append(child)
                found = True
        return found

    walk(body)
    return blocks


def safe_class(node: Node) -> str:
    values = [value for value in node.attrs.get("class", "").split() if re.fullmatch(r"[A-Za-z0-9_-]+", value)]
    return " ".join(values)


def ref_number(node: Node) -> int | None:
    value = text_of(node)
    matches = NUMBER_ANY_RE.findall(value)
    if matches:
        number = int(matches[-1])
        if 1 <= number <= LAST_SECTION:
            return number
    href = node.attrs.get("href", "")
    fragment = urlparse(href).fragment.lower()
    if fragment:
        digits = "".join(WORD_NUMBER[word] for word in fragment.split("-") if word in WORD_NUMBER)
        if digits and 1 <= int(digits) <= LAST_SECTION:
            return int(digits)
    return None


def render(node: Node | str) -> str:
    if isinstance(node, str):
        return html.escape(clean_chars(node), quote=False)
    inner = "".join(render(child) for child in node.children)
    tag = node.tag
    if tag in {"script", "style", "meta", "img", "iframe", "form", "input"}:
        if tag == "img" and node.attrs.get("alt"):
            return f'<span class="image-alt">[Image: {html.escape(clean_chars(node.attrs["alt"]), quote=False)}]</span>'
        return ""
    if tag == "br":
        return "<br>"
    if tag == "hr":
        return "<hr>"
    if tag in {"p", "table", "thead", "tbody", "tfoot", "tr", "td", "th", "ul", "ol", "li", "dl", "dt", "dd", "blockquote", "pre"}:
        return f"<{tag}>{inner}</{tag}>"
    if tag in {"em", "i"}:
        return f"<em>{inner}</em>"
    if tag in {"strong", "b"}:
        return f"<strong>{inner}</strong>"
    if tag == "a":
        number = ref_number(node)
        return f'<a data-ref="goodell:{number}">{inner}</a>' if number is not None else inner
    if tag == "span":
        attrs: list[str] = []
        css = safe_class(node)
        if css:
            attrs.append(f' class="{css}"')
        lang = node.attrs.get("lang", "").lower()
        if lang in {"grc", "el", "greek"}:
            attrs.append(' lang="grc"')
        return f"<span{''.join(attrs)}>{inner}</span>"
    if tag in {"div", "section", "figure", "figcaption", "sup", "sub", "small"}:
        return inner
    return inner


def plain(node: Node) -> str:
    parts: list[str] = []
    def walk(value: Node | str) -> None:
        if isinstance(value, str):
            parts.append(value)
        elif value.tag == "img" and value.attrs.get("alt"):
            parts.append(f" [Image: {value.attrs['alt']}] ")
        elif value.tag not in {"script", "style", "meta", "iframe", "form", "input"}:
            # A line or cell break is a word boundary.  Without the space the
            # DCC pattern "<strong>Greek</strong><br><em>gloss</em>" fuses into
            # one word, and clean_chars then reads the gloss as Greek.
            separates = value.tag in PLAIN_SEPARATORS
            if separates:
                parts.append(" ")
            for child in value.children:
                walk(child)
            if separates:
                parts.append(" ")
    walk(node)
    return norm("".join(parts))


def lines_of(node: Node) -> list[str]:
    lines: list[list[str]] = [[]]
    def walk(value: Node | str) -> None:
        if isinstance(value, str):
            lines[-1].append(value)
        elif value.tag == "br":
            lines.append([])
        elif value.tag not in {"script", "style", "meta", "img", "iframe", "form", "input"}:
            for child in value.children:
                walk(child)
    walk(node)
    return [norm("".join(line)) for line in lines if norm("".join(line))]


def citation_of(cite_lines: list[str]) -> str:
    """The reference the print gives, and nothing else.

    An example may carry, on its own ``<br>`` line or after the reference, a
    grammatical label or a note: "(Possessive Genitive)", "(Historical
    Present)", "(The king is thought of as the central figure.)", and at
    goodell:454 a footnote body as well.  Joining the lines put those in the
    citation field, so goodell:506 shipped a cite of "(Possessive Genitive)"
    where the print gives no reference at all, and goodell:498 shipped "(The
    king is thought of as the central figure.) Xen. Anabasis 1.10.1".

    A grammatical label is not a citation.  Every reference in this grammar is
    an author, a work and a number, so a bracketed run with no numeral in it
    cannot be one and is dropped; so is a footnote.  What is left is the
    reference.  When nothing is left the block is not the three-line pattern
    and ``extract_examples`` takes no example from it.
    """
    text = FOOTNOTE_RE.sub(" ", " ".join(cite_lines))
    text = BRACKETED_RE.sub(
        lambda match: match.group(0) if DIGIT_RE.search(match.group(0)) else " ", text
    )
    return norm(text).strip(" ,;:.")


def extract_examples(blocks: list[Node]) -> list[dict[str, str]]:
    """Extract only the DCC three-line Greek / italic gloss / citation pattern."""
    result: list[dict[str, str]] = []
    for block in blocks:
        if block.tag != "p":
            continue
        lines = lines_of(block)
        if len(lines) < 3:
            continue
        grc, gloss, *cite_lines = lines
        grc = EXAMPLE_LABEL_RE.sub("", grc)
        cite = citation_of(cite_lines)
        if (
            GREEK_RE.search(grc)
            and not re.search(r"[A-Za-z]", grc)
            and re.search(r"[A-Za-z]", gloss)
            and not GREEK_RE.search(gloss)
            and cite
            and not GREEK_RE.search(cite)
        ):
            item = {"grc": grc, "gloss": gloss, "cite": cite}
            if item not in result:
                result.append(item)
    return result


def refs_of(blocks: list[Node]) -> list[str]:
    refs: list[str] = []
    for block in blocks:
        for node in descendants(block):
            if node.tag == "a":
                number = ref_number(node)
                target = f"goodell:{number}" if number is not None else None
                if target and target not in refs:
                    refs.append(target)
    return refs


def convert(source_dir: Path) -> tuple[list[dict[str, object]], dict[str, object]]:
    sections: dict[int, dict[str, object]] = {}
    marker_audit: list[dict[str, object]] = []
    # DCC stacks a combining macron OUTERMOST, over breathing and accent, the
    # same transmission defect Smyth's print corrects innermost.  Restacked
    # here with the shared rule (see convert_smyth.STACKED_MACRON_RE) before
    # the HTML parser ever sees the text -- the regex only matches Greek
    # letter clusters, so running it over the raw markup is safe.
    mark_repairs = {"macronsRestacked": 0, "ancepsMacronsKept": 0, "subscriptMacronsKept": 0}
    for path in sorted(source_dir.glob("*.html")):
        parser = TreeBuilder()
        text = unicodedata.normalize("NFC", path.read_text(encoding="utf-8"))
        text = convert_smyth.restack_macron_text(text, mark_repairs)
        parser.feed(text)
        parser.close()
        root = parser.root
        article = find_article(root)
        body = article_body(article)
        title = page_title(root)
        slug = unquote(path.stem)
        current: int | None = None
        payloads: dict[int, list[Node]] = collections.defaultdict(list)
        headings: dict[int, list[str]] = {}
        local_headings: list[str] = []
        for block in relevant_blocks(body):
            if block.tag in {"h2", "h3", "h4", "h5", "h6"}:
                heading = text_of(block)
                if heading:
                    local_headings = [heading]
                continue
            marker = marker_in(block)
            if marker:
                number, strong = marker
                marker_audit.append({"n": number, "sourceSlug": slug, "label": text_of(strong)})
                current = number
                headings[number] = [title, *local_headings]
                payloads[number].append(remove_marker(block, strong, number))
            elif current is not None:
                payloads[current].append(block)
        for number, blocks in payloads.items():
            if number in sections:
                raise ValueError(f"duplicate section {number}: {sections[number]['sourceSlug']} and {slug}")
            body_html = "".join(render(block) for block in blocks)
            body_plain = norm(" ".join(plain(block) for block in blocks))
            # A malformed table on one mirror page swallows its later Drupal
            # footer in the stdlib HTML tree.  The citation block is chrome,
            # never Goodell text, so retain only the preceding body text.
            body_plain = re.split(r"\b(?:Chapter-\d+\.xml|Suggested Citation)\b", body_plain, maxsplit=1)[0].strip()
            if not body_plain:
                body_plain = "[Image-only section: DCC source provides an uncaptioned image.]"
            path_value = headings[number] or [title]
            sections[number] = {
                "work": "goodell",
                "n": number,
                "id": f"goodell:{number}",
                "sourceSlug": slug,
                "letters": [],
                "notes": [],
                "path": path_value,
                "head": path_value[-1],
                "html": f'<section id="s{number}">{body_html}</section>',
                "plain": body_plain,
                "examples": extract_examples(blocks),
                "refs": refs_of(blocks),
                "refRanges": [],
                "citedBy": [],
                "prev": None,
                "next": None,
            }
    records = [sections[number] for number in sorted(sections)]
    by_id = {str(record["id"]): record for record in records}
    for index, record in enumerate(records):
        record["prev"] = records[index - 1]["id"] if index else None
        record["next"] = records[index + 1]["id"] if index + 1 < len(records) else None
        for target in record["refs"]:
            if target in by_id:
                by_id[target]["citedBy"].append(record["id"])
    meta: dict[str, object] = {
        "work": "goodell",
        "title": "A School Grammar of Attic Greek",
        "source": "grammar-goodell/src/dcc/",
        "edition": "DCC corrected edition",
        "license": "CC BY-SA",
        "attribution": "Text: Dickinson College Commentaries edition",
        "counts": {
            "pages": len(list(source_dir.glob("*.html"))),
            "sections": len(records),
            "sectionMarkers": len(marker_audit),
            "examples": sum(len(record["examples"]) for record in records),
            "sectionCrossRefs": sum(len(record["refs"]) for record in records),
        },
        "anomalies": {
            "markerAudit": marker_audit,
            "missingSections": [number for number in range(1, LAST_SECTION + 1) if number not in sections],
            "sourceMarkRepairs": mark_repairs,
        },
    }
    return records, meta


def write_outputs(records: list[dict[str, object]], meta: dict[str, object], sections: Path, meta_path: Path) -> None:
    sections.parent.mkdir(parents=True, exist_ok=True)
    sections.write_bytes(("\n".join(json_line(record) for record in records) + "\n").encode("utf-8"))
    meta_path.write_bytes((json.dumps(meta, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--sections", type=Path, default=DEFAULT_SECTIONS)
    parser.add_argument("--meta", type=Path, default=DEFAULT_META)
    args = parser.parse_args()
    records, meta = convert(args.input)
    write_outputs(records, meta, args.sections, args.meta)
    print(f"converted {len(records)} sections from {meta['counts']['pages']} DCC pages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
