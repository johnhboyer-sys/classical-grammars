#!/usr/bin/env python3
"""Discriminating cases for the T8 transform's text rules (stdlib only).

Each case here was a shipped defect or a regression caught by the pack
diff during the polish round, and each pins the rule that settled it.
Run: python3 scripts/wordtool/test_t8rows.py
"""

from __future__ import annotations

import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import entrylib as L  # noqa: E402
import extract  # noqa: E402
import t8rows as T  # noqa: E402

CIT = ('<span class="lx-cit"><span class="lx-quote" lang="grc">-ιη</span> '
       '<span class="lx-bibl"><span class="lx-author">Hdt.</span> 1.92</span>'
       '</span>')


class Tidy(unittest.TestCase):
    """A gloss ends on its last word; an abbreviation keeps its period."""

    def check(self, src, want):
        self.assertEqual(T._tidy(src), want)

    def test_capitalised_abbreviation_keeps_its_period(self):
        self.check('usually with Art., , ', 'usually with Art.')

    def test_sentence_period_goes(self):
        self.check('give up. ', 'give up')
        self.check('scourge in Hippon. ', 'scourge in Hippon.')

    def test_grammar_abbreviation_keeps_its_period(self):
        self.check('c. gen. ', 'c. gen.')
        self.check('—Pass. impers., ', '—Pass. impers.')

    def test_latin_gender_letter_keeps_its_period(self):
        # Without it the Latin part-letter rule reads ", f" as debris.
        # In Greek the same shape is a citation's part letter.
        T.configure('lat-ls', 'lat-analyses', 'la')
        try:
            self.check('ae, f., ', 'ae, f.')
        finally:
            T.configure('grc-lsj', 'grc-analyses', 'grc')
        self.check('oblectamentum, b., ', 'oblectamentum, b')

    def test_uncovered_separator_goes_too(self):
        self.check('council of Pontus, al., . ', 'council of Pontus, al')
        self.assertEqual(T._strip_links(T._tidy('council of Pontus, al., . ')),
                         'council of Pontus')

    def test_author_initial_and_links_go_bare_for_dangling_link(self):
        self.check('unmoved, S. ', 'unmoved, S')
        self.check('= βρύσσος, Id. ', '= βρύσσος, Id')
        self.assertEqual(T._strip_links(T._tidy('unmoved, S. ')), 'unmoved')

    def test_short_greek_abbreviation_in_a_quotation(self):
        self.check('<span lang="grc">τί ν.</span>; ',
                   '<span lang="grc">τί ν.</span>')


class ExampleGloss(unittest.TestCase):
    """An example's translation, with the citation strip's leavings off."""

    def check(self, src, want):
        self.assertEqual(T._example_gloss(src), want)

    def test_reference_stub_behind_is_trimmed(self):
        self.check('the law-court there, Decr. ap', 'the law-court there')
        self.check('cj. in', '')
        self.check('Epigr. in', '')

    def test_phrasal_verb_is_not_a_stub(self):
        self.check('draws in, takes in', 'draws in, takes in')

    def test_governor_alone_is_not_a_translation(self):
        self.check('by', '')
        self.check('of the', '')
        self.check('cj. for', '')

    def test_gloss_ending_on_its_preposition_survives(self):
        self.check('to gape at', 'to gape at')
        self.check('want of', 'want of')

    def test_one_word_translation_survives(self):
        self.check('then', 'then')
        self.check('as soon as', 'as soon as')

    def test_stray_bracket_keeps_the_side_with_the_words(self):
        self.check('sc. ), τά, food for sick persons',
                   'τά, food for sick persons')
        self.check('adorned, embroidered with flowers, ibid.): metaph., :—Med., gather, cull flowers',
                   'adorned, embroidered with flowers')
        self.check('best written divisim, as by Alex. critics), darkened on either side, of strong emotions, as anger',
                   'darkened on either side, of strong emotions, as anger')
        self.check('quietly as it were), with a smile on his face',
                   'quietly as it were, with a smile on his face')

    def test_review_round_cases(self):
        # Grok's findings on the first three commits of this round.
        self.check('lets Zeus in', 'lets Zeus in')
        self.assertEqual(T._strip_links(T._tidy('rare, pf., ')), 'rare, pf.')
        out = T.mark_prose_authors(A % 'Hdt.' + ' (?) explains the form')
        self.assertIn('lx-prose', out)
        out = T.mark_prose_authors('Freq. ap. ' + A % 'Cic.' + ' 1.2, of men')
        self.assertTrue(out.startswith('Freq. <span class="lx-bibl"'))
        self.assertEqual(T.unique_authors(T.mark_prose_authors(
            'of men, ' + A % 'A.' + ' or ' + A % 'Ar.' + ' ap. ' + A % 'Phot.' + ' s.v. ψό, x')),
            ['A.', 'Ar.', 'Phot.'])
        self.check('for the names of those who offered vestments were '
                   'embroidered upon them), al., etc.; l.c',
                   'for the names of those who offered vestments were '
                   'embroidered upon them')


class CitationStrip(unittest.TestCase):
    def test_nested_citation_is_stripped_whole(self):
        self.assertEqual(T._strip_citations(CIT + ', x'), ', x')

    def test_preamble_citation_keeps_its_quoted_form(self):
        self.assertEqual(T._keep_quoted_forms('Ion. ' + CIT),
                         'Ion. <span class="lx-quote" lang="grc">-ιη</span>')

    def test_italic_inside_a_late_closing_parenthesised_citation_stays(self):
        # πολύστιος: "(στία) with many small stones, pebbly, Call. Jov. 26"
        src = ('(<span class="lx-cit"><span class="lx-quote" lang="grc">στία'
               '</span>) <i>with many small stones, pebbly,</i> '
               '<span class="lx-bibl"><span class="lx-author">Call.</span>'
               '</span></span>')
        self.assertIn('<i>with many small stones, pebbly,</i>',
                      T._strip_citations(src))

    def test_translation_inside_an_example_in_parentheses_goes(self):
        # L&S aditio: the bracket closes inside the quotation.
        src = ('(i. e. aditio ad hanc; <span class="lx-cit"><span class='
               '"lx-quote">v. Zumpt, § 681),</span> <i>why do you approach '
               'her?</i> <span class="lx-bibl"><span class="lx-author">Plaut.'
               '</span></span></span>')
        self.assertNotIn('why do you', T._strip_citations(src))

    def test_title_locus_is_stripped_whole(self):
        self.assertEqual(T.STRIP_WORK.sub('', '<i class="lx-title">IG</i> 12(8).526, x'), ', x')
        self.assertEqual(T.STRIP_WORK.sub('', '<i class="lx-title">IG</i> ΙΙ(2).199 x'), ' x')


class SourceText(unittest.TestCase):
    def test_bracket_outside_the_element_moves_inside(self):
        src = ('&lt; <span class="lx-cit"><span class="lx-quote" lang="grc">'
               'ἐν&gt; ῥεύμασι</span></span>')
        self.assertIn('⟨ἐν⟩ ῥεύμασι', T._source_editorial_angles(src))
        src = '(&lt;<span class="lx-foreign" lang="grc">τῷ</span>&gt; add. Kaibel)'
        self.assertIn('⟨τῷ⟩</span>', T._source_editorial_angles(src))

    def test_stray_bracket_goes_and_a_derivation_arrow_stays(self):
        self.assertEqual(T._source_editorial_angles('Dim. of &gt;ἔδαφος 4'),
                         'Dim. of ἔδαφος 4')
        self.assertEqual(T._source_editorial_angles('(m&gt;n)'), '(m&gt;n)')

    def test_homonym_letter_leaves_the_identity_line(self):
        self.assertEqual(
            T._drop_print_homonym(' (B)<span class="lx-foreign" lang="grc">· τάφος</span>'),
            '<span class="lx-foreign" lang="grc">τάφος</span>')


A = '<span class="lx-author">%s</span>'


class BareCitations(unittest.TestCase):
    """A bare author that cites is wrapped with its tail; one that is
    prose is marked; the sentence that governs one keeps the name."""

    def wrap(self, src):
        return T.mark_prose_authors(src)

    def test_author_and_sv_chain_become_one_citation(self):
        out = self.wrap('<i>slabs,</i> ' + A % 'Suid.' + ' s.v. ἄβαξι.')
        self.assertIn('<span class="lx-bibl" data-bare="1">' + A % 'Suid.'
                      + ' s.v. ἄβαξι</span>.', out)
        self.assertEqual(T._strip_citations(out), '<i>slabs,</i> .')

    def test_or_pair_with_apud_is_one_citation(self):
        # γράσος: "A. or Ar. ap. Phot. s.v. ψό"
        src = ('of men, ' + A % 'A.' + ' or ' + A % 'Ar.' + ' ap. '
               + A % 'Phot.' + ' s.v. ψό, x')
        out = self.wrap(src)
        self.assertEqual(out.count('data-bare'), 1)
        self.assertEqual(T._strip_citations(out), 'of men, , x')

    def test_pair_behind_a_governor_is_prose_on_both_halves(self):
        # ἀνίαχος: "f.l. for αὐΐαχος in Hom. and Q.S."
        out = self.wrap('f.l. for x in ' + A % 'Hom.' + ' and ' + A % 'Q.S.')
        self.assertEqual(out.count('lx-prose'), 2)
        self.assertNotIn('data-bare', out)

    def test_governed_bare_citation_keeps_its_name(self):
        # ἄβδης: "scourge in Hippon. 1"
        out = self.wrap('<i>scourge</i> in ' + A % 'Hippon.' + ' 1.')
        self.assertTrue(out.startswith('<i>scourge</i> in Hippon. <span class="lx-bibl" data-bare="1">'))
        self.assertEqual(T._strip_citations(out).strip(), '<i>scourge</i> in Hippon. .')

    def test_plain_text_lead_joins_the_citation(self):
        # ἀγκτηριάζω: "Crito ap. Gal. 13.878"
        out = self.wrap('<i>bind,</i> Crito ap. ' + A % 'Gal.' + ' 13.878.')
        # Crito is named, so Crito chips, as Perseus's own "<author>Archig.
        # </author> ap. <author>Gal.</author>" does.
        self.assertIn('<span class="lx-bibl" data-bare="1"><span class="lx-author">Crito</span> ap. ', out)
        self.assertEqual(T.unique_authors(out), ['Crito', 'Gal.'])
        self.assertEqual(T._strip_citations(out), '<i>bind,</i> .')

    def test_lead_before_a_marked_citation(self):
        # βωλά: "Decr.Byz. ap. D. 18.90"
        src = ('x, Decr.Byz. ap. <span class="lx-bibl">' + A % 'D.'
               + ' 18.90</span>.')
        out = self.wrap(src)
        # Not data-bare: the citation inside was a zone boundary already.
        self.assertIn('<span class="lx-bibl"><span class="lx-author">Decr.Byz.</span> ap. <span class="lx-bibl">', out)
        self.assertEqual(T.unique_authors(out), ['Decr.Byz.', 'D.'])

    def test_a_named_lead_chips_and_a_source_label_does_not(self):
        # αἰθρήεις: "Pherenic. ap. Sch. Pi. O. 3.28" shipped "Pi." alone.
        src = ('= αἴθριος, Pherenic. ap. ' + A % 'Sch.' + ' <span class="lx-bibl">'
               + '<i class="lx-title">Pi.</i> <i class="lx-title">O.</i> 3.28</span>')
        # The inner citation names no author, so its title chips, as before.
        self.assertEqual(T.unique_authors(self.wrap(src)), ['Pherenic.', 'Sch.', 'Pi.'])
        # ἀκρόδρυα: the chain ends on the plain "eund.", which is a link.
        src = 'generally, Glaucides ap.eund. <span class="lx-bibl">3.81a</span>'
        self.assertEqual(T.unique_authors(self.wrap(src)), ['Glaucides'])
        # ἀδάμας: an oracle quoted in Herodotus names no author; στάσιμος's
        # "Lex Solonis" names a law.
        src = 'x, Orac. ap. <span class="lx-bibl">' + A % 'Hdt.' + ' 7.141</span>'
        out = self.wrap(src)
        self.assertEqual(T.unique_authors(out), ['Hdt.'])
        self.assertIn('<span class="lx-bibl">Orac. ap. <span class="lx-bibl">', out)
        src = 'x, Lex Solonis ap. <span class="lx-bibl">' + A % 'Lys.' + ' 10.18</span>'
        self.assertEqual(T.unique_authors(self.wrap(src)), ['Lex Solonis', 'Lys.'])

    def test_marking_the_lead_never_changes_the_text(self):
        import entrylib as L
        # ἐπηγκενίδες: Rhian.'s tail ends on "ap." and the title behind
        # the plain "Sch." gets a wrapper of its own; marking the lead by
        # replacement across that close emitted "Sch." twice.
        src = 'was read by ' + A % 'Rhian.' + ' ap. Sch.<i class="lx-title">Od.</i> l.c.)'
        out = self.wrap(src)
        # "read by" governs the citation, so the name stays in the
        # sentence in front of the wrapper; nothing else is repeated.
        self.assertEqual(out.count('Sch.'), 1)
        self.assertEqual(out.count('Od.'), 1)
        self.assertEqual(' '.join(L.text_of(T._strip_citations(out)).split()), 'was read by Rhian. )')

    def test_zone_runs_past_a_wrapper(self):
        import entrylib as L
        body = ('<i>suture</i> of a wound, ' + A % 'Hp.' + ' ap. ' + A % 'Erot.'
                + '; of the skull-bones, <span class="lx-bibl">' + A % 'Gal.'
                + ' 19.86</span>.')
        zone, _ev = L.defzone(self.wrap(body))
        self.assertIn('of the skull-bones', zone)


class ShortEntryTail(unittest.TestCase):
    """A short entry's prose past its first citation joins the row."""

    def test_continuation_joins_the_row(self):
        # μόρφνος, reduced
        html = ('<i>epith. of an eagle,</i> <span class="lx-bibl"><span class="lx-author">Il.'
                '</span> 24.316</span>; described as a vulture by ' + A % 'Suid.' + '.')
        row = T.make_row('μόρφνος', 'μόρφνος', T.mark_prose_authors(html), 'sense')
        import entrylib as L
        self.assertEqual(L.text_of(row['zone']),
                         'epith. of an eagle; described as a vulture by Suid.')

    def test_apparatus_alone_is_not_a_continuation(self):
        html = ('<i>greedy,</i> <span class="lx-bibl"><span class="lx-author">Hdn.Gr.'
                '</span> 1.2</span>, al.')
        row = T.make_row('x', 'x', html, 'sense')
        import entrylib as L
        self.assertEqual(L.text_of(row['zone']), 'greedy')


BIB = '<span class="lx-bibl">%s</span>'


def latin(fn):
    """Run a case against the Lewis & Short packs, and put LSJ back."""
    def wrapped(self):
        T.configure('lat-ls', 'lat-analyses', 'la')
        try:
            fn(self)
        finally:
            T.configure('grc-lsj', 'grc-analyses', 'grc')
    return wrapped


def q(html):
    """_quotation_lead on a fixture, split at its first marked reference
    as the zone cut splits a sense."""
    m = re.search(r'<span class="lx-bibl"', html)
    return T._quotation_lead(html[:m.start()], html[m.start():]) if m else T._quotation_lead(html, '')


class LatinQuotationLead(unittest.TestCase):
    """Lewis & Short quotes in plain text; only grammar tells a quotation
    from an idiom definition written in the same shape."""

    # Shape A: a whole clause. fortis, via Ennius.
    FORTIS = (': sicut fortis equus, spatio qui saepe supremo Vicit Olympia, '
              'nunc senio confectus quiescit, <i>a powerful horse</i>, '
              + A % 'Enn.' + ' ap. ' + BIB % (A % 'Cic.' + ' de Sen. 5, 14'))
    # Shape B: a bare case-form.
    AGRORUM = ': agrorum, <i>in the country</i>, ' + BIB % (A % 'Cod. Th.' + ' 16, 4, 10')

    @latin
    def test_quotation_shapes(self):
        self.assertTrue(q(self.FORTIS).startswith('sicut fortis equus'))
        self.assertEqual(q(self.AGRORUM), 'agrorum')
        self.assertEqual(q(' carmina, <i>artless, rude songs</i>, ' + BIB % 'Liv. 4'),
                         'carmina')
        self.assertEqual(q(' fabellas, i. e. <i>fitting, suitable</i>, ' + BIB % 'Hor.'),
                         'fabellas')
        # "an" is the Latin particle, not the English article.
        self.assertEqual(q(' Lucanus an Apulus, anceps, <i>doubtful whether</i>, ' + BIB % 'Hor.'),
                         'Lucanus an Apulus, anceps')

    @latin
    def test_definitions_keep_their_cut(self):
        for zone in ('; of things, <i>splendid</i>, ' + BIB % 'Cic. 1',
                     '—Esp., <i>x y</i>, ' + BIB % 'Cic. 1',
                     'Hence, adv.: <i>x y</i>, ' + BIB % 'Cic. 1',
                     # manus: an idiom formula carries an infinitive, and its
                     # definition reads "to …".
                     ' manum ferulae subducere, <i>to take the hand from the rod</i>, '
                     + BIB % 'Juv. 1, 15',
                     # A sub-lemma states a form, not a quotation.
                     ' <b class="lx-orth">Attĭci</b>, <span class="lx-itype">ōrum</span>, '
                     '<span class="lx-gen">m.</span>, <i>the Athenians</i>, ' + BIB % 'Cic. 1',
                     # dico: the print italicised the quotation itself.
                     ': Catonis est dictum. <i>Pedibus compensari pecuniam</i>, ' + BIB % 'Cic.'):
            self.assertEqual(q(zone), '', zone)
        # The print's "idiom: quotation" shape.
        self.assertEqual(T._quotation_lead(
            ' in manibus esse, <i>to be in hands</i>: ',
            '<span class="lx-cit"><span class="lx-quote">x</span></span>'), '')
        # A reference the print left in plain text carries no example, so
        # the row stays (Arabia "in Arabic, Sol. c. 33.").
        self.assertEqual(T._quotation_lead(' Arabice sacri vocantur, <i>in Arabic</i>, Sol. c. 33.', ''), '')
        # An italic that is a grammar label or a conjunction is no translation.
        self.assertEqual(q(' tonitru, <i>neutr.</i>, rests solely ' + BIB % 'Charis. p. 18'), '')
        self.assertEqual(q(' exempla = edere <i>or</i> statuere, ' + BIB % 'Plaut. 1'), '')

    @latin
    def test_infinitive_in_a_quotation_is_the_authors(self):
        # metallum, via Pliny: the translation is not a verb phrase.
        self.assertEqual(q(
            ' herba tantae suavitatis, ut metallum esse coeperit, <i>a mine</i>, ' + BIB % 'Plin.'),
            'herba tantae suavitatis, ut metallum esse coeperit')

    @latin
    def test_a_latin_word_in_the_prints_own_sentence(self):
        # Memmius: "<i>adjudged guilty of</i> ambitus, <i>went into exile</i>"
        ev = ('<i>a public man, adjudged guilty of</i> ambitus, <i>went into exile</i>, '
              + BIB % (A % 'Cic.' + ' 1'))
        self.assertEqual(T.examples_of('', ev), [])

    def test_greek_is_untouched(self):
        self.assertEqual(q(self.AGRORUM), '')
        self.assertEqual(T.examples_of('', self.AGRORUM), [])


class LatinUntaggedExample(unittest.TestCase):
    @latin
    def test_quotation_translation_and_reference(self):
        ex = T.examples_of('', T.mark_prose_authors(LatinQuotationLead.AGRORUM))
        self.assertEqual(ex, [{'eng': 'in the country', 'gr': 'agrorum', 'cit': 'Cod. Th. 16, 4, 10'}])
        ex = T.examples_of('', T.mark_prose_authors(LatinQuotationLead.FORTIS))
        self.assertEqual((ex[0]['eng'], ex[0]['cit']), ('a powerful horse', 'Enn. ap. Cic. de Sen. 5, 14'))

    @latin
    def test_translation_runs_to_the_reference(self):
        # iniuria: "<i>an action for a personal injury</i> or <i>affront</i>, Cic."
        ev = (': actio injuriarum, <i>an action for a personal injury</i> or <i>affront</i>, '
              + BIB % (A % 'Cic.' + ' Caecin. 12, 35'))
        self.assertEqual(T.examples_of('', ev)[0]['eng'], 'an action for a personal injury or affront')
        # iners: the aside the reference sits inside is cut at its bracket.
        ev = ': versus, <i>artless</i> (= sine arte facti, ' + BIB % (A % 'Hor.' + ' A. P. 445') + ')'
        self.assertEqual(T.examples_of('', ev)[0]['eng'], 'artless')

    @latin
    def test_translation_is_the_italics_and_their_connectives(self):
        # Grok's read of thirty: what the print writes between the
        # translation and its reference is not the translation.
        for src, want in (
                (': legatus, i. e. <i>the fetial priest</i>, fetialis, ', 'the fetial priest'),
                (': internecini judicium, <i>of one who has committed perjury</i>, acc. to ',
                 'of one who has committed perjury'),
                # The print's English note after the translation stays.
                (': ingens lustrum, <i>the grand lustrum, a hundred years</i>, at the end of which '
                 'the ludi saeculares were celebrated, ',
                 'the grand lustrum, a hundred years, at the end of which the ludi saeculares were celebrated'),
                (': Noctis, i. e. <i>the evening-star</i>, id. poët. ', 'the evening-star'),
                (': medulla, i.e. <i>with mortar and pestle</i> = pilā ligneā, which he had used just before, ',
                 'with mortar and pestle, which he had used just before'),
                (': paludes, <i>the extensive marshy district</i>, still called <i>the Pomptine</i> '
                 '(<i>Pontine</i>) <i>Marshes</i>, ',
                 'the extensive marshy district, still called the Pomptine (Pontine) Marshes'),
                (': virgo, i. e. <i>Arne</i> or <i>Canace</i>, ', 'Arne or Canace'),
                (': bos, <i>Pasiphaë</i>, ', 'Pasiphaë'),
                # A lone proper noun is a translation here, not an author.
                (': Deus, i. e. <i>Vulcan</i>, who is said to have had his forge in Mt. Aetna, ',
                 'Vulcan')):
            ex = T.examples_of('', src + BIB % (A % 'Ov.' + ' M. 6, 116'))
            self.assertEqual(ex[0]['eng'], want, src)
        # A translation the print sets inside the quotation's own bracket
        # is a shape this pass does not read.
        self.assertEqual(T.examples_of(
            '', ': commoditas et aequitas (<i>proportion, symmetry</i>) membrorum, '
            + BIB % (A % 'Suet.' + ' Aug. 79')), [])
        # satelles: "id. poët. ap. Non." is one citation.
        out = T.mark_prose_authors(': Noctis, i. e. <i>the evening-star</i>, ' + A % 'id.'
                                   + ' poët. ap. ' + BIB % (A % 'Non.' + ' 65, 10'))
        self.assertIn('data-bare="1"><span class="lx-author">id.</span> poët. ap. ', out)
        self.assertEqual(T.examples_of('', out)[0]['eng'], 'the evening-star')

    @latin
    def test_marked_quotations_keep_their_places(self):
        """The untagged pass runs last: it fills what the print's own
        marked quotations leave, and never displaces one. Written
        against the cap rather than a number, so raising the cap does
        not quietly change what this proves."""
        cit = ('<span class="lx-cit"><span class="lx-quote">%s</span> '
               + BIB % (A % 'Cic.' + ' 1') + '</span>')
        marked = ['q%d' % i for i in range(T.EXAMPLE_CAP)]
        untagged = ': agrorum, <i>in the country</i>, ' + BIB % 'Cod. Th. 1'
        # A full drawer: the untagged quotation has nowhere to go.
        ev = cit % marked[0] + untagged + ''.join('; ' + cit % q for q in marked[1:])
        self.assertEqual([e['gr'] for e in T.examples_of('', ev)], marked)
        # One place left: it takes it, and takes it last.
        ev = cit % marked[0] + untagged + ''.join('; ' + cit % q for q in marked[1:-1])
        self.assertEqual([e['gr'] for e in T.examples_of('', ev)],
                         marked[:-1] + ['agrorum'])

    @latin
    def test_a_converted_row_keeps_the_note_the_drawer_has_not(self):
        """abdo, acer, adoptivus: the print writes a note after the
        quotation. The drawer takes the quotation; the note is not in
        it, so the row stays."""
        conts = [('x', 'y')]
        ex = [{'gr': 'lumen de suo lumine', 'eng': 'to kindle', 'cit': 'Cic. 1'}]
        real = T._quotation_lead
        try:
            T._quotation_lead = lambda z, e: 'lumen de suo lumine'
            got = T.continuation_gloss
            # Says only what the drawer says: the row goes.
            T.continuation_gloss = lambda z, e='': ('to kindle', '')
            self.assertEqual(T._without_quotations(conts, ex), [])
            # Says a note besides: the row stays.
            T.continuation_gloss = lambda z, e='': ('to kindle.—Comp. abditior', '')
            self.assertEqual(T._without_quotations(conts, ex), conts)
        finally:
            T._quotation_lead = real
            T.continuation_gloss = got

    @latin
    def test_short_entry_keeps_its_tail(self):
        html = ('<i>a gloss</i>, ' + BIB % (A % 'Plaut.' + ' 1') + ': tropa, <i>a game of dice</i>, '
                + BIB % (A % 'Cic.' + ' 1') + '; described by the ancients as a game.')
        row = T.make_row('x', 'x', T.mark_prose_authors(html), 'sense')
        import entrylib as L
        self.assertIn('described by the ancients', L.text_of(row['zone']))
        self.assertEqual(row['examples'][0]['gr'], 'tropa')


class LatinCitations(unittest.TestCase):
    """Lewis & Short's "ap" without its period, "Att.ap." without its
    space, "Paul. ex Fest.", the editor after the page, and the citation
    the digitisation left in plain text."""

    def strip(self, html):
        import entrylib as L
        # The emitter collapses the doubled space a removed citation leaves.
        return ' '.join(L.text_of(T._strip_citations(T.mark_prose_authors(html))).split())

    @latin
    def test_ap_without_period_and_without_space(self):
        self.assertEqual(self.strip('omnia mala in aliquem, ' + A % 'Enn.' + ' ap '
                                    + BIB % (A % 'Non.' + ' p. 90, 15')), 'omnia mala in aliquem,')
        self.assertEqual(self.strip('queas, Att.ap.' + BIB % (A % 'Macr.' + ' 6, 1')), 'queas,')

    @latin
    def test_lead_in_an_entry_with_no_author_span(self):
        # chimerinus: no lx-author anywhere, so the lead loop never ran.
        out = T.mark_prose_authors('tropa, Kalend. ap. ' + BIB % '<i class="lx-title">Inscr. Orell.</i> II. p. 381')
        # A calendar is a kind of source, not an author: no span, no chip.
        self.assertTrue(out.startswith('tropa, <span class="lx-bibl">Kalend. ap. '))

    @latin
    def test_paulus_ex_festo_with_its_editor(self):
        out = T.mark_prose_authors('abscedentes, Paul. ex ' + BIB % (A % 'Fest.' + ' p. 22') + ' Müll.')
        self.assertEqual(out, 'abscedentes, <span class="lx-bibl">Paul. ex <span class="lx-bibl">'
                              '<span class="lx-author">Fest.</span> p. 22 Müll.</span></span>')
        self.assertEqual(T.unique_authors(out), ['Fest.'])
        # caeles: the editor after a marked citation inside a bare author's.
        out = T.mark_prose_authors('di caelites. ' + A % 'Enn.' + ' ap. '
                                   + BIB % (A % 'Varr.' + ' <i class="lx-title">L. L.</i> 7, § 6') + ' Müll.')
        self.assertTrue(out.endswith('Müll.</span></span>'))

    @latin
    def test_plain_text_festus_is_a_citation(self):
        out = T.mark_prose_authors('prohibet, Paul. ex Fest. p. 9 Müll. So too')
        self.assertIn('<span class="lx-bibl" data-bare="1">Paul. ex <span class="lx-author">Fest.</span>'
                      ' p. 9 Müll.</span>', out)
        self.assertEqual(T.unique_authors(out), ['Fest.'])
        self.assertEqual(self.strip('x, (Trag. Rel. p. 201 Rib.), y'), 'x, (), y')
        # saevus: the plain "Naev. ap." in front joins, and Naevius chips.
        out = T.mark_prose_authors('mare, Naev. ap. Fest. s. v. topper, p. 352 Müll.; x')
        self.assertEqual(T.unique_authors(out), ['Naev.', 'Fest.'])
        self.assertEqual(self.strip('mare, Naev. ap. Fest. s. v. topper, p. 352 Müll.; x'), 'mare, ; x')
        # A marked Festus keeps its own span; only the editor moves in.
        self.assertEqual(T.mark_prose_authors('Fest. s. v. abacus, p. 10 Müll.').count('lx-bibl'), 1)

    @latin
    def test_the_lead_is_the_one_ending_at_the_citation(self):
        # cohors: two leads in the window; the first ended elsewhere and
        # "Glaucia ap" stayed in the gloss.
        src = ('Cors, Varr. ap. Non. l. l.; Glaucia ap. '
               + BIB % (A % 'Cic.' + ' <i class="lx-title">de Or.</i> 2, 65') + ' fin.')
        self.assertEqual(self.strip(src), 'Cors, Varr. ap. Non. l. l.; fin.')
        # copior: the same behind "and".
        src = 'ingenti copiantur, Quadrig. ap. Gell. l. l., and Cael. ap. ' + BIB % (A % 'Non.' + ' p. 87, 8')
        self.assertNotIn('Cael', self.strip(src))
        # quamuis: a two-word name, before a citation this pass built.
        src = 'Without a <i>verb</i>, Carm. Marci ap. Fest. s. v. negumate, p. 165 Müll.: x'
        self.assertEqual(self.strip(src), 'Without a verb, : x')

    @latin
    def test_the_lead_chain_runs_into_paulus(self):
        # abitio: "Gloss. ap. Paul. ex Fest." is one chain of links.
        src = ('= mors, <i>death</i>, acc. to Gloss. ap. Paul. ex '
               + BIB % (A % 'Fest.' + ' p. 380, 9') + ' Müll.')
        out = T.mark_prose_authors(src)
        # "acc. to" governs the chain, so its first name stays in the
        # sentence in front of the wrapper.
        self.assertIn('acc. to Gloss. <span class="lx-bibl">Gloss. ap. Paul. ex <span class="lx-bibl">'
                      '<span class="lx-author">Fest.</span> p. 380, 9 Müll.</span></span>', out)
        # A glossary is a kind of source, not an author: no chip for it.
        self.assertEqual(T.unique_authors(out), ['Fest.'])
        # annicto: "Naev. ap. Paul. ex <Fest.>" — the poet is named and
        # chips, as he does when the whole reference is plain text.
        src = 'alii adnictat, Naev. ap. Paul. ex ' + BIB % (A % 'Fest.' + ' p. 29') + ' Müll.'
        self.assertEqual(T.unique_authors(T.mark_prose_authors(src)), ['Naev.', 'Fest.'])
        # volubilis: "id. Fragm. ap. Prisc." — the fragments are the named
        # author's own, so "Fragm." mints no chip of its own.
        src = 'x, ' + A % 'id.' + ' Fragm. ap. ' + BIB % (A % 'Prisc.' + ' p. 617') + ' P.'
        # "id." is not an author (3a5e2e9): with no antecedent in this
        # snippet it mints no chip, and Priscian's stands alone.
        self.assertEqual(T.unique_authors(T.mark_prose_authors(src)), ['Prisc.'])
        # Sila: "Sall. Fragm. ap. Serv." names Sallust, and the chip is
        # Sallust's, as it is where Perseus marked the same shape.
        src = 'x, Sall. Fragm. ap. ' + BIB % (A % 'Serv.' + ' ad Verg. A. 1, 702')
        self.assertEqual(T.unique_authors(T.mark_prose_authors(src)), ['Sall.', 'Serv.'])
        # στεμφυλίς: "Philem.Gloss. ap. Ath." is Philemon's glossary.
        src = 'x, Philem.Gloss. ap. ' + BIB % (A % 'Ath.' + ' 2.49f')
        self.assertEqual(T.unique_authors(T.mark_prose_authors(src)), ['Philem.', 'Ath.'])

    @latin
    def test_a_lead_inside_a_quotation_is_left_alone(self):
        # affecto: the merged quotation span (T13) holds "Sall. Fragm. ap.
        # Aug." between its two quotations, and the example extractor
        # reads the quotation's first author span as where its Latin ends.
        src = ('<span class="lx-cit"><span class="lx-quote">dominationes, Sall. Fragm. ap. '
               + BIB % (A % 'Aug.' + ' Civ. Dei, 3, 17') + ': caelum,</span></span>')
        self.assertNotIn('<span class="lx-author">Sall. Fragm.</span>', T.mark_prose_authors(src))
        # nugator: the lead before a Festus this pass wrapped from plain text.
        src = "nauci'st homo, Enn. ap. Paul. ex Fest. s. v. naucus, p. 166 Müll. (x"
        self.assertEqual(self.strip(src), "nauci'st homo, (x")
        self.assertEqual(T.unique_authors(T.mark_prose_authors(src)), ['Enn.', 'Fest.'])

    @latin
    def test_the_lead_before_a_bare_title(self):
        # saepio: no author span at all, only the inscription's title.
        src = 'SAEPIATVR, Cenot. Pisan. ap. <i class="lx-title">Inscr. Orell.</i> 642; cf.'
        self.assertEqual(self.strip(src), 'SAEPIATVR, ; cf.')

    @latin
    def test_the_editor_after_the_quotations_close(self):
        # aborior: the citation is the quotation's reference, so its close
        # is followed by the quotation's, then "Müll." and the dash.
        src = ('<span class="lx-cit"><span class="lx-quote">ubi aboriuntur,</span> '
               + BIB % (A % 'Varr.' + ' <i class="lx-title">L.L.</i> 5, 7, § 66')
               + '</span> Müll. —Of the voice')
        self.assertIn('§ 66 Müll.</span></span> —Of the voice', T.mark_prose_authors(src))
        # armillum: before an em dash; anomalia: after "sq.".
        self.assertIn('p. 2 Müll.</span>—Hence',
                      T.mark_prose_authors(BIB % (A % 'Fest.' + ' p. 2') + ' Müll.—Hence'))
        self.assertIn('§ 3 sq. Müll.</span>',
                      T.mark_prose_authors(BIB % (A % 'Varr.' + ' L. L. 9, § 3') + ' sq. Müll.'))

    @latin
    def test_festus_as_the_digitisation_spells_him(self):
        for src in ('bottles, Paul. ex Fest p 46 Müll.',
                    'bottles, Paul. ex Fest, p. 29 Müll.',
                    'bottles, Fest. S. V. NEC, p. 162 Müll.',
                    'bottles, Paul. ex Fest. s. h. v. p. 15 Müll.',
                    'bottles, Fest. s. v. majorem consulem, p. 161, 31 Müll.',
                    'bottles, Pac. ap. Fest. s. v. redhostire'):
            self.assertEqual(self.strip(src), 'bottles,', src)
            self.assertIn('Fest.', T.unique_authors(T.mark_prose_authors(src)), src)
        # duritia: a marked Cato before a plain Festus with the lemma in
        # capitals and the line after the page.
        src = 'etc., ' + A % 'Cato' + ' ap. Fest. S. V. REPASTINARI, p. 281, 23 Müll.; x'
        self.assertEqual(self.strip(src), 'etc., ; x')
        # A name alone is a name, not a reference.
        for src in ('cf. Fest. and Non.', 'acc. to Festus, it signifies'):
            self.assertEqual(T.mark_prose_authors(src), src)

    @latin
    def test_varro_and_chapter_references_in_plain_text(self):
        src = 'the accusative case, Var. L. L. 8, § 66 Müll.; v. accusativus'
        self.assertEqual(self.strip(src), 'the accusative case, ; v. accusativus')
        self.assertEqual(T.unique_authors(T.mark_prose_authors(src)), ['Varr.'])
        self.assertEqual(self.strip('vas, Varr L. L. 5, § 119 Müll.: x'), 'vas, : x')
        for src in ('vocantur, <i>in Arabic</i>, Sol. c. 33.',
                    'abditissimus, Aug. Enchir. c. 16.',
                    'a fellow-clergyman, Jul. Epit. Nov. c. 115, § 475.'):
            out = T.mark_prose_authors(src)
            self.assertNotIn(' c. ', self.strip(src), src)
            self.assertEqual(len(T.unique_authors(out)), 1, src)

    @latin
    def test_the_zone_runs_past_a_citation_nested_in_a_bare_wrapper(self):
        import entrylib as L
        # cutis: the zone used to cut at the inner marked citation and
        # keep "Prop., Planc. ap". The wrapper stays bare (the zone runs
        # past a bare author's citation) and the cut skips what it holds.
        src = ('Prop., ' + A % 'Planc.' + ' ap. '
               + BIB % (A % 'Cic.' + ' <i class="lx-title">Fam.</i> 10, 18, 3') + '; '
               + BIB % (A % 'Cels.' + ' 2, 8'))
        out = T.mark_prose_authors(src)
        self.assertIn('data-bare="1"><span class="lx-author">Planc.</span> ap. ', out)
        zone = L.defzone(out)[0]
        self.assertNotIn('Planc.', zone)
        self.assertEqual(L.text_of(zone).strip(), 'Prop.,')
        # et: the zone does not run past the wrapper into the next
        # quotation.
        src = ('qui illius impudentiam norat et duritudinem, ' + A % 'Cato' + ' ap. '
               + BIB % (A % 'Gell.' + ' 1') + ': te sale nata precor, ' + A % 'Enn.' + ' ap. '
               + BIB % (A % 'Non.' + ' 2'))
        self.assertEqual(L.text_of(L.defzone(T.mark_prose_authors(src))[0]).strip(),
                         'qui illius impudentiam norat et duritudinem,')
        # fero: Vahlen's edition in the print's own spelling.
        self.assertEqual(self.strip('help, (Trag. v. 50 ed. Vahl.)'), 'help, ()')

    def test_the_lead_chain_ends_on_the_plain_scholiast(self):
        # ἀφυσγετός: "Tyrannio ap.Sch. <Il. 1.1>" is one chain; read as
        # "Sch." alone it stranded "Tyrannio ap." in the identity line.
        src = '(ἀφύσγετος Tyrannio ap.Sch. ' + BIB % '<i class="lx-title">Il.</i> 1.1' + ')'
        self.assertEqual(self.strip(src), '(ἀφύσγετος )')
        src = '= αἴθριος, Pherenic. ap. ' + A % 'Sch.' + ' ' + BIB % '<i class="lx-title">Pi.</i> 1'
        self.assertEqual(self.strip(src), '= αἴθριος,')
        # A run of capitals is a quotation, not a name.
        self.assertEqual(self.strip('TRES. DATO. ap. ' + BIB % (A % 'Fest.' + ' p. 376')), 'TRES. DATO.')

    @latin
    def test_the_governed_name_is_the_leads_own(self):
        src = 'acc. to Gloss. ap. Paul. ex ' + BIB % (A % 'Fest.' + ' p. 380, 9') + ' Müll.'
        self.assertEqual(self.strip(src), 'acc. to Gloss.')

    @latin
    def test_festus_ends_where_the_print_or_the_markup_ends(self):
        for src, want in (('a look, a view, Fest. s. v. spectio, p. 333 Müll.</div>', 'a look, a view,'),
                          ('x, Fest. S. V. NEC, p. 162 Müll.—Subst.', 'x, —Subst.'),
                          ('in Fest. s. v. opima, p. 190: IVNONI', 'in Fest. : IVNONI'),
                          ('the double, XII. Tab. ap. Fest. S. V. VINDICIAE, p. 376, 30 Müll.; x', 'the double, ; x')):
            self.assertEqual(self.strip(src), want, src)
        out = T.mark_prose_authors('the double, XII. Tab. ap. Fest. S. V. VINDICIAE, p. 376, 30 Müll.; x')
        self.assertEqual(T.unique_authors(out), ['XII. Tab.', 'Fest.'])

    def test_a_line_the_print_attests_is_a_sense(self):
        # cruento I "Lit.: vigiles, Enn. ap. Macr." has A/B under it and
        # four quotations of its own; ἀνάλγητος I is a nested roman of
        # seven words with a citation.
        self.assertFalse(T.is_banner('I.', 'Lit.:', True, 0, False, attested=True))
        self.assertTrue(T.is_banner('I.', 'Lit.:', True, 0, False, attested=False))
        self.assertFalse(T.is_banner('I.', 'of persons, insensible to pain or danger,', True, 1, False, True))
        self.assertTrue(T.is_banner('I.', 'of persons, insensible to pain or danger,', True, 1, False, False))
        # A top-level roman with a cue and no attestation is still a head.
        self.assertTrue(T.is_banner('I.', 'computation, reckoning', True, 0, False, False))

    def test_the_example_window_skips_a_lemma_inside_the_citation(self):
        # λόγος II.2: "ἱεροὶ λ., of Orphic rhapsodies, Suid. S.V. Ὀρφεύς".
        ev = ('<span class="lx-foreign" lang="grc">ἱεροὶ λ.,</span> of Orphic <i>rhapsodies,</i> '
              + A % 'Suid.' + ' S.V. <span class="lx-foreign" lang="grc">Ὀρφεύς</span>.')
        ex = T.examples_of('', T.mark_prose_authors(ev))
        self.assertEqual([e['gr'] for e in ex], ['ἱεροὶ λ.'])
        self.assertEqual(ex[0]['eng'], 'of Orphic rhapsodies')

    def test_a_pair_is_one_citation(self):
        # σάλαξ: "Thphr. or Arist. (Fr. 261) ap. Poll. 10.149" — refusing
        # the pair when the second author looked like prose left "or
        # Arist." on the row.
        src = ('riddle, ' + A % 'Thphr.' + ' or ' + A % 'Arist.' + ' (' + BIB % '<i class="lx-title">Fr.</i> 261'
               + ') ap. ' + BIB % (A % 'Poll.' + ' 10.149'))
        # "Arist." itself is the parenthesis rule's residue (its locus is
        # bracketed, so it reads as prose); the conjunction must not be.
        self.assertNotIn(' or ', self.strip(src))

    def test_a_volume_in_roman_and_a_locus_after_a_period(self):
        # ταὐτοπάθεια "Hdn.Gr. ap. An.Ox. 3. 271", δεείλη "Sch. … iii 6".
        src = 'signification, ' + A % 'Hdn.Gr.' + ' ap. <i class="lx-title">An.Ox.</i> 3. 271, x'
        self.assertNotIn('271', self.strip(src))
        src = '= δείλη, ' + A % 'Sch.' + ' <i class="lx-title">Ar.</i> iii 6, x'
        self.assertNotIn('iii', self.strip(src))

    def test_as_governs_a_name(self):
        src = 'or = τομίας (as ' + A % 'Sch.' + ' ' + BIB % '<i class="lx-title">Theoc.</i> 1.1' + ')'
        self.assertEqual(self.strip(src), 'or = τομίας (as Sch. )')

    @latin
    def test_festus_as_printed_the_hard_cases(self):
        for src, want in (('appellantur, Paul. ex Fest. pp. 11. 51 Müll.', 'appellantur,'),
                          ('company, Fest. p. 344 b. Müll.; x', 'company, ; x'),
                          ('facit, Fest. p. 234 fin. Müll.; x', 'facit, ; x'),
                          ('reglescit, Fest. s. h. v. p. 278, 30 Müll.', 'reglescit,'),
                          ('illuviem, Lucil. ap. Fest. l. l.; x', 'illuviem, ; x'),
                          ('ITO, Fragm. XII. Tab. ap. Fest. s. v. X, p. 1: y', 'ITO, : y'),
                          ('etc., Lex Serv. Tullii ap. Fest. p. 1; x', 'etc., ; x')):
            self.assertEqual(self.strip(src), want, src)
        self.assertEqual(T.unique_authors(T.mark_prose_authors('ITO, Fragm. XII. Tab. ap. Fest. s. v. X, p. 1: y')),
                         ['Fragm. XII. Tab.', 'Fest.'])
        # A governed plain-text reference keeps its name in the sentence.
        self.assertEqual(self.strip('a stake, acc. to Varr L. L. 6, § 70 Müll.'), 'a stake, acc. to Varr.')
        self.assertEqual(self.strip('for children, acc. to Paul. ex Fest. p. 9 Müll.'), 'for children, acc. to Paul.')
        self.assertEqual(self.strip('for children, acc. to Fest. p. 9 Müll.'), 'for children, acc. to Fest.')
        # arbiter: the wrapper the lead joins around a plain-text
        # reference is bare like it, so the zone runs on.
        import entrylib as L
        src = 'DATO. ap. Fest. s. v. vindiciae, p. 376 Müll., and the ancient formula: ' + BIB % (A % 'Cic.' + ' 1')
        self.assertEqual(L.text_of(T._strip_citations(L.defzone(T.mark_prose_authors(src))[0])).split(),
                         ['DATO.', ',', 'and', 'the', 'ancient', 'formula:'])

    @latin
    def test_only_a_reference_with_its_editor_is_wrapped_inside_a_quotation(self):
        # The digitisation runs two quotations into one span with the
        # first one's reference between them. Wrapping that reference is
        # what splits them (mensa keeps its Curiales quotation and its
        # own Festus); the looser shapes cut in the wrong place and take
        # the second quotation with them (calceus, adverto), so inside a
        # quotation only name + page + editor is wrapped.
        def quoted(q):
            return ('<span class="lx-cit"><span class="lx-quote">' + q + '</span> '
                    + BIB % (A % 'Cic.' + ' 1') + '</span>')
        ev = quoted('Curiales mensae, in quibus immolabatur Junoni, Paul. ex Fest. '
                    's. v. Curiales, p. 64 Müll.: mensae deorum,')
        self.assertEqual(T.examples_of('', T.mark_prose_authors(ev))[0]['gr'],
                         'Curiales mensae, in quibus immolabatur Junoni, Paul. ex Fest.')
        for quote in ('Titin. ap. Fest. s. v. mulleos, p. 142 ib. (Com. Rel. p. 128 Rib.): '
                      'calcei habiles et apti ad pedem,',
                      'si voles advortere animum, Enn. ap. Var. L. L. 7, § 89 Müll. '
                      '(Trag. v. 386 Vahl.): facete advortis animum tuum ad animum meum,'):
            self.assertEqual(T.mark_prose_authors(quoted(quote)), quoted(quote))
            self.assertEqual(T.examples_of('', quoted(quote))[0]['gr'], quote.rstrip(','))

    def test_greek_editors_stay_where_they_are(self):
        src = BIB % (A % 'Orph.' + ' <i class="lx-title">A.</i> 646') + ' Ruhnk. (x)'
        self.assertEqual(T.mark_prose_authors(src), src)
        src = 'x ' + A % 'Hsch.' + ' (ψωραλέον Ruhnk.).'
        self.assertNotIn('Ruhnk.</span>', T.mark_prose_authors(src))


class IdentityAgainstFormsBar(unittest.TestCase):
    """D4: the bar wins. A Lewis & Short bar body is the inflection
    itself and is short, so the old length floor exempted every Latin
    entry from a rule that was already ruled."""

    @latin
    def test_a_short_latin_inflection_is_still_a_duplicate(self):
        for line, bar in (('ĕre, 3', 'ĕre, 3'), ('ātus, 1', 'ātus, 1'), ('lŭi, 3', 'lŭi, 3')):
            self.assertEqual(T.ident_without_forms(line, [['', bar]]), '', line)

    def test_greek_keeps_its_floor_until_the_line_is_ruled_on(self):
        # "Att. fut. ἀποικιῶ" over a bar that says "fut. ἀποικιῶ": the
        # label carries the dialect, and the label goes with the form.
        # 13 entries would lose the word that says which future it is.
        self.assertEqual(T.ident_without_forms('Att. fut. ἀποικιῶ', [['fut.', 'ἀποικιῶ']]),
                         'Att. fut. ἀποικιῶ')

    @latin
    def test_the_line_keeps_what_the_bar_does_not_carry(self):
        self.assertEqual(T.ident_without_forms('ātus, 1, v. freq. dep. utor', [['', 'ātus, 1']]),
                         'v. freq. dep. utor')
        self.assertEqual(T.ident_without_forms('a, um, Part. armo', [['', 'a, um']]), 'Part. armo')
        self.assertEqual(T.ident_without_forms('a, um, = ἀβάσκαντος', [['', 'a, um']]), '= ἀβάσκαντος')

    @latin
    def test_a_short_run_matches_only_at_the_prints_boundaries(self):
        # Inside a word is not a duplicate: the bar's "a, um" must not
        # find the "a, um" inside a longer form.
        self.assertEqual(T.ident_without_forms('columnae', [['', 'umna']]), 'columnae')
        # Inside the print's own sentence it stays whole, as before.
        self.assertEqual(T.ident_without_forms('(aor. in use ἔβην, hence)', [['aor.', 'ἔβην']]),
                         '(aor. in use ἔβην, hence)')

    def test_the_greek_verb_lines_are_left_for_john(self):
        # φράσσω: the bar has the principal parts and the line threads
        # them through the Attic and Epic forms. Whatever comes out, the
        # line's own wording survives — this is the open design question,
        # not something the floor change decides.
        out = T.ident_without_forms(
            'Att. φράττω, al.: fut. φράξω (δια-), etc.: aor. ἔφραξα, Ep. φράξα',
            [['fut.', 'φράξω'], ['aor.', 'ἔφραξα']])
        self.assertIn('Att. φράττω', out)
        self.assertIn('Ep. φράξα', out)


class ZonePolish(unittest.TestCase):
    """A row opens on its first word and closes on its last, whichever
    path built it."""

    def z(self, zone):
        return T.row_doc({'lv': 0, 'n': '', 'zone': zone}, 'x')['z']

    def test_the_comma_before_a_stripped_bare_citation(self):
        # ἀβόητος: "not loudly lamented, Epigr.Gr. 240" — the citation
        # went, the comma stayed inside the cue.
        self.assertEqual(self.z('<b class="cue">not loudly lamented,</b>'),
                         '<b class="cue">not loudly lamented</b>')
        self.assertEqual(self.z('<b class="cue">a plant</b>;'), '<b class="cue">a plant</b>')

    def test_the_supplied_words_bracket(self):
        # ἀβίωτος "ἀβίωτόν [ἐστι] life is intolerable": the Greek is in
        # the drawer, the bracket was left on the row.
        self.assertEqual(self.z('] life is intolerable'), 'life is intolerable')
        self.assertEqual(self.z('<b class="cue">to be swollen,</b> ['), '<b class="cue">to be swollen</b>')
        # A bracket with its mate, and a real aside, stay.
        self.assertEqual(self.z('ἄξιόν [ἐστι] meet'), 'ἄξιόν [ἐστι] meet')
        self.assertEqual(self.z('grease (syn'), 'grease (syn')

    def test_a_polish_never_empties_a_row(self):
        # The six the build gate caught: a gloss that is only the word
        # the trailing rule removes, and a supplied-word bracket whose
        # gloss is short enough to read as a truncated aside.
        for z in ('or', 'and', '<b class="cue">and</b>', '[<b class="cue">commander</b>'):
            self.assertTrue(re.search(r'\w', re.sub(r'<[^>]+>', '', self.z(z))), z)
        self.assertEqual(self.z('<b class="cue">and</b>'), '<b class="cue">and</b>')
        self.assertEqual(self.z('[<b class="cue">commander</b>'), '[<b class="cue">commander</b>')

    def test_the_seam_a_removed_quotation_left(self):
        self.assertEqual(self.z('coming alongside of : hence, coming near'), 'coming alongside of: hence, coming near')
        self.assertEqual(self.z('holly, Ilex Aquifolium, :—also κήλαστρος'), 'holly, Ilex Aquifolium:—also κήλαστρος')
        self.assertEqual(self.z('repetition, []'), 'repetition')
        self.assertEqual(self.z('slowly, 142; 143 al.—'), 'slowly, 142; 143 al.')
        self.assertEqual(self.z('copiantur, Quadrig. ap. Gell. l. l., and'), 'copiantur, Quadrig. ap. Gell. l. l.')
        self.assertEqual(self.z('a band'), 'a band')
        # The print's own colon-dash and a Greek middle dot are untouched.
        self.assertEqual(self.z('kindle:—metaph.'), 'kindle:—metaph.')

    @latin
    def test_the_dash_that_opened_a_split_note(self):
        # abbas: ".—Hence, abbātissa" split at the dash, which then led
        # the row. A hyphen is a sub-lemma's and stays.
        self.assertEqual(self.z('—Hence, abbātissa, ae, f., an abbess'), 'Hence, abbātissa, ae, f., an abbess')
        self.assertEqual(self.z('<b class="cue">—In dates</b>'), '<b class="cue">In dates</b>')
        self.assertEqual(self.z('-nesco, -nĭtas'), '-nesco, -nĭtas')
        self.assertEqual(self.z('. loose ship for a place'), 'loose ship for a place')


class GroupLabel(unittest.TestCase):
    def test_the_cap_does_not_land_inside_a_bracket(self):
        # ἀφαιρέω II: cueless, so the label is the prose, capped.
        lab = 'Med., fut. ἀφαιρήσομαι (in pass. sense ἀφαιρεθήσομαι): take away for oneself'
        self.assertEqual(T.cap_label(lab), 'Med., fut. ἀφαιρήσομαι')
        self.assertEqual(T.cap_label('relation, correspondence, proportion'),
                         'relation, correspondence, proportion')
        # A cap never empties a label: redeo II is one long aside.
        self.assertEqual(T.cap_label('(With the idea of ire predominating; cf.: recido, redigo)'),
                         'With the idea of ire predominating; cf.')
        # A label the cut never touched keeps the print's last word.
        for lab in ('show affection for', 'set fire to', 'be mixed with', 'in front of'):
            self.assertEqual(T.cap_label(lab), lab)
        self.assertEqual(T.cap_label('put in a certain state, condition (with'),
                         'put in a certain state, condition')
        # Long enough to be cut, so the link word the cut leaves goes.
        self.assertEqual(T.cap_label('with Verbs of perceiving, observing, and judging of'),
                         'with Verbs of perceiving, observing')


class SmallLatinFixes(unittest.TestCase):
    def entry_docs(self, head):
        recs = extract.get('lat-ls', extract.fold_latin(head))
        self.assertTrue(recs, f'missing source entry: lat-ls {head}')
        return [T.to_doc(T.model(rec.get('head') or head, rec),
                         rec.get('key') or '') for rec in recs
                if rec.get('head') == head]

    @latin
    def test_parenthesized_collateral_gender_is_not_the_headwords(self):
        self.assertEqual(self.entry_docs('charta')[0].get('g'), 'f.')
        noun = next(doc for doc in self.entry_docs('solum')
                    if doc.get('key') == 'so^lum1')
        self.assertEqual(noun.get('g'), 'n.')

    @latin
    def test_a_verbs_neuter_label_is_not_a_gender(self):
        voveo = self.entry_docs('voveo')[0]
        self.assertNotIn('g', voveo)
        self.assertEqual(voveo.get('i'), '2')
        laxo = self.entry_docs('laxo')[0]
        self.assertNotIn('g', laxo)
        self.assertEqual(laxo.get('i'), 'āvi, 1')

    @latin
    def test_a_nouns_correct_gender_stays(self):
        self.assertEqual(self.entry_docs('bulla')[0].get('g'), 'f.')

    @latin
    def test_identity_line_drops_a_stranded_governor(self):
        html = ('<b class="lx-head">Academice</b> <span class="lx-itype">ēs</span>, in '
                + BIB % (A % 'Cic.' + ' Att. 13, 16') + '; better written as Greek'
                + '<div class="lx-sense" data-level="1"><i>x</i></div>')
        self.assertEqual(T.head_bits(html)[2], 'ēs')
        # Not a word that ends in "in": Elis "ĭdis (acc. Elin".
        html = ('<b class="lx-head">Elis</b> <span class="lx-itype">ĭdis</span> (acc. Elin '
                + BIB % (A % 'Cic.' + ' 1') + ')<div class="lx-sense" data-level="1"><i>x</i></div>')
        self.assertEqual(T.head_bits(html)[2], 'ĭdis (acc. Elin)')

    def test_identity_line_of_punctuation_alone_is_dropped(self):
        # ἀγαλματογλύφος: the "=" its pointer left behind, and οὔ που:
        # the print's ellipsis and nothing else.
        html = ('<b class="lx-head">x</b> =<div class="lx-sense" data-level="1">'
                '<i>y</i></div>')
        self.assertEqual(T.head_bits(html)[2], '')
        html = ('<b class="lx-head">x</b> . .<div class="lx-sense" data-level="1">'
                '<i>y</i></div>')
        self.assertEqual(T.head_bits(html)[2], '')

    @latin
    def test_a_bare_conjugation_number_stays(self):
        # L&S expergiscor "3": the conjugation, and the whole line.
        html = ('<b class="lx-head">expergiscor</b> <span class="lx-itype">3</span>'
                '<div class="lx-sense" data-level="1"><i>y</i></div>')
        self.assertEqual(T.head_bits(html)[2], '3')

    def test_identity_line_still_dedupes_against_a_bar_ending_on_the_governor(self):
        # σύλληψις: the bar keeps "σύλλαψις v.l. in"; the line dropped the "in".
        self.assertEqual(
            T.ident_without_forms('εως, Ion. σύλλαψις v.l.', [['Ion.', 'σύλλαψις v.l. in']]),
            'εως')
        self.assertEqual(
            T.ident_without_forms('ον (also α, ον); Att. contr. ἀκούσιος [ᾱ], ον',
                                  [['Att.', 'contr. ἀκούσιος [ᾱ], ον, also in']]),
            'ον (also α, ον)')

    @latin
    def test_latin_id_resolves(self):
        self.assertEqual(T.cite_from(BIB % (A % 'id.' + ' 3, 6'), 'Cels.')[0], 'Cels. 3, 6')


class LatinEquations(unittest.TestCase):
    """L&S opens many entries with the Greek word the Latin one comes
    from — "onocrotalus, i, m., = ὀνοκρόταλος" — and head_bits had been
    dropping it. Restore just that clause from the entry's opening
    declaration; leave everything past the first sense alone."""

    def ident(self, head, index=0):
        recs = extract.get('lat-ls', extract.fold_latin(head))
        self.assertTrue(recs, f'missing source entry: lat-ls {head}')
        matches = [r for r in recs if r.get('head') == head]
        self.assertGreater(len(matches), index, f'no entry {index} for lat-ls {head}')
        return T.head_bits(matches[index]['html'])[2]

    @latin
    def test_itype_gains_the_equation(self):
        self.assertEqual(self.ident('onocrotalus'), 'i, = ὀνοκρόταλος')
        self.assertEqual(self.ident('nama'), 'ătis, = νᾶμα')

    @latin
    def test_pos_gains_the_equation(self):
        self.assertEqual(self.ident('eu'), 'interj., = εὖ')

    @latin
    def test_no_trailing_period(self):
        # Aristides: the print's own sentence period ends the preamble,
        # not the equation.
        self.assertEqual(self.ident('Aristides'), 'is, = Ἀριστείδης')

    @latin
    def test_alternative_spelling_of_the_headword_still_counts(self):
        # Lindus (-os): a parenthesized alternative spelling of the
        # headword itself, before its grammar, is not a second word.
        self.assertEqual(self.ident('Lindus'), 'i, = Λίνδος')
        # Partheni or Parthīni: same, joined by "or" instead of parens,
        # and the equation itself chains two Greek words the same way.
        self.assertEqual(self.ident('Partheni'), 'ōrum, = Παρθεινοί or Παρθινοί')

    @latin
    def test_a_later_derived_words_equation_does_not_come_along(self):
        # hypogeus goes on, in the same sense (not in `pre`), to derive
        # hypŏgēum "= ὑπόγειον"; only the entry's own equation belongs
        # on hypogeus's identity line. Two independent readers passed 19
        # of 20 cases of this shape and both failed exactly this one.
        self.assertEqual(self.ident('hypogeus'), 'adj., = ὑπόγαιος')

    @latin
    def test_variant_spelling_in_parens_is_taken(self):
        # sandix, pagrus: L&S's own further Greek spelling, in parens
        # right after the equation and holding nothing but that Greek
        # (commas, hyphens, spaces aside), belongs to the equation.
        self.assertEqual(self.ident('sandix'), '= σάνδυξ (σάνδιξ)')
        self.assertEqual(self.ident('pagrus'), 'ri, = πάγρος (φάγρος)')

    @latin
    def test_variant_list_in_parens_is_taken(self):
        # Attis: three further spellings, still nothing but Greek
        # (and the commas between them) inside the parens.
        self.assertEqual(self.ident('Attis'), 'ĭdis, = Ἄττις (Ἄττυς, Ἄτυς, Ἄττιν)')

    @latin
    def test_variant_after_dialect_label_is_taken(self):
        # cratera, Ephyra: no parens at all — the print instead names
        # the dialect and gives the Greek straight after it.
        self.assertEqual(self.ident('cratera'), 'ae, = κρατήρ, Ion. κρητήρ')
        self.assertEqual(self.ident('Ephyra'), 'ae, and, = Ἐφύρα, Ion. Ἐφύρη')

    @latin
    def test_dialect_label_inside_the_parens_is_taken(self):
        # John's ruling: a dialect or form label at the front of the
        # parens counts as part of the equation the same as it does
        # outside them. aruncus, camus: the abbreviated "Dor."; malum:
        # the unabbreviated "Doric"; Callirrhoe: "epic," with the comma
        # the print puts after it.
        self.assertEqual(self.ident('aruncus'), 'i, = ἤρυγγος (Dor. ἄρυγγος)')
        self.assertEqual(self.ident('camus'), 'i, = κημός (Dor. καμός)')
        self.assertEqual(self.ident('malum', index=1), 'i, = μῆλον (Doric μᾶλον)')
        self.assertEqual(self.ident('Callirrhoe'), 'ēs, = Καλλιρρόη (epic, Καλλιρόη)')

    @latin
    def test_and_or_joining_greek_inside_the_parens_is_taken(self):
        # philitia: "(φιδίτια and φειδιτια)" — the print's own "and"
        # joins two further spellings, no label at all.
        self.assertEqual(self.ident('philitia'), 'ōrum, = φιλίτια (φιδίτια and φειδιτια)')

    @latin
    def test_parenthetical_gloss_is_not_a_variant(self):
        # andron's "(ἀνήρ, a man)" and argilla's "(ἀργής, white)" are
        # L&S's own English note on the Greek, not a further spelling
        # of it — the parens hold more than Greek, commas, hyphens and
        # spaces, so they stay off the identity line, as before this
        # branch touched them. analeptris's "(ἀναλαμβάνω, to hold up)"
        # is the same shape.
        self.assertEqual(self.ident('andron'), 'ōnis, = ἀνδρών')
        self.assertEqual(self.ident('argilla'), 'ae, = ἄργιλλος')
        self.assertEqual(self.ident('analeptris'), 'ĭdis, = ἀναληπτρίς')

    @latin
    def test_citation_in_parens_is_not_a_variant(self):
        # Cannae's "(Κάννα, Polyb.)" cites Polybius for the singular;
        # melania's "(μέλας, Cels. 5, 28, 19)" and linyphus's "(λίνυφος,
        # Gloss.)" cite a source the same way. None of "Polyb.", "Cels.
        # 5, 28, 19" or "Gloss." is Greek, so the parens are left where
        # they were.
        self.assertEqual(self.ident('Cannae'), 'ārum, = Κάνναι')
        self.assertEqual(self.ident('melania'), 'ae, = μελανία')
        self.assertEqual(self.ident('linyphus'), 'i, = λινόϋφος, λινοϋφής')

    @latin
    def test_implied_noun_in_parens_is_not_a_variant(self):
        # gagates "(λίθος)" ("the stone"), hysopites/hepteris "(οἶνος/
        # ναῦς)", sophistice "(τέχνη)" and proceleusmaticus "(πούς)" are
        # all-Greek by shape (Greek spans, no stray English), but the
        # parenthesized word is the noun the headword's meaning implies,
        # not a further spelling of the equation's own Greek word --
        # measured by likeness (John's rule; ratio < 0.6), not shape.
        self.assertEqual(self.ident('gagates'), 'ae, = γαγάτης')
        self.assertEqual(self.ident('hysopites'), 'ae, = ὑσσωπίτης')
        self.assertEqual(self.ident('hepteris'), 'is, = ἑπτήρης')
        self.assertEqual(self.ident('sophistice', index=1), 'ēs, = σοφιστική')
        self.assertEqual(self.ident('proceleusmaticus'), 'i, = προκελευσματικὸς')

    @latin
    def test_etymology_with_an_internal_hyphen_is_not_a_variant(self):
        # thermapalus's "(θερμός-ἁπαλός)" is L&S's own etymology ("hot +
        # soft"), one Greek span with a hyphen joining two stems in the
        # middle of it -- not a variant spelling, however close a bare
        # ratio would read it, because a mid-word hyphen between Greek
        # letters marks an etymology and never a variant.
        self.assertEqual(self.ident('thermapalus'), 'adj., = θερμάπαλος')

    @latin
    def test_ending_or_stem_in_parens_is_still_taken(self):
        # Arcesilas "(-αος)": a hyphen at the front or back of the word
        # marks an ending or a stem, not a spelling to measure by
        # likeness, and it is taken regardless of the ratio.
        self.assertEqual(self.ident('Arcesilas'), 'ae, = Ἀρκεσίλας (-αος)')

    @latin
    def test_close_spelling_in_parens_is_still_taken(self):
        # Sciron "(Σκείρων)" and Crimisus "(Κριμισσός)": no label, no
        # "and"/"or", but the word inside is a close spelling of the
        # equation's own Greek (John's ratio >= 0.6), so it is taken the
        # same as before this round.
        self.assertEqual(self.ident('Sciron'), 'ōnis, = Σκίρων (Σκείρων)')
        self.assertEqual(self.ident('Crimisus'), 'i, = Κριμῖσός (Κριμισσός)')

    @latin
    def test_or_join_outside_parens_is_still_taken(self):
        # Hyarotis "(or Ὑδραώτης)": the print's own "or" joins the
        # further spelling, inside the parens this time (cratera and
        # Ephyra do it outside); that settles it on its own, no ratio
        # needed.
        self.assertEqual(self.ident('Hyarotis'), 'ĭdis, = Ὑαρῶτις (or Ὑδραώτης)')

    def test_lsj_is_untouched(self):
        # πυρισπόρος already carries "= foreg." from LSJ's own pointer
        # logic, on a wholly different code path; the Latin rule above
        # must never run for grc-lsj.
        recs = extract.get('grc-lsj', extract.fold_greek('πυρισπόρος'))
        rec = next(r for r in recs if r.get('head') == 'πυρισπόρος')
        self.assertEqual(T.head_bits(rec['html'])[2], 'ον, = foreg., .')


class Polish(unittest.TestCase):
    def test_trailing_separator_and_comma_before_period(self):
        self.assertEqual(T._polish_emitted('prob. by mistake for x,'), 'prob. by mistake for x')
        self.assertEqual(T._polish_emitted('Amphiaraus,. next'), 'Amphiaraus. next')

    def test_ellipsis_is_not_a_comma_before_a_period(self):
        self.assertEqual(T._polish_emitted('habeat, ... ac'), 'habeat, ... ac')


FOR = '<span class="lx-foreign" lang="grc">%s</span>'


class GovernedGreek(unittest.TestCase):
    """A Greek run the sentence governs stays on the sense line."""

    def eng(self, zone):
        return T.split_sense(zone)

    def test_object_inside_the_italic_is_part_of_the_cue(self):
        # σισυρνοδύτης: "one who wears a σίσυρνα,"
        eng, ill = self.eng('<i>one who wears a ' + FOR % 'σίσυρνα,' + '</i> ')
        self.assertIn('σίσυρνα', eng)
        self.assertEqual(ill, '')

    def test_governor_with_nothing_between_keeps_its_object(self):
        # ἀβακίσκος: "Dim. of ἄβαξ, small stone for inlaying, in mosaic work"
        eng, ill = self.eng('<span class="lx-gram">Dim. of</span> ' + FOR % 'ἄβαξ,'
                            + ' <i>small stone for inlaying,</i> in mosaic work, ')
        self.assertIn('ἄβαξ', eng)
        self.assertIn('<b class="cue">small stone for inlaying', eng)
        self.assertEqual(ill, '')
        # στομφασμός: "as ἀμφασία, γνάμπτω for ἀφασία, γνάπτω" — both runs.
        eng, ill = self.eng('<i>creation of a word,</i> as ' + FOR % 'ἀμφασία' + ' for '
                            + FOR % 'ἀφασία,')
        self.assertIn('ἀμφασία', eng)
        self.assertIn('ἀφασία', eng)
        self.assertEqual(ill, '')

    def test_greek_inside_an_aside_stays_in_the_sentence(self):
        # θεόπληκτος: "(in Dor. form -πλακτος)" shipped "(in Dor. form"
        eng, ill = self.eng('<i>stricken of God,</i> (in Dor. form ' + FOR % '-πλακτος' + ').')
        self.assertIn('-πλακτος', eng)
        self.assertEqual(ill, '')
        # ἤτριον: "warp (the woof being κρόκη)"
        eng, ill = self.eng('<i>warp</i> (the woof being ' + FOR % 'κρόκη' + '),')
        self.assertIn('κρόκη', eng)
        self.assertEqual(ill, '')
        # A closed parenthesis before the Greek does not shelter it.
        eng, ill = self.eng('<i>warp</i> (of cloth) ' + FOR % 'κρόκη ἐστίν')
        self.assertIn('κρόκη', ill)

    def test_comma_still_makes_a_quotation(self):
        # ἐπιμωμάομαι: "find fault with, τινί" — the print's comma says so.
        eng, ill = self.eng('<i>find fault with,</i> ' + FOR % 'τινί')
        self.assertNotIn('τινί', eng)
        self.assertIn('τινί', ill)

    def test_supplied_word_stays_with_sc(self):
        # Ἀδρόμιος: "sc. μήν, month at Halos" shipped "sc".
        eng, ill = self.eng('sc. ' + FOR % 'μήν,' + ' month at Halos, ')
        self.assertIn('μήν', eng)
        self.assertIn('month at Halos', eng)


class BracketsWithTheirLetters(unittest.TestCase):
    def test_bracket_outside_the_span_moves_in(self):
        # ἀβόητος: "[κλέος] οὐκ ἀ." shipped "not noised abroad, ["
        z = T._brackets_into_greek('<i>not noised abroad,</i> [' + FOR % 'κλέος' + '] ')
        self.assertIn(FOR % '[κλέος]', z)
        self.assertNotIn('] ', z)

    def test_bracket_closed_outside_the_span_moves_in(self):
        # ἀβίωτος: "ἀβίωτόν [ἐστι] life is intolerable" shipped "] life is…"
        z = T._brackets_into_greek(FOR % 'ἀβίωτόν [ἐστι' + '] <i>life is intolerable,</i>')
        self.assertIn(FOR % 'ἀβίωτόν [ἐστι]', z)
        eng, ill = T.split_sense(z)
        self.assertTrue(eng.startswith('<b class="cue">life is intolerable'))

    def test_bracketed_author_is_a_citation(self):
        # ἀδιαπνευστέω: "[Gal.]10.528" shipped "not to evaporate, []10.528"
        out = T.mark_prose_authors('<i>not to evaporate,</i> [' + A % 'Gal.' + ']10.528.')
        self.assertIn('data-bare', out)
        self.assertEqual(T._strip_citations(out), '<i>not to evaporate,</i> .')

    def test_second_locus_after_a_comma_joins_the_citation(self):
        # λεπτοκοπέω: "Dsc. 1.12, 5.75 (both Pass.)" shipped "small, 5.75"
        out = T.mark_prose_authors('<i>chop fine,</i> ' + A % 'Dsc.' + ' 1.12, 5.75 (both Pass.).')
        self.assertEqual(T._strip_citations(out), '<i>chop fine,</i>  (both Pass.).')
        # ", 3 kinds" is prose and stays.
        out = T.mark_prose_authors('<i>x,</i> ' + A % 'Dsc.' + ' 1.12, 3 kinds of it.')
        self.assertEqual(T._strip_citations(out), '<i>x,</i> , 3 kinds of it.')


class PolishSeams(unittest.TestCase):
    def test_separator_inside_the_closing_tag_goes(self):
        # ἀβόητος: "<b class="cue">not loudly lamented,</b>" after Epigr.Gr. went.
        self.assertEqual(T._polish_emitted('<b class="cue">not loudly lamented,</b>'),
                         '<b class="cue">not loudly lamented</b>')
        self.assertEqual(T._polish_emitted('<b class="cue">age, seniority,</b> : opp. x'),
                         '<b class="cue">age, seniority</b>: opp. x')

    def test_leading_period_and_trailing_open_bracket_go(self):
        self.assertEqual(T._polish_emitted('. (or Abas), ae, m.'), '(or Abas), ae, m.')
        self.assertEqual(T._polish_emitted('to the Gr. γε ('), 'to the Gr. γε')
        self.assertEqual(T._polish_emitted('... ac'), '... ac')

    def test_comma_before_a_bracket_goes_in_the_gloss_only(self):
        row = {'lv': 0, 'n': '', 'zone': '<b class="cue">chop fine,</b> (both Pass.)'}
        self.assertEqual(T.row_doc(row, 'x')['z'], '<b class="cue">chop fine</b> (both Pass.)')
        self.assertEqual(T._polish_emitted('ου, (ῥήγνυμι)'), 'ου, (ῥήγνυμι)')


class Chips(unittest.TestCase):
    """An author chip names an author; "Id." and a bare work title name
    the last one the print named."""

    def test_id_resolves_to_the_last_named_author(self):
        ev = BIB % (A % 'Pl.' + ' Phd. 65a') + '; ' + BIB % (A % 'Id.' + ' R. 509b')
        self.assertEqual(T.unique_authors(ev), ['Pl.'])
        # From the row above, through `prev`; nothing to resolve against
        # means no chip rather than a chip reading "Id.".
        ev = BIB % (A % 'Id.' + ' R. 509b')
        self.assertEqual(T.unique_authors(ev, 'Pl.'), ['Pl.'])
        self.assertEqual(T.unique_authors(ev), [])

    def test_bare_title_is_the_last_authors_work(self):
        # "Pl. Phd. 65a, R. 509b": the table lists R. under Pl.
        ev = BIB % (A % 'Pl.' + ' Phd. 65a') + ', ' + BIB % ('<i class="lx-title">R.</i> 509b')
        self.assertEqual(T.unique_authors(ev), ['Pl.'])
        # A work with no author stays a chip of its own.
        ev = BIB % (A % 'Pl.' + ' Phd. 65a') + ', ' + BIB % ('<i class="lx-title">AP</i> 7.1')
        self.assertEqual(T.unique_authors(ev), ['Pl.', 'AP'])

    def test_prose_mention_is_an_antecedent(self):
        ev = ('only in <span class="lx-author lx-prose">Cicero</span>: '
              + BIB % (A % 'id.' + ' Fam. 15, 18, 1'))
        self.assertEqual(T.unique_authors(ev), ['Cicero'])

    def test_last_author_skips_id(self):
        self.assertEqual(T.last_author(A % 'Hdt.' + ' 1.1, ' + A % 'Id.' + ' 2.2'), 'Hdt.')

    def test_entry_carries_the_antecedent_across_rows(self):
        html = ('<b class="lx-head" lang="grc">x</b>, <div class="lx-sense" data-level="1">'
                '<i>one,</i> ' + BIB % (A % 'Hdt.' + ' 1.1') + '.</div>'
                '<div class="lx-sense" data-level="1"><b class="lx-sense-n">2.</b> <i>two,</i> '
                + BIB % (A % 'Id.' + ' 2.2') + '.</div>')
        doc = T.to_doc(T.model('x', {'head': 'x', 'key': 'x', 'html': html}), 'x')
        self.assertEqual([r.get('au') for r in doc['rows']], [['Hdt.'], ['Hdt.']])


class GovernedQuote(unittest.TestCase):
    """The object Perseus wrapped into the quotation after it."""

    def test_first_word_of_the_quote_is_the_object(self):
        # ξεστιαῖος: "of a ξέστης, μέτρον Gal. 13.435" shipped "of a".
        html = ('<i>of a</i> <span class="lx-cit"><span class="lx-quote" lang="grc">ξέστης, μέτρον'
                '</span> ' + BIB % (A % 'Gal.' + ' 13.435') + '</span>.')
        row = T.make_row('x', 'x', T.mark_prose_authors(html), 'sense')
        import entrylib as L
        self.assertEqual(L.text_of(row['zone']), 'of a ξέστης')
        self.assertEqual([e['gr'] for e in row['examples']], ['μέτρον'])

    def test_one_word_quote_moves_whole(self):
        html = ('<i>not organized as a</i> <span class="lx-cit"><span class="lx-quote" lang="grc">κόσμος'
                '</span> ' + BIB % (A % 'Arist.' + ' 1.1') + '</span>.')
        row = T.make_row('x', 'x', T.mark_prose_authors(html), 'sense')
        import entrylib as L
        self.assertEqual(L.text_of(row['zone']), 'not organized as a κόσμος')
        self.assertEqual(row['examples'], [])
        self.assertEqual(row['authors'], ['Arist.'])

    def test_the_italic_after_a_moved_quote_comes_too(self):
        # ψιλοκιθαριστής: "one who plays the κιθάρα without singing to it"
        html = ('<i>one who plays the</i> <span class="lx-cit"><span class="lx-quote" lang="grc">κιθάρα'
                '</span> <i>without singing to it,</i> ' + BIB % (A % 'Chares' + ' 4') + '</span>.')
        row = T.make_row('x', 'x', T.mark_prose_authors(html), 'sense')
        import entrylib as L
        self.assertEqual(L.text_of(row['zone']), 'one who plays the κιθάρα without singing to it')
        self.assertEqual(row['examples'], [])

    def test_a_phrase_is_a_quotation(self):
        html = ('<i>put up with</i> <span class="lx-cit"><span class="lx-quote" lang="grc">μηκέτι τὴν ἐλευθερίαν'
                '</span> ' + BIB % (A % 'D.' + ' 1.1') + '</span>.')
        row = T.make_row('x', 'x', T.mark_prose_authors(html), 'sense')
        self.assertEqual([e['gr'] for e in row['examples']], ['μηκέτι τὴν ἐλευθερίαν'])


class ShortEntryChips(unittest.TestCase):
    def test_id_in_a_glossary_entry_resolves_across_rows(self):
        rows = [{'authors': ['Hsch.']}, {'authors': ['Id.']}, {'authors': ['Id. 3.5', 'Et.Gud.']},
                {'authors': ['Id.']}]
        T.resolve_same_authors(rows)
        self.assertEqual([r['authors'] for r in rows],
                         [['Hsch.'], ['Hsch.'], ['Hsch. 3.5', 'Et.Gud.'], ['Et.Gud.']])
        rows = [{'authors': ['Sor. 1.125', 'id. 2.3']}]
        T.resolve_same_authors(rows)
        self.assertEqual(rows[0]['authors'], ['Sor. 1.125', 'Sor. 2.3'])
        rows = [{'authors': ['Id.']}]
        T.resolve_same_authors(rows)
        self.assertEqual(rows[0]['authors'], [])


class TitleLoci(unittest.TestCase):
    """A title-only citation goes with every locus the print hangs on it."""

    def test_further_loci_after_the_comma_go_too(self):
        # παραδρομίς: "IG 2(2).1035.56 (pl.), 12(9).234.34 (Euboea)"
        z = T.STRIP_WORK.sub('', '<i>place for taking the air,</i> <i class="lx-title">IG</i> '
                             '2(2).1035.56 (pl.), 12(9).234.34 (), x')
        self.assertEqual(z.strip(), '<i>place for taking the air,</i>  (), x'.strip())
        # ἑκαστάκις: "IG 9(I).694.8 (Corc.)"; σελίς: "4(2)(1).103.163, al."
        self.assertEqual(T.STRIP_WORK.sub('', '<i class="lx-title">IG</i> 9(I).694.8 (Corc.) ; x'),
                         ' ; x')
        self.assertEqual(T.STRIP_WORK.sub('', '<i class="lx-title">IG</i> 1(2).374.58, al., 4(2)(1).103.163, al. (), x'),
                         ', al. (), x')

    def test_a_second_locus_with_a_bracketed_volume(self):
        # κυμβίον: "IG 2(2).1522.32,11(2).145.48" left "(2).145.48"
        self.assertEqual(
            T.STRIP_WORK.sub('', '<i class="lx-title">IG</i> 2(2).1522.32,11(2).145.48 (), x'),
            ' (), x')
        # ἐπικριτήριον, once the placeName spans are out: "GDI 5040.67 ,
        # 5024.52" — the space in front of the comma is the strip's.
        self.assertEqual(
            T.STRIP_WORK.sub('', '<i class="lx-title">GDI</i> 5040.67 , 5024.52 . x'),
            ' . x')

    def test_space_before_a_separator_goes(self):
        self.assertEqual(T._polish_emitted('of Arist. , objection raised'),
                         'of Arist., objection raised')
        self.assertEqual(T._polish_emitted('kind of boat, al. ; Lat. x'),
                         'kind of boat, al.; Lat. x')

    def test_the_mark_reads_the_spelling_the_pack_holds(self):
        # The analyses pack keys its parses by the exact accented
        # surface, and the fold that finds the record throws the accent
        # away: "h" holds ἡ, ἥ, ἧ, ᾗ, ἤ, ἦ and ᾖ together. Pooling them
        # marked ᾗ and ἤ under ὁ and αἱ under εἰ.
        self.assertEqual(T.mark_headword('ᾗ φὴς σὺ σκληρότητι', 'ὁ'),
                         'ᾗ φὴς σὺ σκληρότητι')
        self.assertNotIn('hw', T.mark_headword('εἰς ἑτέραν ἕδραν', 'ἵζω'))
        # The spelling the pack does hold still marks.
        self.assertIn('<b class="hw">τῇ</b>', T.mark_headword('τῇ ἴμεν', 'ὁ'))

    def test_a_work_title_is_not_an_author_chip(self):
        # ἀέροψ cites "Sch. Ar. Av. 1354" and shipped the chips
        # "Ar., Av.": Aristophanes and his own Birds, as two authors.
        self.assertTrue(T._work_only('Av.'))
        self.assertTrue(T._work_only('HA'))
        self.assertTrue(T._work_only('Fr.'))
        # A title LSJ gives no author keeps its chip.
        self.assertFalse(T._work_only('AP'))
        self.assertFalse(T._work_only('h.Merc.'))
        # An abbreviation the table prints as an author stays an author,
        # even where another author has a work of the same name (Ph. is
        # Philo, and Sophocles' Philoctetes).
        self.assertFalse(T._work_only('Ar.'))
        self.assertFalse(T._work_only('Ph.'))

    def test_a_work_chip_goes_where_the_tables_can_say_so(self):
        # Owned by more than one author, so it identifies nobody.
        self.assertEqual(T.drop_work_chips(['Lyc.', 'Fr.', 'Hsch.']),
                         ['Lyc.', 'Hsch.'])
        # One owner and no chip claims it: kept, because the tables'
        # works lists are too thin to drop a name the print gives.
        self.assertEqual(T.drop_work_chips(['Al.']), ['Al.'])
        # An author is never dropped.
        self.assertEqual(T.drop_work_chips(['Ar.', 'Pl.']), ['Ar.', 'Pl.'])

    @latin
    def test_the_tables_switch_with_the_dataset(self):
        # "Planc." is Cicero's Pro Plancio in L&S and nothing in LSJ. The
        # builder runs Greek and then Latin in one process, so a cached
        # map from the first pass would answer for the second.
        self.assertTrue(T._work_only('Planc.'))
        self.assertEqual(T.drop_work_chips(['Cic.', 'Planc.', 'Liv.']),
                         ['Cic.', 'Liv.'])

    def test_a_hyphen_form_expands_only_where_a_witness_confirms_it(self):
        import gen_ideal_verb as G
        known = {'παιδεύσω', 'ποιήσω'}.__contains__
        # The shapes the join was written for, and a witness knows them.
        self.assertEqual(G.expand_suffix('παιδεύω', '-σω', known), 'παιδεύσω')
        self.assertEqual(G.expand_suffix('ποιέω', '-ήσω', known), 'ποιήσω')
        # The shapes it was not. The print's own abbreviation comes back
        # rather than a string no witness supplies.
        self.assertEqual(
            G.expand_suffix('καταλαμβάνω', '-λήψομαι', known), '-λήψομαι')
        self.assertEqual(G.expand_suffix('ὑγιάζω', '-άσω', known), '-άσω')
        self.assertEqual(
            G.expand_suffix('ἀνατρέχω', '-έδραμον', known), '-έδραμον')
        # With no check at all nothing is joined: a caller that cannot
        # confirm a form does not get to invent one.
        self.assertEqual(G.expand_suffix('παιδεύω', '-σω'), '-σω')

    @latin
    def test_a_latin_principal_part_names_its_own_slot(self):
        # Read by position, "abito, ĕre, 3" shipped "pf. ĕre | sup. 3":
        # the print gives an infinitive and a conjugation number.
        self.assertEqual(T._latin_slot('3'), 'conj.')
        self.assertEqual(T._latin_slot('ĕre'), 'inf.')
        self.assertEqual(T._latin_slot('ātum'), 'sup.')
        self.assertEqual(T._latin_slot('āvi'), 'pf.')
        # Read on the last word: the print writes "and ălĭtum".
        self.assertEqual(T._latin_slot('and ălĭtum'), 'sup.')
        self.assertEqual(T._latin_slot('cŭcurri and curri'), 'pf.')
        # A shape that names no slot gets none, rather than the next
        # label in a list: "ātus" is a participle and "Halm" an editor.
        self.assertEqual(T._latin_slot('ātus'), '')
        self.assertEqual(T._latin_slot('Halm'), '')

    def test_an_equation_row_keeps_an_abbreviations_period(self):
        # ἀκτερής is "= foreg., prob. in Hsch." and shipped "in Hsch".
        # eq_zone stripped a trailing period whatever it belonged to;
        # _tidy is the rule that knows a sentence's from an
        # abbreviation's, and it runs after.
        # As it reaches eq_zone, with the author already marked in the
        # prose by mark_prose_authors.
        html = '<span class="lx-abbr">=</span> foreg., prob. in Hsch.'
        self.assertTrue(T.eq_zone(html).rstrip().endswith('Hsch.'))
        # "q. v." loses its "v." upstream, and the bare "q." went with
        # the period this used to take: L&S myrrhis is "= myrtis".
        self.assertEqual(T.eq_zone('= myrtis, q.').strip(), '= myrtis')

    def test_the_prints_ellipsis_survives(self):
        # LSJ writes the omission with two dots, spaced or not. Both dots
        # are the witness's and neither may be folded away.
        for text in ('ὁ μέν.., ὁ δέ..',
                     'both.. and',
                     'Εἰλείθυιαι . . ὠδῖνας ἔχουσαι',
                     'αἰδοῦς ἀξίαν.. τὴν προθυμίαν'):
            self.assertEqual(T._polish_emitted(text), text)

    def test_a_sense_line_does_not_open_on_the_moved_quotations_tail(self):
        # μέν: the print's "μέν . . , δέ . . (or when the correlative
        # clause is neg. …)". The quotation goes to the drawer and the
        # ellipsis that closed it must not head the sense line.
        self.assertEqual(
            T._polish_emitted({'z': '.. (or when the clause is neg.)'}),
            {'z': '(or when the clause is neg.)'})
        # At the head of a quotation the same mark is the print's own.
        self.assertEqual(T._polish_emitted({'ex': [{'g': '. ., ἤ'}]}),
                         {'ex': [{'g': '. ., ἤ'}]})

    def test_a_comma_before_the_prints_period_still_folds(self):
        # The shape the collapse rule was there for is its neighbour's:
        # Ἀμφιεραϊστής "worshipper of Amphiaraus,." once the citation
        # between the comma and the period went.
        self.assertEqual(T._polish_emitted('worshipper of Amphiaraus, . and x'),
                         'worshipper of Amphiaraus. and x')

    def test_the_old_shapes_still_strip(self):
        self.assertEqual(T.STRIP_WORK.sub('', '<i class="lx-title">IG</i> ΙΙ(2).199 x'), ' x')
        self.assertEqual(T.STRIP_WORK.sub('', '<i class="lx-title">Ep.</i> 1p.10U. x'), ' x')
        self.assertEqual(T.STRIP_WORK.sub('', '<i class="lx-title">R.</i> 526a, x'), ', x')

    def test_bracket_before_a_citation_moves_into_the_quote(self):
        html = ('<i>live by the side of,</i> [<span class="lx-cit"><span class="lx-quote" lang="grc">'
                'ψυχὴ] τῷ σώματι παραζῶσα</span> ' + BIB % (A % 'Plu.' + ' 2.672e') + '</span>.')
        out = T.mark_prose_authors(html)
        self.assertIn('<span class="lx-quote" lang="grc">[ψυχὴ]', out)
        row = T.make_row('x', 'x', out, 'sense')
        import entrylib as L
        self.assertEqual(L.text_of(row['zone']), 'live by the side of')
        self.assertEqual(row['examples'][0]['gr'], '[ψυχὴ] τῷ σώματι παραζῶσα')


class LocusWithNoAuthor(unittest.TestCase):
    """A run of loci the print hangs on one title is stripped whole.

    Each case is an entry the census reported under "locus with no
    author": the title and its first locus went and a bare number stayed
    on the sense line.
    """

    T = '<i class="lx-title">%s</i>'

    def strip(self, src):
        return T.STRIP_WORK.sub('', src)

    def test_a_marked_aside_between_the_loci_does_not_stop_the_run(self):
        # αἱμάτιον: "SIG 1002.11 (Milet.), 1025.53 (Cos)" left ", 1025.53".
        # _strip_citations has usually taken the placeName span out
        # already, so the print's bracket arrives here standing empty.
        self.assertEqual(
            self.strip(self.T % 'SIG' + ' 1002.11 (), 1025.53 (), x'), ' (), x')
        # ἔξοδος: "IG 14.422 (Tauromenium), 5(1).1390.50".
        self.assertEqual(
            self.strip(self.T % 'IG' + ' 14.422 (), 5(1).1390.50, x'), ', x')
        # On the paths that still hold the span, the span reads as the aside.
        self.assertEqual(
            self.strip(self.T % 'SIG' + ' 1002.11 (<span class="lx-placeName">'
                       'Milet.</span>), 1025.53, x'), ', x')

    def test_an_aside_that_ends_the_run_keeps_the_prints_separator(self):
        # θηροκτόνος: "epith. of Heracles, IG 5(2).91 (Tegea); of
        # Artemis". Eating the shell at the end of a run took the
        # semicolon with it and the sense read "Heracles, of Artemis".
        self.assertEqual(
            self.strip('Heracles, ' + self.T % 'IG' + ' 5(2).91 (); of Artemis'),
            'Heracles,  (); of Artemis')

    def test_an_aside_that_names_a_reading_is_not_an_aside(self):
        # ἴκρια: "(prob. in IG 1(2).374.151)" holds a whole citation, so
        # the run stops in front of it and "4.39" stays where it is.
        self.assertIn('4.39', self.strip(
            self.T % 'IG' + ' 1(2).94.28 (prob. in ' + self.T % 'IG'
            + ' 1(2).374.151), 4.39, x'))

    def test_the_volume_the_print_spaces_off_from_its_title(self):
        # ἀδελφός: "IG 12 (9).906.19" left "(9).906.19".
        self.assertEqual(self.strip(self.T % 'IG' + ' 12 (9).906.19; x'), '; x')
        # ἐκέχειρον: "IG 12 (5). 1341.53" left "(5). 1341.53".
        self.assertEqual(self.strip(self.T % 'IG' + ' 12 (5). 1341.53, x'), ', x')

    def test_a_further_locus_after_cf_goes_with_its_title(self):
        # ἀκινάκης: "IG 1.170.17, cf. 2.646.11".
        self.assertEqual(
            self.strip(self.T % 'IG' + ' 1.170.17, cf. 2.646.11; x'), '; x')
        # But a bare number after "cf." is a cross-reference, not a locus.
        self.assertEqual(
            self.strip(self.T % 'IG' + ' 1.170.17, cf. 2; x'), ', cf. 2; x')

    def test_ib_carries_the_same_loci_a_title_does(self):
        # ἀμαυρόω: "ib. 12(9).1129.22" left "(9).1129.22".
        self.assertEqual(self.strip('a tomb, ib. 12(9).1129.22:—x'), 'a tomb, :—x')
        # ἀντιτυγχάνω: "ib. 5(1).1146 (Gythium, i B.C.), cf. 7.3080".
        self.assertEqual(self.strip('x ib. 5(1).1146 (), cf. 7.3080 (), y'),
                         'x  (), y')
        # The trailing stop the old digits-and-stops pattern ate still goes.
        self.assertEqual(self.strip('hammer, ib. 78. (Perh. x'),
                         'hammer,  (Perh. x')

    def test_a_volume_written_over_two_years(self):
        # ἀσυντέλεστος: "Annuario 4/5.225" left "/5.225".
        self.assertEqual(self.strip(self.T % 'Annuario' + ' 4/5.225, x'), ', x')

    def test_al_carries_an_aside_of_its_own(self):
        # γυμνασιαρχέω: "IG 3.1104, al., 5(1).481, al. (Sparta), 7.1669".
        self.assertEqual(
            self.strip(self.T % 'IG' + ' 3.1104, al., 5(1).481, al. (), 7.1669, x'),
            ', x')
        # κλᾴξ: "42(1).102.110, al. (Epid., iv B.C.), 5(1).1390.92".
        self.assertEqual(
            self.strip(self.T % 'IG' + ' 42(1).102.110, al. (), 5(1).1390.92; x'),
            '; x')

    def test_an_unmarked_place_and_century_bridge_two_loci(self):
        # ἑκατόμβοιος: "SIG 36.36 (Delph., V B.C.), 82.6 (Delph., V B.C.)";
        # ἱεροθέσιον: "OGI 383.36 (Nemrud Dagh), 403.1 (Kara Kush)". The
        # aside that ends the run stays, as it always has.
        self.assertEqual(
            self.strip(self.T % 'SIG' + ' 36.36 (Delph., V B.C.), 82.6 '
                       '(Delph., V B.C.), x'), ' (Delph., V B.C.), x')
        self.assertEqual(
            self.strip(self.T % 'OGI' + ' 383.36 (Nemrud Dagh), 403.1 (Kara Kush), x'),
            ' (Kara Kush), x')

    def test_the_identity_line_reads_the_same_run(self):
        # _TITLED_LOCUS shares the grammar so the line and the forms bar
        # agree on where a citation ends.
        for src in (self.T % 'IG' + ' 12 (9).906.19',
                    self.T % 'IG' + ' 14.422 (), 5(1).1390.50',
                    self.T % 'IG' + ' 1.170.17, cf. 2.646.11'):
            self.assertEqual(T._TITLED_LOCUS.sub('<CIT>', src + '; x'), '<CIT>; x')


class AsideAcrossACitation(unittest.TestCase):
    """A quotation cannot close a bracket the definition opened."""

    def test_the_asides_tail_comes_out_of_the_quotation(self):
        # L&S concitor: "(rare; not in Cic.; <quote>in MSS. freq.
        # interchanged with concitator): belli,</quote> Liv. 23, 41, 1"
        zone = ('<i>an exciter</i> (rare; not in Cic.; <span class="lx-cit">'
                '<span class="lx-quote">in MSS. freq. interchanged with concitator): belli,'
                '</span> ' + BIB % (A % 'Liv.' + ' 23, 41, 1') + '</span>')
        out = T.close_open_paren(zone)
        self.assertIn('in MSS. freq. interchanged with concitator) <span class="lx-cit">', out)
        self.assertIn('<span class="lx-quote">belli,</span>', out)
        import entrylib as L
        eng, _ill = T.split_sense(zone)
        self.assertEqual(L.text_of(eng),
                         'an exciter (rare; not in Cic.; in MSS. freq. interchanged with concitator)')

    def test_nothing_left_to_quote(self):
        # L&S tutor: the whole quotation was the aside's tail.
        zone = ('<i>a guardian</i> (prop. of the person; cf. <span class="lx-cit">'
                '<span class="lx-quote">curator, of the estate),</span> '
                + BIB % (A % 'Just.' + ' 1, 14, 4') + '</span>')
        out = T.close_open_paren(zone)
        self.assertIn('curator, of the estate) <span class="lx-cit">', out)
        self.assertIn('<span class="lx-quote"></span>', out)

    def test_a_balanced_zone_is_untouched(self):
        zone = ('<i>x</i> (aside) <span class="lx-cit"><span class="lx-quote">'
                'a quotation) with a bracket</span></span>')
        self.assertEqual(T.close_open_paren(zone), zone)

    def test_a_long_head_is_the_quotations_own_bracket(self):
        zone = ('<i>x</i> (aside <span class="lx-cit"><span class="lx-quote">'
                'one two three four five six seven eight nine ten eleven twelve thirteen)'
                '</span></span>')
        self.assertEqual(T.close_open_paren(zone), zone)


class IdVeto(unittest.TestCase):
    """"Id." means the last author named, but an interposed citation can
    put the wrong name in that seat. pungo's "Cic. Phil. 8, 7, 20; Ter.
    Phorm. 185: ... id. N. D. 1, 20, 52" makes Ter. the antecedent, though
    N. D. is Cicero's; the by-name veto table catches only that pair."""

    @latin
    def test_ter_n_d_resolves_to_cic_through_the_table(self):
        bibl = BIB % (A % 'id.' + ' <i class="lx-title">N. D.</i> 1, 20, 52')
        raw, prev, _ = T.cite_from(bibl, 'Ter.')
        self.assertEqual(raw, 'Cic. N. D. 1, 20, 52')
        # The veto corrects the citation only; the antecedent the print's
        # chain gave stays, so a following "id. ib." is not moved by it.
        self.assertEqual(prev, 'Ter.')

    @latin
    def test_sen_vit_beat_is_untouched(self):
        # Not in the table (and never cut at the first period: this is
        # Seneca's own "Vit. Beat.", not Suetonius' "Vit.").
        bibl = BIB % (A % 'id.' + ' <i class="lx-title">Vit. Beat.</i> 3, 36, 1')
        raw, prev, _ = T.cite_from(bibl, 'Sen.')
        self.assertEqual(raw, 'Sen. Vit. Beat. 3, 36, 1')
        self.assertEqual(prev, 'Sen.')

    @latin
    def test_id_with_no_work_is_untouched(self):
        # "id. p. 30" parses to an empty work and matches no veto entry,
        # even though ("Quint.", "Pis.") is one.
        bibl = BIB % (A % 'id.' + ' p. 30')
        raw, prev, _ = T.cite_from(bibl, 'Quint.')
        self.assertEqual(raw, 'Quint. p. 30')
        self.assertEqual(prev, 'Quint.')


class AbbreviationPeriodsByEntry(unittest.TestCase):
    """The print's final abbreviation period survives every row path."""

    def rows(self, dataset, head):
        analyses = 'grc-analyses' if dataset.startswith('grc') else 'lat-analyses'
        lang = 'grc' if dataset.startswith('grc') else 'la'
        fold = extract.fold_greek if dataset.startswith('grc') else extract.fold_latin
        prior = (T.DATASET, T.ANALYSES, T.LANG)
        try:
            T.configure(dataset, analyses, lang)
            recs = extract.get(dataset, fold(head))
            self.assertTrue(recs, f'missing source entry: {dataset} {head}')
            docs = [T.to_doc(T.model(rec.get('head') or head, rec), rec.get('key') or '')
                    for rec in recs if rec.get('head') == head]
            self.assertTrue(docs, f'missing exact source head: {dataset} {head}')
            return [L.text_of(row.get('z') or '').strip()
                    for doc in docs for row in doc.get('rows') or []]
        finally:
            T.configure(*prior)

    def docs(self, dataset, head):
        analyses = 'grc-analyses' if dataset.startswith('grc') else 'lat-analyses'
        lang = 'grc' if dataset.startswith('grc') else 'la'
        fold = extract.fold_greek if dataset.startswith('grc') else extract.fold_latin
        prior = (T.DATASET, T.ANALYSES, T.LANG)
        try:
            T.configure(dataset, analyses, lang)
            recs = extract.get(dataset, fold(head))
            return [T.to_doc(T.model(rec.get('head') or head, rec), rec.get('key') or '')
                    for rec in recs if rec.get('head') == head]
        finally:
            T.configure(*prior)

    def test_greek_grammar_and_author_abbreviations(self):
        self.assertIn('metaph.', self.rows('grc-lsj', 'ἄβατος'))
        self.assertTrue(any(line.endswith('Poll.')
                            for line in self.rows('grc-lsj', 'θεραπουσία')))
        self.assertTrue(any(line.endswith('D.S.')
                            for line in self.rows('grc-lsj', 'βαιτοφόρος')))

    def test_latin_grammar_and_author_abbreviations(self):
        self.assertIn('Prop.', self.rows('lat-ls', 'abalieno'))
        self.assertTrue(any(line.endswith('absol.')
                            for line in self.rows('lat-ls', 'abeo')))
        self.assertIn('v. the foll. art.', self.rows('lat-ls', 'abomino'))

    def test_english_word_vetoes(self):
        self.assertTrue(any(line.endswith('art')
                            for line in self.rows('grc-lsj', 'ὀξυρεπής')))
        self.assertFalse(any(line.endswith('art.')
                             for line in self.rows('grc-lsj', 'ὀξυρεπής')))
        self.assertTrue(any(line.endswith('term')
                            for line in self.rows('lat-ls', 'simul')))
        self.assertFalse(any(line.endswith('term.')
                             for line in self.rows('lat-ls', 'simul')))
        self.assertTrue(any(line.endswith('aeter-num')
                            for line in self.rows('lat-ls', 'aeternus')))
        self.assertFalse(any(line.endswith('aeter-num.')
                             for line in self.rows('lat-ls', 'aeternus')))
        groups = [label for doc in self.docs('lat-ls', 'bulla')
                  for _number, label in doc.get('gr') or []]
        self.assertIn('Any thing rounded by art', groups)
        self.assertNotIn('Any thing rounded by art.', groups)


class WorkTitleChipsByEntry(unittest.TestCase):
    """A chip names the cited author, not the cited work."""

    def chips(self, dataset, head):
        analyses = 'grc-analyses' if dataset.startswith('grc') else 'lat-analyses'
        lang = 'grc' if dataset.startswith('grc') else 'la'
        fold = extract.fold_greek if dataset.startswith('grc') else extract.fold_latin
        prior = (T.DATASET, T.ANALYSES, T.LANG)
        try:
            T.configure(dataset, analyses, lang)
            recs = extract.get(dataset, fold(head))
            self.assertTrue(recs, f'missing source entry: {dataset} {head}')
            docs = [T.to_doc(T.model(rec.get('head') or head, rec),
                             rec.get('key') or '') for rec in recs
                    if rec.get('head') == head]
            self.assertTrue(docs, f'missing exact source head: {dataset} {head}')
            return [tok for doc in docs
                    for tok in ((doc.get('au') or []) + [
                        chip for row in doc.get('rows') or []
                        for chip in row.get('au') or []])]
        finally:
            T.configure(*prior)

    def test_print_marked_work_titles_go(self):
        self.assertNotIn('Fr.', self.chips('grc-lsj', 'ἀρκεσίβουλος'))
        self.assertNotIn('Inv.', self.chips('grc-lsj', 'ἀξιομίσητος'))

    def test_unmarked_named_work_title_goes(self):
        self.assertNotIn('Decl.', self.chips('lat-ls', 'perplexio'))

    def test_author_counter_cases_stay(self):
        self.assertIn('Virg.', self.chips('grc-lsj', 'ἀερομαντεία'))
        self.assertIn('Al.', self.chips('grc-lsj', 'βρέχω'))


class EditorSiglaByEntry(unittest.TestCase):
    """A one-letter editor siglum stays in print but is not an author."""

    def docs(self, head):
        prior = (T.DATASET, T.ANALYSES, T.LANG)
        try:
            T.configure('grc-lsj', 'grc-analyses', 'grc')
            recs = extract.get('grc-lsj', extract.fold_greek(head))
            self.assertTrue(recs, f'missing source entry: grc-lsj {head}')
            docs = [T.to_doc(T.model(rec.get('head') or head, rec),
                             rec.get('key') or '') for rec in recs
                    if rec.get('head') == head]
            self.assertTrue(docs, f'missing exact source head: grc-lsj {head}')
            return docs
        finally:
            T.configure(*prior)

    def examples(self, head):
        return [example for doc in self.docs(head)
                for row in doc.get('rows') or []
                for example in row.get('ex') or []]

    def chips(self, head):
        return [chip for doc in self.docs(head)
                for chip in ((doc.get('au') or []) + [
                    author for row in doc.get('rows') or []
                    for author in row.get('au') or []])]

    def test_editor_only_citation_is_not_an_author(self):
        examples = self.examples('ἀδιαληψία')
        recs = extract.get('grc-lsj', extract.fold_greek('ἀδιαληψία'))
        rec = next(rec for rec in recs if rec.get('head') == 'ἀδιαληψία')
        match = T._EDITOR.search(rec['html'])
        self.assertIsNotNone(match)
        self.assertNotIn('S.', T.unique_authors(
            T.demote_editor_sigla(match.group(0))))
        self.assertEqual([example['g'] for example in examples],
                         ['διανοημάτων', 'τινός'])
        self.assertIsNone(examples[0].get('c'))

    def test_editor_demotion_keeps_every_quotation(self):
        examples = self.examples('εὐρυχωρία')
        self.assertEqual(len(examples), 11)
        self.assertEqual([example['g'] for example in examples], [
            'ἐν τῇ λοιπῇ <b class="hw">εὐ.</b> τῆς θήκης',
            'πολλὴν <b class="hw">εὐ.</b> ἔχειν',
            '-ίας σε δεῖ',
            'ἕκητι Συλοσῶντος <b class="hw">εὐρυχωρίη</b>',
            '<b class="hw">εὐ.</b> ποιεῖτε τῷ θεῷ',
            'ἡ ἄνω εὐ',
            'ἡ ἀκουστικὴ εὐ',
            'ἐν <b class="hw">εὐ.</b> εἶναι',
            'ἐν <b class="hw">εὐρυχωρίῃ</b> ναυμαχέειν',
            'τῆς ἀποδείξεως',
            '<b class="hw">εὐ.</b> τινὸς διδόναι, παρέχειν',
        ])

    def test_id_keeps_eunapius_as_its_antecedent(self):
        citations = [example.get('c') for example in self.examples('διαδέχομαι')]
        self.assertIn('Eun. p.243', citations)

    def test_id_keeps_arrian_as_its_antecedent(self):
        citations = [example.get('c') for example in self.examples('ὑπερασπίζω')]
        self.assertIn('Arr. An. 6.28.4', citations)

    def test_rowless_entry_keeps_locator_not_editor(self):
        doc, = self.docs('μές')
        self.assertEqual(doc.get('au'), ['p.364'])


class BareConnectiveExample(unittest.TestCase):
    """A connective the print set between quotations is not a translation."""

    def docs(self, head):
        prior = (T.DATASET, T.ANALYSES, T.LANG)
        try:
            T.configure('grc-lsj', 'grc-analyses', 'grc')
            recs = extract.get('grc-lsj', extract.fold_greek(head))
            self.assertTrue(recs, f'missing source entry: grc-lsj {head}')
            return [T.to_doc(T.model(rec.get('head') or head, rec),
                             rec.get('key') or '')
                    for rec in recs]
        finally:
            T.configure(*prior)

    def examples(self, head):
        return [example for doc in self.docs(head)
                for row in doc.get('rows') or []
                for example in row.get('ex') or []]

    def test_agathoo_or_is_not_the_translation(self):
        # ἀγαθόω: "do good to one, τινί or τινά" — the drawer kept the
        # quotation and shipped "or" as its meaning.
        examples = self.examples('ἀγαθόω')
        self.assertFalse(any((ex.get('e') or '').strip().lower() == 'or'
                             for ex in examples))
        self.assertTrue(any(L.text_of(ex.get('g') or '') == 'τινί τινά'
                            for ex in examples))

    def test_aletor_ie_is_not_the_translation(self):
        examples = self.examples('ἀλήτωρ')
        self.assertFalse(any((ex.get('e') or '').strip().lower() == 'i.e.'
                             for ex in examples))

    def test_men_alone_survives(self):
        # μέν, frozen seed: Il. 16.28's quotation "δέ" is translated "alone".
        examples = self.examples('μέν')
        self.assertTrue(any((ex.get('e') or '') == 'alone' for ex in examples))


if __name__ == '__main__':
    unittest.main()


class Headword(unittest.TestCase):
    """What <b class="hw"> is allowed to cover, measured over both packs
    in research/reports/REPORT-headword-marking.md. The span holds the
    word and nothing else, and LSJ's abbreviation of a diphthong-initial
    headword counts as the word."""

    def mark(self, gr, lemma):
        return T.mark_headword(gr, lemma)

    def test_full_stop_after_a_form_stays_outside_the_mark(self):
        # 158 spans in grc-lsj-t8 bolded the print's full stop.
        self.assertEqual(self.mark('αἰδοῦς ἀξίαν.', 'ἄξιος'),
                         'αἰδοῦς <b class="hw">ἀξίαν</b>.')

    def test_greek_question_mark_stays_outside_the_mark(self):
        # U+037E is a Greek-block character, so the token pattern ate it.
        self.assertEqual(self.mark('τί σοι ζῆν ἄξιον;', 'ἄξιος'),
                         'τί σοι ζῆν <b class="hw">ἄξιον</b>;')

    def test_ano_teleia_stays_outside_the_mark(self):
        self.assertEqual(self.mark('ἀφηνιάζετο· ἐχωρίζετο', 'ἀφηνιάζω'),
                         '<b class="hw">ἀφηνιάζετο</b>· ἐχωρίζετο')

    def test_the_abbreviations_period_stays_inside(self):
        self.assertEqual(self.mark('ἡ ἀ. αὐτοῦ', 'ἀνάδειξις'),
                         'ἡ <b class="hw">ἀ.</b> αὐτοῦ')

    def test_a_diphthong_headword_abbreviates_to_the_diphthong(self):
        # 1,186 of these went unmarked because the rule took one letter.
        self.assertEqual(self.mark('τὴν ἀναπνοὴν οὐκ εὔ.', 'εὔκολος'),
                         'τὴν ἀναπνοὴν οὐκ <b class="hw">εὔ.</b>')
        self.assertEqual(self.mark('ὅπλον εἰ.', 'εἰκονικός'),
                         'ὅπλον <b class="hw">εἰ.</b>')

    def test_a_prefix_abbreviation_must_match_the_head_letter_for_letter(self):
        # εὖ. is not the opening of εὔκολος, and a bare εἰ is not εἰκονικός.
        self.assertEqual(self.mark('οὐκ εὖ.', 'εὔκολος'), 'οὐκ εὖ.')
        self.assertEqual(self.mark('εἰ δέ τις', 'εἰκονικός'), 'εἰ δέ τις')

    def test_an_inflected_form_still_marks_through_morpheus(self):
        self.assertEqual(self.mark('τιθέναι τινὰ νικᾶσαι', 'τίθημι'),
                         '<b class="hw">τιθέναι</b> τινὰ νικᾶσαι')
