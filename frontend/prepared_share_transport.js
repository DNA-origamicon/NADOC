import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import { mkdtemp, writeFile, rm, readFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { resolve, join } from 'node:path'
import { createShareBridge } from './prepared_share_bridge.js'
const exec = promisify(execFile)
const wsl = process.platform === 'linux' ? readFile('/proc/version', 'utf8').then(value => /microsoft/i.test(value)).catch(() => false) : Promise.resolve(false)
let nodePath
const bridges = new Map()
export async function hostTransport({ root, controlFile, config, path, options }) {
  let status, value
  if (await wsl && (config.platform === 'win32' || !/^http:\/\/127\.0\.0\.1:/.test(config.url))) {
    // WSL NAT is not the physical LAN. Use a local Windows process, rather than
    // widening the guest firewall rule to admit the VM's control connection.
    nodePath ??= exec('powershell.exe', ['-NoProfile', '-Command', '(Get-Command node.exe).Source']).then(async result => (await exec('wslpath', ['-u', result.stdout.trim()])).stdout.trim())
    const windows = async file => (await exec('wslpath', ['-w', file])).stdout.trim()
    if (/\/broadcast\/(frame|camera|heartbeat|hold|pause|progress)$/.test(path)) {
      let bridge = bridges.get(controlFile)
      if (!bridge || bridge.closed) {
        bridge = createShareBridge(await nodePath, [await windows(resolve(root, '../scripts/prepared_share_bridge.mjs')), await windows(controlFile)])
        bridges.set(controlFile, bridge)
      }
      const result = await bridge.request(path, options)
      if (result.status < 200 || result.status >= 300) throw new Error(result.value.error ?? 'Sharing host request failed')
      return result.value
    }
    const scratch = options.body ? await mkdtemp(join(tmpdir(), 'nadoc-share-upload-')) : null
    try {
      const body = scratch ? join(scratch, 'snapshot.nadocview') : ''
      if (body) await writeFile(body, options.body, { mode: 0o600 })
      const args = [await windows(resolve(root, '../scripts/prepared_share_request.mjs')), await windows(controlFile), path, options.method ?? 'GET', body ? await windows(body) : '', options.headers?.['X-NADOC-Title'] ?? '', options.headers?.['X-NADOC-Broadcast'] ?? '']
      const result = await exec(await nodePath, args, { timeout: 25000, maxBuffer: 1024 * 1024 })
      ;({ status, value } = JSON.parse(result.stdout))
    } finally { if (scratch) await rm(scratch, { recursive: true, force: true }) }
  } else {
    const response = await fetch(config.url + path, { ...options, headers: { ...options.headers, Authorization: `Bearer ${config.token}` }, signal: AbortSignal.timeout(15000) })
    status = response.status; value = await response.json()
  }
  if (status < 200 || status >= 300) throw new Error(value.error ?? 'Sharing host request failed')
  // Query identity also makes opening a second part a real page navigation in
  // guest tabs running the first prototype, which predates hash-change routing.
  const decorate = share => { if (share?.url && /^[a-f0-9]{32}$/.test(share.id)) { const url = new URL(share.url); url.searchParams.set('view', share.id); share.url = url.href } return share }
  if (value.shares) value.shares.forEach(decorate); else decorate(value)
  return value
}
