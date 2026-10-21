#!/usr/bin/env python3
"""Convert the mirrored DCC Monro pages to canonical section JSON.

The 205 source files are offline Drupal page mirrors.  Only the grammar body
inside each ``article.grammar-monro`` is retained.  Printed section labels are
the leading bold text of a paragraph.  Starred labels on three pages mark a
continuation of an earlier section rather than a new numbered item.
"""

from __future__ import annotations

import argparse
import collections
import html
import json
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "grammar-monro" / "src" / "dcc"
DEFAULT_SECTIONS = ROOT / "data" / "monro" / "sections.jsonl"
DEFAULT_META = ROOT / "data" / "monro" / "meta.json"
LAST_SECTION = 405

BODY_OPEN_RE = re.compile(
    r'<div\b(?=[^>]*\bfield--name-body\b)[^>]*>', re.I
)
DIV_TAG_RE = re.compile(r"<div\b[^>]*>|</div\s*>", re.I)
TITLE_RE = re.compile(
    r'<h1\b[^>]*\bpage-title\b[^>]*>(.*?)</h1\s*>', re.I | re.S
)
TAG_RE = re.compile(r"<[^>]+>")
MARKER_RE = re.compile(
    r'(?P<open><p\b[^>]*>)\s*'
    r'(?:<a\b[^>]*>\s*</a>\s*)*'
    r'<(?P<tag>strong|b)\b[^>]*>(?P<label>.*?)</(?P=tag)>',
    re.I | re.S,
)
MARKER_LABEL_RE = re.compile(
    r"^(\d{1,3})(?:\.(\d+))?\.?\s*(\*)?\.?$"
)
# The DCC sets 63 line numbers with a space after the book dot ("Il. 1. 515");
# the space is a typesetting slip, so the pattern tolerates it and the cite is
# normalized back to "Il. 1.515" (CITE_SPACE_RE) for consumers that key on it.
CITE_RE = re.compile(
    r"^(?P<cite>(?:Il|Od)\.\s*\d+\.\s*\d+(?:\s*[-–—]\s*\d+)?)\s+(?P<quote>.+)$"
)
CITE_SPACE_RE = re.compile(r"(\d)\.\s+(\d)")
# "(= 19.150, 24.140)": the further places the same verse occupies, which
# the DCC prints between the citation and the verse.
PARALLEL_RE = re.compile(r"^\s*\(\s*=\s*[\d.,\s;–—-]+\)\s*")
# A quotation cannot begin with a bare number.  Where one does, the DCC has
# split the line number and CITE_RE, which tolerates a space after the book
# dot, has stopped inside it: "Od. 11. 4 19 ὡς ἀμφὶ κρητῆρα" is Od. 11.419,
# not Od. 11.4, and "Od. 3.17 1 νεοίμεθα" is Od. 3.171.  Joining the halves
# would be a guess about a second slip, so the example is dropped instead.
SPLIT_LINE_RE = re.compile(r"^\d")
# A citation the DCC set in Greek letters, which the cut at the first Latin
# letter cannot see: §12 runs "Il. 2.77 <verse> Οδ. 17.208 <verse>" into one
# paragraph and §136 does the same with "Ιλ. 24.735", so both verses shipped
# under the first citation.
GREEK_CITE_RE = re.compile(r"[ἸΙ]λ\s*\.|[ὈΟ]δ\s*\.")
# A cross reference to another section of Monro, which the print sets in the
# note after the verse: "ναῦφιν ἀμυνόμενοι (§ 152)".
SECTION_REF_RE = re.compile(r"§")
# The bracketed runs of a quotation, outermost first.
BRACKET_RE = re.compile(r"[([][^()\[\]]*[)\]]")
SCRIPT_WORD_RE = re.compile(
    r"[A-Za-z\u00c0-\u024f\u1e00-\u1eff\u0370-\u03ff\u1f00-\u1fff\u0300-\u036f]+"
)
GREEK_RE = re.compile(r"[\u0370-\u03ff\u1f00-\u1fff]")
ASCII_RE = re.compile(r"[A-Za-z]")
RANGE_RE = re.compile(r"(\d+)\s*[-–—]\s*(\d+)")

LATIN_QUANTITY_TO_GREEK = {
    "ā": "ᾱ", "ē": "ε\u0304", "ī": "ῑ", "ō": "ο\u0304", "ū": "ῡ",
    "ă": "ᾰ", "ĕ": "ε\u0306", "ĭ": "ῐ", "ŏ": "ο\u0306", "ŭ": "ῠ",
    "Ā": "Ᾱ", "Ē": "Ε\u0304", "Ī": "Ῑ", "Ō": "Ο\u0304", "Ū": "Ῡ",
    "Ă": "Ᾰ", "Ĕ": "Ε\u0306", "Ĭ": "Ῐ", "Ŏ": "Ο\u0306", "Ŭ": "Ῠ",
}
LATIN_QUANTITY_VOWELS = frozenset(LATIN_QUANTITY_TO_GREEK)
ASCII_TO_GREEK = {
    "a": "α", "b": "β", "c": "κ", "d": "δ", "e": "ε", "f": "φ",
    "g": "γ", "h": "η", "i": "ι", "j": "ϳ", "k": "κ", "l": "λ",
    "m": "μ", "n": "ν", "o": "ο", "p": "ρ", "q": "θ", "r": "ρ",
    "s": "ς", "t": "τ", "u": "υ", "v": "ν", "w": "ω", "x": "χ",
    "y": "υ", "z": "ζ",
}
ASCII_TO_GREEK.update({key.upper(): value.upper() for key, value in list(ASCII_TO_GREEK.items())})
GREEK_TO_LATIN = {
    "α": "a", "β": "b", "γ": "g", "δ": "d", "ε": "e", "ζ": "z",
    "η": "e", "θ": "th", "ι": "i", "κ": "k", "λ": "l", "μ": "m",
    "ν": "v", "ξ": "x", "ο": "o", "π": "p", "ρ": "r", "σ": "s",
    "ς": "s", "τ": "t", "υ": "u", "φ": "ph", "χ": "ch", "ψ": "ps",
    "ω": "o",
}
BLOCK_TAGS = {"p", "div", "ol", "ul", "li", "table", "thead", "tbody", "tr", "td", "th", "blockquote", "h2", "h3", "h4"}
TEXT_SCOPE_TAGS = {"p", "li", "td", "th", "blockquote", "h2", "h3", "h4"}
VOID_TAGS = {"br", "hr", "img", "input", "meta", "link"}


def norm(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def is_latin_letter(char: str) -> bool:
    return char.isalpha() and unicodedata.name(char, "").startswith("LATIN ")


def is_greek_letter(char: str) -> bool:
    return char.isalpha() and unicodedata.name(char, "").startswith("GREEK ")


def token_script(value: str) -> str | None:
    latin = sum(is_latin_letter(char) for char in value)
    greek = sum(is_greek_letter(char) for char in value)
    if not latin and not greek:
        return None
    if latin == greek:
        for char in value:
            if is_latin_letter(char):
                return "latin"
            if is_greek_letter(char):
                return "greek"
    return "latin" if latin > greek else "greek"


def latin_to_greek(char: str) -> str:
    if char in LATIN_QUANTITY_TO_GREEK:
        return LATIN_QUANTITY_TO_GREEK[char]
    decomposed = unicodedata.normalize("NFD", char)
    if not decomposed:
        return char
    mapped = ASCII_TO_GREEK.get(decomposed[0])
    return mapped + decomposed[1:] if mapped else char


def greek_to_latin(char: str) -> str:
    if not is_greek_letter(char):
        return char
    base = unicodedata.normalize("NFD", char)[0].lower()
    replacement = GREEK_TO_LATIN.get(base, "")
    return replacement.capitalize() if char.isupper() else replacement


def nearest_context_script(
    value: str, matches: list[re.Match[str]], index: int, scripts: list[str | None]
) -> str:
    candidates: list[tuple[int, int, str]] = []
    for direction in (-1, 1):
        neighbor = index + direction
        while 0 <= neighbor < len(matches):
            script = scripts[neighbor]
            if script is not None:
                if direction < 0:
                    gap = value[matches[neighbor].end() : matches[index].start()]
                    side = 0
                else:
                    gap = value[matches[index].end() : matches[neighbor].start()]
                    side = 1
                distance = len(re.sub(r"\s+", "", gap))
                candidates.append((distance, side, script))
                break
            neighbor += direction
    return min(candidates)[2] if candidates else "latin"


def normalize_flat(
    value: str, stats: collections.Counter[str] | None = None
) -> str:
    matches = list(SCRIPT_WORD_RE.finditer(value))
    scripts = [token_script(match.group()) for match in matches]
    targets: list[str] = []
    for index, match in enumerate(matches):
        token = match.group()
        script = scripts[index]
        bare_quantity = script == "latin" and all(
            char in LATIN_QUANTITY_VOWELS or unicodedata.combining(char)
            for char in token
        )
        if bare_quantity:
            script = nearest_context_script(value, matches, index, scripts)
        target = script or "latin"
        targets.append(target)
        has_quantity = any(char in LATIN_QUANTITY_VOWELS for char in token)
        has_latin = any(is_latin_letter(char) for char in token)
        has_greek = any(is_greek_letter(char) for char in token)
        if stats is not None and has_quantity:
            quantity_count = sum(char in LATIN_QUANTITY_VOWELS for char in token)
            if bare_quantity or (has_latin and has_greek):
                stats[f"{target}ContextTokens"] += 1
                stats[f"{target}ContextCharacters"] += quantity_count
            else:
                stats["retainedLatinWordTokens"] += 1
                stats["retainedLatinWordCharacters"] += quantity_count
        if stats is not None and has_latin and has_greek:
            stats["mixedScriptTokens"] += 1

    parts: list[str] = []
    position = 0
    for match, target in zip(matches, targets):
        parts.append(value[position : match.start()])
        token = match.group()
        if target == "greek":
            parts.append("".join(latin_to_greek(char) if is_latin_letter(char) else char for char in token))
        else:
            parts.append("".join(greek_to_latin(char) if is_greek_letter(char) or unicodedata.combining(char) else char for char in token))
        position = match.end()
    parts.append(value[position:])
    return unicodedata.normalize("NFC", "".join(parts))


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    value = value.replace("\u00a0", " ")
    return normalize_flat(value)


def visible_html(value: str) -> str:
    return norm(clean_text(html.unescape(TAG_RE.sub("", value))))


def extract_div_inner(article: str) -> str:
    match = BODY_OPEN_RE.search(article)
    if match is None:
        raise ValueError("no grammar body field in article")
    depth = 1
    for token in DIV_TAG_RE.finditer(article, match.end()):
        if token.group().lower().startswith("</"):
            depth -= 1
            if depth == 0:
                return article[match.end() : token.start()]
        else:
            depth += 1
    raise ValueError("unclosed grammar body field")


def page_parts(path: Path) -> tuple[str, str]:
    source = unicodedata.normalize("NFC", path.read_text(encoding="utf-8"))
    article_start = source.find("<article ")
    article_end = source.find("</article>", article_start)
    if article_start < 0 or article_end < 0:
        raise ValueError(f"{path.name}: no grammar article")
    title_match = TITLE_RE.search(source)
    if title_match is None:
        raise ValueError(f"{path.name}: no page title")
    article = source[article_start:article_end]
    body = extract_div_inner(article) if BODY_OPEN_RE.search(article) else ""
    return visible_html(title_match.group(1)), body


@dataclass
class Node:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list[Node | str] = field(default_factory=list)


class FragmentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("root")
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = Node(tag.lower(), {key.lower(): value or "" for key, value in attrs})
        self.stack[-1].children.append(node)
        if tag.lower() not in VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                self.stack = self.stack[:index]
                return

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data.replace("\u00a0", " "))


def text_leaves(node: Node) -> list[tuple[Node, int, str]]:
    leaves: list[tuple[Node, int, str]] = []
    for index, child in enumerate(node.children):
        if isinstance(child, str):
            leaves.append((node, index, child))
        elif child.tag != "img":
            leaves.extend(text_leaves(child))
    return leaves


def normalize_scope(node: Node, stats: collections.Counter[str]) -> None:
    leaves = text_leaves(node)
    if not leaves:
        return
    starts: list[int] = []
    parts: list[str] = []
    position = 0
    for _, _, value in leaves:
        starts.append(position)
        parts.append(value)
        position += len(value)
    source = "".join(parts)
    matches = list(SCRIPT_WORD_RE.finditer(source))
    scripts = [token_script(match.group()) for match in matches]
    targets: list[str] = []
    for index, match in enumerate(matches):
        token = match.group()
        script = scripts[index]
        bare_quantity = script == "latin" and all(
            char in LATIN_QUANTITY_VOWELS or unicodedata.combining(char)
            for char in token
        )
        if bare_quantity:
            script = nearest_context_script(source, matches, index, scripts)
        target = script or "latin"
        targets.append(target)
        has_quantity = any(char in LATIN_QUANTITY_VOWELS for char in token)
        has_latin = any(is_latin_letter(char) for char in token)
        has_greek = any(is_greek_letter(char) for char in token)
        if has_quantity:
            quantity_count = sum(char in LATIN_QUANTITY_VOWELS for char in token)
            if bare_quantity or (has_latin and has_greek):
                stats[f"{target}ContextTokens"] += 1
                stats[f"{target}ContextCharacters"] += quantity_count
            else:
                stats["retainedLatinWordTokens"] += 1
                stats["retainedLatinWordCharacters"] += quantity_count
        if has_latin and has_greek:
            stats["mixedScriptTokens"] += 1

    replacements = list(source)
    for match, target in zip(matches, targets):
        for offset, char in enumerate(match.group(), match.start()):
            if target == "greek" and is_latin_letter(char):
                replacements[offset] = latin_to_greek(char)
            elif target == "latin" and is_greek_letter(char):
                replacements[offset] = greek_to_latin(char)
    for (parent, index, original), start in zip(leaves, starts):
        parent.children[index] = unicodedata.normalize(
            "NFC", "".join(replacements[start : start + len(original)])
        )


def normalize_tree(node: Node, stats: collections.Counter[str]) -> None:
    if node.tag in TEXT_SCOPE_TAGS:
        normalize_scope(node, stats)
        return
    for index, child in enumerate(node.children):
        if isinstance(child, str):
            node.children[index] = normalize_flat(child, stats)
        else:
            normalize_tree(child, stats)


def node_text(node: Node | str) -> str:
    if isinstance(node, str):
        return node
    if node.tag == "img":
        return clean_text(node.attrs.get("alt", ""))
    return "".join(node_text(child) for child in node.children)


def descendants(node: Node, tag: str) -> Iterable[Node]:
    for child in node.children:
        if not isinstance(child, Node):
            continue
        if child.tag == tag:
            yield child
        yield from descendants(child, tag)


def close_open_bracket(value: str) -> str:
    """Cut a quotation at a bracket the print never closes inside it.

    The DCC sets an editor's note after the verse, often opening it with a
    bracket and a quotation mark: "Il. 4.407 ἀγαγόνθʼ (\"Diomede and I\")",
    "Od. 6.221 ἄντην δʼ οὐκ ἂν ἔγωγε λοέσσομαι (ἄντην is emphatic: cp. ...)".
    Cutting the note at its first Latin letter leaves the bracket, and with
    it the first Greek word of a note that is not part of the verse.
    """
    depth = 0
    opened = None
    for index, character in enumerate(value):
        if character in "([":
            if depth == 0:
                opened = index
            depth += 1
        elif character in ")]" and depth:
            depth -= 1
    if depth and opened is not None:
        return value[:opened].rstrip(" ([“”\"")
    return value


def drop_note_brackets(quote: str, printed: str) -> str:
    """Cut a quotation at a bracket the print does not set the way it stands.

    Dropping the emphasized words leaves the brackets that held them: the print
    sets "θάνατόν νύ τοι ὅρκι᾿ ἔταμνον it was death then to you that I made (in
    making the treaty)" and the quotation came away as "θάνατόν νύ τοι ὅρκι᾿
    ἔταμνον ()".  Where the note is itself in Greek the cut at the first Latin
    letter never fires and the whole of it stayed inside the verse, as
    "(ὁμῆλιξ)" at §116 and "( ἵκοιτο)" at §282.

    ``printed`` is the paragraph as the DCC set it, emphasis and all.  A
    bracketed run the verse really carries stands there verbatim; one the
    emphasis has been taken out of does not, and the quotation ends where it
    opens.
    """
    for bracket in BRACKET_RE.finditer(quote):
        if bracket.group(0) not in printed:
            return quote[: bracket.start()].rstrip(" ([,;:·“”\"")
    return quote


def text_before_em(node: Node | str) -> str:
    """The paragraph's text up to the first emphasized word.

    The DCC sets the verse in plain type and its translation in emphasis, so
    the emphasis is where the verse ends.  This used to remove the emphasized
    words and keep everything else, which is not the same thing: whatever the
    print set between two emphasized runs came away inside the verse.  A note
    in brackets is the common case, and it arrived either emptied ("θάνατόν νύ
    τοι ὅρκι᾿ ἔταμνον ()" at §71, where the note "in making the treaty" stood
    inside the brackets) or whole ("ὁμηλικίη δέ μοί ἐσσι (ὁμῆλιξ)" at §116,
    where the print reads "you are one of the same age (ὁμῆλιξ) with me").
    """
    pieces: list[str] = []

    def walk(item: Node | str) -> bool:
        """Append ``item``'s text; return False at the first emphasis."""
        if isinstance(item, str):
            pieces.append(item)
            return True
        if item.tag in {"em", "i"}:
            return False
        for child in item.children:
            if not walk(child):
                return False
        return True

    walk(node)
    return "".join(pieces)


def extract_examples(root: Node) -> list[dict[str, str]]:
    examples: list[dict[str, str]] = []
    for paragraph in descendants(root, "p"):
        if "padding-left" not in paragraph.attrs.get("style", "").lower():
            continue
        value = norm(node_text(paragraph))
        match = CITE_RE.match(value)
        if match is None:
            continue
        before_em = norm(text_before_em(paragraph))
        quote_match = CITE_RE.match(before_em)
        quote = quote_match.group("quote") if quote_match else match.group("quote")
        ascii_start = ASCII_RE.search(quote)
        if ascii_start:
            quote = quote[: ascii_start.start()].rstrip(" ([,;:“”\"")
        # The parallel places the print notes after a citation belong to
        # it, not to the verse: §309 sets "Od. 2.105 (= 19.150, 24.140)
        # ἐπὴν δαΐδας παραθεῖτο" and the note led the quotation.
        quote = PARALLEL_RE.sub("", quote, count=1)
        # A second verse in the same paragraph, cited in Greek letters, and a
        # cross reference in the note after the verse, both of which the cut
        # at the first Latin letter walks straight past.
        quote = norm(close_open_bracket(quote))
        if not quote or not GREEK_RE.search(quote):
            continue
        if SPLIT_LINE_RE.match(quote):
            continue
        glosses = [norm(node_text(item)) for name in ("em", "i") for item in descendants(paragraph, name)]
        gloss = norm(" ".join(value for value in glosses if value))
        example = {
            "grc": quote,
            "gloss": gloss,
            "cite": CITE_SPACE_RE.sub(
                r"\1.\2", norm(match.group("cite")).replace(" – ", "–").replace(" - ", "-")
            ),
        }
        if example not in examples:
            examples.append(example)
    return examples


def digit_fragment(fragment: str) -> int | None:
    direct = re.match(r"(\d{1,3})", fragment)
    if direct:
        return int(direct.group(1))
    words = {"zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9"}
    digits: list[str] = []
    for part in fragment.lower().split("-"):
        if part == "point":
            break
        if part in words:
            digits.append(words[part])
        elif digits:
            break
    return int("".join(digits)) if digits else None


def resolve_refs(href: str, label: str, slug_sections: dict[str, list[int]]) -> list[int]:
    parsed = urlparse(href)
    if "/grammar/monro/" not in parsed.path:
        return []
    slug = unquote(parsed.path.rstrip("/").rsplit("/", 1)[-1])
    numbers = [
        int(match.group(1))
        for match in re.finditer(r"(?<!\d)(\d{1,3})(?:\.\d+)*(?!\d)", label)
    ]
    if not numbers:
        fragment_number = digit_fragment(unquote(parsed.fragment))
        if fragment_number is not None:
            numbers.append(fragment_number)
    if not numbers and len(slug_sections.get(slug, [])) == 1:
        numbers.extend(slug_sections[slug])
    return list(dict.fromkeys(number for number in numbers if 1 <= number <= LAST_SECTION))


class Renderer:
    def __init__(self, slug_sections: dict[str, list[int]]) -> None:
        self.slug_sections = slug_sections
        self.ref_uses: list[int] = []
        self.ranges: list[dict[str, int]] = []

    @staticmethod
    def text(value: str) -> str:
        return html.escape(re.sub(r"\s+", " ", value), quote=False)

    def inner(self, node: Node) -> str:
        return "".join(self.render(child) for child in node.children)

    def render(self, value: Node | str) -> str:
        if isinstance(value, str):
            return self.text(value)
        tag = value.tag
        content = self.inner(value).strip() if tag in BLOCK_TAGS else self.inner(value)
        if tag in {"script", "style", "form", "input", "button", "iframe", "svg"}:
            return ""
        if tag == "br":
            return "<br>"
        if tag == "img":
            alt = norm(value.attrs.get("alt", ""))
            return self.text(alt)
        if tag == "a":
            label = norm(node_text(value))
            targets = resolve_refs(value.attrs.get("href", ""), label, self.slug_sections)
            if not targets:
                return content
            self.ref_uses.extend(targets)
            found = RANGE_RE.search(label)
            if found:
                start = int(found.group(1))
                end_text = found.group(2)
                end = int(end_text)
                if end < start:
                    unit = 10 ** len(end_text)
                    end = (start // unit) * unit + end
                    if end < start:
                        end += unit
                item = {"start": start, "end": end}
                if item not in self.ranges:
                    self.ranges.append(item)
            return f'<a data-ref="monro:{targets[0]}">{content}</a>'
        rename = {"b": "strong", "i": "em"}.get(tag, tag)
        if rename in {"p", "ol", "ul", "li", "table", "thead", "tbody", "tr", "td", "th", "blockquote", "h2", "h3", "h4", "em", "strong", "sup", "sub", "span", "q"}:
            return f"<{rename}>{content}</{rename}>"
        return content


class PlainParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def boundary(self) -> None:
        if self.parts and not self.parts[-1].endswith(" "):
            self.parts.append(" ")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in BLOCK_TAGS or tag == "br":
            self.boundary()

    def handle_endtag(self, tag: str) -> None:
        if tag in BLOCK_TAGS:
            self.boundary()

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def plain_from_html(value: str) -> str:
    parser = PlainParser()
    parser.feed(value)
    parser.close()
    return norm("".join(parser.parts))


def parse_fragment(raw: str, stats: collections.Counter[str]) -> Node:
    parser = FragmentParser()
    parser.feed(raw)
    parser.close()
    normalize_tree(parser.root, stats)
    return parser.root


def marker_candidates(body: str) -> list[tuple[re.Match[str], int, bool, str]]:
    found: list[tuple[re.Match[str], int, bool, str]] = []
    for match in MARKER_RE.finditer(body):
        label = visible_html(match.group("label"))
        parsed = MARKER_LABEL_RE.fullmatch(label)
        if parsed:
            found.append((match, int(parsed.group(1)), bool(parsed.group(3)), label))
    return found


def accepted_markers(body: str) -> list[tuple[re.Match[str], int, bool, str]]:
    accepted: list[tuple[re.Match[str], int, bool, str]] = []
    current: int | None = None
    for item in marker_candidates(body):
        _, number, starred, _ = item
        if current is None or (not starred and number > current):
            accepted.append(item)
            current = number
    return accepted


def strip_opening_marker(raw: str, marker: re.Match[str]) -> str:
    rest = raw[marker.end() - marker.start() :]
    rest = re.sub(r"^\s*\.\s*", "", rest, count=1)
    return marker.group("open") + rest


def convert(source_dir: Path) -> tuple[list[dict[str, object]], dict[str, object]]:
    pages: list[dict[str, object]] = []
    primary_by_section: dict[int, tuple[str, str, str]] = {}
    continuations: dict[int, list[tuple[str, str, str]]] = collections.defaultdict(list)
    slug_sections: dict[str, list[int]] = collections.defaultdict(list)
    ignored_pages: list[dict[str, str]] = []
    normalization_stats: collections.Counter[str] = collections.Counter()

    paths = sorted(source_dir.glob("*.html"), key=lambda path: path.name)
    for path in paths:
        title, body = page_parts(path)
        slug = path.stem
        slug_key = unquote(slug)
        accepted = accepted_markers(body)
        pages.append({"slug": slug, "title": title, "markers": [(number, star, label) for _, number, star, label in accepted]})
        if not accepted:
            ignored_pages.append({"slug": slug, "head": title})
            continue
        for index, (match, number, starred, _) in enumerate(accepted):
            end = accepted[index + 1][0].start() if index + 1 < len(accepted) else len(body)
            raw = strip_opening_marker(body[match.start() : end], match)
            item = (slug, title, raw)
            if starred:
                continuations[number].append(item)
            else:
                if number in primary_by_section:
                    raise ValueError(f"duplicate primary section {number}")
                primary_by_section[number] = item
                slug_sections[slug_key].append(number)

    expected = set(range(1, LAST_SECTION + 1))
    if set(primary_by_section) != expected:
        missing = sorted(expected - set(primary_by_section))
        extra = sorted(set(primary_by_section) - expected)
        raise ValueError(f"section coverage mismatch: missing={missing}, extra={extra}")

    records: list[dict[str, object]] = []
    source_rows: list[dict[str, object]] = []
    footnote_markers = 0
    for number in range(1, LAST_SECTION + 1):
        primary = primary_by_section[number]
        fragments = [primary] + continuations.get(number, [])
        roots = [parse_fragment(raw, normalization_stats) for _, _, raw in fragments]
        renderer = Renderer(slug_sections)
        body_html = "".join(renderer.inner(root).strip() for root in roots)
        section_html = f'<section id="s{number}">{body_html}</section>'
        refs: list[str] = []
        for target in renderer.ref_uses:
            target_id = f"monro:{target}"
            if target_id not in refs:
                refs.append(target_id)
        examples: list[dict[str, str]] = []
        for root in roots:
            for example in extract_examples(root):
                if example not in examples:
                    examples.append(example)
        plain = norm(clean_text(plain_from_html(section_html)))
        footnote_markers += plain.count("[fn]")
        slug, head, _ = primary
        records.append(
            {
                "work": "monro",
                "n": number,
                "id": f"monro:{number}",
                "letters": [],
                "notes": [],
                "path": [head],
                "head": head,
                "html": section_html,
                "plain": plain,
                "examples": examples,
                "refs": refs,
                "refRanges": renderer.ranges,
                "citedBy": [],
                "prev": f"monro:{number - 1}" if number > 1 else None,
                "next": f"monro:{number + 1}" if number < LAST_SECTION else None,
            }
        )
        source_rows.append(
            {
                "n": number,
                "slug": slug,
                "continuationSlugs": [item[0] for item in continuations.get(number, [])],
            }
        )

    by_id = {record["id"]: record for record in records}
    unresolved: list[dict[str, object]] = []
    for record in records:
        for target_id in record["refs"]:
            target = by_id.get(target_id)
            if target is None:
                unresolved.append({"section": record["n"], "target": target_id})
            elif record["id"] not in target["citedBy"]:
                target["citedBy"].append(record["id"])

    continuation_rows = [
        {"n": number, "slug": slug, "head": head}
        for number in sorted(continuations)
        for slug, head, _ in continuations[number]
    ]
    meta: dict[str, object] = {
        "work": "monro",
        "title": "A Grammar of the Homeric Dialect",
        "author": "D. B. Monro",
        "source": "grammar-monro/src/dcc/",
        "license": "CC BY-SA 4.0",
        "attribution": "Text: Dickinson College Commentaries edition (CC BY-SA 4.0)",
        "sectionSources": source_rows,
        "counts": {
            "sourcePages": len(paths),
            "sections": len(records),
            "primarySectionMarkers": len(primary_by_section),
            "crossPageContinuations": len(continuation_rows),
            "sectionCrossRefUses": sum(len(Renderer(slug_sections).ref_uses) for _ in []),
            "uniqueRefEdges": sum(len(record["refs"]) for record in records),
            "crossRefRanges": sum(len(record["refRanges"]) for record in records),
            "examples": sum(len(record["examples"]) for record in records),
            "footnoteMarkersRetained": footnote_markers,
        },
        "extraction": {
            "sectionSplit": "leading strong/bold numeric paragraph labels; rising labels start sections; starred first labels append cross-page continuations",
            "examplePattern": "indented paragraphs whose text begins with Il. or Od. book.line; Greek text before the first emphasized gloss",
            "crossPageContinuations": continuation_rows,
            "ignoredUnnumberedPages": ignored_pages,
            "sourceTextNormalization": {
                "policy": "retain precomposed Latin quantity vowels in Latin-script words; map them to marked Greek vowels only in Greek-script context",
                "latinQuantityContextDecisions": {
                    "greekContextTokens": normalization_stats["greekContextTokens"],
                    "latinContextTokens": normalization_stats["latinContextTokens"],
                    "greekContextCharacters": normalization_stats["greekContextCharacters"],
                    "latinContextCharacters": normalization_stats["latinContextCharacters"],
                },
                "retainedLatinWordQuantity": {
                    "tokens": normalization_stats["retainedLatinWordTokens"],
                    "characters": normalization_stats["retainedLatinWordCharacters"],
                },
                "mixedScriptTokens": normalization_stats["mixedScriptTokens"],
            },
            "unresolvedRefs": unresolved,
        },
    }
    # Count link uses after rendering without adding a non-canonical record field.
    meta["counts"]["sectionCrossRefUses"] = sum(
        str(record["html"]).count('<a data-ref="') for record in records
    )
    return records, meta


def json_line(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def write_outputs(records: list[dict[str, object]], meta: dict[str, object], sections: Path, meta_path: Path) -> None:
    sections.parent.mkdir(parents=True, exist_ok=True)
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    sections.write_bytes(("\n".join(json_line(record) for record in records) + "\n").encode("utf-8"))
    meta_path.write_bytes((json.dumps(meta, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


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
        f"wrote {counts['sections']} sections from {counts['sourcePages']} pages; "
        f"{counts['uniqueRefEdges']} ref edges; {counts['examples']} examples; "
        f"{counts['crossPageContinuations']} cross-page continuations"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
