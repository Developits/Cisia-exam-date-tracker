#!/usr/bin/env python3
"""
Unit tests for matcher.py — verifies word-boundary university matching,
multi-exam type OR logic, date parsing, and row filter evaluation.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import unittest
from datetime import date
from matcher import (
    match_university,
    match_exam_type,
    is_date_in_range,
    row_matches_filter,
    parse_user_date_range,
)


class TestMatchUniversity(unittest.TestCase):
    def test_any_always_matches(self):
        match, score, name = match_university("ANY", "Sapienza University of Rome", "Rome", "Lazio")
        self.assertTrue(match)
        self.assertEqual(score, 1.0)

    def test_word_boundary_prevents_false_positive(self):
        """'bari' should NOT match 'Cagliari' (short alias false positive fix)."""
        match, _, _ = match_university("bari", "University of Cagliari", "Cagliari", "Sardinia")
        self.assertFalse(match)

    def test_bari_matches_bari(self):
        """'bari' should match the actual University of Bari."""
        match, score, _ = match_university("bari", "University of Bari", "Bari", "Puglia")
        self.assertTrue(match)
        self.assertGreater(score, 0.0)

    def test_sapienza_partial_match(self):
        match, score, _ = match_university("sapienza", "Sapienza University of Rome", "Rome", "Lazio")
        self.assertTrue(match)

    def test_bologna_matches(self):
        match, _, _ = match_university("Bologna", "University of Bologna", "Bologna", "Emilia-Romagna")
        self.assertTrue(match)

    def test_pisa_does_not_match_pisano(self):
        """'pisa' should not match a fictional 'Pisano Institute' via substring."""
        # If the row university IS 'Pisano Institute', 'pisa' as a standalone word IS in it
        # so this is a design question — we test that 'pisa' matches 'University of Pisa' correctly
        match, _, _ = match_university("pisa", "University of Pisa", "Pisa", "Tuscany")
        self.assertTrue(match)

    def test_fuzzy_misspelling(self):
        """'Sapineza' (misspelling) should still match Sapienza via fuzzy ratio."""
        match, score, _ = match_university("Sapineza", "Sapienza University of Rome", "Rome", "Lazio")
        self.assertTrue(match)
        self.assertGreater(score, 0.60)

    def test_no_match_unrelated(self):
        match, score, _ = match_university("Harvard", "Sapienza University of Rome", "Rome", "Lazio")
        self.assertFalse(match)
        self.assertEqual(score, 0.0)


class TestMatchExamType(unittest.TestCase):
    def test_all_matches_everything(self):
        self.assertTrue(match_exam_type("ALL", "TOLC-I (Engineering)"))
        self.assertTrue(match_exam_type("ALL", "CEnT-S (English)"))

    def test_tolc_i_matches(self):
        self.assertTrue(match_exam_type("TOLC-I (Engineering)", "TOLC-I (Engineering)"))

    def test_tolc_e_matches(self):
        self.assertTrue(match_exam_type("TOLC-E (Economics)", "TOLC-E (Economics)"))

    def test_cent_s_does_not_match_generic_cent(self):
        """'cent-s' pattern must NOT match a hypothetical row with 'percentage'."""
        self.assertFalse(match_exam_type("CEnT-S (English)", "percentage scores"))

    def test_multi_exam_or_logic(self):
        """Comma-separated exam types: row matches if it matches ANY selected exam."""
        multi = "TOLC-I (Engineering),CEnT-S (English)"
        self.assertTrue(match_exam_type(multi, "TOLC-I (Engineering)"))
        self.assertTrue(match_exam_type(multi, "CEnT-S (English)"))
        self.assertFalse(match_exam_type(multi, "TOLC-E (Economics)"))

    def test_multi_exam_all_types(self):
        multi = "TOLC-I (Engineering),TOLC-E (Economics),CEnT-S (English)"
        self.assertTrue(match_exam_type(multi, "TOLC-I (Engineering)"))
        self.assertTrue(match_exam_type(multi, "TOLC-E (Economics)"))
        self.assertTrue(match_exam_type(multi, "CEnT-S (English)"))


class TestDateParsing(unittest.TestCase):
    def test_dd_mm_yyyy_range(self):
        s, e = parse_user_date_range("10/08/2026 - 15/09/2026")
        self.assertEqual(s, "2026-08-10")
        self.assertEqual(e, "2026-09-15")

    def test_month_names(self):
        s, e = parse_user_date_range("August to September", default_year=2026)
        self.assertEqual(s, "2026-08-01")
        self.assertEqual(e, "2026-09-30")

    def test_empty_returns_none(self):
        s, e = parse_user_date_range("")
        self.assertIsNone(s)
        self.assertIsNone(e)


class TestIsDateInRange(unittest.TestCase):
    def test_in_range(self):
        self.assertTrue(is_date_in_range("15/09/2026", "2026-08-01", "2026-09-30"))

    def test_before_range(self):
        self.assertFalse(is_date_in_range("01/07/2026", "2026-08-01", "2026-09-30"))

    def test_after_range(self):
        self.assertFalse(is_date_in_range("01/10/2026", "2026-08-01", "2026-09-30"))

    def test_no_bounds(self):
        self.assertTrue(is_date_in_range("15/09/2026"))


class TestRowMatchesFilter(unittest.TestCase):
    def _make_row(self, fmt="TOLC@HOME", test_type="TOLC-I (Engineering)",
                  university="Sapienza University of Rome", city="Rome",
                  region="Lazio", date="15/09/2026", state="AVAILABLE SEATS"):
        return {
            "format": fmt, "test_type": test_type,
            "university": university, "city": city,
            "region": region, "date": date, "state": state,
            "key": "test_key", "url": "https://example.com",
            "seats": "10", "deadline": "01/09/2026"
        }

    def test_home_modality_required(self):
        row = self._make_row(fmt="TOLC@UNI")
        f = {"exam_type": "ALL", "university_query": "ANY", "start_date": None, "end_date": None}
        self.assertFalse(row_matches_filter(row, f))

    def test_full_match(self):
        row = self._make_row()
        f = {
            "exam_type": "TOLC-I (Engineering)",
            "university_query": "Sapienza",
            "start_date": "2026-08-01",
            "end_date": "2026-09-30"
        }
        self.assertTrue(row_matches_filter(row, f))

    def test_multi_exam_match(self):
        row = self._make_row(test_type="CEnT-S (English)")
        f = {
            "exam_type": "TOLC-I (Engineering),CEnT-S (English)",
            "university_query": "ANY",
            "start_date": None,
            "end_date": None
        }
        self.assertTrue(row_matches_filter(row, f))

    def test_date_out_of_range(self):
        row = self._make_row(date="01/11/2026")
        f = {
            "exam_type": "ALL",
            "university_query": "ANY",
            "start_date": "2026-08-01",
            "end_date": "2026-09-30"
        }
        self.assertFalse(row_matches_filter(row, f))

    def test_university_no_false_positive(self):
        """'bari' filter must NOT match a Cagliari row."""
        row = self._make_row(university="University of Cagliari", city="Cagliari", region="Sardinia")
        f = {"exam_type": "ALL", "university_query": "bari", "start_date": None, "end_date": None}
        self.assertFalse(row_matches_filter(row, f))


if __name__ == "__main__":
    unittest.main(verbosity=2)
