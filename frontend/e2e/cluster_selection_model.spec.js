import { test, expect } from '@playwright/test'
import { loadScaffoldedPart } from './helpers/scene_harness.js'

test('3D and sidebar cluster selection converge without member-strand state', async ({ page }) => {
  test.setTimeout(60_000)
  await loadScaffoldedPart(page, { doc: 'e2e-cluster-selection-model', name: 'cluster-selection-model' })
  await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    const { store } = await import('/src/state/store.js')
    const design = store.getState().currentDesign
    const strand = design.strands.find(s => s.domains?.length)
    const domain = strand.domains[0]
    await api.createCluster({
      name: 'Selection Cluster',
      helix_ids: [domain.helix_id],
      domain_ids: [{ strand_id: strand.id, domain_index: 0 }],
    })
  })
  await page.locator('#canvas').click({ position: { x: 5, y: 5 } })
  await page.keyboard.press('f')
  await page.waitForFunction(() => window.__nadocTest?.getClusterBeadScreenPositions?.().length > 0)

  await page.evaluate(() => {
    document.getElementById('select-filter-trigger')?.click()
    document.querySelector('#select-filter .sf-btn[data-key="clust"]')?.click()
  })
  const panels = []
  for (const selector of ['#menu-bar', '#left-panel', '#right-panel']) {
    const box = await page.locator(selector).boundingBox().catch(() => null)
    if (box) panels.push(box)
  }
  const points = (await page.evaluate(() => window.__nadocTest.getClusterBeadScreenPositions()))
    .filter(p => !panels.some(r => p.x >= r.x && p.x <= r.x + r.width && p.y >= r.y && p.y <= r.y + r.height))
  expect(points.length).toBeGreaterThan(0)

  const point = points[0]
  await page.mouse.click(point.x, point.y)
  await expect.poll(async () =>
    (await page.evaluate(() => window.__nadocTest.getCanonicalSelection())).items[0]?.kind,
  ).toBe('cluster')
  const state = await page.evaluate(() => ({
    selection: window.__nadocTest.getCanonicalSelection(),
    projected: window.__nadocTest.getMultiSelection(),
  }))
  const picked = { point, ...state }
  expect(picked.selection.items).toEqual([{ kind: 'cluster', id: picked.point.id }])
  expect(picked.projected.strandIds).toEqual([])

  await page.mouse.click(picked.point.x, picked.point.y)
  await expect.poll(async () =>
    (await page.evaluate(() => window.__nadocTest.getCanonicalSelection())).items.length,
  ).toBe(0)

  await page.evaluate(() => {
    document.querySelector('.right-tab-btn[data-tab="clustering"]')?.click()
  })
  const row = page.locator(`#cluster-list [data-cluster-id="${picked.point.id}"]`)
  await expect(row).toBeAttached()
  await page.evaluate((id) => {
    document.querySelector(`#cluster-list [data-cluster-id="${CSS.escape(id)}"]`)?.click()
  }, picked.point.id)
  expect(await page.evaluate(() => window.__nadocTest.getCanonicalSelection()))
    .toEqual(picked.selection)
})
