#!/usr/bin/env python3
"""T8 — LSJ/L&S entry into rows.

The transform half of the T8 design: a pack entry in, the print's senses
out as rows — English first, the print's own wording, hierarchy intact.
No page markup, no CSS, no abbreviation expansion; those belong to
whoever renders it. `gen_cgl.py` renders the design mock from this;
the wordtool pack builder will render JSON from the same rows.

See grammars/scripts/wordtool/SPEC-t8-rows.md.
"""
import os
import re
import json
import difflib
import unicodedata
import html as htmllib
import extract
import entrylib as L
# Principal-parts extraction. Imported at load, not inside the
# try/except below: when this module was only importable from the
# renderer's directory, the builder silently shipped dialect
# debris as τίθημι's forms bar and every gate passed.
from gen_ideal_verb import SLOT_CAPTIONS, flashcard, forms_scope

PRED = {'II': 'I', '2': '1', 'b': 'a', 'β': 'α', 'B': 'A', 'C': 'B'}

DATASET = 'grc-lsj'
ANALYSES = 'grc-analyses'
LANG = 'grc'

# Grok and Opus found the one title the print leaves unmarked: perplexio
# gives "Porc. Latro, Decl. ap. Cat. 33". No markup rule can see "Decl.".
_UNMARKED_WORK_TITLES = frozenset({('lat', 'perplexio', 'Decl.')})

# Grok and Opus agreed that in "Phld. Rh. 2.190 S." the final letter
# names the editor, not Sophocles. A one-letter author span directly
# after a closed numeric locus has the same role throughout the print.
_EDITOR = re.compile(
    r'((?:\bp{1,2}\.\s*)?\d+(?:\.\d+)?[a-z]?</span>'
    r'(?:\s*</span>)?\s*)'
    r'<span class="lx-author"([^>]*)>([A-Z]\.)</span>',
    re.I,
)


def demote_editor_sigla(raw):
    """Keep the printed siglum but stop all lx-author consumers seeing it."""
    return _EDITOR.sub(
        r'\1<span class="lx-bibl" data-editor="1"\2>\3</span>', raw
    )


def configure(dataset, analyses, lang):
    """Point the transform at a pack. One process, one language at a
    time — the builder calls this once per dataset."""
    global DATASET, ANALYSES, LANG
    DATASET, ANALYSES, LANG = dataset, analyses, lang
    _AN_BUCKETS.clear()
    _AN_LEMMAS.clear()
    _AN_SPELT.clear()
    # The two dictionaries have their own tables of authors and works, and
    # everything derived from them is per dataset. The builder builds
    # Greek and then Latin in one process, so a map left standing here is
    # the wrong dictionary's: `_WORK_OWNER` has been Greek's throughout
    # every Latin pass since it was written.
    _WORK_OWNER.clear()
    _WORK_OWNERS.clear()


def fold(q):
    return (extract.fold_greek(q) if DATASET.startswith('grc')
            else extract.fold_latin(q))


def lex_get(word):
    return extract.get(DATASET, word)

LETTER = re.compile(r'^[A-Z]$')
ROMAN = re.compile(r'^[IVX]+$')

# A gloss that stops on one of these never ended a print sentence — the
# definition continued through the Greek that split_sense moved to the
# drawer ("to be", "Sup. of", "Dim. of", "like", "causal of").
DANGLING_GLOSS = re.compile(
    r'(?:^|\s)(?:of|be|to|like|for|with|than|from|in|a|an|the|opp\.|=)$')

# The two shapes of a formula stub — a gloss that is not a meaning but a
# relation to another word, which the Greek completes. Either it ends on
# an article/copula ("fastened with a", "lie in the", "to be"), or it
# carries the print's morphological vocabulary ("Sup. of", "verb. Adj.
# of", "commoner form of", "= fem. of"). "getting rid of" and "lavish
# of" are meanings that happen to end in a preposition — neither shape.
STUB_ENDS = re.compile(r'(?:^|\s)(?:a|an|the|be|like|=)$')
# A comma-led trailing token that never ends a print sentence: a linking
# abbreviation whose target was stripped ("…, cf", "…, ap", "…, q"), a
# clipped abbreviation stem ("…, i" from i.e.), or an author initial
# ("…, S"). ONLY tokens from the print's citation apparatus — never
# English vocabulary: L&S glosses prepositions as bare comma-lists
# ("by, at, in, on") and marks gender ", m" — those words stay. The
# comma may sit inside a closing tag ("poor,</b> ap"), and stripping
# one tail can expose another, so callers go through _strip_dangling.
DANGLING_LINK = re.compile(
    r'[,;]\s*((?:</[a-z]+>)*\s*)'
    # The conjunction that joined two authors of one citation, left in
    # front of the abbreviation once both were recognised as citation
    # and taken out: ἀγγειολογέω's "Antyll. or Heliod. ap. Ath." became
    # ", or ap", γράσος's "A. or Ar. ap. Phot." the same. Optional, so
    # every tail the pattern caught before is caught still.
    r'(?:(?:and|or)\s+)?'
    r'(?:cf|ap|al|ib|id|Id|sq|sqq|etc|esp|opp|usu|freq|dub|prob|pf|'
    r'impf|sc|viz|[A-Z]|[bcdeilpqsvx])'
    r'\s*((?:</[a-z]+>)*\s*)$')
# The same tail behind the print's semicolon. Safer there than behind a
# comma, which is why the comma list had to be kept short: a gloss lists
# its synonyms with commas ("by, at, in, on"), never with semicolons.

# A connective the print wrote to introduce what comes next, left holding
# nothing once that material became an example: ἁβρός ends "dainty,
# luxurious; hence" with the ἁβρὰ παθεῖν it announced now in the drawer.
DANGLING_LEAD = re.compile(
    r';\s*((?:</[a-z]+>)*\s*)'
    r'(?:hence|so|also|thus|then|but|and|or)'
    r'\s*((?:</[a-z]+>)*\s*)$', re.I)


def clause_label(plain):
    """A division label from prose: the first complete clause, not a
    42-char slice. Cut at clause punctuation inside the cap; else at the
    last comma outside parentheses; too short means the prose has no
    usable clause (ἀνήρ "man, …") — return None and let short_label
    keep the old behaviour."""
    t = re.sub(r'\s+', ' ', plain or '').strip()
    m = re.search(r'[:;·]', t)
    if m and m.start() <= 42:
        c = t[:m.start()].strip(' ,;:')
        if len(c) >= 8:
            return c
    depth, cut = 0, -1
    for i, ch in enumerate(t[:43]):
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth = max(0, depth - 1)
        elif ch == ',' and depth == 0:
            cut = i
    if cut >= 8:
        return t[:cut].strip(' ;:')
    return None


# A locus whose author was stripped. LSJ σύγκαυσις reads "parched state
# of body, Gal. 15.895" with Gal. in a bare lx-author span — outside the
# lx-bibl the citation strip works on — so removing the citation leaves
# the volume and page sitting behind the definition. Digits and their own
# separators only, optionally behind the linking abbreviation that
# introduced them; a definition never ends on a bare number.
# The volume may be a roman numeral, and Perseus types it in Greek
# capitals as often as Latin: ἀγρολικός cites "IG ΙΙ(2).199".
DANGLING_LOCUS = re.compile(
    r',\s*((?:</[a-z]+>)*\s*)(?:(?:ap|cf|ib|v|p|pp)\.\s*)?'
    r'(?:[IVXΙΧ]{1,4}(?=\())?(?:\(\d+\)\.)?\d[\d.,\s]*\.?[A-Za-z]?\.?\s*((?:</[a-z]+>)*\s*)$')
# The reference a locus belongs to, still on the line untagged: L&S
# admissio III cites "Cod. 6, 15, 5". Stripping there takes the locus
# apart comma by comma and leaves "Cod. 6" — worse than either keeping
# it or cutting the citation whole. Only a locus whose author the
# citation strip already removed is debris (σύγκαυσις "parched state of
# body, 15.895", whose Gal. was a bare lx-author span).
LOCUS_OWNED = re.compile(r'[A-Z][A-Za-z.]*\.\s*\d[\d.]*\s*$')


def _strip_locus(s):
    m = DANGLING_LOCUS.search(s)
    if not m or LOCUS_OWNED.search(L.text_of(s[:m.start()])):
        return s
    return s[:m.start()] + m.group(1) + m.group(2)


def _strip_links(s):
    """The linking-abbreviation tail. Safe on any field the pack stores:
    no citation ends on 'cf' or 'ap'."""
    # "q. v." tells the reader to look the target up; an equation or a
    # pointer already is that link (L&S funicula "= funiculus, q. v.").
    s = re.sub(r'[,;]?\s*\bqq?\.\s*v\.?(?=(?:\s*</[a-z]+>)*\s*$)', '', s)
    for _ in range(3):
        s2 = DANGLING_LINK.sub(r'\1\2', s)
        if s2 == s:
            return s
        s = s2
    return s


def _strip_dangling(s):
    """Every tail a definition can be left holding. Definition prose
    only — the locus rule reads a trailing number as a citation whose
    author was stripped, and a citation's own book and chapter are
    exactly that shape: run it over ex.c and "Cic. Verr. 2, 4, 33" comes
    back "Cic. Verr. 2"."""
    for _ in range(5):
        s2 = DANGLING_LEAD.sub(r'\1\2', _strip_locus(_strip_links(s)))
        if s2 == s:
            break
        s = s2
    return _strip_part_letter(s)


# The part letter of a citation, left behind because a cue tag stood
# between the comma and it: ἀνασάξιμον cites IG 2.780, 1078b and ships
# "opened and worked, after having been closed, b"; ψυχαγωγή ends
# "oblectamentum, b" off Cod.Just. 8.10.12.6b. Also Ἀθῆναι "to Athens,
# a", ἄρκτος "the south pole, a", ἀρχοντικός "ex-archon, a".
#
# GREEK ONLY, and that is the whole care of it. Lewis & Short ends a
# sub-lemma gloss on exactly this shape and means it — "advŏcātus, i, m",
# "aerārĭa, ae, f", "Armĕnĭum, ii, n" are the genitive and the gender,
# and 132 of the 142 Latin rows matching this pattern are that. A rule
# written from the Greek evidence alone would have deleted every one.
# Matched against the markup, not the text: the cue tag between the
# comma and the letter is the whole reason the letter survived the
# citation strip, so a pattern reading only the stripped text finds the
# case and then fails to remove it.
#
# The closing tags after the letter are LOOKED AT, never consumed. A
# first version swallowed them, and where the letter sat inside a cue
# span that opened earlier — "<b class="cue">…, b</b>" — taking the
# </b> left the span open and the audit found 62 unbalanced entries.
# The opener is upstream of the match and cannot be removed with it, so
# the closer has to stay.
_PART_LETTER = re.compile(
    r',\s*[a-z]\s*(?:\(\s*[,;·]*\s*\)\s*)?(?=(?:\s*</[^>]+>)*\s*$)')
# The other shape: the letter carries its own cue span, opened and closed
# inside the match. Balanced by construction — the wrapper's opening tag
# is part of what is removed — so this one may take its tags with it.
_PART_LETTER_TAGGED = re.compile(
    r',\s*<([a-z]+)\b[^>]*>\s*[a-z]\s*</\1>\s*(?=(?:\s*</[^>]+>)*\s*$)')


_TOKEN = re.compile(r'<[^>]+>|[^<]+')


def _strip_part_letter(s):
    """Drop a citation's orphaned part letter from the end of a gloss.

    Works on TEXT NODES only, never on tags, so the markup cannot come
    out unbalanced — which is what a regex got wrong here twice: the
    first version ate the closing tags and left cue spans open, and the
    audit went from 0 hard defects to 62.

    The common shape puts the comma inside the cue and the letter
    outside it — "<b class="cue">the south pole,</b> a" — so both ends
    of the edit are in different text nodes and neither is adjacent to
    the other in the string. Hence a walker rather than a pattern.
    """
    if DATASET.startswith('lat') or '<' not in s:
        return _PART_LETTER.sub('', s)
    toks = _TOKEN.findall(s)
    text = [i for i, t in enumerate(toks)
            if not t.startswith('<') and t.strip()]
    if not text:
        return s
    last = text[-1]
    # The shell of a citation whose contents were stripped can trail the
    # letter — ἀρχοντικός's zone is "…ex-archon,</b> a ()" at this point,
    # and _polish_emitted does not clear that paren until later. Look
    # past it rather than depend on the order of two passes.
    bare = re.sub(r'\(\s*[,;·]*\s*\)', '', toks[last])
    if re.fullmatch(r'\s*[a-z]\s*', bare):
        toks[last] = bare
        if len(text) < 2:
            return s
        prev = text[-2]
        if not re.search(r',\s*$', toks[prev]):
            return s
        toks[last] = ''
        toks[prev] = re.sub(r',\s*$', '', toks[prev])
    elif _PART_LETTER.search(toks[last]) and last == text[-1]:
        toks[last] = _PART_LETTER.sub('', toks[last])
    else:
        return s
    # An element left holding nothing is dropped whole, open and close
    # together, so the pair stays balanced.
    out = []
    for i, t in enumerate(toks):
        if (t.startswith('<') and not t.startswith('</')
                and i + 2 < len(toks) and toks[i + 1] == ''
                and toks[i + 2].startswith('</')):
            toks[i + 1] = toks[i + 2] = ''
            continue
        out.append(t)
    return ''.join(out).rstrip()

STUB_FORMULA = re.compile(
    r'\b(?:Sup|Dim|Comp|fem|masc|neut|Adj|Adv|Subst|verb|form|forms|'
    r'causal|collat|deriv|contr|lengthd|strengthd|shortened|abbrev|'
    r'commoner|older|earlier|later|poet|Pass|Med|Act)\b')


def show_n(n):
    """Print's period on roman and lettered addresses: II. A."""
    n = n or ''
    if ROMAN.match(n) or re.fullmatch(r'[A-Z]', n):
        return n + '.'
    return n


def polish_label(lab):
    """Shouty band names → one casing. WITH Acc vs WITH GEN is the print."""
    t = (lab or '').strip()
    m = re.fullmatch(r'WITH\s+(\w+)\.?', t, re.I)
    if m:
        return 'With ' + m.group(1).lower() + '.'
    m = re.fullmatch(r'With\s+(\w+)\.?', t, re.I)
    if m:
        return 'With ' + m.group(1).lower() + '.'
    m = re.fullmatch(r'(POSITION|ABS|Lit|Trop|Transf|Esp)\.?', t, re.I)
    if m:
        word = m.group(1)
        return word[:1].upper() + word[1:].lower() + ('.' if word.lower() != 'position' else '')
    m = re.fullmatch(r'In (gen|partic|space|time|composition)\.?', t, re.I)
    if m:
        tail = m.group(1).lower()
        extra = '.' if tail in ('gen', 'partic') else ''
        return 'In ' + tail + extra
    if re.fullmatch(r'IN COMPOS(?:ITION)?\.?', t, re.I):
        return 'In composition'
    if re.fullmatch(r'PROSODY\.?', t, re.I):
        return 'Prosody'
    return t
BANNER_ZONE = re.compile(
    r'^(WITH\s+\w+|POSITION|ABS\.?|Special phrases|PROSODY|'
    r'IN COMPOS(?:ITION)?\.?|'
    r'of (?:Place|Time|Number)|In space|In time|'
    r'Lit\.?|Trop\.?|Transf\.?|In gen\.?|Esp\.?|In partic\.?|'
    r'With \w+|Attributively|In composition)s?\b',
    re.I)
# _TITLED_LOCUS is defined after STRIP_WORK; the two share one locus grammar.
# A title's locus may open on a roman volume, and Perseus types it in
# Greek capitals as often as Latin: ἀγρολικός cites "IG ΙΙ(2).199".
# An inscription's locus: "IG 12(9).234.34", "4(2)(1).103.163", "9(I).694.8",
# "SIG 244i39", "12(3).537a". The volume may be bracketed more than once
# and typed as a roman numeral.
# The print spaces the bracketed volume off from the title as often as it
# closes it up, and puts the stop either side of the bracket: ἀδελφός
# cites "IG 12 (9).906.19" and ἐκέχειρον "IG 12 (5). 1341.53". The bridge
# is allowed only around a bracket, so a locus can never run across a
# full stop that ends a sentence to reach the next number.
# A periodical whose volume runs over two years is cited with a slash:
# "Annuario 4/5.225", "Clara Rhodos 6/7.386", "Arch.Anz. 38/39.154".
_VOL = r'(?:\s*\([\dIVXΙΧ]+\)\s*\.?\s*)'
_LOCUS = (r'(?:[IVXΙΧ]{1,4}(?=\s*\())?[\d.]*(?:/\d+)?' + _VOL
          + r'*[\d.]*\d(?:[a-z](?![A-Za-z.])\d*)?')
# The print's short aside after a locus: "(pl.)", "(Corc.)", "(bis)".
# This is the bare kind, and it is the only kind allowed to END a run of
# loci, because an aside at the end takes the print's own separator with
# it: θηροκτόνος reads "epith. of Heracles, IG 5(2).91 (Tegea); of
# Artemis", and eating the shell of that bracket turned the semicolon
# into a comma.
_LOCUS_ASIDE = r'(?:\s*\((?:pl|sg|bis|ibid|[A-Z][a-z]{1,8})\.?\))?'
# Between two loci the aside may be one Perseus marked: αἱμάτιον hangs
# "SIG 1002.11 (Milet.), 1025.53" and ἔξοδος "IG 14.422 (Tauromenium),
# 5(1).1390.50" on one title, and the run stopped at the marked place.
# _strip_citations has already dropped lx-placeName and lx-date on most
# of the paths that reach here, leaving the print's bracket standing
# empty, so the shell counts as the aside too; the span itself is read on
# the paths that still hold it (_note_text). Only between loci: the
# repetition it sits in has to reach a further locus or nothing is eaten.
# The contents are a closed vocabulary of apparatus, not a bounded run of
# any characters: an aside that names a reading rather than a place is
# evidence, and ἴκρια's "(prob. in IG 1(2).374.151)" holds a whole
# citation. Read here: the marked span; a century ("V B.C.", "ii A.D.");
# the print's short words; and a place, which may be two words
# ("Nemrud Dagh", "Orchom. Boeot.").
_ASIDE_PART = (r'(?:<span class="lx-(?:placeName|date)">[^<]*</span>'
               r'|[ivxIVX]{1,4}\s*[AB]\.\s*[CD]\.'
               r'|(?:pl|sg|bis|ibid)\.?'
               r'|[A-Z][a-z]{1,12}\.?(?:\s+[A-Z][a-z]{1,12}\.?)?)')
_ASIDE_BETWEEN = (r'(?:\s*\(\s*(?:' + _ASIDE_PART
                  + r'(?:\s*,?\s*' + _ASIDE_PART + r')*)?[\s,;]*\))?')
# A further locus the print introduces with "cf.": ἀκινάκης "IG 1.170.17,
# cf. 2.646.11". Only where a locus follows, never a bare number, so a
# cross-reference to a sense ("cf. 2") is left where it stands.
_LOCUS_CF = r'(?:cf\.\s*(?=\d+\s*[.(]))?'
# The further loci of the same work after the print's comma: "IG
# 2(2).1035.56 (pl.), 12(9).234.34" left ", 12(9).234.34" in 289
# glosses once the title and its first locus were out. One grammar for
# all of them: a plain continuation ("SIG 254A 11,257.10") is a locus
# like any other, and reading it with a separate, simpler pattern took
# "11" and left "(2).145.48" behind on κυμβίον. The print's space before
# the comma is its own (a stripped placeName leaves one: ἐπικριτήριον
# "GDI 5040.67 , 5024.52").
# The print's "al." carries an aside of its own before the comma:
# γυμνασιαρχέω reads "IG 3.1104, al., 5(1).481, al. (Sparta), 7.1669"
# and κλᾴξ "42(1).102.110, al. (Epid., iv B.C.), 5(1).1390.92".
_LOCUS_MORE = (r'(?:' + _ASIDE_BETWEEN + r'\s*,\s*(?:al\.' + _ASIDE_BETWEEN
               + r'\s*,\s*)?' + _LOCUS_CF + _LOCUS + r')*')
STRIP_WORK = re.compile(
    r'<i class="lx-title">.*?</i>'
    r'(?:\s*' + _LOCUS +
    # a page reference and an editor's siglum after the locus ("Ep.
    # 1p.10U."), and the part letter ("526a") — not the "p" of "p.10"
    r'(?:\s*p\.\s*[\d.]+)?(?:\s*[A-Z]\.(?![A-Za-z]))?(?:[a-z](?![A-Za-z.]))?'
    + _LOCUS_MORE + _LOCUS_ASIDE + r')?'
    # "ib." carries the same run of loci a title does, and read with a
    # looser digits-and-stops pattern it stopped at the first bracket:
    # ἀμαυρόω's "ib. 12(9).1129.22" left "(9).1129.22" on the line. The
    # trailing separator the old pattern ate is still eaten.
    r'|(?<![A-Za-z])ib\.(?:\s*' + _LOCUS + _LOCUS_MORE + _LOCUS_ASIDE + r')?'
    # the trailing stop or separator the old digits-and-stops pattern ate,
    # kept so this round changes only what the brackets changed
    r'(?:\s*[.,;]+)?',
    re.S)
# The identity line's version: a title with at least one locus, read
# with the same grammar so the line and the forms bar agree on what a
# citation is (ἐγγραφή "Dor. ἐγγροφά IG 4.1485.126 (Epid.)").
_TITLED_LOCUS = re.compile(
    r'<i class="lx-title">[^<]*</i>\s*' + _LOCUS
    + _LOCUS_MORE + _LOCUS_ASIDE, re.S)


def sense_numbers(ss):
    """Fill a blank first numeral from the next sibling; never concatenate
    parent and child (CGL shows one address per line).

    The sibling is looked for where the print would have put it: at this
    row's own level, or one below it, which is where Perseus parks a
    division run it has demoted. Anything deeper is this row's own
    descendant, and reading one as the sibling is what stranded χείρ —
    its "2. hand and arm" sits two levels down, so the scan supplied "1."
    where the print means "I." and left the entry's own II, III, IV
    nested underneath that supplied 1 instead of beside it. 408 entries
    shipped that shape, and ~4,900 more shipped the wrong numeral alone,
    the nesting hidden by the flatten pass (ἄβιος printed "1. 2. II. III."
    for the print's "I. 2. II. III.").

    Preference, not a bound: when neither level holds a numeral the scan
    falls back to the original any-depth search, which is right when the
    print's series is demoted further still. Narrowing it to a bound cost
    5,292 Greek entries the numeral they correctly had.

    A same-level sibling is the strongest evidence there is, so it wins
    even against a nearer roman one level down: αἰσχύνω is "A. make ugly
    … B. Pass." and its first division is A, not 1."""
    out = []
    for i, (lvl, body) in enumerate(ss):
        n = L.sense_number(body).strip()
        supplied = False
        if not n:
            cand = None
            for j in range(i + 1, len(ss)):
                if ss[j][0] < lvl:
                    break
                if ss[j][0] > lvl + 1:
                    continue
                nj = L.sense_number(ss[j][1]).strip()
                if nj:
                    cand = nj
                    break
            # A candidate the predecessor table cannot step back is no
            # candidate at all: it names no numeral we could supply, so it
            # must not consume the search and suppress the fallback. L&S
            # dapsilis opens unnumbered, keeps its "β. With abl." five
            # levels down, and puts "A. Form dapsĭlĭter" at lvl+1 — pass 1
            # stopped on that A, which has no predecessor, and the entry
            # lost the "α." the old any-depth scan gave it.
            if cand is None or cand.rstrip('.') not in PRED:
                for j in range(i + 1, len(ss)):
                    if ss[j][0] < lvl:
                        break
                    nj = L.sense_number(ss[j][1]).strip()
                    if nj:
                        cand = nj
                        break
            if cand is not None:
                key = cand.rstrip('.')
                if key in PRED and _opens_series(out, ss, i, lvl, PRED[key]):
                    n, supplied = PRED[key] + '.', True
        out.append((lvl, n, body, supplied))
    return out


def _series(n):
    """Which of the print's numbering series an address belongs to.

    I, V and X are roman here, never letters — the same call
    `is_letter_addr` makes."""
    n = (n or '').rstrip('.')
    if not n:
        return ''
    if ROMAN.match(n):
        return 'roman'
    if n.isdigit():
        return 'arabic'
    if is_letter_addr(n):
        return 'letter'
    return 'other'


def _opens_series(out, ss, i, lvl, want):
    """True when this blank row really is the first of its series.

    A supplied numeral is only ever the FIRST member of a run — it is
    read off the successor and handed back one place. Handing it to
    every unnumbered row at that level numbers them all the same:
    δύσκολος writes "I. of persons … [NB …] … but, generally, hard to
    please … II. of things", and the two unnumbered paragraphs are
    continuations of I, not fresh senses, so the entry shipped three
    rows numbered I.

    The test is per series, not per level. ἀραρίσκω opens "A. trans.:—"
    and then an unnumbered "join together" whose print address is I: the
    letter band before it belongs to another series and must not stop the
    roman one from starting.

    It reads the address each earlier row ENDED UP with, from `out`, not
    the one the print gave it. A numeral we supplied occupies the series
    just as firmly as a printed one, and consulting the source alone let
    a run of unnumbered siblings each claim the same address: ἄρνειος has
    two unnumbered senses before its II. and shipped "I." twice,
    Ἐρεχθεύς four and shipped it four times. δύσκολος only came out right
    because a printed "I." happened to stand in front of its blanks."""
    for j in range(i - 1, -1, -1):
        if ss[j][0] < lvl:
            return True
        if ss[j][0] > lvl:
            continue
        nj = out[j][1]
        if not nj:
            continue
        # A letter band at this level CLOSES the series that ran inside
        # it. The print restarts its numbering under every band, so a
        # roman already spent in band A says nothing about band B.
        # ἀραρίσκω again: A. runs I-IV and B. runs I-V, and because
        # Perseus parks both bands and both of their first senses at the
        # same level, the scan below walked out of B, back into A, found
        # the I. supplied there and left B's own first division blank
        # beside its II, III, IV, V. One entry in 168,389 has the shape,
        # and it is the entry that already taught this function a letter
        # band must not STOP a roman series from starting.
        #
        # LSJ-shaped, and inert on Lewis & Short: L&S inverts the
        # hierarchy, parenting its letters under romans (sum, ago, habeo
        # put A. and B. beneath I. and II.), so the shape never arises
        # there. Measured: 0 Latin entries change.
        if is_letter_addr(nj.rstrip('.')) and _series(want) != 'letter':
            return True
        if _series(nj) == _series(want):
            return False
    return True
# titles inside bibl already stripped by the span above; leftover i.titles
# in the zone stay if they are part of the definition (rare).


def lift_demoted_siblings(ss):
    """Perseus parks an entry's implicit first sense unnumbered at the
    base level with its print-siblings II, III… one level down (οὐσία,
    ἀνήρ, ἁφή) — that is where the supplied 'I' above came from. In
    print they are one flat series, so lift the run back up, children
    riding along. A genuine base-level address ends the run (ἀναβαίνω
    keeps its B division and everything under it untouched).

    Returns (items, lifted): the indexes of moved items. A lifted row
    is a print SENSE that the move may leave at the top with children —
    the roman section-head rule must not eat it (the band path blanks
    the zone to a 42-char label and drops the examples: ἀκμή II lost
    'prime, zenith, esp. of man's age' before this was passed through).
    """
    if len(ss) < 2:
        return ss, frozenset()
    l0, n0, _, sup0 = ss[0]
    if not (sup0 and n0.rstrip('.') == 'I'):
        return ss, frozenset()
    # The demoted run is found by level, not by being the very next row.
    # Requiring ss[1] to be the "II" held for οὐσία, whose first sense has
    # no children, and declined for χείρ, whose ss[1] is that sense's own
    # "2. hand and arm" and whose II sits further down the list. What
    # identifies the run is that the shallowest thing under this sense is
    # exactly one level down and is numbered II — the print's second
    # division wearing the indent Perseus gave it.
    #
    # II specifically, and the numeral is the whole test. An unnumbered
    # sense followed one level down by "I." is not a demoted series at
    # all: it is a headword PREAMBLE, the general meaning the print states
    # before it subdivides, and the romans under it are its genuine
    # subdivisions, correctly nested already — ἁγνός opens "pure, chaste,
    # holy" and then divides I., II., III. Lifting those flattens a
    # correct entry into a wrong one. Followed by "II.", the same shape is
    # division I with its siblings demoted. Measured on the philosophy
    # readers' shards, which hit this from their own direction: 8,091
    # demoted series against 209 preambles, 97.5% to 2.5%.
    stop = next((j for j in range(1, len(ss)) if ss[j][0] <= l0), len(ss))
    run = range(1, stop)
    if not len(run) or min(ss[j][0] for j in run) != l0 + 1:
        return ss, frozenset()
    first = next(j for j in run if ss[j][0] == l0 + 1)
    if ss[first][1].rstrip('.') != 'II':
        return ss, frozenset()
    out = [ss[0]]
    for j in run:
        lvl, n, body, sup = ss[j]
        out.append((lvl - 1, n, body, sup))
    out.extend(ss[stop:])
    return out, frozenset(run)


def demote_band_first_sense(ss):
    """The other half of the demoted-division problem, under a band.

    Perseus parks a division run one level below where the print means
    it. Where that happens at the top of an entry, the fix is to lift the
    run — see lift_demoted_siblings. Where a letter band stands over it,
    the fix is the opposite move: the band's own unnumbered first sense
    is left at the BAND's level, beside it rather than under it, while
    its roman siblings sit correctly one level down.

    ἀραρίσκω prints "A. trans.:— join together, fasten … II. fit
    together … III. fit, equip … IV. make fitting … B. intr.:— to be
    joined closely together … II. fit well". Perseus gives A and the
    unnumbered "join together" the same level, so "join together" reads
    as a second band rather than as division I inside A, and II-IV nest
    under it. Demote it to join its siblings instead of lifting them,
    which would put the whole roman series beside the band it belongs to.

    Same guard as the lift, for the same reason: the run must start at
    "II." A run starting at "I." means the unnumbered sense is a preamble
    and the romans below it are already right.
    """
    out = list(ss)
    for i in range(1, len(out)):
        lvl, n, body, sup = out[i]
        if not sup:
            continue
        prev = None
        for j in range(i - 1, -1, -1):
            if out[j][0] < lvl:
                break
            if out[j][0] == lvl:
                prev = out[j]
                break
        if prev is None or not is_letter_addr((prev[1] or '').rstrip('.')):
            continue
        stop = next((j for j in range(i + 1, len(out)) if out[j][0] <= lvl),
                    len(out))
        run = range(i + 1, stop)
        if not len(run) or min(out[j][0] for j in run) != lvl + 1:
            continue
        first = next(j for j in run if out[j][0] == lvl + 1)
        if (out[first][1] or '').rstrip('.') != 'II':
            continue
        out[i] = (lvl + 1, n, body, sup)
    return out


def demote_roman_first_subsense(ss):
    """A sub-sense the print numbered "1." that reaches us as roman "I."

    Perseus parks a division's first sub-sense at the DIVISION's level
    rather than under it — the same demotion lift_demoted_siblings and
    demote_band_first_sense handle — and where that sub-sense is the
    first of an arabic run, its "1." also arrives as a capital I. The two
    are one glyph apart in the printed face and this is an OCR read, not
    something Liddell and Scott wrote.

    σπουδάζω proves it inside a single entry: its "II. trans." division
    has children 1., 2., and its "I. intr." division has children I., 2.,
    3., 4. Same position, same entry, two different glyphs for it.
    ἐπιτυγχάνω's II. reads I., 2., 3., 4. while its III. opens unnumbered;
    L&S exspiro's A. has 1., 2. against B.'s I., 2.

    Three conditions, all required, because "I." followed by "2." is
    ORDINARY LSJ everywhere else — φρήν is "I. midriff … 2. heart …
    3. mind … 4. will", a division with sub-senses, and renumbering that
    would be vandalism. What marks the artifact is that the roman series
    at this level is already open (a roman sibling stands before it, so
    this cannot be another division of the same series), and that the run
    beneath it opens on the print's own "2." The row then takes the level
    that run sits at, joining the siblings it belongs to.
    """
    out = list(ss)
    for i in range(1, len(out)):
        lvl, n, body, sup = out[i]
        if sup or (n or '').rstrip('.') != 'I':
            continue
        prev = None
        for j in range(i - 1, -1, -1):
            if out[j][0] < lvl:
                break
            if out[j][0] == lvl:
                prev = (out[j][1] or '').rstrip('.')
                break
        if not prev or not ROMAN.match(prev):
            continue
        stop = next((j for j in range(i + 1, len(out)) if out[j][0] <= lvl),
                    len(out))
        run = range(i + 1, stop)
        if not len(run):
            continue
        deep = min(out[j][0] for j in run)
        first = next(j for j in run if out[j][0] == deep)
        if (out[first][1] or '').rstrip('.') != '2':
            continue
        out[i] = (deep, '1.', body, sup)
    return out


_ABBREVS = {}
# "Id." and "ib." both send the reader back to the last author named.
_SAME_OR_IB = re.compile(r'^(?:id|ib|ibid)\.?$', re.I)


def abbrevs():
    """The print's own table of authors and works (scripts/wordtool/data),
    keyed by the pack's language. Works are nested under their author."""
    name = 'ls-abbrevs.json' if DATASET.startswith('lat') else 'lsj-abbrevs.json'
    if name not in _ABBREVS:
        # Through the repo root, not __file__: sample_diff runs HEAD's copy
        # of this module from a temporary directory.
        path = os.path.join(extract._REPO, 'scripts', 'wordtool', 'data', name)
        try:
            with open(path, encoding='utf-8') as fh:
                _ABBREVS[name] = json.load(fh)
        except OSError:
            _ABBREVS[name] = {}
    return _ABBREVS[name]


_ID_VETO = None


def id_veto():
    """A closed, by-name table: (the author "id." would otherwise inherit,
    the work the print names) -> the author the print actually means.

    L&S's "id." means the last author named, but an interposed parallel
    citation, or a mention the markup left in plain text, can put the
    wrong name in that seat (pungo: "Cic. Phil. 8, 7, 20; Ter. Phorm.
    185: ... id. N. D. 1, 20, 52" makes "id." read Ter., though N. D. is
    Cicero's). A rule keyed on the work alone would also misfire — Tert.
    writes his own Or., Col. writes his own R. R. — so the veto is keyed
    on the pair the transform is about to compose. Latin only. Loaded
    through the same path abbrevs() uses (data/, not __file__), so
    sample_diff's temp-directory copy of this module still finds it."""
    global _ID_VETO
    if _ID_VETO is None:
        path = os.path.join(extract._REPO, 'scripts', 'wordtool', 'data', 'ls-id-veto.json')
        try:
            with open(path, encoding='utf-8') as fh:
                rows = json.load(fh)
        except OSError:
            rows = []
        _ID_VETO = {(prev, work): author for prev, work, author in rows}
    return _ID_VETO


def _id_work(bibl_html, auth_end):
    """The work "id." names in bibl_html, read WHOLE: everything from the
    end of the id. author span to the first token that carries a digit,
    whether or not it sits in an <i class="lx-title"> span, whitespace
    collapsed. Never cut at a period — "Sen. Vit. Beat." is one work, not
    "Vit." Runs of a stray extra period fold to one; an "id." with no
    work before its locus (id. p. 30, id. ib. 4, 7, 77, id. 3, 6) yields
    an empty string, which matches no veto entry."""
    tail = bibl_html[auth_end:]
    m = re.match(r'\s*</span>', tail)
    if m:
        tail = tail[m.end():]
    text = re.sub(r'\s+', ' ', L.text_of(tail)).strip()
    toks = []
    for tok in text.split(' '):
        if re.search(r'\d', tok):
            break
        toks.append(tok)
    work = ' '.join(toks).strip()
    return re.sub(r'\.{2,}$', '.', work)


def _work_of(author, title):
    """True when the table lists `title` among `author`'s works."""
    works = abbrevs().get('works', {}).get(author) or {}
    return title in works or title.rstrip('.') in works or title.rstrip('.') + '.' in works


# "Od." is the Odyssey and also Theophrastus' De Odoribus, whose loci
# are a plain section number where Homer's are book.line. 36 bare "Od.
# 17.347" citations became Theophrastus chips because a Theophrastus
# citation stood before them.
_HOMERIC_TITLE = {'Il.', 'Od.'}


def _homeric(title, chunk):
    """A dotted locus under Il. or Od. is Homer's, whoever was named
    last. Homer himself keeps the attribution, so "Hom. Il. 1.1" still
    chips as Hom.; it is Theophrastus, whose De Odoribus the table also
    abbreviates Od., who does not."""
    if title.strip() not in _HOMERIC_TITLE:
        return False
    return bool(re.search(r'\d+\s*\.\s*\d', L.text_of(chunk)))


def author_of_work(title):
    """The one author the table gives this work to, or ''.

    A run of bare titles keeps the author the print last named, and can
    restore one an unrelated mention has displaced: ἐπάγω cites "APo.
    81b5" and then "Id. Rh. 1356b8", and the Id. is Aristotle however
    many other authors the entry has named in between. Only where the
    table gives the work to exactly one author; a shared abbreviation
    says nothing."""
    if not _WORK_OWNER:
        owners = {}
        for author, works in (abbrevs().get('works') or {}).items():
            for work in works or ():
                owners.setdefault(work.rstrip('.'), set()).add(author)
        _WORK_OWNER.update({w: next(iter(a)) for w, a in owners.items() if len(a) == 1})
        _WORK_OWNER.setdefault('', '')
    return _WORK_OWNER.get((title or '').strip().rstrip('.'), '')


def last_author(html):
    """The last author the print names in this stretch, prose mentions
    included, and never "Id." — the antecedent the next "Id." means.

    An editor credited with a conjecture is not the antecedent: ἀνάριθμος
    reads "μηνῶν ἀ. (Herm. for μήλων)" and then cites Sophocles twice as
    "Id.", which shipped as "Herm. Tr. 247"."""
    last = ''
    for m in re.finditer(r'class="lx-author[^"]*"[^>]*>([^<]+)</span>', html):
        tok = m.group(1).strip()
        if not tok or SAME_AUTH.match(tok.rstrip('.')):
            continue
        after = L.text_of(html[m.end():m.end() + 24]).lstrip()
        if re.match(r'(?:for|cj\.|conj\.)\b', after):
            continue
        last = tok
    return last


def unique_authors(ev, prev=''):
    """The chips: each author the evidence cites, once, in print order.

    "Id." is not an author. The print writes it for the last author it
    named, in the sentence before or in the row above, and 14,399 Greek
    and 25,528 Latin chips shipped it unresolved. A citation that names
    only a work — "R. 509b" after "Pl. Phd. 65a" — means that author's
    work by the same convention, so the chip is the author when the
    table lists the work under him; a work with no author (AP, h.Merc.,
    Ev.Matt.) stays the chip it was. `prev` is the antecedent named
    before this evidence began."""
    tokens, seen = [], set()
    last = prev
    # Citations and the prose mentions between them, in print order: a
    # prose "Cicero" is the antecedent of the "id." after it.
    bibls = [(m.start(), chunk) for m, chunk in zip(
        re.finditer(r'<span class="lx-bibl"', ev), each_span(ev, 'lx-bibl'))]
    prose = [(m.start(), m.group(1).strip()) for m in re.finditer(
        r'<span class="lx-author lx-prose"[^>]*>([^<]+)', ev)]
    for pos, chunk in sorted(bibls + prose, key=lambda x: x[0]):
        if isinstance(chunk, str) and not chunk.startswith('<'):
            if chunk and not _SAME_OR_IB.match(chunk.rstrip('.')):
                last = chunk
            continue
        # Every author the citation names — "A. or Ar. ap. Phot." names
        # three — and its title only when it names none.
        auths = [x.strip() for x in re.findall(r'class="lx-author"[^>]*>([^<]+)', chunk)]
        if not auths:
            t = re.search(r'class="lx-title"[^>]*>([^<]+)', chunk)
            title = t.group(1).strip() if t else ''
            if title and last and _work_of(last, title) and not (
                    last != 'Hom.' and _homeric(title, chunk)):
                auths = [last]
            elif title:
                auths = [title]
        for tok in auths:
            if not tok:
                continue
            if _SAME_OR_IB.match(tok.rstrip('.')):
                if not last:
                    continue
                tok = last
            else:
                last = tok
            if tok not in seen:
                seen.add(tok)
                tokens.append(tok)
    tokens = drop_work_chips(tokens)
    # A table-work-only token is a title only when the print says so and
    # never also calls it an author. Thus ἀρκεσίβουλος loses "Fr.", while
    # the author-marked counter-cases the two readers found stay.
    remove = _print_work_titles(ev)
    tokens = [tok for tok in tokens if tok not in remove]
    if len(tokens) > 6:
        return tokens[:6] + ['+']
    return tokens


GREEK_SPAN = re.compile(
    r'<span class="lx-(?:foreign|quote)"[^>]*>.*?</span>', re.S)
RUBRIC_LEAD = re.compile(
    r'^(of |in |folld\.|c\. |abs\.|freq\.|with |in Poets|generally)\b', re.I)
CF_OPEN = re.compile(r'\(\s*cf\.', re.I)


def strip_crossrefs(html):
    """Drop LSJ '(cf. λέγω (B) II)' / '(v. infr. b)' notes, nested parens
    included. If we don't, split_sense treats the Greek inside as an
    illustration and the English is left with a dangling '(cf.'"""
    out, i = [], 0
    while True:
        m = CF_OPEN.search(html, i)
        if not m:
            out.append(html[i:])
            break
        last_lt, last_gt = html.rfind('<', 0, m.start()), html.rfind('>', 0, m.start())
        if last_lt > last_gt:
            out.append(html[i:m.end()])
            i = m.end()
            continue
        depth, j = 0, m.start()
        while j < len(html):
            ch = html[j]
            if ch == '<':
                gt = html.find('>', j)
                j = len(html) if gt < 0 else gt + 1
                continue
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
                if depth == 0:
                    j += 1
                    break
            j += 1
        out.append(html[i:m.start()])
        i = j
    return re.sub(r'\s+,', ',', ''.join(out))


def _drop_unmatched_parens(html, pair='()'):
    """Remove mateless parentheses, without touching tags — but only when
    what follows is short debris. An unmatched open paren with a real
    aside behind it stays: deleting it would merge the aside into the
    definition prose ("grease (syn" is honest; "grease syn" is not).

    The same for LSJ's square brackets when asked (pair='[]'): the
    print supplies a word in them — "ἀβίωτόν [ἐστι] life is
    intolerable" — and when the Greek goes to the drawer the bracket
    stays on the row, opening it ("] life is intolerable", 124 rows) or
    ending it ("to be swollen, [", 746 rows)."""
    lparen, rparen = pair
    opens, remove = [], set()
    in_tag = False
    for i, ch in enumerate(html):
        if ch == '<':
            in_tag = True
        if not in_tag:
            if ch == lparen:
                opens.append(i)
            elif ch == rparen:
                if opens:
                    opens.pop()
                else:
                    remove.add(i)
        if ch == '>':
            in_tag = False
    for i in opens:
        tail = re.sub(r'<[^>]*>', '', html[i + 1:])
        if len(re.findall(r'[^\W\d_]+', tail)) <= 2:
            # A truncated aside: cut its visible remnant ("(syn"), but
            # keep every tag so the markup stays balanced.
            in_t = False
            for j in range(i, len(html)):
                if html[j] == '<':
                    in_t = True
                if not in_t:
                    remove.add(j)
                if html[j] == '>':
                    in_t = False
    return ''.join(ch for i, ch in enumerate(html) if i not in remove)


def _tidy(html):
    """Collapse whitespace and trailing punctuation. Do not strip tags:
    a sense that is only a gloss ends in </b>, and removing it leaves
    <b class="cue"> open so every later line inherits the bold and the
    grid collapses."""
    html = re.sub(r'\s+', ' ', html)
    html = re.sub(r',\s*;', ',', html)
    html = re.sub(r',\s*,+', ',', html)
    html = re.sub(r'\s+\.', '.', html)
    # Trailing separators go; the sentence's own period goes; the
    # period of an abbreviation stays. βασιλεύς 2 ends "usually with
    # Art., IG 2(2).641" and once the reference is out the last mark
    # is the one that makes "Art." an abbreviation.
    # Only a capitalised one: a lowercase link ("cf.", "al.", "etc.")
    # loses its period here so that DANGLING_LINK, which runs after,
    # sees the bare token it was written for.
    # Looped: a stripped period can uncover a separator (Ποντάρχης's
    # "Pontus, al., ." once its references are out) and the other way.
    # In Latin a single lowercase letter keeps its period: L&S "ae, f."
    # is the gender, and without the period the Latin part-letter rule
    # reads ", f" as citation debris and deletes it. In Greek the same
    # shape is a citation's part letter (ψυχαγωγή "oblectamentum, b")
    # and the walker wants it bare. A single capital is an author's
    # initial ("unmoved, S.") and DANGLING_LINK wants it bare, as it
    # wants every link ("Id.", "cf.", "sc.").
    # A Greek token of one or two letters before it is LSJ's own
    # abbreviation of the headword in a quotation ("τί ν." for νέον).
    while True:
        before = html
        html = re.sub(r'[ ,;:]+(?=(?:</\w+>\s*)*$)', '', html)
        # The sentence's period behind an abbreviation's: "by Suid.."
        # once the citation between them is out.
        html = re.sub(r'\.{2,}(?=(?:</\w+>\s*)*$)', '.', html)
        # A capitalised token of any length: the author abbreviations
        # the governed-citation rule leaves at the end ("scourge in
        # Hippon.", "first in Arist.") outnumber sentences the print
        # ends on a proper noun inside a gloss.
        m = re.search(r'(?<![A-Za-zͰ-Ͽἀ-῿])([A-Za-z]{1,10}|[Ͱ-Ͽἀ-῿]{1,2})\.'
                      r'(?:</\w+>\s*)*$', html)
        # Keep an author's period when the sentence itself governs the
        # name; citation cleanup has removed the rest of the reference.
        governed_author = re.search(
            r'\b(?:in|by|from|after|before|among|as|to|than|of|acc\.\s+to)\s+'
            r'[A-Z](?:[A-Za-z]{1,9}|(?:\.[A-Z])+)?\.(?:</\w+>\s*)*$', html)
        keep = m and m.group(1).lower() not in _LINK_TAIL and (
            m.group(1).islower() and len(m.group(1)) == 1 and DATASET.startswith('lat')
            or m.group(1)[0].isupper() and len(m.group(1)) > 1
            or m.group(1) in _GRAM_TAIL
            or not re.match(r'[A-Za-z]', m.group(1)))
        # Still strip _LINK_TAIL after a preposition ("in Id."), as the keep
        # rule already does. DANGLING_LINK cannot match here (it wants [,;]).
        keep = keep or (bool(governed_author) and not (
            m and m.group(1).lower() in _LINK_TAIL))
        if not keep:
            html = re.sub(r'\.+(?=(?:</\w+>\s*)*$)', '', html)
        if html == before:
            break
    return _drop_unmatched_parens(html).strip()


# Grammar abbreviations keep their period at the end of a gloss ("sts.
# with a part."); links do not, so DANGLING_LINK can see them.
_GRAM_TAIL = frozenset(
    'part pl sg dat gen acc nom voc inf opt subj imper impf aor fut pf plpf '
    'pres adj adv subst neut masc fem dual intr trans abs med pass act '
    'sc lyr perf sup comp gr plur sing ext pers rel indic obj impers abl'.split())
# Lowercase grammar stems that the print ends a gloss on, found by
# work/abbrev-periods/detect.py. Capitalised stems pass the rule above.
_GRAM_TAIL_ADDED = frozenset(
    'absol abstr active amplif analog appel art aug class collect com comm '
    'compd concr conj constr contr corresp decl dem demonstr dep deriv dim '
    'dissyl distr ellipt epic euphon finit freq imperf inanim inch indecl '
    'indef intens interrog lang metaph meton mid neg nom numer object obl '
    'onomat orig part partit patr pleon plqpf poet posit pos poss praep prep '
    'pregn pron prop prov proverb rhet signif simp specif subject subst suff '
    'syll syn sync transf trisyl trop vb'.split())
_GRAM_TAIL = _GRAM_TAIL | _GRAM_TAIL_ADDED
_LINK_TAIL = frozenset(
    'cf ap al ib id sq sqq etc esp opp usu freq dub prob sc viz'.split())

# These are English words ending a sentence ("with quick-turning art.",
# "the end of any object.") on stems that elsewhere are the print's
# abbreviations ("v. the foll. art.", "gen. object."). Two readers checked
# them, so they are listed by name rather than guessed by rule.
_PERIOD_WORD_VETO = frozenset({
    ('grc', 'ὀξυρεπής', 'art'),
    ('lat', 'bulla', 'art'),
    ('lat', 'caelo', 'art'),
    ('lat', 'cornu', 'object'),
    ('lat', 'provoco', 'object'),
    ('lat', 'idem', 'subject'),
    ('lat', 'locus', 'subject'),
    ('lat', 'ipse', 'subject'),
    ('lat', 'simul', 'term'),
    # A translation, not a sense line: "give a specimen of his art".
    ('grc', 'ἐπιδείκνυμι', 'art'),
    # "Poet. transf., a lyric poet": the person, not poet(ice).
    ('lat', 'fidicen', 'poet'),
})


def _cue_italics(html):
    html = re.sub(r'<i>(.*?)</i>', r'<b class="cue">\1</b>', html)
    return _tidy(html)


def _mute_italics(html):
    html = re.sub(r'<i>(.*?)</i>', r'<i class="tr">\1</i>', html)
    return _tidy(html)



def _has_words(html):
    """Letters, not leftover punctuation: STRIP_WORK on πάμφυλος III
    leaves ', ' behind, which is not a surviving gloss."""
    return bool(re.search(r'[^\W\d_]', L.text_of(html or '')))


# A Greek run that opens a sense and is followed by one of these is the
# thing being defined, not an illustration of it: LSJ ἐπί II reads
# "ἔπι, for ἔπεστι, there is". Pull the Greek out and the line becomes
# "for ἔπεστι, there is" — a definition with no subject.
DEFINED_BY = re.compile(
    r'^(?:for|=|i\.\s?e\.|short(?:ened)? for|abbrev\.\s*for|'
    r'(?:[A-Za-z]+\.?\s+)?(?:for|form of)\b)',
    re.I)


# A sentence that ends on a preposition governs the citation after it:
# "first in Hom.", "condemned by Arist.", "cj. for ἀδαής in Hp." The
# citation strip took the object with the reference and 10,296 Greek
# rows ended "first in", "condemned by". The name stays in the sentence;
# the citation stays a citation and still feeds the chips. Only when
# nothing separates the two — a gloss can end on a preposition of its
# own ("worth listening to,") and the print's comma is what says so.
_GOVERNOR_END = re.compile(
    r'(?:^|[\s>(])(?:in|by|with|from|to|than|of|after|before|among|as|acc\. to)'
    r'\s*$', re.I)


def keep_governed_author(zone, ev):
    zt = L.text_of(zone)
    if not zt or not _GOVERNOR_END.search(zt):
        return zone
    m = re.match(r'\s*<span class="lx-bibl"[^>]*>', ev)
    if not m:
        return zone
    block = ev[m.start():_complete_el(ev, m.start()) or len(ev)]
    a = re.search(r'class="lx-author"[^>]*>([^<]+)', block)
    name = a.group(1).strip() if a else ''
    if not name:
        t = re.match(r'<span class="lx-bibl"[^>]*>\s*<i class="lx-title">([^<]+)</i>',
                     block)
        name = t.group(1).strip() if t else ''
    if not name or not re.match(r'[A-Z]', name):
        return zone
    return zone.rstrip() + ' ' + htmllib.escape(name)


# The object the sentence governs, when Perseus wrapped it in the
# quotation that follows it: ξεστιαῖος "of a ξέστης, μέτρον Gal. 13.435"
# marks "ξέστης, μέτρον" as one lx-quote, and the row read "of a". The
# first word before the print's comma is the object and moves onto the
# line; the rest stays the example. A quote of one word with no comma
# (ἀκόσμητος "not organized as a κόσμος") moves whole, and the citation
# stays for the chips. A phrase before the comma is a quotation.
def keep_governed_quote(zone, ev):
    zt = L.text_of(zone)
    if not zt or not _GOVERNED_LEAD.search(zt):
        return zone, ev
    m = re.match(r'\s*<span class="lx-cit"[^>]*>\s*(<span class="lx-quote"[^>]*>([^<]*)</span>)', ev)
    if not m:
        return zone, ev
    first, _sep, rest = m.group(2).partition(',')
    first = first.strip()
    if not first or len(first.split()) > 2 or not re.search(r'[Ͱ-Ͽἀ-῿]', first):
        return zone, ev
    obj = f'<span class="lx-foreign" lang="{LANG}">{first},</span>'
    if rest.strip():
        ev = ev[:m.start(2)] + rest.strip() + ev[m.end(2):]
        return zone.rstrip() + ' ' + obj, ev
    # The whole quote was the object, and the italic the print set after
    # it inside the citation continues the sentence: ψιλοκιθαριστής "one
    # who plays the κιθάρα *without singing to it*". It comes too, or
    # it is lost with the example it used to translate.
    obj = f'<span class="lx-foreign" lang="{LANG}">{first}</span>'
    # The whole element goes with its text. An empty lx-quote left
    # behind read as a second, childless sense (βούνιον II, ὀνύχιον I,
    # σπληνίσκος, χαλκίδιον, and about a hundred more).
    tail = re.match(r'\s*<i>(?!<)(.*?)</i>', ev[m.end():])
    if tail and '<span' not in tail.group(1):
        ev = ev[:m.start(1)] + ev[m.end():m.end() + tail.start()] \
            + ev[m.end() + tail.end():]
        return zone.rstrip() + ' ' + obj + ' <i>' + tail.group(1) + '</i>', ev
    ev = ev[:m.start(1)] + ev[m.end(1):]
    return zone.rstrip() + ' ' + obj, ev


# A quotation cannot close a bracket the definition opened. Perseus
# starts the lx-quote too early where the print's aside runs past the
# citation: L&S concitor reads "(rare; not in Cic.; <quote>in MSS. freq.
# interchanged with concitator): belli,</quote> Liv." and the citation
# strip took the aside's tail away with the element, so 412 Latin and
# 166 Greek rows ended on a bracket opened over nothing. The words up to
# and including the mate belong to the sentence and move out in front of
# the quotation; what the print writes after them, past its own colon or
# comma, stays the quotation.
_QUOTE_EL = re.compile(
    r'(<span class="lx-cit"[^>]*>\s*)?(<span class="lx-quote"[^>]*>)([^<]*)(</span>)')


def close_open_paren(zone):
    def fix(m):
        before = L.text_of(zone[:m.start()])
        if before.count('(') <= before.count(')'):
            return m.group(0)
        inner = m.group(3)
        depth = 0
        for i, ch in enumerate(inner):
            if ch == '(':
                depth += 1
            elif ch == ')':
                if depth == 0:
                    head, tail = inner[:i + 1], inner[i + 1:]
                    break
                depth -= 1
        else:
            return m.group(0)
        # An aside's tail is a few words. A long one means the quotation
        # itself carries a bracket and the mate is the print's own.
        if len(head.split()) > 12:
            return m.group(0)
        tail = re.sub(r'^\s*[:;,]\s*', '', tail)
        # In front of the citation element, not merely of the quotation
        # inside it: the strip takes the whole element and the aside's
        # tail would go with it.
        return (head.strip() + ' ' + (m.group(1) or '')
                + m.group(2) + tail + m.group(4))
    return _QUOTE_EL.sub(fix, zone)


# A work title the sentence governs keeps its name, as a governed
# author does: ἀμοιβή "requital, recompense, Hom. only in Od." lost the
# Od. to the title strip and ended "only in". The locus goes.
_GOVERNED_TITLE = re.compile(
    r'((?:^|[\s>(])(?:in|by|with|from|to|than|of|after|before|among|acc\. to)\s+)'
    r'<i class="lx-title">([^<]+)</i>(?:\s*(?:[IVXΙΧ]{1,4}(?=\())?[\d.]*(?:\(\d+\))?'
    r'[\d.]*\d(?:,\s*[\d.]+)*[a-z]?)?', re.I)


def _keep_governed_titles(html):
    return _GOVERNED_TITLE.sub(r'\1\2', html)


# A Greek run the sentence governs is its object, not an illustration.
# "one who wears a σίσυρνα", "Dim. of ἄβαξ", "warden of a κῶμος": the
# print names the word in the middle of the English, and the split took
# it for a quotation, so 2,685 Greek rows ended "of", 546 "the", 406 "a"
# and 357 "as", with the object in the drawer and, where the print's
# italic followed it, the real gloss read as that quotation's
# translation (ἀβακίσκος lost "small stone for inlaying"). Two shapes
# say the Greek is governed: it stands inside the print's own italic,
# or the text in front of it ends on a governor with nothing — no comma,
# no colon — between the two. The comma is what says a quotation
# follows ("find fault with, τινί").
_GOVERNED_LEAD = re.compile(
    r'(?:^|[\s>(])(?:of|a|an|the|as|like|into|than|to|on|in|with|by|from|'
    r'and|or|i\.\s?e\.|e\.\s?g\.|sc\.)\s*$', re.I)


def _split_point(z):
    """The first Greek run that illustrates the sense, or None when every
    run is part of the sentence."""
    for m in GREEK_SPAN.finditer(z):
        before = z[:m.start()]
        if before.count('<i>') > before.count('</i>'):
            continue
        if _GOVERNED_LEAD.search(L.text_of(before)):
            # Unless Perseus wrapped the governed word and the quotation
            # illustrating it in one span: προστάτις marks "προστάτης,
            # ἐὰν … θεαῖς" as a single run, and keeping all of it on the
            # line loses S. OC 458 with the drawer. The print's comma
            # inside the span, with a real clause after it, says a
            # quotation follows.
            inner = L.text_of(m.group(0))
            head, _sep, rest = inner.partition(',')
            if not (rest and len(rest.split()) >= 3 and len(head.split()) <= 3):
                continue
        # Inside the print's own parenthesis the sentence is an aside
        # about the word, and the Greek in it is what the aside is about:
        # θεόπληκτος "(in Dor. form -πλακτος)", ἤτριον "(the woof being
        # κρόκη)", μετεωριστής "(explaining the Aeol. form πεδαοριστής)".
        # Taken as an illustration it went to the drawer and left the
        # bracket open on the sense line.
        plain = L.text_of(before)
        if plain.count('(') > plain.count(')'):
            # Only where the print's bracket actually closes after the
            # run. A "(" the citation strip orphaned is not an aside:
            # ποτίζω 4 lost "(Axum, iv A.D.);" and the stray bracket
            # then held every following run out of the drawer, leaving
            # the sense line as "(; οἴνῳ codd. )".
            # The mate may sit inside the run itself, which is how
            # Perseus marks ἀφοπλίζω's "(in Lacon. form ἀφοπλίττονται),"
            # with the bracket inside the span.
            # And only where the sentence has words of its own in front
            # of the bracket. ποτίζω 4 is nothing but "( ; οἴνῳ codd. )"
            # once its citations are out, and holding the Greek there
            # leaves the reader a sense line of punctuation.
            if not re.search(r'[^\W\d_]{2}', plain.split('(')[0]):
                pass
            elif ')' in L.text_of(m.group(0)) or ')' in L.text_of(z[m.end():]):
                continue
        return m
    return None


# LSJ's editorial brackets sit outside the span Perseus wrapped the word
# in: "[κλέος] οὐκ ἀ.", "ἀβίωτόν [ἐστι] life is intolerable". Split at
# the span and one bracket stays on the sense line (691 Greek rows ended
# "[", 258 opened "]"). The bracket belongs with its letters.
def _brackets_into_greek(z):
    z = re.sub(r'\[\s*(<span class="lx-(?:foreign|quote)"[^>]*>)([^<]*)(</span>)\s*\]',
               r'\1[\2]\3', z)
    z = re.sub(r'\[\s*(<span class="lx-(?:foreign|quote)"[^>]*>)([^<\[]*\][^<]*</span>)',
               r'\1[\2', z)
    z = re.sub(r'(<span class="lx-(?:foreign|quote)"[^>]*>[^<\]]*\[[^<\]]*)(</span>)\s*\]',
               r'\1]\2', z)
    return z


def split_sense(zone):
    """CGL order: English is the sense, Greek is an example.

    LSJ often writes the idiom first (θεῖναί τινί τι ἐν χερσίν, put it
    in his hands). Pull the English to the front; the Greek follows as
    illustration. A short pre-Greek rubric (of ships, of women) stays
    as a parenthetical, not as the cue."""
    z = _strip_citations(close_open_paren(zone))
    z2 = STRIP_WORK.sub('', _keep_governed_titles(z))
    if _has_words(z) and not _has_words(z2):
        # The pack marked the gloss itself as a work title: πάμφυλος III
        # is <i class="lx-title">Pamphylian</i> and nothing else. Unwrap
        # it rather than delete the sense.
        z2 = re.sub(r'<i class="lx-title">(.*?)</i>', r'\1', z, flags=re.S)
    z = z2
    z3 = strip_crossrefs(z)
    if _has_words(z) and not _has_words(z3):
        # "(cf." opened here and closes past the citation cut, so the
        # nested-paren walk ran off the end (καταστηματικός II).
        z3 = re.sub(r'\(\s*(?:cf\.|v\.|vide)\s*$', '', z, flags=re.I)
    z = _brackets_into_greek(z3)
    m = _split_point(z)
    if not m:
        return _cue_italics(z), ''
    pre, rest = z[:m.start()], z[m.start():]
    greeks, pos = [], 0
    for gm in GREEK_SPAN.finditer(rest):
        gap = L.text_of(rest[pos:gm.start()]).strip(' ,;:—')
        if pos and gap:
            break
        greeks.append(gm.group(0))
        pos = gm.end()
    ill, tail = ''.join(greeks), rest[pos:]
    pre_txt = L.text_of(pre).strip(' ,.;:—')
    tail_txt = L.text_of(tail).strip(' ,.;:—')
    if not pre_txt:
        if DEFINED_BY.match(tail_txt):
            # Keep the Greek on the sense line; it is the subject.
            return _cue_italics(ill + ' ' + tail), ''
        return _cue_italics(tail), _mute_italics(ill)
    # "opp. ἀθάνατος", "cf. θνησείδιον": the Greek is a word being named,
    # not a quotation. Left as an illustration it lands in the drawer and
    # is handed the next citation in the entry (θνητός got Od. 5.213).
    if REF_LEAD.search(L.text_of(pre)[-24:]):   # unstripped: pre_txt has lost the '.' of 'opp.'
        # Resolving "= sq." inserts the neighbour before a quoted form.
        # Keep the named neighbour on the equation line, but leave the
        # following Greek run in the evidence drawer.
        if re.search(r'=\s*$', L.text_of(pre)) and len(greeks) > 1:
            gm = list(GREEK_SPAN.finditer(rest))[1]
            main = pre + greeks[0] + rest[gm.end():]
            return _cue_italics(main), _mute_italics(gm.group(0))
        return _cue_italics(z), ''
    if '<i>' not in pre and RUBRIC_LEAD.match(pre_txt) and tail_txt:
        rub = pre_txt.rstrip(' ,;:')
        eng = f'<span class="rub">({htmllib.escape(rub)})</span> ' + _cue_italics(tail)
        return _tidy(eng), _mute_italics(ill)
    return _cue_italics(pre), _mute_italics(ill + ' ' + tail)


def _sense_segments(body):
    """[(zone, evidence)] — one pair per definition the print wrote into
    this sense (L.defsegments), minus the candidates that turn out not to
    be definitions.

    A candidate earns its own row only if its zone carries a cue — an
    italic translation the print set there. Anything else is apparatus
    that happened to start with an italic, and folds back into the
    evidence of the definition before it, so segmenting never costs a
    citation or an example."""
    segs = L.defsegments(body)
    if len(segs) == 1:
        return segs
    # Evidence accumulates in a list and is joined once. Folding with
    # `+=` copies the whole accumulated string per rejected candidate,
    # which is quadratic in its length — invisible on LSJ's short
    # entries and pathological on L&S's long ones, where `ab` and `A1`
    # took the Latin half of the build from a minute to over ten.
    kept = [(segs[0][0], [segs[0][1]])]
    for sz, sev in segs[1:]:
        if continuation_gloss(sz, sev):
            kept.append((sz, [sev]))
        else:
            kept[-1][1].extend((sz, sev))
    return [(z, ''.join(parts)) for z, parts in kept]


# A parenthesised letter is the print's address for a sub-division
# (πρύτανις "(a)"), not a definition it can head. The brackets are what
# say so: bare, three letters is a gloss — LSJ ἀφαυρός is "feeble,
# powerless … dim", and die, pay, see, fan, dew, row, rot and dye are
# all glosses this rule used to reject.
ADDRESS_ONLY = re.compile(r'^(?:\([a-zA-Z0-9]{1,3}\)|[a-zA-Z0-9])[.,]?$')


def _lead_punct(html):
    """Drop the punctuation that separated this definition from the one
    before it. The print's dash before a further note ("—also of men,
    opp. monsters") separated something; on its own line it separates
    nothing, and the same goes for the comma or colon a cut lands after.
    A hyphen stays — it abbreviates a sub-lemma, and θεατρικά ships as
    "-κά, τά, properties"."""
    # A leading period only when it is not the print's ellipsis: LSJ
    # opens a quotation with ". ." and the mark is the witness's (ἄλλος).
    return re.sub(r'^(\s*(?:<[^>]+>\s*)*?)(?:[—–,;:]|\.(?!\s*[.·]))\s*', r'\1', html)


def continuation_gloss(zone, ev=''):
    """(gloss, illustration) if this segment holds a definition the print
    wrote, else None. One predicate, used both to decide whether a
    segment stands on its own and to build its row — a segment rejected
    here folds its wording back into the definition before it, and a
    second, looser test on the way to the row would drop that wording
    instead (πρατήριον lost Plu. and D.C. exactly that way).

    A block the print opens with "Adv." states its gloss INSIDE the
    citation that follows it — ἀβαρής reads "Adv. -ρῶς *without giving
    offence,* Simp." — so the zone is the bare marker and carries no cue.
    That is the shape zone_from_evidence already reads for ἅλς III and
    τίθημι 12; the marker stays in front of what it finds, because "Adv."
    is what says the gloss belongs to the adverb."""
    zone = keep_governed_author(zone, ev)
    eng, ill = split_sense(zone)
    # Only for a block the print sets off with its own marker. Running
    # it on every rejected candidate re-scans that candidate's whole
    # evidence, which took the build from 2.5 minutes to over ten.
    # Bounded by evidence size as well as by shape. zone_from_evidence
    # rescans its argument per span (each_span re-slices), so it is
    # quadratic in the evidence it is handed — fine on the short Adv.
    # block this is for, and ruinous on L&S's long entries, which open
    # lx-pos blocks by the dozen. A block that stated its gloss inside
    # its first citation does not need 4kB to do it.
    if (ev and len(ev) < 4000 and '<b class="cue">' not in eng
            and zone.lstrip().startswith('<span class="lx-pos"')):
        ev_eng, ev_ill = zone_from_evidence(ev)
        # An adverb's gloss is short — "Adv. -τως without delay". A long
        # one means the block ran past its own definition and swallowed
        # what followed: ἁβρός's Adv. section came back "step delicately,
        # 5, : neut. sg. as Adv., neut. pl., 42.5: Comp..—Chiefly poet.".
        # Length is the honest test here; the print's punctuation is not,
        # since L&S writes "Adv.: word, gloss" with a colon by
        # convention. A block this rule declines is left exactly where it
        # was before the rule existed.
        if '<b class="cue">' in ev_eng and len(L.text_of(ev_eng)) <= 60:
            # From the zone, not from eng: split_sense tidies a
            # trailing period away, and "Adv." is an abbreviation whose
            # period is part of it.
            lead = L.text_of(zone).strip(' ,;:')
            eng = _tidy(f'{lead} {ev_eng}' if lead else ev_eng)
            ill = ev_ill
    eng = _strip_dangling(_lead_punct(eng))
    if not _has_words(eng) or '<b class="cue">' not in eng:
        return None
    if ADDRESS_ONLY.match(L.text_of(eng)):
        return None
    # A definition uses words. Ἀσκληπιός's sub-lemma chain leaves
    # "2.617b, 12(1).162" carrying a cue tag and nothing a reader could
    # read as a meaning; every real gloss has a word of two letters.
    if not re.search(r'[^\W\d_]{2}', L.text_of(eng)):
        return None
    return eng, ill


def _without_quotations(conts, examples):
    """The continuation candidates minus the Lewis & Short quotations
    now in the sense's drawer.

    A Latin quotation with its translation in the italic is not a
    definition (see _latin_quotation_lead), and once examples_of has it
    the row that shipped the translation as a sense says it twice. Only
    then: the example budget is per definition, and a translation the
    drawer cannot hold stays on the line it was on rather than leaving
    the reader-visible text. The sense's evidence is the whole
    paragraph either way, so nothing folds and nothing is lost.

    And only what the drawer says. The print writes a note after the
    quotation often enough — abdo's "—Comp. abditior", acer's "—Acer is
    constr. with abl.", adoptivus's "(or grandson, v. adoptio)" — and
    that note is on this candidate, not in the drawer. Dropping the
    candidate whole took it with them: 59 entries lost wording that way
    when the budget went from four to eight and rows the old cap had
    left alone started converting. A candidate that says anything the
    drawer does not carry keeps its row."""
    if not conts or not examples or not DATASET.startswith('lat'):
        return conts
    drawer = {e['gr']: e.get('eng') or '' for e in examples}
    out = []
    for z, e in conts:
        lead = _quotation_lead(z, e)
        if lead not in drawer:
            out.append((z, e))
            continue
        got = continuation_gloss(z, e)
        said = _content_words(L.text_of(got[0])) if got else set()
        if said - _content_words(drawer[lead]) - _content_words(lead):
            out.append((z, e))
    return out


def _content_words(text):
    """Words a reader would miss, for comparing what two fields say."""
    return {w.lower() for w in re.findall(r"(?<![^\W\d_])[^\W\d_]{3,}(?![^\W\d_])",
                                          text or '')}


def continuation_row(parent, zone, ev):
    """A row for a definition the print wrote later in the same sense
    paragraph. It has no address of its own — LSJ never numbered it — so
    it ships supplied, one level under the definition it follows."""
    got = continuation_gloss(zone, ev)
    if not got:
        return None
    eng, _ill = got
    # "Adv." opens a sub-entry of the WORD, not of the definition it
    # follows: ἀβαρής's adverb is not a sub-sense of "not burdensome".
    # Indenting it there would trade a wrong citation for a wrong place.
    block = zone.lstrip().startswith('<span class="lx-pos"')
    return {
        'lv': parent['lv'] if block else parent['lv'] + 1,
        'n': '',
        'supplied': True,
        'banner': False,
        'usage': is_usage(eng, L.text_of(eng)),
        'zone': eng,
        'zfull': eng,
        'illust': '',
        # No evidence of its own — see the note in model(). The sense's
        # quotations and authors stay on the sense's own row.
        'examples': [],
        'plain': L.text_of(zone),
        'authors': [],
        'slug': parent['slug'],
        'lemma': parent['lemma'],
        'kids': False,
        'lifted': False,
        'cont': True,
    }


def cue_zone(zone):
    eng, _ = split_sense(zone)
    return eng


def cap_label(lab, limit=42):
    """A tab label fits its button; a cap that lands inside a bracket
    does not ("Med., fut. ἀφαιρήσομαι (in pass. sense" on ἀφαιρέω II).
    Cut at the word before the limit, then drop an aside the cut left
    open, and the link word or separator that is then last.

    Only a label the cut touched is trimmed. The print writes labels
    that simply end on a preposition — ἀγαπάω's "show affection for",
    ἐξάπτω's "set fire to" — and trimming those took a word the print
    meant, which is not what a cap is for."""
    cut = False
    if len(lab) > limit:
        lab = lab[:limit].rsplit(' ', 1)[0]
        cut = True
    if lab.count('(') > lab.count(')'):
        # Not when the aside is the whole label: redeo II is "(With the
        # idea of ire predominating; cf.: recido, redigo)", and dropping
        # the bracket left the division with no label at all. Keep the
        # words and lose the bracket.
        without = lab[:lab.rfind('(')]
        lab = without if without.strip() else lab.replace('(', '', 1)
        cut = True
    if not cut:
        return lab
    return re.sub(r'(?:\s+(?:of|in|with|to|for|and|or|the|a)|[\s,;:—])+$', '', lab)


def short_label(zone_text, n=6):
    t = re.sub(r'\s+', ' ', zone_text).strip(' ,.;:—')
    t = re.split(r'\s*\(cf|\s*\(v\.|\s*\(whether|\s*\(freq', t, maxsplit=1)[0]
    t = t.strip(' ,.;:—(')
    words = t.split()
    if len(words) <= n:
        return t.rstrip('.,;:')
    return ' '.join(words[:n]).rstrip('.,;:')


USAGE_LEAD = re.compile(
    r'^(?:among the \w+|later\b|as a title|'
    r'in (?:the )?(?:LXX|NT|N\.T\.|Poets|prose|Hom\.|Att\.|Ion\.|Dor\.|Aeol\.|Com\.|Trag\.))\b',
    re.I)


def is_usage(zone_html, zone_text):
    """Corpus/register note, not a new translation equivalent.

    A numbered LSJ/L&S line with no italic gloss ('among the Jews',
    'later as a title') is a usage chip, not a sense."""
    t = re.sub(r'\s+', ' ', zone_text or '').strip(' ,;:')
    if re.match(r'^(Lit|Trop|Transf|In gen|Esp|In partic)\b', t, re.I):
        return False
    if '<b class="cue">' in (zone_html or ''):
        return False
    if 'lx-usg' in (zone_html or ''):
        return True
    return bool(USAGE_LEAD.match(t))


def is_letter_addr(nn):
    """A–H, K–U, W–Z. I/V/X are roman, not letter I/V."""
    return bool(LETTER.match(nn or '') and nn not in 'IVX')


def is_banner(n, zone_text, has_children, lv=0, lifted=False, attested=False):
    nn = (n or '').rstrip('.')
    zt = zone_text.strip()
    if nn == '•':
        return False
    # A childless line is a sense (Latin A. Food; Greek V. τιθέναι νόμον).
    if not has_children:
        return False
    # A line the print attests is a sense, however label-shaped: L&S
    # cruento "I. Lit.: vigiles, Enn. ap. Macr." quotes and cites the
    # literal sense before A/B divide it, LSJ ἀνάλγητος "I. of persons,
    # insensible to pain or danger, Meliss. ap. Arist." the same. A
    # heading introduces children and has nothing to cite. These rows
    # were senses only while citation debris padded the gloss past the
    # word counts below; once the lead joined its citation, nine turned
    # into headings and shipped ex: [] and au: [].
    if attested and lv > 0 or attested and BANNER_ZONE.match(zt):
        return False
    m = BANNER_ZONE.match(zt)
    if m:
        rest = zt[m.end():].strip(' ,.;:—')
        # "ABS., used adverbially…" is a sense, not an empty Abs. header.
        # A lifted row is a print sense: it heads only when NOTHING
        # follows the label — προσαυγάζω III "abs., gleam" is the
        # one-word gloss the < 2 rule was eating.
        return len(rest.split()) < (1 if lifted else 2)
    # A lifted row's gloss and examples are its content — the
    # address-shape rules below would blank them to a label. An address
    # WE supplied says the same thing: the print left that paragraph
    # unnumbered, so the roman it now wears is our inference and cannot
    # be evidence that the print meant a section head. μένος opens
    # "might, force" with four quotations of its own and sub-senses 2–4
    # under it; reading its supplied I. as a heading drops all four.
    if lifted:
        return False
    if not (ROMAN.match(nn) or is_letter_addr(nn)):
        return False
    # Top A/B/C and I/II are section heads even when they carry a cue.
    if lv == 0:
        return True
    # Nested roman/letter: kickers (of Place), not a 9-word gloss.
    return len(zt.split()) <= 8


def has_child(items, i):
    dl = items[i][0]
    return i + 1 < len(items) and items[i + 1][0] > dl


# LSJ marks a homonym with a parenthesised capital after the headword —
# ἄβιος (A), ἄβιος (B) — and the pack key carries a digit instead
# (a)/bios1, a)/bios2), because the key is Perseus's handle, not the
# print's mark. Rendering the digit as the superscript invents a mark
# LSJ never wrote: κάρ is key ka/r2 and the print letters it (A).
#
# Worse, the key numbers homonyms the print does not distinguish at all.
# 561 of the 1,474 numbered keys have no letter in the entry, so the
# entry showed a superscript for a distinction its own text never makes.
# Both reader sites had already stopped trusting it and read the letter
# themselves; this puts the print's answer in the pack, where it belongs.
# Within the opening of the entry, not glued to the headword: the print
# sets the letter after the inflection as often as before it — "ἄβιος,
# (B), ον" but "ἄβιος, ον (A), = ἀβίωτος". Anchoring it to the first
# token, which is what both reader sites do, misses the second shape.
# A single capital alone in brackets is a specific enough thing that a
# 40-character window does not collide with the citations that follow
# ("(Leon.)" has no single capital in it).
_PRINT_HOM = re.compile(r'^.{0,40}?\(([A-Z])\)')


def print_homonym(rec):
    """The homonym letter LSJ printed, or '' where it printed none.

    LSJ only. Lewis & Short marks no homonyms at all — "abactus, a, um,
    Part. of abigo" against "abactus, ūs, m." are told apart by their
    inflection and nothing else — so the Latin digit is invented in the
    same way the Greek one is, and 4,210 entries carry it. Removing it
    would leave a reader no way to refer to one of three stacked malus
    entries, which is a different question from LSJ's, where the print
    supplies a letter to use instead. Latin keeps the key's digit until
    that question is answered.
    """
    if DATASET.startswith('lat'):
        m = re.search(r'(\d+)$', rec.get('key') or '')
        return m.group(1) if m else ''
    m = _PRINT_HOM.match(' '.join(L.text_of(rec.get('html') or '').split()))
    return m.group(1) if m else ''


def _drop_print_homonym(rest):
    """LSJ's homonym letter is the record's `hom`, not its identity line.

    ἀδεής shipped an identity line reading "(A)" and ἄμαλλος (B) a gloss
    "= (B): πέρδιξ". The letter sits in the first few tokens after the
    headword, before or after the inflection (print_homonym reads the
    same window)."""
    if DATASET.startswith('lat'):
        return rest
    m = re.search(r'\s*\(([A-Z])\)(?![A-Za-z])\s*[·\u0387:]?'
                  r'(?:(<span class="lx-foreign"[^>]*>)\s*[·\u0387]\s*)?', rest[:80])
    if not m or len(L.text_of(rest[:m.start()])) > 40:
        return rest
    return rest[:m.start()] + (m.group(2) or '') + rest[m.end():]


# The governor a stripped citation leaves at the end of a line: "v.l. in",
# "(in", "also in". Both the identity line and its match against the forms
# bar use it.
_STRANDED_IN = re.compile(r'\s*\(?\s*(?:(?:or|also|and)\s+)?(?<![^\W\d_])in$')

_HEAD_GEN = re.compile(r'<span class="lx-gen"[^>]*>.*?</span>', re.S)


def _paren_depth(raw, stop):
    depth = 0
    in_tag = False
    for ch in raw[:stop]:
        if ch == '<':
            in_tag = True
        elif ch == '>':
            in_tag = False
        elif not in_tag:
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth = max(0, depth - 1)
    return depth


def _head_gender(raw):
    """The headword's gender element, apart from collateral forms."""
    gens = list(_HEAD_GEN.finditer(raw))
    if not gens:
        return None
    first = gens[0]
    if _paren_depth(raw, first.start()) > 0:
        first_text = L.text_of(first.group(0)).strip()
        # Grok and Opus read charta's inner m. as chartus's and its outer
        # f. as the headword's. Prefer that differing top-level gender.
        for gen in gens[1:]:
            if (_paren_depth(raw, gen.start()) == 0
                    and L.text_of(gen.group(0)).strip() != first_text):
                return gen.group(0), gen.start(), gen.end()
    return first.group(0), first.start(), first.end()


_LAT_GRAM_TAGS = {'lx-itype', 'lx-gen', 'lx-pos', 'lx-number'}
_LAT_FOREIGN_EQ = re.compile(r'<span class="lx-foreign"[^>]*\blang="grc"[^>]*>')
# The dialect and form labels L&S sets before a further Greek spelling
# in the equation's own clause — "= κρατήρ, Ion. κρητήρ" — found by
# scanning every lat-ls entry with an opening equation for this shape.
# Only Ion., Dor. and the unabbreviated Doric occur there; Att., Aeol.,
# Ep., poet., Lacon. and Boeot. are L&S's other dialect labels and are
# accepted on the same footing should one of them appear here too.
_LAT_DIALECT_LABEL = re.compile(
    r',\s*(?:Ion|Dor(?:ic)?|Att|Aeol|Ep|Lacon|Boeot|poet)\b\.?\s+')
# The same labels, at the front of a parenthesis instead — "(Dor.
# ἄρυγγος)", "(Doric μᾶλον)", "(epic, Καλλιρόη)" — with an optional
# comma after the label instead of the one required before it above.
# The set actually found this way: Dor., Doric, epic; the rest are
# L&S's other dialect and form labels, accepted on the same footing.
_LAT_PAREN_LABEL = re.compile(
    r'^(?:Dor(?:ic)?|Ion(?:ic)?|Att(?:ic)?|Aeol(?:ic)?|Ep(?:ic)?|epic'
    r'|poet|Lacon(?:ic)?|Boeot(?:ian)?)\.?,?\s+')


def _lat_last_gram_end(pre, start, before):
    """End offset of the last top-level lx-itype/lx-gen/lx-pos/lx-number
    element in pre[start:before], skipping one that belongs to a
    parenthetical aside (Alpes's "(rare in sing., Alpis, is, = ...)" has
    its own itype, and it is not the headword's)."""
    last = None
    i = start
    while i < before:
        if pre[i] == '<':
            j = _complete_el(pre, i) or i + 1
            if j <= before and _paren_depth(pre, i) == 0:
                if _tag_class(pre[i:j]) in _LAT_GRAM_TAGS:
                    last = j
            i = j
            continue
        i += 1
    return last


def _lat_gap_is_clean(gap):
    """Whitespace and punctuation, with at most one balanced aside inside
    it — nothing else may stand between the headword's own grammar and
    its equation. cetus keeps its aside this way: "m. (acc. to the Gr.
    cētŏs, ...), = κῆτος"; botryo's "a parallel form to botrys" does not,
    because it is prose outside any parenthesis."""
    depth = 0
    kept = []
    for ch in gap:
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth = max(0, depth - 1)
        elif depth == 0:
            kept.append(ch)
    return re.fullmatch(r'[\s,;:]*', ''.join(kept)) is not None


def _match_paren(raw, open_at):
    """Index just past the "(" at `open_at`'s matching ")", skipping
    parens written inside markup attributes (there are none in this
    text) and counting only ones outside any tag. None if it never
    closes."""
    depth, in_tag = 0, False
    i = open_at
    while i < len(raw):
        ch = raw[i]
        if ch == '<':
            in_tag = True
        elif ch == '>':
            in_tag = False
        elif not in_tag:
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
                if depth == 0:
                    return i + 1
        i += 1
    return None


def _strip_grc_diacritics(s):
    """Accents and breathings off, lower-cased — nothing else. Verified
    against John's own worked ratios (Κριμῖσός/Κριμισσός 0.94,
    Ἐριννύς/Ἐρινύς 0.92, ὑσσωπίτης/οἶνος 0.29): this plain NFD-strip,
    not `extract.fold_greek`'s Latin transliteration, is what reproduces
    them — fold_greek collapses ς and σ together and throws the ratios
    off (0.14 instead of 0.29 for the οἶνος case)."""
    s = unicodedata.normalize('NFD', s)
    return ''.join(c for c in s if not unicodedata.combining(c)).lower()


def _lat_variant_word_ok(word, base):
    """Is `word`, one further spelling L&S's parenthesis offers beside
    the equation's own Greek, actually a variant of it — John's rule
    (c)-(e), for the plain case with no label and no "or"/"and" (those
    two are decided before this is ever called; see
    `_paren_is_greek_only`).

    A hyphen at the front or back marks an ending or a stem, not a
    spelling, and is taken regardless of likeness: Arcesilas's "(-αος)",
    Paropamisus's "(Παραπ-)". A hyphen in the MIDDLE of the word marks
    an etymology instead and is never taken, however close the ratio
    reads — thermapalus's "θερμός-ἁπαλός" scores high against
    θερμάπαλος but is two words glossing the compound, not one spelling
    it. Otherwise the word stands or falls on
    `difflib.SequenceMatcher` closeness to the equation's own Greek word,
    accents and case folded off both sides: Crimisus's "(Κριμισσός)"
    against "Κριμῖσός" is 0.94 and taken; gagates's "(λίθος)" against
    "γαγάτης" is 0.17 and is not — L&S naming the stone the word means,
    not a further spelling of the word itself."""
    if word.startswith('-') or word.endswith('-'):
        return True
    if '-' in word:
        return False
    ratio = difflib.SequenceMatcher(
        None, _strip_grc_diacritics(word), _strip_grc_diacritics(base)).ratio()
    return ratio >= 0.6


def _paren_is_greek_only(inner, base):
    """True iff a parenthesis's contents belong on the equation line
    beside `base`, the equation's own Greek word.

    The shape is always: nothing but one or more Greek spans, with only
    commas, hyphens and whitespace between them — plus, at the front,
    one dialect or form label (see `_LAT_PAREN_LABEL`), and the print's
    own "and"/"or" joining two of the Greek spans. andron's "(ἀνήρ, a
    man)" fails this outright: "a man" is English left over once the
    Greek span and the label are removed, so this reads as L&S's own
    note on the word, not a further spelling of it. Same for a citation
    like Cannae's "(Κάννα, Polyb.)" — "Polyb." is left over too.

    That shape alone used to be enough, but L&S also parenthesizes the
    noun a word's meaning implies (gagates "(λίθος)", hepteris
    "(ναῦς)") and, once, an etymology (thermapalus's "(θερμός-ἁπαλός)")
    — Greek by that shape test, but not a further spelling of the
    equation. A label (aruncus's "(Dor. ἄρυγγος)") or an "and"/"or" join
    (philitia's "(φιδίτια and φειδιτια)") still settles it on its own;
    absent either, every word inside must itself be a variant of `base`
    — an ending/stem or a close spelling — see `_lat_variant_word_ok`."""
    lm = _LAT_PAREN_LABEL.match(inner)
    body = inner[lm.end():] if lm else inner
    # `kept`: the literal characters outside any Greek span, to check
    # the shape (nothing but whitespace/comma/hyphen/and/or) and spot an
    # "and"/"or" join. `recon`: the same, but with a Greek span's own
    # text spliced back in where it stood, so a boundary hyphen written
    # outside the span (Arcesilas's "(-<span>αος</span>)") stays right
    # next to the word it marks once this is split into words below.
    i, saw_grc, kept, recon = 0, False, [], []
    while i < len(body):
        if body[i] == '<':
            j = _complete_el(body, i) or i + 1
            if _LAT_FOREIGN_EQ.match(body[i:]):
                saw_grc = True
                recon.append(L.text_of(body[i:j]))
            else:
                kept.append(body[i:j])
                recon.append(body[i:j])
            i = j
            continue
        kept.append(body[i])
        recon.append(body[i])
        i += 1
    if not saw_grc:
        return False
    joined = ''.join(kept)
    has_and_or = re.search(r'\band\b|\bor\b', joined) is not None
    text = re.sub(r'\band\b|\bor\b', '', joined)
    if not re.fullmatch(r'[\s,\-]*', text):
        return False
    if lm or has_and_or:
        return True
    each = [w for w in re.split(r'[\s,]+', ''.join(recon).strip()) if w]
    return bool(each) and all(_lat_variant_word_ok(w, base) for w in each)


def _lat_extend_variant(pre, end, base):
    """Grow an equation's end past a further spelling the print gives
    in the same clause, right after it: a dialect or form label
    introducing another Greek span (cratera "= κρατήρ, Ion. κρητήρ"),
    or a parenthesis holding nothing but Greek (sandix "= σάνδυξ
    (σάνδιξ)"), with its own leading label (aruncus "(Dor. ἄρυγγος)")
    or "and"/"or" joining two Greek words inside it (philitia "(φιδίτια
    and φειδιτια)") allowed the same as outside. Chained "or"/"and"
    Greek after a label counts too, the same as the bare equation does.
    Stops at the first thing that is not one of those two shapes —
    culleus's own parenthetical gloss "(a sheath; hence)" after its
    "Ion. κουλεός" is left alone, same as andron's and Cannae's parens
    are. `base` is the equation's own first Greek word, for
    `_paren_is_greek_only` to measure a labelless, and/or-less
    parenthesis against (see `_lat_variant_word_ok`) — a dialect label
    still takes unconditionally, the same as outside the parens."""
    lm = _LAT_DIALECT_LABEL.match(pre[end:])
    if lm:
        j = end + lm.end()
        if _LAT_FOREIGN_EQ.match(pre[j:]):
            end = _complete_el(pre, j)
            while True:
                nx = re.match(r'\s+(?:or|and)\s+', pre[end:])
                if not nx:
                    break
                j2 = end + nx.end()
                if not _LAT_FOREIGN_EQ.match(pre[j2:]):
                    break
                end = _complete_el(pre, j2)
    pm = re.match(r'\s*\(', pre[end:])
    if pm:
        open_at = end + pm.end() - 1
        close = _match_paren(pre, open_at)
        if close is not None and _paren_is_greek_only(pre[open_at + 1:close - 1], base):
            end = close
    return end


def _lat_opening_equation(pre):
    """Lewis and Short's own "= <Greek>" from a headword's opening
    declaration, for a caller to append to the identity line.

    The shape: the headword, then its own grammar (declension, gender,
    part of speech, in either order, with at most one parenthetical
    aside among them), then "=" and a Greek span — "or"/"and" chaining a
    second Greek word when the print joins them that way (Partheni "=
    Παρθεινοί or Παρθινοί"), and then a further spelling the print
    gives in the same clause (see `_lat_extend_variant`). hypogeus goes
    on to derive a second word under "Hence, subst.:" with its own "=
    ὑπόγειον"; that clause is not even in `pre`, which stops at the
    entry's first sense, so it can never reach here. Anything else that
    intervenes before the "=" — an etymological note, a second
    headword's own declaration, a bare Greek span with no "=" before
    it — fails the shape, and this returns None rather than guess."""
    hm = re.search(r'<b class="lx-head"[^>]*>.*?</b>', pre, re.S)
    if not hm:
        return None
    start = hm.end()
    eq_pos = eq_end = base_word = None
    i = start
    while i < len(pre):
        if pre[i] == '<':
            i = _complete_el(pre, i) or i + 1
            continue
        if pre[i] == '=' and _paren_depth(pre, i) == 0:
            m = re.match(r'=\s*', pre[i:])
            j = i + m.end()
            if _LAT_FOREIGN_EQ.match(pre[j:]):
                eq_pos = i
                eq_end = _complete_el(pre, j)
                base_word = L.text_of(pre[j:eq_end])
                while True:
                    nx = re.match(r'\s+(?:or|and)\s+', pre[eq_end:])
                    if not nx:
                        break
                    j2 = eq_end + nx.end()
                    if not _LAT_FOREIGN_EQ.match(pre[j2:]):
                        break
                    eq_end = _complete_el(pre, j2)
            break
        i += 1
    if eq_pos is None:
        return None
    gram_end = _lat_last_gram_end(pre, start, eq_pos)
    gap = pre[start if gram_end is None else gram_end:eq_pos]
    if not _lat_gap_is_clean(gap):
        return None
    eq_end = _lat_extend_variant(pre, eq_end, base_word)
    clause = L.text_of(pre[eq_pos:eq_end])
    clause = re.sub(r'\s+', ' ', clause).strip(' .,;:—')
    return clause or None


def _latin_verb_opening(html):
    if not DATASET.startswith('lat'):
        return False
    pre, _ = L.split_preamble(html)
    pos = L.first_element(pre, 'lx-pos')
    text = L.text_of(pos[0]) if pos else ''
    return bool(re.search(r'(?:^|\s)v(?:\.|erb\b)', text, re.I))


def head_bits(html):
    pre, _ = L.split_preamble(html)
    hm = re.search(r'<b class="lx-head"[^>]*>.*?</b>', pre, re.S)
    lemma = L.text_of(hm.group(0)) if hm else ''
    rest = pre[:hm.start()] + pre[hm.end():] if hm else pre
    rest = _drop_print_homonym(rest)
    gen = _head_gender(rest)
    gender = L.text_of(gen[0]) if gen else ''
    if gen:
        rest = rest[:gen[1]] + rest[gen[2]:]
    rest = _strip_citations(_keep_quoted_forms(rest))
    rest = rest.replace(':—', '; ')
    if DATASET.startswith('grc'):
        # A work title with a locus is a citation: οὐσία's "SIG 167.26
        # (Mylasa, iv B. C.)" is where the Ion. form is attested, not a
        # fact about the word. A bare title is prose the sentence uses —
        # ἀάατος's "in Il. ⏑ _ _ ⏑" — and stays.
        rest = _TITLED_LOCUS.sub('', rest)
    at = L.first_citation(rest, extra='per|number')
    if at is not None:
        rest = rest[:at]
    ident = L.text_of(rest)
    ident = re.sub(r'\s+', ' ', ident).strip(' ,;:—')
    ident = re.split(r',?\s+with senses|\.\s+common in', ident)[0]
    ident = re.sub(r'\s+,', ',', ident)
    ident = re.sub(r',{2,}', ',', ident).strip(' ,;:—')
    # The shell a stripped citation leaves inside a bracket: ἀβέλτερος's
    # "(α, ον Pl. Phlb. 48c)" reads "(α, ον )" once the reference is out.
    ident = re.sub(r'\s+\)', ')', ident)
    itype = False
    if DATASET.startswith('lat'):
        if not gender:
            gm = re.search(r'(?:^|,\s*)([mfn])(?:\b|\.)', L.text_of(pre)[:100])
            if gm:
                gender = gm.group(1) + '.'
        it = L.first_element(pre, 'lx-itype')
        pos = L.first_element(pre, 'lx-pos')
        itype_txt = re.sub(r'\s+', ' ', L.text_of(it[0])).strip(' ,;:') if it else ''
        pos_txt = re.sub(r'\s+', ' ', L.text_of(pos[0])).strip(' ,;:') if pos else ''
        if not pos_txt and re.search(r'\bconj\.?\b', L.text_of(pre)[:80], re.I):
            pos_txt = 'conj.'
        if gender:
            ident = itype_txt
            itype = True
        elif pos_txt:
            ident = pos_txt
        else:
            ident = re.split(
                r'\b(?:Sanscr|kindr|Gr\.|cf\. root|cf\.:|cf\. Doed)\b', ident)[0]
            ident = ident.strip(' ,;:')
            ident = re.split(r'\s*;\s*', ident)[0]
    # The line ends where a label or citation the preposition governed
    # was stripped: L&S Academice "ēs, in Cic. Att. 13, 16", coopto "old
    # formula in Liv. 3, 64, 10". The governor goes with what it governed.
    # defigo's "to fasten down or in" is the print's gloss and stays.
    # hecatompolis's "in" is its itype — the Greek accusative — and stays.
    if not itype and not re.search(r'\b(?:down|up|out|off) (?:or|and) in$', ident):
        ident = _STRANDED_IN.sub('', ident).strip(' ,;:—')
    # Punctuation alone is not an identity line: οὔ που's head matter is
    # the print's ellipsis and nothing else, and ἀγαλματογλύφος's is the
    # "=" its pointer left behind (202 entries), with a stray "]" or "-"
    # in a few more. A digit is kept, because in L&S it is the
    # conjugation (expergiscor "3").
    # Two marks are the print speaking and stay: the asterisk LSJ sets in
    # front of a form it says is assumed rather than attested
    # (ἀμφαγνοέω), and the question mark it sets against a doubtful
    # gender (πυργομαγδῶλ "(τό?)", whose τό goes to the gender field and
    # leaves the doubt behind).
    if not re.search(r'[^\W_]', ident) and not re.fullmatch(r'[*]|\(\?\)', ident):
        ident = ''
    if len(ident) > 90:
        ident = ident[:90].rsplit(' ', 1)[0] + '…'
    # Grok and Opus read voveo's "v. a. and n." as verb labels. Clear
    # only the gender after building the identity, so principal parts stay.
    if gender and _latin_verb_opening(html):
        gender = ''
    # L&S opens onocrotalus "i, m., = ὀνοκρόταλος" — the Greek word the
    # Latin one comes from — and the transform above had been dropping
    # it. Restore just that clause from the opening declaration; a later
    # equation, like hypŏgēum's under hypogeus's "Hence, subst.:", is not
    # in `pre` at all and this never sees it.
    if DATASET.startswith('lat'):
        eq = _lat_opening_equation(pre)
        if eq and eq not in ident:
            ident = f'{ident}, {eq}' if ident else eq
    return lemma, gender, ident


IDENT_CLS = {
    'lx-orth', 'lx-itype', 'lx-gen', 'lx-pron', 'lx-pos',
}
GRAM_CLS = {'lx-gram', 'lx-gramGrp'}
FORM_OF_CLS = {'lx-per', 'lx-number', 'lx-mood', 'lx-tns', 'lx-gram', 'lx-gramGrp', 'lx-pos'}
QTY_RE = re.compile(r'^[ᾱᾰῑῐῡῠαειουωάέίόύήώ\u0304\u0306̄̆]{1,2}$')
SKIP_TXT = re.compile(r'^(?:[,;:\s]|or|and|also|etc\.?|—|--)+$', re.I)
PTR_TXT = re.compile(
    r'^(?:poet\.|late form|cj\.)?\s*for\b'
    r'|^v\.\s|^vide\b|^v\.\s*sub\b'
    r'|^fem\. of|^masc\. of|^neut\b|^Dim\. of'
    r'|^epith\.|^etym\. of|^expl\. of|^cj\. for|^f\.\s?l\.'
    r'|^sine expl|^exclam|^title of|^doubtful|^name of|^also\b'
    r'|^late form\b',
    re.I)
# Only a *reference* to the neighbouring entry — "fem. of sq.", "= foreg.",
# "v. sq." A bare "sq." after a page number is the print's "and following"
# (L&S dissidium: "Madv. ad Exc. II. p. 812 sq."); substituting a headword
# there invents a citation.
REL_LEAD = r'((?:\bof|\bv\.|\bcf\.|\bsee|=|\bfor)\s+)'
REL_SQ = re.compile(REL_LEAD + r'sq\.', re.I)
REL_FORE = re.compile(REL_LEAD + r'foreg\.', re.I)
# The abbreviation span may hold its own spaces — Perseus writes both
# "<span class="lx-abbr">=</span> sq." and "<span class="lx-abbr"> = </span>
# sq." — and requiring the bare glyph left 22 entries shipping a raw
# "= sq. 2" that names nothing to the reader (ἀρραφής, δουλικός,
# ἔναυλον). The neighbour lookup was working the whole time; nothing
# ever asked it.
REL_SQ_MARKUP = re.compile(
    r'(<span class="lx-abbr"[^>]*>\s*=\s*</span>\s*)sq\.', re.I)
PTR_HEAD = re.compile(
    r'^(?:(?:[A-Za-z][A-Za-z]*\.|and|poet\.?|late|form|contr\.?)\s+)*for\b'
    r'|v\.|vide\b|fem\. of|masc\. of|Dim\. of|neut\. of|'
    r'etym\. of|expl\. of|cj\. for|f\.\s?l\.|sine expl|late form\b'
    r'|^[A-Za-z]+\.?\s+forms? of\b'
    r'|^(?:\d+\s+)?(?:(?:sg|pl|pf|aor|impf|fut|pres|Pass|Med|Act|imper)\.?\s+)+of\b'
    r'|^of\b',
    re.I)
GREEK_RUN = re.compile(
    r"[Ͱ-Ͽἀ-῿](?:[Ͱ-Ͽἀ-῿̀-ͯ\u0300-\u036f]|[ʼ'’])*"
)
SUBLEM_SPLIT = re.compile(
    r'(?=<b class="lx-orth"[^>]*>[^<]*[··])|(?:[;,]|\s)\s*(?=v\.)')


def _tag_class(tag):
    m = re.search(r'class="([^"]+)"', tag)
    return m.group(1).split()[0] if m else ''


def _complete_el(h, i):
    m = re.match(r'<(\w+)([^>]*)>', h[i:])
    if not m:
        return None
    name = m.group(1)
    if m.group(0).endswith('/>') or name in ('br', 'img'):
        return i + len(m.group(0))
    depth, j = 1, i + len(m.group(0))
    for t in re.finditer(r'</?\w+[^>]*>', h[j:]):
        raw = t.group(0)
        if raw.startswith('</'):
            depth -= 1
            if depth == 0:
                return j + t.end()
        elif not raw.endswith('/>'):
            nm = re.match(r'<(\w+)', raw)
            if nm and nm.group(1) not in ('br', 'img'):
                depth += 1
    return len(h)


def _tokens(h):
    i = 0
    while i < len(h):
        if h[i] == '<':
            end = _complete_el(h, i) or i + 1
            yield 'tag', h[i:end], i, end
            i = end
        else:
            j = h.find('<', i)
            if j < 0:
                j = len(h)
            yield 'text', h[i:j], i, j
            i = j


def _strip_citations(html):
    """Remove citation elements without leaving nested-span debris.

    A prose author is not a citation element. It keeps the lx-author
    class so entrylib's segmentation still counts it as a reference and
    cuts where it always did, and _tag_class reads only the first token,
    so it arrives here looking exactly like one. Unwrap it instead of
    dropping it: the words are the sentence — ὁ's "the oldest and in
    Hom. the commonest sense" — and this function is what removed them.
    """
    out = []
    depth = 0          # open parentheses in the prose itself
    for kind, frag, _a, _b in _tokens(html):
        if kind == 'tag':
            cls = _tag_class(frag)
            if cls in {'lx-bibl', 'lx-cit', 'lx-author', 'lx-date',
                       'lx-placeName'}:
                if 'lx-prose' in frag:
                    out.append(re.sub(r'<[^>]+>', '', frag))
                elif cls == 'lx-cit' and depth > 0 and _cit_runs_past_paren(frag, depth):
                    # A citation opened inside the definition's own
                    # parenthesis is prose (entrylib._zone_cut), and
                    # Perseus closes such a citation late: πολύστιος
                    # reads "(στία) with many small stones, pebbly, Call.
                    # Jov. 26" with the gloss INSIDE the lx-cit, after
                    # the bracket has closed. Drop the quotation and the
                    # reference, keep the words. A citation that closes
                    # before the bracket does is an example, and its
                    # italic is that example's translation (ἀτρεκής).
                    out.append(_cit_prose(frag))
                continue
        else:
            depth += frag.count('(') - frag.count(')')
            depth = max(depth, 0)
        out.append(frag)
    return ''.join(out)


def _cit_runs_past_paren(el, depth):
    """True when the bracket open at this citation closes inside it,
    before a plain italic the citation still holds."""
    m = re.search(r'<i>(?!</i>)', el)
    if not m:
        return False
    # The citation's own text, not its quotation's: L&S aditio quotes
    # "v. Zumpt, § 681)," with the bracket inside the quote, and the
    # italic after it is the example's translation.
    before = L.text_of(_cit_prose(el[:m.start()]))
    return before.count(')') - before.count('(') >= depth


def _cit_prose(el):
    """The wording of an lx-cit minus its quotation and reference."""
    inner = re.sub(r'^<span[^>]*>|</span>$', '', el)
    out = []
    for kind, frag, _a, _b in _tokens(inner):
        if kind == 'tag' and _tag_class(frag) in {
                'lx-quote', 'lx-bibl', 'lx-author', 'lx-date', 'lx-placeName'}:
            continue
        out.append(frag)
    return ''.join(out)


def _keep_quoted_forms(html):
    """A citation in the preamble quotes the form it attests.

    οὐσία opens "Ion. -ιη Hdt. 1.92, 6.86.αʹ, SIG 167.26 (Mylasa, iv B.
    C.)": the -ιη is the Ionic form and the rest is where it is found.
    Perseus wraps form and reference together in one lx-cit, so
    stripping citations took the form with them and the identity line
    read "Ion. 1.92" — the label with its form gone and the locus left
    behind. 627 Greek preambles carry the shape. Keep the quotation,
    drop the reference around it."""
    out = []
    for kind, frag, _a, _b in _tokens(html):
        if kind == 'tag' and _tag_class(frag) == 'lx-cit':
            q = L.first_element(frag, 'lx-quote')
            out.append(q[0] if q else frag)
            continue
        out.append(frag)
    return ''.join(out)


def _recover_sense_source(html):
    """Keep a short entry's definition when citations precede it.

    Proper-name entries put their main gloss between print separators;
    other entries keep all non-citation wording, including grammar notes.
    """
    mark = re.search(
        r':—\s*(?=(?:<i(?:\s+class="lx-title")?>|(?:a|an|the)\b))',
        html, re.I)
    if mark:
        end = html.find(':—', mark.end())
        return html[mark.end():end if end >= 0 else len(html)]
    clean = _clean_recovered_source(_strip_citations(html))
    plain = re.sub(r'\s+', ' ', L.text_of(clean))
    if re.search(r'<i>(?!\s*</i>).*?</i>', clean, re.S):
        return clean
    if re.search(
            r'\b(?:a Macedonian month|prop\. oxytone|'
            r'and Aeol\. for|of unknown signif\.|the signif\. of this word|'
            r'more correctly written|correct derivation)', plain, re.I):
        return clean
    return ''


def _clean_recovered_source(html):
    """Remove apparatus left bare when recovery strips its citations."""
    html = STRIP_WORK.sub('', html)
    html = re.sub(r'\(\s*,?\s*\)', '', html)
    html = re.sub(r'^\s*(?:Müll\.\s*)?[\]),;:]+\s*', '', html)
    html = re.sub(r'^\s*Müll\.\s*', '', html)
    html = re.sub(r'\[[^]]*\]\s*ap\.?', '', html, flags=re.I)
    html = re.sub(r'(?<![\w])\d+(?:\(\d+\))?(?:\.\d+)+(?!\w)', '', html)
    html = re.sub(r'\(\d+\)(?:\.\d+)*', '', html)
    html = re.sub(r'[,;]\s*al\.?\s*(?=[;,]|$)', '', html, flags=re.I)
    html = re.sub(r'\bcf\.\s*(?=[,;.)]|$)', '', html, flags=re.I)
    html = re.sub(r'(?:[,;]\s*)*(?:(?:ap|cf|al|etc)\.?\s*[,;.\s]*)+$',
                  '', html, flags=re.I)
    html = re.sub(r'\(\s*,?\s*\)', '', html)
    html = re.sub(r'\s+,', ',', html)
    html = re.sub(r',\s*,+', ',', html)
    html = re.sub(r',\s*\.', '', html)
    html = re.sub(r'^\s*[,;:]+\s*', '', html)
    return html.strip()


def _is_qty(frag):
    if 'lx-foreign' not in frag and 'lx-pron' not in frag:
        return False
    t = L.text_of(frag).strip('[] ')
    return bool(QTY_RE.match(t))


def split_short(html):
    """Cut an unnumbered preamble into morphology vs the rest.

    Identity keeps inflection, gender, variants, quantity. Dialect-for,
    v., =, and English glosses start the meaning."""
    pre, _ = L.split_preamble(html)
    hm = re.search(r'<b class="lx-head"[^>]*>.*?</b>', pre, re.S)
    lemma = L.text_of(hm.group(0)) if hm else ''
    rest = pre[hm.end():] if hm else pre
    rest = _drop_print_homonym(rest)
    cut = None
    pending_form = None
    skip_sc = False
    for kind, frag, a, b in _tokens(rest):
        if skip_sc:
            if kind != 'text' or ')' not in frag:
                continue
            skip_sc = False
            off = frag.find(')') + 1
            a = a + off
            frag = frag[off:]
        if kind == 'text':
            t = frag.strip()
            if not t or SKIP_TXT.match(t) or re.fullmatch(r'[\[\](),;:\s]+', t):
                continue
            if re.match(r'^\(sc\.?', t, re.I):
                skip_sc = ')' not in frag
                continue
            if pending_form is not None and re.match(r'^of\b', t, re.I):
                cut = pending_form
                break
            pending_form = None
            if PTR_TXT.match(t) or t.startswith('='):
                cut = a
                break
            cut = a
            break
        cls = _tag_class(frag)
        if cls in IDENT_CLS or _is_qty(frag):
            pending_form = None
            continue
        if cls in FORM_OF_CLS:
            after = L.text_of(rest[b:])[:48]
            gram_txt = L.text_of(frag)
            if (re.match(r'\s*(and\s+\S+\s+)?for\b', after, re.I)
                    or re.match(r'\s*(sq|foreg|seq)\b', after, re.I)
                    or re.search(r'\b(?:for|of)\b', gram_txt)):
                cut = a if pending_form is None else pending_form
                break
            if pending_form is None:
                pending_form = a
            continue
        pending_form = None
        if 'lx-foreign' in frag:
            cut = a
            break
        if re.search(r'lx-(?:bibl|cit|author)|lx-title|lx-abbr', frag):
            cut = a
            break
        t = L.text_of(frag).strip()
        if t and not SKIP_TXT.match(t):
            cut = a
            break
    if cut is None:
        ident_html, meaning = rest, ''
    else:
        ident_html, meaning = rest[:cut], rest[cut:]
    gen = _head_gender(ident_html)
    gender = L.text_of(gen[0]) if gen else ''
    ident = L.text_of(ident_html)
    ident = re.sub(r'\s+', ' ', ident).strip(' ,;:')
    ident = re.sub(r'\s+,', ',', ident)
    if gender:
        ident = re.sub(r'(^|,\s*)' + re.escape(gender) + r'(?=\s|,|$)', r'\1', ident)
        ident = ident.strip(' ,;:')
    ident = re.sub(r'\s+,', ',', ident).strip(' ,;:')
    ident = _drop_unmatched_parens(ident).rstrip()
    if not _has_words(ident):
        ident = ''
    meaning = meaning.strip()
    meaning = re.sub(r'^[\s,;:]+', '', meaning)
    if gender and _latin_verb_opening(html):
        gender = ''
    return lemma, gender, ident, meaning


def neighbour_head(word, delta):
    recs = lex_get(word)
    if not recs:
        return None
    head = recs[0].get('head') or word
    folded = fold(head)
    bucket = extract.load_bucket(DATASET, extract.bucket_name(folded)) or {}
    keys = list(bucket)
    try:
        i = keys.index(folded)
    except ValueError:
        return None
    j = i + delta
    if 0 <= j < len(keys) and bucket[keys[j]]:
        return bucket[keys[j]][0].get('head')
    return None


def resolve_rel(html, word):
    """sq./foreg. name a print neighbour. Substitute that lemma, once.

    No neighbour in the pack → leave the print's word. Not a link."""
    if REL_SQ.search(html):
        nxt = neighbour_head(word, 1)
        if nxt:
            html = REL_SQ.sub(
                lambda m: m.group(1) + _rel_lemma(nxt), html, count=1)
    elif REL_SQ_MARKUP.search(html):
        nxt = neighbour_head(word, 1)
        if nxt:
            html = REL_SQ_MARKUP.sub(
                lambda m: m.group(1) + _rel_lemma(nxt), html, count=1)
    if REL_FORE.search(html):
        prev = neighbour_head(word, -1)
        if prev:
            html = REL_FORE.sub(
                lambda m: m.group(1) + _rel_lemma(prev), html, count=1)
    return html


def _rel_lemma(head):
    """The neighbour's headword, in this pack's language — a Latin lemma
    tagged lang="grc" sets in the Greek face."""
    return (f'<span class="lx-foreign" lang="{LANG}">'
            f'{htmllib.escape(head)}</span>')


def wrap_gr(text):
    out, last = [], 0
    for m in GREEK_RUN.finditer(text):
        out.append(htmllib.escape(text[last:m.start()]))
        out.append(f'<span lang="grc">{htmllib.escape(m.group(0))}</span>')
        last = m.end()
    out.append(htmllib.escape(text[last:]))
    return ''.join(out)


# A pointer that names no target: the linking abbreviation alone. Tested
# against the WHOLE pointer, never a fragment of one — ptr_display runs
# per piece and the pieces are joined, so dropping a bare "v." there took
# the tail off L&S culmen's "contr. form of columen, q. v." and left it
# pointing at "q."
_EMPTY_PTR = re.compile(r'(?:v|vide|cf|of|q\.\s*v|s\.\s*v)\.?', re.I)


def ptr_display(html):
    """Pointer line: print's wording, Greek in spans, cites stripped."""
    html = _strip_citations(html)
    html = STRIP_WORK.sub('', html)
    # "(q. v.)" tells the reader to look the target up; on a pointer
    # line that is what the line already is (ἀχέω C shipped "Dor. for
    # ἠχέω v.").
    html = re.sub(r'\s*\(\s*qq?\.\s*v\.\s*\)', '', html)
    html = re.sub(r'<span class="lx-author"[^>]*>.*?</span>', '', html)
    html = re.sub(r'<span class="lx-date"[^>]*>.*?</span>', '', html)
    html = re.sub(r'<span class="lx-placeName"[^>]*>.*?</span>', '', html)
    stop = re.search(r'<span class="lx-(?:bibl|cit|date|placeName)|<i class="lx-title"', html)
    if stop:
        html = html[:stop.start()]
    parts, pos = [], 0
    for m in re.finditer(
            r'<span class="lx-foreign"[^>]*>.*?</span>|'
            r'<b class="lx-orth"[^>]*>.*?</b>',
            html, re.S):
        pre = L.text_of(html[pos:m.start()])
        if pre.strip():
            parts.append(wrap_gr(re.sub(r'\s+', ' ', pre).strip()))
        g = L.text_of(m.group(0)).strip(' ,;:')
        if g:
            if _GREEK_CH.search(g):
                parts.append(wrap_gr(g))
            elif DATASET.startswith('grc'):
                parts.append(f'<span lang="la">{htmllib.escape(g)}</span>')
            else:
                parts.append(htmllib.escape(g))
        pos = m.end()
    tail = L.text_of(html[pos:])
    if tail.strip():
        parts.append(wrap_gr(re.sub(r'\s+', ' ', tail).strip()))
    s = ' '.join(p for p in parts if p)
    s = re.sub(r'\s+', ' ', s)
    s = re.sub(r'\s+([.,;:)])', r'\1', s)
    s = re.sub(r'\s*\(\s*[,;·]*\s*\)', '', s)    # the shell of a stripped aside
    s = re.sub(r'\s+\.$', '', s)               # a period left standing alone
    s = re.sub(r'\(\s+', '(', s)   # author stripped from inside a parenthesis
    s = re.sub(r'(</span>)\s*[\d()].*$', r'\1', s)
    # A locus token anywhere — "a274", "11(4).1064a1", "(2).6.40" — ends
    # the pointer; a bare division number ("= ἀραγμός 2") is not one.
    s = re.sub(r'(</span>[^<]*?)[,;:]?\s+(?:al\.,?\s+)?(?=\S*\d)\S*(?:[()a-z.]\d|\d[()a-z]).*$',
               r'\1', s)
    # And a bare number straight after the target — μά (B) "Thess. for
    # δέ, 461; also found…" — but not a division number ("= ἀραγμός 2").
    s = re.sub(r'(</span>)[,;:]?\s+(?:al\.,?\s+)?(?!\d{1,2}\s*$)\d\S*.*$', r'\1', s)
    # A small-roman volume with its page ("i 27"), and the "al." that
    # followed a stripped reference ("fem. of ἄρχων, al."). The shell
    # of a stripped aside can leave two periods in front of these.
    s = re.sub(r'\.{2,}$', '.', s)
    s = re.sub(r'\s+[ivx]{1,4}\s+\d+[a-z]?\.?$', '', s)
    s = re.sub(r'\s+\d[\d.]*$', '', s)
    s = re.sub(r'[,;]\s*(?:[A-Z][\w.]*\s+)?(?:al|etc|cf|sq|ap)\.*\s*$', '', s)
    # Citations were stripped upstream; their bare numbers and the commas
    # that held them are debris ("…only twice),, 14.2,,,,,, 6.38: impf.,").
    s = re.sub(r'(?:\s*,)+', ',', s)
    s = re.sub(r'(?:,\s*\d[\d.]*)+\s*(?::[^,]*)?\s*$', '', s)
    s = re.sub(r',(\S)', r', \1', s)
    s = re.sub(r'[,;]\s*\.$', '', s)
    s = _drop_unmatched_parens(s)
    s = re.sub(r'\.{2,}$', '.', s)
    # The sentence's final period, behind a Greek word or a bracket; an
    # abbreviation keeps its own ("Dim. of ἀκρόπους", not "…οus.").
    s = re.sub(r'(</span>|\))\.$', r'\1', s)
    s = s.strip(' ,;:')
    return s


_CROSS_REFERENCE = re.compile(
    r'(?:^|[,;:(]\s*)(?P<ref>'
    r'(?:fem\.|masc\.|neut\.|Dim\.)\s+of\b.*|'
    r'(?:v\.|vide|cf\.)\s+.*|'
    r'(?:poet\.|late form|cj\.|worse forms?)\s+(?:of|for)\b.*|'
    r'(?:etym\.|expl\.)\s+of\b.*|'
    r'(?:f\.\s*l\.|sine expl\.|but see|name of|title of)(?:\s.*)?)'
    r'$', re.I)


def cross_reference_display(html):
    """Return only a true cross-reference; drop a leading locus or aside."""
    display = ptr_display(html)
    if PTR_HEAD.match(L.text_of(display)):
        return display
    m = _CROSS_REFERENCE.search(display)
    if not m:
        return ''
    ref = m.group('ref').strip(' ,;:')
    # A ref matched behind an opening paren carries its mate's tail.
    if ref.endswith(')') and '(' not in ref:
        ref = ref[:-1].strip(' ,;:')
    return ref


_EQUATION_PTR = re.compile(r'(?:^|[(),;:?]\s*)((?:=|Subst\.)\s+\S.*)$')


def equation_pointer(html):
    """A resolved equation (= φουλβῖνον) or derived-form note (Subst.
    ἑρκοθηρευτής) is a pointer even without v./cf. wording — the wording
    test must not delete an entry's only content. Leading print debris
    ("(?),") is stepped over; a target lemma is required."""
    text = L.text_of(ptr_display(html)).strip(' ,;:')
    m = _EQUATION_PTR.search(text)
    if not m:
        return ''
    ref = m.group(1).strip(' ,;:')
    if ref.endswith(')') and '(' not in ref:
        ref = ref[:-1].strip(' ,;:')
    return wrap_gr(ref) if first_greek_lemma(ref) else ''


def _work_only(title):
    """LSJ's own tables list this abbreviation as a work and never as an
    author or a publication.

    A work is not an author, and a chip that shows one tells the reader
    something false: ἀέροψ cites "Ar. Av. 1354" and shipped the chips
    "Ar., Av."; δίχρως "Arist., HA"; ἀδίαρθρος "Thphr., HP"; ἄνθυλλον
    "Dsc., Plin., HN". 2,198 chips over 294 abbreviations, every one of
    them a title the front matter prints under an author.

    A title LSJ gives no author (AP, h.Merc., Ev.Matt., IG, POxy.) is not
    in the works table and stays the chip it was."""
    ab = abbrevs()
    t = title.strip()
    bare = t.rstrip('.')
    for key in ('authors', 'publications'):
        table = ab.get(key) or {}
        if t in table or bare in table or bare + '.' in table:
            return False
    return any(t in works or bare in works or bare + '.' in works
               for works in (ab.get('works') or {}).values())


def _print_work_titles(raw, head=''):
    """Work-only chips the same source record identifies as titles."""
    titles = {L.text_of(m.group(0)).strip() for m in
              re.finditer(r'<i class="lx-title"[^>]*>.*?</i>', raw, re.S)}
    authors = {L.text_of(m.group(0)).strip() for m in
               re.finditer(r'<span class="lx-author"[^>]*>.*?</span>', raw, re.S)}
    remove = {tok for tok in titles - authors if _work_only(tok)}
    prefix = DATASET.split('-', 1)[0]
    remove.update(tok for dataset, named_head, tok in _UNMARKED_WORK_TITLES
                  if dataset == prefix and named_head == head)
    return remove


def _drop_print_work_titles(out, raw, head):
    """Remove print-identified work titles from entry and row chips."""
    remove = _print_work_titles(raw, head)
    if remove:
        out['authors'] = [tok for tok in out.get('authors') or []
                          if tok not in remove]
        for row in out.get('rows') or []:
            row['authors'] = [tok for tok in row.get('authors') or []
                              if tok not in remove]
    return out


def _work_owners(title):
    """The authors the tables give this work to."""
    if not _WORK_OWNERS:
        for author, works in (abbrevs().get('works') or {}).items():
            for work in works or ():
                _WORK_OWNERS.setdefault(work.strip().rstrip('.'), set()).add(author)
        _WORK_OWNERS.setdefault('', set())
    return _WORK_OWNERS.get((title or '').strip().rstrip('.')) or set()


def drop_work_chips(tokens):
    """Chips that name a work rather than an author, where the tables can
    say so without guessing.

    Two cases are certain. The author who owns the work is a chip on the
    same row, so the work is his and the reader has him already: ἄγναφος
    read "Ev.Matt., Marc., PLond." and L&S ab "Plaut., Cic., Ov., Planc.,
    Liv., Tib.", Cicero beside his own Pro Plancio. And the tables give
    the abbreviation to more than one author, so it identifies nobody:
    "Fr." is Fragmenta and 24 authors have one.

    What is left standing is a work the tables give to exactly one author
    and no chip on the row claims. That is where the tables' own gaps
    bite: "Al." is Nicander's Alexipharmaca in the works list, and LSJ
    cites "Al. Le. 11.19" for a reading in Leviticus, so dropping the
    chip on the table's word would lose what the print names. 166 chips
    stay for that reason, 58 of them "Al.".
    """
    have = set(tokens)
    out = []
    for tok in tokens:
        if _work_only(tok):
            owners = _work_owners(tok)
            if (owners & have) or len(owners) > 1:
                continue
        out.append(tok)
    return out


def short_authors(html):
    """Authors and work-titles that sit loose in a short preamble."""
    tokens, seen = [], set()
    for tok in unique_authors(html):
        if tok not in seen:
            seen.add(tok)
            tokens.append(tok)
    for m in re.finditer(r'<span class="lx-author"[^>]*>([^<]+)', html):
        tok = m.group(1).strip()
        if tok and tok not in seen:
            seen.add(tok)
            tokens.append(tok)
    for m in re.finditer(r'<i class="lx-title">([^<]+)</i>', html):
        tok = m.group(1).strip()
        if tok and tok not in seen and not _work_only(tok):
            seen.add(tok)
            tokens.append(tok)
    tokens = drop_work_chips(tokens)
    if len(tokens) > 6:
        return tokens[:6] + ['+']
    return tokens


def citation_tokens(html):
    """Print citations as separate abbreviation tokens, loci included."""
    found = []
    covered = []
    prev = last_raw = ''
    for m in re.finditer(r'<span class="lx-bibl"', html):
        if any(a <= m.start() < b for a, b in covered):
            continue        # nested inside one already read
        end = _complete_el(html, m.start())
        if not end:
            continue
        block = html[m.start():end]
        token, prev, last_raw = cite_from(block, prev, last_raw)
        token = re.sub(r'\s+', ' ', token).strip(' ,;:')
        if token:
            found.append((m.start(), token))
        covered.append((m.start(), end))

    anchor = re.compile(
        r'<span class="lx-author"[^>]*>|<i class="lx-title"[^>]*>', re.I)
    for m in anchor.finditer(html):
        if any(a <= m.start() < b for a, b in covered):
            continue
        end = _complete_el(html, m.start())
        if not end:
            continue
        parts = [L.text_of(html[m.start():end]).strip()]
        pos = end
        while True:
            ws = re.match(r'\s*', html[pos:])
            pos += ws.end()
            title = re.match(r'<i class="lx-title"[^>]*>', html[pos:], re.I)
            if title:
                title_end = _complete_el(html, pos)
                if not title_end:
                    break
                parts.append(L.text_of(html[pos:title_end]).strip())
                covered.append((pos, title_end))
                pos = title_end
                continue
            text_end = html.find('<', pos)
            text_end = len(html) if text_end < 0 else text_end
            plain = html[pos:text_end]
            stop = re.search(r'[,;:—]', plain)
            plain = plain[:stop.start()] if stop else plain
            extra = re.sub(r'\s+', ' ', L.text_of(plain)).strip()
            if (re.search(r'\d', extra)
                    or re.fullmatch(r'(?:l\.c\.|s\.v\.|ib\.)', extra, re.I)):
                parts.append(extra)
            break
        token = ' '.join(p for p in parts if p).strip(' ,;:(')
        if token:
            found.append((m.start(), token))

    out = []
    for _pos, token in sorted(found):
        if token not in out:
            out.append(token)
    return out[:6] + (['+'] if len(out) > 6 else [])


def classify_short(html):
    t = L.text_of(html).strip(' ,;:')
    if not t:
        return 'empty'
    if PTR_HEAD.match(t) or re.match(r'^\(\?\),?\s*=', t):
        return 'ptr'
    # A pointer behind the entry's citation: L&S salisatores "Paul. ex
    # Fest. p. 326 Müll.; v. Theocriti Idyll. 3, 37".
    if PTR_HEAD.match(L.text_of(_strip_citations(html)).strip(' ,;:')):
        return 'ptr'
    stripped = _strip_citations(html)
    stripped = STRIP_WORK.sub('', stripped)
    stripped = re.sub(r'<span class="lx-author"[^>]*>.*?</span>', '', stripped)
    leftover = L.text_of(stripped).strip(' ,;:.')
    leftover = re.sub(r'\b(?:al|etc|cf)\.?\b', '', leftover, flags=re.I)
    leftover = leftover.strip(' ,;:.()')
    if not leftover:
        return 'cite'
    if leftover.startswith('=') or (html.lstrip().startswith('<span class="lx-foreign"')
                                    and not re.match(r'^[A-Za-z]', leftover)):
        return 'eq'
    if re.match(r'^=', t) or t.startswith('='):
        return 'eq'
    if re.search(r'[A-Za-z]{3,}', leftover):
        return 'sense'
    if GREEK_RUN.search(leftover):
        return 'eq'
    return 'cite'


def split_chunks(meaning):
    if not meaning:
        return []
    # "(q. v.)" says to look the target up, which is what a pointer or
    # equation line already does; left in, the sub-lemma split cut it at
    # "v." and ἀχέω (C) shipped a second pointer reading "v.".
    meaning = re.sub(r'\s*\(\s*qq?\.\s*v\.\s*\)', '', meaning)
    meaning = re.sub(r',?\s*\bqq?\.\s*v\.(?=\s|$|<)', '', meaning)
    structural = re.split(r'\s*:—\s*', meaning)
    parts = [p for chunk in structural for p in SUBLEM_SPLIT.split(chunk)
             if p and p.strip()]
    return parts or [meaning]


ARTICLES = {'ὁ', 'ἡ', 'τό', 'οἱ', 'αἱ', 'τά', 'τόν', 'τήν', 'τῆς', 'τοῦ', 'τῷ', 'τῇ'}
_GLOSS = {}
_LSJ_REC = {}


def first_greek_lemma(text):
    for tok in GREEK_RUN.findall(text or ''):
        t = tok.strip('.,;:··')
        if t and t not in ARTICLES:
            return t
    return None


def synonym_targets(text):
    """Single-lemma Greek glosses (optionally comma-separated). Empty if a phrase."""
    t = re.sub(r'\s*\bcf\..*$', '', text or '', flags=re.I)
    t = t.strip(' =,;:.')
    if not t:
        return []
    out = []
    for part in re.split(r'[,;]', t):
        toks = [x.strip('.,;:··') for x in GREEK_RUN.findall(part)
                if x.strip('.,;:··') not in ARTICLES]
        leftover = GREEK_RUN.sub('', part)
        leftover = re.sub(r'[\s,;=:.··()]+', '', leftover)
        if len(toks) != 1 or leftover:
            return []
        out.append(toks[0])
    return out


def lsj_record(word):
    if word in _LSJ_REC:
        return _LSJ_REC[word]
    recs = lex_get(word)
    if recs:
        _LSJ_REC[word] = recs[0]
        return recs[0]
    surface = fold(word)
    # The tie-break must be total: lemmas_of is a frozenset, and letting
    # its iteration order decide made the borrowed gloss depend on the
    # process's hash seed — ἔκειεν borrowed κεντέω's gloss in one build
    # and κεντάω's nothing in the next.
    cands = sorted((f for f in lemmas_of(word) if f), key=lambda f: (
        0 if surface.startswith(f) or f.startswith(surface[: max(3, len(f) - 1)]) else 1,
        abs(len(f) - len(surface)),
        f,
    ))
    fallback = None
    for folded in cands:
        bucket = extract.load_bucket(DATASET, extract.bucket_name(folded)) or {}
        recs = bucket.get(folded)
        if not recs:
            continue
        # Prefer a record with senses of its own: a pointer entry
        # (κεντάω "= κεντέω") has nothing to lend a borrower.
        if L.senses(recs[0].get('html') or ''):
            _LSJ_REC[word] = recs[0]
            return recs[0]
        if fallback is None:
            fallback = recs[0]
    _LSJ_REC[word] = fallback
    return fallback
    return None


# Print abbreviations whose period must not end a borrowed gloss's
# clause. Case-sensitive: "Pass." the voice, not "pass" the verb.
_CLIP_ABBREV = re.compile(
    r'(?:esp|opp|usu|freq|prob|dub|viz|Adj|Adv|Sup|Dim|Comp|Subst|'
    r'fem|masc|neut|verb|Ion|Att|Dor|Aeol|Ep|Lat|Pass|Med|Act|'
    r'dat|gen|acc|nom|voc|aor|impf|inf|part|opt|subj|imper|pf|fut)$')


def _clip_gloss(t):
    t = t or ''
    t = re.sub(r'^=\s*' + GREEK_RUN.pattern + r'[^A-Za-z]*', '', t)
    # Clip at the first clause end — but a period closing a 1–2 letter
    # abbreviation is punctuation inside the clause: "go up, mount,
    # c. acc. loci" clips to "go up, mount", not "go up, mount, c",
    # and "long for, i.e. …" to "long for", not "long for, i".
    cut = len(t)
    m = re.search(r',\s*[A-Za-z]{1,2}\.', t)
    if m:
        cut = m.start()
    for m in re.finditer(r'[.;]', t[:cut]):
        if m.group() == '.':
            w = re.search(r'([A-Za-z]+)$', t[:m.start()])
            # A period after a short token or a known print abbreviation
            # is punctuation inside the clause ("verb. Adj. of ἀγκυλέομαι"
            # must not clip to "verb").
            if w and (len(w.group(1)) <= 2 or _CLIP_ABBREV.match(w.group(1))):
                continue
        cut = m.start()
        break
    t = t[:cut]
    # A cut at a longer abbreviation's period leaves its stem dangling
    # ("…disturbance, esp" / "…friendship, usu").
    t = re.sub(r',\s*(?:esp|opp|cf|viz|sc|usu|freq|etc|prob|dub|al|ib)$', '', t)
    t = re.sub(r'\s+', ' ', t).strip(' ,;:=')
    words = t.split()
    if len(words) > 8:
        t = ' '.join(words[:8])
    return t or None


def first_gloss(word, hops=0):
    """First English sense of an LSJ lemma. Follow v./= once; do not invent."""
    if not word or hops > 2:
        return None
    if word in _GLOSS:
        return _GLOSS[word]
    _GLOSS[word] = None
    rec = lsj_record(word)
    if not rec:
        return None
    # Use the same normalized source that model() uses before borrowing a
    # gloss from this entry.
    html = resolve_rel(
        mark_prose_authors(_source_editorial_angles(rec['html'])), word)
    ss = L.senses(html)
    if ss:
        zone, _ = L.defzone(ss[0][1])
        eng, ill = split_sense(zone)
        # A bold orthography after the first cue opens a cross-entry block,
        # not a longer gloss (καταστερισμός → Καταστερισμοί, title of ...).
        eng = re.split(r'(?=<b class="lx-orth")', eng, maxsplit=1)[0]
        t = L.text_of(eng).strip(' ,;:')
        # The print's aside is not the gloss, and its Latin letters are
        # not English: φύος reads "= φύτευμα (φυός cod.)", and reading
        # the bracket as a definition gave every entry pointing at it a
        # gloss of "cod". Judge, and follow, the sentence outside the
        # brackets; fall back to the whole where nothing is left.
        outside = re.sub(r'\([^()]*\)', ' ', t).strip(' ,;:') or t
        if (outside and outside not in ('=',) and not re.match(r'^=\s*$', outside)
                and re.search(r'[A-Za-z]{3,}', outside)):
            _GLOSS[word] = _clip_gloss(outside)
            return _GLOSS[word]
        bare = re.sub(r'\([^()]*\)', ' ', L.text_of(zone) + ' ' + L.text_of(ill))
        tgt = first_greek_lemma(bare) or first_greek_lemma(L.text_of(zone) + ' ' + L.text_of(ill))
        if tgt and tgt != word:
            _GLOSS[word] = first_gloss(tgt, hops + 1)
            return _GLOSS[word]
        return None
    _, _, _, meaning = split_short(html)
    if not meaning:
        return None
    kind = classify_short(meaning)
    if kind == 'sense':
        eng, _ = split_sense(meaning)
        _GLOSS[word] = _clip_gloss(L.text_of(eng).strip(' ,;:'))
        return _GLOSS[word]
    tgt = first_greek_lemma(L.text_of(meaning))
    if tgt and tgt != word:
        _GLOSS[word] = first_gloss(tgt, hops + 1)
        return _GLOSS[word]
    return None


def eq_zone(html):
    lead = ''
    rest = html
    orth = re.search(r'<b class="lx-orth"[^>]*>.*?</b>', html, re.S)
    if orth and orth.start() < 50:
        head = L.text_of(orth.group(0)).strip(' ··,;:')
        if head:
            lead = f'<b class="sublem" lang="grc">{htmllib.escape(head)}</b> '
        rest = html[orth.end():]
    rest = _strip_citations(rest)
    rest = STRIP_WORK.sub('', rest)
    rest = re.sub(r'<span class="lx-author"[^>]*>.*?</span>', '', rest)
    rest = strip_crossrefs(rest)
    # Separators only. The period is _tidy's business, and it knows the
    # difference between a sentence's and an abbreviation's: stripping it
    # here shipped ἀκτερής "= foreg., prob. in Hsch" and ἀβοαί "once in
    # Hom", where the print writes "Hsch." and "Hom."
    gloss = L.text_of(rest).strip(' ,;:')
    gloss = re.sub(r'\s+', ' ', gloss)
    # "q. v." loses its "v." to the link strip upstream and the bare "q."
    # was going with the period this used to take off the end.
    gloss = re.sub(r'[,;]?\s*\bq\.\s*$', '', gloss)
    gloss = re.sub(r'\s*\bcf\..*$', '', gloss, flags=re.I).strip(' ,;:')
    if not gloss and not lead:
        return ''
    body = wrap_gr(gloss) if gloss else ''
    mark = '<span class="eq-mark">=</span> '
    # A remainder of bare articles is the print's gender marker, not the
    # right side of an equation (σπληδώ, ἡ — never σπληδώ = ἡ).
    gloss_words = [w.strip('.,;:··') for w in gloss.split()] if gloss else []
    gloss_words = [w for w in gloss_words if w]
    only_articles = bool(gloss_words) and all(w in ARTICLES for w in gloss_words)
    if lead and not body:
        main = lead.strip()
    elif lead and only_articles:
        main = f'{lead.strip()}, {body}'
    elif lead:
        main = (lead + mark + body).strip()
    elif body and re.match(r'^[=＝]', gloss.strip()):
        main = body
    else:
        main = (mark + body).strip()
    extra = ''
    for tgt in synonym_targets(gloss):
        g = first_gloss(tgt)
        if g:
            g = re.sub(r',\s*,+', ',', g)
            extra = f' <span class="eq-def"><b class="cue">{htmllib.escape(g)}</b></span>'
            break
    return _tidy(main) + extra


# A short entry is one row, and the print's sentence often runs past
# the first citation: μόρφνος reads "epith. of an eagle, dub. sens.,
# Il. 24.316, Hes. Sc. 134: taken to be a Subst. by Arist. HA 618b25,
# Lyc. 838; described as a vulture by Suid." and shipped "epith. of an
# eagle, dub. sens." with the rest read as apparatus. 104 Greek entries
# lose a run of four or more words that way (of 16,067 short ones).
# The continuation is carried onto the row, citations stripped and the
# governed authors' names kept, because the row is the entry.
_GOVERNED_BIBL = re.compile(
    r'((?:^|[\s>(])(?:in|by|with|from|to|than|of|after|before|among|acc\. to)\s+)'
    r'(<span class="lx-bibl"(?![^>]*data-bare)[^>]*>\s*(?:<span class="lx-author">)?'
    r'(?:<i class="lx-title">)?([^<]+))', re.I)


def _keep_governed_bibls(html):
    """The name of a citation the sentence governs, put in front of it."""
    def repl(m):
        name = m.group(3).strip()
        if not re.match(r'[A-Z]', name):
            return m.group(0)
        return m.group(1) + name + ' ' + m.group(2)
    return _GOVERNED_BIBL.sub(repl, html)


def _short_tail(ev, examples):
    """A short entry's prose past its first citation, or ''."""
    if not ev or len(ev) > 6000:
        return ''
    html = _keep_governed_bibls(ev)
    # A quotation that became an example stays in the drawer.
    for ex in examples:
        gr = (ex.get('gr') or '').strip()
        if gr:
            html = html.replace(gr, '', 1)
    tail = _clean_recovered_source(_strip_citations(html))
    tail = re.sub(r'<span class="lx-(?:foreign|quote)"[^>]*>\s*</span>', '', tail)
    text = L.text_of(tail)
    # Words of three letters in either script, not abbreviations: θῦλαξ's
    # tail is "= προσκεφάλαιον, Hsch.; cited fr. Hom. by Poll." and the
    # equation is content.
    if len(re.findall(r"(?<![^\W\d_])[^\W\d_]{3,}(?![^\W\d_]|\.)", text)) < 2:
        return ''
    if re.search(r'\bAdv\.', text[:12]):
        return ''            # a sub-entry with its own gloss, not prose
    return _cue_italics(_strip_dangling(tail))


def make_row(word, lemma, html, kind):
    zone_src, ev = html, ''
    cut = L.first_citation(html)
    if cut is not None:
        zone_src, ev = html[:cut], html[cut:]
        zone_src = keep_governed_author(zone_src, ev)
        zone_src, ev = keep_governed_quote(zone_src, ev)
    trailing_form = re.match(
        r'^\s*<span class="lx-pos"[^>]*>\s*Adj\.?\s*</span>', html, re.I)
    if trailing_form:
        zone_src = _clean_recovered_source(_strip_citations(html))
        zone = _cue_italics(zone_src)
        ill = ''
    elif kind == 'eq':
        zone = eq_zone(zone_src)
        ill = ''
    else:
        eng, ill = split_sense(zone_src)
        zone = eng
        if not _has_words(zone) and cut is not None:
            # A fruitless recovery must not erase the row it was trying
            # to save — an empty zone_src also zeroes ill, which empties
            # the drawer and drops the entry's citations with it.
            _rs = _recover_sense_source(html)
            if _has_words(_rs):
                zone_src = _rs
                zone, ill = split_sense(zone_src)
    au = short_authors(html)
    examples = examples_of(ill, ev, L.text_of(zone), last_author(html[:cut] if cut is not None else ''))
    was_promoted = False
    if not _has_words(zone) and examples:
        # Short Hesychius-style entries often put the defining Greek in
        # the slot split_sense normally treats as an example. A bare dot,
        # dash, or bracket is not a sense line: lift the definition and
        # remove it from the drawer.
        promoted = defining_example_gloss(html)
        if _has_words(promoted):
            zone, ill, examples = wrap_gr(promoted), '', []
            was_promoted = True
    if was_promoted or (re.search(r'<span class="lx-abbr"[^>]*>=</span>', html)
                        and examples):
        au = citation_tokens(html)
    # Not onto a promoted Greek stub: βόλβιτον's "βόλιτον, -τος" plus
    # "worse forms of…" is not an entry, the print's cross-reference is,
    # and model_short reads that only from a row with no English.
    tail = '' if was_promoted else _short_tail(ev, examples)
    if not L.text_of(zone).strip() and DATASET.startswith('lat'):
        # An entry that opens on its citation and says its piece after
        # it: L&S librilla is "Paul. ex Fest. p. 116 Müll. (Scalig.
        # prefers to read librilia)", and the note is the row. Latin
        # only: LSJ's short entries of this shape are forms notes and
        # pointers, and the row model has nowhere for them.
        # A note of at least three words that is not a cross-reference:
        # "f.l. for ἐπικλινοπάλη" and "cf. the two foll. articles" are the
        # pointer line's, and "(not found)" is not a row.
        text = L.text_of(tail)
        if (not tail or len(re.findall(r'(?<![^\W\d_])[^\W\d_]{3,}(?![^\W\d_])', text)) < 3
                or PTR_HEAD.match(text)
                or re.match(r'(?:cf|v|vide|see|but see|i\.\s*q)\.?[:\s]', text, re.I)
                or re.match(r'\S+\s+(?:and\s+\S+\s+)?for\s', text)):
            return None
        zone, tail = _tidy(re.sub(r'^(\s*(?:<[^>]+>\s*)*)[(.]\s*', r'\1', tail)), ''
    elif not L.text_of(zone).strip():
        return None
    # Not when the zone already carries it: bovus's zone was recovered
    # from the whole entry, and the tail would say it twice.
    if tail and _has_words(zone) and L.text_of(tail)[:40].strip() not in L.text_of(zone):
        tail = re.sub(r'^(\s*(?:<[^>]+>\s*)*)\.\s*', r'\1', tail)
        joint = '' if re.match(r'\s*[:;,—]', L.text_of(tail)) else ';'
        zone = _tidy(zone.rstrip(' ,;:') + joint + ' ' + tail)
    return {
        'lv': 0,
        'n': '',
        'supplied': False,
        'banner': False,
        'bare': True,
        'zone': zone,
        'illust': '',
        'examples': examples,
        'plain': L.text_of(zone_src),
        'authors': au,
        'slug': fold(lemma or word),
        'lemma': lemma or word,
        'kids': False,
    }


LEXICAL_NOTE = re.compile(
    r'(?:\bstrengthd\.?|\bf\.?\s*l\.?|\bcodd?\.)', re.I)


def _note_text(html):
    """Visible non-citation wording from a short lexical note."""
    work = html
    for cls in ('lx-bibl', 'lx-cit'):
        for el in list(each_span(work, cls)):
            work = work.replace(el, '', 1)
    work = STRIP_WORK.sub('', work)
    work = re.sub(r'<span class="lx-(?:author|date|placeName)"[^>]*>.*?</span>',
                  '', work, flags=re.S)
    return re.sub(r'\s+', ' ', L.text_of(work)).strip(' ,;:')


def defining_example_gloss(html):
    """Definition to lift when a short row otherwise shows punctuation.

    Editorial notes such as ``f. l.`` need their full wording. In an
    equation, the first foreign run is the gloss, except when the print's
    middle dot starts a later run (περιλῆσαι).
    """
    plain = L.text_of(html)
    if LEXICAL_NOTE.search(plain):
        return _note_text(html)
    runs = [L.text_of(m.group(0)).strip(' ,;:')
            for m in GREEK_SPAN.finditer(html)]
    for run in runs:
        if re.match(r'^[··]', run):
            tail = re.split(r'[··]', run, maxsplit=1)[1].strip(' ,;:')
            if _has_words(tail):
                return tail
    return runs[0] if runs else ''


# A short entry's chips come from citation_tokens, which keeps each
# print citation whole ("Sor. 1.125", "Id. 3.5"), and its rows are the
# sub-lemmas of a Hesychius-style glossary: ἀγμείονες "βουβῶνες, Hsch.
# ἀγμή· ἑστία, Id. ἀγμηρόν· ἥσυχον, Id." — 838 rows shipped "Id." after
# the numbered entries had theirs resolved. The antecedent is the last
# author named in any row before, and the locus stays.
_SAME_LEAD = re.compile(r'^(?:Id|id|ib|ibid)\.?(?=\s|$)')
_AUTHOR_PART = re.compile(r'\s+(?=[\d(]|s\.\s*v\.|ap\.|l\.\s*c\.|ib\.)')


def resolve_same_authors(rows, last=''):
    for r in rows:
        out, seen = [], set()
        for tok in r.get('authors') or []:
            if _SAME_LEAD.match(tok):
                if not last:
                    continue
                tok = _SAME_LEAD.sub(last, tok, 1)
            elif tok != '+':
                head = _AUTHOR_PART.split(tok, 1)[0].strip()
                # The antecedent is an author, not an author and a work:
                # "Ar. Ra. 320" would otherwise make the next "Id. Pl.
                # 100" read "Ar. Ra. Pl. 100". Multi-token author names
                # are real ("Paul. ex Fest."), so a trailing token is
                # dropped only when what remains is itself an author the
                # table knows.
                head = re.sub(r'\s+p\.$', '', head)
                if ' ' in head:
                    stem = head.rsplit(' ', 1)[0].strip()
                    if stem in (abbrevs().get('authors') or {}):
                        head = stem
                last = head or last
            if tok not in seen:
                seen.add(tok)
                out.append(tok)
        if r.get('authors') is not None:
            r['authors'] = out
    return last


def model_short(word, html):
    lemma, gender, ident, meaning = split_short(html)
    meaning = resolve_rel(meaning, word)
    rows, ptrs = [], []
    for chunk in split_chunks(meaning):
        kind = classify_short(chunk)
        if kind in ('empty', 'cite'):
            continue
        if kind == 'ptr':
            use, extra = chunk, ''
            extra_at = re.search(r',\s*in\s+', chunk)
            if extra_at and re.match(r'^\s*(?:fem|masc|Dim)\. of', L.text_of(chunk), re.I):
                use, extra = chunk[:extra_at.start()], chunk[extra_at.start():]
            disp = cross_reference_display(use) or equation_pointer(use)
            if disp:
                ptrs.append(disp)
            if extra:
                extra = _strip_citations(extra)
                extra = re.sub(r'<i class="lx-title">.*?</i>.*', '', extra, flags=re.S)
                extra = re.sub(r'<span class="lx-date"[^>]*>.*?</span>', '', extra)
                note = L.text_of(extra).strip(' ,;:')
                note = re.sub(r'\s+', ' ', note)
                note = re.sub(r'[\d().,\s]+$', '', note).strip(' ,;:')
                if note:
                    ident = (ident + ', ' if ident else '') + note
            continue
        row = make_row(word, lemma, chunk, kind)
        if row:
            # Same debris rule as the sense loop: a zone that is only a
            # dangling "cf." (λααν) recovers the Greek from its own
            # evidence rather than shipping the link with nothing linked.
            z = _strip_dangling(row['zone'])
            if _has_words(L.text_of(z)):
                row['zone'] = z
            elif row.get('examples'):
                ex0 = row['examples'][0]
                row['zone'] = _tidy((z + ' ' + wrap_gr(ex0['gr'])).strip())
                row['examples'] = row['examples'][1:]
            rows.append(row)
    if rows and not ptrs and not any(
            re.search(r'[A-Za-z]{3,}', L.text_of(r['zone'])) for r in rows):
        # βόλβιτον: "…worse forms of βόλιτον, -τος, acc. to Phryn." The
        # promoted Greek "βόλιτον, -τος" is a stub; the print's own
        # sentence is a cross-reference, and that is the entry.
        xref = cross_reference_display(meaning)
        # Only a reference that IS the entry — not a "cf." beside an
        # equation the print wrote (ἀάβακτοι "= ἀβλαβεῖς … cf. ἀάβηκτον").
        if xref and re.match(r'(?:worse forms?|f\.\s?l\.|late form|poet\.|cj\.|'
                             r'Dor\.|Ion\.|Aeol\.|Att\.|Ep\.)', xref):
            ptrs, rows = [xref], []
    resolve_same_authors(rows, last_author(L.split_preamble(html)[0]))
    stub_authors = citation_tokens(html) if not rows else []
    if not rows and not ptrs:
        leftover = cross_reference_display(meaning)
        if leftover:
            ptrs.append(leftover)
        else:
            fallback = equation_pointer(meaning)
            if fallback:
                ptrs.append(fallback)
            else:
                # An entry that is nothing but citations. The authors are
                # the only thing the print gives; hand them over as data —
                # the renderer knows how to draw and expand them.
                stub_authors = citation_tokens(html)
    if stub_authors:
        holder = [{'authors': stub_authors}]
        resolve_same_authors(holder)
        stub_authors = holder[0]['authors']
    return {
        'lemma': lemma or word,
        'authors': stub_authors,
        'gender': gender,
        'ident': ident,
        'forms': [],
        'groups': [],
        'rows': rows,
        'ptr': ' '.join(ptrs),
        'n_senses': len(rows),
        'slug': fold(lemma or word),
    }



# Grammatical tags the print italicises alongside a real gloss.
GRAM_TAG = re.compile(
    r'^(?:conj|adj|adv|prep|pron|interj|num|part|particle|v\.\s*[and]\.?|v|'
    r'[mfn]|abl|gen|dat|acc|voc|nom|pl|sg|sup|comp|dim|freq|desid|inch|'
    r'Ion|Ep|Att|Dor|Aeol|poet|dub|prob|abs|impers|dep|trans|intr)\b\.?$',
    re.I)


# A single italic word can be a meaning ("and") or a grammatical term
# ("Supine", "pers."). Chasing the terms with a blocklist leaks; require
# the candidate to look like a gloss instead, and put nothing on the
# headword line unless it clearly is one.
# Only consulted for a ONE-WORD candidate, where the set of grammatical
# terms the print italicises is small and closed. A multi-word gloss is
# judged by its shape instead.
GRAM_WORD = re.compile(
    r'^(?:conj|adj|adv|prep|pron|interj|num|part|sup|comp|inf|imperf|praes|'
    r'fut|pass|act|dep|impers|dim|freq|desid|inch|sing|plur|masc|fem|neut|'
    r'abl|gen|dat|acc|voc|nom|temp|tempp|perf|perff|collat|contr|sync|'
    r'syncop|obsol|rar|poet|class|ante|post|gerund|supin|partic|verb|noun)$',
    re.I)
FUNCTION_GLOSS = re.compile(
    r'^(?:and|or|but|not|if|for|in|on|at|to|from|with|by|as|than|that|'
    r'when|where|while|so|yet|nor|both|even|also|indeed|truly|now|then)$',
    re.I)


def preamble_gloss(pre):
    """The basic meaning, when the print states it before the senses.

    L&S amo carries "to like, to love" in its preamble and then opens
    with the bare label "I. In gen."; et carries "and". Looking a word up
    should not require opening a sense to learn what it means. The words
    are the print's own and stay where the print put them — on the
    headword line, not promoted into a sense it never wrote."""
    text = L.text_of(pre)
    for m in re.finditer(r'<i>(.*?)</i>', pre, re.S):
        t = re.sub(r'\s+', ' ', L.text_of(m.group(1))).strip(' ,;:')
        # The closing period ends the sentence; it does not make "bring."
        # or "and." an abbreviation.
        t = re.sub(r'(?<=[A-Za-z])\.$', '', t)
        if not t or _GREEK_CH.search(t):
            continue
        # "(2d pers. ĕs …)": an aside about forms, not the meaning.
        before = L.text_of(pre[:m.start()])
        if before.count('(') > before.count(')'):
            continue
        # "good; comp." is a gloss plus a grammar note; "v. n. inch" is
        # only grammar notes. Cut at the first abbreviation and keep what
        # stands before it.
        kept = []
        for tok in t.split():
            if re.fullmatch(r"[A-Za-z]{1,5}\.", tok):
                break
            kept.append(tok)
        t = ' '.join(kept).strip(' ,;:.')
        # "good; comp" — a gloss with a grammar note tacked on. Clauses of
        # a gloss are separated by commas; a short tail after a semicolon
        # is an appendage.
        t = re.sub(r';\s*[A-Za-z]{1,6}$', '', t).strip(' ,;:')
        if not t:
            continue
        words = [w for w in re.findall(r"[A-Za-z][A-Za-z'-]*", t)]
        if len(words) >= 2:
            if len(t) > 60:
                t = t[:60].rsplit(' ', 1)[0]
            return t
        # A one-word gloss is lowercase ("good", "and"); L&S capitalises
        # the grammatical terms it italicises ("Supine").
        if len(words) == 1 and not GRAM_WORD.match(words[0]) and (
                FUNCTION_GLOSS.match(words[0])
                or (words[0].islower() and len(words[0]) >= 3)):
            return t
    return ''


# head_bits and form_bar both read the entry's preamble, so a dialect
# variant the print states once arrives twice: οὐσία shows "Dor. ἐσσία,
# ὠσία (qq. v.)" in its identity line and again in its forms bar, and
# 629 entries do the same (251 Greek, 378 Latin).
#
# The bar wins — John's call, and the evidence agrees with it. The bar
# is structured, label beside body, and the prose copy is the one that
# arrives damaged: οὐσία's identity line reads "Ion. 1.92, SIG 167.26
# (Mylasa)", the Ion. form itself stripped by the citation pass with
# only its locus left behind.
#
# Only what the bar actually carries is removed, matched on collapsed
# text so markup differences do not hide a duplicate, and only at the
# print's own boundaries at both ends of the run — which is what stops a
# short run matching inside a word. An eight-character floor used to
# stand in for the boundary check at the front, and it exempted the
# whole of Lewis & Short, whose bar body IS the inflection and is short
# by nature: "ātus, 1", "ĕre, 3", "a, um". So contollo printed "ĕre, 3"
# twice, one line above the other, and said nothing else; usitor
# repeated "ātus, 1" in front of the part the bar does not carry. 1,172
# Latin entries are that shape (John, 2026-09-08).
#
# LATIN ONLY, and deliberately. LSJ writes the dialect on the label
# rather than the form — "Att. fut. ἀποικιῶ" over a bar that carries
# the future unqualified — and the label goes with the form it labels,
# so a shorter floor costs 13 Greek entries the word that says WHICH
# dialect's future it is. Greek keeps its floor until the identity
# line itself is ruled on; that is the open question, not this.
# A grammatical label immediately before a form: "aor. 2", "pf. part.",
# "Ep. impf." Bounded to what actually labels a form, so ordinary prose
# before a variant is not swallowed with it.
# A label with no form after it: what a middle cut leaves behind.
_BARE_LABEL_END = re.compile(
    r'(?:^|[\s,;:·])(?:Ep|Ion|Att|Dor|Aeol|Boeot|Lacon|Cret|Trag|Com|Ep\.\s*and\s*Ion|'
    r'fut|aor|pf|plpf|impf|pres|inf|part|subj|opt|imper|med|pass|act|Med|Pass|Act|'
    r'Comp|Sup|Dim|Adv|contr|dat|gen|acc|nom|voc|sg|pl|dual)\.?$', re.I)


_FORM_LABEL = re.compile(
    r'(?:\b(?:aor|fut|pf|plpf|impf|part|inf|imper|subj|opt|pres|'
    r'nom|gen|dat|acc|voc|sg|pl|dual|Med|Pass|Act|Ep|Ion|Dor|Att|Aeol|'
    r'contr|poet|late|v|adj|adv)\.?\s*\d?\s*){1,3}$', re.I)


def ident_without_forms(ident, forms):
    """Drop from the identity line whatever the forms bar already shows."""
    if not ident or not forms:
        return ident
    flat = ' '.join(ident.split())
    for label, body in forms:
        for piece in re.split(r'·|;', L.text_of(body)):
            piece = ' '.join(piece.split()).strip(' ,;:·')
            anchored = False
            if DATASET.startswith('lat'):
                # Lewis and Short's parts are short (āvi, ātum): four is
                # the floor there (#41), and a piece at or above it
                # matches bare or with its label.
                if len(piece) < 4:
                    continue
                leads = [f'{label} {piece}'.strip(), piece]
            elif len(piece) < 8:
                # A short Greek form matches only with its label in front
                # (ἐγγραφή "Dor. ἐγγροφά"): bare, it could be anywhere.
                # And only where the line begins or after the print's
                # own punctuation: "Att. fut. ἀποικιῶ" over a bar that
                # says "fut. ἀποικιῶ" keeps the dialect the label carries.
                if len(piece) < 3 or not label:
                    continue
                leads = [f'{label} {piece}']
                anchored = True
            else:
                leads = [f'{label} {piece}'.strip(), piece]
            # The bar's body still ends on the governor the identity line
            # dropped (σύλληψις "σύλλαψις v.l. in"): match without it too.
            leads += [_STRANDED_IN.sub('', x).rstrip(' ,;:')
                      for x in leads if _STRANDED_IN.search(x)]
            for lead in leads:
                if not lead:
                    continue
                at = flat.find(lead)
                # The bar's bodies are truncated for display, so a piece
                # can be a PREFIX of what the identity line says. Removing
                # one then leaves the tail stranded — οὐσία lost
                # "(ὀντ-, part." and kept "of εἰμί sum)". Only cut where
                # the print itself ends the run.
                if at < 0:
                    continue
                # The print's own boundary in front of the run, or the
                # match is inside a word.
                if at > 0 and flat[at - 1] not in ' ,;:·(':
                    continue
                if anchored and at > 0 and flat[:at].rstrip().split(' ')[-1].endswith('.'):
                    # The word before the match is itself a label
                    # ("Att." in "Att. fut. ἀποικιῶ"): cutting after it
                    # strands the dialect. "ῆς, ἡ Dor. ἐγγροφά" is not.
                    continue
                # Inside brackets the print is writing a sentence, not
                # listing forms: καταγορεύω has "(aor. in use κατεῖπον,
                # hence καταγορεύῃ shd. be restored…)", and taking the
                # form out of it leaves "aor. in use hence". The bar may
                # duplicate it; the sentence has to stay whole.
                if flat.count('(', 0, at) > flat.count(')', 0, at):
                    continue
                end = at + len(lead)
                if end < len(flat) and flat[end] not in ' ,;:·':
                    continue
                if end < len(flat) and flat[end] == ' ' and \
                        not re.match(r'\s*(?:[,;:·]|$)', flat[end:]):
                    continue
                # Take the label with the form, or it is left standing
                # on its own: removing ὑπέχᾰνον from "aor. 2 ὑπέχᾰνον,
                # pf. ὑποκέχηνα" leaves "aor. 2 pf. ὑποκέχηνα", which
                # reads as one label for another form's word. The bar's
                # label and the line's are not always spelled the same
                # ("aor." against "aor. 2"), so the line's own is matched
                # here rather than the bar's.
                head_m = _FORM_LABEL.search(flat[:at])
                start = head_m.start() if head_m else at
                # Cutting from the middle of a chain rewrites the labels
                # that survive. ἀγγέλλω reads "Ep. and Ion. fut.
                # ἀγγελέω, Att. ἀγγελῶ", and taking the Ionic future out
                # left "Ep. and Att. ἀγγελῶ", which says the Epic future
                # is ἀγγελῶ; ἀφύσσω ran a Doric future straight into an
                # Epic aorist. A cut whose left side ends on a
                # conjunction or on a label with no form of its own is
                # refused; the bar shows the form either way.
                before = flat[:start].rstrip(' ,;:·')
                if re.search(r'\b(?:and|or)$', before) or _BARE_LABEL_END.search(before):
                    continue
                # And only from the end of the line, or the whole line.
                # A form taken out of the middle leaves its neighbours
                # holding each other's labels however the seam is
                # tidied (ἀφύσσω ran a Doric future into an Epic aorist,
                # ἀγοράζω shipped ": etc.:"); the bar carries the form
                # in either case, so the duplicate is the cheaper fault.
                if start and flat[end:].strip(' ,;:·') and not DATASET.startswith('lat'):
                    # Greek only: Lewis and Short's parts are a bare
                    # chain ("āvī, ātum, āre") that a middle cut leaves
                    # whole, and main's floor of four was measured on it.
                    continue
                flat = flat[:start] + flat[end:]
                break
    flat = re.sub(r'\s{2,}', ' ', flat)
    flat = re.sub(r'(?:^|(?<=\s))[,;:]\s*', '', flat)
    return flat.strip(' ,;:')


# A Latin principal part names itself. The perfect ends in -i (āvī, uī,
# psi), the supine in -um (ātum, nsum), the infinitive in -re (āre, ĕre)
# and the conjugation is a bare number. Reading them by position instead
# put the conjugation number in the supine slot for 1,025 entries (abito
# "ĕre, 3" shipped "pf. ĕre | sup. 3", where the print gives an
# infinitive and a conjugation), the supine in the perfect's for 254, and
# the infinitive in the perfect's for 250. An editor's name that the
# print sets in the same run ("Halm", "Fleckeisen") names no slot and
# gets none.
_LATIN_SLOTS = (
    ('conj.', re.compile(r'^\d')),
    ('inf.', re.compile(r're$')),
    ('sup.', re.compile(r'um$')),
    ('pf.', re.compile(r'i$')),
)


def _latin_slot(part):
    """The slot this part belongs in, or '' when its shape says nothing.

    Read on the part's last word, with the quantity marks off but the
    digits kept: `extract.fold_latin` is a key fold and drops both.
    """
    plain = unicodedata.normalize('NFD', part)
    plain = ''.join(c for c in plain if not unicodedata.combining(c)).lower()
    words = plain.split()
    tail = words[-1] if words else ''
    for slot, shape in _LATIN_SLOTS:
        if shape.search(tail):
            return slot
    return ''


def form_bar(html, lemma):
    if DATASET.startswith('lat'):
        pre, _ = L.split_preamble(html)
        it = L.first_element(pre, 'lx-itype')
        if not it:
            return []
        parts = [p.strip() for p in L.text_of(it[0]).split(',') if p.strip()]
        if len(parts) < 2:
            return []
        # pf./sup./conj. are principal parts. On an adjective (malus, a,
        # um) they label the print into nonsense — "PF. a | SUP. um".
        # Only a verb gets slots; anything else shows the print's own
        # itype with no label of ours on it.
        pos = L.first_element(pre, 'lx-pos')
        pos_txt = L.text_of(pos[0]) if pos else ''
        if not re.search(r'\bv\.\s*(?:a|n|dep|freq|inch|impers)\b|\bverb\b',
                         pos_txt, re.I):
            return [['', ', '.join(parts)]]
        return [[_latin_slot(form), form] for form in parts]
    try:
        # The print's hyphen forms are expanded only where the
        # analyses pack knows the result. See gen_ideal_verb.expand_suffix.
        fc = flashcard(forms_scope(html), lemma,
                       attested=lambda form: bool(lemmas_of(form)))
        bits = []
        for name, v in fc[1:]:
            if not v:
                continue
            form = v[0]
            cap = SLOT_CAPTIONS.get(name, name)
            bits.append([cap, form])
        if bits:
            return bits
    except Exception:
        pass
    pre, _ = L.split_preamble(html)
    h = L.first_element(pre, 'lx-head')
    body = pre[h[2]:] if h else pre
    # The print's first label follows the headword's comma — "οὐσία, Ion.
    # -ιη" — and a row that opens on that comma matched no label and was
    # skipped, so the first dialect form never reached the bar. A label
    # the print introduces with a comma opens a row of its own (ἀδικέω's
    # "Aeol. ἀδικήω Sapph. 1.20, Dor. ἀδικίω"), and its ":—" block
    # separator is a separator here too.
    body = re.sub(r'^[\s,;:]+', '', body)
    body = re.sub(r',\s*(?=<span class="lx-gramGrp">)', '; ', body)
    body = body.replace(':—', '; ')
    rows = L.forms_rows(body)
    bits = []
    for label, content in rows:
        content = _strip_citations(_keep_quoted_forms(content))
        # The reference behind a form is not the form: "Tab.Heracl.
        # 1.138" is where ἀδικίω is attested.
        content = STRIP_WORK.sub('', content)
        lt = L.text_of(label).strip(' ,;:')
        ct = L.text_of(content)
        # The shell a stripped citation leaves: "-ιη, , (, )".
        ct = re.sub(r'\(\s*[,;·]*\s*\)', '', ct)
        ct = re.sub(r'\s*,(?:\s*,)+', ',', ct)
        # The bar shows forms. A trailing Greek etymology — ἄατος's
        # "(ἄω)", οὐσία's "(ὀντ-, part. of εἰμί sum)" — and a lone
        # article are the identity line's business.
        ct = re.sub(r'\s*\(\s*[Ͱ-Ͽἀ-῿][^()]*\)\s*$', '', ct)
        ct = re.sub(r'\s*·\s*(?:ὁ|ἡ|τό|οἱ|αἱ|τά)(?=\s*·|\s*$)', '', ct)
        ct = ct.strip(' ,;:—·')
        if not lt or not ct:
            continue
        if len(ct) > 42:
            ct = ct[:42].rsplit(' ', 1)[0] + '…'
        # A bar row shows a form. ἀάω opens "Ep. Verb (twice in Trag., v.
        # infr.), used by Hom. in aor. Act. ἄᾰσα": a label on a sentence,
        # and the sentence is what the reader would see.
        if not _GREEK_CH.search(ct):
            continue
        bits.append([lt, ct])
        if len(bits) >= 8:
            break
    return bits



ABBR_DEBRIS = re.compile(r'\b(?:al|ib|cf|etc|sq|foreg|v|vide|Id|dub|lyr|ap|sc|cj)\.?\b', re.I)


def _gloss_score(eng):
    """How much of this looks like a definition rather than apparatus.

    "al." is what is left of "Ev.Luc. 22.41, al." once the references go;
    it is not a gloss, and it must not beat "kneel down"."""
    t = ABBR_DEBRIS.sub('', L.text_of(eng or ''))
    # Lowercase words only: an author's name a governed citation keeps
    # in the sentence ("dub. in Phld.") is not a definition, and it must
    # not beat "immediately" (ἄμεσος Adv.).
    return len(re.findall(r'(?<![^\W\d_])[a-zα-ωἀ-ῼ][^\W\d_]+', t))


def zone_from_evidence(ev):
    """A sense the print states only among its references.

    Two shapes, and neither order is safe on its own. LSJ ἅλς III and
    τίθημι 12 put the gloss inside a citation ("τιθέναι τὰ γόνατα kneel
    down, Ev.Marc. 15.19, al."), while καταστηματικός II leaves it
    outside one, after a cross-reference the definition/evidence cut split
    in half. Score both and take the one that reads like a definition."""
    outside = ev
    for b in list(each_span(ev, 'lx-cit')) + list(each_span(ev, 'lx-bibl')):
        outside = outside.replace(b, '', 1)
    outside = STRIP_WORK.sub('', outside)
    outside = re.sub(r'^[\s)\],;:.]+', '', outside)
    cands = [split_sense(outside)]

    block = next(each_span(ev, 'lx-cit'), '')
    if block:
        inner = re.sub(r'^<span class="lx-cit"[^>]*>', '', block)
        inner = re.sub(r'</span>\s*$', '', inner)
        inner = re.sub(r'<span class="lx-bibl".*?</span>', '', inner, flags=re.S)
        inner = STRIP_WORK.sub('', inner)
        eng, ill = split_sense(inner)
        eng = re.sub(r'[\s,;]*[\d]+(?:\.[\d]+)*\s*(?=(?:</\w+>\s*)*$)', '', eng)
        cands.append((eng, ill))

    # Ties go to the citation. Leftover apparatus scores as well as a
    # short gloss ("ap" against "sugar", "and, without" against "the
    # toes"), and the print puts the gloss beside the quotation.
    cands.reverse()

    def _rank(c):
        # The print's own translation cue is what makes a candidate a
        # definition; an aside has none. ἔκλαμπρος states its adverb's
        # gloss inside the citation ("-ρως brilliantly") and carries
        # "(Pisidia, ἐγλ-lapis)" outside it, and once the aside kept its
        # Greek the longer string won and the row was lost.
        return ('<b class="cue">' in c[0], _gloss_score(c[0]))

    best = max(cands, key=_rank)
    return (_tidy(best[0]), best[1]) if _gloss_score(best[0]) else ('', '')


def source_is_bare(html):
    """True when the print gives nothing but a headword and its morphology.

    LSJ ἐξάρθρωμα is "ἐξάρθρωμα, ατος, τό," and stops. Rendering nothing
    for it is honest; rendering nothing for πεύθομαι, which says "older
    form of πυνθάνομαι", is a bug. The build gate needs to tell them
    apart, or it either passes real losses or fails on empty sources."""
    rest = re.sub(r'<b class="lx-(?:head|orth)"[^>]*>.*?</b>', '', html,
                  flags=re.S)
    for cls in ('lx-itype', 'lx-gen', 'lx-pron', 'lx-pos', 'lx-number',
                'lx-orth', 'lx-per'):
        for el in list(each_span(rest, cls)):
            rest = rest.replace(el, '', 1)
    return not _has_words(rest)


def models(word):
    """Every entry filed under this key, in the print's order.

    Folding strips the accent that separates βίος (life) from βιός
    (bow), so one key can hold several unrelated words. Rendering
    recs[0] and stopping drops the rest without telling anyone."""
    recs = lex_get(word)
    if not recs:
        raise LookupError(
            f"no {DATASET} entry for {word!r} "
            f"(folded {fold(word)!r})")
    return [model(word, rec) for rec in recs]


def model(word, rec=None):
    if rec is None:
        recs = lex_get(word)
        if not recs:
            raise LookupError(
                f"no {DATASET} entry for {word!r} "
                f"(folded {fold(word)!r})")
        rec = recs[0]
    rec = dict(rec)
    rec['html'] = demote_editor_sigla(rec.get('html') or '')
    html = resolve_rel(
        mark_prose_authors(_source_editorial_angles(rec['html'])), word)
    hom = print_homonym(rec)
    numbered, lifted = lift_demoted_siblings(sense_numbers(L.senses(html)))
    # Levels only, and no rows added or removed, so the lift's indexes
    # stay valid.
    numbered = demote_band_first_sense(numbered)
    numbered = demote_roman_first_subsense(numbered)
    if not numbered:
        m = model_short(word, html)
        m['hom'] = hom
        m['key'] = rec.get('key') or ''
        m.setdefault('gloss', preamble_gloss(L.split_preamble(html)[0]))
        return _drop_print_work_titles(
            m, rec.get('html') or '', rec.get('head') or word)
    lemma, gender, ident = head_bits(html)
    base = min((d for d, *_ in numbered), default=0)
    rows = []
    bullets = []   # unnumbered '•' senses, kept in case nothing else survives
    # The author "Id." stands for: the last one the print named, which
    # may be in the preamble or in the sense above this one.
    named = last_author(L.split_preamble(html)[0])

    for i, (dl, n, body, supplied) in enumerate(numbered):
        if i:
            named = last_author(numbered[i - 1][2]) or named
        segments = _sense_segments(body)
        # The cut that separates two definitions does not separate their
        # quotations. A print unit that does not itself become a row —
        # its gloss inside a citation block (ἀβαρής's Adv.), an untagged
        # quotation in front of it (χείρ's "come to blows"), no italic at
        # all (ἀφαυρός's "almost always Comp. and Sup.") — leaves its
        # quotations and authors in the row above it. Verified against
        # the print on a random sample: the glosses are right, and about
        # three rows in ten carried a citation belonging to the sense
        # after them. A wrong citation in a lexicon is worse than no
        # citation, so until attribution is fixed the recovery is the
        # gloss alone and every sense's evidence stays where it was
        # before this work — on the sense's own row.
        whole_ev = L.defzone(body)[1]
        # A sense whose own opening says nothing is carried by the first
        # definition the print wrote after it. Perseus parks ἡνιοχεύς
        # "8." on a bare locus and L&S absis I. on a textual note, and
        # "the constellation Auriga" / "In a church, the choir" a few
        # tokens later is what the sense means. Promote that wording to
        # the sense line, keeping the evidence it stood on: segmenting
        # must never cost the entry a row.
        while len(segments) > 1 and not _has_words(segments[0][0]):
            segments = ([(_lead_punct(segments[1][0]),
                          segments[0][1] + segments[1][1])]
                        + segments[2:])
            zone = segments[0][0]
        zone = keep_governed_author(segments[0][0], whole_ev)
        zone, ev = keep_governed_quote(zone, whole_ev)
        zt = L.text_of(zone)
        nn = (n or '').rstrip('.')
        if nn == '•':
            if zt:
                ident = short_label(zt, 16)
                bullets.append((zone, ev))
            continue
        # An address of our own making — supplied here, or left behind by
        # the lift — is not the print declaring a section head.
        ours = supplied or (i in lifted)
        attested = bool(re.search(r'class="lx-(?:cit|bibl)\b', ev))
        banner = is_banner(n, zt, has_child(numbered, i), dl - base, ours, attested)
        numeral = False
        if not banner and BANNER_ZONE.match(zt):
            # "PROSODY: in ἐπιόψομαι, ι is not elided…" is one note.
            # split_sense would leave "PROSODY: in" and hide the rest.
            # Keep (v. lemma) pointers — they are the note, not a cf. aside.
            z = STRIP_WORK.sub('', _keep_governed_titles(_strip_citations(zone)))
            eng = _cue_italics(z)
            if L.text_of(z).rstrip().endswith('.') and not L.text_of(eng).endswith('.'):
                eng += '.'
            ill = ''
        else:
            eng, ill = split_sense(zone)
            # A numbered sense whose zone is all Greek (βρίζω II:
            # "βρίζει· ἐσθίει, πιέζει, κύει, Hsch.") leaves split_sense
            # with no English and the row renders blank. Same shape as an
            # unnumbered Hesychius gloss — read it as an equation.
            # Runs for banners too: their zone is blanked, and if the lv
            # surgery later demotes one to a sense it falls back to zfull.
            # ἑξηκονταδύο's sense is "62, 64, 65, 66, 67, 68, 69": a
            # numeral entry's gloss is its numbers.
            numeral = bool(re.fullmatch(r'\s*\d{1,4}(?:\s*,\s*\d{1,4})+[\s,]*',
                                        L.text_of(eng)))
            if not _has_words(eng) and not numeral:
                eq = eq_zone(zone)
                if _has_words(eq):
                    eng, ill = eq, ''
                else:
                    ev_eng, ev_ill = zone_from_evidence(ev)
                    if _has_words(ev_eng):
                        eng, ill = ev_eng, ev_ill
        # Strip a dangling linking abbreviation BEFORE the empty-gloss
        # recoveries, so a row whose whole gloss was ", cf" (κομπάζω III)
        # can recover its content from the evidence instead of shipping
        # the debris.
        eng_kept = eng
        if not banner and not numeral:
            eng = _strip_dangling(eng)
        if not banner and not _has_words(eng) and ill:
            # "αἱμοειδής, ές, = αἱματοειδής": split_sense sent the Greek to
            # the drawer and left "=" as the gloss. When nothing but
            # punctuation stands in front of it, the Greek IS the
            # definition — keep it on the line.
            eng, ill = _tidy((eng + ' ' + ill).strip()), ''
        # The antecedent an "Id." means is the last author named before
        # it, and the zone comes before the evidence: προσαγωγή 5 names
        # Hp. in its own definition and its "Id. Acut. 11" was resolved
        # off the row above, shipping "Aen.Tact. Acut. 11", a citation
        # that cannot exist. unique_authors already reads the zone.
        examples = [] if banner else examples_of(
            ill, ev, L.text_of(eng), last_author(zone) or named)
        if not banner and not _has_words(eng) and examples:
            # "αἱμοειδής, ές, = αἱματοειδής, Ph. 2.244": the target sits in
            # the citation as a quotation, so both fallbacks score it zero
            # and the row ships a bare "=". For an equation the Greek is
            # the definition — put it on the line and out of the drawer.
            eng = _tidy((eng + ' ' + wrap_gr(examples[0]['gr'])).strip())
            examples = examples[1:]
        _stub = L.text_of(eng).rstrip(' ,;:')
        _stub_words = [w for w in _stub.split() if w != '=']
        if (i == 0 and lifted and not banner and examples
                and len(_stub_words) <= 4 and DANGLING_GLOSS.search(_stub)
                and (STUB_ENDS.search(_stub) or STUB_FORMULA.search(_stub)
                     or len(_stub_words) <= 2)):
            # A lifted entry's first sense was a band before the lift, so
            # its zone never went through split_sense — which sends a
            # definitional Greek word to the drawer when the print writes
            # the definition through it: ἀδυνατέω "to be ἀδύνατος, lack
            # strength" shipped as "to be". Only a 1–2 word stub is that
            # mis-split; a full gloss may end on the same word ("getting
            # rid of", "lavish of" — genitive-taking glosses) and its
            # example is a quotation that stays in the drawer. The
            # spliced continuation stops at the example's own first
            # illustration (ἀναβιβάζω: "make to go up, cause to mount",
            # not the ἐπὶ τὴν πυρήν that follows).
            ex0 = examples[0]
            gr0 = (ex0['gr'] or '').split(',')[0].strip()
            cont = re.split(GREEK_RUN.pattern, ex0.get('eng') or '', maxsplit=1)[0].strip(' ,;:')
            # Only a single Greek word is the lemma the print wrote the
            # definition through; anything longer is a quotation that
            # stays in the drawer, illustrations and citation intact
            # (ἀναβιβάζω keeps ἐπὶ τὴν πυρήν behind the line).
            if len(gr0.split()) == 1:
                eng = _tidy((eng + ' ' + wrap_gr(gr0)
                             + (', ' + cont if cont else '')).strip())
                if gr0 == (ex0['gr'] or '').strip():
                    examples = examples[1:]
        # Only now is it safe to drop the sense. The empty-zone test used
        # to run before the fallbacks, so a sense whose definition sits
        # inside its citation — δεκάσκαλμος "with ten banks of oars", the
        # entry's only sense — was discarded before anything could look
        # for it.
        if not banner and not _has_words(eng) and not examples and not numeral:
            # Nothing recovered. A debris gloss the reader could at least
            # follow beats a silently dropped sense — and keeps the row
            # count invariant against the shipped pack.
            if _has_words(L.text_of(eng_kept)):
                eng = eng_kept
            else:
                continue
        rows.append({
            'lv': dl - base,
            'n': nn,
            'supplied': supplied,
            'banner': banner,
            'usage': (not banner) and is_usage(eng, L.text_of(eng)),
            'zone': '' if banner else eng,
            # The gloss as written, kept even on a banner: the group label
            # comes from its bold cue, and a banner's zone is emptied.
            'zfull': eng,
            'illust': '' if banner else ill,
            'examples': examples,
            'plain': zt,
            # The zone too: a bare citation the print set inside the
            # definition ("slabs (?) in theatre, Suid. s.v. ἄβαξι") is
            # wrapped there and never reaches the evidence.
            'authors': [] if banner else unique_authors(zone + ev, named),
            'slug': fold(lemma or word),
            'lemma': lemma or word,
            'kids': has_child(numbered, i),
            'lifted': ours,
            'attested': attested,
            # A banner heads its sense's children; the definitions the
            # print wrote after its label are among them. Gating this on
            # `not banner` threw away 1,060 Greek and 865 Latin of them
            # (L&S abortus I. "Lit.: … but also, to produce or cause
            # abortion"). They expand under the banner, before its own
            # numbered children.
            'conts': _without_quotations(segments[1:], examples),
        })
    # LSJ packs F. PROSODY / G. IN COMPOSITION as children of the last
    # case tab (ἐπί E. Abs.). They continue the A–E series, not Abs.
    last_let = None
    for r in rows:
        nn = r['n']
        if r['lv'] == 0 and is_letter_addr(nn):
            last_let = nn
            continue
        if last_let and r['lv'] > 0 and is_letter_addr(nn) and nn > last_let:
            r['lv'] = 0
            last_let = nn
    groups = []
    seen_az = False
    for r in rows:
        nn = r['n']
        if r['lv'] != 0:
            continue
        if DATASET.startswith('lat'):
            # I. II. are tabs; A–H are senses. A later I. after H. is
            # letter I (et … et), not a third roman division.
            if is_letter_addr(nn):
                seen_az = True
            if seen_az or not ROMAN.match(nn):
                continue
        elif not (is_letter_addr(nn) or ROMAN.match(nn)):
            continue
        cues = [L.text_of(c)
                for c in re.findall(r'<b class="cue">(.*?)</b>', r['zfull'])]
        # A cueless division is a prose sense; its label is the prose's
        # FIRST CLAUSE, not a 42-char slice — οὐσία II reads "in Philos.",
        # not "in Philos., like Ion. φύσις (with". Fall back to the
        # capped slice only when the first clause is itself a wall.
        plain_lab = clause_label(r['plain']) or short_label(r['plain'])
        lab = ', '.join(cues) if cues else plain_lab
        bm = BANNER_ZONE.match(r['plain'])
        if bm:
            lab = polish_label(bm.group(0).rstrip('.:'))
        # A period this round newly keeps (malitiosus "nom. prop.") must
        # not tip the choice of label, so measure such a cue without it.
        # Only those: a cue whose period was always there keeps its old
        # length (helice "nom. propr.", perodi "part. perf." unchanged).
        elif cues and len(lab) < 14 and len(plain_lab) > len(
                lab[:-1] if re.search(r'\b(?:%s)\.$' % '|'.join(_GRAM_TAIL_ADDED),
                                      lab, re.I) else lab) + 3:
            lab = plain_lab
        lab = re.sub(r'\s*,+\s*', ', ', lab).strip(' ,;:')
        # Label builders strip punctuation after _tidy. Put back a period
        # only when the print ends the label on a known grammar abbreviation.
        pm = re.search(r'\b([A-Za-z][A-Za-z. ]{0,14})\.\s*$', r['plain'])
        if pm and not lab.endswith('.'):
            stem = pm.group(1).split()[-1].rstrip('.').lower()
            # Not where DANGLING_LINK will strip the tail (", freq"): a
            # period there would keep a dangling link on the label.
            if (stem in _GRAM_TAIL and lab.lower().endswith(stem)
                    and not DANGLING_LINK.search(lab)):
                lab += '.'
        groups.append((nn, cap_label(lab)))
    # Carry each group's label onto its own row, so a band whose zone was
    # emptied still names the group (see banner_label).
    glabs, seen_lab = dict(groups), set()
    for r in rows:
        if r['lv'] == 0 and r['n'] in glabs and r['n'] not in seen_lab:
            seen_lab.add(r['n'])
            r['glab'] = glabs[r['n']]
    # Perseus markup often parks later senses at the same depth as
    # the print's top divisions (L&S mensa F–H; same pattern in LSJ).
    # After a tab has opened, leftover lv0 rows nest under it.
    if groups:
        tab_keys = {n for n, _ in groups}
        seen_tabs = set()
        for r in rows:
            nn = r['n']
            if r['lv'] == 0 and nn in tab_keys and nn not in seen_tabs:
                seen_tabs.add(nn)
                continue
            if r['lv'] == 0 and seen_tabs:
                r['lv'] = 1
    for i, r in enumerate(rows):
        kids = i + 1 < len(rows) and rows[i + 1]['lv'] > r['lv']
        r['kids'] = kids
        if not kids:
            # Demoted back to a sense after the lv surgery took its
            # children away. Its zone was emptied when it was marked a
            # banner, so put the gloss back or the row renders blank
            # (Latin Rhodos A, Nisibis, cornutus, Hydaspes, cuneo, Gyges).
            if r['banner'] and not L.text_of(r['zone']).strip():
                r['zone'] = r['zfull']
            r['banner'] = False
        else:
            bm = BANNER_ZONE.match(r['plain'] or '')
            rest = r['plain'][bm.end():].strip(' ,.;:—') if bm else 'x'
            # Same lifted rule as is_banner: a lifted row heads only
            # when nothing follows the label (προσαυγάζω III "abs.,
            # gleam" keeps its one-word gloss).
            if bm and not r.get('attested') and len(rest.split()) < (1 if r.get('lifted') else 2):
                r['banner'] = True
    if len(groups) < 2:
        if sum(1 for r in rows if not r['banner']) <= 8:
            for r in rows:
                r['lv'] = 0
            # Flattening removed every parent-child relation, which can
            # orphan a banner the refresh above had let stand (ὑπεξάγω II).
            # A heading with nothing under it is not a heading.
            kept = []
            for r in rows:
                label = (r['zone'] or r.get('glab') or r.get('zfull')
                         or r.get('plain') or '')
                if not r['banner'] or _has_words(label):
                    kept.append(r)      # a heading that names something
                    continue
                r['banner'] = False
                r['kids'] = False
                r['zone'] = r.get('zfull') or ''
                if _has_words(r['zone']) or r.get('examples'):
                    kept.append(r)
            rows = kept
    if not rows:
        # The senses rendered nothing, but the meaning may sit in the
        # preamble: πεύθομαι is "older form of πυνθάνομαι" with one empty
        # numbered sense after it. Read it as a short entry instead.
        m = model_short(word, html)
        # Do not lose a bullet sense on the way: πεύθομαι's is
        # "Act. πεύθω, lay information against", the only place that
        # meaning appears.
        for zone_b, ev_b in bullets:
            eng_b, ill_b = split_sense(zone_b)
            if not _has_words(eng_b):
                eng_b, ill_b = zone_from_evidence(ev_b)
            if not _has_words(eng_b):
                continue
            m['rows'].append({
                'lv': 0, 'n': '', 'supplied': False, 'banner': False,
                'usage': False, 'zone': eng_b, 'zfull': eng_b,
                'illust': ill_b,
                'examples': examples_of(ill_b, ev_b, L.text_of(eng_b),
                                        last_author(zone_b) or last_author(html)),
                'plain': L.text_of(zone_b), 'authors': unique_authors(zone_b + ev_b, last_author(html)),
                'slug': fold(lemma or word), 'lemma': lemma or word,
                'kids': False,
            })
        m['n_senses'] = len(m['rows'])
        m['hom'] = hom
        m['key'] = rec.get('key') or ''
        return _drop_print_work_titles(
            m, rec.get('html') or '', rec.get('head') or word)
    # Continuations expand last, after the lv surgery and the flatten:
    # they are not the print's own divisions and must not be counted as
    # senses when those rules decide how deep this entry nests.
    expanded = []
    for r in rows:
        conts = r.pop('conts', None)
        expanded.append(r)
        for zone_c, ev_c in conts or ():
            child = continuation_row(r, zone_c, ev_c)
            if child:
                r['kids'] = True
                expanded.append(child)
    rows = expanded
    forms = form_bar(html, lemma or word)
    out = {
        'lemma': lemma or word,
        'hom': hom,
        'gloss': preamble_gloss(L.split_preamble(html)[0]),
        'key': rec.get('key') or '',
        'gender': gender,
        'ident': ident_without_forms(ident, forms),
        'forms': forms,
        'groups': groups,
        'rows': rows,
        'n_senses': sum(1 for r in rows if not r['banner']),
        'slug': fold(lemma or word),
    }
    return _drop_print_work_titles(
        out, rec.get('html') or '', rec.get('head') or word)


SAME_AUTH = re.compile(r'^id\.?$', re.I)


def each_span(html, cls):
    """Yield full <span class="cls">…</span> elements, nesting-safe."""
    for m in re.finditer(r'<span class="' + re.escape(cls) + r'"', html):
        depth = 0
        for t in re.finditer(r'<span\b[^>]*>|</span>', html[m.start():]):
            if t.group().startswith('</'):
                depth -= 1
                if depth == 0:
                    yield html[m.start(): m.start() + t.end()]
                    break
            else:
                depth += 1


def cite_from(bibl_html, prev, last_raw=''):
    # An editor-only reference supplies no citation and cannot become
    # the antecedent for a later "Id." reference.
    if ('data-editor="1"' in bibl_html
            and re.fullmatch(r'\s*[A-Z]\.\s*', L.text_of(bibl_html))):
        return '', prev, last_raw
    raw = re.sub(r'\s+', ' ', L.text_of(bibl_html)).strip()
    # A wrapped citation may open on the "ap." that joined it to a
    # first author the print left in plain text ("f.l. ap. Erot.").
    raw = re.sub(r'^ap\.\s*', '', raw)
    am = re.search(r'class="lx-author"[^>]*>([^<]+)', bibl_html)
    auth = am.group(1).strip() if am else ''
    if auth and SAME_AUTH.match(auth.rstrip('.')):
        if prev:
            use = prev
            if DATASET.startswith('lat'):
                work = _id_work(bibl_html, am.end())
                veto = id_veto().get((prev, work))
                if veto:
                    use = veto
            # Lewis & Short writes "id."; the drawer shipped it unresolved
            # ("id. 3, 6", "id. ib. 4, 7, 77") on every Latin citation.
            raw = re.sub(r'^[Ii]d\.?', use, raw)
            auth = use
            # The veto corrects this one citation and nothing after it:
            # the antecedent chain stays as the transform read it, so a
            # following "id. ib." keeps the reading it had (exspecto's
            # "id. ib. 3, 60, 1" after a vetoed "id. Tusc." is the print's
            # own ambiguity, not this round's to settle).
    elif auth:
        prev = auth
    if re.fullmatch(r'[\d.]+', raw) and last_raw:
        prefix = re.sub(r'[\d.]+\s*$', '', last_raw).strip()
        if prefix:
            raw = prefix + ' ' + raw
    return raw, prev or auth, raw


# What stands before a bare Greek run decides whether it is a quotation
# or a pointer: "opp. ἀθάνατος", "cf. θνησείδιον", "= foreg." name other
# words, and the citation that follows belongs to the entry, not to them.
REF_LEAD = re.compile(
    r'(?:opp\.|cf\.|v\.|vide|=|for|freq\. in|Ep\.|Att\.|Ion\.|Dor\.|Aeol\.'
    r'|dat\.|gen\.|acc\.|pl\.|sg\.)\s*[,:]?\s*$', re.I)


_GOVERNOR_WORDS = frozenset(
    'by of to in at with from for on the a an'.split())

_BARE_CONNECTIVE = frozenset(
    'or and but nor i.e viz'.split())


def _example_gloss(text):
    """An example's own English gloss. A locus or citation that escaped
    span markup is not one — a gloss never carries a digit — and neither
    is an author/work chain ("Hsch.", "Ar. Pax l.c.", "Don.") or a bare
    grammar tag ("fut"): a gloss has at least one ordinary lowercase
    word."""
    eng = text.strip(' ,;:()[]')
    if re.search(r'\d', eng):
        return ''
    core = re.sub(r'\bl\.\s*c\.', '', eng).strip(' ,;:')
    toks = core.split()
    if not toks:
        return ''
    if all(re.fullmatch(r"[A-Z][A-Za-z'’]*\.?,?", t) for t in toks):
        return ''
    _tense = ('fut', 'aor', 'pf', 'impf', 'plpf', 'pres', 'opt', 'subj',
              'inf', 'imper', 'med', 'pass', 'act')
    if len(toks) <= 2 and all(GRAM_TAG.match(t.rstrip('.,'))
                              or t.rstrip('.,').lower() in _tense
                              for t in toks):
        return ''
    if not _has_words(ABBR_DEBRIS.sub('', eng)):
        return ''
    # What the citation strip leaves around a translation is trimmed,
    # not taken as part of it: a bracket closed on nothing in front
    # ("sc. ), τά, food for sick persons"), the stub of a reference
    # behind ("the law-court there, Decr. ap", "Epigr. in", "cj. in"),
    # the preposition that governed a stripped author ("as dry from
    # moist, by"), punctuation the strip left leading (". , for
    # building"). What is left has to end on a word of its own.
    if eng.count(')') > eng.count('('):
        # Whichever side of the stray bracket carries the words: "sc. ),
        # τά, food for sick persons" has them after it, ἀνεπίγραφος's
        # "for the names of those who offered vestments…), al., etc."
        # before it.
        cut = eng.rfind(')')
        before, after = eng[:cut], eng[cut + 1:]
        # What follows the bracket is the translation unless it is the
        # next block (ἀνθίζω "…ibid.): metaph., :—Med., gather") or a
        # reference's tail ("al., etc.; l.c").
        after = after.split(':—')[0]
        take_after = (len(after.split()) >= 3
                      and not re.match(r'[\s,;:]*[a-z]+\.[,;]', after))
        if take_after and len(before.split()) >= 3 and not re.search(
                r'[A-Z][a-z]*\.|\b(?:written|codd?|cj|v\.l|leg|Sch|read)\b', before):
            # "quietly as it were), with a smile": the bracket's mate went
            # with the citation and both sides are the translation. Not
            # when the first side is an editor's note (ἀμφιμέλας "best
            # written divisim, as by Alex. critics), darkened…").
            eng = before.rstrip(' ,;:') + ', ' + after.lstrip(' ,;:')
        else:
            eng = after if take_after else before
    eng = re.sub(r'^[^A-Za-z‘\'"(\[=Ͱ-Ͽἀ-῿-]+', '', eng)
    for _ in range(3):
        eng = re.sub(r'[,;]?\s*(?:[A-Z][\w.]*\s+){0,2}(?<![A-Za-z])'
                     r'(?:ap|cf|ib|ibid|al|etc|v|sq|sqq|q\.\s*v|opp)\.?$',
                     '', eng).rstrip(' ,;:')
        # "in" only behind an abbreviation or a name — "cj. in", "v.l.
        # in", "Serapio in" — never off a phrasal verb ("takes in").
        eng = re.sub(r'(?:^|[,;])\s*(?:[A-Z][\w.]*|[a-z]+\.(?:[a-z]+\.)*)\s+in$',
                     '', eng).rstrip(' ,;:')
        eng = re.sub(r',\s*(?:by|of|to|in|at|with|from|and|or|the|a|an)$',
                     '', eng).rstrip(' ,;:')
    toks = eng.split()
    if not toks or not _has_words(ABBR_DEBRIS.sub('', eng)):
        return ''
    if all(re.fullmatch(r"[A-Z][A-Za-z'’]*\.?,?", t) for t in toks):
        return ''
    # "by", "of the", "cj. for": a governor left when its object was a
    # citation. Not a gloss that ends on its preposition — L&S writes
    # "to gape at", "to deprive of" — and not an adverb: mox is "then".
    if toks[-1].rstrip('.,;:').lower() in _GOVERNOR_WORDS and (
            all(t.rstrip('.,;:').lower() in _GOVERNOR_WORDS for t in toks)
            or len(toks) == 2 and toks[0].endswith('.')):
        return ''
    # "or", "and", "i.e.": the whole remaining gloss is the print's
    # connective between two quotations, not a translation: ἀγαθόω
    # ships "τινί τινά" rendered "or".
    if len(toks) == 1 and toks[0].rstrip('.,;:').lower() in _BARE_CONNECTIVE:
        return ''
    return eng.rstrip(' ,;:(')


# Lewis & Short quotes in plain text. Where LSJ wraps every quotation in
# lx-quote or lx-foreign, L&S writes the Latin bare — "sicut fortis equus,
# spatio qui saepe supremo Vicit Olympia, nunc senio confectus quiescit,
# <i>a powerful horse</i>, Enn. ap. Cic." — with the translation in a
# plain italic and the reference after it. Nothing in the markup says the
# Latin is a quotation; the entrylib cut rule, written for LSJ, reads the
# italic as a definition and the translation shipped as a sense of its
# own, the Latin glued to it: 27 in 60 Latin recovered rows, on a random
# read. The other shape of the same thing is a bare case-form ("agrorum,
# <i>in the country</i>, Cod. Th.").
#
# Only grammar separates a quotation from an idiom definition the print
# writes in the same shape — manus has "manum ferulae subducere, <i>to
# take the hand from the rod</i>, Juv. 1, 15" — and Morpheus has the
# grammar: an idiom formula carries an infinitive or an indefinite
# placeholder (aliquem, quippiam), a quotation does not. Every test
# below is a veto, so an unknown lead keeps the print's cut: the failure
# is the status quo, never a deleted definition.
_LEAD_ENGLISH = frozenset(
    'the of and with to by or as also hence than any one some thing things '
    'which who whose this that those it its from on not but when where while '
    'into upon between among after before been are was were his her their '
    'our your my for'.split())
# Not "an" — the Latin interrogative particle, inside quotations ("Lucanus
# an Apulus, anceps") — and not "In": verse capitalises its first word.
# "for" is fari's, and never quoted alone.
_FORM_CLS = ('lx-pos', 'lx-orth')
_LEAD_RUBRIC = re.compile(
    r'\b(?:Esp|Pregn|Transf|Trop|Lit|Absol|Poet|Meton|Fig|Sup|Comp|Prop|'
    r'Ellipt|Impers)\.')
_LEAD_PLACEHOLDER = frozenset(
    'aliquis aliquid alicui aliquem alicujus aliqua quippiam quis se sibi '
    'rem re'.split())
_LEAD_IE = re.compile(r'\b[ie]\.\s*[eg]\.')


def _reads_latin(text):
    """Every word parses as Latin and none is an English marker."""
    toks = LATIN_TOKEN.findall(text)
    if not toks:
        return False
    # Before the parse test: "the", "this" and "one" all parse as Latin.
    if any(t.lower() in _LEAD_ENGLISH for t in toks):
        return False
    return all(_analyses_features(t) for t in toks)


def _latin_quotation_lead(lead, translation=''):
    """The Latin quotation in the untagged text before an italic, or ''."""
    if not lead or '—' in lead or lead.lstrip().startswith('.'):
        return ''
    text = _LEAD_IE.sub(' ', lead)
    if _LEAD_RUBRIC.search(text) or not _reads_latin(text):
        return ''
    # An aside in brackets is the print's ("(regio)" before a sub-lemma's
    # gloss), and a lone preposition or conjunction is nobody's quotation
    # (ingravo's "in <i>…</i>").
    core = text.strip(' ,;:')
    if core.startswith('(') and core.endswith(')'):
        return ''
    toks = LATIN_TOKEN.findall(text)
    if len(toks) == 1 and all(f.startswith('indeclform')
                              for f in _analyses_features(toks[0])):
        return ''
    # The italic is the translation. When it reads as Latin itself the
    # print italicised the quotation (dico: "Catonis est dictum. <i>Pedibus
    # compensari pecuniam</i>, Cic."), and there is no translation here.
    # Three words of it: "a mine" parses too (a, minae). And a translation
    # has a word in it — tonitrus's "<i>neutr.</i>" is a grammar label,
    # facio's "edere <i>or</i> statuere" a conjunction.
    if len(LATIN_TOKEN.findall(translation)) >= 3 and _reads_latin(translation):
        return ''
    if not re.search(r'(?<![^\W\d_])[^\W\d_]{3,}(?![^\W\d_]|\.)', translation):
        return ''
    # A bracket the quotation opens and the translation sits inside —
    # affingo "adfingit (<i>creating, she adds</i> thereto) aut mutat" —
    # is the print translating mid-sentence; the quotation continues
    # past it and this pass does not read that shape.
    if lead.count('(') != lead.count(')'):
        return ''
    # An idiom's definition is a verb phrase and reads "to …"; a
    # quotation's translation reads as the passage does ("a mine", "am I
    # envied?"), and an infinitive in it is the author's.
    verbal = bool(re.match(r'\s*(?:not\s+)?to\b', translation, re.I))
    for t in LATIN_TOKEN.findall(text):
        if t.lower() in _LEAD_PLACEHOLDER:
            return ''
        if verbal and any('inf' in f.split() for f in _analyses_features(t)):
            return ''
    return text.strip(' ,;:')


_CITE_DEBRIS = re.compile(
    r'\b(?:acc|cf|ib|ibid|id|ap|al|sq|sqq|v|vid|etc|l|c|s|p|pp)\.|[A-Z][A-Za-z]*\.|\d')


def _connective(gap):
    """True when the text between two italics, or after the last, is the
    print's own and belongs in the translation: "or", "i. e.", "(for",
    "still called", and the English note the print adds — Aetnaeus's
    "Vulcan, who is said to have had his forge in Mt. Aetna", lustrum's
    "at the end of which the ludi saeculares were celebrated". Not Latin
    (fetialis's ", fetialis,") and not the reference's debris
    (internecinus's "acc. to", satelles's "id. poët."): those are what the
    print writes between the translation and its reference."""
    core = _LEAD_IE.sub(' ', gap.replace('*', ' ')).strip(' ,;:.()')
    if not core:
        return True
    if _CITE_DEBRIS.search(core):
        return False
    return not _reads_latin(core)


def _translation_text(html):
    """A quotation's translation: the italics up to its reference, joined
    by the print's short connectives, and nothing else.

    An aside in brackets stays when it is English ("(for impudent,
    shameless)") and goes when it is the print's Latin paraphrase (emptor
    "(= magno pretio emens)"); one the reference sits inside is cut at its
    bracket (iners "artless (= sine arte…, Hor.)"), and so is an equation
    with Latin after it (ne "much less now I am old = nedum")."""
    its = list(re.finditer(r'<i>(.*?)</i>', html, re.S))
    if not its:
        return ''
    # Spacing kept: text_of strips it, and "still called" needs its.
    raw = lambda s: htmllib.unescape(L.STRIP.sub('', s))
    text, end = raw(its[0].group(1)), its[0].end()
    for m in its[1:]:
        gap = raw(html[end:m.start()])
        if not _connective(gap):
            break
        text += gap.replace('*', ' ') + raw(m.group(1))
        end = m.end()
    else:
        tail = raw(html[end:])
        if _connective(tail):
            text += tail.replace('*', ' ')
    text = re.sub(r'\s*\(([^()]*)\)',
                  lambda m: '' if m.group(1).lstrip().startswith('=')
                  or _reads_latin(m.group(1)) else m.group(0), text)
    while text.count('(') > text.count(')'):
        text = text[:text.rfind('(')]
    # "= nedum", "= pilā ligneā, which he had used just before": the Latin
    # equation goes, up to the print's comma, and the note after it stays.
    text = re.sub(r'\s*=\s*([^=,;]*)',
                  lambda m: '' if _reads_latin(m.group(1)) else m.group(0), text)
    closed = text.rstrip(' ,;:.').endswith(')')
    eng = _example_gloss(text)
    # _example_gloss reads a lone capitalised word as an author's name,
    # which in LSJ's drawer it is. Here the italic is the translation,
    # and "Vulcan", "Hippolytus", "October" are what the print wrote.
    if not eng and not re.search(r'\d', text) and re.search(
            r'(?<![^\W\d_])[^\W\d_]{3,}(?![^\W\d_]|\.)', text):
        eng = text.strip(' ,;:.')
    if closed and eng.count('(') > eng.count(')'):
        eng += ')'
    return eng


def _plain_italics(html):
    """(lead, element class before it, i_start, i_end) for every plain <i>
    at the top level of `html`. The lead is the untagged text between the
    element that closed last and the italic — never the text of an
    element, so a sub-lemma's "Attĭci, ōrum, m." cannot read as Latin —
    cut back to the print's last ':' or ';'."""
    stack, prev_close, prev_cls = [], 0, None
    for m in _TAG_ANY.finditer(html):
        closing, _name, attrs = m.groups()
        if attrs.rstrip().endswith('/'):
            continue
        if closing:
            cls = stack.pop() if stack else ''
            if not stack:
                prev_close, prev_cls = m.end(), cls
            continue
        if not stack and m.group(0) == '<i>':
            end = _complete_el(html, m.start()) or len(html)
            gap = html[prev_close:m.start()]
            parts = re.split(r'[;:]', gap)
            # A Latin word the print's own English sentence runs through
            # is not a quotation: Memmius reads "<i>adjudged guilty of</i>
            # ambitus, <i>went into exile</i>". Off a plain italic, only
            # the print's ':' or ';' starts a quotation.
            lead = '' if prev_cls == '' and len(parts) == 1 else parts[-1]
            yield lead, prev_cls, m.start(), end
        stack.append(_tag_class(m.group(0)))


def _quotation_lead(zone, ev=''):
    """The Latin quotation an L&S candidate definition opens on, or ''."""
    if not DATASET.startswith('lat') or '<i>' not in zone:
        return ''
    # A sub-lemma or an Adv./Subst. block states a form, not a quotation.
    if re.search(r'class="lx-(?:pos|orth)"', zone[:zone.index('<i>')]):
        return ''
    # The print's "idiom: quotation" shape — manus "in manibus esse, <i>to
    # be in everybody's hands</i>: est in manibus oratio, Cic."
    if re.search(r':\s*(?:</[^>]+>\s*)*$', zone) and re.match(
            r'\s*<span class="lx-(?:cit|quote)', ev):
        return ''
    # Only a quotation whose reference Perseus marked: that is what the
    # drawer's example stands on. Where the print's reference is plain
    # text (Arabia "in Arabic, Sol. c. 33") no example can carry the
    # translation, and the row stays as it was.
    if not re.match(r'\s*<span class="lx-bibl"', ev):
        return ''
    for lead, _cls, a, b in _plain_italics(zone):
        return _latin_quotation_lead(lead, L.text_of(zone[a:b]))
    return ''


def _next_outside_citation(html):
    """Offset of the next quotation span that is not inside a citation,
    or None."""
    covered = []
    for m in re.finditer(r'<span class="lx-bibl"', html):
        end = _complete_el(html, m.start())
        if end:
            covered.append((m.start(), end))
    for m in re.finditer(r'<span class="lx-(?:foreign|cit)\b', html):
        if not any(a <= m.start() < b for a, b in covered):
            return m.start()
    return None


# How many examples a sense's drawer holds. Eight, John's call
# 2026-09-08, measured: at four, a drawer showed every quotation the
# print gives for 84% of LSJ senses but only 72% of Lewis & Short's,
# which is the half that reads as truncated. Eight clears 95% and 88%
# for about a quarter more quotation text. The examples arrive in the
# print's own order, so the cap takes the last ones the print gives,
# never a chosen subset; the biggest sense in either lexicon is L&S
# facio α with 176, so no cap short of all of them is not arbitrary.
EXAMPLE_CAP = 8


def examples_of(ill_html, ev, sense_eng='', prev=''):
    """Click-drawer examples: Greek quotation + its LSJ citation.
    English (Greek) only when the print translated that example and the
    English is not the sense gloss itself."""
    items, seen = [], set()
    sense_fold = re.sub(r'\W+', ' ', sense_eng).strip().lower()
    if ill_html:
        greeks = GREEK_SPAN.findall(ill_html)
        eng = L.text_of(GREEK_SPAN.sub('', ill_html)).strip(' ,;:')
        gr = ' '.join(L.text_of(g) for g in greeks).strip(' ,;:')
        if gr:
            eng = _example_gloss(eng)
            if re.sub(r'\W+', ' ', eng).strip().lower() == sense_fold:
                eng = ''
            items.append({'eng': eng, 'gr': gr, 'cit': ''})
            seen.add(gr)
    # Resolve EVERY citation in source order first: "Id." means the
    # last-named author in the PRINT, and the drawer keeps only some
    # citations — resolving inside the keep-loop made οὐσία II.3's
    # "Id. Phdr. 245e" read Aristotle off the last kept citation when
    # the print's antecedent was a skipped "Pl. R. 509b".
    _queue = {}
    p, lr = prev, ''
    # The print's antecedent for "Id." can be a STANDALONE author
    # mention, not just the author inside a citation ("Phld. Mus. p.40
    # … Id. Piet. 15") — walk authors and citations together in source
    # order, and let a bare author update the antecedent.
    bibl_at = []
    for m in re.finditer(r'<span class="lx-bibl"', ev):
        end = ev.find('</span>', m.start())
        bibl_at.append((m.start(), next(each_span(ev[m.start():], 'lx-bibl'), '')))
    auth_at = []
    # A prose mention too ("perh. only in Cicero: … id. Fam. 15, 18, 1").
    for m in re.finditer(r'<span class="lx-author(?: lx-prose)?"[^>]*>([^<]+)</span>', ev):
        # An editor credited with a conjecture is not an antecedent
        # (ἀνάριθμος "(Herm. for μήλων)" then two Sophocles "Id.").
        if re.match(r'(?:for|cj\.|conj\.)\b',
                    L.text_of(ev[m.end():m.end() + 24]).lstrip()):
            continue
        inside = any(s <= m.start() < s + len(b) for s, b in bibl_at)
        if not inside:
            auth_at.append((m.start(), m.group(1).strip()))
    events = sorted([(pos, 'b', b) for pos, b in bibl_at]
                    + [(pos, 'a', a) for pos, a in auth_at])
    for _, kind, val in events:
        if kind == 'a':
            if val and not SAME_AUTH.match(val.rstrip('.')):
                p = val
            continue
        if not re.search(r'class="lx-author"', val):
            tm = re.search(r'class="lx-title"[^>]*>([^<]+)', val)
            owner = author_of_work(tm.group(1)) if tm else ''
            if owner:
                p = owner
        token, p, lr = cite_from(val, p, lr)
        _queue.setdefault(val, []).append(token)

    def cite_of(bibl_html):
        lst = _queue.get(bibl_html)
        return lst.pop(0) if lst else ''

    for block in each_span(ev, 'lx-cit'):
        qm = re.search(r'class="lx-quote"[^>]*>(.*?)</span>', block, re.S)
        bm = re.search(r'<span class="lx-bibl"', block)
        gr = L.text_of(qm.group(1)).strip(' ,;:') if qm else ''
        cit = ''
        if bm:
            inner = list(each_span(block, 'lx-bibl'))
            if inner:
                cit = cite_of(inner[0])
        if not gr:
            continue
        if gr in seen:
            # The same words met twice, the second time with their
            # reference (cacoethes "in medic. lang.", Cels. 5, 28): keep
            # one example and give it the reference, rather than drop it.
            # Only when the words end on a grammar abbreviation, the shape
            # whose kept period made the two copies equal; merging every
            # repeated quotation (241 more) is class 10's round, not this.
            tail = re.search(r'([A-Za-z]+)\.$', gr)
            if cit and tail and tail.group(1).lower() in _GRAM_TAIL:
                for it in items:
                    if it['gr'] == gr and not it['cit']:
                        it['cit'] = cit
                        break
            continue
        # The print glosses some quotations in place — "αἱ πρῶται οὐ.
        # (individuals)" — and that English is the example's context,
        # not apparatus. Whatever text the block holds besides the
        # quote and the citation is that gloss.
        rest_txt = block.replace(qm.group(1), '', 1) if qm else block
        for b in each_span(rest_txt, 'lx-bibl'):
            rest_txt = rest_txt.replace(b, '', 1)
        eng = _example_gloss(L.text_of(rest_txt))
        if re.sub(r'\W+', ' ', eng).strip().lower() == sense_fold:
            eng = ''
        seen.add(gr)
        items.append({'eng': eng, 'gr': gr, 'cit': cit})
        if len(items) >= EXAMPLE_CAP:
            break
    # Not every quotation is wrapped in lx-cit. ἐπί E. reads
    # "κτεῖνον δʼ ἐ. μηλοβοτῆρας as well, Il. 18.529" as a bare
    # lx-foreign, its italic translation, and a bibl. The reference is
    # what makes it a quotation: definitional Greek has none after it.
    if len(items) < EXAMPLE_CAP:
        rest = ev
        for block in each_span(ev, 'lx-cit'):
            rest = rest.replace(block, '', 1)
        for m in re.finditer(r'<span class="lx-foreign"[^>]*>(.*?)</span>',
                             rest, re.S):
            gr = L.text_of(m.group(1)).strip(' ,;:')
            after = rest[m.end():]
            nxt = _next_outside_citation(after)
            window = after[:nxt] if nxt is not None else after
            bibl = next(each_span(window, 'lx-bibl'), '')
            if not gr or gr in seen or not bibl:
                continue
            # "opp. ἐμπύριος and αἰθέριος": the second of a named pair has
            # only "and" before it, so look past the conjunction and the
            # word it joins.
            lead = L.text_of(rest[:m.start()])[-48:]
            lead = re.sub(r'\s+(?:and|or)\s*$', '', lead, flags=re.I)
            lead = re.sub(r'[Ͱ-Ͽἀ-῿][Ͱ-Ͽἀ-῿̀-ͯ]*[,;]?\s*$', '', lead)
            if REF_LEAD.search(lead):
                continue          # a word being pointed at, not quoted
            eng = L.text_of(re.sub(r'<span class="lx-bibl".*$', '', window,
                                   flags=re.S)).strip(' ,;:')
            eng = _example_gloss(eng)
            if re.sub(r'\W+', ' ', eng).strip().lower() == sense_fold:
                eng = ''
            cit = cite_of(bibl)
            seen.add(gr)
            items.append({'eng': eng, 'gr': gr, 'cit': cit})
            if len(items) >= EXAMPLE_CAP:
                break
    # Lewis & Short's quotation in plain text, its translation in a plain
    # italic, and the reference after it (see _latin_quotation_lead).
    # Last, so the print's own marked quotations keep their places in the
    # drawer and this only ever adds.
    if len(items) < EXAMPLE_CAP and DATASET.startswith('lat'):
        quotes = []
        for lead, cls, a, b in _plain_italics(ev):
            gr = ('' if cls in _FORM_CLS
                  else _latin_quotation_lead(lead, L.text_of(ev[a:b])))
            quotes.append((gr, a, b))
        for j, (gr, a, b) in enumerate(quotes):
            if not gr or gr in seen:
                continue
            # The translation runs to the reference, through the print's
            # "or" and "i. e." italics ("<i>an action for a personal
            # injury</i> or <i>affront</i>, Cic."); it stops at the next
            # quotation, and at a citation the print marked, whose
            # reference is its own.
            stop = next((a2 for g2, a2, _b2 in quotes[j + 1:] if g2), len(ev))
            nxt = re.search(r'<span class="lx-(?:foreign|cit)\b', ev[b:stop])
            end = b + nxt.start() if nxt else stop
            bm = re.search(r'<span class="lx-bibl"', ev[b:end])
            if not bm:
                continue
            bibl = next(each_span(ev[b + bm.start():], 'lx-bibl'), '')
            if not bibl:
                continue
            eng = _translation_text(ev[a:b + bm.start()])
            if not eng:
                continue
            if re.sub(r'\W+', ' ', eng).strip().lower() == sense_fold:
                eng = ''
            # Resolved against the print's own antecedent rather than the
            # shared queue: an identical "id." wrapper earlier in the
            # evidence has already taken that queue's token.
            prev = ''
            for am in re.finditer(r'class="lx-author"[^>]*>([^<]+)', ev[:b + bm.start()]):
                if not SAME_AUTH.match(am.group(1).strip().rstrip('.')):
                    prev = am.group(1).strip()
            cit = cite_from(bibl, prev, '')[0]
            seen.add(gr)
            items.append({'eng': eng, 'gr': gr, 'cit': cit})
            if len(items) >= EXAMPLE_CAP:
                break
    if items and not items[0]['cit']:
        stripped = ev
        for block in each_span(ev, 'lx-cit'):
            stripped = stripped.replace(block, '', 1)
        if re.match(r'\s*<span class="lx-bibl"', stripped):
            inner = next(each_span(stripped, 'lx-bibl'), None)
            if inner:
                items[0]['cit'], _, _ = cite_from(inner, '', '')
    return items


GREEK_TOKEN = re.compile(
    r"[Ͱ-Ͽἀ-῿](?:[Ͱ-Ͽἀ-῿̀-ͯ\u0300-\u036f]|[ʼ'’])*\.?"
)
LATIN_TOKEN = re.compile(
    r"[A-Za-zāēīōūȳăĕĭŏŭäëïöüÿĀĒĪŌŪĂĔĬŎŬ]+"
)

# Analyses buckets keyed by 2-letter fold; lemma sets keyed by folded form.
_AN_BUCKETS = {}
_WORK_OWNER = {}
_WORK_OWNERS = {}
_AN_LEMMAS = {}
_AN_SPELT = {}
_MISSING = object()


def _analyses_bucket(folded):
    name = extract.bucket_name(folded)
    if name not in _AN_BUCKETS:
        try:
            _AN_BUCKETS[name] = extract.load_bucket(ANALYSES, name) or {}
        except (OSError, KeyError, ValueError):
            _AN_BUCKETS[name] = {}
    return _AN_BUCKETS[name]


def lemmas_of(form):
    """Folded Morpheus lemmas for a surface form. Empty if the pack
    has no parse — caller still has exact-match and abbreviation."""
    f = fold(form)
    if not f:
        return frozenset()
    hit = _AN_LEMMAS.get(f)
    if hit is not None:
        return hit
    rec = _analyses_bucket(f).get(f)
    out = set()
    if isinstance(rec, dict):
        for parses in rec.values():
            for row in parses:
                if row and row[0]:
                    out.add(fold(row[0]))
    out = frozenset(out)
    _AN_LEMMAS[f] = out
    return out


def lemmas_spelt(form):
    """Folded lemmas for this exact spelling, or None when the pack does
    not hold it.

    The analyses pack is keyed by the total fold, and a folded record is a
    dict of the accented surfaces under it: "h" holds ἡ, ἥ, ἧ, ᾗ, ἠ’, ἤ,
    ἦ and ᾖ. `lemmas_of` pools all of them, which is why ἢ could mark
    under ὁ and αἱ under εἰ. When the pack knows the spelling in front of
    us, its own parses are the answer.

    None, not an empty set, when the spelling is absent: the print writes
    a grave for an oxytone before another word, an enclitic's accent on
    the word before it, and quantity marks Morpheus does not, and the
    fold is the only way in for those.
    """
    f = fold(form)
    if not f:
        return None
    key = unicodedata.normalize('NFC', form)
    hit = _AN_SPELT.get((f, key))
    if hit is not None:
        return hit if hit is not _MISSING else None
    rec = _analyses_bucket(f).get(f)
    parses = rec.get(key) if isinstance(rec, dict) else None
    if parses is None:
        _AN_SPELT[(f, key)] = _MISSING
        return None
    out = frozenset(fold(row[0]) for row in parses if row and row[0])
    _AN_SPELT[(f, key)] = out
    return out


def _analyses_features(form):
    """Morpheus feature strings for a surface form ("pres inf act",
    "masc gen pl") — the part of the parse lemmas_of throws away."""
    f = fold(form)
    if not f:
        return frozenset()
    rec = _analyses_bucket(f).get(f)
    out = set()
    if isinstance(rec, dict):
        for parses in rec.values():
            for row in parses:
                if row and len(row) > 3 and row[3]:
                    out.add(row[3])
    return frozenset(out)


# The Greek token pattern runs on the whole Greek block, so a token can
# carry off the punctuation that follows it: U+037E ";" and U+0387 "·"
# are Greek-block characters, and the trailing "." the abbreviation rule
# needs is also the print's full stop. Marked spans keep their letters
# and hand the punctuation back to the surrounding text.
_MARK_TAIL = re.compile('[.\u003b\u00b7\u037e\u0387\u0374]+$')


def _prefix_abbr(core, lemma):
    """LSJ abbreviates a diphthong-initial headword to the diphthong —
    εὔ. for εὔθυμος, οἰ. for οἰνώδης, αὐ. for αὐτοσχέδιος. Accepted only
    when the letters are literally the head's own opening, breathings and
    accents included, so "εἰ." marks εἰκονικός and not the conjunction."""
    if not (1 < len(core) < len(lemma)):
        return False
    a = unicodedata.normalize('NFC', core).lower()
    b = unicodedata.normalize('NFC', lemma).lower()
    return b.startswith(a)


def mark_headword(gr, lemma):
    """Wrap every instance of the lemma in an example — dictionary
    form, inflected, or LSJ's abbreviation of it (λ., τ., ἐ., εὔ.).
    Inflection is Morpheus: a token highlights if any parse's lemma
    folds to this entry, so θέσθαι / θεὶς match τίθημι and τι does not."""
    if not gr or not lemma:
        return htmllib.escape(gr)
    folded = fold(lemma)
    init = folded[:1]

    def is_head(tok):
        core = _MARK_TAIL.sub('', tok)
        abbr = tok.endswith('.')
        f = fold(core)
        if not f:
            return ''
        if abbr and f == init:
            return 'abbr'
        if abbr and len(f) <= 4 and _prefix_abbr(core, lemma):
            return 'abbr'
        if f == folded:
            return 'form'
        # Greek only, and the spelling first. The Greek fold destroys
        # the breathing and the accent, which Morpheus keeps and which
        # tell ἡ from ἤ from ᾗ. The Latin fold destroys i/j, u/v and the
        # quantity marks, which are spelling conventions and not
        # distinctions: read against the exact spelling, L&S loses
        # majoribus under magnus, jugis under iugum and sublata under
        # tollo, and gains nothing. Latin keeps the pooled lookup.
        if not DATASET.startswith('lat'):
            spelt = lemmas_spelt(core)
            if spelt is not None:
                return 'form' if folded in spelt else ''
        return 'form' if folded in lemmas_of(core) else ''

    tok_re = LATIN_TOKEN if DATASET.startswith('lat') else GREEK_TOKEN
    out, last = [], 0
    for m in tok_re.finditer(gr):
        out.append(htmllib.escape(gr[last:m.start()]))
        tok = m.group(0)
        kind = is_head(tok)
        if kind:
            # The abbreviation's period is part of the word; a full stop
            # or an ano teleia after a written-out form is not.
            body = _MARK_TAIL.sub('', tok)
            tail = tok[len(body):]
            if kind == 'abbr' and tail.startswith('.'):
                body, tail = body + '.', tail[1:]
            out.append(f'<b class="hw">{htmllib.escape(body)}</b>')
            out.append(htmllib.escape(tail))
        else:
            out.append(htmllib.escape(tok))
        last = m.end()
    out.append(htmllib.escape(gr[last:]))
    return ''.join(out)




# ---------------------------------------------------------------- record
# Stored text keeps a closed set of inline marks — cue, hw, rub, eq-mark,
# sublem, and a language span — because those are facts about the text.
# Everything else the pack marked up (lx-tns, lx-gram, lx-itype, lx-orth,
# lx-etym …) is unwrapped: the words stay, the classification goes.

_GREEK_CH = re.compile(r'[Ͱ-Ͽἀ-῿]')
_KEEP_CLS = {'cue', 'hw', 'rub', 'eq-mark', 'sublem'}
_TAG = re.compile(r'<(/?)(span|b|i)\b([^>]*)>', re.I)
_EDITORIAL_LETTERS = r'A-Za-zÀ-ÖØ-öø-ÿĀ-ſͰ-Ͽἀ-῿\u02bc\u0300-\u036f'
_EDITORIAL_BODY = (
    r'([' + _EDITORIAL_LETTERS + r']{1,12}'
    r'(?: [' + _EDITORIAL_LETTERS + r']{1,12})*)')
_UNOWNED_ANGLE = re.compile(r'<' + _EDITORIAL_BODY + r'>')
_ENTITY_ANGLE = re.compile(r'&lt;' + _EDITORIAL_BODY + r'&gt;', re.I)
_SPLIT_ENTITY_ANGLE = re.compile(
    r'&lt;([' + _EDITORIAL_LETTERS + r']{1,12})(</(?:span|b)>)&gt;', re.I)
_DOUBLE_ENTITY_I = re.compile(r'&amp;lt;(i)&amp;gt;', re.I)
_SOURCE_ENTITY_I = re.compile(r'&lt;(i)&gt;', re.I)
_HTML_TAG_NAMES = {
    'a', 'abbr', 'address', 'area', 'article', 'aside', 'audio', 'b', 'base',
    'bdi', 'bdo', 'blockquote', 'body', 'br', 'button', 'canvas', 'caption',
    'cite', 'code', 'col', 'colgroup', 'data', 'datalist', 'dd', 'del',
    'details', 'dfn', 'dialog', 'div', 'dl', 'dt', 'em', 'embed', 'fieldset',
    'figcaption', 'figure', 'footer', 'form', 'h1', 'h2', 'h3', 'h4', 'h5',
    'h6', 'head', 'header', 'hgroup', 'hr', 'html', 'i', 'iframe', 'img',
    'input', 'ins', 'kbd', 'label', 'legend', 'li', 'link', 'main', 'map',
    'mark', 'menu', 'meta', 'meter', 'nav', 'noscript', 'object', 'ol',
    'optgroup', 'option', 'output', 'p', 'picture', 'pre', 'progress', 'q',
    'rp', 'rt', 'ruby', 's', 'samp', 'script', 'search', 'section', 'select',
    'slot', 'small', 'source', 'span', 'strong', 'style', 'sub', 'summary',
    'sup', 'table', 'tbody', 'td', 'template', 'textarea', 'tfoot', 'th',
    'thead', 'time', 'title', 'tr', 'track', 'u', 'ul', 'var', 'video', 'wbr',
}
_INLINE_TAG = re.compile(r'<[^>]+>')
_GREEK_STRETCH = re.compile(
    r'[Ͱ-Ͽἀ-῿](?:[Ͱ-Ͽἀ-῿̀-ͯ\u0300-\u036f\s··,;:!?()\[\]ʼ’\'"“”–—-]*[Ͱ-Ͽἀ-῿])'
)


def _wrap_greek_text(text):
    """Wrap text stretches that contain at least two Greek letters."""
    return _GREEK_STRETCH.sub(
        lambda m: f'<span lang="grc">{m.group(0)}</span>', text)


def _wrap_unmarked_greek(html):
    """Tag Greek in a Latin field without nesting a second grc span."""
    out, stack, pos = [], [], 0
    for m in _INLINE_TAG.finditer(html):
        text = html[pos:m.start()]
        out.append(text if any(stack) else _wrap_greek_text(text))
        tag = m.group(0)
        out.append(tag)
        if tag.startswith('</'):
            if stack:
                stack.pop()
        else:
            stack.append(bool(re.search(r'\blang="grc"', tag, re.I))
                         or (stack[-1] if stack else False))
        pos = m.end()
    text = html[pos:]
    out.append(text if any(stack) else _wrap_greek_text(text))
    return ''.join(out)


def _editorial_angle(match):
    inner = match.group(1)
    return match.group(0) if inner.casefold() in _HTML_TAG_NAMES else f'⟨{inner}⟩'


# Perseus sets the print's supplied-text brackets on either side of the
# element that holds the letters as often as inside it. θάλλω writes
# "&lt; <span class="lx-cit"><span class="lx-quote">δένδρεα&gt; τέθηλε"
# — the opening bracket outside the citation and the closing one inside
# the quotation — and τοίνυν "(&lt;<span class="lx-foreign">τῷ</span>&gt;
# add. Kaibel)", both outside. Eleven Greek entries each. The bracket
# belongs with its letters, inside the element, or the example ships
# "δένδρεα> τέθηλε" with the opening half stranded in the prose.
_ANGLE_OPEN_OUTSIDE = re.compile(
    r'&lt;\s*(<(?:span|b)\b[^>]*>(?:\s*<span\b[^>]*>)?)'
    r'([' + _EDITORIAL_LETTERS + r']{1,12})&gt;', re.I)
_ANGLE_BOTH_OUTSIDE = re.compile(
    r'&lt;(<(?:span|b)\b[^>]*>)([' + _EDITORIAL_LETTERS + r']{1,12})'
    r'(</(?:span|b)>)&gt;', re.I)
# The print's lacuna mark, "< . . >", in two Hesychius glosses (πακοτή,
# χίδαι). Same brackets as supplied text, so the same glyphs.
_ANGLE_LACUNA = re.compile(r'&lt;\s*\.\s*\.\s*&gt;')
# Perseus debris, not the print: a closing bracket with no opening one
# anywhere in the entry, standing between whitespace and a Greek word
# (ἐδάφιον "Dim. of &gt;ἔδαφος 4") or between a digit and a comma
# (Ἑλλαδαρχέω "Ἑλλαδάρχης 3&gt;,"); an opening one directly before the
# sense's close (nine L&S entries end "§ 83.&lt;</div>"); a closing one
# that opens a sense body (L&S acanthus). Derivation arrows are paired
# with letters on both sides — δοκίς's "(m&gt;n)", βλάξ's "βλᾱ- &lt;
# μλᾱ-" — and are left alone by every pattern here.
_ANGLE_STRAY_CLOSE = re.compile(
    r'(?<=\s)&gt;(?=[Ͱ-Ͽἀ-῿])|(?<=\d)&gt;(?=,)')
_ANGLE_STRAY_OPEN = re.compile(r'\s*&lt;\s*(?=</div>|$)')
_ANGLE_STRAY_LEAD = re.compile(r'(<div class="lx-sense"[^>]*>)\s*&gt;\s*')


def _source_editorial_angles(html):
    """Turn source editorial brackets into text before Greek wrapping."""
    html = _ANGLE_OPEN_OUTSIDE.sub(
        lambda m: f'{m.group(1)}⟨{m.group(2)}⟩', html)
    html = _ANGLE_BOTH_OUTSIDE.sub(
        lambda m: f'{m.group(1)}⟨{m.group(2)}⟩{m.group(3)}', html)
    html = _ANGLE_LACUNA.sub('⟨..⟩', html)
    html = _ANGLE_STRAY_OPEN.sub('', html)
    html = _ANGLE_STRAY_LEAD.sub(r'\1', html)
    if '&lt;' not in html:
        html = _ANGLE_STRAY_CLOSE.sub('', html)
    html = _SPLIT_ENTITY_ANGLE.sub(
        lambda m: f'⟨{m.group(1)}{m.group(2)}⟩', html)
    html = _DOUBLE_ENTITY_I.sub(lambda m: f'⟨{m.group(1)}⟩', html)
    html = _SOURCE_ENTITY_I.sub(lambda m: f'⟨{m.group(1)}⟩', html)
    html = _ENTITY_ANGLE.sub(_editorial_angle, html)
    return _UNOWNED_ANGLE.sub(_editorial_angle, html)


# An author the print put INSIDE a sentence. LSJ writes ὁ A as "the
# oldest and in Hom. the commonest sense : freq. also in Hdt. (1.86,
# 5.35, al.)", and both authors carry an lx-author span. The citation
# strip removed every such span, so the entry shipped "the oldest and in the
# commonest sense : freq. also in (al.)" — grammatical objects gone and
# the prose left with holes in it. 2,637 Greek entries and 116 Latin
# read like that, 3,136 holes in all.
#
# The distinction is structural, not statistical. An lx-author nested in
# an lx-bibl is a citation and is extracted as one; a BARE lx-author,
# outside any bibl, is a citation only when a linking abbreviation or a
# locus follows it — "Moschio ap. Ath. 5.208a", "Suid. s.v. ἄβαξ",
# σύγκαυσις's "Gal. 15.895". When an ordinary English word follows
# instead, the author is the sentence's own subject or object: Hsch.
# EXPLAINS, Aristarch. WROTE, Ar.Byz. READ, in Hom. ONLY.
#
# The span is MARKED, not removed. entrylib's REF_CLASS counts an
# lx-author as a reference, and a closing reference is what arms the
# segmentation to cut a new definition at the next plain <i>. Unwrapping
# the span took that signal away with it: οἴχομαι's "in Hom. sts. means
# <i>absent, away,</i>" stopped cutting, and the gloss the cut used to
# produce stayed buried in the evidence. Eight entries lost a printed
# definition that way before this was understood.
#
# So the class becomes "lx-author lx-prose". REF_CLASS matches on a word
# boundary and still sees a reference, so every cut lands where it did.
# The eight strippers and chip collectors in this file all spell it
# `class="lx-author"` with the closing quote and no longer match, so the
# words survive and no chip is minted from them. _strip_citations
# unwraps a marked span instead of dropping it. At emit time _norm_inline reads the first
# class token, still lx-author, and unwraps the span as it always did —
# the pack ships plain text.
_AUTHOR_OPEN = re.compile(r'<span[^>]*class="lx-author"[^>]*>', re.I)
_BIBL_OPEN = re.compile(r'class="lx-(?:bibl|cit)\b', re.I)
# The word after the author, skipping tags. Capitalised followers are
# left alone: "Hom. Il. 1.1" is a citation and Il. is its work.
# One comma or semicolon may stand between the author and the sentence
# that continues past it: "First in Hdt., never in Trag., rare in Att."
# and "[First syll. short in Hes., long in A.R.]" are prose, and
# requiring the word to follow immediately left 236 of them stripped.
# The separator changes nothing about the test that follows it — a
# citation follower after a comma ("Hom., cf. …") is still a citation,
# because cf. and al. and etc. are in the set below.
_AFTER_AUTHOR = re.compile(
    r'^\s*(?:</?[a-z][^>]*>\s*)*(?:\(\?\)\s*)?([,;])?\s*([a-zë]{1,12})\.?')
# "in" is the ambiguous one. "Anon. in Rh. 174.6." and "Alex.Aphr. in
# Metaph." are commentary citations and the author heads them; "freq. in
# Hom. in the phrase ὅρκια δηλήσασθαι" is a sentence. The word after the
# "in" decides: a capitalised work title means citation, an English
# determiner or common noun means prose.
_IN_THEN = re.compile(
    r'^\s*(?:</?[a-z][^>]*>\s*)*(?:\(\?\)\s*)?[,;]?\s*in\.?\s+'
    r'(?:</?[a-z][^>]*>\s*)*([A-Za-z][A-Za-z.]*)')
# What follows the "in" decides, and raw capitalisation is not enough in
# either direction. "Phlp. in de An. 17.33" opens its title with a
# lowercase Latin preposition, and reading that as prose put a stray
# "Phlp." in ἄλγυνσις's gloss. "twice in Hom., in Med." capitalises a
# grammatical label that is not a work at all, and reading THAT as a
# title left the ὁ-class hole open on δαμάζω and ἀκούω.
_TITLE_AFTER_IN = frozenset(('de',))          # Latin title opener
_LABEL_AFTER_IN = frozenset(
    # Voice, dialect and register labels: prose, never a work. "Ep." is
    # deliberately absent — it is the Epic dialect in LSJ and Epistulae
    # in Lewis & Short, and one transform runs both, so the safe reading
    # is the one that leaves a citation alone.
    'Med Pass Act Dor Att Ion Aeol Com Trag Prose'.split())
# Linking abbreviations and Latin work-title openers: the author belongs
# to the citation that follows, however bare its span. ap. alone covered
# 4,991 of the first census's 8,423 candidates, s.v. another 1,916.
_CITE_FOLLOWER = frozenset((
    'ap apud ad ib ibid cf v vid l ll sq sqq s sv p pp et al seq sch '
    'praef de pro ep fr '
    # Lewis & Short's "Cic. poët. ap. Non.": the author's verse fragment.
    'poët poet '
    # "in" is handled separately by _IN_THEN, not listed here: it is a
    # citation link before a work title and English before anything else.
    ).split())
# The other half of the same sentence. ὁ writes "freq. also in Hdt.
# (1.86, 5.35, al.)": Hdt. is the object of "in" and the parenthesis
# holds its loci, so no prose word follows and the test above cannot see
# it. Look behind instead — but only when a parenthesis follows, which is
# what separates this from "cf. Phld. Rh. 2.30S." where the locus simply
# comes next. Both conditions are needed: the governor alone matched
# 5,833 places, 2,136 of them behind "cf.", nearly all citations. With
# the parenthesis required and cf. excluded it is 265 Greek and 2 Latin,
# and they read as prose — "freq. in Hom. (mostly in Il.)", "perh. only
# in Cicero (and in him only in two passages)".
_AUTHOR_GOVERNOR = re.compile(
    r'(?:^|[\s>(;,])(?:in|by|with|of|from|to|than|for|after|before|among|'
    r'esp\.|freq\.|also|so|and|or|not)\s*$', re.I)
_PAREN_NEXT = re.compile(r'^\s*(?:</?[a-z][^>]*>\s*)*\(')
# A linking abbreviation IN FRONT of the author settles it before any
# test of what follows: "cf. Hsch.", "Hp. ap. Gal.", "acc. to Did. ap."
# are citations however the sentence continues afterwards. Without this,
# δαηρόν's "EM 244.42, cf. Hsch.; perh. to be read in Emp. 90" read the
# "; perh." after Hsch. as prose continuing, marked Hsch. prose, and so
# collected no chip for it — and because "cf. Hsch." sits past the first
# citation it is in the evidence zone and never rendered either. The
# reader simply lost Hesychius. 87 authors were in that position.
# Two authors joined by and/or are one citation naming both — "Antyll.
# or Heliod. ap. Ath. 5.208a", "Ruf. and Aspasia ap. Aët. 16.50". The
# conjunction is ordinary English, so the follower test read the first
# author as prose and kept it while the second was stripped as the
# citation it is: ἀγγειολογέω shipped "Antyll. or ap" and γράσος "A. or
# ap. s.v." Neither half is prose; the pair belongs to the citation.
# The inner group must not match a span, or it swallows the very author
# span the pattern is looking for and the pair never matches.
_PAIR_NEXT = re.compile(
    r'^\s*(?:</?[a-z][^>]*>\s*)*(?:and|or)\s+'
    r'(?:</?(?:i|b|em|sup|sub)[^>]*>\s*)*<span[^>]*class="lx-author"', re.I)
_CITE_LEAD = re.compile(
    r'(?:^|[\s;,(])(?:cf|v|vid|ap|apud|ib|ibid|see|s\.\s*v|q\.\s*v)\.\s*$',
    re.I)
_STRIP_TAGS = re.compile(r'<[^>]+>')
_TAG_ANY = re.compile(r'<(/?)(\w+)([^>]*)>')

# A bare author that IS a citation is a citation Perseus forgot to wrap.
# "Suid. s.v. ἄβαξι", "Crito ap. Gal. 13.878", "Hdn.Gr. ap. Sch. Il.
# 8.178" carry the same author, link and locus as any lx-bibl, only the
# lx-bibl is missing. Stripping the author span alone left the rest in
# the gloss — 2,264 Greek rows read like ἀβάκιον's "slabs (?) in
# theatre, s.v. ἄβαξι" — and minted no chip, so the reader lost both
# ways. Wrapping author and tail in the lx-bibl the print's markup
# implies gives every consumer the shape it already handles: the strip
# takes the citation whole, unique_authors names the author, and the
# example extractor reads it as the quotation's reference.
#
# The tail is a closed grammar of citation tokens, each anchored on the
# last: apud plus an author, s.v. plus the Greek lemma named, a work
# title, a locus, ibid., "l.c.", and — because "Antyll. or Heliod. ap.
# Ath." is one citation naming two authors — and/or plus another author
# not marked prose. Anything else ends the citation, and its final
# period is the sentence's, not the citation's.
_TAIL_LOCUS = (r'(?:[ivx]{1,4}\s+)?(?:\(\d+\)\.)?\d+(?:\.\s?\d+)*(?:\(\d+\))?(?:\.\d+)*(?:[a-z]\d*)?'
               r'(?=[\s,;:.)A-Z]|$)')
_TAIL_STEPS = [
    ('poet', re.compile(r'\s*po[eë]t\.(?=\s)')),
    # Lewis & Short writes "ap" without its period as often as with.
    ('ap', re.compile(r'\s*(?:,\s*)?ap(?:\.|(?![A-Za-z]))\s*(?=<span[^>]*class="lx-(?:author|bibl)"|<i class="lx-title">|'
                      r'(?:eund|Sch|Id)\.|[A-Z][A-Za-z]{0,3}\.(?=[\s,;:)]|$))')),
    # The author after "ap." in plain text: "ap. eund.", "ap. Stob.",
    # "ap. J." — an abbreviation of up to four letters.
    ('name', re.compile(r'\s*(?:eund|Sch|Id|[A-Z][A-Za-z]{0,3})\.(?=[\s,;:)]|$)')),
    # "Enn. ap. Paul. ex Fest. p. 9": the epitome behind the epitomist.
    ('ex', re.compile(r'\s*ex\s*(?=<span[^>]*class="lx-(?:author|bibl)")')),
    # Lewis & Short sets the lemma in small capitals ("Fest. S. V. NEC")
    # and abbreviates sub hac voce ("s. h. v.") where the entry is the
    # lemma itself; then no lemma follows and the page comes next.
    ('sv', re.compile(r'\s*[sS]\.\s*[vV]\.\s*(?=<span class="lx-foreign"|[Ͱ-Ͽἀ-῿A-Za-z])'
                      r'|\s*s\.\s*h\.\s*v\.(?=[\s,])')),
    # The lemma named: one word, in either script (L&S "Fest. s.v.
    # abacus"), or two when the first is a proclitic the lemma needs
    # (τιτυννός "Suid. s.v. ἐκ τιτυννῶν"). A second bare word otherwise
    # is the gloss that follows.
    ('greek', re.compile(r'\s*(?:(?:ἐκ|ἐξ|ἐν|εἰς|ἐς|ἀπό|ἀπʼ|κατά|κατʼ|πρός|ὑπό|ὑπʼ|διά|διʼ|ἐπί|ἐπʼ|'
                         r'παρά|περί|σύν|ὁ|ἡ|τό|οἱ|αἱ|τά|τοῦ|τῆς|τῷ|τῇ|τόν|τήν|τούς|τάς|τῶν|τοῖς|ταῖς|οὐ|οὐκ|μή)'
                         r'\s+)?[Ͱ-Ͽἀ-῿A-Za-z][^\s<,;:.)]*')),
    ('in', re.compile(r'\s*in\s*(?=<i class="lx-title">)')),
    # A page reference may follow the lemma's comma ("s. v. topper, p.
    # 352") and carry the line after the page ("p. 281, 23 Müll.").
    ('locus', re.compile(r'\s*(?:,?\s*p\.\s*\d+(?:,\s*\d+)?(?:\s*[A-Z]\.)?|ll\.\s*cc\.|l\.\s*c\.|'
                         r'ib(?:id)?\.(?:\s*' + _TAIL_LOCUS + r')?|' + _TAIL_LOCUS + r')')),
    # A second locus in the same work, after the print's comma: "Dsc.
    # 1.12, 5.75", "Test.Epict. 4.28, 6.29". Only one with a point in it:
    # ", 3 kinds of" is prose.
    ('locus2', re.compile(r'\s*,\s*(?=\d+\.\d)' + _TAIL_LOCUS)),
    ('pair', re.compile(r'\s*(?:and|or)\s+(?=<span[^>]*class="lx-author")')),
    # The editor's query on an attribution: ἡμικυκλοειδής "Heliod. (?)
    # ap. Orib. 46.11.34".
    ('query', re.compile(r'\s*\(\?\)')),
    # An editor's siglum after the locus ("Fr. 36.10J.", "p.54 R.") and
    # a parenthesised page reference ("(p.470.15 W.)").
    ('siglum', re.compile(r'\s*[A-Z]\.(?=[\s,;:)]|$)')),
    ('page', re.compile(r'\s*\((?:p\.\s*)?[\d.]+(?:\s*[A-Z]\.)?\)')),
    # Lewis & Short's editors, named after the page: "p. 262 Müll.",
    # "p. 210 Rib.", 5,361 times after a marked citation's close. A
    # closed list, never a pattern: the next citation's author ("Verg.",
    # "Serv.") and LSJ's etymological "Lat." stand in the same place.
    # Latin only — the 21 hits in LSJ are editors named after a Greek
    # form, "(ἐπαινέσαι Bekk.)", and not a locus at all.
    ('editor', re.compile(r'\s*(?:Müll|Rib|Weissenb|Drak|Orell|Spald|Ruhnk|Oud|Vahl|Lachm|'
                          r'Fleck|Schneid|Madv|Forbig|Merk|Bekk|Dind|Halm|Hertz|Momms|Bip|'
                          r'Roth|Kayser|Sillig|Zumpt|Kritz|Nipp|Dietsch|Gron|Heins|Burm|Wagn)'
                          r'\.(?=[\s,;:)—]|$)')),
]
# "Crito ap.", "Decr.Byz. ap.", "Ps.-", "Sch." in plain text in front
# of a marked author or citation: the citation begins there.
# A name: a capitalised word ("Crito", "Decr.Byz.", "Ps.-Plu.") or a
# siglum of up to three capitals ("EM", "AB"). Never a run of four —
# the Twelve Tables' "PraeTOR. ARBITROS. TRES. DATO. ap. Fest." is a
# quotation, and reading "TRES. DATO." as the author cut it in half.
_LEAD_NAME = (r'(?:[A-Z][a-zà-ÿ][A-Za-zÀ-ÿ]*|[A-Z]{1,3})'
              r'(?:\.-?[A-Z][A-Za-zÀ-ÿ]*)*(?:\.\s*|\s+)')
_LEAD_PATTERN = (
    # "Att.ap." runs the name into the link with no space; "Enn. ap Non."
    # drops the link's period. Both are Lewis & Short, 30 rows between
    # them, and both left the gloss ending "Att." or "Enn. ap".
    # The chain may be more than one link long — "Gloss. ap. Paul. ex
    # Fest.", "Plaut. ap. Paul. ex Fest.", "Lex Serv. Tullii ap. Fest."
    # — and every link belongs to the citation, or the gloss ends "acc.
    # to Gloss. ap". A plain "Sch." or "Ps.-" after the last "ap." is
    # the link to the marked citation ("Tyrannio ap.Sch. <Il. 1.1>"),
    # not a lead of its own: read as one, it left "Tyrannio ap." behind.
    r'(?<![A-Za-z])(?:(?:(?:' + _LEAD_NAME + r'){0,3}ap(?:\.|(?![A-Za-z]))\s*)+'
    r'(?:(?:Sch|eund|Id)\.\s*|Ps\.-)?'
    r'(?:[A-Z][a-z]+\.?\s+ex\s+)?'
    # "Paul. ex Fest. p. 9 Müll." — Paulus's epitome of Festus, the Latin
    # "ap." chain; 1,674 of the 1,676 "Name. ex" leads in L&S are Paulus
    # and LSJ has none. The name is required: a quotation can end on ex.
    r'|[A-Z][a-z]+\.?\s+ex\s+'
    r'|Ps\.-|Sch\.\s+)')
_LEAD_APUD = re.compile(_LEAD_PATTERN)
_LEAD_APUD_AT = re.compile(_LEAD_PATTERN + r'\Z')


def _lead_before(html, start):
    """The longest lead ending exactly at `start`, or None.

    A plain search over the window in front of a citation returns the
    FIRST lead in it, and a window of 60 characters often holds two:
    cohors reads "Varr. ap. Non. l. l.; Glaucia ap. <Cic. de Or. 2, 65>",
    and "Varr. ap." came back, ended somewhere else, and "Glaucia ap."
    was left in the gloss. 128 marked citations in Lewis & Short sat
    behind an earlier lead that way."""
    return _LEAD_APUD_AT.search(html, max(0, start - 60), start)


_LEAD_RUN = re.compile(r'((?:' + _LEAD_NAME + r'){1,3})(ap(?:\.|(?![A-Za-z]))\s*)')


def _lead_author_edits(html, start, end, quotes):
    """Insertions putting each name in the lead html[start:end] that
    cites through "ap." in an author span. Perseus marks the chains it
    did mark that way — "<author>Archig.</author> ap. <author>Gal.</author>
    8.651", "<author>Plaut.</author> Fragm. ap. <bibl>Diom.</bibl>" — and
    unique_authors reads every author span in the wrapper, so the plain
    lead's name chipped nowhere: αἰθρήεις showed "Pi." for "Pherenic. ap.
    Sch. Pi. O. 3.28" and annicto "Fest." for "Naev. ap. Paul. ex Fest."
    The whole run is the name, as _wrap_plain_citations reads "Carm.
    Marci ap. Fest."; "Paul. ex" and the plain "Sch."/"eund." link are
    not names of their own.

    Insertions, not a replacement: the lead can hold the close of an
    earlier wrapper (ἐπηγκενίδες "Rhian. ap. Sch. Od. l.c." closes
    Rhian.'s after "ap."), and a replacement across it emitted "Sch."
    twice. Inside a quotation nothing is marked: the example extractor
    reads a quotation's first author span as where its Latin ends, and
    the merged span (T13) affecto "dominationes, Sall. Fragm. ap. Aug.
    Civ. Dei, 3, 17: caelum" lost its Latin to "ap. : caelum"."""
    if any(a <= start < b for a, b in quotes):
        return []
    out = []
    for m in _LEAD_RUN.finditer(html, start, end):
        name = m.group(1).rstrip()
        if name.rstrip('.') in _SOURCE_LABELS:
            continue
        # "Cic. Fragm. ap. Prisc." is Cicero, as Perseus marks it where it
        # did ("<author>Cic.</author> Fragm. ap."); 48 rows chipped him
        # twice. The same glued on by a period: "Philem.Gloss." is Philemon.
        name = re.sub(r'\.?\s*(?:Fragm|Fr|Gloss)\.$', '.', name)
        out.append((m.start(1), m.start(1), '<span class="lx-author">'))
        o = m.start(1) + len(name)
        out.append((o, o, '</span>'))
    return out


# A lead that names a kind of source and no one — "Orac. ap. Hdt.", "Lex
# ap. D.", "Fragm. ap. Prisc." after an "id." the print did name — is not
# an author, and Perseus marks none of these anywhere in either lexicon
# (444 oracles, 166 laws, 620 fragments). A named one is: "Lex Solonis",
# "XII. Tab.", "Carm. Marci", and "Sall. Fragm." is Sallust.
_SOURCE_LABELS = frozenset(
    'Orac Lex Decr Epigr Poet Poët Poeta Poëta Poetae Prov Gramm Foed Test '
    'Jusj Docum Epist Edict Syngr Inscr Fragm Fr Tab Form Hymn Carm Gloss '
    'Auct Aenigm Anon Com Trag Lyr Eleg Adesp Kalend'.split()) | {'S. C'}
# The print's own labels, capitalised at a sense's opening — "Freq. ap.
# Cic.", "Esp. ap. Plin." — are not the first author of a citation.
_LABELS = frozenset(
    # Not "Poet." or "Prop.": "Poet. ap. Ath." is an unnamed poet quoted
    # and "Prop." is Propertius as often as a label.
    'Freq Rar Esp Lit Trop Abs Transf Fig Meton Also Hence Subst '
    'Adv Pass Med Act So But And Or In Of Gen Usu Rarely Often Once Twice '
    'Only Cf Dub Prob Perh'.split())


def _label_lead(lead):
    """Offset into the lead past a label that is not an author: 0 for
    "Crito ap. ", the length of "Freq. " for "Freq. ap. "."""
    first = re.match(r'([A-Z][A-Za-zÀ-ÿ]*)\.?\s+', lead)
    if first and first.group(1) in _LABELS:
        return first.end()
    return 0


_TAIL_ELEMENT = re.compile(
    r'\s*<(?:span[^>]*class="lx-(?:author|foreign|bibl)"|i class="lx-title")[^>]*>')


def _citation_tail(html, pos, prose_open, last='author'):
    """End offset of the citation whose author's span ends at `pos`."""
    end = pos
    while True:
        step = None
        for name, rx in _TAIL_STEPS:
            if name == 'greek' and last != 'sv':
                continue
            if name == 'name' and last != 'ap':
                continue
            if name == 'ex' and last != 'name':
                continue
            if name == 'poet' and last != 'author':
                continue
            if name in ('siglum', 'page', 'editor') and last not in ('locus', 'title', 'bibl'):
                continue
            if name == 'locus2' and last != 'locus':
                continue
            if name == 'editor' and not DATASET.startswith('lat'):
                continue
            m = rx.match(html, end)
            if m and m.end() > end:
                step = (name, m.end())
                break
        if step:
            last, end = step
            if last == 'locus2':
                last = 'locus'
            continue
        # An element the grammar expects next: an author after ap. or a
        # pair conjunction, a title, a wrapped citation after Sch., the
        # Greek after s.v.
        m = _TAIL_ELEMENT.match(html, end)
        if not m:
            break
        cls = _tag_class(m.group(0))
        if cls == 'lx-author':
            if last not in ('ap', 'pair', 'ex') or m.end() - len(
                    m.group(0).lstrip()) in prose_open:
                break
            last = 'author'
        elif cls == 'lx-foreign':
            if last != 'sv':
                break
            last = 'greek'
        elif cls == 'lx-bibl':
            if last not in ('ap', 'name', 'in', 'ex'):
                break
            last = 'bibl'
        else:
            if last not in ('author', 'in', 'ap', 'name'):
                break
            last = 'title'
        close = _complete_el(html, m.start() + len(m.group(0)) - len(m.group(0).lstrip()))
        if not close:
            break
        end = close
    return end


def mark_prose_authors(html):
    """Tag lx-author spans that are prose, not citations, as lx-prose."""
    # The brackets LSJ puts round a doubtful attribution, "[Gal.] 14.519",
    # sit outside the author's span; the wrapper began at the span and
    # 51 Greek rows ended "[]10.528". The attribution's doubt is the
    # print's; the citation is a citation either way.
    html = re.sub(r'\[\s*(<span[^>]*class="lx-author"[^>]*>[^<]*</span>)\s*\]',
                  r'\1', html)
    # The supplied word's bracket in front of a whole citation, its mate
    # inside the quotation: παραζῶ "[ψυχὴ] τῷ σώματι παραζῶσα Plu." The
    # cut falls at the citation and the bracket stayed on the sense line
    # (269 Greek rows ended "["). It goes in with its letters.
    html = re.sub(r'\[\s*(<span class="lx-cit"[^>]*>\s*<span class="lx-quote"[^>]*>)',
                  r'\1[', html)
    if DATASET.startswith('lat'):
        html = _wrap_plain_citations(html)
    # The lead loop below joins a plain "Kalend. ap." to a marked citation
    # in an entry with no lx-author at all (chimerinus).
    if 'lx-author' not in html and 'lx-bibl' not in html and 'lx-title' not in html:
        return html
    cuts = []          # (start, end) of tags to drop, innermost text kept
    cites = []         # (open_start, close_end) of bare authors that cite
    forced = set()     # open offsets of a governed pair's second author
    stack = []
    bibl = 0
    for m in _TAG_ANY.finditer(html):
        closing, _name, attrs = m.groups()
        if closing:
            if not stack:
                continue
            kind, open_span = stack.pop()
            if kind == 'bibl':
                bibl -= 1
            elif kind == 'author':
                tail = html[m.end():m.end() + 120]
                after = _AFTER_AUTHOR.match(tail)
                sep = after.group(1) if after else ''
                word = after.group(2).lower() if after else ''
                if open_span[0] in forced:
                    # "f.l. for αὐΐαχος in Hom. and Q.S.": the sentence
                    # governs the pair, so both halves are prose. Judged
                    # alone, the second half has nothing after it and
                    # read as a citation while the first stayed prose.
                    prose = True
                elif word == 'in':
                    nxt = _IN_THEN.match(tail)
                    tok = (nxt.group(1) if nxt else '').rstrip('.')
                    if tok in _LABEL_AFTER_IN:
                        prose = True
                    elif tok.lower() in _TITLE_AFTER_IN:
                        prose = False
                    else:
                        prose = not tok[:1].isupper()
                else:
                    prose = bool(after and word not in _CITE_FOLLOWER)
                if not prose and _PAREN_NEXT.match(tail):
                    before = _STRIP_TAGS.sub(
                        ' ', html[max(0, open_span[0] - 300):open_span[0]])
                    prose = bool(_AUTHOR_GOVERNOR.search(before[-40:]))
                if prose and open_span[0] not in forced:
                    lead = _STRIP_TAGS.sub(
                        ' ', html[max(0, open_span[0] - 160):open_span[0]])
                    if _CITE_LEAD.search(lead):
                        prose = False
                    elif sep and not _AUTHOR_GOVERNOR.search(lead[-40:]):
                        # Across a comma or semicolon the sentence has to
                        # be governing the author for this to be prose.
                        # "First in Hdt., never in Trag." has the "in";
                        # θῦλαξ's "= προσκεφάλαιον, Hsch.; cited fr. Hom."
                        # has nothing — the author simply follows the word
                        # it glosses, which is a citation. Without this the
                        # relaxation that rescued 236 entries quietly cost
                        # 23 others their chip.
                        prose = False
                    elif (_PAIR_NEXT.match(tail)
                          and not _AUTHOR_GOVERNOR.search(lead[-40:])):
                        # A pair is a citation unless the sentence is
                        # governing it: ἀλέxω's "Not in A. or E. (exc.
                        # lyr.)" says the word is absent from Aeschylus
                        # and Euripides, which is prose about them, while
                        # "Antyll. or Heliod. ap. Ath." is a reference.
                        prose = False
                if prose:
                    cuts.append((open_span, (m.start(), m.end())))
                    pm = _PAIR_NEXT.match(tail)
                    if pm and _AUTHOR_GOVERNOR.search(_STRIP_TAGS.sub(
                            ' ', html[max(0, open_span[0] - 160):open_span[0]])[-40:]):
                        nxt = re.search(r'<span[^>]*class="lx-author"', tail)
                        if nxt:
                            forced.add(m.end() + nxt.start())
                else:
                    cites.append((open_span[0], m.end()))
        elif attrs.rstrip().endswith('/'):
            continue
        else:
            if _BIBL_OPEN.search(attrs):
                stack.append(('bibl', None))
                bibl += 1
            elif bibl == 0 and _AUTHOR_OPEN.match(m.group(0)):
                stack.append(('author', (m.start(), m.end())))
            else:
                stack.append(('', None))
    prose_open = {o[0] for o, _c in cuts}
    quotes = _quote_ranges(html)
    edits = []         # (offset, text to insert) and (start, end) marks
    for (o_start, o_end), _close in cuts:
        edits.append((o_start, o_end, html[o_start:o_end].replace(
            'class="lx-author"', 'class="lx-author lx-prose"', 1)))
    wrapped_to = -1
    for start, close_end in sorted(cites):
        if start < wrapped_to:
            continue        # already inside an earlier citation's tail
        # The citation may begin before its span: "Crito ap. Gal. 13.878"
        # and "Decr.Byz. ap. D. 18.90" name their first author in plain
        # text, and only the second is marked. Take the name and its
        # "ap." into the wrapper, or the gloss ends "…, Crito ap".
        lead_m = _lead_before(html, start)
        if lead_m:
            start = lead_m.start() + _label_lead(lead_m.group(0))
        end = _citation_tail(html, close_end, prose_open)
        # A governed citation keeps the author's name in the sentence
        # — "first in Hom.", "condemned by Arist." — as
        # keep_governed_author does for a citation Perseus marked. The
        # wrapper is what the chips and examples read; the name in
        # front of it is what the reader reads.
        lead = _STRIP_TAGS.sub(' ', html[max(0, start - 40):start])
        name = ''
        if _GOVERNOR_END.search(lead) and not _CITE_LEAD.search(lead):
            # The name is the first in the wrapper: the marked author,
            # or the plain lead's own ("acc. to Gloss. ap. Paul. ex
            # Fest." keeps "Gloss.", not the Festus inside).
            am = re.match(r'(?:<span[^>]*>)?([A-Z][^<]*?)\s*(?:</span>|\s+ap\b|\s+ex\b)', html[start:])
            name = am.group(1).strip() + ' ' if am else ''
        edits.append((start, start, name + '<span class="lx-bibl" data-bare="1">'))
        if lead_m:
            edits.extend(_lead_author_edits(html, start, lead_m.end(), quotes))
        edits.append((end, end, '</span>'))
        wrapped_to = end
    # The same lead in front of a citation Perseus did mark: βωλά's
    # "Decr.Byz. ap. <span class="lx-bibl">D. 18.90</span>". The name
    # and its "ap." join the citation, or the pointer keeps them.
    covered = [(a, b) for a, b, _t in edits if a != b] + [
        (a, e) for a, e in ((s_, _citation_tail(html, c_, prose_open))
                            for s_, c_ in cites)]
    # The same for a citation _wrap_plain_citations built from plain text
    # ("Enn. ap. Paul. ex Fest. s. v. naucus, p. 166 Müll." — nugator
    # shipped "Enn. ap."), and for a work title with no author span in
    # front of it ("Cenot. Pisan. ap. Inscr. Orell. 642").
    for m in re.finditer(r'<span class="lx-bibl"(?: data-bare="1")?>|<i class="lx-title">', html):
        if any(a <= m.start() < b for a, b in covered):
            continue
        lead = _lead_before(html, m.start())
        if not lead:
            continue
        lead_start = lead.start() + _label_lead(lead.group(0))
        close = _complete_el(html, m.start())
        if not close:
            continue
        # The tail past the marked citation joins too: "Paul. ex Fest.
        # p. 22 Müll." names its editor after the page.
        close = _citation_tail(html, close, prose_open,
                               'title' if m.group(0).startswith('<i') else 'author')
        # A governed lead keeps its first name in the sentence, as a
        # bare author's does: "acc. to Gloss. ap. Paul. ex Fest." reads
        # "acc. to Gloss." once the citation is out.
        before = _STRIP_TAGS.sub(' ', html[max(0, lead_start - 40):lead_start])
        if _GOVERNOR_END.search(before) and not _CITE_LEAD.search(before):
            nm = re.match(r'([A-Z][^<]*?)\s*(?:\s+ap\b|\s+ex\b)', html[lead_start:])
            if nm:
                edits.append((lead_start, lead_start, nm.group(1).strip() + ' '))
        # Not data-bare: the citation inside was a zone boundary when
        # Perseus marked it, and ψεῦσμα II's "Sch. Theoc. 12.24" has to
        # stay one, or its quotation stops being an example. A bare
        # title ("Cenot. Pisan. ap. Inscr. Orell. 642") was not one, so
        # its wrapper is bare like a bare author's.
        bare = ' data-bare="1"' if m.group(0).startswith('<i') or 'data-bare' in m.group(0) else ''
        edits.append((lead_start, lead_start, f'<span class="lx-bibl"{bare}>'))
        edits.extend(_lead_author_edits(html, lead_start, lead.end(), quotes))
        edits.append((close, close, '</span>'))
    out, pos = [], 0
    for a, b, text in sorted(edits, key=lambda e: (e[0], e[1])):
        out.append(html[pos:a])
        out.append(text)
        pos = b
    out.append(html[pos:])
    return ''.join(out)


# Citations Lewis & Short's digitisation left in plain text. "Paul. ex
# Fest. p. 9 Müll." (174 times) and Ribbeck's fragment collections
# "(Trag. Rel. p. 201 Rib.)" carry no span at all, so they read as prose
# and 74 glosses shipped "ex Fest" and 308 "Müll" in their wording. A
# closed grammar of the two shapes, wrapped as the bare author's citation
# is (data-bare); the chip is "Fest." — the site's abbreviation table
# knows Festus and knows "Paul." only as the jurist. And an editor named
# after a marked citation's close ("<bibl>Fest. p. 22</bibl> Müll.",
# 5,361 times) is moved inside it, where the tail grammar puts one that
# follows a bare author.
# The digitisation spells the reference every way: "Fest p 169 Müll.",
# "Fest, p. 29", "S. V. NEC", "s. h. v. p. 15", "s. v. majorem consulem,
# p. 161, 31" — and "Naev. ap. Paul. ex Fest." names both the poet and
# the epitomist. A lemma without a page ("Fest. s. v. redhostire") is
# still the reference.
# A reference ends where the print or the markup ends it: a space, a
# separator, a bracket, the em dash, the element's close. Without the
# last two the match backed off to the lemma alone and left ", p. 333
# Müll" on 40 rows that had been clean.
_REF_END = r'(?=[\s,;:.)\]—–<]|$)'
_PLAIN_FESTUS = re.compile(
    r'(?<![A-Za-z>])(?:((?:(?:[A-Z][a-z]+|[IVX]+)\.?\s+){0,2}[A-Z][a-z]+\.?)(\s+ap\.?\s+))?'
    r'(Paul\.?\s+ex\s+)?(Fest)[.,]?'
    r'((?:\s+(?:[sS]\.\s*[vV]\.|s\.\s*h\.\s*v\.)(?:\s+(?!pp?\.?\s*\d)[^\s<,;:()\d][^\s<,;:()]*){0,4},?)?'
    r'(?:\s+l\.\s*l\.'
    r'|\s+pp?\.?\s*\d+(?:[.,]\s*\d+)?(?:\s+and\s+\d+)?(?:\s+[ab]\.)?(?:\s+(?:fin|init|sq)\.)?(?:\s+Müll\.)?)?)'
    + _REF_END)
# Varro's De Lingua Latina cited in plain text, with the editor after
# the paragraph ("Varr L. L. 5, § 119 Müll.", "Var. L. L. 8, § 66"): the
# author is Varro however the digitisation clipped him.
_PLAIN_VARRO = re.compile(
    r'(?<![A-Za-z>])(Varr?o?)[.,]?(\s+L\.\s*L\.\s*\d+(?:,\s*\d+)*,?\s*§\s*\d+'
    r'(?:\s+sq\.)?(?:\s+Müll\.)?)' + _REF_END)
# A chapter reference in plain text: "Sol. c. 33", "Aug. Enchir. c. 16",
# "Jul. Epit. Nov. c. 66, § 234", "Tert. Jud. Dom. c. 8". A closed list
# of the authors the print cites by chapter this way.
_PLAIN_CHAPTER = re.compile(
    r'(?<![A-Za-z>])(Sol|Aug|Prud|Tert|Jul)\.(\s+(?:[A-Z][a-z]*\.\s+){0,3}c\.\s*\d+'
    r'(?:,\s*§\s*\d+)?)' + _REF_END)
_PLAIN_RIBBECK = re.compile(
    r'(?<![A-Za-z>])(?:(?:Trag|Com)\.\s+Rel\.\s+p\.\s*\d+\s+Rib\.'
    r'|(?:Trag|Com|Ann)\.\s+v\.\s*\d+\s+(?:ed\.\s+)?Vahl\.)')
# The citation may be the reference of a quotation, so its close is
# followed by the quotation's own closing tag before the editor ("<cit>
# <quote>…</quote> <bibl>Varr. L. L. 5, § 23</bibl></cit> Müll.", 923
# times); the print writes "sq. Müll." and "Müll.—" (319 times) as often
# as "Müll.;". Every one of these left "Müll." in the running text and
# thirty rows opened on it.
_EDITOR_AFTER = re.compile(
    r'((?:</span>)*)(\s*(?:sq\.\s*)?(?:Müll|Rib|Weissenb|Drak|Orell|Spald|Ruhnk|Oud|Vahl|Lachm|Fleck|Schneid|'
    r'Madv|Forbig|Merk|Bekk|Dind|Halm|Hertz|Momms|Bip|Roth|Kayser|Sillig|Zumpt|'
    r'Kritz|Nipp|Dietsch|Gron|Heins|Burm|Wagn)\.)(?=[\s,;:)—]|$)')


def _quote_ranges(html):
    """(start, end) of every lx-quote span — the print's own quoted text.

    The digitisation runs two of the print's quotations into one span,
    with the first one's reference between them: mensa "Curiales
    mensae, … Paul. ex Fest. s. v. Curiales, p. 64 Müll.: mensae
    deorum", calceus "Titin. ap. Fest. s. v. mulleos, p. 142 ib. (Com.
    Rel. p. 128 Rib.): calcei habiles et apti ad pedem", adverto "si
    voles advortere animum, Enn. ap. Var. L. L. 7, § 89 Müll. (Trag. v.
    386 Vahl.): facete advortis animum tuum ad animum meum".

    Wrapping that reference is what SPLITS the span — the quotation the
    drawer reads ends at the wrapper, so mensa ships the Curiales
    quotation with its own Festus reference. So a reference inside a
    quotation is still wrapped, but only in the shape that cannot be
    anything else: a name, a page and its editor. The looser shapes
    added for running text (a page with no editor, Varro's L. L., a
    chapter reference) match inside these spans too, and there they cut
    the quotation in the wrong place and lose the rest of it —
    calceus's "p. 142 ib." and adverto's "Var. L. L. 7, § 89 Müll."
    each took the second quotation with them. Those stay outside."""
    out = []
    for m in re.finditer(r'<span class="lx-quote"', html):
        end = _complete_el(html, m.start())
        if end:
            out.append((m.start(), end))
    return out


def _wrap_plain_citations(html):
    """Lewis & Short's plain-text citations, wrapped; its editors, inside."""
    quotes = _quote_ranges(html)

    def outside(m):
        return not any(a <= m.start() < b for a, b in quotes)

    def wrappable(m):
        """A Festus inside a quotation needs its editor to be wrapped."""
        return outside(m) or 'Müll' in (m.group(5) or '')

    def governed(m, name):
        """The name to leave in the sentence in front of the wrapper."""
        before = _STRIP_TAGS.sub(' ', m.string[max(0, m.start() - 40):m.start()])
        return name + ' ' if _GOVERNOR_END.search(before) and not _CITE_LEAD.search(before) else ''

    def festus(m):
        # "Naev. ap. Fest.": Naevius is named and chips; "Paul. ex Fest."
        # names the epitomist, whom the site's table knows only as the
        # jurist, and does not.
        if not m.group(5):
            return m.group(0)      # "Fest." alone is a name, not a reference
        keep = governed(m, (m.group(1) or '').split()[0] if m.group(1)
                        else ('Paul.' if m.group(3) else 'Fest.'))
        lead = ''
        if m.group(1):
            # "Carm. Marci ap. Fest.", "Plaut. Fragm. ap. Fest.": the
            # source cited is both words. A label in front ("So Naev.
            # ap.") is the sentence's, not the name's.
            name = m.group(1)
            first = re.match(r'([A-Z][a-z]+)\.\s+(?=[A-Z])', name)
            if first and first.group(1) in _LABELS:
                lead += name[:first.end()]
                name = name[first.end():]
            lead += f'<span class="lx-author">{name}</span>{m.group(2)}'
        lead += m.group(3) or ''
        return (f'{keep}<span class="lx-bibl" data-bare="1">{lead}<span class="lx-author">{m.group(4)}.'
                f'</span>{m.group(5)}</span>')
    html = _PLAIN_FESTUS.sub(lambda m: festus(m) if wrappable(m) else m.group(0), html)
    html = _PLAIN_VARRO.sub(
        lambda m: (f'{governed(m, "Varr.")}<span class="lx-bibl" data-bare="1"><span class="lx-author">Varr.</span>'
                   f'{m.group(2)}</span>') if outside(m) else m.group(0), html)
    html = _PLAIN_CHAPTER.sub(
        lambda m: (f'{governed(m, m.group(1) + ".")}<span class="lx-bibl" data-bare="1">'
                   f'<span class="lx-author">{m.group(1)}.</span>{m.group(2)}</span>')
        if outside(m) else m.group(0), html)
    html = _PLAIN_RIBBECK.sub(
        lambda m: ('<span class="lx-bibl" data-bare="1">' + m.group(0) + '</span>')
        if outside(m) else m.group(0), html)
    out, pos = [], 0
    for m in re.finditer(r'<span class="lx-bibl"', html):
        if m.start() < pos:
            continue
        end = _complete_el(html, m.start())
        if not end:
            continue
        ed = _EDITOR_AFTER.match(html, end)
        if not ed:
            continue
        # The citation's own closing tag is the last seven characters;
        # the editor moves inside it and the outer closes stay put.
        out.append(html[pos:end - 7] + ed.group(2) + '</span>' + ed.group(1))
        pos = ed.end()
    out.append(html[pos:])
    return ''.join(out)


def _norm_inline(html):
    """Reduce pack markup to the marks the record may carry.

    Kept as written: cue, hw, rub, eq-mark, sublem. Foreign runs become a
    plain lang span, tagged by the script inside them — L&S quotes Greek
    inside a Latin entry, so the pack's language is the wrong answer.
    Everything else is unwrapped: the words stay, the classification goes."""
    if not html:
        return ''
    # LSJ uses angle brackets for short runs of supplied letters, both as
    # literal brackets and as entities. Leave real HTML tag names alone so
    # the markup audit still catches a leaked <div>, <br>, or <img>.
    html = _source_editorial_angles(html)
    if '<' not in html:
        return _wrap_unmarked_greek(html) if DATASET.startswith('lat') else html
    out, stack, pos = [], [], 0
    for m in _TAG.finditer(html):
        out.append(html[pos:m.start()])
        pos = m.end()
        closing, tag, attrs = m.group(1) == '/', m.group(2).lower(), m.group(3)
        if closing:
            kind = stack.pop() if stack else None
            if kind is None:
                continue
            what, opened = kind
            if what == 'keep':
                out.append(f'</{opened}>')
            elif what == 'lang':
                out.append('</span>')
            continue
        cm = re.search(r'class="([^"]*)"', attrs)
        cls = (cm.group(1) if cm else '').strip()
        lm = re.search(r'lang="([^"]*)"', attrs)
        if cls in _KEEP_CLS:
            out.append(f'<{tag} class="{cls}">')
            stack.append(('keep', tag))
        elif cls in ('lx-foreign', 'lx-quote') or (lm and not cls.startswith('lx-')):
            close = html.find(f'</{tag}>', m.end())
            inner = html[m.end():close if close >= 0 else len(html)]
            lang = ('grc' if _GREEK_CH.search(inner)
                    else (lm.group(1) if lm else ('la' if LANG == 'la' else 'grc')))
            out.append(f'<span lang="{lang}">')
            stack.append(('lang', tag))
        else:
            stack.append(('drop', tag))
    out.append(html[pos:])
    normalized = ''.join(out)
    return (_wrap_unmarked_greek(normalized)
            if DATASET.startswith('lat') else normalized)


def _polish_zone(z):
    """What a gloss may not open or close on, applied once, to every row.

    The rules are the ones the row builders already state — _lead_punct
    ("the print's dash before a further note separated something; on
    its own line it separates nothing"), _tidy ("a gloss ends on its
    last word") — but each runs on some paths and not others. Lewis &
    Short's short entries split at ".—" and 5,787 rows opened on the
    dash; a citation Perseus left bare is stripped after the tidy ran
    and 2,229 LSJ glosses ended on the comma before it, inside the cue's
    closing tag. The bracket rule is _drop_unmatched_parens's, for the
    print's supplied-word brackets."""
    src = z
    z = _lead_punct(z)
    z = _drop_unmatched_parens(z, '[]')
    # An emptied bracket, like the emptied parenthesis _polish_emitted
    # drops: "repetition, []" once the Greek inside it went to the drawer.
    z = re.sub(r'\s*\[\s*\]', '', z)
    # The space a removed quotation left in front of its separator
    # ("coming alongside of : hence"), and the comma before a colon.
    z = re.sub(r'(?<=\S)\s+(?=[,;:](?:\s|<|$))', '', z)
    z = re.sub(r',\s*(?=[;:])', '', z)
    # The dash after a removed citation ("143 al.—") ends nothing, nor
    # does the conjunction that joined it to the one before (copior
    # "Quadrig. ap. Gell. l. l., and Cael. ap. Non." leaves ", and").
    z = re.sub(r'(?:[ ,;:—–]|\b(?:and|or))+(?=(?:</\w+>\s*)*$)', '', z)
    # A polish never empties a row. The print writes glosses that are
    # nothing but the word this function trims off the end of other
    # rows — ἰδέ and τʼ mean "and", ὅτι V and δευτέριος 2 open on "or",
    # and ἔπαρχος I is "[commander" where the bracket rule reads a
    # two-word tail as a truncated aside. Six rows rendered blank and
    # the build gate refused to write the pack, which is the rule this
    # restates: every non-banner row keeps a letter or a number.
    return z.strip() if _has_words(z) or not _has_words(src) else src.strip()


def row_doc(r, lemma):
    # The part letter is stripped here as well as in _strip_dangling,
    # because most of these rows never reach that function: it runs on
    # three paths and ἀνασάξιμον, Ἀθῆναι and ἄρκτος take none of them.
    # Safe at this point precisely because it is the row's own gloss and
    # Greek only — see _strip_part_letter for why Latin must be left
    # alone, and note that a citation's part letter, which IS meaningful,
    # lives in ex.c and never passes through here.
    d = {'lv': r['lv'], 'n': r['n'],
         'z': _polish_zone(_strip_part_letter(_norm_inline(r['zone'])))}
    # A comma in front of the print's opening bracket, once the citation
    # between them went: λεπτοκοπέω "chop fine or small, (both Pass.)"
    # off "Dsc. 1.12, 5.75 (both Pass.)". The gloss only: the identity
    # line writes "ου, (ῥήγνυμι)" and means it.
    d['z'] = re.sub(r',((?:\s*</(?:b|span)>)*)\s+\(', r'\1 (', d['z'])
    if r.get('banner'):
        d['b'] = 1
        # A banner's zone is emptied; the label lives here — and the
        # label needs the same strip, or the six rows that reach the
        # pack as banners keep the part letter the rest just lost
        # (ἀρχοντικός "ex-archon, a", μνημοδόχος "recorder, f").
        d['z'] = _strip_part_letter(
            _norm_inline(r.get('glab') or r.get('zfull') or ''))
    # Some paths skip _tidy or split after its period check. At this common
    # row boundary, restore a print-attested grammar or author abbreviation.
    visible = L.text_of(d['z']).strip()
    tm = re.search(r'([A-Za-z][A-Za-z.]*)$', visible)
    if tm and not visible.endswith('.'):
        tok = tm.group(1)
        plain = r.get('plain') or ''
        attested = re.search(r'(?<![\w.])' + re.escape(tok) + r'\.', plain, re.I)
        grammar = tok.lower() in _GRAM_TAIL and not (
            tok.islower() and tok.lower() in {'access', 'act', 'active', 'class',
                                              'object', 'part', 'pass', 'prop',
                                              'respect', 'subject', 'term'})
        author = tok + '.' in (abbrevs().get('authors') or {})
        if author and len(tok) == 1:
            author = bool(re.search(r'\b(?:in|by|from|after|before|among|as|to|than|of)\s+'
                                    + re.escape(tok) + r'\.', plain))
        # Not where DANGLING_LINK will strip the tail, as for labels.
        if attested and (grammar or author) and not DANGLING_LINK.search(d['z']):
            d['z'] = re.sub(r'(?=(?:</(?:b|span|i)>\s*)*$)', '.', d['z'], count=1)
    if r.get('supplied'):
        d['s'] = 1
    if r.get('usage'):
        d['u'] = 1
    if r.get('authors'):
        d['au'] = r['authors']
    ex = []
    for e in r.get('examples') or []:
        item = {'g': _norm_inline(mark_headword(e['gr'], lemma))}
        if e.get('eng'):
            item['e'] = e['eng']
        if e.get('cit'):
            item['c'] = e['cit']
        ex.append(item)
    if ex:
        d['ex'] = ex
    return d


def to_doc(m, key=''):
    """One dictionary entry as the pack stores it."""
    lemma = m['lemma']
    d = {'head': lemma, 'rows': [row_doc(r, lemma) for r in m['rows']]}
    if key:
        d['key'] = key
    for src, short in (('hom', 'hom'), ('gender', 'g'), ('ident', 'i'),
                       ('gloss', 'gl'), ('ptr', 'p')):
        if not m.get(src):
            continue
        if src == 'ptr':
            # A cross-reference whose target the citation strip removed
            # is a promise the entry cannot keep: 127 entries shipped a
            # pointer reading "v." and nothing else, three read "of".
            # Better to say nothing. All of them carry other content, so
            # none goes hollow.
            if _EMPTY_PTR.fullmatch(L.text_of(m[src]).strip()):
                continue
            d[short] = _norm_inline(m[src])
        else:
            d[short] = m[src]
    if m.get('authors'):
        d['au'] = m['authors']
    if m.get('forms'):
        d['f'] = m['forms']
    if m.get('groups'):
        d['gr'] = m['groups']
    # The key is the entry's identity in the pack, a betacode string
    # whose "(" is a rough breathing, not a bracket the prose rules may
    # trim (Μῶἁ is "*mw=a("). Polish the record without it.
    key_value = d.pop('key', None)
    d = _polish_emitted(d)
    # The head is not available to _tidy, so enforce the named word veto
    # here, after every path that can restore an abbreviation period.
    dataset = DATASET.split('-', 1)[0]
    def veto_word_period(value):
        visible = L.text_of(value or '').strip()
        tm = re.search(r'([A-Za-z]+)\.$', visible)
        if tm and (dataset, lemma, tm.group(1).lower()) in _PERIOD_WORD_VETO:
            return re.sub(r'\.(?=(?:</(?:b|span|i)>\s*)*$)', '', value, count=1)
        return value
    for row in d.get('rows') or []:
        row['z'] = veto_word_period(row.get('z') or '')
        for ex in row.get('ex') or []:
            if ex.get('e'):
                ex['e'] = veto_word_period(ex['e'])
    for i, (number, label) in enumerate(d.get('gr') or []):
        d['gr'][i] = (number, veto_word_period(label))
    if key_value is not None:
        d['key'] = key_value
    return d


_PUNCT_RUN = re.compile(r'([,;])((?:\s|</?[^>]+>)*)([,;])')


def _collapse_punct(m):
    """Keep the stronger of two separators, and the markup between."""
    mark = ';' if ';' in (m.group(1), m.group(3)) else ','
    # The stripped material left its spacing behind too.
    return mark + re.sub(r'[ \t]+', ' ', m.group(2))


def _polish_emitted(value, field=None):
    """Apply final prose punctuation rules once, across every stored field.

    `field` is the key the string is stored under, so the one rule that
    is about the sense line and not about prose in general can tell where
    it is."""
    if isinstance(value, str):
        # The tail of a quotation that has moved to the drawer, left at
        # the head of the sense line: LSJ μέν prints "μέν . . , δέ . . (or
        # when the correlative clause is neg. …)", the quotation goes and
        # the ellipsis that closed it stays behind. 31 rows over both
        # packs. The sense line only: at the head of a quotation the same
        # mark is the print's own and says words were left out
        # (ἄλλος "οὐδὲν ἄλλο ἢ . ., ἤ").
        if field == 'z':
            value = re.sub(r'^((?:<[^>]+>\s*)*)\s*\.\s*\.(?:\s*\.)*\s*',
                           r'\1', value)
        value = re.sub(r',(?=(?:</(?:b|span)>\s*)+,)', '', value)
        value = re.sub(r',(?:\s*,)+', ',', value)
        # A citation whose author and locus were both stripped leaves its
        # shell: "= περί, (, ), etc". Empty parens are never prose, and a
        # comma abutting a close-paren ("e. g., )") is the stripped
        # cluster's seam.
        value = re.sub(r'\s*\(\s*[,;·]*\s*\)', '', value)
        value = re.sub(r',\s*\)', ')', value)
        value = re.sub(r'\(\s*,\s*', '(', value)
        # A linking abbreviation with nothing left to link dangles at the
        # end of the line ("…ἀδιάφορον, 1.83, cf"). Prose never stops
        # there; the citations it pointed at live in the drawer or chips.
        # Links only: this pass runs over every stored string, citations
        # included, and the other tails are prose rules.
        value = _strip_links(value)
        value = re.sub(r',(?:\s*,)+', ',', value)
        # A run of separators with the material between them stripped out.
        # The existing collapse above only sees commas that touch, and
        # only across </b> and </span>; what survives is the mixed and
        # tag-separated kind — ἀδευκής's "only in Od., ; ;, cf.",
        # ἀναλογούντως's "c. dat.,; fittingly", L&S aestimo's "Gronov. ad
        # 4, 41; ; and". Collapse to the strongest mark in the run, since
        # the print's semicolon divides more than its comma, and keep any
        # markup that stood between them.
        for _ in range(5):
            new_value = _PUNCT_RUN.sub(_collapse_punct, value)
            if new_value == value:
                break
            value = new_value
        # Nothing prose writes opens on its own separator: ἀ-'s identity
        # line began ", properly ἁ- since", ἀπονευρόομαι's sense "; to be
        # unnerved". Whatever stood in front was a citation the strip
        # removed, and its separator outlived it.
        # Two colons with the material between them stripped: οὐσία's
        # identity line reads "(qq. v.): : (ὀντ-, part. of εἰμί sum)".
        # Kept separate from the run above because a colon carries more
        # force than a comma and must not be traded for one.
        value = re.sub(r':(?:\s*:)+', ':', value)
        # A comma left in front of the print's period once the citation
        # between them went: Ἀμφιεραϊστής "worshipper of Amphiaraus,."
        # At the very end both marks are the seam and both go — _tidy
        # would have taken the period, and putting one back left
        # ἀναιμόσαρκος "of the cicada." and ξῦσις "polishing,."
        value = re.sub(r',\s*\.(?=(?:\s*</(?:b|span|i)>)*\s*$)', '', value)
        value = re.sub(r',\s*\.(?!\s*\.)', '.', value)
        # And in front of the print's colon: L&S fator "multa fantur, :
        # fatatus" once "Paul. ex Fest. p. 88 Müll." between them went.
        value = re.sub(r',((?:\s*</(?:b|span)>)*)\s*:', r'\1:', value)
        # A link with nothing left to link before the print's closing
        # bracket: amphora "(also called quadrantal; cf. Müll.)" once the
        # citation between them went.
        # Straight after the bracket or a separator only: "(q. v.)" is
        # the print's own and keeps its v.
        value = re.sub(r'(?:(?<=\()|[,;])\s*(?:cf|v|ap|al|sq|ib)\.\s*\)', ')', value)
        value = re.sub(r'\s*\(\s*\)', '', value)
        # A doubled period is NOT collapsed. LSJ writes its ellipsis with
        # two dots and the print's own spacing — "ὁ μέν.., ὁ δέ..",
        # "both.. and", "Εἰλείθυιαι . . ὠδῖνας ἔχουσαι" — and a rule that
        # folded ". ." into "." was taking a mark the witness supplies. It
        # was read over 2,700 sampled entries: of the 130 strings it
        # changed, 129 were an ellipsis and one was a dangling "cf. ."
        # that collapsing did not fix either. The doubled period a
        # stripped citation leaves at the END of a line is a different
        # shape and still folds, in the zone tidy above ("in Dsc.." keeps
        # one period and its abbreviation).
        # A leading period is the headword's, cut from it by Perseus's
        # markup (L&S "Aba. (or Abas), ae, m."); prose never opens on one.
        # Before the separator rule, and never on an ellipsis: LSJ opens
        # a quotation with ". ." and running the separator rule first
        # turned ἄλλος's ". ., ἤ" into ", ἤ".
        value = re.sub(r'^(\s*(?:<[^>]+>\s*)*)\.(?!\s*[.·])\s*', r'\1', value)
        value = re.sub(r'^(\s*(?:<[^>]+>\s*)*)[,;·]\s*', r'\1', value)
        # A bracket opened on nothing at the end of the line: the aside
        # it opened went with the citation (βραδανίζω's identity line
        # "(", L&S ce "…to the Gr. γε (").
        value = re.sub(r'\s*\(\s*(?=(?:</(?:b|span|i)>\s*)*$)', '', value)
        # Nor does it end on one, once the citation behind it has gone:
        # ἀγρολικός's "prob. by mistake for ἀρβυλικός," (the comma the
        # print set before "IG ΙΙ(2).199"). Inside the closing tags too:
        # the print set its comma inside the italic ("<i>not loudly
        # lamented,</i> Epigr.Gr. 240") to separate the gloss from the
        # citation that followed, and 2,229 Greek cues still ended on it
        # after the citation went.
        value = re.sub(r'[,;:]\s*(?=(?:</(?:b|span|i)>\s*)*$)', '', value)
        # The space in front of a separator, left where the citation
        # between them was: ἀπόρημα "of Arist. , objection raised to",
        # κυβαία "kind of boat, al. ; Lat." Prose never puts one there.
        value = re.sub(r'[ \t]+([,;:])', r'\1', value)
        # The gap the removed separator left behind. Cosmetic in a
        # browser, which folds runs of spaces, but the audit reads the
        # text and so does anyone diffing two builds.
        return re.sub(r'[ \t]{2,}', ' ', value)
    if isinstance(value, list):
        return [_polish_emitted(item, field) for item in value]
    if isinstance(value, dict):
        return {key: _polish_emitted(item, key) for key, item in value.items()}
    return value


def docs(word):
    """Every entry under this key, ready to store."""
    return [to_doc(m, (m.get('key') or '')) for m in models(word)]


if __name__ == '__main__':
    import sys as _sys
    args = [a for a in _sys.argv[1:] if a != '--latin']
    if '--latin' in _sys.argv:
        configure('lat-ls', 'lat-analyses', 'la')
    for w in args:
        print(json.dumps(docs(w), ensure_ascii=False, indent=1))
