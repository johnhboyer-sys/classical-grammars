#!/usr/bin/env python3
"""Build the word-tool packs from the Perseus data shipped with Diogenes.

Four datasets, each emitted as ONE pack file of independently-gzipped
buckets plus a small byte-range index, so any static host (git checkout,
GH Pages, Cloudflare R2) serves lookups with a single Range request:

  grc-analyses  greek-analyses.txt   form -> morphological analyses
  lat-analyses  latin-analyses.txt   form -> morphological analyses
  grc-lsj       grc.lsj.xml          LSJ entries (full lexicon)
  lat-ls        lat.ls.perseus-eng1.xml  Lewis & Short entries (full)

A fifth, grc-ml, is the Middle Liddell (An Intermediate Greek-English
Lexicon, 1889) from PerseusDL/canonical-pdlrefwk, fetched by
fetch_ml.py into the gitignored sources/ directory and built with
--ml-only when the Diogenes data is absent. It goes through the same
lexicon parser after a small ML-only markup repair (see
ml_fragment_fix). The T8 row transform is NOT applied to grc-ml; that
is a later decision, so there is no grc-ml-t8 pack.

A bucket is the set of forms/keys sharing a 2-letter folded-ASCII prefix.
Bucket payloads are JSON, gzip-compressed per bucket; the index maps
bucket name -> [byte offset, byte length] within the pack.

The parsing rules are ported from the plato-reader pipeline
(stage4_morphology / stage5_lsj / beta.py), which established them
against this same data; the corpus filter is removed — the word tool
carries the whole form space.

Sources stay in /Applications/Diogenes.app (never modified). Licensing:
Perseus Digital Library data, CC BY-SA; Morpheus analyses as distributed
with Diogenes.

Usage: python3 build_wordtool.py [--out DIR]
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from collections import defaultdict
from html import escape, unescape
from html.entities import html5
from pathlib import Path

DIOGENES_DATA = Path("/Applications/Diogenes.app/Contents/dependencies/data")
DEFAULT_OUT = Path(__file__).resolve().parents[2] / "data" / "wordtool"

# Middle Liddell: one TEI P4 file in PerseusDL/canonical-pdlrefwk, pinned
# to a commit so the pack is reproducible. CC BY-SA 4.0 (repo README).
ML_COMMIT = "02768b0c37d6102be4899fc0eb57f9d348195243"
ML_FILE = "viaf66541464.001.perseus-eng1.xml"
ML_URL = (
    "https://raw.githubusercontent.com/PerseusDL/canonical-pdlrefwk/"
    f"{ML_COMMIT}/data/viaf66541464/001/{ML_FILE}"
)
ML_SHA256 = "e273dbed7938de7ab9ed4cf4af0e93216141f89226318a697c94b5d43f924cb7"
ML_SOURCE = Path(__file__).resolve().parent / "sources" / ML_FILE

LICENSE = (
    "Perseus Digital Library data as distributed with Diogenes "
    "(P. J. Heslin). Lexica (LSJ 1940, Lewis & Short 1879): CC BY-SA "
    "(PerseusDL/lexica states 4.0). Middle Liddell (1889): CC BY-SA 4.0 "
    "from PerseusDL/canonical-pdlrefwk, text provided by Perseus Digital "
    "Library, http://www.perseus.tufts.edu, with funding from the "
    "Annenberg Foundation. Morphology (Morpheus analyses): Perseus "
    "morphology data; Perseus notes component rights vary — verify terms "
    "before any public deployment. Derived packs carry the source licenses."
)

# ---------------------------------------------------------------- betacode

_B2U = {
    "a": "α", "b": "β", "g": "γ", "d": "δ", "e": "ε", "z": "ζ", "h": "η",
    "q": "θ", "i": "ι", "k": "κ", "l": "λ", "m": "μ", "n": "ν", "c": "ξ",
    "o": "ο", "p": "π", "r": "ρ", "s": "σ", "t": "τ", "u": "υ", "f": "φ",
    "x": "χ", "y": "ψ", "w": "ω", "v": "ϝ",
}
_MARK2U = {
    ")": "̓", "(": "̔", "/": "́", "\\": "̀",
    "=": "͂", "|": "ͅ", "+": "̈",
}


def beta_to_unicode(beta: str) -> str:
    """Betacode -> polytonic Greek. Handles '*' capitals (marks may precede
    the letter), final sigma, elision apostrophe; drops the '_'/'^' length
    marks (vowel length is carried by the parse string where it matters)."""
    out: list[str] = []
    i = 0
    n = len(beta)
    while i < n:
        ch = beta[i]
        if ch == "*":
            marks = []
            i += 1
            while i < n and beta[i] in _MARK2U:
                marks.append(_MARK2U[beta[i]])
                i += 1
            if i < n and beta[i].lower() in _B2U:
                out.append(_B2U[beta[i].lower()].upper())
                out.extend(marks)
                i += 1
            else:
                out.extend(marks)
            continue
        low = ch.lower()
        if low in _B2U:
            out.append(_B2U[low])
        elif ch in _MARK2U:
            out.append(_MARK2U[ch])
        elif ch == "'":
            out.append("’")
        elif ch in "_^!":
            pass
        elif ch.isdigit():
            pass  # homonym numbers are carried separately
        else:
            out.append(ch)
        i += 1
    text = canonical_marks("".join(out))
    # Final sigma: σ at word end (before space/punct/end) -> ς
    return re.sub(r"σ(?![\ẁ-ͯἀ-῿Ͱ-Ͽ])", "ς", text)


_NON_ALPHA = re.compile(r"[^a-z]")
_U2B = {u: b for b, u in _B2U.items()}
_U2B["ς"] = "s"

# Precomposed Greek requires breathings/diaeresis before accents before
# iota subscript; all are ccc=230/240 so NFC never reorders them itself.
_MARK_RANK = {"̓": 0, "̔": 0, "̈": 0, "́": 1, "̀": 1, "͂": 1, "ͅ": 2}
_MARK_RUN = re.compile(r"[̀-ͅ]+")


def canonical_marks(text: str) -> str:
    """Sort each combining-mark run into composable order, then NFC —
    this is what makes 'marks in any order' actually true."""
    decomposed = unicodedata.normalize("NFD", text)
    ordered = _MARK_RUN.sub(
        lambda m: "".join(sorted(m.group(0), key=lambda c: _MARK_RANK.get(c, 9))),
        decomposed,
    )
    return unicodedata.normalize("NFC", ordered)


def beta_fold(beta: str) -> str:
    """ASCII fold of a betacode key: base letters only, lowercased."""
    return _NON_ALPHA.sub("", beta.lower())


def greek_display_fold(text: str) -> str:
    """ASCII fold of displayed Unicode Greek, matching beta_fold of the
    key it came from (and the client's foldGreek)."""
    out = []
    for ch in unicodedata.normalize("NFD", text).lower():
        mapped = _U2B.get(ch)
        if mapped:
            out.append(mapped)
        elif "a" <= ch <= "z":
            out.append(ch)
    return "".join(out)


def latin_fold(form: str) -> str:
    """Fold a Latin form for lookup: decompose (so displayed macrons like
    Aarōn fold to aaron), lowercase, j->i, v->u, letters only."""
    base = unicodedata.normalize("NFD", form)
    return _NON_ALPHA.sub("", base.lower().replace("j", "i").replace("v", "u"))


_LATIN_MACRON = re.compile(r"([aeiouyAEIOUY])_")


def latin_display(form: str) -> str:
    """Vowel+underscore -> macron (Aaro_n -> Aarōn); drop stray '_'/'^'."""
    text = _LATIN_MACRON.sub(lambda m: m.group(1) + "̄", form)
    return unicodedata.normalize("NFC", text.replace("_", "").replace("^", ""))


def homonym_split(lemma: str) -> tuple[str, str]:
    """'a(/zw1' / 'abdico#1' -> (bare lemma, homonym number or '')."""
    m = re.match(r"^(.*?)[#]?(\d+)$", lemma)
    if m:
        return m.group(1), m.group(2)
    return lemma, ""


def bucket_name(folded: str) -> str:
    if len(folded) >= 2:
        return folded[:2]
    if len(folded) == 1:
        return folded
    return "_"


# ------------------------------------------------------------- analyses

# {lemma_id flag form,lemma \t gloss \t parse} — ported from stage4.
_GROUP = re.compile(r"\{(\d+) \d+ ([^\t}]*)\t([^\t}]*)\t([^}]*)\}")


def parse_analyses(path: Path, greek: bool):
    """Stream an analyses file into {bucket: {folded: {formDisplay: rows}}}
    plus the set of distinct lemmas. Row = [lemma, gloss, parse,
    formVariant|None] with lemma still in source encoding.

    Two normalized keys can share a display (Ἄτλαν is both *)/atlan voc
    and *a)/tlan acc), so rows MERGE — assignment would lose parses. And
    every displayed variant (dialect/macron forms like ἄασο under the
    key a)/as') is also registered under its own fold, so anything the
    tool can show, the tool can find."""
    buckets: dict[str, dict[str, dict[str, list]]] = defaultdict(
        lambda: defaultdict(dict)
    )
    lemmas: set[str] = set()
    n_forms = 0
    n_aliases = 0
    display_fold = greek_display_fold if greek else latin_fold

    def add_rows(folded: str, form_disp: str, rows: list) -> None:
        forms = buckets[bucket_name(folded)][folded]
        existing = forms.setdefault(form_disp, [])
        have = {(r[0], r[1], r[2], r[3]) for r in existing}
        for row in rows:
            if (row[0], row[1], row[2], row[3]) not in have:
                existing.append(row)
                have.add((row[0], row[1], row[2], row[3]))

    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            key, tab, value = line.partition("\t")
            if not tab or key.startswith("!"):
                continue
            key = key.strip().lstrip("-")
            if not key:
                continue
            if greek:
                folded = beta_fold(key)
                form_disp = beta_to_unicode(key)
            else:
                folded = latin_fold(key)
                form_disp = latin_display(key)
            if not folded:
                continue
            rows = []
            seen = set()
            for _lemma_id, form_lemma, gloss, parse in _GROUP.findall(value):
                form, comma, lemma = form_lemma.partition(",")
                if not comma:
                    # Single field: the group names only the lemma — there is
                    # no per-group form variant, the line key is the form.
                    lemma = form
                    form = ""
                lemma = lemma.strip()
                if not lemma:
                    continue
                gloss = gloss.strip()
                parse = parse.strip()
                variant = None
                if form:
                    variant = beta_to_unicode(form) if greek else latin_display(form)
                    if variant == form_disp:
                        variant = None
                dedup = (lemma, gloss, parse, variant)
                if dedup in seen:
                    continue
                seen.add(dedup)
                lemmas.add(lemma)
                rows.append([lemma, gloss, parse, variant])
            if not rows:
                continue
            n_forms += 1
            add_rows(folded, form_disp, rows)
            # Register each distinct variant under its own fold too.
            for row in rows:
                variant = row[3]
                if not variant:
                    continue
                vfold = display_fold(variant)
                if not vfold or vfold == folded:
                    continue
                add_rows(vfold, variant, [[row[0], row[1], row[2], None]])
                n_aliases += 1
    return buckets, lemmas, n_forms, n_aliases


# ---------------------------------------------------------------- lexica

_TAG_MAP = {
    "head": ("b", "lx-head"),
    "orth": ("b", "lx-orth"),
    "gen": ("span", "lx-gen"),
    "itype": ("span", "lx-itype"),
    "pos": ("span", "lx-pos"),
    "etym": ("span", "lx-etym"),
    "i": ("i", None),
    "tr": ("span", "lx-tr"),
    "foreign": ("span", "lx-foreign"),
    "quote": ("span", "lx-quote"),
    "cit": ("span", "lx-cit"),
    "bibl": ("span", "lx-bibl"),
    "author": ("span", "lx-author"),
    "title": ("i", "lx-title"),
    "usg": ("span", "lx-usg"),
    "case": ("span", "lx-case"),
    "number": ("span", "lx-number"),
    "mood": ("span", "lx-mood"),
    "tns": ("span", "lx-tns"),
}

_CONNECTIVE = re.compile(r"^[\s,;]*(?:(?:or|and)[\s,;]*)?$", re.IGNORECASE)
_DANGLING_CONNECTIVE = re.compile(r"(?:\s*[,;]\s*)?\b(?:or|and)\s*$", re.IGNORECASE)
_DANGLING_ARTICLE = re.compile(r"\b(?:an?|the)$", re.IGNORECASE)
_BASE_STRIP = re.compile(r"[0-9_^\-]")


def _to_html(el) -> str:
    tag = el.tag if isinstance(el.tag, str) else None
    parts = []
    body_open = False
    if tag == "sense":
        level = el.get("level") or "1"
        n = el.get("n") or ""
        parts.append(f'<div class="lx-sense" data-level="{escape(level)}">')
        if n:
            parts.append(f'<b class="lx-sense-n">{escape(n)}.</b> ')
        body_open = True
    elif tag in _TAG_MAP:
        html_tag, cls = _TAG_MAP[tag]
        cls_attr = f' class="{cls}"' if cls else ""
        lang = el.get("lang")
        lang_attr = ' lang="grc"' if lang == "greek" else ""
        parts.append(f"<{html_tag}{cls_attr}{lang_attr}>")
        body_open = True
    elif tag is not None:
        parts.append(f'<span class="lx-{escape(tag)}">')
        body_open = True
    if tag is not None and el.text:
        parts.append(escape(el.text))
    for child in el:
        parts.append(_to_html(child))
    if body_open:
        if tag == "sense":
            parts.append("</div>")
        else:
            html_tag = _TAG_MAP.get(tag, ("span", None))[0]
            parts.append(f"</{html_tag}>")
    if el.tail:
        parts.append(escape(el.tail))
    return "".join(parts)


def entry_html(root) -> str:
    parts = []
    if root.text:
        parts.append(escape(root.text))
    for child in root:
        parts.append(_to_html(child))
    return "".join(parts).strip()


def _strip_edge_punctuation(value: str) -> str:
    while value and (
        value[0].isspace() or unicodedata.category(value[0]).startswith("P")
    ):
        value = value[1:]
    while value and (
        value[-1].isspace() or unicodedata.category(value[-1]).startswith("P")
    ):
        value = value[:-1]
    return value


def derive_short_def(root) -> str:
    """Compact definition from an entry's leading italic run (stage5 port,
    guards intact: never ship a def ending on a bare article, never cut a
    def over 100 chars)."""
    sense = next((el for el in root.iter() if el.tag == "sense"), None)
    body = sense if sense is not None else root
    children = list(body)
    first_i = next((i for i, child in enumerate(children) if child.tag == "i"), None)
    if first_i is None:
        return ""
    parts = ["".join(children[first_i].itertext())]
    previous = children[first_i]
    for child in children[first_i + 1 :]:
        if child.tag != "i" or not _CONNECTIVE.fullmatch(previous.tail or ""):
            break
        parts.extend((previous.tail or "", "".join(child.itertext())))
        previous = child
    short_def = " ".join("".join(parts).split())
    short_def = _strip_edge_punctuation(short_def)
    short_def = _DANGLING_CONNECTIVE.sub("", short_def)
    short_def = _strip_edge_punctuation(short_def)
    if _DANGLING_ARTICLE.search(short_def):
        return ""
    if len(short_def) > 100:
        return ""
    return short_def


# ------------------------------------------------------- middle liddell

_ML_ENTITY = re.compile(r"&([A-Za-z][A-Za-z0-9]*);")
_ML_XML_ENTITIES = {"lt", "gt", "amp", "quot", "apos"}
_ML_COMMENT = re.compile(r"<!--.*?-->", re.S)
_ML_LANG = re.compile(r'(<(?:foreign|ref) [^>]*?lang=)(greek|la)\b')
_ML_STEM_NOTE = re.compile(r'<note anchored="yes">.*?</note>', re.S)
_ML_SKIPPED_NOTE = re.compile(r"<note [^>]*>#[^<]*</note>")
# Perseus's machine form of the print's "id.": where the Middle Liddell
# repeats the author it has just named, the file writes <usg>id=Il.</usg>
# rather than the author alone. 7,907 of them were shipping "id=Il.",
# "id=Ar.", "id=Thuc." to the reader. The author it names is the
# witness's own text; only Perseus's prefix goes, as the other machine
# annotations here do.
_ML_USG_ID = re.compile(r"(<usg\b[^>]*>)\s*(?:id=)+(?=\S)")
# Perseus's part-of-speech code, which the Middle Liddell does not print:
# <gramGrp><pos>n</pos></gramGrp> on διακώλυσις, <pos>adj</pos> on
# διακωλυτέος. 932 entries were showing the code as if it were the
# print's own abbreviation. Only the bare lowercase codes go; a <pos>
# holding the print's own wording is left alone.
_ML_POS_CODE = re.compile(
    r"<pos>\s*(?:n|adj|v|adv|prep|conj|part|pron|interj|num|exclam)\s*</pos>")
# A sense the file numbers "Perseus". 18 entries showed "Perseus." where
# the reader expects a sense number. One of them (ἄν1) is an empty
# placeholder and goes whole; the other 17 carry the summary line the
# print sets at the head of a preposition entry ("down, downwards, with
# gen. or acc." at κατά), so only the machine number goes and the text
# stays, as the n="0" rule already does for the unnumbered first sense.
_ML_PERSEUS_EMPTY = re.compile(
    r'<sense[^>]*\sn="Perseus"[^>]*>\s*(?:<trans>\s*<tr>\s*</tr>\s*</trans>)?\s*</sense>')
_ML_PERSEUS_SENSE = re.compile(r'(<sense [^>]*?) n="Perseus"')
_ML_SENSE_N0 = re.compile(r'(<sense [^>]*?) n="0"')
# A '_' or '^' after a Greek letter (and its marks) is a length mark;
# both together mark anceps, and one written after a compound's hyphen
# ("δια-^πάλη") belongs to the vowel before the hyphen.
_ML_LENGTH = re.compile(r"([Ͱ-Ͽ])([̀-ͯ]*)([_^]*)(-?)([_^]*)")
_ML_LENGTH_MARK = {"_": "̄", "^": "̆"}
_ML_LATIN = re.compile(r'(<foreign lang="la">)([^<]*)(</foreign>)')
_ML_GREEK = re.compile(
    r'(<(foreign|orth|ref|note) [^>]*?lang="greek"[^>]*>)([^<]*)(</\2>)'
)
_ML_BETA = re.compile(r"^(?=.*[A-Za-z][()/\\=|])[A-Za-z()/\\=|+*'\s.,;:?!_^0-9-]+$")
# Beta Code in untagged text, one token at a time. A token starts with a
# letter or '*' and converts only when an accent or subscript follows a
# lowercase vowel or breathing, or a breathing sits on the initial
# lowercase vowel: "tau/th|", "=eu)nhth/r", "a)p." do, but "id=Aesch.",
# "(tune)and", "much)longed" and the sense reference "II)" do not.
_ML_TOKEN = re.compile(
    r"(?<![^\s>=(!-])((?:\*[()/\\=|+]*)?[A-Za-z][A-Za-z()/\\=|+'^_]*[0-9]?)(?=[\s<.,;:)]|$)"
)
_ML_TOKEN_ACCENT = re.compile(r"[aehiouw()+][/\\=|]")
_ML_TOKEN_BREATHING = re.compile(r"^(?:\*[()]|[aehiouw]{1,2}[()])")


def _ml_entity(m: re.Match) -> str:
    name = m.group(1)
    if name in _ML_XML_ENTITIES:
        return m.group(0)
    return html5.get(name + ";", m.group(0))


def _ml_greek(m: re.Match) -> str:
    open_tag, _tag, text, close = m.groups()
    if _ML_BETA.match(text):
        # 87 Greek-tagged strings Perseus never converted (three of them
        # the orths of the duplicate-key entries).
        text = beta_to_unicode(text)
    return open_tag + text + close


def _ml_token(m: re.Match) -> str:
    token = m.group(1)
    if _ML_TOKEN_ACCENT.search(token) or _ML_TOKEN_BREATHING.match(token):
        return beta_to_unicode(token)
    return token


def _ml_text(m: re.Match) -> str:
    return _ML_TOKEN.sub(_ml_token, m.group(0))


def ml_fragment_fix(fragment: str) -> str:
    """Make one Middle Liddell <entry> fragment parse and render like an
    LSJ <div2>. Applied only to grc-ml, never to the Diogenes lexica.

    - HTML named entities (&mdash; and a dozen others) are not XML.
    - XML comments (Perseus editing notes) sit inside text elements.
    - 82 tags write lang=greek / lang=la unquoted.
    - <note anchored="yes"> with no other attribute is a Perseus-internal
      Beta Code stem annotation inside <gramGrp>, not printed text; a
      note beginning "#" is a Perseus "#skipped" marker.
    - The unnumbered opening sense carries n="0"; without a number it
      renders like LSJ's unnumbered level-1 sense instead of "0.".
    - Length marks stay as '_' and '^' in the Unicode text; they ship as
      macron/breve placed before the other marks, the way the LSJ pack
      carries ᾱ and ᾰ. Latin in <foreign lang="la"> gets latin_display,
      as in the L&S pack.
    - Beta Code the conversion missed, in Greek-tagged text (_ml_greek)
      and in untagged text (_ml_token).
    """
    fragment = _ML_ENTITY.sub(_ml_entity, fragment)
    fragment = _ML_COMMENT.sub("", fragment)
    fragment = _ML_LANG.sub(r'\1"\2"', fragment)
    fragment = _ML_STEM_NOTE.sub("", fragment)
    fragment = _ML_SKIPPED_NOTE.sub("", fragment)
    fragment = _ML_USG_ID.sub(r"\1", fragment)
    fragment = _ML_POS_CODE.sub("", fragment)
    fragment = _ML_PERSEUS_EMPTY.sub("", fragment)
    fragment = _ML_PERSEUS_SENSE.sub(r"\1", fragment)
    fragment = _ML_SENSE_N0.sub(r"\1", fragment)
    fragment = unicodedata.normalize("NFD", canonical_marks(fragment))
    fragment = _ML_LENGTH.sub(
        lambda m: m.group(1)
        + "".join(_ML_LENGTH_MARK[c] for c in m.group(3) + m.group(5))
        + m.group(2) + m.group(4),
        fragment,
    )
    fragment = _ML_LATIN.sub(
        lambda m: m.group(1) + latin_display(m.group(2)) + m.group(3), fragment
    )
    fragment = _ML_GREEK.sub(_ml_greek, fragment)
    fragment = re.sub(r">[^<]+<", _ml_text, fragment)
    return unicodedata.normalize("NFC", fragment)


def parse_lexicon(path: Path, entry_tag: str, greek: bool,
                  head_path: str = "head", fix=None):
    """Stream a Diogenes lexicon (a headerless series of <divN> fragments)
    into buckets, key indexes for the lemma ladder, and short defs.

    head_path names the element whose text is the display head; fix, when
    given, rewrites each entry fragment before it is parsed (grc-ml)."""
    open_re = re.compile(rf"<{entry_tag} ")
    key_re = re.compile(rf'<{entry_tag} [^>]*key="([^"]*)"')
    close = f"</{entry_tag}>"

    buckets: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    all_keys: set[str] = set()
    base_index: dict[str, list[str]] = defaultdict(list)
    fold_index: dict[str, list[str]] = defaultdict(list)
    short_defs: dict[str, str] = {}
    n_entries = 0
    n_bad = 0

    buf: list[str] = []
    key = ""
    want = False
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if open_re.search(line):
                m = key_re.search(line)
                # Keys are raw XML attribute text; ~70 LSJ keys carry
                # entities (&lt;z&gt;) that must be unescaped or their
                # folds grow phantom letters and lemma resolution fails.
                key = unescape(m.group(1)) if m else ""
                want = bool(key)
                buf = []
            if want:
                buf.append(line)
                if close in line:
                    fragment = "".join(buf)
                    start = fragment.index(f"<{entry_tag} ")
                    end = fragment.rindex(close) + len(close)
                    entry_xml = fragment[start:end]
                    if fix is not None:
                        entry_xml = fix(entry_xml)
                    html = ""
                    head = ""
                    sdef = ""
                    try:
                        root = ET.fromstring(entry_xml)
                        head = root.findtext(head_path) or ""
                        html = entry_html(root)
                        sdef = derive_short_def(root)
                    except ET.ParseError:
                        n_bad += 1
                        html = escape(
                            re.sub(r"<[^>]+>", " ", entry_xml)
                        ).strip()
                    if not head:
                        head = beta_to_unicode(key) if greek else latin_display(key)
                    folded = beta_fold(key) if greek else latin_fold(key)
                    if folded:
                        buckets[bucket_name(folded)][folded].append(
                            {"key": key, "head": head, "html": html}
                        )
                        all_keys.add(key)
                        base_index[_BASE_STRIP.sub("", key)].append(key)
                        fold_index[folded].append(key)
                        if sdef:
                            short_defs[key] = sdef
                        n_entries += 1
                    want = False
    return buckets, all_keys, base_index, fold_index, short_defs, n_entries, n_bad


# --------------------------------------------------------- lemma -> keys

# Morpheus analyses a form it cannot find whole as prefix plus simplex
# and writes the lemma with a hyphen: "ἀπό-ἅζομαι", "σύν-ὀμάζω",
# "ἐν-λείβω". No such key exists in LSJ, so 13,994 of the 24,214
# unresolved Greek lemmas were these. Joining the prefix by the
# ordinary rules — elision before a vowel, aspiration before a rough
# breathing, ἐκ to ἐξ, the nasal of ἐν and σύν assimilated — finds the
# compound LSJ does list (ἀφάζομαι, ἐλλείβω); when it does not, the
# simplex is the entry the reader wants, and the display lemma still
# shows the compound Morpheus read.
_VOWELS = "αεηιουω"
_ASPIRATE = {"π": "φ", "τ": "θ", "κ": "χ"}


def _bare(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text)
                   if not unicodedata.combining(c))


def _unaccented(text: str) -> str:
    """Letters and breathings only: the prefix's own breathing stays,
    its accent (which the compound moves) goes."""
    return unicodedata.normalize("NFC", "".join(
        c for c in unicodedata.normalize("NFD", text)
        if not unicodedata.combining(c) or c in "\u0313\u0314"))


def join_compound(lemma: str) -> str | None:
    """The compound a hyphenated Morpheus lemma spells, in Unicode, or
    None when the shape is not one prefix and one simplex."""
    prefix, sep, base = lemma.partition("-")
    if not sep or not prefix or not base or "-" in base or "," in prefix:
        return None
    p = _unaccented(prefix).lower()
    first = _bare(base)[:1].lower()
    if not first:
        return None
    if p in ("ἐκ", "ἐξ") and first in _VOWELS:
        return "ἐξ" + unicodedata.normalize("NFC", _strip_breathing(base))
    if first in _VOWELS:
        rough = "\u0314" in unicodedata.normalize("NFD", base)[:3]
        # The breathing is the simplex's; inside the compound it goes.
        base = unicodedata.normalize("NFC", _strip_breathing(base))
        if _bare(p) in ("περι", "προ", "αμφι"):
            return p + base
        if _bare(p)[-1:] in _VOWELS:
            p = p[:-1]
        if rough and p[-1:] in _ASPIRATE:
            p = p[:-1] + _ASPIRATE[p[-1]]
        return p + base
    if _bare(p) in ("εν", "συν"):
        stem = p[:-1]
        if first in "πβφμψ":
            return stem + "μ" + base
        if first in "γκχξ":
            return stem + "γ" + base
        if first == "λ":
            return stem + "λ" + base
        if _bare(p) == "συν" and first in "σζ":
            return stem + base
        if _bare(p) == "συν" and first == "ρ":
            return stem + "ρ" + base
    return p + base


def _strip_breathing(base: str) -> str:
    decomposed = unicodedata.normalize("NFD", base)
    return decomposed[:3].replace("\u0313", "").replace("\u0314", "") + decomposed[3:]


def resolve_lemmas(
    lemmas: set[str],
    all_keys: set[str],
    base_index: dict[str, list[str]],
    fold_index: dict[str, list[str]],
    greek: bool,
) -> dict[str, list[str]]:
    """Ranked ladder from stage5: exact, digit-stripped base, ascii fold —
    plus the Morpheus/LSJ headword mismatches (-ws adverbs under the
    adjective, -teos verbals under -teon), and last a hyphenated
    compound joined, then its simplex (join_compound)."""
    out: dict[str, list[str]] = {}
    for lemma in lemmas:
        raw = lemma.replace("#", "")
        cands: list[tuple[str, str]] = [("exact", raw), ("base", _BASE_STRIP.sub("", raw))]
        fold = beta_fold(raw) if greek else latin_fold(raw)
        cands.append(("fold", fold))
        if greek and fold.endswith("ws"):
            cands.append(("fold", fold[:-2] + "hs"))
        if greek and fold.endswith("teos"):
            cands.append(("fold", fold[:-4] + "teon"))
        if greek and "-" in raw:
            joined = join_compound(beta_to_unicode(raw))
            if joined:
                cands.append(("fold", greek_display_fold(joined)))
            cands.append(("fold", beta_fold(raw.rsplit("-", 1)[1])))
        matched: list[str] | None = None
        for kind, value in cands:
            if kind == "exact" and value in all_keys:
                matched = [value]
            elif kind == "base" and base_index.get(value):
                matched = sorted(set(base_index[value]))
            elif kind == "fold" and fold_index.get(value):
                matched = sorted(set(fold_index[value]))
            if matched:
                break
        if matched:
            out[lemma] = matched
    return out


def repair_gloss(gloss: str, derived: str) -> str:
    """Swap in the derived def only when the shipped gloss is its
    word-boundary prefix (the stage7 rule), or fill a blank gloss."""
    if not derived:
        return gloss
    if not gloss:
        return derived
    if derived == gloss:
        return gloss
    if derived.startswith(gloss):
        boundary = derived[len(gloss)]
        if not boundary.isalnum() or gloss.endswith((" ", "-", ",")):
            return derived
    return gloss


# ---------------------------------------------------------------- output

def finalize_analyses(buckets, lemma_map, short_defs, greek: bool):
    """Rewrite rows in place: resolve lemma display + dictionary keys and
    repair glosses. Row becomes [lemmaDisplay, dictKeys[], gloss, parse,
    formVariant|null]. dictKeys is a real array — Lewis & Short has 78
    keys containing spaces, so a joined string cannot round-trip."""
    for bucket in buckets.values():
        for folded in bucket.values():
            for form, rows in folded.items():
                for row in rows:
                    lemma, gloss, parse, variant = row
                    bare, hom = homonym_split(lemma)
                    disp = beta_to_unicode(bare) if greek else latin_display(bare)
                    if hom:
                        disp = f"{disp} ({hom})"
                    keys = lemma_map.get(lemma, [])
                    if keys:
                        gloss = repair_gloss(gloss, short_defs.get(keys[0], ""))
                    row[:] = [disp, keys, gloss, parse, variant]


def write_pack(out_dir: Path, name: str, buckets, extra_meta: dict) -> dict:
    pack_path = out_dir / f"{name}.pack"
    index: dict[str, list[int]] = {}
    offset = 0
    with open(pack_path, "wb") as pack:
        for bk in sorted(buckets):
            payload = json.dumps(
                buckets[bk], ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
            member = gzip.compress(payload, 6)
            pack.write(member)
            index[bk] = [offset, len(member)]
            offset += len(member)
    sha = hashlib.sha256(pack_path.read_bytes()).hexdigest()
    idx = {"format": 1, "pack": f"{name}.pack", "sha256": sha, "buckets": index, **extra_meta}
    (out_dir / f"{name}.idx.json").write_text(
        json.dumps(idx, ensure_ascii=False), encoding="utf-8"
    )
    return {"pack_bytes": offset, "buckets": len(index), "sha256": sha, **extra_meta}



# ------------------------------------------------------------------ T8

# An entry the transform cannot read is a bug to look at, not a row to
# drop quietly, so the ceiling is zero. It was briefly 0.4%, a number
# carried over from an unrelated measurement, and it waved through 127
# entries broken by a name the transform no longer defined. A tolerance
# nobody has justified for a named cause is not a tolerance.
T8_ERR_CEILING: dict[str, float] = {}
T8_ERR_DEFAULT = 0.0

_STRIP_TAGS = re.compile(r"<[^>]+>")


def _visible(html: str) -> str:
    """What the reader can actually read. Punctuation alone is not a
    gloss — a row shipping a bare "=" or "(" is blank to them, and
    testing for non-empty text let 287 of those through — but a number
    is: LSJ defines ἐπιπενταμερής as "= 1+5/6" and means it."""
    text = unescape(_STRIP_TAGS.sub("", html or ""))
    return text.strip() if re.search(r"[^\W_]", text) else ""


def build_t8(out_dir: Path, dataset: str, analyses: str, lang: str,
             name: str, expect: int, limit: int | None = None) -> dict:
    """Render every entry of a lexicon pack into T8 rows.

    Reads the pack just written, so cross-entry lookups (a Greek gloss
    pulled from the entry it points at, 'fem. of sq.' resolved against
    the neighbouring key) work exactly as they do in the design mock —
    same code, one path. See SPEC-t8-rows.md.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import extract
    import t8rows

    extract.PACKDIR = str(out_dir)
    t8rows.configure(dataset, analyses, lang)

    idx = json.loads((out_dir / f"{dataset}.idx.json").read_text())
    names = sorted(idx["buckets"])
    if limit:
        names = names[:limit]

    buckets: dict[str, dict[str, list]] = {}
    n = blank = bare = unlabelled = hollow = bare_source = 0
    errs: list[tuple[str, str]] = []
    blank_eg: list[str] = []
    bare_eg: list[str] = []
    hollow_eg: list[str] = []
    for i, bname in enumerate(names, 1):
        src = extract.load_bucket(dataset, bname) or {}
        out: dict[str, list] = {}
        for folded, recs in src.items():
            docs = []
            for rec in recs:
                head = rec.get("head") or folded
                try:
                    m = t8rows.model(head, rec)
                    d = t8rows.to_doc(m, rec.get("key") or "")
                except Exception as exc:                     # noqa: BLE001
                    errs.append((rec.get("key") or head, type(exc).__name__))
                    continue
                rows = d["rows"]
                for j, r in enumerate(rows):
                    if _visible(r.get("z", "")):
                        continue
                    who = f'{rec.get("key") or head} {r.get("n") or "?"}'
                    kids = (j + 1 < len(rows)
                            and rows[j + 1]["lv"] > r["lv"])
                    if r.get("b"):
                        # A division the print never labelled (μέν A has
                        # neither gloss nor evidence) is an address, not a
                        # stripped header — but only if it heads senses.
                        if kids:
                            unlabelled += 1
                        else:
                            bare += 1
                            bare_eg.append(who)
                    else:
                        # The reader sees the sense line before any drawer
                        # or child rows. Evidence cannot turn punctuation
                        # into a readable gloss.
                        blank += 1
                        blank_eg.append(who)
                if t8rows.source_is_bare(rec["html"]):
                    bare_source += 1
                elif (not d["rows"] and not d.get("f") and not d.get("p")
                        and not d.get("i") and not d.get("gl")
                        and not d.get("au")):
                    # Match the renderer audit's visible fields exactly.
                    # These are the same fields the renderer exposes,
                    # including entry-level citation tokens.
                    hollow += 1
                    hollow_eg.append(rec.get("key") or head)
                docs.append(d)
                n += 1
            if docs:
                out[folded] = docs
        if out:
            buckets[bname] = out
        if i % 50 == 0:
            print(f"  {name}: {i}/{len(names)} buckets, {n} entries", flush=True)

    rate = len(errs) / max(n + len(errs), 1)
    ceiling = T8_ERR_CEILING.get(dataset, T8_ERR_DEFAULT)
    problems = []
    if hollow:
        problems.append(
            f"{hollow} entries render nothing at all — headword and blank: "
            f"{hollow_eg[:8]}")
    if blank:
        problems.append(f"{blank} senses render with no gloss: {blank_eg[:8]}")
    if bare:
        problems.append(f"{bare} banners render with no label: {bare_eg[:8]}")
    if rate > ceiling:
        problems.append(
            f"transform failed on {len(errs)} of {n + len(errs)} entries "
            f"({rate:.3%}, ceiling {ceiling:.3%}); first: {errs[:5]}")
    if limit is None and n + len(errs) != expect:
        problems.append(
            f"rendered {n + len(errs)} entries, lexicon pack has {expect} — "
            "content has been dropped")
    if problems:
        raise SystemExit("T8 build gate failed for " + name + ":\n  "
                         + "\n  ".join(problems))

    if limit is not None:
        # A smoke test must never leave a truncated pack behind: the
        # gates have run and reported, and that is all it is for.
        print(f"  {name}: {n} entries over {len(names)} bucket(s), "
              f"{len(errs)} unreadable — smoke test, pack not written",
              flush=True)
        return {"entries": n, "errors": len(errs), "smoke_test": True}
    meta = write_pack(out_dir, name, buckets,
                      {"entries": n, "errors": len(errs),
                       "error_rate": round(rate, 5),
                       "unlabelled_divisions": unlabelled,
                       "bare_in_print": bare_source, "source": dataset})
    print(f"  {name}: {n} entries, {len(errs)} unreadable ({rate:.3%}), "
          f"{unlabelled} divisions the print left unlabelled, "
          f"{bare_source} entries bare in the print", flush=True)
    return meta


def build_ml(out_dir: Path, manifest: dict) -> None:
    """Build grc-ml from the fetched Middle Liddell TEI and record it in
    the manifest. No analyses link to it and no T8 pack is derived from
    it: the T8 row transform is not applied to grc-ml (a later decision).
    """
    if not ML_SOURCE.exists():
        raise SystemExit(f"{ML_SOURCE} missing: run fetch_ml.py first")
    data = ML_SOURCE.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    if sha != ML_SHA256:
        raise SystemExit(f"{ML_SOURCE}: sha256 {sha}, pinned {ML_SHA256}")
    print("middle liddell…", flush=True)
    ml_buckets, _keys, _base, _fold, _defs, ml_n, ml_bad = parse_lexicon(
        ML_SOURCE, "entry", greek=True, head_path="form/orth", fix=ml_fragment_fix
    )
    print(f"  {ml_n} entries ({ml_bad} fallback-rendered)", flush=True)
    manifest["datasets"]["grc-ml"] = write_pack(
        out_dir, "grc-ml", ml_buckets, {"entries": ml_n, "fallback_rendered": ml_bad}
    )
    manifest["sources"][ML_FILE] = {
        "bytes": len(data), "sha256": sha,
        "repo": "PerseusDL/canonical-pdlrefwk", "commit": ML_COMMIT,
    }
    manifest["license"] = LICENSE


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--t8-only", action="store_true",
                    help="rebuild only the T8 row packs, from the lexicon "
                         "packs already in --out")
    ap.add_argument("--ml-only", action="store_true",
                    help="build only grc-ml from sources/ (no Diogenes "
                         "data needed); other manifest entries are kept")
    ap.add_argument("--t8-limit", type=int, default=None,
                    help="T8 smoke test: first N buckets only, gates that "
                         "count whole-pack content relaxed")
    args = ap.parse_args()
    out_dir: Path = args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.ml_only:
        mpath = out_dir / "manifest.json"
        manifest = json.loads(mpath.read_text()) if mpath.exists() else {
            "format": 2, "datasets": {}, "sources": {}}
        build_ml(out_dir, manifest)
        mpath.write_text(json.dumps(manifest, indent=1, ensure_ascii=False),
                         encoding="utf-8")
        print("done:", out_dir, flush=True)
        return 0

    if args.t8_only:
        mpath = out_dir / "manifest.json"
        manifest = json.loads(mpath.read_text()) if mpath.exists() else {
            "format": 2, "datasets": {}, "sources": {}}
        for ds, an, lang, name in (
            ("grc-lsj", "grc-analyses", "grc", "grc-lsj-t8"),
            ("lat-ls", "lat-analyses", "la", "lat-ls-t8"),
        ):
            expect = (manifest.get("datasets", {}).get(ds, {}) or {}).get("entries", 0)
            print(f"{name}…", flush=True)
            manifest.setdefault("datasets", {})[name] = build_t8(
                out_dir, ds, an, lang, name, expect, limit=args.t8_limit)
        if args.t8_limit:
            print("smoke test only — manifest not written", flush=True)
        else:
            mpath.write_text(json.dumps(manifest, indent=1, ensure_ascii=False),
                             encoding="utf-8")
        print("done:", out_dir, flush=True)
        return 0
    manifest: dict = {"format": 2, "datasets": {}, "sources": {}, "license": LICENSE}

    for fname in [
        "greek-analyses.txt", "latin-analyses.txt",
        "grc.lsj.xml", "lat.ls.perseus-eng1.xml",
    ]:
        p = DIOGENES_DATA / fname
        manifest["sources"][fname] = {"bytes": p.stat().st_size}

    # ---- Greek
    print("greek analyses…", flush=True)
    grc_buckets, grc_lemmas, grc_forms, grc_aliases = parse_analyses(
        DIOGENES_DATA / "greek-analyses.txt", greek=True
    )
    print(f"  {grc_forms} forms, {grc_aliases} variant aliases, {len(grc_lemmas)} lemmas", flush=True)
    print("lsj…", flush=True)
    lsj_buckets, lsj_keys, lsj_base, lsj_fold, lsj_defs, lsj_n, lsj_bad = parse_lexicon(
        DIOGENES_DATA / "grc.lsj.xml", "div2", greek=True
    )
    print(f"  {lsj_n} entries ({lsj_bad} fallback-rendered)", flush=True)
    lemma_map = resolve_lemmas(grc_lemmas, lsj_keys, lsj_base, lsj_fold, greek=True)
    print(f"  lemma->LSJ resolved {len(lemma_map)}/{len(grc_lemmas)}", flush=True)
    finalize_analyses(grc_buckets, lemma_map, lsj_defs, greek=True)
    manifest["datasets"]["grc-analyses"] = write_pack(
        out_dir, "grc-analyses", grc_buckets,
        {"forms": grc_forms, "variant_aliases": grc_aliases, "lemmas": len(grc_lemmas), "lemmas_resolved": len(lemma_map)},
    )
    manifest["datasets"]["grc-lsj"] = write_pack(
        out_dir, "grc-lsj", lsj_buckets, {"entries": lsj_n, "fallback_rendered": lsj_bad}
    )
    del grc_buckets, lsj_buckets, lsj_keys, lsj_base, lsj_fold
    print("grc-lsj-t8…", flush=True)
    manifest["datasets"]["grc-lsj-t8"] = build_t8(
        out_dir, "grc-lsj", "grc-analyses", "grc", "grc-lsj-t8", lsj_n)

    # ---- Latin
    print("latin analyses…", flush=True)
    lat_buckets, lat_lemmas, lat_forms, lat_aliases = parse_analyses(
        DIOGENES_DATA / "latin-analyses.txt", greek=False
    )
    print(f"  {lat_forms} forms, {lat_aliases} variant aliases, {len(lat_lemmas)} lemmas", flush=True)
    print("lewis-short…", flush=True)
    ls_buckets, ls_keys, ls_base, ls_fold, ls_defs, ls_n, ls_bad = parse_lexicon(
        DIOGENES_DATA / "lat.ls.perseus-eng1.xml", "div1", greek=False
    )
    print(f"  {ls_n} entries ({ls_bad} fallback-rendered)", flush=True)
    lat_map = resolve_lemmas(lat_lemmas, ls_keys, ls_base, ls_fold, greek=False)
    print(f"  lemma->L&S resolved {len(lat_map)}/{len(lat_lemmas)}", flush=True)
    finalize_analyses(lat_buckets, lat_map, ls_defs, greek=False)
    manifest["datasets"]["lat-analyses"] = write_pack(
        out_dir, "lat-analyses", lat_buckets,
        {"forms": lat_forms, "variant_aliases": lat_aliases, "lemmas": len(lat_lemmas), "lemmas_resolved": len(lat_map)},
    )
    manifest["datasets"]["lat-ls"] = write_pack(
        out_dir, "lat-ls", ls_buckets, {"entries": ls_n, "fallback_rendered": ls_bad}
    )
    print("lat-ls-t8…", flush=True)
    manifest["datasets"]["lat-ls-t8"] = build_t8(
        out_dir, "lat-ls", "lat-analyses", "la", "lat-ls-t8", ls_n)

    # ---- Middle Liddell (only when fetched; the Diogenes packs never
    # depend on it)
    if ML_SOURCE.exists():
        build_ml(out_dir, manifest)
    else:
        print(f"grc-ml skipped: {ML_SOURCE} not fetched", flush=True)

    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8"
    )
    print("done:", out_dir, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
