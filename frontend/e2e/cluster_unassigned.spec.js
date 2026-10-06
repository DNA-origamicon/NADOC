import { test, expect } from '@playwright/test'
import { loadScaffoldedPart, trackConsoleErrors } from './helpers/scene_harness.js'

// Persistence: __e2e__cluster-repair*.nadoc and associated project snapshots;
// global teardown removes both, temporary viewer credentials, and reports.
// Isolated servers disable session caching; no custom outputs are written.
test('disconnected extrusion, repair, undo, and circular-pattern dropdown', async ({ page }) => {
  test.setTimeout(90_000)
  const errors = trackConsoleErrors(page)
  await loadScaffoldedPart(page, { doc: 'e2e-cluster-repair', name: 'cluster-repair' })
  const ids = await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    const { store } = await import('/src/state/store.js')
    const original = store.getState().currentDesign.cluster_transforms[0].id
    await api.addBundleSegment({ cells: [[0, 7], [1, 7], [1, 8], [1, 9], [0, 9], [0, 8]], lengthBp: 35 })
    const clusters = store.getState().currentDesign.cluster_transforms
    if (clusters.length !== 2) throw new Error(`Expected two clusters, got ${clusters.length}`)
    const added = clusters.find(c => c.id !== original)
    if (added.helix_ids.length !== 6) throw new Error('Incomplete extrusion cluster')
    await api.deleteCluster(added.id) // reproduce an older file’s unassigned extrusion
    return { original, added: added.id }
  })
  await page.locator('#right-tab-strip [data-tab=clustering]').click()
  const repair = page.locator('#cluster-repair-btn')
  if (!await repair.isVisible()) await page.locator('#cluster-panel-heading').click()
  await repair.click()
  await expect.poll(() => page.evaluate(async () => (await import('/src/state/store.js')).store.getState().currentDesign.cluster_transforms.length)).toBe(2)
  expect(await page.evaluate(async () => (await import('/src/state/store.js')).store.getState().currentDesign.cluster_transforms.map(c => c.id))).toEqual([ids.original, ids.added])
  await page.evaluate(async () => { await (await import('/src/api/client.js')).undo() })
  await expect.poll(() => page.evaluate(async () => (await import('/src/state/store.js')).store.getState().currentDesign.cluster_transforms.length)).toBe(1)
  await repair.click()
  await expect.poll(() => page.evaluate(async () => (await import('/src/state/store.js')).store.getState().currentDesign.cluster_transforms.length)).toBe(2)
  await page.getByRole('button', { name: 'Tools', exact: true }).hover()
  await page.locator('#menu-tools-circular-pattern').click()
  await page.locator(`#cluster-list [data-cluster-id="${ids.original}"]`).click()
  await expect(page.getByRole('combobox', { name: 'Cluster', exact: true }).locator('option')).toHaveCount(2)
  await page.getByRole('button', { name: 'Centered about', exact: true }).click()
  await expect(page.getByRole('combobox', { name: 'Center cluster', exact: true })).toHaveValue(ids.added)
  await page.getByRole('button', { name: 'Close Circular Pattern', exact: true }).click()
  expect(errors).toEqual([])
})
