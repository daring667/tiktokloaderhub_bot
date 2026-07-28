"""Shared pytest fixtures."""
import asyncio
import os
import tempfile

# Pyrogram (imported transitively by services) requires an event loop at
# import time on Python 3.14+.  Create one before any other imports.
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

import pytest
from services.database import BotDatabase


@pytest.fixture()
def tmp_db(tmp_path):
    """Create a fresh BotDatabase backed by a temporary file."""
    db_path = str(tmp_path / "test.db")
    db = BotDatabase(db_path=db_path)
    yield db
    db.close()


@pytest.fixture(autouse=True)
def _no_admin_by_default(monkeypatch):
    """Handlers call report_error(), which reads ADMIN_ID/OWNER_ID and sends
    a Telegram message if one is set. Tests shouldn't depend on whatever
    happens to be in the ambient environment, so default to "no admin" —
    tests that specifically exercise report_error set these explicitly."""
    monkeypatch.delenv("ADMIN_ID", raising=False)
    monkeypatch.delenv("OWNER_ID", raising=False)

