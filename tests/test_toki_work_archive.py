import json
import subprocess
import sys
import zipfile
from pathlib import Path
from unittest.mock import patch

import toki_core as core
import toki_library as lib
from toki_archive_catalog import archived_episodes
import test_toki_library as legacy


def add_chapter(root, number, title):
    folder = root / title
    folder.mkdir()
    for page in (10, 2, 1):
        (folder / f"image{page}.jpg").write_bytes(b"\xff\xd8\xff" + f"{number}-{page}".encode() + b"\xff\xd9")
    state_path = root / ".toki-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    entry = {"number": number, "folderName": title, "sourceId": f"/manhwa/a/{number}", "sourceTitle": title,
             "sourceUrl": f"https://newtoki1.org/manhwa/a/{number}", "displayTitle": title}
    state["episodes"].append(entry)
    state["completedEpisodes"].append(number)
    state["completedEpisodeIds"].append(entry["sourceId"])
    state_path.write_text(json.dumps(state), encoding="utf-8")
    metadata = root / "metadata.json"
    data = json.loads(metadata.read_text(encoding="utf-8"))
    data["episodes"].append(entry)
    metadata.write_text(json.dumps(data), encoding="utf-8")
    return folder


class WholeWorkArchiveTests(legacy.unittest.TestCase):
    setUp = legacy.LibraryTests.setUp
    work = legacy.LibraryTests.work

    def test_one_zip_multiple_chapters_decimal_split_order_and_update_after_cleanup(self):
        job, root, first = self.work()
        for number, title in ((2, '작품 a 141.2화'), (3, '작품 a 141.5화'), (4, '작품 a 142-1화'), (5, '작품 a 142-2화')):
            add_chapter(root, number, title)
        cover = root / 'cover.jpg'
        cover.write_bytes(b'cover stays')
        result = lib.archive_library_items([job.job_id], execute=True, remove_originals=True)
        self.assertTrue(result['success'], result)
        self.assertEqual((result['archiveCount'], result['createdCount'], result['removedOriginalCount']), (1, 1, 15))
        archive = Path(result['jobs'][0]['archives'][0]['path'])
        self.assertEqual(archive.name, root.name + '.zip')
        self.assertEqual(len(list(archive.parent.glob('*.zip'))), 1)
        with zipfile.ZipFile(archive) as bundle:
            old = {n: bundle.read(n) for n in bundle.namelist() if '/' in n}
            self.assertEqual(list(old), sorted(old))
            self.assertEqual([n.split('/')[0] for n in list(old)[::3]], [
                '000001 작품 a 141.0화', '000002 작품 a 141.2화', '000003 작품 a 141.5화',
                '000004 작품 a 142-1화', '000005 작품 a 142-2화'])
            self.assertIn('metadata.json', bundle.namelist())
        self.assertEqual(len(archived_episodes(root, verify_crc=True)), 5)
        self.assertTrue(cover.exists() and (root / 'metadata.json').exists())
        self.assertFalse(first.exists())
        next_folder = add_chapter(root, 6, '작품 a 143화')
        updated = lib.archive_library_items([job.job_id], execute=True, remove_originals=True)
        self.assertTrue(updated['success'], updated)
        self.assertEqual(updated['removedOriginalCount'], 3)
        self.assertFalse(next_folder.exists())
        with zipfile.ZipFile(archive) as bundle:
            self.assertEqual(len([n for n in bundle.namelist() if '/' in n]), 18)
            self.assertTrue(all(bundle.read(n) == data for n, data in old.items()))
        self.assertEqual(len(archived_episodes(root, verify_crc=True)), 6)
        checked = core.verify_job_files(job.job_id)
        self.assertTrue(checked['healthy'], checked)
        self.assertEqual(checked['summary']['archivedImages'], 18)
        again = lib.archive_library_items([job.job_id], execute=True, remove_originals=True)
        self.assertEqual((again['createdCount'], again['skippedCount']), (0, 1))

    def test_legacy_episode_zips_can_be_merged_without_removing_existing_archives(self):
        job, root, _ = self.work()
        add_chapter(root, 2, '작품 a 141.5화')
        old = lib.archive_library_items([job.job_id], mode='episodes', execute=True, remove_originals=True)
        paths = [Path(a['path']) for a in old['jobs'][0]['archives']]
        guards = [p.read_bytes() for p in paths]
        result = lib.archive_library_items([job.job_id], execute=True, remove_originals=True)
        self.assertTrue(result['success'], result)
        self.assertEqual(result['createdCount'], 1)
        archive = Path(result['jobs'][0]['archives'][0]['path'])
        with zipfile.ZipFile(archive) as bundle:
            self.assertEqual(len([n for n in bundle.namelist() if n.endswith('.jpg')]), 6)
        self.assertEqual([p.read_bytes() for p in paths], guards)
        self.assertEqual(len(archived_episodes(root)), 2)

    def test_catalog_publish_failure_restores_existing_zip_and_preserves_raw(self):
        job, root, _ = self.work()
        first = lib.archive_library_items([job.job_id], execute=True, remove_originals=True)
        archive = Path(first['jobs'][0]['archives'][0]['path'])
        previous = archive.read_bytes()
        index = archive.parent / '.toki-archive-index.json'
        previous_index = index.read_bytes()
        folder = add_chapter(root, 2, '작품 a 141.5화')
        with patch.object(lib, '_write_json', side_effect=OSError('disk full')):
            result = lib.archive_library_items([job.job_id], execute=True, remove_originals=True)
        self.assertFalse(result['success'])
        self.assertEqual(archive.read_bytes(), previous)
        self.assertEqual(index.read_bytes(), previous_index)
        self.assertEqual(len(list(folder.glob('*.jpg'))), 3)

    def test_cancel_mid_update_preserves_previous_complete_archive(self):
        job, root, _ = self.work()
        first = lib.archive_library_items([job.job_id], execute=True, remove_originals=True)
        archive = Path(first['jobs'][0]['archives'][0]['path'])
        previous = archive.read_bytes()
        folder = add_chapter(root, 2, '작품 a 141.5화')
        calls = []
        def cancel():
            calls.append(True)
            return len(calls) > 3
        result = lib.archive_library_items([job.job_id], execute=True, remove_originals=True, cancelled=cancel)
        self.assertTrue(result['cancelled'])
        self.assertEqual(archive.read_bytes(), previous)
        self.assertEqual(len(list(folder.glob('*.jpg'))), 3)

    def test_cli_default_whole_zip_cleanup_then_append_and_node_completion(self):
        job, root, _ = self.work()
        add_chapter(root, 2, '작품 a 141.5화')
        (self.root / '.library-cli-test').touch()
        command = [sys.executable, '-X', 'utf8', str(core.ROOT_DIR / 'tests/fixtures/library_cli_host.py'), str(self.root),
                   'library', 'archive', '--job', job.job_id]
        def cli(*args):
            result = subprocess.run([*command, *args, '--json'], cwd=core.ROOT_DIR,
                capture_output=True, text=True, encoding='utf-8', timeout=30,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            return json.loads(result.stdout)
        plan = cli('--dry-run')
        self.assertEqual((plan['mode'], plan['archiveCount']), ('work', 1))
        self.assertFalse((root / '_archives').exists())
        first = cli('--execute', '--yes', '--remove-originals')
        self.assertEqual(first['removedOriginalCount'], 6)
        add_chapter(root, 3, '작품 a 142-1화')
        updated = cli('--execute', '--yes', '--remove-originals')
        self.assertEqual(updated['removedOriginalCount'], 3)
        script = "import {loadArchivedEpisodes} from './downloader_archives.js'; console.log(loadArchivedEpisodes(process.argv[1]).length)"
        node = subprocess.run(['node', '--input-type=module', '-e', script, str(root)], cwd=core.ROOT_DIR,
            capture_output=True, text=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.assertEqual(node.stdout.strip(), '3', node.stderr)
        self.assertEqual(len(list((root / '_archives').glob('*.zip'))), 1)
        print('[CLI work ZIP] preview 1 ZIP; 2 chapters compressed, 6 originals cleaned; append retained old pages; Node completion 3')

    def test_zip64_catalog_is_understood_by_node(self):
        job, root, _ = self.work()
        # Force genuine ZIP64 central offsets/count records without a 4 GiB fixture.
        with patch.object(zipfile, 'ZIP64_LIMIT', 1):
            result = lib.archive_library_items([job.job_id], execute=True, remove_originals=True)
        self.assertTrue(result['success'], result)
        script = "import {loadArchivedEpisodes} from './downloader_archives.js'; console.log(loadArchivedEpisodes(process.argv[1]).length)"
        node = subprocess.run(['node', '--input-type=module', '-e', script, str(root)], cwd=core.ROOT_DIR,
            capture_output=True, text=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.assertEqual(node.stdout.strip(), '1', node.stderr)

    def test_rescan_renumbering_applies_to_archived_only_chapters(self):
        job, root, _ = self.work()
        first = lib.archive_library_items([job.job_id], execute=True, remove_originals=True)
        state_path = root / '.toki-state.json'
        state = json.loads(state_path.read_text(encoding='utf-8'))
        state['episodes'][0]['number'] = 2
        state['completedEpisodes'] = [2]
        state_path.write_text(json.dumps(state), encoding='utf-8')
        # New earlier source has a different stable ID even though its row is 1.
        add_chapter(root, 3, '작품 a 140화')
        state = json.loads(state_path.read_text(encoding='utf-8'))
        state['episodes'][-1]['number'] = 1
        state['completedEpisodes'] = [1, 2]
        state_path.write_text(json.dumps(state), encoding='utf-8')
        result = lib.archive_library_items([job.job_id], execute=True, remove_originals=True)
        self.assertTrue(result['success'], result)
        with zipfile.ZipFile(first['jobs'][0]['archives'][0]['path']) as bundle:
            names = [n for n in bundle.namelist() if n.endswith('.jpg')]
            self.assertTrue(names[0].startswith('000001 작품 a 140화/'))
            self.assertTrue(names[-1].startswith('000002 작품 a 141.0화/'))

    def test_legacy_truncated_folder_gets_full_display_title_inside_zip(self):
        job, root, _ = self.work()
        state_path = root / '.toki-state.json'
        state = json.loads(state_path.read_text(encoding='utf-8'))
        state['episodes'][0]['displayTitle'] = '완전한 작품 제목 141.0화'
        state_path.write_text(json.dumps(state), encoding='utf-8')
        result = lib.archive_library_items([job.job_id], execute=True)
        self.assertTrue(result['success'], result)
        with zipfile.ZipFile(result['jobs'][0]['archives'][0]['path']) as bundle:
            names = [n for n in bundle.namelist() if n.endswith('.jpg')]
            self.assertTrue(all(n.startswith('000001 완전한 작품 제목 141.0화/') for n in names))

    def test_two_thousand_chapters_read_zip_directory_only_twice(self):
        job, root, _ = self.work()
        output = root / '_archives'
        output.mkdir()
        target = output / (root.name + '.zip')
        episodes = []
        with zipfile.ZipFile(target, 'w') as bundle:
            for number in range(1, 2001):
                prefix = f'{number:06d} 작품 {number}화/'
                bundle.writestr(prefix + '000001.jpg', b'page')
                episodes.append({'number': number, 'sourceId': f'/manhwa/a/{number}',
                    'sourceTitle': f'작품 {number}화', 'folderName': f'작품 {number}화', 'prefix': prefix, 'imageCount': 1})
        (output / '.toki-archive-index.json').write_text(json.dumps({target.name: {
            'episodes': episodes, 'size': target.stat().st_size, 'mtimeNs': str(target.stat().st_mtime_ns)}}), encoding='utf-8')
        from toki_work_archive import _existing_chapters
        with patch.object(zipfile, 'ZipFile', wraps=zipfile.ZipFile) as opened:
            result = _existing_chapters(root)
            self.assertEqual(len(result), 2000)
            self.assertLessEqual(opened.call_count, 2)
