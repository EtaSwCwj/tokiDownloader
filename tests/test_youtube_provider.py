from __future__ import annotations

import unittest

from toki_core import default_config, normalize_config
from youtube_provider import (
    YouTubePolicyError,
    inspect_youtube_url,
    plan_youtube_format,
    preview_youtube_filename,
    youtube_format_policy_snapshot,
)


class YouTubeProviderTests(unittest.TestCase):
    def test_default_policy_is_best_quality_and_offline(self) -> None:
        config = default_config()
        self.assertEqual(config["configVersion"], 24)
        policy = youtube_format_policy_snapshot(config)
        self.assertEqual(policy["mode"], "video_audio")
        self.assertEqual(policy["maxHeight"], 0)
        self.assertEqual(policy["container"], "auto")
        self.assertFalse(policy["networkRequested"])
        self.assertFalse(policy["downloadExecuted"])

    def test_filename_template_is_windows_safe_and_rejects_arbitrary_expressions(self) -> None:
        preview = preview_youtube_filename(
            "%(upload_date)s - %(title)s [%(id)s].%(ext)s",
            {"title": "제목: 테스트", "upload_date": "20260807"},
        )
        self.assertEqual(preview["preview"], "20260807 - 제목_ 테스트 [dQw4w9WgXcQ].mp4")
        self.assertFalse(preview["networkRequested"])
        with self.assertRaisesRegex(ValueError, "지원하지 않는"):
            preview_youtube_filename("%(title)s/%(filepath)s.%(ext)s")
        with self.assertRaisesRegex(ValueError, "필요"):
            preview_youtube_filename("고정 이름.mp4")

    def test_plan_builds_bounded_resolution_and_codec_preferences(self) -> None:
        config = {
            **default_config(),
            "youtubeMaxHeight": 1080,
            "youtubeContainer": "mp4",
            "youtubeVideoCodec": "h264",
            "youtubeAudioCodec": "aac",
        }
        plan = plan_youtube_format(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ", config
        )
        self.assertEqual(
            plan["formatSelector"], "bv*[height<=?1080]+ba/b[height<=?1080]"
        )
        self.assertEqual(
            plan["formatSort"], ["res:1080", "vcodec:h264", "acodec:aac"]
        )
        self.assertIn("--remux-video", plan["arguments"])
        self.assertTrue(plan["requiresFfmpeg"])
        self.assertFalse(plan["networkRequested"])
        self.assertFalse(plan["downloadExecuted"])

    def test_audio_video_modes_and_playlist_reference_stay_explicit(self) -> None:
        audio = plan_youtube_format(
            "https://youtu.be/dQw4w9WgXcQ",
            {**default_config(), "youtubeFormatMode": "audio_only", "youtubeAudioCodec": "opus"},
        )
        self.assertEqual(audio["formatSelector"], "ba")
        self.assertEqual(audio["formatSort"], ["acodec:opus"])
        self.assertFalse(audio["requiresFfmpeg"])
        playlist = plan_youtube_format(
            "https://www.youtube.com/playlist?list=PL1234567890",
            default_config(),
        )
        self.assertEqual(playlist["reference"]["referenceType"], "playlist")
        self.assertEqual(playlist["arguments"][0], "--yes-playlist")

    def test_invalid_urls_and_config_values_are_rejected_or_migrated(self) -> None:
        with self.assertRaises(YouTubePolicyError) as caught:
            inspect_youtube_url("https://example.com/watch?v=abc")
        self.assertEqual(caught.exception.code, "youtube.unsupported_url")
        normalized = normalize_config(
            {
                "youtubeFormatMode": "invalid",
                "youtubeMaxHeight": 999,
                "youtubeContainer": "avi",
                "youtubeVideoCodec": "mpeg2",
                "youtubeAudioCodec": "wav",
            }
        )
        defaults = default_config()
        for key in (
            "youtubeFormatMode",
            "youtubeMaxHeight",
            "youtubeContainer",
            "youtubeVideoCodec",
            "youtubeAudioCodec",
            "youtubeFilenameTemplate",
        ):
            self.assertEqual(normalized[key], defaults[key])
