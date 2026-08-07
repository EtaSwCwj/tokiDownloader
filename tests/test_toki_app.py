from __future__ import annotations

import json
import argparse
import re
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import toki_app
from toki_app import build_parser, run_cli, run_direct_download
from toki_core import default_config


class CliParserTests(unittest.TestCase):
    def test_notification_cli_reports_sets_and_previews_via_gui(self) -> None:
        status_args = build_parser().parse_args(["notifications", "status", "--json"])
        status_values = {
            "notifyOnComplete": True,
            "notifyOnError": True,
            "sound": "none",
            "messageBox": False,
            "supportedSounds": ["none", "system"],
        }
        with (
            patch("toki_app.gui_is_running", return_value=False),
            patch(
                "toki_app.notification_settings_snapshot",
                return_value=status_values,
            ) as snapshot,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(status_args), 0)
        snapshot.assert_called_once_with()

        set_args = build_parser().parse_args(
            [
                "notifications", "set", "--complete", "on", "--error", "off",
                "--sound", "system", "--message-box", "on", "--json",
            ]
        )
        saved = default_config()
        saved.update(
            {
                "notifyOnComplete": True,
                "notifyOnError": False,
                "notificationSound": "system",
                "notificationMessageBox": True,
            }
        )
        with (
            patch("toki_app.gui_is_running", return_value=True),
            patch("toki_app.control_request", return_value=saved) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(set_args), 0)
        request.assert_called_once_with(
            {
                "action": "set_settings",
                "updates": {
                    "notifyOnComplete": True,
                    "notifyOnError": False,
                    "notificationMessageBox": True,
                    "notificationSound": "system",
                },
                "reset": False,
            }
        )

        empty_set = build_parser().parse_args(["notifications", "set"])
        with self.assertRaisesRegex(toki_app.ControlError, "하나 이상"):
            run_cli(empty_set)

        preview_args = build_parser().parse_args(
            [
                "notifications", "preview", "--kind", "error",
                "--title", "실패 작품", "--detail", "네트워크 오류", "--json",
            ]
        )
        with (
            patch("toki_app.ensure_gui_running") as ensure_gui,
            patch(
                "toki_app.control_request", return_value={"executed": True}
            ) as preview_request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(preview_args), 0)
        ensure_gui.assert_called_once_with()
        preview_request.assert_called_once_with(
            {
                "action": "preview_notification",
                "kind": "error",
                "title": "실패 작품",
                "detail": "네트워크 오류",
            }
        )

        close_args = build_parser().parse_args(
            ["notifications", "close", "--json"]
        )
        with (
            patch("toki_app.ensure_gui_running"),
            patch(
                "toki_app.control_request", return_value={"closed": 1}
            ) as close_request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(close_args), 0)
        close_request.assert_called_once_with({"action": "close_notifications"})

    def test_embedded_browser_cli_plans_offline_and_guards_navigation(self) -> None:
        plan = build_parser().parse_args(
            [
                "embedded-browser", "plan", "--url",
                "https://newtoki1.org/manhwa/34360", "--json",
            ]
        )
        with (
            patch("toki_app.ensure_gui_running") as ensure_gui,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(plan), 0)
        ensure_gui.assert_not_called()

        guarded = build_parser().parse_args(
            [
                "embedded-browser", "manage", "--show-gui", "--url",
                "https://newtoki1.org/manhwa/34360", "--navigate", "--json",
            ]
        )
        with self.assertRaisesRegex(toki_app.ControlError, "--yes"):
            run_cli(guarded)

        offline = build_parser().parse_args(
            [
                "embedded-browser", "manage", "--show-gui", "--url",
                "https://newtoki1.org/manhwa/34360", "--json",
            ]
        )
        with (
            patch("toki_app.ensure_gui_running"),
            patch("toki_app.control_request", return_value={"shown": True}) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(offline), 0)
        request.assert_called_once_with(
            {
                "action": "show_embedded_browser",
                "url": "https://newtoki1.org/manhwa/34360",
                "navigate": False,
                "confirmed": False,
            }
        )

    def test_proxy_auth_cli_guards_secrets_and_supports_noninteractive_stdin(self) -> None:
        status = build_parser().parse_args(["proxy-auth", "status", "--json"])
        with self.assertRaisesRegex(toki_app.ControlError, "--yes"):
            run_cli(status)

        save = build_parser().parse_args(
            [
                "proxy-auth", "set", "--proxy", "http://127.0.0.1:8080",
                "--username", "proxy-user", "--password-stdin", "--yes", "--json",
            ]
        )
        with (
            patch("sys.stdin", StringIO("secret-password\n")),
            patch(
                "toki_app.store_proxy_credentials",
                return_value={"stored": True, "valuesExposed": False},
            ) as store,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(save), 0)
        store.assert_called_once_with(
            "http://127.0.0.1:8080", "proxy-user", "secret-password"
        )

        manage = build_parser().parse_args(
            ["proxy-auth", "manage", "--show-gui", "--json"]
        )
        with (
            patch("toki_app.ensure_gui_running"),
            patch("toki_app.control_request", return_value={"shown": True}) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(manage), 0)
        request.assert_called_once_with({"action": "show_proxy_credential_manager"})

    def test_cookie_cli_plans_without_store_and_guards_sensitive_operations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "cookies.json"
            source.write_text(
                '[{"name":"session","value":"x","domain":".example.test"}]',
                encoding="utf-8",
            )
            plan = build_parser().parse_args(
                [
                    "cookies", "plan-import", "--provider", "manatoki",
                    "--input", str(source), "--json",
                ]
            )
            with (
                patch("toki_app.import_provider_cookies") as importer,
                redirect_stdout(StringIO()),
            ):
                self.assertEqual(run_cli(plan), 0)
            importer.assert_not_called()

        status = build_parser().parse_args(
            ["cookies", "status", "--provider", "manatoki", "--json"]
        )
        with self.assertRaisesRegex(toki_app.ControlError, "--yes"):
            run_cli(status)

        confirmed = build_parser().parse_args(
            [
                "cookies", "status", "--provider", "manatoki", "--yes", "--json",
            ]
        )
        with (
            patch(
                "toki_app.provider_cookie_status",
                return_value={"provider": "manatoki", "stored": False},
            ) as status_service,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(confirmed), 0)
        status_service.assert_called_once_with("manatoki")

        manage = build_parser().parse_args(
            ["cookies", "manage", "--provider", "manatoki", "--show-gui", "--json"]
        )
        with (
            patch("toki_app.ensure_gui_running"),
            patch("toki_app.control_request", return_value={"shown": True}) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(manage), 0)
        request.assert_called_once_with(
            {"action": "show_cookie_manager", "provider": "manatoki"}
        )
    def test_public_ip_cli_plans_without_network_and_requires_yes_for_check(self) -> None:
        plan = build_parser().parse_args(["public-ip", "plan", "--json"])
        with (
            patch("toki_app.lookup_public_ip") as lookup,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(plan), 0)
        lookup.assert_not_called()

        check = build_parser().parse_args(["public-ip", "check", "--json"])
        with self.assertRaisesRegex(toki_app.ControlError, "--yes"):
            run_cli(check)

        confirmed = build_parser().parse_args(
            ["public-ip", "check", "--yes", "--json"]
        )
        with (
            patch(
                "toki_app.lookup_public_ip",
                return_value={"ok": True, "ip": "203.0.113.7"},
            ) as lookup,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(confirmed), 0)
        lookup.assert_called_once_with()

    def test_network_policy_cli_merges_provider_values_and_updates_gui(self) -> None:
        policies = {
            provider: {"requestDelayMs": 0, "backoffSeconds": 2}
            for provider in ("manatoki", "newtoki", "booktoki")
        }
        current = {
            **default_config(),
            "providerPolicies": policies,
        }
        args = build_parser().parse_args(
            [
                "network-policy", "set", "--proxy", "http://127.0.0.1:8080",
                "--speed-limit-kib", "2048", "--provider", "manatoki",
                "--request-delay-ms", "250", "--backoff", "4", "--json",
            ]
        )
        saved = {
            **current,
            "proxyUrl": "http://127.0.0.1:8080",
            "speedLimitKib": 2048,
            "providerPolicies": {
                **policies,
                "manatoki": {"requestDelayMs": 250, "backoffSeconds": 4},
            },
        }
        with (
            patch("toki_app.gui_is_running", return_value=True),
            patch("toki_app.control_request", side_effect=[current, saved]) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(args), 0)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(
            request.call_args_list[1].args[0]["updates"]["providerPolicies"]["manatoki"],
            {"requestDelayMs": 250, "backoffSeconds": 4},
        )

    def test_browser_mode_cli_reports_and_sets_shared_policy(self) -> None:
        status = build_parser().parse_args(["browser-mode", "status", "--json"])
        with (
            patch("toki_app.settings_snapshot", return_value={"showBrowser": False}),
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(status), 0)

        update = build_parser().parse_args(
            ["browser-mode", "set", "visible", "--json"]
        )
        with (
            patch("toki_app.gui_is_running", return_value=True),
            patch(
                "toki_app.control_request", return_value={"showBrowser": True}
            ) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(update), 0)
        request.assert_called_once_with(
            {
                "action": "set_settings",
                "updates": {"showBrowser": True},
                "reset": False,
            }
        )

    def test_clipboard_cli_inspects_duplicates_and_updates_monitor(self) -> None:
        inspect_args = build_parser().parse_args(
            [
                "clipboard",
                "inspect",
                "--text",
                "https://newtoki1.org/manhwa/34360",
                "--json",
            ]
        )
        existing = toki_app.DownloadJob(
            job_id="j1",
            url="https://newtoki1.org/manhwa/34360",
            output_dir="D:/Manga",
            work_key="manatoki:34360",
        )
        with (
            patch("toki_app.load_job_by_work_key", return_value=existing),
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(inspect_args), 0)

        monitor = build_parser().parse_args(
            ["clipboard", "monitor", "--state", "on", "--json"]
        )
        with (
            patch("toki_app.gui_is_running", return_value=False),
            patch(
                "toki_app.update_app_settings",
                return_value={"clipboardMonitor": True},
            ) as update,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(monitor), 0)
        update.assert_called_once_with({"clipboardMonitor": True})

    def test_completion_action_cli_sets_previews_and_cancels_without_execution(self) -> None:
        set_args = build_parser().parse_args(
            ["completion-action", "set", "--action", "shutdown", "--countdown", "30", "--json"]
        )
        values = {
            "completionAction": "shutdown",
            "completionCountdownSeconds": 30,
        }
        with (
            patch("toki_app.gui_is_running", return_value=False),
            patch("toki_app.update_app_settings", return_value=values) as update,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(set_args), 0)
        update.assert_called_once_with(
            {"completionAction": "shutdown", "completionCountdownSeconds": 30}
        )

        preview = build_parser().parse_args(
            ["completion-action", "preview", "--action", "shutdown", "--countdown", "20", "--show-gui"]
        )
        with (
            patch("toki_app.ensure_gui_running"),
            patch("toki_app.control_request", return_value={"shown": True}) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(preview), 0)
        request.assert_called_once_with(
            {
                "action": "preview_completion_action",
                "completionAction": "shutdown",
                "countdownSeconds": 20,
            }
        )

        cancel = build_parser().parse_args(["completion-action", "cancel"])
        with (
            patch("toki_app.ensure_gui_running"),
            patch(
                "toki_app.control_request", return_value={"cancelled": True}
            ) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(cancel), 0)
        request.assert_called_once_with({"action": "cancel_completion_action"})

    def test_work_copy_commands_route_to_gui_ipc(self) -> None:
        expected = {
            "copy-id": "copy_id",
            "copy-link": "copy_link",
            "copy-path": "copy_path",
            "copy-title": "copy_title",
        }
        for command, action in expected.items():
            with self.subTest(command=command):
                args = build_parser().parse_args([command, "--job", "j1"])
                with (
                    patch("toki_app.gui_is_running", return_value=True),
                    patch(
                        "toki_app.control_request", return_value={"copied": "value"}
                    ) as request,
                    redirect_stdout(StringIO()),
                ):
                    self.assertEqual(run_cli(args), 0)
                request.assert_called_once_with({"action": action, "jobId": "j1"})

    def test_work_copy_commands_work_without_running_gui(self) -> None:
        job = toki_app.DownloadJob(
            job_id="j1",
            url="https://example.test/work/1",
            output_dir="D:/Manga",
            title="작품",
            output_path="D:/Manga/작품",
        )
        with (
            patch("toki_app.gui_is_running", return_value=False),
            patch("toki_app.load_job_by_id", return_value=job),
            patch("toki_app.copy_text_to_clipboard") as clipboard,
            redirect_stdout(StringIO()),
        ):
            args = build_parser().parse_args(["copy-path", "--job", "j1"])
            self.assertEqual(run_cli(args), 0)
        clipboard.assert_called_once_with("D:/Manga/작품")

    def test_duplicate_images_cli_supports_hash_gui_and_close(self) -> None:
        report = {
            "ok": True,
            "scannedImages": 20,
            "duplicateGroupCount": 2,
            "duplicateImageCount": 4,
        }
        args = build_parser().parse_args(
            ["duplicates", "images", "--job", "j1", "--algorithm", "sha256", "--json"]
        )
        with (
            patch("toki_app.find_duplicate_images", return_value=report) as scan,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(args), 0)
        scan.assert_called_once_with("j1", algorithm="sha256")

        show = build_parser().parse_args(
            ["duplicates", "images", "--job", "j1", "--algorithm", "phash", "--show-gui"]
        )
        with (
            patch("toki_app.ensure_gui_running"),
            patch("toki_app.control_request", return_value={"shown": True}) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(show), 0)
        request.assert_called_once_with(
            {"action": "show_duplicate_images", "jobId": "j1", "algorithm": "phash"}
        )

        close = build_parser().parse_args(["duplicates", "images", "--close"])
        with (
            patch("toki_app.ensure_gui_running"),
            patch("toki_app.control_request", return_value={"closed": True}) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(close), 0)
        request.assert_called_once_with({"action": "close_duplicate_images"})

    def test_duplicate_works_cli_supports_json_gui_and_close(self) -> None:
        report = {
            "ok": True,
            "scannedWorks": 10,
            "duplicateGroupCount": 2,
            "duplicateWorkCount": 3,
        }
        args = build_parser().parse_args(["duplicates", "works", "--json"])
        with (
            patch("toki_app.find_duplicate_works", return_value=report) as scan,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(args), 0)
        scan.assert_called_once_with()

        show = build_parser().parse_args(["duplicates", "works", "--show-gui"])
        with (
            patch("toki_app.ensure_gui_running"),
            patch("toki_app.control_request", return_value={"shown": True}) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(show), 0)
        request.assert_called_once_with({"action": "show_duplicate_works"})

        close = build_parser().parse_args(["duplicates", "works", "--close"])
        with (
            patch("toki_app.ensure_gui_running"),
            patch("toki_app.control_request", return_value={"closed": True}) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(close), 0)
        request.assert_called_once_with({"action": "close_duplicate_works"})

    def test_local_archive_inspect_cli_supports_json_gui_and_close(self) -> None:
        inspect_args = build_parser().parse_args(
            ["local", "inspect", "--path", "work.cbz", "--json"]
        )
        report = {
            "ok": True,
            "format": "zip",
            "fileCount": 3,
            "imageCount": 2,
            "suspiciousPathCount": 0,
        }
        with (
            patch("toki_app.inspect_local_archive", return_value=report) as inspect,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(inspect_args), 0)
        inspect.assert_called_once_with(Path("work.cbz"))

        show_args = build_parser().parse_args(
            ["local", "inspect", "--path", "work.cbz", "--show-gui"]
        )
        with (
            patch("toki_app.ensure_gui_running"),
            patch("toki_app.control_request", return_value={"shown": True}) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(show_args), 0)
        request.assert_called_once_with(
            {"action": "show_archive_inspection", "path": "work.cbz"}
        )

        close_args = build_parser().parse_args(["local", "inspect", "--close"])
        with (
            patch("toki_app.ensure_gui_running"),
            patch("toki_app.control_request", return_value={"closed": True}) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(close_args), 0)
        request.assert_called_once_with({"action": "close_archive_inspection"})

    def test_group_cli_routes_service_and_gui_management_contracts(self) -> None:
        create_args = build_parser().parse_args(
            ["group", "create", "--name", "나중에 읽기", "--json"]
        )
        with (
            patch("toki_app.gui_is_running", return_value=False),
            patch(
                "toki_app.create_work_collection",
                return_value={"groupId": "g1", "name": "나중에 읽기"},
            ) as creator,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(create_args), 0)
        creator.assert_called_once_with("나중에 읽기")

        assign_args = build_parser().parse_args(
            ["group", "assign", "--job", "job-1", "--group", "g1", "--json"]
        )
        with (
            patch("toki_app.gui_is_running", return_value=True),
            patch(
                "toki_app.control_request",
                return_value={"ok": True, "group": {"name": "나중에 읽기"}},
            ) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(assign_args), 0)
        request.assert_called_once_with(
            {"action": "assign_group", "jobId": "job-1", "groupId": "g1"}
        )

        manage_args = build_parser().parse_args(["group", "manage", "--show-gui"])
        with (
            patch("toki_app.ensure_gui_running"),
            patch("toki_app.control_request", return_value={"shown": True}) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(manage_args), 0)
        request.assert_called_once_with({"action": "show_group_manager"})

    def test_jobs_snapshot_cli_previews_and_requires_confirmation(self) -> None:
        export_args = build_parser().parse_args(
            ["jobs", "export", "--output", "jobs.json", "--json"]
        )
        with (
            patch(
                "toki_app.export_jobs_snapshot",
                return_value={"ok": True, "jobCount": 2, "runCount": 3},
            ) as exporter,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(export_args), 0)
        exporter.assert_called_once_with(Path("jobs.json"))

        preview_args = build_parser().parse_args(
            ["jobs", "import", "--input", "jobs.json", "--dry-run", "--json"]
        )
        with (
            patch(
                "toki_app.import_jobs_snapshot",
                return_value={"ok": True, "pendingJobs": 2, "pendingRuns": 3},
            ) as importer,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(preview_args), 0)
        importer.assert_called_once_with(Path("jobs.json"), execute=False)

        unsafe_args = build_parser().parse_args(
            ["jobs", "import", "--input", "jobs.json", "--execute", "--json"]
        )
        with self.assertRaises(ValueError):
            run_cli(unsafe_args)

        gui_args = build_parser().parse_args(
            [
                "jobs", "import", "--input", "jobs.json", "--execute", "--yes",
                "--via-gui", "--json",
            ]
        )
        with (
            patch("toki_app.ensure_gui_running"),
            patch("toki_app.control_request", return_value={"ok": True}) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(gui_args), 0)
        request.assert_called_once_with(
            {"action": "import_jobs_snapshot", "input": "jobs.json", "execute": True}
        )

        show_args = build_parser().parse_args(
            ["jobs", "import", "--input", "jobs.json", "--show-gui"]
        )
        with (
            patch("toki_app.ensure_gui_running"),
            patch("toki_app.control_request", return_value={"shown": True}) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(show_args), 0)
        request.assert_called_once_with(
            {"action": "show_jobs_snapshot_import", "input": "jobs.json"}
        )

        close_args = build_parser().parse_args(["jobs", "import", "--close"])
        with (
            patch("toki_app.ensure_gui_running"),
            patch("toki_app.control_request", return_value={"closed": True}) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(close_args), 0)
        request.assert_called_once_with({"action": "close_jobs_snapshot_import"})

    def test_config_cli_routes_get_set_export_import_and_reset(self) -> None:
        get_args = build_parser().parse_args(
            ["config", "get", "--key", "theme", "--json"]
        )
        with (
            patch("toki_app.gui_is_running", return_value=False),
            patch("toki_app.settings_snapshot", return_value={"theme": "dark"}),
            redirect_stdout(StringIO()) as output,
        ):
            self.assertEqual(run_cli(get_args), 0)
        self.assertEqual(json.loads(output.getvalue())["value"], "dark")

        set_args = build_parser().parse_args(
            ["config", "set", "--key", "workConcurrency", "--value", "3", "--json"]
        )
        with (
            patch("toki_app.gui_is_running", return_value=False),
            patch("toki_app.update_app_settings", return_value={"workConcurrency": 3}) as setter,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(set_args), 0)
        setter.assert_called_once_with({"workConcurrency": 3})

        export_args = build_parser().parse_args(
            ["config", "export", "--output", "settings.json", "--json"]
        )
        with (
            patch("toki_app.export_app_settings", return_value={"ok": True}) as exporter,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(export_args), 0)
        exporter.assert_called_once_with(Path("settings.json"))

        import_args = build_parser().parse_args(
            ["config", "import", "--input", "settings.json", "--execute", "--yes", "--json"]
        )
        with (
            patch("toki_app.gui_is_running", return_value=False),
            patch("toki_app.import_app_settings", return_value={"ok": True}) as importer,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(import_args), 0)
        importer.assert_called_once_with(Path("settings.json"), execute=True)

        reset_args = build_parser().parse_args(
            ["config", "reset", "--execute", "--yes", "--json"]
        )
        with (
            patch("toki_app.gui_is_running", return_value=False),
            patch("toki_app.reset_app_settings", return_value={"ok": True}) as resetter,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(reset_args), 0)
        resetter.assert_called_once_with(execute=True)

        running_set = build_parser().parse_args(
            ["config", "set", "--key", "theme", "--value", "dark", "--json"]
        )
        with (
            patch("toki_app.gui_is_running", return_value=True),
            patch(
                "toki_app.control_request", return_value={"theme": "dark"}
            ) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(running_set), 0)
        request.assert_called_once_with(
            {
                "action": "set_settings",
                "updates": {"theme": "dark"},
                "reset": False,
            }
        )

        running_import = build_parser().parse_args(
            ["config", "import", "--input", "settings.json", "--execute", "--yes", "--json"]
        )
        with (
            patch("toki_app.gui_is_running", return_value=True),
            patch("toki_app.control_request", return_value={"ok": True}) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(running_import), 0)
        request.assert_called_once_with(
            {"action": "import_settings", "input": "settings.json", "execute": True}
        )

    def test_version_file_is_semver_and_cli_reports_same_value(self) -> None:
        version = (toki_app.ROOT_DIR / "VERSION").read_text(encoding="utf-8").strip()
        self.assertRegex(version, r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")

        with redirect_stdout(StringIO()) as output, self.assertRaises(SystemExit) as exit_result:
            build_parser().parse_args(["--version"])

        self.assertEqual(exit_result.exception.code, 0)
        self.assertEqual(output.getvalue().strip(), f"toki-cli {version}")

    def test_readme_covers_every_top_level_cli_command(self) -> None:
        parser = build_parser()
        subparsers = next(
            action
            for action in parser._actions
            if isinstance(action, argparse._SubParsersAction)
        )
        commands = set(subparsers.choices)
        readme = (toki_app.ROOT_DIR / "README.md").read_text(encoding="utf-8")
        documented = set(
            re.findall(r"(?:\.\\)?toki-cli\.cmd\s+([a-z][a-z-]*)", readme)
        )

        self.assertEqual(commands - documented, set())
        self.assertEqual(documented - commands, set())

    def test_diagnostics_export_cli_supports_direct_and_gui_contracts(self) -> None:
        direct_args = build_parser().parse_args(
            ["diagnostics", "export", "--output", "bundle.zip", "--json"]
        )
        result = {"ok": True, "path": "bundle.zip", "bytes": 100, "files": []}
        with (
            patch("toki_app.export_diagnostics", return_value=result) as service,
            redirect_stdout(StringIO()) as output,
        ):
            self.assertEqual(run_cli(direct_args), 0)
        service.assert_called_once_with(Path("bundle.zip"))
        self.assertEqual(json.loads(output.getvalue())["path"], "bundle.zip")

        gui_args = build_parser().parse_args(
            ["diagnostics", "export", "--via-gui", "--json"]
        )
        with (
            patch("toki_app.ensure_gui_running") as ensure_gui,
            patch("toki_app.control_request", return_value=result) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(gui_args), 0)
        ensure_gui.assert_called_once_with()
        request.assert_called_once_with({"action": "export_diagnostics", "output": ""})

    def test_migrate_cli_reports_and_applies_shared_schema_services(self) -> None:
        status_args = build_parser().parse_args(["migrate", "status", "--json"])
        schema = {"ok": True, "version": 1, "currentVersion": 2}
        with (
            patch("toki_app.config_schema_status", return_value=schema) as config_status,
            patch("toki_app.database_schema_status", return_value=schema) as db_status,
            redirect_stdout(StringIO()) as output,
        ):
            self.assertEqual(run_cli(status_args), 0)
        self.assertTrue(json.loads(output.getvalue())["ok"])
        config_status.assert_called_once_with()
        db_status.assert_called_once_with()

        apply_args = build_parser().parse_args(["migrate", "apply", "--json"])
        applied = {"ok": True, "after": {"version": 2, "currentVersion": 2}}
        with (
            patch("toki_app.apply_config_migrations", return_value=applied) as config_apply,
            patch("toki_app.apply_database_migrations", return_value=applied) as db_apply,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(apply_args), 0)
        config_apply.assert_called_once_with()
        db_apply.assert_called_once_with()

    def test_doctor_cli_can_open_gui_report(self) -> None:
        args = build_parser().parse_args(["doctor", "--show-gui", "--json"])
        report = {
            "shown": True,
            "report": {
                "ok": True,
                "required": {"passed": 5, "total": 5, "missing": []},
                "checks": [],
            },
        }
        with (
            patch("toki_app.ensure_gui_running") as ensure_gui,
            patch("toki_app.control_request", return_value=report) as request,
            redirect_stdout(StringIO()),
        ):
            exit_code = run_cli(args)

        self.assertEqual(exit_code, 0)
        ensure_gui.assert_called_once_with()
        request.assert_called_once_with({"action": "show_doctor"})

    def test_doctor_cli_returns_shared_dependency_report(self) -> None:
        args = build_parser().parse_args(["doctor", "--json"])
        report = {
            "ok": True,
            "required": {"passed": 1, "total": 1, "missing": []},
            "optional": {"available": 0, "total": 1},
            "checks": [
                {
                    "name": "Python",
                    "kind": "required",
                    "available": True,
                    "version": "3.13",
                    "path": "python.exe",
                }
            ],
        }
        with (
            patch("toki_app.dependency_diagnostics", return_value=report) as service,
            redirect_stdout(StringIO()) as output,
        ):
            exit_code = run_cli(args)

        self.assertEqual(exit_code, 0)
        service.assert_called_once_with()
        self.assertTrue(json.loads(output.getvalue())["ok"])

    def test_performance_stability_cli_can_start_gui_contract(self) -> None:
        args = build_parser().parse_args(
            ["performance", "stability", "--records", "500", "--cycles", "5", "--via-gui", "--json"]
        )
        result = {"started": True, "running": True, "last": None}
        with (
            patch("toki_app.ensure_gui_running") as ensure_gui,
            patch("toki_app.control_request", return_value=result) as request,
            redirect_stdout(StringIO()),
        ):
            exit_code = run_cli(args)

        self.assertEqual(exit_code, 0)
        ensure_gui.assert_called_once_with()
        request.assert_called_once_with(
            {
                "action": "start_stability_test",
                "records": 500,
                "cycles": 5,
                "output": "",
            }
        )

    def test_performance_stability_cli_uses_shared_recovery_service(self) -> None:
        args = build_parser().parse_args(
            ["performance", "stability", "--records", "500", "--cycles", "5", "--json"]
        )
        result = {
            "ok": True,
            "records": 500,
            "cycles": 5,
            "integrity": "ok",
            "durationMs": 10.0,
            "forcedTermination": {"recoveryPassed": True},
            "reportPath": "report.json",
        }
        with (
            patch("toki_app.run_stability_recovery_test", return_value=result) as service,
            redirect_stdout(StringIO()) as output,
        ):
            exit_code = run_cli(args)

        self.assertEqual(exit_code, 0)
        service.assert_called_once_with(records=500, cycles=5, report_path=None)
        self.assertTrue(json.loads(output.getvalue())["forcedTermination"]["recoveryPassed"])

    def test_performance_resources_cli_uses_gui_state_when_running(self) -> None:
        args = build_parser().parse_args(["performance", "resources", "--json"])
        result = {
            "ok": True,
            "limits": {
                "ioThreads": 4,
                "cpuProcesses": 2,
                "maxPendingDownloads": 1000,
            },
        }
        with (
            patch("toki_app.gui_is_running", return_value=True),
            patch("toki_app.control_request", return_value=result) as request,
            redirect_stdout(StringIO()) as output,
        ):
            exit_code = run_cli(args)
        self.assertEqual(exit_code, 0)
        request.assert_called_once_with({"action": "resource_status"})
        self.assertEqual(json.loads(output.getvalue())["limits"]["cpuProcesses"], 2)

    def test_retention_cli_reports_status_and_executes_via_gui(self) -> None:
        status_args = build_parser().parse_args(["retention", "status", "--json"])
        with (
            patch(
                "toki_app.log_retention_status",
                return_value={"ok": True, "fileCount": 2, "totalBytes": 2048},
            ),
            patch(
                "toki_app.cleanup_run_history",
                return_value={"ok": True, "candidateRuns": 4},
            ),
            redirect_stdout(StringIO()) as output,
        ):
            status_exit = run_cli(status_args)
        self.assertEqual(status_exit, 0)
        self.assertEqual(json.loads(output.getvalue())["runs"]["candidateRuns"], 4)

        execute_args = build_parser().parse_args(
            [
                "retention", "cleanup-runs", "--max-per-work", "20",
                "--max-age-days", "90", "--execute", "--json",
            ]
        )
        with (
            patch("toki_app.gui_is_running", return_value=True),
            patch(
                "toki_app.control_request",
                return_value={"ok": True, "candidateRuns": 4, "removedRuns": 4},
            ) as request,
            redirect_stdout(StringIO()),
        ):
            execute_exit = run_cli(execute_args)
        self.assertEqual(execute_exit, 0)
        request.assert_called_once_with(
            {"action": "cleanup_run_history", "maxPerWork": 20, "maxAgeDays": 90}
        )

    def test_thumbnail_cache_cli_previews_and_executes_through_running_gui(self) -> None:
        report = {
            "ok": True,
            "existingFiles": 12,
            "existingBytes": 4096,
            "removeFiles": 3,
            "removeBytes": 1024,
        }
        status = build_parser().parse_args(["thumbnail-cache", "status", "--json"])
        with (
            patch("toki_app.cleanup_thumbnail_cache", return_value=report) as cleanup,
            redirect_stdout(StringIO()),
        ):
            status_exit = run_cli(status)
        self.assertEqual(status_exit, 0)
        cleanup.assert_called_once_with(execute=False)

        execute = build_parser().parse_args(
            ["thumbnail-cache", "cleanup", "--execute", "--json"]
        )
        with (
            patch("toki_app.gui_is_running", return_value=True),
            patch("toki_app.control_request", return_value=report) as request,
            redirect_stdout(StringIO()),
        ):
            execute_exit = run_cli(execute)
        self.assertEqual(execute_exit, 0)
        request.assert_called_once_with({"action": "cleanup_thumbnail_cache"})

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
            "theme": "system",
            "trayEnabled": False,
            "closeToTray": False,
            "minimizeToTray": False,
            "notifyOnComplete": True,
            "notifyOnError": True,
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
                "--row-density", "compact", "--theme", "dark", "--json",
                "--view-mode", "icon", "--thumbnails", "off",
                "--thumbnail-size", "large", "--always-on-top", "on",
                "--opacity", "85",
                "--quick-actions", "settings.open,folder.open,download.start",
                "--folder-template", "[{site}][{id}] {title}",
                "--language", "ko", "--ui-scale", "125", "--font", "Arial",
                "--clear-background",
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
                    "theme": "dark",
                    "listViewMode": "icon",
                    "thumbnailSize": "large",
                    "windowOpacity": 85,
                    "quickActions": [
                        "settings.open",
                        "folder.open",
                        "download.start",
                    ],
                    "folderNameTemplate": "[{site}][{id}] {title}",
                    "uiLanguage": "ko",
                    "uiScale": 125,
                    "fontFamily": "Arial",
                    "backgroundImage": "",
                    "showBrowser": True,
                    "logVisible": False,
                    "thumbnailsVisible": False,
                    "alwaysOnTop": True,
                },
                "reset": False,
            }
        )

        show = build_parser().parse_args(
            ["settings", "--show-gui", "--tab", "provider", "--search", "yt-dlp"]
        )
        with (
            patch("toki_app.ensure_gui_running"),
            patch("toki_app.control_request", return_value={"shown": True}) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(show), 0)
        request.assert_called_once_with(
            {"action": "show_settings", "tab": "provider", "search": "yt-dlp"}
        )

        close = build_parser().parse_args(["settings", "--close"])
        with (
            patch("toki_app.ensure_gui_running"),
            patch("toki_app.control_request", return_value={"closed": True}) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(close), 0)
        request.assert_called_once_with({"action": "close_settings"})

        tray = build_parser().parse_args(
            ["tray", "notify", "--message", "완료 테스트"]
        )
        with (
            patch("toki_app.ensure_gui_running"),
            patch(
                "toki_app.control_request",
                return_value={"enabled": True, "visible": True},
            ) as tray_request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(tray), 0)
        tray_request.assert_called_once_with(
            {"action": "tray", "command": "notify", "message": "완료 테스트"}
        )

    def test_language_cli_lists_status_and_updates_through_gui_contract(self) -> None:
        list_args = build_parser().parse_args(["language", "list", "--json"])
        with redirect_stdout(StringIO()):
            self.assertEqual(run_cli(list_args), 0)

        status_args = build_parser().parse_args(["language", "status", "--json"])
        with (
            patch("toki_app.settings_snapshot", return_value={"uiLanguage": "ko"}),
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(status_args), 0)

        set_args = build_parser().parse_args(["language", "set", "ko", "--json"])
        with (
            patch("toki_app.gui_is_running", return_value=True),
            patch(
                "toki_app.control_request", return_value={"uiLanguage": "ko"}
            ) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(set_args), 0)
        request.assert_called_once_with(
            {
                "action": "set_settings",
                "updates": {"uiLanguage": "ko"},
                "reset": False,
            }
        )

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

    def test_refresh_list_reports_gui_loading_failure_with_nonzero_exit(self) -> None:
        args = build_parser().parse_args(["refresh-list"])
        with (
            patch("toki_app.ensure_gui_running"),
            patch(
                "toki_app.control_request",
                return_value={
                    "refreshed": False,
                    "viewState": {"state": "error", "message": "DB 읽기 실패"},
                },
            ),
            redirect_stdout(StringIO()) as output,
        ):
            exit_code = run_cli(args)
        result = json.loads(output.getvalue())
        self.assertEqual(exit_code, 2)
        self.assertFalse(result["ok"])
        self.assertEqual(result["viewState"]["state"], "error")

    def test_list_state_parser_and_local_json_contract(self) -> None:
        args = build_parser().parse_args(
            ["list-state", "--query", "없는 작품", "--json"]
        )
        self.assertEqual(args.command, "list-state")
        self.assertEqual(args.preview, "auto")
        with (
            patch("toki_app.count_jobs", side_effect=[4, 0]),
            redirect_stdout(StringIO()) as output,
        ):
            exit_code = run_cli(args)
        result = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(result["state"], "no_results")
        self.assertEqual(result["action"], "reset_filters")

    def test_list_state_gui_preview_uses_ipc_contract(self) -> None:
        args = build_parser().parse_args(
            [
                "list-state",
                "--apply-gui",
                "--preview",
                "error",
                "--message",
                "진단 오류",
                "--json",
            ]
        )
        with (
            patch("toki_app.ensure_gui_running"),
            patch(
                "toki_app.control_request",
                return_value={"state": "error", "message": "진단 오류"},
            ) as request,
            redirect_stdout(StringIO()),
        ):
            exit_code = run_cli(args)
        self.assertEqual(exit_code, 0)
        request.assert_called_once_with(
            {
                "action": "preview_list_view_state",
                "state": "error",
                "message": "진단 오류",
            }
        )

    def test_shortcuts_and_focus_cli_contracts(self) -> None:
        shortcuts = build_parser().parse_args(["shortcuts", "--json"])
        with redirect_stdout(StringIO()) as output:
            shortcut_exit = run_cli(shortcuts)
        shortcut_result = json.loads(output.getvalue())
        self.assertEqual(shortcut_exit, 0)
        self.assertGreater(shortcut_result["count"], 10)

        shortcut_window = build_parser().parse_args(["shortcuts", "--show-gui"])
        with (
            patch("toki_app.ensure_gui_running"),
            patch("toki_app.control_request", return_value={"shown": True}) as shortcut_request,
            redirect_stdout(StringIO()),
        ):
            window_exit = run_cli(shortcut_window)
        self.assertEqual(window_exit, 0)
        shortcut_request.assert_called_once_with({"action": "show_shortcut_help"})

    def test_shortcut_cli_edits_exports_and_guards_import_execution(self) -> None:
        current = default_config()
        updated = {**current, "shortcutOverrides": {"focus.search": ["Ctrl+Alt+F"]}}
        set_args = build_parser().parse_args(
            [
                "shortcuts", "--set", "focus.search", "--keys", "Ctrl+Alt+F",
                "--json",
            ]
        )
        with (
            patch("toki_app.settings_snapshot", return_value=current),
            patch("toki_app.gui_is_running", return_value=False),
            patch("toki_app.update_app_settings", return_value=updated) as update,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(set_args), 0)
        update.assert_called_once_with(
            {"shortcutOverrides": {"focus.search": ["Ctrl+Alt+F"]}}
        )

        invalid_combinations = (
            (["shortcuts", "--keys", "Ctrl+F"], "--keys"),
            (["shortcuts", "--execute"], "--execute"),
            (["shortcuts", "--yes"], "--yes"),
            (["shortcuts", "--reset", "unknown.action"], "지원하지 않는"),
        )
        for arguments, message in invalid_combinations:
            with self.subTest(arguments=arguments):
                parsed = build_parser().parse_args(arguments)
                with self.assertRaisesRegex(toki_app.ControlError, message):
                    run_cli(parsed)

        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "shortcuts.json"
            source.write_text(
                json.dumps(
                    {
                        "format": "tokiDownloader-shortcuts",
                        "formatVersion": 1,
                        "shortcutOverrides": {"focus.search": ["Ctrl+Alt+F"]},
                    }
                ),
                encoding="utf-8",
            )
            guarded = build_parser().parse_args(
                ["shortcuts", "--import", str(source), "--execute", "--json"]
            )
            with self.assertRaisesRegex(toki_app.ControlError, "--yes"):
                run_cli(guarded)

        focus = build_parser().parse_args(
            ["focus", "--target", "next", "--json"]
        )
        with (
            patch("toki_app.ensure_gui_running"),
            patch(
                "toki_app.control_request",
                return_value={
                    "focus": "list",
                    "selectedRow": 1,
                    "selectedJobId": "job-2",
                },
            ) as request,
            redirect_stdout(StringIO()),
        ):
            focus_exit = run_cli(focus)
        self.assertEqual(focus_exit, 0)
        request.assert_called_once_with(
            {"action": "keyboard_focus", "target": "next", "clear": False}
        )

    def test_window_cli_supports_screen_center_and_safe_restore(self) -> None:
        args = build_parser().parse_args(
            ["window", "--screen", "Side Display", "--center", "--safe"]
        )
        with (
            patch("toki_app.ensure_gui_running"),
            patch(
                "toki_app.control_request",
                return_value={"screenName": "Side Display", "onScreen": True},
            ) as request,
            redirect_stdout(StringIO()),
        ):
            exit_code = run_cli(args)
        self.assertEqual(exit_code, 0)
        request.assert_called_once_with(
            {
                "action": "window",
                "x": None,
                "y": None,
                "width": None,
                "height": None,
                "maximized": None,
                "screenName": "Side Display",
                "center": True,
                "safe": True,
            }
        )

    def test_performance_audit_supports_local_json_and_gui_dialog(self) -> None:
        local = build_parser().parse_args(["performance", "audit", "--json"])
        report = {
            "ok": True,
            "jobCount": 10000,
            "runCount": 12000,
            "elapsedMs": 4.2,
            "queries": [{"ok": True}],
        }
        with (
            patch("toki_app.job_database_diagnostics", return_value=report),
            redirect_stdout(StringIO()) as output,
        ):
            local_exit = run_cli(local)
        self.assertEqual(local_exit, 0)
        self.assertEqual(json.loads(output.getvalue())["jobCount"], 10000)

        shown = build_parser().parse_args(["performance", "audit", "--show-gui"])
        with (
            patch("toki_app.ensure_gui_running"),
            patch(
                "toki_app.control_request",
                return_value={"shown": True, "report": report},
            ) as request,
            redirect_stdout(StringIO()),
        ):
            gui_exit = run_cli(shown)
        self.assertEqual(gui_exit, 0)
        request.assert_called_once_with({"action": "show_performance_diagnostics"})

    def test_performance_benchmark_cli_passes_sizes_page_and_output(self) -> None:
        args = build_parser().parse_args(
            [
                "performance", "benchmark", "--sizes", "100", "1000",
                "--page-size", "50", "--output", r"C:\보고서\성능.json", "--json",
            ]
        )
        result = {
            "ok": True,
            "sizes": [100, 1000],
            "results": [],
            "reportPath": r"C:\보고서\성능.json",
        }
        with (
            patch("toki_app.run_job_database_benchmark", return_value=result) as benchmark,
            redirect_stdout(StringIO()) as output,
        ):
            exit_code = run_cli(args)
        self.assertEqual(exit_code, 0)
        benchmark.assert_called_once_with(
            [100, 1000], page_size=50, report_path=Path(r"C:\보고서\성능.json")
        )
        self.assertTrue(json.loads(output.getvalue())["ok"])

        via_gui = build_parser().parse_args(
            ["performance", "benchmark", "--via-gui", "--json"]
        )
        with (
            patch("toki_app.ensure_gui_running"),
            patch(
                "toki_app.control_request",
                return_value={"started": True, "running": True, "last": None},
            ) as request,
            redirect_stdout(StringIO()),
        ):
            gui_exit = run_cli(via_gui)
        self.assertEqual(gui_exit, 0)
        request.assert_called_once_with(
            {
                "action": "start_performance_benchmark",
                "sizes": [100, 1000, 10000, 100000],
                "pageSize": 200,
                "output": "",
            }
        )

    def test_performance_event_policy_cli_is_machine_readable(self) -> None:
        args = build_parser().parse_args(
            ["performance", "event-policy", "--event", "image_saved", "--json"]
        )
        with redirect_stdout(StringIO()) as output:
            exit_code = run_cli(args)
        result = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(result["uiMode"], "coalesced")
        self.assertEqual(result["uiIntervalMs"], 100)

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
