/**
 * Playwright global teardown — remove parts/assemblies that e2e tests saved into
 * the workspace, so the library doesn't accumulate test clutter.
 *
 * Tests create their parts with the `__e2e__` name prefix (see scene_harness.js
 * loadScaffoldedPart + the File>New smoke tests); the auto-save writes them to
 * workspace/ as `__e2e__<name>_<n>.nadoc`. We delete exactly those, by prefix.
 * workspace/ is gitignored, so this only touches local recovery artifacts.
 *
 * Session-recovery docs (workspace/.session/<doc_id>/) are NOT cleaned here: the
 * e2e backends run with NADOC_DISABLE_SESSION_CACHE, so they never write any.
 *
 * Binding authoring rule (also in CLAUDE.md): every Playwright test that can
 * persist a workspace design/assembly MUST give it the __e2e__ prefix. A
 * different artifact class needs its own failure-safe cleanup registered with
 * the test or added here; cleanup in the successful test body is insufficient.
 */
import { readdir, rm } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const WORKSPACE = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', 'workspace')
const E2E_PREFIX = '__e2e__'

export default async function globalTeardown() {
  let files
  try { files = await readdir(WORKSPACE) } catch { return } // no workspace → nothing to clean
  const victims = files.filter(f =>
    (f.startsWith(E2E_PREFIX) || f.startsWith('e2e__')) &&
    (f.endsWith('.nadoc') || f.endsWith('.nass')))
  await Promise.all(victims.map(f => rm(path.join(WORKSPACE, f)).catch(() => {})))
  const scratch = path.join(WORKSPACE, 'playwright_tests')
  let scratchFiles = []
  try { scratchFiles = await readdir(scratch) } catch {}
  const scratchVictims = scratchFiles.filter(f =>
    f.startsWith(E2E_PREFIX) || f.startsWith('e2e__'))
  await Promise.all(scratchVictims.map(f => rm(path.join(scratch, f), { recursive: true, force: true })))
  if (victims.length || scratchVictims.length) console.log(`[e2e teardown] removed ${victims.length + scratchVictims.length} __e2e__ artifact(s)`)
}
