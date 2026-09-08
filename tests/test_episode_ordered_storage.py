import hashlib
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import toki_core as core
import toki_library as library
from toki_archive_catalog import archived_episodes
import test_toki_library as fixtures
from test_toki_work_archive import add_chapter


class OrderedEpisodeStorageTests(unittest.TestCase):
    setUp = fixtures.LibraryTests.setUp
    work = fixtures.LibraryTests.work

    def hashes(self, root):
        return sorted(hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*.jpg') if '_archives' not in p.parts)

    def test_default_migration_preserves_files_completion_and_archive_then_is_idempotent(self):
        job, root, _ = self.work()
        add_chapter(root, 2, '작품 a 141.2화')
        add_chapter(root, 3, '작품 a 141.5화')
        add_chapter(root, 4, '작품 a 142-1화')
        add_chapter(root, 5, '작품 a 142-2화')
        initial = library.archive_library_items([job.job_id], execute=True)
        archive = Path(initial['results'][0]['archivePath'])
        zip_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
        before = self.hashes(root)
        plan = core.plan_episode_folder_rename(job.job_id)
        self.assertEqual(plan['mode'], 'ordered_title')
        self.assertEqual(plan['renameCount'], 5)
        self.assertTrue(plan['canExecute'], plan['conflicts'])
        result = core.rename_episode_folders(job.job_id)
        self.assertEqual(result['renamedCount'], 5)
        self.assertTrue(Path(result['archiveIndexBackupPath']).exists())
        names = [r['folderName'] for r in result['episodes']]
        self.assertEqual(names, sorted(names))
        self.assertEqual(names[0], '000001 작품 a 141.0화')
        self.assertEqual(names[-1], '000005 작품 a 142-2화')
        self.assertTrue(all((root / name).is_dir() for name in names))
        self.assertEqual(self.hashes(root), before)
        self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), zip_hash)
        self.assertEqual({e['folderName'] for e in archived_episodes(root)}, set(names))
        self.assertTrue(core.verify_job_files(job.job_id)['healthy'])
        self.assertEqual(core.plan_episode_folder_rename(job.job_id)['renameCount'], 0)
        cleanup = library.archive_library_items([job.job_id], execute=True, remove_originals=True)
        self.assertTrue(cleanup['success'], cleanup)
        self.assertEqual(cleanup['removedOriginalCount'], 15)
        self.assertTrue(core.verify_job_files(job.job_id)['healthy'])

    def test_catalog_write_error_rolls_back_folder_metadata_and_index(self):
        job, root, folder = self.work()
        library.archive_library_items([job.job_id], execute=True)
        index = root / '_archives/.toki-archive-index.json'
        before = {p: p.read_bytes() for p in (index, root / 'metadata.json', root / '.toki-state.json')}
        original_writer = core._write_episode_rename_json
        def fail_index(path, payload):
            if path == index:
                raise OSError('simulated catalog failure')
            return original_writer(path, payload)
        with patch.object(core, '_write_episode_rename_json', side_effect=fail_index):
            with self.assertRaisesRegex(OSError, 'catalog failure'):
                core.rename_episode_folders(job.job_id)
        self.assertTrue(folder.is_dir())
        self.assertEqual({p: p.read_bytes() for p in before}, before)
        self.assertFalse(list(root.glob('.toki-episode-rename-*')))

    def test_destination_conflict_does_not_change_user_files(self):
        job, root, folder = self.work()
        destination = root / '000001 작품 a 141.0화'
        destination.mkdir()
        (destination / 'user.txt').write_text('guard')
        plan = core.plan_episode_folder_rename(job.job_id)
        self.assertFalse(plan['canExecute'])
        with self.assertRaises(FileExistsError):
            core.rename_episode_folders(job.job_id)
        self.assertEqual((destination / 'user.txt').read_text(), 'guard')
        self.assertTrue(folder.is_dir())

    def test_actual_cli_defaults_to_ordered_migration_and_matches_node_names(self):
        job, root, folder = self.work()
        (self.root / '.library-cli-test').touch()
        command = [sys.executable, '-X', 'utf8', str(core.ROOT_DIR / 'tests/fixtures/library_cli_host.py'), str(self.root),
                   'rename-episodes', '--job', job.job_id, '--json']
        def call(args):
            result = subprocess.run(args, cwd=core.ROOT_DIR, capture_output=True, text=True, encoding='utf-8',
                                    timeout=20, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            return json.loads(result.stdout)
        plan = call(command)
        self.assertEqual(plan['mode'], 'ordered_title')
        self.assertTrue(folder.is_dir())
        result = call([*command, '--execute', '--yes'])
        self.assertEqual(result['renamedCount'], 1)
        target = result['mappings'][0]['destinationFolderName']
        self.assertEqual(target, '000001 작품 a 141.0화')
        self.assertTrue((root / target).is_dir())
        self.assertEqual(call(command)['renameCount'], 0)
        node = call(['node', '--input-type=module', '-e', "import {orderedEpisodeFolderName} from './downloader_naming.js'; console.log(JSON.stringify(orderedEpisodeFolderName(1,'작품 a 141.0화')))"])
        self.assertEqual(node, target)
