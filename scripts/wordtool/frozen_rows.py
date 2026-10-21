#!/usr/bin/env python3
"""Frozen T8 rows for a fixed set of entries: the fast regression gate.

The pack diff is the honest gate and it costs a rebuild, about
twenty-five minutes for both packs. That is the right price to pay
before shipping, and the wrong price to pay while writing a rule. This
runs the transform over a few hundred committed entries and compares the
result with what it produced when the file was last blessed, in a few
seconds, so a rule that breaks something is caught while it is still
being written.

It reads the entries from the committed lexicon packs (`grc-lsj`,
`lat-ls`), never from the Diogenes sources, so it runs anywhere the repo
is checked out.

The set is chosen, not sampled at random alone. Every entry that drove a
rule is in it, named in `SEEDS` beside the rule it settled, because those
are the shapes a later rule is most likely to break. A seeded spread
across the buckets is added for breadth, so a rule that damages ordinary
entries is caught too.

Cross-entry effects are covered, which is the point. `first_gloss`
reaches into the entry a stub points at; ἀλυκτρόν borrows from φύος, and
when a rule lengthened φύος's line every entry pointing at it silently
began shipping a gloss of "cod". Both entries are frozen here, so the
next such change fails in seconds rather than after a build and a diff
against the branch point.

Usage:
    python3 scripts/wordtool/frozen_rows.py            # check, exit 1 on drift
    python3 scripts/wordtool/frozen_rows.py --update   # re-bless, then READ THE DIFF

A difference is not a failure; it is a question. Read every one and
explain it, exactly as `diff_packs.py` requires, before re-blessing.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import extract  # noqa: E402
import t8rows  # noqa: E402

FROZEN = os.path.join(HERE, "data", "rows-frozen.json")

# Entries that settled a rule, with the rule they settled. When one of
# these changes, the rule named beside it is the first place to look.
SEEDS = {
    "grc-lsj": [
        ("ἀβακίσκος", "a Greek run the sentence governs stays on the line"),
        ("σισυρνοδύτης", "the governed run inside the print's italic"),
        ("στομφασμός", "two governed runs in one sentence"),
        ("ἐπιμωμάομαι", "the print's comma still makes a quotation"),
        ("Ἀδρόμιος", "sc. governs the word it supplies"),
        ("ἀβόητος", "the bracket belongs with its letters"),
        ("ἀβίωτος", "a bracket closed outside the span"),
        ("ἀδιαπνευστέω", "a bracketed author is a citation"),
        ("λεπτοκοπέω", "a second locus after the print's comma"),
        ("ξεστιαῖος", "the object Perseus wrapped into the quotation"),
        ("ἀκόσμητος", "a one-word quote moves whole"),
        ("ψιλοκιθαριστής", "the italic after a moved quote comes too"),
        ("προσαγωγή", "Id. resolves from the sense's own zone"),
        ("ἐπάγω", "a bare title keeps the author the print named"),
        ("οὐσία", "Id. across a sense boundary"),
        ("κρούω", "Id. after a prose mention"),
        ("κηρύσσω", "Id. after l.c."),
        ("ἀγμείονες", "Id. in a glossary entry's chips"),
        ("ἀανές", "Id. and a second author in one row"),
        ("ἀβηροῦσιν", "Id. repeated down a glossary"),
        ("ἀνάριθμος", "an editor's conjecture is not the antecedent"),
        ("ἀγαθός", "Od. is Homer's, not Theophrastus'"),
        ("ἄκανθα", "a Homeric title after a Theophrastus citation"),
        ("παύω", "a bare Od. after another author"),
        ("λύθρον", "Homer keeps his own works"),
        ("κυμβίον", "two loci, no space after the comma"),
        ("παραδρομίς", "further loci after the print's comma"),
        ("ἐπικριτήριον", "a space before the comma, left by a strip"),
        ("ἑκαστάκις", "a roman volume in the locus"),
        ("σελίς", "al. between two loci"),
        ("ἐγγραφή", "the forms bar wins where the line agrees"),
        ("ἑβδεμήκοντα", "the identity line reads loci as the bar does"),
        ("ἀγγέλλω", "a cut may not break a label chain"),
        ("ἀφύσσω", "a cut only from the end of the line"),
        ("μοναρχέω", "a whole identity line that duplicates the bar"),
        ("ἐσώτατος", "a cut at the end of the line"),
        ("θεόπληκτος", "the Greek inside the print's aside"),
        ("ἤτριον", "an aside about the word it defines"),
        ("μετεωριστής", "an aside explaining a dialect form"),
        ("ποτίζω", "an orphaned bracket is not an aside"),
        ("ἀφοπλίζω", "the mate may sit inside the run"),
        ("ἔκλαμπρος", "a candidate with a cue outranks an aside"),
        ("ἀλυκτρόν", "a borrowed gloss reads outside the brackets"),
        ("φύος", "the entry a stub borrows from"),
        ("ἔνδοι", "an aside read as the sense"),
        ("πυρρός", "a gloss the print states after its quotation"),
        ("σύνοικος", "a quotation glued to the sense line"),
        ("ἀφαιρέω", "a gloss recovered from inside a citation"),
        ("ἀβαρής", "an Adv. block states its gloss in its citation"),
        ("ἁβρός", "several definitions in one sense paragraph"),
        ("μέν", "the entry whose first sense renders nothing"),
        ("ἄλλος", "an ellipsis at the head of a quotation"),
        ("Μῶἁ", "the key's rough breathing is not a bracket"),
        ("βούνιον", "a quotation moved whole leaves no empty element"),
        ("καπνίας", "a continuation row the print numbers"),
        ("πρυτανικός", "a continuation row inside a sense"),
    ],
    "lat-ls": [
        ("concitor", "a quotation cannot close the definition's bracket"),
        ("tutor", "nothing left to quote"),
        ("defervesco", "the aside's tail and the quotation after it"),
        ("gloriosus", "a synonym list the strip had eaten"),
        ("exordium", "a synonym list after a citation"),
        ("extorqueo", "a short synonym list"),
        ("contabulo", "an aside closed past the citation"),
        ("propositio", "a Latin quotation standing as the sense line"),
        ("Massilia", "the Greek an aside is about"),
        ("cana", "a Greek etymology inside an aside"),
        ("colloco", "a Greek verb named in an aside"),
        ("Bendidius", "a Greek name in an aside"),
        ("emolumentum", "Greek terms inside a quotation"),
        ("cinefactus", "an editor's note is not the sense"),
        ("eclipsis", "the print's first sense, not its apparatus"),
        ("Tigellinus", "a gloss behind a run of line numbers"),
        ("aberratio", "a prose mention is an antecedent"),
        ("actio", "ib. resolves like id."),
        ("invideo", "an equation opening a sense"),
        ("Aba", "a leading period is the headword's"),
        ("ce", "a bracket opened on nothing at the line's end"),
        ("apor", "a pointer with its q. v. dropped"),
        ("abstractus", "a source that stops after the gender"),
        ("aio", "id. across a sense boundary"),
        ("assecla", "id. after a prose mention"),
    ],
}

# Entries drawn by a fixed seed, for breadth: a rule that damages
# ordinary entries rather than the awkward ones is caught here.
SPREAD = 120
SEED = 20260907


def spread(dataset):
    idx = json.load(open(os.path.join(extract.PACKDIR, f"{dataset}.idx.json")))
    rng = random.Random(SEED)
    names = sorted(idx["buckets"])
    picks = []
    for bucket in rng.sample(names, min(30, len(names))):
        keys = sorted(extract.load_bucket(dataset, bucket) or {})
        if keys:
            picks.extend(rng.sample(keys, min(4, len(keys))))
    return sorted(set(picks))[:SPREAD]


def render(dataset):
    """{key: [doc, ...]} for every frozen entry of this dataset."""
    analyses = "grc-analyses" if dataset.startswith("grc") else "lat-analyses"
    lang = "grc" if dataset.startswith("grc") else "la"
    t8rows.configure(dataset, analyses, lang)
    fold = extract.fold_greek if dataset.startswith("grc") else extract.fold_latin
    out = {}
    for head, _why in SEEDS[dataset]:
        out.setdefault(fold(head), None)
    for key in spread(dataset):
        out.setdefault(key, None)
    for key in list(out):
        recs = extract.get(dataset, key)
        if not recs:
            out.pop(key)
            continue
        docs = []
        for rec in recs:
            model = t8rows.model(rec.get("head") or key, rec)
            docs.append(t8rows.to_doc(model, rec.get("key") or ""))
        out[key] = docs
    return out


def build():
    return {name: render(name) for name in ("grc-lsj", "lat-ls")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--update", action="store_true",
                    help="re-bless the file, then read the diff before committing")
    args = ap.parse_args()
    fresh = build()
    n = sum(len(v) for v in fresh.values())
    if args.update:
        with open(FROZEN, "w", encoding="utf-8") as fh:
            json.dump(fresh, fh, ensure_ascii=False, indent=1, sort_keys=True)
            fh.write("\n")
        print(f"blessed {n} entries into {os.path.relpath(FROZEN)}")
        print("read `git diff` on that file and explain every change before committing")
        return 0
    if not os.path.exists(FROZEN):
        print(f"{FROZEN} is missing; run with --update to create it")
        return 1
    frozen = json.load(open(FROZEN, encoding="utf-8"))
    # Compare what the file can hold. to_doc returns tuples in places
    # (the forms bar, the group labels) and JSON has only arrays, so a
    # raw comparison calls every one of them a change.
    fresh = json.loads(json.dumps(fresh, ensure_ascii=False))
    drift = []
    for dataset in sorted(set(frozen) | set(fresh)):
        was, now = frozen.get(dataset, {}), fresh.get(dataset, {})
        for key in sorted(set(was) | set(now)):
            if was.get(key) != now.get(key):
                why = dict((k, v) for k, v in
                           ((extract.fold_greek(h) if dataset.startswith("grc")
                             else extract.fold_latin(h), w)
                            for h, w in SEEDS[dataset])).get(key, "")
                head = ((now.get(key) or was.get(key) or [{}])[0] or {}).get("head", key)
                drift.append((dataset, head, why))
    if not drift:
        print(f"frozen rows unchanged: {n} entries over both lexica")
        return 0
    print(f"{len(drift)} of {n} frozen entries changed:")
    for dataset, head, why in drift:
        print(f"  {dataset} {head}" + (f"   [{why}]" if why else ""))
    print("\nEach one is a question, not a verdict. Read it, explain it, and")
    print("re-bless with --update only once you can say why it changed.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
