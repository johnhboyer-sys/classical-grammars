# SPEC: reverse citation index across every grammar (passage → §§)

`SPEC-citations.md` describes the Smyth-only index. This one covers the rest
of the corpus and the combined file, so that

> which sections of any grammar we own discuss Thucydides 1.9?

is one lookup rather than six.

Built by `scripts/build_citations_all.py`; checked by
`scripts/verify_citations_all.py`. Both are stdlib-only and offline.

## Files

| file | built by | contents |
|---|---|---|
| `data/smyth/citations.json` | `build_citations_index.py` | Smyth. **Not touched by this pipeline** — `build_citations_all.py` reads it and never writes it. |
| `data/goodwin-gmt/citations.json` | `build_citations_all.py` | Goodwin, *Moods and Tenses* |
| `data/gildersleeve/citations.json` | " | Gildersleeve, *Syntax of Classical Greek* |
| `data/monro/citations.json` | " | Monro, *Homeric Dialect* |
| `data/goodell/citations.json` | " | Goodell, *School Grammar of Attic Greek* |
| `data/ag/citations.json` | " | Allen & Greenough, *New Latin Grammar* |
| `data/citations-index.json` | " | all six, keyed by passage |

The five per-grammar files have the shape of Smyth's, with four extra
`_meta` fields — `work`, `unparsedRate`, `tablePrefixes` and
`unparsedByReason` — and a `reason` on every entry in
`_meta.unparsedCitations` naming the rule that rejected it:

```jsonc
"unparsedByReason": {
  "locator truncated (too shallow for the work)": 135,
  "no prefix in this grammar's table": 128,
  "leading element impossible for the work": 10,
  "locator does not parse": 1
},
"unparsedCitations": [
  {"text": "Thuc.  76.4", "section": 632, "anchor": null,
   "reason": "locator '76.4' begins at 76, and thuc has only 8: a reference whose leading element the print's compressed list dropped"}
]
```

### Bennett is not here — an honest gap

Bennett's *New Latin Grammar* has no citation data to index. Its HTML carries
no `<cite>` tags and all 1,221 of its extracted examples have an empty
`cite`: the source (`alpheios-project/grammar-bennett`) prints its examples
without attributions. There is nothing to key, so there is no
`data/bennett/citations.json` and no Bennett table in
`scripts/citation_tables.py`. This is a property of the source, not a
decision about difficulty; if a future Bennett conversion recovers
attributions, add a table and a line to `WORKS`.

## Where citations come from

Two places per section, merged:

1. every `<cite data-cite="...">` in the section's `html` **and** in each of
   its `notes[].html` — Goodwin, Gildersleeve and A&G carry these, as Smyth
   does;
2. every `examples[].cite`, which is the only source for Monro and Goodell
   and which in Gildersleeve holds 418 citations the tag scan does not
   produce (the example-extraction round read them out of plain text).

An example cite that the tag scan already yielded for the same section is
not counted twice: the scan's output is a multiset and each example cite
consumes one match from it before being emitted on its own. Citations from
(1) carry an anchor; those emitted by (2) do not.

| grammar | citations indexed from |
|---|---|
| goodwin-gmt | 5,902 (5,902 tags; 0 example-only) |
| gildersleeve | 5,391 (4,973 tags; 418 example-only) |
| monro | 1,834 (all example-only) |
| goodell | 769 (all example-only) |
| ag | 2,270 (2,270 tags; 0 example-only) |

## Canonical passage key

Identical in shape to Smyth's:

```
<author-slug>.<locator>              (single-work corpora)
<author-slug>.<work-slug>.<locator>  (multi-work authors)
```

**Slugs are Smyth's vocabulary, deliberately.** Every table maps onto the
same `(author_slug, work_slug)` pairs Smyth already uses, so one passage has
one key everywhere it is cited. That is the whole point of the combined
file: Goodell's `Soph. Oedipus the King 413`, Goodwin's `Soph. OT 413` and
Smyth's `Soph. OT 413` all become `soph.ot.413`; Monro's `Il. 2.77` and
Smyth's `Hom. Il. 2.77` both become `hom.il.2.77`. Works no grammar in the
corpus had before get a slug by the same rule (abbreviation lowercased,
periods dropped, internal spaces hyphenated).

## The tables

`scripts/citation_tables.py` holds one closed table per grammar, in the
shape of Smyth's `AUTHOR_WORK_TABLE`: an exact citation prefix as that
grammar writes it → `(author_full, author_slug, work_full, work_slug)`, with
`work_full`/`work_slug` `None` for a single-work corpus.

Goodwin and Gildersleeve use the same Perseus abbreviation system Smyth
does, so both tables are composed from one shared Greek block (plus a
shared Latin block, for the passages Goodwin quotes for comparison) and a
short list of their own extras. The composition is written out explicitly;
nothing is inherited implicitly, and a reviewer reads one shared list and
two short ones instead of two near-duplicate 250-line lists.

| grammar | prefixes in its table |
|---|---|
| goodwin-gmt | 302 |
| gildersleeve | 300 |
| monro | 2 |
| goodell | 45 |
| ag | 133 |

These are tables, not parsers. **A prefix that is not listed goes to
`_meta.unparsedCitations`.** No shape is inferred, no author is guessed from
context, no fuzzy match repairs a misspelling — Goodell's own misspellings
(`Xen. Anabais`, `Aesch. Prometheus Bond`, `Eur. Ipheginia in Tauris`,
`Thucycides`, …) are each listed as their own prefix, with the correctly
spelled `work_full`, so that they can be read and checked one at a time.

### Prefix matching

The **longest listed prefix wins**, matched case-insensitively after
whitespace collapse, and the character after the match may not be a letter.

* Case-insensitivity is not a guess: the grammars' small-caps rendering
  leaves real strings like `XEN. Anab.`, `THuc.`, `Hom. OD.` and
  `Plat. PHaedo` in the data, all of which are the table's own prefixes in
  another case. It also means one row covers both.
* Longest-wins is what lets `Cic. N. D. 2.93` beat `Cic. N.`, `Pind. I.
  3.58` beat `Pind.` (Isthmians, not roman numeral one), and `Plat. Menex.`
  beat nothing it should not.
* The non-letter boundary keeps `Plat. Sym.` from matching
  `Plat. Symp. 174D` (which has its own row).

## Locator normalization

The text after the matched prefix is normalized to a dot-joined locator.
Everything here is stated because these grammars, unlike Smyth, do not write
locators uniformly.

| input | rule | result |
|---|---|---|
| `Thuc. 1. 137` | spaces inside a locator are separators like dots | `thuc.1.137` |
| `Od.20.294` | no space needed after the prefix | `hom.od.20.294` |
| `Plat. Alc. 1.116c` | the separator between prefix and locator is discarded, so Smyth's `Alc. 1 110d` and Gildersleeve's `Alc. 1.116c` agree | `plat.alc-1.116c` |
| `Plat. Rep. 478D` | a trailing Stephanus/Bekker letter is lowercased | `plat.rep.478d` |
| `Plat. Crito 52 B` | a lone `a`–`e` after a bare number is that number's letter, not a component | `plat.crito.52b` |
| `Cic. Fam. 1.5a. 3` | a letter may sit on any component | `cic.fam.1.5a.3` |
| `Xen. Hell. iii. 5` | **roman numerals normalize to arabic**, upper or lower case, validated by round-trip (so `iic` is rejected, not silently accepted) | `xen.hell.3.5` |
| `Xen. Cyrop. 7. 5. 30` | any number of components | `xen.cyrop.7.5.30` |

Roman-to-arabic is applied **only to locator components, never to a
prefix** — `Pind. I. 3.58` is the third Isthmian, not `pind.1.3.58`,
because `Pind. I.` is a table row and the table decides where the prefix
ends. A component that is neither digits(+letter) nor a well-formed roman
numeral makes the whole citation unparsed.

### Ranges

Unlike Smyth, these grammars do cite ranges (`Il. 1.3-5`,
`Soph. Ajax 403–404`, `Plato Apology 17c–d`, `Thuc. 4.119.1-3`). All dash
characters normalize to `-`, and **a range is indexed at its opening
locator only**: `Il. 1.3-5` → `hom.il.1.3`. Nothing between the endpoints is
indexed and no endpoint is expanded, because expanding an abbreviated end
(`5.665-6` → 666, `24.376-80` → 380) is an inference, and one range in Monro
runs backwards (`Il. 23.88-86`) — a typo an expander would have to guess
about. This under-indexes; it never mis-keys. 86 citations corpus-wide are
ranges.

### Minimum locator depth

Goodwin's source leaves truncated continuation references behind. A passage
printed as `XEN. Cyr. i. 6. 13 … Ib. 47` converts to two `data-cite` values,
the second of which is `Xen. Cyrop. 47` — the book and chapter that governed
it are gone. Keyed naively that becomes `xen.cyrop.47`, a passage that does
not exist (the Cyropaedia has eight books).

`MIN_LOCATOR_DEPTH` in `citation_tables.py` therefore requires two locator
components for the multi-book narrative works every grammar here cites as
book.chapter(.section) or book.line: Homer's *Iliad* and *Odyssey*,
Xenophon's *Anabasis*, *Cyropaedia*, *Hellenica* and *Memorabilia*,
Thucydides, Herodotus, and Arrian's *Anabasis*. A shallower locator is
reported as unparsed. All 140 affected citations were inspected: none is a
genuine whole-book reference, and many are impossible outright (`Cyrop. 47`,
`Thuc. 108`, `Hdt. 202`).

Works cited one level deep by design — Plato by Stephanus page, the orators
by oration, Pindar by ode, drama by line, Latin single-book works by
chapter — are not listed and are unaffected.

### Book counts

Depth is not the only thing the print's compression breaks. **A locator
whose first element is impossible for its work is a truncation in the
print's own compressed lists, not a passage.** Gildersleeve §632 ends with a
run reading `DEM.1.7 DEM., 1.11 DEM., 2.13 DEM., 4.22 … ISOC.2.7 (twice)
ISOC., 6.1 ISOC., 45 ISOC., 8.47`: the author repeats, the locator
compresses, and now and then the book falls out, leaving a chapter and
section where a book and chapter belong. `THUC., 76.4` keyed naively is
Thucydides book 76, of a work that has eight.

`BOOK_COUNTS` in `citation_tables.py` therefore records, for each work whose
first locator element runs over a **closed, well-known set**, how large that
set is; a citation whose first element exceeds it is reported as unparsed.
71 works have a count: the Greek and Latin histories and multi-book prose
(Thucydides 8, Herodotus 9, both Homeric poems 24, Xenophon's *Anabasis* 7,
*Cyropaedia* 8, *Hellenica* 7, *Memorabilia* 4, Arrian 7, Diogenes Laertius
10, Strabo 17, Euclid 13), Pindar's four books of epinicians (O. 14, P. 12,
N. 11, I. 9), the Attic orators' fixed corpora (Demosthenes 61, Isocrates
21, Lysias 35, Antiphon 6, Andocides 4, Aeschines 3, Dinarchus 3, Lycurgus
1), the Gospels and Acts, and the Latin works A&G cites by book (Caesar,
Vergil, Livy, Lucretius, Horace, Ovid, Juvenal, Propertius, Curtius,
Velleius, Valerius Maximus, Gellius, Quintilian, Apuleius, Varro, both
Plinys, Tacitus' *Annals*, and eighteen works of Cicero).

This caught 68 citations: 22 in Gildersleeve, 15 in A&G, 21 (in 10 distinct
keys) in Goodwin, 2 in Monro. Every one was read. What the reading found:

* **Nineteen were flatly impossible** — the 17 Gildersleeve keys
  (`thuc.100.2`, `thuc.76.4`, `xen.hell.8.4.12`, …) and Monro's
  `hom.il.81.495` and `hom.od.44.478`.
* **Demosthenes above 61 and Isocrates above 21 are equally closed**, and
  are taken the same way. The Demosthenic corpus is fixed at 61 orations
  with the *Exordia* and letters cited separately (Gildersleeve has its own
  `Dem. Ex.` row), and Isocrates at 21 with the letters cited as `Ep.` So
  Goodwin's `Dem. 215`, `Dem. 67`, `Dem. 75`, `Dem. 76` and `Isoc. 37`, and
  Gildersleeve's `Dem. 73.4`, `Dem. 81.5` and `Isoc. L. 4.2`, go unkeyed.
  That last one also shows the ceiling catching a roman-numeral misreading:
  `L.` parsed as 50.
* **Lycurgus survives in one speech**, *Against Leocrates*, so Goodwin's
  bare `LYCURG. 100`, `Lyc. 61`, `60`, `50`, `135` are that speech's
  sections with the oration number dropped. Supplying the number the print
  does not write would be a repair rather than a reading, so these five go
  unkeyed like the rest.
* **A&G's `Cic. Catil. 5 … 61`** (13 citations) are bare section numbers for
  a work of four orations; since the values run past the length of the first
  Catilinarian, they cannot all be assigned to it, and they go unkeyed.
* **A&G's `Hor. Ep. 11.2`, `13.7`, `17`** are the *Epodes*, which A&G
  abbreviates the same way as the two-book *Epistulae*. The ceiling
  surfaced a genuine ambiguity in the abbreviation, and these three go
  unkeyed rather than into `hor.ep` beside the Epistulae.

Only counts I can vouch for are in the table. Left out, and why:

* **Plato** — the first element is a Stephanus page.
* **Tragedy, comedy and lyric** — the first element is a verse line or the
  poet's own running number.
* **Aristotle** — Goodwin cites the *Nicomachean Ethics* both as
  book.chapter (`Nic. Eth. 10. 1`) and by bare Bekker page
  (`Nic. Eth. 1139b`), so the first element is not reliably a book. A
  ceiling of 10 was tried and discarded: it threw out four sound Bekker
  references. Aristotle therefore carries two addressing schemes in the
  index — `aristot.nic-eth.10.1` and `aristot.nic-eth.1139b` — both real,
  neither a prefix of the other.
* **Isaeus** — eleven speeches survive and Perseus numbers a twelfth for
  the fragments, so 12 looked closed. Then verifier check 10 found
  `isaeus.14.52` in **Smyth's own frozen index**, from a TEI `<bibl>` that
  reads `Isaeus 14.52` (§2698, subsection `e`). Either some edition numbers
  him past 12 or the TEI is wrong; I cannot tell, so Isaeus has no ceiling.
  The Smyth key is recorded here and left alone —
  `data/smyth/citations.json` belongs to `build_citations_index.py` and is
  byte-frozen — and check 10 reports a Smyth finding as a note rather than
  failing on it.
* **Plautus and Terence** — A&G cites some plays by act.scene (max 5) and
  others by bare line (`Pl. Truc. 60`), so no one ceiling fits.
* **Tacitus' *Histories*** — five books survive of twelve or fourteen
  written, so "closed" is ambiguous.
* **Hyperides, Stobaeus, Theocritus, Martial, Catullus, Persius, Seneca's
  *Epistulae*, Aristotle's *Poetics*** — numbering fragmentary, editorial,
  or one I could not vouch for.

### What the ceilings still cannot catch

A bare oration number that is *within* its corpus is indistinguishable from
a truncation. Gildersleeve §292's `DEM., 46` and §49's `Dem. 5` both key
faithfully to a real Demosthenic oration, and both sit in runs of citations
to a different oration, so both may be references the print compressed.
Nothing in the data settles it, and no ceiling can: 46 and 5 are legal
oration numbers. They are keyed as written and named here as a known
residue — the same class as the impossible ones above, minus the evidence
that would let a check reject them. The QA sample below counts one such case
against us for exactly this reason.

## Citation-string cleaning

Applied identically to every grammar before the table is consulted. Each
rule exists because some grammar's `cite` field carries that noise; none
changes which passage a citation names.

* HTML entities unescaped; zero-width characters removed (Goodell has runs
  of U+200B in front of `Soph. Antigone 605`).
* `[fn]…[/fn]` spans removed (Goodell's example extraction folded footnote
  markup into the cite).
* A leading or trailing parenthesised group removed, repeatedly, but only
  while something is left to key on: Goodell writes
  `Xen. Anabasis 1.1.2 (Historical Present)` and
  `(i.e., he did this on various occasions) Xen. Anabasis 2.3.11`. A cite
  that is *nothing but* a parenthesis — `(Possessive Genitive)`,
  `(Frequent, in many shades of meaning.)` — survives cleaning intact and is
  correctly reported as unparsed, because it is not a citation.
* Whitespace collapsed; leading and trailing `.,;:` stripped (Gildersleeve's
  example cites keep the sentence punctuation that followed them:
  `Dem. 37.`, `fr. 33:`).

## Section identity and anchors

`section` is the grammar's own identifier: the integer `n` where a section
has one, otherwise the suffix of its stable `id` — which today means
Goodwin's seven unnumbered appendix sections, `"app-1"` … `"app-7"`, holding
347 citations between them. So `section` is an int for every grammar except
Goodwin, where it is an int or one of those seven strings. Sorting puts the
numbered sections first, in numeric order.

`anchor` follows Smyth's rule — the nearest preceding lettered subsection id
in document order, a scroll target rather than a containment claim — with
one tightening: an id counts as an anchor only if the record's own `letters`
array declares it. Only Smyth and A&G have lettered subsections at all
(A&G: 326 of 638 sections); Gildersleeve's `id="n1"` note anchors would
otherwise have matched Smyth's `^[a-z]\d?$` pattern and been emitted as
bogus subsection letters. Goodwin, Gildersleeve, Monro and Goodell therefore
produce no anchors, and A&G's are checked against its own declared letters.

## What each grammar deliberately leaves unkeyed

Every unparsed entry carries a `reason` naming the rule that rejected it,
and `_meta.unparsedByReason` counts them by class.

| grammar | unparsed | rate | what it is |
|---|---|---|---|
| goodwin-gmt | 274 | 4.64% | 135 locators too shallow; 128 bare continuation references — `Id. An. 13.`, `Ib. 26.`, `Cyr. 22`, `Hell. 16.`, `Lib. Eth. 4`, bare `Alc.`, `Gorg.`, `Men.`, `Soph.`, `Nic.`, `An.`, `Erot.`, `Marc.`, fragment references, 2 references to modern scholarship; 10 leading elements impossible for their work; 1 locator that does not parse |
| gildersleeve | 285 | 5.29% | 242 with no table prefix, four-fifths of them fragment references, the rest comic-fragment authors cited by Meineke volume.page.line (`Philem. 4.40`, `Pherecr. 2.281.3`), modern scholarship in the same tags (`Blass, Rhein. Mus. …`, `J. H. U. Circ. …`, `W. St. …`) and a few bare numbers; 22 impossible leading elements; 16 fragment locators that do not parse; 5 too shallow |
| monro | 2 | 0.11% | `Il. 81.495` and `Od. 44.478` — impossible book numbers |
| goodell | 15 | 1.95% | 6 cite fields holding running prose rather than a citation; 6 `Menander FCG`; `Corpus Inscriptionum Atticarum 2263`; `Epich. in Xen. Memorabilia 2.1.20`; `(see Xen. Memorabilia 4.4.19)` |
| ag | 19 | 0.84% | 15 impossible leading elements (13 `Cic. Catil.` bare sections, 3 `Hor. Ep.` Epodes); 3 `Sal. Fr.` (Maurenbrecher's numbering of the *Historiae* fragments); 1 `Pub. Com. 168` |

**Fragments are excluded on purpose, everywhere.** A citation like
`EUR. fr. 1028`, `fr. 321 N2`, `PIND. fr. 110 Bgk.4`, `HES. fr. 5 Rz.` or
`COM. FR. Mein. 3.462.13-4` numbers a fragment *within a named modern
edition* — Nauck's *TGF*, Bergk, Meineke, Kock, Ahrens, Rzach, Schneidewin.
The numbers do not carry across editions, so a fragment key could not be
joined between two grammars even when both cite the same fragment, and might
silently join two different ones. Lyric cited by the author's own running
number without an edition marker (`Tyrt. 12.35`, `Thgn. 153`, `Solon 4.30`)
*is* keyed; it is the standard reference for those poets and both grammars
that use it use it the same way.

Two bare Latin play titles in Goodwin **are** keyed, and this is a judgement
worth flagging: `Sept.` → `aesch.seven` and `Pac.` → `aristoph.peace`.
Goodwin writes the same plays as `Aesch. Seven` and `Aristoph. Peace`
elsewhere, no other work in his corpus is abbreviated either way, and the
line numbers fit (Sept. 38–1015 against the *Seven*'s 1078 lines; Pac.
135–1302 against the *Peace*'s 1357). The `<cite>` contexts were read
directly: both sit in runs of Aeschylus and Aristophanes citations.

### The ceiling

`verify_citations_all.py` fails if any grammar's unparsed rate exceeds
**6%**. The worst today is Gildersleeve at 5.29%, four-fifths of it the
fragment references above; the rest sit at or below 4.64%. Six per cent
leaves room for a source edit to add a few more of the same kinds without
breaking CI, while a genuinely new *class* of unkeyed citation — a work
abbreviation nobody put in a table, a locator shape nobody anticipated —
shows up as a jump well past it. The ceiling is deliberately a floor on
honesty, not a target: the correct response to a rate rising toward it is to
read the new unparsed list and extend a table, never to raise the ceiling.

## The combined file

`data/citations-index.json`:

```jsonc
{
  "thuc.1.9": [
    {"work": "goodwin-gmt", "section": 238},
    {"work": "goodwin-gmt", "section": 410},
    {"work": "goodwin-gmt", "section": 412},
    {"work": "smyth", "section": 1516},
    {"work": "smyth", "section": 1686},
    {"work": "smyth", "section": 2309, "anchor": "b"}
  ],
  "_meta": {
    "works": ["ag", "gildersleeve", "goodell", "goodwin-gmt", "monro", "smyth"],
    "uniqueKeys": 14134,
    "entries": 20051,
    "entriesByWork": {"ag": 2204, "gildersleeve": 4564, "goodell": 747,
                      "goodwin-gmt": 5520, "monro": 1831, "smyth": 5185},
    "keysCitedByMoreThanOneWork": 2203
  }
}
```

It is the exact union of the six per-work indexes and adds nothing of its
own (verifier check 6). Keys are sorted; each key's entries are sorted by
`(work, section, anchor)`. `_meta` cannot collide with a passage key, which
always begins with a lowercase author slug.

2,203 of the 14,134 keys are cited by more than one grammar — that overlap
is what the shared slug vocabulary buys.

### Looking a passage up

A locator is a **dot-path**, and grammars cite at different depths: Smyth
and Goodwin cite Thucydides as book.chapter, Gildersleeve as
book.chapter.section. So "Thucydides 1.9" is the key `thuc.1.9` **plus every
key beneath it**:

```python
hits = [e for k, v in index.items()
        if k != "_meta" and (k == q or k.startswith(q + "."))
        for e in v]
```

For `q = "thuc.1.9"` that is 9 sections across Goodwin, Gildersleeve and
Smyth; the exact-match-only answer would be 6, and would silently drop
Gildersleeve. As in Smyth's spec, do **not** try to split a key on `.` to
recover the work — the number of locator components varies per work, and
only the tables know where a work slug ends.

## Verification

`scripts/verify_citations_all.py` (in CI, "Citations, all grammars"):

1. citation totals reconcile with an independent rescan of every section
   through `html.parser` rather than the builder's regex;
2. every section referenced by an index exists in that grammar's
   `sections.jsonl`;
3. the build is deterministic — two runs against a private copy of the data
   are byte-identical to each other and to the checked-in files;
4. every grammar's unparsed rate is reported and is under the ceiling;
5. every `author_slug` names one author across all five tables, and each
   `(author_slug, work_slug)` pair names one work within a grammar (the
   pair is deliberately reached from differently spelled prefixes in
   different grammars — that is the joining mechanism);
6. the combined file is the exact union of the per-work files, Smyth's
   included;
7. ten spot-fixtures resolve, one per awkward shape (`Od.20.294`,
   `Cic. N.D. 2.93`, `Sept. 754`, Goodell's full work names, …), in both
   the per-work file and the combined one;
8. the cross-grammar prefix lookup for `thuc.1.9` reaches three grammars;
9. `data/smyth/citations.json` still has `build_citations_index.py`'s
   format and its 5,193 source citations — this pipeline never writes it;
10. no key in the five indexes built here names a book its work does not
    have, checked against `BOOK_COUNTS` over the written index rather than
    by trusting the builder — this is the defect class the minimum-depth
    rule missed. Smyth's frozen index is scanned by the same check and any
    finding there is printed as a note, not failed on (today: none, since
    Isaeus lost its ceiling because of `isaeus.14.52`).

### Sampled QA

`verify_citations_all.py --sample` prints 30 random passage keys (fixed
seed) next to the citation text each was built from. The recorded pass:

**All 30 key exactly what their citation string says. 29 were confirmed to
name a real passage of the named work.** The thirtieth is Gildersleeve §49's
`Dem. 5` → `dem.5`: a real Demosthenic oration, keyed faithfully, but one of
the bare oration numbers the print's compressed lists produce, so it may be
a truncation. Nothing in the data settles it and no ceiling can reject it
(see "What the ceilings still cannot catch" above), so it is counted against
us — **29/30**.

The sample covered all five grammars and the shapes that most needed
checking: spaced locators (`Thuc. 5. 7`), a stripped trailing period
(`Dem. 21.40.`), a stripped leading gloss (`(i.e., I fear she will)
Eur. Alcestis 315`), an uppercase Stephanus letter (`Plat. Crito 44D` →
`plat.crito.44d`), Goodell's full work names, Monro's bare `Il.`/`Od.`, and
A&G's Latin.
