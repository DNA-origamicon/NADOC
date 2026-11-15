import { existsSync } from 'node:fs'
import path from 'node:path'
import { test, expect } from '@playwright/test'

// Read-only local design diagnosis. Autosave is disabled; only the __e2e__ host
// is saved. Global teardown removes that host, revision store and bridge scratch;
// screenshots use Playwright's managed output directory.
test('saved two-base flexible connections retain visible beads', async ({ page }) => {
  test.setTimeout(240000)
  const fixture = path.resolve('../workspace/Assembly Tests/JJ_Hinge_AuNP_stacked_poly_FINAL_with_fluors.nadoc')
  test.skip(!existsSync(fixture), 'Local user design')
  await page.addInitScript(() => localStorage.setItem('nadoc:preferences:v1', JSON.stringify({ autosave: false })))
  await page.goto('/?doc=__e2e__flexible-visibility')
  await page.waitForFunction(() => !!window.__nadocTest?.store)
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name', '__e2e__flexible-visibility-host')
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.locator('#welcome-screen')).not.toBeVisible()
  await page.evaluate(async fixture => {
    const api = await import('/src/api/client.js')
    await api.loadDesign(fixture)
  }, fixture)
  const result = await page.evaluate(() => {
    const t = window.__nadocTest
    const arcs = { group: t.scene.getObjectByName('flexibleArcs') }
    const state = t.store.getState()
    return { representation: state.representation,
      connections: state.currentDesign.flexible_connections,
      visible: arcs.group.visible,
      meshes: arcs.group.children.map(m => ({ name:m.name, count:m.count, opacity:m.material.opacity })),
    }
  })
  expect(result.connections.length).toBeGreaterThan(0)
  expect(result.meshes.filter(m => m.name === 'flexSegmentBeads').every(m => m.count === 2 && m.opacity > 0)).toBe(true)
  expect(result.visible).toBe(true)
  expect(result.meshes.filter(m => m.name === 'flexSegmentBeads').length).toBe(result.connections.length)
})
