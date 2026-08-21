"""Asynchronous, bounded download jobs for the Mini App API."""

import asyncio
import os
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from services.downloader import download_video


MAX_RESULT_SIZE = 50 * 1024 * 1024
JOB_TTL_SECONDS = 30 * 60
DOWNLOAD_TIMEOUT_SECONDS = 180


@dataclass
class DownloadJob:
    job_id: str
    user_id: int
    url: str
    status: str = "queued"
    result_path: str | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    task: asyncio.Task | None = field(default=None, repr=False)

    def public(self) -> dict:
        result = {
            "id": self.job_id,
            "url": self.url,
            "status": self.status,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self.status == "completed":
            result["download_url"] = f"/api/jobs/{self.job_id}/file"
        return result


class JobManager:
    def __init__(self, downloads_dir: str | Path, max_concurrent: int = 2):
        self.downloads_dir = Path(downloads_dir)
        self.downloads_dir.mkdir(parents=True, exist_ok=True)
        self.jobs: dict[str, DownloadJob] = {}
        self.semaphore = asyncio.Semaphore(max_concurrent)

    def create(self, user_id: int, url: str) -> DownloadJob:
        active = sum(
            job.user_id == user_id and job.status in {"queued", "running"}
            for job in self.jobs.values()
        )
        if active >= 1:
            raise ValueError("У вас уже есть активная загрузка")
        job = DownloadJob(uuid.uuid4().hex, user_id, url.strip())
        self.jobs[job.job_id] = job
        job.task = asyncio.create_task(self._run(job))
        return job

    def get_owned(self, job_id: str, user_id: int) -> DownloadJob | None:
        job = self.jobs.get(job_id)
        return job if job and job.user_id == user_id else None

    async def cancel(self, job: DownloadJob) -> bool:
        if job.status in {"completed", "failed", "cancelled"}:
            return False
        job.status = "cancelled"
        job.updated_at = time.time()
        if job.task and not job.task.done():
            job.task.cancel()
        return True

    async def _run(self, job: DownloadJob) -> None:
        output_path = self.downloads_dir / f"{job.job_id}.mp4"
        try:
            async with self.semaphore:
                if job.status == "cancelled":
                    return
                job.status = "running"
                job.updated_at = time.time()
                result_path = await asyncio.wait_for(
                    download_video(job.url, str(output_path), DOWNLOAD_TIMEOUT_SECONDS),
                    timeout=DOWNLOAD_TIMEOUT_SECONDS,
                )
                if job.status == "cancelled":
                    return
                if not os.path.exists(result_path):
                    raise ValueError("Файл не создан")
                if os.path.getsize(result_path) > MAX_RESULT_SIZE:
                    raise ValueError("Файл больше 50 МБ")
                job.result_path = result_path
                job.status = "completed"
        except asyncio.CancelledError:
            if job.status != "cancelled":
                job.status = "failed"
                job.error = "Загрузка отменена"
            return
        except Exception as exc:
            job.status = "failed"
            job.error = str(exc)[:300] or "Ошибка загрузки"
            output_path.unlink(missing_ok=True)
        finally:
            job.updated_at = time.time()

    async def cleanup(self) -> int:
        now = time.time()
        removed = 0
        for job_id, job in list(self.jobs.items()):
            if now - job.updated_at < JOB_TTL_SECONDS:
                continue
            if job.task and not job.task.done():
                job.task.cancel()
            if job.result_path:
                Path(job.result_path).unlink(missing_ok=True)
            shutil.rmtree(self.downloads_dir / job_id, ignore_errors=True)
            del self.jobs[job_id]
            removed += 1
        return removed
