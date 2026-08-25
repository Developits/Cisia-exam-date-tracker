#!/usr/bin/env python3
"""
CISIA TOLC Seat Availability Tracker
Monitors CISIA calendar pages and delivers instant push notifications via ntfy.sh
when test seats become available.
"""

import sys
import os
import json
import time
import argparse
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import requests
from bs4 import BeautifulSoup

import config

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("CISIA-Tracker")


def get_rome_now() -> datetime:
    """Returns the current datetime in Europe/Rome timezone."""
    return datetime.now(ZoneInfo(config.TIMEZONE))


def is_active_minute(dt: datetime) -> bool:
    """
    Checks if given Rome datetime falls within:
    - Daily operating hours: 06:55 to 22:05
    - Active minute intervals: :55 to :05 and :25 to :35
    """
    # Check overall day boundaries
    time_minutes = dt.hour * 60 + dt.minute
    start_total = config.START_HOUR * 60 + config.START_MINUTE  # 06:55 -> 415
    end_total = config.END_HOUR * 60 + config.END_MINUTE        # 22:05 -> 1325

    if time_minutes < start_total or time_minutes > end_total:
        return False

    # Check minute windows
    minute = dt.minute
    return any(minute in window for window in config.MINUTE_WINDOWS)


def calculate_sleep_seconds(dt: datetime) -> float:
    """
    Calculates how many seconds to sleep until the next scheduled check.
    If currently inside an active window, returns seconds to next minute boundary.
    If outside, searches ahead minute-by-minute for the next active window.
    """
    if is_active_minute(dt):
        # Sleep until the exact start of the next minute
        return max(1.0, 60.0 - dt.second - (dt.microsecond / 1_000_000.0))

    # Advance minute by minute to find next active slot
    cursor = dt.replace(second=0, microsecond=0) + timedelta(minutes=1)
    while not is_active_minute(cursor):
        cursor += timedelta(minutes=1)

    delta = (cursor - dt).total_seconds()
    return max(1.0, delta)


def clean_text(text: str) -> str:
    """Cleans up whitespace and newlines from parsed cell text."""
    if not text:
        return ""
    return " ".join(text.strip().split())


def parse_page_rows(html_content: str, page_info: dict) -> list[dict]:
    """
    Parses the CISIA calendar HTML and returns list of standardized row dictionaries.
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
    for tr in tbody.find_all("tr", recursive=False):
        tds = tr.find_all("td")
        if len(tds) < 8:
            continue

        # Column indices:
        # 0: MODALITÀ
        # 1: UNIVERSITÀ
        # 2: REGIONE / STATO ESTERO
        # 3: CITTÀ
        # 4: FINE ISCRIZIONI
        # 5: POSTI
        # 6: STATO
        # 7: DATA TEST

        modalita = clean_text(tds[0].get_text())
        universita = clean_text(tds[1].get_text())
        regione = clean_text(tds[2].get_text())
        citta = clean_text(tds[3].get_text())
        fine_iscrizioni = clean_text(tds[4].get_text())
        posti = clean_text(tds[5].get_text())
        stato = clean_text(tds[6].get_text()).upper()
        data_test = clean_text(tds[7].get_text())

        # Create unique row identity key
        key = f"{page_info['name']}|{modalita}|{universita}|{citta}|{data_test}"

        rows.append({
            "key": key,
            "test_type": page_info["name"],
            "url": page_info["url"],
            "modalita": modalita,
            "universita": universita,
            "regione": regione,
            "citta": citta,
            "fine_iscrizioni": fine_iscrizioni,
            "posti": posti,
            "stato": stato,
            "data_test": data_test
        })

    return rows


def fetch_page(page_info: dict) -> list[dict]:
    """Fetches a single CISIA page and parses its rows."""
    try:
        response = requests.get(
            page_info["url"],
            headers=config.HTTP_HEADERS,
            timeout=config.REQUEST_TIMEOUT
        )
        response.raise_for_status()
        return parse_page_rows(response.text, page_info)
    except Exception as e:
        logger.error(f"Error fetching {page_info['name']} ({page_info['url']}): {e}")
        return []


def send_ntfy_alert(row: dict, change_type: str, old_status: str = "") -> bool:
    """
    Sends a high-priority push notification via ntfy.sh.
    """
    topic = config.NTFY_TOPIC
    url = f"{config.NTFY_SERVER}/{topic}"

    title = f"🚨 Posti Disponibili! [{row['test_type']}]"
    
    if change_type == "new":
        reason_text = "Nuova data aggiunta con posti disponibili!"
    else:
        reason_text = f"Stato aggiornato: {old_status} ➔ POSTI DISPONIBILI"

    body = (
        f"📢 {reason_text}\n\n"
        f"🏛 Università: {row['universita']}\n"
        f"💻 Modalità: {row['modalita']}\n"
        f"📍 Città: {row['citta']} ({row['regione']})\n"
        f"📅 Data Test: {row['data_test']}\n"
        f"🎟 Posti: {row['posti']}\n"
        f"⏳ Fine Iscrizioni: {row['fine_iscrizioni']}\n"
        f"⚡ Stato: {row['stato']}"
    )

    headers = {
        "Title": title.encode("utf-8"),
        "Priority": config.NTFY_PRIORITY,
        "Tags": "bell,school,rotating_light",
        "Click": config.CISIA_LOGIN_URL,
        "Actions": f"view, Prenota su CISIA, {config.CISIA_LOGIN_URL}; view, Apri Calendario, {row['url']}"
    }

    try:
        res = requests.post(
            url,
            data=body.encode("utf-8"),
            headers=headers,
            timeout=10
        )
        res.raise_for_status()
        logger.info(f"Notification sent successfully to ntfy topic '{topic}' for {row['universita']} ({row['data_test']})")
        return True
    except Exception as e:
        logger.error(f"Failed to send ntfy notification: {e}")
        return False


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


def run_check_cycle(previous_state: dict[str, dict], is_first_run: bool) -> tuple[dict[str, dict], int]:
    """
    Fetches all tracked pages, compares against previous state,
    and dispatches notifications for newly available seats.
    Returns the updated state and count of alerts sent.
    """
    current_state = {}
    alerts_sent = 0

    for page in config.TRACKED_PAGES:
        logger.info(f"Checking {page['name']}...")
        rows = fetch_page(page)
        for r in rows:
            current_state[r["key"]] = r

    if not current_state:
        logger.warning("No rows fetched from any pages in this cycle. Keeping previous state.")
        return previous_state, 0

    if is_first_run and not previous_state:
        # First startup: record baseline state without notification spam
        available_count = sum(1 for r in current_state.values() if "POSTI DISPONIBILI" in r["stato"])
        logger.info(f"Initialized baseline state with {len(current_state)} total rows ({available_count} currently available).")
        save_state(current_state)
        return current_state, 0

    # Detect changes
    for key, row in current_state.items():
        is_available = "POSTI DISPONIBILI" in row["stato"]

        if key not in previous_state:
            # Condition 1: New row added with POSTI DISPONIBILI
            if is_available:
                logger.info(f"NEW ROW with available seats: {row['test_type']} | {row['universita']} | {row['data_test']}")
                if send_ntfy_alert(row, change_type="new"):
                    alerts_sent += 1
        else:
            old_row = previous_state[key]
            old_stato = old_row.get("stato", "")
            was_available = "POSTI DISPONIBILI" in old_stato

            # Condition 2: Existing row became POSTI DISPONIBILI from previous non-available status
            if is_available and not was_available:
                logger.info(f"STATUS CHANGED to available: {row['test_type']} | {row['universita']} | {row['data_test']} (Old: {old_stato})")
                if send_ntfy_alert(row, change_type="status_change", old_status=old_stato):
                    alerts_sent += 1

    save_state(current_state)
    return current_state, alerts_sent


def send_test_notification():
    """Sends a sample test alert to verify the ntfy setup."""
    sample_row = {
        "test_type": "TOLC-I (Ingegneria) [TEST]",
        "url": "https://testcisia.it/calendario.php?tolc=ingegneria",
        "modalita": "TOLC@UNI",
        "universita": "Università di Prova (Test Alert)",
        "regione": "LAZIO",
        "citta": "ROMA",
        "fine_iscrizioni": "01/09/2026",
        "posti": "10",
        "stato": "POSTI DISPONIBILI",
        "data_test": "15/09/2026"
    }
    logger.info(f"Sending test notification to topic: '{config.NTFY_TOPIC}' via {config.NTFY_SERVER}...")
    success = send_ntfy_alert(sample_row, change_type="new")
    if success:
        logger.info("Test notification delivered successfully! Check your phone/browser on ntfy.sh.")
    else:
        logger.error("Test notification failed. Please check your network and topic name.")


class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        rome_now = get_rome_now().strftime("%Y-%m-%d %H:%M:%S")
        status_data = {
            "status": "online",
            "rome_time": rome_now,
            "topic": config.NTFY_TOPIC,
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
    parser.add_argument("--test-notify", action="store_true", help="Send a test notification to ntfy and exit.")
    parser.add_argument("--reset-state", action="store_true", help="Delete state.json before running.")
    args = parser.parse_args()

    if args.test_notify:
        send_test_notification()
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
    logger.info(f" Active Hours: {config.START_HOUR:02d}:{config.START_MINUTE:02d} to {config.END_HOUR:02d}:{config.END_MINUTE:02d}")
    logger.info(f" Active Windows: :55-:05 and :25-:35 every minute")
    logger.info(f" ntfy Server: {config.NTFY_SERVER}")
    logger.info(f" ntfy Topic:  {config.NTFY_TOPIC}")
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
            logger.error(f"Unexpected error in main loop: {e}", exc_info=True)
            time.sleep(30)


if __name__ == "__main__":
    main()
