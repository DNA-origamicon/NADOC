/** Starts a temporary internet viewer on this PC, with no incoming firewall rule. */
import { execFile, spawn } from 'node:child_process'
import { promisify } from 'node:util'
import { readFile, writeFile, chmod } from 'node:fs/promises'
import { resolve, join } from 'node:path'
const exec = promisify(execFile)
export async function launchPreparedShare({ root, controlFile, minutes = 120 }) {
  if (Number(process.versions.node.split('.')[0]) < 20) throw new Error('Hosting requires Node.js 20 or newer. Install Node.js LTS on this computer.')
  if (!Number.isInteger(minutes) || minutes < 1 || minutes > 480) throw new Error('Host lifetime must be 1–480 minutes')
  const repo = resolve(root, '..'), dist = join(root, 'dist')
  try { await readFile(join(dist, 'viewer.html')) }
  catch (error) {
    if (error.code !== 'ENOENT') throw error
    await exec(process.execPath, [join(root, 'node_modules/vite/bin/vite.js'), 'build'], {
      cwd: root, timeout: 120000, maxBuffer: 8 * 1024 * 1024,
    })
  }
  // Pre-create privately: Windows UNC file creation otherwise inherits mode 0644.
  for (const file of [controlFile, controlFile + '.status.json']) {
    await writeFile(file, '', { mode: 0o600 }); await chmod(file, 0o600)
  }
  const wsl = process.platform === 'linux' && /microsoft/i.test(await readFile('/proc/version', 'utf8').catch(() => ''))
  if (wsl || process.platform === 'win32') {
    const windows = async path => wsl ? (await exec('wslpath', ['-w', path])).stdout.trim() : path
    try {
      // PowerShell Start-Process with redirected output can keep its caller alive
      // until the meeting ends. Only use PowerShell for executable discovery.
      const command = "$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; @{node=(Get-Command node.exe).Source; tailscale=(Get-Command tailscale.exe).Source} | ConvertTo-Json -Compress"
      const executables = JSON.parse((await exec('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', command], { timeout: 15000, windowsHide: true })).stdout)
      const node = wsl ? (await exec('wslpath', ['-u', executables.node])).stdout.trim() : executables.node
      const [bootstrap, script, windowsDist, windowsControl] = await Promise.all([
        windows(join(repo, 'scripts/prepared_share_spawn.mjs')),
        windows(join(repo, 'scripts/prepared_internet_host.mjs')), windows(dist), windows(controlFile),
      ])
      await exec(node, [bootstrap, windowsControl, script, '--dist', windowsDist, '--control-file', windowsControl,
        '--minutes', String(minutes), '--tailscale', executables.tailscale], { timeout: 15000, windowsHide: true })
    } catch (cause) {
      throw new Error('Could not start internet sharing. Check that Node.js and Tailscale are installed and available on the hosting PC, then try again.', { cause })
    }
  } else {
    // Verify the host prerequisite before detaching; guests need only a browser.
    try { await exec('tailscale', ['version'], { timeout: 10000 }) }
    catch { throw new Error('Install Tailscale on the hosting computer (https://tailscale.com/download), start its service, and sign in with tailscale up. Guests do not need Tailscale.') }
    const child = spawn(process.execPath, [join(repo, 'scripts/prepared_internet_host.mjs'), '--dist', dist, '--control-file', controlFile, '--minutes', String(minutes)], { stdio: 'ignore', detached: true })
    await new Promise((ok, fail) => { child.once('spawn', ok); child.once('error', fail) })
    child.unref()
  }
}
