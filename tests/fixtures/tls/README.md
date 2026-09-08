# Local test TLS identity

`localhost-cert.pem` and `localhost-key.pem` are a public, self-signed test-only
identity for loopback integration tests. The key is intentionally checked in; it
is not a user credential, deployment secret, or trusted production CA. Tests
explicitly trust this certificate only on their own client instances.
