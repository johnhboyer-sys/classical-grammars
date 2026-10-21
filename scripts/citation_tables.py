#!/usr/bin/env python3
"""Hand-built citation normalization tables for the non-Smyth grammars.

One closed table per grammar, in the same shape as
``build_citations_index.py``'s ``AUTHOR_WORK_TABLE``: an exact citation
prefix, as that grammar writes it, mapped to

    (author_full, author_slug, work_full | None, work_slug | None)

``work_full``/``work_slug`` are ``None`` for a single-work corpus (keyed
``<author_slug>.<locator>``); otherwise the key is
``<author_slug>.<work_slug>.<locator>``.

These are tables, not parsers. A prefix that is not listed here is reported
as unparsed by ``build_citations_all.py`` -- never guessed at. Slugs
deliberately reuse Smyth's vocabulary (``thuc``, ``hom.il``, ``plat.apol``,
``soph.ot``, ...) so the same passage gets the same key in every grammar and
the combined index joins across them.

Prefix matching is case-insensitive and whitespace-collapsed (the grammars'
own small-caps rendering leaves strings like ``XEN. Anab.``, ``THuc.`` and
``Hom. OD.`` in the data); the longest listed prefix wins. See
SPEC-citations.md.
"""

from __future__ import annotations

Row = tuple[str, str, str | None, str | None]

# ---------------------------------------------------------------------------
# Shared Greek abbreviations (Perseus style)
#
# Goodwin and Gildersleeve use the same abbreviation system Smyth does, so
# these rows are shared between their two tables. Each grammar's table below
# names the shared block explicitly and then adds its own extras; nothing is
# inherited implicitly.
# ---------------------------------------------------------------------------

GREEK_SHARED: dict[str, Row] = {}


def _single(prefix: str, author_full: str, author_slug: str,
            table: dict[str, Row] | None = None) -> None:
    (GREEK_SHARED if table is None else table)[prefix] = (
        author_full, author_slug, None, None)


def _works(author_prefix: str, author_full: str, author_slug: str,
           works: dict[str, str], table: dict[str, Row] | None = None) -> None:
    target = GREEK_SHARED if table is None else table
    for abbr, slug in works.items():
        prefix = f"{author_prefix} {abbr}" if author_prefix else abbr
        target[prefix] = (author_full, author_slug, abbr, slug)


# -- orators and historians cited as "<Author> <book/oration>.<section>" -----
_single("Thuc.", "Thucydides", "thuc")
_single("Hdt.", "Herodotus", "hdt")
_single("Dem.", "Demosthenes", "dem")
_single("Lys.", "Lysias", "lys")
_single("Isoc.", "Isocrates", "isoc")
_single("Aeschin.", "Aeschines", "aeschin")
_single("Andoc.", "Andocides", "andoc")
_single("Antiph.", "Antiphon", "antiph")
_single("Antiphon", "Antiphon", "antiph")
_single("Isaeus", "Isaeus", "isaeus")
_single("Din.", "Dinarchus", "din")
_single("Lyc.", "Lycurgus", "lycurg")
_single("Lycurg.", "Lycurgus", "lycurg")
_single("Hyp.", "Hyperides", "hyp")
_single("Strab.", "Strabo", "strab")
_single("Stob.", "Stobaeus", "stob")
GREEK_SHARED["Hyp. Eux."] = ("Hyperides", "hyp", "Eux.", "eux")
GREEK_SHARED["Stob. Flor."] = ("Stobaeus", "stob", "Flor.", "flor")
GREEK_SHARED["Diog. Laert."] = ("Diogenes Laertius", "diog-laert", None, None)

# -- Homer, the Homeric Hymns, Hesiod ---------------------------------------
_works("Hom.", "Homer", "hom", {"Il.": "il", "Od.": "od"})
_single("HH", "Homeric Hymns", "hh")
_works("Hes.", "Hesiod", "hes", {"WD": "wd", "Th.": "th", "Sh.": "sh"})

# -- Plato ------------------------------------------------------------------
# Plt./Polit./Stat. are three names for one dialogue (the Politicus); they
# share the slug Smyth uses, "stat". Sym./Symp. likewise.
_works("Plat.", "Plato", "plat", {
    "Apol.": "apol", "Rep.": "rep", "Gorg.": "gorg", "Phaedo": "phaedo",
    "Laws": "laws", "Prot.": "prot", "Theaet.": "theaet", "Euthyd.": "euthyd",
    "Lach.": "lach", "Charm.": "charm", "Menex.": "menex",
    "Euthyph.": "euthyph", "Phileb.": "phileb", "Lysis": "lysis",
    "Soph.": "soph", "Crat.": "crat", "Meno": "meno", "Hipp. Maj.": "hipp-maj",
    "Hipp. Min.": "hipp-min", "Tim.": "tim", "Criti.": "criti",
    "Parm.": "parm", "Sym.": "sym", "Phaedrus": "phaedrus", "Crito": "crito",
    "Ion": "ion", "Theag.": "theag", "Epin.": "epin", "Sis.": "sis",
    "Ax.": "ax", "Lovers": "lovers", "Hipparch.": "hipparch",
    "Stat.": "stat",
})
for _alias, _canon, _slug in [
    ("Plt.", "Stat.", "stat"),
    ("Polit.", "Stat.", "stat"),
    ("Symp.", "Sym.", "sym"),
    ("Phil.", "Phileb.", "phileb"),
    ("Lys.", "Lysis", "lysis"),
]:
    GREEK_SHARED[f"Plat. {_alias}"] = ("Plato", "plat", _canon, _slug)
# Alcibiades I/II: the dialogue number sits between work and locator, exactly
# as in Smyth ("Plat. Alc. 1 110d"); Goodwin and Gildersleeve write it with a
# dot instead ("Plat. Alc. 1.116c"). Both parse: whatever separator stands
# between a matched prefix and its locator is discarded.
GREEK_SHARED["Plat. Alc. 1"] = ("Plato", "plat", "Alc. 1", "alc-1")
GREEK_SHARED["Plat. Alc. 2"] = ("Plato", "plat", "Alc. 2", "alc-2")

# -- Xenophon ---------------------------------------------------------------
_works("Xen.", "Xenophon", "xen", {
    "Anab.": "anab", "Cyrop.": "cyrop", "Hell.": "hell", "Mem.": "mem",
    "Ec.": "ec", "Sym.": "sym", "Hiero": "hiero", "Ages.": "ages",
    "Apol.": "apol", "Ways": "ways", "Horse.": "horse", "Hunt.": "hunt",
    "Cav.": "cav", "Const. Lac.": "const-lac",
})
for _alias, _canon, _slug in [
    ("Xen. An.", "Anab.", "anab"),
    ("Xen. Cyr.", "Cyrop.", "cyrop"),
    ("Xen. Symp.", "Sym.", "sym"),
    ("Xen. Hier.", "Hiero", "hiero"),
    ("Xen. Oecon.", "Ec.", "ec"),
    ("Xen. Cyn.", "Hunt.", "hunt"),
]:
    GREEK_SHARED[_alias] = ("Xenophon", "xen", _canon, _slug)
GREEK_SHARED["Ps. Xen. Const. Ath."] = (
    "Pseudo-Xenophon", "ps-xen", "Const. Ath.", "const-ath")

# -- tragedy and comedy -----------------------------------------------------
_works("Soph.", "Sophocles", "soph", {
    "Ant.": "ant", "OT": "ot", "OC": "oc", "El.": "el", "Phil.": "phil",
    "Aj.": "aj", "Trach.": "trach",
})
_works("Eur.", "Euripides", "eur", {
    "Med.": "med", "Orest.": "orest", "Hec.": "hec", "Alc.": "alc",
    "Hipp.": "hipp", "IT": "it", "Ion": "ion", "El.": "el", "Andr.": "andr",
    "Hel.": "hel", "Ba.": "ba", "Phoen.": "phoen", "Her.": "her",
    "Supp.": "supp", "IA": "ia", "Tro.": "tro", "Cycl.": "cycl",
    "Heraclid.": "heraclid",
})
_works("Aesch.", "Aeschylus", "aesch", {
    "Ag.": "ag", "PB": "pb", "Lib.": "lib", "Eum.": "eum", "Pers.": "pers",
    "Seven": "seven", "Supp.": "supp",
})
_works("Aristoph.", "Aristophanes", "aristoph", {
    "Cl.": "cl", "Wasps": "wasps", "Ach.": "ach", "Frogs": "frogs",
    "Birds": "birds", "Kn.": "kn", "Eccl.": "eccl", "Pl.": "pl",
    "Thes.": "thes", "Lys.": "lys", "Peace": "peace",
})

# -- lyric, elegy, epigram --------------------------------------------------
# Cited by the author's own running number, not by a named work.
for _prefix, _full, _slug in [
    ("Thgn.", "Theognis", "thgn"), ("Theoc.", "Theocritus", "theoc"),
    ("Solon", "Solon", "solon"), ("Tyrt.", "Tyrtaeus", "tyrt"),
    ("Mimn.", "Mimnermus", "mimn"), ("Simon.", "Simonides", "simon"),
    ("Semon.", "Semonides", "semon"), ("Archil.", "Archilochus", "archil"),
    ("Anacr.", "Anacreon", "anacr"),
]:
    _single(_prefix, _full, _slug)
_works("Pind.", "Pindar", "pind",
       {"O.": "o", "P.": "p", "N.": "n", "I.": "i"})
_works("Bacchyl.", "Bacchylides", "bacchyl", {"Ep.": "ep", "Dith.": "dith"})
GREEK_SHARED["Men. Sent."] = ("Menander", "men", "Sent.", "sent")

# -- prose of the schools ---------------------------------------------------
_works("Aristot.", "Aristotle", "aristot", {
    "Nic. Eth.": "nic-eth", "Pol.": "pol", "Met.": "met", "Poetics": "poet",
})
_works("Arr.", "Arrian", "arr", {"An.": "an", "Cyn.": "cyn"})
_works("Luc.", "Lucian", "luc", {"Symp.": "symp", "Am.": "am"})
GREEK_SHARED["Lucian Am."] = ("Lucian", "luc", "Am.", "am")
GREEK_SHARED["Jul. Mis."] = ("Julian", "jul", "Mis.", "mis")
GREEK_SHARED["Hermog. Id."] = ("Hermogenes", "hermog", "Id.", "id")
GREEK_SHARED["Damian. Opt."] = ("Damianus", "damian", "Opt.", "opt")
GREEK_SHARED["A.D. Synt."] = (
    "Apollonius Dyscolus", "apoll-dysc", "Synt.", "synt")
GREEK_SHARED["Plut. Cor."] = ("Plutarch", "plut", "Cor.", "cor")

# -- Greek scripture --------------------------------------------------------
for _prefix, _full, _slug in [
    ("Matthew", "Gospel of Matthew", "matthew"),
    ("Mark", "Gospel of Mark", "mark"),
    ("Luke", "Gospel of Luke", "luke"),
    ("John", "Gospel of John", "john"),
    ("Acts", "Acts of the Apostles", "acts"),
    ("Psalm", "Psalms", "psalms"),
]:
    _single(_prefix, _full, _slug)


# ---------------------------------------------------------------------------
# Latin abbreviations (Allen & Greenough, Perseus style)
#
# Shared with the handful of Latin passages Goodwin quotes for comparison, so
# "Verg. A. 1.37" in Goodwin and in A&G land on one key.
# ---------------------------------------------------------------------------

LATIN_SHARED: dict[str, Row] = {}

_works("Cic.", "Cicero", "cic", {
    "Fam.": "fam", "Att.": "att", "Q. Fr.": "q-fr", "ad Brut.": "ad-brut",
    "Ver.": "ver", "Catil.": "catil", "Mil.": "mil", "S. Rosc.": "s-rosc",
    "Man.": "man", "Clu.": "clu", "Quinct.": "quinct", "Arch.": "arch",
    "Mur.": "mur", "Flac.": "flac", "Rab. Post.": "rab-post",
    "Rab. Perd.": "rab-perd", "Sest.": "sest", "Deiot.": "deiot",
    "Lig.": "lig", "Marc.": "marc", "Pis.": "pis", "Cael.": "cael",
    "Vat.": "vat", "Q. Rosc.": "q-rosc", "Planc.": "planc", "Caec.": "caec",
    "Sul.": "sul", "Tul.": "tul", "Font.": "font", "Div. Caec.": "div-caec",
    "Scaur.": "scaur", "Balb.": "balb", "Dom.": "dom", "Har.": "har",
    "Prov.": "prov", "Agr.": "agr", "Phil.": "phil", "Tusc.": "tusc",
    "Sen.": "sen", "Amic.": "amic", "Off.": "off", "Fin.": "fin",
    "de Orat.": "de-orat", "N. D.": "n-d", "Div.": "div", "Orat.": "orat",
    "Leg.": "leg", "Luc.": "luc", "Parad.": "parad", "Inv.": "inv",
    "Tim.": "tim", "Ac.": "ac", "Fat.": "fat", "Top.": "top",
}, table=LATIN_SHARED)
# A&G cites the Laelius de Amicitia under both of its names.
LATIN_SHARED["Lael."] = ("Cicero", "cic", "Amic.", "amic")
# A&G writes the De Natura Deorum without the space Perseus uses.
LATIN_SHARED["Cic. N.D."] = ("Cicero", "cic", "N. D.", "n-d")

_works("Caes.", "Caesar", "caes", {"Gal.": "gal", "Civ.": "civ"},
       table=LATIN_SHARED)
LATIN_SHARED["B. Alex."] = ("Pseudo-Caesar", "ps-caes", "B. Alex.", "b-alex")
_works("Verg.", "Vergil", "verg", {"A.": "a", "Ecl.": "ecl", "G.": "g"},
       table=LATIN_SHARED)
_works("Hor.", "Horace", "hor",
       {"S.": "s", "Carm.": "carm", "Ep.": "ep", "Ars": "ars"},
       table=LATIN_SHARED)
_works("Ov.", "Ovid", "ov",
       {"Met.": "met", "Ars": "ars", "Ep.": "ep", "Tr.": "tr"},
       table=LATIN_SHARED)
_works("Sal.", "Sallust", "sal", {"Jug.": "jug", "Cat.": "cat"},
       table=LATIN_SHARED)
_works("Tac.", "Tacitus", "tac",
       {"Ann.": "ann", "Hist.": "hist", "Ag.": "ag"}, table=LATIN_SHARED)
_works("Ter.", "Terence", "ter", {
    "Ph.": "ph", "Eu.": "eu", "An.": "an", "Ad.": "ad", "Hau.": "hau",
    "Hec.": "hec",
}, table=LATIN_SHARED)
_works("Pl.", "Plautus", "pl", {
    "Trin.": "trin", "Am.": "am", "Mil.": "mil", "As.": "as", "Aul.": "aul",
    "Capt.": "capt", "St.": "st", "Cur.": "cur", "Per.": "per",
    "Rud.": "rud", "Epid.": "epid", "Mer.": "mer", "Cist.": "cist",
    "Bac.": "bac", "Mos.": "mos", "Truc.": "truc", "Ps.": "ps",
    "Poen.": "poen", "Men.": "men",
}, table=LATIN_SHARED)
_works("Nep.", "Cornelius Nepos", "nep", {
    "Att.": "att", "Timoth.": "timoth", "Eum.": "eum", "Ag.": "ag",
    "Han.": "han", "Ep.": "ep", "Dat.": "dat", "Paus.": "paus",
    "Alc.": "alc",
}, table=LATIN_SHARED)
_works("Sen.", "Seneca the Younger", "sen", {
    "Ep.": "ep", "Med.": "med", "Her. F.": "her-f", "Her. O.": "her-o",
}, table=LATIN_SHARED)
_works("Suet.", "Suetonius", "suet",
       {"Jul.": "jul", "Dom.": "dom", "Aug.": "aug"}, table=LATIN_SHARED)
LATIN_SHARED["Plin. Ep."] = ("Pliny the Younger", "plin-min", "Ep.", "ep")
LATIN_SHARED["Plin. Nat."] = ("Pliny the Elder", "plin-mai", "Nat.", "nat")
LATIN_SHARED["Quint. Inst."] = ("Quintilian", "quint", "Inst.", "inst")
LATIN_SHARED["Apul. Met."] = ("Apuleius", "apul", "Met.", "met")
LATIN_SHARED["Cato Agr."] = ("Cato the Elder", "cato", "Agr.", "agr")
LATIN_SHARED["Var. R."] = ("Varro", "var", "R.", "r")
for _prefix, _full, _slug in [
    ("Liv.", "Livy", "liv"), ("Curt.", "Curtius Rufus", "curt"),
    ("Vell.", "Velleius Paterculus", "vell"), ("Juv.", "Juvenal", "juv"),
    ("Mart.", "Martial", "mart"), ("Lucr.", "Lucretius", "lucr"),
    ("Prop.", "Propertius", "prop"), ("Catul.", "Catullus", "catul"),
    ("Pers.", "Persius", "pers"), ("Gel.", "Aulus Gellius", "gel"),
    ("V. Max.", "Valerius Maximus", "v-max"),
]:
    _single(_prefix, _full, _slug, table=LATIN_SHARED)


# ---------------------------------------------------------------------------
# Per-grammar tables
# ---------------------------------------------------------------------------

# Goodwin, *Syntax of the Moods and Tenses of the Greek Verb*.
# Perseus Greek plus the Latin passages Goodwin quotes for comparison.
# Deliberately absent: the bare continuation references Goodwin's source
# leaves behind -- "Id. An. 13.", "Ib. 26.", "Cyr. 22", "Hell. 16.", bare
# "Alc.", "Gorg.", "Men.", "Soph.", "Sept.", "Pac.", "Nic.", "An.", "Erot.",
# "Marc.", "Lib. Eth." -- which name a work or a section without the book
# that governs it and cannot be resolved without reading the surrounding
# prose; and every fragment reference ("Eur. Fr.", "Soph. Fr.", "Acus. Fr.",
# "LYS. Frag.", ...), whose numbering is edition-specific. Both go to
# meta.unparsedCitations.
GOODWIN: dict[str, Row] = {**GREEK_SHARED, **LATIN_SHARED}
GOODWIN["Cic.Ver."] = ("Cicero", "cic", "Ver.", "ver")
GOODWIN["Euc."] = ("Euclid", "euc", None, None)
# Two bare Latin titles Goodwin uses for plays he elsewhere abbreviates in
# full: Septem contra Thebas (which he also writes "Aesch. Seven") and Pax
# (also "Aristoph. Peace"). Both are listed because they are unambiguous in
# Goodwin's corpus and because their line numbers fit -- Sept. 38-1015
# against the Seven's 1078 lines, Pac. 135-1302 against the Peace's 1357.
GOODWIN["Sept."] = ("Aeschylus", "aesch", "Seven", "seven")
GOODWIN["Pac."] = ("Aristophanes", "aristoph", "Peace", "peace")

# Gildersleeve, *Syntax of Classical Greek*.
# The same Perseus Greek block. Deliberately absent: every "fr." reference
# (Nauck's TGF, Bergk, Meineke, Kock, Ahrens, Rzach, Schneidewin -- the
# edition is part of the citation and the numbering does not carry across
# editions); the comic-fragment authors cited only by Meineke
# volume.page.line ("Philem. 4.40", "Pherecr. 2.281.3", ...); and the modern
# scholarship Gildersleeve cites in the same tags ("Blass, Rhein. Mus. ...",
# "J. H. U. Circ. ...", "W. St. ...", "Msth., Gr. d. Att. Inschr.2").
GILDERSLEEVE: dict[str, Row] = {**GREEK_SHARED, **LATIN_SHARED}
GILDERSLEEVE["Dem. Ex."] = ("Demosthenes", "dem", "Ex.", "ex")
GILDERSLEEVE["Plat. Euthyph"] = ("Plato", "plat", "Euthyph.", "euthyph")

# Monro, *A Grammar of the Homeric Dialect*: Homer and nothing else.
MONRO: dict[str, Row] = {
    "Il.": ("Homer", "hom", "Il.", "il"),
    "Od.": ("Homer", "hom", "Od.", "od"),
}

# Goodell, *A School Grammar of Attic Greek*: full work names in English.
# Slugs are Smyth's, so Goodell's "Soph. Oedipus the King 413" and Smyth's
# "Soph. OT 413" are one key. The misspellings below are Goodell's own and
# are listed explicitly rather than repaired by a fuzzy match. Deliberately
# absent: "Menander FCG" (Fragmenta Comicorum Graecorum -- edition-specific),
# "Corpus Inscriptionum Atticarum" (an inscription corpus, as in Smyth), and
# the cite fields that hold running prose rather than a citation.
GOODELL: dict[str, Row] = {}
_single("Thucydides", "Thucydides", "thuc", table=GOODELL)
_single("Demosthenes", "Demosthenes", "dem", table=GOODELL)
_single("Lysias", "Lysias", "lys", table=GOODELL)
_works("Xen.", "Xenophon", "xen", {
    "Anabasis": "anab", "Hellenica": "hell", "Memorabilia": "mem",
    "Cyropaedia": "cyrop",
}, table=GOODELL)
_works("Plato", "Plato", "plat", {
    "Apology": "apol", "Protagoras": "prot", "Phaedo": "phaedo",
    "Crito": "crito", "Republic": "rep", "Gorgias": "gorg",
}, table=GOODELL)
_works("Soph.", "Sophocles", "soph", {
    "Oedipus the King": "ot", "Oedipus at Colonus": "oc", "Antigone": "ant",
    "Philoctetes": "phil", "Electra": "el", "Ajax": "aj",
}, table=GOODELL)
_works("Aesch.", "Aeschylus", "aesch", {
    "Prometheus Bound": "pb", "Agamemnon": "ag",
    "Seven Against Thebes": "seven", "Libation Bearers": "lib",
    "Eumenides": "eum", "Persians": "pers",
}, table=GOODELL)
_works("Eur.", "Euripides", "eur", {
    "Medea": "med", "Alcestis": "alc", "Hippolytus": "hipp",
    "Andromache": "andr", "Electra": "el", "The Trojan Women": "tro",
    "Iphigenia in Tauris": "it", "Iphigenia in Aulis": "ia",
}, table=GOODELL)
_works("Aristoph.", "Aristophanes", "aristoph", {
    "Clouds": "cl", "Frogs": "frogs", "Wasps": "wasps",
}, table=GOODELL)
GOODELL["Aristot. Poetics"] = ("Aristotle", "aristot", "Poetics", "poet")
# Goodell's own misspellings, listed one by one so the table stays a table.
# They keep the correctly spelled work name, so each slug still stands for
# exactly one work.
for _typo, _row in {
    "Xen. Anabais": ("Xenophon", "xen", "Anabasis", "anab"),
    "Xen. Anabsis": ("Xenophon", "xen", "Anabasis", "anab"),
    "Xen. Anabsais": ("Xenophon", "xen", "Anabasis", "anab"),
    "Xen. Memorobilia": ("Xenophon", "xen", "Memorabilia", "mem"),
    "Thucycides": ("Thucydides", "thuc", None, None),
    "Aesch. Prometheus Bond": ("Aeschylus", "aesch", "Prometheus Bound", "pb"),
    "Eur. Iphigenia in Taurus": (
        "Euripides", "eur", "Iphigenia in Tauris", "it"),
    "Eur. Ipheginia in Tauris": (
        "Euripides", "eur", "Iphigenia in Tauris", "it"),
}.items():
    GOODELL[_typo] = _row

# Allen & Greenough, *New Latin Grammar*: Perseus Latin, and nothing else.
# Deliberately absent: "Sal. Fr." (Maurenbrecher's numbering of the Historiae
# fragments) and "Pub. Com." (one citation, ambiguous).
AG: dict[str, Row] = dict(LATIN_SHARED)

TABLES: dict[str, dict[str, Row]] = {
    "goodwin-gmt": GOODWIN,
    "gildersleeve": GILDERSLEEVE,
    "monro": MONRO,
    "goodell": GOODELL,
    "ag": AG,
}

# ---------------------------------------------------------------------------
# Minimum locator depth
#
# Goodwin's source leaves truncated continuation references behind: a section
# that cites "XEN. Cyr. i. 6. 13" and then "Ib. 47" converts to data-cite
# "Xen. Cyrop. 47", with the book and chapter that governed it gone. For the
# multi-book narrative works below -- always cited book.chapter(.section) or
# book.line by every grammar here -- a bare single number is one of those
# truncations, not a whole-book reference: all 135 in the corpus were
# inspected and none is a genuine reference to a whole book, while many are
# outright impossible (Cyrop. 47 of 8 books, Thuc. 108 of 8, Hdt. 202 of 9).
# They are reported as unparsed rather than keyed to a passage that does not
# exist. Works not listed here (Plato by Stephanus page, the orators by
# oration, Pindar by ode, drama by line) have no depth requirement.
MIN_LOCATOR_DEPTH: dict[tuple[str, str | None], int] = {
    ("hom", "il"): 2,
    ("hom", "od"): 2,
    ("xen", "anab"): 2,
    ("xen", "cyrop"): 2,
    ("xen", "hell"): 2,
    ("xen", "mem"): 2,
    ("thuc", None): 2,
    ("hdt", None): 2,
    ("arr", "an"): 2,
}

# ---------------------------------------------------------------------------
# Book counts
#
# The same compression that produces a too-shallow locator also produces one
# whose *first* element is impossible. Gildersleeve's dense back-reference
# runs ("DEM.1.7 DEM., 1.11 ... THUC., 76.4") repeat the author and compress
# the locator, and sometimes the book falls out, leaving a chapter and
# section where a book and chapter should be: "THUC., 76.4" keyed naively is
# Thucydides book 76, of a work that has eight.
#
# For a work whose first locator element runs over a closed, well-known set --
# books of a history, odes of a Pindaric book, orations of an orator's
# corpus -- that count is recorded here, and a citation whose first element
# exceeds it is reported as unparsed rather than keyed to a passage that
# cannot exist.
#
# Only closed counts belong here. Deliberately absent, and why:
#   * every Plato dialogue -- the first element is a Stephanus page, not a
#     book;
#   * Aristotle -- Goodwin cites the *Nicomachean Ethics* both as book.chapter
#     ("Nic. Eth. 10. 1") and by bare Bekker page ("Nic. Eth. 1139b"), so the
#     first element is not reliably a book at all; a ceiling of 10 would have
#     thrown out four sound Bekker references;
#   * tragedy and comedy -- the first element is a verse line;
#   * lyric and elegy cited by the poet's own running number;
#   * Plautus and Terence -- A&G cites some plays by act.scene (max 5) and
#     others by bare line ("Pl. Truc. 60"), so no one ceiling fits;
#   * Tacitus' *Histories* -- five books survive of twelve or fourteen
#     written, so "closed" is ambiguous;
#   * Isaeus -- eleven speeches survive and Perseus numbers a twelfth for the
#     fragments, so 12 looked closed, until this check found Smyth's own TEI
#     citing "Isaeus 14.52" (§2698). Some edition numbers him past 12, or the
#     TEI is wrong; either way I cannot vouch for a count, so there is none;
#   * Hyperides, Stobaeus, Theocritus, Martial, Catullus, Persius, Seneca's
#     *Epistulae*, Aristotle's *Poetics*, the Homeric Hymns' outliers -- the
#     numbering is fragmentary, editorial, or one I could not vouch for.
# A work absent from this table is simply not ceiling-checked.
BOOK_COUNTS: dict[tuple[str, str | None], int] = {
    # -- Greek histories and multi-book prose -------------------------------
    ("thuc", None): 8,
    ("hdt", None): 9,
    ("hom", "il"): 24,
    ("hom", "od"): 24,
    ("xen", "anab"): 7,
    ("xen", "cyrop"): 8,
    ("xen", "hell"): 7,
    ("xen", "mem"): 4,
    ("arr", "an"): 7,
    ("diog-laert", None): 10,
    ("strab", None): 17,
    ("euc", None): 13,
    # -- the Attic orators: corpora fixed at these numbers, with letters and
    # prooemia cited separately (Gildersleeve's "Dem. Ex." has its own row) --
    ("dem", None): 61,
    ("isoc", None): 21,
    ("lys", None): 35,
    ("antiph", None): 6,
    ("andoc", None): 4,
    ("aeschin", None): 3,
    ("din", None): 3,
    # Lycurgus survives in one speech, Against Leocrates. Goodwin's bare
    # "LYCURG. 100" is that speech's section 100 with the oration number
    # dropped -- but supplying the number the print does not write is a
    # repair, not a reading, so those five citations go unkeyed like the rest.
    ("lycurg", None): 1,
    # -- Pindar's four books of epinicians ----------------------------------
    ("pind", "o"): 14,
    ("pind", "p"): 12,
    ("pind", "n"): 11,
    ("pind", "i"): 9,
    # -- Greek scripture ----------------------------------------------------
    ("matthew", None): 28,
    ("mark", None): 16,
    ("luke", None): 24,
    ("john", None): 21,
    ("acts", None): 28,
    ("psalms", None): 150,
    # -- Latin --------------------------------------------------------------
    ("caes", "gal"): 8,
    ("caes", "civ"): 3,
    ("verg", "a"): 12,
    ("verg", "ecl"): 10,
    ("verg", "g"): 4,
    ("liv", None): 142,
    ("lucr", None): 6,
    ("hor", "carm"): 4,
    ("hor", "s"): 2,
    ("hor", "ep"): 2,
    ("ov", "met"): 15,
    ("ov", "ars"): 3,
    ("ov", "tr"): 5,
    ("ov", "ep"): 21,
    ("juv", None): 16,
    ("prop", None): 4,
    ("curt", None): 10,
    ("vell", None): 2,
    ("v-max", None): 9,
    ("gel", None): 20,
    ("quint", "inst"): 12,
    ("apul", "met"): 11,
    ("var", "r"): 3,
    ("plin-min", "ep"): 10,
    ("plin-mai", "nat"): 37,
    ("tac", "ann"): 16,
    ("cic", "fam"): 16,
    ("cic", "att"): 16,
    ("cic", "q-fr"): 3,
    ("cic", "ver"): 2,
    ("cic", "catil"): 4,
    ("cic", "phil"): 14,
    ("cic", "tusc"): 5,
    ("cic", "n-d"): 3,
    ("cic", "off"): 3,
    ("cic", "fin"): 5,
    ("cic", "de-orat"): 3,
    ("cic", "div"): 2,
    ("cic", "leg"): 3,
    ("cic", "inv"): 2,
    ("cic", "agr"): 3,
}

# Bennett's *New Latin Grammar* has no table here: its 1,221 extracted
# examples carry no cite at all and its HTML has no <cite> tags, so there is
# nothing to index. See SPEC-citations.md.
