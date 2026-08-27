#!/usr/bin/env python3
"""
Database Persistence Layer for CISIA Personalized Filter Bot.
Handles SQLite operations for users, active filters, alert history, and expiration cycles.
"""

import os
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import logging

import config

logger = logging.getLogger("CISIA-DB")

# Guard flag to avoid repeating CREATE TABLE / makedirs on every call
_db_initialized: set[str] = set()


def get_db_connection(db_path: str = None) -> sqlite3.Connection:
    """Returns a thread-safe sqlite3 connection with Row factory and WAL mode."""
    path = db_path or getattr(config, "DB_PATH", "subscriptions.db")
    # check_same_thread=False is safe because WAL mode handles concurrent readers/writers
    conn = sqlite3.connect(path, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db(db_path: str = None):
    """Initializes SQLite tables if they do not already exist. Called once at startup."""
    path = db_path or getattr(config, "DB_PATH", "subscriptions.db")
    # Skip if already initialized AND the file still exists on disk
    if path in _db_initialized and os.path.exists(path):
        return

    parent_dir = os.path.dirname(os.path.abspath(path))
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)

    conn = get_db_connection(path)
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                created_at TEXT NOT NULL,
                is_active INTEGER DEFAULT 1
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS filters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                exam_type TEXT NOT NULL,
                university_query TEXT NOT NULL DEFAULT 'ANY',
                start_date TEXT,
                end_date TEXT,
                duration_days INTEGER,
                expires_at TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                last_alert_at TEXT,
                FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_filters_user ON filters(user_id);
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_filters_status ON filters(status);
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS alert_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filter_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                seat_key TEXT NOT NULL,
                sent_at TEXT NOT NULL,
                FOREIGN KEY(filter_id) REFERENCES filters(id) ON DELETE CASCADE
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_alerts_lookup ON alert_history(filter_id, seat_key);
        """)
    conn.close()
    _db_initialized.add(path)
    logger.info(f"Database initialized at: {path}")


def purge_old_alert_history(db_path: str = None, days: int = 7):
    """
    Deletes alert_history records older than `days` days.
    Called periodically to prevent unbounded table growth.
    """
    cutoff = (datetime.now(ZoneInfo(config.TIMEZONE)) - timedelta(days=days)).isoformat()
    conn = get_db_connection(db_path)
    with conn:
        cursor = conn.execute(
            "DELETE FROM alert_history WHERE sent_at < ?", (cutoff,)
        )
        if cursor.rowcount > 0:
            logger.info(f"Purged {cursor.rowcount} old alert_history rows (older than {days} days).")
    conn.close()


def register_or_update_user(user_id: int, username: str = "", first_name: str = "", db_path: str = None) -> dict:
    """Registers a new user or updates their profile info."""
    init_db(db_path)
    conn = get_db_connection(db_path)
    now_iso = datetime.now(ZoneInfo(config.TIMEZONE)).isoformat()
    with conn:
        conn.execute("""
            INSERT INTO users (user_id, username, first_name, created_at, is_active)
            VALUES (?, ?, ?, ?, 1)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name,
                is_active = 1
        """, (user_id, username or "", first_name or "", now_iso))
    conn.close()
    return {"user_id": user_id, "username": username, "first_name": first_name}


def create_filter(
    user_id: int,
    exam_type: str,
    university_query: str = "ANY",
    start_date: str = None,
    end_date: str = None,
    duration_days: int = None,
    db_path: str = None
) -> int:
    """
    Creates a new filter subscription for a user.
    exam_type may be a comma-separated list for multi-exam tracking.
    Calculates expires_at based on duration_days or end_date.
    """
    init_db(db_path)
    now_rome = datetime.now(ZoneInfo(config.TIMEZONE))
    now_iso = now_rome.isoformat()

    expires_at = None
    if duration_days and duration_days > 0:
        expires_at = (now_rome + timedelta(days=duration_days)).isoformat()
    elif end_date:
        try:
            ed = datetime.strptime(end_date, "%Y-%m-%d").replace(
                hour=23, minute=59, second=59, tzinfo=ZoneInfo(config.TIMEZONE)
            )
            expires_at = ed.isoformat()
        except Exception:
            expires_at = None

    conn = get_db_connection(db_path)
    with conn:
        cursor = conn.execute("""
            INSERT INTO filters (
                user_id, exam_type, university_query, start_date, end_date,
                duration_days, expires_at, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?)
        """, (
            user_id, exam_type, university_query, start_date, end_date,
            duration_days, expires_at, now_iso
        ))
        filter_id = cursor.lastrowid
    conn.close()
    return filter_id


def get_user_filters(user_id: int, include_inactive: bool = True, db_path: str = None) -> list[dict]:
    """Retrieves all filters configured by a user."""
    init_db(db_path)
    conn = get_db_connection(db_path)
    query = "SELECT * FROM filters WHERE user_id = ?"
    params = [user_id]
    if not include_inactive:
        query += " AND status = 'active'"
    query += " ORDER BY id DESC"

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_filter_by_id(filter_id: int, db_path: str = None) -> dict | None:
    """Retrieves a single filter by ID."""
    init_db(db_path)
    conn = get_db_connection(db_path)
    row = conn.execute("SELECT * FROM filters WHERE id = ?", (filter_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_filter_status(filter_id: int, user_id: int, status: str, db_path: str = None) -> bool:
    """Updates status ('active', 'paused', 'expired') for a filter."""
    init_db(db_path)
    conn = get_db_connection(db_path)
    with conn:
        cursor = conn.execute("""
            UPDATE filters SET status = ? WHERE id = ? AND user_id = ?
        """, (status, filter_id, user_id))
        updated = cursor.rowcount > 0
    conn.close()
    return updated


def delete_filter(filter_id: int, user_id: int, db_path: str = None) -> bool:
    """Deletes a filter and its associated alert history."""
    init_db(db_path)
    conn = get_db_connection(db_path)
    with conn:
        cursor = conn.execute("""
            DELETE FROM filters WHERE id = ? AND user_id = ?
        """, (filter_id, user_id))
        deleted = cursor.rowcount > 0
    conn.close()
    return deleted


def renew_filter(filter_id: int, user_id: int, additional_days: int = 14, db_path: str = None) -> dict | None:
    """Renews an expired or active filter by adding additional_days from now."""
    init_db(db_path)
    now_rome = datetime.now(ZoneInfo(config.TIMEZONE))
    new_expires_at = (now_rome + timedelta(days=additional_days)).isoformat()
    conn = get_db_connection(db_path)
    with conn:
        cursor = conn.execute("""
            UPDATE filters
            SET status = 'active',
                duration_days = ?,
                expires_at = ?
            WHERE id = ? AND user_id = ?
        """, (additional_days, new_expires_at, filter_id, user_id))
        updated = cursor.rowcount > 0
    conn.close()
    if updated:
        return get_filter_by_id(filter_id, db_path)
    return None


def get_all_active_filters(db_path: str = None) -> list[dict]:
    """Retrieves all currently active filters across all users."""
    init_db(db_path)
    conn = get_db_connection(db_path)
    rows = conn.execute("""
        SELECT f.*, u.username, u.first_name
        FROM filters f
        JOIN users u ON f.user_id = u.user_id
        WHERE f.status = 'active' AND u.is_active = 1
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def check_and_expire_filters(db_path: str = None) -> list[dict]:
    """
    Marks any expired active filters as 'expired' and returns them.
    Also triggers periodic alert_history cleanup every ~100 calls (probabilistic).
    """
    init_db(db_path)
    now_rome = datetime.now(ZoneInfo(config.TIMEZONE))
    now_iso = now_rome.isoformat()

    conn = get_db_connection(db_path)
    rows = conn.execute("""
        SELECT f.*, u.username, u.first_name
        FROM filters f
        JOIN users u ON f.user_id = u.user_id
        WHERE f.status = 'active'
          AND f.expires_at IS NOT NULL
          AND f.expires_at <= ?
    """, (now_iso,)).fetchall()

    expired_filters = [dict(r) for r in rows]

    if expired_filters:
        expired_ids = [f["id"] for f in expired_filters]
        with conn:
            conn.executemany(
                "UPDATE filters SET status = 'expired' WHERE id = ?",
                [(fid,) for fid in expired_ids]
            )
        logger.info(f"Marked {len(expired_filters)} filters as expired: {expired_ids}")

    conn.close()

    # Probabilistic cleanup: ~1% chance per cycle to purge old alert_history
    import random
    if random.random() < 0.01:
        try:
            purge_old_alert_history(db_path=db_path, days=7)
        except Exception as e:
            logger.warning(f"Alert history cleanup failed: {e}")

    return expired_filters


def should_send_alert(
    filter_id: int,
    user_id: int,
    seat_key: str,
    cooldown_seconds: int = None,
    db_path: str = None
) -> bool:
    """Checks if an alert for this seat_key has already been sent to this user/filter recently."""
    init_db(db_path)
    cooldown = cooldown_seconds if cooldown_seconds is not None else getattr(config, "ALERT_COOLDOWN_SECONDS", 3600)
    now_rome = datetime.now(ZoneInfo(config.TIMEZONE))
    cutoff_time = (now_rome - timedelta(seconds=cooldown)).isoformat()

    conn = get_db_connection(db_path)
    row = conn.execute("""
        SELECT sent_at FROM alert_history
        WHERE filter_id = ? AND seat_key = ? AND sent_at >= ?
        ORDER BY sent_at DESC LIMIT 1
    """, (filter_id, seat_key, cutoff_time)).fetchone()
    conn.close()
    return row is None


def record_alert_sent(filter_id: int, user_id: int, seat_key: str, db_path: str = None):
    """Records an alert dispatch into alert_history and updates filter's last_alert_at."""
    init_db(db_path)
    now_iso = datetime.now(ZoneInfo(config.TIMEZONE)).isoformat()
    conn = get_db_connection(db_path)
    try:
        with conn:
            conn.execute("""
                INSERT INTO alert_history (filter_id, user_id, seat_key, sent_at)
                VALUES (?, ?, ?, ?)
            """, (filter_id, user_id, seat_key, now_iso))
            conn.execute("""
                UPDATE filters SET last_alert_at = ? WHERE id = ?
            """, (now_iso, filter_id))
    except Exception as e:
        # Filter may have been deleted between should_send_alert and record_alert_sent
        logger.warning(f"Could not record alert for filter #{filter_id} (may have been deleted): {e}")
    conn.close()
