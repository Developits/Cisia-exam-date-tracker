#!/usr/bin/env python3
"""
Unit tests for matcher.py
"""

import unittest
from datetime import date
import matcher


class TestMatcher(unittest.TestCase):
    def test_university_alias_and_fuzzy(self):
        target_uni = "Sapienza University of Rome"
        target_city = "ROME"
        target_region = "LAZIO"

        # Exact / alias matches
        match, score, name = matcher.match_university("sapienza", target_uni, target_city, target_region)
        self.assertTrue(match)

        # Misspelling from user prompt: "sepienga"
        match, score, name = matcher.match_university("sepienga", target_uni, target_city, target_region)
        self.assertTrue(match)

        # City match
        match, score, name = matcher.match_university("rome", target_uni, target_city, target_region)
        self.assertTrue(match)

        # Non-matching
        match, score, name = matcher.match_university("bologna", target_uni, target_city, target_region)
        self.assertFalse(match)

        # "ANY" match
        match, score, name = matcher.match_university("ANY", target_uni, target_city, target_region)
        self.assertTrue(match)

    def test_parse_user_date_range(self):
        # Format: DD/MM/YYYY - DD/MM/YYYY
        s, e = matcher.parse_user_date_range("10/08/2026 - 15/09/2026")
        self.assertEqual(s, "2026-08-10")
        self.assertEqual(e, "2026-09-15")

        # Format: DD/MM to DD/MM with default year 2026
        s, e = matcher.parse_user_date_range("10/08 to 15/09", default_year=2026)
        self.assertEqual(s, "2026-08-10")
        self.assertEqual(e, "2026-09-15")

        # Format: Next 30 Days
        s, e = matcher.parse_user_date_range("Next 30 Days")
        self.assertIsNotNone(s)
        self.assertIsNotNone(e)

    def test_exam_type_matching(self):
        self.assertTrue(matcher.match_exam_type("CEnT-S (English)", "CEnT-S (English)"))
        self.assertTrue(matcher.match_exam_type("CEnT-S", "CEnT-S (English)"))
        self.assertTrue(matcher.match_exam_type("ALL", "TOLC-I (Engineering)"))
        self.assertTrue(matcher.match_exam_type("TOLC-I", "TOLC-I (Engineering)"))
        self.assertFalse(matcher.match_exam_type("TOLC-E", "TOLC-I (Engineering)"))

    def test_row_matches_filter(self):
        row = {
            "test_type": "CEnT-S (English)",
            "format": "CENT@HOME",
            "university": "Sapienza University of Rome",
            "city": "ROME",
            "region": "LAZIO",
            "date": "15/08/2026",
            "state": "AVAILABLE SEATS",
            "seats": "10"
        }

        # Matching filter
        f1 = {
            "exam_type": "CEnT-S (English)",
            "university_query": "sepienga",
            "start_date": "2026-08-10",
            "end_date": "2026-09-15"
        }
        self.assertTrue(matcher.row_matches_filter(row, f1))

        # Non-matching exam type
        f2 = dict(f1, exam_type="TOLC-I (Engineering)")
        self.assertFalse(matcher.row_matches_filter(row, f2))

        # Date outside window (test date is 15/08, filter ends 12/08)
        f3 = dict(f1, end_date="2026-08-12")
        self.assertFalse(matcher.row_matches_filter(row, f3))

        # Non-home format should be rejected strictly
        row_uni = dict(row, format="CENT@UNI")
        self.assertFalse(matcher.row_matches_filter(row_uni, f1))


if __name__ == "__main__":
    unittest.main()
