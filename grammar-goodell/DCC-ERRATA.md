# DCC Goodell errata ledger

Defects found in the DCC edition of Goodell (*A School Grammar of Attic
Greek*, ed. Meagan Ayer et al.) while converting the mirrored pages in
`grammar-goodell/src/dcc/`. Each entry records the defect, the evidence,
and how our data handles it. The ledger exists so the findings survive
in one place — for our own conversions, and to hand to DCC upstream
(https://dcc.dickinson.edu/) if John chooses to report them.

Machine-readable counterparts: `data/goodell/meta.json` under
`anomalies` (conversion pass), `data/goodell/index-english.json` under
`_meta.repairs` (index pass), and the WARN output of
`scripts/verify_index_goodell.py`.

## english-index.html (found 2026-08-15, index extraction + Codex review)

| # | defect | evidence | our handling |
|---|---|---|---|
| 1 | Typo "Relexive pronouns" for *Reflexive* | entry headword; §§197–201 spell it Reflexive | repaired; source spelling kept in `_meta.repairs` |
| 2 | Two entries fused on one line: "Conjunctions, coordinating 602; Consonants, classified 38, …" share a `<br>` line | between *Conjunctions* and *Contraction* in the C run | split into two entries; recorded in `_meta.repairs` |
| 3 | Five citation links carry the previous link's section fragment | Accent "in crasis 37" → `#…36`; Accent "of contract adjs. 89.b" → `#seven-seven`; Crasis "accent in 37" → `#…36`; Middle "participles, declined 276" → `#…275`; Participle "endings 275" ✓ but "declension … 276" → `#…275` | visible citations verified correct against section content; data records the visible numbers; verify script WARNs |
| 4 | Broken attribute quoting swallows `target=` into the href (`href="…#four-three-three target="`) | *Descent*, *Patronymics*, *Verbal nouns and adjs.* entries | fragment decoder splits on non-letter runs, so the section number still validates |
| 5 | Citation links with no `href` at all | "Nasal class … 356", "Present system … 356, 357", "Wish … 476" | parsed as citations anyway; link validation recorded as unavailable |
| 6 | Trailing comma set inside the link text ("72.d,") | *Accent*, "recessive in certain vocatives" | token parser strips terminal punctuation |
| 7 | One citation links the odd relative form `chapters/Chapter-638` instead of a chapter page | *Purpose*, "638 a, c & d" | treated as a section hint; no slug to validate |
| 8 | Range endpoints linked separately with a bare text dash between ("38 – 56", "627 – 635", "1 – 7", "402 – 414") | *Consonants*, *Indicative mode*, *Pronunciation*, *Verbal nouns and adjs.* | endpoints joined into one range ref; arguably presentation rather than error, listed for completeness |

## Chapter pages (found earlier, conversion pass — `data/goodell/meta.json` anomalies)

| # | defect | evidence | our handling |
|---|---|---|---|
| 9 | Eight section markers printed without the closing dot ("11" not "11."), one with trailing text ("385. εἶμι") | §§11, 49, 130, 143, 194, 385, 514, 528 (`anomalies.markerAudit`) | converter accepts both forms; audit list committed |
| 10 | Combining macron stacked outermost, over breathing and accent (the transmission defect Smyth's print corrects innermost) | 8 restacked, 1 anceps kept (`anomalies.sourceMarkRepairs`) | restacked with the shared `convert_smyth` rule before parsing |
| 11 | One malformed table swallows the page's Drupal footer into the section body in a stdlib HTML tree | "Suggested Citation" text appearing inside a section | converter truncates the body at the citation block |
| 12 | §523's section number split across two adjacent `<strong>` tags | ω-conjugation page | converter reassembles the marker |

## Mixed Greek and Latin scripts (found 2026-08-26, script-mixing audit)

The DCC pages set some words in the wrong script, in both directions. A Greek
word picks up a Latin lookalike ("tί" for *τί*, 158 times); an English word
picks up a Greek one ("alsο" for *also*, "knοw" for *know*). Only the first
direction was repaired, so the second survived into the data — and because the
old rule converted a Latin letter whenever a *neighbouring* character was
Greek, one stray omicron pulled the rest of its word across with it
("knοw" → "kνοw"). The audit found 67 sections affected in `html`, 103 in
`plain`. Mixed-script words break text search and copy on any site serving the
data. The other four non-Smyth works (Gildersleeve, Goodwin, Monro, Bennett)
are clean; this is a Goodell-only, DCC-only defect.

| # | defect | evidence | our handling |
|---|---|---|---|
| 13 | Greek lookalikes set inside English words | "alsο" §518, "knοw" ×8, "hοw" ×8, "οf" ×16, "οr" ×8, "Νοrway" §506; 67 sections in all | `clean_chars` now decides per word, not per neighbouring character: it moves stray lookalikes into whichever script the word's unambiguous letters attest, and leaves a word alone when both scripts are attested |
| 14 | Word-final sigma typed as a Latin s | "ὡs" §507, "οὗτοs" §676, "θέs" §379, "χρεωs" §449, "πείσῃs" §474, "οὕs" §614, "ὁπόσοs" §621 | restored to ς where the trailing s is the word's only Latin letter |
| 15 | Three words the source leaves genuinely ambiguous | "wίse" §177 (Greek accented iota in *wise*), "cσmpleted" §456 (Greek sigma for *o*), "στέφωput" §412 (Greek headword and English gloss fused in a table cell) | left as found — both scripts are attested, and repairing them would mean emending |
| 16 | A missing space at a tag boundary: `<strong>οὗ</strong>retain` | §379, the only such fusion in the corpus | left as found; it renders fused on DCC too |

Our own defect, fixed alongside these: `plain()` flattened the markup without
a separator, so DCC's "<strong>Greek</strong><br><em>gloss</em>" pattern fused
into one word ("δεινοῦout") and `clean_chars` then read the English gloss as
Greek ("πόλεωςin" → "πόλεωςιν", "the" → "τηε" 26 times). `plain()` now treats
a line, cell, or block edge as a word boundary. Regression tests:
`scripts/test_goodell_script_mixing.py`.

Additions belong here as they are found; renumber nothing, append only.
