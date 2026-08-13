import { test, expect } from '@playwright/test'

// Small enough for a deterministic UI gate while still containing real reference
// strands on reference-only and shared helix axes.
const DESIGN = '/home/joshua/NADOC/workspace/Ultimate Polymer Hinge.nadoc'

test('Simulation tab camera navigation ignores hidden reference geometry', async ({ page }) => {
  test.setTimeout(180_000)
  await page.goto('/')
  await page.evaluate(async (path) => {
    const api = await import('/src/api/client.js')
    await api.loadDesign(path)
    await api.getGeometry()
    document.getElementById('welcome-screen')?.classList.add('hidden')
    document.getElementById('left-panel')?.classList.remove('locked-hidden', 'hidden')
    document.querySelectorAll('#left-tab-strip .left-tab-btn')
      .forEach(button => { button.disabled = false })
    window.__leftSidebar?.refresh?.()
  }, DESIGN)

  const expected = await page.evaluate(async () => {
    const { navigationDesign, navigationGeometry } =
      await import('/src/scene/reference_navigation.js')
    const dbg = window.__NADOC_DBG__
    const state = { ...dbg.store.getState(), simulationTabActive: true }
    const geometry = navigationGeometry(state)
    const lo = [Infinity, Infinity, Infinity]
    const hi = [-Infinity, -Infinity, -Infinity]
    for (const n of geometry) for (let i = 0; i < 3; i++) {
      lo[i] = Math.min(lo[i], n.backbone_position[i])
      hi[i] = Math.max(hi[i], n.backbone_position[i])
    }
    const center = lo.map((v, i) => (v + hi[i]) * 0.5)
    return {
      center,
      geometryCount: geometry.length,
      totalGeometryCount: state.currentGeometry.length,
      navHelixCount: navigationDesign(state).helices.length,
    }
  })
  expect(expected.geometryCount).toBeGreaterThan(0)
  expect(expected.geometryCount).toBeLessThan(expected.totalGeometryCount)

  await page.locator('#left-tab-strip [data-tab="dynamics"]').click()
  await expect(page.locator('#tab-content-dynamics')).toBeVisible()

  const actual = await page.evaluate(() => ({
    simulationTabActive: window.__NADOC_DBG__.store.getState().simulationTabActive,
    target: window.__NADOC_DBG__.controls.target.toArray(),
    navHelixCount: window.__NADOC_DBG__.msNav.probe()?.helices,
  }))
  expect(actual.simulationTabActive).toBe(true)
  expect(actual.navHelixCount).toBe(expected.navHelixCount)
  for (let i = 0; i < 3; i++) expect(actual.target[i]).toBeCloseTo(expected.center[i], 5)
})
