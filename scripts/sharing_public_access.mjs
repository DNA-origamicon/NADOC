/** Verify the public route without using the host's private/MagicDNS resolver. */
import https from 'node:https'
import { isIP } from 'node:net'

export function isPublicIPv4(address) {
  if (isIP(address) !== 4) return false
  const [a, b] = address.split('.').map(Number)
  return !(a === 0 || a === 10 || a === 127 || a >= 224 ||
    (a === 100 && b >= 64 && b <= 127) || (a === 169 && b === 254) ||
    (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168) ||
    (a === 198 && (b === 18 || b === 19)))
}

export function publicRequest(origin, address, path) {
  const url = new URL(path, origin)
  return new Promise((resolve, reject) => {
    const request = https.get(url, { agent: false, servername: url.hostname,
      lookup: (_host, options, callback) => options.all
        ? callback(null, [{ address, family: 4 }]) : callback(null, address, 4),
    }, response => {
      const chunks = []; let size = 0
      response.on('data', chunk => {
        size += chunk.length
        if (size > 65536) request.destroy(new Error('Unexpected oversized public check response'))
        else chunks.push(chunk)
      })
      response.on('end', () => resolve({ status: response.statusCode, body: Buffer.concat(chunks).toString() }))
      response.on('error', reject)
    })
    const timeout = setTimeout(() => request.destroy(new Error('Public HTTPS check timed out')), 8000)
    request.on('close', () => clearTimeout(timeout)); request.on('error', reject)
  })
}

export async function checkPublicAccess(origin, probeId, { fetchDns = fetch, request = publicRequest } = {}) {
  const url = new URL(origin)
  if (url.protocol !== 'https:' || !/^[a-z0-9-]+\.[a-z0-9.-]+\.ts\.net$/i.test(url.hostname) || url.origin !== origin) throw new Error('Expected an exact Tailscale HTTPS origin')
  const checks = await Promise.all([
    ['Google public DNS', 'https://dns.google/resolve'],
    ['Cloudflare public DNS', 'https://cloudflare-dns.com/dns-query'],
  ].map(async ([name, endpoint]) => {
    try {
      const response = await fetchDns(`${endpoint}?name=${encodeURIComponent(url.hostname)}&type=A`, { headers: { Accept: 'application/dns-json' }, signal: AbortSignal.timeout(8000) })
      if (!response.ok) throw new Error(`Resolver HTTP ${response.status}`)
      const value = await response.json(), addresses = [...new Set((value.Answer ?? []).filter(row => row.type === 1).map(row => row.data))]
      const ok = value.Status === 0 && addresses.length > 0 && addresses.every(isPublicIPv4)
      return { name, ok, addresses: ok ? addresses : [], detail: ok ? 'Public relay addresses found' : value.Status === 3 ? 'Hostname not published (NXDOMAIN)' : 'No usable public relay addresses' }
    } catch (error) { return { name, ok: false, addresses: [], detail: error.message } }
  }))
  const finish = (state, message) => ({ state, message, checkedAt: new Date().toISOString(), checks })
  if (checks.some(check => !check.ok)) return finish('dns_pending', 'Public DNS is not ready. Keep hosting running while Tailscale publishes the hostname; this can take ten minutes or longer. Do not send the invitation yet.')
  const addresses = [...new Set(checks.flatMap(check => check.addresses))].slice(0, 4)
  for (const address of addresses) {
    try {
      const [health, management, editor] = await Promise.all([
        request(origin, address, '/__nadoc_public_health'), request(origin, address, '/host/shares'), request(origin, address, '/api/design'),
      ])
      const identity = JSON.parse(health.body)
      const ok = health.status === 200 && identity.service === 'nadoc-prepared-viewer' && identity.probeId === probeId && management.status === 404 && editor.status === 404
      checks.push({ name: `Public HTTPS relay ${address}`, ok, detail: ok ? 'Valid certificate, correct viewer, editor and management isolated' : 'Public route identity or isolation check failed' })
    } catch (error) { checks.push({ name: `Public HTTPS relay ${address}`, ok: false, detail: error.message }) }
  }
  return checks.every(check => check.ok)
    ? finish('ready', 'Public DNS and HTTPS verified. Guests need only the invitation and meeting password.')
    : finish('unreachable', 'Public HTTPS verification failed. Keep hosting running and recheck the connection details below.')
}
