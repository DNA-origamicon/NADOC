import { readFile } from 'node:fs/promises'
import { setTimeout as delay } from 'node:timers/promises'
import { shareControlFile } from '../scripts/prepared_share_control.mjs'
import { hostTransport } from './prepared_share_transport.js'
import { launchPreparedShare } from '../scripts/launch_prepared_share.mjs'

export function preparedSharePlugin({ controlFile, launch = launchPreparedShare, transport = hostTransport } = {}) {
  function configure(server) {
    let starting = null
    const credentialPath = () => controlFile ?? shareControlFile(server.config.root, server.httpServer?.address()?.port ?? 5173)
    async function hostRequest(path, options = {}) {
      let config
      try { config = JSON.parse(await readFile(credentialPath(), 'utf8')) } catch { throw new Error('Sharing host is not running. Choose Create link to start it.') }
      if (!/^http:\/\/(?:\d{1,3}\.){3}\d{1,3}:\d+$/.test(config.url) || !/^[a-f0-9]{64}$/.test(config.token)) throw new Error('Invalid local share-host configuration')
      return transport({ root: server.config.root, controlFile: credentialPath(), config, path, options })
    }
    async function ensureHost() {
      try { return await hostRequest('/host/shares') } catch { /* explicitly started below */ }
      if (!starting) starting = (async () => {
        await launch({ root: server.config.root, controlFile: credentialPath() })
        for (let i = 0; i < 100; i++) {
          let state
          try { state = JSON.parse(await readFile(credentialPath() + '.status.json', 'utf8')) } catch { /* starting */ }
          if (state?.state === 'error') throw new Error(state.error)
          try { return await hostRequest('/host/shares') } catch { await delay(500) }
        }
        throw new Error('Internet sharing did not become ready. Check Tailscale on the hosting PC; guests do not need it.')
      })().finally(() => { starting = null })
      return starting
    }
    server.middlewares.use(async (req, res, next) => {
      const path = req.url?.split('?')[0]
      if (!path?.startsWith('/__nadoc_share/')) return next()
      const send = (code, value) => { res.writeHead(code, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' }); res.end(JSON.stringify(value)) }
      // Only a local, same-origin editor can publish. Never offer this on a guest server.
      if (!['127.0.0.1', '::1', '::ffff:127.0.0.1'].includes(req.socket.remoteAddress) ||
          !/^(localhost|127\.0\.0\.1|\[::1\])(?::\d+)?$/.test(req.headers.host ?? '') ||
          req.headers['sec-fetch-site'] === 'cross-site' ||
          (req.headers.origin && req.headers.origin !== `http://${req.headers.host}`) ||
          (req.method !== 'GET' && req.headers['x-nadoc-share'] !== '1')) return send(403, { error: 'Share links must be created from NADOC on the hosting PC.' })
      try {
        if (req.method === 'GET' && path === '/__nadoc_share/status') {
          try { return send(200, { running: true, ...await hostRequest('/host/shares') }) }
          catch { return send(200, { running: false, shares: [] }) }
        }
        if (req.method === 'POST' && path === '/__nadoc_share/start') return send(200, await ensureHost())
        if (req.method === 'POST' && path === '/__nadoc_share/create') {
          const chunks = []; let size = 0
          for await (const chunk of req) { size += chunk.length; if (size > 512 * 1024 * 1024) return send(413, { error: 'Package exceeds 512 MiB' }); chunks.push(chunk) }
          return send(201, await hostRequest('/host/shares', { method: 'POST', headers: { 'X-NADOC-Title': req.headers['x-nadoc-title'] ?? 'Shared design' }, body: Buffer.concat(chunks) }))
        }
        const remove = path.match(/^\/__nadoc_share\/shares\/([a-f0-9]{32})$/)
        if (req.method === 'DELETE' && remove) return send(200, await hostRequest(`/host/shares/${remove[1]}`, { method: 'DELETE' }))
        if (req.method === 'POST' && path === '/__nadoc_share/stop') return send(200, await hostRequest('/host/stop', { method: 'POST' }))
        return send(404, { error: 'Unknown share action' })
      } catch (error) { return send(503, { error: error.message }) }
    })
  }
  return { name: 'nadoc-local-prepared-share', apply: 'serve', configureServer: configure, configurePreviewServer: configure }
}
