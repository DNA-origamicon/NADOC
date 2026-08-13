import { test, expect } from '@playwright/test'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

// Small enough for a deterministic UI gate while still containing real reference
// strands on reference-only and shared helix axes.
const HERE = path.dirname(fileURLToPath(import.meta.url))
const DESIGN = path.resolve(HERE, '../../tests/smoke/smoke_design.nadoc')

test('Simulation tab ignores hidden references without moving the camera', async ({ page }) => {
  test.setTimeout(180_000)
  await page.goto('/')
  await page.evaluate(async (path) => {
    const api = await import('/src/api/client.js')
    await api.loadDesign(path)
    await api.getGeometry()
    const dbg = window.__NADOC_DBG__
    const design = dbg.store.getState().currentDesign
    dbg.store.setState({
      currentDesign: {
        ...design,
        strands: design.strands.map((strand, index) => (
          index === 0 ? { ...strand, is_reference: true } : strand
        )),
      },
    })
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
    return {
      geometryCount: geometry.length,
      totalGeometryCount: state.currentGeometry.length,
      navHelixCount: navigationDesign(state).helices.length,
    }
  })
  expect(expected.geometryCount).toBeGreaterThan(0)
  expect(expected.geometryCount).toBeLessThan(expected.totalGeometryCount)

  const before = await page.evaluate(() => ({
    position: window.__NADOC_DBG__.camera.position.toArray(),
    target: window.__NADOC_DBG__.controls.target.toArray(),
    up: window.__NADOC_DBG__.camera.up.toArray(),
    quaternion: window.__NADOC_DBG__.camera.quaternion.toArray(),
  }))

  await page.locator('#left-tab-strip [data-tab="dynamics"]').click()
  await expect(page.locator('#tab-content-dynamics')).toBeVisible()

  const actual = await page.evaluate(() => ({
    simulationTabActive: window.__NADOC_DBG__.store.getState().simulationTabActive,
    position: window.__NADOC_DBG__.camera.position.toArray(),
    target: window.__NADOC_DBG__.controls.target.toArray(),
    up: window.__NADOC_DBG__.camera.up.toArray(),
    quaternion: window.__NADOC_DBG__.camera.quaternion.toArray(),
    navHelixCount: window.__NADOC_DBG__.msNav.probe()?.helices,
  }))
  expect(actual.simulationTabActive).toBe(true)
  expect(actual.navHelixCount).toBe(expected.navHelixCount)
  expect(actual.position).toEqual(before.position)
  expect(actual.target).toEqual(before.target)
  expect(actual.up).toEqual(before.up)
  expect(actual.quaternion).toEqual(before.quaternion)
})
