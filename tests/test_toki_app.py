from __future__ import annotations

import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

from toki_app import build_parser, run_cli


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
            ["cleanup-records", "--status", "completed", "--status", "error", "--yes"]
        )
        self.assertEqual(cleanup.status, ["completed", "error"])
        self.assertTrue(cleanup.yes)
        refresh = build_parser().parse_args(["refresh-list"])
        self.assertEqual(refresh.command, "refresh-list")

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
