# 🎓 CISIA TOLC Seat Availability Tracker & Telegram Bot

An automated Python tracker that monitors CISIA TOLC test calendar pages (**TOLC-I Engineering**, **TOLC-E Economics**, and **CEnT-S English**). It detects newly opened test seats for home-based tests (**TOLC@HOME** / **CENT@HOME**) and sends instant Telegram push notifications with direct booking buttons.

---

## ⚡ Features

- **Monitors 3 English Calendars**:
  - `TOLC-I (Engineering)`: `https://testcisia.it/calendario.php?tolc=ingegneria&l=gb`
  - `TOLC-E (Economics)`: `https://testcisia.it/calendario.php?tolc=economia&l=gb`
  - `CEnT-S (English)`: `https://testcisia.it/calendario.php?tolc=cents&l=gb&lingua=inglese`
- **Instant Telegram Alerts**:
  1. **New test date added** with format `@HOME` and state `AVAILABLE SEATS`.
  2. **Existing `@HOME` test date reopened** from `NOT LONGER AVAILABLE`, `NOT BOOKABLE`, or `BOOKINGS CLOSED` to `AVAILABLE SEATS`.
  3. **Multi-Account Broadcast**: Sends notifications simultaneously to all configured Telegram chat IDs.
- **Continuous Italian Time Scheduler**:
  - Operates every day from **06:00 to 22:00 (6:00 AM – 10:00 PM)** Italian time (`Europe/Rome`).
  - Checks **every 1 minute continuously** (60s loop).
  - Sleeps automatically at night from 22:01 to 05:59 until 06:00:00 next morning (0% CPU).
- **Rich Telegram Notifications**:
  - University, format (`TOLC@HOME`), city/region, test date, available seats, and booking deadline.
  - Interactive inline action buttons: **🚀 Book on CISIA** and **📅 Open Calendar**.

---

## 📱 Telegram Bot Setup (100% Free)

1. **Create Bot**: Open Telegram, message `@BotFather`, send `/newbot`, and copy your **Bot Token**.
2. **Get Chat IDs**: Open `@userinfobot` in Telegram and get your numeric **Chat ID**.
   *(Make sure each user sends `/start` to your bot).*
3. Set your environment variables in `.env`:
   ```bash
   TELEGRAM_BOT_TOKEN=your_bot_token_from_botfather
   TELEGRAM_CHAT_ID=1720364178,5050910753,5632118722
   ```

---

## 🛠️ Local Usage & Testing

### Installation
```bash
pip install -r requirements.txt
```

### CLI Commands

- **Send a Test Telegram Notification**:
  ```bash
  python tracker.py --test-notify
  ```

- **Run Single Check Cycle**:
  ```bash
  python tracker.py --once
  ```

- **Start Continuous Scheduler**:
  ```bash
  python tracker.py
  ```

- **Run Automated Test Suite**:
  ```bash
  python test_tracker.py
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
   - `TELEGRAM_BOT_TOKEN`: `your_bot_token`
   - `TELEGRAM_CHAT_ID`: `1720364178,5050910753,5632118722`
5. Click **Deploy Web Service**.
6. Set up a free 5-minute HTTP monitor at [cron-job.org](https://cron-job.org) pinging your Render URL (`https://cisia-exam-date-tracker.onrender.com/`) to keep it awake 24/7!
