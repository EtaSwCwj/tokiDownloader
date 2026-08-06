from __future__ import annotations

import tempfile
import json
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

import toki_core
from toki_core import (
    available_work_slots,
    DownloadJob,
    DownloadRun,
    build_downloader_args,
    build_work_key,
    count_jobs,
    count_runs,
    delete_job_record,
    delete_job_records,
    hydrate_job_metadata,
    load_job_by_work_key,
    load_jobs_page,
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
    normalize_work_concurrency,
    read_run_log,
    recover_interrupted_jobs,
    retry_backoff_seconds,
    resolve_cover_path,
    reorder_pending_jobs,
    save_jobs,
    save_runs,
    set_job_pause_state,
    set_process_tree_paused,
    should_auto_retry,
    update_job_note,
    update_job_markers,
)


class CoreContractTests(unittest.TestCase):
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
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "jobs.db"
        self.path_patch = patch.object(toki_core, "JOB_DB_PATH", self.database_path)
        self.path_patch.start()
        toki_core._INITIALIZED_JOB_DBS.clear()

    def tearDown(self) -> None:
        toki_core._INITIALIZED_JOB_DBS.clear()
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
