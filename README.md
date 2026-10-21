# classical-grammars

The standard Greek and Latin reference grammars as clean, structured data:
one record per printed section, keyed by the section number the print uses,
with cross-references, examples, citations and indexes. Also the lexicon
packs (LSJ, Middle Liddell, Lewis & Short, Morpheus analyses) behind the
word tool on [grammata](https://grammata.pages.dev).

This repository is published from a private working repository. It holds the
data and the scripts that build and check it; changes arrive here by sync,
so please open issues rather than pull requests.

## The grammars

| Work | Data | Source | License |
|---|---|---|---|
| Smyth, *A Greek Grammar for Colleges* (1920) | `data/smyth/` | Perseus Digital Library | CC BY-NC-SA 3.0 US |
| Allen & Greenough, *New Latin Grammar* (1903) | `data/ag/` | Perseus Digital Library | CC BY-SA 4.0 |
| Bennett, *New Latin Grammar* | `data/bennett/` | Alpheios | CC BY-NC-SA 3.0 US |
| Gildersleeve, *Syntax of Classical Greek* | `data/gildersleeve/` | Perseus Digital Library | Perseus "free" (non-commercial) |
| Goodwin, *Syntax of the Moods and Tenses of the Greek Verb* | `data/goodwin-gmt/` | Perseus Digital Library | Perseus "free" (non-commercial) |
| Monro, *A Grammar of the Homeric Dialect* | `data/monro/` | Dickinson College Commentaries | CC BY-SA 4.0 |
| Goodell, *A School Grammar of Attic Greek* | `data/goodell/` | Dickinson College Commentaries | CC BY-SA |

**Each work keeps its own license; there is no single license for the whole
repository.** Each `data/<work>/meta.json` records the source and its terms.
The non-commercial texts may be shared and adapted freely, but not used
commercially. For Gildersleeve and Goodwin, Perseus's terms also ask you to
credit Perseus, keep its availability statement, and offer Perseus any
changes you make. The lexica and Morpheus data in `data/wordtool/` are
Perseus data as distributed with Diogenes.

## What is here

| Path | What it holds |
|---|---|
| `data/<work>/sections.jsonl` | One record per printed section. Shape in `SPEC-section-ids.md`. |
| `data/<work>/meta.json` | Source, license, counts, and the anomalies each converter found. |
| `data/<work>/citations.json`, `data/citations-index.json` | Passage-to-section indexes, and one combined file keyed by passage across the grammars (`SPEC-citations-all.md`). |
| `data/smyth/index-english.json`, `index-greek.json` | Smyth's printed indexes, transcribed from the 1920 scan (`SPEC-index-english.md`). |
| `data/smyth/verbs.json`, `particles.json` | The verb list and particle landmarks (`SPEC-landmarks.md`). |
| `data/smyth/constructions.json` | Construction names to Smyth sections, from the AGDT guidelines (`SPEC-constructions.md`). |
| `data/smyth/topics.json`, `section-topics.json`, `topics/*.md` | Topics and the topic pages, every claim cited (`SPEC-topics.md`). |
| `data/smyth/crosswalk.json` | For each topic, the sections of the other grammars that treat it (`SPEC-crosswalk.md`). |
| `data/wordtool/` | The lexicon packs: byte-range files a static host serves with one Range request. |
| `scripts/` | A converter and a verifier for each grammar, the index and landmark builders, and `wordtool/` for the packs. |
| `grammar-*/src/` | The Dickinson and Perseus source files the converters read that are not fetched. |

## Corrections

The text is the print. Errors made in transmitting it (Perseus's typing, beta
code, conversion) are repaired in the converters, where each repair is
written down and checked by a verifier; the print itself is not emended
silently.

## Running the checks

Python 3, standard library only.

```
python3 scripts/fetch_sources.py   # the pinned Perseus and AGDT sources, once
python3 scripts/verify_smyth.py    # and the other verify_*.py
python3 scripts/wordtool/test_packs.py
```

CI (`.github/workflows/ci.yml`) runs every verifier on each push.
