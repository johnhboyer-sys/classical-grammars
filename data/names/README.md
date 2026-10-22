# Proper-name supplement (DRAFT until John approves)

`names.jsonl` holds one short entry per Greek proper name that LSJ does not cover, for the T8 lookup (`scripts/wordtool/names_supplement.py` adds them to `grc-lsj-t8` and attaches their keys to `grc-analyses`). The first set covers the names in the 44 plays of the Greek Drama Reader that T8 missed on 2026-10-22 (greek-plays `docs/proper-names/`).

Each line: `key` (the Morpheus lemma in Beta Code, as `grc-analyses` stores it), `head`, `en` (the English name), `text` (the entry), and `source`:

- `smith-bio:<id>`: William Smith, *Dictionary of Greek and Roman Biography and Mythology* (1849), entry `<id>`.
- `smith-geo:<id>`: William Smith, *Dictionary of Greek and Roman Geography* (1854), entry `<id>`.
- `own`: written for this supplement (patronymics, adjectives, Ionic spellings, Aristophanes' invented characters).

The entries are short summaries in our own words.

## Licence

The Smith entries are drawn from the Perseus Digital Library's TEI texts:

> Text provided under a CC BY-SA license by Perseus Digital Library, http://www.perseus.tufts.edu, with funding from the National Endowment for the Humanities and Tufts University. Data accessed from https://github.com/PerseusDL/canonical-pdlrefwk/ (`data/viaf88890045/003/viaf88890045.003.perseus-eng1.xml` and `data/viaf88890045/002/viaf88890045.002.xml`) on 2026-10-22.

This supplement is released under the same licence, CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0/). John Boyer, 2026-10-22: "cc by-sa fine".
