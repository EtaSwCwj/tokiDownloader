from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import toki_core
from toki_core import (
    DownloadJob,
    build_downloader_args,
    build_work_key,
    count_jobs,
    delete_job_record,
    delete_job_records,
    load_job_by_work_key,
    load_jobs_page,
    normalize_range,
    save_jobs,
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
        deleted = delete_job_record(job.job_id)
        self.assertEqual(deleted.job_id, job.job_id)
        self.assertEqual(count_jobs(), 0)
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
