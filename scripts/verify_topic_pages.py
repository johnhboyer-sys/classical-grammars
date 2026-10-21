#!/usr/bin/env python3
"""Verify the section citations in topics/*.md against the grammar corpora.

research/topic-pages-design.md makes this the QA model for authored prose:
every claim carries a section citation, and a script checks each citation
mechanically. For every "§n" or "§n a" citation in a page:

  - the section exists in the named grammar (Smyth unless the citation is
    prefixed "GMT", "Gildersleeve", "Monro", "Goodell", "A&G" or "Bennett";
    every non-Smyth citation must carry its own prefix, a bare § never
    inherits one);
  - a lettered anchor ("§2072 a") is on the section's letters list, else
    WARN (the TEI marks only a subset of Smyth's lettered subdivisions);
  - for each sentence that carries the citation, at least two of the
    sentence's content words (lowercase, four letters or more, not
    stopwords, matched on a six-letter stem) or one quoted Greek string
    (compared with accents and macrons stripped) appear in the cited
    section's plain text or head, else WARN with the sentence, so a claim
    the section does not support is visible;
  - every Greek word the sentence quotes appears in one of the sections
    that sentence cites, else FAIL naming the word, so a form no witness
    supplies cannot reach the page;
  - every Greek word anywhere on the page, including in a sentence that
    cites nothing, appears in some section the page declares. This is the
    backstop: a workflow step naming a form and citing no section would
    otherwise not be read at all.

A range "§§2054-2087" is checked section by section for existence and
against the pooled text of the range for support.

The front matter's `sections:` block must list, per grammar, exactly the
sections and ranges the body cites; `slug:` must match the file name;
and `topic:`, where a page carries one, must name a record in
data/smyth/topics.json.

FAIL on a missing section, a slug mismatch, or a front-matter mismatch.
WARN never fails the run unless --strict is given. Exit status is non-zero
on any FAIL.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PAGES = ROOT / "topics"
DATA = ROOT / "data"

WORKS = {
    None: "smyth",
    "Smyth": "smyth",
    "GMT": "goodwin-gmt",
    "Gildersleeve": "gildersleeve",
    "Monro": "monro",
    "Goodell": "goodell",
    "A&G": "ag",
    "Bennett": "bennett",
}

CITATION_RE = re.compile(
    r"(?:\b(Smyth|GMT|Gildersleeve|Monro|Goodell|A&G|Bennett)\s+)?"
    r"(§§?)\s*(\d+)(?:\s*[-–]\s*(\d+))?"
    r"(?:\s+([a-z])(?=[),.;:\]]|\s*$))?"
)

GREEK_RUN_RE = re.compile(r"[Ͱ-Ͽἀ-῿][Ͱ-Ͽἀ-῿̀-ͯ’᾽᾿'ʼ ]*")

# The sentence break. Two shapes are not one, and both were found by
# pages that passed while a Greek run went unchecked.
#
# The mark must follow a letter or a closing bracket. LSJ's and Smyth's
# spaced ellipsis (". . .") otherwise broke a quotation in half whenever
# the next word began with an accented Greek vowel, and the half holding
# the Greek then carried no citation.
#
# A citation in parentheses continues its sentence. "did I not say so?
# (§2025)" split into a sentence with the Greek and no citation, and one
# with the citation and nothing to check.
SENTENCE_SPLIT_RE = re.compile(
    r"(?<=[^\s.][.!?])\s+"
    r"(?!\(\s*(?:Smyth|GMT|Gildersleeve|Monro|Goodell|A&G|Bennett)?\s*§)"
    r"(?=[A-ZΑ-ΩἈ-῿\"“(§])")

STOP = {
    "that", "this", "with", "from", "when", "which", "what", "where", "there",
    "their", "they", "then", "than", "have", "been", "being", "also", "into",
    "only", "some", "such", "does", "must", "will", "would", "could", "should",
    "here", "these", "those", "about", "after", "before", "more", "most",
    "very", "like", "just", "each", "both", "other", "same", "still", "often",
    "usually", "always", "never", "whether", "because", "since", "while",
    "until", "though", "although", "itself", "them", "your", "ours", "says",
    "note", "cite", "cited", "look", "read", "make", "makes", "give", "gives",
    "take", "takes", "want", "wants", "page", "pages", "topic", "topics",
  "smyth", "goodwin", "gildersleeve", "monro", "goodell", "section",
    "sections", "test", "check", "expect", "normally", "closest", "match",
    "rarely", "even", "again", "another", "between", "under", "over", "back",
    "lists", "list", "example", "examples", "compare", "compared",
}


def fold(text: str) -> str:
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.replace("’", "'").replace("᾽", "'").replace("᾿", "'").replace("ʼ", "'")
    return " ".join(text.lower().split())


def stem(word: str) -> str:
    return word if len(word) <= 6 else word[:6]


class Corpus:
    def __init__(self) -> None:
        self.loaded: dict[str, dict[int, dict] | None] = {}

    def get(self, work: str) -> dict[int, dict] | None:
        if work not in self.loaded:
            path = DATA / work / "sections.jsonl"
            if not path.exists():
                self.loaded[work] = None
            else:
                rows: dict[int, dict] = {}
                with path.open(encoding="utf-8") as fh:
                    for line in fh:
                        if line.strip():
                            row = json.loads(line)
                            if isinstance(row.get("n"), int):
                                rows[row["n"]] = row
                self.loaded[work] = rows
        return self.loaded[work]


_TOPIC_SLUGS: set[str] | None = None


def topic_slugs() -> set[str]:
    """Slugs in the derived topic list, read once."""
    global _TOPIC_SLUGS
    if _TOPIC_SLUGS is None:
        path = DATA / "smyth" / "topics.json"
        if path.exists():
            with path.open(encoding="utf-8") as fh:
                _TOPIC_SLUGS = {t["slug"] for t in json.load(fh)["topics"]}
        else:
            _TOPIC_SLUGS = set()
    return _TOPIC_SLUGS


class Report:
    def __init__(self) -> None:
        self.fails = 0
        self.warns = 0
        self.passes = 0

    def check(self, ok: bool, title: str, detail: str = "") -> None:
        if ok:
            self.passes += 1
        else:
            self.fails += 1
        print(f"[{'PASS' if ok else 'FAIL'}] {title}")
        for line in detail.splitlines():
            print(f"  {line}")

    def warn(self, title: str, detail: str = "") -> None:
        self.warns += 1
        print(f"[WARN] {title}")
        for line in detail.splitlines():
            print(f"  {line}")


def split_front_matter(text: str) -> tuple[str, str]:
    if not text.startswith("---"):
        return "", text
    end = text.find("\n---", 3)
    if end < 0:
        return "", text
    return text[3:end], text[end + 4:]


def parse_front_matter(fm: str) -> dict:
    """A deliberately small YAML-ish reader: `key: value`, `key:` followed by
    `  - item` lines, and a `sections:` block of `  work: [a, b-c, ...]`."""
    out: dict = {}
    current: str | None = None
    for line in fm.splitlines():
        if not line.strip():
            continue
        if line.startswith("  - ") and current:
            out.setdefault(current, []).append(line[4:].strip().strip('"'))
            continue
        m = re.match(r"^  ([a-z0-9-]+):\s*\[(.*)\]\s*$", line)
        if m and current == "sections":
            out.setdefault("sections", {})[m.group(1)] = [
                p.strip() for p in m.group(2).split(",") if p.strip()
            ]
            continue
        m = re.match(r"^([a-z]+):\s*(.*)$", line)
        if m:
            current = m.group(1)
            value = m.group(2).strip()
            if value:
                out[current] = value.strip('"')
            elif current == "sections":
                out.setdefault("sections", {})
            else:
                out.setdefault(current, [])
    return out


BLOCK_START = re.compile(r"^(?:#+\s|[-*]\s|\d+\.\s|\||>)")


def blocks(body: str) -> list[str]:
    """The body as paragraphs, with hard-wrapped lines joined.

    A page that wraps its prose at eighty columns was reading as one
    sentence per line, so "…the substantive-making power of the article\n
    (§1153) and the predicate position…" arrived as a sentence beginning
    on a citation and sharing almost nothing with it. Headings, list
    items, table rows and quotations start their own block; a blank line
    ends one."""
    out: list[str] = []
    current: list[str] = []
    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            if current:
                out.append(" ".join(current))
                current = []
            continue
        if BLOCK_START.match(line):
            if current:
                out.append(" ".join(current))
                current = []
            line = re.sub(r"^#+\s*", "", line)
            line = re.sub(r"^(?:[-*]|\d+\.)\s+", "", line)
            out.append(line)
            continue
        current.append(line)
    if current:
        out.append(" ".join(current))
    return out


def sentences(body: str) -> list[str]:
    out: list[str] = []
    for block in blocks(body):
        block = block.replace("`", "")
        for s in SENTENCE_SPLIT_RE.split(block):
            s = s.strip()
            if s:
                out.append(s)
    return out


def dehyphenate(text: str) -> str:
    """The print breaks a word across a line and the TEI keeps the hyphen
    and the break: Smyth 2070 d holds "γιγνομέ- νων". A page quoting the
    whole word is right and the section still contains it, so the joined
    form is searched too."""
    return re.sub(r"-\s+", "", text)


def unhyphenate(text: str) -> str:
    """The print's own syllable hyphens inside a form. The comparison
    tables set "δηλό-τερος", "κακ-ῑ́ων", "πρό-τερο-ς", and a page quoting
    the word as one piece is quoting what the section holds."""
    return text.replace("-", "")


def haystack(rows: dict[int, dict], numbers: list[int]) -> str:
    parts = []
    for n in numbers:
        row = rows.get(n)
        if row:
            parts.append(row.get("head", ""))
            parts.append(row.get("plain", ""))
    folded = fold(" ".join(parts))
    # Every spelling, not one: the hyphen is real in some sections, a
    # line break in others and a syllable division in the paradigm
    # tables, and dropping it everywhere would hide the difference.
    return " ".join((folded, dehyphenate(folded), unhyphenate(folded)))


def greek_missing(sentence: str, hay: str) -> list[tuple[str, str]]:
    """(run, word) for every Greek word quoted that the sentence's own
    sections do not contain.

    `support` asks only whether a citation is on topic, and one match
    anywhere in the sentence satisfies it. This asks the harder question,
    the one the editorial law actually states: a page may not put a Greek
    form on the screen unless a section it cites supplies it.

    The test is word by word, not run by run, because a page may quote
    across what the print separates — an ellipsis Smyth prints inside the
    example, or a phrase the section states in two places. Word order and
    the print's own gaps are not the page's to preserve; the forms are.
    """
    out = []
    for run in GREEK_RUN_RE.findall(CITATION_RE.sub(" ", sentence)):
        folded = fold(run).strip(" '")
        if len(folded.replace(" ", "")) < 2:
            continue
        if folded in hay:
            continue
        for word in folded.split():
            if len(word.strip("'")) >= 2 and word not in hay:
                out.append((run.strip(), word))
    return out


def support(sentence: str, hay: str) -> tuple[list[str], list[str]]:
    """(content words found, Greek strings found)."""
    text_no_cites = CITATION_RE.sub(" ", sentence)
    tokens = set(hay.split())
    found_words = []
    words = {w for w in re.findall(r"[a-z]+", text_no_cites.lower()) if len(w) >= 4 and w not in STOP}
    for word in sorted(words):
        st = stem(word)
        if any(tok.startswith(st) for tok in tokens):
            found_words.append(word)
    found_greek = []
    for run in GREEK_RUN_RE.findall(text_no_cites):
        folded = fold(run).strip(" '")
        if len(folded.replace(" ", "")) >= 2 and folded in hay:
            found_greek.append(run.strip())
    return found_words, found_greek


def verify_page(path: Path, corpus: Corpus, report: Report) -> None:
    text = path.read_text(encoding="utf-8")
    fm_text, body = split_front_matter(text)
    fm = parse_front_matter(fm_text)
    full = path.resolve()
    shown = full.relative_to(ROOT) if full.is_relative_to(ROOT) else path
    print(f"\n== {shown}")

    report.check(
        fm.get("slug") == path.stem,
        f"front matter slug matches file name ({path.stem})",
        f"slug={fm.get('slug')!r}",
    )
    report.check(
        bool(fm.get("title")) and bool(fm.get("questions")) and bool(fm.get("aliases")),
        "front matter carries title, aliases and questions",
        f"title={fm.get('title')!r}; aliases={len(fm.get('aliases', []))}; "
        f"questions={len(fm.get('questions', []))}",
    )
    # The `topic` field points at a record in the derived topic list, and
    # a pointer that names nothing is worse than no pointer: it reads as
    # a link to a page that does not exist. particle-an.md carried
    # `topic: an` for a day before the Greek index became a topic source
    # and gave ἄν a record.
    topic = fm.get("topic")
    if topic:
        report.check(
            topic in topic_slugs(),
            f"front matter topic names a record in the topic list ({topic})",
            "" if topic in topic_slugs() else
            f"no topic with slug {topic!r} in data/smyth/topics.json",
        )

    cited: dict[str, set[str]] = {}
    missing: list[str] = []
    unknown_work: list[str] = []
    anchor_miss: list[str] = []
    weak: list[tuple[str, str, list[str], list[str]]] = []
    n_citations = 0
    n_sentences = 0
    run_on = []
    unsourced: list[str] = []
    for sentence in sentences(body):
        matches = list(CITATION_RE.finditer(sentence))
        if not matches:
            continue
        n_sentences += 1
        pooled: list[str] = []
        # A bare "§n" means Smyth, so a run-on list after another
        # grammar's prefix ("GMT §594, §595") silently checks the second
        # number against Smyth, where it may exist and say something
        # else. Inside one sentence, a bare citation that follows a
        # prefixed one with only a separator between them is flagged:
        # the page must repeat the prefix or say Smyth.
        for i, m in enumerate(matches):
            n_citations += 1
            prefix, marker, start, end, letter = m.groups()
            if prefix is None and i:
                prev = matches[i - 1]
                between = sentence[prev.end():m.start()]
                # A comma or "and" continues a list, and the reader
                # carries the prefix across it. A semicolon separates two
                # sources, so "(GMT §457; §2619)" is a mixed citation and
                # the bare number is Smyth's, as everywhere else.
                if prev.group(1) and re.fullmatch(r"[\s,]*(?:and|or)?[\s,]*", between):
                    run_on.append(
                        f"{prev.group(1)} {prev.group(2)}{prev.group(3)} then a bare "
                        f"{marker}{start} in: {sentence.strip()[:110]}")
            work = WORKS[prefix]
            rows = corpus.get(work)
            label = f"{prefix + ' ' if prefix else ''}{marker}{start}{'-' + end if end else ''}{' ' + letter if letter else ''}"
            if rows is None:
                unknown_work.append(label)
                continue
            first, last = int(start), int(end) if end else int(start)
            numbers = list(range(first, last + 1)) if last >= first else [first]
            cited.setdefault(work, set()).add(f"{first}-{last}" if end else str(first))
            absent = [n for n in numbers if n not in rows]
            if absent:
                missing.append(f"{label} (absent: {absent[:5]})")
                continue
            if letter and letter not in rows[first].get("letters", []):
                anchor_miss.append(f"{label} (letters: {rows[first].get('letters')})")
            hay = haystack(rows, numbers)
            pooled.append(hay)
            words, greek = support(sentence, hay)
            if len(words) < 2 and not greek:
                weak.append((label, sentence, words, greek))
        # Pooled, because a sentence citing two sections may quote from
        # either, and the reader who follows the citations sees both.
        for run, word in greek_missing(sentence, " ".join(pooled)):
            unsourced.append(f"{word!r} of {run!r} in: {sentence.strip()[:120]}")

    report.check(
        not run_on,
        "every citation names its grammar; no bare section number follows "
        "another grammar's",
        "\n".join(run_on),
    )
    report.check(
        not missing and not unknown_work,
        f"every cited section exists ({n_citations} citations in {n_sentences} sentences)",
        ("missing: " + "; ".join(missing) if missing else "")
        + ("\nno corpus for: " + "; ".join(unknown_work) if unknown_work else ""),
    )
    if anchor_miss:
        report.warn(
            f"{len(anchor_miss)} lettered anchors are not on the section's letters list",
            "\n".join(anchor_miss),
        )
    # A failure, not a warning. The other two reports below are
    # heuristics about how well a sentence matches its section; this one
    # is the editorial law itself, and a Greek form no cited section
    # supplies has no witness behind it.
    report.check(
        not unsourced,
        "every Greek word quoted is in a section the sentence cites",
        "\n".join(unsourced),
    )
    if weak:
        report.warn(
            f"{len(weak)} citations whose sentence shares fewer than two content words "
            "and no Greek string with the cited section",
            "\n".join(
                f"{label}: {sentence}\n    words found: {words}; greek found: {greek}"
                for label, sentence, words, greek in weak
            ),
        )
    else:
        report.check(True, "every cited sentence shares content with its section")

    # The backstop. The check above reads a sentence against the
    # sections that sentence cites, so a sentence carrying no citation at
    # all is not read: a workflow step saying "read the negative as μή"
    # names a Greek form and cites nothing, and 155 sentences over these
    # pages are of that shape. Every Greek word on the page must occur in
    # some section the page declares, whatever sentence it stands in.
    page_hay = []
    for work, parts in (fm.get("sections") or {}).items():
        rows = corpus.get(work)
        if rows is None:
            continue
        numbers = []
        for part in parts:
            part = part.replace("–", "-")
            if "-" in part:
                first, last = part.split("-", 1)
                numbers.extend(range(int(first), int(last) + 1))
            elif part.isdigit():
                numbers.append(int(part))
        page_hay.append(haystack(rows, numbers))
    page_hay = " ".join(page_hay)
    stray = []
    for sentence in sentences(body):
        if list(CITATION_RE.finditer(sentence)):
            continue
        for run, word in greek_missing(sentence, page_hay):
            stray.append(f"{word!r} of {run!r} in: {sentence.strip()[:110]}")
    report.check(
        not stray,
        "every Greek word on the page is in a section the page cites",
        "\n".join(stray),
    )

    declared = {
        work: {p.replace("–", "-") for p in parts}
        for work, parts in fm.get("sections", {}).items()
    }
    problems = []
    for work in sorted(set(declared) | set(cited)):
        d, c = declared.get(work, set()), cited.get(work, set())
        if d != c:
            extra = sorted(d - c, key=lambda s: int(s.split("-")[0]))
            absent = sorted(c - d, key=lambda s: int(s.split("-")[0]))
            problems.append(f"{work}: declared but not cited {extra}; cited but not declared {absent}")
    report.check(
        not problems,
        "front-matter sections list matches the body's citations",
        "\n".join(problems)
        + (
            "\nbody cites: "
            + "; ".join(
                f"{w}: [{', '.join(sorted(v, key=lambda s: int(s.split('-')[0])))}]"
                for w, v in sorted(cited.items())
            )
            if problems
            else ""
        ),
    )
    print(
        f"  citations {n_citations}  sentences with citations {n_sentences}  "
        f"works {sorted(cited)}  weak {len(weak)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pages", nargs="*", type=Path, help="page files (default: topics/*.md)")
    parser.add_argument("--strict", action="store_true", help="treat WARN as FAIL")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    pages = args.pages or sorted(DEFAULT_PAGES.glob("*.md"))
    corpus = Corpus()
    report = Report()
    if not pages:
        print("no topic pages found")
        return 1
    for page in pages:
        verify_page(page, corpus, report)

    print("\nVERIFY REPORT SUMMARY")
    print(f"  pages: {len(pages)}; checks passed: {report.passes}; failed: {report.fails}; warnings: {report.warns}")
    failed = report.fails > 0 or (args.strict and report.warns > 0)
    print(f"  overall: {'FAIL' if failed else 'PASS'}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
