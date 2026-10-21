# Spec: cross-grammar crosswalk

Status: built 2026-09-07 on top of SPEC-topics.md. Output:
`data/smyth/crosswalk.json`. Built by `scripts/build_crosswalk.py`,
verified by `scripts/verify_crosswalk.py`. Python stdlib only,
deterministic. Answers item 8 of the classicist questionnaire
(cross-grammar parallels on the same topic).

## What this is

For each of the 827 derived Smyth topic records with an English name, the
sections of the other grammars we own that treat the same phenomenon, with a
score and the evidence, so a topic page can print a line like

    Smyth §§2070-2078; GMT §§847-854; Monro §246; Goodell §§589-591

and a reader can open the evidence and judge it. The works are the four
other Greek grammars (`goodwin-gmt`, `gildersleeve`, `monro`, `goodell`)
and, under a stricter rule, the two Latin ones (`ag`, `bennett`).

Nothing in it is a hand-built mapping. Every candidate is a materialised
join of data already in `data/`, and every candidate says which join
produced it and with which strings.

## Record shape

```json
{
  "slug": "absolute",
  "name": "Absolute",
  "aliases": [],
  "smyth": [{"n": 2058}, {"n": 2070, "to": 2075}, "..."],
  "smythHeads": ["THE CIRCUMSTANTIAL PARTICIPLE", "GENITIVE ABSOLUTE. ACCUSATIVE ABSOLUTE", "..."],
  "greekTerms": 355,
  "candidates": [
    {
      "work": "goodwin-gmt", "label": "GMT",
      "sections": [{"n": 847, "to": 854}],
      "heads": ["Genitive Absolute.", "Accusative Absolute."],
      "score": 1.75,
      "evidenceKinds": ["greek-terms", "heading"],
      "evidence": [
        {"kind": "greek-terms", "score": 1.0, "cosine": 0.535, "sharedTerms": 6,
         "sharedIdf": 40.1, "smythSections": [2073],
         "terms": ["ανθρωπων", "αφεστηκε", "δεδογμενον", "δηλωθεντοσ", "..."],
         "sections": [849, 850]},
        {"kind": "heading", "topicString": "Absolute",
         "sectionString": "Genitive Absolute.", "ancestor": false,
         "matched": ["absolute"], "score": 0.75,
         "sections": [847, 848, 849, 850, 851]}
      ]
    }
  ]
}
```

- One record per topic in `topics.json`, in the same order, carrying the
  topic's name, aliases and Smyth sections verbatim (`smyth`) with their
  heads (`smythHeads`) so the page needs no second lookup.
- `greekTerms`: the size of the topic's Greek vocabulary after function
  words are removed; a topic with a small number has little for the
  Greek-term evidence to work with.
- `candidates`: sorted by work (Greek grammars first, in the declared
  order), then score descending, then section. At most five per work.
- `sections`: one section `{n}` or one gap-free run `{n, to}` in the
  work's own order. A run is what consecutive kept sections coalesce into;
  its `heads` are the distinct section heads it spans.
- `score`: the best single section's score in the run.
- `evidence`: every piece that fired on any section of the run, best
  first, each with the `sections` of the run it fired on and the strings
  it matched, so a reader can see why the candidate is there. Kinds:

| kind | what fired | score |
|---|---|---|
| `heading` | `topicString` (name or alias) against `sectionString` (the head, or with `ancestor: true` an element of the path above it), `matched` tokens | coverage of the topic's tokens by the head x (0.5 + 0.5 x share of the head's tokens matched); x0.8 for an ancestor |
| `goodell-index` | Goodell's English index `headword` identical to the topic name or alias after folding (plural tolerated); `raw` is the index line | 1.0 for each section the entry cites |
| `greek-terms` | cosine of tf-idf vectors of Greek tokens, for the pooled topic (`smythSections: []`) or the single best anchor section (`smythSections: [n]`); `terms` are the strongest shared tokens, `sharedTerms` and `sharedIdf` the count and the idf sum of all of them | (cosine - 0.05) / 0.30, capped at 1.0 |
| `cites-smyth` | the section's text cites a Smyth section inside the topic by number, `matched` is the citation text | 1.0 |
| `cited-by-smyth` | a Smyth section inside the topic cites the section by number | 1.0 |
| `citation-chain` | the section cites (`via`) a section of another grammar that is itself a kept candidate for the topic | 0.5 |

`meta` carries the inputs, the work lists and labels, every rule and
threshold with its value, the stopword and synonym tables, the counts, the
48 Greek function words the corpus itself elected, and an audit.

## How it is built

1. Load `topics.json`, every work's `sections.jsonl` (rows with an integer
   `n`; GMT's appendix rows are skipped) and Goodell's `index-english.json`.
2. Normalise heading strings: strip leading numbering ("II.", "Section
   VI:", "(b)"), fold with `build_topics.fold_name` (lowercase, diacritics
   off, Greek transliterated), drop stopwords, singularise (`clauses` to
   `clause`, `wishes` to `wish`), and fold a short table of metalanguage
   variants (`sentence` to `clause`, `mode` to `mood`, and the abbreviations
   Goodell's index uses: `subjv`, `indic`, `adj`, `gen`, ...). The tables are
   in `meta.rules` and are spelling normalisation, not a topic mapping.
3. Greek tokens: runs of Greek letters of two or more characters in a
   section's `plain` and its notes, folded (diacritics off, final sigma
   merged). Document frequency is counted over all 5,736 sections of the
   five Greek grammars, Smyth included. Any token in more than 5% of them
   is a function word and is dropped: the article, καί, δέ, ἄν, οὐ, μή, εἰ,
   ὡς, ὅτι, πρός, περί and their like, 48 in all. The rest are weighted
   (1 + log tf) x log(N/df) and each section is a unit vector.
4. Score every section of every other grammar against the topic:
   - heading: the best match of any topic name or alias against the head
     (x1.0) or a path ancestor (x0.8). "Absolute" against "Genitive
     Absolute." is 0.75; "Result clauses" against "Consecutive Relative
     Clauses Expressing Result" is 0.667; "Genitive absolute" against a
     bare "Genitive" is 0.5, because the coarser section is the weaker
     parallel.
   - goodell-index: 1.0 for the sections a headword-identical entry cites.
   - greek-terms: the better of the pooled topic vector (all anchor
     sections' counts summed) and the best single anchor section. Either
     counts only when the shared terms together carry at least 18 nats of
     idf: two short sections that both mention ἀμφί, ὑπέρ and ὑπό have
     cosine 0.66 and idf sum 10, four terms each rarer than one section in
     a hundred reach 18. The cosine is rescaled so that 0.05 (the noise
     between any two sections that quote Greek) is 0 and 0.35 is full
     evidence.
   - citations: `Smyth § n` in another grammar, `Goodwin § n` (or `Moods
     and Tenses`, `G. M. T.`), `Gildersleeve § n`, `Monro § n`, `Goodell §
     n`. The section sign is required: Smyth §2758's "Goodwin Moods and
     Tenses 389" is a page of the 1889 appendix on οὐ μή, and journal
     references carry numbers too. Cited ranges of more than sixty sections
     are taken as their first section.
5. A section's score is the sum. Sections scoring at least 0.75 are kept.
   The threshold is set so that an exact heading, an index headword or a
   citation passes alone; a partial heading like "Absolute" in "Genitive
   Absolute." (0.75) passes alone but "Result clauses" in a four-word head
   (0.667) needs a Greek-term cosine of 0.075 above the floor; and Greek
   terms alone need a cosine of 0.30. Citation chains are added after the
   first pass, since they depend on what was kept.
6. Consecutive kept sections of one work coalesce into one candidate; the
   best five per work are written.
7. Latin grammars: heading evidence only, only against the head (never an
   ancestor), and only an exact match of the normalised token sets. No
   Greek-term, index or citation evidence can reach them. "Genitive
   absolute" therefore cannot reach "Ablative Absolute", and "Absolute"
   does not either, because the token sets differ. `meta.works.latinRule`
   states this.
8. `meta.audit.uncovered`: every topic with a hub anchor in Part IV Syntax
   (an anchor section that is one of the topic's `hub.hubSections`, in
   Part IV) and no candidate in any other Greek grammar.
9. Sort, round scores to three decimals, write with `indent=2,
   ensure_ascii=False`, no timestamps.

The 1,418 topic records the Smyth Greek index seeds are out of scope. Every
evidence kind below was built and its precision measured on records with an
English name; scoring ἄν or ὥστε by the same rules is a round of work with
its own reading and its own measurement, and it has not been done.
`meta.inputs.topicsScope` says so in the file, `verify_crosswalk.py` check 1
holds the line both ways, and SPEC-topics.md records the debt.

Current counts: 827 topics; 433 with a candidate in another Greek grammar,
442 with any; 1,870 candidates (GMT 497, Gildersleeve 276, Monro 282,
Goodell 698, A&G 62, Bennett 55); evidence kinds over candidates: heading
853, greek-terms 1,564, goodell-index 142, citation-chain 26; 30 topics
uncovered. Explicit citations found: Monro cites Goodwin's Moods and
Tenses 28 times by section, Goodell 3 times; nobody we own cites Smyth by
section (Monro's "H. W. Smyth" is the articles), and Smyth cites none of
the others by section. So the citation evidence is real but thin, and it
enters the file as chains through kept candidates.

## Precision measured

`verify_crosswalk.py` check 8 prints 40 candidates chosen by the smallest
`sha1("20260907:" + slug + ":" + work + ":" + first section)`, with the
topic name, the Smyth anchor head the evidence names (or the topic's own
anchors when the evidence is a heading or index match) and the candidate's
head; `--sample-texts` adds the section texts. The 40 were read against
the texts on 2026-09-07 and judged as: the candidate treats the same
phenomenon as the Smyth anchor it is paired with, or as the topic when the
evidence names no anchor (right); related, but a different phenomenon or a
mixed run (partly); only shared vocabulary (wrong).

**31 right, 5 partly, 4 wrong.** Strict precision 31/40; counting partly,
36/40.

The wrong four, so the failure modes are on record:

- `orthotone` to Goodell §196 (poetic pronoun forms): Smyth §181's list of
  enclitic pronouns shares seven rare forms (νιν, σφε, σφιν...) with a
  section about metre, not accent.
- `sentence` to GMT §§712-719 (Causal Sentences): a one-word topic name
  contained in a two-word head scores 0.75 and passes alone. One-word
  topics ("Time", "Cause", "Position", "Sentence") are the weak spot of the
  heading evidence.
- `number` to Goodell §232 (adverbs of number): Goodell's index headword
  "Number" means numerals; Smyth's means grammatical number. Headword
  identity does not see homonyms.
- `purpose-circumstantial-participle` to Goodell §631 (ἕως clauses):
  Goodell's index entry "Purpose, expressions of" gathers every construction
  that can express purpose; the topic is one of them.

The partly five are of one shape: the candidate treats the Smyth anchor
section's own phenomenon (dative of agent with verbals in -τέος, Smyth
§1488 to Goodell §596) but the topic that owns the anchor is named for
something else ("Perfect tense"). That is the topic list's granularity
(SPEC-topics.md, "not the page list"), carried through faithfully.

A pilot reading of an earlier build (index-based random sample, 40
candidates) came out 33 right, 4 partly, 3 wrong; the two builds differ by
the citation fix and the sampling method only.

## What it is not

- Not a mapping anyone drew. No pair of sections was placed by hand, and no
  synonym of a construction name is known to it except what Smyth's index
  and the AGDT names already made aliases (`consecutive clause` for
  `result-clauses`). "Final clause" reaches "Purpose" only where the Greek
  terms carry it.
- Not symmetric and not a graph. It runs from Smyth topics outward; the
  other grammars have no topic records of their own.
- Not a judgement of equivalence. A score is a sum of evidence weights,
  and the site should show the evidence, not the number. The measured
  precision above is what the number is worth.
- Not complete. Smyth's "verbs of ..." index entries (acknowledge,
  admiring, blaming, ceasing, ... 30 of them with a Part IV hub anchor)
  name verb classes no other grammar heads, and their single anchor
  sections rarely share enough Greek with anything to clear the bar; they
  are listed in `meta.audit.uncovered` rather than forced.
- Not a Latin crosswalk. The Latin candidates are exact heading matches
  ("Apposition", "Temporal clauses", "Clauses of Result") and nothing more;
  a Greek construction and its Latin analogue with a different name
  (genitive absolute and ablative absolute) are not joined, on purpose.
- Not stable across edits to its inputs. A change to `topics.json` or to
  any `sections.jsonl` changes the idf, the function-word set and the
  scores; the verifier's determinism check will say so, and the QA sample
  is drawn by hash so that most of it survives a rebuild.

## Verification

`scripts/verify_crosswalk.py` (exit 0 = pass): one record per topic in the
same order with the same name, aliases and sections; every candidate
section exists in its work, ranges run forwards with no gap, works are
declared; every candidate clears `meta.rules.keepMin`, at most
`maxPerWork` per work, sorted best first, and every piece of evidence names
sections of its candidate; Latin candidates carry exact heading evidence
only; citation evidence names Smyth sections inside the topic; every topic
with a Part IV hub anchor has a Greek-grammar candidate or is audited as
uncovered, and nothing audited is covered; meta counts agree with the
array; the 40-candidate QA sample is printed for a person; a fresh build
is byte-identical to the committed file. It runs in CI as its own step.
