from __future__ import annotations

import json
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

from toki_app import build_parser, run_cli, run_direct_download


class CliParserTests(unittest.TestCase):
    def test_self_test_core_only_json_arguments(self) -> None:
        args = build_parser().parse_args(["self-test", "--core-only", "--json"])
        self.assertEqual(args.command, "self-test")
        self.assertTrue(args.core_only)
        self.assertTrue(args.json)
        self.assertFalse(args.via_gui)

    def test_self_test_via_gui_arguments(self) -> None:
        args = build_parser().parse_args(["self-test", "--via-gui", "--json"])
        self.assertTrue(args.via_gui)
        self.assertFalse(args.core_only)

    def test_download_show_browser_is_explicit(self) -> None:
        args = build_parser().parse_args(
            ["download", "--url", "https://newtoki1.org/manhwa/34360"]
        )
        self.assertFalse(args.show_browser)
        self.assertEqual(args.mode, "new")

    def test_rescan_modes_and_range_arguments(self) -> None:
        new = build_parser().parse_args(
            ["rescan", "--job", "work-1", "--mode", "new"]
        )
        self.assertEqual(new.mode, "new")
        ranged = build_parser().parse_args(
            [
                "rescan", "--job", "work-1", "--mode", "range",
                "--start", "12", "--last", "24",
            ]
        )
        self.assertEqual((ranged.start, ranged.last), (12, 24))

    def test_rescan_cli_sends_exact_job_mode_and_range(self) -> None:
        args = build_parser().parse_args(
            [
                "rescan", "--job", "work-1", "--mode", "range",
                "--start", "12", "--last", "24",
            ]
        )
        with (
            patch("toki_app.control_request", return_value={"job_id": "new-run"}) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(args), 0)
        request.assert_called_once_with(
            {
                "action": "rescan",
                "jobId": "work-1",
                "mode": "range",
                "start": 12,
                "last": 24,
            }
        )

    def test_stop_and_cancel_accept_job_ids(self) -> None:
        stop = build_parser().parse_args(["stop", "--job", "active-1"])
        self.assertEqual(stop.job, "active-1")
        cancel = build_parser().parse_args(["cancel", "--job", "queued-1"])
        self.assertEqual(cancel.job, "queued-1")
        pause = build_parser().parse_args(["pause", "--job", "active-1"])
        resume = build_parser().parse_args(["resume", "--job", "active-1"])
        self.assertEqual(pause.job, resume.job)

    def test_queue_list_and_move_arguments(self) -> None:
        queue_list = build_parser().parse_args(["queue", "list", "--json"])
        self.assertEqual(queue_list.queue_command, "list")
        self.assertTrue(queue_list.json)
        move = build_parser().parse_args(
            ["queue", "move", "--job", "queued-2", "--before", "queued-1"]
        )
        self.assertEqual(move.before, "queued-1")
        first = build_parser().parse_args(
            ["queue", "move", "--job", "queued-2", "--first"]
        )
        self.assertTrue(first.first)

    def test_work_and_image_concurrency_arguments(self) -> None:
        current = build_parser().parse_args(["concurrency", "--json"])
        self.assertTrue(current.json)
        update = build_parser().parse_args(
            ["set-concurrency", "--works", "3", "--images", "8"]
        )
        self.assertEqual(update.works, 3)
        self.assertEqual(update.images, 8)

    def test_set_concurrency_sends_both_values_to_running_gui(self) -> None:
        args = build_parser().parse_args(
            ["set-concurrency", "--works", "2", "--images", "7"]
        )
        with (
            patch("toki_app.gui_is_running", return_value=True),
            patch(
                "toki_app.control_request",
                return_value={"workConcurrency": 2, "imageConcurrency": 7},
            ) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(args), 0)
        request.assert_called_once_with(
            {"action": "set_concurrency", "works": 2, "images": 7}
        )

    def test_set_concurrency_requires_at_least_one_value(self) -> None:
        args = build_parser().parse_args(["set-concurrency"])
        with self.assertRaises(ValueError):
            run_cli(args)

    def test_settings_query_update_and_show_gui_are_cli_controlled(self) -> None:
        values = {
            "outputDir": r"C:\Manga",
            "workConcurrency": 2,
            "imageConcurrency": 8,
            "retryCount": 3,
            "retryBackoffSeconds": 4,
            "showBrowser": False,
            "logVisible": True,
            "logMaxMiB": 5,
            "logBackupCount": 2,
            "rowDensity": "comfortable",
        }
        query = build_parser().parse_args(["settings", "--json"])
        with (
            patch("toki_app.gui_is_running", return_value=False),
            patch("toki_app.settings_snapshot", return_value=values) as snapshot,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(query), 0)
        snapshot.assert_called_once_with()

        update = build_parser().parse_args(
            [
                "set-settings", "--works", "3", "--images", "10",
                "--show-browser", "on", "--log-visible", "off",
                "--log-max-mib", "8", "--log-backups", "4",
                "--row-density", "compact", "--json",
            ]
        )
        with (
            patch("toki_app.gui_is_running", return_value=True),
            patch("toki_app.control_request", return_value=values) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(update), 0)
        request.assert_called_once_with(
            {
                "action": "set_settings",
                "updates": {
                    "workConcurrency": 3,
                    "imageConcurrency": 10,
                    "logMaxMiB": 8,
                    "logBackupCount": 4,
                    "rowDensity": "compact",
                    "showBrowser": True,
                    "logVisible": False,
                },
                "reset": False,
            }
        )

        show = build_parser().parse_args(
            ["settings", "--show-gui", "--tab", "network"]
        )
        with (
            patch("toki_app.ensure_gui_running"),
            patch("toki_app.control_request", return_value={"shown": True}) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(show), 0)
        request.assert_called_once_with({"action": "show_settings", "tab": "network"})

    def test_retry_policy_arguments_and_gui_request(self) -> None:
        current = build_parser().parse_args(["retry-policy", "--json"])
        self.assertTrue(current.json)
        args = build_parser().parse_args(
            ["set-retry-policy", "--count", "3", "--backoff", "4"]
        )
        with (
            patch("toki_app.gui_is_running", return_value=True),
            patch(
                "toki_app.control_request",
                return_value={"retryCount": 3, "retryBackoffSeconds": 4},
            ) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(args), 0)
        request.assert_called_once_with(
            {
                "action": "set_retry_policy",
                "retryCount": 3,
                "backoffSeconds": 4,
            }
        )

    def test_direct_download_uses_same_retry_backoff_policy(self) -> None:
        args = build_parser().parse_args(
            [
                "download", "--direct", "--url",
                "https://newtoki1.org/manhwa/34360",
            ]
        )
        completed = [
            type("Completed", (), {"returncode": code})()
            for code in (1, 1, 0)
        ]
        with (
            patch(
                "toki_app.load_config",
                return_value={
                    "outputDir": r"C:\Manga",
                    "imageConcurrency": 5,
                    "retryCount": 2,
                    "retryBackoffSeconds": 2,
                },
            ),
            patch("toki_app.find_node", return_value="node"),
            patch("toki_app.build_downloader_args", return_value=["down.js"]),
            patch("toki_app.subprocess.run", side_effect=completed) as runner,
            patch("toki_app.time.sleep") as sleeper,
            patch("toki_app.append_log"),
        ):
            self.assertEqual(run_direct_download(args), 0)
        self.assertEqual(runner.call_count, 3)
        self.assertEqual([call.args[0] for call in sleeper.call_args_list], [2, 4])

    def test_list_query_arguments(self) -> None:
        args = build_parser().parse_args(
            [
                "list", "--query", "작가", "--status", "완료", "--sort", "title",
                "--apply-gui", "--json",
            ]
        )
        self.assertEqual(args.query, "작가")
        self.assertEqual(args.status, "완료")
        self.assertEqual(args.sort, "title")
        self.assertTrue(args.apply_gui)
        self.assertTrue(args.json)

    def test_pin_and_tag_arguments(self) -> None:
        pin = build_parser().parse_args(["pin", "--job", "abc", "--on"])
        self.assertTrue(pin.on)
        tag = build_parser().parse_args(["tag", "--job", "abc", "--color", "blue"])
        self.assertEqual(tag.color, "blue")

    def test_remove_record_requires_explicit_confirmation_flag(self) -> None:
        args = build_parser().parse_args(["remove-record", "--job", "abc", "--yes"])
        self.assertTrue(args.yes)

    def test_cleanup_and_refresh_arguments(self) -> None:
        cleanup = build_parser().parse_args(
            [
                "cleanup-records",
                "--status",
                "completed",
                "--status",
                "error",
                "--status",
                "authentication",
                "--yes",
            ]
        )
        self.assertEqual(cleanup.status, ["completed", "error", "authentication"])
        self.assertTrue(cleanup.yes)
        refresh = build_parser().parse_args(["refresh-list"])
        self.assertEqual(refresh.command, "refresh-list")

    def test_move_folder_defaults_to_dry_run_and_execute_requires_yes(self) -> None:
        dry_run = build_parser().parse_args(
            ["move-folder", "--job", "job-1", "--output", r"D:\Manga", "--json"]
        )
        with (
            patch("toki_app.gui_is_running", return_value=True),
            patch(
                "toki_app.control_request",
                return_value={
                    "source": r"C:\Manga\마나토끼\작품",
                    "destination": r"D:\Manga\마나토끼\작품",
                    "conflict": False,
                },
            ) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(dry_run), 0)
        request.assert_called_once_with(
            {
                "action": "move_folder",
                "jobId": "job-1",
                "output": r"D:\Manga",
                "execute": False,
            },
            timeout_ms=2500,
        )

        unsafe = build_parser().parse_args(
            ["move-folder", "--job", "job-1", "--output", r"D:\Manga", "--execute"]
        )
        with self.assertRaises(RuntimeError):
            run_cli(unsafe)

    def test_rebuild_metadata_defaults_to_dry_run_and_execute_requires_yes(self) -> None:
        dry_run = build_parser().parse_args(
            ["rebuild-metadata", "--job", "job-1", "--json"]
        )
        with (
            patch("toki_app.gui_is_running", return_value=True),
            patch(
                "toki_app.control_request",
                return_value={
                    "metadataPath": r"C:\Manga\작품\metadata.json",
                    "backupPath": r"C:\Manga\작품\metadata.json.bak",
                    "executed": False,
                },
            ) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(dry_run), 0)
        request.assert_called_once_with(
            {"action": "rebuild_metadata", "jobId": "job-1", "execute": False}
        )

        unsafe = build_parser().parse_args(
            ["rebuild-metadata", "--job", "job-1", "--execute"]
        )
        with self.assertRaises(RuntimeError):
            run_cli(unsafe)

    def test_verify_files_cli_uses_read_only_service_and_exit_code(self) -> None:
        args = build_parser().parse_args(
            ["verify-files", "--job", "job-1", "--issue-limit", "25", "--json"]
        )
        result = {
            "jobId": "job-1",
            "title": "작품",
            "outputPath": r"C:\Manga\작품",
            "healthy": False,
            "durationMs": 3,
            "summary": {
                "episodeFolders": 1,
                "images": 1,
                "issueCount": 1,
                "issuesTruncated": False,
            },
            "issues": [{"kind": "image_invalid", "path": "x", "detail": "손상"}],
        }
        with (
            patch("toki_app.verify_job_files", return_value=result) as verify,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(args), 2)
        verify.assert_called_once_with("job-1", 25)

        show_gui = build_parser().parse_args(
            ["verify-files", "--job", "job-1", "--show-gui"]
        )
        with (
            patch("toki_app.ensure_gui_running"),
            patch(
                "toki_app.control_request",
                return_value={"started": True, "jobId": "job-1"},
            ) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(show_gui), 0)
        request.assert_called_once_with({"action": "verify_files", "jobId": "job-1"})

    def test_preview_cli_contract_and_gui_request(self) -> None:
        args = build_parser().parse_args(
            [
                "preview", "--job", "job-1", "--episode", "12",
                "--limit", "20", "--offset", "40", "--json",
            ]
        )
        result = {
            "jobId": "job-1",
            "title": "작품",
            "episode": 12,
            "total": 0,
            "images": [],
        }
        with (
            patch("toki_app.list_job_episode_images", return_value=result) as preview,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(args), 0)
        preview.assert_called_once_with("job-1", 12, limit=20, offset=40)

        show_gui = build_parser().parse_args(
            ["preview", "--job", "job-1", "--episode", "12", "--show-gui"]
        )
        with (
            patch("toki_app.ensure_gui_running"),
            patch(
                "toki_app.control_request",
                return_value={"started": True, "jobId": "job-1"},
            ) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(show_gui), 0)
        request.assert_called_once_with(
            {"action": "preview_images", "jobId": "job-1", "episode": 12}
        )

    def test_convert_images_defaults_to_dry_run_and_requires_confirmation(self) -> None:
        args = build_parser().parse_args(
            ["convert-images", "--job", "job-1", "--format", "webp", "--json"]
        )
        result = {
            "jobId": "job-1",
            "targetRoot": r"C:\Manga\작품\_converted\webp",
            "sourceCount": 3,
            "existingTargetCount": 0,
            "pendingCount": 3,
            "executed": False,
        }
        with (
            patch("toki_app.plan_image_conversion", return_value=result) as plan,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(args), 0)
        plan.assert_called_once_with("job-1", "webp", quality=90)

        unsafe = build_parser().parse_args(
            [
                "convert-images", "--job", "job-1", "--format", "png",
                "--execute",
            ]
        )
        with self.assertRaises(RuntimeError):
            run_cli(unsafe)

        show_gui = build_parser().parse_args(
            [
                "convert-images", "--job", "job-1", "--format", "webp",
                "--quality", "80", "--show-gui",
            ]
        )
        with (
            patch("toki_app.ensure_gui_running"),
            patch(
                "toki_app.control_request",
                return_value={"planned": True, "jobId": "job-1"},
            ) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(show_gui), 0)
        request.assert_called_once_with(
            {
                "action": "convert_images",
                "jobId": "job-1",
                "format": "webp",
                "quality": 80,
            }
        )

        progress = build_parser().parse_args(
            [
                "convert-images", "--job", "job-1", "--format", "webp",
                "--execute", "--yes", "--progress-json",
            ]
        )
        executed = {
            **result,
            "executed": True,
            "convertedCount": 3,
            "skippedExistingCount": 0,
            "failedCount": 0,
            "cancelled": False,
            "success": True,
        }

        def convert_with_progress(*_args, **kwargs):
            kwargs["progress_callback"](
                {
                    "current": 1,
                    "total": 3,
                    "converted": 1,
                    "skipped": 0,
                    "failed": 0,
                    "status": "converted",
                }
            )
            return executed

        output = StringIO()
        with (
            patch("toki_app.convert_job_images", side_effect=convert_with_progress),
            redirect_stdout(output),
        ):
            self.assertEqual(run_cli(progress), 0)
        lines = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(lines[0]["event"], "progress")
        self.assertEqual(lines[1]["event"], "result")
        self.assertTrue(lines[1]["result"]["ok"])

        cancel = build_parser().parse_args(
            ["cancel-conversion", "--job", "job-1"]
        )
        with (
            patch("toki_app.ensure_gui_running"),
            patch(
                "toki_app.control_request",
                return_value={"cancelled": True, "jobId": "job-1"},
            ) as cancel_request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(cancel), 0)
        cancel_request.assert_called_once_with(
            {"action": "cancel_image_conversion", "jobId": "job-1"}
        )

    def test_work_and_run_detail_arguments(self) -> None:
        info = build_parser().parse_args(["info", "--job", "job-1", "--json"])
        self.assertEqual(info.job, "job-1")
        self.assertTrue(info.json)
        runs = build_parser().parse_args(
            ["runs", "--job", "job-1", "--limit", "25", "--offset", "50", "--json"]
        )
        self.assertEqual(runs.limit, 25)
        self.assertEqual(runs.offset, 50)
        run_info = build_parser().parse_args(["run-info", "--run", "run-1"])
        self.assertEqual(run_info.run, "run-1")
        run_logs = build_parser().parse_args(
            ["run-logs", "--run", "run-1", "--tail", "250", "--json"]
        )
        self.assertEqual(run_logs.tail, 250)
        self.assertTrue(run_logs.json)
        run_log = build_parser().parse_args(["run-log", "--run", "run-1"])
        self.assertEqual(run_log.run, "run-1")
        close_run_log = build_parser().parse_args(["run-log", "--close"])
        self.assertTrue(close_run_log.close)

    def test_note_and_open_source_arguments(self) -> None:
        note = build_parser().parse_args(
            ["set-note", "--job", "job-1", "--text", "확인 필요"]
        )
        self.assertEqual(note.text, "확인 필요")
        source = build_parser().parse_args(["open-source", "--job", "job-1"])
        self.assertEqual(source.job, "job-1")
        cover = build_parser().parse_args(["open-cover", "--job", "job-1"])
        self.assertEqual(cover.job, "job-1")
        refresh = build_parser().parse_args(["refresh-metadata", "--job", "job-1"])
        self.assertEqual(refresh.job, "job-1")
        details = build_parser().parse_args(["details", "--job", "job-1"])
        self.assertEqual(details.job, "job-1")
        close_details = build_parser().parse_args(["details", "--close"])
        self.assertTrue(close_details.close)


if __name__ == "__main__":
    unittest.main()
