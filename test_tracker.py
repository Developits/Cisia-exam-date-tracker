#!/usr/bin/env python3
"""
Unit and Integration Tests for CISIA TOLC Seat Tracker
"""

import os
import json
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import patch, MagicMock

import config
import tracker


class TestScheduler(unittest.TestCase):
    def setUp(self):
        self.rome_tz = ZoneInfo("Europe/Rome")

    def test_active_minute_windows(self):
        # 05:59 -> False (before start)
        dt = datetime(2026, 8, 25, 5, 59, tzinfo=self.rome_tz)
        self.assertFalse(tracker.is_active_minute(dt))

        # 06:00 -> True (start)
        dt = datetime(2026, 8, 25, 6, 0, tzinfo=self.rome_tz)
        self.assertTrue(tracker.is_active_minute(dt))

        # 07:15 -> True (mid morning, every minute active)
        dt = datetime(2026, 8, 25, 7, 15, tzinfo=self.rome_tz)
        self.assertTrue(tracker.is_active_minute(dt))

        # 14:42 -> True (afternoon, every minute active)
        dt = datetime(2026, 8, 25, 14, 42, tzinfo=self.rome_tz)
        self.assertTrue(tracker.is_active_minute(dt))

        # 22:00 -> True (end boundary)
        dt = datetime(2026, 8, 25, 22, 0, tzinfo=self.rome_tz)
        self.assertTrue(tracker.is_active_minute(dt))

        # 22:01 -> False (after night end)
        dt = datetime(2026, 8, 25, 22, 1, tzinfo=self.rome_tz)
        self.assertFalse(tracker.is_active_minute(dt))

        # 23:00 -> False
        dt = datetime(2026, 8, 25, 23, 0, tzinfo=self.rome_tz)
        self.assertFalse(tracker.is_active_minute(dt))

        # 03:00 -> False
        dt = datetime(2026, 8, 25, 3, 0, tzinfo=self.rome_tz)
        self.assertFalse(tracker.is_active_minute(dt))

    def test_calculate_sleep_seconds_when_active(self):
        # When active at 07:00:30, should sleep ~30 seconds until next minute
        dt = datetime(2026, 8, 25, 7, 0, 30, 0, tzinfo=self.rome_tz)
        sleep_sec = tracker.calculate_sleep_seconds(dt)
        self.assertAlmostEqual(sleep_sec, 30.0, places=1)

    def test_calculate_sleep_seconds_when_inactive(self):
        # When inactive at 05:00:00, next active is today 06:00:00 (1 hour = 3600 seconds)
        dt = datetime(2026, 8, 25, 5, 0, 0, 0, tzinfo=self.rome_tz)
        sleep_sec = tracker.calculate_sleep_seconds(dt)
        self.assertEqual(sleep_sec, 3600)

        # When inactive at 22:10:00, next active is tomorrow 06:00:00
        # 22:10 to 24:00 is 1h50m (110m), + 6h00m (360m) = 470m = 28200 seconds
        dt = datetime(2026, 8, 25, 22, 10, 0, 0, tzinfo=self.rome_tz)
        sleep_sec = tracker.calculate_sleep_seconds(dt)
        self.assertEqual(sleep_sec, (110 + 360) * 60)


class TestParserAndChangeDetection(unittest.TestCase):
    def setUp(self):
        self.sample_html = """
        <html><body>
        <table id="calendario">
            <thead>
                <tr>
                    <th>FORMAT</th><th>UNIVERSITY</th><th>REGION / FOREIGN COUNTRY</th><th>CITY</th>
                    <th>BOOKINGS DEADLINE</th><th>SEATS</th><th>STATE</th><th>DATE</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td>TOLC@UNI</td>
                    <td>University of Pisa</td>
                    <td>TUSCANY</td>
                    <td>PISA</td>
                    <td>26/08/2026</td>
                    <td>5</td>
                    <td><span style="color: LimeGreen;">AVAILABLE SEATS</span></td>
                    <td>01/09/2026</td>
                </tr>
                <tr>
                    <td>TOLC@HOME</td>
                    <td>Sapienza University of Rome</td>
                    <td>LAZIO</td>
                    <td>ROME</td>
                    <td>26/08/2026</td>
                    <td>---</td>
                    <td><span style="color: Crimson;">NOT LONGER AVAILABLE</span></td>
                    <td>01/09/2026</td>
                </tr>
            </tbody>
        </table>
        </body></html>
        """
        self.page_info = {
            "name": "TOLC-I (Engineering)",
            "url": "https://testcisia.it/calendario.php?tolc=ingegneria&l=gb"
        }

    def test_parse_page_rows(self):
        rows = tracker.parse_page_rows(self.sample_html, self.page_info)
        self.assertEqual(len(rows), 2)
        
        row1 = rows[0]
        self.assertEqual(row1["format"], "TOLC@UNI")
        self.assertEqual(row1["university"], "University of Pisa")
        self.assertEqual(row1["city"], "PISA")
        self.assertEqual(row1["seats"], "5")
        self.assertEqual(row1["state"], "AVAILABLE SEATS")
        self.assertEqual(row1["date"], "01/09/2026")
        
        row2 = rows[1]
        self.assertEqual(row2["format"], "TOLC@HOME")
        self.assertEqual(row2["state"], "NOT LONGER AVAILABLE")

    @patch("tracker.send_notifications")
    @patch("tracker.save_state")
    @patch("tracker.fetch_page")
    def test_first_run_silent_initialization(self, mock_fetch, mock_save, mock_alert):
        mock_fetch.side_effect = lambda page: tracker.parse_page_rows(self.sample_html, page) if page["name"] == "TOLC-I (Engineering)" else []
        
        # Empty previous state and is_first_run=True
        state, alerts = tracker.run_check_cycle(previous_state={}, is_first_run=True)
        
        self.assertEqual(alerts, 0)
        mock_alert.assert_not_called()
        self.assertTrue(mock_save.called)
        self.assertEqual(len(state), 2)

    @patch("tracker.send_notifications", return_value=True)
    @patch("tracker.save_state")
    @patch("tracker.fetch_page")
    def test_status_change_triggers_alert(self, mock_fetch, mock_save, mock_alert):
        # Initial state where Sapienza had NOT LONGER AVAILABLE
        parsed = tracker.parse_page_rows(self.sample_html, self.page_info)
        initial_state = {r["key"]: r for r in parsed}

        # Updated HTML where Sapienza becomes AVAILABLE SEATS
        updated_html = self.sample_html.replace("NOT LONGER AVAILABLE", "AVAILABLE SEATS")
        mock_fetch.side_effect = lambda page: tracker.parse_page_rows(updated_html, page) if page["name"] == "TOLC-I (Engineering)" else []

        state, alerts = tracker.run_check_cycle(previous_state=initial_state, is_first_run=False)

        self.assertEqual(alerts, 1)
        mock_alert.assert_called_once()
        args, kwargs = mock_alert.call_args
        self.assertEqual(kwargs["change_type"], "status_change")
        self.assertEqual(kwargs["old_status"], "NOT LONGER AVAILABLE")

    @patch("tracker.send_notifications", return_value=True)
    @patch("tracker.save_state")
    @patch("tracker.fetch_page")
    def test_new_available_row_triggers_alert(self, mock_fetch, mock_save, mock_alert):
        parsed = tracker.parse_page_rows(self.sample_html, self.page_info)
        initial_state = {parsed[0]["key"]: parsed[0]}  # only Pisa initially

        # Current returns Pisa + Sapienza (which has AVAILABLE SEATS and is TOLC@HOME)
        updated_html = self.sample_html.replace("NOT LONGER AVAILABLE", "AVAILABLE SEATS")
        mock_fetch.side_effect = lambda page: tracker.parse_page_rows(updated_html, page) if page["name"] == "TOLC-I (Engineering)" else []

        state, alerts = tracker.run_check_cycle(previous_state=initial_state, is_first_run=False)

        self.assertEqual(alerts, 1)
        mock_alert.assert_called_once()
        args, kwargs = mock_alert.call_args
        self.assertEqual(kwargs["change_type"], "new")

    @patch("tracker.send_notifications", return_value=True)
    @patch("tracker.save_state")
    @patch("tracker.fetch_page")
    def test_uni_modality_status_change_is_ignored(self, mock_fetch, mock_save, mock_alert):
        # Pisa is TOLC@UNI
        parsed = tracker.parse_page_rows(self.sample_html, self.page_info)
        initial_pisa = dict(parsed[0])
        initial_pisa["state"] = "NOT LONGER AVAILABLE"
        initial_state = {initial_pisa["key"]: initial_pisa}

        # Current returns Pisa with AVAILABLE SEATS, but it's TOLC@UNI so should NOT alert
        mock_fetch.side_effect = lambda page: [parsed[0]] if page["name"] == "TOLC-I (Engineering)" else []

        state, alerts = tracker.run_check_cycle(previous_state=initial_state, is_first_run=False)

        self.assertEqual(alerts, 0)
        mock_alert.assert_not_called()

    @patch("tracker.send_notifications", return_value=True)
    @patch("tracker.save_state")
    @patch("tracker.fetch_page")
    def test_cent_home_modality_triggers_alert(self, mock_fetch, mock_save, mock_alert):
        # CEnT-S CENT@HOME test
        cent_row = {
            "key": "CEnT-S (English)|CENT@HOME|Sapienza University of Rome|ROME|15/09/2026|01/09/2026#1",
            "test_type": "CEnT-S (English)",
            "url": "https://testcisia.it/calendario.php?tolc=cents&l=gb&lingua=inglese",
            "format": "CENT@HOME",
            "university": "Sapienza University of Rome",
            "region": "LAZIO",
            "city": "ROME",
            "deadline": "01/09/2026",
            "seats": "5",
            "state": "AVAILABLE SEATS",
            "date": "15/09/2026"
        }
        old_cent = dict(cent_row)
        old_cent["state"] = "NOT LONGER AVAILABLE"

        mock_fetch.side_effect = lambda page: [cent_row] if page["name"] == "CEnT-S (English)" else []
        state, alerts = tracker.run_check_cycle(previous_state={old_cent["key"]: old_cent}, is_first_run=False)

        self.assertEqual(alerts, 1)
        mock_alert.assert_called_once()


if __name__ == "__main__":
    unittest.main()
