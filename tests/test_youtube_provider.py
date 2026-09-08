from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from toki_core import CONFIG_SCHEMA_VERSION, default_config, normalize_config
from youtube_provider import (
    YouTubePolicyError,
    apply_youtube_upload_date_mtime,
    inspect_youtube_url,
    plan_youtube_execution,
    plan_youtube_format,
    plan_youtube_upload_date_mtime,
    preview_youtube_filename,
    youtube_format_policy_snapshot,
    youtube_execution_config_snapshot,
)


class YouTubeProviderTests(unittest.TestCase):
    def test_default_policy_is_best_quality_and_offline(self) -> None:
        config = default_config()
        self.assertEqual(config["configVersion"], CONFIG_SCHEMA_VERSION)
        policy = youtube_format_policy_snapshot(config)
        self.assertEqual(policy["mode"], "video_audio")
        self.assertEqual(policy["maxHeight"], 0)
        self.assertEqual(policy["container"], "auto")
        self.assertFalse(policy["networkRequested"])
        self.assertFalse(policy["downloadExecuted"])
        self.assertFalse(policy["writeThumbnail"])
        self.assertFalse(policy["embedThumbnail"])
        self.assertFalse(policy["writeInfoJson"])
        self.assertFalse(policy["writeDescription"])
        self.assertFalse(policy["embedMetadata"])
        self.assertFalse(policy["embedChapters"])
        self.assertFalse(policy["applyUploadDateMtime"])

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
            plan["formatSort"], ["lang:ko", "res:1080", "vcodec:h264", "acodec:aac"]
        )
        self.assertIn("--remux-video", plan["arguments"])
        self.assertTrue(plan["requiresFfmpeg"])
        self.assertFalse(plan["networkRequested"])
        self.assertFalse(plan["downloadExecuted"])

    def test_execution_plan_adds_machine_progress_and_bounded_output_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plan = plan_youtube_execution(
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                temp_dir,
                {**default_config(), "proxyUrl": "https://secret.invalid"},
            )
        arguments = plan["arguments"]
        self.assertEqual(arguments[0], "--ignore-config")
        self.assertIn("--progress-template", arguments)
        self.assertTrue(any("@@TOKI_YTDLP_PROGRESS@@" in value for value in arguments))
        self.assertIn("--no-mtime", arguments)
        self.assertIn("--no-overwrites", arguments)
        self.assertEqual(arguments[-1], "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertFalse(plan["networkRequested"])
        self.assertFalse(plan["downloadExecuted"])
        worker_config = youtube_execution_config_snapshot(
            {**default_config(), "proxyUrl": "https://secret.invalid"}
        )
        self.assertNotIn("proxyUrl", worker_config)
        self.assertEqual(worker_config["youtubeFormatMode"], "video_audio")

    def test_audio_video_modes_and_playlist_reference_stay_explicit(self) -> None:
        audio = plan_youtube_format(
            "https://youtu.be/dQw4w9WgXcQ",
            {**default_config(), "youtubeFormatMode": "audio_only", "youtubeAudioCodec": "opus"},
        )
        self.assertEqual(audio["formatSelector"], "ba")
        self.assertEqual(audio["formatSort"], ["lang:ko", "acodec:opus"])
        self.assertFalse(audio["requiresFfmpeg"])
        playlist = plan_youtube_format(
            "https://www.youtube.com/playlist?list=PL1234567890",
            default_config(),
        )
        self.assertEqual(playlist["reference"]["referenceType"], "playlist")
        self.assertEqual(playlist["arguments"][0], "--yes-playlist")

    def test_language_subtitle_and_multiaudio_plan_uses_official_bounded_options(self) -> None:
        plan = plan_youtube_format(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            {
                **default_config(),
                "youtubePreferredLanguages": ["ko", "en", "ja"],
                "youtubeSubtitleMode": "manual_auto",
                "youtubeSubtitleFormat": "srt",
                "youtubeEmbedSubtitles": True,
                "youtubeAudioTrackMode": "all",
            },
        )
        self.assertEqual(plan["formatSelector"], "bv*+mergeall[vcodec=none]")
        self.assertIn("--audio-multistreams", plan["arguments"])
        self.assertIn("--write-auto-subs", plan["arguments"])
        self.assertIn("--embed-subs", plan["arguments"])
        self.assertIn("ko,en,ja", plan["arguments"])
        self.assertTrue(plan["requiresFfmpeg"])
        self.assertFalse(plan["networkRequested"])

    def test_thumbnail_and_metadata_plan_is_explicit_private_and_chapter_independent(self) -> None:
        plan = plan_youtube_format(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            {
                **default_config(),
                "youtubeWriteThumbnail": True,
                "youtubeEmbedThumbnail": True,
                "youtubeWriteInfoJson": True,
                "youtubeWriteDescription": True,
                "youtubeEmbedMetadata": True,
            },
        )
        for option in (
            "--write-thumbnail",
            "--embed-thumbnail",
            "--write-info-json",
            "--clean-info-json",
            "--no-write-comments",
            "--write-description",
            "--no-write-playlist-metafiles",
            "--embed-metadata",
            "--no-embed-chapters",
            "--no-embed-info-json",
        ):
            self.assertIn(option, plan["arguments"])
        self.assertTrue(plan["infoJsonMayContainPersonalInformation"])
        self.assertFalse(plan["requestComments"])
        self.assertTrue(plan["commentsMayBePresent"])
        self.assertTrue(plan["postProcessingRequired"])
        self.assertTrue(plan["requiresFfmpeg"])
        self.assertFalse(plan["networkRequested"])
        self.assertFalse(plan["downloadExecuted"])

    def test_channel_and_playlist_order_preserves_explicit_scope(self) -> None:
        channel = inspect_youtube_url("https://www.youtube.com/@OpenAI/videos")
        self.assertEqual(channel["referenceType"], "channel")
        self.assertEqual(channel["channelScope"], "videos")
        self.assertTrue(channel["collection"])
        reverse = plan_youtube_format(
            "https://www.youtube.com/@OpenAI/videos",
            {**default_config(), "youtubeCollectionOrder": "reverse"},
        )
        self.assertEqual(reverse["arguments"][0], "--yes-playlist")
        self.assertIn("--no-lazy-playlist", reverse["arguments"])
        self.assertIn("--playlist-items", reverse["arguments"])
        self.assertIn("::-1", reverse["arguments"])
        self.assertTrue(reverse["fullCollectionScanRequired"])
        site_order = plan_youtube_format(
            "https://www.youtube.com/playlist?list=PL1234567890", default_config()
        )
        self.assertIn("--playlist-items", site_order["arguments"])
        self.assertIn("::", site_order["arguments"])
        single_video = plan_youtube_format(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL1234567890",
            {**default_config(), "youtubeCollectionOrder": "reverse"},
        )
        self.assertEqual(single_video["arguments"][0], "--no-playlist")
        self.assertFalse(single_video["collectionOrderApplied"])
        self.assertNotIn("--playlist-items", single_video["arguments"])
        with self.assertRaises(YouTubePolicyError):
            inspect_youtube_url("https://www.youtube.com/@OpenAI/unknown-tab")

    def test_chapter_markers_are_independent_from_metadata_embedding(self) -> None:
        chapters = plan_youtube_format(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            {**default_config(), "youtubeEmbedChapters": True},
        )
        self.assertIn("--embed-chapters", chapters["arguments"])
        self.assertNotIn("--embed-metadata", chapters["arguments"])
        self.assertTrue(chapters["postProcessingRequired"])
        self.assertTrue(chapters["requiresFfmpeg"])
        combined = plan_youtube_format(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            {
                **default_config(),
                "youtubeEmbedMetadata": True,
                "youtubeEmbedChapters": True,
            },
        )
        self.assertIn("--embed-metadata", combined["arguments"])
        self.assertIn("--embed-chapters", combined["arguments"])
        self.assertNotIn("--no-embed-chapters", combined["arguments"])

    def test_upload_date_mtime_plan_and_confirmed_temp_file_apply_are_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "영상.mp4"
            target.write_bytes(b"test")
            plan = plan_youtube_upload_date_mtime(
                target, "20260807", config=default_config(), enabled=True
            )
            self.assertEqual(plan["targetUtc"], "2026-08-07T00:00:00+00:00")
            self.assertTrue(plan["requiresConfirmation"])
            self.assertFalse(plan["executed"])
            with self.assertRaisesRegex(ValueError, "--yes"):
                apply_youtube_upload_date_mtime(
                    target, "20260807", config=default_config(), enabled=True
                )
            applied = apply_youtube_upload_date_mtime(
                target,
                "20260807",
                config=default_config(),
                enabled=True,
                confirmed=True,
            )
            self.assertTrue(applied["executed"])
            self.assertEqual(target.stat().st_mtime_ns, applied["afterMtimeNs"])
            self.assertEqual(applied["afterMtimeNs"], plan["targetTimestampNs"])
            self.assertTrue(applied["accessTimePreserved"])
        with self.assertRaisesRegex(ValueError, "유효하지 않은"):
            plan_youtube_upload_date_mtime("video.mp4", "20260230", enabled=True)
        format_plan = plan_youtube_format(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            {**default_config(), "youtubeApplyUploadDateMtime": True},
        )
        self.assertEqual(
            format_plan["postDownloadActions"][0]["action"],
            "set_mtime_from_upload_date",
        )

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
                "youtubeWriteThumbnail": "yes",
                "youtubeEmbedThumbnail": 1,
                "youtubeWriteInfoJson": [],
                "youtubeWriteDescription": "false",
                "youtubeEmbedMetadata": "on",
                "youtubeCollectionOrder": "random",
                "youtubeEmbedChapters": "yes",
                "youtubeApplyUploadDateMtime": "yes",
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
            "youtubePreferredLanguages",
            "youtubeSubtitleMode",
            "youtubeSubtitleFormat",
            "youtubeEmbedSubtitles",
            "youtubeAudioTrackMode",
            "youtubeWriteThumbnail",
            "youtubeEmbedThumbnail",
            "youtubeWriteInfoJson",
            "youtubeWriteDescription",
            "youtubeEmbedMetadata",
            "youtubeCollectionOrder",
            "youtubeEmbedChapters",
            "youtubeApplyUploadDateMtime",
        ):
            self.assertEqual(normalized[key], defaults[key])
