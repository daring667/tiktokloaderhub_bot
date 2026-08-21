# Universal Telegram Bot Deployment Standard

This document is the baseline for deploying another Telegram bot on the same Debian host.
It uses a Python virtual environment, systemd, a timer-based monitor, GitHub Actions, and tests.

## 1. Required Project Contract

Every bot repository should provide:

```text
main.py                       # long-running process entrypoint
healthcheck.py                # exits 0 only when the bot is healthy
requirements.txt              # pinned or bounded runtime dependencies
.env.example                  # variable names only, no real secrets
tests/                        # pytest tests
```

Recommended:

```text
deploy/systemd/<service>.service
deploy/systemd/<service>-monitor.service
deploy/systemd/<service>-monitor.timer
deploy/monitor/<service>_monitor.py
.github/workflows/test-and-deploy.yml
```

The healthcheck must be deterministic and cheap. It must not send user-facing Telegram messages.
It should verify the real dependency that matters for the bot, return non-zero on failure, and
clean up temporary files.

## 2. Naming and Paths

Choose one unique service name per bot. For example:

```text
Project:       /home/droid/my_bot
Service:       my-bot.service
Monitor:       my-bot-monitor.service
Timer:         my-bot-monitor.timer
Config:        /etc/my-bot-monitor.env
Venv:          /home/droid/my_bot/venv
```

Never reuse `tiktokbot.service` for another bot. Never put a second bot in the first bot's
working directory or virtual environment.

## 3. Environment and Secrets

The application environment belongs in the project directory and must not be committed:

```bash
cd /home/droid/my_bot
cp .env.example .env
chmod 600 .env
```

The monitor environment belongs outside Git:

```text
/etc/my-bot-monitor.env
```

Secure it with:

```bash
sudo chown root:root /etc/my-bot-monitor.env
sudo chmod 600 /etc/my-bot-monitor.env
```

Use separate Telegram bot tokens for separate bots. A monitor notification token may be a
separate bot as well. Never paste tokens into commits, workflow files, chat messages, or logs.

## 4. Python Installation

Run once for a new project:

```bash
cd /home/droid/my_bot
python3 -m venv venv
./venv/bin/python -m pip install --upgrade pip
./venv/bin/pip install -r requirements.txt
./venv/bin/python -m pytest -q
```

Keep OS packages separate from Python packages. Declare required system packages such as
`ffmpeg` in the project README or deployment checklist.

## 5. systemd Service Rules

The application service should:

- run as the unprivileged `droid` user;
- set `WorkingDirectory` to the project root;
- use the project venv explicitly in `ExecStart`;
- use `Restart=on-failure` with a delay;
- log to journald;
- define memory limits appropriate to the bot;
- contain no Telegram token in the unit file.

Template:

```ini
[Unit]
Description=My Telegram Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=droid
WorkingDirectory=/home/droid/my_bot
ExecStart=/home/droid/my_bot/venv/bin/python main.py
Restart=on-failure
RestartSec=10
EnvironmentFile=/home/droid/my_bot/.env
StandardOutput=journal
StandardError=journal
SyslogIdentifier=my-bot

[Install]
WantedBy=multi-user.target
```

After installing or changing a unit:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now my-bot.service
sudo systemctl is-active my-bot.service
sudo journalctl -u my-bot.service -n 50 --no-pager
```

## 6. Monitor Rules

The monitor runs as root only when it must call `systemctl restart`. It should:

1. check `systemctl is-active <service>`;
2. run `<project>/healthcheck.py` with the project's venv;
3. restart the service on failure;
4. send a notification without exposing secrets;
5. write its own result to journald;
6. run from a timer, not from an infinite loop.

Example `/etc/my-bot-monitor.env`:

```bash
NOTIFY_BOT_TOKEN=REPLACE_OUTSIDE_GIT
NOTIFY_CHAT_ID=REPLACE_OUTSIDE_GIT
SERVICE_NAME=my-bot.service
PROJECT_DIR=/home/droid/my_bot
PYTHON_PATH=/home/droid/my_bot/venv/bin/python
HEALTHCHECK_TIMEOUT=120
LOG_TAIL_LINES=50
LOG_LOOK_BACK=10m
```

Example timer policy:

```ini
[Timer]
OnBootSec=2min
OnUnitActiveSec=5min
AccuracySec=30s
```

Install and verify:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now my-bot-monitor.timer
sudo systemctl list-timers my-bot-monitor.timer
sudo systemctl start my-bot-monitor.service
sudo journalctl -u my-bot-monitor.service -n 50 --no-pager
```

Do not configure a monitor to restart a service continuously without rate limiting or useful
logs. A bad token, bad URL, or broken deployment should be visible as a healthcheck failure.

## 7. GitHub Actions Contract

Every push to the production branch must:

1. check out the repository;
2. install the declared Python version and dependencies;
3. run the complete test suite;
4. deploy only after tests pass;
5. update the server checkout;
6. install dependencies;
7. restart the matching systemd service;
8. wait briefly and verify it is active;
9. run the healthcheck;
10. print service logs on failure.

Use GitHub Actions secrets for credentials. The self-hosted runner must have only the sudo
permissions it needs, preferably limited to the matching service and deployment commands.
Do not use `git reset --hard` on a server without first deciding how local edits are handled.
For production, the server checkout should be treated as immutable and local edits should be
rejected or explicitly stashed and reported.

Deployment command shape:

```bash
cd /home/droid/my_bot
git fetch origin master
git reset --hard origin/master
venv/bin/pip install -r requirements.txt
sudo systemctl restart my-bot.service
sudo systemctl is-active my-bot.service
venv/bin/python healthcheck.py
```

## 8. First-Run Checklist

For each new bot:

- [ ] repository cloned to a unique project directory;
- [ ] `.env` created from `.env.example` and set to mode `600`;
- [ ] credentials tested without printing them;
- [ ] venv created and dependencies installed;
- [ ] required OS packages installed;
- [ ] tests pass locally;
- [ ] `healthcheck.py` passes locally;
- [ ] service unit installed with the correct user and paths;
- [ ] service enabled and active;
- [ ] monitor env created under `/etc` with mode `600`;
- [ ] monitor service runs successfully once manually;
- [ ] monitor timer is enabled;
- [ ] GitHub remote uses the intended repository;
- [ ] GitHub authentication and runner permissions tested;
- [ ] push to the production branch runs tests before restart;
- [ ] rollback command is documented.

## 9. Standard Diagnostics

```bash
sudo systemctl status my-bot.service
sudo systemctl status my-bot-monitor.timer
sudo journalctl -u my-bot.service -n 100 --no-pager
sudo journalctl -u my-bot-monitor.service -n 100 --no-pager
cd /home/droid/my_bot && venv/bin/python -m pytest -q
cd /home/droid/my_bot && venv/bin/python healthcheck.py
```

If a bot is in a restart loop, stop the service before investigating:

```bash
sudo systemctl stop my-bot.service
sudo journalctl -u my-bot.service -n 200 --no-pager
```

## 10. Rollback

Keep the last known-good commit available:

```bash
cd /home/droid/my_bot
git log --oneline -10
git fetch origin
git reset --hard <known-good-commit>
sudo systemctl restart my-bot.service
venv/bin/python healthcheck.py
```

Rollback is a deployment operation, not a code deletion. Record the failed commit and the
healthcheck result before returning to the latest branch.
