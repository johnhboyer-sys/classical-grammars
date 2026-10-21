#!/usr/bin/env python3
"""Build data/smyth/topics.json: the derived topic list for the topic-page layer.

research/topic-pages-design.md rules out a hand-built ontology. Every topic
here is a materialised join of data the repo already owns:

  data/smyth/index-english.json   Smyth's own terminology: each headword with
                                  the sections it cites
  data/smyth/index-greek.json     Smyth's Greek index: the particles,
                                  prepositions, pronouns and endings a learner
                                  searches for, each with the sections it cites
  data/smyth/constructions.json   construction names from the AGDT annotation
                                  guidelines (CC BY-SA, see meta.attribution)
                                  with their section ranges
  data/smyth/sections.jsonl       cross-reference hubs: inbound refs (citedBy)
                                  per section, counted twice, once over the
                                  whole grammar and once over Part IV Syntax
                                  only, because Part I phonology dominates the
                                  raw counts

A topic starts as one index headword or one construction name. Construction
names that cite exactly the same sections are one topic. A construction topic
is then folded into the index topic whose expanded section set it overlaps
best (Jaccard at or above JACCARD_MERGE); both names are kept, the headword
as the name and the construction name as an alias. Index topics never merge
with each other, so a construction can never bridge two headwords. A section
whose inbound Part IV count reaches HUB_MIN_SYNTAX is a hub; every topic that
cites it explicitly records it, and a hub no topic cites becomes a topic of
its own, named by its section head.

The Greek index is a fourth seed source and it stands apart from the other
three. A Greek entry becomes one topic named by the headword the print gives,
with the transliteration in aliases; entries printing the same headword are
one topic. Greek seeds never merge with an English headword or a construction
and never take a slug another topic already holds, so adding this source adds
records and changes none.

Two files come out of the one join. topics.json holds the topic records,
each naming the sections it covers. section-topics.json holds the same join
read backwards: one row per Smyth section with the slugs of the topics that
cover it, ranges expanded. It is a separate file rather than a field on
sections.jsonl because topics.json is derived from sections.jsonl, so writing
the answer back into sections.jsonl would make the converter's output depend
on its own output; SPEC-section-ids.md records that.

Python stdlib only. Deterministic: sorted output, stable slugs, no
timestamps. Verified by scripts/verify_topics.py.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SECTIONS = ROOT / "data" / "smyth" / "sections.jsonl"
DEFAULT_INDEX = ROOT / "data" / "smyth" / "index-english.json"
DEFAULT_INDEX_GREEK = ROOT / "data" / "smyth" / "index-greek.json"
DEFAULT_CONSTRUCTIONS = ROOT / "data" / "smyth" / "constructions.json"
DEFAULT_OUT = ROOT / "data" / "smyth" / "topics.json"
DEFAULT_OUT_SECTIONS = ROOT / "data" / "smyth" / "section-topics.json"

# A construction joins the index headword it overlaps this much (Jaccard on
# the expanded section sets). 0.5 means the shared sections are at least half
# of the union: a construction whose range is the range the index cites
# merges, a construction whose few sections sit inside a headword that cites
# two hundred does not.
JACCARD_MERGE = 0.5

# A section cited by at least this many other Part IV sections is a hub.
HUB_MIN_SYNTAX = 5

# Construction context kinds that name a construction rather than pool the
# sections a heading happens to discuss (SPEC-constructions.md: "prose
# entries are context, not definitions").
CONSTRUCTION_KINDS = ("list-item", "table-row", "heading")

SYNTAX_PART = "Part IV: Syntax"

GREEK_TO_LATIN = {
    "α": "a", "β": "b", "γ": "g", "δ": "d", "ε": "e", "ζ": "z", "η": "e",
    "θ": "th", "ι": "i", "κ": "k", "λ": "l", "μ": "m", "ν": "n", "ξ": "x",
    "ο": "o", "π": "p", "ρ": "r", "σ": "s", "ς": "s", "τ": "t", "υ": "u",
    "φ": "ph", "χ": "ch", "ψ": "ps", "ω": "o",
}
ROUGH_BREATHING = "̔"
SMOOTH_BREATHING = "̓"

# Greek index entries that are not topics, and why. A headword that is one
# Greek letter carrying no breathing is the letter itself, not a word: those
# entries are about pronunciation, quantity, and what the letter turns into
# before another consonant. A breathing marks a word, so ὁ, ἤ, ὦ and ᾗ stay.
# An entry with no section to point at is a bare cross-reference ("οὐκ, see
# οὐ") and has nothing for a topic to cover.
GREEK_EXCLUDE_LETTER = "alphabet-letter"
GREEK_EXCLUDE_NO_SECTIONS = "no-section-refs"


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------


def load_sections(path: Path) -> dict[int, dict]:
    rows: dict[int, dict] = {}
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                row = json.loads(line)
                rows[row["n"]] = row
    return rows


def ref_number(ref_id: str) -> int | None:
    match = re.search(r":(\d+)$", ref_id)
    return int(match.group(1)) if match else None


def inbound_counts(sections: dict[int, dict]) -> dict[int, tuple[int, int]]:
    """n -> (inbound, inboundSyntax): distinct citing sections other than
    the section itself, then the subset of those in Part IV."""
    counts: dict[int, tuple[int, int]] = {}
    for n, row in sections.items():
        citers = set()
        for cited_by in row.get("citedBy", []):
            m = ref_number(cited_by)
            if m is not None and m != n and m in sections:
                citers.add(m)
        syntax = sum(1 for m in citers if sections[m]["path"][0] == SYNTAX_PART)
        counts[n] = (len(citers), syntax)
    return counts


# --------------------------------------------------------------------------
# Slugs
# --------------------------------------------------------------------------


def slugify(text: str) -> str:
    """Lowercase ASCII, hyphen-separated. Greek is transliterated with the
    table build_landmarks.py uses for particle slugs (rough breathing at word
    start becomes h-, or rh- on rho); every other mark is dropped."""
    nfd = unicodedata.normalize("NFD", text)
    out: list[str] = []
    word_start = True
    for i, ch in enumerate(nfd):
        if unicodedata.combining(ch):
            continue
        base = ch.lower()
        if base in GREEK_TO_LATIN:
            latin = GREEK_TO_LATIN[base]
            if word_start:
                j = i + 1
                while j < len(nfd) and unicodedata.combining(nfd[j]):
                    if nfd[j] == ROUGH_BREATHING:
                        latin = "rh" if base == "ρ" else "h" + latin
                    j += 1
            out.append(latin)
            word_start = False
        elif base.isascii() and base.isalnum():
            out.append(base)
            word_start = False
        else:
            out.append("-")
            word_start = True
    return re.sub(r"-+", "-", "".join(out)).strip("-")


def fold_name(text: str) -> str:
    return " ".join(slugify(text).split("-"))


def strip_numbering(heading: str) -> str:
    return re.sub(r"^\s*[\d.]+\s*", "", heading).strip()


# --------------------------------------------------------------------------
# Section lists
# --------------------------------------------------------------------------


def section_key(entry: dict) -> tuple[int, int]:
    return (entry["n"], entry.get("to", entry["n"]))


def normalise_sections(entries: list[dict]) -> list[dict]:
    seen: dict[tuple[int, int], dict] = {}
    for entry in entries:
        key = section_key(entry)
        if key not in seen:
            seen[key] = {"n": key[0]} if key[0] == key[1] else {"n": key[0], "to": key[1]}
    return [seen[k] for k in sorted(seen)]


def expand(entries: list[dict], sections: dict[int, dict]) -> set[int]:
    out: set[int] = set()
    for entry in entries:
        for n in range(entry["n"], entry.get("to", entry["n"]) + 1):
            if n in sections:
                out.add(n)
    return out


def jaccard(a: set[int], b: set[int]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# --------------------------------------------------------------------------
# Seed topics
# --------------------------------------------------------------------------


class Seed:
    """One pre-merge topic: an index headword or a construction name."""

    def __init__(self, kind: str, name: str, sections: list[dict], provenance: dict):
        self.kind = kind  # "index" | "construction"
        self.name = name
        self.sections = sections
        self.provenance = provenance
        self.cross_refs: list[str] = []
        # Slug qualifiers for a construction name that collides, coarsest
        # last: immediate menu, root of the decision tree, source heading.
        self.qualifiers: list[str] = []


def index_refs(entry: dict) -> list[dict]:
    refs = list(entry.get("refs", []))
    for sub in entry.get("sub", []):
        refs.extend(sub.get("refs", []))
    return refs


def seeds_from_index(index_doc: dict, sections: dict[int, dict], audit: dict) -> list[Seed]:
    by_name: dict[str, Seed] = {}
    for entry in index_doc["entries"]:
        headword = entry["headword"].strip()
        cited: list[dict] = []
        for ref in index_refs(entry):
            if ref.get("nonSection"):
                continue
            n = ref.get("n")
            if not isinstance(n, int) or n not in sections:
                continue
            to = ref.get("to")
            if isinstance(to, int) and to in sections and to >= n:
                cited.append({"n": n, "to": to})
            else:
                cited.append({"n": n})
        provenance = {"headword": headword, "raw": entry["raw"], "pages": entry["pages"]}
        if not cited:
            audit["indexEntriesWithoutSections"].append(
                {"headword": headword, "crossRefs": entry.get("crossRefs", [])}
            )
            continue
        key = fold_name(headword)
        seed = by_name.get(key)
        if seed is None:
            seed = Seed("index", headword, [], {"indexEntries": []})
            by_name[key] = seed
        seed.sections = normalise_sections(seed.sections + cited)
        seed.provenance["indexEntries"].append(provenance)
        seed.cross_refs.extend(entry.get("crossRefs", []))
    return [by_name[k] for k in sorted(by_name)]


def seeds_from_constructions(doc: dict, sections: dict[int, dict]) -> list[Seed]:
    grouped: dict[tuple[str, tuple[tuple[int, int], ...]], Seed] = {}
    for entry in doc["entries"]:
        if entry["contextKind"] not in CONSTRUCTION_KINDS:
            continue
        cited = normalise_sections(
            [
                {"n": s["n"], **({"to": s["to"]} if "to" in s else {})}
                for s in entry["sections"]
                if s["n"] in sections
            ]
        )
        if not cited:
            continue
        key = (fold_name(entry["construction"]), tuple(section_key(s) for s in cited))
        seed = grouped.get(key)
        if seed is None:
            seed = Seed("construction", entry["construction"], cited, {"constructions": []})
            context = [p.strip() for p in entry["agdtContext"].split(">")]
            heading = strip_numbering(entry["sourceHeading"].split(">")[-1])
            if len(context) > 1:
                seed.qualifiers = [context[-2], context[0], heading]
            else:
                seed.qualifiers = [heading]
            grouped[key] = seed
        seed.provenance["constructions"].append(
            {
                "construction": entry["construction"],
                "agdtContext": entry["agdtContext"],
                "contextKind": entry["contextKind"],
                "sourceHeading": entry["sourceHeading"],
            }
        )
    return [grouped[k] for k in sorted(grouped)]


# --------------------------------------------------------------------------
# Merging
# --------------------------------------------------------------------------


def merge_seeds(seeds: list[Seed], sections: dict[int, dict], audit: dict) -> list[list[Seed]]:
    index_seeds = [s for s in seeds if s.kind == "index"]
    index_expanded = [expand(s.sections, sections) for s in index_seeds]
    clusters: list[list[Seed]] = [[s] for s in index_seeds]

    # Construction names citing exactly the same sections are one topic.
    same_sections: dict[tuple[tuple[int, int], ...], list[Seed]] = defaultdict(list)
    for seed in seeds:
        if seed.kind == "construction":
            same_sections[tuple(section_key(s) for s in seed.sections)].append(seed)

    standalone: list[list[Seed]] = []
    for key in sorted(same_sections):
        group = sorted(same_sections[key], key=lambda s: fold_name(s.name))
        expanded = expand(group[0].sections, sections)
        if any(
            c["contextKind"] == "heading"
            for seed in group
            for c in seed.provenance["constructions"]
        ):
            # The adposition sections (heading kind): the preposition is its
            # own topic, never an alias of an English headword that happens
            # to cite its section.
            standalone.append(group)
            continue
        best: int | None = None
        best_score = 0.0
        for i, other in enumerate(index_expanded):
            score = jaccard(expanded, other)
            if score > best_score or (
                score == best_score
                and best is not None
                and fold_name(index_seeds[i].name) < fold_name(index_seeds[best].name)
            ):
                best, best_score = i, score
        if best is not None and best_score >= JACCARD_MERGE:
            clusters[best].extend(group)
            audit["merges"].append(
                {
                    "headword": index_seeds[best].name,
                    "constructions": [s.name for s in group],
                    "jaccard": round(best_score, 3),
                }
            )
        else:
            standalone.append(group)
    return clusters + standalone


def cluster_name(cluster: list[Seed]) -> tuple[str, str]:
    """(name, kind): the index headword if there is one, else the
    alphabetically first construction name."""
    for seed in cluster:
        if seed.kind == "index":
            return seed.name, "index"
    return sorted((s.name for s in cluster), key=fold_name)[0], "construction"


# --------------------------------------------------------------------------
# Topic records
# --------------------------------------------------------------------------


def make_topic(cluster: list[Seed], sections: dict[int, dict]) -> dict:
    name, kind = cluster_name(cluster)
    all_sections = normalise_sections([s for seed in cluster for s in seed.sections])
    names = sorted({seed.name for seed in cluster}, key=fold_name)
    aliases = [n for n in names if n != name]
    sources = sorted(
        {"index-english" if seed.kind == "index" else "constructions" for seed in cluster}
    )
    provenance: dict = {"indexEntries": [], "constructions": []}
    cross_refs: list[str] = []
    qualifiers: list[str] = []
    for seed in cluster:
        provenance["indexEntries"].extend(seed.provenance.get("indexEntries", []))
        provenance["constructions"].extend(seed.provenance.get("constructions", []))
        cross_refs.extend(seed.cross_refs)
        if seed.qualifiers and not qualifiers:
            qualifiers = seed.qualifiers
    provenance["indexEntries"].sort(key=lambda e: (fold_name(e["headword"]), e["raw"]))
    provenance["constructions"].sort(
        key=lambda c: (fold_name(c["construction"]), c["agdtContext"], c["contextKind"])
    )
    return {
        "slug": "",
        "name": name,
        "aliases": aliases,
        "sections": all_sections,
        "sources": sources,
        "hub": {},
        "anchors": [],
        "related": [],
        "provenance": provenance,
        "_nameSource": kind,
        "_crossRefs": sorted(set(cross_refs)),
        "_qualifiers": qualifiers,
    }


def assign_slugs(topics: list[dict]) -> None:
    groups: dict[str, list[dict]] = defaultdict(list)
    for topic in topics:
        groups[slugify(topic["name"])].append(topic)
    for base, members in groups.items():
        if len(members) == 1:
            members[0]["slug"] = base
            continue
        # Smyth's own headword keeps the bare slug (headwords were merged by
        # folded name, so there is at most one). Construction names are
        # qualified by the coarsest level of their AGDT context at which they
        # all come out distinct, then numbered if still tied.
        index_named = [t for t in members if t["_nameSource"] == "index"]
        others = sorted(
            (t for t in members if t["_nameSource"] != "index"),
            key=lambda t: (t["_qualifiers"], [section_key(s) for s in t["sections"]]),
        )
        for topic in index_named:
            topic["slug"] = base
        depth = max(len(t["_qualifiers"]) for t in others)
        chosen: list[str] | None = None
        for level in range(depth):
            candidate = [
                f"{base}-{slugify(t['_qualifiers'][min(level, len(t['_qualifiers']) - 1)])}"
                if t["_qualifiers"]
                else base
                for t in others
            ]
            if len(set(candidate)) == len(candidate) and base not in candidate:
                chosen = candidate
                break
        if chosen is None:
            chosen = [
                f"{base}-{slugify(t['_qualifiers'][0])}" if t["_qualifiers"] else base
                for t in others
            ]
        taken = {t["slug"] for t in members if t["slug"]}
        for topic, candidate in zip(others, chosen):
            if candidate in taken or candidate == base:
                i = 2
                while f"{candidate}-{i}" in taken:
                    i += 1
                candidate = f"{candidate}-{i}"
            topic["slug"] = candidate
            taken.add(candidate)


def hub_sections(sections: dict[int, dict], counts: dict[int, tuple[int, int]]) -> list[int]:
    return [n for n in sorted(sections) if counts[n][1] >= HUB_MIN_SYNTAX]


def explicit_holders(topics: list[dict]) -> dict[int, list[dict]]:
    """n -> the topics citing n explicitly, as a section or the start of a
    range."""
    by_explicit: dict[int, list[dict]] = defaultdict(list)
    for topic in topics:
        for n in sorted({entry["n"] for entry in topic["sections"]}):
            by_explicit[n].append(topic)
    return by_explicit


def record_hub(topic: dict, n: int) -> None:
    topic.setdefault("_hubSections", []).append(n)
    if "hub" not in topic["sources"]:
        topic["sources"] = sorted(topic["sources"] + ["hub"])


def attach_hubs(
    topics: list[dict],
    sections: dict[int, dict],
    counts: dict[int, tuple[int, int]],
    audit: dict,
) -> list[dict]:
    """Record hub sections on every topic that cites them explicitly (as a
    section or the start of a range); a hub nothing cites becomes its own
    topic."""
    by_explicit = explicit_holders(topics)
    hub_only: list[dict] = []
    for n in hub_sections(sections, counts):
        syntax = counts[n][1]
        holders = by_explicit.get(n, [])
        if holders:
            for topic in holders:
                record_hub(topic, n)
            audit["hubsAttached"].append(
                {"n": n, "inboundSyntax": syntax, "topics": sorted(t["slug"] for t in holders)}
            )
            continue
        row = sections[n]
        hub_only.append(
            {
                "slug": f"{slugify(row['head'])}-{n}",
                "name": row["head"],
                "aliases": [],
                "sections": [{"n": n}],
                "sources": ["hub"],
                "hub": {},
                "anchors": [],
                "related": [],
                "provenance": {"indexEntries": [], "constructions": []},
                "_nameSource": "hub",
                "_crossRefs": [],
                "_qualifiers": [],
                "_hubSections": [n],
            }
        )
        audit["hubsStandalone"].append({"n": n, "inboundSyntax": syntax, "head": row["head"]})
    return topics + hub_only


def attach_hubs_greek(
    greek_topics: list[dict],
    sections: dict[int, dict],
    counts: dict[int, tuple[int, int]],
    audit: dict,
) -> None:
    """A Greek topic records a hub it cites, like any other topic, but the
    standalone question was already settled by the other three sources.

    A hub only a Greek topic cites keeps its standalone record: a slug is a
    URL (SPEC-section-ids.md), and adding a source must not retire one.
    §2651 and §2737 are the two this applies to.
    """
    by_explicit = explicit_holders(greek_topics)
    attached = {entry["n"]: entry for entry in audit["hubsAttached"]}
    for n in hub_sections(sections, counts):
        holders = by_explicit.get(n, [])
        if not holders:
            continue
        for topic in holders:
            record_hub(topic, n)
        slugs = sorted(t["slug"] for t in holders)
        if n in attached:
            attached[n]["topics"] = sorted(attached[n]["topics"] + slugs)
        else:
            audit["hubsAttached"].append(
                {"n": n, "inboundSyntax": counts[n][1], "topics": slugs}
            )
    audit["hubsAttached"].sort(key=lambda entry: entry["n"])


def resolve_cross_ref(ref: str, by_fold: dict[str, str]) -> str | None:
    key = fold_name(ref)
    if key in by_fold:
        return by_fold[key]
    # The print index abbreviates and pluralises freely ("Compound adj.",
    # "Conditional clauses" for the "Conditional" entry).
    if key.endswith("s") and key[:-1] in by_fold:
        return by_fold[key[:-1]]
    if key + "s" in by_fold:
        return by_fold[key + "s"]
    return None


def finish_topics(
    topics: list[dict],
    sections: dict[int, dict],
    counts: dict[int, tuple[int, int]],
    audit: dict,
) -> list[dict]:
    # Two maps. An English index "See ..." points inside the English index, so
    # it resolves against the three sources that were here before the Greek
    # index arrived and a Greek headword can never become its answer; adding
    # the fourth source therefore leaves every existing `related` list alone.
    # A Greek entry's cross-reference sees everything, itself included.
    core = [t for t in topics if "index-greek" not in t["sources"]]
    by_fold: dict[str, str] = {}
    for t in core:
        by_fold.setdefault(fold_name(t["name"]), t["slug"])
    for t in core:
        for alias in t["aliases"]:
            by_fold.setdefault(fold_name(alias), t["slug"])
    with_greek = dict(by_fold)
    for t in topics:
        if "index-greek" in t["sources"]:
            with_greek.setdefault(fold_name(t["name"]), t["slug"])
    for t in topics:
        if "index-greek" in t["sources"]:
            for alias in t["aliases"]:
                with_greek.setdefault(fold_name(alias), t["slug"])
    for topic in topics:
        members = expand(topic["sections"], sections)
        citers: set[int] = set()
        for n in members:
            for cited_by in sections[n].get("citedBy", []):
                m = ref_number(cited_by)
                if m is not None and m in sections and m not in members:
                    citers.add(m)
        syntax_citers = {m for m in citers if sections[m]["path"][0] == SYNTAX_PART}
        topic["hub"] = {
            "inbound": len(citers),
            "inboundSyntax": len(syntax_citers),
            "hubSections": sorted(topic.pop("_hubSections", [])),
        }
        anchors = []
        for entry in topic["sections"]:
            row = sections[entry["n"]]
            inbound, syntax = counts[entry["n"]]
            anchors.append(
                {
                    "n": entry["n"],
                    **({"to": entry["to"]} if "to" in entry else {}),
                    "head": row["head"],
                    "path": row["path"],
                    "inbound": inbound,
                    "inboundSyntax": syntax,
                }
            )
        topic["anchors"] = anchors
        related = []
        names = with_greek if "index-greek" in topic["sources"] else by_fold
        for ref in topic.pop("_crossRefs"):
            slug = resolve_cross_ref(ref, names)
            if slug is None:
                audit["unresolvedCrossRefs"].append({"topic": topic["slug"], "see": ref})
            elif slug != topic["slug"] and slug not in related:
                related.append(slug)
        topic["related"] = sorted(related)
        topic.pop("_qualifiers")
        topic.pop("_nameSource")
    topics.sort(key=lambda t: t["slug"])
    return topics


def alias_refless_entries(topics: list[dict], audit: dict) -> None:
    """An index entry with no section refs and one resolvable cross-reference
    ("Mutes. See Stops") is an alias of the topic it points at.

    English entries only, and they land on English, construction and hub
    topics only: a Greek headword is not what an English "See" is pointing at,
    and letting one answer would rewrite records the Greek index has no
    business in."""
    topics = [t for t in topics if "index-greek" not in t["sources"]]
    by_fold = {fold_name(t["name"]): t for t in topics}
    by_slug = {t["slug"]: t for t in topics}
    remaining = []
    for entry in audit["indexEntriesWithoutSections"]:
        targets = []
        for ref in entry["crossRefs"]:
            slug = resolve_cross_ref(ref, {k: t["slug"] for k, t in by_fold.items()})
            if slug is not None:
                targets.append(by_slug[slug])
        if len(targets) == 1:
            target = targets[0]
            if entry["headword"] not in target["aliases"] and entry["headword"] != target["name"]:
                target["aliases"] = sorted(target["aliases"] + [entry["headword"]], key=fold_name)
            audit["aliasesFromCrossRefs"].append(
                {"headword": entry["headword"], "slug": target["slug"]}
            )
        else:
            remaining.append(entry)
    audit["indexEntriesWithoutSections"] = remaining


# --------------------------------------------------------------------------
# The Greek index
# --------------------------------------------------------------------------


def greek_head_form(headword: str) -> str:
    """The headword without its parenthetical. The Greek index prints the
    parenthesis as a gloss, a dialect note or a variant spelling ("ἄν (for
    ἀνά, prep.)", "ᾱ (Dor., Aeol.) for η", "εἰς (ἐς)"), never as part of the
    word, so it names the record but does not shape the slug."""
    return re.sub(r"\([^)]*\)", " ", headword)


def is_alphabet_letter(headword: str) -> bool:
    """True when the headword is a single Greek letter carrying no breathing.
    Every Greek word beginning with a vowel is printed with a breathing, so a
    bare letter is the letter itself: Α, ᾱ, ῃ, Β, ν. ἤ, ἦ, ᾗ, ὁ, ὅ, ὦ and ἕ
    carry one and are words."""
    nfd = unicodedata.normalize("NFD", headword.strip())
    bases = [ch for ch in nfd if not unicodedata.combining(ch)]
    if len(bases) != 1:
        return False
    letter = bases[0]
    if letter.lower() not in GREEK_TO_LATIN and letter not in ("Ϝ", "ϝ"):
        return False
    return not any(ch in (SMOOTH_BREATHING, ROUGH_BREATHING) for ch in nfd)


def greek_sections(entry: dict, sections: dict[int, dict]) -> list[dict]:
    """The sections an entry's refs land on. An `anchor` is a lettered
    subdivision of a section ("885. 1", "476 b"); the section is what a topic
    covers, so the anchor is dropped here and kept in the provenance `raw`."""
    cited: list[dict] = []
    for ref in entry.get("refs", []):
        if ref.get("nonSection"):
            continue
        n = ref.get("n")
        if not isinstance(n, int) or n not in sections:
            continue
        to = ref.get("to")
        if isinstance(to, int) and to in sections and to >= n:
            cited.append({"n": n, "to": to})
        else:
            cited.append({"n": n})
    return normalise_sections(cited)


def topics_from_index_greek(
    doc: dict, sections: dict[int, dict], taken: set[str], audit: dict
) -> list[dict]:
    """One topic per Greek headword, named as the print names it.

    Entries printing the same headword are one topic, matched on the exact
    string: transliteration folds ὅς, ὡς and ὥς together and ἦ onto ἤ, and
    close is not a match. The slug is the transliteration of the headword
    without its parenthetical; when that slug is already held, by an existing
    topic or by another Greek headword that transliterates the same way, the
    entry's first section number qualifies it (`hope-346`), the bare slug
    going to the headword with the most sections and, if that ties, the one
    the print gives first.
    """
    groups: dict[str, list[dict]] = {}
    order: list[str] = []
    for entry in doc["entries"]:
        headword = entry["headword"].strip()
        if is_alphabet_letter(headword):
            audit["indexGreekExcluded"].append(
                {"headword": headword, "reason": GREEK_EXCLUDE_LETTER, "raw": entry["raw"]}
            )
            continue
        if not greek_sections(entry, sections):
            audit["indexGreekExcluded"].append(
                {
                    "headword": headword,
                    "reason": GREEK_EXCLUDE_NO_SECTIONS,
                    "raw": entry["raw"],
                    "crossRefs": entry.get("crossRefs", []),
                }
            )
            continue
        if headword not in groups:
            groups[headword] = []
            order.append(headword)
        groups[headword].append(entry)

    records: list[dict] = []
    for position, headword in enumerate(order):
        entries = groups[headword]
        cited = normalise_sections(
            [s for entry in entries for s in greek_sections(entry, sections)]
        )
        transliteration = fold_name(greek_head_form(headword))
        # Sorted on the fold and then on the string itself: the index's search
        # keys for one entry can fold together ("-η-" and "-ε-" are both "e"),
        # and a tie broken by nothing is a tie broken by the hash seed.
        aliases = sorted(
            ({transliteration} | {k for entry in entries for k in entry.get("searchKeys", [])})
            - {headword},
            key=lambda alias: (fold_name(alias), alias),
        )
        records.append(
            {
                "slug": "",
                "name": headword,
                "aliases": aliases,
                "sections": cited,
                "sources": ["index-greek"],
                "hub": {},
                "anchors": [],
                "related": [],
                "provenance": {
                    "indexEntries": [],
                    "constructions": [],
                    "indexGreek": [
                        {
                            "headword": headword,
                            "raw": entry["raw"],
                            "pages": entry["pages"],
                        }
                        for entry in entries
                    ],
                },
                "_nameSource": "index-greek",
                "_crossRefs": sorted({r for entry in entries for r in entry.get("crossRefs", [])}),
                "_qualifiers": [],
                "_base": slugify(greek_head_form(headword)),
                "_rank": (-len(expand(cited, sections)), position),
            }
        )

    assign_greek_slugs(records, taken, audit)
    for record in records:
        record.pop("_base")
        record.pop("_rank")
    return records


def assign_greek_slugs(records: list[dict], taken: set[str], audit: dict) -> None:
    """The bare transliteration where it is free, else qualified by the first
    section the topic cites, else numbered. `taken` is every slug the other
    three sources hold, so no existing slug moves."""
    held = set(taken)
    by_base: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        by_base[record["_base"]].append(record)
    for base in sorted(by_base):
        members = sorted(by_base[base], key=lambda r: r["_rank"])
        for record in members:
            candidate = base
            if candidate in held:
                candidate = f"{base}-{record['sections'][0]['n']}"
            if candidate in held:
                i = 2
                while f"{candidate}-{i}" in held:
                    i += 1
                candidate = f"{candidate}-{i}"
            if candidate != base:
                audit["greekSlugCollisions"].append(
                    {"headword": record["name"], "base": base, "slug": candidate}
                )
            record["slug"] = candidate
            held.add(candidate)


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def build(
    sections_path: Path,
    index_path: Path,
    constructions_path: Path,
    index_greek_path: Path,
) -> dict:
    sections = load_sections(sections_path)
    index_doc = json.loads(index_path.read_text(encoding="utf-8"))
    constructions_doc = json.loads(constructions_path.read_text(encoding="utf-8"))
    index_greek_doc = json.loads(index_greek_path.read_text(encoding="utf-8"))
    counts = inbound_counts(sections)

    audit: dict = {
        "indexEntriesWithoutSections": [],
        "aliasesFromCrossRefs": [],
        "unresolvedCrossRefs": [],
        "merges": [],
        "hubsAttached": [],
        "hubsStandalone": [],
        "indexGreekExcluded": [],
        "greekSlugCollisions": [],
    }

    seeds = seeds_from_index(index_doc, sections, audit)
    seeds += seeds_from_constructions(constructions_doc, sections)
    clusters = merge_seeds(seeds, sections, audit)
    topics = [make_topic(c, sections) for c in clusters]
    assign_slugs(topics)
    topics = attach_hubs(topics, sections, counts, audit)
    greek = topics_from_index_greek(
        index_greek_doc, sections, {t["slug"] for t in topics}, audit
    )
    attach_hubs_greek(greek, sections, counts, audit)
    topics = finish_topics(topics + greek, sections, counts, audit)
    alias_refless_entries(topics, audit)

    top_hubs = sorted(sections, key=lambda n: (-counts[n][1], n))[:20]
    meta = {
        "work": "smyth",
        "inputs": {
            "sections": sections_path.name,
            "indexEnglish": index_path.name,
            "constructions": constructions_path.name,
            "indexGreek": index_greek_path.name,
        },
        "attribution": {
            "constructions": (
                "Construction names come from Celano, Giuseppe G. A. 2014. Guidelines "
                "for the annotation of the Ancient Greek Dependency Treebank 2.0. "
                "https://github.com/PerseusDL/treebank_data/edit/master/AGDT2/guidelines "
                "Copyright 2014 The Perseus Digital Library, Tufts University. "
                "CC BY-SA 3.0 US. See SPEC-constructions.md."
            ),
            "indexEnglish": "Smyth, A Greek Grammar for Colleges (1920), English Index.",
            "indexGreek": "Smyth, A Greek Grammar for Colleges (1920), Greek Index.",
        },
        "rules": {
            "jaccardMerge": JACCARD_MERGE,
            "hubMinSyntax": HUB_MIN_SYNTAX,
            "constructionKinds": list(CONSTRUCTION_KINDS),
            "syntaxPart": SYNTAX_PART,
            "greekMerge": (
                "Greek entries printing the same headword are one topic, matched on "
                "the exact string; a Greek topic never merges with an English "
                "headword, a construction or another Greek headword"
            ),
            "greekSlug": (
                "the transliteration of the headword without its parenthetical; when "
                "that slug is held, by an existing topic or by a Greek headword that "
                "transliterates the same way and covers more sections, the topic's "
                "first section number qualifies it"
            ),
            "greekExclusions": {
                GREEK_EXCLUDE_LETTER: (
                    "the headword is one Greek letter carrying no breathing, so the "
                    "entry is about the letter: its pronunciation, its quantity, what "
                    "it becomes before another consonant"
                ),
                GREEK_EXCLUDE_NO_SECTIONS: (
                    "the entry cites no section, being a bare cross-reference"
                ),
            },
        },
        "counts": {
            "topics": len(topics),
            "bySource": {
                key: sum(1 for t in topics if key in t["sources"])
                for key in ("index-english", "index-greek", "constructions", "hub")
            },
            "withAliases": sum(1 for t in topics if t["aliases"]),
            "merged": sum(
                1 for t in topics if {"index-english", "constructions"} <= set(t["sources"])
            ),
            "hubSections": len({n for t in topics for n in t["hub"]["hubSections"]}),
            "hubSectionsStandalone": len(audit["hubsStandalone"]),
            "indexEntriesSeeded": sum(len(t["provenance"]["indexEntries"]) for t in topics),
            "constructionEntriesSeeded": sum(len(t["provenance"]["constructions"]) for t in topics),
            "indexGreekEntriesSeeded": sum(
                len(t["provenance"].get("indexGreek", [])) for t in topics
            ),
            "indexGreekEntriesExcluded": {
                reason: sum(
                    1 for e in audit["indexGreekExcluded"] if e["reason"] == reason
                )
                for reason in (GREEK_EXCLUDE_LETTER, GREEK_EXCLUDE_NO_SECTIONS)
            },
        },
        "topHubsSyntax": [
            {
                "n": n,
                "head": sections[n]["head"],
                "inbound": counts[n][0],
                "inboundSyntax": counts[n][1],
            }
            for n in top_hubs
        ],
        "audit": audit,
    }
    return {"meta": meta, "topics": topics}


# --------------------------------------------------------------------------
# The join read backwards
# --------------------------------------------------------------------------

# How many topic records section-topics.json names in its meta, widest
# coverage first, so a reader sees at once which records are broad.
BROADEST_REPORTED = 25


def coverage(topics: list[dict], sections: dict[int, dict]) -> dict[str, set[int]]:
    """slug -> the sections the topic covers, ranges expanded. A record citing
    {"n": 2249, "to": 2278} covers every section in that range. hub.hubSections
    add nothing: a hub is recorded only on a topic that already cites it as a
    section or as a range start."""
    return {t["slug"]: expand(t["sections"], sections) for t in topics}


def section_topics(topics: list[dict], sections: dict[int, dict]) -> list[dict]:
    """One row per section in sections.jsonl, in section order, carrying the
    slugs of every topic that covers it, sorted by slug. A section no topic
    covers gets an empty list."""
    covers = coverage(topics, sections)
    by_section: dict[int, list[str]] = defaultdict(list)
    for slug in sorted(covers):
        for n in covers[slug]:
            by_section[n].append(slug)
    return [{"n": n, "topics": by_section.get(n, [])} for n in sorted(sections)]


def build_section_topics(
    topics: list[dict],
    sections: dict[int, dict],
    sections_path: Path,
    topics_path: Path,
) -> dict:
    rows = section_topics(topics, sections)
    covers = coverage(topics, sections)
    histogram: dict[int, int] = defaultdict(int)
    for row in rows:
        histogram[len(row["topics"])] += 1
    widest = sorted(covers.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    meta = {
        "work": "smyth",
        "inputs": {"sections": sections_path.name, "topics": topics_path.name},
        "rules": {
            "join": (
                "a topic covers a section when the section falls in one of the "
                "topic's sections entries, ranges expanded end to end"
            ),
            "sort": "rows in section order; slugs sorted ascending",
            "coverageThreshold": None,
            "coverageThresholdNote": (
                "No record is dropped for covering too much. Smyth's own index "
                "headwords carry book-sized ranges (Verbs covers 1,026 sections, "
                "Syntax 542), and on those sections the slug says little that the "
                "section's own path does not; but every threshold that removes "
                "them also strips hundreds of sections of every topic they have, "
                "and picking one would be the hand-built ontology SPEC-topics.md "
                "refuses. broadestTopics below lets a renderer rank or filter."
            ),
        },
        "counts": {
            "sections": len(rows),
            "sectionsWithTopics": sum(1 for row in rows if row["topics"]),
            "sectionsWithoutTopics": sum(1 for row in rows if not row["topics"]),
            "assignments": sum(len(row["topics"]) for row in rows),
            "maxTopicsOnASection": max(len(row["topics"]) for row in rows),
            "distribution": [
                {"topics": k, "sections": histogram[k]} for k in sorted(histogram)
            ],
        },
        "broadestTopics": [
            {"slug": slug, "sections": len(members)}
            for slug, members in widest[:BROADEST_REPORTED]
        ],
        "mostCoveredSections": [
            {
                "n": row["n"],
                "topics": len(row["topics"]),
                "head": sections[row["n"]]["head"],
                "path": sections[row["n"]]["path"],
            }
            for row in sorted(rows, key=lambda r: (-len(r["topics"]), r["n"]))[:10]
        ],
    }
    return {"meta": meta, "sections": rows}


def write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sections", type=Path, default=DEFAULT_SECTIONS)
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--constructions", type=Path, default=DEFAULT_CONSTRUCTIONS)
    parser.add_argument("--index-greek", type=Path, default=DEFAULT_INDEX_GREEK)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--out-sections", type=Path, default=DEFAULT_OUT_SECTIONS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    doc = build(args.sections, args.index, args.constructions, args.index_greek)
    write_json(args.out, doc)
    counts = doc["meta"]["counts"]
    print(
        f"wrote {args.out}: {counts['topics']} topics "
        f"(index-english {counts['bySource']['index-english']}, "
        f"index-greek {counts['bySource']['index-greek']}, "
        f"constructions {counts['bySource']['constructions']}, "
        f"hub {counts['bySource']['hub']}; merged {counts['merged']})"
    )
    sections = load_sections(args.sections)
    reverse = build_section_topics(doc["topics"], sections, args.sections, args.out)
    write_json(args.out_sections, reverse)
    rcounts = reverse["meta"]["counts"]
    print(
        f"wrote {args.out_sections}: {rcounts['sections']} sections "
        f"({rcounts['sectionsWithTopics']} with a topic, "
        f"{rcounts['sectionsWithoutTopics']} without; "
        f"{rcounts['assignments']} assignments, "
        f"at most {rcounts['maxTopicsOnASection']} on one section)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
