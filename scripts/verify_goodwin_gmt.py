#!/usr/bin/env python3
"""Independently verify the Goodwin section JSONL conversion."""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "grammar-goodwin-gmt" / "src" / "goodwin-gmt-dltext.xml"
DEFAULT_SECTIONS = ROOT / "data" / "goodwin-gmt" / "sections.jsonl"
DEFAULT_META = ROOT / "data" / "goodwin-gmt" / "meta.json"
EXPECTED_LICENSE = (
    'Perseus Digital Library, availability status "free": the text may be '
    "freely distributed provided you credit Perseus, leave the availability "
    "statement intact, use it for non-commercial purposes only, and offer "
    "Perseus any modifications you make"
)
EXPECTED_ATTRIBUTION = (
    "Text provided by Perseus Digital Library, with funding from The "
    "National Endowment for the Humanities. Original version available "
    "for viewing and download at http://www.perseus.tufts.edu/hopper/."
)
COUNT = 926
ID_RE = re.compile(r"^goodwin-gmt:(\d+)$")
APP_ID_RE = re.compile(r"^goodwin-gmt:app-(\d+)$")
RESIDUE_RE = re.compile(r"[A-Za-z)(/\\=|+*]")
LATIN_MACRON_RE = re.compile("[āēīōūȳăĕĭŏŭĀĒĪŌŪȲĂĔĬŎŬ]")
ENTITY_RE = re.compile(r"&(?:#\d+|#x[0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]+);")
RAW_TAG_RE = re.compile(r"</?[A-Za-z][^>]*>")
# A shipped example holding two Greek sentences holds two of Goodwin's
# examples, and the record carries only one citation, so one of them is
# published under the other's reference.  Read off the shipped rows, not off
# the converter: the same shape defined there let 13 of these ship.
FUSED_GREEK_RE = re.compile(r"[Ͱ-Ͽἀ-῿]{4}\.\s+[Ͱ-Ͽἀ-῿]")
# Four shipped examples do run to two sentences, and are right to: the source
# puts each inside one ``cit`` with one ``bibl``, so the witness itself says
# the sentences are one quotation of one passage.  Checked in the XML at each
# section named.  (§35's second is a further defect of another kind: an
# English ``note`` inside the Greek quote, transliterated as though it were
# Greek.  That is recorded, not licensed, here.)
FUSED_IN_ONE_CIT = {
    (35, "Thuc. 2. 15"),
    (35, "Dem. 19.189"),
    (97, "Aristot. Nic. Eth. 1173a"),
    (246, "Lys. 12.22"),
}
# Six examples whose ``grc`` differs from the Greek the HTML prints, because
# the source itself is corrupt there and the two readings mangle it in two
# ways.  Each was checked in the XML: §156 "i)a/sat'" (the print reads
# "ιἄσατ̓", the field "ἰάσατ̓"), §189 and §911 twice and §923 carry English
# or a stray parenthesis typed inside a Greek quote ("ἡε σαψς προμισεδ" is
# "he says promised"; "θηναίοις" has lost the alpha of "Ἀθηναίοις"), and
# §329 the same.  Neither reading is Goodwin's, and a witness for the right
# one would have to come from the print, not from here.  Recorded so that a
# seventh divergence fails.
PRINTED_GREEK_CORRUPT = {
    (156, "Eur. Fr. 1057"),
    (189, "Isaeus 11. 24"),
    (329, "Hom. Od. 24.333"),
    (911, "Dem. 4.18"),
    (911, "Eur. Hec. 423"),
    (923, "Thuc. 1.86"),
}


def norm(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


class GreekAudit(HTMLParser):
    """Collect text whose nearest explicit language is Greek."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.stack: list[tuple[str, str | None]] = []
        self.greek: list[str] = []
        self.entities: list[str] = []
        self.errors: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        inherited = self.stack[-1][1] if self.stack else None
        self.stack.append((tag, values.get("lang", inherited)))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        return

    def handle_endtag(self, tag: str) -> None:
        if not self.stack:
            self.errors.append(f"stray </{tag}>")
            return
        opened, _ = self.stack.pop()
        if opened != tag:
            self.errors.append(f"</{tag}> closes <{opened}>")

    def handle_data(self, data: str) -> None:
        if self.stack and self.stack[-1][1] == "grc":
            self.greek.append(data)

    def handle_entityref(self, name: str) -> None:
        if self.stack and self.stack[-1][1] == "grc":
            self.entities.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if self.stack and self.stack[-1][1] == "grc":
            self.entities.append(f"&#{name};")


class PrintedItems(HTMLParser):
    """Flatten a section's HTML into the pieces a reader sees, in print order.

    Four kinds are kept and everything else is running prose: Greek (a
    ``lang="grc"`` span or ``q``), an English gloss (a bare ``q``, a
    ``span class="gloss"``, an ``em`` or a ``strong``), a citation (a
    ``cite``, carrying its ``data-cite``), and the text between them.  The
    Latin speaker labels the renderer marks ``lang="en"`` inside Greek are
    dropped, because the ``grc`` field drops them too.

    Nothing here knows how the converter finds an example.  It reads the
    rendered section, which the renderer builds from the source's own tags
    without ever consulting ``collect_examples``, ``bare_example``,
    ``cit_example`` or ``greek_of``.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[tuple[str, str, str]] = []
        self.stack: list[tuple[str, str | None, list[str], str]] = []

    @staticmethod
    def kind_of(tag: str, attrs: dict[str, str | None]) -> str | None:
        if tag in {"span", "q"} and attrs.get("lang") == "grc":
            return "grc"
        if tag == "q" or (tag == "span" and attrs.get("class") == "gloss"):
            return "gloss"
        if tag in {"em", "strong"}:
            return "gloss"
        if tag == "cite":
            return "cite"
        if tag == "span" and attrs.get("lang") == "en":
            return "drop"
        return None

    def enclosing(self) -> list[str] | None:
        for _, kind, buffer, _ in reversed(self.stack):
            if kind is not None:
                return buffer
        return None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        self.stack.append((tag, self.kind_of(tag, values), [], values.get("data-cite") or ""))

    def handle_endtag(self, tag: str) -> None:
        if not self.stack:
            return
        _, kind, buffer, cite = self.stack.pop()
        if kind in {"grc", "gloss", "cite"}:
            outer = self.enclosing()
            if outer is None:
                self.items.append((kind, norm("".join(buffer)), cite))
            else:
                outer.append("".join(buffer))

    def handle_data(self, data: str) -> None:
        outer = self.enclosing()
        if outer is None:
            self.items.append(("text", data, ""))
        else:
            outer.append(data)


def printed_items(html_value: str) -> list[tuple[str, str, str]]:
    parser = PrintedItems()
    parser.feed(html_value)
    parser.close()
    return parser.items


def seat_example(
    items: list[tuple[str, str, str]], start: int, example: dict[str, object]
) -> int | None:
    """Seat one example in the printed items at ``start``, or return None.

    The example is seated when the print sets, in this order and with only
    its own prose between them, the whole of the ``grc`` field as one or
    more Greek runs, the whole of the ``gloss`` field as one or more glosses,
    and the citation whose ``data-cite`` is the ``cite`` field.  The citation
    may stand before the Greek, which is how Goodwin sets it in §13 and §74,
    and the gloss may follow the citation, as in §66.
    """
    grc = norm(str(example.get("grc", "")))
    gloss = norm(str(example.get("gloss", "")))
    cite = norm(str(example.get("cite", "")))
    if items[start][0] != "grc" or not items[start][1] or not grc.startswith(items[start][1]):
        return None
    run = [items[start][1]]
    index = start + 1
    while norm(" ".join(run)) != grc and index < len(items):
        if items[index][0] == "grc":
            run.append(items[index][1])
        elif items[index][0] != "text":
            break
        index += 1
    if norm(" ".join(run)) != grc:
        return None
    before = start - 1
    while before >= 0 and items[before][0] == "text":
        before -= 1
    following = index
    while following < len(items) and items[following][0] != "cite":
        following += 1
    if before >= 0 and items[before][0] == "cite" and norm(items[before][2]) == cite:
        end = index
    elif following < len(items) and norm(items[following][2]) == cite:
        end = following + 1
    else:
        return None
    if gloss:
        window = max(end, following + 1)
        while window < len(items) and items[window][0] in {"text", "gloss"}:
            window += 1
        available = [value for kind, value, _ in items[start:window] if kind == "gloss"]
        if not any(
            norm(" ".join(available[first:last])) == gloss
            for first in range(len(available))
            for last in range(first + 1, len(available) + 1)
        ):
            return None
    return end


def source_apostrophes(path: Path) -> tuple[int, int]:
    root = ET.parse(path).getroot()
    body = root.find("text/body")
    if body is None:
        raise ValueError("source has no body")
    parents = {child: parent for parent in body.iter() for child in parent}
    body_count = 0
    head_count = 0
    for elem in body.iter():
        if elem.tag not in {"foreign", "quote", "note", "gloss"}:
            continue
        if (elem.get("lang") or "").lower() not in {"greek", "grc"}:
            continue
        count = "".join(elem.itertext()).count("'")
        current = parents.get(elem)
        in_head = False
        while current is not None:
            if current.tag == "head":
                in_head = True
                break
            current = parents.get(current)
        if in_head:
            head_count += count
        else:
            body_count += count
    return body_count, head_count


def load(path: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"line {line_number}: invalid JSON: {error}") from error
        if not isinstance(value, dict):
            raise ValueError(f"line {line_number}: record is not an object")
        records.append(value)
    return records


def is_descendant(
    elem: ET.Element, ancestor: ET.Element, parents: dict[ET.Element, ET.Element]
) -> bool:
    current: ET.Element | None = elem
    while current is not None:
        if current is ancestor:
            return True
        current = parents.get(current)
    return False


def source_body_ownership(path: Path) -> tuple[int, int, int, int]:
    """Count direct source blocks and make sure a numbered or appendix unit owns each."""
    root = ET.parse(path).getroot()
    body = root.find("text/body")
    if body is None:
        raise ValueError("source has no body")
    parents = {child: parent for parent in body.iter() for child in parent}
    appendix = next(
        (elem for elem in body if elem.tag == "div1" and elem.get("n") == "appendix"),
        None,
    )
    if appendix is None:
        raise ValueError("source has no appendix div1")
    all_blocks = [
        elem
        for elem in body.iter()
        if elem.tag in {"p", "table", "list", "l"}
        and (parent := parents.get(elem)) is not None
        and parent.tag in {"div1", "div2", "div3"}
    ]
    appendix_blocks: set[ET.Element] = set()
    appendix_parts = 0
    for elem in appendix.iter():
        if elem.tag not in {"div2", "div3"}:
            continue
        owned = [child for child in elem if child.tag in {"p", "table", "list", "l"}]
        if owned:
            appendix_parts += 1
            appendix_blocks.update(owned)

    numbered_blocks: set[ET.Element] = set()
    current: int | None = None
    pre_marker = 0
    for elem in body.iter():
        if elem.tag == "milestone" and elem.get("unit") == "smythp":
            raw = elem.get("n", "")
            current = int(raw) if raw.isdigit() else None
            continue
        if elem not in all_blocks or is_descendant(elem, appendix, parents):
            continue
        if current is None:
            pre_marker += 1
        else:
            numbered_blocks.add(elem)
    owned = numbered_blocks | appendix_blocks
    unowned = len(set(all_blocks) - owned)
    duplicates = len(numbered_blocks & appendix_blocks)
    return len(all_blocks), unowned, duplicates, appendix_parts


def check(condition: bool, title: str, detail: str, failures: list[str]) -> None:
    print(f"[{'PASS' if condition else 'FAIL'}] {title}: {detail}")
    if not condition:
        failures.append(title)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--sections", type=Path, default=DEFAULT_SECTIONS)
    parser.add_argument("--meta", type=Path, default=DEFAULT_META)
    args = parser.parse_args()
    failures: list[str] = []
    try:
        records = load(args.sections)
    except (OSError, ValueError) as error:
        print(f"[FAIL] JSONL load: {error}")
        return 1
    try:
        meta = json.loads(args.meta.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        print(f"[FAIL] meta load: {error}")
        return 1

    sections = records[:COUNT]
    appendices = records[COUNT:]
    numbers = [record.get("n") for record in sections]
    ids = [record.get("id") for record in sections]
    contiguous = numbers == list(range(1, COUNT + 1))
    valid_ids = all(
        isinstance(value, str)
        and (match := ID_RE.fullmatch(value))
        and int(match.group(1)) == number
        for value, number in zip(ids, numbers)
    )
    check(
        len(sections) == COUNT and contiguous and len(set(ids)) == COUNT and valid_ids,
        "section identity",
        f"{len(sections)} numbered records; contiguous 1-{COUNT}; duplicate IDs {len(ids) - len(set(ids))}",
        failures,
    )

    appendix_ids = [record.get("id") for record in appendices]
    appendix_expected = [f"goodwin-gmt:app-{index}" for index in range(1, len(appendices) + 1)]
    appendix_nonempty = all(isinstance(record.get("plain"), str) and norm(record["plain"]) for record in appendices)
    appendix_links = all(
        record.get("prev") == (f"goodwin-gmt:{COUNT}" if index == 1 else f"goodwin-gmt:app-{index - 1}")
        and record.get("next") == (f"goodwin-gmt:app-{index + 1}" if index < len(appendices) else None)
        for index, record in enumerate(appendices, 1)
    )
    check(
        bool(appendices)
        and appendix_ids == appendix_expected
        and all(isinstance(value, str) and APP_ID_RE.fullmatch(value) for value in appendix_ids)
        and appendix_nonempty
        and appendix_links
        and sections[-1].get("next") == "goodwin-gmt:app-1",
        "appendix identity and navigation",
        f"{len(appendices)} contiguous nonempty appendix records; links {'valid' if appendix_links else 'invalid'}",
        failures,
    )

    counts = meta.get("counts", {}) if isinstance(meta.get("counts"), dict) else {}
    identity_ok = (
        meta.get("work") == "goodwin-gmt"
        and meta.get("title") == "Syntax of the Moods and Tenses of the Greek Verb"
        and meta.get("author") == "William Watson Goodwin"
        and meta.get("license") == EXPECTED_LICENSE
        and meta.get("attribution") == EXPECTED_ATTRIBUTION
    )
    recomputed = {
        "sections": COUNT,
        "appendixRecords": len(appendices),
        "uniqueRefEdges": sum(
            len(record.get("refs", [])) for record in records if isinstance(record.get("refs"), list)
        ),
        "examples": sum(
            len(record.get("examples", []))
            for record in records
            if isinstance(record.get("examples"), list)
        ),
    }
    count_errors = [
        f"{key}: meta={counts.get(key)} records={value}"
        for key, value in recomputed.items()
        if counts.get(key) != value
    ]
    check(
        identity_ok and not count_errors,
        "metadata",
        f"work/title/author and Perseus license/attribution exact={identity_ok}; "
        f"count mismatches={count_errors or 'none'}",
        failures,
    )

    greek_chunks: list[str] = []
    greek_entities: list[str] = []
    html_errors: list[str] = []
    empty: list[int] = []
    raw_text: list[str] = []
    example_bad: list[int] = []
    example_fused: list[tuple[object, str]] = []
    for record in records:
        number = record.get("n")
        html_value = record.get("html")
        plain = record.get("plain")
        if not isinstance(html_value, str) or not isinstance(plain, str):
            empty.append(int(number) if isinstance(number, int) else -1)
            continue
        audit = GreekAudit()
        audit.feed(html_value)
        audit.close()
        greek_chunks.extend(audit.greek)
        greek_entities.extend(audit.entities)
        html_errors.extend(f"{number}: {error}" for error in audit.errors)
        if not norm(plain):
            empty.append(int(number))
        # Text fields must not contain source markup or unresolved entities.
        for key in ("head", "plain"):
            value = record.get(key, "")
            if isinstance(value, str) and (RAW_TAG_RE.search(value) or ENTITY_RE.search(value)):
                raw_text.append(f"{number}:{key}")
        examples = record.get("examples", [])
        if not isinstance(examples, list):
            example_bad.append(int(number))
        else:
            for example in examples:
                if not isinstance(example, dict) or not isinstance(example.get("grc"), str):
                    example_bad.append(int(number))
                    continue
                grc = example["grc"]
                if RESIDUE_RE.search(grc) or unicodedata.normalize("NFC", grc) != grc:
                    example_bad.append(int(number))
                if FUSED_GREEK_RE.search(grc) and (
                    number,
                    example.get("cite"),
                ) not in FUSED_IN_ONE_CIT:
                    example_fused.append((number, grc[:70]))

    grc_field_entities: list[str] = []

    def find_grc_field_entities(value: object) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "grc" and isinstance(child, str):
                    grc_field_entities.extend(ENTITY_RE.findall(child))
                find_grc_field_entities(child)
        elif isinstance(value, list):
            for child in value:
                find_grc_field_entities(child)

    find_grc_field_entities(records)

    greek = "".join(greek_chunks)
    residue = RESIDUE_RE.findall(greek)
    check(
        not residue and not example_bad,
        "Beta Code residue",
        f"{len(residue)} residue characters in HTML Greek; {len(example_bad)} bad example records",
        failures,
    )
    check(
        not greek_entities and not grc_field_entities,
        "no entities in Greek",
        f"{len(greek_entities)} HTML Greek entities; {len(grc_field_entities)} grc-field entities",
        failures,
    )
    non_nfc = sum(chunk != unicodedata.normalize("NFC", chunk) for chunk in greek_chunks)
    latin_macrons = LATIN_MACRON_RE.findall(json.dumps(records, ensure_ascii=False))
    check(
        non_nfc == 0 and not latin_macrons,
        "Unicode normalization",
        f"{non_nfc} non-NFC Greek chunks; {len(latin_macrons)} Latin quantity vowels",
        failures,
    )
    check(
        not example_fused,
        "one example, one citation",
        f"{len(example_fused)} examples hold two Greek sentences and one citation; "
        f"first={example_fused[:3]}",
        failures,
    )
    check(not empty, "nonempty bodies", f"{len(empty)} empty records", failures)
    oversized = [
        record.get("n")
        for record in sections
        if isinstance(record.get("plain"), str) and len(record["plain"]) > 20_000
    ]
    check(
        not oversized,
        "numbered section size cap",
        f"{len(oversized)} sections exceed 20,000 plain chars",
        failures,
    )
    check(
        not raw_text and not html_errors,
        "no raw XML leakage",
        f"{len(raw_text)} text-field leaks; {len(html_errors)} HTML nesting errors",
        failures,
    )
    expected_apostrophes, heading_apostrophes = source_apostrophes(args.input)
    converted_apostrophes = greek.count("\u1fbd")
    check(
        "'" not in greek and converted_apostrophes == expected_apostrophes,
        "apostrophe conversion",
        f"{converted_apostrophes}/{expected_apostrophes} body apostrophes converted to U+1FBD; {heading_apostrophes} source heading apostrophes also render in the heading fields",
        failures,
    )
    try:
        source_blocks, unowned, duplicates, source_appendices = source_body_ownership(args.input)
        check(
            unowned == 0 and duplicates == 0 and len(appendices) == source_appendices,
            "source body-block ownership",
            f"{source_blocks} direct body blocks; {unowned} unowned; {duplicates} multiply owned; {source_appendices} appendix divisions",
            failures,
        )
    except (ET.ParseError, ValueError) as error:
        check(False, "source body-block ownership", str(error), failures)

    # Every example is a pair the print itself sets.
    #
    # Nothing above this reads what an example says.  The checks ask that
    # "grc" hold no Beta Code residue, that it be NFC, and that it not run to
    # two sentences; the citation and the gloss are never looked at at all.
    # So an example could carry another example's reference, or another
    # sentence's translation, and every check would still report PASS.  That
    # is how 48 examples shipped whose Greek was not the Greek the print sets
    # there: ``greek_of`` gathered Greek from inside and after the English
    # translation, so Goodwin's own explanatory form was glued to the end of
    # the quotation.  §116 shipped "Περικλῆς προηγόρευε, ὅτι Ἀρχίδαμός οἱ
    # ξένος εἴη ξένος μοί ἐστιν", where the print sets only the first six
    # words as Thucydides and "(i.e. he said ξένος μοί ἐστιν)" as Goodwin;
    # §92 shipped "cf. the following δείξεις δὲ μᾶλλον" inside the quotation
    # of Sophocles; §875 shipped "ὡς ἐμοῦ μόνης πέλας οὔσης" for a line that
    # ends at πέλας, the participle being the editor's "(sc. οὔσης)".
    #
    # This check reads the rendered section instead.  It asks that the print
    # set the Greek, the translation and the recorded citation together, in
    # the order Goodwin prints them.  Relax the tail clause in ``greek_of``
    # again and 48 examples fail here while the nine checks above stay green.
    unseated: list[object] = []
    seated = 0
    for record in records:
        html_value = record.get("html")
        if not isinstance(html_value, str):
            continue
        items = printed_items(html_value)
        number = record.get("n")
        cursor = 0
        for example in record.get("examples", []):
            if not isinstance(example, dict):
                continue
            if (number, example.get("cite")) in PRINTED_GREEK_CORRUPT:
                continue
            place = next(
                (
                    end
                    for index in range(cursor, len(items))
                    if (end := seat_example(items, index, example)) is not None
                ),
                None,
            )
            if place is None:
                unseated.append(
                    (record.get("id"), norm(str(example.get("grc", "")))[:50], example.get("cite"))
                )
            else:
                seated = seated + 1
                cursor = place
    check(
        not unseated,
        "every example is a pair the print itself sets",
        f"{seated} examples seated in the printed section; "
        f"{len(unseated)} not set together by the print; "
        f"{len(PRINTED_GREEK_CORRUPT)} allowed for a corrupt source reading; "
        f"first={unseated[:5]}",
        failures,
    )

    print("\nSPOT CHECKS")
    for number in (1, 355, 926):
        record = records[number - 1]
        examples = record.get("examples", [])
        sample = {
            "id": record["id"],
            "head": record["head"],
            "plainStart": str(record["plain"])[:500],
            "exampleCount": len(examples) if isinstance(examples, list) else None,
            "firstExample": examples[0] if isinstance(examples, list) and examples else None,
        }
        print(json.dumps(sample, ensure_ascii=False))

    print(f"\nVERIFY RESULT: {'PASS' if not failures else 'FAIL'}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
