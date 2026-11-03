import { test, expect } from '@playwright/test'
import { loadScaffoldedPart } from './helpers/scene_harness.js'

async function visibleAxes(page) {
  return page.evaluate(() => {
    const ctrl = window.__nadocTest.getDesignRenderer().getHelixCtrl()
    return ctrl.getAxisArrows().flatMap(a => [a.shaft, a.straightShaft,
      ...a.segments.flatMap(s => [s.mesh, s.tubeMesh])]).filter(m => m?.visible).length
  })
}

test('movable cluster eye and strand hide suppress rendered axes and restore them', async ({ page }) => {
  test.setTimeout(90_000)
  await loadScaffoldedPart(page, { doc: 'e2e-cluster-axis-visibility', name: 'cluster-axis-visibility' })
  await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    const design = window.__nadocTest.store.getState().currentDesign
    await api.createCluster({ name: 'Axis visibility', helix_ids: design.helices.map(h => h.id) })
    const testApi = window.__nadocTest
    const ctrl = testApi.getDesignRenderer().getHelixCtrl()
    const arrow = ctrl.getAxisArrows()[0]
    const center = arrow.aStart.clone().add(arrow.aEnd).multiplyScalar(.5)
    const span = arrow.aStart.distanceTo(arrow.aEnd)
    testApi.applyCameraPoseForTest({ target: center.toArray(),
      position: [center.x + span * 1.4, center.y + span * .3, center.z] })
  })
  await page.locator('#right-tab-strip [data-tab="clustering"]').click()
  const hide = page.locator('#cluster-list button[title="Hide cluster"]').last()
  await expect(hide).toBeVisible()
  await expect.poll(() => visibleAxes(page)).toBeGreaterThan(0)
  await page.screenshot({ path: '/tmp/nadoc-axis-before.png' })
  const point = await page.evaluate(() => window.__nadocTest.getClusterBeadScreenPositions()
    .find(p => p.x > 350 && p.x < 640 && p.y > 180 && p.y < 520))
  expect(point).toBeTruthy()
  await page.evaluate(() => document.querySelector('#select-filter .sf-btn[data-key="line"]').click())
  await page.mouse.move(point.x, point.y)
  const previewCount = () => page.evaluate(() => window.__nadocTest.scene.getObjectByName('previewGlow')?.count ?? 0)
  await page.screenshot({ path: '/tmp/nadoc-hover-debug.png' })
  await expect.poll(previewCount).toBeGreaterThan(0)

  await hide.click()
  await expect.poll(() => visibleAxes(page)).toBe(0)
  await page.screenshot({ path: '/tmp/nadoc-axis-hidden.png' })
  for (const key of ['line', 'strand', 'clust', 'base', 'ends']) {
    await page.evaluate(key => {
      document.querySelector('#select-filter .sf-btn[data-key="default"]').click()
      document.querySelector(`#select-filter .sf-btn[data-key="${key}"]`).click()
    }, key)
    expect(await page.evaluate(() => window.__nadocTest.getSelectionLevel()))
      .toBe({ line: 'domain', strand: 'strand', clust: 'cluster', base: 'base', ends: 'end' }[key])
    await page.mouse.move(point.x + 5, point.y + 5)
    await page.mouse.move(point.x, point.y)
    await expect.poll(previewCount).toBe(0)
  }

  await page.locator('#cluster-list button[title="Show cluster"]').last().click()
  await expect.poll(() => visibleAxes(page)).toBeGreaterThan(0)
  await page.evaluate(() => document.querySelector('#select-filter .sf-btn[data-key="line"]').click())
  await page.mouse.move(point.x + 5, point.y + 5)
  await page.mouse.move(point.x, point.y)
  await expect.poll(previewCount).toBeGreaterThan(0)
  await page.evaluate(() => {
    const t = window.__nadocTest
    t.visibility.hideStrands(t.store.getState().currentDesign.strands.map(s => s.id))
  })
  await expect.poll(() => visibleAxes(page)).toBe(0)
  // Hiding under a stationary cursor must remove the existing preview, too.
  await expect.poll(previewCount).toBe(0)
  await page.evaluate(() => window.__nadocTest.visibility.undo())
  await expect.poll(() => visibleAxes(page)).toBeGreaterThan(0)
})
