from __future__ import annotations

import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import toki_app
from toki_app import ControlError, build_parser, run_cli
from toki_core import DownloadJob, DownloadRun


class CliControlContractTests(unittest.TestCase):
    def test_gui_control_commands_send_exact_ipc_requests(self) -> None:
        screenshot_path = str(Path("audit-screenshot.png").resolve())
        cases = (
            ("stop", ["stop", "--job", "active-1"], {"action": "stop", "jobId": "active-1"}, 0),
            ("cancel", ["cancel", "--job", "queued-1"], {"action": "cancel", "jobId": "queued-1"}, 0),
            ("pause", ["pause", "--job", "active-1"], {"action": "pause", "jobId": "active-1"}, 0),
            ("resume", ["resume", "--job", "active-1"], {"action": "resume", "jobId": "active-1"}, 0),
            ("retry", ["retry", "--job", "work-1"], {"action": "retry", "jobId": "work-1"}, 0),
            ("status", ["status", "--json"], {"action": "status"}, 0),
            ("queue-list", ["queue", "list", "--json"], {"action": "queue_list"}, 1),
            (
                "queue-before",
                ["queue", "move", "--job", "queued-2", "--before", "queued-1"],
                {
                    "action": "queue_move",
                    "jobId": "queued-2",
                    "beforeJobId": "queued-1",
                    "position": "",
                },
                1,
            ),
            (
                "queue-first",
                ["queue", "move", "--job", "queued-2", "--first"],
                {
                    "action": "queue_move",
                    "jobId": "queued-2",
                    "beforeJobId": "",
                    "position": "first",
                },
                1,
            ),
            (
                "queue-last",
                ["queue", "move", "--job", "queued-2", "--last"],
                {
                    "action": "queue_move",
                    "jobId": "queued-2",
                    "beforeJobId": "",
                    "position": "last",
                },
                1,
            ),
            ("details-show", ["details", "--job", "work-1"], {"action": "show_details", "jobId": "work-1"}, 1),
            ("details-close", ["details", "--close"], {"action": "close_details", "jobId": None}, 1),
            ("run-log-show", ["run-log", "--run", "run-1"], {"action": "show_run_log", "runId": "run-1"}, 1),
            ("run-log-close", ["run-log", "--close"], {"action": "close_run_log", "runId": None}, 1),
            ("info", ["info", "--job", "work-1", "--json"], {"action": "job_info", "jobId": "work-1"}, 0),
            (
                "runs",
                ["runs", "--job", "work-1", "--limit", "25", "--offset", "50", "--json"],
                {"action": "list_runs", "jobId": "work-1", "limit": 25, "offset": 50},
                0,
            ),
            (
                "set-note",
                ["set-note", "--job", "work-1", "--text", "review"],
                {"action": "set_note", "jobId": "work-1", "text": "review"},
                0,
            ),
            ("pin-on", ["pin", "--job", "work-1", "--on"], {"action": "pin_job", "jobId": "work-1", "pinned": True}, 0),
            ("pin-off", ["pin", "--job", "work-1", "--off"], {"action": "pin_job", "jobId": "work-1", "pinned": False}, 0),
            ("tag", ["tag", "--job", "work-1", "--color", "blue"], {"action": "tag_job", "jobId": "work-1", "color": "blue"}, 0),
            (
                "remove-record",
                ["remove-record", "--job", "work-1", "--yes"],
                {"action": "remove_record", "jobId": "work-1"},
                0,
            ),
            (
                "cleanup-records",
                [
                    "cleanup-records",
                    "--status",
                    "completed",
                    "--status",
                    "authentication",
                    "--status",
                    "stopped",
                    "--yes",
                ],
                {"action": "cleanup_records", "states": ["완료", "인증 필요", "중지됨"]},
                0,
            ),
            (
                "open-folder",
                ["open-folder", "--job", "work-1"],
                {"action": "open_folder", "jobId": "work-1"},
                0,
            ),
            (
                "screenshot",
                ["screenshot", "--output", "audit-screenshot.png"],
                {"action": "screenshot", "path": screenshot_path},
                1,
            ),
        )

        for name, argv, expected_request, expected_ensure_count in cases:
            with self.subTest(command=name):
                args = build_parser().parse_args(argv)
                response = (
                    {"path": screenshot_path}
                    if name == "screenshot"
                    else {"ok": True}
                )
                with (
                    patch("toki_app.gui_is_running", return_value=True),
                    patch("toki_app.ensure_gui_running") as ensure_gui,
                    patch("toki_app.control_request", return_value=response) as request,
                    redirect_stdout(StringIO()),
                ):
                    self.assertEqual(run_cli(args), 0)
                request.assert_called_once_with(expected_request)
                self.assertEqual(ensure_gui.call_count, expected_ensure_count)

    def test_set_output_creates_target_and_uses_gui_control_without_local_config_write(self) -> None:
        target = Path(r"C:\audit-output-contract").resolve()
        args = build_parser().parse_args(["set-output", str(target)])
        with (
            patch("toki_app.gui_is_running", return_value=True),
            patch.object(Path, "mkdir") as mkdir,
            patch("toki_app.control_request", return_value={"outputDir": str(target)}) as request,
            patch("toki_app.save_config") as save_config,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(args), 0)
        mkdir.assert_called_once_with(parents=True, exist_ok=True)
        request.assert_called_once_with({"action": "set_output", "path": str(target)})
        save_config.assert_not_called()

    def test_open_folder_without_gui_honors_requested_job_folder(self) -> None:
        cases = (
            (r"C:\library\work-1", r"C:\fallback", r"C:\library\work-1"),
            ("", r"C:\library-root", r"C:\library-root"),
        )
        for output_path, output_dir, expected in cases:
            with self.subTest(output_path=output_path):
                job = DownloadJob(
                    job_id="work-1",
                    url="https://example.invalid/work-1",
                    output_dir=output_dir,
                    output_path=output_path,
                )
                args = build_parser().parse_args(["open-folder", "--job", "work-1"])
                with (
                    patch("toki_app.gui_is_running", return_value=False),
                    patch("toki_app.load_job_by_id", return_value=job) as load_job,
                    patch("toki_app.load_config") as load_config,
                    patch("toki_app.open_in_explorer") as open_folder,
                    redirect_stdout(StringIO()) as stdout,
                ):
                    self.assertEqual(run_cli(args), 0)
                load_job.assert_called_once_with("work-1")
                load_config.assert_not_called()
                open_folder.assert_called_once_with(expected)
                self.assertEqual(stdout.getvalue().strip(), expected)

    def test_open_folder_without_gui_rejects_unknown_requested_job(self) -> None:
        args = build_parser().parse_args(["open-folder", "--job", "missing"])
        with (
            patch("toki_app.gui_is_running", return_value=False),
            patch("toki_app.load_job_by_id", return_value=None),
            patch("toki_app.open_in_explorer") as open_folder,
        ):
            with self.assertRaisesRegex(ControlError, "missing"):
                run_cli(args)
        open_folder.assert_not_called()

    def test_open_folder_without_job_keeps_default_output_fallback(self) -> None:
        args = build_parser().parse_args(["open-folder"])
        with (
            patch("toki_app.gui_is_running", return_value=False),
            patch("toki_app.load_config", return_value={"outputDir": r"C:\default-library"}),
            patch("toki_app.load_job_by_id") as load_job,
            patch("toki_app.open_in_explorer") as open_folder,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(args), 0)
        load_job.assert_not_called()
        open_folder.assert_called_once_with(r"C:\default-library")

    def test_destructive_record_commands_require_confirmation_before_any_backend_call(self) -> None:
        cases = (
            ["remove-record", "--job", "work-1"],
            ["cleanup-records", "--status", "completed"],
        )
        for argv in cases:
            with self.subTest(command=argv[0]):
                args = build_parser().parse_args(argv)
                with (
                    patch("toki_app.gui_is_running") as gui_running,
                    patch("toki_app.control_request") as request,
                    patch("toki_app.delete_job_record") as delete_one,
                    patch("toki_app.delete_job_records") as delete_many,
                ):
                    with self.assertRaisesRegex(ControlError, "--yes"):
                        run_cli(args)
                gui_running.assert_not_called()
                request.assert_not_called()
                delete_one.assert_not_called()
                delete_many.assert_not_called()

    def test_run_info_and_logs_remain_local_read_only_queries(self) -> None:
        run = DownloadRun(run_id="run-1", work_key="work-1", state="완료", progress=100)

        info_args = build_parser().parse_args(["run-info", "--run", "run-1", "--json"])
        with (
            patch("toki_app.load_run", return_value=run) as load_run,
            patch("toki_app.read_run_log") as read_log,
            patch("toki_app.control_request") as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(info_args), 0)
        load_run.assert_called_once_with("run-1")
        read_log.assert_not_called()
        request.assert_not_called()

        logs_args = build_parser().parse_args(
            ["run-logs", "--run", "run-1", "--tail", "20000", "--json"]
        )
        with (
            patch("toki_app.load_run", return_value=run) as load_run,
            patch("toki_app.read_run_log", return_value=["line one", "line two"]) as read_log,
            patch("toki_app.control_request") as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(logs_args), 0)
        load_run.assert_called_once_with("run-1")
        read_log.assert_called_once_with("run-1", 10000)
        request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
