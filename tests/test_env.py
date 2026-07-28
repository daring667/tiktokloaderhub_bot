"""Tests for services/utils/env.py (ADMIN_ID/OWNER_ID resolution, used by main.py)."""
from services.utils.env import resolve_admin_id


def test_admin_id_used_when_set(monkeypatch):
    monkeypatch.setenv("ADMIN_ID", "555")
    monkeypatch.setenv("OWNER_ID", "999")
    assert resolve_admin_id() == 555


def test_falls_back_to_owner_id_when_admin_id_unset(monkeypatch):
    monkeypatch.delenv("ADMIN_ID", raising=False)
    monkeypatch.setenv("OWNER_ID", "999")
    assert resolve_admin_id() == 999


def test_falls_back_to_owner_id_when_admin_id_is_empty_string(monkeypatch):
    monkeypatch.setenv("ADMIN_ID", "")
    monkeypatch.setenv("OWNER_ID", "999")
    assert resolve_admin_id() == 999


def test_defaults_to_zero_when_neither_set(monkeypatch):
    monkeypatch.delenv("ADMIN_ID", raising=False)
    monkeypatch.delenv("OWNER_ID", raising=False)
    assert resolve_admin_id() == 0
