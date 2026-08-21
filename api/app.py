"""aiohttp application for the Telegram downloader Mini App."""

import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse

from aiohttp import web
from dotenv import load_dotenv

from api.auth import TelegramAuthError, user_id_from_init_data, validate_init_data
from api.jobs import JobManager

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOWNLOADS_DIR = PROJECT_ROOT / "downloads" / "miniapp"
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID") or os.getenv("OWNER_ID") or "0")
URL_RE = re.compile(r"^https?://\S+$", re.IGNORECASE)
ALLOWED_HOSTS = {"tiktok.com", "youtube.com", "youtu.be", "youtube-nocookie.com"}
JOBS_KEY = web.AppKey("jobs", JobManager)
USER_ID_KEY = web.RequestKey("user_id", int)


def is_allowed_url(url: str) -> bool:
    if len(url) > 2048 or not URL_RE.match(url):
        return False
    hostname = (urlparse(url).hostname or "").lower().rstrip(".")
    return any(hostname == allowed or hostname.endswith(f".{allowed}") for allowed in ALLOWED_HOSTS)


def build_app(job_manager: JobManager | None = None) -> web.Application:
    manager = job_manager or JobManager(DOWNLOADS_DIR, bot_token=BOT_TOKEN)
    app = web.Application(client_max_size=1024 * 1024)
    app[JOBS_KEY] = manager

    @web.middleware
    async def cors_middleware(request, handler):
        origin = os.getenv("MINIAPP_ALLOWED_ORIGIN", "*")
        if request.method == "OPTIONS":
            response = web.Response(status=204)
        else:
            response = await handler(request)
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Telegram-Init-Data"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Vary"] = "Origin"
        return response

    @web.middleware
    async def auth_middleware(request, handler):
        if request.path == "/api/health":
            return await handler(request)
        try:
            fields = validate_init_data(
                request.headers.get("X-Telegram-Init-Data", ""), BOT_TOKEN
            )
            request[USER_ID_KEY] = user_id_from_init_data(fields)
        except TelegramAuthError as exc:
            raise web.HTTPUnauthorized(text=json.dumps({"error": str(exc)}), content_type="application/json")
        return await handler(request)

    app.middlewares.append(cors_middleware)
    app.middlewares.append(auth_middleware)

    async def health(_request):
        return web.json_response({"ok": True, "service": "tiktokloaderhub-api"})

    async def create_job(request):
        try:
            payload = await request.json()
        except (json.JSONDecodeError, ValueError):
            raise web.HTTPBadRequest(text=json.dumps({"error": "Некорректный JSON"}), content_type="application/json")
        url = str(payload.get("url", "")).strip()
        if not is_allowed_url(url):
            raise web.HTTPBadRequest(text=json.dumps({"error": "Нужна ссылка TikTok или YouTube"}), content_type="application/json")
        try:
            job = manager.create(request[USER_ID_KEY], url)
        except ValueError as exc:
            raise web.HTTPConflict(text=json.dumps({"error": str(exc)}), content_type="application/json")
        return web.json_response(job.public(), status=202)

    async def get_job(request):
        job = manager.get_owned(request.match_info["job_id"], request[USER_ID_KEY])
        if not job:
            raise web.HTTPNotFound(text=json.dumps({"error": "Задание не найдено"}), content_type="application/json")
        return web.json_response(job.public())

    async def cancel_job(request):
        job = manager.get_owned(request.match_info["job_id"], request[USER_ID_KEY])
        if not job:
            raise web.HTTPNotFound(text=json.dumps({"error": "Задание не найдено"}), content_type="application/json")
        await manager.cancel(job)
        return web.json_response(job.public())

    async def download_result(request):
        job = manager.get_owned(request.match_info["job_id"], request[USER_ID_KEY])
        if not job or job.status != "completed" or not job.result_path:
            raise web.HTTPNotFound(text=json.dumps({"error": "Файл ещё не готов"}), content_type="application/json")
        path = Path(job.result_path)
        if not path.is_file():
            raise web.HTTPNotFound(text=json.dumps({"error": "Файл больше недоступен"}), content_type="application/json")
        return web.FileResponse(path)

    async def admin_summary(request):
        if request[USER_ID_KEY] != ADMIN_ID:
            raise web.HTTPForbidden(text=json.dumps({"error": "Нет доступа"}), content_type="application/json")
        jobs = list(manager.jobs.values())
        return web.json_response({
            "service": "tiktokloaderhub-api",
            "jobs": len(jobs),
            "active": sum(job.status in {"queued", "running"} for job in jobs),
            "completed": sum(job.status == "completed" for job in jobs),
            "failed": sum(job.status == "failed" for job in jobs),
        })

    app.router.add_get("/api/health", health)
    app.router.add_post("/api/jobs", create_job)
    app.router.add_get("/api/jobs/{job_id}", get_job)
    app.router.add_post("/api/jobs/{job_id}/cancel", cancel_job)
    app.router.add_get("/api/jobs/{job_id}/file", download_result)
    app.router.add_get("/api/admin/summary", admin_summary)
    return app


if __name__ == "__main__":
    web.run_app(build_app(), host=os.getenv("MINIAPP_API_HOST", "127.0.0.1"), port=int(os.getenv("MINIAPP_API_PORT", "8081")))
