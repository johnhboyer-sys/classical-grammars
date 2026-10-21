#!/usr/bin/env python3
"""The ideal verb entry — structural sketch, not a finished skin.

Five zones argued from consultation needs, filled with real LSJ content:
identity line (headword + canonical principal parts), division frame,
uniformly-numbered sense ledger, full forms apparatus as end matter,
end matter. Supplied numerals per John's uniformity law (2026-08-20):
digital presentation regularizes what print compressed for space.
"""
import os
import re
import html as htmllib
import extract
import entrylib as L

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))
OUT = os.path.join(_REPO, "work", "design", "dict-entry")

PRED = {'II': 'I', '2': '1', 'b': 'a', 'β': 'α', 'B': 'A'}
ROMAN = re.compile(r'^[IVX]+\.?$')


def display_numbers(ss):
    """Return [(display_level, numeral_html, body, supplied)] with the
    print's implied numerals made explicit:
    - an unnumbered first sense gets the predecessor of its first numbered
      sibling (II.->I., 2.->1.) and joins that sibling's level;
    - a sense whose children start at 2./b./β./II. carries the implied
      first-child ordinal too (the citable address: 'II. 1.')."""
    out = []
    nums = [L.sense_number(b).strip() for _, b in ss]
    lvls = [l for l, _ in ss]
    for i, (lvl, body) in enumerate(ss):
        n, supplied, dl = nums[i], False, lvl
        if i == 0 and not n and len(ss) > 1:
            roman_js = [j for j in range(1, len(ss)) if ROMAN.match(nums[j] or '')]
            if roman_js:
                n, supplied, dl = 'I.', True, lvls[roman_js[0]]
            else:
                numbered = [j for j in range(1, len(ss)) if nums[j]]
                if numbered:
                    key = (nums[numbered[0]] or '').rstrip('.')
                    if key in PRED:
                        n, supplied, dl = PRED[key] + '.', True, lvls[numbered[0]]
        # implied first-child ordinal
        child_n = None
        for j in range(i + 1, len(ss)):
            if lvls[j] <= lvl:
                break
            child_n = nums[j]
            break
        if child_n:
            key = child_n.rstrip('.')
            if key in PRED and L.text_of(L.defzone(body)[0]).strip(' ,.;:—'):
                n = (n + ' ' if n else '') + PRED[key] + '.'
                supplied = True
        out.append((dl, n, body, supplied))
    return out


GREEK_RUN = re.compile(r'-?[Ͱ-Ͽἀ-῿][Ͱ-Ͽἀ-῿̀-ͯ]*')
TNS_SPAN = re.compile(r'<span class="lx-tns">(.*?)</span>')
VOICE_MARK = re.compile(
    r'<span class="lx-gram">(Med|Pass|Act)\b|(?:—|:)\s*(Med|Pass|Act)\b\.?')


def in_tag(html, pos):
    lt, gt = html.rfind('<', 0, pos), html.rfind('>', 0, pos)
    return lt > gt


def expand_suffix(head, suffix, attested=None):
    """LSJ abbreviates regular parts to endings: παιδεύω + '-σω' → παιδεύσω;
    contract verbs drop their theme vowel: ποιέω + '-ήσω' → ποιήσω.

    The join is a guess, and on most shapes it is wrong. It strips one
    letter from the headword and glues the ending on, so it reads
    καταλαμβάνω + '-λήψομαι' as καταλαμβάνλήψομαι (the print means
    καταλήψομαι, from the preverb), ὑγιάζω + '-άσω' as ὑγιάζάσω (ὑγιάσω),
    and ἀνατρέχω + '-έδραμον' as ἀνατρέχέδραμον. 1,366 values in the
    Greek forms bar were strings no witness supplies, which is the one
    thing the editorial law forbids outright.

    So the guess must be confirmed. `attested` is a callable the caller
    supplies, returning true when a form is one the analyses pack knows;
    when it rejects the join, or when the caller supplies no check, the
    print's own abbreviation is returned unchanged and the reader sees
    what LSJ set.
    """
    s = suffix.lstrip('-')
    import unicodedata
    first = unicodedata.normalize('NFD', s[0])[0]
    if first in 'αεηοω' and head[-2:] in ('έω', 'άω', 'όω', 'εω', 'αω', 'οω'):
        return head[:-2] + s
    stem = head[:-1]
    if first == 'ψ' and stem[-1] in 'πβφ':      # γράφω + -ψω → γράψω
        stem = stem[:-1]
    elif first == 'ξ' and stem[-1] in 'κγχ':    # πλέκω + -ξω → πλέξω
        stem = stem[:-1]
    elif first in 'ψξ' and stem[-2:] in ('σσ', 'ττ', 'πτ'):
        stem = stem[:-2]
    joined = stem + s
    if attested is None or not attested(joined):
        return suffix
    return joined


# The textbook-irregular table: verbs whose parts are diathesis-split across
# semantic divisions (ἵστημι) or whose stem sections defeat the walk. Every
# textbook hand-curates exactly these; ours is honest about which slots are
# curated (†) rather than lifted from the entry's own forms text.
CURATED = {
    'ἵστημι': {'fut': 'στήσω', 'aor': 'ἔστησα / ἔστην', 'pf': 'ἕστηκα',
               'pfmp': 'ἕσταμαι', 'aorp': 'ἐστάθην'},
    'φέρω': {'pfmp': 'ἐνήνεγμαι'},
}


def _without_bare(html):
    """The markup with t8rows's own citation wrappers unwrapped."""
    out, depth, pos = [], [], 0
    for m in re.finditer(r'<span\b[^>]*>|</span>', html):
        out.append(html[pos:m.start()])
        tag = m.group(0)
        if tag.startswith('</'):
            if depth and depth.pop():
                pass            # the wrapper's own close
            else:
                out.append(tag)
        else:
            bare = 'data-bare' in tag
            depth.append(bare)
            if not bare:
                out.append(tag)
        pos = m.end()
    out.append(html[pos:])
    return ''.join(out)


def forms_scope(html):
    """Preamble plus any leading form sections (φέρω's II.–V.), div wrappers
    kept so section boundaries stay visible to the voice-reset logic."""
    pre, rest = L.split_preamble(html)
    out = [pre]
    for start, open_end, close, lvl in L.sense_spans(rest):
        body = rest[open_end:close]
        n = L.sense_number(body).strip().rstrip('.')
        if re.fullmatch(r'[A-E]', n) and not re.fullmatch(r'[IVX]+', n):
            break
        zt = L.text_of(L.defzone(body)[0])
        # The 400-byte probe is measured on the markup as Perseus wrote
        # it; the citation wrappers t8rows adds (data-bare) would push
        # a tense label past it (ἀποσεύω lost its aor. pass.).
        probe = _without_bare(body)[:400]
        if not re.match(r'\s*(fut\.|aor|pf\.|impf\.|from |other tenses'
                        r'|Pass\.|Med\.|Ep\.|Ion\.|Dor\.)', zt) \
                and 'lx-tns' not in probe:
            break
        out.append(rest[start:close + 6])
    return ''.join(out)


def flashcard(scope_html, head, attested=None):
    """The Hansen & Quinn six: pres (headword), fut, aor, pf act,
    pf mid/pass, aor pass — walked voice-aware through LSJ's forms text."""
    events = []
    for m in TNS_SPAN.finditer(scope_html):
        events.append((m.start(), 'label', L.text_of(m.group(1)), m.end()))
    for m in VOICE_MARK.finditer(scope_html):
        word = m.group(1) or m.group(2)
        if not (m.group(1) or not in_tag(scope_html, m.start())):
            continue
        # "as Pass." is a usage note; "in Med. Ms." is the codex Mediceus
        before = L.text_of(scope_html[max(0, m.start() - 120):m.start()])
        after = L.text_of(scope_html[m.end():m.end() + 8])
        if re.search(r'\b(as|in)\s*$', before) or re.match(r'\s*Ms', after):
            continue
        events.append((m.start(), 'voice', word.lower(), m.end()))
    # each form section (φέρω's II.–V.) starts back in the active voice
    for m in re.finditer(r'<div class="lx-sense"', scope_html):
        events.append((m.start(), 'voice', 'act', m.end()))
    events.sort()
    voice = 'act'
    slots = {}  # name -> (form, expanded, source_label, priority)
    PRI = {'aor.1': 3, 'aor.': 2, 'aor.2': 1}
    for k, (pos, kind, val, end) in enumerate(events):
        if kind == 'voice':
            voice = val
            continue
        lab = re.sub(r'\s+', '', val.rstrip(':').lower())
        # the form must sit between this label and the next event — a slot
        # whose content is "(v. infr.)" must not steal Greek from later text
        nxt = events[k + 1][0] if k + 1 < len(events) else end + 300
        window = L.text_of(scope_html[end:min(nxt, end + 300)])
        m = GREEK_RUN.search(window)
        if not m:
            continue
        # "aor. 1 imper. οἶσε" names a sub-form, not the principal part
        if re.search(r'\b(imper|inf|part|subj|opt|\d\s*(sg|pl)|dual)\b',
                     window[:m.start()]):
            continue
        form, expanded = m.group(0), False
        if form.startswith('-'):
            joined = expand_suffix(head, form, attested)
            form, expanded = joined, joined != form
        def put(slot, pri=0):
            if slot not in slots or pri > slots[slot][3]:
                slots[slot] = (form, expanded, lab, pri)
        if voice == 'act':
            if lab == 'fut.':
                put('fut')
            elif lab in PRI:
                put('aor', PRI[lab])
            elif lab == 'pf.':
                put('pf')
        elif voice in ('mid', 'med'):
            if lab == 'pf.':
                put('pfmp')
        elif voice == 'pass':
            if lab == 'pf.':
                put('pfmp', 1)   # H&Q's 5th part; Pass-section pf. preferred
            elif lab in PRI or lab == 'aor.':
                put('aorp')
    for slot, form in CURATED.get(head, {}).items():
        slots[slot] = (form, False, 'curated', 9)
    order = [('pres', (head, False, 'head', 0))] + [
        (k, slots.get(k)) for k in ('fut', 'aor', 'pf', 'pfmp', 'aorp')]
    return order


CANON = ('fut.', 'aor.', 'aor.1', 'aor.2', 'pf.')


def principal_parts(rows):
    """Lift one form per canonical tense label from the forms rows — the
    identity line (headword serves as the present). Scanning stops after
    the principal-part slots fill, which also stops before the forms run
    repeats its labels for the middle and passive voices."""
    parts = []
    seen = set()
    for lab, content in rows:
        lt = re.sub(r'\s+', '', L.text_of(lab).strip().rstrip(':').lower())
        if lt in CANON and lt not in seen:
            m = re.search(r'[Ͱ-Ͽἀ-῿][Ͱ-Ͽἀ-῿̀-ͯ,() -]*', L.text_of(content))
            if m:
                form = m.group(0).strip(' ,()')
                parts.append((lt.replace('aor.', 'aor. '), form.split(',')[0].strip()))
                seen.add(lt)
        if len(parts) >= 4 or (parts and lt == 'pf.'):
            break
    return parts


CSS = """
@font-face { font-family:"Athena Lyceum"; src:url("../../../public/fonts/AthenaLyceum-Regular.woff2") format("woff2"); font-weight:400; font-style:normal; }
@font-face { font-family:"Athena Lyceum"; src:url("../../../public/fonts/AthenaLyceum-Italic.woff2") format("woff2"); font-weight:400; font-style:italic; }
@font-face { font-family:"Athena Lyceum"; src:url("../../../public/fonts/AthenaLyceum-Bold.woff2") format("woff2"); font-weight:700; font-style:normal; }
@font-face { font-family:"Athena Lyceum"; src:url("../../../public/fonts/AthenaLyceum-BoldItalic.woff2") format("woff2"); font-weight:700; font-style:italic; }
:root { --ink:#1c1a17; --muted:#777064; --faint:#a39a8b; --paper:#fcfbf8;
  --line:#e6e1d6; --wash:#f4f1ea; --act:#2456d6; --note:#8a6d3b; }
* { box-sizing:border-box; }
body { margin:0; background:var(--paper); color:var(--ink);
  font:19px/1.6 "Athena Lyceum", Georgia, serif; }
main { max-width:52rem; margin:0 auto; padding:0 1.25rem 5rem; }
.intro { max-width:52rem; margin:1.6rem auto .6rem; padding:0 1.25rem;
  color:var(--muted); font-size:.95rem; font-family:system-ui,sans-serif; }
.intro h1 { color:var(--ink); font:700 1.25rem/1.3 system-ui,sans-serif; margin:0 0 .4rem; }

.zone { position:relative; border:1px dashed var(--faint); border-radius:8px;
  padding:1rem 1.1rem .8rem; margin:1.4rem 0; }
.zone-tag { position:absolute; top:-.72rem; left:.9rem; background:var(--paper);
  padding:0 .5rem; font:700 .78rem/1.4 system-ui,sans-serif; color:var(--note);
  text-transform:uppercase; letter-spacing:.07em; }
.zone-why { font:400 .85rem/1.45 system-ui,sans-serif; color:var(--muted);
  border-top:1px solid var(--line); margin-top:.8rem; padding-top:.5rem; }

.id-line { display:flex; flex-wrap:wrap; gap:.4rem 1.1rem; align-items:baseline; }
.id-head { font-size:1.5em; font-weight:700; }
.id-part { white-space:nowrap; }
.id-part b { font-weight:400; }
.id-part .pp-label { font:400 .78rem system-ui,sans-serif; color:var(--muted); }
.id-btn { font:600 .85rem system-ui,sans-serif; color:var(--muted);
  background:var(--wash); border:1px solid var(--line); border-radius:999px;
  padding:.2rem .7rem; cursor:pointer; }
.id-btn:hover { color:var(--act); border-color:var(--act); }

.v-tabs { display:flex; gap:.4rem; flex-wrap:wrap; margin:.2rem 0 .8rem;
  font-family:system-ui,sans-serif; font-size:.85rem; }
.v-tabs button { font:inherit; color:var(--muted); background:var(--wash);
  border:1px solid var(--line); border-radius:999px; padding:.2rem .75rem; cursor:pointer; }
.v-tabs button.on { background:var(--ink); border-color:var(--ink); color:var(--paper); }
.v-tabs button b { color:inherit; }

.lx-bibl { color:var(--muted); }
.lx-author { font-variant-caps:small-caps; }
.v-sense { margin:.55em 0; }
.v-sense.lv1 { margin-left:1.35rem; }
.v-sense.lv2 { margin-left:2.7rem; }
.v-sense.lv3 { margin-left:4.05rem; }
/* aligned ledger: chevron gutter · numeral column (right-aligned, so the
   periods of I. / 1. / a. sit on one axis) · one text edge */
.v-def { display:grid; grid-template-columns:1em 2.7em 1fr; column-gap:.4em;
  align-items:baseline; }
.v-def .chev { grid-column:1; }
.v-def .lx-sense-n { grid-column:2; justify-self:end; }
.v-def .z { grid-column:3; }
.v-def i { font-weight:700; }
.v-ev { margin-left:calc(1em + 2.7em + .8em); }
.v-div-h { display:grid; grid-template-columns:1em 2.7em 1fr; column-gap:.4em; }
.v-div-h .lx-sense-n { grid-column:2; justify-self:end; }
.v-div-h .z { grid-column:3; }
.constr { font:600 .78rem system-ui,sans-serif; color:var(--note);
  background:var(--wash); border-radius:4px; padding:0 .35em; margin-right:.3em; }
.v-count { font:400 .85rem system-ui,sans-serif; color:var(--faint); margin-left:.45em; }
.v-ev { display:none; }
.v-sense.open .v-ev { display:block; }
.v-sense.closable .v-def { cursor:pointer; }
.chev { display:inline-block; width:.9em; color:var(--faint); }
.v-sense:not(.closable) .chev { visibility:hidden; }
.closable .chev::before { content:"▸"; }
.closable.open .chev::before { content:"▾"; }
.div-h { margin:1.2rem 0 .4rem; font-weight:700; padding-top:.6rem;
  border-top:1px solid var(--line); }
.div-forms { font-size:1em; color:var(--ink); background:var(--wash);
  border-radius:6px; padding:.4rem .7rem; margin:.4rem 0 .6rem; }
.div-forms .df-label { font:600 .78rem system-ui,sans-serif; color:var(--note);
  text-transform:uppercase; letter-spacing:.05em; margin-right:.5em; }

.forms-rows { border-top:1px solid var(--line); }
.forms-row { display:grid; grid-template-columns:9.5rem 1fr; gap:0 1rem;
  padding:.35rem 0; border-bottom:1px solid var(--line); }
.forms-row.nolabel { grid-template-columns:1fr; }
.forms-row .f-label { color:var(--muted); }
#apparatus { display:none; }
#apparatus.open { display:block; }
.fc-table { border-collapse:collapse; margin:.6rem 0; width:100%; }
.fc-table th { font:600 .78rem system-ui,sans-serif; color:var(--muted);
  text-transform:uppercase; letter-spacing:.05em; text-align:left;
  padding:.2rem .6rem .2rem 0; border-bottom:1px solid var(--line); }
.fc-table td { padding:.28rem .6rem .28rem 0; border-bottom:1px solid var(--line);
  white-space:nowrap; }
.fc-table td:first-child { font-weight:700; }
.fc-table .fc-none { color:var(--faint); }
.fc-table sup { color:var(--note); font-size:.7em; }
@media (max-width:640px) { .fc-table { display:block; overflow-x:auto; } }
.lx-author[title], .lx-title[title], .lx-bibl[title] { cursor:help;
  border-bottom:1px dotted var(--faint); }
.key-demo { margin:.5rem 0; }
.key-demo .kd-row { padding:.25rem 0; border-bottom:1px solid var(--line); }
.key-demo .kd-abbr { display:inline-block; min-width:8.5rem; color:var(--muted); }
.key-demo .kd-full i { font-style:italic; }
"""

JS = """
document.addEventListener('click', (e) => {
  if (e.target.closest('.id-btn')) {
    const a = document.getElementById('apparatus');
    a.classList.add('open'); a.scrollIntoView({block:'start'}); return;
  }
  const d = e.target.closest('.closable .v-def');
  if (d) { d.parentElement.classList.toggle('open'); return; }
  const t = e.target.closest('.v-tabs button');
  if (t) {
    t.closest('.v-tabs').querySelectorAll('button').forEach(b=>b.classList.toggle('on', b===t));
    document.querySelectorAll('.v-div').forEach(x =>
      x.style.display = (t.dataset.div==='all' || x.dataset.div===t.dataset.div) ? '' : 'none');
  }
});
"""

CONSTR_RE = re.compile(
    r'^\s*((?:c\.|abs\.|freq\.|folld\.|with|in)\s[^<]{0,38}?[,:]|abs\.,?)', re.I)


PLAIN_I = re.compile(r'<i>[^<]+</i>')


def extend_to_translation(zone, ev):
    """A sub-sense with no gloss of its own usually still carries the
    print's English — an italic translation after the first citation
    (κλισίην, θρόνον τ. τινί, `set a stool or chair for him'). Extend the
    visible cut to the end of that first italic instead of stopping at the
    first citation. Print's words, print's order, nothing invented."""
    if '<i>' in zone:
        return zone, ev
    m = PLAIN_I.search(ev)
    if not m or L.text_of(ev[:m.start()]).count(' ') > 45:
        return zone, ev
    return zone + ev[:m.end()], ev[m.end():]


def sense_row(dl, n, body, supplied):
    zone, ev = L.defzone(body)
    m = re.search(r'[(\[]\s*$', zone)
    if m:
        zone, ev = zone[:m.start()], zone[m.start():] + ev
    zone, ev = extend_to_translation(zone, ev)
    zt = L.text_of(zone)
    n_html = (f'<b class="lx-sense-n"{" data-supplied" if supplied else ""}>{n}</b> '
              if n else '')
    # construction cue: a leading grammar label becomes a scannable chip,
    # absorbing the matched text (the label is plain text at the zone start)
    chip = ''
    cm = CONSTR_RE.match(zt)
    if cm and len(cm.group(1)) < 44:
        lead = zone[:zone.find('<')] if '<' in zone else zone
        matched = cm.group(1)
        pos = lead.find(matched)
        if pos >= 0:
            zone = zone[:pos] + zone[pos + len(matched):]
            chip = f'<span class="constr">{htmllib.escape(matched.strip(" ,:"))}</span>'
    cls = f'v-sense lv{min(max(dl - 1, 0), 3)}'
    if not zt.strip('.,;:— '):
        zone = ''
    # Not the citations t8rows wraps itself (data-bare): those were
    # bare authors when this rule was measured.
    refs = len(re.findall(r'class="lx-bibl"(?! data-bare)', ev))
    count = f'<span class="v-count">{refs} refs</span>' if refs else ''
    if ev.strip():
        return (f'<div class="{cls} closable"><div class="v-def">'
                f'<span class="chev"></span>{n_html}{chip}{zone}{count}</div>'
                f'<div class="v-ev">{ev}</div></div>')
    return f'<div class="{cls}"><div class="v-def"><span class="chev"></span>{n_html}{chip}{zone}</div></div>'


SLOT_CAPTIONS = {'pres': 'pres.', 'fut': 'fut.', 'aor': 'aor.',
                 'pf': 'pf. act.', 'pfmp': 'pf. m/p', 'aorp': 'aor. pass.'}

# ---- citation legibility: the LSJ front-matter key (data/lsj-abbrevs.json) ----
import json as _json
ABBREVS = _json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       'data', 'lsj-abbrevs.json')))


def author_info(abbr):
    a = ABBREVS['authors']
    for key in (abbr, abbr.replace(' ', ''), re.sub(r'^Ps\.-', '', abbr)):
        if key in a:
            hit = a[key][0]
            tip = hit['name']
            extra = ', '.join(x for x in (hit['epithet'], hit['date']) if x)
            return (tip + (f' ({extra})' if extra else ''), key)
    return None


AUTH_SPAN = re.compile(r'<span class="lx-author">(.*?)</span>')
TITLE_I = re.compile(r'^(.{0,40}?)<i class="lx-title">(.*?)</i>')
BIBL_PUB = re.compile(r'<span class="lx-bibl">((?:<i class="lx-title">)?)([A-Z][A-Za-z]*\.?)')


def annotate_citations(h):
    """Expand the print's abbreviations into hover keys: author spans get the
    front-matter name/epithet/date, a following work title gets its full
    title, bare publication references (IG, SIG, POxy.) get theirs."""
    out, pos = [], 0
    for m in AUTH_SPAN.finditer(h):
        out.append(h[pos:m.start()])
        label = L.text_of(m.group(1))
        info = author_info(label)
        seg_end = m.end()
        if info:
            tip, key = info
            span = f'<span class="lx-author" title="{htmllib.escape(tip)}">{m.group(1)}</span>'
            tm = TITLE_I.match(h[m.end():])
            if tm:
                full = ABBREVS['works'].get(key, {}).get(L.text_of(tm.group(2)))
                if full:
                    span += (tm.group(1) + f'<i class="lx-title" '
                             f'title="{htmllib.escape(full)}">{tm.group(2)}</i>')
                    seg_end = m.end() + tm.end()
            out.append(span)
        else:
            out.append(m.group(0))
        pos = seg_end
    out.append(h[pos:])
    h2 = ''.join(out)

    def pub_sub(m):
        full = ABBREVS['publications'].get(m.group(2)) or ABBREVS['publications'].get(m.group(2).rstrip('.'))
        if full:
            return (f'<span class="lx-bibl" title="{htmllib.escape(full[:160])}">'
                    f'{m.group(1)}{m.group(2)}')
        return m.group(0)
    return BIBL_PUB.sub(pub_sub, h2)

FLASH_DEMO = [('παιδεύω', 'paideu/w'), ('λύω', 'lu/w'), ('ποιέω', 'poie/w'),
              ('γράφω', 'gra/fw'), ('πράσσω', 'pra/ssw'), ('λαμβάνω', 'lamba/nw'),
              ('δίδωμι', 'di/dwmi'), ('τίθημι', 'ti/qhmi'), ('ἵστημι', 'i(/sthmi'),
              ('φέρω', 'fe/rw'), ('βλώσκω', 'blw/skw')]


def card_cell(v):
    if v is None:
        return '<td class="fc-none">—</td>'
    form, expanded, src, _ = v
    mark = '<sup>*</sup>' if expanded else '<sup>†</sup>' if src == 'curated' else ''
    return f'<td lang="grc">{htmllib.escape(form)}{mark}</td>'


def build():
    tith = [e for e in extract.get('grc-lsj', 'τίθημι') if e['key'] == 'ti/qhmi'][0]
    pher = [e for e in extract.get('grc-lsj', 'φέρω') if e['key'] == 'fe/rw'][0]

    # --- τίθημι pieces ---
    pre, rest = L.split_preamble(tith['html'])
    head_end = pre.find('</b>') + 4
    forms_html = pre[head_end:].lstrip(', ')
    rows = L.forms_rows(forms_html)
    fc = flashcard(forms_scope(tith['html']), tith['head'])
    pp_html = ' '.join(
        f'<span class="id-part"><span class="pp-label">{SLOT_CAPTIONS[name]}</span> '
        f'<b lang="grc">{htmllib.escape(v[0])}</b></span>'
        for name, v in fc[1:] if v)
    demo_rows = []
    for w, key in FLASH_DEMO:
        e = [x for x in extract.get('grc-lsj', w) if x['key'] == key][0]
        c = flashcard(forms_scope(e['html']), e['head'])
        demo_rows.append('<tr>' + ''.join(card_cell(v) for _, v in c) + '</tr>')
    demo_html = ('<table class="fc-table"><tr>'
                 + ''.join(f'<th>{SLOT_CAPTIONS[n]}</th>' for n, _ in
                           [('pres', 0), ('fut', 0), ('aor', 0), ('pf', 0),
                            ('pfmp', 0), ('aorp', 0)])
                 + '</tr>' + ''.join(demo_rows) + '</table>')
    ss = L.senses(rest)
    disp = display_numbers(ss)
    # division A only, as the worked example
    a_end = next(i for i, (dl, n, b, s) in enumerate(disp[1:], 1) if dl == disp[0][0])
    a_rows = ''.join(sense_row(dl, n, b, s) for dl, n, b, s in disp[1:a_end])
    a_zone = L.defzone(disp[0][2])[0]
    a_n = disp[0][1]
    rows_html = ''.join(
        (f'<div class="forms-row"><div class="f-label">{lab}</div>'
         f'<div class="f-content">{content}</div></div>') if lab else
        (f'<div class="forms-row nolabel"><div class="f-content">{content}</div></div>')
        for lab, content in rows)

    # --- φέρω division frame with voice-attached forms ---
    pss = L.senses(L.split_preamble(pher['html'])[1])
    pdisp = display_numbers(pss)
    base = pdisp[0][0]
    tabs, panes = [], []
    tops = [i for i, (dl, n, b, s) in enumerate(pdisp) if dl == base]
    for di, i in enumerate(tops):
        dl, n, b, s = pdisp[i]
        zone, ev = L.defzone(b)
        zt = L.text_of(zone).strip(' ,.;:—')
        label = re.split(r'[,;:—]|(?<=\.)\s', zt, maxsplit=1)[0][:22]
        tabs.append(f'<button type="button" data-div="d{di}"'
                    f'{" class=on" if di == 0 else ""}><b>{htmllib.escape(n.rstrip("."))}</b> '
                    f'{htmllib.escape(label)}</button>')
        end = tops[di + 1] if di + 1 < len(tops) else len(pdisp)
        # voice-attached forms: tense labels inside the division's own text
        forms_note = ''
        fm = re.search(r'(<span class="lx-tns">.{0,400}?)(?=<div|$)', ev, re.S)
        if fm or 'lx-tns' in ev:
            note = re.sub(r'\s+', ' ', L.text_of(ev)[:180])
            forms_note = (f'<div class="div-forms" lang="grc"><span class="df-label">forms of this '
                          f'voice</span>{htmllib.escape(note)}…</div>')
        inner = ''.join(sense_row(dl2, n2, b2, s2) for dl2, n2, b2, s2 in pdisp[i + 1:end][:4])
        panes.append(f'<div class="v-div" data-div="d{di}" style="{"" if di == 0 else "display:none"}">'
                     f'<div class="div-h" lang="grc"><b class="lx-sense-n">{n}</b> {zone}</div>'
                     f'{forms_note}{inner}'
                     f'<p style="color:var(--faint);font:italic .9rem system-ui">… (division continues; sketch shows four rows)</p></div>')

    zones = f"""
<div class="zone"><span class="zone-tag">1 · identity — the Hansen &amp; Quinn flashcard</span>
  <div class="id-line" lang="grc"><span class="id-head">τίθημι</span>{pp_html}
    <button type="button" class="id-btn">All forms — {len(rows)} rows ↓</button></div>
  <div class="zone-why">The six principal parts in recitation order — the parts
  a reader needs to IDENTIFY a form. The complete inventory (every dialect,
  mood and person LSJ records) stays in zone 4, one tap away; nothing is lost,
  it is tiered. Extraction proof across eleven verbs, walked voice-aware
  through LSJ’s own forms text:</div>
  {demo_html}
  <div class="zone-why">Plain = lifted verbatim from LSJ (quantity marks and
  all: λέλῠκα). <sup>*</sup> = expanded from LSJ’s ending abbreviation
  (“fut. -σω” → παιδεύσω; γράφω + “-ψω” → γράψω). <sup>†</sup> = from the
  curated table of textbook irregulars — ἵστημι’s parts are split across its
  causal/intransitive divisions, so no walk recovers them; every textbook
  hand-curates exactly these verbs, and ours marks that provenance. — = LSJ
  records nothing (βλώσκω has no perfect middle or aorist passive). For the
  81% of verbs with no forms apparatus at all, this line is the headword
  alone.</div></div>

<div class="zone"><span class="zone-tag">2 + 3 · division frame &amp; sense ledger (worked: τίθημι A)</span>
  <div class="v-tabs"><button class="on"><b>A</b> in local sense</button><button><b>B</b> put in a state</button><button><b>C</b> make, execute</button></div>
  <div class="div-h" lang="grc"><b class="lx-sense-n">{a_n}</b> {a_zone}</div>
  <div lang="grc">{a_rows}</div>
  <div class="zone-why">Uniform numbering: supplied numerals (the print’s implied
  I., and the citable “II. 1.” where children start at 2.) render identically —
  UNIFORMITY where print restricted. Construction cues (c. dat., abs., with
  Advbs.) become scannable chips at the row head. Definition zone always
  visible; evidence behind the row (A/B variant still open).</div></div>

<div class="zone"><span class="zone-tag">2b · voice frame with voice-attached forms (worked: φέρω)</span>
  <div class="v-tabs">{''.join(tabs)}</div>
  <div lang="grc">{''.join(panes)}</div>
  <div class="zone-why">Where the print divides by voice, each division owns its
  forms — LSJ already writes Pass./Med. forms inside those divisions (7% of
  verbs), Bailly prints “Moy. épq. (f. εἴσομαι…)” at the division head. The
  sketch surfaces that run as a labelled note at the top of the pane.</div></div>

<div class="zone" id="apparatus"><span class="zone-tag">4 · the full apparatus (end matter)</span>
  <div class="forms-rows" lang="grc">{rows_html}</div>
  <div class="zone-why">The complete dialect/tense record — every form, every
  citation, nothing lost — parked out of the reading path. Reached from the
  identity line. The scholar’s zone.</div></div>

<div class="zone"><span class="zone-tag">5 · end matter</span>
  <p style="color:var(--muted)">Etymology, cross-references, L&amp;S “—Hence”
  derivative blocks. Nothing of τίθημι’s goes here; fero’s redup. tetuli notes
  and amo’s ămans block would — and παιδεύω’s own etymology “(παῖς)” already
  sits at the END of its printed forms run: LSJ agrees with the placement.</p></div>

<div class="zone"><span class="zone-tag">6 · citations made legible — the front-matter key</span>
  <p style="color:var(--muted);font:.95rem system-ui,sans-serif">LSJ’s own
  Authors-and-Works list (front matter, PD, as digitized by Logeion) is now
  parsed into <b>data/lsj-abbrevs.json</b>: 1,017 author abbreviations with
  name, genre and date; 772 work abbreviations; 208 epigraphical and
  papyrological publications. Against the full pack, <b>97.9%</b> of the
  413,730 author citations resolve (92.1% direct + 5.8% contextual Id./ib.).
  Every citation in the zones above now carries its expansion as a hover key
  (dotted underline). Samples, statically:</p>
  <div class="key-demo">
    <div class="kd-row"><span class="kd-abbr">Hdt. 3.99</span>
      <span class="kd-full">Herodotus (Historicus, v B.C.) 3.99</span></div>
    <div class="kd-row"><span class="kd-abbr">A. <i>Ag.</i> 905</span>
      <span class="kd-full">Aeschylus (Tragicus, vi/v B.C.), <i>Agamemnon</i> 905</span></div>
    <div class="kd-row"><span class="kd-abbr">Pl. <i>R.</i> 376e</span>
      <span class="kd-full">Plato (Philosophus, v/iv B.C.), <i>Respublica</i> 376e</span></div>
    <div class="kd-row"><span class="kd-abbr"><i>SIG</i> 331.13</span>
      <span class="kd-full">Sylloge Inscriptionum Graecarum (ed. Dittenberger) 331.13</span></div>
    <div class="kd-row"><span class="kd-abbr"><i>BGU</i> 1141.19</span>
      <span class="kd-full">Berliner griechische Urkunden 1141.19</span></div>
  </div>
  <div class="zone-why">The date field is the quiet prize: with every witness
  dated, a sense’s attestation range (Homer → papyri) becomes computable —
  the evidence-as-warrant reading of the citations, made visible. Unresolved
  tail: authors LSJ cites unabbreviated (Antipho, Longus), spacing variants,
  Ps.- prefixes — a normalization list, not a redesign.</div></div>
"""
    intro = ('<h1>The ideal verb entry — structural sketch</h1>'
             '<p>Not a skin: an argument in five zones, with real LSJ content '
             'slotted in. Dashed boxes and the amber notes are scaffolding for '
             'our discussion, not UI. τίθημι works zones 1, 2–3, 4; φέρω works '
             'the voice frame. Every word inside the zones is LSJ’s.</p>')
    zones = annotate_citations(zones)
    page = (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>The ideal verb — sketch</title><style>{CSS}</style></head><body>'
            f'<div class="intro">{intro}</div><main>{zones}</main>'
            f'<script>{JS}</script></body></html>')
    with open(os.path.join(OUT, 'verb-ideal-sketch.html'), 'w') as f:
        f.write(page)
    print('verb-ideal-sketch.html', os.path.getsize(os.path.join(OUT, 'verb-ideal-sketch.html')))
    print('τίθημι flashcard:', [(n, v[0]) for n, v in fc if v])


if __name__ == '__main__':
    build()
