# SPEC: Smyth English Index (print, 1920)

The Perseus digitization of Smyth carries the grammar but not the back matter's
two indexes. This spec covers phase 1: the **English Index**, recovered from a
public-domain page scan and transcribed by hand from the images. (The Greek
Index, pages 757-784, is phase 2 and is not touched here.)

Index entries cite **section numbers**, not pages, so they drop straight into
the scheme in `SPEC-section-ids.md` without a page-to-section mapping step.

---

## 1. Provenance

| | |
|---|---|
| Work | Herbert Weir Smyth, *A Greek Grammar for Colleges* |
| Imprint | New York: American Book Company, 1920 |
| Scan | archive.org item `smyth-greek-grammar-for-colleges-1920` |
| Item URL | https://archive.org/details/smyth-greek-grammar-for-colleges-1920 |
| Rights | Public Domain Mark 1.0 (item metadata); work published 1920, not in copyright |
| English Index | printed pages **723-756** (34 pages) |
| Leaf mapping | `leaf = page + 13`, so leaves **736-769** |
| Greek Index | starts printed page 757 (leaf 770) — out of scope |

### Edition verification

- The item's own metadata gives title, publisher and 1920 date.
- The body runs §1-3048, matching `data/smyth/sections.jsonl` exactly
  (3048 rows, no gaps).
- Spot-check: the grammar's §1 in the scan opens "The Greek alphabet has
  twenty-four letters", the same text as `sections.jsonl` §1.
- The index's own citations were checked against the section list wholesale:
  every section number cited resolves inside 1-3048 (see the verify report).

A second, independent scan of the same edition exists as
`agreekgrammarfo02smytgoog` (Google/americana, 804 leaves). Its page images are
only 725x1100, too coarse for a dense index page, so it was used only to
cross-check the page range, never for transcription.

### Why not OCR

Both scans carry archive.org OCR. On this index it is unusable: the Google
text renders `1325-1327` as `1S2,'>-1327` and `1356-1360` as `18M-I300`. A
section number that is wrong is worse than one that is missing, so every entry
here was read off the page image by eye.

---

## 2. Image preparation

`index-scan/prep.py` reproduces the whole pipeline. For each leaf:

1. Fetch the JP2 from the item's `_jp2.zip` (1328x1929, 8-bit greyscale) at
   `.../_jp2.zip/..._jp2%2F..._0NNN.jp2`.
2. Save unaltered as `index-scan/page-0NNN.png`, named by **printed page**.
3. Find the printed vertical rule between the columns: the sharpest ink column
   between 0.38w and 0.62w of the page body.
4. Cut two column boxes either side of the rule, trim each to its content
   bounding box with 10px padding, then split each column at the blank
   line-gap nearest its vertical middle — so no printed line is ever cut in
   half.
5. Upscale (LANCZOS) to at most 1900px high and 1400px wide.

Result, per page: `index-scan/crops/page-0NNN-{c1,c2}-{1,2}.png`.

`index-scan/` is gitignored (138 MB of images) except for two small files that
are committed: `index-scan/prep.py`, which regenerates every image, and
`index-scan/TRANSCRIBER-CONTRACT.md`, the working brief handed to each
transcriber (an operational restatement of sections 3 and 4 below).

`index-scan-manifest.json` is committed and records, per page: printed page,
leaf, image filename, tile filenames, the exact archive.org URL, and a SHA-256
prefix of the PNG, so a second transcriber can refetch byte-identical images.

---

## 3. Per-page transcription files

**This is the primary record.** `data/smyth/index-english.json` is derived from
it; if the two ever disagree, the page files win.

One file per printed page: `data/smyth/index-english-pages/page-0NNN.json`.

```json
{
 "page": 723,
 "leaf": 736,
 "archiveId": "smyth-greek-grammar-for-colleges-1920",
 "image": "index-scan/page-0723.png",
 "columns": 2,
 "runningHead": "ENGLISH INDEX",
 "pageNotes": "",
 "lines":   [ {"col": 1, "text": "..."} ],
 "entries": [ {...} ],
 "unreadable": [],
 "counts": {"linesCol1": 40, "linesCol2": 40, "lines": 80, "entries": 13}
}
```

### Layout and reading order

The index is set in **two columns** divided by a printed vertical rule.
`columns` records what the transcriber actually observed on that page, so a
deviation shows up as data rather than as a silent assumption.

Reading order is strict: **left column top to bottom, then right column top to
bottom.** Every `lines` entry carries its `col`, and the `lines` array must be
in that order — the verify script fails a page whose column tags are not
monotonic.

Running heads (`723` / `ENGLISH INDEX`) and the foot folio are not index
content: the head goes in `runningHead`, the folio is dropped. Page 723 carries
a full-width display title above both columns, noted in `pageNotes`. Any other
deviation — a third column, a full-width line, a standalone letter heading —
goes in `pageNotes` verbatim.

Three things that look like lines but are not, and so are excluded from `lines`
and recorded in `pageNotes` instead:

- the blank line the compositor leaves at a **letter change**. This index sets
  no letter headings at all, only a blank; that is why one column can hold 47
  lines against the other's 48;
- printer's **signature lines** at the foot (`GREEK GRAM. — 47` on p. 737,
  `— 48` on p. 753);
- ink specks and stray sorts in the margins.

The print sets a thin space before `;` and `,`; it is normalised away
(`1371; separation`, not `1371 ; separation`).

### `lines`

The raw printed lines, in reading order, exactly as set, **including
end-of-line hyphens**. Lines are never joined here; joining happens in
`entries[].raw`. This is what makes two independent passes diffable line by
line.

### `entries`

```json
{
 "headword": "Abstract",
 "raw": "Abstract, nouns, gender, 199 c, 840; ... See Quality, Action.",
 "col": 1,
 "wrapped": false,
 "refs": [ {"verbatim": "199 c", "n": 199, "anchor": "c"} ],
 "sub": [ {"label": "Numbers", "raw": "Numbers, 354 e.", "refs": [...]} ],
 "crossRefs": ["Quality", "Action"],
 "notes": "optional"
}
```

- `headword` — the entry word(s) up to the first comma, verbatim, never empty.
- `raw` — the whole entry paragraph as one string. Line breaks join with a
  single space; a word-division hyphen at a line end is deleted and the halves
  join with nothing (`corre-` + `sponding` -> `corresponding`).
- `col` — the column the entry **starts** in.
- `sub` — sub-entries. In the print these are paragraphs whose first line is
  indented further than the main entry's continuation lines, beginning with a
  capitalised word; they belong to the preceding main entry. Omitted when none.
- `crossRefs` — targets of "See X" / "See also X". Omitted when none.

### Wrapping

An entry that breaks across the column rule or the page edge is one entry, not
two:

- **foot of col 1 -> head of col 2**: stitched inside the page file, with
  `"wrapped": true, "wrapNote": "col1->col2"`.
- **across a page break**: NOT stitched in the page files, because each page
  file must hold exactly what is on that page. The earlier page carries the
  fragment with `"wrapped": true, "wrapNote": "continues on next page"`; the
  later page carries its fragment with
  `"wrapNote": "continued from previous page"`. `build_index_english.py`
  stitches the pair into one final entry.

---

## 4. Reference notation

Every ref keeps `verbatim`, the citation string exactly as printed. The
normalised fields sit alongside it, so a disputed parse can always be checked
against what the page actually says.

| printed | normalised |
|---|---|
| `1289` | `{"verbatim":"1289","n":1289}` |
| `1348 b` | `{"verbatim":"1348 b","n":1348,"anchor":"b"}` |
| `2001-2007` | `{"verbatim":"2001-2007","n":2001,"to":2007}` |
| `858. 6` | `{"verbatim":"858. 6","n":858,"anchor":"6"}` |
| `863 a 2` | `{"verbatim":"863 a 2","n":863,"anchor":"a 2"}` |
| `1554 a N. 1` | `{"verbatim":"1554 a N. 1","n":1554,"anchor":"a","note":"N. 1"}` |
| `991 b N.` | `{"verbatim":"991 b N.","n":991,"anchor":"b","note":"N."}` |
| `211 ff.` | `{"verbatim":"211 ff.","n":211,"ff":true}` |
| `897 (2)` | `{"verbatim":"897 (2)","n":897,"anchor":"(2)"}` |
| `28 D` | `{"verbatim":"28 D","n":28,"anchor":"D"}` |
| `81 D 1` | `{"verbatim":"81 D 1","n":81,"anchor":"D 1"}` |
| `p. 188` | `{"verbatim":"p. 188","nonSection":true}` |
| `Intr. C` | `{"verbatim":"Intr. C","nonSection":true}` |

`n` is the section number, `to` the inclusive end of a range, `anchor` the
subdivision within the section, `note` Smyth's `N.` (note) marker, `ff` the
open-ended "and following". A ref with no `n` is not a section citation and is
listed in `_meta.unresolvedRefs`.

### The two small-capital markers

They look alike on the page and are handled differently:

- **`N.`** is Smyth's *note*. It goes in `note`, never in `anchor`, because it
  follows whatever subdivision letter is already there (`1554 a N. 1`).
- **`D`** is the *dialect* marker. It behaves as a subdivision label, so it goes
  in `anchor`, capitalised as printed, carrying any number after it (`D 1`).
  Small-capital `A`, `B`, `C` labelling a section's major subdivisions
  (`2076 A N.`) are anchors on the same footing.

The point is dropped inside `anchor`/`note`; `verbatim` keeps it where the print
sets one. Transcribers on this pass split on this: some filed `D` under `note`.
`build_index_english.py` does not fix it — the page files were normalised in
place, so the committed record is consistent, and this rule is now in the
transcriber's brief.

### Inherited anchors

The print elides the section number inside runs of subdivisions.

1. **Bare letter.** `264 a, e, 271` = 264 a, 264 e, 271. A bare letter always
   inherits the previous ref's section number, flagged `"inherited": true`.
2. **Bare number.** `858. 6, 9` = 858. 6 and 858. 9. A bare number inherits
   **only** when the previous ref already carried a numeric anchor and the bare
   number is **less than 20**. `Dentals, 16; before dentals, 83; before μ, 86,
   87` has no numeric anchor in play, so 86 and 87 are plain sections.
3. Where the inherited anchor sits under a letter, the letter carries too:
   `863 a 2, 3, b 2` = `863 a 2`, `863 a 3` (inherited), `863 b 2`.

Anything the transcriber could not settle carries `"uncertain": true` plus an
`entry.notes` explanation. Nothing is silently chosen. This pass produced 97
inherited anchors and 7 uncertain refs.

**Where the under-20 test fails.** Smyth's suffix lists (§§859-865) number
their subdivisions well past 20, so runs like `861. 11, 19, 22, 23` and
`863 a 16, 21, 24` break the heuristic: read literally, `22` and `23` would be
§22 and §23, which is nonsense in a list of noun suffixes. The transcribers
recorded these as inherited anchors **and** flagged them `"uncertain": true`
rather than trust either reading. They are the bulk of the 7 uncertain refs:
`Place` (p. 745), `Suffixes` (pp. 752-753), plus `Digamma` (p. 732) and
`Proper names` (p. 748). A second pass should be given the same latitude, so
the disagreement — if there is one — lands on the same refs.

### Unreadable numbers

A digit that cannot be read is never guessed. The ref becomes
`{"verbatim": "<what is legible>", "unreadable": true}`, the page number goes
into the page file's `unreadable` array, and the final JSON surfaces it under
`_meta.unresolvedRefs`.

---

## 5. Final file

`data/smyth/index-english.json`, built by `scripts/build_index_english.py`:

```json
{
 "work": "smyth",
 "source": {"archiveId": "...", "edition": "...", "pages": "723-756",
            "leaves": "736-769", "url": "..."},
 "entries": [
   {"headword": "...", "raw": "...", "pages": [723], "wrapped": false,
    "refs": [...], "sub": [...], "crossRefs": [...], "notes": "..."}
 ],
 "_meta": {"status": "print-1920", "entryCount": 0, "refCount": 0,
           "pageCount": 34,
           "perPageSource": "data/smyth/index-english-pages/page-NNNN.json",
           "unresolvedRefs": []}
}
```

Entries keep the print's own order — alphabetical as the 1920 compositor set
it, not re-sorted. The build step does exactly two things beyond concatenation:
stitch page-break continuations, and fold page numbers into `entries[].pages`.

Stitching has to decide *what* the fragment continues. A page can break in the
middle of the main paragraph or in the middle of a sub-entry; a sub-entry is
treated as still open when its text does not end in a full point, and the
fragment then attaches to it rather than to the main paragraph. Joining follows
what the break falls on: `preced-` + `ing` drops the hyphen, `496-` + `531`
keeps it and closes the range into one ref (flagged `splitAcrossPages`), and an
ordinary break takes a single space.

### As built

| | |
|---|---|
| pages | 34 (723-756) |
| entries | 752 |
| refs | 5308 |
| page-break continuations stitched | 22 |
| inherited anchors | 97 |
| uncertain refs | 7 |
| unresolved refs | 11 — all Introduction citations (`Intr. B`-`Intr. F`) |
| unreadable | 0 |

---

## 6. Verification

`python3 scripts/verify_index_english.py` (stdlib only). Checks:

1. all 34 page files present, well formed, honest about their own `counts`,
   and in column reading order;
2. the final JSON is derivable from the page files — entry arithmetic and text
   traceability;
3. every `n` and `to` exists in `sections.jsonl` (1-3048);
4. single-letter anchors against the target section's `letters[]` — a **WARN**,
   not a failure, because the TEI only marks a subset of Smyth's lettered
   subdivisions;
5. no empty headwords; adjacent duplicates and ref-less entries reported;
6. alphabetical order, tolerance **25 descents** (see below);
7. ref counts per page against the median, to catch a half-transcribed page;
8. letter coverage A-Z;
9. a seeded 30-entry QA sample (`--sample`, `--seed`): for each sampled entry,
   does the text at a cited section actually mention the headword? Misses are
   listed as *suspects* and never deleted — the heuristic is lexical and the
   print's shorthand defeats it often enough that a suspect is a prompt to look
   at the page, not a verdict.

### Ordering tolerance

The 1920 index is not machine-sorted. It files some entries by the sense of a
phrase rather than letter by letter. A strict `sorted()` therefore flags
descents that are correct transcriptions of an imperfect print. The check
accepts up to 25 and prints every one with its page number so each can be
checked against the image.

This pass produces four, all verified against the page images as the print's
own order:

| page | the print sets |
|---|---|
| 737 | `Impersonal verbs` then `Impersonal and personal constr.` |
| 745 | `Person concerned` then `Person` |
| 746 | `Potential optative` then `Potential` |
| 756 | `Whole and part` then `Whole` |

### Result of this pass

All checks PASS. Three WARNs, each explained:

- 4 of 635 single-letter anchors are absent from the target section's
  `letters[]` (`2110 a`, `2383 c`, `2163 c`, `659 d`) — the TEI marks only a
  subset of Smyth's lettered subdivisions;
- 2 adjacent headword repeats, `Potential optative` and `Sentence` — both are
  genuinely two consecutive main entries in the print (`Potential optative,
  with ἄν` / `without ἄν`);
- no entry under **X**. Confirmed against p. 756, which runs `Wondering`,
  `Yes`, `Yes and No questions`, `Yielding`, `Yod`, `Zeugma`. The index has no
  X.

Entries per letter: A 90, B 11, C 83, D 57, E 44, F 23, G 11, H 20, I 42, J 2,
K 4, L 16, M 30, N 19, O 25, P 102, Q 4, R 37, S 68, T 28, U 5, V 15, W 11,
X 0, Y 4, Z 1.

The seeded QA sample matched 29 of 30. The single suspect, `Wanting` at §1396,
was checked by hand and is right: §1396 is "the genitive with verbs signifying
to want, lack, empty" — the heuristic stems the headword to `wanti` and the
section says `want`.

---

## 7. Known uncertainties

- **Punctuation at line ends.** In this typeface a comma that has lost its tail
  in printing is not reliably distinguishable from a full point (e.g. after
  `1744` on page 723). Punctuation never changes the refs, so these are read in
  context and noted on the entry.
- **`N.` vs `n.`** Smyth's note marker is set in small capitals; where the scan
  is weak the two can be confused. Kept as printed.
- **Numeric subdivisions.** Section anchors like `858. 6` have no counterpart
  in the TEI, whose `letters[]` only records lettered subdivisions. They are
  recorded but cannot be validated against `sections.jsonl`.
- **Inherited anchors** are an editorial reading of the print's ellipsis, not a
  literal transcription. `verbatim` always preserves the literal token so the
  reading can be re-checked or rejected downstream.
- **Three independent passes.** This transcription is one pass. The per-page
  file format above exists so a second and third pass can be produced under the
  same conventions and diffed mechanically, entry by entry and line by line.

## Adjudication (2026-08-02)

Three independent passes — Opus (vision transcription), LlamaParse
(parse_page_with_agent), and Churro via Stanford HistoryGenie (run by the
owner) — were token-aligned and diffed. 259 disputed sites: 62 pure
letter-case disputes auto-resolved to the small-capital print forms, 32
subentry-segmentation disputes auto-resolved by the print's own indentation
(ink-projection test), and the remainder ruled by the owner against
line-exact image crops. Six content edits resulted (see
data/smyth/index-english-adjudication.json for the complete ruling log);
the Opus transcription was upheld everywhere else. Verification re-run
post-edit: all checks pass.
