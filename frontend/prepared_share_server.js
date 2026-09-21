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
        try { await launch({ root: server.config.root, controlFile: credentialPath() }) }
        catch (error) {
          // A bootstrap can time out after spawning successfully. Trust only an
          // authenticated response from the host, never a stale status file.
          try { return await hostRequest('/host/shares') } catch { throw error }
        }
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
        const content = path.match(/^\/__nadoc_share\/shares\/([a-f0-9]{32})\/content$/)
        if (req.method === 'POST' && content) {
          const chunks = []; let size = 0
          for await (const chunk of req) { size += chunk.length; if (size > 512 * 1024 * 1024) return send(413, { error: 'Package exceeds 512 MiB' }); chunks.push(chunk) }
          return send(200, await hostRequest(`/host/shares/${content[1]}/content`, { method: 'POST', headers: { 'X-NADOC-Title': req.headers['x-nadoc-title'] ?? 'Shared design' }, body: Buffer.concat(chunks) }))
        }
        const timeline = path.match(/^\/__nadoc_share\/shares\/([a-f0-9]{32})\/trajectory$/)
        if (['GET', 'POST'].includes(req.method) && timeline) {
          const chunks = []; let size = 0
          for await (const chunk of req) { size += chunk.length; if (size > 2048) return send(413, { error: 'Command too large' }); chunks.push(chunk) }
          return send(200, await hostRequest(`/host/shares/${timeline[1]}/trajectory`, { method: req.method, ...(req.method === 'POST' ? { body: Buffer.concat(chunks) } : {}) }))
        }
        const remove = path.match(/^\/__nadoc_share\/shares\/([a-f0-9]{32})$/)
        const broadcast = path.match(/^\/__nadoc_share\/shares\/([a-f0-9]{32})\/broadcast\/(start|camera|scene|pause|heartbeat)$/)
        if (req.method === 'POST' && broadcast) {
          const chunks = []; let size = 0
          const limit = broadcast[2] === 'scene' ? 512 * 1024 * 1024 : 4096
          for await (const chunk of req) { size += chunk.length; if (size > limit) return send(413, { error: 'Broadcast update too large' }); chunks.push(chunk) }
          return send(200, await hostRequest(`/host/shares/${broadcast[1]}/broadcast/${broadcast[2]}`, { method: 'POST',
            headers: { 'X-NADOC-Broadcast': req.headers['x-nadoc-broadcast'] ?? '' }, body: Buffer.concat(chunks) }))
        }
        if (req.method === 'DELETE' && remove) return send(200, await hostRequest(`/host/shares/${remove[1]}`, { method: 'DELETE' }))
        if (req.method === 'POST' && path === '/__nadoc_share/stop') return send(200, await hostRequest('/host/stop', { method: 'POST' }))
        return send(404, { error: 'Unknown share action' })
      } catch (error) { return send(503, { error: error.message }) }
    })
  }
  return { name: 'nadoc-local-prepared-share', apply: 'serve', configureServer: configure, configurePreviewServer: configure }
}
