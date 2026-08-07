from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from toki_core import default_config
from youtube_provider import plan_youtube_execution
from youtube_worker import (
    classify_youtube_failure,
    main,
    parse_youtube_output_line,
    run_youtube_execution,
    resolve_ytdlp_command,
    simulate_youtube_execution,
)


class YouTubeWorkerTests(unittest.TestCase):
    def test_progress_item_and_completion_lines_become_normalized_events(self) -> None:
        progress = parse_youtube_output_line(
            "@@TOKI_YTDLP_PROGRESS@@abc\t2\t4\tdownloading\t 50.0%\t8 MiB/s\t00:10"
        )
        self.assertEqual(progress["event"], "youtube_progress")
        self.assertEqual(progress["itemProgress"], 50)
        self.assertEqual(progress["progress"], 37)
        self.assertEqual(progress["itemIndex"], 2)
        item = parse_youtube_output_line(
            "@@TOKI_YTDLP_ITEM@@abc\t2\t4\t제목\t탭 포함"
        )
        self.assertEqual(item["title"], "제목\t탭 포함")
        json_item = parse_youtube_output_line(
            "@@TOKI_YTDLP_ITEM@@"
            + json.dumps(
                {
                    "videoId": "abc",
                    "itemIndex": 2,
                    "itemTotal": 4,
                    "videoTitle": "영상\t제목",
                    "collectionTitle": "재생목록 제목",
                    "channel": "채널",
                },
                ensure_ascii=False,
            )
        )
        self.assertEqual(json_item["title"], "재생목록 제목")
        self.assertEqual(json_item["videoTitle"], "영상\t제목")
        completed = parse_youtube_output_line(
            "@@TOKI_YTDLP_COMPLETE@@abc\t2\t4\t20260807\tC:\\Video\\clip.mp4"
        )
        self.assertEqual(completed["uploadDate"], "20260807")
        self.assertEqual(completed["outputPath"], "C:\\Video\\clip.mp4")
        self.assertIsNone(parse_youtube_output_line("ordinary yt-dlp line"))

    def test_failure_classification_distinguishes_terminal_and_retryable_cases(self) -> None:
        self.assertEqual(
            classify_youtube_failure("Sign in to confirm you're not a bot"),
            {"category": "authentication_required", "retryable": False},
        )
        self.assertEqual(
            classify_youtube_failure("ERROR: Private video"),
            {"category": "source", "retryable": False},
        )
        self.assertEqual(
            classify_youtube_failure("HTTP Error 429: Too Many Requests"),
            {"category": "network", "retryable": True},
        )

    def test_simulation_emits_complete_progress_without_external_process(self) -> None:
        output = StringIO()
        code = simulate_youtube_execution(
            "https://www.youtube.com/playlist?list=PL1234567890",
            r"C:\Video",
            stream=output,
        )
        events = [
            json.loads(line.removeprefix("@@TOKI@@"))
            for line in output.getvalue().splitlines()
        ]
        self.assertEqual(code, 0)
        self.assertEqual(events[0]["event"], "youtube_started")
        self.assertTrue(events[0]["simulated"])
        self.assertEqual(sum(event["event"] == "youtube_item" for event in events), 3)
        self.assertEqual(events[-1]["event"], "completed")
        self.assertEqual(events[-1]["progress"], 100)

    def test_live_runner_normalizes_fake_ytdlp_process_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fake = Path(temp_dir) / "fake_ytdlp.py"
            fake.write_text(
                "print('@@TOKI_YTDLP_ITEM@@abc\\t1\\t1\\t로컬 가짜 영상')\n"
                "print('@@TOKI_YTDLP_PROGRESS@@abc\\t1\\t1\\tdownloading\\t 42.0%\\t1 MiB/s\\t00:01')\n"
                "print('@@TOKI_YTDLP_COMPLETE@@abc\\t1\\t1\\t20260807\\tN/A')\n",
                encoding="utf-8",
            )
            output = StringIO()
            errors = StringIO()
            with patch(
                "youtube_worker.resolve_ytdlp_command",
                return_value=[sys.executable, str(fake)],
            ):
                code = run_youtube_execution(
                    "https://www.youtube.com/watch?v=abc",
                    temp_dir,
                    default_config(),
                    stream=output,
                    error_stream=errors,
                )
        events = [
            json.loads(line.removeprefix("@@TOKI@@"))
            for line in output.getvalue().splitlines()
        ]
        self.assertEqual(code, 0)
        self.assertEqual(errors.getvalue(), "")
        self.assertEqual(
            [event["event"] for event in events],
            [
                "youtube_started",
                "youtube_item",
                "youtube_progress",
                "youtube_item_completed",
                "completed",
            ],
        )
        self.assertEqual(events[-1]["processedItems"], 1)

    def test_worker_main_reports_missing_dependency_as_terminal_event(self) -> None:
        output = StringIO()
        with (
            patch("youtube_worker.resolve_ytdlp_command", side_effect=RuntimeError("yt-dlp가 설치되어 있지 않습니다.")),
            patch("sys.stdout", output),
        ):
            code = main(
                [
                    "--url",
                    "https://www.youtube.com/watch?v=abc",
                    "--output",
                    r"C:\Video",
                ]
            )
        event = json.loads(output.getvalue().strip().removeprefix("@@TOKI@@"))
        self.assertEqual(code, 2)
        self.assertEqual(event["event"], "error")
        self.assertEqual(event["category"], "dependency")
        self.assertFalse(event["retryable"])

    def test_installed_ytdlp_accepts_runtime_templates_with_offline_info_json(self) -> None:
        try:
            command = resolve_ytdlp_command()
        except RuntimeError:
            self.skipTest("선택 의존성 yt-dlp가 설치되어 있지 않습니다.")
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir) / "offline.info.json"
            fixture.write_text(
                json.dumps(
                    {
                        "id": "offline123",
                        "title": "오프라인 실행 계약",
                        "webpage_url": "https://www.youtube.com/watch?v=offline123",
                        "extractor": "youtube",
                        "extractor_key": "Youtube",
                        "formats": [
                            {
                                "format_id": "video",
                                "url": "https://invalid.local/video",
                                "ext": "mp4",
                                "vcodec": "avc1",
                                "acodec": "none",
                                "height": 720,
                            },
                            {
                                "format_id": "audio",
                                "url": "https://invalid.local/audio",
                                "ext": "m4a",
                                "vcodec": "none",
                                "acodec": "mp4a",
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            plan = plan_youtube_execution(
                "https://www.youtube.com/watch?v=offline123",
                temp_dir,
                default_config(),
            )
            arguments = list(plan["arguments"][:-1])
            for index, value in enumerate(arguments[:-1]):
                if value == "--print" and arguments[index + 1].startswith("before_dl:"):
                    arguments[index + 1] = arguments[index + 1].removeprefix("before_dl:")
                    break
            arguments.extend(("--simulate", "--load-info-json", str(fixture)))
            completed = subprocess.run(
                [*command, *arguments],
                cwd=temp_dir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
                check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        self.assertNotIn("invalid.local", completed.stderr)
        item_line = next(
            line
            for line in completed.stdout.splitlines()
            if line.startswith("@@TOKI_YTDLP_ITEM@@")
        )
        self.assertEqual(
            parse_youtube_output_line(item_line)["videoTitle"],
            "오프라인 실행 계약",
            item_line,
        )


if __name__ == "__main__":
    unittest.main()
