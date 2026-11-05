import { test, expect } from '@playwright/test'
import { loadScaffoldedPart } from './helpers/scene_harness.js'

test('3D and sidebar overhang selection converge on one canonical ref', async ({ page }) => {
  await loadScaffoldedPart(page, { doc: 'e2e-overhang-selection-model', name: 'overhang-selection-model' })
  await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    const testApi = window.__nadocTest
    const helix = testApi.store.getState().currentDesign.helices[0]
    const domain = { helix_id: helix.id, start_bp: 99, end_bp: 90, direction: 'REVERSE' }
    await api.addStrand({ domains: [domain] })
    await api.extrudeOverhang({ helixId: domain.helix_id, bpIndex: domain.end_bp,
      direction: domain.direction, isFivePrime: false, neighborRow: 0, neighborCol: 1, lengthBp: 8 })
    const nuc = testApi.store.getState().currentGeometry.find(n => n.overhang_id)
    const [x, y, z] = nuc.backbone_position
    testApi.applyCameraPoseForTest({ target: [x, y, z], position: [x + 15, y - 15, z + 5], up: [0, 0, 1] })
  })
  await page.waitForFunction(() => window.__nadocTest?.getOverhangBeadScreenPositions?.().length > 0)

  await page.evaluate(() => {
    document.getElementById('select-filter-trigger')?.click()
    document.querySelector('#select-filter .sf-btn[data-key="ovhangs"]')?.click()
  })
  const panels = []
  for (const selector of ['#menu-bar', '#left-panel', '#right-panel']) {
    const box = await page.locator(selector).boundingBox().catch(() => null)
    if (box) panels.push(box)
  }
  const points = (await page.evaluate(() => window.__nadocTest.getOverhangBeadScreenPositions()))
    .filter(p => !panels.some(r => p.x >= r.x && p.x <= r.x + r.width && p.y >= r.y && p.y <= r.y + r.height))
  expect(points.length).toBeGreaterThan(0)

  let picked = null
  for (const point of points) {
    await page.mouse.click(point.x, point.y)
    await page.waitForTimeout(100)
    const selection = await page.evaluate(() => window.__nadocTest.getCanonicalSelection())
    if (selection.items.length === 1 && selection.items[0].kind === 'overhang') {
      picked = { point, selection }
      break
    }
  }
  expect(picked, 'a real WebGL click should resolve an overhang ref').not.toBeNull()
  expect(picked.selection.items).toEqual([{ kind: 'overhang', id: picked.point.id }])

  // Fixed-filter sole re-click follows the approved clear rule.
  await page.mouse.click(picked.point.x, picked.point.y)
  await expect.poll(async () =>
    (await page.evaluate(() => window.__nadocTest.getCanonicalSelection())).items.length,
  ).toBe(0)

  // The sidebar is the other entry path; it must produce the identical snapshot.
  await page.locator('.right-tab-btn[data-tab="overhangs"]').click()
  if (!await page.locator('#overhang-list').isVisible()) await page.locator('#overhang-panel-heading').click()
  const row = page.locator(`#overhang-list [data-overhang-id="${picked.point.id}"]`)
  await expect(row).toBeVisible()
  await page.evaluate((id) => {
    document.querySelector(`#overhang-list [data-overhang-id="${CSS.escape(id)}"]`)?.click()
  }, picked.point.id)
  const sidebarSelection = await page.evaluate(() => window.__nadocTest.getCanonicalSelection())
  expect(sidebarSelection).toEqual(picked.selection)
})
