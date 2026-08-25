import os
from dotenv import load_dotenv

load_dotenv()

# Telegram Bot Settings
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ntfy.sh Settings (Optional secondary notification channel)
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "")
NTFY_SERVER = os.getenv("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
NTFY_PRIORITY = os.getenv("NTFY_PRIORITY", "high")  # 'default', 'high', 'urgent'

# Target CISIA Calendar Pages
TRACKED_PAGES = [
    {
        "name": "TOLC-I (Ingegneria)",
        "url": "https://testcisia.it/calendario.php?tolc=ingegneria"
    },
    {
        "name": "TOLC-E (Economia)",
        "url": "https://testcisia.it/calendario.php?tolc=economia"
    },
    {
        "name": "CEnT-S (Inglese)",
        "url": "https://testcisia.it/calendario.php?tolc=cents&lingua=inglese"
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
