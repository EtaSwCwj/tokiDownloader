import json
import os
import subprocess
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import toki_core as core
import toki_library as lib
from toki_reading_order import assign_reading_order
import test_toki_library as fixtures
from test_toki_work_archive import add_chapter


class ReadingOrderTests(unittest.TestCase):
    def test_shared_cases_and_cross_runtime_parity(self):
        cases = json.loads((Path(__file__).parent / 'fixtures/reading_order_cases.json').read_text(encoding='utf-8'))
        inputs, expected = [], []
        for case in cases:
            rows = [{'number':i+1, 'sourceId':f'/work/{i+1}', 'sourceTitle':s} for i, s in enumerate(case['titles'])]
            original = json.dumps(rows)
            result = assign_reading_order(rows, case['work'])
            self.assertEqual([r['number'] for r in sorted(result,key=lambda r:r['readingOrder'])], case['expected'], case['name'])
            self.assertEqual([r['number'] for r in result if r['readingOrderWarning']], case.get('warnings',[]))
            self.assertEqual(json.dumps(rows), original)
            self.assertEqual(assign_reading_order(result, case['work']), result)
            inputs.append({'rows':rows, 'work':case['work']})
            expected.append(result)
        script = "import fs from 'node:fs'; import {assignReadingOrder} from './downloader_reading_order.js'; console.log(JSON.stringify(JSON.parse(fs.readFileSync(0,'utf8')).map(c=>assignReadingOrder(c.rows,c.work))))"
        proc = subprocess.run(['node','--input-type=module','-e',script],input=json.dumps(inputs),
            capture_output=True,text=True,encoding='utf-8',cwd=core.ROOT_DIR,timeout=30,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.assertEqual(proc.returncode,0,proc.stderr)
        self.assertEqual(json.loads(proc.stdout),expected)

    def test_ten_thousand_entries(self):
        rows = [{'number':i+1, 'sourceTitle':f'작품 {"외전" if i%5==0 else ""}{10000-i}화'} for i in range(10000)]
        start = time.perf_counter()
        result = assign_reading_order(rows, '작품')
        self.assertEqual(len({r['readingOrder'] for r in result}),10000)
        self.assertEqual(sum(r['readingGroup']=='extra' for r in result),2000)
        print(f'[reading order Python] 10000 entries: {(time.perf_counter()-start)*1000:.0f} ms')


class ReadingOrderStorageTests(unittest.TestCase):
    setUp = fixtures.LibraryTests.setUp
    work = fixtures.LibraryTests.work

    def test_cli_migration_and_archived_only_rebuild_use_same_order_without_redownload(self):
        job, root, _ = self.work()
        add_chapter(root, 2, '작품 a 외전1')
        add_chapter(root, 3, '작품 a 142화')
        add_chapter(root, 4, '작품 a 외전2')
        add_chapter(root, 5, '작품 a 143화')
        before_state = json.loads((root/'.toki-state.json').read_text(encoding='utf-8'))
        original = sorted(p.read_bytes() for p in root.rglob('*.jpg'))
        (self.root/'.library-cli-test').touch()
        command = [os.sys.executable, '-X', 'utf8', str(core.ROOT_DIR/'tests/fixtures/library_cli_host.py'), str(self.root)]
        def cli(*args):
            p = subprocess.run([*command,*args,'--json'],capture_output=True,text=True,encoding='utf-8',
                               cwd=core.ROOT_DIR,timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            return json.loads(p.stdout)
        preview = cli('rename-episodes','--job',job.job_id)
        self.assertEqual([r['readingOrder'] for r in preview['episodes']], [1,4,2,5,3])
        changed = cli('rename-episodes','--job',job.job_id,'--execute','--yes')
        after_state = json.loads((root/'.toki-state.json').read_text(encoding='utf-8'))
        self.assertEqual(after_state['completedEpisodes'],before_state['completedEpisodes'])
        self.assertEqual(set(after_state['completedEpisodeIds']),set(before_state['completedEpisodeIds']))
        self.assertEqual(sorted(p.read_bytes() for p in root.rglob('*.jpg')),original)
        self.assertEqual(cli('rename-episodes','--job',job.job_id)['renameCount'],0)
        result = cli('library','archive','--job',job.job_id,'--execute','--yes','--remove-originals')
        self.assertTrue(result['success'],result)
        archive = Path(result['results'][0]['archivePath'])
        expected = [r['folderName'] for r in sorted(changed['episodes'],key=lambda r:r['readingOrder'])]
        with zipfile.ZipFile(archive) as bundle:
            images = [n for n in bundle.namelist() if n.endswith('.jpg')]
            self.assertEqual([n.split('/')[0] for n in images[::3]],expected)
            self.assertEqual(sorted(bundle.read(n) for n in images),original)
        # Change only the source ordinals, keep reading semantics and IDs. All
        # originals are gone: the update must stream existing ZIP members.
        for name in ('.toki-state.json','metadata.json'):
            payload = json.loads((root/name).read_text(encoding='utf-8'))
            for row in payload['episodes']:
                row['number'] = 6-row['number']
            (root/name).write_text(json.dumps(payload),encoding='utf-8')
        updated = cli('library','archive','--job',job.job_id,'--execute','--yes')
        self.assertTrue(updated['success'],updated)
        with zipfile.ZipFile(archive) as bundle:
            images = [n for n in bundle.namelist() if n.endswith('.jpg')]
            self.assertEqual([n.split('/')[0] for n in images[::3]],expected)
            self.assertEqual(sorted(bundle.read(n) for n in images),original)

    def test_permutation_rollback_preserves_user_bytes_and_metadata(self):
        job, root, first = self.work()
        second = add_chapter(root,2,'작품 a 142화')
        # Controlled plan with two existing destinations forms a real rename
        # cycle, covering the transaction independently of title heuristics.
        plan = core.plan_episode_folder_rename(job.job_id)
        for mapping, destination in zip(plan['mappings'], (second,first)):
            mapping.update(destination=str(destination), samePath=False)
        guards = {p:p.read_bytes() for p in [root/'.toki-state.json',root/'metadata.json']}
        images = {p:p.read_bytes() for p in root.rglob('*.jpg')}
        writer = core._write_episode_rename_json
        def fail_state(path,payload):
            if path == root/'.toki-state.json':
                raise OSError('injected state failure')
            return writer(path,payload)
        with patch.object(core,'plan_episode_folder_rename',return_value=plan), patch.object(core,'_write_episode_rename_json',side_effect=fail_state):
            with self.assertRaisesRegex(OSError,'state failure'):
                core.rename_episode_folders(job.job_id)
        self.assertEqual({p:p.read_bytes() for p in guards},guards)
        self.assertEqual({p:p.read_bytes() for p in images},images)
        self.assertFalse(list(root.glob('.toki-episode-rename-*')))
