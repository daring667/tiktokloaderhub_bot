#!/usr/bin/env python3
"""
Healthcheck script for TikTok/YouTube downloader bot.
Tests if the bot can successfully download a video.

Exit codes:
  0 - OK, download successful
  1 - Exception occurred
  2 - File not created
  3 - File is empty
"""

import sys
import os
import shutil
import tempfile
import traceback
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.downloader import download_video

# Configuration from environment
TEST_URL = os.getenv("HEALTHCHECK_TEST_URL", "https://www.tiktok.com/@jungkook/video/7655377348442787093")
TIMEOUT = int(os.getenv("HEALTHCHECK_TIMEOUT", "180"))


async def main():
    """Run healthcheck."""
    # A fresh, uniquely-owned directory per run avoids permission clashes when
    # this script is invoked by different users (e.g. root via the monitor
    # timer, and a regular user via CI) against a shared /tmp path.
    output_dir = Path(tempfile.mkdtemp(prefix="tiktokbot_healthcheck_"))
    try:
        start = time.time()

        # Generate unique filename based on timestamp
        filename = f"healthcheck_{int(time.time())}.mp4"
        output_path = str(output_dir / filename)
        
        print(f"[healthcheck] Starting download from: {TEST_URL}")
        print(f"[healthcheck] Output: {output_path}")
        print(f"[healthcheck] Timeout: {TIMEOUT}s")
        
        # Download video using same logic as bot
        result_path = await download_video(TEST_URL, output_path, timeout=TIMEOUT)
        
        # Verify file exists
        if not result_path or not Path(result_path).exists():
            print("[healthcheck] FAIL: file not created")
            return 2
        
        # Verify file is not empty
        file_size = Path(result_path).stat().st_size
        if file_size == 0:
            print("[healthcheck] FAIL: file is empty")
            return 3
        
        duration = time.time() - start
        print(f"[healthcheck] OK: downloaded {file_size} bytes in {duration:.1f}s")
        return 0

    except Exception as e:
        print(f"[healthcheck] FAIL: exception: {e}")
        traceback.print_exc()
        return 1
    finally:
        shutil.rmtree(output_dir, ignore_errors=True)


if __name__ == "__main__":
    import asyncio
    sys.exit(asyncio.run(main()))
