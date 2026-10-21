# SPEC: landmark data — verb list, indexes, particles

Status: built 2026-08-01; index handling revised 2026-08-03. Covers the
reference-navigation landmarks the owner uses in his physical Smyth
(sticky tabs on the major sections, each particle, and the alphabetized
verb list at the back). Built by `scripts/build_landmarks.py` from
`grammar-smyth/src/smyth_eng_u.xml` into `data/smyth/verbs.json` and
`data/smyth/particles.json`. Verified by `scripts/verify_landmarks.py`.

The print indexes are no longer this pipeline's concern:
`index-english.json` is built for real by `scripts/build_index_english.py`
(digitized from the print back matter via the multi-reader adjudication
pipeline), and `index-greek.json` is being built the same way
(`work/greek-index/STATUS.md`). `build_landmarks.py` used to write both as
`not_digitized` stubs; that write was removed 2026-08-03 after it
clobbered the real English index. Until the Greek pipeline lands, the
committed `index-greek.json` stub is maintained by no script.

## Source inventory

The TEI source (`grammar-smyth/src/smyth_eng_u.xml`) has exactly **5**
top-level `div1` divisions:

| `div1[@n]` | `@type` | head | content |
|---|---|---|---|
| 1 | `Part` | Part I: Letters, Sounds, Syllables, Accent | body |
| 2 | `Part` | Part II: Inflection | body |
| 3 | `Part` | Part III: Formation of Words | body |
| 4 | `Part` | Part IV: Syntax | body, incl. the `PARTICLES` chapter (§§2769–3003) |
| 5 | `part` (lowercase) | Appendix: List of Verbs | **digitized** |

There is no English Index or Greek Index `div` anywhere in the file — the
print book's back matter (List of Verbs, English Index, Greek Index) is
represented in the TEI by exactly one of those three: the Appendix. This
was confirmed by:

- enumerating every `<div…type="…">` value in the source (`Chapter`,
  `Part`/`part`, `Section`, `Sub3`, `SubSub`, `Subsection`, `Subsub`,
  `section`, `smythp`, `subsection`, `subsub` — no `index`/`Index`/`glossary`
  type anywhere);
- confirming the file ends immediately after the Appendix's last verb
  entry (`ὠνέομαι`, under "Verbs beginning with ω") with no further
  `div1`;
- checking `grammar-smyth/xhtml/` (110 pre-rendered pages) and
  `grammar-smyth/xhtml/smyth.html`'s own table of contents, which lists
  only Parts I–IV and the Appendix — no index page exists among the
  rendered files either;
- checking `grammar-smyth/index/alph-index-smyth`, the repo's one other
  candidate: it is a CSV of ~86 entries, but it is a small Alpheios-built
  site-navigation aid for grammatical *topics* ("case", "declension",
  "mood", "tense", "voice", "part of speech" and their subtypes), not the
  print book's English or Greek back-of-book index. Its own two rows for
  `alph-general-index` and `alph-table-of-contents` both point at
  `smyth.html#table-of-contents` — a dead end, not an index page.

**Conclusion: the Appendix (List of Verbs) is fully digitized; the print
book's English Index and Greek Index are not present in this TEI
digitization in any form.** That gap is why the indexes were later
digitized from scans of the print back matter by their own pipelines
(see the status note at the top) — this builder neither writes nor
verifies them.

## `data/smyth/verbs.json`

```jsonc
{
  "work": "smyth",
  "source": "Appendix: List of Verbs (TEI div1[@type='part'][@n='5'])",
  "collation": "greek-alphabet-order",
  "verbs": [
    { "lemma": "ἀγάλλω", "entryHtml": "<p>...</p>", "sections": [507] },
    ...
  ],
  "_meta": { "letterGroups": 24, "entriesWithoutLemma": [], "invalidSectionRefs": [], "count": 761 }
}
```

- One entry per `<p>` under each of the Appendix's 24 letter-group `div2`s
  — all 24 letters of the Greek alphabet, α through ω, nothing skipped
  (`ppa.html`…`ppz.html` in the xhtml rendering: 24 files, Latin-named,
  so they skip `ppj`/`ppv` and don't sort alphabetically; the
  `@n="1".."24"` attributes and the `<head>` text do sort, and that's
  what the builder trusts).
- `lemma` is the text of the entry's first `<foreign lang="greek">` node
  — always the headword in every one of the 761 entries (0
  `entriesWithoutLemma`).
- `entryHtml` is the full entry, rendered by a small TEI→HTML renderer
  (`foreign`→`<span lang="grc">`, `gloss`→`<span class="gloss">`,
  `emph[@rend=bold]`→`<strong>`, `ref`→`<a data-ref="smyth:N">`,
  `bibl`→`<cite data-cite="...">`) — the same tag vocabulary
  `convert_smyth.py` uses for section `html`, kept as a small
  self-contained copy rather than an import, since the Appendix only ever
  uses this subset.
- `sections` is every in-range `<ref target="sNNN">` cross-reference
  inside the entry (e.g. "III." linking to §507, the third verb-class
  definition) — i.e. every place in the grammar body the entry itself
  points to, not places that discuss the verb. 0 `invalidSectionRefs`
  (refs pointing outside `sections.jsonl`); the field would carry any
  found, not drop them silently.
- **761 verb entries**, 24 letter groups, matching the Appendix's own 767
  `<p>` elements minus 6 front-matter paragraphs at the `div1` level
  (format-of-the-list explanation, before the first letter group).
- 13 lemma strings are duplicated (e.g. `δέω` "bind" vs. `δέω` "need,
  lack") — verified to be genuine print homographs with distinct
  `entryHtml`, not extraction duplicates.

### Collation rule

`greek-alphabet-order`: strip every Unicode combining mark (NFD, drop
`unicodedata.combining() == True` characters — accents, breathing,
iota subscript, vowel-length macra all go), lowercase what remains, fold
final sigma to medial sigma, drop every non-Greek character, then sort by
each base letter's index in the 24-letter Greek alphabet (α=0 … ω=23).
Dropping non-Greek characters matters: the appendix prints stem
boundaries as hyphens (`ἄγ-νῡμι`, `δί-δωμι` — 188 of the 761 headwords)
and six headwords list several forms separated by commas, and the print
list alphabetizes as if those marks were absent.

Ties (identical letter skeletons) break on the NFD codepoint sequence of
the original string, so the order is total and deterministic even between
true accent-only variants. That fallback is a *second* element of the key
tuple, never concatenated onto the letter sequence — concatenating it
would let a codepoint decide a comparison between two different skeletons
where one is a prefix of the other (`ἀε-` vs `ἀείρω`), pushing every
bare-stem headword after its longer neighbours.

Result: the built order reproduces the print appendix's own order for 759
of 761 entries. The two exceptions are accent-only or breathing-only
neighbours the accent-blind key cannot order the way the print page does
(`εἰμί`/`εἶμι`; `ἕπω`, which the print list keeps beside `ἕπομαι` rather
than at its strict alphabetical place after `ἐπριάμην`).

`scripts/verify_landmarks.py` check 7 confirms `verbs.json` is sorted by
exactly this key — note that this is a consistency check between the data
and `build_landmarks.collation_key`, not an independent statement about
Greek alphabetical order.

## `data/smyth/particles.json`

```jsonc
{
  "work": "smyth",
  "particles": [
    { "particle": "ἄν", "slug": "an", "sections": [{"n":1761,"role":"primary"}, ..., {"n":1845,"role":"mention"}, ...] },
    ...
  ],
  "_meta": { "primarySource": "...", "mentionSource": "...", "particleCount": 48, "slugCollisions": [...], "parseNotes": [...] }
}
```

### Primary source

Part IV's own `PARTICLES` chapter (§§2769–3003) holds 40 `div3`
subsections. The first six (§§2769–2774) are the chapter's own
head-less preamble on particles in general and yield no particle; the
other 34 are each headed by one particle or a small group of closely
related forms the grammar discusses together (e.g. "δαί, δῆθεν, δήπου,
δῆτα", "οὐδέ, οὔτε (μηδέ, μήτε)", "ἠδέ (AND ἰδε)"). A 35th primary
heading, "THE PARTICLE ἄν" (§§1761–1768), lives outside that chapter
under Part IV › "THE VERB: VOICES" — ἄν is Smyth's modal particle,
grouped with the verb system rather than the connective/asseverative
particles. Splitting every heading's comma/parenthetical list into
individual forms (see "Heading parser" below) yields **48 particles**,
each with the heading's full section range marked `role: "primary"`.

This is a superset of the brief's illustrative list (ἄν, μέν, δέ, γάρ,
οὖν, καί, τε, γε, δή, ἦ, μήν, περ, τοι, ἀλλά, ἄρα, αὖ, οὐδέ/μηδέ) — every
one of those is present, plus the book's other digitized particle
headings (γοῦν, εἴτε, ἠδέ/ἰδε, καίπερ, καίτοι, μά, μέντοι, ναί/νή,
νῦν and its orthographic variants, ὅπως, οὔτε/μήτε, οὐκοῦν/οὔκουν, πλήν,
τοί, ὥς/ὡς, ἆρα, ἀτάρ). **εἰ (the conditional particle) is not among
them**: conditional sentences get two TOC headings ("CONDITIONAL
CLAUSES" §§2280–2288, "CLASSIFICATION OF CONDITIONAL SENTENCES"
§§2289–2368), but neither is headed "εἰ" the way ἄν, μέν, etc. get their
own heading — the print book (and this digitization) organizes εἰ's
discussion by construction, not as its own particle chapter. (The only
two headings anywhere in the source with a bare εἰ in them are "εἰ with
the Optative…" §§2359–2365, inside the conditionals treatment, and "οὐ
AFTER εἰ (ἐά̄ν)" §§2698–2701.) `particles.json` does not fabricate a
primary entry for εἰ. Nothing flags the gap in the data — there is no
heading to parse and so nothing lands in `_meta.parseNotes`; it is
simply absent, and documented here.

### Heading parser

`parse_particle_forms()` splits a heading into forms: parenthesized
content is a second list of forms (optionally prefixed with the literal
English word "AND", which the source uses instead of a comma before the
last item — verified by inspection of all 34 headings, not a guess), and
both the pre-parenthesis and in-parenthesis text split on commas. One
heading — `καίτοι<*>` — carries a literal `<*>` substring, a
Perseus-digitization glyph gap (a missing ligature/accent character) that
appears 149 times across the whole source; it is stripped and logged in
`_meta.parseNotes` rather than left in the particle string. It is the
only such artifact in any of the 34 headings, and so `parseNotes` holds
exactly one entry.

### Mention source

The brief's priority list for particle→§§ data is (1) the Greek index's
particle entries, (2) the TOC, (3) section heads mentioning a particle.
Source (1) does not exist (see "Source inventory"), so mentions come from
(3): every `<head>` in the document outside *any* particle's primary
subtree is scanned for a token whose accent-stripped letter-skeleton
(NFD, combining marks dropped, Greek letters kept — *not* transliterated
to Latin, so ε and η stay distinct letters here) matches the particle's
skeleton. A hit's whole printed section range is recorded with
`role: "mention"` for every section number already present in
`sections.jsonl` (a range is never fabricated past what
`sections.jsonl` actually contains). Example: ἄν picks up 79 mention
sections this way (e.g. "INFINITIVE AND PARTICIPLE WITH ἄν" §§1845–1849,
"THE PARTICIPLE WITH ἄν" §2146) beyond its 8 primary sections.

This is coarser than a real index: it only sees section/subsection
*headings*, never body prose, and it is necessarily accent-blind — ἤ and
ἦ (or ὥς and ὡς) are the same base letter with only an accent
difference, so they get identical mention sets from this method by
construction. This is a documented limitation, not a bug; a genuine
back-of-book Greek index (which does not survive in the digitization)
would be needed to do better.

Excluding *every* particle's primary subtree, rather than only the
particle's own, is deliberate: the difference touches four particles
(ἄρα, ἆρα, ἤ, ἦ) and 25 sections, and every one of those 25 is an
accent-blind false hit picked up inside the neighbouring accent-variant's
own chapter. It suppresses noise, not signal.

### Slugs and collisions

Per `SPEC-section-ids.md` (`/smyth/particles/<particle>`, "NFC, lowercase,
bare of accents"): each base Greek letter maps to one Latin skeleton
(α→a, β→b, γ→g, δ→d, ε→e, ζ→z, **η→e**, θ→th, ι→i, κ→k, λ→l, μ→m, ν→n,
ξ→x, ο→o, π→p, ρ→r, σ/ς→s, τ→t, υ→u, φ→ph, χ→ch, ψ→ps, **ω→o**), with a
leading rough-breathing mark rendered as `h` (`ῥ`→`rh`), and every other
diacritic (accent, smooth breathing, iota subscript, vowel-length macron)
dropped. This is a lossy scheme by design — bare Latin ASCII slugs can't
carry Greek's five-way accent system — so **7 collisions** are expected
and were found:

| slug | colliding forms | resolved as |
|---|---|---|
| `ara` | ἄρα, ἆρα | `ara`, `ara-2` |
| `de` | δέ, δή | `de`, `de-2` |
| `e` | ἤ, ἦ | `e`, `e-2` |
| `men` | μέν, μήν | `men`, `men-2` |
| `nun` | νύ̄ν, νύν, νῦν | `nun`, `nun-2`, `nun-3` |
| `oukoun` | οὔκουν, οὐκοῦν | `oukoun`, `oukoun-2` |
| `hos` | ὥς, ὡς | `hos`, `hos-2` |

Disambiguation rule (deterministic, so a rebuild never reassigns a
different form to a different slug): within a collision group, sort the
colliding forms by their own NFD codepoint sequence; the first keeps the
bare slug, the rest get `-2`, `-3`, … in that order.
`scripts/verify_landmarks.py` checks 5–6 confirm the resulting 48 slugs
are unique and lowercase ASCII.

## `data/smyth/index-english.json` / `data/smyth/index-greek.json`

Not built here (since 2026-08-03). `index-english.json` is the real
digitized English Index, owned by `scripts/build_index_english.py` and
`scripts/verify_index_english.py`. `index-greek.json` is still the
original `not_digitized` stub
(`{ "entries": [], "_meta": { "status": "not_digitized", ... } }`) that
the site renders as "not yet available"; it will be replaced by the
Greek-index pipeline (`work/greek-index/STATUS.md`). No script rewrites
the stub in the meantime.

## What's missing vs. the print book

| Print structure | Digitized? | Deliverable |
|---|---|---|
| Appendix: List of Verbs | Yes, in full (24/24 letter groups) | `verbs.json`, 761 entries |
| Particle chapters (Part IV) | Yes, 34 of 34 headings under `PARTICLES`, plus ἄν's separate heading | `particles.json`, 48 particles |
| εἰ as a dedicated particle heading | No — book organizes it by construction (conditional clauses), not as its own chapter | not fabricated; documented above |
| English Index | Not in the TEI; digitized 2026-08 from print scans | `index-english.json` (built by `build_index_english.py`) |
| Greek Index | Not in the TEI; print digitization in progress | `index-greek.json` stub until `work/greek-index` stage 4 lands |

## Determinism

`scripts/build_landmarks.py` reads the TEI source once, resolves the
source's glyph placeholders with `convert_smyth.py`'s own `GLYPH_FIXES`
table (imported, not copied — a copied table drifted once and shipped
`[ιγλιδε]` placeholders into `verbs.json`), NFC-normalizes it
up front (`unicodedata.normalize("NFC", ...)`, matching `convert_smyth.py`'s
own convention — the source mixes precomposed and decomposed Greek), and
writes every output with `sort_keys=False` but list order always fixed
by the same collation/document-order rules on every run. `scripts/verify_landmarks.py`
check 9 re-runs the builder into a temp directory and diffs both output
files (`verbs.json`, `particles.json`) byte-for-byte against the
checked-in copies. Without a reachable
`--tei-source` it cannot run, and then reports `SKIP` — counted apart
from passes, so an unrun check never reads as a verified one.

## Running

```
python3 scripts/build_landmarks.py \
  --tei-source /path/to/grammar-smyth/src/smyth_eng_u.xml \
  --sections data/smyth/sections.jsonl \
  --out-dir data/smyth

python3 scripts/verify_landmarks.py \
  --tei-source /path/to/grammar-smyth/src/smyth_eng_u.xml
```

`--tei-source` defaults to `grammar-smyth/src/smyth_eng_u.xml` relative to
the repo root, which resolves correctly in a normal checkout; it must be
passed explicitly inside a `git worktree` checkout, since `grammar-smyth/`
is gitignored and worktrees don't carry gitignored directories over.
