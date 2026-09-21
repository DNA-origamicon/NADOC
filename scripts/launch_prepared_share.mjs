/** Starts a temporary internet viewer on this PC, with no incoming firewall rule. */
import { execFile, spawn } from 'node:child_process'
import { promisify } from 'node:util'
import { readFile, writeFile, chmod } from 'node:fs/promises'
import { resolve, join } from 'node:path'
const exec = promisify(execFile)
const quote = value => `'${String(value).replaceAll("'", "''")}'`
export async function launchPreparedShare({ root, controlFile, minutes = 120 }) {
  if (!Number.isInteger(minutes) || minutes < 1 || minutes > 480) throw new Error('Host lifetime must be 1–480 minutes')
  const repo = resolve(root, '..'), dist = join(root, 'dist')
  await readFile(join(dist, 'viewer.html'))
  // Pre-create privately: Windows UNC file creation otherwise inherits mode 0644.
  for (const file of [controlFile, controlFile + '.status.json']) {
    await writeFile(file, '', { mode: 0o600 }); await chmod(file, 0o600)
  }
  const wsl = process.platform === 'linux' && /microsoft/i.test(await readFile('/proc/version', 'utf8').catch(() => ''))
  if (wsl || process.platform === 'win32') {
    const windows = async path => wsl ? (await exec('wslpath', ['-w', path])).stdout.trim() : path
    const [script, windowsDist, windowsControl] = await Promise.all([windows(join(repo, 'scripts/prepared_internet_host.mjs')), windows(dist), windows(controlFile)])
    const args = [script, '--dist', windowsDist, '--control-file', windowsControl, '--minutes', String(minutes)]
    const command = `$ErrorActionPreference='Stop'; $node=(Get-Command node.exe).Source; $ts=(Get-Command tailscale.exe).Source; $argv=@(${args.map(quote).join(',')},'--tailscale',$ts); $quoted=($argv | ForEach-Object { '"' + $_.Replace('"','\\"') + '"' }) -join ' '; Start-Process -FilePath $node -ArgumentList $quoted -WindowStyle Hidden -RedirectStandardOutput ${quote(windowsControl + '.stdout.log')} -RedirectStandardError ${quote(windowsControl + '.stderr.log')}`
    await exec('powershell.exe', ['-NoProfile', '-EncodedCommand', Buffer.from(command, 'utf16le').toString('base64')], { timeout: 15000 })
  } else {
    // Verify the host prerequisite before detaching; guests need only a browser.
    await exec('tailscale', ['version'], { timeout: 10000 })
    const child = spawn(process.execPath, [join(repo, 'scripts/prepared_internet_host.mjs'), '--dist', dist, '--control-file', controlFile, '--minutes', String(minutes)], { stdio: 'ignore', detached: true })
    child.unref()
  }
}
