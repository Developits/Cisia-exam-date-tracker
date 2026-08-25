#!/usr/bin/env python3
"""
CISIA TOLC Seat Availability Tracker
Monitors CISIA calendar pages and delivers instant push notifications via Telegram
when home-based (TOLC@HOME / CENT@HOME) test seats become available.
"""

import sys
import os
import json
import time
import html
import argparse
import logging
import threading
import traceback
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry
from bs4 import BeautifulSoup

import config

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("CISIA-Tracker")

# Configure robust HTTP session with retries
http_session = requests.Session()
retry_strategy = Retry(
    total=2,
    backoff_factor=1,
    status_forcelist=[500, 502, 503, 504],
    raise_on_status=False
)
adapter = HTTPAdapter(max_retries=retry_strategy)
http_session.mount("https://", adapter)
http_session.mount("http://", adapter)


def get_rome_now() -> datetime:
    """Returns the current datetime in Europe/Rome timezone."""
    return datetime.now(ZoneInfo(config.TIMEZONE))


def is_active_minute(dt: datetime) -> bool:
    """
    Checks if given Rome datetime falls within:
    - Daily operating hours: 06:00 to 22:00 (every minute)
    """
    time_minutes = dt.hour * 60 + dt.minute
    start_total = config.START_HOUR * 60 + config.START_MINUTE  # 06:00 -> 360
    end_total = config.END_HOUR * 60 + config.END_MINUTE        # 22:00 -> 1320

    return start_total <= time_minutes <= end_total


def calculate_sleep_seconds(dt: datetime) -> float:
    """
    Calculates how many seconds to sleep until the next scheduled check.
    If currently inside operating hours (06:00 - 22:00), sleeps until the next minute boundary (~60s).
    If outside (night time), sleeps until 06:00 next morning.
    """
    if is_active_minute(dt):
        # Sleep until the exact start of the next minute
        return max(1.0, 60.0 - dt.second - (dt.microsecond / 1_000_000.0))

    # Next active time is START_HOUR:START_MINUTE (06:00:00)
    if dt.hour >= config.END_HOUR and dt.minute > config.END_MINUTE:
        # After 22:00, target is tomorrow at 06:00:00
        target = (dt + timedelta(days=1)).replace(
            hour=config.START_HOUR, minute=config.START_MINUTE, second=0, microsecond=0
        )
    else:
        # Before 06:00, target is today at 06:00:00
        target = dt.replace(
            hour=config.START_HOUR, minute=config.START_MINUTE, second=0, microsecond=0
        )

    delta = (target - dt).total_seconds()
    return max(1.0, delta)


def clean_text(text: str) -> str:
    """Cleans up whitespace and newlines from parsed cell text."""
    if not text:
        return ""
    return " ".join(text.strip().split())


def parse_page_rows(html_content: str, page_info: dict) -> list[dict]:
    """
    Parses the CISIA calendar HTML and returns list of collision-free standardized row dictionaries.
    """
    soup = BeautifulSoup(html_content, "html.parser")
    table = soup.find("table", id="calendario")
    if not table:
        logger.warning(f"No table id='calendario' found for {page_info['name']}")
        return []

    tbody = table.find("tbody")
    if not tbody:
        logger.warning(f"No tbody found in table for {page_info['name']}")
        return []

    rows = []
    key_counter = {}

    for tr in tbody.find_all("tr", recursive=False):
        tds = tr.find_all("td")
        if len(tds) < 8:
            continue

        # Column indices on CISIA English calendar:
        # 0: FORMAT (e.g. TOLC@HOME, CENT@HOME, TOLC@UNI)
        # 1: UNIVERSITY
        # 2: REGION / FOREIGN COUNTRY
        # 3: CITY
        # 4: BOOKINGS DEADLINE
        # 5: SEATS
        # 6: STATE (e.g. AVAILABLE SEATS, NOT LONGER AVAILABLE, NOT BOOKABLE, BOOKINGS CLOSED)
        # 7: DATE

        test_format = clean_text(tds[0].get_text())
        university = clean_text(tds[1].get_text())
        region = clean_text(tds[2].get_text())
        city = clean_text(tds[3].get_text())
        deadline = clean_text(tds[4].get_text())
        seats = clean_text(tds[5].get_text())
        state = clean_text(tds[6].get_text()).upper()
        test_date = clean_text(tds[7].get_text())

        # Generate unique collision-free key including session index
        base_key = f"{page_info['name']}|{test_format}|{university}|{city}|{test_date}|{deadline}"
        key_counter[base_key] = key_counter.get(base_key, 0) + 1
        key = f"{base_key}#{key_counter[base_key]}"

        rows.append({
            "key": key,
            "test_type": page_info["name"],
            "url": page_info["url"],
            "format": test_format,
            "university": university,
            "region": region,
            "city": city,
            "deadline": deadline,
            "seats": seats,
            "state": state,
            "date": test_date
        })

    return rows


def fetch_page(page_info: dict) -> list[dict] | None:
    """
    Fetches a single CISIA page and parses its rows.
    Returns list of rows on success, or None if the request failed after retries.
    """
    try:
        response = http_session.get(
            page_info["url"],
            headers=config.HTTP_HEADERS,
            timeout=config.REQUEST_TIMEOUT
        )
        response.raise_for_status()
        return parse_page_rows(response.text, page_info)
    except Exception as e:
        logger.error(f"Error fetching {page_info['name']} ({page_info['url']}): {e}")
        return None


def send_telegram_alert(row: dict, change_type: str, old_status: str = "") -> bool:
    """
    Sends an instant push notification via Telegram Bot API with inline buttons to all configured chat IDs.
    Properly escapes HTML entities to prevent Telegram parse errors.
    """
    token = config.TELEGRAM_BOT_TOKEN.strip()
    raw_chat_ids = config.TELEGRAM_CHAT_ID.strip()
    if not token or not raw_chat_ids:
        return False

    # Support multiple comma/space/semicolon separated chat IDs
    chat_ids = [c.strip() for c in raw_chat_ids.replace(";", ",").replace(" ", ",").split(",") if c.strip()]
    if not chat_ids:
        return False

    if change_type == "new":
        reason_text = "✨ <b>New test date added with available seats!</b>"
    else:
        escaped_old = html.escape(old_status)
        reason_text = f"🔄 <b>Status updated:</b> <s>{escaped_old}</s> ➔ <b>AVAILABLE SEATS</b>"

    message = (
        f"🚨 <b>{html.escape(row['test_type'])} {html.escape(row['seats'])} SEATS AVAILABLE ALERT!</b>\n\n"
        f"{reason_text}\n\n"
        f"🏛 <b>University:</b> {html.escape(row['university'])}\n"
        f"💻 <b>Format:</b> {html.escape(row['format'])}\n"
        f"📍 <b>City:</b> {html.escape(row['city'])} ({html.escape(row['region'])})\n"
        f"📅 <b>Test Date:</b> {html.escape(row['date'])}\n"
        f"🎟 <b>Seats:</b> {html.escape(row['seats'])}\n"
        f"⏳ <b>Bookings Deadline:</b> {html.escape(row['deadline'])}\n"
        f"⚡️ <b>State:</b> {html.escape(row['state'])}"
    )

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    sent_successfully = 0

    for cid in chat_ids:
        payload = {
            "chat_id": cid,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
            "reply_markup": {
                "inline_keyboard": [
                    [
                        {"text": "🚀 Book on CISIA", "url": config.CISIA_LOGIN_URL},
                        {"text": "📅 Open Calendar", "url": row["url"]}
                    ]
                ]
            }
        }
        try:
            res = http_session.post(url, json=payload, timeout=10)
            res.raise_for_status()
            logger.info(f"Telegram notification sent to chat_id '{cid}' for {row['university']} ({row['date']})")
            sent_successfully += 1
            # Throttling to respect Telegram API rate limits
            time.sleep(0.1)
        except Exception as e:
            logger.error(f"Failed to send Telegram notification to chat_id '{cid}': {e}")

    return sent_successfully > 0


# Cache for error throttling: {error_signature: last_sent_timestamp}
_last_error_alerts: dict[str, float] = {}


def send_developer_error_alert(error_title: str, error_detail: str, traceback_str: str = "", force: bool = False) -> bool:
    """
    Sends an error notification with stack trace directly to the developer Telegram chat ID (Mr Marshmallow: 1720364178).
    Throttles identical error signatures to once every ERROR_THROTTLE_SECONDS unless force=True.
    """
    token = config.TELEGRAM_BOT_TOKEN.strip()
    dev_id = getattr(config, "DEVELOPER_CHAT_ID", "").strip()
    if not token or not dev_id:
        return False

    now = time.time()
    error_key = f"{error_title}:{error_detail[:100]}"

    if not force:
        last_sent = _last_error_alerts.get(error_key, 0.0)
        if now - last_sent < config.ERROR_THROTTLE_SECONDS:
            logger.info(f"Skipping duplicate developer error alert (throttled): {error_title}")
            return False

    _last_error_alerts[error_key] = now

    rome_time = get_rome_now().strftime("%Y-%m-%d %H:%M:%S")

    # Truncate traceback to safe length (Telegram limit is 4096 chars for message)
    clean_tb = traceback_str.strip()
    if len(clean_tb) > 2000:
        clean_tb = clean_tb[-2000:]

    tb_section = f"\n\n📋 <b>Traceback:</b>\n<pre><code>{html.escape(clean_tb)}</code></pre>" if clean_tb else ""

    message = (
        f"⚠️ <b>CISIA TRACKER ERROR ALERT</b>\n"
        f"⏰ <b>Rome Time:</b> <code>{rome_time}</code>\n"
        f"🚨 <b>Issue:</b> <b>{html.escape(error_title)}</b>\n"
        f"📝 <b>Details:</b> {html.escape(error_detail)}"
        f"{tb_section}"
    )

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": dev_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }

    try:
        res = http_session.post(url, json=payload, timeout=10)
        res.raise_for_status()
        logger.info(f"Developer error alert delivered to chat_id '{dev_id}'")
        return True
    except Exception as e:
        logger.error(f"Failed to deliver developer error alert to chat_id '{dev_id}': {e}")
        return False


def send_notifications(row: dict, change_type: str, old_status: str = "") -> bool:
    """Dispatches notifications to configured Telegram chat IDs."""
    return send_telegram_alert(row, change_type, old_status)


def load_state() -> dict[str, dict]:
    """Loads previous state from JSON file."""
    if not os.path.exists(config.STATE_FILE):
        return {}
    try:
        with open(config.STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Could not load state from {config.STATE_FILE}: {e}")
        return {}


def save_state(state: dict[str, dict]):
    """Atomically saves current state to JSON file."""
    temp_file = f"{config.STATE_FILE}.tmp"
    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(temp_file, config.STATE_FILE)
    except Exception as e:
        logger.error(f"Failed to save state to {config.STATE_FILE}: {e}")
        if os.path.exists(temp_file):
            os.remove(temp_file)


def is_home_modality(format_str: str) -> bool:
    """Checks if test format is home-based (e.g. TOLC@HOME, CENT@HOME, TOLC@CASA)."""
    fmt = (format_str or "").upper()
    return "HOME" in fmt or "CASA" in fmt


def is_available_state(state_str: str) -> bool:
    """Checks if state indicates available seats."""
    st = (state_str or "").upper()
    return "AVAILABLE SEATS" in st or "POSTI DISPONIBILI" in st


def run_check_cycle(previous_state: dict[str, dict], is_first_run: bool) -> tuple[dict[str, dict], int]:
    """
    Fetches each tracked page independently, updates state per page,
    and dispatches notifications for newly available seats (TOLC@HOME / CENT@HOME only).
    Preserves state for any page that encounters a transient network failure.
    Returns the updated state and count of alerts sent.
    """
    updated_state = dict(previous_state)
    alerts_sent = 0
    pages_successfully_fetched = 0

    for page in config.TRACKED_PAGES:
        logger.info(f"Checking {page['name']}...")
        rows = fetch_page(page)
        
        if rows is None:
            logger.warning(f"Failed to fetch {page['name']}. Retaining previous state for this calendar.")
            continue

        pages_successfully_fetched += 1
        page_prefix = f"{page['name']}|"

        # Build current rows for this specific page
        page_state = {r["key"]: r for r in rows}

        if is_first_run and not previous_state:
            # Baseline initialization: merge into state without triggering alerts
            for k, r in page_state.items():
                updated_state[k] = r
            continue

        # Remove old rows belonging specifically to this page
        old_page_keys = [k for k in updated_state if k.startswith(page_prefix)]
        old_page_state = {k: updated_state[k] for k in old_page_keys}

        # Detect changes for this page
        for key, row in page_state.items():
            is_available = is_available_state(row["state"])
            is_home = is_home_modality(row.get("format", ""))

            if key not in old_page_state:
                # Condition 1: New HOME row added with AVAILABLE SEATS
                if is_home and is_available:
                    logger.info(f"NEW HOME ROW with available seats: {row['test_type']} | {row['university']} | {row['date']}")
                    if send_notifications(row, change_type="new"):
                        alerts_sent += 1
            else:
                old_row = old_page_state[key]
                old_state = old_row.get("state", "")
                was_available = is_available_state(old_state)

                # Condition 2: Existing HOME row became AVAILABLE SEATS from previous unavailable state
                if is_home and is_available and not was_available:
                    logger.info(f"STATUS CHANGED to available for HOME: {row['test_type']} | {row['university']} | {row['date']} (Old: {old_state})")
                    if send_notifications(row, change_type="status_change", old_status=old_state):
                        alerts_sent += 1

        # Replace this page's keys in updated_state
        for k in old_page_keys:
            del updated_state[k]
        for k, r in page_state.items():
            updated_state[k] = r

    if is_first_run and not previous_state and pages_successfully_fetched > 0:
        available_home = sum(
            1 for r in updated_state.values()
            if is_home_modality(r["format"]) and is_available_state(r["state"])
        )
        logger.info(f"Initialized baseline state with {len(updated_state)} total rows ({available_home} HOME seats currently available).")

    if pages_successfully_fetched > 0:
        save_state(updated_state)

    return updated_state, alerts_sent


def send_test_notification():
    """Sends a sample test alert to verify notification setup."""
    sample_row = {
        "test_type": "TOLC-I (Engineering) [TEST]",
        "url": "https://testcisia.it/calendario.php?tolc=ingegneria&l=gb",
        "format": "TOLC@HOME",
        "university": "Sapienza University of Rome (Test Alert)",
        "region": "LAZIO",
        "city": "ROME",
        "deadline": "01/09/2026",
        "seats": "10",
        "state": "AVAILABLE SEATS",
        "date": "15/09/2026"
    }
    logger.info("Sending test notification across configured channels...")
    success = send_notifications(sample_row, change_type="new")
    if success:
        logger.info("Test notification delivered successfully to Telegram!")
    else:
        logger.error("Test notification failed. Please verify TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.")


class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/test":
            sample_row = {
                "test_type": "TOLC-I (Engineering) [TEST]",
                "url": "https://testcisia.it/calendario.php?tolc=ingegneria&l=gb",
                "format": "TOLC@HOME",
                "university": "Sapienza University of Rome (Test Alert)",
                "region": "LAZIO",
                "city": "ROME",
                "deadline": "01/09/2026",
                "seats": "10",
                "state": "AVAILABLE SEATS",
                "date": "15/09/2026"
            }
            success = send_notifications(sample_row, change_type="new")
            self.send_response(200 if success else 500)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            resp = {
                "success": success,
                "message": "Test notification triggered from Render to Telegram!",
                "telegram_configured": bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID)
            }
            self.wfile.write(json.dumps(resp).encode("utf-8"))
        if self.path == "/test-error":
            sample_tb = (
                "Traceback (most recent call last):\n"
                "  File \"tracker.py\", line 560, in main\n"
                "    state, alerts = run_check_cycle(state, is_first_run)\n"
                "  File \"tracker.py\", line 370, in run_check_cycle\n"
                "    raise ConnectionResetError(\"Simulated Render Error for Developer Alert Testing\")"
            )
            success = send_developer_error_alert(
                error_title="Simulated Test Error on Render",
                error_detail="ConnectionResetError: Simulated Render Error for Developer Alert Testing",
                traceback_str=sample_tb,
                force=True
            )
            self.send_response(200 if success else 500)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            resp = {
                "success": success,
                "message": f"Developer test error alert sent to Telegram ID {config.DEVELOPER_CHAT_ID}!",
                "developer_id": config.DEVELOPER_CHAT_ID
            }
            self.wfile.write(json.dumps(resp).encode("utf-8"))
            return

        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        rome_now = get_rome_now().strftime("%Y-%m-%d %H:%M:%S")
        status_data = {
            "status": "online",
            "rome_time": rome_now,
            "telegram_configured": bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID),
            "developer_id": config.DEVELOPER_CHAT_ID,
            "active_now": is_active_minute(get_rome_now())
        }
        self.wfile.write(json.dumps(status_data).encode("utf-8"))

    def log_message(self, format, *args):
        # Suppress noisy HTTP access logs
        return


def start_health_server():
    port = int(os.getenv("PORT", "8080"))
    try:
        server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        logger.info(f"Health check HTTP server started on port {port} (Ready for Render/Cloud hosts)")
    except Exception as e:
        logger.warning(f"Could not start HTTP server on port {port}: {e}")


def main():
    parser = argparse.ArgumentParser(description="CISIA TOLC Seat Availability Tracker")
    parser.add_argument("--once", action="store_true", help="Run a single check cycle immediately and exit.")
    parser.add_argument("--test-notify", action="store_true", help="Send a test notification to Telegram and exit.")
    parser.add_argument("--test-error", action="store_true", help="Send a test error notification to developer and exit.")
    parser.add_argument("--reset-state", action="store_true", help="Delete state.json before running.")
    args = parser.parse_args()

    if args.test_notify:
        send_test_notification()
        return

    if args.test_error:
        send_developer_error_alert(
            error_title="Manual Test Error",
            error_detail="Developer requested manual error test via CLI",
            traceback_str="Traceback (most recent call last):\n  File \"tracker.py\", line 1\n    Manual CLI test invocation",
            force=True
        )
        return

    if args.reset_state and os.path.exists(config.STATE_FILE):
        os.remove(config.STATE_FILE)
        logger.info(f"Removed {config.STATE_FILE}")

    state = load_state()
    is_first_run = len(state) == 0

    if args.once:
        logger.info("Running single check cycle...")
        state, alerts = run_check_cycle(state, is_first_run)
        logger.info(f"Cycle completed. Alerts sent: {alerts}")
        return

    # Start health check server for Render/Cloud hosts
    start_health_server()

    logger.info("==================================================")
    logger.info("       CISIA TOLC Availability Tracker Starting    ")
    logger.info(f" Timezone: {config.TIMEZONE}")
    logger.info(f" Operating Hours: {config.START_HOUR:02d}:{config.START_MINUTE:02d} to {config.END_HOUR:02d}:{config.END_MINUTE:02d} (Every 1 minute)")
    logger.info(f" Telegram Broadcast: {'Configured' if config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID else 'Disabled'}")
    logger.info(f" Developer Error Alert ID: {config.DEVELOPER_CHAT_ID or 'Disabled'}")
    logger.info("==================================================")

    while True:
        try:
            now_rome = get_rome_now()

            if is_active_minute(now_rome):
                logger.info(f"Active window check at Rome time {now_rome.strftime('%H:%M:%S')}")
                state, alerts = run_check_cycle(state, is_first_run)
                is_first_run = False

            sleep_sec = calculate_sleep_seconds(get_rome_now())
            next_run = get_rome_now() + timedelta(seconds=sleep_sec)
            
            if not is_active_minute(now_rome):
                logger.info(f"Outside active window. Sleeping {sleep_sec:.0f}s until next window at {next_run.strftime('%Y-%m-%d %H:%M:%S')} Rome time.")
            
            time.sleep(sleep_sec)

        except KeyboardInterrupt:
            logger.info("Tracker stopped by user.")
            sys.exit(0)
        except Exception as e:
            tb_str = traceback.format_exc()
            logger.error(f"Unexpected error in main loop: {e}", exc_info=True)
            send_developer_error_alert(
                error_title="Main Loop Exception",
                error_detail=str(e),
                traceback_str=tb_str
            )
            time.sleep(30)


if __name__ == "__main__":
    main()
