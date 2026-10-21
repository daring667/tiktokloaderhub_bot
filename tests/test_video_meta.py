"""Tests for the video dimensions passed to Telegram.

`send_video` without width/height records the video as 0x0, and clients then
guess the aspect ratio -- which squashes a vertical video into a landscape box.
"""
import json
import subprocess
from unittest.mock import patch

from services.utils.video_meta import probe_video_metadata


def _ffprobe(streams, duration="54.000000"):
    payload = {"streams": streams, "format": {"duration": duration}}
    return subprocess.CompletedProcess(
        args=[], returncode=0, stdout=json.dumps(payload), stderr="")


class TestProbeVideoMetadata:

    def test_reads_vertical_dimensions(self):
        with patch("subprocess.run", return_value=_ffprobe(
                [{"width": 1080, "height": 1920}])):
            assert probe_video_metadata("v.mp4") == {
                "width": 1080, "height": 1920, "duration": 54}

    def test_reads_horizontal_dimensions(self):
        with patch("subprocess.run", return_value=_ffprobe(
                [{"width": 1920, "height": 1080}])):
            meta = probe_video_metadata("v.mp4")
            assert (meta["width"], meta["height"]) == (1920, 1080)

    def test_rotation_swaps_the_sides(self):
        """A phone recording is stored landscape with a rotation matrix."""
        with patch("subprocess.run", return_value=_ffprobe(
                [{"width": 1920, "height": 1080,
                  "side_data_list": [{"rotation": -90}]}])):
            meta = probe_video_metadata("v.mp4")
            assert (meta["width"], meta["height"]) == (1080, 1920)

    def test_half_turn_keeps_the_sides(self):
        with patch("subprocess.run", return_value=_ffprobe(
                [{"width": 1920, "height": 1080,
                  "side_data_list": [{"rotation": 180}]}])):
            meta = probe_video_metadata("v.mp4")
            assert (meta["width"], meta["height"]) == (1920, 1080)

    def test_unreadable_rotation_is_ignored(self):
        with patch("subprocess.run", return_value=_ffprobe(
                [{"width": 1920, "height": 1080,
                  "side_data_list": [{"rotation": "sideways"}]}])):
            meta = probe_video_metadata("v.mp4")
            assert (meta["width"], meta["height"]) == (1920, 1080)

    def test_a_failure_costs_the_hint_not_the_upload(self):
        """The result is splatted into send_video, so it must stay empty."""
        with patch("subprocess.run", side_effect=FileNotFoundError("no ffprobe")):
            assert probe_video_metadata("v.mp4") == {}

    def test_nonzero_exit_returns_empty(self):
        with patch("subprocess.run", side_effect=subprocess.CalledProcessError(
                1, "ffprobe")):
            assert probe_video_metadata("missing.mp4") == {}

    def test_no_video_stream_returns_empty(self):
        with patch("subprocess.run", return_value=_ffprobe([])):
            assert probe_video_metadata("audio.m4a") == {}

    def test_missing_dimensions_are_left_out(self):
        with patch("subprocess.run", return_value=_ffprobe([{}])):
            assert probe_video_metadata("v.mp4") == {"duration": 54}

    def test_unusable_duration_is_left_out(self):
        with patch("subprocess.run", return_value=_ffprobe(
                [{"width": 640, "height": 360}], duration="N/A")):
            assert probe_video_metadata("v.mp4") == {"width": 640, "height": 360}

    def test_zero_duration_is_left_out(self):
        with patch("subprocess.run", return_value=_ffprobe(
                [{"width": 640, "height": 360}], duration="0")):
            assert "duration" not in probe_video_metadata("v.mp4")
