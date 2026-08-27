#!/usr/bin/env python3
"""
Unit tests for bot.py
"""

import os
import unittest
from unittest.mock import patch, MagicMock
import config
import db
from bot import TelegramBot, user_sessions


class TestTelegramBot(unittest.TestCase):
    def setUp(self):
        self.test_db = "test_bot.db"
        if os.path.exists(self.test_db):
            os.remove(self.test_db)
        db.init_db(self.test_db)
        self.bot = TelegramBot(token="12345:dummy_bot_token", db_path=self.test_db)
        user_sessions.clear()

    def tearDown(self):
        if os.path.exists(self.test_db):
            os.remove(self.test_db)
        user_sessions.clear()

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
        user_id = 5555
        chat_id = 5555
        msg_id = 100

        # 1. Start wizard
        q1 = {
            "id": "cb1",
            "from": {"id": user_id, "username": "alice", "first_name": "Alice"},
            "message": {"chat": {"id": chat_id}, "message_id": msg_id},
            "data": "wizard_start"
        }
        self.bot.handle_callback_query(q1)
        self.assertEqual(user_sessions[user_id]["step"], "exam_type")

        # 2. Select Exam (CEnT-S)
        q2 = {
            "id": "cb2",
            "from": {"id": user_id},
            "message": {"chat": {"id": chat_id}, "message_id": msg_id},
            "data": "wiz_exam_CEnT-S (English)"
        }
        self.bot.handle_callback_query(q2)
        self.assertEqual(user_sessions[user_id]["data"]["exam_type"], "CEnT-S (English)")
        self.assertEqual(user_sessions[user_id]["step"], "university")

        # 3. Select University (Sapienza)
        q3 = {
            "id": "cb3",
            "from": {"id": user_id},
            "message": {"chat": {"id": chat_id}, "message_id": msg_id},
            "data": "wiz_uni_Sapienza"
        }
        self.bot.handle_callback_query(q3)
        self.assertEqual(user_sessions[user_id]["data"]["university_query"], "Sapienza")
        self.assertEqual(user_sessions[user_id]["step"], "date_range")

        # 4. Select Date (Next 30 Days)
        q4 = {
            "id": "cb4",
            "from": {"id": user_id},
            "message": {"chat": {"id": chat_id}, "message_id": msg_id},
            "data": "wiz_date_30d"
        }
        self.bot.handle_callback_query(q4)
        self.assertIsNotNone(user_sessions[user_id]["data"]["start_date"])
        self.assertEqual(user_sessions[user_id]["step"], "duration")

        # 5. Select Duration (14 Days) -> Finalize
        q5 = {
            "id": "cb5",
            "from": {"id": user_id},
            "message": {"chat": {"id": chat_id}, "message_id": msg_id},
            "data": "wiz_dur_14"
        }
        self.bot.handle_callback_query(q5)

        # User session should be cleaned up and filter saved in DB
        self.assertNotIn(user_id, user_sessions)
        filters = db.get_user_filters(user_id, db_path=self.test_db)
        self.assertEqual(len(filters), 1)
        self.assertEqual(filters[0]["exam_type"], "CEnT-S (English)")
        self.assertEqual(filters[0]["university_query"], "Sapienza")
        self.assertEqual(filters[0]["duration_days"], 14)


if __name__ == "__main__":
    unittest.main()
