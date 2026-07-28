#!/usr/bin/env python3
"""
TikTok Bot Monitor - Monitors bot health and auto-restarts on failure.

Configuration via environment file: /etc/tiktokbot-monitor.env
Expected variables:
  - NOTIFY_BOT_TOKEN: Telegram bot token for notifications
  - NOTIFY_CHAT_ID: Telegram chat ID (default: 922302725)
  - HEALTHCHECK_TEST_URL: URL to test (required)
  - SERVICE_NAME: systemd service name (default: tiktokbot.service)
  - PROJECT_DIR: Project directory (default: auto-detected)
  - PYTHON_PATH: Python interpreter (default: auto-detected virtualenv or sys.executable)
"""

import os
import sys
import subprocess
import time
import urllib.request
import urllib.error
import json
import socket

# Default environment variables (no hardcoded path defaults)
DEFAULT_CONFIG = {
    "notify_chat_id": "922302725",
    "service_name": "tiktokbot.service",
    "healthcheck_timeout": "180",
    "log_tail_lines": "50",
    "log_look_back": "10m"
}


def log(msg: str):
    """Print log message with timestamp."""
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def load_env_config(env_file: str) -> dict:
    """Load configuration from environment file and override with system environment variables."""
    config = DEFAULT_CONFIG.copy()
    
    # Try to load from configuration file
    if os.path.exists(env_file):
        try:
            with open(env_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    if '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip().lower()
                        value = value.strip().strip('"').strip("'")
                        config[key] = value
        except Exception as e:
            log(f"Error reading {env_file}: {e}")
    else:
        log(f"Warning: {env_file} not found, using defaults and environment variables")

    # Override with system environment variables (case-insensitive key mapping)
    env_keys = [
        "notify_bot_token", "notify_chat_id", "healthcheck_test_url",
        "service_name", "python_path", "project_dir",
        "healthcheck_timeout", "log_tail_lines", "log_look_back"
    ]
    for key in env_keys:
        env_val = os.environ.get(key.upper())
        if env_val is not None:
            config[key] = env_val
    
    return config


def check_service_active(service_name: str) -> bool:
    """Check if systemd service is active."""
    try:
        result = subprocess.run(
            ["systemctl", "is-active", service_name],
            capture_output=True,
            text=True,
            timeout=5
        )
        return result.returncode == 0
    except Exception as e:
        log(f"Error checking service status: {e}")
        return False


def restart_service(service_name: str) -> bool:
    """Restart systemd service."""
    try:
        log(f"Restarting service: {service_name}")
        result = subprocess.run(
            ["systemctl", "restart", service_name],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            log(f"Service {service_name} restarted successfully")
            return True
        else:
            log(f"Failed to restart service: {result.stderr}")
            return False
    except Exception as e:
        log(f"Error restarting service: {e}")
        return False


def get_service_logs(service_name: str, look_back: str, tail_lines: str) -> str:
    """Get recent logs from systemd journal."""
    try:
        result = subprocess.run(
            ["journalctl", "-u", service_name, f"--since={look_back} ago", 
             "-n", tail_lines, "--no-pager"],
            capture_output=True,
            text=True,
            timeout=10
        )
        return result.stdout
    except Exception as e:
        log(f"Error reading service logs: {e}")
        return f"(Could not read logs: {e})"


def run_healthcheck(python_path: str, project_dir: str, timeout: int, env_vars: dict) -> tuple:
    """
    Run healthcheck script.
    
    Returns:
        (exit_code, stdout_stderr)
    """
    healthcheck_script = os.path.join(project_dir, "healthcheck.py")
    
    if not os.path.exists(healthcheck_script):
        return 2, "healthcheck.py not found"
    
    try:
        env = os.environ.copy()
        env.update(env_vars)
        
        result = subprocess.run(
            [python_path, healthcheck_script],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=project_dir,
            env=env
        )
        
        output = (result.stdout + result.stderr).strip()
        return result.returncode, output
    except subprocess.TimeoutExpired:
        return 1, "healthcheck timeout"
    except Exception as e:
        return 1, f"healthcheck error: {e}"


def send_telegram_notification(bot_token: str, chat_id: str, message: str) -> bool:
    """Send notification via Telegram Bot API."""
    if not bot_token or not chat_id:
        log("Warning: NOTIFY_BOT_TOKEN or NOTIFY_CHAT_ID not configured")
        return False
    
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    
    # Truncate message to 4000 chars (Telegram has limits, and we want space for other info)
    if len(message) > 4000:
        message = message[:3900] + "\n... (truncated)"
    
    data = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML"
    }
    
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode('utf-8'),
            headers={"Content-Type": "application/json"}
        )
        
        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode('utf-8'))
            if result.get('ok'):
                log(f"Notification sent to chat {chat_id}")
                return True
            else:
                log(f"Telegram API error: {result.get('description')}")
                return False
    except urllib.error.URLError as e:
        log(f"Network error sending Telegram notification: {e}")
        return False
    except Exception as e:
        log(f"Error sending Telegram notification: {e}")
        return False


def format_notification(issue: str, action: str, logs: str, config: dict) -> str:
    """Format notification message."""
    hostname = socket.gethostname()
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    
    # Truncate logs to fit message size limit
    logs_truncated = logs
    if len(logs_truncated) > 1500:
        logs_truncated = logs_truncated[-1500:]
        logs_truncated = "...(tail)\n" + logs_truncated
    
    message = (
        f"<b>🚨 TikTok Bot Issue Detected</b>\n"
        f"<b>Host:</b> {hostname}\n"
        f"<b>Time:</b> {ts}\n"
        f"<b>Service:</b> {config.get('service_name', 'tiktokbot.service')}\n\n"
        f"<b>Issue:</b>\n{issue}\n\n"
        f"<b>Action:</b>\n{action}\n\n"
        f"<b>Recent Logs:</b>\n"
        f"<code>{logs_truncated}</code>"
    )
    
    return message


def main():
    """Main monitoring loop."""
    # Load configuration
    config = load_env_config("/etc/tiktokbot-monitor.env")
    
    service_name = config.get("service_name", "tiktokbot.service")
    healthcheck_url = config.get("healthcheck_test_url")
    healthcheck_timeout = int(config.get("healthcheck_timeout", "180"))
    notify_bot_token = config.get("notify_bot_token")
    notify_chat_id = config.get("notify_chat_id")
    log_tail_lines = config.get("log_tail_lines", "50")
    log_look_back = config.get("log_look_back", "10m")
    
    # Dynamically determine project directory if not configured
    project_dir = config.get("project_dir")
    if not project_dir:
        # Detect if we are running in the project structure
        script_dir = os.path.dirname(os.path.abspath(__file__))
        candidate_dir = os.path.abspath(os.path.join(script_dir, "..", ".."))
        if os.path.isfile(os.path.join(candidate_dir, "main.py")):
            project_dir = candidate_dir
        else:
            # Fallback to current working directory if it contains main.py
            cwd = os.getcwd()
            if os.path.isfile(os.path.join(cwd, "main.py")):
                project_dir = cwd

    # Dynamically determine python interpreter if not configured
    python_path = config.get("python_path")
    if not python_path:
        if project_dir:
            for venv_name in ["venv", "venv2", ".venv"]:
                candidate_python = os.path.join(project_dir, venv_name, "bin", "python")
                if os.path.isfile(candidate_python):
                    python_path = candidate_python
                    break
        if not python_path:
            python_path = sys.executable

    log(f"=== TikTok Bot Monitor started ===")
    log(f"Service: {service_name}")
    log(f"Project: {project_dir}")
    log(f"Python: {python_path}")
    log(f"Healthcheck URL: {healthcheck_url}")
    
    if not project_dir:
        log("ERROR: PROJECT_DIR is not configured and could not be determined automatically.")
        return 1
    
    if not healthcheck_url:
        log("ERROR: HEALTHCHECK_TEST_URL not configured")
        return 1
    
    # Step 1: Check if service is active
    if not check_service_active(service_name):
        log(f"ISSUE: Service {service_name} is NOT ACTIVE")
        
        restarted = restart_service(service_name)
        action = "Service restarted" if restarted else "Failed to restart service"
        logs = get_service_logs(service_name, log_look_back, log_tail_lines)
        
        message = format_notification(
            f"Service {service_name} was not active",
            action,
            logs,
            config
        )
        send_telegram_notification(notify_bot_token, notify_chat_id, message)
        
        return 1 if not restarted else 0
    
    log(f"Service {service_name} is ACTIVE")
    
    # Step 2: Run healthcheck
    log(f"Running healthcheck with {healthcheck_timeout}s timeout...")
    
    healthcheck_env = {
        "HEALTHCHECK_TEST_URL": healthcheck_url,
        "HEALTHCHECK_TIMEOUT": str(healthcheck_timeout)
    }
    
    hc_code, hc_output = run_healthcheck(python_path, project_dir, healthcheck_timeout, healthcheck_env)
    
    if hc_code == 0:
        log(f"HEALTHCHECK PASSED: {hc_output}")
        return 0
    
    # Healthcheck failed
    log(f"HEALTHCHECK FAILED (code {hc_code}): {hc_output}")
    
    # Interpret failure codes
    issue_map = {
        1: "Download exception/network error",
        2: "File was not created",
        3: "File is empty"
    }
    issue = issue_map.get(hc_code, f"Unknown error (code {hc_code})")
    
    # Restart service
    restarted = restart_service(service_name)
    action = "Service restarted" if restarted else "Failed to restart service"
    
    # Get logs
    logs = get_service_logs(service_name, log_look_back, log_tail_lines)
    
    # Send notification
    message = format_notification(
        f"Healthcheck failed: {issue}",
        action,
        logs,
        config
    )
    send_telegram_notification(notify_bot_token, notify_chat_id, message)
    
    return 1 if not restarted else 0


if __name__ == "__main__":
    try:
        exit_code = main()
        log(f"Monitor completed with code {exit_code}")
        sys.exit(exit_code)
    except KeyboardInterrupt:
        log("Monitor interrupted")
        sys.exit(130)
    except Exception as e:
        log(f"FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
