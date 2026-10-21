#!/usr/bin/env python3
"""Build data/smyth/constructions.json from the AGDT 2.x annotation guidelines.

Source: PerseusDL/treebank_data, AGDT2/guidelines/Greek_guidelines_2.5.md
        (Celano 2014, CC BY-SA 3.0 US). See SPEC-constructions.md.

Stdlib only. Deterministic: same input bytes -> same output bytes.
"""

import html.parser
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(REPO, "grammar-agdt", "AGDT2", "guidelines",
                      "Greek_guidelines_2.5.md")
SECTIONS = os.path.join(REPO, "data", "smyth", "sections.jsonl")
OUT = os.path.join(REPO, "data", "smyth", "constructions.json")

SOURCE_LABEL = "AGDT2/guidelines/Greek_guidelines_2.5.md"

# The only Smyth link family in the guidelines: a Perseus hopper URL whose
# `doc` parameter carries the section number. Two hand-typo variants occur
# (`Smyfth`, `perseus.txufts.edu`); both are still parseable, so they are
# mapped and reported rather than dropped.
SMYTH_HREF = re.compile(r"doc=Smy\w*\+grammar\+(\d+)")
CANONICAL_HREF = re.compile(
    r"^https?://www\.perseus\.tufts\.edu/hopper/text"
    r"\?doc=Smyth\+grammar\+\d+&fromdoc=Perseus%3Atext%3A1999\.04\.0007$")

HEADINGS = ("h1", "h2", "h3", "h4", "h5", "h6")
VOID = {"br", "hr", "img", "meta", "link", "input", "col", "area", "base"}
DASH = re.compile(r"^[\s–—-]*[–—-][\s–—-]*$")
# link text is normally the bare section number; once it is "2112b", i.e. a
# lettered subsection (Smyth §2112 b) -> anchor "b"
NUM_TEXT = re.compile(r"^(\d+)\s*([a-z])?$")
NUMBERED = re.compile(r"^\s*(\d+(?:\.\d+)*)\.?\s+(.*)$", re.S)
PAREN = re.compile(r"\s*\(([^()]*)\)")
# `tree1`/`tree2` are links to Arethusa sample trees, not part of any name
CITE_RESIDUE = re.compile(r"\b(?:SG|noun|verb|see|also|and|or|tree\d*)\b"
                          r"|[\d\s,;:.–—-]")
TRAILING_CITE = re.compile(r"\s*[;,]?\s*SG\s*[\d\s,;–—-]*$")


class Node:
    __slots__ = ("tag", "attrs", "children", "line")

    def __init__(self, tag, attrs=None, line=0):
        self.tag = tag
        self.attrs = attrs or {}
        self.children = []
        self.line = line


class TreeBuilder(html.parser.HTMLParser):
    """Forgiving tree builder: unmatched end tags are ignored, unclosed tags
    stay open. The guidelines use `<a id=...>` anchors that wrap whole
    sections without closing in place, so strict parsing is not an option."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root")
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, dict(attrs), self.getpos()[0])
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(Node(tag, dict(attrs), self.getpos()[0]))

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def text_of(node, skip_lists=False):
    """All descendant text. With skip_lists, nested <ul>/<ol> are omitted so a
    list item yields its own label rather than its whole subtree."""
    out = []
    stack = [node]
    while stack:
        cur = stack.pop()
        if isinstance(cur, str):
            out.append(cur)
            continue
        if skip_lists and cur is not node and cur.tag in ("ul", "ol"):
            continue
        stack.extend(reversed(cur.children))
    return "".join(out)


def norm(s):
    return re.sub(r"\s+", " ", s.replace("\xa0", " ")).strip()


def strip_citations(s):
    """Drop parentheticals that are nothing but SG citation apparatus.
    `(SG 1297-1305)` and `(noun: SG 1306-1319; verb: SG 1341-1371)` go;
    `(with ἀπό, διά, ἐξ)` stays."""

    def repl(m):
        return "" if CITE_RESIDUE.sub("", m.group(1)) == "" else m.group(0)

    prev = None
    while prev != s:
        prev = s
        s = PAREN.sub(repl, s)
    s = TRAILING_CITE.sub("", s)
    return s


def clean_name(raw):
    s = strip_citations(norm(raw))
    s = norm(s).strip(" .,;:–—-")
    return norm(s)


def split_heading(raw):
    """'4.1.1.2.2 Genitive of measure' -> ('4.1.1.2.2', 'Genitive of measure')"""
    t = norm(raw)
    m = NUMBERED.match(t)
    if m:
        return m.group(1), norm(m.group(2))
    return None, t


def is_smyth_link(node):
    if isinstance(node, str) or node.tag != "a":
        return None
    href = node.attrs.get("href", "")
    m = SMYTH_HREF.search(href)
    return m if m else None


def collect(root):
    """Document-order walk. Returns (links, headings_seen).

    Each link: dict with n, to, href, line, and the ancestor chain.
    """
    links = []
    heading_titles = {}   # dotted number -> title
    state = {"key": None, "title": None}
    range_ends = set()    # id() of links already consumed as a range end

    def breadcrumb(key, title):
        if key is None:
            return title
        parts = key.split(".")
        crumbs = []
        for i in range(1, len(parts) + 1):
            k = ".".join(parts[:i])
            if k in heading_titles:
                crumbs.append("%s %s" % (k, heading_titles[k]))
        return " > ".join(crumbs) if crumbs else title

    def walk(node, ancestors):
        children = node.children
        for i, child in enumerate(children):
            if isinstance(child, str):
                continue
            if child.tag in HEADINGS:
                key, title = split_heading(text_of(child))
                if title:
                    if key:
                        heading_titles[key] = title
                    state["key"], state["title"] = key, title
                    state["crumb"] = breadcrumb(key, title)
            m = is_smyth_link(child)
            if m:
                to = None
                label = NUM_TEXT.match(norm(text_of(child)))
                anchor = label.group(2) if label else None
                # range: <a>1289</a> – <a>1406</a> as adjacent siblings
                if label:
                    j = i + 1
                    if (j < len(children) and isinstance(children[j], str)
                            and DASH.fullmatch(children[j])):
                        nxt = children[j + 1] if j + 1 < len(children) else None
                        m2 = is_smyth_link(nxt) if nxt is not None else None
                        if m2 and NUM_TEXT.match(norm(text_of(nxt))):
                            to = int(m2.group(1))
                            range_ends.add(id(nxt))
                links.append({
                    "n": int(m.group(1)),
                    "to": to,
                    "anchor": anchor,
                    "isRangeEnd": id(child) in range_ends,
                    "href": child.attrs.get("href", ""),
                    "line": child.line,
                    "ancestors": ancestors + [node, child],
                    "headingKey": state["key"],
                    "headingTitle": state["title"],
                    "headingCrumb": state.get("crumb", state["title"]),
                })
            walk(child, ancestors + [node])

    walk(root, [])
    return links


def context_for(link):
    """Resolve construction name, context path and kind from the ancestor chain."""
    chain = link["ancestors"]
    li_chain = [n for n in chain if not isinstance(n, str) and n.tag == "li"]
    if li_chain:
        labels = [clean_name(text_of(li, skip_lists=True)) for li in li_chain]
        labels = [l for l in labels if l]
        name = labels[-1] if labels else ""
        head = link["headingTitle"] or ""
        path = ([head] if head and head.lower() != labels[0].lower() else []) + labels
        return name, " > ".join(path), "list-item"

    td = None
    tr = None
    for n in chain:
        if isinstance(n, str):
            continue
        if n.tag == "td" or n.tag == "th":
            td = n
        if n.tag == "tr":
            tr = n
    if td is not None and tr is not None:
        cells = [c for c in tr.children
                 if not isinstance(c, str) and c.tag in ("td", "th")]
        name = clean_name(text_of(cells[0])) if cells else ""
        # The guidelines contain exactly one table; its caption reads
        # "1. Table for semantic roles in AG" (source L1013).
        return name, "1. Table for semantic roles in AG", "table-row"

    for n in reversed(chain):
        if not isinstance(n, str) and n.tag in HEADINGS:
            _, title = split_heading(text_of(n))
            return clean_name(title), link["headingCrumb"] or title, "heading"

    return (clean_name(link["headingTitle"] or ""),
            link["headingCrumb"] or link["headingTitle"] or "", "prose")


def href_form(href):
    """Normalize a link to its shape, masking only the section number."""
    return SMYTH_HREF.sub(lambda m: m.group(0).replace(m.group(1), "NNNN"), href)


def main():
    with open(SOURCE, encoding="utf-8") as fh:
        raw = fh.read()

    valid = set()
    with open(SECTIONS, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                valid.add(json.loads(line)["n"])

    parser = TreeBuilder()
    parser.feed(raw)
    parser.close()
    links = collect(parser.root)

    forms = {}
    malformed = []
    unmappable = []
    unnamed = []
    entries = {}

    for link in links:
        forms[href_form(link["href"])] = forms.get(href_form(link["href"]), 0) + 1
        if not CANONICAL_HREF.match(link["href"]):
            malformed.append({"line": link["line"], "href": link["href"],
                              "section": link["n"],
                              "note": "typo in source URL; section number recovered"})
        bad = [x for x in [link["n"], link["to"]] if x is not None and x not in valid]
        if bad:
            unmappable.append({"line": link["line"], "href": link["href"],
                               "sections": bad,
                               "note": "no such section in sections.jsonl"})
            continue

        name, path, kind = context_for(link)
        if not name:
            unnamed.append({"line": link["line"], "section": link["n"],
                            "headingCrumb": link["headingCrumb"],
                            "note": "no construction name recoverable from context"})
            continue

        key = (name, path, kind, link["headingCrumb"] or "")
        entry = entries.setdefault(key, set())
        # the right-hand link of "1297–1305" is the range's end, not a
        # separate citation; the range already records it
        if not link["isRangeEnd"]:
            entry.add((link["n"], link["to"], link["anchor"]))

    out_entries = []
    empty = []
    for (name, path, kind, crumb), secs in entries.items():
        if not secs:
            empty.append({"construction": name, "agdtContext": path,
                          "note": "context held only range-end links"})
            continue
        sections = []
        for n, to, anchor in sorted(secs, key=lambda p: (
                p[0], -1 if p[1] is None else p[1], p[2] or "")):
            sec = {"n": n}
            if anchor is not None:
                sec["anchor"] = anchor
            if to is not None:
                sec["to"] = to
            sections.append(sec)
        out_entries.append({
            "construction": name,
            "agdtContext": path,
            "contextKind": kind,
            "sections": sections,
            "sourceFile": SOURCE_LABEL,
            "sourceHeading": crumb,
        })
    out_entries.sort(key=lambda e: (e["construction"].lower(), e["agdtContext"],
                                    e["contextKind"], e["sourceHeading"]))

    linked = {l["n"] for l in links} | {l["to"] for l in links if l["to"]}
    expanded = set()
    for l in links:
        if l["to"] is not None and l["to"] >= l["n"]:
            expanded.update(range(l["n"], l["to"] + 1))
        else:
            expanded.add(l["n"])

    doc = {
        "meta": {
            "source": {
                "repository": "https://github.com/PerseusDL/treebank_data",
                "commit": "bf4334f0af5e13d16b04c1cccd6237e683ac6f5f",
                "file": SOURCE_LABEL,
                "title": "Guidelines for the annotation of the Ancient Greek "
                         "Dependency Treebank 2.0",
                "author": "Giuseppe G. A. Celano",
                "year": 2014,
                "license": "CC BY-SA 3.0 US",
                "copyright": "Copyright 2014 The Perseus Digital Library, "
                             "Tufts University",
            },
            "target": {"work": "smyth",
                       "edition": "Smyth, Greek Grammar for Colleges (1920)"},
            "counts": {
                "totalLinks": len(links),
                "rangeCitations": sum(1 for l in links if l["to"] is not None),
                "distinctSectionsLinked": len(linked),
                "distinctSectionsWithRangesExpanded": len(expanded),
                "entries": len(out_entries),
                "entriesByContextKind": {
                    k: sum(1 for e in out_entries if e["contextKind"] == k)
                    for k in sorted({e["contextKind"] for e in out_entries})
                },
            },
            "linkForms": dict(sorted(forms.items())),
            "malformedLinks": sorted(malformed, key=lambda x: x["line"]),
            "unmappableLinks": sorted(unmappable, key=lambda x: x["line"]),
            "unnamedContexts": sorted(unnamed, key=lambda x: x["line"]),
            "emptyContexts": sorted(empty, key=lambda x: (x["construction"],
                                                         x["agdtContext"])),
        },
        "entries": out_entries,
    }

    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")

    print("links=%d entries=%d distinct=%d ranges=%d malformed=%d unnamed=%d"
          % (len(links), len(out_entries), len(linked),
             doc["meta"]["counts"]["rangeCitations"], len(malformed),
             len(unnamed)), file=sys.stderr)


if __name__ == "__main__":
    main()
