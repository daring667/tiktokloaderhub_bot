import hashlib
import hmac
import json
import asyncio
import time
from urllib.parse import urlencode

import pytest
from aiohttp.test_utils import TestClient, TestServer

from api.auth import TelegramAuthError, user_id_from_init_data, validate_init_data
from api.jobs import JobManager


BOT_TOKEN = "test-bot-token"


def make_init_data(user_id=123, auth_date=None, token=BOT_TOKEN):
    fields = {
        "auth_date": str(auth_date or int(time.time())),
        "user": json.dumps({"id": user_id, "first_name": "Test"}, separators=(",", ":")),
        "query_id": "AAH-test",
    }
    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def test_validate_init_data_accepts_signed_payload():
    fields = validate_init_data(make_init_data(), BOT_TOKEN)
    assert user_id_from_init_data(fields) == 123


def test_validate_init_data_rejects_tampering():
    init_data = make_init_data()
    fields = dict(item.split("=", 1) for item in init_data.split("&") if "=" in item)
    fields["hash"] = "0" * 64
    with pytest.raises(TelegramAuthError, match="invalid"):
        validate_init_data(urlencode(fields), BOT_TOKEN)


def test_validate_init_data_rejects_expired_payload():
    with pytest.raises(TelegramAuthError, match="expired"):
        validate_init_data(make_init_data(auth_date=int(time.time()) - 100), BOT_TOKEN, max_age=30)

@pytest.mark.asyncio
async def test_job_manager_enforces_single_job_and_ownership(tmp_path, monkeypatch):
    async def fake_download(_url, output_path, timeout=180):
        with open(output_path, "wb") as output:
            output.write(b"video")
        return output_path

    monkeypatch.setattr("api.jobs.download_video", fake_download)
    manager = JobManager(tmp_path)
    job = manager.create(123, "https://www.tiktok.com/@user/video/1")

    assert manager.get_owned(job.job_id, 999) is None
    with pytest.raises(ValueError, match="активная"):
        manager.create(123, "https://www.youtube.com/watch?v=1")

    await job.task
    assert job.status == "completed"
    assert manager.get_owned(job.job_id, 123).public()["status"] == "completed"

@pytest.mark.asyncio
async def test_job_manager_cancel_removes_result(tmp_path, monkeypatch):
    async def slow_download(_url, output_path, timeout=180):
        await __import__("asyncio").sleep(10)
        return output_path

    monkeypatch.setattr("api.jobs.download_video", slow_download)
    manager = JobManager(tmp_path)
    job = manager.create(123, "https://www.tiktok.com/@user/video/1")
    assert await manager.cancel(job) is True
    with pytest.raises(asyncio.CancelledError):
        await job.task
    assert job.status == "cancelled"


@pytest.mark.asyncio
async def test_job_manager_sends_completed_video_to_owner(tmp_path, monkeypatch):
    async def fake_download(_url, output_path, timeout=180):
        with open(output_path, "wb") as output:
            output.write(b"video")
        return output_path

    sent = {}

    def fake_send(token, chat_id, file_path):
        sent.update(token=token, chat_id=chat_id, file_path=file_path)

    monkeypatch.setattr("api.jobs.download_video", fake_download)
    monkeypatch.setattr("api.jobs.send_video_to_telegram", fake_send)
    manager = JobManager(tmp_path, bot_token="bot-token")
    job = manager.create(456, "https://www.tiktok.com/@user/video/1")

    await job.task
    assert job.status == "completed"
    assert job.delivery_status == "sent"
    assert sent["token"] == "bot-token"
    assert sent["chat_id"] == 456

@pytest.mark.asyncio
async def test_api_requires_telegram_auth(tmp_path, monkeypatch):
    import api.app as app_module
    from api.app import build_app

    monkeypatch.setattr(app_module, "BOT_TOKEN", BOT_TOKEN)
    client = TestClient(TestServer(build_app(JobManager(tmp_path))))
    await client.start_server()
    try:
        response = await client.post("/api/jobs", json={"url": "https://www.tiktok.com/@user/video/1"})
        assert response.status == 401
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_api_health_and_cors_preflight(tmp_path, monkeypatch):
    import api.app as app_module
    from api.app import build_app

    monkeypatch.setattr(app_module, "BOT_TOKEN", BOT_TOKEN)
    monkeypatch.setenv("MINIAPP_ALLOWED_ORIGIN", "https://example.com")
    client = TestClient(TestServer(build_app(JobManager(tmp_path))))
    await client.start_server()
    try:
        response = await client.options("/api/jobs", headers={"Origin": "https://example.com"})
        assert response.status == 204
        assert response.headers["Access-Control-Allow-Origin"] == "https://example.com"
        response = await client.get("/api/health")
        assert (await response.json())["ok"] is True
    finally:
        await client.close()

@pytest.mark.asyncio
async def test_api_rejects_foreign_job(tmp_path, monkeypatch):
    import api.app as app_module
    from api.app import build_app

    monkeypatch.setattr(app_module, "BOT_TOKEN", BOT_TOKEN)
    async def fake_download(_url, output_path, timeout=180):
        with open(output_path, "wb") as output:
            output.write(b"video")
        return output_path

    monkeypatch.setattr("api.jobs.download_video", fake_download)
    manager = JobManager(tmp_path)
    client = TestClient(TestServer(build_app(manager)))
    await client.start_server()
    try:
        headers = {"X-Telegram-Init-Data": make_init_data(123)}
        response = await client.post(
            "/api/jobs", headers=headers,
            json={"url": "https://www.tiktok.com/@user/video/1"},
        )
        assert response.status == 202
        job = await response.json()
        foreign_headers = {"X-Telegram-Init-Data": make_init_data(999)}
        response = await client.get(f"/api/jobs/{job['id']}", headers=foreign_headers)
        assert response.status == 404
    finally:
        await client.close()
