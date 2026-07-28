# TikTok Bot Monitoring Setup Guide

## Overview

This monitoring setup provides:
- **Health checks** to verify the bot is actually downloading videos
- **Auto-restart** when the service fails or becomes unresponsive
- **Telegram notifications** when issues are detected
- **Automatic recovery** with minimal manual intervention

The monitor runs every 5 minutes and checks:
1. Is the systemd service active?
2. Can the bot download a test video within the timeout?

If either check fails, the service is automatically restarted and you receive a Telegram notification with logs.

---

## Installation Steps

### 1. Prepare Configuration File

Create `/etc/tiktokbot-monitor.env` with your settings:

```bash
sudo tee /etc/tiktokbot-monitor.env > /dev/null <<'EOF'
# Telegram bot credentials for notifications
NOTIFY_BOT_TOKEN=YOUR_NOTIFY_BOT_TOKEN_HERE
NOTIFY_CHAT_ID=YOUR_CHAT_ID_HERE

# A stable test URL for healthcheck.
# Pick a durable, currently-live video from a large verified account —
# niche/old videos can go stale on the CDN and cause false-positive restarts.
HEALTHCHECK_TEST_URL=https://www.tiktok.com/@tiktok/video/...

# Systemd service name to monitor
SERVICE_NAME=tiktokbot.service

# Python interpreter path
PYTHON_PATH=/home/youruser/TT/venv/bin/python

# Project directory
PROJECT_DIR=/home/youruser/TT

# Healthcheck timeout in seconds
HEALTHCHECK_TIMEOUT=180

# Log settings
LOG_TAIL_LINES=50
LOG_LOOK_BACK=10m
EOF
```

**Important:** Replace `YOUR_NOTIFY_BOT_TOKEN_HERE` with your actual Telegram bot token.

To keep the file secure:
```bash
sudo chmod 640 /etc/tiktokbot-monitor.env
sudo chown root:root /etc/tiktokbot-monitor.env
```

### 2. Copy Monitor Script

```bash
sudo cp deploy/monitor/tiktokbot_monitor.py /usr/local/bin/tiktokbot_monitor.py
sudo chmod 755 /usr/local/bin/tiktokbot_monitor.py
```

### 3. Install Systemd Units

```bash
# Copy files
sudo cp deploy/systemd/tiktokbot-monitor.service /etc/systemd/system/
sudo cp deploy/systemd/tiktokbot-monitor.timer /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload

# Enable timer to start at boot
sudo systemctl enable tiktokbot-monitor.timer

# Start the timer
sudo systemctl start tiktokbot-monitor.timer
```

### 4. Verify Installation

Check timer status:
```bash
sudo systemctl list-timers tiktokbot-monitor.timer
```

Check service status:
```bash
sudo systemctl status tiktokbot-monitor.timer
sudo systemctl status tiktokbot-monitor.service
```

---

## Configuration Details

### Environment Variables

All configuration goes into `/etc/tiktokbot-monitor.env`:

| Variable | Required | Default | Notes |
|----------|----------|---------|-------|
| `NOTIFY_BOT_TOKEN` | Yes* | - | Telegram bot token; get from @BotFather |
| `NOTIFY_CHAT_ID` | No | - | Your Telegram chat ID for notifications |
| `HEALTHCHECK_TEST_URL` | Yes | - | A stable video URL (TikTok or YouTube) |
| `SERVICE_NAME` | No | tiktokbot.service | Name of systemd service to monitor |
| `PYTHON_PATH` | No | /home/youruser/TT/venv/bin/python | Python interpreter |
| `PROJECT_DIR` | No | /home/youruser/TT | Project root directory |
| `HEALTHCHECK_TIMEOUT` | No | 180 | Download timeout in seconds |
| `LOG_TAIL_LINES` | No | 50 | How many log lines to include in notifications |
| `LOG_LOOK_BACK` | No | 10m | How far back to look in journalctl (e.g., "10m", "1h") |

*NOTIFY_BOT_TOKEN is optional. If not set, Telegram notifications will be skipped (but restart still happens).

### Healthcheck Script

The `healthcheck.py` script:
- Downloads a test video using the same logic as the production bot
- Returns exit codes:
  - `0` = Success
  - `1` = Exception/network error
  - `2` = File not created
  - `3` = File is empty

### Timer Schedule

Default schedule (from `tiktokbot-monitor.timer`):
- First run: 2 minutes after boot
- Subsequent runs: Every 5 minutes

To change the schedule, edit `/etc/systemd/system/tiktokbot-monitor.timer`:
```ini
[Timer]
OnBootSec=2min        # Change this for boot delay
OnUnitActiveSec=5min  # Change this for check interval
```

Then reload:
```bash
sudo systemctl daemon-reload
sudo systemctl restart tiktokbot-monitor.timer
```

---

## Monitoring & Troubleshooting

### View Monitor Logs

Real-time logs:
```bash
sudo journalctl -u tiktokbot-monitor.service -f
```

Last 50 lines:
```bash
sudo journalctl -u tiktokbot-monitor.service -n 50
```

Since a specific time:
```bash
sudo journalctl -u tiktokbot-monitor.service --since "30 minutes ago"
```

### View Bot Service Logs

```bash
sudo journalctl -u tiktokbot.service -f
```

### Manual Test

Run healthcheck manually:
```bash
export HEALTHCHECK_TEST_URL="https://www.tiktok.com/@tiktok/video/..."
export HEALTHCHECK_TIMEOUT=180
/home/youruser/TT/venv/bin/python /home/youruser/TT/healthcheck.py
echo $?
```

Run monitor manually:
```bash
sudo /usr/local/bin/tiktokbot_monitor.py
echo $?
```

### Manual Service Restart

If you need to restart the bot service manually:
```bash
sudo systemctl restart tiktokbot.service
```

### Stop Monitoring

Temporarily:
```bash
sudo systemctl stop tiktokbot-monitor.timer
```

Permanently:
```bash
sudo systemctl disable tiktokbot-monitor.timer
sudo systemctl stop tiktokbot-monitor.timer
```

---

## Security Notes

1. **Token Protection**: The environment file `/etc/tiktokbot-monitor.env` contains your Telegram bot token.
   - Owned by root with read-only for the monitor user
   - Never commit to version control
   - Keep backups secure

2. **Telegram Bot**: Use a dedicated "notify" bot separate from your main bot.
   - This limits damage if credentials are leaked
   - Easy to rotate if needed

3. **Monitor Permissions**: `deploy/systemd/tiktokbot-monitor.service` has no `User=` line, so it runs as root — that's what lets it call `systemctl restart` on the bot service without extra setup. If you'd rather run it as a non-root user, add `User=youruser` to the service file and grant that user passwordless sudo for the restart command:
     ```bash
     sudo visudo
     # Add: youruser ALL = NOPASSWD: /bin/systemctl restart tiktokbot.service
     ```

---

## Advanced Customization

### Change Healthcheck URL

To test with YouTube instead of TikTok:
```bash
HEALTHCHECK_TEST_URL="https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

### Increase Check Frequency

For more aggressive monitoring (every 2 minutes):
```bash
# Edit the timer
sudo systemctl edit --full tiktokbot-monitor.timer
# Change: OnUnitActiveSec=2min
sudo systemctl daemon-reload
sudo systemctl restart tiktokbot-monitor.timer
```

### Add Custom Restart Logic

Modify `/usr/local/bin/tiktokbot_monitor.py` to:
- Check additional conditions
- Run custom commands after restart
- Change notification formatting
- Integrate with other monitoring systems

---

## Telegram Notifications

### Create a Notify Bot

1. Talk to @BotFather on Telegram
2. Create a new bot (`/newbot` command)
3. Get your bot token
4. Get your chat ID:
   - Send a message to your bot
   - Visit `https://api.telegram.org/bot<TOKEN>/getUpdates`
   - Find your chat ID in the response

### Notification Content

Each notification includes:
- Issue summary (service down, healthcheck failed)
- Host name and timestamp
- Recent service logs (last 10 minutes, up to 50 lines)
- Action taken (restart attempted)

---

## Performance Impact

The monitoring system is lightweight:
- Monitor runs every **5 minutes** (not continuously)
- Each check takes ~2-3 seconds (plus healthcheck download time)
- Uses **journalctl** for logs (system-native, no extra overhead)
- HTTP notification to Telegram is asynchronous

**Total impact**: Negligible (0.1-1% CPU during checks).

---

## Rollback / Uninstall

If you need to remove monitoring:

```bash
# Stop and disable
sudo systemctl disable tiktokbot-monitor.timer
sudo systemctl stop tiktokbot-monitor.timer

# Remove files
sudo rm /etc/systemd/system/tiktokbot-monitor.service
sudo rm /etc/systemd/system/tiktokbot-monitor.timer
sudo rm /usr/local/bin/tiktokbot_monitor.py

# Reload systemd
sudo systemctl daemon-reload

# Optionally remove config
sudo rm /etc/tiktokbot-monitor.env
```

---

## FAQ

**Q: What if Telegram notifications don't work?**  
A: Check:
1. Is NOTIFY_BOT_TOKEN valid?
2. Is NOTIFY_CHAT_ID correct?
3. Monitor logs: `journalctl -u tiktokbot-monitor.service`
4. Test manually: `python -c "import urllib.request; ..."`

**Q: Can I use this for multiple bots?**  
A: Yes! Create separate config files and service directories:
```bash
/etc/tiktokbot-monitor.env          # For tiktokbot.service
/etc/other-bot-monitor.env          # For other-bot.service
/etc/systemd/system/other-bot-monitor.service
/etc/systemd/system/other-bot-monitor.timer
```

**Q: How do I know if monitoring is actually running?**  
A: Check timer status and logs:
```bash
sudo systemctl list-timers tiktokbot-monitor.timer
sudo journalctl -u tiktokbot-monitor.timer
```

**Q: The healthcheck keeps failing. What do I check?**  
A: 1. Is the test URL valid/working?
2. Does the bot have internet access?
3. Are dependencies installed (requests, yt-dlp)?
4. Run healthcheck manually to see the exact error

**Q: Can I increase verbosity?**  
A: Add debug prints to `/usr/local/bin/tiktokbot_monitor.py` and check logs:
```bash
sudo journalctl -u tiktokbot-monitor.service -f
```

---

## Support

If you encounter issues:
1. Check monitor logs: `journalctl -u tiktokbot-monitor.service -n 100`
2. Check bot logs: `journalctl -u tiktokbot.service -n 100`
3. Run healthcheck manually with the test URL
4. Verify configuration in `/etc/tiktokbot-monitor.env`
