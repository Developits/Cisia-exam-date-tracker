import os
from dotenv import load_dotenv

load_dotenv()

# Telegram Bot Settings
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
# Dedicated Interactive Filter Bot Token (defaults to TELEGRAM_BOT_TOKEN if not explicitly provided)
FILTER_BOT_TOKEN = os.getenv("FILTER_BOT_TOKEN", "").strip() or TELEGRAM_BOT_TOKEN
# Developer ID for error logs and crash reports (Mr Marshmallow)
DEVELOPER_CHAT_ID = os.getenv("DEVELOPER_CHAT_ID", "1720364178")
# Throttle repeated error notifications (seconds) to prevent spam
ERROR_THROTTLE_SECONDS = int(os.getenv("ERROR_THROTTLE_SECONDS", "900"))  # 15 minutes
# Per-user alert cooldown for identical seat row (seconds)
ALERT_COOLDOWN_SECONDS = int(os.getenv("ALERT_COOLDOWN_SECONDS", "3600"))  # 1 hour
# Database path for user subscriptions and filters
DB_PATH = os.getenv("DB_PATH", "subscriptions.db")

# Target CISIA Calendar Pages (English)
TRACKED_PAGES = [
    {
        "name": "TOLC-I (Engineering)",
        "url": "https://testcisia.it/calendario.php?tolc=ingegneria&l=gb"
    },
    {
        "name": "TOLC-E (Economics)",
        "url": "https://testcisia.it/calendario.php?tolc=economia&l=gb"
    },
    {
        "name": "CEnT-S (English)",
        "url": "https://testcisia.it/calendario.php?tolc=cents&l=gb&lingua=inglese"
    }
]

# Direct login / booking page
CISIA_LOGIN_URL = "https://testcisia.it/studenti_tolc/login_sso.php"

# Timezone & Schedule configuration
TIMEZONE = "Europe/Rome"

# Daily operational window (Rome local time):
# Runs every 1 minute continuously from 06:00 to 22:00
START_HOUR = 6
START_MINUTE = 0
END_HOUR = 22
END_MINUTE = 0

# State persistence
STATE_FILE = os.getenv("STATE_FILE", "state.json")

# HTTP Request settings
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "15"))
HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache"
}
