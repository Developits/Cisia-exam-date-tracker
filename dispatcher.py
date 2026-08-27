#!/usr/bin/env python3
"""
Personalized Alert Dispatcher for CISIA Filter Bot.
Evaluates newly open seats against all active user subscriptions and delivers instant push notifications.
"""

import html
import time
import logging
import requests
from zoneinfo import ZoneInfo
from datetime import datetime

import config
import db
import matcher

logger = logging.getLogger("CISIA-Dispatcher")

http_session = requests.Session()


def send_bot_message(token: str, chat_id: int | str, text: str, reply_markup: dict = None) -> bool:
    """Sends an HTML formatted message to a Telegram chat via Bot API."""
    if not token or not chat_id:
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    try:
        res = http_session.post(url, json=payload, timeout=10)
        res.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"Failed to send Telegram message to chat_id '{chat_id}': {e}")
        return False


def dispatch_personalized_alerts(row: dict, change_type: str, old_status: str = "", db_path: str = None) -> int:
    """
    Evaluates a seat row against all active user filters in SQLite.
    Delivers personalized alerts to matching users with anti-spam cooldowns.
    """
    token = config.FILTER_BOT_TOKEN
    if not token:
        return 0

    active_filters = db.get_all_active_filters(db_path=db_path)
    if not active_filters:
        return 0

    alerts_sent = 0

    for f in active_filters:
        if not matcher.row_matches_filter(row, f):
            continue

        filter_id = f["id"]
        user_id = f["user_id"]
        seat_key = row.get("key", "")

        # Check anti-spam cooldown
        if not db.should_send_alert(filter_id, user_id, seat_key, db_path=db_path):
            logger.info(f"Suppressed duplicate alert for user {user_id} on filter #{filter_id} (seat: {seat_key})")
            continue

        if change_type == "new":
            reason_text = "✨ <b>New test date opened with available seats!</b>"
        else:
            escaped_old = html.escape(old_status) if old_status else "NOT AVAILABLE"
            reason_text = f"🔄 <b>Status updated:</b> <s>{escaped_old}</s> ➔ <b>AVAILABLE SEATS</b>"

        date_window_str = ""
        if f.get("start_date") or f.get("end_date"):
            start_d = f.get("start_date") or "Any"
            end_d = f.get("end_date") or "Any"
            date_window_str = f" • 📅 {start_d} to {end_d}"

        # Format comma-separated exam types for display
        exam_display = html.escape(f["exam_type"].replace(",", " / "))

        message = (
            f"🚨 <b>MATCHING CISIA SEAT AVAILABLE!</b>\n\n"
            f"🎯 <i>Matches your filter #{filter_id} ({exam_display} • 🏛 {html.escape(f['university_query'])}{date_window_str})</i>\n\n"
            f"{reason_text}\n\n"
            f"🏛 <b>University:</b> {html.escape(row['university'])}\n"
            f"💻 <b>Format:</b> {html.escape(row['format'])}\n"
            f"📍 <b>City:</b> {html.escape(row['city'])} ({html.escape(row['region'])})\n"
            f"📅 <b>Test Date:</b> {html.escape(row['date'])}\n"
            f"🎟 <b>Seats:</b> {html.escape(row['seats'])}\n"
            f"⏳ <b>Bookings Deadline:</b> {html.escape(row['deadline'])}\n"
            f"⚡️ <b>State:</b> {html.escape(row['state'])}"
        )

        reply_markup = {
            "inline_keyboard": [
                [
                    {"text": "🚀 Book on CISIA", "url": config.CISIA_LOGIN_URL},
                    {"text": "📅 Open Calendar", "url": row.get("url", config.TRACKED_PAGES[0]["url"])}
                ],
                [
                    {"text": "📋 My Active Trackers", "callback_data": "menu_mytrackers"}
                ]
            ]
        }

        if send_bot_message(token, user_id, message, reply_markup):
            db.record_alert_sent(filter_id, user_id, seat_key, db_path=db_path)
            alerts_sent += 1
            logger.info(f"Personalized alert delivered to user {user_id} for filter #{filter_id}")
            time.sleep(0.1)  # Respect rate limits

    return alerts_sent


def dispatch_expiration_alerts(expired_filters: list[dict], db_path: str = None) -> int:
    """Sends notification to users whose filters just expired with 1-click renewal buttons."""
    token = config.FILTER_BOT_TOKEN
    if not token or not expired_filters:
        return 0

    sent = 0
    for f in expired_filters:
        fid = f["id"]
        user_id = f["user_id"]
        msg = (
            f"⏳ <b>Tracker Filter Expired</b>\n\n"
            f"Your active tracker <b>#{fid}</b> for <b>{html.escape(f['exam_type'])}</b> (🏛 {html.escape(f['university_query'])}) has reached its time limit.\n\n"
            f"Tap below to extend or manage your trackers:"
        )

        reply_markup = {
            "inline_keyboard": [
                [
                    {"text": "🔄 Extend +14 Days", "callback_data": f"renew_{fid}_14"},
                    {"text": "🔄 Extend +30 Days", "callback_data": f"renew_{fid}_30"}
                ],
                [
                    {"text": "🗑 Delete Tracker", "callback_data": f"del_{fid}"},
                    {"text": "📋 My Trackers", "callback_data": "menu_mytrackers"}
                ]
            ]
        }

        if send_bot_message(token, user_id, msg, reply_markup):
            sent += 1
            time.sleep(0.1)

    return sent


def search_immediate_matches(filter_dict: dict, current_state: dict[str, dict]) -> list[dict]:
    """
    Scans the current parsed state for any open seats matching the given filter.
    Returns list of matching row dicts.
    """
    matches = []
    if not current_state:
        return matches

    for row in current_state.values():
        st = (row.get("state") or "").upper()
        if "AVAILABLE SEATS" not in st and "POSTI DISPONIBILI" not in st:
            continue
        if matcher.row_matches_filter(row, filter_dict):
            matches.append(row)

    return matches
