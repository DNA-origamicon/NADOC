import { test } from 'node:test'
import assert from 'node:assert/strict'
import { internetOrigin, hasInternetRoute } from './prepared_internet_config.mjs'
test('internet setup preserves unrelated private shares and refuses any occupied HTTPS listener', () => {
  const status = { BackendState: 'Running', Self: { DNSName: 'host.example.ts.net.' } }
  assert.equal(internetOrigin(status, { TCP: { 5173: { HTTPS: true } } }), 'https://host.example.ts.net')
  assert.throws(() => internetOrigin(status, { Foreground: { session: { TCP: { 443: { HTTPS: true } } } } }), /already used/)
  assert.throws(() => internetOrigin({ BackendState: 'NeedsLogin' }, {}), /sign in/)
  assert.throws(() => internetOrigin({ ...status, Self: { DNSName: 'evil.example/' } }, {}), /unavailable/)
})
test('readiness requires this exact public proxy, not an existing private editor route', () => {
  const target = 'http://127.0.0.1:5183', origin = 'https://host.example.ts.net'
  const config = { Web: { 'host.example.ts.net:443': { Handlers: { '/': { Proxy: target } } } }, AllowFunnel: { 'host.example.ts.net:443': true } }
  assert.equal(hasInternetRoute({ Foreground: { session: config } }, origin, target), true)
  assert.equal(hasInternetRoute({ ...config, AllowFunnel: {} }, origin, target), false)
  assert.equal(hasInternetRoute(config, origin, 'http://127.0.0.1:5173'), false)
})
