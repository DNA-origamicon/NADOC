import { test } from 'node:test'
import assert from 'node:assert/strict'
import { checkPublicAccess, isPublicIPv4 } from './sharing_public_access.mjs'
const origin = 'https://host.example.ts.net:10000'
const dns = async () => ({ ok: true, json: async () => ({ Status: 0, Answer: [{ type: 1, data: '208.111.34.11' }] }) })
const request = async (_origin, _address, path) => path === '/__nadoc_public_health' ? { status: 200, body: JSON.stringify({ service: 'nadoc-prepared-viewer', probeId: 'instance' }) } : { status: 404, body: '{}' }
test('private and MagicDNS answers cannot establish public availability', () => {
  for (const address of ['127.0.0.1', '10.1.2.3', '100.89.83.24', '172.16.2.3', '192.168.1.2', '169.254.1.1', '::1']) assert.equal(isPublicIPv4(address), false)
  assert.equal(isPublicIPv4('208.111.34.11'), true)
})
test('both public DNS resolvers and pinned HTTPS identity/isolation must pass', async () => {
  const paths = []
  const result = await checkPublicAccess(origin, 'instance', { fetchDns: dns, request: async (...args) => { paths.push(args); return request(...args) } })
  assert.equal(result.state, 'ready'); assert.equal(result.checks.length, 3)
  assert.ok(paths.every(([base, address]) => base === origin && address === '208.111.34.11'))
})
test('NXDOMAIN and private DNS cannot be hidden by a successful local viewer', async () => {
  for (const value of [{ Status: 3 }, { Status: 0, Answer: [{ type: 1, data: '100.89.83.24' }] }]) {
    const result = await checkPublicAccess(origin, 'instance', { fetchDns: async () => ({ ok: true, json: async () => value }), request: () => assert.fail('must not probe private routes') })
    assert.equal(result.state, 'dns_pending')
  }
})
test('wrong host identity, exposed management, or TLS failures never report ready', async () => {
  for (const probe of [async () => ({ status: 200, body: '{}' }), async () => { throw new Error('certificate mismatch') }]) {
    assert.equal((await checkPublicAccess(origin, 'instance', { fetchDns: dns, request: probe })).state, 'unreachable')
  }
})
test('resolver outage and disagreement remain pending', async () => {
  let count = 0
  const result = await checkPublicAccess(origin, 'instance', { fetchDns: async () => { if (++count === 2) throw new Error('offline'); return dns() }, request })
  assert.equal(result.state, 'dns_pending')
})
