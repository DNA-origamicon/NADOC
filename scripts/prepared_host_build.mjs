import { createHash } from 'node:crypto'
import { readFile, readdir } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

/** Identity of the code and cached viewer actually loaded by a detached host. */
export async function preparedHostBuildId(dist) {
  const scripts = dirname(fileURLToPath(import.meta.url)), viewer = join(scripts, '../frontend/src/viewer')
  const hash = createHash('sha256').update(await readFile(join(dist, 'viewer.html')))
  for (const [root, matches] of [[scripts, name => /^(prepared_|sharing_).*\.mjs$/.test(name) && !name.includes('.test.')], [viewer, name => name.endsWith('.js') && !name.endsWith('.test.js')]]) {
    for (const name of (await readdir(root)).filter(matches).sort()) hash.update(name).update(await readFile(join(root, name)))
  }
  return hash.digest('hex')
}
