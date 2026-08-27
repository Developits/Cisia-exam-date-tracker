import os
import gc
import unittest
from unittest.mock import patch, MagicMock
import config
import db
import dispatcher


class TestDispatcher(unittest.TestCase):
    def setUp(self):
        self.test_db = "test_dispatcher.db"
        db._db_initialized.discard(self.test_db)
        if os.path.exists(self.test_db):
            try:
                os.remove(self.test_db)
            except PermissionError:
                pass
        db.init_db(self.test_db)
        db.register_or_update_user(1001, "student1", "Student", db_path=self.test_db)

    def tearDown(self):
        gc.collect()
        db._db_initialized.discard(self.test_db)
        if os.path.exists(self.test_db):
            try:
                os.remove(self.test_db)
            except PermissionError:
                pass

    @patch("dispatcher.send_bot_message", return_value=True)
    def test_dispatch_personalized_alerts(self, mock_send):
        # Create a filter for CEnT-S at Sapienza in August-September 2026
        fid = db.create_filter(
            user_id=1001,
            exam_type="CEnT-S (English)",
            university_query="Sapienza",
            start_date="2026-08-10",
            end_date="2026-09-15",
            duration_days=30,
            db_path=self.test_db
        )

        sample_row = {
            "key": "CEnT-S (English)|CENT@HOME|Sapienza University of Rome|ROME|15/08/2026|01/08/2026#1",
            "test_type": "CEnT-S (English)",
            "format": "CENT@HOME",
            "university": "Sapienza University of Rome",
            "city": "ROME",
            "region": "LAZIO",
            "date": "15/08/2026",
            "seats": "10",
            "deadline": "01/08/2026",
            "state": "AVAILABLE SEATS"
        }

        with patch("config.FILTER_BOT_TOKEN", "dummy_token"):
            # First alert should trigger send
            alerts = dispatcher.dispatch_personalized_alerts(sample_row, change_type="new", db_path=self.test_db)
            self.assertEqual(alerts, 1)
            mock_send.assert_called_once()

            # Second immediate identical alert should be throttled by anti-spam cooldown
            alerts2 = dispatcher.dispatch_personalized_alerts(sample_row, change_type="new", db_path=self.test_db)
            self.assertEqual(alerts2, 0)

    def test_immediate_search_matches(self):
        filter_dict = {
            "exam_type": "TOLC-I (Engineering)",
            "university_query": "Pisa",
            "start_date": "2026-09-01",
            "end_date": "2026-09-30"
        }

        mock_state = {
            "row1": {
                "key": "row1",
                "test_type": "TOLC-I (Engineering)",
                "format": "TOLC@HOME",
                "university": "University of Pisa",
                "city": "PISA",
                "region": "TUSCANY",
                "date": "15/09/2026",
                "seats": "5",
                "state": "AVAILABLE SEATS"
            },
            "row2": {
                "key": "row2",
                "test_type": "TOLC-I (Engineering)",
                "format": "TOLC@HOME",
                "university": "Sapienza University of Rome",
                "city": "ROME",
                "region": "LAZIO",
                "date": "15/09/2026",
                "seats": "10",
                "state": "AVAILABLE SEATS"
            }
        }

        matches = dispatcher.search_immediate_matches(filter_dict, mock_state)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["university"], "University of Pisa")


if __name__ == "__main__":
    unittest.main()
