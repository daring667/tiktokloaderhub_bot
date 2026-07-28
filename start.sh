#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="./venv/bin/python"
if [ ! -x "$PYTHON" ]; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON=python3
  elif command -v python >/dev/null 2>&1; then
    PYTHON=python
  else
    echo "ERROR: Python interpreter not found. Install python3 or create a virtualenv."
    exit 1
  fi
fi

COOKIES_B64=""
if [ -f ".env" ]; then
  COOKIES_B64=$($PYTHON - <<'PY'
import re
text = open('.env', encoding='utf-8').read()
match = re.search(r'^COOKIES_B64=(.*)$', text, flags=re.MULTILINE)
if match:
    value = match.group(1)
    lines = text[match.end():].splitlines()
    for line in lines:
        if re.fullmatch(r'[A-Za-z0-9+/=]+', line):
            value += line
        else:
            break
    print(value.strip())
else:
    print('')
PY
)
fi

if [ -n "$COOKIES_B64" ]; then
  echo "Restoring cookies.txt from COOKIES_B64"
  printf "%s" "$COOKIES_B64" | base64 -d > cookies.txt
elif [ -f "cookies.txt" ]; then
  echo "COOKIES_B64 not set; using existing cookies.txt"
else
  echo "COOKIES_B64 not set and cookies.txt not found"
fi

mkdir -p logs

# Start the bot and save logs to file
$PYTHON main.py 2>&1 | tee -a logs/bot.log
