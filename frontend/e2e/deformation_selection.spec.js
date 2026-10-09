import { test, expect } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { loadScaffoldedPart, trackConsoleErrors } from './helpers/scene_harness.js'

// Persisted parts use __e2e__; global teardown removes them and their project
// histories. Session caching is disabled by the config. Review screenshots are
// deliberately retained under .development-artifacts/deformation-selection/.
const evidence = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../.development-artifacts/deformation-selection')
for (const kind of ['bend', 'twist']) test(`${kind} exact mixed selection, cancel, apply and reopen`, async ({ page }) => {
  test.setTimeout(120_000)
  await page.setViewportSize({ width: 1800, height: 1000 })
  const errors = trackConsoleErrors(page)
  await loadScaffoldedPart(page, { doc: `__e2e__selection-${kind}`, name: `selection-${kind}` })
  await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    const { store } = await import('/src/state/store.js')
    const d = structuredClone(store.getState().currentDesign)
    const hid = d.helices[0].id
    d.strands = [{ id: 'selected', strand_type: 'scaffold', domains: [
      { helix_id: hid, start_bp: 0, end_bp: 99, direction: 'FORWARD' },
      { helix_id: hid, start_bp: 100, end_bp: 199, direction: 'FORWARD' }] },
      { id: 'stationary', strand_type: 'staple', domains: [{ helix_id: hid, start_bp: 0, end_bp: 199, direction: 'REVERSE' }] }]
    d.cluster_transforms = [{ id: 'partial', name: 'Selected domain', helix_ids: [hid], domain_ids: [{ strand_id: 'selected', domain_index: 1 }] }]
    d.feature_log = []; d.feature_log_cursor = -1; d.deformations = []
    await api.importDesign(JSON.stringify(d))
    const { createSelectionController } = await import('/src/scene/selection_controller.js')
    createSelectionController({ store }).replace([
      { kind: 'cluster', id: 'partial' }, { kind: 'domain', strandId: 'selected', domainIndex: 1 }])
    window.__nadocTest.applyCameraPoseForTest({ target: [0, 0, 33], position: [100, 20, 33] })
  })
  const read = () => page.evaluate(async () => {
    const { store } = await import('/src/state/store.js')
    const api = await import('/src/api/client.js')
    return { design: store.getState().currentDesign, geometry: (await api._request('GET', '/design/geometry')).nucleotides }
  })
  const before = await read()
  await page.getByRole('button', { name: 'Tools', exact: true }).hover()
  await page.locator(`#menu-tools-${kind}`).click()
  const popup = page.locator('.tool-popup[data-tool-panel="deform-panel"]')
  await expect(popup).toBeVisible()
  await expect(page.locator('#def-current-selection')).toContainText('Domain · selected [1]')
  expect(await page.evaluate(async () => { const e = await import('/src/scene/deformation_editor.js'); const s = (await import('/src/state/store.js')).store.getState(); return { state: e.getState(), active: s.deformToolActive, targets: e.getDeformSessionTargets(), selection: s.selection } })).toMatchObject({ state: 'BOTH', active: true })
  await expect(page.locator('#def-apply-btn')).toBeEnabled()
  await expect(page.locator('#def-plane-a-bp')).toHaveValue('100')
  await expect(page.locator('#def-plane-b-bp')).toHaveValue('199')
  const highlights = () => page.evaluate(() => {
    const scene = window.__nadocTest.scene
    return { corners: scene.getObjectByName('clusterSelectionCorners')?.visible ?? false,
      glow: scene.getObjectByName('selectionGlow')?.count ?? 0 }
  })
  await expect.poll(highlights).toEqual({ corners: false, glow: 0 })
  await page.locator('#def-plane-a-bp').fill('100'); await page.locator('#def-plane-a-bp').press('Tab')
  await page.locator('#def-plane-b-bp').fill('199'); await page.locator('#def-plane-b-bp').press('Tab')
  const input = page.locator(kind === 'bend' ? '#def-bend-angle' : '#def-twist-value')
  await input.fill('60'); await input.press('Tab')
  await page.evaluate(async () => (await import('/src/scene/deformation_editor.js')).waitForDeformationIdle())
  await page.locator('#def-change-selection').click()
  await expect(page.locator('#def-apply-btn')).toBeDisabled()
  await expect.poll(async () => (await highlights()).corners).toBe(true)
  expect((await read()).design.deformations).toHaveLength(0)
  // Clear keeps the panel open and cannot fall back to whole-design deformation.
  await page.locator('#def-clear-selection').click()
  await expect(page.locator('#def-apply-btn')).toBeDisabled()
  await page.evaluate(async () => {
    const { store } = await import('/src/state/store.js')
    const { createSelectionController } = await import('/src/scene/selection_controller.js')
    createSelectionController({ store }).replace([{ kind: 'strand', id: 'selected' }])
  })
  expect(await page.evaluate(async () => { const e = await import('/src/scene/deformation_editor.js'); const s = (await import('/src/state/store.js')).store.getState(); return { state: e.getState(), active: s.deformToolActive, targets: e.getDeformSessionTargets(), selection: s.selection } })).toMatchObject({ state: 'BOTH', active: true })
  await expect(page.locator('#def-apply-btn')).toBeEnabled()
  await expect(page.locator('#def-plane-a-bp')).toHaveValue('0')
  await expect(page.locator('#def-plane-b-bp')).toHaveValue('199')
  await expect.poll(highlights).toEqual({ corners: false, glow: 0 })
  await page.locator('#def-plane-a-bp').fill('0'); await page.locator('#def-plane-a-bp').press('Tab')
  await page.locator('#def-plane-b-bp').fill('199'); await page.locator('#def-plane-b-bp').press('Tab')
  await input.fill('60'); await input.press('Tab')
  await page.evaluate(async () => (await import('/src/scene/deformation_editor.js')).waitForDeformationIdle())
  fs.mkdirSync(evidence, { recursive: true })
  await page.screenshot({ path: path.join(evidence, `${kind}-preview.png`) })
  await page.locator('#def-apply-btn').click()
  await expect(popup).not.toBeVisible()
  await expect.poll(async () => (await read()).design.deformations?.length).toBe(1)
  let after = await read()
  expect(after.design.deformations[0].targets).toEqual([{ kind: 'strand', id: 'selected' }])
  const stationary = rows => rows.filter(n => n.strand_id === 'stationary')
  expect(stationary(after.geometry).length).toBeGreaterThan(0)
  expect(stationary(after.geometry)).toEqual(stationary(before.geometry))
  expect(after.geometry).not.toEqual(before.geometry)
  await page.evaluate(async () => (await import('/src/api/client.js')).undo())
  expect((await read()).geometry).toEqual(before.geometry)
  await page.evaluate(async () => (await import('/src/api/client.js')).redo())
  expect((await read()).geometry).toEqual(after.geometry)
  // Re-edit the persisted feature through the Feature Log UI, retaining scope.
  await page.locator('[title="Edit this feature"]').last().click()
  await expect(popup).toBeVisible()
  await expect(page.locator('#def-current-selection')).toContainText('Strand · selected')
  await input.fill('45'); await input.press('Tab')
  await page.locator('#def-apply-btn').click()
  await expect(popup).not.toBeVisible()
  const edited = await read()
  expect(edited.design.deformations).toHaveLength(1)
  expect(edited.design.deformations[0].target_ranges).toEqual(after.design.deformations[0].target_ranges)
  expect(stationary(edited.geometry)).toEqual(stationary(before.geometry))
  after = edited
  await page.evaluate(async kind => {
    const api = await import('/src/api/client.js')
    const file = `workspace/__e2e__selection-${kind}-saved.nadoc`
    await api.saveDesign(file); await api.loadDesign(file)
  }, kind)
  expect((await read()).geometry).toEqual(after.geometry)
  await page.screenshot({ path: path.join(evidence, `${kind}-reopened.png`) })
  expect(errors).toEqual([])
})
