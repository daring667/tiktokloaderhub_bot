# tests/test_bot_start.py

import os
from dotenv import load_dotenv

load_dotenv()

def test_env_vars_exist():
    assert os.getenv("BOT_TOKEN") is not None
    assert os.getenv("API_KEY") is not None
    assert os.getenv("API_HASH") is not None
