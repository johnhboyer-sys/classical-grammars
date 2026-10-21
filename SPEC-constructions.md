# Spec: construction → Smyth § table

Status: drafted 2026-08-01, branch `construction-table`. Seed data for the platform's
construction layer. Output: `data/smyth/constructions.json`.

## What this is

Named grammatical constructions mapped to the Smyth §§ that govern them, harvested
from the annotation guidelines of the Ancient Greek Dependency Treebank. Those
guidelines are built section by section on Smyth and deep-link him throughout, so
they are the densest published construction→§ mapping that exists.

This powers "this sentence has a conditional clause → Smyth §2280–2368" in the
readers, and Pedalion-style construction browsing on the site.

## Provenance and licence

- Repository: <https://github.com/PerseusDL/treebank_data>, pinned at commit
  `bf4334f0af5e13d16b04c1cccd6237e683ac6f5f`.
- File: `AGDT2/guidelines/Greek_guidelines_2.5.md`.
- Author: Giuseppe G. A. Celano. Cite as the repo asks:
  > Celano, Giuseppe G. A. 2014. Guidelines for the annotation of the Ancient Greek
  > Dependency Treebank 2.0. https://github.com/PerseusDL/treebank_data/edit/master/AGDT2/guidelines
- Copyright 2014 The Perseus Digital Library, Tufts University.
- Licence: **CC BY-SA 3.0 US** (<http://creativecommons.org/licenses/by-sa/3.0/us/>).
  ShareAlike is viral: anything derived from `constructions.json` — including any
  page that renders construction names or context paths verbatim — must carry the
  attribution above and be offered under a compatible licence. Keep this data in its
  own file so the obligation stays traceable.
- Target: Smyth, *Greek Grammar for Colleges* (1920), the Perseus text already in
  `data/smyth/sections.jsonl`. §-numbers are that edition's.

The clone lives at `grammar-agdt/` and is gitignored, like the other source clones.
Re-create it with:

```
git clone --depth 1 --filter=blob:none --sparse \
  https://github.com/PerseusDL/treebank_data grammar-agdt
cd grammar-agdt && git sparse-checkout set AGDT2/guidelines
```

`Greek_guidelines.md`, `Greek_guidelines_2.5.md` and `Greek_guidelines.html` carry an
identical set of Smyth links; the two `.md` files differ only in the version number in
their title. `_2.5` is used as the newest.

## Link forms found

One family only. No `smythp=`, no `%3Asection%3D`, no alpheios `#sNNNN`, no bare
"Smyth 1234" prose citations — all zero in this source.

| form | count |
|---|---|
| `http://www.perseus.tufts.edu/hopper/text?doc=Smyth+grammar+NNNN&fromdoc=Perseus%3Atext%3A1999.04.0007` | 619 |
| same over `https` | 3 |
| `…?doc=Smyfth+grammar+NNNN…` (typo in `Smyth`) | 1 |
| `http://www.perseus.txufts.edu/…` (typo in host) | 1 |
| **total** | **624** |

The two typo URLs are dead as links but their section number is unambiguous, so they
are mapped and listed in `meta.malformedLinks` rather than dropped.

## Ranges

The guidelines write a range as two links joined by a dash:
`<a …1297>1297</a>–<a …1305>1305</a>`. 200 of the 624 links open such a pair
(197 en dash, 3 hyphen). A pair is recognised only when both anchors are Smyth links
whose visible text is a section number and the only thing between them is a dash — no
looser heuristic, and no ranges are inferred from prose.

Ranges are **stored as ranges**, `{"n": 1297, "to": 1305}`, not expanded. Expanding
would be lossy in the other direction: the introduction cites the whole advanced-syntax
layer as `900–2687`, which would flood the table with 1,788 spurious rows. This matches
`SPEC-section-ids.md`, where `/smyth/2070-2078` is already a first-class URL. The
right-hand link of a pair is counted as a link but is not also emitted as a standalone
citation.

## Record shape

```json
{
  "meta": { "source": {...}, "target": {...}, "counts": {...},
            "linkForms": {...}, "malformedLinks": [], "unmappableLinks": [],
            "unnamedContexts": [], "emptyContexts": [] },
  "entries": [
    {
      "construction": "genitive of possession or belonging",
      "agdtContext": "Genitive > dependent > genitive proper > genitive of possession or belonging",
      "contextKind": "list-item",
      "sections": [{ "n": 1297, "to": 1305 }],
      "sourceFile": "AGDT2/guidelines/Greek_guidelines_2.5.md",
      "sourceHeading": "4 (Smyth's Grammar) Advanced syntax layer / semantic layer > 4.1 Morphosyntactic tagset > 4.1.1 Syntax of the case > 4.1.1.2 Genitive"
    }
  ]
}
```

- `construction` — the source's own label, never invented. Cleaning is limited to
  stripping citation apparatus: a parenthetical is removed only if what remains after
  deleting digits, dashes, punctuation and the tokens `SG`, `noun`, `verb`, `see`,
  `also`, `and`, `or`, `treeN` is empty. So `genitive of quality (SG 1320–1321)` becomes
  `genitive of quality`, while `(with ἀπό, διά, ἐξ) instrument or means` is left alone.
  Names are as generic as the source's own menus: leaf labels like `time`, `cause`,
  `dependent` are real AGDT options and are kept — `agdtContext` disambiguates them.
- `agdtContext` — where the name sits in the annotator's decision tree, `>`-joined.
  For list items: the enclosing heading's title followed by the chain of ancestor
  `<li>` labels. For table rows: the source's single table caption (a fixed string in the builder, matching the caption verbatim). For prose and headings: the
  heading breadcrumb.
- `contextKind` — how precise the mapping is. Filter on this.
  - `list-item` (144 entries) — the annotation algorithm's own menus. Highest
    precision: a named option with its governing §§ attached.
  - `table-row` (39) — the semantic-role table. The name is the row's first cell;
    the §§ pool the "Greek examples from SG" and "Remarks" columns, so a few are
    contrastive rather than definitional (e.g. `measure` carries §1317 from a remark
    distinguishing it from the partitive genitive).
  - `heading` (18) — mostly the adposition sections, where the § is linked from the
    heading itself (`4.1.1.5.1 ἀμφί` → §1681).
  - `prose` (53) — links in the body text under a heading; the construction is that
    heading's title. Loosest: an entry like `Introduction` pools everything the intro
    cites. Useful as "§§ discussed here", not as a definition.
- `sections` — `{n}`, plus `anchor` for a lettered subsection (one occurrence: §2112 b)
  and `to` for a range. Sorted, deduplicated.
- `sourceHeading` — full numbered heading breadcrumb, for provenance and for telling
  same-named entries apart (`dependent` appears once each under Genitive, Dative and
  Accusative).

Entries are keyed by `(construction, agdtContext, contextKind, sourceHeading)` and
sorted by that key, case-folded on the name. A § cited under several constructions
appears under each. Consumers wanting one row per name should merge on `construction`
after filtering by `contextKind`.

## Extraction method

`scripts/build_constructions.py`, stdlib only, deterministic.

1. Parse the guidelines with a forgiving `html.parser` tree builder — unmatched end
   tags ignored, unclosed tags left open. Strict parsing is not an option: the source
   uses `<a id="…">` anchors that wrap whole sections without closing in place.
2. Walk in document order, tracking the numbered heading breadcrumb (`4.1.1.2` inherits
   `4`, `4.1`, `4.1.1`) and, for each Smyth link, its ancestor chain.
3. Resolve context innermost-first: enclosing `<li>` → enclosing table row → enclosing
   heading → current heading. A list item's label is its own text with nested
   `<ul>`/`<ol>` subtrees excluded.
4. Detect range pairs among sibling nodes; mark the right-hand link consumed.
5. Group, sort, write with `sort_keys=True, indent=2, ensure_ascii=False`.

A link that cannot be placed is excluded from `entries` but audited in meta: `malformedLinks`
(typo URLs), `unmappableLinks` (§ absent from `sections.jsonl`), `unnamedContexts`
(link whose context yields no name), `emptyContexts`. Only `malformedLinks` is
non-empty.

## Verification

`scripts/verify_constructions.py` (exit 0 = pass). It re-runs the builder twice, so it
rewrites the output file idempotently.

- determinism: two builds byte-identical, and the committed file matches a fresh build
- every Smyth link in the source is accounted for (624 = 624)
- link and distinct-§ counts within 10% of the prior estimates (~623, ~273)
- every cited § — including every § inside a range — exists in `sections.jsonl`
- no range ends before it starts
- no empty section list, no empty construction name, no empty context, no missing
  `sourceFile`
- entry keys unique, entries in canonical order, no duplicate sections within an entry
- `unmappableLinks` and `unnamedContexts` both empty

## Known limits

- Coverage is the AGDT annotator's decision tree, not all of Greek syntax. Conditional
  sentences appear as `conditional clause` (§2280–2368) and `conditional relative
  clause` (§2560–2573); there is no finer split into future/general/contrafactual,
  because the annotation scheme does not make one. The construction layer will need a
  second, hand-curated source for those distinctions.
- Names are English (plus Greek adpositions) and lower-case as the source writes them;
  no normalisation, no slugs. Slugging is a downstream decision.
- `prose` entries are context, not definitions. Ship the site's construction browser
  off `list-item` + `table-row` + `heading` first.
