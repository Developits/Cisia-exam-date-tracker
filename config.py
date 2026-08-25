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

# Windows of minutes in each active hour:
# Window 1: :55 to :05 (e.g. 06:55 to 07:05, 07:55 to 08:05, ..., 21:55 to 22:05)
# Window 2: :25 to :35 (e.g. 07:25 to 07:35, 08:25 to 08:35, ..., 21:25 to 21:35)
MINUTE_WINDOWS = [
    set(range(25, 36)),  # 25, 26, ..., 35
    set(range(55, 60)) | set(range(0, 6))  # 55, 56, 57, 58, 59, 0, 1, 2, 3, 4, 5
]

# Overall daily operational window (Rome local time):
# Starts at 06:55 (morning) and finishes at 22:05 (10 PM window end)
START_HOUR = 6
START_MINUTE = 55
END_HOUR = 22
END_MINUTE = 5

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
