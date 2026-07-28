# Deployment & monitoring

Everything needed to run the bot as a systemd service on Linux, with a healthcheck monitor that auto-restarts it on failure. No Docker involved — the bot runs directly on the host inside a venv.

## Quick start

```bash
# 1. Clone the repo and create the venv
git clone <this repo> TT && cd TT
python3 -m venv venv
./venv/bin/pip install -r requirements.txt

# 2. Create .env (see .env.example) with your bot's credentials

# 3. Install + start bot service and monitor in one go
sudo bash deploy/setup_monitoring.sh
# by default this assumes user "droid" and path /home/droid/TiktokBot/TT —
# override with RUN_USER / PROJECT_DIR env vars if yours differs:
#   sudo RUN_USER=myuser PROJECT_DIR=/home/myuser/TT bash deploy/setup_monitoring.sh

# 4. Set the Telegram token for monitor alerts
sudo nano /etc/tiktokbot-monitor.env   # set NOTIFY_BOT_TOKEN

# 5. Verify
sudo systemctl status tiktokbot.service
sudo systemctl list-timers tiktokbot-monitor.timer
```

### Full documentation

- **[README_MONITORING.md](README_MONITORING.md)** — complete guide with troubleshooting, FAQ, and advanced configuration

## What's included

- `systemd/tiktokbot.service` — the bot itself, template with `{{RUN_USER}}` / `{{PROJECT_DIR}}` placeholders filled in by the setup script
- `systemd/tiktokbot-monitor.service` + `systemd/tiktokbot-monitor.timer` — healthcheck monitor, runs every 5 minutes
- `monitor/tiktokbot_monitor.py` — checks the bot service is active, runs a real download as a healthcheck, restarts the service and sends a Telegram alert on failure
- `tiktokbot-monitor.env.example` — config template for `/etc/tiktokbot-monitor.env`
- `setup_monitoring.sh` — installs and enables all of the above

## How it works

```
Every 5 minutes:
    ↓
Monitor checks: is the bot service active?
    ├─ NO  → restart it → notify
    └─ YES → run healthcheck (download a real video)
              ├─ success → nothing to do
              └─ fail    → restart it → notify
```

## Verification

```bash
sudo systemctl status tiktokbot.service
sudo systemctl list-timers tiktokbot-monitor.timer
sudo /usr/local/bin/tiktokbot_monitor.py     # manual run
sudo journalctl -u tiktokbot.service -f
sudo journalctl -u tiktokbot-monitor.service -f
```

## Configuration

All monitor configuration lives in `/etc/tiktokbot-monitor.env` (outside the repo, never committed):

```bash
NOTIFY_BOT_TOKEN=YOUR_BOT_TOKEN_HERE
NOTIFY_CHAT_ID=YOUR_CHAT_ID_HERE
HEALTHCHECK_TEST_URL=https://www.tiktok.com/@...
SERVICE_NAME=tiktokbot.service
PYTHON_PATH=/home/youruser/TT/venv/bin/python
PROJECT_DIR=/home/youruser/TT
HEALTHCHECK_TIMEOUT=180
```

`PYTHON_PATH` and `PROJECT_DIR` are filled in automatically by `setup_monitoring.sh`. `HEALTHCHECK_TEST_URL` matters more than it looks: pick a durable video (a large verified account, not a random clip) — a video whose CDN link goes stale will make the monitor think the bot is broken and restart it every 5 minutes for no reason.

See `tiktokbot-monitor.env.example` for the full list with descriptions.

## Troubleshooting

**Monitor not running?**
```bash
sudo systemctl status tiktokbot-monitor.timer
sudo journalctl -u tiktokbot-monitor.timer -n 20
```

**Notifications not working?**
```bash
sudo journalctl -u tiktokbot-monitor.service | grep -i telegram
# check NOTIFY_BOT_TOKEN in /etc/tiktokbot-monitor.env
```

**Service keeps restarting?**
```bash
# run the healthcheck manually to see the real error
export HEALTHCHECK_TEST_URL="https://..."
./venv/bin/python healthcheck.py
echo $?
```

See [README_MONITORING.md](README_MONITORING.md) for the complete guide.

## More info

- Healthcheck script: [../healthcheck.py](../healthcheck.py)
- Main bot: [../main.py](../main.py)
