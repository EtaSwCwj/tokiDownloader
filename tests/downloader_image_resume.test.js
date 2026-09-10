import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import vm from 'node:vm';
import http from 'node:http';
import { spawnSync } from 'node:child_process';
import { inspectImageList, collectEpisodeImages } from '../downloader_image_list.js';
import { downloadEpisodeImages, imageResumePaths } from '../downloader_image_resume.js';
import { existingImageFileIsValid, saveImage, runDownloadTasks, writeImageBufferAtomically } from '../down.js';

const chapter = { sourceId: '/manhwa/1/2', folderName: '000002 작품 2화' };
const payload = id => Buffer.from([255, 216, 255, 224, id, 255, 217]);
const images = (...ids) => ids.map(id => ({ src: `https://images.test/${id}.jpg`, extension: '.jpg' }));
async function fixture(action) {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'toki-image-resume-'));
    try { return await action(root); }
    finally { fs.rmSync(root, { recursive: true, force: true }); }
}
function options(extra = {}) {
    const fetched = [];
    return { fetched, validateFile: existingImageFileIsValid, runTasks: runDownloadTasks,
        saveImage: async (directory, fileName, url) => {
            fetched.push(url);
            await writeImageBufferAtomically(directory, fileName, payload(Number(new URL(url).pathname.match(/\d+/)[0])));
        }, ...extra };
}
const rootBytes = root => fs.readdirSync(path.join(root, chapter.folderName)).filter(name => /\.jpg$/.test(name))
    .sort().map(name => fs.readFileSync(path.join(root, chapter.folderName, name))[4]);

test('browser extraction includes hidden/lazy images, srcset, duplicates and unresolved errors', () => {
    const node = attrs => ({ attributes: Object.entries(attrs).map(([name, value]) => ({name, value})),
        getAttribute: name => attrs[name] ?? null, currentSrc: '', loading: 'lazy', scrollIntoView() {} });
    const nodes = [node({'data-src':'/1.jpg', src:'data:image/gif;base64,AA=='}),
        node({src:'/2.jpg'}), node({src:'/2.jpg'}), node({'data-srcset':'/low.jpg 1x, /high.jpg 2x'}),
        node({src:'data:image/gif;base64,AA=='}), node({})];
    const value = vm.runInNewContext(`(${inspectImageList.toString()})('reader img')`, {
        URL, location:{href:'https://images.test/reader'}, document:{readyState:'complete',
            querySelectorAll: selector => selector === 'reader img' ? nodes
                : [{scrollHeight:100,getAttribute:name=>name==='data-image-count'?'6':null}]} });
    assert.equal(value.images.length,4);
    assert.equal(value.images[2].src,value.images[1].src);
    assert.equal(value.images[3].src,'https://images.test/high.jpg');
    assert.equal(value.unresolved.length,2);
    assert.equal(value.expectedCounts[0],6);
});

function snapshot(list, extra = {}) {
    return {images:list,unresolved:[],expectedCounts:[],nodeCount:list.length,readerHeight:100,ready:true,...extra};
}
async function collect(sequence, options = {}) {
    let time=0, index=0;
    return collectEpisodeImages({evaluate:async()=>sequence[Math.min(index++,sequence.length-1)]}, {
        now:()=>time, wait:async ms=>{time+=ms;},pollMs:100,stableMs:300,timeoutMs:1000,...options });
}
test('list stabilization compares order, count and layout and waits for late insertion', async () => {
    const result = await collect([snapshot(images(1)),snapshot(images(1,2)),snapshot(images(2,1)),snapshot(images(2,1))]);
    assert.deepEqual(result,images(2,1));
});
test('declared count mismatch, unresolved images, zero lists and loading pages never become complete', async () => {
    for (const input of [snapshot(images(1),{expectedCounts:[2]}),snapshot(images(1),{unresolved:[{index:1}]}),
        snapshot([]),snapshot(images(1),{ready:false})]) {
        await assert.rejects(collect([input]),e=>e.errorCode==='incomplete_episode_image_list');
    }
});
test('a stalled browser snapshot respects the image-list deadline', async () => {
    await assert.rejects(collectEpisodeImages({evaluate:()=>new Promise(()=>{})},{timeoutMs:20}),
        error=>error.diagnostics.reason==='browser_snapshot_timeout');
});

test('first mapping never trusts legacy numeric files and preserves their bytes reversibly', async () => fixture(async root => {
    const folder=path.join(root,chapter.folderName);fs.mkdirSync(folder);
    fs.writeFileSync(path.join(folder,'0000.jpg'),payload(99));
    fs.writeFileSync(path.join(folder,'0001.jpg'),payload(98));
    fs.writeFileSync(path.join(folder,'notes.txt'),'user note');
    const deps=options();const result=await downloadEpisodeImages(root,chapter,images(1,2),deps);
    assert.equal(result.reused,0);assert.equal(deps.fetched.length,2);
    assert.deepEqual(rootBytes(root),[1,2]);
    assert.equal(fs.readFileSync(path.join(result.backupPath,'0000.jpg'))[4],99);
    assert.equal(fs.readFileSync(path.join(folder,'notes.txt'),'utf8'),'user note');
}));
test('unchanged reinspection skips all downloads and file copies', async () => fixture(async root => {
    await downloadEpisodeImages(root,chapter,images(1,2),options());
    const deps=options({copyFile:async()=>{throw Error('must not copy');}});
    const result=await downloadEpisodeImages(root,chapter,images(1,2),deps);
    assert.equal(result.reused,2);assert.equal(deps.fetched.length,0);
}));
test('insertion and reversal reuse by URL rather than index; duplicate occurrences remain', async () => fixture(async root => {
    await downloadEpisodeImages(root,chapter,images(1,2),options());
    const deps=options();const result=await downloadEpisodeImages(root,chapter,images(2,3,1,2),deps);
    assert.deepEqual(rootBytes(root),[2,3,1,2]);assert.deepEqual(deps.fetched,images(3).map(i=>i.src));
    assert.equal(result.reused,3);
}));
test('same-index changed URL downloads replacement; query strings are not stripped', async () => fixture(async root => {
    await downloadEpisodeImages(root,chapter,images(1),options());
    const deps=options();await downloadEpisodeImages(root,chapter,[{...images(2)[0],src:'https://images.test/2.jpg?v=2'}],deps);
    assert.equal(deps.fetched.length,1);assert.deepEqual(rootBytes(root),[2]);
}));
test('shrinking lists and mid-download changes cannot publish or replace old raw images', async () => fixture(async root => {
    await downloadEpisodeImages(root,chapter,images(1,2),options());
    await assert.rejects(downloadEpisodeImages(root,chapter,images(1),options()),e=>e.diagnostics.reason==='list_shrank');
    await assert.rejects(downloadEpisodeImages(root,chapter,images(2,1,3),options({verifyList:async()=>images(2,1,3,4)})),
        e=>e.diagnostics.reason==='list_changed_during_download');
    assert.deepEqual(rootBytes(root),[1,2]);
    const deps=options();await downloadEpisodeImages(root,chapter,images(2,1,3,4),deps);
    assert.deepEqual(deps.fetched,images(4).map(i=>i.src));assert.deepEqual(rootBytes(root),[2,1,3,4]);
}));
test('network interruption keeps durable objects; retry only fetches absent or invalid objects', async () => fixture(async root => {
    const deps=options();const normal=deps.saveImage;
    deps.saveImage=async(d,f,u)=>{if(u.endsWith('/2.jpg')) throw Error('network interrupted');await normal(d,f,u);};
    await assert.rejects(downloadEpisodeImages(root,chapter,images(1,2,3),deps));
    const paths=imageResumePaths(root,chapter);const ledger=JSON.parse(fs.readFileSync(paths.manifest));
    assert.equal(ledger.phase,'downloading');
    fs.writeFileSync(path.join(paths.objects,ledger.images[2].objectName),Buffer.alloc(0));
    const again=options();await downloadEpisodeImages(root,chapter,images(1,2,3),again);
    assert.deepEqual(again.fetched,images(2,3).map(i=>i.src));assert.deepEqual(rootBytes(root),[1,2,3]);
}));
test('actual process death after an atomic object save resumes without a numeric guess', async () => fixture(async root => {
    const script=path.resolve('tests/fixtures/image_resume_crash.mjs');
    const child=spawnSync(process.execPath,[script,root],{windowsHide:true,encoding:'utf8'});
    assert.equal(child.status,77,child.stderr);
    const again=options();await downloadEpisodeImages(root,chapter,images(1,2),again);
    assert.deepEqual(again.fetched,images(2).map(i=>i.src));assert.deepEqual(rootBytes(root),[1,2]);
}));
test('projection failure is recoverable with no network or lost old bytes', async () => fixture(async root => {
    await downloadEpisodeImages(root,chapter,images(1,2),options());
    const {copyFile:unused,...deps}=options();
    // Fail while publishing, after safe copies of existing images were staged.
    deps.copyFile=async(source,target)=>{
        if(path.dirname(target)===path.join(root,chapter.folderName)) throw Error('disk interruption');
        fs.copyFileSync(source,target);
    };
    await assert.rejects(downloadEpisodeImages(root,chapter,images(2,1),deps));
    const again=options();await downloadEpisodeImages(root,chapter,images(2,1),again);
    assert.equal(again.fetched.length,0);assert.deepEqual(rootBytes(root),[2,1]);
}));
test('manifest must persist before downloading; invalid paths cannot be trusted', async () => fixture(async root => {
    const deps=options({writeManifest:async()=>{throw Error('checkpoint denied');}});
    await assert.rejects(downloadEpisodeImages(root,chapter,images(1),deps));assert.equal(deps.fetched.length,0);
    await downloadEpisodeImages(root,chapter,images(1),options());
    const paths=imageResumePaths(root,chapter);const ledger=JSON.parse(fs.readFileSync(paths.manifest));
    ledger.images[0].objectName='../outside.jpg';fs.writeFileSync(paths.manifest,JSON.stringify(ledger));
    await assert.rejects(downloadEpisodeImages(root,chapter,images(1),options()),e=>e.diagnostics.reason==='invalid_resume_paths');
}));
test('linked chapter paths cannot redirect reuse, backups or publication', async () => fixture(async root => {
    const target=path.join(root,'unrelated');fs.mkdirSync(target);
    fs.writeFileSync(path.join(target,'0000.jpg'),payload(99));
    fs.symlinkSync(target,path.join(root,chapter.folderName),process.platform==='win32'?'junction':'dir');
    await assert.rejects(downloadEpisodeImages(root,chapter,images(1),options()),/Linked image resume path/);
    assert.equal(fs.readFileSync(path.join(target,'0000.jpg'))[4],99);
}));
test('missing raw image after completion is downloaded; stale completion metadata is not enough', async () => fixture(async root => {
    await downloadEpisodeImages(root,chapter,images(1,2),options());
    fs.unlinkSync(path.join(root,chapter.folderName,'0001.jpg'));
    const deps=options();await downloadEpisodeImages(root,chapter,images(1,2),deps);
    assert.deepEqual(deps.fetched,images(2).map(i=>i.src));assert.deepEqual(rootBytes(root),[1,2]);
}));
test('ZIP-only episodes retain the existing early exclusion before any image-list verification', () => {
    const source=fs.readFileSync(new URL('../down.js',import.meta.url),'utf8');
    assert.ok(source.indexOf('selection.links.filter(item => !item.archiveExists)')<source.indexOf('await collectEpisodeImages(page)'));
    assert.ok(source.indexOf('await downloadEpisodeImages(')<source.lastIndexOf('completedEpisodes.add(parseInt(link[i].num))'));
});

const chromePath = process.env.TOKI_TEST_CHROME || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
test('hidden real Chromium handles delayed DOM, lazy/hidden images, URL reorder and insertion', {
    skip:!fs.existsSync(chromePath), timeout:30000,
}, async () => fixture(async root => {
    const {default:puppeteer}=await import('rebrowser-puppeteer-core');
    const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII=','base64');
    const server=http.createServer((request,response)=>{
        if(request.url.endsWith('.png')) {response.writeHead(200,{'Content-Type':'image/png'});response.end(png);return;}
        response.writeHead(200,{'Content-Type':'text/html; charset=utf-8'});
        response.end(`<div class="theme-viewer-images" data-image-count="2"><img src="/1.png"></div>
          <script>setTimeout(()=>{const i=document.createElement('img');i.dataset.src='/2.png';
          i.style.display='none';document.querySelector('div').append(i);},350)</script>`);
    });
    await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
    let browser;
    try {
        browser=await puppeteer.launch({executablePath:chromePath,headless:true,args:['--disable-gpu','--no-first-run']});
        const page=await browser.newPage();await page.goto(`http://127.0.0.1:${server.address().port}/`);
        const list=await collectEpisodeImages(page,{stableMs:400,pollMs:100});
        assert.equal(list.length,2);assert.ok(list[1].src.endsWith('/2.png'));
        const fetched=[];
        const deps={validateFile:existingImageFileIsValid,runTasks:runDownloadTasks,verifyList:()=>collectEpisodeImages(page,{stableMs:300,pollMs:100}),
            saveImage:async(d,f,u)=>{fetched.push(u);await saveImage(d,f,u,{backoffSeconds:0,
                download:async src=>Buffer.from(await (await fetch(src)).arrayBuffer())});}};
        await downloadEpisodeImages(root,chapter,list,deps);
        await page.evaluate(()=>{const root=document.querySelector('div');root.dataset.imageCount='3';
            root.prepend(root.lastElementChild);const image=document.createElement('img');image.src='/3.png';root.append(image);});
        const reordered=await collectEpisodeImages(page,{stableMs:300,pollMs:100});
        const result=await downloadEpisodeImages(root,chapter,reordered,deps);
        assert.equal(result.reused,2);assert.equal(fetched.length,3);
        const ledger=JSON.parse(fs.readFileSync(imageResumePaths(root,chapter).manifest));
        assert.deepEqual(ledger.published.map(item=>new URL(item.src).pathname),['/2.png','/1.png','/3.png']);
    } finally {
        if(browser) await browser.close();
        server.closeAllConnections();await new Promise(resolve=>server.close(resolve));
    }
}));
