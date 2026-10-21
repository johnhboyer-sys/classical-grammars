"""Shared mechanics for dictionary-entry design mockups.

Everything here is tag- and entity-aware string surgery over the pack HTML.
Safe because the sense markup is verified flat (0 nested divs in 253,287
sense blocks across both packs).
"""
import re
import html as htmllib

SENSE_OPEN = re.compile(r'<div class="lx-sense" data-level="(\d+)">')
SENSE_N = re.compile(r'^\s*<b class="lx-sense-n">(.*?)</b>[\s,]*', re.S)
STRIP = re.compile(r'<[^>]+>')
TAG_TOKEN = re.compile(r'<[^>]+>|&[a-zA-Z#0-9]+;|.', re.S)


def text_of(fragment):
    return htmllib.unescape(STRIP.sub('', fragment)).strip()


def sense_spans(h):
    """Yield (start, end_of_open_tag, close_start, level) per sense block."""
    for m in SENSE_OPEN.finditer(h):
        close = h.find('</div>', m.end())
        yield m.start(), m.end(), close, int(m.group(1))


def senses(h):
    """[(level, body_html)] for every sense block."""
    return [(lvl, h[oe:c]) for _, oe, c, lvl in sense_spans(h)]


def rel_base(h):
    lv = [s[3] for s in sense_spans(h)]
    return min(lv) if lv else 0


def split_preamble(h):
    m = SENSE_OPEN.search(h)
    return (h, '') if not m else (h[:m.start()], h[m.start():])


# A citation the transform wrapped itself (t8rows.mark_prose_authors,
# data-bare) was a bare author in Perseus, and the definition zone ran
# past those; it still does, so the print's material after one stays
# in the definition.
CIT_OPEN = re.compile(r'<span class="lx-(?:cit|bibl)\b(?![^>]*data-bare)')
TAG_RE = re.compile(r'<[^>]+>')
TAG_NAME = re.compile(r'<\s*/?\s*([A-Za-z][\w:-]*)')
QUOTE_SPAN = re.compile(r'class="lx-(?:foreign|quote)\b')
GAP_RE = re.compile(r'&[#a-zA-Z0-9]{1,8};|:—|[()]|[:;]')
POS_CLASS = re.compile(r'class="lx-pos"')
REF_CLASS = re.compile(r'class="lx-(?:cit|bibl|title|author|date|placeName)\b')


def _bare_wrapper_start(body, at):
    """Start of the bare wrapper open at `at`, or None when none is."""
    start = body.rfind('<span class="lx-bibl" data-bare="1">', 0, at)
    if start < 0:
        return None
    depth = 0
    for m in re.finditer(r'<(/?)span\b[^>]*>', body[start:]):
        depth += -1 if m.group(1) else 1
        if depth == 0:
            return start if start + m.end() > at else None
    return start


def first_citation(body, pos=0, extra=''):
    """Offset where the first citation opens the evidence: one Perseus
    marked, not one the transform wrapped around a bare author
    (data-bare — the zone runs past those). A marked citation nested
    inside such a wrapper is the bare author's own tail, and the
    boundary is the wrapper's start: "Prop., <bare>Planc. ap. <Cic.
    Fam. 10, 18, 3></bare>" cut on the inner Cicero and left "Prop.,
    Planc. ap" on the row (cutis). Not the wrapper's end: past it lies
    the next quotation (L&S et "…duritudinem, Cato ap. Gell.: te sale
    nata precor…"), and the cut that segments a later definition arms
    from here."""
    pat = re.compile(r'<span class="lx-(?:cit|bibl' + ('|' + extra if extra else '')
                     + r')\b(?![^>]*data-bare)')
    m = pat.search(body, pos)
    if not m:
        return None
    start = _bare_wrapper_start(body, m.start())
    return m.start() if start is None else start


def _zone_cut(body):
    """Offset where a definition's prose ends and its evidence begins.

    A citation inside an open parenthesis is part of the prose, not the
    start of the evidence: LSJ οὐσία II reads "like φύσις (with which it
    is interchanged in various uses, e. g. Philol. 11, Pl. R. 359a …),
    stable being, immutable reality" — cutting at Philol. 11 threw away
    the definition after the close-paren. The zone never ends mid-paren.

    A short parenthetical citation cluster is prose (οὐσία II's "e. g.
    Philol. 11 … Thphr. HP 6.1.1" is ~65 visible chars); a long one is an
    apparatus block the zone must not swallow (L&S aequor ran to 600+
    chars of editions). Bound by visible text, and cut at the citation as
    before when it is exceeded."""
    pos = 0
    while True:
        at = first_citation(body, pos)
        if at is None:
            return len(body)
        depth = body.count('(', 0, at) - body.count(')', 0, at)
        if depth <= 0:
            return at
        close = body.find(')', at)
        if close < 0 or len(text_of(body[at:close])) > 120:
            return at
        pos = close + 1


def defzone(body):
    """(zone_html, evidence_html) for the sense's FIRST definition —
    its opening prose up to the first citation, and everything after."""
    body = SENSE_N.sub('', body, count=1)
    at = _zone_cut(body)
    return body[:at], body[at:]


def _segment_cuts(body, first_ev):
    """Offsets in `body` where the print starts another definition.

    LSJ writes several definitions into one sense paragraph, each a
    rubric and an italic gloss with its own quotations after it: ἁβρός is
    "graceful, delicate, pretty … of things, splendid … of style,
    graceful, pretty … freq. with a notion of disparagement, dainty,
    luxurious". Everything past the first gloss looked like apparatus and
    was dropped, so 14,848 Greek entries shipped one of the several
    meanings the print gives.

    A plain <i> — the print's translation cue, never <i class="lx-title">
    — opens the next definition when a reference has closed since the
    last one and no unreferenced quotation stands between them. The cut
    lands on the print's own ':' or ';' before the rubric, so "of things,"
    leads the new definition instead of trailing the old evidence.

    An <i> that translates the quotation beside it (ἁβρὰ παθεῖν live
    *delicately*) is that example's gloss, not a new sense; the bare
    quotation before it is what says so. An <i> inside an open parenthesis
    is apparatus, not a gloss: πρατήριον cites "PTeb. 701 (a). 7", whose
    part letter is set in italics like any other. A quotation is done
    being quoted once any reference follows it — ἁβρός's "ἁ. ἄθυρμα, of a pet dog, IG
    14.1647 (Lipara)" ends on a title and a place, neither of them
    wrapped in lx-bibl, and "of things, splendid" after it is a sense."""
    cuts = []
    stack = []         # open (tag name, is a reference) elements
    refs = 0           # how many of them are references
    ev_end = None      # end offset of the last reference to close
    armed = False      # a reference has closed since the last cut
    quoted = False     # an unreferenced quotation stands between it and here
    sep = None         # last ':' or ';' the print wrote since then
    paren = 0          # open parentheses in the print's own text
    held = False       # a reference closed inside them, still unclosed
    pos = 0
    for m in TAG_RE.finditer(body):
        if not stack:
            for gm in GAP_RE.finditer(body, pos, m.start()):
                tok = gm.group(0)
                if tok == '(':
                    paren += 1
                elif tok == ')':
                    paren = max(0, paren - 1)
                    if not paren and held:
                        # The reference that closed inside the
                        # parenthesis owns it: ἄκοσμος II reads "AP 7.561
                        # (Jul.), but in 9.323 (Antip.)…". Arming at the
                        # author leaves the cut before the ')' and the
                        # next definition opens on a stray bracket.
                        ev_end, sep, held = gm.end(), None, False
                        armed = ev_end >= first_ev
                elif tok == ':—':
                    # The print's own block separator. What follows is a
                    # further block of the entry, not more evidence for
                    # the definition above it — ἀβάκχευτος ends "…Id. Or.
                    # 319 :—in late Prose, Luc. Laps. 3".
                    if not paren:
                        cuts.append(gm.end())
                        armed, sep, quoted = False, None, False
                elif not paren and armed and tok in ':;':
                    # Entities are matched first, so the ';' closing
                    # '&#x27;' is never read as the print's separator.
                    sep = gm.end()
        pos = m.end()
        tag = m.group(0)
        nm = TAG_NAME.match(tag)
        name = nm.group(1).lower() if nm else ''
        if name not in ('span', 'i'):
            continue
        if tag.startswith('</'):
            while stack and stack[-1][0] != name:
                stack.pop()
            if not stack:
                continue
            if stack.pop()[1]:
                refs -= 1
                if not refs:
                    if paren:
                        # What the print puts in parentheses is an aside
                        # and does not change the sentence outside them.
                        # So a reference in there is an aside about the
                        # quotation beside it, not that quotation's own
                        # citation — ἅπαξ writes "opp. δυοῖν δίς (2 x 2),
                        # four" and the "four" translates δυοῖν δίς — and
                        # the quotation stands. The same rule the other
                        # way up: a quotation inside the parentheses is
                        # part of the aside and never puts the sentence
                        # in quotation, which is why the ἀμπλ- in
                        # ἀναπλέκω's "(Andania, i B. C., in form ἀμπλ-)"
                        # does not hide the "Med., braid oneʼs hair"
                        # after it.
                        held = True
                    else:
                        ev_end, sep, held, quoted = pos, None, False, False
                        armed = pos >= first_ev
            continue
        if tag.endswith('/>'):
            continue
        if not refs and not paren and POS_CLASS.search(tag):
            # "Adv." heads a sub-entry with its own forms, glosses and
            # citations: ἀβαρής prints "…CIG 5361.15 (Berenice). Adv.
            # -ρῶς without giving offence, Simp." Left inside the
            # definition before it, Simp. is filed under "not
            # burdensome" and "without giving offence" is lost.
            cuts.append(m.start())
            armed, sep, quoted = False, None, False
        is_ref = bool(REF_CLASS.search(tag))
        if is_ref:
            refs += 1
        elif not refs:
            if QUOTE_SPAN.search(tag) and not paren:
                quoted = True
            elif tag == '<i>' and armed and not quoted and not paren:
                cuts.append(sep if sep is not None else ev_end)
                armed, sep = False, None
        stack.append((name, is_ref))
    return cuts


def defsegments(body):
    """[(zone_html, evidence_html)] — one pair per definition the print
    wrote into this sense. The pairs concatenate back to the sense body,
    so no wording is lost by segmenting; the first pair is exactly what
    defzone() returns when the sense holds only one definition."""
    body = SENSE_N.sub('', body, count=1)
    first = _zone_cut(body)
    bounds = [b for b in _segment_cuts(body, first) if b > first]
    out = []
    for start, end in zip([0] + bounds, bounds + [len(body)]):
        piece = body[start:end]
        at = _zone_cut(piece) if start else first
        out.append((piece[:at], piece[at:]))
    return out


def sense_number(body):
    m = SENSE_N.match(body)
    return m.group(1) if m else ''


def split_top_level(fragment, seps=':;'):
    """Split on separators outside any tag and outside entities ('&lt;' ends
    in ';'), tracking span depth so a ':' inside a span never splits."""
    parts, buf, depth = [], [], 0
    for tok in TAG_TOKEN.findall(fragment):
        if tok.startswith('<'):
            if tok.startswith('</'):
                depth -= 1
            elif not tok.endswith('/>') and not tok.startswith('<br'):
                depth += 1
            buf.append(tok)
            continue
        if len(tok) == 1 and tok in seps and depth == 0:
            parts.append(''.join(buf).strip())
            buf = []
        else:
            buf.append(tok)
    if ''.join(buf).strip():
        parts.append(''.join(buf).strip())
    return parts


LABEL_SPAN = re.compile(
    r'^\s*((?:<span class="lx-(?:tns|gram|mood|per|number|gramGrp)">.*?</span>[\s,]*)+)',
    re.S)


def forms_rows(preamble_html):
    """Cut a forms preamble into [label_html, content_html] rows at the
    print's own ':' and ';'. A segment with no leading grammar label folds
    into the previous row."""
    rows = []
    for seg in split_top_level(preamble_html):
        m = LABEL_SPAN.match(seg)
        if m:
            rows.append([m.group(1), seg[m.end():]])
        elif rows:
            rows[-1][1] += ' · ' + seg
        else:
            rows.append(['', seg])
    return rows


def first_element(h, cls):
    """Extract the first complete <span class="cls">…</span> element,
    nesting-safe. Returns (element_html, start, end) or None."""
    m = re.search(r'<span class="' + re.escape(cls) + r'[" ]', h)
    if not m:
        return None
    depth = 0
    pos = m.start()
    for t in re.finditer(r'<span\b[^>]*>|</span>', h[m.start():]):
        if t.group(0).startswith('</'):
            depth -= 1
            if depth == 0:
                end = m.start() + t.end()
                return h[m.start():end], m.start(), end
        else:
            depth += 1
    return None
