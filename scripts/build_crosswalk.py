#!/usr/bin/env python3
"""Build data/smyth/crosswalk.json: for each derived Smyth topic, the sections
of the other grammars that treat the same phenomenon, with a score and the
evidence, so a topic page can print "Smyth §§2070-2075; GMT §§847-851;
Goodell §§589-590".

Nothing here is a hand-built mapping. Four kinds of evidence, all from data
the repo owns:

  heading        the topic's name and aliases against each other grammar's
                 section head and the ancestors in its path, after
                 normalisation (lowercase, diacritics and Greek folded to
                 ASCII, stopwords out, plurals singularised, a few
                 metalanguage variants folded). Scored as the coverage of
                 the topic's tokens by the head, weighted by the share of
                 the head accounted for; a path ancestor counts at 0.8.
  goodell-index  Goodell's own English index: a headword identical (after
                 the same folding, plural tolerated) to the topic's name or
                 an alias, and the sections that entry cites.
  greek-terms    the Greek words of the topic's anchor sections in Smyth
                 against each section of the other Greek grammars, as the
                 cosine of tf-idf vectors, pooled over the topic or for the
                 best single anchor section. Function words are excluded by
                 their document frequency: any token in more than
                 FUNCTION_WORD_DF of all Greek-grammar sections. The shared
                 terms must carry SHARED_MIN_IDF nats between them.
  citation       a section in another grammar whose text cites Smyth by
                 number inside the topic, or a Smyth section inside the
                 topic that cites the other grammar by number. A section
                 citing a section that is itself a kept candidate for the
                 topic gets a discounted "citation-chain" hit.

A section's score is the sum of its evidence scores. Sections at or above
KEEP_MIN are kept; consecutive kept sections of one work coalesce into one
candidate carrying the union of the evidence and the sections each piece
fired on, and the best MAX_PER_WORK candidates per work are written.

The Latin grammars (ag, bennett) are a different language: only the heading
evidence applies to them, and only an exact match (token sets equal). They
never get Greek-term or index evidence, so "Genitive absolute" cannot reach
"Ablative Absolute".

Python stdlib only. Deterministic: sorted output, rounded scores, no
timestamps. Verified by scripts/verify_crosswalk.py.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_topics import fold_name  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DEFAULT_TOPICS = DATA / "smyth" / "topics.json"
DEFAULT_OUT = DATA / "smyth" / "crosswalk.json"

# Topic records seeded by the Greek index are out of scope here. Every
# evidence kind below was designed and its precision measured on topics with
# an English name (SPEC-crosswalk.md); a headword like ἄν or ὥστε would be
# scored by rules nobody has read the output of yet. SPEC-topics.md records it
# as owed work.
SKIP_SOURCE = "index-greek"

GREEK_WORKS = ["goodwin-gmt", "gildersleeve", "monro", "goodell"]
LATIN_WORKS = ["ag", "bennett"]
WORK_LABELS = {
    "goodwin-gmt": "GMT",
    "gildersleeve": "Gildersleeve",
    "monro": "Monro",
    "goodell": "Goodell",
    "ag": "A&G",
    "bennett": "Bennett",
}

# A section is kept when the sum of its evidence reaches this. An exact
# heading, an index headword or a citation each score 1.0 and pass alone. A
# partial heading (topic "Absolute" against "Genitive Absolute." is 0.667)
# passes only with corroboration: a Greek-term score of at least 0.083, that
# is a cosine of 0.07 above the floor. Greek terms alone need a cosine of
# 0.30 or better.
KEEP_MIN = 0.75
# Consecutive kept sections of one work form one candidate; this many
# candidates per work are written, best first.
MAX_PER_WORK = 5
# Heading evidence: a path ancestor (the chapter a section sits in) is
# discounted against the section's own head.
ANCESTOR_WEIGHT = 0.8
# Greek-term evidence: cosine below the floor is noise between any two
# sections that quote Greek; cosine at the ceiling is full evidence.
GREEK_FLOOR = 0.05
GREEK_CEILING = 0.35
# A Greek token found in more than this fraction of all Greek-grammar
# sections is a function word (articles, καί, δέ, ἄν, οὐ, μή, εἰ, ὡς ...).
FUNCTION_WORD_DF = 0.05
# The Greek-term cosine is the better of the pooled topic vector and the
# best single anchor section. Either counts only when the shared terms
# together carry this much surprise (the sum of their idf, in nats): two
# short sections that both mention ἀμφί, ὑπέρ and ὑπό have cosine 0.66 and
# idf sum 10; four terms each rarer than one section in a hundred reach 18.
SHARED_MIN_IDF = 18.0
MIN_GREEK_TOKEN_LEN = 2
# A citation of a section that is itself a kept candidate.
CHAIN_WEIGHT = 0.5

SYNTAX_PART = "Part IV: Syntax"

STOPWORDS = {
    "a", "an", "the", "of", "and", "or", "with", "in", "on", "to", "for",
    "by", "as", "at", "from", "into", "its", "it", "is", "are", "be", "than",
    "that", "this", "these", "those", "etc", "use", "uses", "used", "general",
    "remark", "remarks", "chapter", "part", "section", "i", "ii", "iii", "iv",
    "v", "vi", "vii", "viii", "ix", "x", "xi", "xii", "kind", "kinds", "other",
    "same", "so", "when", "also", "see", "sq", "ff",
}

# Metalanguage variants folded to one token. The grammars' own headings and
# Goodell's index abbreviate and vary ("Temporal Sentences", "Optative mode",
# "Dubitative subjv"); this is spelling normalisation, not a topic mapping.
SYNONYMS = {
    "sentence": "clause",
    "mode": "mood",
    "subjv": "subjunctive",
    "subj": "subjunctive",
    "indic": "indicative",
    "opt": "optative",
    "imperat": "imperative",
    "infin": "infinitive",
    "inf": "infinitive",
    "partic": "participle",
    "adj": "adjective",
    "adv": "adverb",
    "gen": "genitive",
    "dat": "dative",
    "acc": "accusative",
    "nom": "nominative",
    "voc": "vocative",
    "interrog": "interrogative",
    "indir": "indirect",
    "rel": "relative",
    "pron": "pronoun",
    "prep": "preposition",
    "conj": "conjunction",
    "compar": "comparative",
    "superl": "superlative",
    "aor": "aorist",
    "perf": "perfect",
    "impf": "imperfect",
    "fut": "future",
    "pres": "present",
    "pass": "passive",
    "mid": "middle",
    "act": "active",
}

GREEK_TOKEN = re.compile(r"[Ͱ-Ͽἀ-῿]+")
LEADING_NUMBERING = re.compile(
    r"^\s*(?:(?:section|chapter)\s+)?(?:[ivxlc]+|\d+|[a-z])[.:)]\s*", re.IGNORECASE
)

# Explicit citations. Each pattern's first group is the cited section
# number and the optional second group the end of a cited range. The section
# sign is required: Smyth's "Goodwin Moods and Tenses 389" (§2758) is a page
# of the 1889 appendix on οὐ μή, not a section, and journal references
# ("Gildersleeve American Journal of Philology 3. 202") carry numbers too. A
# bare "Goodwin, § 28" is accepted because Monro cites Moods and Tenses that
# way; a number the target work does not have is dropped, which is what
# happens to citations of Goodwin's Greek Grammar.
SECTION_REF = r"[^0-9]{0,30}?§§?\s*(\d+)(?:\s*[-–]\s*(\d+))?"
CITATION_PATTERNS = {
    "smyth": [re.compile(r"\bSmyth\b" + SECTION_REF)],
    "goodwin-gmt": [
        re.compile(
            r"(?:\bGoodwin(?:'s)?\b(?:,?\s*(?:Moods\s+and\s+Tenses|M\.\s?T\.))?"
            r"|\bG\.\s?M\.\s?T\.)" + SECTION_REF
        )
    ],
    "gildersleeve": [re.compile(r"\bGildersleeve\b" + SECTION_REF)],
    "monro": [re.compile(r"(?:\bMonro\b|Homeric\s+Grammar|\bH\.\s?G\.)" + SECTION_REF)],
    "goodell": [re.compile(r"\bGoodell\b" + SECTION_REF)],
}


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------


def load_sections(work: str) -> dict[int, dict]:
    rows: dict[int, dict] = {}
    with (DATA / work / "sections.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                row = json.loads(line)
                if isinstance(row.get("n"), int):
                    rows[row["n"]] = row
    return rows


def section_text(row: dict) -> str:
    parts = [row.get("plain", "")]
    for note in row.get("notes", []):
        parts.append(note.get("plain", ""))
    return " ".join(parts)


# --------------------------------------------------------------------------
# Normalisation
# --------------------------------------------------------------------------


def singular(token: str) -> str:
    if len(token) <= 3:
        return token
    if token.endswith("ies"):
        return token[:-3] + "y"
    if token.endswith(("ses", "xes", "zes", "ches", "shes")):
        return token[:-2]
    if token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


def heading_tokens(text: str) -> tuple[str, ...]:
    """Normalised token set of a heading or topic name, as a sorted tuple."""
    text = LEADING_NUMBERING.sub("", text)
    text = LEADING_NUMBERING.sub("", text)
    out = set()
    for tok in fold_name(text).split():
        if tok in STOPWORDS or tok.isdigit():
            continue
        tok = SYNONYMS.get(tok, tok)
        tok = singular(tok)
        tok = SYNONYMS.get(tok, tok)
        if tok in STOPWORDS or len(tok) < 2:
            continue
        out.add(tok)
    return tuple(sorted(out))


def fold_greek(token: str) -> str:
    nfd = unicodedata.normalize("NFD", token)
    return "".join(c for c in nfd if not unicodedata.combining(c)).lower().replace("ς", "σ")


def greek_tokens(text: str) -> list[str]:
    return [
        fold_greek(t) for t in GREEK_TOKEN.findall(text) if len(t) >= MIN_GREEK_TOKEN_LEN
    ]


def heading_score(topic: tuple[str, ...], head: tuple[str, ...]) -> tuple[float, list[str]]:
    """coverage of the topic's tokens by the head, weighted by how much of
    the head that accounts for: 1.0 when the sets are equal; 0.75 when a
    one-word topic sits inside a two-word head ("Absolute" in "Genitive
    Absolute"); 0.5 when a two-word topic meets a one-word head ("Genitive
    absolute" against "Genitive"), which is the coarser section."""
    shared = sorted(set(topic) & set(head))
    if not shared:
        return 0.0, []
    coverage = len(shared) / len(topic)
    precision = len(shared) / len(head)
    return coverage * (0.5 + 0.5 * precision), shared


# --------------------------------------------------------------------------
# Other-grammar side: per-section features
# --------------------------------------------------------------------------


class Work:
    def __init__(self, slug: str, sections: dict[int, dict], latin: bool):
        self.slug = slug
        self.latin = latin
        self.sections = sections
        self.order = sorted(sections)
        # (string, tokens, weight) per section: the head at 1.0, each distinct
        # path ancestor at ANCESTOR_WEIGHT.
        self.heading_strings: dict[int, list[tuple[str, tuple[str, ...], float]]] = {}
        self.greek_counts: dict[int, Counter] = {}
        for n, row in sections.items():
            strings: list[tuple[str, tuple[str, ...], float]] = []
            seen = set()
            head = row["head"]
            strings.append((head, heading_tokens(head), 1.0))
            seen.add(head)
            for ancestor in row["path"][:-1] if row["path"] and row["path"][-1] == head else row["path"]:
                if ancestor not in seen:
                    seen.add(ancestor)
                    strings.append((ancestor, heading_tokens(ancestor), ANCESTOR_WEIGHT))
            self.heading_strings[n] = [s for s in strings if s[1]]
            if not latin:
                self.greek_counts[n] = Counter(greek_tokens(section_text(row)))


def build_idf(
    works: list[Work], smyth: dict[int, dict]
) -> tuple[dict[str, float], set[str], int, dict[int, Counter]]:
    """idf over every section of every Greek grammar, Smyth included, the
    function-word set (tokens above FUNCTION_WORD_DF of sections), the
    section count, and Smyth's own per-section Greek token counts."""
    df: Counter = Counter()
    total = 0
    for work in works:
        if work.latin:
            continue
        for counts in work.greek_counts.values():
            df.update(counts.keys())
            total += 1
    smyth_counts = {n: Counter(greek_tokens(section_text(row))) for n, row in smyth.items()}
    for counts in smyth_counts.values():
        df.update(counts.keys())
        total += 1
    function_words = {t for t, c in df.items() if c > FUNCTION_WORD_DF * total}
    idf = {t: math.log(total / c) for t, c in df.items() if t not in function_words}
    return idf, function_words, total, smyth_counts


def tfidf(counts: Counter, idf: dict[str, float]) -> dict[str, float]:
    vec = {}
    for t, c in counts.items():
        w = idf.get(t)
        if w is not None:
            vec[t] = (1 + math.log(c)) * w
    norm = math.sqrt(sum(v * v for v in vec.values()))
    return {t: v / norm for t, v in vec.items()} if norm else {}


# --------------------------------------------------------------------------
# Evidence
# --------------------------------------------------------------------------


def topic_sections(topic: dict, smyth: dict[int, dict]) -> list[int]:
    out = set()
    for entry in topic["sections"]:
        for n in range(entry["n"], entry.get("to", entry["n"]) + 1):
            if n in smyth:
                out.add(n)
    return sorted(out)


def topic_names(topic: dict) -> list[tuple[str, tuple[str, ...]]]:
    names = []
    seen = set()
    for name in [topic["name"]] + topic["aliases"]:
        toks = heading_tokens(name)
        if toks and toks not in seen:
            seen.add(toks)
            names.append((name, toks))
    return names


def heading_evidence(
    names: list[tuple[str, tuple[str, ...]]], work: Work
) -> dict[int, tuple[float, dict]]:
    """n -> (score, evidence) for every section with any shared token."""
    out: dict[int, tuple[float, dict]] = {}
    for n in work.order:
        best: tuple[float, dict] | None = None
        for string, toks, weight in work.heading_strings[n]:
            for name, ntoks in names:
                if work.latin:
                    if weight < 1.0 or toks != ntoks:
                        continue
                    score, shared = 1.0, list(ntoks)
                else:
                    score, shared = heading_score(ntoks, toks)
                    score *= weight
                if score > 0 and (best is None or score > best[0]):
                    best = (
                        score,
                        {
                            "kind": "heading",
                            "topicString": name,
                            "sectionString": string,
                            "ancestor": weight < 1.0,
                            "matched": shared,
                        },
                    )
        if best is not None:
            out[n] = best
    return out


def goodell_index_map(index_doc: dict) -> dict[str, list[dict]]:
    """folded headword -> entries (headword, raw, sections)."""
    out: dict[str, list[dict]] = defaultdict(list)
    for entry in index_doc["entries"]:
        secs = sorted(
            {r["n"] for r in entry.get("refs", []) if isinstance(r.get("n"), int)}
        )
        if not secs:
            continue
        out[fold_name(entry["headword"])].append(
            {"headword": entry["headword"], "raw": entry["raw"], "sections": secs}
        )
    return out


def index_evidence(topic: dict, index_map: dict[str, list[dict]]) -> dict[int, tuple[float, dict]]:
    out: dict[int, tuple[float, dict]] = {}
    for name in [topic["name"]] + topic["aliases"]:
        key = fold_name(name)
        keys = [key]
        if key.endswith("s"):
            keys.append(key[:-1])
        else:
            keys.append(key + "s")
        for k in keys:
            for entry in index_map.get(k, []):
                for n in entry["sections"]:
                    if n not in out:
                        out[n] = (
                            1.0,
                            {
                                "kind": "goodell-index",
                                "topicString": name,
                                "headword": entry["headword"],
                                "raw": entry["raw"],
                            },
                        )
    return out


def find_citations(text: str, target: str, exists: dict[int, dict]) -> list[tuple[int, str]]:
    hits = []
    for pattern in CITATION_PATTERNS.get(target, []):
        for m in pattern.finditer(text):
            start = int(m.group(1))
            end = int(m.group(2)) if m.group(2) else start
            if end < start or end - start > 60:
                end = start
            for n in range(start, end + 1):
                if n in exists:
                    hits.append((n, m.group(0).strip()))
    return hits


class Citations:
    """Every explicit section citation between the works, found once."""

    def __init__(self, smyth: dict[int, dict], works: list[Work]):
        by_slug = {w.slug: w for w in works}
        # other work section -> [(smyth n, matched string)]
        self.to_smyth: dict[str, dict[int, list[tuple[int, str]]]] = defaultdict(dict)
        # smyth n -> {work slug: [(n, matched)]}
        self.from_smyth: dict[int, dict[str, list[tuple[int, str]]]] = defaultdict(dict)
        # (citing work, n) -> {target work: [(n, matched)]}
        self.between: dict[tuple[str, int], dict[str, list[tuple[int, str]]]] = defaultdict(dict)
        self.count = Counter()
        for n, row in smyth.items():
            text = section_text(row)
            for work in works:
                if work.latin:
                    continue
                hits = find_citations(text, work.slug, work.sections)
                if hits:
                    self.from_smyth[n][work.slug] = hits
                    self.count[f"smyth->{work.slug}"] += len(hits)
        for work in works:
            if work.latin:
                continue
            for n, row in work.sections.items():
                text = section_text(row)
                hits = find_citations(text, "smyth", smyth)
                if hits:
                    self.to_smyth[work.slug][n] = hits
                    self.count[f"{work.slug}->smyth"] += len(hits)
                for other in works:
                    if other.latin or other.slug == work.slug:
                        continue
                    hits = find_citations(text, other.slug, other.sections)
                    if hits:
                        self.between[(work.slug, n)][other.slug] = hits
                        self.count[f"{work.slug}->{other.slug}"] += len(hits)
        self.works = by_slug


def citation_evidence(
    members: set[int], citations: Citations, work: Work
) -> dict[int, tuple[float, dict]]:
    out: dict[int, tuple[float, dict]] = {}
    for n, hits in citations.to_smyth.get(work.slug, {}).items():
        inside = [(m, s) for m, s in hits if m in members]
        if inside:
            out[n] = (
                1.0,
                {
                    "kind": "cites-smyth",
                    "smythSections": sorted({m for m, _ in inside}),
                    "matched": sorted({s for _, s in inside}),
                },
            )
    for m in sorted(members):
        for n, matched in citations.from_smyth.get(m, {}).get(work.slug, []):
            if n not in out:
                out[n] = (
                    1.0,
                    {"kind": "cited-by-smyth", "smythSections": [m], "matched": [matched]},
                )
            else:
                out[n][1].setdefault("smythSections", [])
    return out


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------


def coalesce(
    work: Work, kept: dict[int, tuple[float, list[dict]]]
) -> list[dict]:
    """Consecutive kept sections (in the work's own order) become one
    candidate. Evidence of one kind and one matched string is merged, with
    the sections it fired on listed."""
    runs: list[list[int]] = []
    prev = None
    for n in work.order:
        if n not in kept:
            prev = None
            continue
        if prev is not None and runs and runs[-1][-1] == prev:
            runs[-1].append(n)
        else:
            runs.append([n])
        prev = n
    candidates = []
    for run in runs:
        merged: dict[tuple, dict] = {}
        for n in run:
            for ev in kept[n][1]:
                key = (
                    ev["kind"],
                    ev.get("topicString"),
                    ev.get("sectionString"),
                    ev.get("headword"),
                    tuple(ev.get("smythSections", [])) if ev["kind"] != "greek-terms" else (),
                    tuple(ev.get("via", [])),
                )
                slot = merged.get(key)
                if slot is None:
                    slot = dict(ev)
                    slot["sections"] = []
                    merged[key] = slot
                slot["sections"].append(n)
                slot["score"] = max(slot["score"], ev["score"])
                if ev["kind"] == "greek-terms":
                    if ev["cosine"] > slot["cosine"]:
                        slot["cosine"] = ev["cosine"]
                        slot["smythSections"] = ev["smythSections"]
                        slot["sharedTerms"] = ev["sharedTerms"]
                        slot["sharedIdf"] = ev["sharedIdf"]
                    slot["terms"] = sorted(set(slot["terms"]) | set(ev["terms"]))[:12]
        evidence = sorted(
            merged.values(),
            key=lambda e: (-e["score"], e["kind"], e["sections"][0], str(e.get("matched", ""))),
        )
        for ev in evidence:
            ev["score"] = round(ev["score"], 3)
            if "cosine" in ev:
                ev["cosine"] = round(ev["cosine"], 3)
        heads = []
        for n in run:
            head = work.sections[n]["head"]
            if head not in heads:
                heads.append(head)
        score = max(kept[n][0] for n in run)
        candidates.append(
            {
                "work": work.slug,
                "label": WORK_LABELS[work.slug],
                "sections": [{"n": run[0]}] if len(run) == 1 else [{"n": run[0], "to": run[-1]}],
                "heads": heads,
                "score": round(score, 3),
                "evidenceKinds": sorted({e["kind"] for e in evidence}),
                "evidence": evidence,
            }
        )
    candidates.sort(key=lambda c: (-c["score"], c["sections"][0]["n"]))
    return candidates[:MAX_PER_WORK]


def score_topic(
    topic: dict,
    smyth: dict[int, dict],
    works: list[Work],
    idf: dict[str, float],
    smyth_counts: dict[int, Counter],
    postings: dict[str, dict[str, list[tuple[int, float]]]],
    index_map: dict[str, list[dict]],
    citations: Citations,
) -> tuple[list[dict], dict]:
    members = topic_sections(topic, smyth)
    member_set = set(members)
    names = topic_names(topic)
    counts: Counter = Counter()
    for n in members:
        counts.update(smyth_counts[n])
    topic_vec = tfidf(counts, idf)
    anchor_vecs = {n: tfidf(smyth_counts[n], idf) for n in members}

    per_work: dict[str, dict[int, tuple[float, list[dict]]]] = {}
    stats = {"greekTerms": len(topic_vec)}
    for work in works:
        section_evidence: dict[int, list[dict]] = defaultdict(list)
        for n, (score, ev) in heading_evidence(names, work).items():
            ev["score"] = round(score, 3)
            section_evidence[n].append(ev)
        if work.latin:
            per_work[work.slug] = {
                n: (sum(e["score"] for e in evs), evs) for n, evs in section_evidence.items()
            }
            continue
        if work.slug == "goodell":
            for n, (score, ev) in index_evidence(topic, index_map).items():
                ev["score"] = score
                section_evidence[n].append(ev)
        for n, (score, ev) in citation_evidence(member_set, citations, work).items():
            ev["score"] = score
            section_evidence[n].append(ev)
        # Greek terms via the postings lists: the pooled topic vector, then
        # each anchor section on its own.
        work_postings = postings[work.slug]
        best: dict[int, tuple[float, str | int, list[tuple[float, str]], float]] = {}
        for label, vec in [("pooled", topic_vec)] + [(n, anchor_vecs[n]) for n in members]:
            dots: dict[int, float] = defaultdict(float)
            shared: dict[int, list[tuple[float, str]]] = defaultdict(list)
            for term, tw in vec.items():
                for n, sw in work_postings.get(term, ()):
                    contribution = tw * sw
                    dots[n] += contribution
                    shared[n].append((contribution, term))
            for n, cosine in dots.items():
                if cosine <= GREEK_FLOOR:
                    continue
                shared_idf = sum(idf[t] for _, t in shared[n])
                if shared_idf < SHARED_MIN_IDF:
                    continue
                if n not in best or cosine > best[n][0]:
                    best[n] = (cosine, label, shared[n], shared_idf)
        for n, (cosine, label, pairs, shared_idf) in best.items():
            score = min(1.0, (cosine - GREEK_FLOOR) / (GREEK_CEILING - GREEK_FLOOR))
            terms = [t for _, t in sorted(pairs, key=lambda p: (-p[0], p[1]))[:8]]
            section_evidence[n].append(
                {
                    "kind": "greek-terms",
                    "score": score,
                    "cosine": cosine,
                    "sharedTerms": len(pairs),
                    "sharedIdf": round(shared_idf, 1),
                    "smythSections": [] if label == "pooled" else [label],
                    "terms": terms,
                }
            )
        per_work[work.slug] = {
            n: (sum(e["score"] for e in evs), evs) for n, evs in section_evidence.items()
        }

    # Citation chains: a section citing a section that is itself kept.
    kept_by_work = {
        slug: {n for n, (score, _) in scored.items() if score >= KEEP_MIN}
        for slug, scored in per_work.items()
    }
    for work in works:
        if work.latin:
            continue
        for n in work.order:
            targets = citations.between.get((work.slug, n))
            if not targets:
                continue
            for other_slug, hits in targets.items():
                via = sorted({m for m, _ in hits if m in kept_by_work.get(other_slug, set())})
                if not via:
                    continue
                ev = {
                    "kind": "citation-chain",
                    "score": CHAIN_WEIGHT,
                    "via": [f"{other_slug}:{m}" for m in via],
                    "matched": sorted({s for m, s in hits if m in via}),
                }
                score, evs = per_work[work.slug].get(n, (0.0, []))
                evs = evs + [ev]
                per_work[work.slug][n] = (score + CHAIN_WEIGHT, evs)

    candidates: list[dict] = []
    for work in works:
        kept = {n: v for n, v in per_work[work.slug].items() if v[0] >= KEEP_MIN}
        candidates.extend(coalesce(work, kept))
    return candidates, stats


def build(topics_path: Path) -> dict:
    topics_doc = json.loads(topics_path.read_text(encoding="utf-8"))
    smyth = load_sections("smyth")
    works = [Work(slug, load_sections(slug), latin=False) for slug in GREEK_WORKS]
    works += [Work(slug, load_sections(slug), latin=True) for slug in LATIN_WORKS]
    index_doc = json.loads((DATA / "goodell" / "index-english.json").read_text(encoding="utf-8"))
    index_map = goodell_index_map(index_doc)

    idf, function_words, total_sections, smyth_counts = build_idf(works, smyth)
    postings: dict[str, dict[str, list[tuple[int, float]]]] = {}
    for work in works:
        if work.latin:
            continue
        work_postings: dict[str, list[tuple[int, float]]] = defaultdict(list)
        for n in work.order:
            for term, w in tfidf(work.greek_counts[n], idf).items():
                work_postings[term].append((n, w))
        postings[work.slug] = work_postings
    citations = Citations(smyth, works)

    out_topics = []
    uncovered = []
    per_work_counts: Counter = Counter()
    kind_counts: Counter = Counter()
    scoped = [t for t in topics_doc["topics"] if SKIP_SOURCE not in t["sources"]]
    for topic in scoped:
        candidates, stats = score_topic(
            topic, smyth, works, idf, smyth_counts, postings, index_map, citations
        )
        greek_hits = [c for c in candidates if c["work"] in GREEK_WORKS]
        for c in candidates:
            per_work_counts[c["work"]] += 1
            for k in c["evidenceKinds"]:
                kind_counts[k] += 1
        syntax_hub = [
            a["n"]
            for a in topic["anchors"]
            if a["n"] in topic["hub"]["hubSections"] and a["path"][0] == SYNTAX_PART
        ]
        if syntax_hub and not greek_hits:
            uncovered.append({"slug": topic["slug"], "name": topic["name"], "hubSections": syntax_hub})
        out_topics.append(
            {
                "slug": topic["slug"],
                "name": topic["name"],
                "aliases": topic["aliases"],
                "smyth": topic["sections"],
                "smythHeads": [a["head"] for a in topic["anchors"]],
                "greekTerms": stats["greekTerms"],
                "candidates": candidates,
            }
        )

    meta = {
        "work": "smyth",
        "inputs": {
            "topics": topics_path.name,
            "topicsScope": (
                "topic records whose sources do not name index-greek: the evidence "
                "kinds below were built and measured on topics with an English name, "
                "and the Greek index headwords are owed a round of their own"
            ),
            "sections": {w: f"data/{w}/sections.jsonl" for w in ["smyth"] + GREEK_WORKS + LATIN_WORKS},
            "goodellIndex": "data/goodell/index-english.json",
        },
        "works": {
            "greek": GREEK_WORKS,
            "latin": LATIN_WORKS,
            "labels": WORK_LABELS,
            "latinRule": (
                "Latin grammars carry heading evidence only, and only an exact match "
                "of the normalised token sets; no Greek-term, index or citation evidence."
            ),
        },
        "rules": {
            "keepMin": KEEP_MIN,
            "maxPerWork": MAX_PER_WORK,
            "ancestorWeight": ANCESTOR_WEIGHT,
            "sharedMinIdf": SHARED_MIN_IDF,
            "greekFloor": GREEK_FLOOR,
            "greekCeiling": GREEK_CEILING,
            "functionWordDf": FUNCTION_WORD_DF,
            "chainWeight": CHAIN_WEIGHT,
            "evidenceKinds": {
                "heading": "coverage of the topic's tokens by the head times (0.5 + 0.5 x share of the head's tokens matched), topic name or alias against section head (x1.0) or path ancestor (x ancestorWeight)",
                "goodell-index": "Goodell index headword identical to the topic name or alias after folding, plural tolerated: 1.0 for each section the entry cites",
                "greek-terms": "cosine of tf-idf vectors of Greek tokens (function words out): the pooled topic vector or one anchor section, whichever is higher, when the shared terms' idf sum reaches sharedMinIdf; rescaled from greekFloor..greekCeiling to 0..1",
                "cites-smyth": "the section's text cites a Smyth section inside the topic: 1.0",
                "cited-by-smyth": "a Smyth section inside the topic cites the section: 1.0",
                "citation-chain": "the section cites a section of another grammar that is itself a kept candidate: chainWeight",
            },
            "stopwords": sorted(STOPWORDS),
            "synonyms": SYNONYMS,
        },
        "counts": {
            "topics": len(out_topics),
            "topicsWithCandidates": sum(1 for t in out_topics if t["candidates"]),
            "topicsWithGreekCandidates": sum(
                1 for t in out_topics if any(c["work"] in GREEK_WORKS for c in t["candidates"])
            ),
            "candidates": sum(len(t["candidates"]) for t in out_topics),
            "byWork": {w: per_work_counts[w] for w in GREEK_WORKS + LATIN_WORKS},
            "byEvidenceKind": dict(sorted(kind_counts.items())),
            "greekSectionsIndexed": total_sections,
            "functionWords": len(function_words),
            "citationsFound": dict(sorted(citations.count.items())),
        },
        "functionWords": sorted(function_words),
        "audit": {
            "uncovered": uncovered,
            "uncoveredNote": (
                "Topics with a hub anchor in Part IV Syntax and no candidate in any "
                "other Greek grammar."
            ),
        },
    }
    return {"meta": meta, "topics": out_topics}


def write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topics", type=Path, default=DEFAULT_TOPICS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    doc = build(args.topics)
    write_json(args.out, doc)
    counts = doc["meta"]["counts"]
    print(
        f"wrote {args.out}: {counts['topics']} topics, "
        f"{counts['topicsWithGreekCandidates']} with a Greek-grammar candidate, "
        f"{counts['candidates']} candidates {counts['byWork']}; "
        f"uncovered syntax hubs {len(doc['meta']['audit']['uncovered'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
