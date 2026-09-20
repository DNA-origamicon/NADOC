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
import { readFile, readdir, rm } from 'node:fs/promises'
import { cleanupProjectArtifacts } from './project_artifact_cleanup.js'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { bridgeCredentialsPath } from '../viewer_test_server.js'

const WORKSPACE = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', 'workspace')
const E2E_PREFIX = '__e2e__'

export default async function globalTeardown() {
  // Playwright may terminate Vite by signal, without httpServer's close event.
  // These are exclusively the isolated test ports; never remove the live key.
  const frontendRoot = path.resolve(WORKSPACE, '../frontend')
  const frontendPort = process.env.NADOC_E2E_FRONTEND_PORT || (process.env.NADOC_E2E_API_BASE?.endsWith(':8001') ? '5174' : '5175')
  if (Number(frontendPort) !== 5173) await rm(bridgeCredentialsPath(frontendRoot, Number(frontendPort)), { force: true })
  let files
  try { files = await readdir(WORKSPACE) } catch { return } // no workspace → nothing to clean
  const victims = files.filter(f =>
    (f.startsWith(E2E_PREFIX) || f.startsWith('e2e__')) &&
    (f.endsWith('.nadoc') || f.endsWith('.nass')))
  // Autosave also persists hidden project history. Resolve IDs before deleting parts,
  // and remove a store only if every snapshot proves it belongs to a test design.
  const projectIds = []
  for (const file of victims.filter(name => name.endsWith('.nadoc'))) {
    try { projectIds.push(JSON.parse(await readFile(path.join(WORKSPACE, file), 'utf8')).id) } catch {}
  }
  const projects = await cleanupProjectArtifacts(WORKSPACE, projectIds)
  if (projects.length) console.log(`[e2e teardown] removed ${projects.length} test project revision store(s)`)
  await Promise.all(victims.map(f => rm(path.join(WORKSPACE, f)).catch(() => {})))
  const scratch = path.join(WORKSPACE, 'playwright_tests')
  let scratchFiles = []
  try { scratchFiles = await readdir(scratch) } catch {}
  const scratchVictims = scratchFiles.filter(f =>
    f.startsWith(E2E_PREFIX) || f.startsWith('e2e__'))
  await Promise.all(scratchVictims.map(f => rm(path.join(scratch, f), { recursive: true, force: true })))
  // Direct NAMD surface drafts are a separate artifact class, named by the test.
  const surfaceDir = path.join(WORKSPACE, 'namd_surfaces')
  let surfaces = []
  try { surfaces = await readdir(surfaceDir) } catch {}
  await Promise.all(surfaces.filter(f => f.startsWith('__e2e__namd-peg-direct') && (f.endsWith('.json') || f.endsWith('.tmp')))
    .map(f => rm(path.join(surfaceDir, f), { force: true })))
  if (victims.length || scratchVictims.length) console.log(`[e2e teardown] removed ${victims.length + scratchVictims.length} __e2e__ artifact(s)`)
}
