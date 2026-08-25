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
        # 06:54 -> False (before start)
        dt = datetime(2026, 8, 25, 6, 54, tzinfo=self.rome_tz)
        self.assertFalse(tracker.is_active_minute(dt))

        # 06:55 -> True (morning start)
        dt = datetime(2026, 8, 25, 6, 55, tzinfo=self.rome_tz)
        self.assertTrue(tracker.is_active_minute(dt))

        # 07:00 -> True (in 55-05 window)
        dt = datetime(2026, 8, 25, 7, 0, tzinfo=self.rome_tz)
        self.assertTrue(tracker.is_active_minute(dt))

        # 07:05 -> True (window boundary)
        dt = datetime(2026, 8, 25, 7, 5, tzinfo=self.rome_tz)
        self.assertTrue(tracker.is_active_minute(dt))

        # 07:06 -> False (outside window)
        dt = datetime(2026, 8, 25, 7, 6, tzinfo=self.rome_tz)
        self.assertFalse(tracker.is_active_minute(dt))

        # 07:20 -> False (outside window)
        dt = datetime(2026, 8, 25, 7, 20, tzinfo=self.rome_tz)
        self.assertFalse(tracker.is_active_minute(dt))

        # 07:25 -> True (start of 25-35 window)
        dt = datetime(2026, 8, 25, 7, 25, tzinfo=self.rome_tz)
        self.assertTrue(tracker.is_active_minute(dt))

        # 07:30 -> True (mid 25-35 window)
        dt = datetime(2026, 8, 25, 7, 30, tzinfo=self.rome_tz)
        self.assertTrue(tracker.is_active_minute(dt))

        # 07:35 -> True (end of 25-35 window)
        dt = datetime(2026, 8, 25, 7, 35, tzinfo=self.rome_tz)
        self.assertTrue(tracker.is_active_minute(dt))

        # 07:36 -> False (outside window)
        dt = datetime(2026, 8, 25, 7, 36, tzinfo=self.rome_tz)
        self.assertFalse(tracker.is_active_minute(dt))

        # 22:05 -> True (night end boundary)
        dt = datetime(2026, 8, 25, 22, 5, tzinfo=self.rome_tz)
        self.assertTrue(tracker.is_active_minute(dt))

        # 22:06 -> False (after night end)
        dt = datetime(2026, 8, 25, 22, 6, tzinfo=self.rome_tz)
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
        # When inactive at 07:06:00, next active is 07:25:00 (19 minutes = 1140 seconds)
        dt = datetime(2026, 8, 25, 7, 6, 0, 0, tzinfo=self.rome_tz)
        sleep_sec = tracker.calculate_sleep_seconds(dt)
        self.assertEqual(sleep_sec, 19 * 60)

        # When inactive at 22:10:00, next active is next day 06:55:00
        # 22:10 to 24:00 is 1h50m (110m), + 6h55m (415m) = 525m = 31500 seconds
        dt = datetime(2026, 8, 25, 22, 10, 0, 0, tzinfo=self.rome_tz)
        sleep_sec = tracker.calculate_sleep_seconds(dt)
        self.assertEqual(sleep_sec, (110 + 415) * 60)


class TestParserAndChangeDetection(unittest.TestCase):
    def setUp(self):
        self.sample_html = """
        <html><body>
        <table id="calendario">
            <thead>
                <tr>
                    <th>MODALITÀ</th><th>UNIVERSITÀ</th><th>REGIONE</th><th>CITTÀ</th>
                    <th>FINE ISCRIZIONI</th><th>POSTI</th><th>STATO</th><th>DATA TEST</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td>TOLC@UNI</td>
                    <td>Universita' di Pisa</td>
                    <td>TOSCANA</td>
                    <td>PISA</td>
                    <td>26/08/2026</td>
                    <td>5</td>
                    <td><span style="color: LimeGreen;">POSTI DISPONIBILI</span></td>
                    <td>01/09/2026</td>
                </tr>
                <tr>
                    <td>TOLC@CASA</td>
                    <td>Sapienza Università di Roma</td>
                    <td>LAZIO</td>
                    <td>ROMA</td>
                    <td>26/08/2026</td>
                    <td>---</td>
                    <td><span style="color: Crimson;">POSTI ESAURITI</span></td>
                    <td>01/09/2026</td>
                </tr>
            </tbody>
        </table>
        </body></html>
        """
        self.page_info = {
            "name": "TOLC-I (Ingegneria)",
            "url": "https://testcisia.it/calendario.php?tolc=ingegneria"
        }

    def test_parse_page_rows(self):
        rows = tracker.parse_page_rows(self.sample_html, self.page_info)
        self.assertEqual(len(rows), 2)
        
        row1 = rows[0]
        self.assertEqual(row1["modalita"], "TOLC@UNI")
        self.assertEqual(row1["universita"], "Universita' di Pisa")
        self.assertEqual(row1["citta"], "PISA")
        self.assertEqual(row1["posti"], "5")
        self.assertEqual(row1["stato"], "POSTI DISPONIBILI")
        self.assertEqual(row1["data_test"], "01/09/2026")
        
        row2 = rows[1]
        self.assertEqual(row2["modalita"], "TOLC@CASA")
        self.assertEqual(row2["stato"], "POSTI ESAURITI")

    @patch("tracker.send_notifications")
    @patch("tracker.save_state")
    @patch("tracker.fetch_page")
    def test_first_run_silent_initialization(self, mock_fetch, mock_save, mock_alert):
        mock_fetch.return_value = tracker.parse_page_rows(self.sample_html, self.page_info)
        
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
        # Initial state where Sapienza had POSTI ESAURITI
        parsed = tracker.parse_page_rows(self.sample_html, self.page_info)
        initial_state = {r["key"]: r for r in parsed}

        # Updated HTML where Sapienza becomes POSTI DISPONIBILI
        updated_html = self.sample_html.replace("POSTI ESAURITI", "POSTI DISPONIBILI")
        mock_fetch.return_value = tracker.parse_page_rows(updated_html, self.page_info)

        state, alerts = tracker.run_check_cycle(previous_state=initial_state, is_first_run=False)

        self.assertEqual(alerts, 1)
        mock_alert.assert_called_once()
        args, kwargs = mock_alert.call_args
        self.assertEqual(kwargs["change_type"], "status_change")
        self.assertEqual(kwargs["old_status"], "POSTI ESAURITI")

    @patch("tracker.send_notifications", return_value=True)
    @patch("tracker.save_state")
    @patch("tracker.fetch_page")
    def test_new_available_row_triggers_alert(self, mock_fetch, mock_save, mock_alert):
        parsed = tracker.parse_page_rows(self.sample_html, self.page_info)
        initial_state = {parsed[0]["key"]: parsed[0]}  # only Pisa initially

        # Current returns Pisa + Sapienza (which has POSTI DISPONIBILI)
        updated_html = self.sample_html.replace("POSTI ESAURITI", "POSTI DISPONIBILI")
        mock_fetch.return_value = tracker.parse_page_rows(updated_html, self.page_info)

        state, alerts = tracker.run_check_cycle(previous_state=initial_state, is_first_run=False)

        self.assertEqual(alerts, 1)
        mock_alert.assert_called_once()
        args, kwargs = mock_alert.call_args
        self.assertEqual(kwargs["change_type"], "new")


if __name__ == "__main__":
    unittest.main()
