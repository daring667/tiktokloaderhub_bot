#!/bin/bash
# Sets up the bot as a systemd service plus a healthcheck monitor timer.
# Usage: sudo bash deploy/setup_monitoring.sh

set -e

echo "TikTok Bot: systemd + monitoring setup"
echo "======================================="

if [ "$EUID" -ne 0 ]; then
   echo "This script must be run as root (sudo)"
   exit 1
fi

RUN_USER="${RUN_USER:-droid}"
PROJECT_DIR="${PROJECT_DIR:-/home/$RUN_USER/TiktokBot/TT}"
MONITOR_SCRIPT="$PROJECT_DIR/deploy/monitor/tiktokbot_monitor.py"
CONFIG_FILE="/etc/tiktokbot-monitor.env"
CONFIG_EXAMPLE="$PROJECT_DIR/deploy/tiktokbot-monitor.env.example"

if [ ! -d "$PROJECT_DIR" ]; then
    echo "Project directory not found at $PROJECT_DIR"
    echo "Set RUN_USER / PROJECT_DIR env vars if your layout differs, e.g.:"
    echo "  sudo RUN_USER=myuser PROJECT_DIR=/home/myuser/tiktokbot bash deploy/setup_monitoring.sh"
    exit 1
fi

if [ ! -x "$PROJECT_DIR/venv/bin/python" ]; then
    echo "No virtualenv found at $PROJECT_DIR/venv — create it first:"
    echo "  python3 -m venv $PROJECT_DIR/venv && $PROJECT_DIR/venv/bin/pip install -r $PROJECT_DIR/requirements.txt"
    exit 1
fi

echo "Installing bot service..."
sed -e "s#{{PROJECT_DIR}}#$PROJECT_DIR#g" -e "s#{{RUN_USER}}#$RUN_USER#g" \
    "$PROJECT_DIR/deploy/systemd/tiktokbot.service" > /etc/systemd/system/tiktokbot.service
echo "Bot service installed"

if [ ! -f "$MONITOR_SCRIPT" ]; then
    echo "Monitor script not found at $MONITOR_SCRIPT"
    exit 1
fi

echo "Installing monitor script to /usr/local/bin/..."
cp "$MONITOR_SCRIPT" /usr/local/bin/tiktokbot_monitor.py
chmod 755 /usr/local/bin/tiktokbot_monitor.py
echo "Monitor script installed"

if [ -f "$CONFIG_FILE" ]; then
    echo "Config file $CONFIG_FILE already exists — skipping (edit manually if needed)"
else
    echo "Creating config file at $CONFIG_FILE..."
    cp "$CONFIG_EXAMPLE" "$CONFIG_FILE"
    sed -i \
        -e "s#^PYTHON_PATH=.*#PYTHON_PATH=$PROJECT_DIR/venv/bin/python#" \
        -e "s#^PROJECT_DIR=.*#PROJECT_DIR=$PROJECT_DIR#" \
        "$CONFIG_FILE"
    chmod 600 "$CONFIG_FILE"
    chown root:root "$CONFIG_FILE"
    echo "Config file created at $CONFIG_FILE"
    echo "IMPORTANT: edit it and set NOTIFY_BOT_TOKEN"
fi

echo "Installing systemd units..."
cp "$PROJECT_DIR/deploy/systemd/tiktokbot-monitor.service" /etc/systemd/system/
cp "$PROJECT_DIR/deploy/systemd/tiktokbot-monitor.timer" /etc/systemd/system/
echo "Systemd units installed"

echo "Reloading systemd..."
systemctl daemon-reload

echo "Enabling and starting bot service..."
systemctl enable --now tiktokbot.service

echo "Enabling and starting monitor timer..."
systemctl enable --now tiktokbot-monitor.timer

echo ""
echo "======================================="
echo "Setup complete"
echo "======================================="
echo ""
echo "Next steps:"
echo "1. Edit $CONFIG_FILE and set NOTIFY_BOT_TOKEN (from @BotFather)"
echo ""
echo "2. Verify:"
echo "   systemctl status tiktokbot.service"
echo "   systemctl list-timers tiktokbot-monitor.timer"
echo ""
echo "3. Logs:"
echo "   journalctl -u tiktokbot.service -f"
echo "   journalctl -u tiktokbot-monitor.service -f"
echo ""
echo "See deploy/README_MONITORING.md for troubleshooting and advanced config."
