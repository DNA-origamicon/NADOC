/** Short-lived native bootstrap; the meeting process owns its own lifetime. */
import { spawn } from 'node:child_process'
import { openSync, closeSync } from 'node:fs'

const [logBase, script, ...args] = process.argv.slice(2)
const descriptors = []
try {
  descriptors.push(openSync(logBase + '.stdout.log', 'a', 0o600))
  descriptors.push(openSync(logBase + '.stderr.log', 'a', 0o600))
  const child = spawn(process.execPath, [script, ...args], {
    detached: true, windowsHide: true, stdio: ['ignore', ...descriptors],
  })
  await new Promise((ok, fail) => { child.once('spawn', ok); child.once('error', fail) })
  child.unref()
} finally {
  for (const fd of descriptors) closeSync(fd)
}
