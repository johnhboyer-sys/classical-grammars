# Spec: derived topic list

Status: built 2026-09-07 against research/topic-pages-design.md, which
rules that "the topic list is derived, not designed". Outputs:
`data/smyth/topics.json` and `data/smyth/section-topics.json`. Both built by
`scripts/build_topics.py`, both verified by `scripts/verify_topics.py`. Python
stdlib only, deterministic.

## What this is

The candidate list for the topic-page layer: one record per grammatical
phenomenon that data we already own can name, with the Smyth §§ it lands
on. It is the join the design calls for and nothing more. A record is a
candidate for a page at `/smyth/topics/<slug>`; it is not a page, and it
carries no prose.

Four inputs, all in `data/smyth/`:

| input | what it contributes | source count |
|---|---|---|
| `index-english.json` | Smyth's own terminology: each headword and the §§ it cites | 752 entries, 732 with § refs |
| `index-greek.json` | the words themselves: the particles, prepositions, pronouns, verbs and endings a learner searches for, each headword with the §§ it cites | 1,496 entries, 1,449 of them seeding 1,418 topics |
| `constructions.json` | construction names from the AGDT annotation guidelines with their § ranges (CC BY-SA 3.0 US, attribution carried in `meta.attribution` and required downstream, see SPEC-constructions.md) | 201 entries of kind `list-item`, `table-row`, `heading` |
| `sections.jsonl` | cross-reference hubs: per section, the count of distinct other sections citing it (`citedBy`), and the same count restricted to citers in Part IV Syntax | 3,048 sections, 38 hubs |

The Part IV count exists because the raw count is dominated by Part I
phonology (§37 compensatory lengthening has 23 inbound refs, the most in
the book); a translator wants the syntax hubs (§2106 supplementary
participle in indirect discourse, 18 inbound Part IV refs, then §1392
genitive of separation, §2083 and §2086 adverbial adjuncts of the
participle).

The Greek index was added last and it was added additively: every record the
other three sources produced comes out of the build byte for byte as it did
before, and no slug retired. The rules that pay for that are under "The Greek
index" below.

## Record shape

```json
{
  "slug": "result-clauses",
  "name": "Result clauses",
  "aliases": ["consecutive clause"],
  "sections": [{"n": 2239}, {"n": 2249, "to": 2278}, {"n": 2260}, {"n": 2556}, {"n": 2705}],
  "sources": ["constructions", "index-english"],
  "hub": {"inbound": 18, "inboundSyntax": 18, "hubSections": []},
  "anchors": [{"n": 2249, "to": 2278, "head": "RESULT CLAUSES (CONSECUTIVE CLAUSES)",
               "path": ["Part IV: Syntax", "...", "RESULT CLAUSES (CONSECUTIVE CLAUSES)"],
               "inbound": 1, "inboundSyntax": 1}],
  "related": [],
  "provenance": {"indexEntries": [{"headword": "...", "raw": "...", "pages": [750]}],
                 "constructions": [{"construction": "...", "agdtContext": "...",
                                    "contextKind": "list-item", "sourceHeading": "..."}]}
}
```

- `slug`: lowercase ASCII, hyphenated, stable. Built from `name`; Greek is
  transliterated with the particle-slug table from `build_landmarks.py`
  (`πρός` is `pros`, `ὑπό` is `hupo`).
- `name`: the index headword when the topic has one (Smyth's terminology
  wins), else the alphabetically first construction name, else the section
  head of a standalone hub. A Greek record is named by its Greek headword
  exactly as the print gives it, parenthetical and all: `ἄν`, `ὥστε`,
  `ἄν (for ἀνά, prep.)`.
- `aliases`: every other name that landed on the record: merged
  construction names, and headwords of ref-less index entries whose single
  cross-reference resolves here ("Mutes. See Stops" makes `Mutes` an alias
  of `stops`). A Greek record carries its transliteration here, so a search
  for "an" or "hoste" finds ἄν and ὥστε, and any `searchKeys` the Greek
  index supplies for the entry ("-αινο/ε-" carries "-αινόε-", "-αινο-",
  "-αινε-").
- `sections`: `{n}` or `{n, to}` for a range, sorted and deduplicated.
  Ranges are stored as ranges, as in constructions.json. Lettered anchors
  from the index ("2032 f") are dropped here; the index entry's `raw` text in
  `provenance` keeps them.
- `sources`: which inputs produced the record: `index-english`,
  `index-greek`, `constructions`, `hub`. `index-greek` never appears beside
  `index-english` or `constructions`, because a Greek record never merges;
  it appears beside `hub`.
- `hub.inbound` / `hub.inboundSyntax`: distinct sections outside the
  topic's expanded section set that cite a section inside it, whole grammar
  and Part IV only. A ranking score, not a definition. `hub.hubSections`:
  the topic's explicitly cited sections that are hubs in their own right.
- `anchors`: one per `sections` entry, with the section's `head`, `path`
  and its own inbound counts, so a reader can see what the topic is without
  opening sections.jsonl.
- `related`: slugs resolved from the index entry's "See ..."
  cross-references; unresolved ones are listed in `meta.audit`.
- `provenance`: the input rows verbatim, so every record is traceable. A
  Greek record carries a third key, `indexGreek`, holding `{headword, raw,
  pages}` per entry in print order. The key is written only on the records
  that have one: records the other three sources produce keep the two keys
  they had, and so come out of the build byte for byte as before. A consumer
  reads it with `provenance.get("indexGreek", [])`.

`meta` carries the inputs, the CC BY-SA attribution, the rules and
thresholds, counts, the top twenty Part IV hubs, and an audit of every
decision that was not mechanical (merges made, hubs attached, cross-refs
that failed to resolve, index entries with no section to land on).

## How it is built

1. Index seeds: one per headword with at least one § ref (top-level and
   sub-entry refs pooled; refs flagged `nonSection` skipped). Headwords
   equal after folding are one seed.
2. Construction seeds: one per (construction name, section set) over the
   kinds `list-item`, `table-row`, `heading`. `prose` entries are excluded
   on SPEC-constructions.md's own advice. Construction names citing exactly
   the same sections are one seed.
3. Merge: each construction seed joins the index seed it overlaps best,
   measured as Jaccard similarity of the range-expanded section sets, if
   that score is at least 0.5. Index seeds never merge with each other, so
   a construction can never bridge two headwords, and a construction joins
   at most one headword. Adposition headings (`heading` kind: ἀμφί, πρός,
   ...) never merge; the preposition stays its own topic, with the
   `(with πρός) ...` list items that cite the same § as aliases.
4. Slugs: from the name. When a construction name collides with a headword
   ("cause", "time"), the headword keeps the bare slug and the construction
   is qualified by its AGDT menu at the coarsest level that separates the
   colliders (`cause-circumstantial-participle`,
   `command-syntax-of-the-infinitive`), then numbered.
5. Greek seeds: one per Greek index headword, after the English and
   construction slugs are settled, so nothing they hold can move. See "The
   Greek index" below.
6. Hubs: a section with at least 5 inbound Part IV refs is recorded on
   every topic that cites it as a section or range start, Greek topics
   included. A hub no `index-english`, `constructions` or `hub` topic cites
   explicitly becomes a topic of its own, slug `<head>-<n>`
   (`omission-of-the-verb-946`). The standalone question is put to those
   three sources only: §2651 and §2737 are cited by Greek records and by no
   other, and they keep their standalone records, because a slug is a URL
   (SPEC-section-ids.md) and a new source must not retire one.
7. Sort by slug, write with `indent=2, ensure_ascii=False`, no timestamps.

Current counts: 2,245 topics; 730 from the English index, 1,418 from the
Greek index, 138 from constructions, 249 carrying a hub; 44 records merge an
English index headword with a construction and nothing else merges; 38 hub
sections, 3 of them standalone topics.

## The Greek index

Smyth's Greek index is the words themselves. `topics/particle-an.md` was
written against a `topic: an` that no record answered, because ἄν is a Greek
headword, and so were ὥστε, ὅπως, ἵνα, μή, ἄρα, γάρ and δέ.

**One entry, one topic, and no merging.** A Greek record is seeded by one
headword. Entries printing the same headword are pooled into one record,
matched on the exact string: the transliteration is lossy, it folds ὅς, ὡς
and ὥς together and ἦ onto ἤ, and close is not a match. A Greek seed never
merges with an English headword, with a construction, or with another Greek
headword. The preposition πρός is therefore two records, the AGDT heading
`pros` and the Greek index `pros-1073`, and ἀνά is `ana` and `ana-354`.
Merging them would rewrite records that were right before this source
existed; it is recorded below as work owed rather than done here.

**Slugs.** The slug is the transliteration of the headword with its
parenthetical removed, by the same table and the same rules as every other
slug in the file (`ἄν` is `an`, `ὥστε` is `hoste`, `ὑπό` is `hupo`). The
Greek index prints a parenthesis as a gloss, a dialect note or a variant
(`ἄν (for ἀνά, prep.)`, `ᾱ (Dor., Aeol.) for η`, `εἰς (ἐς)`), never as part
of the word, so it names the record and stays out of the slug.

Transliteration collides freely, both with slugs the other three sources
already hold and with other Greek headwords: ὅς, ὡς and ὥς are all `hos`,
ἐν and -εν are both `en`, and ὅπῃ transliterates onto the English index's
`Hope`. The rule, in order:

1. A slug another source already holds is never taken. Slugs are assigned
   after the English, construction and hub slugs are settled.
2. Among Greek headwords that transliterate the same way, the bare slug goes
   to the record covering the most sections; a tie goes to the headword the
   print gives first. ἄν, with 40 section entries, keeps `an`.
3. Everything else is qualified by the first section the record cites:
   `an-75` for `ἄν (for ἀνά, prep.)`, `an-214` for `-ᾶν`, `an-2283` for
   `ᾱ̓́ν`, `hope-346` for ὅπῃ, `pros-1073` for πρός.
4. If that is still held, a number is appended (`-2`, `-3`). Nothing in the
   current data needs it.

123 of the 1,418 Greek slugs are qualified this way; the other 1,295 are the
bare transliteration.

**Sections.** From the entry's `refs`, `{n}` or `{n, to}`, deduplicated and
sorted, as everywhere else in the file. A ref's `anchor` is a lettered
subdivision of a section ("885. 1", "476 b", "214 D 5") and the section is
what a topic covers, so the anchor is dropped here and the entry's `raw`
text in `provenance` keeps it. A `ff` ref ("211 ff.") contributes its own
section and nothing more: the print does not say where the run ends.

**What is excluded.** 47 of the 1,496 entries, by two rules, both stated in
`meta.rules.greekExclusions` and both re-derived by the verifier:

- `alphabet-letter`, 35 entries. The headword is a single Greek letter
  carrying no breathing, so the entry is about the letter and not about a
  word: `Α, pronunc., 24 ; quantity, 4, 170 ; lengthens to ᾱ after ε, ι, ρ`,
  `Β, bef. dental stop, 82`, `ῃ, diphth., 5`. Every Greek word that begins
  with a vowel is printed with a breathing, so the breathing is the print's
  own mark of a word, and ἤ, ἦ, ᾗ, ὁ, ὅ, ὦ and ἕ, which are single letters
  too, stay as topics. A few of the 35 are formatives rather than
  orthography (`α, nom. sing. 1 decl.`, `ᾱ, suff.`, `ν, class of pres.
  stems`, `ῑ, remains unchanged in aug.`); the rule is orthographic and
  mechanical and it takes them with the rest. Ϝ is excluded by this rule
  rather than the next one, having no section either.
- `no-section-refs`, 12 entries. The entry cites no section at all, being a
  bare cross-reference: `οὐκ, see οὐ`, `μήτε, see οὔτε`, `ἅπᾱς, see πᾶς`.
  There is nothing for a topic to cover. They are not folded into the topic
  they point at either, because that would add an alias to a record that was
  finished before this source arrived.

**Not excluded: the long entries.** A ref list of eighty is not a bad topic
here. Ranked by refs, the Greek index's longest entries are μή (79), οὐ
(65), ἄν (43), Ε (40), Α (34), εἰ (34), αὐτός (31), εἰμί (30), καί (28) and
ὅπως (25). Six of the top ten are exactly the particles this layer exists
for, and the print differentiates their refs itself, by sense, in
semicolon-separated runs that `raw` preserves. The two that are genuinely
undifferentiated, Α and Ε, are alphabet letters that the letter rule already
takes. So there is no cap on ref count, and adding one would cost μή and ἄν
to save nothing.

**What the Greek index does not touch.** An English index "See ..."
cross-reference resolves against English, construction and hub names only,
and a ref-less English entry is aliased onto those same three sources. Before
this source those were the only names there were, so the restriction is what
keeps the older records exactly as they were. It costs something, and the
cost is recorded rather than hidden: five English cross-references point at
Greek headwords that are now topics (`Intensive particles` at αὐτός,
`Negatives` at μή and at οὐ, `Relative` at ὅς, `Alpha privative` at
ἀ-privative) and stay in `meta.audit.unresolvedCrossRefs` instead of
becoming `related` links. A Greek entry's own cross-reference sees every
name, its own included, and 14 of them resolve (ὁ to `article`, κέ(ν) to
`an`, μηδέ to `oude`).

## The join read backwards: `section-topics.json`

A topic record names the §§ it covers. The reverse, "what topics land on
§2249", is the same join read the other way, and the same builder writes it
as a second file:

```json
{"meta": {...}, "sections": [{"n": 1, "topics": ["alphabet", "digamma", "letters"]},
                             {"n": 194, "topics": []}]}
```

- One row per record in `sections.jsonl`, in § order, all 3,048 of them.
- `topics`: every slug whose record covers that §, ranges expanded end to
  end, so a record citing `{"n": 2249, "to": 2278}` names all thirty. Sorted
  ascending and deduplicated. `hub.hubSections` add nothing, because a hub is
  only ever recorded on a topic that already cites it as a section or a range
  start.
- A § no topic covers gets `[]`. Five do: §194, §269, §921, §1098, §1656,
  all of them the bare heading a run of lettered subsections hangs off, which
  Smyth's index cites by the later § rather than the heading. There were
  eight before the Greek index: §272 is now covered by ἰχθῡ́ς, §277 by
  βασιλεύς, -ῆς and -εύς, §279 by ἀηδών and οι.
- `meta` carries the join rule, the counts, the distribution of topics per §,
  the twenty-five records with the widest coverage, and the ten §§ with the
  most topics.

It is a separate file rather than a `topics` field on the section record
because `topics.json` is derived from `sections.jsonl`. Writing the answer
back would make `convert_smyth.py`'s output depend on a file built from that
output, and `verify_smyth.py` check 9, which rebuilds `sections.jsonl` from
the TEI and compares byte for byte, is the guarantee that pays for. A
consumer that wants the field joins the two files on `n`. `SPEC-section-ids.md`
records the same thing.

Nothing is dropped for covering too much. Smyth's own index headwords carry
book-sized ranges: `verbs` covers 1,026 §§, a third of the grammar,
`syntax` 542, `complex-sentences` 442. On those §§ the slug says little the
§'s own `path` does not. But no coverage threshold pays for itself: capping
at 100 §§ drops 36 records and leaves 392 §§ with no topic at all, up from 8,
and choosing the cap would be exactly the hand-built ontology this spec
refuses. `meta.broadestTopics` is there so a renderer can rank narrow records
first or hide the widest, which is a presentation decision and belongs
downstream.

Current counts: 3,048 §§, 3,043 with at least one topic, 20,001 assignments,
6.56 topics per § on average, at most 93 (§489, `CHANGES IN THE VERB-STEM`,
which the Greek index's ending entries cite over and over). Before the Greek
index: 3,040 covered, 14,965 assignments, 4.91 on average, at most 19.

## What it is not

- Not an ontology. Nothing here was named by hand; every name is Smyth's
  English index, his Greek index, the AGDT guidelines', or a Smyth section
  head.
- Not de-duplicated across sources. πρός is a record from the AGDT headings
  and a record from the Greek index, ἀνά likewise, and the English index's
  `Hope` sits beside ὅπῃ. Joining them is real work and it is owed; doing it
  by hand is what this spec refuses, and doing it by transliteration alone
  would merge ὅς with ὡς.
- Not crosswalked, for the Greek records. `crosswalk.json` covers the 827
  records the other three sources produce; SPEC-crosswalk.md says why, and
  that too is owed work.
- Not the page list. The index's granularity is Smyth's, so "Absolute"
  covers genitive, accusative and infinitive absolute in one record, and
  the pilot page `topics/genitive-absolute.md` is finer than any derived
  record. Pages cite records; records do not dictate pages.
- Not a hierarchy. `related` holds the index's own "See" links and nothing
  inferred.
- Not filtered for quality. AGDT leaf labels like `dependent` or
  `statement` are kept as aliases where their sections overlap a headword;
  `provenance.constructions[].agdtContext` says what they meant.
- Not licensed as one unit. Records with `constructions` in `sources` carry
  CC BY-SA names; anything rendering them must carry the attribution in
  `meta.attribution.constructions`.

## Verification

`scripts/verify_topics.py` (exit 0 = pass), fourteen checks: every cited §
and hub § exists; ranges run forwards; slugs unique, lowercase ASCII,
sorted; every English index entry with § refs is in some topic's provenance;
every non-prose construction entry is placed; sources agree with provenance
and no Greek record carries a second source; hub sections meet the declared
threshold; meta counts agree with the array; a fresh build is byte-identical
to both committed files; `section-topics.json` has one sorted, deduplicated
row per §, in order, naming only slugs that exist; and the join agrees both
ways, every § a topic covers naming that topic and every slug named on a §
covering it. The distribution of topics per § is printed as a note under
check 11.

Checks 13 and 14 hold the Greek index to the same standard, re-deriving it
from `index-greek.json` rather than trusting the build. 13: every one of the
1,496 entries either seeds exactly one topic or is excluded by one of the two
declared rules, which the verifier re-implements; no entry is both; the
seeded and excluded counts add up to 1,496 and agree with `meta.counts`. 14:
every Greek record covers exactly the sections its own entries cite, is named
by a headword the print gives, carries its transliteration among its aliases,
and holds either the bare transliteration or that transliteration qualified
by its first section, the bare form only when nothing else holds it; and no
headword is split over two records. The transliteration table and both Greek
rules are written out again in the verifier rather than imported, so a change
to either has to be made twice.
