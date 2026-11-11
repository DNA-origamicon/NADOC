import { test, expect } from '@playwright/test'
import path from 'node:path'
import { trackConsoleErrors } from './helpers/scene_harness.js'

// Read-only legacy fixture with session-only animation metadata edits. No saves,
// exports or jobs. Isolated backend disables session caching; teardown cleans reports.
test('trajectory deletion paints before a slow response and restores the row after failure', async ({ page }) => {
  test.setTimeout(90000)
  const errors = trackConsoleErrors(page)
  await page.setViewportSize({ width: 1600, height: 1000 })
  await page.goto('/?doc=__e2e__keyframe-deletion')
  await page.waitForFunction(() => !!window.__nadocTest)
  await page.evaluate(async example => {
    const api = await import('/src/api/client.js')
    await api.loadDesign(example)
    document.getElementById('welcome-screen').classList.add('hidden')
    document.getElementById('left-panel').classList.remove('locked-hidden')
    for (const button of document.querySelectorAll('#left-tab-strip button')) button.disabled = false
    window.__leftSidebar.refresh()
  }, path.resolve(process.cwd(), '..', 'Examples', '2hb_xover_atoms_test.nadoc'))
  await page.locator('.left-tab-btn[data-tab="scene"]').click()
  await page.waitForFunction(() => window.__nadocTest.store.getState().currentDesign.animations?.length)
  await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    const id = window.__nadocTest.store.getState().currentDesign.animations[0].id
    await api.createKeyframe(id, { name: 'Delete trajectory', is_trajectory: true, trajectory_engine: 'namd', hold_duration_s: 1 })
    await api.createKeyframe(id, { name: 'Keep camera', hold_duration_s: 1 })
  })
  let release, received = false
  const gate = new Promise(resolve => { release = resolve })
  await page.route('**/api/design/animations/*/keyframes/*', async route => {
    if (route.request().method() !== 'DELETE') return route.continue()
    received = true
    await gate
    await route.continue()
  })
  const rows = page.locator('.anim-keyframe')
  await expect(rows).toHaveCount(2)
  await rows.first().getByTitle('Delete keyframe', { exact: true }).click()
  await expect(rows).toHaveCount(1, { timeout: 500 })
  await expect.poll(() => received).toBe(true)
  // The server has not acknowledged deletion, yet the row is already gone.
  expect(await page.evaluate(() => window.__nadocTest.store.getState().currentDesign.animations[0].keyframes.length)).toBe(2)
  await page.waitForTimeout(5500)
  await expect(page.locator('#op-progress')).not.toHaveClass(/visible/)
  await expect(rows).toHaveCount(1)
  const acknowledgement = page.waitForResponse(response => response.request().method() === 'DELETE' && response.url().includes('/keyframes/'))
  release()
  const response = await acknowledgement
  expect(response.url()).toContain('metadata_only=true')
  expect(Object.keys((await response.json()).design).sort()).toEqual(['animations', 'id'])
  await expect.poll(() => page.evaluate(() => window.__nadocTest.store.getState().currentDesign.animations[0].keyframes.length)).toBe(1)
  await page.unroute('**/api/design/animations/*/keyframes/*')
  // Explicit feature-seek refusal returns null through the normal API path, without a network error.
  await page.evaluate(() => window.__nadocTest.store.setState({ featureSeekPending: true }))
  await rows.first().getByTitle('Delete keyframe', { exact: true }).click()
  await expect(rows).toHaveCount(1)
  await expect(rows).toContainText('Keep camera')
  await page.evaluate(() => window.__nadocTest.store.setState({ featureSeekPending: false }))
  expect(errors, errors.join('\n')).toEqual([])
})
