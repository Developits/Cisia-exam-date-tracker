# 🎓 CISIA TOLC Seat Availability Tracker & Interactive Filter Bot

An automated Python system that monitors CISIA test calendar pages (**TOLC-I Engineering**, **TOLC-E Economics**, and **CEnT-S English**). It detects newly opened test seats for home-based tests (**TOLC@HOME** / **CENT@HOME**) and sends instant Telegram push notifications with direct 1-click booking buttons.

Includes an **Interactive Telegram Bot** where any student can set up personalized filters (exam type, target university, specific date range, and tracking duration), manage multiple trackers, and receive tailored seat alerts.

---

## ⚡ Features

### 1. 🤖 Interactive Personalized Filter Bot
- **Step-by-Step Inline Wizard**:
  - **Exam Type**: Choose between `TOLC-I (Engineering)`, `TOLC-E (Economics)`, `CEnT-S (English)`, or `All Exams`.
  - **University**: Select from popular university buttons (Sapienza, Bologna, Polimi, Pisa, Padua, Turin) or type any custom university with **Smart Fuzzy & Alias Matching** (e.g., *Sapienza*, *sepienga*, *Roma*, *unibo*, *polimi*).
  - **Date Range Window**: Select `Any Upcoming Date`, `Next 30 Days`, `Next 60 Days`, `August - September`, or enter a custom date range (e.g. `10/08/2026 - 15/09/2026` or `10/08 to 15/09`).
  - **Tracking Duration**: Set how long the filter runs (`7 Days`, `14 Days`, `30 Days`, `60 Days`, or `Indefinite / Until Stopped`).
- **Instant Availability Search**: When a user creates a filter, the bot immediately checks current CISIA calendar data and reports any matching seats already open.
- **📋 My Trackers Dashboard (`/mytrackers`)**:
  - View all active trackers with remaining days and status.
  - 1-click **Pause**, **Resume**, **Extend/Renew (+14d / +30d)**, or **Delete**.
- **⏳ Auto-Expiration & 1-Click Renewals**: Automatically alerts the user when a tracker expires with quick renewal buttons.
- **🛡 Anti-Spam Deduplication**: Prevents alert spam by enforcing cooldown periods for identical seats per user filter.

### 2. 📡 Real-Time CISIA Scraper & Broadcaster
- **Monitors 3 English Calendars**:
  - `TOLC-I (Engineering)`: `https://testcisia.it/calendario.php?tolc=ingegneria&l=gb`
  - `TOLC-E (Economics)`: `https://testcisia.it/calendario.php?tolc=economia&l=gb`
  - `CEnT-S (English)`: `https://testcisia.it/calendario.php?tolc=cents&l=gb&lingua=inglese`
- **Instant Alerts**:
  - Detects **new test dates added** with format `@HOME` and state `AVAILABLE SEATS`.
  - Detects **existing `@HOME` test dates reopened** from `NOT LONGER AVAILABLE` to `AVAILABLE SEATS`.
- **Continuous Italian Time Scheduler**:
  - Operates every day from **06:00 to 22:00 (6:00 AM – 10:00 PM)** Italian time (`Europe/Rome`).
  - Checks **every 1 minute continuously** (60s loop).
  - Sleeps automatically at night from 22:01 to 05:59 until 06:00:00 next morning (0% CPU).
- **Rich Telegram Notifications**:
  - University, format (`TOLC@HOME`), city/region, test date, available seats, and booking deadline.
  - Interactive inline action buttons: **🚀 Book on CISIA** and **📅 Open Calendar**.

---

## 📱 Telegram Bot Setup

1. **Create Bot Token**:
   - Open Telegram, message `@BotFather`, send `/newbot`, and follow prompts to get your **Bot Token**.
2. **Configure `.env`**:
   ```bash
   # Dedicated Interactive Filter Bot Token (or reuse main bot token)
   FILTER_BOT_TOKEN=your_bot_token_from_botfather

   # Optional Global Broadcast Chat IDs (comma-separated)
   TELEGRAM_BOT_TOKEN=your_bot_token_from_botfather
   TELEGRAM_CHAT_ID=1720364178

   # Developer Chat ID for crash alerts (Mr Marshmallow)
   DEVELOPER_CHAT_ID=1720364178
   ```

---

## 🤖 Telegram Bot Commands

| Command | Action |
| :--- | :--- |
| `/start` or `/menu` | Open the interactive main menu and dashboard |
| `/new` | Launch the step-by-step filter creation wizard |
| `/mytrackers` or `/list` | View, pause, resume, extend, or delete active trackers |
| `/check` | Perform an instant lookup of all currently available `@HOME` seats |
| `/help` | View instructions and how the tracker works |

---

## 🛠️ Local Usage & Testing

### Installation
```bash
pip install -r requirements.txt
```

### CLI Commands

- **Start Scraper + Interactive Bot**:
  ```bash
  python tracker.py
  ```

- **Run Single Check Cycle**:
  ```bash
  python tracker.py --once
  ```

- **Send a Test Notification**:
  ```bash
  python tracker.py --test-notify
  ```

- **Run Full Automated Test Suite**:
  ```bash
  python -m unittest discover -s . -p "test_*.py"
  ```

---

## ☁️ 24/7 Free Cloud Hosting on Render.com

1. Go to **[dashboard.render.com](https://dashboard.render.com)**.
2. Click **New +** ➔ **Web Service** and connect this repository.
3. Configure settings:
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python tracker.py`
   - **Instance Type**: **Free**
4. Under **Environment Variables**, add:
   - `FILTER_BOT_TOKEN`: `your_bot_token`
   - `TELEGRAM_BOT_TOKEN`: `your_bot_token`
   - `TELEGRAM_CHAT_ID`: `your_chat_id`
   - `DEVELOPER_CHAT_ID`: `1720364178`
5. Click **Deploy Web Service**.
6. Set up a free 5-minute HTTP monitor at [cron-job.org](https://cron-job.org) pinging your Render URL (`https://your-service.onrender.com/`) to keep it awake 24/7!
