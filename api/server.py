"""Console entrypoint for the Mini App API."""

from api.app import build_app
from aiohttp import web
import os


if __name__ == "__main__":
    web.run_app(
        build_app(),
        host=os.getenv("MINIAPP_API_HOST", "127.0.0.1"),
        port=int(os.getenv("MINIAPP_API_PORT", "8081")),
    )
