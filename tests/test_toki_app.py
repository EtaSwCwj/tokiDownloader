from __future__ import annotations

import json
import argparse
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch, Mock

import toki_app
from toki_app import ControlError, build_parser, local_api_http_request, run_cli, run_direct_download
from toki_core import default_config


class CliParserTests(unittest.TestCase):
    def test_launcher_cli_status_and_explicit_taskbar_repair(self) -> None:
        with patch("toki_app.runtime_status", return_value={"ok": True, "runs": []}) as status, redirect_stdout(StringIO()):
            self.assertEqual(run_cli(build_parser().parse_args(["launcher", "status", "--json"])), 0)
            status.assert_called_once_with()
        with patch("toki_app.taskbar_shortcuts", return_value={"ok": True}) as taskbar, redirect_stdout(StringIO()):
            self.assertEqual(run_cli(build_parser().parse_args(["launcher", "taskbar", "--json"])), 0)
            taskbar.assert_called_with(False)
            self.assertEqual(run_cli(build_parser().parse_args(["launcher", "taskbar", "--repair", "--json"])), 0)
            taskbar.assert_called_with(True)

    def test_fast_gui_reply_survives_false_write_wait_with_drained_queue(self) -> None:
        request = {'action': 'ping'}
        payload = (json.dumps(request, ensure_ascii=False) + '\n').encode('utf-8')
        for pending in ([0], [len(payload), 0]):
            with self.subTest(pending=pending):
                socket = Mock()
                socket.waitForConnected.return_value = True
                socket.write.return_value = len(payload)
                socket.bytesToWrite.side_effect = pending
                socket.waitForBytesWritten.return_value = False
                socket.bytesAvailable.return_value = 42
                socket.readAll.return_value = b'{"ok":true,"result":{"pong":true}}\n'
                with patch('toki_app.QLocalSocket', return_value=socket):
                    self.assertEqual(toki_app.control_request(request), {'pong': True})

    def test_pending_gui_write_timeout_never_implies_gui_is_absent(self) -> None:
        socket = Mock()
        socket.waitForConnected.return_value = True
        socket.write.side_effect = len
        socket.bytesToWrite.return_value = 10
        socket.waitForBytesWritten.return_value = False
        with patch('toki_app.QLocalSocket', return_value=socket):
            self.assertTrue(toki_app.gui_is_running())

    def test_busy_gui_ping_does_not_trigger_offline_mutations_or_second_gui(self) -> None:
        with patch("toki_app.control_request", side_effect=toki_app.ControlTimeoutError("busy")):
            self.assertTrue(toki_app.gui_is_running())
            with patch("toki_app.start_gui_background") as launch:
                toki_app.ensure_gui_running()
                launch.assert_not_called()
        with patch("toki_app.control_request", side_effect=ControlError("not connected")):
            self.assertFalse(toki_app.gui_is_running())
        with patch("toki_app.control_request", return_value={"pong": True}):
            self.assertTrue(toki_app.gui_is_running())

    def test_app_identity_cli_reports_local_and_live_gui_state(self) -> None:
        local_args = build_parser().parse_args(["app-identity", "--json"])
        local = {
            "ok": True,
            "displayName": "tokiDownloader",
            "windowsAppUserModelId": "EtaSwCwj.tokiDownloader.GUI.1",
            "iconExists": True,
            "applied": False,
        }
        with (
            patch("toki_app.application_identity_snapshot", return_value=local),
            redirect_stdout(StringIO()) as stdout,
        ):
            self.assertEqual(run_cli(local_args), 0)
        self.assertEqual(json.loads(stdout.getvalue()), local)

        live_args = build_parser().parse_args(
            ["app-identity", "--via-gui", "--json"]
        )
        live = {**local, "applied": True}
        with (
            patch("toki_app.ensure_gui_running") as ensure_live,
            patch("toki_app.control_request", return_value=live) as request,
            redirect_stdout(StringIO()) as stdout,
        ):
            self.assertEqual(run_cli(live_args), 0)
        ensure_live.assert_called_once_with()
        request.assert_called_once_with({"action": "application_identity"})
        self.assertTrue(json.loads(stdout.getvalue())["applied"])

        show_args = build_parser().parse_args(
            ["app-identity", "--show-gui", "--json"]
        )
        close_args = build_parser().parse_args(
            ["app-identity", "--close", "--json"]
        )
        with (
            patch("toki_app.ensure_gui_running") as ensure,
            patch(
                "toki_app.control_request",
                side_effect=[{"shown": True, **live}, {"closed": True}],
            ) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(show_args), 0)
            self.assertEqual(run_cli(close_args), 0)
        self.assertEqual(ensure.call_count, 2)
        self.assertEqual(
            [call.args[0] for call in request.call_args_list],
            [
                {"action": "show_application_identity"},
                {"action": "close_application_identity"},
            ],
        )

        text_close_args = build_parser().parse_args(["app-identity", "--close"])
        for closed, expected_text in (
            (True, "앱 정보 창을 닫았습니다."),
            (False, "앱 정보 창은 이미 닫혀 있습니다."),
        ):
            with (
                patch("toki_app.ensure_gui_running"),
                patch("toki_app.control_request", return_value={"closed": closed}),
                redirect_stdout(StringIO()) as stdout,
            ):
                self.assertEqual(run_cli(text_close_args), 0)
            self.assertEqual(stdout.getvalue().strip(), expected_text)

    def test_hitomi_original_image_cli_uses_shared_offline_plan(self) -> None:
        status_args = build_parser().parse_args(
            ["hitomi", "images", "status", "--json"]
        )
        with (
            patch("toki_app.gui_is_running", return_value=False),
            patch("toki_app.settings_snapshot", return_value=default_config()),
            redirect_stdout(StringIO()) as stdout,
        ):
            self.assertEqual(run_cli(status_args), 0)
        self.assertTrue(json.loads(stdout.getvalue())["useOriginal"])

        set_args = build_parser().parse_args(
            ["hitomi", "images", "set", "--original", "off", "--json"]
        )
        saved = {**default_config(), "hitomiUseOriginalImages": False}
        with (
            patch("toki_app.gui_is_running", return_value=True),
            patch("toki_app.control_request", side_effect=[default_config(), saved]) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(set_args), 0)
        self.assertEqual(
            request.call_args_list[1].args[0],
            {
                "action": "set_settings",
                "updates": {"hitomiUseOriginalImages": False},
                "reset": False,
            },
        )

        fixture = Path(__file__).parent / "fixtures" / "hitomi" / "galleryinfo_1234567.js"
        plan_args = build_parser().parse_args(
            [
                "hitomi", "images", "plan", "--input", "1234567",
                "--fixture", str(fixture), "--original", "off",
                "--sample-limit", "1", "--json",
            ]
        )
        with (
            patch("toki_app.gui_is_running", return_value=False),
            patch("toki_app.settings_snapshot", return_value=default_config()),
            redirect_stdout(StringIO()) as stdout,
        ):
            self.assertEqual(run_cli(plan_args), 0)
        result = json.loads(stdout.getvalue())
        self.assertEqual(result["sample"][0]["selectedVariant"], "webp")
        self.assertTrue(result["sampleTruncated"])
        self.assertFalse(result["networkRequested"])

    def test_hitomi_metadata_file_cli_plans_and_writes_only_with_confirmation(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "hitomi" / "galleryinfo_1234567.js"
        status_args = build_parser().parse_args(
            ["hitomi", "metadata-files", "status", "--json"]
        )
        with (
            patch("toki_app.gui_is_running", return_value=False),
            patch("toki_app.settings_snapshot", return_value=default_config()),
            redirect_stdout(StringIO()) as stdout,
        ):
            self.assertEqual(run_cli(status_args), 0)
        self.assertEqual(json.loads(stdout.getvalue())["mode"], "metadata_json")

        set_args = build_parser().parse_args(
            ["hitomi", "metadata-files", "set", "--mode", "both", "--json"]
        )
        saved = {**default_config(), "hitomiMetadataFileMode": "both"}
        with (
            patch("toki_app.gui_is_running", return_value=True),
            patch("toki_app.control_request", side_effect=[default_config(), saved]) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(set_args), 0)
        self.assertEqual(
            request.call_args_list[1].args[0],
            {
                "action": "set_settings",
                "updates": {"hitomiMetadataFileMode": "both"},
                "reset": False,
            },
        )

        with tempfile.TemporaryDirectory() as temporary:
            plan_args = build_parser().parse_args(
                [
                    "hitomi", "metadata-files", "plan", "--input", "1234567",
                    "--fixture", str(fixture), "--output", temporary,
                    "--mode", "both", "--json",
                ]
            )
            with (
                patch("toki_app.gui_is_running", return_value=False),
                patch("toki_app.settings_snapshot", return_value=default_config()),
                redirect_stdout(StringIO()) as stdout,
            ):
                self.assertEqual(run_cli(plan_args), 0)
            self.assertEqual(json.loads(stdout.getvalue())["fileCount"], 2)
            self.assertFalse((Path(temporary) / "metadata.json").exists())

            unconfirmed_args = build_parser().parse_args(
                [
                    "hitomi", "metadata-files", "write", "--input", "1234567",
                    "--fixture", str(fixture), "--output", temporary, "--json",
                ]
            )
            with (
                patch("toki_app.gui_is_running", return_value=False),
                patch("toki_app.settings_snapshot", return_value=default_config()),
            ):
                with self.assertRaises(ControlError):
                    run_cli(unconfirmed_args)

            write_args = build_parser().parse_args(
                [
                    "hitomi", "metadata-files", "write", "--input", "1234567",
                    "--fixture", str(fixture), "--output", temporary,
                    "--mode", "both", "--yes", "--json",
                ]
            )
            with (
                patch("toki_app.gui_is_running", return_value=False),
                patch("toki_app.settings_snapshot", return_value=default_config()),
                redirect_stdout(StringIO()) as stdout,
            ):
                self.assertEqual(run_cli(write_args), 0)
            result = json.loads(stdout.getvalue())
            self.assertEqual(result["writtenCount"], 2)
            self.assertTrue((Path(temporary) / "metadata.json").is_file())
            self.assertTrue((Path(temporary) / "info.txt").is_file())

    def test_hitomi_title_cli_selects_from_local_metadata(self) -> None:
        status_args = build_parser().parse_args(
            ["hitomi", "title", "status", "--json"]
        )
        with (
            patch("toki_app.gui_is_running", return_value=False),
            patch("toki_app.settings_snapshot", return_value=default_config()),
            redirect_stdout(StringIO()) as stdout,
        ):
            self.assertEqual(run_cli(status_args), 0)
        self.assertFalse(json.loads(stdout.getvalue())["preferJapanese"])

        set_args = build_parser().parse_args(
            ["hitomi", "title", "set", "--prefer-japanese", "on", "--json"]
        )
        saved = {**default_config(), "hitomiPreferJapaneseTitle": True}
        with (
            patch("toki_app.gui_is_running", return_value=True),
            patch("toki_app.control_request", side_effect=[default_config(), saved]) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(set_args), 0)
        self.assertEqual(
            request.call_args_list[1].args[0],
            {
                "action": "set_settings",
                "updates": {"hitomiPreferJapaneseTitle": True},
                "reset": False,
            },
        )

        fixture = Path(__file__).parent / "fixtures" / "hitomi" / "galleryinfo_1234567.js"
        select_args = build_parser().parse_args(
            [
                "hitomi",
                "title",
                "select",
                "--input",
                "1234567",
                "--fixture",
                str(fixture),
                "--prefer-japanese",
                "on",
                "--json",
            ]
        )
        with (
            patch("toki_app.gui_is_running", return_value=False),
            patch("toki_app.settings_snapshot", return_value=default_config()),
            redirect_stdout(StringIO()) as stdout,
        ):
            self.assertEqual(run_cli(select_args), 0)
        result = json.loads(stdout.getvalue())
        self.assertEqual(result["selectedTitle"], "日本語タイトル")
        self.assertEqual(result["selectedField"], "japaneseTitle")
        self.assertFalse(result["networkRequested"])

    def test_hitomi_excluded_tag_cli_uses_shared_offline_policy(self) -> None:
        status_args = build_parser().parse_args(
            ["hitomi", "tags", "status", "--json"]
        )
        with (
            patch("toki_app.gui_is_running", return_value=False),
            patch("toki_app.settings_snapshot", return_value=default_config()),
            redirect_stdout(StringIO()) as stdout,
        ):
            self.assertEqual(run_cli(status_args), 0)
        self.assertEqual(json.loads(stdout.getvalue())["rules"], [])

        set_args = build_parser().parse_args(
            ["hitomi", "tags", "set", "--tags", "guro, full color", "--json"]
        )
        saved = {**default_config(), "hitomiExcludedTags": ["guro", "full color"]}
        with (
            patch("toki_app.gui_is_running", return_value=True),
            patch("toki_app.control_request", side_effect=[default_config(), saved]) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(set_args), 0)
        self.assertEqual(
            request.call_args_list[1].args[0],
            {
                "action": "set_settings",
                "updates": {"hitomiExcludedTags": "guro, full color"},
                "reset": False,
            },
        )

        fixture = Path(__file__).parent / "fixtures" / "hitomi" / "galleryinfo_1234567.js"
        evaluate_args = build_parser().parse_args(
            [
                "hitomi",
                "tags",
                "evaluate",
                "--input",
                "1234567",
                "--fixture",
                str(fixture),
                "--tags",
                "full color",
                "--json",
            ]
        )
        with (
            patch("toki_app.gui_is_running", return_value=False),
            patch("toki_app.settings_snapshot", return_value=default_config()),
            redirect_stdout(StringIO()) as stdout,
        ):
            self.assertEqual(run_cli(evaluate_args), 0)
        result = json.loads(stdout.getvalue())
        self.assertTrue(result["excluded"])
        self.assertEqual(result["matches"][0]["tag"], "female:full color")
        self.assertFalse(result["networkRequested"])

        clear_args = build_parser().parse_args(
            ["hitomi", "tags", "set", "--clear", "--json"]
        )
        with (
            patch("toki_app.gui_is_running", return_value=False),
            patch("toki_app.settings_snapshot", return_value=default_config()),
            patch("toki_app.update_app_settings", return_value=default_config()) as update,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(clear_args), 0)
        update.assert_called_once_with({"hitomiExcludedTags": []})

    def test_hitomi_filename_cli_uses_shared_offline_policy(self) -> None:
        status_args = build_parser().parse_args(
            ["hitomi", "filenames", "status", "--json"]
        )
        with (
            patch("toki_app.gui_is_running", return_value=False),
            patch("toki_app.settings_snapshot", return_value=default_config()),
            redirect_stdout(StringIO()) as stdout,
        ):
            self.assertEqual(run_cli(status_args), 0)
        self.assertEqual(json.loads(stdout.getvalue())["mode"], "number_original")

        set_args = build_parser().parse_args(
            ["hitomi", "filenames", "set", "--mode", "original", "--json"]
        )
        saved = {**default_config(), "hitomiFilenameMode": "original"}
        with (
            patch("toki_app.gui_is_running", return_value=True),
            patch("toki_app.control_request", side_effect=[default_config(), saved]) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(set_args), 0)
        self.assertEqual(
            request.call_args_list[1].args[0],
            {
                "action": "set_settings",
                "updates": {"hitomiFilenameMode": "original"},
                "reset": False,
            },
        )

        fixture = Path(__file__).parent / "fixtures" / "hitomi" / "galleryinfo_1234567.js"
        plan_args = build_parser().parse_args(
            [
                "hitomi",
                "filenames",
                "plan",
                "--input",
                "1234567",
                "--fixture",
                str(fixture),
                "--mode",
                "number",
                "--sample-limit",
                "1",
                "--json",
            ]
        )
        with (
            patch("toki_app.gui_is_running", return_value=False),
            patch("toki_app.settings_snapshot", return_value=default_config()),
            redirect_stdout(StringIO()) as stdout,
        ):
            self.assertEqual(run_cli(plan_args), 0)
        result = json.loads(stdout.getvalue())
        self.assertEqual(result["sample"][0]["fileName"], "0001.jpg")
        self.assertTrue(result["sampleTruncated"])
        self.assertFalse(result["networkRequested"])

    def test_hitomi_metadata_cli_keeps_external_fetch_explicit(self) -> None:
        status_args = build_parser().parse_args(
            ["hitomi", "metadata", "status", "--json"]
        )
        with (
            patch("toki_app.gui_is_running", return_value=False),
            patch("toki_app.settings_snapshot", return_value=default_config()),
            redirect_stdout(StringIO()) as stdout,
        ):
            self.assertEqual(run_cli(status_args), 0)
        self.assertTrue(json.loads(stdout.getvalue())["enabled"])

        decide_args = build_parser().parse_args(
            [
                "hitomi",
                "metadata",
                "decide",
                "--outcome",
                "failure",
                "--error-code",
                "hitomi.metadata_network",
                "--json",
            ]
        )
        required = {**default_config(), "hitomiMetadataMode": "required"}
        with (
            patch("toki_app.gui_is_running", return_value=False),
            patch("toki_app.settings_snapshot", return_value=required),
            redirect_stdout(StringIO()) as stdout,
        ):
            self.assertEqual(run_cli(decide_args), 0)
        decision = json.loads(stdout.getvalue())
        self.assertEqual(decision["decision"], "stop")
        self.assertFalse(decision["shouldContinue"])
        self.assertFalse(decision["networkRequested"])

        set_args = build_parser().parse_args(
            ["hitomi", "metadata", "set", "--mode", "required", "--json"]
        )
        saved = {**default_config(), "hitomiMetadataMode": "required"}
        with (
            patch("toki_app.gui_is_running", return_value=True),
            patch("toki_app.control_request", side_effect=[default_config(), saved]) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(set_args), 0)
        self.assertEqual(
            request.call_args_list[1].args[0],
            {
                "action": "set_settings",
                "updates": {"hitomiMetadataMode": "required"},
                "reset": False,
            },
        )

        plan_args = build_parser().parse_args(
            [
                "hitomi",
                "metadata",
                "plan",
                "--input",
                "https://exhentai.org/g/987654/abcdef1234/",
                "--json",
            ]
        )
        with (
            patch("toki_app.gui_is_running", return_value=False),
            patch("toki_app.settings_snapshot", return_value=default_config()),
            redirect_stdout(StringIO()) as stdout,
        ):
            self.assertEqual(run_cli(plan_args), 0)
        plan = json.loads(stdout.getvalue())
        self.assertEqual(plan["request"]["body"]["gidlist"][0][1], "<gallery-token>")
        self.assertNotIn("abcdef1234", repr(plan))

        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary) / "metadata fixture.js"
            fixture.write_text(
                'var galleryinfo = {"id":"42","title":"fixture title","files":[]};',
                encoding="utf-8",
            )
            parse_args = build_parser().parse_args(
                [
                    "hitomi",
                    "metadata",
                    "parse",
                    "--input",
                    "42",
                    "--fixture",
                    str(fixture),
                    "--json",
                ]
            )
            with (
                patch("toki_app.gui_is_running", return_value=False),
                patch("toki_app.settings_snapshot", return_value=default_config()),
                redirect_stdout(StringIO()) as stdout,
            ):
                self.assertEqual(run_cli(parse_args), 0)
            self.assertEqual(json.loads(stdout.getvalue())["title"], "fixture title")

        fetch_args = build_parser().parse_args(
            [
                "hitomi",
                "metadata",
                "fetch",
                "--input",
                "https://hitomi.la/manga/sample-42.html",
                "--json",
            ]
        )
        with (
            patch("toki_app.gui_is_running", return_value=False),
            patch("toki_app.settings_snapshot", return_value=default_config()),
        ):
            with self.assertRaises(ControlError):
                run_cli(fetch_args)
        confirmed_args = build_parser().parse_args(
            [
                "hitomi",
                "metadata",
                "fetch",
                "--input",
                "https://hitomi.la/manga/sample-42.html",
                "--yes",
                "--timeout",
                "12",
                "--json",
            ]
        )
        with (
            patch("toki_app.gui_is_running", return_value=False),
            patch("toki_app.settings_snapshot", return_value=default_config()),
            patch(
                "toki_app.fetch_hitomi_metadata",
                return_value={"ok": True, "title": "fetched", "networkRequested": True},
            ) as fetch,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(confirmed_args), 0)
        fetch.assert_called_once_with(
            "https://hitomi.la/manga/sample-42.html",
            provider_hint="auto",
            config=default_config(),
            timeout=12,
            confirmed=True,
        )

        with (
            patch("toki_app.gui_is_running", return_value=False),
            patch("toki_app.settings_snapshot", return_value=default_config()),
            patch(
                "toki_app.fetch_hitomi_metadata",
                side_effect=toki_app.HitomiReferenceError(
                    "hitomi.metadata_dns", "DNS 주소를 확인하지 못했습니다."
                ),
            ),
            redirect_stdout(StringIO()) as stdout,
        ):
            self.assertEqual(run_cli(confirmed_args), 2)
        failed = json.loads(stdout.getvalue())
        self.assertEqual(failed["errorCode"], "hitomi.metadata_dns")
        self.assertEqual(
            failed["metadataPolicy"]["decision"], "continue_without_metadata"
        )

        cookie_fetch_args = build_parser().parse_args(
            [
                "hitomi", "metadata", "fetch",
                "--input", "https://exhentai.org/g/987654/abcdef1234/",
                "--use-cookies", "--yes", "--json",
            ]
        )
        with (
            patch("toki_app.gui_is_running", return_value=False),
            patch("toki_app.settings_snapshot", return_value=default_config()),
            patch(
                "toki_app.provider_cookie_request_header",
                return_value="ipb_member_id=member; ipb_pass_hash=secret",
            ) as cookie_header,
            patch(
                "toki_app.fetch_hitomi_metadata",
                return_value={"ok": True, "networkRequested": True},
            ) as fetch,
            redirect_stdout(StringIO()) as output,
        ):
            self.assertEqual(run_cli(cookie_fetch_args), 0)
        cookie_header.assert_called_once_with(
            "exhentai", "https://api.e-hentai.org/api.php"
        )
        fetch.assert_called_once_with(
            "https://exhentai.org/g/987654/abcdef1234/",
            provider_hint="auto",
            config=default_config(),
            timeout=30,
            confirmed=True,
            cookie_header="ipb_member_id=member; ipb_pass_hash=secret",
        )
        self.assertNotIn("ipb_pass_hash", output.getvalue())

        hitomi_cookie_args = build_parser().parse_args(
            [
                "hitomi", "metadata", "fetch",
                "--input", "42", "--use-cookies", "--yes", "--json",
            ]
        )
        with (
            patch("toki_app.gui_is_running", return_value=False),
            patch("toki_app.settings_snapshot", return_value=default_config()),
            patch("toki_app.provider_cookie_request_header") as cookie_header,
            patch("toki_app.fetch_hitomi_metadata") as fetch,
            redirect_stdout(StringIO()) as output,
        ):
            self.assertEqual(run_cli(hitomi_cookie_args), 2)
        blocked = json.loads(output.getvalue())
        self.assertEqual(blocked["errorCode"], "hitomi.cookie_host_mismatch")
        cookie_header.assert_not_called()
        fetch.assert_not_called()

        show_args = build_parser().parse_args(
            [
                "hitomi",
                "metadata",
                "show",
                "--input",
                "42",
                "--json",
            ]
        )
        with (
            patch("toki_app.ensure_gui_running"),
            patch("toki_app.control_request", return_value={"shown": True}) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(show_args), 0)
        request.assert_called_once_with(
            {
                "action": "show_hitomi_metadata",
                "reference": "42",
                "provider": "auto",
                "fixture": "",
            }
        )

        close_args = build_parser().parse_args(
            ["hitomi", "metadata", "close", "--json"]
        )
        with (
            patch("toki_app.ensure_gui_running"),
            patch("toki_app.control_request", return_value={"closed": True}) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(close_args), 0)
        request.assert_called_once_with({"action": "close_hitomi_metadata"})

    def test_hitomi_cli_inspects_offline_and_controls_gui_dialog(self) -> None:
        inspect_args = build_parser().parse_args(
            [
                "hitomi",
                "inspect",
                "--input",
                "https://hitomi.la/manga/sample-1234567.html",
                "--json",
            ]
        )
        stdout = StringIO()
        with redirect_stdout(stdout):
            self.assertEqual(run_cli(inspect_args), 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["workKey"], "hitomi:1234567")
        self.assertFalse(payload["networkRequested"])

        invalid_args = build_parser().parse_args(
            ["hitomi", "inspect", "--input", "https://example.com/1", "--json"]
        )
        stdout = StringIO()
        with redirect_stdout(stdout):
            self.assertEqual(run_cli(invalid_args), 2)
        self.assertEqual(
            json.loads(stdout.getvalue())["errorCode"],
            "hitomi.unsupported_host",
        )

        show_args = build_parser().parse_args(
            [
                "hitomi",
                "inspect",
                "--input",
                "42",
                "--provider",
                "exhentai",
                "--show-gui",
                "--json",
            ]
        )
        with (
            patch("toki_app.ensure_gui_running"),
            patch(
                "toki_app.control_request",
                return_value={"shown": True, "result": {"workKey": "exhentai:42"}},
            ) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(show_args), 0)
        request.assert_called_once_with(
            {
                "action": "show_hitomi_inspector",
                "reference": "42",
                "provider": "exhentai",
            }
        )

        close_args = build_parser().parse_args(["hitomi", "close", "--json"])
        with (
            patch("toki_app.ensure_gui_running"),
            patch("toki_app.control_request", return_value={"closed": True}) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(close_args), 0)
        request.assert_called_once_with({"action": "close_hitomi_inspector"})

        status_args = build_parser().parse_args(["hitomi", "status", "--json"])
        with redirect_stdout(StringIO()) as stdout:
            self.assertEqual(run_cli(status_args), 0)
        self.assertFalse(json.loads(stdout.getvalue())["download"])

        server_status_args = build_parser().parse_args(
            ["hitomi", "server", "status", "--json"]
        )
        with (
            patch("toki_app.gui_is_running", return_value=False),
            patch("toki_app.settings_snapshot", return_value=default_config()),
            redirect_stdout(StringIO()) as stdout,
        ):
            self.assertEqual(run_cli(server_status_args), 0)
        self.assertEqual(json.loads(stdout.getvalue())["mode"], "auto")

        server_set_args = build_parser().parse_args(
            [
                "hitomi",
                "server",
                "set",
                "--mode",
                "manual",
                "--manual-server",
                "ehentai",
                "--priority",
                "ehentai,exhentai,hitomi",
                "--json",
            ]
        )
        saved = {
            **default_config(),
            "hitomiServerMode": "manual",
            "hitomiManualServer": "ehentai",
            "hitomiServerPriority": ["ehentai", "exhentai", "hitomi"],
        }
        with (
            patch("toki_app.gui_is_running", return_value=True),
            patch("toki_app.control_request", side_effect=[default_config(), saved]) as request,
            redirect_stdout(StringIO()) as stdout,
        ):
            self.assertEqual(run_cli(server_set_args), 0)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(
            request.call_args_list[1].args[0],
            {
                "action": "set_settings",
                "updates": {
                    "hitomiServerMode": "manual",
                    "hitomiManualServer": "ehentai",
                    "hitomiServerPriority": "ehentai,exhentai,hitomi",
                },
                "reset": False,
            },
        )
        self.assertEqual(json.loads(stdout.getvalue())["manualServer"], "ehentai")

        server_plan_args = build_parser().parse_args(
            [
                "hitomi",
                "server",
                "plan",
                "--input",
                "https://exhentai.org/g/987654/abcdef1234/",
                "--json",
            ]
        )
        with (
            patch("toki_app.gui_is_running", return_value=False),
            patch("toki_app.settings_snapshot", return_value=default_config()),
            redirect_stdout(StringIO()) as stdout,
        ):
            self.assertEqual(run_cli(server_plan_args), 0)
        self.assertEqual(json.loads(stdout.getvalue())["candidateServers"], ["exhentai", "ehentai"])

    def test_local_api_cli_controls_settings_token_and_loopback_request(self) -> None:
        status = {
            "ok": True,
            "enabled": True,
            "running": True,
            "host": "127.0.0.1",
            "baseUrl": "http://127.0.0.1:8765",
            "tokenHint": "…abcdef",
        }
        status_args = build_parser().parse_args(["local-api", "status", "--json"])
        with (
            patch("toki_app.gui_is_running", return_value=True),
            patch("toki_app.control_request", return_value=status) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(status_args), 0)
        request.assert_called_once_with({"action": "local_api_status"})

        set_args = build_parser().parse_args(
            ["local-api", "set", "--state", "on", "--port", "9123", "--json"]
        )
        with (
            patch("toki_app.gui_is_running", return_value=True),
            patch("toki_app.control_request", return_value=status) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(set_args), 0)
        self.assertEqual(
            request.call_args_list[0].args[0],
            {
                "action": "set_settings",
                "updates": {"localApiEnabled": True, "localApiPort": 9123},
                "reset": False,
            },
        )
        self.assertEqual(
            request.call_args_list[1].args[0], {"action": "local_api_status"}
        )

        token_args = build_parser().parse_args(
            ["local-api", "token", "--show", "--yes", "--json"]
        )
        with (
            patch("toki_app.ensure_gui_running"),
            patch(
                "toki_app.control_request",
                return_value={**status, "token": "secret-value"},
            ) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(token_args), 0)
        request.assert_called_once_with(
            {
                "action": "local_api_token",
                "reveal": True,
                "copy": False,
                "rotate": False,
                "confirmed": True,
            }
        )

        request_args = build_parser().parse_args(
            ["local-api", "request", "--path", "/v1/health", "--json"]
        )
        with (
            patch("toki_app.ensure_gui_running"),
            patch(
                "toki_app.control_request",
                side_effect=[status, {**status, "token": "secret-value"}],
            ) as ipc,
            patch(
                "toki_app.local_api_http_request",
                return_value={"ok": True, "statusCode": 200, "response": {"ok": True}},
            ) as http_request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(request_args), 0)
        self.assertEqual(ipc.call_count, 2)
        http_request.assert_called_once_with(
            "http://127.0.0.1:8765",
            "secret-value",
            method="GET",
            path="/v1/health",
            body="",
        )
        with self.assertRaises(ControlError):
            local_api_http_request("http://example.com:8765", "token")

    def test_memory_cli_reports_gui_process_tree_and_controls_display(self) -> None:
        snapshot = {
            "ok": True,
            "displayEnabled": True,
            "processId": 123,
            "application": {"combinedRssBytes": 400 * 1024**2},
            "system": {"percent": 55.0},
            "display": {"percent": 55, "severity": "normal"},
        }
        status_args = build_parser().parse_args(
            ["memory", "status", "--child-limit", "50", "--json"]
        )
        with (
            patch("toki_app.gui_is_running", return_value=True),
            patch("toki_app.control_request", return_value=snapshot) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(status_args), 0)
        request.assert_called_once_with(
            {"action": "memory_status", "childLimit": 50}
        )

        set_args = build_parser().parse_args(
            ["memory", "set", "--display", "off", "--json"]
        )
        with (
            patch("toki_app.gui_is_running", return_value=True),
            patch("toki_app.control_request", return_value=snapshot) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(set_args), 0)
        self.assertEqual(
            request.call_args_list[0].args[0],
            {
                "action": "set_settings",
                "updates": {"memoryDisplayEnabled": False},
                "reset": False,
            },
        )
        self.assertEqual(
            request.call_args_list[1].args[0],
            {"action": "memory_status", "childLimit": 200},
        )

    def test_sleep_prevention_cli_reports_sets_and_plans_without_power_call(self) -> None:
        status = {
            "ok": True,
            "configured": True,
            "activeDownloads": 1,
            "requested": True,
            "active": True,
        }
        status_args = build_parser().parse_args(
            ["sleep-prevention", "status", "--json"]
        )
        with (
            patch("toki_app.gui_is_running", return_value=True),
            patch("toki_app.control_request", return_value=status) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(status_args), 0)
        request.assert_called_once_with({"action": "sleep_prevention_status"})

        set_args = build_parser().parse_args(
            ["sleep-prevention", "set", "--state", "on", "--json"]
        )
        with (
            patch("toki_app.gui_is_running", return_value=True),
            patch("toki_app.control_request", return_value=status) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(set_args), 0)
        self.assertEqual(
            request.call_args_list[0].args[0],
            {
                "action": "set_settings",
                "updates": {"preventSleepDuringDownloads": True},
                "reset": False,
            },
        )
        self.assertEqual(
            request.call_args_list[1].args[0],
            {"action": "sleep_prevention_status"},
        )

        plan_args = build_parser().parse_args(
            ["sleep-prevention", "plan", "--active-downloads", "2", "--json"]
        )
        with (
            patch(
                "toki_app.sleep_prevention_policy_snapshot",
                return_value={"ok": True, "requested": False},
            ) as planner,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(plan_args), 0)
        planner.assert_called_once_with(active_downloads=2)

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
            with self.assertRaisesRegex(toki_app.ControlError, "--yes"):
                run_cli(plan)
            plan = build_parser().parse_args(
                [
                    "cookies", "plan-import", "--provider", "manatoki",
                    "--input", str(source), "--yes", "--json",
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

        policy = build_parser().parse_args(
            ["cookies", "policy", "--provider", "exhentai", "--json"]
        )
        with redirect_stdout(StringIO()) as output:
            self.assertEqual(run_cli(policy), 0)
        payload = json.loads(output.getvalue())
        self.assertTrue(payload["authenticationRequired"])
        self.assertFalse(payload["accessRestrictionBypassSupported"])
        self.assertFalse(payload["valuesExposed"])

        hitomi_manage = build_parser().parse_args(
            ["cookies", "manage", "--provider", "exhentai", "--show-gui", "--json"]
        )
        with (
            patch("toki_app.ensure_gui_running"),
            patch("toki_app.control_request", return_value={"shown": True}) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(hitomi_manage), 0)
        request.assert_called_once_with(
            {"action": "show_cookie_manager", "provider": "exhentai"}
        )

    def test_youtube_format_cli_uses_shared_offline_policy(self) -> None:
        status = build_parser().parse_args(["youtube", "format", "status", "--json"])
        with (
            patch("toki_app.gui_is_running", return_value=False),
            patch("toki_app.settings_snapshot", return_value=default_config()),
            redirect_stdout(StringIO()) as output,
        ):
            self.assertEqual(run_cli(status), 0)
        self.assertFalse(json.loads(output.getvalue())["networkRequested"])

        plan = build_parser().parse_args(
            [
                "youtube", "format", "plan",
                "--input", "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "--max-height", "1080", "--container", "mp4",
                "--video-codec", "h264", "--audio-codec", "aac", "--json",
            ]
        )
        with (
            patch("toki_app.gui_is_running", return_value=False),
            patch("toki_app.settings_snapshot", return_value=default_config()),
            redirect_stdout(StringIO()) as output,
        ):
            self.assertEqual(run_cli(plan), 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["formatSelector"], "bv*[height<=?1080]+ba/b[height<=?1080]")
        self.assertFalse(payload["downloadExecuted"])

        set_args = build_parser().parse_args(
            ["youtube", "format", "set", "--mode", "audio_only", "--json"]
        )
        with (
            patch("toki_app.gui_is_running", return_value=False),
            patch("toki_app.update_app_settings", return_value={**default_config(), "youtubeFormatMode": "audio_only"}) as update,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(set_args), 0)
        update.assert_called_once_with({"youtubeFormatMode": "audio_only"})

        filename = build_parser().parse_args(
            [
                "youtube", "filename", "preview",
                "--template", "%(upload_date)s - %(title)s [%(id)s].%(ext)s", "--json",
            ]
        )
        with (
            patch("toki_app.gui_is_running", return_value=False),
            patch("toki_app.settings_snapshot", return_value=default_config()),
            redirect_stdout(StringIO()) as output,
        ):
            self.assertEqual(run_cli(filename), 0)
        self.assertEqual(
            json.loads(output.getvalue())["preview"],
            "20260807 - 영상 제목 [dQw4w9WgXcQ].mp4",
        )

        tracks = build_parser().parse_args(
            [
                "youtube", "tracks", "plan", "--input",
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "--languages", "ko,en,ja", "--subtitles", "manual_auto",
                "--subtitle-format", "srt", "--embed-subtitles", "on",
                "--audio-tracks", "all", "--json",
            ]
        )
        with (
            patch("toki_app.gui_is_running", return_value=False),
            patch("toki_app.settings_snapshot", return_value=default_config()),
            redirect_stdout(StringIO()) as output,
        ):
            self.assertEqual(run_cli(tracks), 0)
        payload = json.loads(output.getvalue())
        self.assertIn("--audio-multistreams", payload["arguments"])
        self.assertIn("--embed-subs", payload["arguments"])
        self.assertFalse(payload["downloadExecuted"])

        metadata = build_parser().parse_args(
            [
                "youtube", "metadata", "plan", "--input",
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "--write-thumbnail", "on", "--embed-thumbnail", "on",
                "--write-info-json", "on", "--write-description", "on",
                "--embed-metadata", "on", "--json",
            ]
        )
        with (
            patch("toki_app.gui_is_running", return_value=False),
            patch("toki_app.settings_snapshot", return_value=default_config()),
            redirect_stdout(StringIO()) as output,
        ):
            self.assertEqual(run_cli(metadata), 0)
        payload = json.loads(output.getvalue())
        self.assertIn("--write-info-json", payload["arguments"])
        self.assertIn("--embed-thumbnail", payload["arguments"])
        self.assertIn("--no-embed-chapters", payload["arguments"])
        self.assertFalse(payload["downloadExecuted"])

        metadata_set = build_parser().parse_args(
            ["youtube", "metadata", "set", "--write-thumbnail", "on", "--json"]
        )
        expected = {**default_config(), "youtubeWriteThumbnail": True}
        with (
            patch("toki_app.gui_is_running", return_value=False),
            patch("toki_app.update_app_settings", return_value=expected) as update,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(metadata_set), 0)
        update.assert_called_once_with({"youtubeWriteThumbnail": True})

        collection = build_parser().parse_args(
            [
                "youtube", "collection", "plan", "--input",
                "https://www.youtube.com/@OpenAI/videos",
                "--order", "reverse", "--json",
            ]
        )
        with (
            patch("toki_app.gui_is_running", return_value=False),
            patch("toki_app.settings_snapshot", return_value=default_config()),
            redirect_stdout(StringIO()) as output,
        ):
            self.assertEqual(run_cli(collection), 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["reference"]["channelScope"], "videos")
        self.assertIn("--playlist-items", payload["arguments"])
        self.assertIn("::-1", payload["arguments"])
        self.assertTrue(payload["fullCollectionScanRequired"])

        collection_set = build_parser().parse_args(
            ["youtube", "collection", "set", "--order", "reverse", "--json"]
        )
        expected = {**default_config(), "youtubeCollectionOrder": "reverse"}
        with (
            patch("toki_app.gui_is_running", return_value=False),
            patch("toki_app.update_app_settings", return_value=expected) as update,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(collection_set), 0)
        update.assert_called_once_with({"youtubeCollectionOrder": "reverse"})

        chapters = build_parser().parse_args(
            [
                "youtube", "chapters", "plan", "--input",
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "--embed", "on", "--json",
            ]
        )
        with (
            patch("toki_app.gui_is_running", return_value=False),
            patch("toki_app.settings_snapshot", return_value=default_config()),
            redirect_stdout(StringIO()) as output,
        ):
            self.assertEqual(run_cli(chapters), 0)
        payload = json.loads(output.getvalue())
        self.assertIn("--embed-chapters", payload["arguments"])
        self.assertTrue(payload["postProcessingRequired"])

        chapters_set = build_parser().parse_args(
            ["youtube", "chapters", "set", "--embed", "on", "--json"]
        )
        expected = {**default_config(), "youtubeEmbedChapters": True}
        with (
            patch("toki_app.gui_is_running", return_value=False),
            patch("toki_app.update_app_settings", return_value=expected) as update,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(chapters_set), 0)
        update.assert_called_once_with({"youtubeEmbedChapters": True})

        mtime_plan = build_parser().parse_args(
            [
                "youtube", "mtime", "plan", "--file", "C:\\Temp\\video.mp4",
                "--upload-date", "20260807", "--state", "on", "--json",
            ]
        )
        with (
            patch("toki_app.gui_is_running", return_value=False),
            patch("toki_app.settings_snapshot", return_value=default_config()),
            redirect_stdout(StringIO()) as output,
        ):
            self.assertEqual(run_cli(mtime_plan), 0)
        payload = json.loads(output.getvalue())
        self.assertTrue(payload["wouldModifyFileTimestamp"])
        self.assertFalse(payload["executed"])

        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "video.mp4"
            target.write_bytes(b"test")
            mtime_apply = build_parser().parse_args(
                [
                    "youtube", "mtime", "apply", "--file", str(target),
                    "--upload-date", "20260807", "--state", "on", "--yes", "--json",
                ]
            )
            with (
                patch("toki_app.gui_is_running", return_value=False),
                patch("toki_app.settings_snapshot", return_value=default_config()),
                redirect_stdout(StringIO()) as output,
            ):
                self.assertEqual(run_cli(mtime_apply), 0)
            self.assertTrue(json.loads(output.getvalue())["executed"])

        mtime_set = build_parser().parse_args(
            ["youtube", "mtime", "set", "--state", "on", "--json"]
        )
        expected = {**default_config(), "youtubeApplyUploadDateMtime": True}
        with (
            patch("toki_app.gui_is_running", return_value=False),
            patch("toki_app.update_app_settings", return_value=expected) as update,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(mtime_set), 0)
        update.assert_called_once_with({"youtubeApplyUploadDateMtime": True})

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
        lookup.assert_called_once_with(confirmed=True)

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

    def test_archive_viewer_cli_reports_sets_and_requires_confirmed_execution(self) -> None:
        policy = {
            "mode": "system",
            "viewerPath": "",
            "available": True,
            "changesSystemAssociation": False,
        }
        status_args = build_parser().parse_args(
            ["archive-viewer", "status", "--json"]
        )
        with (
            patch("toki_app.gui_is_running", return_value=True),
            patch("toki_app.control_request", return_value=policy) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(status_args), 0)
        request.assert_called_once_with({"action": "archive_viewer_policy"})

        set_args = build_parser().parse_args(
            [
                "archive-viewer",
                "set",
                "--mode",
                "custom",
                "--path",
                "viewer.exe",
                "--json",
            ]
        )
        custom_policy = {**policy, "mode": "custom", "viewerPath": "viewer.exe"}
        with (
            patch("toki_app.gui_is_running", return_value=False),
            patch(
                "toki_app.update_app_settings",
                return_value={"archiveViewerMode": "custom", "archiveViewerPath": "viewer.exe"},
            ) as update,
            patch(
                "toki_app.archive_viewer_policy_snapshot", return_value=custom_policy
            ),
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(set_args), 0)
        update.assert_called_once_with(
            {"archiveViewerMode": "custom", "archiveViewerPath": "viewer.exe"}
        )

        preview_args = build_parser().parse_args(
            ["archive-viewer", "open", "--path", "work.cbz", "--json"]
        )
        preview = {
            "ok": True,
            "executed": False,
            "viewerLabel": "Windows 기본 연결 프로그램",
            "path": "work.cbz",
        }
        with (
            patch("toki_app.open_archive_with_viewer", return_value=preview) as open_viewer,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(preview_args), 0)
        open_viewer.assert_called_once_with(Path("work.cbz"), execute=False)

        unconfirmed = build_parser().parse_args(
            ["archive-viewer", "open", "--path", "work.cbz", "--execute"]
        )
        with self.assertRaisesRegex(ValueError, "--execute --yes"):
            run_cli(unconfirmed)

        execute_args = build_parser().parse_args(
            [
                "archive-viewer",
                "open",
                "--path",
                "work.cbz",
                "--execute",
                "--yes",
                "--json",
            ]
        )
        executed = {**preview, "executed": True}
        with (
            patch("toki_app.open_archive_with_viewer", return_value=executed) as open_viewer,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(execute_args), 0)
        open_viewer.assert_called_once_with(Path("work.cbz"), execute=True)

    def test_persistence_cli_reports_sets_previews_and_confirms_recovery(self) -> None:
        policy = {
            "autosaveIntervalSeconds": 1,
            "startupRecoveryEnabled": True,
        }
        recovery = {
            "ok": True,
            "executed": False,
            "jobCount": 1,
            "runCount": 1,
            "jobIds": ["stale"],
            "runIds": ["stale-run"],
        }
        status_args = build_parser().parse_args(
            ["persistence", "status", "--json"]
        )
        with (
            patch("toki_app.gui_is_running", return_value=False),
            patch("toki_app.persistence_policy_snapshot", return_value=policy),
            patch("toki_app.recover_interrupted_jobs", return_value=recovery) as recover,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(status_args), 0)
        recover.assert_called_once_with(execute=False)

        set_args = build_parser().parse_args(
            [
                "persistence",
                "set",
                "--autosave-seconds",
                "9",
                "--startup-recovery",
                "off",
                "--json",
            ]
        )
        with (
            patch("toki_app.gui_is_running", return_value=True),
            patch(
                "toki_app.control_request",
                side_effect=[
                    {"autosaveIntervalSeconds": 9},
                    {"ok": True, "policy": policy, "recovery": recovery},
                ],
            ) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(set_args), 0)
        self.assertEqual(
            request.call_args_list[0].args[0],
            {
                "action": "set_settings",
                "updates": {
                    "autosaveIntervalSeconds": 9,
                    "recoverInterruptedOnStartup": False,
                },
                "reset": False,
            },
        )
        self.assertEqual(
            request.call_args_list[1].args[0], {"action": "persistence_status"}
        )

        preview_args = build_parser().parse_args(
            ["persistence", "recover", "--json"]
        )
        with (
            patch("toki_app.gui_is_running", return_value=False),
            patch("toki_app.recover_interrupted_jobs", return_value=recovery) as recover,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(preview_args), 0)
        recover.assert_called_once_with(execute=False)

        unconfirmed = build_parser().parse_args(
            ["persistence", "recover", "--execute"]
        )
        with self.assertRaisesRegex(ValueError, "--execute --yes"):
            run_cli(unconfirmed)

        execute_args = build_parser().parse_args(
            ["persistence", "recover", "--execute", "--yes", "--json"]
        )
        executed = {**recovery, "executed": True}
        with (
            patch("toki_app.gui_is_running", return_value=False),
            patch(
                "toki_app.recover_interrupted_jobs", return_value=executed
            ) as recover,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(execute_args), 0)
        recover.assert_called_once_with(execute=True)

        show_args = build_parser().parse_args(
            ["persistence", "recover", "--show-gui"]
        )
        with (
            patch("toki_app.ensure_gui_running"),
            patch("toki_app.control_request", return_value={"shown": True}) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(show_args), 0)
        request.assert_called_once_with({"action": "show_recovery_dialog"})

    def test_list_performance_cli_reports_and_updates_live_policy(self) -> None:
        policy = {
            "ok": True,
            "configured": {
                "pageSize": 100,
                "loadedLimit": 500,
                "scrollLines": 2,
                "lazyLoading": True,
                "lowSpecMode": True,
            },
            "effective": {"pageSize": 100, "loadedLimit": 500},
        }
        status_args = build_parser().parse_args(
            ["list-performance", "status", "--json"]
        )
        with (
            patch("toki_app.gui_is_running", return_value=True),
            patch("toki_app.control_request", return_value=policy) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(status_args), 0)
        request.assert_called_once_with({"action": "list_performance_status"})

        set_args = build_parser().parse_args(
            [
                "list-performance",
                "set",
                "--page-size",
                "100",
                "--loaded-limit",
                "500",
                "--scroll-lines",
                "2",
                "--lazy-loading",
                "on",
                "--low-spec",
                "on",
                "--json",
            ]
        )
        with (
            patch("toki_app.gui_is_running", return_value=True),
            patch(
                "toki_app.control_request",
                side_effect=[{"ok": True}, policy],
            ) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(set_args), 0)
        self.assertEqual(
            request.call_args_list[0].args[0],
            {
                "action": "set_settings",
                "updates": {
                    "listPageSize": 100,
                    "listLoadedLimit": 500,
                    "listScrollLines": 2,
                    "listLazyLoading": True,
                    "lowSpecMode": True,
                },
                "reset": False,
            },
        )
        self.assertEqual(
            request.call_args_list[1].args[0],
            {"action": "list_performance_status"},
        )

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

    def test_job_menu_cli_can_show_or_inspect_grouped_menu(self) -> None:
        show = build_parser().parse_args(["job-menu", "--job", "work-1"])
        inspect = build_parser().parse_args(
            ["job-menu", "--job", "work-1", "--inspect"]
        )
        with (
            patch(
                "toki_app.control_request",
                side_effect=[
                    {"shown": True},
                    {
                        "jobId": "work-1",
                        "rootItems": ["작품 정보 및 실행 이력", "복사"],
                    },
                ],
            ) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(show), 0)
            self.assertEqual(run_cli(inspect), 0)
        self.assertEqual(
            [call.args[0] for call in request.call_args_list],
            [
                {"action": "show_job_menu", "jobId": "work-1"},
                {"action": "inspect_job_menu", "jobId": "work-1"},
            ],
        )

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

    def test_youtube_download_requires_confirmation_or_offline_simulation(self) -> None:
        live = build_parser().parse_args(
            ["download", "--url", "https://www.youtube.com/watch?v=video-one"]
        )
        with (
            patch("toki_app.ensure_gui_running") as ensure_gui,
            self.assertRaisesRegex(ValueError, "--confirm-external"),
        ):
            run_cli(live)
        ensure_gui.assert_not_called()

        simulated = build_parser().parse_args(
            [
                "download",
                "--url",
                "https://www.youtube.com/watch?v=video-one",
                "--simulate",
            ]
        )
        with (
            patch("toki_app.ensure_gui_running"),
            patch("toki_app.load_config", return_value={"outputDir": r"C:\Video"}),
            patch(
                "toki_app.control_request",
                return_value={"job_id": "youtube-sim"},
            ) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(simulated), 0)
        payload = request.call_args.args[0]
        self.assertTrue(payload["simulation"])
        self.assertFalse(payload["externalRequestConfirmed"])
        self.assertEqual(payload["scanMode"], "new")

    def test_direct_youtube_simulation_launches_python_worker_not_node(self) -> None:
        args = build_parser().parse_args(
            [
                "download",
                "--direct",
                "--simulate",
                "--url",
                "https://www.youtube.com/watch?v=video-one",
            ]
        )
        completed = type("Completed", (), {"returncode": 0})()
        with (
            patch("toki_app.load_config", return_value=default_config()),
            patch("toki_app.find_node") as find_node,
            patch("toki_app.subprocess.run", return_value=completed) as runner,
            patch("toki_app.append_log"),
        ):
            self.assertEqual(run_direct_download(args), 0)
        find_node.assert_not_called()
        command = runner.call_args.args[0]
        self.assertEqual(command[0], sys.executable)
        self.assertTrue(str(command[1]).endswith("youtube_worker.py"))
        self.assertIn("--simulate", command)

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

        close_gui = build_parser().parse_args(["verify-files", "--close"])
        with (
            patch("toki_app.ensure_gui_running"),
            patch(
                "toki_app.control_request", return_value={"closed": True}
            ) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(close_gui), 0)
        request.assert_called_once_with({"action": "close_file_verification"})

        missing_job = build_parser().parse_args(["verify-files", "--json"])
        with self.assertRaisesRegex(ControlError, "--job"):
            run_cli(missing_job)

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

        for option, field, value in (
            ("--episode-id", "episodeId", "source-b"),
            ("--episode-folder", "episodeFolder", "작품 140-2화"),
        ):
            args = build_parser().parse_args([
                "preview", "--job", "job-1", option, value, "--show-gui",
            ])
            with (
                patch("toki_app.ensure_gui_running"),
                patch("toki_app.control_request", return_value={"started": True}) as request,
                redirect_stdout(StringIO()),
            ):
                self.assertEqual(run_cli(args), 0)
            request.assert_called_once_with({
                "action": "preview_images", "jobId": "job-1", "episode": None, field: value,
            })

        close_gui = build_parser().parse_args(["preview", "--close"])
        with (
            patch("toki_app.ensure_gui_running"),
            patch(
                "toki_app.control_request", return_value={"closed": True}
            ) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(close_gui), 0)
        request.assert_called_once_with({"action": "close_image_preview"})

        missing_job = build_parser().parse_args(["preview", "--json"])
        with self.assertRaisesRegex(ControlError, "--job"):
            run_cli(missing_job)

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
            patch(
                "toki_app.image_processing_policy_snapshot",
                return_value={
                    "maxWidth": 0,
                    "maxHeight": 0,
                    "excludedExtensions": [],
                },
            ),
            patch("toki_app.plan_image_conversion", return_value=result) as plan,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(args), 0)
        plan.assert_called_once_with(
            "job-1",
            "webp",
            quality=90,
            max_width=0,
            max_height=0,
            excluded_extensions=[],
        )

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
                "--quality", "80", "--max-width", "1600",
                "--max-height", "2400", "--exclude-ext", "gif,bmp",
                "--show-gui",
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
                "maxWidth": 1600,
                "maxHeight": 2400,
                "excludedExtensions": ["gif", "bmp"],
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
            patch(
                "toki_app.image_processing_policy_snapshot",
                return_value={
                    "maxWidth": 0,
                    "maxHeight": 0,
                    "excludedExtensions": [],
                },
            ),
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

        close = build_parser().parse_args(["convert-images", "--close"])
        with (
            patch("toki_app.ensure_gui_running"),
            patch(
                "toki_app.control_request", return_value={"closed": True}
            ) as close_request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(close), 0)
        close_request.assert_called_once_with({"action": "close_image_conversion"})

        missing = build_parser().parse_args(["convert-images", "--job", "job-1"])
        with self.assertRaisesRegex(toki_app.ControlError, "--job과 --format"):
            run_cli(missing)

    def test_pdf_cli_covers_policy_plan_confirm_progress_gui_cancel_and_close(self) -> None:
        policy = {
            "automatic": False,
            "scope": "per_episode",
            "dependency": {"available": True},
        }
        status = build_parser().parse_args(["pdf", "status", "--json"])
        with (
            patch("toki_app.gui_is_running", return_value=False),
            patch("toki_app.pdf_generation_policy_snapshot", return_value=policy),
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(status), 0)

        set_args = build_parser().parse_args(
            ["pdf", "set", "--automatic", "on", "--json"]
        )
        with (
            patch("toki_app.gui_is_running", return_value=True),
            patch("toki_app.control_request", return_value={**policy, "automatic": True}) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(set_args), 0)
        self.assertEqual(
            request.call_args_list[0].args[0],
            {
                "action": "set_settings",
                "updates": {"pdfGenerationEnabled": True},
                "reset": False,
            },
        )
        self.assertEqual(request.call_args_list[1].args[0], {"action": "pdf_status"})

        plan_result = {
            "jobId": "job-1",
            "targetRoot": r"C:\Manga\작품\_pdf",
            "episodeCount": 2,
            "sourceCount": 10,
            "pendingCount": 2,
            "preservesOriginals": True,
        }
        plan_args = build_parser().parse_args(
            ["pdf", "plan", "--job", "job-1", "--json"]
        )
        with (
            patch("toki_app.plan_job_pdf_generation", return_value=plan_result) as planner,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(plan_args), 0)
        planner.assert_called_once_with("job-1")

        unsafe = build_parser().parse_args(
            ["pdf", "generate", "--job", "job-1", "--execute"]
        )
        with self.assertRaisesRegex(RuntimeError, "--execute --yes"):
            run_cli(unsafe)

        gui_args = build_parser().parse_args(
            ["pdf", "generate", "--job", "job-1", "--show-gui"]
        )
        with (
            patch("toki_app.ensure_gui_running"),
            patch("toki_app.control_request", return_value={"started": True}) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(gui_args), 0)
        request.assert_called_once_with(
            {"action": "generate_pdf", "jobId": "job-1", "execute": False}
        )

        progress_args = build_parser().parse_args(
            [
                "pdf", "generate", "--job", "job-1", "--execute", "--yes",
                "--progress-json",
            ]
        )
        executed = {
            **plan_result,
            "executed": True,
            "success": True,
            "generatedCount": 2,
        }

        def generate_with_progress(_job_id, *, progress_callback=None):
            progress_callback(
                {"current": 1, "total": 2, "status": "generated"}
            )
            return executed

        output = StringIO()
        with (
            patch("toki_app.generate_job_pdfs", side_effect=generate_with_progress),
            redirect_stdout(output),
        ):
            self.assertEqual(run_cli(progress_args), 0)
        events = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([event["event"] for event in events], ["progress", "result"])

        cancel = build_parser().parse_args(
            ["pdf", "cancel", "--job", "job-1", "--json"]
        )
        close = build_parser().parse_args(["pdf", "close", "--json"])
        with (
            patch("toki_app.ensure_gui_running"),
            patch("toki_app.control_request", return_value={"cancelled": True}) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(cancel), 0)
        request.assert_called_once_with(
            {"action": "cancel_pdf_generation", "jobId": "job-1"}
        )
        with (
            patch("toki_app.ensure_gui_running"),
            patch("toki_app.control_request", return_value={"closed": True}) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(close), 0)
        request.assert_called_once_with({"action": "close_pdf_generation"})

    def test_image_processing_policy_cli_reports_and_updates_gui(self) -> None:
        status = build_parser().parse_args(
            ["image-processing", "status", "--json"]
        )
        with (
            patch("toki_app.gui_is_running", return_value=True),
            patch(
                "toki_app.control_request",
                return_value={"maxWidth": 0, "maxHeight": 0},
            ) as status_request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(status), 0)
        status_request.assert_called_once_with({"action": "image_processing_policy"})

        update = build_parser().parse_args(
            [
                "image-processing", "set", "--max-width", "1600",
                "--max-height", "2400", "--exclude", "gif; bmp", "--json",
            ]
        )
        saved = default_config()
        saved.update(
            {
                "imageResizeMaxWidth": 1600,
                "imageResizeMaxHeight": 2400,
                "imageExcludedExtensions": [".gif", ".bmp"],
            }
        )
        with (
            patch("toki_app.gui_is_running", return_value=True),
            patch("toki_app.control_request", return_value=saved) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(update), 0)
        request.assert_called_once_with(
            {
                "action": "set_settings",
                "updates": {
                    "imageResizeMaxWidth": 1600,
                    "imageResizeMaxHeight": 2400,
                    "imageExcludedExtensions": ["gif", "bmp"],
                },
                "reset": False,
            }
        )

        empty = build_parser().parse_args(["image-processing", "set"])
        with self.assertRaisesRegex(toki_app.ControlError, "하나 이상"):
            run_cli(empty)

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
