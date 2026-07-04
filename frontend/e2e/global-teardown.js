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
    f.startsWith(E2E_PREFIX) && (f.endsWith('.nadoc') || f.endsWith('.nass')))
  await Promise.all(victims.map(f => rm(path.join(WORKSPACE, f)).catch(() => {})))
  if (victims.length) console.log(`[e2e teardown] removed ${victims.length} __e2e__ artifact(s) from workspace/`)
}
