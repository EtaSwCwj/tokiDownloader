from __future__ import annotations

import tempfile
import json
import importlib.util
import os
import sqlite3
import time
import unicodedata
import unittest
import zipfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import toki_core
from toki_core import (
    archive_viewer_policy_snapshot,
    append_bounded_text,
    available_ui_languages,
    available_work_slots,
    DownloadJob,
    DownloadRun,
    SleepPreventionController,
    build_downloader_args,
    build_job_list_view_state,
    build_work_key,
    browser_launch_policy,
    cleanup_thumbnail_cache,
    cleanup_run_history,
    completion_action_plan,
    cookie_import_plan,
    assess_provider_cookies,
    clear_provider_cookies,
    clear_proxy_credentials,
    create_work_collection,
    count_jobs,
    count_runs,
    dependency_diagnostics,
    discover_episode_folders,
    convert_job_images,
    default_config,
    delete_job_record,
    delete_job_records,
    downloader_event_update_policy,
    downloader_environment_overrides,
    embedded_browser_capabilities,
    embedded_browser_navigation_plan,
    export_diagnostics,
    export_jobs_snapshot,
    export_provider_cookies,
    export_shortcut_settings,
    find_duplicate_works,
    find_duplicate_images,
    folder_name_template_preview,
    generate_job_pdfs,
    hydrate_job_metadata,
    image_processing_policy_snapshot,
    import_jobs_snapshot,
    import_provider_cookies,
    inspect_local_archive,
    inspect_clipboard_url,
    load_ui_strings,
    list_work_collections,
    job_database_diagnostics,
    keyboard_shortcut_catalog,
    keyboard_shortcut_keys,
    menu_action_availability,
    load_job_by_work_key,
    load_jobs_page,
    list_job_episode_images,
    list_performance_policy_snapshot,
    local_api_policy_snapshot,
    local_api_request_plan,
    generate_local_api_token,
    memory_usage_snapshot,
    load_run,
    load_episode_state_manifest,
    load_runs_page,
    mark_job_cancelled,
    mark_run_cancelled,
    normalize_range,
    normalize_image_concurrency,
    normalize_scan_mode,
    normalize_scan_request,
    normalize_retry_backoff,
    normalize_retry_count,
    normalize_error_category,
    normalize_embedded_browser_url,
    normalize_notification_sound,
    normalize_folder_name_template,
    normalize_shortcut_overrides,
    normalize_background_image,
    open_archive_with_viewer,
    plan_archive_viewer_open,
    persistence_policy_snapshot,
    normalize_font_family,
    normalize_proxy_url,
    normalize_provider_policies,
    normalize_speed_limit_kib,
    normalize_ui_language,
    normalize_ui_scale,
    normalize_config,
    normalize_work_concurrency,
    move_job_folder,
    network_policy_snapshot,
    notification_event_plan,
    notification_settings_snapshot,
    plan_job_folder_move,
    plan_image_conversion,
    plan_job_pdf_generation,
    plan_metadata_rebuild,
    plan_window_geometry,
    public_ip_check_plan,
    pdf_generation_policy_snapshot,
    lookup_public_ip,
    provider_cookie_status,
    provider_cookie_policy,
    provider_cookie_request_header,
    proxy_credential_status,
    read_run_log,
    rebuild_job_metadata,
    rename_work_collection,
    recover_interrupted_jobs,
    render_folder_name_template,
    retry_backoff_seconds,
    resolve_cover_path,
    reorder_pending_jobs,
    resource_admission,
    resource_budget,
    ROOT_DIR,
    run_job_database_benchmark,
    run_stability_recovery_test,
    save_jobs,
    save_runs,
    assign_job_to_collection,
    set_job_pause_state,
    set_process_tree_paused,
    should_auto_retry,
    settings_snapshot,
    shortcut_import_plan,
    shortcut_settings_snapshot,
    sleep_prevention_policy_snapshot,
    store_proxy_credentials,
    thumbnail_cache_path,
    update_app_settings,
    update_job_note,
    verify_job_files,
    update_job_markers,
    work_collection_for_job,
)


class CoreContractTests(unittest.TestCase):
    def test_application_identity_has_unique_assets_and_windows_app_id(self) -> None:
        configured = toki_core.application_identity_snapshot()
        runtime_before_probes = {
            key: configured[key] for key in ("attempted", "applied", "error")
        }
        self.assertTrue(configured["ok"])
        self.assertEqual(configured["displayName"], "tokiDownloader")
        self.assertEqual(
            configured["windowsAppUserModelId"], "EtaSwCwj.tokiDownloader.GUI.1"
        )
        self.assertTrue(configured["iconExists"])
        self.assertTrue(configured["executableIconExists"])
        self.assertEqual(Path(configured["iconPath"]).suffix, ".png")
        self.assertEqual(Path(configured["executableIconPath"]).suffix, ".ico")
        self.assertTrue(
            Path(configured["iconPath"])
            .read_bytes()
            .startswith(b"\x89PNG\r\n\x1a\n")
        )
        ico_header = Path(configured["executableIconPath"]).read_bytes()[:6]
        self.assertEqual(ico_header[:4], b"\x00\x00\x01\x00")
        self.assertGreaterEqual(int.from_bytes(ico_header[4:6], "little"), 7)
        from scripts.generate_app_icons import SVG_CONTENT, SVG_PATH

        self.assertEqual(SVG_PATH.read_text(encoding="utf-8"), SVG_CONTENT)
        self.assertIn("Generated by scripts/generate_app_icons.py", SVG_CONTENT)

        calls: list[str] = []
        applied = toki_core.apply_windows_app_user_model_id(
            platform_name="nt",
            setter=lambda value: calls.append(value) or 0,
        )
        self.assertEqual(calls, ["EtaSwCwj.tokiDownloader.GUI.1"])
        self.assertTrue(applied["applied"])
        self.assertEqual(applied["error"], "")

        failed = toki_core.apply_windows_app_user_model_id(
            platform_name="nt", setter=lambda _value: 1
        )
        self.assertFalse(failed["applied"])
        self.assertIn("HRESULT", failed["error"])
        unsupported = toki_core.apply_windows_app_user_model_id(
            platform_name="posix"
        )
        self.assertFalse(unsupported["attempted"])
        self.assertFalse(unsupported["applied"])
        runtime_after_probes = toki_core.application_identity_snapshot()
        self.assertEqual(
            {key: runtime_after_probes[key] for key in runtime_before_probes},
            runtime_before_probes,
        )

    def test_local_api_is_loopback_token_authenticated_and_action_limited(self) -> None:
        config = default_config()
        self.assertFalse(config["localApiEnabled"])
        self.assertEqual(config["localApiPort"], 8765)
        with patch("toki_core.secrets.token_urlsafe", return_value="temporary-token"):
            token = generate_local_api_token()
        self.assertEqual(token, "temporary-token")
        policy = local_api_policy_snapshot(
            config,
            running=True,
            current_port=9123,
            token=token,
        )
        self.assertEqual(policy["host"], "127.0.0.1")
        self.assertEqual(policy["baseUrl"], "http://127.0.0.1:9123")
        self.assertFalse(policy["publicBindingAllowed"])
        self.assertFalse(policy["corsEnabled"])
        self.assertFalse(policy["tokenPersistent"])
        self.assertNotIn(token, json.dumps(policy, ensure_ascii=False))

        unauthorized = local_api_request_plan(
            "GET", "/v1/health", {}, b"", token
        )
        self.assertEqual(unauthorized["statusCode"], 401)
        headers = {"Authorization": f"Bearer {token}"}
        health = local_api_request_plan(
            "GET", "/v1/health", headers, b"", token
        )
        self.assertEqual(health["route"], "health")
        jobs = local_api_request_plan(
            "GET", "/v1/jobs?limit=25&offset=50&query=test", headers, b"", token
        )
        self.assertEqual(
            jobs["request"],
            {
                "action": "list_jobs",
                "query": "test",
                "status": "",
                "sort": "updated",
                "limit": 25,
                "offset": 50,
            },
        )
        allowed = local_api_request_plan(
            "POST",
            "/v1/control",
            {**headers, "Content-Type": "application/json"},
            b'{"action":"pause","jobId":"job-1"}',
            token,
        )
        self.assertEqual(allowed["request"]["action"], "pause")
        forbidden = local_api_request_plan(
            "POST",
            "/v1/control",
            {**headers, "Content-Type": "application/json"},
            b'{"action":"remove_record","jobId":"job-1"}',
            token,
        )
        self.assertEqual(forbidden["statusCode"], 403)
        with self.assertRaises(ValueError):
            update_app_settings({"localApiPort": 80})

    def test_memory_usage_snapshot_separates_app_children_and_system_pressure(self) -> None:
        gib = 1024**3

        class MemoryInfo:
            def __init__(self, rss: int) -> None:
                self.rss = rss

        class Process:
            def __init__(self, pid: int, parent: int, name: str, rss: int) -> None:
                self.pid = pid
                self._parent = parent
                self._name = name
                self._rss = rss
                self._children: list[Process] = []

            def memory_info(self) -> MemoryInfo:
                return MemoryInfo(self._rss)

            def children(self, recursive: bool = False) -> list[Process]:
                self.assert_recursive = recursive
                return list(self._children)

            def ppid(self) -> int:
                return self._parent

            def name(self) -> str:
                return self._name

            def status(self) -> str:
                return "running"

        root = Process(100, 1, "pythonw.exe", 300 * 1024**2)
        root._children = [
            Process(102, 100, "chrome.exe", 700 * 1024**2),
            Process(101, 100, "node.exe", 500 * 1024**2),
        ]
        virtual = type("Virtual", (), {"total": 16 * gib, "available": 2 * gib})()
        config = default_config()
        self.assertTrue(config["memoryDisplayEnabled"])

        with (
            patch("toki_core.psutil.Process", return_value=root),
            patch("toki_core.psutil.virtual_memory", return_value=virtual),
        ):
            snapshot = memory_usage_snapshot(config, process_id=100, child_limit=1)

        self.assertTrue(snapshot["ok"])
        self.assertEqual(snapshot["system"]["percent"], 87.5)
        self.assertEqual(snapshot["display"]["severity"], "warning")
        self.assertEqual(snapshot["application"]["ownRssBytes"], 300 * 1024**2)
        self.assertEqual(snapshot["application"]["childRssBytes"], 1200 * 1024**2)
        self.assertEqual(snapshot["application"]["combinedRssBytes"], 1500 * 1024**2)
        self.assertEqual(snapshot["application"]["childProcessCount"], 2)
        self.assertEqual(snapshot["application"]["children"][0]["pid"], 102)
        self.assertTrue(snapshot["application"]["childrenTruncated"])

    def test_sleep_prevention_policy_uses_thread_request_and_releases_cleanly(self) -> None:
        config = default_config()
        self.assertFalse(config["preventSleepDuringDownloads"])
        config["preventSleepDuringDownloads"] = True
        calls: list[int] = []
        controller = SleepPreventionController(
            platform_name="nt",
            execution_state_setter=lambda flags: calls.append(flags) or 1,
        )

        active = controller.set_required(True)
        self.assertTrue(active["active"])
        self.assertEqual(
            calls,
            [
                SleepPreventionController.ES_CONTINUOUS
                | SleepPreventionController.ES_SYSTEM_REQUIRED
            ],
        )
        controller.set_required(True)
        self.assertEqual(len(calls), 1)
        policy = sleep_prevention_policy_snapshot(
            config, active_downloads=2, controller=controller
        )
        self.assertTrue(policy["requested"])
        self.assertTrue(policy["active"])
        self.assertTrue(policy["preventsSystemSleepOnly"])
        self.assertFalse(policy["preventsDisplaySleep"])

        released = controller.close()
        self.assertFalse(released["active"])
        self.assertEqual(calls[-1], SleepPreventionController.ES_CONTINUOUS)
        self.assertEqual(released["transitionCount"], 2)

        failed = SleepPreventionController(
            platform_name="nt", execution_state_setter=lambda _flags: 0
        ).set_required(True)
        self.assertFalse(failed["ok"])
        self.assertFalse(failed["active"])
        self.assertIn("거부", failed["lastError"])

    def test_notification_plans_separate_enablement_sound_and_message_box(self) -> None:
        config = default_config()
        default_status = notification_settings_snapshot(config)
        self.assertEqual(default_status["sound"], "none")
        self.assertFalse(default_status["messageBox"])

        config.update(
            {
                "notificationSound": "system",
                "notificationMessageBox": True,
                "notifyOnComplete": True,
                "notifyOnError": False,
            }
        )
        complete = notification_event_plan(
            "complete", title="완료 작품", config=config
        )
        self.assertTrue(complete["enabled"])
        self.assertTrue(complete["trayRequested"])
        self.assertTrue(complete["messageBoxRequested"])
        self.assertTrue(complete["soundRequested"])
        self.assertEqual(complete["message"], "다운로드 완료: 완료 작품")

        disabled_error = notification_event_plan(
            "error", title="실패 작품", detail="네트워크 오류", config=config
        )
        self.assertFalse(disabled_error["enabled"])
        self.assertFalse(disabled_error["messageBoxRequested"])
        self.assertFalse(disabled_error["soundRequested"])
        preview = notification_event_plan(
            "error",
            title="실패 작품",
            detail="네트워크 오류",
            config=config,
            preview=True,
        )
        self.assertTrue(preview["enabled"])
        self.assertEqual(preview["message"], "실패 작품: 네트워크 오류")
        with self.assertRaises(ValueError):
            normalize_notification_sound("custom")
        with self.assertRaises(ValueError):
            notification_event_plan("unknown", config=config)

    def test_shortcut_overrides_validate_conflicts_disable_and_portable_export(self) -> None:
        config = default_config()
        config["shortcutOverrides"] = {
            "focus.search": ["Ctrl+Alt+F"],
            "search.clear": [],
        }
        snapshot = shortcut_settings_snapshot(config)
        by_id = {item["id"]: item for item in snapshot["shortcuts"]}
        self.assertEqual(by_id["focus.search"]["keys"], ["Ctrl+Alt+F"])
        self.assertFalse(by_id["search.clear"]["enabled"])
        self.assertEqual(snapshot["overrideCount"], 2)
        with self.assertRaisesRegex(ValueError, "중복"):
            normalize_shortcut_overrides({"focus.search": ["Ctrl+L"]})
        with self.assertRaisesRegex(ValueError, "단일 문자"):
            normalize_shortcut_overrides({"focus.search": ["A"]})
        with self.assertRaisesRegex(ValueError, "종료 키"):
            normalize_shortcut_overrides({"focus.search": ["Alt+F4"]})
        with self.assertRaisesRegex(ValueError, "객체"):
            normalize_shortcut_overrides([])

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            exported = root / "shortcuts.json"
            with patch("toki_core.load_config", return_value=config):
                result = export_shortcut_settings(exported)
                plan = shortcut_import_plan(exported)
            self.assertTrue(result["ok"])
            self.assertFalse(result["containsSecrets"])
            self.assertFalse(plan["executed"])
            self.assertEqual(
                plan["shortcutOverrides"]["focus.search"], ["Ctrl+Alt+F"]
            )
            invalid = root / "invalid.json"
            invalid.write_text(
                json.dumps(
                    {
                        "format": "tokiDownloader-shortcuts",
                        "formatVersion": 1,
                        "shortcutOverrides": [],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "객체"):
                shortcut_import_plan(invalid)

    def test_embedded_browser_defaults_offline_and_plans_https_navigation(self) -> None:
        capability = embedded_browser_capabilities()
        self.assertEqual(capability["defaultPage"], "offline")
        self.assertTrue(capability["offTheRecordProfile"])
        self.assertFalse(capability["persistentCookies"])
        self.assertFalse(capability["sharesAutomationCookies"])
        plan = embedded_browser_navigation_plan(
            "https://newtoki1.org/manhwa/34360"
        )
        self.assertTrue(plan["requiresNetwork"])
        self.assertTrue(plan["requiresConfirmation"])
        self.assertFalse(plan["sendsProviderCookies"])
        self.assertFalse(plan["executed"])
        self.assertEqual(plan["host"], "newtoki1.org")
        with self.assertRaises(ValueError):
            normalize_embedded_browser_url("http://example.test")
        with self.assertRaises(ValueError):
            normalize_embedded_browser_url("https://user:secret@example.test/")

    def test_proxy_credentials_use_injected_vault_and_only_reach_matching_runtime(self) -> None:
        class MemoryCredentialBackend:
            def __init__(self) -> None:
                self.values: dict[tuple[str, str], str] = {}

            def set_password(self, service: str, username: str, value: str) -> None:
                self.values[(service, username)] = value

            def get_password(self, service: str, username: str) -> str | None:
                return self.values.get((service, username))

            def delete_password(self, service: str, username: str) -> None:
                self.values.pop((service, username), None)

        backend = MemoryCredentialBackend()
        proxy_url = "socks5://127.0.0.1:1080"
        stored = store_proxy_credentials(
            proxy_url,
            "proxy-user",
            "secret-password",
            backend=backend,
        )
        self.assertTrue(stored["stored"])
        self.assertFalse(stored["valuesExposed"])
        self.assertNotIn("secret-password", json.dumps(stored))
        status = proxy_credential_status(proxy_url, backend=backend)
        self.assertTrue(status["matchesConfiguredProxy"])
        self.assertEqual(status["username"], "proxy-user")
        self.assertNotIn("secret-password", json.dumps(status))
        config = default_config()
        config["proxyUrl"] = proxy_url
        self.assertEqual(
            downloader_environment_overrides(config, backend=backend),
            {
                "TOKI_PROXY_USERNAME": "proxy-user",
                "TOKI_PROXY_PASSWORD": "secret-password",
            },
        )
        config["proxyUrl"] = "http://127.0.0.1:8080"
        self.assertEqual(downloader_environment_overrides(config, backend=backend), {})
        self.assertTrue(clear_proxy_credentials(backend=backend)["cleared"])
        self.assertFalse(proxy_credential_status(proxy_url, backend=backend)["stored"])

    def test_cookie_import_status_export_and_clear_use_injected_secure_backend(self) -> None:
        class MemoryCredentialBackend:
            def __init__(self) -> None:
                self.values: dict[tuple[str, str], str] = {}

            def set_password(self, service: str, username: str, value: str) -> None:
                self.values[(service, username)] = value

            def get_password(self, service: str, username: str) -> str | None:
                return self.values.get((service, username))

            def delete_password(self, service: str, username: str) -> None:
                self.values.pop((service, username), None)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "cookies.json"
            output = root / "exported.json"
            source.write_text(
                json.dumps(
                    [
                        {
                            "name": "session",
                            "value": "secret-value",
                            "domain": ".example.test",
                            "path": "/",
                            "secure": True,
                        }
                    ]
                ),
                encoding="utf-8",
            )
            backend = MemoryCredentialBackend()
            plan = cookie_import_plan("manatoki", source)
            self.assertFalse(plan["executed"])
            self.assertEqual(plan["cookieCount"], 1)
            imported = import_provider_cookies(
                "manatoki", source, backend=backend
            )
            self.assertTrue(imported["executed"])
            status = provider_cookie_status("manatoki", backend=backend)
            self.assertTrue(status["stored"])
            self.assertEqual(status["cookieCount"], 1)
            self.assertFalse(status["valuesExposed"])
            self.assertNotIn("secret-value", json.dumps(status))
            exported = export_provider_cookies(
                "manatoki", output, backend=backend
            )
            self.assertTrue(exported["containsSensitiveValues"])
            self.assertIn("secret-value", output.read_text(encoding="utf-8"))
            cleared = clear_provider_cookies("manatoki", backend=backend)
            self.assertTrue(cleared["cleared"])
            self.assertFalse(
                provider_cookie_status("manatoki", backend=backend)["stored"]
            )

    def test_exhentai_cookie_policy_filters_domains_and_never_reports_values(self) -> None:
        class MemoryCredentialBackend:
            def __init__(self) -> None:
                self.values: dict[tuple[str, str], str] = {}

            def set_password(self, service: str, username: str, value: str) -> None:
                self.values[(service, username)] = value

            def get_password(self, service: str, username: str) -> str | None:
                return self.values.get((service, username))

        policy = provider_cookie_policy("exhentai")
        self.assertTrue(policy["authenticationRequired"])
        self.assertFalse(policy["accessRestrictionBypassSupported"])
        self.assertEqual(
            policy["recommendedCookieNames"],
            ["ipb_member_id", "ipb_pass_hash", "igneous"],
        )
        assessment = assess_provider_cookies(
            "exhentai",
            [
                {"name": "ipb_member_id", "value": "secret-a", "domain": ".e-hentai.org"},
                {"name": "ipb_pass_hash", "value": "secret-b", "domain": ".e-hentai.org"},
                {"name": "session", "value": "unrelated-secret", "domain": ".example.test"},
            ],
        )
        self.assertIsNone(assessment["authenticationReady"])
        self.assertFalse(assessment["authenticationReadinessVerifiable"])
        self.assertEqual(assessment["relevantCookieCount"], 2)
        self.assertEqual(assessment["ignoredCookieCount"], 1)
        self.assertNotIn("secret", json.dumps(assessment))

        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "cookies.json"
            source.write_text(
                json.dumps(
                    [
                        {"name": "ipb_member_id", "value": "secret-a", "domain": ".e-hentai.org"},
                        {"name": "ipb_pass_hash", "value": "secret-b", "domain": ".e-hentai.org"},
                        {"name": "session", "value": "unrelated-secret", "domain": ".example.test"},
                    ]
                ),
                encoding="utf-8",
            )
            backend = MemoryCredentialBackend()
            plan = cookie_import_plan("exhentai", source)
            self.assertEqual(plan["cookieCount"], 2)
            self.assertEqual(plan["ignoredCookieCount"], 1)
            self.assertIsNone(plan["authenticationReady"])
            imported = import_provider_cookies("exhentai", source, backend=backend)
            self.assertTrue(imported["executed"])
            stored_payload = json.loads(
                backend.values[(toki_core.CREDENTIAL_SERVICE, "cookies:exhentai")]
            )
            self.assertEqual(len(stored_payload["cookies"]), 2)
            self.assertNotIn("unrelated-secret", json.dumps(stored_payload))
            status = provider_cookie_status("exhentai", backend=backend)
            self.assertIsNone(status["authenticationReady"])
            self.assertFalse(status["valuesExposed"])
            self.assertNotIn("secret-a", json.dumps(status))
            header = provider_cookie_request_header(
                "exhentai",
                "https://api.e-hentai.org/api.php",
                backend=backend,
                now_epoch=1,
            )
            self.assertIn("ipb_member_id=secret-a", header)
            self.assertIn("ipb_pass_hash=secret-b", header)
            with self.assertRaisesRegex(ValueError, "도메인"):
                provider_cookie_request_header(
                    "exhentai",
                    "https://example.test/api",
                    backend=backend,
                )

        with tempfile.TemporaryDirectory() as temporary:
            unsafe = Path(temporary) / "unsafe.json"
            unsafe.write_text(
                json.dumps(
                    [{"name": "session", "value": "safe; injected=x", "domain": ".e-hentai.org"}]
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "안전하지 않은"):
                cookie_import_plan("exhentai", unsafe)

    def test_public_ip_service_requires_confirmation_plan_and_accepts_injected_response(self) -> None:
        plan = public_ip_check_plan()
        self.assertTrue(plan["requiresNetwork"])
        self.assertTrue(plan["requiresConfirmation"])
        self.assertFalse(plan["sendsCookies"])
        self.assertFalse(plan["networkRequested"])
        self.assertFalse(plan["executed"])
        self.assertEqual(plan["maxResponseBytes"], 4096)
        with self.assertRaisesRegex(ValueError, "명시적 확인"):
            lookup_public_ip()
        calls = []
        result = lookup_public_ip(
            fetcher=lambda endpoint, timeout: (
                calls.append((endpoint, timeout)) or b'{"ip":"203.0.113.7"}'
            )
        )
        self.assertEqual(result["ip"], "203.0.113.7")
        self.assertEqual(result["version"], 4)
        self.assertTrue(result["executed"])
        self.assertFalse(result["networkRequested"])
        self.assertTrue(result["injectedFetcher"])
        self.assertEqual(len(calls), 1)
        ipv6 = lookup_public_ip(
            fetcher=lambda _endpoint, _timeout: b'{"ip":"2001:db8::7"}'
        )
        self.assertEqual(ipv6["version"], 6)
        with self.assertRaises(ValueError):
            lookup_public_ip(fetcher=lambda _endpoint, _timeout: b'{"ip":"invalid"}')
        with self.assertRaisesRegex(ValueError, "허용 크기"):
            lookup_public_ip(fetcher=lambda _endpoint, _timeout: b"x" * 4097)

    def test_network_policy_validates_proxy_speed_and_provider_pacing(self) -> None:
        config = default_config()
        config["proxyUrl"] = "socks5://127.0.0.1:1080"
        config["speedLimitKib"] = 2048
        config["providerPolicies"]["manatoki"] = {
            "requestDelayMs": 250,
            "backoffSeconds": 4,
        }
        result = network_policy_snapshot(
            config, url="https://newtoki1.org/manhwa/34360"
        )
        self.assertTrue(result["proxyEnabled"])
        self.assertFalse(result["proxyAuthenticationStored"])
        self.assertEqual(result["provider"], "manatoki")
        self.assertEqual(result["providerPolicy"]["requestDelayMs"], 250)
        self.assertEqual(result["providerPolicy"]["backoffSeconds"], 4)
        self.assertEqual(
            normalize_proxy_url("http://localhost:8080/"),
            "http://localhost:8080",
        )
        self.assertEqual(normalize_speed_limit_kib(0), 0)
        with self.assertRaises(ValueError):
            normalize_proxy_url("http://user:secret@localhost:8080")
        with self.assertRaises(ValueError):
            normalize_speed_limit_kib(1)
        with self.assertRaises(ValueError):
            normalize_provider_policies({"unknown": {}})

    def test_browser_policy_defaults_to_hidden_isolated_automation_profile(self) -> None:
        headless = browser_launch_policy(False)
        self.assertEqual(headless["mode"], "headless")
        self.assertFalse(headless["windowVisible"])
        self.assertFalse(headless["personalChromeProfile"])
        self.assertTrue(headless["recommended"])
        visible = browser_launch_policy(True)
        self.assertEqual(visible["mode"], "visible-diagnostic")
        self.assertTrue(visible["windowVisible"])
        self.assertFalse(visible["recommended"])

    def test_korean_ui_resources_and_display_preferences_are_validated(self) -> None:
        languages = available_ui_languages()
        self.assertIn({"code": "ko", "name": "한국어"}, languages)
        strings = load_ui_strings("ko")
        for key in (
            "main.menu.work",
            "settings.tab.general",
            "settings.tab.display",
            "provider.youtube",
        ):
            self.assertIn(key, strings)
        self.assertEqual(normalize_ui_language("KO"), "ko")
        self.assertEqual(normalize_ui_scale(125), 125)
        self.assertEqual(normalize_font_family("Malgun Gothic"), "Malgun Gothic")
        self.assertEqual(normalize_background_image("sample.webp"), "sample.webp")
        with self.assertRaises(ValueError):
            normalize_ui_language("en")
        with self.assertRaises(ValueError):
            normalize_ui_scale(250)
        with self.assertRaises(ValueError):
            normalize_background_image("sample.exe")

    def test_folder_name_template_preserves_requested_rule_and_validates_windows_path(self) -> None:
        template = "[{author}][{group}] {title}"
        metadata = {
            "author": "이요미네 츠쿠",
            "group": "N／A",
            "title": "이세계에서 개인방송 활동을 했더니 대량의 얀데레 신자를 만들어 버린 건",
            "source": {"siteTitle": "마나토끼", "workId": "34360"},
        }
        self.assertEqual(
            render_folder_name_template(template, metadata),
            "[이요미네 츠쿠][N／A] 이세계에서 개인방송 활동을 했더니 대량의 얀데레 신자를 만들어 버린 건",
        )
        result = folder_name_template_preview(template, metadata=metadata)
        self.assertTrue(result["dryRun"])
        self.assertFalse(result["existingFoldersChanged"])
        with self.assertRaisesRegex(ValueError, "지원하지 않는"):
            normalize_folder_name_template("{publisher} {title}")
        with self.assertRaisesRegex(ValueError, "금지 문자"):
            normalize_folder_name_template("{author}/{title}")
        with self.assertRaisesRegex(ValueError, "title"):
            normalize_folder_name_template("[{author}]")

    def test_local_zip_archive_inspection_is_read_only_and_flags_unsafe_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive_path = root / "work.cbz"
            outside_path = root / "escape.jpg"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("001/001.jpg", b"image")
                archive.writestr("001/empty.png", b"")
                archive.writestr("../escape.jpg", b"unsafe")

            result = inspect_local_archive(archive_path)

            self.assertTrue(result["ok"])
            self.assertFalse(result["healthy"])
            self.assertEqual(result["format"], "zip")
            self.assertEqual(result["imageCount"], 3)
            self.assertEqual(result["emptyFileCount"], 1)
            self.assertEqual(result["suspiciousPathCount"], 1)
            self.assertFalse(result["extracted"])
            self.assertFalse(result["filesChanged"])
            self.assertFalse(outside_path.exists())

    def test_archive_viewer_policy_plans_and_launches_without_changing_associations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive_path = root / "한글 작품.cbz"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("001/001.jpg", b"image")

            system_policy = archive_viewer_policy_snapshot(default_config())
            self.assertEqual(system_policy["mode"], "system")
            self.assertFalse(system_policy["changesSystemAssociation"])
            self.assertTrue(system_policy["requiresConfirmation"])

            custom = default_config()
            custom["archiveViewerMode"] = "custom"
            custom["archiveViewerPath"] = str(Path(toki_core.__file__).resolve())
            plan = plan_archive_viewer_open(archive_path, config=custom)
            self.assertTrue(plan["ok"])
            self.assertFalse(plan["executed"])
            self.assertEqual(plan["mode"], "custom")
            self.assertEqual(plan["command"][1], str(archive_path.resolve()))
            self.assertFalse(plan["changesSystemAssociation"])

            launched: list[dict[str, object]] = []
            result = open_archive_with_viewer(
                archive_path,
                config=custom,
                execute=True,
                launcher=lambda value: launched.append(value) or 314,
            )
            self.assertTrue(result["executed"])
            self.assertEqual(result["processId"], 314)
            self.assertEqual(len(launched), 1)
            self.assertTrue(archive_path.is_file())

            config_path = root / "config.json"
            with patch.object(toki_core, "CONFIG_PATH", config_path):
                toki_core.save_config(default_config())
                with self.assertRaisesRegex(ValueError, "실행 파일 경로"):
                    toki_core.update_app_settings({"archiveViewerMode": "custom"})
                saved = toki_core.update_app_settings(
                    {
                        "archiveViewerMode": "custom",
                        "archiveViewerPath": str(Path(toki_core.__file__).resolve()),
                    }
                )
                self.assertEqual(saved["archiveViewerMode"], "custom")

    def test_persistence_policy_validates_autosave_and_startup_recovery(self) -> None:
        policy = persistence_policy_snapshot(default_config())
        self.assertEqual(policy["autosaveIntervalSeconds"], 1)
        self.assertTrue(policy["startupRecoveryEnabled"])
        self.assertTrue(policy["preservesProgress"])
        self.assertTrue(policy["preservesDownloadedFiles"])
        with self.assertRaisesRegex(ValueError, "1~300초"):
            toki_core.normalize_autosave_interval_seconds(0)

        with tempfile.TemporaryDirectory() as temporary:
            config_path = Path(temporary) / "config.json"
            with patch.object(toki_core, "CONFIG_PATH", config_path):
                toki_core.save_config(default_config())
                saved = toki_core.update_app_settings(
                    {
                        "autosaveIntervalSeconds": 12,
                        "recoverInterruptedOnStartup": False,
                    }
                )
                updated = persistence_policy_snapshot(saved)
                self.assertEqual(updated["autosaveIntervalSeconds"], 12)
                self.assertFalse(updated["startupRecoveryEnabled"])

    def test_list_performance_policy_preserves_config_and_bounds_low_spec_cost(self) -> None:
        normal = default_config()
        normal.update(
            {
                "listPageSize": 800,
                "listLoadedLimit": 5000,
                "listScrollLines": 20,
                "listLazyLoading": False,
                "lowSpecMode": False,
                "thumbnailsVisible": True,
            }
        )
        normal_policy = list_performance_policy_snapshot(normal)
        self.assertEqual(normal_policy["effective"]["pageSize"], 800)
        self.assertEqual(normal_policy["effective"]["loadedLimit"], 5000)
        self.assertFalse(normal_policy["effective"]["lazyLoading"])
        self.assertTrue(normal_policy["effective"]["thumbnailsVisible"])
        self.assertTrue(normal_policy["eagerLoadingOptIn"])

        low = {**normal, "lowSpecMode": True}
        low_policy = list_performance_policy_snapshot(low)
        self.assertEqual(low_policy["configured"]["pageSize"], 800)
        self.assertEqual(low_policy["configured"]["loadedLimit"], 5000)
        self.assertEqual(low_policy["effective"]["pageSize"], 100)
        self.assertEqual(low_policy["effective"]["loadedLimit"], 500)
        self.assertEqual(low_policy["effective"]["scrollLines"], 3)
        self.assertTrue(low_policy["effective"]["lazyLoading"])
        self.assertFalse(low_policy["effective"]["thumbnailsVisible"])
        self.assertEqual(low_policy["effective"]["thumbnailCacheEntries"], 32)
        self.assertFalse(low_policy["eagerLoadingOptIn"])
        self.assertTrue(low_policy["visibleOnlyThumbnailDecode"])
        with self.assertRaisesRegex(ValueError, "25~1000"):
            toki_core.normalize_list_page_size(24)
        with self.assertRaisesRegex(ValueError, "100~5000"):
            toki_core.normalize_list_loaded_limit(99)
        with self.assertRaisesRegex(ValueError, "1~20"):
            toki_core.normalize_list_scroll_lines(21)

    def test_settings_export_import_preview_apply_and_reset_are_safe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path = root / "config.json"
            export_path = root / "export.json"
            with patch.object(toki_core, "CONFIG_PATH", config_path):
                current = default_config()
                current["workConcurrency"] = 2
                toki_core.save_config(current)
                exported = toki_core.export_app_settings(export_path)
                payload = json.loads(export_path.read_text(encoding="utf-8"))
                payload["settings"]["workConcurrency"] = 3
                payload["settings"]["theme"] = "dark"
                export_path.write_text(json.dumps(payload), encoding="utf-8")

                preview = toki_core.import_app_settings(export_path)
                self.assertFalse(preview["executed"])
                self.assertEqual(settings_snapshot()["workConcurrency"], 2)
                self.assertEqual(preview["after"]["workConcurrency"], 3)

                applied = toki_core.import_app_settings(export_path, execute=True)
                self.assertTrue(applied["executed"])
                self.assertTrue(Path(applied["backupPath"]).is_file())
                self.assertEqual(settings_snapshot()["workConcurrency"], 3)
                self.assertEqual(settings_snapshot()["theme"], "dark")

                reset_preview = toki_core.reset_app_settings()
                self.assertFalse(reset_preview["executed"])
                self.assertEqual(settings_snapshot()["workConcurrency"], 3)
                reset_result = toki_core.reset_app_settings(execute=True)
                self.assertTrue(reset_result["executed"])
                self.assertEqual(settings_snapshot()["workConcurrency"], 1)
                self.assertTrue(exported["ok"])

                payload["settings"]["workConcurrency"] = 99
                export_path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaises(ValueError):
                    toki_core.import_app_settings(export_path)

    def test_diagnostics_bundle_excludes_user_data_and_redacts_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "diagnostics.zip"

            result = export_diagnostics(target)

            self.assertTrue(result["ok"])
            with zipfile.ZipFile(target) as archive:
                self.assertEqual(
                    set(archive.namelist()),
                    {"diagnostics.json", "recent-gui.log.txt", "README.txt"},
                )
                combined = "\n".join(
                    archive.read(name).decode("utf-8") for name in archive.namelist()
                )
            self.assertNotIn(str(ROOT_DIR), combined)
            self.assertNotIn(str(Path.home()), combined)
            self.assertNotIn("https://", combined)
            self.assertIn('"outputDir": "<REDACTED>"', combined)
            sample = toki_core._redact_diagnostic_value(
                "[INFO] [abc123] D:\\Private Manga\\title manatoki:34360 https://example.com",
                (str(ROOT_DIR), str(Path.home()), r"D:\Private Manga"),
            )
            self.assertEqual(
                sample,
                "[INFO] [<JOB>] <PRIVATE_PATH>\\title <WORK_ID> <URL>",
            )

    def test_config_schema_migration_backs_up_and_preserves_unknown_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config_path = Path(temporary) / "config.json"
            config_path.write_text(
                json.dumps({"futureField": {"enabled": True}}), encoding="utf-8"
            )

            result = toki_core.apply_config_migrations(config_path)
            migrated = json.loads(config_path.read_text(encoding="utf-8"))

            self.assertTrue(result["ok"])
            self.assertEqual(result["before"]["version"], 0)
            self.assertEqual(
                result["after"]["version"], toki_core.CONFIG_SCHEMA_VERSION
            )
            self.assertTrue(Path(result["backupPath"]).is_file())
            self.assertEqual(migrated["futureField"], {"enabled": True})
            self.assertEqual(
                migrated["configVersion"], toki_core.CONFIG_SCHEMA_VERSION
            )
            future_path = Path(temporary) / "future.json"
            future_payload = {"configVersion": toki_core.CONFIG_SCHEMA_VERSION + 1}
            future_path.write_text(json.dumps(future_payload), encoding="utf-8")
            with self.assertRaises(ValueError):
                toki_core.apply_config_migrations(future_path)
            self.assertEqual(
                json.loads(future_path.read_text(encoding="utf-8")), future_payload
            )

    def test_windows_setup_script_uses_lockfile_check_mode_and_doctor(self) -> None:
        script = (ROOT_DIR / "setup-gui.ps1").read_text(encoding="utf-8")

        self.assertIn("[switch]$CheckOnly", script)
        self.assertIn("[switch]$WithArchiveTools", script)
        self.assertIn("[switch]$WithBrowserTools", script)
        self.assertIn("[switch]$WithYouTube", script)
        self.assertIn("requirements-archive-tools.txt", script)
        self.assertIn("requirements-browser-tools.txt", script)
        self.assertIn("requirements-youtube.txt", script)
        self.assertIn("'youtube_worker.py'", script)
        self.assertIn("Run setup-gui.cmd -WithYouTube", script)
        self.assertIn("'ci', '--no-audit', '--no-fund'", script)
        self.assertIn("toki_app.py') doctor --json", script)
        self.assertNotIn(
            "pause", (ROOT_DIR / "setup-gui.cmd").read_text(encoding="utf-8")
        )

    def test_clean_install_smoke_is_isolated_and_self_cleaning(self) -> None:
        script = (ROOT_DIR / "scripts" / "clean-install-smoke.ps1").read_text(
            encoding="utf-8"
        )

        self.assertIn("git -C $projectRoot archive", script)
        self.assertIn("self-test --json", script)
        self.assertIn("StartsWith($tempRoot", script)
        self.assertIn("StartsWith('toki-clean-install-')", script)
        self.assertIn("Remove-Item -LiteralPath $resolvedWorkspace", script)

    def test_dependency_doctor_separates_required_and_optional_tools(self) -> None:
        report = dependency_diagnostics()
        checks = {item["name"]: item for item in report["checks"]}

        self.assertTrue(report["ok"])
        self.assertTrue(checks["Python"]["available"])
        self.assertTrue(checks["Node.js"]["available"])
        self.assertTrue(checks["puppeteer-real-browser"]["available"])
        self.assertEqual(checks["Pillow"]["kind"], "optional")
        self.assertEqual(checks["FFmpeg"]["kind"], "optional")
        self.assertEqual(checks["PyQt6-WebEngine"]["kind"], "optional")
        self.assertEqual(checks["yt-dlp"]["kind"], "optional")

    def test_bounded_text_keeps_utf8_tail_and_reports_dropped_bytes(self) -> None:
        text, dropped = append_bounded_text("앞" * 10, "끝" * 10, 17)

        self.assertLessEqual(len(text.encode("utf-8")), 17)
        self.assertTrue(text.endswith("끝"))
        self.assertGreater(dropped, 0)

    def test_resource_budget_limits_io_cpu_and_download_queue(self) -> None:
        normal = resource_budget(cpu_count=16, available_memory_bytes=16 * 1024**3)
        low_memory = resource_budget(cpu_count=16, available_memory_bytes=2 * 1024**3)

        self.assertEqual(normal["ioThreads"], 8)
        self.assertEqual(normal["cpuProcesses"], 4)
        self.assertEqual(low_memory["ioThreads"], 4)
        self.assertEqual(low_memory["cpuProcesses"], 1)
        self.assertTrue(
            resource_admission("cpu", active_count=3, budget=normal)["allowed"]
        )
        self.assertFalse(
            resource_admission("cpu", active_count=4, budget=normal)["allowed"]
        )
        self.assertFalse(
            resource_admission(
                "download_queue", queued_count=1_000, budget=normal
            )["allowed"]
        )

    def test_thumbnail_cache_key_changes_with_source_and_cleanup_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "원본 표지.jpg"
            cache_dir = root / "앱 캐시"
            source.write_bytes(b"first")
            first_key = thumbnail_cache_path(source, cache_dir=cache_dir)
            source.write_bytes(b"second-version")
            second_key = thumbnail_cache_path(source, cache_dir=cache_dir)
            self.assertNotEqual(first_key, second_key)
            self.assertEqual(second_key.parent, cache_dir.resolve())

            cache_dir.mkdir(parents=True)
            now = time.time()
            for index in range(5):
                path = cache_dir / f"{index}.png"
                path.write_bytes(bytes([index]) * (index + 1) * 10)
                os.utime(path, (now - index, now - index))
            (cache_dir / "partial.tmp").write_bytes(b"partial")

            preview = cleanup_thumbnail_cache(
                cache_dir=cache_dir,
                max_files=2,
                max_bytes=1_000,
                max_age_days=90,
                execute=False,
            )
            self.assertEqual(preview["removeFiles"], 4)
            self.assertEqual(len(list(cache_dir.iterdir())), 6)

            executed = cleanup_thumbnail_cache(
                cache_dir=cache_dir,
                max_files=2,
                max_bytes=1_000,
                max_age_days=90,
                execute=True,
            )
            self.assertTrue(executed["ok"])
            self.assertEqual(executed["removedFiles"], 4)
            self.assertEqual(len(list(cache_dir.glob("*.png"))), 2)
            self.assertTrue(source.is_file())

    def test_downloader_event_policy_coalesces_only_high_frequency_progress(self) -> None:
        image = downloader_event_update_policy("image_saved")
        completed = downloader_event_update_policy("completed")
        metadata = downloader_event_update_policy("work_metadata")

        self.assertEqual(image["uiMode"], "coalesced")
        self.assertEqual(image["uiIntervalMs"], 100)
        self.assertFalse(image["persistRun"])
        self.assertEqual(completed["uiMode"], "immediate")
        self.assertTrue(completed["persistRun"])
        self.assertTrue(completed["terminal"])
        self.assertTrue(metadata["persistRun"])

    def test_window_geometry_preserves_valid_monitor_and_recovers_missing_screen(self) -> None:
        screens = [
            {
                "name": "Primary", "x": 0, "y": 0, "width": 3072, "height": 1232,
                "devicePixelRatio": 1.25, "primary": True,
            },
            {
                "name": "Side", "x": 3840, "y": -564, "width": 2560, "height": 1440,
                "devicePixelRatio": 1.5, "primary": False,
            },
        ]
        valid = plan_window_geometry(
            {
                "x": 3851, "y": -349, "width": 720, "height": 997,
                "screenName": "Side", "screenDpr": 1.5,
            },
            screens,
        )
        recovered = plan_window_geometry(
            {
                "x": 9000, "y": 4000, "width": 1000, "height": 800,
                "screenName": "Removed", "screenDpr": 2.0,
                "relativeX": 40, "relativeY": 30,
            },
            screens,
        )
        centered = plan_window_geometry(
            {"width": 800, "height": 600},
            screens,
            target_screen="Side",
            center=True,
        )

        self.assertEqual((valid["x"], valid["y"]), (3851, -349))
        self.assertEqual(valid["screenName"], "Side")
        self.assertFalse(valid["clamped"])
        self.assertEqual((recovered["x"], recovered["y"]), (40, 30))
        self.assertEqual(recovered["screenName"], "Primary")
        self.assertTrue(recovered["clamped"])
        self.assertTrue(recovered["dpiChanged"])
        self.assertEqual(centered["screenName"], "Side")
        self.assertEqual(centered["x"], 3840 + (2560 - 800) // 2)

    def test_keyboard_shortcut_catalog_is_unique_and_cli_backed(self) -> None:
        catalog = keyboard_shortcut_catalog()
        action_ids = [item["id"] for item in catalog]
        keys = [key for item in catalog for key in item["keys"]]

        self.assertEqual(len(action_ids), len(set(action_ids)))
        self.assertEqual(len(keys), len(set(keys)))
        self.assertTrue(all(item["cli"] for item in catalog))
        self.assertEqual(keyboard_shortcut_keys("focus.search"), ["Ctrl+F"])
        with self.assertRaises(ValueError):
            keyboard_shortcut_keys("missing.action")

    def test_menu_action_availability_tracks_selection_queue_and_process_state(self) -> None:
        job = DownloadJob(
            job_id="j1",
            url="https://example.test/work/1",
            output_dir="D:/Manga",
            output_path="D:/Manga/work",
        )
        idle = menu_action_availability(job, form_url="https://example.test/work/2")
        running = menu_action_availability(
            job,
            form_url="",
            active_job_ids=["j1", "j2"],
            paused_job_ids=["j1"],
        )
        queued = menu_action_availability(job, queued_job_ids=["j1"])
        empty = menu_action_availability(None)

        self.assertTrue(idle["download.start"])
        self.assertTrue(idle["job.rescan_full"])
        self.assertTrue(idle["folder.open"])
        self.assertTrue(running["job.stop"])
        self.assertTrue(running["job.pause"])
        self.assertTrue(running["job.resume"])
        self.assertFalse(running["job.rescan_full"])
        self.assertFalse(running["snapshot.import"])
        self.assertFalse(queued["job.rescan_new"])
        self.assertFalse(empty["details.open"])

    def test_completion_action_requires_idle_armed_state_and_countdown(self) -> None:
        none = completion_action_plan("none", 15, armed=True)
        busy = completion_action_plan(
            "shutdown", 30, active_count=1, pending_count=2, armed=True
        )
        shutdown = completion_action_plan("shutdown", 30, armed=True)

        self.assertFalse(none["shouldTrigger"])
        self.assertFalse(busy["shouldTrigger"])
        self.assertTrue(shutdown["shouldTrigger"])
        self.assertTrue(shutdown["requiresCountdown"])
        self.assertTrue(shutdown["destructive"])
        with self.assertRaises(ValueError):
            completion_action_plan("shutdown", 1, armed=True)

    def test_clipboard_url_inspection_rejects_noise_and_flags_work_duplicates(self) -> None:
        noise = inspect_clipboard_url("일반 텍스트 https://example.com/page")
        new = inspect_clipboard_url(
            "복사: https://newtoki1.org/manhwa/34360)."
        )
        duplicate = inspect_clipboard_url(
            new["url"], existing_work_keys={new["workKey"]}
        )

        self.assertFalse(noise["candidate"])
        self.assertEqual(noise["reason"], "unsupported_url")
        self.assertTrue(new["candidate"])
        self.assertEqual(new["workKey"], "manatoki:34360")
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(duplicate["reason"], "duplicate")

    def test_job_list_view_state_covers_loading_empty_filtered_error_and_content(self) -> None:
        loading = build_job_list_view_state(loading=True, total_count=12)
        empty = build_job_list_view_state()
        no_results = build_job_list_view_state(
            total_count=12, filtered_count=0, query="없는 작품"
        )
        error = build_job_list_view_state(error="DB 읽기 실패", total_count=12)
        content = build_job_list_view_state(total_count=12, filtered_count=3)

        self.assertEqual(loading["state"], "loading")
        self.assertEqual(empty["action"], "focus_url")
        self.assertEqual(no_results["state"], "no_results")
        self.assertEqual(no_results["action"], "reset_filters")
        self.assertEqual(error["action"], "retry")
        self.assertEqual(error["message"], "DB 읽기 실패")
        self.assertEqual(content["state"], "content")
        self.assertEqual(content["filtered"], 3)

    def test_settings_normalize_invalid_values_and_update_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path = root / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "outputDir": "",
                        "showBrowser": "yes",
                        "workConcurrency": 99,
                        "imageConcurrency": 0,
                        "retryCount": -1,
                        "retryBackoffSeconds": 999,
                        "logMaxMiB": 0,
                        "logBackupCount": 99,
                        "rowDensity": "giant",
                        "theme": "sepia",
                        "listViewMode": "tiles",
                        "thumbnailSize": "huge",
                        "windowOpacity": 10,
                        "quickActions": ["missing.action"],
                        "trayEnabled": "yes",
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(toki_core, "CONFIG_PATH", config_path):
                loaded = toki_core.load_config()
                defaults = default_config()
                self.assertEqual(loaded["outputDir"], defaults["outputDir"])
                self.assertFalse(loaded["showBrowser"])
                self.assertEqual(loaded["workConcurrency"], 1)
                self.assertEqual(loaded["logMaxMiB"], 2)
                self.assertEqual(loaded["rowDensity"], "comfortable")
                self.assertEqual(loaded["theme"], "system")
                self.assertEqual(loaded["listViewMode"], "list")
                self.assertEqual(loaded["thumbnailSize"], "medium")
                self.assertEqual(loaded["windowOpacity"], 100)
                self.assertEqual(loaded["quickActions"], defaults["quickActions"])
                self.assertFalse(loaded["trayEnabled"])

                output = root / "새 저장 폴더"
                background = root / "한글 배경.png"
                background.write_bytes(b"png-test")
                updated = update_app_settings(
                    {
                        "outputDir": str(output),
                        "folderNameTemplate": "[{site}][{id}] {title}",
                        "uiLanguage": "ko",
                        "uiScale": 125,
                        "fontFamily": "Arial",
                        "backgroundImage": str(background),
                        "showBrowser": True,
                        "logVisible": False,
                        "workConcurrency": 3,
                        "imageConcurrency": 12,
                        "retryCount": 4,
                        "retryBackoffSeconds": 7,
                        "logMaxMiB": 5,
                        "logBackupCount": 3,
                        "rowDensity": "compact",
                        "theme": "dark",
                        "listViewMode": "icon",
                        "thumbnailsVisible": False,
                        "thumbnailSize": "large",
                        "alwaysOnTop": True,
                        "windowOpacity": 85,
                        "quickActions": [
                            "settings.open",
                            "folder.open",
                            "settings.open",
                        ],
                        "trayEnabled": True,
                        "closeToTray": True,
                        "notifyOnComplete": False,
                    }
                )
                self.assertTrue(output.is_dir())
                self.assertEqual(updated["workConcurrency"], 3)
                self.assertEqual(
                    updated["folderNameTemplate"], "[{site}][{id}] {title}"
                )
                self.assertEqual(updated["uiLanguage"], "ko")
                self.assertEqual(updated["uiScale"], 125)
                self.assertEqual(updated["fontFamily"], "Arial")
                self.assertEqual(
                    updated["backgroundImage"], str(background.resolve())
                )
                self.assertEqual(updated["logBackupCount"], 3)
                self.assertEqual(updated["rowDensity"], "compact")
                self.assertEqual(updated["theme"], "dark")
                self.assertEqual(updated["listViewMode"], "icon")
                self.assertFalse(updated["thumbnailsVisible"])
                self.assertEqual(updated["thumbnailSize"], "large")
                self.assertTrue(updated["alwaysOnTop"])
                self.assertEqual(updated["windowOpacity"], 85)
                self.assertEqual(
                    updated["quickActions"], ["settings.open", "folder.open"]
                )
                self.assertTrue(updated["trayEnabled"])
                self.assertTrue(updated["closeToTray"])
                self.assertFalse(updated["notifyOnComplete"])
                self.assertFalse((root / "config.json.tmp").exists())
                persisted = json.loads(config_path.read_text(encoding="utf-8"))
                self.assertEqual(settings_snapshot(persisted), updated)
                with self.assertRaises(ValueError):
                    update_app_settings({"unknownSetting": True})

    def test_config_normalization_preserves_unknown_future_fields(self) -> None:
        normalized = normalize_config({"futureField": {"enabled": True}})
        self.assertEqual(normalized["futureField"], {"enabled": True})
        self.assertEqual(normalized["logBackupCount"], 1)

    def test_log_rotation_honors_configurable_backup_count(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            log_path = Path(temporary) / "gui.log"
            log_path.write_text("new-current", encoding="utf-8")
            log_path.with_suffix(".log.1").write_text("older-one", encoding="utf-8")
            log_path.with_suffix(".log.2").write_text("oldest", encoding="utf-8")
            with patch.object(toki_core, "LOG_PATH", log_path):
                toki_core._rotate_log_if_needed(max_bytes=1, backup_count=2)
            self.assertEqual(log_path.read_text(encoding="utf-8"), "")
            self.assertEqual(
                log_path.with_suffix(".log.1").read_text(encoding="utf-8"),
                "new-current",
            )
            self.assertEqual(
                log_path.with_suffix(".log.2").read_text(encoding="utf-8"),
                "older-one",
            )

    def test_work_key_ignores_rotating_domain(self) -> None:
        self.assertEqual(build_work_key("https://newtoki1.org/manhwa/34360"), "manatoki:34360")
        self.assertEqual(build_work_key("https://newtoki999.org/comic/34360"), "manatoki:34360")
        self.assertEqual(build_work_key("https://booktoki12.org/novel/88"), "booktoki:88")

    def test_range_normalization_and_validation(self) -> None:
        self.assertEqual(normalize_range(0, 0), (None, None))
        self.assertEqual(normalize_range(3, 9), (3, 9))
        with self.assertRaises(ValueError):
            normalize_range(10, 2)

    def test_downloader_arguments_keep_paths_as_single_arguments(self) -> None:
        job = DownloadJob(
            job_id="job",
            url="https://newtoki1.org/manhwa/34360",
            output_dir=r"C:\한글 폴더\Manga",
            start=1,
            last=2,
            show_browser=True,
        )
        args = build_downloader_args(job)
        self.assertIn(job.output_dir, args)
        self.assertIn("-show-browser", args)
        self.assertIn("-json-events", args)
        template_index = args.index("-folder-template")
        self.assertEqual(args[template_index + 1], "[{author}][{group}] {title}")
        self.assertIn("-speed-limit-kib", args)
        self.assertIn("-request-delay-ms", args)
        self.assertIn("-provider-backoff", args)
        concurrency_index = args.index("-image-concurrency")
        self.assertEqual(args[concurrency_index + 1], "5")
        mode_index = args.index("-scan-mode")
        self.assertEqual(args[mode_index + 1], "new")

    def test_downloader_arguments_include_selected_network_policy(self) -> None:
        job = DownloadJob(
            job_id="network",
            url="https://newtoki1.org/manhwa/34360",
            output_dir=r"C:\Manga",
        )
        config = default_config()
        config["proxyUrl"] = "http://127.0.0.1:8080"
        config["speedLimitKib"] = 4096
        config["providerPolicies"]["manatoki"] = {
            "requestDelayMs": 300,
            "backoffSeconds": 5,
        }
        args = build_downloader_args(job, network_config=config)
        self.assertEqual(args[args.index("-proxy") + 1], "http://127.0.0.1:8080")
        self.assertEqual(args[args.index("-speed-limit-kib") + 1], "4096")
        self.assertEqual(args[args.index("-request-delay-ms") + 1], "300")
        self.assertEqual(args[args.index("-provider-backoff") + 1], "5")

    def test_image_concurrency_has_safe_bounds(self) -> None:
        self.assertEqual(normalize_image_concurrency(None), 5)
        self.assertEqual(normalize_image_concurrency(16), 16)
        with self.assertRaises(ValueError):
            normalize_image_concurrency(17)

    def test_work_concurrency_has_safe_bounds(self) -> None:
        self.assertEqual(normalize_work_concurrency(None), 1)
        self.assertEqual(normalize_work_concurrency(4), 4)
        with self.assertRaises(ValueError):
            normalize_work_concurrency(5)

    def test_available_work_slots_never_exceeds_capacity(self) -> None:
        self.assertEqual(available_work_slots(0, 3), 3)
        self.assertEqual(available_work_slots(2, 3), 1)
        self.assertEqual(available_work_slots(3, 3), 0)
        self.assertEqual(available_work_slots(9, 3), 0)

    def test_scan_modes_and_range_contract_are_explicit(self) -> None:
        source = DownloadJob(
            job_id="source",
            url="https://newtoki1.org/manhwa/34360",
            output_dir=r"C:\Manga",
        )
        self.assertEqual(normalize_scan_mode(None), "new")
        self.assertEqual(
            toki_core.rescan_job_parameters(source, "new")["scan_mode"], "new"
        )
        self.assertEqual(
            toki_core.rescan_job_parameters(source, "full")["scan_mode"], "full"
        )
        ranged = toki_core.rescan_job_parameters(source, "range", 10, 20)
        self.assertEqual((ranged["start"], ranged["last"]), (10, 20))
        with self.assertRaises(ValueError):
            toki_core.rescan_job_parameters(source, "range")
        with self.assertRaises(ValueError):
            normalize_scan_mode("auto")
        self.assertEqual(normalize_scan_request("new", 10, 20), ("new", None, None))
        with self.assertRaises(ValueError):
            normalize_scan_request("range", None, None)

    def test_retry_policy_has_safe_bounds_and_exponential_delays(self) -> None:
        self.assertEqual(normalize_retry_count(None), 2)
        self.assertEqual(normalize_retry_count(0), 0)
        self.assertEqual(normalize_retry_backoff(None), 2)
        self.assertEqual(
            [retry_backoff_seconds(number, 3) for number in range(1, 5)],
            [3, 6, 12, 24],
        )
        with self.assertRaises(ValueError):
            normalize_retry_count(6)
        with self.assertRaises(ValueError):
            normalize_retry_backoff(0)

    def test_auto_retry_excludes_success_cancel_and_exhausted_attempts(self) -> None:
        self.assertTrue(
            should_auto_retry(
                exit_code=1,
                cancel_requested=False,
                attempt_count=1,
                retry_limit=2,
            )
        )
        self.assertFalse(
            should_auto_retry(
                exit_code=0,
                cancel_requested=False,
                attempt_count=1,
                retry_limit=2,
            )
        )
        self.assertFalse(
            should_auto_retry(
                exit_code=1,
                cancel_requested=False,
                attempt_count=1,
                retry_limit=2,
                error_category="authentication_required",
            )
        )
        self.assertFalse(
            should_auto_retry(
                exit_code=1,
                cancel_requested=False,
                attempt_count=1,
                retry_limit=2,
                retryable_hint=False,
            )
        )
        self.assertEqual(normalize_error_category("unexpected"), "unknown")
        self.assertFalse(
            should_auto_retry(
                exit_code=1,
                cancel_requested=True,
                attempt_count=1,
                retry_limit=2,
            )
        )
        self.assertFalse(
            should_auto_retry(
                exit_code=1,
                cancel_requested=False,
                attempt_count=3,
                retry_limit=2,
            )
        )

    def test_metadata_refresh_arguments_preserve_existing_work_folder(self) -> None:
        job = DownloadJob(
            job_id="metadata",
            url="https://newtoki1.org/manhwa/34360",
            output_dir=r"C:\Manga",
            output_path=r"C:\Manga\마나토끼\[작가][그룹] 제목",
            metadata_only=True,
        )
        args = build_downloader_args(job)
        self.assertIn("-metadata-only", args)
        content_path_index = args.index("-content-path")
        self.assertEqual(args[content_path_index + 1], job.output_path)
        self.assertEqual(DownloadRun.from_job(job).operation, "metadata_refresh")

    def test_full_rescan_preserves_existing_work_folder_after_template_change(self) -> None:
        job = DownloadJob(
            job_id="rescan-existing",
            url="https://newtoki1.org/manhwa/34360",
            output_dir=r"C:\Manga",
            output_path=r"C:\Manga\마나토끼\[기존 작가][기존 그룹] 기존 제목",
            scan_mode="full",
        )
        args = build_downloader_args(
            job, folder_template="[{site}][{id}] {title}"
        )
        content_index = args.index("-content-path")
        self.assertEqual(args[content_index + 1], job.output_path)
        template_index = args.index("-folder-template")
        self.assertEqual(args[template_index + 1], "[{site}][{id}] {title}")

    def test_pending_job_and_run_can_be_cancelled_before_start(self) -> None:
        job = DownloadJob(
            job_id="pending",
            url="https://newtoki1.org/manhwa/34360",
            output_dir=r"C:\Manga",
        )
        run = DownloadRun.from_job(job)
        mark_job_cancelled(job)
        mark_run_cancelled(run)
        self.assertEqual(job.state, "취소됨")
        self.assertEqual(run.state, "취소됨")
        self.assertTrue(run.finished_at)
        with self.assertRaises(ValueError):
            mark_job_cancelled(job)

    def test_pending_queue_can_move_before_first_and_last(self) -> None:
        jobs = [
            DownloadJob(
                job_id=job_id,
                url=f"https://newtoki1.org/manhwa/{8000 + index}",
                output_dir=r"C:\Manga",
            )
            for index, job_id in enumerate(("a", "b", "c"))
        ]
        moved = reorder_pending_jobs(jobs, "c", before_job_id="b")
        self.assertEqual([job.job_id for job in moved], ["a", "c", "b"])
        moved = reorder_pending_jobs(moved, "b", position="first")
        self.assertEqual([job.job_id for job in moved], ["b", "a", "c"])
        moved = reorder_pending_jobs(moved, "b", position="last")
        self.assertEqual([job.job_id for job in moved], ["a", "c", "b"])
        with self.assertRaises(ValueError):
            reorder_pending_jobs(jobs, "a")

    def test_pause_state_and_process_tree_are_applied_by_pid(self) -> None:
        job = DownloadJob(
            job_id="running",
            url="https://newtoki1.org/manhwa/34360",
            output_dir=r"C:\Manga",
            state="실행 중",
        )
        run = DownloadRun.from_job(job)
        run.state = "실행 중"
        set_job_pause_state(job, run, paused=True)
        self.assertEqual(job.state, "일시정지")
        set_job_pause_state(job, run, paused=False)
        self.assertEqual(job.state, "실행 중")

        class FakeProcess:
            def __init__(self, pid: int, children: list["FakeProcess"] | None = None) -> None:
                self.pid = pid
                self._children = children or []
                self.actions: list[str] = []

            def children(self, recursive: bool = False) -> list["FakeProcess"]:
                self.assert_recursive = recursive
                return self._children

            def suspend(self) -> None:
                self.actions.append("suspend")

            def resume(self) -> None:
                self.actions.append("resume")

        child = FakeProcess(22)
        root = FakeProcess(11, [child])
        with patch.object(toki_core.psutil, "Process", return_value=root):
            self.assertEqual(set_process_tree_paused(11, True), [22, 11])
            self.assertEqual(set_process_tree_paused(11, False), [22, 11])
        self.assertEqual(child.actions, ["suspend", "resume"])
        self.assertEqual(root.actions, ["suspend", "resume"])

    def test_retry_contract_resets_previous_range(self) -> None:
        source = DownloadJob(
            job_id="old",
            url="https://newtoki1.org/manhwa/34360",
            output_dir=r"C:\Manga",
            start=10,
            last=24,
        )
        retry = toki_core.retry_job_parameters(source)
        self.assertEqual(retry["url"], source.url)
        self.assertIsNone(retry["start"])
        self.assertIsNone(retry["last"])
        self.assertEqual(retry["scan_mode"], "full")

    def test_youtube_work_identity_and_retry_contract_are_provider_scoped(self) -> None:
        first = toki_core.build_work_key(
            "https://www.youtube.com/watch?v=video-one&list=playlist-one"
        )
        second = toki_core.build_work_key(
            "https://youtu.be/video-two"
        )
        playlist = toki_core.build_work_key(
            "https://www.youtube.com/playlist?list=playlist-one"
        )
        self.assertEqual(first, "youtube:video:video-one")
        self.assertEqual(second, "youtube:video:video-two")
        self.assertEqual(playlist, "youtube:playlist:playlist-one")
        self.assertEqual(
            toki_core.build_work_key("https://www.youtube.com/@OpenAI/Videos"),
            "youtube:channel:/@openai/videos",
        )
        source = DownloadJob(
            job_id="youtube-old",
            url="https://www.youtube.com/watch?v=video-one",
            output_dir=r"C:\Video",
            simulation=True,
        )
        retry = toki_core.retry_job_parameters(source)
        self.assertTrue(retry["simulation"])
        self.assertFalse(retry["external_request_confirmed"])
        self.assertEqual(DownloadRun.from_job(source).operation, "youtube_simulation")

    def test_youtube_worker_arguments_require_confirmation_and_exclude_unrelated_config(self) -> None:
        live = DownloadJob(
            job_id="youtube-live",
            url="https://www.youtube.com/watch?v=video-one",
            output_dir=r"C:\Video",
        )
        with self.assertRaisesRegex(ValueError, "명시적 확인"):
            toki_core.build_youtube_worker_args(live, default_config())
        live.external_request_confirmed = True
        arguments = toki_core.build_youtube_worker_args(
            live,
            {**default_config(), "proxyUrl": "https://secret.invalid"},
        )
        self.assertEqual(Path(arguments[0]).name, "youtube_worker.py")
        config = json.loads(arguments[arguments.index("--config-json") + 1])
        self.assertNotIn("proxyUrl", config)
        simulated = DownloadJob(
            job_id="youtube-sim",
            url="https://www.youtube.com/watch?v=video-one",
            output_dir=r"C:\Video",
            simulation=True,
        )
        self.assertIn("--simulate", toki_core.build_youtube_worker_args(simulated, default_config()))

    def test_run_log_filters_current_and_rotated_files(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            log_path = Path(folder) / "gui.log"
            rotated_path = log_path.with_suffix(".log.1")
            rotated_path.write_text(
                "2026-01-01 [INFO] [run-a] 이전 로그\n"
                "2026-01-01 [INFO] [run-b] 다른 로그\n",
                encoding="utf-8",
            )
            log_path.write_text(
                "2026-01-02 [INFO] [run-a] 현재 로그 1\n"
                "2026-01-02 [ERROR] [run-a] 현재 로그 2\n",
                encoding="utf-8",
            )
            with patch.object(toki_core, "LOG_PATH", log_path):
                self.assertEqual(
                    read_run_log("run-a", count=2),
                    [
                        "2026-01-02 [INFO] [run-a] 현재 로그 1",
                        "2026-01-02 [ERROR] [run-a] 현재 로그 2",
                    ],
                )
                self.assertEqual(len(read_run_log("run-a", count=10)), 3)


class JobRepositoryTests(unittest.TestCase):
    def test_duplicate_image_sha256_scan_uses_bounded_threads_and_preserves_files(self) -> None:
        output_path = Path(self.temp_dir.name) / "work"
        episode_one = output_path / "0001 first"
        episode_two = output_path / "0002 second"
        episode_one.mkdir(parents=True)
        episode_two.mkdir(parents=True)
        first = episode_one / "001.jpg"
        duplicate = episode_two / "002.png"
        unique = episode_two / "003.webp"
        first.write_bytes(b"same-image-bytes")
        duplicate.write_bytes(b"same-image-bytes")
        unique.write_bytes(b"different-image-bytes")
        job = DownloadJob(
            job_id="image-duplicates",
            url="https://newtoki1.org/manhwa/9901",
            output_dir=self.temp_dir.name,
            output_path=str(output_path),
            title="이미지 중복 작품",
        )
        save_jobs([job])

        report = find_duplicate_images(job.job_id, algorithm="sha256", max_workers=99)

        self.assertTrue(report["ok"])
        self.assertEqual(report["pool"]["kind"], "thread")
        self.assertLessEqual(report["pool"]["workers"], 8)
        self.assertEqual(report["scannedImages"], 3)
        self.assertEqual(report["duplicateGroupCount"], 1)
        self.assertEqual(report["duplicateImageCount"], 2)
        self.assertEqual(set(report["groups"][0]["paths"]), {str(first.resolve()), str(duplicate.resolve())})
        self.assertTrue(report["readOnly"])
        self.assertFalse(report["filesChanged"])
        self.assertEqual(unique.read_bytes(), b"different-image-bytes")

    def test_duplicate_work_scan_reports_title_author_and_path_without_changes(self) -> None:
        shared_path = str(Path(self.temp_dir.name) / "shared")
        jobs = [
            DownloadJob(
                job_id="duplicate-a",
                url="https://newtoki1.org/manhwa/8801",
                output_dir=self.temp_dir.name,
                output_path=shared_path,
                title="같은 작품",
                author="같은 작가",
            ),
            DownloadJob(
                job_id="duplicate-b",
                url="https://newtoki1.org/manhwa/8802",
                output_dir=self.temp_dir.name,
                output_path=shared_path,
                title="같은 작품",
                author="같은 작가",
            ),
            DownloadJob(
                job_id="unique",
                url="https://newtoki1.org/manhwa/8803",
                output_dir=self.temp_dir.name,
                title="다른 작품",
                author="다른 작가",
            ),
        ]
        save_jobs(jobs)

        report = find_duplicate_works()

        self.assertEqual(report["scannedWorks"], 3)
        self.assertEqual(report["duplicateGroupCount"], 2)
        self.assertEqual(report["duplicateWorkCount"], 2)
        self.assertEqual(
            {group["reason"] for group in report["groups"]},
            {"same_title_author", "same_output_path"},
        )
        self.assertTrue(report["readOnly"])
        self.assertFalse(report["metadataChanged"])
        self.assertFalse(report["downloadFilesChanged"])
        self.assertEqual(count_jobs(), 3)

    def test_integrated_search_scans_ten_thousand_records_with_bounded_page(self) -> None:
        jobs = [
            DownloadJob(
                job_id=f"search-{index}",
                url=f"https://newtoki1.org/manhwa/{50000 + index}",
                output_dir=r"C:\Manga",
                title=f"대량 작품 {index}",
                author="유일작가" if index == 9876 else f"작가 {index % 100}",
                group=f"메타그룹 {index % 20}",
            )
            for index in range(10_000)
        ]
        save_jobs(jobs)
        started = time.perf_counter()
        result = load_jobs_page(query="유일작가", limit=50)
        elapsed_ms = (time.perf_counter() - started) * 1000

        self.assertEqual([job.job_id for job in result], ["search-9876"])
        self.assertEqual(count_jobs(query="유일작가"), 1)
        self.assertLess(elapsed_ms, 2_000)

    def test_work_collections_create_rename_assign_and_unassign_without_file_changes(self) -> None:
        job = DownloadJob(
            job_id="group-job",
            url="https://newtoki1.org/manhwa/7788",
            output_dir=self.temp_dir.name,
            group="N／A",
        )
        marker = Path(self.temp_dir.name) / "download.txt"
        marker.write_text("keep", encoding="utf-8")
        save_jobs([job])

        created = create_work_collection("나중에 읽기")
        self.assertEqual(created["memberCount"], 0)
        renamed = rename_work_collection(created["groupId"], "즐겨찾기")
        self.assertEqual(renamed["name"], "즐겨찾기")
        assigned = assign_job_to_collection(job.job_id, created["groupId"])
        self.assertEqual(assigned["group"]["name"], "즐겨찾기")
        self.assertFalse(assigned["metadataChanged"])
        self.assertFalse(assigned["downloadFilesChanged"])
        self.assertEqual(work_collection_for_job(job.job_id)["groupId"], created["groupId"])
        self.assertEqual(list_work_collections()[0]["memberCount"], 1)
        self.assertEqual(load_job_by_work_key(job.work_key).group, "N／A")
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

        unassigned = assign_job_to_collection(job.job_id, None)
        self.assertIsNone(unassigned["group"])
        self.assertIsNone(work_collection_for_job(job.job_id))
        self.assertEqual(list_work_collections()[0]["memberCount"], 0)

        with self.assertRaises(ValueError):
            create_work_collection("즐겨찾기")

    def test_job_snapshot_export_preview_and_additive_import_preserve_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_db = root / "source.db"
            target_db = root / "target.db"
            snapshot_path = root / "jobs.json"
            work_folder = root / "downloaded-work"
            work_folder.mkdir()
            marker = work_folder / "keep.txt"
            marker.write_text("preserve", encoding="utf-8")
            source_job = DownloadJob(
                job_id="job-source",
                url="https://newtoki1.org/manhwa/12345",
                output_dir=str(root),
                output_path=str(work_folder),
                state="실행 중",
                title="스냅샷 작품",
            )
            source_run = DownloadRun(
                run_id="run-source",
                work_key=source_job.work_key,
                state="실행 중",
                process_pid=1234,
            )
            save_jobs([source_job], database_path=source_db)
            save_runs([source_run], database_path=source_db)

            exported = export_jobs_snapshot(snapshot_path, database_path=source_db)
            self.assertEqual(exported["jobCount"], 1)
            self.assertEqual(exported["runCount"], 1)

            preview = import_jobs_snapshot(snapshot_path, database_path=target_db)
            self.assertFalse(preview["executed"])
            self.assertEqual(preview["pendingJobs"], 1)
            self.assertEqual(load_jobs_page(database_path=target_db), [])

            imported = import_jobs_snapshot(
                snapshot_path, execute=True, database_path=target_db
            )
            restored_jobs = load_jobs_page(database_path=target_db)
            self.assertEqual(imported["importedJobs"], 1)
            self.assertEqual(imported["importedRuns"], 1)
            self.assertEqual(restored_jobs[0].state, "중지됨")
            self.assertEqual(marker.read_text(encoding="utf-8"), "preserve")
            self.assertFalse(imported["downloadFilesChanged"])

            duplicate = import_jobs_snapshot(
                snapshot_path, execute=True, database_path=target_db
            )
            self.assertEqual(duplicate["importedJobs"], 0)
            self.assertEqual(duplicate["importedRuns"], 0)
            self.assertEqual(duplicate["skippedExistingWorks"], 1)

    def test_run_retention_preserves_latest_and_active_records(self) -> None:
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        runs = [
            DownloadRun(
                run_id="latest", work_key="work:one", state="완료", created_at=now
            ),
            DownloadRun(
                run_id="old-one", work_key="work:one", state="완료",
                created_at="2020-01-01T00:00:00+09:00",
            ),
            DownloadRun(
                run_id="old-two", work_key="work:one", state="오류",
                created_at="2019-01-01T00:00:00+09:00",
            ),
            DownloadRun(
                run_id="active-old", work_key="work:one", state="실행 중",
                created_at="2018-01-01T00:00:00+09:00",
            ),
            DownloadRun(
                run_id="only-old", work_key="work:two", state="완료",
                created_at="2017-01-01T00:00:00+09:00",
            ),
        ]
        save_runs(runs)

        preview = cleanup_run_history(
            max_per_work=2, max_age_days=30, execute=False
        )
        self.assertEqual(preview["candidateRuns"], 2)
        self.assertEqual(count_runs(), 5)

        executed = cleanup_run_history(
            max_per_work=2, max_age_days=30, execute=True
        )
        self.assertTrue(executed["ok"])
        self.assertEqual(executed["removedRuns"], 2)
        self.assertEqual(count_runs(), 3)
        self.assertIsNotNone(load_run("latest"))
        self.assertIsNotNone(load_run("active-old"))
        self.assertIsNotNone(load_run("only-old"))

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "jobs.db"
        self.path_patch = patch.object(toki_core, "JOB_DB_PATH", self.database_path)
        self.path_patch.start()
        toki_core._INITIALIZED_JOB_DBS.clear()
        toki_core._DATABASE_MIGRATION_REPORTS.clear()

    def tearDown(self) -> None:
        toki_core._INITIALIZED_JOB_DBS.clear()
        toki_core._DATABASE_MIGRATION_REPORTS.clear()
        self.path_patch.stop()
        self.temp_dir.cleanup()

    def test_same_work_upserts_one_record(self) -> None:
        first = DownloadJob(
            job_id="first",
            url="https://newtoki1.org/manhwa/34360",
            output_dir=r"C:\Manga",
            title="이전 제목",
        )
        latest = DownloadJob(
            job_id="latest",
            url="https://newtoki99.org/manhwa/34360",
            output_dir=r"C:\Manga",
            title="최신 제목",
        )
        save_jobs([first])
        save_jobs([latest])
        self.assertEqual(count_jobs(), 1)
        loaded = load_job_by_work_key("manatoki:34360")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.job_id, "latest")
        self.assertEqual(loaded.title, "최신 제목")

    def test_database_diagnostics_verify_all_list_query_indexes(self) -> None:
        save_jobs(
            [
                DownloadJob(
                    job_id=f"diagnostic-{index}",
                    url=f"https://newtoki1.org/manhwa/{8100 + index}",
                    output_dir=r"C:\Manga",
                    title=f"진단 작품 {index}",
                    state="완료" if index % 2 else "오류",
                    progress=index * 10,
                    pinned=index == 2,
                )
                for index in range(4)
            ]
        )
        report = job_database_diagnostics()

        self.assertTrue(report["ok"])
        self.assertEqual(report["jobCount"], 4)
        self.assertEqual(report["missingIndexes"], [])
        self.assertEqual(len(report["queries"]), 6)
        self.assertTrue(all(plan["usesIndex"] for plan in report["queries"]))
        self.assertTrue(all(not plan["temporarySort"] for plan in report["queries"]))

    def test_synthetic_database_benchmark_is_isolated_and_writes_report(self) -> None:
        report_path = Path(self.temp_dir.name) / "한글 경로" / "benchmark.json"
        report = run_job_database_benchmark(
            [100, 1_000], page_size=50, report_path=report_path
        )

        self.assertTrue(report["ok"])
        self.assertEqual(report["sizes"], [100, 1_000])
        self.assertTrue(report["temporaryDatabaseRemoved"])
        self.assertTrue(report_path.is_file())
        self.assertEqual([item["count"] for item in report["results"]], [100, 1_000])
        self.assertTrue(all(item["firstPageMs"] <= 2_000 for item in report["results"]))
        self.assertEqual(count_jobs(), 0)

    def test_stability_recovery_test_forces_child_exit_and_uses_isolated_db(self) -> None:
        report_path = Path(self.temp_dir.name) / "stability.json"

        report = run_stability_recovery_test(
            records=100,
            cycles=2,
            report_path=report_path,
        )

        self.assertTrue(report["ok"])
        self.assertEqual(report["integrity"], "ok")
        self.assertTrue(report["forcedTermination"]["recoveryPassed"])
        self.assertEqual(report["forcedTermination"]["recoveredJobIds"], ["forced-crash"])
        self.assertEqual(report["forcedTermination"]["recoveredRunIds"], ["forced-crash"])
        self.assertTrue(report["temporaryDatabaseRemoved"])
        self.assertTrue(report_path.is_file())
        self.assertEqual(count_jobs(), 0)

    def test_restart_recovery_scans_beyond_first_history_page(self) -> None:
        interrupted = DownloadJob(
            job_id="interrupted",
            url="https://newtoki1.org/manhwa/9000",
            output_dir=r"C:\Manga",
            state="실행 중",
            progress=37,
        )
        save_jobs([interrupted])
        save_runs([DownloadRun.from_job(interrupted)])
        completed = [
            DownloadJob(
                job_id=f"completed-{index}",
                url=f"https://newtoki1.org/manhwa/{10000 + index}",
                output_dir=r"C:\Manga",
                state="완료",
                progress=100,
            )
            for index in range(1000)
        ]
        save_jobs(completed)
        self.assertNotIn(
            interrupted.job_id,
            {job.job_id for job in load_jobs_page(limit=200)},
        )

        preview = recover_interrupted_jobs(execute=False)
        self.assertFalse(preview["executed"])
        self.assertEqual(preview["jobIds"], [interrupted.job_id])
        self.assertEqual(toki_core.load_job_by_id(interrupted.job_id).state, "실행 중")
        self.assertEqual(load_run(interrupted.job_id).state, "실행 중")

        result = recover_interrupted_jobs()

        self.assertTrue(result["executed"])
        self.assertEqual(result["jobIds"], [interrupted.job_id])
        self.assertEqual(result["runIds"], [interrupted.job_id])
        recovered_job = toki_core.load_job_by_id(interrupted.job_id)
        recovered_run = load_run(interrupted.job_id)
        self.assertEqual(recovered_job.state, "중지됨")
        self.assertEqual(recovered_job.progress, 37)
        self.assertIn("이전 GUI", recovered_job.error)
        self.assertEqual(recovered_run.state, "중지됨")
        self.assertTrue(recovered_run.finished_at)
        self.assertEqual(count_jobs(state="완료"), 1000)

    def test_same_work_keeps_multiple_execution_runs(self) -> None:
        first = DownloadJob(
            job_id="run-first",
            url="https://newtoki1.org/manhwa/34360",
            output_dir=r"C:\Manga",
            state="완료",
        )
        second = DownloadJob(
            job_id="run-second",
            url="https://newtoki99.org/manhwa/34360",
            output_dir=r"C:\Manga",
            state="오류",
        )
        save_jobs([first])
        save_runs([DownloadRun.from_job(first)])
        save_jobs([second])
        save_runs([DownloadRun.from_job(second)])
        self.assertEqual(count_jobs(), 1)
        self.assertEqual(count_runs(first.work_key), 2)
        self.assertEqual(
            {run.run_id for run in load_runs_page(first.work_key)},
            {"run-first", "run-second"},
        )

    def test_existing_job_database_backfills_one_legacy_run(self) -> None:
        job = DownloadJob(
            job_id="legacy-run",
            url="https://newtoki1.org/manhwa/34361",
            output_dir=r"C:\Manga",
            state="완료",
            progress=100,
        )
        connection = sqlite3.connect(self.database_path)
        try:
            connection.execute(
                """
                CREATE TABLE jobs (
                    job_id TEXT PRIMARY KEY, work_key TEXT NOT NULL, title TEXT NOT NULL,
                    state TEXT NOT NULL, progress INTEGER NOT NULL, url TEXT NOT NULL,
                    pinned INTEGER NOT NULL, tag_color TEXT NOT NULL, created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL, payload TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    job.job_id,
                    job.work_key,
                    job.title,
                    job.state,
                    job.progress,
                    job.url,
                    0,
                    "",
                    job.created_at,
                    job.created_at,
                    json.dumps(job.to_dict(), ensure_ascii=False),
                ),
            )
            connection.commit()
        finally:
            connection.close()
        self.assertEqual(count_runs(job.work_key), 1)
        migrated = load_run(job.job_id)
        self.assertIsNotNone(migrated)
        self.assertEqual(migrated.state, "완료")
        self.assertEqual(migrated.progress, 100)
        schema = toki_core.database_schema_status(self.database_path)
        self.assertEqual(schema["version"], toki_core.JOB_DB_SCHEMA_VERSION)
        self.assertEqual(
            [item["version"] for item in schema["migrations"]], [1, 2, 3, 4]
        )
        self.assertTrue(Path(schema["lastMigration"]["backupPath"]).is_file())

    def test_future_database_version_is_rejected_without_rewrite(self) -> None:
        connection = sqlite3.connect(self.database_path)
        try:
            connection.execute("CREATE TABLE sentinel(value TEXT NOT NULL)")
            connection.execute("INSERT INTO sentinel(value) VALUES ('keep')")
            connection.execute(
                f"PRAGMA user_version = {toki_core.JOB_DB_SCHEMA_VERSION + 1}"
            )
            connection.commit()
        finally:
            connection.close()

        with self.assertRaises(RuntimeError):
            toki_core.apply_database_migrations(self.database_path)

        connection = sqlite3.connect(self.database_path)
        try:
            value = connection.execute("SELECT value FROM sentinel").fetchone()[0]
            version = connection.execute("PRAGMA user_version").fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(value, "keep")
        self.assertEqual(version, toki_core.JOB_DB_SCHEMA_VERSION + 1)
        self.assertFalse(
            self.database_path.with_suffix(
                self.database_path.suffix + f".pre-v{toki_core.JOB_DB_SCHEMA_VERSION}.bak"
            ).exists()
        )

    def test_run_updates_do_not_duplicate_and_pages_are_bounded(self) -> None:
        work_key = "manatoki:7001"
        runs = [
            DownloadRun(run_id=f"run-{index}", work_key=work_key)
            for index in range(15)
        ]
        save_runs(runs)
        runs[0].state = "완료"
        runs[0].progress = 100
        save_runs([runs[0]])
        self.assertEqual(count_runs(work_key), 15)
        self.assertEqual(len(load_runs_page(work_key, limit=10, offset=0)), 10)
        self.assertEqual(len(load_runs_page(work_key, limit=10, offset=10)), 5)
        loaded = load_run("run-0")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.state, "완료")
        self.assertEqual(loaded.progress, 100)

    def test_user_note_persists_on_work_record(self) -> None:
        job = DownloadJob(
            job_id="noted",
            url="https://newtoki1.org/manhwa/7002",
            output_dir=r"C:\Manga",
        )
        save_jobs([job])
        update_job_note(job.job_id, "다음에 10화부터 확인")
        loaded = load_job_by_work_key(job.work_key)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.user_note, "다음에 10화부터 확인")

    def test_existing_metadata_file_hydrates_work_fields(self) -> None:
        output_folder = Path(self.temp_dir.name) / "hydrated-work"
        output_folder.mkdir()
        metadata_path = output_folder / "metadata.json"
        metadata_path.write_text(
            json.dumps(
                {
                    "author": "작가 A",
                    "group": "그룹 B",
                    "coverUrl": "https://example.test/cover.jpg",
                    "coverFile": "cover.jpg",
                    "source": {"site": "manatoki"},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        job = DownloadJob(
            job_id="hydrate",
            url="https://newtoki1.org/manhwa/7003",
            output_dir=self.temp_dir.name,
            output_path=str(output_folder),
        )
        self.assertTrue(hydrate_job_metadata(job))
        self.assertEqual(job.author, "작가 A")
        self.assertEqual(job.group, "그룹 B")
        self.assertEqual(job.site, "manatoki")
        self.assertEqual(job.metadata_path, str(metadata_path.resolve()))

    def test_cover_path_resolution_requires_existing_file(self) -> None:
        cover = Path(self.temp_dir.name) / "cover.jpg"
        cover.write_bytes(b"cover")
        job = DownloadJob(
            job_id="cover",
            url="https://newtoki1.org/manhwa/7004",
            output_dir=self.temp_dir.name,
            cover_path=str(cover),
        )
        self.assertEqual(resolve_cover_path(job), str(cover.resolve()))
        cover.unlink()
        with self.assertRaises(FileNotFoundError):
            resolve_cover_path(job)

    def test_page_loading_is_bounded(self) -> None:
        jobs = [
            DownloadJob(
                job_id=f"job-{index}",
                url=f"https://newtoki1.org/manhwa/{1000 + index}",
                output_dir=r"C:\Manga",
            )
            for index in range(25)
        ]
        save_jobs(jobs)
        self.assertEqual(len(load_jobs_page(limit=10, offset=0)), 10)
        self.assertEqual(len(load_jobs_page(limit=10, offset=20)), 5)

    def test_query_state_filter_and_sort(self) -> None:
        jobs = [
            DownloadJob(
                job_id="alpha",
                url="https://newtoki1.org/manhwa/2001",
                output_dir=r"C:\Manga",
                title="알파 작품",
                author="작가A",
                group="그룹A",
                state="완료",
                progress=100,
            ),
            DownloadJob(
                job_id="beta",
                url="https://newtoki1.org/manhwa/2002",
                output_dir=r"C:\Manga",
                title="베타 작품",
                author="작가B",
                group="그룹B",
                state="오류",
                progress=40,
            ),
        ]
        save_jobs(jobs)
        self.assertEqual(count_jobs(query="작가B"), 1)
        self.assertEqual(load_jobs_page(query="그룹B")[0].job_id, "beta")
        self.assertEqual(load_jobs_page(query="beta")[0].job_id, "beta")
        collection = create_work_collection("보관 작품")
        assign_job_to_collection("beta", collection["groupId"])
        self.assertEqual(load_jobs_page(query="보관 작품")[0].job_id, "beta")
        self.assertEqual(load_jobs_page(state="완료")[0].job_id, "alpha")
        sorted_jobs = load_jobs_page(sort="progress")
        self.assertEqual([job.job_id for job in sorted_jobs], ["alpha", "beta"])
        with self.assertRaises(ValueError):
            load_jobs_page(sort="invalid")

    def test_pin_and_color_tag_persist_and_sort_first(self) -> None:
        normal = DownloadJob(
            job_id="normal",
            url="https://newtoki1.org/manhwa/3001",
            output_dir=r"C:\Manga",
            title="가 작품",
        )
        pinned = DownloadJob(
            job_id="pinned",
            url="https://newtoki1.org/manhwa/3002",
            output_dir=r"C:\Manga",
            title="나 작품",
        )
        save_jobs([normal, pinned])
        updated = update_job_markers("pinned", pinned=True, tag_color="purple")
        self.assertTrue(updated.pinned)
        self.assertEqual(updated.tag_color, "purple")
        self.assertEqual(load_jobs_page(sort="title")[0].job_id, "pinned")
        with self.assertRaises(ValueError):
            update_job_markers("pinned", tag_color="unknown")

    def test_delete_record_never_deletes_download_files(self) -> None:
        output_folder = Path(self.temp_dir.name) / "downloaded-work"
        output_folder.mkdir()
        image = output_folder / "001.jpg"
        image.write_bytes(b"image")
        job = DownloadJob(
            job_id="delete-me",
            url="https://newtoki1.org/manhwa/4001",
            output_dir=self.temp_dir.name,
            output_path=str(output_folder),
            state="완료",
        )
        save_jobs([job])
        save_runs([DownloadRun.from_job(job)])
        deleted = delete_job_record(job.job_id)
        self.assertEqual(deleted.job_id, job.job_id)
        self.assertEqual(count_jobs(), 0)
        self.assertEqual(count_runs(job.work_key), 0)
        self.assertTrue(image.is_file())

    def test_folder_move_dry_run_and_execute_preserve_files_and_update_paths(self) -> None:
        workspace = Path(self.temp_dir.name)
        source = workspace / "old-root" / "마나토끼" / "[작가][그룹] 작품"
        source.mkdir(parents=True)
        metadata = source / "metadata.json"
        cover = source / "cover.jpg"
        episode = source / "0001 1화" / "image0000.jpg"
        episode.parent.mkdir()
        metadata.write_text("{}", encoding="utf-8")
        cover.write_bytes(b"cover")
        episode.write_bytes(b"image")
        job = DownloadJob(
            job_id="move-work",
            url="https://newtoki1.org/manhwa/6001",
            output_dir=str(workspace / "old-root"),
            output_path=str(source),
            metadata_path=str(metadata),
            cover_path=str(cover),
            state="완료",
        )
        save_jobs([job])

        target_root = workspace / "new root 한글"
        plan = plan_job_folder_move(job.job_id, str(target_root))
        destination = target_root / "마나토끼" / source.name
        self.assertEqual(plan["destination"], str(destination.resolve()))
        self.assertTrue(plan["canExecute"])
        self.assertFalse(plan["executed"])
        self.assertTrue(episode.is_file())
        self.assertFalse(destination.exists())

        result = move_job_folder(job.job_id, str(target_root))
        moved = toki_core.load_job_by_id(job.job_id)
        self.assertTrue(result["moved"])
        self.assertFalse(source.exists())
        self.assertTrue((destination / "0001 1화" / "image0000.jpg").is_file())
        self.assertEqual(moved.output_dir, str(target_root.resolve()))
        self.assertEqual(moved.output_path, str(destination.resolve()))
        self.assertEqual(moved.metadata_path, str(destination / "metadata.json"))
        self.assertEqual(moved.cover_path, str(destination / "cover.jpg"))

    def test_folder_move_rejects_destination_collision_and_active_job(self) -> None:
        workspace = Path(self.temp_dir.name)
        source = workspace / "old" / "마나토끼" / "작품"
        source.mkdir(parents=True)
        job = DownloadJob(
            job_id="move-conflict",
            url="https://newtoki1.org/manhwa/6002",
            output_dir=str(workspace / "old"),
            output_path=str(source),
            state="완료",
        )
        save_jobs([job])
        target = workspace / "target"
        (target / "마나토끼" / "작품").mkdir(parents=True)
        plan = plan_job_folder_move(job.job_id, str(target))
        self.assertTrue(plan["conflict"])
        self.assertFalse(plan["canExecute"])
        with self.assertRaises(FileExistsError):
            move_job_folder(job.job_id, str(target))

        job.state = "실행 중"
        save_jobs([job])
        with self.assertRaises(ValueError):
            plan_job_folder_move(job.job_id, str(workspace / "other"))

    def test_local_metadata_rebuild_previews_backs_up_and_recovers_core_fields(self) -> None:
        workspace = Path(self.temp_dir.name)
        output = workspace / "마나토끼" / "[작가 A][그룹 B] 작품 제목"
        output.mkdir(parents=True)
        metadata_path = output / "metadata.json"
        metadata_path.write_text(
            json.dumps(
                {
                    "description": "기존 설명",
                    "genres": ["판타지"],
                    "episodeCount": 77,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        cover = output / "cover.png"
        cover.write_bytes(b"cover")
        job = DownloadJob(
            job_id="rebuild-meta",
            url="https://newtoki1.org/manhwa/6100",
            output_dir=str(workspace),
            output_path=str(output),
            cover_path=str(cover),
            cover_url="https://example.test/cover.png",
            site="manatoki",
            state="완료",
        )
        save_jobs([job])

        preview = plan_metadata_rebuild(job.job_id)
        self.assertFalse(preview["executed"])
        self.assertEqual(preview["metadata"]["title"], "작품 제목")
        self.assertEqual(preview["metadata"]["author"], "작가 A")
        self.assertEqual(preview["metadata"]["group"], "그룹 B")
        self.assertEqual(preview["metadata"]["description"], "기존 설명")
        self.assertEqual(preview["metadata"]["episodeCount"], 77)

        result = rebuild_job_metadata(job.job_id)
        rebuilt = json.loads(metadata_path.read_text(encoding="utf-8"))
        backup = json.loads(metadata_path.with_suffix(".json.bak").read_text(encoding="utf-8"))
        loaded = toki_core.load_job_by_id(job.job_id)
        self.assertTrue(result["backupCreated"])
        self.assertEqual(backup["description"], "기존 설명")
        self.assertEqual(rebuilt["source"]["workId"], "6100")
        self.assertEqual(rebuilt["coverFile"], "cover.png")
        self.assertEqual(loaded.metadata_path, str(metadata_path.resolve()))
        self.assertEqual(loaded.author, "작가 A")

    def test_manifestless_modern_folders_recover_in_natural_order_and_report_missing_state(
        self,
    ) -> None:
        workspace = Path(self.temp_dir.name)
        work_title = "복구 작품"
        output = workspace / "마나토끼" / "[작가][그룹] 다른 루트 제목"
        folder_names = [
            f"{work_title} 1~5화",
            f"{work_title} 141.5화",
            f"{work_title} 287화",
        ]
        valid_jpeg = b"\xff\xd8\xff" + b"image" + b"\xff\xd9"
        for folder_name in folder_names:
            episode = output / folder_name
            episode.mkdir(parents=True)
            (episode / "0000.jpg").write_bytes(valid_jpeg)

        unrelated = output / "사용자 메모"
        unrelated.mkdir()
        (unrelated / "0000.jpg").write_bytes(valid_jpeg)
        prefixed_without_image = output / f"{work_title} 이미지 없는 메모"
        prefixed_without_image.mkdir()
        (prefixed_without_image / "note.txt").write_text("memo", encoding="utf-8")
        (output / "metadata.json").write_text(
            json.dumps(
                {"title": unicodedata.normalize("NFD", work_title)},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        job = DownloadJob(
            job_id="manifestless-modern-recovery",
            url="https://newtoki1.org/manhwa/7400",
            output_dir=str(workspace),
            output_path=str(output),
            state="완료",
        )
        save_jobs([job])

        discovered = discover_episode_folders(output)
        self.assertEqual([entry.number for entry in discovered], [1, 2, 3])
        self.assertEqual([entry.folder_name for entry in discovered], folder_names)
        self.assertEqual(
            [entry.display_title for entry in discovered],
            folder_names,
        )
        self.assertTrue(
            all(entry.discovery == "modern-recovery" for entry in discovered)
        )
        self.assertTrue(all(entry.number_inferred for entry in discovered))
        self.assertEqual(len({entry.number for entry in discovered}), 3)
        self.assertNotIn(unrelated.resolve(), {entry.path for entry in discovered})
        self.assertNotIn(
            prefixed_without_image.resolve(),
            {entry.path for entry in discovered},
        )

        verification = verify_job_files(job.job_id)
        self.assertFalse(verification["healthy"])
        self.assertEqual(verification["summary"]["episodeFolders"], 3)
        self.assertEqual(verification["summary"]["images"], 3)
        self.assertIn(
            "state_missing",
            {issue["kind"] for issue in verification["issues"]},
        )

    def test_metadata_rebuild_persists_modern_recovery_when_both_manifests_are_damaged(
        self,
    ) -> None:
        workspace = Path(self.temp_dir.name)
        work_title = "루트 복구 작품"
        output = workspace / "마나토끼" / f"[작가][그룹] {work_title}"
        folder_names = [
            f"{work_title} 1~5화",
            f"{work_title} 141.5화",
            f"{work_title} 287화",
        ]
        valid_png = b"\x89PNG\r\n\x1a\n" + b"image" + b"IEND"
        for folder_name in folder_names:
            episode = output / folder_name
            episode.mkdir(parents=True)
            (episode / "0000.png").write_bytes(valid_png)
        unrelated = output / "임의 사용자 폴더"
        unrelated.mkdir()
        (unrelated / "0000.png").write_bytes(valid_png)
        metadata_path = output / "metadata.json"
        metadata_path.write_text(
            json.dumps({"episodes": {"broken": True}}, ensure_ascii=False),
            encoding="utf-8",
        )
        (output / ".toki-state.json").write_text(
            json.dumps(
                {
                    "version": 2,
                    "completedEpisodes": [1, 2, 3],
                    "episodes": "broken",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        job = DownloadJob(
            job_id="damaged-manifest-modern-recovery",
            url="https://newtoki1.org/manhwa/7401",
            output_dir=str(workspace),
            output_path=str(output),
            state="완료",
        )
        save_jobs([job])

        preview = plan_metadata_rebuild(job.job_id)
        self.assertEqual(preview["episodeFolderCount"], 3)
        self.assertEqual(preview["recoveredEpisodeCount"], 3)
        self.assertEqual(
            [episode["number"] for episode in preview["metadata"]["episodes"]],
            [1, 2, 3],
        )
        self.assertTrue(
            all(
                episode.get("numberInferred") is True
                for episode in preview["metadata"]["episodes"]
            )
        )
        self.assertEqual(
            [episode["folderName"] for episode in preview["metadata"]["episodes"]],
            folder_names,
        )
        self.assertEqual(
            [episode["displayTitle"] for episode in preview["metadata"]["episodes"]],
            folder_names,
        )
        self.assertNotIn(
            unrelated.name,
            {episode["folderName"] for episode in preview["metadata"]["episodes"]},
        )

        result = rebuild_job_metadata(job.job_id)
        rebuilt = json.loads(metadata_path.read_text(encoding="utf-8"))
        self.assertTrue(result["executed"])
        self.assertEqual(
            [episode["folderName"] for episode in rebuilt["episodes"]],
            folder_names,
        )
        self.assertTrue(
            all(episode.get("numberInferred") is True for episode in rebuilt["episodes"])
        )
        rediscovered = discover_episode_folders(output)
        self.assertEqual(
            [entry.folder_name for entry in rediscovered],
            folder_names,
        )
        self.assertTrue(all(entry.discovery == "metadata" for entry in rediscovered))
        self.assertTrue(all(entry.number_inferred for entry in rediscovered))

    def test_file_verification_reports_healthy_episode_and_image_inventory(self) -> None:
        workspace = Path(self.temp_dir.name)
        output = workspace / "마나토끼" / "[작가][그룹] 정상 작품"
        for number in (1, 2):
            episode = output / f"{number:04d} {number}화"
            episode.mkdir(parents=True)
            (episode / "image0000.jpg").write_bytes(
                b"\xff\xd8\xff" + b"valid-image" + b"\xff\xd9"
            )
        (output / "metadata.json").write_text("{}", encoding="utf-8")
        (output / ".toki-state.json").write_text(
            json.dumps({"version": 1, "completedEpisodes": [1, 2]}),
            encoding="utf-8",
        )
        job = DownloadJob(
            job_id="verify-healthy",
            url="https://newtoki1.org/manhwa/6200",
            output_dir=str(workspace),
            output_path=str(output),
            state="완료",
        )
        save_jobs([job])

        result = verify_job_files(job.job_id)
        self.assertTrue(result["healthy"])
        self.assertTrue(result["readOnly"])
        self.assertEqual(result["summary"]["episodeFolders"], 2)
        self.assertEqual(result["summary"]["images"], 2)
        self.assertEqual(result["summary"]["issueCount"], 0)

    def test_state_v2_discovers_full_title_folders_for_all_file_consumers(self) -> None:
        workspace = Path(self.temp_dir.name)
        output = workspace / "마나토끼" / "[작가][그룹] 신형 작품"
        folder_names = ["신형 작품 전체 제목 1화", "신형 작품 전체 제목 2화"]
        valid_jpeg = b"\xff\xd8\xff" + b"image" + b"\xff\xd9"
        for folder_name in folder_names:
            episode = output / folder_name
            episode.mkdir(parents=True)
            (episode / "0000.jpg").write_bytes(valid_jpeg)
        episodes = [
            {
                "number": number,
                "sourceId": f"/manhwa/7000/episode-{number}",
                "sourceUrl": f"https://newtoki1.org/manhwa/7000/episode-{number}",
                "sourceTitle": f"신형 작품 전체 제목 {number}화",
                "displayTitle": f"신형 작품 전체 제목 {number}화",
                "folderName": folder_name,
            }
            for number, folder_name in enumerate(folder_names, start=1)
        ]
        (output / "metadata.json").write_text(
            json.dumps({"episodes": episodes}, ensure_ascii=False),
            encoding="utf-8",
        )
        (output / ".toki-state.json").write_text(
            json.dumps(
                {
                    "version": 2,
                    "completedEpisodes": [1, 2],
                    "completedEpisodeIds": [
                        "/manhwa/7000/episode-1",
                        "/manhwa/7000/episode-2",
                    ],
                    "episodes": episodes,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        job = DownloadJob(
            job_id="state-v2-folders",
            url="https://newtoki1.org/manhwa/7000",
            output_dir=str(workspace),
            output_path=str(output),
            state="완료",
        )
        save_jobs([job])

        manifest = load_episode_state_manifest(output)
        discovered = discover_episode_folders(output, manifest)
        self.assertTrue(manifest.valid)
        self.assertEqual(manifest.version, 2)
        self.assertEqual([entry.number for entry in discovered], [1, 2])
        self.assertEqual([entry.folder_name for entry in discovered], folder_names)
        self.assertTrue(all(entry.discovery == "manifest" for entry in discovered))

        verification = verify_job_files(job.job_id)
        self.assertTrue(verification["healthy"])
        self.assertEqual(verification["summary"]["episodeFolders"], 2)
        self.assertEqual(verification["summary"]["images"], 2)
        self.assertEqual(verification["state"]["version"], 2)
        self.assertEqual(verification["state"]["manifestEpisodes"], 2)

        preview = list_job_episode_images(job.job_id, 2)
        self.assertEqual(preview["episode"], 2)
        self.assertEqual(preview["availableEpisodes"], [1, 2])
        self.assertEqual(Path(preview["episodeFolders"][0]).name, folder_names[1])
        self.assertEqual([image["name"] for image in preview["images"]], ["0000.jpg"])

        conversion = plan_image_conversion(job.job_id, "webp")
        self.assertEqual(conversion["sourceCount"], 2)
        self.assertEqual(
            {Path(item["source"]).parent.name for item in conversion["sample"]},
            set(folder_names),
        )
        pdf = plan_job_pdf_generation(job.job_id)
        self.assertEqual(pdf["episodeFolderCount"], 2)
        self.assertEqual(pdf["episodeCount"], 2)
        self.assertEqual(pdf["sourceCount"], 2)

    def test_state_v2_uses_legacy_numbered_folder_when_exact_folder_is_missing(self) -> None:
        workspace = Path(self.temp_dir.name)
        output = workspace / "마나토끼" / "[작가][그룹] 이전 자료"
        legacy = output / "0001 축약된 이전 제목"
        legacy.mkdir(parents=True)
        (legacy / "image0000.jpg").write_bytes(
            b"\xff\xd8\xff" + b"image" + b"\xff\xd9"
        )
        (output / "metadata.json").write_text("{}", encoding="utf-8")
        (output / ".toki-state.json").write_text(
            json.dumps(
                {
                    "version": 2,
                    "completedEpisodes": [1],
                    "episodes": [
                        {
                            "number": 1,
                            "sourceId": "",
                            "sourceUrl": "",
                            "sourceTitle": "",
                            "displayTitle": "전체 제목 1화",
                            "folderName": "전체 제목 1화",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        job = DownloadJob(
            job_id="state-v2-legacy-fallback",
            url="https://newtoki1.org/manhwa/7001",
            output_dir=str(workspace),
            output_path=str(output),
            state="완료",
        )
        save_jobs([job])

        manifest = load_episode_state_manifest(output)
        discovered = discover_episode_folders(output, manifest)
        self.assertTrue(manifest.valid)
        self.assertEqual(len(discovered), 1)
        self.assertEqual(discovered[0].path, legacy.resolve())
        self.assertEqual(discovered[0].discovery, "legacy-fallback")
        self.assertTrue(verify_job_files(job.job_id)["healthy"])

    def test_episode_discovery_keeps_state_v1_numbered_folder_compatibility(self) -> None:
        workspace = Path(self.temp_dir.name)
        output = workspace / "마나토끼" / "[작가][그룹] v1 자료"
        folders = [output / "0001 첫 회차", output / "0002 둘째 회차"]
        for folder in folders:
            folder.mkdir(parents=True)
        (output / ".toki-state.json").write_text(
            json.dumps({"version": 1, "completedEpisodes": [1, 2]}),
            encoding="utf-8",
        )

        manifest = load_episode_state_manifest(output)
        discovered = discover_episode_folders(output, manifest)
        self.assertTrue(manifest.valid)
        self.assertEqual(manifest.version, 1)
        self.assertEqual([entry.number for entry in discovered], [1, 2])
        self.assertEqual([entry.path for entry in discovered], [
            folder.resolve() for folder in folders
        ])
        self.assertTrue(all(entry.discovery == "legacy" for entry in discovered))

    def test_state_v2_exact_folder_keeps_leftover_legacy_duplicate_visible(self) -> None:
        workspace = Path(self.temp_dir.name)
        output = workspace / "마나토끼" / "[작가][그룹] 중복 자료"
        exact = output / "전체 제목 1화"
        legacy = output / "0001 축약 제목"
        for folder in (exact, legacy):
            folder.mkdir(parents=True)
            (folder / "image0000.jpg").write_bytes(
                b"\xff\xd8\xff" + b"image" + b"\xff\xd9"
            )
        episodes = [
            {
                "number": 1,
                "sourceId": "",
                "sourceUrl": "",
                "sourceTitle": "",
                "displayTitle": "전체 제목 1화",
                "folderName": exact.name,
            }
        ]
        (output / "metadata.json").write_text("{}", encoding="utf-8")
        (output / ".toki-state.json").write_text(
            json.dumps(
                {"version": 2, "completedEpisodes": [1], "episodes": episodes},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        job = DownloadJob(
            job_id="state-v2-duplicate",
            url="https://newtoki1.org/manhwa/7002",
            output_dir=str(workspace),
            output_path=str(output),
            state="완료",
        )
        save_jobs([job])

        discovered = discover_episode_folders(output)
        self.assertEqual([entry.path for entry in discovered], [exact.resolve(), legacy.resolve()])
        result = verify_job_files(job.job_id)
        self.assertFalse(result["healthy"])
        self.assertEqual(result["summary"]["episodeFolders"], 2)
        self.assertEqual(result["summary"]["duplicateEpisodes"], 1)

    def test_invalid_state_uses_metadata_episode_manifest_for_discovery(self) -> None:
        workspace = Path(self.temp_dir.name)
        output = workspace / "마나토끼" / "[작가][그룹] 메타데이터 복구"
        exact = output / "메타데이터 전체 제목 1화"
        exact.mkdir(parents=True)
        (exact / "image0000.jpg").write_bytes(
            b"\xff\xd8\xff" + b"image" + b"\xff\xd9"
        )
        episodes = [
            {
                "number": 1,
                "sourceId": "",
                "sourceUrl": "",
                "sourceTitle": "",
                "displayTitle": exact.name,
                "folderName": exact.name,
            }
        ]
        (output / "metadata.json").write_text(
            json.dumps({"episodes": episodes}, ensure_ascii=False),
            encoding="utf-8",
        )
        (output / ".toki-state.json").write_text("not-json", encoding="utf-8")
        job = DownloadJob(
            job_id="metadata-manifest-fallback",
            url="https://newtoki1.org/manhwa/7003",
            output_dir=str(workspace),
            output_path=str(output),
            state="완료",
        )
        save_jobs([job])

        discovered = discover_episode_folders(output)
        self.assertEqual(len(discovered), 1)
        self.assertEqual(discovered[0].path, exact.resolve())
        self.assertEqual(discovered[0].discovery, "metadata")
        result = verify_job_files(job.job_id)
        self.assertFalse(result["healthy"])
        self.assertEqual(result["summary"]["episodeFolders"], 1)
        self.assertEqual(result["summary"]["images"], 1)
        self.assertEqual(result["summary"]["missingEpisodes"], 0)
        self.assertEqual(result["issues"][0]["kind"], "state_invalid")

    def test_partial_state_v2_keeps_all_declared_nonprefixed_folders_discoverable(self) -> None:
        workspace = Path(self.temp_dir.name)
        output = workspace / "마나토끼" / "[작가][그룹] 부분 손상 작품"
        valid_jpeg = b"\xff\xd8\xff" + b"image" + b"\xff\xd9"
        episodes = []
        expected_paths = set()
        for number in range(1, 273):
            folder_name = f"부분 손상 작품 전체 제목 {number}화"
            folder = output / folder_name
            folder.mkdir(parents=True)
            (folder / "0000.jpg").write_bytes(valid_jpeg)
            expected_paths.add(folder.resolve())
            episodes.append(
                {
                    "number": number,
                    "sourceId": f"/manhwa/7100/episode-{number}",
                    "sourceUrl": f"https://newtoki1.org/manhwa/7100/episode-{number}",
                    "sourceTitle": folder_name,
                    "displayTitle": folder_name,
                    "folderName": folder_name,
                }
            )
        episodes[49].pop("number")
        episodes[99]["number"] = 99
        episodes[149].pop("folderName")
        unrelated = output / "사용자 메모"
        unrelated.mkdir()
        (unrelated / "0000.jpg").write_bytes(valid_jpeg)
        (output / "metadata.json").write_text("{}", encoding="utf-8")
        (output / ".toki-state.json").write_text(
            json.dumps(
                {
                    "version": 2,
                    "completedEpisodes": list(range(1, 273)),
                    "completedEpisodeIds": [
                        *(f"/manhwa/7100/episode-{number}" for number in range(1, 273)),
                        "/manhwa/7100/not-in-manifest",
                    ],
                    "episodes": episodes,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        job = DownloadJob(
            job_id="partial-state-v2",
            url="https://newtoki1.org/manhwa/7100",
            output_dir=str(workspace),
            output_path=str(output),
            state="완료",
        )
        save_jobs([job])

        manifest = load_episode_state_manifest(output)
        discovered = discover_episode_folders(output, manifest)
        self.assertFalse(manifest.valid)
        self.assertEqual(len(manifest.episodes), 272)
        self.assertEqual(len(discovered), 272)
        self.assertEqual({entry.path for entry in discovered}, expected_paths)
        self.assertNotIn(unrelated.resolve(), {entry.path for entry in discovered})
        self.assertGreaterEqual(
            sum(not episode.record_valid for episode in manifest.episodes),
            2,
        )

        result = verify_job_files(job.job_id)
        self.assertFalse(result["healthy"])
        self.assertFalse(result["state"]["valid"])
        self.assertEqual(result["summary"]["episodeFolders"], 272)
        self.assertEqual(result["summary"]["images"], 272)
        self.assertIn("state_invalid", {issue["kind"] for issue in result["issues"]})
        self.assertEqual(result["summary"]["duplicateEpisodes"], 0)
        self.assertEqual(result["summary"]["uniqueEpisodes"], 272)
        self.assertEqual(result["missingEpisodes"], [])
        self.assertEqual(
            result["missingEpisodeIds"],
            ["/manhwa/7100/not-in-manifest"],
        )

    def test_partial_metadata_manifest_recovers_only_named_episode_folders(self) -> None:
        workspace = Path(self.temp_dir.name)
        output = workspace / "마나토끼" / "[작가][그룹] metadata 부분 복구"
        folder_names = [f"metadata 전체 제목 {number}화" for number in range(1, 4)]
        for folder_name in folder_names:
            (output / folder_name).mkdir(parents=True)
        unrelated = output / "임의 생성 폴더"
        unrelated.mkdir()
        episodes = [
            {
                "number": number,
                "sourceId": "",
                "sourceUrl": "",
                "sourceTitle": folder_name,
                "displayTitle": folder_name,
                "folderName": folder_name,
            }
            for number, folder_name in enumerate(folder_names, start=1)
        ]
        episodes[1].pop("number")
        episodes[1].pop("folderName")
        (output / "metadata.json").write_text(
            json.dumps({"episodes": episodes}, ensure_ascii=False),
            encoding="utf-8",
        )

        discovered = discover_episode_folders(output)
        self.assertEqual([entry.number for entry in discovered], [1, 2, 3])
        self.assertEqual({entry.path.name for entry in discovered}, set(folder_names))
        self.assertNotIn(unrelated.resolve(), {entry.path for entry in discovered})
        recovered = next(entry for entry in discovered if entry.number == 2)
        self.assertEqual(recovered.discovery, "metadata-recovery")

    def test_state_v2_allows_reused_ordinal_with_distinct_episode_identities(self) -> None:
        workspace = Path(self.temp_dir.name)
        output = workspace / "마나토끼" / "[작가][그룹] 순번 재사용 작품"
        folder_names = ["순번 재사용 작품 구판 7화", "순번 재사용 작품 신판 7화"]
        valid_jpeg = b"\xff\xd8\xff" + b"image" + b"\xff\xd9"
        episodes = []
        for edition, folder_name in zip(("old", "new"), folder_names):
            folder = output / folder_name
            folder.mkdir(parents=True)
            (folder / "0000.jpg").write_bytes(valid_jpeg)
            episodes.append(
                {
                    "number": 7,
                    "sourceId": f"/manhwa/7200/{edition}-episode-7",
                    "sourceUrl": f"https://newtoki1.org/manhwa/7200/{edition}-episode-7",
                    "sourceTitle": folder_name,
                    "displayTitle": folder_name,
                    "folderName": folder_name,
                }
            )
        (output / "metadata.json").write_text("{}", encoding="utf-8")
        (output / ".toki-state.json").write_text(
            json.dumps(
                {
                    "version": 2,
                    "completedEpisodes": [7],
                    "completedEpisodeIds": [episode["sourceId"] for episode in episodes],
                    "episodes": episodes,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        job = DownloadJob(
            job_id="reused-ordinal-v2",
            url="https://newtoki1.org/manhwa/7200",
            output_dir=str(workspace),
            output_path=str(output),
            state="완료",
        )
        save_jobs([job])

        manifest = load_episode_state_manifest(output)
        discovered = discover_episode_folders(output, manifest)
        self.assertTrue(manifest.valid)
        self.assertEqual([entry.number for entry in discovered], [7, 7])
        self.assertEqual({entry.source_id for entry in discovered}, {
            episode["sourceId"] for episode in episodes
        })
        result = verify_job_files(job.job_id)
        self.assertTrue(result["healthy"])
        self.assertEqual(result["summary"]["episodeFolders"], 2)
        self.assertEqual(result["summary"]["uniqueEpisodes"], 2)
        self.assertEqual(result["summary"]["expectedEpisodes"], 2)
        self.assertEqual(result["summary"]["duplicateEpisodes"], 0)

    def test_state_v2_partial_ids_verify_idless_completed_and_untracked_folders(self) -> None:
        workspace = Path(self.temp_dir.name)
        output = workspace / "마나토끼" / "[작가][그룹] 부분 ID 작품"
        valid_jpeg = b"\xff\xd8\xff" + b"image" + b"\xff\xd9"
        identified_folder = output / "부분 ID 작품 1화"
        untracked_folder = output / "부분 ID 작품 3화"
        for folder in (identified_folder, untracked_folder):
            folder.mkdir(parents=True)
            (folder / "0000.jpg").write_bytes(valid_jpeg)
        episodes = [
            {
                "number": 1,
                "sourceId": "/manhwa/7300/episode-1",
                "sourceUrl": "https://newtoki1.org/manhwa/7300/episode-1",
                "sourceTitle": identified_folder.name,
                "displayTitle": identified_folder.name,
                "folderName": identified_folder.name,
            },
            {
                "number": 2,
                "sourceId": "",
                "sourceUrl": "",
                "sourceTitle": "부분 ID 작품 2화",
                "displayTitle": "부분 ID 작품 2화",
                "folderName": "부분 ID 작품 2화",
            },
            {
                "number": 3,
                "sourceId": "",
                "sourceUrl": "",
                "sourceTitle": untracked_folder.name,
                "displayTitle": untracked_folder.name,
                "folderName": untracked_folder.name,
            },
        ]
        (output / "metadata.json").write_text("{}", encoding="utf-8")
        (output / ".toki-state.json").write_text(
            json.dumps(
                {
                    "version": 2,
                    "completedEpisodes": [1, 2],
                    "completedEpisodeIds": ["/manhwa/7300/episode-1"],
                    "episodes": episodes,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        job = DownloadJob(
            job_id="partial-id-verification",
            url="https://newtoki1.org/manhwa/7300",
            output_dir=str(workspace),
            output_path=str(output),
            state="완료",
        )
        save_jobs([job])

        result = verify_job_files(job.job_id)
        self.assertFalse(result["healthy"])
        self.assertEqual(result["missingEpisodes"], [2])
        self.assertEqual(result["missingEpisodeIds"], [])
        self.assertEqual(result["untrackedEpisodes"], [3])
        self.assertEqual(result["untrackedEpisodeIds"], [])
        self.assertEqual(result["summary"]["expectedEpisodes"], 2)
        self.assertEqual(result["summary"]["missingEpisodes"], 1)
        self.assertEqual(result["summary"]["untrackedEpisodes"], 1)

    def test_state_v2_partial_ids_keep_idless_identity_at_a_reused_ordinal(self) -> None:
        workspace = Path(self.temp_dir.name)
        output = workspace / "마나토끼" / "[작가][그룹] 혼합 ID 작품"
        identified_folder = output / "혼합 ID 작품 정식 7화"
        identified_folder.mkdir(parents=True)
        (identified_folder / "0000.jpg").write_bytes(
            b"\xff\xd8\xff" + b"image" + b"\xff\xd9"
        )
        episodes = [
            {
                "number": 7,
                "sourceId": "/manhwa/7301/identified-7",
                "sourceUrl": "https://newtoki1.org/manhwa/7301/identified-7",
                "sourceTitle": identified_folder.name,
                "displayTitle": identified_folder.name,
                "folderName": identified_folder.name,
            },
            {
                "number": 7,
                "sourceId": "",
                "sourceUrl": "",
                "sourceTitle": "혼합 ID 작품 이전 7화",
                "displayTitle": "혼합 ID 작품 이전 7화",
                "folderName": "혼합 ID 작품 이전 7화",
            },
        ]
        (output / "metadata.json").write_text("{}", encoding="utf-8")
        (output / ".toki-state.json").write_text(
            json.dumps(
                {
                    "version": 2,
                    "completedEpisodes": [7],
                    "completedEpisodeIds": ["/manhwa/7301/identified-7"],
                    "episodes": episodes,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        job = DownloadJob(
            job_id="partial-id-reused-ordinal",
            url="https://newtoki1.org/manhwa/7301",
            output_dir=str(workspace),
            output_path=str(output),
            state="완료",
        )
        save_jobs([job])

        result = verify_job_files(job.job_id)
        self.assertEqual(result["missingEpisodes"], [7])
        self.assertEqual(result["missingEpisodeIds"], [])
        self.assertEqual(result["summary"]["expectedEpisodes"], 2)
        self.assertEqual(result["summary"]["missingEpisodes"], 1)

    def test_file_verification_detects_missing_empty_and_invalid_images(self) -> None:
        workspace = Path(self.temp_dir.name)
        output = workspace / "마나토끼" / "[작가][그룹] 문제 작품"
        empty_episode = output / "0001 빈 회차"
        broken_episode = output / "0002 손상 회차"
        empty_episode.mkdir(parents=True)
        broken_episode.mkdir(parents=True)
        (broken_episode / "image0000.jpg").write_bytes(b"not-a-jpeg")
        (broken_episode / "image0001.png").write_bytes(b"")
        (output / "metadata.json").write_text("not-json", encoding="utf-8")
        (output / ".toki-state.json").write_text(
            json.dumps({"version": 1, "completedEpisodes": [1, 2, 3]}),
            encoding="utf-8",
        )
        job = DownloadJob(
            job_id="verify-broken",
            url="https://newtoki1.org/manhwa/6201",
            output_dir=str(workspace),
            output_path=str(output),
            state="완료",
        )
        save_jobs([job])

        result = verify_job_files(job.job_id, issue_limit=3)
        kinds = {issue["kind"] for issue in result["issues"]}
        self.assertFalse(result["healthy"])
        self.assertEqual(result["missingEpisodes"], [3])
        self.assertEqual(result["summary"]["emptyEpisodes"], 1)
        self.assertEqual(result["summary"]["invalidImages"], 1)
        self.assertEqual(result["summary"]["zeroByteImages"], 1)
        self.assertGreater(result["summary"]["issueCount"], 3)
        self.assertTrue(result["summary"]["issuesTruncated"])
        self.assertIn("metadata_invalid", kinds)

    def test_file_verification_handles_one_thousand_episode_folders(self) -> None:
        workspace = Path(self.temp_dir.name)
        output = workspace / "마나토끼" / "[작가][그룹] 대규모 작품"
        valid_jpeg = b"\xff\xd8\xff" + b"image" + b"\xff\xd9"
        for number in range(1, 1001):
            episode = output / f"{number:04d} {number}화"
            episode.mkdir(parents=True)
            (episode / "image0000.jpg").write_bytes(valid_jpeg)
        (output / "metadata.json").write_text("{}", encoding="utf-8")
        (output / ".toki-state.json").write_text(
            json.dumps(
                {"version": 1, "completedEpisodes": list(range(1, 1001))}
            ),
            encoding="utf-8",
        )
        job = DownloadJob(
            job_id="verify-large",
            url="https://newtoki1.org/manhwa/6202",
            output_dir=str(workspace),
            output_path=str(output),
            state="완료",
        )
        save_jobs([job])

        result = verify_job_files(job.job_id, issue_limit=10)
        self.assertTrue(result["healthy"])
        self.assertEqual(result["summary"]["episodeFolders"], 1000)
        self.assertEqual(result["summary"]["images"], 1000)
        self.assertEqual(result["summary"]["returnedIssues"], 0)

    def test_episode_image_preview_is_naturally_sorted_and_paginated(self) -> None:
        workspace = Path(self.temp_dir.name)
        output = workspace / "마나토끼" / "[작가][그룹] 미리보기 작품"
        first = output / "0001 첫 회차"
        second = output / "0002 둘째 회차"
        first.mkdir(parents=True)
        second.mkdir(parents=True)
        for name in ("image10.jpg", "image2.jpg", "image1.jpg", "note.txt"):
            (first / name).write_bytes(b"data")
        (second / "image1.png").write_bytes(b"data")
        job = DownloadJob(
            job_id="preview-images",
            url="https://newtoki1.org/manhwa/6300",
            output_dir=str(workspace),
            output_path=str(output),
            state="완료",
        )
        save_jobs([job])

        first_page = list_job_episode_images(job.job_id, limit=2)
        self.assertEqual(first_page["episode"], 1)
        self.assertEqual(first_page["availableEpisodes"], [1, 2])
        self.assertEqual(first_page["total"], 3)
        self.assertEqual(
            [image["name"] for image in first_page["images"]],
            ["image1.jpg", "image2.jpg"],
        )
        second_page = list_job_episode_images(job.job_id, 1, limit=2, offset=2)
        self.assertEqual([image["name"] for image in second_page["images"]], ["image10.jpg"])
        with self.assertRaises(ValueError):
            list_job_episode_images(job.job_id, 99)

    @unittest.skipUnless(importlib.util.find_spec("PIL"), "Pillow optional dependency")
    def test_image_conversion_preserves_originals_and_skips_existing_outputs(self) -> None:
        from PIL import Image

        workspace = Path(self.temp_dir.name)
        output = workspace / "마나토끼" / "[작가][그룹] 변환 작품"
        episode = output / "0001 첫 회차"
        episode.mkdir(parents=True)
        png_path = episode / "same.png"
        jpg_path = episode / "same.jpg"
        Image.new("RGBA", (128, 96), (255, 0, 0, 100)).save(png_path)
        Image.new("RGB", (120, 80), (0, 255, 0)).save(jpg_path)
        original_png = png_path.read_bytes()
        original_jpg = jpg_path.read_bytes()
        job = DownloadJob(
            job_id="convert-images",
            url="https://newtoki1.org/manhwa/6400",
            output_dir=str(workspace),
            output_path=str(output),
            state="완료",
        )
        save_jobs([job])

        plan = plan_image_conversion(job.job_id, "jpeg", quality=85)
        self.assertEqual(plan["format"], "jpg")
        self.assertEqual(plan["sourceCount"], 2)
        self.assertEqual(plan["pendingCount"], 2)
        self.assertTrue(plan["preservesOriginals"])
        self.assertFalse(Path(plan["targetRoot"]).exists())
        self.assertEqual(len({item["target"] for item in plan["sample"]}), 2)

        result = convert_job_images(job.job_id, "jpg", quality=85)
        targets = sorted(Path(result["targetRoot"]).rglob("*.jpg"))
        self.assertTrue(result["success"])
        self.assertEqual(result["convertedCount"], 2)
        self.assertEqual(len(targets), 2)
        self.assertEqual(png_path.read_bytes(), original_png)
        self.assertEqual(jpg_path.read_bytes(), original_jpg)
        with Image.open(targets[0]) as converted:
            self.assertEqual(converted.mode, "RGB")

        repeated = convert_job_images(job.job_id, "jpg", quality=85)
        self.assertEqual(repeated["convertedCount"], 0)
        self.assertEqual(repeated["skippedExistingCount"], 2)

        policy_config = default_config()
        policy_config.update(
            {
                "imageResizeMaxWidth": 64,
                "imageResizeMaxHeight": 64,
                "imageExcludedExtensions": ["png"],
            }
        )
        policy = image_processing_policy_snapshot(policy_config)
        self.assertTrue(policy["resizeEnabled"])
        self.assertEqual(policy["excludedExtensions"], [".png"])
        resized_plan = plan_image_conversion(
            job.job_id,
            "webp",
            max_width=64,
            max_height=64,
            excluded_extensions=["png"],
        )
        self.assertEqual(resized_plan["candidateSourceCount"], 2)
        self.assertEqual(resized_plan["excludedSourceCount"], 1)
        self.assertEqual(resized_plan["sourceCount"], 1)
        self.assertIn("webp-64x64", resized_plan["targetRoot"])
        resized_result = convert_job_images(
            job.job_id,
            "webp",
            max_width=64,
            max_height=64,
            excluded_extensions=["png"],
        )
        self.assertTrue(resized_result["success"])
        self.assertEqual(resized_result["resizedCount"], 1)
        resized_targets = list(Path(resized_result["targetRoot"]).rglob("*.webp"))
        self.assertEqual(len(resized_targets), 1)
        with Image.open(resized_targets[0]) as resized_image:
            self.assertLessEqual(resized_image.width, 64)
            self.assertLessEqual(resized_image.height, 64)
        self.assertEqual(png_path.read_bytes(), original_png)
        self.assertEqual(jpg_path.read_bytes(), original_jpg)

        webp_plan = plan_image_conversion(job.job_id, "webp", quality=80)
        stale_temporary = Path(webp_plan["sample"][0]["target"] + ".tmp")
        stale_temporary.parent.mkdir(parents=True, exist_ok=True)
        stale_temporary.write_bytes(b"partial")
        checks = 0
        events = []

        def cancel_after_first() -> bool:
            nonlocal checks
            checks += 1
            return checks > 1

        cancelled = convert_job_images(
            job.job_id,
            "webp",
            quality=80,
            progress_callback=events.append,
            cancel_check=cancel_after_first,
        )
        self.assertTrue(cancelled["cancelled"])
        self.assertEqual(cancelled["processedCount"], 1)
        self.assertEqual(cancelled["remainingCount"], 1)
        self.assertEqual(cancelled["recoveredTemporaryFiles"], 1)
        self.assertEqual(len(events), 1)
        self.assertFalse(stale_temporary.exists())

        recovered = convert_job_images(job.job_id, "webp", quality=80)
        self.assertTrue(recovered["success"])
        self.assertEqual(recovered["convertedCount"], 1)
        self.assertEqual(recovered["skippedExistingCount"], 1)

    @unittest.skipUnless(importlib.util.find_spec("PIL"), "Pillow optional dependency")
    def test_pdf_generation_is_per_episode_atomic_and_preserves_originals(self) -> None:
        from PIL import Image

        workspace = Path(self.temp_dir.name)
        output = workspace / "마나토끼" / "[작가][그룹] PDF 작품"
        first = output / "0001 첫 회차"
        second = output / "0002 둘째 회차"
        first.mkdir(parents=True)
        second.mkdir(parents=True)
        sources = [
            first / "image1.png",
            first / "image2.jpg",
            second / "image1.webp",
        ]
        Image.new("RGBA", (80, 120), (255, 0, 0, 100)).save(sources[0])
        Image.new("RGB", (90, 130), (0, 255, 0)).save(sources[1])
        Image.new("RGB", (100, 140), (0, 0, 255)).save(sources[2])
        originals = {path: path.read_bytes() for path in sources}
        job = DownloadJob(
            job_id="generate-pdf",
            url="https://newtoki1.org/manhwa/6500",
            output_dir=str(workspace),
            output_path=str(output),
            state="완료",
        )
        save_jobs([job])

        policy = pdf_generation_policy_snapshot(default_config())
        self.assertFalse(policy["automatic"])
        self.assertTrue(policy["preservesOriginals"])
        plan = plan_job_pdf_generation(job.job_id)
        self.assertEqual(plan["episodeCount"], 2)
        self.assertEqual(plan["sourceCount"], 3)
        self.assertEqual(plan["pendingCount"], 2)
        self.assertFalse(Path(plan["targetRoot"]).exists())

        events = []
        result = generate_job_pdfs(job.job_id, progress_callback=events.append)
        targets = sorted(Path(result["targetRoot"]).glob("*.pdf"))
        self.assertTrue(result["success"])
        self.assertEqual(result["generatedCount"], 2)
        self.assertEqual(len(events), 2)
        self.assertEqual(len(targets), 2)
        self.assertTrue(all(path.read_bytes().startswith(b"%PDF") for path in targets))
        self.assertEqual(
            {path: path.read_bytes() for path in sources},
            originals,
        )

        stale_temporary = targets[0].with_suffix(".pdf.tmp")
        stale_temporary.write_bytes(b"partial")
        repeated = generate_job_pdfs(job.job_id)
        self.assertEqual(repeated["generatedCount"], 0)
        self.assertEqual(repeated["skippedCurrentCount"], 2)
        self.assertEqual(repeated["recoveredTemporaryFiles"], 1)
        self.assertFalse(stale_temporary.exists())

        time.sleep(0.01)
        Image.new("RGB", (80, 120), (10, 20, 30)).save(sources[0])
        changed_source = sources[0].read_bytes()
        replacement_plan = plan_job_pdf_generation(job.job_id)
        self.assertEqual(replacement_plan["replacementCount"], 1)
        replaced = generate_job_pdfs(job.job_id)
        self.assertEqual(replaced["generatedCount"], 1)
        self.assertEqual(replaced["replacedCount"], 1)
        self.assertEqual(sources[0].read_bytes(), changed_source)

        cancelled = generate_job_pdfs(job.job_id, cancel_check=lambda: True)
        self.assertTrue(cancelled["cancelled"])
        self.assertEqual(cancelled["processedCount"], 0)
        self.assertEqual(cancelled["remainingCount"], 2)

    @unittest.skipUnless(importlib.util.find_spec("PIL"), "Pillow optional dependency")
    def test_image_conversion_failure_removes_partial_target_and_reports_progress(self) -> None:
        workspace = Path(self.temp_dir.name)
        output = workspace / "마나토끼" / "[작가][그룹] 손상 이미지 작품"
        episode = output / "0001 첫 회차"
        episode.mkdir(parents=True)
        corrupt = episode / "image1.jpg"
        corrupt.write_bytes(b"not-an-image")
        job = DownloadJob(
            job_id="convert-corrupt-image",
            url="https://newtoki1.org/manhwa/6401",
            output_dir=str(workspace),
            output_path=str(output),
            state="완료",
        )
        save_jobs([job])
        events = []

        result = convert_job_images(
            job.job_id,
            "webp",
            progress_callback=events.append,
        )

        target = Path(result["targetRoot"]) / episode.name / "image1.webp"
        self.assertFalse(result["success"])
        self.assertEqual(result["failedCount"], 1)
        self.assertEqual(result["processedCount"], 1)
        self.assertEqual(result["remainingCount"], 0)
        self.assertEqual(events[0]["status"], "failed")
        self.assertFalse(target.exists())
        self.assertFalse(Path(str(target) + ".tmp").exists())

    def test_bulk_cleanup_only_removes_selected_states(self) -> None:
        jobs = [
            DownloadJob(
                job_id="completed",
                url="https://newtoki1.org/manhwa/5001",
                output_dir=self.temp_dir.name,
                state="완료",
            ),
            DownloadJob(
                job_id="error",
                url="https://newtoki1.org/manhwa/5002",
                output_dir=self.temp_dir.name,
                state="오류",
            ),
            DownloadJob(
                job_id="waiting",
                url="https://newtoki1.org/manhwa/5003",
                output_dir=self.temp_dir.name,
                state="대기",
            ),
        ]
        save_jobs(jobs)
        removed = delete_job_records(["완료", "오류"])
        self.assertEqual({job.job_id for job in removed}, {"completed", "error"})
        self.assertEqual(count_jobs(), 1)
        with self.assertRaises(ValueError):
            delete_job_records(["대기"])


if __name__ == "__main__":
    unittest.main()
