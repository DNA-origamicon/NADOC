#!/usr/bin/env node
/** Cross-platform host setup/check command. Never prints invitations or credentials. */
import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { resolve } from 'node:path'
import { readFile } from 'node:fs/promises'
import { setTimeout as delay } from 'node:timers/promises'
import { shareControlFile } from './prepared_share_control.mjs'
import { launchPreparedShare } from './launch_prepared_share.mjs'
import { hostTransport } from '../frontend/prepared_share_transport.js'
const root = fileURLToPath(new URL('../frontend', import.meta.url))
const args = process.argv.slice(2), checkOnly = args.includes('--check')
if (args.some(arg => !['--check', '--browser'].includes(arg))) throw new Error('Usage: node scripts/setup_sharing.mjs [--check] [--browser]')
const controlFile = shareControlFile(resolve(root))
async function status() {
  const config = JSON.parse(await readFile(controlFile, 'utf8'))
  return hostTransport({ root, controlFile, config, path: '/host/shares', options: {} })
}
try {
  let current
  try { current = await status() } catch { /* setup below */ }
  if (!current && !checkOnly) {
    console.log('Preparing the guest viewer and temporary internet host. No designs are published.')
    await launchPreparedShare({ root, controlFile })
  }
  const deadline = Date.now() + (checkOnly ? 0 : 15 * 60 * 1000)
  let previous = ''
  do {
    try { current = await status() } catch {
      current = undefined
      let report
      try { report = JSON.parse(await readFile(controlFile + '.status.json', 'utf8')) } catch { /* launching */ }
      if (report?.state === 'error') throw new Error(report.error)
      if (checkOnly) throw new Error('Hosting is offline. Run node scripts/setup_sharing.mjs to set it up.')
    }
    if (current) {
      const access = current.publicAccess
      if (!access) throw new Error('This running host predates public-access checks. End hosting in File → Sharing, then rerun setup.')
      const summary = JSON.stringify(access.checks ?? []) + access.message
      if (summary !== previous) {
        console.log(access.message)
        for (const check of access.checks ?? []) console.log(`  ${check.ok ? 'PASS' : 'WAIT'} ${check.name}: ${check.detail}`)
        previous = summary
      }
      if (access.state === 'ready') {
        if (args.includes('--browser')) await new Promise((ok, fail) => {
          const child = spawn(process.execPath, [fileURLToPath(new URL('./check_sharing_browser.mjs', import.meta.url))], { stdio: 'inherit' })
          child.on('error', fail); child.on('exit', code => code === 0 ? ok() : fail(new Error('Guest browser check failed. Install Chromium with: cd frontend && npx playwright install chromium; then retry --check --browser.')))
        })
        console.log('Ready. Open File → Sharing and create an invitation. Guests need its link and password only.'); process.exitCode = 0; break }
    }
    if (Date.now() >= deadline) throw new Error('Public access is not verified yet. Hosting remains running; rerun with --check. See docs/sharing_host_setup.md for the reported setup step.')
    await delay(3000)
  } while (true)
} catch (error) { console.error(error.message); process.exitCode = 1 }
