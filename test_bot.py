#!/usr/bin/env python3
"""
Unit tests for bot.py — verifies wizard flow, user registration, and session guard.
"""

import os
import gc
import unittest
from unittest.mock import patch, MagicMock
import config
import db
from bot import TelegramBot, user_sessions


class TestTelegramBot(unittest.TestCase):
    def setUp(self):
        self.test_db = "test_bot.db"
        db._db_initialized.discard(self.test_db)
        if os.path.exists(self.test_db):
            try:
                os.remove(self.test_db)
            except PermissionError:
                pass
        db.init_db(self.test_db)
        self.bot = TelegramBot(token="12345:dummy_bot_token", db_path=self.test_db)
        user_sessions.clear()

    def tearDown(self):
        gc.collect()
        db._db_initialized.discard(self.test_db)
        user_sessions.clear()
        if os.path.exists(self.test_db):
            try:
                os.remove(self.test_db)
            except PermissionError:
                pass

    @patch.object(TelegramBot, "send_message")
    def test_start_command_registers_user_and_shows_menu(self, mock_send):
        msg = {
            "message_id": 1,
            "from": {"id": 5555, "username": "alice", "first_name": "Alice"},
            "chat": {"id": 5555},
            "text": "/start"
        }
        self.bot.handle_text_message(msg)

        # Verify user is registered in SQLite
        conn = db.get_db_connection(self.test_db)
        user = conn.execute("SELECT * FROM users WHERE user_id = 5555").fetchone()
        conn.close()
        self.assertIsNotNone(user)
        self.assertEqual(user["username"], "alice")

        mock_send.assert_called_once()
        args, kwargs = mock_send.call_args
        self.assertIn("Welcome, Alice!", args[1])

    @patch.object(TelegramBot, "edit_message_text")
    @patch.object(TelegramBot, "answer_callback_query")
    def test_wizard_full_flow(self, mock_answer, mock_edit):
        """Tests the full multi-select exam wizard from start to filter creation."""
        user_id = 5555
        chat_id = 5555
        msg_id = 100

        def _cb(data):
            return {
                "id": f"cb_{data}",
                "from": {"id": user_id, "username": "alice", "first_name": "Alice"},
                "message": {"chat": {"id": chat_id}, "message_id": msg_id},
                "data": data
            }

        # Step 1: Start wizard
        self.bot.handle_callback_query(_cb("wizard_start"))
        self.assertEqual(user_sessions[user_id]["step"], "exam_type")
        self.assertEqual(user_sessions[user_id]["data"]["selected_exams"], [])

        # Step 1: Toggle CEnT-S ON
        self.bot.handle_callback_query(_cb("wiz_toggle_CEnT-S (English)"))
        self.assertIn("CEnT-S (English)", user_sessions[user_id]["data"]["selected_exams"])

        # Step 1: Confirm exam selection
        self.bot.handle_callback_query(_cb("wiz_exam_confirm"))
        self.assertEqual(user_sessions[user_id]["step"], "university")

        # Step 2: Select Any University
        self.bot.handle_callback_query(_cb("wiz_uni_ANY"))
        self.assertEqual(user_sessions[user_id]["data"]["university_query"], "ANY")
        self.assertEqual(user_sessions[user_id]["step"], "date_range")

        # Step 3: Select Next 30 Days
        self.bot.handle_callback_query(_cb("wiz_date_30d"))
        self.assertIsNotNone(user_sessions[user_id]["data"]["start_date"])
        self.assertEqual(user_sessions[user_id]["step"], "duration")

        # Step 4: Select 14 Days duration → finalize
        self.bot.handle_callback_query(_cb("wiz_dur_14"))

        # Session should be cleaned up and filter saved in DB
        self.assertNotIn(user_id, user_sessions)
        filters = db.get_user_filters(user_id, db_path=self.test_db)
        self.assertEqual(len(filters), 1)
        self.assertEqual(filters[0]["exam_type"], "CEnT-S (English)")
        self.assertEqual(filters[0]["university_query"], "ANY")
        self.assertEqual(filters[0]["duration_days"], 14)

    @patch.object(TelegramBot, "edit_message_text")
    @patch.object(TelegramBot, "answer_callback_query")
    def test_wizard_multi_exam_select_all(self, mock_answer, mock_edit):
        """Tests selecting all exams via the Select All button."""
        user_id = 7777
        chat_id = 7777
        msg_id = 200

        def _cb(data):
            return {
                "id": f"cb_{data}",
                "from": {"id": user_id, "username": "bob", "first_name": "Bob"},
                "message": {"chat": {"id": chat_id}, "message_id": msg_id},
                "data": data
            }

        self.bot.handle_callback_query(_cb("wizard_start"))
        self.bot.handle_callback_query(_cb("wiz_exam_all"))
        selected = user_sessions[user_id]["data"]["selected_exams"]
        self.assertEqual(len(selected), 3)  # All 3 exam types selected

        self.bot.handle_callback_query(_cb("wiz_exam_clear"))
        selected = user_sessions[user_id]["data"]["selected_exams"]
        self.assertEqual(len(selected), 0)  # Cleared

    @patch.object(TelegramBot, "edit_message_text")
    @patch.object(TelegramBot, "answer_callback_query")
    def test_session_guard_after_restart(self, mock_answer, mock_edit):
        """Tests that clicking a wizard callback with no session shows a recovery message."""
        user_id = 9999
        chat_id = 9999
        msg_id = 300

        # Simulate clicking 'wiz_exam_confirm' with NO existing session (post-restart scenario)
        q = {
            "id": "cb_orphan",
            "from": {"id": user_id, "username": "carol", "first_name": "Carol"},
            "message": {"chat": {"id": chat_id}, "message_id": msg_id},
            "data": "wiz_exam_confirm"
        }
        # Should NOT crash — should trigger _require_session which starts fresh wizard
        self.bot.handle_callback_query(q)
        # answer_callback_query should be called with the expiry message
        mock_answer.assert_called()


if __name__ == "__main__":
    unittest.main()
