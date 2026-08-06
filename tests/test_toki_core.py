from __future__ import annotations

import tempfile
import json
import importlib.util
import os
import sqlite3
import time
import unittest
import zipfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import toki_core
from toki_core import (
    append_bounded_text,
    available_work_slots,
    DownloadJob,
    DownloadRun,
    build_downloader_args,
    build_job_list_view_state,
    build_work_key,
    cleanup_thumbnail_cache,
    cleanup_run_history,
    count_jobs,
    count_runs,
    dependency_diagnostics,
    convert_job_images,
    default_config,
    delete_job_record,
    delete_job_records,
    downloader_event_update_policy,
    export_diagnostics,
    hydrate_job_metadata,
    job_database_diagnostics,
    keyboard_shortcut_catalog,
    keyboard_shortcut_keys,
    load_job_by_work_key,
    load_jobs_page,
    list_job_episode_images,
    load_run,
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
    normalize_config,
    normalize_work_concurrency,
    move_job_folder,
    plan_job_folder_move,
    plan_image_conversion,
    plan_metadata_rebuild,
    plan_window_geometry,
    read_run_log,
    rebuild_job_metadata,
    recover_interrupted_jobs,
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
    set_job_pause_state,
    set_process_tree_paused,
    should_auto_retry,
    settings_snapshot,
    thumbnail_cache_path,
    update_app_settings,
    update_job_note,
    verify_job_files,
    update_job_markers,
)


class CoreContractTests(unittest.TestCase):
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
                self.assertFalse(loaded["trayEnabled"])

                output = root / "새 저장 폴더"
                updated = update_app_settings(
                    {
                        "outputDir": str(output),
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
                        "trayEnabled": True,
                        "closeToTray": True,
                        "notifyOnComplete": False,
                    }
                )
                self.assertTrue(output.is_dir())
                self.assertEqual(updated["workConcurrency"], 3)
                self.assertEqual(updated["logBackupCount"], 3)
                self.assertEqual(updated["rowDensity"], "compact")
                self.assertEqual(updated["theme"], "dark")
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
        concurrency_index = args.index("-image-concurrency")
        self.assertEqual(args[concurrency_index + 1], "5")
        mode_index = args.index("-scan-mode")
        self.assertEqual(args[mode_index + 1], "new")

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

        result = recover_interrupted_jobs()

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
            [item["version"] for item in schema["migrations"]], [1, 2]
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
                title="[작가A][그룹A] 알파 작품",
                state="완료",
                progress=100,
            ),
            DownloadJob(
                job_id="beta",
                url="https://newtoki1.org/manhwa/2002",
                output_dir=r"C:\Manga",
                title="[작가B][그룹B] 베타 작품",
                state="오류",
                progress=40,
            ),
        ]
        save_jobs(jobs)
        self.assertEqual(count_jobs(query="작가B"), 1)
        self.assertEqual(load_jobs_page(query="그룹B")[0].job_id, "beta")
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
        Image.new("RGBA", (8, 6), (255, 0, 0, 100)).save(png_path)
        Image.new("RGB", (7, 5), (0, 255, 0)).save(jpg_path)
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
