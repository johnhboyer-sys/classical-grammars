#!/usr/bin/env python3
"""Tests for the proper-name supplement (stdlib only).

Run: python3 scripts/wordtool/test_names_supplement.py
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import names_supplement as ns  # noqa: E402
from build_wordtool import write_pack  # noqa: E402

PYLADES = {"key": "*pula/dhs", "en": "Pylades", "source": "smith-bio:pylades-bio-1",
           "text": "Pylades, son of Strophius, king of Phocis & friend of Orestes."}
IOLEUS = {"key": "*)io/leus", "en": "Ioleus", "source": "own", "text": "Ionic form of Ἰόλαος: Iolaus."}


def packs(tmp: Path) -> None:
    write_pack(tmp, "grc-lsj-t8", {"pu": {"puladhs": [{"head": "πυλάδης", "key": "pula/dhs", "rows": []}]}}, {"entries": 1})
    write_pack(tmp, "grc-analyses", {
        "pu": {"puladhs": {
            "Πυλάδης": [["Πυλάδης", [], "", "masc nom sg", None]],
            "πυλάδης": [["πυλάδης", ["pula/dhs"], "gate", "masc nom sg", None]],
        }},
    }, {"forms": 2})


class Supplement(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        packs(self.tmp)

    def t8_slot(self, folded):
        _, t8 = ns.read_pack(self.tmp, "grc-lsj-t8")
        return t8[folded[:2]].get(folded, [])

    def test_doc_renders_head_rows_and_credit(self):
        doc = ns.to_doc(PYLADES)
        self.assertEqual(doc["head"], "Πυλάδης")
        self.assertEqual(doc["key"], "*pula/dhs")
        self.assertEqual(doc["rows"][0]["lv"], 0)
        self.assertTrue(doc["rows"][0]["z"].startswith('<b class="cue">Pylades</b>, son of'))
        self.assertIn("&amp;", doc["rows"][0]["z"])
        self.assertEqual(doc["rows"][0]["au"], ["Smith, Biography and Mythology (1849)"])
        self.assertNotIn("au", ns.to_doc(IOLEUS)["rows"][0])

    def test_apply_adds_doc_and_attaches_key_only_to_keyless_rows(self):
        out = ns.apply(self.tmp, [PYLADES, IOLEUS])
        slot = self.t8_slot("puladhs")
        self.assertEqual([d["key"] for d in slot], ["pula/dhs", "*pula/dhs"])
        _, an = ns.read_pack(self.tmp, "grc-analyses")
        forms = an["pu"]["puladhs"]
        self.assertEqual(forms["Πυλάδης"][0][1], ["*pula/dhs"])
        self.assertEqual(forms["πυλάδης"][0][1], ["pula/dhs"])
        self.assertEqual(out["grc-analyses"]["names_attached"], 1)
        self.assertEqual(out["grc-lsj-t8"]["names_supplement"], 2)
        self.assertEqual([d["key"] for d in self.t8_slot("ioleus")], ["*)io/leus"])

    def test_apply_twice_is_the_same_as_once(self):
        first = ns.apply(self.tmp, [PYLADES])
        second = ns.apply(self.tmp, [PYLADES])
        self.assertEqual(first["grc-lsj-t8"]["sha256"], second["grc-lsj-t8"]["sha256"])
        self.assertEqual(first["grc-analyses"]["sha256"], second["grc-analyses"]["sha256"])

    def test_dropping_an_entry_removes_its_doc_and_key(self):
        ns.apply(self.tmp, [PYLADES])
        ns.apply(self.tmp, [IOLEUS])
        self.assertEqual([d["key"] for d in self.t8_slot("puladhs")], ["pula/dhs"])
        _, an = ns.read_pack(self.tmp, "grc-analyses")
        self.assertEqual(an["pu"]["puladhs"]["Πυλάδης"][0][1], [])

    def test_lexicon_key_collision_raises(self):
        with self.assertRaises(ValueError):
            ns.apply(self.tmp, [{**PYLADES, "key": "pula/dhs"}])

    def test_attaches_to_a_capitalised_keyless_row_in_the_heads_own_slot(self):
        # Grammata's form index files Οἰκλῆς under the lemma Ὀϊκλέης; the
        # lookup renders every row in the folded slot of the word it gets.
        write_pack(self.tmp, "grc-analyses", {"oi": {"oiklhs": {
            "Ὀικλῆς": [["Ὀϊκλέης", [], "", "masc nom sg", "Ὀϊκλῆς"]],
            "οἰκλῆς": [["οἰκλέω", [], "", "pres", None]],
        }}}, {"forms": 2})
        ns.apply(self.tmp, [{"key": "*oi)klh=s", "en": "Oicles", "source": "own", "text": "Oicles, father of Amphiaraus."}])
        _, an = ns.read_pack(self.tmp, "grc-analyses")
        self.assertEqual(an["oi"]["oiklhs"]["Ὀικλῆς"][0][1], ["*oi)klh=s"])
        self.assertEqual(an["oi"]["oiklhs"]["οἰκλῆς"][0][1], [])

    def test_homonym_display(self):
        self.assertEqual(ns.display("*pa/ris2"), "Πάρις (2)")

    def test_committed_names_file_loads(self):
        if ns.NAMES.exists():
            entries = ns.load()
            for e in entries:
                self.assertTrue(e["text"] and e["en"] and e["key"], e)
                self.assertIn(e["source"].split(":", 1)[0], ns.CREDIT, e)


if __name__ == "__main__":
    unittest.main()
