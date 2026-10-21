# SPEC: reverse citation index (passage → Smyth §§)

> This file describes the **Smyth** index only, which
> `scripts/build_citations_index.py` owns and which the rest of the
> pipeline never rewrites. The same index for Goodwin, Gildersleeve,
> Monro, Goodell and Allen & Greenough, and the combined cross-grammar
> file `data/citations-index.json`, are specified in
> **`SPEC-citations-all.md`**.

Answers, at runtime and with zero NLP: "which Smyth sections quote or cite
this passage?" Built by `scripts/build_citations_index.py` from
`data/smyth/sections.jsonl` into `data/smyth/citations.json`.

## Source of citations

Every classical-text citation in Smyth renders, via `scripts/convert_smyth.py`,
to `<cite data-cite="...">...</cite>` inside a section's `html` field — both
the ~3,047 citations paired with a Greek quotation (also duplicated in
`examples[].cite`) and the ~2,146 citations attached directly to foreign text
or bare prose that never made it into `examples[]`. The index is built by
scanning `html` for every `<cite data-cite="...">` tag, so it covers all
~5,193 citations from one source of truth, not just `examples[]`.

## Canonical passage key

```
<author-slug>.<locator>              (single-work corpora)
<author-slug>.<work-slug>.<locator>  (multi-work authors)
```

Both parts are built from a **hand-built normalization table** in
`build_citations_index.py` (`AUTHOR_WORK_TABLE`), keyed on the exact citation
prefix as it appears in Smyth (e.g. `"Xen. Anab."`, `"Thuc."`, `"Plat. Hipp.
Maj."`). There are 96 distinct prefixes in the source; each maps to one row:

| field | meaning |
|---|---|
| `author_full` | display name, e.g. "Xenophon" |
| `author_slug` | lowercase key segment, e.g. `xen` |
| `work_full` | the work abbreviation as Smyth writes it, e.g. "Anab.", or `None` for single-work authors |
| `work_slug` | lowercase key segment, e.g. `anab`, or `None` |

Slugs are the work/author abbreviation lowercased, periods stripped, internal
spaces turned into hyphens (e.g. "Hipp. Maj." → `hipp-maj`, "Const. Ath." →
`const-ath`). This is a closed, reviewable table, not an algorithm run over
arbitrary input — a 97th prefix appearing in a future edit will not silently
mis-key; the build script sends anything not in the table to `meta.unparsed`
instead of guessing.

**Locator** is the citation text after the author/work prefix, kept verbatim
(already plain ASCII digits, dots, and a single trailing lowercase letter in
this source — no normalization needed). Its shape is fixed per work, not
declared separately in the JSON, because a reader integration already knows
its own granularity per work:

| granularity | example works | shape |
|---|---|---|
| Stephanus page + letter | all Plato dialogues | `17b` |
| book.line | Homer (Il., Od.) | `1.352` |
| book.chapter.section | Xen. Anab., Cyrop., Hell., Mem. | `1.2.3` |
| chapter.section | Xen. Ages., Cav., Ec., Hiero, Horse., Hunt., Ways | `1.2` |
| single running section | Xen. Apol., Sym. | `12` |
| single verse line | tragedy/comedy (Aesch., Soph., Eur., Aristoph.) | `567` |
| oration/book.section | Thuc., Hdt., Dem., Lys., Isoc., Aeschin., Andoc., Antiph., Isaeus, Diog. Laert. | `18.199` |
| single sequential number | Men. Sent. | `551` |
| ode.line | Pind. O. | `1.3` |
| chapter.section | Stob. Flor. | `120.13` |

**Worked examples** (why this scheme, not CTS URNs or a reader's own work
id): none of the three reader repos (plato-reader, homer-reader,
aristotle-reader — see research below) key passages by CTS URN or by a
citation string; each has its own runtime address format (Stephanus
page+letter for Plato, book.line for Homer, Bekker column+line for
Aristotle) and its own work-id casing convention (`Apology` vs `iliad` vs
`DA`). No single existing scheme is "the" reader format. Reusing Smyth's own
citation vocabulary, normalized into a small closed table, means:

- `Plat. Apol. 17b` → `plat.apol.17b`
- `Hom. Il. 1.352` → `hom.il.1.352`
- `Xen. Anab. 1.2.3` → `xen.anab.1.2.3`
- `Thuc. 4.47` → `thuc.4.47`
- `Dem. 18.199` → `dem.18.199`

A reader resolves its own runtime state (work id + locator) to this key with
a small static lookup of its own — e.g. plato-reader already knows a passage
is `{ work: "Apology", column: "17b" }`; it needs one more static table
entry (`Apology → plat.apol`) to look up `plat.apol.17b` in this index. That
table is the reader's integration work, out of scope here; this index's job
is to be a single stable, auditable target for it. Do **not** try to reverse
the key by splitting on `.` — the number of dot-separated locator components
varies per work (see table above), so only `AUTHOR_WORK_TABLE` disambiguates
where the work-slug ends and the locator begins.

### Special case: Alcibiades I

Smyth cites `Plat. Alc. 1 110d` / `Plat. Alc. 2 113c` — the dialogue number
(1 or 2) sits *between* the work abbreviation and the Stephanus locator, not
after it like every other multi-part work title. The build script detects
this one case (`Plat. Alc. <digit> <locator>`) and folds the digit into the
work slug (`alc-1`, `alc-2`) before the normal table lookup, so the key is
`plat.alc-1.110d`. Only `Alc. 1` appears in the current data; `Alc. 2` is in
the table pre-emptively since the dialogue exists and could appear after a
future TEI update.

## Ranges

**None occur in the source.** Every one of the 5,193 citations was checked:
zero contain a hyphen, en dash, em dash, or comma-separated list (`grep -c
'[-–—,]' cites.tsv` → 0 across all extracted citation strings). Smyth cites a
single point locator every time it cites a passage at all. The index
therefore has no range representation to design — if a future TEI update
introduces one, `build_citations_index.py`'s citation regex will fail to
match it and it will land in `meta.unparsed` rather than being silently
mis-split.

## Subsection anchor (`anchor`)

Most sections divide into Smyth's own lettered subsections (e.g. "See `292
d`" marks subsection **d** of §292). `anchor` names **the nearest preceding
lettered anchor id in document order** — i.e. where a reader should scroll to
land on or just above the citation — not a containment claim.

The build script tracks, while scanning each section's `html` in document
order, the most recent element with `id="<letter><digit>?"` (`<strong
id="a">`, `<p id="a">`, or `<span id="a">` — Smyth uses all three depending
on where the letter starts) and attaches it as `anchor` to every `<cite>`
that follows until the next such id. Dialect-note and footnote ids (`D`,
`D1`, `fn1`, `fn2`) are excluded by the id pattern (`^[a-z]\d?$`,
case-sensitive) and never emitted as an anchor value. `anchor` is omitted
when no lettered anchor precedes the citation in its section.

Two known cases where the nearest preceding anchor is *not* the citation's
containing subsection, both harmless as scroll targets because the target
still sits immediately above the citation on the same page:

- 4 citations inside a dialect note that follows the last lettered
  subsection (§44 → `a`, §325 → `f`, §773 → `b` ×2) take that letter rather
  than the note's own `D` id.
- Where a short lettered note precedes unlettered content, that content's
  citations inherit the note's letter — §2744 is the clearest instance, its
  subsection **a** being a one-sentence aside ahead of the section's main
  numbered list.

Every id emitted as an anchor is a real, unique fragment on the section's
page (`verify_smyth.py` check 6 reports zero duplicate HTML ids), so
`/smyth/<n>#<anchor>` always resolves.

## JSON shape

`data/smyth/citations.json`:

```jsonc
{
  "plat.apol.17b": [
    {"section": 1270},
    {"section": 1411}
  ],
  "hom.il.21.567": [
    {"section": 44, "anchor": "a"}
  ],
  "_meta": {
    "sourceCitations": 5193,
    "parsed": 5187,
    "unparsed": 6,
    "uniqueKeys": 4183,
    "byAuthor": {"xen": 1259, "thuc": 698, "...": "..."},
    "unparsedCitations": [
      {"text": "C.I.A. /lref>", "section": 904, "anchor": "c"}
    ]
  }
}
```

Passage keys are sorted lexicographically; each key's section list is sorted
by `(section, anchor)`; duplicate `(section, anchor)` pairs for the same key
are collapsed (a section that quotes the same passage twice in different
examples produces one entry, not two). All output is deterministic — same
input, byte-identical output on every run.

`_meta` is a reserved key that can never collide with a real passage key
(real keys always start with a lowercase author slug immediately followed by
`.`, never `_`).

## Unparsed citations

6 of the 5,193 source citations do not match any recognizable
author/locator shape: `C.I.A. /lref&gt;` (×5) and `I.G.A. /lref&gt;` (×1).
These come from the TEI's `<bibl>` elements for two Attic inscription corpora
(*Corpus Inscriptionum Atticarum*, *Inscriptiones Graecae Antiquissimae*)
whose `n` attribute is empty and whose text content is itself truncated
mid-tag (`/lref>`, missing a closing angle bracket in the source) —
`scripts/convert_smyth.py`'s `bibl.get("n") or text_of(bibl)` fallback
carries the broken fragment straight into `data-cite`. This is a pre-existing
defect in `data/smyth/sections.jsonl`/`smyth_eng_u.xml` (already flagged in
`meta.json`'s `biblWithoutN` list), out of scope to fix here (`sections.jsonl`
and `convert_smyth.py` are not to be modified by this task). These 6 are
listed in full, per-occurrence, in `_meta.unparsedCitations` — never dropped,
never guessed at.

Any citation string this build encounters that does not match the
`AUTHOR_WORK_TABLE` (e.g. a 97th work abbreviation introduced by a future
source edit) is treated the same way: added to `unparsedCitations` rather
than silently mis-keyed or dropped, and the run still succeeds.
