"""
Pure downloading functions for healthcheck and testing.
No Pyrogram dependencies.
"""
import os
import re
import time
import asyncio
import aiohttp
from pathlib import Path

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://tikwm.com/",
}


def is_tiktok_url(url: str) -> bool:
    """Check if URL is TikTok."""
    return 'tiktok.com' in url.lower()


def is_youtube_url(url: str) -> bool:
    """Check if URL is YouTube."""
    return any(x in url.lower() for x in ['youtube.com', 'youtu.be', 'youtube.com/shorts'])


def is_instagram_url(url: str) -> bool:
    """Check if URL is Instagram."""
    if not url:
        return False
    lower = url.lower()
    return any(x in lower for x in ['instagram.com/reel/', 'instagram.com/p/', 'instagram.com/tv/', 'instagr.am/'])


def extract_urls(text: str) -> list[str]:
    """Extract all URLs from a text message, in order of appearance."""
    if not text:
        return []
    return re.findall(r'https?://\S+', text)


def extract_url(text: str) -> str | None:
    """Extract the first URL from a text message."""
    urls = extract_urls(text)
    return urls[0] if urls else None


async def download_tiktok_video(url: str, output_path: str, timeout: tuple = (5, 120)) -> str:
    """
    Download TikTok video using TikTokDownloader asynchronously.
    """
    from services.tiktok.tiktok_downloader import TikTokDownloader
    downloader = TikTokDownloader(url)
    return await downloader.download(output_path)


async def download_youtube_video(url: str, output_path: str, timeout: int = 180) -> str:
    """
    Download YouTube video using YouTubeDownloader asynchronously.
    """
    from services.youtube.youtube_downloader import YouTubeDownloader
    downloader = YouTubeDownloader(url)
    formats = downloader.get_available_formats()
    if not formats:
        raise ValueError("No formats found")
    
    # Try to find a video format first, otherwise fall back to first format
    video_stream = next((f for f in formats if f.get('type') == 'video'), None)
    if not video_stream:
        video_stream = formats[0]
    
    itag = video_stream['itag']
    return await downloader.download(itag, output_path)


async def download_instagram_video(url: str, output_path: str, timeout: int = 180) -> str:
    """
    Download Instagram video using InstagramDownloader asynchronously.
    """
    from services.instagram.instagram_downloader import InstagramDownloader
    downloader = InstagramDownloader(url)
    return await downloader.download(output_path)


async def download_video(url: str, output_path: str, timeout: int = 180) -> str:
    """
    Auto-detect and download video from TikTok, YouTube, or Instagram asynchronously.
    """
    if not url:
        raise ValueError("Empty URL provided")
    
    if is_tiktok_url(url):
        return await download_tiktok_video(url, output_path, timeout=(5, timeout))
    elif is_youtube_url(url):
        return await download_youtube_video(url, output_path, timeout=timeout)
    elif is_instagram_url(url):
        return await download_instagram_video(url, output_path, timeout=timeout)
    else:
        raise ValueError(f"Unsupported URL: {url}")
