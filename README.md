# 🎓 CISIA TOLC Seat Availability Tracker & Alert System

An automated monitor for CISIA TOLC test calendar pages (**TOLC-I Ingegneria**, **TOLC-E Economia**, and **CEnT-S Inglese**). It tracks test seat availability in real time and sends instant push notifications with alert sounds to your mobile phone or browser via **ntfy.sh**.

---

## ⚡ Features

- **Monitors 3 Calendars**:
  - `TOLC-I (Ingegneria)`: `https://testcisia.it/calendario.php?tolc=ingegneria`
  - `TOLC-E (Economia)`: `https://testcisia.it/calendario.php?tolc=economia`
  - `CEnT-S (Inglese)`: `https://testcisia.it/calendario.php?tolc=cents&lingua=inglese`
- **Instant Alerts**:
  1. **New row added** with `POSTI DISPONIBILI`.
  2. **Existing row status changes** from `POSTI ESAURITI`, `ISCRIZIONI CHIUSE`, or `ISCRIZIONI CONCLUSE` to `POSTI DISPONIBILI`.
- **Smart Italian Time Scheduler**:
  - Operates **06:55 to 22:05** (Rome time / CET & CEST).
  - Checks every minute during **30-minute interval windows**: `:55 to :05` and `:25 to :35`.
  - Smart sleep calculation during off-peak times (0% idle CPU usage).
- **Rich Mobile Notifications**:
  - University name, test mode (`TOLC@UNI` / `TOLC@CASA`), city, test date, available seats, and registration deadline.
  - Direct "Prenota Ora" (Book Now) action button to open CISIA login instantly.
  - High priority with phone ringing/vibration.

---

## 📱 1. Setup Mobile Notifications (30 Seconds, 100% Free)

You can receive push notifications on your phone with **zero account creation**:

1. **Install ntfy**:
   - **Android**: Download [ntfy on Google Play](https://play.google.com/store/apps/details?id=io.heckel.ntfy) or F-Droid.
   - **iOS**: Download [ntfy on App Store](https://apps.apple.com/app/ntfy/id1625396347).
   - **Web / Desktop**: Or simply open [ntfy.sh](https://ntfy.sh) in any browser.
2. **Subscribe to your topic**:
   - Open the ntfy app, tap `+` (Subscribe to topic), and enter your chosen topic name (e.g. `my_cisia_alerts_2026`).
3. Set that topic name in `.env`:
   ```bash
   NTFY_TOPIC=my_cisia_alerts_2026
   ```

---

## 🛠️ 2. Local Setup & Testing

### Installation
```bash
pip install -r requirements.txt
```

### Configuration
Copy `.env.example` to `.env` and set your desired topic name:
```bash
# On Windows PowerShell:
Copy-Item .env.example .env

# On Linux/macOS:
cp .env.example .env
```

### CLI Commands

- **Send a Test Notification** (to verify your phone receives it):
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

## ☁️ 3. Where to Host for Free (24/7 Cloud Options)

Here are the best **100% free** ways to run the tracker 24/7 without keeping your computer on:

### 🌟 Option A: Koyeb (Recommended - 100% Free Always-On)
[Koyeb.com](https://www.koyeb.com) provides a free tier with 1 web service/worker that runs 24/7 with zero sleeping.
1. Push this folder to a GitHub repository.
2. Create a free account at [koyeb.com](https://www.koyeb.com).
3. Click **Create Service** > **GitHub**, select your repository.
4. Set Environment Variables:
   - `NTFY_TOPIC`: `your_topic_name`
5. Click **Deploy**. Koyeb will build the Docker container and run your tracker 24/7!

---

### 🌟 Option B: Hugging Face Spaces (100% Free Docker Container)
[Hugging Face](https://huggingface.co/spaces) offers free CPU Docker spaces that run continuously 24/7:
1. Create a free account at [huggingface.co](https://huggingface.co).
2. Go to **Spaces** > **Create new Space**.
3. Select **Docker** (Blank).
4. Upload or git-push the files (`Dockerfile`, `tracker.py`, `config.py`, `requirements.txt`).
5. Under Space Settings > **Variables and secrets**, add `NTFY_TOPIC` = `your_topic_name`.
6. Your space will build and run continuously in the cloud for free.

---

### 🌟 Option C: Render.com (Free Tier)
1. Sign up at [render.com](https://render.com).
2. Click **New +** > **Background Worker** or **Web Service**.
3. Connect your GitHub repo.
4. Set runtime to **Python 3** (or Docker).
5. Build Command: `pip install -r requirements.txt`
6. Start Command: `python tracker.py`
7. Add Environment Variable `NTFY_TOPIC`.

---

### 🌟 Option D: Oracle Cloud Always Free VM
1. Sign up for [Oracle Cloud Free Tier](https://www.oracle.com/cloud/free/) (Free forever AMD/ARM VM).
2. SSH into your free Ubuntu instance.
3. Clone repository and run as a systemd service:
   ```ini
   # /etc/systemd/system/cisia-tracker.service
   [Unit]
   Description=CISIA TOLC Tracker
   After=network.target

   [Service]
   Type=simple
   User=ubuntu
   WorkingDirectory=/home/ubuntu/Cisea
   ExecStart=/usr/bin/python3 /home/ubuntu/Cisea/tracker.py
   Restart=always
   RestartSec=10

   [Install]
   WantedBy=multi-user.target
   ```
4. Enable and start:
   ```bash
   sudo systemctl enable --now cisia-tracker
   ```

---

### 🖥️ Option E: Run Locally in Background (Windows / Mac / Linux)

#### Windows Background Run:
You can run it invisibly in the background using `pythonw`:
```powershell
Start-Process pythonw -ArgumentList "tracker.py"
```
Or set it in **Windows Task Scheduler** to start automatically at login.

#### Linux / macOS / Raspberry Pi Background Run:
```bash
nohup python3 tracker.py > tracker.log 2>&1 &
```
