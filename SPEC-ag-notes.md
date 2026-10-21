# Spec addendum: Allen & Greenough (`ag`)

Addendum to SPEC-section-ids.md, which stays the binding contract. This records
only what is specific to A&G. Written 2026-08-01, alongside `scripts/convert_ag.py`
and `scripts/verify_ag.py`.

## Source and licence

- File: `grammar-ag-tei/data/viaf39744457/001/viaf39744457.001.perseus-eng1.xml`
- Repository: https://github.com/PerseusDL/canonical-pdlrefwk
- Commit: `02768b0c37d6102be4899fc0eb57f9d348195243`
- Licence: CC BY-SA 4.0, Perseus Digital Library, funded by the NEH. Credit
  Perseus, keep the availability statement, offer Perseus any modifications.
- Edition: Ginn and Company, 1903. TEI P5 (EpiDoc conversion begun 2014); the
  Perseus release date in the header is 1997-12-16.
- The `grammar-ag-tei/` checkout is gitignored: it is a sparse clone, not our text.
- Not the source: the local `grammar-allen-greenough/` clone is the alpheios HTML
  re-rendering with murkier licensing.

## Numbering

- Printed sections **1–638**, no gaps, no duplicates. This matches SPEC-section-ids.md.
- The source carries **642** `smythp` markers. Markers 639–642 number the closing
  glossary as if it were four printed sections. It is back matter (below), so the
  data stops at 638 and the four extra markers are inventoried in
  `meta.anomalies.backMatter`.
- The TEI reuses Smyth's unit names (`smythp`, `smythsub`) verbatim; they carry no
  Smyth meaning here.

## Structure: markers, not containers

Smyth wraps each section in its own `div`. A&G does not: sections are **empty
`milestone` elements** dropped between the block-level children of a `div`. A
section owns every block that follows its marker in document order until the next
marker, which means a section routinely runs past the end of the `div` it started
in — 226 blocks in this text open a new `div` while continuing the previous
section. The converter walks the body once and assigns blocks to the marker in
force; `path` and `head` come from the `div` chain of the marker itself.

Structural `head` elements are metadata (they build `path` and the TOC) and never
appear in a section's `html` or `plain`.

## Anchor schemes

| unit | anchor | source |
| --- | --- | --- |
| lettered subsection | `#a`, `#b`, … | `milestone[@unit="smythsub"]/@n` |
| Note | `#n1`, `#n2`, … | `note[@place="inline"]/@n` |
| repeated Note label | `#n1-2`, `#n1-3`, … | second and later Note with the same printed label |
| footnote | `#fn1`, `#fn2`, … | `note[@place="foot"]`, numbered through the section |

- **Letters.** The source strips the printed "a." label and keeps only the marker,
  so a letter anchor renders as an empty `<span class="subsection" id="a">` at the
  marker's place. 961 letters come from markers; 5 more (§43 a, §49 a, §217 a b c)
  are recovered from labels the source left in the prose, under a narrow rule: the
  paragraph must open with an `emph` holding exactly "x.", the letter must occur
  once in the section, must not already be a marker, and must complete an unbroken
  a, b, c … run. Anything short of that is reported, not guessed.
- **Notes.** A&G's "Note 1" / "Note 2" units are `note[@place="inline"]`, and the
  printed label restarts inside each lettered subsection, so 123 sections repeat a
  label. The printed label stays in the record's `label` field; the anchor takes a
  `-2`, `-3` suffix in document order so anchors are unique within the section.
  Two notes carry no label at all and anchor as `#n` / `#n-2`.
- **Footnotes** have no printed label and number straight through the section
  (up to `#fn22`).
- `old_Subsub` and `old_Sub3` markers (98 of them) sit in front of paradigm titles
  and carry no citable label; they render as nothing.
- Cross-references to numbered sub-units ("§ 214. 2") and to Notes ("§ 266. N. 1")
  appear in the prose, but the source encodes only the section number inside the
  `ref`; the rest is loose text. No anchors are minted for them.

## Cross-references

- A `ref` carries the bare section number in `@n`; `@target="U"` is a constant and
  means nothing. Rendered as `<a data-ref="ag:N">`.
- A subsection citation ("§ 598. f") is split across three nodes: the `ref`, a "."
  in its tail, and an `emph` holding the letter. 356 of these in sections (380 in
  the whole body) get `data-anchor="f"`.
- Ranges are written `<ref>A</ref>–<ref>B</ref>`: 18 occurrences, 17 distinct.
- "ff." after a `ref` is the print abbreviation for "and following" and yields no
  range endpoint.

## Latin, macrons, and glosses

- Vowel length is **precomposed** in this source (ā is U+0101; there are no
  combining U+0304 macrons), and the file is already in NFC. The converter
  normalizes to NFC at parse anyway, which is a no-op here and keeps the pipeline's
  guarantee. `verify_ag.py` compares per-character macron and breve counts between
  the source blocks and the record text: they must match exactly.
- Latin is `foreign[@xml:lang="la"]` → `<span lang="la">`. 81 Greek runs
  (`xml:lang="greek"`) → `<span lang="grc">`; 3 French → `<span lang="fr">`. No
  untagged Greek exists in this text.
- `examples[]` uses the key **`la`** (not Smyth's `grc`): `{la, gloss, cite}`.
  `la` is the `cit/quote` text; `cite` is `bibl/@n`, a Perseus canonical-citation
  abbreviation such as `Verg. A. 6.653` — the TEI carries no URNs, so records have
  no `urn` field.
- A translation is often split across several `gloss` siblings with the print's
  small-capital words left bare between them, so the gloss is the whole run from
  the `cit` to the last `gloss` before the next `cit` or `bibl`. A `cit` whose next
  sibling is not a `gloss` has no translation (24 of 1800).
- The source omits whitespace at some `emph` boundaries inside quotes
  (`Thēbānōrumimperātōrem`). The data preserves the source text as it stands.

## Record shape

Identical to Smyth's, with `dialectNotes` (a Greek concern) replaced by `notes`:

```
{ work: "ag", n, id: "ag:N", letters: [...], notes: [{anchor, label, kind, html, plain}],
  path, head, html, plain, examples: [{la, gloss, cite}], refs, refRanges, citedBy,
  prev, next }
```

`kind` is `"note"` or `"footnote"`. As in Smyth, `sections.jsonl` carries no
`topics` field: topics are derived downstream, not extracted from the text.

## HTML

`p`, `table`/`row`/`cell`, `list`/`item` → `<ol>`/`<ul>` with `value` on numbered
items, `quote` → `<q lang="la">`, `bibl` → `<cite data-cite>`, `cit` →
`<span class="example">`, `gloss` → `<span class="gloss">`, `pb` →
`<span class="page-break" data-page>`, `figure` → `<span class="figure">`.
`emph` with no `rend` or `rend="ital"` → `<em>`; `strikethrough` → `<s>`; `lig`
and `center` → `<span class="rend-lig">` / `<span class="rend-center">`.

Blocks never nest inside `<p>`: lists (811), notes (715), and tables inside a
source `p` are lifted to sibling level, and non-row children of a `table` and
non-item children of a `list` are emitted in front of it, matching what a browser
foster-parents. A `note` inside phrasing-only markup (`emph`, `head`) renders as
`<span class="note">` rather than `<aside>`, keeping its anchor.

## Anomalies found

- **§609** declares one lettered subsection and labels it `e`; there is no a–d.
- **§221** (prepositions), **§514**, **§627** print letter labels that the source
  never marked — 54, 8, and 3 of them. §221 and §514 repeat a, b, c under each
  entry, so no unique anchor exists; §627's a, b, c are genuine but are not marked
  in a form the narrow rule accepts. Listed in `meta.anomalies.unmarkedLetterLabels`.
- **Two footnotes sit inside structural `head` elements** (both in the Prosody
  chapter) and so belong to no section. Their full text is in
  `meta.anomalies.unassignedElements`.
- **Three cross-references do not resolve**: §497 cites 1588 (no such section),
  §326 cites 641 and §603 cites 642 (both back-matter markers).
- One `cit` has no `bibl`; 24 have no gloss.

## Front and back matter (inventoried, not extracted)

- **Front matter**: a page marker and one paragraph before §1 — "Latin Grammar is
  usually treated under three heads…". Full text in `meta.anomalies.frontMatter`.
- **Back matter**: the div headed "GLOSSARY: OF TERMS USED IN GRAMMAR, RHETORIC,
  AND PROSODY", holding "Grammatical Terms", "Rhetorical Figures", and "Terms of
  Prosody" — 108 blocks, ~8,000 characters, 32 cross-references into the grammar,
  numbered 639–642 by the source. A good candidate for a later landmark or
  glossary route; it is not a printed section range.
- **No index.** The TEI carries none. A&G's printed English/Latin index is absent
  from this file; the alpheios re-rendering has it as `fullindex.htm`, and any
  future index landmark will need its own source and its own licence check.
