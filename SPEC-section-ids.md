# Spec: canonical section IDs and URL scheme

Status: adopted 2026-08-01. This is the API everything else builds on — site, readers, data repo, construction table. Changes after launch require redirects, never breakage.

## Works

Slugs: `smyth`, `ag` (Allen & Greenough), `bennett`. Lowercase, short, stable.

## Section identity

- The atomic addressable unit is the **printed section number**: Smyth §1–§3048, A&G §1–§638, Bennett §1–§375, with one lettered section (§222A) that the print numbers
  in the series, so 376 records in all.
- Canonical data ID: `<work>:<number>` (e.g. `smyth:2297`). In HTML anchors and filenames: `s2297` (matches existing Perseus/alpheios convention).
- **Lettered subsections** (`2297 a`, `2326 d`) are anchors within the section, not separate pages: element id `a`, `b`, … citation string "Smyth §2297 a" ⇄ URL `/smyth/2297#a`. Nested letters (rare, e.g. "a. 1.") flatten to `a1`.
- **Dialect notes** ("D" subsections, Epic/Ionic): anchor `#D` (multiple: `#D1`, `#D2` in document order). These carry a `dialect: true` flag in data — the Homer reader filters on it.
- **Footnotes**: anchor `#fn1`, `#fn2` within their section.

## URLs

- Section page: `/smyth/2297` — one page per §, rendered inside its chapter context (prev/next §§ reachable). Trailing slash and `/smyth/s2297` redirect to canonical.
- Subsection: `/smyth/2297#a`. Arrival highlights the target subsection.
- **Ranges** (`2070–2078`, as cross-refs cite them): `/smyth/2070-2078` is a valid URL. It serves §2070 with a range banner ("cited as a range through §2078") and the range's §§ listed as links. Only ranges that actually occur in the corpus's cross-references are pre-generated; unknown ranges redirect to the first section.
- Topics: `/smyth/topics/<slug>` (e.g. `conditional-sentences`); landmarks are curated topic pages.
- Particle index: `/smyth/particles` and `/smyth/particles/<particle>` (NFC, lowercase, bare of accents in the slug: `/particles/an` for ἄν, with the display form on the page). Accent-only collisions (7 pairs, e.g. ἄρα/ἆρα, μέν/μήν) get deterministic `-2`/`-3` suffixes — rule and assignments in SPEC-landmarks.md.
- Verb list (Appendix): `/smyth/verbs` and `/smyth/verbs/<lemma-slug>`.
- Indexes: `/smyth/index/english`, `/smyth/index/greek`.
- Citation resolver: `/cite?q=Smyth+2297+a` (also bare `?q=2297a`) → 302 to canonical URL. Accepts the citation formats found in the wild: "Smyth §2297", "S 2297", "smythp 2297", "2297 a", ranges.

## Compatibility redirects (claim existing citation traffic)

- `/smyth/xhtml/*.html#sNNNN` patterns (alpheios) and `smythp=NNNN` query params (Perseus-style) get a documented mapping table; where hosting allows, serve 301s.

## Edition note

Text is Perseus's 1920 first edition (CC-SA). §-numbering differences vs. the 1956 revision are recorded per-section in a `editionNote` field when known; unknown by default.

## Data record (per section, summary)

`{ work, n, id, letters: [...], dialectNotes: [...], path (part/chapter/topic), head, html, plain, examples: [{grc, gloss, cite, urn?}], refs: [ids], refRanges: [...], citedBy: [ids], prev, next, editionNote? }`

IDs never encode presentation (no page numbers, no chapter numbers in the ID — hierarchy lives in `path`).

### Topics are a sidecar, not a section field

This summary listed a `topics: [slugs]` field until 2026-09-07. It never
existed in the data, and it cannot: `data/smyth/topics.json` is derived from
`sections.jsonl`, so a section record carrying its topic slugs would make
`convert_smyth.py`'s output depend on a file built from that same output, and
neither file could then be rebuilt from the TEI alone. `convert_smyth.py`
stays the only writer of `data/smyth/sections.jsonl` and reads nothing derived
from it.

The slugs live in `data/smyth/section-topics.json`, the second output of
`scripts/build_topics.py`: one row per section, in section order, `{ n,
topics: [slugs] }`, joined on `n`. A consumer that wants the field composes
the two files. `SPEC-topics.md` has the shape and the join rule; the other
works have no topic layer, so they have no sidecar.
