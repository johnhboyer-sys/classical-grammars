#!/usr/bin/env python3
"""Convert the vendored Bennett New Latin Grammar HTML to canonical JSONL.

The source is one XHTML file per printed part plus a supplement.  Each section
opens with ``<p><b><a name="sectN">N</a>.</b> ...``; the anchor names run 1-375
without a gap, plus the inserted ``222A`` (Ablative of Association).  Footnotes
live in footnotes.htm, anchored ``Nt_N`` and referenced inline as ``NtA_N``;
each referenced footnote is attached to its section as a note record.  Heading
context (h2/h3/h4 and centered paragraphs) becomes the section path, never body
text.  The converter performs no network access and no editorial repair.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import unicodedata
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterator


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "grammar-bennett"
DEFAULT_SECTIONS = ROOT / "data" / "bennett" / "sections.jsonl"
DEFAULT_META = ROOT / "data" / "bennett" / "meta.json"
LAST_SECTION = 375
# The printed order of the source: the six parts, then the supplement.
SECTION_FILES = ("part1.htm", "part2.htm", "part3.htm", "part4.htm", "part5.htm", "part6.htm", "supplement.htm")
FRONT_MATTER_FILES = ("preface.htm", "intro.htm")
MARKER_RE = re.compile(r"^sect(\d+[A-Z]?)$")
SECT_HREF_RE = re.compile(r"#sect(\d+[A-Z]?)$")
NOTE_HREF_RE = re.compile(r"^footnotes\.htm#Nt_(\d+)$")
NOTE_ANCHOR_RE = re.compile(r"^NtA_(\d+)$")
RANGE_TAIL_RE = re.compile(r"^\s*[-–—]\s*(\d{1,3})\b")
HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "wbr"}


def norm(value: str | None) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", value or "")).strip()


def json_line(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def section_sort_key(label: str) -> tuple[int, str]:
    match = re.fullmatch(r"(\d+)([A-Z]?)", label)
    assert match is not None
    return int(match.group(1)), match.group(2)


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
        if len(self.stack) > 1 and self.stack[-1].tag == tag:
            self.stack.pop()

    def handle_data(self, data: str) -> None:
        self.stack[-1].add(data)


def parse_file(path: Path) -> Node:
    parser = TreeBuilder()
    # The files declare iso-8859-1; every non-ASCII character arrives as a
    # numeric entity, which convert_charrefs resolves to precomposed macrons.
    parser.feed(path.read_text(encoding="iso-8859-1"))
    parser.close()
    return parser.root


def descendants(node: Node) -> Iterator[Node]:
    for child in node.children:
        if isinstance(child, Node):
            yield child
            yield from descendants(child)


def find_body(root: Node) -> Node:
    for node in descendants(root):
        if node.tag == "body":
            return node
    raise ValueError("no body element found")


def page_title(root: Node) -> str:
    for node in descendants(root):
        if node.tag == "title":
            return norm("".join(child for child in node.children if isinstance(child, str)))
    return ""


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


def heading_text(node: Node) -> str:
    """A heading's text without its footnote marker (the bracketed sup)."""
    return text_of(node, skip={"sup"})


def is_heading(node: Node) -> bool:
    return node.tag in HEADING_TAGS or (node.tag == "p" and "center" in node.attr_words("class"))


def is_content_center(node: Node) -> bool:
    """A centered paragraph holding an image or verse is body, not a heading."""
    if node.tag != "p":
        return False
    if any(child.tag == "img" for child in descendants(node)):
        return True
    return not text_of(node)


def marker_in(block: Node) -> tuple[str, Node] | None:
    for node in descendants(block):
        if node.tag == "a":
            match = MARKER_RE.fullmatch(node.attrs.get("name", ""))
            if match:
                return match.group(1), node
    return None


def remove_marker(block: Node, marker: Node) -> Node:
    """Clone the block with the marker's printed number and its period gone."""
    in_marker = False
    after_marker = False
    def clone(value: Node | str) -> Node | str:
        nonlocal in_marker, after_marker
        if isinstance(value, str):
            if in_marker:
                return ""
            if after_marker:
                after_marker = False
                return re.sub(r"^\s*\.", "", value, count=1)
            return value
        was_marker = value is marker
        if was_marker:
            in_marker = True
        copied = Node(value.tag, list(value.attrs.items()))
        for child in value.children:
            copied.add(clone(child))
        if was_marker:
            in_marker = False
            after_marker = True
        return copied
    result = clone(block)
    assert isinstance(result, Node)
    return result


def safe_class(node: Node) -> str:
    values = [value for value in node.attrs.get("class", "").split() if re.fullmatch(r"[A-Za-z0-9_-]+", value)]
    return " ".join(values)


def sect_target(node: Node) -> str | None:
    match = SECT_HREF_RE.search(node.attrs.get("href", ""))
    return match.group(1) if match else None


def note_target(node: Node) -> int | None:
    match = NOTE_HREF_RE.fullmatch(node.attrs.get("href", ""))
    if match:
        return int(match.group(1))
    # A bare NtA anchor without an href still marks a footnote reference.
    anchor = NOTE_ANCHOR_RE.fullmatch(node.attrs.get("name", ""))
    return int(anchor.group(1)) if anchor else None


def render(node: Node | str) -> str:
    if isinstance(node, str):
        return html.escape(unicodedata.normalize("NFC", node), quote=False)
    inner = "".join(render(child) for child in node.children)
    tag = node.tag
    if tag in {"script", "style", "meta", "iframe", "form", "input", "link"}:
        return ""
    if tag == "img":
        src = node.attrs.get("src", "")
        alt = norm(node.attrs.get("alt", ""))
        if re.fullmatch(r"[A-Za-z0-9._-]+\.png", src):
            return f'<img src="{src}" alt="{html.escape(alt, quote=True)}">'
        return f'<span class="image-alt">[Image: {html.escape(alt, quote=False)}]</span>' if alt else ""
    if tag == "br":
        return "<br>"
    if tag == "hr":
        return "<hr>"
    if tag == "a":
        target = sect_target(node)
        if target is not None:
            return f'<a data-ref="bennett:{target}">{inner.strip()}</a>'
        note = note_target(node)
        if note is not None:
            label = text_of(node) or f"[{note}]"
            return f'<sup class="footnote-ref" data-note="fn{note}">{html.escape(label, quote=False)}</sup>'
        return inner
    if tag == "sup":
        # A sup inside a footnote reference is already rendered by its anchor.
        return inner if node.parent is not None and node.parent.tag == "a" else f"<sup>{inner}</sup>"
    if tag in {"em", "i"}:
        return f"<em>{inner}</em>" if inner.strip() else inner
    if tag in {"strong", "b"}:
        # A marker bold is empty once its number is removed; drop the shell.
        return f"<strong>{inner}</strong>" if inner.strip() else inner
    if tag == "u":
        return f"<u>{inner}</u>"
    if tag == "font":
        css = safe_class(node)
        return f'<span class="{css}">{inner}</span>' if css else inner
    if tag == "span":
        css = safe_class(node)
        return f'<span class="{css}">{inner}</span>' if css else f"<span>{inner}</span>"
    if tag in {"p", "blockquote", "div"}:
        css = safe_class(node)
        attr = f' class="{css}"' if css else ""
        return inner if tag == "div" and not css else f"<{tag}{attr}>{inner}</{tag}>"
    if tag in {"td", "th"}:
        attrs = ""
        for name in ("colspan", "rowspan"):
            value = node.attrs.get(name, "")
            if value.isdigit() and value != "1":
                attrs += f' {name}="{value}"'
        return f"<{tag}{attrs}>{inner}</{tag}>"
    if tag in {"table", "thead", "tbody", "tfoot", "tr", "ul", "ol", "li", "dl", "dt", "dd", "pre"}:
        return f"<{tag}>{inner}</{tag}>"
    if tag in HEADING_TAGS:
        return f"<{tag}>{inner}</{tag}>"
    return inner


def plain(node: Node) -> str:
    parts: list[str] = []
    def walk(value: Node | str) -> None:
        if isinstance(value, str):
            parts.append(value)
        elif value.tag == "img":
            alt = norm(value.attrs.get("alt", ""))
            if alt:
                parts.append(f" [Image: {alt}] ")
        elif value.tag in {"p", "tr", "td", "li", "blockquote", "pre", "div"}:
            parts.append(" ")
            for child in value.children:
                walk(child)
            parts.append(" ")
        elif value.tag not in {"script", "style", "meta", "iframe", "form", "input"}:
            for child in value.children:
                walk(child)
    walk(node)
    return norm("".join(parts))


def extract_examples(blocks: list[Node]) -> list[dict[str, str]]:
    """Extract the ``<b>Latin</b>, <i>gloss</i>`` pairs Bennett indents."""
    result: list[dict[str, str]] = []
    for block in blocks:
        if block.tag != "blockquote":
            continue
        for paragraph in [node for node in descendants(block) if node.tag == "p"]:
            children = [child for child in paragraph.children if not (isinstance(child, str) and not child.strip())]
            if len(children) < 3:
                continue
            first, second, third = children[0], children[1], children[2]
            if (
                isinstance(first, Node) and first.tag == "b"
                and isinstance(second, str) and second.strip().startswith(",")
                and isinstance(third, Node) and third.tag == "i"
            ):
                item = {"la": text_of(first), "gloss": text_of(third), "cite": ""}
                if item["la"] and item["gloss"] and item not in result:
                    result.append(item)
    return result


def refs_of(blocks: list[Node]) -> tuple[list[str], list[dict[str, int]]]:
    refs: list[str] = []
    ranges: list[dict[str, int]] = []
    for block in blocks:
        for parent in [block, *descendants(block)]:
            children = parent.children
            for index, child in enumerate(children):
                if not isinstance(child, Node) or child.tag != "a":
                    continue
                target = sect_target(child)
                if target is None:
                    continue
                if f"bennett:{target}" not in refs:
                    refs.append(f"bennett:{target}")
                # A printed range hyperlinks only its start: ``166</a>-169.``
                tail = children[index + 1] if index + 1 < len(children) else ""
                if target.isdigit() and isinstance(tail, str):
                    match = RANGE_TAIL_RE.match(tail)
                    if match and int(match.group(1)) > int(target):
                        value = {"start": int(target), "end": int(match.group(1))}
                        if value not in ranges:
                            ranges.append(value)
    return refs, ranges


def note_refs_in(nodes: list[Node]) -> list[int]:
    found: list[int] = []
    for node in nodes:
        for item in [node, *descendants(node)]:
            if item.tag == "a":
                number = note_target(item)
                if number is not None and number not in found:
                    found.append(number)
    return found


def parse_footnotes(path: Path) -> dict[int, Node]:
    """Map footnote numbers to their paragraphs, backref anchor removed."""
    notes: dict[int, Node] = {}
    for node in descendants(find_body(parse_file(path))):
        if node.tag != "p":
            continue
        anchor = next((child for child in node.children if isinstance(child, Node) and child.tag == "a" and re.fullmatch(r"Nt_\d+", child.attrs.get("name", ""))), None)
        if anchor is None:
            continue
        number = int(anchor.attrs["name"].split("_")[1])
        stripped = Node(node.tag, list(node.attrs.items()))
        for child in node.children:
            if child is not anchor:
                stripped.add(child)
        notes[number] = stripped
    return notes


def convert(source_dir: Path) -> tuple[list[dict[str, object]], dict[str, object]]:
    footnote_nodes = parse_footnotes(source_dir / "footnotes.htm")
    records: list[dict[str, object]] = []
    marker_audit: list[dict[str, object]] = []
    markers_not_at_start: list[dict[str, object]] = []
    heading_footnotes: list[dict[str, object]] = []
    centered_blocks_kept_inline: list[str] = []
    attached_notes: dict[str, list[int]] = {}
    order: list[str] = []
    payloads: dict[str, list[Node]] = {}
    paths: dict[str, list[str]] = {}
    source_files: dict[str, str] = {}

    for file_name in SECTION_FILES:
        body = find_body(parse_file(source_dir / file_name))
        part: list[str] = []
        subtitle_expected = False
        chapter: str | None = None
        center_head: str | None = None
        sub_head: str | None = None
        current: str | None = None
        buffer: list[Node] = []

        def update_slots(node: Node, text: str) -> None:
            nonlocal part, subtitle_expected, chapter, center_head, sub_head
            if node.tag in {"h1", "h2"}:
                part = [text]
                subtitle_expected = True
                chapter = None
                center_head = None
                sub_head = None
            elif node.tag == "h3":
                if subtitle_expected:
                    part.append(text)
                    subtitle_expected = False
                else:
                    chapter = text
                center_head = None
                sub_head = None
            elif node.tag == "p":
                center_head = text
                sub_head = None
            else:
                sub_head = text

        def flush_as_headings(number: str) -> None:
            for node in buffer:
                if node.tag == "p" and is_content_center(node):
                    # An image or verse line printed just before the next
                    # marker still belongs to the section above it.
                    if current is not None:
                        payloads[current].append(node)
                    continue
                text = heading_text(node)
                for note in note_refs_in([node]):
                    attached_notes.setdefault(number, []).append(note)
                    heading_footnotes.append({"n": number, "footnote": note, "heading": text})
                if text:
                    update_slots(node, text)
            buffer.clear()

        def flush_into_payload() -> None:
            # Headings followed by more body text instead of a marker are
            # printed inside the running section: keep them in its body, but
            # still let them steer the path of the sections that follow.
            for node in buffer:
                if current is None:
                    continue
                centered_blocks_kept_inline.append(current)
                payloads[current].append(node)
                text = heading_text(node)
                if text and not (node.tag == "p" and is_content_center(node)):
                    update_slots(node, text)
            buffer.clear()

        for block in body.children:
            if not isinstance(block, Node) or block.tag in {"br", "hr"}:
                continue
            if is_heading(block):
                buffer.append(block)
                continue
            marker = marker_in(block)
            if marker is not None:
                number, anchor = marker
                label = text_of(anchor)
                block_text = text_of(block)
                marker_audit.append({"n": number, "sourceFile": file_name, "label": label})
                if not block_text.startswith(number):
                    markers_not_at_start.append({"n": number, "sourceFile": file_name, "blockStart": block_text[:60]})
                flush_as_headings(number)
                current = number
                order.append(number)
                source_files[number] = file_name
                paths[number] = [head for head in [*part, chapter, center_head, sub_head] if head]
                payloads[number] = [remove_marker(block, anchor)]
            elif current is not None:
                if buffer:
                    flush_into_payload()
                payloads[current].append(block)
        if buffer:
            flush_into_payload()

    assert order == sorted(order, key=section_sort_key)
    # The source prints section 7's marker with a doubled period ("7.. 1.");
    # whatever punctuation survives the marker removal is reported, not fixed.
    marker_residue = [
        {"n": number, "residue": plain(payloads[number][0])[:40]}
        for number in order
        if plain(payloads[number][0]).startswith((".", ",", ";"))
    ]
    footnote_occurrences = 0
    for number in order:
        blocks = payloads[number]
        for note in note_refs_in(blocks):
            footnote_occurrences += 1
            if note not in attached_notes.setdefault(number, []):
                attached_notes[number].append(note)
        note_records = [
            {
                "anchor": f"fn{note}",
                "label": str(note),
                "kind": "footnote",
                "html": "".join(render(child) for child in footnote_nodes[note].children).strip(),
                "plain": plain(footnote_nodes[note]),
            }
            for note in attached_notes.get(number, [])
            if note in footnote_nodes
        ]
        refs, ranges = refs_of(blocks)
        for note in attached_notes.get(number, []):
            if note in footnote_nodes:
                for target in refs_of([footnote_nodes[note]])[0]:
                    if target not in refs:
                        refs.append(target)
        body_html = "".join(render(block) for block in blocks)
        path_value = paths[number]
        n_value: int | str = int(number) if number.isdigit() else number
        records.append(
            {
                "work": "bennett",
                "n": n_value,
                "id": f"bennett:{number}",
                "letters": [],
                "notes": note_records,
                "path": path_value,
                "head": path_value[-1] if path_value else f"Bennett section {number}",
                "html": f'<section id="s{number}">{body_html}</section>',
                "plain": norm(" ".join(plain(block) for block in blocks)),
                "examples": extract_examples(blocks),
                "refs": refs,
                "refRanges": ranges,
                "citedBy": [],
                "prev": None,
                "next": None,
            }
        )

    by_id = {str(record["id"]): record for record in records}
    for index, record in enumerate(records):
        record["prev"] = records[index - 1]["id"] if index else None
        record["next"] = records[index + 1]["id"] if index + 1 < len(records) else None
        for target in record["refs"]:
            if target in by_id:
                by_id[target]["citedBy"].append(record["id"])
    unresolved = [
        {"n": record["n"], "target": target}
        for record in records
        for target in record["refs"]
        if target not in by_id
    ]

    # Front matter inventory: the introduction and preface carry no section
    # markers, so they stay out of the records and are described here.
    front_matter: list[dict[str, object]] = []
    for file_name in FRONT_MATTER_FILES:
        root = parse_file(source_dir / file_name)
        body = find_body(root)
        blocks = [child for child in body.children if isinstance(child, Node)]
        front_matter.append(
            {
                "file": file_name,
                "title": page_title(root),
                "blocks": len(blocks),
                "characters": sum(len(text_of(block)) for block in blocks),
                "footnoteRefs": note_refs_in(blocks),
            }
        )

    # The table of contents is navigation, not text: check that every section
    # link in it resolves, and keep only the tally.
    toc_body = find_body(parse_file(source_dir / "toc.htm"))
    toc_targets = [target for target in (sect_target(node) for node in descendants(toc_body) if node.tag == "a") if target is not None]
    toc_unresolved = sorted({target for target in toc_targets if f"bennett:{target}" not in by_id})

    attached = sorted({note for notes in attached_notes.values() for note in notes})
    front_notes = sorted({note for item in front_matter for note in item["footnoteRefs"]})
    orphan_notes = [note for note in sorted(footnote_nodes) if note not in attached and note not in front_notes]

    meta: dict[str, object] = {
        "work": "bennett",
        "title": "New Latin Grammar",
        "author": "Charles E. Bennett",
        "source": "grammar-bennett/",
        "license": "CC BY-NC-SA 3.0 US",
        "attribution": "New Latin Grammar, Charles E. Bennett (see grammar-bennett/README.md)",
        "counts": {
            "sectionFiles": len(SECTION_FILES),
            "sections": len(records),
            "sectionMarkers": len(marker_audit),
            "tables": sum(str(record["html"]).count("<table>") for record in records),
            "images": sum(str(record["html"]).count("<img ") for record in records),
            "footnotesInSource": len(footnote_nodes),
            "footnotesAttached": len(attached),
            "sectionFootnoteRefs": footnote_occurrences,
            "examples": sum(len(record["examples"]) for record in records),
            "sectionCrossRefs": sum(len(record["refs"]) for record in records),
            "crossRefRanges": sum(len(record["refRanges"]) for record in records),
            "tocSectionLinks": len(toc_targets),
        },
        "anomalies": {
            "markerAudit": marker_audit,
            "markersNotAtBlockStart": markers_not_at_start,
            "markerResidue": marker_residue,
            "letteredSections": [
                {
                    "n": "222A",
                    "note": "printed insert between 222 and 223 (Ablative of Association); its n field is the string \"222A\" where every other n is an integer",
                }
            ],
            "missingSections": [number for number in range(1, LAST_SECTION + 1) if f"bennett:{number}" not in by_id],
            "unresolvedRefs": unresolved,
            "tocUnresolvedTargets": toc_unresolved,
            "headingFootnotes": heading_footnotes,
            "centeredBlocksKeptInline": sorted(set(centered_blocks_kept_inline), key=section_sort_key),
            "footnotesOutsideSections": {
                "frontMatter": front_notes,
                "backMatter": orphan_notes,
                "note": "notes 1-3 belong to the introduction; note 63 is cited only from the index of sources",
            },
            "defectiveFootnoteBackrefs": [
                {"note": 10, "href": "part1.htmpart2.htm#NtA_10", "issue": "backref href glues two file names together"},
                {"note": 63, "href": "#NtA_63", "issue": "backref points into footnotes.htm but the anchor is in index.htm"},
            ],
            "frontMatter": front_matter,
            "index": {
                "present": True,
                "converted": False,
                "note": "index.htm (sources of examples, index of subjects) is navigation back matter and is not converted to sections",
            },
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
    counts = meta["counts"]
    print(
        f"converted {counts['sections']} sections with {counts['tables']} tables, "
        f"{counts['footnotesAttached']} footnotes, and {counts['examples']} examples"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
