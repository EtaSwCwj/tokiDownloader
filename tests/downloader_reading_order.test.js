import test from 'node:test';
import assert from 'node:assert/strict';
import cases from './fixtures/reading_order_cases.json' with {type:'json'};
import { assignReadingOrder } from '../downloader_reading_order.js';

for (const item of cases) test(`reading order: ${item.name}`, () => {
    const input = item.titles.map((sourceTitle,i) => ({number:i+1, sourceId:`/work/${i+1}`,sourceTitle}));
    const original = JSON.stringify(input);
    const result = assignReadingOrder(input, item.work);
    assert.deepEqual([...result].sort((a,b)=>a.readingOrder-b.readingOrder).map(r=>r.number), item.expected);
    assert.deepEqual(result.filter(r=>r.readingOrderWarning).map(r=>r.number), item.warnings || []);
    assert.equal(JSON.stringify(input), original);
    assert.deepEqual(result.map(r=>r.sourceId), input.map(r=>r.sourceId));
    assert.deepEqual(assignReadingOrder(result, item.work), result);
});

test('reading order preserves sparse site ordinals and inferred unnumbered anchors', () => {
    const input = [{number:10,sourceTitle:'작품 외전1'}, {number:20,sourceTitle:'작품 2화'}, {number:30,sourceTitle:'작품 1화'}];
    assert.deepEqual(assignReadingOrder(input,'작품').map(r=>r.readingOrder), [30,20,10]);
    const inferred = assignReadingOrder([{number:1,sourceTitle:'작품 9화',numberInferred:true},
        {number:2,sourceTitle:'작품 2화'}, {number:3,sourceTitle:'작품 1화'}], '작품');
    assert.deepEqual(inferred.map(r=>r.readingOrder), [1,3,2]);
    assert.equal(inferred[0].readingOrderWarning, 'unnumbered');
});

test('ten thousand entries use bounded metadata-only sorting', () => {
    const rows = Array.from({length:10000}, (_,i)=>({number:i+1,sourceTitle:`작품 ${i%5===0?'외전':''}${10000-i}화`}));
    const start = performance.now();
    const result = assignReadingOrder(rows,'작품');
    assert.equal(new Set(result.map(r=>r.readingOrder)).size, 10000);
    assert.equal(result.filter(r=>r.readingGroup==='extra').length, 2000);
    console.log(`[reading order Node] 10000 entries: ${Math.round(performance.now()-start)} ms`);
});
