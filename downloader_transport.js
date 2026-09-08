import http from 'node:http';
import https from 'node:https';
import net from 'node:net';
import tls from 'node:tls';
import { Duplex } from 'node:stream';

// Split a complete first ClientHello record without changing handshake bytes.
// TLS/certificate negotiation remains entirely with Node's verified TLS stack.
export function splitClientHello(chunk, hostname) {
    if (chunk.length < 10 || chunk[0] !== 22 || chunk[5] !== 1 || !hostname)
        return null;
    const end = 5 + chunk.readUInt16BE(3);
    if (end > chunk.length) return null;
    const name = Buffer.from(hostname);
    const position = chunk.indexOf(name, 9);
    if (position < 9 || position + name.length > end || name.length < 2) return null;
    const cut = position + Math.floor(name.length / 2);
    const first = Buffer.from(chunk.subarray(0, 5));
    const second = Buffer.from(first);
    first.writeUInt16BE(cut - 5, 3);
    second.writeUInt16BE(end - cut, 3);
    return [Buffer.concat([first, chunk.subarray(5, cut)]),
        Buffer.concat([second, chunk.subarray(cut, end), chunk.subarray(end)])];
}

class HelloRecordStream extends Duplex {
    constructor(options) {
        super();
        this.first = true;
        this.hostname = options.servername || options.host;
        this.raw = net.connect({host: options.host, port: options.port || 443,
            lookup: options.lookup, family: options.family, localAddress: options.localAddress});
        this.raw.setNoDelay(true);
        this.raw.on('data', chunk => { if (!this.push(chunk)) this.raw.pause(); });
        this.raw.on('end', () => this.push(null));
        this.raw.on('error', error => this.destroy(error));
        this.raw.on('close', () => { if (!this.destroyed) this.destroy(); });
    }
    _read() { this.raw.resume(); }
    _write(chunk, encoding, done) {
        const parts = this.first ? splitClientHello(chunk, this.hostname) : null;
        this.first = false;
        if (!parts) return this.raw.write(chunk, done);
        this.pendingWrite = done;
        this.raw.write(parts[0], error => {
            if (this.destroyed) return;
            if (error) return this.finishWrite(error);
            this.timer = setTimeout(() => {
                this.timer = null;
                if (!this.destroyed) this.raw.write(parts[1], error => this.finishWrite(error));
            }, 30);
        });
    }
    finishWrite(error) {
        const done = this.pendingWrite;
        this.pendingWrite = null;
        if (done) done(error);
    }
    _final(done) { this.raw.end(done); }
    _destroy(error, done) {
        clearTimeout(this.timer);
        this.raw.destroy();
        this.finishWrite(error || new Error('TLS connection closed'));
        done(error);
    }
}

export class FragmentedHelloAgent extends https.Agent {
    constructor(options = {}) { super({keepAlive: true, maxSockets: 16, maxTotalSockets: 16, maxFreeSockets: 4, ...options}); }
    createConnection(options) {
        return tls.connect({...options, socket: new HelloRecordStream(options)});
    }
}

export class ImageTransport {
    constructor({proxyAgent = null, wait = async () => {}, consume = async () => {},
        log = () => {}, timeoutMs = 60000, tlsOptions = {}} = {}) {
        this.proxyAgent = proxyAgent;
        this.wait = wait;
        this.consume = consume;
        this.log = log;
        this.timeoutMs = timeoutMs;
        this.normalAgent = new https.Agent({keepAlive: true, maxSockets: 16, maxTotalSockets: 16, maxFreeSockets: 4, ...tlsOptions});
        this.compatibleAgent = new FragmentedHelloAgent(tlsOptions);
        this.compatibleOrigins = new Set();
    }
    async download(src, headers, redirects = 0) {
        if (redirects > 5) throw new Error('이미지 리디렉션이 너무 많습니다.');
        const target = new URL(src);
        if (!['http:', 'https:'].includes(target.protocol)) throw new Error('지원하지 않는 이미지 URL 프로토콜입니다.');
        const useCompatible = !this.proxyAgent && this.compatibleOrigins.has(target.origin);
        let response;
        try {
            response = await this.request(target, headers, useCompatible);
        } catch (error) {
            // Only connection resets before authenticated TLS negotiation qualify.
            // Never change proxy routing, retry HTTP denial, or bypass certificate errors.
            if (this.proxyAgent || useCompatible || target.protocol !== 'https:'
                || error.code !== 'ECONNRESET' || !error.beforeTlsHandshake) throw error;
            response = await this.request(target, headers, true);
            if (!this.compatibleOrigins.has(target.origin)) {
                if (this.compatibleOrigins.size >= 128) this.compatibleOrigins.delete(this.compatibleOrigins.values().next().value);
                this.compatibleOrigins.add(target.origin);
                this.log(`이미지 연결 복구: ${target.hostname} · TLS 초기 메시지 분할 · 인증서 검증 유지`);
            }
        }
        if (response.location) return this.download(new URL(response.location, target).href, headers, redirects + 1);
        return response.buffer;
    }
    async request(target, headers, compatible) {
        await this.wait();
        const secure = target.protocol === 'https:';
        const transport = secure ? https : http;
        return new Promise((resolve, reject) => {
            let authenticated = !secure;
            let settled = false;
            let timer;
            const armTimeout = () => {
                clearTimeout(timer);
                timer = setTimeout(() => {
                    const error = new Error('이미지 요청 시간 초과');
                    error.code = 'ETIMEDOUT';
                    request.destroy(error);
                }, this.timeoutMs);
            };
            const finish = (error, result) => {
                if (settled) return;
                settled = true;
                clearTimeout(timer);
                if (error) {
                    error.beforeTlsHandshake = secure && !authenticated;
                    reject(error);
                } else resolve(result);
            };
            const request = transport.get(target, {
                headers,
                agent: this.proxyAgent || (secure ? compatible ? this.compatibleAgent : this.normalAgent : undefined),
            }, async response => {
                armTimeout();
                try {
                    if (response.statusCode >= 300 && response.statusCode < 400 && response.headers.location) {
                        response.destroy();
                        finish(null, {location: response.headers.location});
                        return;
                    }
                    if (response.statusCode < 200 || response.statusCode >= 300) {
                        response.destroy();
                        throw new Error(`HTTP ${response.statusCode}`);
                    }
                    const chunks = [];
                    let bytes = 0;
                    for await (const chunk of response) {
                        bytes += chunk.length;
                        if (bytes > 128 * 1024 * 1024) {
                            response.destroy();
                            throw new Error('이미지 응답이 128 MiB 안전 한도를 넘습니다.');
                        }
                        // User-configured rate limiting is intentional waiting,
                        // not a stalled server. Do not charge it to the timeout.
                        clearTimeout(timer);
                        await this.consume(chunk.length);
                        if (settled) return;
                        armTimeout();
                        chunks.push(Buffer.from(chunk));
                    }
                    finish(null, {buffer: Buffer.concat(chunks)});
                } catch (error) { finish(error); }
            });
            armTimeout();
            request.on('socket', socket => {
                if (secure && !socket.connecting && !socket.secureConnecting && socket.authorized) authenticated = true;
                if (secure && !authenticated) socket.once('secureConnect', () => { authenticated = true; });
            });
            request.on('error', error => finish(error));
        });
    }
    close() {
        this.normalAgent.destroy();
        this.compatibleAgent.destroy();
        this.proxyAgent?.destroy();
    }
}
