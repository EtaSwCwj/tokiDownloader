import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import https from 'node:https';
import http from 'node:http';
import net from 'node:net';
import { ImageTransport, FragmentedHelloAgent, splitClientHello } from '../downloader_transport.js';
import { validateImageBuffer } from '../downloader_policy.js';

const cert = fs.readFileSync(new URL('./fixtures/tls/localhost-cert.pem', import.meta.url));
const key = fs.readFileSync(new URL('./fixtures/tls/localhost-key.pem', import.meta.url));
const jpeg = Buffer.from([0xff, 0xd8, 0xff, 0xe0, 1, 2, 3, 0xff, 0xd9]);
const trusted = {ca: cert, servername: 'localhost'};
async function listen(t, server) {
    const sockets = new Set();
    server.on('connection', socket => {
        sockets.add(socket);
        socket.on('error', () => {});
        socket.on('close', () => sockets.delete(socket));
    });
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    t.after(async () => {
        for (const socket of sockets) socket.destroy();
        await new Promise(resolve => server.close(resolve));
    });
    return server.address().port;
}
async function endpoint(t, handler = (_req, res) => res.end(jpeg)) {
    return listen(t, https.createServer({key, cert}, handler));
}
async function resetNormalHelloRelay(t, upstream) {
    const observed = {blocked: 0, fragmented: 0};
    const server = net.createServer(socket => {
        let buffered = Buffer.alloc(0);
        const inspect = chunk => {
            buffered = Buffer.concat([buffered, chunk]);
            if (buffered.length < 5 || buffered.length < 5 + buffered.readUInt16BE(3)) return;
            socket.off('data', inspect);
            const firstRecord = buffered.subarray(0, 5 + buffered.readUInt16BE(3));
            if (firstRecord.includes(Buffer.from('localhost'))) {
                observed.blocked++;
                socket.resetAndDestroy();
                return;
            }
            observed.fragmented++;
            socket.pause();
            const target = net.connect(upstream, '127.0.0.1', () => {
                target.write(buffered);
                socket.pipe(target);
                target.pipe(socket);
                socket.resume();
            });
            target.on('error', () => socket.destroy());
            socket.on('close', () => target.destroy());
        };
        socket.on('data', inspect);
    });
    return {port: await listen(t, server), observed};
}

test('ClientHello splitting preserves every handshake and trailing byte', () => {
    const name = 'localhost';
    const handshake = Buffer.concat([Buffer.from([1, 0, 0, 20]), Buffer.alloc(12), Buffer.from(name), Buffer.alloc(4)]);
    const header = Buffer.from([22, 3, 1, 0, 0]);
    header.writeUInt16BE(handshake.length, 3);
    const tail = Buffer.from([20, 3, 3, 0, 1, 1]);
    const wire = Buffer.concat([header, handshake, tail]);
    const parts = splitClientHello(wire, name);
    assert.ok(parts);
    const secondSize = parts[1].readUInt16BE(3);
    assert.deepEqual(Buffer.concat([parts[0].subarray(5), parts[1].subarray(5, 5 + secondSize)]), handshake);
    assert.deepEqual(parts[1].subarray(5 + secondSize), tail);
    assert.equal(parts[0].length, 5 + parts[0].readUInt16BE(3));
    assert.equal(parts[0].includes(Buffer.from(name)), false);
    assert.equal(parts[1].includes(Buffer.from(name)), false);
    for (const input of [Buffer.alloc(0), wire.subarray(0, 15), Buffer.from('plain text')])
        assert.equal(splitClientHello(input, name), null);
    assert.equal(splitClientHello(wire, 'missing.example'), null);
});

test('real HTTPS reset recovers with verified TLS and reuses the origin for concurrent images', async t => {
    const origin = await endpoint(t);
    const {port, observed} = await resetNormalHelloRelay(t, origin);
    const logs = [];
    let waits = 0, bytes = 0;
    const client = new ImageTransport({tlsOptions: trusted, timeoutMs: 3000, log: line => logs.push(line),
        wait: async () => { waits++; }, consume: async size => { bytes += size; }});
    t.after(() => client.close());
    const url = `https://127.0.0.1:${port}/image.jpg`;
    assert.deepEqual(await client.download(url, {}), jpeg);
    const images = await Promise.all(Array.from({length: 8}, () => client.download(url, {})));
    assert.ok(images.every(image => validateImageBuffer(image, '.jpg').valid));
    for (let i = 0; i < 30; i++) assert.deepEqual(await client.download(url, {}), jpeg);
    for (const sockets of Object.values(client.compatibleAgent.freeSockets))
        for (const socket of sockets) assert.equal(socket.listenerCount('secureConnect'), 0);
    assert.equal(observed.blocked, 1);
    assert.ok(observed.fragmented >= 1);
    assert.equal(client.compatibleOrigins.size, 1);
    assert.equal(logs.length, 1);
    assert.equal(waits, 40); // 1 failed normal + 39 successful requests
    assert.equal(bytes, jpeg.length * 39);
});

test('untrusted certificates and wrong hostnames stay rejected on fragmented TLS', async t => {
    const origin = await endpoint(t);
    const {port} = await resetNormalHelloRelay(t, origin);
    const client = new ImageTransport({tlsOptions: {servername: 'localhost'}, timeoutMs: 2000});
    t.after(() => client.close());
    await assert.rejects(client.download(`https://127.0.0.1:${port}/image.jpg`, {}),
        error => error.code === 'DEPTH_ZERO_SELF_SIGNED_CERT');
    assert.equal(client.compatibleOrigins.size, 0);
    const agent = new FragmentedHelloAgent({ca: cert, servername: 'wrong.example'});
    t.after(() => agent.destroy());
    await assert.rejects(new Promise((resolve, reject) => {
        https.get(`https://127.0.0.1:${origin}/`, {agent}, resolve).on('error', reject);
    }), error => error.code === 'ERR_TLS_CERT_ALTNAME_INVALID');
});

test('HTTP denial and resets after authenticated TLS never trigger the connection fallback', async t => {
    const port = await endpoint(t, (req, res) => {
        if (req.url === '/reset') req.socket.destroy();
        else { res.writeHead(403); res.end('denied'); }
    });
    const client = new ImageTransport({tlsOptions: trusted, timeoutMs: 2000});
    t.after(() => client.close());
    for (const route of ['/denied', '/reset'])
        await assert.rejects(client.download(`https://127.0.0.1:${port}${route}`, {}));
    assert.equal(client.compatibleOrigins.size, 0);
});

test('configured proxy errors do not open a direct fallback connection', async t => {
    let hits = 0;
    const port = await endpoint(t, (_req, res) => { hits++; res.end(jpeg); });
    class ResetProxy extends https.Agent {
        createConnection(_options, callback) {
            queueMicrotask(() => callback(Object.assign(new Error('proxy reset'), {code: 'ECONNRESET'})));
        }
    }
    const client = new ImageTransport({proxyAgent: new ResetProxy(), tlsOptions: trusted, timeoutMs: 1000});
    t.after(() => client.close());
    await assert.rejects(client.download(`https://127.0.0.1:${port}/`, {}), {code: 'ECONNRESET'});
    assert.equal(hits, 0);
    assert.equal(client.compatibleOrigins.size, 0);
});

test('image transport keeps redirect bounds, HTTP support and intentional rate-limit waits', async t => {
    const port = await listen(t, http.createServer((req, res) => {
        if (req.url === '/loop') { res.writeHead(302, {Location:'/loop'}); res.end(); }
        else if (req.url === '/redirect') { res.writeHead(302, {Location:'/image'}); res.end(); }
        else res.end(jpeg);
    }));
    const client = new ImageTransport({timeoutMs: 100, consume: async () => new Promise(resolve => setTimeout(resolve, 150))});
    t.after(() => client.close());
    assert.deepEqual(await client.download(`http://127.0.0.1:${port}/redirect`, {}), jpeg);
    await assert.rejects(client.download(`http://127.0.0.1:${port}/loop`, {}), /리디렉션/);
    await assert.rejects(client.download('file:///local.jpg', {}), /프로토콜/);
});

test('stalled TLS setup is time bounded and leaves no cached compatibility state', async t => {
    const port = await listen(t, net.createServer(() => {}));
    const client = new ImageTransport({timeoutMs: 80});
    t.after(() => client.close());
    await assert.rejects(client.download(`https://127.0.0.1:${port}/`, {}), {code:'ETIMEDOUT'});
    assert.equal(client.compatibleOrigins.size, 0);
});

test('closing an in-flight fragmented handshake releases its socket and write callback', async t => {
    const port = await listen(t, net.createServer(() => {}));
    const client = new ImageTransport({tlsOptions: trusted, timeoutMs: 2000});
    client.compatibleOrigins.add(`https://127.0.0.1:${port}`);
    const pending = client.download(`https://127.0.0.1:${port}/image`, {});
    const rejected = assert.rejects(pending);
    await new Promise(resolve => setTimeout(resolve, 10));
    client.close();
    await rejected;
    await new Promise(resolve => setTimeout(resolve, 20));
    assert.equal(Object.values(client.compatibleAgent.sockets).flat().length, 0);
});

test('recovered origin cache and connection pools stay bounded', async t => {
    const client = new ImageTransport();
    t.after(() => client.close());
    client.request = async (_target, _headers, compatible) => {
        if (!compatible) throw Object.assign(new Error('reset'), {code:'ECONNRESET', beforeTlsHandshake:true});
        return {buffer:jpeg};
    };
    for (let i = 0; i < 140; i++) await client.download(`https://image${i}.example/test`, {});
    assert.equal(client.compatibleOrigins.size, 128);
    assert.equal(client.compatibleOrigins.has('https://image0.example'), false);
    assert.equal(client.compatibleOrigins.has('https://image139.example'), true);
    assert.equal(client.normalAgent.maxTotalSockets, 16);
    assert.equal(client.compatibleAgent.maxTotalSockets, 16);
});
