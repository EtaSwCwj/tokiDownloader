import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import net from 'node:net';
import { ProxyAgent } from 'proxy-agent';

import {
    authenticatedProxyUrl,
    bandwidthDelayMs,
    normalizeProxyUrl,
    normalizeRequestDelayMs,
    normalizeSpeedLimitKib,
    proxyAuthenticationResponse,
    proxyCredentialsFromEnvironment,
} from '../downloader_network.js';

function listen(server) {
    return new Promise((resolve, reject) => {
        server.once('error', reject);
        server.listen(0, '127.0.0.1', () => {
            server.off('error', reject);
            resolve(server.address().port);
        });
    });
}

function closeServer(server) {
    return new Promise(resolve => server.close(resolve));
}

function requestThroughProxy(proxyUrl) {
    return new Promise((resolve, reject) => {
        const agent = new ProxyAgent({ getProxyForUrl: () => proxyUrl });
        const request = http.get(
            'http://127.0.0.1:9/proxy-auth-test',
            { agent },
            response => {
                const chunks = [];
                response.on('data', chunk => chunks.push(Buffer.from(chunk)));
                response.on('end', () => resolve({
                    statusCode: response.statusCode,
                    body: Buffer.concat(chunks).toString('utf8'),
                }));
            },
        );
        request.setTimeout(5000, () => request.destroy(new Error('local proxy timeout')));
        request.on('error', reject);
    });
}

function createAuthenticatedSocks5Server(observed) {
    return net.createServer(socket => {
        let buffer = Buffer.alloc(0);
        let state = 'greeting';
        socket.on('data', chunk => {
            buffer = Buffer.concat([buffer, chunk]);
            while (true) {
                if (state === 'greeting') {
                    if (buffer.length < 2 + buffer[1])
                        return;
                    buffer = buffer.subarray(2 + buffer[1]);
                    socket.write(Buffer.from([0x05, 0x02]));
                    state = 'auth';
                    continue;
                }
                if (state === 'auth') {
                    if (buffer.length < 2)
                        return;
                    const usernameLength = buffer[1];
                    if (buffer.length < 2 + usernameLength + 1)
                        return;
                    const passwordLength = buffer[2 + usernameLength];
                    const messageLength = 3 + usernameLength + passwordLength;
                    if (buffer.length < messageLength)
                        return;
                    observed.username = buffer.subarray(2, 2 + usernameLength).toString('utf8');
                    observed.password = buffer.subarray(
                        3 + usernameLength,
                        messageLength,
                    ).toString('utf8');
                    buffer = buffer.subarray(messageLength);
                    socket.write(Buffer.from([0x01, 0x00]));
                    state = 'connect';
                    continue;
                }
                if (state === 'connect') {
                    if (buffer.length < 5)
                        return;
                    const addressType = buffer[3];
                    const addressLength = addressType === 0x01
                        ? 4
                        : addressType === 0x04
                            ? 16
                            : 1 + buffer[4];
                    const messageLength = 4 + addressLength + 2;
                    if (buffer.length < messageLength)
                        return;
                    buffer = buffer.subarray(messageLength);
                    socket.write(Buffer.from([0x05, 0x00, 0x00, 0x01, 127, 0, 0, 1, 0, 0]));
                    state = 'http';
                    continue;
                }
                if (state === 'http') {
                    if (!buffer.includes(Buffer.from('\r\n\r\n')))
                        return;
                    socket.end(
                        'HTTP/1.1 200 OK\r\nContent-Length: 14\r\nConnection: close\r\n\r\nsocks-proxy-ok',
                    );
                    state = 'done';
                }
                return;
            }
        });
    });
}

test('proxy URLs accept HTTP and SOCKS without persisted credentials', () => {
    assert.equal(normalizeProxyUrl('http://127.0.0.1:8080'), 'http://127.0.0.1:8080');
    assert.equal(normalizeProxyUrl('socks5://localhost:1080'), 'socks5://localhost:1080');
    assert.throws(() => normalizeProxyUrl('ftp://localhost:21'), /HTTP/);
    assert.throws(() => normalizeProxyUrl('http://user:secret@localhost:8080'), /인증/);
});

test('proxy credentials answer proxy challenges only and stop repeated attempts', () => {
    const credentials = {
        username: 'proxy-user',
        password: 'secret-password',
        configured: true,
    };
    assert.deepEqual(
        proxyAuthenticationResponse({ source: 'Proxy' }, credentials),
        {
            response: 'ProvideCredentials',
            username: 'proxy-user',
            password: 'secret-password',
        },
    );
    assert.deepEqual(
        proxyAuthenticationResponse({ source: 'Server' }, credentials),
        { response: 'CancelAuth' },
    );
    assert.deepEqual(
        proxyAuthenticationResponse({ source: 'Proxy' }, credentials, true),
        { response: 'CancelAuth' },
    );
});

test('HTTP and SOCKS5 proxy agents authenticate against local servers', async () => {
    let httpAuthorization = '';
    const httpProxy = http.createServer((request, response) => {
        httpAuthorization = String(request.headers['proxy-authorization'] ?? '');
        response.writeHead(httpAuthorization === 'Basic dXNlcjpwYXNz' ? 200 : 407, {
            'Content-Type': 'text/plain',
        });
        response.end('http-proxy-ok');
    });
    const httpPort = await listen(httpProxy);
    try {
        const result = await requestThroughProxy(`http://user:pass@127.0.0.1:${httpPort}`);
        assert.equal(result.statusCode, 200);
        assert.equal(result.body, 'http-proxy-ok');
        assert.equal(httpAuthorization, 'Basic dXNlcjpwYXNz');
    }
    finally {
        await closeServer(httpProxy);
    }

    const observed = { username: '', password: '' };
    const socksProxy = createAuthenticatedSocks5Server(observed);
    const socksPort = await listen(socksProxy);
    try {
        const result = await requestThroughProxy(`socks5://user:pass@127.0.0.1:${socksPort}`);
        assert.equal(result.statusCode, 200);
        assert.equal(result.body, 'socks-proxy-ok');
        assert.deepEqual(observed, { username: 'user', password: 'pass' });
    }
    finally {
        await closeServer(socksProxy);
    }
});

test('proxy credentials stay out of command URLs and are safely encoded at runtime', () => {
    const credentials = proxyCredentialsFromEnvironment({
        TOKI_PROXY_USERNAME: 'user name',
        TOKI_PROXY_PASSWORD: 'p@ss:/word',
    });
    assert.deepEqual(credentials, {
        username: 'user name',
        password: 'p@ss:/word',
        configured: true,
    });
    assert.equal(
        authenticatedProxyUrl('socks5://localhost:1080', credentials),
        'socks5://user%20name:p%40ss%3A%2Fword@localhost:1080',
    );
    assert.deepEqual(
        proxyCredentialsFromEnvironment({}),
        { username: '', password: '', configured: false },
    );
    assert.throws(
        () => proxyCredentialsFromEnvironment({ TOKI_PROXY_USERNAME: 'user' }),
        /모두 필요/,
    );
});

test('speed and request pacing have bounded deterministic plans', () => {
    assert.equal(normalizeSpeedLimitKib(0), 0);
    assert.equal(normalizeSpeedLimitKib(1024), 1024);
    assert.equal(bandwidthDelayMs(1024 * 1024, 1024), 1000);
    assert.equal(normalizeRequestDelayMs(250), 250);
    assert.throws(() => normalizeSpeedLimitKib(1), /32/);
    assert.throws(() => normalizeRequestDelayMs(6000), /5000/);
});
