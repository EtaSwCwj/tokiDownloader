from __future__ import annotations

import unittest

from toki_app import build_parser


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
