import { test } from 'node:test'
import assert from 'node:assert/strict'
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import { mkdtemp, writeFile, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'

test('bootstrap exits while its child remains alive and preserves native argument boundaries', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'nadoc-spawn-'))
  const script = join(dir, "child with spaces.cjs"), log = join(dir, 'host')
  const argument = `spaces ' quotes \" and $literal`
  try {
    await writeFile(script, "console.log(process.argv[2]); setTimeout(() => console.error('finished'), 3500)")
    await promisify(execFile)(process.execPath, [fileURLToPath(new URL('./prepared_share_spawn.mjs', import.meta.url)), log, script, argument], { timeout: 2000 })
    for (let i = 0; i < 20 && !(await readFile(log + '.stdout.log', 'utf8')); i++) await delay(50)
    assert.equal((await readFile(log + '.stdout.log', 'utf8')).trim(), argument)
    assert.equal(await readFile(log + '.stderr.log', 'utf8'), '')
  } finally {
    // Bounded child also exits on a failed assertion; wait before removing logs on Windows.
    await delay(4000)
    await rm(dir, { recursive: true, force: true })
  }
})
