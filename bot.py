#!/usr/bin/env python3
"""
Interactive Telegram Bot for CISIA Custom Seat Filters.
Provides an interactive Inline Keyboard Wizard for setting up custom exam filters,
managing active trackers, immediate availability lookups, and receiving push notifications.

Wizard Flow:
  Step 1 — Exam Type (multi-select toggle checkboxes, comma-separated OR logic)
  Step 2 — University (Any / Type custom name with word-boundary fuzzy match)
  Step 3 — Date Range (presets or custom text input)
  Step 4 — Duration (7/14/30/60 days or indefinite)
  → Finalize: save to DB + immediate seat scan
"""

import sys
import os
import json
import html
import time
import logging
import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import requests

import config
import db
import matcher
import dispatcher

logger = logging.getLogger("CISIA-Bot")

# In-memory wizard conversation state: {user_id: {step, data, msg_id}}
# NOTE: This is reset on process restart (Render redeploys). Wizard state is intentionally ephemeral.
user_sessions: dict[int, dict] = {}

# All exam types available for tracking
EXAM_TYPES = [
    "TOLC-I (Engineering)",
    "TOLC-E (Economics)",
    "CEnT-S (English)",
]

# Maximum message length Telegram allows (4096 chars); we target a safe margin
_TELEGRAM_MAX_CHARS = 3900


def _truncate_for_telegram(text: str, max_chars: int = _TELEGRAM_MAX_CHARS) -> str:
    """Truncates a message to stay under Telegram's 4096-char limit."""
    if len(text) <= max_chars:
        return text
    suffix = "\n\n<i>...message truncated to fit Telegram limits. Use /mytrackers to view all.</i>"
    return text[:max_chars - len(suffix)] + suffix


class TelegramBot:
    def __init__(self, token: str = None, db_path: str = None):
        self.token = token or config.FILTER_BOT_TOKEN
        self.db_path = db_path or getattr(config, "DB_PATH", "subscriptions.db")
        self.http = requests.Session()
        self.running = False
        self.last_update_id = 0
        self._thread = None

    def api_call(self, method: str, payload: dict = None, timeout: int = 15) -> dict | None:
        """Executes a Telegram Bot API request."""
        if not self.token:
            return None
        url = f"https://api.telegram.org/bot{self.token}/{method}"
        try:
            res = self.http.post(url, json=payload or {}, timeout=timeout)
            if res.status_code == 409:
                # 409 Conflict occurs briefly during Render zero-downtime deploys while the previous container terminates
                logger.info(f"Telegram polling session conflict (409) on {method} — waiting for previous instance to exit...")
                time.sleep(3)
                return None
            res.raise_for_status()
            data = res.json()
            if data.get("ok"):
                return data.get("result")
            logger.warning(f"Telegram API returned error for {method}: {data}")
            return None
        except Exception as e:
            if "409" not in str(e):
                logger.error(f"Error calling Telegram API {method}: {e}")
            return None

    def send_message(self, chat_id: int | str, text: str, reply_markup: dict = None) -> dict | None:
        """Sends an HTML formatted message (auto-truncated to Telegram limits)."""
        payload = {
            "chat_id": chat_id,
            "text": _truncate_for_telegram(text),
            "parse_mode": "HTML",
            "disable_web_page_preview": False
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return self.api_call("sendMessage", payload)

    def edit_message_text(self, chat_id: int | str, message_id: int, text: str, reply_markup: dict = None) -> dict | None:
        """Edits an existing message's text and markup (auto-truncated to Telegram limits)."""
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": _truncate_for_telegram(text),
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return self.api_call("editMessageText", payload)

    def answer_callback_query(self, callback_query_id: str, text: str = None, show_alert: bool = False):
        """Acknowledges a callback button click."""
        payload = {
            "callback_query_id": callback_query_id,
            "show_alert": show_alert
        }
        if text:
            payload["text"] = text
        self.api_call("answerCallbackQuery", payload)

    # ---------------------------------------------------------
    # UI Screens & Wizards
    # ---------------------------------------------------------

    def show_main_menu(self, chat_id: int, user_info: dict, message_id: int = None):
        """Displays the home dashboard menu."""
        first_name = html.escape(user_info.get("first_name", "Student"))
        text = (
            f"👋 <b>Welcome, {first_name}!</b>\n\n"
            f"🎓 <b>CISIA TOLC & CENT Seat Availability Tracker</b>\n"
            f"Set up personalized filters to get notified the second your target exam opens!\n\n"
            f"✨ <b>What would you like to do?</b>"
        )
        markup = {
            "inline_keyboard": [
                [
                    {"text": "➕ Set Up New Tracker", "callback_data": "wizard_start"}
                ],
                [
                    {"text": "📋 My Active Trackers", "callback_data": "menu_mytrackers"},
                    {"text": "🔍 Instant Seat Check", "callback_data": "menu_check"}
                ],
                [
                    {"text": "ℹ️ How It Works", "callback_data": "menu_help"}
                ]
            ]
        }
        if message_id:
            self.edit_message_text(chat_id, message_id, text, markup)
        else:
            self.send_message(chat_id, text, markup)

    def show_help(self, chat_id: int, message_id: int = None):
        """Displays instructions and help screen."""
        text = (
            f"ℹ️ <b>How CISIA Tracker Works</b>\n\n"
            f"1. <b>Continuous Monitoring:</b> We check official CISIA calendars every <b>1 minute</b> (06:00 to 22:00 Rome time).\n"
            f"2. <b>Personalized Filters:</b> Pick your exact exam (TOLC-I, TOLC-E, CEnT-S), university, and test date range.\n"
            f"3. <b>Home-based Focus:</b> We strictly monitor <code>TOLC@HOME</code> and <code>CENT@HOME</code> tests.\n"
            f"4. <b>Instant Booking:</b> When seats appear, you get an alert with a direct 1-click booking link.\n"
            f"5. <b>Control:</b> Set how long you want to track (7-60 days or until stopped), pause, or delete anytime."
        )
        markup = {
            "inline_keyboard": [
                [{"text": "➕ Set Up Tracker Now", "callback_data": "wizard_start"}],
                [{"text": "🏠 Main Menu", "callback_data": "menu_main"}]
            ]
        }
        if message_id:
            self.edit_message_text(chat_id, message_id, text, markup)
        else:
            self.send_message(chat_id, text, markup)

    # ---------------------------------------------------------
    # Wizard Step 1: Multi-select Exam Type
    # ---------------------------------------------------------

    def _build_exam_type_markup(self, selected: list[str]) -> dict:
        """Builds the toggle checkbox keyboard for exam type selection."""
        buttons = []
        for exam in EXAM_TYPES:
            is_on = exam in selected
            icon = "☑️" if is_on else "☐"
            buttons.append([{"text": f"{icon} {exam}", "callback_data": f"wiz_toggle_{exam}"}])

        # Quick-select row
        buttons.append([
            {"text": "✨ Select All", "callback_data": "wiz_exam_all"},
            {"text": "🗑 Clear All", "callback_data": "wiz_exam_clear"}
        ])

        # Confirm (only enabled if at least one is selected)
        if selected:
            buttons.append([{"text": f"Done → ({len(selected)} selected)", "callback_data": "wiz_exam_confirm"}])
        else:
            buttons.append([{"text": "⚠️ Select at least one exam", "callback_data": "wiz_noop"}])

        buttons.append([{"text": "❌ Cancel", "callback_data": "menu_main"}])
        return {"inline_keyboard": buttons}

    def start_wizard(self, chat_id: int, user_id: int, message_id: int = None):
        """Step 1: Select Exam Type (multi-select toggle checkboxes)."""
        user_sessions[user_id] = {
            "step": "exam_type",
            "data": {"selected_exams": []}
        }
        text = (
            f"🎓 <b>Step 1/4: Choose Exam Type(s)</b>\n\n"
            f"Tap to toggle each exam type you want to track.\n"
            f"You can select <b>multiple</b> exam types in one tracker!"
        )
        markup = self._build_exam_type_markup([])
        if message_id:
            self.edit_message_text(chat_id, message_id, text, markup)
        else:
            self.send_message(chat_id, text, markup)

    def _refresh_exam_type_screen(self, chat_id: int, user_id: int, message_id: int):
        """Re-renders the exam type step with current toggle state."""
        sess = user_sessions.get(user_id, {})
        selected = sess.get("data", {}).get("selected_exams", [])
        text = (
            f"🎓 <b>Step 1/4: Choose Exam Type(s)</b>\n\n"
            f"Tap to toggle each exam type you want to track.\n"
            f"You can select <b>multiple</b> exam types in one tracker!"
        )
        markup = self._build_exam_type_markup(selected)
        self.edit_message_text(chat_id, message_id, text, markup)

    # ---------------------------------------------------------
    # Wizard Step 2: University (Any / Type Custom)
    # ---------------------------------------------------------

    def show_university_step(self, chat_id: int, user_id: int, message_id: int):
        """Step 2: Select University."""
        sess = user_sessions.get(user_id, {})
        sess["step"] = "university"
        exams_str = ", ".join(sess.get("data", {}).get("selected_exams", [])) or "All Exams"

        text = (
            f"🏛 <b>Step 2/4: Choose University</b>\n\n"
            f"Target Exam(s): <b>{html.escape(exams_str)}</b>\n\n"
            f"Select <b>Any University</b> to track all locations, or type a specific university name:"
        )
        markup = {
            "inline_keyboard": [
                [
                    {"text": "🌐 Any University (All Locations)", "callback_data": "wiz_uni_ANY"}
                ],
                [
                    {"text": "✏️ Type University Name", "callback_data": "wiz_uni_custom"}
                ],
                [
                    {"text": "🔙 Back", "callback_data": "wizard_start"}
                ]
            ]
        }
        self.edit_message_text(chat_id, message_id, text, markup)

    # ---------------------------------------------------------
    # Wizard Step 3: Date Range
    # ---------------------------------------------------------

    def show_date_range_step(self, chat_id: int, user_id: int, message_id: int = None):
        """Step 3: Select Date Range."""
        sess = user_sessions.get(user_id, {})
        sess["step"] = "date_range"
        data = sess.get("data", {})
        exams_str = ", ".join(data.get("selected_exams", [])) or "All Exams"

        text = (
            f"📅 <b>Step 3/4: Choose Exam Date Range</b>\n\n"
            f"• Exam(s): <b>{html.escape(exams_str)}</b>\n"
            f"• University: <b>{html.escape(data.get('university_query', 'Any'))}</b>\n\n"
            f"Which test dates are you interested in?"
        )
        markup = {
            "inline_keyboard": [
                [
                    {"text": "🌟 Any Upcoming Date", "callback_data": "wiz_date_any"}
                ],
                [
                    {"text": "📅 Next 30 Days", "callback_data": "wiz_date_30d"},
                    {"text": "📅 Next 60 Days", "callback_data": "wiz_date_60d"}
                ],
                [
                    {"text": "🗓 August – September", "callback_data": "wiz_date_aug_sep"}
                ],
                [
                    {"text": "✏️ Type Custom Date Range", "callback_data": "wiz_date_custom"}
                ],
                [
                    {"text": "🔙 Back", "callback_data": "wiz_back_to_uni"}
                ]
            ]
        }
        if message_id:
            self.edit_message_text(chat_id, message_id, text, markup)
        else:
            self.send_message(chat_id, text, markup)

    # ---------------------------------------------------------
    # Wizard Step 4: Duration
    # ---------------------------------------------------------

    def show_duration_step(self, chat_id: int, user_id: int, message_id: int = None):
        """Step 4: Select Tracker Duration."""
        sess = user_sessions.get(user_id, {})
        sess["step"] = "duration"
        data = sess.get("data", {})
        exams_str = ", ".join(data.get("selected_exams", [])) or "All Exams"

        start_d = data.get("start_date")
        end_d = data.get("end_date")
        if start_d or end_d:
            date_str = f"{start_d or 'Any'} to {end_d or 'Any'}"
        else:
            date_str = "Any Upcoming"

        text = (
            f"⏳ <b>Step 4/4: Tracking Duration</b>\n\n"
            f"• Exam(s): <b>{html.escape(exams_str)}</b>\n"
            f"• University: <b>{html.escape(data.get('university_query', 'Any'))}</b>\n"
            f"• Dates: <b>{html.escape(date_str)}</b>\n\n"
            f"How long should this tracker stay active?"
        )
        markup = {
            "inline_keyboard": [
                [
                    {"text": "⚡️ 7 Days", "callback_data": "wiz_dur_7"},
                    {"text": "⚡️ 14 Days", "callback_data": "wiz_dur_14"}
                ],
                [
                    {"text": "⚡️ 30 Days", "callback_data": "wiz_dur_30"},
                    {"text": "⚡️ 60 Days", "callback_data": "wiz_dur_60"}
                ],
                [
                    {"text": "♾ Until Stopped / Indefinite", "callback_data": "wiz_dur_0"}
                ],
                [
                    {"text": "🔙 Back", "callback_data": "wiz_back_to_date"}
                ]
            ]
        }
        if message_id:
            self.edit_message_text(chat_id, message_id, text, markup)
        else:
            self.send_message(chat_id, text, markup)

    # ---------------------------------------------------------
    # Wizard Finalize
    # ---------------------------------------------------------

    def finalize_filter_creation(self, chat_id: int, user_id: int, message_id: int):
        """Saves the filter and performs an immediate search on current state."""
        sess = user_sessions.pop(user_id, None)
        if not sess or not sess.get("data"):
            self.show_main_menu(chat_id, {"first_name": "Student"}, message_id)
            return

        data = sess["data"]
        selected_exams = data.get("selected_exams", [])
        exam_type = ",".join(selected_exams) if selected_exams else "ALL"
        university = data.get("university_query", "ANY")
        start_date = data.get("start_date")
        end_date = data.get("end_date")
        duration_days = data.get("duration_days")

        filter_id = db.create_filter(
            user_id=user_id,
            exam_type=exam_type,
            university_query=university,
            start_date=start_date,
            end_date=end_date,
            duration_days=duration_days,
            db_path=self.db_path
        )

        start_d = start_date or "Any"
        end_d = end_date or "Any"
        date_window_str = f"{start_d} to {end_d}" if (start_date or end_date) else "Any upcoming date"
        duration_str = f"{duration_days} Days" if duration_days and duration_days > 0 else "Indefinite (Until stopped)"
        exams_display = ", ".join(selected_exams) if selected_exams else "All Exams"

        # Load current state to do immediate search
        state = {}
        if os.path.exists(config.STATE_FILE):
            try:
                with open(config.STATE_FILE, "r", encoding="utf-8") as f:
                    state = json.load(f)
            except Exception:
                pass

        filter_record = db.get_filter_by_id(filter_id, db_path=self.db_path)
        matching_seats = dispatcher.search_immediate_matches(filter_record, state)

        immediate_text = ""
        if matching_seats:
            immediate_text = (
                f"\n\n🎉 <b>GREAT NEWS! {len(matching_seats)} matching seat session(s) are AVAILABLE RIGHT NOW:</b>\n"
            )
            for s in matching_seats[:3]:
                immediate_text += (
                    f"• 🏛 <b>{html.escape(s['university'])}</b> ({html.escape(s['date'])}) — <i>{html.escape(s['seats'])} seats</i>\n"
                )
            immediate_text += f"\n👉 Tap <b>🚀 Book on CISIA</b> below to secure your seat immediately!"
        else:
            immediate_text = (
                f"\n\n📡 <b>Monitoring Active:</b> No open seats right now. "
                f"The bot will check CISIA every <b>1 minute</b> and ping you instantly when seats open!"
            )

        text = (
            f"✅ <b>Tracker #{filter_id} Created Successfully!</b>\n\n"
            f"📋 <b>Your Filter Settings:</b>\n"
            f"• <b>Exam(s):</b> {html.escape(exams_display)}\n"
            f"• <b>University:</b> {html.escape(university)}\n"
            f"• <b>Date Window:</b> {html.escape(date_window_str)}\n"
            f"• <b>Duration:</b> {html.escape(duration_str)}\n"
            f"• <b>Modality:</b> <code>TOLC@HOME / CENT@HOME</code>"
            f"{immediate_text}"
        )

        buttons = []
        if matching_seats:
            buttons.append([{"text": "🚀 Book on CISIA", "url": config.CISIA_LOGIN_URL}])
        buttons.append([{"text": "📋 My Active Trackers", "callback_data": "menu_mytrackers"}])
        buttons.append([{"text": "➕ Add Another Tracker", "callback_data": "wizard_start"}])
        buttons.append([{"text": "🏠 Main Menu", "callback_data": "menu_main"}])

        self.edit_message_text(chat_id, message_id, text, {"inline_keyboard": buttons})

    # ---------------------------------------------------------
    # Dashboard: My Trackers
    # ---------------------------------------------------------

    def show_user_trackers(self, chat_id: int, user_id: int, message_id: int = None):
        """Displays dashboard of user's trackers with management buttons."""
        filters = db.get_user_filters(user_id, include_inactive=True, db_path=self.db_path)

        if not filters:
            text = (
                f"📋 <b>My Active Trackers</b>\n\n"
                f"You don't have any active trackers yet.\n"
                f"Create one now to start getting notified!"
            )
            markup = {
                "inline_keyboard": [
                    [{"text": "➕ Create New Tracker", "callback_data": "wizard_start"}],
                    [{"text": "🏠 Main Menu", "callback_data": "menu_main"}]
                ]
            }
            if message_id:
                self.edit_message_text(chat_id, message_id, text, markup)
            else:
                self.send_message(chat_id, text, markup)
            return

        now_rome = datetime.now(ZoneInfo(config.TIMEZONE))
        text = f"📋 <b>Your Trackers ({len(filters)})</b>\n\n"
        buttons = []

        for f in filters:
            fid = f["id"]
            status_icon = "🟢" if f["status"] == "active" else ("⏸" if f["status"] == "paused" else "⏳")

            # Safe date display — handle None start/end dates
            start_d = f.get("start_date") or "Any"
            end_d = f.get("end_date") or "Any"
            dates = f"{start_d} to {end_d}" if (f.get("start_date") or f.get("end_date")) else "Any upcoming date"

            expiry_text = "Indefinite"
            if f.get("expires_at"):
                try:
                    exp_dt = datetime.fromisoformat(f["expires_at"])
                    # Ensure both datetimes are timezone-aware for comparison
                    if exp_dt.tzinfo is None:
                        exp_dt = exp_dt.replace(tzinfo=ZoneInfo(config.TIMEZONE))
                    remaining = exp_dt - now_rome
                    if remaining.total_seconds() > 0:
                        days = remaining.days
                        hours = remaining.seconds // 3600
                        expiry_text = f"{days}d {hours}h remaining"
                    else:
                        expiry_text = "Expired"
                except Exception:
                    pass

            # Multi-exam display
            exam_display = f.get("exam_type", "ALL").replace(",", ", ")

            text += (
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"{status_icon} <b>Tracker #{fid}: {html.escape(exam_display)}</b>\n"
                f"🏛 <b>University:</b> {html.escape(f['university_query'])}\n"
                f"📅 <b>Dates:</b> {html.escape(dates)}\n"
                f"⏳ <b>Status:</b> {html.escape(f['status'].upper())} ({expiry_text})\n"
            )

            row_btns = []
            if f["status"] == "active":
                row_btns.append({"text": f"⏸ Pause #{fid}", "callback_data": f"toggle_{fid}_paused"})
            elif f["status"] == "paused":
                row_btns.append({"text": f"▶️ Resume #{fid}", "callback_data": f"toggle_{fid}_active"})
            elif f["status"] == "expired":
                row_btns.append({"text": f"🔄 Renew +14d #{fid}", "callback_data": f"renew_{fid}_14"})

            row_btns.append({"text": f"🗑 Delete #{fid}", "callback_data": f"del_{fid}"})
            buttons.append(row_btns)

        buttons.append([{"text": "➕ Add New Tracker", "callback_data": "wizard_start"}])
        buttons.append([{"text": "🏠 Main Menu", "callback_data": "menu_main"}])

        markup = {"inline_keyboard": buttons}
        if message_id:
            self.edit_message_text(chat_id, message_id, text, markup)
        else:
            self.send_message(chat_id, text, markup)

    # ---------------------------------------------------------
    # Instant Seat Check
    # ---------------------------------------------------------

    def show_instant_check(self, chat_id: int, message_id: int = None):
        """Displays currently available @HOME seats across all tracked calendars."""
        state = {}
        if os.path.exists(config.STATE_FILE):
            try:
                with open(config.STATE_FILE, "r", encoding="utf-8") as f:
                    state = json.load(f)
            except Exception:
                pass

        available_seats = [
            r for r in state.values()
            if ("AVAILABLE SEATS" in r.get("state", "").upper() or "POSTI DISPONIBILI" in r.get("state", "").upper())
            and ("HOME" in r.get("format", "").upper() or "CASA" in r.get("format", "").upper())
        ]

        if not available_seats:
            text = (
                f"🔍 <b>Instant Seat Check</b>\n\n"
                f"Currently, there are <b>0 available @HOME seats</b> on CISIA calendars.\n\n"
                f"Set up a personalized tracker and the bot will alert you the exact moment seats open!"
            )
        else:
            text = f"🔍 <b>Available @HOME Seats ({len(available_seats)})</b>\n\n"
            for s in available_seats[:8]:
                text += (
                    f"• <b>{html.escape(s['test_type'])}</b>\n"
                    f"  🏛 {html.escape(s['university'])} ({html.escape(s['city'])})\n"
                    f"  📅 Date: <b>{html.escape(s['date'])}</b> | 🎟 Seats: <b>{html.escape(s['seats'])}</b>\n"
                    f"  ⏳ Deadline: {html.escape(s['deadline'])}\n\n"
                )
            if len(available_seats) > 8:
                text += f"<i>...and {len(available_seats) - 8} more.</i>\n"

        markup = {
            "inline_keyboard": [
                [{"text": "🚀 Book on CISIA", "url": config.CISIA_LOGIN_URL}],
                [{"text": "➕ Set Up Tracker", "callback_data": "wizard_start"}],
                [{"text": "🏠 Main Menu", "callback_data": "menu_main"}]
            ]
        }
        if message_id:
            self.edit_message_text(chat_id, message_id, text, markup)
        else:
            self.send_message(chat_id, text, markup)

    # ---------------------------------------------------------
    # Updates & Event Handling
    # ---------------------------------------------------------

    def _require_session(self, user_id: int, callback_query_id: str, chat_id: int, msg_id: int) -> bool:
        """
        Guard: if the user has no in-memory session (e.g. after a Render restart),
        shows a friendly error and prompts them to restart the wizard.
        Returns True if session is valid, False if guard triggered.
        """
        if user_id not in user_sessions:
            self.answer_callback_query(
                callback_query_id,
                "⚠️ Session expired (bot restarted). Starting fresh...",
                show_alert=True
            )
            self.start_wizard(chat_id, user_id, msg_id)
            return False
        return True

    def handle_callback_query(self, query: dict):
        """Dispatches callback queries from inline buttons."""
        query_id = query.get("id")
        user = query.get("from", {})
        user_id = user.get("id")
        message = query.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        msg_id = message.get("message_id")
        data = query.get("data", "")

        db.register_or_update_user(
            user_id=user_id,
            username=user.get("username", ""),
            first_name=user.get("first_name", ""),
            db_path=self.db_path
        )

        # ── Navigation ──────────────────────────────────────────────
        if data == "menu_main":
            self.answer_callback_query(query_id)
            self.show_main_menu(chat_id, user, msg_id)
            return

        if data == "menu_help":
            self.answer_callback_query(query_id)
            self.show_help(chat_id, msg_id)
            return

        if data == "menu_mytrackers":
            self.answer_callback_query(query_id)
            self.show_user_trackers(chat_id, user_id, msg_id)
            return

        if data == "menu_check":
            self.answer_callback_query(query_id)
            self.show_instant_check(chat_id, msg_id)
            return

        if data == "wizard_start":
            self.answer_callback_query(query_id)
            self.start_wizard(chat_id, user_id, msg_id)
            return

        # No-op button (e.g. "Select at least one exam" hint)
        if data == "wiz_noop":
            self.answer_callback_query(query_id, "Please select at least one exam type first.")
            return

        # ── Step 1: Exam Type Toggle ─────────────────────────────────
        if data.startswith("wiz_toggle_"):
            if not self._require_session(user_id, query_id, chat_id, msg_id):
                return
            exam = data.replace("wiz_toggle_", "")
            sess = user_sessions[user_id]
            selected = sess["data"].setdefault("selected_exams", [])
            if exam in selected:
                selected.remove(exam)
            else:
                selected.append(exam)
            self.answer_callback_query(query_id, f"{'☑️ Added' if exam in selected else '☐ Removed'}: {exam}")
            self._refresh_exam_type_screen(chat_id, user_id, msg_id)
            return

        if data == "wiz_exam_all":
            if not self._require_session(user_id, query_id, chat_id, msg_id):
                return
            user_sessions[user_id]["data"]["selected_exams"] = list(EXAM_TYPES)
            self.answer_callback_query(query_id, "All exams selected!")
            self._refresh_exam_type_screen(chat_id, user_id, msg_id)
            return

        if data == "wiz_exam_clear":
            if not self._require_session(user_id, query_id, chat_id, msg_id):
                return
            user_sessions[user_id]["data"]["selected_exams"] = []
            self.answer_callback_query(query_id, "Selection cleared.")
            self._refresh_exam_type_screen(chat_id, user_id, msg_id)
            return

        if data == "wiz_exam_confirm":
            if not self._require_session(user_id, query_id, chat_id, msg_id):
                return
            selected = user_sessions[user_id]["data"].get("selected_exams", [])
            if not selected:
                self.answer_callback_query(query_id, "Please select at least one exam type.", show_alert=True)
                return
            self.answer_callback_query(query_id, f"Exam(s) confirmed: {', '.join(selected)}")
            self.show_university_step(chat_id, user_id, msg_id)
            return

        if data == "wiz_back_to_uni":
            self.answer_callback_query(query_id)
            if not self._require_session(user_id, query_id, chat_id, msg_id):
                return
            self.show_university_step(chat_id, user_id, msg_id)
            return

        # ── Step 2: University ───────────────────────────────────────
        if data.startswith("wiz_uni_"):
            if not self._require_session(user_id, query_id, chat_id, msg_id):
                return
            uni = data.replace("wiz_uni_", "")
            if uni == "custom":
                user_sessions[user_id]["step"] = "waiting_uni_text"
                user_sessions[user_id]["msg_id"] = msg_id
                self.answer_callback_query(query_id)
                prompt = (
                    f"✏️ <b>Type Your Target University</b>\n\n"
                    f"Reply with the university or city name.\n"
                    f"Examples: <i>Sapienza, Bologna, Milan, Pisa, Rome, Bari, Catania</i>\n\n"
                    f"<i>Tip: partial names work — 'Poli' will match 'Politecnico'</i>"
                )
                self.edit_message_text(chat_id, msg_id, prompt, {
                    "inline_keyboard": [[{"text": "🔙 Back", "callback_data": "wiz_back_to_uni"}]]
                })
                return

            user_sessions[user_id]["data"]["university_query"] = uni
            self.answer_callback_query(query_id, f"Selected: {uni}")
            self.show_date_range_step(chat_id, user_id, msg_id)
            return

        if data == "wiz_back_to_date":
            self.answer_callback_query(query_id)
            if not self._require_session(user_id, query_id, chat_id, msg_id):
                return
            self.show_date_range_step(chat_id, user_id, msg_id)
            return

        # ── Step 3: Date Range ───────────────────────────────────────
        if data.startswith("wiz_date_"):
            if not self._require_session(user_id, query_id, chat_id, msg_id):
                return
            dtype = data.replace("wiz_date_", "")
            if dtype == "custom":
                user_sessions[user_id]["step"] = "waiting_date_text"
                user_sessions[user_id]["msg_id"] = msg_id
                self.answer_callback_query(query_id)
                prompt = (
                    f"✏️ <b>Type Your Desired Date Range</b>\n\n"
                    f"Enter the date range in <b>DD/MM/YYYY</b> format.\n"
                    f"Examples:\n"
                    f"• <code>10/08/2026 - 15/09/2026</code>\n"
                    f"• <code>10/08 to 15/09</code>\n"
                    f"• <code>August 2026</code>"
                )
                self.edit_message_text(chat_id, msg_id, prompt, {
                    "inline_keyboard": [[{"text": "🔙 Back", "callback_data": "wiz_back_to_date"}]]
                })
                return

            s_date, e_date = None, None
            now_d = datetime.now(ZoneInfo(config.TIMEZONE)).date()
            if dtype == "30d":
                s_date, e_date = now_d.isoformat(), (now_d + timedelta(days=30)).isoformat()
            elif dtype == "60d":
                s_date, e_date = now_d.isoformat(), (now_d + timedelta(days=60)).isoformat()
            elif dtype == "aug_sep":
                s_date, e_date = matcher.parse_user_date_range("August to September")
            # dtype == "any" → s_date, e_date remain None

            user_sessions[user_id]["data"]["start_date"] = s_date
            user_sessions[user_id]["data"]["end_date"] = e_date
            self.answer_callback_query(query_id)
            self.show_duration_step(chat_id, user_id, msg_id)
            return

        # ── Step 4: Duration ─────────────────────────────────────────
        if data.startswith("wiz_dur_"):
            if not self._require_session(user_id, query_id, chat_id, msg_id):
                return
            try:
                days = int(data.replace("wiz_dur_", ""))
            except ValueError:
                self.answer_callback_query(query_id, "Invalid selection. Please try again.", show_alert=True)
                return
            user_sessions[user_id]["data"]["duration_days"] = days
            self.answer_callback_query(query_id, "Saving tracker...")
            self.finalize_filter_creation(chat_id, user_id, msg_id)
            return

        # ── Tracker Management ───────────────────────────────────────
        if data.startswith("toggle_"):
            parts = data.split("_")
            try:
                fid = int(parts[1])
                new_status = parts[2]
            except (IndexError, ValueError):
                self.answer_callback_query(query_id, "Invalid action.", show_alert=True)
                return
            db.update_filter_status(fid, user_id, new_status, db_path=self.db_path)
            self.answer_callback_query(query_id, f"Tracker #{fid} {new_status}!")
            self.show_user_trackers(chat_id, user_id, msg_id)
            return

        if data.startswith("del_"):
            try:
                fid = int(data.replace("del_", ""))
            except ValueError:
                self.answer_callback_query(query_id, "Invalid action.", show_alert=True)
                return
            db.delete_filter(fid, user_id, db_path=self.db_path)
            self.answer_callback_query(query_id, f"Tracker #{fid} deleted!", show_alert=True)
            self.show_user_trackers(chat_id, user_id, msg_id)
            return

        if data.startswith("renew_"):
            parts = data.split("_")
            try:
                fid = int(parts[1])
                days = int(parts[2])
            except (IndexError, ValueError):
                self.answer_callback_query(query_id, "Invalid action.", show_alert=True)
                return
            db.renew_filter(fid, user_id, additional_days=days, db_path=self.db_path)
            self.answer_callback_query(query_id, f"Tracker #{fid} extended for {days} days!", show_alert=True)
            self.show_user_trackers(chat_id, user_id, msg_id)
            return

        # Unknown callback — fall back to main menu
        self.answer_callback_query(query_id)
        self.show_main_menu(chat_id, user, msg_id)

    def handle_text_message(self, msg: dict):
        """Processes incoming text messages and conversation inputs."""
        user = msg.get("from", {})
        user_id = user.get("id")
        chat_id = msg.get("chat", {}).get("id")
        text = (msg.get("text") or "").strip()

        db.register_or_update_user(
            user_id=user_id,
            username=user.get("username", ""),
            first_name=user.get("first_name", ""),
            db_path=self.db_path
        )

        # ── Commands ─────────────────────────────────────────────────
        if text.startswith("/start") or text.startswith("/menu"):
            user_sessions.pop(user_id, None)
            self.show_main_menu(chat_id, user)
            return

        if text.startswith("/mytrackers") or text.startswith("/list"):
            user_sessions.pop(user_id, None)
            self.show_user_trackers(chat_id, user_id)
            return

        if text.startswith("/new"):
            user_sessions.pop(user_id, None)
            self.start_wizard(chat_id, user_id)
            return

        if text.startswith("/check"):
            self.show_instant_check(chat_id)
            return

        if text.startswith("/help"):
            self.show_help(chat_id)
            return

        if text.startswith("/cancel"):
            user_sessions.pop(user_id, None)
            self.send_message(chat_id, "❌ <b>Operation cancelled.</b> Use /start to return to the main menu.")
            return

        # ── Wizard text input states ──────────────────────────────────
        sess = user_sessions.get(user_id)

        if sess and sess.get("step") == "waiting_uni_text":
            # Match using word-boundary fuzzy — store typed value directly for live row matching
            match, score, matched_name = matcher.match_university(text, text)
            # We store the typed query, not the matched canonical name, because
            # matching happens against live CISIA rows at alert time
            sess["data"]["university_query"] = text
            sess["step"] = "date_range"
            msg_id = sess.get("msg_id")

            self.send_message(chat_id, f"🏛 University set to: <b>{html.escape(text)}</b>")
            self.show_date_range_step(chat_id, user_id, None)
            return

        if sess and sess.get("step") == "waiting_date_text":
            s_date, e_date = matcher.parse_user_date_range(text)
            if not s_date and not e_date:
                err_text = (
                    f"⚠️ <b>Could not recognize date range</b>\n\n"
                    f"Please enter in format <code>DD/MM/YYYY - DD/MM/YYYY</code> or <code>10/08 to 15/09</code>.\n"
                    f"Or tap below to choose a preset:"
                )
                markup = {
                    "inline_keyboard": [
                        [{"text": "🌟 Any Upcoming Date", "callback_data": "wiz_date_any"}],
                        [{"text": "📅 Next 30 Days", "callback_data": "wiz_date_30d"}]
                    ]
                }
                self.send_message(chat_id, err_text, markup)
                return

            sess["data"]["start_date"] = s_date
            sess["data"]["end_date"] = e_date
            sess["step"] = "duration"
            self.send_message(chat_id, f"📅 Date range set to: <b>{s_date} to {e_date}</b>")
            self.show_duration_step(chat_id, user_id, None)
            return

        # Default fallback
        self.show_main_menu(chat_id, user)

    def poll_updates(self):
        """Long-polling update loop."""
        logger.info("Interactive Telegram Bot polling started...")
        while self.running:
            try:
                payload = {
                    "offset": self.last_update_id + 1,
                    "timeout": 10,
                    "allowed_updates": ["message", "callback_query"]
                }
                res = self.api_call("getUpdates", payload, timeout=15)
                if not res:
                    time.sleep(1)
                    continue

                for update in res:
                    self.last_update_id = max(self.last_update_id, update.get("update_id", 0))

                    if "callback_query" in update:
                        self.handle_callback_query(update["callback_query"])
                    elif "message" in update and "text" in update["message"]:
                        self.handle_text_message(update["message"])

            except Exception as e:
                logger.error(f"Error in Telegram Bot update loop: {e}")
                time.sleep(3)

    def start_polling_in_thread(self):
        """Starts the bot poller in a daemon background thread."""
        if not self.token:
            logger.warning("FILTER_BOT_TOKEN not configured. Interactive filter bot will not start.")
            return

        # Delete any existing webhook to ensure getUpdates long-polling works cleanly
        try:
            self.api_call("deleteWebhook", {"drop_pending_updates": False})
        except Exception:
            pass

        self.running = True
        self._thread = threading.Thread(target=self.poll_updates, daemon=True)
        self._thread.start()
        logger.info("Interactive Telegram Filter Bot thread launched.")

    def stop(self):
        """Stops the poller."""
        self.running = False


bot_instance = TelegramBot()
