import os
import gc
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import config
import db


class TestDB(unittest.TestCase):
    def setUp(self):
        self.test_db = "test_subscriptions.db"
        # Remove guard so init_db reinitializes fresh tables for each test
        db._db_initialized.discard(self.test_db)
        if os.path.exists(self.test_db):
            try:
                os.remove(self.test_db)
            except PermissionError:
                pass
        db.init_db(self.test_db)

    def tearDown(self):
        gc.collect()  # Force close any lingering SQLite connections on Windows
        db._db_initialized.discard(self.test_db)
        if os.path.exists(self.test_db):
            try:
                os.remove(self.test_db)
            except PermissionError:
                pass  # Will be cleaned up on next setUp

    def test_user_registration_and_filter_crud(self):
        # Register user
        user = db.register_or_update_user(12345, "john_doe", "John", db_path=self.test_db)
        self.assertEqual(user["user_id"], 12345)

        # Create filter
        f_id = db.create_filter(
            user_id=12345,
            exam_type="CEnT-S (English)",
            university_query="Sapienza",
            start_date="2026-08-10",
            end_date="2026-09-15",
            duration_days=14,
            db_path=self.test_db
        )
        self.assertGreater(f_id, 0)

        # Get user filters
        filters = db.get_user_filters(12345, db_path=self.test_db)
        self.assertEqual(len(filters), 1)
        self.assertEqual(filters[0]["exam_type"], "CEnT-S (English)")
        self.assertEqual(filters[0]["status"], "active")

        # Pause filter
        db.update_filter_status(f_id, 12345, "paused", db_path=self.test_db)
        active_filters = db.get_user_filters(12345, include_inactive=False, db_path=self.test_db)
        self.assertEqual(len(active_filters), 0)

        # Resume filter
        db.update_filter_status(f_id, 12345, "active", db_path=self.test_db)
        active_filters = db.get_user_filters(12345, include_inactive=False, db_path=self.test_db)
        self.assertEqual(len(active_filters), 1)

        # Delete filter
        deleted = db.delete_filter(f_id, 12345, db_path=self.test_db)
        self.assertTrue(deleted)
        filters_after = db.get_user_filters(12345, db_path=self.test_db)
        self.assertEqual(len(filters_after), 0)

    def test_alert_deduplication(self):
        db.register_or_update_user(999, "alert_user", "Tester", db_path=self.test_db)
        f_id = db.create_filter(999, "TOLC-I (Engineering)", "Pisa", db_path=self.test_db)
        seat_key = "TOLC-I|TOLC@HOME|Pisa|PISA|15/09/2026#1"

        # Initially should send
        self.assertTrue(db.should_send_alert(f_id, 999, seat_key, cooldown_seconds=3600, db_path=self.test_db))

        # Record alert
        db.record_alert_sent(f_id, 999, seat_key, db_path=self.test_db)

        # Cooldown check should now be False
        self.assertFalse(db.should_send_alert(f_id, 999, seat_key, cooldown_seconds=3600, db_path=self.test_db))

    def test_expiration_and_renewal(self):
        db.register_or_update_user(888, "expire_user", "Exp", db_path=self.test_db)
        f_id = db.create_filter(
            user_id=888,
            exam_type="TOLC-E (Economics)",
            university_query="Bologna",
            duration_days=1,
            db_path=self.test_db
        )

        # Manually force expires_at to the past
        past_iso = (datetime.now(ZoneInfo(config.TIMEZONE)) - timedelta(hours=2)).isoformat()
        conn = db.get_db_connection(self.test_db)
        with conn:
            conn.execute("UPDATE filters SET expires_at = ? WHERE id = ?", (past_iso, f_id))
        conn.close()

        # Check and expire
        expired = db.check_and_expire_filters(db_path=self.test_db)
        self.assertEqual(len(expired), 1)
        self.assertEqual(expired[0]["id"], f_id)

        # Status should now be expired
        f = db.get_filter_by_id(f_id, db_path=self.test_db)
        self.assertEqual(f["status"], "expired")

        # Renew
        renewed = db.renew_filter(f_id, 888, additional_days=14, db_path=self.test_db)
        self.assertIsNotNone(renewed)
        self.assertEqual(renewed["status"], "active")


if __name__ == "__main__":
    unittest.main()
