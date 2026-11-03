import { test, expect } from '@playwright/test'
import { readFile, writeFile, mkdir } from 'node:fs/promises'
import path from 'node:path'
import { existsSync } from 'node:fs'
import { randomUUID } from 'node:crypto'
import { cleanupProjectArtifacts } from './project_artifact_cleanup.js'
let projectId
const root = path.resolve(import.meta.dirname, '../..')
const fixture = path.join(root, 'workspace/__e2e__relax-origami.nadoc')
// Only the __e2e__ copy may autosave. Global teardown also clears its project
// history. The retained app capture is explicit review evidence on Archive.
test.skip(!existsSync(path.join(root, 'workspace/Experimental/D003/D003_rigid_clusters_verified.nadoc')), 'Requires the locally reconstructed D003 experiment')
test.beforeAll(async () => {
  const design = JSON.parse(await readFile(path.join(root, 'workspace/Experimental/D003/D003_rigid_clusters_verified.nadoc'), 'utf8'))
  design.id = randomUUID(); projectId = design.id; design.metadata.name = '__e2e__relax-origami'
  console.log('RELAX_TEST_PROJECT', projectId)
  await writeFile(fixture, JSON.stringify(design))
})
test.afterAll(async () => {
  await cleanupProjectArtifacts(path.join(root, 'workspace'), projectId ? [projectId] : [])
  // Keep the prefixed fixture until global teardown: it supplies the project ID
  // for a second cleanup after any final autosave has finished.
})
test('Relax Origami menu applies an undoable bond fit to D003', async ({ page }) => {
  test.setTimeout(120000)
  const errors = []; page.on('pageerror', e => errors.push(e.message))
  page.on('response', async response => {
    if (response.url().endsWith('/design/relax-origami')) {
      const body = await response.json().catch(() => ({}))
      console.log('RELAX_RESPONSE', response.status(), body.detail || body.relaxation?.message)
    }
  })
  await page.goto(`/?doc=__e2e__relax-origami&open=${encodeURIComponent(fixture)}&open-type=design`)
  await page.waitForFunction(() => window.__nadocTest?.store?.getState()?.currentDesign?.helices?.length === 88)
  await page.locator('#menu-bar > .menu-item').filter({ has: page.locator('#menu-help-experimental') }).hover()
  await page.locator('#menu-help-experimental').hover()
  await page.locator('#menu-help-relax-origami').click()
  await page.getByRole('button', { name: 'Relax current design', exact: true }).click()
  try {
    const status = page.locator('.relax-origami-modal [role=status]')
    await expect(status).not.toHaveText('Minimizing backbone stretch…', { timeout: 90000 })
    await expect(status).toContainText('Maximum bond excess')
  } catch (error) {
    console.log('RELAX_DIALOG', await page.locator('.relax-origami-modal').allTextContents())
    throw error
  }
  const design = await page.evaluate(() => window.__nadocTest.store.getState().currentDesign)
  expect(design.cluster_transforms.map(c => c.helix_ids.length).sort()).toEqual([22, 22, 22, 22])
  expect(design.feature_log.at(-1).params.relaxation.bond_count).toBe(43)
  expect(design.feature_log.at(-1).op_kind).toBe('relax-origami')
  expect(design.feature_log.at(-1).params.relaxation.after.max_excess_nm).toBeLessThan(20)
  expect(design.feature_log.at(-1).params.relaxation.clashes.before.overlapping_body_pairs).toBe(6)
  expect(design.feature_log.at(-1).params.relaxation.clashes.after.overlapping_body_pairs).toBe(0)
  expect(design.feature_log.at(-1).params.relaxation.clashes.after.minimum_axis_envelope_gap_nm).toBeGreaterThan(2.04)
  await page.locator('.modal__close').last().click()
  await page.evaluate(() => {
    const points = window.__nadocTest.store.getState().currentGeometry.map(n => n.backbone_position)
    const lo = [0, 1, 2].map(i => Math.min(...points.map(p => p[i])))
    const hi = [0, 1, 2].map(i => Math.max(...points.map(p => p[i])))
    const target = lo.map((x, i) => (x + hi[i]) / 2)
    const distance = 2 * Math.max(...hi.map((x, i) => x - lo[i]))
    window.__nadocTest.applyCameraPoseForTest({ position: [target[0] + distance, target[1], target[2]], target, up: [0, 1, 0] })
  })
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
  const evidence = path.join(root, '.development-artifacts/relax-origami')
  await mkdir(evidence, { recursive: true })
  await page.screenshot({ path: path.join(evidence, 'app-clash-aware.png') })
  const undone = await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    await api.undo()
    return window.__nadocTest.store.getState().currentDesign.feature_log.some(e => e.op_kind === 'relax-origami')
  })
  expect(undone).toBe(false)
  expect(errors).toEqual([])
})
