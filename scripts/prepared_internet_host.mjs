#!/usr/bin/env node
/** Owns one foreground Funnel and two loopback listeners for one meeting. */
import { execFile, spawn } from 'node:child_process'
import { promisify } from 'node:util'
import { writeFile, unlink } from 'node:fs/promises'
import { resolve } from 'node:path'
import { setTimeout as delay } from 'node:timers/promises'
import { createPreparedHost } from './prepared_view_host.mjs'
import { checkPublicAccess } from './sharing_public_access.mjs'
import { internetOrigin, hasInternetRoute } from './prepared_internet_config.mjs'
const exec = promisify(execFile)
const flags = Object.fromEntries(process.argv.slice(2).reduce((pairs, value, i, args) => i % 2 ? pairs : [...pairs, [value, args[i + 1]]], []))
const controlFile = flags['--control-file'], statusFile = controlFile + '.status.json'
const tailscale = flags['--tailscale'] || 'tailscale', target = 'http://127.0.0.1:5183'
let app, tunnel, expiryTimer, checkTimer, closing = false, output = ''
let publicAccess = { state: 'checking', message: 'Checking public DNS and HTTPS…', checks: [] }
const report = value => writeFile(statusFile, JSON.stringify(value), { mode: 0o600 })
const ts = async args => (await exec(tailscale, args, { windowsHide: true, timeout: 10000, maxBuffer: 1024 * 1024 })).stdout
async function stop(error) {
  if (closing) return
  closing = true; clearTimeout(expiryTimer); clearTimeout(checkTimer); app?.stop()
  // Foreground Funnel is owned by this CLI connection and disappears when it exits.
  // Never reset the provider: the user may have unrelated private editor shares.
  tunnel?.kill()
  await unlink(controlFile).catch(() => {})
  await report(error ? { state: 'error', error } : { state: 'stopped' })
}
async function main() {
  if (!controlFile) throw new Error('A private control file is required')
  await report({ state: 'starting' })
  const origin = internetOrigin(JSON.parse(await ts(['status', '--json'])), JSON.parse(await ts(['serve', 'status', '--json'])))
  app = await createPreparedHost({ dist: resolve(flags['--dist']), publicOrigin: origin, lifetimeMs: Number(flags['--minutes'] || 120) * 60000, getPublicAccess: () => publicAccess })
  const listen = (server, port) => new Promise((ok, fail) => { server.once('error', fail); server.listen(port, '127.0.0.1', ok) })
  await listen(app.server, 5183); await listen(app.controlServer, 5184)
  app.server.once('close', () => { void stop() })
  expiryTimer = setTimeout(() => { void stop() }, app.expiresAt - Date.now())
  tunnel = spawn(tailscale, ['funnel', '--yes', `--https=${new URL(origin).port || '443'}`, '--bg=false', target], { windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] })
  const collect = bytes => { output = (output + bytes.toString()).slice(-12000) }
  tunnel.stdout.on('data', collect); tunnel.stderr.on('data', collect)
  tunnel.on('error', error => { void stop(error.message) })
  tunnel.on('exit', () => { if (!closing) void stop(output.trim() || 'The internet sharing connection ended.') })
  for (let i = 0; i < 80 && !closing; i++) {
    if (hasInternetRoute(JSON.parse(await ts(['serve', 'status', '--json'])), origin, target)) {
      await writeFile(controlFile, JSON.stringify({ url: 'http://127.0.0.1:5184', token: app.controlToken, expiresAt: app.expiresAt, platform: process.platform, publicOrigin: origin }), { mode: 0o600 })
      const verify = async () => {
        try { publicAccess = await checkPublicAccess(origin, app.probeId) }
        catch (error) { publicAccess = { state: 'unreachable', message: error.message, checks: [] } }
        if (closing) return
        await report({ state: 'ready', origin, publicAccess })
        checkTimer = setTimeout(() => { void verify().catch(error => { void stop(error.message) }) }, 30000)
      }
      await report({ state: 'ready', origin, publicAccess })
      void verify().catch(error => { void stop(error.message) })
      return
    }
    // Account approval is host-only. Surface the provider's exact link in NADOC.
    if (/https:\/\/login\.tailscale\.com\/[^\s]+/.test(output)) throw new Error(output.trim())
    await delay(500)
  }
  if (!closing) throw new Error(output.trim() || 'The public sharing route did not become ready. Check Tailscale on the hosting PC.')
}
process.once('SIGINT', () => { void stop() }); process.once('SIGTERM', () => { void stop() })
main().catch(async error => { await stop(error.message); process.exitCode = 1 })
