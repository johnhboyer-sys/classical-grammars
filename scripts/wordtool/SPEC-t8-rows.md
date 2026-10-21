# SPEC: T8 row packs (`grc-lsj-t8`, `lat-ls-t8`)

Status: drafted 2026-08-25. Builder: `scripts/wordtool/build_wordtool.py`.
Consumer: grammar-site `/words`. Design of record: grammar-site
`work/design/dict-entry/tools/gen_cgl.py` on branch
`claude/dictionary-entry-design-87ae8f`.

## 1. Thesis

The T8 dictionary entry — meaning first, bold cue-gloss, author
abbreviations, examples behind a click — is computed **here, at build
time**, and shipped as row structure. `/words` renders it; it does not
derive it.

Three things force that. `first_gloss()` reaches into a *different*
entry to pull its gloss (ῥαθώδημα shows ψεῦσμα's "lie, untruth, fraud").
`neighbour_head()` needs the bucket's key order to resolve `fem. of sq.`
`mark_headword()` marks θέσθαι and τιθέναι as forms of τίθημι through
Morpheus — 911,519 Greek forms. In a browser each of those is another
Range request, or a second implementation of a 1,900-line transform. In
the builder they are already in memory.

## 2. Row structure, not rendered HTML

The pack stores what the entry *is*, not how it looks. Eight design
takes say the markup will keep moving; re-baking 168,389 entries because
a class name changed is not a thing we should ever do. Tabs, drawers,
sticky heads, and the abbreviation toggle are the site's business.

Measured on 498 random LSJ entries, against the entry HTML the lexicon
pack ships today:

| | raw | gzip-6 |
|---|---:|---:|
| source entry HTML (today) | 1.00× | 1.00× |
| T8 rendered HTML | 1.31× | 0.89× |
| **T8 row JSON** | **0.31×** | **0.52×** |

Projected `grc-lsj-t8` ≈ 9.4 MB against the 18.3 MB lexicon pack; Latin
in proportion. The T8 pack is *smaller* than the source it presents,
because it keeps at most `EXAMPLE_CAP` examples per sense (eight) and
drops the rest of the citation apparatus.

That is also why the lexicon packs stay exactly as they are. `grc-lsj`
remains the complete record and the fallback; `grc-lsj-t8` is a
presentation dataset. Full apparatus is, as ever, the Logeion link.

## 3. Record

Same bucketing, keying, and folding as the lexicon packs — two-letter
folded-ASCII bucket, folded key, `write_pack()` unchanged. A key holds a
**list of records, all of them** (see §5).

```json
{
  "key": "βίος",
  "head": "βίος",
  "g": "ὁ",
  "i": "verbal noun of λέγω (B)",
  "f": [["FUT.", "θήσω"], ["AOR.", "ἔθηκα"]],
  "gr": [["A", "set, put, place"], ["B", "put in a certain state, condition"]],
  "rows": [
    {
      "lv": 0, "n": "1",
      "z": "<b class=\"cue\">cleverness</b> or <b class=\"cue\">skill</b> in handicraft and art",
      "au": ["Il.", "Pi.", "Pl.", "+"],
      "ex": [{"g": "τέκτονος, ὅς ῥά τε πάσης εὖ εἰδῇ <b class=\"hw\">σ.</b>",
              "c": "Il. 15.412"}]
    },
    { "lv": 0, "n": "4", "z": "among the Jews", "u": 1, "au": ["LXX"] }
  ],
  "p": "fem. of ῥαφιδεύς"
}
```

Keys are short because they repeat 168,389 times. `lv` nesting level ·
`n` the print's numeral · `z` the gloss · `b` banner · `s` numeral
supplied by us, not the print · `u` usage chip · row or entry `au`
citation abbreviations · `ex` examples (`g` Greek/Latin, `e` the print's English
if it gave one, `c` citation) · `f` forms bar · `gr` group labels for
tabs · `i` identity line · `p` pointer line for stub entries.

Absent keys mean absent, never empty-string. Booleans are `1` or gone.

### Inline markup stays, block markup goes

`z`, `ex.g` and `p` keep a **closed vocabulary of inline spans**, because
these are facts about the text, not decisions about layout:

| markup | means |
|---|---|
| `<b class="cue">` | the print's italic translation cue |
| `<span class="rub">` | pre-gloss rubric (*of ships*, *of women*) |
| `<b class="hw">` | a form of this entry's lemma, per Morpheus |
| `<span lang="grc">` / `lang="la"` | language run inside the other language |
| `<span class="eq-mark">` | the `=` of a Greek-explains-Greek gloss |
| `<b class="sublem">` | a sub-lemma heading its own equation |

Nothing else. No grid, no chevrons, no tab or drawer markup, no
`.xs`/`.xf` pairs.

Those three fields are the only markup-capable fields. The renderer
HTML-escapes `i`, `gl`, and every other prose field. The transform must
therefore put no tag in them. In `z`, `ex.g`, and `p`, decoded `<κε>`
and entity-encoded `&lt;κε&gt;` both ship as visible editorial brackets:
`⟨κε⟩`. Conversion runs on source text before language or headword spans
can split the brackets from their letters. It accepts one or more 1–12
letter runs separated by spaces, including combining marks and U+02BC.
Known HTML tag names, digits, attributes, and punctuation stay unchanged,
so the markup audit still fails on a leaked `<div>`, `<br>`, or `<img>`.
The source-encoded supplied `<i>` in συναινετικόν also becomes `⟨i⟩`;
it is source text, not an inline tag.

In the Latin pack, every unmarked run of two or more Greek letters in
`z`, `ex.g`, or `p` gets one `<span lang="grc">` wrapper. Adjacent Greek
text stays in one wrapper, and a run already inside such a span is not
wrapped again. Greek in escaped `i` or `gl` stays plain until the
renderer can assign language there.

### Rows whose print gives no English definition

A sense row must still say something on its line. When a short
Hesychius-style entry splits into punctuation on the line and a defining
Greek gloss in the evidence drawer, the transform promotes that gloss to
`z` and removes it from `ex`. A lexical note such as `f. l.` or
`strengthd. for` moves as a whole; it is not reduced to its first Greek
form. Promotion is lossless: it keeps every sub-lemma, preserves balanced
parentheses, wraps promoted Greek in `lang="grc"`, keeps any drawer
examples, and carries each full citation token, including its locus, in
the row's `au`.

Some short entries contain only gender and citations. They keep an empty
`rows` array and put each print citation, with its locus, in entry-level
`au`: `['Sor. 1.125', 'Orib. Fr. 143', 'Paul.Aeg. 3.23']`. One long blob
is invalid, as is English definition text in `au`. A pure cross-reference
keeps its pointer in `p`, empty rows, and no invented gloss. The renderer
shows entry-level `au` with the same abbreviation expansion used for
row-level `au`.

Short senses may begin with citations before their gloss. The first
citation is not the end of the definition zone: if the source retains a
real gloss after it, the transform recovers that print wording as a
normal sense row.

### Several definitions in one sense paragraph

LSJ and L&S write more than one definition into a single sense, each a
rubric and an italic gloss followed by its own quotations, separated by
nothing but the print's `;` or `:`. ἁβρός is *graceful, delicate,
pretty* … of things, *splendid* … of style, *graceful, pretty* … freq.
with a notion of disparagement, *dainty, luxurious*. Stopping the
definition zone at the first citation read all of that as apparatus:
13,725 Greek and 7,077 Latin entries shipped one of the several meanings
the print gives, and οὐσία II lost "hence, *being* in the abstract, opp.
non-being".

The transform cuts the sense at each of those boundaries. The first
definition is the sense row, as before; each later one becomes a row of
its own, `s` set and `n` absent, one level under it, with its own
examples and its own `au` — so the example cap is a budget per
definition, not per paragraph. `s` therefore means the row's address is
ours and not the print's: a supplied numeral, or a continuation the
print never numbered.

A boundary is a plain `<i>` — the print's translation cue, never
`<i class="lx-title">` — with a reference closed before it and no
unreferenced quotation between, cut back to the print's own `;` or `:`
so the rubric leads the new definition. A banner's label does not stop
this: the definitions the print writes after "Lit.:" are the banner's
children (L&S abortus I.).

Four things are not boundaries. An `<i>` inside an open parenthesis is
apparatus — πρατήριον cites "PTeb. 701 (a). 7" and sets the part letter
in italics like anything else. An `<i>` translating the quotation beside
it is that example's gloss, and the bare quotation before it says so.
What the print puts in parentheses is an aside and does not change the
sentence outside them, which settles that rule both ways up: a reference
inside them does not end the quotation before them (ἅπαξ writes "opp.
δυοῖν δίς (2 x 2), *four*" and the "four" translates δυοῖν δίς), and a
quotation inside them never puts the sentence in quotation at all
(ἀναπλέκω's "(Andania, i B. C., in form ἀμπλ-)" must not hide the "Med.,
*braid oneʼs hair*" that follows it). A candidate whose zone
carries no cue, no word of two letters, or only an address in brackets
is not a definition — brackets are what make an address, since bare and
three letters long is a gloss (ἀφαυρός "feeble, powerless … *dim*").
And a `;` that closes an HTML entity is not the print's separator.

Arming waits for the print's own `)` when a reference closed inside one,
so a cut never lands between a citation and its bracket (ἄκοσμος II
"AP 7.561 (Jul.), but in 9.323…").

**A candidate that fails folds its wording back into the definition
before it** — one predicate decides both whether a segment stands alone
and what its row says, so a rejected segment never takes a citation with
it. A sense whose own opening says nothing is carried by the first
definition after it (ἡνιοχεύς 8., L&S absis I.). Either way the
separating punctuation the cut landed on is dropped from the head of the
new line. Segmenting must not cost the entry a row, and does not: row
counts are identical to the previous build on all 168,389 entries.

Continuations expand after the level surgery and the flatten, so they
are never counted as the print's own divisions when those rules decide
how deep an entry nests.

Debris rules that run beside this: a trailing locus whose author the
citation strip already removed (σύγκαυσις "parched state of body,
15.895", whose Gal. was a bare `lx-author` span) and a connective left
holding nothing once the material it announced became an example
("dainty, luxurious; hence"). Both are **prose rules and must stay on
prose**. `_polish_emitted` walks every stored string including `ex.c`,
where the link rule alone is safe: a citation's own book and chapter are
the same shape as a stripped locus, and running the locus rule there
turned "Cic. Verr. 2, 4, 33" into "Cic. Verr. 2" on 83,824 Latin
citations. The locus rule also leaves a locus whose reference is still
on the line untagged (L&S admissio III "Cod. 6, 15, 5"), because
stripping there takes the citation apart comma by comma.

Three effects are accepted. A row's `au` is now the authors of its own
definition, so an author later in the paragraph moves to the row it
belongs to; 44 entries lose one author chip outright where the split
crosses the per-row cap. 317 Greek and 48 Latin entries drop a quotation
that only had a citation because the old window reached across a
definition boundary to borrow the next one's (ἀδιάλυτος's σύμβασις,
whose own reference is a bare `lx-author`). And a sub-lemma chain inside
a sense now surfaces as continuation rows rather than being dropped
(Ἀσκληπιός ships Ἀσκληπιάδης, Ἀσκληπιασταί, Ἀσκληπιεῖον); whether those
should instead carry `<b class="sublem">` is open.

Recovered short senses remove citation debris before they become rows:
empty parentheses, bare loci, orphan `ap.`/`cf.`/`al.`/`etc.`, leading
punctuation, and editor names that lost their citation target. A recovered
identity made only of punctuation is absent. `:—` separates short-entry
blocks; each block becomes its own row, so a trailing adjective block is
not cut off with the main proper-name sense.

Final emission collapses repeated commas in every string field (including
a comma stranded inside a closing tag next to another) — one record-wide
rule, after all paths have built their fields. Unmatched parentheses are
handled earlier, in the tidy pass that builds each zone, and
conservatively: an unmatched `(` whose visible tail is two words or fewer
is a truncated aside and is cut, tail and all, tags kept; one with a
longer tail stays as printed — the stray paren is honest, and deleting it
would merge the aside into the definition prose.

`p` is only for a cross-reference whose wording says `fem. of`, `v.`,
`cf.`, or another clear reference form — or a resolved equation
(`= φουλβῖνον`) or derived-form note (`Subst. ἑρκοθηρευτής`) whose target
lemma survives; the wording test never deletes an entry's only content.
A parenthetical, author locus, or orphan page number goes to entry-level
`au`, not `p`. Citation tokens may ship beside a real pointer. A `:—`
block whose remainder is bare articles is the print's gender marker and
never becomes the right side of an equation (`σπληδώ, ἡ`, not
`σπληδώ = ἡ`); a sub-lemma with no remainder stands alone, without a
dangling `=`.

### Citations the print set bare, and the sentences that govern them

Perseus marks most citations as `lx-bibl` and some as a bare
`lx-author` with the rest of the citation in plain text: "Suid. s.v.
ἄβαξι", "Crito ap. Gal. 13.878", "Hdn.Gr. ap. Sch. Il. 8.178". A bare
author is one of two things, and the transform decides which before
anything else reads the entry.

**Prose.** An author the sentence governs is its subject or object —
"the oldest and in Hom. the commonest sense", "Hsch. explains", "First
in Hdt., never in Trag." The span is marked `lx-author lx-prose` and
its words stay; no chip is minted from it. The tests are structural: a
linking abbreviation or a locus after the author makes a citation, an
English word makes prose, "in" is a citation link before a work title
("Anon. in Rh. 174.6", "Phlp. in de An.") and English before a label
or a determiner ("in Med.", "in the phrase"), a linking abbreviation
in front settles it as a citation ("cf. Hsch."), and a pair joined by
and/or is one citation unless the sentence governs it ("Not in A. or
E."), in which case both halves are prose.

**Citation.** Everything else is wrapped, with its tail, in
`<span class="lx-bibl" data-bare="1">`. The tail is a closed grammar
of citation tokens, each anchored on the last: apud and an author or a
marked citation, s.v. and the Greek lemma named, a work title, a
locus, ibid., l.c., an editor's siglum, a parenthesised page, an
editorial "(?)", and and/or plus another author not marked prose. A
plain-text "Crito ap.", "Decr.Byz. ap.", "Ps.-" or "Sch." in front of
the author — or in front of a citation Perseus did mark — joins it,
and the name in it is one of the citation's authors, marked as Perseus
marks the chains it did mark ("Archig. ap. Gal."): Pherenicus chips
for "Pherenic. ap. Sch. Pi. O. 3.28", Naevius for "Naev. ap. Paul. ex
Fest.". A lead that names a kind of source and no one — "Orac. ap.
Hdt.", "Lex ap. D.", "Fragm. ap. Prisc." after an "id." — mints no
chip (`_SOURCE_LABELS`). Anything else ends the citation, and its
final period is the sentence's. From there every consumer does what it does with any
citation: the strip takes it whole, the chips name its author, the
example extractor reads it as the quotation's reference.

Two things the wrapper does not do. It does not end the definition
zone: a bare author never did, and the print's material after it
stays in the definition (ἁρμή "suture of a wound, of the skull-bones,
Id. ap. Gal."), so `entrylib.CIT_OPEN` ignores `data-bare` and the
chips are collected from the zone as well as the evidence. And it does
not change the verb forms extractor's probe, which is measured on the
markup without these wrappers.

**A citation the sentence governs keeps the author's name.** "first
in Hom.", "condemned by Arist.", "acc. to Phryn.", "Hom. only in Od."
— the sentence ends on its preposition and the object is the citation.
The name stays in the sentence (`keep_governed_author` for a marked
citation at the zone's edge, the wrapper's own lead for a bare one, a
governed bare title likewise) and the citation stays a citation. Only
when nothing separates the two: a gloss can end on a preposition of
its own ("worth listening to,") and the print's comma is what says so.

### The Greek the sentence governs

A Greek run inside the definition is a quotation unless the sentence
governs it. Two shapes say it does, and `split_sense` skips both when
it looks for the first illustration: the run stands inside the print's
own italic ("*one who wears a σίσυρνα*"), or the text in front of it
ends on a governor — of, a, an, the, as, like, into, than, to, on, in,
with, by, from, and, or, i.e., e.g., sc. — with nothing between ("Dim.
of ἄβαξ, *small stone for inlaying*", "as ἀμφασία, γνάμπτω for ἀφασία").
The comma is what says a quotation follows: "*find fault with,* τινί"
keeps τινί in the drawer. Before this rule 2,685 Greek rows ended "of",
1,319 "with", 546 "the", 406 "a", 357 "as", the object sat in the
drawer, and where the print's italic followed the object the real
gloss was read as that quotation's translation.

Perseus sometimes wraps the object into the quotation after it:
ξεστιαῖος "of a ξέστης, μέτρον Gal. 13.435" marks "ξέστης, μέτρον" as
one `lx-quote`. When the zone ends on a governor and the evidence opens
on such a quote, the first word before the print's comma moves onto
the line and the rest stays the example (`keep_governed_quote`); a
one-word quote moves whole and its citation stays for the chips. A
phrase before the comma is a quotation and does not move.

LSJ's editorial brackets sit outside the span Perseus wrapped the word
in — "[κλέος] οὐκ ἀ.", "ἀβίωτόν [ἐστι] *life is intolerable*" — and the
split left one bracket on the sense line. The bracket moves in with its
letters before the split (`_brackets_into_greek`). The brackets round a
doubtful attribution, "[Gal.] 14.519", go before the bare authors are
marked, so the citation is one; a second locus after the print's comma
("Dsc. 1.12, 5.75") joins a bare citation's tail, but only one with a
point in it, since ", 3 kinds of" is prose.

A separator the print set inside the italic ("*not loudly lamented,*
Epigr.Gr. 240") separated the gloss from a citation that is now gone,
and `_polish_emitted` strips it inside the closing tags as it does
outside them. A comma before the print's opening bracket in a gloss
("chop fine or small, (both Pass.)") is the same seam and goes, in the
gloss only: the identity line writes "ου, (ῥήγνυμι)" and means it. A
leading period is the headword's (L&S "Aba. (or Abas)") and a bracket
opened on nothing at the end of a line went with its citation.

### "Id." is not an author

The print writes "Id." (L&S "id.", and "ib." for the work as well) for
the last author it named, in the sentence before or in the row above.
14,399 Greek and 25,528 Latin chips shipped it unresolved, and the
reader lost the author both ways. `unique_authors` walks the citations
and the prose mentions between them in print order and resolves each
"Id." against the last name it passed; the row inherits the antecedent
from the sense above it and, for the first sense, from the preamble
(`last_author`). A citation that names only a work — "R. 509b" after
"Pl. Phd. 65a" — means that author's work by the same convention, so
the chip is the author when the table in `data/lsj-abbrevs.json` lists
the work under him, and a work with no author (AP, h.Merc., Ev.Matt.)
stays the chip it was. An "Id." with nothing to resolve against mints
no chip. The examples' citations already resolved "Id." within a row;
they now inherit the same antecedent across rows. A short entry's chips
come from `citation_tokens`, which keeps each print citation whole
("Sor. 1.125", "Id. 3.5"), and its rows are the sub-lemmas of a
Hesychius-style glossary (ἀγμείονες "βουβῶνες, Hsch. ἀγμή· ἑστία, Id."):
`resolve_same_authors` walks those rows in order and rewrites the "Id."
with the author part of the last token before it, locus kept.

### The identity line, the forms bar, and the shape of a gloss's end

A citation is nested — quotation, then reference with its author — and
the citation strip reads complete elements, never the first closing
tag it meets. The form the print set inside a citation is the form:
"Ion. -ιη Hdt. 1.92" gives the bar "Ion. | -ιη" and the identity line
keeps it only where the bar does not (D4: the bar wins). A title with
a locus is stripped from the identity line; a bare title stays
("in Il. ⏑ _ _ ⏑" is a prosody note). The print's homonym letter is
`hom`, never text.

A gloss ends on its last word. Trailing separators go; a final period
goes unless it closes an abbreviation — capitalised of any length
("Art.", "Hippon."), a grammar term ("part.", "impers."), in Latin a
single lowercase letter (the gender: "ae, f."), a Greek token of one or
two letters (LSJ's own abbreviation of the headword in a quotation, "τί
ν.") — and never a link ("Id.", "cf.", "sc."), which the dangling-tail
rules read bare. An example's translation is trimmed of what the strip
leaves around it (a bracket closed on nothing, a reference's stub, the
preposition that governed a stripped author) and kept; it is dropped
only when nothing but a governor is left.

### Lewis & Short's untagged quotations

LSJ wraps every quotation in `lx-quote` or `lx-foreign`. Lewis & Short
writes the Latin bare — "sicut fortis equus, spatio qui saepe supremo
Vicit Olympia, nunc senio confectus quiescit, *a powerful horse*, Enn.
ap. Cic." — with the translation in a plain italic and the reference
after it, and nothing in the markup says the Latin is a quotation. Read
as a definition, the translation shipped as a sense of its own with the
Latin glued to it (inconditus "carmina, artless, rude soldiers' songs");
27 of 60 Latin recovered rows were that. The other shape is a bare
case-form: "agrorum, *in the country*, Cod. Th."

The quotation is the sense's example — `ex.g` the Latin, `ex.e` the
translation, `ex.c` its reference — and the false row goes only once the
drawer has it. The drawer's budget is `EXAMPLE_CAP` per definition, and a
translation the drawer cannot hold stays on the line it was on rather
than leaving the reader-visible text; the print's marked quotations keep
first claim on the drawer, so this pass runs last and only ever adds.

Only grammar tells a quotation from an idiom definition written in the
same shape (manus "manum ferulae subducere, *to take the hand from the
rod*, Juv."), and Morpheus has the grammar. Every test is a veto and an
unknown lead keeps the print's cut. The lead is the untagged text
between the print's last ':' or ';' (or the last closed reference) and
the italic, never an element's text: a sub-lemma's "Attĭci, ōrum, m."
parses as Latin word for word. It carries no English marker word (a
closed set: not "an", the Latin particle in "Lucanus an Apulus", and
not "In", which verse capitalises), no capitalised rubric ("Esp.",
"Transf."), no block dash, no aside in brackets and no unbalanced one,
no lone preposition or conjunction; every word parses; no indefinite
placeholder (aliquem, quippiam); an infinitive only when the translation
reads "to …", which is how an idiom's definition reads and a passage's
does not ("ut metallum esse coeperit, *a mine*"). The italic is not
Latin itself (dico's "Catonis est dictum. *Pedibus compensari
pecuniam*" is the print italicising the quotation), has a word in it
("*neutr.*" is a grammar label, "edere *or* statuere" a conjunction),
and does not follow a plain italic with only a comma between (Memmius's
"*adjudged guilty of* ambitus, *went into exile*" runs a Latin word
through its own sentence). The print's "idiom: quotation" shape ("in
manibus esse, *to be in everybody's hands*: est in manibus oratio,
Cic.") and a reference the digitisation left in plain text ("in Arabic,
Sol. c. 33") keep the row as it was.

The translation is the italics up to the reference, with the print's
own English between and after them ("or", "i. e.", "still called", and
the note the print adds: Aetnaeus's "Vulcan, who is said to have had
his forge in Mt. Aetna"). Latin between the translation and its
reference (fetialis's ", fetialis,") and the reference's debris
(internecinus's "acc. to", satelles's "id. poët.") are not the
translation. An English aside in brackets stays, a Latin one goes
("(= magno pretio emens)"), an aside the reference sits inside is cut at
its bracket, and an equation with Latin after it goes up to the print's
comma ("= nedum"; "= pilā ligneā, which he had used just before" keeps
its note). A lone proper noun is a translation here, not an author
("Vulcan", "October"). The reference is resolved against the print's
own antecedent, not the shared queue.

### Neighbour equations

The print's `<span class="lx-abbr">=</span> sq.` form means “equal to the
next entry,” just like plain-text `= sq.`. `REL_SQ_MARKUP` resolves it
against the next key in the bucket (663 entries in the reviewed build).
The inserted neighbour belongs on the equation line; any later quoted
form and citation remain in the evidence drawer. Resolution must not
drop examples or leave doubled punctuation.

A division after the relation stays after the resolved lemma: `= sq. II`
becomes `= παρακαθίζω II`. This applies in a numbered entry's preamble as
well as in a short-entry meaning. When an equation borrows its neighbour's
first gloss, a later bold orthography starts a new cross-entry block and
does not become part of that gloss.

## 4. Abbreviations ship once, not 168,389 times

`au` and `ex.c` normally store the **short token only** (`Il.`,
`Hyp. Ath. 5`). A citation-only entry has no quotation to support an
`ex.c`, so each entry-level `au` token keeps the print's compact full
reference instead (`Sor. 1.125`). Promoted rows do the same so the move
does not lose a locus. Today's mock bakes both
forms into every entry as `.xs`/`.xf` span
pairs; at pack scale that is the same author name written out tens of
thousands of times.

Ship the keys as their own small static JSON — LSJ authors/works
(176 KB) and L&S authors/works/other (59 KB), both already parsed and
committed in the design worktree — fetched once, lazily, the first time
a reader turns *Expand abbreviations* on. The toggle is global and rare;
the entry payload should not carry it.

### Expansion is per field, never a scan of the text

This is the condition the one-list approach depends on. Some
abbreviations are shaped like Roman numerals — `D.` Demosthenes, `X.`
Xenophon, `LXX` the Septuagint, `C.` *Carmina*, `M.` *adversus
Mathematicos* — so a scan for "things that look like abbreviations"
would eventually read a sense address `II.` as *Ilias*.

It cannot, because expansion is only ever applied to fields whose role
is already known:

| field | expanded against |
|---|---|
| `au` | authors + works |
| `ex.c` | authors + works |
| `n` (sense address) | **never** |
| `z`, `i`, group labels | grammatical list only — closed, word-bounded, never a bare single capital |

Verified on the current mocks: 2,261 expanded tokens across both
languages, 128 of them numeral-shaped and every one correct, and **zero**
expansions inside a sense address. `Il.` and `II.` are different strings
(letter L, two capital I's), so exact lookup never confuses them; the
guarantee is that a numeral is never offered to the expander at all.

The grammatical list is the one that runs over prose, and the one that
has bitten before — an unbounded `ACC` once turned "According" into
"accusativeording". Keep it short, require a period or word edge, and
leave anything ambiguous unexpanded (LSJ `Antipho` is two people; it
stays as printed).

## 5. Homographs: every record, not the first

`model()` currently takes `recs[0]`. Folding strips exactly the accent
that distinguishes the entries, so `bios` holds both βίος *life* and
βιός *bow* — a reader at *Iliad* 1.49 gets "life" and no sign the other
exists. Latin `os` is *ōris* mouth and *ossis* bone; `malus` is bad,
apple tree, and mast; `dis` has four. 1.0% of Greek keys and 4.3% of
Latin hold more than one entry — about 3,400 keys.

The build renders **every record** under a key. `/words` stacks them:
a T8 entry is already a self-contained article with its own headword and
rule, so two stacked read correctly with no new UI. A chooser is a later
question, and only if stacking something like `in` proves ugly.

## 6. Build gates

These are invariants, not aspirations — each one was a real bug found by
sampling, and each is cheap to assert while the buckets are in memory.
Fail the build, don't warn.

- Every non-banner row's visible `z` contains a Unicode letter or number.
  Examples and child rows do not waive this rule: they sit behind or
  below the sense line and cannot make punctuation into a gloss.
- No banner row lacks a label.
- A source that contains more than headword and morphology must expose at
  least one reader-visible entry field: `rows`, `f`, `p`, `i`, `gl`, or
  entry-level `au`.
- Transform exceptions are counted into `manifest.json` beside the
  sha256, and a rise over the recorded baseline fails the build. Today's
  baseline is the fold-mismatch class (~0.2% of Greek heads, e.g.
  `φιλοτεχνῖται` under pack key `filotexntexnitai`); it must not grow.
- Record count per dataset equals the lexicon pack's record count. A T8
  pack that renders fewer entries than the lexicon has dropped content.

`scripts/wordtool/test_packs.py` is the place for these.

### As built (2026-08-25)

`build_t8()` reads the lexicon pack just written, so cross-entry lookups
work through the same code as the mock. `--t8-only` rebuilds just these
packs from existing lexicon packs; `--t8-limit N` is a smoke test.

| | pack | entries | unreadable | unlabelled divisions | bare in print |
|---|---:|---:|---:|---:|---:|
| `grc-lsj-t8` | 9.7 MB | 116,715 | 0 | 1 | 6 |
| `lat-ls-t8` | 7.4 MB | 51,674 | 0 | 12 | 2 |

Entry counts equal the lexicon packs exactly. Bucket slices are smaller
than the lexicon's — median 8 KB, p90 59 KB, max 401 KB.

**A gate must test what the reader sees, not a proxy for it.** Every
gate here was wrong on its first attempt, always in the same way — it
compared something easier to measure than the thing that matters:

- counting *records* rather than *content*, so an entry could be present
  and empty and the build stayed green (`δεκάσκαλμος`, whose only sense
  is "with ten banks of oars", rendered blank);
- testing whether stripped text was non-empty rather than whether it
  held letters, so `', '` counted as a surviving gloss;
- checking senses, pointer and authors but not the identity line, so
  five L&S cross-references (`Barcinus` → "v Barcas") were reported as
  blank when the reader sees them perfectly well.

Related: an empty definition zone must never be discarded before the
fallbacks run. It was, and it cost roughly 39 senses per 40 buckets
sampled — the definition of those senses sits inside the citation.
`zone_from_evidence` now scores the text outside the citations against
the text inside the first one and takes the better; a bare "al." left
over from stripping references must not beat "kneel down" (τίθημι 12).

**A silent dependency is worse than a missing one.** `form_bar` imported
the principal-parts helper inside `try/except: pass`. That helper lived
beside the renderer, so the mock resolved it and the builder did not —
and the swallowed exception meant nothing failed. The pack shipped
τίθημι's forms as dialect debris ("Ep. and so in Aeol., Supp. 4.27")
while the mock showed `fut. θήσω | aor. ἔθηκα`, and every gate passed.
The helper lives here now and imports at load. Found by Grok, 2026-08-25,
by importing the transform alone and diffing against the renderer's path
— which is the only way to see it, since the mock has both halves.

**The error ceiling is zero, and stays zero.** It was briefly 0.4%, a
figure carried over from an unrelated failure mode found in review, and
it passed 127 entries — every LSJ and L&S entry consisting only of
citations — that the transform could not read at all. The cause was a
name the transform called but no longer defined after the split
(`authors_html`, left in the renderer): invisible in the mock, which
imports both halves, and fatal in the builder, which imports the
transform alone. The builder is the only place the transform runs on its
own, so this gate is the only thing that will catch the next one. Do not
raise it to make a build pass; find the entry.

The gates fired four times during the first full run, and every failure
was a real defect the thirteen seed words could not reach:

- `ἅλς` III states its sense only inside the citation ("ἃ. ἀμμωνιακός
  rock-salt, PLond."); `καταστηματικός` II states it outside one, after a
  cross-reference the definition/evidence cut split in half. Both now
  recover the print's own words — see `zone_from_evidence`.
- `πάμφυλος` III is a gloss the pack marked as a work *title*, so
  `STRIP_WORK` deleted the definition. A stripper may no longer empty a
  zone that had words.
- `ὑπεξάγω` II was a heading orphaned by the flatten pass, which runs
  after banners are decided. Labelless orphans are dropped; labelled ones
  are not — demoting them cost `malus` its "B. In partic." band, caught
  because the mock stopped being byte-identical.

A division the print never labelled (`μέν` A has neither gloss nor
evidence) is an address, not a stripped header: counted, not failed. What
fails is a row with nothing on the line and nothing behind it.

## 7. Out of scope

The Astro side (`/words` rendering, tabs, drawers, sticky, the picker
question). Clickable cross-references. The lemma-first `split_sense`
leak and `examples_of` picking up bare `lx-foreign` citations — both
known, both live in the transform and can be fixed after it moves. The
lexicon and analyses packs are untouched; their format, keying, and
licensing (CC BY-SA, Perseus, attribution on the page) do not change.
